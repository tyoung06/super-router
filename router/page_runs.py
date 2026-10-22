"""The commands the page server starts (build brief 23, decisions 6 and 17). Each one is `sr` with an argument list the
command builder made (router/page_commands.py), never a shell string: it runs in its own session
(`start_new_session=True`) with stdin closed, so closing the page's terminal stops the page, not the task; its output
is read on a thread of its own, so no request waits on it. A request that starts one answers at once with the run's id
and pid.

The Run log keeps, for the last 100 runs, what each printed: its envelope's message, then its stderr (each capped at
256 KB, the tail kept). A run is matched to its task's row by pid before its envelope arrives (the row carries the pid
of the process that made it, brief 22; while the server has not reaped its child, no other process can hold that pid),
and by the envelope's task id once it ends. A task from Terminal or from before this server started is not here."""
import collections
import itertools
import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEEP = 100                  # decision 17: the last 100 runs
CAP = 256 * 1024            # characters of stdout or stderr kept per run, the tail
ENVELOPE_STDOUT = (0, 3, 4, 5)


def _iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds")


def _tail(text):
    if len(text) <= CAP:
        return text
    return f"[the first {len(text) - CAP} characters are not kept]\n" + text[-CAP:]


def envelope_of(code, stdout, stderr):
    """(the envelope, the stderr left over): the last line that is a JSON object, on stdout for exits 0, 3, 4 and 5 and
    on stderr for the rest (rules v2.30, Contracts), else (None, stderr)."""
    on_stderr = code not in ENVELOPE_STDOUT
    lines = ((stderr if on_stderr else stdout) or "").splitlines()
    for i in range(len(lines) - 1, -1, -1):
        try:
            found = json.loads(lines[i])
        except ValueError:
            continue
        if isinstance(found, dict):
            if on_stderr:
                stderr = "\n".join(lines[:i] + lines[i + 1:])
            return found, stderr
    return None, stderr


class Runs:
    """Every command this server started, newest last; at most KEEP kept (a running one is never dropped)."""

    def __init__(self, popen=subprocess.Popen, root=ROOT, prefix=None, clock=time.time, keep=KEEP,
                 thread=threading.Thread):
        self.popen, self.root, self.clock, self.keep, self.thread = popen, Path(root), clock, keep, thread
        self.prefix = list(prefix) if prefix is not None else [sys.executable, "-m", "router"]
        self._runs, self._ids, self._lock = collections.OrderedDict(), itertools.count(1), threading.Lock()
        self.on_finished = None  # brief 26 (decision 11): called with (a copy of the run, its exit) before it reads as ended

    def start(self, args, display, kind="action", request=None):
        """`sr <args>` started now; its record (a copy). Raises OSError when the command can't start."""
        proc = self.popen([*self.prefix, *args], cwd=str(self.root), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, start_new_session=True)
        run = {"id": f"run-{next(self._ids)}", "kind": kind, "display": display, "started": _iso(self.clock()),
               "pid": proc.pid, "running": True, "exit": None, "envelope": None, "message": None, "stderr": "",
               "task_id": None, "request": request}
        with self._lock:
            self._runs[run["id"]] = run
            self._prune()
            found = dict(run)
        self.thread(target=self._wait, args=(run["id"], proc), daemon=True).start()
        return found

    def record(self, kind, display):
        """A run the server makes itself through subprocess.run (its own `sr check`, the memory start): the record to
        fill with `finished`; its pid is not known while it runs."""
        run = {"id": f"run-{next(self._ids)}", "kind": kind, "display": display, "started": _iso(self.clock()), "pid": None,
               "running": True, "exit": None, "envelope": None, "message": None, "stderr": "", "task_id": None,
               "request": None}
        with self._lock:
            self._runs[run["id"]] = run
            self._prune()
        return run["id"]

    def finished(self, run_id, code, stdout, stderr):
        envelope, rest = envelope_of(code, stdout or "", stderr or "")
        with self._lock:
            run = self._runs.get(run_id)
            found = dict(run) if run is not None else None
        if found is not None and self.on_finished is not None:
            try:  # before the run reads as ended, so a page that sees it end never reads the old kept status
                self.on_finished(found, code)
            except Exception:  # never let a hook lose a run's end
                pass
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            run.update(running=False, exit=code, envelope=envelope, stderr=_tail(rest or ""),
                       message=_tail(str(envelope.get("message") or "")) if envelope else None)
            if envelope and envelope.get("task_id") and not run["task_id"]:
                run["task_id"] = envelope["task_id"]
            self._prune()

    def _wait(self, run_id, proc):
        try:
            stdout, stderr = proc.communicate()
        except Exception as e:  # the pipes broke: say so, never crash the server
            stdout, stderr = "", f"the page server lost this command's output ({type(e).__name__})"
        self.finished(run_id, proc.returncode, stdout, stderr)

    def _prune(self):
        extra = len(self._runs) - self.keep
        for run_id in [r for r, run in self._runs.items() if not run["running"]][:max(extra, 0)]:
            del self._runs[run_id]

    def bind(self, rows):
        """Match each running run to the row its process made (the row's `pid` is the run's pid)."""
        pids = {row.get("pid"): row.get("task_id") for row in rows or [] if isinstance(row, dict) and row.get("pid")}
        with self._lock:
            for run in self._runs.values():
                if run["running"] and not run["task_id"] and run["pid"] in pids:
                    run["task_id"] = pids[run["pid"]]

    def list(self):
        """Every kept run, newest first, as copies."""
        with self._lock:
            return [dict(run) for run in reversed(self._runs.values())]

    def get(self, run_id):
        with self._lock:
            run = self._runs.get(run_id)
            return dict(run) if run else None
