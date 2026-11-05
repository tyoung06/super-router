"""Plan limits (rules v2.15, Resume): how each worker tells a plan-limit stop from any other
failure, and the test-only injected limit.

A plan limit gets the code `plan_limit` on its call row; only that code makes a stop resumable.
The texts below were read from the installed tools' own code on 2026-10-15, never seen live
(READ_FROM). A tool update can change them: they live here only, and tests/test_plan_limit.py
holds them as the answer key.
"""
import json
import re
import subprocess
from pathlib import Path

CODE = "plan_limit"
READ_FROM = {"claude": "2.1.301", "codex": "0.162.1"}

# Claude's own list of the openings of a "you can't go on" message (its usage-limit detector),
# for the plan login: session, weekly and per-model limits, and being out of usage credits.
CLAUDE_OPENINGS = (
    "You've hit your",
    "You've reached your",
    "You're out of usage credits",
    "You're out of extra usage",
    "Your seat type doesn't include usage",
    "Your usage allocation has been disabled by your admin",
)
# On exit 0 only the plain limit line counts, so an answer that starts the same way stays an answer.
_CLAUDE_EXIT_0 = re.compile(r"You've hit your [A-Za-z0-9 -]{1,40}? limit(?: · [^\n]*)?")
CODEX_MARK = "hit your usage limit"   # "You've hit your usage limit. ... try again at <time>."
# Brief 30 (A4): a Cursor call stopped by the X Subscription's weekly pool. Never seen live: the names are the error codes
# the installed agent's own code carries for a used-up allowance (2026.10.22-27dcf5f: `FREE_USER_USAGE_LIMIT`,
# `PRO_USER_USAGE_LIMIT`) and the plain words such a limit is said in. A pool stop is never resumable (rules v2.28): this only
# picks the refusal's words. [GUESS] until a pool stop is seen.
CURSOR_POOL = re.compile(r"(?i)usage[_ ]limit|out of usage|weekly limit|weekly pool")
_TIMEOUT = 30


def _plain(text):
    """Curly apostrophes as straight ones, so either spelling matches."""
    return (text or "").replace("’", "'")


def claude(returncode, stdout, stderr):
    """The limit line when a `claude -p` call stopped on a plan limit, else None. On a non-zero exit
    any line of either stream that opens like one of Claude's own limit messages counts; on exit 0
    only an answer that is that one line and nothing else."""
    if returncode == 0:
        text = _plain(stdout).strip()
        return text if _CLAUDE_EXIT_0.fullmatch(text) else None
    for line in (_plain(stdout) + "\n" + _plain(stderr)).splitlines():
        line = line.strip()
        if line.startswith(CLAUDE_OPENINGS):
            return line
    return None


def codex(returncode, stdout, stderr, prompt=""):
    """The limit line when a `codex exec` call stopped on a plan limit, else None. Exit 0 is an
    answer (it is read from the output file), never a limit. Codex echoes the prompt into its output, so a line that is one
    of the prompt's own lines isn't read: a task about usage limits isn't a limit (Cleanup 2, row 4). By whole lines, since a
    short prompt can sit inside a real limit line ("hi" in "You've hit").
    [GUESS: Codex echoes the prompt unchanged, as failure_text assumes; an echo it changed reads as it did before this fix.]"""
    if returncode == 0:
        return None
    asked = {line.strip() for line in _plain(prompt).splitlines()}
    for line in (_plain(stdout) + "\n" + _plain(stderr)).splitlines():
        if CODEX_MARK in line.lower() and line.strip() not in asked:
            return line.strip()
    return None


# ---------- the injected limit: test-only, scratch log only ----------

AGENTS = ("claude", "chatgpt")
ENV_NAME = "SR_INJECT_PLAN_LIMIT"
# What each tool prints at its limit (the answer-key texts), and the stream it uses.
_INJECTED = {
    "claude": {"returncode": 1, "stdout": "You've hit your session limit · resets 3pm (injected for a test)\n",
               "stderr": ""},
    "chatgpt": {"returncode": 1, "stdout": "",
                "stderr": "ERROR: You've hit your usage limit. Try again later. (injected for a test)\n"},
}


def _injected_reply(agent, argv):
    """The injected limit as the tool would print it for this call. Brief 24 (F): a Claude search call runs with
    `--output-format stream-json`, so its limit comes as the stream's result event (an error), as the worker reads it;
    every other call gets the plain text."""
    reply = dict(_INJECTED[agent])
    if agent == "claude" and "stream-json" in argv:
        line = reply["stdout"].strip()
        reply["stdout"] = json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": line}) + "\n"
    return reply


class InjectRefused(Exception):
    """The injected limit was asked for where it is not allowed. Nothing ran."""


