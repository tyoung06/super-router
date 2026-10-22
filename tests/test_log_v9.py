"""Build brief 11, phase A: log version 9 (rules v2.18, Split). A task row gains `parent` (the split's task id,
on a piece) and `split_plan` (the approved plan as JSON, on a split); `mode` gains `split` and `piece`, checked
in code (no CHECK on mode, Phase 0 gate 4). `sr log` prints pieces indented under their parent.
Every value here is fake."""
import json
import sqlite3

import pytest

from router import __main__ as cli
from router import log

from helpers import ALL_AGENTS, JEV_OK, V13_CALLS_SCHEMA, V13_SCHEMA

NOT_ASKED = {"status": "not_asked"}


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _split(conn, tid="sr-s", task="Write an intro and a checklist."):
    log.add_task(conn, tid, task, "cli", NOT_ASKED, mode="split")
    return log.get_task(conn, tid)


# ---------- the columns ----------

def test_a_new_log_is_version_9_with_parent_and_split_plan_last_on_tasks():
    c = log.init_db(":memory:")
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 16
    assert [r[1] for r in c.execute("PRAGMA table_info(tasks)")][-12:] == ["parent", "split_plan", "slots", "web", "project", "handoff", "chat", "memory", "reason_code", "pid", "run_started_at", "answered_by"]


def test_mode_still_has_no_check_constraint_and_status_keeps_its_own():
    c = log.init_db(":memory:")
    sql = c.execute("SELECT sql FROM sqlite_master WHERE name = 'tasks'").fetchone()[0]
    assert sql.count("CHECK") == 1 and "status IN" in sql


def test_modes_are_route_relay_split_piece():
    assert log.MODES == ("route", "relay", "split", "piece")


# ---------- a split row ----------

def test_a_split_task_is_not_sent_to_jev(conn):
    row = _split(conn)
    assert (row["mode"], row["jev_status"], row["parent"], row["preset"]) == ("split", "not_asked", None, None)
    with pytest.raises(ValueError, match="split task.*not_asked"):
        log.add_task(conn, "sr-x", "t", "cli", JEV_OK, mode="split")


def test_a_split_task_has_no_preset_and_no_parent(conn):
    with pytest.raises(ValueError, match="only a relay task has a preset"):
        log.add_task(conn, "sr-x", "t", "cli", NOT_ASKED, mode="split", preset="collab")
    _split(conn)
    with pytest.raises(ValueError, match="only a piece has a parent"):
        log.add_task(conn, "sr-y", "t", "cli", NOT_ASKED, mode="split", parent="sr-s")


def test_not_asked_is_for_relay_and_split_only(conn):
    with pytest.raises(ValueError, match="not_asked"):
        log.add_task(conn, "sr-x", "t", "cli", NOT_ASKED)
    with pytest.raises(ValueError, match="not_asked"):
        _split(conn)
        log.add_task(conn, "sr-p", "t", "cli", NOT_ASKED, mode="piece", parent="sr-s")


# ---------- a piece row ----------

def test_a_piece_names_its_split_and_is_labeled_by_jev(conn):
    _split(conn)
    log.add_task(conn, "sr-p1", "Write a 100-word intro.", "split", JEV_OK, mode="piece", parent="sr-s")
    row = log.get_task(conn, "sr-p1")
    assert (row["mode"], row["parent"], row["jev_status"], row["jev_label"]) == ("piece", "sr-s", "ok", "quick_answer")


def test_a_piece_needs_a_parent_that_is_a_split_task(conn):
    with pytest.raises(ValueError, match="a piece needs its parent"):
        log.add_task(conn, "sr-p", "t", "split", JEV_OK, mode="piece")
    with pytest.raises(log.StateError, match="no such task"):
        log.add_task(conn, "sr-p", "t", "split", JEV_OK, mode="piece", parent="sr-nope")
    log.add_task(conn, "sr-r", "t", "cli", JEV_OK)
    with pytest.raises(log.StateError, match="not a split task"):
        log.add_task(conn, "sr-p", "t", "split", JEV_OK, mode="piece", parent="sr-r")
    assert log.get_task(conn, "sr-p") is None


