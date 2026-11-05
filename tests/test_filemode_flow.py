"""Build brief 28 (decisions 1, 3, 5, 8, 9, 10 and 18; Tests, "The change", "Prompts", "Takeover and resume", "Discard and
the open-task rule"): a --project task on a git project runs in file mode. Claude's build call works in the task's copy
(the fake worker edits files there, as Claude's tools would), the change and its diff are kept, the project's tests run
on a throwaway copy (a fake runner here; the real sandbox is tests/test_testrun.py), checkers get the change and the tests
as data, a delivered change waits to land with no handoff entry yet, and the project is busy until it lands or is
discarded. A stopped build call is never taken over: it offers Resume, which puts the copy back first. Real git in temp
folders; fake agents; every value fake."""
import json
from pathlib import Path

import pytest

from router import __main__ as cli
from router import checking, copies, filecalls, log, projects, resume, takeover, testrun
from tests.test_context import TASK
from tests.test_copies import git, make_repo
from tests.test_handoff_contract import HANDOFF
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_relay import CONFIG, GOOD_NOTE, ROSTER, Chat, RelayHook
from tests.test_collab import LOADED
from tests.helpers import fake_label, as_recheck
from tests.test_resume_run import WRITING

CODE = {**WRITING, "label": "code"}
FIXED_CALC = "def add(a, b):\n    return a + b\n"


@pytest.fixture
def conn(tmp_path):
    c = log.init_db(tmp_path / "router.db")  # a log on disk, so the diff and the test output are kept beside it
    yield c
    c.close()


@pytest.fixture
def project(real_git, tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "config" / "projects.json")
    monkeypatch.setattr(projects, "TESTS_PATH", tmp_path / "config" / "project_tests.json")
    folder = tmp_path / "garden"
    make_repo(folder, {"calc.py": "def add(a, b):\n    return a - b\n", "README.md": "# Garden\n"})
    projects.add("garden", str(folder))
    git(folder, "add", "HANDOFF.md")
    git(folder, "commit", "-q", "-m", "handoff")
    return folder


class CopyWorker:
    """A fake Claude: on a file-mode call it applies the scripted edits in the copy (its working folder) and answers."""

    def __init__(self, *steps):
        self.steps, self.calls = list(steps), []

    def __call__(self, prompt, copy=None, search=False, **kw):
        self.calls.append({"prompt": prompt, "copy": copy, "search": search})
        step = self.steps.pop(0) if self.steps else ("an answer\n\n" + HANDOFF, {})
        if isinstance(step, BaseException):
            raise step
        reply, edits = step
        for path, body in edits.items():
            target = Path(copy.folder) / path
            if body is None:
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(body)
        return as_recheck(prompt, reply)  # brief 29.1: an old-shape re-check reply in the new shape


class Runner:
    def __init__(self, *results):
        self.results, self.runs = list(results), []

    def __call__(self, folder, words, *, project_folder, secrets=()):
        self.runs.append({"folder": Path(folder), "words": words, "project_folder": Path(project_folder),
                          "files": sorted(p.name for p in Path(folder).iterdir())})
        return self.results.pop(0) if self.results else testrun.Result(0, "passed", "OK", "Ran 1 test\n\nOK")


@pytest.fixture
def runner(monkeypatch):
    found = Runner()
    monkeypatch.setattr(testrun, "run", found)
    monkeypatch.setattr(testrun, "available", lambda: True)
    return found


def route(conn, *, worker, chatgpt=None, jev=CODE, files_ready=lambda: (True, None), task=TASK, wait=True):
    lines, clock, hook = [], Clock(), Webhook()
    code = cli.cmd_route(task, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=fake_label(jev),
                         post=hook.post, worker=worker, chatgpt=chatgpt or Chat("PASS"), codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=wait, out=lines.append,
                         project="garden", files_ready=files_ready)
    return code, "\n".join(lines), log.recent_tasks(conn)[0]


BUILD = ("Fixed add.\n\n## Handoff\n### Produced\ncalc.py and test_calc.py changed\n### Status\nadd works\n### Next\nship it",
         {"calc.py": FIXED_CALC, "test_calc.py": "import unittest\n"})


# ---------- intake (decision 1) ----------

