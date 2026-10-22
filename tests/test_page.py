"""Status page tests (build brief 21, B4: the page reads the JSON commands). The server runs `sr status --json` (kept a
minute per server) and `sr log --json` as argument lists from the repo folder and serves what they print, which went
through the redactor in `sr`; it never opens router.db and never reads .env. Bound to 127.0.0.1, GET only, the Host
header checked. The only network use is 127.0.0.1 inside the test; the two commands are fakes."""
import http.client
import json
import re
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from router import __main__ as cli
from router import page

INDEX = Path(__file__).resolve().parent.parent / "static" / "index.html"
APP_JS = INDEX.parent / "app.js"  # brief 23: the page's script left index.html (the CSP allows no inline script)


def _page_text():
    return INDEX.read_text() + APP_JS.read_text() + (INDEX.parent / "app.css").read_text()
STATUS = {"agents": [{"name": "cursor", "online": True}], "api_version": 1}
LOG = {"api_version": 1, "tasks": [{"task_id": "sr-b"}, {"task_id": "sr-a"}], "next_before": None}


class Commands:
    """A fake `subprocess.run` for the two commands: records each argv and where it ran; answers per subcommand."""

    def __init__(self, status=STATUS, log=LOG, fail=()):
        self.calls, self.answers, self.fail = [], {"status": status, "log": log}, fail

    def __call__(self, argv, **kw):
        assert isinstance(argv, list) and not kw.get("shell"), "an argument list, never a shell string"
        self.calls.append((argv, kw))
        name = argv[3]
        if name in self.fail:
            return SimpleNamespace(returncode=1, stdout="", stderr=json.dumps({"reason_code": "setup", "exit": 1}))
        return SimpleNamespace(returncode=0, stdout=json.dumps(self.answers[name]) + "\n", stderr="")


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _serve(reader):
    srv = page.make_server(0, reader)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def commands():
    return Commands()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def server(commands, clock):
    srv = _serve(page.Reader(run=commands, clock=clock))
    yield srv
    srv.shutdown()
    srv.server_close()


def _request(srv, path, host=None, method="GET"):
    port = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.putrequest(method, path, skip_host=True)
    conn.putheader("Host", host or f"127.0.0.1:{port}")
    conn.putheader("X-SR-Token", srv.token)  # brief 23 (decision 2): every /api request carries the launch token
    conn.endheaders()
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp, body


# ---------- the server ----------

def test_page_make_server_binds_localhost_only():
    srv = page.make_server(0, page.Reader(run=Commands()))
    try:
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        srv.server_close()


def test_api_status_is_sr_status_json_run_as_an_argument_list_from_the_repo(server, commands):
    resp, body = _request(server, "/api/status")
    assert resp.status == 200 and resp.getheader("Content-Type").startswith("application/json")
    assert resp.getheader("Cache-Control") == "no-store"
    assert json.loads(body) == STATUS
    argv, kw = commands.calls[0]
    assert argv == [sys.executable, "-m", "router", "status", "--json"] and kw["cwd"] == str(page.ROOT)


def test_the_status_is_kept_a_minute_per_server_and_the_log_runs_every_poll(server, commands, clock):
    for _ in range(12):  # the page polls every 5 s
        assert _request(server, "/api/status")[0].status == 200
        assert _request(server, "/api/log")[0].status == 200
        clock.t += 5
    names = [argv[3] for argv, _ in commands.calls]
    assert names.count("status") == 1 and names.count("log") == 12 and page.STATUS_SECONDS == 60
    clock.t = 61
    _request(server, "/api/status")
    assert [argv[3] for argv, _ in commands.calls].count("status") == 2


def test_api_log_is_sr_log_json_with_a_limit(server, commands):
    resp, body = _request(server, "/api/log")
    assert resp.status == 200 and [t["task_id"] for t in json.loads(body)["tasks"]] == ["sr-b", "sr-a"]
    assert commands.calls[0][0] == [sys.executable, "-m", "router", "log", "--json", "--limit", str(page.LOG_LIMIT)]


