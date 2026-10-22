"""Build brief 16, phase A: the two stage kinds and the `redteam` preset (rules v2.23, Relay). An attack stage names
`attack_of` (an earlier stage; input that stage; its agent not that stage's agent; the attack_list contract). A revise
stage names `revise_of` and `against` (two different earlier stages; same agent as `revise_of`; one per preset;
never a check or a review; the revision contract, allowed on the last stage). Checked on the chain after the slots
are filled; intake refuses `build` = `attack` and `build` = `check`; `attack` = `check` is allowed and the default.
Every value here is fake except the shipped file."""
import json

import pytest

from router import __main__ as cli
from router import log, presets, relay
from tests.helpers import shipped_presets_doc, shipped_roster

SENDERS = tuple(cli.SENDERS)
ROSTER = shipped_roster()


def _loaded(path=None):
    return presets.load_presets(ROSTER, SENDERS, relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS,
                                path=path)


def _problems(entry):
    return presets.problems("p", entry, ROSTER, SENDERS, relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)


def _redteam():
    return {"stages": [{"n": 1, "agent": "claude", "role": "build", "input": "task", "contract": "deliverable"},
                       {"n": 2, "agent": "chatgpt", "role": "attack", "input": "stage:1", "attack_of": 1,
                        "contract": "attack_list"},
                       {"n": 3, "agent": "claude", "role": "revise", "revise_of": 1, "against": 2,
                        "contract": "revision"}],
            "checker": "chatgpt", "slots": {"build": [1, 3], "attack": [2], "check": ["checker"]}}


# ---------- the shipped preset ----------

def test_the_shipped_file_is_1_4_with_redteam_exactly_as_decision_1():
    doc = shipped_presets_doc()  # brief 21: 1.6's descriptions out
    assert doc["version"] == "1.5" and list(doc["presets"])[:4] == ["research-build", "collab", "versus", "redteam"]  # 17: +vote
    assert doc["presets"]["redteam"] == _redteam()
    assert "1.4" in presets.FILE_VERSIONS


def test_redteam_loads_with_its_stage_kinds_and_slots():
    loaded = _loaded()
    assert loaded.problems == {}
    rt = loaded.presets["redteam"]
    assert [(s.n, s.agent, s.role, s.input, s.attack_of, s.revise_of, s.against, s.contract) for s in rt.stages] == [
        (1, "claude", "build", "task", None, None, None, "deliverable"),
        (2, "chatgpt", "attack", "stage:1", 1, None, None, "attack_list"),
        (3, "claude", "revise", None, None, 1, 2, "revision")]
    assert rt.checker == "chatgpt" and rt.doer == "claude" and rt.check_agent == "chatgpt"
    assert presets.slot_map(rt) == {"build": "claude", "attack": "chatgpt", "check": "chatgpt"}
    assert rt.revise_stage is rt.stages[2] and rt.attack_stage is rt.stages[1]


def test_the_other_three_presets_are_unchanged():
    doc = shipped_presets_doc()
    from tests.test_presets import COLLAB, GOOD
    from tests.test_versus_presets import VERSUS
    for name in ("research-build", "collab", "versus"):
        doc["presets"][name].pop("slots")
    assert doc["presets"]["research-build"] == GOOD["presets"]["research-build"]
    assert doc["presets"]["collab"] == COLLAB and doc["presets"]["versus"] == VERSUS


def test_relay_list_prints_redteam_with_its_kinds_and_slots(capsys):
    assert cli.cmd_relay_list(loaded=_loaded()) == 0
    out = capsys.readouterr().out
    assert "redteam" in out and "2. attack of stage 1 by chatgpt (input: stage 1, contract attack_list)" in out
    assert "3. revise of stage 1 against stage 2 by claude (contract revision)" in out
    assert "  slots: build (stages 1, 3) claude, attack (stage 2) chatgpt, check (checker) chatgpt" in out


# ---------- each refusal of decision 10 ----------

def _with(change):
    entry = _redteam()
    change(entry["stages"])
    return entry


