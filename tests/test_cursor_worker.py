"""Build brief 20, phase A (rules v2.28, Cursor): the Cursor worker. `agent -p` on the owner's X Subscription, one Grok
model pinned by name, every tool denied, text in and text out. The argument list, the scratch folder and its deny
file, the five-name environment, the stream parser, the served-model match, the login and version gates, and every
way a call fails. The three real streams from the Phase 0 probes (agent 2026.10.16-e3cb207, 2026-10-19) are the
fixtures in tests/fixtures/cursor/. No test runs the real `agent`; the fake on PATH is a Python script this file
writes. Every value here is fake."""
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from router import __main__ as cli
from router import checking, cursor_worker, safety, search

REAL_POPEN = subprocess.Popen  # captured at import, before conftest's per-test guard replaces it
FIXTURES = Path(__file__).parent / "fixtures" / "cursor"
PIN = (FIXTURES / "pin.ndjson").read_text()
CANARY_A = (FIXTURES / "canary-a.ndjson").read_text()
CANARY_B = (FIXTURES / "canary-b.ndjson").read_text()
TRUST_GATE = (FIXTURES / "trust-gate.stderr.txt").read_text()
MODEL = "grok-4.7-high"
SERVED = "Grok 4.7 256K High"
ENVIRON = {"HOME": "/h", "PATH": "/bin", "USER": "t", "LANG": "C", "TMPDIR": "/tmp/t",
           "JEV_API_KEY": "FAKE-JEV", "GROK_WEBHOOK_URL": "https://example.invalid/hook", "GROK_WEBHOOK_KEY": "FAKE-KEY",
           "CURSOR_API_ENDPOINT": "https://example.invalid", "OPENAI_BASE_URL": "http://x"}
FIVE = {"HOME": "/h", "PATH": "/bin", "USER": "t", "LANG": "C", "TMPDIR": "/tmp/t"}
# What a child process on a Mac sees besides what it was handed: CoreFoundation adds __CF_USER_TEXT_ENCODING to every
# process, and Python's locale coercion (PEP 538) exports LC_CTYPE under LANG=C. Neither comes from the router.
RUNTIME_ADDED = {"__CF_USER_TEXT_ENCODING", "LC_CTYPE"}
PROMPT = cursor_worker.wrap("Reply with the single word ok.")


def event(**fields):
    return json.dumps(fields)


def stream(*, model=SERVED, texts=("ok",), result="ok", is_error=False, tools=(), terminal=True, init=True,
           permission_mode="default"):
    """A stream like the real one: init, user, assistant blocks, tool events, the terminal result."""
    lines = []
    if init:
        lines.append(event(type="system", subtype="init", apiKeySource="login", cwd="/w/cursor/x", session_id="s",
                           model=model, permissionMode=permission_mode))
    lines.append(event(type="user", message={"role": "user", "content": [{"type": "text", "text": "p"}]}))
    lines.append(event(type="thinking", subtype="delta", text="hm"))  # not in the docs; ignored
    for tool in tools:
        lines.append(event(type="tool_call", **tool))
    for text in texts:
        lines.append(event(type="assistant", message={"role": "assistant", "content": [{"type": "text", "text": text}]}))
    if terminal:
        lines.append(event(type="result", subtype="success", duration_ms=1234, duration_api_ms=1234, is_error=is_error,
                           result=result, session_id="s", request_id="r",
                           usage={"inputTokens": 10, "outputTokens": 2, "cacheReadTokens": 0, "cacheWriteTokens": 0}))
    return "\n".join(lines) + "\n"


def tool(kind, subtype, result=None, args=None):
    body = {"args": args or {"path": "/x"}}
    if result is not None:
        body["result"] = result
    return {"subtype": subtype, "call_id": "c", "tool_call": {kind: body, "toolCallId": "c"}}


DENIED_READ = {"error": {"errorMessage": "Permission denied"}}
DENIED_SHELL = {"permissionDenied": {"command": "ls ..", "error": "Command blocked by permissions configuration"}}


