"""Build brief 22, D1 (rules v2.31, Web search and Cursor; decision 7; Phase 0 choices 4 to 7 with the owner's amendment
to choice 6): the router runs the existing probes itself when a tool's installed version has no pass, one probe per
tool at a time by a lock, and a task waiting on it reads `waiting_on: probe`. A probe that ran and failed stays failed
for that version until the tool moves; one that could not run is tried again by the next task that needs it, at most
once an hour per tool and version, the task meanwhile running as a failed probe would. Fakes only: no probe here calls
a model, and every value is fake."""
import fcntl
import functools
import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from router import __main__ as cli
from router import claude_probe, cursor_probe, cursor_worker, locks, log, probes, runs, search, state, status
from tests.conftest import FAKE_START
from tests.helpers import shipped_roster

ROSTER = shipped_roster()
V1, V2 = "2.1.306", "2.1.307"
A1, A2 = "2026.10.21-aaaaaaa", "2026.10.22-bbbbbbb"
T0 = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


# ---------- fakes: the existing probes' results, recorded the way their command_check records them ----------

def _claude_result(version, outcome):
    if outcome == "pass":
        checks = [claude_probe.Check("claude ran to the end", True, ""), claude_probe.Check("WebSearch ran", True, "")]
    elif outcome == "fail":
        checks = [claude_probe.Check("claude ran to the end", True, ""),
                  claude_probe.Check("no other tool ran", False, "Bash")]
    else:  # could not run
        checks = [claude_probe.Check("claude ran to the end", False, "claude timed out after 300 s")]
    return claude_probe.Result(checks, version, 1.0)


class ClaudeProbes:
    """`checks` for the gate: each key makes a command_check that records a pass or clears it, as the real one does."""

    def __init__(self, path, version, outcome="pass"):
        self.path, self.version, self.outcome, self.ran = path, version, outcome, []

    def factory(self, key):
        def make():
            def run():
                self.ran.append(key)
                result = _claude_result(self.version, self.outcome)
                if result.passed:
                    search.record_pass(self.path, self.version, key=key)
                else:
                    search.clear(self.path, key=key)
                return result
            return run
        return make

    @property
    def checks(self):
        return {key: self.factory(key) for key in probes.CLAUDE_KEYS}


def _gate(tmp_path, version, fakes, out, now=T0, folder=None):
    return probes.claude_gate(tmp_path / "probe_state.json", folder=folder, out=out.append, checks=fakes.checks,
                              version=lambda: version, now=now)


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "probe_state.json"


# ---------- Claude ----------

def test_a_pass_on_the_installed_version_runs_nothing(tmp_path, state_path):
    search.record_pass(state_path, V1)
    fakes, out = ClaudeProbes(state_path, V1), []
    assert _gate(tmp_path, V1, fakes, out)() is True and fakes.ran == [] and out == []


def test_no_pass_runs_claudes_two_probes_records_them_and_answers(tmp_path, state_path):
    search.record_pass(state_path, "2.1.0")
    search.record_pass(state_path, "2.1.0", key=search.WEB_FILES)
    fakes, out = ClaudeProbes(state_path, V1), []
    assert _gate(tmp_path, V1, fakes, out)() is True
    assert fakes.ran == [search.SEARCH_KEY, search.WEB_FILES]  # exactly two probe runs
    assert search.passed_version(state_path, search.SEARCH_KEY) == V1 == search.passed_version(state_path, search.WEB_FILES)
    assert f"probe: claude search passed on Claude Code {V1}" in out
    assert f"probe: claude --web files passed on Claude Code {V1}" in out


def test_the_web_file_mode_alone_probes_only_what_is_missing(tmp_path, state_path):
    search.record_pass(state_path, V1)
    fakes, out = ClaudeProbes(state_path, V1), []
    assert _gate(tmp_path, V1, fakes, out)(search.WEB_FILES) is True and fakes.ran == [search.WEB_FILES]


