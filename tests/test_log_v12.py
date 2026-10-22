"""Build brief 19, phase B (rules v2.27, Memory): log version 12. A task row gains `chat` (the chat name, nullable)
and `memory` (the retain records the router made for it, as JSON); a call row gains `memory` (the memory block as
sent, or why it was not, as JSON). One migration, 11 -> 12, after a backup; every older version lands on 12. Every
value here is fake."""
import sqlite3
from datetime import datetime, timezone

import pytest

from router import log

from helpers import JEV_OK, V13_CALLS_SCHEMA, V13_SCHEMA

NOT_ASKED = {"status": "not_asked"}


def _at(text):
    return datetime.fromisoformat(text).astimezone(timezone.utc)


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def test_a_new_log_is_version_12_with_the_three_columns_last():
    c = log.init_db(":memory:")
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 16
    assert [r[1] for r in c.execute("PRAGMA table_info(tasks)")][-8:] == ["project", "handoff", "chat", "memory", "reason_code", "pid", "run_started_at", "answered_by"]
    assert [r[1] for r in c.execute("PRAGMA table_info(calls)")][-4:] == ["context", "memory", "served", "round_file"]


# ---------- the tag (decision 7) ----------

def test_a_routed_or_relay_task_stores_its_chat_name(conn):
    log.add_task(conn, "sr-c", "t", "cli", JEV_OK, chat="tray")
    log.add_task(conn, "sr-r", "t", "cli", NOT_ASKED, mode="relay", preset="versus", chat="tray")
    log.add_task(conn, "sr-n", "t", "cli", JEV_OK)
    assert log.chat_of(log.get_task(conn, "sr-c")) == "tray"
    assert log.chat_of(log.get_task(conn, "sr-r")) == "tray"
    assert log.chat_of(log.get_task(conn, "sr-n")) is None


def test_a_split_or_a_piece_never_carries_a_chat(conn):
    with pytest.raises(ValueError, match="only a routed or relay task has a chat"):
        log.add_task(conn, "sr-s", "t", "cli", NOT_ASKED, mode="split", chat="tray")


def test_a_chat_name_is_plain(conn):
    with pytest.raises(ValueError, match="a chat name is lower case letters, digits and -"):
        log.add_task(conn, "sr-x", "t", "cli", JEV_OK, chat="My Chat")


def test_one_tag_per_task(conn):
    with pytest.raises(ValueError, match="one tag per task"):
        log.add_task(conn, "sr-x", "t", "cli", JEV_OK, project="demo", chat="tray")


def test_tag_of_each_kind_of_row(conn):
    log.add_task(conn, "sr-p", "t", "cli", JEV_OK, project="demo")
    log.add_task(conn, "sr-c", "t", "cli", JEV_OK, chat="tray")
    log.add_task(conn, "sr-n", "t", "cli", JEV_OK)
    assert log.tag_of(log.get_task(conn, "sr-p")) == "project:demo"
    assert log.tag_of(log.get_task(conn, "sr-c")) == "chat:tray"
    assert log.tag_of(log.get_task(conn, "sr-n")) is None
    assert log.tag_of({"task_id": "old"}) is None and log.chat_of({"task_id": "old"}) is None


# ---------- the write record on the task row (decision 6) ----------

def test_memory_writes_are_appended_as_a_json_list(conn):
    log.add_task(conn, "sr-c", "t", "cli", JEV_OK, chat="tray")
    assert log.memory_of(log.get_task(conn, "sr-c")) == []
    log.add_memory_write(conn, "sr-c", {"document_id": "task-sr-c", "chars": 120, "state": "done/passed/2"})
    log.add_memory_write(conn, "sr-c", {"skipped": "looks like a key", "state": "done/fixed/4"})
    found = log.memory_of(log.get_task(conn, "sr-c"))
    assert [w.get("document_id") for w in found] == ["task-sr-c", None]
    assert found[1]["skipped"] == "looks like a key" and all("at" in w for w in found)
    assert log.memory_of({"task_id": "old"}) == []


