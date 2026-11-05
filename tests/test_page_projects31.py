"""Build brief 31 (the server's part): the new actions build their argv exactly in Python, every refusal answers 400
before anything runs, and the project output read runs `sr project test|run --json <name> --status` as an argument list
(a bad name or kind is a 400). The actions run tests/fake_sr.py (no router, no model); the reads are a fake. Every value
here is fake."""
import json
from types import SimpleNamespace

import pytest

from router import page
from router import page_commands as pc
from tests.test_page_server import _call, _wait, repo, world  # noqa: F401 (the fixtures)


def _ran(out):
    return [json.loads(line) for line in out.read_text().splitlines()] if out.exists() else []


# ---------- T: Test (decisions 1 and 2) ----------

def test_a_test_is_its_projects_name_and_nothing_else():
    command = pc.build({"action": "project_test", "name": "seed-trays"}, {})
    assert list(command.args) == ["project", "test", "--json", "seed-trays"]
    assert command.copy() == "sr project test seed-trays"


@pytest.mark.parametrize("request_", [
    {"action": "project_test"},
    {"action": "project_test", "name": "-h"},
    {"action": "project_test", "name": "seed trays"},
])
def test_a_bad_test_request_is_refused_before_anything_runs(request_):
    with pytest.raises(pc.Refused):
        pc.build(request_, {})


def test_a_test_reaches_sr_exactly_and_its_end_drops_the_kept_status(world, monkeypatch, tmp_path):
    out = tmp_path / "argv.jsonl"
    monkeypatch.setenv("FAKE_SR_OUT", str(out))
    dropped = []
    world.srv.reader.forget_status = lambda: dropped.append(True)
    resp, body = _call(world.srv, "POST", "/api/run", {"action": "project_test", "name": "seed-trays"})
    assert resp.status == 200
    _wait(world.runs)
    assert _ran(out) == [["project", "test", "--json", "seed-trays"]]
    assert dropped  # decision 11: status carries the last Test
    assert "project_test" in page.DROPS_STATUS


class OutputReads:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        assert isinstance(argv, list) and not kw.get("shell")
        self.calls.append(argv[3:])
        doc = {"api_version": 1, "project": {"name": argv[-2], "test_status": {"running": False, "output": "OK\n"}}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(doc) + "\n", stderr="")


def test_the_output_read_runs_sr_project_test_status_and_refuses_a_bad_name_or_kind(world):
    reads = OutputReads()
    world.srv.reader.run = reads
    resp, body = _call(world.srv, "GET", "/api/project-output?name=seed-trays&kind=test")
    assert resp.status == 200 and json.loads(body)["project"]["test_status"]["output"] == "OK\n"
    assert reads.calls == [["project", "test", "--json", "seed-trays", "--status"]]
    for query in ("name=-h&kind=test", "name=seed-trays&kind=shell", "name=seed-trays"):
        assert _call(world.srv, "GET", f"/api/project-output?{query}")[0].status == 400
    assert len(reads.calls) == 1
    assert _call(world.srv, "GET", "/api/project-output?name=seed-trays&kind=test", token=False)[0].status == 403


# ---------- R: the run command, Run and Stop (decisions 3 to 7) ----------

def test_the_run_command_is_one_argument_after_the_dashes_and_clear_takes_none():
    command = pc.build({"action": "project_run_command", "name": "seed-trays", "words": "python3 app.py --port 8000"}, {})
    assert list(command.args) == ["project", "run-command", "--json", "seed-trays", "--", "python3 app.py --port 8000"]
    command = pc.build({"action": "project_run_command", "name": "seed-trays", "clear": True}, {})
    assert list(command.args) == ["project", "run-command", "--json", "--clear", "seed-trays"]


def test_run_and_stop_are_the_projects_name_and_nothing_else():
    assert list(pc.build({"action": "project_run", "name": "seed-trays"}, {}).args) == ["project", "run", "--json", "seed-trays"]
    assert list(pc.build({"action": "project_stop", "name": "seed-trays"}, {}).args) == ["project", "stop", "--json", "seed-trays"]


@pytest.mark.parametrize("request_", [
    {"action": "project_run_command", "name": "seed-trays", "words": "   "},
    {"action": "project_run_command", "name": "seed-trays", "words": "x" * 301},
    {"action": "project_run_command", "name": "seed-trays", "words": "python3 app.py\x07"},
    {"action": "project_run_command", "name": "seed-trays", "clear": True, "words": "python3 app.py"},
    {"action": "project_run", "name": "-h"},
    {"action": "project_stop"},
])
def test_a_bad_run_request_is_refused_before_anything_runs(request_):
    with pytest.raises(pc.Refused):
        pc.build(request_, {})


