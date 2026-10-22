"""Build brief 24, C1 (decisions 4, 6 and 7): `router/takeover.py` decides from the log, availability and the preset who
takes over a stopped call and who checks after, or why nobody does. Pure: no agent is called, nothing is written by it.

The two tables of Phase 0's item 4 are the cases here: who takes over (routed tasks and pieces, relay stages and check
rounds, a split's plan and integration), and every stop (covered or not). Plus the manual resume's count, which reads
only `-resume` rows now that a takeover row carries `resume_of` too (the owner's C3). Fakes only."""
import pytest

from router import availability, log, relay, resume, split, takeover
from tests.helpers import shipped_roster
from tests.test_collab import AMENDED, LOADED, PLAN
from tests.test_relay import GOOD_NOTE

AGENTS = ("claude", "grok", "chatgpt", "muse", "cursor")
SKILLS = shipped_roster().skills
RB, COLLAB, REDTEAM = LOADED.presets["research-build"], LOADED.presets["collab"], LOADED.presets["redteam"]
VERSUS, VOTE = LOADED.presets["versus"], LOADED.presets["vote"]
WHY = {"chatgpt": "ChatGPT is signed out (codex login)", "grok": "Grok Bot isn't set up: no inbox repo in settings",
       "claude": "Claude is signed out (claude login)"}


def table(*out):
    """Availability with the named agents out, every other one available."""
    return lambda a: availability.Availability(False, WHY[a], "signed_out") if a in out else availability.YES


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _route(conn, *, skill, agent, checker, state="pending", reason="best", files=None):
    jev = {"status": "ok", "label": skill, "confidence": 0.9, "needs_split": 0.1, "tokens": 0}
    log.add_task(conn, "t", "a task", "cli", jev, files=files)
    log.set_route(conn, "t", agents=AGENTS, agent=agent, route_reason=reason, skill=skill, skill_source="jev",
                  checker=checker, check_state=state)


def _relay(conn, preset, mode="relay"):
    log.add_task(conn, "t", "a task", "cli", {"status": "not_asked", "tokens": 0}, mode=mode,
                 preset=preset.name if mode == "relay" else None)
    log.set_route(conn, "t", agents=AGENTS, agent=preset.doer, route_reason=mode, checker=preset.check_agent,
                  check_state="pending")


def _done(conn, call_id, kind, agent, text="ok", **kw):
    log.add_call(conn, call_id, "t", kind, agent, status="done", text=text, **kw)


def _stop(conn, call_id, kind, agent, code="plan_limit", text=None, **kw):
    words = text or {"plan_limit": f"plan limit on {agent}: x", "overdue": None}.get(code, "codex exited 1: model at capacity")
    log.add_call(conn, call_id, "t", kind, agent, status="failed", text=words, reason_code=code, **kw)


def _decide(conn, available=None, preset=None, exclude=None):
    task, calls = log.get_task(conn, "t"), log.calls_for(conn, "t")
    stopped = takeover.pending(task, calls)
    assert stopped is not None, "the newest row should be a stop the takeover may pick up"
    return takeover.decide(task, calls, stopped, available=available or table(), skills=SKILLS, preset=preset,
                           exclude=exclude)


def _after(plan):
    return plan.to, plan.agent, plan.checker, plan.check_state, plan.check_note


def unchecked(why):
    return f"no other agent available to check ({why})"


# ---------- routed tasks and pieces: who takes over, who checks after ----------

def test_claudes_first_call_at_its_plan_limit_goes_to_chatgpt_and_nobody_is_left_to_check(conn):
    _route(conn, skill="writing", agent="claude", checker="chatgpt")
    _stop(conn, "t", "do", "claude")
    plan = _decide(conn)
    assert plan.ok and (plan.kind, plan.call_id, plan.why) == ("do", "t-takeover", "Claude hit its plan limit")
    assert _after(plan) == ("chatgpt", "chatgpt", None, "unchecked", unchecked("Claude hit its plan limit"))


def test_the_best_agents_failed_call_goes_to_second_place_and_the_stopped_agent_never_checks(conn):
    _route(conn, skill="web_research", agent="chatgpt", checker="claude")
    _stop(conn, "t", "do", "chatgpt", code=None)
    plan = _decide(conn)
    assert plan.why == "ChatGPT's call failed: codex exited 1: model at capacity"
    assert _after(plan) == ("claude", "claude", None, "unchecked", unchecked(plan.why))


