"""Brief 29.1 (decision 2; brief 28's issues 16 and 17): no file changed, no tests. A build or fix call that leaves the change
since the base empty runs no tests (`not_run`, why `no file changed`); its checker gets "No file changed, so no tests ran."
in place of the tests block and the judge line without "and the test results"; a call that changed no file while the change
isn't empty runs none either and keeps the task's last record. A task delivered or failed with no change removes its copy
then; a stopped one keeps it for Resume. Real git in temp folders, fake agents; every value fake."""
from router import copies, filecalls, log, projects, testrun
from tests.test_filemode_flow import BUILD, Chat, CopyWorker, Runner, conn, project, route, runner  # noqa: F401
from tests.test_handoff_contract import HANDOFF

LISTING = ("The project holds calc.py and README.md.\n\n" + HANDOFF, {})


def _tests_set():
    projects.set_tests("garden", ["python3", "-m", "unittest"])


def test_a_build_that_changed_no_file_runs_no_tests_and_says_why(project, conn, runner):
    _tests_set()
    chat = Chat("PASS")
    code, out, row = route(conn, worker=CopyWorker(LISTING), chatgpt=chat)
    assert code == 0, out
    assert runner.runs == []
    do = next(c for c in log.calls_for(conn, row["task_id"]) if c["kind"] == "do")
    assert log.tests_of(do)["outcome"] == "not_run" and log.tests_of(do)["why"] == "no file changed"
    assert "no tests run: no file changed" in out
    prompt = chat.prompts[0]
    assert "===== change: 0 files =====\n(no file changed)" in prompt
    assert "No file changed, so no tests ran." in prompt and "===== tests =====" not in prompt
    assert prompt.rstrip().endswith(filecalls.NO_CHANGE_JUDGE_LINE)
    assert "and the test results" not in filecalls.NO_CHANGE_JUDGE_LINE
    assert filecalls.NO_CHANGE_JUDGE_LINE == filecalls.JUDGE_LINE.replace(" and the test results", "")


def test_a_task_delivered_with_no_change_removes_its_copy_and_says_no_file_changed(project, conn, runner):
    code, out, row = route(conn, worker=CopyWorker(LISTING), chatgpt=Chat("PASS"))
    found = log.project_files_of(log.get_task(conn, row["task_id"]))
    assert found["copy"] is False and not copies.exists(row["task_id"]) and found["changed"] == []
    assert "Files: no file changed; nothing to land." in out


def test_a_failed_check_with_no_change_removes_its_copy_too(project, conn, runner):
    """Issue 17: a task that fails with no change keeps nothing to discard."""
    worker = CopyWorker(LISTING, ("Still nothing to change.\n\n" + HANDOFF, {}))
    code, out, row = route(conn, worker=worker, chatgpt=Chat("FIX\n1. [must] wrong", "FIX\n1. not fixed: still wrong"))
    row = log.get_task(conn, row["task_id"])
    assert row["check_state"] == "failed", out
    found = log.project_files_of(row)
    assert found["copy"] is False and not copies.exists(row["task_id"])
    assert "Files: no file changed; the copy is removed." in out


def test_a_stopped_task_with_no_change_keeps_its_copy_for_resume(project, conn, runner):
    worker = CopyWorker(LISTING, RuntimeError("the fix round's process died"))
    code, out, row = route(conn, worker=worker, chatgpt=Chat("FIX\n1. [must] wrong"))
    row = log.get_task(conn, row["task_id"])
    assert copies.exists(row["task_id"]) and log.project_files_of(row)["copy"] is True


def test_a_fix_that_changed_no_file_keeps_the_last_tests_and_runs_none(project, conn, runner):
    """The change since the base isn't empty (the build changed calc.py), but the fix call changed nothing: no tests run
    after it, the task keeps the build's test record, and the re-check gets it as before."""
    _tests_set()
    runner.results = [testrun.Result(1, "failed", "FAILED (failures=1)", "AssertionError\nFAILED (failures=1)")]
    worker = CopyWorker(BUILD, ("The failing test is expected: it pins the old bug.\n\n" + HANDOFF, {}))
    chat = Chat("FIX\n1. [must] the test fails", "PASS")
    code, out, row = route(conn, worker=worker, chatgpt=chat)
    assert len(runner.runs) == 1, "only the build call ran the tests"
    calls = log.calls_for(conn, row["task_id"])
    fix = next(c for c in calls if c["kind"] == "fix")
    assert log.tests_of(fix) is None
    assert log.project_files_of(log.get_task(conn, row["task_id"]))["tests"]["outcome"] == "failed"
    recheck = chat.prompts[-1]
    assert "===== tests =====\ncommand: python3 -m unittest\noutcome: failed (exit 1)" in recheck
    assert recheck.rstrip().endswith(filecalls.JUDGE_LINE)
