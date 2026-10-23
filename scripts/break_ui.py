"""Build brief 23, G (`/break-ui`): the page's worst cases as demo roots shaped exactly like demo/ (the documents the
router's own serializers made, edited at the data boundary, never the page), and a dev-only server for each, with a
switcher page. Never part of the page, the router or `sr`; the regression fixture for the next change to the page.

    python scripts/break_ui.py OUT_DIR            # OUT_DIR/<scenario>/ for each scenario
    python scripts/break_ui.py OUT_DIR --serve    # and serve them: the switcher on http://127.0.0.1:8800

Scenarios: demo, worst (a 4,000-character task with no spaces, a one-character task, a 200-character file name, a
2 MB result, every waiting state at once, a 64-character chat name, 64 tasks for History), empty, one (every count
at 1), two-agents, null-lights, status-failing, and newproject (brief 26): not a demo, so the New project sheet's Create
works, against a fake reader and a fake `sr` (nothing real runs or is written but `made.json` in the scenario folder).
Its dry run answers by the name typed: `slow…` never answers, `link…` and `root…` are the router's refusals, a name
already a project is taken, `recipe…` is a folder that is there (HANDOFF.md 14 lines), anything else a new folder under a
long iCloud projects root. Create: notes holding `token:` are refused (exit 2), a name starting `partial` stops part
way (exit 1), anything else is made and shows in the sidebar. And memoryswitch (brief 27): not a demo, so the Setup sheet's
Memory switch runs, against a fake reader whose memory state is `memory.json` in the scenario folder and a fake `sr` that
answers `sr memory on|off --json` (on takes 4 s, off 1 s) and writes it. A file in the scenario folder changes it: `refuse`
(the run is refused, exit 2), `hang` (the run never ends), `slow-status` (each status read takes 3 s); `runs.jsonl`
lists every run the fake `sr` got."""
import copy
import http.server
import json
import shutil
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from router import page  # noqa: E402

DEMO = ROOT / "demo"
LONG_CHAT = "northwind-industries-holdings-quarterly-board-review-follow-ups"  # 64; chat names have no length limit
LONG_PROJECT = "northwind-industries-holdings-website-redesign-2026"
_STATE = "eyJ2aWV3IjoiYm9hcmQiLCJmaWx0ZXJzIjpbeyJrZXkiOiJyZWdpb24iLCJ2YWx1ZSI6Im5vcnRoIn1dLCJzb3J0IjoiZGVzYyJ9"
LONG_TASK = ("https://analytics.example.com/dashboard/share?utm_source=newsletter&utm_medium=email&state=" + _STATE * 60)[:4000]
SHORT_TASK = "?"
LONG_FILE = ("Q3-2026-board-review-deck-final-v12-APPROVED-by-legal-and-finance-for-the-northwind-industries-holdings-"
             "quarterly-meeting-with-comments-from-aleksandra-wisniewska-kowalczyk-and-jo-before-the-vote.pdf")[:200]
