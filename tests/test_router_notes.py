"""Brief 30, decisions 1, 2, 7 and 8 (rules 2.43, Router notes): the notes file, its checks and its cap, `sr notes` and
`sr notes save`. The local file is each test's own (conftest points `notes.PATH` at the temp folder); the default is the
repo's tracked one. A secret- or key-shaped value is built at run time from pieces. Every value here is fake."""
import json
import os
import secrets as random_secrets
import stat

import pytest

from router import __main__ as cli
from router import notes, receipt, safety, settings

SIX = ("All agents", "Claude", "ChatGPT", "Grok", "Cursor", "Planner")
SET = ("## All agents\nUse metric units.\n\n## Claude\nKeep it short.\n\n## ChatGPT\n\n## Grok\nName the accounts.\n\n"
       "## Cursor\n\n## Planner\nA yes-or-no question goes to vote.\n")


def _key():
    return "to" + "ken: " + random_secrets.token_hex(8)  # a key shape, built now


# ---------- the default and the file (decision 1) ----------

def test_the_tracked_default_is_the_six_headings_with_one_blank_line_after_each_and_nothing_else():
    assert notes.DEFAULT_PATH.read_text() == "".join(f"## {h}\n\n" for h in SIX)
    found = notes.parse(notes.DEFAULT_PATH.read_text())
    assert found.problem is None and found.state == "blank" and set(found.sections) == {k for k, _ in notes.SECTIONS}


def test_while_the_local_file_is_missing_the_router_reads_the_default():
    assert not notes.PATH.exists()
    found = notes.read()
    assert found.default is True and found.state == "blank" and found.text == notes.DEFAULT_PATH.read_text()


def test_the_local_file_wins_once_it_is_there():
    notes.PATH.write_text(SET)
    found = notes.read()
    assert found.default is False and found.state == "set"
    assert found.sections["all_agents"] == "Use metric units." and found.sections["chatgpt"] == ""
    assert found.chars == {"all_agents": 17, "claude": 14, "chatgpt": 0, "grok": 18, "cursor": 0, "planner": 34}


def test_the_gitignore_keeps_the_local_file_out_and_the_default_in(real_git):
    root = safety.REPO_ROOT
    ignored = __import__("subprocess").run(["git", "-C", str(root), "check-ignore", "-q", "config/router-notes.md"])
    kept = __import__("subprocess").run(["git", "-C", str(root), "check-ignore", "-q", "config/router-notes.default.md"])
    assert ignored.returncode == 0 and kept.returncode == 1


# ---------- the format (decision 2) ----------

def test_sections_in_any_order_trailing_spaces_and_deeper_headings_as_text():
    text = "## Planner  \nsplit it\n\n\n## Claude\t\n\n### A heading of mine\nline\n\n## All agents\nall\n"
    found = notes.parse(text)
    assert found.problem is None
    assert found.sections == {"planner": "split it", "claude": "### A heading of mine\nline", "all_agents": "all"}


def test_blank_lines_at_both_ends_drop_and_a_blank_section_sends_nothing():
    found = notes.parse("## Claude\n\n\n  inside  \n\n\n## Grok\n\n\n")
    assert found.sections == {"claude": "  inside  ", "grok": ""}
    assert notes.part_for(found.sections, "grok") == ("", None)


@pytest.mark.parametrize("text,line,code", [
    ("hello\n## Claude\nx\n", 1, "notes_invalid"),                     # text before the first heading
    ("\n\n## Claude\nx\n## Somebody\ny\n", 5, "notes_invalid"),         # a `## ` line that isn't one of the six
    ("## Claude\nx\n## Grok\ny\n## Claude\nz\n", 5, "notes_invalid"),   # a heading twice
    ("## claude\nx\n", 1, "notes_invalid"),                             # exact headings only
    ("## \nx\n", 1, "notes_invalid"),
])
def test_each_invalid_shape_is_named_by_its_line_never_its_text(text, line, code):
    found = notes.parse(text)
    assert found.state == "invalid" and found.line == line and found.code == code
    assert f"line {line}" in found.problem
    for word in ("hello", "Somebody", "claude", "x\n"):
        assert word not in found.problem


def test_a_key_or_an_env_value_is_named_by_its_line_never_its_value():
    value = "fake-env-value-" + random_secrets.token_hex(6)
    found = notes.parse(f"## All agents\nfine\nmine is {value}\n", secrets=[value])
    assert (found.line, found.code) == (3, "notes_key") and value not in found.problem and "value from .env" in found.problem
    key = _key()
    found = notes.parse(f"## Claude\nok\n\n## Grok\n{key}\n")
    assert (found.line, found.code) == (5, "notes_key") and key not in found.problem and "looks like it holds a key" in found.problem


