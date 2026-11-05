"""SQLite log (router.db), version 10.

Code writes every row. A model never writes status, IDs or timestamps.
Times are UTC ISO-8601 strings, so they sort and compare as text.

`tasks` holds one row per task. `calls` holds one row per agent call (the first call that does
the task, then the check, the fix and the re-check; on a relay task one `stage` row per stage,
plus a `reask` row when a contract was missed). A task's `result` is written once, when its
check loop has ended, so nothing can show a result before its check is done. A relay task's row
carries `mode` relay and its `preset`; a chain that stopped carries `failed_stage` (rules v2.12).
A call that stopped on a plan limit carries `reason_code` plan_limit, and the call that replaced it
on `sr resume` carries `resume_of`, the stopped call's id (rules v2.15, Resume). Stopped rows stay.
A call that research-build's search switch made eligible carries `search` (version 7): JSON with its
state (`allowed` or `off (probe not passed)`) and, when the tool reports them, the queries and their count.
A call made by `sr fallback` carries `fallback_of` (version 8, rules v2.17): the id of the original doer's call it
replaces. It replaces that row and every row after it for the step functions (fallback_view); every row stays.
A relay task carries `slots` (version 10, rules v2.21): the agent in each of its preset's slots, as JSON, written
whole on every new relay task (the owner's D1); null on rows from before, which ran with the defaults. A routed task
sent with --web carries `web` 1 (version 10, rules v2.22); null otherwise. A project task carries `project` and the
router's `handoff` writes, and each of its calls the `context` record (version 11, rules v2.25). A chat task carries
`chat` (version 12, rules v2.27, Memory): the tag is `project:<name>` or `chat:<name>`, never both; a tagged task's
`memory` holds the retain records the router made at its endings, and each call's `memory` the block as sent. A Cursor
call carries `served` (version 13, rules v2.28, Cursor; build brief 20): the model the stream named, the id asked for, the
tool events counted and named, duration_ms, permissionMode, usage and where its raw stream went; NULL on every other call.
A task that came back to the owner carries `reason_code` (version 14, rules v2.30, Router for the interface; build brief 21,
decision 1): written by the code that makes the return, at that moment, from RETURN_CODES; its prose reason is never
parsed back. A call carries `round_file` (version 14, rules v2.30, Round outputs): the call's own file under `tasks/`.
Rows from before version 14 read NULL in both; nothing is reconstructed (decision 3). A task carries `pid` and
`run_started_at` (version 15, rules v2.31, Router for the interface; build brief 22, decision 4): the process that runs it
and that process's own start time, written when a run starts and cleared when it ends; and `answered_by` on a Jev floor
row (decision 2): the task that answered it. Version 15 logs are in WAL mode and every connection waits 15 s for another
writer (decision 6).
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERSION = 21  # kept in PRAGMA user_version; a version 1 log has 0
BUSY_SECONDS = 15  # build brief 22, decision 6: every connection waits this long for another writer before `locked`

STATUSES = ("queued", "sent", "done", "failed", "timed_out", "cancelled", "returned")
# `not_asked` is a relay task's status: Jev is never called on one (rules v2.12).
JEV_STATUSES = ("ok", "below_floor", "none_of_these", "error", "over_cap", "not_asked",
                "not_set_up")  # build brief 24 (decision 13): no JEV_API_KEY, so Jev isn't called
# brief 25 (log version 16): a label the owner gave is `owner`; brief 29.1 (decision 24): the follow-up's is `router`
SKILL_SOURCES = ("jev", "owner", "router")
CHECK_STATES = ("not_needed", "unchecked", "pending", "passed", "fixed", "failed",
                "blocked")  # brief 29.1 (decision 17): the doer lacked what it needed; no fix round
MODES = ("route", "relay", "split", "piece", "plan", "auto",  # brief 33.1 (decision 1): a plan task; brief 34: a run
         "suggest")  # brief 33.4 (decision 10): one Suggest ideas click
# A split (rules v2.18) is never sent to Jev; a piece is labeled like any routed task and names its split in `parent`.
NOT_ASKED_MODES = ("relay", "split", "plan", "auto", "suggest")  # brief 33.1: Jev is never called on a plan; brief 34: nor on a
# run; brief 33.4: nor on a suggest
# `stage` and `reask` are the relay kinds: one `stage` row per stage, a `reask` row when the
# stage's contract was missed and its agent was asked once more.
CALL_KINDS = ("do", "check", "fix", "recheck", "stage", "reask",
              "questions")  # brief 33.4 (decision 3): a plan's stage-1 round that ended in `## Questions`: no longer the stage
# Brief 21, C1 (rules v2.30, Round outputs): main sets this for one command (router/rounds.writer); add_call and
# finish_call hand it each call that came back with text, after its row is written. None: no files (tests, reads).
ROUND_WRITER = None
STAGE_KINDS = ("stage", "reask")
MAX_STAGES = 4  # rules v2.12, Money and Relay
CALL_STATUSES = ("sent", "done", "failed", "timed_out")
VERDICTS = ("PASS", "FIX", "BLOCKED", "unreadable")  # brief 29.1 (decision 17): BLOCKED
# The only reason code: a call that stopped on Claude's or ChatGPT's plan limit (router/plan_limit.py).
# Any other failure keeps its own text and no code.
REASON_CODES = ("plan_limit", "process_ended",  # build brief 22: a call whose sr process ended while it ran
                # build brief 24 (decision 6, C5): a Grok call out at 2N; its answer after the takeover; a call too long
                # for Grok; a call that failed in the router's own code (never taken over)
                "overdue", "late", "too_long", "internal_error",
                # build brief 28 (decisions 7 and 8): the copy held a path it never carries or a link, or a change broke
                # a limit; the task stops and nothing takes the call over
                "copy_problem",
                # build brief 32 (decision 11): an optional stage skipped (its call failed or its list missed its
                # contract after the re-ask); the chain went on without it, and nothing takes it over or resumes it
                "skipped",
                # build brief 33.3 (decision 6): the call's stream marked it billed to usage credits; the task stops, Fable
                # turns off, nothing takes it over and nothing is retried
                "credits")
# Build brief 21 (rules v2.30, Router for the interface): why a task came back to the owner, on the task row
# (tasks.reason_code), written by the code that makes the return. A refusal writes no row; its code rides in the JSON only.
RETURN_CODES = ("needs_label", "no_skill", "no_answer", "not_routed", "needs_tag", "not_live", "files_to_agent",
                "handoff_key", "handoff_unreadable", "memory_down",
                "unavailable",  # build brief 24 (decision 3): make_media without Grok Bot, or no agent for the skill
                "notes_key",  # brief 30 (decision 4): the router notes kept with the task looked like a key on the send
                "too_long",  # brief 33 (decision 11): Grok would do it, and the from-block would pass Grok's limit
                "budget")  # brief 34 (decision 7): a run stopped at its budget (the run row's own code)
HANDOFF_RETURN_CODES = ("handoff_key", "handoff_unreadable", "notes_key")  # what return_for_context takes
# Brief 29.1 (decision 3): the returns `sr route --skill <key> --answers <n>` may answer: a Jev floor question, and a task Jev
# labeled with a skill version 2 doesn't route ("Send as <skill>" on its card)
ANSWERABLE_CODES = ("needs_label", "not_routed")
SEARCH_STATES = ("allowed", "off (probe not passed)", "off (file without --web)",
                 "off (--web file probe not passed)")  # router/search.py
# Build brief 9 (the owner's D2): a versus task whose reviews are in waits for the owner's pick as `returned`
# (the one status that means "with the owner"; the status CHECK can't gain a value without a table rebuild)
# with this check_note. Nothing is its result until `sr pick`.
AWAITING_PICK = "awaiting pick"
# Build brief 11 (rules v2.18, Split): a split waits with the owner as `returned` too, with one of these notes:
# its plan for their y/N/e, or its pieces (`waiting: pieces #5, #6`) until each is delivered or skipped.
AWAITING_APPROVAL = "awaiting approval"
WAITING_PIECES = "waiting: pieces"
# Brief 33.4 (decision 5): a plan that asked its questions waits with the owner, `returned` with this note, its copy kept
AWAITING_ANSWERS = "awaiting answers"
_ROLE = re.compile(r"[a-z][a-z0-9_-]*")
PROJECT_NAME = re.compile(r"[a-z0-9-]+")  # rules v2.25: a project name is lower case letters, digits and -

# Only status has a CHECK. Agent names come from config/agents.json and are checked in code
# (set_route): a CHECK naming the agents would hardcode them, and SQLite can't change a CHECK
# without rebuilding the table. The call columns are checked in code the same way.
SCHEMA = """
CREATE TABLE tasks (
    task_id         TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    sent_at         TEXT,
    source          TEXT NOT NULL,
    task            TEXT NOT NULL,
    jev_status      TEXT NOT NULL,
    jev_label       TEXT,
    jev_confidence  REAL,
    jev_needs_split REAL,
    jev_tokens      INTEGER NOT NULL DEFAULT 0,
    jev_error       TEXT,
    skill           TEXT,
    skill_source    TEXT,
    agent           TEXT,
    route_reason    TEXT,
    checker         TEXT,
    check_state     TEXT,
    status          TEXT NOT NULL CHECK (status IN
                    ('queued', 'sent', 'done', 'failed', 'timed_out', 'cancelled', 'returned')),
    run_uuid        TEXT,
    result          TEXT,
    result_url      TEXT,
    check_note      TEXT,
    files           TEXT,
    mode            TEXT NOT NULL DEFAULT 'route',
    preset          TEXT,
    failed_stage    INTEGER,
    parent          TEXT,
    split_plan      TEXT,
    slots           TEXT,
    web             INTEGER,
    project         TEXT,
    handoff         TEXT,
    chat            TEXT,
    memory          TEXT,
    reason_code     TEXT,
    pid             INTEGER,
    run_started_at  TEXT,
    answered_by     TEXT,
    project_files   TEXT,
    from_task       TEXT,
    idea            INTEGER,
    plan            TEXT,
    plan_step       TEXT,
    models          TEXT,
    auto            TEXT
)
"""

CALLS_SCHEMA = """
CREATE TABLE calls (
    call_id     TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL,
    kind        TEXT NOT NULL,
    agent       TEXT NOT NULL,
    status      TEXT NOT NULL,
    sent_at     TEXT NOT NULL,
    finished_at TEXT,
    run_uuid    TEXT,
    text        TEXT,
    verdict     TEXT,
    url         TEXT,
    stage       INTEGER,
    role        TEXT,
    reason_code TEXT,
    resume_of   TEXT,
    search      TEXT,
    fallback_of TEXT,
    context     TEXT,
    memory      TEXT,
    served      TEXT,
    round_file  TEXT,
    tests       TEXT,
    model       TEXT,
    effort      TEXT,
    time_limit  INTEGER
)
"""

V1_COLUMNS = (
    "task_id", "created_at", "updated_at", "sent_at", "source", "task",
    "agent", "route_reason", "status", "run_uuid", "result", "result_url",
)
V2_COLUMNS = (
    "task_id", "created_at", "updated_at", "sent_at", "source", "task",
    "jev_status", "jev_label", "jev_confidence", "jev_needs_split", "jev_tokens", "jev_error",
    "skill", "skill_source", "agent", "route_reason", "checker", "check_state",
    "status", "run_uuid", "result", "result_url",
)
V3_COLUMNS = V2_COLUMNS + ("check_note",)
V4_COLUMNS = V3_COLUMNS + ("files",)
# The calls table's columns in versions 3 and 4, before stage and role.
V4_CALL_COLUMNS = ("call_id", "task_id", "kind", "agent", "status", "sent_at", "finished_at",
                   "run_uuid", "text", "verdict", "url")
_RELAY_TASK_COLUMNS = ("ALTER TABLE tasks ADD COLUMN mode TEXT NOT NULL DEFAULT 'route';"
                       " ALTER TABLE tasks ADD COLUMN preset TEXT;"
                       " ALTER TABLE tasks ADD COLUMN failed_stage INTEGER;")
_RELAY_CALL_COLUMNS = "ALTER TABLE calls ADD COLUMN stage INTEGER; ALTER TABLE calls ADD COLUMN role TEXT;"
V5_COLUMNS = V4_COLUMNS + ("mode", "preset", "failed_stage")
V5_CALL_COLUMNS = V4_CALL_COLUMNS + ("stage", "role")
_RESUME_CALL_COLUMNS = ("ALTER TABLE calls ADD COLUMN reason_code TEXT; ALTER TABLE calls ADD COLUMN resume_of TEXT;"
                        " ALTER TABLE calls ADD COLUMN search TEXT;")
V6_CALL_COLUMNS = V5_CALL_COLUMNS + ("reason_code", "resume_of")
_SEARCH_CALL_COLUMN = "ALTER TABLE calls ADD COLUMN search TEXT;"
V7_CALL_COLUMNS = V6_CALL_COLUMNS + ("search",)
V8_CALL_COLUMNS = V7_CALL_COLUMNS + ("fallback_of",)
_FALLBACK_CALL_COLUMN = "ALTER TABLE calls ADD COLUMN fallback_of TEXT;"
_SPLIT_TASK_COLUMNS = " ALTER TABLE tasks ADD COLUMN parent TEXT; ALTER TABLE tasks ADD COLUMN split_plan TEXT;"
V9_COLUMNS = V5_COLUMNS + ("parent", "split_plan")
# Version 10 (build brief 15): a relay task's slot map and a routed task's --web mark.
_SLOTS_TASK_COLUMNS = " ALTER TABLE tasks ADD COLUMN slots TEXT; ALTER TABLE tasks ADD COLUMN web INTEGER;"
_SLOTS_ADDED = "; slots and web columns added to tasks"
# Version 11 (build brief 18, rules v2.25 Project context): a task's project name and the handoff writes the router
# made for it; a call's context record (the handoff as sent, or how much of it was).
V10_COLUMNS = V9_COLUMNS + ("slots", "web")
_PROJECT_TASK_COLUMNS = " ALTER TABLE tasks ADD COLUMN project TEXT; ALTER TABLE tasks ADD COLUMN handoff TEXT;"
_CONTEXT_CALL_COLUMN = " ALTER TABLE calls ADD COLUMN context TEXT;"
_PROJECT_COLUMNS = _PROJECT_TASK_COLUMNS + _CONTEXT_CALL_COLUMN
_PROJECT_ADDED = "project and handoff columns added to tasks; context column added to calls"
# Version 12 (build brief 19, rules v2.27 Memory): a task's chat name (its tag when it has no project) and the retain
# records the router made for it; a call's memory record (the memory block as sent, or why it was not).
V11_COLUMNS = V10_COLUMNS + ("project", "handoff")
V11_CALL_COLUMNS = V8_CALL_COLUMNS + ("context",)
_MEMORY_TASK_COLUMNS = " ALTER TABLE tasks ADD COLUMN chat TEXT; ALTER TABLE tasks ADD COLUMN memory TEXT;"
_MEMORY_CALL_COLUMN = " ALTER TABLE calls ADD COLUMN memory TEXT;"
_MEMORY_COLUMNS = _MEMORY_TASK_COLUMNS + _MEMORY_CALL_COLUMN
_MEMORY_ADDED = "chat and memory columns added to tasks; memory column added to calls"
# Version 13 (build brief 20, rules v2.28 Cursor): a Cursor call's `served` record on calls; NULL on every other call.
V12_COLUMNS = V11_COLUMNS + ("chat", "memory")
V12_CALL_COLUMNS = V11_CALL_COLUMNS + ("memory",)
_SERVED_CALL_COLUMN = " ALTER TABLE calls ADD COLUMN served TEXT;"
_SERVED_ADDED = "served column added to calls"
# Version 14 (build brief 21, rules v2.30): a returned task's reason_code on tasks; a call's round_file on calls.
V13_COLUMNS = V12_COLUMNS  # version 13 added no task column
V13_CALL_COLUMNS = V12_CALL_COLUMNS + ("served",)
_REASON_TASK_COLUMN = " ALTER TABLE tasks ADD COLUMN reason_code TEXT;"
_ROUND_CALL_COLUMN = " ALTER TABLE calls ADD COLUMN round_file TEXT;"
_V14_ADDED = "reason_code column added to tasks; round_file column added to calls"
# Version 15 (build brief 22, decision 6): the run on a task (pid, run_started_at) and a floor row's answered_by.
V14_COLUMNS = V13_COLUMNS + ("reason_code",)
V14_CALL_COLUMNS = V13_CALL_COLUMNS + ("round_file",)
_RUN_TASK_COLUMNS = (" ALTER TABLE tasks ADD COLUMN pid INTEGER; ALTER TABLE tasks ADD COLUMN run_started_at TEXT;"
                     " ALTER TABLE tasks ADD COLUMN answered_by TEXT;")
_V15_ADDED = "pid, run_started_at and answered_by columns added to tasks"
# Build brief 25 (log version 16): a label or answer the owner gave reads `owner`. The old value is found by exclusion,
# never spelled: any skill_source that is neither of today's two values nor empty.
OWNER_SOURCE = " UPDATE tasks SET skill_source = 'owner' WHERE skill_source IS NOT NULL AND skill_source NOT IN ('jev', 'owner');"
V16_ADDED = "skill_source set to owner where it named the one who labeled the task"
# Version 17 (build brief 28, decisions 8 and 19): a task's project files record (file mode: its state, base, change, diff,
# commit, undo commit, or why it was off) and a call's tests record (exit, outcome, summary, output file).
V16_COLUMNS = V14_COLUMNS + ("pid", "run_started_at", "answered_by")
_FILES_TASK_COLUMN = " ALTER TABLE tasks ADD COLUMN project_files TEXT;"
_TESTS_CALL_COLUMN = " ALTER TABLE calls ADD COLUMN tests TEXT;"
V17_ADDED = "project_files column added to tasks; tests column added to calls"
# Version 18 (build brief 33, decision 17): the earlier task a task builds from (`--from`) and the idea it was sent from
# (`--idea`) on tasks, and the table of each project's Ideas list. An idea's state is derived, never stored.
V17_COLUMNS = V16_COLUMNS + ("project_files",)
V17_CALL_COLUMNS = V14_CALL_COLUMNS + ("tests",)
IDEAS_SCHEMA = """
CREATE TABLE ideas (
    id           INTEGER PRIMARY KEY,
    project      TEXT NOT NULL,
    text         TEXT NOT NULL,
    source_kind  TEXT NOT NULL CHECK (source_kind IN ('later', 'added')),
    source_task  TEXT,
    created_at   TEXT NOT NULL,
    dismissed_at TEXT
)
"""
_FROM_IDEA_COLUMNS = " ALTER TABLE tasks ADD COLUMN from_task TEXT; ALTER TABLE tasks ADD COLUMN idea INTEGER;"
_IDEAS_TABLE = f" {IDEAS_SCHEMA.strip()};"
V18_ADDED = "from_task and idea columns added to tasks; ideas table added"
# Version 19 (build brief 33.1, decision 19): a plan task's plan (as the planner returned it, the owner's edits and the hash of
# the docs/PLAN.md it rendered) and a step task's plan task and step.
V18_COLUMNS = V17_COLUMNS + ("from_task", "idea")
_PLAN_TASK_COLUMNS = " ALTER TABLE tasks ADD COLUMN plan TEXT; ALTER TABLE tasks ADD COLUMN plan_step TEXT;"
V19_ADDED = "plan and plan_step columns added to tasks"
# Version 20 (build brief 33.3, decision 7): a task's own model choices (`--model <agent>=<model>`, `--effort`) and each
# call's model asked, effort and time limit; `calls.served` (version 13's column) takes every agent's served record.
V19_COLUMNS = V18_COLUMNS + ("plan", "plan_step")
V19_CALL_COLUMNS = V17_CALL_COLUMNS
_MODELS_TASK_COLUMN = " ALTER TABLE tasks ADD COLUMN models TEXT;"
_MODELS_CALL_COLUMNS = (" ALTER TABLE calls ADD COLUMN model TEXT; ALTER TABLE calls ADD COLUMN effort TEXT;"
                        " ALTER TABLE calls ADD COLUMN time_limit INTEGER;")
V20_ADDED = "models column added to tasks; model, effort and time_limit columns added to calls"
# Version 21 (build brief 34, decision 14): a run row's record (`mode` `auto`): its plan, its steps, the budget, the calls
# used, the stop and the passed marks; the stop-here marks live on the plan row's record, the step tasks name the run as
# their parent.
V20_COLUMNS = V19_COLUMNS + ("models",)
V20_CALL_COLUMNS = V19_CALL_COLUMNS + ("model", "effort", "time_limit")
_AUTO_TASK_COLUMN = " ALTER TABLE tasks ADD COLUMN auto TEXT;"
V21_ADDED = "auto column added to tasks"
# What each in-place upgrade adds, by the version it starts from. `call_columns` names the calls
# table's columns when it already exists, so the check after the upgrade covers its rows too.
UPGRADES = {
    2: {"columns": V2_COLUMNS,
        "statements": f"{CALLS_SCHEMA}; ALTER TABLE tasks ADD COLUMN check_note TEXT;"
                      f" ALTER TABLE tasks ADD COLUMN files TEXT; {_RELAY_TASK_COLUMNS}{_SPLIT_TASK_COLUMNS}{_SLOTS_TASK_COLUMNS}",
        "added": "calls table added; check_note, files, mode, preset and failed_stage columns added; "
                 "parent and split_plan columns added to tasks"},
    3: {"columns": V3_COLUMNS, "call_columns": V4_CALL_COLUMNS,
        "statements": f"ALTER TABLE tasks ADD COLUMN files TEXT; {_RELAY_TASK_COLUMNS} {_RELAY_CALL_COLUMNS}"
                      f" {_RESUME_CALL_COLUMNS} {_FALLBACK_CALL_COLUMN}{_SPLIT_TASK_COLUMNS}{_SLOTS_TASK_COLUMNS}",
        "added": "files, mode, preset and failed_stage columns added to tasks; stage, role, reason_code, "
                 "resume_of, search and fallback_of columns added to calls; parent and split_plan columns added to tasks"},
    4: {"columns": V4_COLUMNS, "call_columns": V4_CALL_COLUMNS,
        "statements": f"{_RELAY_TASK_COLUMNS} {_RELAY_CALL_COLUMNS} {_RESUME_CALL_COLUMNS} {_FALLBACK_CALL_COLUMN}"
                      f"{_SPLIT_TASK_COLUMNS}{_SLOTS_TASK_COLUMNS}",
        "added": "mode, preset and failed_stage columns added to tasks; stage, role, reason_code, resume_of, "
                 "search and fallback_of columns added to calls; parent and split_plan columns added to tasks"},
    5: {"columns": V5_COLUMNS, "call_columns": V5_CALL_COLUMNS,
        "statements": f"{_RESUME_CALL_COLUMNS} {_FALLBACK_CALL_COLUMN}{_SPLIT_TASK_COLUMNS}{_SLOTS_TASK_COLUMNS}",
        "added": "reason_code, resume_of, search and fallback_of columns added to calls; "
                 "parent and split_plan columns added to tasks"},
    6: {"columns": V5_COLUMNS, "call_columns": V6_CALL_COLUMNS,
        "statements": f"{_SEARCH_CALL_COLUMN} {_FALLBACK_CALL_COLUMN}{_SPLIT_TASK_COLUMNS}{_SLOTS_TASK_COLUMNS}",
        "added": "search and fallback_of columns added to calls; parent and split_plan columns added to tasks"},
    7: {"columns": V5_COLUMNS, "call_columns": V7_CALL_COLUMNS,
        "statements": f"{_FALLBACK_CALL_COLUMN}{_SPLIT_TASK_COLUMNS}{_SLOTS_TASK_COLUMNS}",
        "added": "fallback_of column added to calls; parent and split_plan columns added to tasks"},
    8: {"columns": V5_COLUMNS, "call_columns": V8_CALL_COLUMNS,
        "statements": f"{_SPLIT_TASK_COLUMNS}{_SLOTS_TASK_COLUMNS}",
        "added": "parent and split_plan columns added to tasks"},
    9: {"columns": V9_COLUMNS, "call_columns": V8_CALL_COLUMNS,
        "statements": _SLOTS_TASK_COLUMNS,
        "added": "slots and web columns added to tasks"},
    10: {"columns": V10_COLUMNS, "call_columns": V8_CALL_COLUMNS,
         "statements": _PROJECT_COLUMNS,
         "added": _PROJECT_ADDED},
    11: {"columns": V11_COLUMNS, "call_columns": V11_CALL_COLUMNS,
         "statements": _MEMORY_COLUMNS,
         "added": _MEMORY_ADDED},
    12: {"columns": V12_COLUMNS, "call_columns": V12_CALL_COLUMNS,
         "statements": _SERVED_CALL_COLUMN,
         "added": _SERVED_ADDED},
    13: {"columns": V13_COLUMNS, "call_columns": V13_CALL_COLUMNS,
         "statements": _REASON_TASK_COLUMN + _ROUND_CALL_COLUMN,
         "added": _V14_ADDED},
    14: {"columns": V14_COLUMNS, "call_columns": V14_CALL_COLUMNS,
         "statements": _RUN_TASK_COLUMNS,
         "added": _V15_ADDED},
    15: {"columns": V16_COLUMNS, "call_columns": V14_CALL_COLUMNS,
         "statements": OWNER_SOURCE,
         "added": V16_ADDED},
    16: {"columns": V16_COLUMNS, "call_columns": V14_CALL_COLUMNS,
         "statements": _FILES_TASK_COLUMN + _TESTS_CALL_COLUMN,
         "added": V17_ADDED},
    17: {"columns": V17_COLUMNS, "call_columns": V17_CALL_COLUMNS,
         "statements": _FROM_IDEA_COLUMNS + _IDEAS_TABLE,
         "added": V18_ADDED},
    18: {"columns": V18_COLUMNS, "call_columns": V17_CALL_COLUMNS,
         "statements": _PLAN_TASK_COLUMNS,
         "added": V19_ADDED},
    19: {"columns": V19_COLUMNS, "call_columns": V19_CALL_COLUMNS,
         "statements": _MODELS_TASK_COLUMN + _MODELS_CALL_COLUMNS,
         "added": V20_ADDED},
    20: {"columns": V20_COLUMNS, "call_columns": V20_CALL_COLUMNS,
         "statements": _AUTO_TASK_COLUMN,
         "added": V21_ADDED},
}
for _from in range(2, 9):  # every older log lands on version 10 with the slots and web columns too
    UPGRADES[_from]["added"] += _SLOTS_ADDED
for _from in range(2, 10):  # ...and on version 11 with the project, handoff and context columns (brief 18)
    # version 2 makes its calls table from CALLS_SCHEMA, which already has `context`
    UPGRADES[_from]["statements"] += _PROJECT_TASK_COLUMNS if _from == 2 else _PROJECT_COLUMNS
    UPGRADES[_from]["added"] += "; " + _PROJECT_ADDED
for _from in range(2, 11):  # ...and on version 12 with the chat and memory columns (brief 19)
    # version 2 makes its calls table from CALLS_SCHEMA, which already has `memory`
    UPGRADES[_from]["statements"] += _MEMORY_TASK_COLUMNS if _from == 2 else _MEMORY_COLUMNS
    UPGRADES[_from]["added"] += "; " + _MEMORY_ADDED
for _from in range(2, 12):  # ...and on version 13 with the served column (brief 20)
    # version 2 makes its calls table from CALLS_SCHEMA, which already has `served`
    if _from != 2:
        UPGRADES[_from]["statements"] += _SERVED_CALL_COLUMN
    UPGRADES[_from]["added"] += "; " + _SERVED_ADDED
for _from in range(2, 13):  # ...and on version 14 with reason_code and round_file (brief 21)
    # version 2 makes its calls table from CALLS_SCHEMA, which already has `round_file`
    UPGRADES[_from]["statements"] += _REASON_TASK_COLUMN + ("" if _from == 2 else _ROUND_CALL_COLUMN)
    UPGRADES[_from]["added"] += "; " + _V14_ADDED
for _from in range(2, 14):  # ...and on version 15 with the run columns and answered_by (brief 22)
    UPGRADES[_from]["statements"] += _RUN_TASK_COLUMNS
    UPGRADES[_from]["added"] += "; " + _V15_ADDED
for _from in range(2, 15):  # ...and on version 16 with the owner's stored value renamed (brief 25)
    UPGRADES[_from]["statements"] += OWNER_SOURCE
    UPGRADES[_from]["added"] += "; " + V16_ADDED
for _from in range(2, 16):  # ...and on version 17 with project_files and tests (brief 28)
    # version 2 makes its calls table from CALLS_SCHEMA, which already has `tests`
    UPGRADES[_from]["statements"] += _FILES_TASK_COLUMN + ("" if _from == 2 else _TESTS_CALL_COLUMN)
    UPGRADES[_from]["added"] += "; " + V17_ADDED
for _from in range(2, 17):  # ...and on version 18 with from_task, idea and the ideas table (brief 33)
    UPGRADES[_from]["statements"] += _FROM_IDEA_COLUMNS + _IDEAS_TABLE
    UPGRADES[_from]["added"] += "; " + V18_ADDED
for _from in range(2, 18):  # ...and on version 19 with plan and plan_step (brief 33.1)
    UPGRADES[_from]["statements"] += _PLAN_TASK_COLUMNS
    UPGRADES[_from]["added"] += "; " + V19_ADDED
for _from in range(2, 19):  # ...and on version 20 with models on tasks and model, effort, time_limit on calls (brief 33.3)
    # version 2 makes its calls table from CALLS_SCHEMA, which already has the three call columns
    UPGRADES[_from]["statements"] += _MODELS_TASK_COLUMN + ("" if _from == 2 else _MODELS_CALL_COLUMNS)
    UPGRADES[_from]["added"] += "; " + V20_ADDED
for _from in range(2, 20):  # ...and on version 21 with auto on tasks (brief 34)
    UPGRADES[_from]["statements"] += _AUTO_TASK_COLUMN
    UPGRADES[_from]["added"] += "; " + V21_ADDED


class StateError(Exception):
    """A status change that is not allowed, or a task or call that does not exist."""


class VersionError(Exception):
    """The file is not a current-version log. Nothing was changed."""


class MigrateRefused(Exception):
    """`sr migrate` stopped before changing anything."""


class MigrateFailed(Exception):
    """`sr migrate` changed the log, then a check after the change failed. Nothing was deleted."""


def _utc(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _iso(now=None):
    return _utc(now).isoformat(timespec="seconds")


def _allowed(name, value, allowed, required=False):
    if value is None and not required:
        return
    if value not in allowed:
        raise ValueError(f"{name} {value!r} is not allowed here. Allowed: {', '.join(allowed)}.")


def connect(path, *, read_only=False):
    """Every connection to a log (build brief 22, decision 6): rows by name, and a 15 s wait for another writer before
    `database is locked` (Python's own default is 5 s). `read_only` opens the file with `mode=ro`: it never writes, and
    under WAL it still reads the last committed rows while another command writes."""
    if read_only:
        conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=BUSY_SECONDS)
    else:
        conn = sqlite3.connect(path, timeout=BUSY_SECONDS)
    conn.row_factory = sqlite3.Row
    return conn


def _read_only(path):
    return connect(path, read_only=True)


def _in_memory(path):
    return str(path) == ":memory:" or str(path).startswith("file::memory:")


def _version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _columns(conn):
    return tuple(row[1] for row in conn.execute("PRAGMA table_info(tasks)"))


def init_db(path):
    """Open the log. A missing or empty file becomes an empty version 15 log, in WAL mode (decision 6).
    A version 1 to 14 log is refused and left exactly as it is: `sr migrate` moves or upgrades it."""
    conn = connect(path)
    try:
        version, columns = _version(conn), _columns(conn)
        if version == VERSION and columns:
            return conn
        if version == 0 and not columns:
            # One transaction, so a new log never exists without its version mark.
            conn.executescript(f"BEGIN; {SCHEMA}; {CALLS_SCHEMA}; {IDEAS_SCHEMA}; PRAGMA user_version = {VERSION}; COMMIT;")
            if not _in_memory(path):
                conn.execute("PRAGMA journal_mode=WAL")  # set once, outside any transaction; it stays in the file
            return conn
    except BaseException:
        conn.close()
        raise
    conn.close()
    raise VersionError(_version_message(Path(str(path)).name, version))


def _version_message(name, version):
    if version == 0:
        return (f"{name} is a version 1 log. Run `sr migrate` once: it moves the old log into backups/ "
                f"and starts an empty version {VERSION} log. Nothing was changed.")
    if version in UPGRADES:
        return (f"{name} is a version {version} log. Run `sr migrate` once: it copies the log into backups/, then "
                f"upgrades it in place to version {VERSION} ({UPGRADES[version]['added']}). Nothing was changed.")
    return f"{name} has log version {version}, which this router doesn't know. Nothing was changed."


def open_read_only(path):
    """A JSON read's log (build brief 21: a JSON command never writes): the log read-only; an empty log in memory when
    there is no file yet (nothing is made on disk); VersionError, as init_db gives it, on any other version."""
    if not Path(path).exists():
        return init_db(":memory:")
    try:
        conn = _read_only(path)
        version, columns = _version(conn), _columns(conn)
    except sqlite3.DatabaseError as e:
        raise VersionError(f"{Path(str(path)).name} could not be read ({type(e).__name__}). Nothing was changed.") from None
    if version == VERSION and columns:
        return conn
    conn.close()
    raise VersionError(_version_message(Path(str(path)).name, version))


def file_version(path):
    """The log file's own version (PRAGMA user_version), read-only, or None when there is no readable file."""
    try:
        conn = _read_only(path)
    except sqlite3.DatabaseError:
        return None
    try:
        return _version(conn)
    except sqlite3.DatabaseError:
        return None
    finally:
        conn.close()


def is_run_step(row):
    """Brief 34 (decision 2): a step of an Auto run: a piece of the run (a row with the run as its parent) whose file-mode
    record names the run (`run`). Its prompts, tests and checks are Build step k's; its entry, memory and land are the
    run's, as a split's piece's are its split's."""
    return bool((project_files_of(row) or {}).get("run")) if "project_files" in row.keys() else False


def is_piece(row):
    """Build brief 29 (decision 9): a piece of a split is a row with a parent, whatever its team: mode `piece` (a route
    piece) or `relay` (a piece of another team). Every "is this a piece" reads this."""
    return bool(row["parent"] if "parent" in row.keys() else None)


CHAINED_MODES = ("relay", "plan")  # brief 33.1 (decision 1): a plan runs redteam's chain as a relay task does


def runs_preset(row):
    """Build brief 29 (decision 9): the row runs a preset's chain (a relay task, or a piece of a team other than route).
    Brief 33.1: a plan task too. Every "does this run a preset" reads this."""
    return (row["mode"] if "mode" in row.keys() else None) in CHAINED_MODES


def add_task(conn, task_id, task, source, jev, now=None, files=None, mode="route", preset=None, parent=None,
             slots=None, web=False, project=None, chat=None, run=None, owner_label=False, answers=None, from_task=None,
             idea=None, plan=None, plan_step=None, models=None, auto=None):
    """Log a new task as queued, with Jev's answer. Brief 33 (decision 17): `from_task`, the earlier task it builds from,
    and `idea`, the project idea it was sent from (both checked at intake). `jev` holds status, label, confidence,
    needs_split, tokens and error (see router/jev.py). Who does the task is set by set_route.
    `files` is the list of file records (name, type, size, frames) from router/media.py, or None;
    `task` is the text the owner typed, never the copy with the file lines that Jev got.
    A relay task (`mode` relay) names its `preset` and has Jev's status `not_asked`, and only a
    relay task or a split task may (rules v2.12, v2.18: Jev is never called on either). A piece
    (`mode` piece) names its split task in `parent` and is labeled by Jev like any routed task;
    only a piece has a parent (rules v2.18, Split). A relay task's `slots` is the agent in each of its preset's
    slots ({slot: agent}, rules v2.21); only a relay task has slots. `web` marks a routed task the owner sent with
    --web (rules v2.22); only a routed task (mode route) takes it. `project` is the registered project name on a
    project task (rules v2.25): a routed or relay task only, never a split or a piece. `chat` is the chat name on a
    chat task (rules v2.27, Memory, "The tag"): the same shape and the same two modes; never beside a project. `run` is
    (pid, start time) when the row is born with the run that makes it (build brief 22, decision 4), so no other command
    sees it unowned for even a moment. `owner_label` (build brief 22, decision 2): a routed task its owner labeled with
    `--skill`, so Jev was not asked (`not_asked` on a route task). `answers` is the Jev floor row it answers: that row
    gets `answered_by` in the same write, or nothing is written (StateError) when it is no longer an unanswered floor
    question. Brief 33.1 (decision 19): a plan task (`mode` plan) names its preset (redteam) and slots as a relay task does,
    always has a project, and starts with its `plan` record (the menu it is read against); a step task carries
    `plan_step`, {plan, step}, and a project. Brief 33.3 (decision 4): `models` is the task's own model choices,
    {agent: {"model", "effort"}}, checked at intake (router/models.py); None when none were given."""
    _allowed("jev_status", jev.get("status"), JEV_STATUSES, required=True)
    _allowed("mode", mode, MODES, required=True)
    if mode in CHAINED_MODES:
        if not isinstance(preset, str) or not preset:
            raise ValueError(f"a {mode} task needs a preset name.")
    elif preset is not None:
        raise ValueError("only a relay task has a preset.")  # (a plan task has redteam's, brief 33.1)
    if mode == "plan" and (project is None or parent is not None or chat is not None or files or web):
        raise ValueError("a plan task has a project, and no parent, chat, file or --web.")
    if (plan is not None) != (mode == "plan"):
        raise ValueError("a plan task, and only one, starts with its plan record.")
    if mode == "auto" and (project is None or parent is not None or chat is not None or files or web):  # brief 34
        raise ValueError("a run has a project, and no parent, chat, file or --web.")
    if (auto is not None) != (mode == "auto"):
        raise ValueError("a run, and only one, starts with its auto record.")
    owner = get_task(conn, parent) if parent is not None else None
    run_step = owner is not None and owner["mode"] == "auto"  # brief 34 (decision 2): a step task of a run
    if plan_step is not None and (mode not in ("route", "relay") or project is None or (parent is not None and not run_step)
                                  or not isinstance(plan_step, dict)):
        raise ValueError("a step of a plan is a routed or relay task on its project.")
    if mode in NOT_ASKED_MODES and jev.get("status") != "not_asked":
        raise ValueError(f"a {mode} task's jev_status is not_asked: Jev is never called on a {mode} task.")
    if mode not in NOT_ASKED_MODES and jev.get("status") == "not_asked" and not (owner_label and mode == "route"):
        raise ValueError("jev_status not_asked belongs to relay and split tasks, and a routed task you labeled.")
    if answers is not None and not owner_label:
        raise ValueError("only a task you labeled answers a floor question.")
    if models is not None:
        if (not isinstance(models, dict) or not models
                or not all(isinstance(a, str) and isinstance(e, dict) and set(e) <= {"model", "effort"}
                           and all(v is None or isinstance(v, str) for v in e.values()) and any(e.values())
                           for a, e in models.items())):
            raise ValueError("a task's models map each agent to its model and effort, at least one of them.")
    if mode == "piece" and (not isinstance(parent, str) or not parent):
        raise ValueError("a piece needs its parent: the split task it belongs to.")
    if parent is not None:  # brief 29 (decision 9): a route piece, or a relay row that is a piece of another team;
        # brief 34 (decision 2): a run's step, a routed or relay task whose parent is the run
        if not isinstance(parent, str) or not parent:
            raise ValueError("a parent is the split task's id.")
        if owner is None:
            raise StateError(f"{parent}: no such task, so no piece can name it")
        if run_step:
            if mode not in ("route", "relay") or plan_step is None:
                raise ValueError("a run's step is a routed or relay task with its plan step.")
        else:
            if mode not in ("piece", "relay"):
                raise ValueError("only a piece has a parent: a route piece or a relay task of a split.")
            if owner["mode"] != "split":
                raise StateError(f"{parent}: not a split task, so it has no pieces")
    if slots is not None:
        if mode not in CHAINED_MODES:
            raise ValueError("only a relay task has slots.")  # (and a plan task, brief 33.1)
        # brief 32 (decision 16): an optional slot left out at intake is kept as null
        if not isinstance(slots, dict) or not all(isinstance(k, str) and (isinstance(v, str) or v is None)
                                                  for k, v in slots.items()):
            raise ValueError("slots map slot names to agent names (or null for a slot left out).")
    if web and mode != "route":
        raise ValueError("only a routed task takes --web.")
    if project is not None:  # brief 29 (decision 12): a split on a project, and its pieces, carry the project too
        if mode not in ("route", "relay", "split", "piece", "plan", "auto", "suggest"):  # brief 33.4: a suggest; brief 33.1: a plan task too; brief 34: a run
            raise ValueError("only a routed, relay or split task, or a piece, has a project.")
        if not isinstance(project, str) or not PROJECT_NAME.fullmatch(project):
            raise ValueError("a project name is lower case letters, digits and -.")
    # brief 33 (decision 8); brief 33.1 (decision 18): `--from` is allowed on `sr plan` too
    if from_task is not None and (mode not in ("route", "relay", "plan") or parent is not None):
        raise ValueError("only a routed or relay task builds from an earlier result; never a split or a piece.")
    if idea is not None and (project is None or not isinstance(idea, int) or isinstance(idea, bool)):
        raise ValueError("an idea is a project's idea id.")
    if chat is not None:
        if project is not None:
            raise ValueError("one tag per task: a task has a project or a chat, never both.")
        if mode not in ("route", "relay") or parent is not None:  # brief 29: a split and its pieces are never tagged so
            raise ValueError("only a routed or relay task has a chat; never a split or a piece.")
        if not isinstance(chat, str) or not PROJECT_NAME.fullmatch(chat):
            raise ValueError("a chat name is lower case letters, digits and -.")
    tokens = jev.get("tokens") or 0
    if not isinstance(tokens, int) or tokens < 0:
        raise ValueError("jev tokens must be a whole number, 0 or more.")
    stamp = _iso(now)
    pid, started = run if run is not None else (None, None)
    conn.execute(
        "INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, jev_label,"
        " jev_confidence, jev_needs_split, jev_tokens, jev_error, status, files, mode, preset, parent, slots, web,"
        " project, chat, pid, run_started_at, from_task, idea, plan, plan_step, models, auto)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (task_id, stamp, stamp, source, task, jev["status"], jev.get("label"), jev.get("confidence"),
         jev.get("needs_split"), tokens, jev.get("error"), json.dumps(list(files)) if files else None, mode, preset,
         parent, json.dumps(slots) if slots is not None else None, 1 if web else None, project, chat, pid, started,
         from_task, idea, json.dumps(plan, ensure_ascii=False) if plan is not None else None,
         json.dumps(plan_step) if plan_step is not None else None,
         json.dumps(models, sort_keys=True) if models is not None else None,
         json.dumps(auto, ensure_ascii=False) if auto is not None else None),
    )
    if answers is not None:  # brief 22 (decision 2): one write, the new row and the floor row's answered_by
        cur = conn.execute("UPDATE tasks SET answered_by = ? WHERE task_id = ? AND status = 'returned'"
                           f" AND reason_code IN ({', '.join('?' for _ in ANSWERABLE_CODES)}) AND answered_by IS NULL",
                           (task_id, answers, *ANSWERABLE_CODES))
        if cur.rowcount != 1:
            conn.rollback()
            raise StateError(f"{answers}: no longer an unanswered floor question")
    conn.commit()


