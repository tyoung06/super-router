"""Build brief 23, G (`/break-ui`): the page's worst cases as demo roots shaped exactly like demo/ (the documents the
router's own serializers made, edited at the data boundary, never the page), and a dev-only server for each, with a
switcher page. Never part of the page, the router or `sr`; the regression fixture for the next change to the page.
Brief 33: next33, the chips (three 400-character ones on a forgotten card of a 64-character chat, an older card's
Suggested next), What now? at its longest on the 51-character project with every bar control, and its Ideas sheet at
50 ideas. Brief 33.1: plan331, the plan card at its longest (12 steps of 399 characters, each why and finish line at its
limit, every need, a long count), "Plan #12345 · 11 of 12" on the 51-character project's bar beside every control, What
now?'s finish line with its three chips, and a One step card with a 399-character task.

    python scripts/break_ui.py OUT_DIR            # OUT_DIR/<scenario>/ for each scenario
    python scripts/break_ui.py OUT_DIR --serve    # and serve them: the switcher on http://127.0.0.1:8800 (--base N moves it)

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
lists every run the fake `sr` got. And projectfiles (brief 28): not a demo, so Land, Undo, Discard, the tests sheet, Turn
on undo and the drop sheet run, against a fake `sr` that moves a task's state in `files.json` (the reader lays it over
every row) and the same `refuse`, `hang` and `slow-status` files; the waiting change holds 500 files (the limit) with deep
paths and binaries, seed-library's test command is 287 characters, and the scenario's own drop folder is `drop/`. And
split (brief 29): not a demo, so the plan card's Edit and team select, Approve, Reject, Skip and Route it run, against a fake
`sr` (`plan.json`, `go.json`, `skip.json` and `routed.json` in the scenario folder, laid over the documents by the reader)
and the same `refuse`, `hang` and `slow-status` files; the plan has four pieces (a 399-character text, the longest a piece
may be; a two-word one; a refused team; a tie), the split waiting on its pieces has every piece state and a 37-file part,
the No split answer and its task are long, and the plan sits on a 51-character project. A new text starting with @ or /
is refused as the router refuses it."""
import copy
from datetime import datetime, timedelta
import http.server
import json
import shutil
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from router import page, projrun  # noqa: E402

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
SCENARIOS = ("demo", "worst", "empty", "one", "two-agents", "null-lights", "status-failing", "newproject", "memoryswitch",
             "projectfiles", "split", "checker291", "notes30", "projects31", "redteam32", "pinned321", "next33",
             "plan331", "models333", "auto34", "spec332", "q334", "uia", "pills", "bar-wrong")
# Brief 29.1: the checker's worst cases. A check item is one line of a model's reply with no limit, so as long as a
# checker writes one (a full source URL with no break in it, a quoted error, Polish names); a blocked line likewise; a
# versus candidate's change at the copy's limit (500 files, deep paths, binaries) beside one that changed nothing; a test
# command at its 300-character limit.
SOURCE_URL = ("https://www.globenewswire.com/news-release/2026/10/15/3381284/0/en/Rapsodo-Launches-MLM2XPRO-the-Most-"
              "Advanced-Mobile-Launch-Monitor-Yet-with-Shot-Tracer-and-Course-Mapping-for-Members.html?utm_source=newsletter")
LONG_NOTES = [
    {"n": 2, "text": f"The launch date is supported by Rapsodo's own release ({SOURCE_URL}); the result could link it next "
                     "to the date rather than at the end, so a reader checking the date finds the source in one place."},
    {"n": 3, "text": "Fine."},
    {"n": 4, "text": "The sign-off names Aleksandra Wiśniewska-Kowalczyk and Bartholomew Fitzgerald; the committee's "
                     "minutes spell the second as Fitzgerald-Ó Súilleabháin since September."},
    {"n": 5, "text": "Hedged: \"most members garden on Saturdays\" is a fair reading of the sign-up sheet, not a count."},
    {"n": 6, "text": "Could be shorter."},
    {"n": 7, "text": "The second line runs to 61 characters; the sign's template fits 48 at the size the committee prints."},
    {"n": 8, "text": "bartholomew.fitzgerald@northwind-industries-holdings.example.com is quoted as the contact; the "
                     "newsletter usually gives the shared inbox instead."},
    {"n": 9, "text": "A comma after \"browns\" would read better."},
    {"n": 10, "text": "Tone: warm and plain, as asked."},
    {"n": 11, "text": "I couldn't open the committee's shared drive link, so the bin colours are unchecked."},
    {"n": 12, "text": "The word count is 19, well under the limit."}]
LONG_MUSTS = [
    {"n": 1, "text": "The tests fail: overdue loans come last, not first. (not fixed: test_overdue_first still expects "
                     "kale first, and the sort key compares due dates as strings, so 2026-10-9 sorts after 2026-10-10)"},
    {"n": 2, "text": "lend() accepts a packet with no stock left and returns None instead of refusing it."},
    {"n": 4, "text": "The handoff's Produced names test_members.py, which the change doesn't touch. (not fixed)"},
    {"n": 5, "text": f"The README's link to the lending rules points at {SOURCE_URL}, a press release, not the rules. (not "
                     "fixed: it still does)"},
    {"n": 6, "text": "A member named Ó Súilleabháin is sorted under S, so the overdue list skips them. (not fixed: the "
                     "sort strips accents first)"},
    {"n": 7, "text": "The overdue count says 1 loans."},
    {"n": 8, "text": "Returns are counted twice when a packet comes back on its due date."},
    {"n": 9, "text": "The change removes the guard for an empty loan list, so the page crashes with no loans."},
    {"n": 11, "text": "The change edits migrations/0007_due_dates.py, which the task didn't ask for and which has run."}]
BLOCKED_WHAT = ("the owner's notes from Tuesday's committee meeting (the decisions on the tool shed rota, the seed library's "
                "Saturday hours and the work party dates), which the task names as the email's source but doesn't include, "
                f"and the committee's shared drive link it cites, {SOURCE_URL}")
DEEP_CAND = ("src/components/northwind-industries-holdings/seed-library/lending/"
             "OutOfStockPacketRefusal.integration.test.tsx")
# Brief 28: project files' worst cases. A change at the limit (500 files), paths as deep as real repositories make them,
# binaries, a 300-character test command (the limit), and the longest reason file mode is off.
DEEP = ("src/components/northwind-industries-holdings/quarterly-board-review/"
        "AleksandraWisniewskaKowalczykApprovalFlow.integration.test.tsx")
LONG_TESTS = ["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--maxfail=1", "-k",
              "lending and not slow and not network and not windows_only and not flaky_on_ci",
              "tests/unit/loans/", "tests/unit/packets/", "tests/integration/members/", "--durations=20",
              "--junitxml=reports/junit-northwind-industries-holdings-seed-library.xml"]
LONG_WHY = ("Claude's file check failed on Claude Code 2.1.311 (nothing written outside the folder: 3 change(s) "
            "outside); file mode is off on this version")
LONG_ROOT = "~/Library/Mobile Documents/com~apple~CloudDocs/Northwind Industries Holdings/Client Projects 2026"

# Brief 29: split's worst cases. A piece is under 400 characters (split.MAX_PIECE_CHARS), so 399 is the longest; a why,
# a join, a No split line and a refusal have no limit but one line, so they are as long as a planner or the router writes
# them; a piece's part of the change is one chip per file.
LONG_PIECE = ("Rewrite the volunteer onboarding email for the Northwind community garden so it explains the new tool shed "
              "rota, the seed library's lending rules and the Saturday work parties, keeps the sign-up link exactly as it is "
              "(https://example.org/garden/volunteers/onboarding?utm_source=newsletter&utm_medium=email&utm_campaign=autumn-"
              "2026-volunteer-drive) and stays under 200 words, warm but plain, no emoji")
SHORT_PIECE = "Proofread it."
LONG_TEAM_WHY = ("Three people on the board disagree about this, so three answers made on their own and counted by the "
                 "router settle it better than one agent's opinion, and a tie comes back to you to pick.")
LONG_REFUSAL = ("research-build can't run now: slot research (Grok Bot): Grok Bot isn't set up: no GROK_WEBHOOK_URL or "
                "GROK_WEBHOOK_KEY in .env; no inbox repo in settings; no other agent can research there")
LONG_JOIN = ("Put the onboarding email first, exactly as written, then the proofread note under it, then the price range for "
             "the rain barrels with every source as a link, then the board's decision with its one-line reason; keep each "
             "piece's own headings and don't rewrite what the pieces said.")
LONG_SPLIT_TASK = ("Four things for the Northwind community garden's autumn newsletter, each on its own: the volunteer "
                   "onboarding email rewritten with the sign-up link kept exactly, a proofread of the crop rotation note, "
                   "this year's prices for a 50-gallon rain barrel from three garden centres with sources, and the board's "
                   "decision on whether the seed library keeps paper or spreadsheet records, with one line why.")
LONG_NO_SPLIT = ("Each part needs the one before it: the migration script reads the schema the first part writes, the "
                 "backfill runs against what the migration made, and the rollback note names the exact columns the "
                 "backfill touched, so no part can run alone and a split would only lose the thread between them.")
LONG_NO_SPLIT_TASK = ("Add a loans_due_at column to the seed library's members table with a migration, backfill it from "
                      "each open loan's lent_on date plus four weeks, then write the rollback note naming every column "
                      "the backfill touched; the project is the one at "
                      "~/Projects/northwind-industries-holdings-website-redesign-2026.")
PART = [{"path": f"src/components/northwind-industries-holdings/volunteer-onboarding/{name}", "status": status,
         "plus": plus, "minus": minus}
        for name, status, plus, minus in (
            ("OnboardingEmailTemplate.integration.test.tsx", "changed", 1284, 977),
            ("assets/garden-volunteers-header-final-v12-APPROVED.png", "added", None, None),
            ("a", "deleted", 0, 1))]
PART += [{"path": f"content/newsletter/autumn-2026/sections/section_{k:02d}.md", "status": "added", "plus": 12, "minus": 0}
         for k in range(34)]


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
    _projectfiles(out / "projectfiles", log, status, shows)
    _split(out / "split", log, status, shows)
    _checker291(out / "checker291", log, status, shows)
    _notes30(out / "notes30", log, status, shows)
    _projects31(out / "projects31", log, status, shows)
    _redteam32(out / "redteam32", log, status, shows)
    _pinned321(out / "pinned321", log, status, shows)
    _next33(out / "next33", log, status, shows)
    _plan331(out / "plan331", log, status, shows)
    _models333(out / "models333", log, status, shows)
    _auto34(out / "auto34", log, status, shows)
    _spec332(out / "spec332", log, status, shows)
    _q334(out / "q334", log, status, shows)
    _uia(out / "uia", log, status, shows)
    _pills(out / "pills", log, status, shows)
    _bar_wrong(out / "bar-wrong", status)
    return out


def _checker291(root, log, status, shows):
    """Brief 29.1: the checker's page parts at their worst, read only (a demo): a pass with eleven notes, one with
    exactly one; a failed file-mode check with nine open musts and Land anyway on a 500-file change; a Blocked card with
    a long line on a long task; a follow-up by the stand-in; a plan with three slot selects and a follow-up piece; a versus
    task on a project with one candidate's 500 files and failing tests beside one that changed nothing."""
    rows, shows, status = copy.deepcopy(log["tasks"]), copy.deepcopy(shows), copy.deepcopy(status)

    def both(row, **fields):
        row.update(fields)
        if row["task_id"] in shows:
            shows[row["task_id"]].update(fields)

    notes = next(t for t in rows if t["text"].startswith("Write a two-line sign for the compost bins."))
    both(notes, notes=[{"n": 1, "text": "The second line could name the bins' colours."}] + LONG_NOTES)
    one = next(t for t in rows if t.get("outcome") == "passed" and t is not notes and not t.get("notes"))
    both(one, notes=[{"n": 1, "text": "Could be shorter."}])  # exactly one: "1 note"
    failed = next(t for t in rows if t["text"].startswith("Show overdue loans first"))
    record = dict(failed["project_files"], changed=[{"path": DEEP_CAND, "status": "changed", "plus": 1284, "minus": 977}]
                  + [{"path": f"src/loans/rules/rule_{k:03d}.py", "status": "added", "plus": 12, "minus": 0}
                     for k in range(499)])
    both(failed, open_musts=LONG_MUSTS, land_anyway=True, project_files=record)
    blocked = next(t for t in rows if t.get("outcome") == "blocked")
    both(blocked, check_note=f"blocked: {BLOCKED_WHAT}", text=LONG_PIECE)
    follow = next(t for t in rows if t.get("skill") == "follow_up")
    both(follow, agent="chatgpt", checker="claude", route_reason="stand-in for claude: Claude is signed out")
    plan = next(t for t in rows if t.get("waiting_on") == "split_plan" and t["text"].startswith("Three separate"))
    pieces = shows[plan["task_id"]]["pieces"]
    pieces[0].update(route={"skill": "follow_up", "agent": "chatgpt", "checker": "claude", "check_state": "pending",
                            "comes_back": None}, jev={"status": "below_floor", "label": "writing", "confidence": 0.31})
    pieces[2].update(team="vote", planner_team="research-build", team_source="owner",
                     slots={"a": "cursor", "c": "claude"}, slot_map={"a": "cursor", "b": "chatgpt", "c": "claude"},
                     chain="Cursor answers → ChatGPT answers → Claude answers → the count (a tie: your pick)")
    versus = next(t for t in rows if t.get("preset") == "versus" and (t.get("project_files") or {}).get("versus"))
    cands = copy.deepcopy(versus["project_files"]["candidates"])
    cands["a"].update(changed=[{"path": DEEP_CAND, "status": "changed", "plus": 1284, "minus": 977},
                               {"path": "assets/packet-out-of-stock-badge-final-v12-APPROVED.png", "status": "added",
                                "plus": None, "minus": None}, {"path": "a", "status": "deleted", "plus": 0, "minus": 1}]
                      + [{"path": f"src/loans/rules/rule_{k:03d}.py", "status": "added", "plus": 12, "minus": 0}
                         for k in range(497)],
                      tests={"outcome": "failed", "exit": 1, "summary": "FAILED (failures=3, errors=1)", "output": None,
                             "command": LONG_TESTS})
    cands["b"].update(changed=[], tests=None)
    both(versus, project_files=dict(versus["project_files"], candidates=cands))
    _save(root, log, status, rows, shows)


# Brief 30: the router notes and project notes at their worst. The router notes past their 6,000 cap (invalid: the router
# names the line) with a pasted URL that has no break in it, Polish names, `###` lines and every section filled; a project
# with the 51-character name at the 20,000 cap, 312 short lines, its block of eight entries with deep
# Produced paths; twelve projects for the sheets' select; a card offering Pin, Save and Forget on a 2 MB result; a forgotten
# card; a Details with twenty calls' notes (every section, the judge and planner parts, a Grok call left out).
NOTES_URL = ("https://analytics.example.com/dashboard/share?utm_source=newsletter&utm_medium=email&state=" + _STATE * 3)
NOTE_LINES = {
    "All agents": ["Use metric units for every distance, weight and bed size; give imperial in brackets only when asked.",
                   f"Our shared dashboard (read only, never paste it into a reply): {NOTES_URL}",
                   "### Names", "Spell the committee's names exactly: Aleksandra Wiśniewska-Kowalczyk, Bartholomew Fitzgerald, Jo."],
    "Claude": ["Keep answers under 80 words unless the task asks for more."] * 3,
    "ChatGPT": ["When you check, keep each item to one sentence and name its source with its full link."] * 3,
    "Grok": ["Say which X accounts you read, with each handle, its follower count and the post's date and link."] * 3,
    "Cursor": ["Use only Python's standard library; no third-party packages, no network, no files."] * 3,
    "Planner": ["For a yes-or-no question, use vote; for anything that needs sources, research-build first."] * 3,
}


