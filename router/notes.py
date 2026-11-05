"""Router notes (rules 2.43, Router notes; build brief 30, decisions 1 to 11).

One file the owner edits on the page, `config/router-notes.md` (this Mac's own, gitignored), sent with every agent call
on a task as the person's standing instructions: `## All agents` to every agent, each agent's own section to that agent,
and `## Planner` to a split's plan call. While the file is missing the router reads the tracked default
(`config/router-notes.default.md`: the six headings and nothing else), so nothing is sent.

The format (decision 2): a section starts at its exact heading line (trailing spaces ignored), in any order, each at most
once; its text runs to the next `## ` line, blank lines at both ends dropped; `###` and deeper are text. Invalid, and
nothing in it is ever sent: text before the first heading, a `## ` line that isn't one of the six, a heading twice, more
than `notes_max` characters, a line holding a `.env` value or one the key scan matches. A problem is named by its line,
never its text.

Read once per task, at intake (decision 4): a valid file with text is kept with the task as `tasks/<task_id>/
router-notes.md` beside the log, and every call on the task sends from that copy (a split's pieces from the split's);
the key scan runs again on what each call is about to send. The block's words are decision 5's; on Grok the notes give
way after the memory block and before the handoff, whole (router/context.py). Only `sr notes save` (and the owner's own
editor) writes the file."""
import hashlib
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from router import locks, safety, settings

PATH = safety.REPO_ROOT / "config" / "router-notes.md"                   # gitignored: this Mac's own
DEFAULT_PATH = safety.REPO_ROOT / "config" / "router-notes.default.md"   # tracked: the six headings, nothing else
NAME, DEFAULT_NAME = "config/router-notes.md", "config/router-notes.default.md"
COPY_NAME = "router-notes.md"   # tasks/<task_id>/router-notes.md: the task's copy (decision 4)
LOCK = "notes"
WHERE = "Setup → Router notes"  # where the owner fixes a refused file (decision 4)

# The six sections (decision 2), in the default's order: (key, heading). The key is what the JSON and the call records use.
SECTIONS = (("all_agents", "All agents"), ("claude", "Claude"), ("chatgpt", "ChatGPT"), ("grok", "Grok"),
            ("cursor", "Cursor"), ("planner", "Planner"))
HEADINGS = {f"## {title}": key for key, title in SECTIONS}
AGENTS = ("claude", "chatgpt", "grok", "cursor")   # each has its own section; Jev never gets one
_HEADING_LINE = re.compile(r"^## ")

# Decision 5: the words, the design chat's.
LEAD = ("Notes from the person who sent this task, kept for every task they send. They are part of this message: follow "
        "them where they fit this task. The task, the instructions after these notes and the reply format win any "
        "conflict.")
OPEN, CLOSE = "--- notes ---", "--- end of notes ---"
JUDGE_LINE = ("When you judge another agent's work, not following the person's notes is never on its own a [must], a fail "
              "or a [high] attack; mention it as a [note] at most. The notes above were written for you; the agent you "
              "judge had its own.")
PLANNER_LEAD = ("How the person likes a task split and its teams picked. The menu and its rules win any conflict: never a "
                "team the menu doesn't offer.")
PLANNER_OPEN, PLANNER_CLOSE = "--- planner notes ---", "--- end of planner notes ---"
GROK_LEFT_OUT = "Grok: router notes left out (over its limit)"   # decision 6: the card's line (router/cardline.py)
GROK_SHARE_LINE = "Grok gets these only on a call they fit."      # decision 7: the editor's line
LEFT_OUT = "grok_limit"                                            # a call record's `left_out`

# Decision 3: who judges and who plans. A judging call is a check, a re-check, a `versus` review or an attack (and the
# re-ask of a review or an attack); a plan call is a split's plan and its re-ask (brief 32's Plan it will take it too).
JUDGE_KINDS, JUDGE_ROLES = ("check", "recheck"), ("review", "attack")
PLAN_ROLES = ("split_plan",)  # router/split.py's PLAN_ROLE


class Refused(safety.SafeError):
    """A notes file the router won't take or send: why, naming the line, never its text. `code` is the reason code."""

    def __init__(self, message, code="notes_invalid", line=None):
        super().__init__(message)
        self.code = code
        self.line = line


