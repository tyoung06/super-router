"""Build brief 9, phase A (rules v2.16, Relay): config/presets.json 1.2 with `versus`, and the loader's
new fields. `input`: absent is the stage before, "task" the task alone, "stage:k" the task and stage k's
result (k earlier). `review_of`: a review of one earlier stage by another agent, never of a review, with
`input` naming the same stage. A preset with review stages names no checker and no check stage,
reviews every other stage exactly once, and names the owner as the one who picks. The owner's D1: a stage a
review stage reviews needs no contract. Every value here is fake except the shipped file."""
import json

import pytest

from router import __main__ as cli
from router import presets, relay
from tests.helpers import shipped_presets_doc, shipped_roster

SENDERS = tuple(cli.SENDERS)
VERSUS = {
    "stages": [
        {"n": 1, "agent": "claude", "role": "build", "input": "task", "contract": None},
        {"n": 2, "agent": "chatgpt", "role": "build", "input": "task", "contract": None},
        {"n": 3, "agent": "chatgpt", "role": "review", "input": "stage:1", "review_of": 1, "contract": "review_note"},
        {"n": 4, "agent": "claude", "role": "review", "input": "stage:2", "review_of": 2, "contract": "review_note"},
    ],
    "pick": "owner",
}


def _versus():
    return json.loads(json.dumps(VERSUS))


def _problems(preset):
    return presets.problems("p", preset, shipped_roster(), SENDERS, relay.CONTRACTS, roles=relay.ROLES,
                            verdicts=relay.VERDICTS)


def _load(doc, tmp_path):
    path = tmp_path / "presets.json"
    path.write_text(json.dumps(doc))
    return presets.load_presets(shipped_roster(), SENDERS, relay.CONTRACTS, path=path, roles=relay.ROLES,
                                verdicts=relay.VERDICTS)


# ---------- the shipped file ----------

def test_the_shipped_file_is_version_1_3_with_versus_exactly_as_the_brief_gives_it():
    doc = shipped_presets_doc()  # brief 21: 1.6's descriptions out
    assert doc["version"] == "1.5" and list(doc["presets"])[:3] == ["research-build", "collab", "versus"]  # 16: +redteam, 17: +vote
    assert doc["presets"]["versus"].pop("slots") == {"a": [1, 4], "b": [2, 3]}  # brief 15
    assert doc["presets"]["versus"] == VERSUS


