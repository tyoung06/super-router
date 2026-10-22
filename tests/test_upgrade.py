"""`sr migrate`'s second job: a version 2 log is upgraded in place to version 3, after a backup copy."""
import sqlite3
import stat
from datetime import datetime, timezone

import pytest

from router import __main__ as cli
from router import log
from tests.helpers import make_v1_log, make_v2_log, make_v3_log, sha256

T0 = datetime(2026, 10, 13, 20, 0, tzinfo=timezone.utc)
BACKUP = "router-v2-2026-10-13.db"
ROWS = [
    {},
    {"agent": "claude", "route_reason": "best", "skill": "quick_answer", "checker": None, "check_state": "not_needed",
     "sent_at": None, "run_uuid": None},
    {"status": "returned", "agent": None, "route_reason": "returned: skill not routed in version 2", "checker": None,
     "check_state": None, "result": None, "sent_at": None, "run_uuid": None},
    {"status": "cancelled", "result": None},
]


def _paths(tmp_path):
    return tmp_path / "router.db", tmp_path / "backups"


def _snapshot(path):
    """Every row's rowid and version 2 columns, in rowid order."""
    c = sqlite3.connect(path)
    rows = c.execute(f"SELECT rowid, {', '.join(log.V2_COLUMNS)} FROM tasks ORDER BY rowid").fetchall()
    c.close()
    return rows


