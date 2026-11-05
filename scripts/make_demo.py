"""The demo's invented sample (build brief 23, decision 15), made by the router's own code. It builds a scratch log in a
temp folder by running the real commands (route, relay, split, pick, cancel) with fake agents, a fake Jev, a fake
webhook and a fake memory store, on a fixed clock with fixed task ids, then writes what the real serializers print
(`router/status.py`, `router/jsonview.py`) into demo/, beside the round files and media the run left. `sr serve --demo`
serves demo/ and runs nothing. A test regenerates it and fails on any drift (tests/test_demo.py).

Everything here is invented: the tasks, the answers, the names. No real log, key, name, path or task is read, and no
command, model, webhook or network is reached (the script blocks them). Run: `python scripts/make_demo.py`."""
import json
import os
import shlex
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
from router import (availability, chatgpt_worker, claude_worker, cursor_worker, filemode, gitops, ideas, ids, inbox, spec,  # noqa: E402
                    jsonview, log, media, memory, models,
                    notes, plan, presets, projects, projnotes, projrun, projsecrets, projspec, projtest, receipt, relay, rounds, runs,
                    settings, status)
from tests.fake_hindsight import FakeHindsight  # noqa: E402

OUT = ROOT / "demo"
START = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)
CONFIG = {"GROK_WEBHOOK_URL": "https://example.invalid/hook", "GROK_WEBHOOK_KEY": "FAKE-WEBHOOK-KEY-00"}
STATUS_ENV = {}  # the demo's status: Grok Bot has no webhook set ("not configured"); Jev has no key ("not set up")
# Brief 30 (decision 20): the demo's router notes, placeholder lines in each section, kept with every demo task
DEMO_NOTES = ("## All agents\n<a line every agent follows, such as how you like answers>\n\n"
              "## Claude\n<a line for Claude alone>\n\n## ChatGPT\n<a line for ChatGPT alone, such as how it checks>\n\n"
              "## Grok\n<a line for Grok Bot alone, such as what it names>\n\n## Cursor\n<a line for Cursor alone>\n\n"
              "## Planner\n<how you like a task split and its teams picked>\n")
NO_GROK = {"grok": ("Grok Bot isn't set up: no inbox repo in settings", "not_configured")}
PLAN_LIMIT = claude_worker.WorkerError("plan limit on claude: You've hit your session limit · resets 3pm", code="plan_limit")


# ---------- fakes ----------

class Scripted:
    """A fake agent: each call returns the next reply (or raises it). Brief 33.3 (decision 7): a text reply carries a
    served record as the real workers' do (the model asked, and the model that answered: `served`, else the one asked)."""

    def __init__(self, *replies, served=None):
        self.replies, self.served = list(replies), served

    def __call__(self, prompt, **kwargs):
        reply = self.replies.pop(0) if self.replies else "An answer."
        if isinstance(reply, BaseException):
            raise reply
        choice = kwargs.get("choice")
        if choice is None or not isinstance(reply, str) or not choice.model:
            return reply
        answered = self.served or choice.model
        record = {**choice.record(), "model": answered, "credits": {"seen": False},
                  "source": "stream: init and modelUsage" if choice.agent == "claude" else "codex header",
                  "differs": answered != choice.model}
        answer = claude_worker.Answer if choice.agent == "claude" else chatgpt_worker.Answer
        return answer(reply, served=record)


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
              files=(), hindsight=None, available=None, model_flags=()):
        self.frozen.at(minute)
        clock = Clock()
        hook = hook or Hook()
        cli.cmd_route(text, conn=self.conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                      label=label_of(answer), post=hook.post, worker=worker or Scripted(),
                      chatgpt=chatgpt or Scripted("PASS"), codex_login=lambda: True, fetch=hook.fetch, close=hook.close,
                      sleep=clock.sleep, clock=clock, wait=wait, ask=None, chat=chat, project=project, files=list(files),
                      frames=fake_frames, pages=fake_pages, hindsight=hindsight, available=available,
                      model_flags=list(model_flags), out=_quiet)  # brief 33.3: a task's own model choice
        return self.last()

    def check(self, minute, *, hook, worker=None, chatgpt=None, available=None):
        """`sr check` at `minute` (brief 24: a takeover at overdue, a late answer)."""
        self.frozen.at(minute)
        cli.cmd_check(conn=self.conn, config=CONFIG, fetch=hook.fetch, close=hook.close, post=hook.post,
                      worker=worker or Scripted(), chatgpt=chatgpt or Scripted(), codex_login=lambda: True,
                      presets=LOADED, roster=ROSTER, available=available, out=_quiet)

    def relay(self, minute, preset, text, *, worker, chatgpt, hook=None, wait=True, chat=None, slots=(), project=None,
              cursor=None, cursor_ready=None):
        self.frozen.at(minute)
        clock = Clock()
        hook = hook or Hook()
        cli.cmd_relay(preset, text, conn=self.conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                      settings_paths=[], post=hook.post, worker=worker, chatgpt=chatgpt, codex_login=lambda: True,
                      fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=wait, chat=chat,
                      slots=list(slots), hindsight=self.hindsight if chat else None, project=project,
                      files_ready=lambda: (False, "the demo reaches no git"), cursor=cursor, cursor_ready=cursor_ready,
                      out=_quiet)
        return self.last()

    def split(self, minute, text, *, planner, labels, project=None):
        self.frozen.at(minute)
        clock, hook = Clock(), Hook()
        cli.cmd_split(text, conn=self.conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                      label=label_of(*labels), ask=None, post=hook.post, worker=planner, chatgpt=Scripted(),
                      codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                      wait=True, loaded=LOADED, project=project, files_ready=lambda: (True, None), out=_quiet)
        return self.last(mode="split")

    def split_edit(self, minute, row, piece, *, team=None, text=None, labels=(), slots=None):
        """Brief 29 (decision 8): `sr split --edit`, as the page's team select and Edit run it; brief 29.1 (decision 12):
        a preset piece's slots."""
        self.frozen.at(minute)
        cli.cmd_split_edit([row["task_id"]], piece=str(piece), team=team, text=text, slots=slots, conn=self.conn,
                           config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=label_of(*labels),
                           loaded=LOADED, out=_quiet)

    def split_go(self, minute, row, *, worker, chatgpt, labels, skills=()):
        self.frozen.at(minute)
        clock, hook = Clock(), Hook()
        cli.cmd_split_go([row["task_id"]], conn=self.conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=label_of(*labels), ask=None, post=hook.post, worker=worker, chatgpt=chatgpt,
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=True, answer="y", skills=list(skills), loaded=LOADED, out=_quiet)

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
# Brief 32 (decision 19): the second attacker's list, made from the build alone, and a revision that answers both by label
B_ATTACKS = ("## Attacks\n1. [high] Anyone with the sheet's link could change or delete an order.\n"
             "2. [medium] Two staff adding phone orders at once could overwrite each other.\n"
             "3. [low] The paid column doesn't say how a card payment is marked.\n\n"
             "## Strongest\nAnyone with the link could change the orders.")
REVISION = (PLAN_STEPS.replace("1. Make one shared sheet", "1. Make one shared sheet, editable by staff only,")
            .replace("3. Print", "3. Turn on version history and keep a daily copy.\n4. Print")
            + "\n\n## Answered\nA3: The column names are fixed in step 1, so this attack does not apply.\n"
              "B2: A shared sheet saves each edit as it is typed, so two staff adding rows at once don't overwrite each "
              "other.\nB3: Paid is yes or no; how it was paid isn't part of this plan.")
SHED_STEPS = ("Tool-shed key plan\n\n1. Keep two keys: one in the lockbox by the gate, one with the shed lead.\n"
              "2. Volunteers sign the lockbox sheet when they take or return the key.\n3. Change the lockbox code each season.")
SHED_BUILD = f"## Deliverable\n{SHED_STEPS}\n\n## Unfinished\nnone"
SHED_ATTACKS = ("## Attacks\n1. [high] Nothing says what happens when the key isn't returned by dark.\n"
                "2. [medium] The lockbox code is shared with no record of who knows it.\n"
                "3. [low] \"Each season\" doesn't say who changes it.\n\n## Strongest\nA key kept overnight leaves the shed open.")
SHED_REVISION = (SHED_STEPS.replace("3. Change", "3. A key not back by dark: the shed lead collects it the next morning.\n4. The "
                                    "shed lead changes")
                 + "\n\n## Answered\nA2: Only volunteers on this season's list get the code; that list is the record.")


CURSOR_OFF = "Cursor is off: its safety check failed on agent 2026.10.19-6bbf2c4"  # the demo status's own words for Cursor


class CursorFake:
    """The demo's Cursor (brief 32): each call answers the next text, served by the pinned model with no tool event."""

    def __init__(self, *replies):
        self.replies = list(replies)

    def __call__(self, prompt, *, call_id="call"):
        return cursor_worker.CursorAnswer(self.replies.pop(0) if self.replies else "an answer",
                                          {"model": "Grok 4.7 256K High", "asked": "grok-4.7-high", "tool_events": 0,
                                           "tools": [], "duration_ms": 21000, "permission_mode": "default"})
NOTE = ("## Findings\n- Tumblers turn quicker but cost more.\n- Three-bay bins suit shared gardens.\n"
        "- Worm bins work in small spaces.\n\n## Sources\n- https://example.org/compost-guide\n"
        "- https://example.org/tumbler-test\n- https://example.org/worm-bins\n\n## Gaps\n- No prices for 2026.")
# Build brief 28 (decision 21): the project files demo. seed-library has git and a test command; the changes, their
# diffs and their test runs are invented here and written as the router keeps them (the demo reaches no git).
SEEDS_HANDOFF = "\n\n## Handoff\n### Produced\n{files}\n### Status\n{status}\n### Next\n{next}"
LANDED_RESULT = ("Each loan now has a due date, four weeks out, and a test checks it." + SEEDS_HANDOFF.format(
    files="loans.py changed; test_loans.py added", status="Loans have due dates.", next="Show overdue loans first."))
FAILING_RESULT = ("Overdue loans now sort first." + SEEDS_HANDOFF.format(
    files="loans.py changed", status="Overdue loans sort first.", next="Email a reminder a week before."))
WAITING_RESULT = ("Each packet counts its loans: lend() adds one, and a test checks it." + SEEDS_HANDOFF.format(
    files="packets.py changed; test_packets.py added", status="Packets count their loans.", next="Show the count on the list."))