def test_a_probe_that_ran_and_failed_stays_failed_until_claude_moves(tmp_path, state_path):
    fakes, out = ClaudeProbes(state_path, V1, "fail"), []
    assert _gate(tmp_path, V1, fakes, out)() is False and len(fakes.ran) == 2
    assert probes.failure(state_path, search.SEARCH_KEY)["kind"] == probes.RAN_FAILED
    assert any("FAILED" in line and "search stays off on this version" in line for line in out)
    fakes.ran.clear()
    assert _gate(tmp_path, V1, fakes, out, now=T0 + timedelta(days=3))() is False and fakes.ran == []  # no retry
    fakes.version, fakes.outcome = V2, "pass"
    assert _gate(tmp_path, V2, fakes, out)() is True and len(fakes.ran) == 2  # a new version: probed again


def test_a_probe_that_could_not_run_is_tried_again_after_an_hour(tmp_path, state_path):
    fakes, out = ClaudeProbes(state_path, V1, "could_not_run"), []
    assert _gate(tmp_path, V1, fakes, out)() is False
    assert probes.failure(state_path, search.SEARCH_KEY)["kind"] == probes.COULD_NOT_RUN
    assert any("could not run" in line and "tried again after" in line for line in out)
    fakes.ran.clear()
    assert _gate(tmp_path, V1, fakes, out, now=T0 + timedelta(minutes=59))() is False and fakes.ran == []
    fakes.outcome = "pass"
    assert _gate(tmp_path, V1, fakes, out, now=T0 + timedelta(minutes=61))() is True and len(fakes.ran) == 2
    assert probes.failure(state_path, search.SEARCH_KEY) is None  # a pass clears the record


def test_sr_probe_by_hand_stays_the_override(tmp_path, state_path):
    fakes, out = ClaudeProbes(state_path, V1, "fail"), []
    _gate(tmp_path, V1, fakes, out)()
    search.record_pass(state_path, V1)  # The owner's `sr probe` in Terminal passed
    fakes.ran.clear()
    assert _gate(tmp_path, V1, fakes, out)() is True and fakes.ran == []


def test_an_unknown_installed_version_never_probes(tmp_path, state_path):
    fakes, out = ClaudeProbes(state_path, "unknown"), []
    assert _gate(tmp_path, "unknown", fakes, out)() is False and fakes.ran == []


# ---------- the lock and waiting_on: probe ----------

