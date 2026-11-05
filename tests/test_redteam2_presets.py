"""Build brief 32, R (decisions 7, 11, 12, 14 and 18): the second attacker in the preset. presets 1.7: redteam builds,
attacks twice (stage 3, Cursor's, optional, never seeing stage 2's list), revises against both and is checked. The loader
takes `optional` on an attack stage that is not the first attack and `against` as a list of one or two attack stages of
the same build, and refuses anything else. `attack2` holds neither the build agent nor the attack agent; Cursor may fill
`attack` or `attack2`, never `check`. The optional stage is left out at intake when its default agent isn't available (a
three-stage chain, `attack2` null), never when set by flag. An old task's row (no `attack2`) reads in the three-stage
shape without labels. The split's menu counts redteam 5 to 7 calls, 4 to 6 without Cursor. Every value here is fake but
the shipped file."""
import json

import pytest

from router import __main__ as cli
from router import availability, presets, relay, teams
from tests.helpers import shipped_roster

SENDERS = tuple(cli.SENDERS)
ROSTER = shipped_roster()
DESCRIPTION = ("One agent builds, two others attack it on their own, the builder fixes what they found, and a checker "
               "confirms the fixes.")
REDTEAM_17 = {
    "description": DESCRIPTION,
    "stages": [{"n": 1, "agent": "claude", "role": "build", "input": "task", "contract": "deliverable"},
               {"n": 2, "agent": "chatgpt", "role": "attack", "input": "stage:1", "attack_of": 1, "contract": "attack_list"},
               {"n": 3, "agent": "cursor", "role": "attack", "input": "stage:1", "attack_of": 1, "contract": "attack_list",
                "optional": True},
               {"n": 4, "agent": "claude", "role": "revise", "revise_of": 1, "against": [2, 3], "contract": "revision"}],
    "checker": "chatgpt",
    "slots": {"build": [1, 4], "attack": [2], "attack2": [3], "check": ["checker"]}}


def _loaded(path=None):
    return presets.load_presets(ROSTER, SENDERS, relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS, path=path)


def _problems(entry):
    return presets.problems("p", entry, ROSTER, SENDERS, relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)


def _entry(**changes):
    entry = json.loads(json.dumps(REDTEAM_17))
    entry.pop("description")
    for n, fields in changes.items():
        stage = entry["stages"][int(n[1:]) - 1]
        for key, value in fields.items():
            if value is None:
                stage.pop(key, None)
            else:
                stage[key] = value
    return entry


class Avail:
    """An availability table: every agent available but the ones named, with a why."""

    def __init__(self, **off):
        self.off = off

    def __call__(self, agent):
        why = self.off.get(agent)
        return availability.Availability(why is None, why, None if why is None else "not_live")


# ---------- presets 1.7 (decision 7) ----------

def test_the_shipped_redteam_is_1_7s_four_stages_with_the_optional_second_attack():
    doc = json.loads(presets.PRESETS_PATH.read_text())
    assert doc["version"] == "1.7" and "1.7" in presets.FILE_VERSIONS
    assert doc["presets"]["redteam"] == REDTEAM_17


def test_redteam_loads_with_both_attack_stages_and_its_slots():
    loaded = _loaded()
    assert loaded.problems == {}
    rt = loaded.presets["redteam"]
    assert [(s.n, s.agent, s.role, s.input, s.attack_of, s.revise_of, s.against_stages, s.optional) for s in rt.stages] == [
        (1, "claude", "build", "task", None, None, (), False),
        (2, "chatgpt", "attack", "stage:1", 1, None, (), False),
        (3, "cursor", "attack", "stage:1", 1, None, (), True),
        (4, "claude", "revise", None, None, 1, (2, 3), False)]
    assert [s.n for s in rt.attack_stages] == [2, 3] and rt.attack_stage.n == 2 and rt.revise_stage.n == 4
    assert presets.slot_map(rt) == {"build": "claude", "attack": "chatgpt", "attack2": "cursor", "check": "chatgpt"}
    assert rt.letter_of(2) == "A" and rt.letter_of(3) == "B" and rt.lettered
    assert presets.chain(rt) == "Claude build → ChatGPT attack → Cursor attack → Claude revise → ChatGPT check"


