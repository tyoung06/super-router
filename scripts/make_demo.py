"""The demo's invented sample (build brief 23, decision 15), made by the router's own code. It builds a scratch log in a
temp folder by running the real commands (route, relay, split, pick, cancel) with fake agents, a fake Jev, a fake
webhook and a fake memory store, on a fixed clock with fixed task ids, then writes what the real serializers print
(`router/status.py`, `router/jsonview.py`) into demo/, beside the round files and media the run left. `sr serve --demo`
serves demo/ and runs nothing. A test regenerates it and fails on any drift (tests/test_demo.py).

Everything here is invented: the tasks, the answers, the names. No real log, key, name, path or task is read, and no
command, model, webhook or network is reached (the script blocks them). Run: `python scripts/make_demo.py`."""
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests.adapters  # noqa: E402

from router import __main__ as cli  # noqa: E402
from router import (availability, claude_worker, ids, inbox, jsonview, log, media, presets, projects, receipt,  # noqa: E402
                    relay, rounds, runs, settings, status)
from tests.fake_hindsight import FakeHindsight  # noqa: E402

OUT = ROOT / "demo"
START = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)
CONFIG = {"GROK_WEBHOOK_URL": "https://example.invalid/hook", "GROK_WEBHOOK_KEY": "FAKE-WEBHOOK-KEY-00"}
STATUS_ENV = {}  # the demo's status: Grok Bot has no webhook set ("not configured"); Jev has no key ("not set up")
NO_GROK = {"grok": ("Grok Bot isn't set up: no inbox repo in settings", "not_configured")}
PLAN_LIMIT = claude_worker.WorkerError("plan limit on claude: You've hit your session limit · resets 3pm", code="plan_limit")


# ---------- fakes ----------

class Scripted:
    """A fake agent: each call returns the next reply (or raises it)."""

    def __init__(self, *replies):
        self.replies = list(replies)

    def __call__(self, prompt, **kwargs):
        reply = self.replies.pop(0) if self.replies else "An answer."
        if isinstance(reply, BaseException):
            raise reply
        return reply


class Hook:
    """A fake webhook and inbox: each send is answered by the body named for its call id's last part (do, c1, s3)."""

    def __init__(self, **bodies):
        self.bodies, self.sent = bodies, []

    @staticmethod
    def _key(call_id):
        return call_id.split("-")[-1] if call_id.count("-") >= 4 else "do"

    def post(self, url, headers=None, json=None, timeout=None):
        self.sent.append(json)
        return _Reply()

    def fetch(self):
        found = []
        for n, p in enumerate(self.sent, 1):
            body = self.bodies.get(self._key(p["task_id"]))
            if body is not None:
                found.append({"number": n, "title": p["task_id"], "body": body(p["task_id"]) if callable(body) else body,
                              "url": f"https://github.com/example/inbox/issues/{n}"})
        return found

    def close(self, number):
        pass


class _Reply:
    status_code = 200

    def json(self):
        return {"success": True, "runUuid": "demo-run"}


class Gate:
    """A command's availability for a demo task (brief 24): every agent is available but the ones named, each with the
    router's words and code (router/availability.py), invented."""

    def __init__(self, **out):
        self.out = out

    def of(self, names, fresh=False):
        return {n: availability.Availability(False, *self.out[n]) if n in self.out else availability.YES for n in names if n}

    def __call__(self, name, fresh=False):
        return self.of([name])[name]


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


class Frozen:
    """The log's clock: fixed, moving three seconds a read, set to a new minute before each task."""

    def __init__(self):
        self.now = START

    def at(self, minutes):
        self.now = START + timedelta(minutes=minutes)

    def utc(self, now=None):
        if now is not None:
            return now.astimezone(timezone.utc)
        self.now += timedelta(seconds=3)
        return self.now


def jev(label, confidence=0.94, state="ok"):
    return {"status": state, "label": label, "confidence": confidence, "needs_split": 0.08, "tokens": 640}


