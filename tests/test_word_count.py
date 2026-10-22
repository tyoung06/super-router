"""Build brief 17, Phase W (rules v2.24, Checking: "The word count is code's."). The router counts the deliverable's
words by code (the text before the first `## Missing`, `## Answered`, `## Unfinished` or `## Handoff` heading) and
gives every check, re-check and fix round the count on one line, with the task's own sentences about length quoted,
never parsed into a number. The owner's flag A: the line goes before the blocks, so a cut in delivery never drops it.
Not on a versus review, a vote stage, a revise stage or a contract re-ask. Every value here is fake."""
import pytest

from router import checking, log, relay
from tests.helpers import count_lines_in
from tests.test_loop import Scripted
from tests.test_relay import GOOD_NOTE, Chat, RelayHook

RULE = checking.LENGTH_RULE_LINE


# ---------- the counter (decision 15, the owner's choice 6) ----------

@pytest.mark.parametrize("text, n", [
    ("Review the budget every Sunday at six.", 7),
    ("", 0),
    (None, 0),
    ("   \n\n  ", 0),
])
def test_plain_text_and_empty(text, n):
    assert checking.word_count(text) == n


def test_markdown_headings_bullets_and_emphasis_are_stripped_not_counted():
    md = "# Plan\n\n## Steps\n- **Check** the *rent*\n* Check `food`\n+ Check fun\n> Keep it short\n1. Sum it\n2) Done"
    plain = "Plan Steps Check the rent Check food Check fun Keep it short Sum it Done"
    assert checking.word_count(md) == checking.word_count(plain) == 15


@pytest.mark.parametrize("note", ["## Missing", "## Answered", "## Unfinished", "## Handoff", "# missing", "## Answered:"])
def test_a_note_section_and_everything_after_it_is_not_counted(note):
    text = f"One two three.\n\n{note}\nfour five six seven\n\n## Later\neight"
    assert checking.word_count(text) == 3


def test_the_first_note_heading_cuts_even_when_a_later_heading_is_not_a_note():
    assert checking.word_count("a b\n## Unfinished\nnone\n## Missing\nx y z") == 2


def test_a_level_three_heading_named_missing_does_not_cut():
    assert checking.word_count("a b\n### Missing\nc") == 4  # "Missing" is a word of the deliverable here


def test_a_redteam_revision_counts_only_the_text_before_answered():
    text = "Line one here.\nLine two.\n\n## Answered\n3. Sunday is the user's choice."
    assert checking.word_count(text) == 5


def test_a_code_fence_counts_its_words_but_not_its_fence_lines():
    # Code is words too: a result that is code is judged on the same count a reader would make.
    text = "Run this:\n```python\nprint('hello world')\n```\nDone."
    assert checking.word_count(text) == 5  # Run, this:, print('hello, world'), Done.


def test_a_note_heading_inside_a_code_fence_does_not_cut():
    assert checking.word_count("a\n```\n## Missing\nb c\n```\nd") == 5  # a, Missing (its # stripped), b, c, d


@pytest.mark.parametrize("text, n", [
    ("well-known", 1),
    ("$15", 1),
    ("6:00 PM", 2),
    ("https://example.com/a-b?c=d", 1),
    ("a — b", 2),
    ("| a | b |", 2),
    ("U.S.", 1),
    ("1,000", 1),
    ("don't", 1),
    ("café crème", 2),
    ("--- ***", 0),
])
def test_the_edge_rules(text, n):
    assert checking.word_count(text) == n


def test_the_same_text_always_gives_the_same_count():
    text = "## Deliverable\n- one\n- two-three\n\n```\nx = 1\n```\n\n## Unfinished\nnone"
    assert len({checking.word_count(text) for _ in range(5)}) == 1
    assert checking.word_count(text) == 5  # Deliverable, one, two-three, x, 1 ("=" has no letter or digit)


# ---------- the task's own words on length ----------

def test_the_whole_sentence_with_a_length_word_is_quoted():
    task = "Write a plan for a weekly budget review. Plain text, under 400 words. Use bullets."
    assert checking.length_sentences(task) == ["Plain text, under 400 words."]


@pytest.mark.parametrize("word", ["word", "words", "page", "sentence", "sentences", "paragraph", "paragraphs",
                                  "line", "lines", "WORDS", "Pages"])
def test_every_length_word_counts_in_any_case(word):
    assert checking.length_sentences(f"Explain it. Keep it to one {word}.") == [f"Keep it to one {word}."]


@pytest.mark.parametrize("task", ["Explain why a weekly review helps.", "Meet the deadline and follow the guidelines.",
                                  "Write online copy."])
def test_no_length_word_means_no_phrase(task):
    assert checking.length_sentences(task) == []


def test_two_sentences_and_a_newline_split():
    task = "Two pages at most!\nThen a summary of three lines? Thanks."
    assert checking.length_sentences(task) == ["Two pages at most!", "Then a summary of three lines?"]


def test_the_count_line_with_and_without_the_tasks_words():
    assert checking.count_line("Explain it.", "a b c") == "The result is 3 words."
    assert checking.count_line("Explain it in under 60 words.", "a b") == (
        'The result is 2 words. The task\'s own words on length: "Explain it in under 60 words."')
    assert checking.count_line("Explain.", "") == "The result is 0 words."
    assert checking.count_line("A. Two pages. One line.", "x") == (
        'The result is 1 word. The task\'s own words on length: "Two pages." "One line."')


# ---------- every surface that gives a verdict (decision 16) ----------

