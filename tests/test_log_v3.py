"""The version 3 log: one row per agent call in `calls`, a `check_note` on each task, and the
six check states. `tasks.result` stays empty until the check loop has ended."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from router import log
from tests.helpers import ALL_AGENTS, JEV_OK, add_row, make_v2_log, sha256

T0 = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)
CALL_COLUMNS = ["call_id", "task_id", "kind", "agent", "status", "sent_at", "finished_at",
                "run_uuid", "text", "verdict", "url"]


def _iso(when):
    return when.isoformat(timespec="seconds")


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _columns(conn, table):
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]


# ---------- the tables ----------

def test_a_new_log_is_version_5_with_calls_check_note_files_and_the_relay_columns(tmp_path):
    c = log.init_db(tmp_path / "router.db")
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 16
    assert _columns(c, "tasks") == list(log.V2_COLUMNS) + ["check_note", "files", "mode", "preset", "failed_stage",
                                                         "parent", "split_plan", "slots", "web", "project", "handoff", "chat", "memory", "reason_code",
                                                         "pid", "run_started_at", "answered_by"]
    assert _columns(c, "calls") == CALL_COLUMNS + ["stage", "role", "reason_code", "resume_of", "search", "fallback_of",
                                                   "context", "memory", "served", "round_file"]
    c.close()


def test_the_six_check_states_and_nothing_else(conn):
    assert log.CHECK_STATES == ("not_needed", "unchecked", "pending", "passed", "fixed", "failed")
    for n, state in enumerate(log.CHECK_STATES):
        log.add_task(conn, f"sr-{n}", "t", "cli", JEV_OK)
        log.set_route(conn, f"sr-{n}", agents=ALL_AGENTS, agent="grok", route_reason="best", check_state=state)
        assert log.get_task(conn, f"sr-{n}")["check_state"] == state
    log.add_task(conn, "sr-x", "t", "cli", JEV_OK)
    with pytest.raises(ValueError):
        log.set_route(conn, "sr-x", agents=ALL_AGENTS, agent="grok", route_reason="best", check_state="verified")


def test_set_route_stores_a_check_note(conn):
    log.add_task(conn, "sr-1", "t", "cli", JEV_OK)
    log.set_route(conn, "sr-1", agents=ALL_AGENTS, agent="grok", route_reason="best", checker="chatgpt",
                  check_state="unchecked", check_note="checker chatgpt isn't live yet")
    assert log.get_task(conn, "sr-1")["check_note"] == "checker chatgpt isn't live yet"


# ---------- calls ----------

def test_a_grok_call_is_sent_then_finished(conn):
    add_row(conn, "sr-1", agent="grok")
    log.add_call(conn, "sr-1", "sr-1", "do", "grok", run_uuid="u1", now=T0)
    call = log.get_call(conn, "sr-1")
    assert (call["task_id"], call["kind"], call["agent"], call["status"]) == ("sr-1", "do", "grok", "sent")
    assert (call["sent_at"], call["finished_at"], call["run_uuid"], call["text"]) == (_iso(T0), None, "u1", None)
    log.finish_call(conn, "sr-1", "done", text="pong", url="https://x/1", now=T0 + timedelta(minutes=1))
    call = log.get_call(conn, "sr-1")
    assert (call["status"], call["text"], call["url"], call["finished_at"]) == (
        "done", "pong", "https://x/1", _iso(T0 + timedelta(minutes=1)))
    with pytest.raises(log.StateError):
        log.finish_call(conn, "sr-1", "failed", text="late")


def test_a_claude_call_is_written_finished_in_one_go(conn):
    add_row(conn, "sr-1")
    log.add_call(conn, "sr-1-c1", "sr-1", "check", "claude", status="done", text="PASS", verdict="PASS", now=T0)
    call = log.get_call(conn, "sr-1-c1")
    assert (call["status"], call["verdict"], call["text"]) == ("done", "PASS", "PASS")
    assert call["sent_at"] == call["finished_at"] == _iso(T0)


def test_call_kind_status_and_verdict_are_checked_in_code(conn):
    add_row(conn, "sr-1")
    assert log.CALL_KINDS == ("do", "check", "fix", "recheck", "stage", "reask")
    assert log.CALL_STATUSES == ("sent", "done", "failed", "timed_out")
    assert log.VERDICTS == ("PASS", "FIX", "unreadable")
    with pytest.raises(ValueError):
        log.add_call(conn, "sr-1-x", "sr-1", "redo", "claude")
    with pytest.raises(ValueError):
        log.add_call(conn, "sr-1-x", "sr-1", "check", "claude", status="lost")
    with pytest.raises(ValueError):
        log.add_call(conn, "sr-1-x", "sr-1", "check", "claude", status="done", verdict="MAYBE")
    log.add_call(conn, "sr-1-c1", "sr-1", "check", "grok", now=T0)
    with pytest.raises(ValueError):
        log.finish_call(conn, "sr-1-c1", "sent")
    assert log.calls_for(conn, "sr-1") and len(log.calls_for(conn, "sr-1")) == 1


def test_a_call_needs_an_existing_task(conn):
    with pytest.raises(log.StateError):
        log.add_call(conn, "sr-nope-c1", "sr-nope", "check", "claude")


def test_calls_for_a_task_come_back_in_the_order_they_were_sent(conn):
    add_row(conn, "sr-1", agent="grok")
    for n, (call_id, kind) in enumerate([("sr-1", "do"), ("sr-1-c1", "check"), ("sr-1-f1", "fix")]):
        log.add_call(conn, call_id, "sr-1", kind, "grok", now=T0 + timedelta(minutes=n))
    assert [c["call_id"] for c in log.calls_for(conn, "sr-1")] == ["sr-1", "sr-1-c1", "sr-1-f1"]
    assert log.calls_for(conn, "sr-other") == []


def test_set_sent_records_the_do_call(conn):
    add_row(conn, "sr-1", agent="grok")
    log.set_sent(conn, "sr-1", "uuid-1", now=T0)
    call = log.get_call(conn, "sr-1")
    assert (call["kind"], call["agent"], call["status"], call["run_uuid"], call["sent_at"]) == (
        "do", "grok", "sent", "uuid-1", _iso(T0))


def test_open_grok_calls_lists_sent_grok_calls_of_open_tasks_only(conn):
    add_row(conn, "sr-a", agent="grok")
    add_row(conn, "sr-b")
    add_row(conn, "sr-c", agent="grok")
    log.set_sent(conn, "sr-a", "ua", now=T0)                               # a do call, out
    log.add_call(conn, "sr-b-c1", "sr-b", "check", "grok", now=T0 + timedelta(seconds=1))  # a check, out
    log.add_call(conn, "sr-b", "sr-b", "do", "claude", status="done", text="r", now=T0)  # claude, finished
    log.set_sent(conn, "sr-c", "uc", now=T0 + timedelta(seconds=2))
    log.set_cancelled(conn, "sr-c")                                         # its call is out, but the task isn't open
    assert log.open_grok_calls(conn) == ["sr-a", "sr-b-c1"]
    log.finish_call(conn, "sr-a", "done", text="pong")
    assert log.open_grok_calls(conn) == ["sr-b-c1"]
    assert not hasattr(log, "open_grok_tasks")


def test_mark_timeouts_marks_the_call_and_a_timed_out_do_call_ends_the_task(conn):
    add_row(conn, "sr-old", agent="grok")
    add_row(conn, "sr-new", agent="grok")
    add_row(conn, "sr-chk", agent="grok")
    log.set_sent(conn, "sr-old", "u1", now=T0 - timedelta(minutes=31))
    log.set_sent(conn, "sr-new", "u2", now=T0 - timedelta(minutes=29))
    log.set_sent(conn, "sr-chk", "u3", now=T0 - timedelta(minutes=40))
    log.finish_call(conn, "sr-chk", "done", text="r", now=T0 - timedelta(minutes=35))
    log.add_call(conn, "sr-chk-c1", "sr-chk", "check", "grok", now=T0 - timedelta(minutes=31))
    assert log.mark_timeouts(conn, now=T0, minutes=30) == ["sr-old", "sr-chk-c1"]
    assert log.get_call(conn, "sr-old")["status"] == "timed_out"
    assert log.get_task(conn, "sr-old")["status"] == "timed_out"
    assert log.get_call(conn, "sr-new")["status"] == "sent"
    assert log.get_call(conn, "sr-chk-c1")["status"] == "timed_out"
    assert log.get_task(conn, "sr-chk")["status"] == "sent", "only the loop decides how a timed-out check ends"


# ---------- tasks.result is written once, at the end of the loop ----------

def test_the_result_is_empty_until_the_loop_ends(conn):
    log.add_task(conn, "sr-1", "t", "cli", JEV_OK)
    log.set_route(conn, "sr-1", agents=ALL_AGENTS, agent="grok", route_reason="interim", skill="web_research",
                  skill_source="jev", checker="claude", check_state="pending")
    log.set_sent(conn, "sr-1", "u1", now=T0)
    log.finish_call(conn, "sr-1", "done", text="the answer", url="https://x/1")
    row = log.get_task(conn, "sr-1")
    assert (row["status"], row["result"], row["check_state"]) == ("sent", None, "pending")
    log.set_done(conn, "sr-1", "the answer", "https://x/1", check_state="passed")
    row = log.get_task(conn, "sr-1")
    assert (row["status"], row["result"], row["check_state"], row["check_note"]) == (
        "done", "the answer", "passed", None)


def test_set_done_can_set_the_final_check_state_and_note(conn):
    add_row(conn, "sr-1")
    log.set_done(conn, "sr-1", "r", check_state="unchecked", check_note="check round 1 by claude failed: WorkerError")
    row = log.get_task(conn, "sr-1")
    assert (row["check_state"], row["check_note"]) == ("unchecked", "check round 1 by claude failed: WorkerError")
    add_row(conn, "sr-2")
    with pytest.raises(ValueError):
        log.set_done(conn, "sr-2", "r", check_state="verified")


def test_set_done_without_check_fields_leaves_them_as_routed(conn):
    log.add_task(conn, "sr-1", "t", "cli", JEV_OK)
    log.set_route(conn, "sr-1", agents=ALL_AGENTS, agent="claude", route_reason="best", check_state="not_needed")
    log.set_done(conn, "sr-1", "r")
    assert log.get_task(conn, "sr-1")["check_state"] == "not_needed"


def test_set_check_state_works_on_an_open_task_only(conn):
    add_row(conn, "sr-1")
    log.set_check_state(conn, "sr-1", "pending")
    assert log.get_task(conn, "sr-1")["check_state"] == "pending"
    log.set_check_state(conn, "sr-1", "unchecked", note="grok checks arrive in phase D")
    assert log.get_task(conn, "sr-1")["check_note"] == "grok checks arrive in phase D"
    log.set_done(conn, "sr-1", "r")
    with pytest.raises(log.StateError):
        log.set_check_state(conn, "sr-1", "passed")
    with pytest.raises(ValueError):
        log.set_check_state(conn, "sr-1", "verified")


# ---------- opening an old log ----------

def test_init_db_refuses_a_version_2_log_and_changes_nothing(tmp_path):
    path = make_v2_log(tmp_path / "router.db", [{}, {"status": "returned", "agent": None, "result": None}])
    before = sha256(path)
    with pytest.raises(log.VersionError) as err:
        log.init_db(path)
    assert "version 2" in str(err.value) and "sr migrate" in str(err.value)
    assert sha256(path) == before


# ---------- version 4: files on a task (build brief 4) ----------

def test_add_task_stores_the_file_records_as_json_and_files_of_reads_them_back():
    c = log.init_db(":memory:")
    files = [{"name": "logo.png", "type": "image/png", "size": 1000, "frames": None},
             {"name": "clip.mp4", "type": "video/mp4", "size": 5000, "frames": 12}]
    log.add_task(c, "sr-f", "what are these", "cli", {"status": "ok", "label": "read_media", "confidence": 0.9, "tokens": 700},
                 files=files)
    log.add_task(c, "sr-n", "no files", "cli", {"status": "ok", "label": "writing", "confidence": 0.9, "tokens": 700})
    with_files, without = log.get_task(c, "sr-f"), log.get_task(c, "sr-n")
    assert log.files_of(with_files) == files and with_files["files"].startswith("[{")
    assert without["files"] is None and log.files_of(without) == []
    assert with_files["task"] == "what are these"
    c.close()
