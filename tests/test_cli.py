"""Command tests (route, check, log) with fakes. Every secret here is fake."""
import json

import pytest

from router import __main__ as cli
from router import log, safety
from tests.helpers import add_row, shipped_roster, fake_label

CONFIG = {"GROK_WEBHOOK_URL": "https://example.invalid/hook", "GROK_WEBHOOK_KEY": "FAKE-KEY-123"}
ROSTER = shipped_roster()
SECRETS = ("FAKE-KEY-123", "example.invalid")


class _Reply:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class Recorder:
    """A fake that records its calls and returns a fixed value (or raises)."""

    def __init__(self, value=None, raises=None):
        self.value, self.raises, self.calls = value, raises, []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.raises:
            raise self.raises
        return self.value


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _count(conn):
    return conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]


def _route(conn, task, *, config=CONFIG, environ=None, settings_paths=(), label=None,
           post=None, worker=None, source="cli"):
    lines = []
    code = cli.cmd_route(
        task, conn=conn, config=config, roster=ROSTER, label=label or fake_label(), environ=environ or {}, settings_paths=list(settings_paths),
        post=post or Recorder(_Reply(200, {"success": True, "runUuid": "uuid-abc"})),
        worker=worker or Recorder("an answer"), source=source, out=lines.append,
    )
    return code, "\n".join(lines)


def _only_row(conn):
    rows = log.recent_tasks(conn)
    assert len(rows) == 1
    return rows[0]


# ---------- route: refusals log nothing ----------

def test_route_refuses_billing_switch_in_shell_and_logs_nothing(conn):
    post, label = Recorder(), fake_label()
    code, out = _route(conn, "@grok hi", environ={"ANTHROPIC_API_KEY": "FAKE-ANTHROPIC"}, post=post,
                       label=label)
    assert code == 2
    assert "ANTHROPIC_API_KEY" in out and "FAKE-ANTHROPIC" not in out
    assert _count(conn) == 0 and post.calls == [] and label.calls == []


def test_route_refuses_billing_switch_in_dotenv(conn):
    code, _ = _route(conn, "hi", config={**CONFIG, "ANTHROPIC_AUTH_TOKEN": "FAKE"})
    assert code == 2 and _count(conn) == 0


def test_route_refuses_billing_switch_even_if_dotenv_blanks_it(conn):
    code, _ = _route(conn, "hi", config={**CONFIG, "ANTHROPIC_API_KEY": ""},
                     environ={"ANTHROPIC_API_KEY": "FAKE"})
    assert code == 2 and _count(conn) == 0


def test_route_refuses_api_key_helper(conn, tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"apiKeyHelper": "/fake/helper.sh"}))
    code, out = _route(conn, "hi", settings_paths=[settings])
    assert code == 2 and "apiKeyHelper" in out and _count(conn) == 0


def test_a_missing_webhook_no_longer_refuses_a_task(conn):
    # Build brief 24 (decision 12): only Grok needs the webhook names; a quick answer runs on Claude without them
    code, out = _route(conn, "hi", config={})
    assert code == 0 and "GROK_WEBHOOK_URL" not in out and _count(conn) == 1
    assert _only_row(conn)["status"] == "done" and _only_row(conn)["agent"] == "claude"


@pytest.mark.parametrize("task", ["@grok", "   ", "@CLAUDE   "])
def test_route_refuses_empty_task(conn, task):
    code, _ = _route(conn, task)
    assert code == 2 and _count(conn) == 0


# ---------- route: grok ----------

def test_route_grok_override_sends_and_logs_sent(conn):
    post = Recorder(_Reply(200, {"success": True, "runUuid": "uuid-abc"}))
    code, out = _route(conn, "@grok Reply with the word pong", post=post)
    row = _only_row(conn)
    assert code == 0
    assert (row["status"], row["agent"], row["route_reason"]) == ("sent", "grok", "override")
    assert row["run_uuid"] == "uuid-abc" and row["sent_at"]
    assert row["task"] == "Reply with the word pong"
    assert post.calls[0][1]["json"] == {"task_id": row["task_id"], "task": "Reply with the word pong"}
    assert row["task_id"] in out


def test_route_grok_rejected_logs_failed_without_secrets(conn):
    code, out = _route(conn, "@grok hi", post=Recorder(_Reply(500, {"error": "FAKE-KEY-123"})))
    row = _only_row(conn)
    assert code == 1 and row["status"] == "failed" and "500" in row["result"]
    for secret in SECRETS:
        assert secret not in row["result"] and secret not in out


