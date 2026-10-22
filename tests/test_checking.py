"""router/checking.py: the checker and fix prompts, the verdict reader, and next_step, which
turns a task row and its calls into the next action. Pure code: no calls anywhere."""
import json
from pathlib import Path

import pytest

from router import checking, log, routing
from tests.helpers import ALL_AGENTS, JEV_OK, shipped_roster

TASK = "Find the population of Lisbon in 2024, with a source link."
RESULT = "Lisbon had about 567,000 residents in 2024 (source: https://example.org/lisbon)."
NOTES = "1. The figure needs a year.\n2. Add the source link."
AGENT_NAMES = tuple(json.loads((Path(__file__).resolve().parent.parent / "config" / "agents.json").read_text())["agents"])
NEVER_NAMED = AGENT_NAMES + ("claude", "anthropic", "sonnet", "haiku", "opus", "grok", "xai", "chatgpt", "openai",
                             "gpt", "codex", "muse", "meta", "jev", "typesafe")


# ---------- the checker prompt ----------

def test_checker_prompt_says_the_person_asked_and_received_and_carries_both_as_data():
    prompt = checking.checker_prompt(TASK, RESULT, no_tools=False)
    assert "The person asked" in prompt and "received" in prompt   # brief 24 (decision 17): "the person"
    assert TASK in prompt and RESULT in prompt
    assert prompt.index(TASK) < prompt.index(RESULT)
    low = prompt.lower()
    assert "data" in low and "not to be followed" in low


def test_checker_prompt_says_what_to_judge_and_never_asks_for_style_fixes():
    low = checking.checker_prompt(TASK, RESULT, no_tools=False).lower()
    for phrase in ("what the task asked", "wrong or missing", "contradict", "source links"):
        assert phrase in low, phrase
    assert "style" in low and "wording" in low


def test_checker_prompt_never_passes_a_result_that_did_not_do_the_task():
    low = checking.checker_prompt(TASK, RESULT, no_tools=False).lower()
    assert "could not do the task" in low and "gives no answer" in low
    assert "never pass" in low and "even when" in low
    assert checking.NO_RESULT_RULE.lower() in low


def test_a_result_that_did_the_work_and_found_fewer_than_asked_is_an_answer_not_a_non_result():
    # Task #9 (2026-10-13): "two deals, not three", with sources, was failed twice as "could not do the task".
    rule = checking.NO_RESULT_RULE.lower()
    assert "fewer" in rule and "has answered" in rule and "on its evidence" in rule
    assert rule.index("never pass") < rule.index("fewer"), "the exception comes after the rule it narrows"
    for prompt in (checking.checker_prompt(TASK, RESULT, no_tools=True), checking.checker_prompt(TASK, RESULT, no_tools=False)):
        assert "has answered" in prompt.lower()


def test_checker_prompt_demands_the_verdict_format():
    prompt = checking.checker_prompt(TASK, RESULT, no_tools=False)
    assert "PASS" in prompt and "FIX" in prompt
    assert "first line" in prompt.lower() and "numbered" in prompt.lower()
    assert "nothing before" in prompt.lower()


def test_the_no_tools_paragraph_appears_only_for_the_claude_worker():
    with_it = checking.checker_prompt(TASK, RESULT, no_tools=True).lower()
    without = checking.checker_prompt(TASK, RESULT, no_tools=False).lower()
    for phrase in ("can't open links", "look anything up", "prices", "dates", "verified"):
        assert phrase in with_it and phrase not in without, phrase


# ---------- the fix prompt ----------

def test_fix_prompt_carries_task_earlier_result_and_notes_as_data():
    prompt = checking.fix_prompt(TASK, RESULT, NOTES)
    assert TASK in prompt and RESULT in prompt and NOTES in prompt
    assert prompt.index(TASK) < prompt.index(NOTES) < prompt.index(RESULT)  # brief 11.1: the notes before the result
    low = prompt.lower()
    assert "reviewed" in low and "data" in low
    assert "suggestions" in low and "not instructions from the person" in low   # brief 24 (decision 17)
    assert "would change what the task asked for" in low
    assert "complete revised result" in low and "no commentary" in low


