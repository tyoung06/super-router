"""Redaction and environment checks.

Problems are always reported by name, never by value.
"""
import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = REPO_ROOT / "workspace"

# Build brief 24 (decision 12): no .env name is required any more. Grok's two webhook names matter only for Grok: a
# missing one means Grok Bot isn't set up (router/availability.py), never that every command is refused.

# Any of these makes an agent bill per token instead of using its plan. The router refuses to
# run while one is set, in the shell or in .env (SUPER-ROUTER.md, Money).
BILLED_AGENT = {
    "ANTHROPIC_API_KEY": "claude",
    "ANTHROPIC_AUTH_TOKEN": "claude",
    "CLAUDE_CODE_USE_BEDROCK": "claude",
    "CLAUDE_CODE_USE_VERTEX": "claude",
    "OPENAI_API_KEY": "chatgpt",
    "CODEX_API_KEY": "chatgpt",
    "CURSOR_API_KEY": "cursor",  # rules v2.28, Money: Cursor runs on its own login and the X Subscription's pool, never a key
}
BILLING_SWITCHES = tuple(BILLED_AGENT)

# The only environment variables a `claude` subprocess gets.
CLAUDE_ENV_KEYS = ("HOME", "PATH", "USER", "LANG")
# The only environment variables an `agent` (Cursor) subprocess gets (build brief 20, decision 2): the four above and
# TMPDIR, where the command keeps its session scratch. Built from scratch, so no key, token or webhook value reaches it.
CURSOR_ENV_KEYS = ("HOME", "PATH", "USER", "LANG", "TMPDIR")


class SafeError(Exception):
    """An error whose message is written to contain no secrets.

    Still redacted before it is stored or shown.
    """


# Rules v2.25 (Secrets): a project's handoff that still holds something that looks like a key after redaction is
# never sent. These are shapes, not values: a `.env` name or a key word with a value, a bearer token, the known
# prefixes, a URL carrying a key. A `[REDACTED]` value is the redactor's own mark and never matches. A false
# positive stops the task and names the line, which is the safe direction.
_ENV_NAMES = "|".join(("GROK_WEBHOOK_URL", "GROK_WEBHOOK_KEY", "JEV_API_KEY") + tuple(BILLED_AGENT))
_VALUE = r"[\"']?(?!\[REDACTED\])\S{8,}"
KEY_PATTERNS = (
    re.compile(r"\b(?:" + _ENV_NAMES + r")\s*[:=]\s*" + _VALUE),
    re.compile(r"(?i)\b(?:api[_ -]?key|secret|token|password|passwd|webhook(?:[_ -]?url)?)\b\s*[:=]\s*" + _VALUE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bxox[abp]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"(?i)https?://\S*[?&](?:key|token|secret|api_key|apikey|access_token)=(?!\[REDACTED\])\S+"),
)


def key_like(text):
    """The 1-based number of the first line that looks like it holds a key, or None. Shapes only, never values."""
    for n, line in enumerate((text or "").splitlines(), 1):
        if any(p.search(line) for p in KEY_PATTERNS):
            return n
    return None


SECRET_MIN_LENGTH = 8  # build brief 22 (decision 10, the owner's amendment): a shorter .env value is not a secret


def env_secrets(values):
    """The secrets in `.env` (rules v2.31, Secrets; build brief 22, decision 10): every value of 8 characters or more,
    in order, once each. A shorter value is not treated as a secret and is never masked (it would mask common words).
    The log, the prose, the JSON and the round files all redact with this one set."""
    return list(dict.fromkeys(v for v in (values or {}).values() if isinstance(v, str) and len(v) >= SECRET_MIN_LENGTH))


def redact(text, secrets):
    text = "" if text is None else str(text)
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return text


# Characters that can hide, fake or reorder what a terminal shows.
_BIDI = {0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A)}
_MARK = "\ufffd"


