"""Is each agent reachable (rules v2.30, Money and Status and JSON; build brief 21, decision 8)? Never a prompt to a
model and never the webhook: Claude's check is `claude auth status` (Phase 0, C1: it answers signed in or not in a
fraction of a second, which `--version` cannot), ChatGPT's `codex login status`, Cursor's `agent status`, Grok's a read
of the inbox repo. Each answers (online, reason). A check returns only that pair, never its output: `claude auth
status` prints the account's email and organization, which never leave this module. `sr status` runs the four
fresh, side by side; `sr serve` keeps them a minute (router/page.py). Build brief 24 (decision 1): each answer carries a code
beside the pair (`Answer`), so availability reads why an agent can't be used without parsing words: `signed_out`,
`unreachable` (the check did not answer) or `not_configured` (Claude signed in some other way than the plan)."""
import json
import os
import subprocess
import threading
from datetime import datetime, timezone

from router import chatgpt_worker, cursor_worker, safety, settings

TIMEOUT = 15             # seconds per check; a slower check reads offline
PLAN_AUTH = "claude.ai"  # `authMethod` of a plan login (Phase 0: "claude.ai" signed in, "none" signed out)
CODES = ("signed_out", "unreachable", "not_configured")


class Answer(tuple):
    """(online, reason), equal to the plain pair, with `code` beside it when the agent is offline (build brief 24)."""

    def __new__(cls, pair, code=None):
        made = super().__new__(cls, pair)
        made.code = code
        return made


def _code(found, default):
    """A check's code: the one it gave, else `default` for an offline answer, else None."""
    if found[0]:
        return None
    given = getattr(found, "code", None)
    return given if given in CODES else default


def claude(run=subprocess.run, environ=os.environ):
    """Online when `claude auth status` exits 0 and says logged in with the plan. Run with the four-name environment the
    worker gets, so no key in the shell can reach it."""
    try:
        proc = run(["claude", "auth", "status"], capture_output=True, text=True, timeout=TIMEOUT,
                   env=safety.claude_env(environ), stdin=subprocess.DEVNULL)
    except (subprocess.TimeoutExpired, OSError) as e:
        return Answer((False, f"claude auth status did not answer ({type(e).__name__})"), "unreachable")
    try:
        doc = json.loads(proc.stdout or "")
    except ValueError:
        doc = None
    if not isinstance(doc, dict):
        return Answer((False, "claude auth status gave no answer"), "unreachable")
    if doc.get("loggedIn") is not True or proc.returncode != 0:
        return Answer((False, "not signed in (claude auth login)"), "signed_out")
    method = doc.get("authMethod")
    if method != PLAN_AUTH:
        return Answer((False, f"signed in with {safety.one_line(str(method))}, not the Claude plan"), "not_configured")
    return Answer((True, None))


def chatgpt(login=chatgpt_worker.login_status):
    """Online when `codex login status` reports a ChatGPT login (the check the ChatGPT worker already makes)."""
    return Answer((True, None)) if login() else Answer((False, "not signed in with ChatGPT (codex login)"), "signed_out")


def cursor(check=cursor_worker.online):
    """Online when `agent status` says signed in (build brief 20). A check that did not answer is `unreachable`, never a
    sign-out (brief 23, choice 18)."""
    found = tuple(check())
    if found[0]:
        return Answer(found)
    return Answer(found, "unreachable" if "did not answer" in (found[1] or "") else "signed_out")


def grok(run=subprocess.run):
    """Online when the inbox repo answers a read (`gh api repos/<inbox>`): the repo Grok Bot's results land in. The
    webhook is never called by a check. The repo is the setting (brief 24, decision 11); GitHub answers its full name in
    its own case, so the two are compared without case."""
    repo, problem = settings.inbox_repo()
    if repo is None:
        return Answer((False, problem), "not_configured")
    try:
        proc = run(["gh", "api", f"repos/{repo}", "--jq", ".full_name"], capture_output=True, text=True,
                   timeout=TIMEOUT, stdin=subprocess.DEVNULL)
    except (subprocess.TimeoutExpired, OSError) as e:
        return Answer((False, f"the inbox repo did not answer ({type(e).__name__})"), "unreachable")
    if proc.returncode == 0 and (proc.stdout or "").strip().lower() == repo.lower():
        return Answer((True, None))
    return Answer((False, "the inbox repo did not answer (gh)"), "unreachable")


CHECKS = {"claude": claude, "chatgpt": chatgpt, "grok": grok, "cursor": cursor}


def run_all(checks, now=None):
    """{agent: {"online", "reason", "checked_at", "code"}} from {agent: check}, the checks side by side, each at most
    TIMEOUT seconds more. A check that raises reads offline by its type; one still running at the end reads offline too;
    both are `unreachable` (brief 24). The owner's decision 2 after F: a check that didn't answer (`unreachable`) is run once
    more, side by side with any other such check; its second answer is the one kept."""
    found = _run_once(checks, now)
    again = {name: checks[name] for name in checks if found[name]["code"] == "unreachable"}
    if again:
        found.update(_run_once(again, now))
    return found


def _run_once(checks, now=None):
    results, threads = {}, []

    def one(name, check):
        try:
            found = check()
            ok, reason = found
            code = _code(found, "unreachable")
        except Exception as e:  # a check that blows up is an offline agent, never a crash of `sr status`
            ok, reason, code = False, f"check failed ({type(e).__name__})", "unreachable"
        results[name] = (bool(ok), None if ok else reason, None if ok else code)

    for name, check in checks.items():
        thread = threading.Thread(target=one, args=(name, check), daemon=True)
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join(TIMEOUT + 5)
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    found = {}
    for name in checks:
        ok, reason, code = results.get(name, (False, "the check did not finish", "unreachable"))
        found[name] = {"online": ok, "reason": reason, "checked_at": stamp, "code": code}
    return found
