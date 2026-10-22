"""Build brief 21, A1 (rules v2.30, Router for the interface; decisions 2 and 3): log version 14. A task row gains
`reason_code`, written by the code that makes a return at the moment the task comes back (never parsed back from
prose); a call row gains `round_file` (phase C names the call's round file there). One migration, 13 -> 14, after a
backup, with the counts before and after; every older version lands on 14. Old rows read NULL: nothing is
reconstructed. Every value here is fake."""
import sqlite3

import pytest

from router import __main__ as cli
from router import log
from tests.helpers import V14_SCHEMA

V14_ADDED = "reason_code column added to tasks; round_file column added to calls"
V14_THEN_15 = V14_ADDED + "; pid, run_started_at and answered_by columns added to tasks"  # brief 22: a version 13 log lands on 15
V14_THEN_16 = V14_THEN_15 + "; " + log.V16_ADDED  # brief 25: ...and now on 16


def test_a_new_log_is_version_14_with_reason_code_last_on_tasks_and_round_file_last_on_calls():
    c = log.init_db(":memory:")
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 16
    assert [r[1] for r in c.execute("PRAGMA table_info(tasks)")][-6:] == ["chat", "memory", "reason_code", "pid", "run_started_at", "answered_by"]
    assert [r[1] for r in c.execute("PRAGMA table_info(calls)")][-3:] == ["memory", "served", "round_file"]
    c.close()


def _make_v13(path):
    """A version 13 log as brief 20 left it: today's tables without the two columns, three tasks (one returned for its
    label, one done with a Cursor call), and their calls."""
    c = sqlite3.connect(path)
    tasks_v13 = V14_SCHEMA.replace(",\n    reason_code     TEXT", "")
    calls_v13 = log.CALLS_SCHEMA.replace(",\n    round_file  TEXT", "")
    assert "reason_code" not in tasks_v13 and "round_file" not in calls_v13
    c.executescript(f"{tasks_v13}; {calls_v13}; PRAGMA user_version = 13;")
    rows = (("sr-1", "returned", "returned: needs your label", None), ("sr-2", "done", "best", "passed"),
            ("sr-3", "done", "relay", "passed"))
    for i, (task_id, status, reason, state) in enumerate(rows, 1):
        c.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, status, route_reason,"
                  " check_state, mode) VALUES (?, ?, ?, 'cli', ?, 'ok', ?, ?, ?, ?)",
                  (task_id, f"2026-10-20T00:00:0{i}+00:00", f"2026-10-20T00:00:0{i}+00:00", f"t{i}", status, reason, state,
                   "relay" if i == 3 else "route"))
    c.execute("INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at, text) VALUES "
              "('sr-2', 'sr-2', 'do', 'claude', 'done', '2026-10-20T00:00:02+00:00', 'an answer')")
    c.execute("INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at, text, stage, role, served) VALUES "
              "('sr-3-s2', 'sr-3', 'stage', 'cursor', 'done', '2026-10-20T00:00:03+00:00', 'b', 2, 'build',"
              " '{\"asked\": \"grok-4.7-high\", \"model\": \"Grok 4.7 256K High\", \"tool_events\": 0}')")
    c.commit()
    c.close()


def test_init_db_refuses_a_version_13_log_and_names_the_two_columns(tmp_path):
    db = tmp_path / "router.db"
    _make_v13(db)
    with pytest.raises(log.VersionError, match=r"version 13 log.*sr migrate.*version 16 \(" + V14_THEN_16 + r"\)"):
        log.init_db(db)


def test_upgrade_from_version_13_adds_both_columns_and_keeps_every_row(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _make_v13(db)
    done = log.migrate(db, backups)
    assert done["added"] == log.UPGRADES[13]["added"] == V14_THEN_16
    assert (done["from"], done["rows"], done["calls"], done["highest"]) == (13, 3, 2, 3)
    assert done["backup"].name.startswith("router-v13-") and done["backup"].exists()
    c = log.init_db(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 16
    # decision 3: old rows are not backfilled; the returned task's reason stays prose, its code NULL
    assert [tuple(r) for r in c.execute("SELECT task_id, reason_code, route_reason FROM tasks ORDER BY rowid")] == [
        ("sr-1", None, "returned: needs your label"), ("sr-2", None, "best"), ("sr-3", None, "relay")]
    assert [tuple(r) for r in c.execute("SELECT call_id, round_file FROM calls ORDER BY rowid")] == [
        ("sr-2", None), ("sr-3-s2", None)]
    assert log.served_of(log.get_call(c, "sr-3-s2"))["model"] == "Grok 4.7 256K High"  # the version 13 column kept
    c.close()
    with pytest.raises(log.MigrateRefused, match="already a version 16"):
        log.migrate(db, backups)


def test_every_older_upgrade_lands_on_14_with_both_columns():
    for from_version in range(2, 14):
        plan = log.UPGRADES[from_version]
        assert plan["added"].endswith(V14_THEN_16), from_version
        assert "ALTER TABLE tasks ADD COLUMN reason_code TEXT" in plan["statements"], from_version
        # version 2 makes its calls table from CALLS_SCHEMA, which already has round_file
        assert ("ALTER TABLE calls ADD COLUMN round_file TEXT" in plan["statements"]) == (from_version != 2), from_version
    assert log.UPGRADES[13]["columns"] == log.V13_COLUMNS == log.V12_COLUMNS
    assert log.UPGRADES[13]["call_columns"] == log.V13_CALL_COLUMNS == log.V12_CALL_COLUMNS + ("served",)


def test_sr_migrate_prints_the_backup_the_columns_and_the_counts(tmp_path, capsys):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _make_v13(db)
    assert cli.cmd_migrate(db_path=db, backups_dir=backups) == 0
    out = capsys.readouterr().out
    assert "Log: router.db, version 13, 3 rows (highest #3), integrity ok, no open tasks." in out
    assert "Backup copy: backups/router-v13-" in out
    assert f"Upgraded in place: {V14_THEN_16}, now version 16." in out
    assert "Checked after: 3 rows, 2 calls, highest #3, every version 13 column unchanged" in out


def test_a_migration_is_refused_while_a_task_is_open(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _make_v13(db)
    c = sqlite3.connect(db)
    c.execute("UPDATE tasks SET status = 'queued' WHERE task_id = 'sr-2'")
    c.commit()
    c.close()
    with pytest.raises(log.MigrateRefused, match="1 task\\(s\\) are still queued or sent"):
        log.migrate(db, backups)
    assert not backups.exists() or not any(backups.iterdir())
