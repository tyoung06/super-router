"""The run supervisor (build brief 31, decision 4): started only by `sr project run` (router/projrun.py `start`), in a
session of its own, so closing the page or Terminal doesn't end it.

It starts the project's run command as an argument list (never a shell) in the project's folder, in a process group of
its own, with the environment `start` gave it (the router's own less the router's `.env` names and the billing switches,
the project's `.env` on top); records the program's pid and its `ps` start time in `run/projects/<name>/run.json`; reads
the program's output (stdout and stderr together) and writes each line redacted (the router's `.env` values and the
project's, 8 characters or more) to the run's log, which keeps its newest 5 MB; and when the program ends records the
exit code and the time: `stopped` when Stop asked for it, else `exited`. Nothing here restarts a run that ended."""
import argparse
import os
import select
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from router import projrun, runs, safety

DRAIN_SECONDS = 2.0  # after the program ends, how long a child it left holding the output may keep writing


def _iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main(argv=None, popen=subprocess.Popen):
    parser = argparse.ArgumentParser(prog="python -m router.supervise", allow_abbrev=False)
    for flag in ("--name", "--folder", "--run-folder", "--log", "--router-env"):
        parser.add_argument(flag, required=True)
    parser.add_argument("words", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    words = args.words[1:] if args.words[:1] == ["--"] else args.words
    run_folder = Path(args.run_folder)
    record = projrun.read_record(run_folder, args.name) or {}
    secrets = [*safety.env_secrets(projrun.router_values(args.router_env)),
               *safety.env_secrets(projrun.project_values(args.folder))]
    writer = projrun.Redacted(args.log, secrets)
    try:
        proc = popen(words, cwd=args.folder, env=dict(os.environ), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                     stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as e:
        writer.add(f"The run command could not start ({type(e).__name__}): {safety.one_line(str(e), secrets)}\n".encode())
        writer.close()
        projrun.write_record(run_folder, args.name, {**record, "state": "exited", "exit": None, "ended": _iso(),
                                                     "error": f"could not start ({type(e).__name__})",
                                                     "supervisor": os.getpid()})
        return 1
    started = runs.start_time(proc.pid)
    record = {**record, "state": "running", "pid": proc.pid, "pid_started": started if isinstance(started, str) else None,
              "supervisor": os.getpid()}
    projrun.write_record(run_folder, args.name, record)
    fd = proc.stdout.fileno()
    ended_at = None
    while True:
        ready, _, _ = select.select([fd], [], [], 0.5)
        if ready:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            writer.add(chunk)
        elif proc.poll() is not None:
            if ended_at is None:
                ended_at = time.monotonic()
            elif time.monotonic() - ended_at > DRAIN_SECONDS:
                break
    code = proc.wait()
    writer.close()
    now = projrun.read_record(run_folder, args.name) or record
    projrun.write_record(run_folder, args.name, {**now, "state": "stopped" if now.get("stop_asked") else "exited",
                                                 "exit": code, "ended": _iso()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
