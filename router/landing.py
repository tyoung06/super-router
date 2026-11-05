"""Land, Undo and Discard (rules 2.40, Project files; build brief 28, decisions 10 to 13; Phase 0, item 7).

Land puts a waiting change into the project's folder as one commit on the branch the task started from: the change's
paths and HANDOFF.md (with the task's entry) and nothing else. Every check comes first and writes nothing: the task waits
to land; the folder is on the task's branch; the branch hasn't changed any of the change's paths since the base (when it
moved over other paths only, the commit goes on top); none of the paths has uncommitted edits and no added path is there
already; nothing the copy never carries and no link; every changed text file passes the redactor and the key scan (a hit
names file and line, never the value). Then the objects and the commit are made off the owner's index
(router/gitops.py), a journal is written beside the log, the branch is moved only if nobody moved it meanwhile, and only
then are the files written and the owner's index entries for exactly those paths set. A land interrupted after the branch
moved is finished by the next land, undo, discard or project command (`recover`); one interrupted before leaves the folder
as it was (loose objects only). Brief 29.1 (decision 1): nothing is written in the folder after the commit: the
committed entry ends `landed` (and the router's tests line), and the card, `sr show` and the log carry the commit's id.
Undo is one more commit putting the land's paths back. Discard drops the copy and writes the one-line `discarded` entry.
Nothing here resets, rebases, amends, forces or collects garbage.
"""
import hashlib
import json
import os
import shlex
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from router import context, copies, gitops, locks, log, projects, safety

HANDOFF = projects.HANDOFF
SPEC_FILE = "SPEC.md"  # brief 33.2 (decision 3): router/spec.py's FILE (spec imports settings alone; the name is kept here)
SUBJECT_CHARS = 60
LANDABLE = ("passed", "fixed", "unchecked", "not_needed")


class Refused(safety.SafeError):
    """Nothing was written: why, never a file's contents."""

    def __init__(self, message, code="land_refused"):
        super().__init__(message)
        self.code = code


@contextmanager
def project_lock(name, *, folder, task_id=None, conn=None, code="land_refused"):
    """One router write in a project at a time (brief 28, `/break-ui`: a double click started two lands): land, undo,
    discard, files in and Turn on undo hold `project-<name>`; another meanwhile is refused at once with nothing written,
    naming the task that holds it when there is one."""
    lock = f"project-{name}"
    try:
        with locks.held(lock, folder=folder, task_id=task_id, wait=False):
            yield
    except locks.Busy:
        found = locks.holder(folder, lock) or {}
        row = log.get_task(conn, found["task_id"]) if conn is not None and found.get("task_id") else None
        who = f" (#{row['n']})" if row else f" ({found['task_id']})" if found.get("task_id") else ""
        raise Refused(f"another land, undo, discard or file change is running in {name}{who}; try again when it "
                      "ends", code) from None


class Partial(safety.SafeError):
    """The branch moved but the folder's files could not all be written; the journal finishes it next time."""
    code = "project_partial"


@dataclass(frozen=True)
class Done:
    commit: str
    branch: str
    paths: list
    folder: Path

    @property
    def short(self):
        return gitops.short(self.commit)


# ---------- the journal ----------

def _journal(journal_dir, folder):
    name = hashlib.sha256(str(Path(folder).resolve()).encode()).hexdigest()[:16]
    return Path(journal_dir) / f"{name}.json"


def _write_journal(journal_dir, folder, record):
    path = _journal(journal_dir, folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".journal-")
    with os.fdopen(fd, "w") as f:
        json.dump(record, f)
    os.replace(temp, path)
    return path


def _apply(folder, commit, paths):
    """Write each path as `commit` holds it (or remove it), then set the owner's index entries for exactly those paths."""
    folder = Path(folder)
    entries = {}
    with gitops.Blobs(["-C", folder]) as blobs:
        for path in paths:
            found = gitops.blob_at(folder, commit, path)
            target = folder / path
            if found is None:
                if target.is_symlink() or target.is_file():
                    target.unlink()
                entries[path] = None
                continue
            mode, sha = found
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temp = tempfile.mkstemp(dir=target.parent, prefix=".sr-land-")
            with os.fdopen(fd, "wb") as f:
                f.write(blobs.read(sha))
            os.chmod(temp, 0o755 if mode == "100755" else 0o644)
            os.replace(temp, target)
            entries[path] = (mode, sha)
    gitops.set_index(folder, entries)


