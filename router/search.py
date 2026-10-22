"""Web search on a call (rules v2.22, Web search). Claude and ChatGPT may search on every call they make, decided
here in code by whether the call carries a file and whether the task was sent with --web, never by the model, the
task text or the agent's choice: a call with a file has no search unless the task has --web. Claude gets WebSearch
only (no page fetching, no other tool; on a --web file call, Read in its copy folder too) and only after `sr probe`
passed on the installed Claude Code version. Grok: the router never switches its search on or off (None).
"""
import json
import re
import subprocess
from datetime import datetime, timezone

from router import log

MAX_SEARCHES = 5                    # asked for in the prompt; more is logged, never refused (the owner)
ALLOWED = "allowed"
OFF_PROBE = "off (probe not passed)"
OFF_FILE = "off (file without --web)"  # the addendum's D6: every Claude or ChatGPT call row records its state
OFF_WEB_FILES = "off (--web file probe not passed)"  # The owner's D9: Claude's --web file mode needs its own probe pass
STATES = (ALLOWED, OFF_PROBE, OFF_FILE, OFF_WEB_FILES)
SEARCH_KEY = "claude_search"   # probe_state.json: the search probe's pass (brief 8)
WEB_FILES = "claude_web_files"  # probe_state.json: the --web file probe's pass (brief 15 addendum, D9)
SEARCH_AGENTS = ("claude", "chatgpt")
_VERSION_TIMEOUT = 30


def _get(task, key):
    try:
        return task[key]
    except (KeyError, IndexError):
        return None


def allowed(task, *, files=(), kind=None, role=None):
    """True on every call, unless it carries a file and the task was not sent with --web (rules v2.22). `kind`
    and `role` are taken and ignored: no preset, role or kind condition remains."""
    return not files or log.web_of(task)


def state(task, *, kind, role, agent, files, ready):
    """The search state of one call by Claude or ChatGPT: `allowed`; `off (file without --web)`; or for Claude
    `off (probe not passed)` when `ready()` (the probe gate, asked only when it matters) says no, and on a --web
    file call `off (--web file probe not passed)` when `ready(WEB_FILES)` says no (the owner's D9: ChatGPT's half
    still works). None for Grok (and any other agent): the router does nothing about its search, nothing is logged."""
    if agent not in SEARCH_AGENTS:
        return None
    if not allowed(task, files=files):
        return OFF_FILE
    if agent == "claude":
        if not ready():
            return OFF_PROBE
        if files and not ready(WEB_FILES):
            return OFF_WEB_FILES
    return ALLOWED


# ---------- the probe gate: a pass is kept per Claude Code version ----------

def claude_version(run=subprocess.run):
    """The installed Claude Code version ("2.1.301"), or "unknown"."""
    try:
        proc = run(["claude", "--version"], capture_output=True, text=True, timeout=_VERSION_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    found = re.search(r"\d+\.\d+\.\d+", proc.stdout or "") if proc.returncode == 0 else None
    return found.group(0) if found else "unknown"


def _read(path):
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def ready(path, installed, key=SEARCH_KEY):
    """True only when `sr probe`'s check named `key` (the search check, or the --web file check) passed on this
    exact Claude Code version."""
    entry = _read(path).get(key)
    return installed != "unknown" and isinstance(entry, dict) and entry.get("version") == installed


def passed_version(path, key):
    """The version the check named `key` passed on, or None (no file, no entry, a malformed one). Build brief 20 reads
    the Cursor sandbox pass with it (router/cursor_worker.py, `cursor_sandbox`)."""
    entry = _read(path).get(key)
    return entry.get("version") if isinstance(entry, dict) and isinstance(entry.get("version"), str) else None


def record_pass(path, version, now=None, key=SEARCH_KEY):
    data = _read(path)
    data[key] = {"version": version, "passed_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")}
    path.write_text(json.dumps(data, indent=2) + "\n")


def clear(path, key=SEARCH_KEY):
    data = _read(path)
    if key in data:
        del data[key]
        path.write_text(json.dumps(data, indent=2) + "\n")


def ready_check(path, run=subprocess.run):
    """What `main` hands the commands: a function that answers the probe gate for the installed version (asked
    once per command and mode, only on a Claude call that may search). `mode` WEB_FILES asks the --web file
    probe's pass instead of the search probe's."""
    def check(mode=None):
        return ready(path, claude_version(run), key=mode or SEARCH_KEY)
    return check
