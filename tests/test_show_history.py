"""What the owner sees after the loop: `sr show` with the check line and note, `sr show --history`
with every call, `sr log`'s check column, and the status page's new fields and badges."""
from pathlib import Path

import pytest

from router import __main__ as cli
from router import jsonview, log, page
from tests.helpers import ALL_AGENTS, JEV_OK, add_row, shipped_roster

INDEX = Path(__file__).resolve().parent.parent / "static" / "index.html"
TASK = "find sources on the new EU AI rules"
RESULT = "The EU AI Act applies from 2026. Source: https://example.org/ai-act"
FIXED = "The EU AI Act applies in stages from 2 Feb 2025. Source: https://example.org/ai-act"


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _web_task(conn, task_id="sr-1"):
    log.add_task(conn, task_id, TASK, "cli", {**JEV_OK, "label": "web_research"})
    log.set_route(conn, task_id, agents=ALL_AGENTS, agent="grok", route_reason="interim", skill="web_research",
                  skill_source="jev", checker="claude", check_state="pending")
    return task_id


def _fixed_and_passed(conn, task_id="sr-1"):
    """A task that went do -> FIX -> fix -> PASS (ending 6)."""
    _web_task(conn, task_id)
    log.set_sent(conn, task_id, "uuid-do")
    log.finish_call(conn, task_id, "done", text=RESULT, url="https://github.com/x/y/issues/1")
    log.add_call(conn, f"{task_id}-c1", task_id, "check", "claude", status="done",
                 text="FIX\n1. Give the exact date.", verdict="FIX")
    log.add_call(conn, f"{task_id}-f1", task_id, "fix", "grok", run_uuid="uuid-fix")
    log.finish_call(conn, f"{task_id}-f1", "done", text=FIXED, url="https://github.com/x/y/issues/2")
    log.add_call(conn, f"{task_id}-c2", task_id, "recheck", "claude", status="done", text="PASS", verdict="PASS")
    log.set_done(conn, task_id, FIXED, "https://github.com/x/y/issues/1", check_state="fixed")
    return task_id


def _show(conn, *words, history=False):
    lines = []
    code = cli.cmd_show(conn=conn, words=list(words), history=history, out=lines.append)
    return code, "\n".join(lines)


# ---------- sr show ----------

def test_show_prints_the_check_line_and_the_note_and_the_furthest_result(conn):
    _web_task(conn)
    log.set_sent(conn, "sr-1", "u")
    log.finish_call(conn, "sr-1", "done", text=RESULT)
    log.add_call(conn, "sr-1-c1", "sr-1", "check", "claude", status="failed", text="claude exited 1")
    log.set_done(conn, "sr-1", RESULT, check_state="unchecked", check_note="check round by claude didn't run: claude exited 1")
    code, out = _show(conn, "1")
    assert code == 0
    assert "Check: unchecked" in out and "Note: check round by claude didn't run: claude exited 1" in out
    assert RESULT in out and "CHECK ROUND FAILED: claude, claude exited 1. This result is unchecked." in out


def test_show_after_a_fix_prints_the_fixed_result_only(conn):
    _fixed_and_passed(conn)
    code, out = _show(conn, "1")
    assert code == 0
    assert FIXED in out and RESULT not in out and "Give the exact date" not in out
    assert "CHECKED (sanity check only): passed after one fix." in out and "--history" in out


def test_show_on_an_open_task_says_to_run_sr_check(conn):
    _web_task(conn)
    log.set_sent(conn, "sr-1", "u")
    code, out = _show(conn, "1")
    assert code == 0 and "no result yet" in out and "sr check" in out


# ---------- sr show --history ----------

def test_history_lists_every_call_in_order_with_the_original_and_the_fix_list(conn):
    _fixed_and_passed(conn)
    code, out = _show(conn, "1", history=True)
    assert code == 0
    import re
    heads = [line for line in out.splitlines() if re.match(r"\d+\. (do|check|fix|recheck) by ", line)]
    assert len(heads) == 4
    assert "do by grok" in heads[0] and "done" in heads[0] and "issues/1" in heads[0]
    assert "check by claude" in heads[1] and "FIX" in heads[1]
    assert "fix by grok" in heads[2] and "issues/2" in heads[2]
    assert "recheck by claude" in heads[3] and "PASS" in heads[3]
    assert RESULT in out and "1. Give the exact date." in out and FIXED in out
    assert out.index(RESULT) < out.index("Give the exact date") < out.index(FIXED)


def test_history_prints_call_text_safely(conn):
    _web_task(conn)
    log.set_sent(conn, "sr-1", "u")
    log.finish_call(conn, "sr-1", "done", text="evil \x1b[2J text FAKE-KEY-123")
    log.set_done(conn, "sr-1", "evil \x1b[2J text FAKE-KEY-123", check_state="unchecked")
    lines = []
    cli.cmd_show(conn=conn, words=["1"], history=True, secrets=["FAKE-KEY-123"], out=lines.append)
    out = "\n".join(lines)
    assert "\x1b" not in out and "FAKE-KEY-123" not in out and "[REDACTED]" in out


def test_history_on_an_open_task_says_to_run_sr_check_and_shows_no_calls(conn):
    _web_task(conn)
    log.set_sent(conn, "sr-1", "u")
    log.finish_call(conn, "sr-1", "done", text=RESULT)
    code, out = _show(conn, "1", history=True)
    assert code == 1 and "sr check" in out and RESULT not in out


def test_history_on_a_task_from_before_this_build_says_so(conn):
    add_row(conn, "sr-old", task="an old task", agent="grok")
    log.set_done(conn, "sr-old", "an old result", check_state="unchecked")
    code, out = _show(conn, "1", history=True)
    assert code == 0 and "no call history" in out and "an old result" not in out


def test_history_on_a_missing_task(conn):
    code, out = _show(conn, "9", history=True)
    assert code == 1 and "No task #9" in out


def test_main_parses_show_history(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "cmd_show", lambda **kw: seen.update(kw) or 0)
    assert cli.main(["show", "3", "--history"], platform="darwin") == 0
    assert seen["words"] == ["3"] and seen["history"] is True
    assert cli.main(["show", "3"], platform="darwin") == 0
    assert seen["history"] is False


# ---------- sr log ----------

def test_log_shows_the_new_check_states(conn):
    _fixed_and_passed(conn)
    lines = []
    cli.cmd_log(conn=conn, out=lines.append)
    assert "fixed" in lines[1] and FIXED[:20] in lines[1]


# ---------- the status page ----------

def test_page_tasks_json_has_check_note(conn):
    _web_task(conn)
    log.set_done(conn, "sr-1", RESULT, check_state="unchecked", check_note="checker chatgpt isn't live yet")
    row = jsonview.task_view(conn, log.recent_tasks(conn)[0])  # brief 21, B4: the page reads sr log --json
    assert row["check_note"] == "checker chatgpt isn't live yet" and row["check_state"] == "unchecked"
    assert row["outcome"] == "unchecked"



def test_exit_code_5_and_history_are_documented():
    assert "5 " in cli.__doc__ and "not passed" in cli.__doc__.lower()
    roster = shipped_roster()
    parser = cli._parser(roster)
    assert "--history" in parser.format_help() or "--history" in parser._subparsers._group_actions[0].choices["show"].format_help()
