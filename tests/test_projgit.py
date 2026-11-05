"""Build brief 28 (decisions 14 to 16; Tests, "Files in, Turn on undo, New project"): each writes exactly its commit; each
refusal writes nothing; the dry run writes nothing (a tree listing with sizes and modification times compared); the
.gitignore is made, or its missing lines added at its end without touching the others; a key-scan hit names file and line
and never prints the value. Real git in temp folders; every value fake."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from router import __main__ as cli
from router import gitops, landing, log, projects, projgit
from tests.helpers import set_local
from tests.test_copies import git, make_repo
from tests.test_landing import head, show, state


@pytest.fixture
def registry(real_git, tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "config" / "projects.json")
    monkeypatch.setattr(projects, "TESTS_PATH", tmp_path / "config" / "project_tests.json")
    return tmp_path


def gitted(tmp_path, name="garden"):
    folder = tmp_path / name
    make_repo(folder, {"README.md": "# Garden\n"})
    projects.add(name, str(folder))
    git(folder, "add", "HANDOFF.md")
    git(folder, "commit", "-q", "-m", "handoff")
    return folder


def plain(tmp_path, name="plain-folder"):
    folder = tmp_path / name
    folder.mkdir()
    (folder / "notes.txt").write_text("plain notes\n")
    projects.add(name, str(folder))
    return folder


def run(argv, capsys):
    code = cli.main(argv, platform="darwin")
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def fake_file(folder, name, body):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(body)
    return str(folder / name)


# ---------- files in ----------

def test_files_in_is_one_commit_holding_them_and_handoff(registry, capsys):
    folder = gitted(registry)
    drop = registry / "drop"
    set_local(drop_folder=str(drop))
    a = fake_file(drop, "calc.py", "def add(a, b):\n    return a - b\n")
    b = fake_file(drop, "test_calc.py", "import unittest\n")
    before = head(folder)
    code, out = run(["project", "files", "garden", "--file", a, "--file", b], capsys)
    assert code == 0, out
    assert git(folder, "rev-parse", "HEAD~1").decode().strip() == before
    assert sorted(n for n in show(folder, head(folder))[3:] if n) == ["HANDOFF.md", "calc.py", "test_calc.py"]
    assert (folder / "calc.py").read_text() == "def add(a, b):\n    return a - b\n"
    assert projects.entries_of((folder / "HANDOFF.md").read_text())[0].endswith("files added: calc.py, test_calc.py")
    sent = list((drop / "sent").iterdir())
    assert len(sent) == 1 and sorted(p.name for p in sent[0].iterdir()) == ["calc.py", "test_calc.py"]
    assert not (drop / "calc.py").exists()
    assert git(folder, "status", "--porcelain=v1").decode() == ""
    # brief 29.1 (issue 10): the router's reflog line carries the commit's subject
    assert git(folder, "reflog", "-1", "--format=%gs").decode().strip() == "sr: files added: calc.py, test_calc.py"


def test_turn_on_undo_and_new_projects_first_commit_carry_their_subject_in_the_reflog(registry, capsys):
    """Brief 29.1 (issue 10): a first commit's reflog line is its subject too."""
    set_local(projects_root=str(registry / "root"))
    code, out = run(["project", "new", "patch"], capsys)
    assert code == 0, out
    folder = registry / "root" / "patch"
    assert git(folder, "reflog", "-1", "--format=%gs").decode().strip() == "sr: new project"


@pytest.mark.parametrize("make,words", [
    (lambda f, src: (f / "README.md").name, "README.md is already in the folder; a file is never overwritten"),
    (lambda f, src: fake_file(src, ".env", "X=1\n"), ".env is a name a project's files never take"),
    (lambda f, src: fake_file(src, ".mcp.json", "{}\n"), ".mcp.json is a name a project's files never take"),
    (lambda f, src: fake_file(src, "keys.txt", "token = " + "".join(("gh", "p_", "a" * 24)) + "\n"),
     "keys.txt line 1 looks like it holds a key"),
])
def test_each_files_refusal_writes_nothing(registry, capsys, make, words):
    folder = gitted(registry)
    src = registry / "src"
    path = make(folder, src)
    if not os.path.isabs(str(path)):
        path = fake_file(src, path, "my own readme\n")
    before = state(folder)
    code, out = run(["project", "files", "garden", "--file", path], capsys)
    assert code == 2 and words in out and "Nothing was changed." in out and "gh" + "p_" not in out
    assert state(folder) == before


