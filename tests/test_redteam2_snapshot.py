"""Build brief 32 (Tests, Prompts): every redteam prompt this brief doesn't change holds byte for byte, and the ones it
changes have new snapshots. An old task's run today (presets 1.6, one list) gives `main`'s prompts at c030f8e byte for
byte (tests/fixtures/redteam_prompts_v1_6.json, recorded there by tests/redteam_snapshot.py). A run with both lists
gives tests/fixtures/redteam_prompts_v1_7.json, recorded on this brief's code: the second attack's own prompt and the
revise, check, fix, re-check and fallback redo and check with both lists labeled. With the second attack left out the
run gives tests/fixtures/redteam_prompts_v1_7_one_list.json, whose label example names list A only (the design chat's D
fix of 29 Oct). Brief 33 (decision 5): the three prompts whose result can be delivered (the revise stage, its fix round
and the fallback's redo) now end with the `## Next` line, and every other prompt holds byte for byte. Every value here is
fake."""
import json
from pathlib import Path

from router import __main__ as cli
from router import checking, presets, relay
from tests import redteam_snapshot
from tests.helpers import shipped_roster
from tests.test_cursor_send import Cursor, Ready, answer

FIXTURES = Path(__file__).parent / "fixtures"


def _loaded(path=None):
    return presets.load_presets(shipped_roster(), tuple(cli.SENDERS), relay.CONTRACTS, roles=relay.ROLES,
                                verdicts=relay.VERDICTS, path=path)


NEXT_TAIL = "\n\n" + checking.NEXT_LINE


def _with_next(recorded):
    """Brief 33 (decision 5): a recorded run as it is sent now. Claude's second prompt (the revise stage), its third (the
    fix round) and, in the fallback, ChatGPT's first (the redo) each end with the `## Next` line; nothing else moves."""
    for run in recorded.values():
        for i in (1, 2):
            run["claude"][i] += NEXT_TAIL
        if "fallback" in run:
            run["fallback"]["chatgpt"][0] += NEXT_TAIL
    return recorded


def two_lists():
    """The run with presets 1.7's second attack: a fresh fake Cursor per run, answering the second list."""
    return redteam_snapshot.snapshot(_loaded(), cursor=lambda: Cursor(answer(redteam_snapshot.B_LIST)), cursor_ready=Ready())


def one_list():
    """Presets 1.7 with the second attack left out (Cursor not ready): one labeled list, answered by label."""
    return redteam_snapshot.snapshot(_loaded(), cursor=lambda: Cursor(answer(redteam_snapshot.B_LIST)),
                                     cursor_ready=Ready((False, "cursor: not signed in (agent login)")),
                                     words=redteam_snapshot.ONE_LABELED)


def _prompts(found):
    for run in found.values():
        for who in ("claude", "chatgpt", "cursor"):
            yield from run.get(who, [])
        for who in ("claude", "chatgpt"):
            yield from run.get("fallback", {}).get(who, [])


def test_an_old_tasks_prompts_are_mains_at_c030f8e_byte_for_byte():
    assert redteam_snapshot.snapshot(_loaded(FIXTURES / "presets_v1_6.json")) == _with_next(json.loads(
        (FIXTURES / "redteam_prompts_v1_6.json").read_text()))


def test_the_two_list_prompts_are_their_snapshot_byte_for_byte():
    found = two_lists()
    assert found == _with_next(json.loads((FIXTURES / "redteam_prompts_v1_7.json").read_text()))
    rows = [tuple(r[:4]) for r in found["fixed"]["rows"]]
    assert rows[:4] == [("stage", 1, "build", "claude"), ("stage", 2, "attack", "chatgpt"), ("stage", 3, "attack", "cursor"),
                        ("stage", 4, "revise", "claude")]


def test_what_the_two_list_snapshot_holds():
    found = json.loads((FIXTURES / "redteam_prompts_v1_7.json").read_text())
    run = found["fallback"]
    attack_a, attack_b = run["chatgpt"][0], run["cursor"][0]
    assert redteam_snapshot.A_LIST not in attack_b and redteam_snapshot.BUILD in attack_b  # the build alone
    revise, check, fix, recheck = run["claude"][1], run["chatgpt"][1], run["claude"][2], run["chatgpt"][2]
    for prompt in (revise, check, fix, recheck, run["fallback"]["chatgpt"][0], run["fallback"]["claude"][0]):
        assert "A1 1. [high] No trigger for a change is defined." in prompt, prompt[:300]
        assert "B1 1. [high] Nothing says who reviews when the owner is away." in prompt, prompt[:300]
    assert attack_a.count("## Attacks") == attack_b.count("## Attacks")


# ---------- one list (the design chat's D fix of 29 Oct, item 4) ----------

def test_with_one_list_the_label_example_names_list_a_only():
    found = one_list()
    assert [tuple(r[:4]) for r in found["fixed"]["rows"]][:3] == [
        ("stage", 1, "build", "claude"), ("stage", 2, "attack", "chatgpt"), ("stage", 3, "revise", "claude")]
    with_lists = [p for p in _prompts(found) if "===== ATTACK LIST A" in p]
    assert with_lists and found["fixed"]["cursor"] == [] and found["fallback"]["cursor"] == []
    for prompt in with_lists:
        assert "ATTACK LIST B" not in prompt and "B2" not in prompt and "B1" not in prompt
    explained = [p for p in with_lists if "its label (" in p]
    assert len(explained) >= 4 and all("its label (A1, A2)" in p for p in explained)
    assert any("`A1, A2: …`" in p for p in with_lists)


def test_with_two_lists_the_label_example_names_both():
    explained = [p for p in _prompts(two_lists()) if "its label (" in p]
    assert explained and all("its label (A1, B2)" in p for p in explained)


def test_the_one_list_prompts_are_their_snapshot_byte_for_byte():
    assert one_list() == _with_next(json.loads((FIXTURES / "redteam_prompts_v1_7_one_list.json").read_text()))


def test_the_answered_contract_line_names_list_a_only_with_one_list():
    a = relay.AttackList(2, "chatgpt", "A", items=(relay.AttackItem("A1", 1, "high", "x"),))
    b = relay.AttackList(3, "cursor", "B", items=(relay.AttackItem("B1", 1, "high", "y"),))
    one = relay.revision("The plan.\n\n## Answered\nSunday is fine.", (a,))
    two = relay.revision("The plan.\n\n## Answered\nSunday is fine.", (a, b))
    assert one == ["Answered: each line starts with an attack's label (A1, A2); this one doesn't: Sunday is fine."]
    assert two == ["Answered: each line starts with an attack's label (A1, B2); this one doesn't: Sunday is fine."]
