"""Build brief 33.2, C (decision 6): `covers:` per step when the project's spec has examples. The contract (a missing line, an
unknown label, `none`); the record's covers with each example's text; the coverage line on the card and in docs/PLAN.md;
the planner's, revise's and fix's prompts say the shape whole with the line; the attack prompt names an example no step
covers and the checker's line keeps it a [note]; the STEP block quotes the covered example's text and the step's check
line says it tests it; `sr plan --edit --covers`; the plan record's `spec_hash`. Real git in temp folders, fake agents;
every value here is fake."""
import json
from argparse import Namespace

import pytest

from router import __main__ as cli
from router import log, plan, projects, spec
from tests.test_filemode_flow import CopyWorker, conn, project, runner  # noqa: F401 (fixtures)
from tests.test_plan_approval import _land
from tests.test_plan_chain import A_LIST, B_LIST, ReadWorker, World
from tests.test_plan_contract import GOOD, MENU
from tests.test_plan_steps import SKELETON, _route_step
from tests.test_relay import CONFIG, Chat
from tests.test_spec332 import SPEC, _commit_spec

EXAMPLES = ["E1", "E2", "E3"]
COVERED = GOOD.replace("   done when: test_cli.py's test_help passes under python3 -m unittest, checking that `python3 cli.py --help` exits 0\n",
                       "   done when: test_cli.py's test_help passes under python3 -m unittest, checking that `python3 cli.py --help` exits 0\n"
                       "   covers: E1\n", 1)
COVERED = COVERED.replace("   done when: test_convert.py's test_c_to_f passes, checking that 100 C gives 212 F\n",
                          "   done when: test_convert.py's test_c_to_f passes, checking that 100 C gives 212 F\n   covers: E2, E3\n", 1)
REVISED = COVERED + "\n## Answered\nA2, B2: the steps are as small as they can be\n"


# ---------- the contract ----------

def test_with_examples_each_step_needs_a_covers_line_naming_labels_the_spec_has_or_none():
    parsed, missing = plan.read(COVERED, MENU, examples=EXAMPLES)
    assert missing == []
    assert [s["covers"] for s in parsed.steps] == [["E1"], ["E2", "E3"]]
    parsed, missing = plan.read(GOOD, MENU, examples=EXAMPLES)
    assert missing == ["Steps: step 1 has no `covers:` line (the spec's examples it covers, like `covers: E1, E3`, or `covers: none`)",
                       "Steps: step 2 has no `covers:` line (the spec's examples it covers, like `covers: E1, E3`, or `covers: none`)"]
    parsed, missing = plan.read(COVERED.replace("covers: E2, E3", "covers: E2, E9"), MENU, examples=EXAMPLES)
    assert missing == ["Steps: step 2's `covers:` names E9, which the spec's `## Examples` list doesn't have (it has E1, E2, E3)"]
    parsed, missing = plan.read(COVERED.replace("covers: E2, E3", "covers: none"), MENU, examples=EXAMPLES)
    assert missing == [] and parsed.steps[1]["covers"] == []
    parsed, missing = plan.read(COVERED.replace("covers: E2, E3", "covers: E2\n   covers: E3"), MENU, examples=EXAMPLES)
    assert missing == ["Steps: step 2 has 2 `covers:` lines; give one"]
    parsed, missing = plan.read(COVERED.replace("covers: E2, E3", "covers: the second one"), MENU, examples=EXAMPLES)
    assert missing[0].startswith("Steps: step 2's `covers:` names the second one, which the spec's")


def test_without_examples_covers_is_never_required_and_a_covers_line_is_harmless():
    parsed, missing = plan.read(GOOD, MENU)
    assert missing == [] and all(s["covers"] == [] for s in parsed.steps)
    parsed, missing = plan.read(COVERED, MENU)
    assert missing == [] and all(s["covers"] == [] for s in parsed.steps)  # read as text; never a stray line
    parsed, missing = plan.read(COVERED, MENU, examples=[])
    assert missing == []


def test_the_record_keeps_each_cover_with_its_examples_text_and_the_coverage():
    record = plan.new_record(MENU)
    record["spec"] = {"examples": spec.parse(SPEC).examples, "done_when": spec.parse(SPEC).done_when}
    parsed, _ = plan.read(COVERED, MENU, examples=EXAMPLES)
    found = plan.with_plan(record, parsed)
    assert found["steps"][0]["covers"] == [{"label": "E1", "text": "c_to_f(100) == 212"}]
    assert found["steps"][1]["covers"] == [{"label": "E2", "text": "f_to_c(212) == 100"}, {"label": "E3", "text": "c_to_f(-40) == -40"}]
    assert plan.coverage(found) == {"covered": ["E1", "E2", "E3"], "missing": [], "words": "Covers E1–E3"}
    parsed, _ = plan.read(COVERED.replace("covers: E2, E3", "covers: E3"), MENU, examples=EXAMPLES)
    assert plan.coverage(plan.with_plan(record, parsed))["words"] == "Covers E1, E3; not E2"
    parsed, _ = plan.read(COVERED.replace("covers: E1", "covers: none").replace("covers: E2, E3", "covers: none"), MENU,
                          examples=EXAMPLES)
    assert plan.coverage(plan.with_plan(record, parsed))["words"] == "Covers none of E1–E3"
    assert plan.coverage(plan.with_plan(plan.new_record(MENU), parsed)) is None  # no examples: no coverage line