LANDED_DIFF = """diff --git a/loans.py b/loans.py
index 3f1a2b4..8c9d0e1 100644
--- a/loans.py
+++ b/loans.py
@@ -1,6 +1,9 @@
+from datetime import date, timedelta
+
 class Loan:
-    def __init__(self, packet, member):
+    def __init__(self, packet, member, lent_on):
         self.packet = packet
         self.member = member
+        self.due = lent_on + timedelta(weeks=4)
diff --git a/test_loans.py b/test_loans.py
new file mode 100644
index 0000000..5b6c7d8
--- /dev/null
+++ b/test_loans.py
@@ -0,0 +1,8 @@
+import unittest
+from datetime import date
+from loans import Loan
+
+
+class DueDate(unittest.TestCase):
+    def test_four_weeks_out(self):
+        self.assertEqual(Loan("kale", "ada", date(2026, 10, 1)).due, date(2026, 10, 29))
"""
FAILING_DIFF = """diff --git a/loans.py b/loans.py
index 8c9d0e1..a1b2c3d 100644
--- a/loans.py
+++ b/loans.py
@@ -12,4 +12,4 @@ def listed(loans, today):
-    return sorted(loans, key=lambda loan: loan.due)
+    return sorted(loans, key=lambda loan: loan.due, reverse=True)
"""
WAITING_DIFF = """diff --git a/packets.py b/packets.py
index 0d1e2f3..4a5b6c7 100644
--- a/packets.py
+++ b/packets.py
@@ -3,5 +3,8 @@ class Packet:
     def __init__(self, crop):
         self.crop = crop
+        self.lend_count = 0
 
     def lend(self, member):
-        return Loan(self, member, date.today())
+        loan = Loan(self, member, date.today())
+        self.lend_count += 1
+        return loan
diff --git a/test_packets.py b/test_packets.py
new file mode 100644
index 0000000..9e8f7a6
--- /dev/null
+++ b/test_packets.py
@@ -0,0 +1,9 @@
+import unittest
+from packets import Packet
+
+
+class LendCount(unittest.TestCase):
+    def test_each_loan_counts(self):
+        packet = Packet("beans")
+        packet.lend("ada"), packet.lend("lin")
+        self.assertEqual(packet.lend_count, 2)
"""
FAILING_TESTS = ("F.\n======================================================================\nFAIL: test_overdue_first "
                 "(test_loans.Listing.test_overdue_first)\n----------------------------------------------------------------"
                 "------\nAssertionError: 'kale' != 'beans'\n\n----------------------------------------------------------"
                 "------------\nRan 2 tests in 0.002s\n\nFAILED (failures=1)\n")
PASSING_TESTS = "..\n----------------------------------------------------------------------\nRan 2 tests in 0.001s\n\nOK\n"
DEMO_FILES_VIEWS = {  # what status reads of each demo project's git (brief 28): invented, never a git command
    "seed-library": {"git": True, "branch": "main", "head": "4f2a9c1", "files_mode": "on", "why": None},
    "plot-planner": {"git": True, "branch": "main", "head": "7d3e1a9", "files_mode": "on", "why": None},  # brief 29
    "garden-site": {"git": False, "branch": None, "head": None, "files_mode": "off", "why": "no git yet: Turn on undo"},
    "swap-shelf": {"git": True, "branch": "main", "head": "4f2a9c1", "files_mode": "on", "why": None},  # brief 29.1
    # brief 33.1 (decision 21): a plan two steps in, a plan waiting for approval, a One step answer, a finished plan
    "pea-trial": {"git": True, "branch": "main", "head": "9c4e2b7", "files_mode": "on", "why": None},
    "bean-board": {"git": True, "branch": "main", "head": "2b8d6f1", "files_mode": "on", "why": None},
    "herb-labels": {"git": True, "branch": "main", "head": "6a1c3e5", "files_mode": "on", "why": None},
    "compost-log": {"git": True, "branch": "main", "head": "8e5b1d3", "files_mode": "on", "why": None},
    "rain-gauge": {"git": True, "branch": "main", "head": "7b1d3f5", "files_mode": "on", "why": None},  # brief 33.2: a revision
    # brief 34 (decision 16): the Auto projects, file mode on at intake too (the demo's one exception: the switch needs it)
    "seed-swap": {"git": True, "branch": "main", "head": "1a3c5e7", "files_mode": "on", "why": None},
    "trellis-plan": {"git": True, "branch": "main", "head": "2b4d6f8", "files_mode": "on", "why": None},
    "mulch-notes": {"git": True, "branch": "main", "head": "3c5e7a9", "files_mode": "on", "why": None}}


# ---------- brief 33.1 (decision 21): the plan's demo projects ----------

PEA_PLAN = """## Steps
1. Make the skeleton: trial.py that prints a help line, and test_trial.py with one test that runs it.
   team: route
   why: the smallest thing that runs, so each later step has a test to stand on
   done when: test_trial.py's test_help passes under python3 -m unittest
   covers: none
2. Add record_sowing(bed, date) that stores a sowing in trial.json, with a test.
   team: route
   why: every later step reads the sowings
   done when: test_trial.py's test_record_sowing passes, checking a sowing is read back
   covers: E1, E2
3. Fetch the week's frost forecast and warn when a sowing falls in a frost window, with a test that fakes the feed.
   team: redteam
   why: the forecast is the part most likely to be wrong, so it gets attacked
   done when: test_frost.py's test_warns_in_frost_window passes with a faked feed
   covers: E3
4. Write the README: how to record a sowing and read the frost warnings.
   team: route
   why: the volunteers need it
   done when: README.md names both commands and the test command
   covers: none

## Needs from you
- key: FROST_FEED_KEY (step 3): the frost forecast feed
- account: a frost forecast feed account (step 3)
- decision: Warn three days or five days before a frost? (step 3)"""
BEAN_PLAN = """## Steps
1. Make the skeleton: board.py printing an empty bean board, and test_board.py with one test that passes.
   team: route
   why: there is no code yet, so step 1 is the smallest thing that runs
   done when: test_board.py's test_empty_board passes under python3 -m unittest
2. Add plant(row, variety) and a test that a second planting in one row is refused.
   team: redteam
   why: the row rule is where a mistake would cost a season
   done when: test_board.py's test_one_planting_per_row passes
3. Research which bean varieties suit a north-facing bed, with sources.
   team: research-build
   why: a research step: it changes no code
   done when: the result names three varieties, each with a source

## Needs from you
- decision: Bush beans or climbing beans first? (step 2)
- test command: python3 -m unittest"""
COMPOST_PLAN = """## Steps
1. Make the skeleton: compost.py that prints the bins, and test_compost.py with one test that passes.
   team: route
   why: the smallest thing that runs
   done when: test_compost.py's test_bins passes under python3 -m unittest
2. Add turn(bin) that records a turning date, with a test.
   team: route
   why: the one thing the volunteers asked for
   done when: test_compost.py's test_turn passes, checking the date is kept

## Needs from you
none"""
HERB_ONE_STEP = ("## One step\nA one-line docstring is one small change, not a plan.\ntask: Add a one-line docstring to "
                 "label_text() in labels.py.\nteam: route")
PLAN_ATTACKS_A = ("## Attacks\n1. [high] Step 2's finish line names no file for its test.\n2. [medium] Nothing says where "
                  "the board is kept between runs.\n3. [low] Step 3 could come first.\n\n## Strongest\nStep 2's test file.")
PLAN_ATTACKS_B = ("## Attacks\n1. [medium] The skeleton's test only proves it starts.\n2. [low] Research-build may be more "
                  "than step 3 needs.\n3. [low] The decision has no deadline.\n\n## Strongest\nThe thin first test.")
PLAN_ANSWERED = "\n\n## Answered\nA3: research first would leave the board untested.\nB2: the sources matter here."
PLAN_SLOTS = {"build": "claude", "attack": "chatgpt", "attack2": "cursor", "check": "chatgpt"}

# Brief 34 (decision 16): the three Auto projects' plans: a run two steps in (seed-swap), a run stopped at its budget,
# started at step 2 after step 1 was built by hand (trellis-plan), and a finished run waiting to land (mulch-notes).
SWAP_PLAN = """## Steps
1. Make the skeleton: swap.py that prints a help line, and test_swap.py with one test that runs it.
   team: route
   why: the smallest thing that runs, so each later step has a test to stand on
   done when: test_swap.py's test_help passes under python3 -m unittest
2. Add offer(packet, grower) that records an offer in swaps.json, with a test.
   team: route
   why: every later step reads the offers
   done when: test_swap.py's test_offer passes, checking an offer is read back
3. Match offers to wants and print the swaps, with a test that fakes two growers.
   team: redteam
   why: the matching is the part most likely to be wrong, so it gets attacked
   done when: test_match.py's test_two_growers passes with faked offers
4. Write the README: how to offer a packet and read the matches.
   team: route
   why: the growers need it
   done when: README.md names both commands and the test command

## Needs from you
- test command: python3 -m unittest"""
TRELLIS_PLAN = """## Steps
1. Make the skeleton: trellis.py that prints a help line, and test_trellis.py with one test that runs it.
   team: route
   why: the smallest thing that runs, so each later step has a test to stand on
   done when: test_trellis.py's test_help passes under python3 -m unittest
2. Add a bed's trellis plan from its climbers, with a test for beans and peas.
   team: redteam
   why: the spacing rule is the part most likely to be wrong, so it gets attacked
   done when: test_trellis.py's test_beans_and_peas passes
3. Write the README: how to plan a bed's trellis.
   team: route
   why: the volunteers need it
   done when: README.md names the command and the test command

## Needs from you
- test command: python3 -m unittest"""
MULCH_PLAN = """## Steps
1. Make the skeleton: mulch.py that prints a help line, and test_mulch.py with one test that runs it.
   team: route
   why: the smallest thing that runs, so the next step has a test to stand on
   done when: test_mulch.py's test_help passes under python3 -m unittest
2. Add note(bed, depth) that records a mulch note in mulch.json, with a test.
   team: route
   why: the one thing the notes are for
   done when: test_mulch.py's test_note passes, checking a note is read back

## Needs from you
- test command: python3 -m unittest"""
AUTO_PROJECTS = ("seed-swap", "trellis-plan", "mulch-notes")