def label_of(*answers):
    """A fake Jev: the answers in order (one per labeled text)."""
    queue = list(answers)

    def label(text, *, task_id, tokens_this_month):
        return dict(queue.pop(0) if len(queue) > 1 else queue[0])
    return label


def png(width, height, rgb, mark=None):
    """A small valid PNG made in code: a flat colour, with an optional square of a second colour."""
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            inside = mark and mark[0] <= x < mark[2] and mark[1] <= y < mark[3]
            row += bytes(mark[4] if inside else rgb)
        rows.append(bytes(row))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def fake_pages(pdf, dest):
    Path(dest).mkdir(parents=True, exist_ok=True)
    pages = []
    for n in (1, 2):
        page = Path(dest) / f"page-{n}.png"
        page.write_bytes(png(60, 80, (246, 244, 236), (8, 10 + 18 * n, 52, 20 + 18 * n, (90, 90, 90))))
        pages.append(page)
    return pages, 2


def fake_frames(clip, dest):
    Path(dest).mkdir(parents=True, exist_ok=True)
    frames = []
    for n, colour in ((1, (88, 142, 72)), (2, (120, 160, 90))):
        frame = Path(dest) / f"frame_0{n}.png"
        frame.write_bytes(png(96, 54, colour, (30, 20, 66, 40, (200, 170, 90))))
        frames.append(frame)
    return frames


# ---------- the world ----------

class World:
    def __init__(self, tmp):
        self.tmp, self.frozen, self.count = tmp, Frozen(), 0
        self.now = None  # the demo's clock: when its status is taken (set after the last task)
        self.conn = log.init_db(tmp / "router.db")
        self.store = FakeHindsight()
        self.hindsight = self.store.client  # the router's memory client over the fake store
        self.inbox = tmp / "inbox"
        self.inbox.mkdir()

    def next_id(self, now=None):
        self.count += 1
        return f"sr-{self.frozen.now:%Y%m%d-%H%M%S}-{self.count:04x}"

    def route(self, minute, text, answer, *, worker=None, chatgpt=None, hook=None, wait=True, chat=None, project=None,
              files=(), hindsight=None, available=None):
        self.frozen.at(minute)
        clock = Clock()
        hook = hook or Hook()
        cli.cmd_route(text, conn=self.conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                      label=label_of(answer), post=hook.post, worker=worker or Scripted(),
                      chatgpt=chatgpt or Scripted("PASS"), codex_login=lambda: True, fetch=hook.fetch, close=hook.close,
                      sleep=clock.sleep, clock=clock, wait=wait, ask=None, chat=chat, project=project, files=list(files),
                      frames=fake_frames, pages=fake_pages, hindsight=hindsight, available=available, out=_quiet)
        return self.last()

    def check(self, minute, *, hook, worker=None, chatgpt=None, available=None):
        """`sr check` at `minute` (brief 24: a takeover at overdue, a late answer)."""
        self.frozen.at(minute)
        cli.cmd_check(conn=self.conn, config=CONFIG, fetch=hook.fetch, close=hook.close, post=hook.post,
                      worker=worker or Scripted(), chatgpt=chatgpt or Scripted(), codex_login=lambda: True,
                      presets=LOADED, roster=ROSTER, available=available, out=_quiet)

    def relay(self, minute, preset, text, *, worker, chatgpt, hook=None, wait=True, chat=None, slots=()):
        self.frozen.at(minute)
        clock = Clock()
        hook = hook or Hook()
        cli.cmd_relay(preset, text, conn=self.conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                      settings_paths=[], post=hook.post, worker=worker, chatgpt=chatgpt, codex_login=lambda: True,
                      fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=wait, chat=chat,
                      slots=list(slots), hindsight=self.hindsight if chat else None, out=_quiet)
        return self.last()

    def split(self, minute, text, *, planner, labels):
        self.frozen.at(minute)
        clock, hook = Clock(), Hook()
        cli.cmd_split(text, conn=self.conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                      label=label_of(*labels), ask=None, post=hook.post, worker=planner, chatgpt=Scripted(),
                      codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                      wait=True, out=_quiet)
        return self.last(mode="split")

    def split_go(self, minute, row, *, worker, chatgpt, labels, skills=()):
        self.frozen.at(minute)
        clock, hook = Clock(), Hook()
        cli.cmd_split_go([row["task_id"]], conn=self.conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=label_of(*labels), ask=None, post=hook.post, worker=worker, chatgpt=chatgpt,
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=True, answer="y", skills=list(skills), out=_quiet)

    def last(self, mode=None):
        rows = self.conn.execute("SELECT rowid AS n, * FROM tasks" + (" WHERE mode = ?" if mode else "")
                                 + " ORDER BY rowid DESC LIMIT 1", (mode,) if mode else ()).fetchall()
        return rows[0]


