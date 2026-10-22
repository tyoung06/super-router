"""`sr migrate`: move the version 1 log into backups/ once, and start an empty version 2 log."""
import stat
import sqlite3
from datetime import datetime, timezone

import pytest

from router import __main__ as cli
from router import log
from tests.helpers import make_v1_log, sha256

T0 = datetime(2026, 10, 8, 20, 0, tzinfo=timezone.utc)
BACKUP_NAME = "router-v1-final-2026-10-08.db"


def _paths(tmp_path):
    return tmp_path / "router.db", tmp_path / "backups"


def _rows(path):
    c = sqlite3.connect(path)
    n = c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    c.close()
    return n


def test_migrate_moves_the_old_log_and_starts_an_empty_current_version_log(tmp_path):
    db, backups = _paths(tmp_path)
    make_v1_log(db, ["done"] * 8 + ["timed_out"])
    before = sha256(db)
    done = log.migrate(db, backups, now=T0)
    backup = backups / BACKUP_NAME
    assert (done["rows"], done["backup"], done["sha256"]) == (9, backup, before)
    assert sha256(backup) == before and _rows(backup) == 9
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600, "the backup is owner-only"
    assert done["job"] == "move"
    c = log.init_db(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION
    assert log.recent_tasks(c) == []
    c.close()


def test_the_backup_name_uses_the_utc_date(tmp_path):
    db, backups = _paths(tmp_path)
    make_v1_log(db)
    late = datetime(2026, 10, 9, 2, 30, tzinfo=timezone.utc)  # still 8 Oct in a zone behind UTC
    assert log.migrate(db, backups, now=late)["backup"].name == "router-v1-final-2026-10-09.db"


@pytest.mark.parametrize("open_status", ["queued", "sent"])
def test_migrate_refuses_while_a_task_is_open(tmp_path, open_status):
    db, backups = _paths(tmp_path)
    make_v1_log(db, ["done", open_status])
    before = sha256(db)
    with pytest.raises(log.MigrateRefused, match="queued or sent"):
        log.migrate(db, backups, now=T0)
    assert sha256(db) == before and not (backups / BACKUP_NAME).exists()


def test_migrate_refuses_when_the_backup_name_is_taken(tmp_path):
    db, backups = _paths(tmp_path)
    make_v1_log(db)
    backups.mkdir()
    (backups / BACKUP_NAME).write_bytes(b"an older backup")
    before = sha256(db)
    with pytest.raises(log.MigrateRefused, match="already exists"):
        log.migrate(db, backups, now=T0)
    assert sha256(db) == before
    assert (backups / BACKUP_NAME).read_bytes() == b"an older backup"


def test_migrate_refuses_a_current_version_log(tmp_path):
    db, backups = _paths(tmp_path)
    log.init_db(db).close()
    with pytest.raises(log.MigrateRefused, match=f"already a version {log.VERSION}"):
        log.migrate(db, backups, now=T0)
    assert not backups.exists()


def test_migrate_refuses_when_there_is_no_log(tmp_path):
    db, backups = _paths(tmp_path)
    with pytest.raises(log.MigrateRefused, match="no router.db"):
        log.migrate(db, backups, now=T0)
    assert not db.exists() and not backups.exists()


def test_migrate_refuses_a_file_that_is_not_a_log(tmp_path):
    db, backups = _paths(tmp_path)
    db.write_bytes(b"this is not a database at all, just some bytes" * 20)
    with pytest.raises(log.MigrateRefused):
        log.migrate(db, backups, now=T0)
    assert db.exists() and not backups.exists()


def test_migrate_refuses_while_a_save_is_half_finished(tmp_path):
    db, backups = _paths(tmp_path)
    make_v1_log(db)
    (tmp_path / "router.db-journal").write_bytes(b"")
    with pytest.raises(log.MigrateRefused, match="journal"):
        log.migrate(db, backups, now=T0)
    assert db.exists() and not (backups / BACKUP_NAME).exists()


# ---------- the command ----------

def test_cmd_migrate_prints_what_it_did(tmp_path):
    db, backups = _paths(tmp_path)
    make_v1_log(db, ["done", "done", "timed_out"])
    before = sha256(db)
    lines = []
    assert cli.cmd_migrate(db_path=db, backups_dir=backups, now=T0, out=lines.append) == 0
    out = "\n".join(lines)
    assert "3 rows" in out and "integrity ok" in out
    assert f"backups/{BACKUP_NAME}" in out and before in out
    assert f"version {log.VERSION}" in out and "#1" in out


def test_cmd_migrate_refusal_says_nothing_changed(tmp_path):
    db, backups = _paths(tmp_path)
    lines = []
    assert cli.cmd_migrate(db_path=db, backups_dir=backups, now=T0, out=lines.append) == 2
    assert "Nothing was changed" in "\n".join(lines)


def test_main_migrate_runs_before_the_log_is_opened(capsys):
    make_v1_log(cli.DB_PATH, ["done"])
    assert cli.main(["migrate"], platform="darwin") == 0
    assert any(p.name.startswith("router-v1-final-") for p in cli.BACKUPS_DIR.iterdir())
    assert f"version {log.VERSION}" in capsys.readouterr().out


@pytest.mark.parametrize("command", [["log"], ["show"], ["cancel"], ["check"], ["route", "hi"]])
def test_other_commands_refuse_a_version_1_log_and_leave_it_alone(monkeypatch, capsys, command):
    monkeypatch.setattr(cli.safety, "prepare_workspace", lambda *a, **k: None)
    make_v1_log(cli.DB_PATH, ["done"])
    before = sha256(cli.DB_PATH)
    assert cli.main(command, platform="darwin") == 2
    assert "sr migrate" in capsys.readouterr().out
    assert sha256(cli.DB_PATH) == before
