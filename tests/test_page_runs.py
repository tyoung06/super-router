"""Build brief 23, A6 (decisions 6, 7 and 17): the commands the page server starts. Each runs as an argument list in its own
session with stdin closed, its output read on a thread, so the start answers at once; the Run log keeps the last 100
runs, what each printed (its envelope's message, then its stderr), matched to its task's row by pid before its envelope
arrives. Once a minute while any open task waits on Grok the server runs `sr check --json`, never two at once, behind
the dead-run check's guard. The children here are tests/fake_sr.py (real processes, no router, no model)."""
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from router import page, page_runs

FAKE_SR = Path(__file__).resolve().parent / "fake_sr.py"
PREFIX = [sys.executable, str(FAKE_SR)]


def _wait_done(runs, run_id, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        run = runs.get(run_id)
        if not run["running"]:
            return run
        time.sleep(0.05)
    raise AssertionError(f"{run_id} still running")


@pytest.fixture
def runs(tmp_path):
    return page_runs.Runs(root=tmp_path, prefix=PREFIX)


# ---------- a command started by the page ----------

def test_a_start_answers_at_once_while_a_three_second_command_runs(runs, monkeypatch):
    monkeypatch.setenv("FAKE_SR_SLEEP", "3")
    began = time.monotonic()
    run = runs.start(["check", "--json"], "sr check --json")
    assert time.monotonic() - began < 1 and run["running"] is True and run["pid"] > 0 and run["exit"] is None
    done = _wait_done(runs, run["id"])
    assert done["exit"] == 0 and done["envelope"]["argv"] == ["check", "--json"] and done["message"] == "fake sr ran check"


def test_the_child_runs_in_its_own_session_with_stdin_closed(runs):
    done = _wait_done(runs, runs.start(["check", "--json"], "sr check --json")["id"])
    envelope = done["envelope"]
    assert envelope["sid"] == envelope["pid"] == done["pid"] and envelope["sid"] != os.getsid(0)
    assert envelope["stdin"] == 0


def test_the_argv_reaches_the_child_as_given_one_argument_each(runs):
    text = 'He said "hi" & `ls` $HOME\nnext line --skill coding -h @grok'
    done = _wait_done(runs, runs.start(["route", "--json", "--source", "ui", "--", text], "shown")["id"])
    assert done["envelope"]["argv"] == ["route", "--json", "--source", "ui", "--", text]


def test_a_refusal_keeps_its_envelope_from_stderr_and_the_rest_of_stderr(runs, monkeypatch):
    monkeypatch.setenv("FAKE_SR_EXIT", "2")
    monkeypatch.setenv("FAKE_SR_STDERR", "a warning line")
    done = _wait_done(runs, runs.start(["route", "--json", "--", "x"], "shown")["id"])
    assert done["exit"] == 2 and done["envelope"]["reason_code"] == "bad_task" and done["stderr"] == "a warning line"
    assert done["message"] == "fake sr ran route"


def test_the_envelopes_task_id_names_the_run(runs, monkeypatch):
    monkeypatch.setenv("FAKE_SR_TASK", "sr-20261021-000803-3d77")
    done = _wait_done(runs, runs.start(["route", "--json", "--", "x"], "shown")["id"])
    assert done["task_id"] == "sr-20261021-000803-3d77"


def test_a_killed_command_has_no_envelope_and_its_signal_as_the_exit(runs, monkeypatch):
    monkeypatch.setenv("FAKE_SR_SLEEP", "30")
    run = runs.start(["route", "--json", "--", "x"], "shown")
    os.kill(run["pid"], 9)
    done = _wait_done(runs, run["id"])
    assert done["exit"] == -9 and done["envelope"] is None and done["message"] is None


def test_a_running_run_is_matched_to_the_row_its_process_made(runs, monkeypatch):
    monkeypatch.setenv("FAKE_SR_SLEEP", "2")
    run = runs.start(["route", "--json", "--", "x"], "shown")
    runs.bind([{"task_id": "sr-other", "pid": 1}, {"task_id": "sr-20261021-000803-3d77", "pid": run["pid"]}])
    assert runs.get(run["id"])["task_id"] == "sr-20261021-000803-3d77"
    runs.bind([{"task_id": "sr-later", "pid": run["pid"]}])  # bound once; a later row never renames it
    assert runs.get(run["id"])["task_id"] == "sr-20261021-000803-3d77"


class FakeProc:
    _pids = iter(range(5000, 9000))

    def __init__(self, argv, **kw):
        assert isinstance(argv, list) and not kw.get("shell") and kw["start_new_session"] is True
        assert kw["stdin"] is page_runs.subprocess.DEVNULL
        self.pid, self.returncode = next(self._pids), 0

    def communicate(self):
        return json.dumps({"message": "done"}) + "\n", ""


def test_only_the_last_100_runs_are_kept_and_a_running_one_never_goes(tmp_path):
    started = []

    class Held:  # the first run never finishes
        def __init__(self, target, args, daemon):
            self.target, self.args = target, args

        def start(self):
            if started:
                self.target(*self.args)
            started.append(1)
    runs = page_runs.Runs(popen=FakeProc, root=tmp_path, prefix=PREFIX, thread=Held)
    first = runs.start(["check", "--json"], "sr check --json")
    for _ in range(104):
        runs.start(["check", "--json"], "sr check --json")
    kept = runs.list()
    assert len(kept) == 100 and kept[-1]["id"] == first["id"] and kept[-1]["running"] is True
    assert kept[0]["id"] == "run-105"


def test_output_past_the_cap_keeps_the_tail(monkeypatch):
    monkeypatch.setattr(page_runs, "CAP", 10)
    runs = page_runs.Runs(popen=FakeProc, prefix=PREFIX, thread=lambda **kw: SimpleNamespace(start=lambda: None))
    run_id = runs.record("check", "sr check --json")
    runs.finished(run_id, 1, "", "0123456789abcdef")
    assert runs.get(run_id)["stderr"] == "[the first 6 characters are not kept]\n6789abcdef"


def test_a_list_is_newest_first_and_a_copy(runs):
    one, two = runs.record("check", "a"), runs.record("memory", "b")
    found = runs.list()
    assert [r["id"] for r in found] == [two, one]
    found[0]["display"] = "changed"
    assert runs.get(two)["display"] == "b"


# ---------- the Grok check, once a minute, one at a time (decision 7) ----------

class Log:
    def __init__(self, tasks):
        self.tasks, self.calls = tasks, []

    def __call__(self, argv, **kw):
        assert isinstance(argv, list) and not kw.get("shell")
        self.calls.append((argv, kw))
        if argv[3] == "log":
            return SimpleNamespace(returncode=0, stdout=json.dumps({"tasks": self.tasks}) + "\n", stderr="")
        return SimpleNamespace(returncode=0, stdout=json.dumps({"message": "checked", "exit": 0}) + "\n", stderr="")

    def checks(self):
        return [kw for argv, kw in self.calls if argv[3] == "check"]


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class Later:
    def __init__(self):
        self.jobs = []

    def __call__(self, job):
        self.jobs.append(job)

    def run_all(self):
        while self.jobs:
            self.jobs.pop(0)()


def _reader(tasks, runs=None):
    run, clock, later = Log(tasks), Clock(), Later()
    return page.Reader(run=run, clock=clock, start=later, runs=runs), run, clock, later


def test_a_task_waiting_on_grok_gets_a_check_once_a_minute(tmp_path):
    reader, run, clock, later = _reader([{"task_id": "sr-1", "waiting_on": "grok"}])
    assert reader.tick() is True
    later.run_all()
    assert len(run.checks()) == 1
    clock.t += 30
    assert reader.tick() is False                 # not a minute yet
    clock.t += 31
    assert reader.tick() is True
    later.run_all()
    assert len(run.checks()) == 2


def test_no_task_waiting_on_grok_means_no_check(tmp_path):
    for tasks in ([], [{"task_id": "sr-1", "waiting_on": "pick"}], [{"task_id": "sr-1", "outcome": "passed"}]):
        reader, run, clock, later = _reader(tasks)
        assert reader.tick() is False and later.jobs == []


def test_never_two_checks_at_once_with_the_dead_run_check(tmp_path):
    reader, run, clock, later = _reader([{"task_id": "sr-1", "waiting_on": "grok"}])
    reader._checking = True                        # the dead-run check is running
    assert reader.tick() is False and later.jobs == []
    reader._checking = False
    assert reader.tick() is True
    clock.t += 120
    assert reader.tick() is False                  # the first is still out
    later.run_all()
    clock.t += 61
    assert reader.tick() is True


def test_a_check_runs_in_its_own_session_and_lands_in_the_run_log(tmp_path):
    runs = page_runs.Runs(root=tmp_path, prefix=PREFIX)
    reader, run, clock, later = _reader([{"task_id": "sr-1", "waiting_on": "grok", "pid": None}], runs=runs)
    reader.tick()
    later.run_all()
    kw = run.checks()[0]
    assert kw["start_new_session"] is True and kw["stdin"] is page.subprocess.DEVNULL and kw["cwd"] == str(page.ROOT)
    found = runs.list()[0]
    assert (found["kind"], found["display"], found["exit"], found["message"], found["running"]) == (
        "check", "sr check --json", 0, "checked", False)


def test_the_memory_start_at_launch_runs_in_its_own_session_and_lands_in_the_run_log(tmp_path):
    runs, seen, lines = page_runs.Runs(root=tmp_path, prefix=PREFIX), [], []

    def run(argv, **kw):
        seen.append(kw)
        return SimpleNamespace(returncode=0, stdout="memory: already online\n", stderr="")
    page.start_memory(run=run, out=lines.append, runs=runs)
    assert seen[0]["start_new_session"] is True and lines == ["memory: already online"]
    assert runs.list()[0]["kind"] == "memory" and runs.list()[0]["exit"] == 0


def test_the_page_modules_never_use_a_shell_or_a_string_command():
    for name in ("page.py", "page_runs.py", "page_commands.py"):
        text = (Path(page.__file__).parent / name).read_text(encoding="utf-8")
        assert "shell=True" not in text and "os.system" not in text and "os.popen" not in text, name


def test_the_ticker_ticks_once_a_minute_and_survives_a_failing_tick():
    slept, ticks = [], []

    class Reader:
        def tick(self):
            ticks.append(1)
            if len(ticks) == 1:
                raise OSError("the log could not be read")
    page.ticker(Reader(), sleep=slept.append, rounds=3)
    assert slept == [60, 60, 60] and len(ticks) == 3 and page.GROK_CHECK_SECONDS == 60