_LINE = "region,store,week,units,revenue,returns,notes\nnorth,Maple Street,2026-W42,1284,18311.40,12,\"restock trays\"\n"
BIG_RESULT = "Here is the full export you asked for.\n\n```csv\n" + _LINE * (2_000_000 // len(_LINE)) + "```\n"
SCENARIOS = ("demo", "worst", "empty", "one", "two-agents", "null-lights", "status-failing", "newproject", "memoryswitch")
LONG_ROOT = "~/Library/Mobile Documents/com~apple~CloudDocs/Northwind Industries Holdings/Client Projects 2026"


def _read(name):
    return json.loads((DEMO / name).read_text(encoding="utf-8"))


def _write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")


class Ids:
    """Task ids of the router's shape after the demo's newest, in order."""

    def __init__(self):
        self.k = 0

    def next(self):
        self.k += 1
        return f"sr-20261020-{(self.k * 37) % 240000:06d}-{0xb000 + self.k:04x}", f"2026-10-20T{8 + self.k // 60:02d}:{self.k % 60:02d}:00+00:00"


def _clone(rows, shows, base, ids, n, out, **changes):
    """A copy of demo task `base` as a new task: a new id, number and time, `changes` on the row and its show, its
    round files and media copied under the new id, the calls' round files pointing at them."""
    row, show = copy.deepcopy(base), copy.deepcopy(shows[base["task_id"]])
    task_id, at = ids.next()
    old = base["task_id"]
    fields = {"task_id": task_id, "n": n, "created_at": at, "updated_at": at, **changes}
    row.update(fields)
    show.update(fields)
    for call in show.get("calls") or []:
        if call.get("round_file"):
            call["round_file"] = call["round_file"].replace(old, task_id)
        call["call_id"] = call["call_id"].replace(old, task_id)
    for part in ("tasks", "media/in", "media/pages", "media/frames", "media/out"):
        source = DEMO / "files" / part / old
        if source.is_dir():
            shutil.copytree(source, out / "files" / part / task_id)
    rows.append(row)
    shows[task_id] = show
    return row, show


def _base(rows, pred):
    return next(t for t in rows if pred(t))


def _status_for(rows, status):
    chats = {}
    for t in rows:
        if t.get("chat"):
            c = chats.setdefault(t["chat"], {"name": t["chat"], "tasks": 0, "newest": t["created_at"]})
            c["tasks"] += 1
            c["newest"] = max(c["newest"], t["created_at"])
    status["chats"] = sorted(chats.values(), key=lambda c: c["newest"], reverse=True)
    status["open_tasks"] = [t for t in rows if t.get("waiting_on") or t.get("status") in ("queued", "sent")]
    return status


def build(out):
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    log, status = _read("log.json"), _read("status.json")
    shows = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (DEMO / "tasks").glob("*.json")}
    for name in SCENARIOS:
        root = out / name
        shutil.copytree(DEMO, root)
    _worst(out / "worst", log, status, shows)
    _empty(out / "empty", log, status)
    _one(out / "one", log, status, shows)
    _two_agents(out / "two-agents", status)
    _null_lights(out / "null-lights", status)
    (out / "status-failing" / "status.json").unlink()
    status = copy.deepcopy(status)
    status["projects"] = status["projects"] + [{"name": LONG_PROJECT, "path": f"{LONG_ROOT}/{LONG_PROJECT}",
                                                "handoff_lines": 212, "open_task": None}]
    status["projects_root"] = LONG_ROOT
    _write(out / "newproject" / "status.json", status)
    _write(out / "memoryswitch" / "memory.json", {"setting": "auto", "online": True, "starting": False, "documents": 16,
                                                  "installed": True})
    return out


def _save(root, log, status, rows, shows):
    shutil.rmtree(root / "tasks")
    for task_id, show in shows.items():
        if any(r["task_id"] == task_id for r in rows):
            _write(root / "tasks" / f"{task_id}.json", show)
    rows = sorted(rows, key=lambda t: t["n"], reverse=True)
    _write(root / "log.json", {**log, "tasks": rows, "next_before": None})
    _write(root / "status.json", _status_for(rows, status))