def test_a_file_over_the_limit_and_a_project_without_git_are_refused(registry, capsys, monkeypatch):
    folder = gitted(registry)
    monkeypatch.setattr(projgit, "FILE_LIMIT", 10)
    big = fake_file(registry / "src", "big.csv", "x" * 20 + "\n")
    code, out = run(["project", "files", "garden", "--file", big], capsys)
    assert code == 2 and "at most 50 MB" in out
    nogit = plain(registry)
    before = state_plain = sorted(p.name for p in nogit.iterdir())
    code, out = run(["project", "files", "plain-folder", "--file", fake_file(registry / "src", "a.csv", "a\n")], capsys)
    assert code == 2 and "no git yet: Turn on undo" in out and sorted(p.name for p in nogit.iterdir()) == before


def test_files_in_while_a_task_waits_and_the_land_then_refuses_the_clash(registry, capsys, tmp_path, monkeypatch):
    from tests.test_filemode_flow import BUILD, CopyWorker, route
    from router import testrun
    monkeypatch.setattr(testrun, "available", lambda: False)
    folder = gitted(registry)
    (folder / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    git(folder, "add", "calc.py")
    git(folder, "commit", "-q", "-m", "calc")
    conn = log.init_db(tmp_path / "router.db")
    code, out, row = route(conn, worker=CopyWorker(BUILD))
    assert log.project_files_of(log.get_task(conn, row["task_id"]))["state"] == "waiting", out
    code, said = run(["project", "files", "garden", "--file", fake_file(registry / "src", "test_calc.py", "mine\n")], capsys)
    assert code == 0, said
    lines = []
    assert cli.cmd_land([str(row["n"])], conn=conn, config={}, verb="land", out=lines.append) == 2
    assert "test_calc.py" in "\n".join(lines)


# ---------- Turn on undo ----------

def test_the_dry_run_writes_nothing_and_counts_what_git_would_track(registry, capsys):
    folder = plain(registry)
    (folder / ".env").write_text("SECRET=" + "v" * 12 + "\n")
    (folder / "__pycache__").mkdir()
    (folder / "__pycache__" / "x.pyc").write_bytes(b"\0")
    before = sorted((p.name, p.stat().st_mtime_ns) for p in folder.rglob("*"))
    code, out = run(["project", "git", "plain-folder", "--dry-run", "--json"], capsys)
    found = json.loads(out.strip().splitlines()[-1])
    assert code == 0 and found["would"] == "turn_on"
    assert found["names"] == [".gitignore", "HANDOFF.md", "notes.txt"] and found["files"] == 3
    assert found["gitignore"] == {"exists": False, "adds": list(projgit.GITIGNORE_LINES)}
    assert sorted((p.name, p.stat().st_mtime_ns) for p in folder.rglob("*")) == before and not (folder / ".git").exists()


def test_turn_on_undo_makes_one_first_commit_and_leaves_env_ignored(registry, capsys):
    folder = plain(registry)
    env = folder / ".env"
    env.write_text("SECRET=" + "v" * 12 + "\n")
    env_before = (env.read_bytes(), env.stat().st_mtime_ns)
    code, out = run(["project", "git", "plain-folder"], capsys)
    assert code == 0, out
    names = git(folder, "ls-tree", "-r", "--name-only", "HEAD").decode().split()
    assert names == [".gitignore", "HANDOFF.md", "notes.txt"]
    assert git(folder, "log", "--format=%H").decode().split() == [head(folder)]
    assert (folder / ".gitignore").read_text() == "\n".join(projgit.GITIGNORE_LINES) + "\n"
    assert git(folder, "status", "--porcelain=v1", "--ignored").decode().splitlines() == ["!! .env"]
    assert (env.read_bytes(), env.stat().st_mtime_ns) == env_before
    assert gitops.inspect(folder).branch == "main"
    code, out = run(["project", "git", "plain-folder"], capsys)
    assert code == 2 and "already has git" in out


def test_an_existing_gitignore_gets_only_its_missing_lines_at_its_end(registry, capsys):
    folder = plain(registry)
    (folder / ".gitignore").write_text("# mine\n*.log\n.env")  # no newline at the end, one line already there
    code, out = run(["project", "git", "plain-folder"], capsys)
    assert code == 0, out
    assert (folder / ".gitignore").read_text() == "# mine\n*.log\n.env\n" + "\n".join(projgit.GITIGNORE_LINES[1:]) + "\n"


def test_a_key_in_a_file_refuses_turn_on_undo_by_file_and_line(registry, capsys):
    folder = plain(registry)
    value = "".join(("AK", "IA", "ABCDEFGHIJKLMNOP"))
    (folder / "config.txt").write_text(f"one\nkey: {value}\n")
    before = sorted((p.name, p.stat().st_mtime_ns) for p in folder.rglob("*"))
    code, out = run(["project", "git", "plain-folder"], capsys)
    assert code == 2 and "config.txt line 2 looks like it holds a key" in out and value not in out
    assert sorted((p.name, p.stat().st_mtime_ns) for p in folder.rglob("*")) == before and not (folder / ".git").exists()


def test_too_many_files_refuse_turn_on_undo(registry, capsys, monkeypatch):
    folder = plain(registry)
    from router import copies
    monkeypatch.setattr(copies, "MAX_FILES", 2)
    code, out = run(["project", "git", "plain-folder", "--dry-run"], capsys)
    assert code == 0 and "Would refuse: 3 files would be tracked; at most 2" in out


def test_an_interrupted_turn_on_is_finished_not_refused(registry, capsys):
    folder = plain(registry)
    git(folder, "init", "-q", "-b", "main")  # a .git with no commit and no index, as an interrupted run leaves it
    code, out = run(["project", "git", "plain-folder"], capsys)
    assert code == 0, out
    assert git(folder, "ls-tree", "-r", "--name-only", "HEAD").decode().split() == [".gitignore", "HANDOFF.md", "notes.txt"]


# ---------- New project ----------

def test_new_project_sets_up_git_with_gitignore_and_handoff(registry, capsys):
    set_local(projects_root=str(registry / "root"))
    code, out = run(["project", "new", "seeds", "--dry-run"], capsys)
    assert code == 0 and "git is set up" in out
    code, out = run(["project", "new", "seeds"], capsys)
    assert code == 0 and "git set up: one first commit" in out
    folder = registry / "root" / "seeds"
    assert git(folder, "ls-tree", "-r", "--name-only", "HEAD").decode().split() == [".gitignore", "HANDOFF.md"]
    assert len(git(folder, "log", "--format=%H").decode().split()) == 1
    assert (folder / ".gitignore").read_text() == "\n".join(projgit.GITIGNORE_LINES) + "\n"
    assert git(folder, "status", "--porcelain=v1").decode() == ""


def test_new_project_without_git_is_made_as_before(registry, capsys, monkeypatch):
    set_local(projects_root=str(registry / "root"))
    monkeypatch.setattr(gitops, "installed", lambda which=None: False)
    code, out = run(["project", "new", "seeds", "--dry-run", "--json"], capsys)
    assert json.loads(out.strip().splitlines()[-1])["git"] is False
    code, out = run(["project", "new", "seeds"], capsys)
    assert code == 0 and "file work needs git" in out
    folder = registry / "root" / "seeds"
    assert sorted(p.name for p in folder.iterdir()) == ["HANDOFF.md"]
