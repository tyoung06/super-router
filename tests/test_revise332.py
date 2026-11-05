"""Build brief 33.2, R1 (decisions 9 and 10): Revise plan, no new flag. `sr plan` on a project whose current plan has open
steps makes a revision: the record carries `revises` and `inherited`; the planner returns only the steps after the done
ones, numbered from d+1 (d + new ≤ 12), with `## Needs from you`, `covers:` and `## Changed`; `## One step` is not allowed;
code prepends the done steps byte for byte. Every call gets the current plan as `PLAN SO FAR`. Ticks for an inherited step
come from the old plan's step tasks. The land renders docs/PLAN.md with the inherited steps ticked and the title saying
it revises #old; the old plan's Undo is refused; the revision's Undo makes the old plan current again. Edits touch new
steps only; marks start empty. Refused at intake: an open task, a kept failed change of a step. The estimate counts the
new steps. Covers survive a spec edit by text. Real git in temp folders, fake agents; every value here is fake."""
import json
from argparse import Namespace

import pytest

from router import __main__ as cli
from router import auto, checking, log, plan, projects, receipt, spec
from tests.test_copies import git
from tests.test_filemode_flow import CopyWorker, conn, project, runner  # noqa: F401 (fixtures)
from tests.test_plan_approval import _land
from tests.test_plan_chain import A_LIST, ReadWorker, World
from tests.test_plan_contract import GOOD, MENU
from tests.test_plan_rest import NO_NEEDS, REVISED_NO_NEEDS, _now
from tests.test_plan_steps import RESEARCH, SKELETON, _route_step
from tests.test_relay import CONFIG, Chat
from tests.test_spec332 import SPEC, _commit_spec

REV = """## Steps
2. Add the Celsius to Fahrenheit conversion with its test, as a routed task.
   team: route
   why: the core rule
   done when: test_convert.py's test_c_to_f passes, checking that 100 C gives 212 F
3. Add c_to_k(c) to conv.py with a unittest.
   team: route
   why: the idea
   done when: test_convert.py's test_c_to_k passes

## Needs from you
none

## Changed
step 2: its team is now route, a routed task is enough
"""
REV_ANSWERED = REV + "\n## Answered\nA2, B2: small enough\n"


def _first_plan(conn, project, *, worker=None):
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    w = World(worker=worker or ReadWorker(NO_NEEDS, REVISED_NO_NEEDS))
    code, row = w.plan(conn)
    assert code == 0, w.said
    assert _land(conn, log.get_task(conn, row["task_id"]))[0] == 0
    found = log.get_task(conn, row["task_id"])
    code, said, step = _route_step(conn, f"{found['n']}:1", worker=CopyWorker(RESEARCH))  # step 1 done, no change
    assert code == 0, said
    return log.get_task(conn, row["task_id"]), step


def _revise(conn, text="Add c_to_k.", **kw):
    w = World(worker=kw.pop("worker", None) or ReadWorker(REV, REV_ANSWERED), **kw)
    code, row = w.plan(conn, task=text)
    return code, (log.get_task(conn, row["task_id"]) if row is not None else None), w


# ---------- the lifted refusal, the record, the prompts (decision 9) ----------

def test_a_plan_with_an_open_step_is_revised_in_place_of_refused_and_every_call_gets_the_plan_so_far(project, conn, runner):
    old, step1 = _first_plan(conn, project)
    code, rev, w = _revise(conn)
    assert code == 0, w.said
    record = plan.record_of(rev)
    assert record["revises"] == old["task_id"] and record["revises_n"] == old["n"] and record["inherited"] == 1
    assert record["steps"][0] == plan.record_of(old)["steps"][0]  # byte for byte from the old record
    assert [s["text"][:12] for s in record["steps"]] == ["Make the ske", "Add the Cels", "Add c_to_k(c"]
    assert record["changed"] == [{"step": 2, "why": "its team is now route, a routed task is enough"}]
    planner, revise = [c["prompt"] for c in w.worker.calls]
    attack, check = w.chat.prompts
    for prompt in (planner, revise, attack, check, w.cursor.prompts[0]):
        assert plan.SO_FAR_LABEL in prompt and f"Done by #{step1['n']}" in prompt and "- [x] **Step 1.**" in prompt
    assert plan.revision_line(1) in planner and plan.revision_line(1) in revise
    assert plan.CHANGED_FORM in planner and plan.CHANGED_FORM in revise and plan.ONE_STEP_LINE not in planner
    assert "numbered from 2" in planner
    doc = plan.view(conn, rev)
    assert doc["revises"] == {"task_id": old["task_id"], "n": old["n"]} and doc["inherited"] == 1
    assert doc["changed"] == record["changed"] and [s["state"] for s in doc["steps"]] == ["done", "open", "open"]
    assert doc["steps"][0]["task"]["task_id"] == step1["task_id"]