# ---------- runs (build brief 22, decision 4): the process that runs a task ----------

def claim_run(conn, task_id, pid, started):
    """Write a run on a task that no run holds (or that this same run holds already). True when it holds it now.
    `updated_at` is left alone: a run is not a change of state."""
    cur = conn.execute("UPDATE tasks SET pid = ?, run_started_at = ? WHERE task_id = ?"
                       " AND (pid IS NULL OR (pid = ? AND run_started_at IS ?))", (pid, started, task_id, pid, started))
    conn.commit()
    return cur.rowcount == 1


def release_run(conn, task_id, pid, started):
    """Clear a run, only when it is this one (the pid and its start time both match)."""
    cur = conn.execute("UPDATE tasks SET pid = NULL, run_started_at = NULL WHERE task_id = ? AND pid = ?"
                       " AND run_started_at IS ?", (task_id, pid, started))
    conn.commit()
    return cur.rowcount == 1


def clear_run(conn, task_id, pid, started):
    """`sr check` on a dead run: clear the run it judged dead (that pid and that start time, so a fresh run is never
    cleared by mistake)."""
    return release_run(conn, task_id, pid, started)


def cancel_floor_row(conn, task_id):
    """Brief 22 (decision 2): `sr cancel` on an unanswered Jev floor row: `cancelled`, Jev's label and its code kept."""
    cur = conn.execute("UPDATE tasks SET status = 'cancelled', updated_at = ? WHERE task_id = ? AND status = 'returned'"
                       " AND reason_code = 'needs_label' AND answered_by IS NULL", (_iso(), task_id))
    conn.commit()
    if cur.rowcount != 1:
        row = get_task(conn, task_id)
        raise StateError(f"{task_id}: cannot cancel a task that is {row['status'] if row else 'missing'}")


