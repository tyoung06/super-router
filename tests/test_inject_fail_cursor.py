"""Build brief 32 (D's step 4): the test-only hook SR_INJECT_FAIL=cursor. Cursor's next `agent -p` ends as a failed
call (exit 1, nothing on stdout, one line on stderr) at the worker's process boundary, so the worker's own reading fails
it and the chain skips the second attack; every later call goes through. Like SR_INJECT_PLAN_LIMIT it works only on a
scratch log and is refused on the real one before anything runs. Fakes only; every value here is fake."""
import functools
import subprocess

import pytest

from router import __main__ as cli
from router import chatgpt_worker, claude_worker, cursor_worker, log, plan_limit, relay
from tests.test_cursor_send import Ready
from tests.test_cursor_worker import ENVIRON, MODEL, PROMPT, stream
from tests.test_plan_limit import Git
from tests.test_redteam2_chain import A_LIST, BUILD, REVISION_A, TASK
from tests.test_redteam2_presets import _loaded
from tests.test_relay import CONFIG, Chat, Clock, RelayHook, Scripted
from tests.helpers import shipped_roster


class Runner:
    """A fake `agent -p` that answers a good stream, counting its calls."""

    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stream(texts=("an answer",), result="an answer"), "")


@pytest.fixture(autouse=True)
def _scratch_in_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(cursor_worker, "temp_root", lambda: tmp_path)


def _hook(tmp_path):
    return plan_limit.failing("cursor", tmp_path / "scratch.db", root=tmp_path, run=Git(tmp_path / "main" / ".git"))


def test_the_injected_failure_is_refused_on_the_real_log(tmp_path):
    main = tmp_path / "super-router"
    with pytest.raises(plan_limit.InjectRefused, match="test-only.*scratch log"):
        plan_limit.failing("cursor", main / "router.db", root=main, run=Git(main / ".git"))


@pytest.mark.parametrize("agent", ["claude", "chatgpt", "grok", ""])
def test_it_names_cursor_only(tmp_path, agent):
    with pytest.raises(plan_limit.InjectRefused, match="names cursor"):
        plan_limit.failing(agent, tmp_path / "scratch.db", root=tmp_path, run=Git(tmp_path / "main" / ".git"))


def test_it_fails_one_cursor_call_through_the_real_worker_then_lets_calls_through(tmp_path):
    real = Runner()
    run = _hook(tmp_path)(real)
    with pytest.raises(cursor_worker.WorkerError) as err:
        cursor_worker.run(PROMPT, model=MODEL, run=run, environ=ENVIRON)
    assert str(err.value) == "agent exited 1: an injected failure for a test (SR_INJECT_FAIL=cursor)"
    assert real.calls == [] and not plan_limit.cursor_pool(str(err.value))  # never read as the weekly pool
    assert cursor_worker.run(PROMPT, model=MODEL, run=run, environ=ENVIRON) == "an answer"
    assert len(real.calls) == 1


def test_main_wraps_only_cursors_worker(monkeypatch, tmp_path):
    monkeypatch.setattr(plan_limit, "main_checkout", lambda root, run=None: tmp_path / "elsewhere")
    claude, chatgpt, cursor = cli._workers({plan_limit.FAIL_ENV: "cursor"}, "m", "grok-4.7-high")
    assert claude is claude_worker.run and chatgpt.func is chatgpt_worker.run and "run" not in chatgpt.keywords
    assert cursor.func is cursor_worker.run and cursor.keywords["model"] == "grok-4.7-high" and "run" in cursor.keywords
    assert "run" not in cli._workers({}, "m", "grok-4.7-high")[2].keywords


def test_main_refuses_it_on_the_real_log_before_anything_runs(monkeypatch, capsys):
    monkeypatch.setenv(plan_limit.FAIL_ENV, "cursor")
    monkeypatch.setattr(plan_limit, "main_checkout", lambda root, run=None: cli.DB_PATH.parent)
    assert cli.main(["log"], platform="darwin") == 2
    out = capsys.readouterr().out
    assert "Refused: SR_INJECT_FAIL is test-only" in out and "Nothing was logged or sent." in out
    assert not cli.DB_PATH.exists(), "nothing ran: the log was never opened"


def test_main_names_the_hook_on_a_scratch_log(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(plan_limit.FAIL_ENV, "cursor")
    monkeypatch.setattr(plan_limit, "main_checkout", lambda root, run=None: tmp_path / "elsewhere")
    assert cli.main(["log"], platform="darwin") == 0
    assert "Test hook: the next cursor call fails (an injected failure; scratch log " in capsys.readouterr().out


def test_through_the_chain_the_second_attack_is_skipped_with_its_reason_and_never_taken_over(tmp_path):
    conn = log.init_db(":memory:")
    real = Runner()
    cursor = functools.partial(cursor_worker.run, model=MODEL, run=_hook(tmp_path)(real), environ=ENVIRON)
    hook, clock, lines = RelayHook(), Clock(), []
    code = cli.cmd_relay("redteam", TASK, conn=conn, config=CONFIG, roster=shipped_roster(), loaded=_loaded(), environ={},
                         settings_paths=[], post=hook.post, worker=Scripted(BUILD, REVISION_A), chatgpt=Chat(A_LIST, "PASS"),
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=True, cursor=cursor, cursor_ready=Ready(), out=lines.append)
    row = log.recent_tasks(conn)[0]
    calls = log.calls_for(conn, row["task_id"])
    assert code == 0, "\n".join(lines)
    assert [(c["kind"], c["stage"], c["agent"], c["status"], c["reason_code"]) for c in calls] == [
        ("stage", 1, "claude", "done", None), ("stage", 2, "chatgpt", "done", None),
        ("stage", 3, "cursor", "failed", "skipped"), ("stage", 4, "claude", "done", None), ("check", None, "chatgpt", "done", None)]
    assert real.calls == [] and not any("takeover" in c["call_id"] for c in calls)  # no takeover row
    assert relay.attack_lists(row, calls)[1].why.endswith("an injected failure for a test (SR_INJECT_FAIL=cursor)")
    conn.close()
