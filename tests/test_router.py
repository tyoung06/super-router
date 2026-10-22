"""Tests written BEFORE the logic (see SUPER-ROUTER-HANDOFF.md, Build steps).

They fail until the `router` package exists. That is expected.
Every secret in this file is fake.
"""
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from router import grok, ids, inbox, log, routing, safety
from tests.helpers import JEV_OK, shipped_roster
from tests.helpers import add_row

UTC = timezone.utc
T0 = datetime(2026, 10, 2, 18, 0, 0, tzinfo=UTC)


# ---------- ids ----------

def test_ids_format():
    assert re.fullmatch(r"sr-\d{8}-\d{6}-[0-9a-f]{4}", ids.new_task_id())


def test_ids_use_given_time_in_utc():
    assert ids.new_task_id(now=T0).startswith("sr-20261002-180000-")


def test_ids_are_unique():
    made = {ids.new_task_id(now=T0) for _ in range(50)}
    assert len(made) > 1


# ---------- routing ----------

ALL = ("claude", "grok", "chatgpt", "muse")
ROSTER = shipped_roster()


def test_routing_override_grok_names_the_doer():
    tag, rest = routing.parse_override("@grok what is trending", ALL)
    decision = routing.decide(JEV_OK, ROSTER, override=tag)
    assert (rest, decision.agent, decision.reason) == ("what is trending", "grok", "override")


def test_routing_override_claude_names_the_doer():
    tag, rest = routing.parse_override("@claude explain venvs", ALL)
    decision = routing.decide(JEV_OK, ROSTER, override=tag)
    assert (rest, decision.agent, decision.reason) == ("explain venvs", "claude", "override")


def test_routing_strip_override_removes_prefix_only():
    assert routing.parse_override("@grok what is trending", ALL) == ("grok", "what is trending")
    assert routing.parse_override("no prefix here", ALL) == (None, "no prefix here")
    assert routing.parse_override("email me @grok later", ALL) == (None, "email me @grok later")


# ---------- log ----------

@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def test_log_add_task_starts_queued(conn):
    add_row(conn, "sr-1", "do a thing", "grok", "best")
    row = log.get_task(conn, "sr-1")
    assert row["status"] == "queued"
    assert row["source"] == "cli"
    assert row["agent"] == "grok"
    assert row["task"] == "do a thing"
    assert row["route_reason"] == "best"


def test_log_get_missing_task_is_none(conn):
    assert log.get_task(conn, "sr-nope") is None


def test_log_duplicate_task_id_is_rejected(conn):
    add_row(conn, "sr-1", "a", "grok", "best")
    with pytest.raises(sqlite3.IntegrityError):
        add_row(conn, "sr-1", "b", "grok", "best")


def test_log_set_sent_records_run_uuid(conn):
    add_row(conn, "sr-1", "a", "grok", "best")
    log.set_sent(conn, "sr-1", "uuid-123", now=T0)
    row = log.get_task(conn, "sr-1")
    assert row["status"] == "sent"
    assert row["run_uuid"] == "uuid-123"
    assert log.open_grok_calls(conn) == ["sr-1"]


def test_log_set_done_records_result(conn):
    add_row(conn, "sr-1", "a", "grok", "best")
    log.set_sent(conn, "sr-1", "uuid-123", now=T0)
    log.set_done(conn, "sr-1", "pong", "https://example.com/issue/1")
    row = log.get_task(conn, "sr-1")
    assert row["status"] == "done"
    assert row["result"] == "pong"
    assert row["result_url"] == "https://example.com/issue/1"
    assert log.open_grok_calls(conn) == []


def test_log_set_failed(conn):
    add_row(conn, "sr-1", "a", "grok", "best")
    log.set_failed(conn, "sr-1", "webhook returned 401")
    row = log.get_task(conn, "sr-1")
    assert row["status"] == "failed"
    assert "401" in row["result"]


def test_log_mark_timeouts_after_30_minutes(conn):
    add_row(conn, "sr-old", "a", "grok", "best")
    add_row(conn, "sr-new", "b", "grok", "best")
    log.set_sent(conn, "sr-old", "u1", now=T0 - timedelta(minutes=31))
    log.set_sent(conn, "sr-new", "u2", now=T0 - timedelta(minutes=29))
    assert log.mark_timeouts(conn, now=T0, minutes=30) == ["sr-old"]
    assert log.get_task(conn, "sr-old")["status"] == "timed_out"
    assert log.get_task(conn, "sr-new")["status"] == "sent"


def test_log_mark_timeouts_leaves_done_tasks_alone(conn):
    add_row(conn, "sr-1", "a", "grok", "best")
    log.set_sent(conn, "sr-1", "u1", now=T0 - timedelta(hours=5))
    log.set_done(conn, "sr-1", "pong")
    assert log.mark_timeouts(conn, now=T0, minutes=30) == []
    assert log.get_task(conn, "sr-1")["status"] == "done"


# ---------- grok ----------

class _Reply:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def test_grok_build_payload():
    assert grok.build_payload("sr-1", "hello") == {"task_id": "sr-1", "task": "hello"}