def test_route_grok_connection_error_logs_failed_without_secrets(conn):
    boom = ConnectionError("HTTPSConnectionPool(host='example.invalid') url: /hook FAKE-KEY-123")
    code, out = _route(conn, "@grok hi", post=Recorder(raises=boom))
    row = _only_row(conn)
    assert code == 1 and row["status"] == "failed"
    for secret in SECRETS:
        assert secret not in row["result"] and secret not in out


# ---------- route: claude ----------

def test_route_claude_logs_done_with_redacted_result(conn):
    worker = Recorder("answer with FAKE-KEY-123 inside")
    code, out = _route(conn, "explain venvs", worker=worker)
    row = _only_row(conn)
    assert code == 0
    assert (row["status"], row["agent"], row["route_reason"]) == ("done", "claude", "best")
    assert row["result"] == "answer with [REDACTED] inside"
    assert worker.calls[0][0] == ("explain venvs",)
    assert "FAKE-KEY-123" not in out


def test_route_claude_worker_error_logs_failed_redacted(conn):
    worker = Recorder(raises=safety.SafeError("claude exited 1: FAKE-KEY-123"))
    code, _ = _route(conn, "@claude hi", worker=worker)
    row = _only_row(conn)
    assert code == 1 and row["status"] == "failed"
    assert "exited 1" in row["result"] and "FAKE-KEY-123" not in row["result"]


def test_route_unexpected_error_stores_type_name_only(conn):
    worker = Recorder(raises=ValueError("https://example.invalid/hook leaked"))
    code, _ = _route(conn, "@claude hi", worker=worker)
    row = _only_row(conn)
    assert code == 1 and row["result"] == "unexpected error: ValueError"


def test_route_source_flag_is_logged(conn):
    _route(conn, "@claude hi", source="test")
    assert _only_row(conn)["source"] == "test"


# ---------- check ----------

from datetime import datetime, timedelta, timezone  # noqa: E402

from router import inbox  # noqa: E402

T0 = datetime(2026, 10, 2, 18, 0, 0, tzinfo=timezone.utc)


def _sent_task(conn, task_id, minutes_ago=1):
    add_row(conn, task_id, "t", "grok", "override")
    log.set_sent(conn, task_id, "uuid", now=T0 - timedelta(minutes=minutes_ago))


def _check(conn, *, fetch, close=None, now=T0):
    lines = []
    close = close or Recorder()
    code = cli.cmd_check(conn=conn, config=CONFIG, fetch=fetch, close=close, now=now, out=lines.append)
    return code, "\n".join(lines), close


def test_check_marks_matched_task_done_redacted_and_closes_issue(conn):
    _sent_task(conn, "sr-1")
    fetch = Recorder([{"number": 7, "title": "sr-1", "body": "pong FAKE-KEY-123", "url": "https://x/7"}])
    code, out, close = _check(conn, fetch=fetch)
    row = log.get_task(conn, "sr-1")
    assert code == 0
    assert (row["status"], row["result"], row["result_url"]) == ("done", "pong [REDACTED]", "https://x/7")
    assert close.calls == [((7,), {})]
    assert "FAKE-KEY-123" not in out


def test_check_leaves_unmatched_issues_alone(conn):
    _sent_task(conn, "sr-1")
    fetch = Recorder([{"number": 1, "title": "spike-1", "body": "old", "url": "u1"}])
    code, _, close = _check(conn, fetch=fetch)
    assert code == 0 and close.calls == []
    assert log.get_task(conn, "sr-1")["status"] == "sent"


def test_check_skips_gh_when_nothing_is_open(conn):
    fetch = Recorder([])
    code, _, _ = _check(conn, fetch=fetch)
    assert code == 0 and fetch.calls == []


def test_check_marks_timeouts_after_matching(conn):
    _sent_task(conn, "sr-old", minutes_ago=31)
    _sent_task(conn, "sr-late-but-here", minutes_ago=45)
    fetch = Recorder([{"number": 9, "title": "sr-late-but-here", "body": "made it", "url": "u9"}])
    code, out, _ = _check(conn, fetch=fetch)
    assert log.get_task(conn, "sr-old")["status"] == "timed_out"
    assert log.get_task(conn, "sr-late-but-here")["status"] == "done"
    assert "sr-old" in out


