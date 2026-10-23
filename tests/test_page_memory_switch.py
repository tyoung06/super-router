"""Build brief 27, B (decisions 10, 14): the page's one new action, `memory_switch`. `{"to": "on"|"off"}` builds
`sr memory on|off --json` (`--json` marked as added); any other `to` answers 400 before anything runs; `/api/command`
builds it for the note's command line. A run that exits 0 drops the server's kept status; a refused one keeps it.
The demo answers 409. The actions run tests/fake_sr.py (no router, no model); the reads are a fake."""
import json

import pytest

from router import page_commands as pc
from tests.test_page_server import _call, _wait, repo, world  # noqa: F401 (the fixtures)


def _ran(out):
    return [json.loads(line) for line in out.read_text().splitlines()] if out.exists() else []


@pytest.mark.parametrize("to", ["on", "off"])
def test_the_builder_makes_sr_memory_on_or_off_json(to):
    command = pc.build({"action": "memory_switch", "to": to}, {})
    assert (list(command.args), command.added) == (["memory", to, "--json"], frozenset({2}))
    assert command.display() == f"sr memory {to} --json" and command.copy() == f"sr memory {to}"


@pytest.mark.parametrize("to", ["ON", "auto", "", None, "--help", "on --json", ["on"]])
def test_any_other_to_is_refused(to):
    with pytest.raises(pc.Refused, match="on or off"):
        pc.build({"action": "memory_switch", "to": to}, {})


@pytest.mark.parametrize("to", ["on", "off"])
def test_the_argv_reaches_sr_exactly(world, monkeypatch, tmp_path, to):
    out = tmp_path / "argv.jsonl"
    monkeypatch.setenv("FAKE_SR_OUT", str(out))
    resp, body = _call(world.srv, "POST", "/api/run", {"action": "memory_switch", "to": to})
    assert resp.status == 200 and json.loads(body)["argv"] == ["memory", to, "--json"]
    _wait(world.runs)
    assert _ran(out) == [["memory", to, "--json"]]


def test_a_bad_to_answers_400_and_runs_nothing(world, monkeypatch, tmp_path):
    out = tmp_path / "argv.jsonl"
    monkeypatch.setenv("FAKE_SR_OUT", str(out))
    resp, body = _call(world.srv, "POST", "/api/run", {"action": "memory_switch", "to": "rebuild"})
    assert resp.status == 400 and world.runs.list() == [] and _ran(out) == []


def test_the_command_line_for_the_note(world):
    resp, body = _call(world.srv, "POST", "/api/command", {"action": "memory_switch", "to": "off"})
    found = json.loads(body)
    assert resp.status == 200 and found["display"] == "sr memory off --json"
    assert [(p["text"], p["added"]) for p in found["parts"]] == [("sr", False), ("memory", False), ("off", False),
                                                                    ("--json", True)]


# ---------- the kept status (decision 10; the owner's choice 7: no drop when the run starts) ----------

def test_the_kept_status_is_not_dropped_when_a_switch_run_starts_only_when_it_ends(world, monkeypatch):
    monkeypatch.setenv("FAKE_SR_SLEEP", "1")  # the run is still going when the page reads status
    _call(world.srv, "GET", "/api/status")
    _call(world.srv, "POST", "/api/run", {"action": "memory_switch", "to": "on"})
    _call(world.srv, "GET", "/api/status")
    assert world.reads.count("status") == 1  # kept: no drop at the start (the owner's choice 7)
    _wait(world.runs)
    _call(world.srv, "GET", "/api/status")
    assert world.reads.count("status") == 2  # dropped at the end: the next plain read is fresh


def test_the_drop_happens_after_a_successful_run_and_not_after_a_refused_one(world, monkeypatch):
    _call(world.srv, "GET", "/api/status")
    _call(world.srv, "POST", "/api/run", {"action": "memory_switch", "to": "on"})
    _wait(world.runs)
    _call(world.srv, "GET", "/api/status")
    assert world.reads.count("status") == 2
    monkeypatch.setenv("FAKE_SR_EXIT", "2")
    _call(world.srv, "POST", "/api/run", {"action": "memory_switch", "to": "off"})
    _wait(world.runs)
    _call(world.srv, "GET", "/api/status")
    assert world.reads.count("status") == 2


def test_the_demo_answers_409(monkeypatch):
    import subprocess
    import threading
    from router import page

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("the demo runs nothing"))
    srv = page.make_server(0, demo=True, platform="darwin")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        resp, body = _call(srv, "POST", "/api/run", {"action": "memory_switch", "to": "off"})
        assert resp.status == 409 and json.loads(body)["message"] == "Demo: nothing runs."
    finally:
        srv.shutdown()
        srv.server_close()
