"""Build brief 33.3 (decision 7): log version 20 adds `tasks.models` (a task's own model choices from `--model` and
`--effort`), `calls.model` (the model a call asked for), `calls.effort` and `calls.time_limit`; `calls.served` (version
13's column) takes every agent's record. `sr migrate` copies the log into backups/ through SQLite's backup API first, then
adds the columns in place; the counts and every older column are the same after, every old row reads NULL in the new
columns, an old Claude row reads as asked `sonnet` with its served model unknown. Every value here is fake."""
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from router import __main__ as cli
from router import log, models
from tests.helpers import V19_CALLS_SCHEMA, V19_SCHEMA

NOW = "2026-10-29T09:00:00+00:00"
WHEN = datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)


def _v19_log(path, tasks=3):
    conn = sqlite3.connect(path)
    conn.executescript(f"{V19_SCHEMA}; {V19_CALLS_SCHEMA}; {log.IDEAS_SCHEMA}; PRAGMA user_version = 19;")
    for n in range(1, tasks + 1):
        task_id = f"sr-20261029-09000{n}-ab1{n}"
        conn.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, skill, skill_source, "
                     "status, project, plan_step) VALUES (?, ?, ?, 'cli', ?, 'ok', 'code', 'jev', 'done', 'garden', ?)",
                     (task_id, NOW, NOW, f"task {n}", None if n == 1 else json.dumps({"plan": "sr-20261029-090001-ab11", "step": n})))
        conn.execute("INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at, text, served) "
                     "VALUES (?, ?, 'do', ?, 'done', ?, 'result', ?)",
                     (task_id, task_id, "cursor" if n == 3 else "claude", NOW,
                      json.dumps({"asked": "grok-4.7-high", "model": "Grok 4.7 256K High", "tool_events": 0}) if n == 3 else None))
    conn.commit()
    conn.close()


