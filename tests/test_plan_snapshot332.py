"""Build brief 33.2 (§4 Prompts): the new prompts' snapshot. One run on a project with SPEC.md (tests/plan_snapshot.py's
`snapshot_332`: a plan with covers, its fix round, step 1 with the STEP block quoting its example, a revision from an idea
with `PLAN SO FAR`, `## Changed` and the keep-unless words, and the Draft chip's `--no-files` task) gives
tests/fixtures/plan_prompts_33_2.json byte for byte, recorded on this brief's code. 33.1's snapshot holds as it is
(tests/test_plan_snapshot.py: a project without a spec). Real git in temp folders, fake agents; every value here is fake."""
import json
from pathlib import Path

from router import context, plan, projspec, spec
from tests import plan_snapshot
from tests.test_filemode_flow import conn, project, runner  # noqa: F401 (fixtures)

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOT = FIXTURES / "plan_prompts_33_2.json"


def test_the_new_prompts_are_their_snapshot_byte_for_byte(project, conn, runner, tmp_path):
    assert plan_snapshot.snapshot_332(conn, tmp_path, project) == json.loads(SNAPSHOT.read_text())


def test_what_the_33_2_snapshot_holds():
    found = json.loads(SNAPSHOT.read_text())
    assert found["rows"]["plan"] == [
        ["stage", 1, "plan", "claude", "done"], ["stage", 2, "attack", "chatgpt", "done"],
        ["stage", 3, "attack", "cursor", "done"], ["stage", 4, "revise", "claude", "done"],
        ["check", None, None, "chatgpt", "done"], ["fix", None, None, "claude", "done"],
        ["recheck", None, None, "chatgpt", "done"]]
    assert found["rows"]["revision"] == found["rows"]["plan"][:5]
    assert found["rows"]["step"] == [["do", None, None, "claude", "done"], ["check", None, None, "chatgpt", "done"]]
    assert found["rows"]["draft"] == found["rows"]["step"]
    every = (found["plan"]["claude"] + found["plan"]["chatgpt"] + found["plan"]["cursor"] + found["step"]["claude"]
             + found["step"]["chatgpt"] + found["revision"]["claude"] + found["revision"]["chatgpt"] + found["revision"]["cursor"]
             + found["draft"]["claude"] + found["draft"]["chatgpt"])
    assert all(spec.BLOCK_LINE in p and "===== SPEC.md (garden) =====" in p for p in every)  # the spec block on every call
    planner, revise, fix = found["plan"]["claude"]
    attack, check, recheck = found["plan"]["chatgpt"]
    for prompt in (planner, revise, fix):
        assert plan.COVERS_FORM in prompt and plan.EXAMPLES_RULE in prompt
        assert spec.JUDGE_LINE not in prompt
    for prompt in (attack, check, recheck, found["plan"]["cursor"][0]):
        assert spec.JUDGE_LINE in prompt
    doer, step_check = found["step"]["claude"][0], found["step"]["chatgpt"][0]
    assert "It covers SPEC.md's E1: c_to_f(100) == 212." in doer and plan.STEP_CHECK_LINE_COVERS in step_check
    assert spec.BUILD_CLAUSE in doer  # the build clause rides on the doer's paragraph
    rev_planner, rev_revise = found["revision"]["claude"]
    for prompt in (rev_planner, rev_revise) + tuple(found["revision"]["chatgpt"]) + tuple(found["revision"]["cursor"]):
        assert plan.SO_FAR_LABEL in prompt and "- [x] **Step 1.**" in prompt
        assert prompt.index("===== SPEC.md (garden) =====") < prompt.index(plan.SO_FAR_LABEL)
    assert plan.CHANGED_FORM in rev_planner and plan.KEEP_UNLESS_LINE in rev_planner and plan.KEEP_UNLESS_LINE in rev_revise
    assert plan.revision_line(1) in rev_planner and plan.ONE_STEP_LINE not in rev_planner
    draft_do, draft_check = found["draft"]["claude"][0], found["draft"]["chatgpt"][0]
    assert draft_do.startswith(projspec.DRAFT_TEXT) or projspec.DRAFT_TEXT in draft_do
    assert spec.BUILD_CLAUSE not in draft_do and "Make the change by editing files there" not in draft_do  # text only
    assert context.HANDOFF_LINE in draft_do
