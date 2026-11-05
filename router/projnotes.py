"""A project's notes, Pin to notes and Save to project (rules 2.43, Project context and Project files; build brief 30,
decisions 12 to 14 and the owner's D19).

A project's notes are the part of its `HANDOFF.md` above the router's block, which already rides on every call of the
project. The router writes that part only on the owner's own command: `sr project notes <name> --save` (the page's Notes
editor) replaces it, and `sr project pin` (Pin to notes on a result card) adds a piece of a result at its end. Each holds
the project's lock (refused at once while a land, undo, discard, files in, Turn on undo or another notes write holds it),
re-reads the file, checks `--expect`'s hash, refuses a marker line, a `.env` value, a key or more than
`project_notes_max` characters with nothing written, keeps the router's block byte for byte and the file's own line
endings, and with git and `HANDOFF.md` tracked makes one commit holding `HANDOFF.md` alone (the journal, no hooks, the
project's git name, never rewriting history); otherwise, the router's own folder among them, it writes the file whole and
commits nothing. No entry goes in the block.

`sr project save` (Save to project on a done card) writes a done task's delivered result, without its `## Handoff`
section, into the project as a new `.md` or `.txt` file, as files in does: one commit holding it and `HANDOFF.md` with
the entry `### <date> · saved: <path> (from #<n>)`. Refused with nothing written: a path already there (never
overwritten), a path a copy never carries, text the redactor or the key scan flags (the line, never the value), a project
without git, a task not done, a task with no text result. `save_path` proposes `docs/<slug>.md`."""
import hashlib
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from router import copies, gitops, landing, log, projects, safety, settings
from router import spec as spec_mod
from router.spec import FILE as SPEC_FILE