@pytest.mark.parametrize("changes, words", [
    ({"s2": {"optional": True}, "s3": {"optional": None}}, "the first attack"),
    ({"s1": {"optional": True}}, "only an attack stage"),
    ({"s4": {"optional": True}}, "only an attack stage"),
    ({"s3": {"optional": "yes"}}, "must be true"),
    ({"s4": {"against": [2, 3, 2]}}, "one or two"),
    ({"s4": {"against": []}}, "one or two"),
    ({"s4": {"against": [1, 2]}}, "attack stages of the build it revises"),
    ({"s4": {"against": [2, 2]}}, "twice"),
])
def test_the_loader_refuses_optional_and_against_anywhere_else(changes, words):
    found = _problems(_entry(**changes))
    assert any(words in p for p in found), found


def test_against_takes_one_attack_stage_in_a_list_and_the_old_int_form_still_loads():
    one = _entry()
    one["stages"] = [one["stages"][0], one["stages"][1], {**one["stages"][3], "n": 3, "against": [2]}]
    one["slots"] = {"build": [1, 3], "attack": [2], "check": ["checker"]}
    assert _problems(one) == []
    one["stages"][2]["against"] = 2  # presets 1.4 to 1.6 wrote an int
    assert _problems(one) == []


# ---------- who fills attack2 (decision 12) ----------

@pytest.mark.parametrize("flags, words", [
    ([("attack2", "claude")], "slots build and attack2 both hold claude; an attacker does not attack its own build."),
    ([("attack2", "chatgpt")], "slots attack and attack2 both hold chatgpt; two lists from one agent are not two attackers."),
])
def test_attack2_holds_neither_the_build_agent_nor_the_attack_agent(flags, words):
    filled, refused = presets.slot_refusals(_loaded().presets["redteam"], flags, ROSTER)
    assert filled is None and words in refused


def test_cursor_may_fill_attack_or_attack2_never_check_and_its_versus_slots_stay():
    rt = _loaded().presets["redteam"]
    assert presets.slot_allowed("cursor", "redteam", "attack") and presets.slot_allowed("cursor", "redteam", "attack2")
    assert not presets.slot_allowed("cursor", "redteam", "check") and not presets.slot_allowed("cursor", "redteam", "build")
    assert presets.slot_allowed("cursor", "versus", "a") and not presets.slot_allowed("cursor", "research-build", "build")
    filled, refused = presets.slot_refusals(rt, [("attack", "cursor"), ("attack2", "grok")], ROSTER)
    assert refused == [] and presets.slot_map(filled)["attack"] == "cursor"
    filled, refused = presets.slot_refusals(rt, [("check", "cursor")], ROSTER)
    assert filled is None and any("redteam check" in r for r in refused)


def test_attack2_is_a_slot_of_redteam_only():
    loaded = _loaded()
    filled, refused = presets.slot_refusals(loaded.presets["research-build"], [("attack2", "cursor")], ROSTER)
    assert filled is None and refused == ["research-build has no slot attack2 (its slots: research, build, check)."]
    assert "attack2" in presets.slot_names()


# ---------- the optional stage left out (decision 11) ----------

def _fill(flags=(), **off):
    rt = _loaded().presets["redteam"]
    return presets.fill_unavailable(rt, list(flags), ROSTER, Avail(**off), send_paths=SENDERS, contracts=relay.CONTRACTS,
                                    roles=relay.ROLES, verdicts=relay.VERDICTS)


