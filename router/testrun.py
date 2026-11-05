"""The project's tests, run by the router (rules 2.40, Project files, Tests; build brief 28, decisions 5 and 17).

No agent runs a command, tests included: the router runs the project's test command itself, after each Claude build or
fix call, on a throwaway copy of the copy, so nothing a test writes (caches, outputs) is ever part of the change. The
command is the project's words (`sr project tests`), run as an argument list, never through a shell, under macOS
`sandbox-exec` with a profile written here:

- nothing is allowed but what the profile names (`deny default`), so no network, no Mach service (the keychain, the
  pasteboard, opening a URL in another app) and no shared memory;
- reads of the system folders, the throwaway's three folders and, when the first word starts with `.venv/` or `venv/`,
  that environment folder in the project, read only; nothing else under the home folder, not even a file's details;
- writes only in the throwaway's three folders (the copy, its home, its temp folder);
- an environment of four names built from scratch: PATH (without its home folder entries), LANG, and HOME and TMPDIR
  pointing inside the throwaway; no key and no `.env` value reaches it;
- a time limit (300 s by default), after which the whole process group is killed.

Its output (stdout and stderr together) is redacted and cut to its last 20,000 characters; the caller keeps it as
`tasks/<task_id>/tests-<k>.txt` and sums it up on the call row. The last rule that matches wins in a profile (Phase 0,
Proof 2), so the home folder's deny comes after the system reads and before the one environment folder."""
import codecs
import os
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from router import safety

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
TIMEOUT = 300           # seconds (decision 5)
OUTPUT_CHARS = 20_000   # the output's tail kept and shown
READ_CAP = 1_000_000    # bytes kept while reading: a test that prints without end can't fill the memory
LIVE_CAP = 2_000_000    # brief 31: the live file's characters before it is cut to its last half
LIVE_LINE = 65_536      # brief 31: a line with no end is written in pieces of this size
WORDS_LIMIT = 300       # characters in the stored command (decision 17)
ENV_PREFIXES = (".venv/", "venv/")
FOLDERS = ("project", "home", "tmp")  # the throwaway's three folders; the copy is `project`, the working folder
SYSTEM_READS = ("/usr", "/bin", "/sbin", "/System", "/Library", "/Applications", "/opt", "/private/etc",
                "/private/var/db/timezone", "/private/var/select", "/dev")
OUTCOMES = ("passed", "failed", "timed_out")


class TestsError(safety.SafeError):
    """A command the router won't store or run: the reason, with no secret in it."""


@dataclass(frozen=True)
class Result:
    exit: object      # the exit code, or None when the time limit killed it
    outcome: str      # passed, failed or timed_out
    summary: str      # the output's last non-empty line, cut to 200 characters
    output: str       # redacted, its last OUTPUT_CHARS characters

    def record(self):
        """What the call row keeps (decision 19, `tests`): the output is the file's name, set by the caller."""
        return {"exit": self.exit, "outcome": self.outcome, "summary": self.summary}


def available():
    """Whether this Mac has `sandbox-exec` (without it tests stay off, and status says why)."""
    return Path(SANDBOX_EXEC).exists()


# ---------- the command (decision 17) ----------

def split_words(text):
    """The stored words of a test command typed as one line: split as a shell would split them (`shlex.split`), never
    run through one. TestsError when it is empty, past WORDS_LIMIT characters or can't be split."""
    if not isinstance(text, str) or not text.strip():
        raise TestsError("the test command is empty")
    if len(text) > WORDS_LIMIT:
        raise TestsError(f"the test command is {len(text):,} characters; at most {WORDS_LIMIT}")
    if any(ord(ch) < 32 for ch in text):
        raise TestsError("the test command holds a control character")
    try:
        words = shlex.split(text)
    except ValueError as e:
        raise TestsError(f"the test command can't be split into words ({e})") from None
    if not words:
        raise TestsError("the test command is empty")
    return words


def env_folder(words, folder):
    """The project's environment folder the first word names (`.venv/bin/python` -> `<folder>/.venv`), or None when the
    first word does not start with `.venv/` or `venv/`."""
    first = words[0]
    for prefix in ENV_PREFIXES:
        if first.startswith(prefix):
            return Path(folder) / prefix.rstrip("/")
    return None


def check_words(words, folder):
    """Why these words can't be the project's test command, or None: a `.venv/` or `venv/` first word must be a file in
    the project folder (it is run from there, never from the copy, which holds no environment), inside its folder."""
    env = env_folder(words, folder)
    if env is None:
        return None
    program = Path(folder) / words[0]
    try:
        real, root = program.resolve(), env.resolve()
    except OSError:
        return f"{words[0]} could not be resolved in the project folder"
    if ".." in Path(words[0]).parts:
        return f"{words[0]} leaves its environment folder"
    if not program.is_file():
        return f"{words[0]} is not in the project folder"
    if not (real.is_relative_to(root) or program.parent.resolve().is_relative_to(root)):
        return f"{words[0]} leaves its environment folder"
    return None


