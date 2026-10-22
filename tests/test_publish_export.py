"""Build brief 25, C1 (decision 9): the export reads HEAD, never the working tree, and copies the allowlist only. A file
in neither list, a binary that isn't a known synthetic one (or whose bytes changed), and a tracked copy of a file the
publish makes each stop it; a symlink, a submodule and a tracked file .gitignore ignores are never copied. Temp repos and
invented words only."""
import hashlib

import pytest

from scripts import publish
from tests.publish_fixtures import TREE, commit, git, make_private, real_git, write_tree


@pytest.fixture
def private(tmp_path, monkeypatch):
    real_git(monkeypatch)
    return make_private(tmp_path)


def _why(entries, path):
    return [why for p, why in entries if p == path]


def test_the_export_reads_head_not_the_working_tree(private):
    (private / "router" / "core.py").write_text("changed, not committed\n")
    (private / "router" / "new.py").write_text("untracked\n")
    found = publish.export(private)
    assert found.files["router/core.py"] == (b"def hello():\n    return 'hi'\n", False)
    assert "router/new.py" not in found.files and found.stops == []


def test_the_allowlist_is_copied_and_nothing_else(private):
    found = publish.export(private)
    assert sorted(found.files) == sorted(p for p in TREE if publish.classify(p) == "allow")
    for name in ("NOTES.md", "CLAUDE.md", "SUPER-ROUTER.md", "labeltest/run.py", "tests/test_labeltest_jev.py",
                 "publish/ci.yml"):
        assert name not in found.files
    assert found.skipped == [] and found.stops == []


def test_a_file_in_neither_list_stops(private):
    write_tree(private, {"notes.txt": "x\n", ".github/workflows/own.yml": "x\n"})
    commit(private, "two files in neither list")
    stops = publish.export(private).stops
    assert _why(stops, "notes.txt") == ["in neither list"] and _why(stops, ".github/workflows/own.yml") == ["in neither list"]


def test_a_symlink_is_never_copied(private):
    (private / "docs" / "outside").symlink_to("/etc/hosts")
    commit(private, "a link out")
    found = publish.export(private)
    assert "docs/outside" not in found.files and _why(found.skipped, "docs/outside") == ["a symlink: never copied"]


def test_a_submodule_is_never_copied(private):
    head = git(private, "rev-parse", "HEAD")
    git(private, "update-index", "--add", "--cacheinfo", f"160000,{head},router/vendor")
    git(private, "commit", "-q", "-m", "a submodule entry")
    found = publish.export(private)
    assert "router/vendor" not in found.files and _why(found.skipped, "router/vendor") == ["a submodule: never copied"]


def test_a_tracked_file_gitignore_ignores_is_never_copied(private):
    write_tree(private, {"router/media/photo.txt": "kept out\n"})  # the fixture's .gitignore ignores media/
    git(private, "add", "-f", "router/media/photo.txt")
    git(private, "commit", "-q", "-m", "a forced add")
    found = publish.export(private)
    assert "router/media/photo.txt" not in found.files
    assert _why(found.skipped, "router/media/photo.txt") == ["matched by .gitignore: never copied"]


def test_an_unknown_binary_stops(private):
    write_tree(private, {"docs/photo.png": b"\x89PNG\r\n\x1a\n\x00a real photo"})
    commit(private, "a binary")
    found = publish.export(private)
    assert "docs/photo.png" not in found.files
    assert _why(found.stops, "docs/photo.png") == ["a binary not in the list of known synthetic binaries"]


def test_a_known_binary_goes_and_a_changed_one_stops(private, monkeypatch):
    data = b"\x89PNG\r\n\x1a\n\x00drawn by code"
    monkeypatch.setattr(publish, "KNOWN_BINARIES", {"docs/sample.png": hashlib.sha256(data).hexdigest()})
    write_tree(private, {"docs/sample.png": data})
    commit(private, "a known binary")
    assert publish.export(private).files["docs/sample.png"] == (data, False)
    write_tree(private, {"docs/sample.png": data + b"!"})
    commit(private, "its bytes changed")
    assert _why(publish.export(private).stops, "docs/sample.png") == ["a known binary whose bytes changed"]


def test_a_tracked_copy_of_a_file_the_publish_makes_stops(private):
    write_tree(private, {"docs/RULES.md": "# a stale copy\n"})
    commit(private, "a tracked copy")
    assert _why(publish.export(private).stops, "docs/RULES.md") == ["made at publish: it must not be tracked"]


def test_the_executable_bit_is_kept(private):
    (private / "scripts" / "tool.py").chmod(0o755)
    commit(private, "executable")
    found = publish.export(private)
    assert found.files["scripts/tool.py"][1] is True and found.files["router/core.py"][1] is False
