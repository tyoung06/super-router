"""Untrusted task and result text is made safe before it is printed. The log keeps the raw redacted text."""
import pytest

from router import __main__ as cli
from router import log, safety
from tests.helpers import add_row, shipped_roster, fake_label

MARK = "�"
SECRET = "FAKE-KEY-123"
CONFIG = {"GROK_WEBHOOK_URL": "https://example.invalid/hook", "GROK_WEBHOOK_KEY": SECRET}
ROSTER = shipped_roster()


@pytest.mark.parametrize("raw, shown", [
    ("\x1b[2Jhi", MARK + "[2Jhi"),                    # clear-screen escape
    ("\x1b]52;c;ZXZpbA==\x07ok", MARK + "]52;c;ZXZpbA==" + MARK + "ok"),  # clipboard write
    ("safe\rEVIL", "safe\nEVIL"),                       # carriage-return overwrite
    ("a\r\nb", "a\nb"),
    ("x‮evil", "x" + MARK + "evil"),               # right-to-left override
    ("x\u009by", "x" + MARK + "y"),                     # C1 control
    ("x\x7fy", "x" + MARK + "y"),                       # DEL
    ("line1\n\tline2", "line1\n\tline2"),               # newlines and tabs stay
    ("café 🚀", "café 🚀"),                             # normal text stays
])
def test_for_terminal_replaces_control_and_bidi_characters(raw, shown):
    assert safety.for_terminal(raw) == shown


@pytest.mark.parametrize("ch", ["؜", "‎", "‏", "‪", "‫", "‬", "‭",
                                "‮", "⁦", "⁧", "⁨", "⁩"])
def test_for_terminal_replaces_every_bidi_control(ch):
    assert safety.for_terminal("a" + ch + "b") == "a" + MARK + "b"


@pytest.mark.parametrize("raw, shown", [("a\nb", "a" + MARK + "b"), ("a\tb", "a" + MARK + "b"), ("a\r\nb", "a" + MARK + "b"),
                                        ("a\u202eb", "a" + MARK + "b"), ("plain name.pdf", "plain name.pdf")])
def test_one_line_marks_a_newline_or_tab_as_well(raw, shown):
    """A file name inside a message stays on one line: for_terminal keeps newlines and tabs, one_line marks them."""
    assert safety.one_line(raw) == shown


def test_for_terminal_handles_none():
    assert safety.for_terminal(None) == ""


def test_for_terminal_redacts_and_never_glues_a_split_secret():
    assert SECRET not in safety.for_terminal("x " + SECRET + " y", [SECRET])
    shown = safety.for_terminal("FAKE-\x1bKEY-123", [SECRET])
    assert SECRET not in shown and MARK in shown


# ---------- every existing print path uses it ----------

@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _no_controls(text):
    return "\x1b" not in text and "‮" not in text and "\x07" not in text


def test_route_prints_a_safe_answer_but_logs_the_raw_one(conn):
    lines = []
    code = cli.cmd_route(
        "@claude hi", conn=conn, config=CONFIG, roster=ROSTER, label=fake_label(), environ={}, settings_paths=[],
        post=None, worker=lambda t: "\x1b[2Jboo‮",
        out=lines.append,
    )
    assert code == 0
    shown = "\n".join(lines)
    assert _no_controls(shown) and MARK in shown
    assert log.recent_tasks(conn)[0]["result"] == "\x1b[2Jboo‮"


def test_route_error_text_is_printed_safely(conn):
    def worker(task):
        raise safety.SafeError("bad \x1b[31mred")
    lines = []
    cli.cmd_route("@claude hi", conn=conn, config=CONFIG, roster=ROSTER, label=fake_label(), environ={}, settings_paths=[],
                  post=None, worker=worker, out=lines.append)
    assert _no_controls("\n".join(lines))


def test_log_prints_safe_one_liners(conn):
    add_row(conn, "sr-1", "task \x1b]0;title\x07 ‮rev", "claude", "best")
    log.set_done(conn, "sr-1", "result \x1b[2J")
    lines = []
    assert cli.cmd_log(conn=conn, out=lines.append) == 0
    assert _no_controls("\n".join(lines))


def test_check_prints_inbox_errors_safely(conn):
    add_row(conn, "sr-1", "t", "grok", "best")
    log.set_sent(conn, "sr-1", "uuid")

    def fetch():
        raise safety.SafeError("gh failed: \x1b[2J")
    lines = []
    cli.cmd_check(conn=conn, config=CONFIG, fetch=fetch, close=None, out=lines.append)
    assert _no_controls("\n".join(lines))