def _quiet(*args, **kwargs):
    pass


def _refuse(*args, **kwargs):
    raise RuntimeError("the demo reaches no command, model, webhook or network")


ROSTER = None
LOADED = None


# ---------- the invented tasks, one of every kind ----------

def _vote(answer, why):
    return f"## Answer\n{answer}\n\n## Why\n{why}\n\n## Confidence\n75"


REVIEW_PASS = "## Verdict\npass\n\n## Notes\n- Wrong: nothing.\n- Strong: short and concrete."
REVIEW_FAIL = "## Verdict\nfail\n\n## Notes\n- Wrong: it promises a crust the loaf doesn't have.\n- Strong: warm tone."
ATTACKS = ("## Attacks\n1. [high] The plan has no backup if the spreadsheet is edited by mistake.\n"
           "2. [medium] Nobody owns the sheet on weekends.\n3. [low] The column names are not fixed in advance.\n\n"
           "## Strongest\nA mistaken edit could lose a day of pre-orders.")
PLAN_STEPS = ("Pre-order plan\n\n1. Make one shared sheet with columns: name, item, pickup day, paid.\n"
              "2. Staff add each phone order the moment it comes in.\n3. Print the next day's list at closing.")
BUILD = f"## Deliverable\n{PLAN_STEPS}\n\n## Unfinished\nnone"
REVISION = (PLAN_STEPS.replace("3. Print", "3. Turn on version history and keep a daily copy.\n4. Print")
            + "\n\n## Answered\n3. The column names are fixed in step 1, so this attack does not apply.")
NOTE = ("## Findings\n- Tumblers turn quicker but cost more.\n- Three-bay bins suit shared gardens.\n"
        "- Worm bins work in small spaces.\n\n## Sources\n- https://example.org/compost-guide\n"
        "- https://example.org/tumbler-test\n- https://example.org/worm-bins\n\n## Gaps\n- No prices for 2026.")
HANDOFF_RESULT = ("Lending rules\n\n- Take up to five packets a month.\n- Bring back seeds from what you grow.\n\n"
                  "## Handoff\n### Produced\nnothing written: Lending rules, the seed library's two rules in a list.\n"
                  "### Status\nThe README has its lending section.\n### Next\nAdd the opening hours.")
PLAN = ("## Pieces\n1. Write a one-page FAQ for the seed library.\n2. Draft a short email announcing the seed library.\n\n"
        "## Join\nPut the email first, then the FAQ.")
PLAN_TWO = ("## Pieces\n1. List three winter vegetables for a small garden.\n2. Write a haiku about frost.\n\n"
            "## Join\nPut the list above the haiku.")


