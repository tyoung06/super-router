"""The router's own probes (rules v2.31, Web search and Cursor; build brief 22, decision 7; the owner's amendment to choice 6):
when a task is about to make a Claude call that may search and the installed Claude Code has no pass, the router runs
Claude's two probes itself; when a Cursor slot is coming and the installed `agent` has no sandbox pass, it runs the two
canaries itself. The probes are the existing ones (`claude_probe`, `web_files_probe`, `cursor_probe`), called, never
rewritten: they run and record a pass or clear it, as `sr probe` does. One probe per tool at a time, by a lock
(router/locks.py); a second task waits on it (`waiting_on: probe`) and goes on with what the first recorded.

A probe that ran and failed a check stays failed for that version until the tool moves (Cursor stays off; Claude runs
without search); `sr probe` in Terminal stays the override. A probe that could not run (a timeout, a process error, no
answer) is tried again by the next task that needs it, at most once an hour per tool and version; meanwhile the task runs
as a failed probe would. Which of the two is recorded beside the pass in `probe_state.json` (`<key>_failure`).

Build brief 24 (decision 10): ChatGPT's safety check runs itself too. A Codex probe pass is kept per Codex version
(`codex_sandbox`), as Cursor's is; before ChatGPT's first call in a command, on a Codex version with no pass, the router
runs the existing `codex_probe` once (one ChatGPT call, one probe at a time by its lock) and goes on only after a pass.
A failure makes ChatGPT unavailable on that version (router/availability.py), and the call that needed it is a failed
call, which the takeover covers. `sr probe` stays the manual override and records what it finds the same way."""
import json
import time
from datetime import datetime, timedelta, timezone

from router import cursor_probe, cursor_worker, locks, runs, search

RETRY = timedelta(hours=1)
RAN_FAILED, COULD_NOT_RUN = "ran_failed", "could_not_run"
CLAUDE_KEYS = (search.SEARCH_KEY, search.WEB_FILES)
CODEX_KEY = "codex_sandbox"  # brief 24 (decision 10): ChatGPT's Codex probe pass, per Codex version
WORDS = {search.SEARCH_KEY: "claude search", search.WEB_FILES: "claude --web files",
         cursor_worker.SANDBOX_KEY: "Cursor's safety check", CODEX_KEY: "ChatGPT's safety check"}
RAN_TO_THE_END = "ran to the end"   # the probes' first check: false when the tool could not run