def test_a_missing_cursor_leaves_the_second_attack_out_and_the_chain_runs_three_stages():
    filled, fills, why = _fill(cursor="Cursor isn't set up: no model")
    assert why is None and len(filled.stages) == 3 and filled.left_out == ("attack2",)
    assert [(s.n, s.role, s.agent) for s in filled.stages] == [(1, "build", "claude"), (2, "attack", "chatgpt"),
                                                               (3, "revise", "claude")]
    assert filled.revise_stage.against_stages == (2,) and filled.revise_stage.revise_of == 1
    assert presets.row_slots(filled) == {"build": "claude", "attack": "chatgpt", "attack2": None, "check": "chatgpt"}
    assert fills == [{"slot": "attack2", "agent": None, "default": "cursor", "why": "Cursor isn't set up: no model"}]
    assert presets.fills_reason(fills) == "relay; attack2 left out (cursor): Cursor isn't set up: no model"
    assert presets.fills_of(presets.fills_reason(fills)) == [
        {"slot": "attack2", "agent": None, "default": "cursor", "why": "Cursor isn't set up: no model"}]
    assert filled.lettered and filled.letter_of(2) == "A"


def test_a_flagged_attack2_is_never_left_out_and_is_refused_when_its_agent_isnt_available():
    filled, refused = presets.slot_refusals(_loaded().presets["redteam"], [("attack2", "cursor")], ROSTER,
                                            Avail(cursor="cursor: not signed in (agent login)"))
    assert filled is None and refused == ["cursor can't fill slot attack2: cursor: not signed in (agent login)."]


def test_with_cursor_available_the_chain_is_the_four_stages():
    filled, fills, why = _fill()
    assert why is None and fills == [] and len(filled.stages) == 4 and filled.left_out == ()
    assert presets.row_slots(filled) == {"build": "claude", "attack": "chatgpt", "attack2": "cursor", "check": "chatgpt"}


# ---------- a task's filled preset, read from its row (decision 18) ----------

def _row(slots, preset="redteam"):
    return {"preset": preset, "slots": json.dumps(slots) if slots is not None else None, "project": None}


def test_a_row_holding_attack2_null_reads_three_stages_with_labels_and_an_old_row_without_labels():
    loaded = _loaded()
    new, _ = presets.for_task(_row({"build": "claude", "attack": "chatgpt", "attack2": None, "check": "chatgpt"}), loaded)
    old, _ = presets.for_task(_row({"build": "claude", "attack": "chatgpt", "check": "chatgpt"}), loaded)
    for found in (new, old):
        assert [(s.n, s.role) for s in found.stages] == [(1, "build"), (2, "attack"), (3, "revise")]
        assert found.revise_stage.against_stages == (2,)
    assert new.lettered and not old.lettered
    both, _ = presets.for_task(_row({"build": "claude", "attack": "chatgpt", "attack2": "cursor", "check": "chatgpt"}), loaded)
    assert len(both.stages) == 4 and both.lettered and presets.slot_map(both)["attack2"] == "cursor"
    pre_v10, _ = presets.for_task(_row(None), loaded)
    assert len(pre_v10.stages) == 3 and not pre_v10.lettered


def test_an_old_rows_grok_attack_reads_as_it_ran():
    old, _ = presets.for_task(_row({"build": "claude", "attack": "grok", "check": "chatgpt"}), _loaded())
    assert [(s.n, s.agent) for s in old.stages] == [(1, "claude"), (2, "grok"), (3, "claude")]


# ---------- the counts (decision 14) ----------

def test_the_menu_counts_redteam_five_to_seven_calls_and_four_to_six_without_cursor():
    loaded = _loaded()
    rt = next(t for t in teams.menu(loaded, ROSTER, Avail(), send_paths=SENDERS) if t["name"] == "redteam")
    assert (rt["calls"], rt["max_calls"]) == (5, 7)
    assert rt["chain"] == "Claude build → ChatGPT attack → Cursor attack → Claude revise → ChatGPT check"
    rt = next(t for t in teams.menu(loaded, ROSTER, Avail(cursor="Cursor isn't set up"), send_paths=SENDERS)
              if t["name"] == "redteam")
    assert (rt["calls"], rt["max_calls"]) == (4, 6) and rt["ready"]
    assert rt["chain"] == "Claude build → ChatGPT attack → Claude revise → ChatGPT check"
