"""Build brief 33.2, the review's list (§3): what the reviewer found built short of a decision's words, each fixed here
tests first. Decision 3 on versus (both candidates' builds put SPEC.md back); decision 12's keep-unless words on the
revise, the fix round and the re-asks of a revision from an idea; decision 9's busy words ("…, then revise"); decision
19's `left_out` on a task's spec; decisions 6 and 18's quoted example on a step's card (`plan_step.covers`); decision 2.6's
judge line on a review and an attack; decision 4's spec save while a plan waits for approval; decision 15 after a failed
attack; `PLAN SO FAR` after the spec block; 33.1's D5 once the test command the plan was made with is cleared. Real git in
temp folders, fake agents; every value here is fake."""
import json

from router import __main__ as cli
from router import auto, copies, ideas, jsonview, log, plan, projects, projspec, receipt, spec, whatnow
from router.chatgpt_worker import WorkerError
from tests.test_auto_run import _auto, _route_plan
from tests.test_covers332 import COVERED, REVISED
from tests.test_filemode_flow import FIXED_CALC, CopyWorker, conn, project, runner  # noqa: F401 (fixtures)
from tests.test_plan_approval import _land
from tests.test_plan_chain import A_LIST, ReadWorker, World
from tests.test_plan_contract import GOOD
from tests.test_plan_rest import NO_NEEDS, REVISED_NO_NEEDS
from tests.test_plan_steps import RESEARCH, SKELETON, _approved, _route_step
from tests.test_relay import CONFIG, Chat
from tests.test_revise332 import REV, REV_ANSWERED, _first_plan, _revise
from tests.test_spec332 import SPEC, _commit_spec
from tests.test_specchange332 import CHANGED
from tests.test_versus_project import CHATGPT_BUILD, CLAUDE_BUILD, _run as versus_run

REV_SPEC = REV.replace("   done when: test_convert.py's test_c_to_f passes, checking that 100 C gives 212 F\n",
                       "   done when: test_convert.py's test_c_to_f passes, checking that 100 C gives 212 F\n   covers: E2\n") \
    .replace("   done when: test_convert.py's test_c_to_k passes\n", "   done when: test_convert.py's test_c_to_k passes\n   covers: none\n")
REV_SPEC_ANSWERED = REV_SPEC + "\n## Answered\nA2, B2: small enough\n"


# ---------- decision 3 on versus ----------

def test_both_versus_candidates_builds_put_spec_md_back_and_say_so(project, conn, runner):
    _commit_spec(project)
    chatgpt_build = CHATGPT_BUILD.replace("=== end file ===\n", "=== end file ===\n=== file: SPEC.md ===\n# ChatGPT's spec\n=== end file ===\n", 1)
    code, out, row, worker, chat = versus_run(conn, chatgpt_build=chatgpt_build,
                                              claude_build=(CLAUDE_BUILD, {"calc.py": FIXED_CALC, "SPEC.md": "# Claude's spec\n"}))
    assert code == 0, out
    found = log.project_files_of(log.get_task(conn, row["task_id"]))
    for slot in ("a", "b"):
        candidate = found["candidates"][slot]
        assert candidate["spec_restored"] is True
        assert "SPEC.md" not in [c["path"] for c in candidate["changed"]]
        assert (copies.folder_of(f"{row['task_id']}-{slot}") / "SPEC.md").read_text() == SPEC
    assert out.count(spec.PUT_BACK_LINE) == 2
    for review in (chat.prompts[-1], worker.calls[-1]["prompt"]):  # neither review sees the forged spec
        assert "Claude's spec" not in review and "ChatGPT's spec" not in review
        assert spec.JUDGE_LINE in review  # decision 2.6: a review judges by the spec too
    assert spec.JUDGE_LINE not in worker.calls[0]["prompt"] and spec.JUDGE_LINE not in chat.prompts[0]


# ---------- decision 12: the keep-unless words on every prompt of a revision from an idea ----------

def _idea(conn, text="Add c_to_k(c) to conv.py with a unittest."):
    out = receipt.Receipt()
    assert cli.cmd_ideas(["garden"], conn=conn, add=True, text=text, out=out) == 0, out.message
    return ideas.all_of(conn, "garden")[0]


def test_the_keep_unless_words_reach_the_revise_the_fix_round_and_both_reasks_of_a_revision_from_an_idea(project, conn, runner):
    old, step1 = _first_plan(conn, project)
    idea = _idea(conn)
    w = World(worker=ReadWorker("no plan here", REV, "no revision here", REV_ANSWERED, REV_ANSWERED),
              chat=Chat(A_LIST, "FIX\n1. [must] Step 3's done-when names no file.", "PASS"))
    code, row = w.plan(conn, task=idea.text, idea_ref=str(idea.id))
    assert code == 0, w.said
    planner, reask, revise, revise_reask, fix = [c["prompt"] for c in w.worker.calls]
    for prompt in (planner, reask, revise, revise_reask, fix):
        assert plan.KEEP_UNLESS_LINE in prompt, prompt[:300]
    assert plan.KEEP_UNLESS_LINE not in w.chat.prompts[0]  # the attack judges; it keeps nothing


