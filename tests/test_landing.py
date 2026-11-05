"""Build brief 28 (decisions 10 to 13; Tests, "Land", "Undo", "Discard and the open-task rule"): Land puts a waiting change
into the project's folder as one commit holding exactly the change's paths and HANDOFF.md; the owner's other edits and
staged changes stay as they are; every refusal writes nothing (a tree listing with sizes and modification times, `git
log` and `git status` compared before and after); no hook runs; a fault after the objects leaves the folder as it was.
Undo is one more commit; Discard drops the copy. Real git in temp folders; the waiting tasks come from a real routed run
with fake agents (tests/test_filemode_flow.py); every value fake."""
import os
import subprocess
from pathlib import Path

import pytest

from router import __main__ as cli
from router import copies, gitops, landing, log, projects, testrun
from tests.test_copies import git
from tests.test_filemode_flow import BUILD, FIXED_CALC, CopyWorker, Runner, conn, project, route, runner  # noqa: F401
from tests.test_handoff_contract import HANDOFF


def head(folder):
    return git(folder, "rev-parse", "HEAD").decode().strip()


def state(folder):
    """What 'writes nothing' compares: every file's path, size and modification time (outside .git), the commits on every
    ref, and git status."""
    files = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            path = Path(dirpath) / name
            info = path.lstat()
            files.append((path.relative_to(folder).as_posix(), info.st_size, info.st_mtime_ns))
    commits = git(folder, "log", "--all", "--format=%H").decode()
    status = git(folder, "status", "--porcelain=v1", "--untracked-files=all").decode()
    return sorted(files), commits, status


def waiting(conn, worker=None, **kw):
    code, out, row = route(conn, worker=worker or CopyWorker(BUILD), **kw)
    row = log.get_task(conn, row["task_id"])
    assert log.project_files_of(row)["state"] == "waiting", out
    return row


def land(conn, row, verb="land"):
    lines = []
    code = cli.cmd_land([str(row["n"])], conn=conn, config={}, verb=verb, out=lines.append)
    return code, "\n".join(lines)


def show(folder, commit):
    return git(folder, "show", "--name-only", "--format=%s%n%an <%ae>", commit).decode().split("\n")


# ---------- Land ----------

def test_land_makes_one_commit_holding_exactly_the_change_and_handoff(project, conn, runner):
    row = waiting(conn)
    before = head(project)
    code, out = land(conn, row)
    assert code == 0, out
    after = head(project)
    assert git(project, "rev-parse", "HEAD~1").decode().strip() == before
    subject, author, _, *names = show(project, after)
    assert subject == f"sr: {row['task'].splitlines()[0][:60]} ({row['task_id']})"
    assert author == "Test Owner <owner@example.invalid>"
    assert sorted(n for n in names if n) == ["HANDOFF.md", "calc.py", "test_calc.py"]
    assert (project / "calc.py").read_text() == FIXED_CALC and (project / "test_calc.py").exists()
    found = log.project_files_of(log.get_task(conn, row["task_id"]))
    assert found["state"] == "landed" and found["commit"] == after and found["copy"] is False
    assert not copies.exists(row["task_id"])
    newest = projects.entries_of((project / "HANDOFF.md").read_text())[0]
    committed = git(project, "show", f"{after}:HANDOFF.md").decode()
    # brief 29.1 (decision 1, issue 5): nothing is written in the folder after the commit, so the entry ends `landed`
    # in both and the folder is clean; the card, sr show and the log carry the id
    assert newest == projects.entries_of(committed)[0] and newest.splitlines()[0].endswith("· landed")
    assert newest.splitlines()[-1] == "No tests ran: the project has no test command"  # issue 7: the router's line
    assert f"Landed #{row['n']} as {after[:7]} on main" in out
    assert git(project, "status", "--porcelain=v1").decode() == ""
    shown = []
    cli.cmd_show(conn=conn, words=[str(row["n"])], out=shown.append)
    assert f"Landed as {after[:7]} on main." in "\n".join(shown)