def _plan_row(w, minute, name, text, plan_text, *, state, commit=None, spec_text=None):
    """A plan task as the router keeps it: its rows (the plan, both attacks, the revise, the check), the plan on the row,
    and its file record (waiting to land, or landed). The demo reaches no git, so the rows are written as the router writes
    them, never by a command."""
    w.frozen.at(minute)
    task_id = w.next_id()
    found = plan.menu(LOADED, ROSTER, None, send_paths=tuple(cli.SENDERS))
    record = plan.new_record(plan.menu_names(found))
    record["menu_text"] = plan.menu_block(found)
    record["test_command_then"] = shlex.join(projects.tests_of(name)) if projects.tests_of(name) else None
    if spec_text is not None:  # brief 33.2 (decision 21): the plan read the project's SPEC.md, so its steps carry covers
        parsed_spec = spec.parse(spec_text)
        record["spec_hash"] = spec.digest(spec_text)
        record["spec"] = {"examples": list(parsed_spec.examples), "done_when": list(parsed_spec.done_when)}
    log.add_task(w.conn, task_id, text, "ui", {"status": "not_asked", "tokens": 0}, mode="plan", preset="redteam",
                 slots=dict(PLAN_SLOTS), project=name, plan=record)
    log.set_route(w.conn, task_id, agents=ROSTER.names, agent="claude", route_reason=None, checker="chatgpt",
                  check_state="pending")
    revised = plan_text + PLAN_ANSWERED
    for call_id, agent, n, role, body in ((f"{task_id}-s1", "claude", 1, "plan", plan_text),
                                          (f"{task_id}-s2", "chatgpt", 2, "attack", PLAN_ATTACKS_A),
                                          (f"{task_id}-s3", "cursor", 3, "attack", PLAN_ATTACKS_B),
                                          (f"{task_id}-s4", "claude", 4, "revise", revised)):
        log.add_call(w.conn, call_id, task_id, "stage", agent, status="done", text=body, stage=n, role=role)
    log.add_call(w.conn, f"{task_id}-c1", task_id, "check", "chatgpt", status="done", text="PASS\n1. [note] The decision "
                 "could name who makes it.", verdict="PASS")
    log.set_done(w.conn, task_id, plan_text, check_state="passed")
    parsed, missing = plan.read(plan_text, record["menu"], one_step=False, examples=plan.example_labels(record))
    assert not missing, missing
    record = plan.with_plan(record, parsed)
    row = log.get_task(w.conn, task_id)
    text_md = plan.render(record, n=row["n"], date=plan.date_of(row))
    record["hash"] = plan.digest(text_md)
    if state == "landed":
        record["writes"] = [{"blob": f"{commit}0" * 4, "commit": commit, "task_id": task_id, "kind": "land"}]
    log.set_plan(w.conn, task_id, record)
    log.set_project_files(w.conn, task_id, {
        "mode": "on", "state": state, "copy": state == "waiting", "base": "9c4e2b7a1d3f5b8e0c2a4d6f8b1e3a5c7d9f0b2e",
        "branch": "main", "files": 3, "left_out": [],
        "changed": [{"path": plan.FILE, "status": "added", "plus": text_md.count("\n"), "minus": 0}],
        "diff": None, "latest": "after-plan-md-1", "tests": {"exit": None, "summary": None, "output": None, "command": None,
                                                            "outcome": "not_run", "why": plan.NO_TESTS},
        "commit": commit, "undo_commit": None, "why": None})
    return log.get_task(w.conn, task_id)


RAIN_PLAN = """## Steps
1. Make the skeleton: gauge.py that prints a help line, and test_gauge.py with one test that runs it.
   team: route
   why: the smallest thing that runs
   done when: test_gauge.py's test_help passes under python3 -m unittest
2. Add record(mm, date) that stores a reading in gauge.json, with a test.
   team: route
   why: every later step reads the readings
   done when: test_gauge.py's test_record passes, checking a reading is read back
3. Add a weekly total and a README that says how to run the tests.
   team: route
   why: what the allotment wants to see
   done when: test_gauge.py's test_weekly passes; README.md names the test command

## Needs from you
none"""
RAIN_REVISION = """## Steps
2. Add record(mm, date, bed) that stores a reading per bed in gauge.json, with a test.
   team: route
   why: the idea asks for a reading per bed, so the store takes the bed from here on
   done when: test_gauge.py's test_record passes, checking a reading is read back for its bed
3. Add a weekly total per bed, with a test.
   team: route
   why: the total follows the store
   done when: test_gauge.py's test_weekly passes for two beds
4. Write the README: how to record a reading and read the weekly totals.
   team: route
   why: what the allotment needs
   done when: README.md names both commands and the test command

## Needs from you
none

## Changed
step 2: it now takes the bed, as the idea asks
step 3: the weekly total is per bed, and the README moved to its own step"""


def _revision_row(w, minute, old_row, text, rev_text, *, idea=None):
    """Brief 33.2 (decision 11): a revision of a landed plan with one step done, waiting for approval: the record carries
    `revises`, `inherited` and the done step byte for byte; the planner's `## Changed`; docs/PLAN.md rendered with the
    inherited tick."""
    w.frozen.at(minute)
    task_id = w.next_id()
    name = log.project_of(old_row)
    found = plan.menu(LOADED, ROSTER, None, send_paths=tuple(cli.SENDERS))
    record = plan.new_record(plan.menu_names(found))
    record["menu_text"] = plan.menu_block(found)
    old_record = plan.record_of(old_row)
    d = plan.first_open(w.conn, old_row)[0] - 1
    record.update(revises=old_row["task_id"], revises_n=old_row["n"], inherited=d,
                  done_steps=plan.inherited_steps(old_record, d, []))
    log.add_task(w.conn, task_id, text, "ui", {"status": "not_asked", "tokens": 0}, mode="plan", preset="redteam",
                 slots=dict(PLAN_SLOTS), project=name, plan=record, idea=idea)
    log.set_route(w.conn, task_id, agents=ROSTER.names, agent="claude", route_reason=None, checker="chatgpt",
                  check_state="pending")
    revised = rev_text + PLAN_ANSWERED
    for call_id, agent, n, role, body in ((f"{task_id}-s1", "claude", 1, "plan", rev_text),
                                          (f"{task_id}-s2", "chatgpt", 2, "attack", PLAN_ATTACKS_A),
                                          (f"{task_id}-s3", "cursor", 3, "attack", PLAN_ATTACKS_B),
                                          (f"{task_id}-s4", "claude", 4, "revise", revised)):
        log.add_call(w.conn, call_id, task_id, "stage", agent, status="done", text=body, stage=n, role=role)
    log.add_call(w.conn, f"{task_id}-c1", task_id, "check", "chatgpt", status="done", text="PASS\n1. [note] Step 4 could "
                 "name the README's sections.", verdict="PASS")
    log.set_done(w.conn, task_id, rev_text, check_state="passed")
    parsed, missing = plan.read(rev_text, record["menu"], one_step=False, revision=d)
    assert not missing, missing
    record = plan.with_plan(record, parsed)
    row = log.get_task(w.conn, task_id)
    text_md = plan.render(record, n=row["n"], date=plan.date_of(row), ticks=plan.tick_numbers(plan.ticks(w.conn, row)))
    record["hash"] = plan.digest(text_md)
    log.set_plan(w.conn, task_id, record)
    log.set_project_files(w.conn, task_id, {
        "mode": "on", "state": "waiting", "copy": True, "base": "7b1d3f5a9c2e4b6d8f0a2c4e6b8d0f2a4c6e8b0d",
        "branch": "main", "files": 4, "left_out": [],
        "changed": [{"path": plan.FILE, "status": "changed", "plus": 9, "minus": 6}],
        "diff": None, "latest": "after-plan-md-1", "tests": {"exit": None, "summary": None, "output": None, "command": None,
                                                            "outcome": "not_run", "why": plan.NO_TESTS},
        "commit": None, "undo_commit": None, "why": None})
    return log.get_task(w.conn, task_id)


def _step_row(w, minute, plan_row, k, result):
    """A step of a landed plan, landed: the routed task its Build step chip sent, checked, with its tick."""
    step = plan.steps_of(plan.record_of(plan_row))[k - 1]
    w.frozen.at(minute)
    task_id = w.next_id()
    log.add_task(w.conn, task_id, step["text"], "ui", jev("code", 0.93), project=log.project_of(plan_row),
                 plan_step={"plan": plan_row["task_id"], "step": k})
    log.set_route(w.conn, task_id, agents=ROSTER.names, agent="claude", route_reason="best", skill="code",
                  skill_source="jev", checker="chatgpt", check_state="pending")
    handoff = "Pea trial notes.\n\nThe router writes below this line."  # the handoff as it rode on the call
    log.add_call(w.conn, task_id, task_id, "do", "claude", status="done", text=result,
                 context={"project": log.project_of(plan_row), "lines": 3, "total": 3, "text": handoff})
    log.add_call(w.conn, f"{task_id}-c1", task_id, "check", "chatgpt", status="done", text="PASS", verdict="PASS")
    log.set_done(w.conn, task_id, result.split("\n\n## Handoff")[0], check_state="passed")
    commit = f"{k}b7c9d1e3f5a7b9c1d3e5f7a9b1c3d5e7f9a1b3c{k}"
    log.set_project_files(w.conn, task_id, {
        "mode": "on", "state": "landed", "copy": False, "base": "9c4e2b7a1d3f5b8e0c2a4d6f8b1e3a5c7d9f0b2e",
        "branch": "main", "files": 4, "left_out": [], "changed": [{"path": "trial.py", "status": "changed", "plus": 6,
                                                                     "minus": 0}],
        "diff": None, "latest": f"after-{task_id}", "tests": {"exit": 0, "summary": "OK", "output": None,
                                                            "command": ["python3", "-m", "unittest"], "outcome": "passed"},
        "commit": commit, "undo_commit": None, "why": None,
        "plan_md": {"state": "written", "why": None, "kind": "land"}})
    plan.add_write(w.conn, log.get_task(w.conn, plan_row["task_id"]), blob=f"{k}{commit[:39]}", commit=commit,
                   task_id=task_id, kind="land")
    return log.get_task(w.conn, task_id)


STEP_DONE = "Done.\n\n## Handoff\n### Produced\n{files}\n### Status\n{status}\n### Next\n{next}"


PEA_SPEC = """# Pea trial

A sowing log for the pea beds: which variety went in where, and when it came up.

## Examples

1. `record("Kelvedon Wonder", bed=2)` adds a sowing dated today
2. `sowings(bed=2)` lists that bed's sowings, newest first
3. `frost_warning(forecast)` names a sowing that falls in a frost window

## Done when

- every example above has a passing test
- README.md says how to run the tests
"""