def answering_task(conn, task_id):
    """The task that answered a floor row (its answered_by), or None."""
    row = get_task(conn, task_id)
    return get_task(conn, row["answered_by"]) if row is not None and row["answered_by"] else None


def answered_task(conn, task_id):
    """The floor row a task answered, or None."""
    return conn.execute(f"SELECT {_COLUMNS} FROM tasks WHERE answered_by = ?", (task_id,)).fetchone()


def running_tasks(conn):
    """Every task a run holds, oldest first."""
    return conn.execute(f"SELECT {_COLUMNS} FROM tasks WHERE pid IS NOT NULL ORDER BY rowid").fetchall()


def _split_row(conn, task_id):
    row = get_task(conn, task_id)
    if row is None:
        raise StateError(f"{task_id}: no such task")
    if row["mode"] != "split":
        raise StateError(f"{task_id}: not a split task")
    return row


def set_split_plan(conn, task_id, plan):
    """Store a split's plan (rules v2.18): the joining line and, per piece, the planner's text, the owner's
    edit if any, the piece's task id and its stored label. One JSON text column (build brief 11)."""
    _split_row(conn, task_id)
    conn.execute("UPDATE tasks SET split_plan = ?, updated_at = ? WHERE task_id = ?",
                 (json.dumps(plan, ensure_ascii=False), _iso(), task_id))
    conn.commit()


