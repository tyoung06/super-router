"""Build brief 24, A5 (decision 10): ChatGPT's safety check runs itself. A Codex probe pass is kept per Codex version
(`codex_sandbox` in probe_state.json), as Cursor's is. Before ChatGPT's first call in a command, on a Codex version with no
pass, the router runs the existing `codex_probe` once (one ChatGPT call, one probe at a time by the `probe-codex` lock)
and goes on only after a pass. A failure makes ChatGPT unavailable on that version (availability reads it), and the call
that needed it is a failed call; one that could not run is tried again after an hour. `sr probe` stays the manual
override and records what it finds the same way. Fakes only: no probe here calls a model."""
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from router import __main__ as cli
from router import availability, codex_probe, locks, log, probes, status
from tests.conftest import REAL_CODEX_GATE
from tests.helpers import shipped_roster

ROSTER = shipped_roster()
V1, V2 = "0.162.1", "0.163.0"
T0 = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def _result(version, outcome):
    if outcome == "pass":
        checks = [codex_probe.Check("codex ran to the end", True, "exit 0, 9 events"),
                  codex_probe.Check("workspace/ unchanged", True)]
    elif outcome == "fail":
        checks = [codex_probe.Check("codex ran to the end", True, "exit 0, 9 events"),
                  codex_probe.Check("workspace/ unchanged", False, "new: probe.txt")]
    else:  # could not run
        checks = [codex_probe.Check("codex ran to the end", False, "exit -1, 0 events: codex timed out after 600 s")]
    return codex_probe.Result(checks, version, 1.0)


class Probe:
    def __init__(self, version=V1, outcome="pass"):
        self.version, self.outcome, self.ran = version, outcome, 0

    def __call__(self):
        self.ran += 1
        return _result(self.version, self.outcome)


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "probe_state.json"


def _gate(state_path, probe, version=V1, now=T0, lines=None):
    out = (lines if lines is not None else []).append
    return probes.chatgpt_gate(state_path, folder=None, out=out, check=probe, version=lambda: version, now=now)


def test_a_pass_on_the_installed_codex_runs_nothing(state_path):
    probes.record_codex(state_path, _result(V1, "pass"), T0)
    probe = Probe()
    assert _gate(state_path, probe)() == (True, None) and probe.ran == 0


def test_no_pass_runs_the_probe_once_records_it_and_goes_on(state_path):
    probe, lines = Probe(), []
    assert _gate(state_path, probe, lines=lines)() == (True, None)
    assert probe.ran == 1 and json.loads(state_path.read_text())["codex_sandbox"]["version"] == V1
    assert lines == [f"probe: ChatGPT's safety check has no pass on codex {V1}; probing (one ChatGPT call)",
                     f"probe: ChatGPT's safety check passed on codex {V1}"]
    assert _gate(state_path, probe)() == (True, None) and probe.ran == 1     # the next command: the pass stands
    assert _gate(state_path, Probe(V2), version=V2)() == (True, None)        # codex moved: probed again


def test_a_probe_that_ran_and_failed_keeps_chatgpt_off_on_that_version(state_path):
    probe, lines = Probe(outcome="fail"), []
    ok, why = _gate(state_path, probe, lines=lines)()
    assert (ok, probe.ran) == (False, 1)
    assert why == (f"ChatGPT's safety check failed on codex {V1} (workspace/ unchanged: new: probe.txt); ChatGPT stays off "
                   "on this version")
    assert lines[-1] == f"probe: {why}"
    assert _gate(state_path, probe, now=T0 + timedelta(days=2))() == (False, why) and probe.ran == 1  # never again
    found = availability.of("chatgpt", roster=ROSTER, names=frozenset(), doc={}, probe_data=json.loads(state_path.read_text()),
                            versions={"chatgpt": V1}, now=T0)
    assert (found.available, found.code) == (False, "probe_failed")
    assert found.why == f"ChatGPT is off: its safety check failed on codex {V1}"
    assert _gate(state_path, Probe(V2), version=V2)() == (True, None)       # a later Codex passes: on again


def test_a_probe_that_could_not_run_is_tried_again_after_an_hour(state_path):
    probe = Probe(outcome="could_not_run")
    ok, why = _gate(state_path, probe)()
    assert not ok and why.startswith(f"ChatGPT's safety check could not run on codex {V1} (codex ran to the end: ")
    assert _gate(state_path, probe, now=T0 + timedelta(minutes=30))()[0] is False and probe.ran == 1
    probe.outcome = "pass"
    assert _gate(state_path, probe, now=T0 + timedelta(minutes=61))() == (True, None) and probe.ran == 2
    assert "codex_sandbox_failure" not in json.loads(state_path.read_text())   # a pass clears the record


def test_an_unknown_codex_version_never_probes(state_path):
    probe = Probe()
    assert _gate(state_path, probe, version="unknown")() == (
        False, "ChatGPT's command line gave no version (is codex installed?)") and probe.ran == 0


