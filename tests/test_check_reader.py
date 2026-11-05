"""Brief 29.1 (decisions 14, 15 and 17; the owner's D20, the checker's fixes 1, 2 and 6): code reads a check. First line
exactly PASS, FIX or BLOCKED; after PASS or FIX a numbered list, one item per line, each `[must]` or `[note]`. Code's
reading wins: any must is FIX whatever the first line says, a FIX with no must is PASS with notes; an item with no tag is a
note after PASS, and after FIX a must unless it is only a source link (D's issue D4, the owner, 28 Oct). A re-check gives one line per first-list must, `fixed` or `not fixed: …`, then only a new must the revision made:
FIX when any must is not fixed or a new must is listed, else PASS; a first-list must with no line gets the one re-ask,
then reads unreadable. BLOCKED ends the task with no fix round (ending 9). Pure; every value fake."""
import pytest

from router import checking, log


# ---------- the first check ----------

@pytest.mark.parametrize("text, verdict, items", [
    ("PASS", "PASS", []),
    ("PASS\n1. [note] The second line could be shorter.", "PASS", [(1, "note", "The second line could be shorter.")]),
    ("FIX\n1. [must] The year is 2023, not 2024.\n2. [note] Tighten line two.", "FIX",
     [(1, "must", "The year is 2023, not 2024."), (2, "note", "Tighten line two.")]),
    ("FIX\n1. [note] wording only", "PASS", [(1, "note", "wording only")]),        # a FIX with no must: PASS with notes
    ("PASS\n1. [must] The date is wrong.", "FIX", [(1, "must", "The date is wrong.")]),  # any must: FIX
    ("FIX\n1. Add the year.", "FIX", [(1, "must", "Add the year.")]),               # no tag: a must
    ("**FIX**\n\n1. **[Must]** the total is off\n   by two\n2) [NOTE] style", "FIX",
     [(1, "must", "the total is off by two"), (2, "note", "style")]),               # wrappers, a continuation line
    ("FIX: add the source link", "FIX", [(1, "must", "add the source link")]),      # today's one-line fix list
    ("FIX\n- line 1 is too long\n- [note] no garden word", "FIX",
     [(1, "must", "line 1 is too long"), (2, "note", "no garden word")]),           # a bullet list: each bullet an item
    ("pass\n\nLooks complete to me.", "PASS", []),                                  # free words after PASS: no item
    ("FIX", "unreadable", []),
    ("Verdict: PASS", "unreadable", []),
    ("", "unreadable", []),
    (None, "unreadable", []),
])
def test_the_reader_reads_the_verdict_and_the_items(text, verdict, items):
    found = checking.read_check(text)
    assert found.verdict == verdict
    assert [(i.n, i.tag, i.text) for i in found.items] == items


def test_the_first_lines_word_is_kept_beside_codes_reading():
    found = checking.read_check("FIX\n1. [note] wording only")
    assert (found.said, found.verdict) == ("FIX", "PASS")
    assert not checking.read_check("FIX\n1. Add the year.").items[0].tagged


@pytest.mark.parametrize("text, what", [
    ("BLOCKED: the notes from yesterday's meeting", "the notes from yesterday's meeting"),
    ("BLOCKED\nThe meeting notes the email draws on.", "The meeting notes the email draws on."),
    ("**Blocked**\n\n- the router's own README details", "the router's own README details"),
])
def test_blocked_names_what_the_doer_needed(text, what):
    found = checking.read_check(text)
    assert (found.verdict, found.blocked) == ("BLOCKED", what) and found.items == ()


def test_read_verdict_keeps_its_two_values_for_every_caller():
    assert checking.read_verdict("FIX\n1. Add the year.") == ("FIX", "1. Add the year.")
    assert checking.read_verdict("PASS\n1. [note] x") == ("PASS", None)
    assert checking.read_verdict("BLOCKED: the notes")[0] == "BLOCKED"
    assert set(log.VERDICTS) == {"PASS", "FIX", "BLOCKED", "unreadable"}


# ---------- the re-check ----------

FIRST = checking.read_check("FIX\n1. [must] The year is wrong.\n2. [note] Tighten it.\n3. [must] No source link.")


