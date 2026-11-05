"""Build brief 33.1, D1 (the live check's step 1, 30 Oct): the revise put a list of tests under two steps' `done when:`
and a need line without its step; both the revise and its re-ask missed the shape, and the plan ended at stage 4. The
reader glued every line under a step onto the step's text ("step 3 has 870 characters") and called a `decision:` line
without `(step <k>)` "none of key:, account:, decision: or test command:"; the revise, fix and re-ask prompts never said
the shape's lines (one line each). Now a line after a step's labeled lines is named as such and never becomes part of
the task the step sends; a need line that starts with its kind is told its form; and every plan prompt that asks for the
plan back says the shape whole. Every value here is fake."""
import pytest

from router import log, plan
from tests.test_filemode_flow import conn, project, runner  # noqa: F401 (fixtures)
from tests.test_plan_chain import A_LIST, REVISED, ReadWorker, World
from tests.test_plan_contract import GOOD, MENU
from tests.test_relay import Chat

LISTED = GOOD.replace(
    "   done when: test_convert.py's test_c_to_f passes, checking that 100 C gives 212 F\n",
    "   done when: all of these in test_convert.py pass:\n"
    "   - `test_c_to_f`: 100 C gives 212 F\n"
    "   - `test_f_to_c`: 212 F gives 100 C\n")


# ---------- the reader ----------

def test_lines_after_a_steps_labeled_lines_are_named_never_glued_onto_its_text():
    parsed, missing = plan.read(LISTED, MENU)
    stray = [m for m in missing if m.startswith("Steps: step 2 has 2 more lines after its team:, why: and done when:")]
    assert len(stray) == 1, missing
    assert "'- `test_c_to_f`: 100 C gives 212 F'" in stray[0] and "separated by semicolons" in stray[0]
    assert not any("characters; each must be under 400" in m for m in missing)
    assert parsed.steps[1]["text"] == "Add the Celsius to Fahrenheit conversion with its test."


def test_a_steps_text_may_still_wrap_before_its_labeled_lines():
    wrapped = GOOD.replace("2. Add the Celsius to Fahrenheit conversion with its test.\n",
                           "2. Add the Celsius to Fahrenheit\n   conversion with its test.\n")
    parsed, missing = plan.read(wrapped, MENU)
    assert missing == [] and parsed.steps[1]["text"] == "Add the Celsius to Fahrenheit conversion with its test."


@pytest.mark.parametrize("line, form", [
    ("- decision: Celsius or Fahrenheit by default? Default assumed: Celsius.", "decision: <the question> (step <k>)"),
    ("- account: a weather service account", "account: <what> (step <k>)"),
    ("- key: WEATHER_KEY: to fetch today's temperature", "key: <NAME> (step <k>): <what it is for>"),
])
def test_a_need_line_that_starts_with_its_kind_is_told_its_form(line, form):
    text = GOOD.split("## Needs from you")[0] + f"## Needs from you\n{line}\n"
    missing = plan.contract(text, MENU)
    kind = form.split(":")[0]
    assert missing == [f"Needs from you: a {kind}: line reads `{form}`; this one doesn't: {line[2:][:80]!r}"], missing


def test_a_line_of_no_kind_is_still_none_of_them():
    text = GOOD.split("## Needs from you")[0] + "## Needs from you\nRisk: step 2's rounding may need a tolerance.\n"
    assert any("this line is none of key:, account:, decision: or test command:" in m
               for m in plan.contract(text, MENU))


def test_the_revision_contract_reads_the_same_way():
    missing = plan.revision_contract(LISTED + "\n## Answered\nnone\n", None, MENU)
    assert any(m.startswith("Steps: step 2 has 2 more lines after") for m in missing), missing


# ---------- the shape in every prompt that asks for the plan back ----------

def test_the_shape_says_one_line_each_and_the_plans_form_is_the_shape_without_its_lead():
    assert plan.SHAPE.endswith(plan.ONE_LINE) and plan.SHAPE.startswith("Return exactly two sections and nothing else: ")
    assert plan.PLAN_FORM == f"The plan's shape: {plan.STEPS_FORM} {plan.ONE_LINE}"
    assert "separated by semicolons" in plan.ONE_LINE and "never as a list under it" in plan.ONE_LINE


def test_the_revise_and_its_re_ask_say_the_plans_form(project, conn, runner):
    w = World(worker=ReadWorker(GOOD, LISTED + "\n## Answered\nnone\n", REVISED))
    code, row = w.plan(conn)
    assert code == 0, w.said
    calls = log.calls_for(conn, row["task_id"])
    assert [(c["kind"], c["stage"]) for c in calls][3:5] == [("stage", 4), ("reask", 4)]
    revise, reask = w.worker.calls[1]["prompt"], w.worker.calls[2]["prompt"]
    assert plan.PLAN_FORM in revise and plan.PLAN_FORM in reask
    assert "Steps: step 2 has 2 more lines after its team:, why: and done when: lines" in reask
    assert plan.ONE_STEP_LINE not in revise + reask


def test_the_fix_round_says_the_plans_form(project, conn, runner):
    w = World(worker=ReadWorker(GOOD, REVISED, REVISED), chat=Chat(A_LIST, "FIX\n1. [must] step 2 names no test file",
                                                                 "PASS\n1. fixed"))
    code, row = w.plan(conn)
    assert code == 0, w.said
    assert plan.PLAN_FORM in w.worker.calls[2]["prompt"] and plan.FIX_LINE in w.worker.calls[2]["prompt"]


def test_the_planners_re_ask_says_the_whole_shape(project, conn, runner):
    w = World(worker=ReadWorker(LISTED, GOOD, REVISED))
    code, row = w.plan(conn)
    assert code == 0, w.said
    first, reask = w.worker.calls[0]["prompt"], w.worker.calls[1]["prompt"]
    assert plan.SHAPE in first and plan.SHAPE in reask and plan.ONE_STEP_LINE in reask
