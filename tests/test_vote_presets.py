"""Build brief 17, phase A (rules v2.24, Relay: tally presets; Slots): the `vote` preset in config/presets.json 1.5
(decision 1) and the tally branch of presets.problems() (decision 2, the owner's choice 1: `pick: "tally"` reuses the
`pick` field), each refusal with its own sentence, asked of the filled chain at intake. Every value here is fake."""
import json
from pathlib import Path

import pytest

from router import __main__ as cli
from router import log, presets, relay
from tests.helpers import shipped_presets_doc, shipped_presets_text, shipped_roster
from tests.test_relay import CONFIG, Chat, Clock, RelayHook, Scripted

SENDERS = tuple(cli.SENDERS)
ROSTER = shipped_roster()
LOADED = presets.load_presets(ROSTER, SENDERS, relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)


def _vote():
    return {"stages": [{"n": 1, "agent": "claude", "role": "vote", "input": "task", "contract": "vote"},
                       {"n": 2, "agent": "chatgpt", "role": "vote", "input": "task", "contract": "vote"},
                       {"n": 3, "agent": "grok", "role": "vote", "input": "task", "contract": "vote"}],
            "pick": "tally", "slots": {"a": [1], "b": [2], "c": [3]}}


def _problems(entry):
    return presets.problems("vote", entry, ROSTER, SENDERS, relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


# ---------- the shipped preset (decision 1) ----------

def test_the_shipped_file_is_1_5_with_vote_exactly_as_decision_1():
    doc = shipped_presets_doc()  # brief 21: 1.6's descriptions out
    assert doc["version"] == "1.5"
    assert list(doc["presets"]) == ["research-build", "collab", "versus", "redteam", "vote"]
    assert doc["presets"]["vote"] == _vote()
    assert "1.5" in presets.FILE_VERSIONS


def test_the_other_four_presets_are_byte_for_byte_mains():
    # tests/fixtures/presets_v1_4.json is `git show e99e209:config/presets.json`, saved before phase A (its pick `owner` since brief 25)
    main = (Path(__file__).parent / "fixtures" / "presets_v1_4.json").read_text()
    now = shipped_presets_text()  # brief 21: 1.6's description lines out
    assert {k: v for k, v in json.loads(now)["presets"].items() if k != "vote"} == json.loads(main)["presets"]
    before = main.replace('"version": "1.4"', '"version": "1.5"')
    cut = before.rindex("\n    }") + len("\n    }")   # the end of redteam's entry: everything up to it unchanged
    assert now[:cut] == before[:cut]


def test_vote_loads_as_a_tally_preset():
    assert LOADED.problems == {}
    vote = LOADED.presets["vote"]
    assert vote.tallies and not vote.has_reviews and vote.pick == "tally"
    assert [(s.n, s.agent, s.role, s.input, s.contract) for s in vote.stages] == [
        (1, "claude", "vote", "task", "vote"), (2, "chatgpt", "vote", "task", "vote"), (3, "grok", "vote", "task", "vote")]
    assert vote.checker is None and vote.check_agent is None and vote.check_stage is None
    assert vote.doer == "claude"  # stage 1's agent while the chain runs; the tally names the doer
    assert presets.slot_map(vote) == {"a": "claude", "b": "chatgpt", "c": "grok"}


def test_no_other_preset_tallies():
    assert [name for name, p in LOADED.presets.items() if p.tallies] == ["vote"]


def test_sr_relay_list_names_the_tally():
    lines = presets.describe(LOADED)
    at = lines.index("vote")
    assert lines[at + 1:at + 6] == ["  1. vote by claude (input: task, contract vote)",
                                    "  2. vote by chatgpt (input: task, contract vote)",
                                    "  3. vote by grok (input: task, contract vote)",
                                    "  pick: tally (code counts the answers; no majority: you pick)",
                                    "  slots: a (stage 1) claude, b (stage 2) chatgpt, c (stage 3) grok"]


# ---------- the refusals (decision 2), each its own sentence ----------

def _with(**changes):
    entry = _vote()
    for i, fields in changes.items():
        stage = entry["stages"][int(i[1:]) - 1]
        for k, v in fields.items():
            if v is None:
                stage.pop(k, None)
            else:
                stage[k] = v
    return entry


def test_the_good_entry_has_no_problem():
    assert _problems(_vote()) == []


@pytest.mark.parametrize("count", [1, 2, 4])
def test_an_even_count_or_fewer_than_three_is_refused(count):
    entry = _vote()
    agents = ["claude", "chatgpt", "grok", "muse"]
    entry["stages"] = [{"n": i, "agent": agents[i - 1], "role": "vote", "input": "task", "contract": "vote"}
                       for i in range(1, count + 1)]
    entry["slots"] = {chr(96 + i): [i] for i in range(1, count + 1)}
    found = _problems(entry)
    assert (f"preset vote has {count} stage{'s' if count > 1 else ''}; a tally needs an odd number of voters, at "
            "least three (two answers are not a vote).") in found


def test_a_stage_that_does_not_get_the_task_alone_is_refused():
    found = _problems(_with(s2={"input": "stage:1"}))
    assert ("preset vote, stage 2 has input 'stage:1'; a vote stage gets the task alone (input 'task'), never "
            "another stage's result.") in found
    found = _problems(_with(s3={"input": None}))
    assert ("preset vote, stage 3 has input None; a vote stage gets the task alone (input 'task'), never "
            "another stage's result.") in found


def test_a_stage_that_is_not_a_vote_is_refused():
    found = _problems(_with(s2={"role": "build"}))
    assert "preset vote, stage 2 has the role 'build'; every stage of a tally preset is a vote." in found


def test_a_stage_without_the_vote_contract_is_refused():
    found = _problems(_with(s1={"contract": None}))
    assert ("preset vote, stage 1 names contract None; a vote stage names vote, which code reads the answer "
            "line from.") in found


def test_a_checker_is_refused():
    entry = {**_vote(), "checker": "chatgpt"}
    assert "preset vote is a tally and names a checker (chatgpt); the tally is the check." in _problems(entry)


def test_a_check_stage_is_refused():
    found = _problems(_with(s3={"is_check": True}))
    assert "preset vote, stage 3 is marked is_check; a tally preset has no check stage." in found


@pytest.mark.parametrize("field, value", [("review_of", 1), ("attack_of", 1), ("revise_of", 1)])
def test_a_review_attack_or_revise_stage_is_refused(field, value):
    found = _problems(_with(s3={field: value}))
    kind = {"review_of": "review", "attack_of": "attack", "revise_of": "revise"}[field]
    assert f"preset vote, stage 3 is a {kind} stage; a tally preset has no review, attack or revise stage." in found


def test_one_agent_in_two_stages_is_refused():
    found = _problems(_with(s2={"agent": "claude"}))
    assert ("preset vote: stages 1 and 2 are both claude; every voter is a different agent (one agent voting twice "
            "is not a vote).") in found


def test_a_preset_that_picks_nothing_reads_no_review_stages_and_no_tally():
    entry = _vote()
    entry.pop("pick")
    assert "preset vote has no checker, no check stage, no review stages and no tally; it needs one of them." \
        in _problems(entry)


def test_a_pick_other_than_tally_on_vote_stages_is_refused():
    entry = {**_vote(), "pick": "claude"}
    assert ("preset vote has pick 'claude' but no review stages; a pick is owner on a preset with review stages, "
            "or tally on a tally preset.") in _problems(entry)


# ---------- slots at intake (rules v2.21, decision 2: on the filled chain) ----------

def _relay(conn, slots, task="Yes or no?"):
    hook, lines, clock = RelayHook(), [], Clock()
    code = cli.cmd_relay("vote", task, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                         settings_paths=[], post=hook.post, worker=Scripted(), chatgpt=Chat(), codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=False,
                         slots=list(slots), out=lines.append)
    return code, "\n".join(lines)


def test_a_reorder_is_accepted():
    filled, refused = presets.slot_refusals(LOADED.presets["vote"], [("a", "grok"), ("b", "claude"), ("c", "chatgpt")],
                                            ROSTER)
    assert refused == []
    assert _problems(presets.as_entry(filled)) == []
    assert [s.agent for s in filled.stages] == ["grok", "claude", "chatgpt"]


def test_two_slots_with_one_agent_are_refused_with_no_row_written(conn):
    code, out = _relay(conn, [("a", "claude"), ("b", "claude")])
    assert code == 2
    assert ("Refused: preset vote: stages 1 and 2 are both claude; every voter is a different agent (one agent "
            "voting twice is not a vote).") in out
    assert "Nothing was logged or sent." in out
    assert log.recent_tasks(conn) == []


def test_a_slot_vote_does_not_have_is_refused(conn):
    code, out = _relay(conn, [("d", "claude")])
    assert code == 2 and "vote has no slot d (its slots: a, b, c)." in out and log.recent_tasks(conn) == []


def test_slot_names_include_c():
    assert "c" in presets.slot_names()


def test_a_vote_slot_flag_on_route_or_split_is_refused(capsys):
    for argv, words in ((["route", "x", "--c", "claude"], "slot flags are for sr relay only (--c on sr route)."),
                        (["split", "x", "--c=grok"], "slot flags are for sr relay only (--c on sr split).")):
        assert cli.main(argv, platform="darwin") == 2
        assert f"Refused: {words} Nothing was logged or sent." in capsys.readouterr().out
