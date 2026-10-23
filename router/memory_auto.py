"""Memory starts on its own (rules v2.31, Memory "Down"; build brief 22, decision 8; Phase 0 choice 10): with
`memory: auto` (config/settings.json), the first fresh recall of a command that finds the store down starts it
(`memory_server.start`, waiting up to 60 s for `/health`), one start at a time by the `memory` lock beside the log; the
task shows `waiting_on: memory` meanwhile and `sr status` shows `memory.starting`. After a start the backfill stores
every delivered tagged task the bank is missing (`memory.backfill`), then the recall goes on. A start is tried once per
command; a failed one leaves the recall to fail as it always did (the task runs without its block; a tagged `recall`
comes back `memory_down`). `memory: off` never starts it. A retain at delivery never starts it: the next start's backfill
fills in what it missed. Nothing here calls a model."""
import subprocess
import time

from router import locks, memory, memory_server, runs, settings

START_SECONDS = 60  # decision 8: how long a task waits for the store it started


def starter(*, environ, home, popen=subprocess.Popen, sleep=time.sleep, clock=time.monotonic):
    """The start a command uses: `memory_server.start` with this Mac's process tools (main passes the real ones)."""
    def start(client, *, limit, out):
        try:
            return memory_server.start(client, environ=environ, home=home, popen=popen, sleep=sleep, clock=clock,
                                       out=out, limit=limit)
        except memory_server.ServerError:
            return 2
    return start


class AutoStore:
    """The memory client a command that runs agents uses: the store's own client, with the start-on-recall above. Every
    other attribute is the client's own."""

    def __init__(self, client, *, mode, start, conn, secrets, out, folder):
        self._client, self._mode, self._start = client, mode, start
        self._conn, self._secrets, self._out, self._folder = conn, secrets, out, folder
        self._tried = False

    def __getattr__(self, name):
        return getattr(self._client, name)

    def recall(self, *args, **kwargs):
        self.ensure()
        return self._client.recall(*args, **kwargs)

    def ensure(self):
        """Start the store when it is down, once per command, and backfill it after a start."""
        if self._tried or (self._mode or settings.memory_mode()) != "auto":  # brief 27: read at each start, not once
            return
        self._tried = True
        if self._client.online():
            return
        with locks.held("memory", folder=self._folder, task_id=runs.current(), on="memory"):
            if self._client.online():  # another command started it while this one waited
                return
            self._out(f"memory: the store was down; starting it (up to {START_SECONDS} s)")
            said = []
            code = self._start(self._client, limit=START_SECONDS, out=said.append)
            if code != 0:
                why = "Hindsight is not installed" if code == 2 else f"no answer within {START_SECONDS} s"
                self._out(f"memory: could not start the store ({why}); this task runs without its memory block")
                return
            self._out("memory: started")
            memory.backfill(self._conn, self._client, self._secrets, self._out)


def wrap(client, *, conn, secrets, out, folder, start, mode=None):
    """The store a command uses: the AutoStore over `client`, or `client` itself when there is none (tests)."""
    if client is None:
        return None
    return AutoStore(client, mode=mode, start=start, conn=conn, secrets=secrets, out=out, folder=folder)
