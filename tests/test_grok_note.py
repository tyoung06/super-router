"""Build brief 21, C2 (decision 5; rules v2.30, Status and JSON, Grok timeout). A task or piece whose Grok call has been out
N minutes (`grok_timeout_minutes`, config/settings.json, 5) has `check_note` read `waiting: grok, <m> min`; from 2N,
`overdue: grok, <m> min`. Written only where `check_note` is empty or already a Grok note (the owner's C6), by the commands
that step a task (the wait step, and each poll of a wait); the return clears it. `waiting_on` reads `grok` either way.
It changes nothing else: no retry, no cancel, no second send. A JSON read never writes it. Fakes only."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from router import __main__ as cli
from router import log, settings
from tests.helpers import fake_label
from tests.test_json_actions import World, jev
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_relay import GOOD_NOTE, Chat, RelayHook

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
# Brief 24 (decision 6): at 2N the router takes a Grok call over; an override never is, so its call keeps waiting and the
# note is all that changes. The tests that reach 2N route one.
OVERRIDE = "@grok what are gardeners on X saying about trays"


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    w = World(monkeypatch, tmp_path, capsys)
    w.label, w.hook, w.chatgpt = fake_label(jev("x_social_pulse")), Webhook(), Chat("PASS")
    return w


def _ago(minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _backdate(minutes, n=1):
    """The task's Grok call, sent `minutes` ago."""
    conn = log.init_db(cli.DB_PATH)
    try:
        task = log.task_by_number(conn, n)
        call = [c for c in log.calls_for(conn, task["task_id"]) if c["agent"] == "grok" and c["status"] == "sent"][-1]
        conn.execute("UPDATE calls SET sent_at = ? WHERE call_id = ?", (_ago(minutes), call["call_id"]))
        conn.commit()
    finally:
        conn.close()


def _row(n=1):
    conn = log.init_db(cli.DB_PATH)
    try:
        return log.task_by_number(conn, n)
    finally:
        conn.close()


# ---------- the note's text ----------

@pytest.mark.parametrize("minutes, note", [(0, None), (4.9, None), (5, "waiting: grok, 5 min"), (7.9, "waiting: grok, 7 min"),
                                           (9.99, "waiting: grok, 9 min"), (10, "overdue: grok, 10 min"),
                                           (27, "overdue: grok, 27 min")])
def test_the_note_from_n_and_from_2n(minutes, note):
    sent = (NOW - timedelta(minutes=minutes)).isoformat()
    assert log.grok_note(sent, NOW, 5) == note


def test_no_n_no_note():
    sent = (NOW - timedelta(minutes=60)).isoformat()
    assert log.grok_note(sent, NOW, None) is None and log.grok_note(sent, NOW, 0) is None


def test_n_is_settings_five_and_a_local_file_can_change_it(tmp_path, monkeypatch):
    assert settings.grok_timeout_minutes() == 5
    settings.LOCAL_PATH.write_text(json.dumps({"grok_timeout_minutes": 2, "grok_inbox_repo": "owner/inbox"}))  # brief 24: a full setup keeps its inbox
    assert settings.grok_timeout_minutes() == 2


# ---------- where it is written (C6) ----------

def _open(conn, note=None, status="sent"):
    log.add_task(conn, "sr-1", "t", "cli", jev("x_social_pulse"))
    log.set_route(conn, "sr-1", agents=("grok", "chatgpt"), agent="grok", route_reason="best", checker="chatgpt",
                  check_state="pending")
    if status == "sent":
        log.set_sent(conn, "sr-1", "u")
    if note is not None:
        conn.execute("UPDATE tasks SET check_note = ? WHERE task_id = 'sr-1'", (note,))
        conn.commit()


def test_written_on_an_empty_note_and_over_a_grok_note_only():
    conn = log.init_db(":memory:")
    _open(conn)
    assert log.set_grok_note(conn, "sr-1", "waiting: grok, 5 min") is True
    assert log.set_grok_note(conn, "sr-1", "waiting: grok, 5 min") is False  # unchanged: no write
    assert log.set_grok_note(conn, "sr-1", "overdue: grok, 10 min") is True
    assert log.get_task(conn, "sr-1")["check_note"] == "overdue: grok, 10 min"
    assert log.set_grok_note(conn, "sr-1", None) is True and log.get_task(conn, "sr-1")["check_note"] is None


def test_never_over_a_real_note_and_never_on_an_ended_task():
    conn = log.init_db(":memory:")
    _open(conn, note="checker chatgpt isn't live yet")
    assert log.set_grok_note(conn, "sr-1", "waiting: grok, 5 min") is False
    assert log.set_grok_note(conn, "sr-1", None) is False  # clearing never touches a real note
    assert log.get_task(conn, "sr-1")["check_note"] == "checker chatgpt isn't live yet"
    conn = log.init_db(":memory:")
    _open(conn)
    log.set_cancelled(conn, "sr-1")
    assert log.set_grok_note(conn, "sr-1", "waiting: grok, 5 min") is False


