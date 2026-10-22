"""Claude worker tests. Every secret here is fake."""
import subprocess

import pytest

from router import claude_worker, safety

ENVIRON = {"HOME": "/h", "PATH": "/bin", "GROK_WEBHOOK_KEY": "FAKE-KEY-123", "ANTHROPIC_BASE_URL": "http://x"}


@pytest.fixture(autouse=True)
def tmp_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(claude_worker, "WORKSPACE", workspace)
    return workspace


def test_worker_runs_claude_safely(fake_run, tmp_workspace):
    run = fake_run(stdout="  five bullets \n")
    assert claude_worker.run("Explain venvs zebra-7781", run=run, environ=ENVIRON) == "five bullets"

    argv, kw = run.calls[0]
    assert argv == safety.claude_argv("sonnet")
    assert claude_worker.WORKER_MODEL == "sonnet"
    assert all("zebra-7781" not in a for a in argv), "task text must go on stdin"
    assert kw["input"] == "Explain venvs zebra-7781"
    assert kw["cwd"] == tmp_workspace and tmp_workspace.is_dir()
    assert kw["env"] == {"HOME": "/h", "PATH": "/bin"}
    assert kw["timeout"] == 600


def test_worker_task_starting_with_dash_stays_on_stdin(fake_run):
    run = fake_run(stdout="ok")
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
    with pytest.raises(claude_worker.WorkerError):
        claude_worker.run("hi", run=fake_run(stdout="  \n"), environ=ENVIRON)


def test_worker_error_is_a_safe_error():
    assert issubclass(claude_worker.WorkerError, safety.SafeError)
