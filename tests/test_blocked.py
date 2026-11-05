"""Brief 29.1 (decision 17, the checker's fix 6): a check that answers BLOCKED ends the task with no fix round: status
failed, check_state, outcome and reason_code `blocked`, exit 5, the doer's result kept and the note naming what it needed.
No fallback (the redo would get the same inputs), no resume, nothing stored in memory. On a project its handoff line reads
`blocked: <what it needed>`; a blocked file-mode task keeps its change for Discard only; a blocked piece reads blocked, so
Skip goes on; a re-check may answer BLOCKED too. Fake agents, real git in temp folders; every value fake."""
from router import __main__ as cli
from router import checking, jsonview, log, projects, split, state
from tests.fake_hindsight import FakeHindsight
from tests.test_chat_intake import _route, conn  # noqa: F401 (the fixture)
from tests.test_context import HANDOFF_TEXT, SECTION, project  # noqa: F401 (the fixture)
from tests.test_filemode_flow import BUILD, CopyWorker, route, runner  # noqa: F401
from tests.test_filemode_flow import project as garden  # noqa: F401
from tests.test_landing import land
from tests.test_loop import Scripted
from tests.test_relay import Chat

NEEDED = "the notes from yesterday's meeting"
BLOCKED = f"BLOCKED: {NEEDED}"


def test_a_blocked_check_ends_the_task_failed_with_no_fix_round(conn):
    code, out, row, _ = _route(conn, worker=Scripted("I need your notes to write this."), chatgpt=Chat(BLOCKED))
    assert code == 5, out
    assert (row["status"], row["check_state"], row["reason_code"]) == ("failed", "blocked", "blocked")
    assert row["result"] == "I need your notes to write this." and row["check_note"] == f"blocked: {NEEDED}"
    assert [c["kind"] for c in log.calls_for(conn, row["task_id"])] == ["do", "check"]  # no fix round
    assert f"BLOCKED: {NEEDED}." in out and "Send the task again with it." in out
    found = state.of(row, log.calls_for(conn, row["task_id"]))
    assert (found.waiting_on, found.outcome) == (None, "blocked")
    assert checking.ENDINGS[9] == ("blocked", 5)


def test_the_json_says_blocked_and_offers_no_rescue(conn):
    _, _, row, _ = _route(conn, worker=Scripted("I need your notes."), chatgpt=Chat(BLOCKED))
    view = jsonview.task_view(conn, row)
    assert (view["outcome"], view["reason_code"], view["check_state"]) == ("blocked", "blocked", "blocked")
    assert view["fallback"]["ok"] is False and view["resume"]["ok"] is False and view["land_anyway"] is False
    check = jsonview.show_view(conn, row)["calls"][1]
    assert (check["said"], check["verdict"], check["blocked"], check["items"]) == ("BLOCKED", "BLOCKED", NEEDED, [])


def test_sr_fallback_and_sr_resume_refuse_a_blocked_task(conn):
    from tests.test_fallback_run import _fallback
    _, _, row, _ = _route(conn, worker=Scripted("I need your notes."), chatgpt=Chat(BLOCKED))
    code, out, *_ = _fallback(conn, row)
    assert code == 2 and "can't fall back" in out
    lines = []
    from tests.test_resume_run import LOADED, CONFIG, ROSTER
    assert cli.cmd_resume([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                          settings_paths=[], post=None, worker=Scripted(), out=lines.append) == 2
    assert log.get_task(conn, row["task_id"])["status"] == "failed"


def test_a_blocked_task_is_never_stored_in_memory(conn):
    fake = FakeHindsight(results=[])
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("I need your notes."), chatgpt=Chat(BLOCKED),
                               hindsight=fake.client)
    assert code == 5 and row["check_state"] == "blocked"
    assert fake.retains == []


def test_a_blocked_recheck_ends_blocked_too(conn):
    code, out, row, _ = _route(conn, worker=Scripted("Draft one.", "Draft two."),
                               chatgpt=Chat("FIX\n1. [must] Name the client.", "BLOCKED: the client's name"))
    assert code == 5 and (row["status"], row["check_state"]) == ("failed", "blocked")
    assert row["result"] == "Draft two." and row["check_note"] == "blocked: the client's name"
    assert [c["kind"] for c in log.calls_for(conn, row["task_id"])] == ["do", "check", "fix", "recheck"]


def test_on_a_project_the_handoff_line_reads_blocked(project, conn):
    code, out, row, _ = _route(conn, project="demo", worker=Scripted("I need your notes." + SECTION), chatgpt=Chat(BLOCKED))
    assert code == 5 and row["check_state"] == "blocked", out
    entries = projects.entries_of((project / "HANDOFF.md").read_text())
    assert entries[0].endswith(f"· blocked: {NEEDED}")


def test_a_blocked_file_mode_task_keeps_its_change_for_discard_only(garden, conn, runner):
    code, out, row = route(conn, worker=CopyWorker(BUILD), chatgpt=Chat(BLOCKED))
    row = log.get_task(conn, row["task_id"])
    assert (row["status"], row["check_state"]) == ("failed", "blocked"), out
    record = log.project_files_of(row)
    assert record["copy"] and record.get("state") != "waiting"
    assert "the check was blocked" in out and f"sr discard {row['n']}" in out
    code, said = land(conn, row)
    assert code == 2 and "has no change waiting to land" in said
    lines = []
    assert cli.cmd_land([str(row["n"])], conn=conn, config={}, verb="land", out=lines.append, anyway=True) == 2
    assert "a blocked task offers Discard only" in "\n".join(lines)
    code, said = land(conn, row, "discard")
    assert code == 0, said


def test_a_blocked_piece_reads_blocked_so_skip_goes_on():
    row = {"status": "failed", "check_state": "blocked", "check_note": f"blocked: {NEEDED}", "mode": "route",
           "agent": "claude", "route_reason": None, "preset": None, "failed_stage": None, "task_id": "sr-p1"}

    class Row(dict):
        def keys(self):
            return super().keys()
    assert split.piece_state(Row(row)) == ("blocked", f"it needed {NEEDED}")
