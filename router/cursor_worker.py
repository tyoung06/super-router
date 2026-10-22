"""Run a prompt through the Cursor command line, `agent -p`, on the owner's X Subscription (rules v2.28, Cursor; build
brief 20): one Grok model pinned by name in config/agents.json, every tool denied, text in and text out. The prompt
is the command's one positional argument; the answer is read from its stream-json events: the assistant text blocks
(the terminal `result` field only when there is none), the init event's served model, every tool event counted and
named. Each call runs from a fresh scratch folder workspace/cursor/<call_id>/ that holds only the deny file
.cursor/cli.json, with the five-name environment (router/safety.py, cursor_env), and the folder is removed afterwards
whatever happened. Never --force, --yolo, --resume, --api-key; the router refuses to run while CURSOR_API_KEY is set.
Proved by the Phase 0 canary probes on agent 2026.10.16-e3cb207 (2026-10-19): a read, a shell command and a listing,
all refused by the deny file; the pass is pinned to that version in probe_state.json (`cursor_sandbox`) and proved
again by `sr probe` when the command moves (router/cursor_probe.py)."""
import json
import os
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from router import checking, safety, search

WORKER_TIMEOUT = 600      # the number the Claude worker uses (choice 6)
STATUS_TIMEOUT = 10       # `agent status` and `agent --version`: local reads, never a model call (decision 9)
PROMPT_LIMIT = 100_000    # characters: the prompt rides on the command line (decision 2)
WORKSPACE = safety.WORKSPACE
SCRATCH_ROOT = "cursor"   # workspace/cursor/<call_id>/, under the folder the other workers use
DENY_FILE = Path(".cursor") / "cli.json"
# Decision 3, the file the canaries proved: every shell command, read and write, relative and absolute. "Deny rules
# take precedence over allow rules" (the permissions page), so ~/.cursor/cli-config.json cannot widen it. Changing
# this file means running the canaries again.
DENY = {"permissions": {"allow": [], "deny": ["Shell(*)", "Read(**)", "Write(**)", "Read(/**)", "Write(/**)"]}}
LOGIN_OK = "Logged in as"       # `agent status` on the owner's Mac, 2026-10-19: "✓ Logged in as <address>"
SANDBOX_KEY = "cursor_sandbox"  # probe_state.json: the agent version the canary probes passed on (the owner, 2026-10-19)
# Decision 8: after the scope paragraph, on every Cursor call (build, review, re-ask; a routed call too).
NO_TOOLS_SENTENCE = (
    "You have no tools in this session: do not try to read, write, run or search anything, and put everything you "
    "produce in your reply as text."
)
# The subcommands `agent --help` lists (2026.10.16-e3cb207). The command matches its first positional token against
# them, so a prompt starting with one of these words would run that subcommand (`update`, `login`, `ls`, ...). Every
# prompt opens with the scope paragraph (wrap), whose first word is "This", and run() refuses one that does not.
SUBCOMMANDS = ("persist", "install-shell-integration", "uninstall-shell-integration", "login", "logout", "mcp",
               "plugin", "worker", "status", "whoami", "models", "team", "bedrock", "about", "update", "create-chat",
               "generate-rule", "rule", "agent", "ls", "resume", "help")
# The stream's tool kinds (the key under `tool_call`): the three the deny file covers fail the call when one
# completes without a denial or an error; a listing fails it when it found anything (choice 10, the owner's change 2).
FENCED_TOOLS = ("readToolCall", "shellToolCall", "writeToolCall")
GLOB_TOOL = "globToolCall"
_CONTEXT_TOKEN = re.compile(r"\d+[km]", re.IGNORECASE)  # "256K", "1M": a context-size tier in a display name
_FAST = "fast"


class WorkerError(safety.SafeError):
    """The worker refused, failed or timed out. `served` is the call's served record when the stream got as far as
    an init event (the row keeps it, so a mismatch names both models). `code` stays None: a Cursor stop is never a
    plan limit (rules v2.28, Resume)."""

    def __init__(self, message, served=None, code=None, stream=None):
        super().__init__(message)
        self.served = served
        self.code = code
        self.stream = stream  # the raw stdout, when the command ran (choice 3: kept under media/cursor/)