def build_log(w):
    tmp = w.tmp
    garden = "garden"
    # 1. passed (routed writing, a chat with memory)
    w.route(1, "Write a two-sentence welcome for the Maple Street community garden newsletter.", jev("writing"),
            worker=Scripted("Welcome to the Maple Street garden! Bring gloves, bring friends, and take home what you grow."),
            chat=garden, hindsight=w.hindsight)
    # 2. fixed
    w.route(6, "Draft a 40-word notice that the garden's tool shed now opens at 7 am.", jev("writing"),
            worker=Scripted("The tool shed now opens at 7 am.", "From Monday, the tool shed opens at 7 am on weekdays."),
            chatgpt=Scripted("FIX\n1. Say the 7 am opening is on weekdays only.", "PASS"), chat=garden,
            hindsight=w.hindsight)
    # 3. failed its check twice: the fallback is offered
    w.route(11, "Write a Python function to_minutes(text) that turns '2h 15m' into 135, with three doctests.",
            jev("code", 0.97), worker=Scripted("def to_minutes(text):\n    return 0", "def to_minutes(text):\n    return 1"),
            chatgpt=Scripted("FIX\n1. It returns 0 for every input.", "FIX\n1. It still ignores the hours."))
    # 4. unchecked: a quick answer
    w.route(16, "How many tablespoons are in a quarter cup?", jev("quick_answer", 0.99), worker=Scripted("4 tablespoons."))
    # 5. versus, waiting for the pick
    w.relay(21, "versus", "A 25-word blurb for a bakery's new rye loaf.",
            worker=Scripted("Dark, tangy and slow-proofed for two days: our new rye is made for butter, soup and Sunday.",
                            REVIEW_FAIL), chatgpt=Scripted("Our new rye: a crackling crust, a soft sour crumb.", REVIEW_PASS))
    # 6. versus, picked
    picked = w.relay(26, "versus", "A one-line slogan for a bike repair cafe.",
                     worker=Scripted("Fix it over coffee.", REVIEW_PASS),
                     chatgpt=Scripted("Bring a flat, leave with a smile.", REVIEW_PASS))
    w.frozen.at(29)
    cli.cmd_pick([picked["task_id"], "a"], conn=w.conn, loaded=LOADED, out=_quiet)
    # 7. vote, a majority
    w.relay(31, "vote", "One word: should the garden newsletter go out weekly or monthly? Then one line why.",
            worker=Scripted(_vote("Monthly", "Volunteers have time to write once a month.")),
            chatgpt=Scripted(_vote("Monthly", "Readers open a monthly letter more often.")),
            hook=Hook(s3=_vote("Weekly", "Weekly keeps the plot news fresh.")), chat=garden)
    # 8. vote, a tie waiting for the pick
    w.relay(36, "vote", "Pick a one-word name for the garden's seed library.",
            worker=Scripted(_vote("Sprout", "Short and friendly.")), chatgpt=Scripted(_vote("Kernel", "It sounds sturdy.")),
            hook=Hook(s3=_vote("Acorn", "Small things grow.")))
    # 9. redteam, with attacks
    w.relay(41, "redteam", "Plan how the bakery moves its pre-orders from a paper list to a shared spreadsheet.",
            worker=Scripted(BUILD, REVISION), chatgpt=Scripted(ATTACKS, "PASS"))
    # 10. research-build, passed
    w.relay(46, "research-build", "Compare three compost bin designs for a small shared garden, with sources.",
            worker=Scripted("Three bins compared\n\nA three-bay bin suits a shared garden best; a tumbler is quicker."),
            chatgpt=Scripted("PASS"), hook=Hook(s1=NOTE))
    # 11. stopped on a plan limit: the resume is offered
    w.route(51, "Summarize this week's garden volunteer sign-ups into a short table.", jev("writing"),
            worker=Scripted(claude_worker.WorkerError("plan limit on claude: You've hit your session limit · resets 3pm",
                                                      code="plan_limit")))
    # 12. stopped when its process ended: the resume is offered (the rows sr check writes for a dead run)
    w.frozen.at(56)
    task_id = w.next_id()
    log.add_task(w.conn, task_id, "Write a 60-word description of the garden's new rain barrel.", "ui", jev("writing"))
    log.set_route(w.conn, task_id, agents=ROSTER.names, agent="claude", route_reason="best", skill="writing",
                  skill_source="jev", checker="chatgpt", check_state="pending")
    log.add_call(w.conn, task_id, task_id, "do", "claude", status="failed", text=None, reason_code="process_ended")
    log.set_failed(w.conn, task_id, cli.PROCESS_ENDED_RESULT)
    # 15. a split plan waiting, one piece under the floor
    w.split(71, "Build a one-page FAQ for the seed library and a short email announcing it.", planner=Scripted(PLAN),
            labels=[jev("writing", 0.95), jev("planning", 0.52, "below_floor")])
    # 16. a split's pieces, one blocked (it failed its check twice)
    two = w.split(76, "List three winter vegetables for a small garden and write a haiku about frost.",
                  planner=Scripted(PLAN_TWO), labels=[jev("quick_answer", 0.97), jev("writing", 0.95)])
    w.split_go(78, two, worker=Scripted("Kale, leeks and garlic.", "Frost on the bean poles", "Frost on the poles, again"),
               chatgpt=Scripted("FIX\n1. A haiku has three lines.", "FIX\n1. Still not three lines."), labels=[jev("writing")])
    # 17. needs a label: Jev was under the floor
    w.route(81, "redo last month's volunteer calendar for november, same format", jev("writing", 0.5, "below_floor"))
    # 18. cancelled (a Grok task, cancelled while it was out)
    row = w.route(86, "What are local bakeries posting about pumpkin bread on X?", jev("x_social_pulse", 0.95), wait=False)
    w.frozen.at(88)
    cli.cmd_cancel(conn=w.conn, words=[row["task_id"]], out=_quiet)
    # 19. tagged with memory: a recall over the garden chat
    w.route(91, "What did we decide about the newsletter schedule?", jev("recall", 0.98),
            worker=Scripted("You voted for a monthly newsletter (2 to 1); the tool shed notice went out for weekdays."),
            chat=garden, hindsight=w.hindsight)
    # 20. a project task with its handoff
    folder = tmp / "Projects" / "garden-site"
    folder.mkdir(parents=True)
    projects.add("garden-site", folder)
    w.route(96, "Write the README section that explains the seed library's lending rules.", jev("writing"),
            worker=Scripted(HANDOFF_RESULT), project="garden-site")
    # 21. a file: an image read and checked
    photo = w.inbox / "raised-bed.png"
    photo.write_bytes(png(120, 80, (110, 150, 80), (20, 30, 100, 60, (150, 105, 60))))
    w.route(101, "Describe this photo of the garden's new raised bed in one sentence.", jev("read_media", 0.97),
            worker=Scripted("A wooden raised bed full of dark soil sits on a green lawn."), files=[photo])
    # 22. a PDF (its page images) and 23. a video (its stills)
    menu = w.inbox / "menu.pdf"
    menu.write_bytes(b"%PDF-1.4\n% invented demo file\n")
    w.route(106, "Summarize this menu in three bullet points.", jev("read_media", 0.96),
            worker=Scripted("- Three breads\n- Two soups\n- One cake of the day"), files=[menu])
    clip = w.inbox / "garden-walk.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42 invented demo file")
    w.route(111, "What plants can you see in this short garden video?", jev("read_media", 0.95),
            worker=Scripted("Beans on poles, a row of kale and two tomato cages."), files=[clip])
    # 24. a Grok image (make_media): the router pulls the image Grok made into media/out/<task_id>/
    badge = png(64, 64, (250, 240, 220), (16, 16, 48, 48, (214, 64, 52)))
    inbox.fetch_file = lambda path, run=None: badge
    w.route(116, "Make a pixel-art badge of a tomato for the garden newsletter.", jev("make_media", 0.97),
            hook=Hook(do=lambda call_id: f"Here is the badge.\n\nmedia/out/{call_id}/tomato-badge.png"))
    # brief 24 (decision 15's demo): 25. a stand-in: Grok Bot isn't set up, so ChatGPT does Meta research, without
    # Meta, and Claude checks it (X research has no stand-in: Grok Bot's alone, the owner, 21 Oct)
    w.route(118, "What are gardeners on Instagram and Facebook saying about no-dig beds this month?",
            jev("meta_social_trends", 0.96),
            chatgpt=Scripted("- Many say no-dig beds save their backs.\n- Some warn about slugs under the cardboard.\n\n"
                             "Sources: garden blogs quoting Instagram and Facebook posts; the apps themselves couldn't be "
                             "searched, so what people say now may be missing."), worker=Scripted("PASS"),
            available=Gate(**NO_GROK))
    # 26. a takeover after a plan limit: Claude stopped, ChatGPT took over the first call, nobody was left to check it
    w.route(121, "Write a 30-word thank-you note to the garden's volunteers.", jev("writing"), worker=Scripted(PLAN_LIMIT),
            chatgpt=Scripted("Thank you for every weeded row, every watered bed and every early Saturday. The garden grows "
                             "because you show up. See you at the harvest supper!"), available=Gate())
    # 27. an overdue takeover and its late Grok answer: 11 minutes on, `sr check` hands it to ChatGPT; Grok's answer
    # comes 3 minutes later and is kept on its row, never used (Meta research: Grok's X calls are never taken over)
    grok = Hook()  # one inbox for the send and both checks: its issue lands only before the second
    w.route(124, "What are cyclists on Facebook saying about the new Maple Street bike lane?",
            jev("meta_social_trends", 0.95), wait=False, hook=grok, available=Gate())
    w.check(135, hook=grok, worker=Scripted("PASS"), available=Gate(),
            chatgpt=Scripted("- Riders like the painted buffer.\n- A few ask for a curb at the corner.\n\n"
                             "Sources: local news quoting Facebook posts; Facebook itself couldn't be searched."))
    grok.bodies["do"] = "- Cyclists on Facebook love the new lane.\n- Some want it extended to the park."
    w.check(138, hook=grok, available=Gate())
    # 28. make_media without Grok Bot comes back before any agent call: nothing stands in for it
    w.route(141, "Make a pixel-art badge of a carrot for the garden newsletter.", jev("make_media", 0.97),
            available=Gate(**NO_GROK))
    # 29. X research without Grok Bot comes back too (the owner, 21 Oct: web search can't see X posts)
    w.route(142, "What are people on X saying about the garden's new compost bins?", jev("x_social_pulse", 0.96),
            available=Gate(**NO_GROK))
    # 30. Jev isn't set up: the task waits for your label (a refused team is the run log's third run)
    w.route(144, "Draft the agenda for next month's garden meeting.", {"status": "not_set_up", "tokens": 0})
    # the last two: overdue on Grok, then waiting on Grok. The demo's clock stops 6.5 minutes after the second's send,
    # and each note is the router's own (log.grok_note, the whole minutes since its send), so a card's timer, which
    # counts to the demo's clock, agrees with its note (the owner, 21 Oct)
    rows = [w.route(minute, text, jev("x_social_pulse", 0.96), wait=False) for minute, text in (
        (147, "What are bike commuters posting about winter tires on X?"),
        (153, "What are people saying about sourdough discard recipes on X this week?"))]
    sent = [log.calls_for(w.conn, row["task_id"])[-1]["sent_at"] for row in rows]
    w.now = datetime.fromisoformat(sent[-1]) + timedelta(minutes=6, seconds=30)
    for row, at in zip(rows, sent):
        log.set_grok_note(w.conn, row["task_id"], log.grok_note(at, w.now, settings.grok_timeout_minutes()))


