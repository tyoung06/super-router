"""The small UI cleanup brief, row 1: `steps` on `task_view`, so `sr log --json` and `sr show --json` both carry it. `chain`
is the task's own filled chain (for_task's left-out attack2, project shape and plan shape all hold), with the check step
added only when the preset has a checker and the row names one; null for Route, a route piece and a preset that can't be
read. `now` is the call in progress and not yet logged, shaped like a call row, since a running Claude, ChatGPT or Cursor
call has no row until it ends. The whole key is null for Auto. Worked out each time, never stored: `log.VERSION` stays 21.
Fakes only; every value here is fake."""
import json

import pytest

from router import __main__ as cli
from router import jsonview, log, presets, relay, split
from tests.fixtures import json_shapes
from tests.helpers import shipped_roster
from tests.test_json_actions import FAKE_ENV, World, jev  # noqa: F401
from tests.test_loop import Scripted
from tests.test_redteam_chain import BUILD
from tests.test_relay import Chat

ROSTER = shipped_roster()
LOADED = presets.load_presets(ROSTER, tuple(cli.SENDERS), relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
PLAN_RECORD = {"steps": [], "needs": [], "menu": [], "base": "abc"}


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    return World(monkeypatch, tmp_path, capsys)


def _relay(conn, preset, tid="sr-1", slots=None, project=None, checker="chatgpt", agent="claude", mode="relay", parent=None, **kw):
    log.add_task(conn, tid, "a task", "cli", {"status": "not_asked", "tokens": 0}, mode=mode, preset=preset, slots=slots,
                 project=project, parent=parent, **kw)
    log.set_route(conn, tid, agents=ROSTER.names, agent=agent, route_reason="relay", checker=checker,
                  check_state="pending" if checker else "not_needed")
    return log.get_task(conn, tid)


def _steps(conn, tid="sr-1", loaded=LOADED):
    return jsonview.task_view(conn, log.get_task(conn, tid), loaded=loaded)["steps"]


def _chain(steps):
    return [(s["stage"], s["role"], s["agent"]) for s in steps["chain"]]


# ---------- the chain ----------

def test_research_build_is_its_stages_then_the_check(conn):
    _relay(conn, "research-build")
    assert _chain(_steps(conn)) == [(1, "research", "grok"), (2, "build", "claude"), (None, "check", "chatgpt")]


def test_collab_off_a_project_ends_with_its_edit_stage_and_no_check_step(conn):
    _relay(conn, "collab", checker=None)
    assert _chain(_steps(conn)) == [(1, "plan", "claude"), (2, "amend", "chatgpt"), (3, "execute", "claude"), (4, "edit", "chatgpt")]


def test_collab_on_a_project_never_runs_its_edit_stage_and_has_the_check(conn):
    _relay(conn, "collab", project="garden")
    assert _chain(_steps(conn)) == [(1, "plan", "claude"), (2, "amend", "chatgpt"), (3, "execute", "claude"), (None, "check", "chatgpt")]


def test_redteam_has_both_attackers_when_the_row_filled_them(conn):
    _relay(conn, "redteam", slots={"build": "claude", "attack": "chatgpt", "attack2": "cursor", "check": "chatgpt"})
    assert _chain(_steps(conn)) == [(1, "build", "claude"), (2, "attack", "chatgpt"), (3, "attack", "cursor"), (4, "revise", "claude"),
                                    (None, "check", "chatgpt")]


def test_a_left_out_second_attacker_is_not_in_the_chain(conn):
    _relay(conn, "redteam", slots={"build": "claude", "attack": "chatgpt", "attack2": None, "check": "chatgpt"})
    assert _chain(_steps(conn)) == [(1, "build", "claude"), (2, "attack", "chatgpt"), (3, "revise", "claude"), (None, "check", "chatgpt")]


def test_filled_slots_name_the_tasks_own_agents_not_the_defaults(conn):
    _relay(conn, "versus", slots={"a": "claude", "b": "cursor"}, checker=None)
    chain = _chain(_steps(conn))
    assert chain[1] == (2, "build", "cursor") and all(step[1] != "check" for step in chain)


def test_a_plan_runs_its_plan_shape(conn):
    log.add_task(conn, "sr-1", "a plan", "cli", {"status": "not_asked", "tokens": 0}, mode="plan", preset="redteam",
                 project="garden", plan=PLAN_RECORD,
                 slots={"build": "claude", "attack": "chatgpt", "attack2": "cursor", "check": "chatgpt"})
    log.set_route(conn, "sr-1", agents=ROSTER.names, agent="claude", route_reason="relay", checker="chatgpt", check_state="pending")
    assert _chain(_steps(conn)) == [(1, "plan", "claude"), (2, "attack", "chatgpt"), (3, "attack", "cursor"), (4, "revise", "claude"),
                                    (None, "check", "chatgpt")]


def test_a_split_is_its_plan_its_join_and_the_check(conn):
    log.add_task(conn, "sr-1", "a split", "cli", {"status": "not_asked", "tokens": 0}, mode="split")
    log.set_route(conn, "sr-1", agents=ROSTER.names, agent="claude", route_reason="split", checker="chatgpt", check_state="pending")
    assert _chain(_steps(conn)) == [(1, split.PLAN_ROLE, "claude"), (2, split.INTEGRATE_ROLE, "claude"), (None, "check", "chatgpt")]


def test_a_split_delivered_unchecked_has_no_check_step(conn):
    log.add_task(conn, "sr-1", "a split", "cli", {"status": "not_asked", "tokens": 0}, mode="split")
    log.set_route(conn, "sr-1", agents=ROSTER.names, agent="claude", route_reason="split", checker=None, check_state="unchecked")
    assert [s[1] for s in _chain(_steps(conn))] == [split.PLAN_ROLE, split.INTEGRATE_ROLE]


@pytest.mark.parametrize("preset, slots", [("versus", {"a": "claude", "b": "chatgpt"}), ("vote", {"a": "claude", "b": "chatgpt", "c": "grok"})])
def test_versus_and_vote_have_no_check_step(conn, preset, slots):
    _relay(conn, preset, slots=slots, checker=None)
    assert all(s["role"] != "check" for s in _steps(conn)["chain"])


def test_an_unchecked_relay_with_no_checker_has_no_check_step(conn):
    _relay(conn, "research-build", checker=None)
    assert [s[1] for s in _chain(_steps(conn))] == ["research", "build"]


def test_a_route_task_has_no_chain(conn):
    log.add_task(conn, "sr-1", "a task", "cli", jev("writing"))
    log.set_route(conn, "sr-1", agents=ROSTER.names, agent="claude", route_reason="best", skill="writing", skill_source="jev",
                  checker="chatgpt", check_state="pending")
    assert _steps(conn) == {"chain": None, "now": {"kind": "do", "stage": None, "role": None, "agent": "claude"}}


def test_a_route_piece_has_no_chain_and_a_team_piece_has_its_teams(conn):
    log.add_task(conn, "sr-p", "a split", "cli", {"status": "not_asked", "tokens": 0}, mode="split")
    log.add_task(conn, "sr-1", "a piece", "cli", jev("writing"), mode="piece", parent="sr-p")
    log.set_route(conn, "sr-1", agents=ROSTER.names, agent="claude", route_reason="best", skill="writing", skill_source="jev",
                  checker="chatgpt", check_state="pending")
    assert _steps(conn)["chain"] is None
    _relay(conn, "research-build", tid="sr-2", parent="sr-p")
    assert [s[1] for s in _chain(_steps(conn, "sr-2"))] == ["research", "build", "check"]


def test_auto_has_no_steps_at_all(conn):
    log.add_task(conn, "sr-1", "a run", "cli", {"status": "not_asked", "tokens": 0}, mode="auto", project="garden",
                 auto={"plan": "sr-0", "steps": []})
    assert _steps(conn) is None


def test_a_preset_that_cant_be_read_gives_a_null_chain_with_no_error(conn):
    _relay(conn, "research-build")
    log.add_call(conn, "sr-1-s1", "sr-1", "stage", "grok", status="done", text="x", stage=1, role="research")
    assert _steps(conn, loaded=None) == {"chain": None, "now": None}


def test_a_filled_slot_that_no_longer_matches_gives_a_null_chain(conn):
    _relay(conn, "research-build", slots={"gone": "claude"})
    assert _steps(conn) == {"chain": None, "now": None}


def test_an_ended_task_keeps_its_chain_so_a_cancelled_one_shows_how_far_it_got(conn):
    _relay(conn, "research-build")
    log.set_cancelled(conn, "sr-1")
    assert [s[1] for s in _chain(_steps(conn))] == ["research", "build", "check"] and _steps(conn)["now"] is None


# ---------- now, from the rows ----------

def test_now_is_the_next_stage_and_is_shaped_like_a_call_row(conn):
    _relay(conn, "redteam", slots={"build": "claude", "attack": "chatgpt", "attack2": "cursor", "check": "chatgpt"})
    log.add_call(conn, "sr-1-s1", "sr-1", "stage", "claude", status="done", text="a build", stage=1, role="build")
    assert _steps(conn)["now"] == {"kind": "reask", "stage": 1, "role": "build", "agent": "claude"}  # its contract's one re-ask
    log.add_call(conn, "sr-1-s1r", "sr-1", "reask", "claude", status="done", text=BUILD, stage=1, role="build")
    assert _steps(conn)["now"] == {"kind": "stage", "stage": 2, "role": "attack", "agent": "chatgpt"}


def test_now_is_null_while_a_sent_row_shows_the_call(conn):
    _relay(conn, "research-build")
    log.add_call(conn, "sr-1-s1", "sr-1", "stage", "grok", status="sent", stage=1, role="research")
    assert _steps(conn)["now"] is None


def test_now_is_null_on_a_task_that_waits_on_the_owner(conn):
    log.add_task(conn, "sr-1", "a split", "cli", {"status": "not_asked", "tokens": 0}, mode="split")
    log.set_route(conn, "sr-1", agents=ROSTER.names, agent="claude", route_reason="split", checker="chatgpt", check_state="pending")
    log.add_call(conn, "sr-1-s1", "sr-1", "stage", "claude", status="done", text="plan", stage=1, role=split.PLAN_ROLE)
    log.set_split_plan(conn, "sr-1", {"pieces": [], "join": "x", "approved": False})
    log.set_split_returned(conn, "sr-1", "awaiting approval")
    row = log.get_task(conn, "sr-1")
    assert row["status"] == "returned" and _steps(conn)["now"] is None


def test_now_is_null_with_no_agent_named_yet(conn):
    log.add_task(conn, "sr-1", "a task", "cli", jev("writing", 0.2, status="below_floor"))
    assert _steps(conn) == {"chain": None, "now": None}


def test_now_is_null_once_the_task_ended(conn):
    log.add_task(conn, "sr-1", "a task", "cli", jev("writing"))
    log.set_route(conn, "sr-1", agents=ROSTER.names, agent="claude", route_reason="best", skill="writing", skill_source="jev",
                  checker="chatgpt", check_state="pending")
    log.add_call(conn, "sr-1", "sr-1", "do", "claude", status="done", text="done")
    log.set_done(conn, "sr-1", "done", check_state="passed")
    assert _steps(conn) == {"chain": None, "now": None}


def test_the_next_step_of_a_routed_task_comes_from_its_check_loop(conn):
    log.add_task(conn, "sr-1", "a task", "cli", jev("writing"))
    log.set_route(conn, "sr-1", agents=ROSTER.names, agent="claude", route_reason="best", skill="writing", skill_source="jev",
                  checker="chatgpt", check_state="pending")
    log.add_call(conn, "sr-1", "sr-1", "do", "claude", status="done", text="draft")
    assert _steps(conn)["now"] == {"kind": "check", "stage": None, "role": None, "agent": "chatgpt"}
    log.add_call(conn, "sr-1-c1", "sr-1", "check", "chatgpt", status="done", text="FIX\n1. [must] Rhyme.", verdict="FIX")
    assert _steps(conn)["now"] == {"kind": "fix", "stage": None, "role": None, "agent": "claude"}
    log.add_call(conn, "sr-1-f1", "sr-1", "fix", "claude", status="done", text="better")
    assert _steps(conn)["now"] == {"kind": "recheck", "stage": None, "role": None, "agent": "chatgpt"}


# ---------- now, read from inside a real command's call: the no-row case, with no model ----------

def test_now_from_inside_each_call_of_a_real_route(world):
    seen = []

    def peek(reply, fake):
        def call(prompt, **kwargs):
            conn = log.open_read_only(cli.DB_PATH)
            try:
                row = log.task_by_number(conn, 1)
                seen.append((jsonview.task_view(conn, row, loaded=LOADED)["steps"], len(log.calls_for(conn, row["task_id"]))))
            finally:
                conn.close()
            return fake(prompt, **kwargs)
        return call

    claude, chat = Scripted("Draft one.", "Draft two."), Chat("FIX\n1. Make it rhyme.", "PASS")
    world.worker, world.chatgpt = peek("do", claude), peek("check", chat)
    world.json("route", "write a two-line poem")
    assert [(s["now"]["kind"], s["now"]["agent"], rows) for s, rows in seen] == [
        ("do", "claude", 0), ("check", "chatgpt", 1), ("fix", "claude", 2), ("recheck", "chatgpt", 3)]


def test_now_from_inside_each_stage_of_a_real_relay(world):
    seen = []
    build, check = "## Plan\n1. A step, checked.\n\n## Open questions\nnone\n", "PASS"

    def peek(fake):
        def call(prompt, **kwargs):
            conn = log.open_read_only(cli.DB_PATH)
            try:
                row = log.task_by_number(conn, 1)
                steps = jsonview.task_view(conn, row, loaded=LOADED)["steps"]
                seen.append((steps["now"]["kind"], steps["now"]["stage"], steps["now"]["role"], steps["now"]["agent"]))
                assert steps["chain"][0]["role"] == "plan"
            finally:
                conn.close()
            return fake(prompt, **kwargs)
        return call

    from tests.test_collab import AMENDED, DELIVERABLE, EDITED, PLAN
    world.worker, world.chatgpt = peek(Scripted(PLAN, DELIVERABLE)), peek(Chat(AMENDED, EDITED))
    world.json("relay", "collab", "write a short spec")
    assert seen == [("stage", 1, "plan", "claude"), ("stage", 2, "amend", "chatgpt"), ("stage", 3, "execute", "claude"),
                    ("stage", 4, "edit", "chatgpt")]


# ---------- what it doesn't change ----------

def test_the_log_version_stays_21():
    assert log.VERSION == 21


def test_both_reads_carry_it_and_the_shape_holds(world):
    world.worker, world.chatgpt = Scripted("Draft."), Chat("PASS")
    world.json("route", "write a two-line poem")
    code, out, _ = world.run("show", "1", "--json")
    shown = json.loads(out)
    json_shapes.check(shown, json_shapes.SHOW)
    code, out, _ = world.run("log", "--json")
    logged = json.loads(out)
    json_shapes.check(logged, json_shapes.LOG)
    assert shown["steps"] == logged["tasks"][0]["steps"] == {"chain": None, "now": None}


def test_working_keeps_its_two_keys(conn):
    _relay(conn, "research-build")
    assert jsonview.task_view(conn, log.get_task(conn, "sr-1"), loaded=LOADED)["working"] == {
        "agent": "grok", "doing": "stage 1 of 2 (research)"}
