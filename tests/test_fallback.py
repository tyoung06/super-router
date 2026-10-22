"""Build brief 10, phase A (rules v2.17, Fallback): eligibility and resolution from the log alone
(router/fallback.py), the view rule (log.fallback_view), the redo's prompt and the never-the-failed-result
guard, and log version 8 (`calls.fallback_of`). Every value here is fake."""
import sqlite3

import pytest

from router import __main__ as cli
from router import fallback, log, presets, relay
from tests.helpers import V13_CALLS_SCHEMA, V13_SCHEMA, roster_with, shipped_roster

LOADED = presets.load_presets(shipped_roster(), tuple(cli.SENDERS), relay.CONTRACTS, roles=relay.ROLES,
                              verdicts=relay.VERDICTS)
AGENTS = ("claude", "grok", "chatgpt", "muse")
LIVE = ("claude", "grok", "chatgpt")
TASK = "Write a haiku about seed trays."
FIRST, FIXED = "FIRST-RESULT-x91: trays in the morning", "FIXED-RESULT-x92: trays at dawn"
FINAL = "FIX\n- line 2 has 8 syllables\n- no season word\n- title missing"
NOTE = "## Findings\n- a\n- b\n- c\n## Sources\n- https://a.example\n- https://b.example\n- https://c.example\n## Gaps\nnone"
JEV = {"status": "ok", "label": "writing", "confidence": 0.9, "needs_split": 0.1, "tokens": 10}


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _route(conn, tid="sr-1", skill="writing", doer="claude", checker="chatgpt", reason="best", recheck=FINAL,
           state="failed", fix="done"):
    log.add_task(conn, tid, TASK, "cli", {**JEV, "label": skill})
    log.set_route(conn, tid, agents=AGENTS, agent=doer, route_reason=reason, skill=skill, skill_source="jev",
                  checker=checker, check_state="pending")
    log.add_call(conn, tid, tid, "do", doer, "done", text=FIRST)
    log.add_call(conn, f"{tid}-c1", tid, "check", checker, "done", text="FIX\n- too long", verdict="FIX")
    log.add_call(conn, f"{tid}-f1", tid, "fix", doer, fix, text=FIXED if fix == "done" else "claude exited 1")
    if recheck is not None:
        log.add_call(conn, f"{tid}-c2", tid, "recheck", checker, "done", text=recheck,
                     verdict="PASS" if recheck.startswith("PASS") else "FIX")
    log.set_done(conn, tid, FIXED, check_state=state, check_note="not passed after one fix round")
    return log.get_task(conn, tid)


def _research(conn, tid="sr-r"):
    log.add_task(conn, tid, TASK, "cli", {"status": "not_asked", "tokens": 0}, mode="relay", preset="research-build")
    log.set_route(conn, tid, agents=AGENTS, agent="claude", route_reason="relay", checker="chatgpt", check_state="pending")
    log.add_call(conn, f"{tid}-s1", tid, "stage", "grok", "done", text=NOTE, stage=1, role="research")
    log.add_call(conn, f"{tid}-s2", tid, "stage", "claude", "done", text=FIRST, stage=2, role="build")
    log.add_call(conn, f"{tid}-c1", tid, "check", "chatgpt", "done", text="FIX\n- a price", verdict="FIX")
    log.add_call(conn, f"{tid}-f1", tid, "fix", "claude", "done", text=FIXED)
    log.add_call(conn, f"{tid}-c2", tid, "recheck", "chatgpt", "done", text=FINAL, verdict="FIX")
    log.set_done(conn, tid, FIXED, check_state="failed", check_note="not passed after one fix round")
    return log.get_task(conn, tid)


PLAN = "## Plan\n1. a\n2. b\n3. c\n## Open questions\nnone"
AMENDED = "## Changes\nnone\n## Plan\n1. a\n2. b\n3. c"
BUILT = f"## Deliverable\n{FIRST}\n## Unfinished\nnone"
EDITED = f"## Deliverable\n{FIXED}\n## Edits\n- shortened\n## Unresolved\n- no season word\n- title missing"


def _collab(conn, tid="sr-c", unresolved=None):
    log.add_task(conn, tid, TASK, "cli", {"status": "not_asked", "tokens": 0}, mode="relay", preset="collab")
    log.set_route(conn, tid, agents=AGENTS, agent="claude", route_reason="relay", checker="chatgpt", check_state="pending")
    for n, agent, role, text in ((1, "claude", "plan", PLAN), (2, "chatgpt", "amend", AMENDED),
                                 (3, "claude", "execute", BUILT), (4, "chatgpt", "edit", unresolved or EDITED)):
        log.add_call(conn, f"{tid}-s{n}", tid, "stage", agent, "done", text=text, stage=n, role=role)
    edited = unresolved or EDITED
    state = relay.check_verdict(edited)
    log.set_done(conn, tid, relay.check_parts(edited)[0], check_state=state, check_note="checked-by-stage 4")
    return log.get_task(conn, tid)