def recover(conn, folder, journal_dir, out=print):
    """Finish what an interrupted land, undo or files commit left (Phase 0, item 7): the branch moved to the new commit,
    so its files are written and its record kept; the branch never moved, so the journal goes. Returns what it did."""
    path = _journal(journal_dir, folder)
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        path.unlink(missing_ok=True)
        return "dropped"
    found = gitops.run(["-C", folder, "rev-parse", "-q", "--verify", f"refs/heads/{record['branch']}"], check=False)
    at = os.fsdecode(found.stdout).strip() if found.returncode == 0 else gitops.ZERO  # no branch yet: a first commit's
    if at == record["new"]:
        if record.get("index_only"):  # an interrupted first commit: the files are the folder's own, only the index is set
            gitops.run(["-C", folder, "read-tree", record["new"]])
        else:
            _apply(folder, record["new"], record["paths"])
        if record.get("task_id") and conn is not None:
            _finish_record(conn, record)
        out(f"Finished an interrupted {record['kind']} in {safety.one_line(projects.tilde(folder))} "
            f"({gitops.short(record['new'])}).")
        path.unlink(missing_ok=True)
        return "finished"
    if at != record["old"]:
        out(f"An interrupted {record['kind']} in {safety.one_line(projects.tilde(folder))} was left as it is: its branch "
            "has moved on since, so its files are yours to check (git status).")
    path.unlink(missing_ok=True)
    return "dropped"


def _finish_record(conn, record):
    row = log.get_task(conn, record["task_id"])
    if row is None or log.project_files_of(row) is None:
        return
    if record["kind"] == "land":
        found = log.project_files_of(row) or {}
        log.update_project_files(conn, record["task_id"], state="landed", commit=record["new"], copy=False)
        copies.remove(found.get("copy_id") or record["task_id"])
    elif record["kind"] == "undo":
        log.update_project_files(conn, record["task_id"], state="undone", undo_commit=record["new"])


def _commit(folder, branch, head, changes, message, journal_dir, kind, task_id=None, fault=None):
    """Objects and the commit off the owner's index, the journal, the branch moved only from `head`, then the files and
    the index entries. `fault` (tests) raises at its named step."""
    commit = gitops.commit_paths(folder, head, changes, message, gitops.identity(folder))
    if fault == "after_objects":
        raise RuntimeError("fault injected after the objects were written")
    paths = sorted(changes)
    journal = _write_journal(journal_dir, folder, {"kind": kind, "task_id": task_id, "folder": str(folder),
                                                   "branch": branch, "old": head, "new": commit, "paths": paths})
    try:
        gitops.move_branch(folder, branch, commit, head, message=message.splitlines()[0])  # issue 10: the subject
    except gitops.GitError:
        journal.unlink(missing_ok=True)
        raise Refused(f"the branch {branch} moved while this ran; nothing was changed. Try again") from None
    if fault == "after_branch":
        raise RuntimeError("fault injected after the branch moved")
    try:
        _apply(folder, commit, paths)
    except (OSError, gitops.GitError) as e:
        raise Partial(f"the commit {gitops.short(commit)} is on {branch} but its files could not all be written "
                      f"({type(e).__name__}); the next land, undo, discard or project command finishes them") from None
    journal.unlink(missing_ok=True)
    return commit


# ---------- the checks ----------

def _first_line(task_text, limit=SUBJECT_CHARS):
    """The task's first line for a commit's subject, at most `limit` characters. Brief 29.1 (issue 6): a longer line is cut
    where a word ends and gains "…", never mid-word (a word longer than the limit alone is cut where the limit falls)."""
    line = safety.one_line(next((x.strip() for x in (task_text or "").splitlines() if x.strip()), ""))
    return cut_at_word(line, limit)


def cut_at_word(text, limit):
    if len(text) <= limit:
        return text
    cut = text[:limit - 1]
    if " " in cut.strip():
        cut = cut[:cut.rstrip().rindex(" ")]
    return cut.rstrip(" ,;:") + "…"


def tests_line(tests):
    """Brief 29.1 (issue 7): the router's line at the end of a landed entry, from the task's latest tests record: the
    doer's words were written before the tests ran."""
    if not tests or tests.get("outcome") == "not_run":
        return f"No tests ran: {(tests or {}).get('why') or 'no test command'}"
    command = shlex.join(tests.get("command") or [])
    return f"Tests passed: `{command}`" if tests.get("outcome") == "passed" else f"Tests failed: `{command}`"


