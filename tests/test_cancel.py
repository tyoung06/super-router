"""`sr cancel`, and `check` coping with tasks that moved while it ran.

A cancel is stored as the status 'cancelled' (version 2 log)."""
from datetime import datetime, timedelta, timezone

import pytest

from router import __main__ as cli
from router import log
from tests.helpers import add_row

T0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
CONFIG = {"GROK_WEBHOOK_URL": "https://example.invalid/hook", "GROK_WEBHOOK_KEY": "FAKE-KEY-123"}


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _add(conn, task_id, status, agent="claude", task="a task"):
    add_row(conn, task_id, task, agent, "best")
    if status in ("sent", "done"):
        log.set_sent(conn, task_id, "uuid")
    if status == "done":
        log.set_done(conn, task_id, "pong")


def _cancel(conn, *words):
    lines = []
    code = cli.cmd_cancel(conn=conn, words=list(words), out=lines.append)
    return code, "\n".join(lines)


def _row(conn, task_id):
    return log.get_task(conn, task_id)


# ---------- log.set_cancelled ----------

def test_set_cancelled_stores_the_cancelled_status(conn):
    _add(conn, "sr-q", "queued")
    _add(conn, "sr-s", "sent", agent="grok")
    log.set_cancelled(conn, "sr-q")
    log.set_cancelled(conn, "sr-s")
    for task_id in ("sr-q", "sr-s"):
        assert (_row(conn, task_id)["status"], _row(conn, task_id)["result"]) == ("cancelled", None)


def test_set_cancelled_refuses_finished_tasks(conn):
    _add(conn, "sr-d", "done")
    with pytest.raises(log.StateError):
        log.set_cancelled(conn, "sr-d")


def test_set_cancelled_can_be_limited_to_queued(conn):
    _add(conn, "sr-s", "sent", agent="grok")
    with pytest.raises(log.StateError):
        log.set_cancelled(conn, "sr-s", allowed_from=("queued",))
    assert _row(conn, "sr-s")["status"] == "sent"


# ---------- sr cancel ----------

@pytest.mark.parametrize("ref", ["1", "#1", "sr-q"])
def test_cancel_by_number_or_task_id(conn, ref):
    _add(conn, "sr-q", "queued", task="write a long story")
    code, out = _cancel(conn, ref)
    assert code == 0
    assert _row(conn, "sr-q")["status"] == "cancelled"
    assert "#1" in out and "sr-q" in out and "write a long story" in out


def test_cancelling_a_sent_grok_task_says_only_the_log_changed(conn):
    _add(conn, "sr-g", "sent", agent="grok")
    code, out = _cancel(conn, "1")
    assert code == 0
    assert "Only the log changed" in out and "issue will stay open" in out


def test_cancel_refuses_a_finished_task(conn):
    _add(conn, "sr-d", "done")
    code, out = _cancel(conn, "1")
    assert code == 1 and "already done" in out
    assert _row(conn, "sr-d")["status"] == "done"


def test_cancel_with_no_number_and_nothing_open(conn):
    _add(conn, "sr-d", "done")
    code, out = _cancel(conn)
    assert code == 1 and "Nothing to cancel" in out


def test_cancel_with_no_number_and_one_open_task_cancels_it(conn):
    _add(conn, "sr-d", "done")
    _add(conn, "sr-q", "queued")
    code, _ = _cancel(conn)
    assert code == 0 and _row(conn, "sr-q")["status"] == "cancelled"


def test_cancel_with_no_number_and_two_open_tasks_changes_nothing(conn):
    _add(conn, "sr-a", "queued")
    _add(conn, "sr-b", "sent", agent="grok")
    code, out = _cancel(conn)
    assert code == 1 and "#1" in out and "#2" in out and "sr cancel" in out
    assert _row(conn, "sr-a")["status"] == "queued" and _row(conn, "sr-b")["status"] == "sent"


def test_cancel_refuses_words(conn):
    _add(conn, "sr-q", "queued", task="tesla question")
    code, out = _cancel(conn, "tesla")
    assert code == 1 and "task number" in out
    assert _row(conn, "sr-q")["status"] == "queued"


def test_cancel_missing_number(conn):
    code, out = _cancel(conn, "9")
    assert code == 1 and "No task #9" in out


def test_cancel_prints_task_text_safely(conn):
    _add(conn, "sr-q", "queued", task="evil \x1b[2J text")
    _, out = _cancel(conn, "1")
    assert "\x1b" not in out


def test_show_labels_a_cancelled_task(conn):
    _add(conn, "sr-q", "queued")
    log.set_cancelled(conn, "sr-q")
    lines = []
    cli.cmd_show(conn=conn, words=["1"], out=lines.append)
    assert "(cancelled by you)" in "\n".join(lines)


# ---------- check copes with tasks that moved while it ran ----------

def _sent(conn, task_id, minutes_ago=1):
    add_row(conn, task_id, "t", "grok", "override")
    log.set_sent(conn, task_id, "uuid", now=T0 - timedelta(minutes=minutes_ago))


def test_check_skips_a_task_that_was_cancelled_meanwhile_and_still_marks_timeouts(conn):
    _sent(conn, "sr-1")
    _sent(conn, "sr-old", minutes_ago=31)
    closed = []

    def fetch():
        log.set_cancelled(conn, "sr-1")  # another window cancels it while gh runs
        return [{"number": 7, "title": "sr-1", "body": "pong", "url": "https://x/7"}]

    lines = []
    code = cli.cmd_check(conn=conn, config=CONFIG, fetch=fetch, close=closed.append, now=T0, out=lines.append)
    out = "\n".join(lines)
    assert code == 0
    assert "sr-1 is already cancelled" in out and closed == []
    assert _row(conn, "sr-1")["status"] == "cancelled"
    assert _row(conn, "sr-old")["status"] == "timed_out"


def test_check_prints_each_result_it_collects(conn):
    _sent(conn, "sr-1")
    lines = []
    cli.cmd_check(conn=conn, config=CONFIG, now=T0, out=lines.append, close=lambda n: None,
                  fetch=lambda: [{"number": 7, "title": "sr-1", "body": "the answer FAKE-KEY-123", "url": "u"}])
    out = "\n".join(lines)
    assert "the answer [REDACTED]" in out and "FAKE-KEY-123" not in out


def test_mark_timeouts_skips_a_call_whose_task_moved_meanwhile(conn, monkeypatch):
    _sent(conn, "sr-old", minutes_ago=31)
    real_move = log._move

    def move_after_someone_else(conn_, task_id, *args, **kwargs):
        # Another window marks it done first (via the real _move, so this fake isn't re-entered).
        real_move(conn_, task_id, ("sent",), "done", result="arrived just in time")
        return real_move(conn_, task_id, *args, **kwargs)

    monkeypatch.setattr(log, "_move", move_after_someone_else)
    assert log.mark_timeouts(conn, now=T0, minutes=30) == []
    monkeypatch.undo()
    assert _row(conn, "sr-old")["status"] == "done"
    assert log.get_call(conn, "sr-old")["status"] == "sent", "the call is left alone when its task moved"