def _columns(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def test_a_new_log_is_version_20_with_the_new_columns_last():
    c = log.init_db(":memory:")
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 21
    assert _columns(c, "tasks")[-2:] == ["models", "auto"]  # brief 34: log 21 adds auto
    assert _columns(c, "calls")[-3:] == ["model", "effort", "time_limit"]


def test_a_version_19_log_is_refused_until_migrated_and_names_what_is_added(tmp_path):
    db = tmp_path / "router.db"
    _v19_log(db)
    with pytest.raises(log.VersionError, match=r"version 19 log.*sr migrate.*version 21 \(" + log.V20_ADDED + "; " + log.V21_ADDED + r"\)"):
        log.init_db(db)


def test_the_upgrade_backs_up_then_adds_the_columns_and_reads_every_row_as_before(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _v19_log(db)
    done = log.migrate(db, backups, now=WHEN)
    assert done["added"] == log.UPGRADES[19]["added"] == log.V20_ADDED + "; " + log.V21_ADDED
    assert (done["from"], done["rows"], done["calls"], done["highest"]) == (19, 3, 3, 3)
    assert done["backup"].name == "router-v19-2026-10-29.db" and done["backup_check"]["content"] == "same"
    assert done["journal_mode"] == "wal"
    c = log.init_db(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 21
    assert [r[0] for r in c.execute("SELECT models FROM tasks")] == [None] * 3
    assert [tuple(r) for r in c.execute("SELECT model, effort, time_limit FROM calls")] == [(None, None, None)] * 3
    assert [log.plan_step_of(r) for r in c.execute("SELECT * FROM tasks ORDER BY rowid")][1] == {"plan": "sr-20261029-090001-ab11", "step": 2}
    row = log.task_by_number(c, 1)
    assert log.models_of(row) == {}
    old = log.get_call(c, "sr-20261029-090001-ab11")
    assert log.served_of(old) is None and models.asked_of(old, {"chatgpt": "gpt-6.1-sol"}) == "sonnet"  # decision 7: as asked
    cursor = log.get_call(c, "sr-20261029-090003-ab13")
    assert log.served_of(cursor)["model"] == "Grok 4.7 256K High"  # the version 13 record kept
    backup = sqlite3.connect(done["backup"])
    assert backup.execute("PRAGMA user_version").fetchone()[0] == 19 and "models" not in _columns(backup, "tasks")
    assert "time_limit" not in _columns(backup, "calls")
    backup.close()
    with pytest.raises(log.MigrateRefused, match="already a version 21"):
        log.migrate(db, backups, now=WHEN)


def test_every_older_upgrade_lands_on_20_with_the_four_columns():
    for from_version in range(2, 20):
        plan = log.UPGRADES[from_version]
        assert "ADD COLUMN models TEXT" in plan["statements"], from_version
        if from_version != 2:  # version 2 makes its calls table from CALLS_SCHEMA, which already has them
            assert "ADD COLUMN time_limit INTEGER" in plan["statements"] and "ADD COLUMN effort TEXT" in plan["statements"]
        assert plan["added"].endswith(log.V20_ADDED + "; " + log.V21_ADDED), from_version


def test_sr_migrate_prints_the_backup_and_the_columns(tmp_path, capsys):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _v19_log(db)
    assert cli.cmd_migrate(db_path=db, backups_dir=backups, now=WHEN) == 0
    out = capsys.readouterr().out
    assert "Log: router.db, version 19, 3 rows (highest #3), integrity ok, no open tasks." in out
    assert f"Upgraded in place: {log.V20_ADDED}; {log.V21_ADDED}, now version 21." in out


def test_add_task_keeps_the_models_choices_and_refuses_a_bad_shape():
    c = log.init_db(":memory:")
    jev = {"status": "ok", "label": "code", "confidence": 0.9, "needs_split": 0.1, "tokens": 0}
    choices = {"claude": {"model": "claude-haiku-5-5", "effort": None}, "chatgpt": {"model": None, "effort": "ultra"}}
    log.add_task(c, "sr-a", "t", "cli", jev, models=choices)
    assert log.models_of(log.get_task(c, "sr-a")) == choices
    log.add_task(c, "sr-b", "t", "cli", jev)
    assert log.models_of(log.get_task(c, "sr-b")) == {}
    for bad in ({}, {"claude": "haiku"}, {"claude": {"model": None, "effort": None}}, {"claude": {"colour": "x"}}, [1]):
        with pytest.raises(ValueError, match="models map each agent"):
            log.add_task(c, "sr-c", "t", "cli", jev, models=bad)
    assert log.get_task(c, "sr-c") is None


def test_add_call_keeps_the_model_effort_limit_and_any_agents_served_record():
    c = log.init_db(":memory:")
    log.add_task(c, "sr-a", "t", "cli", {"status": "ok", "label": "code", "confidence": 0.9, "needs_split": 0.1, "tokens": 0})
    served = {"asked": "claude-opus-5-5", "model": "claude-opus-5-5", "source": "stream: init and modelUsage",
              "credits": {"seen": False}}
    log.add_call(c, "sr-a", "sr-a", "do", "claude", status="done", text="x", model="claude-opus-5-5", effort="high",
                 time_limit=1200, served=served)
    row = log.get_call(c, "sr-a")
    assert (row["model"], row["effort"], row["time_limit"]) == ("claude-opus-5-5", "high", 1200)
    assert log.served_of(row) == served and models.asked_of(row) == "claude-opus-5-5"
    log.add_call(c, "sr-a-c1", "sr-a", "check", "chatgpt", status="done", text="PASS", model="gpt-6.1-sol", time_limit=600,
                 served={"asked": "gpt-6.1-sol", "model": "gpt-6.1-sol", "source": "codex header", "credits": {"seen": False}})
    assert log.served_of(log.get_call(c, "sr-a-c1"))["source"] == "codex header"
    for kw in ({"model": ""}, {"effort": 3}, {"time_limit": 0}, {"time_limit": True}, {"served": {"model": "x"}},
               {"served": {"asked": "x", "tool_events": "two"}}):
        with pytest.raises(ValueError):
            log.add_call(c, "sr-a-f1", "sr-a", "fix", "claude", status="done", text="x", **kw)
    assert log.get_call(c, "sr-a-f1") is None
    log.add_call(c, "sr-a-s2", "sr-a", "stage", "cursor", status="done", text="x", stage=2, role="build",
                 served={"asked": "grok-4.7-high", "model": "Grok 4.7 256K High", "tool_events": 0, "tools": []})
    assert log.served_of(log.get_call(c, "sr-a-s2"))["tool_events"] == 0  # Cursor's record as brief 20 made it