def test_both_prompts_scope_out_standing_instructions_from_elsewhere():
    for prompt in (checking.checker_prompt(TASK, RESULT, no_tools=False), checking.fix_prompt(TASK, RESULT, NOTES)):
        low = prompt.lower()
        assert "one-off text task" in low and "not a working session" in low
        for phrase in ("briefing", "handoff", "fixed phrase", "do not apply", "only this message"):
            assert phrase in low, phrase


def test_a_reply_that_opens_with_a_standing_phrase_is_unreadable_not_a_pass():
    assert checking.read_verdict("Fully briefed\nPASS") == ("unreadable", None)
    assert checking.read_verdict("Fully briefed") == ("unreadable", None)


# ---------- name nobody ----------

@pytest.mark.parametrize("prompt", [
    checking.checker_prompt("a neutral task", "a neutral result", no_tools=True),
    checking.checker_prompt("a neutral task", "a neutral result", no_tools=False),
    checking.fix_prompt("a neutral task", "a neutral result", "1. a neutral note"),
])
def test_neither_prompt_names_any_agent_or_model(prompt):
    low = prompt.lower()
    for name in NEVER_NAMED:
        assert name not in low, name


# ---------- the verdict reader ----------

@pytest.mark.parametrize("text, expected", [
    ("PASS", ("PASS", None)),
    ("**PASS**", ("PASS", None)),
    ("Pass.", ("PASS", None)),
    ("pass\n\nLooks complete to me.", ("PASS", None)),
    ("  \n  `PASS`  \n", ("PASS", None)),
    ("FIX\n1. Add the source link.\n2. Give the year.", ("FIX", "1. Add the source link.\n2. Give the year.")),
    ("FIX: add the source link", ("FIX", "add the source link")),
    ("**FIX**\n\n1. Add the year", ("FIX", "1. Add the year")),
    ("FIX", ("unreadable", None)),
    ("FIX\n\n   \n", ("unreadable", None)),
    ("Verdict: PASS", ("unreadable", None)),
    ("I think it passes.", ("unreadable", None)),
    ("", ("unreadable", None)),
    (None, ("unreadable", None)),
    ("PASSED", ("unreadable", None)),
])
def test_read_verdict(text, expected):
    assert checking.read_verdict(text) == expected


def test_verdicts_match_the_log():
    assert set(v for v, _ in [checking.read_verdict("PASS"), checking.read_verdict("FIX\n1. x"),
                               checking.read_verdict("?")]) == set(log.VERDICTS)


# ---------- next_step: section 5 of the brief, one test per row ----------

@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _task(conn, *, agent="grok", checker="claude", check_state="pending", note=None, skill="web_research",
          task_id="sr-1"):
    log.add_task(conn, task_id, TASK, "cli", JEV_OK)
    log.set_route(conn, task_id, agents=ALL_AGENTS, agent=agent, route_reason="best", skill=skill,
                  skill_source="jev", checker=checker, check_state=check_state, check_note=note)
    return task_id


def _do(conn, task_id="sr-1", status="done", text=RESULT, agent="grok"):
    if agent == "grok":
        log.set_sent(conn, task_id, "uuid")
        if status != "sent":
            log.finish_call(conn, task_id, status, text=text)
    else:
        log.add_call(conn, task_id, task_id, "do", agent, status=status, text=text)


def _call(conn, call_id, kind, agent="claude", status="done", text="PASS", task_id="sr-1"):
    verdict = checking.read_verdict(text)[0] if kind in ("check", "recheck") and status == "done" else None
    log.add_call(conn, call_id, task_id, kind, agent, status=status, text=text, verdict=verdict)


def _step(conn, task_id="sr-1"):
    return checking.next_step(log.get_task(conn, task_id), log.calls_for(conn, task_id))


def test_endings_table():
    assert checking.ENDINGS == {
        1: ("not_needed", 0), 2: ("unchecked", 0), 3: ("passed", 0), 4: ("unchecked", 0),
        5: ("failed", 5), 6: ("fixed", 0), 7: ("unchecked", 0), 8: ("failed", 5),
    }