# ---------- the documents ----------

def _replace_paths(value, tmp):
    """Every temp-folder and home-folder path becomes `~`, so the demo is the same on any machine and names no home."""
    if isinstance(value, str):
        for prefix in (str(tmp.resolve()), str(tmp), str(Path.home())):
            value = value.replace(prefix, "~")
        return value
    if isinstance(value, list):
        return [_replace_paths(v, tmp) for v in value]
    if isinstance(value, dict):
        return {k: _replace_paths(v, tmp) for k, v in value.items()}
    return value


def _write(path, doc, tmp):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_replace_paths(doc, tmp), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _refused_send(w):
    """The one refused send: what `sr relay versus --json --source ui -- '@claude hi'` answers, from the real command
    and the real envelope (`receipt.Receipt`, `_envelope`), with nothing run."""
    out, clock, hook = receipt.Receipt(), Clock(), Hook()
    code = cli.cmd_relay("versus", "@claude hi", conn=w.conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                         settings_paths=[], post=hook.post, worker=Scripted(), chatgpt=Scripted(),
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=False, source="ui", out=out)
    return code, cli._envelope(out, code)


def _refused_team(w):
    """Brief 24 (decision 8): a team refused for a missing agent, what `sr relay vote --json --source ui -- …` answers
    while Grok Bot isn't set up, from the real command and envelope, with nothing run."""
    out, clock, hook = receipt.Receipt(), Clock(), Hook()
    code = cli.cmd_relay("vote", "Pick a one-word theme for the harvest supper.", conn=w.conn, config=CONFIG,
                         roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[], post=hook.post, worker=Scripted(),
                         chatgpt=Scripted(), codex_login=lambda: True, fetch=hook.fetch, close=hook.close,
                         sleep=clock.sleep, clock=clock, wait=False, source="ui", available=Gate(**NO_GROK), out=out)
    return code, cli._envelope(out, code)


