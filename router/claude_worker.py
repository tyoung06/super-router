"""Run a task through `claude -p` in workspace/. Text answers only, on the plan. On a call with
files (rules v2.10, Media) the copies go to workspace/task-<tag>/, the call runs inside that folder
with the Read tool and nothing else, and the folder is removed afterwards.

Brief 33.3 (rules 2.48, Models): every call runs on the model its `choice` names (router/models.py resolves it; the
agent default when none is given), with its time limit and, when one was set, its effort; every call is stream-json,
so the answer is the result event's text and the stream names the model that answered (`served` on the answer, with the
init event's model, the result's modelUsage keys and what the stream said about usage credits). A rate-limit event
that marks the call billed to usage credits fails the call with the code `credits` (decision 6). The probes keep
`WORKER_MODEL`, the agent default's alias (decision 10)."""
import json
import os
import subprocess
from pathlib import Path

from router import media, models, plan_limit, safety

WORKER_MODEL = "sonnet"
WORKER_TIMEOUT = 600
WORKSPACE = safety.WORKSPACE


class WorkerError(safety.SafeError):
    """The worker refused, failed, or timed out. `code` is `plan_limit` when the call stopped on a
    plan limit (rules v2.15, Resume), `credits` when its stream marked it billed to usage credits (brief 33.3), else
    None. `served` (brief 33.3) is the served record the stream gave before the failure, when there was one."""

    def __init__(self, message, code=None, served=None):
        super().__init__(message)
        self.code = code
        self.served = served


class SearchAnswer(str):
    """The answer of a call with web search, with the queries Claude ran (from its own tool log). Brief 29.1 (issue 2): a
    file-mode call's answer also carries the tools its init event listed. Brief 33.3: `served`, the served record."""

    def __new__(cls, text, queries=(), tools=None, served=None):
        answer = super().__new__(cls, text)
        answer.queries = list(queries)
        answer.tools = list(tools) if tools is not None else None
        answer.served = served
        return answer


class Answer(str):
    """The answer of a plain call (no search), with its served record (brief 33.3)."""

    def __new__(cls, text, served=None):
        answer = super().__new__(cls, text)
        answer.served = served
        return answer


def default_choice():
    """The agent default as the worker runs it when nothing resolved a model (the probes, a direct call)."""
    return models.Choice("claude", WORKER_MODEL, timeout=WORKER_TIMEOUT)


def run(task, run=subprocess.run, environ=os.environ, files=(), tag=None, search=False, copy=None, choice=None):
    """`files` are (source, relative name) pairs from media.layout; `tag` names the copy folder.
    `search` (only router/search.py decides it) runs the call with WebSearch and nothing else and
    returns a SearchAnswer. With files too (a --web task, rules v2.22) the call runs in the copy folder with Read
    and WebSearch only, and every Read in Claude's tool log must be a path inside that folder: any other path
    fails the call and its answer is never used (the owner's D8). Without search the call is as it always was.
    `choice` (brief 33.3) is the call's model, effort and time limit (router/models.py); None runs the agent default."""
    problems = safety.billing_problems(environ)
    if problems:
        raise WorkerError("refused: " + " ".join(problems))
    choice = choice or default_choice()
    model, effort, timeout = choice.model or WORKER_MODEL, choice.effort, choice.timeout or WORKER_TIMEOUT
    if copy is not None:  # build brief 28: a file-mode call, with the task's copy as its working folder
        argv = safety.claude_files_argv(model, write=copy.write, search=copy.search, effort=effort)
        return _files_answer(_call(run, task, environ, copy.folder, None, argv=argv, timeout=timeout), copy, choice)
    WORKSPACE.mkdir(exist_ok=True)
    if search and files:
        with media.workspace_copy(tag or "call", files, WORKSPACE) as folder:
            proc = _call(run, task, environ, folder, None, argv=safety.claude_web_files_argv(model, effort=effort),
                         timeout=timeout)
            return _search_answer(proc, allowed=WEB_FILE_TOOLS, folder=folder, choice=choice)
    if search:
        return _search_answer(_call(run, task, environ, WORKSPACE, None, argv=safety.claude_search_argv(model, effort=effort),
                                    timeout=timeout), choice=choice)
    if files:
        with media.workspace_copy(tag or "call", files, WORKSPACE) as folder:
            proc = _call(run, task, environ, folder, "Read", argv=safety.claude_argv(model, tools="Read", effort=effort),
                         timeout=timeout)
    else:
        proc = _call(run, task, environ, WORKSPACE, "", argv=safety.claude_argv(model, effort=effort), timeout=timeout)
    return _plain_answer(proc, choice)


