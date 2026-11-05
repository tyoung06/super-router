"""Build brief 34 (decision 14): log version 21 adds `tasks.auto`, a run row's record (its plan, its steps, the budget, the
calls used, the stop and the passed marks); the stop-here marks live on the plan row's record and a run's step names the
run as its parent. `sr migrate` copies the log into backups/ through SQLite's backup API first, then adds the column in
place; the counts and every older column are the same after, and every old row reads NULL in it. Every value here is fake."""
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from router import __main__ as cli
from router import log
from tests.helpers import V19_CALLS_SCHEMA, V20_SCHEMA

NOW = "2026-10-30T09:00:00+00:00"
WHEN = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)


def _v20_log(path, tasks=3):
    conn = sqlite3.connect(path)
    conn.executescript(f"{V20_SCHEMA}; {log.CALLS_SCHEMA}; {log.IDEAS_SCHEMA}; PRAGMA user_version = 20;")
    for n in range(1, tasks + 1):
        task_id = f"sr-20261030-09000{n}-ab1{n}"
        conn.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, skill, skill_source, "
                     "status, project, models) VALUES (?, ?, ?, 'cli', ?, 'ok', 'code', 'jev', 'done', 'garden', ?)",
                     (task_id, NOW, NOW, f"task {n}", json.dumps({"claude": {"model": "claude-opus-5-5", "effort": None}}) if n == 2 else None))
        conn.execute("INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at, text, model, time_limit) "
                     "VALUES (?, ?, 'do', 'claude', 'done', ?, 'result', 'claude-opus-5-5', 1200)", (task_id, task_id, NOW))
    conn.commit()
    conn.close()


def _columns(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def test_a_new_log_is_version_21_with_auto_last():
    c = log.init_db(":memory:")
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 21
    assert _columns(c, "tasks")[-2:] == ["models", "auto"]
    assert log.V20_COLUMNS[-1] == "models" and log.V20_CALL_COLUMNS[-3:] == ("model", "effort", "time_limit")


def test_a_version_20_log_is_refused_until_migrated(tmp_path):
    db = tmp_path / "router.db"
    _v20_log(db)
    with pytest.raises(log.VersionError, match=r"version 20 log.*sr migrate.*version 21 \(" + log.V21_ADDED + r"\)"):
        log.init_db(db)


def test_migrate_adds_the_column_in_place_and_keeps_every_older_column(tmp_path, capsys):
    db = tmp_path / "router.db"
    _v20_log(db)
    done = log.migrate(db, tmp_path / "backups", now=WHEN)
    assert done["from"] == 20 and done["added"] == log.UPGRADES[20]["added"] == log.V21_ADDED
    c = sqlite3.connect(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 21
    assert _columns(c, "tasks")[-2:] == ["models", "auto"]
    rows = c.execute("SELECT task_id, models, auto FROM tasks ORDER BY rowid").fetchall()
    assert [r[2] for r in rows] == [None, None, None] and json.loads(rows[1][1])["claude"]["model"] == "claude-opus-5-5"
    assert c.execute("SELECT model, time_limit FROM calls").fetchall() == [("claude-opus-5-5", 1200)] * 3
    c.close()
    with pytest.raises(log.MigrateRefused, match="already a version 21"):
        log.migrate(db, tmp_path / "backups", now=WHEN)
    assert cli.cmd_migrate(db_path=db, backups_dir=tmp_path / "backups", now=WHEN) == 2  # the command says so too
    out = capsys.readouterr().out
    assert "already a version 21" in out


def test_every_older_upgrade_lands_on_21():
    for from_version, plan in log.UPGRADES.items():
        assert plan["added"].endswith(log.V21_ADDED), from_version
        assert "auto" in plan["statements"], from_version


def test_a_run_row_and_its_steps(tmp_path):
    c = log.init_db(":memory:")
    record = {"plan": "sr-plan", "n": 7, "from_step": 1, "steps": [{"k": 1, "task_id": None, "state": "open", "attempt": 0}],
              "budget": 6, "used": 0, "stop": None, "passed_marks": []}
    c.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, status, mode, project, plan) "
              "VALUES ('sr-plan', ?, ?, 'cli', 'plan', 'not_asked', 'done', 'plan', 'garden', '{}')", (NOW, NOW))
    log.add_task(c, "sr-run", "Auto: plan #7", "cli", {"status": "not_asked", "tokens": 0}, mode="auto", project="garden",
                 auto=record)
    row = log.get_task(c, "sr-run")
    assert row["mode"] == "auto" and log.auto_of(row) == record and row["preset"] is None
    log.set_auto(c, "sr-run", {**record, "used": 2})
    assert log.auto_of(log.get_task(c, "sr-run"))["used"] == 2
    # a step of the run: a routed task with its plan step whose parent is the run (decision 2)
    log.add_task(c, "sr-step", "step one", "cli", {"status": "ok", "label": "code", "confidence": 0.9, "needs_split": 0.1, "tokens": 0},
                 mode="route", project="garden", parent="sr-run", plan_step={"plan": "sr-plan", "step": 1})
    step = log.get_task(c, "sr-step")
    assert log.is_piece(step) and step["parent"] == "sr-run" and log.plan_step_of(step) == {"plan": "sr-plan", "step": 1}
    assert [r["task_id"] for r in log.pieces_of(c, "sr-run")] == ["sr-step"]
    with pytest.raises(ValueError, match="a run's step"):  # a routed task with a run parent needs its plan step
        log.add_task(c, "sr-x", "x", "cli", {"status": "ok", "label": "code", "confidence": 0.9, "needs_split": 0.1, "tokens": 0},
                     mode="route", project="garden", parent="sr-run")
    with pytest.raises(ValueError, match="a run has a project"):
        log.add_task(c, "sr-y", "x", "cli", {"status": "not_asked", "tokens": 0}, mode="auto", auto=record)
    with pytest.raises(ValueError, match="starts with its auto record"):
        log.add_task(c, "sr-z", "x", "cli", {"status": "not_asked", "tokens": 0}, mode="auto", project="garden")
    with pytest.raises(log.StateError, match="not a run"):
        log.set_auto(c, "sr-step", record)
    # a stopped run (returned) is the project's open task (decision 1); its step never is (a parent row)
    c.execute("UPDATE tasks SET status = 'returned', check_note = 'auto stopped: stop here before step 2' WHERE task_id = 'sr-run'")
    c.commit()
    assert log.open_task_for(c, "garden")["task_id"] == "sr-run"