def _worst(root, log, status, shows):
    rows, shows, status, ids = copy.deepcopy(log["tasks"]), copy.deepcopy(shows), copy.deepcopy(status), Ids()
    # 64 tasks for History: older copies of the demo's finished ones, numbered after it
    finished = [t for t in rows if t.get("outcome") in ("passed", "fixed", "unchecked")]
    n = max(t["n"] for t in rows)
    while len(rows) < 52:
        n += 1
        base = finished[n % len(finished)]
        _clone(rows, shows, base, ids, n, root, text=f"{base['text']} (again, #{n})")
    chat = {"chat": LONG_CHAT, "tag": f"chat:{LONG_CHAT}", "project": None}
    plan = [  # the long chat, oldest first: every failure on its first screen
        (lambda t: t.get("waiting_on") == "needs_label", {}),
        (lambda t: t.get("waiting_on") == "split_plan", {}),
        (lambda t: t.get("mode") == "split" and t.get("waiting_on") == "piece", {}),
        (lambda t: t.get("waiting_on") == "pick", {}),
        (lambda t: t.get("waiting_on") == "vote_pick", {}),
        (lambda t: t.get("check_note", "") and t["check_note"].startswith("overdue: grok"), {}),
        (lambda t: t.get("skill") == "writing" and t.get("outcome") == "passed" and t.get("mode") == "route",
         {"waiting_on": "probe", "outcome": None, "status": "queued", "result": None, "check_state": "pending"}),
        (lambda t: t.get("skill") == "writing" and t.get("outcome") == "passed" and t.get("mode") == "route",
         {"waiting_on": "memory", "outcome": None, "status": "queued", "result": None, "check_state": "pending"}),
        (lambda t: t.get("skill") == "quick_answer" and t.get("mode") == "route",
         {"text": SHORT_TASK, "result": "Could you say a little more about what you need?"}),
        (lambda t: t.get("skill") == "writing" and t.get("outcome") == "passed" and t.get("mode") == "route",
         {"text": LONG_TASK, "result": "That link opens a shared dashboard view (north region, sorted newest first); "
                                       "open it in a browser to see the board."}),
        (lambda t: t.get("skill") == "read_media" and (t.get("files") or [{}])[0].get("name", "").endswith(".pdf"),
         {"files": [{"name": LONG_FILE, "type": "application/pdf", "size": 1_948_221, "frames": None, "original": None,
                     "moved_to": None, "pages": 3, "total_pages": 3}]}),
        (lambda t: t.get("skill") == "writing" and t.get("outcome") == "passed" and t.get("mode") == "route",
         {"text": "Export every store's weekly sales for the year as CSV.", "skill": "bulk_text", "result": BIG_RESULT}),
    ]
    for pred, changes in plan:
        n += 1
        row, show = _clone(rows, shows, _base(log["tasks"], pred), ids, n, root, **chat, **changes)
        if changes.get("files"):
            folder = root / "files" / "media" / "in" / row["task_id"]
            for old in list(folder.iterdir()) if folder.exists() else []:
                old.rename(folder / LONG_FILE)
    status["projects"] = status.get("projects", []) + [{"name": LONG_PROJECT, "open_task": None}]
    _write(root / "projects.json", {**_read("projects.json"), "projects": _read("projects.json")["projects"] + [
        {"name": LONG_PROJECT, "path": f"~/Projects/{LONG_PROJECT}", "handoff": True}]})
    _save(root, log, status, rows, shows)


def _empty(root, log, status):
    status = copy.deepcopy(status)
    status.update(chats=[], projects=[], open_tasks=[], running=[])
    shutil.rmtree(root / "files")
    _write(root / "runs.json", {"runs": []})
    _write(root / "projects.json", {**_read("projects.json"), "projects": []})
    _save(root, log, status, [], {})


def _one(root, log, status, shows):
    rows, shows, ids = [], copy.deepcopy(shows), Ids()
    base = _base(log["tasks"], lambda t: t.get("waiting_on") == "needs_label")
    _clone(rows, shows, base, ids, 1, root, chat="tray", tag="chat:tray")
    status = copy.deepcopy(status)
    status["projects"] = status["projects"][:1]
    _save(root, log, status, rows, shows)


def _two_agents(root, status):
    status = copy.deepcopy(status)
    status["agents"] = [dict(a, online=True, reason=None) for a in status["agents"] if a["name"] in ("claude", "chatgpt")]
    _write(root / "status.json", status)


def _null_lights(root, status):
    status = copy.deepcopy(status)
    status["agents"] = [dict(a, online=None, reason=None, checked_at=None, probe=None) for a in status["agents"]]
    status["memory"], status["jev"] = None, None
    _write(root / "status.json", status)


class PagingReader(page.DemoReader):
    """The demo reader with `sr log`'s paging: 50 a page, older ones after `--before`."""

    def log(self, flags=()):
        code, body = self._file("log.json")
        if code != 200:
            return code, body
        doc = json.loads(body)
        tasks = doc["tasks"]
        wanted = dict(f.split("=", 1) for f in flags if "=" in f)
        if wanted.get("--chat"):
            tasks = [t for t in tasks if t.get("chat") == wanted["--chat"]]
        if wanted.get("--project"):
            tasks = [t for t in tasks if t.get("project") == wanted["--project"]]
        if wanted.get("--search"):
            tasks = [t for t in tasks if wanted["--search"].lower() in (t.get("text") or "").lower()]
        if wanted.get("--before"):
            ids = [t["task_id"] for t in tasks]
            tasks = tasks[ids.index(wanted["--before"]) + 1:] if wanted["--before"] in ids else []
        shown = tasks[:50]
        return 200, json.dumps({**doc, "tasks": shown, "next_before": shown[-1]["task_id"] if len(tasks) > 50 else None}).encode()