def test_check_fetch_failure_marks_no_timeouts(conn):
    _sent_task(conn, "sr-old", minutes_ago=31)
    code, out, _ = _check(conn, fetch=Recorder(raises=inbox.InboxError("gh issue list failed: HTTP 502")))
    assert code == 1 and "502" in out
    assert log.get_task(conn, "sr-old")["status"] == "sent"


def test_check_close_failure_still_logs_done(conn):
    _sent_task(conn, "sr-1")
    fetch = Recorder([{"number": 7, "title": "sr-1", "body": "pong", "url": "u7"}])
    close = Recorder(raises=inbox.InboxError("gh issue close failed"))
    code, out, _ = _check(conn, fetch=fetch, close=close)
    assert log.get_task(conn, "sr-1")["status"] == "done"
    assert "#7" in out


# ---------- log ----------

def test_log_command_prints_recent_tasks(conn):
    add_row(conn, "sr-a", "first task", "claude", "best")
    log.set_done(conn, "sr-a", "line one\nline two")
    add_row(conn, "sr-b", "second task", "grok", "override")
    lines = []
    assert cli.cmd_log(conn=conn, limit=20, out=lines.append) == 0
    text = "\n".join(lines)
    assert text.index("sr-b") < text.index("sr-a")
    assert "done" in text and "queued" in text and "first task" in text
    assert "line one line two" in text  # results shown on one line


def test_log_command_empty_log(conn):
    lines = []
    assert cli.cmd_log(conn=conn, out=lines.append) == 0
    assert "No tasks" in "\n".join(lines)


# ---------- route: slash commands ----------

@pytest.mark.parametrize("task", ["/logout", "@claude /logout", "  /cost", "@grok /clear"])
def test_route_refuses_tasks_starting_with_slash(conn, task):
    label, worker, post = fake_label(), Recorder("x"), Recorder()
    code, out = _route(conn, task, label=label, worker=worker, post=post)
    assert code == 2 and "/" in out
    assert _count(conn) == 0 and label.calls == [] and worker.calls == [] and post.calls == []


def test_route_allows_slash_later_in_the_task(conn):
    code, _ = _route(conn, "@claude what does 1/2 + 1/3 equal")
    assert code == 0 and _only_row(conn)["status"] == "done"


# ---------- main: workspace is prepared before route ----------

def test_main_route_prepares_workspace_first(monkeypatch, tmp_path):
    order = []
    monkeypatch.setattr(cli, "DB_PATH", tmp_path / "router.db")
    monkeypatch.setattr(cli.safety, "prepare_workspace", lambda *a, **k: order.append("prepare"))
    monkeypatch.setattr(cli, "cmd_route", lambda *a, **k: order.append("route") or 0)
    assert cli.main(["route", "hi"]) == 0
    assert order == ["prepare", "route"]


def test_main_route_refuses_when_workspace_cannot_be_prepared(monkeypatch, tmp_path, capsys):
    def boom(*a, **k):
        raise safety.SafeError("git init in workspace/ failed: no git")

    monkeypatch.setattr(cli, "DB_PATH", tmp_path / "router.db")
    monkeypatch.setattr(cli.safety, "prepare_workspace", boom)
    monkeypatch.setattr(cli, "cmd_route", lambda *a, **k: pytest.fail("route must not run"))
    assert cli.main(["route", "hi"]) == 2
    assert "git init" in capsys.readouterr().out


# ---------- main: only directly on the Mac ----------

@pytest.mark.parametrize("command", [["route", "hi"], ["check"], ["log"], ["show"], ["cancel"], ["serve"],
                                     ["migrate"]])
def test_main_refuses_off_the_mac_before_touching_the_log(monkeypatch, tmp_path, capsys, command):
    db = tmp_path / "router.db"
    monkeypatch.setattr(cli, "DB_PATH", db)
    monkeypatch.setattr(cli.safety, "prepare_workspace", lambda *a, **k: pytest.fail("must not prepare"))
    monkeypatch.setattr(cli.page, "serve", lambda *a, **k: pytest.fail("must not serve"))
    assert cli.main(command, platform="linux") == 2
    assert not db.exists(), "the log must not be opened at all"
    assert "Mac" in capsys.readouterr().out


def test_main_runs_on_the_mac(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "DB_PATH", tmp_path / "router.db")
    assert cli.main(["log"], platform="darwin") == 0
