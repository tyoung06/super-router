"""Cleanup 1 (2.5, D3): an entry with nothing to land gets its own commit, so the folder stays clean: `sr: entry #<n>`,
`HANDOFF.md` alone, by land's journal and with no hooks. A hand edit is never swept in. A kept copy still lands after the
head moved, and nothing is committed mid-run. Fakes only, on throwaway git projects; no model call."""
import pytest

from router import __main__ as cli
from router import auto, claude_worker, copies, gitops, landing, log, projects
from tests.test_auto_run import STEP1, STEP2, _approved, _auto, _route_plan
from tests.test_copies import git
from tests.test_filemode_flow import BUILD, CODE, CopyWorker, conn, project, route, runner  # noqa: F401 (fixtures)
from tests.test_handoff_contract import HANDOFF
from tests.test_loop import Webhook
from tests.test_plan_approval import _land, _planned
from tests.test_relay import CONFIG, ROSTER, Chat

LOADED = cli._presets_or_none(ROSTER)
ANSWER = ("An answer in words.\n\n" + HANDOFF, {})
FAIL = "FIX\n1. [must] it is wrong"
BLOCKED = "BLOCKED\n1. [must] it was not given the seed list"


def _status(folder):
    return git(folder, "status", "--porcelain").decode().strip()


def _head(folder):
    return git(folder, "rev-parse", "HEAD").decode().strip()


def _paths(folder, rev="HEAD"):
    return git(folder, "show", "--name-only", "--format=", rev).decode().split()


def _subject(folder, rev="HEAD"):
    return git(folder, "log", "-1", "--format=%s", rev).decode().strip()


def _one_entry_commit(folder, before, row):
    assert _status(folder) == ""
    assert git(folder, "rev-parse", "HEAD~1").decode().strip() == before
    assert _subject(folder) == f"sr: entry #{row['n']}" and _paths(folder) == ["HANDOFF.md"]


# ---------- each ending that writes an entry with nothing to land ----------

def test_a_delivered_no_change_task(project, conn, runner):
    before = _head(project)
    code, out, row = route(conn, worker=CopyWorker(ANSWER), chatgpt=Chat("PASS"))
    assert row["status"] == "done" and f"entry for #{row['n']} written" in out, out
    _one_entry_commit(project, before, row)
    assert projects.entries_of((project / "HANDOFF.md").read_text())[0].startswith(f"### #{row['n']}")


def test_a_blocked_task(project, conn, runner):
    before = _head(project)
    code, out, row = route(conn, worker=CopyWorker(ANSWER), chatgpt=Chat(BLOCKED))
    assert row["check_state"] == log.BLOCKED, out
    _one_entry_commit(project, before, row)


def test_a_failed_task(project, conn, runner):
    before = _head(project)
    code, out, row = route(conn, worker=CopyWorker(claude_worker.WorkerError("claude exited 1: no")), chatgpt=None)
    assert row["status"] == "failed", out
    _one_entry_commit(project, before, row)


def test_a_discard(project, conn, runner):
    code, out, row = route(conn, worker=CopyWorker(BUILD), chatgpt=Chat("PASS"))
    before = _head(project)
    code, said = _land(conn, row, verb="discard")
    assert code == 0, said
    _one_entry_commit(project, before, row)
    assert "discarded" in projects.entries_of((project / "HANDOFF.md").read_text())[0]


def test_a_plan_reject(project, conn, runner):
    w, row = _planned(conn)
    before = _head(project)
    code, said = _land(conn, row, verb="discard")
    assert code == 0, said
    _one_entry_commit(project, before, row)


# ---------- the owner's edits, and where no commit can hold it ----------

def test_a_dirty_handoff_gets_no_commit_and_the_edit_stays(project, conn, runner):
    path = project / "HANDOFF.md"
    path.write_text("My own unsaved words.\n\n" + path.read_text())
    before = _head(project)
    code, out, row = route(conn, worker=CopyWorker(ANSWER), chatgpt=Chat("PASS"))
    assert _head(project) == before and "My own unsaved words." in path.read_text()
    assert projects.entries_of(path.read_text())[0].startswith(f"### #{row['n']}") and "HANDOFF.md" in _status(project)


