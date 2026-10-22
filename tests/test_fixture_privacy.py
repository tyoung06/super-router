"""Build brief 25, A2 (decision 5): the test files hold nothing of the Mac that recorded them. The streams recorded from
real Cursor and Codex runs keep their shape with the home folder read as `/Users/you` and every account-linked id
(session, request, call, conversation, thread) a fake one; no test file holds this Mac's home folder or the full name
of its account, both read at run time, so this file spells neither."""
import re
import subprocess
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
FIXTURES = TESTS / "fixtures"
RECORDED = sorted((FIXTURES / "cursor").glob("*")) + [FIXTURES / "codex_probe_run10.jsonl"]
UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
FAKE_UUID = re.compile(r"00000000-0000-4000-8000-\d{12}")
HOME_PATH = re.compile(r"/Users/([A-Za-z0-9._-]+)")
REAL_POPEN = subprocess.Popen  # taken at import: conftest blocks real subprocesses, and `id -F` is this file's one


def _test_files():
    return [p for p in TESTS.rglob("*") if p.is_file() and "__pycache__" not in p.parts]


def test_the_recorded_streams_are_all_here():
    assert len(RECORDED) == 5 and all(p.exists() for p in RECORDED)


def test_the_recorded_streams_read_the_home_folder_as_users_you():
    for path in RECORDED:
        homes = set(HOME_PATH.findall(path.read_text()))
        assert homes <= {"you"}, path.name


def test_every_id_in_the_recorded_streams_is_a_fake_one():
    found = {path.name: UUID.findall(path.read_text()) for path in RECORDED}
    assert all(found[name] for name in ("canary-a.ndjson", "canary-b.ndjson", "pin.ndjson", "codex_probe_run10.jsonl"))
    for name, ids in found.items():
        assert all(FAKE_UUID.fullmatch(i) for i in ids), name


def test_no_test_file_holds_this_macs_home_folder():
    home = str(Path.home()).encode()
    assert [p.name for p in _test_files() if home in p.read_bytes()] == []


def test_no_test_file_holds_the_full_name_of_this_macs_account(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", REAL_POPEN)
    try:
        words = subprocess.run(["id", "-F"], capture_output=True, text=True, timeout=10).stdout.split()
    except (OSError, subprocess.SubprocessError):
        words = []
    if len(words) < 2:
        pytest.skip("this account has no two-word full name to look for")
    name = re.compile(re.escape(words[0]) + r"[\s_.\-]*" + re.escape(words[-1]), re.I)
    found = [p.name for p in _test_files() if name.search(p.read_bytes().decode("utf-8", errors="replace"))]
    assert found == []