def test_a_route_task_has_no_parent(conn):
    _split(conn)
    with pytest.raises(ValueError, match="only a piece has a parent"):
        log.add_task(conn, "sr-r", "t", "cli", JEV_OK, parent="sr-s")


def test_pieces_of_a_split_come_back_in_creation_order(conn):
    _split(conn)
    _split(conn, "sr-other")
    for tid in ("sr-p2", "sr-p1", "sr-p3"):
        log.add_task(conn, tid, tid, "split", JEV_OK, mode="piece", parent="sr-s")
    log.add_task(conn, "sr-q", "q", "split", JEV_OK, mode="piece", parent="sr-other")
    assert [r["task_id"] for r in log.pieces_of(conn, "sr-s")] == ["sr-p2", "sr-p1", "sr-p3"]
    assert [r["task_id"] for r in log.pieces_of(conn, "sr-other")] == ["sr-q"]


# ---------- the stored plan ----------

PLAN = {"join": "Intro first, then the checklist.",
        "pieces": [{"id": "sr-p1", "planner_text": "Write a 100-word intro.", "edited_text": None},
                   {"id": "sr-p2", "planner_text": "Write a 5-item checklist.", "edited_text": "A 5-item list."}]}


def test_the_plan_is_stored_as_json_on_the_split_row_and_read_back(conn):
    _split(conn)
    log.set_split_plan(conn, "sr-s", PLAN)
    row = log.get_task(conn, "sr-s")
    assert json.loads(row["split_plan"]) == PLAN
    assert log.split_plan_of(row) == PLAN


def test_only_a_split_task_carries_a_plan(conn):
    log.add_task(conn, "sr-r", "t", "cli", JEV_OK)
    with pytest.raises(log.StateError, match="not a split task"):
        log.set_split_plan(conn, "sr-r", PLAN)
    assert log.split_plan_of(log.get_task(conn, "sr-r")) is None


def test_plan_time_jev_tokens_go_on_the_split_row_so_the_monthly_sum_counts_them(conn):
    _split(conn)
    assert log.jev_tokens_this_month(conn) == 0
    log.add_jev_tokens(conn, "sr-s", 700)
    log.add_jev_tokens(conn, "sr-s", 650)
    assert log.get_task(conn, "sr-s")["jev_tokens"] == 1350
    assert log.jev_tokens_this_month(conn) == 1350
    with pytest.raises(ValueError):
        log.add_jev_tokens(conn, "sr-s", -1)
    log.add_task(conn, "sr-r", "t", "cli", JEV_OK)
    with pytest.raises(log.StateError, match="not a split task"):
        log.add_jev_tokens(conn, "sr-r", 5)


# ---------- the upgrade 8 -> 9 ----------

def _make_v8(path):
    c = sqlite3.connect(path)
    tasks_v8 = V13_SCHEMA.replace(",\n    parent          TEXT,\n    split_plan      TEXT,\n    slots           TEXT,\n    web             INTEGER" + ",\n    project         TEXT,\n    handoff         TEXT,\n    chat            TEXT,\n    memory          TEXT", "")
    calls_v8 = V13_CALLS_SCHEMA.replace(",\n    context     TEXT,\n    memory      TEXT,\n    served      TEXT", "")
    assert "parent" not in tasks_v8 and "split_plan" not in tasks_v8
    c.executescript(f"{tasks_v8}; {calls_v8}; PRAGMA user_version = 8;")
    for i in (1, 2):
        c.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, status) VALUES "
                  f"('sr-{i}', '2026-10-15T00:00:0{i}+00:00', '2026-10-15T00:00:0{i}+00:00', 'cli', 't{i}', 'ok', 'done')")
    c.execute("INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at) VALUES "
              "('sr-1', 'sr-1', 'do', 'claude', 'done', '2026-10-15T00:00:00+00:00')")
    c.commit()
    c.close()


