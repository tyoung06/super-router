"""Build brief 22, B4 (rules v2.31, Router for the interface, "Liveness and cancel"; decision 5): `sr cancel <n>` on a
running task marks it `cancelled`, then sends SIGINT to its run, the path Ctrl+C already takes (exit 130, nothing half
written: the agent's child process is killed by `subprocess.run`, the note of the call removed, no row for the call).
A pid whose start time doesn't match the run is never signalled; one `ps` can't judge is not signalled either. A
resume or fallback in flight (its row already ended) gets the SIGINT and its row is left as it was; a waiting split is
never signalled (its pieces are untouched). The signal and the process table are fakes. Every value here is fake."""
import json
import os
import signal

import pytest

from router import __main__ as cli
from router import log, runs
from tests.conftest import FAKE_START
from tests.helpers import fake_label, shipped_roster
from tests.test_json_actions import World, jev
from tests.test_loop import Scripted
from tests.test_relay import Chat

ROSTER = shipped_roster()
OTHER_PID, OTHER_START = 4321, "2026-10-20T11:00:00+00:00"


class Table:
    """A fake process table with one other process; a SIGINT to it ends it after `stops_after` polls."""

    def __init__(self, start=OTHER_START, stops_after=1, unknown=False):
        self.start, self.stops_after, self.unknown, self.signals, self.polls = start, stops_after, unknown, [], 0

    def read(self, pid):
        if pid == os.getpid():
            return FAKE_START
        if pid != OTHER_PID:
            return None
        if self.unknown:
            return runs.UNKNOWN
        if self.signals:
            self.polls += 1
            if self.stops_after is not None and self.polls >= self.stops_after:
                return None
        return self.start

    def kill(self, pid, sig):
        self.signals.append((pid, sig))


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _routed(conn, tid="sr-1", status="queued"):
    log.add_task(conn, tid, "write a line", "cli", jev("writing"))
    log.set_route(conn, tid, agents=ROSTER.names, agent="claude", route_reason="best", skill="writing",
                  skill_source="jev", checker="chatgpt", check_state="pending")
    log.claim_run(conn, tid, OTHER_PID, OTHER_START)