# ---------- the sandbox ----------

def _quote(path):
    text = str(path)
    if any(ord(ch) < 32 for ch in text):
        raise TestsError("a folder name holds a control character")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ancestors(path):
    """Every folder above `path`, root first, as resolved paths: their details (not their listing) are readable, so a
    program can resolve the path it runs from."""
    found = []
    for parent in reversed(Path(path).parents):
        found.append(parent)
    return found


def profile(throwaway, *, home, env=None):
    """The sandbox-exec profile for one run (Proof 2's, built per run). `throwaway` is the run's own folder (its three
    folders are the only writable places), `home` the home folder (nothing under it is readable), `env` the project's
    environment folder, read only, or None."""
    throwaway, home = Path(throwaway), Path(home)
    inside = [throwaway / name for name in FOLDERS]
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process-exec process-fork)",
        "(allow file-map-executable)",
        "(allow sysctl-read)",
        "(allow signal (target same-sandbox))",
        "(allow file-read* (literal \"/\") " + " ".join(f"(subpath {_quote(p)})" for p in SYSTEM_READS) + ")",
        "(allow file-read-metadata " + " ".join(f"(literal {_quote(p)})" for p in _ancestors(throwaway / "x")) + ")",
        "(allow file-read* file-write* " + " ".join(f"(subpath {_quote(p)})" for p in inside) + ")",
        "(allow file-write-data (literal \"/dev/null\"))",
        f"(deny file-read* (subpath {_quote(home)}))",
    ]
    if env is not None:
        env = Path(env)
        lines.append("(allow file-read-metadata " + " ".join(f"(literal {_quote(p)})" for p in _ancestors(env)) + ")")
        lines.append(f"(allow file-read* (subpath {_quote(env)}))")
    if throwaway.is_relative_to(home):  # never by default (the system's temp folder), but a run there stays readable
        lines.append("(allow file-read-metadata " + " ".join(f"(literal {_quote(p)})" for p in _ancestors(throwaway / "x"))
                     + ")")
        lines.append("(allow file-read* " + " ".join(f"(subpath {_quote(p)})" for p in inside) + ")")
    return "\n".join(lines) + "\n"


def environment(throwaway, environ, home):
    """The four names a run gets (decision 5): PATH without the entries under the home folder (nothing there is
    readable), LANG, and HOME and TMPDIR inside the throwaway."""
    home = Path(home)
    kept = []
    for entry in (environ.get("PATH") or "/usr/bin:/bin:/usr/sbin:/sbin").split(os.pathsep):
        if not entry:
            continue
        try:
            under = Path(entry).expanduser().resolve().is_relative_to(home.resolve())
        except OSError:
            continue
        if not under and entry not in kept:
            kept.append(entry)
    return {"PATH": os.pathsep.join(kept), "LANG": environ.get("LANG") or "en_US.UTF-8",
            "HOME": str(Path(throwaway) / "home"), "TMPDIR": str(Path(throwaway) / "tmp") + "/"}


# ---------- one run ----------

def _summary(output):
    for line in reversed(output.splitlines()):
        if line.strip():
            return line.strip()[:200]
    return ""


def _reader(stream, kept, live=None, secrets=()):
    """Read the child's output to its end, keeping only the last READ_CAP bytes. Brief 31 (decision 2): with `live`, each
    whole line is also appended to that file as it arrives, redacted, so a page can show a Test while it runs; a line
    with no end yet is written in pieces past LIVE_LINE, holding back the longest secret's length so a value split
    across two pieces is still caught."""
    size = 0
    writer = _Live(live, secrets) if live is not None else None
    read = getattr(stream, "read1", stream.read)  # read1: what has arrived, so the live file follows the run
    try:
        while True:
            chunk = read(65536)
            if not chunk:
                return
            kept.append(chunk)
            size += len(chunk)
            while size - len(kept[0]) >= READ_CAP and len(kept) > 1:
                size -= len(kept.popleft())
            if writer is not None:
                writer.add(chunk)
    finally:
        if writer is not None:
            writer.close()


