"""Build brief 31 (decisions 1 and 2): `sr project test <name>` runs the project's test command as the router runs it after
a build (the sandbox, the four-name environment, the redacted tail), on a throwaway copy of the committed files at the
head, made under the copies root with a task copy's exclusions and removed when the run ends. No task, no log row, no
agent; it never takes the project's lock and never touches the folder. The newest 10 results are kept under
`run/projects/<name>/tests/`; while it runs, the output so far is in `test-live.txt`, whole lines, redacted."""
import json
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from router import __main__ as cli
from router import copies, locks, projects, projtest, testrun

needs_sandbox = pytest.mark.skipif(not testrun.available(), reason="sandbox-exec is not on this machine")

PASSING = """
    import unittest

    class Passing(unittest.TestCase):
        def test_adds(self):
            self.assertEqual(1 + 1, 2)
    """


@pytest.fixture
def sandbox(real_git):
    real_git.add("sandbox-exec")
    return real_git


def git(folder, *args):
    subprocess.run(["git", "-C", str(folder), *args], check=True, capture_output=True)


@pytest.fixture
def garden(tmp_path, monkeypatch):
    """A registered project with git and one commit holding a passing suite; its test command set."""
    monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "projects.json")
    monkeypatch.setattr(projects, "TESTS_PATH", tmp_path / "project_tests.json")
    folder = tmp_path / "garden"
    folder.mkdir()
    (folder / "test_ok.py").write_text(textwrap.dedent(PASSING).lstrip())
    (folder / ".env").write_text("SOIL_KEY=never-in-a-copy-0123456789\n")
    (folder / ".gitignore").write_text(".env\n")
    projects.add("garden", folder)
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    return folder


def commit_all(folder):
    git(folder, "init", "-q")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "first")


def snapshot(folder):
    files = sorted((p.relative_to(folder).as_posix(), p.read_bytes()) for p in Path(folder).rglob("*")
                   if p.is_file() and ".git" not in p.relative_to(folder).parts)
    status = subprocess.run(["git", "-C", str(folder), "status", "--porcelain"], capture_output=True, text=True).stdout
    return files, status


def run_cli(argv, capsys):
    code = cli.main(argv, platform="darwin")
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# ---------- the live output (decision 2) ----------

@needs_sandbox
def test_the_live_file_gets_whole_lines_as_they_arrive_redacted(sandbox, tmp_path):
    copy = tmp_path / "copy"
    copy.mkdir()
    secret = "hydrangea-" + "0123456789"
    (copy / "slow.py").write_text(textwrap.dedent(f"""
        import sys, time
        print("first line holds {secret}", flush=True)
        time.sleep(1.5)
        print("second line", flush=True)
        """).lstrip())
    live = tmp_path / "live.txt"
    seen = {}

    def watch():
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            text = live.read_text() if live.exists() else ""
            if "first line" in text:
                seen["early"] = text
                return
            time.sleep(0.05)
    watcher = threading.Thread(target=watch)
    watcher.start()
    result = testrun.run(copy, ["python3", "slow.py"], project_folder=copy, secrets=[secret], home=tmp_path / "home",
                         live=live)
    watcher.join()
    assert result.outcome == "passed"
    assert "second line" not in seen["early"]  # the first line was there before the run ended
    assert seen["early"].endswith("\n") and secret not in seen["early"] and "[REDACTED]" in seen["early"]
    assert live.read_text() == "first line holds [REDACTED]\nsecond line\n"


# ---------- a run (decision 1) ----------

@needs_sandbox
def test_a_test_runs_on_a_head_copy_that_is_removed_and_never_touches_the_folder(sandbox, garden, tmp_path):
    commit_all(garden)
    (garden / "notes.txt").write_text("uncommitted, never in the copy\n")
    before = snapshot(garden)
    seen = {}

    def runner(copy, words, **kw):
        seen["copy"], seen["files"] = Path(copy), sorted(p.name for p in Path(copy).iterdir())
        seen["under_root"] = copies.copies_root() in Path(copy).parents
        return testrun.run(copy, words, home=tmp_path / "home", **kw)
    record = projtest.run("garden", run_folder=tmp_path / "run", runner=runner)
    assert record["outcome"] == "passed" and record["exit"] == 0 and record["summary"] == "OK"
    assert record["head"] == subprocess.run(["git", "-C", str(garden), "rev-parse", "HEAD"], capture_output=True,
                                            text=True).stdout.strip()
    assert set(record) >= {"outcome", "exit", "summary", "seconds", "when", "head", "command"}
    assert seen["under_root"] and seen["files"] == [".gitignore", "test_ok.py"]  # no .env, no uncommitted file
    assert not seen["copy"].exists()  # removed when the run ended
    assert snapshot(garden) == before
    kept = projtest.last("garden", run_folder=tmp_path / "run")
    assert kept["outcome"] == "passed" and "Ran 1 test" in projtest.output_of(kept, run_folder=tmp_path / "run")