@pytest.mark.parametrize("text, verdict, states, new", [
    ("PASS\n1. fixed\n3. fixed", "PASS", {1: "fixed", 3: "fixed"}, []),
    ("PASS\n1. fixed\n3. not fixed: still no link", "FIX", {1: "fixed", 3: "not_fixed"}, []),     # code's reading wins
    ("FIX\n1. fixed\n3. fixed\n4. [must] The new line contradicts line one.", "FIX", {1: "fixed", 3: "fixed"},
     [(4, "must", "The new line contradicts line one.")]),
    ("FIX\n1. fixed\n3. fixed\n4. [note] Could be shorter.", "PASS", {1: "fixed", 3: "fixed"},
     [(4, "note", "Could be shorter.")]),
    ("PASS\n- 1: Fixed.\n- **3.** Not fixed — the link is dead", "FIX", {1: "fixed", 3: "not_fixed"}, []),
])
def test_the_recheck_reads_one_line_per_first_list_must(text, verdict, states, new):
    found = checking.read_recheck(text, FIRST)
    assert found.verdict == verdict and found.missing == ()
    assert {i.n: i.state for i in found.lines} == states
    assert [(i.n, i.tag, i.text) for i in found.items] == new


def test_a_first_list_must_with_no_line_is_missing_and_reads_unreadable():
    found = checking.read_recheck("PASS\n1. fixed", FIRST)
    assert found.missing == (3,) and found.verdict == "unreadable"
    assert checking.read_recheck("PASS", FIRST).missing == (1, 3)


def test_a_blocked_recheck_is_read_before_its_lines():
    found = checking.read_recheck("BLOCKED: the client's email address", FIRST)
    assert (found.verdict, found.blocked, found.missing) == ("BLOCKED", "the client's email address", ())


def test_the_first_list_as_the_recheck_reads_it():
    assert checking.first_list(FIRST) == "1. [must] The year is wrong.\n2. [note] Tighten it.\n3. [must] No source link."
    old = checking.read_check("FIX\n1. Add the year.\n2. Give the source.")  # a list from before: every item a must
    assert checking.first_list(old) == "1. [must] Add the year.\n2. [must] Give the source."


# ---------- the loop ----------

@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _task(conn):
    from tests.test_checking import ALL_AGENTS, JEV_OK, TASK
    log.add_task(conn, "sr-1", TASK, "cli", JEV_OK)
    log.set_route(conn, "sr-1", agents=ALL_AGENTS, agent="claude", route_reason="best", skill="writing", skill_source="jev",
                  checker="chatgpt", check_state="pending")
    log.add_call(conn, "sr-1", "sr-1", "do", "claude", status="done", text="The result.")


def _call(conn, call_id, kind, text, agent="chatgpt"):
    calls = log.calls_for(conn, "sr-1")
    log.add_call(conn, call_id, "sr-1", kind, agent, status="done", text=text,
                 verdict=checking.verdict_for(kind, text, calls) if kind in ("check", "recheck") else None)


def _step(conn):
    return checking.next_step(log.get_task(conn, "sr-1"), log.calls_for(conn, "sr-1"))


def test_the_endings_gain_blocked():
    assert checking.ENDINGS[9] == ("blocked", 5)


def test_a_blocked_check_ends_the_task_with_no_fix_round(conn):
    _task(conn)
    _call(conn, "sr-1-c1", "check", "BLOCKED: the meeting notes")
    step = _step(conn)
    assert (step.action, step.ending, step.blocked) == ("finish", 9, "the meeting notes")
    assert step.check_state == "blocked" and step.exit_code == 5


def test_a_fix_with_notes_only_passes_and_the_fix_round_gets_the_musts_and_notes_apart(conn):
    _task(conn)
    _call(conn, "sr-1-c1", "check", "FIX\n1. [note] wording")
    assert (_step(conn).action, _step(conn).ending) == ("finish", 3)


def test_the_fix_step_carries_the_first_checks_reading(conn):
    _task(conn)
    _call(conn, "sr-1-c1", "check", "FIX\n1. [must] The year is wrong.\n2. [note] Tighten it.")
    step = _step(conn)
    assert step.action == "fix"
    assert [i.text for i in step.reading.musts] == ["The year is wrong."]
    assert [i.text for i in step.reading.notes] == ["Tighten it."]


def test_a_recheck_missing_a_line_gets_one_re_ask_then_reads_unreadable(conn):
    _task(conn)
    _call(conn, "sr-1-c1", "check", "FIX\n1. [must] The year is wrong.\n2. [must] No link.")
    _call(conn, "sr-1-f1", "fix", "The fixed result.", agent="claude")
    _call(conn, "sr-1-c2", "recheck", "PASS\n1. fixed")
    step = _step(conn)
    assert (step.action, step.missing) == ("recheck", (2,))
    _call(conn, "sr-1-c2r", "recheck", "PASS\n1. fixed")
    step = _step(conn)
    assert (step.action, step.ending) == ("finish", 7)


