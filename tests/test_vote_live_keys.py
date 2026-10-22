"""Build brief 17, phase E: the answer keys for the live runs, fixed and committed BEFORE any model runs (rule 11).
A model's answer is never used to decide what the right answer was. The tests here check only that the keys are
well formed and that the code reads them as the brief means (no call is made). Every value here is fake or the
brief's own text.

Run 1 key, checked by Claude Code before committing (2026-10-16): Texas's land area is 676,587 to 676,657 km²;
France's whole area with its overseas regions is 643,801 km² (674,843 km² only if Adélie Land in Antarctica is
counted, still under Texas); Spain is the smallest of the three. So "Texas" is right either way France is read."""
from router import checking, log, presets, relay, settings
from router import __main__ as cli
from tests.helpers import shipped_roster

# ---------- Run 1: defaults (a claude, b chatgpt, c grok) ----------
RUN1_TASK = "Which of these is the largest by land area: Texas, France, or Spain? Answer with the name only."
RUN1_SLOTS = ()
RUN1_KEY = "texas"                       # normalised; every voter is expected to give it
RUN1_EXPECTED_SHOW = "Answer: Texas (checked-by-vote 3/0)"
RUN1_PASS = ("the code path ran: three contracts parsed (a re-ask allowed), the tally stored in check_note, "
             "sr show prints the Answer line; a 2/1 is still a pass of the code (paste the dissent)")

# ---------- Run 2: reordered, built to split ----------
RUN2_TASK = ("For a personal budget tracked in a spreadsheet, should categories be fixed at setup or added as "
             "spending happens? Answer: fixed, or as-needed.")
RUN2_SLOTS = (("a", "chatgpt"), ("b", "grok"), ("c", "claude"))
RUN2_ANSWERS = ("fixed", "as-needed")    # normalised; no right answer: a judgment call, built to split
RUN2_OUTCOMES = ("2/1", "1/1/1")         # either is fine; 1/1/1 -> sr pick <n> none; 3/0 is a report line
RUN2_PASS = ("Grok at stage 2 waits; stage 3 (claude) runs only after sr check collects Grok; the tally or the "
             "awaiting pick is stored")

# ---------- Run 3: the word count on a routed task ----------
RUN3_TASK = "Explain in under 60 words why a weekly budget review should be at the same time every week."
RUN3_LABEL = "writing"                   # The owner's flag C: fixed in the driver, so 0 Jev
RUN3_DOER, RUN3_CHECKER = "claude", "chatgpt"
RUN3_COUNT_LINE_TAIL = (' The task\'s own words on length: "Explain in under 60 words why a weekly budget review '
                        'should be at the same time every week."')
RUN3_LIMIT = 60                           # the brief's reading of the task, for the report line only; code never parses it
RUN3_PASS = ("the check prompt carries `The result is N words.` plus the quoted sentence; N by code; the checker's "
             "verdict recorded; a pass over 60 words is a report line, not a brief failure")

BUDGET = {"claude": 4, "chatgpt": 4, "grok": 2, "jev": 0}


def test_run_1_and_2_pass_intake_on_the_shipped_slots_and_limit():
    roster = shipped_roster()
    loaded = presets.load_presets(roster, tuple(cli.SENDERS), relay.CONTRACTS, roles=relay.ROLES,
                                  verdicts=relay.VERDICTS)
    for task, slots in ((RUN1_TASK, RUN1_SLOTS), (RUN2_TASK, RUN2_SLOTS)):
        filled, refused = presets.slot_refusals(loaded.presets["vote"], list(slots), roster)
        assert refused == [] and cli._grok_vote_refusal(filled, task) is None
        assert len(relay.vote_prompt(task)) < settings.grok_prompt_limit()[0]
    filled, _ = presets.slot_refusals(loaded.presets["vote"], list(RUN2_SLOTS), roster)
    assert [s.agent for s in filled.stages] == ["chatgpt", "grok", "claude"]


def test_the_keys_are_what_the_normaliser_reads():
    assert relay.normalise("Texas") == relay.normalise("**Texas.**") == RUN1_KEY
    assert {relay.normalise("Fixed"), relay.normalise("As-needed.")} == set(RUN2_ANSWERS)


def test_run_3s_label_routes_claude_then_chatgpt_and_the_count_line_quotes_the_task():
    import json
    from router import safety
    table = json.loads((safety.REPO_ROOT / "config" / "skill_table.json").read_text())
    skill = table["skills"][RUN3_LABEL]
    assert (skill["best"], skill["second"]) == (RUN3_DOER, RUN3_CHECKER)
    assert checking.count_line(RUN3_TASK, "one two three") == "The result is 3 words." + RUN3_COUNT_LINE_TAIL


def test_the_budget_is_the_briefs():
    assert BUDGET == {"claude": 4, "chatgpt": 4, "grok": 2, "jev": 0}
    assert log.VERSION == 16   # no migration in brief 17; brief 18 added version 11; brief 19 added version 12 (chat, memory); 20 13; 21 14; 22 15; 25 16