def test_grok_send_posts_with_bearer_header_and_returns_run_uuid():
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update(url=url, headers=headers, json=json, timeout=timeout)
        return _Reply(200, {"success": True, "runUuid": "uuid-abc"})

    run_uuid = grok.send("sr-1", "hello", "https://example.invalid/hook", "FAKE-KEY-123", fake_post)
    assert run_uuid == "uuid-abc"
    assert seen["url"] == "https://example.invalid/hook"
    assert seen["headers"]["Authorization"] == "Bearer FAKE-KEY-123"
    assert seen["json"] == {"task_id": "sr-1", "task": "hello"}
    assert seen["timeout"]  # a hung webhook must not hang the router


def test_grok_send_raises_on_non_200():
    def fake_post(url, headers=None, json=None, timeout=None):
        return _Reply(401, {"error": "bad key"})

    with pytest.raises(grok.DispatchError):
        grok.send("sr-1", "hello", "https://example.invalid/hook", "FAKE-KEY-123", fake_post)


def test_grok_send_names_the_webhooks_error_text_with_the_status():
    def fake_post(url, headers=None, json=None, timeout=None):
        return _Reply(400, {"success": False, "error": "Automation run rate limit exceeded: limit 10000 per minute"})

    with pytest.raises(grok.DispatchError) as err:
        grok.send("sr-1", "hello", "https://example.invalid/hook", "FAKE-KEY-123", fake_post)
    assert "HTTP 400" in str(err.value) and "rate limit exceeded" in str(err.value)


def test_grok_send_raises_when_success_is_false():
    def fake_post(url, headers=None, json=None, timeout=None):
        return _Reply(200, {"success": False})

    with pytest.raises(grok.DispatchError):
        grok.send("sr-1", "hello", "https://example.invalid/hook", "FAKE-KEY-123", fake_post)


def test_grok_error_never_contains_the_key():
    def fake_post(url, headers=None, json=None, timeout=None):
        return _Reply(500, {"error": "server"})

    with pytest.raises(grok.DispatchError) as err:
        grok.send("sr-1", "hello", "https://example.invalid/hook", "FAKE-KEY-123", fake_post)
    assert "FAKE-KEY-123" not in str(err.value)
    assert "example.invalid" not in str(err.value)


# ---------- inbox ----------

ISSUES = [
    {"number": 3, "title": "sr-1", "body": "pong", "url": "https://example.com/3"},
    {"number": 4, "title": " sr-2 ", "body": "second", "url": "https://example.com/4"},
    {"number": 5, "title": "sr-1 extra words", "body": "no", "url": "https://example.com/5"},
    {"number": 6, "title": "spike-1", "body": "old", "url": "https://example.com/6"},
]


def test_inbox_matches_on_exact_title():
    got = inbox.match_results(["sr-1"], ISSUES)
    assert got == [{"task_id": "sr-1", "result": "pong", "url": "https://example.com/3", "number": 3}]


def test_inbox_ignores_whitespace_around_title():
    got = inbox.match_results(["sr-2"], ISSUES)
    assert [g["task_id"] for g in got] == ["sr-2"]


def test_inbox_ignores_issues_with_no_open_task():
    assert inbox.match_results([], ISSUES) == []
    assert inbox.match_results(["sr-99"], ISSUES) == []


def test_inbox_handles_empty_body():
    issues = [{"number": 7, "title": "sr-3", "body": None, "url": "https://example.com/7"}]
    assert inbox.match_results(["sr-3"], issues)[0]["result"] == ""


# ---------- safety ----------

def test_redact_replaces_secret():
    assert safety.redact("key is FAKE-KEY-123 ok", ["FAKE-KEY-123"]) == "key is [REDACTED] ok"


def test_redact_replaces_every_occurrence_and_every_secret():
    text = "A FAKE-KEY-123 B https://example.invalid/hook C FAKE-KEY-123"
    out = safety.redact(text, ["FAKE-KEY-123", "https://example.invalid/hook"])
    assert "FAKE-KEY-123" not in out
    assert "example.invalid" not in out


def test_redact_ignores_empty_secrets():
    assert safety.redact("nothing to hide", ["", None]) == "nothing to hide"


GOOD_ENV = {"GROK_WEBHOOK_URL": "https://example.invalid/hook", "GROK_WEBHOOK_KEY": "FAKE-KEY-123"}


def test_check_env_ok():
    assert safety.check_env(GOOD_ENV) == []


def test_check_env_flags_api_key_by_name_not_value():
    problems = safety.check_env({**GOOD_ENV, "ANTHROPIC_API_KEY": "FAKE-ANTHROPIC-VALUE"})
    assert len(problems) == 1
    assert "ANTHROPIC_API_KEY" in problems[0]
    assert "FAKE-ANTHROPIC-VALUE" not in problems[0]


def test_check_env_no_longer_requires_the_webhook_names():
    # Build brief 24 (decision 12): REQUIRED_ENV is gone; a missing webhook name means Grok Bot isn't set up
    # (router/availability.py), never that every command is refused. The billing switches still refuse.
    assert safety.check_env({"GROK_WEBHOOK_URL": "", "GROK_WEBHOOK_KEY": "FAKE-KEY-123"}) == []
    assert safety.check_env({}) == []
    assert not hasattr(safety, "REQUIRED_ENV")
    assert safety.check_env({"OPENAI_API_KEY": "FAKE-SWITCH"}) == safety.billing_problems({"OPENAI_API_KEY": "FAKE-SWITCH"}) != []
