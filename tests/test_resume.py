"""Phase B of build brief 7: `router/resume.py` decides from the log alone whether a task stopped by
a plan limit can be resumed, and who does what (rules v2.15, Resume). Pure: no agent is called."""
import pytest

from router import log, relay, resume
from tests.helpers import ALL_AGENTS
from tests.test_collab import LOADED

LIVE = ("claude", "grok", "chatgpt")
LIMIT = "plan limit on claude: You've hit your session limit"
RB, COLLAB = LOADED.presets["research-build"], LOADED.presets["collab"]


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _route(conn, tid, *, skill, agent, checker, state="pending", reason="best"):
    jev = {"status": "ok", "label": skill, "confidence": 0.9, "needs_split": 0.1, "tokens": 0}
    log.add_task(conn, tid, "a task", "cli", jev)
    log.set_route(conn, tid, agents=ALL_AGENTS, agent=agent, route_reason=reason, skill=skill, skill_source="jev",
                  checker=checker, check_state=state)


def _relay(conn, tid, preset):
    log.add_task(conn, tid, "a task", "cli", {"status": "not_asked", "tokens": 0}, mode="relay", preset=preset.name)
    log.set_route(conn, tid, agents=ALL_AGENTS, agent=preset.doer, route_reason="relay", checker=preset.check_agent,
                  check_state="pending")


def _call(conn, call_id, tid, kind, agent, status="done", text="ok", **kw):
    log.add_call(conn, call_id, tid, kind, agent, status=status, text=text, **kw)


def _stop(conn, call_id, tid, kind, agent, **kw):
    _call(conn, call_id, tid, kind, agent, status="failed", text=f"plan limit on {agent}: x", reason_code="plan_limit", **kw)


def _decide(conn, tid, live=LIVE, preset=None):
    return resume.decide(log.get_task(conn, tid), log.calls_for(conn, tid), live=live, preset=preset)


def _failed_do(conn, tid, agent, **route):
    _route(conn, tid, agent=agent, **route)
    _stop(conn, tid, tid, "do", agent)
    log.set_failed(conn, tid, f"plan limit on {agent}: x")


# ---------- eligibility, in the brief's order, each with its own reason ----------

def test_an_open_task_is_refused(conn):
    _route(conn, "t", skill="writing", agent="claude", checker="chatgpt")
    plan = _decide(conn, "t")
    assert not plan.ok and "still open" in plan.reason and "sr check" in plan.reason


@pytest.mark.parametrize("status", ["cancelled", "timed_out"])
def test_a_cancelled_or_timed_out_task_is_refused(conn, status):
    _route(conn, "t", skill="writing", agent="claude", checker="chatgpt")
    if status == "cancelled":
        log.set_cancelled(conn, "t")
    else:
        log.set_sent(conn, "t", "uuid")
        log._move(conn, "t", ("sent",), "timed_out")
    plan = _decide(conn, "t")
    assert not plan.ok and f"it is {status}" in plan.reason and "only a task stopped by a plan limit" in plan.reason


def test_a_task_that_finished_with_every_round_run_is_refused(conn):
    _route(conn, "t", skill="writing", agent="claude", checker="chatgpt")
    _call(conn, "t", "t", "do", "claude")
    _call(conn, "t-c1", "t", "check", "chatgpt", text="PASS", verdict="PASS")
    log.set_done(conn, "t", "ok", check_state="passed")
    plan = _decide(conn, "t")
    assert not plan.ok and "it is done" in plan.reason


def test_a_stop_that_is_not_a_plan_limit_is_refused_with_its_reason(conn):
    _route(conn, "t", skill="writing", agent="claude", checker="chatgpt")
    _call(conn, "t", "t", "do", "claude", status="failed", text="claude exited 1: boom")
    log.set_failed(conn, "t", "claude exited 1: boom")
    plan = _decide(conn, "t")
    assert not plan.ok and plan.reason == "not a plan limit: claude exited 1: boom"