def _notes_text():
    text = "".join(f"## {title}\n" + "\n".join(lines) + "\n\n" for title, lines in NOTE_LINES.items())
    pad = "\n".join(f"- {NOTE_LINES['All agents'][0]} ({k})" for k in range(60))
    return text.replace("## Claude\n", f"{pad}\n\n## Claude\n", 1)[:6412]


def _notes30(root, log, status, shows):
    rows, shows, status = copy.deepcopy(log["tasks"]), copy.deepcopy(shows), copy.deepcopy(status)
    text = _notes_text()
    sections = {"all_agents": 4021, "claude": 177, "chatgpt": 263, "grok": 296, "cursor": 248, "planner": 266}
    view = {"state": "invalid", "why": "the router notes are 6,412 characters; at most 6,000", "line": None,
            "reason_code": "notes_invalid", "sections": sections, "total": len(text), "max": 6000,
            "grok": {"share": 4317, "limit": 3662, "line": "Grok gets these only on a call they fit."},
            "hash": "9f2c4e1a7b3d5f60", "default": False}
    status["notes"] = dict(view)
    _write(root / "notes.json", {"api_version": 1, "notes": {**view, "text": text, "path": "config/router-notes.md"}})
    # twelve projects, the long one first in the sidebar's order of names
    extra = [{"name": LONG_PROJECT, "path": f"{LONG_ROOT}/{LONG_PROJECT}", "handoff_lines": 333, "open_task": None,
              "git": True, "branch": "main", "head": "c0ffee1", "tests": None, "files_mode": "on", "why": None}]
    extra += [{"name": f"garden-{k:02d}", "path": f"~/Projects/garden-{k:02d}", "handoff_lines": 4, "open_task": None,
               "git": False, "branch": None, "head": None, "tests": None, "files_mode": "off", "why": "no git yet: Turn on undo"}
              for k in range(8)]
    status["projects"] = status["projects"] + extra
    produced = ("src/components/northwind-industries-holdings/seed-library/lending/OutOfStockPacketRefusal."
                "integration.test.tsx and docs/lending-rules/aleksandra-wisniewska-kowalczyk-approval-notes.md")
    entries = [f"### #{900 + k} · 2026-10-2{k % 10} · writing · claude\nProduced:\n{produced}\nStatus:\n"
               "The lending rules are drafted and waiting for the committee's vote on Saturday.\nNext:\nLand it." for k in range(8)]
    block = "<!-- sr:start -->\n\n" + "\n\n".join(entries) + "\n\n<!-- sr:end -->"
    notes_lines = [f"- Bed {k}: {('Wiśniewska-Kowalczyk ' * (k % 3)).strip() or 'Jo'} waters it on Saturdays"
                   for k in range(312)]
    long_notes = "\n".join(notes_lines)
    long_notes = long_notes[:19990]
    _write(root / "project-notes" / f"{LONG_PROJECT}.json", {"api_version": 1, "notes": {
        "name": LONG_PROJECT, "folder": f"{LONG_ROOT}/{LONG_PROJECT}", "notes": long_notes, "block": block,
        "hash": "1a2b3c4d5e6f7a8b", "chars": len(long_notes), "lines": len(long_notes.splitlines()), "max": 20000,
        "git": True, "tracked": True, "exists": True, "has_block": True}})
    for project in extra[1:]:
        _write(root / "project-notes" / f"{project['name']}.json", {"api_version": 1, "notes": {
            "name": project["name"], "folder": project["path"], "notes": "", "block": "<!-- sr:start -->\n<!-- sr:end -->",
            "hash": "0000000000000000", "chars": 0, "lines": 0, "max": 20000, "git": False, "tracked": False,
            "exists": True, "has_block": True}})

    def both(row, **fields):
        row.update(fields)
        if row["task_id"] in shows:
            shows[row["task_id"]].update(fields)

    done = [t for t in rows if t.get("outcome") in ("passed", "fixed") and t.get("result")]
    big = done[0]
    both(big, result=BIG_RESULT, save_path="docs/" + "northwind-industries-holdings-quarterly" + ".md",
         card_actions={"pin": True, "save": True, "forget": True, "remember": False}, chat=LONG_CHAT)
    gone = done[1]
    both(gone, forgotten="2026-10-28", card_actions={"pin": True, "save": True, "forget": False, "remember": True},
         chat=LONG_CHAT)
    detailed = done[2]
    calls = []
    for k in range(20):
        agent = ("claude", "chatgpt", "grok", "cursor")[k % 4]
        record = ({"left_out": "grok_limit", "chars": 4317, "from": detailed["task_id"]} if agent == "grok" else
                  {"sections": {"all_agents": 4021, agent: sections[agent], **({"planner": 266} if k == 0 else {})},
                   "judge": k % 2 == 1, "planner": k == 0, "chars": 4900})
        calls.append({"call_id": f"{detailed['task_id']}-{k}", "order": k + 1,
                      "kind": "stage" if k % 3 == 0 else ("check", "fix", "recheck")[k % 3], "stage": k + 1,
                      "role": "split_plan" if k == 0 else "attack" if k % 3 == 0 else None, "agent": agent,
                      "status": "done", "verdict": None, "sent_at": detailed["created_at"], "finished_at": None,
                      "round_file": None, "served": None, "reason_code": None, "resume_of": None, "fallback_of": None,
                      "takeover_of": None, "search": None, "memory": None, "tests": None, "cwd": None, "tools": None,
                      "said": None, "items": [], "blocked": None, "prompt_file": None, "router_notes": record})
    both(detailed, router_notes={"hash": "9f2c4e1a7b3d5f60", "chars": 6412,
                                 "file": f"tasks/{detailed['task_id']}/router-notes.md"})
    shows[detailed["task_id"]]["calls"] = calls
    _save(root, log, status, rows, shows)


# Brief 31: Test, Run, Stop and Secrets at their worst. The 51-character project carries a 300-character test command
# whose last Test was killed (exit 137) after 20,000 characters of pytest's coloured output with a 412-character path line;
# a 300-character run command (quotes, a space in a path) whose run is going, its tail 2,000 lines of long JSON log lines
# with a masked key; 40 .env names, the longest 80 characters, 6 empty, in a deep iCloud folder. Beside it: a project whose
# Test and Run are both off, one whose run exited 137, one whose run never started, one with exactly one name, one Test
# running live, and one with no .env at all.
ENV_NAMES = (["NORTHWIND_INDUSTRIES_HOLDINGS_QUARTERLY_REPORTING_SERVICE_ACCOUNT_CREDENTIALS_JSON",
              "ALEKSANDRA_WISNIEWSKA_KOWALCZYK_PERSONAL_ACCESS_TOKEN", "STRIPE_SECRET_KEY", "DATABASE_URL", "JO"]
             + [f"GARDEN_CLUB_INTEGRATION_{k:02d}_API_KEY" for k in range(35)])
TEST_WORDS = ["python3", "-m", "pytest", "tests/unit", "tests/integration", "-k",
              "not slow and not network and not wisniewska_kowalczyk_import", "--maxfail=1", "--durations=10", "-p",
              "no:cacheprovider", "--color=yes", "--junitxml=reports/northwind-industries-holdings/quarterly/junit.xml",
              "--cov=northwind_industries_holdings", "--cov-report=term-missing:skip-covered", "-o",
              "log_cli=true"]
RUN_WORDS = ["python3", "-m", "uvicorn", "northwind_industries_holdings.website.app:create_app", "--factory", "--host",
             "127.0.0.1", "--port", "8000", "--reload", "--reload-dir", "src/northwind_industries_holdings",
             "--log-config", "config/logging (development, Aleksandra).yaml", "--env-file", ".env",
             "--proxy-headers", "--forwarded-allow-ips=127.0.0.1"]
DEEP_PATH = ("tests/integration/northwind_industries_holdings/website/quarterly_board_review/"
             "aleksandra_wisniewska_kowalczyk/test_out_of_stock_packet_refusal_for_the_seed_library_lending_rules_"
             "when_the_committee_has_not_yet_voted_on_saturday_and_the_intern_jo_has_already_sent_the_newsletter.py")


def _test_output():
    lines = ["\x1b[1m============================= test session starts ==============================\x1b[0m",
             "platform darwin -- Python 3.14.7, pytest-8.4.2, pluggy-1.6.0", "rootdir: ~/Projects/" + LONG_PROJECT,
             "collected 1,284 items", ""]
    k = 0
    while len("\n".join(lines)) < 19_000:
        lines.append(f"{DEEP_PATH}::test_case_{k} \x1b[32mPASSED\x1b[0m\t[{k % 100:3d}%]")
        k += 1
    lines += ["Fatal Python error: Killed (out of memory)", "\x1b[31m\x1b[1m1 failed\x1b[0m, 1,283 passed in 293.41s"]
    return "\n".join(lines)[-20_000:]


def _run_output():
    lines = []
    for k in range(2000):
        if k == 3:
            lines.append("Loading the board's key: [REDACTED]")
        lines.append(json.dumps({"ts": f"2026-10-28T10:{k // 60 % 60:02d}:{k % 60:02d}Z", "level": "INFO",
                                 "msg": "GET /lending/packets?member=Aleksandra%20Wi%C5%9Bniewska-Kowalczyk&state=" + _STATE,
                                 "status": 200, "ms": k % 97}))
    return "\n".join(lines[-2000:]) + "\n"


def _projects31(root, log, status, shows):
    rows, shows, status = copy.deepcopy(log["tasks"]), copy.deepcopy(shows), copy.deepcopy(status)
    stamp = "2026-10-28T10:42:07+00:00"

    def project(name, **fields):
        base = {"name": name, "path": f"~/Projects/{name}", "handoff_lines": 4, "open_task": None, "git": True,
                "branch": "main", "head": "c0ffee1", "tests": ["python3", "-m", "unittest"], "files_mode": "on",
                "why": None, "last_test": None, "run_command": None, "run": None, "secrets": None}
        return {**base, **fields}
    extra = [
        project(LONG_PROJECT, path=f"{LONG_ROOT}/{LONG_PROJECT}", tests=TEST_WORDS,
                last_test={"outcome": "failed", "exit": 137, "when": stamp, "summary": "1 failed, 1,283 passed",
                           "head": "c0ffee1"},
                run_command=RUN_WORDS, run={"state": "running", "running": True, "started": stamp, "ended": None,
                                            "exit": None}, secrets=len(ENV_NAMES)),
        project("garden-00", git=False, head=None, branch=None, files_mode="off",
                why="it is inside another git repository, not at its top level", tests=None),
        project("garden-01", run_command=["python3", "app.py"],
                run={"state": "exited", "running": False, "started": stamp, "ended": stamp, "exit": 137}, secrets=0),
        project("garden-02", run_command=["python3", "app.py"],
                run={"state": "exited", "running": False, "started": stamp, "ended": stamp, "exit": None}),
        project("garden-03", run_command=["python3", "app.py"], secrets=1,
                last_test={"outcome": "timed_out", "exit": None, "when": stamp, "summary": "timed out after 300 s",
                           "head": "c0ffee1"}),
        project("garden-04", last_test={"outcome": "passed", "exit": 0, "when": stamp, "summary": "OK", "head": "c0ffee1"},
                test_running=True),
        project("garden-05", path=f"{LONG_ROOT}/garden-05", run_command=RUN_WORDS, secrets=len(ENV_NAMES)),  # Run's confirm
    ]
    mine = {item["name"] for item in extra}
    status["projects"] = [p for p in status["projects"] if p.get("name") not in mine] + extra
    secrets = {LONG_PROJECT: [{"name": n, "set": k % 7 != 6} for k, n in enumerate(ENV_NAMES)],
               "garden-00": [], "garden-01": [], "garden-02": [], "garden-03": [{"name": "JO", "set": True}], "garden-04": [],
               "garden-05": [{"name": n, "set": True} for n in ENV_NAMES]}
    for name, found in secrets.items():
        _write(root / "secrets" / f"{name}.json", {"api_version": 1, "project": {"name": name, "secrets": found}})
    for item in extra:
        name = item["name"]
        test = {"running": False, "started": None, "head": None, "output": "", "last": item["last_test"]}
        if name == LONG_PROJECT:
            test["output"] = projrun.shown(_test_output())  # as the router's read gives it (break-ui 1)
        if name == "garden-04":  # a Test running live
            test = {"running": True, "started": stamp, "head": "c0ffee1a2b3c", "output": "test_lend.py ..\n", "last": None}
        _write(root / "project-output" / f"{name}-test.json", {"api_version": 1, "project": {"name": name, "test_status": test}})
        run = item["run"] or {}
        doc = {"running": bool(run.get("running")), "state": run.get("state"), "command": item["run_command"],
               "ran": item["run_command"], "started": run.get("started"), "ended": run.get("ended"), "exit": run.get("exit"),
               "output": projrun.shown(_run_output()) if name == LONG_PROJECT else ("" if not run else "Traceback (most recent call last):\n  "
                         "File \"app.py\", line 1\nMemoryError\n"), "folder": item["path"],
               "env_names": [f["name"] for f in secrets.get(name, [])]}
        _write(root / "project-output" / f"{name}-run.json", {"api_version": 1, "project": {"name": name, "run_status": doc}})
    _save(root, log, status, rows, shows)


# Brief 31: the projects31 scenario's fake `sr`: Test, the run command, Run, Stop and a secret's set or remove each answer
# as the router's envelope does; it reads a secret's value on stdin and says only its length. `refuse` in the scenario
# folder makes each refuse with the router's longest words.
FAKE_PROJECTS_SR = r"""
import json, os, sys, time
args = sys.argv[1:]
value = sys.stdin.read() if "--set" in args else ""
open("runs.jsonl", "a").write(json.dumps({"argv": args, "stdin": len(value)}) + "\n")
env = {"task_id": None, "n": None, "status": None, "waiting_on": None, "outcome": None, "reason_code": None, "exit": 0,
       "message": "fake sr: " + " ".join(args[:2]) + (f" (a value of {len(value)} characters on stdin)" if value else "")}
time.sleep(3.0 if args[1:2] == ["test"] else 1.0)
if os.path.exists("refuse"):
    env.update(reason_code="project_refused", exit=2, message="Refused: this project's .env holds a name containing "
               "\"NORTHWIND_INDUSTRIES_HOLDINGS_QUARTERLY_REPORTING\" (never_run_env in this Mac's local settings), so Run "
               "never starts it. Nothing was started. (git doesn't ignore its .env: add .env to its .gitignore first.)")
print(json.dumps(env), file=sys.stdout if env["exit"] == 0 else sys.stderr)
sys.exit(env["exit"])
"""