def scan_text(path, data, secrets):
    """Why `data` can't land (a .env value or something shaped like a key), naming the file and line, or None. A file that
    isn't UTF-8 text is not scanned (decision 11: every changed text file)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if safety.redact(text, secrets) != text:
        for n, line in enumerate(text.splitlines(), 1):
            if safety.redact(line, secrets) != line:
                return f"{safety.one_line(path)} line {n} holds a value from .env"
        return f"{safety.one_line(path)} holds a value from .env"
    found = safety.key_like(text)
    if found is not None:
        return f"{safety.one_line(path)} line {found} looks like it holds a key"
    return None


def _repo(folder, branch):
    repo = gitops.inspect(folder)
    if repo.why:
        raise Refused(f"the project's folder can't take a commit: {repo.why}")
    if branch is not None and repo.branch != branch:
        raise Refused(f"the folder is on branch {safety.one_line(repo.branch)}; the task started on "
                      f"{safety.one_line(branch)}. Switch back to {safety.one_line(branch)} first")
    return repo


def _under_link(folder, path):
    """True when a folder on the way to `path` is a link in the project's folder (a write there would follow it)."""
    here = Path(folder)
    for part in Path(path).parts[:-1]:
        here = here / part
        if here.is_symlink():
            return True
    return False


def _clean(folder, paths, added):
    linked = [p for p in paths if _under_link(folder, p) or (p in added and Path(folder, p).is_symlink())]
    if linked:
        raise Refused("these files sit under a link in the folder: " + ", ".join(safety.one_line(p) for p in linked[:8]))
    there = [p for p in added if os.path.lexists(Path(folder) / p)]
    if there:
        raise Refused("these new files are already in the folder: " + ", ".join(safety.one_line(p) for p in there[:8]))
    dirty = gitops.dirty(folder, paths)
    if dirty:
        raise Refused("these files have uncommitted edits in the folder: " + ", ".join(safety.one_line(p) for p in dirty[:8]))


# ---------- Land (decision 11) ----------

# ---------- Land anyway (brief 29.1, decision 21: the checker's fix 7, reopening D1) ----------

ANYWAY = "check not passed"  # the commit message ends `(<task_id>, check not passed)`; the entry `landed (check not passed)`


def anyway_refusal(row, found):
    """Why `sr land <n> --anyway` can't take this task, or None when it can: a file-mode task whose check ended failed
    (FIX after the fix round, or the fix round didn't run), delivered, with its copy kept and a change; a project split
    whose join check failed too. Never a blocked task, a stopped one, a piece or a versus task (the pick is its gate).
    Pure: the JSON's `land_anyway` offer reads it."""
    n = row["n"]
    if not found or found.get("mode") != "on":
        return f"#{n} is not a file-mode task: there is nothing to land"
    if log.is_piece(row):
        return f"#{n} is a piece: only its split lands"
    if found.get("candidates") or found.get("picked") or found.get("versus"):
        return f"#{n} is a versus task: the pick is its gate, so it never lands anyway"
    if found.get("state") == "waiting":
        return f"#{n} waits to land as checked: sr land {n} lands it"
    if found.get("state") in ("landed", "undone", "discarded"):
        return f"#{n} is already {found['state']}"
    if row["check_state"] == log.BLOCKED:
        return f"#{n} was blocked: a blocked task offers Discard only"
    if row["status"] != "done" or row["check_state"] != "failed":
        return f"#{n}'s check didn't fail (it is {row['status']}, {row['check_state'] or 'no check'}): Land anyway is " \
               "for a change whose check failed"
    if not found.get("changed"):
        return f"#{n} changed no file: there is nothing to land"
    if not found.get("copy"):
        return f"#{n}'s copy is gone, so there is nothing to land"
    return None