@pytest.mark.parametrize("outcome, line", [("passed", "Tests passed: `python3 -m unittest`"),
                                           ("failed", "Tests failed: `python3 -m unittest`")])
def test_a_landed_entry_ends_with_the_routers_tests_line(project, conn, runner, outcome, line):
    """Brief 29.1 (decision 5, issue 7): the entry keeps the doer's words from before the tests, then the router's line."""
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    runner.results.append(testrun.Result(0 if outcome == "passed" else 1, outcome, "x", "out"))
    row = waiting(conn)
    assert land(conn, row)[0] == 0
    assert projects.entries_of((project / "HANDOFF.md").read_text())[0].splitlines()[-1] == line


LONG = "Fix the bug in add so that it returns the sum of both of its numbers and add a test"


def test_land_and_undo_subjects_are_cut_at_a_word(project, conn, runner):
    """Brief 29.1 (decision 5, issue 6): a subject never ends mid-word; a cut one ends with an ellipsis."""
    row = waiting(conn, task=LONG)
    assert land(conn, row)[0] == 0
    subject = show(project, head(project))[0]
    assert subject == f"sr: Fix the bug in add so that it returns the sum of both of… ({row['task_id']})"
    assert land(conn, row, "undo")[0] == 0
    undo = show(project, head(project))[0]
    assert undo.startswith("sr: undo ") and undo.endswith(f"… ({row['task_id']})")
    words = undo.removeprefix("sr: undo ").split(", ", 1)[1].removesuffix(f"… ({row['task_id']})")
    assert LONG.startswith(words) and LONG[len(words)] == " "  # cut where a word ends


def test_the_reflog_carries_each_commits_subject(project, conn, runner):
    """Brief 29.1 (decision 5, issue 10): the router's reflog lines in a project read the commit's subject, not
    `super-router`."""
    row = waiting(conn)
    land(conn, row)
    land(conn, row, "undo")
    subjects = git(project, "log", "-2", "--format=%s").decode().splitlines()
    assert git(project, "reflog", "-2", "--format=%gs").decode().splitlines() == subjects


def test_the_owners_other_edits_and_staged_changes_stay_as_they_are(project, conn, runner):
    row = waiting(conn)
    (project / "README.md").write_text("# Garden, edited by the owner\n")
    (project / "notes.txt").write_text("staged by the owner\n")
    git(project, "add", "notes.txt")
    code, out = land(conn, row)
    assert code == 0, out
    status = git(project, "status", "--porcelain=v1").decode().splitlines()
    assert "A  notes.txt" in status and " M README.md" in status
    names = [n for n in show(project, head(project))[3:] if n]
    assert "README.md" not in names and "notes.txt" not in names


def test_a_moved_branch_that_didnt_touch_the_change_lands_on_the_new_head(project, conn, runner):
    row = waiting(conn)
    (project / "README.md").write_text("# Garden two\n")
    git(project, "commit", "-q", "-am", "the owner moved on")
    moved = head(project)
    code, out = land(conn, row)
    assert code == 0, out
    assert git(project, "rev-parse", "HEAD~1").decode().strip() == moved


@pytest.mark.parametrize("make,words", [
    (lambda folder: (folder / "calc.py").write_text("x = 'the owner edits'\n"), "uncommitted edits in the folder: calc.py"),
    (lambda folder: (folder / "test_calc.py").write_text("mine\n"), "already in the folder: test_calc.py"),
    (lambda folder: git(folder, "checkout", "-q", "-b", "other"), "the folder is on branch other"),
    (lambda folder: ((folder / "calc.py").write_text("# moved\n"), git(folder, "commit", "-q", "-am", "moved")),
     "changed these files since the task started: calc.py"),
])
def test_each_refusal_writes_nothing(project, conn, runner, make, words):
    row = waiting(conn)
    make(project)
    before = state(project)
    code, out = land(conn, row)
    assert code == 2 and words in out and "Nothing was changed." in out
    assert state(project) == before
    assert log.project_files_of(log.get_task(conn, row["task_id"]))["state"] == "waiting"