def _decide(conn, row, live=LIVE):
    preset = LOADED.presets.get(row["preset"]) if row["mode"] == "relay" else None
    return fallback.decide(row, log.calls_for(conn, row["task_id"]), live=live, preset=preset)


# ---------- resolution: the three task kinds ----------

def test_a_routed_double_fail_swaps_the_pair_and_reads_the_stored_fix_list(conn):
    plan = _decide(conn, _route(conn))
    assert plan.ok, plan.reason
    assert (plan.kind, plan.doer, plan.original, plan.checker, plan.check_stage) == (
        "routed", "chatgpt", "claude", "claude", False)
    assert plan.fix_list == "- line 2 has 8 syllables\n- no season word\n- title missing" and plan.fix_lines == 3
    assert plan.replaces["call_id"] == "sr-1" and plan.call_id == "sr-1-fb1"
    assert (plan.stage, plan.role, plan.input_stage) == (None, None, None)
    assert set(plan.failed_texts) == {FIRST, FIXED}


def test_research_build_redoes_stage_2_from_the_stored_note_with_chatgpt_and_claude_checks(conn):
    plan = _decide(conn, _research(conn))
    assert plan.ok, plan.reason
    assert (plan.kind, plan.doer, plan.checker, plan.check_stage) == ("research-build", "chatgpt", "claude", False)
    assert (plan.replaces["call_id"], plan.stage, plan.role, plan.input_stage) == ("sr-r-s2", 2, "build", 1)
    assert NOTE not in plan.failed_texts and FIRST in plan.failed_texts and FIXED in plan.failed_texts


def test_collab_redoes_stage_3_from_the_stored_amended_plan_and_claude_checks_as_the_check_stage(conn):
    plan = _decide(conn, _collab(conn))
    assert plan.ok, plan.reason
    assert (plan.kind, plan.doer, plan.checker, plan.check_stage) == ("collab", "chatgpt", "claude", True)
    assert (plan.replaces["call_id"], plan.stage, plan.role, plan.input_stage) == ("sr-c-s3", 3, "execute", 2)
    assert plan.fix_list == "- no season word\n- title missing"
    assert BUILT in plan.failed_texts and EDITED in plan.failed_texts and AMENDED not in plan.failed_texts


def test_r1_grok_as_the_original_doer_checks_the_redo(conn):
    plan = _decide(conn, _route(conn, skill="x_social_pulse", doer="grok", checker="chatgpt"))
    assert plan.ok and (plan.doer, plan.checker) == ("chatgpt", "grok")


def test_the_original_doer_not_live_means_the_redo_is_delivered_unchecked(conn):
    plan = _decide(conn, _route(conn), live=("chatgpt",))
    assert plan.ok and plan.checker is None
    assert "unchecked" in fallback.describe(_route(conn, tid="sr-2"), plan)[0]


# ---------- refusals, in the brief's order ----------

@pytest.mark.parametrize("make, words", [
    (lambda c: _route(c, reason="override"), "not eligible: an override task never falls back"),
    (lambda c: _route(c, skill="quick_answer"), "not eligible: a quick_answer task is never checked"),
    (lambda c: _route(c, recheck="PASS", state="fixed"), "not a double fail: it passed after one fix"),
    (lambda c: _route(c, recheck=None, state="failed", fix="failed"),
     "not a double fail: its check failed, but the fix round didn't run"),
    (lambda c: _route(c, recheck="FIX", state="failed"), "no fix list stored"),
    (lambda c: _route(c, skill="bulk_text", doer="claude", checker="grok"), "checker is grok: cannot redo"),
    (lambda c: _collab(c, unresolved=EDITED.replace("- no season word\n- title missing", "none")),
     "not a double fail: it passed"),
])
def test_each_refusal_says_why(conn, make, words):
    plan = _decide(conn, make(conn))
    assert not plan.ok and plan.reason.startswith(words), plan.reason


