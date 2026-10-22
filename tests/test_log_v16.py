"""Build brief 25 (the owner's change of 21 Oct): log version 16. The stored value for a label or answer the owner gave,
`skill_source`, is `owner`. `sr migrate` copies the log into backups/ first, then sets `skill_source` to `owner` on every
row whose value is neither `jev` nor `owner` nor empty: it finds the old value by exclusion and never spells it, so the
rows here plant invented ones. Nothing else in a row moves, and the check after the upgrade proves it."""
import re
import sqlite3
from datetime import datetime, timezone

import pytest

from router import log

NOW = "2026-10-22T09:00:00+00:00"
WHEN = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)


def _v15_log(path, sources):
    """A version 15 log (the current columns; 16 adds none) holding one task per `skill_source` value."""
    conn = log.init_db(path)
    for n, source in enumerate(sources, 1):
        conn.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, skill, skill_source, "
                     "status) VALUES (?, ?, ?, 'cli', ?, 'ok', 'writing', ?, 'done')",
                     (f"sr-20261020-12000{n}-ab1{n}", NOW, NOW, f"task {n}", source))
    conn.execute("INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at) "
                 "VALUES ('sr-20261020-120001-ab11-c1', 'sr-20261020-120001-ab11', 'do', 'claude', 'done', ?)", (NOW,))
    conn.execute("PRAGMA user_version = 15")
    conn.commit()
    conn.close()


def _sources(path):
    conn = sqlite3.connect(path)
    try:
        return [r[0] for r in conn.execute("SELECT skill_source FROM tasks ORDER BY rowid")]
    finally:
        conn.close()


def test_the_version_and_the_two_stored_values():
    assert log.VERSION == 16 and log.SKILL_SOURCES == ("jev", "owner")


def test_the_old_value_is_found_by_exclusion_never_spelled():
    quoted = set(re.findall(r"'([^']*)'", log.OWNER_SOURCE))
    assert quoted <= {"owner", "jev"} and "NOT IN" in log.OWNER_SOURCE and "skill_source" in log.OWNER_SOURCE


def test_a_version_15_log_lands_on_16_with_only_the_stored_value_renamed(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _v15_log(db, ["jev", None, "a-legacy-value", "owner", "another-old-one"])
    done = log.migrate(db, backups, now=WHEN)
    assert done["job"] == "upgrade" and done["from"] == 15 and done["rows"] == 5 and done["calls"] == 1
    assert "skill_source" in done["added"] and "owner" in done["added"]
    assert _sources(db) == ["jev", None, "owner", "owner", "owner"]
    assert log.file_version(db) == 16
    assert _sources(done["backup"]) == ["jev", None, "a-legacy-value", "owner", "another-old-one"]  # the copy from before
    assert done["backup"].name == "router-v15-2026-10-22.db"


def test_a_log_with_nothing_to_rename_lands_on_16_unchanged(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _v15_log(db, ["jev", None])
    log.migrate(db, backups, now=WHEN)
    assert _sources(db) == ["jev", None] and log.file_version(db) == 16


def test_an_older_log_gets_the_rename_too():
    for version in range(2, 16):
        assert log.OWNER_SOURCE in log.UPGRADES[version]["statements"], version
        assert log.V16_ADDED in log.UPGRADES[version]["added"], version


def test_the_check_after_the_upgrade_still_catches_any_other_change(tmp_path, monkeypatch):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    _v15_log(db, ["a-legacy-value"])
    sneaky = log.UPGRADES[15]["statements"] + " UPDATE tasks SET task = 'changed';"
    monkeypatch.setitem(log.UPGRADES, 15, {**log.UPGRADES[15], "statements": sneaky})
    with pytest.raises(log.MigrateFailed, match="content hash different"):
        log.migrate(db, backups, now=WHEN)