def test_a_failed_task_from_before_version_6_has_no_row_and_is_not_a_plan_limit(conn):
    _route(conn, "t", skill="writing", agent="claude", checker="chatgpt")
    log.set_failed(conn, "t", "claude exited 1: ")
    plan = _decide(conn, "t")
    assert not plan.ok and plan.reason == "not a plan limit: claude exited 1:"


def test_a_grok_call_is_never_resumed(conn):
    _relay(conn, "t", RB)
    _stop(conn, "t-s1", "t", "stage", "grok", stage=1, role="research")
    log.set_failed(conn, "t", "x", failed_stage=1)
    plan = _decide(conn, "t", preset=RB)
    assert not plan.ok and "only Claude and ChatGPT can be resumed" in plan.reason and "grok" in plan.reason


def test_an_override_task_is_never_resumed(conn):
    _failed_do(conn, "t", "claude", skill="writing", checker="chatgpt", reason="override")
    plan = _decide(conn, "t")
    assert not plan.ok and "override" in plan.reason and "run it again" in plan.reason


def test_a_task_resumed_once_is_not_resumed_again(conn):
    _failed_do(conn, "t", "claude", skill="writing", checker="chatgpt")
    log._move(conn, "t", ("failed",), "queued")
    _stop(conn, "t-resume", "t", "do", "chatgpt", resume_of="t")
    log.set_failed(conn, "t", "plan limit on chatgpt: x")
    plan = _decide(conn, "t")
    assert not plan.ok and plan.reason == "it was already resumed once" and plan.both_at_limit


def test_the_substitute_must_be_live(conn):
    _failed_do(conn, "t", "claude", skill="writing", checker="chatgpt")
    plan = _decide(conn, "t", live=("claude", "grok"))
    assert not plan.ok and plan.reason == "chatgpt isn't live, so it can't take over"


def _collab_up_to_stage_4(conn, tid, stage3_agent="claude"):
    _relay(conn, tid, COLLAB)
    _call(conn, f"{tid}-s1", tid, "stage", "claude", stage=1, role="plan")
    _call(conn, f"{tid}-s2", tid, "stage", "chatgpt", stage=2, role="amend")
    _call(conn, f"{tid}-s3", tid, "stage", stage3_agent, stage=3, role="execute")


def test_a_check_stage_is_refused_when_the_substitute_made_the_stage_before(conn):
    _collab_up_to_stage_4(conn, "t")
    _stop(conn, "t-s4", "t", "stage", "chatgpt", stage=4, role="edit")
    log.set_failed(conn, "t", "x", failed_stage=4)
    plan = _decide(conn, "t", preset=COLLAB)
    assert not plan.ok
    assert plan.reason == "claude made stage 3, so it can't check it; stage 3's result stays unchecked"


def test_a_check_round_is_refused_when_the_substitute_did_the_work(conn):
    """D4: that result was already delivered unchecked; a resume would change nothing."""
    _route(conn, "t", skill="writing", agent="claude", checker="chatgpt")
    _call(conn, "t", "t", "do", "claude")
    _stop(conn, "t-c1", "t", "check", "chatgpt")
    log.set_done(conn, "t", "ok", check_state="unchecked", check_note="check round by chatgpt didn't run: x")
    plan = _decide(conn, "t")
    assert not plan.ok and plan.reason == "claude did the work, so it can't check it; the result stays unchecked"


# ---------- who does what ----------

def test_a_quick_answer_doer_is_replaced_and_nothing_is_checked(conn):
    _failed_do(conn, "t", "claude", skill="quick_answer", checker=None, state="not_needed")
    plan = _decide(conn, "t")
    assert plan.ok and (plan.stopped_agent, plan.substitute, plan.agent, plan.checker) == ("claude", "chatgpt", "chatgpt", None)
    assert (plan.kind, plan.call_id, plan.check_state, plan.swapped) == ("do", "t-resume", "not_needed", False)


