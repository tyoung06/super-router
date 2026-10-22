"""Build brief 15, phase A: log version 10. A task row gains `slots` (a relay task's slot map as JSON, written
whole on every new relay task: the owner's D1) and `web` (1 when the owner sent the task with --web: rules v2.22,
the addendum's D10). One migration, 9 -> 10, after a backup. Every value here is fake."""
import json
import sqlite3

import pytest

from router import __main__ as cli
from router import log

from helpers import JEV_OK, V13_CALLS_SCHEMA, V13_SCHEMA

NOT_ASKED = {"status": "not_asked"}


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def test_a_new_log_is_version_10_with_slots_and_web_last_on_tasks():
    c = log.init_db(":memory:")
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 16
    assert [r[1] for r in c.execute("PRAGMA table_info(tasks)")][-10:] == ["slots", "web", "project", "handoff", "chat", "memory", "reason_code", "pid", "run_started_at", "answered_by"]  # briefs 18 and 19 added two each


def test_a_relay_task_stores_its_slot_map_whole(conn):
    log.add_task(conn, "sr-r", "t", "cli", NOT_ASKED, mode="relay", preset="versus",
                 slots={"a": "claude", "b": "grok"})
    row = log.get_task(conn, "sr-r")
    assert json.loads(row["slots"]) == {"a": "claude", "b": "grok"} and log.slots_of(row) == {"a": "claude", "b": "grok"}


def test_only_a_relay_task_has_slots(conn):
    with pytest.raises(ValueError, match="only a relay task has slots"):
        log.add_task(conn, "sr-x", "t", "cli", JEV_OK, slots={"a": "claude"})


def test_slots_must_be_a_map_of_names_to_agents(conn):
    with pytest.raises(ValueError, match="slots map slot names to agent names"):
        log.add_task(conn, "sr-x", "t", "cli", NOT_ASKED, mode="relay", preset="versus", slots={"a": 3})


def test_a_relay_task_without_slots_stores_null(conn):
    log.add_task(conn, "sr-r", "t", "cli", NOT_ASKED, mode="relay", preset="collab")
    assert log.get_task(conn, "sr-r")["slots"] is None and log.slots_of(log.get_task(conn, "sr-r")) is None


def test_web_is_stored_as_1_on_a_routed_task_and_null_otherwise(conn):
    log.add_task(conn, "sr-w", "t", "cli", JEV_OK, web=True)
    log.add_task(conn, "sr-n", "t", "cli", JEV_OK)
    assert log.get_task(conn, "sr-w")["web"] == 1 and log.web_of(log.get_task(conn, "sr-w")) is True
    assert log.get_task(conn, "sr-n")["web"] is None and log.web_of(log.get_task(conn, "sr-n")) is False


def test_only_a_routed_task_takes_web(conn):
    with pytest.raises(ValueError, match="only a routed task takes --web"):
        log.add_task(conn, "sr-x", "t", "cli", NOT_ASKED, mode="relay", preset="collab", web=True)


def test_web_of_a_row_without_the_column_is_false():
    assert log.web_of({"task_id": "sr-old"}) is False


# ---------- the upgrade 9 -> 10 ----------

def _make_v9(path):
    c = sqlite3.connect(path)
    tasks_v9 = V13_SCHEMA.replace(",\n    slots           TEXT,\n    web             INTEGER" + ",\n    project         TEXT,\n    handoff         TEXT,\n    chat            TEXT,\n    memory          TEXT", "")
    calls_v9 = V13_CALLS_SCHEMA.replace(",\n    context     TEXT,\n    memory      TEXT,\n    served      TEXT", "")
    assert "slots" not in tasks_v9 and "web " not in tasks_v9 and "project" not in tasks_v9 and "context" not in calls_v9
    c.executescript(f"{tasks_v9}; {calls_v9}; PRAGMA user_version = 9;")
    for i in (1, 2, 3):
        jev, mode, preset = ("not_asked", "relay", "versus") if i == 3 else ("ok", "route", None)
        c.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, status, mode, preset)"
                  " VALUES (?, ?, ?, 'cli', ?, ?, 'done', ?, ?)",
                  (f"sr-{i}", f"2026-10-15T00:00:0{i}+00:00", f"2026-10-15T00:00:0{i}+00:00", f"t{i}", jev, mode, preset))
    c.execute("INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at) VALUES "
              "('sr-1', 'sr-1', 'do', 'claude', 'done', '2026-10-15T00:00:00+00:00')")
    c.commit()
    c.close()


def test_upgrade_from_version_9_adds_slots_and_web_and_keeps_every_row(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _make_v9(db)
    with pytest.raises(log.VersionError, match=r"version 9 log.*sr migrate.*version 16 \(slots and web columns added"):
        log.init_db(db)
    done = log.migrate(db, backups)
    assert done["added"] == log.UPGRADES[9]["added"] == ("slots and web columns added to tasks; project and handoff "
                                                          "columns added to tasks; context column added to calls; chat and "
                                                          "memory columns added to tasks; memory column added to calls; served column added to calls; reason_code column added to tasks; round_file column added to calls; pid, run_started_at and answered_by columns added to tasks; skill_source set to owner where it named the one who labeled the task")
    assert (done["rows"], done["calls"], done["highest"]) == (3, 1, 3)
    assert done["backup"].name.startswith("router-v9-") and done["backup"].exists()
    c = log.init_db(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 16
    assert [tuple(r) for r in c.execute("SELECT slots, web FROM tasks")] == [(None, None)] * 3
    assert [r["preset"] for r in c.execute("SELECT preset FROM tasks")] == [None, None, "versus"]
    c.close()
    with pytest.raises(log.MigrateRefused, match="already a version 16"):
        log.migrate(db, backups)


def test_sr_migrate_prints_the_9_to_10_upgrade(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _make_v9(db)
    lines = []
    assert cli.cmd_migrate(db_path=db, backups_dir=backups, out=lines.append) == 0
    out = "\n".join(lines)
    assert "version 9, 3 rows (highest #3)" in out
    assert ("Upgraded in place: slots and web columns added to tasks; project and handoff columns added to tasks; "
            "context column added to calls; chat and memory columns added to tasks; memory column added to calls; served column added to calls; reason_code column added to tasks; round_file column added to calls; pid, run_started_at and answered_by columns added to tasks; skill_source set to owner where it named the one who labeled the task, now version 16.") in out


def test_every_older_upgrade_lands_on_10_with_the_slots_and_web_columns():
    for version, plan in log.UPGRADES.items():
        if version in (10, 11, 12, 13, 14, 15):  # brief 18's 10 -> 11, brief 19's 11 -> 12, brief 20's 12 -> 13, brief 21's 13 -> 14 and brief 22's 14 -> 15 add later columns only; brief 25's 15 -> 16 renames a stored value only
            continue
        assert "ADD COLUMN slots TEXT" in plan["statements"], version
        assert "ADD COLUMN web INTEGER" in plan["statements"], version
        assert "slots and web" in plan["added"], version