@needs_sandbox
def test_a_failing_suite_and_a_timeout_remove_the_copy_too(sandbox, garden, tmp_path):
    (garden / "test_ok.py").write_text(textwrap.dedent(PASSING.replace("1 + 1, 2", "1 + 1, 3")).lstrip())
    commit_all(garden)
    made = []

    def failing(copy, words, **kw):
        made.append(Path(copy))
        return testrun.run(copy, words, home=tmp_path / "home", **kw)
    record = projtest.run("garden", run_folder=tmp_path / "run", runner=failing)
    assert record["outcome"] == "failed" and record["exit"] == 1 and not made[-1].exists()
    (garden / "test_ok.py").write_text("import time\ntime.sleep(30)\n")
    git(garden, "commit", "-q", "-am", "slow")

    def slow(copy, words, **kw):
        made.append(Path(copy))
        return testrun.run(copy, ["python3", "test_ok.py"], home=tmp_path / "home", timeout=1, **kw)
    record = projtest.run("garden", run_folder=tmp_path / "run", runner=slow)
    assert record["outcome"] == "timed_out" and record["exit"] is None and not made[-1].exists()


def test_the_newest_ten_results_are_kept(garden, tmp_path, real_git):
    commit_all(garden)
    clock = iter(range(1_800_000_000, 1_800_000_200, 5))

    def fake(copy, words, **kw):
        return testrun.Result(0, "passed", "OK", "Ran 1 test\nOK")
    for _ in range(12):
        projtest.run("garden", run_folder=tmp_path / "run", runner=fake, clock=lambda: next(clock), available=lambda: True)
    kept = sorted((tmp_path / "run" / "projects" / "garden" / "tests").glob("*.json"))
    assert len(kept) == 10 and len(list(kept[0].parent.glob("*.txt"))) == 10


# ---------- refusals, with nothing made ----------

def test_no_test_command_is_refused(garden, tmp_path, real_git):
    commit_all(garden)
    projects.clear_tests("garden")
    with pytest.raises(projtest.Refused, match="garden has no test command"):
        projtest.run("garden", run_folder=tmp_path / "run")
    assert not (tmp_path / "run").exists() and not copies.copies_root().exists()


def test_no_git_and_no_commit_are_refused(garden, tmp_path, real_git):
    with pytest.raises(projtest.Refused, match="no git yet"):
        projtest.run("garden", run_folder=tmp_path / "run", available=lambda: True)
    git(garden, "init", "-q")
    with pytest.raises(projtest.Refused, match="no commit yet"):
        projtest.run("garden", run_folder=tmp_path / "run", available=lambda: True)
    assert not copies.copies_root().exists()


def test_the_routers_own_folder_is_refused(garden, tmp_path, real_git, monkeypatch):
    commit_all(garden)
    monkeypatch.setattr(projects, "folder_of", lambda name: Path(cli.__file__).resolve().parent.parent)
    with pytest.raises(projtest.Refused, match="the router's own folder"):
        projtest.run("garden", run_folder=tmp_path / "run", available=lambda: True)


def test_a_second_test_while_one_runs_is_refused_and_the_project_lock_is_never_taken(garden, tmp_path, real_git):
    commit_all(garden)
    run_folder = tmp_path / "run"
    with locks.held(projtest.lock_name("garden"), folder=run_folder, wait=False):
        with pytest.raises(projtest.Refused, match="a Test is already running on garden"):
            projtest.run("garden", run_folder=run_folder, available=lambda: True,
                         runner=lambda copy, words, **kw: testrun.Result(0, "passed", "OK", ""))
    with locks.held("project-garden", folder=run_folder, wait=False):  # a land holds the project: Test still runs
        record = projtest.run("garden", run_folder=run_folder, available=lambda: True,
                              runner=lambda copy, words, **kw: testrun.Result(0, "passed", "OK", ""))
    assert record["outcome"] == "passed"


def test_no_sandbox_is_refused(garden, tmp_path, real_git):
    commit_all(garden)
    with pytest.raises(projtest.Refused, match="no test sandbox"):
        projtest.run("garden", run_folder=tmp_path / "run", available=lambda: False)


