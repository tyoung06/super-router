"""`route` waits for Grok's result by default (option A). Fake clock, fake gh: nothing really waits."""
import time

import pytest

from router import __main__ as cli
from router import inbox, log
from tests.helpers import add_row, shipped_roster, fake_label

SECRET = "FAKE-KEY-123"
CONFIG = {"GROK_WEBHOOK_URL": "https://example.invalid/hook", "GROK_WEBHOOK_KEY": SECRET}
ROSTER = shipped_roster()


class _Reply:
    status_code = 200

    def json(self):
        return {"success": True, "runUuid": "uuid-abc"}


class Clock:
    """Fake monotonic clock. Its sleep only moves time forward."""

    def __init__(self):
        self.t, self.sleeps = 0.0, []

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


class Inbox:
    """Fake gh. Each fetch returns (or raises) the next item; the last one repeats."""

    def __init__(self, *replies, on_fetch=None, seconds_per_fetch=0, clock=None):
        self.replies, self.on_fetch, self.calls, self.closed = list(replies), on_fetch, 0, []
        self.seconds_per_fetch, self.clock = seconds_per_fetch, clock

    def fetch(self):
        self.calls += 1
        if self.on_fetch:
            self.on_fetch(self.calls)
        if self.clock:
            self.clock.t += self.seconds_per_fetch
        reply = self.replies[min(self.calls, len(self.replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply

    def close(self, number):
        self.closed.append(number)


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _issue(task_id, body="pong", number=7):
    return {"number": number, "title": task_id, "body": body, "url": f"https://github.com/x/y/issues/{number}"}


def _route(conn, box, clock, *, wait=True, post=None, task="@grok what is up on X", worker=None):
    lines = []
    code = cli.cmd_route(
        task, conn=conn, config=CONFIG, roster=ROSTER, label=fake_label(), environ={}, settings_paths=[],
        post=post or (lambda *a, **k: _Reply()),
        worker=worker or (lambda t: "an answer"),
        fetch=box.fetch, close=box.close, sleep=clock.sleep, clock=clock, wait=wait,
        out=lines.append,
    )
    return code, "\n".join(lines), log.recent_tasks(conn)[0]


def test_waits_and_prints_the_result_when_it_arrives(conn):
    clock = Clock()
    box = Inbox([], [], "LATER")  # replaced below once the task_id is known
    box.on_fetch = lambda n: box.replies.__setitem__(2, [_issue(log.recent_tasks(conn)[0]["task_id"], "the answer " + SECRET)])
    code, out, row = _route(conn, box, clock)
    assert code == 0
    assert (row["status"], row["result"]) == ("done", "the answer [REDACTED]")
    assert "the answer [REDACTED]" in out and SECRET not in out
    assert box.closed == [7] and clock.sleeps == [20, 20]


def test_gives_up_at_the_deadline_and_leaves_the_task_sent(conn):
    clock = Clock()
    box = Inbox([])
    code, out, row = _route(conn, box, clock)
    assert code == 3
    assert row["status"] == "sent"
    assert "don't resend" in out and "sr check" in out
    assert sum(clock.sleeps) == 600 and box.calls == 31


def test_deadline_holds_even_when_gh_is_slow(conn):
    clock = Clock()
    box = Inbox([], seconds_per_fetch=60, clock=clock)
    code, _, _ = _route(conn, box, clock)
    assert code == 3 and clock.t <= 600 + 60


def test_three_inbox_errors_in_a_row_stop_waiting_but_never_mark_failed(conn):
    clock = Clock()
    box = Inbox(inbox.InboxError("gh issue list failed: HTTP 502"))
    code, out, row = _route(conn, box, clock)
    assert code == 3 and box.calls == 3
    assert row["status"] == "sent"
    assert "WAS sent" in out and "don't resend" in out


def test_inbox_errors_reset_after_a_good_read(conn):
    clock = Clock()
    err = inbox.InboxError("gh issue list failed: HTTP 502")
    box = Inbox(err, err, [], err, err, "LATER")
    box.on_fetch = lambda n: box.replies.__setitem__(5, [_issue(log.recent_tasks(conn)[0]["task_id"])])
    code, _, row = _route(conn, box, clock)
    assert code == 0 and row["status"] == "done"


def test_logged_out_gh_stops_waiting_at_once(conn):
    clock = Clock()
    box = Inbox(inbox.InboxError("gh issue list failed: not logged in", returncode=4))
    code, out, row = _route(conn, box, clock)
    assert code == 3 and box.calls == 1 and row["status"] == "sent"


def test_an_empty_issue_body_counts_as_not_ready(conn):
    clock = Clock()
    box = Inbox("LATER", "LATER")

    def fill(n):
        task_id = log.recent_tasks(conn)[0]["task_id"]
        box.replies[0] = [_issue(task_id, body="   ")]
        box.replies[1] = [_issue(task_id, body="real answer")]
    box.on_fetch = fill
    code, _, row = _route(conn, box, clock)
    assert code == 0 and row["result"] == "real answer" and clock.sleeps == [20]


def test_only_its_own_task_is_collected(conn):
    add_row(conn, "sr-other", "other task", "grok", "override")
    log.set_sent(conn, "sr-other", "uuid-other")
    clock = Clock()
    box = Inbox("LATER")
    box.on_fetch = lambda n: box.replies.__setitem__(0, [
        _issue("sr-other", "not mine", number=5), _issue(log.recent_tasks(conn)[0]["task_id"], "mine", number=6)])
    code, _, _ = _route(conn, box, clock)
    assert code == 0 and box.closed == [6]
    assert log.get_task(conn, "sr-other")["status"] == "sent"


def test_a_result_collected_by_another_command_is_shown(conn):
    clock = Clock()

    def someone_else_checks(n):
        if n == 2:
            log.set_done(conn, log.recent_tasks(conn)[0]["task_id"], "collected by sr check")
    box = Inbox([], on_fetch=someone_else_checks)
    code, out, row = _route(conn, box, clock)
    assert code == 0 and "collected by sr check" in out and box.closed == []


def test_a_cancel_from_another_window_stops_the_wait(conn):
    clock = Clock()
    box = Inbox([], on_fetch=lambda n: log.set_cancelled(conn, log.recent_tasks(conn)[0]["task_id"]))
    code, out, row = _route(conn, box, clock)
    assert code == 1 and "cancelled" in out and row["status"] == "cancelled"


def test_no_wait_returns_at_once(conn):
    clock = Clock()
    box = Inbox([])
    code, out, row = _route(conn, box, clock, wait=False)
    assert code == 0 and row["status"] == "sent"
    assert box.calls == 0 and clock.sleeps == []
    assert "sr check" in out


def test_a_failed_close_still_counts_as_done(conn):
    clock = Clock()
    box = Inbox("LATER")
    box.on_fetch = lambda n: box.replies.__setitem__(0, [_issue(log.recent_tasks(conn)[0]["task_id"])])

    def close(number):
        raise inbox.InboxError("gh issue close failed")
    box.close = close
    code, out, row = _route(conn, box, clock)
    assert code == 0 and row["status"] == "done" and "could not close issue #7" in out


def test_a_cancel_during_the_send_is_reported(conn):
    clock = Clock()

    def post(*args, **kwargs):
        log.set_cancelled(conn, log.recent_tasks(conn)[0]["task_id"])
        return _Reply()
    code, out, row = _route(conn, Inbox([]), clock, post=post)
    assert code == 1 and "Grok may still" in out and row["status"] == "cancelled"


def test_a_claude_answer_for_a_task_cancelled_meanwhile_is_shown_as_not_saved(conn):
    def worker(task):
        log.set_cancelled(conn, log.recent_tasks(conn)[0]["task_id"])
        return "late answer"
    lines = []
    code = cli.cmd_route("@claude hi", conn=conn, config=CONFIG, roster=ROSTER, label=fake_label(), environ={}, settings_paths=[],
                         post=None, worker=worker, out=lines.append)
    out = "\n".join(lines)
    assert code == 1 and "not saved" in out and "late answer" in out
    assert log.recent_tasks(conn)[0]["status"] == "cancelled"


# ---------- inbox details ----------

def test_inbox_error_carries_the_gh_exit_code(fake_run):
    with pytest.raises(inbox.InboxError) as err:
        inbox.fetch_issues(run=fake_run(returncode=4, stderr="To get started with GitHub CLI, please run: gh auth login"))
    assert err.value.returncode == 4


# ---------- main wires the real pieces ----------

def _capture_route(monkeypatch, terminal):
    seen = {}
    monkeypatch.setattr(cli.safety, "prepare_workspace", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_stdout_is_terminal", lambda: terminal)
    monkeypatch.setattr(cli, "cmd_route", lambda task, **kw: seen.update(kw) or 0)
    return seen


def test_main_waits_by_default_in_a_terminal(monkeypatch):
    seen = _capture_route(monkeypatch, terminal=True)
    assert cli.main(["route", "hi"], platform="darwin") == 0
    assert seen["wait"] is True
    assert seen["fetch"] is inbox.fetch_issues and seen["close"] is inbox.close_issue
    assert seen["sleep"] is time.sleep and seen["clock"] is time.monotonic


def test_main_no_wait_flag(monkeypatch):
    seen = _capture_route(monkeypatch, terminal=True)
    assert cli.main(["route", "--no-wait", "hi"], platform="darwin") == 0
    assert seen["wait"] is False


def test_main_does_not_wait_when_output_is_not_a_terminal(monkeypatch):
    seen = _capture_route(monkeypatch, terminal=False)
    assert cli.main(["route", "hi"], platform="darwin") == 0
    assert seen["wait"] is False


def test_main_does_not_accept_abbreviated_flags(monkeypatch):
    seen = _capture_route(monkeypatch, terminal=True)
    with pytest.raises(SystemExit):
        cli.main(["route", "tell", "me", "--no"], platform="darwin")
    assert seen == {}
