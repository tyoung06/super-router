"""The page server (build brief 23; rules v2.32, Interface): a local page that shows the log and runs `sr` with buttons.

It answers on 127.0.0.1 only, and only when the Host header is 127.0.0.1 or localhost. Other websites can't drive it:
every `/api/` request carries the launch token (random for each run, put into the served page, never printed or
written; without it, 403); a POST must be `application/json` (else 415) with the page's own `Origin` (else 403); no
CORS header is ever sent and OPTIONS gets 405; the CSP allows no inline script. Files reach the page by `fetch` with the
token and a blob URL, never a bare URL.

What it runs: `sr status --json` (kept a minute; a fresh one at most once per 10 s), `sr log --json`, `sr show <task_id>
--json`, `sr project list --json`, the actions the command builder makes (router/page_commands.py) as argument lists in
their own session (router/page_runs.py), its own `sr check --json` (a dead run, brief 22; and once a minute while a task
waits on Grok, decision 7), `sr memory start` at launch when memory is auto, and `open -R` for Open in Finder. Never a
shell string. It never opens router.db and never reads .env: it serves what `sr` printed, which went through the redactor
there. The one file it writes is a file dropped on the page, into the drop folder (router/page_files.py).

`sr serve --demo` serves the invented sample in demo/ the same way and runs nothing: every POST answers "Demo: nothing
runs." Task and result text are untrusted; the page shows them as text."""
import base64
import binascii
import hmac
import json
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from router import page_commands, page_files, page_runs

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
INDEX = STATIC / "index.html"
ALLOWED_HOSTS = ("127.0.0.1", "localhost")
STATUS_SECONDS = 60   # brief 20 (amendment 4) and brief 21: the checks at most once a minute per server
FRESH_SECONDS = 10    # brief 23 (decision 16): "Check again" reads a fresh status at most once per 10 s
GROK_CHECK_SECONDS = 60  # brief 23 (decision 7): `sr check` once a minute while any open task waits on Grok
LOG_LIMIT = 50
COMMAND_TIMEOUT = 120
CHECK_TIMEOUT = 60 * 60  # brief 22: `sr check` may make an agent call while it moves tasks on; brief 24 (C21): a
                         # takeover adds one call of up to 600 s to a check that can already make four
MEMORY_TIMEOUT = 5 * 60  # brief 22: `sr memory start` waits up to 180 s for the store, then backfills
BODY_LIMIT = 1024 * 1024              # a POST's body, except a drop
DROP_BODY_LIMIT = 70 * 1024 * 1024    # a 50 MiB file is about 67 MB as base64
TOKEN_HEADER = "X-SR-Token"
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
STATIC_FILES = {"/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/static/app.css": ("app.css", "text/css; charset=utf-8"),
                "/static/icon.svg": ("icon.svg", "image/svg+xml")}  # brief 23, G: so the browser asks for no /favicon.ico
POSTS = ("/api/command", "/api/run", "/api/drop", "/api/reveal")
DEMO_MESSAGE = "Demo: nothing runs."
RESTARTED = "The page server restarted: reload."


def sr(*args):
    """`sr` as an argument list: this Python, the router module, the arguments as given."""
    return [sys.executable, "-m", "router", *args]


def _in_background(job):
    threading.Thread(target=job, daemon=True).start()