def test_a_staged_file_is_never_swept_into_the_entry_commit(project, conn, runner):
    (project / "mine.txt").write_text("staged\n")
    git(project, "add", "mine.txt")
    code, out, row = route(conn, worker=CopyWorker(ANSWER), chatgpt=Chat("PASS"))
    assert _paths(project) == ["HANDOFF.md"] and _status(project) == "A  mine.txt"


def test_an_untracked_handoff_is_written_only(project, conn, runner):
    git(project, "rm", "-q", "--cached", "HANDOFF.md")
    git(project, "commit", "-q", "-m", "untrack it")
    before = _head(project)
    code, out, row = route(conn, worker=CopyWorker(ANSWER), chatgpt=Chat("PASS"))
    assert _head(project) == before
    assert projects.entries_of((project / "HANDOFF.md").read_text())[0].startswith(f"### #{row['n']}")


def test_no_git_is_written_only(real_git, tmp_path, monkeypatch, conn):
    monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "config" / "projects.json")
    monkeypatch.setattr(projects, "TESTS_PATH", tmp_path / "config" / "project_tests.json")
    folder = tmp_path / "plain"
    folder.mkdir()
    projects.add("garden", str(folder))
    code, out, row = route(conn, worker=CopyWorker(ANSWER), chatgpt=Chat("PASS"), files_ready=lambda: (True, None))
    assert projects.entries_of((folder / "HANDOFF.md").read_text())[0].startswith(f"### #{row['n']}")
    assert not (folder / ".git").exists()


@pytest.mark.parametrize("error", [gitops.GitError("git said no"), landing.Refused("the branch moved")])
def test_a_failed_commit_never_fails_the_task(project, conn, runner, monkeypatch, error):
    def fails(*a, **kw):
        raise error
    monkeypatch.setattr(landing, "_commit", fails)
    before = _head(project)
    code, out, row = route(conn, worker=CopyWorker(ANSWER), chatgpt=Chat("PASS"))
    assert row["status"] == "done" and _head(project) == before
    assert projects.entries_of((project / "HANDOFF.md").read_text())[0].startswith(f"### #{row['n']}")
    assert "not committed" in out and f"entry for #{row['n']} written" in out, out


def test_a_failed_commit_on_a_discard_still_writes_the_line_and_says_so(project, conn, runner, monkeypatch):
    code, out, row = route(conn, worker=CopyWorker(BUILD), chatgpt=Chat("PASS"))
    monkeypatch.setattr(landing, "_commit", lambda *a, **kw: (_ for _ in ()).throw(gitops.GitError("no")))
    code, said = _land(conn, row, verb="discard")
    assert code == 0 and "not committed" in said, said
    assert "discarded" in projects.entries_of((project / "HANDOFF.md").read_text())[0]


def test_commit_uses_no_hooks(project, conn, runner):
    hook = project / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text("#!/bin/sh\necho ran > hook-ran.txt\nexit 1\n")
    hook.chmod(0o755)
    code, out, row = route(conn, worker=CopyWorker(ANSWER), chatgpt=Chat("PASS"))
    assert _subject(project) == f"sr: entry #{row['n']}" and not (project / "hook-ran.txt").exists()


# ---------- check 1: a kept copy still lands after an entry commit moved the head ----------

def test_a_stopped_task_resumed_then_landed_after_its_entry_commit(project, conn, runner):
    limit = claude_worker.WorkerError("plan limit on claude: You've hit your limit", code="plan_limit")
    code, out, row = route(conn, worker=CopyWorker(limit), chatgpt=Chat())
    assert row["status"] == "failed" and _subject(project) == f"sr: entry #{row['n']}" and _status(project) == "", out
    assert copies.exists(row["task_id"])
    lines = []
    code = cli.cmd_resume([row["task_id"]], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[],
                          post=Webhook().post, worker=CopyWorker(BUILD), chatgpt=Chat("PASS"), codex_login=lambda: True,
                          out=lines.append)
    assert code in (0, 5), "\n".join(lines)
    code, said = _land(conn, row)
    assert code == 0, said
    assert _status(project) == "" and (project / "test_calc.py").exists()


