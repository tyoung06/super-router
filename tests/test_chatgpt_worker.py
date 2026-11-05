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
        # brief 33.3: codex's own header, as `codex exec` prints it before the work (the model it was configured with)
        header = f"OpenAI Codex v0.162.1\n--------\nworkdir: /x\nmodel: {argv[argv.index('--model') + 1]}\nprovider: openai\n"
        return subprocess.CompletedProcess(argv, self.returncode, header, self.stderr)


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


# ---------- brief 33.3 (rules 2.48, Models): the choice, the effort flag, the time limit, the served record ----------

def test_without_a_choice_the_call_runs_on_the_pin_with_no_effort_and_keeps_the_header_model():
    from router import models
    run = CodexFake("the answer")
    answer = chatgpt_worker.run("hi", model=MODEL, web_search="disabled", run=run, environ=ENVIRON)
    argv, kw = run.calls[0]
    assert ("--model", MODEL) in _pairs(argv) and not any(v.startswith("model_reasoning_effort") for _, v in _pairs(argv))
    assert kw["timeout"] == 600
    assert answer == "the answer"
    assert answer.served["asked"] == MODEL and answer.served["model"] == MODEL and answer.served["source"] == "codex header"
    assert answer.served["credits"] == {"seen": False} and answer.served["differs"] is False and answer.served["file"] == models.AGENTS_NAME


def test_the_choice_sets_the_model_the_effort_as_codexs_config_key_and_the_time_limit():
    from router import models
    choice = models.Choice("chatgpt", "gpt-6-astra", effort="xhigh", timeout=900, layer="stage", key="redteam.2",
                           file="config/models.local.json")
    run = CodexFake("ok")
    answer = chatgpt_worker.run("hi", model=MODEL, web_search="live", run=run, environ=ENVIRON, choice=choice)
    argv, kw = run.calls[0]
    assert ("--model", "gpt-6-astra") in _pairs(argv) and ("-c", 'model_reasoning_effort="xhigh"') in _pairs(argv)
    assert kw["timeout"] == 900 and argv[-1] == "-"
    assert (answer.served["asked"], answer.served["model"], answer.served["effort"], answer.served["time_limit"],
            answer.served["layer"], answer.served["key"]) == ("gpt-6-astra", "gpt-6-astra", "xhigh", 900, "stage", "redteam.2")


def test_a_failed_call_keeps_its_served_record_and_a_timeout_names_its_own_limit():
    from router import models
    run = CodexFake(returncode=1, stderr="boom")
    with pytest.raises(chatgpt_worker.WorkerError) as err:
        chatgpt_worker.run("hi", model=MODEL, web_search="disabled", run=run, environ=ENVIRON)
    assert err.value.served["model"] == MODEL
    with pytest.raises(chatgpt_worker.WorkerError, match="timed out after 900 s"):
        chatgpt_worker.run("hi", model=MODEL, web_search="disabled", run=CodexFake(raises=subprocess.TimeoutExpired(["codex"], 900)),
                           environ=ENVIRON, choice=models.Choice("chatgpt", MODEL, timeout=900))


def test_a_header_with_no_model_line_reads_served_unknown():
    class Bare(CodexFake):
        def __call__(self, argv, **kwargs):
            proc = super().__call__(argv, **kwargs)
            return subprocess.CompletedProcess(argv, proc.returncode, "", proc.stderr)
    answer = chatgpt_worker.run("hi", model=MODEL, web_search="disabled", run=Bare("x"), environ=ENVIRON)
    assert answer.served["model"] is None and answer.served["source"] is None and answer.served["asked"] == MODEL


# ---------- Cleanup 1 (2.1): a failure names its cause, never the prompt's end ----------

CAPACITY = "ERROR: Selected model is at capacity. Please try a different model."
ECHOED = "Check the note on the seed trays.\n\nJudge it against what it says is done.\nThe doer read a copy of the files."


def _failure(stderr, prompt=ECHOED, code=1):
    with pytest.raises(chatgpt_worker.WorkerError) as err:
        chatgpt_worker.run(prompt, model=MODEL, web_search="disabled", run=CodexFake(returncode=code, stderr=stderr), environ=ENVIRON)
    return str(err.value)


def test_a_capacity_error_names_itself_once_and_holds_no_prompt_text():
    """The recorded shape (#159): Codex's stderr ends in the prompt, then the same ERROR line twice."""
    text = _failure(f"{ECHOED}\n{CAPACITY}\n{CAPACITY}\n")
    assert text == f"codex exited 1: {CAPACITY}"


def test_several_different_errors_are_all_named_in_order():
    assert _failure(f"reading things\nERROR: first\n{ECHOED}\nERROR: second\nERROR: first\n") == "codex exited 1: ERROR: first; ERROR: second"


def test_an_error_line_inside_the_prompt_is_the_prompts_and_never_the_cause():
    prompt = "Why does this print\nERROR: the seed tray is empty\nwhen I run it?"
    assert _failure(f"{prompt}\n{CAPACITY}\n", prompt=prompt) == f"codex exited 1: {CAPACITY}"


def test_no_error_line_keeps_todays_tail():
    stderr = "x" * 400 + "the end of it"
    assert _failure(stderr) == "codex exited 1: " + stderr[-300:]


def test_a_lower_case_or_mid_line_error_is_not_an_error_line():
    assert _failure("an ERROR: in a sentence\nerror: lower\n") == "codex exited 1: an ERROR: in a sentence\nerror: lower"


def test_the_cause_survives_to_the_tasks_note():
    """The row's text and the check's note, as `checking.next_step` reads a failed check."""
    from router import checking
    call = {"status": "failed", "text": f"codex exited 1: {CAPACITY}", "kind": "check"}
    assert CAPACITY in checking._why_not_run(call)
