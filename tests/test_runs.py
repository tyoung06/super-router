"""Build brief 22, B1 (rules v2.31, Resume and Router for the interface, "Liveness and cancel"; decision 4): a run
writes its process id and that process's own start time on the task row when it starts and clears them when it ends.
A run is alive when `ps` finds the pid with the same start time to the second; a pid reused by another process started
at another time, so it is not the run. `ps` is run as an argument list; here a fake process table stands in (conftest),
and no test reads the real one. `sr check` never advances a task whose run is alive in another process: that is the
two-writer fault Phase 0 showed (a second `sr check` re-made a running call and the first window's write then failed).
Every value here is fake."""
import json
import os
import subprocess

import pytest

from router import __main__ as cli
from router import log, runs, status
from tests.conftest import FAKE_START
from tests.fixtures import json_shapes
from tests.helpers import fake_label, shipped_roster
from tests.test_json_actions import FAKE_ENV, World, jev
from tests.test_loop import Scripted
from tests.test_relay import Chat

ROSTER = shipped_roster()
OTHER_PID, OTHER_START = 4321, "2026-10-20T11:00:00+00:00"


# ---------- reading a process's start time ----------

class FakePs:
    def __init__(self, stdout="", returncode=0, raises=None, stderr=""):
        self.stdout, self.returncode, self.raises, self.stderr, self.calls = stdout, returncode, raises, stderr, []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


def test_the_start_time_is_read_with_ps_as_an_argument_list_in_utc():
    ps = FakePs("Wed Oct 21 01:02:02 2026    \n")
    assert runs.start_time(123, run=ps) == "2026-10-21T01:02:02+00:00"
    argv, kwargs = ps.calls[0]
    assert argv == ["/bin/ps", "-o", "lstart=", "-p", "123"]
    assert kwargs["env"] == {"TZ": "UTC", "LC_ALL": "C", "PATH": "/bin:/usr/bin"} and not kwargs.get("shell")
    assert kwargs["timeout"] == runs.PS_TIMEOUT


def test_a_single_digit_day_parses():
    assert runs.start_time(5, run=FakePs("Tue Oct  6 09:08:07 2026\n")) == "2026-10-06T09:08:07+00:00"


def test_ps_that_writes_to_stderr_reads_unknown_never_gone():
    """The owner's F addition: only an exit with empty stdout and empty stderr means the process is gone; a `ps` that says
    anything on stderr could not answer cleanly, so the run is never judged dead (or cleared) on it."""
    assert runs.start_time(5, run=FakePs("", returncode=1, stderr="ps: kvm_getprocs: Operation not permitted\n")) is runs.UNKNOWN
    assert runs.start_time(5, run=FakePs("Wed Oct 21 01:02:02 2026\n", returncode=0, stderr="ps: warning\n")) is runs.UNKNOWN
    assert runs.alive(5, "2026-10-21T01:02:02+00:00",
                      read=lambda pid: runs.start_time(pid, run=FakePs("", returncode=1, stderr="ps: error\n"))) is None


def test_a_pid_that_is_gone_reads_none():
    assert runs.start_time(99999, run=FakePs("", returncode=1)) is None
    assert runs.start_time(99999, run=FakePs("  \n", returncode=0)) is None


@pytest.mark.parametrize("raises", [OSError("no ps"), subprocess.TimeoutExpired(["ps"], 5)])
def test_ps_that_cannot_answer_reads_unknown(raises):
    assert runs.start_time(1, run=FakePs(raises=raises)) is runs.UNKNOWN
    assert runs.start_time(1, run=FakePs("not a date", returncode=0)) is runs.UNKNOWN


def test_alive_needs_the_pid_and_its_start_time_both():
    table = {10: "2026-10-20T10:00:00+00:00"}
    read = table.get
    assert runs.alive(10, "2026-10-20T10:00:00+00:00", read=read) is True
    assert runs.alive(11, "2026-10-20T10:00:00+00:00", read=read) is False          # gone
    assert runs.alive(10, "2026-10-20T09:59:59+00:00", read=read) is False          # a reused pid: another process
    assert runs.alive(10, "2026-10-20T10:00:00+00:00", read=lambda pid: runs.UNKNOWN) is None  # ps can't tell
    assert runs.alive(10, None, read=read) is None                                   # no start time to match: can't tell
    assert runs.alive(11, None, read=read) is False                                  # ...but a gone pid is gone
    assert runs.alive(None, None, read=read) is False


def test_this_process_is_known_by_its_pid_and_its_own_start_time():
    assert runs.me() == (os.getpid(), FAKE_START)


# ---------- claims ----------

def _task(conn, tid="sr-1", **kw):
    log.add_task(conn, tid, "t", "cli", jev("writing"), **kw)
    log.set_route(conn, tid, agents=ROSTER.names, agent="claude", route_reason="best", skill="writing",
                  skill_source="jev", checker="chatgpt", check_state="pending")


def _run_of(conn, tid="sr-1"):
    row = log.get_task(conn, tid)
    return row["pid"], row["run_started_at"]


