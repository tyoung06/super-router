"""Build brief 22, B2 (rules v2.31, Resume, "A process-ended stop"; decision 4 and Phase 0 choices 1 and 3): a local call
(Claude, ChatGPT, Cursor) writes its row only after it returns, so just before each one the run writes a small note
beside the log, `run/calls/<task_id>.json`, naming the call and holding what it was sent (its search state, its context
and memory records), and removes it once the row is written. Only `sr check` writes a dead run: with a note, that call
becomes a failed row with reason `process_ended` and the saved records, and the task `failed`, so `state.of` reads
outcome `process_ended`; without a note no call was running, so the run is cleared and the task goes on as any open
task; a run that ended at the Jev floor prompt comes back `needs_label`; an ended row (a resume in flight) is only
cleared. A run `ps` can't judge is never marked. JSON reads never write. Every value here is fake."""
import json
import os

import pytest

from router import __main__ as cli
from router import log, runs, state
from tests.conftest import FAKE_START
from tests.helpers import fake_label, shipped_roster
from tests.test_json_actions import FAKE_ENV, World, jev
from tests.test_loop import Scripted
from tests.test_relay import Chat

ROSTER = shipped_roster()
OTHER_PID, OTHER_START = 4321, "2026-10-20T11:00:00+00:00"   # gone in the fake process table


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    return World(monkeypatch, tmp_path, capsys)


def _note_path(task_id):
    return cli.DB_PATH.parent / "run" / "calls" / f"{task_id}.json"


# ---------- the note ----------

class NoteWatcher(Scripted):
    """A fake agent that reads its task's note while it is being called."""

    def __init__(self, task_id, *replies):
        super().__init__(*replies)
        self.task_id, self.notes = task_id, []

    def __call__(self, prompt, **kwargs):
        path = _note_path(self.task_id)
        self.notes.append(json.loads(path.read_text()) if path.exists() else None)
        return super().__call__(prompt)


def test_a_local_call_writes_its_note_first_and_removes_it_after_its_row(world):
    tid = "sr-20261020-000001-ab01"
    world.label = fake_label(jev("writing"))
    world.worker, world.chatgpt = NoteWatcher(tid, "a draft"), Chat("PASS")
    world.run("route", "write a line")
    note = world.worker.notes[0]
    assert note is not None
    assert {k: note[k] for k in ("call_id", "kind", "agent", "stage", "role", "pid", "started")} == {
        "call_id": tid, "kind": "do", "agent": "claude", "stage": None, "role": None, "pid": os.getpid(),
        "started": FAKE_START}
    assert note["search"] == {"state": "off (probe not passed)"}
    assert not _note_path(tid).exists()
    assert oct(_note_path(tid).parent.stat().st_mode & 0o777) == "0o700"


def test_a_relay_stage_note_names_its_stage_and_role(world):
    tid = "sr-20261020-000001-ab01"
    world.worker = NoteWatcher(tid, "## Plan\n1. a", "built")
    world.chatgpt = Chat("## Amended plan\n1. a", "## Deliverable\nok\n\n## Edits\n- none\n\n## Unresolved\nnone")
    world.run("relay", "collab", "plan a picnic")
    notes = [(n["kind"], n["stage"], n["role"], n["agent"]) for n in world.worker.notes]
    assert notes[0] == ("stage", 1, "plan", "claude")
    assert all(kind in ("stage", "reask") and stage and role for kind, stage, role, agent in notes)
    assert not _note_path(tid).exists()


@pytest.mark.parametrize("ending", [KeyboardInterrupt, RuntimeError("boom")])
def test_the_note_is_removed_when_the_call_is_interrupted_or_fails(world, ending):
    world.label = fake_label(jev("writing"))
    world.worker = Scripted(ending)
    world.run("route", "write a line")
    assert not _note_path("sr-20261020-000001-ab01").exists()


# ---------- the dead-run check in sr check ----------

def _routed(conn, tid="sr-1", agent="claude", checker="chatgpt", **kw):
    log.add_task(conn, tid, "write a line", "cli", jev("writing"), **kw)
    log.set_route(conn, tid, agents=ROSTER.names, agent=agent, route_reason="best", skill="writing",
                  skill_source="jev", checker=checker, check_state="pending")


def _dead_note(tid, **record):
    runs.write_note(cli.DB_PATH.parent / "run", tid, {"call_id": tid, "kind": "do", "agent": "claude", "stage": None,
                                                       "role": None, "search": {"state": "allowed"}, "context": None,
                                                       "memory": None, "pid": OTHER_PID, "started": OTHER_START,
                                                       **record})


