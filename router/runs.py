"""Runs (rules v2.31, Resume and Router for the interface, "Liveness and cancel"; build brief 22, decisions 4 and 5): which
process runs a task. A run writes its process id and that process's own start time on the task row when it starts and
clears them when it ends (log.claim_run, log.release_run). A run is alive when `ps` finds the pid and that pid's process
started at the same second: a pid reused by another process started at another time, so it is not the run, and the
router never signals it. `ps` is run as an argument list with a fixed environment, so its answer is in UTC and in
English whatever this Mac's settings are; nothing here calls a model.

One process may run several tasks in turn (`sr check`, a split's pieces) and may enter the same task twice (a split runs
its integration inside its own command): `claim` and `release` keep a count per task, and only the outermost release
clears the row. `FOLDER` is the run folder beside the log (`run/`), set by main for one command; None writes nothing
there (tests that don't ask for it)."""
import json
import os
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from router import log

PS = ("/bin/ps", "-o", "lstart=", "-p")
PS_ENV = {"TZ": "UTC", "LC_ALL": "C", "PATH": "/bin:/usr/bin"}
PS_TIMEOUT = 5
LSTART = "%a %b %d %H:%M:%S %Y"


class _Unknown:
    """`ps` could not say (it failed, timed out or printed something else): never read as dead, never signalled."""

    def __repr__(self):
        return "UNKNOWN"


UNKNOWN = _Unknown()
FOLDER_NAME = "run"  # beside the log, gitignored: the notes, locks and waits of runs
FOLDER = None   # the run folder beside the log, set by main for one command
_ME = None      # (pid, start time) of this process, read once
_HELD = {}      # task_id -> how many times this process holds its run


def start_time(pid, run=subprocess.run):
    """The process's start time as ISO UTC to the second ("2026-10-21T01:02:02+00:00"), None when no such process exists,
    or UNKNOWN when `ps` could not answer. Only an exit with empty stdout and empty stderr means the process is gone
    (that is what `ps -p` does for a pid nobody has, seen on this Mac); anything `ps` writes to stderr, or an exit that
    is not 0 with something on stdout, is UNKNOWN (the owner's F addition): a run is never judged dead on an answer `ps`
    could not give cleanly."""
    try:
        proc = run([*PS, str(int(pid))], capture_output=True, text=True, timeout=PS_TIMEOUT, env=dict(PS_ENV),
                   stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError, ValueError):
        return UNKNOWN
    text = (proc.stdout or "").strip()
    if (proc.stderr or "").strip():
        return UNKNOWN
    if not text:
        return None
    if proc.returncode != 0:
        return UNKNOWN
    try:
        return datetime.strptime(" ".join(text.split()), LSTART).replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return UNKNOWN


READ = start_time  # how a pid's start time is read (tests hand a fake process table)


def me():
    """(pid, start time) of this process; the start time None when `ps` could not read it (then nothing can signal it)."""
    global _ME
    if _ME is None:
        started = READ(os.getpid())
        _ME = (os.getpid(), started if isinstance(started, str) else None)
    return _ME


def alive(pid, started, read=None):
    """True: the run's process is there with its start time. False: gone, or a reused pid (another start time).
    None: can't tell (`ps` failed, or a pid that is there but has no start time on record to match): treated as alive by
    every caller, and never signalled. A pid with no start time on record that is gone is dead."""
    if pid is None:
        return False
    found = (read or READ)(pid)
    if found is UNKNOWN:
        return None
    if started is None:
        return False if found is None else None
    return found == started


def holder(row):
    """The row's run as (pid, start time), or None when no run holds it."""
    pid = row["pid"] if "pid" in row.keys() else None
    return None if pid is None else (pid, row["run_started_at"])


def mine(row):
    found = holder(row)
    return found is not None and found == me()


def held_elsewhere(row):
    """True when another process's run holds the row and is alive, or can't be judged."""
    found = holder(row)
    if found is None or found == me():
        return False
    return alive(*found) is not False


def dead(row):
    """True when a run holds the row and its process is gone (or the pid now belongs to another process)."""
    found = holder(row)
    return found is not None and found != me() and alive(*found) is False


def adopt(task_id):
    """The row was born with this process's run on it (log.add_task(run=...)): count it held."""
    _HELD[task_id] = _HELD.get(task_id, 0) + 1