@pytest.mark.parametrize("change, words", [
    (lambda s: s[1].pop("attack_of"), "stage 2 has the role attack but no attack_of"),
    (lambda s: s[1].update(role="build", contract="deliverable"), "stage 2 names attack_of but not the role attack"),
    (lambda s: s[1].update(attack_of=2, input="stage:1"), "stage 2 has attack_of 2; it must be the number of an earlier stage"),
    (lambda s: s[1].update(agent="claude"), "stage 2 by claude attacks stage 1, which is claude's own work"),
    (lambda s: s[1].update(input="task"), "stage 2 attacks stage 1 but has input 'task'; an attack's input must be 'stage:1'"),
    (lambda s: s[1].update(contract="deliverable"), "stage 2 is an attack and names contract 'deliverable'"),
    (lambda s: s[2].pop("against"), "stage 3 names revise_of but no against"),
    (lambda s: s[2].pop("revise_of"), "stage 3 has the role revise but no revise_of"),
    (lambda s: s[2].update(revise_of=3), "stage 3 has revise_of 3; it must be the number of an earlier stage"),
    (lambda s: s[2].update(against=4), "stage 3 has against 4; it must be the number of an earlier stage"),
    (lambda s: s[2].update(against=1), "stage 3 revises stage 1 against stage 1; against must be another stage"),
    (lambda s: s[2].update(agent="chatgpt"), "stage 3 by chatgpt revises stage 1, which is claude's"),
    (lambda s: s[2].update(is_check=True), "stage 3 is a revise stage and is marked is_check"),
    (lambda s: s[2].update(input="stage:2"), "stage 3 is a revise stage and names an input"),
    (lambda s: s[2].update(contract="deliverable"), "stage 3 is a revise stage and names contract 'deliverable'"),
])
def test_each_stage_kind_refusal_is_named(change, words):
    found = _problems(_with(change))
    assert any(words in p for p in found), found


def test_at_most_one_revise_stage():
    entry = _redteam()
    entry["stages"].insert(2, {"n": 3, "agent": "claude", "role": "revise", "revise_of": 1, "against": 2,
                               "contract": "revision"})
    entry["stages"][3]["n"] = 4
    entry["slots"] = {"build": [1, 3, 4], "attack": [2], "check": ["checker"]}
    found = _problems(entry)
    assert any("preset p has 2 revise stages; at most one" in p for p in found), found


def test_only_a_revise_stage_may_name_a_contract_on_the_last_stage():
    entry = _redteam()
    entry["stages"][2].update(role="build", contract="revision")
    for key in ("revise_of", "against"):
        entry["stages"][2].pop(key)
    found = _problems(entry)
    assert any("is the last stage and names a contract" in p for p in found), found
    assert _problems(_redteam()) == []


# ---------- intake on slots (decision 9) ----------

def _filled(flags):
    return presets.slot_refusals(_loaded().presets["redteam"], flags, ROSTER)


def _all_problems(filled):
    return presets.problems("redteam", presets.as_entry(filled), ROSTER, SENDERS, relay.CONTRACTS, roles=relay.ROLES,
                            verdicts=relay.VERDICTS)


@pytest.mark.parametrize("flags", [
    [("build", "grok"), ("attack", "chatgpt"), ("check", "chatgpt")],
    [("attack", "grok")],
    [("build", "chatgpt"), ("attack", "claude"), ("check", "claude")],
    [],
])
def test_accepted_fillings(flags):
    filled, refused = _filled(flags)
    assert refused == [] and _all_problems(filled) == []


@pytest.mark.parametrize("flags, words", [
    ([("build", "claude"), ("attack", "claude")],
     "slots build and attack both hold claude; an attacker does not attack its own build."),
    ([("build", "chatgpt"), ("check", "chatgpt")],
     "slots build and check both hold chatgpt; no agent checks or reviews its own work."),
    ([("attack", "claude")], "slots build and attack both hold claude; an attacker does not attack its own build."),
])
def test_refused_fillings_with_their_reasons(flags, words):
    filled, refused = _filled(flags)
    assert filled is None and words in refused


def test_attack_and_check_may_hold_the_same_agent():
    filled, refused = _filled([("attack", "claude"), ("check", "claude"), ("build", "chatgpt")])
    assert refused == [] and filled.checker == "claude" and filled.stages[1].agent == "claude"


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def test_a_refused_redteam_filling_writes_no_row_and_calls_no_one(conn):
    from tests.test_slots_intake import CONFIG
    lines = []
    code = cli.cmd_relay("redteam", "Write a plan.", conn=conn, config=CONFIG, roster=ROSTER, loaded=_loaded(),
                         environ={}, settings_paths=[], post=None, worker=None,
                         slots=[("build", "claude"), ("attack", "claude")], out=lines.append)
    assert code == 2 and log.recent_tasks(conn) == []
    assert "Refused: slots build and attack both hold claude; an attacker does not attack its own build." in lines


def test_a_slot_that_would_make_the_reviser_differ_from_the_builder_is_refused(tmp_path):
    doc = json.loads(presets.PRESETS_PATH.read_text())
    doc["presets"]["redteam"]["slots"] = {"b1": [1], "attack": [2], "b3": [3], "check": ["checker"]}
    path = tmp_path / "presets.json"
    path.write_text(json.dumps(doc))
    loaded = _loaded(path)
    assert loaded.problems == {}   # with the defaults stage 1 and 3 are both claude
    filled, refused = presets.slot_refusals(loaded.presets["redteam"], [("b3", "grok")], ROSTER)
    assert refused == []
    found = presets.problems("redteam", presets.as_entry(filled), ROSTER, SENDERS, relay.CONTRACTS, roles=relay.ROLES,
                             verdicts=relay.VERDICTS)
    assert any("stage 3 by grok revises stage 1, which is claude's" in p for p in found), found