class Reader:
    """Runs the read commands for the page: `sr status --json` (kept STATUS_SECONDS), `sr log --json`, `sr show --json`
    and `sr project list --json`. (HTTP code, body bytes): 200 and the command's one JSON line, or 502 and its error
    (its own JSON on stderr when it gave one). Brief 22: a fresh status that shows a dead run starts `sr check --json`
    through `start` (a thread; tests hand their own). Brief 23: `tick` does the same once a minute while a task waits on
    Grok, behind the same guard; every log read matches running sends to their rows (`runs`)."""

    def __init__(self, run=subprocess.run, clock=time.monotonic, root=ROOT, start=_in_background, runs=None):
        self.run, self.clock, self.root, self.start, self.runs = run, clock, root, start, runs
        self._kept, self._lock, self._checking, self._last_grok, self._fresh = None, threading.Lock(), False, None, None

    def _json(self, argv):
        try:
            proc = self.run(argv, cwd=str(self.root), capture_output=True, text=True, timeout=COMMAND_TIMEOUT,
                            stdin=subprocess.DEVNULL)
        except (subprocess.TimeoutExpired, OSError) as e:
            return 502, json.dumps({"error": f"{argv[3]} did not answer ({type(e).__name__})"}).encode()
        text = (proc.stdout if proc.returncode == 0 else proc.stderr) or ""
        try:
            json.loads(text)
        except ValueError:
            return 502, json.dumps({"error": f"{argv[3]} gave no JSON (exit {proc.returncode})"}).encode()
        return (200 if proc.returncode == 0 else 502), text.strip().encode()

    def status(self, fresh=False):
        with self._lock:
            now = self.clock()
            if fresh and self._kept is not None and (self._fresh is None or now - self._fresh >= FRESH_SECONDS):
                self._kept, self._fresh = None, now  # decision 16: "Check again", at most once per 10 s
            if self._kept is None or now - self._kept[0] >= STATUS_SECONDS:
                code, body = self._json(sr("status", "--json"))
                if code != 200:
                    return code, body  # a failure is never kept
                self._kept = (now, code, body)
                self._after_status(body)
            return self._kept[1], self._kept[2]

    def status_doc(self):
        """The kept status as a document, or None when it can't be read (then nothing can be checked or run)."""
        code, body = self.status()
        try:
            return json.loads(body) if code == 200 else None
        except ValueError:
            return None

    def _after_status(self, body):
        """Brief 22 (decision 4): a run whose process ended, seen in a fresh status: `sr check` once (it writes dead runs)."""
        try:
            running = json.loads(body).get("running") or []
        except (ValueError, AttributeError):
            return
        if self._checking or not any(isinstance(r, dict) and r.get("alive") is False for r in running):
            return
        self._checking = True
        self.start(self._check)

    def tick(self):
        """Brief 23 (decision 7): under --json a command never waits for Grok, so once a minute while any open task waits
        on `grok` (a held piece included) the server runs `sr check --json`, one at a time, behind the dead-run check's
        guard. Brief 24 (decision 7): also while a late Grok answer may still come (`late.state` is `out`), so it is
        collected. Reads `sr log --json`; True when it started a check."""
        code, body = self.log()
        if code != 200:
            return False
        try:
            tasks = json.loads(body).get("tasks") or []
        except (ValueError, AttributeError):
            return False
        if not any(isinstance(t, dict) and (t.get("waiting_on") == "grok" or (t.get("late") or {}).get("state") == "out")
                   for t in tasks):
            return False
        with self._lock:
            now = self.clock()
            if self._checking or (self._last_grok is not None and now - self._last_grok < GROK_CHECK_SECONDS):
                return False
            self._checking, self._last_grok = True, now
        self.start(self._check)
        return True

    def _check(self):
        """`sr check --json` in its own session (brief 23, decision 6), kept in the Run log when the server has one."""
        run_id = self.runs.record("check", "sr check --json") if self.runs is not None else None
        code, stdout, stderr = None, "", ""
        try:
            proc = self.run(sr("check", "--json"), cwd=str(self.root), capture_output=True, text=True,
                            timeout=CHECK_TIMEOUT, stdin=subprocess.DEVNULL, start_new_session=True)
            code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
        except (subprocess.TimeoutExpired, OSError) as e:
            stderr = f"sr check did not finish ({type(e).__name__})"
        finally:
            with self._lock:
                self._checking, self._kept = False, None  # the next status read is fresh
            if run_id is not None:
                self.runs.finished(run_id, code, stdout, stderr)

    def log(self, flags=()):
        code, body = self._json(sr("log", "--json", "--limit", str(LOG_LIMIT), *flags))
        if code == 200 and self.runs is not None:  # brief 23: a send is matched to its row by pid before its envelope
            try:
                self.runs.bind(json.loads(body).get("tasks") or [])
            except (ValueError, AttributeError):
                pass
        return code, body

    def show(self, task_id):
        return self._json(sr("show", task_id, "--json"))

    def projects(self):
        return self._json(sr("project", "list", "--json"))