def test_the_checker_swaps_when_the_substitute_would_check_its_own_work(conn):
    _failed_do(conn, "t", "claude", skill="writing", checker="chatgpt")
    plan = _decide(conn, "t")
    assert plan.ok and (plan.agent, plan.checker, plan.swapped, plan.check_state) == ("chatgpt", "claude", True, "pending")


def test_a_chatgpt_doer_is_replaced_by_claude_and_chatgpt_checks(conn):
    _failed_do(conn, "t", "chatgpt", skill="web_research", checker="claude")
    plan = _decide(conn, "t")
    assert plan.ok and (plan.substitute, plan.agent, plan.checker, plan.swapped) == ("claude", "claude", "chatgpt", True)


def test_a_grok_checker_stays(conn):
    _failed_do(conn, "t", "claude", skill="bulk_text", checker="grok")
    plan = _decide(conn, "t")
    assert plan.ok and (plan.agent, plan.checker, plan.swapped) == ("chatgpt", "grok", False)


def test_an_unchecked_task_stays_unchecked_with_its_note(conn):
    _failed_do(conn, "t", "claude", skill="writing", checker="muse", state="unchecked")
    plan = _decide(conn, "t")
    assert plan.ok and (plan.checker, plan.check_state) == ("muse", "unchecked")


def test_a_stopped_check_round_goes_to_the_other_builder_when_it_did_not_do_the_work(conn):
    _route(conn, "t", skill="x_social_pulse", agent="grok", checker="chatgpt")
    _call(conn, "t", "t", "do", "grok")
    _stop(conn, "t-c1", "t", "check", "chatgpt")
    log.set_done(conn, "t", "ok", check_state="unchecked", check_note="check round by chatgpt didn't run: x")
    plan = _decide(conn, "t")
    assert plan.ok and (plan.kind, plan.call_id, plan.agent, plan.checker) == ("check", "t-c1-resume", "grok", "claude")
    assert (plan.check_state, plan.check_note) == ("pending", None)


def test_a_stopped_fix_goes_to_the_substitute_and_the_recheck_swaps(conn):
    _route(conn, "t", skill="writing", agent="claude", checker="chatgpt")
    _call(conn, "t", "t", "do", "claude")
    _call(conn, "t-c1", "t", "check", "chatgpt", text="FIX\n1. a", verdict="FIX")
    _stop(conn, "t-f1", "t", "fix", "claude")
    log.set_done(conn, "t", "ok", check_state="failed", check_note="fix round by claude didn't run: x")
    plan = _decide(conn, "t")
    assert plan.ok and (plan.kind, plan.agent, plan.checker, plan.swapped, plan.check_state) == (
        "fix", "chatgpt", "claude", True, "pending")


def test_a_stopped_recheck_goes_to_the_other_builder_when_it_did_not_fix(conn):
    _route(conn, "t", skill="x_social_pulse", agent="grok", checker="chatgpt")
    _call(conn, "t", "t", "do", "grok")
    _call(conn, "t-c1", "t", "check", "chatgpt", text="FIX\n1. a", verdict="FIX")
    _call(conn, "t-f1", "t", "fix", "grok")
    _stop(conn, "t-c2", "t", "recheck", "chatgpt")
    log.set_done(conn, "t", "ok", check_state="unchecked")
    plan = _decide(conn, "t")
    assert plan.ok and (plan.kind, plan.checker) == ("recheck", "claude")


def test_a_relay_build_stage_is_replaced_and_the_presets_checker_swaps(conn):
    _relay(conn, "t", RB)
    _call(conn, "t-s1", "t", "stage", "grok", stage=1, role="research")
    _stop(conn, "t-s2", "t", "stage", "claude", stage=2, role="build")
    log.set_failed(conn, "t", "x", failed_stage=2)
    plan = _decide(conn, "t", preset=RB)
    assert plan.ok and (plan.kind, plan.stage, plan.role, plan.call_id) == ("stage", 2, "build", "t-s2-resume")
    assert (plan.agent, plan.checker, plan.swapped, plan.check_state) == ("chatgpt", "claude", True, "pending")


