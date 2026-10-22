"""Build brief 25, C1 (decisions 2 and 9; the owner's binaries rule of 21 Oct): what goes public. An allowlist of folders and
files; a never-public list (decision 2's, the label-test files that go with labeltest/, and publish/, whose workflow is
placed, not copied); anything else stops the publish. A file that isn't text goes public only when named, with its
SHA-256, in the list of known synthetic binaries."""
import hashlib
import re
import subprocess
from pathlib import Path

import pytest

from scripts import publish
from tests.publish_fixtures import real_git

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("path", [
    "router/x.py", "static/app.js", "scripts/publish.py", "docs/SETUP.md", "demo/log.json", "tests/test_x.py",
    "config/agents.json", "config/presets.json", "config/settings.json", "config/skill_table.json", "requirements.txt",
    "pytest.ini", ".env.example", ".gitignore", ".gitleaksignore", "README.md", "LICENSE"])
def test_the_allowlist(path):
    assert publish.classify(path) == "allow"


@pytest.mark.parametrize("path", [
    "NOTES.md", "SUPER-ROUTER-HANDOFF.md", "SUPER-ROUTER.md", "CLAUDE.md", "AGENTS.md", "labeltest/run.py",
    ".claude/launch.json", "publish/ci.yml", "tests/test_labeltest_claude.py", "tests/test_labeltest_jev.py",
    "tests/test_labeltest_report.py", "tests/test_labeltest_round3.py", "tests/test_labeltest_round4.py",
    "tests/test_labeltest_score.py"])
def test_never_public(path):
    assert publish.classify(path) == "never"


@pytest.mark.parametrize("path", [
    "config/projects.json", "config/settings.local.json", "notes.txt", ".github/workflows/ci.yml", "routerx/a.py",
    "Tests/x.py", "HANDOFF.md", "router.db", ".env"])
def test_anything_else_is_in_neither_list(path):
    assert publish.classify(path) == "neither"


def test_the_files_made_at_publish_are_allowed_in_the_copy_only():
    assert set(publish.MADE) == {"docs/RULES.md", ".github/workflows/ci.yml"}
    assert publish.classify("docs/RULES.md", copy=True) == "allow"
    assert publish.classify(".github/workflows/ci.yml", copy=True) == "allow"
    assert publish.classify(".github/workflows/other.yml", copy=True) == "neither"


@pytest.mark.skipif(not (ROOT / "labeltest").exists(), reason="labeltest/ is not in this copy")
def test_the_never_public_tests_are_exactly_the_ones_that_need_labeltest():
    needs = sorted(f"tests/{p.name}" for p in (ROOT / "tests").glob("test_*.py")
                   if re.search(r"^(from|import) labeltest", p.read_text(), re.M))
    assert sorted(publish.LABEL_TESTS) == needs


def test_is_binary():
    assert publish.is_binary(b"\x89PNG\r\n\x1a\n\x00\x00")
    assert publish.is_binary(b"\xff\xfe not utf-8")
    assert not publish.is_binary("text with é and – in it\n".encode())
    assert not publish.is_binary(b"")


def test_every_known_binary_is_allowlisted_synthetic_and_its_bytes_match():
    assert publish.KNOWN_BINARIES
    for path, digest in publish.KNOWN_BINARIES.items():
        data = (ROOT / path).read_bytes()
        assert publish.classify(path) == "allow" and publish.is_binary(data)
        assert hashlib.sha256(data).hexdigest() == digest, path


@pytest.mark.skipif(not (ROOT / ".git").exists(), reason="not a git checkout")
def test_every_binary_in_the_public_tree_is_a_known_one(monkeypatch):
    real_git(monkeypatch)
    names = subprocess.run(["git", "ls-files", "-z"], cwd=str(ROOT), capture_output=True, check=True).stdout
    found = {}
    for name in names.decode().split("\0"):
        if name and publish.classify(name, copy=True) == "allow" and (ROOT / name).is_file():
            data = (ROOT / name).read_bytes()
            if publish.is_binary(data):
                found[name] = hashlib.sha256(data).hexdigest()
    assert found == publish.KNOWN_BINARIES