class CursorAnswer(str):
    """The answer of a call, with the served record for the call row (decision 10)."""

    def __new__(cls, text, served=None, stream=None):
        answer = super().__new__(cls, text)
        answer.served = dict(served or {})
        answer.stream = stream  # the raw stdout (choice 3)
        return answer


@dataclass
class Parsed:
    events: list
    init: dict | None
    tools: list        # one dict per tool_call event: kind, subtype, outcome, files
    result: dict | None
    texts: list        # the assistant text blocks, in order


@dataclass
class Outcome:
    argv: list
    returncode: int
    stdout: str
    stderr: str
    parsed: Parsed


# ---------- the prompt and the command ----------

def opener():
    return f"{checking.SCOPE_PARAGRAPH} {NO_TOOLS_SENTENCE}"


def wrap(prompt):
    """Every Cursor prompt (decision 8, choice 5): the scope paragraph and the no-tools sentence, then the prompt the
    Claude worker would get for that role, byte for byte."""
    return f"{opener()}\n\n{prompt}"


def first_token_problem(prompt):
    """Why a prompt may not go on the command line as it is: empty, or its first word is one of Cursor's subcommands
    or starts with a dash, so the command would read it as a subcommand or a flag. None for a wrapped prompt."""
    text = prompt or ""
    if not text.strip():
        return "the prompt is empty"
    first = text.split(None, 1)[0]
    if first.startswith("-"):
        return f"the prompt starts with {first!r}, which the command would read as a flag"
    if first in SUBCOMMANDS:
        return f"the prompt starts with {first!r}, which the command would read as a subcommand"
    return None


def argv(model, scratch, prompt):
    """Flags first, the prompt last as the one positional (decision 2 with amendment 2 and the owner's change 12). The
    workspace is the scratch folder and --trust names it alone: without it print mode exits at Cursor's trust gate."""
    return ["agent", "-p", "--model", model, "--output-format", "stream-json", "--mode", "ask",
            "--sandbox", "enabled", "--workspace", str(scratch), "--trust", prompt]


def deny_text():
    return json.dumps(DENY, indent=2) + "\n"


def scratch_folder(call_id):
    """workspace/cursor/<call_id>/, made fresh (an older folder of the same name removed), holding the deny file."""
    scratch = WORKSPACE / SCRATCH_ROOT / str(call_id)
    if scratch.exists():
        shutil.rmtree(scratch)
    (scratch / DENY_FILE.parent).mkdir(parents=True)
    (scratch / DENY_FILE).write_text(deny_text())
    return scratch


def remove_scratch(scratch):
    """The scratch folder goes, and workspace/cursor/ with it when nothing else is there."""
    shutil.rmtree(scratch, ignore_errors=True)
    try:
        scratch.parent.rmdir()
    except OSError:
        pass