# Brief 26: the fake `sr` the newproject scenario runs (as `python -c`, from the scenario folder). It answers
# `project new` as the router's envelope does and records a made project in made.json; anything else is a plain answer.
FAKE_SR = r"""
import json, sys, time
args = sys.argv[1:]
time.sleep(0.8)
env = {"task_id": None, "n": None, "status": None, "waiting_on": None, "outcome": None, "reason_code": None, "exit": 0,
       "message": "fake sr: " + " ".join(args[:2])}
if args[:2] == ["project", "new"]:
    name = args[3]
    notes = args[args.index("--") + 1] if "--" in args else ""
    if "token:" in notes:
        line = next(i for i, l in enumerate(notes.splitlines(), 1) if "token:" in l)
        env.update(reason_code="project_refused", exit=2,
                   message=f"Refused: line {line} of the notes looks like it holds a key. Nothing was changed.")
    elif name.startswith("partial"):
        env.update(reason_code="project_partial", exit=1, message=(
            f"Stopped: HANDOFF.md could not be written. What exists now: the projects root ROOT (made now), the folder "
            f"ROOT/{name}, HANDOFF.md is not there, {name} is not registered. Nothing was deleted."))
    else:
        lines = (len(notes.splitlines()) + 1 if notes else 0) + 2
        try:
            made = json.load(open("made.json"))
        except OSError:
            made = []
        made.append({"name": name, "path": "ROOT/" + name, "handoff_lines": lines, "open_task": None})
        open("made.json", "w").write(json.dumps(made).replace("ROOT", ROOT_PATH))
        env["message"] = f"Created {name} at ROOT/{name}. HANDOFF.md made ({lines} lines)."
        env["project"] = {"name": name, "folder": "ROOT/" + name, "handoff_lines": lines, "did": "created"}
print(json.dumps(env).replace("ROOT", ROOT_PATH), file=sys.stdout if env["exit"] == 0 else sys.stderr)
sys.exit(env["exit"])
""".replace("ROOT_PATH", repr(LONG_ROOT))


# Brief 27: the memoryswitch scenario's fake `sr`, run as `python -c` from the scenario folder.
FAKE_MEMORY_SR = r"""
import json, os, sys, time
args = sys.argv[1:]
open("runs.jsonl", "a").write(json.dumps(args) + "\n")
env = {"task_id": None, "n": None, "status": None, "waiting_on": None, "outcome": None, "reason_code": None, "exit": 0,
       "message": "fake sr: " + " ".join(args[:2])}
if args[:1] == ["memory"] and args[1:2] in (["on"], ["off"]):
    if os.path.exists("hang"):
        time.sleep(3600)
    if os.path.exists("refuse"):
        env.update(reason_code="setup", exit=2,
                   message="Refused: config/settings.local.json is not a JSON object. Nothing was changed.")
    else:
        to = args[1]
        time.sleep(4 if to == "on" else 1)
        was = json.load(open("memory.json")).get("setting", "auto")
        state = ({"setting": "auto", "online": True, "starting": False, "documents": 16, "installed": True} if to == "on"
                 else {"setting": "off", "online": False, "starting": False, "documents": None, "installed": True})
        json.dump(state, open("memory.json", "w"))
        env["message"] = f"memory: {to} (it was {'on' if was == 'auto' else 'off'})"
        env["memory"] = {"setting": state["setting"], "was": was, "online": state["online"], "installed": True}
print(json.dumps(env), file=sys.stdout if env["exit"] == 0 else sys.stderr)
sys.exit(env["exit"])
"""


class MemorySwitchReader(PagingReader):
    """Brief 27: the memoryswitch scenario's reads: the demo's status with memory from memory.json; never kept."""

    def status(self, fresh=False):
        import time
        if (self.root / "slow-status").exists():
            time.sleep(3)
        code, body = self._file("status.json")
        if code != 200:
            return code, body
        doc = json.loads(body)
        doc["memory"] = json.loads((self.root / "memory.json").read_text(encoding="utf-8"))
        return 200, json.dumps(doc).encode()

    def forget_status(self):
        pass