def test_a_failed_check_landed_anyway_after_its_entry_commit(project, conn, runner):
    code, out, row = route(conn, worker=CopyWorker(BUILD, BUILD), chatgpt=Chat(FAIL, FAIL))
    assert row["check_state"] == "failed" and _subject(project) == f"sr: entry #{row['n']}", out
    code, said = _land(conn, row, anyway=True)
    assert code == 0, said
    assert _status(project) == "" and "landed" in projects.entries_of((project / "HANDOFF.md").read_text())[0]


def test_another_entry_commit_while_a_change_waits_doesnt_stop_its_land(project, conn, runner):
    code, out, row = route(conn, worker=CopyWorker(BUILD), chatgpt=Chat("PASS"))
    assert log.project_files_of(row)["state"] == "waiting"
    landing.write_entry(conn, project, 99, "### #99 · 2026-11-03 · a later line", journal_dir=cli._journal_dir())
    assert _subject(project) == "sr: entry #99"
    code, said = _land(conn, row)
    assert code == 0, said
    assert _status(project) == ""


# ---------- check 2: nothing is committed mid-run ----------

def test_a_stopped_run_commits_nothing_and_writes_no_entry_and_land_so_far_still_lands(project, conn, runner, monkeypatch):
    _route_plan(conn, _approved(conn))
    before, text = _head(project), (project / "HANDOFF.md").read_text()
    code, out, run = _auto(conn, environ={}, chatgpt=Chat("PASS", FAIL, FAIL, FAIL, FAIL),
                           worker=CopyWorker(STEP1, STEP2, STEP2, STEP2, STEP2))
    assert auto.run_state(run, log.auto_of(run)) == "stopped", out.message
    assert _head(project) == before and (project / "HANDOFF.md").read_text() == text and _status(project) == ""
    (project / "notes.txt").write_text("the owner's\n")
    git(project, "add", "notes.txt")
    git(project, "commit", "-q", "-m", "the head moves while the run is stopped")
    code, said = _land(conn, run)
    assert code == 0, said
    assert (project / "cli.py").exists() and not (project / "convert.py").exists()
    assert _status(project) == ""


def test_discard_run_commits_its_one_line(project, conn, runner):
    _route_plan(conn, _approved(conn))
    code, out, run = _auto(conn, chatgpt=Chat("PASS", FAIL, FAIL, FAIL, FAIL), worker=CopyWorker(STEP1, STEP2, STEP2, STEP2, STEP2))
    before = _head(project)
    code, said = _land(conn, run, verb="discard")
    assert code == 0, said
    _one_entry_commit(project, before, run)


def test_a_step_with_no_change_commits_its_entry_then_its_tick(project, conn, runner):
    """Build step k, delivered with no change: its entry's own commit, then docs/PLAN.md's, each one path, the folder clean."""
    plan_row = _approved(conn)
    before = _head(project)
    lines = []
    code = cli.cmd_route("Step one, already done.", conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=lambda *a, **kw: CODE, post=None, worker=CopyWorker(ANSWER), chatgpt=Chat("PASS"),
                         codex_login=lambda: True, fetch=None, close=None, sleep=lambda s: None, clock=lambda: 0.0, wait=True,
                         out=lines.append, project="garden", step_ref=f"{plan_row['task_id']}:1",
                         files_ready=lambda: (True, None))
    assert code in (0, 5), "\n".join(lines)
    assert _status(project) == "", "\n".join(lines)
    assert sorted({tuple(_paths(project)), tuple(_paths(project, "HEAD~1"))}) == [("HANDOFF.md",), ("docs/PLAN.md",)]
    assert git(project, "rev-parse", "HEAD~2").decode().strip() == before