def test_the_revisions_contract_counts_from_d_plus_1_caps_at_12_needs_changed_and_refuses_one_step():
    parsed, missing = plan.read(REV, MENU, revision=1)
    assert missing == [] and parsed.changed == [{"step": 2, "why": "its team is now route, a routed task is enough"}]
    assert [s["text"][:7] for s in parsed.steps] == ["Add the", "Add c_t"]
    parsed, missing = plan.read(REV.replace("2. Add the", "1. Add the").replace("3. Add c", "2. Add c"), MENU, revision=1)
    assert missing == ["Steps: a revision's steps are numbered from 2 (steps 1 to 1 are done and stay); the first here is 1"]
    parsed, missing = plan.read(REV.replace("\n## Changed\nstep 2: its team is now route, a routed task is enough\n", "\n"), MENU, revision=1)
    assert missing == ["Changed: the ## Changed heading is missing (one `step k: <why>` line per open step you changed or dropped, or none)"]
    parsed, missing = plan.read(REV.replace("step 2: its team", "step 1: its team"), MENU, revision=1)
    assert missing == ["Changed: step 1 is done and stays; name an open step of the current plan (step 2 on)"]
    parsed, missing = plan.read(REV.replace("step 2: its team is now route, a routed task is enough", "none"), MENU, revision=1)
    assert missing == [] and parsed.changed == []
    parsed, missing = plan.read(REV.replace("step 2: its team is now route, a routed task is enough", "the team changed"), MENU, revision=1)
    assert missing == ["Changed: this line is not `step k: <why>` nor none: 'the team changed'"]
    from tests.test_plan_contract import ONE
    parsed, missing = plan.read(ONE, MENU, revision=1)
    assert missing == ["One step: not allowed on a revision; return the steps after the done ones (`## Steps`, `## Needs from you`, `## Changed`)"]
    many = "## Steps\n" + "".join(f"{k}. Step {k}.\n   team: route\n   why: w\n   done when: t\n" for k in range(2, 14)) + "\n## Needs from you\nnone\n\n## Changed\nnone\n"
    parsed, missing = plan.read(many, MENU, revision=1)
    assert missing == ["Steps: 1 done step plus 12 new make 13; a plan holds at most 12"]
    assert plan.read(GOOD, MENU)[0].changed is None  # not a revision: no `## Changed`, and none asked


# ---------- ticks across plans, the land and the undos ----------

def test_ticks_come_from_the_old_plan_for_inherited_steps_and_from_this_one_after(project, conn, runner):
    old, step1 = _first_plan(conn, project)
    code, rev, w = _revise(conn)
    assert code == 0, w.said
    assert plan.tick_numbers(plan.ticks(conn, rev)) == {1: step1["n"]}
    assert plan.first_open(conn, rev)[0] == 2
    assert _land(conn, rev)[0] == 0
    assert plan.current(conn, "garden")["task_id"] == rev["task_id"]
    text = (project / "docs" / "PLAN.md").read_text()
    assert f"Plan #{rev['n']} (revises #{old['n']}) · 2026" in text.splitlines()[4] and "· 1 of 3 steps done" in text.splitlines()[4]
    assert f"- [x] **Step 1.**" in text and f"  - Done by #{step1['n']}" in text and "- [ ] **Step 2.**" in text
    handoff = (project / "HANDOFF.md").read_text()
    assert f"plan #{rev['n']} approved (revises #{old['n']})" in handoff
    assert _now(conn)["words"].startswith("Build step 2:")
    code, said, step2 = _route_step(conn, f"{rev['n']}:2", worker=CopyWorker(RESEARCH))
    assert code == 0, said
    assert plan.tick_numbers(plan.ticks(conn, log.get_task(conn, rev["task_id"]))) == {1: step1["n"], 2: step2["n"]}
    # a third plan revising the revision inherits both
    rev2_text = REV.replace("## Steps\n2. Add the Celsius to Fahrenheit conversion with its test, as a routed task.\n   team: route\n   why: the core rule\n   done when: test_convert.py's test_c_to_f passes, checking that 100 C gives 212 F\n3. Add c_to_k(c)", "## Steps\n3. Add c_to_k(c)").replace("step 2: its team is now route, a routed task is enough", "none")
    code, rev2, w = _revise(conn, worker=ReadWorker(rev2_text, rev2_text + "\n## Answered\nA2, B2: fine\n"))
    assert code == 0, w.said
    assert plan.record_of(rev2)["inherited"] == 2 and plan.record_of(rev2)["revises"] == rev["task_id"]
    assert plan.tick_numbers(plan.ticks(conn, rev2)) == {1: step1["n"], 2: step2["n"]}
    assert _land(conn, rev2)[0] == 0
    assert "· 2 of 3 steps done" in (project / "docs" / "PLAN.md").read_text()


