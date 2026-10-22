"""Build brief 21, A2 (rules v2.30, Router for the interface, "States are fields"; decision 1 and the owner's go of 20 Oct):
`state.of(task, calls)` gives `waiting_on` (an open task: what it is blocked on) or `outcome` (an ended task), never
both, computed from the row and its calls, never stored, and never from check_note. One table-driven case per value;
the reserved values (brief 22's `probe`, `memory`, `process_ended`, and `attack`) are in the vocabulary and no row shape
reaches them. Every value here is fake."""
import json

import pytest

from router import log, plan_limit, split, state
from tests.helpers import ALL_AGENTS

AGENTS = ALL_AGENTS + ("cursor",)
OK = {"status": "ok", "label": "writing", "confidence": 0.93, "needs_split": 0.1, "tokens": 0}
NOT_ASKED = {"status": "not_asked", "tokens": 0}


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _routed(conn, tid="sr-1", *, jev=OK, agent="claude", checker="chatgpt", check_state="pending", skill="writing"):
    log.add_task(conn, tid, "t", "cli", jev)
    if agent is not None:
        log.set_route(conn, tid, agents=AGENTS, agent=agent, route_reason="best", skill=skill, skill_source="jev",
                      checker=checker, check_state=check_state)
    return tid


def _call(conn, tid, call_id, kind="do", agent="claude", status="done", **kw):
    log.add_call(conn, call_id, tid, kind, agent, status=status, text=kw.pop("text", "x" if status != "sent" else None),
                 **kw)


def _relay(conn, tid, preset, roles, *, agents=None):
    log.add_task(conn, tid, "t", "cli", NOT_ASKED, mode="relay", preset=preset)
    log.set_route(conn, tid, agents=AGENTS, agent="claude", route_reason="relay", checker=None, check_state="pending")
    for n, role in enumerate(roles, 1):
        agent = (agents or {}).get(n, "claude" if n % 2 else "chatgpt")
        _call(conn, tid, f"{tid}-s{n}", "stage", agent, stage=n, role=role)


def _of(conn, tid, **kw):
    return state.of(log.get_task(conn, tid), log.calls_for(conn, tid), **kw)


# ---------- the vocabularies ----------

def test_the_vocabularies_are_the_owners():
    assert state.WAITING_ON == ("needs_label", "split_plan", "pick", "vote_pick", "grok", "piece", "probe", "memory")
    assert state.OUTCOMES == ("passed", "fixed", "failed_check", "returned", "cancelled", "timed_out", "picked", "tie",
                              "skipped", "stopped", "unchecked", "plan_limit", "process_ended")
    assert state.RESERVED == ()  # brief 22 made process_ended (B2), probe (D1) and memory (D2) happen
    assert "check_failed" not in state.WAITING_ON + state.OUTCOMES  # The owner's Q4: a rescue is never a wait


def test_attack_is_not_a_state_word():
    """Brief 22, decision 1: nothing waits on the owner during an attack stage (`working` names the stage; an attack by Grok
    reads `grok`), so `attack` leaves the vocabulary."""
    assert "attack" not in state.WAITING_ON + state.OUTCOMES + state.RESERVED


# ---------- waiting_on: what an open task is blocked on ----------

def test_needs_label_a_task_that_came_back_for_its_label(conn):
    _routed(conn, agent=None, jev={**OK, "status": "below_floor", "confidence": 0.5})
    log.set_returned(conn, "sr-1", "returned: needs your label", reason_code="needs_label")
    assert _of(conn, "sr-1") == state.State("needs_label", None)


def test_needs_label_a_task_at_the_terminal_prompt(conn):
    _routed(conn, agent=None, jev={**OK, "status": "below_floor", "confidence": 0.5})  # Jev's row, no route, no call
    assert _of(conn, "sr-1") == state.State("needs_label", None)


