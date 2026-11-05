"""Build brief 33.1 (decision 19): log version 19 adds `tasks.plan` (a plan task's plan as the planner returned it, the
owner's edits and the hash of the docs/PLAN.md it rendered) and `tasks.plan_step` (a step task's plan task and step), and
the mode `plan`. `sr migrate` copies the log into backups/ through SQLite's backup API first, then adds the columns in
place; the counts and every older column are the same after, and every old row reads NULL in both columns."""
import sqlite3
from datetime import datetime, timezone

import pytest

from router import __main__ as cli
from router import log
from tests.helpers import V18_SCHEMA, V19_CALLS_SCHEMA

NOW = "2026-10-29T09:00:00+00:00"
WHEN = datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)


def _v18_log(path, tasks=3):
    conn = sqlite3.connect(path)
    conn.executescript(f"{V18_SCHEMA}; {V19_CALLS_SCHEMA}; {log.IDEAS_SCHEMA}; PRAGMA user_version = 18;")
    for n in range(1, tasks + 1):
        task_id = f"sr-20261029-09000{n}-ab1{n}"
        conn.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, skill, skill_source, "
                     "status, project, from_task) VALUES (?, ?, ?, 'cli', ?, 'ok', 'writing', 'jev', 'done', 'garden', ?)",
                     (task_id, NOW, NOW, f"task {n}", None if n == 1 else "sr-20261029-090001-ab11"))
        conn.execute("INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at, text) "
                     "VALUES (?, ?, 'do', 'claude', 'done', ?, 'result')", (task_id, task_id, NOW))
    conn.execute("INSERT INTO ideas (project, text, source_kind, created_at) VALUES ('garden', 'Add a frost alert', "
                 "'added', ?)", (NOW,))
    conn.commit()
    conn.close()


def _columns(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def test_a_new_log_is_version_19_with_the_two_plan_columns_last():
    c = log.init_db(":memory:")
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 21
    assert _columns(c, "tasks")[-4:] == ["plan", "plan_step", "models", "auto"]  # brief 33.3 adds one after
    assert "plan" in log.MODES and "plan" in log.CHAINED_MODES and "plan" in log.NOT_ASKED_MODES


def test_a_version_18_log_is_refused_until_migrated_and_names_what_is_added(tmp_path):
    db = tmp_path / "router.db"
    _v18_log(db)
    with pytest.raises(log.VersionError, match=r"version 18 log.*sr migrate.*version 21 \(" + log.V19_ADDED + "; " + log.V20_ADDED + "; " + log.V21_ADDED + r"\)"):
        log.init_db(db)


def test_the_upgrade_backs_up_then_adds_the_columns_and_reads_every_row_as_before(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _v18_log(db)
    done = log.migrate(db, backups, now=WHEN)
    assert done["added"] == log.UPGRADES[18]["added"] == log.V19_ADDED + "; " + log.V20_ADDED + "; " + log.V21_ADDED
    assert (done["from"], done["rows"], done["calls"], done["highest"]) == (18, 3, 3, 3)
    assert done["backup"].name == "router-v18-2026-10-29.db" and done["backup_check"]["content"] == "same"
    c = log.init_db(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 21
    assert [tuple(r) for r in c.execute("SELECT plan, plan_step FROM tasks")] == [(None, None)] * 3
    assert [r[0] for r in c.execute("SELECT from_task FROM tasks ORDER BY rowid")] == [
        None, "sr-20261029-090001-ab11", "sr-20261029-090001-ab11"]
    assert c.execute("SELECT COUNT(*) FROM ideas").fetchone()[0] == 1
    row = log.task_by_number(c, 1)
    assert log.plan_of(row) is None and log.plan_step_of(row) is None
    backup = sqlite3.connect(done["backup"])
    assert backup.execute("PRAGMA user_version").fetchone()[0] == 18 and "plan" not in _columns(backup, "tasks")
    backup.close()
    with pytest.raises(log.MigrateRefused, match="already a version 21"):
        log.migrate(db, backups, now=WHEN)


def test_every_older_upgrade_lands_on_19_with_the_plan_columns():
    for from_version in range(2, 19):
        plan = log.UPGRADES[from_version]
        assert "ADD COLUMN plan TEXT" in plan["statements"] and "ADD COLUMN plan_step TEXT" in plan["statements"]
        assert plan["added"].endswith(log.V19_ADDED + "; " + log.V20_ADDED + "; " + log.V21_ADDED), from_version


def test_sr_migrate_prints_the_backup_and_the_counts(tmp_path, capsys):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _v18_log(db, tasks=2)
    assert cli.cmd_migrate(db_path=db, backups_dir=backups, now=WHEN) == 0
    out = capsys.readouterr().out
    assert "version 18, 2 rows (highest #2)" in out and f"Upgraded in place: {log.V19_ADDED}; {log.V20_ADDED}; {log.V21_ADDED}, now version 21." in out


def test_a_plan_task_and_a_step_task_keep_their_records():
    c = log.init_db(":memory:")
    log.add_task(c, "sr-20261029-100000-aa01", "Plan the first version.", "cli", {"status": "not_asked", "tokens": 0},
                 mode="plan", preset="redteam", project="garden", plan={"menu": ["route"]})
    row = log.get_task(c, "sr-20261029-100000-aa01")
    assert log.plan_of(row) == {"menu": ["route"]} and row["mode"] == "plan" and log.runs_preset(row)
    log.add_task(c, "sr-20261029-100000-aa02", "Make the skeleton.", "cli", {"status": "ok", "label": "code",
                                                                          "confidence": 0.9},
                 project="garden", plan_step={"plan": "sr-20261029-100000-aa01", "step": 1})
    assert log.plan_step_of(log.get_task(c, "sr-20261029-100000-aa02")) == {"plan": "sr-20261029-100000-aa01", "step": 1}
    with pytest.raises(ValueError, match="a plan task has a project"):
        log.add_task(c, "sr-20261029-100000-aa03", "x", "cli", {"status": "not_asked", "tokens": 0}, mode="plan",
                     preset="redteam", plan={"menu": []})
    with pytest.raises(ValueError, match="starts with its plan record"):
        log.add_task(c, "sr-20261029-100000-aa04", "x", "cli", {"status": "not_asked", "tokens": 0}, mode="plan",
                     preset="redteam", project="garden")
