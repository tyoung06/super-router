"""One at a time, by a lock file (rules v2.31, Web search, Cursor and Memory "Down"; build brief 22, decisions 7 and 8;
Phase 0 choice 4): one probe per tool and one memory start at a time, across every `sr` command on this Mac.

A lock is a file under the run folder beside the log (`run/locks/<name>.lock`, gitignored, owner-only) held with
`fcntl.flock`: the operating system lets go of it the moment its holder's process ends, crash included, so a lock is
never stale and nothing has to judge one. The file's text (the holder's pid and start time, since when, for which task)
is written while it is held, only so `sr status` can say a start is running; it never decides who holds the lock.

While a task waits for a lock, or holds one to probe or to start the store, its process writes
`run/waits/<task_id>.json` (what it waits on: `probe` or `memory`), removed when it is done. `waiting_on` reads it for a
JSON read, and only when the note's pid and start time are the task row's own run, so a note a dead run left behind
means nothing."""
import fcntl
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from router import runs

POLL_SECONDS = 1.0
WAITS = ("probe", "memory")


def _folder(base, name):
    path = Path(base) / name
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    for p in (Path(base), path):
        os.chmod(p, 0o700)
    return path


def lock_path(folder, name):
    return Path(folder) / "locks" / f"{name}.lock"


def _write_wait(folder, task_id, on, name):
    pid, started = runs.me()
    path = _folder(folder, "waits") / f"{task_id}.json"
    temp = path.with_name(f".{path.name}.{os.getpid()}")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"on": on, "lock": name, "pid": pid, "started": started}, f, sort_keys=True)
    os.replace(temp, path)


def _clear_wait(folder, task_id):
    (Path(folder) / "waits" / f"{task_id}.json").unlink(missing_ok=True)


@contextmanager
def held(name, *, folder, task_id=None, on=None, sleep=time.sleep, poll=POLL_SECONDS):
    """Hold lock `name` for the block, waiting (polling, so Ctrl+C still works) while another process holds it. With
    `task_id` and `on`, the task shows `waiting_on: <on>` from the moment it starts waiting until the block ends. No
    folder (a test with no run folder): nothing to share, the block just runs."""
    if folder is None:
        yield
        return
    path = _folder(folder, "locks") / f"{name}.lock"
    if task_id and on:
        _write_wait(folder, task_id, on, name)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                sleep(poll)
        pid, started = runs.me()
        os.ftruncate(fd, 0)
        os.pwrite(fd, json.dumps({"pid": pid, "started": started, "task_id": task_id,
                                  "since": datetime.now(timezone.utc).isoformat(timespec="seconds")}).encode(), 0)
        try:
            yield
        finally:
            os.ftruncate(fd, 0)
    finally:
        os.close(fd)  # closing the file lets go of the lock
        if task_id and on:
            _clear_wait(folder, task_id)


def holder(folder, name):
    """Who holds lock `name` as its file says ({pid, started, task_id, since}), when that process is alive; else None.
    For status only: the lock itself is the flock."""
    if folder is None:
        return None
    try:
        found = json.loads(lock_path(folder, name).read_text() or "null")
    except (OSError, ValueError):
        return None
    if not isinstance(found, dict) or runs.alive(found.get("pid"), found.get("started")) is False:
        return None
    return found


def waiting_on(folder, row):
    """`probe` or `memory` when the task's own run is waiting for (or holding) that lock, else None."""
    if folder is None or row is None or runs.holder(row) is None:
        return None
    try:
        found = json.loads((Path(folder) / "waits" / f"{row['task_id']}.json").read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(found, dict) or (found.get("pid"), found.get("started")) != runs.holder(row):
        return None
    return found.get("on") if found.get("on") in WAITS else None
