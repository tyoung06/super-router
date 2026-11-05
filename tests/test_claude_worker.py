"""Claude worker tests. Every secret here is fake."""
import subprocess

import pytest

from router import claude_worker, models, safety
from tests.helpers import claude_stream

ENVIRON = {"HOME": "/h", "PATH": "/bin", "GROK_WEBHOOK_KEY": "FAKE-KEY-123", "ANTHROPIC_BASE_URL": "http://x"}


@pytest.fixture(autouse=True)
def tmp_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(claude_worker, "WORKSPACE", workspace)
    return workspace


def test_worker_runs_claude_safely(fake_run, tmp_workspace):
    run = fake_run(stdout=claude_stream("  five bullets \n"))  # brief 33.3: every call is stream-json
    answer = claude_worker.run("Explain venvs zebra-7781", run=run, environ=ENVIRON)
    assert answer == "five bullets" and answer.served["model"] == "claude-sonnet-5-5"

    argv, kw = run.calls[0]
    assert argv == safety.claude_argv("sonnet")
    assert claude_worker.WORKER_MODEL == "sonnet"
    assert all("zebra-7781" not in a for a in argv), "task text must go on stdin"
    assert kw["input"] == "Explain venvs zebra-7781"
    assert kw["cwd"] == tmp_workspace and tmp_workspace.is_dir()
    assert kw["env"] == {"HOME": "/h", "PATH": "/bin"}
    assert kw["timeout"] == 600


def test_worker_task_starting_with_dash_stays_on_stdin(fake_run):
    run = fake_run(stdout=claude_stream("ok"))
    claude_worker.run("--help me write a note", run=run, environ=ENVIRON)
    argv, kw = run.calls[0]
    assert "--help" not in argv
    assert kw["input"] == "--help me write a note"


@pytest.mark.parametrize("switch", safety.BILLING_SWITCHES)
def test_worker_refuses_any_billing_switch(fake_run, switch):
    run = fake_run(stdout="never")
    with pytest.raises(claude_worker.WorkerError) as err:
        claude_worker.run("hi", run=run, environ={**ENVIRON, switch: "FAKE-VALUE"})
    assert switch in str(err.value) and "FAKE-VALUE" not in str(err.value)
    assert run.calls == []


def test_worker_nonzero_exit_raises(fake_run):
    run = fake_run(returncode=1, stderr="not logged in\n")
    with pytest.raises(claude_worker.WorkerError) as err:
        claude_worker.run("hi", run=run, environ=ENVIRON)
    assert "exited 1" in str(err.value) and "not logged in" in str(err.value)


def test_worker_timeout_raises(fake_run):
    run = fake_run(raises=subprocess.TimeoutExpired(["claude"], 600))
    with pytest.raises(claude_worker.WorkerError) as err:
        claude_worker.run("hi", run=run, environ=ENVIRON)
    assert "timed out" in str(err.value)


def test_worker_missing_claude_raises(fake_run):
    run = fake_run(raises=FileNotFoundError("claude"))
    with pytest.raises(claude_worker.WorkerError):
        claude_worker.run("hi", run=run, environ=ENVIRON)


def test_worker_empty_answer_raises(fake_run):
    with pytest.raises(claude_worker.WorkerError, match="empty"):
        claude_worker.run("hi", run=fake_run(stdout=claude_stream("  \n")), environ=ENVIRON)
    with pytest.raises(claude_worker.WorkerError, match="no result event"):  # brief 33.3: text that is no stream
        claude_worker.run("hi", run=fake_run(stdout="  \n"), environ=ENVIRON)


# ---------- brief 33.3 (rules 2.48, Models): the choice, the served record, the credits check ----------

