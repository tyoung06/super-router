"""Build brief 28, C1 (decision 20; Tests, "Server"): the page's six new actions, each argv built by the server and run as
`sr` (tests/fake_sr.py: no router, no model): `land`, `undo` and `discard` by task id, `project_files` with dropped files,
`project_git`, and `project_tests` with the words as one argument after `--` (or `--clear`). A bad name, task id or path
answers 400 before anything runs; Turn on undo's dry run is a read beside `/api/project-check`; the demo answers 409 to
every POST; a successful project action drops the kept status. Every value here is fake."""
import json

import pytest

from router import page, page_commands
from tests.test_page_project_new import CheckReads, _ran, demo  # noqa: F401 (the demo fixture)
from tests.test_page_server import Reads, _call, _wait, repo, world  # noqa: F401 (the fixtures)

TASK = "sr-20261027-090000-ab12"


def _run(world, request, monkeypatch, tmp_path):
    out = tmp_path / "argv.jsonl"
    monkeypatch.setenv("FAKE_SR_OUT", str(out))
    resp, body = _call(world.srv, "POST", "/api/run", request)
    if resp.status == 200:
        _wait(world.runs)
    return resp, json.loads(body), _ran(out)


@pytest.mark.parametrize("verb", ["land", "undo", "discard"])
def test_land_undo_and_discard_run_by_task_id(world, monkeypatch, tmp_path, verb):
    resp, body, ran = _run(world, {"action": verb, "task_id": TASK}, monkeypatch, tmp_path)
    assert resp.status == 200 and body["argv"] == [verb, "--json", TASK] and ran == [[verb, "--json", TASK]]


@pytest.mark.parametrize("verb", ["land", "undo", "discard"])
@pytest.mark.parametrize("task", ["#5", "5", "sr-1", "--json", None, "sr-20261027-090000-ab12 x"])
def test_a_bad_task_id_answers_400_and_runs_nothing(world, monkeypatch, tmp_path, verb, task):
    resp, body, ran = _run(world, {"action": verb, "task_id": task}, monkeypatch, tmp_path)
    assert resp.status == 400 and "task id" in body["error"] and ran == [] and world.runs.list() == []


def test_project_files_takes_files_dropped_at_the_drop_folders_top_level(world, monkeypatch, tmp_path):
    drop = tmp_path / "Router Drop"
    drop.mkdir(exist_ok=True)
    a, b = drop / "calc.py", drop / "test_calc.py"
    a.write_text("x\n")
    b.write_text("y\n")
    resp, body, ran = _run(world, {"action": "project_files", "name": "garden", "files": [str(a), str(b)]},
                           monkeypatch, tmp_path)
    assert resp.status == 200
    assert ran == [["project", "files", "--json", "garden", "--file", str(a), "--file", str(b)]]


@pytest.mark.parametrize("files,why", [
    ([], "at least one dropped file"), (None, "at least one dropped file"), (["/etc/hosts"], "drop folder's top level"),
    (["-rf"], "starts with -"),
])
def test_a_bad_file_answers_400_and_runs_nothing(world, monkeypatch, tmp_path, files, why):
    resp, body, ran = _run(world, {"action": "project_files", "name": "garden", "files": files}, monkeypatch, tmp_path)
    assert resp.status == 400 and why in body["error"] and ran == []


def test_a_file_named_twice_is_refused(world, monkeypatch, tmp_path):
    drop = tmp_path / "Router Drop"
    drop.mkdir(exist_ok=True)
    (drop / "a.csv").write_text("a\n")
    resp, body, ran = _run(world, {"action": "project_files", "name": "garden", "files": [str(drop / "a.csv")] * 2},
                           monkeypatch, tmp_path)
    assert resp.status == 400 and "named twice" in body["error"] and ran == []


def test_project_git_runs_turn_on_undo(world, monkeypatch, tmp_path):
    resp, body, ran = _run(world, {"action": "project_git", "name": "plain-folder"}, monkeypatch, tmp_path)
    assert resp.status == 200 and ran == [["project", "git", "--json", "plain-folder"]]


@pytest.mark.parametrize("words", ["python3 -m unittest", "pytest -k 'add and not slow'", "-h", "--json", 'say "hi"',
                                   "$HOME/x"])
