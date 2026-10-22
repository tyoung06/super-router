"""Build brief 15, phase A: slots in the presets (rules v2.21, Relay → Slots). Each preset names its slots in
config/presets.json beside its stages: a slot covers stages (and, on research-build, the checker), its default is
the agent the preset names there. `presets.fill` puts other agents in slots for one task; `presets.for_task`
builds a task's filled preset from its row. Every value here is fake except the shipped file."""
import json

import pytest

from router import __main__ as cli
from router import presets, relay
from tests.helpers import SHIPPED_PRESET_VERSIONS, shipped_presets_doc, shipped_roster

SENDERS = tuple(cli.SENDERS)


def _shipped():
    return presets.load_presets(shipped_roster(), SENDERS, relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)


def _problems(preset):
    return presets.problems("p", preset, shipped_roster(), SENDERS, relay.CONTRACTS, roles=relay.ROLES,
                            verdicts=relay.VERDICTS)


def _rb(slots):
    return {"stages": [{"n": 1, "agent": "grok", "role": "research", "contract": "research_note"},
                       {"n": 2, "agent": "claude", "role": "build", "contract": None}],
            "checker": "chatgpt", "slots": slots}


def _collab(slots):
    return {"stages": [{"n": 1, "agent": "claude", "role": "plan", "contract": "plan"},
                       {"n": 2, "agent": "chatgpt", "role": "amend", "contract": "amended_plan"},
                       {"n": 3, "agent": "claude", "role": "execute", "contract": "deliverable"},
                       {"n": 4, "agent": "chatgpt", "role": "edit", "contract": "edit_check", "is_check": True}],
            "checker": None, "slots": slots}


RB_SLOTS = {"research": [1], "build": [2], "check": ["checker"]}


# ---------- the shipped file ----------

def test_the_shipped_file_is_1_3_with_the_slots_of_rules_2_21():
    doc = shipped_presets_doc()  # brief 21: 1.6's descriptions out
    assert doc["version"] in ("1.3", "1.4", "1.5")  # brief 16: 1.4 (redteam), 17: 1.5 (vote); these three slot maps unchanged
    assert doc["presets"]["research-build"]["slots"] == {"research": [1], "build": [2], "check": ["checker"]}
    assert doc["presets"]["collab"]["slots"] == {"lead": [1, 3], "partner": [2, 4]}
    assert doc["presets"]["versus"]["slots"] == {"a": [1, 4], "b": [2, 3]}
    assert "1.3" in presets.FILE_VERSIONS and "1.4" in presets.FILE_VERSIONS


def test_the_shipped_file_changed_only_by_the_slots_maps():
    doc = shipped_presets_doc()
    doc["presets"].pop("redteam")  # brief 16 adds it; tests/test_redteam_presets.py checks it
    doc["presets"].pop("vote")  # brief 17 adds it; tests/test_vote_presets.py checks it
    for entry in doc["presets"].values():
        entry.pop("slots")
    from tests.test_presets import COLLAB, GOOD
    assert doc["presets"]["research-build"] == GOOD["presets"]["research-build"]
    assert doc["presets"]["collab"] == COLLAB
    assert set(doc["presets"]) == {"research-build", "collab", "versus"}


def test_the_shipped_presets_load_with_no_problems_and_carry_their_slots():
    loaded = _shipped()
    assert loaded.problems == {}
    rb = loaded.presets["research-build"]
    assert [(s.name, s.stages, s.checker, s.agent, s.default) for s in rb.slots] == [
        ("research", (1,), False, "grok", "grok"), ("build", (2,), False, "claude", "claude"),
        ("check", (), True, "chatgpt", "chatgpt")]
    assert presets.slot_map(loaded.presets["collab"]) == {"lead": "claude", "partner": "chatgpt"}
    assert presets.slot_map(loaded.presets["versus"]) == {"a": "claude", "b": "chatgpt"}


@pytest.mark.parametrize("name", ["research-build", "collab", "versus"])
def test_the_defaults_give_a_preset_equal_to_todays(name):
    loaded = _shipped()
    base = loaded.presets[name]
    filled = presets.fill(base, presets.slot_map(base))
    assert filled == base
    assert filled.stages == base.stages and filled.checker == base.checker and filled.pick == base.pick
    assert presets.fill(base, {}) == base
    assert presets.changed(filled) == {}


# ---------- fill ----------

def test_fill_puts_agents_in_slots_and_changes_nothing_else():
    loaded = _shipped()
    rb = presets.fill(loaded.presets["research-build"], {"research": "chatgpt", "check": "claude", "build": "grok"})
    assert [(s.n, s.agent, s.role, s.contract) for s in rb.stages] == [
        (1, "chatgpt", "research", "research_note"), (2, "grok", "build", None)]
    assert rb.checker == "claude" and rb.doer == "grok" and rb.check_agent == "claude"
    assert presets.changed(rb) == {"research": "chatgpt", "build": "grok", "check": "claude"}
    collab = presets.fill(loaded.presets["collab"], {"lead": "chatgpt", "partner": "claude"})
    assert [s.agent for s in collab.stages] == ["chatgpt", "claude", "chatgpt", "claude"]
    assert collab.check_stage.agent == "claude" and collab.doer == "chatgpt" and collab.check_stage.is_check
    versus = presets.fill(loaded.presets["versus"], {"b": "grok"})
    assert [s.agent for s in versus.stages] == ["claude", "grok", "grok", "claude"]
    assert [s.review_of for s in versus.stages] == [None, None, 1, 2]
    assert presets.changed(versus) == {"b": "grok"}