def _split(conn, tid="sr-s", *, approved):
    log.add_task(conn, tid, "t", "cli", NOT_ASKED, mode="split")
    log.set_route(conn, tid, agents=AGENTS, agent="claude", route_reason="split", checker="chatgpt", check_state="pending")
    _call(conn, tid, f"{tid}-s1", "stage", "claude", stage=1, role=split.PLAN_ROLE)
    plan = split.new_plan(["one piece", "two piece"], "join them", ["sr-p1", "sr-p2"])
    plan["approved"] = approved
    log.set_split_plan(conn, tid, plan)
    log.set_split_returned(conn, tid, log.AWAITING_APPROVAL if not approved else f"{log.WAITING_PIECES} #2, #3")
    return plan


def test_split_plan_a_split_waiting_for_the_approval(conn):
    _split(conn, approved=False)
    assert _of(conn, "sr-s") == state.State("split_plan", None)


def test_piece_a_split_waiting_for_its_pieces(conn):
    _split(conn, approved=True)
    assert _of(conn, "sr-s") == state.State("piece", None)


def test_pick_a_versus_task_whose_reviews_are_in(conn):
    _relay(conn, "sr-v", "versus", ["build", "build", "review", "review"])
    log.set_awaiting_pick(conn, "sr-v")
    assert _of(conn, "sr-v") == state.State("pick", None)


def test_vote_pick_a_vote_with_no_majority(conn):
    _relay(conn, "sr-t", "vote", ["vote", "vote", "vote"], agents={1: "claude", 2: "chatgpt", 3: "grok"})
    log.set_awaiting_pick(conn, "sr-t")
    assert _of(conn, "sr-t") == state.State("vote_pick", None)


def test_grok_a_task_with_a_grok_call_out(conn):
    _routed(conn, agent="grok", skill="x_social_pulse")
    log.set_sent(conn, "sr-1", "uuid")
    assert _of(conn, "sr-1") == state.State("grok", None)


def test_grok_a_piece_held_behind_another_pieces_grok_call(conn):
    _routed(conn)
    assert _of(conn, "sr-1", held=True) == state.State("grok", None)


def test_a_task_in_progress_waits_on_nothing_and_has_not_ended(conn):
    _routed(conn)
    _call(conn, "sr-1", "sr-1")  # the doer answered; the check is next (or running)
    assert _of(conn, "sr-1") == state.State(None, None)
    assert not _of(conn, "sr-1").ended


# ---------- outcomes: how an ended task ended ----------

def _done(conn, tid, check_state, note=None, *, calls=("do", "check")):
    _routed(conn, tid)
    for k, kind in enumerate(calls):
        _call(conn, tid, f"{tid}-{k}", kind, "claude" if kind in ("do", "fix") else "chatgpt",
              verdict="PASS" if kind in ("check", "recheck") else None)
    log.set_done(conn, tid, "r", check_state=check_state, check_note=note)


@pytest.mark.parametrize("check_state, outcome", [("passed", "passed"), ("fixed", "fixed"), ("failed", "failed_check"),
                                                  ("not_needed", "unchecked"), ("unchecked", "unchecked")])
def test_a_done_task_reads_its_check(conn, check_state, outcome):
    _done(conn, "sr-1", check_state)
    assert _of(conn, "sr-1") == state.State(None, outcome)


def test_a_double_fail_is_failed_check_even_when_a_fallback_is_possible(conn):
    _done(conn, "sr-1", "failed", "not passed after one fix round", calls=("do", "check", "fix", "recheck"))
    assert _of(conn, "sr-1") == state.State(None, "failed_check")  # The owner's Q4: the offer rides beside it, not a wait


def test_a_fallback_that_stopped_on_a_plan_limit_leaves_failed_check(conn):
    _done(conn, "sr-1", "failed", "not passed after one fix round", calls=("do", "check", "fix", "recheck"))
    _call(conn, "sr-1", "sr-1-fb1", "do", "chatgpt", status="failed", reason_code=plan_limit.CODE, fallback_of="sr-1-0")
    assert _of(conn, "sr-1") == state.State(None, "failed_check")  # a stopped fallback changes nothing


@pytest.mark.parametrize("code", [c for c in log.RETURN_CODES if c != "needs_label"])
def test_returned_any_other_return(conn, code):
    _routed(conn, agent=None)
    log.set_returned(conn, "sr-1", "returned: something", reason_code=code)
    assert _of(conn, "sr-1") == state.State(None, "returned")


