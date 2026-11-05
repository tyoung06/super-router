"""Build brief 33.4 (§4 Prompts): the new prompts get a snapshot: the Questions words, the answers block on every later call and
the suggest prompt, in tests/fixtures/plan_prompts_33_4.json, byte for byte, recorded on this brief's code. Fake agents."""
import json
from pathlib import Path

from router import plan, suggest
from tests import plan_snapshot
from tests.test_filemode_flow import conn, project, runner  # noqa: F401 (fixtures)

SNAPSHOT = Path(__file__).parent / "fixtures" / "plan_prompts_33_4.json"


def test_the_new_prompts_are_their_snapshot_byte_for_byte(project, conn, runner, tmp_path):
    assert plan_snapshot.snapshot_334(conn, tmp_path) == json.loads(SNAPSHOT.read_text())


def test_what_the_33_4_snapshot_holds():
    found = json.loads(SNAPSHOT.read_text())
    assert found["rows"] == [["questions", 1, "plan", "claude", "done"], ["stage", 1, "plan", "claude", "done"],
                             ["stage", 2, "attack", "chatgpt", "done"], ["stage", 3, "attack", "cursor", "done"],
                             ["stage", 4, "revise", "claude", "done"], ["check", None, None, "chatgpt", "done"]]
    asks, answered, revise = found["plan"]["claude"]
    assert plan.QUESTIONS_LINE in asks and plan.ANSWERS_LABEL not in asks
    assert plan.ANSWERED_LINE in answered and plan.QUESTIONS_LINE not in answered
    for prompt in [answered, revise, *found["plan"]["chatgpt"], *found["plan"]["cursor"]]:
        assert plan.ANSWERS_LABEL in prompt
    assert suggest.SHAPE in found["suggest"][0] and suggest.IDEAS_LABEL in found["suggest"][0]
