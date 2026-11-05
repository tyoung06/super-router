"""Build brief 28 (decisions 1, 2, 4, 7 and 8; Tests, "The copy" and "The change"): the scratch copy and the router's own
history of it, on real git in temp folders (the `real_git` fixture: git only, under a global config of the test's own).
Every fake value is made here at run time."""
import os
import secrets
import subprocess
from pathlib import Path

import pytest

from router import copies, gitops, safety


def git(folder, *args, data=None):
    return subprocess.run(["git", "-C", str(folder), *args], check=True, capture_output=True, input=data).stdout


def make_repo(root, files, *, links=(), message="first"):
    """A repository at `root` with `files` ({path: bytes or str}) committed, and `links` ({path: target}) too."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    for path, body in files.items():
        full = root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(body if isinstance(body, bytes) else body.encode())
    for path, target in dict(links).items():
        os.symlink(target, root / path)
    git(root, "add", "-f", "--", *files, *dict(links))
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD").decode().strip()


def tree_of(folder):
    found = {}
    for dirpath, dirnames, filenames in os.walk(folder):
        for name in filenames:
            path = Path(dirpath) / name
            found[path.relative_to(folder).as_posix()] = (path.read_bytes(), path.stat().st_mode & 0o777)
    return found


# ---------- what a copy never carries ----------

@pytest.mark.parametrize("path,why", [
    (".env", ".env"), (".env.local", ".env"), (".ENV", ".env"), ("backend/.env", ".env"), ("a/.env.production", ".env"),
    (".git/config", ".git"), (".claude/settings.json", ".claude"), ("sub/.claude/x", ".claude"), (".mcp.json", ".mcp.json"),
    (".MCP.json", ".MCP.json"), (".cursor/rules", ".cursor"), (".codex/config.toml", ".codex"), ("HANDOFF.md", "HANDOFF.md"),
    ("handoff.md", "HANDOFF.md"),
    ("docs/HANDOFF.md", None), (".gitignore", None), (".github/workflows/ci.yml", None), ("app.py", None),
    ("environment.py", None), (".envrc", None), ("my.env", None),
])
def test_what_a_copy_never_carries(path, why):
    assert copies.excluded(path) == why


# ---------- the copy ----------

def test_the_copy_holds_the_tracked_files_at_the_base_and_nothing_else(real_git, tmp_path):
    nonce = "nonce-" + secrets.token_hex(8)
    folder = tmp_path / "project"
    head = make_repo(folder, {
        "app.py": "print('hi')\n", "tools/run.sh": "#!/bin/sh\necho hi\n", ".gitignore": ".env\n",
        ".env.local": f"TOKEN={nonce}\n", ".claude/settings.json": "{}\n", ".mcp.json": "{}\n", ".cursor/rules": "x\n",
        ".codex/config.toml": "x\n", "HANDOFF.md": "notes\n", "docs/HANDOFF.md": "a doc\n",
    }, links={"link-to-app": "app.py"})
    os.chmod(folder / "tools" / "run.sh", 0o755)
    git(folder, "add", "tools/run.sh")
    git(folder, "commit", "-q", "-m", "exec")
    head = git(folder, "rev-parse", "HEAD").decode().strip()
    (folder / ".env").write_text(f"SECRET={nonce}\n")      # ignored
    (folder / "untracked.txt").write_text("not tracked\n")
    made = copies.make("sr-t1", folder, head)
    copy = copies.folder_of("sr-t1")
    held = tree_of(copy)
    assert sorted(held) == [".gitignore", "app.py", "docs/HANDOFF.md", "tools/run.sh"]
    assert made.files == 4 and made.left_out == [{"path": "link-to-app", "why": "link"}]
    assert held["tools/run.sh"][1] == 0o755 and held["app.py"][1] == 0o644
    assert not any(nonce.encode() in body for body, _ in held.values())
    assert not list(copy.rglob(".git")) and not (copy / ".git").exists()
    history = copies.history_of("sr-t1")
    assert history.is_dir() and not history.resolve().is_relative_to(copy.resolve())
    assert (copy.stat().st_mode & 0o777) == 0o700 and (history.stat().st_mode & 0o777) == 0o700
    # a file changed in the folder after intake never reaches it
    (folder / "app.py").write_text("print('changed')\n")
    assert (copy / "app.py").read_text() == "print('hi')\n"


def test_a_submodule_entry_is_left_out_and_listed(real_git, tmp_path):
    folder = tmp_path / "project"
    make_repo(folder, {"a.txt": "a\n"})
    sha = git(folder, "rev-parse", "HEAD").decode().strip()
    git(folder, "update-index", "--add", "--cacheinfo", f"160000,{sha},vendor/lib")
    git(folder, "commit", "-q", "-m", "submodule")
    made = copies.make("sr-sub", folder, git(folder, "rev-parse", "HEAD").decode().strip())
    assert made.left_out == [{"path": "vendor/lib", "why": "submodule"}]
    assert sorted(tree_of(copies.folder_of("sr-sub"))) == ["a.txt"]


def test_over_the_file_limit_is_too_big_and_writes_nothing(real_git, tmp_path, monkeypatch):
    folder = tmp_path / "project"
    head = make_repo(folder, {f"f{i}.txt": "x\n" for i in range(4)})
    monkeypatch.setattr(copies, "MAX_FILES", 3)
    with pytest.raises(copies.TooBig, match=r"too big for a copy \(4 files\)"):
        copies.make("sr-big", folder, head)
    assert not copies.folder_of("sr-big").exists() and not copies.history_of("sr-big").exists()


def test_over_the_size_limit_is_too_big(real_git, tmp_path, monkeypatch):
    folder = tmp_path / "project"
    head = make_repo(folder, {"big.bin": b"x" * 5000})
    monkeypatch.setattr(copies, "MAX_BYTES", 4000)
    with pytest.raises(copies.TooBig, match="too big for a copy"):
        copies.make("sr-mb", folder, head)
    assert not copies.folder_of("sr-mb").exists()


def test_two_paths_that_differ_only_in_case_are_refused(real_git, tmp_path):
    folder = tmp_path / "project"
    make_repo(folder, {"a.txt": "a\n"})
    blob = git(folder, "hash-object", "-w", "--stdin", data=b"other\n").decode().strip()
    git(folder, "update-index", "--add", "--cacheinfo", f"100644,{blob},A.txt")
    git(folder, "commit", "-q", "-m", "case")
    with pytest.raises(copies.CopyError, match="differ only in case"):
        copies.make("sr-case", folder, git(folder, "rev-parse", "HEAD").decode().strip())
    assert not copies.folder_of("sr-case").exists()


# ---------- snapshots and restore ----------

def test_snapshot_and_restore_are_byte_exact(real_git, tmp_path):
    folder = tmp_path / "project"
    head = make_repo(folder, {"a.txt": "a\n", "deep/b.txt": "b\n", "crlf.txt": b"one\r\ntwo\r\n"})
    copies.make("sr-snap", folder, head)
    copy = copies.folder_of("sr-snap")
    (copy / ".gitattributes").write_text("* text=auto\n")
    (copy / ".gitignore").write_text("ignored.log\n")
    (copy / "ignored.log").write_text("kept anyway\n")
    os.chmod(copy / "a.txt", 0o755)
    before = tree_of(copy)
    copies.snapshot("sr-snap", "before-c1")
    (copy / "a.txt").write_text("edited\n")
    (copy / "crlf.txt").write_bytes(b"lf only\n")
    (copy / "deep" / "b.txt").unlink()
    (copy / "new" / "deeper").mkdir(parents=True)
    (copy / "new" / "deeper" / "c.txt").write_text("c\n")
    os.symlink("/", copy / "a-link")
    copies.restore("sr-snap", "before-c1")
    assert tree_of(copy) == before
    assert not (copy / "a-link").exists() and not (copy / "new").exists()


def test_restore_never_follows_a_link(real_git, tmp_path):
    folder = tmp_path / "project"
    head = make_repo(folder, {"a.txt": "a\n"})
    copies.make("sr-link", folder, head)
    copy = copies.folder_of("sr-link")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep\n")
    copies.snapshot("sr-link", "before-c1")
    (copy / "a.txt").unlink()
    os.symlink(outside / "keep.txt", copy / "a.txt")
    os.symlink(outside, copy / "dir-link")
    copies.restore("sr-link", "before-c1")
    assert (outside / "keep.txt").read_text() == "keep\n" and sorted(p.name for p in outside.iterdir()) == ["keep.txt"]
    assert not (copy / "a.txt").is_symlink() and (copy / "a.txt").read_text() == "a\n"
    assert not (copy / "dir-link").exists()


# ---------- the change ----------

def test_the_change_lists_added_changed_and_deleted_files_with_counts(real_git, tmp_path):
    folder = tmp_path / "project"
    head = make_repo(folder, {"calc.py": "def add(a, b):\n    return a - b\n", "old.txt": "gone\n", "img.bin": b"\x00\x01"})
    copies.make("sr-ch", folder, head)
    copy = copies.folder_of("sr-ch")
    (copy / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (copy / "old.txt").unlink()
    (copy / "test_calc.py").write_text("import unittest\n\nclass T(unittest.TestCase):\n    pass\n")
    (copy / "img.bin").write_bytes(b"\x00\x02\x03")
    found = copies.change("sr-ch", "after-c1")
    assert found.problem is None
    assert found.changed == [
        {"path": "calc.py", "status": "changed", "plus": 1, "minus": 1},
        {"path": "img.bin", "status": "changed", "plus": None, "minus": None},
        {"path": "old.txt", "status": "deleted", "plus": 0, "minus": 1},
        {"path": "test_calc.py", "status": "added", "plus": 4, "minus": 0},
    ]
    assert "diff --git a/calc.py b/calc.py" in found.diff and "+    return a + b" in found.diff
    assert "Binary files" in found.diff


def test_an_empty_change_is_empty(real_git, tmp_path):
    folder = tmp_path / "project"
    head = make_repo(folder, {"a.txt": "a\n"})
    copies.make("sr-empty", folder, head)
    found = copies.change("sr-empty", "after-c1")
    assert found.changed == [] and found.diff == "" and found.problem is None


@pytest.mark.parametrize("make,words", [
    (lambda copy: (copy / ".env").write_text("X=1\n"), "(.env): .env"),
    (lambda copy: (copy / "sub").mkdir() or (copy / "sub" / ".claude").mkdir() or (copy / "sub" / ".claude" / "s").write_text("x"),
     "(.claude): sub/.claude"),
    (lambda copy: os.symlink("/", copy / "root-link"), "a link: root-link"),
    (lambda copy: (copy / "HANDOFF.md").write_text("x\n"), "(HANDOFF.md): HANDOFF.md"),
])
def test_a_change_holding_what_a_copy_never_carries_fails(real_git, tmp_path, make, words):
    folder = tmp_path / "project"
    head = make_repo(folder, {"a.txt": "a\n"})
    copies.make("sr-bad", folder, head)
    make(copies.folder_of("sr-bad"))
    assert words in copies.problem_before_call("sr-bad")
    assert words in copies.change("sr-bad", "after-c1").problem


def test_a_changed_file_over_the_limit_and_too_many_files_fail(real_git, tmp_path, monkeypatch):
    folder = tmp_path / "project"
    head = make_repo(folder, {"a.txt": "a\n"})
    copies.make("sr-lim", folder, head)
    copy = copies.folder_of("sr-lim")
    monkeypatch.setattr(copies, "MAX_FILE_BYTES", 10)
    (copy / "a.txt").write_text("much more than ten bytes\n")
    assert "a.txt is" in copies.change("sr-lim", "after-c1").problem
    monkeypatch.setattr(copies, "MAX_FILE_BYTES", 10_000)
    monkeypatch.setattr(copies, "MAX_CHANGED", 2)
    for i in range(3):
        (copy / f"n{i}.txt").write_text("n\n")
    assert "at most 2" in copies.change("sr-lim", "after-c2").problem


def test_a_clean_copy_passes_the_before_call_check(real_git, tmp_path):
    folder = tmp_path / "project"
    copies.make("sr-ok", folder, make_repo(folder, {"a.txt": "a\n"}))
    assert copies.problem_before_call("sr-ok") is None


def test_remove_takes_the_copy_and_its_history(real_git, tmp_path):
    folder = tmp_path / "project"
    copies.make("sr-rm", folder, make_repo(folder, {"a.txt": "a\n"}))
    assert copies.exists("sr-rm")
    assert copies.remove("sr-rm") is True and not copies.exists("sr-rm")
    assert copies.remove("sr-rm") is True  # nothing left: still true


def test_file_bytes_refuses_a_link(real_git, tmp_path):
    folder = tmp_path / "project"
    copies.make("sr-fb", folder, make_repo(folder, {"a.txt": "a\n"}))
    os.symlink(tmp_path / "project" / "a.txt", copies.folder_of("sr-fb") / "l.txt")
    assert copies.file_bytes("sr-fb", "a.txt") == b"a\n"
    with pytest.raises(copies.CopyError, match="not a plain file"):
        copies.file_bytes("sr-fb", "l.txt")


# ---------- the project's git (decision 1) ----------

def test_inspect_a_repository_on_a_branch(real_git, tmp_path):
    folder = tmp_path / "project"
    head = make_repo(folder, {"a.txt": "a\n"})
    found = gitops.inspect(folder, router_root=tmp_path / "router")
    assert (found.git, found.branch, found.head, found.why) == (True, "main", head, None)


def test_inspect_says_why_each_folder_runs_handoff_only(real_git, tmp_path):
    router = tmp_path / "router"
    make_repo(router, {"r.txt": "r\n"})
    plain = tmp_path / "plain"
    plain.mkdir()
    assert gitops.inspect(plain, router_root=router).why == "no git yet: Turn on undo"
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "-q")
    assert gitops.inspect(empty, router_root=router).why == "no commit yet: Turn on undo"
    detached = tmp_path / "detached"
    head = make_repo(detached, {"a.txt": "a\n"})
    git(detached, "checkout", "-q", "--detach", head)
    assert gitops.inspect(detached, router_root=router).why == "it is on a detached head"
    sub = tmp_path / "detached" / "sub"
    sub.mkdir()
    assert gitops.inspect(sub, router_root=router).why == "it is inside another git repository, not at its top level"
    assert gitops.inspect(router, router_root=router).why == gitops.OWN_FOLDER
    inner = router / "inner"
    inner.mkdir()
    assert gitops.inspect(inner, router_root=router).why == gitops.OWN_FOLDER
    worktree = tmp_path / "elsewhere"
    git(router, "worktree", "add", "-q", "-b", "side", str(worktree))
    assert gitops.inspect(worktree, router_root=router).why == gitops.OWN_FOLDER


def test_the_routers_own_folder_is_refused_even_without_asking_git(tmp_path, monkeypatch):
    monkeypatch.setattr(gitops, "installed", lambda which=None: False)
    assert gitops.inspect(safety.REPO_ROOT).why == gitops.OWN_FOLDER
    assert gitops.inspect(safety.REPO_ROOT / "router").why == gitops.OWN_FOLDER


def test_no_git_installed_is_said(tmp_path, monkeypatch):
    monkeypatch.setattr(gitops, "installed", lambda which=None: False)
    assert gitops.inspect(tmp_path).why == "git isn't installed"


def test_identity_is_the_projects_or_the_routers(real_git, tmp_path, monkeypatch):
    folder = tmp_path / "project"
    make_repo(folder, {"a.txt": "a\n"})
    assert gitops.identity(folder) == ("Test Owner", "owner@example.invalid")
    empty_config = tmp_path / "empty-gitconfig"
    empty_config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_config))
    assert gitops.identity(folder) == (gitops.ROUTER_NAME, gitops.ROUTER_EMAIL)
    git(folder, "config", "user.name", "Local Name")
    git(folder, "config", "user.email", "local@example.invalid")
    assert gitops.identity(folder) == ("Local Name", "local@example.invalid")
