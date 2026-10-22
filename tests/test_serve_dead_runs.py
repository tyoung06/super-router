"""Build brief 22, B5 (rules v2.31, Resume: "`sr check` (or the interface's poll) marks such a task"; decision 4): `sr
serve` reads `sr status --json` at most once a minute; when that shows a run whose process ended (`running[].alive` is
false), it runs `sr check --json` once, as an argument list from the repo folder, on a thread of its own so the page
keeps answering, never two at a time; then the next status read is fresh. The commands are fakes."""
import json
from types import SimpleNamespace

from router import page

DEAD = {"api_version": 1, "running": [{"n": 1, "task_id": "sr-1", "pid": 4321, "alive": False, "since": "x"}]}
ALIVE = {"api_version": 1, "running": [{"n": 1, "task_id": "sr-1", "pid": 4321, "alive": True, "since": "x"}]}
UNKNOWN = {"api_version": 1, "running": [{"n": 1, "task_id": "sr-1", "pid": 4321, "alive": None, "since": "x"}]}


class Commands:
    def __init__(self, status):
        self.status, self.calls = status, []

    def __call__(self, argv, **kw):
        assert isinstance(argv, list) and not kw.get("shell")
        self.calls.append((argv, kw))
        name = argv[3]
        body = self.status if name == "status" else {"tasks": []}
        return SimpleNamespace(returncode=0, stdout=json.dumps(body) + "\n", stderr="")

    def checks(self):
        return [(argv, kw) for argv, kw in self.calls if argv[3] == "check"]


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Later:
    """Runs a background job only when told to (the thread is the server's business, the job is the test's)."""

    def __init__(self):
        self.jobs = []

    def __call__(self, job):
        self.jobs.append(job)

    def run_all(self):
        while self.jobs:
            self.jobs.pop(0)()


def test_a_dead_run_in_the_status_makes_the_server_run_sr_check_once():
    commands, clock, later = Commands(DEAD), Clock(), Later()
    reader = page.Reader(run=commands, clock=clock, start=later)
    assert reader.status()[0] == 200
    assert reader.status()[0] == 200          # kept: no second read, no second check
    assert len(later.jobs) == 1 and commands.checks() == []
    later.run_all()
    (argv, kw), = commands.checks()
    assert argv[1:] == ["-m", "router", "check", "--json"] and kw["cwd"] == str(page.ROOT)
    assert kw["stdin"] is not None and kw["timeout"] == page.CHECK_TIMEOUT


def test_no_check_while_one_is_running_and_a_fresh_status_after_it():
    commands, clock, later = Commands(DEAD), Clock(), Later()
    reader = page.Reader(run=commands, clock=clock, start=later)
    reader.status()
    clock.t += 61
    reader.status()                            # a fresh read, the first check not run yet: no second
    assert len(later.jobs) == 1
    later.run_all()
    reads = [argv for argv, kw in commands.calls if argv[3] == "status"]
    reader.status()                            # the check cleared the kept status: read again at once
    assert len([argv for argv, kw in commands.calls if argv[3] == "status"]) == len(reads) + 1


def test_a_live_run_or_one_ps_cannot_judge_runs_no_check():
    for status in (ALIVE, UNKNOWN, {"api_version": 1}):
        commands, later = Commands(status), Later()
        page.Reader(run=commands, clock=Clock(), start=later).status()
        assert later.jobs == []


def test_a_check_that_fails_to_run_is_let_go():
    later = Later()

    def run(argv, **kw):
        if argv[3] == "check":
            raise OSError("no python")
        return SimpleNamespace(returncode=0, stdout=json.dumps(DEAD) + "\n", stderr="")

    reader = page.Reader(run=run, clock=Clock(), start=later)
    reader.status()
    later.run_all()                            # no exception escapes
    reader.status()
    assert len(later.jobs) == 1                # the next dead run read starts another