def _plans(w):
    """Brief 33.1 (decision 21): pea-trial two steps in, bean-board's plan waiting for approval, herb-labels' One step,
    compost-log's finished plan (its What now? reads the finish line)."""
    tmp = w.tmp
    for name in ("pea-trial", "bean-board", "herb-labels", "compost-log", "rain-gauge"):
        folder = tmp / "Projects" / name
        folder.mkdir(parents=True)
        projects.add(name, folder)
    projects.set_tests("pea-trial", ["python3", "-m", "unittest"])
    projects.set_tests("compost-log", ["python3", "-m", "unittest"])
    projects.set_tests("rain-gauge", ["python3", "-m", "unittest"])
    (tmp / "Projects" / "pea-trial" / "SPEC.md").write_text(PEA_SPEC, encoding="utf-8")  # brief 33.2 (decision 21)
    pea = _plan_row(w, 146.2, "pea-trial", "Plan the first version.", PEA_PLAN, state="landed",
                    commit="3a5c7e9b1d3f5a7c9e1b3d5f7a9c1e3b5d7f9a1c", spec_text=PEA_SPEC)
    _step_row(w, 146.25, pea, 1, STEP_DONE.format(files="trial.py and test_trial.py added", status="test_help passes",
                                                  next="Record a sowing."))
    _step_row(w, 146.3, pea, 2, STEP_DONE.format(files="trial.py and test_trial.py changed",
                                                 status="test_record_sowing passes", next="The frost warnings."))
    _plan_row(w, 146.4, "bean-board", "Plan the first version.", BEAN_PLAN, state="waiting")
    w.frozen.at(146.5)
    task_id = w.next_id()
    found = plan.menu(LOADED, ROSTER, None, send_paths=tuple(cli.SENDERS))
    record = plan.new_record(plan.menu_names(found))
    record["menu_text"] = plan.menu_block(found)
    log.add_task(w.conn, task_id, "Add a one-line docstring to labels.py.", "ui", {"status": "not_asked", "tokens": 0},
                 mode="plan", preset="redteam", slots=dict(PLAN_SLOTS), project="herb-labels", plan=record)
    log.set_route(w.conn, task_id, agents=ROSTER.names, agent="claude", route_reason=None, checker="chatgpt",
                  check_state="pending")
    log.add_call(w.conn, f"{task_id}-s1", task_id, "stage", "claude", status="done", text=HERB_ONE_STEP, stage=1,
                 role="plan")
    log.set_failed(w.conn, task_id, plan.ONE_STEP_REASON + "A one-line docstring is one small change, not a plan.",
                   failed_stage=1)
    compost = _plan_row(w, 146.6, "compost-log", "Plan the first version.", COMPOST_PLAN, state="landed",
                        commit="5d7f9b1c3e5a7d9f1b3c5e7a9d1f3b5c7e9a1d3f")
    _step_row(w, 146.65, compost, 1, STEP_DONE.format(files="compost.py and test_compost.py added",
                                                      status="test_bins passes", next="Record a turning."))
    _step_row(w, 146.7, compost, 2, STEP_DONE.format(files="compost.py and test_compost.py changed",
                                                     status="test_turn passes", next="Write the README."))
    # brief 33.2 (decision 21): rain-gauge's plan one step in, then a revision from an idea, waiting for approval
    rain = _plan_row(w, 146.8, "rain-gauge", "Plan the first version.", RAIN_PLAN, state="landed",
                     commit="7b1d3f5a9c2e4b6d8f0a2c4e6b8d0f2a4c6e8b0d")
    _step_row(w, 146.85, rain, 1, STEP_DONE.format(files="gauge.py and test_gauge.py added", status="test_help passes",
                                                   next="Record a reading."))
    found, _ = ideas.add(w.conn, "rain-gauge", "Record a reading per bed, not one for the whole plot.", now=w.frozen.now)
    _revision_row(w, 146.9, rain, "Record a reading per bed, not one for the whole plot.", RAIN_REVISION, idea=found.id)


def _run_row(w, minute, plan_row, *, from_step, estimate, changed):
    """A run as the router makes it at `--on`: the run row (`mode` auto, its record), its copy's record."""
    from router import auto
    w.frozen.at(minute)
    run_id = w.next_id()
    steps = plan.steps_of(plan.record_of(plan_row))
    record = auto.new_record(plan_row, steps, from_step=from_step, budget=auto.budget_for(estimate["max_calls"]), estimate=estimate)
    name = log.project_of(plan_row)
    log.add_task(w.conn, run_id, f"Auto: plan #{plan_row['n']}, steps {from_step} to {len(steps)}", "ui",
                 {"status": "not_asked", "tokens": 0}, mode="auto", project=name, auto=record)
    log.set_project_files(w.conn, run_id, {
        "mode": "on", "state": "none", "copy": True, "base": DEMO_FILES_VIEWS[name]["head"] + "0" * 33, "branch": "main",
        "files": 4, "left_out": [], "changed": changed, "diff": None, "latest": None, "tests": None, "commit": None,
        "undo_commit": None, "why": None})
    return log.get_task(w.conn, run_id), record


TRELLIS_ATTACKS_A = ("## Attacks\n1. [high] Peas climb a net, beans a pole: one spacing rule can't fit both.\n2. [medium] "
                     "Nothing says what a bed with no climbers prints.\n\n## Strongest\nThe one spacing rule.")
TRELLIS_ATTACKS_B = ("## Attacks\n1. [medium] The test names beans and peas but checks beans alone.\n2. [low] The plan's "
                     "words say 'trellis' where the volunteers say 'frame'.\n\n## Strongest\nThe one-crop test.")
TRELLIS_ANSWERED = "\n\n## Answered\nB2: the volunteers' word is kept in the README, not the code."


def _demo_tests(outcome, k):
    """A step's test run as the router records it on the call row (brief 33.2, decision 16: the run's card sums them)."""
    return {"exit": 0 if outcome == "passed" else 1, "outcome": outcome, "summary": "OK" if outcome == "passed" else "FAILED (failures=1)",
            "output": f"tests-{k}.txt", "command": ["python3", "-m", "unittest"]}


def _run_step_row(w, minute, run_row, plan_row, k, result, *, changed, calls=(("do", "claude"), ("check", "chatgpt")),
                  state="done", attempt=1, tests=()):
    """A step of a run, as the loop makes one: the run's step (its parent), in the run's copy from its snapshot; done with
    its calls, or queued while it runs. `calls` names the rows an attempt wrote (kind, agent), the check last."""
    from router import filecalls
    step = plan.steps_of(plan.record_of(plan_row))[k - 1]
    w.frozen.at(minute)
    task_id = w.next_id()
    routed = step.get("team") in (None, "route")
    log.add_task(w.conn, task_id, step["text"], "ui", jev("code", 0.93) if routed else {"status": "not_asked", "tokens": 0},
                 project=log.project_of(plan_row), parent=run_row["task_id"], plan_step={"plan": plan_row["task_id"], "step": k},
                 mode="route" if routed else "relay", preset=None if routed else step.get("team"),
                 slots=dict(PLAN_SLOTS) if step.get("team") == "redteam" else None)
    log.set_route(w.conn, task_id, agents=ROSTER.names, agent="claude", route_reason="best" if routed else None,
                  skill="code" if routed else None, skill_source="jev" if routed else None, checker="chatgpt", check_state="pending")
    record = {**filecalls.piece_record(run_row["task_id"], k, log.project_files_of(run_row)),
              "start": f"step-{k}-{attempt}-start", "run": run_row["task_id"]}
    if state in ("done", "failed"):
        handoff = "Notes.\n\nThe router writes below this line."
        stage = 0
        for i, (kind, agent, *role) in enumerate(calls):
            if kind == "stage":
                stage += 1
                call_id = f"{task_id}-s{stage}"
            elif kind == "do":
                call_id = task_id
            else:
                call_id = f"{task_id}-{kind[0]}{i}"
            verdict = ("PASS" if state == "done" else "FIX") if kind in ("check", "recheck") else None
            text = (verdict + ("\n1. [must] test_beans_and_peas doesn't cover peas." if verdict == "FIX" else "")) if verdict else result
            if kind == "stage":  # a redteam step's attack lists and its revise, so the card's board has rows
                text = {"attack": TRELLIS_ATTACKS_A, "attack2": TRELLIS_ATTACKS_B, "revise": result + TRELLIS_ANSWERED}.get(role[0] if role else "", result)
            ran = list(tests)[sum(1 for kind_, *_ in list(calls)[:i] if kind_ in ("do", "fix"))] if kind in ("do", "fix") and tests else None
            log.add_call(w.conn, call_id, task_id, kind, agent, status="done", text=text, verdict=verdict,
                         stage=stage if kind == "stage" else None, role=role[0] if role else None,
                         tests=ran,  # brief 33.2 (decision 16): each build and fix call's test run, summed on the run's card
                         context={"project": log.project_of(plan_row), "lines": 2, "total": 2, "text": handoff} if i == 0 else None)
        if state == "done":
            log.set_done(w.conn, task_id, result.split("\n\n## Handoff")[0], check_state="passed")
        else:  # as the loop ends a check that failed twice (checking.py's finish step)
            log.set_done(w.conn, task_id, result.split("\n\n## Handoff")[0], check_state="failed",
                         check_note="not passed after one fix round")
        record.update(changed=changed, latest=f"after-{task_id}",
                      tests={"exit": 0 if state == "done" else 1, "summary": "OK" if state == "done" else "FAILED (failures=1)",
                             "output": None, "command": ["python3", "-m", "unittest"],
                             "outcome": "passed" if state == "done" else "failed"})
    log.set_project_files(w.conn, task_id, record)
    return log.get_task(w.conn, task_id)


REDTEAM_ATTEMPT = (("stage", "claude", "build"), ("stage", "chatgpt", "attack"), ("stage", "cursor", "attack2"),
                   ("stage", "claude", "revise"), ("check", "chatgpt"), ("fix", "claude"), ("recheck", "chatgpt"))