def main_checkout(root, run=subprocess.run):
    """The main checkout's folder (the one whose router.db is the real log), from git's common
    folder, or None when git can't say."""
    try:
        proc = run(["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                   capture_output=True, text=True, timeout=_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        return None
    return Path(out).resolve().parent


def is_real_log(db_path, *, root, run=subprocess.run):
    """True when `db_path` is the real log (router.db in the main checkout), and also when that
    can't be told, so the hook fails closed."""
    main = main_checkout(root, run=run)
    if main is None:
        return True
    return Path(db_path).resolve() == (main / "router.db").resolve()


OVERDUE_ENV = "SR_INJECT_OVERDUE"  # build brief 24: a Grok call logged 2 × grok_timeout_minutes early


def overdue_minutes(value, db_path, n, *, root, run=subprocess.run):
    """The test-only overdue hook (build brief 24, C8): how many minutes early this command logs each Grok send, so
    whichever process checks next reads the call overdue. `value` names grok, the only agent with an overdue; `n` is
    grok_timeout_minutes. Raises InjectRefused on the real log, for any other value, or without an N."""
    if value != "grok":
        raise InjectRefused(f"{OVERDUE_ENV} names grok, not {value!r}.")
    if not n:
        raise InjectRefused(f"{OVERDUE_ENV} needs grok_timeout_minutes in config/settings.json.")
    if is_real_log(db_path, root=root, run=run):
        raise InjectRefused(f"{OVERDUE_ENV} is test-only and works only on a scratch log; this is the real log "
                            "(router.db in the main checkout), or git could not say which log it is.")
    return 2 * n


def injected(agent, db_path, *, root, run=subprocess.run):
    """The test-only hook: returns a function that wraps a subprocess runner so the next call by
    `agent` returns that tool's plan-limit text, and every later call goes through. The worker's
    own detector then sees the limit, as it would a real one. Raises InjectRefused on the real log
    or for any agent but claude and chatgpt."""
    if agent not in AGENTS:
        raise InjectRefused(f"{ENV_NAME} names claude or chatgpt, not {agent!r}.")
    if is_real_log(db_path, root=root, run=run):
        raise InjectRefused(f"{ENV_NAME} is test-only and works only on a scratch log; this is the real log "
                            "(router.db in the main checkout), or git could not say which log it is.")

    def wrap(real_run):
        state = {"used": False}

        def one_shot(argv, **kwargs):
            if state["used"]:
                return real_run(argv, **kwargs)
            state["used"] = True
            return subprocess.CompletedProcess(argv, **_injected_reply(agent, argv))
        return one_shot
    return wrap


FAIL_ENV = "SR_INJECT_FAIL"  # build brief 32 (D's step 4): Cursor's next call fails, on a scratch log only
FAIL_AGENTS = ("cursor",)
# What the failed call returns: exit 1, nothing on stdout, one line on stderr (never the weekly pool's words)
_FAILED = {"cursor": {"returncode": 1, "stdout": "", "stderr": "an injected failure for a test (SR_INJECT_FAIL=cursor)\n"}}


def failing(agent, db_path, *, root, run=subprocess.run):
    """The test-only failure hook (build brief 32, D's step 4): returns a function that wraps a subprocess runner so
    `agent`'s next call ends as a failed call, and every later call goes through. The worker's own reading fails it
    (`agent exited 1: …`), as it would a real failure. Raises InjectRefused on the real log or for any agent but
    cursor (Claude's and ChatGPT's stops are the plan-limit hook's)."""
    if agent not in FAIL_AGENTS:
        raise InjectRefused(f"{FAIL_ENV} names cursor, not {agent!r}.")
    if is_real_log(db_path, root=root, run=run):
        raise InjectRefused(f"{FAIL_ENV} is test-only and works only on a scratch log; this is the real log "
                            "(router.db in the main checkout), or git could not say which log it is.")

    def wrap(real_run):
        state = {"used": False}

        def one_shot(argv, **kwargs):
            if state["used"]:
                return real_run(argv, **kwargs)
            state["used"] = True
            return subprocess.CompletedProcess(argv, **_FAILED[agent])
        return one_shot
    return wrap


QUESTIONS_ENV = "SR_INJECT_QUESTIONS"  # build brief 33.4 (decision 17): a plan's stage 1 asks, on a scratch log only


def questions_injected(value, db_path, *, root, run=subprocess.run):
    """The test-only questions hook (build brief 33.4, decision 17): `plan` makes this command's new plan answer stage 1
    with three fixed questions, in place of the model call. Raises InjectRefused on the real log or for any other value."""
    if value != "plan":
        raise InjectRefused(f"{QUESTIONS_ENV} names plan, not {value!r}.")
    if is_real_log(db_path, root=root, run=run):
        raise InjectRefused(f"{QUESTIONS_ENV} is test-only and works only on a scratch log; this is the real log "
                            "(router.db in the main checkout), or git could not say which log it is.")
    return True


def cursor_pool(text):
    """Brief 30 (A4): whether a stopped Cursor call's words (its row's text) say the weekly pool stopped it."""
    return bool(CURSOR_POOL.search(text or ""))
