"""Build brief 16, phase B: the redteam contracts (rules v2.23, Relay), checked in code, never by a model.
The attack contract: `## Attacks` with at least 3 numbered items, each `N. [high|medium|low] text` (any case; a list
marker before the number allowed), numbers distinct, and `## Strongest` with exactly one line. The revision contract:
a non-empty deliverable before `## Answered`, and `## Answered` reading none or lines that each start with a number
from the attack list. Every value here is fake."""
import pytest

from router import relay

ATTACKS = """## Attacks
1. [high] The plan never says when the review happens.
2. [Medium] "Triggers a change" is vague.
- 3. [LOW] It is long.

## Strongest
The plan never says when the review happens."""


# ---------- the attack contract ----------

def test_a_good_attack_list_meets_the_contract_and_parses():
    assert relay.attack_list(ATTACKS) == []
    items, strongest = relay.parse_attacks(ATTACKS)
    assert items == [(1, "high", "The plan never says when the review happens."),
                     (2, "medium", '"Triggers a change" is vague.'), (3, "low", "It is long.")]
    assert strongest == "The plan never says when the review happens."


def test_the_item_pattern_accepts_the_three_severities_in_any_case_and_a_list_marker():
    for line in ("1. [high] x", "2) [MEDIUM] y", "- 3. [Low] z", "* 10. [hIgH] w"):
        assert relay.ATTACK_ITEM.match(line), line
    for line in ("1. high x", "1. [critical] x", "1. [] x", "1. [high]", "[high] 1. x"):
        assert not relay.ATTACK_ITEM.match(line), line


@pytest.mark.parametrize("text, words", [
    ("## Strongest\nx", "Attacks: the ## Attacks heading is missing"),
    ("## Attacks\n1. [high] a\n2. [low] b\n## Strongest\nx", "Attacks: need 3 numbered items with a severity, found 2"),
    ("## Attacks\n1. [high] a\n2. [low] b\n3. c has none\n## Strongest\nx",
     "Attacks: item 3 has no severity; start it `3. [high|medium|low]`"),
    ("## Attacks\n1. [high] a\n2. [critical] b\n3. [low] c\n## Strongest\nx",
     "Attacks: item 2 has no severity; start it `2. [high|medium|low]`"),
    ("## Attacks\n1. [high] a\n1. [low] b\n3. [low] c\n## Strongest\nx", "Attacks: item number 1 is used twice"),
    ("## Attacks\n1. [high] a\n2. [low] b\n3. [low] c", "Strongest: the ## Strongest heading is missing"),
    ("## Attacks\n1. [high] a\n2. [low] b\n3. [low] c\n## Strongest\n", "Strongest: need exactly one line, found 0"),
    ("## Attacks\n1. [high] a\n2. [low] b\n3. [low] c\n## Strongest\nx\ny", "Strongest: need exactly one line, found 2"),
])
def test_each_attack_miss_is_named(text, words):
    assert words in relay.attack_list(text)


def test_lines_inside_a_code_fence_are_not_headings_or_items():
    text = "## Attacks\n1. [high] a\n2. [low] b\n```\n## Strongest\n3. [low] c\n```\n3. [low] d\n## Strongest\nx"
    assert relay.attack_list(text) == []
    assert [n for n, _, _ in relay.parse_attacks(text)[0]] == [1, 2, 3]


def test_prose_lines_under_attacks_are_ignored_by_code():
    text = "## Attacks\nHere is what I found.\n1. [high] a\n   more about a\n2. [low] b\n3. [low] c\n## Strongest\nx"
    assert relay.attack_list(text) == []


# ---------- the revision contract ----------

REVISION = "The revised plan.\nSecond line.\n\n## Answered\n3. Length is what the task allows (under 400 words)."


def test_a_good_revision_meets_the_contract_and_splits():
    assert relay.revision(REVISION, ATTACKS) == []
    deliverable, answered = relay.split_answered(REVISION)
    assert deliverable == "The revised plan.\nSecond line."
    assert answered == "3. Length is what the task allows (under 400 words)."


