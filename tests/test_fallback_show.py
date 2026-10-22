"""Build brief 10, phase C (rules v2.17, Fallback): the messages. A task that ends with its check failed
twice ends with `Run: sr fallback <n>  (<agent> redoes it; <agent> checks)` or `No fallback: <reason>`;
`sr show` names a fallback row and the call it replaces, and after a redo also failed twice prints both
attempts, original first; `sr log` marks a task that fell back; the status page needs no change. Fake
agents only; every value here is fake."""
import pytest

from router import __main__ as cli
from router import jsonview, log, page
from tests.test_collab import AMENDED, DELIVERABLE, EDITED, PLAN
from tests.test_collab import TASK as COLLAB_TASK
from tests.test_fallback_run import (CHECK1, FINAL, FINAL_LIST, FIRST, FIXED, REDO, _double_fail_route, _fallback,
                                     _double_fail_research)
from tests.test_loop import Scripted, Webhook
from tests.test_relay import GOOD_NOTE, ROSTER, SECRET, Chat, RelayHook
from tests.test_resume_run import LOADED, WRITING, _relay, _route

FAILED_EDIT = EDITED.replace("## Unresolved\nnone", "## Unresolved\n- the error cases are missing")


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _show(conn, n, **kw):
    lines = []
    code = cli.cmd_show(conn=conn, words=[str(n)], secrets=[SECRET], roster=ROSTER, presets=LOADED, out=lines.append,
                        **kw)
    return code, lines


# ---------- the line that ends a double fail ----------

def test_a_routed_double_fail_ends_with_the_fallback_command(conn):
    code, out, row = _route(conn, WRITING, worker=Scripted(FIRST, FIXED), chatgpt=Chat(CHECK1, FINAL))
    assert out.splitlines()[-1] == f"Run: sr fallback {row['n']}  (chatgpt redoes it; claude checks)"


def test_a_double_fail_checked_by_grok_says_why_there_is_no_fallback(conn):
    bulk = {"status": "ok", "label": "bulk_text", "confidence": 0.95, "needs_split": 0.1, "tokens": 0}
    code, out, row = _route(conn, bulk, worker=Scripted(FIRST, FIXED), hook=Webhook(c1=CHECK1, c2=FINAL))
    assert (row["checker"], row["check_state"]) == ("grok", "failed"), out
    assert out.splitlines()[-1] == "No fallback: checker is grok: cannot redo"


def test_a_research_build_double_fail_ends_with_the_fallback_command(conn):
    row = _double_fail_research(conn, RelayHook(s1=GOOD_NOTE))
    code, lines = _show(conn, row["n"])
    assert lines[-1] == f"Run: sr fallback {row['n']}  (chatgpt redoes it; claude checks)"


def test_a_collab_check_stage_with_unresolved_items_ends_with_the_fallback_command(conn):
    code, out, row = _relay(conn, "collab", COLLAB_TASK, worker=Scripted(PLAN, DELIVERABLE),
                            chatgpt=Chat(AMENDED, FAILED_EDIT))
    assert out.splitlines()[-1] == f"Run: sr fallback {row['n']}  (chatgpt redoes it; claude checks)"


def test_no_fallback_line_after_a_pass(conn):
    code, out, row = _route(conn, WRITING, worker=Scripted(FIRST), chatgpt=Chat("PASS"))
    assert "fallback" not in out


def test_a_redo_that_fails_twice_says_there_is_no_second_fallback(conn):
    row = _double_fail_route(conn)
    code, out, *_ = _fallback(conn, row, chatgpt=Chat(REDO, "REDO-FIXED"),
                              worker=Scripted("FIX\n- still flat", "FIX\n- now too short"))
    assert "No fallback: already fell back once" in out


# ---------- sr show and --history ----------

def test_sr_show_names_the_fallback_row_and_the_call_it_replaces(conn):
    row = _double_fail_route(conn)
    _fallback(conn, row, chatgpt=Chat(REDO), worker=Scripted("PASS"))
    code, lines = _show(conn, row["n"])
    tid = row["task_id"]
    assert (f"Fallback: the first call by chatgpt — replaces call {tid} (claude's result failed its check "
            "twice).") in lines
    assert REDO in lines and "CHECKED: passed." in lines
    assert any(line.startswith("Doer: chatgpt") and "Checker: claude" in line for line in lines)
    assert not any(line.startswith("Run: sr fallback") for line in lines)