def _autos(w):
    """Brief 34 (decision 16): seed-swap's run two steps in (step 3 running), trellis-plan's run stopped at its budget
    (started at step 2, which passed on its retry; the two attempts used the budget up before step 3), mulch-notes'
    finished run waiting to land. Every row as the router writes it; nothing runs."""
    from router import auto
    tmp = w.tmp
    for name in AUTO_PROJECTS:
        folder = tmp / "Projects" / name
        folder.mkdir(parents=True)
        projects.add(name, folder)
        projects.set_tests(name, ["python3", "-m", "unittest"])
    # seed-swap: a run two steps in, step 3 (redteam) running
    swap = _plan_row(w, 147.0, "seed-swap", "Plan the first version.", SWAP_PLAN, state="landed",
                     commit="1a3c5e7b9d1f3a5c7e9b1d3f5a7c9e1b3d5f7a9c")
    run, record = _run_row(w, 147.1, swap, from_step=1, estimate={"calls": 11, "max_calls": 19, "jev_labels": 3},
                           changed=[{"path": "swap.py", "status": "added", "plus": 24, "minus": 0},
                                    {"path": "test_swap.py", "status": "added", "plus": 18, "minus": 0},
                                    {"path": "swaps.json", "status": "added", "plus": 1, "minus": 0}])
    s1 = _run_step_row(w, 147.15, run, swap, 1, STEP_DONE.format(files="swap.py and test_swap.py added", status="test_help passes",
                                                                  next="Record an offer."),
                       changed=[{"path": "swap.py", "status": "added", "plus": 9, "minus": 0}, {"path": "test_swap.py", "status": "added", "plus": 8, "minus": 0}])
    s2 = _run_step_row(w, 147.2, run, swap, 2, STEP_DONE.format(files="swap.py and test_swap.py changed, swaps.json added",
                                                                 status="test_offer passes", next="Match the offers."),
                       changed=[{"path": "swap.py", "status": "changed", "plus": 15, "minus": 0}, {"path": "test_swap.py", "status": "changed", "plus": 10, "minus": 0},
                                {"path": "swaps.json", "status": "added", "plus": 1, "minus": 0}])
    s3 = _run_step_row(w, 147.25, run, swap, 3, "", changed=[], state="running")
    for entry, row, state in ((auto.step_entry(record, 1), s1, "done"), (auto.step_entry(record, 2), s2, "done"), (auto.step_entry(record, 3), s3, "running")):
        entry.update(state=state, attempt=1, task_id=row["task_id"], calls=auto.used_calls(w.conn, run["task_id"]) if False else len(log.calls_for(w.conn, row["task_id"])),
                     outcome="passed" if state == "done" else None)
    record["used"] = auto.used_calls(w.conn, run["task_id"])
    log.set_auto(w.conn, run["task_id"], record)
    # trellis-plan: step 1 built by hand and landed; the run started at step 2, which took two attempts (its retry
    # passed), and reached its budget before step 3
    trellis = _plan_row(w, 147.3, "trellis-plan", "Plan the first version.", TRELLIS_PLAN, state="landed",
                        commit="2b4d6f8a0c2e4b6d8f0a2c4e6b8d0f2a4c6e8b0d")
    _step_row(w, 147.35, trellis, 1, STEP_DONE.format(files="trellis.py and test_trellis.py added", status="test_help passes",
                                                      next="The bed's plan."))
    run, record = _run_row(w, 147.4, trellis, from_step=2, estimate={"calls": 7, "max_calls": 11, "jev_labels": 1},
                           changed=[{"path": "trellis.py", "status": "changed", "plus": 31, "minus": 2},
                                    {"path": "test_trellis.py", "status": "changed", "plus": 14, "minus": 0}])
    first = _run_step_row(w, 147.45, run, trellis, 2, STEP_DONE.format(files="trellis.py and test_trellis.py changed",
                                                                        status="test_beans_and_peas fails on peas", next="Fix the spacing."),
                          changed=[{"path": "trellis.py", "status": "changed", "plus": 20, "minus": 2}], calls=REDTEAM_ATTEMPT + (("fix", "claude"), ("recheck", "chatgpt")),
                          state="failed", attempt=1)
    second = _run_step_row(w, 147.5, run, trellis, 2, STEP_DONE.format(files="trellis.py and test_trellis.py changed",
                                                                         status="test_beans_and_peas passes", next="Write the README."),
                           changed=[{"path": "trellis.py", "status": "changed", "plus": 31, "minus": 2}, {"path": "test_trellis.py", "status": "changed", "plus": 14, "minus": 0}],
                           calls=REDTEAM_ATTEMPT + (("fix", "claude"),), state="done", attempt=2)
    auto.step_entry(record, 2).update(state="done", attempt=2, task_id=second["task_id"], calls=len(log.calls_for(w.conn, second["task_id"])), outcome="passed")
    used = auto.used_calls(w.conn, run["task_id"])
    record["used"] = used
    why = f"the budget is reached: {auto.budget_words(record, used)} used"
    log.set_auto(w.conn, run["task_id"], auto.with_stop(record, "budget", why, step=3))
    log.set_returned(w.conn, run["task_id"], f"returned: {why}", reason_code="budget")
    cli._auto_note(w.conn, run["task_id"], f"{auto.STOP_NOTE}{why}")
    # mulch-notes: a finished run waiting to land
    mulch = _plan_row(w, 147.6, "mulch-notes", "Plan the first version.", MULCH_PLAN, state="landed",
                      commit="3c5e7a9b1d3f5a7c9e1b3d5f7a9c1e3b5d7f9a1b")
    run, record = _run_row(w, 147.65, mulch, from_step=1, estimate={"calls": 4, "max_calls": 8, "jev_labels": 2},
                           changed=[{"path": "mulch.py", "status": "added", "plus": 22, "minus": 0},
                                    {"path": "test_mulch.py", "status": "added", "plus": 16, "minus": 0},
                                    {"path": "mulch.json", "status": "added", "plus": 1, "minus": 0}])
    m1 = _run_step_row(w, 147.7, run, mulch, 1, STEP_DONE.format(files="mulch.py and test_mulch.py added", status="test_help passes", next="Record a note."),
                       changed=[{"path": "mulch.py", "status": "added", "plus": 9, "minus": 0}, {"path": "test_mulch.py", "status": "added", "plus": 8, "minus": 0}],
                       tests=[_demo_tests("passed", 1)])
    m2 = _run_step_row(w, 147.75, run, mulch, 2, STEP_DONE.format(files="mulch.py and test_mulch.py changed, mulch.json added",
                                                                   status="test_note passes", next="Write the README."),
                       changed=[{"path": "mulch.py", "status": "changed", "plus": 13, "minus": 0}, {"path": "test_mulch.py", "status": "changed", "plus": 8, "minus": 0},
                                {"path": "mulch.json", "status": "added", "plus": 1, "minus": 0}], calls=(("do", "claude"), ("check", "chatgpt"), ("fix", "claude"), ("recheck", "chatgpt")),
                       tests=[_demo_tests("failed", 1), _demo_tests("passed", 2)])
    for entry, row in ((auto.step_entry(record, 1), m1), (auto.step_entry(record, 2), m2)):
        entry.update(state="done", attempt=1, task_id=row["task_id"], calls=len(log.calls_for(w.conn, row["task_id"])), outcome="passed")
    record["used"] = auto.used_calls(w.conn, run["task_id"])
    log.set_auto(w.conn, run["task_id"], record)
    folder = tmp / "tasks" / run["task_id"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "changes.diff").write_text(MULCH_DIFF, encoding="utf-8")
    (folder / "tests-1.txt").write_text(PASSING_TESTS, encoding="utf-8")
    log.update_project_files(w.conn, run["task_id"], state="waiting", diff=f"tasks/{run['task_id']}/changes.diff", latest="end",
                             tests={"outcome": "passed", "exit": 0, "summary": "OK", "output": f"tasks/{run['task_id']}/tests-1.txt",
                                    "command": ["python3", "-m", "unittest"]})
    log.set_done(w.conn, run["task_id"], "Auto finished: every step passed; the run waits to land.", check_state="passed")
    cli._auto_note(w.conn, run["task_id"], auto.FINISHED_NOTE)


MULCH_DIFF = """diff --git a/mulch.py b/mulch.py
new file mode 100644
--- /dev/null
+++ b/mulch.py
@@ -0,0 +1,22 @@
+\"\"\"Mulch notes: a note per bed, with its depth.\"\"\"
+import json
+import sys
+
+NOTES = "mulch.json"
+
+
+def note(bed, depth):
+    found = json.load(open(NOTES)) if __import__("os").path.exists(NOTES) else []
+    found.append({"bed": bed, "depth": depth})
+    json.dump(found, open(NOTES, "w"))
+    return found
+
+
+if __name__ == "__main__":
+    if "--help" in sys.argv:
+        print("mulch.py: note(bed, depth) records a mulch note")
+    else:
+        print(note(sys.argv[1], int(sys.argv[2])))
diff --git a/test_mulch.py b/test_mulch.py
new file mode 100644
--- /dev/null
+++ b/test_mulch.py
@@ -0,0 +1,16 @@
+import unittest
+
+import mulch
+
+
+class Notes(unittest.TestCase):
+    def test_help(self):
+        self.assertTrue(mulch.__doc__.startswith("Mulch notes"))
+
+    def test_note(self):
+        self.assertEqual(mulch.note("north", 5)[-1], {"bed": "north", "depth": 5})
"""


def _file_mode(w, row, *, state, changed, diff, tests_out, outcome, exit_code, summary, commit=None, copy=True):
    """Brief 28: a demo task's project files record, its diff and its test run, written as the router keeps them."""
    task_id = row["task_id"]
    folder = w.tmp / "tasks" / task_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "changes.diff").write_text(diff, encoding="utf-8")
    (folder / "tests-1.txt").write_text(tests_out, encoding="utf-8")
    tests = {"outcome": outcome, "exit": exit_code, "summary": summary, "output": f"tasks/{task_id}/tests-1.txt",
             "command": ["python3", "-m", "unittest"]}
    do = next(c for c in log.calls_for(w.conn, task_id) if c["kind"] == "do")
    log.set_call_tests(w.conn, do["call_id"], tests)
    log.set_project_files(w.conn, task_id, {
        "mode": "on", "state": state, "copy": copy, "base": "4f2a9c1e5b7d3a8f6c0e2b4d6f8a1c3e5b7d9f0a", "branch": "main",
        "files": 12, "left_out": [], "changed": changed, "diff": f"tasks/{task_id}/changes.diff",
        "latest": f"after-{do['call_id']}", "tests": tests, "commit": commit, "undo_commit": None, "why": None})


HANDOFF_RESULT = ("Lending rules\n\n- Take up to five packets a month.\n- Bring back seeds from what you grow.\n\n"
                  "## Handoff\n### Produced\nnothing written: Lending rules, the seed library's two rules in a list.\n"
                  "### Status\nThe README has its lending section.\n### Next\nAdd the opening hours.\n"
                  "Add a map of the seed shelves.")
# Brief 29 (decision 5): under each piece the planner writes its team and a one-line why.
PLAN_TWO = ("## Pieces\n1. List three winter vegetables for a small garden.\nteam: route\nwhy: A short list a writer can "
            "check.\n2. Write a haiku about frost.\nteam: route\nwhy: One short poem.\n\n"
            "## Join\nPut the list above the haiku.")


# Brief 29 (decision 19): split on the page. A plan with three teams, one changed by the owner; a split whose versus piece
# waits for its pick; a project split waiting to land with its two pieces' parts; a No split answer. Every text is
# invented, in the garden's words. The two-piece plan of #15 stays (it shows the skill picker), so no earlier id moves.
PLAN = ("## Pieces\n1. Write a one-page FAQ for the seed library.\nteam: route\nwhy: One writer and a checker are enough.\n"
        "2. Draft a short email announcing the seed library.\nteam: route\nwhy: A short email; the skill table's writer.\n\n"
        "## Join\nPut the email first, then the FAQ.")
