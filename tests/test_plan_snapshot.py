"""Build brief 33.1 (Tests, Prompts): the new prompts get snapshots. A plan's run (plan, two attacks, revise, check, fix
round, re-check) and its step 1 routed with `--step` give tests/fixtures/plan_prompts_33_1.json byte for byte, recorded
on this brief's code by tests/plan_snapshot.py. Every prompt this brief doesn't change holds by the snapshots already in
the suite (redteam, relay, the skill table's). Real git in temp folders, fake agents; every value here is fake."""
import json
from pathlib import Path

from router import checking, context, plan
from tests import plan_snapshot
from tests.test_filemode_flow import conn, project, runner  # noqa: F401 (fixtures)

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOT = FIXTURES / "plan_prompts_33_1.json"


def test_the_plans_prompts_are_their_snapshot_byte_for_byte(project, conn, runner, tmp_path):
    assert plan_snapshot.snapshot(conn, tmp_path) == json.loads(SNAPSHOT.read_text())


def test_what_the_plan_snapshot_holds():
    found = json.loads(SNAPSHOT.read_text())
    assert found["rows"]["plan"] == [
        ["stage", 1, "plan", "claude", "done"], ["stage", 2, "attack", "chatgpt", "done"],
        ["stage", 3, "attack", "cursor", "done"], ["stage", 4, "revise", "claude", "done"],
        ["check", None, None, "chatgpt", "done"], ["fix", None, None, "claude", "done"],
        ["recheck", None, None, "chatgpt", "done"]]
    assert found["rows"]["step"] == [["do", None, None, "claude", "done"], ["check", None, None, "chatgpt", "done"]]
    planner, revise, fix = found["plan"]["claude"]
    attack, check, recheck = found["plan"]["chatgpt"]
    for line in (plan.INSTRUCTIONS.format(name="garden"), plan.SHAPE, plan.ONE_STEP_LINE, plan.MENU_HEAD):
        assert line in planner
    assert plan.REVISE_LEAD in revise and plan.FIX_LINE in fix and plan.ONE_STEP_LINE not in revise + fix
    assert plan.PLAN_FORM in revise and plan.PLAN_FORM in fix  # D1: the shape's lines, one line each, said again
    for prompt in (attack, found["plan"]["cursor"][0]):
        assert plan.attack_line(True) in prompt
    assert plan.check_line(True) in check and plan.check_line(True) in recheck
    every = found["plan"]["claude"] + found["plan"]["chatgpt"] + found["plan"]["cursor"]
    assert all("===== PROJECT FILES =====" in p for p in every)
    assert all(context.HANDOFF_LINE not in p and checking.NEXT_LINE not in p for p in every)
    doer, step_check = found["step"]["claude"][0], found["step"]["chatgpt"][0]
    block = plan.STEP_BLOCK.format(k=1, n=1, done_when="test_cli.py's test_help passes under python3 -m unittest, "
                                                       "checking that `python3 cli.py --help` exits 0")
    assert block in doer and block in step_check and plan.STEP_CHECK_LINE in step_check
    assert plan.STEP_CHECK_LINE not in doer
