"""The check loop inside `route` and `sr check`, with Claude as the checker: every ending of
the brief's section 5 as the owner sees it, with fake agents. Every secret here is fake."""
import signal

import pytest

from router import __main__ as cli
from router import checking, log
from tests.helpers import fake_label, grok_era_roster

SECRET = "FAKE-KEY-123"
CONFIG = {"GROK_WEBHOOK_URL": "https://example.invalid/hook", "GROK_WEBHOOK_KEY": SECRET}
# The loop mechanics here are Grok does, Claude checks (web_research before ChatGPT went live, and
# still every @grok task), so these tests use build brief 2's roster: chatgpt off, grok the stand-in.
ROSTER = grok_era_roster()
TASK = "find sources on the new EU AI rules"
RESULT = "The EU AI Act applies from 2026. Source: https://example.org/ai-act"
FIXED = "The EU AI Act applies in stages from 2 Feb 2025. Source: https://example.org/ai-act"
WEB = {"status": "ok", "label": "web_research", "confidence": 0.93, "needs_split": 0.1, "tokens": 764}
CODE = {"status": "ok", "label": "code", "confidence": 0.93, "needs_split": 0.1, "tokens": 764}
BULK = {"status": "ok", "label": "bulk_text", "confidence": 0.93, "needs_split": 0.1, "tokens": 764}


class Scripted:
    """A fake agent: each call returns the next scripted reply (or raises it). Records prompts."""

    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        reply = self.replies.pop(0) if self.replies else "an answer"
        if isinstance(reply, BaseException) or isinstance(reply, type):
            raise reply
        return reply


class _Reply:
    def __init__(self, status_code=200, body=None):
        self.status_code, self._body = status_code, body or {"success": True, "runUuid": "uuid-abc"}

    def json(self):
        return self._body


class Webhook:
    """A fake webhook plus inbox. Each send is recorded; replies are scripted per call id."""

    def __init__(self, fail=(), **bodies):
        """`bodies`: the issue body per call ("do", "c1", "f1", "c2"). `fail`: the calls whose
        send the webhook refuses with HTTP 500."""
        self.sent, self.closed, self.calls, self.bodies, self.fail = [], [], 0, bodies, fail

    @staticmethod
    def _key(call_id):
        return call_id.split("-")[-1] if call_id.count("-") == 4 else "do"

    def post(self, url, headers=None, json=None, timeout=None):
        self.sent.append(json)
        if self._key(json["task_id"]) in self.fail:
            return _Reply(500, {"error": "server"})
        return _Reply()

    def fetch(self):
        self.calls += 1
        issues = []
        for n, payload in enumerate(self.sent, 1):
            call_id = payload["task_id"]
            key = self._key(call_id)
            if key in self.bodies and key not in self.fail:
                issues.append({"number": n, "title": call_id, "body": self.bodies[key],
                               "url": f"https://github.com/x/y/issues/{n}"})
        return issues

    def close(self, number):
        self.closed.append(number)


class Clock:
    def __init__(self):
        self.t, self.sleeps = 0.0, []

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _route(conn, task, jev, *, worker=None, hook=None, wait=True, environ=None):
    lines, clock = [], Clock()
    hook = hook or Webhook()
    worker = worker or Scripted()
    try:
        code = cli.cmd_route(
            task, conn=conn, config=CONFIG, roster=ROSTER, environ=environ or {}, settings_paths=[],
            label=fake_label(jev), post=hook.post, worker=worker, fetch=hook.fetch, close=hook.close,
            sleep=clock.sleep, clock=clock, wait=wait, out=lines.append,
        )
    except KeyboardInterrupt:
        pytest.fail("KeyboardInterrupt escaped cmd_route")
    rows = log.recent_tasks(conn)
    assert len(rows) == 1
    return code, "\n".join(lines), rows[0], worker, hook


def _check(conn, *, worker=None, hook=None, environ=None, now=None):
    lines = []
    hook = hook or Webhook()
    worker = worker or Scripted()
    code = cli.cmd_check(conn=conn, config=CONFIG, environ=environ or {}, settings_paths=[], post=hook.post,
                         worker=worker, fetch=hook.fetch, close=hook.close, now=now, out=lines.append)
    return code, "\n".join(lines)


def _calls(conn, task_id):
    return [(c["call_id"], c["kind"], c["agent"], c["status"], c["verdict"]) for c in log.calls_for(conn, task_id)]


# ---------- rows 1 and 2: nothing to check ----------

