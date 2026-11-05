"""Build brief 33.1, P and A (decisions 4, 6, 8, 11 and 15): the plan's contract, read by code; the record and the owner's
edits; docs/PLAN.md as the router renders it. Pure: no agent, no folder. Every value here is fake."""
import pytest

from router import plan

MENU = ["route", "research-build", "collab", "redteam"]
GOOD = """## Steps
1. Make the skeleton: a cli.py that prints its help, and test_cli.py with one test that runs it.
   team: route
   why: the smallest thing that runs, so every later step has a test to stand on
   done when: test_cli.py's test_help passes under python3 -m unittest, checking that `python3 cli.py --help` exits 0
2. Add the Celsius to Fahrenheit conversion with its test.
   team: redteam
   why: the core rule, worth an attack before it lands
   done when: test_convert.py's test_c_to_f passes, checking that 100 C gives 212 F

## Needs from you
- key: WEATHER_KEY (step 2): to fetch today's temperature
- account: a weather service account (step 2)
- decision: Celsius or Fahrenheit by default? (step 2)
- test command: python3 -m unittest
"""
ONE = """## One step
A one-line docstring is one small change, not a plan.
task: Add a one-line docstring to hello.py's greet function.
team: route
"""


def test_a_good_plan_meets_the_contract_and_reads_whole():
    parsed, missing = plan.read(GOOD, MENU)
    assert missing == []
    assert [s["team"] for s in parsed.steps] == ["route", "redteam"]
    assert parsed.steps[0]["done_when"].startswith("test_cli.py's test_help passes")
    assert parsed.needs == [
        {"kind": "key", "name": "WEATHER_KEY", "what": "to fetch today's temperature", "step": 2},
        {"kind": "account", "name": None, "what": "a weather service account", "step": 2},
        {"kind": "decision", "name": None, "what": "Celsius or Fahrenheit by default?", "step": 2},
        {"kind": "test_command", "name": None, "what": "python3 -m unittest", "step": None}]


def test_needs_may_say_none():
    text = GOOD.split("## Needs from you")[0] + "## Needs from you\nnone\n"
    assert plan.read(text, MENU)[1] == []


def test_a_one_step_answer_is_read_on_stage_1_only():
    assert plan.one_step_of(ONE, MENU) == {"why": "A one-line docstring is one small change, not a plan.",
                                          "task": "Add a one-line docstring to hello.py's greet function.",
                                          "team": "route"}
    assert plan.contract(ONE, MENU) == []
    assert plan.read(ONE, MENU, one_step=False)[1] == [
        "One step: not allowed now; return the whole plan (`## Steps` and `## Needs from you`)"]
    assert plan.one_step_of(GOOD, MENU) is None


@pytest.mark.parametrize("text, words", [
    (ONE.replace("team: route", "team: vote"), "One step's team 'vote' is not on the TEAMS list"),
    (ONE.replace("task: ", "tasks are: "), "One step has no `task:` line"),
    (ONE.replace("A one-line docstring is one small change, not a plan.\n", ""), "One step: need one line saying why"),
    (GOOD + "\n" + ONE, "Return either the plan"),
])
def test_a_bad_one_step_misses_the_contract(text, words):
    assert any(words in m for m in plan.contract(text, MENU)), plan.contract(text, MENU)


def _steps(n):
    body = "".join(f"{k}. Step {k} of the work.\n   team: route\n   why: it is next\n   done when: test_{k} passes\n"
                   for k in range(1, n + 1))
    return f"## Steps\n{body}\n## Needs from you\nnone\n"


@pytest.mark.parametrize("text, words", [
    (_steps(0), "Steps: need 1 to 12 numbered steps, found 0"),
    (_steps(13), "Steps: need 1 to 12 numbered steps, found 13"),
    (GOOD.replace("team: redteam", "team: vote"), "Steps: step 2's team 'vote' is not on the TEAMS list"),
    (GOOD.replace("   team: redteam\n", ""), "Steps: step 2 has no `team:` line"),
    (GOOD.replace("   why: the core rule, worth an attack before it lands\n", ""), "Steps: step 2 has no `why:` line"),
    (GOOD.replace("   done when: test_convert.py's test_c_to_f passes, checking that 100 C gives 212 F\n", ""),
     "Steps: step 2 has no `done when:` line"),
    (GOOD.replace("Add the Celsius", "@claude Add the Celsius"), "Steps: step 2 starts with @ or /"),
    (GOOD.replace("Add the Celsius", "Add the Celsius " + "x" * 400), "Steps: step 2 has"),
    (GOOD.replace("why: the core rule", "why: " + "y" * 200), "Steps: step 2's `why:` has"),
    (GOOD.replace("done when: test_convert.py's", "done when: " + "d" * 300), "Steps: step 2's `done when:` has"),
    (GOOD.replace("WEATHER_KEY", "weather_key"), "the key name 'weather_key' isn't upper case letters"),
    (GOOD.replace("WEATHER_KEY", "2WEATHER"), "the key name '2WEATHER' isn't upper case letters"),
    (GOOD.replace("(step 2): to fetch", "(step 7): to fetch"), "names step 7; the plan has 2"),
    (GOOD + "- test command: pytest -q\n", "at most one test command, found 2"),
    (GOOD.replace("- account: a weather service account (step 2)", "- a weather service account"),
     "this line is none of key:, account:, decision: or test command:"),
    (GOOD.split("## Needs from you")[0], "Needs from you: the ## Needs from you heading is missing"),
    (GOOD.split("## Needs from you")[0] + "## Needs from you\nnone\n- key: A (step 1): x\n", "none goes alone"),
])
def test_each_way_a_plan_misses(text, words):
    missing = plan.contract(text, MENU)
    assert any(words in m for m in missing), missing