# ---------- the command and its status ----------

def test_sr_project_test_json_and_status(garden, tmp_path, real_git, capsys, monkeypatch):
    commit_all(garden)
    monkeypatch.setattr(testrun, "available", lambda: True)
    monkeypatch.setattr(projtest, "RUNNER", lambda copy, words, **kw: testrun.Result(0, "passed", "OK", "Ran 1 test\n\nOK"))
    code, out, err = run_cli(["project", "test", "garden", "--json"], capsys)
    assert code == 0, err
    doc = json.loads(out.strip().splitlines()[-1])
    assert doc["exit"] == 0 and doc["project"]["name"] == "garden" and doc["project"]["test"]["outcome"] == "passed"
    code, out, err = run_cli(["project", "test", "garden", "--status", "--json"], capsys)
    status = json.loads(out.strip().splitlines()[-1])["project"]["test_status"]
    assert status["running"] is False and status["last"]["outcome"] == "passed" and "Ran 1 test" in status["output"]
    code, out, err = run_cli(["project", "test", "garden"], capsys)
    assert code == 0 and "Tests passed on garden" in out


def test_a_refused_test_exits_2_naming_why(garden, tmp_path, real_git, capsys):
    projects.clear_tests("garden")
    code, out, err = run_cli(["project", "test", "garden", "--json"], capsys)
    doc = json.loads(err.strip().splitlines()[-1])
    assert code == 2 and doc["reason_code"] == "project_refused" and "garden has no test command" in doc["message"]
    code, out, err = run_cli(["project", "test", "nowhere", "--json"], capsys)
    assert code == 2 and json.loads(err.strip().splitlines()[-1])["reason_code"] == "project_unknown"


def test_project_list_json_gives_the_last_test(garden, tmp_path, real_git, capsys, monkeypatch):
    commit_all(garden)
    monkeypatch.setattr(testrun, "available", lambda: True)
    monkeypatch.setattr(projtest, "RUNNER", lambda copy, words, **kw: testrun.Result(1, "failed", "FAILED", "x"))
    run_cli(["project", "test", "garden", "--json"], capsys)
    code, out, err = run_cli(["project", "list", "--json"], capsys)
    found = [p for p in json.loads(out)["projects"] if p["name"] == "garden"][0]
    assert found["last_test"]["outcome"] == "failed" and found["last_test"]["when"]
    # D's finding (brief 31): `sr status` runs before main sets the run folder; its records must read the log's run folder
    code, out, err = run_cli(["status", "--json"], capsys)
    found = [p for p in json.loads(out)["projects"] if p["name"] == "garden"][0]
    assert found["last_test"]["outcome"] == "failed" and found["test_running"] is False


# ---------- break-ui (brief 31): the output's display copy, and a Test running ----------

def test_the_status_output_loses_terminal_escapes_and_is_redacted_again(garden, tmp_path, real_git):
    commit_all(garden)
    secret = "hydrangea-" + "0123456789"
    coloured = f"\x1b[1mtest session\x1b[0m\ntest_adds \x1b[32mPASSED\x1b[0m\nkey {secret[:5]}\x1b[0m{secret[5:]}\nbell\x07\n"
    projtest.run("garden", run_folder=tmp_path / "run", available=lambda: True,
                 runner=lambda copy, words, **kw: testrun.Result(0, "passed", "OK", coloured))
    found = projtest.status("garden", run_folder=tmp_path / "run", secrets=[secret])
    assert "\x1b" not in found["output"] and "[32m" not in found["output"]
    assert "test_adds PASSED" in found["output"] and secret not in found["output"] and "key [REDACTED]" in found["output"]
    assert "\x07" not in found["output"] and "bell�" in found["output"]  # another control character shown as a mark
    kept = projtest.output_of(projtest.last("garden", run_folder=tmp_path / "run"), run_folder=tmp_path / "run", name="garden")
    assert "\x1b[32m" in kept  # the kept file stays as it was written


def test_running_says_so_only_while_a_test_holds_its_lock(garden, tmp_path, real_git):
    commit_all(garden)
    run_folder = tmp_path / "run"
    seen = {}

    def runner(copy, words, **kw):
        seen["during"] = projtest.running("garden", run_folder=run_folder)
        return testrun.Result(0, "passed", "OK", "")
    projtest.run("garden", run_folder=run_folder, available=lambda: True, runner=runner)
    assert seen["during"] is True and projtest.running("garden", run_folder=run_folder) is False
    assert projtest.running("garden", run_folder=None) is False