def split_plan_of(row):
    """A split task's stored plan as a dict, or None (no plan yet, or not a split)."""
    raw = row["split_plan"] if "split_plan" in row.keys() else None
    return json.loads(raw) if raw else None


def plan_of(row):
    """Brief 33.1 (decision 19): a plan task's record (router/plan.py) as a dict, or None."""
    raw = row["plan"] if "plan" in row.keys() else None
    return json.loads(raw) if raw else None


def auto_of(row):
    """Brief 34 (decision 14): a run row's record (router/auto.py) as a dict, or None."""
    raw = row["auto"] if "auto" in row.keys() else None
    return json.loads(raw) if raw else None


def set_auto(conn, task_id, record):
    """Store a run row's record whole (its plan, its steps, the budget, the calls used, the stop, the passed marks)."""
    row = get_task(conn, task_id)
    if row is None or (row["mode"] if "mode" in row.keys() else None) != "auto":
        raise StateError(f"{task_id}: not a run, so it has no auto record")
    conn.execute("UPDATE tasks SET auto = ? WHERE task_id = ?", (json.dumps(record, ensure_ascii=False), task_id))
    conn.commit()


def reopen_run(conn, task_id, run=None):
    """Brief 34 (decision 4): a stopped run (`returned`) goes on: queued again, its note and reason cleared, under the run
    that continues it."""
    pid, started = run if run is not None else (None, None)
    _move(conn, task_id, ("returned",), "queued", check_note=None, reason_code=None, pid=pid, run_started_at=started)


def set_plan(conn, task_id, record):
    """Store a plan task's record whole (its menu, the plan as returned, the owner's edits, the hashes)."""
    row = get_task(conn, task_id)
    if row is None or (row["mode"] if "mode" in row.keys() else None) != "plan":
        raise StateError(f"{task_id}: not a plan task, so it has no plan record")
    conn.execute("UPDATE tasks SET plan = ? WHERE task_id = ?", (json.dumps(record, ensure_ascii=False), task_id))
    conn.commit()


def plan_step_of(row):
    """Brief 33.1 (decision 19): a step task's {plan, step}, or None."""
    raw = row["plan_step"] if "plan_step" in row.keys() else None
    return json.loads(raw) if raw else None


def models_of(row):
    """Brief 33.3 (decision 4): a task's own model choices, {agent: {"model", "effort"}}, or {} (a row from before log
    version 20 too)."""
    raw = row["models"] if "models" in row.keys() else None
    found = json.loads(raw) if raw else {}
    return found if isinstance(found, dict) else {}


def add_jev_tokens(conn, task_id, tokens):
    """Jev's tokens for a piece labeled at plan time go on the split row (the owner's D2), so the monthly sum
    counts them even when no piece row is ever made; the piece row then stores its label with 0 tokens."""
    if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
        raise ValueError("jev tokens must be a whole number, 0 or more.")
    _split_row(conn, task_id)
    conn.execute("UPDATE tasks SET jev_tokens = jev_tokens + ?, updated_at = ? WHERE task_id = ?",
                 (tokens, _iso(), task_id))
    conn.commit()


def set_split_returned(conn, task_id, note):
    """A split waits with the owner (`returned`, the owner's D4): for their approval of the plan, or for its pieces.
    Its doer, checker and check state stay, for the integration."""
    if note != AWAITING_APPROVAL and not note.startswith(WAITING_PIECES):
        raise ValueError(f"a waiting split's note is '{AWAITING_APPROVAL}' or '{WAITING_PIECES} …'.")
    _split_row(conn, task_id)
    _move(conn, task_id, ("queued", "sent", "returned"), "returned", check_note=note)


def reopen_split(conn, task_id, *, agents=None, checker=None, check_state=None, check_note=None):
    """Every piece is delivered or skipped: the split is queued again for its integration. Build brief 24 (decision 4):
    with `check_state`, the integration's checker as it stands now (ChatGPT, or nobody: unchecked with the reason)."""
    row = _split_row(conn, task_id)
    if not (row["check_note"] or "").startswith(WAITING_PIECES):
        raise StateError(f"{task_id}: not waiting for its pieces")
    fields = {"check_note": check_note}
    if check_state is not None:
        _allowed("checker", checker, tuple(agents or ()))
        _allowed("check_state", check_state, CHECK_STATES, required=True)
        fields.update(checker=checker, check_state=check_state)
    _move(conn, task_id, ("returned",), "queued", **fields)


def cancel_waiting_split(conn, task_id):
    """`sr cancel` on a split waiting with the owner (for their approval or its pieces): `cancelled`. Its piece
    rows are not touched. StateError for any other task, so a returned routed task is never cancelled here."""
    row = _split_row(conn, task_id)
    note = row["check_note"] or ""
    if row["status"] != "returned" or not (note == AWAITING_APPROVAL or note.startswith(WAITING_PIECES)):
        raise StateError(f"{task_id}: not a split waiting with you")
    _move(conn, task_id, ("returned",), "cancelled")


def waiting_splits(conn):
    """Split tasks waiting with the owner (for their approval or for their pieces), oldest first."""
    return conn.execute(
        f"SELECT {_COLUMNS} FROM tasks WHERE status = 'returned' AND mode = 'split'"
        " AND (check_note = ? OR check_note LIKE ?) ORDER BY created_at, rowid",
        (AWAITING_APPROVAL, WAITING_PIECES + "%")).fetchall()


def pieces_of(conn, task_id):
    """A split's piece rows, in the order they were made (plan order)."""
    return conn.execute(f"SELECT {_COLUMNS} FROM tasks WHERE parent = ? ORDER BY rowid", (task_id,)).fetchall()


def slots_of(row):
    """A relay task's stored slot map ({slot: agent}), or None (no map: a row from before version 10)."""
    raw = row["slots"] if "slots" in row.keys() else None
    return json.loads(raw) if raw else None


def web_of(row):
    """True when the owner sent the task with --web (rules v2.22)."""
    return bool(row["web"]) if "web" in row.keys() else False


def project_of(row):
    """A task's project name (rules v2.25), or None; rows from before log version 11 read as None."""
    try:
        return row["project"] or None
    except (KeyError, IndexError):
        return None


def handoff_of(row):
    """The writes the router made to the project's handoff file for this task, oldest first: a list of records
    (`kind` entry or line, `text` as written, `lines` the file's line count after, `block_start`, `at`). [] when none."""
    try:
        raw = row["handoff"]
    except (KeyError, IndexError):
        return []
    return json.loads(raw) if raw else []


def add_handoff_write(conn, task_id, record, now=None):
    """Log one write the router made to the project's handoff file for this task (rules v2.25: the write is logged
    on the task row with the file's line count after). Appended; never replaces an earlier write."""
    row = get_task(conn, task_id)
    if row is None:
        raise StateError(f"{task_id}: no such task")
    if not project_of(row):
        raise StateError(f"{task_id}: not a project task, so no handoff write belongs to it")
    for key in ("kind", "text", "lines", "block_start"):
        if key not in record:
            raise ValueError(f"a handoff write record needs {key}.")
    writes = handoff_of(row) + [{**record, "at": _iso(now)}]
    conn.execute("UPDATE tasks SET handoff = ?, updated_at = ? WHERE task_id = ?",
                 (json.dumps(writes), _iso(now), task_id))
    conn.commit()


def chat_of(row):
    """A task's chat name (rules v2.27), or None; rows from before log version 12 read as None."""
    try:
        return row["chat"] or None
    except (KeyError, IndexError):
        return None


def tag_of(row):
    """The task's memory tag: `project:<name>`, `chat:<name>`, or None on an untagged task."""
    project, chat = project_of(row), chat_of(row)
    if project:
        return f"project:{project}"
    if chat:
        return f"chat:{chat}"
    return None


FORGET_KEYS = frozenset({"forgotten", "remembered"})  # brief 30 (decision 15): the owner's Forget and Remember again


def memory_of(row):
    """The retain records the router made for this task, oldest first (rules v2.27, "When"): each
    `{"document_id", "chars", "at", "state"}` or `{"skipped", "at", "state"}`. [] when none."""
    try:
        raw = row["memory"]
    except (KeyError, IndexError):
        return []
    return json.loads(raw) if raw else []


def add_memory_write(conn, task_id, record, now=None):
    """Log one retain the router made (or skipped) for a tagged task, keyed on the ending it was made for (`state`).
    Appended, like the handoff writes; a fallback or a resume that delivers again gets its own record. It leaves
    `updated_at` alone (the owner, 20 Oct): that is the delivery's time, which the task's memory heading shows, so a
    backfill or a rebuild long after the delivery never moves it. Brief 30 (decision 15): a `{"forgotten": <date>}` or
    `{"remembered": <date>}` record is the owner's Forget or Remember again, appended the same way."""
    row = get_task(conn, task_id)
    if row is None:
        raise StateError(f"{task_id}: no such task")
    if not tag_of(row):
        raise StateError(f"{task_id}: not a tagged task, so no memory write belongs to it")
    if FORGET_KEYS & set(record):
        if len(FORGET_KEYS & set(record)) != 1 or not isinstance(record.get("forgotten", record.get("remembered")), str):
            raise ValueError("a Forget record is {forgotten: <date>} or {remembered: <date>}.")
    elif "state" not in record:
        raise ValueError("a memory write record needs state.")
    elif not (("document_id" in record and "chars" in record) or "skipped" in record):
        raise ValueError("a memory write record needs document_id and chars, or skipped.")
    writes = memory_of(row) + [{**record, "at": _iso(now)}]
    conn.execute("UPDATE tasks SET memory = ? WHERE task_id = ?", (json.dumps(writes), task_id))
    conn.commit()