def test_a_key_scan_hit_names_file_and_line_never_the_value(project, conn, runner):
    value = "".join(("sk", "-", "abcdefghijklmnop", "qrstuv"))
    leaky = ("Done.\n\n" + HANDOFF, {"calc.py": FIXED_CALC + f"API = '{value}'\n"})
    row = waiting(conn, worker=CopyWorker(leaky))
    before = state(project)
    code, out = land(conn, row)
    assert code == 2 and "calc.py line 3 looks like it holds a key" in out and value not in out
    assert state(project) == before


def test_an_env_value_in_the_change_is_refused_by_line(project, conn, runner):
    secret = "envvalue" + "x" * 12
    row = waiting(conn, worker=CopyWorker(("Done.\n\n" + HANDOFF, {"calc.py": FIXED_CALC + f"# {secret}\n"})))
    before = state(project)
    lines = []
    code = cli.cmd_land([str(row["n"])], conn=conn, config={"SOME_TOKEN": secret}, verb="land", out=lines.append)
    assert code == 2 and "calc.py line 3 holds a value from .env" in "\n".join(lines) and secret not in "\n".join(lines)
    assert state(project) == before


def test_no_hook_runs(project, conn, runner):
    row = waiting(conn)
    hooks = project / ".git" / "hooks"
    planted = project.parent / "hook-ran.txt"
    for name in ("pre-commit", "post-commit", "commit-msg", "prepare-commit-msg", "reference-transaction",
                 "post-index-change", "post-checkout"):
        (hooks / name).write_text(f"#!/bin/sh\necho {name} >> '{planted}'\n")
        os.chmod(hooks / name, 0o755)
    code, out = land(conn, row)
    assert code == 0, out
    assert not planted.exists()
    code, out = land(conn, row, "undo")
    assert code == 0 and not planted.exists()


def test_the_author_falls_back_to_the_router(project, conn, runner, tmp_path, monkeypatch):
    row = waiting(conn)
    empty = tmp_path / "empty-gitconfig"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    code, out = land(conn, row)
    assert code == 0, out
    assert show(project, head(project))[1] == f"{gitops.ROUTER_NAME} <{gitops.ROUTER_EMAIL}>"


def test_a_fault_after_the_objects_leaves_the_folder_as_it_was(project, conn, runner, tmp_path):
    row = waiting(conn)
    before = state(project)
    with pytest.raises(RuntimeError, match="after the objects"):
        landing.land(conn, row["task_id"], cli._land_entry(conn, row), journal_dir=tmp_path / "lands", date="2026-10-27",
                     fault="after_objects")
    assert state(project) == before
    assert log.project_files_of(log.get_task(conn, row["task_id"]))["state"] == "waiting"
    assert not list((tmp_path / "lands").glob("*.json")) if (tmp_path / "lands").exists() else True


def test_a_land_interrupted_after_the_branch_moved_is_finished_next_time(project, conn, runner, tmp_path):
    row = waiting(conn)
    with pytest.raises(RuntimeError, match="after the branch"):
        landing.land(conn, row["task_id"], cli._land_entry(conn, row), journal_dir=tmp_path / "lands", date="2026-10-27",
                     fault="after_branch")
    new = head(project)
    assert (project / "calc.py").read_text() != FIXED_CALC  # the branch moved; the files not yet
    lines = []
    assert landing.recover(conn, project, tmp_path / "lands", out=lines.append) == "finished"
    assert (project / "calc.py").read_text() == FIXED_CALC and (project / "test_calc.py").exists()
    assert git(project, "status", "--porcelain=v1").decode() == ""
    found = log.project_files_of(log.get_task(conn, row["task_id"]))
    assert found["state"] == "landed" and found["commit"] == new and not copies.exists(row["task_id"])


def test_landing_twice_or_a_task_not_waiting_is_refused(project, conn, runner):
    row = waiting(conn)
    assert land(conn, row)[0] == 0
    code, out = land(conn, row)
    assert code == 2 and "no change waiting to land (it is landed)" in out