def test_a_passed_task_and_a_stopped_task_are_refused(conn):
    log.add_task(conn, "sr-p", TASK, "cli", JEV)
    log.set_route(conn, "sr-p", agents=AGENTS, agent="claude", route_reason="best", skill="writing",
                  checker="chatgpt", check_state="pending")
    log.add_call(conn, "sr-p", "sr-p", "do", "claude", "done", text=FIRST)
    log.add_call(conn, "sr-p-c1", "sr-p", "check", "chatgpt", "done", text="PASS", verdict="PASS")
    log.set_done(conn, "sr-p", FIRST, check_state="passed")
    assert _decide(conn, log.get_task(conn, "sr-p")).reason == "not a double fail: it passed"
    log.add_task(conn, "sr-s", TASK, "cli", JEV)
    log.set_route(conn, "sr-s", agents=AGENTS, agent="claude", route_reason="best", skill="writing",
                  checker="chatgpt", check_state="pending")
    log.set_failed(conn, "sr-s", "claude exited 1")
    assert _decide(conn, log.get_task(conn, "sr-s")).reason == "not a double fail: it is failed, so it stopped before its check"


def test_an_unchecked_task_is_refused(conn):
    row = _route(conn, state="unchecked")
    conn.execute("DELETE FROM calls WHERE call_id LIKE 'sr-1-c%' OR call_id = 'sr-1-f1'")
    conn.commit()
    assert _decide(conn, log.get_task(conn, "sr-1")).reason == "not a double fail: it ended unchecked"


def test_a_versus_task_is_refused(conn):
    log.add_task(conn, "sr-v", TASK, "cli", {"status": "not_asked", "tokens": 0}, mode="relay", preset="versus")
    log.set_route(conn, "sr-v", agents=AGENTS, agent="claude", route_reason="relay", check_state="pending")
    assert _decide(conn, log.get_task(conn, "sr-v")).reason == "not eligible: a versus task; run it again"


def test_a_checker_that_is_not_live_cannot_redo(conn):
    assert _decide(conn, _route(conn), live=("claude", "grok")).reason == "checker is chatgpt, which isn't live: cannot redo"


def test_already_fell_back_once_only_counts_a_fallback_that_came_back(conn):
    row = _route(conn)
    log.add_call(conn, "sr-1-fb1", "sr-1", "do", "chatgpt", "failed", text="plan limit on chatgpt",
                 reason_code="plan_limit", fallback_of="sr-1")
    plan = _decide(conn, row)
    assert plan.ok and plan.call_id == "sr-1-fb2"  # a stopped fallback doesn't count (R3)
    log.add_call(conn, "sr-1-fb2", "sr-1", "do", "chatgpt", "done", text="REDO", fallback_of="sr-1")
    assert _decide(conn, row).reason == "already fell back once"


# ---------- the view rule ----------

def test_the_view_drops_the_replaced_row_and_everything_after_it(conn):
    _route(conn)
    log.add_call(conn, "sr-1-fb1", "sr-1", "do", "chatgpt", "done", text="REDO", fallback_of="sr-1")
    log.add_call(conn, "sr-1-fb1-c1", "sr-1", "check", "claude", "done", text="PASS", verdict="PASS")
    calls = log.calls_for(conn, "sr-1")
    assert [c["call_id"] for c in log.fallback_view(calls)] == ["sr-1-fb1", "sr-1-fb1-c1"]
    assert log.fallback_base("sr-1", calls) == "sr-1-fb1"


def test_the_view_keeps_a_relay_tasks_earlier_stages(conn):
    _research(conn)
    log.add_call(conn, "sr-r-fb1", "sr-r", "stage", "chatgpt", "done", text="REDO", stage=2, role="build",
                 fallback_of="sr-r-s2")
    assert [c["call_id"] for c in log.fallback_view(log.calls_for(conn, "sr-r"))] == ["sr-r-s1", "sr-r-fb1"]


def test_a_stopped_fallback_row_is_never_in_the_view(conn):
    _route(conn)
    log.add_call(conn, "sr-1-fb1", "sr-1", "do", "chatgpt", "failed", text="limit", reason_code="plan_limit",
                 fallback_of="sr-1")
    calls = log.calls_for(conn, "sr-1")
    assert [c["call_id"] for c in log.fallback_view(calls)] == ["sr-1", "sr-1-c1", "sr-1-f1", "sr-1-c2"]
    assert log.fallback_base("sr-1", calls) == "sr-1"
    # The original's ending reads as before.
    assert relay is not None and fallback.decide(log.get_task(conn, "sr-1"), calls, live=LIVE).ok


def test_without_a_fallback_the_view_is_the_rows_as_they_are(conn):
    _route(conn)
    calls = log.calls_for(conn, "sr-1")
    assert log.fallback_view(calls) == list(calls) and log.fallback_base("sr-1", calls) == "sr-1"


# ---------- the prompt ----------

def test_the_redo_prompt_is_the_original_prompt_then_the_paragraph_then_the_fix_list():
    out = fallback.prompt("BASE PROMPT", "- a\n- b")
    assert out == "BASE PROMPT\n\n" + fallback.PARAGRAPH + "\n\n===== FIX LIST =====\n- a\n- b\n===== END FIX LIST ====="
    assert "data, not instructions" in fallback.PARAGRAPH and "you have not seen it" in fallback.PARAGRAPH


