"""Build brief 28 (decision 1; Tests, "The copy"): when a task with --project runs in file mode, and the card's one line
when it doesn't: no git, no commit, a detached head, a subfolder of a repository, the router's own folder and a worktree
of it, too big for a copy, Claude's file check not passed. The cheap checks run first; the file check (which may cost a
call) only when everything else holds. Real git in temp folders; no model call."""
import os
import subprocess

import pytest

from router import copies, filemode, gitops, probes, safety
from tests.test_copies import git, make_repo


class Ready:
    def __init__(self, answer=(True, None)):
        self.answer, self.asked = answer, 0

    def __call__(self):
        self.asked += 1
        return self.answer


def test_a_repository_on_a_branch_runs_in_file_mode(real_git, tmp_path):
    folder = tmp_path / "project"
    head = make_repo(folder, {"a.py": "x = 1\n"})
    ready = Ready()
    found = filemode.decide(folder, files_ready=ready)
    assert found.on is True and found.why is None and ready.asked == 1
    assert (found.repo.branch, found.repo.head) == ("main", head)
    assert found.as_dict() == {"files_mode": "on", "why": None}


@pytest.mark.parametrize("setup,why", [
    ("plain", "no git yet: Turn on undo"),
    ("empty", "no commit yet: Turn on undo"),
    ("detached", "it is on a detached head"),
    ("subfolder", "it is inside another git repository, not at its top level"),
])
def test_each_folder_that_runs_handoff_only_says_why_and_never_asks_the_file_check(real_git, tmp_path, setup, why):
    folder = tmp_path / "project"
    if setup == "plain":
        folder.mkdir()
    elif setup == "empty":
        folder.mkdir()
        git(folder, "init", "-q")
    elif setup == "detached":
        head = make_repo(folder, {"a.txt": "a\n"})
        git(folder, "checkout", "-q", "--detach", head)
    else:
        make_repo(tmp_path / "outer", {"a.txt": "a\n"})
        folder = tmp_path / "outer" / "inner"
        folder.mkdir()
    ready = Ready()
    found = filemode.decide(folder, files_ready=ready)
    assert (found.on, found.why, ready.asked) == (False, why, 0)


def test_the_routers_own_folder_and_its_worktrees_run_handoff_only(real_git, tmp_path, monkeypatch):
    router = tmp_path / "router"
    make_repo(router, {"r.txt": "r\n"})
    monkeypatch.setattr(safety, "REPO_ROOT", router)
    worktree = tmp_path / "wt"
    git(router, "worktree", "add", "-q", "-b", "side", str(worktree))
    for folder in (router, router / "sub", worktree):
        folder.mkdir(exist_ok=True)
        found = gitops.inspect(folder, router_root=router)
        assert found.why == "this is the router's own folder"
    assert filemode.decide(safety.REPO_ROOT, files_ready=Ready()).why == "this is the router's own folder"


def test_too_big_for_a_copy_runs_handoff_only(real_git, tmp_path, monkeypatch):
    folder = tmp_path / "project"
    make_repo(folder, {f"f{i}.txt": "x\n" for i in range(5)})
    monkeypatch.setattr(copies, "MAX_FILES", 4)
    ready = Ready()
    found = filemode.decide(folder, files_ready=ready)
    assert (found.on, found.why, ready.asked) == (False, "too big for a copy (5 files)", 0)


def test_the_file_check_not_passed_runs_handoff_only_with_its_words(real_git, tmp_path):
    folder = tmp_path / "project"
    make_repo(folder, {"a.txt": "a\n"})
    why = "Claude's file check hasn't passed on Claude Code 2.1.311"
    found = filemode.decide(folder, files_ready=Ready((False, why)))
    assert (found.on, found.why) == (False, why)


def test_the_view_reads_the_check_from_the_state_file_and_never_runs_it(real_git, tmp_path):
    folder = tmp_path / "project"
    make_repo(folder, {"a.txt": "a\n"})
    state = tmp_path / "probe_state.json"
    found = filemode.view(folder, state_path=state, version="2.1.311")  # not run yet: intake runs it first (D, 27 Oct)
    assert found.as_dict() == {"files_mode": "on", "why": None}
    probes.record_failure(state, "claude_files", "2.1.311", probes.RAN_FAILED, "no command ran: Bash ran")
    assert filemode.view(folder, state_path=state, version="2.1.311").as_dict() == {"files_mode": "off", "why": (
        "Claude's file check failed on Claude Code 2.1.311 (no command ran: Bash ran); file mode is off on this version")}
    probes.clear_failure(state, "claude_files")
    probes.search.record_pass(state, "2.1.311", key="claude_files")
    assert filemode.view(folder, state_path=state, version="2.1.311").as_dict() == {"files_mode": "on", "why": None}
    assert filemode.view(tmp_path, state_path=state, version="2.1.311").why == "no git yet: Turn on undo"