def test_coverage_words_compress_runs_of_three_or_more():
    assert plan.coverage_words(["E1", "E2", "E3", "E4"], ["E5", "E6"]) == "Covers E1–E4; not E5, E6"
    assert plan.coverage_words(["E1", "E2"], ["E3", "E4", "E5"]) == "Covers E1, E2; not E3–E5"
    assert plan.coverage_words(["E1", "E3", "E4", "E5", "E7"], []) == "Covers E1, E3–E5, E7"


def test_docs_plan_md_carries_the_coverage_line_and_each_steps_covers():
    record = plan.new_record(MENU)
    record["spec"] = {"examples": spec.parse(SPEC).examples, "done_when": []}
    parsed, _ = plan.read(COVERED.replace("covers: E2, E3", "covers: E3"), MENU, examples=EXAMPLES)
    text = plan.render(plan.with_plan(record, parsed), n=7, date="2026-10-30")
    lines = text.splitlines()
    assert lines[4] == "Plan #7 · 2026-10-30 · 0 of 2 steps done" and lines[5] == "Covers E1, E3; not E2"
    assert "  - Covers: E1" in text and "  - Covers: E3" in text
    plain = plan.render(plan.with_plan(plan.new_record(MENU), plan.read(GOOD, MENU)[0]), n=7, date="2026-10-30")
    assert "Covers" not in plain  # no examples: docs/PLAN.md as before


# ---------- the prompts (the shape whole on the planner, the revise, the fix; the attack and check words) ----------

def test_the_prompts_say_the_covers_line_and_the_attack_and_check_name_an_uncovered_example(project, conn, runner):
    _commit_spec(project)
    partial = COVERED.replace("covers: E2, E3", "covers: E2")  # E3 uncovered
    w = World(worker=ReadWorker(partial, partial + "\n## Answered\nA2, B2: as small as they can be\n", partial + "\n## Answered\nA1: fixed\n"),
              chat=Chat(A_LIST, "FIX\n1. [must] Step 2's done-when names no file.", "PASS"))
    code, row = w.plan(conn)
    assert code == 0, w.said
    planner, revise, fix = [c["prompt"] for c in w.worker.calls]
    attack, check, recheck = w.chat.prompts
    for prompt in (planner, revise, fix):
        assert plan.COVERS_FORM in prompt, prompt[:400]
        assert plan.EXAMPLES_RULE in prompt
    assert plan.steps_form(True) in planner and plan.SHAPE not in planner  # the shape whole, with the line
    assert plan.uncovered_line(["E3"], [{"label": "E3", "text": "c_to_f(-40) == -40"}]) in attack
    assert "E3" in w.cursor.prompts[0] and plan.UNCOVERED_LEAD in w.cursor.prompts[0]
    assert plan.UNCOVERED_CHECK in check and "E3" in check and plan.UNCOVERED_CHECK in recheck
    record = plan.record_of(log.get_task(conn, row["task_id"]))
    assert record["spec_hash"] == spec.digest(SPEC) and [e["label"] for e in record["spec"]["examples"]] == EXAMPLES
    assert plan.coverage(record)["words"] == "Covers E1, E2; not E3"
    doc = plan.view(conn, log.get_task(conn, row["task_id"]))
    assert doc["coverage"] == {"covered": ["E1", "E2"], "missing": ["E3"], "words": "Covers E1, E2; not E3"}
    assert doc["steps"][1]["covers"] == [{"label": "E2", "text": "f_to_c(212) == 100"}] and doc["spec_hash"] == spec.digest(SPEC)


def test_without_a_spec_every_prompt_is_as_before(project, conn, runner):
    w = World()
    code, row = w.plan(conn)
    assert code == 0, w.said
    for prompt in [c["prompt"] for c in w.worker.calls] + w.chat.prompts + w.cursor.prompts:
        assert "covers:" not in prompt and plan.UNCOVERED_LEAD not in prompt and plan.UNCOVERED_CHECK not in prompt
    record = plan.record_of(log.get_task(conn, row["task_id"]))
    assert record["spec_hash"] is None and record["spec"] is None
    assert plan.view(conn, log.get_task(conn, row["task_id"]))["coverage"] is None