def test_the_probe_runs_under_its_own_lock_and_the_task_waits_on_probe(state_path, monkeypatch):
    held = []

    @contextmanager
    def fake_held(name, **kw):
        held.append((name, kw["on"]))
        yield
    monkeypatch.setattr(locks, "held", fake_held)
    _gate(state_path, Probe())()
    assert held == [("probe-codex", "probe")]


def test_status_reads_the_codex_pass_like_cursors(state_path):
    assert status._probe("chatgpt", state_path, V1) == {"passed_on": None, "current": V1, "state": "missing"}
    probes.record_codex(state_path, _result(V1, "pass"), T0)
    assert status._probe("chatgpt", state_path, V1)["state"] == "passed"
    assert status._probe("chatgpt", state_path, V2)["state"] == "moved"
    probes.record_codex(state_path, _result(V2, "fail"), T0)
    assert status._probe("chatgpt", state_path, V2)["state"] == "failed"


# ---------- where the gate is asked ----------

def _task(conn):
    log.add_task(conn, "sr-20261021-120000-aa01", "a task", "cli", {"status": "ok", "label": "web_research",
                                                                  "confidence": 0.9, "tokens": 0})
    log.set_route(conn, "sr-20261021-120000-aa01", agents=tuple(ROSTER.agents), agent="chatgpt", route_reason="best",
                  skill="web_research", checker="claude", check_state="pending")
    return log.get_task(conn, "sr-20261021-120000-aa01")


def test_a_failed_probe_right_before_the_call_fails_that_call_and_runs_no_codex(monkeypatch):
    conn = log.init_db(":memory:")
    task, called, lines = _task(conn), [], []
    deps = SimpleNamespace(chatgpt=lambda *a, **k: called.append(a) or "an answer", codex_ok=True, codex_login=lambda: True,
                           chatgpt_ready=lambda: (False, "ChatGPT's safety check failed on codex 0.162.1 (x); ChatGPT stays "
                                                         "off on this version"))
    code = cli._send_chatgpt(conn, task, task["task_id"], "do", "a task", deps, secrets=(), out=lines.append)
    assert called == [] and code == 1
    row = log.get_call(conn, task["task_id"])
    assert (row["status"], row["text"]) == ("failed", deps.chatgpt_ready()[1])


def test_the_probe_is_asked_once_per_command(monkeypatch):
    conn = log.init_db(":memory:")
    task, asked = _task(conn), []
    deps = SimpleNamespace(chatgpt=lambda *a, **k: "an answer", codex_ok=True, codex_login=lambda: True,
                           chatgpt_ready=lambda: asked.append(1) or (True, None))
    cli._send_chatgpt(conn, task, "sr-20261021-120000-aa01-c9", "check", "a check", deps, secrets=(), out=lambda *a: None)
    cli._send_chatgpt(conn, task, "sr-20261021-120000-aa01-c8", "check", "a check", deps, secrets=(), out=lambda *a: None)
    assert asked == [1]


def test_main_hands_the_codex_gate_to_every_command_that_runs_agents(monkeypatch):
    built, seen = [], {}
    monkeypatch.setattr(cli, "_codex_gate", REAL_CODEX_GATE)  # the real builder, over conftest's stand-in
    monkeypatch.setattr(probes, "chatgpt_gate", lambda path, **kw: built.append((path, kw)) or (lambda: (True, None)))
    monkeypatch.setattr(cli.safety, "prepare_workspace", lambda *a, **k: None)
    monkeypatch.setattr(cli, "cmd_route", lambda *a, **kw: seen.update(kw) or 0)
    assert cli.main(["route", "hello"], platform="darwin") == 0
    assert callable(seen["chatgpt_ready"]) and built and built[0][0] == cli.PROBE_STATE
    assert built[0][1]["version"] is codex_probe.codex_version


def test_a_resume_or_fallback_onto_chatgpt_is_refused_while_its_safety_check_fails():
    from tests.test_resume_run import CONFIG, LOADED, ROSTER as RESUME_ROSTER, ROUTE_TASK, WRITING, Chat, Clock, Scripted, \
        Webhook, _route, claude_limit
    conn = log.init_db(":memory:")
    code, out, row = _route(conn, WRITING, worker=Scripted(claude_limit()))
    assert code == 1 and row["status"] == "failed"
    lines, clock, hook, chat = [], Clock(), Webhook(), Chat("an answer")
    why = "ChatGPT's safety check failed on codex 0.162.1 (x); ChatGPT stays off on this version"
    code = cli.cmd_resume([str(row["n"])], conn=conn, config=CONFIG, roster=RESUME_ROSTER, loaded=LOADED, environ={},
                          settings_paths=[], post=hook.post, worker=Scripted(), chatgpt=chat, codex_login=lambda: True,
                          fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True,
                          chatgpt_ready=lambda: (False, why), out=lines.append)
    assert code == 2 and lines[-1] == f"Refused: #{row['n']} can't be resumed: {why}. Nothing was logged or sent."
    assert chat.calls == [] if hasattr(chat, "calls") else True
    assert [c["call_id"] for c in log.calls_for(conn, row["task_id"])] == [row["task_id"]]  # nothing new written