def test_upgrade_from_version_8_adds_parent_and_split_plan_and_keeps_every_row(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _make_v8(db)
    with pytest.raises(log.VersionError, match=r"version 8 log.*sr migrate.*version 16 \(parent and split_plan columns added"):
        log.init_db(db)
    done = log.migrate(db, backups)
    assert done["added"] == log.UPGRADES[8]["added"] == "parent and split_plan columns added to tasks; slots and web columns added to tasks; project and handoff columns added to tasks; context column added to calls; chat and memory columns added to tasks; memory column added to calls; served column added to calls; reason_code column added to tasks; round_file column added to calls; pid, run_started_at and answered_by columns added to tasks; skill_source set to owner where it named the one who labeled the task"
    assert (done["rows"], done["calls"], done["highest"]) == (2, 1, 2)
    assert (backups / done["backup"].name).exists() and done["backup"].name.startswith("router-v8-")
    c = log.init_db(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 16
    assert [tuple(r) for r in c.execute("SELECT parent, split_plan FROM tasks")] == [(None, None), (None, None)]
    assert [r["mode"] for r in c.execute("SELECT mode FROM tasks")] == ["route", "route"]
    c.close()
    with pytest.raises(log.MigrateRefused, match="already a version 16"):
        log.migrate(db, backups)


def test_sr_migrate_prints_the_8_to_9_upgrade(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _make_v8(db)
    lines = []
    assert cli.cmd_migrate(db_path=db, backups_dir=backups, out=lines.append) == 0
    out = "\n".join(lines)
    assert "version 8, 2 rows (highest #2)" in out
    assert "Upgraded in place: parent and split_plan columns added to tasks; slots and web columns added to tasks; project and handoff columns added to tasks; context column added to calls; chat and memory columns added to tasks; memory column added to calls; served column added to calls; reason_code column added to tasks; round_file column added to calls; pid, run_started_at and answered_by columns added to tasks; skill_source set to owner where it named the one who labeled the task, now version 16." in out


def test_every_older_upgrade_lands_on_9_with_the_split_columns():
    for version, plan in log.UPGRADES.items():
        if version in (9, 10, 11, 12, 13, 14, 15):  # brief 15's 9 -> 10, brief 18's 10 -> 11, brief 19's 11 -> 12, brief 20's 12 -> 13, brief 21's 13 -> 14 and brief 22's 14 -> 15 add later columns only; brief 25's 15 -> 16 renames a stored value only
            continue
        assert "ADD COLUMN parent TEXT" in plan["statements"], version
        assert "ADD COLUMN split_plan TEXT" in plan["statements"], version
        assert "parent and split_plan" in plan["added"], version


# ---------- sr log ----------

def _done_piece(conn, tid, parent, text):
    log.add_task(conn, tid, text, "split", JEV_OK, mode="piece", parent=parent)
    log.set_route(conn, tid, agents=ALL_AGENTS, agent="claude", route_reason="best")


def test_sr_log_prints_pieces_indented_under_their_parent(conn):
    log.add_task(conn, "sr-a", "an older routed task", "cli", JEV_OK)
    _split(conn)
    _done_piece(conn, "sr-p1", "sr-s", "piece one text")
    _done_piece(conn, "sr-p2", "sr-s", "piece two text")
    log.add_task(conn, "sr-b", "a newer routed task", "cli", JEV_OK)
    lines = []
    cli.cmd_log(conn=conn, out=lines.append)
    body = lines[1:]
    order = [next(t for t in ("sr-b", "sr-s", "sr-p1", "sr-p2", "sr-a") if t in line) for line in body]
    assert order == ["sr-b", "sr-s", "sr-p1", "sr-p2", "sr-a"]
    split_line, p1, p2 = body[1], body[2], body[3]
    assert p1.startswith("  ↳") and p2.startswith("  ↳") and "↳" not in split_line
    assert "piece one text" in p1


def test_sr_log_prints_a_piece_whose_parent_is_off_the_page_still_marked(conn):
    _split(conn)
    _done_piece(conn, "sr-p1", "sr-s", "piece one text")
    lines = []
    cli.cmd_log(conn=conn, limit=1, out=lines.append)
    assert len(lines) == 2 and lines[1].startswith("  ↳") and "sr-p1" in lines[1]