HANDOFF = projects.HANDOFF
EDITED = "sr: notes edited"
PIN_HEAD = "### Pinned from #{n} ({date})"
SAVED_ENTRY = "### {date} · saved: {path} (from #{n})"
PATH_CHARS = 200
SAVE_SUFFIXES = (".md", ".txt")
SLUG_CHARS = 40
SLUG_WORDS = 6
# Phase 0's call 10: the router's own reply headings never name a saved file (a vote's result opens with `## Answer`)
OWN_HEADINGS = ("answer", "why", "confidence", "missing", "unfinished", "answered", "handoff", "deliverable")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s{0,3}(```|~~~)")


class Refused(landing.Refused):
    """Nothing was written: why (a line number, never a value)."""

    def __init__(self, message, code="project_refused"):
        super().__init__(message, code)


def max_chars():
    return settings.notes_setting("project_notes_max")[0]


def digest(text):
    """The hash `--expect` checks: the first 16 hex characters of the notes part's SHA-256 (`\\n` line endings)."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _strip_end(text):
    """Trailing blank lines (and the last line's newline) dropped; nothing else touched."""
    return re.sub(r"(?:[ \t]*\n)+\Z", "", text).rstrip("\n") if text else ""


@dataclass(frozen=True)
class Parts:
    notes: str          # the owner's part above the router's block, `\n` endings, trailing blank lines dropped
    block: str          # the file from the router's start marker to its end, byte for byte ("" without a block)
    nl: str             # the file's own line ending
    has_block: bool
    exists: bool


def parts_of(text, exists=True):
    """The notes part and the block part of a HANDOFF.md's text. A file without a block is all notes."""
    nl = projects._newline(text or "")
    start, _ = projects._marker_lines(text or "")
    if start is None:
        notes, block = text or "", ""
    else:
        lines = (text or "").splitlines(keepends=True)
        notes, block = "".join(lines[:start]), "".join(lines[start:])
    notes = _strip_end(notes.replace("\r\n", "\n").replace("\r", "\n"))
    return Parts(notes, block, nl, start is not None, exists)


def compose(parts, notes):
    """Decision 12: the file is the text, one blank line, and the block byte for byte, in the file's own line endings (a
    file without a block gets one at its end, as `sr project add` makes it; a missing file is made)."""
    nl = parts.nl
    block = parts.block if parts.has_block else f"{projects.START}{nl}{projects.END}{nl}"
    text = _strip_end((notes or "").replace("\r\n", "\n").replace("\r", "\n"))
    if not text:
        return block
    return text.replace("\n", nl) + nl + nl + block


def problem(notes, secrets, limit=None):
    """Why these notes can't be written, naming the line, never its text; None when they can (decision 12: `sr project
    new`'s checks with `project_notes_max` in place of its 4,000)."""
    limit = max_chars() if limit is None else limit
    return projects.notes_problem(notes, secrets, limit=limit, what="the notes")


def _folder(name):
    try:
        folder = projects.folder_of(name)
    except projects.ProjectError as e:
        raise Refused(str(e)) from None
    if folder is None:
        raise Refused(f"no project {safety.one_line(str(name))}", "project_unknown")
    if not Path(folder).is_dir():
        raise Refused(f"the folder of {name} is not there")
    return Path(folder)


def _read(folder):
    path = projects.handoff_path(folder)
    if not path.exists():
        return parts_of("", exists=False)
    try:
        return parts_of(projects.read_handoff(folder))
    except projects.ProjectError as e:
        raise Refused(str(e)) from None


def _tracked(folder):
    """(the repo, whether a commit can hold HANDOFF.md): git, a branch and a head, not the router's own folder, and
    HANDOFF.md tracked at the head."""
    repo = gitops.inspect(folder)
    ok = bool(repo.git and not repo.why and repo.head and repo.branch and gitops.blob_at(folder, repo.head, HANDOFF))
    return repo, ok


def view(name, *, secrets=()):
    """`sr project notes <name> --json`'s document (decisions 12 and 17): the notes and the router's block (read-only on
    the page), their hash, characters and lines, the cap, and whether a save commits (git, HANDOFF.md tracked)."""
    folder = _folder(name)
    parts = _read(folder)
    repo, tracked = _tracked(folder)
    block = parts.block.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    return {"name": name, "folder": projects.tilde(folder), "notes": parts.notes, "block": block,
            "hash": digest(parts.notes), "chars": len(parts.notes), "lines": len(parts.notes.splitlines()),
            "max": max_chars(), "git": bool(repo.git), "tracked": tracked, "exists": parts.exists,
            "has_block": parts.has_block}


@dataclass(frozen=True)
class Written:
    commit: object      # the commit id, or None when the file was written with no commit
    lines: int          # HANDOFF.md's line count after
    block_start: object
    folder: Path

    @property
    def short(self):
        return gitops.short(self.commit) if self.commit else None


def _write_whole(path, text):
    fd, temp = tempfile.mkstemp(dir=Path(path).parent, prefix=".sr-handoff-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8"))
        os.chmod(temp, (Path(path).stat().st_mode & 0o777) if Path(path).exists() else 0o644)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def _write(conn, name, change, *, expect, secrets, journal_dir, lock_folder, message, fault=None):
    """Under the project's lock: the file re-read, `expect` checked, `change(parts) -> new notes` applied and checked, the
    file composed around the block, then one commit holding HANDOFF.md alone or the file written whole."""
    folder = _folder(name)
    with landing.project_lock(name, folder=lock_folder, conn=conn, code="project_refused"):
        landing.recover(conn, folder, journal_dir, out=lambda line: None)
        parts = _read(folder)
        if expect is not None and digest(parts.notes) != expect:
            raise Refused(f"the notes of {name} changed since you opened them; open them again, then save",
                          "notes_changed")
        notes = change(parts)
        found = problem(notes, secrets)
        if found:
            raise Refused(f"the notes were not saved: {found}")
        text = compose(parts, notes)
        repo, tracked = _tracked(folder)
        path = projects.handoff_path(folder)
        commit = None
        if tracked:
            current = gitops.blob_at(folder, repo.head, HANDOFF)
            changes = {HANDOFF: (current[0], gitops.hash_file(folder, text.encode("utf-8")))}
            commit = landing._commit(folder, repo.branch, repo.head, changes, message, journal_dir, "notes", fault=fault)
        else:
            _write_whole(path, text)
    return Written(commit, projects.line_count(text), projects.block_start(text), folder)


def save(conn, name, text, *, expect=None, secrets=(), journal_dir, lock_folder, fault=None):
    """Decision 12: replace the project's notes with `text`. Returns Written; raises Refused with nothing written."""
    return _write(conn, name, lambda parts: text, expect=expect, secrets=secrets, journal_dir=journal_dir,
                  lock_folder=lock_folder, message=EDITED, fault=fault)


def pinnable(conn, row):
    """Why task `row` can't be pinned, or None (decision 13: an ended task whose card shows a result, tagged or not)."""
    from router import jsonview  # jsonview reads most of the router; kept local
    if row is None:
        return "no such task"
    if not jsonview.state_of(conn, row).ended:
        return f"#{row['n']} is still open: pin from it once it has ended"
    if row["status"] != "done" or not (row["result"] or "").strip():
        return f"#{row['n']} has no result to pin"
    return None


def pin(conn, name, row, text, *, secrets=(), journal_dir, lock_folder, date, fault=None):
    """Decision 13: a blank line, `### Pinned from #<n> (<date>)` and the text at the end of the notes, with decision
    12's checks, lock and commit (`sr: pinned #<n> to the notes`)."""
    why = pinnable(conn, row)
    if why:
        raise Refused(why, "wrong_state")
    piece = _strip_end((text or "").replace("\r\n", "\n").replace("\r", "\n"))
    if not piece.strip():
        raise Refused("there is nothing to pin: the text is empty")
    head = PIN_HEAD.format(n=row["n"], date=date)

    def change(parts):
        return f"{parts.notes}\n\n{head}\n{piece}" if parts.notes else f"{head}\n{piece}"
    return _write(conn, name, change, expect=None, secrets=secrets, journal_dir=journal_dir, lock_folder=lock_folder,
                  message=f"sr: pinned #{row['n']} to the notes", fault=fault)


# ---------- Save to project (decision 14) ----------

def delivered_text(row):
    """What `sr show <n>` prints as a done task's result, without a `## Handoff` section (decision 14), or None."""
    from router import checking, context  # context reads memory and projects; kept local
    text = (row["result"] or "") if row is not None else ""
    if not text.strip():
        return None
    rest, _ = context.split_handoff(text)
    rest = checking.without_next(rest).rstrip("\n")  # brief 33 (decision 6): Save to project never keeps `## Next`
    return rest + "\n" if rest.strip() else None


MISSING_LEFT_OUT, MISSING_KEPT = "left_out", "kept"


def spec_text(text):
    """Cleanup 1 (2.2): (what a result saved as SPEC.md holds, what happened to its `## Missing` section or None). A spec
    rides on every prompt after it, so a note saying it "still needs saving" is left out. `split_missing` takes everything
    from the last such heading to the end, so anything that would lose more than that note keeps the text whole, and says
    so: a heading after the section, a second section, or nothing left but the note. No section: byte for byte."""
    from router import relay  # relay reads context, which reads memory and projects; kept local
    kept, missing = relay.split_missing(text)
    if kept == text:
        return text, None
    if not kept.strip() or relay.split_missing(kept)[0] != kept or _has_heading(missing or ""):
        return text, MISSING_KEPT
    return kept.rstrip("\n") + "\n", MISSING_LEFT_OUT


_ANY_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
_FENCE_LINE = re.compile(r"^\s{0,3}(```|~~~)")


def _has_heading(text):
    fence = None
    for line in text.splitlines():
        m = _FENCE_LINE.match(line)
        if m:
            fence = None if fence == m.group(1) else (fence or m.group(1))
        elif fence is None and _ANY_HEADING.match(line):
            return True
    return False


def savable(conn, row):
    """Why a task's result can't be saved, or None: done, delivered (never a failed or blocked check, but a picked
    `versus` candidate whatever its review said), with a text result."""
    from router import memory  # memory's picked-candidate rule; kept local
    if row is None:
        return "no such task"
    if row["status"] != "done":
        return f"#{row['n']} isn't done (it is {row['status']}): only a done task's result is saved"
    state = row["check_state"]
    picked = bool(memory.PICKED_FAIL.fullmatch(row["check_note"] or ""))
    if state in ("failed", log.BLOCKED) and not picked:
        return f"#{row['n']}'s check didn't pass: a failed or blocked result is never saved"
    if delivered_text(row) is None:
        return f"#{row['n']} has no text result to save"
    return None


def path_problem(path):
    """Why `path` can't name a saved file, or None: relative, inside the folder, `.md` or `.txt`, no part starting with
    `.`, not HANDOFF.md, at most 200 characters, and nothing a copy never carries."""
    if not isinstance(path, str) or not path.strip():
        return "name the file's path"
    if len(path) > PATH_CHARS:
        return f"the path is {len(path):,} characters; at most {PATH_CHARS}"
    if any(unicodedata.category(c) == "Cc" for c in path) or "\\" in path:
        return "the path holds a character a file name can't take here"
    pure = PurePosixPath(path)
    if pure.is_absolute() or path.startswith("~"):
        return "the path must be relative to the project's folder"
    if any(part in ("..", ".") for part in pure.parts):
        return "the path must stay inside the project's folder"
    if any(part.startswith(".") for part in pure.parts):
        return "no part of the path may start with ."
    if pure.suffix.lower() not in SAVE_SUFFIXES:
        return "the file must end .md or .txt"
    if pure.name.casefold() == HANDOFF.casefold() and len(pure.parts) == 1:
        return "HANDOFF.md is the router's notes file, never a saved result"
    why = spec_mod.case_twin(pure.name) if len(pure.parts) == 1 else None
    if why:
        return why
    why = copies.excluded(path)
    if why:
        return f"{path} is a path a project's copy never carries ({why})"
    return None


def save_result(conn, name, row, path, *, secrets=(), journal_dir, lock_folder, date, fault=None):
    """Decision 14: the delivered result into the project as a new file: one commit holding it and HANDOFF.md with its
    entry, as files in does (the lock, the journal, the scan, no hooks). Returns (landing.Done, the entry, HANDOFF.md's
    lines, its block's start, what happened to a `## Missing` section: `spec_text`); raises Refused."""
    why = savable(conn, row)
    if why:
        raise Refused(why, "wrong_state")
    why = path_problem(path)
    if why:
        raise Refused(why)
    path = PurePosixPath(path).as_posix()
    text, missing = spec_text(delivered_text(row)) if path == SPEC_FILE else (delivered_text(row), None)
    data = text.encode("utf-8")
    found = landing.scan_text(path, data, secrets)
    if found:
        raise Refused(found)
    folder = _folder(name)
    with landing.project_lock(name, folder=lock_folder, conn=conn, code="project_refused"):
        landing.recover(conn, folder, journal_dir, out=lambda line: None)
        repo = gitops.inspect(folder)
        if repo.why or not repo.head or not repo.branch:
            raise Refused(f"{name} can't take a saved file: {repo.why or 'it has no commit on a branch'}"
                          + (" (Turn on undo first)" if not repo.git else ""))
        if _under_link(folder, path) or os.path.lexists(folder / path):
            raise Refused(f"{path} is already in the folder (or under a link there); a file is never overwritten")
        entry = SAVED_ENTRY.format(date=date, path=path, n=row["n"])
        handoff = projects.with_entry(projects.read_handoff(folder), entry)
        current = gitops.blob_at(folder, repo.head, HANDOFF)
        changes = {path: ("100644", gitops.hash_file(folder, data)),
                   HANDOFF: (current[0] if current else "100644", gitops.hash_file(folder, handoff.encode("utf-8")))}
        message = "sr: " + landing.cut_at_word(f"saved {path} (from #{row['n']})", landing.SUBJECT_CHARS)
        commit = landing._commit(folder, repo.branch, repo.head, changes, message, journal_dir, "save", fault=fault)
    return (landing.Done(commit, repo.branch, [path], folder), entry, projects.line_count(handoff), projects.block_start(handoff),
            missing)


def _under_link(folder, path):
    here = Path(folder)
    for part in PurePosixPath(path).parts[:-1]:
        here = here / part
        if here.is_symlink():
            return True
    return False


def _slug(text):
    words = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    slug = "-".join(re.findall(r"[a-z0-9]+", words))
    if len(slug) > SLUG_CHARS:
        cut = slug[:SLUG_CHARS + 1]
        slug = cut[:cut.rfind("-")] if "-" in cut else slug[:SLUG_CHARS]
    return slug.strip("-")


def first_heading(text):
    """The result's first heading outside a code fence that isn't one of the router's own reply headings, or None."""
    fence = None
    for line in (text or "").splitlines():
        m = _FENCE.match(line)
        if m:
            fence = None if fence == m.group(1) else (fence or m.group(1))
            continue
        if fence is not None:
            continue
        m = _HEADING.match(line)
        if m and m.group(1).strip().strip("*_`").rstrip(":").strip().lower() not in OWN_HEADINGS:
            return m.group(1)
    return None


def save_path(row):
    """Decision 14: `docs/<slug>.md`, the slug from the result's first heading, else the task's first six words, or
    `task-<n>` when neither gives one."""
    if row is None:
        return None
    heading = first_heading(delivered_text(row) or "")
    slug = _slug(heading) if heading else ""
    if not slug:
        slug = _slug(" ".join((row["task"] or "").split()[:SLUG_WORDS]))
    return f"docs/{slug or 'task-' + str(row['n'])}.md"