PLAN_TEAMS = (
    "## Pieces\n1. Write a 100-word note on why the garden rotates its crops, for new members.\nteam: route\n"
    "why: One short piece of writing: the skill table's writer is enough.\n"
    "2. Decide whether the seed library should keep its loan records in a spreadsheet or a paper notebook, with one line "
    "why.\nteam: vote\nwhy: A judgment call: three answers made on their own settle it.\n"
    "3. Find what a 50-gallon rain barrel costs at garden centers this year, with sources.\nteam: research-build\n"
    "why: Needs this year's prices from the web before it is written up.\n\n"
    "## Join\nThe note, then the records pick with its reason, then the price range with its sources.")
PLAN_VERSUS = (
    "## Pieces\n1. Write a two-line welcome sign for the tool shed.\nteam: route\nwhy: One short piece of writing.\n"
    "2. Decide whether the seed library should open on Saturday mornings or Sunday afternoons, with one line why.\n"
    "team: versus\nwhy: Two takes made on their own, then you pick one.\n\n"
    "## Join\nThe sign, then the opening time with its reason.")
SIGN = "Tools out, tools back.\nThe shed runs on trust and a little oil."
SATURDAY = "Saturday mornings: most members garden then, and the library sits by the beds."
SUNDAY = "Sunday afternoons: the shed is quiet and volunteers are free after the market."
SHED_REVIEW = "## Verdict\npass\n\n## Notes\n- Wrong: nothing.\n- Strong: one clear reason."
PLAN_PLOTS = (
    "## Pieces\n1. Fix the bug in bed_area() in beds.py so its test passes.\nteam: route\n"
    "why: A small fix a coder and a checker cover.\n"
    "2. Add rain_needed(beds) in a new file water.py, with a unittest test in test_water.py.\nteam: route\n"
    "why: A new function and its test, one piece.\n\n"
    "## Join\nBoth changes in the one copy, then the tests.")
PLOTS_JOINED = ("`bed_area()` now multiplies length by width, and its test passes. `rain_needed(beds)` is in the new "
                "`water.py`, with three cases in `test_water.py`. All 4 tests pass." + SEEDS_HANDOFF.format(
                    files="beds.py changed; water.py and test_water.py added", status="Beds have areas and a rain need.",
                    next="Show each bed's rain need on the plot map."))
PLOTS_DIFF = """diff --git a/beds.py b/beds.py
index 1b2c3d4..5e6f7a8 100644
--- a/beds.py
+++ b/beds.py
@@ -1,2 +1,4 @@
 def bed_area(length, width):
-    return length + width
+    \"\"\"The bed's area in square feet.\"\"\"
+    return length * width
+
diff --git a/water.py b/water.py
new file mode 100644
index 0000000..9a8b7c6
--- /dev/null
+++ b/water.py
@@ -0,0 +1,6 @@
+from beds import bed_area
+
+
+def rain_needed(beds):
+    \"\"\"Gallons a week for the beds, one per square foot.\"\"\"
+    return sum(bed_area(length, width) for length, width in beds)
"""
NO_SPLIT = "## No split\nEach part needs the one before it: the docstring and the example are written from the exact function."


VERSUS_HANDOFF = "\n\n## Handoff\n### Produced\nloans.py and test_loans.py changed\n### Status\n{status}\n### Next\nPick one."
VERSUS_A = ("lend() now checks the packet's stock first and raises OutOfStock; a test lends the last packet twice."
            + VERSUS_HANDOFF.format(status="lend() refuses an empty packet."))
VERSUS_B = ("lend() returns False for a packet with no stock left, and a test covers it."
            + VERSUS_HANDOFF.format(status="lend() says no to an empty packet."))
REVIEW_OF_B = "## Verdict\npass\n\n## Notes\n- Wrong: nothing.\n- Strong: no exception for the caller to catch."
REVIEW_OF_A = "## Verdict\npass\n\n## Notes\n- Wrong: nothing.\n- Strong: the error names the packet."
VERSUS_DIFF_A = """diff --git a/loans.py b/loans.py
--- a/loans.py
+++ b/loans.py
@@ -1,4 +1,9 @@
+class OutOfStock(Exception):
+    pass
+
+
 def lend(packet, member):
+    if packet.stock < 1:
+        raise OutOfStock(packet.name)
     packet.stock -= 1
     return member.loans.append(packet)
"""
VERSUS_DIFF_B = """diff --git a/loans.py b/loans.py
--- a/loans.py
+++ b/loans.py
@@ -1,3 +1,5 @@
 def lend(packet, member):
+    if packet.stock < 1:
+        return False
     packet.stock -= 1
     return member.loans.append(packet)
"""


def _versus_file_mode(w, row):
    """Brief 29.1 (decision 9): a demo versus task on a project before its pick, as the router keeps it: one copy per
    candidate, each with its change, its diff and its tests. The demo reaches no git, so the record is written here."""
    task_id = row["task_id"]
    folder = w.tmp / "tasks" / task_id
    folder.mkdir(parents=True, exist_ok=True)
    candidates = {}
    for slot, diff, plus in (("a", VERSUS_DIFF_A, 7), ("b", VERSUS_DIFF_B, 2)):
        (folder / f"changes-{slot}.diff").write_text(diff, encoding="utf-8")
        (folder / f"tests-{slot}.txt").write_text(PASSING_TESTS.replace("2 tests", "3 tests"), encoding="utf-8")
        tests = {"outcome": "passed", "exit": 0, "summary": "OK", "output": f"tasks/{task_id}/tests-{slot}.txt",
                 "command": ["python3", "-m", "unittest"]}
        candidates[slot] = {"copy_id": f"{task_id}-{slot}", "agent": "claude" if slot == "a" else "chatgpt", "copy": True,
                            "changed": [{"path": "loans.py", "status": "changed", "plus": plus, "minus": 0},
                                        {"path": "test_loans.py", "status": "changed", "plus": 6, "minus": 0}],
                            "diff": f"tasks/{task_id}/changes-{slot}.diff", "latest": None, "tests": tests, "files": 12,
                            "left_out": []}
    log.set_project_files(w.conn, task_id, {
        "mode": "on", "versus": True, "state": "none", "copy": True, "base": "4f2a9c1e5b7d3a8f6c0e2b4d6f8a1c3e5b7d9f0a",
        "branch": "main", "files": 12, "left_out": [], "candidates": candidates, "changed": [], "diff": None,
        "latest": None, "tests": None, "commit": None, "undo_commit": None, "why": None})


def _split_file_mode(w, row, pieces):
    """Brief 29 (decisions 13 and 15): a demo project split's records as the router keeps them: the split's whole change
    waiting to land, with its tests, and each piece's part of it, pointing at the split's one copy. The demo reaches no
    git, so they are written here (as _file_mode writes a task's)."""
    task_id = row["task_id"]
    folder = w.tmp / "tasks" / task_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "changes.diff").write_text(PLOTS_DIFF, encoding="utf-8")
    (folder / "tests-1.txt").write_text(PASSING_TESTS.replace("2 tests", "4 tests"), encoding="utf-8")
    tests = {"outcome": "passed", "exit": 0, "summary": "OK", "output": f"tasks/{task_id}/tests-1.txt",
             "command": ["python3", "-m", "unittest"]}
    join = next(c for c in log.calls_for(w.conn, task_id) if c["role"] == "integrate")
    log.set_call_tests(w.conn, join["call_id"], tests)
    whole = [change for _, part in pieces for change in part]
    log.set_project_files(w.conn, task_id, {
        "mode": "on", "state": "waiting", "copy": True, "base": "7d3e1a9c5b2f4d6e8a0c1e3f5b7d9a2c4e6f8b1d", "branch": "main",
        "files": 9, "left_out": [], "changed": sorted(whole, key=lambda c: c["path"]), "diff": f"tasks/{task_id}/changes.diff",
        "latest": f"after-{join['call_id']}", "tests": tests, "commit": None, "undo_commit": None, "why": None})
    for k, (piece, part) in enumerate(pieces, 1):
        log.set_project_files(w.conn, piece["task_id"], {
            "mode": "on", "owner": task_id, "start": f"piece-{k}-start", "state": "none", "copy": True,
            "base": "7d3e1a9c5b2f4d6e8a0c1e3f5b7d9a2c4e6f8b1d", "branch": "main", "changed": part, "diff": None,
            "latest": None, "tests": None, "commit": None, "undo_commit": None, "why": None})


def _seed_models(tmp):
    """Brief 33.3 (decisions 2 and 3): the shipped defaults into the demo's own local file, as `sr models set` writes them
    (the same ten commands the switch-over runs): code builds and file-mode changes on Opus, a plan's planning calls on
    Fable (off, so on Opus with the card saying so), quick answers on Sonnet."""
    for selector, model in ((("skill", "code"), "opus"), (("skill", "quick_answer"), "sonnet"),
                            *((("role", f"file.{role}"), "opus") for role in ("build", "revise", "execute", "fix", "integrate")),
                            *((("role", f"plan.{role}"), "fable") for role in ("plan", "revise", "fix"))):
        kind, key = selector
        chosen = {"skill": key} if kind == "skill" else {"team": key.split(".")[0], "role": key.split(".")[1]}
        models.set_default(chosen, "claude", model=model, lock_folder=tmp)


