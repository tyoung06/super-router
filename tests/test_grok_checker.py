"""Phase D: Grok inside the loop as a checker (by sub-id), timed-out calls landing in the right
endings, `sr check` moving a task forward one Grok call per run, and `sr cancel` mid-loop.
Fakes only; nothing reaches the webhook."""
from datetime import datetime, timedelta, timezone

import pytest

from router import __main__ as cli
from router import checking, log
from tests.helpers import ALL_AGENTS, JEV_OK
from tests.test_loop import CONFIG, FIXED, RESULT, TASK, WEB, Scripted, Webhook, _calls, _check, _route

BULK = {"status": "ok", "label": "bulk_text", "confidence": 0.93, "needs_split": 0.1, "tokens": 764}
BULK_TASK = "@claude tag these 40 posts"
T0 = datetime(2026, 10, 13, 20, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def test_phase_c_downgrade_is_gone():
    assert not hasattr(cli, "BUILT_CHECKERS")


# ---------- Grok checks a Claude task, by sub-id ----------

def test_grok_checks_a_claude_task_by_sub_id(conn):
    hook = Webhook(c1="PASS\nAll tagged correctly.")
    code, out, row, worker, hook = _route(conn, BULK_TASK, BULK, worker=Scripted("tagged list"), hook=hook)
    task_id = row["task_id"]
    assert code == 0
    assert (row["agent"], row["checker"], row["check_state"], row["result"], row["status"]) == (
        "claude", "grok", "passed", "tagged list", "done")
    assert hook.sent[0]["task_id"] == f"{task_id}-c1"
    # Grok always browses (rules v2.9), so its check prompt says it may open links, whatever the skill.
    assert hook.sent[0]["task"] == checking.checker_prompt("tag these 40 posts", "tagged list", no_tools=False, can_browse=True)
    assert _calls(conn, task_id) == [(task_id, "do", "claude", "done", None),
                                     (f"{task_id}-c1", "check", "grok", "done", "PASS")]
    assert "CHECKED: passed." in out and "sanity" not in out
    assert hook.closed == [1]


def test_grok_fix_list_goes_to_claude_and_grok_rechecks_by_sub_id(conn):
    hook = Webhook(c1="FIX\n1. Post 7 is tagged wrong.", c2="PASS")
    worker = Scripted("tagged list", "fixed tagged list")
    code, out, row, worker, hook = _route(conn, BULK_TASK, BULK, worker=worker, hook=hook)
    task_id = row["task_id"]
    assert code == 0 and (row["check_state"], row["result"]) == ("fixed", "fixed tagged list")
    assert worker.prompts[1] == checking.fix_prompt("tag these 40 posts", "tagged list", "1. Post 7 is tagged wrong.", count=True)
    assert [c[1:3] for c in _calls(conn, task_id)] == [
        ("do", "claude"), ("check", "grok"), ("fix", "claude"), ("recheck", "grok")]
    assert [p["task_id"] for p in hook.sent] == [f"{task_id}-c1", f"{task_id}-c2"]
    assert "CHECKED: passed after one fix." in out and "tagged list" in out
    assert out.count("tagged list") == 1, "the original is not printed"
    assert hook.closed == [1, 2]


def test_a_grok_check_the_webhook_refuses_is_a_failed_check_round(conn):
    hook = Webhook(fail=("c1",))
    code, out, row, _, _ = _route(conn, BULK_TASK, BULK, worker=Scripted("tagged list"), hook=hook)
    assert code == 0 and (row["check_state"], row["result"]) == ("unchecked", "tagged list")
    assert row["check_note"] == "check round by grok didn't run: webhook returned HTTP 500: server"
    assert "CHECK ROUND FAILED: grok, webhook returned HTTP 500: server. This result is unchecked." in out


def test_grok_fix_again_is_not_passed(conn):
    hook = Webhook(c1="FIX\n1. Post 7 is tagged wrong.", c2="FIX\n1. Post 7 is still wrong.")
    code, out, row, _, _ = _route(conn, BULK_TASK, BULK, worker=Scripted("tagged list", "fixed tagged list"), hook=hook)
    assert code == 5 and row["check_state"] == "failed" and row["result"] == "fixed tagged list"
    assert "NOT PASSED: after one fix round." in out and "1. Post 7 is still wrong." in out


# ---------- timed-out calls land in the right endings ----------

def _bulk_task(conn, task_id="sr-b"):
    log.add_task(conn, task_id, "tag these 40 posts", "cli", BULK, now=T0 - timedelta(minutes=40))
    log.set_route(conn, task_id, agents=ALL_AGENTS, agent="claude", route_reason="override", skill="bulk_text",
                  skill_source="jev", checker="grok", check_state="pending")
    log.add_call(conn, task_id, task_id, "do", "claude", status="done", text="tagged list", now=T0 - timedelta(minutes=39))
    return task_id


def _web_task(conn, task_id="sr-w"):
    log.add_task(conn, task_id, TASK, "cli", WEB, now=T0 - timedelta(minutes=40))
    log.set_route(conn, task_id, agents=ALL_AGENTS, agent="grok", route_reason="interim", skill="web_research",
                  skill_source="jev", checker="claude", check_state="pending")
    log.set_sent(conn, task_id, "uuid-do", now=T0 - timedelta(minutes=39))
    log.finish_call(conn, task_id, "done", text=RESULT, url="https://github.com/x/y/issues/1", now=T0 - timedelta(minutes=38))
    return task_id


def test_a_timed_out_check_delivers_the_result_unchecked(conn):
    task_id = _bulk_task(conn)
    log.add_call(conn, f"{task_id}-c1", task_id, "check", "grok", run_uuid="u", now=T0 - timedelta(minutes=31))
    log.set_open_status(conn, task_id, "sent")
    code, out = _check(conn, now=T0)
    row = log.get_task(conn, task_id)
    assert code == 0 and (row["status"], row["check_state"], row["result"]) == ("done", "unchecked", "tagged list")
    assert row["check_note"] == "check round by grok didn't run: timed out"
    assert f"{task_id}-c1 timed out" in out
    assert "CHECK ROUND FAILED: grok, timed out. This result is unchecked." in out


def test_a_timed_out_fix_delivers_the_original_and_the_fix_list(conn):
    task_id = _web_task(conn)
    log.add_call(conn, f"{task_id}-c1", task_id, "check", "claude", status="done", text="FIX\n1. Give the exact date.",
                 verdict="FIX", now=T0 - timedelta(minutes=37))
    log.add_call(conn, f"{task_id}-f1", task_id, "fix", "grok", run_uuid="u", now=T0 - timedelta(minutes=31))
    log.set_open_status(conn, task_id, "sent")
    code, out = _check(conn, now=T0)
    row = log.get_task(conn, task_id)
    assert code == 5 and (row["status"], row["check_state"], row["result"]) == ("done", "failed", RESULT)
    assert "FIX ROUND FAILED: grok, timed out." in out and "1. Give the exact date." in out


def test_a_timed_out_recheck_delivers_the_fixed_result_unchecked(conn):
    task_id = _bulk_task(conn)
    log.add_call(conn, f"{task_id}-c1", task_id, "check", "grok", status="done", text="FIX\n1. Post 7 is wrong.",
                 verdict="FIX", now=T0 - timedelta(minutes=37))
    log.add_call(conn, f"{task_id}-f1", task_id, "fix", "claude", status="done", text="fixed tagged list",
                 now=T0 - timedelta(minutes=36))
    log.add_call(conn, f"{task_id}-c2", task_id, "recheck", "grok", run_uuid="u", now=T0 - timedelta(minutes=31))
    log.set_open_status(conn, task_id, "sent")
    code, out = _check(conn, now=T0)
    row = log.get_task(conn, task_id)
    assert code == 0 and (row["status"], row["check_state"], row["result"]) == ("done", "unchecked", "fixed tagged list")
    assert "CHECK ROUND FAILED: grok (the re-check), timed out. The first check asked for fixes; this is the fixed result." in out
    assert "tagged list\n" not in out.replace("fixed tagged list", "")


def test_a_timed_out_first_call_still_ends_the_task_as_timed_out(conn):
    log.add_task(conn, "sr-t", TASK, "cli", WEB, now=T0 - timedelta(minutes=40))
    log.set_route(conn, "sr-t", agents=ALL_AGENTS, agent="grok", route_reason="interim", skill="web_research",
                  skill_source="jev", checker="claude", check_state="pending")
    log.set_sent(conn, "sr-t", "u", now=T0 - timedelta(minutes=31))
    code, out = _check(conn, now=T0)
    row = log.get_task(conn, "sr-t")
    assert code == 0 and (row["status"], row["result"], row["check_state"]) == ("timed_out", None, "pending")
    assert "sr-t timed out" in out and "CHECK" not in out


# ---------- sr check moves a task forward, one Grok call per run ----------

def test_sr_check_moves_a_task_forward_one_grok_call_per_run(conn):
    hook = Webhook(c1="FIX\n1. Post 7 is tagged wrong.", c2="PASS")
    code, out, row, worker, hook = _route(conn, BULK_TASK, BULK, worker=Scripted("tagged list"), hook=hook, wait=False)
    task_id = row["task_id"]
    assert code == 0 and row["status"] == "sent" and [p["task_id"] for p in hook.sent] == [f"{task_id}-c1"]
    # Run 1: collects the check (FIX), Claude fixes inside sr check, the re-check goes to Grok.
    code, out = _check(conn, worker=Scripted("fixed tagged list"), hook=hook)
    assert code == 0 and [p["task_id"] for p in hook.sent] == [f"{task_id}-c1", f"{task_id}-c2"]
    assert f"#{row['n']} {task_id} waits for {task_id}-c2 (recheck by grok)." in out and "1 task(s) still open" in out
    assert log.get_task(conn, task_id)["status"] == "sent"
    # Run 2: collects the re-check and ends the task.
    code, out = _check(conn, hook=hook)
    row = log.get_task(conn, task_id)
    assert code == 0 and (row["status"], row["check_state"], row["result"]) == ("done", "fixed", "fixed tagged list")
    assert "CHECKED: passed after one fix." in out and "0 task(s) still open" in out
    assert hook.closed == [1, 2]


def test_sr_check_with_an_unreadable_inbox_moves_nothing(conn):
    hook = Webhook(c1="PASS")
    _, _, row, _, _ = _route(conn, BULK_TASK, BULK, worker=Scripted("tagged list"), hook=hook, wait=False)

    def broken_fetch():
        raise cli.inbox.InboxError("gh issue list failed: HTTP 502")

    lines = []
    code = cli.cmd_check(conn=conn, config=CONFIG, environ={}, settings_paths=[], post=hook.post, worker=Scripted(),
                         fetch=broken_fetch, close=hook.close, out=lines.append)
    assert code == 1 and "502" in "\n".join(lines)
    assert log.get_task(conn, row["task_id"])["status"] == "sent" and hook.closed == []


# ---------- sr cancel mid-loop ----------

def test_cancel_mid_loop_cancels_the_task_and_a_late_issue_is_ignored(conn):
    hook = Webhook(c1="PASS")
    _, _, row, _, _ = _route(conn, BULK_TASK, BULK, worker=Scripted("tagged list"), hook=hook, wait=False)
    task_id = row["task_id"]
    lines = []
    assert cli.cmd_cancel(conn=conn, words=[str(row["n"])], out=lines.append) == 0
    assert log.get_task(conn, task_id)["status"] == "cancelled"
    assert "Grok may still" in "\n".join(lines), "a Grok check is out, even though Claude is the doer"
    code, out = _check(conn, hook=hook)  # the issue for the cancelled task is simply ignored
    assert code == 0 and "0 task(s) still open" in out and "PASS" not in out
    assert hook.closed == [] and log.get_task(conn, task_id)["status"] == "cancelled"
    assert log.get_call(conn, f"{task_id}-c1")["status"] == "sent", "the late issue changed nothing"


# ---------- main wires sr check like route ----------

def test_main_check_prepares_the_workspace_and_passes_the_real_pieces(monkeypatch):
    order, seen = [], {}
    monkeypatch.setattr(cli.safety, "prepare_workspace", lambda *a, **k: order.append("prepare"))
    monkeypatch.setattr(cli, "cmd_check", lambda **kw: order.append("check") or seen.update(kw) or 0)
    assert cli.main(["check"], platform="darwin") == 0
    assert order == ["prepare", "check"]
    assert seen["worker"] is cli.claude_worker.run and seen["post"] is cli.requests.post
    assert seen["fetch"] is cli.inbox.fetch_issues and seen["close"] is cli.inbox.close_issue
    assert seen["settings_paths"] == cli.CLAUDE_SETTINGS


def test_main_check_refuses_when_the_workspace_cannot_be_prepared(monkeypatch, capsys):
    def boom(*a, **k):
        raise cli.safety.SafeError("git init in workspace/ failed: no git")

    monkeypatch.setattr(cli.safety, "prepare_workspace", boom)
    monkeypatch.setattr(cli, "cmd_check", lambda **kw: pytest.fail("check must not run"))
    assert cli.main(["check"], platform="darwin") == 2
    assert "git init" in capsys.readouterr().out