def claim(conn, task_id):
    """Hold the task's run for this process: True when it now does (or already did), False when another process holds
    it. The row's pid and start time are written; nothing else on the row changes."""
    if _HELD.get(task_id):
        _HELD[task_id] += 1
        return True
    pid, started = me()
    if log.claim_run(conn, task_id, pid, started):
        _HELD[task_id] = 1
        return True
    return False


def release(conn, task_id):
    """Let go of a run this process holds; the outermost release clears the row (only our own pid and start time)."""
    depth = _HELD.get(task_id, 0)
    if depth == 0:
        return
    if depth > 1:
        _HELD[task_id] = depth - 1
        return
    _HELD.pop(task_id, None)
    pid, started = me()
    try:
        log.release_run(conn, task_id, pid, started)
    except Exception:  # the command is ending; a log it can't write is reported by whatever failed first
        pass


def release_fully(conn, task_id):
    """Let go of a run however many times this process took it (a command ending); the row is cleared once."""
    if _HELD.get(task_id):
        _HELD[task_id] = 1
        if conn is not None:
            release(conn, task_id)
        else:
            _HELD.pop(task_id, None)


def refusal(row):
    """Why a command can't take a task another run holds, in words, or None when it can (`sr resume`, `sr fallback`,
    `sr split --go`, `sr split --skip`)."""
    found = holder(row)
    if found is None or found == me():
        return None
    if alive(*found) is False:
        return f"its run (pid {found[0]}) ended without finishing; run sr check first"
    return f"it is running in another window (pid {found[0]})"


def folder_of(conn):
    """The run folder beside the log this connection has open, or None for a log in memory."""
    for row in conn.execute("PRAGMA database_list"):
        if row[1] == "main":
            return Path(row[2]).parent / FOLDER_NAME if row[2] else None
    return None


def current():
    """The task this process is running now (the last one it took), or None."""
    return next(reversed(_HELD), None) if _HELD else None


@contextmanager
def held(conn, task_id):
    """`with runs.held(conn, task_id) as ok:` hold the run for the block when no other process does."""
    ok = claim(conn, task_id)
    try:
        yield ok
    finally:
        if ok:
            release(conn, task_id)


# ---------- the note of a call in flight (Phase 0 choice 1) ----------
# A local call's row is written only after it returns, so a process that dies during it leaves no row. Just before the
# call, the run writes this note (the call's id, kind, agent, stage and role, its search state and the context and
# memory records it was sent, with the run's pid and start time); once the row is written, the note is removed. `sr check`
# reads a dead run's note to write that call as a process-ended stop with what it was sent, which `sr resume` reuses.

def _subfolder(folder, name):
    path = Path(folder) / name
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    for p in (Path(folder), path):
        os.chmod(p, 0o700)
    return path


def write_note(folder, task_id, record):
    """Write a task's note (owner-only, whole or not at all)."""
    path = _subfolder(folder, "calls") / f"{task_id}.json"
    temp = path.with_name(f".{path.name}.{os.getpid()}")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(record, f, sort_keys=True)
    os.replace(temp, path)
    return path


def read_note(folder, task_id):
    """The task's note, or None (no folder, no note, or one that can't be read)."""
    if folder is None:
        return None
    try:
        found = json.loads((Path(folder) / "calls" / f"{task_id}.json").read_text())
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def drop_note(folder, task_id, call_id=None):
    """Remove the task's note (only when it names `call_id`, when one is given)."""
    if folder is None:
        return
    path = Path(folder) / "calls" / f"{task_id}.json"
    if call_id is not None:
        found = read_note(folder, task_id)
        if found is None or found.get("call_id") != call_id:
            return
    path.unlink(missing_ok=True)


def note_call(task_id, record):
    """Before a local call this process makes on a task it runs: the note, with this run's pid and start time."""
    if FOLDER is None or not _HELD.get(task_id):
        return
    pid, started = me()
    write_note(FOLDER, task_id, {**record, "pid": pid, "started": started,
                                 "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})


def clear_call(task_id, call_id):
    """After the call's row is written (or the call ended without one): its note goes."""
    drop_note(FOLDER, task_id, call_id)


def running(conn, read=None):
    """`sr status --json`'s `running` (decision 4): every row a run holds, with whether its process is alive (None when
    `ps` can't tell) and since when. Reads only."""
    if conn is None:
        return []
    found = []
    for row in log.running_tasks(conn):
        found.append({"n": row["n"], "task_id": row["task_id"], "pid": row["pid"],
                      "alive": alive(row["pid"], row["run_started_at"], read=read), "since": row["run_started_at"]})
    return found