def test_the_old_plans_undo_is_refused_and_the_revisions_undo_makes_it_current_again(project, conn, runner):
    old, step1 = _first_plan(conn, project)
    code, rev, w = _revise(conn)
    assert _land(conn, rev)[0] == 0
    code, said = _land(conn, log.get_task(conn, old["task_id"]), verb="undo")
    assert code == 2 and "no longer the project's current plan" in said
    code, said = _land(conn, log.get_task(conn, rev["task_id"]), verb="undo")
    assert code == 0, said
    assert plan.current(conn, "garden")["task_id"] == old["task_id"]
    assert _now(conn)["words"].startswith("Build step 2:")


# ---------- edits, marks, the estimate ----------

def _edit(conn, row, k, **change):
    args = Namespace(edit=row["task_id"], step=str(k), team=change.get("team"), text="text" in change, done_when=False,
                     covers=False, up=change.get("up", False), down=change.get("down", False), drop=change.get("drop", False),
                     task=[change["text"]] if "text" in change else [])
    out = receipt.Receipt()
    code = cli.cmd_plan_edit(args, conn=conn, config=CONFIG, roster=None, loaded=None, available=None, out=out)
    return code, out


def test_edits_touch_new_steps_only_and_the_marks_start_empty(project, conn, runner):
    old, step1 = _first_plan(conn, project)
    cli.cmd_plan_stop_here(f"{old['n']}:2", ["on"], conn=conn, out=receipt.Receipt())
    code, rev, w = _revise(conn)
    assert code == 0, w.said
    code, out = _edit(conn, rev, 1, text="Something else.")
    assert code == 2 and "step 1 is done; it stays" in out.message
    code, out = _edit(conn, rev, 2, up=True)
    assert code == 2 and "step 1 is done; it stays" in out.message  # a move over a done step
    code, out = _edit(conn, rev, 2, text="Add the conversion, routed.")
    assert code == 0, out.message
    record = plan.record_of(log.get_task(conn, rev["task_id"]))
    assert record["steps"][1]["text"] == "Add the conversion, routed." and record["steps"][0]["text"].startswith("Make the ske")
    assert auto.marks_of(record) == []
    code, out = _edit(conn, rev, 3, drop=True)
    assert code == 0 and len(plan.record_of(log.get_task(conn, rev["task_id"]))["steps"]) == 2


def test_the_estimate_counts_the_new_steps_only(project, conn, runner):
    old, step1 = _first_plan(conn, project)
    code, rev, w = _revise(conn)
    doc = plan.view(conn, rev, cli._plan_menu(cli.SimpleNamespace(presets=None, roster=None, available=None)))
    assert doc["estimate"]["calls"] == sum(s["calls"] for s in doc["steps"][1:])
    assert doc["estimate"]["jev_labels"] == 2


# ---------- the refusals at intake ----------