def land(conn, task_id, entry, *, secrets=(), journal_dir, date, fault=None, anyway=False, extra=None, tests_words=None,
         subject=None, handoff_edit=None):
    """Put the waiting change into the folder as one commit. `entry` is the task's handoff entry from its delivered
    `## Handoff` section (the caller builds it as at delivery); its first line gains `· landed` here and its last line is the
    router's tests line. Nothing is written after the commit (brief 29.1, decision 1). Raises Refused (nothing written) or
    Partial. `anyway` (brief 29.1, decision 21): a change whose check failed, by its own path (anyway_refusal); every
    other check before the commit runs as for any land; the message and the entry say the check didn't pass. `tests_words`
    (brief 33.2, decision 16): the entry's last line in place of the row's own tests line (a run's steps' runs, summed).
    `handoff_edit` (brief 33.4, decision 6): the notes' section, written into HANDOFF.md in this same commit."""
    row = log.get_task(conn, task_id)
    found = log.project_files_of(row) if row is not None else None
    if not found or found.get("mode") != "on":
        raise Refused(f"#{row['n'] if row else '?'} is not a file-mode task: there is nothing to land", "wrong_state")
    if anyway:
        problem = anyway_refusal(row, found)
        if problem:
            raise Refused(problem, "wrong_state")
    elif found.get("state") != "waiting":
        hint = f"; its check didn't pass: sr land {row['n']} --anyway lands it as it is" \
            if anyway_refusal(row, found) is None else ""
        raise Refused(f"#{row['n']} has no change waiting to land (it is {found.get('state')}){hint}", "wrong_state")
    picked = row["mode"] == "relay" and found.get("picked")  # brief 29.1 (decision 9): the pick is a versus task's gate
    if row["check_state"] not in LANDABLE and not picked and not anyway:
        raise Refused(f"#{row['n']}'s check failed: a failed check offers Discard only", "wrong_state")
    cid = found.get("copy_id") or task_id  # a picked versus candidate's copy is `<task_id>-<slot>`
    if not copies.exists(cid):
        raise Refused(f"#{row['n']}'s copy is gone, so there is nothing to land", "wrong_state")
    folder = projects.folder_of(log.project_of(row))
    if folder is None:
        raise Refused(f"project {log.project_of(row)} is no longer registered", "project_unknown")
    recover(conn, folder, journal_dir, out=lambda line: None)
    repo = _repo(folder, found["branch"])
    changed = found.get("changed") or []
    paths = [c["path"] for c in changed]
    added = [c["path"] for c in changed if c["status"] == "added"]
    moved = gitops.changed_since(folder, found["base"], repo.head, paths)
    if moved:
        raise Refused(f"the branch {found['branch']} changed these files since the task started: "
                      + ", ".join(safety.one_line(p) for p in moved[:8]) + ". Discard this change, or run the task again")
    _clean(folder, paths, added)
    changes = {}
    for item in changed:
        path = item["path"]
        if copies.excluded(path):
            raise Refused(f"{safety.one_line(path)} is a path a copy never carries")
        if path == SPEC_FILE:  # brief 33.2 (decision 3): the backstop behind the put-back; it should never fire
            raise Refused("SPEC.md is yours: a change to it never lands (the router puts a build's change to it back); "
                          "discard this change, or run the task again")
        if item["status"] == "deleted":
            changes[path] = None
            continue
        try:
            data = copies.file_bytes(cid, path)
        except (copies.CopyError, OSError) as e:
            raise Refused(str(e)) from None
        problem = scan_text(path, data, secrets)
        if problem:
            raise Refused(problem)
        changes[path] = (copies.file_mode(cid, path), gitops.hash_file(folder, data))
    head, _, rest = entry.strip("\n").partition("\n")
    word = f" · landed ({ANYWAY})" if anyway else " · landed"
    landed_entry = (head.rstrip() + word + ("\n" + rest if rest else "") + "\n"
                    + (tests_words if tests_words is not None else tests_line(found.get("tests"))))
    if anyway:  # brief 30 (A5): in place of the task's `failed:` line, as Undo marks an entry, so the block holds one per task
        handoff_text = projects.replace_entry(projects.read_handoff(folder), row["n"], landed_entry)
    else:
        handoff_text = projects.with_entry(projects.read_handoff(folder), landed_entry)
    if handoff_edit is not None:
        handoff_text = handoff_edit(handoff_text)
    current = gitops.blob_at(folder, repo.head, HANDOFF)
    changes[HANDOFF] = (current[0] if current else "100644", gitops.hash_file(folder, handoff_text.encode("utf-8")))
    for path, data in (extra or {}).items():  # brief 33.1 (decision 14): docs/PLAN.md with the step's tick
        found_at = gitops.blob_at(folder, repo.head, path)
        changes[path] = (found_at[0] if found_at else "100644", gitops.hash_file(folder, data))
    _clean(folder, paths, added)  # once more, just before the branch moves
    # brief 33.2 fix 3: a run's land names the steps that landed (`subject`, auto.land_message), not its row's text
    message = f"sr: {_first_line(subject or row['task'])} ({task_id}{', ' + ANYWAY if anyway else ''})"
    commit = _commit(folder, repo.branch, repo.head, changes, message, journal_dir, "land", task_id, fault)
    lines, start = projects.line_count(handoff_text), projects.block_start(handoff_text)
    copies.remove(cid)
    log.update_project_files(conn, task_id, state="landed", commit=commit, copy=False,
                             **({"anyway": True} if anyway else {}))
    log.add_handoff_write(conn, task_id, {"kind": "land", "text": landed_entry, "lines": lines, "block_start": start,
                                          "state": "landed"})
    return Done(commit, repo.branch, paths, Path(folder))