def test_bulk_text_goes_to_grok_bot_in_second_place_and_chatgpt_checks(conn):
    _route(conn, skill="bulk_text", agent="claude", checker="grok")
    _stop(conn, "t", "do", "claude")
    assert _after(_decide(conn)) == ("grok", "grok", "chatgpt", "pending", None)


def test_a_task_with_files_never_goes_to_grok_bot_but_grok_may_still_check_it_as_at_intake(conn):
    _route(conn, skill="bulk_text", agent="claude", checker="grok", files=[{"name": "a.png", "kind": "image"}])
    _stop(conn, "t", "do", "claude")
    assert _after(_decide(conn)) == ("chatgpt", "chatgpt", "grok", "pending", None)


def test_an_unavailable_agent_is_skipped_and_with_nobody_left_the_takeover_says_why(conn):
    _route(conn, skill="writing", agent="claude", checker="chatgpt")
    _stop(conn, "t", "do", "claude")
    plan = _decide(conn, table("chatgpt"))
    assert not plan.ok and plan.nobody
    assert plan.reason == f"no other agent can take it over ({WHY['chatgpt']})"


def test_a_check_round_goes_to_the_next_checker_and_the_doer_stays(conn):
    _route(conn, skill="bulk_text", agent="claude", checker="grok")
    _done(conn, "t", "do", "claude")
    _stop(conn, "t-c1", "check", "grok", code="overdue")
    plan = _decide(conn)
    assert (plan.why, plan.kind, plan.call_id) == ("Grok Bot was overdue", "check", "t-c1-takeover")
    assert _after(plan) == ("chatgpt", "claude", "chatgpt", "pending", None)


def test_a_check_round_with_nobody_left_is_not_taken_over(conn):
    _route(conn, skill="writing", agent="claude", checker="chatgpt")
    _done(conn, "t", "do", "claude")
    _stop(conn, "t-c1", "check", "chatgpt")
    plan = _decide(conn)
    assert not plan.ok and plan.reason == "no other agent can check it (ChatGPT hit its plan limit)"


def test_a_fix_round_taken_over_by_the_checker_is_delivered_unchecked_c12(conn):
    _route(conn, skill="writing", agent="claude", checker="chatgpt")
    _done(conn, "t", "do", "claude")
    _done(conn, "t-c1", "check", "chatgpt", text="FIX\n- a", verdict="FIX")
    _stop(conn, "t-f1", "fix", "claude")
    plan = _decide(conn)
    assert (plan.kind, plan.call_id) == ("fix", "t-f1-takeover")
    assert _after(plan) == ("chatgpt", "chatgpt", None, "unchecked", unchecked("Claude hit its plan limit"))


def test_a_quick_answer_taken_over_is_still_never_checked(conn):
    _route(conn, skill="quick_answer", agent="claude", checker=None, state="not_needed")
    _stop(conn, "t", "do", "claude")
    assert _after(_decide(conn)) == ("chatgpt", "chatgpt", None, "not_needed", None)


def test_meta_research_from_grok_bot_goes_to_chatgpt_and_claude_checks(conn):
    # Meta research: x_social_pulse is Grok's alone and never taken over (the owner, 21 Oct; test_x_grok_only.py)
    _route(conn, skill="meta_social_trends", agent="grok", checker="chatgpt")
    _stop(conn, "t", "do", "grok", code=None, text="webhook answered 502")
    plan = _decide(conn)
    assert plan.why == "Grok Bot's call failed: webhook answered 502"
    assert _after(plan) == ("chatgpt", "chatgpt", "claude", "pending", None)


def test_a_stand_in_that_stops_goes_on_to_claude_and_nobody_is_left_to_check(conn):
    _route(conn, skill="meta_social_trends", agent="chatgpt", checker="claude", reason=f"stand-in for grok: {WHY['grok']}")
    _stop(conn, "t", "do", "chatgpt")
    plan = _decide(conn, table("grok"))
    assert _after(plan) == ("claude", "claude", None, "unchecked", unchecked("ChatGPT hit its plan limit"))


def test_an_agent_that_stopped_earlier_in_the_task_is_never_picked(conn):
    _route(conn, skill="bulk_text", agent="claude", checker="grok")
    _done(conn, "t", "do", "claude")
    _stop(conn, "t-c1", "check", "grok", code="overdue")
    log.add_call(conn, "t-c1-takeover", "t", "check", "chatgpt", status="done", text="FIX\n- a", verdict="FIX",
                 resume_of="t-c1")
    _stop(conn, "t-f1", "fix", "claude")
    task, calls = log.get_task(conn, "t"), log.calls_for(conn, "t")
    assert takeover.stopped_agents(calls) == {"grok": "Grok Bot was overdue", "claude": "Claude hit its plan limit"}
    plan = takeover.decide(task, calls, calls[-1], available=table(), skills=SKILLS)
    assert not plan.ok and plan.reason == "the task's one takeover was used"