def glob_result(n):
    return {"success": {"pattern": "", "path": "/w", "files": ["f"] * n, "totalFiles": n}}


class AgentFake:
    """Stands in for subprocess.run for `agent -p`, `agent status` and `agent --version`. Records every call and
    checks the subprocess rules. `during` is called with the working folder while the call is "running"."""

    def __init__(self, stdout=None, returncode=0, stderr="", raises=None, status="✓ Logged in as t@example.com",
                 status_code=0, version="2026.10.16-e3cb207\n", during=None):
        self.stdout = PIN if stdout is None else stdout
        self.returncode, self.stderr, self.raises = returncode, stderr, raises
        self.status, self.status_code, self.version, self.during = status, status_code, version, during
        self.calls = []

    def __call__(self, argv, **kwargs):
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv), "an argument list of strings"
        assert not kwargs.get("shell")
        self.calls.append((argv, kwargs))
        if self.raises:
            raise self.raises
        if argv[:2] == ["agent", "status"]:
            return subprocess.CompletedProcess(argv, self.status_code, self.status + "\n", "")
        if argv[:2] == ["agent", "--version"]:
            return subprocess.CompletedProcess(argv, 0, self.version, "")
        if self.during is not None:
            self.during(Path(kwargs["cwd"]))
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)

    @property
    def prompt_calls(self):
        return [(a, k) for a, k in self.calls if a[:2] == ["agent", "-p"]]


@pytest.fixture(autouse=True)
def tmp_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(cursor_worker, "WORKSPACE", workspace)
    monkeypatch.setattr(safety, "WORKSPACE", workspace)
    return workspace


def _run(fake, prompt=PROMPT, model=MODEL, environ=ENVIRON, call_id="sr-x-s2", **kw):
    return cursor_worker.run(prompt, model=model, run=fake, environ=environ, call_id=call_id, **kw)


# ---------- the argument list (decision 2, amendment 2, the owner's change 12) ----------

def test_the_argv_is_flags_first_the_model_pinned_and_the_prompt_last():
    argv = cursor_worker.argv(MODEL, Path("/w/cursor/sr-x-s2"), "P zebra")
    assert argv == ["agent", "-p", "--model", MODEL, "--output-format", "stream-json", "--mode", "ask",
                    "--sandbox", "enabled", "--workspace", "/w/cursor/sr-x-s2", "--trust", "P zebra"]
    joined = " ".join(argv[:-1])
    for never in ("--force", "--yolo", "-f ", "--resume", "--continue", "--background", "--api-key", "-a ", "--add-dir",
                  "--worktree", "--approve-mcps", "--auto-review", "--plugin-dir", "--list-models"):
        assert never not in joined + " ", never


def test_the_deny_file_is_the_json_the_probes_ran_with():
    assert cursor_worker.DENY == {"permissions": {"allow": [], "deny": ["Shell(*)", "Read(**)", "Write(**)", "Read(/**)",
                                                                         "Write(/**)"]}}
    assert cursor_worker.deny_text() == json.dumps(cursor_worker.DENY, indent=2) + "\n"


def test_every_prompt_opens_with_the_scope_paragraph_and_the_no_tools_sentence():
    # Decision 8 and choice 5: the opener, then Claude's prompt for the role, byte for byte.
    assert cursor_worker.wrap("the task\n\nmore") == (checking.SCOPE_PARAGRAPH + " " + cursor_worker.NO_TOOLS_SENTENCE
                                                       + "\n\nthe task\n\nmore")
    assert cursor_worker.NO_TOOLS_SENTENCE == ("You have no tools in this session: do not try to read, write, run or "
                                               "search anything, and put everything you produce in your reply as text.")
    assert cursor_worker.opener().split()[0] == "This" and "This" not in cursor_worker.SUBCOMMANDS


