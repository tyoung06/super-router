"""The version 5 log (build brief 5, relay): `mode`, `preset` and `failed_stage` on a task,
`stage` and `role` on a call, the `stage` and `reask` call kinds, Jev's `not_asked` status,
and `sr migrate`'s upgrade from version 4."""
import sqlite3
import stat
from datetime import datetime, timezone

import pytest

from router import __main__ as cli
from router import log
from tests.helpers import ALL_AGENTS, JEV_OK, add_row, make_v4_log, sha256

T0 = datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc)
NOT_ASKED = {"status": "not_asked", "tokens": 0}
BACKUP_V4 = "router-v4-2026-10-15.db"


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _columns(conn, table):
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]


# ---------- the tables ----------

def test_a_new_log_has_the_relay_columns_and_version_5(tmp_path):
    c = log.init_db(tmp_path / "router.db")
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 16
    assert _columns(c, "tasks")[-17:] == ["check_note", "files", "mode", "preset", "failed_stage", "parent", "split_plan", "slots", "web", "project", "handoff", "chat", "memory", "reason_code", "pid", "run_started_at", "answered_by"]
    assert _columns(c, "calls")[-10:] == ["stage", "role", "reason_code", "resume_of", "search", "fallback_of", "context", "memory", "served", "round_file"]
    assert log.V4_COLUMNS == log.V3_COLUMNS + ("files",)
    assert log.V4_CALL_COLUMNS == ("call_id", "task_id", "kind", "agent", "status", "sent_at", "finished_at",
                                   "run_uuid", "text", "verdict", "url")
    c.close()


def test_the_lists_grew_by_the_relay_values_only():
    assert log.MODES == ("route", "relay", "split", "piece")
    # brief 24 (decision 13) adds not_set_up: no JEV_API_KEY, so Jev isn't called (code-checked; no migration)
    assert log.JEV_STATUSES == ("ok", "below_floor", "none_of_these", "error", "over_cap", "not_asked", "not_set_up")
    assert log.CALL_KINDS == ("do", "check", "fix", "recheck", "stage", "reask")
    assert log.STAGE_KINDS == ("stage", "reask")
    assert log.MAX_STAGES == 4
    assert log.STATUSES == ("queued", "sent", "done", "failed", "timed_out", "cancelled", "returned")


# ---------- the task row ----------

def test_a_route_task_is_mode_route_with_no_preset_by_default(conn):
    add_row(conn, "sr-1")
    row = log.get_task(conn, "sr-1")
    assert (row["mode"], row["preset"], row["failed_stage"]) == ("route", None, None)


def test_a_relay_task_carries_its_preset_and_jev_not_asked(conn):
    log.add_task(conn, "sr-r", "research then build", "cli", NOT_ASKED, mode="relay", preset="research-build")
    row = log.get_task(conn, "sr-r")
    assert (row["mode"], row["preset"], row["jev_status"], row["jev_tokens"], row["jev_label"]) == (
        "relay", "research-build", "not_asked", 0, None)


def test_a_relay_task_needs_a_preset_and_route_never_has_one(conn):
    with pytest.raises(ValueError, match="preset"):
        log.add_task(conn, "sr-r", "t", "cli", NOT_ASKED, mode="relay")
    with pytest.raises(ValueError, match="preset"):
        log.add_task(conn, "sr-r", "t", "cli", JEV_OK, mode="route", preset="research-build")
    with pytest.raises(ValueError, match="mode"):
        log.add_task(conn, "sr-r", "t", "cli", JEV_OK, mode="chain")


def test_not_asked_belongs_to_relay_only_and_relay_never_asks_jev(conn):
    with pytest.raises(ValueError, match="not_asked"):
        log.add_task(conn, "sr-1", "t", "cli", NOT_ASKED)
    with pytest.raises(ValueError, match="not_asked"):
        log.add_task(conn, "sr-r", "t", "cli", JEV_OK, mode="relay", preset="research-build")