def test_grok_bot_past_its_prompt_limit_is_skipped_by_the_callers_exclude(conn):
    _route(conn, skill="bulk_text", agent="claude", checker="grok")
    _stop(conn, "t", "do", "claude")
    plan = _decide(conn, exclude={"grok": "too long for Grok Bot (4210 characters)"})
    assert _after(plan) == ("chatgpt", "chatgpt", None, "unchecked", unchecked("too long for Grok Bot (4210 characters)"))


def test_a_piece_takes_over_as_a_routed_task(conn):
    log.add_task(conn, "p", "a split", "cli", {"status": "not_asked", "tokens": 0}, mode="split")
    jev = {"status": "ok", "label": "writing", "confidence": 0.9, "needs_split": 0.1, "tokens": 0}
    log.add_task(conn, "t", "a piece", "split", jev, mode="piece", parent="p")
    log.set_route(conn, "t", agents=AGENTS, agent="claude", route_reason="best", skill="writing", skill_source="jev",
                  checker="chatgpt", check_state="pending")
    _stop(conn, "t", "do", "claude")
    assert _decide(conn).to == "chatgpt"


# ---------- relay stages and check rounds; a split's plan and integration ----------

def test_a_grok_research_stage_goes_to_chatgpt_and_the_presets_checker_stays(conn):
    _relay(conn, RB)
    _stop(conn, "t-s1", "stage", "grok", code="overdue", stage=1, role="research")
    plan = _decide(conn, preset=RB)
    assert (plan.kind, plan.stage, plan.role, plan.call_id) == ("stage", 1, "research", "t-s1-takeover")
    assert _after(plan) == ("chatgpt", "claude", "chatgpt", "pending", None)


def test_a_grok_stage_goes_to_claude_when_chatgpt_is_out_and_then_nobody_can_check(conn):
    _relay(conn, RB)
    _stop(conn, "t-s1", "stage", "grok", code=None, text="webhook answered 502", stage=1, role="research")
    plan = _decide(conn, table("chatgpt"), preset=RB)
    assert _after(plan) == ("claude", "claude", None, "unchecked", unchecked(WHY["chatgpt"]))


def test_research_builds_stopped_build_goes_to_chatgpt_and_its_result_is_unchecked_the_briefs_example(conn):
    _relay(conn, RB)
    _done(conn, "t-s1", "stage", "grok", text="## Sources\n- a", stage=1, role="research")
    _stop(conn, "t-s2", "stage", "claude", stage=2, role="build")
    plan = _decide(conn, preset=RB)
    assert _after(plan) == ("chatgpt", "chatgpt", None, "unchecked", unchecked("Claude hit its plan limit"))


def test_a_relay_check_round_is_never_taken_by_the_agent_that_did_the_work(conn):
    _relay(conn, RB)
    _done(conn, "t-s1", "stage", "grok", stage=1, role="research")
    _done(conn, "t-s2", "stage", "claude", stage=2, role="build")
    _stop(conn, "t-c1", "check", "chatgpt")
    plan = _decide(conn, preset=RB)
    assert not plan.ok and plan.nobody and "no other agent can take it over" in plan.reason


def test_collab_a_stopped_plan_goes_to_chatgpt_and_the_chain_keeps_its_agents(conn):
    _relay(conn, COLLAB)
    _stop(conn, "t-s1", "stage", "claude", stage=1, role="plan")
    assert _after(_decide(conn, preset=COLLAB)) == ("chatgpt", "claude", "chatgpt", "pending", None)


def test_collab_a_stopped_build_goes_to_chatgpt_and_the_check_stage_is_left_out(conn):
    _relay(conn, COLLAB)
    _done(conn, "t-s1", "stage", "claude", stage=1, role="plan")
    _done(conn, "t-s2", "stage", "chatgpt", stage=2, role="amend")
    _stop(conn, "t-s3", "stage", "claude", stage=3, role="execute")
    plan = _decide(conn, preset=COLLAB)
    assert _after(plan) == ("chatgpt", "chatgpt", None, "unchecked", unchecked("Claude hit its plan limit"))