def test_returned_an_old_row_with_no_code_is_not_reconstructed(conn):
    _routed(conn, agent=None, jev={**OK, "status": "below_floor", "confidence": 0.5})
    log.set_returned(conn, "sr-1", "returned: needs your label")  # written before version 14: no code
    assert _of(conn, "sr-1") == state.State(None, "returned")


def test_cancelled(conn):
    _routed(conn)
    log.set_cancelled(conn, "sr-1")
    assert _of(conn, "sr-1") == state.State(None, "cancelled")


def test_timed_out(conn):
    _routed(conn, agent="grok", skill="x_social_pulse")
    log.set_sent(conn, "sr-1", "uuid", now=None)
    conn.execute("UPDATE calls SET sent_at = '2026-10-01T00:00:00+00:00'")
    log.mark_timeouts(conn)
    assert _of(conn, "sr-1") == state.State(None, "timed_out")


def test_picked_a_versus_task_after_the_pick(conn):
    _relay(conn, "sr-v", "versus", ["build", "build", "review", "review"])
    log.set_awaiting_pick(conn, "sr-v")
    log.set_pick(conn, "sr-v", agents=AGENTS, choice="a", result="A", agent="claude", checker="chatgpt", verdict="fail")
    assert _of(conn, "sr-v") == state.State(None, "picked")


def test_picked_none_on_versus(conn):
    _relay(conn, "sr-v", "versus", ["build", "build", "review", "review"])
    log.set_awaiting_pick(conn, "sr-v")
    log.set_pick(conn, "sr-v", agents=AGENTS, choice="none")
    assert _of(conn, "sr-v") == state.State(None, "picked")


@pytest.mark.parametrize("choice", ["b", "none"])
def test_tie_a_vote_with_no_majority_then_the_owners_pick(conn, choice):
    _relay(conn, "sr-t", "vote", ["vote", "vote", "vote"], agents={1: "claude", 2: "chatgpt", 3: "grok"})
    log.set_awaiting_pick(conn, "sr-t")
    log.set_vote_pick(conn, "sr-t", agents=AGENTS, choice=choice, result="x" if choice != "none" else None,
                      agent="chatgpt" if choice != "none" else None)
    assert _of(conn, "sr-t") == state.State(None, "tie")


def test_a_vote_majority_is_passed(conn):
    _relay(conn, "sr-t", "vote", ["vote", "vote", "vote"], agents={1: "claude", 2: "chatgpt", 3: "grok"})
    log.set_tally(conn, "sr-t", agents=AGENTS, agent="claude", result="Paris", note="checked-by-vote 2/1")
    assert _of(conn, "sr-t") == state.State(None, "passed")


def test_skipped_a_piece_the_split_went_on_without(conn):
    plan = _split(conn, approved=True)
    log.add_task(conn, "sr-p1", "one piece", "split", OK, mode="piece", parent="sr-s")
    log.set_route(conn, "sr-p1", agents=AGENTS, agent="claude", route_reason="best", skill="writing", checker="chatgpt",
                  check_state="pending")
    log.set_cancelled(conn, "sr-p1")
    plan["pieces"][0]["skipped"] = True
    assert _of(conn, "sr-p1", plan=plan) == state.State(None, "skipped")


def test_an_open_skipped_piece_keeps_its_own_wait(conn):
    plan = _split(conn, approved=True)
    plan["pieces"][0]["skipped"] = True
    log.add_task(conn, "sr-p1", "one piece", "split", OK, mode="piece", parent="sr-s")
    log.set_route(conn, "sr-p1", agents=AGENTS, agent="grok", route_reason="best", skill="x_social_pulse",
                  checker="chatgpt", check_state="pending")
    log.set_sent(conn, "sr-p1", "uuid")
    assert _of(conn, "sr-p1", plan=plan) == state.State("grok", None)


def test_stopped_a_failed_first_call(conn):
    _routed(conn)
    _call(conn, "sr-1", "sr-1", status="failed", text="unexpected error: RuntimeError")
    log.set_failed(conn, "sr-1", "unexpected error: RuntimeError")
    assert _of(conn, "sr-1") == state.State(None, "stopped")