# ---------- Undo (decision 12) ----------

def land_paths(folder, commit):
    """The paths a land commit changed, HANDOFF.md left out."""
    raw = gitops.out(["-C", folder, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "--no-renames",
                      f"{commit}^", commit])
    return [p for p in (os.fsdecode(x) for x in raw.split(b"\0") if x) if p != HANDOFF]


def undo(conn, task_id, *, journal_dir, date, fault=None, managed=(), extra=None, handoff_edit=None):
    """One new commit putting every path the land changed back as it was before it, and HANDOFF.md with the entry
    marked undone. Raises Refused (nothing written) or Partial. Brief 33.1 (decision 14): `managed` paths (a step's
    docs/PLAN.md) are left out of what is put back, as HANDOFF.md is, and `extra` {path: bytes} written instead. Brief 33.4
    (decision 6b): `handoff_edit` puts the notes' section back, in this same commit."""
    row = log.get_task(conn, task_id)
    found = log.project_files_of(row) if row is not None else None
    if not found or found.get("state") != "landed" or not found.get("commit"):
        raise Refused(f"#{row['n'] if row else '?'} has no landed change to undo"
                      + (" (it was undone already)" if found and found.get("state") == "undone" else ""), "wrong_state")
    folder = projects.folder_of(log.project_of(row))
    if folder is None:
        raise Refused(f"project {log.project_of(row)} is no longer registered", "project_unknown")
    recover(conn, folder, journal_dir, out=lambda line: None)
    repo = _repo(folder, found["branch"])
    landed = found["commit"]
    paths = [p for p in land_paths(folder, landed) if p not in managed]
    moved = gitops.changed_since(folder, landed, repo.head, paths)
    if moved:
        raise Refused("these files changed since the land, so it can't be undone: "
                      + ", ".join(safety.one_line(p) for p in moved[:8]))
    _clean(folder, paths, [])
    changes = {path: gitops.blob_at(folder, f"{landed}^", path) for path in paths}
    short = gitops.short(landed)
    line = f"### #{row['n']} · {date} · undone ({short})"
    handoff_text = projects.replace_entry(projects.read_handoff(folder), row["n"], line)
    if handoff_edit is not None:
        handoff_text = handoff_edit(handoff_text)
    current = gitops.blob_at(folder, repo.head, HANDOFF)
    changes[HANDOFF] = (current[0] if current else "100644", gitops.hash_file(folder, handoff_text.encode("utf-8")))
    for path, data in (extra or {}).items():  # brief 33.1 (decision 14): docs/PLAN.md written again, the step open
        found_at = gitops.blob_at(folder, repo.head, path)
        changes[path] = (found_at[0] if found_at else "100644", gitops.hash_file(folder, data))
    message = f"sr: undo {short}, {_first_line(row['task'], SUBJECT_CHARS - 12)} ({task_id})"
    commit = _commit(folder, repo.branch, repo.head, changes, message, journal_dir, "undo", task_id, fault)
    log.update_project_files(conn, task_id, state="undone", undo_commit=commit)
    lines, start = projects.line_count(handoff_text), projects.block_start(handoff_text)
    log.add_handoff_write(conn, task_id, {"kind": "line", "text": line, "lines": lines, "block_start": start,
                                          "state": "undone"})
    return Done(commit, repo.branch, paths, Path(folder))


# ---------- a commit of the router's own files (brief 33.1, decision 14) ----------

def commit_files(conn, folder, files, message, *, journal_dir, task_id=None):
    """One commit holding `files` ({path: bytes}) alone, on the folder's branch, through the same journal and checked
    branch move as a land (a step delivered with no change: docs/PLAN.md with its tick). Returns Done, or raises Refused
    (nothing written) or Partial."""
    recover(conn, folder, journal_dir, out=lambda line: None)
    repo = _repo(folder, None)
    changes = {}
    for path, data in files.items():
        found_at = gitops.blob_at(folder, repo.head, path)
        changes[path] = (found_at[0] if found_at else "100644", gitops.hash_file(folder, data))
    commit = _commit(folder, repo.branch, repo.head, changes, message, journal_dir, "tick", task_id)
    return Done(commit, repo.branch, sorted(files), Path(folder))