class DemoReader:
    """Brief 23 (decision 15): the demo's documents, read from the invented files in demo/ (made by
    scripts/make_demo.py). Runs nothing. (HTTP code, body bytes), 404 when the file is missing."""

    def __init__(self, root=None):
        self.root = Path(root) if root is not None else ROOT / "demo"

    def _file(self, name):
        try:
            return 200, (self.root / name).read_bytes().strip()
        except OSError:
            return 404, json.dumps({"error": f"demo file {name} is missing"}).encode()

    def status(self, fresh=False):
        return self._file("status.json")

    def status_doc(self):
        code, body = self.status()
        try:
            return json.loads(body) if code == 200 else None
        except ValueError:
            return None

    def log(self, flags=()):
        code, body = self._file("log.json")
        if code != 200 or not flags:
            return code, body
        doc, wanted = json.loads(body), dict(flag.split("=", 1) for flag in flags)
        tasks = doc.get("tasks") or []
        if wanted.get("--chat"):
            tasks = [t for t in tasks if t.get("chat") == wanted["--chat"]]
        if wanted.get("--project"):
            tasks = [t for t in tasks if t.get("project") == wanted["--project"]]
        if wanted.get("--search"):
            tasks = [t for t in tasks if wanted["--search"].lower() in (t.get("text") or "").lower()]
        return 200, json.dumps({**doc, "tasks": tasks, "next_before": None}).encode()

    def show(self, task_id):
        return self._file(f"tasks/{task_id}.json")

    def projects(self):
        return self._file("projects.json")

    def tick(self):
        return False


def _query(path):
    parts = urlsplit(path)
    return parts.path, {k: v[-1] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}