def test_the_shipped_versus_loads_with_its_inputs_reviews_and_pick():
    loaded = presets.load_presets(shipped_roster(), SENDERS, relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
    assert loaded.problems == {}
    v = loaded.presets["versus"]
    assert [(s.n, s.agent, s.role, s.input, s.review_of, s.contract) for s in v.stages] == [
        (1, "claude", "build", "task", None, None), (2, "chatgpt", "build", "task", None, None),
        (3, "chatgpt", "review", "stage:1", 1, "review_note"), (4, "claude", "review", "stage:2", 2, "review_note")]
    assert v.pick == "owner" and v.checker is None and v.check_stage is None
    assert v.has_reviews and v.check_agent is None
    assert [s.n for s in v.review_stages] == [3, 4] and v.reviewer_of(1).n == 3 and v.reviewer_of(2).n == 4
    # The other presets have no review stages and keep their defaults.
    assert not loaded.presets["research-build"].has_reviews and not loaded.presets["collab"].has_reviews
    assert all(s.input is None and s.review_of is None for name in ("research-build", "collab")
               for s in loaded.presets[name].stages)
    assert loaded.presets["collab"].pick is None


@pytest.mark.parametrize("version", ["1.0", "1.1"])
def test_older_files_still_load(version, tmp_path):
    doc = json.loads(presets.PRESETS_PATH.read_text())
    doc["version"] = version
    del doc["presets"]["versus"]
    del doc["presets"]["redteam"]  # brief 16
    del doc["presets"]["vote"]  # brief 17
    loaded = _load(doc, tmp_path)
    assert loaded.problems == {} and loaded.names == ("research-build", "collab")


def test_the_good_versus_has_no_problems():
    assert _problems(_versus()) == []


# ---------- input ----------

def test_input_absent_is_the_stage_before_and_research_build_is_unchanged():
    stage = presets.Stage(2, "claude", "build", None)
    assert stage.input is None and stage.review_of is None


@pytest.mark.parametrize("value", ["stage:3", "stage:2", "stage:9"])
def test_an_input_naming_a_later_stage_or_itself_is_refused(value):
    p = _versus()
    p["stages"][1]["input"] = value
    assert any("stage 2" in m and "later stage" in m for m in _problems(p))


@pytest.mark.parametrize("value", ["stage:1,2", "stage:1+2", ["stage:1", "stage:2"], "stages:1,2"])
def test_an_input_naming_more_than_one_stage_is_refused(value):
    p = _versus()
    p["stages"][2]["input"] = value
    assert any("more than one stage" in m for m in _problems(p))


@pytest.mark.parametrize("value", ["", "the task", "stage:x", "stage:0", 3, None])
def test_an_input_that_is_not_task_or_one_stage_is_refused(value):
    p = _versus()
    p["stages"][0]["input"] = value
    assert any("input" in m and ("'task' or 'stage:k'" in m or "later stage" in m) for m in _problems(p))


# ---------- review_of ----------

def test_a_review_of_the_same_agent_is_refused():
    p = _versus()
    p["stages"][2]["agent"] = "claude"   # stage 3 reviews stage 1, which is claude's
    found = _problems(p)
    assert any("stage 3" in m and "reviews stage 1" in m and "own work" in m for m in found)


def test_a_review_of_a_review_is_refused():
    p = _versus()
    p["stages"][3].update({"input": "stage:3", "review_of": 3})
    p["stages"][3]["agent"] = "claude"
    found = _problems(p)
    assert any("stage 4" in m and "stage 3 is itself a review" in m for m in found)


def test_review_of_and_input_must_name_the_same_stage():
    p = _versus()
    p["stages"][2]["input"] = "stage:2"
    found = _problems(p)
    assert any("stage 3" in m and "review_of 1" in m and "input" in m and "stage:1" in m for m in found)


@pytest.mark.parametrize("value", [0, 3, 4, "1", True, 1.0])
def test_review_of_must_be_an_earlier_stage_number(value):
    p = _versus()
    p["stages"][2]["review_of"] = value
    assert any("stage 3" in m and "review_of" in m for m in _problems(p))


def test_a_review_role_without_review_of_and_review_of_without_the_review_role_are_refused():
    p = _versus()
    del p["stages"][2]["review_of"]
    assert any("stage 3" in m and "role review" in m and "review_of" in m for m in _problems(p))
    p = _versus()
    p["stages"][2]["role"] = "edit"
    assert any("stage 3" in m and "review_of" in m and "role review" in m for m in _problems(p))


def test_a_review_stage_names_the_review_contract():
    p = _versus()
    p["stages"][3]["contract"] = None
    assert any("stage 4" in m and "review" in m and "review_note" in m for m in _problems(p))
    p = _versus()
    p["stages"][2]["contract"] = "edit_check"
    assert any("stage 3" in m and "review_note" in m for m in _problems(p))


# ---------- a preset with review stages ----------

def test_a_review_preset_that_names_a_checker_is_refused():
    p = _versus()
    p["checker"] = "chatgpt"
    assert any("review stages" in m and "checker" in m for m in _problems(p))


def test_a_review_preset_that_marks_is_check_is_refused():
    p = _versus()
    p["stages"][3]["is_check"] = True
    assert any("review stages" in m and "is_check" in m for m in _problems(p))


def test_an_unreviewed_stage_is_refused():
    p = _versus()
    p["stages"] = p["stages"][:3]   # stage 2 is never reviewed
    found = _problems(p)
    assert any("stage 2 is not reviewed" in m for m in found)


def test_a_stage_reviewed_twice_is_refused():
    p = _versus()
    p["stages"][3].update({"input": "stage:1", "review_of": 1, "agent": "chatgpt"})
    found = _problems(p)
    assert any("stage 1 is reviewed twice" in m for m in found)
    assert any("stage 2 is not reviewed" in m for m in found)


def test_a_review_preset_without_a_pick_is_refused():
    p = _versus()
    del p["pick"]
    assert any("review stages" in m and "pick" in m and "owner" in m for m in _problems(p))
    p["pick"] = "claude"
    assert any("pick" in m and "owner" in m for m in _problems(p))


def test_a_pick_on_a_preset_without_review_stages_is_refused(tmp_path):
    doc = json.loads(presets.PRESETS_PATH.read_text())
    doc["presets"]["collab"]["pick"] = "owner"
    loaded = _load(doc, tmp_path)
    assert any("pick" in m and "no review stages" in m for m in loaded.problems["collab"])


def test_d1_a_reviewed_stage_needs_no_contract_but_an_unreviewed_one_still_does(tmp_path):
    assert _problems(_versus()) == []
    doc = json.loads(presets.PRESETS_PATH.read_text())
    doc["presets"]["collab"]["stages"][0]["contract"] = None
    loaded = _load(doc, tmp_path)
    assert any("stage 1 has no contract" in m for m in loaded.problems["collab"])


def test_the_four_stage_cap_and_the_live_agent_check_still_hold():
    p = _versus()
    p["stages"].append({"n": 5, "agent": "chatgpt", "role": "build", "input": "task", "contract": None})
    assert any("5 stages" in m and "at most 4" in m for m in _problems(p))
    p = _versus()
    p["stages"][1]["agent"] = "muse"  # brief 24: refused for having no sender (the live check left the loader)
    assert any("muse" in m and "no way to send" in m for m in _problems(p))


def test_unknown_stage_fields_are_still_refused():
    p = _versus()
    p["stages"][0]["inputs"] = "task"
    assert any("unknown field 'inputs'" in m for m in _problems(p))


# ---------- sr relay --list ----------

def test_relay_list_prints_inputs_reviews_and_the_pick(capsys):
    loaded = presets.load_presets(shipped_roster(), SENDERS, relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
    lines = presets.describe(loaded)
    at = lines.index("versus")
    assert lines[at:at + 6] == [
        "versus",
        "  1. build by claude (input: task)",
        "  2. build by chatgpt (input: task)",
        "  3. review of stage 1 by chatgpt (input: stage 1, contract review_note)",
        "  4. review of stage 2 by claude (input: stage 2, contract review_note)",
        "  pick: owner",
    ]
    # research-build and collab print as they did.
    assert lines[1:5] == ["research-build", "  1. research by grok (contract research_note)", "  2. build by claude",
                          "  checker: chatgpt"]
    assert "  check: stage 4 (chatgpt)" in lines