# ---------- Undo ----------

def test_undo_is_one_more_commit_putting_the_paths_back(project, conn, runner):
    row = waiting(conn)
    start = head(project)
    calc = (project / "calc.py").read_text()
    land(conn, row)
    landed = head(project)
    code, out = land(conn, row, "undo")
    assert code == 0, out
    undone = head(project)
    assert git(project, "rev-parse", "HEAD~1").decode().strip() == landed
    assert (project / "calc.py").read_text() == calc and not (project / "test_calc.py").exists()
    assert sorted(n for n in show(project, undone)[3:] if n) == ["HANDOFF.md", "calc.py", "test_calc.py"]
    assert projects.entries_of((project / "HANDOFF.md").read_text())[0].endswith(f"· undone ({landed[:7]})")
    assert git(project, "log", "--format=%H").decode().split() == [undone, landed, start] + \
        git(project, "log", "--format=%H", f"{start}~1").decode().split()
    reflog = git(project, "reflog", "--format=%H").decode().split()
    assert reflog[:3] == [undone, landed, start]  # only new commits: no history rewritten
    found = log.project_files_of(log.get_task(conn, row["task_id"]))
    assert found["state"] == "undone" and found["undo_commit"] == undone
    code, out = land(conn, row, "undo")
    assert code == 2 and "undone already" in out


def test_undo_is_refused_when_a_landed_path_changed_since(project, conn, runner):
    row = waiting(conn)
    land(conn, row)
    (project / "calc.py").write_text("# the owner's own edit\n")
    git(project, "commit", "-q", "-am", "owner edit")
    before = state(project)
    code, out = land(conn, row, "undo")
    assert code == 2 and "changed since the land" in out and "calc.py" in out
    assert state(project) == before


# ---------- Discard, cancel and the open-task rule ----------

def test_discard_drops_the_copy_writes_the_line_and_frees_the_project(project, conn, runner):
    row = waiting(conn)
    before_files = [x for x in state(project)[0] if x[0] != "HANDOFF.md"]
    code, out = land(conn, row, "discard")
    assert code == 0, out
    assert not copies.exists(row["task_id"])
    assert [x for x in state(project)[0] if x[0] != "HANDOFF.md"] == before_files
    assert projects.entries_of((project / "HANDOFF.md").read_text())[0].endswith("· discarded")
    assert log.project_files_of(log.get_task(conn, row["task_id"]))["state"] == "discarded"
    assert log.open_task_for(conn, "garden") is None
    assert land(conn, row)[0] == 2


def test_a_waiting_task_blocks_the_next_until_landed(project, conn, runner):
    row = waiting(conn)
    code, out, _ = route(conn, worker=CopyWorker(BUILD))
    assert code == 2 and f"has task {row['n']} open" in out
    land(conn, row)
    code, out, second = route(conn, worker=CopyWorker(("Again.\n\n" + HANDOFF, {"README.md": "# Garden again\n"})))
    assert code == 0, out


def test_cancel_on_a_waiting_task_discards_it(project, conn, runner):
    row = waiting(conn)
    lines = []
    assert cli.cmd_cancel(conn=conn, words=[str(row["n"])], out=lines.append) == 0
    assert "Cancelled" in "\n".join(lines) and not copies.exists(row["task_id"])
    assert log.project_files_of(log.get_task(conn, row["task_id"]))["state"] == "discarded"
    assert log.open_task_for(conn, "garden") is None


def test_cancel_on_an_open_file_mode_task_removes_its_copy(project, conn, runner):
    code, out, row = route(conn, worker=CopyWorker(BUILD), wait=False, jev={"status": "ok", "label": "web_research",
                                                                            "confidence": 0.95, "needs_split": 0.1,
                                                                            "tokens": 10})
    # a web_research task goes to Grok here: it stays open (sent), handoff only
    lines = []
    cli.cmd_cancel(conn=conn, words=[str(row["n"])], out=lines.append)
    assert not copies.exists(row["task_id"])
