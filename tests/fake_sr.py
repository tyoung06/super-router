"""A fake `sr` for the page server's tests (build brief 23): no router, no model, no log. It answers like an action under
`--json`: one envelope line, on stdout for exits 0, 3, 4 and 5 and on stderr for the rest, carrying what the tests check
(its argv, its own pid and session id, how much stdin held). Set by the environment the test gives it:
FAKE_SR_SLEEP (seconds before answering), FAKE_SR_EXIT (the exit code), FAKE_SR_STDERR (extra stderr text),
FAKE_SR_TASK (the task id it names), FAKE_SR_OUT (a file to append its argv to, as one JSON line)."""
import json
import os
import sys
import time

args = sys.argv[1:]
time.sleep(float(os.environ.get("FAKE_SR_SLEEP", "0")))
code = int(os.environ.get("FAKE_SR_EXIT", "0"))
stdin = sys.stdin.read() if not sys.stdin.closed else ""
if os.environ.get("FAKE_SR_OUT"):
    with open(os.environ["FAKE_SR_OUT"], "a", encoding="utf-8") as f:
        f.write(json.dumps(args) + "\n")
envelope = {"task_id": os.environ.get("FAKE_SR_TASK"), "n": None, "status": None, "waiting_on": None, "outcome": None,
            "reason_code": None if code in (0, 3, 4, 5) else "bad_task", "exit": code,
            "message": f"fake sr ran {' '.join(args[:1])}", "argv": args, "pid": os.getpid(), "sid": os.getsid(0),
            "stdin": len(stdin)}
if os.environ.get("FAKE_SR_STDERR"):
    sys.stderr.write(os.environ["FAKE_SR_STDERR"] + "\n")
print(json.dumps(envelope), file=sys.stdout if code in (0, 3, 4, 5) else sys.stderr)
sys.exit(code)