def test_fill_refuses_a_slot_the_preset_does_not_have():
    loaded = _shipped()
    with pytest.raises(ValueError, match="collab has no slot research"):
        presets.fill(loaded.presets["collab"], {"research": "grok"})


def test_the_base_preset_is_never_changed_by_fill():
    loaded = _shipped()
    base = loaded.presets["versus"]
    presets.fill(base, {"a": "grok"})
    assert [s.agent for s in loaded.presets["versus"].stages] == ["claude", "chatgpt", "chatgpt", "claude"]


# ---------- for_task ----------

def _row(preset, slots=None, mode="relay"):
    return {"mode": mode, "preset": preset, "slots": json.dumps(slots) if slots is not None else None}


def test_for_task_reads_the_rows_slots():
    loaded = _shipped()
    preset, problem = presets.for_task(_row("versus", {"a": "claude", "b": "grok"}), loaded)
    assert problem is None and [s.agent for s in preset.stages] == ["claude", "grok", "grok", "claude"]


def test_for_task_with_no_slots_on_the_row_is_the_preset_as_it_is():
    # rows from before log version 10 ran with the defaults
    loaded = _shipped()
    assert presets.for_task(_row("collab"), loaded) == (loaded.presets["collab"], None)


def test_for_task_says_why_when_it_cannot_build_the_preset():
    loaded = _shipped()
    assert presets.for_task(_row("collab"), None)[1] == \
        "config/presets.json could not be read, so its preset collab is unknown"
    assert presets.for_task(_row("nope"), loaded)[1] == "its preset nope can't run: it is not in config/presets.json"
    preset, problem = presets.for_task(_row("collab", {"research": "grok"}), loaded)
    assert preset is None and problem == "its slots (research) don't match preset collab's (lead, partner)"


def test_slots_of_a_row_without_the_column_is_none():
    assert presets.slots_of({"mode": "relay", "preset": "collab"}) is None


# ---------- the loader's checks ----------

def test_good_slots_have_no_problems():
    assert _problems(_rb(RB_SLOTS)) == []
    assert _problems(_collab({"lead": [1, 3], "partner": [2, 4]})) == []


def test_a_preset_without_slots_still_loads():
    entry = _rb(RB_SLOTS)
    del entry["slots"]
    assert _problems(entry) == []


@pytest.mark.parametrize("slots, words", [
    ({"research": [1], "check": ["checker"]}, "stage 2 is in no slot"),
    ({"research": [1, 2], "build": [2], "check": ["checker"]}, "stage 2 is in more than one slot (research, build)"),
    ({"research": [1], "build": [2]}, "the checker is in no slot"),
    ({"research": [1], "build": [2], "check": ["checker"], "also": ["checker"]},
     "the checker is in more than one slot (check, also)"),
    ({"research": [1], "build": [2, 5], "check": ["checker"]}, "slot build names stage 5, which the preset doesn't have"),
    ({"research": [1], "build": [], "check": ["checker"]}, "slot build covers nothing"),
    ({"research": [1], "build": "2", "check": ["checker"]}, "slot build must be a list"),
    ({"Research": [1], "build": [2], "check": ["checker"]}, "slot name 'Research' is not a plain lowercase word"),
    ({"web": [1], "build": [2], "check": ["checker"]}, "slot name 'web' is one of relay's own words"),
    ({"list": [1], "build": [2], "check": ["checker"]}, "slot name 'list' is one of relay's own words"),
    ({"research": [1], "build": [2, "checker"]}, "slot build covers claude and chatgpt; a slot's parts share one default agent"),
    ([], "slots must be an object"),
])
def test_each_bad_slots_map_is_refused_with_its_reason(slots, words):
    found = _problems(_rb(slots))
    assert any(words in p for p in found), found


def test_checker_in_a_slot_of_a_preset_without_a_checker_is_refused():
    found = _problems(_collab({"lead": [1, 3], "partner": [2, 4], "check": ["checker"]}))
    assert any("names the checker, but preset p has none" in p for p in found), found


def test_a_slots_stages_must_share_one_default_agent():
    found = _problems(_collab({"lead": [1, 2], "partner": [3, 4]}))
    assert any("slot lead covers claude and chatgpt" in p for p in found), found


# ---------- sr relay --list ----------

def test_relay_list_prints_each_presets_slots_and_defaults(capsys):
    assert cli.cmd_relay_list(loaded=_shipped()) == 0
    out = capsys.readouterr().out
    assert any(f"version {v}" in out for v in SHIPPED_PRESET_VERSIONS)  # brief 16: 1.4; 17: 1.5; 21: 1.6
    assert "  slots: research (stage 1) grok, build (stage 2) claude, check (checker) chatgpt" in out
    assert "  slots: lead (stages 1, 3) claude, partner (stages 2, 4) chatgpt" in out
    assert "  slots: a (stages 1, 4) claude, b (stages 2, 3) chatgpt" in out
    assert "--<slot> <agent>" in out