def test_collab_a_stopped_check_stage_is_never_taken_by_the_agent_that_made_the_stage_before(conn):
    _relay(conn, COLLAB)
    for n, agent, role in ((1, "claude", "plan"), (2, "chatgpt", "amend"), (3, "claude", "execute")):
        _done(conn, f"t-s{n}", "stage", agent, stage=n, role=role)
    _stop(conn, "t-s4", "stage", "chatgpt", stage=4, role="edit")
    plan = _decide(conn, preset=COLLAB)
    assert not plan.ok and plan.nobody


@pytest.mark.parametrize("n, agent, role", [(1, "claude", "build"), (2, "chatgpt", "attack"), (3, "claude", "revise")])
def test_redteam_keeps_resumes_slot_rules_so_no_stage_is_taken_over(conn, n, agent, role):
    _relay(conn, REDTEAM)
    for k, a, r in ((1, "claude", "build"), (2, "chatgpt", "attack"))[:n - 1]:
        _done(conn, f"t-s{k}", "stage", a, stage=k, role=r)
    _stop(conn, f"t-s{n}", "stage", agent, stage=n, role=role)
    plan = _decide(conn, preset=REDTEAM)
    assert not plan.ok and plan.nobody


def test_a_stopped_re_ask_is_made_again_as_the_stage(conn):
    _relay(conn, RB)
    _done(conn, "t-s1", "stage", "grok", text="no sources", stage=1, role="research")
    _stop(conn, "t-s1r", "reask", "grok", code="overdue", stage=1, role="research")
    plan = _decide(conn, preset=RB)
    assert (plan.kind, plan.call_id, plan.to) == ("stage", "t-s1r-takeover", "chatgpt")


def test_a_splits_plan_goes_to_chatgpt_and_its_integration_check_stays_chatgpts(conn):
    _relay(conn, split.PRESET, mode="split")
    _stop(conn, "t-s1", "stage", "claude", stage=1, role=split.PLAN_ROLE)
    assert _after(_decide(conn, preset=split.PRESET)) == ("chatgpt", "claude", "chatgpt", "pending", None)


def test_a_splits_integration_goes_to_chatgpt_and_is_then_unchecked(conn):
    _relay(conn, split.PRESET, mode="split")
    _done(conn, "t-s1", "stage", "claude", stage=1, role=split.PLAN_ROLE)
    _stop(conn, "t-s2", "stage", "claude", stage=2, role=split.INTEGRATE_ROLE)
    plan = _decide(conn, preset=split.PRESET)
    assert _after(plan) == ("chatgpt", "chatgpt", None, "unchecked", unchecked("Claude hit its plan limit"))


# ---------- every stop: covered or not ----------

@pytest.mark.parametrize("code, words", [
    ("plan_limit", "Claude hit its plan limit"), ("overdue", "Claude was overdue"),
    (None, "Claude's call failed: codex exited 1: model at capacity")])
def test_each_covered_stop_in_words(conn, code, words):
    _route(conn, skill="writing", agent="claude", checker="chatgpt")
    _stop(conn, "t", "do", "claude", code=code)
    assert takeover.why_words(log.calls_for(conn, "t")[-1]) == words


def test_a_grok_stage_too_long_is_a_covered_stop_in_words(conn):
    _relay(conn, RB)
    _done(conn, "t-s1", "stage", "chatgpt", stage=1, role="research")
    _stop(conn, "t-s2", "stage", "grok", code="too_long", text="too long for Grok (4210 characters)", stage=2,
          role="build")
    assert takeover.why_words(log.calls_for(conn, "t")[-1]) == "too long for Grok Bot (4210 characters)"


@pytest.mark.parametrize("code", ["process_ended", "internal_error"])
def test_a_process_that_ended_or_the_routers_own_error_is_never_taken_over(conn, code):
    _route(conn, skill="writing", agent="claude", checker="chatgpt")
    _stop(conn, "t", "do", "claude", code=code, text="x")
    assert takeover.pending(log.get_task(conn, "t"), log.calls_for(conn, "t")) is None