@pytest.mark.parametrize("answered", ["none", "None.", "- none", "**none**"])
def test_answered_may_say_none(answered):
    assert relay.revision(f"The plan.\n\n## Answered\n{answered}", ATTACKS) == []


@pytest.mark.parametrize("text, words", [
    ("The plan only.", "Answered: the ## Answered heading is missing (it may say 'none')"),
    ("## Answered\nnone", "Deliverable: nothing before ## Answered"),
    ("The plan.\n## Answered\n", "Answered: section is empty — write none or list the attacks you reject"),
    ("The plan.\n## Answered\n7. Not relevant.", "Answered: attack 7 is not in the attack list (1, 2, 3)"),
    ("The plan.\n## Answered\nI disagree with most of it.",
     "Answered: each line starts with an attack number; this one doesn't: I disagree with most of it."),
])
def test_each_revision_miss_is_named(text, words):
    assert words in relay.revision(text, ATTACKS)


def test_answered_lines_may_carry_a_list_marker_and_any_number_punctuation():
    assert relay.revision("P.\n## Answered\n- 1. no\n2) no\n3: no", ATTACKS) == []


def test_the_last_answered_heading_outside_a_fence_counts():
    text = "P.\n```\n## Answered\n9. x\n```\n## Answered\n1. fine"
    assert relay.revision(text, ATTACKS) == []
    assert relay.split_answered(text) == ("P.\n```\n## Answered\n9. x\n```", "1. fine")


def test_without_the_attack_list_only_the_shape_is_checked():
    assert relay.revision("P.\n## Answered\n7. x") == []


def test_both_contracts_are_registered_for_presets():
    assert relay.CONTRACTS["attack_list"] is relay.attack_list
    assert relay.CONTRACTS["revision"] is relay.revision
    assert relay.REVISE_CONTRACTS == ("revision",) and relay.ATTACK_CONTRACTS == ("attack_list",)


# ---------- the owner, after #77: the none reader and the wording ----------

@pytest.mark.parametrize("answered", ["none", "None rejected.", "(none rejected)",
                                      "None rejected. The seven missing lines were change notes, not attacks."])
def test_an_answered_section_whose_only_line_starts_with_none_reads_as_none(answered):
    assert relay.revision(f"The plan.\n\n## Answered\n{answered}", ATTACKS) == []


def test_a_numbered_line_plus_none_is_a_contract_miss():
    missing = relay.revision("The plan.\n\n## Answered\n1. Not relevant here.\nnone", ATTACKS)
    assert missing == ["Answered: each line starts with an attack number; this one doesn't: none"]


def test_change_notes_with_no_numbers_are_a_contract_miss():
    notes = "- Dropped speed as a reason to split.\n- Added a cost-based condition.\n- Cut to under 200 words."
    missing = relay.revision(f"The plan.\n\n## Answered\n{notes}", ATTACKS)
    assert len(missing) == 3 and all(m.startswith("Answered: each line starts with an attack number") for m in missing)


def test_none_followed_by_a_sources_line_is_still_a_miss():
    missing = relay.revision("The plan.\n\n## Answered\n(none rejected)\n\nSources: [x](https://example.org)", ATTACKS)
    assert len(missing) == 2


def test_the_check_stage_none_reader_is_unchanged():
    assert relay.says_none("None rejected.") is False and relay.says_none("none") is True


def test_the_revise_reply_and_the_fix_line_say_the_same_thing_about_answered():
    for text in (relay.REVISE_REPLY, relay.REDTEAM_FIX_LINE):
        for words in ("only the attacks you reject", "starting with", "the single word none", "No change notes.",
                      "Sources go in the deliverable, never under `## Answered`."):
            assert words in text, (text, words)
    assert "updated for this fix" not in relay.REDTEAM_FIX_LINE
    prompt = relay.revise_prompt("t", "r", against=ATTACKS)
    assert relay.REVISE_REPLY in prompt and "No change notes." in prompt