def test_an_open_task_still_refuses_and_a_kept_failed_change_of_a_step_does(project, conn, runner):
    old, step1 = _first_plan(conn, project)
    code, said, step2 = _route_step(conn, f"{old['n']}:2", worker=CopyWorker(SKELETON, SKELETON),
                                    chatgpt=Chat("FIX\n1. [must] wrong", "FIX\n1. [must] still wrong"))
    assert code == 5, said
    code, rev, w = _revise(conn)
    assert code == 2 and log.recent_tasks(conn)[0]["task_id"] == step2["task_id"]  # nothing written
    assert f"step 2's failed change (#{step2['n']}) is still kept" in w.said and "Land anyway" in w.said
    assert cli.cmd_land([step2["task_id"]], conn=conn, config=CONFIG, verb="discard", out=lambda l: None) == 0
    code, rev, w = _revise(conn)
    assert code == 0, w.said


# ---------- covers by text (decision 10) ----------

COVERED1 = NO_NEEDS.replace("   done when: test_cli.py's test_help passes under python3 -m unittest, checking that `python3 cli.py --help` exits 0\n",
                            "   done when: test_cli.py's test_help passes under python3 -m unittest, checking that `python3 cli.py --help` exits 0\n   covers: E1, E2\n") \
    .replace("   done when: test_convert.py's test_c_to_f passes, checking that 100 C gives 212 F\n",
             "   done when: test_convert.py's test_c_to_f passes, checking that 100 C gives 212 F\n   covers: E3\n")
REV_COVERED = REV.replace("   done when: test_convert.py's test_c_to_f passes, checking that 100 C gives 212 F\n",
                          "   done when: test_convert.py's test_c_to_f passes, checking that 100 C gives 212 F\n   covers: E2\n") \
    .replace("   done when: test_convert.py's test_c_to_k passes\n", "   done when: test_convert.py's test_c_to_k passes\n   covers: E4\n")
EDITED = ("# Converter\n\n## Examples\n\n- c_to_f(0) == 32\n- c_to_f(-40) == -40\n- f_to_c(212) == 100\n- c_to_k(0) == 273.15\n\n"
          "## Done when\n\n- both functions pass their tests\n")


def test_inherited_covers_follow_the_examples_text_and_a_gone_text_reads_example_changed(project, conn, runner):
    _commit_spec(project)
    old, step1 = _first_plan(conn, project, worker=ReadWorker(COVERED1, COVERED1 + "\n## Answered\nA2, B2: fine\n"))
    assert plan.record_of(old)["steps"][0]["covers"] == [{"label": "E1", "text": "c_to_f(100) == 212"},
                                                         {"label": "E2", "text": "f_to_c(212) == 100"}]
    _commit_spec(project, EDITED, "spec edited")  # E1's text gone; E2's text now at E3; a new E4
    code, rev, w = _revise(conn, worker=ReadWorker(REV_COVERED, REV_COVERED + "\n## Answered\nA2, B2: fine\n"))
    assert code == 0, w.said
    record = plan.record_of(rev)
    assert record["steps"][0]["covers"] == [{"label": None, "text": "c_to_f(100) == 212", "changed": True},
                                            {"label": "E3", "text": "f_to_c(212) == 100"}]  # inherited, matched by text
    assert record["steps"][1]["covers"] == [{"label": "E2", "text": "c_to_f(-40) == -40"}]  # new, by the label as read
    assert record["steps"][2]["covers"] == [{"label": "E4", "text": "c_to_k(0) == 273.15"}]
    assert plan.coverage(record) == {"covered": ["E2", "E3", "E4"], "missing": ["E1"], "words": "Covers E2–E4; not E1"}
    assert plan.covers_words(record["steps"][0]) == "example changed, E3"
    assert record["spec_hash"] == spec.digest(EDITED)
    assert _now(conn)["rung"] == 1  # the revision waits for approval
    assert _land(conn, rev)[0] == 0
    assert _now(conn)["rung"] != "spec_changed"  # the revision read the current spec


# ---------- sr show ----------

def test_show_prints_the_inherited_steps_marked_done(project, conn, runner):
    old, step1 = _first_plan(conn, project)
    code, rev, w = _revise(conn)
    lines = []
    cli.cmd_show(conn=conn, words=[rev["task_id"]], out=lines.append)
    text = "\n".join(lines)
    assert f"Plan: revises #{old['n']} · 1 step inherited" in text
    assert f"[x] 1. Make the skeleton" in text and f"done by #{step1['n']}" in text and "[ ] 2. Add the Celsius" in text
    assert "Changed: step 2: its team is now route" in text