def _plain_answer(proc, choice):
    """A plain call's stream (brief 33.3): the answer from its result event, the served record from the stream; a plan
    limit as before (the result event's text, or either stream on a non-zero exit); a credits mark fails the call."""
    events = _events(proc.stdout)
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    text = (result or {}).get("result") or ""
    is_error = bool((result or {}).get("is_error"))
    served = models.claude_served(events, choice)
    limit = plan_limit.claude(1 if (is_error or proc.returncode) else 0, text if result is not None else proc.stdout,
                              proc.stderr)
    if limit:
        raise WorkerError(f"plan limit on claude: {limit[:300]}", code=plan_limit.CODE, served=served)
    _credits_check(served)
    if result is None:
        # The message can come on either stream: at an API error `claude -p` prints it as the answer.
        said = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        raise WorkerError(f"claude exited {proc.returncode} with no result event: {said[:300]}", served=served)
    if proc.returncode != 0 or is_error:
        raise WorkerError(f"claude exited {proc.returncode}: {text.strip()[:300]}", served=served)
    if not text.strip():
        raise WorkerError("claude returned an empty answer", served=served)
    return Answer(text.strip(), served=served)


CREDITS_WORDS = ("this call was billed to usage credits (the stream's rate-limit event says paid extra usage covered it); "
                 "the task stops and Fable is turned off (rules 2.48, Models)")


def _credits_check(served):
    """Decision 6: a stream whose rate-limit event marks the call billed to usage credits fails it, code `credits`."""
    if (served or {}).get("credits", {}).get("billed"):
        raise WorkerError(f"usage credits: {CREDITS_WORDS}", code=models.CREDITS, served=served)


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


def ran_and_refused(calls, allowed):
    """The tools in `calls` (tool_calls) not named in `allowed`, by name: those that ran and those asked for and refused.
    A call ran only when its result came back without Claude Code's error mark; a call with no result counts as ran (it
    can't be shown refused). Claude's file probe has read its tool log this way since Proof 1 (brief 30); the search and
    --web file probes since the design chat's fix of 29 Oct (Claude Code 2.1.312 asked for tools it didn't have)."""
    others = [c for c in calls if c["name"] not in allowed]
    return (sorted({str(c["name"]) for c in others if c["error"] is not True}),
            sorted({str(c["name"]) for c in others if c["error"] is True}))


def tools_line(ran, refused):
    """A probe check's detail naming both lists: `ran: Bash; asked for and refused: Read, Write`."""
    parts = ([f"ran: {', '.join(ran)}"] if ran else []) + ([f"asked for and refused: {', '.join(refused)}"] if refused else [])
    return "; ".join(parts) or "none in the tool log"


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


