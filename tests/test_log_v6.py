"""The version 6 log (build brief 7, resume): `reason_code` and `resume_of` on a call, and
`sr migrate`'s upgrade from version 5."""
import sqlite3
import stat
from datetime import datetime, timezone

import pytest

from router import __main__ as cli
from router import log
from tests.helpers import add_row, make_v5_log, sha256

T0 = datetime(2026, 10, 15, 21, 0, tzinfo=timezone.utc)
BACKUP_V5 = "router-v5-2026-10-15.db"


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _columns(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def test_a_new_log_is_version_6_with_the_resume_columns(tmp_path):
    c = log.init_db(tmp_path / "router.db")
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 16
    assert _columns(c, "calls")[-10:] == ["stage", "role", "reason_code", "resume_of", "search", "fallback_of", "context", "memory", "served", "round_file"]
    assert log.V5_CALL_COLUMNS == log.V4_CALL_COLUMNS + ("stage", "role")
    assert log.V5_COLUMNS == log.V4_COLUMNS + ("mode", "preset", "failed_stage")
    assert log.REASON_CODES == ("plan_limit", "process_ended",  # brief 22 added the process-ended stop
                                "overdue", "late", "too_long", "internal_error")  # brief 24 (C5): the takeover's codes
    c.close()


def test_a_failed_call_can_carry_the_plan_limit_code(conn):
    add_row(conn, "sr-1")
    log.add_call(conn, "sr-1", "sr-1", "do", "claude", status="failed", text="plan limit on claude: x",
                 reason_code="plan_limit")
    assert log.get_call(conn, "sr-1")["reason_code"] == "plan_limit"


def test_an_unknown_code_or_a_code_on_a_call_that_did_not_fail_is_refused(conn):
    add_row(conn, "sr-1")
    with pytest.raises(ValueError, match="reason_code"):
        log.add_call(conn, "sr-1", "sr-1", "do", "claude", status="failed", reason_code="tired")
    with pytest.raises(ValueError, match="failed call"):
        log.add_call(conn, "sr-1", "sr-1", "do", "claude", status="done", text="ok", reason_code="plan_limit")
    assert log.calls_for(conn, "sr-1") == []


def test_resume_of_names_a_call_of_the_same_task(conn):
    add_row(conn, "sr-1")
    add_row(conn, "sr-2")
    log.add_call(conn, "sr-1", "sr-1", "do", "claude", status="failed", text="x", reason_code="plan_limit")
    log.add_call(conn, "sr-1-resume", "sr-1", "do", "chatgpt", status="done", text="ok", resume_of="sr-1")
    assert log.get_call(conn, "sr-1-resume")["resume_of"] == "sr-1"
    with pytest.raises(log.StateError, match="resume_of"):
        log.add_call(conn, "sr-2-resume", "sr-2", "do", "chatgpt", status="done", text="ok", resume_of="sr-1")
    with pytest.raises(log.StateError, match="resume_of"):
        log.add_call(conn, "sr-2-resume", "sr-2", "do", "chatgpt", status="done", text="ok", resume_of="nope")


# ---------- version 5 to version 6 ----------

ROWS = [
    {"status": "done", "agent": "claude", "checker": "chatgpt", "check_state": "passed"},
    {"status": "failed", "mode": "relay", "preset": "research-build", "jev_status": "not_asked", "failed_stage": 2,
     "result": "relay failed at stage 2 (build by claude): claude exited 1: "},
    {"status": "cancelled", "result": None},
]
CALLS = [
    {"call_id": "sr-v5-1", "task_id": "sr-v5-1", "kind": "do", "agent": "claude", "status": "done",
     "sent_at": "2026-10-15T17:00:00+00:00", "text": "an answer"},
    {"call_id": "sr-v5-2-s2", "task_id": "sr-v5-2", "kind": "stage", "agent": "claude", "status": "failed",
     "sent_at": "2026-10-15T17:01:00+00:00", "text": "claude exited 1: ", "stage": 2, "role": "build"},
]


def _snapshot_v5(path):
    c = sqlite3.connect(path)
    rows = c.execute(f"SELECT rowid, {', '.join(log.V5_COLUMNS)} FROM tasks ORDER BY rowid").fetchall()
    calls = c.execute(f"SELECT rowid, {', '.join(log.V5_CALL_COLUMNS)} FROM calls ORDER BY rowid").fetchall()
    c.close()
    return rows, calls


def test_upgrade_adds_the_resume_columns_to_a_version_5_log_and_keeps_every_row(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    make_v5_log(db, ROWS, CALLS)
    before_hash, before = sha256(db), _snapshot_v5(db)
    done = log.migrate(db, backups, now=T0)
    assert (done["job"], done["from"], done["rows"], done["highest"], done["calls"]) == ("upgrade", 5, 3, 3, 2)
    assert done["added"] == log.UPGRADES[5]["added"] == ("reason_code, resume_of, search and fallback_of columns added to calls; "
                                                  "parent and split_plan columns added to tasks; slots and web columns added to tasks"
                                                  + "; project and handoff columns added to tasks; context column added to calls; chat and memory columns added to tasks; memory column added to calls; served column added to calls; reason_code column added to tasks; round_file column added to calls; pid, run_started_at and answered_by columns added to tasks; skill_source set to owner where it named the one who labeled the task")
    assert done["backup"] == backups / BACKUP_V5 and before_hash == done["sha256"] and done["backup_check"]["content"] == "same"  # brief 22: checked by content
    assert stat.S_IMODE((backups / BACKUP_V5).stat().st_mode) == 0o600
    c = sqlite3.connect(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 16
    assert _columns(c, "calls")[-8:] == ["reason_code", "resume_of", "search", "fallback_of", "context", "memory", "served", "round_file"]
    assert c.execute("SELECT COUNT(*) FROM calls WHERE reason_code IS NOT NULL OR resume_of IS NOT NULL").fetchone()[0] == 0
    c.close()
    assert _snapshot_v5(db) == before, "rowids and every version 5 column, tasks and calls, are unchanged"
    conn = log.init_db(db)
    assert [r["n"] for r in log.recent_tasks(conn)] == [3, 2, 1]
    conn.close()


def test_a_version_4_log_lands_on_version_6_in_one_go(tmp_path):
    from tests.helpers import make_v4_log
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    make_v4_log(db)
    log.migrate(db, backups, now=T0)
    c = sqlite3.connect(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 16
    assert _columns(c, "calls")[-10:] == ["stage", "role", "reason_code", "resume_of", "search", "fallback_of", "context", "memory", "served", "round_file"]
    c.close()


def test_init_db_refuses_a_version_5_log_and_names_the_upgrade(tmp_path):
    db = tmp_path / "router.db"
    make_v5_log(db)
    with pytest.raises(log.VersionError, match=r"version 5 log.*sr migrate.*version 16 \(reason_code, resume_of, search"):
        log.init_db(db)
    assert sqlite3.connect(db).execute("PRAGMA user_version").fetchone()[0] == 5


def test_the_version_5_upgrade_refuses_while_a_task_is_open(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    make_v5_log(db, [{}, {"status": "queued", "result": None}])
    before = sha256(db)
    with pytest.raises(log.MigrateRefused, match="queued or sent"):
        log.migrate(db, backups, now=T0)
    assert sha256(db) == before and not backups.exists()


def test_cmd_migrate_prints_the_version_5_upgrade(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    make_v5_log(db, ROWS, CALLS)
    lines = []
    assert cli.cmd_migrate(db_path=db, backups_dir=backups, now=T0, out=lines.append) == 0
    out = "\n".join(lines)
    assert "version 5, 3 rows (highest #3)" in out and "now version 16" in out and BACKUP_V5 in out
    assert "2 calls" in out