class NewProjectReader(PagingReader):
    """Brief 26: the newproject scenario's reads. Status and the project list add what the fake `sr` made; the dry run
    answers by the name (see the module's docstring). Never kept, so a made project shows on the next read."""

    def _made(self):
        try:
            return json.loads((self.root / "made.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def status(self, fresh=False):
        code, body = self._file("status.json")
        if code != 200:
            return code, body
        doc = json.loads(body)
        doc["projects"] = doc["projects"] + self._made()
        return 200, json.dumps(doc).encode()

    def projects(self):
        doc = json.loads(self._file("projects.json")[1])
        return 200, json.dumps({**doc, "projects": doc["projects"] + self._made()}).encode()

    def forget_status(self):
        pass

    def project_check(self, name):
        import time
        status = self.status_doc() or {}
        root = status.get("projects_root")
        taken = next((p for p in status.get("projects") or [] if p.get("name") == name), None)
        found = {"api_version": 1, "would": "create", "name": name, "folder": f"{root}/{name}",
                 "handoff": {"exists": False, "lines": None, "has_block": False}, "reason_code": None}
        if name.startswith("slow"):
            time.sleep(3600)  # a dry run that never answers
        if taken:
            why = f"{name} is already registered at {taken.get('path')}; remove it first"
        elif name.startswith("link"):
            why = f"{name} in the projects root is a link; a folder kept elsewhere is registered with sr project add {name} <path>"
        elif name.startswith("root"):
            why = "projects_root in settings isn't an absolute or ~ path: nothing is made until it is fixed"
        else:
            why = None
        if why:
            found.update(would="refused", folder=taken.get("path") if taken else None, handoff=None, reason_code="project_refused",
                         message=f"Would refuse: {why}. Nothing was changed.")
        elif name.startswith("recipe"):
            found.update(would="register", handoff={"exists": True, "lines": 14, "has_block": False},
                         message=f"Would register {root}/{name} as it is. Nothing was changed.")
        else:
            found["message"] = f"Would create {root}/{name} and its HANDOFF.md, and register {name}. Nothing was changed."
        return 200, json.dumps(found).encode()


SWITCHER = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Break the page</title><style>body{font:14px system-ui;margin:24px;background:#f4f4f5;color:#111}
nav{position:fixed;left:50%;bottom:16px;transform:translateX(-50%);display:flex;gap:2px;padding:3px;border-radius:9px;
background:#d4d4d8}a{padding:6px 12px;border-radius:7px;color:#111;text-decoration:none}a:hover{background:#fff}</style>
</head><body><p>Dev only: each link opens the page on one dataset (`scripts/break_ui.py`).</p><nav>LINKS</nav></body></html>"""


def serve(out, base=8800):
    servers = []
    links = []
    for i, name in enumerate(SCENARIOS, 1):
        root = Path(out) / name
        if name == "memoryswitch":  # brief 27: not a demo, so the switch runs; the fake sr runs, nothing real does
            from router import page_runs
            runs = page_runs.Runs(root=root, prefix=[sys.executable, "-c", FAKE_MEMORY_SR])
            srv = page.make_server(base + i, reader=MemorySwitchReader(root), runs=runs, root=root, demo_root=root,
                                   platform="linux")
        elif name == "newproject":  # brief 26: not a demo, so Create works; the fake sr runs, nothing real does
            from router import page_runs
            runs = page_runs.Runs(root=root, prefix=[sys.executable, "-c", FAKE_SR])
            srv = page.make_server(base + i, reader=NewProjectReader(root), runs=runs, root=root, demo_root=root,
                                   platform="linux")  # linux: no Open in Finder from a dev page
        else:
            srv = page.make_server(base + i, reader=PagingReader(root), demo=True, demo_root=root)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        links.append(f'<a href="http://127.0.0.1:{base + i}/">{name}</a>')
    html = SWITCHER.replace("LINKS", "".join(links)).encode()

    class Switcher(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, *args):
            pass

    print(f"switcher: http://127.0.0.1:{base}/  " + "  ".join(f"{n}: {base + i}" for i, n in enumerate(SCENARIOS, 1)))
    http.server.ThreadingHTTPServer(("127.0.0.1", base), Switcher).serve_forever()


if __name__ == "__main__":
    target = build(sys.argv[1])
    print(f"scenarios written to {target}")
    if "--serve" in sys.argv[2:]:
        serve(target)