def test_a_memory_write_needs_a_tagged_task_and_a_shape(conn):
    log.add_task(conn, "sr-n", "t", "cli", JEV_OK)
    with pytest.raises(log.StateError, match="not a tagged task"):
        log.add_memory_write(conn, "sr-n", {"document_id": "task-sr-n", "chars": 1, "state": "done/passed/2"})
    log.add_task(conn, "sr-p", "t", "cli", JEV_OK, project="demo")
    with pytest.raises(ValueError, match="needs state"):
        log.add_memory_write(conn, "sr-p", {"document_id": "task-sr-p", "chars": 1})
    with pytest.raises(ValueError, match="document_id and chars, or skipped"):
        log.add_memory_write(conn, "sr-p", {"state": "done/passed/2"})
    with pytest.raises(log.StateError, match="no such task"):
        log.add_memory_write(conn, "sr-missing", {"skipped": "x", "state": "s"})


# ---------- the record on the call row (decision 10) ----------

def test_a_call_stores_its_memory_record(conn):
    log.add_task(conn, "sr-c", "t", "cli", JEV_OK, chat="tray")
    log.add_call(conn, "sr-c", "sr-c", "do", "claude", status="done", text="r",
                 memory={"tag": "chat:tray", "sent": 2, "found": 3, "text": "the block"})
    log.add_call(conn, "sr-c-c1", "sr-c", "check", "grok", memory={"tag": "chat:tray", "left_out": True, "found": 3})
    log.add_call(conn, "sr-c-f1", "sr-c", "fix", "claude", status="done", text="r2",
                 memory={"tag": "chat:tray", "unavailable": True})
    log.add_call(conn, "sr-c-c2", "sr-c", "recheck", "grok")
    assert log.call_memory_of(log.get_call(conn, "sr-c")) == {"tag": "chat:tray", "sent": 2, "found": 3, "text": "the block"}
    assert log.call_memory_of(log.get_call(conn, "sr-c-c1"))["left_out"] is True
    assert log.call_memory_of(log.get_call(conn, "sr-c-f1"))["unavailable"] is True
    assert log.call_memory_of(log.get_call(conn, "sr-c-c2")) is None
    assert log.call_memory_of({"call_id": "old"}) is None


def test_a_memory_record_names_its_tag(conn):
    log.add_task(conn, "sr-c", "t", "cli", JEV_OK, chat="tray")
    with pytest.raises(ValueError, match="a call's memory record names its tag"):
        log.add_call(conn, "sr-c", "sr-c", "do", "claude", status="done", text="r", memory={"sent": 1})


# ---------- chats from the log (decision 15) ----------

def test_chats_lists_names_with_counts_and_newest_date(conn):
    log.add_task(conn, "sr-1", "t", "cli", JEV_OK, chat="tray", now=_at("2026-10-16T10:00:00+00:00"))
    log.add_task(conn, "sr-2", "t", "cli", JEV_OK, chat="garden", now=_at("2026-10-17T10:00:00+00:00"))
    log.add_task(conn, "sr-3", "t", "cli", JEV_OK, chat="tray", now=_at("2026-10-18T10:00:00+00:00"))
    log.add_task(conn, "sr-4", "t", "cli", JEV_OK, project="demo", now=_at("2026-10-19T10:00:00+00:00"))
    log.add_task(conn, "sr-5", "t", "cli", JEV_OK, now=_at("2026-10-19T11:00:00+00:00"))
    found = [(r["chat"], r["count"], r["newest"]) for r in log.chats(conn)]
    assert found == [("tray", 2, "2026-10-18T10:00:00+00:00"), ("garden", 1, "2026-10-17T10:00:00+00:00")]
    assert log.chat_exists(conn, "tray") and not log.chat_exists(conn, "demo") and not log.chat_exists(conn, "none")


def test_recent_tasks_of_a_chat_are_that_chats_rows_newest_first(conn):
    log.add_task(conn, "sr-1", "t1", "cli", JEV_OK, chat="tray", now=_at("2026-10-16T10:00:00+00:00"))
    log.add_task(conn, "sr-2", "t2", "cli", JEV_OK, chat="garden", now=_at("2026-10-17T10:00:00+00:00"))
    log.add_task(conn, "sr-3", "t3", "cli", JEV_OK, chat="tray", now=_at("2026-10-18T10:00:00+00:00"))
    assert [r["task_id"] for r in log.recent_tasks_of_chat(conn, "tray")] == ["sr-3", "sr-1"]
    assert [r["task_id"] for r in log.recent_tasks_of_chat(conn, "tray", limit=1)] == ["sr-3"]
    assert log.recent_tasks_of_chat(conn, "none") == []


