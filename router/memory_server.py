"""`sr memory start|stop|status`: Hindsight as a process the owner starts and stops (rules v2.27, Memory, "What it is"
and "Down"; build brief 19, decisions 1 to 3). The router never starts it on its own.

The server is `~/.hindsight/venv/bin/hindsight-api`, from its own virtual environment, never the router's. It
listens on the loopback address only: the `--host` flag and `HINDSIGHT_API_HOST` both say so, and a `memory_url` off
the loopback is refused before anything starts. Its environment is built from scratch (HOME, PATH, USER and LANG
from the shell, then the Hindsight settings), so no key from anywhere reaches it, and `HINDSIGHT_API_LLM_PROVIDER` is
`none`: no LLM, no extraction, no reflect, no observations. It runs detached in its own session, its output in
`~/.hindsight/sr-daemon.log`, its pid in `~/.hindsight/sr.pid`. The process start, the sleep, the clock and the
kill are injected (main passes the real ones), so no test starts or stops anything.
"""
import os
import signal
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from router import memory, safety, settings

FOLDER = ".hindsight"
BINARY = Path("venv") / "bin" / "hindsight-api"
PID_FILE = "sr.pid"
LOG_FILE = "sr-daemon.log"
# Where the embedded Postgres keeps its data. The installation page says `~/.hindsight/data/`; pg0 0.15.2, the version
# the install resolved to, makes `~/.pg0/` (installation/ and instances/hindsight/data/) and leaves `~/.hindsight/data/`
# unmade (seen on the first real start, 2026-10-18). Status shows the first of these that exists.
DATA_FOLDERS = (".pg0", ".hindsight/data")
KEEP_ENV = safety.CLAUDE_ENV_KEYS  # HOME, PATH, USER, LANG: the same four a claude call gets
# Decision 2 and the go's amendment 2: no LLM, the slim install's providers, CPU only, chunks mode. Nothing else.
SERVER_ENV = {
    "HINDSIGHT_API_LLM_PROVIDER": "none",
    "HINDSIGHT_API_EMBEDDINGS_PROVIDER": "onnx",
    "HINDSIGHT_API_RERANKER_PROVIDER": "rrf",
    "HINDSIGHT_API_EMBEDDINGS_LOCAL_FORCE_CPU": "1",
    "HINDSIGHT_API_RERANKER_LOCAL_FORCE_CPU": "1",
    "HINDSIGHT_API_RETAIN_EXTRACTION_MODE": "chunks",
}
INSTALL = ('python3 -m venv ~/.hindsight/venv && ~/.hindsight/venv/bin/pip install '
           '"hindsight-api-slim[local-onnx,embedded-db]"')
LOOPBACK = ("127.0.0.1", "localhost")
POLL_SECONDS = 2
START_SECONDS = 180
REPORT_EVERY = 20
STOP_SECONDS = 30
USAGE = "sr memory start|stop|status|rebuild|on|off"


class ServerError(safety.SafeError):
    """A refusal before anything starts: names and paths only."""


def paths(home):
    folder = Path(home) / FOLDER
    return {"folder": folder, "binary": folder / BINARY, "pid": folder / PID_FILE, "log": folder / LOG_FILE}


def data_folder(home):
    """The database's folder, or None before the first start made one."""
    for name in DATA_FOLDERS:
        if (Path(home) / name).is_dir():
            return Path(home) / name
    return None


def host_port(url):
    """(host, port) from `memory_url`; refused off the loopback address (rules: 127.0.0.1 and nowhere else)."""
    parsed = urlparse(url)
    host, port = parsed.hostname, parsed.port or 8888
    if host not in LOOPBACK:
        raise ServerError(f"memory_url must be on the loopback address (127.0.0.1), not {safety.one_line(str(host))}")
    return host, port


def argv(home, host, port):
    return [str(paths(home)["binary"]), "--host", host, "--port", str(port)]


def environment(environ, host, port):
    """The server's whole environment: four names from the shell, then the Hindsight settings. Never a key."""
    env = {name: environ[name] for name in KEEP_ENV if name in environ}
    env.update(SERVER_ENV)
    env["HINDSIGHT_API_HOST"] = host
    env["HINDSIGHT_API_PORT"] = str(port)
    return env


def shown(path, home):
    """A path under home, printed as ~/..."""
    try:
        return "~/" + Path(path).relative_to(home).as_posix()
    except ValueError:
        return str(path)


def read_pid(home):
    try:
        return int(paths(home)["pid"].read_text().strip())
    except (OSError, ValueError):
        return None


def human(n):
    """A byte count the way `du -sh` prints it: B, K, M, G, T; one decimal under 10."""
    size = float(n)
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024 or unit == "T":
            if unit == "B":
                return f"{int(size)}B"
            return f"{size:.1f}{unit}" if size < 10 else f"{size:.0f}{unit}"
        size /= 1024