def test_a_new_task_can_be_born_with_its_run():
    conn = log.init_db(":memory:")
    log.add_task(conn, "sr-1", "t", "cli", jev("writing"), run=runs.me())
    assert _run_of(conn) == (os.getpid(), FAKE_START)


def test_a_claim_takes_an_unowned_row_and_the_release_clears_only_its_own():
    conn = log.init_db(":memory:")
    _task(conn)
    assert runs.claim(conn, "sr-1") and _run_of(conn) == (os.getpid(), FAKE_START)
    assert runs.claim(conn, "sr-1")  # the same process again: re-entrant
    runs.release(conn, "sr-1")
    assert _run_of(conn) == (os.getpid(), FAKE_START)  # still held once
    runs.release(conn, "sr-1")
    assert _run_of(conn) == (None, None)
    runs.release(conn, "sr-1")  # not held: nothing happens


def test_a_claim_never_takes_a_row_another_process_holds():
    conn = log.init_db(":memory:")
    _task(conn)
    assert log.claim_run(conn, "sr-1", OTHER_PID, OTHER_START)
    assert not runs.claim(conn, "sr-1")
    assert _run_of(conn) == (OTHER_PID, OTHER_START)
    log.release_run(conn, "sr-1", os.getpid(), FAKE_START)  # not ours: untouched
    assert _run_of(conn) == (OTHER_PID, OTHER_START)


def test_a_claim_and_a_release_leave_updated_at_alone():
    conn = log.init_db(":memory:")
    _task(conn)
    before = log.get_task(conn, "sr-1")["updated_at"]
    runs.claim(conn, "sr-1")
    runs.release(conn, "sr-1")
    assert log.get_task(conn, "sr-1")["updated_at"] == before  # a memory's date is read from updated_at


# ---------- the commands write their run and clear it ----------

class Peek(Scripted):
    """A fake agent that reads, from its own connection, which rows hold a run while it is being called."""

    def __init__(self, *replies):
        super().__init__(*replies)
        self.seen = []

    def __call__(self, prompt, **kwargs):
        conn = log.connect(cli.DB_PATH, read_only=True)
        try:
            self.seen.append([(r["task_id"], r["pid"], r["run_started_at"])
                              for r in conn.execute("SELECT task_id, pid, run_started_at FROM tasks WHERE pid IS NOT NULL")])
        finally:
            conn.close()
        return super().__call__(prompt)


class PeekChat(Peek):
    def __call__(self, prompt, **kwargs):
        return super().__call__(prompt)


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    return World(monkeypatch, tmp_path, capsys)


def _held_rows():
    conn = log.init_db(cli.DB_PATH)
    try:
        return [tuple(r) for r in conn.execute("SELECT task_id, pid FROM tasks WHERE pid IS NOT NULL")]
    finally:
        conn.close()


def test_route_holds_its_run_during_its_calls_and_clears_it_after(world):
    world.label = fake_label(jev("writing"))
    world.worker, world.chatgpt = Peek("a draft"), PeekChat("PASS")
    code, out, err = world.run("route", "write a line")
    assert code == 0
    me = (os.getpid(), FAKE_START)
    assert world.worker.seen == [[("sr-20261020-000001-ab01", *me)]] and world.chatgpt.seen == [[("sr-20261020-000001-ab01", *me)]]
    assert _held_rows() == []


def test_relay_holds_its_run_during_every_stage(world):
    world.worker, world.chatgpt = Peek("## Plan\n1. a", "built", "x"), PeekChat("## Amended plan\n1. a", "## Deliverable\nok\n\n## Edits\n- none\n\n## Unresolved\nnone")
    code, out, err = world.run("relay", "collab", "plan a picnic")
    assert all(seen == [("sr-20261020-000001-ab01", os.getpid(), FAKE_START)] for seen in world.worker.seen + world.chatgpt.seen)
    assert _held_rows() == []