# ---------- the upgrade 11 -> 12 ----------

def _make_v11(path):
    c = sqlite3.connect(path)
    tasks_v11 = V13_SCHEMA.replace(",\n    chat            TEXT,\n    memory          TEXT", "")
    calls_v11 = V13_CALLS_SCHEMA.replace(",\n    memory      TEXT,\n    served      TEXT", "")
    assert "chat" not in tasks_v11 and "memory" not in tasks_v11 and "memory" not in calls_v11 and "served" not in calls_v11
    c.executescript(f"{tasks_v11}; {calls_v11}; PRAGMA user_version = 11;")
    for i in (1, 2, 3):
        jev, mode, preset = ("not_asked", "relay", "versus") if i == 3 else ("ok", "route", None)
        project, handoff = ("demo", '[{"kind": "entry", "text": "### #1", "lines": 9, "block_start": 1}]') if i == 2 else (None, None)
        c.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, status, mode, preset,"
                  " project, handoff) VALUES (?, ?, ?, 'cli', ?, ?, 'done', ?, ?, ?, ?)",
                  (f"sr-{i}", f"2026-10-17T00:00:0{i}+00:00", f"2026-10-17T00:00:0{i}+00:00", f"t{i}", jev, mode, preset,
                   project, handoff))
    c.execute("INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at, context) VALUES "
              "('sr-2', 'sr-2', 'do', 'claude', 'done', '2026-10-17T00:00:00+00:00', '{\"project\": \"demo\"}')")
    c.commit()
    c.close()


def test_upgrade_from_version_11_adds_the_columns_and_keeps_every_row(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _make_v11(db)
    with pytest.raises(log.VersionError, match=r"version 11 log.*sr migrate.*version 16 \(chat and memory columns"):
        log.init_db(db)
    done = log.migrate(db, backups)
    assert done["added"] == log.UPGRADES[11]["added"] == ("chat and memory columns added to tasks; "
                                                          "memory column added to calls; served column added to calls; reason_code column added to tasks; round_file column added to calls; pid, run_started_at and answered_by columns added to tasks; skill_source set to owner where it named the one who labeled the task")
    assert (done["rows"], done["calls"], done["highest"]) == (3, 1, 3)
    assert done["backup"].name.startswith("router-v11-") and done["backup"].exists()
    c = log.init_db(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 16
    assert [tuple(r) for r in c.execute("SELECT chat, memory FROM tasks")] == [(None, None)] * 3
    assert [tuple(r) for r in c.execute("SELECT memory FROM calls")] == [(None,)]
    rows = [log.get_task(c, f"sr-{i}") for i in (1, 2, 3)]
    assert [log.chat_of(r) for r in rows] == [None] * 3 and [log.memory_of(r) for r in rows] == [[]] * 3
    assert log.project_of(rows[1]) == "demo" and log.handoff_of(rows[1])[0]["lines"] == 9  # the old columns kept
    assert log.context_of(log.get_call(c, "sr-2")) == {"project": "demo"}
    c.close()
    with pytest.raises(log.MigrateRefused, match="already a version 16"):
        log.migrate(db, backups)


def test_every_older_upgrade_lands_on_12_with_the_memory_columns():
    for from_version in range(2, 12):
        plan = log.UPGRADES[from_version]
        assert "ALTER TABLE tasks ADD COLUMN chat TEXT" in plan["statements"], from_version
        assert "ALTER TABLE tasks ADD COLUMN memory TEXT" in plan["statements"], from_version
        assert plan["added"].endswith("chat and memory columns added to tasks; memory column added to calls; served column added to calls; reason_code column added to tasks; round_file column added to calls; pid, run_started_at and answered_by columns added to tasks; skill_source set to owner where it named the one who labeled the task"), from_version
        # version 2 makes its calls table from CALLS_SCHEMA, which already has the memory column
        assert ("ALTER TABLE calls ADD COLUMN memory TEXT" in plan["statements"]) == (from_version != 2), from_version
