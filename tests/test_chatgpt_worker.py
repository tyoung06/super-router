"""The ChatGPT worker: `codex exec` on the owner's ChatGPT plan, text only. Every value is fake;
no test runs codex."""
import subprocess
from pathlib import Path

import pytest

from router import chatgpt_worker, safety

ENVIRON = {"HOME": "/h", "PATH": "/bin", "USER": "t", "LANG": "C", "GROK_WEBHOOK_KEY": "FAKE-KEY-123",
           "ANTHROPIC_BASE_URL": "http://x"}
MODEL = "gpt-6.1-sol"


@pytest.fixture(autouse=True)
def tmp_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(chatgpt_worker, "WORKSPACE", workspace)
    monkeypatch.setattr(safety, "WORKSPACE", workspace)
    return workspace


class CodexFake:
    """Stands in for subprocess.run. Writes `answer` to the --output-last-message file, like codex."""

    def __init__(self, answer="an answer", returncode=0, stderr="", raises=None, write_file=True):
        self.answer, self.returncode, self.stderr, self.raises, self.write_file = answer, returncode, stderr, raises, write_file
        self.calls = []

    def __call__(self, argv, **kwargs):
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv)
        assert not kwargs.get("shell")
        self.calls.append((argv, kwargs))
        if self.raises:
            raise self.raises
        if self.write_file and "--output-last-message" in argv:
            Path(argv[argv.index("--output-last-message") + 1]).write_text(self.answer)
        return subprocess.CompletedProcess(argv, self.returncode, "", self.stderr)


def _pairs(argv):
    return [(argv[i], argv[i + 1]) for i in range(len(argv) - 1)]


# ---------- the argument list ----------

def test_worker_runs_codex_exec_with_the_prompt_on_stdin(tmp_workspace):
    run = CodexFake("  five bullets \n")
    assert chatgpt_worker.run("Explain venvs zebra-7781", model=MODEL, web_search="disabled", run=run, environ=ENVIRON) == "five bullets"
    argv, kw = run.calls[0]
    assert argv[:2] == ["codex", "exec"] and argv[-1] == "-"
    assert all("zebra-7781" not in a for a in argv), "task text must go on stdin"
    assert kw["input"] == "Explain venvs zebra-7781"
    assert kw["env"] == {"HOME": "/h", "PATH": "/bin", "USER": "t", "LANG": "C"}
    assert kw["cwd"] == tmp_workspace and tmp_workspace.is_dir()
    assert kw["timeout"] == 600 == chatgpt_worker.WORKER_TIMEOUT


def test_worker_flags_pin_the_model_sandbox_and_config(tmp_workspace):
    run = CodexFake()
    chatgpt_worker.run("hi", model=MODEL, web_search="live", run=run, environ=ENVIRON)
    argv = run.calls[0][0]
    pairs = _pairs(argv)
    assert ("--sandbox", "read-only") in pairs
    assert ("--model", MODEL) in pairs
    assert ("--cd", str(tmp_workspace)) in pairs
    assert ("--color", "never") in pairs
    for flag in ("--ephemeral", "--ignore-user-config", "--ignore-rules"):
        assert flag in argv, flag
    assert ("-c", 'approval_policy="never"') in pairs
    assert ("-c", 'web_search="live"') in pairs
    assert ("-c", "project_doc_max_bytes=0") in pairs
    assert any(flag == "--output-last-message" for flag, _ in pairs)


def test_worker_switches_off_every_codex_capability_beyond_text():
    run = CodexFake()
    chatgpt_worker.run("hi", model=MODEL, web_search="disabled", run=run, environ=ENVIRON)
    disabled = [value for flag, value in _pairs(run.calls[0][0]) if flag == "--disable"]
    for feature in ("shell_tool", "unified_exec", "unified_exec_tty", "view_image", "browser_use",
                    "browser_use_external", "browser_use_full_cdp_access", "in_app_browser", "computer_use", "apps",
                    "image_generation", "hooks", "plugins", "plugin_sharing", "remote_plugin", "skill_search",
                    "skill_mcp_dependency_install", "multi_agent", "worktrees", "goals", "sleep_tool",
                    "shell_snapshot", "tool_suggest", "workspace_dependencies"):
        assert feature in disabled, feature
    assert tuple(disabled) == safety.CODEX_DISABLED_FEATURES and len(disabled) == 24


def test_the_code_mode_host_stays_on_because_web_search_runs_through_it():
    # Codex 0.162.1 runs the web-search tool through the code-mode host (task #8, 2026-10-13). The host's
    # JavaScript reaches no file, command or network of its own (run 10); `sr probe` re-checks that.
    assert "code_mode_host" not in safety.CODEX_DISABLED_FEATURES
    disabled = [value for flag, value in _pairs(safety.codex_argv(MODEL, "live", Path("/tmp/x"))) if flag == "--disable"]
    assert "code_mode_host" not in disabled and len(disabled) == 24


def test_worker_never_uses_a_dangerous_flag_or_a_writing_sandbox():
    joined = " ".join(safety.codex_argv(MODEL, "disabled", Path("/tmp/x")))
    for bad in ("dangerously", "workspace-write", "danger-full-access", "--approve-for-me", "--add-dir", "--worktree"):
        assert bad not in joined, bad