def test_row_1_quick_answer_prints_the_result_and_no_line(conn):
    code, out, row, _, _ = _route(conn, "what is 15% of 240", {**WEB, "label": "quick_answer"}, worker=Scripted("36"))
    assert code == 0 and (row["status"], row["result"], row["check_state"]) == ("done", "36", "not_needed")
    assert "36" in out and "CHECKED" not in out and "UNCHECKED" not in out
    assert _calls(conn, row["task_id"]) == [(row["task_id"], "do", "claude", "done", None)]


def test_row_2_checker_not_live_prints_UNCHECKED_and_why(conn):
    code, out, row, _, _ = _route(conn, "write a parser", CODE, worker=Scripted("def parse(): ..."))
    # brief 24 (decision 4): no checker is named when none is available, and the note says why in its words
    assert code == 0 and (row["status"], row["check_state"], row["checker"]) == ("done", "unchecked", None)
    why = "no other agent available to check (ChatGPT is off: not live in config/agents.json)"
    assert row["check_note"] == why
    assert f"UNCHECKED: {why}." in out
    assert out.index("def parse") < out.index("UNCHECKED:")


# ---------- rows 3 to 8: Grok does, Claude checks ----------

def test_row_3_first_check_passes(conn):
    hook = Webhook(do=RESULT)
    worker = Scripted("PASS")
    code, out, row, worker, hook = _route(conn, TASK, WEB, worker=worker, hook=hook)
    task_id = row["task_id"]
    assert code == 0
    assert (row["status"], row["result"], row["check_state"], row["check_note"]) == ("done", RESULT, "passed", None)
    assert row["result_url"] == "https://github.com/x/y/issues/1"
    assert _calls(conn, task_id) == [(task_id, "do", "grok", "done", None), (f"{task_id}-c1", "check", "claude", "done", "PASS")]
    assert "CHECKED (sanity check only): passed." in out and "can't open links" in out
    assert out.index(RESULT) < out.index("CHECKED")
    assert worker.prompts == [checking.checker_prompt(TASK, RESULT, no_tools=True)]
    assert hook.closed == [1]


@pytest.mark.parametrize("reply, reason", [
    ("Looks fine to me.", "unreadable verdict"),
    (cli.claude_worker.WorkerError("claude exited 1: not logged in"), "claude exited 1: not logged in"),
])
def test_row_4_first_check_did_not_run(conn, reply, reason):
    code, out, row, _, _ = _route(conn, TASK, WEB, worker=Scripted(reply), hook=Webhook(do=RESULT))
    assert code == 0
    assert (row["status"], row["result"], row["check_state"]) == ("done", RESULT, "unchecked")
    assert row["check_note"] == f"check round by claude didn't run: {reason}"
    assert f"CHECK ROUND FAILED: claude, {reason}. This result is unchecked." in out
    assert "CHECKED" not in out.replace("UNCHECKED", "").replace("CHECK ROUND", "")


def test_row_5_fix_round_did_not_run(conn):
    hook = Webhook(do=RESULT, fail=("f1",))  # the fix send fails
    code, out, row, worker, hook = _route(conn, TASK, WEB, worker=Scripted("FIX\n1. Give the exact date."), hook=hook)
    task_id = row["task_id"]
    assert code == 5
    assert (row["status"], row["result"], row["check_state"]) == ("done", RESULT, "failed")
    assert row["check_note"] == "fix round by grok didn't run: webhook returned HTTP 500: server"
    assert hook.sent[1]["task_id"] == f"{task_id}-f1"
    assert hook.sent[1]["task"] == checking.fix_prompt(TASK, RESULT, "1. Give the exact date.", count=True)
    assert "FIX ROUND FAILED: grok, webhook returned HTTP 500: server." in out
    assert "The checker's fix list:" in out and "1. Give the exact date." in out
    assert _calls(conn, task_id)[-1] == (f"{task_id}-f1", "fix", "grok", "failed", None)


def test_row_6_fixed_then_passes_and_the_original_is_not_printed(conn):
    hook = Webhook(do=RESULT, f1=FIXED)
    code, out, row, worker, hook = _route(conn, TASK, WEB, worker=Scripted("FIX\n1. Give the exact date.", "PASS"), hook=hook)
    task_id = row["task_id"]
    assert code == 0
    assert (row["status"], row["result"], row["check_state"], row["check_note"]) == ("done", FIXED, "fixed", None)
    assert [c[1:] for c in _calls(conn, task_id)] == [
        ("do", "grok", "done", None), ("check", "claude", "done", "FIX"), ("fix", "grok", "done", None),
        ("recheck", "claude", "done", "PASS")]
    assert "CHECKED (sanity check only): passed after one fix." in out
    assert f"sr show {row['n']} --history" in out
    assert FIXED in out and RESULT not in out and "Give the exact date" not in out
    assert worker.prompts[1] == checking.checker_prompt(TASK, FIXED, no_tools=True)
    assert hook.closed == [1, 2]