def test_a_second_task_waits_on_the_lock_shows_waiting_on_probe_and_reads_the_first_ones_result(tmp_path, state_path):
    folder = tmp_path / "run"
    conn = log.init_db(tmp_path / "router.db")
    log.add_task(conn, "sr-1", "t", "cli", {"status": "ok", "label": "writing", "confidence": 0.9, "tokens": 1},
                 run=runs.me())
    runs.adopt("sr-1")
    other = os.open(locks._folder(folder, "locks") / "probe-claude.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(other, fcntl.LOCK_EX)  # another process is probing Claude
    fakes, out, seen = ClaudeProbes(state_path, V1), [], []

    def sleep(seconds):  # while this task waits: what a JSON read sees; then the other process records and lets go
        seen.append(locks.waiting_on(folder, log.get_task(conn, "sr-1")))
        search.record_pass(state_path, V1)
        search.record_pass(state_path, V1, key=search.WEB_FILES)
        os.close(other)

    gate = probes.claude_gate(state_path, folder=folder, out=out.append, checks=fakes.checks, version=lambda: V1,
                              now=T0, sleep=sleep)
    assert gate() is True and fakes.ran == []  # it read the other's pass and probed nothing
    assert seen == ["probe"]
    row = log.get_task(conn, "sr-1")
    assert state.of(row, [], waiting=locks.waiting_on(folder, row)) == state.State(None, None)  # done waiting
    assert state.of(row, [], waiting="probe") == state.State("probe", None)
    runs.release(conn, "sr-1")


def test_a_wait_note_left_by_a_dead_run_means_nothing(tmp_path):
    folder = tmp_path / "run"
    conn = log.init_db(":memory:")
    log.add_task(conn, "sr-1", "t", "cli", {"status": "ok", "label": "writing", "confidence": 0.9, "tokens": 1},
                 run=(4321, "2026-10-20T11:00:00+00:00"))
    locks._folder(folder, "waits")
    (folder / "waits" / "sr-1.json").write_text(json.dumps({"on": "probe", "pid": 999, "started": "x"}))
    assert locks.waiting_on(folder, log.get_task(conn, "sr-1")) is None


def test_the_lock_file_says_who_holds_it_only_while_held(tmp_path):
    folder = tmp_path / "run"
    with locks.held("probe-cursor", folder=folder, task_id=None):
        found = locks.holder(folder, "probe-cursor")
        assert (found["pid"], found["started"]) == runs.me()
    assert locks.holder(folder, "probe-cursor") is None
    assert oct((folder / "locks" / "probe-cursor.lock").stat().st_mode & 0o777) == "0o600"


# ---------- Cursor ----------

class CursorCanaries:
    """`check` for cursor_ready: the two canaries' result, recorded as cursor_probe.command_check records it."""

    def __init__(self, path, version, outcome="pass"):
        self.path, self.version, self.outcome, self.ran = path, version, outcome, 0

    def __call__(self):
        self.ran += 1
        if self.outcome == "skipped":
            return cursor_probe.Result([], self.version, 0.0, skipped="not signed in (agent login); the pass on record is missing")
        if self.outcome == "pass":
            checks = [cursor_probe.Check("read canary: agent ran to the end", True, "")]
        elif self.outcome == "fail":
            checks = [cursor_probe.Check("read canary: agent ran to the end", True, ""),
                      cursor_probe.Check("read canary: no read, shell or write completed", False, "readToolCall:success")]
        else:
            checks = [cursor_probe.Check("read canary: agent ran to the end", False, "agent timed out after 600 s")]
        result = cursor_probe.Result(checks, self.version, 1.0)
        if result.passed:
            search.record_pass(self.path, self.version, key=cursor_worker.SANDBOX_KEY)
        else:
            search.clear(self.path, key=cursor_worker.SANDBOX_KEY)
        return result


def _ready_for(path, version, signed_in=True):
    def ready(state_path):
        passed = search.passed_version(state_path, cursor_worker.SANDBOX_KEY)
        if passed != version:
            return cursor_worker.Readiness((False, "cursor: agent moved; run sr probe"), "probe_failed")
        if not signed_in:
            return cursor_worker.Readiness((False, "cursor: not signed in (agent login)"), "signed_out")
        return cursor_worker.Readiness((True, None))
    return ready


def _cursor(state_path, version, canaries, out, now=T0, signed_in=True):
    return probes.cursor_ready(state_path, model="grok-4.7-high", folder=None, out=out.append,
                               ready=_ready_for(state_path, version, signed_in), check=canaries,
                               installed=lambda: version, now=now)


def test_cursor_with_its_pass_on_the_installed_agent_runs_no_canary(state_path):
    search.record_pass(state_path, A1, key=cursor_worker.SANDBOX_KEY)
    canaries, out = CursorCanaries(state_path, A1), []
    assert tuple(_cursor(state_path, A1, canaries, out)) == (True, None) and canaries.ran == 0


def test_a_moved_agent_runs_the_two_canaries_and_goes_on_when_they_pass(state_path):
    search.record_pass(state_path, A1, key=cursor_worker.SANDBOX_KEY)
    canaries, out = CursorCanaries(state_path, A2), []
    assert tuple(_cursor(state_path, A2, canaries, out)) == (True, None) and canaries.ran == 1
    assert search.passed_version(state_path, cursor_worker.SANDBOX_KEY) == A2
    assert f"probe: Cursor's safety check passed on agent {A2}" in out


def test_canaries_that_ran_and_failed_refuse_in_plain_words_and_stay_failed(state_path):
    canaries, out = CursorCanaries(state_path, A2, "fail"), []
    found = _cursor(state_path, A2, canaries, out)
    assert (found[0], found.code) == (False, "probe_failed")
    assert found[1].startswith(f"Cursor's safety check failed on agent {A2}") and "stays off on this version" in found[1]
    assert "sr probe" not in found[1]
    found = _cursor(state_path, A2, canaries, out, now=T0 + timedelta(days=2))
    assert found[0] is False and canaries.ran == 1  # no second run on this version


def test_canaries_that_could_not_run_are_tried_again_after_an_hour(state_path):
    canaries, out = CursorCanaries(state_path, A2, "could_not_run"), []
    found = _cursor(state_path, A2, canaries, out)
    assert found.code == "probe_failed" and "could not run" in found[1] and "tried again after" in found[1]
    assert _cursor(state_path, A2, canaries, out, now=T0 + timedelta(minutes=30))[0] is False and canaries.ran == 1
    canaries.outcome = "pass"
    assert tuple(_cursor(state_path, A2, canaries, out, now=T0 + timedelta(minutes=61))) == (True, None)
    assert canaries.ran == 2 and probes.failure(state_path, cursor_worker.SANDBOX_KEY) is None


def test_signed_out_is_never_probed(state_path):
    search.record_pass(state_path, A1, key=cursor_worker.SANDBOX_KEY)
    canaries, out = CursorCanaries(state_path, A1), []
    found = _cursor(state_path, A1, canaries, out, signed_in=False)
    assert (found[0], found.code) == (False, "signed_out") and canaries.ran == 0


def test_a_cursor_slot_is_refused_before_any_row_when_the_canaries_fail(state_path, monkeypatch, tmp_path, capsys):
    from tests.test_json_actions import World
    world = World(monkeypatch, tmp_path, capsys)
    canaries = CursorCanaries(state_path, A2, "fail")
    monkeypatch.setattr(cli, "_workers", lambda environ, model, cursor_model=None: (world.worker, world.chatgpt, lambda *a, **k: "x"))
    monkeypatch.setattr(cli.probes, "cursor_ready", functools.partial(
        probes.cursor_ready, ready=_ready_for(state_path, A2), check=canaries, installed=lambda: A2, now=T0))
    monkeypatch.setattr(cli, "PROBE_STATE", state_path)
    found = world.json("relay", "versus", "write is_even", "--b", "cursor")
    assert (found["exit"], found["reason_code"], found["task_id"]) == (2, "probe_failed", None)
    assert "Cursor's safety check failed" in found["message"]
    conn = log.init_db(cli.DB_PATH)
    assert log.recent_tasks(conn) == []
    conn.close()


# ---------- status and main ----------

def test_status_names_a_failed_or_unrunnable_probe_on_the_current_version(state_path):
    probes.record_failure(state_path, search.SEARCH_KEY, V1, probes.RAN_FAILED, "no other tool ran: Bash", T0)
    probes.record_failure(state_path, cursor_worker.SANDBOX_KEY, A1, probes.COULD_NOT_RUN, "timed out", T0)
    assert status._probe("claude", state_path, V1)["state"] == "failed"
    assert status._probe("claude", state_path, V2)["state"] == "missing"
    assert status._probe("cursor", state_path, A1)["state"] == "could_not_run"


def test_main_hands_every_command_the_probing_gates(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.safety, "prepare_workspace", lambda *a, **k: None)
    monkeypatch.setattr(cli, "cmd_route", lambda *a, **kw: seen.update(kw) or 0)
    assert cli.main(["route", "hello"], platform="darwin") == 0
    ready = seen["cursor_ready"]
    assert isinstance(ready, functools.partial) and ready.func is probes.cursor_ready and ready.args == (cli.PROBE_STATE,)
    assert ready.keywords["folder"] == cli.DB_PATH.parent / runs.FOLDER_NAME
    gate = seen["claude_ready"]
    assert callable(gate) and gate.__qualname__.startswith("claude_gate")