def _search_answer(proc, allowed=SEARCH_TOOLS, folder=None, choice=None):
    """Read a search call's stream: the answer from its result event, the queries from its tool calls.
    Any tool but the allowed ones loaded, or run, fails the call and its answer is not used; so does, on a --web
    file call (`folder`), any Read that ran whose path is not inside the copy folder (the owner's D8). Brief 33.1
    (decision 23c, brief 32's D8): which tools ran is read as the probes read it, with their own function
    (`ran_and_refused`): a tool Claude asked for and Claude Code refused never ran, so it never fails the call."""
    events = _events(proc.stdout)
    problems = init_problems(events, allowed) if events else []
    calls = tool_calls(events)
    ran, _ = ran_and_refused(calls, allowed)
    if ran:
        problems.append(f"a tool other than {' and '.join(allowed)} ran: {', '.join(ran[:5])}")
    if folder is not None:
        uses = [(c["name"], c["input"]) for c in calls if c["error"] is not True]  # a refused Read touched nothing
        outside = reads_outside(uses, folder)
        if outside:  # the paths are not printed: they may name a private file
            problems.append(f"{len(outside)} Read call(s) outside the task's copy folder")
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    text = (result or {}).get("result") or ""
    is_error = bool((result or {}).get("is_error"))
    served = models.claude_served(events, choice or default_choice())
    limit = plan_limit.claude(1 if (is_error or proc.returncode) else 0, text, proc.stderr)
    if limit:
        raise WorkerError(f"plan limit on claude: {limit[:300]}", code=plan_limit.CODE, served=served)
    _credits_check(served)
    if problems:
        raise WorkerError("search call refused: " + "; ".join(problems), served=served)
    if result is None:
        said = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        raise WorkerError(f"claude exited {proc.returncode} with no result event: {said[:300]}", served=served)
    if proc.returncode != 0 or is_error:
        raise WorkerError(f"claude exited {proc.returncode}: {text.strip()[:300]}", served=served)
    if not text.strip():
        raise WorkerError("claude returned an empty answer", served=served)
    return SearchAnswer(text.strip(), [str(i.get("query", "")) for n, i in tool_uses(events) if n == "WebSearch"],
                        served=served)


FILE_PATH_TOOLS = ("Read", "Edit", "Write", "Glob", "Grep")


def _outside(call, folder):
    """True when a file tool call names a path (file_path or path) that is not inside `folder`."""
    raw = call["input"].get("file_path") or call["input"].get("path")
    return isinstance(raw, str) and bool(raw.strip()) and not inside(raw, folder)


def _files_answer(proc, copy, choice=None):
    """Read a file-mode call's stream (build brief 28, decisions 3 and 7): the answer from its result event. The call fails,
    its answer unused, when the init event lists a tool beyond the call's own or an MCP server, when another tool's call
    ran (one Claude Code refused, such as a `Bash` it doesn't have, is not a run), or when a file tool that ran named a
    path outside the copy."""
    allowed = tuple(safety.CLAUDE_FILE_TOOLS if copy.write else safety.CLAUDE_READ_TOOLS) + (("WebSearch",) if copy.search else ())
    events = _events(proc.stdout)
    problems = init_problems(events, allowed) if events else []
    calls = tool_calls(events)
    ran, _ = ran_and_refused(calls, allowed)  # brief 33.1 (decision 23c): the probes' own function, not a copy
    if ran:
        problems.append(f"a tool beyond the call's own ran: {', '.join(ran[:5])}")
    outside = [c for c in calls if c["name"] in FILE_PATH_TOOLS and c["error"] is not True and _outside(c, copy.folder)]
    if outside:  # the paths are not printed: they may name a private file
        problems.append(f"{len(outside)} file tool call(s) outside the copy")
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    text = (result or {}).get("result") or ""
    is_error = bool((result or {}).get("is_error"))
    served = models.claude_served(events, choice or default_choice())
    limit = plan_limit.claude(1 if (is_error or proc.returncode) else 0, text, proc.stderr)
    if limit:
        raise WorkerError(f"plan limit on claude: {limit[:300]}", code=plan_limit.CODE, served=served)
    _credits_check(served)
    if problems:
        raise WorkerError("file-mode call refused: " + "; ".join(problems), served=served)
    if result is None:
        said = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        raise WorkerError(f"claude exited {proc.returncode} with no result event: {said[:300]}", served=served)
    if proc.returncode != 0 or is_error:
        raise WorkerError(f"claude exited {proc.returncode}: {text.strip()[:300]}", served=served)
    if not text.strip():
        raise WorkerError("claude returned an empty answer", served=served)
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None) or {}
    return SearchAnswer(text.strip(), [str(c["input"].get("query", "")) for c in calls if c["name"] == "WebSearch"],
                        tools=[str(t) for t in init.get("tools") or []], served=served)


def _call(run, task, environ, cwd, tools, argv=None, timeout=None):
    timeout = timeout or WORKER_TIMEOUT
    try:
        return run(
            argv or safety.claude_argv(WORKER_MODEL, tools=tools),
            input=task,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=safety.claude_env(environ),
            cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        raise WorkerError(f"claude timed out after {timeout} s") from None
    except OSError as e:
        raise WorkerError(f"could not start claude ({type(e).__name__})") from None
