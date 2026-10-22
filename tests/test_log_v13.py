"""Build brief 20, phase B (rules v2.28, Cursor): log version 13. A call row gains `served` (a Cursor call's record:
the model the stream named, the id asked for, the tool events counted and named, duration_ms, permissionMode, usage,
and where the raw stream went), NULL on every other call. One migration, 12 -> 13, after a backup; every older
version lands on 13. Every value here is fake."""
import sqlite3

import pytest

from router import __main__ as cli
from router import log

from helpers import JEV_OK, V13_CALLS_SCHEMA, V13_SCHEMA

SERVED = {"model": "Grok 4.7 256K High", "asked": "grok-4.7-high", "tool_events": 0, "tools": [], "duration_ms": 21888,
          "permission_mode": "default", "usage": {"inputTokens": 14183, "outputTokens": 78, "cacheReadTokens": 6272,
                                                  "cacheWriteTokens": 0}}


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def test_a_new_log_is_version_13_with_served_last_on_calls():
    c = log.init_db(":memory:")
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 16
    assert [r[1] for r in c.execute("PRAGMA table_info(calls)")][-4:] == ["context", "memory", "served", "round_file"]  # brief 21: round_file
    assert [r[1] for r in c.execute("PRAGMA table_info(tasks)")][-8:] == ["project", "handoff", "chat", "memory", "reason_code", "pid", "run_started_at", "answered_by"]


def test_a_call_stores_its_served_record_and_every_other_call_reads_none(conn):
    log.add_task(conn, "sr-v", "t", "cli", {"status": "not_asked", "tokens": 0}, mode="relay", preset="versus")
    log.add_call(conn, "sr-v-s1", "sr-v", "stage", "claude", status="done", text="a", stage=1, role="build")
    log.add_call(conn, "sr-v-s2", "sr-v", "stage", "cursor", status="done", text="b", stage=2, role="build", served=SERVED)
    log.add_call(conn, "sr-v-s3", "sr-v", "stage", "cursor", status="failed", text="served model 'Composer 2.5' is not the one asked for",
                 stage=3, role="review", served={**SERVED, "model": "Composer 2.5", "tool_events": 1, "tools": ["readToolCall:started"]})
    assert log.served_of(log.get_call(conn, "sr-v-s1")) is None
    assert log.served_of(log.get_call(conn, "sr-v-s2")) == SERVED
    assert log.served_of(log.get_call(conn, "sr-v-s3"))["model"] == "Composer 2.5"
    assert log.served_of({"call_id": "old"}) is None  # a row from before version 13


def test_a_served_record_names_the_asked_model_and_counts_its_tool_events(conn):
    log.add_task(conn, "sr-r", "t", "cli", JEV_OK)
    with pytest.raises(ValueError, match="a call's served record names the asked model and counts its tool events"):
        log.add_call(conn, "sr-r", "sr-r", "do", "cursor", status="done", text="r", served={"model": "x"})
    with pytest.raises(ValueError, match="a call's served record"):
        log.add_call(conn, "sr-r", "sr-r", "do", "cursor", status="done", text="r", served="not a dict")
    log.add_call(conn, "sr-r", "sr-r", "do", "cursor", status="done", text="r", served={"model": None, "asked": "grok-4.7-high",
                                                                                     "tool_events": 0})
    assert log.served_of(log.get_call(conn, "sr-r")) == {"model": None, "asked": "grok-4.7-high", "tool_events": 0}


# ---------- the upgrade 12 -> 13 ----------