def test_stopped_a_chain_that_failed_at_a_stage(conn):
    _relay(conn, "sr-r", "research-build", ["research"], agents={1: "grok"})
    log.set_failed(conn, "sr-r", "relay failed at stage 1", failed_stage=1)
    assert _of(conn, "sr-r") == state.State(None, "stopped")


def test_plan_limit_a_first_call_stopped_on_the_plan_limit(conn):
    _routed(conn)
    _call(conn, "sr-1", "sr-1", status="failed", text="limit", reason_code=plan_limit.CODE)
    log.set_failed(conn, "sr-1", "limit")
    assert _of(conn, "sr-1") == state.State(None, "plan_limit")


def test_plan_limit_a_check_round_stopped_on_the_plan_limit(conn):
    _routed(conn)
    _call(conn, "sr-1", "sr-1")
    _call(conn, "sr-1", "sr-1-c1", "check", "chatgpt", status="failed", text="limit", reason_code=plan_limit.CODE)
    log.set_done(conn, "sr-1", "r", check_state="unchecked", check_note="check round by chatgpt didn't run: limit")
    assert _of(conn, "sr-1") == state.State(None, "plan_limit")


def test_plan_limit_a_versus_stage_stopped_on_the_plan_limit(conn):
    _relay(conn, "sr-v", "versus", ["build"])
    _call(conn, "sr-v", "sr-v-s2", "stage", "chatgpt", status="failed", text="limit", stage=2, role="build",
          reason_code=plan_limit.CODE)
    log.set_failed(conn, "sr-v", "relay failed at stage 2", failed_stage=2)
    assert _of(conn, "sr-v") == state.State(None, "plan_limit")


# ---------- never check_note; never both; the reserved values unreachable ----------

def test_check_note_is_never_read(conn):
    _done(conn, "sr-1", "passed", "awaiting pick")
    assert _of(conn, "sr-1") == state.State(None, "passed")
    plan = _split(conn, approved=False)
    conn.execute("UPDATE tasks SET check_note = 'picked a; review by claude: pass' WHERE task_id = 'sr-s'")
    assert _of(conn, "sr-s") == state.State("split_plan", None)


def _every_shape(conn):
    """One row of every shape above, for the sweep."""
    shapes = []
    for i, check_state in enumerate(("passed", "fixed", "failed", "not_needed", "unchecked")):
        _done(conn, f"sr-d{i}", check_state)
        shapes.append(f"sr-d{i}")
    _split(conn, "sr-sa", approved=False)
    _split(conn, "sr-sb", approved=True)
    _relay(conn, "sr-v", "versus", ["build", "build", "review", "review"])
    log.set_awaiting_pick(conn, "sr-v")
    _routed(conn, "sr-g", agent="grok", skill="x_social_pulse")
    log.set_sent(conn, "sr-g", "uuid")
    _routed(conn, "sr-q")
    _routed(conn, "sr-c")
    log.set_cancelled(conn, "sr-c")
    return shapes + ["sr-sa", "sr-sb", "sr-v", "sr-g", "sr-q", "sr-c"]


def test_no_row_shape_is_both_open_and_ended_or_reaches_a_reserved_value(conn):
    for tid in _every_shape(conn):
        got = _of(conn, tid)
        assert not (got.waiting_on and got.outcome), tid
        assert got.waiting_on in state.WAITING_ON + (None,) and got.outcome in state.OUTCOMES + (None,), tid
        assert got.waiting_on not in state.RESERVED and got.outcome not in state.RESERVED, tid


def test_the_state_is_never_stored(conn):
    _done(conn, "sr-1", "passed")
    assert "waiting_on" not in log.get_task(conn, "sr-1").keys() and "outcome" not in log.get_task(conn, "sr-1").keys()


def test_as_dict(conn):
    _done(conn, "sr-1", "fixed")
    assert json.loads(json.dumps(_of(conn, "sr-1").as_dict())) == {"waiting_on": None, "outcome": "fixed"}