def test_a_failing_command_is_served_as_502_with_its_own_json_and_never_kept(clock):
    commands = Commands(fail=("status",))
    srv = _serve(page.Reader(run=commands, clock=clock))
    try:
        resp, body = _request(srv, "/api/status")
        assert resp.status == 502 and json.loads(body)["reason_code"] == "setup"
        _request(srv, "/api/status")
        assert [argv[3] for argv, _ in commands.calls].count("status") == 2  # a failure is never kept
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_command_that_gives_no_json_is_502(clock):
    def run(argv, **kw):
        return SimpleNamespace(returncode=0, stdout="Traceback ...", stderr="")
    srv = _serve(page.Reader(run=run, clock=clock))
    try:
        resp, body = _request(srv, "/api/log")
        assert resp.status == 502 and json.loads(body) == {"error": "log gave no JSON (exit 0)"}
    finally:
        srv.shutdown()
        srv.server_close()


def test_the_server_never_opens_the_log_or_reads_env():
    names = set(vars(page))
    assert not names & {"log", "sqlite3", "dotenv_values", "safety"}
    text = Path(page.__file__).read_text()
    assert ".env" not in text.replace("never reads .env", "") and "router.db" not in text.replace(
        "never opens router.db", "").replace("reading of the log", "")


def test_page_serves_index_html_with_a_content_policy(server):
    resp, body = _request(server, "/")
    assert resp.status == 200 and resp.getheader("Content-Type").startswith("text/html")
    assert b"Super Router" in body
    assert "connect-src 'self'" in resp.getheader("Content-Security-Policy")


def test_page_unknown_path_is_404(server):
    assert _request(server, "/router.db")[0].status == 404


def test_page_rejects_other_host_names(server):
    port = server.server_address[1]
    assert _request(server, "/api/status", host="evil.example")[0].status == 403
    assert _request(server, "/api/status", host=f"localhost:{port}")[0].status == 200


def test_a_post_to_a_read_path_is_405(server):  # brief 23: the page sends actions now, but never to a read path
    assert _request(server, "/api/status", method="POST")[0].status == 405


def test_main_serves_on_the_settings_port_with_nothing_else(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.page, "serve", lambda port, **kw: seen.update(port=port, **kw) or 0)
    assert cli.main(["serve"], platform="darwin") == 0
    assert seen["port"] == 8765 and set(seen) == {"port", "out", "start_memory"}  # brief 22: memory at launch
    assert cli.main(["serve", "--port", "9000"], platform="darwin") == 0 and seen["port"] == 9000


# ---------- index.html ----------

def test_page_html_shows_text_never_html():
    text = _page_text()
    for unsafe in ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("]:
        assert unsafe not in text
    assert "textContent" in text


def test_the_page_script_reads_its_json_through_the_server_with_the_token():
    # Brief 23: the old read-only table is gone; the page reads the same JSON through the server, with the launch token,
    # and sends actions only to the server. What it draws from that JSON is tested in tests/js (node --test).
    text = APP_JS.read_text()
    for path in ('"/api/status"', '"/api/log"', '"/api/runs"', '"/api/command"', '"/api/run"', '"/api/drop"'):
        assert path in text, path
    assert '"X-SR-Token": state.token' in text
    assert set(re.findall(r"https?://([\w.-]+)", text)) <= {"www.w3.org"}  # the SVG namespace, never fetched


def test_page_html_loads_nothing_from_outside():
    text = INDEX.read_text()
    sources = re.findall(r"<(?:script|link|img|iframe)[^>]*?(?:src|href)\s*=\s*\"([^\"]*)\"", text)
    assert sources and all(s.startswith("/static/") for s in sources)  # brief 23: only the page's own two files
    assert "<script>" not in text and "<style>" not in text and " style=" not in text