def folder_size(path):
    """The folder's size (the files' byte counts, summed), or 0B when it is missing."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return human(total)


def status_lines(client, home):
    """(the `sr memory status` lines, online?): decision 3 and the go's choice 5; also the tail of a start."""
    data = data_folder(home)
    size = (f"data: {folder_size(data)} {shown(data, home)}" if data is not None
            else f"data: none yet (~/{DATA_FOLDERS[0]} appears on the first start)")
    if not client.online():
        hint = "" if settings.memory_mode() == "off" else "; sr memory start starts it"  # refused while off (brief 27)
        return [f"memory: offline ({client.url}){hint}", size], False
    try:
        version = client.version()
    except memory.Unavailable as e:
        version = f"unknown: {e}"
    lines = [f"memory: online ({client.url}, api {version})"]
    try:
        count = client.stats().get("total_documents")
        lines.append(f"bank {client.bank}: {count} documents" if count is not None else f"bank {client.bank}: stats unreadable")
    except memory.Unavailable as e:
        lines.append(f"bank {client.bank}: not created yet ({e}); sr memory start creates it")
    lines.append(size)
    return lines, True


def status(client, *, home, out):
    lines, online = status_lines(client, home)
    for line in lines:
        out(line)
    return 0 if online else 1


def wait_limit(limit=None):
    """How long a start waits for `/health`: 180 s by hand (the first start downloads its model), or what the caller
    asks (build brief 22, decision 8: 60 s when the router starts it for a task)."""
    return START_SECONDS if limit is None else limit


def start(client, *, environ, home, popen, sleep, clock, out, limit=None):
    """Decision 3: start the server detached, poll `/health` every 2 s for up to 180 s (`limit` when given) with a line
    every 20 s, then create or update the bank. Exit 0 online, 1 when it did not come up (the pid file stays: it may
    still be downloading its model), 2 refused. Already online: nothing is started; the bank is still ensured."""
    host, port = host_port(client.url)
    p = paths(home)
    if client.online():
        out(f"memory: already online ({client.url})")
        client.ensure_bank()
        for line in status_lines(client, home)[0]:
            out(line)
        return 0
    if not p["binary"].exists():
        out(f"Refused: Hindsight is not installed at {shown(p['binary'], home)}. Install it with: {INSTALL}. "
            "Nothing was started.")
        return 2
    p["folder"].mkdir(parents=True, exist_ok=True)
    command = argv(home, host, port)
    out(f"memory: starting Hindsight: {' '.join([shown(command[0], home)] + command[1:])} (log {shown(p['log'], home)})")
    with open(p["log"], "ab") as log_file:
        proc = popen(command, env=environment(environ, host, port), stdin=subprocess.DEVNULL, stdout=log_file,
                     stderr=subprocess.STDOUT, cwd=str(p["folder"]), start_new_session=True)
    p["pid"].write_text(f"{proc.pid}\n")
    began, reported = clock(), 0
    while not client.online():
        code = proc.poll()
        if code is not None:
            out(f"memory: Hindsight exited with code {code} before answering; see {shown(p['log'], home)}")
            return 1
        waited = clock() - began
        if waited >= wait_limit(limit):
            out(f"memory: Hindsight has not answered after {wait_limit(limit)} s; the first start downloads its model and "
                f"may need longer. Check {shown(p['log'], home)}, then sr memory status.")
            return 1
        if waited - reported >= REPORT_EVERY:
            reported = waited
            out(f"memory: still starting ({waited:.0f} s)")
        sleep(POLL_SECONDS)
    client.ensure_bank()
    for line in status_lines(client, home)[0]:
        out(line)
    return 0


def stop(client, *, home, kill, sleep, clock, out):
    """TERM to the pid `sr memory start` wrote, then wait until `/health` stops answering. Never a server this
    command did not start. Exit 0 stopped (or nothing to stop), 1 when it is still answering."""
    p = paths(home)
    pid = read_pid(home)
    if pid is None:
        if client.online():
            out(f"memory: online at {client.url}, but sr memory start did not start it (no {shown(p['pid'], home)}); "
                "stop it yourself.")
            return 1
        out("memory: offline; nothing to stop")
        return 0
    try:
        kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        out(f"memory: process {pid} is already gone")
    began = clock()
    while client.online():
        if clock() - began >= STOP_SECONDS:
            out(f"memory: still answering {STOP_SECONDS} s after TERM (pid {pid}); not killed harder. "
                f"Check {shown(p['log'], home)}.")
            return 1
        sleep(1)
    p["pid"].unlink(missing_ok=True)
    out(f"memory: stopped (pid {pid})")
    return 0