@dataclass(frozen=True)
class Parsed:
    text: str                       # the file as read, `\n` line endings
    sections: dict = field(default_factory=dict)   # key -> its text ("" when the section is there and empty)
    problem: str | None = None      # why it is invalid (naming the line), or None
    line: int | None = None
    code: str | None = None         # notes_invalid | notes_key
    default: bool = False           # read from the tracked default (no local file)

    @property
    def state(self):
        if self.problem is not None:
            return "invalid"
        return "set" if any(self.sections.values()) else "blank"

    @property
    def chars(self):
        return {key: len(self.sections.get(key) or "") for key, _ in SECTIONS}

    @property
    def total(self):
        return len(self.text)

    @property
    def hash(self):
        return digest(self.text)

    @property
    def grok_share(self):
        """Decision 7: the all-agents and Grok parts together, the most Grok could be sent."""
        chars = self.chars
        return chars["all_agents"] + chars["grok"]


def digest(text):
    """The hash `--expect` checks (the first 16 hex characters of the text's SHA-256)."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def max_chars():
    return settings.notes_setting("notes_max")[0]


def _normal(text):
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def parse(text, secrets=(), limit=None, *, scan=True):
    """Decision 2, the file's checks in their order: the cap, then each line (text before the first heading, a `## `
    line that isn't one of the six, a heading twice), then a `.env` value by line, then the key scan by line. `scan`
    False reads the sections alone (a task's copy at a send, whose part is scanned on its own: decision 4)."""
    text = _normal(text)
    limit = max_chars() if limit is None else limit
    if len(text) > limit:
        return Parsed(text, problem=f"the router notes are {len(text):,} characters; at most {limit:,}",
                      code="notes_invalid")
    sections, current, seen = {}, None, {}
    lines = text.split("\n")
    for n, line in enumerate(lines, 1):
        if _HEADING_LINE.match(line):
            key = HEADINGS.get(line.rstrip(" \t"))
            if key is None:
                return Parsed(text, problem=f"line {n} is a `## ` heading that isn't one of the six", line=n,
                              code="notes_invalid")
            if key in seen:
                return Parsed(text, problem=f"line {n} repeats a heading (it is first on line {seen[key]})", line=n,
                              code="notes_invalid")
            seen[key], current = n, key
            sections[key] = []
            continue
        if current is None:
            if line.strip():
                return Parsed(text, problem=f"line {n} is text before the first heading", line=n, code="notes_invalid")
            continue
        sections[current].append(line)
    if not scan:
        return Parsed(text, {key: "\n".join(body).strip("\n") for key, body in sections.items()})
    for n, line in enumerate(lines, 1):
        if safety.redact(line, secrets) != line:
            return Parsed(text, problem=f"line {n} holds a value from .env", line=n, code="notes_key")
    found = safety.key_like(text)
    if found is not None:
        return Parsed(text, problem=f"line {found} looks like it holds a key", line=found, code="notes_key")
    return Parsed(text, {key: "\n".join(body).strip("\n") for key, body in sections.items()})


def _read_text(path):
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise Refused("the router notes aren't UTF-8 text") from None


def read(secrets=(), *, path=None, default_path=None):
    """The notes as the router reads them now: the local file, or the default while there is none (decision 1). A file
    that isn't UTF-8, or can't be read, is invalid (no line)."""
    path, default_path = Path(path or PATH), Path(default_path or DEFAULT_PATH)
    use_default = not path.exists()
    try:
        text = _read_text(default_path if use_default else path) if (not use_default or default_path.exists()) else ""
    except Refused as e:
        return Parsed("", problem=str(e), code="notes_invalid", default=use_default)
    except OSError:
        return Parsed("", problem="the router notes could not be read", code="notes_invalid", default=use_default)
    found = parse(text, secrets)
    return Parsed(found.text, found.sections, found.problem, found.line, found.code, use_default)


def view(found, *, grok_limit=None):
    """`sr notes --json`'s and status's `notes` (decision 9): the state (with why and line), each section's characters,
    the total, the cap, Grok's share and limit, and the hash. The text only where the caller adds it."""
    return {"state": found.state, "why": found.problem, "line": found.line, "reason_code": found.code,
            "sections": found.chars, "total": found.total, "max": max_chars(),
            "grok": {"share": found.grok_share, "limit": grok_limit if grok_limit is not None
                     else settings.grok_prompt_limit()[0], "line": GROK_SHARE_LINE},
            "hash": found.hash, "default": found.default}


def save(text, *, expect=None, secrets=(), path=None, default_path=None, lock_folder=None):
    """Decision 8: check the whole text as decision 2 does and either refuse with nothing written (Refused: the line,
    never its text) or write the file whole, a temp file then a rename, mode 600, under the `notes` lock. `expect` is the
    hash `sr notes` gave: a file changed since is refused (`notes_changed`). Returns the Parsed text written."""
    path = Path(path or PATH)
    found = parse(text, secrets)
    if found.problem is not None:
        raise Refused(f"the router notes were not saved: {found.problem}", found.code, found.line)
    with locks.held(LOCK, folder=lock_folder):
        if expect is not None:
            now = read(secrets, path=path, default_path=default_path)
            if now.hash != expect:
                raise Refused("the router notes changed since you opened them; open them again, then save",
                              "notes_changed")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".router-notes-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                os.fchmod(f.fileno(), 0o600)
                f.write(found.text)
            os.replace(temp, path)
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise
        os.chmod(path, 0o600)
    return found


# ---------- the task's copy (decision 4) ----------

def copy_path(folder, task_id):
    return Path(folder) / "tasks" / task_id / COPY_NAME


def keep_copy(folder, task_id, found):
    """The notes kept with a new task: `tasks/<task_id>/router-notes.md`, owner-only, created once. Only a file with
    text is kept (a blank one sends nothing either way). None (nothing kept) for a log in memory."""
    if folder is None or found is None or found.state != "set":
        return None
    target = copy_path(folder, task_id)
    for d in (target.parent.parent, target.parent):
        d.mkdir(mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(found.text)
    return target


def copy_of(folder, task):
    """The copy a call on `task` sends from: its own, or its split's for a piece (decision 4). (the copy's text, its
    task id) or (None, None) when there is none: a task from before brief 30, a blank file at intake, a log in memory."""
    if folder is None or task is None:
        return None, None
    keys = task.keys() if hasattr(task, "keys") else task
    owner = (task["parent"] if "parent" in keys and task["parent"] else None) or task["task_id"]
    target = copy_path(folder, owner)
    try:
        return _normal(target.read_text(encoding="utf-8")), owner
    except (OSError, UnicodeDecodeError):
        return None, None


def record_of(text):
    """A task's `notes` in the JSON (decision 9): its copy's hash and characters, or None."""
    return None if text is None else {"hash": digest(text), "chars": len(text)}


# ---------- what a call gets (decisions 3 and 5) ----------

def judging(kind, role):
    return kind in JUDGE_KINDS or role in JUDGE_ROLES


def planning(kind, role):
    return role in PLAN_ROLES


def part_for(sections, agent, *, judge=False, plan=False):
    """(the text that goes first in the prompt, ending in one blank line; the call's record). ("", None) when nothing is
    sent: then the prompt is byte for byte as before. The block holds `## All agents` and the calling agent's own
    section; a judging call adds the judge line after it; a plan call adds the planner part (after the lead when the
    agent has no block of its own)."""
    sections = sections or {}
    shared = sections.get("all_agents") or ""
    own = (sections.get(agent) or "") if agent in AGENTS else ""
    planner = (sections.get("planner") or "") if plan else ""
    if not (shared or own or planner):
        return "", None
    parts, record = [], {"sections": {}, "judge": False, "planner": False}
    if shared or own:
        body = [LEAD, OPEN, *([shared] if shared else []), *([""] if shared and own else []), *([own] if own else []),
                CLOSE]
        parts.append("\n".join(body))
        if shared:
            record["sections"]["all_agents"] = len(shared)
        if own:
            record["sections"][agent] = len(own)
        if judge:
            parts.append(JUDGE_LINE)
            record["judge"] = True
    else:
        parts.append(LEAD)
    if planner:
        parts.append("\n".join([PLANNER_LEAD, PLANNER_OPEN, planner, PLANNER_CLOSE]))
        record["sections"]["planner"] = len(planner)
        record["planner"] = True
    text = "\n\n".join(parts) + "\n\n"
    record["chars"] = len(text)
    return text, record


def for_call(folder, task, agent, *, kind=None, role=None):
    """What one call on `task` by `agent` gets from the task's copy: (text, record), ("", None) without a copy. Raises
    Refused (`notes_key`) when the key scan matches what it is about to send (decision 4's scan on send)."""
    text, owner = copy_of(folder, task)
    if text is None:
        return "", None
    sections = parse(text, limit=len(text), scan=False).sections  # checked at intake; scanned again below, as sent
    from router import filecalls  # it reads copies and git; kept local
    plans = planning(kind, role) or filecalls.plan_call(task, kind, role, agent)  # brief 33.1 (decision 3): Plan's calls
    part, record = part_for(sections, agent, judge=judging(kind, role), plan=plans)
    if part:
        found = safety.key_like(part)
        if found is not None:
            raise Refused(f"the router notes kept with this task look like they hold a key (line {found} of what "
                          f"would be sent); nothing was sent. Fix it in {WHERE}", "notes_key", found)
        record["from"] = owner
    return part, record


def left_out(record):
    """Decision 6: the call record of notes left out of a Grok call, whole, for its limit."""
    return {"left_out": LEFT_OUT, "chars": (record or {}).get("chars", 0), "from": (record or {}).get("from")}
