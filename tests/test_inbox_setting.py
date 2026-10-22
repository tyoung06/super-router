"""Build brief 24, A2 (decision 11): the inbox repo is a setting, `grok_inbox_repo`, read from config/settings.local.json
(gitignored) over the tracked file. No tracked code, test, config, doc or demo file spells the real repo or its owner;
these tests read this Mac's own value at run time and skip when there is none, so this file spells neither. NOTES and
the handoff are history and left out (the public copy's privacy pass handles them). With this Mac's value, Grok's image
instruction reads byte for byte as it did when the code spelled the repo."""
import json
import subprocess
from pathlib import Path

import pytest

from router import grok
from tests.test_make_media import INSTRUCTION

ROOT = Path(__file__).resolve().parent.parent
REAL_POPEN = subprocess.Popen  # taken at import: conftest blocks real subprocesses, and git is this file's one
HISTORY = ("NOTES.md", "SUPER-ROUTER-HANDOFF.md")
# Brief 25 (decision 4): LICENSE's copyright line holds the GitHub handle, which is the inbox's owner: the one file
# allowed to hold that word. Never the inbox repo itself, and no other file.
HANDLE_ALLOWED = ("LICENSE",)
BEFORE = "0cb475f"  # main before brief 24: the last commit whose router/grok.py spelled the repo's name


def real_inbox(root=ROOT):
    """This Mac's `grok_inbox_repo` from its own config/settings.local.json, read directly (conftest points the router's
    settings at a temp file), or None."""
    try:
        doc = json.loads((Path(root) / "config" / "settings.local.json").read_text())
    except (OSError, ValueError):
        return None
    value = doc.get("grok_inbox_repo") if isinstance(doc, dict) else None
    return value.strip() if isinstance(value, str) and "/" in value else None


def real_inbox_words(root=ROOT):
    """What no tracked file may hold: the repo and its owner, and the repo's name when it is distinctive (12 characters
    or more, so a plain `inbox` is never banned). Lower case: GitHub's names ignore case. [] without a local value."""
    repo = real_inbox(root)
    if repo is None:
        return []
    owner, name = repo.split("/", 1)
    return [repo.lower(), owner.lower()] + ([name.lower()] if len(name) >= 12 else [])


def _git(args, root, monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", REAL_POPEN)
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=60)


def tracked_files_holding(words, root, monkeypatch, handle=None):
    """The tracked files (outside NOTES and the handoff) whose text holds any of `words`, by name only. `handle`, one of
    the words, is allowed in HANDLE_ALLOWED and nowhere else (brief 25, decision 4)."""
    proc = _git(["ls-files"], root, monkeypatch)
    assert proc.returncode == 0, proc.stderr
    found = []
    for name in proc.stdout.splitlines():
        if name in HISTORY:
            continue
        try:
            data = (Path(root) / name).read_bytes().lower()
        except OSError:
            continue
        held = [w for w in words if not (name in HANDLE_ALLOWED and w == handle)]
        if any(word.encode() in data for word in held):
            found.append(name)
    return found


needs_value = pytest.mark.skipif(real_inbox() is None, reason="no grok_inbox_repo in this Mac's config/settings.local.json")
needs_git = pytest.mark.skipif(not (ROOT / ".git").exists(), reason="not a git checkout")


@needs_value
@needs_git
def test_no_tracked_file_spells_the_inbox_repo_or_its_owner(monkeypatch):
    owner = real_inbox().split("/", 1)[0].lower()
    assert tracked_files_holding(real_inbox_words(), ROOT, monkeypatch, handle=owner) == []


@needs_value
def test_with_this_macs_value_the_image_instruction_reads_as_it_did(monkeypatch):
    repo = real_inbox()
    now = grok.imagine_instructions("sr-20261021-120000-ab12", repo=repo)
    assert now == INSTRUCTION.format(name=repo.split("/", 1)[1], task_id="sr-20261021-120000-ab12")
    if (ROOT / ".git").exists():  # the code as it was before this brief, read from git: the same sentence, byte for byte
        old = _git(["show", f"{BEFORE}:router/grok.py"], ROOT, monkeypatch)
        if old.returncode == 0:
            space = {}
            source = old.stdout.replace("from router import safety", "class safety:\n    SafeError = Exception")
            exec(compile(source, "grok_before.py", "exec"), space)
            assert now == space["imagine_instructions"]("sr-20261021-120000-ab12")


def test_the_words_come_from_the_local_file_and_a_plain_name_is_never_banned(tmp_path):
    assert real_inbox_words(tmp_path) == []
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.local.json").write_text(json.dumps({"grok_inbox_repo": "Someone/inbox"}))
    assert real_inbox_words(tmp_path) == ["someone/inbox", "someone"]
    (tmp_path / "config" / "settings.local.json").write_text(json.dumps({"grok_inbox_repo": "someone/a-long-inbox-name"}))
    assert real_inbox_words(tmp_path) == ["someone/a-long-inbox-name", "someone", "a-long-inbox-name"]


@needs_git
def test_the_scan_finds_a_tracked_file_holding_a_word(tmp_path, monkeypatch):
    for args in (["init", "-q"], ["config", "user.email", "t@example.invalid"], ["config", "user.name", "t"]):
        _git(args, tmp_path, monkeypatch)
    (tmp_path / "code.py").write_text('REPO = "someone/a-long-inbox-name"\n')
    (tmp_path / "NOTES.md").write_text("someone/a-long-inbox-name\n")  # history: left out
    (tmp_path / "clean.py").write_text("nothing here\n")
    _git(["add", "-A"], tmp_path, monkeypatch)
    assert tracked_files_holding(["someone/a-long-inbox-name", "someone"], tmp_path, monkeypatch) == ["code.py"]


def test_the_handle_is_allowed_in_license_alone():
    assert HANDLE_ALLOWED == ("LICENSE",)


@needs_git
def test_only_license_may_hold_the_handle_and_never_the_repo(tmp_path, monkeypatch):
    for args in (["init", "-q"], ["config", "user.email", "t@example.invalid"], ["config", "user.name", "t"]):
        _git(args, tmp_path, monkeypatch)
    (tmp_path / "LICENSE").write_text("Copyright (c) 2026 someone\n")
    (tmp_path / "README.md").write_text("by someone\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "LICENSE").write_text("Copyright (c) 2026 someone\n")  # only the top-level LICENSE is allowed
    _git(["add", "-A"], tmp_path, monkeypatch)
    words = ["someone/a-long-inbox-name", "someone"]
    assert tracked_files_holding(words, tmp_path, monkeypatch, handle="someone") == ["README.md", "docs/LICENSE"]
    (tmp_path / "LICENSE").write_text("Copyright (c) 2026 someone/a-long-inbox-name\n")
    assert "LICENSE" in tracked_files_holding(words, tmp_path, monkeypatch, handle="someone")
