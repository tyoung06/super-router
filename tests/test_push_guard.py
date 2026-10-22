"""Build brief 25, C2 (decision 1): this repo's pre-push guard. After the rename the old URL is the public repo, so a clone
still pointing at it would push private history there. The guard refuses any push whose remote URL isn't the private
repo named in config/settings.local.json (`private_remote`, a name or owner/name; no tracked file names it), and every
push while that is unset. The owner installs it once (.git/hooks isn't tracked). Fake names only."""
import json
import os
import subprocess

import pytest

from scripts import push_guard
from tests.publish_fixtures import git, real_git


@pytest.mark.parametrize("url", [
    "https://github.com/someone/secret-dev.git", "https://github.com/someone/secret-dev", "https://github.com/someone/secret-dev/",
    "git@github.com:someone/secret-dev.git", "ssh://git@github.com/someone/secret-dev.git", "https://github.com/Someone/Secret-Dev.git"])
def test_the_private_repo_passes_in_every_url_form(url):
    assert push_guard.allowed(url, "secret-dev") and push_guard.allowed(url, "someone/secret-dev")


@pytest.mark.parametrize("url", [
    "https://github.com/someone/secret.git", "https://github.com/someone/secret-dev-public.git",
    "git@github.com:someone/secret.git", "/tmp/backup.git", "https://example.invalid/secret-dev-copy"])
def test_any_other_repo_is_refused(url):
    assert not push_guard.allowed(url, "secret-dev")


def test_the_owner_counts_when_the_setting_names_one():
    assert not push_guard.allowed("https://github.com/other/secret-dev.git", "someone/secret-dev")
    assert push_guard.allowed("https://github.com/other/secret-dev.git", "secret-dev")


def test_unset_refuses_everything():
    assert not push_guard.allowed("https://github.com/someone/secret-dev.git", "")


def _root(tmp_path, value):
    (tmp_path / "config").mkdir(exist_ok=True)
    doc = {} if value is None else {"private_remote": value}
    (tmp_path / "config" / "settings.local.json").write_text(json.dumps(doc))
    return tmp_path


def test_check_lets_the_private_repo_through_quietly(tmp_path):
    out = []
    assert push_guard.check(_root(tmp_path, "secret-dev"), "origin", "https://github.com/someone/secret-dev.git", out.append) == 0
    assert out == []


def test_check_refuses_another_repo_and_says_why(tmp_path):
    out = []
    code = push_guard.check(_root(tmp_path, "secret-dev"), "origin", "https://github.com/someone/secret.git", out.append)
    assert code == 1 and "Push refused" in out[0] and "https://github.com/someone/secret.git" in out[0]
    assert "secret-dev" not in " ".join(out)


def test_check_refuses_every_push_while_the_setting_is_missing(tmp_path):
    out = []
    code = push_guard.check(_root(tmp_path, None), "origin", "https://github.com/someone/secret-dev.git", out.append)
    assert code == 1 and "private_remote" in out[0]


@pytest.fixture
def repo(tmp_path, monkeypatch):
    real_git(monkeypatch)
    root = tmp_path / "private"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "remote", "add", "origin", "https://github.com/someone/secret-dev.git")
    _root(root, "secret-dev")
    return root


def test_install_writes_the_hook_and_says_whether_origin_passes(repo):
    out = []
    assert push_guard.install(repo, out=out.append, python="/usr/bin/python3") == 0
    hook = repo / ".git" / "hooks" / "pre-push"
    text = hook.read_text()
    assert text.startswith("#!/bin/sh\n") and push_guard.HOOK_MARK in text and os.access(hook, os.X_OK)
    assert f'"{push_guard.SCRIPT}" check "$1" "$2"' in text
    assert any("origin passes" in line for line in out)
    assert push_guard.install(repo, out=out.append) == 0  # its own hook is replaced, not refused


def test_install_warns_when_origin_would_be_refused(repo):
    git(repo, "remote", "set-url", "origin", "https://github.com/someone/secret.git")
    out = []
    assert push_guard.install(repo, out=out.append) == 0
    assert any("origin would be refused" in line for line in out)


def test_install_refuses_a_hook_that_isnt_the_guards(repo):
    (repo / ".git" / "hooks").mkdir(exist_ok=True)
    (repo / ".git" / "hooks" / "pre-push").write_text("#!/bin/sh\nexit 0\n")
    out = []
    assert push_guard.install(repo, out=out.append) == 1 and "isn't the guard's" in out[0]


def test_install_from_a_worktree_writes_the_shared_hook(repo):
    git(repo, "commit", "-q", "--allow-empty", "-m", "first")
    git(repo, "worktree", "add", "-q", "-b", "side", str(repo / ".worktrees" / "side"))
    assert push_guard.install(repo / ".worktrees" / "side", out=lambda line: None) == 0
    assert push_guard.HOOK_MARK in (repo / ".git" / "hooks" / "pre-push").read_text()


def test_the_installed_hook_refuses_a_wrong_push_end_to_end(repo, tmp_path):
    """The real hook, run as git runs it, from this repo's own script: here the worktree has no private_remote, so the
    guard refuses whatever the URL (fail closed)."""
    push_guard.install(repo, out=lambda line: None)
    hook = repo / ".git" / "hooks" / "pre-push"
    done = subprocess.run([str(hook), "origin", "https://github.com/someone/secret.git"], cwd=str(repo), input="",
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 1 and "Push refused" in (done.stdout + done.stderr)


def test_usage(capsys):
    assert push_guard.main([]) == 2 and push_guard.main(["check", "origin"]) == 2
