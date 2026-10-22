"""Build brief 18, phase A: log version 11. A task row gains `project` (the registered name, nullable) and
`handoff` (the writes the router made to the project's handoff file for this task, as JSON); a call row gains
`context` (what context went with the call, as JSON). One migration, 10 -> 11, after a backup. Every value
here is fake."""
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


def test_a_new_log_is_version_11_with_the_three_columns_last():
    c = log.init_db(":memory:")
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 16
    assert [r[1] for r in c.execute("PRAGMA table_info(tasks)")][-8:] == ["project", "handoff", "chat", "memory", "reason_code", "pid", "run_started_at", "answered_by"]
    assert [r[1] for r in c.execute("PRAGMA table_info(calls)")][-4:] == ["context", "memory", "served", "round_file"]


def test_a_routed_task_stores_its_project_name(conn):
    log.add_task(conn, "sr-p", "t", "cli", JEV_OK, project="demo")
    log.add_task(conn, "sr-n", "t", "cli", JEV_OK)
    assert log.get_task(conn, "sr-p")["project"] == "demo" and log.get_task(conn, "sr-n")["project"] is None


def test_a_relay_task_stores_its_project_name(conn):
    log.add_task(conn, "sr-r", "t", "cli", NOT_ASKED, mode="relay", preset="redteam", project="demo")
    assert log.get_task(conn, "sr-r")["project"] == "demo"


def test_a_split_or_a_piece_never_carries_a_project(conn):
    with pytest.raises(ValueError, match="only a routed or relay task has a project"):
        log.add_task(conn, "sr-s", "t", "cli", NOT_ASKED, mode="split", project="demo")


def test_a_project_name_is_plain(conn):
    with pytest.raises(ValueError, match="a project name is lower case letters, digits and -"):
        log.add_task(conn, "sr-x", "t", "cli", JEV_OK, project="My Project")


def test_project_of_a_row_without_the_column_is_none():
    assert log.project_of({"task_id": "sr-old"}) is None


def test_handoff_writes_are_appended_as_a_json_list(conn):
    log.add_task(conn, "sr-p", "t", "cli", JEV_OK, project="demo")
    assert log.handoff_of(log.get_task(conn, "sr-p")) == []
    log.add_handoff_write(conn, "sr-p", {"kind": "line", "text": "### #1 · 2026-10-16 · failed: x", "lines": 5,
                                         "block_start": 1})
    log.add_handoff_write(conn, "sr-p", {"kind": "entry", "text": "### #1 …", "lines": 9, "block_start": 1})
    found = log.handoff_of(log.get_task(conn, "sr-p"))
    assert [w["kind"] for w in found] == ["line", "entry"] and found[1]["lines"] == 9
    assert all("at" in w for w in found)


def test_a_handoff_write_needs_a_project_task(conn):
    log.add_task(conn, "sr-n", "t", "cli", JEV_OK)
    with pytest.raises(log.StateError, match="not a project task"):
        log.add_handoff_write(conn, "sr-n", {"kind": "entry", "text": "x", "lines": 1, "block_start": 1})


def test_a_call_stores_its_context_record(conn):
    log.add_task(conn, "sr-p", "t", "cli", JEV_OK, project="demo")
    log.add_call(conn, "sr-p", "sr-p", "do", "claude", status="done", text="r",
                 context={"project": "demo", "lines": 4, "total": 4, "text": "the handoff"})
    log.add_call(conn, "sr-p-c1", "sr-p", "check", "grok", context={"project": "demo", "left_out": True, "total": 40})
    assert log.context_of(log.get_call(conn, "sr-p"))["lines"] == 4
    assert log.context_of(log.get_call(conn, "sr-p-c1"))["left_out"] is True
    assert log.context_of({"call_id": "old"}) is None


def test_a_context_record_names_its_project(conn):
    log.add_task(conn, "sr-p", "t", "cli", JEV_OK, project="demo")
    with pytest.raises(ValueError, match="a call's context record names its project"):
        log.add_call(conn, "sr-p", "sr-p", "do", "claude", status="done", text="r", context={"lines": 1})


def test_open_task_for_a_project_is_the_newest_queued_or_sent_row(conn):
    log.add_task(conn, "sr-1", "t", "cli", JEV_OK, project="demo", now=None)
    log.set_route(conn, "sr-1", agents=("claude",), agent="claude", route_reason="best")
    log.set_done(conn, "sr-1", "r")
    assert log.open_task_for(conn, "demo") is None
    log.add_task(conn, "sr-2", "t", "cli", JEV_OK, project="demo")
    assert log.open_task_for(conn, "demo")["task_id"] == "sr-2"
    log.set_returned(conn, "sr-2", "returned: needs your label")  # a returned task is final, never open
    assert log.open_task_for(conn, "demo") is None
    assert log.open_task_for(conn, "other") is None


