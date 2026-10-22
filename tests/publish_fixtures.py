"""Build brief 25, C1: temp repos and fake words for the publish script's tests. Every word here is invented; real git runs
only inside temp folders (conftest blocks real subprocesses, so each test hands `real_git` back first)."""
import subprocess
from pathlib import Path

from scripts import publish

REAL_POPEN = subprocess.Popen  # taken at import, before conftest's per-test guard replaces it

WORDS = publish.Words(
    env=("FAKE-SECRET-VALUE-123",),
    home="/Users/zorblax",
    account="zorblax",
    full_name="Quinn Zorblax",
    email="quinn@zorblax.invalid",
    handle="zorblax06",
    inbox="zorblax06/zorblax-inbox-repo",
    private_remote="zorblax-private-dev",
    forbidden=("secretproj", "examplebroker"),
    author="zorblax06 <1+zorblax06@users.noreply.github.com>",
)

RULES = ("# SUPER-ROUTER.md — Quinn's demands\n\n"
         "Version 2.34 · 2026-10-21 · Only Quinn changes this file. Claude Code may propose edits, never make them.\n\n"
         "## What this project is\n\nQuinn types a task.\n\n"
         "## Money\n\n- No Examplebroker access of any kind. This project never touches real money.\n\n"
         "## Secretproj\n\n- `~/Projects/secretproj` is off limits.\n\n"
         "## Media\n\n- A file lands in `~/Desktop/Router Drop` on Quinn's Mac.\n- Never attach secretproj's files.\n\n"
         "## Project context\n\n- `~/Projects/secretproj` is never registered.\n\n"
         "## Kill criteria\n\n- Any charge: stop.\n\n"
         "## Changes from 2.33\n\n- Quinn's edits.\n")

TREE = {
    "router/__init__.py": "",
    "router/core.py": "def hello():\n    return 'hi'\n",
    "static/app.js": "export const x = 1;\n",
    "scripts/tool.py": "print('tool')\n",
    "docs/SETUP.md": "# Setting up\n",
    "demo/log.json": "[]\n",
    "tests/test_core.py": "def test_core():\n    assert True\n",
    "config/agents.json": "{}\n",
    "config/presets.json": "{}\n",
    "config/settings.json": "{}\n",
    "config/skill_table.json": "{}\n",
    "requirements.txt": "requests==2.34.2\n",
    "pytest.ini": "[pytest]\n",
    ".env.example": "JEV_API_KEY=\n",
    ".gitignore": ".env\nmedia/\n",
    "README.md": "# Example\n",
    "LICENSE": "MIT License\n\nCopyright (c) 2026 zorblax06\n",
    "SUPER-ROUTER.md": RULES,
    "publish/ci.yml": "name: CI\n",
    "NOTES.md": "secretproj notes, Quinn Zorblax, FAKE-SECRET-VALUE-123\n",
    "CLAUDE.md": "# instructions\n",
    "labeltest/run.py": "print('secretproj')\n",
    "tests/test_labeltest_jev.py": "import labeltest\n",
}


def real_git(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", REAL_POPEN)


def git(root, *args, check=True):
    proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=60)
    if check:
        assert proc.returncode == 0, (args, proc.stderr)
    return proc.stdout.strip()


def make_private(tmp_path, tree=None, name="private"):
    """A private repo on `main` with `tree` committed (TREE by default): the publish script's own kind of repo."""
    root = tmp_path / name
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "quinn@zorblax.invalid")
    git(root, "config", "user.name", "zorblax06")
    write_tree(root, TREE if tree is None else tree)
    commit(root, "First commit")
    return root


def write_tree(root, tree):
    for rel, text in tree.items():
        path = Path(root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            path.write_bytes(text)
        else:
            path.write_text(text)


def commit(root, message):
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "--short", "HEAD")


def make_clone(tmp_path):
    """An empty bare repo standing in for the public one on GitHub, and a fresh clone of it: the folder to publish into."""
    bare = tmp_path / "public.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    clone = tmp_path / "public"
    git(tmp_path, "clone", "-q", str(bare), str(clone))
    git(clone, "config", "user.email", "t@example.invalid")
    git(clone, "config", "user.name", "t")
    return clone


def files_of(root):
    """Every file under `root` but .git, as relative paths."""
    root = Path(root)
    return sorted(str(p.relative_to(root)) for p in root.rglob("*")
                  if (p.is_file() or p.is_symlink()) and ".git" not in p.relative_to(root).parts[:1])
