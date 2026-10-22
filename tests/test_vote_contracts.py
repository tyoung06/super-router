"""Build brief 17, phase B (rules v2.24, Relay: tally presets): the vote contract (`## Answer`, one non-empty line;
`## Why`, at least one line; `## Confidence` asked for, never required), the normaliser (decision 5 with the owner's
flag D: surrounding `**`, `*`, `_` and backticks too), the tally (decision 6: a majority is the raw result of the
first stage that gave it; no majority, nothing), the confidence reader, and the vote prompt (decision 4, with
the owner's flag B: the instructions before the TASK block). Code reads all of it; no model decides. Every value here
is fake."""
import pytest

from router import checking, relay


def vote(answer, why="It is the largest.", confidence="85"):
    parts = [f"## Answer\n{answer}", f"## Why\n{why}"]
    if confidence is not None:
        parts.append(f"## Confidence\n{confidence}")
    return "\n\n".join(parts)


# ---------- the contract (decision 3) ----------

def test_a_full_vote_meets_the_contract():
    assert relay.vote(vote("Texas")) == []


def test_confidence_is_never_required():
    assert relay.vote(vote("Texas", confidence=None)) == []
    assert relay.vote(vote("Texas", confidence="very high")) == []


@pytest.mark.parametrize("text, missing", [
    ("## Why\nbecause", ["Answer: the ## Answer heading is missing"]),
    ("## Answer\n\n## Why\nbecause", ["Answer: one line with your answer, found none"]),
    ("## Answer\nTexas\nor France\n\n## Why\nbecause", ["Answer: exactly one line, found 2"]),
    ("## Answer\nTexas", ["Why: the ## Why heading is missing"]),
    ("## Answer\nTexas\n\n## Why\n   \n", ["Why: at least one line, found none"]),
    ("", ["Answer: the ## Answer heading is missing", "Why: the ## Why heading is missing"]),
])
def test_each_miss_is_named(text, missing):
    assert relay.vote(text) == missing


def test_an_answer_heading_inside_a_code_fence_is_not_the_answer():
    assert relay.vote("```\n## Answer\nTexas\n```\n\n## Why\nbecause")[0] == "Answer: the ## Answer heading is missing"


def test_the_answer_line_is_read_raw():
    assert relay.answer_line(vote("  **Texas.**  ")) == "**Texas.**"
    assert relay.answer_line("## Why\nx") is None


def test_the_re_ask_names_what_is_missing_and_asks_for_the_shape_again():
    prompt = relay.reask_prompt("vote", "Which is largest?", "Texas", relay.vote("Texas"))
    assert "- Answer: the ## Answer heading is missing" in prompt and relay.VOTE_SHAPE in prompt
    assert prompt.index(relay.VOTE_SHAPE) < prompt.index("===== TASK =====")


# ---------- the normaliser (decision 5, the owner's flag D) ----------

MATCH = [("Texas", "texas."), ('"Option B"', "option b"), ("The second one", "second one"), ("  Yes!  ", "yes"),
         ("As-needed", "as-needed"),
         # the brief's own
         ("Yes.", "yes"), ('"Option B"', "Option b"), ("The second one", "second one"),
         # flag D
         ("**Texas**", "Texas"), ("*Texas*", "texas"), ("_fixed_", "fixed"), ("`as-needed`", "as-needed"),
         ('**"Texas."**', "texas"), ("**Texas**.", "texas"), ("“Spain”", "spain"), ("fixed;", "Fixed"),
         ("Two   words", "two words"), ("**The second one**", "second one")]
NO_MATCH = [("3", "three"), ("yes, mostly", "yes"), ("Texas (by far)", "Texas"), ("as needed", "as-needed"),
            ("Texas, USA", "Texas"), ("theater", "ater"), ("no", "No way"), ("**Texas", "texas")]


@pytest.mark.parametrize("a, b", MATCH)
def test_these_pairs_match(a, b):
    assert relay.normalise(a) == relay.normalise(b)