def _check(world):
    return world.run("check")


def _log(fn):
    conn = log.init_db(cli.DB_PATH)
    try:
        return fn(conn)
    finally:
        conn.close()


def test_a_dead_run_with_a_note_becomes_a_process_ended_stop(world):
    conn = log.init_db(cli.DB_PATH)
    _routed(conn, run=(OTHER_PID, OTHER_START))
    conn.close()
    _dead_note("sr-1", memory={"tag": "chat:x", "found": 0, "sent": 0})
    world.worker, world.chatgpt = Scripted("never"), Chat("never")
    code, out, err = _check(world)
    assert world.worker.prompts == [] and world.chatgpt.prompts == []
    row = _log(lambda c: log.get_task(c, "sr-1"))
    calls = _log(lambda c: log.calls_for(c, "sr-1"))
    assert (row["status"], row["result"], row["pid"], row["run_started_at"]) == ("failed", "stopped: process ended", None, None)
    assert [(c["call_id"], c["kind"], c["agent"], c["status"], c["reason_code"]) for c in calls] == [
        ("sr-1", "do", "claude", "failed", "process_ended")]
    assert log.search_of(calls[0]) == {"state": "allowed"} and log.call_memory_of(calls[0]) == {"tag": "chat:x", "found": 0, "sent": 0}
    assert state.of(row, calls) == state.State(None, "process_ended")
    assert f"#1 sr-1 stopped: process ended (pid {OTHER_PID}) during the first call by claude." in out
    assert not _note_path("sr-1").exists()


def test_a_dead_relay_stage_names_its_stage(world):
    conn = log.init_db(cli.DB_PATH)
    log.add_task(conn, "sr-r", "plan", "cli", {"status": "not_asked", "tokens": 0}, mode="relay", preset="collab",
                 run=(OTHER_PID, OTHER_START))
    log.set_route(conn, "sr-r", agents=ROSTER.names, agent="claude", route_reason="relay", checker=None,
                  check_state="pending")
    log.add_call(conn, "sr-r-s1", "sr-r", "stage", "claude", status="done", text="## Plan\n1. a", stage=1, role="plan")
    conn.close()
    _dead_note("sr-r", call_id="sr-r-s2", kind="stage", agent="chatgpt", stage=2, role="amend")
    world.worker, world.chatgpt = Scripted("never"), Chat("never")
    code, out, err = _check(world)
    row = _log(lambda c: log.get_task(c, "sr-r"))
    assert (row["status"], row["failed_stage"]) == ("failed", 2)
    assert "during stage 2 (amend) by chatgpt" in out and world.chatgpt.prompts == []


def test_a_dead_run_at_the_floor_prompt_comes_back_for_its_label(world):
    conn = log.init_db(cli.DB_PATH)
    log.add_task(conn, "sr-f", "something vague", "cli", {**jev("writing"), "status": "below_floor", "confidence": 0.5},
                 run=(OTHER_PID, OTHER_START))
    conn.close()
    code, out, err = _check(world)
    row = _log(lambda c: log.get_task(c, "sr-f"))
    assert (row["status"], row["reason_code"], row["pid"], row["jev_label"]) == ("returned", "needs_label", None, "writing")
    assert state.of(row, []) == state.State("needs_label", None)
    assert f"#1 sr-f came back to you: needs your label (its run, pid {OTHER_PID}, ended at the skill question)." in out


def test_an_unowned_task_left_at_the_floor_no_longer_crashes_sr_check(world):
    """Phase 0's second finding as a regression test: a row killed at the prompt before brief 22 (no run on it)."""
    conn = log.init_db(cli.DB_PATH)
    log.add_task(conn, "sr-f", "something vague", "cli", {**jev("writing"), "status": "below_floor", "confidence": 0.5})
    conn.close()
    code, out, err = _check(world)
    assert code == 0 and _log(lambda c: log.get_task(c, "sr-f"))["reason_code"] == "needs_label"


def test_a_dead_run_with_no_note_is_cleared_and_the_task_goes_on(world):
    conn = log.init_db(cli.DB_PATH)
    _routed(conn, run=(OTHER_PID, OTHER_START))  # died between calls: nothing was running
    conn.close()
    world.worker, world.chatgpt = Scripted("a draft"), Chat("PASS")
    code, out, err = _check(world)
    row = _log(lambda c: log.get_task(c, "sr-1"))
    assert (row["status"], row["check_state"], row["pid"]) == ("done", "passed", None)
    assert len(world.worker.prompts) == 1


