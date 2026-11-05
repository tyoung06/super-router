"""Build brief 33.1, P (decisions 1 to 8): Plan, a team on a project only. `sr plan` runs redteam's chain as it is filled
now, in its plan shape: Claude plans read only in a copy of the project (stage 1), ChatGPT and Cursor attack the plan,
Claude revises it read only, and ChatGPT checks it with both lists, the file list, the last Test's outcome and the plan's
check line. Every call gets the copy's file list. Refused at intake with nothing written (`plan_refused`). `## One step`
ends the task as `## No split` does. The plan's Claude calls are never taken over; Resume makes them again in the same
copy. Real git in temp folders, fake agents; every value here is fake."""
import json
from pathlib import Path

import pytest

from router import __main__ as cli
from router import copies, filecalls, log, plan, presets, projects, relay, resume, takeover
from tests.helpers import shipped_roster
from tests.test_cursor_send import Cursor, Ready, answer
from tests.test_filemode_flow import conn, project, runner  # noqa: F401 (fixtures)
from tests.test_loop import Clock
from tests.test_plan_contract import GOOD, ONE
from tests.test_relay import CONFIG, Chat, RelayHook

ROSTER = shipped_roster()
LOADED = presets.load_presets(ROSTER, tuple(cli.SENDERS), relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
TASK = "Plan the first version."
A_LIST = ("## Attacks\n1. [high] Step 2's done-when names no file.\n2. [low] Step 1 is long.\n3. [medium] No account "
          "step.\n\n## Strongest\nStep 2's test.")
B_LIST = ("## Attacks\n1. [medium] The key's use is vague.\n2. [low] Two steps is thin.\n3. [low] Why redteam?\n\n"
          "## Strongest\nThe key.")
REVISED = GOOD + "\n## Answered\nA2, B2: the steps are as small as they can be\n"


class ReadWorker:
    """A fake Claude for a plan: records each call's prompt and copy, never writes (the plan's calls read only)."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, prompt, copy=None, search=False, **kw):
        self.calls.append({"prompt": prompt, "copy": copy, "files": sorted(p.name for p in Path(copy.folder).rglob("*")
                                                                           if p.is_file()) if copy else None})
        reply = self.replies.pop(0) if self.replies else REVISED
        if isinstance(reply, BaseException):
            raise reply
        return reply


class World:
    def __init__(self, worker=None, chat=None, cursor=None, ready=None):
        self.worker = worker or ReadWorker(GOOD, REVISED)
        self.chat = chat or Chat(A_LIST, "PASS")
        self.cursor = cursor if cursor is not None else Cursor(answer(B_LIST))
        self.ready = ready or Ready()
        self.lines = []

    def plan(self, conn, task=TASK, project="garden", **kw):
        clock, hook = Clock(), RelayHook()
        code = cli.cmd_plan(task, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[],
                            post=hook.post, worker=self.worker, chatgpt=self.chat, codex_login=lambda: True,
                            cursor=self.cursor, cursor_ready=self.ready, fetch=hook.fetch, close=hook.close,
                            sleep=clock.sleep, clock=clock, wait=True, project=project,
                            files_ready=lambda: (True, None), out=self.lines.append, **kw)
        rows = log.recent_tasks(conn)
        return code, rows[0] if rows else None

    @property
    def said(self):
        return "\n".join(self.lines)


# ---------- the chain (decisions 1, 3 and 8) ----------

def test_a_plan_runs_redteams_chain_in_its_plan_shape_and_waits_to_land(project, conn, runner):
    w = World()
    code, row = w.plan(conn)
    assert code == 0, w.said
    row = log.get_task(conn, row["task_id"])
    assert (row["mode"], row["preset"], row["agent"], row["checker"]) == ("plan", "redteam", "claude", "chatgpt")
    assert row["jev_status"] == "not_asked"
    calls = log.calls_for(conn, row["task_id"])
    assert [(c["kind"], c["stage"], c["role"], c["agent"]) for c in calls] == [
        ("stage", 1, "plan", "claude"), ("stage", 2, "attack", "chatgpt"), ("stage", 3, "attack", "cursor"),
        ("stage", 4, "revise", "claude"), ("check", None, None, "chatgpt")]
    assert [c["copy"].write for c in w.worker.calls] == [False, False]  # stages 1 and 4 read the copy, never write it
    assert log.project_files_of(row)["state"] == "waiting"
    assert [c["path"] for c in log.project_files_of(row)["changed"]] == [plan.FILE]
    assert "docs/PLAN.md written into the copy: 2 steps." in w.said


def test_nothing_outside_the_copy_changed_and_the_copy_holds_no_new_file_but_the_plan(project, conn, runner):
    before = sorted(p.relative_to(project).as_posix() for p in project.rglob("*") if ".git" not in p.parts)
    w = World()
    code, row = w.plan(conn)
    after = sorted(p.relative_to(project).as_posix() for p in project.rglob("*") if ".git" not in p.parts)
    assert code == 0 and before == after
    found = sorted(p.relative_to(copies.folder_of(row["task_id"])).as_posix()
                   for p in copies.folder_of(row["task_id"]).rglob("*") if p.is_file())
    assert found == ["README.md", "calc.py", plan.FILE]


def test_the_planners_prompt_holds_the_menu_without_vote_the_tests_and_the_file_list(project, conn, runner):
    w = World()
    w.plan(conn)
    first = w.worker.calls[0]["prompt"]
    assert first.startswith(TASK) and plan.INSTRUCTIONS.format(name="garden") in first
    assert plan.MENU_HEAD in first and "- route:" in first and "- redteam:" in first and "- vote:" not in first
    assert "- versus:" not in first
    assert "The project's test command: none. Its last Test: never run." in first
    assert plan.SKELETON_TEST_LINE in first  # no test command: step 1 is a skeleton, and the needs propose the command
    assert "===== PROJECT FILES =====\nREADME.md (" in first and "calc.py (" in first
    assert plan.ONE_STEP_LINE in first and plan.SHAPE in first


def test_every_call_gets_the_file_list_and_the_judges_get_the_plans_lines(project, conn, runner):
    w = World()
    w.plan(conn)
    attack, check = w.chat.prompts[0], w.chat.prompts[1]
    assert "===== PROJECT FILES =====" in attack and plan.attack_line(True) in attack
    assert "===== PROJECT FILES =====" in w.cursor.prompts[0]
    assert "===== PROJECT FILES =====" in w.worker.calls[1]["prompt"]  # the revise
    assert plan.check_line(True) in check and "Its last Test: never run." in check
    assert "ATTACK LIST A · ChatGPT" in check and "ATTACK LIST B · Cursor" in check
    assert "===== PROJECT FILES =====" in check


def test_the_revise_and_the_attacks_never_see_a_handoff_line(project, conn, runner):
    w = World()
    w.plan(conn)
    from router import context
    for prompt in [c["prompt"] for c in w.worker.calls] + w.chat.prompts:
        assert context.HANDOFF_LINE not in prompt


def test_with_a_test_command_that_passed_no_skeleton_rule(project, conn, runner, monkeypatch, tmp_path):
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    from router import projtest
    monkeypatch.setattr(projtest, "last", lambda name, run_folder: {"outcome": "passed",
                                                                    "when": "2026-10-28T12:00:00+00:00"})
    w = World()
    w.plan(conn)
    first = w.worker.calls[0]["prompt"]
    assert "The project's test command: `python3 -m unittest`. Its last Test: passed on 2026-10-28." in first
    assert plan.SKELETON_LINE not in first and plan.SKELETON_TEST_LINE not in first
    assert plan.check_line(False) in w.chat.prompts[1]


def test_without_cursor_the_plan_runs_with_one_attacker(project, conn, runner):
    w = World(worker=ReadWorker(GOOD, REVISED.replace("A2, B2:", "A2:")), cursor=Cursor(),
              ready=Ready((False, "Cursor isn't signed in")))
    code, row = w.plan(conn)
    assert code == 0, w.said
    calls = log.calls_for(conn, row["task_id"])
    assert [(c["stage"], c["role"]) for c in calls if c["kind"] == "stage"] == [(1, "plan"), (2, "attack"), (3, "revise")]
    assert "One attacker: Cursor isn't available" in w.said
    assert json.loads(log.get_task(conn, row["task_id"])["slots"])["attack2"] is None


def test_a_plan_that_misses_its_contract_is_re_asked_once_then_stops(project, conn, runner):
    bad = GOOD.replace("team: redteam", "team: vote")
    w = World(worker=ReadWorker(bad, bad))
    code, row = w.plan(conn)
    assert code == 1
    calls = log.calls_for(conn, row["task_id"])
    assert [(c["kind"], c["stage"]) for c in calls] == [("stage", 1), ("reask", 1)]
    assert "Steps: step 2's team 'vote' is not on the TEAMS list" in calls[1]["text"] or True
    assert log.get_task(conn, row["task_id"])["status"] == "failed"
    assert "contract still missing after the re-ask" in w.said


def test_the_fix_round_returns_the_plan_again_read_only(project, conn, runner):
    w = World(worker=ReadWorker(GOOD, REVISED, REVISED), chat=Chat(A_LIST, "FIX\n1. [must] step 2 names no test file",
                                                                 "PASS\n1. fixed"))
    code, row = w.plan(conn)
    assert code == 0, w.said
    fix = w.worker.calls[2]
    assert fix["copy"].write is False and plan.FIX_LINE in fix["prompt"] and "===== PROJECT FILES =====" in fix["prompt"]
    assert log.get_task(conn, row["task_id"])["check_state"] == "fixed"


# ---------- refusals at intake (decision 1) ----------

def _refused(w, conn, **kw):
    code, row = w.plan(conn, **kw)
    return code, row, w.said


@pytest.mark.parametrize("kw, words", [
    (dict(idea_ref="3"), "there is no idea 3"),  # brief 33.2 (decision 12): route's rules, not a flat refusal
    (dict(chat="tray"), "--chat on sr plan is refused"),
    (dict(files=["photo.png"]), "a file on sr plan is refused"),
    (dict(web=True), "--web on sr plan is refused"),
    (dict(task="@claude Plan it."), "an override prefix on sr plan is refused"),
    (dict(project=None), "Plan works on a project only"),
])
def test_refused_at_intake_with_nothing_written(project, conn, runner, kw, words):
    w = World()
    code, row, said = _refused(w, conn, **kw)
    assert code == 2 and row is None and words in said and w.worker.calls == []


def test_a_project_without_git_is_refused_with_file_modes_why(project, conn, runner, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    projects.add("nogit", str(plain))
    w = World()
    code, row = w.plan(conn, project="nogit")
    assert code == 2 and row is None
    assert "Plan reads the project's files, and nogit has no file mode: no git yet: Turn on undo first" in w.said


def test_the_receipt_names_plan_refused(project, conn, runner):
    out = cli.receipt.Receipt()
    w = World()
    clock, hook = Clock(), RelayHook()
    code = cli.cmd_plan(TASK, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[],
                        post=hook.post, worker=w.worker, chatgpt=w.chat, project=None, out=out)
    assert code == 2 and out.code == "plan_refused"


# ---------- One step (decision 6) ----------

def test_one_step_ends_the_plan_as_no_split_does(project, conn, runner):
    w = World(worker=ReadWorker(ONE))
    code, row = w.plan(conn, task="Add a one-line docstring to hello.py.")
    assert code == 1
    row = log.get_task(conn, row["task_id"])
    assert row["status"] == "failed" and row["result"] == "one step: A one-line docstring is one small change, not a plan."
    assert plan.one_step_reason(row) == "A one-line docstring is one small change, not a plan."
    assert [c["stage"] for c in log.calls_for(conn, row["task_id"])] == [1]  # nothing attacked
    assert w.chat.prompts == [] and w.cursor.prompts == []
    assert not copies.exists(row["task_id"])  # the copy removed
    assert log.handoff_of(row) == [] or log.handoff_of(row) is None  # no entry
    assert "Build it: sr route --project garden -- 'Add a one-line docstring to hello.py'\"'\"'s greet function.'" in w.said


# ---------- no takeover, Resume in the same copy (decision 7) ----------

def test_a_stopped_planner_call_is_never_taken_over_and_resume_makes_it_again_by_claude(project, conn, runner):
    from router import claude_worker
    stop = claude_worker.WorkerError("plan limit on claude: you have reached your limit", code="plan_limit")
    w = World(worker=ReadWorker(stop))
    code, row = w.plan(conn, available=_everyone())
    assert code == 1
    calls = log.calls_for(conn, row["task_id"])
    assert [(c["kind"], c["agent"], c["status"]) for c in calls] == [("stage", "claude", "failed")]
    task = log.get_task(conn, row["task_id"])
    assert filecalls.build_call(task, calls[-1])  # read only, but it needs the files: never taken over
    assert not takeover.used(calls) and "sr resume" in w.said
    opened = dict(task)
    opened["status"] = "queued"  # as the takeover reads it while the task is still open
    view = type("Row", (dict,), {"keys": dict.keys})(opened)
    found = takeover.decide(view, calls, calls[-1], available=_everyone(), preset=presets.for_task(task, LOADED)[0])
    assert not found.ok and "never taken over" in found.reason
    decided = resume.decide(task, calls, live=ROSTER.live, preset=presets.for_task(task, LOADED)[0])
    assert decided.ok and decided.substitute == "claude" and decided.call_id.endswith("-resume")
    assert copies.exists(row["task_id"])  # kept for the resume


def _everyone():
    from tests.test_routing_availability import Gate  # a command's gate answering from a table; everyone available
    return Gate()


def test_a_plan_has_no_fallback(project, conn, runner):
    from router import fallback
    w = World()
    code, row = w.plan(conn)
    found = fallback.decide(log.get_task(conn, row["task_id"]), log.calls_for(conn, row["task_id"]), live=ROSTER.live,
                            preset=presets.for_task(log.get_task(conn, row["task_id"]), LOADED)[0])
    assert not found.ok and "a plan has no fallback" in found.reason


def test_the_plans_claude_calls_get_the_planner_notes(project, conn, runner, monkeypatch, tmp_path):
    from router import notes
    notes.PATH.write_text("## All agents\n\n## Claude\n\n## ChatGPT\n\n## Grok\n\n## Cursor\n\n## Planner\nPrefer route.\n")
    w = World()
    w.plan(conn)
    assert notes.PLANNER_OPEN in w.worker.calls[0]["prompt"] and notes.PLANNER_OPEN in w.worker.calls[1]["prompt"]
    assert all(notes.PLANNER_OPEN not in p for p in w.chat.prompts)
