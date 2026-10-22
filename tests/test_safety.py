"""Safety tests added in handoff v1.1/v1.2. Every secret here is fake."""
import json

import pytest

from router import safety

GOOD_ENV = {"GROK_WEBHOOK_URL": "https://example.invalid/hook", "GROK_WEBHOOK_KEY": "FAKE-KEY-123"}
OTHER_SWITCHES = ["ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"]


# ---------- billing switches ----------

@pytest.mark.parametrize("name", OTHER_SWITCHES)
def test_check_env_flags_every_billing_switch_by_name_not_value(name):
    problems = safety.check_env({**GOOD_ENV, name: "FAKE-SWITCH-VALUE"})
    assert len(problems) == 1
    assert name in problems[0]
    assert "FAKE-SWITCH-VALUE" not in problems[0]


def test_check_env_ignores_empty_billing_switch():
    assert safety.check_env({**GOOD_ENV, "ANTHROPIC_AUTH_TOKEN": "", "ANTHROPIC_API_KEY": "  "}) == []


def test_billing_problems_only_looks_at_billing_switches():
    assert safety.billing_problems({}) == []
    assert safety.billing_problems({"GROK_WEBHOOK_KEY": "FAKE-KEY-123"}) == []
    problems = safety.billing_problems({"CLAUDE_CODE_USE_BEDROCK": "1"})
    assert len(problems) == 1 and "CLAUDE_CODE_USE_BEDROCK" in problems[0]


# ---------- Claude settings ----------

def test_check_claude_settings_flags_api_key_helper_by_name_not_value():
    problems = safety.check_claude_settings({"apiKeyHelper": "/fake/helper.sh"})
    assert len(problems) == 1
    assert "apiKeyHelper" in problems[0]
    assert "/fake/helper.sh" not in problems[0]


def test_check_claude_settings_ok_without_helper():
    assert safety.check_claude_settings({}) == []
    assert safety.check_claude_settings({"permissions": {"allow": ["Read"]}}) == []


def test_check_claude_settings_files_missing_file_is_ok(tmp_path):
    assert safety.check_claude_settings_files([tmp_path / "settings.json"]) == []


def test_check_claude_settings_files_finds_helper(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"apiKeyHelper": "/fake/helper.sh"}))
    problems = safety.check_claude_settings_files([path])
    assert len(problems) == 1 and "apiKeyHelper" in problems[0]


def test_check_claude_settings_files_unreadable_json_is_a_problem(tmp_path):
    path = tmp_path / "settings.local.json"
    path.write_text("{not json")
    problems = safety.check_claude_settings_files([path])
    assert len(problems) == 1 and "settings.local.json" in problems[0]


# ---------- the environment and flags claude gets ----------

def test_claude_env_keeps_only_the_allowlist():
    environ = {
        "HOME": "/h", "PATH": "/bin", "USER": "t", "LANG": "en_US.UTF-8",
        "GROK_WEBHOOK_KEY": "FAKE-KEY-123", "ANTHROPIC_API_KEY": "FAKE",
        "ANTHROPIC_BASE_URL": "http://fake.invalid", "CLAUDECODE": "1",
    }
    assert safety.claude_env(environ) == {"HOME": "/h", "PATH": "/bin", "USER": "t", "LANG": "en_US.UTF-8"}


def test_claude_env_skips_missing_names():
    assert safety.claude_env({"PATH": "/bin"}) == {"PATH": "/bin"}


# ---------- workspace: its own empty git repo ----------

def test_prepare_workspace_makes_an_empty_git_repo_once(fake_run, tmp_path):
    workspace = tmp_path / "workspace"
    run = fake_run()
    safety.prepare_workspace(workspace, run=run)
    assert workspace.is_dir()
    argv, kw = run.calls[0]
    assert argv == ["git", "init", "-q", str(workspace)]
    assert kw["timeout"] == 30

    (workspace / ".git").mkdir()  # what git init would have made
    safety.prepare_workspace(workspace, run=run)
    assert len(run.calls) == 1, "an existing repo is left alone"


def test_prepare_workspace_git_failure_raises(fake_run, tmp_path):
    with pytest.raises(safety.SafeError):
        safety.prepare_workspace(tmp_path / "workspace", run=fake_run(returncode=1, stderr="no git"))


def test_workspace_is_inside_the_repo_and_gitignored():
    assert safety.WORKSPACE.parent == safety.REPO_ROOT
    assert "workspace/" in (safety.REPO_ROOT / ".gitignore").read_text().splitlines()


def test_claude_argv_has_every_safety_flag():
    argv = safety.claude_argv("haiku")
    assert argv[0] == "claude"
    for flag in ["-p", "--strict-mcp-config", "--no-session-persistence", "--safe-mode"]:
        assert flag in argv
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--model") + 1] == "haiku"


def test_claude_argv_never_skips_permissions_or_goes_bare():
    joined = " ".join(safety.claude_argv("sonnet"))
    assert "dangerously" not in joined
    assert "--bare" not in joined


# ---------- claude's init event ----------

def _init(**fields):
    return {"type": "system", "subtype": "init", **fields}


def test_check_claude_init_clean():
    assert safety.check_claude_init(_init(tools=[], mcp_servers=[])) == []


def test_check_claude_init_flags_tools_and_mcp_servers():
    problems = safety.check_claude_init(
        _init(tools=["Bash", "Read"], mcp_servers=[{"name": "brokerage", "status": "connected"}])
    )
    assert len(problems) == 2
    assert any("Bash" in p for p in problems)
    assert any("brokerage" in p for p in problems)


def test_check_claude_init_missing_fields_fail_closed():
    assert len(safety.check_claude_init(_init())) == 2


def test_check_claude_init_rejects_other_events():
    assert len(safety.check_claude_init({"type": "assistant"})) == 1


# ---------- redaction edges ----------

def test_redact_handles_none():
    assert safety.redact(None, ["FAKE-KEY-123"]) == ""


def test_redact_longest_secret_first():
    assert safety.redact("abcdef", ["abc", "abcdef"]) == "[REDACTED]"


def test_safe_error_is_an_exception():
    assert issubclass(safety.SafeError, Exception)


# ---------- host: only directly on the Mac ----------

def test_check_host_ok_on_the_mac():
    assert safety.check_host("darwin") == []


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_check_host_refuses_anywhere_else(platform):
    problems = safety.check_host(platform)
    assert len(problems) == 1
    assert "Mac" in problems[0] and platform in problems[0]
