"""Build brief 22, A2 (rules v2.31, Router for the interface, "The log under two writers"; decision 6): log version 15.
A task row gains `pid` and `run_started_at` (the run that holds it, written when a run starts and cleared when it
ends) and `answered_by` (on a Jev floor row, the task that answered it). One migration, 14 -> 15, after a backup made
with SQLite's backup API (so nothing waiting in a WAL is lost), with the counts before and after; every older version
lands on 15. Old rows read NULL. The 14 -> 15 migrate sets `journal_mode=WAL` once; every connection waits 15 s for
another writer. JSON reads stay read-only and keep working under WAL while a task writes. Every value here is fake."""
import json
import shutil
import sqlite3
import stat

import pytest

from router import __main__ as cli
from router import log
from tests.helpers import V14_SCHEMA

V15_ADDED = "pid, run_started_at and answered_by columns added to tasks"
NEW_TASK_COLUMNS = ["pid", "run_started_at", "answered_by"]


def _make_v14(path, open_task=False):
    """A version 14 log as brief 21 left it (journal mode delete): today's tables without the three columns, three
    tasks (one returned for its label, one done, one relay) and their calls."""
    c = sqlite3.connect(path)
    tasks_v14 = V14_SCHEMA
    assert not any(name in tasks_v14 for name in NEW_TASK_COLUMNS)
    c.executescript(f"{tasks_v14}; {log.CALLS_SCHEMA}; PRAGMA user_version = 14;")
    rows = (("sr-1", "returned", "returned: needs your label", None, "needs_label"),
            ("sr-2", "queued" if open_task else "done", "best", "passed", None),
            ("sr-3", "done", "relay", "passed", None))
    for i, (task_id, status, reason, state, code) in enumerate(rows, 1):
        c.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, status, route_reason,"
                  " check_state, mode, reason_code) VALUES (?, ?, ?, 'cli', ?, 'below_floor', ?, ?, ?, ?, ?)",
                  (task_id, f"2026-10-20T00:00:0{i}+00:00", f"2026-10-20T00:00:0{i}+00:00", f"t{i}", status, reason,
                   state, "relay" if i == 3 else "route", code))
    c.execute("INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at, text, round_file) VALUES "
              "('sr-2', 'sr-2', 'do', 'claude', 'done', '2026-10-20T00:00:02+00:00', 'an answer', 'tasks/sr-2/01-do-claude.md')")
    c.execute("INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at, text, stage, role) VALUES "
              "('sr-3-s2', 'sr-3', 'stage', 'claude', 'done', '2026-10-20T00:00:03+00:00', 'b', 2, 'build')")
    c.commit()
    c.close()


def _mode(path):
    c = sqlite3.connect(path)
    try:
        return c.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        c.close()


# ---------- the new log ----------

def test_a_new_log_is_version_15_with_the_three_run_columns_last_on_tasks():
    c = log.init_db(":memory:")
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 16
    assert [r[1] for r in c.execute("PRAGMA table_info(tasks)")][-4:] == ["reason_code"] + NEW_TASK_COLUMNS
    assert [r[1] for r in c.execute("PRAGMA table_info(calls)")][-1] == "round_file"  # calls unchanged
    c.close()


def test_a_new_log_file_is_in_wal_mode(tmp_path):
    db = tmp_path / "router.db"
    log.init_db(db).close()
    assert _mode(db) == "wal"


def test_every_connection_waits_15_seconds_for_another_writer(tmp_path):
    db = tmp_path / "router.db"
    log.init_db(db).close()
    for conn in (log.init_db(db), log.open_read_only(db), log._read_only(db), log.connect(db), log.connect(db, read_only=True)):
        try:
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 15000
        finally:
            conn.close()
    assert log.BUSY_SECONDS == 15


def test_init_db_refuses_a_version_14_log_and_names_the_three_columns(tmp_path):
    db = tmp_path / "router.db"
    _make_v14(db)
    with pytest.raises(log.VersionError, match=r"version 14 log.*sr migrate.*version 16 \(" + V15_ADDED + "; " + log.V16_ADDED + r"\)"):
        log.init_db(db)
    assert _mode(db) == "delete"  # nothing was changed