# ---------- an entry with nothing to land (Cleanup 1, 2.5) ----------

@dataclass(frozen=True)
class EntryWrite:
    lines: int            # HANDOFF.md's line count after
    block_start: object
    commit: object        # the commit id, or None when the file was written with no commit
    warning: object       # one line for the owner when a commit was due and didn't happen, else None


def write_entry(conn, folder, n, entry, *, journal_dir):
    """The one way an entry that lands nothing reaches HANDOFF.md, so the folder doesn't read dirty: one commit `sr: entry
    #<n>` holding that file alone, by land's path (the journal, no hooks, the checked branch move, off the owner's index),
    when the file is tracked and was clean before the write. A file with the owner's unsaved edit, no git, or an untracked
    file: written as ever, no commit. A commit that fails never fails the task: the entry is written and the line says so.
    Raises projects.ProjectError when the file itself can't take the entry. The caller holds the project's lock."""
    text = projects.with_entry(projects.read_handoff(folder), entry)
    lines, start = projects.line_count(text), projects.block_start(text)
    why = None
    try:
        recover(conn, folder, journal_dir, out=lambda line: None)
        repo = gitops.inspect(folder)
        current = gitops.blob_at(folder, repo.head, HANDOFF) if repo.git and not repo.why and repo.head and repo.branch else None
        if current is not None and not gitops.dirty(folder, [HANDOFF]):
            text = projects.with_entry(projects.read_handoff(folder), entry)  # recover may have finished a commit of it
            lines, start = projects.line_count(text), projects.block_start(text)
            changes = {HANDOFF: (current[0], gitops.hash_file(folder, text.encode("utf-8")))}
            commit = _commit(folder, repo.branch, repo.head, changes, f"sr: entry #{n}", journal_dir, "entry")
            return EntryWrite(lines, start, commit, None)
    except Partial:  # the commit holds the entry and the next command finishes the file
        return EntryWrite(lines, start, None, f"HANDOFF.md: the entry for #{n} is committed, but the file isn't written yet; "
                                              "the next land, undo or discard in this project finishes it.")
    except (Refused, gitops.GitError, OSError) as e:
        why = type(e).__name__
    lines, start = projects.write_entry(folder, entry)
    words = f"HANDOFF.md: the entry for #{n} is written but not committed ({why}); the folder reads dirty until the next commit."
    return EntryWrite(lines, start, None, words if why else None)


# ---------- Discard (decision 13) ----------

def discard(conn, task_id, *, journal_dir, date, out=None):
    """Drop the change: the copy is removed, the folder is left as it is, and the block gets the one-line `discarded`
    entry (a block write, not a commit). For a change waiting to land, or a failed or stopped task's kept copy."""
    row = log.get_task(conn, task_id)
    found = log.project_files_of(row) if row is not None else None
    if not found or found.get("mode") != "on" or found.get("state") in ("landed", "undone", "discarded"):
        raise Refused(f"#{row['n'] if row else '?'} has no change to discard"
                      + (f" (it is {found.get('state')})" if found and found.get("state") != "none" else ""), "wrong_state")
    if row["status"] in ("queued", "sent"):
        raise Refused(f"#{row['n']} is still open; sr cancel {row['n']} stops it and drops its copy", "wrong_state")
    if not found.get("copy") and found.get("state") != "waiting":
        raise Refused(f"#{row['n']} has no copy to discard", "wrong_state")
    folder = projects.folder_of(log.project_of(row))
    if folder is None:  # brief 29.1 (decision 6): a worktree's scratch log holds main's rows; never drop a real copy
        raise Refused(f"project {log.project_of(row)} is no longer registered", "project_unknown")
    recover(conn, folder, journal_dir, out=lambda line: None)
    if found.get("candidates"):  # brief 29.1 (decision 9): a versus task before its pick owns two copies
        for item in found["candidates"].values():
            copies.remove(item["copy_id"])
    copies.remove(found.get("copy_id") or task_id)
    log.update_project_files(conn, task_id, state="discarded", copy=False)
    line = f"### #{row['n']} · {date} · discarded"
    try:
        wrote = write_entry(conn, folder, row["n"], line, journal_dir=journal_dir)
    except projects.ProjectError:
        return None
    log.add_handoff_write(conn, task_id, {"kind": "line", "text": line, "lines": wrote.lines, "block_start": wrote.block_start,
                                          "state": "discarded"})
    if wrote.warning and out is not None:
        out(wrote.warning)
    return True