# ---------- through the router ----------

def test_sr_check_writes_the_note_says_it_and_the_return_clears_it(world):
    world.run("route", OVERRIDE, "--no-wait")
    assert _row()["check_note"] is None and len(world.hook.sent) == 1
    _backdate(6)
    code, out, err = world.run("check")
    assert _row()["check_note"] == "waiting: grok, 6 min" and "(waiting: grok, 6 min)" in out
    _backdate(11)
    code, out, err = world.run("check")
    row = _row()
    assert row["check_note"] == "overdue: grok, 11 min" and "(overdue: grok, 11 min)" in out
    assert row["status"] == "sent" and len(world.hook.sent) == 1  # nothing else changes: no retry, no second send
    world.hook.bodies["do"] = "Gardeners like rubber trays."
    world.run("check")
    row = _row()
    assert row["status"] == "done" and row["check_note"] is None and row["check_state"] == "passed"


def test_the_json_carries_it_and_waiting_on_reads_grok_either_way(world):
    world.run("route", OVERRIDE, "--no-wait")
    doc = json.loads(world.run("show", "1", "--json")[1])
    assert (doc["waiting_on"], doc["check_note"]) == ("grok", None)
    _backdate(12)
    found = world.json("check")
    assert "(overdue: grok, 12 min)" in found["message"] and found["tasks"][0]["waiting_on"] == "grok"
    doc = json.loads(world.run("show", "1", "--json")[1])
    assert (doc["waiting_on"], doc["check_note"]) == ("grok", "overdue: grok, 12 min")
    status = json.loads(world.run("status", "--json")[1])
    assert [(t["n"], t["check_note"]) for t in status["open_tasks"]] == [(1, "overdue: grok, 12 min")]


def test_a_json_read_never_writes_it(world):
    world.run("route", "what are gardeners on X saying about trays", "--no-wait")
    _backdate(8)
    for argv in (("status", "--json"), ("show", "1", "--json"), ("log", "--json"), ("show", "1"), ("log",)):
        world.run(*argv)
    assert _row()["check_note"] is None


def test_a_real_note_on_an_open_task_stays(world):
    world.run("route", "what are gardeners on X saying about trays", "--no-wait")
    conn = log.init_db(cli.DB_PATH)
    conn.execute("UPDATE tasks SET check_note = 'a note the owner must see' WHERE rowid = 1")
    conn.commit()
    conn.close()
    _backdate(7)
    code, out, err = world.run("check")
    assert _row()["check_note"] == "a note the owner must see" and "waiting: grok" not in out


def test_a_relay_stage_out_with_grok_gets_the_note(world):
    world.worker, world.hook = Scripted("A built result."), RelayHook()
    world.run("relay", "research-build", "trays", "--no-wait")
    _backdate(5)
    world.run("check")
    assert _row()["check_note"] == "waiting: grok, 5 min"
    world.hook.bodies["s1"] = GOOD_NOTE
    world.run("check")
    assert _row()["check_note"] is None


def test_the_setting_moves_the_note(world):
    settings.LOCAL_PATH.write_text(json.dumps({"grok_timeout_minutes": 2, "grok_inbox_repo": "owner/inbox"}))  # brief 24: a full setup keeps its inbox
    world.run("route", OVERRIDE, "--no-wait")
    _backdate(3)
    world.run("check")
    assert _row()["check_note"] == "waiting: grok, 3 min"
    _backdate(4)
    world.run("check")
    assert _row()["check_note"] == "overdue: grok, 4 min"


def test_a_wait_in_a_terminal_writes_it_on_each_poll(tmp_path):
    conn = log.init_db(tmp_path / "router.db")
    _open(conn, status="queued")
    log.set_sent(conn, "sr-1", "u", now=NOW - timedelta(minutes=6))  # logs the do call under the task's id
    clock, seen = Clock(), []
    issues = [[], [{"number": 7, "title": "sr-1", "body": "An answer.", "url": "https://github.com/x/y/issues/7"}]]

    def sleep(seconds):
        seen.append(log.get_task(conn, "sr-1")["check_note"])
        clock.sleep(seconds)
    deps = SimpleNamespace(fetch=lambda: issues.pop(0), close=lambda n: None, clock=clock, sleep=sleep, now=NOW)
    code = cli._wait_for_call(conn, "sr-1", log.get_call(conn, "sr-1"), deps, (), lambda line: None)
    assert code is None and seen == ["waiting: grok, 6 min"]
    assert log.get_task(conn, "sr-1")["check_note"] is None  # the return cleared it
