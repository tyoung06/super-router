"""Rule 11: the answer key is fixed before anything changes. tests/fixtures/skill_table_v3_1.json is
config/skill_table.json exactly as shipped on 2026-10-13, before version 3.2 (brief 25: the owner's first name in its
notes reads "the owner"; Jev never sees a note). Every option Jev saw then, and the
questions, must be the same from the shipped table whatever its version, so Jev's scoring (11 of 30 real tasks)
continues uninterrupted. Version 3.4 (2026-10-20; rules v2.28, Jev: "A 12th skill, recall") adds one option after
round 3 of the label test (its text sharpened for round 4): the eleven old options are still 3.1's byte for byte, and the twelfth, recall, goes as
{"what", "not_for"} the way the criteria note says. Thirteen items shuffle differently from twelve, so the order
for a given seed is no longer 3.1's; the options themselves are."""
import json
from pathlib import Path
from types import SimpleNamespace

from router import jev
from router.roster import SKILLS_PATH
from tests.helpers import shipped_roster

V3_1 = json.loads((Path(__file__).parent / "fixtures" / "skill_table_v3_1.json").read_text())
SHIPPED = json.loads(SKILLS_PATH.read_text())
SEEDS = [f"sr-20261013-2200{i:02d}-abcd" for i in range(8)]
RECALL_OPTION = {
    "what": "Answer a question about earlier tasks in the same project or chat from what the router remembers: what was done, decided, produced or said, or what was planned next. The answer reports; it makes nothing new.",
    "not_for": "Any task that produces something, even from an earlier result or 'from memory': writing, rewriting, shortening or redoing a text, planning, code, or anything needing new facts from the web or social media.",
}


def test_the_answer_key_is_version_3_1_as_shipped_on_2026_10_13():
    assert V3_1["version"] == 3.1 and V3_1["updated"] == "2026-10-06" and len(V3_1["skills"]) == 11
    assert V3_1["labeler"]["jev_model"] == "jev-1.13.0"


def test_the_eleven_old_options_from_the_shipped_table_are_the_v3_1_payload_byte_for_byte():
    for seed in SEEDS:
        shipped, key = jev.build_criteria(SHIPPED, seed), jev.build_criteria(V3_1, seed)
        old = {k: v for k, v in shipped.items() if k != "recall"}
        assert set(old) == set(key) and len(shipped) == 13, seed  # 11 skills plus none_of_these, plus recall
        for name in key:
            assert json.dumps(old[name]) == json.dumps(key[name]), (seed, name)  # the same bytes, key order included


def test_the_twelfth_option_recall_goes_as_what_and_not_for():
    for seed in SEEDS:
        option = jev.build_criteria(SHIPPED, seed)["recall"]
        assert option == RECALL_OPTION and list(option) == ["what", "not_for"], seed
    assert jev.option_value(SHIPPED["skills"]["recall"]) == RECALL_OPTION


def test_everything_else_jev_sees_is_unchanged():
    shipped, key = SHIPPED["labeler"], V3_1["labeler"]
    for field in ("question", "fallback_label", "fallback_description", "jev_model", "shuffle_options", "min_confidence"):
        assert shipped[field] == key[field], field
    assert shipped["second_question"]["instructions"] == key["second_question"]["instructions"]
    assert list(SHIPPED["skills"]) == list(V3_1["skills"]) + ["recall"]
    for name in V3_1["skills"]:
        assert jev.option_value(SHIPPED["skills"][name]) == jev.option_value(V3_1["skills"][name]), name


class _Client:
    """Records what the router sends Jev; answers recall. No network."""

    def __init__(self):
        self.calls = []

    def system_one(self, state, questions, model=None):
        self.calls.append({"state": state, "questions": questions, "model": model})
        return SimpleNamespace(
            answers={"skill": SimpleNamespace(choice="recall", confidence=0.91, probabilities={"recall": 0.91, "writing": 0.09}),
                     "needs_split": SimpleNamespace(noul=0.1)},
            usage=SimpleNamespace(input_tokens=800))

    def close(self):
        pass


def test_recall_is_in_the_options_jev_gets_and_a_recall_answer_is_a_label():
    client = _Client()
    out = jev.label("what did we decide last time", task_id="sr-20261020-120000-ab12", roster=shipped_roster(),
                    api_key="k", tokens_this_month=0, make_client=lambda key: client)
    call = client.calls[0]
    criteria = call["questions"]["skill"].criteria
    assert criteria["recall"] == RECALL_OPTION and len(criteria) == 13
    assert (call["state"], call["model"]) == ("what did we decide last time", "jev-1.13.0")
    assert out == {"status": "ok", "label": "recall", "confidence": 0.91, "needs_split": 0.1, "tokens": 800}
