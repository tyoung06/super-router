"""Shared test helpers. Every secret here is fake."""
import hashlib
import json
import re
import sqlite3
from pathlib import Path

from router import log

ALL_AGENTS = ("claude", "grok", "chatgpt", "muse")

# Build brief 21, B1: presets 1.6 is 1.5 plus one `"description": "...",` line per preset, its first key (the owner's own
# commit, their lines). The pins on the shipped file read it through these two, so they hold before and after that commit,
# and still catch any other change.
SHIPPED_PRESET_VERSIONS = ("1.5", "1.6")
_DESCRIPTION_LINE = re.compile(r'(?m)^      "description": "(?:[^"\\\n]|\\.)*",\n')


def shipped_presets_text():
    """config/presets.json's text, each preset's description line out and a 1.6 version read as 1.5 (byte-for-byte pins)."""
    from router import presets
    text = _DESCRIPTION_LINE.sub("", presets.PRESETS_PATH.read_text())
    return text.replace('"version": "1.6"', '"version": "1.5"', 1)


def shipped_presets_doc():
    """config/presets.json as data, each preset's `description` out wherever it sits and a 1.6 version read as 1.5."""
    from router import presets
    doc = json.loads(presets.PRESETS_PATH.read_text())
    for entry in doc["presets"].values():
        entry.pop("description", None)
    if doc.get("version") == "1.6":
        doc["version"] = "1.5"
    return doc

# A plain Jev answer for tests that only need a routed row. 0 tokens, so it never moves a monthly sum.
JEV_OK = {"status": "ok", "label": "quick_answer", "confidence": 0.9, "needs_split": 0.1, "tokens": 0}


def set_local(**keys):
    """Build brief 25: merge `keys` into this test's own config/settings.local.json (conftest points
    `settings.LOCAL_PATH` at a temp file holding the fake inbox repo), never this Mac's file. Returns its path."""
    from router import settings
    path = Path(settings.LOCAL_PATH)
    doc = json.loads(path.read_text()) if path.exists() else {}
    doc.update(keys)
    path.write_text(json.dumps(doc) + "\n")
    return path


def add_row(conn, task_id, task="t", agent="claude", reason="best", source="cli", jev=None, now=None):
    """Log a task the way route does (Jev's answer first, then who does it). Status stays queued."""
    log.add_task(conn, task_id, task, source, jev or JEV_OK, now=now)
    log.set_route(conn, task_id, agents=ALL_AGENTS, agent=agent, route_reason=reason)


# Build brief 22: the tables exactly as log version 14 made them (before tasks.pid, run_started_at and answered_by).
V14_SCHEMA = (log.SCHEMA.replace(",\n    pid             INTEGER", "").replace(",\n    run_started_at  TEXT", "")
              .replace(",\n    answered_by     TEXT", ""))
assert not any(name in V14_SCHEMA for name in ("pid ", "run_started_at", "answered_by"))
# Build brief 21: the tables exactly as log version 13 made them (before tasks.reason_code and calls.round_file). The
# old-log builders start from these, so a version N log never carries a column a later version added.
V13_SCHEMA = V14_SCHEMA.replace(",\n    reason_code     TEXT", "")
V13_CALLS_SCHEMA = log.CALLS_SCHEMA.replace(",\n    round_file  TEXT", "")
assert "reason_code" not in V13_SCHEMA and "round_file" not in V13_CALLS_SCHEMA