def test_without_a_menu_only_the_team_line_is_checked():
    assert plan.contract(GOOD.replace("team: redteam", "team: vote")) == []


def test_the_revision_keeps_the_shape_and_answers_by_label():
    from router import relay
    text_a = "## Attacks\n1. [high] step 2 names no test\n2. [low] a\n3. [low] b\n\n## Strongest\nno test"
    lists = (relay.AttackList(2, "chatgpt", "A", text_a, relay.labeled(text_a, "A")),)
    text = GOOD + "\n## Answered\nA1: step 2's done-when names test_c_to_f\n"
    assert plan.revision_contract(text, lists, MENU) == []
    assert any("not allowed now" in m for m in plan.revision_contract(ONE + "\n## Answered\nnone\n", lists, MENU))
    assert any("Answered" in m for m in plan.revision_contract(GOOD, lists, MENU))
    assert any("attack B1 is not in the attack lists" in m
               for m in plan.revision_contract(GOOD + "\n## Answered\nB1: no\n", lists, MENU))


def test_the_next_section_is_never_a_contract_miss():
    assert plan.contract(GOOD + "\n## Next\n- something\n", MENU) == []


# ---------- the record and the edits (decision 11) ----------

def _record():
    return plan.with_plan(plan.new_record(MENU), plan.read(GOOD, MENU)[0])


def test_the_record_keeps_the_planners_version_beside_the_one_that_stands():
    record, why = plan.edit(_record(), 1, "text", "Make the skeleton cli.py with test_cli.py.", MENU)
    assert why is None
    assert record["steps"][0]["text"] == "Make the skeleton cli.py with test_cli.py."
    assert record["planner"]["steps"][0]["text"].startswith("Make the skeleton: a cli.py")
    assert record["edits"][0]["change"] == "text" and record["edits"][0]["step"] == 1


@pytest.mark.parametrize("change, value, words", [
    ("text", "", "step 1's text is empty"),
    ("text", "/route it", "starts with @ or /"),
    ("text", "two\nlines", "goes on one line"),
    ("done_when", "d" * 300, "step 1's done-when has 300 characters"),
    ("team", "vote", "vote is not a team a step can take now"),
    ("up", None, "step 1 is already first"),
])
def test_an_edit_passes_the_contracts_rules(change, value, words):
    record, why = plan.edit(_record(), 1, change, value, MENU)
    assert record is None and words in why


def test_a_move_renumbers_the_needs():
    record, why = plan.edit(_record(), 2, "up", None, MENU)
    assert why is None
    assert [s["team"] for s in record["steps"]] == ["redteam", "route"]
    assert [n["step"] for n in record["needs"]] == [1, 1, 1, None]


def test_a_drop_keeps_a_need_whose_step_went_with_no_step():
    record, why = plan.edit(_record(), 2, "drop", None, MENU)
    assert why is None and len(record["steps"]) == 1
    assert [n["step"] for n in record["needs"]] == [None, None, None, None]
    assert plan.edit(record, 1, "drop", None, MENU)[1] == "a plan keeps at least one step; Reject drops the whole plan"


# ---------- docs/PLAN.md (decision 15) ----------

def test_docs_plan_md_is_a_checklist_with_its_ticks_and_needs():
    text = plan.render(_record(), n=12, date="2026-10-29", ticks={1: 14})
    assert text.startswith("# Plan\n\n" + plan.WRITER_LINE + "\n\nPlan #12 · 2026-10-29 · 1 of 2 steps done\n")
    assert "- [x] **Step 1.** Make the skeleton" in text and "  - Done by #14\n" in text
    assert "- [ ] **Step 2.** Add the Celsius" in text
    assert "  - Team: redteam\n  - Done when: test_convert.py's test_c_to_f passes" in text
    assert "- Key `WEATHER_KEY` (step 2): to fetch today's temperature" in text
    assert "- Test command: `python3 -m unittest`" in text
    assert plan.render(_record(), n=12, date="2026-10-29", ticks={1: 14}) == text  # the same bytes every time


def test_the_file_list_is_sorted_cut_and_key_scanned():
    shaped = "AK" + "IA" + "ABCDEFGHIJKLMNOP"  # a key-shaped name, built from pieces at run time (never spelled whole)
    entries = [("b.py", 10), ("a.py", 1), (f"keys/{shaped}.txt", 5)]
    lines = plan.file_lines(entries, secrets=())
    assert lines[:2] == ["a.py (1 byte)", "b.py (10 bytes)"]
    assert lines[-1] == "(1 path left out: it looks like a key)"
    many = [(f"f{k:04}.py", k) for k in range(plan.FILES_LISTED + 3)]
    assert plan.file_lines(many)[-1] == f"(the list is cut here: {plan.FILES_LISTED} of 503 files shown)"
    assert plan.file_lines([("notes-SECRETVALUE1.txt", 3)], secrets=["SECRETVALUE1"]) == ["notes-[REDACTED].txt (3 bytes)"]
