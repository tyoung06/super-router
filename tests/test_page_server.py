"""Build brief 23, A8 (decisions 2, 3, 4, 8, 9, 11, 15, 16; the server tests the brief lists): the page server on a fixture
repo. Other websites can't drive it: the launch token on every `/api/` request (else 403), a POST only as
`application/json` (else 415) from the page's own Origin (else 403), no CORS header ever, OPTIONS 405, the Host check,
a CSP with no inline script, the bind on 127.0.0.1. `/api/run` answers before a 3-second command ends, and the typed
text reaches `sr` as one argument after `--`; a refused request runs nothing. Every endpoint answers against a fixture
whose `.env` has mode 000 (the server never opens it), and no file outside the drop folder changes. The demo runs no
subprocess and refuses every POST. The reads are a fake; the actions run tests/fake_sr.py (no router, no model)."""
import base64
import http.client
import json
import os
import stat
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from router import page, page_runs

FAKE_SR = Path(__file__).resolve().parent / "fake_sr.py"
TID, OTHER = "sr-20261021-000803-3d77", "sr-20261021-000901-ab12"
TEXT = 'He said "hi" & it\'s `ls` $HOME\nline two --skill coding -h @grok'


# ---------- the fixture repo and the fake reads ----------

@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    for folder in ("tasks", "media/in", "media/out", "docs", "backups", "config"):
        (r / folder).mkdir(parents=True)
    (r / "tasks" / TID).mkdir()
    (r / "tasks" / TID / "01-do-claude.md").write_text("the answer, **bold**")
    (r / "tasks" / OTHER).mkdir()
    (r / "tasks" / OTHER / "01-do-grok.md").write_text("another task")
    (r / "tasks" / TID / "02-link.md").symlink_to(r / "tasks" / OTHER / "01-do-grok.md")
    (r / "media" / "in" / TID).mkdir()
    (r / "media" / "in" / TID / "pic.png").write_bytes(b"\x89PNG")
    (r / "router.db").write_bytes(b"SQLite")
    (r / "backups" / "router-v14.db").write_bytes(b"SQLite")
    (r / "config" / "agents.json").write_text("{}")
    env = r / ".env"
    env.write_text("JEV_API_KEY=FAKE-KEY-55")
    env.chmod(0)
    (tmp_path / "report.md").write_text("the report")
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "HANDOFF.md").write_text("the handoff")
    (tmp_path / "Router Drop").mkdir()
    yield r
    env.chmod(0o600)


def _status_doc(tmp_path):
    every = ["claude", "grok", "chatgpt"]
    return {"api_version": 1, "running": [],
            "presets": [{"name": "versus", "slots": [{"name": "a", "default": "claude", "allowed": every + ["cursor"]},
                                                     {"name": "b", "default": "chatgpt", "allowed": every + ["cursor"]}]}],
            "skills": [{"key": "code"}, {"key": "planning"}], "drop_folder": str(tmp_path / "Router Drop"),
            "report_path": str(tmp_path / "report.md")}


class Reads:
    """A fake subprocess.run for the read commands: answers each from fixed JSON and records the argv."""

    def __init__(self, tmp_path, log_tasks=()):
        self.tmp, self.calls, self.log_tasks = tmp_path, [], list(log_tasks)

    def __call__(self, argv, **kw):
        assert isinstance(argv, list) and not kw.get("shell")
        self.calls.append(argv)
        name = argv[3]
        doc = {"status": _status_doc(self.tmp), "log": {"api_version": 1, "tasks": self.log_tasks, "next_before": None},
               "show": {"api_version": 1, "task_id": argv[4] if len(argv) > 4 else None},
               "project": {"api_version": 1, "projects": [{"name": "proj", "path": str(self.tmp / "proj")}]},
               "check": {"exit": 0, "message": "checked"}}[name]
        return SimpleNamespace(returncode=0, stdout=json.dumps(doc) + "\n", stderr="")

    def count(self, name):
        return sum(1 for argv in self.calls if argv[3] == name)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def world(repo, tmp_path):
    reads, clock = Reads(tmp_path), Clock()
    runs = page_runs.Runs(root=repo, prefix=[sys.executable, str(FAKE_SR)])
    reader = page.Reader(run=reads, clock=clock, root=repo, start=lambda job: None, runs=runs)
    srv = page.make_server(0, reader, runs=runs, root=repo, platform="darwin")
    seen = []
    srv.reveal_run = lambda argv, **kw: seen.append((argv, kw)) or SimpleNamespace(returncode=0)
    import threading
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield SimpleNamespace(srv=srv, reads=reads, clock=clock, runs=runs, revealed=seen, repo=repo, tmp=tmp_path)
    srv.shutdown()
    srv.server_close()