def test_sr_show_history_marks_the_fallback_row(conn):
    row = _double_fail_route(conn)
    _fallback(conn, row, chatgpt=Chat(REDO), worker=Scripted("PASS"))
    code, lines = _show(conn, row["n"], history=True)
    heads = [line for line in lines if line[:2] in ("5.", "6.")]
    assert heads[0].startswith(f"5. do by chatgpt: done, fallback — replaces call {row['task_id']}, ")
    assert heads[1].startswith("6. check by claude: done PASS")
    assert FIXED in "\n".join(lines)  # the original result stays, shown on request


def test_sr_show_after_a_second_double_fail_prints_both_attempts_original_first(conn):
    row = _double_fail_route(conn)
    _fallback(conn, row, chatgpt=Chat(REDO, "REDO-FIXED-x74"), worker=Scripted("FIX\n- still flat", "FIX\n- now too short"))
    code, lines = _show(conn, row["n"])
    text = "\n".join(lines)
    tail = text[text.index("Both attempts failed their checks twice."):]
    order = [tail.index(s) for s in ("Original result (claude):", FIXED, "Its final fix list (chatgpt):", FINAL_LIST,
                                     "Redo (chatgpt):", "REDO-FIXED-x74", "Its final fix list (claude):", "- now too short")]
    assert order == sorted(order)
    assert lines[-1] == "No fallback: already fell back once"


def test_a_stopped_fallback_shows_and_does_not_count(conn):
    from tests.test_resume_run import codex_limit
    row = _double_fail_route(conn)
    _fallback(conn, row, chatgpt=Chat(codex_limit()))
    code, lines = _show(conn, row["n"])
    assert f"Fallback: the first call by chatgpt stopped (plan limit) — it doesn't count." in lines
    assert lines[-1] == f"Plan limit on chatgpt. Not resumable: fallback. Run sr fallback {row['n']} again when it lifts."


def test_a_relay_stage_line_names_the_fallback(conn):
    hook = RelayHook(s1=GOOD_NOTE)
    row = _double_fail_research(conn, hook)
    _fallback(conn, row, chatgpt=Chat(REDO), worker=Scripted("PASS"), hook=hook)
    code, lines = _show(conn, row["n"])
    assert "  1. research by grok: passed" in lines and "  2. build by chatgpt: fallback, passed" in lines


# ---------- sr log and the page ----------

def test_sr_log_marks_a_task_that_fell_back(conn):
    row = _double_fail_route(conn)
    lines = []
    cli.cmd_log(conn=conn, out=lines.append)
    assert "(fallback)" not in lines[1]
    _fallback(conn, row, chatgpt=Chat(REDO), worker=Scripted("PASS"))
    lines = []
    cli.cmd_log(conn=conn, out=lines.append)
    assert "(fallback) write two lines" in lines[1]


def test_a_stopped_fallback_is_not_marked_in_sr_log(conn):
    from tests.test_resume_run import codex_limit
    row = _double_fail_route(conn)
    _fallback(conn, row, chatgpt=Chat(codex_limit()))
    lines = []
    cli.cmd_log(conn=conn, out=lines.append)
    assert "(fallback)" not in lines[1]


def test_the_status_page_needs_no_change(conn):
    """Brief 21, B4: the page reads `sr log --json` (jsonview.log_view): the redo's row reads as any delivered task."""
    row = _double_fail_route(conn)
    _fallback(conn, row, chatgpt=Chat(REDO), worker=Scripted("PASS"))
    rows = jsonview.log_view(conn, log.recent_tasks(conn), limit=20, loaded=LOADED)["tasks"]
    assert (rows[0]["status"], rows[0]["agent"], rows[0]["checker"], rows[0]["check_state"], rows[0]["result"],
            rows[0]["outcome"], rows[0]["fallback"]["ok"]) == ("done", "chatgpt", "claude", "passed", REDO, "passed", False)