def _now(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _read(path):
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def failure(path, key):
    """The failure on record for probe `key` ({version, kind, at, reason}), or None."""
    found = _read(path).get(f"{key}_failure")
    return found if isinstance(found, dict) else None


def record_failure(path, key, version, kind, reason, now=None):
    data = _read(path)
    data[f"{key}_failure"] = {"version": version, "kind": kind, "reason": reason,
                              "at": _now(now).isoformat(timespec="seconds")}
    path.write_text(json.dumps(data, indent=2) + "\n")


def clear_failure(path, key):
    data = _read(path)
    if f"{key}_failure" in data:
        del data[f"{key}_failure"]
        path.write_text(json.dumps(data, indent=2) + "\n")


def held_back(path, key, version, now=None):
    """Why probe `key` must not run now on `version` (its failure on record), or None when it may."""
    return held_back_in(_read(path), key, version, now)


def held_back_in(data, key, version, now=None):
    """`held_back` on probe_state.json's contents already read (build brief 24: availability is pure)."""
    found = (data or {}).get(f"{key}_failure")
    if not isinstance(found, dict) or found.get("version") != version:
        return None
    if found.get("kind") == RAN_FAILED:
        return found
    try:
        at = datetime.fromisoformat(found.get("at"))
    except (TypeError, ValueError):
        return None
    return found if _now(now) - at < RETRY else None


def could_not_run(result):
    """A probe result whose tool did not run to the end (a timeout, a process error, no answer)."""
    first = result.first_failure
    return first is not None and first.name.endswith(RAN_TO_THE_END)


def _reason(result):
    first = result.first_failure
    if first is None:
        return "no check ran"
    return f"{first.name}" + (f": {first.detail}" if first.detail else "")


def retry_at(found):
    """When a probe that could not run is tried again, in words: `after 14:05` (local time)."""
    return _retry_at(found)


def _retry_at(found):
    try:
        at = datetime.fromisoformat(found["at"]) + RETRY
    except (KeyError, TypeError, ValueError):
        return "in an hour"
    return f"after {at.astimezone():%H:%M}"


# ---------- Claude: the gate before a call that may search ----------

def claude_gate(state_path, *, folder, out, checks, version=search.claude_version, now=None, sleep=time.sleep):
    """What a command hands its Claude calls as `claude_ready` (asked at most once per command and mode by
    `_ready_once`): True when the probe named by `mode` (search, or the --web file mode) passed on the installed Claude
    Code version. With no pass on that version, and none held back by a failure on record, the router runs every Claude
    probe missing on that version first, one at a time by the lock (decision 7, Phase 0 choice 5). `checks` maps each key
    to a function that makes that probe's `command_check` (main builds them with the config)."""
    def check(mode=None):
        key = mode or search.SEARCH_KEY
        installed = version()
        if installed == "unknown":
            return False
        if search.ready(state_path, installed, key):
            return True
        if held_back(state_path, key, installed, now):
            return False
        with locks.held("probe-claude", folder=folder, task_id=runs.current(), on="probe", sleep=sleep):
            for probe_key in CLAUDE_KEYS:
                if search.ready(state_path, installed, probe_key) or held_back(state_path, probe_key, installed, now):
                    continue  # passed meanwhile (another task probed), or held back
                out(f"probe: {WORDS[probe_key]} has no pass on Claude Code {installed}; probing (one call)")
                result = checks[probe_key]()()
                out(_claude_line(state_path, probe_key, result, now))
        return search.ready(state_path, installed, key)
    return check


def _claude_line(state_path, key, result, now):
    version = result.claude_version
    if result.passed:
        clear_failure(state_path, key)
        return f"probe: {WORDS[key]} passed on Claude Code {version}"
    kind = COULD_NOT_RUN if could_not_run(result) else RAN_FAILED
    if version != "unknown":
        record_failure(state_path, key, version, kind, _reason(result), now)
    what = ("search stays off" if key == search.SEARCH_KEY else "its --web file mode stays off")
    if kind == COULD_NOT_RUN:
        return (f"probe: {WORDS[key]} could not run on Claude Code {version} ({_reason(result)}); {what} for now and "
                f"it is tried again {_retry_at(failure(state_path, key) or {})}")
    return f"probe: {WORDS[key]} FAILED on Claude Code {version} ({_reason(result)}); {what} on this version"


# ---------- Cursor: the readiness check ----------

def cursor_ready(state_path, *, model, folder, out, ready=cursor_worker.ready, check=None,
                 installed=cursor_worker.installed_version, now=None, sleep=time.sleep):
    """What a command asks before any row of a task with a Cursor slot or `@cursor`, and before the first Cursor call in
    a command (decision 7): a Readiness. When the only thing missing is the sandbox pass on the installed `agent`, the
    two canaries run first, one probe at a time by the lock: a pass records the version and the task goes on; a failure
    refuses with `probe_failed` in plain words (never "run sr probe"). Signed out stays `signed_out`."""
    found = ready(state_path)
    if found[0] or getattr(found, "code", None) == "signed_out":
        return found
    version = installed()
    if version == "unknown":
        return cursor_worker.Readiness((False, "Cursor's command line gave no version (is it installed?)"), "probe_failed")
    refused = _cursor_held_back(state_path, version, now)
    if refused:
        return refused
    with locks.held("probe-cursor", folder=folder, task_id=runs.current(), on="probe", sleep=sleep):
        found = ready(state_path)
        if found[0] or getattr(found, "code", None) == "signed_out":
            return found
        refused = _cursor_held_back(state_path, version, now)
        if refused:
            return refused
        out(f"probe: Cursor's safety check has no pass on agent {version}; running its two canaries (two pool calls)")
        result = (check or cursor_probe.command_check(state_path, model=model))()
        if result.standing or result.passed:
            clear_failure(state_path, cursor_worker.SANDBOX_KEY)
            out(f"probe: Cursor's safety check passed on agent {result.agent_version}")
            return ready(state_path)
        if result.skipped:
            code = "signed_out" if "signed in" in result.skipped else "probe_failed"
            return cursor_worker.Readiness((False, f"cursor: {result.skipped}"), code)
        kind = COULD_NOT_RUN if could_not_run(result) else RAN_FAILED
        record_failure(state_path, cursor_worker.SANDBOX_KEY, result.agent_version, kind, _reason(result), now)
        refused = _cursor_held_back(state_path, result.agent_version, now)
        out(f"probe: {refused[1]}")
        return refused


def _cursor_held_back(state_path, version, now):
    found = held_back(state_path, cursor_worker.SANDBOX_KEY, version, now)
    if found is None:
        return None
    if found.get("kind") == RAN_FAILED:
        why = (f"Cursor's safety check failed on agent {version} ({found.get('reason')}); Cursor stays off on this "
               "version")
    else:
        why = (f"Cursor's safety check could not run on agent {version} ({found.get('reason')}); it is tried again "
               f"{_retry_at(found)}")
    return cursor_worker.Readiness((False, why), "probe_failed")


# ---------- ChatGPT: the Codex probe before its first call (build brief 24, decision 10) ----------

def _codex_first_failure(result):
    return next((c for c in result.checks if not c.ok), None)


def record_codex(state_path, result, now=None):
    """What a Codex probe found, kept per Codex version: a pass (any failure cleared), or the failure with its kind
    (`could_not_run` when codex did not run to the end, else `ran_failed`). `sr probe` and the gate both record this way.
    Returns the kind, or None on a pass."""
    version = result.codex_version
    if result.passed:
        search.record_pass(state_path, version, now, key=CODEX_KEY)
        clear_failure(state_path, CODEX_KEY)
        return None
    first = _codex_first_failure(result)
    kind = COULD_NOT_RUN if first is not None and first.name.endswith(RAN_TO_THE_END) else RAN_FAILED
    if version != "unknown":
        reason = "no check ran" if first is None else first.name + (f": {first.detail}" if first.detail else "")
        record_failure(state_path, CODEX_KEY, version, kind, reason, now)
    return kind


def _codex_held(state_path, version, now):
    found = held_back(state_path, CODEX_KEY, version, now)
    if found is None:
        return None
    if found.get("kind") == RAN_FAILED:
        return f"ChatGPT's safety check failed on codex {version} ({found.get('reason')}); ChatGPT stays off on this version"
    return (f"ChatGPT's safety check could not run on codex {version} ({found.get('reason')}); it is tried again "
            f"{_retry_at(found)}")


def chatgpt_gate(state_path, *, folder, out, check, version, now=None, sleep=time.sleep):
    """What a command hands its ChatGPT calls as `chatgpt_ready` (asked once per command, before the first ChatGPT call):
    (True, None) when the Codex probe passed on the installed Codex version. With no pass on it and no failure holding it
    back, the existing probe runs first (`check`, one ChatGPT call), one at a time by the `probe-codex` lock, and the
    answer is what it found. Otherwise (False, why) in plain words, never "run sr probe"."""
    def ready():
        installed = version()
        if installed == "unknown":
            return False, "ChatGPT's command line gave no version (is codex installed?)"
        if search.ready(state_path, installed, CODEX_KEY):
            return True, None
        why = _codex_held(state_path, installed, now)
        if why:
            return False, why
        with locks.held("probe-codex", folder=folder, task_id=runs.current(), on="probe", sleep=sleep):
            if search.ready(state_path, installed, CODEX_KEY):
                return True, None  # passed meanwhile: another task probed
            why = _codex_held(state_path, installed, now)
            if why:
                return False, why
            out(f"probe: ChatGPT's safety check has no pass on codex {installed}; probing (one ChatGPT call)")
            result = check()
            if record_codex(state_path, result, now) is None:
                out(f"probe: ChatGPT's safety check passed on codex {result.codex_version}")
                return True, None
            why = _codex_held(state_path, result.codex_version, now) or (
                f"ChatGPT's safety check failed on codex {result.codex_version}")
            out(f"probe: {why}")
            return False, why
    return ready