def test_a_split_holds_itself_and_each_piece_while_the_piece_runs(world, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")  # the World has a terminal: it asks y/N/e
    world.worker = Peek("## Pieces\n1. one\n2. two\n\n## Join\njoin them", "piece one", "piece two", "joined")
    world.chatgpt = PeekChat("PASS", "PASS", "PASS")
    world.label = fake_label(jev("writing"))
    code, out, err = world.run("split", "two things")
    me = (os.getpid(), FAKE_START)
    split_id = "sr-20261020-000001-ab01"
    plan_call, piece_one, piece_two = world.worker.seen[:3]
    assert plan_call == [(split_id, *me)]
    assert len(piece_one) == 2 and (split_id, *me) in piece_one  # the split and the piece being run, nothing else
    assert len(piece_two) == 2 and (split_id, *me) in piece_two and piece_one != piece_two
    assert _held_rows() == []


def test_resume_and_fallback_hold_the_row_during_their_call(world, monkeypatch):
    world.label = fake_label(jev("writing"))
    world.worker, world.chatgpt = Scripted("draft one", "draft two"), Chat("FIX\n1. a", "FIX\n1. b")
    world.run("route", "write a poem")  # a double fail: done, check failed
    world.worker, world.chatgpt = Peek("PASS"), PeekChat("the redo")
    code, out, err = world.run("fallback", "1")
    assert world.chatgpt.seen[0] == [("sr-20261020-000001-ab01", os.getpid(), FAKE_START)]
    assert _held_rows() == []


# ---------- sr check and a run in another process ----------

def _check(conn, worker, chatgpt, out):
    return cli.cmd_check(conn=conn, config=dict(FAKE_ENV), fetch=lambda: [], close=lambda n: None, environ={},
                         settings_paths=(), worker=worker, chatgpt=chatgpt, codex_login=lambda: True, roster=ROSTER,
                         out=out.append)


def test_sr_check_never_advances_a_task_whose_run_is_alive_in_another_process(monkeypatch):
    """Phase 0's simulation as a regression test: before brief 22 this made the Claude call again and the ChatGPT check."""
    conn = log.init_db(":memory:")
    _task(conn)
    log.claim_run(conn, "sr-1", OTHER_PID, OTHER_START)
    monkeypatch.setattr(runs, "READ", lambda pid: OTHER_START if pid == OTHER_PID else None)
    worker, chatgpt, out = Scripted("again"), Chat("PASS"), []
    assert _check(conn, worker, chatgpt, out) == 0
    assert worker.prompts == [] and chatgpt.prompts == [] and log.calls_for(conn, "sr-1") == []
    assert f"#1 sr-1 is running in another window (pid {OTHER_PID})." in out
    assert _run_of(conn) == (OTHER_PID, OTHER_START)


def test_sr_check_leaves_a_run_it_cannot_judge_alone(monkeypatch):
    conn = log.init_db(":memory:")
    _task(conn)
    log.claim_run(conn, "sr-1", OTHER_PID, OTHER_START)
    monkeypatch.setattr(runs, "READ", lambda pid: runs.UNKNOWN)  # ps could not answer: treated as alive
    worker, out = Scripted("again"), []
    _check(conn, worker, Chat("PASS"), out)
    assert worker.prompts == [] and _run_of(conn) == (OTHER_PID, OTHER_START)


def test_sr_check_holds_a_task_while_it_advances_it_and_clears_it_after():
    conn = log.init_db(":memory:")
    _task(conn)
    seen = []

    def worker(prompt):
        seen.append(_run_of(conn))
        return "a draft"

    out = []
    _check(conn, worker, Chat("PASS"), out)
    assert seen == [(os.getpid(), FAKE_START)] and _run_of(conn) == (None, None)


def test_sr_check_skips_a_queued_piece_whose_split_is_running_in_another_process(monkeypatch):
    conn = log.init_db(":memory:")
    log.add_task(conn, "sr-s", "split", "cli", {"status": "not_asked", "tokens": 0}, mode="split")
    log.claim_run(conn, "sr-s", OTHER_PID, OTHER_START)
    log.add_task(conn, "sr-p1", "piece one", "split", jev("writing"), mode="piece", parent="sr-s")
    log.set_route(conn, "sr-p1", agents=ROSTER.names, agent="claude", route_reason="best", skill="writing",
                  skill_source="jev", checker="chatgpt", check_state="pending")
    monkeypatch.setattr(runs, "READ", lambda pid: OTHER_START if pid == OTHER_PID else None)
    worker, out = Scripted("piece"), []
    _check(conn, worker, Chat("PASS"), out)
    assert worker.prompts == [] and log.calls_for(conn, "sr-p1") == []


# ---------- what a page reads ----------

def test_status_lists_every_run_with_its_pid_whether_it_is_alive_and_since_when(world, monkeypatch):
    conn = log.init_db(cli.DB_PATH)
    _task(conn, "sr-a")
    _task(conn, "sr-b")
    log.claim_run(conn, "sr-a", os.getpid(), FAKE_START)
    log.claim_run(conn, "sr-b", OTHER_PID, OTHER_START)  # its process is gone (the fake table doesn't know it)
    conn.close()
    monkeypatch.setattr(cli.online, "run_all", lambda checks, now=None: {})
    code, out, err = world.run("status", "--json")
    doc = json.loads(out)
    assert doc["running"] == [{"n": 1, "task_id": "sr-a", "pid": os.getpid(), "alive": True, "since": FAKE_START},
                              {"n": 2, "task_id": "sr-b", "pid": OTHER_PID, "alive": False, "since": OTHER_START}]
    json_shapes.check(doc, json_shapes.STATUS, optional=("report_path",))
    code, out, err = world.run("status")
    assert f"Running: #1 sr-a pid {os.getpid()} since {FAKE_START} (alive)" in out
    assert f"Running: #2 sr-b pid {OTHER_PID} since {OTHER_START} (ended; sr check marks it)" in out


def test_a_task_view_carries_the_run_and_answered_by(world):
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("4")
    world.run("route", "2 plus 2")
    code, out, err = world.run("show", "1", "--json")
    doc = json.loads(out)
    assert (doc["pid"], doc["run_started_at"], doc["answered_by"]) == (None, None, None)
    json_shapes.check(doc, json_shapes.SHOW)