def chats(conn):
    """Every chat name in the log with its task count and its newest task's time, newest first (`sr chat list`)."""
    return conn.execute(
        "SELECT chat, COUNT(*) AS count, MAX(created_at) AS newest FROM tasks WHERE chat IS NOT NULL"
        " GROUP BY chat ORDER BY newest DESC, chat").fetchall()


def chat_exists(conn, name):
    return conn.execute("SELECT 1 FROM tasks WHERE chat = ? LIMIT 1", (name,)).fetchone() is not None


def project_tasks(conn, project):
    """Every task of a project, its pieces too, newest first (brief 33's What now?)."""
    return conn.execute(f"SELECT {_COLUMNS} FROM tasks WHERE project = ? {_NEWEST_FIRST}", (project,)).fetchall()


def recent_tasks_of_chat(conn, name, limit=20):
    return conn.execute(f"SELECT {_COLUMNS} FROM tasks WHERE chat = ? {_NEWEST_FIRST} LIMIT ?", (name, limit)).fetchall()


def open_task_for(conn, project):
    """The newest open task (queued or sent) of a project, or None (rules v2.25: one open task per project).
    A returned task is final here: nothing resumes it and `sr cancel` cannot touch it, so it never blocks. Build brief 28
    (decision 10): a delivered task whose change waits to land is open too, until it is landed or discarded. Build brief 29
    (decision 12): a split is the project's one open task from intake until it ends, lands or is discarded, at its plan
    and on its pieces too (then `returned`); its pieces are its own, never a second task, so a row with a parent is read
    through its split. Build brief 33.4 (decision 5): a plan waiting for answers, and a versus or tied vote awaiting its
    pick, hold the project too; (decision 10b) a running suggest doesn't: it goes beside any task of its project."""
    return conn.execute(
        "SELECT rowid AS n, * FROM tasks WHERE project = ? AND parent IS NULL AND mode != 'suggest' AND (status IN ('queued', 'sent')"
        " OR (mode = 'plan' AND status = 'returned' AND check_note = ?)"
        " OR (mode = 'relay' AND status = 'returned' AND check_note = ?)"
        " OR (status = 'done' AND json_extract(project_files, '$.state') = 'waiting')"
        " OR (mode = 'split' AND status = 'returned' AND (check_note = ? OR check_note LIKE ?))"
        " OR (mode = 'auto' AND status = 'returned'"  # brief 34 (decision 1): a stopped run holds the project while
        " AND COALESCE(json_extract(project_files, '$.state'), 'none') = 'none'))"  # its copy is kept (not discarded)
        " ORDER BY rowid DESC LIMIT 1", (project, AWAITING_ANSWERS, AWAITING_PICK, AWAITING_APPROVAL,
                                         WAITING_PIECES + "%")).fetchone()


def running_suggests(conn, project):
    """Brief 33.4 (decision 10b): the project's open suggest rows, newest first."""
    return conn.execute(f"SELECT {_COLUMNS} FROM tasks WHERE project = ? AND mode = 'suggest' AND status IN ('queued', 'sent') "
                        f"{_NEWEST_FIRST}", (project,)).fetchall()


# ---------- project files (build brief 28, decisions 8, 10 and 19) ----------

FILE_STATES = ("none", "waiting", "landed", "discarded", "undone")
TEST_OUTCOMES = ("passed", "failed", "timed_out", "not_run")


def project_files_of(row):
    """The task's project files record (router/filecalls.py), or None for a task with no --project or from before."""
    raw = row["project_files"] if "project_files" in row.keys() else None
    return json.loads(raw) if raw else None


def set_project_files(conn, task_id, record, now=None):
    """Write the task's project files record whole. Its `state` is one of FILE_STATES."""
    if not isinstance(record, dict) or record.get("state") not in FILE_STATES:
        raise ValueError(f"a project files record needs a state, one of {', '.join(FILE_STATES)}.")
    cur = conn.execute("UPDATE tasks SET project_files = ?, updated_at = ? WHERE task_id = ?",
                       (json.dumps(record, sort_keys=True), _iso(now), task_id))
    if cur.rowcount != 1:
        raise StateError(f"{task_id}: no such task")
    conn.commit()


def update_project_files(conn, task_id, now=None, **fields):
    """Merge `fields` into the task's record (which must exist) and write it."""
    row = get_task(conn, task_id)
    record = project_files_of(row) if row is not None else None
    if record is None:
        raise StateError(f"{task_id}: no project files record")
    record.update(fields)
    set_project_files(conn, task_id, record, now)
    return record


def set_call_tests(conn, call_id, record):
    """Write a call's tests record (build brief 28): the demo's invented runs; a live call writes it with its row."""
    if not isinstance(record, dict) or record.get("outcome") not in TEST_OUTCOMES:
        raise ValueError(f"a call's tests record needs an outcome, one of {', '.join(TEST_OUTCOMES)}.")
    cur = conn.execute("UPDATE calls SET tests = ? WHERE call_id = ?", (json.dumps(record, sort_keys=True), call_id))
    if cur.rowcount != 1:
        raise StateError(f"{call_id}: no such call")
    conn.commit()


def tests_of(call):
    """A call's tests record (build brief 28), or None."""
    raw = call["tests"] if "tests" in call.keys() else None
    return json.loads(raw) if raw else None


def files_of(row):
    """The file records on a task row, as a list (empty when the task carried no files)."""
    raw = row["files"] if "files" in row.keys() else None
    return json.loads(raw) if raw else []


def _move(conn, task_id, allowed_from, status, now=None, **fields):
    """Change a task's status only if it is currently in one of `allowed_from`."""
    fields = {"status": status, "updated_at": _iso(now), **fields}
    sets = ", ".join(f"{name} = ?" for name in fields)
    marks = ", ".join("?" for _ in allowed_from)
    cur = conn.execute(
        f"UPDATE tasks SET {sets} WHERE task_id = ? AND status IN ({marks})",
        (*fields.values(), task_id, *allowed_from),
    )
    conn.commit()
    if cur.rowcount != 1:
        row = get_task(conn, task_id)
        found = row["status"] if row else "missing"
        raise StateError(f"{task_id}: cannot move to {status} from {found}")


def set_route(conn, task_id, *, agents, agent, route_reason, skill=None, skill_source=None,
              checker=None, check_state=None, check_note=None):
    """Store who does a queued task and who checks it. Agent and checker names must be in
    `agents` (the names in config/agents.json), so an unknown name never reaches the log."""
    _allowed("agent", agent, tuple(agents), required=True)
    _allowed("checker", checker, tuple(agents))
    if checker is not None and checker == agent:
        raise ValueError(f"{agent} can't check its own work.")
    _allowed("skill_source", skill_source, SKILL_SOURCES)
    _allowed("check_state", check_state, CHECK_STATES)
    _move(conn, task_id, ("queued",), "queued", skill=skill, skill_source=skill_source, agent=agent,
          route_reason=route_reason, checker=checker, check_state=check_state, check_note=check_note)


def set_returned(conn, task_id, reason, *, reason_code=None, skill=None, skill_source=None):
    """The task came back to the owner and no agent did it. `reason` starts with 'returned: '; `reason_code` (brief 21) is
    the code the router's decision named beside it (routing.Decision.code), one of RETURN_CODES."""
    if not reason.startswith("returned: "):
        raise ValueError("a returned task's reason starts with 'returned: '.")
    _allowed("skill_source", skill_source, SKILL_SOURCES)
    _allowed("reason_code", reason_code, RETURN_CODES)
    _move(conn, task_id, ("queued",), "returned", route_reason=reason, skill=skill,
          skill_source=skill_source, agent=None, checker=None, check_state=None, reason_code=reason_code)


def set_awaiting_pick(conn, task_id):
    """A versus chain's reviews are in (rules v2.16): the task comes back to the owner as `returned` with
    check_note `awaiting pick`. No result, no doer, no checker and no check state until the owner picks:
    `sr pick` names them. `route_reason` stays `relay`."""
    _move(conn, task_id, ("queued", "sent"), "returned", check_note=AWAITING_PICK, check_state=None, agent=None,
          checker=None, result=None)


def set_awaiting_answers(conn, task_id):
    """Brief 33.4 (decisions 3 and 5): a plan asked: the stage-1 rows that led to it stop being the stage (kind `questions`,
    so the call that carries the answers starts stage 1 with its own one re-ask; the rows stay), and the task comes back
    to the owner as `returned`, in one write."""
    fields = {"status": "returned", "check_note": AWAITING_ANSWERS, "updated_at": _iso(None)}
    sets = ", ".join(f"{name} = ?" for name in fields)
    cur = conn.execute(f"UPDATE tasks SET {sets} WHERE task_id = ? AND status IN ('queued', 'sent')",
                       (*fields.values(), task_id))
    if cur.rowcount != 1:
        conn.rollback()
        row = get_task(conn, task_id)
        raise StateError(f"{task_id}: cannot wait for answers from {row['status'] if row else 'missing'}")
    conn.execute("UPDATE calls SET kind = 'questions' WHERE task_id = ? AND stage = 1 AND kind IN ('stage', 'reask')",
                 (task_id,))
    conn.commit()


def answers_given(conn, task_id, run=None):
    """Brief 33.4 (decision 3): the owner answered: the plan goes on, queued again under the run that continues it."""
    pid, started = run if run is not None else (None, None)
    _move(conn, task_id, ("returned",), "queued", check_note=None, pid=pid, run_started_at=started)


PICKS = ("a", "b", "none")


def set_pick(conn, task_id, *, agents, choice, result=None, agent=None, checker=None, verdict=None):
    """The owner's pick on a task awaiting one (rules v2.16, the owner's D3: stored in check_note, no column).
    a or b: `done`, the picked candidate's text as the result, its builder as the doer, its reviewer as
    the checker and the review's verdict as the check (`passed` or `failed`). none: `failed` with the
    reason "no pick". Moves only a `returned` task whose check_note is still `awaiting pick`, so a
    second pick finds nothing to move."""
    _allowed("choice", choice, PICKS, required=True)
    if choice == "none":
        fields = {"status": "failed", "result": "no pick", "check_note": "picked none", "check_state": None,
                  "agent": None, "checker": None}
    else:
        _allowed("agent", agent, tuple(agents), required=True)
        _allowed("checker", checker, tuple(agents), required=True)
        if checker == agent:
            raise ValueError(f"{agent} can't check its own work.")
        _allowed("verdict", verdict, ("pass", "fail"), required=True)
        fields = {"status": "done", "result": result, "agent": agent, "checker": checker,
                  "check_state": "passed" if verdict == "pass" else "failed",
                  "check_note": f"picked {choice}; review by {checker}: {verdict}"}
    _write_pick(conn, task_id, fields)


def _write_pick(conn, task_id, fields):
    """The one guarded write of a pick (build brief 17, choice 5: shared by versus and vote): only a `returned`
    task whose check_note is still `awaiting pick` moves, so a second pick finds nothing to move."""
    fields = {**fields, "updated_at": _iso()}
    sets = ", ".join(f"{name} = ?" for name in fields)
    cur = conn.execute(
        f"UPDATE tasks SET {sets} WHERE task_id = ? AND status = 'returned' AND check_note = ?",
        (*fields.values(), task_id, AWAITING_PICK),
    )
    conn.commit()
    if cur.rowcount != 1:
        row = get_task(conn, task_id)
        raise StateError(f"{task_id}: cannot record a pick on a task that is {row['status'] if row else 'missing'}")


VOTE_PICKS = ("a", "b", "c", "none")


def set_vote_pick(conn, task_id, *, agents, choice, result=None, agent=None):
    """The owner's pick on a vote with no majority (rules v2.24, decision 9). a, b or c: `done`, that voter's stored
    text as the result, its agent as the doer, no checker, `unchecked` (no two agents agreed on it), check_note
    `picked <x>; no majority`. none: `failed`, `no pick`, check_note `picked none; no majority`."""
    _allowed("choice", choice, VOTE_PICKS, required=True)
    if choice == "none":
        fields = {"status": "failed", "result": "no pick", "check_note": "picked none; no majority",
                  "check_state": None, "agent": None, "checker": None}
    else:
        _allowed("agent", agent, tuple(agents), required=True)
        fields = {"status": "done", "result": result, "agent": agent, "checker": None, "check_state": "unchecked",
                  "check_note": f"picked {choice}; no majority"}
    _write_pick(conn, task_id, fields)


def set_tally(conn, task_id, *, agents, agent, result, note):
    """A vote reached a majority (rules v2.24, decision 6): `done`, the first agreeing stage's text as the result,
    its agent as the doer, no checker, `passed`, and the tally (`checked-by-vote 2/1`) as the check note."""
    _allowed("agent", agent, tuple(agents), required=True)
    if not re.fullmatch(r"checked-by-vote [0-9]+/[0-9]+", note or ""):
        raise ValueError(f"a tally note reads checked-by-vote <for>/<against>, not {note!r}")
    _move(conn, task_id, ("queued", "sent"), "done", result=result, agent=agent, checker=None, check_state="passed",
          check_note=note)


def awaiting_pick_tasks(conn):
    """Relay tasks waiting for the owner's pick, oldest first."""
    return conn.execute(
        f"SELECT {_COLUMNS} FROM tasks WHERE status = 'returned' AND mode = 'relay' AND check_note = ?"
        " ORDER BY created_at, rowid", (AWAITING_PICK,)).fetchall()