def test_the_test_words_reach_sr_as_one_argument_after_dashes(world, monkeypatch, tmp_path, words):
    resp, body, ran = _run(world, {"action": "project_tests", "name": "garden", "words": words}, monkeypatch, tmp_path)
    assert resp.status == 200 and ran == [["project", "tests", "--json", "garden", "--", words]]


def test_clearing_the_test_command(world, monkeypatch, tmp_path):
    resp, body, ran = _run(world, {"action": "project_tests", "name": "garden", "clear": True}, monkeypatch, tmp_path)
    assert resp.status == 200 and ran == [["project", "tests", "--json", "--clear", "garden"]]


@pytest.mark.parametrize("request_,why", [
    ({"name": "garden", "words": ""}, "type the test command"), ({"name": "garden", "words": "x" * 301}, "at most 300"),
    ({"name": "garden", "words": "a\nb"}, "control character"), ({"name": "garden", "clear": True, "words": "x"}, "not both"),
    ({"name": "Garden", "words": "x"}, "the project name"), ({"name": "-h", "words": "x"}, "the project name"),
])
def test_bad_test_words_answer_400_and_run_nothing(world, monkeypatch, tmp_path, request_, why):
    resp, body, ran = _run(world, {"action": "project_tests", **request_}, monkeypatch, tmp_path)
    assert resp.status == 400 and why in body["error"] and ran == []


@pytest.mark.parametrize("action", ["project_files", "project_git", "project_tests"])
@pytest.mark.parametrize("name", ["Seed", "-h", "a/b", "", None])
def test_a_bad_project_name_answers_400(world, monkeypatch, tmp_path, action, name):
    resp, body, ran = _run(world, {"action": action, "name": name, "words": "x", "files": ["x"]}, monkeypatch, tmp_path)
    assert resp.status == 400 and ran == []


# ---------- Turn on undo's dry run, GET /api/project-git-check ----------

class GitCheckReads(CheckReads):
    def __call__(self, argv, **kw):
        if argv[3:5] == ["project", "git"]:
            self.calls.append(argv)
            doc = {"api_version": 1, "would": "turn_on", "name": argv[-1], "files": 2, "bytes": 40,
                   "names": [".gitignore", "notes.txt"], "more": 0, "gitignore": {"exists": False, "adds": [".env"]},
                   "reason_code": None, "message": "m"}
            from types import SimpleNamespace
            return SimpleNamespace(returncode=0, stdout=json.dumps(doc) + "\n", stderr="")
        return super().__call__(argv, **kw)


def test_the_git_check_runs_only_the_dry_run(world):
    reads = GitCheckReads(world.tmp)
    world.srv.reader.run = reads
    resp, body = _call(world.srv, "GET", "/api/project-git-check?name=plain-folder")
    assert resp.status == 200 and json.loads(body)["would"] == "turn_on"
    assert [argv[3:] for argv in reads.calls] == [["project", "git", "--json", "--dry-run", "plain-folder"]]
    assert _call(world.srv, "GET", "/api/project-git-check?name=Bad")[0].status == 400
    assert _call(world.srv, "GET", "/api/project-git-check?name=plain-folder", token=False)[0].status == 403


# ---------- the demo and the kept status ----------

@pytest.mark.parametrize("request_", [{"action": "land", "task_id": TASK}, {"action": "undo", "task_id": TASK},
                                      {"action": "discard", "task_id": TASK},
                                      {"action": "project_git", "name": "garden-site"},
                                      {"action": "project_tests", "name": "garden-site", "words": "python3 -m unittest"}])
def test_the_demo_answers_409_to_every_post(demo, request_):
    resp, body = _call(demo, "POST", "/api/run", request_)
    assert resp.status == 409 and json.loads(body)["message"] == "Demo: nothing runs."


@pytest.mark.parametrize("action", ["land", "undo", "discard", "project_files", "project_git", "project_tests"])
def test_a_successful_project_action_drops_the_kept_status(action):
    dropped = []

    class Reader:
        def forget_status(self):
            dropped.append(1)
    page._after_run(Reader(), {"request": {"action": action}}, 0)
    page._after_run(Reader(), {"request": {"action": action}}, 2)  # a refusal changed nothing
    assert dropped == [1]


def test_the_page_runs_the_six_new_actions():
    assert {"land", "undo", "discard", "project_files", "project_git", "project_tests"} <= set(page_commands.ACTIONS)