def test_upgrade_adds_calls_and_check_note_and_keeps_every_row(tmp_path):
    db, backups = _paths(tmp_path)
    make_v2_log(db, ROWS)
    before_hash, before_rows = sha256(db), _snapshot(db)
    done = log.migrate(db, backups, now=T0)
    backup = backups / BACKUP
    assert (done["job"], done["rows"], done["backup"], done["sha256"]) == ("upgrade", 4, backup, before_hash)
    assert done["backup_check"]["content"] == "same" and _snapshot(backup) == before_rows  # brief 22: the backup API copy, checked by content
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    c = log.init_db(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 16
    assert [r["name"] for r in c.execute("PRAGMA table_info(tasks)")][-17:] == ["check_note", "files", "mode", "preset", "failed_stage",
                                                                                   "parent", "split_plan", "slots", "web", "project", "handoff", "chat", "memory", "reason_code",
                                                                                   "pid", "run_started_at", "answered_by"]
    assert c.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 0
    assert _snapshot(db) == before_rows, "rowids and every version 2 column are unchanged"
    assert [r["n"] for r in log.recent_tasks(c)] == [4, 3, 2, 1]
    assert all(r["check_note"] is None for r in log.recent_tasks(c))
    assert log.calls_for(c, "sr-v2-1") == []
    c.close()


def test_the_backup_name_uses_the_utc_date(tmp_path):
    db, backups = _paths(tmp_path)
    make_v2_log(db)
    late = datetime(2026, 10, 14, 2, 30, tzinfo=timezone.utc)  # still 13 Oct in a zone behind UTC
    assert log.migrate(db, backups, now=late)["backup"].name == "router-v2-2026-10-14.db"


@pytest.mark.parametrize("open_status", ["queued", "sent"])
def test_upgrade_refuses_while_a_task_is_open(tmp_path, open_status):
    db, backups = _paths(tmp_path)
    make_v2_log(db, [{}, {"status": open_status, "result": None}])
    before = sha256(db)
    with pytest.raises(log.MigrateRefused, match="queued or sent"):
        log.migrate(db, backups, now=T0)
    assert sha256(db) == before and not backups.exists()


def test_upgrade_refuses_when_the_backup_name_is_taken(tmp_path):
    db, backups = _paths(tmp_path)
    make_v2_log(db)
    backups.mkdir()
    (backups / BACKUP).write_bytes(b"an older backup")
    before = sha256(db)
    with pytest.raises(log.MigrateRefused, match="already exists"):
        log.migrate(db, backups, now=T0)
    assert sha256(db) == before
    assert (backups / BACKUP).read_bytes() == b"an older backup"
    c = sqlite3.connect(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 2
    c.close()


def test_upgrade_refuses_a_current_version_log(tmp_path):
    db, backups = _paths(tmp_path)
    log.init_db(db).close()
    with pytest.raises(log.MigrateRefused, match="already a version 16"):
        log.migrate(db, backups, now=T0)
    assert not backups.exists()


def test_a_version_1_log_still_gets_the_move_job(tmp_path):
    db, backups = _paths(tmp_path)
    make_v1_log(db, ["done"])
    done = log.migrate(db, backups, now=T0)
    assert done["job"] == "move" and done["backup"].name == "router-v1-final-2026-10-13.db"
    c = log.init_db(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION and log.recent_tasks(c) == []
    c.close()


def test_the_upgrade_job_itself_refuses_a_version_1_log(tmp_path):
    db, backups = _paths(tmp_path)
    make_v1_log(db, ["done"])
    before = sha256(db)
    with pytest.raises(log.MigrateRefused, match="not a version 2"):
        log.upgrade_v2_to_v3(db, backups, now=T0)
    assert sha256(db) == before and not backups.exists()


def test_upgrade_refuses_while_a_save_is_half_finished(tmp_path):
    db, backups = _paths(tmp_path)
    make_v2_log(db)
    (tmp_path / "router.db-journal").write_bytes(b"")
    with pytest.raises(log.MigrateRefused, match="journal"):
        log.migrate(db, backups, now=T0)
    assert not backups.exists()


def test_a_failed_recheck_names_the_backup_and_stops(tmp_path, monkeypatch):
    db, backups = _paths(tmp_path)
    make_v2_log(db, ROWS)
    real = log._content_hash
    seen = []

    def hash_that_changes(*args, **kwargs):
        seen.append(1)
        return real(*args, **kwargs) if len(seen) <= 2 else "something else"  # brief 22: before, the backup's check, after

    monkeypatch.setattr(log, "_content_hash", hash_that_changes)
    with pytest.raises(log.MigrateFailed) as err:
        log.migrate(db, backups, now=T0)
    assert str(backups / BACKUP) in str(err.value)
    assert sha256(backups / BACKUP) != "" and (backups / BACKUP).exists()


# ---------- the command ----------

def test_cmd_migrate_prints_the_upgrade(tmp_path):
    db, backups = _paths(tmp_path)
    make_v2_log(db, ROWS)
    before = sha256(db)
    lines = []
    assert cli.cmd_migrate(db_path=db, backups_dir=backups, now=T0, out=lines.append) == 0
    out = "\n".join(lines)
    assert "version 2" in out and "4 rows" in out and "integrity ok" in out
    assert f"backups/{BACKUP}" in out and before in out
    assert "version 2" in out and "now version 16" in out and "calls" in out and "check_note" in out and "files" in out and "#4" in out


def test_main_migrate_upgrades_a_version_2_log(capsys):
    make_v2_log(cli.DB_PATH, ROWS[:1])
    assert cli.main(["migrate"], platform="darwin") == 0
    assert any(p.name.startswith("router-v2-") for p in cli.BACKUPS_DIR.iterdir())
    assert "now version 16" in capsys.readouterr().out
    c = log.init_db(cli.DB_PATH)
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 16
    c.close()


@pytest.mark.parametrize("command", [["log"], ["show"], ["cancel"], ["check"], ["route", "hi"]])
def test_other_commands_refuse_a_version_2_log_and_leave_it_alone(monkeypatch, capsys, command):
    monkeypatch.setattr(cli.safety, "prepare_workspace", lambda *a, **k: None)
    make_v2_log(cli.DB_PATH, ROWS[:1])
    before = sha256(cli.DB_PATH)
    assert cli.main(command, platform="darwin") == 2
    assert "sr migrate" in capsys.readouterr().out
    assert sha256(cli.DB_PATH) == before


# ---------- version 3 to version 4: the files column (build brief 4) ----------

BACKUP_V3 = "router-v3-2026-10-13.db"


def _snapshot_v3(path):
    c = sqlite3.connect(path)
    rows = c.execute(f"SELECT rowid, {', '.join(log.V3_COLUMNS)} FROM tasks ORDER BY rowid").fetchall()
    calls = c.execute(f"SELECT rowid, {', '.join(log.V4_CALL_COLUMNS)} FROM calls ORDER BY rowid").fetchall()
    c.close()
    return rows, calls


def test_upgrade_adds_the_files_column_to_a_version_3_log_and_keeps_every_row(tmp_path):
    db, backups = _paths(tmp_path)
    make_v3_log(db, ROWS)
    c = sqlite3.connect(db)
    c.execute("INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at, text, verdict)"
              " VALUES ('sr-v3-1-c1', 'sr-v3-1', 'check', 'claude', 'done', '2026-10-13T16:47:00+00:00', 'PASS', 'PASS')")
    c.commit(); c.close()
    before_hash, before = sha256(db), _snapshot_v3(db)
    done = log.migrate(db, backups, now=T0)
    assert (done["job"], done["from"], done["added"], done["rows"], done["highest"]) == (
        "upgrade", 3, log.UPGRADES[3]["added"], 4, 4)
    assert done["backup"] == backups / BACKUP_V3 and before_hash == done["sha256"] and done["backup_check"]["content"] == "same"  # brief 22: checked by content
    assert stat.S_IMODE((backups / BACKUP_V3).stat().st_mode) == 0o600
    c = sqlite3.connect(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 16
    assert "files" in [r[1] for r in c.execute("PRAGMA table_info(tasks)")]
    assert [r[1] for r in c.execute("PRAGMA table_info(calls)")][-10:] == ["stage", "role", "reason_code", "resume_of", "search", "fallback_of", "context", "memory", "served", "round_file"]
    c.close()
    assert _snapshot_v3(db) == before
    conn = log.init_db(db)
    assert all(log.files_of(row) == [] for row in log.recent_tasks(conn))
    conn.close()


def test_init_db_refuses_a_version_3_log_and_names_the_upgrade(tmp_path):
    db, _ = _paths(tmp_path)
    make_v3_log(db)
    with pytest.raises(log.VersionError, match=r"version 3 log.*sr migrate.*version 16 \(files, mode"):
        log.init_db(db)
    assert sqlite3.connect(db).execute("PRAGMA user_version").fetchone()[0] == 3


def test_cmd_migrate_prints_the_version_3_upgrade(tmp_path):
    db, backups = _paths(tmp_path)
    make_v3_log(db, ROWS)
    lines = []
    assert cli.cmd_migrate(db_path=db, backups_dir=backups, now=T0, out=lines.append) == 0
    out = "\n".join(lines)
    assert "version 3, 4 rows (highest #4)" in out and f"Upgraded in place: {log.UPGRADES[3]['added']}, now version 16." in out
    assert BACKUP_V3 in out and "every version 3 column unchanged" in out


def test_a_second_migrate_of_a_version_5_log_is_refused(tmp_path):
    db, backups = _paths(tmp_path)
    make_v3_log(db)
    log.migrate(db, backups, now=T0)
    with pytest.raises(log.MigrateRefused, match="already a version 16"):
        log.migrate(db, backups, now=T0)
