"""The '#' column in `log` and the `show` command."""
import pytest

from router import __main__ as cli
from router import log
from tests.helpers import add_row

SECRET = "FAKE-KEY-123"


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _add(conn, task_id, task, status="done", result="an answer", agent="claude", url=None):
    add_row(conn, task_id, task, agent, "best")
    if status == "sent":
        log.set_sent(conn, task_id, "uuid")
    elif status == "done":
        log.set_done(conn, task_id, result, url)
    elif status == "failed":
        log.set_failed(conn, task_id, result)


def _show(conn, *words):
    lines = []
    code = cli.cmd_show(conn=conn, words=list(words), secrets=[SECRET], out=lines.append)
    return code, "\n".join(lines)


def test_log_shows_a_number_column(conn):
    _add(conn, "sr-a", "first task")
    _add(conn, "sr-b", "second task")
    lines = []
    cli.cmd_log(conn=conn, out=lines.append)
    assert lines[0].lstrip().startswith("#")
    assert lines[1].split()[0] == "2" and "sr-b" in lines[1]
    assert lines[2].split()[0] == "1" and "sr-a" in lines[2]


def test_show_with_no_words_prints_the_newest_task_in_full(conn):
    _add(conn, "sr-a", "older task")
    _add(conn, "sr-b", "newer task", result="line one\nline two")
    code, out = _show(conn)
    assert code == 0
    assert "#2" in out and "sr-b" in out and "newer task" in out
    assert "line one\nline two" in out


@pytest.mark.parametrize("ref", ["1", "#1", "sr-a"])
def test_show_by_number_or_task_id(conn, ref):
    _add(conn, "sr-a", "older task")
    _add(conn, "sr-b", "newer task")
    code, out = _show(conn, ref)
    assert code == 0 and "sr-a" in out and "older task" in out


def test_show_by_words_finds_the_newest_match_ignoring_case(conn):
    _add(conn, "sr-a", "What is Tesla stock doing")
    _add(conn, "sr-b", "Something else")
    _add(conn, "sr-c", "tesla STOCK again")
    code, out = _show(conn, "Tesla", "stock")
    assert code == 0 and "sr-c" in out


def test_show_missing_number_does_not_fall_back_to_a_word_search(conn):
    _add(conn, "sr-a", "the year 2026 plan")
    code, out = _show(conn, "2026")
    assert code == 1 and "No task #2026" in out and "sr-a" not in out


@pytest.mark.parametrize("ref", ["99999999999999999999", "²", "50%", "a_b"])
def test_show_odd_input_never_crashes(conn, ref):
    _add(conn, "sr-a", "plain task")
    code, out = _show(conn, ref)
    assert code == 1 and "No task" in out


def test_show_states_what_kind_of_result_it_is(conn):
    _add(conn, "sr-s", "waiting task", status="sent", agent="grok")
    _add(conn, "sr-f", "broken task", status="failed", result="webhook returned HTTP 500")
    _add(conn, "sr-e", "empty task", result="")
    assert "no result yet" in _show(conn, "sr-s")[1]
    assert "Error:" in _show(conn, "sr-f")[1] and "HTTP 500" in _show(conn, "sr-f")[1]
    assert "(empty result)" in _show(conn, "sr-e")[1]


def test_show_prints_only_https_issue_links_and_safe_text(conn):
    _add(conn, "sr-g", "grok task", agent="grok", result="ok \x1b[2J " + SECRET, url="https://github.com/x/y/issues/1")
    _add(conn, "sr-h", "bad link", agent="grok", url="javascript:alert(1)")
    out_g = _show(conn, "sr-g")[1]
    assert "https://github.com/x/y/issues/1" in out_g
    assert "\x1b" not in out_g and SECRET not in out_g
    assert "javascript:" not in _show(conn, "sr-h")[1]


def test_show_on_an_empty_log(conn):
    code, out = _show(conn)
    assert code == 1 and "No tasks in the log yet" in out
