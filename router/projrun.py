"""Run and Stop (build brief 31, decisions 3 to 7 and 10).

**The run command** (decision 3): `sr project run-command <name> -- <words>` keeps it, `--clear` removes it, in
`config/project_runs.json` (gitignored, the router's own, never in a project), as the test command is kept: one line,
split as a shell would split it, never run through one, at most 300 characters, no control character.

**Run** (decision 4): `sr project run <name>` starts the run command in the project's real folder as the owner would in
Terminal: an argument list, never a shell; not sandboxed; no time limit. Its environment is the router's own with every
name the router's `.env` holds and every billing switch removed, then the project's `.env` (read with `dotenv_values`)
laid on top. It runs under a small supervisor (router/supervise.py) in its own session, so closing the page or Terminal
doesn't end it: the supervisor redacts every line of the program's output (the router's `.env` values and the project's,
8 characters or more) before writing it to `run/projects/<name>/run-<time>.log`, keeps the newest 5 MB of it, and
records the exit code and the time when the program ends. One run per project at a time. Only the owner's command starts
one (decision 5): nothing in the router calls `start` but `sr project run`.

**Stop** (decision 6): `sr project stop <name>` sends the program's process group SIGTERM, then SIGKILL after 10 seconds,
and records `stopped`. The run is known by its process id and its start time together (router/runs.py), so a reused
process id is never signalled. `sr project run <name> --status` gives running or not, the command, when it started, its
exit or `stopped`, and the output's redacted tail."""
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

from router import gitops, locks, projects, runs, safety, settings

RUNS_PATH = safety.REPO_ROOT / "config" / "project_runs.json"   # gitignored: the router's, never in a project
RUNS_NAME = "config/project_runs.json"
WORDS_LIMIT = 300
LOG_KEEP = 5 * 1024 * 1024     # decision 4: the newest 5 MB of a run's output
LOG_CUT = 6 * 1024 * 1024      # past this the log is cut back to LOG_KEEP (a margin, so it isn't cut on every line)
CHUNK_LINE = 65_536            # a line with no end is written in pieces of this size
TAIL_LINES = 2000              # decision 6: `--status` gives the last 2,000 lines,
TAIL_BYTES = 200 * 1024        # at most 200 KB
STOP_WAIT = 10.0               # decision 6: SIGTERM, then SIGKILL after 10 seconds
START_WAIT = 10.0              # how long `sr project run` waits for the supervisor's first record
RECORD = "run.json"
KILL = os.killpg               # tests hand a fake


class Refused(safety.SafeError):
    """A run command, Run or Stop the router won't do: the reason, nothing started or written."""


class Unknown(Refused):
    """No project by that name."""


def _iso(seconds=None):
    return datetime.fromtimestamp(time.time() if seconds is None else seconds, timezone.utc).isoformat(timespec="seconds")


def _control(text):
    return any(unicodedata.category(c) == "Cc" for c in text)


# ---------- the run command (decision 3) ----------

def split_words(text):
    """The run command's words, split as a shell would split them (shlex), never run through one."""
    if not isinstance(text, str) or not text.strip():
        raise Refused("type the run command")
    if len(text) > WORDS_LIMIT:
        raise Refused(f"the run command is {len(text):,} characters; at most {WORDS_LIMIT}")
    if _control(text):
        raise Refused("the run command holds a control character")
    try:
        words = shlex.split(text)
    except ValueError as e:
        raise Refused(f"the run command can't be split as a shell would: {e} (a quote not closed?)") from None
    if not words:
        raise Refused("type the run command")
    return words


def read_runs(path=None):
    """{name: [words]}. A missing file is no commands; one that can't be read is Refused."""
    path = Path(path or RUNS_PATH)
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return {}
    except OSError:
        raise Refused(f"{RUNS_NAME} could not be read") from None
    try:
        data = json.loads(raw)
    except ValueError:
        raise Refused(f"{RUNS_NAME} could not be read: it is not JSON") from None
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, list) and v and
                                             all(isinstance(w, str) for w in v) for k, v in data.items()):
        raise Refused(f"{RUNS_NAME} could not be read: it is not a map of names to words")
    return data