def for_terminal(text, secrets=()):
    """Make untrusted text safe to print. Control and direction-changing characters are
    replaced (never deleted, so a split secret can't be glued back together), then the
    display copy is redacted again. The log keeps the raw redacted text."""
    text = "" if text is None else str(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    shown = "".join(
        ch if ch in "\n\t" or not (ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F or ord(ch) in _BIDI)
        else _MARK
        for ch in text
    )
    return redact(shown, secrets)


def one_line(text, secrets=()):
    """for_terminal for text that must stay on one line, such as a file name inside a message:
    a newline or a tab in it becomes the mark too, so a name can't fake a second line of output."""
    return for_terminal(text, secrets).replace("\n", _MARK).replace("\t", _MARK)


def _is_set(env, name):
    return bool((env.get(name) or "").strip())


def billing_problems(env):
    return [
        f"{name} is set. It would make {BILLED_AGENT[name]} bill per token. Unset it and run again."
        for name in BILLING_SWITCHES
        if _is_set(env, name)
    ]


def check_env(env):
    """Every reason in the environment and .env to refuse to run at all: the per-token billing switches, by name, never
    value. Build brief 24 (decision 12): a missing webhook name is not one."""
    return billing_problems(env)


def check_claude_settings(settings):
    if settings.get("apiKeyHelper"):
        return ["apiKeyHelper is set in Claude settings. It would make claude bill per token."]
    return []


def _settings_files(paths):
    """Per settings file, in order: ("problem", the line) when it can't be read or parsed, or ("settings", the object)."""
    for path in paths:
        try:
            text = path.read_text()
        except FileNotFoundError:
            continue
        except OSError:
            yield "problem", f"Could not read {path.name} to check for apiKeyHelper."
            continue
        try:
            settings = json.loads(text)
        except ValueError:
            yield "problem", f"Could not parse {path.name} to check for apiKeyHelper."
            continue
        if isinstance(settings, dict):
            yield "settings", settings


def check_claude_settings_files(paths):
    problems = []
    for kind, found in _settings_files(paths):
        problems += [found] if kind == "problem" else check_claude_settings(found)
    return problems


def bills_per_token(environ, config, settings_paths):
    """True when a per-token billing switch is set (build brief 21: the refusal's code is billing_switch, read from the
    switches themselves, never from the wording of the problem lines)."""
    return bool(billing_problems(environ) or billing_problems(config)
                or any(check_claude_settings(found) for kind, found in _settings_files(settings_paths) if kind == "settings"))


def check_host(platform):
    """The router runs only directly on the owner's Mac.

    Inside the Claude app's Linux VM the project folder is a shared folder, and
    SQLite's saves can fail halfway there (disk I/O error, 2026-10-02).
    """
    if platform == "darwin":
        return []
    return [
        f"Super Router runs only directly on your Mac, not here ({platform}). "
        "Inside the Claude app's VM its log can't save safely. Use a terminal on your Mac."
    ]


def claude_env(environ):
    return {name: environ[name] for name in CLAUDE_ENV_KEYS if name in environ}


def cursor_env(environ):
    """The five-name environment a Cursor call gets (router/cursor_worker.py); a name not set is left out."""
    return {name: environ[name] for name in CURSOR_ENV_KEYS if name in environ}


def prepare_workspace(workspace=WORKSPACE, run=subprocess.run):
    """Make workspace/ its own empty git repo.

    claude runs there and reads git context from the nearest repo. An empty one
    means it sees no commits from this project.
    """
    workspace.mkdir(exist_ok=True)
    if (workspace / ".git").exists():
        return
    proc = run(["git", "init", "-q", str(workspace)], capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise SafeError(f"git init in workspace/ failed: {proc.stderr.strip()[:200]}")


def claude_argv(model, tools=""):
    """Flags for every claude call. Task text never goes here; it goes on stdin. `tools` is ""
    (no tools) except on a call with files, which gets "Read" and runs inside the task's copy
    folder: --safe-mode confines Read to the working folder (proven 2026-10-13, brief 4's gate)."""
    return [
        "claude",
        "-p",
        "--model", model,
        "--strict-mcp-config",
        "--no-session-persistence",
        "--safe-mode",
        "--tools", tools,
    ]


# Every built-in tool a search call denies by name (build brief 8), on top of --tools allowing only
# WebSearch: no page fetching, no files, no shell, no notebooks, no sub-agents.
CLAUDE_DENIED_TOOLS = ("WebFetch", "Bash", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Glob", "Grep",
                       "Task", "Agent")


def claude_search_argv(model):
    """Flags for a Claude call with web search (rules v2.15, Web search; only router/search.py turns it
    on). Everything a plain call has, but the one built-in tool is WebSearch, allowed without a prompt
    (Claude Code 2.1.301: "WebSearchTool requires permission"); every other tool is denied by name; and
    the output is stream-json (which needs --verbose) so each tool call is on the record. Task text
    never goes here; it goes on stdin."""
    return [
        "claude",
        "-p",
        "--model", model,
        "--strict-mcp-config",
        "--no-session-persistence",
        "--safe-mode",
        "--tools", "WebSearch",
        "--allowedTools", "WebSearch",
        "--disallowedTools", *CLAUDE_DENIED_TOOLS,
        "--output-format", "stream-json",
        "--verbose",
    ]


# The addendum's D8 (rules v2.22): a Claude call with a file on a --web task gets Read (in its copy folder, where
# --safe-mode confines it) and WebSearch, and nothing else; every other tool is still denied by name.
CLAUDE_DENIED_WITH_FILES = tuple(t for t in CLAUDE_DENIED_TOOLS if t != "Read")


def claude_web_files_argv(model):
    """Flags for a Claude call with a file on a --web task: everything a search call has, but the built-in tools are
    Read and WebSearch. Only router/search.py turns it on, and only after the --web file probe passed on this
    Claude Code version. [GUESS] `--tools` takes two names as it takes one; the probe proves it from the init event."""
    return [
        "claude",
        "-p",
        "--model", model,
        "--strict-mcp-config",
        "--no-session-persistence",
        "--safe-mode",
        "--tools", "Read", "WebSearch",
        "--allowedTools", "WebSearch",
        "--disallowedTools", *CLAUDE_DENIED_WITH_FILES,
        "--output-format", "stream-json",
        "--verbose",
    ]


# Codex features that give the model something beyond text: commands, files, a browser, the
# computer, apps, images, hooks, plugins, skills, sub-agents. All on by default in codex-cli
# 0.162.1 (`codex features list`); the worker switches every one off.
# Every Codex capability beyond text and web search. Not here: code_mode_host, because in 0.162.1 the
# web-search tool runs through the code-mode host (task #8). Its JavaScript has no file, command or
# network reach of its own and can only call the tools Codex exposes; `sr probe` re-checks that.
CODEX_DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "unified_exec_tty", "view_image",
    "browser_use", "browser_use_external", "browser_use_full_cdp_access", "in_app_browser", "computer_use",
    "apps", "image_generation", "hooks", "plugins", "plugin_sharing", "remote_plugin",
    "skill_search", "skill_mcp_dependency_install", "multi_agent", "worktrees", "goals", "sleep_tool",
    "shell_snapshot", "tool_suggest", "workspace_dependencies",
)


def codex_argv(model, web_search, output_file, images=(), cd=None):
    """Flags for every codex call. The prompt never goes here; it goes on stdin (`-`). On a call
    with files, `cd` is the task's copy folder and each image goes in with --image (the only way
    ChatGPT can see a file: commands and the image tool stay off)."""
    argv = [
        "codex", "exec",
        "--sandbox", "read-only",
        "--ephemeral",            # no session files on disk
        "--ignore-user-config",   # The owner's ~/.codex/config.toml (and its MCP servers) stays out
        "--ignore-rules",         # and their execpolicy .rules files
        "--cd", str(cd or WORKSPACE),
        "--color", "never",
        "--model", model,
        "--output-last-message", str(output_file),
        "-c", 'approval_policy="never"',
        "-c", f'web_search="{web_search}"',
        "-c", "project_doc_max_bytes=0",  # no AGENTS.md text reaches the model
    ]
    for feature in CODEX_DISABLED_FEATURES:
        argv += ["--disable", feature]
    for image in images:
        argv += ["--image", str(image)]
    return argv + ["-"]


def check_claude_init(event):
    """Read claude's stream-json init event. Any tool or MCP server is a problem."""
    if event.get("type") != "system" or event.get("subtype") != "init":
        return ["Not a claude init event."]
    problems = []
    tools = event.get("tools")
    if tools is None:
        problems.append("Init event has no tools field.")
    elif tools:
        problems.append(f"claude has {len(tools)} tools: {', '.join(map(str, tools[:10]))}")
    servers = event.get("mcp_servers")
    if servers is None:
        problems.append("Init event has no mcp_servers field.")
    elif servers:
        names = [s.get("name", "?") if isinstance(s, dict) else str(s) for s in servers]
        problems.append(f"claude has {len(servers)} MCP servers: {', '.join(names[:10])}")
    return problems