class _Live:
    """Brief 31: the live file of a run's output, whole lines, redacted before they are written."""

    def __init__(self, path, secrets):
        self.path, self.secrets = Path(path), [s for s in secrets if s]
        self.hold = max((len(s) for s in self.secrets), default=1) - 1
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.pending = ""
        self.file = open(self.path, "a", encoding="utf-8")
        os.chmod(self.path, 0o600)

    def _write(self, text):
        if not text:
            return
        self.file.write(safety.redact(text, self.secrets))
        self.file.flush()
        if self.file.tell() > LIVE_CAP:  # keep the newest half, from a line start
            self.file.close()
            data = self.path.read_text(encoding="utf-8", errors="replace")[-LIVE_CAP // 2:]
            self.path.write_text(data[data.find("\n") + 1:] if "\n" in data else data, encoding="utf-8")
            self.file = open(self.path, "a", encoding="utf-8")

    def add(self, chunk):
        self.pending += self.decoder.decode(chunk)
        cut = self.pending.rfind("\n") + 1
        if cut:
            self._write(self.pending[:cut])
            self.pending = self.pending[cut:]
        if len(self.pending) > LIVE_LINE + self.hold:
            keep = self.hold
            self._write(self.pending[:len(self.pending) - keep])
            self.pending = self.pending[len(self.pending) - keep:]

    def close(self):
        self.pending += self.decoder.decode(b"", final=True)
        self._write(self.pending)
        self.pending = ""
        self.file.close()


def _kill_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def make_throwaway(copy_folder, temp_root=None):
    """A fresh folder in the system's temp folder holding `project` (the copy, links kept as links, never followed),
    `home` and `tmp`. The caller removes it (remove_throwaway)."""
    root = Path(tempfile.mkdtemp(prefix="sr-tests-", dir=temp_root)).resolve()
    try:  # brief 29.1 (issue 18): a copy that fails half-way leaves no folder behind
        shutil.copytree(copy_folder, root / "project", symlinks=True)
        (root / "home").mkdir()
        (root / "tmp").mkdir()
    except BaseException:
        remove_throwaway(root)
        raise
    return root


def remove_throwaway(root):
    """The run's own throwaway gone, whatever the tests left in it: a folder they made unwritable is made the owner's again
    (never through a link) and the removal tried once more (brief 28's issue 18: empty `sr-tests-*` folders were left)."""
    shutil.rmtree(root, ignore_errors=True)
    if not os.path.lexists(root):
        return
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in [dirpath] + [os.path.join(dirpath, d) for d in dirnames]:
            if not os.path.islink(name):
                try:
                    os.chmod(name, 0o700)
                except OSError:
                    pass
    shutil.rmtree(root, ignore_errors=True)


def run(copy_folder, words, *, project_folder, secrets=(), timeout=TIMEOUT, environ=None, home=None, popen=None,
        temp_root=None, live=None):
    """Run the project's test words on a throwaway copy of `copy_folder`, in the sandbox, and return the Result. The
    copy is never touched; the throwaway is removed after. `popen` is subprocess.Popen (tests pass the real one).
    `live` (brief 31): a file that gets the output's whole lines, redacted, while the run goes."""
    environ = os.environ if environ is None else environ
    home = Path(home or Path.home()).resolve()
    popen = popen or subprocess.Popen
    words = list(words)
    env = env_folder(words, project_folder)
    if env is not None:
        words[0] = str(Path(project_folder) / words[0])
        env = env.resolve()
    root = make_throwaway(copy_folder, temp_root)  # it removes its own folder when it fails
    try:
        argv = [SANDBOX_EXEC, "-p", profile(root, home=home, env=env), *words]
        kept = deque()
        try:
            proc = popen(argv, cwd=str(root / "project"), env=environment(root, environ, home), stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as e:
            return Result(None, "failed", f"the test command could not start ({type(e).__name__})", "")
        reader = threading.Thread(target=_reader, args=(proc.stdout, kept, live, secrets), daemon=True)
        reader.start()
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_group(proc)
            proc.wait()
        _kill_group(proc)  # a child the test left behind in its group goes too
        reader.join(timeout=5)
        text = b"".join(kept).decode("utf-8", errors="replace")
        text = safety.redact(text, secrets)[-OUTPUT_CHARS:]
        if timed_out:
            return Result(None, "timed_out", f"timed out after {timeout} s", text)
        code = proc.returncode
        return Result(code, "passed" if code == 0 else "failed", _summary(text), text)
    finally:
        remove_throwaway(root)


def line(result):
    """The card's and the prose's tests line (decision 20)."""
    if result is None:
        return "no tests run: no test command"
    if result.get("outcome") == "passed":
        return "tests passed"
    if result.get("outcome") == "timed_out":
        return "tests timed out"
    if result.get("exit") is None:
        return "tests failed"
    return f"tests failed (exit {result['exit']})"


def wait_gone(pgid, seconds=3.0, sleep=time.sleep):
    """True once no process is left in the group (the time-limit kill's check, used by the proof and the tests)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        sleep(0.05)
    return False