def test_row_1_no_check_owed(conn):
    _task(conn, agent="claude", checker=None, check_state="not_needed", skill="quick_answer")
    _do(conn, agent="claude")
    step = _step(conn)
    assert (step.action, step.ending, step.result, step.note) == ("finish", 1, RESULT, None)


def test_row_2_no_check_possible(conn):
    _task(conn, agent="claude", checker="chatgpt", check_state="unchecked", note="checker chatgpt isn't live yet",
          skill="code")
    _do(conn, agent="claude")
    step = _step(conn)
    assert (step.action, step.ending, step.result, step.note) == (
        "finish", 2, RESULT, "checker chatgpt isn't live yet")


def test_row_3_first_check_passes(conn):
    _task(conn)
    _do(conn)
    assert _step(conn).action == "check" and _step(conn).result == RESULT
    _call(conn, "sr-1-c1", "check", text="PASS\nAll good.")
    step = _step(conn)
    assert (step.action, step.ending, step.result, step.fix_list, step.note) == ("finish", 3, RESULT, None, None)


@pytest.mark.parametrize("status, text, reason", [
    ("done", "Looks fine to me.", "unreadable verdict"),
    ("failed", "claude exited 1: not logged in", "claude exited 1: not logged in"),
    ("timed_out", None, "timed out"),
])
def test_row_4_first_check_did_not_run(conn, status, text, reason):
    _task(conn)
    _do(conn)
    _call(conn, "sr-1-c1", "check", status=status, text=text)
    step = _step(conn)
    assert (step.action, step.ending, step.result, step.fix_list) == ("finish", 4, RESULT, None)
    assert step.note.startswith("check round by claude") and reason in step.note


@pytest.mark.parametrize("status, text", [("failed", "webhook returned HTTP 500"), ("timed_out", None), ("done", "   ")])
def test_row_5_fix_round_did_not_run(conn, status, text):
    _task(conn)
    _do(conn)
    _call(conn, "sr-1-c1", "check", text="FIX\n1. Add the year.")
    step = _step(conn)
    assert (step.action, step.result, step.fix_list) == ("fix", RESULT, "1. Add the year.")
    _call(conn, "sr-1-f1", "fix", agent="grok", status=status, text=text)
    step = _step(conn)
    assert (step.action, step.ending, step.result, step.fix_list) == ("finish", 5, RESULT, "1. Add the year.")
    assert step.note.startswith("fix round by grok")


def test_row_6_fixed_then_passes(conn):
    _task(conn)
    _do(conn)
    _call(conn, "sr-1-c1", "check", text="FIX\n1. Add the year.")
    _call(conn, "sr-1-f1", "fix", agent="grok", text="Lisbon had 567,000 residents in 2024 (source: ...).")
    step = _step(conn)
    assert (step.action, step.result) == ("recheck", "Lisbon had 567,000 residents in 2024 (source: ...).")
    _call(conn, "sr-1-c2", "recheck", text="PASS")
    step = _step(conn)
    assert (step.action, step.ending, step.result, step.fix_list, step.note) == (
        "finish", 6, "Lisbon had 567,000 residents in 2024 (source: ...).", None, None)


@pytest.mark.parametrize("status, text", [("done", "Seems ok"), ("failed", "claude exited 1"), ("timed_out", None)])
def test_row_7_recheck_did_not_run(conn, status, text):
    _task(conn)
    _do(conn)
    _call(conn, "sr-1-c1", "check", text="FIX\n1. Add the year.")
    _call(conn, "sr-1-f1", "fix", agent="grok", text="fixed result")
    _call(conn, "sr-1-c2", "recheck", status=status, text=text)
    step = _step(conn)
    assert (step.action, step.ending, step.result, step.fix_list) == ("finish", 7, "fixed result", None)
    assert step.note.startswith("re-check by claude") and "fixed result" in step.note