# Brief 30: the notes30 scenario's fake `sr`: a notes save, a project notes save, a pin, a save and a forget each answer as
# the router's envelope does; `refuse` in the scenario folder makes each refuse with the router's longest words.
FAKE_NOTES_SR = r"""
import json, os, sys, time
args = sys.argv[1:]
open("runs.jsonl", "a").write(json.dumps(args[:4]) + "\n")
env = {"task_id": None, "n": None, "status": None, "waiting_on": None, "outcome": None, "reason_code": None, "exit": 0,
       "message": "fake sr: " + " ".join(args[:2])}
time.sleep(1.2)
if os.path.exists("hang"):
    time.sleep(3600)
if os.path.exists("refuse"):
    env.update(reason_code="notes_key", exit=2, message="Refused: the router notes were not saved: line 4,812 looks like it "
               "holds a key. Nothing was written. Fix it in Setup → Router notes. The notes go to every agent's service, "
               "Grok Bot's inbox at https://github.com/northwind-industries-holdings/router-inbox-for-the-quarterly-board "
               "included, so they hold nothing private.")
print(json.dumps(env), file=sys.stdout if env["exit"] == 0 else sys.stderr)
sys.exit(env["exit"])
"""


def _split(root, log, status, shows):
    """Brief 29: the plan card, the split's piece lines and the No split card at their worst, on one screen (History).
    Not a demo: the fake `sr` records each run, and the reader lays what it changed over the documents."""
    rows, shows, status = copy.deepcopy(log["tasks"]), copy.deepcopy(shows), copy.deepcopy(status)
    plan = next(t for t in rows if t.get("waiting_on") == "split_plan" and t["text"].startswith("Three separate"))
    show = shows[plan["task_id"]]
    for doc in (plan, show):
        doc.update(text=LONG_SPLIT_TASK, project=LONG_PROJECT, tag=f"project:{LONG_PROJECT}",
                   project_files={"mode": "on", "state": "none", "copy": True, "base": "4f2a9c1e5b7d3a8f6c0e2b4d6f8a1c3e5b7d9f0a",
                                  "branch": "main", "files": 1284, "left_out": [], "changed": [], "diff": None,
                                  "latest": None, "tests": None, "commit": None, "undo_commit": None, "why": None})
    first, second, third = show["pieces"]
    first.update(text=LONG_PIECE, needs_label=True, route=None, jev={"status": "below_floor", "label": "planning",
                                                                     "confidence": 0.52},
                 team_why="One email, written once and checked once: the skill table's writer and its checker are enough.")
    second.update(text=SHORT_PIECE, edited=True, jev={"status": "ok", "label": "writing", "confidence": 0.97})
    third.update(refused={"code": "slot_refused", "reason": LONG_REFUSAL}, team_why=LONG_TEAM_WHY)
    fourth = copy.deepcopy(second)
    fourth.update(piece=4, task_id=second["task_id"][:-4] + "beef", text=(
        "Decide whether the seed library should keep its loan records in a spreadsheet or a paper notebook, with one line "
        "why."), edited=False, team="vote", planner_team="vote", team_source="planner", team_why=LONG_TEAM_WHY,
        chain="Claude answers → ChatGPT answers → Grok Bot answers → the count (a tie: your pick)", needs_you="tie",
        calls=3, max_calls=3, jev={"status": "ok", "label": "quick_answer", "confidence": 0.86})
    show["pieces"].append(fourth)
    show["join"] = LONG_JOIN
    show["estimate"] = {"calls": 14, "max_calls": 1284, "jev_labels": 4}  # a huge maximum: the count never truncates
    for team in show["menu"]:
        if team["name"] == "research-build":
            team.update(ready=False, why=LONG_REFUSAL)
    # the split waiting on its pieces: every state, and a part of 37 files
    split = next(t for t in rows if t.get("waiting_on") == "land" and t.get("mode") == "split")
    sshow = shows[split["task_id"]]
    for doc in (split, sshow):
        doc.update(waiting_on="piece", status="returned", outcome=None, card_line=None)
    done, blocked = sshow["pieces"]
    done["project_files"]["changed"] = PART
    blocked.update(status="done", outcome="failed_check", piece_state="blocked", why="it failed its check twice",
                   project_files=dict(blocked["project_files"], changed=[]))
    base = next(t for t in log["tasks"] if t.get("waiting_on") == "pick" and t.get("parent"))
    versus, _ = _clone(rows, shows, base, Ids(), max(t["n"] for t in rows) + 1, root, parent=split["task_id"],
                       piece_of={"split": split["task_id"], "n": split["n"], "piece": 3, "team": "versus"},
                       project=split.get("project"))  # its own piece: a task belongs to one split
    waiting = dict(copy.deepcopy(blocked), piece=3, task_id=versus["task_id"], n=versus["n"], status="returned", outcome=None,
                   piece_state="waiting", why="waits for your pick", team="versus", text=versus["text"])
    held = dict(copy.deepcopy(blocked), piece=4, task_id=blocked["task_id"][:-4] + "cafe", n=None, status="queued",
                outcome=None, piece_state="waiting", why="waits for piece 2", text=LONG_PIECE)  # the order hold's words
    sshow["pieces"] += [waiting, held]
    # No split: a long line on a long task, on a project
    nosplit = next(t for t in rows if t.get("no_split"))
    for doc in (nosplit, shows[nosplit["task_id"]]):
        doc.update(text=LONG_NO_SPLIT_TASK, no_split=LONG_NO_SPLIT, result=f"no split: {LONG_NO_SPLIT}", project=LONG_PROJECT,
                   tag=f"project:{LONG_PROJECT}")
    entry = {"name": LONG_PROJECT, "path": f"~/Projects/{LONG_PROJECT}", "handoff_lines": 212, "open_task": None,
             "git": True, "branch": "main", "head": "4f2a9c1", "tests": LONG_TESTS, "files_mode": "on", "why": None}
    status["projects"] = [p for p in status["projects"] if p["name"] != LONG_PROJECT] + [entry]  # once, with git on
    _write(root / "projects.json", {**_read("projects.json"), "projects": _read("projects.json")["projects"] + [
        {"name": LONG_PROJECT, "path": f"~/Projects/{LONG_PROJECT}", "handoff": True}]})
    _save(root, log, status, rows, shows)
    shutil.copytree(root / "files" / "tasks", root / "tasks", dirs_exist_ok=True)  # not a demo: files sit beside the log


def _projectfiles(root, log, status, shows):
    """Brief 28: the waiting task gets 500 changed files (the limit), deep paths and binaries; seed-library a test command
    at the 300-character limit; garden-site the longest why. The fake `sr` changes `files.json`, which the reader lays
    over every row, so Land, Undo and Discard show their next state."""
    rows, status = copy.deepcopy(log["tasks"]), copy.deepcopy(status)
    waiting = next(t for t in rows if (t.get("project_files") or {}).get("state") == "waiting")
    changed = [{"path": DEEP, "status": "changed", "plus": 1284, "minus": 977},
               {"path": "assets/logo-final-v12-APPROVED.png", "status": "added", "plus": None, "minus": None},
               {"path": "a", "status": "deleted", "plus": 0, "minus": 1}]
    changed += [{"path": f"src/loans/rules/rule_{k:03d}.py", "status": "added", "plus": 12, "minus": 0} for k in range(497)]
    waiting["project_files"]["changed"] = changed
    for row in rows:
        if row["task_id"] in shows:
            shows[row["task_id"]].update({k: row[k] for k in ("project_files",)})
    for project in status["projects"]:
        if project["name"] == "seed-library":
            project["tests"] = LONG_TESTS
        if project["name"] == "garden-site":
            project["why"] = LONG_WHY
            project["git"] = True
    _write(root / "files.json", {})
    status["drop_folder"] = str((root / "drop").resolve())  # the scenario's own drop folder, never the owner's
    (root / "drop").mkdir()
    _save(root, log, status, rows, shows)
    shutil.copytree(root / "files" / "tasks", root / "tasks", dirs_exist_ok=True)  # not a demo: files sit beside the log
    diff = root / "tasks" / waiting["task_id"] / "changes.diff"
    lines = [f"diff --git a/{DEEP} b/{DEEP}", "index 1111111..2222222 100644", f"--- a/{DEEP}", f"+++ b/{DEEP}",
             "@@ -1,977 +1,1284 @@"]
    lines += [f"-  expect(screen.getByText('{'Bartholomew Fitzgerald ' * 6}')).toBeVisible(); // {k}" for k in range(977)]
    lines += [f"+  expect(await screen.findByRole('row', {{ name: /{'Aleksandra Wiśniewska-Kowalczyk ' * 5}/ }})).toBeVisible(); // {k}"
              for k in range(1284)]
    diff.write_text("\n".join(lines) + "\n", encoding="utf-8")


# Brief 32 (decision 17): the redteam board at its worst. An attack, an answer and a skip's reason are model or router
# lines with no limit; a list has at least 3 items and no most (relay.MIN_ATTACKS); labels run past A9; the check's verdict
# is open, passed or not yet per attack; a list that didn't run is one line, as long as the router writes its why; the
# stage line carries every re-ask; the picker's Second attack is left out with the longest reason status gives.
SHEET_URL = ("https://docs.example.org/spreadsheets/d/1Bx9Kp2LmN4qRsTuVwXyZ0aBcDeFgHiJkLmNoPqRsTuV/edit?usp=sharing"
             "#gid=1284093847&range=A1:H200")
RT_A = [("high", f"The plan shares the sheet as {SHEET_URL}, and anyone holding that link can edit it, so one mistaken "
                 "paste overwrites a day of pre-orders with no record of who did it or when."),
        ("medium", "Aleksandra Wiśniewska-Kowalczyk owns the sheet on Saturdays, but step 2 names Jo as the weekend owner, "
                   "so nobody knows who answers a customer whose loaf is missing."),
        ("low", "Vague."),
        ("high", "normalize_preorder_spreadsheet_row_before_export_to_weekly_pickup_list() is named in step 4 and never "
                 "defined, so the export step can't be followed."),
        ("medium", "The notes column will show raw <b>bold</b> tags and &amp; from the paper list's import."),
        ("low", "Lịch nhận bánh không ghi múi giờ (UTC+7), nên chi nhánh Đà Nẵng sẽ đọc sai giờ lấy bánh."),
        ("medium", "The 🥖 column header won't sort in older spreadsheet apps."),
        ("low", "Step 3 prints the list at closing, but closing time changes in winter."),
        ("medium", "There is no way to mark an order collected, so a second pickup can't be caught."),
        ("low", "The plan doesn't say how long old orders stay in the sheet."),
        ("high", "Phone orders taken while the sheet is open on another till can be lost when both save."),
        ("low", "The pickup day column takes free text, so 'Sat', 'saturday' and '26/10' all appear."),
        ("medium", "Nothing says who may delete a row."),
        ("low", "The printed list has no page numbers.")]
RT_B = [("high", "Nobody reviews the list when the shop is short-staffed, so a missed order isn't caught before pickup."),
        ("medium", "The sheet has no column for allergies, though the paper list had one."),
        ("low", "6pm says no time zone."),
        ("high", "A customer's phone number sits in a sheet shared by link, which the shop's privacy notice doesn't cover."),
        ("medium", "Card payments taken over the phone aren't told apart from cash ones."),
        ("low", "The plan says 'staff' without saying which staff."),
        ("medium", "If the internet is down, the plan has no fallback list."),
        ("low", "Column order differs from the paper list's, which slows the first week."),
        ("medium", "Two branches would share one sheet with no branch column."),
        ("low", "There is no example row."),
        ("low", "'Daily copy' doesn't say where the copy goes.")]
RT_ANSWERS = {"A3": "Too vague to act on.",
              "A6": "The shop has one branch; Đà Nẵng is a customer's town, not a branch.",
              "B1": ("The shop is two people on weekdays and both see the sheet on the till; the plan's step 3 print at "
                     f"closing is the review, and the committee's notes at {SHEET_URL} already assign it to whoever closes, "
                     "so a separate reviewer would be a third person the shop doesn't have."),
              "B3": "The shop is in one town.", "B6": "Staff means everyone on the rota, as the paper list did.",
              "B10": "An example row would be a real customer's order."}
LONG_SKIP = ("its list missed its contract after the re-ask: Attacks: need 3 numbered items with a severity, found 2; "
             "Attacks: item 4 has no severity; start it `4. [high|medium|low]`; Strongest: need exactly one line, found 3")
LONG_OUT = ("Cursor's safety check could not run on agent 2026.10.22-27dcf5f (the command line gave no version line in 30 "
            "seconds: it may be updating itself); it is tried again after 11:42")


def _attacks_of(items, letter, agent, checks, answers=RT_ANSWERS):
    return [{"label": f"{letter}{k}", "attacker": agent, "n": k, "severity": sev, "text": text,
             "answered": answers.get(f"{letter}{k}"), "check": checks.get(f"{letter}{k}", "ok")}
            for k, (sev, text) in enumerate(items, 1)]


def _list_of(stage, agent, letter, items, state="ran", why=None, line=None):
    return {"stage": stage, "agent": agent, "letter": letter, "strongest": items[0][1] if items else None,
            "items": [{"label": f"{letter}{k}", "n": k, "severity": s, "text": x} for k, (s, x) in enumerate(items, 1)],
            "state": state, "why": why, "line": line, "round_file": None}


def _call(base, task_id, order, kind, stage, role, agent, status="done", reason=None, verdict=None):
    call = copy.deepcopy(base)
    call.update(call_id=f"{task_id}-c{order}", order=order, kind=kind, stage=stage, role=role, agent=agent, status=status,
                reason_code=reason, verdict=verdict, round_file=None, prompt_file=None)
    return call