def set_sent(conn, task_id, run_uuid, now=None, context=None, memory=None):
    """The task's first call went to Grok: the task is `sent`, and the `do` call is logged under
    the task's own id, so Grok's issue is titled as it always was. `context` is the call's context record,
    `memory` its memory record."""
    _move(conn, task_id, ("queued",), "sent", now, run_uuid=run_uuid, sent_at=_iso(now))
    add_call(conn, task_id, task_id, "do", get_task(conn, task_id)["agent"], run_uuid=run_uuid, now=now, context=context,
             memory=memory)


def return_for_context(conn, task_id, note, reason_code):
    """Rules v2.25: the project's handoff could not be sent (it still looks like it holds a key, or the file is
    gone), so the task comes back to the owner before the call: `returned`, the reason in check_note and route_reason,
    the doer and checker kept so the row still says who would have done it. `reason_code` (brief 21): handoff_key or
    handoff_unreadable, named by the caller from the exception it caught."""
    _allowed("reason_code", reason_code, HANDOFF_RETURN_CODES, required=True)
    _move(conn, task_id, ("queued",), "returned", check_note=note, route_reason=f"returned: {note}",
          reason_code=reason_code)


def return_for_memory(conn, task_id, note):
    """Rules v2.29 (the owner, 2026-10-20, after live #103): a tagged recall task whose next call could not get its memory
    (the first call's fresh recall found the store unreachable, or a round's saved block was itself unavailable) comes
    back to the owner before that call: `returned`, the reason in check_note and route_reason, the doer and checker kept;
    earlier call rows stay. Its reason_code is memory_down (brief 21).
    From queued (a Claude or ChatGPT task, before or between its calls) or sent (a Grok call collected)."""
    _move(conn, task_id, ("queued", "sent"), "returned", check_note=note, route_reason=f"returned: {note}",
          reason_code="memory_down")


def set_done(conn, task_id, result, result_url=None, *, check_state=None, check_note=None):
    """The loop has ended: store the furthest result, and the final check state and note when given."""
    _allowed("check_state", check_state, CHECK_STATES)
    fields = {"result": result, "result_url": result_url}
    if check_state is not None:
        fields["check_state"] = check_state
    if check_note is not None:
        fields["check_note"] = check_note
    _move(conn, task_id, ("queued", "sent"), "done", **fields)


def _check_stage(stage):
    if not isinstance(stage, int) or isinstance(stage, bool) or not 1 <= stage <= MAX_STAGES:
        raise ValueError(f"a stage number is a whole number from 1 to {MAX_STAGES}, not {stage!r}.")


BLOCKED = "blocked"  # brief 29.1 (decision 17): a task's check_state and reason_code when its check said BLOCKED


def set_blocked(conn, task_id, result, *, check_note):
    """Brief 29.1 (decision 17): the check said BLOCKED (what the doer needed was not in what it was given, nor anything it
    could find). The task fails with no fix round: status failed, check_state and reason_code blocked, the doer's result
    kept, the note naming what it needed."""
    _move(conn, task_id, ("queued", "sent"), "failed", result=result, check_state=BLOCKED, check_note=check_note,
          reason_code=BLOCKED)


def set_failed(conn, task_id, error, *, failed_stage=None):
    """The task failed. On a relay task, `failed_stage` names the stage that stopped the chain
    (rules v2.12); `error` is the reason, stored in `result` as for any failed task."""
    fields = {"result": error}
    if failed_stage is not None:
        _check_stage(failed_stage)
        fields["failed_stage"] = failed_stage
    _move(conn, task_id, ("queued", "sent"), "failed", **fields)


def reopen_for_resume(conn, task_id, *, agents, agent, checker, check_state, check_note=None):
    """`sr resume` only (rules v2.15): a task that stopped on a plan limit (failed, or done when its
    last round didn't run) is queued again with the doer and checker the resume plan names. Its
    result and failed stage are cleared; the resumed run writes them again when it ends. The
    stopped call rows keep the old text."""
    _allowed("agent", agent, tuple(agents), required=True)
    _allowed("checker", checker, tuple(agents))
    if checker is not None and checker == agent:
        raise ValueError(f"{agent} can't check its own work.")
    _allowed("check_state", check_state, CHECK_STATES, required=True)
    _move(conn, task_id, ("failed", "done"), "queued", agent=agent, checker=checker, check_state=check_state,
          check_note=check_note, result=None, failed_stage=None)


def set_takeover(conn, task_id, *, agents, agent, checker, check_state, check_note=None, now=None):
    """Build brief 24 (decision 6): the router took over a stopped call. The open task's doer, checker, check state and
    note become the takeover's, in one guarded write; the task stays open (queued or sent), its status unchanged."""
    _allowed("agent", agent, tuple(agents), required=True)
    _allowed("checker", checker, tuple(agents))
    if checker is not None and checker == agent:
        raise ValueError(f"{agent} can't check its own work.")
    _allowed("check_state", check_state, CHECK_STATES, required=True)
    cur = conn.execute(
        "UPDATE tasks SET agent = ?, checker = ?, check_state = ?, check_note = ?, updated_at = ?"
        " WHERE task_id = ? AND status IN ('queued', 'sent')",
        (agent, checker, check_state, check_note, _iso(now), task_id))
    conn.commit()
    if cur.rowcount != 1:
        row = get_task(conn, task_id)
        raise StateError(f"{task_id}: cannot take over a task that is {row['status'] if row else 'missing'}")


def reopen_for_fallback(conn, task_id, *, agents, agent, checker, check_state, check_note=None):
    """`sr fallback` only (rules v2.17): a task whose check failed twice (`done`) is queued again with the
    swap: its checker as the doer, its original doer as the checker (None when that agent isn't live; the
    redo is then delivered unchecked). Its result is cleared; the redo's run writes it again. The original
    rows keep the original result and fix list."""
    _allowed("agent", agent, tuple(agents), required=True)
    _allowed("checker", checker, tuple(agents))
    if checker is not None and checker == agent:
        raise ValueError(f"{agent} can't check its own work.")
    _allowed("check_state", check_state, CHECK_STATES, required=True)
    _move(conn, task_id, ("done",), "queued", agent=agent, checker=checker, check_state=check_state,
          check_note=check_note, result=None, result_url=None, failed_stage=None)


def set_cancelled(conn, task_id, allowed_from=("queued", "sent")):
    _move(conn, task_id, tuple(allowed_from), "cancelled")


def set_open_status(conn, task_id, status):
    """While the loop runs, a task is `sent` whenever a Grok call is out and `queued` otherwise."""
    _allowed("status", status, ("queued", "sent"), required=True)
    _move(conn, task_id, ("queued", "sent"), status)


GROK_NOTES = ("waiting: grok", "overdue: grok")  # brief 21, C2 (decision 5): the Grok timeout note's two forms


def grok_note(sent_at, now, n):
    """The Grok timeout note for a call sent at `sent_at` (ISO), at `now`: None before N minutes (or with no N),
    `waiting: grok, <m> min` from N, `overdue: grok, <m> min` from 2N; m is the whole minutes since the send."""
    if not n:
        return None
    minutes = (_utc(now) - datetime.fromisoformat(sent_at)).total_seconds() / 60
    if minutes < n:
        return None
    return f"{GROK_NOTES[1] if minutes >= 2 * n else GROK_NOTES[0]}, {int(minutes)} min"


def set_grok_note(conn, task_id, note):
    """Write the Grok timeout note on an open task, or clear it (None), only where `check_note` is empty or already a
    Grok note (the owner's C6: never over a real note). True when the row changed."""
    cur = conn.execute(
        "UPDATE tasks SET check_note = ? WHERE task_id = ? AND status IN ('queued', 'sent')"
        " AND (check_note IS NULL OR check_note LIKE ? OR check_note LIKE ?) AND check_note IS NOT ?",
        (note, task_id, GROK_NOTES[0] + "%", GROK_NOTES[1] + "%", note))
    conn.commit()
    return cur.rowcount == 1


def set_check_state(conn, task_id, check_state, note=None):
    """Change an open task's check state (and its note, when given) without moving its status."""
    _allowed("check_state", check_state, CHECK_STATES, required=True)
    fields = {"check_state": check_state}
    if note is not None:
        fields["check_note"] = note
    sets = ", ".join(f"{name} = ?" for name in fields)
    cur = conn.execute(
        f"UPDATE tasks SET {sets}, updated_at = ? WHERE task_id = ? AND status IN ('queued', 'sent')",
        (*fields.values(), _iso(), task_id),
    )
    conn.commit()
    if cur.rowcount != 1:
        row = get_task(conn, task_id)
        raise StateError(f"{task_id}: cannot change the check state of a task that is {row['status'] if row else 'missing'}")


def jev_tokens_this_month(conn, now=None):
    """Jev input tokens logged this calendar month (UTC). The monthly cap is checked against this."""
    start = _utc(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=32)).replace(day=1)
    row = conn.execute(
        "SELECT COALESCE(SUM(jev_tokens), 0) FROM tasks WHERE created_at >= ? AND created_at < ?",
        (_iso(start), _iso(end)),
    ).fetchone()
    return row[0]


# A task's number ('#' in `log`) is SQLite's built-in rowid. It stays stable as long as
# no row is deleted and the table is never rebuilt without copying rowid explicitly.
_COLUMNS = "rowid AS n, *"
_NEWEST_FIRST = "ORDER BY created_at DESC, rowid DESC"
MAX_NUMBER = 2**63 - 1  # largest rowid SQLite can store


def get_task(conn, task_id):
    return conn.execute(f"SELECT {_COLUMNS} FROM tasks WHERE task_id = ?", (task_id,)).fetchone()


def task_by_number(conn, n):
    if not 0 < n <= MAX_NUMBER:
        return None
    return conn.execute(f"SELECT {_COLUMNS} FROM tasks WHERE rowid = ?", (n,)).fetchone()


def newest_task(conn):
    return conn.execute(f"SELECT {_COLUMNS} FROM tasks {_NEWEST_FIRST} LIMIT 1").fetchone()


def find_task(conn, text):
    """The task a command names (rules v2.30, Router for the interface, "Ids everywhere"; build brief 21): `5` or `#5` by
    its number, or an `sr-` task id, exactly or as the prefix of exactly one id. (row, None, None); or (None, message,
    code): `unknown_task` when nothing matches, `ambiguous_task` when a prefix matches more than one (the message names
    them), `usage` when the text is neither a number nor an id. Numbers repeat across logs; an id never does."""
    text = (text or "").strip()
    number = re.fullmatch(r"#?([0-9]+)", text)
    if number:
        row = task_by_number(conn, int(number.group(1)))
        return (row, None, None) if row is not None else (None, f"No task #{number.group(1)}.", "unknown_task")
    if not text.startswith("sr-"):
        return None, None, "usage"
    row = get_task(conn, text)
    if row is not None:
        return row, None, None
    found = conn.execute(f"SELECT {_COLUMNS} FROM tasks WHERE substr(task_id, 1, ?) = ? ORDER BY rowid LIMIT 6",
                         (len(text), text)).fetchall()
    if len(found) == 1:
        return found[0], None, None
    if not found:
        return None, f"No task {text}.", "unknown_task"
    shown = ", ".join(f"#{r['n']} {r['task_id']}" for r in found[:5]) + (", …" if len(found) > 5 else "")
    return None, f"{text} matches more than one task: {shown}. Give more of the id.", "ambiguous_task"


def newest_task_containing(conn, words):
    """Case-insensitive plain-text match (instr, so % and _ are not wildcards)."""
    return conn.execute(
        f"SELECT {_COLUMNS} FROM tasks WHERE instr(lower(task), lower(?)) > 0 {_NEWEST_FIRST} LIMIT 1",
        (words,),
    ).fetchone()


def open_tasks(conn):
    """Tasks that are still queued or sent, newest first."""
    return conn.execute(
        f"SELECT {_COLUMNS} FROM tasks WHERE status IN ('queued', 'sent') {_NEWEST_FIRST}"
    ).fetchall()


def recent_tasks(conn, limit=20):
    return conn.execute(f"SELECT {_COLUMNS} FROM tasks {_NEWEST_FIRST} LIMIT ?", (limit,)).fetchall()


def task_rows(conn, limit=20, *, project=None, chat=None, search=None, before=None):
    """`sr log`'s rows, newest first (build brief 21, B3): only a project's or a chat's, only those whose text holds
    `search` (any case, plain text: never a wildcard), only those older than the row `before` (paging)."""
    where, args = [], []
    if project is not None:
        where.append("project = ?")
        args.append(project)
    if chat is not None:
        where.append("chat = ?")
        args.append(chat)
    if search:
        where.append("instr(lower(task), lower(?)) > 0")
        args.append(search)
    if before is not None:
        where.append("(created_at < ? OR (created_at = ? AND rowid < ?))")
        args += [before["created_at"], before["created_at"], before["n"]]
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    return conn.execute(f"SELECT {_COLUMNS} FROM tasks{clause} {_NEWEST_FIRST} LIMIT ?", (*args, limit)).fetchall()


# ---------- calls: one row per agent call ----------

def stamp(now=None):
    """Now, as the log writes times (brief 29.1, issue 8: a call's `sent_at` taken before it is sent)."""
    return _iso(now)


