"""Brief 29.1 (decisions 14 to 20; the checker's fixes 1 to 6): every new line where the decisions put it and nowhere
else. The check: the judge line's must rule, the must and note paragraph, the unverified line, the no-result rule with
BLOCKED, the router's facts filled in from the doer's call row, the new reply format and the length targets; the re-check:
the FIRST CHECK block after the result, its line and format, and its one re-ask; the fix round: the musts and notes in
their own blocks, the facts' first two sentences, the unverified fix line and the deliverable line; every doer, build and
fix prompt that returns the deliverable gets the deliverable line (collab's execute and redteam's build its `## Unfinished`
form), and nothing else does; every call with a memory block gets the memory line right before it. Pure; every value
fake."""
import pytest

from router import __main__ as cli
from router import checking, context, log, presets, relay, search, split
from tests.helpers import ALL_AGENTS, shipped_roster
from tests.helpers import less_next

TASK = "Name three seed trays for a small garden, in under 60 words."
RESULT = "Tray one. Tray two. Tray three."
FIRST = "FIX\n1. [must] Tray two is not sold any more.\n2. [note] Name the sizes."
ROSTER = shipped_roster()
LOADED = presets.load_presets(ROSTER, tuple(cli.SENDERS), relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _routed(conn, task_id="sr-1", agent="claude", checker="chatgpt"):
    log.add_task(conn, task_id, TASK, "cli", {"status": "ok", "label": "writing", "confidence": 0.9})
    log.set_route(conn, task_id, agents=ALL_AGENTS, agent=agent, route_reason="best", skill="writing",
                  checker=checker, check_state="pending")
    return log.get_task(conn, task_id)


def _plan(conn, row, step, searching=search.OFF_PROBE):
    return cli._plan_call(row, step, log.calls_for(conn, row["task_id"]), searching=searching)


def _before_task(prompt, line):
    """The line is in the prompt once, as its own paragraph, before the TASK block."""
    assert prompt.count(line) == 1, line[:60]
    assert prompt.index(line) < prompt.index("===== TASK =====")


# ---------- the first check (decisions 14, 16, 17, 18) ----------

def test_the_check_carries_every_new_line_before_the_blocks():
    prompt = checking.checker_prompt(TASK, RESULT, no_tools=False)
    for line in (checking.CHECK_JUDGE_LINE, f"{checking.MUST_NOTE_LINE} {checking.ONE_LIST_LINE}",
                 checking.UNVERIFIED_CHECK_LINE, checking.NO_RESULT_RULE, checking.facts_line(False, False),
                 checking.REPLY_FORMAT, checking.CHECK_LENGTH_LINE):
        _before_task(prompt, line)
    assert "Ask for a fix only for those problems" not in prompt and "exactly PASS or FIX." not in prompt
    assert checking.LENGTH_RULE_LINE not in prompt and checking.RECHECK_LINE not in prompt
    order = [prompt.index(x) for x in (checking.CHECK_JUDGE_LINE, checking.MUST_NOTE_LINE, checking.UNVERIFIED_CHECK_LINE,
                                       checking.NO_RESULT_RULE, checking.FACTS_LEAD, checking.REPLY_FORMAT,
                                       checking.CHECK_LENGTH_LINE)]
    assert order == sorted(order)


def test_the_words_are_the_design_chats():
    assert checking.CHECK_JUDGE_LINE.endswith("Style and wording are never a [must].")
    assert "reply BLOCKED and name what it needed in one line. Otherwise reply FIX and say what is missing." in \
        checking.NO_RESULT_RULE
    assert checking.CHECK_MEMORY_LINE.count("that is a [must]; name the memory by its task number.") == 1
    assert "In your list, name the attack by its number." in checking.REDTEAM_CHECK_LINE
    assert checking.CHECK_HANDOFF_LINE.startswith("The result ends with a `## Handoff` section, a note for the next task.")
    assert '"An N-word X" or "about N words" is a target: within 10% of N meets it.' in checking.CHECK_LENGTH_LINE
    assert checking.CHECK_LENGTH_LINE.startswith(checking.LENGTH_RULE_LINE.split(": a result over")[0])


@pytest.mark.parametrize("could, copy, words", [
    (False, False, "The doer had only the task and the blocks in this prompt; it could not search the web;"),
    (True, False, "The doer had only the task and the blocks in this prompt; it could search the web;"),
    (True, True, "The doer had only the task and the blocks in this prompt, and a copy of the project's files; it could "
                 "search the web;"),
])
def test_the_router_facts_are_filled_in(could, copy, words):
    full = checking.facts_line(could, copy)
    assert full.startswith(checking.FACTS_LEAD) and words in full and full.endswith(checking.FACTS_REST)
    fix = checking.facts_line(could, copy, fix=True)
    assert words in fix and checking.FACTS_REST not in fix
    assert fix.endswith("it can't run a command, commit, land or save to memory.")


@pytest.mark.parametrize("agent, state, could", [
    ("chatgpt", search.ALLOWED, True), ("claude", search.OFF_PROBE, False), ("claude", search.ALLOWED, True),
    ("grok", None, True),
])
def test_could_search_comes_from_the_doers_call_row(conn, agent, state, could):
    row = _routed(conn, agent=agent, checker="chatgpt" if agent != "chatgpt" else "claude")
    log.add_call(conn, "sr-1", "sr-1", "do", agent, status="done", text=RESULT,
                 search={"state": state} if state else None)
    _, kind, who, prompt, _ = _plan(conn, row, checking.Step("check", result=RESULT))
    assert kind == "check" and checking.facts_line(could, False) in prompt


def test_a_cursor_row_never_could_search():  # Cursor never routes; on versus its row has no search record
    class Row(dict):
        def keys(self):
            return super().keys()
    assert cli._could_search(Row(agent="cursor", search=None)) is False
    assert cli._could_search(None) is False


# ---------- the re-check (decision 15) ----------

def test_the_recheck_is_the_check_with_the_first_list_its_line_and_format():
    first = checking.read_check(FIRST)
    prompt = checking.checker_prompt(TASK, RESULT, no_tools=False, first=first)
    _before_task(prompt, checking.RECHECK_LINE)
    _before_task(prompt, checking.RECHECK_FORMAT)
    assert checking.ONE_LIST_LINE not in prompt and checking.MUST_NOTE_LINE in prompt  # Phase 0, call 11
    assert checking.REPLY_FORMAT not in prompt
    block = checking._block(checking.FIRST_CHECK_LABEL, checking.first_list(first))
    assert prompt.count(block) == 1 and prompt.index("===== END RESULT =====") < prompt.index(block)
    assert "1. [must] Tray two is not sold any more.\n2. [note] Name the sizes." in block


def test_the_recheck_reask_names_the_missing_must_and_carries_its_reply(conn):
    row = _routed(conn)
    log.add_call(conn, "sr-1", "sr-1", "do", "claude", status="done", text=RESULT)
    two = "FIX\n1. [must] Tray two is gone.\n2. [must] Over the limit."
    log.add_call(conn, "sr-1-c1", "sr-1", "check", "chatgpt", status="done", text=two, verdict="FIX")
    log.add_call(conn, "sr-1-f1", "sr-1", "fix", "claude", status="done", text="Tray one. Tray four. Tray three.")
    log.add_call(conn, "sr-1-c2", "sr-1", "recheck", "chatgpt", status="done", text="PASS\n1. fixed",
                 verdict=checking.verdict_for("recheck", "PASS\n1. fixed", log.calls_for(conn, "sr-1")))
    step = checking.next_step(log.get_task(conn, "sr-1"), log.calls_for(conn, "sr-1"))
    assert (step.action, step.missing) == ("recheck", (2,))
    call_id, kind, who, prompt, _ = _plan(conn, row, step)
    assert (call_id, kind, who) == ("sr-1-c2r", "recheck", "chatgpt")
    assert checking.RECHECK_REASK_LINE.format(which="2") in prompt
    assert checking._block(checking.EARLIER_RECHECK_LABEL, "PASS\n1. fixed") in prompt
    assert checking._block(checking.FIRST_CHECK_LABEL, "1. [must] Tray two is gone.\n2. [must] Over the limit.") in prompt


def test_numbers_read_as_words():
    assert [checking._numbers(x) for x in ((2,), (1, 3), (1, 2, 4))] == ["2", "1 and 3", "1, 2 and 4"]


# ---------- the fix round (decisions 15, 16, 18, 20) ----------

def test_the_fix_round_gets_musts_and_notes_apart_with_its_lines(conn):
    row = _routed(conn)
    log.add_call(conn, "sr-1", "sr-1", "do", "claude", status="done", text=RESULT)
    log.add_call(conn, "sr-1-c1", "sr-1", "check", "chatgpt", status="done", text=FIRST, verdict="FIX")
    step = checking.next_step(log.get_task(conn, "sr-1"), log.calls_for(conn, "sr-1"))
    call_id, kind, who, prompt, _ = _plan(conn, row, step)
    assert (call_id, kind, who) == ("sr-1-f1", "fix", "claude")
    for line in (checking.MUST_FIX_INSTRUCTIONS, checking.facts_line(False, False, fix=True), checking.UNVERIFIED_FIX_LINE,
                 checking.FIX_REPLY_LINE, checking.DELIVERABLE_LINE):
        _before_task(prompt, line)
    assert prompt.index(checking.FIX_REPLY_LINE) < prompt.index(checking.DELIVERABLE_LINE)
    assert checking._block(checking.MUST_FIX_LABEL, "1. Tray two is not sold any more.") in prompt
    assert checking._block(checking.SUGGESTIONS_LABEL, "2. Name the sizes.") in prompt
    assert "===== REVIEW NOTES =====" not in prompt and checking.FIX_INSTRUCTIONS not in prompt
    assert checking.FACTS_REST not in prompt


def test_a_fix_with_no_notes_says_none_and_an_old_list_is_all_musts():
    reading = checking.read_check("FIX\n1. Add the year.")
    prompt = checking.fix_prompt(TASK, RESULT, "1. Add the year.", reading=reading)
    assert checking._block(checking.SUGGESTIONS_LABEL, "none") in prompt
    assert checking._block(checking.MUST_FIX_LABEL, "1. Add the year.") in prompt


def test_redteams_revise_stage_keeps_its_words():
    prompt = relay.prompt_for("revise", TASK, RESULT, against="1. [high] x")
    for line in (checking.MUST_FIX_INSTRUCTIONS, checking.DELIVERABLE_LINE, checking.UNVERIFIED_FIX_LINE,
                 checking.FACTS_LEAD):
        assert line not in prompt


def test_collabs_fix_round_takes_the_unfinished_form():
    reading = checking.read_check(FIRST)
    prompt = checking.fix_prompt(TASK, RESULT, "", reading=reading, unfinished=True)
    assert checking.DELIVERABLE_LINE_UNFINISHED in prompt and checking.DELIVERABLE_LINE not in prompt
    assert "say so under a `## Unfinished` heading after it" in checking.DELIVERABLE_LINE_UNFINISHED


# ---------- the doer's deliverable line (decision 20) ----------

def test_the_routed_doer_gets_the_line_right_after_the_task(conn):
    row = _routed(conn)
    _, kind, _, prompt, _ = _plan(conn, row, checking.Step("do"))
    assert kind == "do" and less_next(prompt) == f"{TASK}\n\n{checking.DELIVERABLE_LINE}"
    _, _, _, open_prompt, _ = _plan(conn, row, checking.Step("do"), searching=search.ALLOWED)
    assert less_next(open_prompt) == f"{TASK}\n\n{checking.DELIVERABLE_LINE}\n\n{checking.SEARCH_LINE_GENERAL}"


@pytest.mark.parametrize("role, kwargs, line", [
    ("build", {}, checking.DELIVERABLE_LINE),                                          # research-build's build
    ("build", {"task_alone": True}, checking.DELIVERABLE_LINE),                        # each versus build
    ("build", {"task_alone": True, "deliverable_shape": True}, checking.DELIVERABLE_LINE_UNFINISHED),  # redteam's
    ("execute", {}, checking.DELIVERABLE_LINE_UNFINISHED),                              # collab's
    ("execute", {"handoff": True}, checking.DELIVERABLE_LINE_UNFINISHED),               # collab's, on a project
])
def test_every_build_that_returns_the_deliverable_gets_the_line(role, kwargs, line):
    prompt = relay.prompt_for(role, TASK, "the stage before", **kwargs)
    assert prompt.count(line) == 1
    other = checking.DELIVERABLE_LINE if line == checking.DELIVERABLE_LINE_UNFINISHED else checking.DELIVERABLE_LINE_UNFINISHED
    assert other not in prompt


@pytest.mark.parametrize("role", ["research", "plan", "amend", "edit", "review", "attack", "revise", "vote"])
def test_no_other_stage_gets_the_line(role):
    prompt = relay.prompt_for(role, TASK, "the stage before", against="1. [high] x")
    assert checking.DELIVERABLE_LINE not in prompt and checking.DELIVERABLE_LINE_UNFINISHED not in prompt
    assert checking.MUST_FIX_INSTRUCTIONS not in prompt


def test_the_splits_integration_gets_it_and_its_plan_does_not():
    plan = {"inputs": [{"text": "a", "result": "A."}, {"text": "b", "result": "B."}], "join": "Both."}
    assert split.integrate_prompt(TASK, plan).count(checking.DELIVERABLE_LINE) == 1
    assert checking.DELIVERABLE_LINE not in split.plan_prompt(TASK, "TEAMS a piece may take")


# ---------- the memory line (decision 20) ----------

def test_every_call_with_a_memory_block_gets_the_line_right_before_it(monkeypatch):
    from router import memory
    entry = memory.Entry(4, "2026-10-26", "writing", "claude", "passed", "An earlier garden task.")
    monkeypatch.setattr(memory, "for_call", lambda conn, task, hindsight, secrets, reuse=None: ([entry], {"tag": "chat:g"}))
    monkeypatch.setattr(log, "project_of", lambda task: None)
    monkeypatch.setattr(log, "tag_of", lambda task: "chat:g")
    prompt, _, record = context.attach("The task.", {"task_id": "sr-9"}, "claude", ())
    assert record["sent"] == 1 and prompt.count(context.MEMORY_USE_LINE) == 1
    assert prompt.endswith(f"{context.MEMORY_USE_LINE}\n\n{record['text']}")
    assert context.MEMORY_USE_LINE not in record["text"]  # the record keeps the block as it is


def test_a_call_without_a_block_never_gets_the_memory_line(monkeypatch):
    from router import memory
    monkeypatch.setattr(memory, "for_call", lambda conn, task, hindsight, secrets, reuse=None: ([], {"tag": "chat:g"}))
    monkeypatch.setattr(log, "project_of", lambda task: None)
    monkeypatch.setattr(log, "tag_of", lambda task: "chat:g")
    prompt, _, record = context.attach("The task.", {"task_id": "sr-9"}, "claude", ())
    assert prompt == "The task." and record["sent"] == 0


# ---------- Proof 2's round 2: the design chat's words ----------

def test_round_2_and_3s_must_list_and_lines_are_the_design_chats():
    must = checking.MUST_NOTE_LINE
    assert ("code that doesn't do what the task needs, including a wrong or impossible result for an input it accepts "
            "without an error;") in must
    assert ("a change or decision the task didn't ask for that the result makes as settled or applies (a rule, a file or "
            "an agreed decision changed without being asked); a choice that a plan, a recommendation or a proposal puts "
            "to the person to approve is never a [must] for being new or different from earlier decisions: say so as a "
            "[note]. An error in a plan is still a [must]: a number, a sum or a schedule that doesn't add up, or a step "
            "that can't work;") in must  # round 3 (#21): the clause's last sentence
    assert checking.UNVERIFIED_CHECK_LINE == (  # round 3 (#29)
        "Check each main claim the answer depends on, as far as your tools allow. When a claim you checked is wrong, it is "
        "a wrong fact: say what is right and where you found it. For a claim the result doesn't back and you couldn't "
        "check, the fix you ask for is: back it or mark it unverified. Never ask for counts, samples or new research the "
        "task didn't ask for.")
    rule = checking.NO_RESULT_RULE
    assert "Only for a result that says it couldn't do the task: if what the doer needed was not in what it was given" in rule
    assert rule.endswith("A result that did the task is never BLOCKED: what you couldn't check yourself is a [note].")


def test_every_check_and_recheck_says_the_tasks_date_before_the_blocks(conn):
    row = _routed(conn)
    log.add_call(conn, "sr-1", "sr-1", "do", "claude", status="done", text=RESULT)
    from router import memory
    line = checking.SENT_ON_LINE.format(date=memory.local_date(row["created_at"]))
    _, _, _, check, _ = _plan(conn, row, checking.Step("check", result=RESULT))
    _before_task(check, line)
    assert check.index(checking.count_line(TASK, RESULT)) < check.index(line)  # after the count line
    _, _, _, recheck, _ = _plan(conn, row, checking.Step("recheck", result=RESULT, reading=checking.read_check(FIRST)))
    _before_task(recheck, line)
    _, _, _, fix, _ = _plan(conn, row, checking.Step("fix", result=RESULT, reading=checking.read_check(FIRST)))
    assert "The task was sent on" not in fix


def test_only_research_builds_check_and_recheck_get_the_research_note_line(conn):
    log.add_task(conn, "sr-r", TASK, "cli", {"status": "not_asked", "tokens": 0}, mode="relay", preset="research-build")
    log.set_route(conn, "sr-r", agents=ALL_AGENTS, agent="claude", route_reason="relay", checker="chatgpt",
                  check_state="pending")
    rb = log.get_task(conn, "sr-r")
    for step in (checking.Step("check", result=RESULT), checking.Step("recheck", result=RESULT,
                                                                       reading=checking.read_check(FIRST))):
        _, _, _, prompt, _ = cli._plan_call(rb, step, (), searching=search.OFF_PROBE)
        _before_task(prompt, checking.RESEARCH_NOTE_CHECK_LINE)
    _, _, _, fix, _ = cli._plan_call(rb, checking.Step("fix", result=RESULT, reading=checking.read_check(FIRST)), (),
                                     searching=search.OFF_PROBE)
    assert checking.RESEARCH_NOTE_CHECK_LINE not in fix
    route = _routed(conn, task_id="sr-2")
    _, _, _, prompt, _ = _plan(conn, route, checking.Step("check", result=RESULT))
    assert checking.RESEARCH_NOTE_CHECK_LINE not in prompt


# ---------- brief 30 (A6): the fix round changes only what the list asks ----------

def test_the_fix_round_gets_the_fix_only_line_right_after_the_lists_line(conn):
    row = _routed(conn)
    log.add_call(conn, "sr-1", "sr-1", "do", "claude", status="done", text=RESULT)
    log.add_call(conn, "sr-1-c1", "sr-1", "check", "chatgpt", status="done", text=FIRST, verdict="FIX")
    step = checking.next_step(log.get_task(conn, "sr-1"), log.calls_for(conn, "sr-1"))
    _, kind, _, prompt, _ = _plan(conn, row, step)
    assert kind == "fix" and prompt.count(checking.FIX_ONLY_LINE) == 1
    assert f"{checking.MUST_FIX_INSTRUCTIONS}\n\n{checking.FIX_ONLY_LINE}\n\n" in prompt
    assert checking.FIX_ONLY_LINE == ("Change only what the list asks for. Don't add facts, sources or claims it didn't "
                                      "ask for: everything you change is checked again, and a new error fails the result.")


@pytest.mark.parametrize("unfinished", [False, True])
def test_every_fix_round_shape_carries_it_once(unfinished):
    prompt = checking.fix_prompt(TASK, RESULT, "", reading=checking.read_check(FIRST), unfinished=unfinished,
                                 prior="the pieces", prior_label="PIECES", prior_lines=["the pieces line"])
    assert prompt.count(checking.FIX_ONLY_LINE) == 1  # a build stage's and a split integration's fix rounds alike


def test_no_other_prompt_carries_the_fix_only_line(conn):
    row = _routed(conn)
    for step in (checking.Step("do"), checking.Step("check", result=RESULT), checking.Step("recheck", result=RESULT)):
        assert checking.FIX_ONLY_LINE not in _plan(conn, row, step)[3]
    for role in ("research", "plan", "amend", "build", "execute", "edit", "review", "attack", "revise", "vote"):
        assert checking.FIX_ONLY_LINE not in relay.prompt_for(role, TASK, "the stage before", against="1. [high] x")
    plan = {"inputs": [{"text": "a", "result": "A."}, {"text": "b", "result": "B."}], "join": "Both."}
    assert checking.FIX_ONLY_LINE not in split.integrate_prompt(TASK, plan)
    assert checking.FIX_ONLY_LINE not in relay.reask_prompt("revise", TASK, RESULT, ["x"])



# ---------- brief 30 (decision 19, K): Proof 3 failed, so K's words were reverted ----------

@pytest.mark.parametrize("kwargs", [{}, {"copy": True}, {"first": checking.read_check("FIX\n1. [must] x")}])
def test_no_check_prompt_asks_for_a_claims_list(kwargs):
    prompt = checking.checker_prompt(TASK, RESULT, no_tools=False, **kwargs)
    assert "CLAIMS" not in prompt and "List the main claims" not in prompt
    assert "Check each main claim the answer depends on, as far as your tools allow." in prompt
