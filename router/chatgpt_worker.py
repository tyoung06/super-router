"""Run a prompt through `codex exec` on the owner's ChatGPT plan, in workspace/. Text answers only:
every Codex capability beyond text and web search (the shell tool first of all) is switched off,
and the read-only sandbox stays on. The code-mode host stays on because web search runs through
it; `sr probe` re-checks that its JavaScript reaches no file or command. Never an API key: the environment it gets has four names, and
the router refuses to run at all while OPENAI_API_KEY or CODEX_API_KEY is set."""
import os
import subprocess
import tempfile
from pathlib import Path

from router import media, plan_limit, safety

WORKER_TIMEOUT = 600
LOGIN_TIMEOUT = 60
WORKSPACE = safety.WORKSPACE
WEB_SEARCH = ("live", "disabled")
LOGIN_OK = "Logged in using ChatGPT"  # what `codex login status` printed on the owner's Mac, 2026-10-13


class WorkerError(safety.SafeError):
    """The worker refused, failed, or timed out. `code` is `plan_limit` when the call stopped on a
    plan limit (rules v2.15, Resume), else None."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def login_status(run=subprocess.run, environ=os.environ):
    """True only when `codex login status` reports a ChatGPT login. Anything else, including a
    failure to run it, is False, so a call can never fall back to an API key."""
    try:
        proc = run(
            ["codex", "login", "status"],
            capture_output=True,
            text=True,
            timeout=LOGIN_TIMEOUT,
            env=safety.claude_env(environ),
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    text = f"{proc.stdout}\n{proc.stderr}".lower()
    return proc.returncode == 0 and LOGIN_OK.lower() in text


def run(prompt, *, model, web_search, run=subprocess.run, environ=os.environ, files=(), tag=None):
    """One `codex exec` call. The prompt goes on stdin; the answer comes back through
    --output-last-message in a private temp folder that is removed afterwards. With `files`
    ((source, relative name) pairs) the copies go to workspace/task-<tag>/, the call runs there,
    and each image is attached with --image; the folder is removed afterwards."""
    problems = safety.billing_problems(environ)
    if problems:
        raise WorkerError("refused: " + " ".join(problems))
    if web_search not in WEB_SEARCH:
        raise ValueError(f"web_search must be one of {', '.join(WEB_SEARCH)}, not {web_search!r}.")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("the ChatGPT model must be a pinned name (config/agents.json).")
    WORKSPACE.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sr-codex-") as temp:
        out_file = Path(temp) / "last-message.txt"
        if files:
            with media.workspace_copy(tag or "call", files, WORKSPACE) as folder:
                images = [folder / rel for _, rel in files if media.viewable("chatgpt", rel)]
                proc = _call(run, prompt, environ, safety.codex_argv(model, web_search, out_file, images=images, cd=folder), folder)
        else:
            proc = _call(run, prompt, environ, safety.codex_argv(model, web_search, out_file), WORKSPACE)
        limit = plan_limit.codex(proc.returncode, proc.stdout, proc.stderr)
        if limit:
            raise WorkerError(f"plan limit on chatgpt: {limit[:300]}", code=plan_limit.CODE)
        if proc.returncode != 0:
            raise WorkerError(f"codex exited {proc.returncode}: {proc.stderr.strip()[-300:]}")
        answer = out_file.read_text().strip() if out_file.exists() else ""
    if not answer:
        raise WorkerError("codex returned an empty answer")
    return answer


def _call(run, prompt, environ, argv, cwd):
    try:
        return run(argv, input=prompt, capture_output=True, text=True, timeout=WORKER_TIMEOUT,
                   env=safety.claude_env(environ), cwd=cwd)
    except subprocess.TimeoutExpired:
        raise WorkerError(f"codex timed out after {WORKER_TIMEOUT} s") from None
    except OSError as e:
        raise WorkerError(f"could not start codex ({type(e).__name__})") from None
