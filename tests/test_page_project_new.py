"""Build brief 26, B (decisions 9, 10, 11, 15): the page server's New project. `project_new` runs `sr project new --json
<name> [-- <notes>]` with the notes as one argument after `--`, whatever they hold; a bad name answers 400 and runs
nothing. The actions run tests/fake_sr.py (no router, no model); the reads are a fake. Every value here is fake."""
import json

import pytest

from tests.test_page_server import Reads, _call, _wait, repo, world  # noqa: F401 (the fixtures)

QUOTED = ['say "hi"', "it's", "a `tick`", "$HOME stays", "one\ntwo\n\nfour", "--skill coding", "-h"]


def _ran(out):
    return [json.loads(line) for line in out.read_text().splitlines()] if out.exists() else []


# ---------- project_new on /api/run (decision 9) ----------

def test_the_argv_without_notes(world, monkeypatch, tmp_path):
    out = tmp_path / "argv.jsonl"
    monkeypatch.setenv("FAKE_SR_OUT", str(out))
    resp, body = _call(world.srv, "POST", "/api/run", {"action": "project_new", "name": "seed-trays", "notes": ""})
    assert resp.status == 200 and json.loads(body)["argv"] == ["project", "new", "--json", "seed-trays"]
    _wait(world.runs)
    assert _ran(out) == [["project", "new", "--json", "seed-trays"]]


@pytest.mark.parametrize("notes", QUOTED)
def test_the_notes_reach_sr_as_one_argument_after_dashes(world, monkeypatch, tmp_path, notes):
    out = tmp_path / "argv.jsonl"
    monkeypatch.setenv("FAKE_SR_OUT", str(out))
    resp, body = _call(world.srv, "POST", "/api/run", {"action": "project_new", "name": "seed-trays", "notes": notes})
    assert resp.status == 200
    _wait(world.runs)
    assert _ran(out) == [["project", "new", "--json", "seed-trays", "--", notes]]


@pytest.mark.parametrize("name", ["Seed", "-h", "--dry-run", "a/b", "", None])
def test_a_bad_name_answers_400_and_runs_nothing(world, monkeypatch, tmp_path, name):
    out = tmp_path / "argv.jsonl"
    monkeypatch.setenv("FAKE_SR_OUT", str(out))
    resp, body = _call(world.srv, "POST", "/api/run", {"action": "project_new", "name": name, "notes": "x"})
    assert resp.status == 400 and "the project name" in json.loads(body)["error"]
    assert world.runs.list() == [] and _ran(out) == []


# ---------- the folder check, GET /api/project-check (decision 10) ----------

class CheckReads(Reads):
    """The fake reads plus the dry run: `sr project new --json --dry-run <name>` answers `would: create`."""

    def __call__(self, argv, **kw):
        if argv[3:5] == ["project", "new"]:
            assert isinstance(argv, list) and not kw.get("shell")
            self.calls.append(argv)
            doc = {"api_version": 1, "would": "create", "name": argv[-1], "folder": f"~/Projects/{argv[-1]}",
                   "handoff": {"exists": False, "lines": None, "has_block": False}, "reason_code": None, "message": "m"}
            from types import SimpleNamespace
            return SimpleNamespace(returncode=0, stdout=json.dumps(doc) + "\n", stderr="")
        return super().__call__(argv, **kw)


@pytest.fixture
def checking(world):
    reads = CheckReads(world.tmp)
    world.srv.reader.run = reads
    return reads


def test_the_check_runs_only_the_dry_run_and_returns_its_json(world, checking):
    resp, body = _call(world.srv, "GET", "/api/project-check?name=seed-trays")
    assert resp.status == 200 and json.loads(body)["would"] == "create"
    assert [argv[3:] for argv in checking.calls] == [["project", "new", "--json", "--dry-run", "seed-trays"]]


def test_the_check_is_not_cached(world, checking):
    for _ in range(3):
        assert _call(world.srv, "GET", "/api/project-check?name=seed-trays")[0].status == 200
    assert checking.count("project") == 3


@pytest.mark.parametrize("query", ["name=Seed", "name=-h", "name=--dry-run", "name=a%2Fb", "name=", "", "name=a.b"])
def test_a_bad_name_answers_400_before_any_run(world, checking, query):
    resp, body = _call(world.srv, "GET", "/api/project-check?" + query)
    assert resp.status == 400 and "the project name" in json.loads(body)["error"] and checking.calls == []