@pytest.mark.parametrize("setup, reason", [
    ("override", "an override is never taken over: you chose the agent"),
    ("make_media", "Grok's make_media call is never taken over: make_media is Grok Bot's alone"),
    ("fallback", "a fallback's calls are never taken over"),
    ("used", "the task's one takeover was used"),
    ("own", "the takeover's own call stopped: the task ends with both reasons"),
])
def test_what_is_never_taken_over_says_why(conn, setup, reason):
    skill, agent, checker = ("make_media", "grok", "claude") if setup == "make_media" else ("writing", "claude", "chatgpt")
    _route(conn, skill=skill, agent=agent, checker=checker, reason="override" if setup == "override" else "best")
    if setup == "fallback":
        _done(conn, "t", "do", "claude")
        log.add_call(conn, "t-fb1", "t", "do", "chatgpt", status="failed", text="x", reason_code="plan_limit",
                     fallback_of="t")
        task, calls = log.get_task(conn, "t"), log.calls_for(conn, "t")
        plan = takeover.decide(task, calls, calls[-1], available=table(), skills=SKILLS)
        assert not plan.ok and plan.reason == reason
        return
    if setup in ("used", "own"):
        _stop(conn, "t", "do", "claude")
        log.add_call(conn, "t-takeover", "t", "do", "chatgpt", status="failed", text="plan limit on chatgpt: x",
                     reason_code="plan_limit", resume_of="t")
        if setup == "used":
            log.add_call(conn, "t-c1", "t", "check", "claude", status="failed", text="x")
    else:
        _stop(conn, "t", "do", agent, code=None)
    task, calls = log.get_task(conn, "t"), log.calls_for(conn, "t")
    plan = takeover.decide(task, calls, calls[-1], available=table(), skills=SKILLS)
    assert not plan.ok and plan.reason == reason and not plan.nobody


@pytest.mark.parametrize("preset", [VERSUS, VOTE], ids=["versus", "vote"])
def test_a_versus_or_vote_task_is_never_taken_over(conn, preset):
    _relay(conn, preset)
    _stop(conn, "t-s1", "stage", "claude", stage=1, role=preset.stage(1).role)
    plan = _decide(conn, preset=preset)
    assert not plan.ok and plan.reason == f"a {preset.name} task is never taken over"


def test_a_cursor_call_is_never_taken_over_and_cursor_never_takes_over(conn):
    _route(conn, skill="writing", agent="cursor", checker="chatgpt")
    _stop(conn, "t", "do", "cursor", code=None, text="pool used up")
    plan = _decide(conn)
    assert not plan.ok and plan.reason == "a Cursor call is never taken over"
    assert takeover._first(["cursor", "chatgpt"], {}, table(), False) == ("chatgpt", None)


def test_pending_needs_an_open_task_whose_newest_row_stopped_and_was_not_made_again(conn):
    _route(conn, skill="writing", agent="claude", checker="chatgpt")
    _stop(conn, "t", "do", "claude")
    task, calls = log.get_task(conn, "t"), log.calls_for(conn, "t")
    assert takeover.pending(task, calls)["call_id"] == "t"
    log.add_call(conn, "t-takeover", "t", "do", "chatgpt", status="failed", text="x", resume_of="t")
    assert takeover.pending(task, log.calls_for(conn, "t")) is None   # the takeover's own stop
    log.set_failed(conn, "t", "x")
    assert takeover.pending(log.get_task(conn, "t"), calls) is None   # a closed task


def test_both_reasons_name_the_takeovers_stop_then_the_first(conn):
    _route(conn, skill="writing", agent="claude", checker="chatgpt")
    _stop(conn, "t", "do", "claude")
    log.add_call(conn, "t-takeover", "t", "do", "chatgpt", status="failed", text="plan limit on chatgpt: x",
                 reason_code="plan_limit", resume_of="t")
    calls = log.calls_for(conn, "t")
    assert takeover.both(calls[-1], calls) == "ChatGPT hit its plan limit, after Claude hit its plan limit"
    assert takeover.both(calls[0], calls) is None


def test_the_words_name_who_took_over_which_call_and_why(conn):
    _route(conn, skill="meta_social_trends", agent="grok", checker="chatgpt")
    _stop(conn, "t", "do", "grok", code="overdue")
    assert takeover.words(_decide(conn)) == "ChatGPT took over the first call · Grok Bot was overdue"


# ---------- relay rows: a takeover row stands in for the row it replaced ----------

