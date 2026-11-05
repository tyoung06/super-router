"""Build brief 33 (decision 17): log version 18 adds `tasks.from_task` (the earlier task a task builds from), `tasks.idea`
(the project idea it was sent from) and a table `ideas` (id, project, text, source kind, source task, created time,
`dismissed_at`). `sr migrate` copies the log into backups/ through SQLite's backup API first, then adds the columns and the
table in place; the counts and every older column are the same after, every old row reads NULL in both columns, and the
ideas table is empty."""
import sqlite3
from datetime import datetime, timezone

import pytest

from router import __main__ as cli
from router import log
from tests.helpers import V17_SCHEMA, V19_CALLS_SCHEMA

NOW = "2026-10-29T09:00:00+00:00"
WHEN = datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)


def _v17_log(path, tasks=3):
    conn = sqlite3.connect(path)
    conn.executescript(f"{V17_SCHEMA}; {V19_CALLS_SCHEMA}; PRAGMA user_version = 17;")
    for n in range(1, tasks + 1):
        task_id = f"sr-20261029-09000{n}-ab1{n}"
        conn.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, skill, skill_source, "
                     "status, chat) VALUES (?, ?, ?, 'cli', ?, 'ok', 'writing', 'jev', 'done', 'tray')",
                     (task_id, NOW, NOW, f"task {n}"))
        conn.execute("INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at, text) "
                     "VALUES (?, ?, 'do', 'claude', 'done', ?, 'result')", (task_id, task_id, NOW))
    conn.commit()
    conn.close()


def _columns(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def test_a_new_log_is_version_18_with_the_two_columns_last_and_the_ideas_table():
    c = log.init_db(":memory:")
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 21
    assert _columns(c, "tasks")[-6:] == ["from_task", "idea", "plan", "plan_step", "models", "auto"]  # briefs 33.1 and 33.3 add after
    assert _columns(c, "ideas") == ["id", "project", "text", "source_kind", "source_task", "created_at", "dismissed_at"]
    assert c.execute("SELECT COUNT(*) FROM ideas").fetchone()[0] == 0


def test_the_ideas_table_takes_only_its_two_source_kinds():
    c = log.init_db(":memory:")
    c.execute("INSERT INTO ideas (project, text, source_kind, created_at) VALUES ('demo', 'Add a round option', 'added', ?)",
              (NOW,))
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO ideas (project, text, source_kind, created_at) VALUES ('demo', 'x', 'suggested', ?)", (NOW,))


def test_a_version_17_log_is_refused_until_migrated_and_names_what_is_added(tmp_path):
    db = tmp_path / "router.db"
    _v17_log(db)
    with pytest.raises(log.VersionError, match=r"version 17 log.*sr migrate.*version 21 \(" + log.V18_ADDED + "; " + log.V19_ADDED + "; " + log.V20_ADDED + "; " + log.V21_ADDED + r"\)"):
        log.init_db(db)


def test_the_upgrade_backs_up_then_adds_the_columns_and_the_table_and_keeps_every_row(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _v17_log(db)
    done = log.migrate(db, backups, now=WHEN)
    assert done["added"] == log.UPGRADES[17]["added"] == log.V18_ADDED + "; " + log.V19_ADDED + "; " + log.V20_ADDED + "; " + log.V21_ADDED
    assert (done["from"], done["rows"], done["calls"], done["highest"]) == (17, 3, 3, 3)
    assert done["backup"].name == "router-v17-2026-10-29.db" and done["backup_check"]["content"] == "same"
    assert done["journal_mode"] == "wal"
    c = log.init_db(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 21
    assert [tuple(r) for r in c.execute("SELECT from_task, idea FROM tasks")] == [(None, None)] * 3
    assert [r[0] for r in c.execute("SELECT chat FROM tasks")] == ["tray"] * 3
    assert c.execute("SELECT COUNT(*) FROM ideas").fetchone()[0] == 0
    backup = sqlite3.connect(done["backup"])
    assert backup.execute("PRAGMA user_version").fetchone()[0] == 17 and "from_task" not in _columns(backup, "tasks")
    assert backup.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'ideas'").fetchone()[0] == 0
    backup.close()
    with pytest.raises(log.MigrateRefused, match="already a version 21"):
        log.migrate(db, backups, now=WHEN)


def test_every_older_upgrade_lands_on_18_with_the_columns_and_the_table():
    for from_version in range(2, 18):
        plan = log.UPGRADES[from_version]
        assert "ADD COLUMN from_task TEXT" in plan["statements"] and "ADD COLUMN idea INTEGER" in plan["statements"]
        assert plan["statements"].count("CREATE TABLE ideas") == 1, from_version
        assert plan["added"].endswith(log.V18_ADDED + "; " + log.V19_ADDED + "; " + log.V20_ADDED + "; " + log.V21_ADDED), from_version


def test_sr_migrate_prints_the_backup_and_the_counts(tmp_path, capsys):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _v17_log(db, tasks=2)
    assert cli.cmd_migrate(db_path=db, backups_dir=backups, now=WHEN) == 0
    out = capsys.readouterr().out
    assert "version 17, 2 rows (highest #2)" in out and f"Upgraded in place: {log.V18_ADDED}; {log.V19_ADDED}; {log.V20_ADDED}; {log.V21_ADDED}, now version 21." in out