def test_the_check_needs_the_token(world, checking):
    assert _call(world.srv, "GET", "/api/project-check?name=seed-trays", token=False)[0].status == 403
    assert checking.calls == []


def test_a_dry_run_that_fails_is_a_502_with_its_words(world):
    from types import SimpleNamespace
    world.srv.reader.run = lambda argv, **kw: SimpleNamespace(
        returncode=2, stdout="", stderr=json.dumps({"exit": 2, "reason_code": "usage", "message": "Refused: x"}) + "\n")
    resp, body = _call(world.srv, "GET", "/api/project-check?name=seed-trays")
    assert resp.status == 502 and json.loads(body)["reason_code"] == "usage"


# ---------- the demo (decision 15) ----------

@pytest.fixture
def demo(monkeypatch):
    import subprocess
    import threading
    from router import page

    def no_run(*a, **k):
        raise AssertionError("the demo runs nothing")
    monkeypatch.setattr(subprocess, "run", no_run)
    monkeypatch.setattr(subprocess, "Popen", no_run)
    srv = page.make_server(0, demo=True, platform="darwin")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_the_demo_check_answers_from_its_own_projects(demo):
    found = json.loads(_call(demo, "GET", "/api/project-check?name=seed-trays")[1])
    assert (found["would"], found["folder"], found["reason_code"]) == ("create", "~/Projects/seed-trays", None)
    assert found["handoff"] == {"exists": False, "lines": None, "has_block": False}
    found = json.loads(_call(demo, "GET", "/api/project-check?name=garden-site")[1])
    assert (found["would"], found["folder"], found["reason_code"]) == ("refused", "~/Projects/garden-site", "project_refused")
    assert "garden-site is already registered" in found["message"]
    assert _call(demo, "GET", "/api/project-check?name=Bad")[0].status == 400


def test_the_demo_refuses_a_create(demo):
    resp, body = _call(demo, "POST", "/api/run", {"action": "project_new", "name": "seed-trays", "notes": ""})
    assert resp.status == 409 and json.loads(body)["message"] == "Demo: nothing runs."


# ---------- the kept status dropped after a create (decision 11) ----------

def _status_reads(world):
    return world.reads.count("status")


def test_a_successful_create_drops_the_kept_status(world):
    _call(world.srv, "GET", "/api/status")
    _call(world.srv, "GET", "/api/status")
    assert _status_reads(world) == 1  # kept
    assert _call(world.srv, "POST", "/api/run", {"action": "project_new", "name": "seed-trays", "notes": "x"})[0].status == 200
    _wait(world.runs)
    _call(world.srv, "GET", "/api/status")  # no ?fresh=1 and no 10 s wait: the next plain read is fresh
    assert _status_reads(world) == 2


def test_a_refused_create_leaves_the_kept_status(world, monkeypatch):
    monkeypatch.setenv("FAKE_SR_EXIT", "2")
    _call(world.srv, "GET", "/api/status")
    _call(world.srv, "POST", "/api/run", {"action": "project_new", "name": "seed-trays", "notes": "x"})
    _wait(world.runs)
    _call(world.srv, "GET", "/api/status")
    assert _status_reads(world) == 1


def test_another_action_leaves_the_kept_status(world):
    _call(world.srv, "GET", "/api/status")
    _call(world.srv, "POST", "/api/run", {"action": "check"})
    _wait(world.runs)
    _call(world.srv, "GET", "/api/status")
    assert _status_reads(world) == 1


def test_the_hook_runs_before_the_run_reads_as_finished(tmp_path):
    import sys
    from router import page_runs
    from tests.test_page_server import FAKE_SR
    seen = []
    runs = page_runs.Runs(root=tmp_path, prefix=[sys.executable, str(FAKE_SR)])
    runs.on_finished = lambda run, code: seen.append((runs.get(run["id"])["running"], run["request"], code))
    runs.start(["project", "new", "--json", "seed-trays"], "sr project new --json seed-trays",
               request={"action": "project_new", "name": "seed-trays"})
    _wait(runs)
    assert seen == [(True, {"action": "project_new", "name": "seed-trays"}, 0)]