@pytest.mark.parametrize("word", cursor_worker.SUBCOMMANDS + ("-p", "--help"))
def test_a_prompt_whose_first_word_is_a_subcommand_or_a_flag_is_refused_before_any_call(word):
    fake = AgentFake()
    with pytest.raises(cursor_worker.WorkerError, match="must open with the scope paragraph"):
        _run(fake, prompt=f"{word} the README now")
    assert fake.calls == []
    assert cursor_worker.first_token_problem(f"{word} x") is not None
    assert cursor_worker.first_token_problem(PROMPT) is None


def test_the_subcommand_list_is_the_one_agent_help_printed_on_2026_10_16():
    assert set(cursor_worker.SUBCOMMANDS) == {"persist", "install-shell-integration", "uninstall-shell-integration", "login",
                                              "logout", "mcp", "plugin", "worker", "status", "whoami", "models", "team",
                                              "bedrock", "about", "update", "create-chat", "generate-rule", "rule", "agent",
                                              "ls", "resume", "help"}


# ---------- a good run (decision 4; the real pin-probe stream) ----------

def test_a_good_stream_gives_the_text_the_served_model_and_no_tool_events():
    fake = AgentFake()
    answer = _run(fake)
    assert answer == "ok" and isinstance(answer, str)
    assert answer.served == {"model": SERVED, "asked": MODEL, "tool_events": 0, "tools": [], "duration_ms": 21888,
                             "permission_mode": "default",
                             "usage": {"inputTokens": 14183, "outputTokens": 78, "cacheReadTokens": 6272, "cacheWriteTokens": 0}}
    argv, kw = fake.prompt_calls[0]
    assert argv[-1] == PROMPT and argv[:3] == ["agent", "-p", "--model"] and argv[3] == MODEL
    assert kw["timeout"] == 600 == cursor_worker.WORKER_TIMEOUT
    assert kw["stdin"] == subprocess.DEVNULL and kw["capture_output"] and kw["text"]


def test_the_call_runs_from_a_fresh_scratch_folder_holding_only_the_deny_file(tmp_workspace):
    seen = {}

    def during(cwd):
        seen["cwd"] = cwd
        seen["files"] = sorted(str(p.relative_to(cwd)) for p in cwd.rglob("*"))
        seen["deny"] = (cwd / ".cursor" / "cli.json").read_text()
    fake = AgentFake(during=during)
    _run(fake, call_id="sr-20261019-010203-ab12-s2")
    argv, kw = fake.prompt_calls[0]
    assert seen["cwd"] == tmp_workspace / "cursor" / "sr-20261019-010203-ab12-s2" == Path(kw["cwd"])
    assert argv[argv.index("--workspace") + 1] == str(seen["cwd"])
    assert seen["files"] == [".cursor", ".cursor/cli.json"]
    assert seen["deny"] == cursor_worker.deny_text()
    assert not seen["cwd"].exists(), "the scratch folder is removed after the call"
    assert not (tmp_workspace / "cursor").exists(), "and workspace/cursor/ with it when empty"


@pytest.mark.parametrize("case", ["failure", "exception", "wrong-model"])
def test_the_scratch_folder_is_gone_after_a_failure_an_exception_and_a_mismatch(tmp_workspace, case):
    fake = {"failure": AgentFake(returncode=1, stderr="boom"), "exception": AgentFake(raises=OSError("no agent")),
            "wrong-model": AgentFake(stdout=stream(model="Composer 2.5"))}[case]
    with pytest.raises(cursor_worker.WorkerError):
        _run(fake)
    assert not (tmp_workspace / "cursor").exists()
    assert sorted(p.name for p in tmp_workspace.iterdir()) == [], "workspace/ is empty after the call"


def test_the_environment_is_the_five_names_and_nothing_else():
    fake = AgentFake()
    _run(fake)
    assert fake.prompt_calls[0][1]["env"] == FIVE
    assert safety.cursor_env(ENVIRON) == FIVE and safety.CURSOR_ENV_KEYS == ("HOME", "PATH", "USER", "LANG", "TMPDIR")
    assert safety.cursor_env({"HOME": "/h"}) == {"HOME": "/h"}  # a missing name is left out, never invented