def test_a_recheck_with_every_line_decides_by_the_lines(conn):
    _task(conn)
    _call(conn, "sr-1-c1", "check", "FIX\n1. [must] The year is wrong.")
    _call(conn, "sr-1-f1", "fix", "The fixed result.", agent="claude")
    _call(conn, "sr-1-c2", "recheck", "PASS\n1. not fixed: still 2024")
    step = _step(conn)
    assert (step.action, step.ending) == ("finish", 8)
    assert log.calls_for(conn, "sr-1")[-1]["verdict"] == "FIX"  # the row records code's reading


def test_a_blocked_recheck_ends_blocked(conn):
    _task(conn)
    _call(conn, "sr-1-c1", "check", "FIX\n1. [must] The year is wrong.")
    _call(conn, "sr-1-f1", "fix", "The fixed result.", agent="claude")
    _call(conn, "sr-1-c2", "recheck", "BLOCKED: the census table")
    assert (_step(conn).ending, _step(conn).blocked) == (9, "the census table")


# ---------- D's issue D4 (the owner, 28 Oct): an untagged item after PASS is a note; after FIX, a link alone is a note --

# #145's shape, every value fake: PASS, three tagged notes, then a "Sources:" list of bullets that are only links, and a
# word-count line; its re-check: PASS, a line per first-list must, then "Notes:" and numbered lines with no tag
CHECK_145 = ("PASS\n"
             "1. [note] The result names three seed swaps, one line each, as the task asked.\n"
             "2. [note] I couldn't open the cited listing pages, so their hours are unchecked.\n"
             "3. [note] Each line gives only a street. That's thin but fits \"one line each\".\n\n"
             "Sources:\n"
             "- [Maple Street swap listing](https://example.org/swaps/maple)\n"
             "- [Library garden calendar](https://example.org/library/calendar)\n\n"
             "Word count: 23")
RECHECK_145 = ("PASS\n1. fixed\n2. fixed\n\nNotes:\n"
               "3. I didn't open the two links or run new searches.\n"
               "4. The lines give only a street, with no word on the swaps. Thin, but it fits \"one line each\".\n\n"
               "Word count: the result is 23 words.")
FIRST_145 = checking.read_check("FIX\n1. [must] Name each swap's day.\n2. [must] Give each swap's street.")


def test_after_pass_an_untagged_item_is_a_note_so_145s_check_passes():
    found = checking.read_check(CHECK_145)
    assert (found.said, found.verdict) == ("PASS", "PASS")
    assert [(i.n, i.tag, i.tagged) for i in found.items] == [
        (1, "note", True), (2, "note", True), (3, "note", True), (4, "note", False), (5, "note", False)]
    assert found.items[3].text == "[Maple Street swap listing](https://example.org/swaps/maple)"
    assert checking.read_check("PASS\n1. Shorter lines would read better.").items[0].tag == "note"


def test_after_pass_a_recheck_s_untagged_new_items_are_notes_so_145s_recheck_passes():
    found = checking.read_recheck(RECHECK_145, FIRST_145)
    assert (found.verdict, found.missing) == ("PASS", ())
    assert {i.n: i.state for i in found.lines} == {1: "fixed", 2: "fixed"}
    assert [(i.n, i.tag) for i in found.items] == [(3, "note"), (4, "note")]


@pytest.mark.parametrize("text, verdict, items", [
    ("FIX\n1. [must] Name the day.\n2. [Swap listing](https://example.org/swaps)\n3. https://example.org/calendar\n"
     "4. <https://example.org/map>\n5. Give the street too.", "FIX",
     [(1, "must"), (2, "note"), (3, "note"), (4, "note"), (5, "must")]),           # a link alone a note, words a must
    ("FIX\n1. [note] Wording only.\n- [a](https://example.org/a), [b](https://example.org/b)", "PASS",
     [(1, "note"), (2, "note")]),                                                  # links only: still no must
    ("FIX\n1. See [the listing](https://example.org/swaps) for the day.", "FIX", [(1, "must")]),  # words and a link
    ("FIX\n1. Add the year.", "FIX", [(1, "must")]),                                # words alone: a must, as before
])
def test_after_fix_an_untagged_item_that_is_only_a_link_is_a_note(text, verdict, items):
    found = checking.read_check(text)
    assert found.verdict == verdict
    assert [(i.n, i.tag) for i in found.items] == items


def test_a_fix_recheck_reads_a_link_alone_as_a_note_and_words_as_a_must():
    found = checking.read_recheck("FIX\n1. fixed\n2. fixed\n3. [Street map](https://example.org/map)\n"
                                  "4. The new line repeats line one.", FIRST_145)
    assert found.verdict == "FIX" and [(i.n, i.tag) for i in found.items] == [(3, "note"), (4, "must")]