def build(out_dir, *, tmp_root=None):
    """Make the demo into `out_dir` (replaced whole). Every module attribute it changes is put back."""
    global ROSTER, LOADED
    saved = {}

    def patch(obj, name, value):
        saved.setdefault((obj, name), getattr(obj, name))
        setattr(obj, name, value)

    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    with tempfile.TemporaryDirectory(dir=tmp_root) as temp:
        tmp = Path(temp)
        try:
            ROSTER = cli.load_roster(send_paths=tuple(cli.SENDERS))
            LOADED = presets.load_presets(ROSTER, tuple(cli.SENDERS), relay.CONTRACTS, roles=relay.ROLES,
                                          verdicts=relay.VERDICTS)
            w = World(tmp)
            patch(subprocess, "Popen", _refuse)
            patch(requests.adapters.HTTPAdapter, "send", _refuse)
            patch(log, "_utc", w.frozen.utc)
            patch(cli, "_now", lambda: w.frozen.now.replace(tzinfo=None))
            patch(ids, "new_task_id", w.next_id)
            patch(runs, "_ME", (os.getpid(), "2026-10-19T08:59:00+00:00"))
            patch(runs, "READ", lambda pid: "2026-10-19T08:59:00+00:00" if pid == os.getpid() else None)
            patch(runs, "_HELD", {})
            patch(runs, "FOLDER", None)
            patch(media, "MEDIA_ROOT", tmp / "media")
            (tmp / "settings.local.json").write_text(json.dumps({"report_path": "~/Downloads/claude-code-report.md"}))
            patch(settings, "LOCAL_PATH", tmp / "settings.local.json")
            patch(projects, "REGISTRY_PATH", tmp / "config" / "projects.json")
            patch(inbox, "fetch_file", inbox.fetch_file)
            patch(cli, "DB_PATH", tmp / "router.db")
            patch(cli, "ENV_PATH", tmp / ".env-none")
            patch(cli, "PROBE_STATE", tmp / "probe_state.json")
            patch(log, "ROUND_WRITER", rounds.writer(secrets=list(CONFIG.values()), out=_quiet, loaded=LOADED))
            build_log(w)
            log.ROUND_WRITER = None
            _documents(w, tmp, out_dir)
        finally:
            for (obj, name), value in saved.items():
                setattr(obj, name, value)
            if old_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old_tz
            time.tzset()