# ---------- the upgrade 10 -> 11 ----------

def _make_v10(path):
    c = sqlite3.connect(path)
    tasks_v10 = V13_SCHEMA.replace(",\n    project         TEXT,\n    handoff         TEXT,\n    chat            TEXT,\n    memory          TEXT", "")
    calls_v10 = V13_CALLS_SCHEMA.replace(",\n    context     TEXT,\n    memory      TEXT,\n    served      TEXT", "")
    assert "project" not in tasks_v10 and "context" not in calls_v10
    c.executescript(f"{tasks_v10}; {calls_v10}; PRAGMA user_version = 10;")
    for i in (1, 2, 3):
        jev, mode, preset = ("not_asked", "relay", "versus") if i == 3 else ("ok", "route", None)
        c.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, status, mode, preset)"
                  " VALUES (?, ?, ?, 'cli', ?, ?, 'done', ?, ?)",
                  (f"sr-{i}", f"2026-10-16T00:00:0{i}+00:00", f"2026-10-16T00:00:0{i}+00:00", f"t{i}", jev, mode, preset))
    c.execute("INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at) VALUES "
              "('sr-1', 'sr-1', 'do', 'claude', 'done', '2026-10-16T00:00:00+00:00')")
    c.commit()
    c.close()


def test_upgrade_from_version_10_adds_the_columns_and_keeps_every_row(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _make_v10(db)
    with pytest.raises(log.VersionError, match=r"version 10 log.*sr migrate.*version 16 \(project and handoff columns"):
        log.init_db(db)
    done = log.migrate(db, backups)
    assert done["added"] == log.UPGRADES[10]["added"] == ("project and handoff columns added to tasks; "
                                                          "context column added to calls; chat and memory columns added to tasks; memory column added to calls; served column added to calls; reason_code column added to tasks; round_file column added to calls; pid, run_started_at and answered_by columns added to tasks; skill_source set to owner where it named the one who labeled the task")
    assert (done["rows"], done["calls"], done["highest"]) == (3, 1, 3)
    assert done["backup"].name.startswith("router-v10-") and done["backup"].exists()
    c = log.init_db(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 16
    assert [tuple(r) for r in c.execute("SELECT project, handoff FROM tasks")] == [(None, None)] * 3
    assert [tuple(r) for r in c.execute("SELECT context FROM calls")] == [(None,)]
    rows = [log.get_task(c, f"sr-{i}") for i in (1, 2, 3)]
    assert [log.project_of(r) for r in rows] == [None] * 3 and [log.handoff_of(r) for r in rows] == [[]] * 3
    c.close()
    with pytest.raises(log.MigrateRefused, match="already a version 16"):
        log.migrate(db, backups)


def test_sr_migrate_prints_the_10_to_11_upgrade(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _make_v10(db)
    lines = []
    assert cli.cmd_migrate(db_path=db, backups_dir=backups, out=lines.append) == 0
    out = "\n".join(lines)
    assert "version 10, 3 rows (highest #3)" in out
    assert ("Upgraded in place: project and handoff columns added to tasks; context column added to calls; chat and memory "
            "columns added to tasks; memory column added to calls; served column added to calls; reason_code column added to tasks; round_file column added to calls; pid, run_started_at and answered_by columns added to tasks; skill_source set to owner where it named the one who labeled the task, now version 16.") in out


def test_every_older_upgrade_lands_on_11_with_the_three_columns():
    for version, plan in log.UPGRADES.items():
        if version in (11, 12, 13, 14, 15):  # brief 19's 11 -> 12 adds the chat and memory columns only; brief 20's 12 -> 13 the served column only; brief 21's 13 -> 14 reason_code and round_file only; brief 22's 14 -> 15 the run columns only; brief 25's 15 -> 16 renames a stored value only
            continue
        assert "ADD COLUMN project TEXT" in plan["statements"], version
        assert "ADD COLUMN handoff TEXT" in plan["statements"], version
        assert ("context     TEXT" if version == 2 else "ADD COLUMN context TEXT") in plan["statements"], version
        assert "project and handoff" in plan["added"] and "context column" in plan["added"], version