def test_a_takeover_row_stands_in_for_its_stage_and_its_agent_is_trusted(conn):
    _relay(conn, RB)
    _stop(conn, "t-s1", "stage", "grok", code="overdue", stage=1, role="research")
    log.add_call(conn, "t-s1-takeover", "t", "stage", "chatgpt", status="done", text=GOOD_NOTE, stage=1,
                 role="research", resume_of="t-s1")
    calls = log.calls_for(conn, "t")
    first, reask, allowed = relay.stage_rows(calls, 1)
    assert first["call_id"] == "t-s1-takeover" and reask is None and allowed
    assert relay._expected_agent(first, "grok", RB, calls) == "chatgpt"
    step = relay.next_stage(log.get_task(conn, "t"), calls, RB)
    assert (step.action, step.n) == ("stage", 2)


def test_after_a_takeover_left_nobody_to_check_the_check_stage_is_never_made(conn):
    _relay(conn, COLLAB)
    _done(conn, "t-s1", "stage", "claude", text=PLAN, stage=1, role="plan")
    _done(conn, "t-s2", "stage", "chatgpt", text=AMENDED, stage=2, role="amend")
    _stop(conn, "t-s3", "stage", "claude", stage=3, role="execute")
    deliverable = "## Deliverable\nthe deliverable\n\n## Unfinished\nnone"
    log.add_call(conn, "t-s3-takeover", "t", "stage", "chatgpt", status="done", text=deliverable, stage=3,
                 role="execute", resume_of="t-s3")
    log.set_takeover(conn, "t", agents=AGENTS, agent="chatgpt", checker=None, check_state="unchecked",
                     check_note=unchecked("Claude hit its plan limit"))
    step = relay.next_stage(log.get_task(conn, "t"), log.calls_for(conn, "t"), COLLAB)
    assert (step.action, step.n, step.agent) == ("check", 3, "chatgpt")


# ---------- the manual resume counts only `-resume` rows (the owner's C3) ----------

def test_a_plan_limit_after_a_takeover_can_still_be_resumed_by_hand(conn):
    _relay(conn, RB)
    _stop(conn, "t-s1", "stage", "grok", code="overdue", stage=1, role="research")
    log.add_call(conn, "t-s1-takeover", "t", "stage", "chatgpt", status="done", text="## Sources\n- a", stage=1,
                 role="research", resume_of="t-s1")
    _stop(conn, "t-s2", "stage", "claude", stage=2, role="build")
    log.set_failed(conn, "t", "x", failed_stage=2)
    plan = resume.decide(log.get_task(conn, "t"), log.calls_for(conn, "t"), live=AGENTS, preset=RB)
    assert plan.ok and plan.substitute == "chatgpt" and plan.call_id == "t-s2-resume"


def test_the_takeovers_own_plan_limit_is_not_resumed_and_the_line_says_both_stopped(conn):
    _route(conn, skill="writing", agent="claude", checker="chatgpt")
    _stop(conn, "t", "do", "claude")
    log.add_call(conn, "t-takeover", "t", "do", "chatgpt", status="failed", text="plan limit on chatgpt: x",
                 reason_code="plan_limit", resume_of="t")
    log.set_failed(conn, "t", "x")
    task, calls = log.get_task(conn, "t"), log.calls_for(conn, "t")
    plan = resume.decide(task, calls, live=AGENTS)
    assert not plan.ok and plan.both_at_limit
    assert resume.stop_line(task, calls, live=AGENTS) == (
        f"Plan limit on chatgpt too: it took over the stopped call. #{task['n']} stays stopped; it can't be resumed.")


def test_a_process_that_ended_during_the_takeovers_call_stays_resumable_by_the_same_agent(conn):
    _route(conn, skill="writing", agent="claude", checker="chatgpt")
    _stop(conn, "t", "do", "claude")
    log.add_call(conn, "t-takeover", "t", "do", "chatgpt", status="failed", text="process ended", reason_code="process_ended",
                 resume_of="t")
    log.set_failed(conn, "t", "stopped: process ended")
    plan = resume.decide(log.get_task(conn, "t"), log.calls_for(conn, "t"), live=AGENTS)
    assert plan.ok and plan.substitute == "chatgpt" and plan.call_id == "t-takeover-resume"


def test_a_second_manual_resume_is_still_refused(conn):
    _route(conn, skill="writing", agent="claude", checker="chatgpt")
    _stop(conn, "t", "do", "claude")
    log.add_call(conn, "t-resume", "t", "do", "chatgpt", status="failed", text="plan limit on chatgpt: x",
                 reason_code="plan_limit", resume_of="t")
    log.set_failed(conn, "t", "x")
    plan = resume.decide(log.get_task(conn, "t"), log.calls_for(conn, "t"), live=AGENTS)
    assert not plan.ok and plan.reason == "it was already resumed once" and plan.both_at_limit