@pytest.mark.parametrize("a, b", NO_MATCH)
def test_these_pairs_do_not_match(a, b):
    assert relay.normalise(a) != relay.normalise(b)


def test_nothing_smarter_no_synonyms_or_numbers():
    assert relay.normalise("3") == "3" and relay.normalise("three") == "three"
    assert relay.normalise("The") == "the"  # "the " needs a space after it; a lone word stays


# ---------- the tally (decision 6) ----------

A, B, C = vote("Texas", why="Texas is 695,662 km²."), vote("texas.", why="Bigger."), vote("France", why="No.")


def test_three_agree():
    t = relay.tally([(1, A), (2, B), (3, vote("**Texas**"))])
    assert (t.winner, t.votes_for, t.votes_against, t.dissent) == (1, 3, 0, ())
    assert t.note == "checked-by-vote 3/0"


@pytest.mark.parametrize("order, winner, dissent", [
    ((C, A, B), 2, (1,)),   # the dissent at stage 1: the first agreeing stage is 2
    ((A, C, B), 1, (2,)),
    ((A, B, C), 1, (3,)),
])
def test_two_to_one_with_the_dissent_at_each_place(order, winner, dissent):
    t = relay.tally(list(enumerate(order, 1)))
    assert (t.winner, t.votes_for, t.votes_against, t.dissent) == (winner, 2, 1, dissent)
    assert t.note == "checked-by-vote 2/1"


def test_three_different_answers_have_no_winner():
    t = relay.tally([(1, A), (2, C), (3, vote("Spain"))])
    assert (t.winner, t.dissent) == (None, (1, 2, 3)) and t.note is None


def test_the_result_is_the_first_agreeing_stage_raw_text_not_the_normalised_answer():
    t = relay.tally([(1, C), (2, B), (3, A)])
    assert t.winner == 2
    assert dict([(1, C), (2, B), (3, A)])[t.winner] == B   # "texas." as stage 2 wrote it, Why and all


def test_a_tally_needs_three_votes():
    with pytest.raises(ValueError):
        relay.tally([(1, A), (2, B)])


# ---------- confidence (decision 3) ----------

@pytest.mark.parametrize("value, n", [("85", 85), ("Confidence: 85", 85), ("85/100", 85), ("85%", 85), ("0", 0),
                                      ("100", 100), ("**85**", 85), ("high", None), ("eighty", None), ("120", None),
                                      ("85 or 90", None), ("", None)])
def test_confidence_reads_a_whole_number_from_0_to_100(value, n):
    assert relay.confidence(vote("Texas", confidence=value)) == n


def test_no_confidence_section_is_none():
    assert relay.confidence(vote("Texas", confidence=None)) is None


# ---------- the vote prompt (decision 4, the owner's flags B and D) ----------

def test_the_vote_prompt_puts_every_instruction_before_the_task_block():
    task = "Which is the largest by land area: Texas, France, or Spain? Answer with the name only."
    prompt = relay.vote_prompt(task, search=True)
    at = prompt.index("===== TASK =====")
    for part in (relay.VOTE_SHAPE, checking.SEARCH_LINE_GENERAL, relay.VOTE_DATA_LINE, checking.SCOPE_PARAGRAPH):
        assert prompt.index(part) < at
    assert prompt.endswith(f"===== TASK =====\n{task}\n===== END TASK =====")
    assert "plain text, no formatting" in relay.VOTE_SHAPE
    assert "exact wording of one of them" in relay.VOTE_SHAPE and "## Why" in relay.VOTE_SHAPE
    assert "## Confidence" in relay.VOTE_SHAPE and "0 to 100" in relay.VOTE_SHAPE


def test_without_search_there_is_no_search_line():
    assert checking.SEARCH_LINE_GENERAL not in relay.vote_prompt("Yes or no?")


def test_the_vote_role_and_contract_are_registered():
    assert "vote" in relay.ROLES and relay.CONTRACTS["vote"] is relay.vote
    assert relay.prompt_for("vote", "Yes or no?", None, search=False, task_alone=True) == relay.vote_prompt("Yes or no?")