def _documents(w, tmp, out_dir):
    staging = Path(str(out_dir) + ".new")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    conn, now = w.conn, w.now
    rows = conn.execute("SELECT rowid AS n, * FROM tasks ORDER BY rowid DESC").fetchall()
    _write(staging / "log.json", jsonview.log_view(conn, rows[:50], limit=50, live=ROSTER.live, loaded=LOADED), tmp)
    for row in rows:
        _write(staging / "tasks" / f"{row['task_id']}.json",
               jsonview.show_view(conn, row, live=ROSTER.live, loaded=LOADED, roster=ROSTER), tmp)
    probe = tmp / "probe_state.json"
    probe.write_text(json.dumps({
        "claude_search": {"version": "2.1.306", "passed_at": "2026-10-19T08:00:00+00:00"},
        "claude_web_files": {"version": "2.1.306", "passed_at": "2026-10-19T08:00:00+00:00"},
        "cursor_sandbox": {"version": "2026.10.12-a1b2c3d", "passed_at": "2026-10-12T08:00:00+00:00"},
        "cursor_sandbox_failure": {"version": "2026.10.19-6bbf2c4", "kind": "ran_failed",
                                   "reason": "read canary: a read completed", "at": "2026-10-19T08:30:00+00:00"}}))
    stamp = now.isoformat()  # every agent checked at the demo's clock, the moment its status is taken
    online = {"claude": {"online": True, "reason": None, "checked_at": stamp},
              "chatgpt": {"online": False, "reason": "not signed in with ChatGPT (codex login)", "checked_at": stamp,
                          "code": "signed_out"},  # brief 24: the check's code, as router/online.py gives it
              "cursor": {"online": True, "reason": None, "checked_at": stamp}}
    rules = tmp / "RULES.md"
    rules.write_text("# The rules\n\nVersion 2.32 · the demo\n")
    doc = status.build(conn, roster=ROSTER, loaded=LOADED, env=STATUS_ENV, parser=cli._parser(ROSTER), online=online,
                       versions={"claude": "2.1.306", "chatgpt": "0.162.1", "cursor": "2026.10.19-6bbf2c4"},
                       state_path=probe, memory_client=FakeHindsight(online=False).client, drop_folder="~/Desktop/Router Drop",
                       rules_path=rules, now=now, log_version=log.VERSION, memory_starting=True, memory_installed=True,
                       send_paths=tuple(cli.SENDERS), contracts=relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
    _write(staging / "status.json", doc, tmp)
    _write(staging / "projects.json", {"api_version": jsonview.API_VERSION,
                                       "projects": cli._projects_json(projects.read_registry(), {})}, tmp)
    code, envelope = _refused_send(w)
    team_code, team_envelope = _refused_team(w)
    stamp = "2026-10-19T11:02:00+00:00"
    _write(staging / "runs.json", {"runs": [
        {"id": "run-3", "kind": "action", "display": "sr relay vote --json --source ui -- 'Pick a one-word theme for the "
         "harvest supper.'", "started": "2026-10-19T11:03:00+00:00", "pid": 41003, "running": False, "exit": team_code,
         "envelope": team_envelope, "message": team_envelope.get("message"), "stderr": "", "task_id": None},
        {"id": "run-2", "kind": "action", "display": "sr relay versus --json --source ui -- '@claude hi'", "started": stamp,
         "pid": 41002, "running": False, "exit": code, "envelope": envelope, "message": envelope.get("message"),
         "stderr": "", "task_id": None},
        {"id": "run-1", "kind": "check", "display": "sr check --json", "started": "2026-10-19T11:01:00+00:00", "pid": None,
         "running": False, "exit": 0, "envelope": None, "message": "Nothing to check.", "stderr": "", "task_id": None},
    ]}, tmp)
    (staging / "report.md").write_text("# A sample report\n\nThis is where your builder's report shows, when "
                                       "`report_path` is set in `config/settings.local.json`.\n\n- Nothing here is real.\n",
                                       encoding="utf-8")
    handoff = (tmp / "Projects" / "garden-site" / "HANDOFF.md").read_text(encoding="utf-8")
    (staging / "handoff").mkdir()
    (staging / "handoff" / "garden-site.md").write_text(handoff, encoding="utf-8")
    for part in ("tasks", "media/in", "media/pages", "media/frames", "media/out"):
        source = tmp / part
        if source.is_dir():
            shutil.copytree(source, staging / "files" / part)
    for path in sorted((staging / "files").rglob("*")):
        if path.is_file():
            path.chmod(0o644)  # the round files are owner-only where they were made; the demo's are plain files
            if path.suffix == ".md":  # a result may name the temp folder (a Grok image's path): the same `~` as the JSON
                path.write_text(_replace_paths(path.read_text(encoding="utf-8"), tmp), encoding="utf-8")
    if Path(out_dir).exists():
        shutil.rmtree(out_dir)
    staging.rename(out_dir)


if __name__ == "__main__":
    build(OUT)
    print(f"demo written to {OUT.relative_to(ROOT)}/")