def _cancel(conn, table, words=("1",), monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setattr(runs, "READ", table.read)
    out, clock = [], Clock()
    code = cli.cmd_cancel(conn=conn, words=list(words), kill=table.kill, sleep=clock.sleep, clock=clock, out=out.append)
    return code, "\n".join(out), clock


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def test_cancel_marks_a_running_task_cancelled_then_sends_sigint_to_its_run(conn, monkeypatch):
    _routed(conn)
    table = Table()
    code, out, clock = _cancel(conn, table, monkeypatch=monkeypatch)
    assert code == 0 and table.signals == [(OTHER_PID, signal.SIGINT)]
    assert log.get_task(conn, "sr-1")["status"] == "cancelled"
    assert "Logged as cancelled." in out and f"Sent Ctrl+C to its run (pid {OTHER_PID}); it stopped." in out


def test_a_pid_whose_start_time_does_not_match_is_never_signalled(conn, monkeypatch):
    _routed(conn)
    table = Table(start="2026-10-20T11:30:00+00:00")  # the pid now belongs to another process
    code, out, clock = _cancel(conn, table, monkeypatch=monkeypatch)
    assert code == 0 and table.signals == []
    row = log.get_task(conn, "sr-1")
    assert (row["status"], row["pid"]) == ("cancelled", None)
    assert "Sent Ctrl+C" not in out


def test_a_dead_run_is_not_signalled_and_its_run_is_cleared(conn, monkeypatch):
    _routed(conn)
    table = Table()
    monkeypatch.setattr(runs, "READ", lambda pid: FAKE_START if pid == os.getpid() else None)
    out, clock = [], Clock()
    code = cli.cmd_cancel(conn=conn, words=["1"], kill=table.kill, sleep=clock.sleep, clock=clock, out=out.append)
    assert code == 0 and table.signals == [] and log.get_task(conn, "sr-1")["pid"] is None


def test_a_run_ps_cannot_judge_is_not_signalled(conn, monkeypatch):
    _routed(conn)
    table = Table(unknown=True)
    code, out, clock = _cancel(conn, table, monkeypatch=monkeypatch)
    assert code == 0 and table.signals == [] and log.get_task(conn, "sr-1")["status"] == "cancelled"
    assert f"Couldn't tell whether its run (pid {OTHER_PID}) is still going, so it was not signalled" in out


def test_a_run_that_does_not_stop_within_10_seconds_is_said_so(conn, monkeypatch):
    _routed(conn)
    table = Table(stops_after=None)
    code, out, clock = _cancel(conn, table, monkeypatch=monkeypatch)
    assert table.signals == [(OTHER_PID, signal.SIGINT)] and clock.now >= 10
    assert f"Sent Ctrl+C to its run (pid {OTHER_PID}); it hasn't stopped after 10 s" in out


def test_a_resume_in_flight_gets_the_sigint_and_its_row_is_left_as_it_was(conn, monkeypatch):
    log.add_task(conn, "sr-1", "write a line", "cli", jev("writing"))
    log.set_route(conn, "sr-1", agents=ROSTER.names, agent="claude", route_reason="best", skill="writing",
                  skill_source="jev", checker="chatgpt", check_state="pending")
    log.add_call(conn, "sr-1", "sr-1", "do", "claude", status="failed", text="limit", reason_code="plan_limit")
    log.set_failed(conn, "sr-1", "limit")
    log.claim_run(conn, "sr-1", OTHER_PID, OTHER_START)
    table = Table()
    code, out, clock = _cancel(conn, table, monkeypatch=monkeypatch)
    assert code == 0 and table.signals == [(OTHER_PID, signal.SIGINT)]
    assert log.get_task(conn, "sr-1")["status"] == "failed"
    assert f"Sent Ctrl+C to the run on #1 (pid {OTHER_PID}); it stopped. #1 is as it was (failed)." in out


def test_a_waiting_split_is_never_signalled(conn, monkeypatch):
    log.add_task(conn, "sr-s", "split", "cli", {"status": "not_asked", "tokens": 0}, mode="split")
    log.set_route(conn, "sr-s", agents=ROSTER.names, agent="claude", route_reason="split", checker="chatgpt",
                  check_state="pending")
    log.set_split_plan(conn, "sr-s", {"pieces": [], "join": "j", "approved": True})
    log.set_split_returned(conn, "sr-s", f"{log.WAITING_PIECES} #2")
    log.claim_run(conn, "sr-s", OTHER_PID, OTHER_START)
    table = Table()
    code, out, clock = _cancel(conn, table, monkeypatch=monkeypatch)
    assert code == 0 and table.signals == [] and log.get_task(conn, "sr-s")["status"] == "cancelled"


def test_an_ended_task_with_no_run_is_still_refused(conn, monkeypatch):
    log.add_task(conn, "sr-1", "t", "cli", jev("writing"))
    log.set_route(conn, "sr-1", agents=ROSTER.names, agent="claude", route_reason="best")
    log.set_cancelled(conn, "sr-1")
    code, out, clock = _cancel(conn, Table(), monkeypatch=monkeypatch)
    assert code == 1 and "nothing to cancel" in out


# ---------- the run's side: the Ctrl+C path ----------

def test_the_run_stops_at_130_with_no_call_row_no_note_and_no_round_file(monkeypatch, tmp_path, capsys):
    world = World(monkeypatch, tmp_path, capsys)
    world.label = fake_label(jev("writing"))

    def cancelled_mid_call(prompt):
        conn = log.connect(cli.DB_PATH)  # what `sr cancel` does from the other window, then its SIGINT lands
        log.set_cancelled(conn, "sr-20261020-000001-ab01")
        conn.close()
        raise KeyboardInterrupt

    world.worker = cancelled_mid_call
    code, out, err = world.run("route", "write a line")
    assert code == 130 and "Stopped. sr-20261020-000001-ab01 is cancelled." in out
    conn = log.init_db(cli.DB_PATH)
    try:
        row = log.task_by_number(conn, 1)
        assert (row["status"], row["pid"]) == ("cancelled", None) and log.calls_for(conn, row["task_id"]) == []
    finally:
        conn.close()
    assert not (cli.DB_PATH.parent / "run" / "calls" / "sr-20261020-000001-ab01.json").exists()
    assert not list((cli.DB_PATH.parent / "tasks").rglob("*.md")) if (cli.DB_PATH.parent / "tasks").exists() else True


def test_a_cancel_during_the_checkers_codex_call_reads_cancelled_not_a_failed_check(monkeypatch, tmp_path, capsys):
    # Brief 23 E, step 5's question: a cancel whose SIGINT lands during ChatGPT's check call (subprocess.run turns it
    # into KeyboardInterrupt and kills codex) takes the same Ctrl+C path as one during the build: the task reads
    # cancelled, the check leaves no call row and no round file, so it is never recorded as a failed check.
    world = World(monkeypatch, tmp_path, capsys)
    world.label, world.worker = fake_label(jev("writing")), Scripted("a line")

    def cancelled_mid_check(prompt, **kwargs):
        conn = log.connect(cli.DB_PATH)  # `sr cancel` from the page's server, then its SIGINT lands in codex's call
        log.set_cancelled(conn, "sr-20261020-000001-ab01")
        conn.close()
        raise KeyboardInterrupt

    world.chatgpt = cancelled_mid_check
    code, out, err = world.run("route", "write a line")
    assert code == 130 and "Stopped. sr-20261020-000001-ab01 is cancelled." in out
    conn = log.init_db(cli.DB_PATH)
    try:
        row = log.task_by_number(conn, 1)
        calls = log.calls_for(conn, row["task_id"])
        assert (row["status"], row["pid"]) == ("cancelled", None)
        assert [(c["kind"], c["agent"], c["status"]) for c in calls] == [("do", "claude", "done")]
    finally:
        conn.close()
    assert sorted(p.name for p in (cli.DB_PATH.parent / "tasks").rglob("*.md")) == ["01-do-claude.md"]


def test_cancel_answers_with_the_json_envelope(monkeypatch, tmp_path, capsys):
    world = World(monkeypatch, tmp_path, capsys)
    conn = log.init_db(cli.DB_PATH)
    _routed(conn)
    conn.close()
    table = Table()
    monkeypatch.setattr(runs, "READ", table.read)
    monkeypatch.setattr(cli.os, "kill", table.kill)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    found = world.json("cancel", "1")
    assert (found["exit"], found["status"], found["outcome"]) == (0, "cancelled", "cancelled")
    assert table.signals == [(OTHER_PID, signal.SIGINT)]
