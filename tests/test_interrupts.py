"""Ctrl+C during `route` acts on the task's real state in the log. Exit code 130, no traceback.

Every call goes through _route, which turns an escaped KeyboardInterrupt into a test failure
instead of ending the whole pytest run."""
import signal

import pytest

from router import __main__ as cli
from router import log
from tests.helpers import shipped_roster, fake_label

CONFIG = {"GROK_WEBHOOK_URL": "https://example.invalid/hook", "GROK_WEBHOOK_KEY": "FAKE-KEY-123"}
ROSTER = shipped_roster()


class _Reply:
    status_code = 200

    def json(self):
        return {"success": True, "runUuid": "uuid-abc"}


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _ctrl_c(*args, **kwargs):
    raise KeyboardInterrupt


def _route(conn, task="@grok what is up on X", *, post=None, worker=None,
           fetch=None, sleep=None, close=None, out=None):
    lines = []
    try:
        code = cli.cmd_route(
            task, conn=conn, config=CONFIG, roster=ROSTER, label=fake_label(), environ={}, settings_paths=[],
            post=post or (lambda *a, **k: _Reply()),
            worker=worker or (lambda t: "an answer"), fetch=fetch or (lambda: []),
            close=close or (lambda n: None), sleep=sleep or (lambda s: None), clock=lambda: 0.0,
            wait=True, out=out or lines.append,
        )
    except KeyboardInterrupt:
        pytest.fail("KeyboardInterrupt escaped cmd_route")
    return code, "\n".join(lines)


def _only_row(conn):
    rows = log.recent_tasks(conn)
    return rows[0] if rows else None


def test_during_the_claude_worker_the_task_is_cancelled(conn):
    code, out = _route(conn, "@claude write a story", worker=_ctrl_c)
    row = _only_row(conn)
    assert code == 130
    assert (row["status"], row["result"]) == ("cancelled", None)
    assert "cancelled" in out


@pytest.mark.parametrize("where", ["sleep", "fetch"])
def test_during_the_wait_the_task_stays_sent(conn, where):
    kwargs = {where: _ctrl_c}
    code, out = _route(conn, **kwargs)
    row = _only_row(conn)
    assert code == 130 and row["status"] == "sent"
    assert "Stopped waiting" in out and "sr check" in out


def test_during_the_send_the_send_finishes_first(conn):
    original = signal.getsignal(signal.SIGINT)

    def post(*args, **kwargs):
        signal.raise_signal(signal.SIGINT)  # The owner presses Ctrl+C mid-send
        return _Reply()

    code, out = _route(conn, post=post)
    row = _only_row(conn)
    assert code == 130
    assert (row["status"], row["run_uuid"]) == ("sent", "uuid-abc")
    assert "Stopped before waiting" in out and "sr check" in out
    assert signal.getsignal(signal.SIGINT) is original


def test_during_the_send_while_logging_it_as_sent(conn, monkeypatch):
    real_set_sent = log.set_sent

    def set_sent(*args, **kwargs):
        signal.raise_signal(signal.SIGINT)
        return real_set_sent(*args, **kwargs)

    monkeypatch.setattr(log, "set_sent", set_sent)
    code, _ = _route(conn)
    assert code == 130 and _only_row(conn)["status"] == "sent"


def test_during_a_failing_send_the_failure_is_reported(conn):
    original = signal.getsignal(signal.SIGINT)

    def post(*args, **kwargs):
        signal.raise_signal(signal.SIGINT)
        raise ConnectionError("network down")

    code, out = _route(conn, post=post)
    assert code == 1 and _only_row(conn)["status"] == "failed"
    assert signal.getsignal(signal.SIGINT) is original


def test_after_the_result_is_saved_it_is_still_shown(conn):
    task = {}

    def fetch():
        task_id = _only_row(conn)["task_id"]
        return [{"number": 7, "title": task_id, "body": "pong", "url": "https://github.com/x/y/issues/7"}]

    code, out = _route(conn, fetch=fetch, close=_ctrl_c)
    row = _only_row(conn)
    assert code == 130 and row["status"] == "done"
    assert "pong" in out


def test_a_second_ctrl_c_during_cleanup_is_held(conn, monkeypatch):
    real = log.set_cancelled

    def set_cancelled(*args, **kwargs):
        signal.raise_signal(signal.SIGINT)  # pressed again while the cancel is written
        return real(*args, **kwargs)

    monkeypatch.setattr(log, "set_cancelled", set_cancelled)
    code, _ = _route(conn, "@claude write a story", worker=_ctrl_c)
    assert code == 130 and _only_row(conn)["status"] == "cancelled"


def test_an_unfinished_write_is_rolled_back_then_the_arrived_result_is_delivered(conn, monkeypatch):
    real_set_done = log.set_done

    def half_written_set_done(conn_, task_id, result, result_url=None, **fields):
        monkeypatch.setattr(log, "set_done", real_set_done)  # only the first write is interrupted
        conn_.execute("UPDATE tasks SET status = 'done', result = ? WHERE task_id = ?", (result, task_id))
        raise KeyboardInterrupt  # Ctrl+C lands before the commit

    monkeypatch.setattr(log, "set_done", half_written_set_done)
    code, out = _route(conn, "@claude write a story")
    row = _only_row(conn)
    # The answer already lives in the task's call row, so after the rollback it is delivered, not lost.
    assert code == 130
    assert (row["status"], row["result"]) == ("done", "an answer")
    assert "already arrived" in out and "an answer" in out