# ---------- the 14 -> 15 migrate ----------

def test_upgrade_from_version_14_adds_the_three_columns_keeps_every_row_and_sets_wal(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _make_v14(db)
    done = log.migrate(db, backups)
    assert done["added"] == log.UPGRADES[14]["added"] == V15_ADDED + "; " + log.V16_ADDED
    assert (done["from"], done["rows"], done["calls"], done["highest"], done["journal_mode"]) == (14, 3, 2, 3, "wal")
    assert _mode(db) == "wal"
    c = log.init_db(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 16
    assert [tuple(r) for r in c.execute("SELECT task_id, pid, run_started_at, answered_by, reason_code FROM tasks"
                                        " ORDER BY rowid")] == [
        ("sr-1", None, None, None, "needs_label"), ("sr-2", None, None, None, None), ("sr-3", None, None, None, None)]
    assert log.get_call(c, "sr-2")["round_file"] == "tasks/sr-2/01-do-claude.md"  # the version 14 column kept
    c.close()
    with pytest.raises(log.MigrateRefused, match="already a version 16"):
        log.migrate(db, backups)


def test_the_backup_is_made_by_the_backup_api_owner_only_and_checked_by_its_content(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _make_v14(db)
    done = log.migrate(db, backups)
    backup = done["backup"]
    assert backup.name.startswith("router-v14-") and stat.S_IMODE(backup.stat().st_mode) == 0o600
    c = sqlite3.connect(backup)
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert c.execute("PRAGMA user_version").fetchone()[0] == 14
    assert [r[1] for r in c.execute("PRAGMA table_info(tasks)")][-1] == "reason_code"  # the version 14 table, whole
    assert c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 3 and c.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 2
    assert log._content_hash(c, log.UPGRADES[14]["columns"], log.UPGRADES[14]["call_columns"]) == done["content_hash"]
    c.close()
    assert done["backup_check"] == {"integrity": "ok", "version": 14, "rows": 3, "calls": 2, "content": "same"}


def test_the_backup_api_keeps_rows_a_file_copy_of_an_open_wal_log_would_miss(tmp_path):
    """Why the backup API (decision 6): rows committed to a WAL but not yet checkpointed live only in -wal; a plain
    file copy misses them, the backup API reads them."""
    src = tmp_path / "live.db"
    w = sqlite3.connect(src)
    w.execute("PRAGMA journal_mode=WAL")
    w.execute("PRAGMA wal_autocheckpoint=0")
    w.execute("CREATE TABLE t (x)")
    w.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(50)])
    w.commit()
    shutil.copyfile(src, tmp_path / "plain.db")
    plain = sqlite3.connect(tmp_path / "plain.db")
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        plain.execute("SELECT COUNT(*) FROM t")
    plain.close()
    log.backup_copy(src, tmp_path / "api.db")
    api = sqlite3.connect(tmp_path / "api.db")
    assert api.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 50
    api.close()
    w.close()
    assert stat.S_IMODE((tmp_path / "api.db").stat().st_mode) == 0o600


def test_a_backup_that_does_not_match_is_removed_and_nothing_changes(tmp_path, monkeypatch):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _make_v14(db)
    real = log._content_hash
    calls = []

    def second_differs(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs) if len(calls) != 2 else "not the same"

    monkeypatch.setattr(log, "_content_hash", second_differs)
    with pytest.raises(log.MigrateRefused, match="backup copy didn't match"):
        log.migrate(db, backups)
    assert not any(backups.iterdir())
    assert sqlite3.connect(db).execute("PRAGMA user_version").fetchone()[0] == 14 and _mode(db) == "delete"


def test_every_older_upgrade_lands_on_15_with_the_three_columns():
    for from_version in range(2, 15):
        plan = log.UPGRADES[from_version]
        assert plan["added"].endswith(V15_ADDED + "; " + log.V16_ADDED), from_version
        for column in NEW_TASK_COLUMNS:
            assert f"ALTER TABLE tasks ADD COLUMN {column}" in plan["statements"], (from_version, column)
    assert log.UPGRADES[14]["columns"] == log.V14_COLUMNS == log.V13_COLUMNS + ("reason_code",)
    assert log.UPGRADES[14]["call_columns"] == log.V14_CALL_COLUMNS == log.V13_CALL_COLUMNS + ("round_file",)


def test_sr_migrate_prints_the_backup_check_the_journal_mode_and_the_counts(tmp_path, capsys):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _make_v14(db)
    assert cli.cmd_migrate(db_path=db, backups_dir=backups) == 0
    out = capsys.readouterr().out
    assert "Log: router.db, version 14, 3 rows (highest #3), integrity ok, no open tasks." in out
    assert "Backup copy: backups/router-v14-" in out and "(owner-only), made with SQLite's backup API" in out
    assert "integrity ok, version 14, 3 rows, 2 calls, content the same as the log's" in out
    assert f"Upgraded in place: {V15_ADDED}; {log.V16_ADDED}, now version 16." in out
    assert "Journal mode: wal (a JSON read and a running task can use the log at once)." in out
    assert "Checked after: 3 rows, 2 calls, highest #3, every version 14 column unchanged" in out


def test_a_migration_is_refused_while_a_task_is_open(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _make_v14(db, open_task=True)
    with pytest.raises(log.MigrateRefused, match="1 task\\(s\\) are still queued or sent"):
        log.migrate(db, backups)
    assert not backups.exists() or not any(backups.iterdir())


# ---------- the save check under WAL (ready for the next migration) ----------

def _wal_log_left_by_a_read(tmp_path):
    db = tmp_path / "router.db"
    log.init_db(db).close()
    reader = log.open_read_only(db)
    reader.execute("SELECT COUNT(*) FROM tasks").fetchone()
    reader.close()
    return db


def test_a_read_only_open_of_a_wal_log_leaves_its_wal_files(tmp_path):
    db = _wal_log_left_by_a_read(tmp_path)
    assert (tmp_path / "router.db-wal").exists() and (tmp_path / "router.db-shm").exists()


def test_the_save_check_checkpoints_a_wal_left_by_a_read_and_lets_the_migration_go_on(tmp_path):
    db = _wal_log_left_by_a_read(tmp_path)
    log._refuse_half_finished_saves(db)  # no refusal
    assert not (tmp_path / "router.db-wal").exists() or (tmp_path / "router.db-wal").stat().st_size == 0


def test_the_save_check_refuses_while_another_command_holds_a_wal_log(tmp_path):
    db = _wal_log_left_by_a_read(tmp_path)
    writer = log.connect(db)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, status)"
                   " VALUES ('sr-x', 'a', 'a', 'cli', 't', 'ok', 'queued')")
    try:
        with pytest.raises(log.MigrateRefused, match="another command has the log open"):
            log._refuse_half_finished_saves(db)
    finally:
        writer.rollback()
        writer.close()


def test_a_journal_beside_a_delete_mode_log_is_still_refused(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _make_v14(db)
    (tmp_path / "router.db-journal").write_bytes(b"")
    with pytest.raises(log.MigrateRefused, match="journal exists"):
        log.migrate(db, backups)


# ---------- reads under WAL while a task writes ----------

def test_a_json_read_answers_while_another_connection_holds_an_open_write(tmp_path, monkeypatch, capsys):
    db = tmp_path / "router.db"
    monkeypatch.setattr(cli, "DB_PATH", db)
    c = log.init_db(db)
    log.add_task(c, "sr-20261020-000001-aaaa", "first", "cli", {"status": "ok", "label": "writing", "confidence": 0.9,
                                                                 "tokens": 5})
    c.close()
    writer = log.connect(db)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("UPDATE tasks SET task = 'not committed yet'")
    try:
        assert cli.main(["log", "--json"], platform="darwin") == 0
        doc = json.loads(capsys.readouterr().out)
        assert [t["text"] for t in doc["tasks"]] == ["first"]  # the last committed row, not the open write
    finally:
        writer.rollback()
        writer.close()