def test_run_and_stop_reach_sr_exactly_and_drop_the_kept_status(world, monkeypatch, tmp_path):
    out = tmp_path / "argv.jsonl"
    monkeypatch.setenv("FAKE_SR_OUT", str(out))
    dropped = []
    world.srv.reader.forget_status = lambda: dropped.append(True)
    for action in ("project_run", "project_stop"):
        resp, body = _call(world.srv, "POST", "/api/run", {"action": action, "name": "seed-trays"})
        assert resp.status == 200
        _wait(world.runs)
    assert _ran(out) == [["project", "run", "--json", "seed-trays"], ["project", "stop", "--json", "seed-trays"]]
    assert len(dropped) == 2


def test_the_run_output_read_runs_sr_project_run_status(world):
    reads = OutputReads()
    world.srv.reader.run = reads
    assert _call(world.srv, "GET", "/api/project-output?name=seed-trays&kind=run")[0].status == 200
    assert reads.calls == [["project", "run", "--json", "seed-trays", "--status"]]


# ---------- S: Secrets, the value on stdin (decisions 8 and 9) ----------

def _fake_value():
    return "hydrangea-" + "0123456789" + "-abcdef"  # built at run time from pieces


def test_a_secret_set_is_its_name_on_the_command_line_and_its_value_only_on_stdin():
    value = _fake_value()
    command = pc.build({"action": "project_secret_set", "name": "seed-trays", "key": "DEMO_KEY", "value": value}, {})
    assert list(command.args) == ["project", "secrets", "--json", "seed-trays", "--set", "DEMO_KEY"]
    assert command.stdin == value and value not in repr(command)
    assert command.copy() == "sr project secrets seed-trays --set DEMO_KEY"
    assert command.note() == f"(the value goes on stdin: {len(value)} characters, never shown)"
    assert value not in json.dumps(command.parts()) and value not in command.display()
    remove = pc.build({"action": "project_secret_remove", "name": "seed-trays", "key": "DEMO_KEY"}, {})
    assert list(remove.args) == ["project", "secrets", "--json", "seed-trays", "--remove", "DEMO_KEY"] and remove.stdin is None


@pytest.mark.parametrize("request_", [
    {"action": "project_secret_set", "name": "seed-trays", "key": "bad-name", "value": "x"},
    {"action": "project_secret_set", "name": "seed-trays", "key": "DEMO_KEY", "value": "one\ntwo"},
    {"action": "project_secret_set", "name": "seed-trays", "key": "DEMO_KEY", "value": "a\x00b"},
    {"action": "project_secret_set", "name": "seed-trays", "key": "DEMO_KEY", "value": "x" * 4097},
    {"action": "project_secret_set", "name": "seed-trays", "key": "DEMO_KEY"},
    {"action": "project_secret_remove", "name": "seed-trays", "key": "DEMO_KEY", "value": "x"},
])
def test_a_bad_secret_request_is_refused_before_anything_runs(request_):
    with pytest.raises(pc.Refused):
        pc.build(request_, {})


def test_the_value_reaches_only_the_childs_stdin_never_its_argv_the_runs_or_the_answer(world, monkeypatch, tmp_path):
    out = tmp_path / "argv.jsonl"
    monkeypatch.setenv("FAKE_SR_OUT", str(out))
    value = _fake_value()
    resp, body = _call(world.srv, "POST", "/api/run", {"action": "project_secret_set", "name": "seed-trays",
                                                       "key": "DEMO_KEY", "value": value})
    assert resp.status == 200 and value not in body.decode() and json.loads(body)["note"].endswith("never shown)")
    finished = _wait(world.runs)
    assert _ran(out) == [["project", "secrets", "--json", "seed-trays", "--set", "DEMO_KEY"]]
    assert finished[0]["envelope"]["stdin"] == len(value)  # the fake counted the value it read on stdin
    assert value not in json.dumps(world.runs.list())  # never on the run's record, its request included
    runs_body = _call(world.srv, "GET", "/api/runs")[1].decode()
    assert value not in runs_body


def test_the_secrets_read_runs_sr_project_secrets_and_refuses_a_bad_name(world):
    reads = OutputReads()
    world.srv.reader.run = reads
    assert _call(world.srv, "GET", "/api/project-secrets?name=seed-trays")[0].status == 200
    assert reads.calls == [["project", "secrets", "--json", "seed-trays"]]
    assert _call(world.srv, "GET", "/api/project-secrets?name=-h")[0].status == 400 and len(reads.calls) == 1