@pytest.mark.parametrize("web_search", ["live", "disabled"])
def test_web_search_is_live_or_disabled_per_call(web_search):
    run = CodexFake()
    chatgpt_worker.run("hi", model=MODEL, web_search=web_search, run=run, environ=ENVIRON)
    assert ("-c", f'web_search="{web_search}"') in _pairs(run.calls[0][0])


def test_any_other_web_search_value_is_refused():
    run = CodexFake()
    with pytest.raises(ValueError):
        chatgpt_worker.run("hi", model=MODEL, web_search="cached", run=run, environ=ENVIRON)
    assert run.calls == []


def test_a_prompt_starting_with_a_dash_stays_on_stdin():
    run = CodexFake()
    chatgpt_worker.run("--help me write a note", model=MODEL, web_search="disabled", run=run, environ=ENVIRON)
    argv, kw = run.calls[0]
    assert "--help" not in argv and kw["input"] == "--help me write a note"


def test_the_model_must_be_a_pinned_name():
    run = CodexFake()
    for bad in (None, "", "   "):
        with pytest.raises(ValueError):
            chatgpt_worker.run("hi", model=bad, web_search="disabled", run=run, environ=ENVIRON)
    assert run.calls == []


# ---------- the answer file ----------

def test_the_answer_comes_from_the_output_file_which_is_then_removed():
    run = CodexFake("the answer")
    assert chatgpt_worker.run("hi", model=MODEL, web_search="disabled", run=run, environ=ENVIRON) == "the answer"
    argv = run.calls[0][0]
    out_file = Path(argv[argv.index("--output-last-message") + 1])
    assert not out_file.exists() and not out_file.parent.exists(), "the temp folder is gone"


@pytest.mark.parametrize("fake", [CodexFake("   \n"), CodexFake(write_file=False)])
def test_an_empty_or_missing_answer_file_is_a_failure(fake):
    with pytest.raises(chatgpt_worker.WorkerError, match="empty"):
        chatgpt_worker.run("hi", model=MODEL, web_search="disabled", run=fake, environ=ENVIRON)


def test_a_non_zero_exit_fails_with_the_last_300_chars_of_stderr():
    run = CodexFake(returncode=1, stderr="x" * 500 + " plan limit reached FAKE-KEY-123")
    with pytest.raises(chatgpt_worker.WorkerError) as err:
        chatgpt_worker.run("hi", model=MODEL, web_search="disabled", run=run, environ=ENVIRON)
    text = str(err.value)
    assert text.startswith("codex exited 1") and "plan limit reached" in text
    assert len(text) < 400, "only the tail of stderr"


def test_timeout_and_missing_codex_are_failures():
    with pytest.raises(chatgpt_worker.WorkerError, match="timed out"):
        chatgpt_worker.run("hi", model=MODEL, web_search="disabled",
                           run=CodexFake(raises=subprocess.TimeoutExpired(["codex"], 600)), environ=ENVIRON)
    with pytest.raises(chatgpt_worker.WorkerError, match="could not start"):
        chatgpt_worker.run("hi", model=MODEL, web_search="disabled",
                           run=CodexFake(raises=FileNotFoundError("codex")), environ=ENVIRON)


@pytest.mark.parametrize("switch", safety.BILLING_SWITCHES)
def test_worker_refuses_any_billing_switch(switch):
    run = CodexFake()
    with pytest.raises(chatgpt_worker.WorkerError) as err:
        chatgpt_worker.run("hi", model=MODEL, web_search="disabled", run=run, environ={**ENVIRON, switch: "FAKE-VALUE"})
    assert switch in str(err.value) and "FAKE-VALUE" not in str(err.value) and run.calls == []


def test_worker_error_is_a_safe_error():
    assert issubclass(chatgpt_worker.WorkerError, safety.SafeError)


# ---------- the login check ----------

def test_login_status_passes_only_on_a_chatgpt_login():
    assert chatgpt_worker.LOGIN_OK == "Logged in using ChatGPT"
    run = CodexFake()
    run.__call__ = None  # not used; a plain FakeRun below
    from tests.conftest import FakeRun
    good = FakeRun(stdout="Logged in using ChatGPT\n")
    assert chatgpt_worker.login_status(run=good) is True
    argv, kw = good.calls[0]
    assert argv == ["codex", "login", "status"]
    assert set(kw["env"]) == {"HOME", "PATH", "USER", "LANG"} - set() and kw["timeout"] == 60
    assert chatgpt_worker.login_status(run=FakeRun(stdout="Logged in using API key\n")) is False
    assert chatgpt_worker.login_status(run=FakeRun(stdout="Not logged in\n", returncode=1)) is False
    assert chatgpt_worker.login_status(run=FakeRun(stdout="Logged in using ChatGPT\n", returncode=1)) is False
    assert chatgpt_worker.login_status(run=FakeRun(raises=FileNotFoundError("codex"))) is False
    assert chatgpt_worker.login_status(run=FakeRun(raises=subprocess.TimeoutExpired(["codex"], 60))) is False


def test_login_status_sees_only_the_four_names(monkeypatch):
    from tests.conftest import FakeRun
    good = FakeRun(stdout="Logged in using ChatGPT")
    chatgpt_worker.login_status(run=good, environ={**ENVIRON, "OPENAI_API_KEY": "sk-FAKE"})
    assert "OPENAI_API_KEY" not in good.calls[0][1]["env"]