def _make_v12(path):
    c = sqlite3.connect(path)
    calls_v12 = V13_CALLS_SCHEMA.replace(",\n    served      TEXT", "")
    assert "served" not in calls_v12
    c.executescript(f"{V13_SCHEMA}; {calls_v12}; PRAGMA user_version = 12;")
    for i in (1, 2, 3):
        jev, mode, preset = ("not_asked", "relay", "versus") if i == 3 else ("ok", "route", None)
        c.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, status, mode, preset, chat,"
                  " memory) VALUES (?, ?, ?, 'cli', ?, ?, 'done', ?, ?, ?, ?)",
                  (f"sr-{i}", f"2026-10-19T00:00:0{i}+00:00", f"2026-10-19T00:00:0{i}+00:00", f"t{i}", jev, mode, preset,
                   "tray" if i == 2 else None, '[{"document_id": "task-sr-2", "chars": 5, "state": "done/passed/2", "at": "x"}]' if i == 2 else None))
    c.execute("INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at, memory) VALUES "
              "('sr-2', 'sr-2', 'do', 'claude', 'done', '2026-10-19T00:00:00+00:00', '{\"tag\": \"chat:tray\", \"sent\": 1, \"found\": 1, \"text\": \"b\"}')")
    c.commit()
    c.close()


def test_upgrade_from_version_12_adds_the_column_and_keeps_every_row(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _make_v12(db)
    with pytest.raises(log.VersionError, match=r"version 12 log.*sr migrate.*version 16 \(served column added to calls; reason_code column added to tasks"):
        log.init_db(db)
    done = log.migrate(db, backups)
    assert done["added"] == log.UPGRADES[12]["added"] == "served column added to calls; reason_code column added to tasks; round_file column added to calls; pid, run_started_at and answered_by columns added to tasks; skill_source set to owner where it named the one who labeled the task"
    assert (done["rows"], done["calls"], done["highest"]) == (3, 1, 3)
    assert done["backup"].name.startswith("router-v12-") and done["backup"].exists()
    c = log.init_db(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 16
    assert [tuple(r) for r in c.execute("SELECT served FROM calls")] == [(None,)]
    assert log.served_of(log.get_call(c, "sr-2")) is None
    assert log.call_memory_of(log.get_call(c, "sr-2")) == {"tag": "chat:tray", "sent": 1, "found": 1, "text": "b"}  # the old columns kept
    assert log.chat_of(log.get_task(c, "sr-2")) == "tray" and log.memory_of(log.get_task(c, "sr-2"))[0]["chars"] == 5
    c.close()
    with pytest.raises(log.MigrateRefused, match="already a version 16"):
        log.migrate(db, backups)


def test_every_older_upgrade_lands_on_13_with_the_served_column():
    for from_version in range(2, 13):
        plan = log.UPGRADES[from_version]
        assert plan["added"].endswith("served column added to calls; reason_code column added to tasks; round_file column added to calls; pid, run_started_at and answered_by columns added to tasks; skill_source set to owner where it named the one who labeled the task"), from_version
        # version 2 makes its calls table from CALLS_SCHEMA, which already has the served column
        assert ("ALTER TABLE calls ADD COLUMN served TEXT" in plan["statements"]) == (from_version != 2), from_version
    assert log.UPGRADES[12]["columns"] == log.V12_COLUMNS and log.UPGRADES[12]["call_columns"] == log.V12_CALL_COLUMNS
    assert log.V12_COLUMNS[-4:] == ("project", "handoff", "chat", "memory") and log.V12_CALL_COLUMNS[-2:] == ("context", "memory")


def test_sr_migrate_prints_the_backup_the_column_and_the_counts(tmp_path, capsys):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _make_v12(db)
    assert cli.cmd_migrate(db_path=db, backups_dir=backups) == 0
    out = capsys.readouterr().out
    assert "Log: router.db, version 12, 3 rows (highest #3), integrity ok, no open tasks." in out
    assert "Backup copy: backups/router-v12-" in out
    assert "Upgraded in place: served column added to calls; reason_code column added to tasks; round_file column added to calls; pid, run_started_at and answered_by columns added to tasks; skill_source set to owner where it named the one who labeled the task, now version 16." in out
    assert "Checked after: 3 rows, 1 calls, highest #3, every version 12 column unchanged" in out