def test_assert_clean_refuses_a_prompt_that_carries_a_failed_result():
    with pytest.raises(ValueError):
        fallback.assert_clean(f"task\n\n{FIXED}", (FIRST, FIXED))
    fallback.assert_clean("task\n\nfix list", (FIRST, FIXED))


def test_a_failed_text_that_is_part_of_an_allowed_input_does_not_block():
    fallback.assert_clean(f"{TASK}\n\nfix", ("seed trays",), allowed=(TASK,))


# ---------- the stop line ----------

def test_the_stop_line_names_the_command_and_the_swap(conn):
    row = _route(conn)
    assert fallback.stop_line(row, log.calls_for(conn, "sr-1"), live=LIVE) == \
        f"Run: sr fallback {row['n']}  (chatgpt redoes it; claude checks)"


def test_the_stop_line_says_why_not(conn):
    row = _route(conn, skill="bulk_text", doer="claude", checker="grok")
    assert fallback.stop_line(row, log.calls_for(conn, "sr-1"), live=LIVE) == "No fallback: checker is grok: cannot redo"


def test_no_stop_line_on_a_task_that_passed_or_a_versus_pick(conn):
    row = _route(conn, recheck="PASS", state="fixed")
    assert fallback.stop_line(row, log.calls_for(conn, "sr-1"), live=LIVE) is None


# ---------- log version 8 ----------

def test_a_new_log_is_version_8_with_fallback_of_last_on_calls():
    c = log.init_db(":memory:")
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 16
    assert [r[1] for r in c.execute("PRAGMA table_info(calls)")][-5:] == ["fallback_of", "context", "memory", "served", "round_file"]  # briefs 18 and 19 added context and memory, 20 served, 21 round_file


def test_fallback_of_must_name_a_call_of_the_same_task(conn):
    _route(conn)
    _route(conn, tid="sr-2")
    with pytest.raises(log.StateError, match="fallback_of"):
        log.add_call(conn, "sr-1-fb1", "sr-1", "do", "chatgpt", "done", text="x", fallback_of="sr-2")
    with pytest.raises(log.StateError, match="fallback_of"):
        log.add_call(conn, "sr-1-fb1", "sr-1", "do", "chatgpt", "done", text="x", fallback_of="nope")


def _make_v7(path):
    c = sqlite3.connect(path)
    calls_v7 = V13_CALLS_SCHEMA.replace(",\n    fallback_of TEXT" + ",\n    context     TEXT,\n    memory      TEXT,\n    served      TEXT", "")
    assert "fallback_of" not in calls_v7
    tasks_v7 = V13_SCHEMA.replace(",\n    parent          TEXT,\n    split_plan      TEXT,\n    slots           TEXT,\n    web             INTEGER" + ",\n    project         TEXT,\n    handoff         TEXT,\n    chat            TEXT,\n    memory          TEXT", "")
    c.executescript(f"{tasks_v7}; {calls_v7}; PRAGMA user_version = 7;")
    c.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, status) VALUES "
              "('sr-a', '2026-10-15T00:00:00+00:00', '2026-10-15T00:00:00+00:00', 'cli', 't', 'ok', 'done')")
    c.execute("INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at) VALUES "
              "('sr-a', 'sr-a', 'do', 'claude', 'done', '2026-10-15T00:00:00+00:00')")
    c.commit()
    c.close()


def test_upgrade_from_version_7_adds_fallback_of_and_keeps_every_row(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _make_v7(db)
    with pytest.raises(log.VersionError, match=r"version 7 log.*sr migrate.*version 16 \(fallback_of column added"):
        log.init_db(db)
    done = log.migrate(db, backups)
    assert done["added"] == log.UPGRADES[7]["added"] == "fallback_of column added to calls; parent and split_plan columns added to tasks; slots and web columns added to tasks; project and handoff columns added to tasks; context column added to calls; chat and memory columns added to tasks; memory column added to calls; served column added to calls; reason_code column added to tasks; round_file column added to calls; pid, run_started_at and answered_by columns added to tasks; skill_source set to owner where it named the one who labeled the task"
    assert (done["rows"], done["calls"], done["highest"]) == (1, 1, 1)
    assert (backups / done["backup"].name).exists() and done["backup"].name.startswith("router-v7-")
    c = log.init_db(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 16
    assert c.execute("SELECT fallback_of FROM calls").fetchone()[0] is None
    with pytest.raises(log.MigrateRefused, match="already a version 16"):
        log.migrate(db, backups)