def _before_blocks(prompt, line):
    """The line is there once, before the first block (the owner's flag A)."""
    assert prompt.count(line) == 1, prompt
    assert prompt.index(line) < prompt.index("===== TASK =====")


def test_routed_prompts_by_kind(conn):
    from tests.test_resume_run import WRITING, _route
    task = "Write two lines about seed trays, under 20 words."
    first, fixed = "Trays stand tall.\nDrive on.", "Trays stand tall at dawn.\nThe first drive flies."
    worker, chat = Scripted(first, fixed), Chat("FIX\n1. Longer.", "PASS")
    _route(conn, WRITING, worker=worker, chatgpt=chat, task=task)
    check, recheck = chat.prompts
    fix = worker.prompts[1]
    phrase = ' The task\'s own words on length: "Write two lines about seed trays, under 20 words."'
    _before_blocks(check, "The result is 5 words." + phrase)
    _before_blocks(recheck, "The result is 9 words." + phrase)
    _before_blocks(fix, "The result is 5 words." + phrase)
    assert RULE in check and RULE in recheck
    assert RULE not in fix  # the fix round gets the count line only
    assert "The result is" not in worker.prompts[0]  # the doer's first call is no check


def test_a_research_build_check(conn):
    from tests.test_resume_run import _relay
    worker, chat = Scripted("A built result in five words."), Chat("PASS")
    _relay(conn, "research-build", "Summarise the note.", worker=worker, chatgpt=chat, hook=RelayHook(s1=GOOD_NOTE))
    _before_blocks(chat.prompts[0], "The result is 6 words.")
    assert RULE in chat.prompts[0]
    assert "The result is" not in worker.prompts[0]  # the build stage is no check


def test_a_collab_check_stage_counts_the_deliverable_before_unfinished(conn):
    from tests.test_collab import AMENDED, DELIVERABLE, EDITED, PLAN, _relay
    code, out, row, worker, chat = _relay(conn, claude=(PLAN, DELIVERABLE), chatgpt=(AMENDED, EDITED))
    edit = chat.prompts[1]
    n = checking.word_count(DELIVERABLE)
    assert n == checking.word_count(DELIVERABLE.split("## Unfinished")[0])
    assert edit.count(f"The result is {n} words.") == 1 and RULE in edit
    assert edit.index(f"The result is {n} words.") < edit.index("===== DELIVERABLE =====")
    assert "The result is" not in chat.prompts[0] and "The result is" not in worker.prompts[1]  # amend, execute


def test_a_redteam_check_counts_only_before_answered_and_the_revise_stage_has_no_line(conn):
    from tests.test_redteam_chain import ATTACKS, BUILD, REVISION, _relay
    code, out, row, worker, chat = _relay(conn, claude=[BUILD, REVISION], chat=[ATTACKS, "PASS"])
    check = chat.prompts[1]
    n = checking.word_count(REVISION.split("\n\n## Answered")[0])
    _before_blocks(check, f'The result is {n} words. The task\'s own words on length: '   # "one-page" is a length word
                          '"Write a one-page plan for a weekly budget review ritual." "Plain text, under 400 words."')
    assert "The result is" not in worker.prompts[1]  # the revise stage reuses fix_prompt, but is no fix round
    assert "The result is" not in chat.prompts[0]    # the attack stage


def test_a_redteam_fix_round_carries_the_line(conn):
    from tests.test_redteam_chain import ATTACKS, BUILD, REVISION, _relay
    fixed = REVISION.replace("6pm", "6pm sharp")
    code, out, row, worker, chat = _relay(conn, claude=[BUILD, REVISION, fixed], chat=[ATTACKS, "FIX\n1. x", "PASS"])
    fix = worker.prompts[2]
    n = checking.word_count(REVISION)
    assert fix.count(f"The result is {n} words.") == 1
    assert fix.index(f"The result is {n} words.") < fix.index("===== TASK =====")


def test_a_split_integration_check(conn):
    from tests.test_split_integrate import JOINED, PLAN, R1, R2, TASK, _run
    code, env = _run(conn, (PLAN, R1, R2, JOINED), ("PASS", "PASS", "PASS"))
    integration_check = env.chat.prompts[-1]
    _before_blocks(integration_check, f"The result is {checking.word_count(JOINED)} words.")
    assert JOINED in integration_check


def test_a_fallback_check(conn):
    from tests.test_fallback_run import REDO, _double_fail_route, _fallback
    row = _double_fail_route(conn)
    code, out, after, worker, chat, hook = _fallback(conn, row, chatgpt=Chat(REDO), worker=Scripted("PASS"))
    _before_blocks(worker.prompts[0], f"The result is {checking.word_count(REDO)} words.")
    assert "The result is" not in chat.prompts[0]  # the redo is no check


def test_a_versus_review_has_no_count_line(conn):
    review = relay.prompt_for("review", "Write a tagline, under 8 words.", "A tagline.")
    assert "The result is" not in review and RULE not in review


def test_a_contract_re_ask_has_no_count_line():
    prompt = relay.reask_prompt("revise", "Under 400 words.", "x", ["Answered: missing"])
    assert "The result is" not in prompt


def test_with_no_length_words_the_prompt_is_the_old_one_plus_the_rule_and_the_count():
    old_free = checking.checker_prompt("Explain trays.", "a b", no_tools=True)
    stripped, removed = count_lines_in(old_free)
    assert removed == 2
    assert "The task's own words" not in old_free and "The result is 2 words." in old_free


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()