def test_a_stopped_reask_is_replaced_by_a_fresh_stage(conn):
    """D8 (the owner): the substitute gets the stage prompt, never the re-ask with the stopped agent's result."""
    _relay(conn, "t", RB)
    _call(conn, "t-s1", "t", "stage", "grok", stage=1, role="research")
    _call(conn, "t-s2", "t", "stage", "claude", stage=2, role="build")
    _stop(conn, "t-s2r", "t", "reask", "claude", stage=2, role="build")
    log.set_failed(conn, "t", "x", failed_stage=2)
    plan = _decide(conn, "t", preset=RB)
    assert plan.ok and (plan.kind, plan.stage, plan.call_id) == ("stage", 2, "t-s2r-resume")


def test_collab_stage_3_resumed_moves_the_check_stage_to_claude(conn):
    """D5: ChatGPT builds, so ChatGPT can't take the check stage; the other builder does."""
    _relay(conn, "t", COLLAB)
    _call(conn, "t-s1", "t", "stage", "claude", stage=1, role="plan")
    _call(conn, "t-s2", "t", "stage", "chatgpt", stage=2, role="amend")
    _stop(conn, "t-s3", "t", "stage", "claude", stage=3, role="execute")
    log.set_failed(conn, "t", "x", failed_stage=3)
    plan = _decide(conn, "t", preset=COLLAB)
    assert plan.ok and (plan.agent, plan.checker, plan.swapped) == ("chatgpt", "claude", True)


@pytest.mark.parametrize("n, role, stopped, sub", [(1, "plan", "claude", "chatgpt"), (2, "amend", "chatgpt", "claude")])
def test_an_earlier_collab_stage_leaves_the_builder_and_the_check_stage_as_they_are(conn, n, role, stopped, sub):
    _relay(conn, "t", COLLAB)
    if n == 2:
        _call(conn, "t-s1", "t", "stage", "claude", stage=1, role="plan")
    _stop(conn, f"t-s{n}", "t", "stage", stopped, stage=n, role=role)
    log.set_failed(conn, "t", "x", failed_stage=n)
    plan = _decide(conn, "t", preset=COLLAB)
    assert plan.ok and (plan.substitute, plan.agent, plan.checker, plan.swapped) == (sub, "claude", "chatgpt", False)


# ---------- the words the owner sees before it runs ----------

def test_the_plan_names_the_stopped_call_the_substitute_and_the_checker(conn):
    _failed_do(conn, "t", "claude", skill="writing", checker="chatgpt")
    lines = resume.describe(log.get_task(conn, "t"), _decide(conn, "t"))
    assert lines == [
        "Resuming #1 t: the first call by claude stopped on its plan limit.",
        "chatgpt does it instead, with what claude was sent.",
        "Checker: claude (chatgpt would otherwise check its own work).",
    ]


def test_the_plan_for_a_relay_stage_and_a_quick_answer(conn):
    _relay(conn, "t", RB)
    _call(conn, "t-s1", "t", "stage", "grok", stage=1, role="research")
    _stop(conn, "t-s2", "t", "stage", "claude", stage=2, role="build")
    log.set_failed(conn, "t", "x", failed_stage=2)
    lines = resume.describe(log.get_task(conn, "t"), _decide(conn, "t", preset=RB))
    assert lines[0] == "Resuming #1 t: stage 2 (build) by claude stopped on its plan limit."
    _failed_do(conn, "q", "claude", skill="quick_answer", checker=None, state="not_needed")
    assert resume.describe(log.get_task(conn, "q"), _decide(conn, "q"))[-1] == "No check: a quick answer is never checked."


def test_other_builder_is_claude_and_chatgpt_only():
    assert (relay.other_builder("claude"), relay.other_builder("chatgpt"), relay.other_builder("grok")) == (
        "chatgpt", "claude", None)
