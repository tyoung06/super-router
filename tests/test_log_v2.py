"""The version 2 log table: Jev's label, who does and checks a task, and the new statuses."""
import sqlite3
from datetime import datetime, timezone

import pytest

from router import log
from tests.helpers import ALL_AGENTS, JEV_OK, add_row, make_v1_log, sha256

V2_COLUMNS = [
    "task_id", "created_at", "updated_at", "sent_at", "source", "task",
    "jev_status", "jev_label", "jev_confidence", "jev_needs_split", "jev_tokens", "jev_error",
    "skill", "skill_source", "agent", "route_reason", "checker", "check_state",
    "status", "run_uuid", "result", "result_url",
]


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _columns(conn):
    return [r["name"] for r in conn.execute("PRAGMA table_info(tasks)")]


# ---------- the table ----------

def test_a_new_log_is_the_current_version_with_the_version_2_columns_first(tmp_path):
    c = log.init_db(tmp_path / "router.db")
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 16
    assert _columns(c)[: len(V2_COLUMNS)] == V2_COLUMNS == list(log.V2_COLUMNS)
    c.close()


def test_status_is_the_only_check_constraint():
    assert log.SCHEMA.count("CHECK") == 1
    for status in log.STATUSES:
        assert f"'{status}'" in log.SCHEMA
    assert log.STATUSES == ("queued", "sent", "done", "failed", "timed_out", "cancelled", "returned")


def test_the_database_rejects_an_unknown_status(conn):
    add_row(conn, "sr-1")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE tasks SET status = 'bogus' WHERE task_id = 'sr-1'")


# ---------- Jev's answer is logged first ----------

def test_add_task_logs_jev_fields_and_starts_queued_with_no_agent(conn):
    jev = {"status": "below_floor", "label": "web_research", "confidence": 0.62,
           "needs_split": 0.4, "tokens": 812, "error": None}
    log.add_task(conn, "sr-1", "look this up", "cli", jev)
    row = log.get_task(conn, "sr-1")
    assert (row["jev_status"], row["jev_label"], row["jev_confidence"]) == ("below_floor", "web_research", 0.62)
    assert (row["jev_needs_split"], row["jev_tokens"], row["jev_error"]) == (0.4, 812, None)
    assert (row["status"], row["agent"], row["checker"], row["skill"]) == ("queued", None, None, None)


def test_jev_status_is_required_and_checked(conn):
    for bad in ({"label": "code"}, {"status": "maybe"}):
        with pytest.raises(ValueError):
            log.add_task(conn, "sr-1", "t", "cli", bad)
    assert log.get_task(conn, "sr-1") is None


def test_jev_tokens_default_to_zero_and_must_be_a_whole_number(conn):
    log.add_task(conn, "sr-1", "t", "cli", {"status": "over_cap"})
    assert log.get_task(conn, "sr-1")["jev_tokens"] == 0
    with pytest.raises(ValueError):
        log.add_task(conn, "sr-2", "t", "cli", {"status": "ok", "label": "code", "tokens": -5})


# ---------- who does it and who checks it ----------

@pytest.mark.parametrize("agent", ALL_AGENTS)
def test_every_agent_in_the_config_is_accepted(conn, agent):
    add_row(conn, "sr-1", agent=agent)
    assert log.get_task(conn, "sr-1")["agent"] == agent


def test_a_task_no_agent_did_has_an_empty_agent(conn):
    log.add_task(conn, "sr-1", "t", "cli", JEV_OK)
    log.set_returned(conn, "sr-1", "returned: doer not live", skill="read_media", skill_source="jev")
    assert log.get_task(conn, "sr-1")["agent"] is None


@pytest.mark.parametrize("field", ["agent", "checker"])
def test_an_unknown_agent_never_reaches_the_log(conn, field):
    log.add_task(conn, "sr-1", "t", "cli", JEV_OK)
    names = {"agent": "claude", "checker": None, field: "gpt"}
    with pytest.raises(ValueError):
        log.set_route(conn, "sr-1", agents=ALL_AGENTS, route_reason="best", **names)
    row = log.get_task(conn, "sr-1")
    assert (row["agent"], row["checker"], row["status"]) == (None, None, "queued")


def test_set_route_stores_the_whole_decision(conn):
    log.add_task(conn, "sr-1", "t", "cli", JEV_OK)
    log.set_route(conn, "sr-1", agents=ALL_AGENTS, agent="grok", route_reason="interim", skill="web_research",
                  skill_source="owner", checker="claude", check_state="unchecked")
    row = log.get_task(conn, "sr-1")
    assert (row["agent"], row["route_reason"], row["skill"], row["skill_source"]) == (
        "grok", "interim", "web_research", "owner")
    assert (row["checker"], row["check_state"], row["status"]) == ("claude", "unchecked", "queued")