def test_row_7_recheck_did_not_run(conn):
    hook = Webhook(do=RESULT, f1=FIXED)
    code, out, row, _, _ = _route(conn, TASK, WEB, worker=Scripted("FIX\n1. Give the exact date.", "Seems ok"), hook=hook)
    assert code == 0
    assert (row["status"], row["result"], row["check_state"]) == ("done", FIXED, "unchecked")
    assert row["check_note"].startswith("re-check by claude didn't run: unreadable verdict")
    assert "CHECK ROUND FAILED: claude (the re-check), unreadable verdict. The first check asked for fixes; this is the fixed result." in out
    assert FIXED in out and RESULT not in out


def test_row_8_fix_then_fix_again(conn):
    hook = Webhook(do=RESULT, f1=FIXED)
    code, out, row, _, _ = _route(conn, TASK, WEB, worker=Scripted("FIX\n1. Give the exact date.", "FIX\n1. Still no source for the date."), hook=hook)
    assert code == 5
    assert (row["status"], row["result"], row["check_state"]) == ("done", FIXED, "failed")
    assert row["check_note"] == "not passed after one fix round"
    assert "NOT PASSED: after one fix round. What the checker still wants fixed:" in out
    assert "1. Still no source for the date." in out
    assert FIXED in out and RESULT not in out and "Give the exact date" not in out


# ---------- a result that says it couldn't do the task ----------

def test_the_checker_is_told_that_a_result_which_could_not_do_the_task_never_passes(conn):
    could_not = "I couldn't verify this because web access failed in this session."
    _, _, row, worker, _ = _route(conn, TASK, WEB, worker=Scripted("FIX\n1. The task was not done."), hook=Webhook(do=could_not, f1=could_not))
    for prompt in worker.prompts:
        assert checking.NO_RESULT_RULE in prompt
    # The rule reaches the re-check too, so a fix that still says "I couldn't" is judged the same way.
    assert len(worker.prompts) == 2 and row["check_state"] in ("failed", "unchecked")


# ---------- the prompts carry only the task and the result ----------

def test_the_checker_sees_the_task_and_the_result_and_nothing_names_an_agent(conn):
    _, _, row, worker, _ = _route(conn, TASK, WEB, worker=Scripted("PASS"), hook=Webhook(do=RESULT))
    prompt = worker.prompts[0]
    assert TASK in prompt and RESULT in prompt
    for name in ("claude", "grok", "chatgpt", "muse", "jev"):
        assert name not in prompt.lower()


# ---------- --no-wait, then sr check finishes the loop ----------

def test_a_no_wait_task_is_finished_by_sr_check(conn):
    hook = Webhook(do=RESULT)
    code, out, row, _, _ = _route(conn, TASK, WEB, hook=hook, wait=False)
    assert code == 0 and (row["status"], row["check_state"], row["result"]) == ("sent", "pending", None)
    assert "Not waiting" in out and hook.calls == 0
    code, out = _check(conn, worker=Scripted("PASS"), hook=hook)
    row = log.get_task(conn, row["task_id"])
    assert code == 0 and (row["status"], row["result"], row["check_state"]) == ("done", RESULT, "passed")
    assert RESULT in out and "CHECKED (sanity check only): passed." in out
    assert hook.closed == [1]


def test_sr_check_returns_5_when_a_task_it_finishes_was_not_passed(conn):
    hook = Webhook(do=RESULT, f1=FIXED)
    _, _, row, _, _ = _route(conn, TASK, WEB, hook=hook, wait=False)
    # Run 1 collects the result, runs the check (FIX) and sends the fix to Grok. Run 2 collects
    # the fix, runs the re-check (FIX again) and ends the task.
    code, out = _check(conn, worker=Scripted("FIX\n1. x"), hook=hook)
    assert code == 0 and f"{row['task_id']}-f1" in out and "sr check" in out
    assert log.get_task(conn, row["task_id"])["status"] == "sent"
    code, out = _check(conn, worker=Scripted("FIX\n1. y"), hook=hook)
    assert code == 5 and "NOT PASSED" in out
    assert log.get_task(conn, row["task_id"])["check_state"] == "failed"