def test_set_route_accepts_the_relay_reason_and_the_last_agent_and_checker(conn):
    log.add_task(conn, "sr-r", "t", "cli", NOT_ASKED, mode="relay", preset="research-build")
    log.set_route(conn, "sr-r", agents=ALL_AGENTS, agent="claude", route_reason="relay", checker="chatgpt",
                  check_state="pending")
    row = log.get_task(conn, "sr-r")
    assert (row["agent"], row["checker"], row["route_reason"], row["skill"], row["check_state"]) == (
        "claude", "chatgpt", "relay", None, "pending")


def test_set_failed_can_record_the_failing_stage(conn):
    log.add_task(conn, "sr-r", "t", "cli", NOT_ASKED, mode="relay", preset="research-build")
    log.set_route(conn, "sr-r", agents=ALL_AGENTS, agent="claude", route_reason="relay", checker="chatgpt",
                  check_state="pending")
    log.set_failed(conn, "sr-r", "relay failed at stage 1 (research by grok): webhook returned HTTP 500", failed_stage=1)
    row = log.get_task(conn, "sr-r")
    assert (row["status"], row["failed_stage"]) == ("failed", 1) and "stage 1" in row["result"]
    add_row(conn, "sr-1")
    log.set_failed(conn, "sr-1", "claude exited 1")
    assert log.get_task(conn, "sr-1")["failed_stage"] is None


def test_failed_stage_is_checked_in_code(conn):
    log.add_task(conn, "sr-r", "t", "cli", NOT_ASKED, mode="relay", preset="research-build")
    for bad in (0, 5, "1", 1.5):
        with pytest.raises(ValueError, match="stage"):
            log.set_failed(conn, "sr-r", "x", failed_stage=bad)
    assert log.get_task(conn, "sr-r")["status"] == "queued"


# ---------- the call row ----------

def test_a_stage_call_carries_its_stage_and_role(conn):
    log.add_task(conn, "sr-r", "t", "cli", NOT_ASKED, mode="relay", preset="research-build")
    log.add_call(conn, "sr-r-s1", "sr-r", "stage", "grok", stage=1, role="research", run_uuid="u")
    log.add_call(conn, "sr-r-s1r", "sr-r", "reask", "grok", stage=1, role="research", run_uuid="u2")
    log.add_call(conn, "sr-r-s2", "sr-r", "stage", "claude", status="done", text="built", stage=2, role="build")
    calls = log.calls_for(conn, "sr-r")
    assert [(c["kind"], c["stage"], c["role"], c["status"]) for c in calls] == [
        ("stage", 1, "research", "sent"), ("reask", 1, "research", "sent"), ("stage", 2, "build", "done")]


def test_stage_and_role_are_checked_in_code(conn):
    log.add_task(conn, "sr-r", "t", "cli", NOT_ASKED, mode="relay", preset="research-build")
    add_row(conn, "sr-1")
    with pytest.raises(ValueError, match="stage"):
        log.add_call(conn, "sr-r-s1", "sr-r", "stage", "grok", role="research")  # no stage number
    with pytest.raises(ValueError, match="role"):
        log.add_call(conn, "sr-r-s1", "sr-r", "stage", "grok", stage=1)  # no role
    with pytest.raises(ValueError, match="stage"):
        log.add_call(conn, "sr-r-s1", "sr-r", "stage", "grok", stage=5, role="research")  # past the cap
    with pytest.raises(ValueError, match="stage"):
        log.add_call(conn, "sr-r-s1", "sr-r", "stage", "grok", stage="1", role="research")
    with pytest.raises(ValueError, match="role"):
        log.add_call(conn, "sr-r-s1", "sr-r", "stage", "grok", stage=1, role="Re search")
    with pytest.raises(ValueError, match="stage"):
        log.add_call(conn, "sr-1-c1", "sr-1", "check", "claude", stage=1, role="research")  # not a stage call
    assert log.calls_for(conn, "sr-r") == [] and log.calls_for(conn, "sr-1") == []