def test_a_plain_call_is_stream_json_on_the_agent_default_with_its_served_record(fake_run, tmp_workspace):
    run = fake_run(stdout=claude_stream("ok", model="claude-sonnet-5-5"))
    answer = claude_worker.run("hi", run=run, environ=ENVIRON)
    argv, kw = run.calls[0]
    assert argv[argv.index("--model") + 1] == "sonnet" and "--effort" not in argv
    assert argv[-3:] == ["--output-format", "stream-json", "--verbose"] and kw["timeout"] == 600
    assert answer.served["asked"] == "sonnet" and answer.served["model"] == "claude-sonnet-5-5"
    assert answer.served["layer"] == "agent" and answer.served["credits"] == {"seen": False}
    assert answer.served["differs"] is False  # the alias's own model


def test_the_choice_sets_the_model_the_effort_and_the_time_limit(fake_run, tmp_workspace):
    choice = models.Choice("claude", "claude-opus-5-5", effort="high", timeout=1200, layer="skill", key="code",
                           file="config/models.local.json", name="Opus 5.5")
    run = fake_run(stdout=claude_stream("ok", model="claude-opus-5-5", effort="high"))
    answer = claude_worker.run("hi", run=run, environ=ENVIRON, choice=choice)
    argv, kw = run.calls[0]
    assert argv == safety.claude_argv("claude-opus-5-5", effort="high") and argv[argv.index("--effort") + 1] == "high"
    assert kw["timeout"] == 1200
    assert answer.served == {"asked": "claude-opus-5-5", "model": "claude-opus-5-5", "init_model": "claude-opus-5-5",
                             "models_used": ["claude-opus-5-5"], "source": "stream: init and modelUsage", "effort": "high",
                             "effort_served": "high", "time_limit": 1200, "layer": "skill", "key": "code",
                             "file": "config/models.local.json", "note": None, "credits": {"seen": False}, "differs": False}


def test_a_served_model_that_differs_is_kept_never_a_failure(fake_run, tmp_workspace):
    choice = models.Choice("claude", "claude-fable-5-1", timeout=1200, layer="task", file="the task")
    run = fake_run(stdout=claude_stream("ok", model="claude-fable-5-1", used=["claude-fable-5-1", "claude-opus-4-8"]))
    answer = claude_worker.run("hi", run=run, environ=ENVIRON, choice=choice)
    assert answer == "ok" and answer.served["model"] == "claude-opus-4-8" and answer.served["differs"] is True


def test_a_stream_that_marks_the_call_billed_to_usage_credits_fails_it_with_the_code(fake_run, tmp_workspace):
    rate = {"status": "rejected", "overageStatus": "allowed", "isUsingOverage": True}
    run = fake_run(stdout=claude_stream("ok", rate=rate))
    with pytest.raises(claude_worker.WorkerError) as err:
        claude_worker.run("hi", run=run, environ=ENVIRON)
    assert err.value.code == "credits" and "usage credits" in str(err.value)
    assert err.value.served["credits"]["billed"] is True and err.value.served["credits"]["seen"] is True
    # a search call and a file-mode call read the same stream the same way
    with pytest.raises(claude_worker.WorkerError) as err:
        claude_worker.run("hi", run=fake_run(stdout=claude_stream("ok", tools=["WebSearch"], rate=rate)), environ=ENVIRON,
                          search=True)
    assert err.value.code == "credits"


def test_a_rate_limit_event_that_bills_nothing_is_kept_and_the_call_goes_on(fake_run, tmp_workspace):
    rate = {"status": "rejected", "errorCode": "credits_required", "canUserPurchaseCredits": True}
    answer = claude_worker.run("hi", run=fake_run(stdout=claude_stream("ok", rate=rate)), environ=ENVIRON)
    assert answer.served["credits"] == {"seen": True, "billed": False, "events": [{"status": "rejected", "errorCode": "credits_required"}]}


def test_a_timeout_names_the_calls_own_limit(fake_run):
    run = fake_run(raises=subprocess.TimeoutExpired(["claude"], 1200))
    with pytest.raises(claude_worker.WorkerError, match="timed out after 1200 s"):
        claude_worker.run("hi", run=run, environ=ENVIRON, choice=models.Choice("claude", "claude-opus-5-5", timeout=1200))


def test_worker_error_is_a_safe_error():
    assert issubclass(claude_worker.WorkerError, safety.SafeError)