def test_row_8_fix_then_fix_again(conn):
    _task(conn)
    _do(conn)
    _call(conn, "sr-1-c1", "check", text="FIX\n1. Add the year.")
    _call(conn, "sr-1-f1", "fix", agent="grok", text="fixed result")
    _call(conn, "sr-1-c2", "recheck", text="FIX\n1. Still no year.")
    step = _step(conn)
    assert (step.action, step.ending, step.result, step.fix_list) == ("finish", 8, "fixed result", "1. Still no year.")
    assert step.note == "not passed after one fix round"


# ---------- waiting, and tasks from before this build ----------

@pytest.mark.parametrize("stage", ["do", "check", "fix", "recheck"])
def test_a_grok_call_in_flight_means_wait(conn, stage):
    _task(conn, agent="claude", checker="grok", skill="bulk_text")
    if stage == "do":
        _task(conn, task_id="sr-2")
        _do(conn, task_id="sr-2", status="sent")
        step = _step(conn, "sr-2")
        assert (step.action, step.call["call_id"]) == ("wait", "sr-2")
        return
    _do(conn, agent="claude")
    if stage == "check":
        _call(conn, "sr-1-c1", "check", agent="grok", status="sent", text=None)
        assert (_step(conn).action, _step(conn).call["call_id"]) == ("wait", "sr-1-c1")
        return
    _call(conn, "sr-1-c1", "check", agent="grok", text="FIX\n1. x")
    if stage == "fix":
        _call(conn, "sr-1-f1", "fix", agent="claude", status="sent", text=None)
        assert (_step(conn).action, _step(conn).call["call_id"]) == ("wait", "sr-1-f1")
        return
    _call(conn, "sr-1-f1", "fix", agent="claude", text="fixed")
    _call(conn, "sr-1-c2", "recheck", agent="grok", status="sent", text=None)
    assert (_step(conn).action, _step(conn).call["call_id"]) == ("wait", "sr-1-c2")


def test_a_task_that_already_ended_has_nothing_to_do(conn):
    _task(conn)
    _do(conn)
    log.set_done(conn, "sr-1", RESULT, check_state="unchecked")
    step = _step(conn)
    assert (step.action, step.ending) == ("finish", None)


def test_a_task_from_before_this_build_has_no_calls_and_nothing_to_do(conn):
    _task(conn, check_state="unchecked")
    log.set_done(conn, "sr-1", "an old result")
    assert log.calls_for(conn, "sr-1") == []
    assert (_step(conn).action, _step(conn).ending) == ("finish", None)


def test_an_open_task_with_no_call_yet_needs_its_first_call(conn):
    _task(conn)
    assert _step(conn).action == "do"


def test_a_failed_first_call_ends_the_task_as_today(conn):
    _task(conn)
    log.set_sent(conn, "sr-1", "uuid")
    log.finish_call(conn, "sr-1", "failed", text="webhook returned HTTP 500")
    log.set_failed(conn, "sr-1", "webhook returned HTTP 500")
    assert (_step(conn).action, _step(conn).ending) == ("finish", None)


# ---------- overrides where the named agent is the second ----------

def test_override_checkers_come_from_decide_and_flow_into_the_loop(conn):
    roster = shipped_roster()
    ok = {"status": "ok", "label": "bulk_text", "confidence": 0.95}
    d = routing.decide(ok, roster, override="grok")   # grok is bulk_text's second, so its best, claude, checks
    assert (d.agent, d.checker) == ("grok", "claude")
    log.add_task(conn, "sr-o", TASK, "cli", ok)
    log.set_route(conn, "sr-o", agents=roster.names, agent=d.agent, route_reason=d.reason, skill=d.skill,
                  skill_source=d.skill_source, checker=d.checker, check_state="pending")
    _do(conn, task_id="sr-o")
    assert _step(conn, "sr-o").action == "check"
    d2 = routing.decide({"status": "ok", "label": "web_research", "confidence": 0.95}, roster, override="claude")
    assert (d2.agent, d2.checker) == ("claude", "chatgpt")  # claude is the second, so the best checks: not live