def _redteam32(root, log, status, shows):
    rows, shows, status, ids = copy.deepcopy(log["tasks"]), copy.deepcopy(shows), copy.deepcopy(status), Ids()
    base = _base(rows, lambda t: t.get("preset") == "redteam" and t["text"].startswith("Plan how the bakery"))
    n = max(t["n"] for t in rows)
    one = shows[base["task_id"]]["calls"][0]

    def task(text, slots, attacks, lists, calls, **changes):
        nonlocal n
        n += 1
        row, show = _clone(rows, shows, base, ids, n, root, text=text, slots=slots, **changes)
        show.update(attacks=attacks, attack_lists=lists,
                    calls=[_call(one, row["task_id"], k, *c) for k, c in enumerate(calls, 1)])
        return row, show

    both = {"build": "claude", "attack": "chatgpt", "attack2": "cursor", "check": "chatgpt"}
    # two long lists, every check verdict, every re-ask on the stage line
    task("Plan how the bakery moves its pre-orders from a paper list to a shared spreadsheet, for both tills and the "
         "weekend staff, with a fallback when the internet is down and a privacy line for customers' phone numbers.", both,
         _attacks_of(RT_A, "A", "chatgpt", {"A1": "open", "A11": None}) + _attacks_of(RT_B, "B", "cursor", {"B4": "open"}),
         [_list_of(2, "chatgpt", "A", RT_A), _list_of(3, "cursor", "B", RT_B)],
         [("stage", 1, "build", "claude"), ("stage", 2, "attack", "chatgpt"), ("reask", 3, "attack", "cursor"),
          ("stage", 3, "attack", "cursor"), ("reask", 4, "revise", "claude"), ("stage", 4, "revise", "claude"),
          ("check", None, None, "chatgpt", "done", None, "FIX"), ("fix", None, None, "claude"),
          ("reask", None, "fix", "claude"), ("recheck", None, None, "chatgpt", "done", None, "FIX")],
         outcome="failed_check", check_state="failed",
         open_musts=[{"n": 1, "text": f"A1 is neither fixed nor answered: {SHEET_URL} is still shared by link. (not fixed)"},
                     {"n": 2, "text": "B4: the privacy line names no one to ask about a phone number. (not fixed)"}])
    # the second attack skipped, its reason as long as the contract's lines make it
    task("Plan the bakery's Saturday pickup rota.", both, _attacks_of(RT_A[:3], "A", "chatgpt", {}),
         [_list_of(2, "chatgpt", "A", RT_A[:3]),
          _list_of(3, "cursor", "B", [], "skipped", LONG_SKIP, f"Second attack skipped: {LONG_SKIP}")],
         [("stage", 1, "build", "claude"), ("stage", 2, "attack", "chatgpt"), ("stage", 3, "attack", "cursor"),
          ("reask", 3, "attack", "cursor", "done", "skipped"), ("stage", 4, "revise", "claude"),
          ("check", None, None, "chatgpt")])
    # left out at intake, with the longest reason status gives Cursor
    task("Plan the bakery's holiday hours sign.", dict(both, attack2=None), _attacks_of(RT_A[:3], "A", "chatgpt", {}),
         [_list_of(2, "chatgpt", "A", RT_A[:3]),
          _list_of(None, "cursor", "B", [], "left_out", LONG_OUT, f"One attacker: Cursor isn't available ({LONG_OUT})")],
         [("stage", 1, "build", "claude"), ("stage", 2, "attack", "chatgpt"), ("stage", 3, "revise", "claude"),
          ("check", None, None, "chatgpt")])
    # the least: three attacks each, every one answered, Grok Bot as the second attacker (a flag), its check running
    answered = {f"{c}{k}": "Out of scope." for c in "AB" for k in (1, 2, 3)}
    unchecked = {f"{c}{k}": None for c in "AB" for k in (1, 2, 3)}
    task("Name the new rye loaf.", dict(both, attack2="grok"),
         _attacks_of(RT_A[:3], "A", "chatgpt", unchecked, answered) + _attacks_of(RT_B[:3], "B", "grok", unchecked, answered),
         [_list_of(2, "chatgpt", "A", RT_A[:3]), _list_of(3, "grok", "B", RT_B[:3])],
         [("stage", 1, "build", "claude"), ("stage", 2, "attack", "chatgpt"), ("stage", 3, "attack", "grok"),
          ("stage", 4, "revise", "claude"), ("check", None, None, "chatgpt", "sent")],
         status="sent", outcome=None, check_state="pending", result=None)
    # a task from before brief 32: one list by number, no labels
    row, show = task("Plan the bakery's loyalty card.", {"build": "claude", "attack": "chatgpt", "check": "chatgpt"},
                     [{"n": k, "severity": s, "text": x, "answered": None} for k, (s, x) in enumerate(RT_A[:4], 1)], None,
                     [("stage", 1, "build", "claude"), ("stage", 2, "attack", "chatgpt"), ("stage", 3, "revise", "claude"),
                      ("check", None, None, "chatgpt")])
    show.pop("attack_lists")
    # the picker: every agent up but Cursor, its reason the longest; redteam runs with the second attack left out
    for a in status["agents"]:
        if a["name"] != "cursor":
            a.update(available=True, why=None, why_code=None, online=True)
        else:
            a.update(available=False, why=LONG_OUT, why_code="probe_failed")
    red = next(p for p in status["presets"] if p["name"] == "redteam")
    red.update(ready=True, why=None, filled=[{"slot": "attack2", "agent": None, "default": "cursor", "why": LONG_OUT}])
    allowed = {"build": ["claude", "chatgpt"], "attack": ["claude", "chatgpt", "grok"], "attack2": ["claude", "chatgpt", "grok"],
               "check": ["claude", "chatgpt"]}
    for slot in red["slots"]:
        slot["allowed"] = allowed[slot["name"]]
    _save(root, log, status, rows, shows)


# Brief 32.1: the pinned stream head and whole results at their worst. The longest project bar (the 51-character project,
# a 300-character test command whose last run failed, a run going, eleven secrets) over a stream of 40 cards; one result
# of 15,000 characters with code blocks, a table and headings (it shows whole now); one of 25,000 (past PREVIEW_CHARS:
# its first part and Show all beside, as before). All tasks' filters and search ride in the same head.
def _long_result(size):
    part = ("## Step {k}: move the pre-orders\n\nEach till exports its orders, then the job merges them by pickup day.\n\n"
            "```python\ndef merge(rows):\n    seen = {{}}\n    for row in rows:\n        key = (row[\"name\"], row[\"pickup\"])\n"
            "        seen[key] = seen.get(key, 0) + row[\"qty\"]\n    return seen\n```\n\n"
            "| Till | Orders | Late | Owner |\n|---|---:|---:|---|\n| North | 1,284 | 12 | Aleksandra Wiśniewska-Kowalczyk |\n"
            "| South | 977 | 3 | Bartholomew Fitzgerald |\n| Web | 3 | 0 | Jo |\n\n- Check the totals.\n- Print the list.\n\n")
    text, k = "", 1
    while len(text) < size:
        text += part.format(k=k)
        k += 1
    return text[:size]


def _pinned321(root, log, status, shows):
    rows, shows, status, ids = copy.deepcopy(log["tasks"]), copy.deepcopy(shows), copy.deepcopy(status), Ids()
    stamp = "2026-10-28T10:42:07+00:00"
    long_bar = {"name": LONG_PROJECT, "path": f"{LONG_ROOT}/{LONG_PROJECT}", "handoff_lines": 212, "open_task": None,
                "git": True, "branch": "main", "head": "c0ffee1", "tests": TEST_WORDS, "files_mode": "on", "why": None,
                "last_test": {"outcome": "failed", "exit": 137, "when": stamp, "summary": "1 failed, 1,283 passed",
                              "head": "c0ffee1"},
                "run_command": RUN_WORDS, "run": {"state": "running", "running": True, "started": stamp, "ended": None,
                                                  "exit": None}, "secrets": len(ENV_NAMES)}
    status["projects"] = [p for p in status["projects"] if p.get("name") != LONG_PROJECT] + [long_bar]
    done = [t for t in rows if t.get("outcome") == "passed" and t.get("result")]
    n = max(t["n"] for t in rows)
    for k in range(40):
        n += 1
        base = done[k % len(done)]
        changes = {"project": LONG_PROJECT, "chat": None, "text": f"{base['text']} (card {k + 1} of 40)"}
        if k == 37:
            changes["result"] = _long_result(15000)
        if k == 38:
            changes["result"] = _long_result(25000)
        _clone(rows, shows, base, ids, n, root, **changes)
    _save(root, log, status, rows, shows)


# Brief 33 (the rest, /break-ui): the chips, What now? and the Ideas list at their worst. A chip's words are a line cut at a
# word to 400 characters (checking.NEXT_MAX_CHARS); a card keeps at most 3 chips, so the most text is three agent chips on
# a forgotten card (no Build from); a 64-character chat beside the From and Idea pills; What now? on the 51-character
# project at its longest (a 400-character chip) with every control on the bar, so it folds into Project tools; the Ideas
# sheet at ideas_max, 50 open ideas, some at the 400-character limit, some sent, Later sources from five-digit tasks.
CHIP_400 = ("Compare the free tier's rate limits against what Open-Meteo's documentation says about non-commercial use, and "
            "check whether the forecast endpoint needs an attribution line on every page that shows the data in a table, "
            "a chart or a widget embedded in the partner sites of Northwind Industries Holdings, and whether Wiśniewska-"
            "Kowalczyk's team needs a separate key for the staging environment before the quarterly board review starts")


def _cut400(words):
    return words if len(words) <= 400 else words[:400].rsplit(" ", 1)[0]


def _chip(kind, words, task_id, project=None, chat=None, later=False):
    text = "" if kind == "build_from" else words
    source = task_id if kind == "build_from" or not project else None
    return {"kind": kind, "words": words, "later": later,
            "fill": {"team": "route", "project": project, "chat": None if project else chat, "text": text,
                     "from": source, "idea": None}}


def _next33(root, log, status, shows):
    rows, shows, status, ids = copy.deepcopy(log["tasks"]), copy.deepcopy(shows), copy.deepcopy(status), Ids()
    done = [t for t in rows if t.get("outcome") == "passed" and t.get("result") and not t.get("project")]
    n = 12340
    long_chip = _cut400(CHIP_400)
    older, _ = _clone(rows, shows, done[0], ids, n, root, chat=LONG_CHAT, project=None, tag=f"chat:{LONG_CHAT}",
                      text="Find two free weather APIs that need no API key. Give each one's rate limit and a link.")
    older["next"] = [_chip("build_from", f"Build from #{n}", older["task_id"], chat=LONG_CHAT),
                     _chip("agent", long_chip, older["task_id"], chat=LONG_CHAT), _chip("agent", "Map it.", older["task_id"], chat=LONG_CHAT)]
    shows[older["task_id"]]["next"] = older["next"]
    n += 1
    newest, _ = _clone(rows, shows, done[1], ids, n, root, chat=LONG_CHAT, project=None, tag=f"chat:{LONG_CHAT}",
                       forgotten="2026-10-20",
                       text="Write a Python script that prints today's forecast for San Diego from the first API.")
    newest["next"] = [_chip("agent", _cut400(f"{CHIP_400} ({k})"), newest["task_id"], chat=LONG_CHAT) for k in (1, 2, 3)]
    for chip in newest["next"]:
        chip["fill"]["from"] = None  # decision 7: a forgotten card's chips carry no --from
    shows[newest["task_id"]]["next"] = newest["next"]
    n += 1
    card, _ = _clone(rows, shows, done[2], ids, n, root, project=LONG_PROJECT, chat=None, tag=f"project:{LONG_PROJECT}",
                     text="Add a function c_to_f(c) to temps.py that converts Celsius to Fahrenheit, with a test.")
    card["next"] = [_chip("build_from", f"Build from #{n}", card["task_id"], project=LONG_PROJECT),
                    _chip("agent", long_chip, card["task_id"], project=LONG_PROJECT, later=True),
                    _chip("agent", "Add a --round option.", card["task_id"], project=LONG_PROJECT, later=True)]
    shows[card["task_id"]]["next"] = card["next"]
    stamp = "2026-10-28T10:42:07+00:00"
    bar = {"name": LONG_PROJECT, "path": f"{LONG_ROOT}/{LONG_PROJECT}", "handoff_lines": 212, "open_task": None, "git": True,
           "branch": "main", "head": "c0ffee1", "tests": TEST_WORDS, "files_mode": "on", "why": None,
           "last_test": {"outcome": "failed", "exit": 137, "when": stamp, "summary": "1 failed, 1,283 passed", "head": "c0ffee1"},
           "run_command": RUN_WORDS, "run": {"state": "running", "running": True, "started": stamp, "ended": None, "exit": None},
           "secrets": len(ENV_NAMES), "ideas": 50,
           "what_now": {"rung": 4, "words": f"Next: {long_chip}", "control": "chip", "task_id": card["task_id"], "n": n,
                        "chip": card["next"][1]}}
    status["projects"] = [p for p in status["projects"] if p.get("name") != LONG_PROJECT] + [bar]
    projects_doc = _read("projects.json")
    projects_doc["projects"] = [p for p in projects_doc["projects"] if p.get("name") != LONG_PROJECT] + [bar]
    _write(root / "projects.json", projects_doc)
    listed = []
    for k in range(50, 0, -1):  # newest first, as `sr ideas` lists them
        text = _cut400(f"{CHIP_400} (idea {k})") if k % 7 == 0 else ("Map it." if k % 11 == 0 else f"Idea {k}: add a Kelvin column to the conversion table, and a test for -40.")
        later = k % 3 == 0
        listed.append({"id": k, "text": text, "source": {"kind": "later" if later else "added",
                                                          "task_id": card["task_id"] if later else None,
                                                          "n": 12345 + k if later else None},
                       "created_at": f"2026-10-{1 + k % 28:02d}T09:00:00+00:00", "state": "sent" if k % 10 == 0 else "open",
                       "sent_as": {"task_id": card["task_id"], "n": 23456 + k} if k % 10 == 0 else None})
    _write(root / "ideas" / f"{LONG_PROJECT}.json", {"task_id": None, "n": None, "status": None, "waiting_on": None,
                                                     "outcome": None, "reason_code": None, "exit": 0, "message": "",
                                                     "ideas": listed, "dismissed": 12})
    _save(root, log, status, rows, shows)


STEP_399 = _cut400(("Add the frost-window check to the Northwind community garden's sowing tracker: read the week's "
                     "forecast from the feed named in FROST_FEED_KEY, mark each sowing whose germination days fall inside a "
                     "frost window, and print the warnings sorted by bed, with Wiśniewska-Kowalczyk's naming rules for beds "
                     "kept exactly, and a test that fakes the feed so no network call is made in the router's sandbox run"))[:399]
WHY_199 = ("The forecast feed is the part most likely to be wrong, so it gets attacked by two agents before it lands, and "
           "the bed names must match the volunteers' printed labels exactly")[:199]
DONE_299 = ("tests/integration/test_frost_window.py's test_warns_for_a_sowing_inside_a_frost_window passes with the faked "
            "feed, checking that a bed sown two days before a forecast frost is warned and a bed sown after it is not, "
            "and the router's test run after the build shows it passing alongside the other 1,283 tests")[:299]