def test_past_the_cap_is_invalid_and_names_the_numbers(monkeypatch):
    monkeypatch.setattr(settings, "notes_setting", lambda name: (40, "test"))
    found = notes.parse("## Claude\n" + "x" * 40)
    assert found.state == "invalid" and found.line is None and "at most 40" in found.problem
    assert notes.parse("## Claude\n" + "x" * 20).state == "set"


def test_the_cap_and_the_project_cap_live_in_the_tracked_settings():
    doc = json.loads((safety.REPO_ROOT / "config" / "settings.json").read_text())
    assert doc["notes_max"] == 6000 and doc["project_notes_max"] == 20000
    assert settings.notes_setting("notes_max") == (6000, "config/settings.json")


def test_crlf_reads_as_lf():
    found = notes.parse("## Claude\r\nshort\r\n")
    assert found.sections == {"claude": "short"} and "\r" not in found.text


def test_a_file_that_is_not_utf8_is_invalid():
    notes.PATH.write_bytes(b"## Claude\n\xff\xfe\n")
    found = notes.read()
    assert found.state == "invalid" and "UTF-8" in found.problem


# ---------- sr notes and sr notes save (decision 8) ----------

def _run(argv):
    out = receipt.Receipt()
    code = cli._main(argv, "darwin", out)
    return code, out


def test_sr_notes_prints_the_default_with_counts_state_cap_and_hash():
    lines = []
    assert cli.cmd_notes([], out=lines.append) == 0
    shown = "\n".join(lines)
    assert "## All agents" in shown and "blank" in shown and notes.digest(notes.DEFAULT_PATH.read_text()) in shown
    assert "6,000" in shown


def test_sr_notes_json_gives_the_text_counts_and_hash():
    notes.PATH.write_text(SET)
    code, out = _run(["notes", "--json"])
    assert code == 0
    doc = out.document
    assert doc["notes"]["text"] == SET and doc["notes"]["state"] == "set" and doc["notes"]["hash"] == notes.digest(SET)
    assert doc["notes"]["sections"]["grok"] == 18 and doc["notes"]["max"] == 6000
    assert doc["notes"]["grok"] == {"share": 35, "limit": settings.grok_prompt_limit()[0], "line": notes.GROK_SHARE_LINE}


def test_save_writes_the_whole_file_mode_600_and_prints_the_counts():
    code, out = _run(["notes", "save", "--json", "--", SET])
    assert code == 0, out.message
    assert notes.PATH.read_text() == SET and stat.S_IMODE(os.stat(notes.PATH).st_mode) == 0o600
    assert out.extra_any == {} and out.extra["notes"]["state"] == "set" and out.extra["notes"]["hash"] == notes.digest(SET)
    assert "Saved the router notes" in out.message


@pytest.mark.parametrize("text,code_word", [
    ("zebra\n## Claude\nx\n", "notes_invalid"),
    ("## Claude\n" + "to" + "ken: " + "0123456789abcdef\n", "notes_key"),
])
def test_save_refuses_with_nothing_written_naming_the_line(text, code_word):
    notes.PATH.write_text(SET)
    code, out = _run(["notes", "save", "--json", "--", text])
    assert code == 2 and out.code == code_word and "line" in out.message
    assert notes.PATH.read_text() == SET  # nothing written
    assert "0123456789abcdef" not in out.message and "zebra" not in out.message


def test_expect_refuses_a_file_changed_since():
    code, out = _run(["notes", "save", "--expect", notes.digest(notes.DEFAULT_PATH.read_text()), "--json", "--", SET])
    assert code == 0, out.message  # the default's hash while there is no file
    code, out = _run(["notes", "save", "--expect", notes.digest("something else"), "--json", "--", "## Claude\nnew\n"])
    assert code == 2 and out.code == "notes_changed" and notes.PATH.read_text() == SET


def test_a_failure_part_way_leaves_the_old_file(monkeypatch):
    notes.PATH.write_text(SET)

    def boom(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        notes.save("## Claude\nnew\n")
    assert notes.PATH.read_text() == SET and [p.name for p in notes.PATH.parent.glob(".router-notes-*")] == []


def test_save_holds_the_notes_lock(monkeypatch):
    held = []

    class Lock:
        def __init__(self, name, **kw):
            held.append(name)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False
    monkeypatch.setattr(notes.locks, "held", Lock)
    notes.save(SET)
    assert held == ["notes"]


def test_the_text_is_one_argument_after_the_double_dash():
    code, out = _run(["notes", "save", "--json", "--"])
    assert code == 2 and out.code == "usage"
    code, out = _run(["notes", "save", "--json", "--", "## Claude\na", "extra"])
    assert code == 2 and out.code == "usage"
    code, out = _run(["notes", "save", "--json", "--", "## Claude\n--json -h\n"])
    assert code == 0 and notes.PATH.read_text() == "## Claude\n--json -h\n"  # text, never flags
