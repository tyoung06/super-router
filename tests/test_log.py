"""Log tests added in handoff v1.2."""
from datetime import datetime, timezone

import pytest

from router import log
from tests.helpers import add_row

T0 = datetime(2026, 10, 2, 18, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def test_log_times_are_utc_iso_strings(conn):
    add_row(conn, "sr-1", "a", "grok", "best")
    log.set_sent(conn, "sr-1", "u1", now=T0)
    row = log.get_task(conn, "sr-1")
    assert row["sent_at"] == "2026-10-02T18:00:00+00:00"
    assert datetime.fromisoformat(row["created_at"]).utcoffset().total_seconds() == 0


def test_log_done_task_cannot_change_again(conn):
    add_row(conn, "sr-1", "a", "claude", "best")
    log.set_done(conn, "sr-1", "answer")
    with pytest.raises(log.StateError):
        log.set_failed(conn, "sr-1", "late error")
    with pytest.raises(log.StateError):
        log.set_sent(conn, "sr-1", "u1")
    assert log.get_task(conn, "sr-1")["result"] == "answer"


def test_log_change_on_missing_task_raises(conn):
    with pytest.raises(log.StateError):
        log.set_done(conn, "sr-nope", "x")


def test_log_recent_tasks_newest_first(conn):
    for task_id in ["sr-a", "sr-b", "sr-c"]:
        add_row(conn, task_id, "t", "claude", "best")
    assert [r["task_id"] for r in log.recent_tasks(conn)] == ["sr-c", "sr-b", "sr-a"]
    assert [r["task_id"] for r in log.recent_tasks(conn, limit=2)] == ["sr-c", "sr-b"]


def test_log_init_db_keeps_rows_on_reopen(tmp_path):
    path = tmp_path / "router.db"
    c = log.init_db(path)
    add_row(c, "sr-1", "a", "grok", "best")
    c.close()
    c = log.init_db(path)
    assert log.get_task(c, "sr-1")["task"] == "a"
    c.close()


def test_log_rejects_unknown_agent(conn):
    with pytest.raises(ValueError):
        add_row(conn, "sr-1", "a", "gpt", "best")
