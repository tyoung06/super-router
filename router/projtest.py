"""Test on demand (build brief 31, decisions 1 and 2).

`sr project test <name>` runs the project's test command (`sr project tests`) exactly as the router runs it after a
build: router/testrun.py's sandbox, its 300-second limit, its environment of four names (no key, no `.env` value, no
network) and its redacted output cut to the last 20,000 characters. It runs on a throwaway copy of the project's
committed files at its head, exported as a task's copy is (router/copies.py: the copies root, the same exclusions), and
the copy is removed when the run ends, whatever the outcome. No task, no log row, no agent. It never takes the project's
lock and never touches the project's folder.

The result (outcome, exit, summary line, seconds, when, the head it tested) and its output are kept under
`run/projects/<name>/tests/`, the newest 10. While a Test runs, its output so far is in `run/projects/<name>/test-live.txt`
(whole lines, redacted), for the page's side panel; `test-current.json` says one is running. A second Test on the same
project while one runs is refused: the lock `project-test-<name>` is held for the run."""
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

from router import copies, gitops, locks, projects, projrun, safety, testrun

KEEP = 10
LIVE = "test-live.txt"
CURRENT = "test-current.json"
RUNNER = None  # tests hand a fake runner; None: testrun.run
SHOWN = 20_000  # characters of output the status gives (the kept output is cut to this already)


class Refused(safety.SafeError):
    """A Test the router won't run: the reason, nothing made."""


class Unknown(Refused):
    """No project by that name."""


def _iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds")


def _stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y%m%dT%H%M%S")


def lock_name(name):
    return f"project-test-{name}"


def folder_of(run_folder, name):
    """Where a project's Test and Run records live, beside the log: `run/projects/<name>/`."""
    return Path(run_folder) / "projects" / name


def check(name, *, available=None, router_root=None):
    """(the project's folder, its test words, its git state) when a Test can run; else Refused with the reason."""
    try:
        folder = projects.folder_of(name)
    except projects.ProjectError as e:
        raise Refused(str(e)) from None
    if folder is None:
        raise Unknown(f"no project {name}")
    words = projects.tests_of(name)
    if not words:
        raise Refused(f"{name} has no test command: sr project tests {name} -- '<command>' sets one")
    repo = gitops.inspect(folder, router_root=router_root)
    if repo.why == gitops.OWN_FOLDER:
        raise Refused("this is the router's own folder: its suite is Claude Code's to run, and it passes Test's limit")
    if repo.head is None:
        raise Refused(f"Test runs the committed files at the head, and {name} has none: {repo.why or 'no commit yet'}")
    if not (available or testrun.available)():
        raise Refused("this Mac has no test sandbox (sandbox-exec)")
    problem = testrun.check_words(words, folder)
    if problem:
        raise Refused(problem)
    return folder, words, repo


def _private(path):
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _keep(where, stamp, record, output):
    tests = _private(where / "tests")
    (tests / f"{stamp}.txt").write_text(output or "")
    os.chmod(tests / f"{stamp}.txt", 0o600)
    (tests / f"{stamp}.json").write_text(json.dumps({**record, "output": f"{stamp}.txt"}, indent=1) + "\n")
    os.chmod(tests / f"{stamp}.json", 0o600)
    for old in sorted(tests.glob("*.json"))[:-KEEP]:
        old.unlink(missing_ok=True)
        (tests / f"{old.stem}.txt").unlink(missing_ok=True)