def test_sr_check_refused_by_a_billing_switch_sends_nothing(conn):
    hook = Webhook(do=RESULT)
    _, _, row, _, _ = _route(conn, TASK, WEB, hook=hook, wait=False)
    worker = Scripted("PASS")
    code, out = _check(conn, worker=worker, hook=hook, environ={"ANTHROPIC_API_KEY": "FAKE"})
    assert code == 2 and "ANTHROPIC_API_KEY" in out and "FAKE" not in out
    assert hook.calls == 0 and worker.prompts == [] and len(hook.sent) == 1
    assert log.get_task(conn, row["task_id"])["status"] == "sent"


def test_sr_check_says_what_each_open_task_waits_for(conn):
    hook = Webhook()
    _, _, row, _, _ = _route(conn, TASK, WEB, hook=hook, wait=False)
    code, out = _check(conn, hook=hook)
    assert code == 0 and f"#{row['n']}" in out and row["task_id"] in out and "grok" in out and "1 task(s) still open" in out


# ---------- Ctrl+C ----------

def test_ctrl_c_during_the_claude_check_leaves_the_task_open_with_no_failed_round(conn):
    hook = Webhook(do=RESULT)
    original = signal.getsignal(signal.SIGINT)
    code, out, row, _, hook = _route(conn, TASK, WEB, worker=Scripted(KeyboardInterrupt), hook=hook)
    task_id = row["task_id"]
    assert code == 130
    assert (row["status"], row["result"], row["check_state"]) == ("queued", None, "pending")
    assert _calls(conn, task_id) == [(task_id, "do", "grok", "done", None)], "no check call row was written"
    assert "sr check" in out and RESULT not in out and "UNCHECKED" not in out
    assert signal.getsignal(signal.SIGINT) is original
    code, out = _check(conn, worker=Scripted("PASS"), hook=hook)
    assert code == 0 and log.get_task(conn, task_id)["check_state"] == "passed" and RESULT in out


def test_ctrl_c_during_the_first_claude_call_still_cancels(conn):
    code, out, row, _, _ = _route(conn, "write a parser", CODE, worker=Scripted(KeyboardInterrupt))
    assert code == 130 and row["status"] == "cancelled" and _calls(conn, row["task_id"]) == []


def test_ctrl_c_while_waiting_on_the_fix_leaves_the_task_sent(conn):
    hook = Webhook(do=RESULT)  # the fix never arrives
    worker = Scripted("FIX\n1. Give the exact date.")

    def fetch_then_ctrl_c():
        issues = hook.fetch()
        if any(i["title"].endswith("-f1") for i in issues) or len(hook.sent) == 2:
            raise KeyboardInterrupt
        return issues

    lines, clock = [], Clock()
    code = cli.cmd_route(TASK, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=fake_label(WEB), post=hook.post, worker=worker, fetch=fetch_then_ctrl_c,
                         close=hook.close, sleep=clock.sleep, clock=clock, wait=True, out=lines.append)
    row = log.recent_tasks(conn)[0]
    assert code == 130 and row["status"] == "sent"
    assert _calls(conn, row["task_id"])[-1][1:] == ("fix", "grok", "sent", None)
    assert "sr check" in "\n".join(lines)


# ---------- waiting runs out mid-loop ----------

def test_a_wait_that_runs_out_on_the_fix_says_which_call_is_out(conn):
    hook = Webhook(do=RESULT)
    code, out, row, _, _ = _route(conn, TASK, WEB, worker=Scripted("FIX\n1. Give the exact date."), hook=hook)
    assert code == 3 and row["status"] == "sent"
    assert f"{row['task_id']}-f1" in out and "fix" in out and "sr check" in out


# ---------- show and history, as far as phase C goes ----------

def test_show_prints_the_ending_line_and_never_the_original(conn):
    hook = Webhook(do=RESULT, f1=FIXED)
    _, _, row, _, _ = _route(conn, TASK, WEB, worker=Scripted("FIX\n1. Give the exact date.", "PASS"), hook=hook)
    lines = []
    assert cli.cmd_show(conn=conn, words=[str(row["n"])], out=lines.append) == 0
    out = "\n".join(lines)
    assert FIXED in out and RESULT not in out and "CHECKED (sanity check only): passed after one fix." in out