def build_log(w):
    tmp = w.tmp
    garden = "garden"
    # 1. passed (routed writing, a chat with memory)
    w.route(1, "Write a two-sentence welcome for the Maple Street community garden newsletter.", jev("writing"),
            worker=Scripted("Welcome to the Maple Street garden! Bring gloves, bring friends, and take home what you grow."),
            chat=garden, hindsight=w.hindsight)
    # 2. fixed
    w.route(6, "Draft a 40-word notice that the garden's tool shed now opens at 7 am.", jev("writing"),
            worker=Scripted("The tool shed now opens at 7 am.", "From Monday, the tool shed opens at 7 am on weekdays.\n\n"
                            "## Next\n- Write the same notice for the noticeboard by the gate."),  # brief 33: Suggested next
            chatgpt=Scripted("FIX\n1. [must] Say the 7 am opening is on weekdays only.", "PASS\n1. fixed"), chat=garden,
            hindsight=w.hindsight)
    # 3. failed its check twice: the fallback is offered
    w.route(11, "Write a Python function to_minutes(text) that turns '2h 15m' into 135, with three doctests.",
            jev("code", 0.97), worker=Scripted("def to_minutes(text):\n    return 0", "def to_minutes(text):\n    return 1"),
            chatgpt=Scripted("FIX\n1. [must] It returns 0 for every input.", "FIX\n1. not fixed: it still ignores the hours."))
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
    # 9. redteam, with both attackers' lists (brief 32, decision 19)
    w.relay(41, "redteam", "Plan how the bakery moves its pre-orders from a paper list to a shared spreadsheet.",
            worker=Scripted(BUILD, REVISION), chatgpt=Scripted(ATTACKS, "PASS"), cursor=CursorFake(B_ATTACKS),
            cursor_ready=lambda: cursor_worker.Readiness((True, None)))
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
               chatgpt=Scripted("FIX\n1. [must] A haiku has three lines.", "FIX\n1. not fixed: still not three lines."),
               labels=[jev("writing")])
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
    lending = w.route(96, "Write the README section that explains the seed library's lending rules.", jev("writing"),
                      worker=Scripted(HANDOFF_RESULT), project="garden-site")
    # brief 30 (decision 20): a pinned note in garden-site's notes (written with no commit: the project has no git), and a
    # saved file's entry in its block, as Save to project writes it on a project with git
    w.frozen.at(97)
    projnotes.pin(w.conn, "garden-site", log.get_task(w.conn, lending["task_id"]),
                  "Take up to five packets a month; bring back seeds from what you grow.", journal_dir=tmp / "journal",
                  lock_folder=None, date=f"{w.frozen.now:%Y-%m-%d}")
    projects.write_entry(folder, f"### {w.frozen.now:%Y-%m-%d} · saved: docs/lending-rules.md (from #{lending['n']})")
    # brief 33 (decisions 7, 14 and 20): garden-site's Ideas list: two added on its sheet, one moved from #20 with Later
    for text in ("Add a map of the raised beds.", "Print a planting calendar for the season."):
        ideas.add(w.conn, "garden-site", text, now=w.frozen.now)
    ideas.add(w.conn, "garden-site", "Add a map of the seed shelves.", source_task=lending["task_id"], now=w.frozen.now)
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
    # brief 28 (decision 21): project files. seed-library has git and a test command; garden-site (above) has no git
    seeds = tmp / "Projects" / "seed-library"
    seeds.mkdir(parents=True)
    projects.add("seed-library", seeds)
    projects.set_tests("seed-library", ["python3", "-m", "unittest"])
    # 31. a change that landed as one commit
    row = w.route(144.2, "Give each seed loan a due date four weeks out, with a test.", jev("code", 0.97),
                  worker=Scripted(LANDED_RESULT), project="seed-library")
    _file_mode(w, row, state="landed", changed=[{"path": "loans.py", "status": "changed", "plus": 4, "minus": 1},
                                                {"path": "test_loans.py", "status": "added", "plus": 8, "minus": 0}],
               diff=LANDED_DIFF, tests_out=PASSING_TESTS, outcome="passed", exit_code=0, summary="OK",
               commit="b7e4d2a9c1f3e5d7b9a1c3e5f7d9b1a3c5e7f9d1", copy=False)
    # 32. a change whose tests failed: its check failed twice, so it can't land (Discard drops its copy)
    row = w.route(144.6, "Show overdue loans first in the list.", jev("code", 0.96),
                  worker=Scripted(FAILING_RESULT, FAILING_RESULT),
                  chatgpt=Scripted("FIX\n1. [must] The tests fail: overdue loans come last, not first.",
                                   "FIX\n1. not fixed: test_overdue_first still expects kale first."), project="seed-library")
    _file_mode(w, row, state="none", changed=[{"path": "loans.py", "status": "changed", "plus": 1, "minus": 1}],
               diff=FAILING_DIFF, tests_out=FAILING_TESTS, outcome="failed", exit_code=1, summary="FAILED (failures=1)")
    # 33. a change waiting to land: Land or Discard, each behind the confirm
    row = w.route(145.0, "Count how many times each seed packet is lent, with a test.", jev("code", 0.97),
                  worker=Scripted(WAITING_RESULT), project="seed-library")
    _file_mode(w, row, state="waiting", changed=[{"path": "packets.py", "status": "changed", "plus": 4, "minus": 1},
                                                 {"path": "test_packets.py", "status": "added", "plus": 9, "minus": 0}],
               diff=WAITING_DIFF, tests_out=PASSING_TESTS, outcome="passed", exit_code=0, summary="OK")
    # 34. a split plan waiting with three teams (brief 29, decisions 7 and 8): the second changed by the owner from vote to
    # versus, and the router's call count
    plan = w.split(145.1, "Three separate things: a note on crop rotation for new members, how the seed library keeps its "
                          "loan records, and what a rain barrel costs this year.", planner=Scripted(PLAN_TEAMS),
                   labels=[jev("writing", 0.94), jev("quick_answer", 0.86), jev("web_research", 0.91)])
    w.split_edit(145.15, plan, 2, team="versus")
    w.split_edit(145.16, plan, 2, slots=["b=cursor"])  # brief 29.1 (decision 12): an agent per piece, Cursor building B
    # 35. a split whose versus piece waits for your pick (brief 29, decision 10): the route piece ran meanwhile
    shed = w.split(145.2, "Two things: a welcome sign for the tool shed, and when the seed library should open.",
                   planner=Scripted(PLAN_VERSUS), labels=[jev("writing", 0.95), jev("quick_answer", 0.88)])
    w.split_go(145.3, shed, worker=Scripted(SIGN, SATURDAY, SHED_REVIEW), chatgpt=Scripted("PASS", SUNDAY, SHED_REVIEW),
               labels=[])
    # 36. a project split waiting to land (decisions 13 to 15): two pieces built in one copy, each with its part, joined
    # and checked as one change
    plots = tmp / "Projects" / "plot-planner"
    plots.mkdir(parents=True)
    projects.add("plot-planner", plots)
    projects.set_tests("plot-planner", ["python3", "-m", "unittest"])
    planner = w.split(145.5, "In this project: fix the bug in bed_area() in beds.py so its test passes; separately, add "
                             "rain_needed(beds) in a new file water.py with a unittest test in test_water.py.",
                      planner=Scripted(PLAN_PLOTS), labels=[jev("code", 0.97), jev("code", 0.96)], project="plot-planner")
    w.split_go(145.6, planner, worker=Scripted("Fixed bed_area().", "Added water.py and its test.", PLOTS_JOINED),
               chatgpt=Scripted("PASS", "PASS", "PASS"), labels=[])
    one, two = log.pieces_of(w.conn, planner["task_id"])
    _split_file_mode(w, planner, [(one, [{"path": "beds.py", "status": "changed", "plus": 3, "minus": 1}]),
                                  (two, [{"path": "water.py", "status": "added", "plus": 6, "minus": 0},
                                         {"path": "test_water.py", "status": "added", "plus": 12, "minus": 0}])])
    # 37. No split (decision 3): an answer, with Route it
    w.split(145.8, "Write a Python function that parses a planting date, then write its docstring from the exact "
                   "function you wrote, then a usage example that calls it.", planner=Scripted(NO_SPLIT), labels=[])
    # brief 29.1 (decision 29): 38. a passed check with notes
    w.route(145.82, "Write a two-line sign for the compost bins.", jev("writing"),
            worker=Scripted("Greens and browns, a layer at a time.\nTurn me weekly and I turn it to soil."),
            chatgpt=Scripted("PASS\n1. [note] The second line could name the bins' colours.\n2. [note] A shorter first "
                             "line would fit the sign's width better."))
    # 39. Blocked: the doer needed what it wasn't given; no fix round
    w.route(145.84, "Write the follow-up email to the garden committee from Tuesday's meeting, using my notes from it.",
            jev("writing"), worker=Scripted("I can't write this yet: your notes from Tuesday's meeting weren't in the task."),
            chatgpt=Scripted("BLOCKED: the owner's notes from Tuesday's meeting"))
    # 40. a follow-up: a chat task Jev wasn't sure of (under 0.4), done by Claude with memory, checked by ChatGPT
    w.route(145.86, "and the same for the herb beds", jev("writing", 0.31, "below_floor"), chat=garden,
            hindsight=w.hindsight, worker=Scripted("Herb beds: water at dawn, and cut chives and mint back by a third "
                                                   "in June.\n\n## Next\n- Make a watering chart for the herb beds.\n"
                                                   "- Write the same tips for the tomato beds."),  # brief 33: its chips
            chatgpt=Scripted("PASS"))
    # 41. versus on a project waiting for your pick, each candidate built in its own copy with its files and tests (its
    # own project: a project has one open task at a time)
    shelf = tmp / "Projects" / "swap-shelf"
    shelf.mkdir(parents=True)
    projects.add("swap-shelf", shelf)
    projects.set_tests("swap-shelf", ["python3", "-m", "unittest"])
    vs = w.relay(145.88, "versus", "Make lend() refuse a packet that is out of stock, with a test.",
                 worker=Scripted(VERSUS_A, REVIEW_OF_B), chatgpt=Scripted(VERSUS_B, REVIEW_OF_A), project="swap-shelf")
    assert vs["preset"] == "versus" and vs["project"] == "swap-shelf", "the demo's versus task was refused"
    _versus_file_mode(w, vs)
    # brief 30 (decision 20): a forgotten card (the first task, in the garden chat), with Remember again on it
    memory.forget(w.conn, log.task_by_number(w.conn, 1), None, [], date="2026-10-19")
    # 42. redteam with one attacker: Cursor isn't available, so the second attack is left out (brief 32, decision 19)
    w.relay(146, "redteam", "Plan how the garden club shares its tool-shed key among volunteers.",
            worker=Scripted(SHED_BUILD, SHED_REVISION), chatgpt=Scripted(SHED_ATTACKS, "PASS"), cursor=CursorFake(),
            cursor_ready=lambda: cursor_worker.Readiness((False, CURSOR_OFF), "probe_failed"))
    # brief 33.3 (decision 13): 43. a task sent with its own model choice (Haiku for Claude), its Details naming the model
    # asked and the one that answered
    w.route(146.2, "Three short lines for the seed library's door: open hours, how to borrow, how to return.",
            jev("writing", 0.93), worker=Scripted("Open Saturdays 9 to 12.\nBorrow a packet: sign the sheet.\n"
                                                 "Return what you saved: a few seeds go a long way."),
            model_flags=["claude=haiku"], chat=garden, hindsight=w.hindsight)
    # 44. a served-differs line: Fable asked (while the switch was on), Opus answered (decision 7: Fable's safety fallback
    # re-runs some requests on Opus); the switch goes off again after, as it is by default (decision 6)
    models.set_fable(True, now=datetime(2026, 10, 19, 11, 26, tzinfo=timezone.utc), lock_folder=tmp)
    w.route(146.4, "Write a careful note on what the garden's pesticide cupboard may hold and what it may not.",
            jev("writing", 0.92), worker=Scripted("Keep only what the label says is for home gardens, in its own bottle, "
                                                 "on the top shelf; never a decanted mix, never anything without a label.",
                                                 served="claude-opus-5-5"), model_flags=["claude=fable"])
    models.set_fable(False, now=datetime(2026, 10, 19, 11, 27, tzinfo=timezone.utc), lock_folder=tmp)
    _plans(w)  # brief 33.1 (decision 21): the plan's four demo projects
    _autos(w)  # brief 34 (decision 16): the three Auto projects' runs
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


