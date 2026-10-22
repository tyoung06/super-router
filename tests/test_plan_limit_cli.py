"""Phase A of build brief 7 (resume), through the commands: a plan-limit stop stores `plan_limit`
on its call row for both workers (any other failure stores no code), a failed first call now
leaves a call row, and the injected limit is refused on the real log. Every secret here is fake."""
import os

import pytest

from router import __main__ as cli
from router import chatgpt_worker, claude_worker, log, plan_limit
from tests.helpers import fake_label
from tests.test_loop import Clock, Scripted
from tests.test_relay import CONFIG, GOOD_NOTE, LOADED, ROSTER, TASK, Chat, RelayHook

QUICK = {"status": "ok", "label": "quick_answer", "confidence": 0.95, "needs_split": 0.1, "tokens": 0}
WRITING = {"status": "ok", "label": "writing", "confidence": 0.95, "needs_split": 0.1, "tokens": 0}
CLAUDE_LIMIT = claude_worker.WorkerError("plan limit on claude: You've hit your session limit · resets 3pm",
                                         code="plan_limit")
CODEX_LIMIT = chatgpt_worker.WorkerError("plan limit on chatgpt: You've hit your usage limit. Try again at 3 PM.",
                                         code="plan_limit")


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _route(conn, jev, *, worker, chatgpt=None, task="write two lines about trays"):
    lines, clock = [], Clock()
    code = cli.cmd_route(task, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=fake_label(jev), post=None, worker=worker, chatgpt=chatgpt or Chat("PASS"),
                         codex_login=lambda: True, sleep=clock.sleep, clock=clock, wait=False, out=lines.append)
    row = log.recent_tasks(conn)[0]
    return code, "\n".join(lines), row, log.calls_for(conn, row["task_id"])


def test_a_plan_limit_on_the_first_call_leaves_a_failed_do_row_with_the_code(conn):
    code, out, row, calls = _route(conn, QUICK, worker=Scripted(CLAUDE_LIMIT))
    assert code == 1 and row["status"] == "failed"
    assert [(c["call_id"], c["kind"], c["agent"], c["status"], c["reason_code"]) for c in calls] == [
        (row["task_id"], "do", "claude", "failed", "plan_limit")]
    assert "You've hit your session limit" in calls[0]["text"] and calls[0]["text"] == row["result"]


def test_any_other_first_call_failure_leaves_a_failed_do_row_with_no_code(conn):
    code, out, row, calls = _route(conn, QUICK, worker=Scripted(claude_worker.WorkerError("claude exited 1: boom")))
    assert code == 1 and row["status"] == "failed"
    assert [(c["kind"], c["status"], c["reason_code"]) for c in calls] == [("do", "failed", None)]


def test_a_plan_limit_on_the_check_round_stores_the_code_on_the_check_row(conn):
    code, out, row, calls = _route(conn, WRITING, worker=Scripted("two lines"), chatgpt=Chat(CODEX_LIMIT))
    assert (row["status"], row["check_state"]) == ("done", "unchecked")
    assert [(c["kind"], c["agent"], c["status"], c["reason_code"]) for c in calls] == [
        ("do", "claude", "done", None), ("check", "chatgpt", "failed", "plan_limit")]


def test_a_plan_limit_on_a_relay_stage_stores_the_code_on_the_stage_row(conn):
    lines, clock, hook = [], Clock(), RelayHook(s1=GOOD_NOTE)
    code = cli.cmd_relay("research-build", TASK, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                         settings_paths=[], post=hook.post, worker=Scripted(CLAUDE_LIMIT), chatgpt=Chat("PASS"),
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=True, out=lines.append)
    row = log.recent_tasks(conn)[0]
    calls = log.calls_for(conn, row["task_id"])
    assert code == 1 and (row["status"], row["failed_stage"]) == ("failed", 2)
    assert [(c["kind"], c["stage"], c["agent"], c["status"], c["reason_code"]) for c in calls] == [
        ("stage", 1, "grok", "done", None), ("stage", 2, "claude", "failed", "plan_limit")]


# ---------- the injected limit through `main` ----------

def test_main_refuses_the_injected_limit_on_the_real_log(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(plan_limit.ENV_NAME, "claude")
    monkeypatch.setattr(plan_limit, "main_checkout", lambda root, run=None: cli.DB_PATH.parent)
    assert cli.main(["log"], platform="darwin") == 2
    out = capsys.readouterr().out
    assert "Refused:" in out and "test-only" in out and "Nothing was logged or sent." in out
    assert not cli.DB_PATH.exists(), "nothing ran: the log was never opened"


def test_main_refuses_the_injected_limit_when_git_cannot_tell(monkeypatch, capsys):
    monkeypatch.setenv(plan_limit.ENV_NAME, "chatgpt")
    monkeypatch.setattr(plan_limit, "main_checkout", lambda root, run=None: None)
    assert cli.main(["log"], platform="darwin") == 2
    assert "test-only" in capsys.readouterr().out


def test_main_names_the_hook_on_a_scratch_log(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(plan_limit.ENV_NAME, "claude")
    monkeypatch.setattr(plan_limit, "main_checkout", lambda root, run=None: tmp_path / "elsewhere")
    assert cli.main(["log"], platform="darwin") == 0
    assert "Test hook: the next claude call stops on an injected plan limit" in capsys.readouterr().out


def test_main_wraps_only_the_named_agents_worker(monkeypatch, tmp_path):
    monkeypatch.setattr(plan_limit, "main_checkout", lambda root, run=None: tmp_path / "elsewhere")
    claude, chatgpt, _ = cli._workers({plan_limit.ENV_NAME: "chatgpt"}, model="m")  # brief 20: a third, the Cursor worker
    assert claude is claude_worker.run
    assert chatgpt.func is chatgpt_worker.run and chatgpt.keywords["model"] == "m" and "run" in chatgpt.keywords
    claude, chatgpt, _ = cli._workers({}, model="m")
    assert claude is claude_worker.run and "run" not in chatgpt.keywords
    assert cli._workers({}, model=None)[1] is None


def test_without_the_variable_nothing_changes(monkeypatch, capsys):
    monkeypatch.delenv(plan_limit.ENV_NAME, raising=False)
    assert cli.main(["log"], platform="darwin") == 0
    assert "Test hook" not in capsys.readouterr().out