def test_a_check_call_on_a_relay_task_has_no_stage(conn):
    log.add_task(conn, "sr-r", "t", "cli", NOT_ASKED, mode="relay", preset="research-build")
    log.add_call(conn, "sr-r-c1", "sr-r", "check", "chatgpt", status="done", text="PASS", verdict="PASS")
    call = log.get_call(conn, "sr-r-c1")
    assert (call["stage"], call["role"]) == (None, None)


def test_open_grok_calls_and_timeouts_see_stage_calls(conn):
    log.add_task(conn, "sr-r", "t", "cli", NOT_ASKED, mode="relay", preset="research-build")
    log.set_route(conn, "sr-r", agents=ALL_AGENTS, agent="claude", route_reason="relay", checker="chatgpt",
                  check_state="pending")
    log.add_call(conn, "sr-r-s1", "sr-r", "stage", "grok", stage=1, role="research", run_uuid="u", now=T0)
    log.set_open_status(conn, "sr-r", "sent")
    assert log.open_grok_calls(conn) == ["sr-r-s1"]
    late = T0.replace(hour=21)
    assert log.mark_timeouts(conn, now=late, minutes=30) == ["sr-r-s1"]
    assert log.get_call(conn, "sr-r-s1")["status"] == "timed_out"
    assert log.get_task(conn, "sr-r")["status"] == "sent", "a timed-out stage call is left to the relay runner"


# ---------- version 4 to version 5 ----------

def _snapshot_v4(path):
    c = sqlite3.connect(path)
    rows = c.execute(f"SELECT rowid, {', '.join(log.V4_COLUMNS)} FROM tasks ORDER BY rowid").fetchall()
    calls = c.execute(f"SELECT rowid, {', '.join(log.V4_CALL_COLUMNS)} FROM calls ORDER BY rowid").fetchall()
    c.close()
    return rows, calls


ROWS = [
    {},
    {"agent": "claude", "route_reason": "best", "skill": "quick_answer", "checker": None, "check_state": "not_needed",
     "sent_at": None, "run_uuid": None},
    {"status": "returned", "agent": None, "route_reason": "returned: skill not routed in version 2", "checker": None,
     "check_state": None, "result": None, "sent_at": None, "run_uuid": None},
    {"status": "cancelled", "result": None},
    {"files": '[{"name": "a.png", "type": "image/png", "size": 10}]'},
]


