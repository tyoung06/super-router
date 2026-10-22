"""Run a task through `claude -p` in workspace/. Text answers only, on the plan. On a call with
files (rules v2.10, Media) the copies go to workspace/task-<tag>/, the call runs inside that folder
with the Read tool and nothing else, and the folder is removed afterwards."""
import json
import os
import subprocess
from pathlib import Path

from router import media, plan_limit, safety

WORKER_MODEL = "sonnet"
WORKER_TIMEOUT = 600
WORKSPACE = safety.WORKSPACE


class WorkerError(safety.SafeError):
    """The worker refused, failed, or timed out. `code` is `plan_limit` when the call stopped on a
    plan limit (rules v2.15, Resume), else None."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class SearchAnswer(str):
    """The answer of a call with web search, with the queries Claude ran (from its own tool log)."""

    def __new__(cls, text, queries=()):
        answer = super().__new__(cls, text)
        answer.queries = list(queries)
        return answer


def run(task, run=subprocess.run, environ=os.environ, files=(), tag=None, search=False):
    """`files` are (source, relative name) pairs from media.layout; `tag` names the copy folder.
    `search` (only router/search.py decides it) runs the call with WebSearch and nothing else and
    returns a SearchAnswer. With files too (a --web task, rules v2.22) the call runs in the copy folder with Read
    and WebSearch only, and every Read in Claude's tool log must be a path inside that folder: any other path
    fails the call and its answer is never used (the owner's D8). Without search the call is as it always was."""
    problems = safety.billing_problems(environ)
    if problems:
        raise WorkerError("refused: " + " ".join(problems))
    WORKSPACE.mkdir(exist_ok=True)
    if search and files:
        with media.workspace_copy(tag or "call", files, WORKSPACE) as folder:
            proc = _call(run, task, environ, folder, None, argv=safety.claude_web_files_argv(WORKER_MODEL))
            return _search_answer(proc, allowed=WEB_FILE_TOOLS, folder=folder)
    if search:
        return _search_answer(_call(run, task, environ, WORKSPACE, None, argv=safety.claude_search_argv(WORKER_MODEL)))
    if files:
        with media.workspace_copy(tag or "call", files, WORKSPACE) as folder:
            proc = _call(run, task, environ, folder, "Read")
    else:
        proc = _call(run, task, environ, WORKSPACE, "")
    limit = plan_limit.claude(proc.returncode, proc.stdout, proc.stderr)
    if limit:
        raise WorkerError(f"plan limit on claude: {limit[:300]}", code=plan_limit.CODE)
    if proc.returncode != 0:
        # The message can come on either stream: at an API error `claude -p` prints it as the answer.
        said = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        raise WorkerError(f"claude exited {proc.returncode}: {said[:300]}")
    answer = proc.stdout.strip()
    if not answer:
        raise WorkerError("claude returned an empty answer")
    return answer


def _events(stdout):
    found = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                found.append(json.loads(line))
            except ValueError:
                continue
    return found


def tool_uses(events):
    """(name, input) for every tool call in Claude's stream-json events, in order."""
    uses = []
    for event in events:
        if event.get("type") != "assistant":
            continue
        for block in (event.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                uses.append((block.get("name"), block.get("input") or {}))
    return uses


SEARCH_TOOLS = ("WebSearch",)
WEB_FILE_TOOLS = ("Read", "WebSearch")  # a --web file call (the owner's D8)


def tool_calls(events):
    """Every tool call in Claude's stream-json events, in order: {name, input, id, error}, where `error` is True or
    False from its tool_result (the user event that answers it), or None when no result came back."""
    results = {}
    for event in events:
        if event.get("type") != "user":
            continue
        for block in (event.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                results[block.get("tool_use_id")] = bool(block.get("is_error"))
    found = []
    for event in events:
        if event.get("type") != "assistant":
            continue
        for block in (event.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                found.append({"name": block.get("name"), "input": block.get("input") or {}, "id": block.get("id"),
                              "error": results.get(block.get("id"))})
    return found


def read_path(tool_input):
    """The path a Read call names, or None."""
    raw = tool_input.get("file_path") or tool_input.get("path")
    return raw if isinstance(raw, str) and raw.strip() else None


def inside(raw, folder):
    """True when a Read's path, resolved (symlinks and .. followed), is inside `folder`."""
    root = Path(folder).resolve()
    path = Path(raw)
    path = path if path.is_absolute() else root / path
    try:
        return path.resolve().is_relative_to(root)
    except (OSError, ValueError):
        return False


def reads_outside(uses, folder):
    """The Read calls (name, input) whose path is not inside `folder`, a path-less Read included."""
    return [i for n, i in uses if n == "Read" and not (read_path(i) and inside(read_path(i), folder))]


def init_problems(events, allowed=SEARCH_TOOLS):
    """What is wrong with a search call's init event: any tool but the allowed ones, or any MCP server."""
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None)
    if init is None:
        return ["no init event"]
    problems = []
    others = [t for t in init.get("tools") or [] if t not in allowed]
    if others:
        problems.append(f"tools other than {' and '.join(allowed)} were loaded: {', '.join(map(str, others[:10]))}")
    if init.get("mcp_servers"):
        problems.append(f"{len(init['mcp_servers'])} MCP server(s) were loaded")
    return problems


def _search_answer(proc, allowed=SEARCH_TOOLS, folder=None):
    """Read a search call's stream: the answer from its result event, the queries from its tool calls.
    Any tool but the allowed ones, loaded or used, fails the call and its answer is not used; so does, on a --web
    file call (`folder`), any Read whose path is not inside the copy folder (the owner's D8)."""
    events = _events(proc.stdout)
    problems = init_problems(events, allowed) if events else []
    uses = tool_uses(events)
    other = [name for name, _ in uses if name not in allowed]
    if other:
        problems.append(f"a tool other than {' and '.join(allowed)} ran: {', '.join(map(str, other[:5]))}")
    if folder is not None:
        outside = reads_outside(uses, folder)
        if outside:  # the paths are not printed: they may name a private file
            problems.append(f"{len(outside)} Read call(s) outside the task's copy folder")
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    text = (result or {}).get("result") or ""
    is_error = bool((result or {}).get("is_error"))
    limit = plan_limit.claude(1 if (is_error or proc.returncode) else 0, text, proc.stderr)
    if limit:
        raise WorkerError(f"plan limit on claude: {limit[:300]}", code=plan_limit.CODE)
    if problems:
        raise WorkerError("search call refused: " + "; ".join(problems))
    if result is None:
        said = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        raise WorkerError(f"claude exited {proc.returncode} with no result event: {said[:300]}")
    if proc.returncode != 0 or is_error:
        raise WorkerError(f"claude exited {proc.returncode}: {text.strip()[:300]}")
    if not text.strip():
        raise WorkerError("claude returned an empty answer")
    return SearchAnswer(text.strip(), [str(i.get("query", "")) for n, i in tool_uses(events) if n == "WebSearch"])


def _call(run, task, environ, cwd, tools, argv=None):
    try:
        return run(
            argv or safety.claude_argv(WORKER_MODEL, tools=tools),
            input=task,
            capture_output=True,
            text=True,
            timeout=WORKER_TIMEOUT,
            env=safety.claude_env(environ),
            cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        raise WorkerError(f"claude timed out after {WORKER_TIMEOUT} s") from None
    except OSError as e:
        raise WorkerError(f"could not start claude ({type(e).__name__})") from None