def test_a_revision_without_an_idea_has_the_words_nowhere(project, conn, runner):
    old, step1 = _first_plan(conn, project)
    code, rev, w = _revise(conn, worker=ReadWorker(REV, REV_ANSWERED, REV_ANSWERED),
                           chat=Chat(A_LIST, "FIX\n1. [must] Step 3's done-when names no file.", "PASS"))
    assert code == 0, w.said
    assert all(plan.KEEP_UNLESS_LINE not in c["prompt"] for c in w.worker.calls)


# ---------- decision 9: the busy words ----------

def test_a_revision_while_a_run_is_stopped_is_refused_with_land_so_far_or_discard_then_revise(project, conn, runner):
    plan_row = _route_plan(conn, _approved(conn))
    cli.cmd_plan_stop_here(f"{plan_row['n']}:2", ["on"], conn=conn, out=receipt.Receipt())
    code, out, run = _auto(conn)
    assert code == 4 and "stop here before step 2" in out.message
    code, rev, w = _revise(conn)
    assert code == 2
    assert f"project garden has task {run['n']} open (Auto stopped). Land the run so far or Discard run first, then revise." in w.said
    assert [r["task_id"] for r in log.recent_tasks(conn, 20) if r["mode"] == "plan"] == [plan_row["task_id"]]  # nothing written


def test_an_open_routed_task_keeps_finish_or_cancel_it_first(project, conn, runner):
    old, step1 = _first_plan(conn, project)
    code, said, step2 = _route_step(conn, f"{old['n']}:2", worker=CopyWorker(SKELETON), chatgpt=Chat("PASS"))
    assert code == 0, said
    code, rev, w = _revise(conn)
    assert code == 2 and f"open (waiting to land). Finish or cancel it first." in w.said and ", then revise" not in w.said


# ---------- decision 19: left out on the task's spec ----------

def test_the_tasks_spec_says_which_call_went_without_it(project, conn, runner):
    _commit_spec(project)
    from tests.test_filemode_flow import BUILD, route
    code, said, row = route(conn, worker=CopyWorker(BUILD), chatgpt=Chat("PASS"))
    assert code == 0, said
    found = jsonview.show_view(conn, log.get_task(conn, row["task_id"]))
    assert found["spec"] == {"hash": spec.digest(SPEC), "chars": len(SPEC), "file": f"tasks/{row['task_id']}/SPEC.md", "left_out": None}
    log.add_call(conn, f"{row['task_id']}-g", row["task_id"], "check", "grok", status="done", text="PASS", verdict="PASS",
                 context={"project": "garden", "lines": 0, "total": 0, "text": "",
                          "spec": spec.left_out({"hash": spec.digest(SPEC), "chars": len(SPEC), "from": row["task_id"]})})
    found = jsonview.show_view(conn, log.get_task(conn, row["task_id"]))
    assert found["spec"]["left_out"] == f"{row['task_id']}-g"


# ---------- decisions 6 and 18: the step card's example ----------

def test_a_steps_json_carries_the_examples_it_covers_with_their_text(project, conn, runner):
    _commit_spec(project)
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    w = World(worker=ReadWorker(COVERED, REVISED))
    code, row = w.plan(conn)
    assert code == 0, w.said
    assert _land(conn, log.get_task(conn, row["task_id"]))[0] == 0
    found = log.get_task(conn, row["task_id"])
    code, said, step = _route_step(conn, f"{found['n']}:1", worker=CopyWorker(RESEARCH), chatgpt=Chat("PASS"))
    assert code == 0, said
    view = plan.step_view(conn, log.get_task(conn, step["task_id"]))
    assert view["covers"] == [{"label": "E1", "text": "c_to_f(100) == 212"}]
    assert jsonview.show_view(conn, log.get_task(conn, step["task_id"]))["plan_step"]["covers"] == view["covers"]
    code, said, step2 = _route_step(conn, f"{found['n']}:2", worker=CopyWorker(RESEARCH), chatgpt=Chat("PASS"))
    assert code == 0, said
    assert [c["label"] for c in plan.step_view(conn, log.get_task(conn, step2["task_id"]))["covers"]] == ["E2", "E3"]


def test_a_step_of_a_plan_without_a_spec_covers_nothing(project, conn, runner):
    old, step1 = _first_plan(conn, project)
    assert plan.step_view(conn, log.get_task(conn, step1["task_id"]))["covers"] == []


# ---------- decision 2.6: the judge line on an attack ----------