def _write_runs(data, path=None):
    path = Path(path or RUNS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def run_command_of(name, *, path=None):
    try:
        return read_runs(path).get(name)
    except Refused:
        return None


def set_run_command(name, words, *, path=None):
    data = read_runs(path)
    data[name] = list(words)
    _write_runs(data, path)


def clear_run_command(name, *, path=None):
    data = read_runs(path)
    if name not in data:
        return False
    del data[name]
    _write_runs(data, path)
    return True


# ---------- the environment (decision 4) ----------

def environment(base, *, router_names, project):
    """The program's environment: `base` (the router's own) less every name the router's `.env` holds and every billing
    switch, then the project's `.env` laid on top (a name both set takes the project's value)."""
    env = {k: v for k, v in base.items() if k not in router_names and k not in safety.BILLING_SWITCHES}
    env.update({k: v for k, v in (project or {}).items() if isinstance(v, str)})
    return env


def _env_file(folder):
    """The project's `.env` as (path, kind): kind None when there is none, `link`, `other` (not a plain file) or `file`."""
    env = Path(folder) / ".env"
    if env.is_symlink():
        return env, "link"
    if not env.exists():
        return env, None
    return env, "file" if env.is_file() else "other"


def env_problem(folder, repo=None, creating=False):
    """Why the project's `.env` keeps it from Run (or Secrets), or None: a link or not a plain file; with git, a `.env`
    git tracks or doesn't ignore (call 6: without git the rule doesn't apply). `creating` (Secrets): a `.env` not there
    yet is checked too, so the router never makes one git would pick up."""
    env, kind = _env_file(folder)
    if kind is None and not creating:
        return None
    if kind == "link":
        return "its .env is a link: Run and Secrets use only a plain .env file in the project's own folder"
    if kind == "other":
        return "its .env is not a plain file"
    repo = repo if repo is not None else gitops.inspect(folder)
    if not repo.git:
        return None
    tracked = gitops.run(["-C", folder, "ls-files", "--error-unmatch", "--", ".env"], check=False)
    if tracked.returncode == 0:
        return "git tracks its .env: take it out of git (git rm --cached .env) and ignore it first"
    ignored = gitops.run(["-C", folder, "check-ignore", "-q", "--", ".env"], check=False)
    if ignored.returncode != 0:
        return "git doesn't ignore its .env: add .env to its .gitignore first"
    return None


def project_values(folder):
    """The project's `.env` as `dotenv_values` reads it, or {} when there is none."""
    env, kind = _env_file(folder)
    if kind != "file":
        return {}
    return dotenv_values(env) or {}


def router_values(path=None):
    path = Path(path or (safety.REPO_ROOT / ".env"))
    if path.is_symlink() and not path.exists():
        return {}
    try:
        return dotenv_values(path) or {}
    except OSError:
        return {}


def never_run_problem(values):
    """Decision 10: why `never_run_env` keeps the project from Run (a part matched inside one of its `.env` names, without
    case), or None."""
    parts, why = settings.never_run_env()
    if why:
        return why + ", so Run refuses every project until it is fixed"
    for part in parts:
        for name in values:
            if part.casefold() in name.casefold():
                return (f'this project\'s .env holds a name containing "{part}" (never_run_env in this Mac\'s local '
                        "settings), so Run never starts it")
    return None


# ---------- the record ----------

def folder_of(run_folder, name):
    return Path(run_folder) / "projects" / name


def read_record(run_folder, name):
    try:
        found = json.loads((folder_of(run_folder, name) / RECORD).read_text())
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def write_record(run_folder, name, record):
    where = folder_of(run_folder, name)
    where.mkdir(parents=True, exist_ok=True)
    temp = where / (RECORD + ".tmp")
    temp.write_text(json.dumps(record, indent=1) + "\n")
    os.chmod(temp, 0o600)
    os.replace(temp, where / RECORD)


def alive(record):
    """True, False or None (can't tell) for the record's program, by its pid and start time (router/runs.py)."""
    if not record or record.get("pid") is None:
        return False
    return runs.alive(record["pid"], record.get("pid_started"))


def running(record):
    """A record that says running and whose program is there (or can't be told apart): one run per project."""
    return bool(record) and record.get("state") == "running" and alive(record) is not False


# ---------- the redacted log (decision 4) ----------

class Redacted:
    """The run's log: each line of the program's output redacted before it is written, whole lines as they arrive; a
    line with no end is written in pieces past CHUNK_LINE, holding back the longest secret's length, so a value split
    across two reads is still caught. The file is owner-only and keeps its newest LOG_KEEP bytes from a line start."""

    def __init__(self, path, secrets):
        self.path = Path(path)
        self.secrets = sorted({s for s in secrets if s}, key=len, reverse=True)
        self.hold = max((len(s) for s in self.secrets), default=1) - 1
        self.pending = ""
        self.raw = b""
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.chmod(self.path, 0o600)
        self.file = os.fdopen(fd, "a", encoding="utf-8")

    def _write(self, text):
        if not text:
            return
        self.file.write(safety.redact(text, self.secrets))
        self.file.flush()
        if self.file.tell() > LOG_CUT:
            self.file.close()
            data = self.path.read_bytes()[-LOG_KEEP:]
            cut = data.find(b"\n")
            data = data[cut + 1:] if cut != -1 else data
            temp = self.path.with_name(self.path.name + ".tmp")
            temp.write_bytes(data)
            os.chmod(temp, 0o600)
            os.replace(temp, self.path)
            self.file = open(self.path, "a", encoding="utf-8")

    def add(self, chunk):
        data = self.raw + chunk
        try:  # a character cut between two reads waits for its other bytes
            text, self.raw = data.decode("utf-8"), b""
        except UnicodeDecodeError as e:
            if e.start >= len(data) - 3 and e.reason == "unexpected end of data":
                text, self.raw = data[:e.start].decode("utf-8", errors="replace"), data[e.start:]
            else:
                text, self.raw = data.decode("utf-8", errors="replace"), b""
        self.pending += text
        cut = self.pending.rfind("\n") + 1
        if cut:
            self._write(self.pending[:cut])
            self.pending = self.pending[cut:]
        if len(self.pending) > CHUNK_LINE + self.hold:
            keep = self.hold
            self._write(self.pending[:len(self.pending) - keep])
            self.pending = self.pending[len(self.pending) - keep:]

    def close(self):
        self.pending += self.raw.decode("utf-8", errors="replace")
        self.raw = b""
        self._write(self.pending)
        self.pending = ""
        self.file.close()


_ESCAPES = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")


def shown(text, secrets=()):
    """The display copy of a Test's or a run's output (break-ui 1: pytest's colours showed as `[32m`): terminal escape
    sequences (colour, cursor) taken out, then every other control character but a newline and a tab shown as a mark and
    never deleted (safety.for_terminal), and the whole redacted again, since taking characters out could join a value a
    program printed in two parts. The kept files stay as they were written."""
    return safety.for_terminal(_ESCAPES.sub("", text or ""), secrets)


def tail(path, lines=None, size=None):
    """The last `lines` lines of a log, at most `size` bytes (decision 6)."""
    lines, size = lines or TAIL_LINES, size or TAIL_BYTES
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            f.seek(max(0, end - size))
            data = f.read()
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace")
    if end > size and "\n" in text:  # the first line was cut by the size: drop its piece
        text = text[text.find("\n") + 1:]
    found = text.splitlines(keepends=True)
    return "".join(found[-lines:])


# ---------- Run (decisions 4, 5 and 10) ----------

def check(name, *, router_root=None):
    """(the project's folder, the run command's words, the project's `.env` values) when Run may start; else Refused."""
    try:
        folder = projects.folder_of(name)
    except projects.ProjectError as e:
        raise Refused(str(e)) from None
    if folder is None:
        raise Unknown(f"no project {name}")
    words = run_command_of(name)
    if not words:
        raise Refused(f"{name} has no run command: sr project run-command {name} -- '<command>' sets one")
    if gitops.inside_router(folder, router_root) or (gitops.installed() and gitops.own_folder(folder, router_root)):
        raise Refused("the router never runs itself: this is the router's own folder")
    if not Path(folder).is_dir():
        raise Refused(f"{name}'s folder isn't there")
    problem = env_problem(folder, gitops.inspect(folder, router_root=router_root) if gitops.installed() else None)
    if problem:
        raise Refused(problem)
    values = project_values(folder)
    problem = never_run_problem(values)
    if problem:
        raise Refused(problem)
    return Path(folder), words, values


def start(name, *, run_folder, router_env=None, base=None, popen=None, router_root=None, clock=time.monotonic,
          wait=START_WAIT, sleep=time.sleep):
    """Start the run command under the supervisor and return its first record (running, or ended already when the
    program was quick). Refused, with nothing started, as `check` says, or while a run is going on the project."""
    folder, words, _ = check(name, router_root=router_root)
    run_folder = Path(run_folder)
    run_folder.mkdir(parents=True, exist_ok=True)
    try:
        with locks.held(f"project-run-{name}", folder=run_folder, wait=False):
            before = read_record(run_folder, name)
            if running(before):
                raise Refused(f"a run is already going on {name} (since {before.get('started')})")
            router_found = router_values(router_env)
            env = environment(dict(os.environ if base is None else base), router_names=set(router_found),
                              project=project_values(folder))
            where = folder_of(run_folder, name)
            where.mkdir(parents=True, exist_ok=True)
            os.chmod(where, 0o700)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            log = where / f"run-{stamp}.log"
            argv = [sys.executable, "-m", "router.supervise", "--name", name, "--folder", str(folder),
                    "--run-folder", str(run_folder), "--log", str(log), "--router-env",
                    str(Path(router_env or (safety.REPO_ROOT / ".env"))), "--", *words]
            write_record(run_folder, name, {"state": "starting", "command": list(words), "folder": str(folder),
                                            "log": str(log), "started": _iso(), "pid": None, "pid_started": None})
            (popen or subprocess.Popen)(argv, cwd=str(safety.REPO_ROOT), env=env, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            deadline = clock() + wait
            while clock() < deadline:
                found = read_record(run_folder, name)
                if found and found.get("state") != "starting":
                    return found
                sleep(0.05)
            raise Refused(f"the run of {name} didn't start in {wait:.0f} s; its log may say why")
    except locks.Busy:
        raise Refused(f"a run is starting on {name} already") from None


# ---------- Stop and the status (decision 6) ----------

def stop(name, *, run_folder, sleep=time.sleep, clock=time.monotonic):
    """End the run's group: SIGTERM, then SIGKILL after STOP_WAIT seconds; record `stopped`. Only when the pid's start
    time matches the record (a reused pid, or one `ps` can't read, is never signalled)."""
    found = read_record(run_folder, name)
    if not found or found.get("state") != "running":
        raise Refused(f"no run is going on {name}")
    there = alive(found)
    if there is None:
        raise Refused(f"couldn't tell whether {name}'s run is still the process it started, so nothing was signalled")
    if there is False:
        raise Refused(f"no run is going on {name} (its process is gone)")
    pid = found["pid"]
    write_record(run_folder, name, {**found, "stop_asked": _iso()})
    try:
        KILL(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = clock() + STOP_WAIT
    while clock() < deadline and _group_alive(pid):
        sleep(0.1)
    if _group_alive(pid):
        try:
            KILL(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        end = clock() + 3
        while clock() < end and _group_alive(pid):
            sleep(0.05)
    end = clock() + 3  # the supervisor writes its own end; wait a moment for it, then write it here
    while clock() < end:
        now = read_record(run_folder, name) or {}
        if now.get("state") == "stopped":
            return now
        sleep(0.05)
    now = read_record(run_folder, name) or found
    done = {**now, "state": "stopped", "ended": now.get("ended") or _iso(), "stop_asked": now.get("stop_asked") or _iso()}
    write_record(run_folder, name, done)
    return done


def _group_alive(pgid):
    try:
        KILL(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _confirm_facts(name):
    """Decision 7: what Run's confirm names: the project's folder (with ~) and the names in its `.env`, never a value."""
    try:
        folder = projects.folder_of(name)
    except projects.ProjectError:
        folder = None
    if folder is None:
        return {"folder": None, "env_names": []}
    try:
        names = sorted(project_values(folder))
    except (OSError, UnicodeDecodeError, ValueError):
        names = []
    return {"folder": projects.tilde(folder), "env_names": names}


def status(name, *, run_folder, secrets=()):
    """Decision 6: running or not, the command, when it started, its exit or `stopped`, and the output's redacted tail (as
    `shown` cleans it for display); with what Run's confirm names (decision 7)."""
    found = read_record(run_folder, name)
    if not found:
        return {"running": False, "state": None, "command": run_command_of(name), "started": None, "ended": None,
                "exit": None, "output": "", "log": None, **_confirm_facts(name)}
    is_running = found.get("state") in ("running", "starting") and alive(found) is not False
    state = found.get("state")
    if state == "running" and not is_running:
        state = "ended"  # its process is gone and nothing recorded its end (the supervisor was killed)
    return {"running": is_running, "state": state, "command": found.get("command") if is_running else run_command_of(name),
            "ran": found.get("command"), "started": found.get("started"), "ended": found.get("ended"),
            "exit": found.get("exit"), "log": found.get("log"),
            "output": shown(tail(found["log"]), secrets) if found.get("log") else "",
            **_confirm_facts(name)}


def view(name, run_folder):
    """`run` in `sr status --json` and `sr project list --json` (decision 11): state, started, ended, exit; or None."""
    if run_folder is None:
        return None
    found = status(name, run_folder=run_folder)
    if found["state"] is None:
        return None
    return {"state": found["state"], "running": found["running"], "started": found["started"], "ended": found["ended"],
            "exit": found["exit"]}