def run(name, *, run_folder, secrets=(), runner=None, clock=time.time, available=None, router_root=None):
    """Run the project's tests once on a fresh copy of its head, keep the result, and return its record. Refused (nothing
    made) when `check` refuses or a Test is already running on the project."""
    folder, words, repo = check(name, available=available, router_root=router_root)
    where = folder_of(run_folder, name)
    try:
        with locks.held(lock_name(name), folder=_private(Path(run_folder)), wait=False):
            _private(where)
            started = clock()
            stamp = _stamp(started)
            copies.ensure_roots()
            dest = copies.copies_root() / f"test-{name}-{stamp}"
            k = 2
            while dest.exists():
                dest = copies.copies_root() / f"test-{name}-{stamp}-{k}"
                k += 1
            live = where / LIVE
            live.write_text("")
            os.chmod(live, 0o600)
            current = where / CURRENT
            current.write_text(json.dumps({"started": _iso(started), "head": repo.head, "branch": repo.branch}) + "\n")
            try:
                try:
                    copies.export(["-C", folder], repo.head, dest)
                except copies.CopyError as e:
                    raise Refused(f"the copy of {name}'s head could not be made: {e}") from None
                result = (runner or RUNNER or testrun.run)(dest, words, project_folder=folder, secrets=secrets, live=live)
            finally:
                shutil.rmtree(dest, ignore_errors=True)
                current.unlink(missing_ok=True)
            ended = clock()
            record = {"outcome": result.outcome, "exit": result.exit, "summary": result.summary,
                      "seconds": round(ended - started, 1), "when": _iso(ended), "started": _iso(started),
                      "head": repo.head, "branch": repo.branch, "command": list(words)}
            _keep(where, stamp, record, safety.redact(result.output, secrets))
            return record
    except locks.Busy:
        raise Refused(f"a Test is already running on {name}") from None


def last(name, *, run_folder):
    """The newest kept result's record, or None."""
    tests = folder_of(run_folder, name) / "tests"
    found = sorted(tests.glob("*.json")) if tests.is_dir() else []
    for path in reversed(found):
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            continue
    return None


def output_of(record, *, run_folder, name=None):
    """A kept result's output (redacted when it was kept), or ""."""
    if not record or not record.get("output"):
        return ""
    folders = [folder_of(run_folder, name) / "tests"] if name else list((Path(run_folder) / "projects").glob("*/tests"))
    for tests in folders:
        path = tests / record["output"]
        if path.is_file():
            return path.read_text(errors="replace")
    return ""


def running(name, *, run_folder):
    """Whether a Test is running on the project now: its marker is there and its lock is held (break-ui 3: the page's
    Test button reads this from status, so it is off while one runs)."""
    if run_folder is None or not (folder_of(run_folder, name) / CURRENT).is_file():
        return False
    return locks.holder(Path(run_folder), lock_name(name)) is not None


def status(name, *, run_folder, secrets=()):
    """Brief 31 (decision 2): whether a Test is running on the project (its lock is held and its marker there), when it
    started and on which head, and the output to show: the live output while it runs, else the newest result's."""
    where = folder_of(run_folder, name)
    current = None
    try:
        current = json.loads((where / CURRENT).read_text())
    except (OSError, ValueError):
        current = None
    is_running = bool(current) and locks.holder(Path(run_folder), lock_name(name)) is not None
    newest = last(name, run_folder=run_folder)
    if is_running:
        output = (where / LIVE).read_text(errors="replace") if (where / LIVE).is_file() else ""
    else:
        output = output_of(newest, run_folder=run_folder, name=name)
    return {"running": is_running, "started": (current or {}).get("started") if is_running else None,
            "head": (current or {}).get("head") if is_running else None,
            "output": projrun.shown(output[-SHOWN:], secrets), "last": newest}


def line(record):
    """The page's and the prose's line for a kept result: "Tests passed", "Tests failed (exit 1)", "Tests timed out"."""
    if not record:
        return None
    if record.get("outcome") == "passed":
        return "Tests passed"
    if record.get("outcome") == "timed_out":
        return "Tests timed out"
    return "Tests failed" if record.get("exit") is None else f"Tests failed (exit {record['exit']})"


def last_view(name, run_folder):
    """`last_test` in `sr status --json` and `sr project list --json` (decision 11): the newest result's outcome and when,
    or None."""
    if run_folder is None:
        return None
    found = last(name, run_folder=run_folder)
    if not found:
        return None
    return {"outcome": found.get("outcome"), "exit": found.get("exit"), "when": found.get("when"),
            "summary": found.get("summary"), "head": gitops.short(found["head"]) if found.get("head") else None}


def project_secrets(folder):
    """Every value of 8 characters or more in the project's own `.env` (call 3: Test's output is redacted with these as
    well as the router's), or [] when it has none, it is a link, or it can't be read. The values stay in memory."""
    env = Path(folder) / ".env"
    if env.is_symlink() or not env.is_file():
        return []
    try:
        return safety.env_secrets(dotenv_values(env) or {})
    except (OSError, UnicodeDecodeError, ValueError):
        return []