class _Handler(BaseHTTPRequestHandler):
    # HTTP/1.0 (the default): one request per connection, so a refusal sent before the body is read leaves nothing behind

    def _send(self, code, body, content_type, extra=()):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        for name, value in extra:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, doc, extra=()):
        self._send(code, json.dumps(doc, ensure_ascii=False).encode(), "application/json; charset=utf-8", extra)

    def _sr_json(self, code_body):
        code, body = code_body
        self._send(code, body, "application/json; charset=utf-8")

    def _host_ok(self):
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in ALLOWED_HOSTS:
            self._send(403, b"Forbidden\n", "text/plain; charset=utf-8")
            return False
        return True

    def _token_ok(self):
        given = self.headers.get(TOKEN_HEADER) or ""
        if not hmac.compare_digest(given.encode(), self.server.token.encode()):
            self._json(403, {"error": "token", "message": RESTARTED})
            return False
        return True

    # ---------- GET ----------

    def do_GET(self):
        if not self._host_ok():
            return
        path, query = _query(self.path)
        if path == "/":
            return self._send(200, self.server.index(), "text/html; charset=utf-8")
        if path in STATIC_FILES:
            name, content_type = STATIC_FILES[path]
            try:
                return self._send(200, (STATIC / name).read_bytes(), content_type)
            except OSError:
                return self._send(404, b"Not found\n", "text/plain; charset=utf-8")
        if not path.startswith("/api/"):
            return self._send(404, b"Not found\n", "text/plain; charset=utf-8")
        if not self._token_ok():
            return
        reader = self.server.reader
        if path == "/api/status":
            return self._sr_json(reader.status(fresh=query.get("fresh") == "1"))
        if path == "/api/log":
            try:
                flags = _log_flags(query)
            except page_commands.Refused as e:
                return self._json(400, {"error": str(e)})
            return self._sr_json(reader.log(flags))
        if path.startswith("/api/task/"):
            task_id = unquote(path[len("/api/task/"):])
            if not page_commands.TASK_ID.fullmatch(task_id):
                return self._json(400, {"error": "not a task id"})
            return self._sr_json(reader.show(task_id))
        if path.startswith("/api/files/"):
            try:
                found = page_files.task_files(self.server.files_root(), unquote(path[len("/api/files/"):]))
            except page_files.Refused as e:
                return self._json(400, {"error": str(e)})
            return self._json(200, {"files": found})
        if path == "/api/file":
            return self._file(query)
        if path == "/api/report":
            return self._report()
        if path.startswith("/api/handoff/"):
            return self._handoff(unquote(path[len("/api/handoff/"):]))
        if path == "/api/setup":
            return self._text_file(self.server.root / "docs" / "SETUP.md")
        if path == "/api/runs":
            return self._json(200, {"runs": self.server.run_list()})
        if path == "/api/logfiles":  # brief 23, F: Log files, the tasks/ folder newest first
            try:
                limit = min(int(query.get("limit") or 30), 100)
                return self._json(200, page_files.log_folders(self.server.files_root(), before=query.get("before"), limit=limit))
            except (ValueError, page_files.Refused) as e:
                return self._json(400, {"error": str(e)})
        if path in POSTS:
            return self._send(405, b"Use POST.\n", "text/plain; charset=utf-8", [("Allow", "POST")])
        return self._json(404, {"error": "no such endpoint"})

    def _text_file(self, path):
        try:
            data, total = page_files.read(path)
        except OSError:
            return self._json(404, {"error": "not there"})
        extra = [("X-SR-Truncated", str(total))] if total else []
        return self._send(200, data, "text/plain; charset=utf-8", extra)

    def _allowed_extras(self):
        doc = self.server.reader.status_doc() or {}
        code, body = self.server.reader.projects()
        listed = []
        if code == 200:
            try:
                listed = json.loads(body).get("projects") or []
            except (ValueError, AttributeError):
                listed = []
        handoffs = [str(Path(p["path"]) / "HANDOFF.md") for p in listed if isinstance(p, dict) and p.get("path")]
        return doc.get("report_path"), handoffs, listed

    def _file(self, query):
        report, handoffs, _ = self._allowed_extras() if Path(query.get("path") or "x").is_absolute() else (None, (), ())
        try:
            real = page_files.resolve(self.server.files_root(), query.get("path"), report_path=report, handoffs=handoffs)
            data, total = page_files.read(real)
        except (page_files.Refused, OSError) as e:
            return self._json(404, {"error": str(e) or "not there"})
        extra = [("X-SR-Truncated", str(total))] if total else []
        if query.get("download") == "1":
            extra.append(("Content-Disposition", f"attachment; filename*=UTF-8''{quote(real.name)}"))
        return self._send(200, data, page_files.content_type(real.name), extra)

    def _report(self):
        if self.server.demo:
            return self._text_file(self.server.demo_root / "report.md")
        report = (self.server.reader.status_doc() or {}).get("report_path")
        if not report:
            return self._json(404, {"error": "no report_path is set"})
        try:
            real = page_files.resolve(self.server.root, str(Path(report).expanduser()), report_path=report)
        except page_files.Refused as e:
            return self._json(404, {"error": str(e)})
        return self._text_file(real)

    def _handoff(self, name):
        if self.server.demo:
            if not name or "/" in name or name.startswith("."):
                return self._json(404, {"error": "no such project"})
            return self._text_file(self.server.demo_root / "handoff" / f"{name}.md")
        _, handoffs, listed = self._allowed_extras()
        folder = next((p["path"] for p in listed if isinstance(p, dict) and p.get("name") == name), None)
        if folder is None:
            return self._json(404, {"error": "no such project"})
        try:
            real = page_files.resolve(self.server.root, str(Path(folder) / "HANDOFF.md"), handoffs=handoffs)
        except page_files.Refused as e:
            return self._json(404, {"error": str(e)})
        return self._text_file(real)

    # ---------- POST ----------

    def do_POST(self):
        if not self._host_ok():
            return
        path, _ = _query(self.path)
        if path.startswith("/api/") and not self._token_ok():
            return
        if path not in POSTS:  # a read, the page or anything else: never a POST
            return self._send(405, b"Use GET.\n", "text/plain; charset=utf-8", [("Allow", "GET")])
        content_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            return self._json(415, {"error": "a POST must be application/json"})
        port = self.server.server_address[1]
        if self.headers.get("Origin") not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            return self._json(403, {"error": "origin", "message": "only this page may send to its server"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        limit = DROP_BODY_LIMIT if path == "/api/drop" else BODY_LIMIT
        if length < 0 or length > limit:
            self.close_connection = True
            return self._json(413, {"error": "the request is too big"})
        try:
            doc = json.loads(self.rfile.read(length) or b"null")
        except ValueError:
            return self._json(400, {"error": "the body is not JSON"})
        if not isinstance(doc, dict):
            return self._json(400, {"error": "the body must be a JSON object"})
        if self.server.demo:
            return self._json(409, {"error": "demo", "message": DEMO_MESSAGE})
        if path in ("/api/command", "/api/run"):
            return self._command(doc, run=path == "/api/run")
        if path == "/api/drop":
            return self._drop(doc)
        return self._reveal(doc)

    def _command(self, doc, run):
        status = self.server.reader.status_doc()
        try:
            command = page_commands.build(doc, status)
        except page_commands.Refused as e:
            return self._json(400, {"error": str(e)})
        shown = {"argv": list(command.args), "display": command.display(), "copy": command.copy(),
                 "parts": command.parts()}
        if not run:
            return self._json(200, shown)
        try:
            started = self.server.runs.start(list(command.args), command.display(), kind="action", request=doc)
        except OSError as e:
            return self._json(500, {"error": f"the command could not start ({type(e).__name__})"})
        return self._json(200, {**shown, "run_id": started["id"], "pid": started["pid"]})

    def _drop(self, doc):
        try:
            data = base64.b64decode(doc.get("data") or "", validate=True)
        except (binascii.Error, ValueError, TypeError):
            return self._json(400, {"error": "the file's data is not base64"})
        folder = (self.server.reader.status_doc() or {}).get("drop_folder")
        try:
            written = page_files.drop_write(folder, doc.get("name"), data)
        except (page_files.Refused, OSError) as e:
            return self._json(400, {"error": str(e)})
        return self._json(200, {"path": str(written), "name": written.name, "size": len(data)})

    def _reveal(self, doc):
        report, handoffs, _ = self._allowed_extras() if Path(str(doc.get("path") or "x")).is_absolute() else (None, (), ())
        try:
            page_files.reveal(self.server.files_root(), doc.get("path"), report_path=report, handoffs=handoffs,
                              platform=self.server.platform, run=self.server.reveal_run)
        except page_files.Refused as e:
            return self._json(400, {"error": str(e)})
        return self._json(200, {"ok": True})

    # ---------- everything else ----------

    def _not_allowed(self):
        if self._host_ok():
            self._send(405, b"Not allowed.\n", "text/plain; charset=utf-8", [("Allow", "GET, POST")])

    do_OPTIONS = do_PUT = do_PATCH = do_DELETE = _not_allowed

    def log_message(self, format, *args):
        pass  # keep the terminal quiet


def _log_flags(query):
    """`sr log` filters from the page's query: each value plain (no leading -, no control character); `before` a task id."""
    flags = []
    for key in ("chat", "project", "search"):
        value = query.get(key)
        if value:
            if key != "search":
                page_commands._value(value, f"the {key}")
            elif page_commands._control(value):
                raise page_commands.Refused("the search holds a control character")
            flags.append(f"--{key}={value}")
    if query.get("before"):
        flags.append(f"--before={page_commands._task_id(query['before'], 'before')}")
    return flags


class PageServer(ThreadingHTTPServer):
    daemon_threads = True

    def index(self):
        text = INDEX.read_text(encoding="utf-8")
        reveal = "1" if self.platform == "darwin" and not self.demo else "0"
        return (text.replace("__SR_TOKEN__", self.token).replace("__SR_DEMO__", "1" if self.demo else "0")
                .replace("__SR_REVEAL__", reveal).encode())

    def files_root(self):
        return self.demo_root / "files" if self.demo else self.root

    def run_list(self):
        if self.demo:
            try:
                return json.loads((self.demo_root / "runs.json").read_text(encoding="utf-8")).get("runs") or []
            except (OSError, ValueError):
                return []
        return [{k: v for k, v in run.items() if k != "request"} for run in self.runs.list()]


def make_server(port, reader=None, *, runs=None, demo=False, demo_root=None, root=None, platform=None, token=None):
    server = PageServer((HOST, port), _Handler)
    server.token = token or secrets.token_urlsafe(32)  # decision 2: in the served page only; never printed or written
    server.demo, server.root = demo, Path(root) if root is not None else ROOT
    server.demo_root = Path(demo_root) if demo_root is not None else ROOT / "demo"
    server.platform = platform or sys.platform
    server.reveal_run = subprocess.run  # decision 11: `open -R` (tests hand their own)
    server.runs = runs if runs is not None or demo else page_runs.Runs(root=server.root)
    server.reader = reader or (DemoReader(server.demo_root) if demo else Reader(root=server.root, runs=server.runs))
    return server


def start_memory(run=subprocess.run, root=ROOT, out=print, runs=None):
    """Brief 22 (decision 8): `sr memory start` (which backfills after the start), as an argument list from the repo
    folder, in its own session (brief 23, decision 6); its lines go to this terminal and, brief 23, to the Run log."""
    run_id = runs.record("memory", "sr memory start") if runs is not None else None
    try:
        proc = run(sr("memory", "start"), cwd=str(root), capture_output=True, text=True, timeout=MEMORY_TIMEOUT,
                   stdin=subprocess.DEVNULL, start_new_session=True)
    except (subprocess.TimeoutExpired, OSError) as e:
        out(f"memory: could not start ({type(e).__name__})")
        if run_id is not None:
            runs.finished(run_id, None, "", f"memory: could not start ({type(e).__name__})")
        return
    for line in (proc.stdout or "").splitlines():
        out(line)
    if run_id is not None:
        runs.finished(run_id, proc.returncode, proc.stdout, proc.stderr)


def start_line(port):
    """Brief 23: where the page is, and that the tasks it started outlive it."""
    return f"Page: http://{HOST}:{port}  (Ctrl+C stops the page; tasks it started keep running)"


def demo_line(port):
    return f"Demo: http://{HOST}:{port}  (sample tasks, nothing runs; Ctrl+C stops it)"


def ticker(reader, *, sleep=time.sleep, every=GROK_CHECK_SECONDS, rounds=None):
    """Brief 23 (decision 7): `reader.tick()` once a minute for as long as the server runs (`rounds` for tests). A tick
    that fails is let go; the next one tries again."""
    done = 0
    while rounds is None or done < rounds:
        sleep(every)
        try:
            reader.tick()
        except Exception:  # never let the ticker die: the next minute tries again
            pass
        done += 1


def serve_demo(port=DEFAULT_PORT, out=print, root=None):
    """`sr serve --demo`: the page on the invented sample; no command runs, no file is written."""
    server = make_server(port, demo=True, demo_root=root)
    out(demo_line(server.server_address[1]))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def serve(port=DEFAULT_PORT, reader=None, out=print, start_memory=None):
    server = make_server(port, reader)
    out(start_line(server.server_address[1]))
    threading.Thread(target=ticker, args=(server.reader,), daemon=True).start()  # brief 23: the minute Grok check
    if start_memory is not None:  # brief 22 (decision 8): on its own thread, so the page answers at once
        threading.Thread(target=lambda: start_memory(out=out, runs=getattr(server, "runs", None)), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