def test_a_plan_missing_its_covers_line_is_reasked_with_the_line_named(project, conn, runner):
    _commit_spec(project)
    w = World(worker=ReadWorker(GOOD, COVERED, REVISED))
    code, row = w.plan(conn)
    assert code == 0, w.said
    calls = log.calls_for(conn, row["task_id"])
    assert calls[1]["kind"] == "reask"
    reask = w.worker.calls[1]["prompt"]
    assert "has no `covers:` line" in reask and plan.steps_form(True) in reask


# ---------- the STEP block and the step's check line ----------

def test_the_step_block_quotes_the_covered_example_and_the_check_line_says_it_tests_it(project, conn, runner):
    _commit_spec(project)
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    w = World(worker=ReadWorker(COVERED, REVISED))
    code, row = w.plan(conn)
    assert code == 0, w.said
    assert _land(conn, log.get_task(conn, row["task_id"]))[0] == 0
    found = log.get_task(conn, row["task_id"])
    worker, chat = CopyWorker(SKELETON), Chat("PASS")
    code, said, step = _route_step(conn, f"{found['n']}:1", worker=worker, chatgpt=chat)
    assert code == 0, said
    do, check = worker.calls[0]["prompt"], chat.prompts[0]
    quoted = "It covers SPEC.md's E1: c_to_f(100) == 212."
    assert quoted in do and quoted in check
    assert plan.STEP_CHECK_LINE_COVERS in check and plan.STEP_CHECK_LINE not in check
    assert plan.STEP_CHECK_LINE_COVERS not in do


def test_a_step_covering_none_has_the_block_as_before(project, conn, runner):
    _commit_spec(project)
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    none = COVERED.replace("covers: E1", "covers: none")
    w = World(worker=ReadWorker(none, none + "\n## Answered\nA2, B2: as small as they can be\n"))
    code, row = w.plan(conn)
    assert code == 0, w.said
    assert _land(conn, log.get_task(conn, row["task_id"]))[0] == 0
    worker, chat = CopyWorker(SKELETON), Chat("PASS")
    code, said, step = _route_step(conn, f"{log.get_task(conn, row['task_id'])['n']}:1", worker=worker, chatgpt=chat)
    assert "It covers SPEC.md" not in worker.calls[0]["prompt"] and plan.STEP_CHECK_LINE in chat.prompts[0]


# ---------- --covers ----------

def _edit_covers(conn, row, step, words):
    args = Namespace(edit=row["task_id"], step=str(step), team=None, text=False, done_when=False, covers=True, up=False,
                     down=False, drop=False, task=[words])
    out = cli.receipt.Receipt()
    code = cli.cmd_plan_edit(args, conn=conn, config=CONFIG, roster=None, loaded=None, available=None, out=out)
    return code, out


def test_covers_joins_the_edits_checked_by_the_same_rule(project, conn, runner):
    _commit_spec(project)
    w = World(worker=ReadWorker(COVERED, REVISED))
    code, row = w.plan(conn)
    assert code == 0, w.said
    row = log.get_task(conn, row["task_id"])
    code, out = _edit_covers(conn, row, 1, "E1, E2")
    assert code == 0, out.message
    record = plan.record_of(log.get_task(conn, row["task_id"]))
    assert record["steps"][0]["covers"] == [{"label": "E1", "text": "c_to_f(100) == 212"}, {"label": "E2", "text": "f_to_c(212) == 100"}]
    assert record["edits"][-1]["change"] == "covers" and record["edits"][-1]["to"] == ["E1", "E2"]
    code, out = _edit_covers(conn, row, 1, "E9")
    assert code == 2 and "E9" in out.message and "doesn't have" in out.message
    code, out = _edit_covers(conn, row, 2, "none")
    assert code == 0 and plan.record_of(log.get_task(conn, row["task_id"]))["steps"][1]["covers"] == []
    assert plan.coverage(plan.record_of(log.get_task(conn, row["task_id"])))["words"] == "Covers E1, E2; not E3"
    from router import page_commands
    found = page_commands.build({"action": "plan_edit", "task_id": row["task_id"], "step": 1, "change": "covers", "value": "E1, E3"}, {})
    assert found.args[-3:] == ("--covers", "--", "E1, E3")


def test_covers_on_a_plan_without_examples_is_refused(project, conn, runner):
    w = World()
    code, row = w.plan(conn)
    code, out = _edit_covers(conn, log.get_task(conn, row["task_id"]), 1, "E1")
    assert code == 2 and "no `## Examples` list" in out.message


def test_the_snapshot_without_a_spec_holds(project, conn, runner, tmp_path):
    from tests import plan_snapshot
    from pathlib import Path
    assert plan_snapshot.snapshot(conn, tmp_path) == json.loads((Path("tests") / "fixtures" / "plan_prompts_33_1.json").read_text())