def add_call(conn, call_id, task_id, kind, agent, status="sent", *, text=None, verdict=None, url=None,
             run_uuid=None, now=None, stage=None, role=None, reason_code=None, resume_of=None, search=None,
             fallback_of=None, context=None, memory=None, served=None, tests=None, sent_at=None, model=None, effort=None,
             time_limit=None):
    """Log one agent call. A Grok call is `sent` and finished later (finish_call); a Claude call
    returns at once, so it is written already finished, in one go. A `stage` or `reask` call
    (relay) carries its stage number and role; no other kind does. A failed call may carry a
    `reason_code` (plan_limit); a call made by `sr resume` names the call it replaces in `resume_of`.
    `search` is the call's search record (router/search.py): a dict with `state` and, when known,
    `queries` and `count`. A call made by `sr fallback` names the original doer's call it replaces in
    `fallback_of` (rules v2.17). `context` (rules v2.25) is the call's context record: a dict naming its `project`
    and what of the handoff went with the call (router/context.py). `memory` (rules v2.27) is the call's memory record:
    a dict naming its `tag` and the block as sent (`sent`, `found`, `text`), or `left_out`, or `unavailable`
    (router/memory.py). `served` (rules v2.28, Cursor) is a Cursor call's record: a dict naming the model the stream served
    (`model`, verbatim), the id asked for (`asked`), the tool events counted (`tool_events`) and named (`tools`), with
    `duration_ms`, `permission_mode`, `usage` and `stream` when known (router/cursor_worker.py); None on every other call.
    `tests` (build brief 28, decision 5) is a file-mode build or fix call's tests record: `outcome` (passed, failed,
    timed_out or not_run), `exit`, `summary`, `output` (the file beside the log), the `command`, and `why` when not run.
    Brief 33.3 (decision 7): `model` is the model the call asked for, `effort` its level when one was set, `time_limit`
    its seconds; `served` takes every agent's record (`asked` and `model`, the model that answered, or None) since then."""
    _allowed("call kind", kind, CALL_KINDS, required=True)
    _allowed("call status", status, CALL_STATUSES, required=True)
    _allowed("verdict", verdict, VERDICTS)
    _allowed("reason_code", reason_code, REASON_CODES)
    if reason_code is not None and status != "failed":
        raise ValueError("only a failed call carries a reason_code.")
    if search is not None:
        if not isinstance(search, dict) or search.get("state") not in SEARCH_STATES:
            raise ValueError(f"a call's search record needs a state, one of {', '.join(SEARCH_STATES)}.")
        search = json.dumps(search, sort_keys=True)
    if context is not None:  # brief 30 (decision 9): a call that carried router notes alone has `notes` and no project
        # brief 33 (decision 9): and a call that carried a from-block alone has `from`
        if not isinstance(context, dict) or not (context.get("project") or isinstance(context.get("notes"), dict)
                                                 or isinstance(context.get("from"), dict)):
            raise ValueError("a call's context record names its project, or holds its router notes or from record.")
        context = json.dumps(context, sort_keys=True)
    if memory is not None:
        if not isinstance(memory, dict) or not memory.get("tag"):
            raise ValueError("a call's memory record names its tag.")
        memory = json.dumps(memory, sort_keys=True)
    if served is not None:
        if (not isinstance(served, dict) or not isinstance(served.get("asked"), str)
                or ("tool_events" in served and (isinstance(served.get("tool_events"), bool)
                                                 or not isinstance(served.get("tool_events"), int)))):
            raise ValueError("a call's served record names the asked model (and counts Cursor's tool events).")
        served = json.dumps(served, sort_keys=True)
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise ValueError("a call's model is the name it asked for.")
    if effort is not None and (not isinstance(effort, str) or not effort.strip()):
        raise ValueError("a call's effort is a level name.")
    if time_limit is not None and (isinstance(time_limit, bool) or not isinstance(time_limit, int) or time_limit <= 0):
        raise ValueError("a call's time limit is whole seconds above 0.")
    if tests is not None:
        if not isinstance(tests, dict) or tests.get("outcome") not in TEST_OUTCOMES:
            raise ValueError(f"a call's tests record needs an outcome, one of {', '.join(TEST_OUTCOMES)}.")
        tests = json.dumps(tests, sort_keys=True)
    if kind in STAGE_KINDS:
        _check_stage(stage)
        if not isinstance(role, str) or not _ROLE.fullmatch(role):
            raise ValueError(f"a stage call needs a plain lowercase role word, not {role!r}.")
    elif stage is not None or role is not None:
        raise ValueError(f"only a stage or reask call has a stage number and a role, not a {kind} call.")
    if get_task(conn, task_id) is None:
        raise StateError(f"{task_id}: no such task, so no call can be logged for it")
    if resume_of is not None:
        replaced = get_call(conn, resume_of)
        if replaced is None or replaced["task_id"] != task_id:
            raise StateError(f"{call_id}: resume_of {resume_of!r} is not a call of {task_id}")
    if fallback_of is not None:
        replaced = get_call(conn, fallback_of)
        if replaced is None or replaced["task_id"] != task_id:
            raise StateError(f"{call_id}: fallback_of {fallback_of!r} is not a call of {task_id}")
    stamp = _iso(now)
    conn.execute(  # brief 29.1 (issue 8): a call written once it ended keeps the time it was sent (`sent_at`)
        "INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at, finished_at, run_uuid, text, verdict, url,"
        " stage, role, reason_code, resume_of, search, fallback_of, context, memory, served, tests, model, effort,"
        " time_limit)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (call_id, task_id, kind, agent, status, sent_at or stamp, None if status == "sent" else stamp, run_uuid,
         text, verdict, url, stage, role, reason_code, resume_of, search, fallback_of, context, memory, served, tests,
         model, effort, time_limit),
    )
    conn.commit()
    if ROUND_WRITER is not None and status != "sent" and text is not None:
        ROUND_WRITER(conn, call_id)


def finish_call(conn, call_id, status, *, text=None, verdict=None, url=None, now=None):
    """A sent call came back (done), failed, or timed out."""
    _allowed("call status", status, ("done", "failed", "timed_out"), required=True)
    _allowed("verdict", verdict, VERDICTS)
    cur = conn.execute(
        "UPDATE calls SET status = ?, finished_at = ?, text = ?, verdict = ?, url = ?"
        " WHERE call_id = ? AND status = 'sent'",
        (status, _iso(now), text, verdict, url, call_id),
    )
    conn.commit()
    if cur.rowcount != 1:
        call = get_call(conn, call_id)
        raise StateError(f"{call_id}: cannot finish a call that is {call['status'] if call else 'missing'}")
    if ROUND_WRITER is not None and status != "timed_out" and text is not None:
        ROUND_WRITER(conn, call_id)  # a Grok call's round file, written when it is collected


def set_round_file(conn, call_id, name):
    """Names a call's round file on its row, once (rules v2.30, Round outputs)."""
    cur = conn.execute("UPDATE calls SET round_file = ? WHERE call_id = ? AND round_file IS NULL", (name, call_id))
    conn.commit()
    return cur.rowcount == 1


def fallback_of(call):
    """The id of the call a `sr fallback` row replaces, or None (rows from before version 8 too)."""
    return call["fallback_of"] if "fallback_of" in call.keys() else None


def fallback_view(calls):
    """The rows the step functions see (rules v2.17, Fallback). A fallback doer's call that came back
    (done) replaces the call it names and every row after that one, so the redo's check loop starts fresh
    while every row stays in the log. A fallback call that stopped (failed: a plan limit, an error) is
    left out entirely: it does not count as the one fallback and changes nothing. With no fallback, the
    rows as they are."""
    calls = [c for c in calls if not (fallback_of(c) and c["status"] == "failed")]
    done = [i for i, c in enumerate(calls) if fallback_of(c)]
    if not done:
        return list(calls)
    j = done[-1]
    i = next((k for k, c in enumerate(calls) if c["call_id"] == fallback_of(calls[j])), j)
    return calls[:i] + calls[j:]


def fallback_base(task_id, calls):
    """The id the next call ids are built on: the fallback row's id once a fallback ran (so the redo's
    check is `<task>-fb1-c1`, never the original's `<task>-c1`), else the task id."""
    rows = [c for c in fallback_view(calls) if fallback_of(c)]
    if rows:
        return rows[-1]["call_id"]
    # brief 33.4 (decision 3): the call that carries the answers is stage 1 again, under ids of its own
    return f"{task_id}-a" if any(c["kind"] == "questions" for c in calls) else task_id


def context_of(call):
    """A call's context record (rules v2.25), or None; rows from before log version 11 read as None."""
    try:
        raw = call["context"]
    except (KeyError, IndexError):
        return None
    return json.loads(raw) if raw else None


def call_memory_of(call):
    """A call's memory record (rules v2.27), or None; rows from before log version 12 read as None."""
    try:
        raw = call["memory"]
    except (KeyError, IndexError):
        return None
    return json.loads(raw) if raw else None


def served_of(call):
    """A call's served record (rules v2.28 for Cursor; brief 33.3 for Claude and ChatGPT), or None; a row from before log
    version 13, or before version 20 on Claude and ChatGPT, reads None."""
    try:
        raw = call["served"]
    except (KeyError, IndexError):
        return None
    return json.loads(raw) if raw else None


def search_of(call):
    """A call's search record as a dict, or None (not eligible, or a row from before version 7)."""
    raw = call["search"] if "search" in call.keys() else None
    return json.loads(raw) if raw else None


def get_call(conn, call_id):
    return conn.execute("SELECT rowid AS n, * FROM calls WHERE call_id = ?", (call_id,)).fetchone()


def calls_for(conn, task_id):
    """A task's calls, oldest first."""
    return conn.execute(
        "SELECT rowid AS n, * FROM calls WHERE task_id = ? ORDER BY sent_at, rowid", (task_id,)
    ).fetchall()


_OPEN_GROK_CALLS = (
    "FROM calls c JOIN tasks t ON t.task_id = c.task_id"
    " WHERE c.agent = 'grok' AND c.status = 'sent' AND t.status IN ('queued', 'sent')"
)


def open_grok_calls(conn):
    """Grok calls still out, for tasks still open. Their ids are the inbox issue titles to look for."""
    rows = conn.execute(f"SELECT c.call_id {_OPEN_GROK_CALLS} ORDER BY c.sent_at, c.rowid")
    return [row["call_id"] for row in rows]


def minutes_since(sent_at, now=None):
    """Whole and part minutes from `sent_at` (ISO) to `now`."""
    return (_utc(now) - datetime.fromisoformat(sent_at)).total_seconds() / 60


def mark_overdue(conn, call_id, now=None):
    """Build brief 24 (decision 6): a Grok call still out at 2N is taken over. Its row becomes failed with code
    `overdue`, guarded on `sent`, so an answer collected a moment ago wins. True when the row changed."""
    cur = conn.execute("UPDATE calls SET status = 'failed', reason_code = 'overdue', finished_at = ?"
                       " WHERE call_id = ? AND status = 'sent'", (_iso(now), call_id))
    conn.commit()
    return cur.rowcount == 1


def mark_skipped(conn, call_id):
    """Build brief 32 (decision 11): an optional stage is skipped, said by its row's reason code; the row's status and
    text (its own words: the failure, or the list that missed its contract) are kept. True when the row changed."""
    cur = conn.execute("UPDATE calls SET reason_code = 'skipped' WHERE call_id = ? AND (reason_code IS NULL OR "
                       "reason_code != 'skipped')", (call_id,))
    conn.commit()
    return cur.rowcount == 1


def late_grok_calls(conn, now=None, minutes=30):
    """Build brief 24 (decision 7): Grok calls taken over at overdue whose answer may still come: code `overdue`, sent
    within the last `minutes` (the Grok timeout), whatever their task's status now. Their ids are issue titles too."""
    cutoff = _iso(_utc(now) - timedelta(minutes=minutes))
    rows = conn.execute("SELECT call_id FROM calls WHERE agent = 'grok' AND status = 'failed' AND reason_code = 'overdue'"
                        " AND sent_at >= ? ORDER BY sent_at, rowid", (cutoff,))
    return [row["call_id"] for row in rows]


def store_late(conn, call_id, text, url=None, now=None):
    """Build brief 24 (decision 7): a late Grok answer is stored on its overdue row, marked `late`, and changes nothing
    else (never a result, never checked, never in memory). Guarded on `overdue`, so a second copy finds nothing. Its
    round file is written then. True when the row changed."""
    cur = conn.execute("UPDATE calls SET reason_code = 'late', text = ?, url = ?, finished_at = ?"
                       " WHERE call_id = ? AND status = 'failed' AND reason_code = 'overdue'",
                       (text, url, _iso(now), call_id))
    conn.commit()
    if cur.rowcount != 1:
        return False
    if ROUND_WRITER is not None and text is not None:
        ROUND_WRITER(conn, call_id)
    return True


def mark_timeouts(conn, now=None, minutes=30):
    """Grok calls out for longer than `minutes` are marked timed_out. A timed-out `do` call ends
    its task as timed_out (nothing was made); for any other kind the loop decides how the task
    ends. Returns the call ids it moved."""
    cutoff = _iso(_utc(now) - timedelta(minutes=minutes))
    stale = conn.execute(
        f"SELECT c.call_id, c.task_id, c.kind {_OPEN_GROK_CALLS} AND c.sent_at < ? ORDER BY c.sent_at, c.rowid",
        (cutoff,),
    ).fetchall()
    moved = []
    for call in stale:
        if call["kind"] == "do":
            try:
                _move(conn, call["task_id"], ("sent",), "timed_out", now)
            except StateError:
                continue  # another command finished or cancelled it a moment ago
        try:
            finish_call(conn, call["call_id"], "timed_out", now=now)
        except StateError:
            continue
        moved.append(call["call_id"])
    return moved


# ---------- the one-time moves between log versions ----------

def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _rows_content(conn, columns, call_columns=None):
    """Every task row's rowid and the given columns, in rowid order, and, when `call_columns` is given, every call row
    the same way: what the content hash is taken over."""
    rows = conn.execute(f"SELECT rowid, {', '.join(columns)} FROM tasks ORDER BY rowid").fetchall()
    content = [list(r) for r in rows]
    if call_columns:
        calls = conn.execute(f"SELECT rowid, {', '.join(call_columns)} FROM calls ORDER BY rowid").fetchall()
        content.append([list(r) for r in calls])
    return content


def _content_hash(conn, columns, call_columns=None):
    """A hash of every task row's rowid and the given columns, in rowid order, and, when
    `call_columns` is given, of every call row the same way."""
    return hashlib.sha256(json.dumps(_rows_content(conn, columns, call_columns), default=str).encode()).hexdigest()