def test_a_plans_attacks_get_the_spec_block_and_the_judge_line_and_the_planner_only_the_block(project, conn, runner):
    _commit_spec(project)
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    w = World(worker=ReadWorker(COVERED, REVISED))
    code, row = w.plan(conn)
    assert code == 0, w.said
    block = spec.render("garden", SPEC)
    planner, revise = [c["prompt"] for c in w.worker.calls]
    attack, check = w.chat.prompts
    for prompt in (planner, revise, attack, check, w.cursor.prompts[0]):
        assert block in prompt
    for prompt in (attack, check, w.cursor.prompts[0]):
        assert spec.JUDGE_LINE in prompt
    assert spec.JUDGE_LINE not in planner and spec.JUDGE_LINE not in revise


# ---------- PLAN SO FAR sits after the spec block ----------

def test_the_plan_so_far_block_comes_after_the_spec_block_on_every_call(project, conn, runner):
    _commit_spec(project)
    old, step1 = _first_plan(conn, project, worker=ReadWorker(COVERED, REVISED))
    code, rev, w = _revise(conn, worker=ReadWorker(REV_SPEC, REV_SPEC_ANSWERED))
    assert code == 0, w.said
    block = spec.render("garden", SPEC)
    for prompt in [c["prompt"] for c in w.worker.calls] + w.chat.prompts + w.cursor.prompts:
        assert prompt.index(block) < prompt.index(plan.SO_FAR_LABEL), prompt[:200]


# ---------- decision 4: a spec saved while a plan waits, then Approve ----------

def test_a_spec_saved_while_the_plan_waits_lands_the_plan_as_it_was_and_reads_changed(project, conn, runner, tmp_path):
    _commit_spec(project)
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    w = World(worker=ReadWorker(COVERED, REVISED))
    code, row = w.plan(conn)
    assert code == 0, w.said
    written = projspec.save(conn, "garden", CHANGED, expect=spec.digest(SPEC), journal_dir=tmp_path / "lands",
                            lock_folder=tmp_path / "locks")
    assert written.message == projspec.EDITED and (project / "SPEC.md").read_text() == CHANGED
    found = log.get_task(conn, row["task_id"])
    assert plan.view(conn, found)["spec_changed"] is True
    code, said = _land(conn, found)
    assert code == 0, said
    assert (project / "SPEC.md").read_text() == CHANGED  # the land never touches it
    assert (project / "docs" / "PLAN.md").exists()
    assert plan.record_of(log.get_task(conn, row["task_id"]))["spec_hash"] == spec.digest(SPEC)  # the plan read the old one
    assert whatnow.for_project(conn, "garden")["rung"] == "spec_changed"


# ---------- decision 15: a failed attack nothing could take ----------

def test_a_plan_whose_attack_failed_removes_its_copy_and_says_so(project, conn, runner):
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    w = World(worker=ReadWorker(GOOD), chat=Chat(WorkerError("codex exec failed: boom")))
    code, row = w.plan(conn)
    assert code == 1, w.said
    task = log.get_task(conn, row["task_id"])
    assert task["status"] == "failed" and task["failed_stage"] == 2
    assert not copies.exists(row["task_id"]) and "copy is removed" in w.said
    assert log.project_files_of(task)["copy"] is False


# ---------- 33.1's D5: the test command the plan was made with ----------

def test_clearing_the_test_command_the_plan_was_made_with_makes_it_the_need_and_takes_build_step_k_away(project, conn, runner):
    old, step1 = _first_plan(conn, project)  # the command set before the plan; the planner proposed none
    record = plan.record_of(old)
    assert record["test_command_then"] == "python3 -m unittest" and plan.proposed_test_command(record) is None
    assert whatnow.for_project(conn, "garden")["rung"] == "plan_step"
    assert [m["kind"] for m in plan.moves(conn, old)[0]] == ["build_step"]
    projects.clear_tests("garden")
    line = whatnow.for_project(conn, "garden")
    assert (line["rung"], line["words"], line["control"]) == ("plan_need", "Before step 2: set the test command", "tests")
    assert line["need"] == {"kind": "test_command", "proposed": "python3 -m unittest", "words": "Before step 2: set the test command"}
    assert plan.moves(conn, old)[0] == []
    assert plan.view(conn, old)["test_command"] == {"proposed": "python3 -m unittest", "set": None}
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    assert whatnow.for_project(conn, "garden")["rung"] == "plan_step"
    assert [m["kind"] for m in plan.moves(conn, old)[0]] == ["build_step"]


def test_a_plan_made_without_a_test_command_keeps_no_then_and_proposes_nothing(project, conn, runner):
    w = World(worker=ReadWorker(NO_NEEDS, REVISED_NO_NEEDS))
    code, row = w.plan(conn)
    assert code == 0, w.said
    record = plan.record_of(log.get_task(conn, row["task_id"]))
    assert "test_command_then" not in record
    assert plan.test_command_view(record, "garden") == {"proposed": None, "set": None}