# The version 1 table, exactly as router/log.py made it before the version 2 rebuild.
V1_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id      TEXT PRIMARY KEY,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    sent_at      TEXT,
    source       TEXT NOT NULL,
    task         TEXT NOT NULL,
    agent        TEXT NOT NULL CHECK (agent IN ('claude', 'grok')),
    route_reason TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('queued', 'sent', 'done', 'failed', 'timed_out')),
    run_uuid     TEXT,
    result       TEXT,
    result_url   TEXT
)
"""


def make_v1_log(path, statuses=("done",)):
    """A version 1 log like the live one before `sr migrate`: user_version 0, one row per status."""
    conn = sqlite3.connect(path)
    conn.execute(V1_SCHEMA)
    for i, status in enumerate(statuses, 1):
        conn.execute(
            "INSERT INTO tasks (task_id, created_at, updated_at, source, task, agent, route_reason, status)"
            " VALUES (?, '2026-10-04T10:00:00+00:00', '2026-10-04T10:00:00+00:00', 'cli', ?, 'claude',"
            " 'classifier', ?)",
            (f"sr-v1-{i}", f"old task {i}", status),
        )
    conn.commit()
    conn.close()
    return Path(path)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def shipped_roster():
    """The real config/agents.json and config/skill_table.json, checked against the real send functions."""
    from router import __main__ as cli
    from router.roster import load_roster
    return load_roster(send_paths=tuple(cli.SENDERS))


def fake_label(answer=None):
    """A stand-in for Jev. Records what it was asked; returns `answer` (by default an ok
    quick_answer label at 0.9, which routes to claude)."""
    calls = []

    def label(task_text, *, task_id, tokens_this_month):
        calls.append({"task": task_text, "task_id": task_id, "tokens_this_month": tokens_this_month})
        return dict(answer or JEV_OK)

    label.calls = calls
    return label


# The version 2 table, exactly as router/log.py made it before the version 3 upgrade.
V2_SCHEMA = """
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
    result_url      TEXT
)
"""

V2_ROW = {
    "created_at": "2026-10-13T16:46:30+00:00", "updated_at": "2026-10-13T16:47:13+00:00",
    "sent_at": "2026-10-13T16:46:31+00:00", "source": "cli", "task": "old task",
    "jev_status": "ok", "jev_label": "web_research", "jev_confidence": 1.0, "jev_needs_split": 0.5,
    "jev_tokens": 700, "jev_error": None, "skill": "web_research", "skill_source": "jev",
    "agent": "grok", "route_reason": "interim", "checker": "claude", "check_state": "unchecked",
    "status": "done", "run_uuid": "uuid-old", "result": "an old result", "result_url": None,
}


def make_v2_log(path, rows=({},)):
    """A version 2 log like the live one before the version 3 upgrade (user_version 2).
    Each item in `rows` overrides V2_ROW's fields; task ids are sr-v2-1, sr-v2-2, ..."""
    conn = sqlite3.connect(path)
    conn.executescript(f"{V2_SCHEMA}; PRAGMA user_version = 2;")
    for i, overrides in enumerate(rows, 1):
        row = {**V2_ROW, "task_id": f"sr-v2-{i}", "task": f"old task {i}", **overrides}
        names = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        conn.execute(f"INSERT INTO tasks ({names}) VALUES ({marks})", tuple(row.values()))
    conn.commit()
    conn.close()
    return Path(path)


def roster_with(**live):
    """The shipped roster with some live flags overridden, for example roster_with(chatgpt=False)
    to test the Grok-does, Claude-checks loop that still runs for @grok tasks."""
    from router.roster import Roster
    shipped = shipped_roster()
    agents = {name: dict(agent) for name, agent in shipped.agents.items()}
    for name, flag in live.items():
        agents[name]["live"] = flag
    return Roster(agents=agents, not_routed=shipped.not_routed, table=shipped.table)


def grok_era_roster():
    """Build brief 2's world, for the loop-mechanics tests (Grok does web research, Claude checks):
    chatgpt off, and grok as web_research's stand-in, as skill table v3.1 had it. Version 3.2 nulled
    every interim because every best agent is live."""
    import json
    from router.roster import Roster
    shipped = shipped_roster()
    agents = {name: dict(agent) for name, agent in shipped.agents.items()}
    agents["chatgpt"]["live"] = False
    table = json.loads(json.dumps(shipped.table))
    table["skills"]["web_research"]["interim"] = "grok"
    return Roster(agents=agents, not_routed=shipped.not_routed, table=table)


# The version 3 table, exactly as router/log.py made it before the version 4 upgrade (version 2 plus check_note).
V3_SCHEMA = V2_SCHEMA.replace("    result_url      TEXT\n)", "    result_url      TEXT,\n    check_note      TEXT\n)")
assert "check_note" in V3_SCHEMA
V3_ROW = {**V2_ROW, "check_note": None}


# The calls table exactly as log versions 3 and 4 made it (before the version 5 stage and role columns).
OLD_CALLS_SCHEMA = """
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
    url         TEXT
)
"""