def test_upgrade_adds_the_relay_columns_to_a_version_4_log_and_keeps_every_row(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    make_v4_log(db, ROWS)
    c = sqlite3.connect(db)
    c.execute("INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at, text, verdict)"
              " VALUES ('sr-v4-1-c1', 'sr-v4-1', 'check', 'claude', 'done', '2026-10-13T16:47:00+00:00', 'PASS', 'PASS')")
    c.execute("INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at, run_uuid)"
              " VALUES ('sr-v4-1', 'sr-v4-1', 'do', 'grok', 'done', '2026-10-13T16:46:31+00:00', 'uuid-old')")
    c.commit(); c.close()
    before_hash, before = sha256(db), _snapshot_v4(db)
    done = log.migrate(db, backups, now=T0)
    assert (done["job"], done["from"], done["rows"], done["highest"], done["calls"]) == ("upgrade", 4, 5, 5, 2)
    assert done["added"] == log.UPGRADES[4]["added"]
    assert done["backup"] == backups / BACKUP_V4 and before_hash == done["sha256"] and done["backup_check"]["content"] == "same"  # brief 22: checked by content
    assert stat.S_IMODE((backups / BACKUP_V4).stat().st_mode) == 0o600
    c = sqlite3.connect(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 16
    assert [r[1] for r in c.execute("PRAGMA table_info(tasks)")][-15:] == ["mode", "preset", "failed_stage", "parent", "split_plan", "slots", "web", "project", "handoff", "chat", "memory", "reason_code", "pid", "run_started_at", "answered_by"]
    assert [r[1] for r in c.execute("PRAGMA table_info(calls)")][-10:] == ["stage", "role", "reason_code", "resume_of", "search", "fallback_of", "context", "memory", "served", "round_file"]
    assert c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 5
    assert c.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 2
    assert c.execute("SELECT DISTINCT mode FROM tasks").fetchall() == [("route",)]
    assert c.execute("SELECT COUNT(*) FROM tasks WHERE preset IS NOT NULL OR failed_stage IS NOT NULL").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM calls WHERE stage IS NOT NULL OR role IS NOT NULL").fetchone()[0] == 0
    c.close()
    assert _snapshot_v4(db) == before, "rowids and every version 4 column, tasks and calls, are unchanged"
    conn = log.init_db(db)
    assert [r["n"] for r in log.recent_tasks(conn)] == [5, 4, 3, 2, 1]
    assert log.files_of(log.get_task(conn, "sr-v4-5")) == [{"name": "a.png", "type": "image/png", "size": 10}]
    conn.close()


def test_init_db_refuses_a_version_4_log_and_names_the_upgrade(tmp_path):
    db = tmp_path / "router.db"
    make_v4_log(db)
    with pytest.raises(log.VersionError, match=r"version 4 log.*sr migrate.*version 16.*mode, preset"):
        log.init_db(db)
    assert sqlite3.connect(db).execute("PRAGMA user_version").fetchone()[0] == 4


def test_the_upgrade_refuses_while_a_task_is_open(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    make_v4_log(db, [{}, {"status": "sent", "result": None}])
    before = sha256(db)
    with pytest.raises(log.MigrateRefused, match="queued or sent"):
        log.migrate(db, backups, now=T0)
    assert sha256(db) == before and not backups.exists()


def test_cmd_migrate_prints_the_version_4_upgrade(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    make_v4_log(db, ROWS)
    lines = []
    assert cli.cmd_migrate(db_path=db, backups_dir=backups, now=T0, out=lines.append) == 0
    out = "\n".join(lines)
    assert "version 4, 5 rows (highest #5)" in out and f"Upgraded in place: {log.UPGRADES[4]['added']}, now version 16." in out
    assert BACKUP_V4 in out and "every version 4 column unchanged" in out and "0 calls" in out


def test_a_second_migrate_of_a_version_5_log_is_refused(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    make_v4_log(db)
    log.migrate(db, backups, now=T0)
    with pytest.raises(log.MigrateRefused, match="already a version 16"):
        log.migrate(db, backups, now=T0)


def test_a_failed_recheck_of_the_calls_names_the_backup_and_stops(tmp_path, monkeypatch):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    make_v4_log(db, ROWS)
    real = log._content_hash
    seen = []

    def hash_that_changes(*args, **kwargs):
        seen.append(1)
        return real(*args, **kwargs) if len(seen) <= 2 else "something else"  # brief 22: before, the backup's check, after

    monkeypatch.setattr(log, "_content_hash", hash_that_changes)
    with pytest.raises(log.MigrateFailed) as err:
        log.migrate(db, backups, now=T0)
    assert str(backups / BACKUP_V4) in str(err.value) and (backups / BACKUP_V4).exists()


@pytest.mark.parametrize("command", [["log"], ["show"], ["cancel"], ["check"], ["route", "hi"], ["relay", "--list"]])
def test_other_commands_refuse_a_version_4_log_and_leave_it_alone(monkeypatch, capsys, command):
    monkeypatch.setattr(cli.safety, "prepare_workspace", lambda *a, **k: None)
    make_v4_log(cli.DB_PATH, ROWS[:1])
    before = sha256(cli.DB_PATH)
    assert cli.main(command, platform="darwin") == 2
    assert "sr migrate" in capsys.readouterr().out
    assert sha256(cli.DB_PATH) == before