def _call(srv, method, path, body=None, *, token=True, origin=True, ctype="application/json", host=None):
    port = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    data = json.dumps(body).encode() if isinstance(body, (dict, list)) else (body or b"")
    conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    conn.putheader("Host", host or f"127.0.0.1:{port}")
    if token:
        conn.putheader("X-SR-Token", srv.token if token is True else token)
    if method == "POST":
        if ctype:
            conn.putheader("Content-Type", ctype)
        if origin:
            conn.putheader("Origin", origin if isinstance(origin, str) else f"http://127.0.0.1:{port}")
        conn.putheader("Content-Length", str(len(data)))
    conn.endheaders(data if method == "POST" else None)
    resp = conn.getresponse()
    out = resp.read()
    conn.close()
    return resp, out


GETS = ["/api/status", "/api/log", f"/api/task/{TID}", f"/api/files/{TID}", f"/api/file?path=tasks/{TID}/01-do-claude.md",
        "/api/report", "/api/handoff/proj", "/api/setup", "/api/runs", "/api/logfiles"]
POSTS = {"/api/command": {"action": "check"}, "/api/run": {"action": "check"},
         "/api/drop": {"name": "a.png", "data": base64.b64encode(b"x").decode()}, "/api/reveal": {"path": "x"}}


def _wait(runs, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if all(not r["running"] for r in runs.list()):
            return runs.list()
        time.sleep(0.05)
    raise AssertionError("a run is still going")


# ---------- other websites can't drive it (decision 2) ----------

def test_the_bind_is_loopback_only(world):
    assert world.srv.server_address[0] == "127.0.0.1"


def test_no_token_or_a_wrong_one_is_403_on_every_api_path(world):
    for token in (False, "wrong-token"):
        for path in GETS + ["/api/nothing"]:
            resp, body = _call(world.srv, "GET", path, token=token)
            assert resp.status == 403 and json.loads(body)["error"] == "token", (token, path)
        for path, body in POSTS.items():
            resp, out = _call(world.srv, "POST", path, body, token=token)
            assert resp.status == 403 and json.loads(out)["message"] == page.RESTARTED, (token, path)
    assert world.runs.list() == [] and list((world.tmp / "Router Drop").iterdir()) == []


def test_a_wrong_or_missing_origin_is_403(world):
    for origin in ("https://evil.example", "http://127.0.0.1:1", "null", False):
        resp, out = _call(world.srv, "POST", "/api/run", {"action": "check"}, origin=origin)
        assert resp.status == 403 and json.loads(out)["error"] == "origin", origin
    port = world.srv.server_address[1]
    assert _call(world.srv, "POST", "/api/command", {"action": "check"}, origin=f"http://localhost:{port}")[0].status == 200
    assert world.runs.list() == []


def test_a_post_that_is_not_json_is_415(world):
    for ctype in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data", None):
        assert _call(world.srv, "POST", "/api/run", {"action": "check"}, ctype=ctype)[0].status == 415, ctype
    assert world.runs.list() == []


def test_options_is_405_and_no_answer_carries_a_cors_header(world):
    resp, _ = _call(world.srv, "OPTIONS", "/api/run")
    assert resp.status == 405
    answers = [resp] + [_call(world.srv, "GET", p)[0] for p in ["/", "/static/app.js"] + GETS]
    answers += [_call(world.srv, "POST", p, b)[0] for p, b in POSTS.items()]
    answers += [_call(world.srv, "GET", "/api/status", token=False)[0]]
    for resp in answers:
        assert not [h for h in resp.getheaders() if h[0].lower().startswith("access-control-")]


def test_the_host_check_stands(world):
    for path in ("/", "/api/status", "/static/app.js"):
        assert _call(world.srv, "GET", path, host="evil.example")[0].status == 403
    assert _call(world.srv, "POST", "/api/run", {"action": "check"}, host="evil.example")[0].status == 403


def test_the_page_carries_its_token_and_a_csp_with_no_inline_script(world):
    resp, body = _call(world.srv, "GET", "/", token=False)
    assert resp.status == 200 and f'<meta name="sr-token" content="{world.srv.token}">'.encode() in body
    assert b'<meta name="sr-reveal" content="1">' in body and b'<meta name="sr-demo" content="0">' in body
    assert resp.getheader("Content-Security-Policy") == page.CSP and "'unsafe-inline'" not in page.CSP
    assert "script-src 'self'" in page.CSP and "img-src 'self' blob:" in page.CSP
    assert resp.getheader("Cache-Control") == "no-store" and resp.getheader("Referrer-Policy") == "no-referrer"
    other = page.make_server(0, page.Reader(run=Reads(world.tmp)))
    import threading
    threading.Thread(target=other.serve_forever, daemon=True).start()
    try:
        assert other.token != world.srv.token and len(world.srv.token) >= 40
        assert _call(other, "GET", "/api/status", token=world.srv.token)[0].status == 403  # a restarted server
    finally:
        other.shutdown()
        other.server_close()


def test_static_serves_its_three_files_and_nothing_else(world):
    resp, _ = _call(world.srv, "GET", "/static/app.js", token=False)
    assert resp.status == 200 and resp.getheader("Content-Type").startswith("text/javascript")
    assert _call(world.srv, "GET", "/static/app.css", token=False)[0].getheader("Content-Type").startswith("text/css")
    # brief 23, G: the page's icon, so the browser asks for no /favicon.ico (its 404 was the page's one console error)
    resp, body = _call(world.srv, "GET", "/static/icon.svg", token=False)
    assert resp.status == 200 and resp.getheader("Content-Type") == "image/svg+xml" and body.startswith(b"<svg")
    assert b'<link rel="icon" href="/static/icon.svg" type="image/svg+xml">' in _call(world.srv, "GET", "/", token=False)[1]
    for path in ("/static/index.html", "/static/../router.db", "/router.db", "/.env", "/static/app.js.map"):
        assert _call(world.srv, "GET", path, token=False)[0].status == 404, path


# ---------- actions (decisions 3, 4, 6) ----------

def test_api_run_answers_before_a_three_second_command_ends_and_the_text_reaches_sr_as_one_argument(world, monkeypatch):
    out = world.tmp / "argv.jsonl"
    monkeypatch.setenv("FAKE_SR_SLEEP", "3")
    monkeypatch.setenv("FAKE_SR_OUT", str(out))
    began = time.monotonic()
    resp, body = _call(world.srv, "POST", "/api/run", {"action": "send", "team": "route", "text": TEXT, "chat": "brief23"})
    assert resp.status == 200 and time.monotonic() - began < 1.5
    found = json.loads(body)
    assert found["pid"] > 0 and found["run_id"].startswith("run-")
    assert found["argv"] == ["route", "--json", "--source", "ui", "--chat", "brief23", "--", TEXT]
    _wait(world.runs)
    assert [json.loads(line) for line in out.read_text().splitlines()] == [found["argv"]]
    resp, body = _call(world.srv, "GET", "/api/runs")
    run = json.loads(body)["runs"][0]
    assert run["display"] == found["display"] and run["exit"] == 0 and run["envelope"]["sid"] == run["pid"]
    assert "request" not in run


@pytest.mark.parametrize("request_", [
    {"action": "send", "team": "route", "text": "x", "chat": "-x"},
    {"action": "send", "team": "collab", "text": "x"},
    {"action": "send", "team": "versus", "text": "x", "slots": {"c": "claude"}},
    {"action": "send", "team": "versus", "text": "x", "slots": {"a": "muse"}},
    {"action": "floor", "text": "x", "skill": "dancing", "answers": TID},
    {"action": "probe"},
    ["not", "an", "object"],
])
def test_a_refused_request_runs_nothing(world, request_):
    resp, body = _call(world.srv, "POST", "/api/run", request_)
    assert resp.status == 400 and json.loads(body)["error"]
    assert world.runs.list() == []


def test_api_command_shows_the_argv_and_runs_nothing(world):
    resp, body = _call(world.srv, "POST", "/api/command", {"action": "send", "team": "versus", "text": "write is_leap",
                                                           "slots": {"b": "cursor"}, "chat": "brief23"})
    found = json.loads(body)
    assert resp.status == 200 and found["copy"] == "sr relay versus --b cursor --chat brief23 -- 'write is_leap'"
    assert found["display"] == "sr relay versus --json --source ui --b cursor --chat brief23 -- 'write is_leap'"
    assert [p["text"] for p in found["parts"] if p["added"]] == ["--json", "--source", "ui"]
    assert world.runs.list() == []


def test_a_body_past_its_limit_is_413(world, monkeypatch):
    monkeypatch.setattr(page, "BODY_LIMIT", 10)
    assert _call(world.srv, "POST", "/api/command", {"action": "check", "padding": "x" * 50})[0].status == 413


# ---------- reads (decision 16) ----------

def test_the_log_filters_pass_on_as_flags(world):
    resp, _ = _call(world.srv, "GET", f"/api/log?chat=tray&search=-x%20y&before={TID}")
    assert resp.status == 200
    assert world.reads.calls[-1][3:] == ["log", "--json", "--limit", "50", "--chat=tray", "--search=-x y", f"--before={TID}"]
    for bad in ("chat=-x", "project=a%0Ab", "before=5", "search=a%07"):
        assert _call(world.srv, "GET", f"/api/log?{bad}")[0].status == 400, bad


def test_a_fresh_status_is_read_at_most_once_per_ten_seconds(world):
    _call(world.srv, "GET", "/api/status")
    _call(world.srv, "GET", "/api/status?fresh=1")
    assert world.reads.count("status") == 2
    _call(world.srv, "GET", "/api/status?fresh=1")  # a second "Check again" within 10 s reads the kept status
    assert world.reads.count("status") == 2
    world.clock.t += 11
    _call(world.srv, "GET", "/api/status?fresh=1")
    assert world.reads.count("status") == 3


def test_a_task_and_its_files(world):
    resp, body = _call(world.srv, "GET", f"/api/task/{TID}")
    assert resp.status == 200 and json.loads(body)["task_id"] == TID and world.reads.calls[-1][3:] == ["show", TID, "--json"]
    assert _call(world.srv, "GET", "/api/task/5")[0].status == 400
    resp, body = _call(world.srv, "GET", f"/api/files/{TID}")
    assert [f["path"] for f in json.loads(body)["files"]] == [f"tasks/{TID}/01-do-claude.md", f"media/in/{TID}/pic.png"]
    resp, body = _call(world.srv, "GET", f"/api/file?path=tasks/{TID}/01-do-claude.md")
    assert resp.status == 200 and body == b"the answer, **bold**" and resp.getheader("Content-Type").startswith("text/plain")
    resp, _ = _call(world.srv, "GET", f"/api/file?path=media/in/{TID}/pic.png&download=1")
    assert resp.getheader("Content-Type") == "image/png" and resp.getheader("Content-Disposition") == "attachment; filename*=UTF-8''pic.png"
    for path in (".env", "router.db", "backups/router-v14.db", "config/agents.json", f"tasks/{TID}/02-link.md",
                 f"tasks/{TID}/../{OTHER}/01-do-grok.md", "/etc/hosts"):
        assert _call(world.srv, "GET", f"/api/file?path={path}")[0].status == 404, path


def test_log_files_list_the_task_folders_newest_first(world):
    resp, body = _call(world.srv, "GET", "/api/logfiles")
    doc = json.loads(body)
    assert resp.status == 200 and [f["task_id"] for f in doc["folders"]] == [OTHER, TID] and doc["next_before"] is None
    assert all(x["path"].startswith(f"tasks/{f['task_id']}/") for f in doc["folders"] for x in f["files"])
    assert _call(world.srv, "GET", "/api/logfiles?before=../etc")[0].status == 400
    assert _call(world.srv, "GET", "/api/logfiles?limit=x")[0].status == 400


def test_the_report_the_handoff_and_setup(world):
    resp, body = _call(world.srv, "GET", "/api/report")
    assert resp.status == 200 and body == b"the report"
    resp, body = _call(world.srv, "GET", "/api/handoff/proj")
    assert resp.status == 200 and body == b"the handoff"
    assert _call(world.srv, "GET", "/api/handoff/nope")[0].status == 404
    assert _call(world.srv, "GET", "/api/setup")[0].status == 404
    (world.repo / "docs" / "SETUP.md").write_text("# Setup")
    assert _call(world.srv, "GET", "/api/setup")[1] == b"# Setup"


# ---------- the drop and Finder (decisions 8, 11) ----------

def test_a_drop_lands_in_the_drop_folder_and_never_overwrites(world):
    drop = world.tmp / "Router Drop"
    body = {"name": "shot.png", "data": base64.b64encode(b"one").decode()}
    first = json.loads(_call(world.srv, "POST", "/api/drop", body)[1])
    second = json.loads(_call(world.srv, "POST", "/api/drop", body)[1])
    assert (Path(first["path"]).parent, Path(first["name"]).name, second["name"]) == (drop, "shot.png", "shot (2).png")
    assert _call(world.srv, "POST", "/api/drop", {"name": "notes.txt", "data": "eA=="})[0].status == 400
    assert _call(world.srv, "POST", "/api/drop", {"name": "a.png", "data": "not base64!"})[0].status == 400
    assert sorted(p.name for p in drop.iterdir()) == ["shot (2).png", "shot.png"]


def test_open_in_finder_runs_open_r_on_an_allowed_path_on_macos_only(world):
    resp, _ = _call(world.srv, "POST", "/api/reveal", {"path": f"tasks/{TID}/01-do-claude.md"})
    assert resp.status == 200
    argv, kw = world.revealed[0]
    assert argv == ["open", "-R", str((world.repo / "tasks" / TID / "01-do-claude.md").resolve())]
    assert _call(world.srv, "POST", "/api/reveal", {"path": ".env"})[0].status == 400
    world.srv.platform = "linux"
    assert _call(world.srv, "POST", "/api/reveal", {"path": f"tasks/{TID}/01-do-claude.md"})[0].status == 400
    assert len(world.revealed) == 1


# ---------- the server never opens .env and changes nothing but the drop folder ----------

def _snapshot(root, skip):
    found = {}
    for path in sorted(root.rglob("*")):
        if skip in path.parents or path == skip:
            continue
        info = os.lstat(path)
        found[str(path)] = (info.st_mtime_ns, info.st_size, stat.S_IMODE(info.st_mode))
    return found


def test_every_endpoint_answers_with_env_unreadable_and_nothing_outside_the_drop_folder_changes(world):
    drop = world.tmp / "Router Drop"
    before = _snapshot(world.tmp, drop)
    codes = {}
    for path in GETS + ["/", "/static/app.js", "/static/app.css"]:
        codes[path] = _call(world.srv, "GET", path)[0].status
    for path, body in POSTS.items():
        codes[path] = _call(world.srv, "POST", path, body)[0].status
    _wait(world.runs)
    assert all(code in (200, 400, 404) for code in codes.values()), codes
    assert codes["/api/run"] == 200 and codes["/api/drop"] == 200 and codes["/api/status"] == 200
    assert _snapshot(world.tmp, drop) == before
    assert stat.S_IMODE(os.stat(world.repo / ".env").st_mode) == 0


# ---------- the demo (decision 15) ----------

def test_the_demo_runs_no_subprocess_and_refuses_every_post(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the demo runs nothing")
    monkeypatch.setattr(page.subprocess, "run", boom)
    monkeypatch.setattr(page.subprocess, "Popen", boom)
    monkeypatch.setattr(page_runs.subprocess, "Popen", boom)
    demo = tmp_path / "demo"
    (demo / "tasks").mkdir(parents=True)
    (demo / "status.json").write_text(json.dumps({"api_version": 1, "agents": [], "drop_folder": None}))
    (demo / "log.json").write_text(json.dumps({"api_version": 1, "tasks": [{"task_id": TID, "chat": "tray", "text": "a tray"}],
                                               "next_before": None}))
    (demo / "tasks" / f"{TID}.json").write_text(json.dumps({"api_version": 1, "task_id": TID}))
    (demo / "runs.json").write_text(json.dumps({"runs": [{"id": "run-1", "display": "sr route --json -- x"}]}))
    (demo / "report.md").write_text("a demo report")
    srv = page.make_server(0, demo=True, demo_root=demo)
    import threading
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        resp, body = _call(srv, "GET", "/", token=False)
        assert b'<meta name="sr-demo" content="1">' in body and b'<meta name="sr-reveal" content="0">' in body
        assert json.loads(_call(srv, "GET", "/api/status")[1])["agents"] == []
        assert json.loads(_call(srv, "GET", "/api/log?chat=tray")[1])["tasks"][0]["task_id"] == TID
        assert json.loads(_call(srv, "GET", "/api/log?chat=other")[1])["tasks"] == []
        assert json.loads(_call(srv, "GET", f"/api/task/{TID}")[1])["task_id"] == TID
        assert json.loads(_call(srv, "GET", "/api/runs")[1])["runs"][0]["id"] == "run-1"
        assert _call(srv, "GET", "/api/report")[1] == b"a demo report"
        for path, body in POSTS.items():
            resp, out = _call(srv, "POST", path, body)
            assert resp.status == 409 and json.loads(out)["message"] == "Demo: nothing runs.", path
        assert _call(srv, "POST", "/api/run", {"action": "check"}, token=False)[0].status == 403  # the token still first
        assert srv.runs is None
    finally:
        srv.shutdown()
        srv.server_close()