def test_a_dead_run_during_a_grok_wait_is_cleared_and_the_task_keeps_waiting(world):
    conn = log.init_db(cli.DB_PATH)
    _routed(conn, agent="grok", checker="chatgpt", run=(OTHER_PID, OTHER_START))
    log.set_sent(conn, "sr-1", "uuid-1")
    conn.close()
    code, out, err = _check(world)
    row = _log(lambda c: log.get_task(c, "sr-1"))
    assert (row["status"], row["pid"]) == ("sent", None)
    assert state.of(row, _log(lambda c: log.calls_for(c, "sr-1"))) == state.State("grok", None)


def test_a_note_whose_call_already_has_its_row_is_stale(world):
    conn = log.init_db(cli.DB_PATH)
    _routed(conn, run=(OTHER_PID, OTHER_START))
    log.add_call(conn, "sr-1", "sr-1", "do", "claude", status="done", text="the draft came back")
    conn.close()
    _dead_note("sr-1")  # died after the row, before removing the note
    world.chatgpt = Chat("PASS")
    code, out, err = _check(world)
    row = _log(lambda c: log.get_task(c, "sr-1"))
    assert (row["status"], row["check_state"]) == ("done", "passed") and not _note_path("sr-1").exists()


def test_a_dead_resume_in_flight_is_only_cleared(world):
    conn = log.init_db(cli.DB_PATH)
    _routed(conn)
    log.add_call(conn, "sr-1", "sr-1", "do", "claude", status="failed", text="limit", reason_code="plan_limit")
    log.set_failed(conn, "sr-1", "limit")
    log.claim_run(conn, "sr-1", OTHER_PID, OTHER_START)
    conn.close()
    code, out, err = _check(world)
    row = _log(lambda c: log.get_task(c, "sr-1"))
    assert (row["status"], row["result"], row["pid"]) == ("failed", "limit", None)
    assert len(_log(lambda c: log.calls_for(c, "sr-1"))) == 1


def test_a_run_ps_cannot_judge_is_never_marked(world, monkeypatch):
    conn = log.init_db(cli.DB_PATH)
    _routed(conn, run=(OTHER_PID, OTHER_START))
    conn.close()
    _dead_note("sr-1")
    monkeypatch.setattr(runs, "READ", lambda pid: runs.UNKNOWN if pid == OTHER_PID else FAKE_START)
    world.worker = Scripted("never")
    code, out, err = _check(world)
    row = _log(lambda c: log.get_task(c, "sr-1"))
    assert (row["status"], row["pid"]) == ("queued", OTHER_PID) and _note_path("sr-1").exists()
    assert world.worker.prompts == []


def test_a_reused_pid_is_not_the_run(world, monkeypatch):
    conn = log.init_db(cli.DB_PATH)
    _routed(conn, run=(OTHER_PID, OTHER_START))
    conn.close()
    _dead_note("sr-1")
    monkeypatch.setattr(runs, "READ", lambda pid: "2026-10-20T11:30:00+00:00" if pid == OTHER_PID else FAKE_START)
    code, out, err = _check(world)
    assert _log(lambda c: log.get_task(c, "sr-1"))["status"] == "failed"  # same pid, another start: the run is gone


def test_a_json_read_shows_a_dead_run_and_changes_nothing(world, monkeypatch):
    conn = log.init_db(cli.DB_PATH)
    _routed(conn, run=(OTHER_PID, OTHER_START))
    conn.close()
    _dead_note("sr-1")
    monkeypatch.setattr(cli.online, "run_all", lambda checks, now=None: {})
    before = _log(lambda c: [tuple(r) for r in c.execute("SELECT * FROM tasks")])
    code, out, err = world.run("status", "--json")
    assert json.loads(out)["running"] == [{"n": 1, "task_id": "sr-1", "pid": OTHER_PID, "alive": False,
                                           "since": OTHER_START}]
    world.run("show", "1", "--json")
    world.run("log", "--json")
    assert _log(lambda c: [tuple(r) for r in c.execute("SELECT * FROM tasks")]) == before
    assert _note_path("sr-1").exists()


def test_the_check_json_lists_what_became_of_a_dead_run(world):
    conn = log.init_db(cli.DB_PATH)
    _routed(conn, run=(OTHER_PID, OTHER_START))
    conn.close()
    _dead_note("sr-1")
    found = world.json("check")
    assert {"task_id": "sr-1", "n": 1, "status": "failed", "waiting_on": None, "outcome": "process_ended",
            "reason_code": None} in found["tasks"]


def test_process_ended_is_no_longer_reserved():
    assert "process_ended" in state.OUTCOMES and "process_ended" not in state.RESERVED
    assert "process_ended" in log.REASON_CODES
