"""Build brief 28 (decision 19; Tests, "JSON keys"): status gains `git` and `test_sandbox`, and per project its git, branch,
head, test words, `files_mode` and why; Claude's probe gains `files`. A task row gains `project_files`, each call its
`tests`; a change waiting to land is `waiting_on: land` with no outcome and is among the open tasks. `land`, `undo`,
`discard` and the project verbs answer with brief 21's envelope. A JSON read never makes a model call, never runs a test
and never writes. Real git in temp folders; fakes for every agent."""
import json
import os
from pathlib import Path

import pytest

from router import __main__ as cli
from router import copies, filecalls, gitops, log, probes, projects, search, testrun
from tests.fixtures import json_shapes
from tests.test_copies import git, make_repo
from tests.test_filemode_flow import BUILD, CopyWorker, route
from tests.test_status import world  # noqa: F401


@pytest.fixture
def garden(world, real_git, tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "config" / "projects.json")
    monkeypatch.setattr(projects, "TESTS_PATH", tmp_path / "config" / "project_tests.json")
    monkeypatch.setattr(testrun, "available", lambda: True)
    folder = tmp_path / "garden"
    make_repo(folder, {"calc.py": "def add(a, b):\n    return a - b\n"})
    projects.add("garden", str(folder))
    git(folder, "add", "HANDOFF.md")
    git(folder, "commit", "-q", "-m", "handoff")
    plain = tmp_path / "plain"
    plain.mkdir()
    projects.add("plain", str(plain))
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    return folder


def status(world):
    code, out, err = world.run("status", "--json")
    assert code == 0 and err == "", (out, err)
    return json.loads(out)


def test_status_has_git_the_test_sandbox_and_each_projects_file_mode(world, garden):
    doc = status(world)
    json_shapes.check(doc, json_shapes.STATUS, optional=("report_path",))
    assert doc["git"]["installed"] is True and doc["git"]["version"]
    assert doc["test_sandbox"] == {"available": True, "why": None}
    by = {p["name"]: p for p in doc["projects"]}
    assert by["garden"]["git"] is True and by["garden"]["branch"] == "main"
    assert by["garden"]["head"] == git(garden, "rev-parse", "--short=7", "HEAD").decode().strip()
    assert by["garden"]["tests"] == ["python3", "-m", "unittest"]
    assert (by["garden"]["files_mode"], by["garden"]["why"]) == ("on", None)  # the check hasn't run: intake runs it first
    assert (by["plain"]["git"], by["plain"]["files_mode"], by["plain"]["why"], by["plain"]["tests"]) == (
        False, "off", "no git yet: Turn on undo", None)
    probes.record_failure(cli.PROBE_STATE, "claude_files", "2.1.305", probes.RAN_FAILED, "no command ran: Bash ran")
    by = {p["name"]: p for p in status(world)["projects"]}
    assert (by["garden"]["files_mode"], by["garden"]["why"]) == ("off", (
        "Claude's file check failed on Claude Code 2.1.305 (no command ran: Bash ran); file mode is off on this version"))
    probes.clear_failure(cli.PROBE_STATE, "claude_files")
    search.record_pass(cli.PROBE_STATE, "2.1.305", key="claude_files")
    by = {p["name"]: p for p in status(world)["projects"]}
    assert (by["garden"]["files_mode"], by["garden"]["why"]) == ("on", None)
    assert next(a for a in status(world)["agents"] if a["name"] == "claude")["probe"]["files"] == "passed"


def test_a_missing_sandbox_says_why_tests_are_off(world, garden, monkeypatch):
    monkeypatch.setattr(testrun, "available", lambda: False)
    assert status(world)["test_sandbox"] == {"available": False,
                                             "why": "this Mac has no sandbox-exec, so no project's tests run"}


def test_a_waiting_change_waits_on_land_in_show_log_and_status(world, garden, monkeypatch):
    conn = log.init_db(cli.DB_PATH)
    monkeypatch.setattr(testrun, "run", lambda folder, words, **kw: testrun.Result(0, "passed", "OK", "OK"))
    code, out, row = route(conn, worker=CopyWorker(BUILD))
    conn.close()
    code, out, err = world.run("show", row["task_id"], "--json")
    doc = json.loads(out)
    json_shapes.check(doc, json_shapes.SHOW)
    assert (doc["waiting_on"], doc["outcome"]) == ("land", None)
    files = doc["project_files"]
    assert files["state"] == "waiting" and files["changed"][0] == {"path": "calc.py", "status": "changed", "plus": 1,
                                                                   "minus": 1}
    assert files["diff"] == f"tasks/{row['task_id']}/changes.diff" and files["base"] and files["branch"] == "main"
    do = next(c for c in doc["calls"] if c["kind"] == "do")
    assert do["tests"]["outcome"] == "passed" and do["tests"]["output"] == f"tasks/{row['task_id']}/tests-1.txt"
    code, out, err = world.run("log", "--json")
    first = json.loads(out)["tasks"][0]
    assert first["project_files"]["state"] == "waiting" and first["waiting_on"] == "land"
    assert [t["waiting_on"] for t in status(world)["open_tasks"]] == ["land"]


def test_land_undo_and_discard_answer_with_the_envelope(world, garden, monkeypatch):
    conn = log.init_db(cli.DB_PATH)
    monkeypatch.setattr(testrun, "run", lambda folder, words, **kw: testrun.Result(0, "passed", "OK", "OK"))
    code, out, row = route(conn, worker=CopyWorker(BUILD))
    conn.close()
    code, out, err = world.run("land", str(row["n"]), "--json")
    found = json.loads(out)
    assert code == 0 and found["exit"] == 0 and found["task_id"] == row["task_id"]
    assert found["commit"] == git(garden, "rev-parse", "HEAD").decode().strip() and found["paths"] == ["calc.py", "test_calc.py"]
    assert (found["waiting_on"], found["outcome"]) == (None, "passed")
    code, out, err = world.run("land", str(row["n"]), "--json")
    found = json.loads(err)
    assert code == 2 and found["reason_code"] == "wrong_state" and found["exit"] == 2
    code, out, err = world.run("undo", str(row["n"]), "--json")
    assert code == 0 and json.loads(out)["commit"] == git(garden, "rev-parse", "HEAD").decode().strip()
    code, out, err = world.run("discard", str(row["n"]), "--json")
    assert code == 2 and json.loads(err)["reason_code"] == "wrong_state"


def test_a_json_read_writes_nothing_and_runs_no_test(world, garden, monkeypatch):
    def no_test(*a, **kw):
        raise AssertionError("a JSON read ran a test")
    monkeypatch.setattr(testrun, "run", no_test)
    before = sorted((p.relative_to(garden).as_posix(), p.stat().st_mtime_ns) for p in garden.rglob("*"))
    log.init_db(cli.DB_PATH).close()
    db_before = cli.DB_PATH.read_bytes()
    status(world)
    world.run("log", "--json")
    assert cli.DB_PATH.read_bytes() == db_before  # the three reads open the log read only
    world.run("project", "git", "plain", "--dry-run", "--json")  # Turn on undo's dry run writes nothing in a project
    assert sorted((p.relative_to(garden).as_posix(), p.stat().st_mtime_ns) for p in garden.rglob("*")) == before
    assert not (Path(projects.folder_of("plain")) / ".git").exists()