def _plan331(root, log, status, shows):
    """The plan card at its longest (12 steps, each at its limits, every kind of need), the bar's plan line with every
    control, What now?'s finish line, and a One step card."""
    rows, shows, status, ids = copy.deepcopy(log["tasks"]), copy.deepcopy(shows), copy.deepcopy(status), Ids()
    waiting = next(t for t in rows if t.get("mode") == "plan" and t.get("waiting_on") == "land")
    teams = ["route", "redteam", "research-build", "collab"]
    steps = [{"k": k, "text": f"{k}. {STEP_399}"[:399], "team": teams[k % 4], "why": WHY_199, "done_when": DONE_299,
              "calls": [2, 5, 3, 4][k % 4], "max_calls": [4, 7, 5, 6][k % 4], "jev_label": teams[k % 4] == "route",
              "state": "open", "task": None} for k in range(1, 13)]
    needs = ([{"kind": "key", "name": name, "what": "the quarterly board review's reporting service, read only", "step": k,
               "set": k % 2 == 0} for k, name in ((3, ENV_NAMES[0]), (5, "FROST_FEED_KEY"), (7, ENV_NAMES[-1]))]
             + [{"kind": "account", "name": None, "what": "a frost forecast feed account with a staging key for the partner "
                 "sites", "step": 3, "set": None},
                {"kind": "decision", "name": None, "what": "Warn three days or five days before a frost, and does a "
                 "covered bed count?", "step": 4, "set": None},
                {"kind": "test_command", "name": None, "what": " ".join(TEST_WORDS), "step": None, "set": False}])
    plan_view = {"n": 12345, "steps": steps, "needs": needs, "test_command": {"proposed": " ".join(TEST_WORDS), "set": None},
                 "estimate": {"calls": 46, "max_calls": 70, "jev_labels": 3}, "edits": [{"step": 2, "change": "up"}] * 3,
                 "edited": True, "planner_steps": steps, "current": False, "done": 0, "total": 12, "hash": "0" * 64}
    card, show = _clone(rows, shows, waiting, ids, 12345, root, project=LONG_PROJECT, tag=f"project:{LONG_PROJECT}",
                        text=LONG_SPLIT_TASK)
    card["plan"] = plan_view
    show["plan"] = plan_view
    one = next(t for t in rows if t.get("one_step"))
    one_row, one_show = _clone(rows, shows, one, ids, 12346, root, project="herb-labels", tag="project:herb-labels")
    long_task = STEP_399
    for doc in (one_row, one_show):
        doc["one_step"] = {"why": LONG_NO_SPLIT[:200], "task": long_task, "team": "research-build"}
        doc["result"] = "one step: " + LONG_NO_SPLIT[:200]
        doc["next"] = [{"kind": "build_it", "words": "Build it", "later": False,
                        "fill": {"team": "research-build", "project": "herb-labels", "chat": None, "text": long_task,
                                 "from": None, "idea": None, "step": None}}]
    finish = {"rung": "finish", "words": "All 12 steps done", "control": "chips", "task_id": card["task_id"], "n": 12345,
              "chip": None, "need": None, "plan_md": {"state": "left_out", "kind": "tick",
              "why": "docs/PLAN.md has uncommitted edits in the folder, so the router left it out of the commit"},
              "chips": [{"kind": "readme", "words": "Write the README", "later": False, "fill": {"team": "route",
                         "project": LONG_PROJECT, "chat": None, "text": "Write README.md for this project: what it does, how "
                         "to set it up, how to run it and how to test it.", "from": None, "idea": None, "step": None}},
                        {"kind": "run_command", "words": "Set the run command", "later": False, "fill": None,
                         "opens": "run_command"},
                        {"kind": "what_next", "words": "What next", "later": False, "fill": {"team": "plan",
                         "project": LONG_PROJECT, "chat": None, "text": "Plan what to build next.", "from": None,
                         "idea": None, "step": None}}]}
    stamp = "2026-10-28T10:42:07+00:00"
    bar = {"name": LONG_PROJECT, "path": f"{LONG_ROOT}/{LONG_PROJECT}", "handoff_lines": 212, "open_task": None, "git": True,
           "branch": "main", "head": "c0ffee1", "tests": TEST_WORDS, "files_mode": "on", "why": None,
           "last_test": {"outcome": "failed", "exit": 137, "when": stamp, "summary": "1 failed, 1,283 passed", "head": "c0ffee1"},
           "run_command": None, "run": None, "secrets": len(ENV_NAMES), "ideas": 50, "what_now": finish,
           "plan": {"task_id": card["task_id"], "n": 12345, "done": 11, "total": 12, "file": "docs/PLAN.md",
                    "next": {"k": 12, "text": STEP_399, "team": "redteam", "done_when": DONE_299}, "plan_md": None}}
    status["projects"] = [p for p in status["projects"] if p.get("name") != LONG_PROJECT] + [bar]
    projects_doc = _read("projects.json")
    projects_doc["projects"] = [p for p in projects_doc["projects"] if p.get("name") != LONG_PROJECT] + [bar]
    _write(root / "projects.json", projects_doc)
    lines = ["# Plan", "", "The router writes this file from the plan you approved and ticks each step here when it is done.",
             "", "Plan #12345 · 2026-10-20 · 11 of 12 steps done", "", "## Steps", ""]
    for step in steps:
        lines += [f"- [{'x' if step['k'] < 12 else ' '}] **Step {step['k']}.** {step['text']}", f"  - Team: {step['team']}",
                  f"  - Done when: {DONE_299}", f"  - Why: {WHY_199}"]
    (root / "plan").mkdir(exist_ok=True)
    (root / "plan" / f"{LONG_PROJECT}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _save(root, log, status, rows, shows)


def _auto34(root, log, status, shows):
    """Brief 34: the run's recap at its longest (12 steps of every team, two retried, a stop why at 399 characters, the
    marks), the switch beside the longest What now? line, the plan panel's 12 Stop here toggles with 399-character step
    texts, the confirm's words at their longest, and 40 changed files on the run; the always-visible count."""
    rows, shows, status, ids = copy.deepcopy(log["tasks"]), copy.deepcopy(shows), copy.deepcopy(status), Ids()
    stopped = next(t for t in rows if t.get("mode") == "auto" and (t.get("auto") or {}).get("state") == "stopped")
    n = 12350
    run, show = _clone(rows, shows, stopped, ids, n, root, project=LONG_PROJECT, tag=f"project:{LONG_PROJECT}",
                       text="Auto: plan #12345, steps 1 to 12")
    teams = ["route", "redteam", "research-build", "collab"]
    why = ("step 10 (#12310) failed its check twice, on its retry too: " + STEP_399)[:399]
    steps = []
    for k in range(1, 13):
        done, failed = k <= 9, k == 10
        steps.append({"k": k, "state": "done" if done else "failed" if failed else "open", "attempt": 2 if k in (4, 10) else 1 if k <= 10 else 0,
                      "team": teams[k % 4], "task_id": run["task_id"] if k <= 10 else None, "n": 12300 + k if k <= 10 else None,
                      "status": "done" if k <= 10 else None, "outcome": "passed" if done else "failed_check" if failed else None,
                      "waiting_on": None, "verdict": "passed" if done else "failed" if failed else None,
                      "calls": [2, 9, 5, 4][k % 4] + (7 if k in (4, 10) else 0), "covered": True})
    auto_view = {"plan": {"task_id": "sr-20261019-120000-0p12", "n": 12345}, "from_step": 1, "state": "stopped", "steps": steps,
                 "budget": 70, "used": 73, "estimate": {"calls": 46, "max_calls": 70, "jev_labels": 3},
                 "stop": {"code": "failed", "why": why, "step": 10}, "passed_marks": [3], "off_requested": False, "hook": False,
                 "copy": True, "next": 10, "words": f"Auto stopped: {why}"}
    changed = [{"path": f"src/northwind/{'sowing-tracker-frost-window-' * 2}{k:02d}.py", "status": "changed", "plus": 12 * k, "minus": k}
               for k in range(1, 41)]
    for doc in (run, show):
        doc["auto"] = auto_view
        doc["waiting_on"] = "auto"
        doc["status"] = "returned"
        doc["outcome"] = None
        doc["check_note"] = f"auto stopped: {why}"
        doc["project_files"] = {**(doc.get("project_files") or {}), "mode": "on", "state": "none", "copy": True, "changed": changed,
                                "diff": None, "tests": None, "commit": None}
        doc["next"] = []
    plan_steps = [{"k": k, "text": f"{k}. {STEP_399}"[:399], "team": teams[k % 4], "done": False, "stop_here": k in (3, 7, 12)}
                  for k in range(1, 13)]
    line = {"rung": "auto_stopped", "words": f"Auto stopped: {why}", "control": "open", "task_id": run["task_id"], "n": n,
            "chip": None, "need": None, "chips": None, "plan_md": None}
    stamp = "2026-10-28T10:42:07+00:00"
    bar = {"name": LONG_PROJECT, "path": f"{LONG_ROOT}/{LONG_PROJECT}", "handoff_lines": 212, "open_task": {"task_id": run["task_id"], "n": n, "status": "returned"},
           "git": True, "branch": "main", "head": "c0ffee1", "tests": TEST_WORDS, "files_mode": "on", "why": None,
           "last_test": {"outcome": "failed", "exit": 137, "when": stamp, "summary": "1 failed, 1,283 passed", "head": "c0ffee1"},
           "run_command": None, "run": None, "secrets": len(ENV_NAMES), "ideas": 50, "what_now": line,
           "plan": {"task_id": "sr-20261019-120000-0p12", "n": 12345, "done": 0, "total": 12, "file": "docs/PLAN.md",
                    "next": {"k": 10, "text": STEP_399, "team": "redteam", "done_when": DONE_299}, "plan_md": None,
                    "steps": plan_steps, "stop_here": [3, 7, 12]},
           "auto": {"state": "stopped", "switch": "off", "why": None,
                    "run": {"task_id": run["task_id"], "n": n, "state": "stopped", "words": f"Auto stopped: {why}",
                            "stop": auto_view["stop"], "used": 73, "budget": 70, "next": 10}}}
    status["projects"] = [p for p in status["projects"] if p.get("name") != LONG_PROJECT] + [bar]
    projects_doc = _read("projects.json")
    projects_doc["projects"] = [p for p in projects_doc["projects"] if p.get("name") != LONG_PROJECT] + [bar]
    _write(root / "projects.json", projects_doc)
    words = (f"Auto runs steps 10 to 12 of plan #12345, 103 calls at most, stopping before step 12 (stop here). "
             + STEP_399)[:399]
    _write(root / "auto-check" / f"{LONG_PROJECT}.json", {"api_version": 1, "task_id": None, "n": None, "status": None,
           "waiting_on": None, "outcome": None, "reason_code": None, "exit": 0, "message": words,
           "auto": {"plan": {"task_id": "sr-20261019-120000-0p12", "n": 12345}, "from_step": 10, "to_step": 12, "steps": [10, 11, 12],
                    "budget": 103, "used": 73, "estimate": {"calls": 13, "max_calls": 20, "jev_labels": 1}, "first_stop_here": 12,
                    "overrun": "A step already started finishes, so the run can pass its budget by up to one step's calls.",
                    "words": words}})
    lines = ["# Plan", "", "The router writes this file from the plan you approved and ticks each step here when it is done.",
             "", "Plan #12345 · 2026-10-20 · 0 of 12 steps done", "", "## Steps", ""]
    for step in plan_steps:
        lines += [f"- [ ] **Step {step['k']}.** {step['text']}", f"  - Team: {step['team']}", f"  - Done when: {DONE_299}", f"  - Why: {WHY_199}"]
    (root / "plan").mkdir(exist_ok=True)
    (root / "plan" / f"{LONG_PROJECT}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _save(root, log, status, rows, shows)


def _spec332(root, log, status, shows):
    """Brief 33.2: the Spec section with a 6,000-character spec and a 60-item `## Examples`; a 12-step plan card with
    `covers:` per step, the coverage line at its longest and the "SPEC.md changed" line; a revision's board with 8
    inherited steps and 4 new ones, `## Changed` at its longest; the `spec_changed` What now? line with Revise plan; a
    run stopped on a spec change with its two ways on, and the on-again confirm's line; a project with no spec (Draft
    it); a task run text only and one whose SPEC.md the router put back; Details' spec lines."""
    rows, shows, status, ids = copy.deepcopy(log["tasks"]), copy.deepcopy(shows), copy.deepcopy(status), Ids()
    teams = ["route", "redteam", "research-build", "collab"]
    # the spec at its longest: 60 examples, each a long line, then ten done-whens, under the 6,000 cap
    examples = [f"`record_sowing('Kelvedon Wonder', bed={k}, date='2026-03-{k % 28 + 1:02d}')` stores the sowing and reads it "
                f"back for bed {k}" for k in range(1, 61)]
    done_when = [f"every example of bed {k} has a passing test under {' '.join(TEST_WORDS)}" for k in range(1, 11)]
    text = ("# " + LONG_PROJECT + "\n\nA sowing log for the Northwind community garden's beds, with frost warnings.\n\n"
            "## Examples\n\n" + "\n".join(f"- {e}" for e in examples) + "\n\n## Done when\n\n"
            + "\n".join(f"{k}. {d}" for k, d in enumerate(done_when, 1)) + "\n")[:6000]
    labels = [{"label": f"E{k}", "text": e} for k, e in enumerate(examples, 1)]
    dones = [{"label": f"D{k}", "text": d} for k, d in enumerate(done_when, 1)]
    spec_doc = {"name": LONG_PROJECT, "folder": f"{LONG_ROOT}/{LONG_PROJECT}", "exists": True, "text": text,
                "hash": "9f2c4e1a7b3d5f60", "chars": len(text), "lines": len(text.splitlines()), "max": 6000, "git": True,
                "commits": True, "tracked": True, "examples": labels, "done_when": dones, "labeled": True, "draft": None,
                "commit_words": "Save makes one commit holding SPEC.md alone."}
    _write(root / "project-spec" / f"{LONG_PROJECT}.json", {"api_version": 1, "spec": spec_doc})
    _write(root / "project-notes" / f"{LONG_PROJECT}.json", {"api_version": 1, "notes": {
        "name": LONG_PROJECT, "folder": f"{LONG_ROOT}/{LONG_PROJECT}", "notes": "# Northwind\n\nThe owner's notes.",
        "block": "<!-- sr:start -->\n<!-- sr:end -->", "hash": "1a2b3c4d5e6f7a8b", "chars": 28, "lines": 3, "max": 20000,
        "git": True, "tracked": True, "exists": True, "has_block": True}})
    draft = {"kind": "draft_spec", "words": "Draft it", "later": False,
             "fill": {"team": "route", "project": "herb-labels", "chat": None, "text": "Write SPEC.md for this project: what it is "
                      "and why, what is not in it, then `## Examples` and `## Done when`, each a numbered list, one line per "
                      "item.", "from": None, "idea": None, "step": None, "no_files": True}}
    _write(root / "project-spec" / "herb-labels.json", {"api_version": 1, "spec": {
        "name": "herb-labels", "folder": "~/Projects/herb-labels", "exists": False, "text": "", "hash": "e3b0c44298fc1c14",
        "chars": 0, "lines": 0, "max": 6000, "git": True, "commits": True, "tracked": False, "examples": [], "done_when": [],
        "labeled": False, "draft": draft, "commit_words": "Save makes one commit holding SPEC.md alone."}})
    # the 12-step plan card: covers per step, the coverage line at its longest, the spec changed since
    waiting = next(t for t in rows if t.get("mode") == "plan" and t.get("waiting_on") == "land")
    covered = [f"E{k}" for k in range(1, 61) if k % 7 != 0]
    missing = [f"E{k}" for k in range(1, 61) if k % 7 == 0]
    coverage = {"covered": covered, "missing": missing,
                "words": "Covers " + ", ".join(covered) + "; not " + ", ".join(missing)}
    steps = [{"k": k, "text": f"{k}. {STEP_399}"[:399], "team": teams[k % 4], "why": WHY_199, "done_when": DONE_299,
              "covers": [{"label": f"E{j}", "text": examples[j - 1]} for j in range(k * 5 - 4, k * 5 + 1) if j % 7 != 0],
              "calls": [2, 5, 3, 4][k % 4], "max_calls": [4, 7, 5, 6][k % 4], "jev_label": teams[k % 4] == "route",
              "state": "open", "task": None} for k in range(1, 13)]
    plan_view = {"n": 12360, "steps": steps, "needs": [], "test_command": {"proposed": None, "set": " ".join(TEST_WORDS)},
                 "estimate": {"calls": 46, "max_calls": 70, "jev_labels": 3}, "edits": [], "edited": False,
                 "planner_steps": steps, "current": False, "done": 0, "total": 12, "hash": "0" * 64, "coverage": coverage,
                 "spec_hash": "9f2c4e1a7b3d5f60", "spec_changed": True, "revises": None, "inherited": 0, "changed": None}
    card, show = _clone(rows, shows, waiting, ids, 12360, root, project=LONG_PROJECT, tag=f"project:{LONG_PROJECT}",
                        text=LONG_SPLIT_TASK)
    card["plan"] = plan_view
    show["plan"] = plan_view
    # the revision's board: 8 inherited steps, 4 new, `## Changed` at its longest
    rev_steps = [{**s, "state": "done" if s["k"] <= 8 else "open", "task": {"task_id": card["task_id"], "n": 12300 + s["k"], "status": "done"} if s["k"] <= 8 else None,
                  "covers": [{"label": None, "text": examples[s["k"] - 1], "changed": True}] + s["covers"][:2] if s["k"] <= 8 else s["covers"]}
                 for s in copy.deepcopy(steps)]
    changed = [{"step": k, "why": _cut400(WHY_199 + " " + STEP_399)[:300]} for k in range(9, 13)]
    rev_view = {**plan_view, "n": 12361, "steps": rev_steps, "done": 8, "spec_changed": False, "revises": {"task_id": card["task_id"], "n": 12345},
                "inherited": 8, "changed": changed, "coverage": coverage, "estimate": {"calls": 14, "max_calls": 22, "jev_labels": 1}}
    rev, rev_show = _clone(rows, shows, waiting, ids, 12361, root, project=LONG_PROJECT, tag=f"project:{LONG_PROJECT}",
                           text="Record a reading per bed, not one for the whole plot.", idea={"id": 7, "text": "Record a reading per bed, not one for the whole plot.", "state": "sent"})
    rev["plan"] = rev_view
    rev_show["plan"] = rev_view
    # a run stopped on a spec change, with its two ways on; the on-again confirm's line
    stopped = next(t for t in rows if t.get("mode") == "auto" and (t.get("auto") or {}).get("state") == "stopped")
    why = "SPEC.md changed since the run started"
    ways = ("Land the run so far or Discard run, then Revise plan; or turn the switch on again: the remaining steps use the "
            "new SPEC.md.")
    run, run_show = _clone(rows, shows, stopped, ids, 12362, root, project=LONG_PROJECT, tag=f"project:{LONG_PROJECT}",
                           text="Auto: plan #12345, steps 1 to 12")
    for doc in (run, run_show):
        doc["auto"] = {**doc["auto"], "stop": {"code": "spec_changed", "why": why, "step": 3}, "words": f"Auto stopped: {why}",
                       "ways": ways, "spec_hash": "9f2c4e1a7b3d5f60", "state": "stopped",
                       "tests": f"Tests: `{' '.join(TEST_WORDS)}` · 40 runs across 12 steps, all passing at the end ("
                                + ", ".join(f"step {k} fixed {'twice' if k % 2 else 'once'}" for k in range(1, 13)) + ")"}
        doc["waiting_on"], doc["status"], doc["outcome"], doc["check_note"] = "auto", "returned", None, f"auto stopped: {why}"
        doc["next"] = []
    # a task run text only, one whose SPEC.md was put back, each with Details' spec lines
    routed = next(t for t in rows if t.get("mode") == "route" and t.get("project") and (t.get("project_files") or {}).get("mode") == "on")
    textonly, textonly_show = _clone(rows, shows, routed, ids, 12363, root, project=LONG_PROJECT, tag=f"project:{LONG_PROJECT}",
                                     text=draft["fill"]["text"])
    restored, restored_show = _clone(rows, shows, routed, ids, 12364, root, project=LONG_PROJECT, tag=f"project:{LONG_PROJECT}",
                                     text=LONG_TASK)
    for doc in (textonly, textonly_show):
        doc["project_files"] = {"mode": "off", "state": "none", "copy": False, "why": "text only, as asked"}
        doc["spec"] = {"hash": "9f2c4e1a7b3d5f60", "chars": len(text), "file": f"tasks/{doc['task_id']}/SPEC.md"}
    for doc in (restored, restored_show):
        doc["project_files"] = {**(doc.get("project_files") or {}), "spec_restored": True}
        doc["spec"] = {"hash": "9f2c4e1a7b3d5f60", "chars": len(text), "file": f"tasks/{doc['task_id']}/SPEC.md"}
    for call in restored_show.get("calls") or []:
        call["spec"] = ({"left_out": "grok_limit", "hash": "9f2c4e1a7b3d5f60", "chars": len(text), "from": restored["task_id"]}
                        if call.get("agent") == "grok" else {"hash": "9f2c4e1a7b3d5f60", "chars": len(text), "from": restored["task_id"]})
    # the project's bar: the spec_changed line with Revise plan; the plan panel's steps (Plan again beside them)
    chip = {"kind": "revise_plan", "words": "Revise plan", "later": False,
            "fill": {"team": "plan", "project": LONG_PROJECT, "chat": None, "text": "Revise the plan for the current SPEC.md.",
                     "from": None, "idea": None, "step": None}}
    line = {"rung": "spec_changed", "words": "SPEC.md changed since plan #12345 · Revise plan", "control": "chip",
            "task_id": card["task_id"], "n": 12345, "chip": chip, "need": None, "chips": None, "plan_md": None}
    plan_steps = [{"k": k, "text": f"{k}. {STEP_399}"[:399], "team": teams[k % 4], "done": k <= 8, "stop_here": k in (9, 12)}
                  for k in range(1, 13)]
    stamp = "2026-10-28T10:42:07+00:00"
    bar = {"name": LONG_PROJECT, "path": f"{LONG_ROOT}/{LONG_PROJECT}", "handoff_lines": 212, "open_task": None, "git": True,
           "branch": "main", "head": "c0ffee1", "tests": TEST_WORDS, "files_mode": "on", "why": None,
           "last_test": {"outcome": "passed", "exit": 0, "when": stamp, "summary": "1,283 passed", "head": "c0ffee1"},
           "run_command": None, "run": None, "secrets": len(ENV_NAMES), "ideas": 50, "what_now": line,
           "plan": {"task_id": card["task_id"], "n": 12345, "done": 8, "total": 12, "file": "docs/PLAN.md",
                    "next": {"k": 9, "text": STEP_399, "team": "redteam", "done_when": DONE_299}, "plan_md": None,
                    "steps": plan_steps, "stop_here": [9, 12]},
           "auto": {"state": "off", "run": None, "switch": "off", "why": None},
           "spec": {"present": True, "hash": "9f2c4e1a7b3d5f60", "chars": len(text), "examples": [e["label"] for e in labels],
                    "done_when": [d["label"] for d in dones]}}
    status["projects"] = [p for p in status["projects"] if p.get("name") != LONG_PROJECT] + [bar]
    projects_doc = _read("projects.json")
    projects_doc["projects"] = [p for p in projects_doc["projects"] if p.get("name") != LONG_PROJECT] + [bar]
    _write(root / "projects.json", projects_doc)
    words = f"Auto runs steps 3 to 12 of plan #12345, 70 calls at most, stopping before step 9 (stop here)."
    _write(root / "auto-check" / f"{LONG_PROJECT}.json", {"api_version": 1, "task_id": None, "n": None, "status": None,
           "waiting_on": None, "outcome": None, "reason_code": None, "exit": 0, "message": words,
           "auto": {"plan": {"task_id": card["task_id"], "n": 12345}, "from_step": 3, "to_step": 12, "steps": list(range(3, 13)),
                    "budget": 70, "used": 9, "estimate": {"calls": 36, "max_calls": 50, "jev_labels": 2}, "first_stop_here": 9,
                    "overrun": "A step already started finishes, so the run can pass its budget by up to one step's calls.",
                    "words": words, "spec_changed": True, "spec_line": "The remaining steps will use the new SPEC.md."}})
    lines = ["# Plan", "", "The router writes this file from the plan you approved and ticks each step here when it is done.",
             "", "Plan #12345 (revises #12300) · 2026-10-20 · 8 of 12 steps done", coverage["words"], "", "## Steps", ""]
    for step in steps:
        lines += [f"- [{'x' if step['k'] <= 8 else ' '}] **Step {step['k']}.** {step['text']}", f"  - Team: {step['team']}",
                  f"  - Done when: {DONE_299}", f"  - Why: {WHY_199}",
                  f"  - Covers: {', '.join(c['label'] for c in step['covers']) or 'none'}"]
    (root / "plan").mkdir(exist_ok=True)
    (root / "plan" / f"{LONG_PROJECT}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _save(root, log, status, rows, shows)


Q334_QUESTION = ("Should the frost warnings for the Northwind community garden's raised beds go out three days or five days "
                 "before the forecast date, given that the partner sites only read their mail on weekdays and the volunteers "
                 "who cover the seedlings live up to an hour away from the plots they look after each season?")[:299]
Q334_OPTION = ("Five days, and a second reminder the evening before, with the bed numbers and the volunteer's name in the "
               "subject line")[:119]
FAKE_Q334_SR = r"""
import json, sys, time
args = sys.argv[1:]
open("runs.jsonl", "a").write(json.dumps(args) + "\n")
env = {"task_id": None, "n": None, "status": None, "waiting_on": None, "outcome": None, "reason_code": None, "exit": 0,
       "message": "fake sr: " + " ".join(args[:2])}
if "--suggest" in args:
    time.sleep(6)
    env.update(added=2, summary="2 added, 1 dropped: too long")
else:
    time.sleep(1)
print(json.dumps(env))
"""


def _q334(root, log, status, shows):
    """Brief 33.4: three questions of four options at the length limits, each with the guess marked (on the 51-character project);
    the same plan planning with its answers; a text-only card offering Save as SPEC.md; one with Plan the project; Ideas
    sheets at 47 and 48 open with "Suggested by" rows and a 3-dropped line, and one with a suggest running; the New project
    sheet (a 2,000-character idea is the owner's to paste). Not a demo: the Suggest button shows and the runs go to a fake
    `sr`, which writes nothing but `runs.jsonl`."""
    rows, shows, status, ids = copy.deepcopy(log["tasks"]), copy.deepcopy(shows), copy.deepcopy(status), Ids()
    waiting = next(t for t in rows if t.get("mode") == "plan" and t.get("waiting_on") == "land")
    asked = [{"k": k, "text": Q334_QUESTION, "guess": "BCA"[k - 1],
              "options": [{"letter": x, "text": Q334_OPTION} for x in "ABCD"]} for k in (1, 2, 3)]
    questions = {"asked": asked, "answers": None, "k": 3, "waiting": True, "planning": False,
                 "command": "sr plan --answer 12350 --pick 1=<letter> --pick 2=<letter> --pick 3=<letter>",
                 "best_guess_command": "sr plan --answer 12350 --best-guess"}
    fields = dict(status="returned", waiting_on="answers", outcome=None, plan=None, result=None, project_files=None, next=[],
                  land_anyway=False, check_state="pending")
    card, card_show = _clone(rows, shows, waiting, ids, 12350, root, project=LONG_PROJECT, tag=f"project:{LONG_PROJECT}",
                             text=LONG_SPLIT_TASK, questions=questions, **fields)
    planning = {**questions, "waiting": False, "planning": True, "answers": [{"k": k, "question": Q334_QUESTION,
                "answer": Q334_OPTION, "how": "picked", "letter": "A"} for k in (1, 2, 3)]}
    _clone(rows, shows, waiting, ids, 12351, root, project="herb-labels", tag="project:herb-labels", text="Plan the labels.",
           questions=planning, **{**fields, "status": "queued", "waiting_on": None})
    done = next(t for t in rows if t.get("status") == "done" and t.get("mode") == "route" and t.get("result") and t.get("project"))
    draft = ("Write SPEC.md for this project: what it is and why, what is not in it, then `## Examples` and `## Done when`, each a "
             "numbered list, one line per item.")
    read_only = {"mode": "on", "state": "none", "read_only": True, "copy": False, "changed": [], "files": 1, "base": "c" * 40,
                 "branch": "main", "left_out": [], "tests": None, "why": "read only, answers in text"}
    _clone(rows, shows, done, ids, 12352, root, project="pea-trial", tag="project:pea-trial", text=draft, text_only=True, parent=None, plan_step=None,
           save_spec={"path": "SPEC.md"}, project_files=read_only, next=[])
    plan_project = {"kind": "plan_project", "words": "Plan the project", "later": False, "fill": {"team": "plan", "project": "plot-planner",
                    "chat": None, "text": "Plan this project from SPEC.md.", "from": None, "idea": None, "step": None}}
    _clone(rows, shows, done, ids, 12353, root, project="plot-planner", tag="project:plot-planner", text=draft, text_only=True, save_spec=None, parent=None, plan_step=None,
           project_files=read_only, next=[plan_project])

    def sheet(project, k, **suggest):
        listed = [{"id": i, "text": f"{i}. {STEP_399}"[:399], "state": "open", "created_at": "2026-10-20T10:00:00+00:00", "sent_as": None,
                   "source": ({"kind": "later", "task_id": card["task_id"], "n": 12350, "suggested": True} if i % 2
                              else {"kind": "added", "task_id": None, "n": None, "suggested": False})} for i in range(k, 0, -1)]
        _write(root / "ideas" / f"{project}.json", {"task_id": None, "n": None, "status": None, "waiting_on": None, "outcome": None,
               "reason_code": None, "exit": 0, "message": "", "ideas": listed, "dismissed": 12, "used": [],
               "suggest": {"running": None, "open": k, "off": None, "last": None, **suggest}})
    sheet(LONG_PROJECT, 47, last={"task_id": card["task_id"], "n": 12350, "status": "done",
                                  "line": "0 added, 3 dropped: too long, starts with @ or /, looks like a key"})
    sheet("pea-trial", 48, off="48 open ideas: dismiss some to get suggestions")
    sheet("seed-swap", 3, running={"task_id": card["task_id"], "n": 12350})
    sheet("herb-labels", 0, last={"task_id": card["task_id"], "n": 12350, "status": "failed", "line": "no idea in the shape"})
    bar = {"name": LONG_PROJECT, "path": f"{LONG_ROOT}/{LONG_PROJECT}", "handoff_lines": 212, "open_task": {"task_id": card["task_id"], "n": 12350, "status": "returned"},
           "git": True, "branch": "main", "head": "c0ffee1", "tests": TEST_WORDS, "files_mode": "on", "why": None, "last_test": None,
           "run_command": None, "run": None, "secrets": 0, "ideas": 47, "plan": None, "auto": None,
           "what_now": {"rung": 1, "words": "Waiting on you: #12350 · answer 3 questions", "control": "open", "task_id": card["task_id"],
                        "n": 12350, "chip": None, "need": None, "chips": None, "plan_md": None}}
    status["projects"] = [p for p in status["projects"] if p.get("name") != LONG_PROJECT] + [bar]
    for agent in status["agents"]:
        if agent["name"] == "claude":
            agent["available"] = True
    projects_doc = _read("projects.json")
    projects_doc["projects"] = [p for p in projects_doc["projects"] if p.get("name") != LONG_PROJECT] + [bar]
    _write(root / "projects.json", projects_doc)
    _save(root, log, status, rows, shows)


def _uia(root, log, status, shows):
    """UI A: a running Route card, which `demo/` has no sample of: a passed Route row, cloned as queued, 1 min 20 s before
    the demo's clock. It serves as a demo, so its clock holds still and it reads "#76 · Route · Claude building · 1m 20s"."""
    rows, shows, status = copy.deepcopy(log["tasks"]), copy.deepcopy(shows), copy.deepcopy(status)
    clock = max([t["updated_at"] for t in rows if t.get("updated_at")] + [a["checked_at"] for a in status["agents"] if a.get("checked_at")])
    started = (datetime.fromisoformat(clock) - timedelta(seconds=80)).isoformat()
    base = next(t for t in rows if t.get("mode") == "route" and t.get("outcome") == "passed" and not t.get("project") and t.get("chat"))
    row, show = _clone(rows, shows, base, Ids(), max(t["n"] for t in rows) + 1, root, status="queued", outcome=None, check_state="pending",
                       working={"agent": "claude", "doing": None}, result=None, next=[], notes=[], created_at=started, updated_at=started,
                       text="Write a two-line sign for the seed library's door.")
    show["calls"] = [c for c in show.get("calls") or [] if c.get("kind") == "do"][:1]
    for call in show["calls"]:
        call.update(status="sent", finished_at=None)
    _save(root, log, status, rows, shows)


def _all_up(status):
    """Every agent up, Jev set up at 32k of 1M, Memory online: the bar as the cleanup brief's section 2 draws it."""
    status = copy.deepcopy(status)
    for agent in status["agents"]:
        agent.update(available=True, why=None, why_code=None, online=True, reason=None, configured=True)
    status["jev"].update(configured=True, available=True, why=None, tokens_month=32000, cap=1000000, over_cap=False)
    status["memory"].update(online=True, starting=False, documents=16)
    for preset in status["presets"]:
        preset.update(ready=True, why=None)
        for slot in preset["slots"]:  # with every agent up, each slot offers its own default too, so no option reads greyed
            slot["allowed"] = list(dict.fromkeys([slot["default"], "claude", "chatgpt"]))
    for key in ("split", "plan"):
        status[key].update(ready=True, why=None)
    return status


def _bar_wrong(root, status):
    """The small UI cleanup: the bar of the brief's section 3, ChatGPT signed out, Grok Bot not set up, Memory starting, with Claude's
    "check didn't answer" for amber and Cursor up."""
    status = _all_up(status)
    for agent in status["agents"]:
        if agent["name"] == "claude":
            agent.update(online=False, why="Claude's sign-in check didn't answer; it is tried anyway", why_code=None)
        elif agent["name"] == "chatgpt":
            agent.update(online=False, available=False, why="ChatGPT is signed out (codex login)", why_code="signed_out",
                         reason="not signed in with ChatGPT (codex login)")
        elif agent["name"] == "grok":
            agent.update(configured=False, online=None, available=False, why_code="not_configured", reason="not configured",
                         why="Grok Bot isn't set up: no GROK_WEBHOOK_URL or GROK_WEBHOOK_KEY in .env; no inbox repo in settings")
    status["memory"].update(online=False, starting=True, documents=None)
    _write(root / "status.json", status)


def _pills(root, log, status, shows):
    """The small UI cleanup: invented cards for every state of a step pill on every team, with every agent up. Each `steps` is what
    `task_view` gives such a row; every card is a clone of a demo card, so nothing here is real."""
    rows, shows, status, ids = copy.deepcopy(log["tasks"]), copy.deepcopy(shows), _all_up(status), Ids()
    routed = _base(rows, lambda t: t["mode"] == "route" and t.get("outcome") == "passed" and not t.get("project"))
    redteam = _base(rows, lambda t: t.get("preset") == "redteam" and t["mode"] == "relay" and t.get("outcome") == "passed")
    landing = _base(rows, lambda t: t["mode"] == "route" and t.get("waiting_on") == "land")
    plan_row = _base(rows, lambda t: t["mode"] == "plan" and t.get("waiting_on") == "land")
    one = shows[routed["task_id"]]["calls"][0]
    n = max(t["n"] for t in rows)
    claude, chatgpt, cursor, grok = "claude", "chatgpt", "cursor", "grok"
    red_chain = [(1, "build", claude), (2, "attack", chatgpt), (3, "attack", cursor), (4, "revise", claude), (None, "check", chatgpt)]
    red_calls = [("stage", 1, "build", claude), ("stage", 2, "attack", chatgpt), ("stage", 3, "attack", cursor)]
    both = {"build": claude, "attack": chatgpt, "attack2": cursor, "check": chatgpt}

    def steps(chain=None, now=None):
        return {"chain": [{"stage": s, "role": r, "agent": a} for s, r, a in chain] if chain else None,
                "now": dict(zip(("kind", "stage", "role", "agent"), now)) if now else None}

    def card(base, text, calls, chain=None, now=None, **changes):
        nonlocal n
        n += 1
        open_task = changes.get("status") in ("queued", "sent")
        fields = dict(text=text, steps=steps(chain, now), next=[], notes=[], working=None, card_line=None, takeover=None, late=None,
                      parent=None, piece_of=None, plan_step=None,
                      **({"project": None, "tag": None, "project_files": None, "chat": None} if base is redteam else {}),
                      **({"outcome": None, "check_state": "pending", "result": None, "waiting_on": None} if open_task else {}))
        fields.update(changes)
        row, show = _clone(rows, shows, base, ids, n, root, **fields)
        show["calls"] = [_call(one, row["task_id"], k, *c) for k, c in enumerate(calls, 1)]
        for key in ("attacks", "attack_lists", "candidates", "votes", "tally", "pieces"):
            if show.get(key):
                show[key] = None
        return row, show

    def team(base, preset, text, chain, calls, **changes):
        return card(base, text, calls, chain, preset=preset, mode="relay", **changes)

    # every state, on a routed card
    card(routed, "Pills: a Route card, building.", [], now=("do", None, None, claude), status="queued", working={"agent": claude, "doing": None})
    card(routed, "Pills: a Route card, its check running.", [("do", None, None, claude)], now=("check", None, None, chatgpt), status="queued")
    card(routed, "Pills: a Route card, its fix running.", [("do", None, None, claude), ("check", None, None, chatgpt, "done", None, "FIX")],
         now=("fix", None, None, claude), status="queued")
    card(routed, "Pills: a failed call.", [("do", None, None, claude, "failed", "internal_error")], status="failed", outcome="stopped", check_state="pending", result=None)
    card(routed, "Pills: stopped on a plan limit.", [("do", None, None, claude, "failed", "plan_limit")], status="failed", outcome="plan_limit", result=None)
    card(routed, "Pills: stopped, the process ended.", [("do", None, None, claude, "failed", "process_ended")], status="failed", outcome="process_ended", result=None)
    card(routed, "Pills: a check that found problems, twice.",
         [("do", None, None, claude), ("check", None, None, chatgpt, "done", None, "FIX"), ("fix", None, None, claude), ("recheck", None, None, chatgpt, "done", None, "FIX")],
         outcome="failed_check", check_state="failed")
    card(routed, "Pills: a blocked check.", [("do", None, None, claude), ("check", None, None, chatgpt, "done", None, "BLOCKED")], status="failed", outcome="blocked", check_state="blocked")
    card(routed, "Pills: an unreadable check.", [("do", None, None, claude), ("check", None, None, claude, "done", None, "unreadable")], outcome="unchecked", check_state="unchecked")
    card(routed, "Pills: a timed-out Grok call.", [("do", None, None, grok, "timed_out")], status="timed_out", outcome="timed_out", agent=grok, result=None)
    card(routed, "Pills: a quick answer.", [("do", None, None, claude)], skill="quick_answer", checker=None, outcome="unchecked", check_state="not_needed")
    card(routed, "Pills: cancelled before its check.", [("do", None, None, claude)], status="cancelled", outcome="cancelled", result=None)
    # every team
    team(redteam, "redteam", "Pills: a running Redteam.", red_chain, red_calls, now=("stage", 4, "revise", claude), slots=both, status="queued")
    team(redteam, "redteam", "Pills: a five-step Redteam, done.", red_chain, [*red_calls, ("stage", 4, "revise", claude), ("check", None, None, chatgpt)], slots=both)
    team(redteam, "redteam", "Pills: a skipped second attack.", red_chain,
         [("stage", 1, "build", claude), ("stage", 2, "attack", chatgpt), ("stage", 3, "attack2", cursor, "failed", "skipped"), ("stage", 4, "revise", claude), ("check", None, None, chatgpt)], slots=both)
    team(redteam, "research-build", "Pills: a Research-build, researching.", [(1, "research", grok), (2, "build", claude), (None, "check", chatgpt)],
         [("stage", 1, "research", grok, "sent")], slots=None, status="sent", waiting_on="grok", outcome=None, result=None, check_state="pending")
    collab = [(1, "plan", claude), (2, "amend", chatgpt), (3, "execute", claude), (4, "edit", chatgpt)]
    team(redteam, "collab", "Pills: Collab, off a project.", collab, [("stage", s, r, a) for s, r, a in collab], slots=None, checker=None, check_state="passed")
    on_project = [*collab[:3], (None, "check", chatgpt)]
    team(redteam, "collab", "Pills: Collab, on a project.", on_project, [*[("stage", s, r, a) for s, r, a in collab[:3]], ("check", None, None, chatgpt)],
         slots=None, project="seed-swap", tag="project:seed-swap")
    versus = [(1, "build", claude), (2, "build", chatgpt), (3, "review", chatgpt), (4, "review", claude)]
    team(redteam, "versus", "Pills: Versus, one review to go.", versus, [("stage", s, r, a) for s, r, a in versus[:3]], now=("stage", 4, "review", claude), slots=None, checker=None, status="queued")
    vote = [(1, "vote", claude), (2, "vote", chatgpt), (3, "vote", grok)]
    team(redteam, "vote", "Pills: Vote, the last answer out.", vote, [("stage", 1, "vote", claude), ("stage", 2, "vote", chatgpt), ("stage", 3, "vote", grok, "sent")],
         slots=None, checker=None, status="sent", waiting_on="grok", outcome=None, result=None, check_state="pending")
    card(redteam, "Pills: a Split, its join running.", [("stage", 1, "split_plan", claude)], [(1, "split_plan", claude), (2, "integrate", claude), (None, "check", chatgpt)],
         now=("stage", 2, "integrate", claude), mode="split", preset=None, slots=None, status="queued")
    # the fixes: note 14 and note 8
    card(landing, "Pills: ready to land.", [("do", None, None, claude), ("check", None, None, chatgpt)])
    for state, line in (("undone", "Pills: passed, then undone."), ("discarded", "Pills: passed, then discarded.")):
        card(landing, line, [("do", None, None, claude), ("check", None, None, chatgpt)], status="done", waiting_on=None, outcome="passed",
             project_files={**landing["project_files"], "state": state, "commit": "a" * 40, "undo_commit": "b" * 40, "copy": False})
    # note 5: a plan waiting on its answers, with a real record that keeps its copy (q334's card has none, so it can't show this)
    asked = [{"k": 1, "text": "Which till comes first?", "guess": "A", "options": [{"letter": "A", "text": "The front till."}, {"letter": "B", "text": "The back till."}]}]
    kept = {**plan_row["project_files"], "state": "none", "copy": True, "changed": [], "diff": None, "tests": None}
    card(plan_row, "Pills: a plan waiting on its answers.", [("questions", 1, "plan", claude)], [(1, "plan", claude), (2, "attack", chatgpt), (3, "attack", cursor), (4, "revise", claude), (None, "check", chatgpt)],
         status="returned", waiting_on="answers", outcome=None, plan=None, result=None, land_anyway=False, check_state="pending", project_files=kept,
         questions={"asked": asked, "answers": None, "k": 1, "waiting": True, "planning": False, "command": "sr plan --answer 1 --pick 1=<letter>",
                    "best_guess_command": "sr plan --answer 1 --best-guess"})
    _save(root, log, status, rows, shows)


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
            doc["what_now"] = self._what_now(wanted["--project"])  # brief 33: as the demo reader gives it
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


# Brief 28: the projectfiles scenario's fake `sr`. land, undo and discard move the task's state in files.json; project
# tests stores the words in tests.json; project git turns git on in git.json; project files refuses a name holding
# `dup` (already in the folder). A file in the scenario folder changes it: `refuse` (every run refused, exit 2), `hang`
# (the run never ends), `slow-status` (each status read takes 3 s).
FAKE_FILES_SR = r"""
import json, os, sys, time
args = sys.argv[1:]
open("runs.jsonl", "a").write(json.dumps(args) + "\n")
env = {"task_id": None, "n": None, "status": None, "waiting_on": None, "outcome": None, "reason_code": None, "exit": 0,
       "message": "fake sr: " + " ".join(args[:2])}
def load(name):
    try:
        return json.load(open(name))
    except (OSError, ValueError):
        return {}
time.sleep(1)
if os.path.exists("hang"):
    time.sleep(3600)
if os.path.exists("refuse"):
    env.update(reason_code="land_refused", exit=2, message="Refused: these files have uncommitted edits in the folder: "
               "src/components/northwind-industries-holdings/quarterly-board-review/AleksandraWisniewskaKowalczyk"
               "ApprovalFlow.integration.test.tsx. Nothing was changed.")
elif args[0] in ("land", "undo", "discard"):
    files = load("files.json")
    task = args[-1]
    env["task_id"] = task
    files[task] = {"land": "landed", "undo": "undone", "discard": "discarded"}[args[0]]
    json.dump(files, open("files.json", "w"))
    env["commit"] = "c0ffee1234567890abcdef1234567890abcdef12"
    env["message"] = f"fake sr: {args[0]} {task}"
elif args[:2] == ["project", "tests"]:
    tests = load("tests.json")
    tests[args[-1] if "--clear" in args else args[3]] = None if "--clear" in args else args[args.index("--") + 1].split()
    json.dump(tests, open("tests.json", "w"))
elif args[:2] == ["project", "git"]:
    git = load("git.json")
    git[args[-1]] = True
    json.dump(git, open("git.json", "w"))
elif args[:2] == ["project", "files"]:
    names = [os.path.basename(a) for i, a in enumerate(args) if i and args[i - 1] == "--file"]
    clash = next((n for n in names if "dup" in n), None)
    if clash:
        env.update(reason_code="project_refused", exit=2,
                   message=f"Refused: {clash} is already in the folder; a file is never overwritten. Nothing was changed.")
    else:
        env["message"] = "Added to garden-site: " + ", ".join(names) + ", and HANDOFF.md, one commit c0ffee1 on main."
print(json.dumps(env), file=sys.stdout if env["exit"] == 0 else sys.stderr)
sys.exit(env["exit"])
"""


# Brief 29: the split scenario's fake `sr`. `split --edit` keeps a piece's new text or team in plan.json (a text starting
# with @ or / is refused as the router refuses it); `split --go --answer y|n` keeps the answer in go.json; `split --skip`
# keeps the piece in skip.json; `route` (Route it) keeps the task in routed.json. The same `refuse`, `hang` and
# `slow-status` files as projectfiles.
FAKE_SPLIT_SR = r"""
import json, os, sys, time
args = sys.argv[1:]
open("runs.jsonl", "a").write(json.dumps(args) + "\n")
env = {"task_id": None, "n": None, "status": None, "waiting_on": None, "outcome": None, "reason_code": None, "exit": 0,
       "message": "fake sr: " + " ".join(args[:2])}
def load(name):
    try:
        return json.load(open(name))
    except (OSError, ValueError):
        return {}
def save(name, doc):
    json.dump(doc, open(name, "w"))
text = args[args.index("--") + 1] if "--" in args else None
time.sleep(1.5)
if os.path.exists("hang"):
    time.sleep(3600)
if os.path.exists("refuse"):
    env.update(reason_code="bad_preset", exit=2, message="Refused: " + LONG_REFUSAL + ". Nothing was logged or sent.")
elif args[:1] == ["split"] and "--edit" in args:
    task, piece = args[args.index("--edit") + 1], args[args.index("--piece") + 1]
    env["task_id"] = task
    if text is not None and (text.startswith("@") or text.startswith("/")):
        env.update(reason_code="bad_task", exit=2, message="Refused: the new text starts with @ or /; a piece takes no "
                   "override prefix and can't start with /. Nothing was logged or sent.")
    else:
        plan = load("plan.json")
        change = plan.setdefault(task, {}).setdefault(piece, {})
        if text is not None:
            change["text"] = text
        if "--team" in args:
            change["team"] = args[args.index("--team") + 1]
        save("plan.json", plan)
        env["message"] = f"Piece {piece} changed."
elif args[:1] == ["split"] and "--go" in args:
    task = args[args.index("--go") + 1]
    go = load("go.json")
    go[task] = args[args.index("--answer") + 1]
    save("go.json", go)
    env.update(task_id=task, message="fake sr: approved" if go[task] == "y" else "fake sr: rejected")
elif args[:1] == ["split"] and "--skip" in args:
    skip = load("skip.json")
    skip[args[args.index("--skip") + 1]] = True
    save("skip.json", skip)
elif args[:1] == ["route"]:
    routed = load("routed.json")
    task = "sr-20261020-235900-%04x" % (0xd000 + len(routed))
    routed[task] = {"text": text, "project": args[args.index("--project") + 1] if "--project" in args else None,
                    "chat": args[args.index("--chat") + 1] if "--chat" in args else None}
    save("routed.json", routed)
    env.update(task_id=task, n=900 + len(routed), status="queued", message="fake sr: routed")
print(json.dumps(env), file=sys.stdout if env["exit"] == 0 else sys.stderr)
sys.exit(env["exit"])
""".replace("LONG_REFUSAL", repr(LONG_REFUSAL))


class SplitReader(PagingReader):
    """Brief 29: the split scenario's reads: the documents with what the fake `sr` kept laid over them (a piece's text and
    team, an approval, a skip, a routed task); never kept."""

    def _over(self, name):
        try:
            return json.loads((self.root / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _task(self, task):
        answer = self._over("go.json").get(task.get("task_id"))
        if answer and task.get("waiting_on") == "split_plan":
            task.update(waiting_on="piece" if answer == "y" else None, status="returned" if answer == "y" else "failed",
                        outcome=None if answer == "y" else "rejected")
        for piece in task.get("pieces") or []:
            change = self._over("plan.json").get(task["task_id"], {}).get(str(piece["piece"]), {})
            if change.get("text"):
                piece.update(text=change["text"], edited=True, jev={"status": "ok", "label": "writing", "confidence": 0.91})
            if change.get("team"):
                piece.update(team=change["team"], team_source="owner", needs_you={"versus": "pick", "vote": "tie"}.get(
                    change["team"]), refused=None, chain=None if change["team"] == "route" else piece.get("chain"))
            if self._over("skip.json").get(piece["task_id"]):
                piece.update(piece_state="skipped", why="you skipped it")
        return task

    def status(self, fresh=False):
        import time
        if (self.root / "slow-status").exists():
            time.sleep(3)
        return super().status(fresh)

    def log(self, flags=()):
        code, body = super().log(flags)
        if code != 200:
            return code, body
        doc = json.loads(body)
        routed = [{**doc["tasks"][-1], "task_id": task, "n": 900 + k, "text": found["text"], "project": found["project"],
                   "chat": found["chat"], "mode": "route", "preset": None, "status": "queued", "waiting_on": None,
                   "outcome": None, "result": None, "no_split": None, "parent": None, "piece_of": None,
                   "created_at": "2026-10-20T23:59:00+00:00", "updated_at": "2026-10-20T23:59:00+00:00"}
                  for k, (task, found) in enumerate(self._over("routed.json").items(), 1)]
        doc["tasks"] = routed[::-1] + [self._task(t) for t in doc["tasks"]]
        return 200, json.dumps(doc).encode()

    def show(self, task_id):
        code, body = super().show(task_id)
        if code != 200:
            return code, body
        return 200, json.dumps(self._task(json.loads(body))).encode()

    def forget_status(self):
        pass


class ProjectFilesReader(PagingReader):
    """Brief 28: the projectfiles scenario's reads: the demo's documents with what the fake `sr` changed laid over them
    (a task's state, a project's test words and its git); never kept."""

    def _over(self, name):
        try:
            return json.loads((self.root / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _task(self, task):
        state = self._over("files.json").get(task.get("task_id"))
        if state and task.get("project_files"):
            task["project_files"] = dict(task["project_files"], state=state, commit="c0ffee1234567890abcdef12",
                                         copy=state == "landed" and False)
            if state != "waiting" and task.get("waiting_on") == "land":
                task["waiting_on"], task["outcome"] = None, "passed"
        return task

    def status(self, fresh=False):
        import time
        if (self.root / "slow-status").exists():
            time.sleep(3)
        code, body = self._file("status.json")
        if code != 200:
            return code, body
        doc = json.loads(body)
        tests, git = self._over("tests.json"), self._over("git.json")
        for project in doc.get("projects") or []:
            if project["name"] in tests:
                project["tests"] = tests[project["name"]]
            if git.get(project["name"]):
                project.update(git=True, branch="main", head="c0ffee1", files_mode="on", why=None)
        doc["open_tasks"] = [t for t in (self._task(t) for t in doc.get("open_tasks") or []) if t.get("waiting_on") or not t.get("outcome")]
        return 200, json.dumps(doc).encode()

    def log(self, flags=()):
        code, body = super().log(flags)
        if code != 200:
            return code, body
        doc = json.loads(body)
        doc["tasks"] = [self._task(t) for t in doc["tasks"]]
        return 200, json.dumps(doc).encode()

    def show(self, task_id):
        code, body = super().show(task_id)
        if code != 200:
            return code, body
        return 200, json.dumps(self._task(json.loads(body))).encode()

    def project_git_check(self, name):
        return self._file(f"git-check/{name}.json")

    def forget_status(self):
        pass


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
        if name == "q334":  # brief 33.4: not a demo, so the questions card and Suggest ideas run; the fake sr writes nothing else
            from router import page_runs
            runs = page_runs.Runs(root=root, prefix=[sys.executable, "-c", FAKE_Q334_SR])
            srv = page.make_server(base + i, reader=PagingReader(root), runs=runs, root=root, demo_root=root,
                                   platform="linux")
        elif name == "projects31":  # brief 31: not a demo, so Test, Run, Stop and Secrets run; the fake sr runs, nothing real
            from router import page_runs
            runs = page_runs.Runs(root=root, prefix=[sys.executable, "-c", FAKE_PROJECTS_SR])
            srv = page.make_server(base + i, reader=PagingReader(root), runs=runs, root=root, demo_root=root,
                                   platform="linux")
        elif name == "notes30":  # brief 30: not a demo, so the editors' Save, Pin, Save to project and Forget run
            from router import page_runs
            runs = page_runs.Runs(root=root, prefix=[sys.executable, "-c", FAKE_NOTES_SR])
            srv = page.make_server(base + i, reader=PagingReader(root), runs=runs, root=root, demo_root=root,
                                   platform="linux")
        elif name == "split":  # brief 29: not a demo, so Edit, the team select, Approve, Skip and Route it run
            from router import page_runs
            runs = page_runs.Runs(root=root, prefix=[sys.executable, "-c", FAKE_SPLIT_SR])
            srv = page.make_server(base + i, reader=SplitReader(root), runs=runs, root=root, demo_root=root,
                                   platform="linux")
        elif name == "projectfiles":  # brief 28: not a demo, so Land, Undo, Discard and the sheets run; the fake sr runs
            from router import page_runs
            runs = page_runs.Runs(root=root, prefix=[sys.executable, "-c", FAKE_FILES_SR])
            srv = page.make_server(base + i, reader=ProjectFilesReader(root), runs=runs, root=root, demo_root=root,
                                   platform="linux")
        elif name == "memoryswitch":  # brief 27: not a demo, so the switch runs; the fake sr runs, nothing real does
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


# ---------- brief 33.3 (decisions 6, 7, 11 and 12): models at their worst ----------

LONG_MODEL = "claude-fable-5-1-preview-2026-10-30-extended-context-reasoning-tier-max-allowance"  # 80: MODEL_NAME's limit
LONG_MODEL_NAME = "Fable 5.1 Preview (extended context, reasoning tier max, 30 October 2026 allowance)"
LONG_GPT = "gpt-6.1-terra-preview-2026-10-30-long-context-reasoning-max-allowance-build-7"
LONG_GROK = "grok-4.7-high-reasoning-preview-2026-10-30-cursor-pinned-build-7-extended-window"


def _models333(root, log, status, shows):
    """The Models sheet with long ids and names on every allowlist (twelve on Claude's), Fable off with the router's own
    off_by, a long ignored-default problem, huge week counts, Setup's row with every select (twelve skills, the whole
    role matrix) and Details with five calls of long ids, long served ids, limits and efforts; a card line with the
    served-differs note at its longest."""
    rows, shows, status, ids = copy.deepcopy(log["tasks"]), copy.deepcopy(shows), copy.deepcopy(status), Ids()
    models = status["models"]
    claude = models["agents"]["claude"]
    extra = [f"{LONG_MODEL[:-1]}{k}" for k in range(8)]
    claude["allowed"] = claude["allowed"] + extra
    claude["names"] = {**claude["names"], **{m: f"{LONG_MODEL_NAME} {k}" for k, m in enumerate(extra)}}
    claude["gated"] = claude["gated"] + extra[:3]
    claude["timeouts"] = {**claude["timeouts"], **{m: 1200 for m in extra}}
    gpt = models["agents"]["chatgpt"]
    gpt["allowed"] = gpt["allowed"] + [LONG_GPT]
    gpt["names"] = {**gpt["names"], LONG_GPT: "GPT-6.1 Terra Preview (long context, reasoning max, 30 October 2026 allowance, build 7)"}
    cursor = models["agents"]["cursor"]
    cursor["allowed"] = cursor["allowed"] + [LONG_GROK]
    models["fable"] = {**models["fable"], "on": False, "changed_at": "2026-10-30T03:14:15+00:00",
                       "off_by": "credits: sr-20261030-031415-c0de (its do call was billed to usage credits)"}
    models["problems"] = [f"config/models.local.json: skills.code.claude: {LONG_MODEL}-9 isn't on claude's allowed list "
                          f"({', '.join(claude['allowed'][:4])}, …); that default is ignored until you fix or clear it",
                          "config/models.local.json: roles.file.build.claude: effort \"ultra\" isn't one of claude's levels "
                          "(low, medium, high, xhigh, max); that default is ignored"]
    models["claude"] = {"opus_calls_this_week": 12345, "fable_calls_this_week": 9876}
    models["layers"] = models["layers"] + [{"layer": "stage", "key": "redteam.2", "agent": "chatgpt", "model": LONG_GPT,
                                            "name": gpt["names"][LONG_GPT], "effort": "ultra", "file": "config/models.local.json"}]
    for item in models["now"]["teams"].get("redteam", []):
        if item["agent"] == "chatgpt" and item["role"] == "attack":
            item.update({"model": LONG_GPT, "name": gpt["names"][LONG_GPT], "layer": "stage", "key": "redteam.2", "effort": "ultra"})
    for item in models["now"]["teams"].get("plan", []):
        if item["agent"] == "claude":
            item["note"] = "Fable is off: Opus 5.5 instead (the router turned it off: credits: sr-20261030-031415-c0de)"
    models["setup"]["roles"] = models["setup"]["roles"] + [{"team": "redteam", "role": "attack", "agent": "chatgpt",
                                                            "model": LONG_GPT, "effort": "ultra", "name": gpt["names"][LONG_GPT]}]
    for row in models["setup"]["skills"]:
        if row["key"] == "code":
            row.update({"model": f"{LONG_MODEL}-9", "name": None})  # the ignored one: not on the list, still shown
    # a card with five calls, long ids throughout, and the served-differs note at its longest
    base = _base(rows, lambda t: t.get("outcome") == "fixed" and t.get("mode") == "route")
    card, show = _clone(rows, shows, base, ids, 33333, root, text="Write the garden's frost notice, on the long Fable preview.")
    long_choice = {"claude": {"model": extra[0], "effort": "max"}, "chatgpt": {"model": LONG_GPT, "effort": "ultra"}}
    served = lambda asked, answered: {"asked": asked, "model": answered, "source": "stream: init and modelUsage",  # noqa: E731
                                      "credits": {"seen": False}, "differs": asked != answered, "layer": "task", "key": "the task",
                                      "file": "the task", "note": None, "effort": "max", "time_limit": 1200}
    calls = show.get("calls") or []
    kinds = [("do", "claude", extra[0], "claude-opus-5-5", 1200, "max"), ("check", "chatgpt", LONG_GPT, LONG_GPT, 600, "ultra"),
             ("fix", "claude", extra[0], "claude-opus-5-5", 1200, "max"), ("recheck", "chatgpt", LONG_GPT, None, 600, "ultra"),
             ("fix", "claude", extra[1], extra[1], 1200, None)]
    while len(calls) < 5:
        calls.append(copy.deepcopy(calls[-1]))
    for call, (kind, agent, asked, answered, limit, effort) in zip(calls, kinds):
        call.update({"kind": kind, "agent": agent, "model": asked, "time_limit": limit, "effort": effort,
                     "served": served(asked, answered) if answered else None, "role": None, "stage": None})
    show["calls"] = calls
    line = f"{LONG_MODEL_NAME} 0 re-ran this on Opus 5.5 · {LONG_MODEL_NAME} 1 re-ran this on {extra[1]}"
    for doc in (card, show):
        doc["models"] = long_choice
        doc["card_line"] = line
    _save(root, log, status, rows, shows)


if __name__ == "__main__":
    target = build(sys.argv[1])
    print(f"scenarios written to {target}")
    if "--serve" in sys.argv[2:]:
        args = sys.argv[2:]
        serve(target, int(args[args.index("--base") + 1]) if "--base" in args else 8800)