# ---------- brief 31 (decision 12): a project's Test, a run going, and its Secrets ----------

DEMO_TEST_OUTPUT = """....
----------------------------------------------------------------------
Ran 4 tests in 0.006s

OK
"""
DEMO_RUN_OUTPUT = """key length: 21
[REDACTED]
Serving the plot planner on http://127.0.0.1:8000
11:01:04 bed 3: watered (12 litres)
11:01:34 bed 5: compost turned
11:02:04 bed 1: seedlings thinned
"""


def _brief31(tmp):
    """plot-planner with a passed Test, a run going (invented output, its key line masked as the supervisor masks it) and
    Secrets with placeholder names, written as the router writes them, so the real views read them. The run's pid is
    this process's own, with the start time the demo's process table gives it, so it reads as running."""
    plots = tmp / "Projects" / "plot-planner"
    (plots / ".env").write_text("WEATHER_API_KEY=" + "placeholder-" + "0000-0000" + "\nMAP_TILES_TOKEN=\n")
    where = tmp / "run" / "projects" / "plot-planner"
    (where / "tests").mkdir(parents=True)
    record = {"outcome": "passed", "exit": 0, "summary": "OK", "seconds": 0.9, "when": "2026-10-19T11:00:09+00:00",
              "started": "2026-10-19T11:00:08+00:00", "head": "7d3e1a9" + "0" * 33, "branch": "main",
              "command": ["python3", "-m", "unittest"], "output": "20261019T110008.txt"}
    (where / "tests" / "20261019T110008.json").write_text(json.dumps(record, indent=1) + "\n")
    (where / "tests" / "20261019T110008.txt").write_text(DEMO_TEST_OUTPUT)
    projrun.set_run_command("plot-planner", ["python3", "planner.py", "--serve"])
    log_file = where / "run-20261019T110100.log"
    log_file.write_text(DEMO_RUN_OUTPUT)
    projrun.write_record(tmp / "run", "plot-planner", {
        "state": "running", "command": ["python3", "planner.py", "--serve"], "folder": str(plots), "log": str(log_file),
        "started": "2026-10-19T11:01:00+00:00", "pid": os.getpid(), "pid_started": "2026-10-19T08:59:00+00:00",
        "supervisor": os.getpid()})


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
            patch(gitops, "installed", lambda which=None: False)  # brief 28: the demo reads no git; its file-mode rows are written
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
            patch(projects, "TESTS_PATH", tmp / "config" / "project_tests.json")  # brief 28
            patch(notes, "PATH", tmp / "router-notes.md")  # brief 30: the demo's own router notes, never the owner's
            (tmp / "router-notes.md").write_text(DEMO_NOTES)
            patch(models, "LOCAL_PATH", tmp / "models.local.json")  # brief 33.3: the demo's own defaults, never the owner's
            _seed_models(tmp)
            patch(status, "git_view", lambda: {"installed": True, "version": "2.50.1"})  # brief 28: a Mac with git
            patch(status, "test_sandbox_view", lambda: {"available": True, "why": None})
            patch(status, "_files_view", lambda folder, state_path, version: dict(DEMO_FILES_VIEWS[Path(folder).name]))
            patch(filemode, "decide", lambda folder, files_ready: filemode.Decision(  # the intake reads the same views
                Path(folder).name in AUTO_PROJECTS,  # brief 34: the Auto switch reads the decision; nothing is sent in the demo
                DEMO_FILES_VIEWS[Path(folder).name]["why"] or "the demo makes no copy", None))
            patch(inbox, "fetch_file", inbox.fetch_file)
            patch(cli, "DB_PATH", tmp / "router.db")
            patch(cli, "ENV_PATH", tmp / ".env-none")
            patch(cli, "PROBE_STATE", tmp / "probe_state.json")
            patch(log, "ROUND_WRITER", rounds.writer(secrets=list(CONFIG.values()), out=_quiet, loaded=LOADED))
            build_log(w)
            log.ROUND_WRITER = None
            patch(runs, "FOLDER", tmp / "run")  # brief 31: the demo's Test, run and Secrets records, read by the real views
            patch(projrun, "RUNS_PATH", tmp / "config" / "project_runs.json")
            _brief31(tmp)
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
    # brief 33.1 (decision 21): the plan's four projects grew the demo past one page of 50; it shows every task on one
    shown = max(len(rows), 50)
    _write(staging / "log.json", jsonview.log_view(conn, rows[:shown], limit=shown + 1, live=ROSTER.live, loaded=LOADED),
           tmp)
    for row in rows:
        _write(staging / "tasks" / f"{row['task_id']}.json",
               jsonview.show_view(conn, row, live=ROSTER.live, loaded=LOADED, roster=ROSTER, send_paths=tuple(cli.SENDERS)),
               tmp)
    probe = tmp / "probe_state.json"
    probe.write_text(json.dumps({
        "claude_search": {"version": "2.1.306", "passed_at": "2026-10-19T08:00:00+00:00"},
        "claude_web_files": {"version": "2.1.306", "passed_at": "2026-10-19T08:00:00+00:00"},
        "cursor_sandbox": {"version": "2026.10.12-a1b2c3d", "passed_at": "2026-10-12T08:00:00+00:00",
                           "canaries": ["read", "list", "rules"], "mcp_tools": []},  # brief 32 (R0): as a pass is kept
        # brief 32: at 10:30, after task 9's Cursor attack on the version that passed; it updated itself and failed
        "cursor_sandbox_failure": {"version": "2026.10.19-6bbf2c4", "kind": "ran_failed",
                                   "reason": "read canary: a read completed", "at": "2026-10-19T10:30:00+00:00"}}))
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
                                       # brief 33 (decision 13): each project's What now?, from the demo's log
                                       "projects": cli._projects_json(projects.read_registry(), {}, conn=conn,
                                                                      loaded=LOADED)}, tmp)
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
    (staging / "git-check").mkdir()  # brief 28: Turn on undo's dry run for the project without git (DemoReader)
    _write(staging / "git-check" / "garden-site.json", {
        "api_version": jsonview.API_VERSION, "would": "turn_on", "name": "garden-site", "folder": "~/Projects/garden-site",
        "files": 2, "bytes": 412, "names": [".gitignore", "HANDOFF.md"], "more": 0,
        "gitignore": {"exists": False, "adds": [".env", ".env.*", ".venv/", "venv/", "__pycache__/", "node_modules/", ".DS_Store"]},
        "reason_code": None, "message": "Would turn on undo for garden-site: makes .gitignore with .env, .env.*, .venv/, venv/, "
                                    "__pycache__/, node_modules/, .DS_Store; git init; one first commit of 2 files (412 bytes). "
                                    "Nothing was changed."}, tmp)
    # brief 30 (decisions 10 and 17): the router notes the Setup sheet's editor reads, and each project's notes
    found = notes.read()
    _write(staging / "notes.json", {"api_version": jsonview.API_VERSION, "notes": {
        **notes.view(found), "text": found.text, "path": notes.NAME}}, tmp)
    for name in sorted(projects.read_registry()):
        _write(staging / "project-notes" / f"{name}.json", {"api_version": jsonview.API_VERSION,
                                                            "notes": projnotes.view(name)}, tmp)
        # brief 33.2 (decision 4): each project's spec as the Spec section reads it (the demo's folders have no git, so
        # the words say a save commits, as the demo's projects read `git: true`)
        doc = projspec.view(name)
        doc.update(git=True, commits=True, tracked=doc["exists"], commit_words="Save makes one commit holding SPEC.md alone.")
        _write(staging / "project-spec" / f"{name}.json", {"api_version": jsonview.API_VERSION, "spec": doc}, tmp)
    # brief 31 (decision 12): each project's Test and Run output and its Secrets' names, as the reads give them
    for name in sorted(projects.read_registry()):
        test = projtest.status(name, run_folder=runs.FOLDER)
        _write(staging / "project-output" / f"{name}-test.json", {"api_version": jsonview.API_VERSION,
                                                                  "project": {"name": name, "test_status": test}}, tmp)
        run = {k: v for k, v in projrun.status(name, run_folder=runs.FOLDER).items() if k != "log"}
        _write(staging / "project-output" / f"{name}-run.json", {"api_version": jsonview.API_VERSION,
                                                                 "project": {"name": name, "run_status": run}}, tmp)
        _write(staging / "secrets" / f"{name}.json", {"api_version": jsonview.API_VERSION, "project": {
            "name": name, "secrets": projsecrets.names(projects.folder_of(name))}}, tmp)
        # brief 33 (decision 20): each project's Ideas list, the envelope `sr ideas --json <name>` prints
        said = receipt.Receipt()
        assert cli.cmd_ideas([name], conn=conn, out=said) == 0
        _write(staging / "ideas" / f"{name}.json", {"task_id": None, "n": None, "status": None, "waiting_on": None,
                                                     "outcome": None, "reason_code": None, "exit": 0,
                                                     "message": said.message, **said.extra_any}, tmp)
    handoff = (tmp / "Projects" / "garden-site" / "HANDOFF.md").read_text(encoding="utf-8")
    (staging / "handoff").mkdir()
    (staging / "handoff" / "garden-site.md").write_text(handoff, encoding="utf-8")
    (staging / "auto-check").mkdir()  # brief 34 (decision 10): each project's dry run, the switch's confirm (DemoReader)
    for name in sorted(projects.read_registry()):
        said = receipt.Receipt()
        code = cli.cmd_auto([name], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[],
                            label=None, post=None, worker=None, on=True, dry_run=True, out=said)
        _write(staging / "auto-check" / f"{name}.json", {"api_version": jsonview.API_VERSION, "task_id": None, "n": None,
                                                         "status": None, "waiting_on": None, "outcome": None,
                                                         "reason_code": said.code, "exit": code, "message": said.message,
                                                         **({"auto": said.extra_any["auto"]} if code == 0 else {})}, tmp)
    (staging / "plan").mkdir()  # brief 33.1 (decision 20): each current plan's docs/PLAN.md, as the router renders it
    for name in sorted(projects.read_registry()):
        found = plan.current(conn, name)
        if found is not None:
            (staging / "plan" / f"{name}.md").write_text(plan.rendered(conn, found), encoding="utf-8")
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