def test_a_git_project_runs_in_file_mode_and_its_copy_is_made_at_intake(project, conn, runner):
    worker = CopyWorker(BUILD)
    code, out, row = route(conn, worker=worker)
    assert code == 0, out
    found = log.project_files_of(row)
    assert found["mode"] == "on" and found["base"] == git(project, "rev-parse", "HEAD").decode().strip()
    assert found["branch"] == "main" and found["files"] == 2  # calc.py and README.md; HANDOFF.md is never copied
    assert "Files: a copy of garden at" in out


def test_a_project_without_git_runs_handoff_only_and_says_why_on_the_record(project, conn, runner, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    projects.remove("garden")
    projects.add("garden", str(plain))
    asked = []
    code, out, row = route(conn, worker=Scripted("Two lines.\n\n" + HANDOFF), files_ready=lambda: asked.append(1))
    assert code == 0 and asked == []
    assert log.project_files_of(row) == {"mode": "off", "state": "none", "copy": False, "why": "no git yet: Turn on undo"}
    assert "Files:" not in out  # Terminal reads as before; the card names why


def test_another_doer_runs_handoff_only_and_never_asks_the_file_check(project, conn, runner):
    asked = []
    chat = Chat("Done by ChatGPT.\n\n" + HANDOFF, "PASS")
    code, out, row = route(conn, worker=Scripted("PASS"), chatgpt=chat, jev={**WRITING, "label": "web_research"},
                           files_ready=lambda: asked.append(1) or (True, None))
    found = log.project_files_of(row)
    assert asked == [] and found["mode"] == "off" and found["why"] == "ChatGPT can't change project files: nothing to land"


def test_the_file_check_not_passed_runs_handoff_only(project, conn, runner):
    why = "Claude's file check hasn't passed on Claude Code 2.1.311"
    code, out, row = route(conn, worker=Scripted("Two lines.\n\n" + HANDOFF, "PASS"), files_ready=lambda: (False, why))
    assert log.project_files_of(row)["why"] == why and not copies.exists(row["task_id"])


# ---------- the build call in the copy (decisions 3, 5, 8) ----------

def test_the_build_call_works_in_the_copy_and_the_change_waits_to_land(project, conn, runner):
    worker = CopyWorker(BUILD)
    chat = Chat("PASS")
    code, out, row = route(conn, worker=worker, chatgpt=chat)
    assert code == 0, out
    spec = worker.calls[0]["copy"]
    assert spec.write is True and Path(spec.folder) == copies.folder_of(row["task_id"])
    assert (project / "calc.py").read_text() == "def add(a, b):\n    return a - b\n"   # the folder is untouched
    found = log.project_files_of(row)
    assert found["state"] == "waiting" and found["copy"] is True
    assert found["changed"] == [{"path": "calc.py", "status": "changed", "plus": 1, "minus": 1},
                                {"path": "test_calc.py", "status": "added", "plus": 1, "minus": 0}]
    diff = (Path(conn.execute("PRAGMA database_list").fetchone()[2]).parent / found["diff"]).read_text()
    assert "+    return a + b" in diff and found["diff"] == f"tasks/{row['task_id']}/changes.diff"
    assert "Waiting to land: sr land" in out and "Files: 2 changed (+2 −1): calc.py, test_calc.py" in out


def test_the_tests_run_after_the_build_on_a_throwaway_and_the_row_keeps_them(project, conn, runner, tmp_path):
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    worker = CopyWorker(BUILD)
    code, out, row = route(conn, worker=worker)
    assert runner.runs[0]["folder"] == copies.folder_of(row["task_id"]) and runner.runs[0]["words"] == ["python3", "-m", "unittest"]
    assert runner.runs[0]["project_folder"] == project and "test_calc.py" in runner.runs[0]["files"]
    do = next(c for c in log.calls_for(conn, row["task_id"]) if c["kind"] == "do")
    tests = log.tests_of(do)
    assert tests == {"outcome": "passed", "exit": 0, "summary": "OK", "output": f"tasks/{row['task_id']}/tests-1.txt",
                     "command": ["python3", "-m", "unittest"]}
    assert (tmp_path / tests["output"]).read_text() == "Ran 1 test\n\nOK" and "tests passed" in out
    assert log.project_files_of(row)["tests"] == tests


def test_no_test_command_runs_nothing_and_says_so(project, conn, runner):
    code, out, row = route(conn, worker=CopyWorker(BUILD))
    do = next(c for c in log.calls_for(conn, row["task_id"]) if c["kind"] == "do")
    assert runner.runs == [] and log.tests_of(do)["outcome"] == "not_run"
    assert "no tests run: the project has no test command" in out


def test_a_change_holding_what_a_copy_never_carries_fails_the_call_and_stops_the_task(project, conn, runner):
    bad = ("Done.\n\n" + HANDOFF, {".env": "X=1\n"})
    code, out, row = route(conn, worker=CopyWorker(bad))
    do = next(c for c in log.calls_for(conn, row["task_id"]) if c["kind"] == "do")
    assert do["status"] == "failed" and do["reason_code"] == "copy_problem" and ".env" in do["text"]
    assert row["status"] == "failed" and not any(c["call_id"].endswith("-takeover") for c in log.calls_for(conn, row["task_id"]))
    assert copies.exists(row["task_id"])  # kept for Discard or Resume


def test_an_empty_change_is_delivered_as_today_and_the_copy_goes(project, conn, runner):
    code, out, row = route(conn, worker=CopyWorker(("Nothing to change.\n\n" + HANDOFF, {})))
    found = log.project_files_of(row)
    assert found["state"] == "none" and found["copy"] is False and not copies.exists(row["task_id"])
    assert "nothing to land" in out and projects.entries_of((project / "HANDOFF.md").read_text())  # the entry, as today


# ---------- the prompts (decision 9) ----------

def test_the_build_prompt_ends_with_the_file_paragraph(project, conn, runner):
    worker = CopyWorker(BUILD)
    route(conn, worker=worker)
    prompt = worker.calls[0]["prompt"]
    assert prompt.endswith(filecalls.build_paragraph(log.recent_tasks(conn)[0]))
    assert prompt.index("===== end handoff =====") < prompt.index("The working folder is a copy of the project garden")
    assert "The project has no test command, so no tests run." in prompt


def test_the_checker_gets_the_change_and_the_tests_as_data(project, conn, runner):
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    runner.results = [testrun.Result(1, "failed", "FAILED (failures=1)", "AssertionError: 1 != 5\n\nFAILED (failures=1)")]
    chat = Chat("PASS")
    route(conn, worker=CopyWorker(BUILD), chatgpt=chat)
    prompt = chat.prompts[0]
    assert "===== change: 2 files =====\nchanged calc.py (+1 -1)\nadded test_calc.py (+1 -0)" in prompt
    assert "+    return a + b" in prompt and "===== end change =====" in prompt
    assert ("===== tests =====\ncommand: python3 -m unittest\noutcome: failed (exit 1)\nAssertionError: 1 != 5" in prompt)
    assert prompt.rstrip().endswith(filecalls.JUDGE_LINE)
    assert prompt.index("===== RESULT =====") < prompt.index("===== change:") < prompt.index("===== tests =====")


def test_the_diff_is_cut_in_the_prompt_and_the_file_list_kept(project, conn, runner, monkeypatch):
    monkeypatch.setattr(filecalls, "DIFF_LIMIT", 40)
    chat = Chat("PASS")
    route(conn, worker=CopyWorker(BUILD), chatgpt=chat)
    prompt = chat.prompts[0]
    assert "changed calc.py (+1 -1)\nadded test_calc.py (+1 -0)" in prompt
    assert "[the diff is cut here at 40 characters; the list above names every changed file]" in prompt


def test_the_fix_round_gets_the_latest_tests_then_the_paragraph(project, conn, runner):
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    runner.results = [testrun.Result(1, "failed", "FAILED (failures=1)", "AssertionError\nFAILED (failures=1)"),
                      testrun.Result(0, "passed", "OK", "OK")]
    worker = CopyWorker(BUILD, ("Fixed the test.\n\n" + HANDOFF, {"test_calc.py": "import unittest  # fixed\n"}))
    chat = Chat("FIX\n1. the test fails", "PASS")
    code, out, row = route(conn, worker=worker, chatgpt=chat)
    fix = worker.calls[1]
    assert fix["copy"].write is True
    assert "===== tests =====\ncommand: python3 -m unittest\noutcome: failed (exit 1)" in fix["prompt"]
    assert fix["prompt"].endswith(filecalls.build_paragraph(log.get_task(conn, row["task_id"])))
    assert "outcome: passed (exit 0)" in chat.prompts[1]  # the re-check sees the fix's tests
    assert log.get_task(conn, row["task_id"])["check_state"] == "fixed" and "waiting" == log.project_files_of(log.get_task(conn, row["task_id"]))["state"]


def test_a_task_not_in_file_mode_gets_no_file_block(project, conn, runner, tmp_path):
    chat = Chat("PASS")
    code, out, row = route(conn, worker=Scripted("Two lines.\n\n" + HANDOFF), chatgpt=chat,
                           files_ready=lambda: (False, "Claude's file check hasn't passed"))
    assert "===== change:" not in chat.prompts[0] and "working folder is a copy" not in chat.prompts[0]


# ---------- delivery and the entry (decision 10) ----------

def test_no_entry_is_written_while_the_change_waits_and_the_project_is_busy(project, conn, runner):
    before = (project / "HANDOFF.md").read_text()
    code, out, row = route(conn, worker=CopyWorker(BUILD))
    assert (project / "HANDOFF.md").read_text() == before and log.handoff_of(log.get_task(conn, row["task_id"])) == []
    assert log.open_task_for(conn, "garden")["task_id"] == row["task_id"]
    code, out2, _ = route(conn, worker=CopyWorker(BUILD))
    assert code == 2 and f"project garden has task {row['n']} open (waiting to land)" in out2


def test_a_failed_check_keeps_the_copy_writes_the_failed_line_and_frees_the_project(project, conn, runner):
    worker = CopyWorker(BUILD, ("Still wrong.\n\n" + HANDOFF, {}))
    chat = Chat("FIX\n1. wrong", "FIX\n1. still wrong")
    code, out, row = route(conn, worker=worker, chatgpt=chat)
    row = log.get_task(conn, row["task_id"])
    found = log.project_files_of(row)
    assert row["check_state"] == "failed" and found["state"] == "none" and found["copy"] is True
    assert "failed" in projects.entries_of((project / "HANDOFF.md").read_text())[0]
    assert log.open_task_for(conn, "garden") is None and "sr discard" in out


def test_the_delivered_result_is_still_remembered_as_today(project, conn, runner):
    code, out, row = route(conn, worker=CopyWorker(BUILD))
    assert log.get_task(conn, row["task_id"])["result"].startswith("Fixed add.")


# ---------- takeover, resume, fallback (decision 18) ----------

def test_a_stopped_build_call_is_never_taken_over_and_resume_restores_the_copy_first(project, conn, runner):
    from router import claude_worker
    limit = claude_worker.WorkerError("plan limit on claude: You've hit your limit", code="plan_limit")

    class HalfThenStop(CopyWorker):
        def __call__(self, prompt, copy=None, **kw):
            (Path(copy.folder) / "half-done.txt").write_text("partial\n")
            raise limit
    code, out, row = route(conn, worker=HalfThenStop())
    calls = log.calls_for(conn, row["task_id"])
    assert row["status"] == "failed" and calls[-1]["reason_code"] == "plan_limit"
    assert not any(takeover.is_takeover(c) for c in calls)
    open_row = {**dict(log.get_task(conn, row["task_id"])), "status": "sent"}  # as the takeover saw it, still open
    assert takeover._not_covered(open_row, calls, calls[-1], None).startswith("a file-mode build call is never taken over")
    plan = resume.decide(log.get_task(conn, row["task_id"]), calls, live=ROSTER.live)
    assert plan.ok and plan.substitute == "claude"
    worker = CopyWorker(BUILD)
    lines = []
    code = cli.cmd_resume([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                          settings_paths=[], post=Webhook().post, worker=worker, chatgpt=Chat("PASS"),
                          codex_login=lambda: True, out=lines.append)
    assert code == 0, lines
    copy = Path(worker.calls[0]["copy"].folder)
    assert not (copy / "half-done.txt").exists()  # the stopped call's file is gone: the copy was restored first
    assert [c["path"] for c in log.project_files_of(log.get_task(conn, row["task_id"]))["changed"]] == ["calc.py", "test_calc.py"]
    assert any("Files: the copy is back as it was before" in line for line in lines)
    assert log.project_files_of(log.get_task(conn, row["task_id"]))["state"] == "waiting"


def test_a_file_mode_task_never_falls_back(project, conn, runner):
    worker = CopyWorker(BUILD, ("Still wrong.\n\n" + HANDOFF, {}))
    code, out, row = route(conn, worker=worker, chatgpt=Chat("FIX\n1. wrong", "FIX\n1. still wrong"))
    from router import fallback
    plan = fallback.decide(log.get_task(conn, row["task_id"]), log.calls_for(conn, row["task_id"]), live=ROSTER.live)
    assert not plan.ok and "a file-mode task never falls back" in plan.reason


def test_a_check_rounds_takeover_is_unchanged(project, conn, runner):
    from router import chatgpt_worker
    chat = Chat(chatgpt_worker.WorkerError("codex exited 1: model at capacity"))
    worker = CopyWorker(BUILD, ("PASS", {}))
    code, out, row = route(conn, worker=worker, chatgpt=chat)
    calls = log.calls_for(conn, row["task_id"])
    check = next(c for c in calls if c["kind"] == "check")
    assert check["status"] == "failed" and check["reason_code"] is None
    assert filecalls.build_call(log.get_task(conn, row["task_id"]), check) is False  # a check is covered as today
    open_row = {**dict(log.get_task(conn, row["task_id"])), "status": "sent"}
    assert takeover._not_covered(open_row, calls[:calls.index(check) + 1], check, None) is None


# ---------- relay: research-build and redteam on a git project ----------

from tests.test_context import ATTACKS, BUILT, REVISED, SECTION  # noqa: E402


def relay(conn, preset, *, worker, chatgpt=None, hook=None, slots=(), files_ready=lambda: (True, None)):
    lines, clock, hook = [], Clock(), hook or RelayHook(s1=GOOD_NOTE)
    code = cli.cmd_relay(preset, TASK, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                         settings_paths=[], post=hook.post, worker=worker, chatgpt=chatgpt or Chat("PASS"),
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=True, slots=list(slots), out=lines.append, project="garden", files_ready=files_ready)
    rows = log.recent_tasks(conn)
    return code, "\n".join(lines), rows[0] if rows else None, hook


def test_research_build_builds_in_the_copy_and_grok_researches_as_today(project, conn, runner):
    worker, chat = CopyWorker(("built" + SECTION, {"calc.py": FIXED_CALC})), Chat("PASS")
    code, out, row, hook = relay(conn, "research-build", worker=worker, chatgpt=chat)
    assert code == 0, out
    assert "working folder is a copy" not in hook.sent[0]["task"] and "===== change:" not in hook.sent[0]["task"]
    assert worker.calls[0]["copy"].write is True
    assert worker.calls[0]["prompt"].endswith(filecalls.build_paragraph(log.get_task(conn, row["task_id"])))
    assert "===== change: 1 file =====\nchanged calc.py (+1 -1)" in chat.prompts[0]
    assert log.project_files_of(log.get_task(conn, row["task_id"]))["state"] == "waiting"


def test_redteam_builds_and_revises_in_the_copy_and_the_attacker_gets_the_change(project, conn, runner):
    worker = CopyWorker((BUILT + SECTION, {"calc.py": FIXED_CALC}),
                        (REVISED, {"test_calc.py": "import unittest\n"}))
    chat = Chat(ATTACKS, "PASS")
    code, out, row, hook = relay(conn, "redteam", worker=worker, chatgpt=chat)
    assert code == 0, out
    assert [c["copy"].write for c in worker.calls] == [True, True]
    attack, check = chat.prompts
    assert "===== change: 1 file =====\nchanged calc.py (+1 -1)" in attack and attack.rstrip().endswith(filecalls.JUDGE_LINE)
    assert "===== change: 2 files =====" in check
    found = log.project_files_of(log.get_task(conn, row["task_id"]))
    assert [c["path"] for c in found["changed"]] == ["calc.py", "test_calc.py"] and found["state"] == "waiting"


def test_a_build_slot_given_to_another_agent_on_a_git_project_is_refused(project, conn, runner):
    code, out, row, hook = relay(conn, "research-build", worker=CopyWorker(), slots=[("build", "chatgpt"), ("check", "claude")])
    assert code == 2 and row is None
    assert "only Claude changes project files" in out and "Nothing was logged or sent." in out


def test_a_claude_checker_reads_the_copy_without_write_tools(project, conn, runner):
    """The checker is Claude when ChatGPT isn't the checker: its call runs in the copy, read only (decision 3)."""
    from tests.test_resume_run import WRITING  # noqa: F401
    worker = CopyWorker(BUILD, ("PASS", {}))
    code, out, row = route(conn, worker=worker, jev={**WRITING, "label": "code"})
    task = log.get_task(conn, row["task_id"])
    assert task["checker"] in ("chatgpt", "claude")
    if task["checker"] == "claude":
        assert worker.calls[1]["copy"].write is False