def make_v3_log(path, rows=({},)):
    """A version 3 log like the live one before the version 4 upgrade (user_version 3): the tasks
    table with check_note, and the calls table. Each item in `rows` overrides V3_ROW's fields."""
    conn = sqlite3.connect(path)
    conn.executescript(f"{V3_SCHEMA}; {OLD_CALLS_SCHEMA}; PRAGMA user_version = 3;")
    for i, overrides in enumerate(rows, 1):
        row = {**V3_ROW, "task_id": f"sr-v3-{i}", "task": f"old task {i}", **overrides}
        names = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        conn.execute(f"INSERT INTO tasks ({names}) VALUES ({marks})", tuple(row.values()))
    conn.commit()
    conn.close()
    return Path(path)


# The version 4 table, exactly as router/log.py made it before the version 5 upgrade (version 3 plus files).
V4_SCHEMA = V3_SCHEMA.replace("    check_note      TEXT\n)", "    check_note      TEXT,\n    files           TEXT\n)")
assert "files" in V4_SCHEMA
V4_ROW = {**V3_ROW, "files": None}


def make_v4_log(path, rows=({},)):
    """A version 4 log like the live one before the version 5 upgrade (user_version 4): tasks with
    check_note and files, and the calls table without stage and role. Each item in `rows`
    overrides V4_ROW's fields; task ids are sr-v4-1, sr-v4-2, ..."""
    conn = sqlite3.connect(path)
    conn.executescript(f"{V4_SCHEMA}; {OLD_CALLS_SCHEMA}; PRAGMA user_version = 4;")
    for i, overrides in enumerate(rows, 1):
        row = {**V4_ROW, "task_id": f"sr-v4-{i}", "task": f"old task {i}", **overrides}
        names = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        conn.execute(f"INSERT INTO tasks ({names}) VALUES ({marks})", tuple(row.values()))
    conn.commit()
    conn.close()
    return Path(path)


# The tables exactly as log version 5 made them (build brief 5): tasks unchanged since, and the
# calls table with stage and role but before the version 6 reason_code and resume_of columns.
V5_SCHEMA = V4_SCHEMA.replace("    files           TEXT\n)",
                              "    files           TEXT,\n    mode            TEXT NOT NULL DEFAULT 'route',\n"
                              "    preset          TEXT,\n    failed_stage    INTEGER\n)")
assert "failed_stage" in V5_SCHEMA
V5_CALLS_SCHEMA = OLD_CALLS_SCHEMA.replace("    url         TEXT\n)", "    url         TEXT,\n    stage       INTEGER,\n"
                                                                     "    role        TEXT\n)")
assert "role" in V5_CALLS_SCHEMA
V5_ROW = {**V4_ROW, "mode": "route", "preset": None, "failed_stage": None}


def make_v5_log(path, rows=({},), calls=()):
    """A version 5 log like the live one before the version 6 upgrade (user_version 5). Each item in
    `rows` overrides V5_ROW's fields (task ids sr-v5-1, sr-v5-2, ...); each item in `calls` is a
    dict of call columns."""
    conn = sqlite3.connect(path)
    conn.executescript(f"{V5_SCHEMA}; {V5_CALLS_SCHEMA}; PRAGMA user_version = 5;")
    for i, overrides in enumerate(rows, 1):
        row = {**V5_ROW, "task_id": f"sr-v5-{i}", "task": f"old task {i}", **overrides}
        conn.execute(f"INSERT INTO tasks ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})", tuple(row.values()))
    for call in calls:
        conn.execute(f"INSERT INTO calls ({', '.join(call)}) VALUES ({', '.join('?' for _ in call)})", tuple(call.values()))
    conn.commit()
    conn.close()
    return Path(path)


def count_lines_in(prompt):
    """Build brief 17, Phase W: `prompt` without the word-count lines (the checker's length rule and the count line,
    each a paragraph of its own), and how many were removed. Every other byte is untouched, so a prompt compared with
    one from before Phase W must be equal after this."""
    import re
    from router import checking
    removed = prompt.count("\n\n" + checking.LENGTH_RULE_LINE)
    prompt = prompt.replace("\n\n" + checking.LENGTH_RULE_LINE, "")
    pattern = re.compile(r"\n\nThe result is [0-9]+ words?\.(?: The task's own words on length: [^\n]*)?(?=\n\n)")
    removed += len(pattern.findall(prompt))
    return pattern.sub("", prompt), removed


def page_source():
    """The page's text: brief 23 moved its script and styles out of index.html (the CSP allows no inline script)."""
    static = Path(__file__).resolve().parent.parent / "static"
    return "".join((static / name).read_text(encoding="utf-8") for name in ("index.html", "app.js", "app.css"))