# ---------- the real process: a fake `agent` first on PATH (the brief's section 4) ----------

@pytest.fixture
def fake_agent(tmp_path, monkeypatch):
    """A Python script named `agent` first on PATH. It records what it was given (argv, cwd, its environment) in
    seen.json and answers from case.json; the test writes the case. The subprocess guard is lifted for this test only."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "agent"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys, time\n"
        "from pathlib import Path\n"
        "here = Path(__file__).resolve().parent\n"
        "case = json.loads((here / 'case.json').read_text()) if (here / 'case.json').exists() else {}\n"
        "(here / 'seen.json').write_text(json.dumps({'argv': sys.argv, 'cwd': os.getcwd(), 'env': dict(os.environ)}))\n"
        "if sys.argv[1:2] == ['status']:\n"
        "    print(case.get('status', 'Logged in as t@example.com')); sys.exit(case.get('status_code', 0))\n"
        "if sys.argv[1:2] == ['--version']:\n"
        "    print(case.get('version', '2026.10.16-e3cb207')); sys.exit(0)\n"
        "if case.get('sleep'):\n"
        "    time.sleep(case['sleep'])\n"
        "sys.stdout.write(case.get('stdout', '')); sys.stderr.write(case.get('stderr', '')); sys.exit(case.get('code', 0))\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(subprocess, "Popen", REAL_POPEN)

    class Fake:
        path = bin_dir
        environ = {"HOME": str(tmp_path), "PATH": f"{bin_dir}:/usr/bin:/bin", "USER": "t", "LANG": "C",
                   "TMPDIR": str(tmp_path), "JEV_API_KEY": "FAKE-JEV", "GROK_WEBHOOK_KEY": "FAKE-KEY",
                   "CURSOR_API_ENDPOINT": "https://example.invalid", "SOME_API_KEY": "x"}

        @staticmethod
        def case(**fields):
            (bin_dir / "case.json").write_text(json.dumps(fields))

        @staticmethod
        def seen():
            return json.loads((bin_dir / "seen.json").read_text())
    return Fake


def test_the_real_process_gets_the_argv_the_scratch_cwd_and_the_five_names_only(fake_agent, tmp_workspace):
    fake_agent.case(stdout=PIN)
    answer = cursor_worker.run(PROMPT, model=MODEL, run=subprocess.run, environ=fake_agent.environ, call_id="sr-x-s2")
    assert answer == "ok"
    seen = fake_agent.seen()
    scratch = tmp_workspace / "cursor" / "sr-x-s2"
    assert seen["argv"][1:] == cursor_worker.argv(MODEL, scratch, PROMPT)[1:]
    assert Path(seen["cwd"]).resolve() == scratch.resolve()
    assert set(seen["env"]) - RUNTIME_ADDED == {"HOME", "PATH", "USER", "LANG", "TMPDIR"}
    assert seen["env"]["HOME"] == fake_agent.environ["HOME"] and seen["env"]["TMPDIR"] == fake_agent.environ["TMPDIR"]
    assert not any(name.endswith("_API_KEY") or name.startswith("GROK_WEBHOOK") or name == "CURSOR_API_ENDPOINT"
                   for name in seen["env"])
    assert not scratch.exists() and not (tmp_workspace / "cursor").exists()


def test_a_slow_agent_times_out_and_the_scratch_folder_is_gone(fake_agent, tmp_workspace, monkeypatch):
    monkeypatch.setattr(cursor_worker, "WORKER_TIMEOUT", 1)
    fake_agent.case(sleep=5, stdout=PIN)
    with pytest.raises(cursor_worker.WorkerError, match="cursor timed out after 1 s"):
        cursor_worker.run(PROMPT, model=MODEL, run=subprocess.run, environ=fake_agent.environ, call_id="sr-x-s2")
    assert not (tmp_workspace / "cursor").exists()


def test_the_real_process_login_and_version_reads_make_no_model_call(fake_agent):
    fake_agent.case(status="Logged in as t@example.com", version="2026.10.16-e3cb207")
    assert cursor_worker.login_status(run=subprocess.run, environ=fake_agent.environ) is True
    assert fake_agent.seen()["argv"][1:] == ["status"]
    assert cursor_worker.installed_version(run=subprocess.run, environ=fake_agent.environ) == "2026.10.16-e3cb207"
    assert fake_agent.seen()["argv"][1:] == ["--version"]
    assert set(fake_agent.seen()["env"]) - RUNTIME_ADDED == {"HOME", "PATH", "USER", "LANG", "TMPDIR"}


# ---------- the served model (decision 5, choice 2, the owner's change 1) ----------

LISTED = [  # `agent --list-models` on 2026-10-19 (id, display name); the fast twins of Grok 4.7 end in zero-width characters
    ("grok-4.7-low", "Grok 4.7  Low"), ("grok-4.7-low-fast", "Grok 4.7  Low Fast​​"),
    ("grok-4.7-medium", "Grok 4.7  Medium"), ("grok-4.7-medium-fast", "Grok 4.7  Medium Fast​​"),
    ("grok-4.7-high", "Grok 4.7  High"), ("grok-4.7-high-fast", "Grok 4.7  High Fast​​"),
    ("grok-4.7-xhigh", "Grok 4.7  Extra High"), ("grok-4.7-xhigh-fast", "Grok 4.7  Extra High Fast​​"),
    ("cursor-grok-4.6-low", "Grok 4.6 Low"), ("cursor-grok-4.6-low-fast", "Grok 4.6 Low Fast"),
    ("cursor-grok-4.6-medium", "Grok 4.6 Medium"), ("cursor-grok-4.6-medium-fast", "Grok 4.6 Medium Fast"),
    ("cursor-grok-4.6-high", "Grok 4.6"), ("cursor-grok-4.6-high-fast", "Grok 4.6 Fast"),
    ("cursor-grok-4.6-xhigh", "Grok 4.6 Extra High"), ("cursor-grok-4.6-xhigh-fast", "Grok 4.6 Extra High Fast"),
    ("cursor-grok-4.5-high", "Grok 4.5"), ("cursor-grok-4.5-high-fast", "Grok 4.5 Fast"),
    ("grok-4.7-high", SERVED),  # what the init event really said for the pin
]


@pytest.mark.parametrize("asked, served", LISTED)
def test_every_listed_grok_id_matches_its_own_display_name(asked, served):
    assert cursor_worker.model_matches(asked, served), (asked, served)


@pytest.mark.parametrize("asked, served", [
    ("grok-4.7-high", "Grok 4.7 256K High​"),          # The owner's change 1: a format character means the fast twin
    ("grok-4.7-high", "Grok 4.7  High Fast​​"),
    ("grok-4.7-high-fast", "Grok 4.7 256K High"),           # a fast pin served at standard speed is not the one asked for
    ("grok-4.7-high", "Grok 4.6"), ("grok-4.7-high", "Grok 4.7  Medium"), ("grok-4.7-high", "Grok 4.7  Extra High"),
    ("grok-4.7-high", "Composer 2.5"), ("grok-4.7-high", "Claude Sonnet 5 1M Thinking"), ("grok-4.7-high", "Auto"),
    ("cursor-grok-4.6-high", "Grok 4.7  High"), ("grok-4.7-high", ""), ("grok-4.7-high", None),
])
def test_a_different_model_or_speed_never_matches(asked, served):
    assert not cursor_worker.model_matches(asked, served), (asked, served)


def test_the_owners_two_cases_for_the_format_character_rule():
    assert not cursor_worker.model_matches("grok-4.7-high", "Grok 4.7 256K High​")
    assert cursor_worker.model_matches("grok-4.7-high-fast", "Grok 4.7 256K High​")


def test_a_wrong_served_model_fails_the_call_before_its_text_is_used():
    fake = AgentFake(stdout=stream(model="Claude Sonnet 5 1M Thinking", texts=("a third-party answer",)))
    with pytest.raises(cursor_worker.WorkerError) as info:
        _run(fake)
    assert "served model 'Claude Sonnet 5 1M Thinking' is not the one asked for (grok-4.7-high)" in str(info.value)
    assert "a third-party answer" not in str(info.value)
    assert info.value.served["model"] == "Claude Sonnet 5 1M Thinking" and info.value.served["asked"] == MODEL


# ---------- the stream: tool events, the text, every failure (decision 4; choice 10 with the owner's change 2; change 4) ----------

def test_the_canary_streams_are_counted_and_kept_and_the_text_still_comes_back():
    answer = _run(AgentFake(stdout=CANARY_A))
    assert answer.served["tool_events"] == 6
    assert answer.served["tools"] == ["readToolCall:started", "readToolCall:completed:error", "shellToolCall:started",
                                      "shellToolCall:completed:denied", "globToolCall:started",
                                      "globToolCall:completed:success (0 files)"]
    assert answer == ("I'll read `../canary.txt` and reply with its exact contents.\nI couldn't read `../canary.txt`. "
                      "The read was denied, so I don't have its contents and can't quote them.")
    b = _run(AgentFake(stdout=CANARY_B))
    assert b.served["tool_events"] == 8 and b.served["tools"].count("globToolCall:completed:success (0 files)") == 3
    assert b.served["tools"][1] == "shellToolCall:completed:denied" and b.served["duration_ms"] == 148910


@pytest.mark.parametrize("kind, result, reason", [
    ("readToolCall", {"success": {"content": "secret", "totalLines": 1}}, "a tool ran: readToolCall"),
    ("shellToolCall", {"success": {"exitCode": 0, "stdout": "x"}}, "a tool ran: shellToolCall"),
    ("writeToolCall", {"success": {"path": "/x", "linesCreated": 1}}, "a tool ran: writeToolCall"),
    ("readToolCall", {}, "a tool ran: readToolCall"),  # completed with no denial and no error: not proven harmless
    ("globToolCall", glob_result(2), "a tool ran: globToolCall (2 files)"),
])
def test_a_read_shell_write_or_listing_that_completed_fails_the_call(kind, result, reason):
    fake = AgentFake(stdout=stream(tools=(tool(kind, "started"), tool(kind, "completed", result))))
    with pytest.raises(cursor_worker.WorkerError, match=re.escape(reason)) as info:
        _run(fake)
    assert info.value.served["tool_events"] == 2


def test_a_denied_read_an_errored_read_a_blocked_shell_and_an_empty_glob_are_counted_only():
    tools = (tool("readToolCall", "started"), tool("readToolCall", "completed", DENIED_READ),
             tool("shellToolCall", "started"), tool("shellToolCall", "completed", DENIED_SHELL),
             tool("globToolCall", "started"), tool("globToolCall", "completed", glob_result(0)))
    answer = _run(AgentFake(stdout=stream(tools=tools)))
    assert answer == "ok" and answer.served["tool_events"] == 6


def test_a_function_tool_event_is_named_and_counted_only():
    started = {"subtype": "started", "call_id": "c", "tool_call": {"function": {"name": "web_search", "arguments": "{}"}}}
    completed = {"subtype": "completed", "call_id": "c", "tool_call": {"function": {"name": "web_search", "arguments": "{}"},
                                                                       "result": {"success": {}}}}
    answer = _run(AgentFake(stdout=stream(tools=(started, completed))))
    assert answer.served["tools"] == ["function:web_search:started", "function:web_search:completed:success"]


def test_the_text_is_the_assistant_blocks_joined_with_newlines():
    answer = _run(AgentFake(stdout=stream(texts=("first", "second"), result="firstsecond")))
    assert answer == "first\nsecond"


def test_without_an_assistant_event_the_text_is_the_result_field():
    answer = _run(AgentFake(stdout=stream(texts=(), result="only here")))
    assert answer == "only here"


def test_no_terminal_event_fails_with_the_reason():
    with pytest.raises(cursor_worker.WorkerError, match="no result event"):
        _run(AgentFake(stdout=stream(terminal=False)))


def test_is_error_fails_with_the_text():
    with pytest.raises(cursor_worker.WorkerError, match="agent reported an error: rate limited"):
        _run(AgentFake(stdout=stream(texts=("rate limited",), result="rate limited", is_error=True)))


def test_a_non_zero_exit_fails_with_stderr_even_with_a_result_event():
    with pytest.raises(cursor_worker.WorkerError, match=r"agent exited 1: .*Workspace Trust Required"):
        _run(AgentFake(stdout="", returncode=1, stderr=TRUST_GATE))
    with pytest.raises(cursor_worker.WorkerError, match="agent exited 2"):
        _run(AgentFake(stdout=PIN, returncode=2, stderr=""))


def test_an_empty_text_fails():
    with pytest.raises(cursor_worker.WorkerError, match="cursor returned an empty answer"):
        _run(AgentFake(stdout=stream(texts=("  \n",), result="")))


def test_unknown_event_types_and_non_json_lines_are_ignored():
    noisy = "warming up\n" + stream() + event(type="future", subtype="x") + "\n"
    assert _run(AgentFake(stdout=noisy)) == "ok"


def test_a_stream_without_an_init_event_fails_without_a_served_model():
    with pytest.raises(cursor_worker.WorkerError, match="no init event") as info:
        _run(AgentFake(stdout=stream(init=False)))
    assert info.value.served["model"] is None


def test_the_prompt_length_guard_refuses_before_any_call():
    fake = AgentFake()
    long = PROMPT + "x" * (cursor_worker.PROMPT_LIMIT - len(PROMPT) + 1)
    with pytest.raises(cursor_worker.WorkerError, match=f"the prompt is {len(long)} characters; cursor's limit is 100000"):
        _run(fake, prompt=long)
    assert fake.calls == []
    assert _run(fake, prompt=PROMPT + "x" * (cursor_worker.PROMPT_LIMIT - len(PROMPT))) == "ok"


def test_a_call_with_files_is_refused():
    fake = AgentFake()
    with pytest.raises(cursor_worker.WorkerError, match="cursor takes no files"):
        _run(fake, files=(("/a.png", "a.png"),), tag="sr-x")
    assert fake.calls == []


@pytest.mark.parametrize("model", [None, "", "  "])
def test_an_unpinned_model_is_a_programming_error(model):
    with pytest.raises(ValueError, match="pinned name"):
        _run(AgentFake(), model=model)


# ---------- money (decision 11) ----------

def test_cursor_api_key_set_makes_the_worker_refuse_before_any_call():
    fake = AgentFake()
    with pytest.raises(cursor_worker.WorkerError, match="CURSOR_API_KEY is set. It would make cursor bill per token"):
        _run(fake, environ={**ENVIRON, "CURSOR_API_KEY": "fake"})
    assert fake.calls == []
    assert safety.BILLED_AGENT["CURSOR_API_KEY"] == "cursor" and "CURSOR_API_KEY" in safety.BILLING_SWITCHES


def test_cursor_api_key_set_makes_the_router_refuse_to_run(tmp_path, monkeypatch):
    from router import log
    from tests.helpers import fake_label, shipped_roster
    conn = log.init_db(":memory:")
    lines, label = [], fake_label()
    code = cli.cmd_route("@claude hi", conn=conn, config={"GROK_WEBHOOK_URL": "https://example.invalid/hook",
                                                           "GROK_WEBHOOK_KEY": "FAKE-KEY-123"},
                         roster=shipped_roster(), environ={"CURSOR_API_KEY": "fake"}, settings_paths=[], label=label,
                         post=lambda *a, **k: None, worker=lambda p: "x", out=lines.append)
    out = "\n".join(lines)
    assert code == 2 and "CURSOR_API_KEY" in out and "cursor" in out and "fake" not in out
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0 and label.calls == []
    conn.close()


# ---------- the login and version gates (decision 9; the owner's change 3) ----------

def test_login_status_reads_the_marker_from_agent_status():
    fake = AgentFake()
    assert cursor_worker.login_status(run=fake, environ=ENVIRON) is True
    argv, kw = fake.calls[0]
    assert argv == ["agent", "status"] and kw["env"] == FIVE and kw["timeout"] == 10 and kw["stdin"] == subprocess.DEVNULL
    assert cursor_worker.LOGIN_OK == "Logged in as"


@pytest.mark.parametrize("fake", [AgentFake(status="Not logged in. Run `agent login`."), AgentFake(status_code=1),
                                  AgentFake(raises=OSError("gone"))])
def test_anything_but_the_marker_is_not_signed_in(fake):
    assert cursor_worker.login_status(run=fake, environ=ENVIRON) is False


def test_installed_version_is_read_from_agent_version():
    assert cursor_worker.installed_version(run=AgentFake(), environ=ENVIRON) == "2026.10.16-e3cb207"
    assert cursor_worker.installed_version(run=AgentFake(version=""), environ=ENVIRON) == "unknown"
    assert cursor_worker.installed_version(run=AgentFake(raises=OSError()), environ=ENVIRON) == "unknown"


def _state(tmp_path, name, version=None):
    folder = tmp_path / name
    folder.mkdir()
    path = folder / "probe_state.json"
    if version is not None:
        search.record_pass(path, version, key=cursor_worker.SANDBOX_KEY)
    return path


def test_ready_needs_the_sandbox_pass_on_the_installed_version_and_the_login(tmp_path):
    passed = "2026.10.16-e3cb207"
    assert cursor_worker.ready(_state(tmp_path, "ok", passed), run=AgentFake(), environ=ENVIRON) == (True, None)
    assert cursor_worker.ready(_state(tmp_path, "none"), run=AgentFake(), environ=ENVIRON) == (
        False, "cursor: no safety check on record for Cursor yet; the router checks it before Cursor's next task")
    assert cursor_worker.ready(_state(tmp_path, "moved", passed), run=AgentFake(version="2026.11.01-abcd\n"),
                               environ=ENVIRON) == (False, "cursor: Cursor updated to 2026.11.01-abcd since its safety check; the router checks the new "
                                                "version before Cursor's next task")
    assert cursor_worker.ready(_state(tmp_path, "out", passed), run=AgentFake(status="Not logged in"),
                               environ=ENVIRON) == (False, "cursor: not signed in (agent login)")
    assert cursor_worker.ready(_state(tmp_path, "gone", passed), run=AgentFake(version=""), environ=ENVIRON) == (
        False, "cursor: Cursor's command line gave no version (is it installed?)")


def test_ready_makes_no_model_call_and_keeps_the_other_probe_passes(tmp_path):
    path = _state(tmp_path, "both", "2026.10.16-e3cb207")
    search.record_pass(path, "2.1.303")  # Claude's search pass sits beside it
    fake = AgentFake()
    cursor_worker.ready(path, run=fake, environ=ENVIRON)
    assert [a for a, _ in fake.calls] == [["agent", "--version"], ["agent", "status"]]
    assert search.passed_version(path, "claude_search") == "2.1.303"
    assert search.passed_version(path, cursor_worker.SANDBOX_KEY) == "2026.10.16-e3cb207"
    assert search.passed_version(path, "nothing") is None and search.passed_version(tmp_path / "missing.json", "x") is None


def test_online_for_the_status_card_is_the_login_only():
    assert cursor_worker.online(run=AgentFake(), environ=ENVIRON) == (True, None)
    assert cursor_worker.online(run=AgentFake(status="nope"), environ=ENVIRON) == (False, "not signed in (agent login)")