def call(prompt, *, model, run=subprocess.run, environ=os.environ, call_id="call"):
    """One `agent -p` from a fresh scratch folder: the raw outcome, not yet judged (the probe judges its own way).
    stdin is closed, so the command can never wait on a prompt. The folder is removed whatever happened."""
    scratch = scratch_folder(call_id)
    try:
        args = argv(model, scratch, prompt)
        try:
            proc = run(args, cwd=scratch, env=safety.cursor_env(environ), stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=WORKER_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise WorkerError(f"cursor timed out after {WORKER_TIMEOUT} s") from None
        except OSError as e:
            raise WorkerError(f"could not start agent ({type(e).__name__})") from None
        stdout, stderr = proc.stdout or "", proc.stderr or ""
        return Outcome(args, proc.returncode, stdout, stderr, parse(stdout))
    finally:
        remove_scratch(scratch)


# ---------- the stream ----------

def parse(stdout):
    """The stream-json events: the init event, every tool event (kind, subtype, outcome, files), the terminal result
    and the assistant text blocks. Lines that are not JSON objects and event types the docs do not list (`thinking`)
    are passed over."""
    events = []
    for line in (stdout or "").splitlines():
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            event = json.loads(text)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None)
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    texts = []
    for event in events:
        if event.get("type") != "assistant":
            continue
        for block in (event.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                texts.append(block["text"])
    tools = [_tool_event(e) for e in events if e.get("type") == "tool_call"]
    return Parsed(events, init, tools, result, texts)


def _tool_event(event):
    """One tool_call event: `kind` is the key under `tool_call` that names the tool (readToolCall, shellToolCall,
    writeToolCall, globToolCall, or function:<name>); `outcome` on a completed event is denied, error or success;
    `files` is a listing's totalFiles."""
    tool_call = event.get("tool_call") if isinstance(event.get("tool_call"), dict) else {}
    kind, body = None, {}
    for key, value in tool_call.items():
        if key.endswith("ToolCall") and isinstance(value, dict):
            kind, body = key, value
            break
    if kind is None and isinstance(tool_call.get("function"), dict):
        kind, body = f"function:{tool_call['function'].get('name')}", tool_call
    if kind is None:
        kind = "unknown"
    subtype = event.get("subtype")
    outcome = files = None
    if subtype == "completed":
        result = body.get("result") if isinstance(body.get("result"), dict) else {}
        outcome = "denied" if "permissionDenied" in result else "error" if "error" in result else "success"
        success = result.get("success") if isinstance(result.get("success"), dict) else {}
        if isinstance(success.get("totalFiles"), int) and not isinstance(success.get("totalFiles"), bool):
            files = success["totalFiles"]
    return {"kind": kind, "subtype": subtype, "outcome": outcome, "files": files}


def _files_text(n):
    return f"{n} file{'' if n == 1 else 's'}"


def tool_label(tool):
    """`<kind>:<subtype>`, with the outcome on a completed event and the file count on a listing (decision 10)."""
    label = f"{tool['kind']}:{tool['subtype']}"
    if tool["outcome"] is not None:
        label += f":{tool['outcome']}"
    if tool["files"] is not None:
        label += f" ({_files_text(tool['files'])})"
    return label


def tool_ran(tool):
    """Why a completed tool event is a breach of the sandbox, or None: a read, shell or write that completed without
    a denial or an error, or a listing that found anything (choice 10 with the owner's change 2). A denied or errored
    call, an empty listing and any other tool are counted and kept, never failed on."""
    if tool["subtype"] != "completed":
        return None
    if tool["kind"] in FENCED_TOOLS and tool["outcome"] not in ("denied", "error"):
        return f"a tool ran: {tool['kind']}"
    if tool["kind"] == GLOB_TOOL and (tool["files"] or 0) >= 1:
        return f"a tool ran: {GLOB_TOOL} ({_files_text(tool['files'])})"
    return None


def served_record(parsed, asked):
    """The call row's `served` record (decision 10, choice 11): the display name verbatim, the id asked for, the tool
    events counted and named, duration_ms and permissionMode from the stream, and the terminal event's usage."""
    init, result = parsed.init or {}, parsed.result or {}
    record = {"model": init.get("model"), "asked": asked, "tool_events": len(parsed.tools),
              "tools": [tool_label(t) for t in parsed.tools], "duration_ms": result.get("duration_ms"),
              "permission_mode": init.get("permissionMode")}
    if isinstance(result.get("usage"), dict):
        record["usage"] = result["usage"]
    return record


def _said(outcome):
    """The first 300 characters of stderr on one line, else of the last text the stream carried."""
    text = (outcome.stderr or "").strip()
    if not text:
        texts = outcome.parsed.texts or [str((outcome.parsed.result or {}).get("result") or "")]
        text = texts[-1]
    return " ".join(text.split())[:300]


def judge(outcome, asked):
    """Decision 4 and 5: the served model must be the one asked for before the text is used; then a non-zero exit, no
    terminal event, is_error, a tool that ran, or an empty text each fail the call with the reason. The owner's change 4:
    the text is the assistant blocks joined with newlines; the result field only when there was no assistant event."""
    parsed = outcome.parsed
    served = served_record(parsed, asked)
    said = _said(outcome)
    if parsed.init is None:
        if outcome.returncode != 0:
            raise WorkerError(f"agent exited {outcome.returncode}: {said}", served=served, stream=outcome.stdout)
        raise WorkerError(f"no init event in the stream: {said}", served=served, stream=outcome.stdout)
    served_name = parsed.init.get("model")
    if not model_matches(asked, served_name):
        raise WorkerError(f"served model {served_name!r} is not the one asked for ({asked}); the text was not used",
                          served=served, stream=outcome.stdout)
    if outcome.returncode != 0:
        raise WorkerError(f"agent exited {outcome.returncode}: {said}", served=served, stream=outcome.stdout)
    if parsed.result is None:
        raise WorkerError(f"agent exited 0 with no result event: {said}", served=served, stream=outcome.stdout)
    text = "\n".join(parsed.texts) if parsed.texts else str(parsed.result.get("result") or "")
    if parsed.result.get("is_error"):
        raise WorkerError(f"agent reported an error: {' '.join(text.split())[:300]}", served=served, stream=outcome.stdout)
    for tool in parsed.tools:
        reason = tool_ran(tool)
        if reason:
            raise WorkerError(reason, served=served, stream=outcome.stdout)
    text = text.strip()
    if not text:
        raise WorkerError("cursor returned an empty answer", served=served, stream=outcome.stdout)
    return CursorAnswer(text, served, stream=outcome.stdout)


def run(prompt, *, model, run=subprocess.run, environ=os.environ, call_id="call", files=(), tag=None):
    """One Cursor call: the prompt as wrap() made it (the opener first), the pinned model, the scratch folder named
    by the call id. Refused before any call: a billing switch, no pinned model, files, a prompt that does not open
    with the scope paragraph, a prompt past PROMPT_LIMIT characters. Returns a CursorAnswer with `served`."""
    problems = safety.billing_problems(environ)
    if problems:
        raise WorkerError("refused: " + " ".join(problems))
    if not isinstance(model, str) or not model.strip():
        raise ValueError("the Cursor model must be a pinned name (config/agents.json).")
    if files:
        raise WorkerError("cursor takes no files (rules v2.28, Cursor): a task with files never reaches it")
    if not (prompt or "").startswith(checking.SCOPE_PARAGRAPH) or first_token_problem(prompt):
        raise WorkerError("refused: a Cursor prompt must open with the scope paragraph (cursor_worker.wrap), so the "
                          "command never reads its first word as a subcommand")
    if len(prompt) > PROMPT_LIMIT:
        raise WorkerError(f"refused: the prompt is {len(prompt)} characters; cursor's limit is {PROMPT_LIMIT}")
    return judge(call(prompt, model=model, run=run, environ=environ, call_id=call_id), model)


# ---------- the served model (decision 5, choice 2, the owner's change 1) ----------

def _normalise(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def model_matches(asked, served):
    """True when the display name the init event gave is the id asked for. The display name is tokenised: a Unicode
    format character anywhere (the zero-width characters Cursor's fast listings end in) or a `Fast` token marks the
    fast twin, and the asked id must then end in `-fast` (and the other way round); `256K`-like context tokens and
    the fast marker are dropped; `Extra High` reads as `xhigh`; a leading `cursor-` is dropped from the id; then both
    sides are lowercased to letters and digits and compared. An id ending in `-high` also matches the served name
    without `high` (Cursor's default effort, which its listing omits: `cursor-grok-4.6-high` is shown as `Grok 4.6`).
    `grok-4.7-high` and `Grok 4.7 256K High` both become `grok47high`."""
    if not isinstance(asked, str) or not isinstance(served, str) or not served.strip() or not asked.strip():
        return False
    has_format = any(unicodedata.category(ch) == "Cf" for ch in served)
    tokens = "".join(ch for ch in served if unicodedata.category(ch) != "Cf").split()
    served_fast = has_format or any(t.lower() == _FAST for t in tokens)
    asked_fast = asked.endswith(f"-{_FAST}")
    if served_fast != asked_fast:
        return False
    core = " ".join(t for t in tokens if t.lower() != _FAST and not _CONTEXT_TOKEN.fullmatch(t)).lower()
    served_n = _normalise(core.replace("extra high", "xhigh"))
    asked_core = asked[:-len(f"-{_FAST}")] if asked_fast else asked
    asked_n = _normalise(asked_core.removeprefix("cursor-"))
    if not served_n or not asked_n:
        return False
    return served_n == asked_n or (asked_n.endswith("high") and served_n == asked_n[:-len("high")])


# ---------- the gates: signed in, and the sandbox pass on the installed version (decision 9; the owner's change 3) ----------

def _local(args, run, environ):
    return run(args, capture_output=True, text=True, timeout=STATUS_TIMEOUT, env=safety.cursor_env(environ),
               stdin=subprocess.DEVNULL)


def login_check(run=subprocess.run, environ=os.environ):
    """(True, None) when `agent status` carries the signed-in marker, (False, why) when it answers without it, and
    (None, why) when it does not answer at all (a timeout, or the command could not start): that is not a sign-in
    answer, and brief 23 (choice 18) never reads it as one. Never a model call."""
    try:
        proc = _local(["agent", "status"], run, environ)
    except (subprocess.TimeoutExpired, OSError) as e:
        return None, f"agent status did not answer ({type(e).__name__})"
    if proc.returncode == 0 and LOGIN_OK.lower() in f"{proc.stdout}\n{proc.stderr}".lower():
        return True, None
    return False, "not signed in (agent login)"


def login_status(run=subprocess.run, environ=os.environ):
    """True only when `agent status` carries the signed-in marker. Anything else, a failure to run it included, is
    False. Never a model call."""
    return login_check(run, environ)[0] is True


def installed_version(run=subprocess.run, environ=os.environ):
    """What `agent --version` prints ("2026.10.16-e3cb207"), or "unknown"."""
    try:
        proc = _local(["agent", "--version"], run, environ)
    except (subprocess.TimeoutExpired, OSError):
        return "unknown"
    lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    return lines[0] if proc.returncode == 0 and lines else "unknown"


class Readiness(tuple):
    """(ok, reason), equal to the plain pair, with `code` beside it (build brief 21: a refusal's reason_code in the
    JSON): probe_failed when the sandbox pass is not on the installed version, signed_out when not signed in."""

    def __new__(cls, pair, code=None):
        made = super().__new__(cls, pair)
        made.code = code
        return made


def ready(state_path, run=subprocess.run, environ=os.environ):
    """(True, None), or (False, reason): asked once per command before the first Cursor call (the owner's change 3).
    The sandbox probe's pass on record (probe_state.json) must be on the installed agent version, and the command
    must be signed in. Two local reads, never a model call. A Readiness, so the refusal's code rides along."""
    recorded = search.passed_version(state_path, SANDBOX_KEY)
    if recorded is None:  # brief 23 (decision 5): plain words, what the router does next; never "run sr probe"
        return Readiness((False, "cursor: no safety check on record for Cursor yet; the router checks it before Cursor's "
                                 "next task"), "probe_failed")
    installed = installed_version(run, environ)
    if installed == "unknown":
        return Readiness((False, "cursor: Cursor's command line gave no version (is it installed?)"), "probe_failed")
    if installed != recorded:
        return Readiness((False, f"cursor: Cursor updated to {installed} since its safety check; the router checks the new "
                                 "version before Cursor's next task"), "probe_failed")
    signed_in, why = login_check(run, environ)
    if not signed_in:  # brief 23 (choice 18): a check that didn't answer says so; the code stays signed_out
        return Readiness((False, f"cursor: {why}"), "signed_out")
    return Readiness((True, None))


def online(run=subprocess.run, environ=os.environ):
    """The status page's check (decision 9): online means `agent status` says signed in, nothing more. Brief 23
    (choice 18): a check that doesn't answer reads "agent status did not answer", never "not signed in"."""
    signed_in, why = login_check(run, environ)
    return (True, None) if signed_in else (False, why)
