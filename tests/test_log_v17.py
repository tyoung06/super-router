"""Build brief 28 (decision 19; Tests, "log 17's migration"): log version 17 adds `tasks.project_files` and
`calls.tests`, both JSON text. `sr migrate` copies the log into backups/ through SQLite's backup API first, then adds the
two columns in place; the counts and every older column are the same after, and every old row reads NULL in both."""
import sqlite3
from datetime import datetime, timezone

import pytest

from router import __main__ as cli
from router import log
from tests.helpers import V16_CALLS_SCHEMA, V16_SCHEMA

NOW = "2026-10-26T09:00:00+00:00"
WHEN = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)


def _v16_log(path, tasks=3):
    conn = sqlite3.connect(path)
    conn.executescript(f"{V16_SCHEMA}; {V16_CALLS_SCHEMA}; PRAGMA user_version = 16;")
    for n in range(1, tasks + 1):
        conn.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, skill, skill_source, "
                     "status, project) VALUES (?, ?, ?, 'cli', ?, 'ok', 'code', 'jev', 'done', 'garden')",
                     (f"sr-20261026-09000{n}-ab1{n}", NOW, NOW, f"task {n}"))
        conn.execute("INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at, text) "
                     "VALUES (?, ?, 'do', 'claude', 'done', ?, 'result')", (f"sr-20261026-09000{n}-ab1{n}", f"sr-20261026-09000{n}-ab1{n}", NOW))
    conn.commit()
    conn.close()


def _columns(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def test_a_new_log_has_the_two_columns_before_brief_33s():
    c = log.init_db(":memory:")
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 21
    assert _columns(c, "tasks")[-7:] == ["project_files", "from_task", "idea", "plan", "plan_step", "models", "auto"] and _columns(c, "calls")[-4:] == ["tests", "model", "effort", "time_limit"]


def test_a_version_16_log_is_refused_until_migrated_and_names_the_two_columns(tmp_path):
    db = tmp_path / "router.db"
    _v16_log(db)
    with pytest.raises(log.VersionError, match=r"version 16 log.*sr migrate.*version 21 \(" + log.V17_ADDED + "; " + log.V18_ADDED + "; " + log.V19_ADDED + "; " + log.V20_ADDED + "; " + log.V21_ADDED + r"\)"):
        log.init_db(db)


def test_the_upgrade_backs_up_then_adds_the_columns_and_keeps_every_row(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _v16_log(db)
    done = log.migrate(db, backups, now=WHEN)
    assert done["added"] == log.UPGRADES[16]["added"] == log.V17_ADDED + "; " + log.V18_ADDED + "; " + log.V19_ADDED + "; " + log.V20_ADDED + "; " + log.V21_ADDED
    assert (done["from"], done["rows"], done["calls"], done["highest"]) == (16, 3, 3, 3)
    assert done["backup"].name == "router-v16-2026-10-26.db" and done["backup_check"]["content"] == "same"
    assert done["journal_mode"] == "wal"
    c = log.init_db(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 21
    assert [r[0] for r in c.execute("SELECT project_files FROM tasks")] == [None] * 3
    assert [r[0] for r in c.execute("SELECT tests FROM calls")] == [None] * 3
    assert [r[0] for r in c.execute("SELECT project FROM tasks")] == ["garden"] * 3
    backup = sqlite3.connect(done["backup"])
    assert backup.execute("PRAGMA user_version").fetchone()[0] == 16 and "project_files" not in _columns(backup, "tasks")
    backup.close()
    with pytest.raises(log.MigrateRefused, match="already a version 21"):
        log.migrate(db, backups, now=WHEN)


def test_every_older_upgrade_lands_on_17_with_both_columns():
    for from_version in range(2, 17):
        plan = log.UPGRADES[from_version]
        assert "ADD COLUMN project_files TEXT" in plan["statements"], from_version
        assert ("ADD COLUMN tests TEXT" in plan["statements"]) == (from_version != 2), from_version  # 2 makes calls fresh
        assert plan["added"].endswith(log.V17_ADDED + "; " + log.V18_ADDED + "; " + log.V19_ADDED + "; " + log.V20_ADDED + "; " + log.V21_ADDED), from_version


def test_sr_migrate_prints_the_backup_and_the_counts(tmp_path, capsys):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _v16_log(db, tasks=2)
    assert cli.cmd_migrate(db_path=db, backups_dir=backups, now=WHEN) == 0
    out = capsys.readouterr().out
    assert "version 16, 2 rows (highest #2)" in out and f"Upgraded in place: {log.V17_ADDED}; {log.V18_ADDED}; {log.V19_ADDED}; {log.V20_ADDED}; {log.V21_ADDED}, now version 21." in out
