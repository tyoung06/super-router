"""Phase D of build brief 7: the messages. The stop line names `sr resume <n>` and the substitute or
says why not; `sr show` names a resumed call and the call it replaces, `--history` marks the stopped
row `plan limit`; `sr log` marks a resumed task; the status page follows the rows. Fake agents only."""
from router import __main__ as cli
from router import log, page
from tests.test_collab import AMENDED, DELIVERABLE, EDITED, LOADED, PLAN
from tests.test_collab import TASK as COLLAB_TASK
from tests.test_loop import Scripted
from tests.test_relay import ROSTER, TASK, Chat
from tests.test_resume_run import QUICK, WRITING, _relay, _resume, _route, claude_limit, codex_limit, conn  # noqa: F401


def _show(conn, *words, history=False, stages=False):
    lines = []
    code = cli.cmd_show(conn=conn, words=list(words), history=history, stages=stages, roster=ROSTER, presets=LOADED,
                        out=lines.append)
    return code, "\n".join(lines)


def _log(conn):
    lines = []
    cli.cmd_log(conn=conn, out=lines.append)
    return lines


def test_the_stop_line_names_the_command_and_the_substitute(conn):
    code, out, row = _route(conn, WRITING, worker=Scripted(claude_limit()))
    assert out.splitlines()[-1] == "Plan limit on claude. Run: sr resume 1  (continues with chatgpt)"


def test_the_stop_line_says_why_an_override_task_cannot_be_resumed(conn):
    code, out, row = _route(conn, WRITING, worker=Scripted(claude_limit()), task="@claude write two lines")
    assert out.splitlines()[-1].startswith("Plan limit on claude. Not resumable: an override task is never resumed")


def test_sr_show_on_a_stopped_task_repeats_the_stop_line(conn):
    _route(conn, QUICK, worker=Scripted(claude_limit()))
    code, out = _show(conn, "1")
    assert code == 0 and "Plan limit on claude. Run: sr resume 1  (continues with chatgpt)" in out


def test_sr_show_names_the_resumed_call_and_the_call_it_replaces(conn):
    _, _, row = _route(conn, WRITING, worker=Scripted(claude_limit()))
    _resume(conn, row, worker=Scripted("PASS"), chatgpt=Chat("two lines by chatgpt"))
    code, out = _show(conn, "1")
    tid = row["task_id"]
    assert f"Resumed: the first call by chatgpt — replaces call {tid} (claude stopped on its plan limit)." in out
    assert "Doer: chatgpt" in out and "Checker: claude" in out and "Plan limit on" not in out


def test_history_marks_the_stopped_row_plan_limit_and_the_resumed_row(conn):
    _, _, row = _route(conn, WRITING, worker=Scripted(claude_limit()))
    _resume(conn, row, worker=Scripted("PASS"), chatgpt=Chat("two lines by chatgpt"))
    code, out = _show(conn, "1", history=True)
    tid = row["task_id"]
    heads = [line for line in out.splitlines() if line[:2] in ("1.", "2.", "3.")]
    assert heads[0].startswith("1. do by claude: failed, plan limit, ")
    assert heads[1].startswith(f"2. do by chatgpt: done, resumed — replaces call {tid}, ")
    assert heads[2].startswith("3. check by claude: done PASS, ")


def test_a_relay_stage_line_says_resumed(conn):
    _, _, row = _relay(conn, "research-build", TASK, worker=Scripted(claude_limit()), chatgpt=Chat())
    _resume(conn, row, worker=Scripted("PASS"), chatgpt=Chat("a built summary"))
    code, out = _show(conn, "1")
    assert "  2. build by chatgpt: resumed, passed" in out
    assert f"Resumed: stage 2 (build) by chatgpt — replaces call {row['task_id']}-s2" in out


def test_sr_show_on_a_refused_check_stage_says_why_not(conn):
    _relay(conn, "collab", COLLAB_TASK, worker=Scripted(PLAN, DELIVERABLE),
           chatgpt=Chat(AMENDED, codex_limit()))
    code, out = _show(conn, "1")
    assert "Plan limit on chatgpt. Not resumable: claude made stage 3" in out


def test_sr_log_marks_a_resumed_task(conn):
    _, _, row = _route(conn, WRITING, worker=Scripted(claude_limit()))
    _route(conn, QUICK, worker=Scripted("fine"))
    _resume(conn, row, worker=Scripted("PASS"), chatgpt=Chat("two lines by chatgpt"))
    lines = _log(conn)
    first = next(line for line in lines if line.lstrip().startswith("1 "))
    second = next(line for line in lines if line.lstrip().startswith("2 "))
    assert "(resumed) " in first and "(resumed)" not in second


def test_the_page_puts_a_resumed_chains_check_stage_on_the_other_builders_card(conn):
    _, _, row = _relay(conn, "collab", COLLAB_TASK, worker=Scripted(PLAN, claude_limit()), chatgpt=Chat(AMENDED))
    # resume, but stop before stage 4 runs: the substitute's stage 3 is logged and the task is open
    log.reopen_for_resume(conn, row["task_id"], agents=ROSTER.names, agent="chatgpt", checker="claude",
                          check_state="pending")
    log.add_call(conn, f"{row['task_id']}-s3-resume", row["task_id"], "stage", "chatgpt", status="done",
                 text=DELIVERABLE, stage=3, role="execute", resume_of=f"{row['task_id']}-s3")
    open_row = log.get_task(conn, row["task_id"])
    from router import jsonview  # brief 21, B4: the page reads `working` from sr log --json
    assert jsonview.working(open_row, log.calls_for(conn, row["task_id"]), LOADED.presets["collab"]) == {
        "agent": "claude", "doing": "stage 4 of 4 (edit)"}
    assert EDITED  # (stage 4 itself is covered in test_resume_run)
