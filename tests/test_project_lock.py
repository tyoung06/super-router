"""Build brief 28, C4 (`/break-ui` on Land): one router write in a project at a time. A double click on the page's
Confirm started two `sr land` runs at once; nothing in the router stopped them. Now land, undo, discard, files in and
Turn on undo hold the lock `project-<name>` (`router/locks.py`, a flock, let go when its holder ends, crash included);
a second one meanwhile is refused at once with nothing written, naming what holds it. Real git in temp folders; fakes
for every agent."""
import json

import pytest

from router import __main__ as cli
from router import locks, log, runs, testrun
from tests.test_copies import git
from tests.test_filemode_flow import BUILD, CopyWorker, route
from tests.test_filemode_json import garden  # noqa: F401 (the fixture)
from tests.test_status import world  # noqa: F401 (the fixture)


def run_dir():
    return cli.DB_PATH.parent / runs.FOLDER_NAME


def test_a_lock_held_elsewhere_is_busy_at_once_without_waiting(tmp_path):
    slept = []
    with locks.held("project-garden", folder=tmp_path):
        with pytest.raises(locks.Busy):
            with locks.held("project-garden", folder=tmp_path, wait=False, sleep=slept.append):
                pass
    assert slept == []
    with locks.held("project-garden", folder=tmp_path, wait=False):  # let go: free again
        pass


@pytest.fixture
def waiting(world, garden, monkeypatch):
    conn = log.init_db(cli.DB_PATH)
    monkeypatch.setattr(testrun, "run", lambda folder, words, **kw: testrun.Result(0, "passed", "OK", "OK"))
    code, out, row = route(conn, worker=CopyWorker(BUILD))
    conn.close()
    assert row["project"] == "garden"
    return row


@pytest.mark.parametrize("verb", ["land", "discard"])
def test_a_second_land_or_discard_meanwhile_is_refused_with_nothing_written(world, garden, waiting, verb):
    head = git(garden, "rev-parse", "HEAD")
    with locks.held("project-garden", folder=run_dir(), task_id=waiting["task_id"]):
        code, out, err = world.run(verb, str(waiting["n"]), "--json")
    found = json.loads(err)
    assert code == 2 and found["reason_code"] == "land_refused"
    assert "another land, undo, discard or file change is running in garden" in found["message"]
    assert f"#{waiting['n']}" in found["message"] and found["message"].endswith("Nothing was changed.")
    assert git(garden, "rev-parse", "HEAD") == head
    code, out, err = world.run("show", str(waiting["n"]), "--json")
    assert json.loads(out)["project_files"]["state"] == "waiting"
    code, out, err = world.run("land", str(waiting["n"]), "--json")  # the lock let go: it lands
    assert code == 0 and json.loads(out)["commit"] == git(garden, "rev-parse", "HEAD").decode().strip()


def test_an_undo_meanwhile_is_refused(world, garden, waiting):
    assert world.run("land", str(waiting["n"]), "--json")[0] == 0
    head = git(garden, "rev-parse", "HEAD")
    with locks.held("project-garden", folder=run_dir()):
        code, out, err = world.run("undo", str(waiting["n"]), "--json")
    assert code == 2 and json.loads(err)["reason_code"] == "land_refused" and git(garden, "rev-parse", "HEAD") == head


def test_files_in_and_turn_on_undo_meanwhile_are_refused(world, garden, tmp_path):
    source = tmp_path / "notes.csv"
    source.write_text("a,b\n")
    head = git(garden, "rev-parse", "HEAD")
    with locks.held("project-garden", folder=run_dir()):
        code, out, err = world.run("project", "files", "garden", "--file", str(source), "--json")
    found = json.loads(err)
    assert code == 2 and found["reason_code"] == "project_refused" and "running in garden" in found["message"]
    assert git(garden, "rev-parse", "HEAD") == head and not (garden / "notes.csv").exists()
    with locks.held("project-plain", folder=run_dir()):
        code, out, err = world.run("project", "git", "plain", "--json")
    assert code == 2 and json.loads(err)["reason_code"] == "project_refused"
    assert not (tmp_path / "plain" / ".git").exists()
    assert world.run("project", "git", "plain", "--dry-run", "--json")[0] == 0  # a dry run writes nothing: no lock


def test_another_projects_lock_never_blocks(world, garden, waiting):
    with locks.held("project-plain", folder=run_dir()):
        assert world.run("land", str(waiting["n"]), "--json")[0] == 0