def _renamed_content_hash(conn, columns, call_columns=None):
    """The content hash as version 16's one rename leaves the rows (build brief 25): a skill_source that is neither of
    today's values nor empty reads `owner`. The upgrade's check after compares against this, so any other change fails."""
    content = _rows_content(conn, columns, call_columns)
    if "skill_source" in columns:
        at = 1 + list(columns).index("skill_source")
        for row in content[:len(content) - (1 if call_columns else 0)]:
            if row[at] is not None and row[at] not in SKILL_SOURCES:
                row[at] = "owner"
    return hashlib.sha256(json.dumps(content, default=str).encode()).hexdigest()


def _refuse_half_finished_saves(db_path):
    """A `-journal` beside the log means a save may be half finished: refused. A log in WAL mode keeps `-wal` and `-shm`
    beside it while any command has it open, and a read-only open leaves them behind (build brief 22): its WAL is
    checkpointed into the file first, and the migration is refused only when another command holds the log. A log not in
    WAL mode with those files beside it is refused, as before."""
    db_path = Path(db_path)
    journal = db_path.with_name(db_path.name + "-journal")
    if journal.exists():
        raise MigrateRefused(f"{journal.name} exists, so a save may be half finished. "
                             "Try again once no other command is running.")
    leftover = [s for s in ("-wal", "-shm") if db_path.with_name(db_path.name + s).exists()]
    if not leftover:
        return
    try:
        mode = _journal_mode(db_path)
    except sqlite3.DatabaseError as e:
        raise MigrateRefused(f"could not read {db_path.name} ({type(e).__name__}).") from None
    if mode != "wal":
        raise MigrateRefused(f"{db_path.name}{leftover[0]} exists, so a save may be half finished. "
                             "Try again once no other command is running.")
    try:
        conn = connect(db_path)
        try:
            conn.execute("PRAGMA busy_timeout = 0")  # never wait here: a holder means another command is running
            busy = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.OperationalError:
        busy = 1
    if busy:
        raise MigrateRefused(f"another command has the log open ({db_path.name}). Try again once no other command is "
                             "running.")


def _journal_mode(db_path):
    conn = _read_only(db_path)
    try:
        return conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()


def backup_copy(db_path, backup):
    """A copy of the log made with SQLite's backup API (build brief 22, decision 6), read from a read-only connection,
    into a new owner-only file. Unlike a file copy it includes what a WAL holds that is not yet in the file. Raises
    FileExistsError when `backup` exists (nothing is overwritten)."""
    backup = Path(backup)
    os.close(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    os.chmod(backup, 0o600)
    src = _read_only(db_path)
    try:
        dst = sqlite3.connect(backup)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    for suffix in ("-wal", "-shm"):  # the copy of a WAL source is itself WAL: fold it into the one file
        if backup.with_name(backup.name + suffix).exists():
            c = sqlite3.connect(backup)
            try:
                c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                c.close()
            break
    return backup


def _peek(db_path):
    """A log's version and task columns, read-only. MigrateRefused if it can't be read."""
    try:
        conn = _read_only(db_path)
        try:
            return _version(conn), _columns(conn)
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        raise MigrateRefused(f"could not read {db_path.name} ({type(e).__name__}).") from None


def migrate(db_path, backups_dir, now=None):
    """`sr migrate`: a version 1 log is moved into backups/ and replaced by an empty log (move_v1);
    a version 2 log is upgraded in place after a backup copy (upgrade_v2_to_v3)."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise MigrateRefused(f"there is no {db_path.name} to migrate.")
    version, columns = _peek(db_path)
    if version == VERSION:
        raise MigrateRefused(f"{db_path.name} is already a version {VERSION} log.")
    if version in UPGRADES:
        return _upgrade_in_place(db_path, backups_dir, now, version)
    if version == 0 and set(columns) == set(V1_COLUMNS):
        return move_v1(db_path, backups_dir, now)
    raise MigrateRefused(f"{db_path.name} is not a version 1 to {VERSION - 1} log.")


def move_v1(db_path, backups_dir, now=None):
    """Move a version 1 log into backups/ and start an empty log in its place.
    Every check runs before anything moves; a failed check raises MigrateRefused.
    Returns {"job": "move", "rows", "backup", "sha256"}."""
    db_path, backups_dir = Path(db_path), Path(backups_dir)
    if not db_path.exists():
        raise MigrateRefused(f"there is no {db_path.name} to migrate.")
    try:
        conn = _read_only(db_path)
        try:
            version, columns = _version(conn), _columns(conn)
            if version == VERSION:
                raise MigrateRefused(f"{db_path.name} is already a version {VERSION} log.")
            if version != 0 or set(columns) != set(V1_COLUMNS):
                raise MigrateRefused(f"{db_path.name} is not a version 1 log.")
            still_open = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status IN ('queued', 'sent')").fetchone()[0]
            if still_open:
                raise MigrateRefused(f"{still_open} task(s) are still queued or sent.")
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise MigrateRefused(f"its integrity check failed ({integrity[:80]}).")
            rows = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        raise MigrateRefused(f"could not read {db_path.name} ({type(e).__name__}).") from None

    _refuse_half_finished_saves(db_path)
    backup = backups_dir / f"router-v1-final-{_utc(now):%Y-%m-%d}.db"
    if backup.exists():
        raise MigrateRefused(f"{backups_dir.name}/{backup.name} already exists.")

    before = _sha256(db_path)
    backups_dir.mkdir(exist_ok=True)
    try:
        os.rename(db_path, backup)  # a move on the same disk: the bytes are not rewritten
    except OSError as e:
        raise MigrateRefused(f"could not move {db_path.name} ({type(e).__name__}).") from None
    os.chmod(backup, 0o600)  # owner-only, like the other backups

    after = _sha256(backup)
    try:
        conn = _read_only(backup)
        try:
            rows_after = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        rows_after = None
    if (after, rows_after) != (before, rows):
        raise MigrateFailed(f"the moved file doesn't match what was checked ({rows} rows before, "
                            f"{rows_after} after). It is at {backup}. No new log was made.")
    init_db(db_path).close()
    return {"job": "move", "rows": rows, "backup": backup, "sha256": before}


def upgrade_v2_to_v3(db_path, backups_dir, now=None):
    """A version 2 log, upgraded in place (it lands on the current version)."""
    return _upgrade_in_place(db_path, backups_dir, now, 2)


def upgrade_v3_to_v4(db_path, backups_dir, now=None):
    """A version 3 log, upgraded in place (it lands on the current version)."""
    return _upgrade_in_place(db_path, backups_dir, now, 3)


def upgrade_v4_to_v5(db_path, backups_dir, now=None):
    """A version 4 log, upgraded in place: the relay columns (build brief 5)."""
    return _upgrade_in_place(db_path, backups_dir, now, 4)


def upgrade_v5_to_v6(db_path, backups_dir, now=None):
    """A version 5 log, upgraded in place: the resume columns on calls (build brief 7)."""
    return _upgrade_in_place(db_path, backups_dir, now, 5)


def upgrade_v6_to_v7(db_path, backups_dir, now=None):
    """A version 6 log, upgraded in place: the search column on calls (build brief 8)."""
    return _upgrade_in_place(db_path, backups_dir, now, 6)


def upgrade_v7_to_v8(db_path, backups_dir, now=None):
    """A version 7 log, upgraded in place: the fallback column on calls (build brief 10)."""
    return _upgrade_in_place(db_path, backups_dir, now, 7)


def upgrade_v8_to_v9(db_path, backups_dir, now=None):
    """A version 8 log, upgraded in place: the split columns on tasks (build brief 11)."""
    return _upgrade_in_place(db_path, backups_dir, now, 8)


def upgrade_v10_to_v11(db_path, backups_dir, now=None):
    """A version 10 log, upgraded in place: project and handoff on tasks, context on calls (build brief 18)."""
    return _upgrade_in_place(db_path, backups_dir, now, 10)


def upgrade_v11_to_v12(db_path, backups_dir, now=None):
    """A version 11 log, upgraded in place: chat and memory on tasks, memory on calls (build brief 19)."""
    return _upgrade_in_place(db_path, backups_dir, now, 11)


def upgrade_v12_to_v13(db_path, backups_dir, now=None):
    """A version 12 log, upgraded in place: served on calls (build brief 20)."""
    return _upgrade_in_place(db_path, backups_dir, now, 12)


def upgrade_v15_to_v16(db_path, backups_dir, now=None):
    """A version 15 log, upgraded in place: the owner's stored value renamed (build brief 25)."""
    return _upgrade_in_place(db_path, backups_dir, now, 15)


def upgrade_v17_to_v18(db_path, backups_dir, now=None):
    """A version 17 log, upgraded in place: from_task and idea on tasks, the ideas table (build brief 33)."""
    return _upgrade_in_place(db_path, backups_dir, now, 17)


def upgrade_v16_to_v17(db_path, backups_dir, now=None):
    """A version 16 log, upgraded in place: project_files on tasks, tests on calls (build brief 28)."""
    return _upgrade_in_place(db_path, backups_dir, now, 16)


def upgrade_v13_to_v14(db_path, backups_dir, now=None):
    """A version 13 log, upgraded in place: reason_code on tasks, round_file on calls (build brief 21)."""
    return _upgrade_in_place(db_path, backups_dir, now, 13)


def _upgrade_in_place(db_path, backups_dir, now, from_version):
    """Upgrade a log in place: copy it into backups/ first, then add what the current version has
    and this one lacks in one transaction, then check that no task row (and no call row, when the
    calls table already existed) changed. Build brief 22 (decision 6): the copy is made with SQLite's backup API, so
    nothing a WAL holds is lost, and checked by its content (integrity, version, counts, a hash over every column of the
    version it was), since a backup-API copy is not byte for byte the file; after the upgrade the log is set to WAL.
    Returns {"job": "upgrade", "from", "added", "rows", "calls", "highest", "backup", "sha256", "content_hash",
    "backup_check", "journal_mode"}."""
    plan = UPGRADES[from_version]
    old_columns, call_columns = plan["columns"], plan.get("call_columns")
    db_path, backups_dir = Path(db_path), Path(backups_dir)
    if not db_path.exists():
        raise MigrateRefused(f"there is no {db_path.name} to migrate.")
    try:
        conn = _read_only(db_path)
        try:
            version, columns = _version(conn), _columns(conn)
            if version == VERSION:
                raise MigrateRefused(f"{db_path.name} is already a version {VERSION} log.")
            if version != from_version or set(columns) != set(old_columns):
                raise MigrateRefused(f"{db_path.name} is not a version {from_version} log.")
            still_open = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status IN ('queued', 'sent')").fetchone()[0]
            if still_open:
                raise MigrateRefused(f"{still_open} task(s) are still queued or sent.")
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise MigrateRefused(f"its integrity check failed ({integrity[:80]}).")
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        raise MigrateRefused(f"could not read {db_path.name} ({type(e).__name__}).") from None

    _refuse_half_finished_saves(db_path)
    try:  # the counts and the hash after the save check, which may have folded a WAL into the file
        conn = _read_only(db_path)
        try:
            rows, highest, calls, content = _counts(conn, old_columns, call_columns)
            renamed = _renamed_content_hash(conn, old_columns, call_columns)  # what version 16 leaves
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        raise MigrateRefused(f"could not read {db_path.name} ({type(e).__name__}).") from None
    backup = backups_dir / f"router-v{from_version}-{_utc(now):%Y-%m-%d}.db"
    if backup.exists():
        raise MigrateRefused(f"{backups_dir.name}/{backup.name} already exists.")

    before = _sha256(db_path)
    backups_dir.mkdir(exist_ok=True)
    try:
        backup_copy(db_path, backup)
    except (OSError, sqlite3.Error) as e:
        backup.unlink(missing_ok=True)
        raise MigrateRefused(f"could not copy {db_path.name} into {backups_dir.name}/ ({type(e).__name__}).") from None
    checked = _check_backup(backup, from_version, old_columns, call_columns, (rows, highest, calls, content))
    if checked is None:
        backup.unlink(missing_ok=True)
        raise MigrateRefused(f"the backup copy didn't match the log, so it was removed. {db_path.name} was not changed.")

    conn = connect(db_path)
    try:
        conn.executescript(f"BEGIN; {plan['statements']} PRAGMA user_version = {VERSION}; COMMIT;")
        mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]  # decision 6: set once, by this migrate
        after = (*_counts(conn, old_columns, call_columns), _version(conn))
    finally:
        conn.close()
    if after != (rows, highest, calls, renamed, VERSION) or mode != "wal":
        raise MigrateFailed(
            f"after the upgrade the log doesn't match what was checked before it ({rows} rows, {calls} calls and "
            f"highest #{highest} before; {after[0]} rows, {after[2]} calls and highest #{after[1]} after; "
            f"content hash {'same' if after[3] == renamed else 'different'}; journal mode {mode}). "
            f"The copy from before the upgrade is at {backup}. Nothing more was changed."
        )
    return {"job": "upgrade", "from": from_version, "added": plan["added"],
            "rows": rows, "calls": calls, "highest": highest, "backup": backup, "sha256": before,
            "content_hash": content, "backup_check": checked, "journal_mode": mode}


def _counts(conn, columns, call_columns):
    """(task rows, highest task number, call rows, content hash) of a log as the given version's columns read it."""
    rows = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    highest = conn.execute("SELECT COALESCE(MAX(rowid), 0) FROM tasks").fetchone()[0]
    calls = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0] if call_columns else 0
    return rows, highest, calls, _content_hash(conn, columns, call_columns)


def _check_backup(backup, version, columns, call_columns, expected):
    """The backup copy read back: integrity ok, the same version, the same counts and the same content hash as the log
    it was made from. The record of the check, or None when anything differs."""
    try:
        conn = _read_only(backup)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            found_version = _version(conn)
            rows, highest, calls, content = _counts(conn, columns, call_columns)
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return None
    if integrity != "ok" or found_version != version or (rows, highest, calls, content) != tuple(expected):
        return None
    return {"integrity": "ok", "version": version, "rows": rows, "calls": calls, "content": "same"}