@pytest.mark.parametrize("field, bad", [("check_state", "checked"), ("skill_source", "haiku")])
def test_check_state_and_skill_source_are_checked_in_code(conn, field, bad):
    log.add_task(conn, "sr-1", "t", "cli", JEV_OK)
    with pytest.raises(ValueError):
        log.set_route(conn, "sr-1", agents=ALL_AGENTS, agent="claude", route_reason="best", **{field: bad})
    assert log.CHECK_STATES == ("not_needed", "unchecked", "pending", "passed", "fixed", "failed")
    assert log.SKILL_SOURCES == ("jev", "owner")


def test_an_agent_never_checks_its_own_work(conn):
    log.add_task(conn, "sr-1", "t", "cli", JEV_OK)
    with pytest.raises(ValueError):
        log.set_route(conn, "sr-1", agents=ALL_AGENTS, agent="claude", route_reason="best", checker="claude")


def test_set_route_only_on_a_queued_task(conn):
    add_row(conn, "sr-1")
    log.set_done(conn, "sr-1", "answer")
    with pytest.raises(log.StateError):
        log.set_route(conn, "sr-1", agents=ALL_AGENTS, agent="grok", route_reason="best")


# ---------- the new statuses ----------

def test_cancelled_is_a_real_status(conn):
    add_row(conn, "sr-q")
    add_row(conn, "sr-s", agent="grok")
    log.set_sent(conn, "sr-s", "uuid")
    for task_id in ("sr-q", "sr-s"):
        log.set_cancelled(conn, task_id)
        row = log.get_task(conn, task_id)
        assert (row["status"], row["result"]) == ("cancelled", None)
    assert not hasattr(log, "CANCEL_NOTE")


def test_a_finished_task_cannot_be_cancelled(conn):
    add_row(conn, "sr-d")
    log.set_done(conn, "sr-d", "answer")
    with pytest.raises(log.StateError):
        log.set_cancelled(conn, "sr-d")


def test_returned_means_no_agent_did_it(conn):
    log.add_task(conn, "sr-1", "t", "cli", {"status": "none_of_these", "label": "none_of_these", "confidence": 0.9})
    log.set_returned(conn, "sr-1", "returned: needs your label")
    row = log.get_task(conn, "sr-1")
    assert (row["status"], row["route_reason"], row["agent"], row["check_state"]) == (
        "returned", "returned: needs your label", None, None)


def test_returned_needs_a_returned_reason_and_a_queued_task(conn):
    log.add_task(conn, "sr-1", "t", "cli", JEV_OK)
    with pytest.raises(ValueError):
        log.set_returned(conn, "sr-1", "doer not live")
    add_row(conn, "sr-2")
    log.set_done(conn, "sr-2", "answer")
    with pytest.raises(log.StateError):
        log.set_returned(conn, "sr-2", "returned: no skill")


# ---------- the monthly Jev token sum ----------

def test_monthly_jev_tokens_count_this_utc_month_only(conn):
    for task_id, when, tokens in [
        ("sr-sep", utc(2026, 9, 30, 23, 59, 59), 100),
        ("sr-oct-first", utc(2026, 10, 1, 0, 0, 0), 200),
        ("sr-oct-last", utc(2026, 10, 31, 23, 59, 59), 300),
        ("sr-nov", utc(2026, 11, 1, 0, 0, 0), 400),
    ]:
        log.add_task(conn, task_id, "t", "cli", {**JEV_OK, "tokens": tokens}, now=when)
    assert log.jev_tokens_this_month(conn, now=utc(2026, 10, 15, 12, 0)) == 500
    assert log.jev_tokens_this_month(conn, now=utc(2026, 12, 1, 0, 0)) == 0


def test_monthly_jev_tokens_on_an_empty_log(conn):
    assert log.jev_tokens_this_month(conn) == 0


# ---------- opening an old log ----------

def test_init_db_refuses_a_version_1_log_and_changes_nothing(tmp_path):
    path = make_v1_log(tmp_path / "router.db", ["done", "timed_out"])
    before = sha256(path)
    with pytest.raises(log.VersionError) as err:
        log.init_db(path)
    assert "version 1" in str(err.value) and "sr migrate" in str(err.value)
    assert sha256(path) == before


def test_init_db_refuses_an_unknown_version(tmp_path):
    path = tmp_path / "router.db"
    c = sqlite3.connect(path)
    c.execute("PRAGMA user_version = 7")
    c.close()
    with pytest.raises(log.VersionError):
        log.init_db(path)
