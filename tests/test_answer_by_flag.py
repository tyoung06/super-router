"""Build brief 22, C1 (rules v2.31, Router for the interface, "Answers without a terminal"; decision 2 and Phase 0
choice 8): `sr route "<text>" --skill <key>` labels a task with the owner's answer (`skill_source` owner) and skips Jev.
With `--answers <n>` it names the Jev floor row it answers: the text must be that row's, byte for byte; its tag and
`--web` come from that row (given again, they must match) and so do its files (`--file` is refused); that row gets
`answered_by` in the same write, leaves `waiting_on`, keeps `returned` and Jev's label. Refused before any row:
`unknown_task`, `wrong_state` (not an unanswered floor return; a piece), `already_used`, `bad_task`, `flag_refused`,
`usage`. `sr cancel <n>` on an unanswered floor row: `cancelled`, Jev's label kept. Fakes only; every value is fake."""
import json

import pytest

from router import __main__ as cli
from router import log, media, state
from tests.helpers import fake_label
from tests.test_json_actions import World, jev
from tests.test_loop import Scripted
from tests.test_relay import Chat

TEXT = "make sense of this vague thing"
LOW = {**jev("writing"), "status": "below_floor", "confidence": 0.5}


def _never(*a, **k):
    raise AssertionError("Jev must not be called on a task the owner labeled")


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    w = World(monkeypatch, tmp_path, capsys)
    monkeypatch.setattr(cli.memory, "client", lambda request, **kw: None)  # no store: a tagged task runs without a block
    return w


def _row(n):
    conn = log.init_db(cli.DB_PATH)
    try:
        return log.task_by_number(conn, n)
    finally:
        conn.close()


def _floor(world, text=TEXT, *extra):
    world.label = fake_label(LOW)
    found = world.json("route", text, *extra)
    assert (found["status"], found["waiting_on"], found["reason_code"]) == ("returned", "needs_label", "needs_label")
    return found


# ---------- --skill alone ----------

def test_skill_labels_the_task_with_the_owners_answer_and_skips_jev(world):
    world.label, world.worker, world.chatgpt = _never, Scripted("a line"), Chat("PASS")
    found = world.json("route", "write one line about trays", "--skill", "writing")
    assert (found["exit"], found["status"], found["outcome"]) == (0, "done", "passed")
    row = _row(1)
    assert (row["jev_status"], row["jev_label"], row["jev_tokens"], row["skill"], row["skill_source"], row["agent"],
            row["checker"]) == ("not_asked", None, 0, "writing", "owner", "claude", "chatgpt")
    code, out, err = world.run("route", "write two lines", "--skill", "writing")
    assert "writing (your choice) -> claude, the skill's best agent." in out


@pytest.mark.parametrize("argv, code_word", [
    (["route", "a task", "--skill", "nope"], "usage"),
    (["route", "a task", "--skill", "none"], "usage"),
    (["route", "@claude a task", "--skill", "writing"], "flag_refused"),
    (["route", "a task", "--answers", "1"], "usage"),
])
def test_skill_refusals_come_before_any_row(world, argv, code_word):
    world.label = _never
    found = world.json(*argv)
    assert (found["exit"], found["reason_code"], found["task_id"]) == (2, code_word, None)
    assert _row(1) is None


def test_skill_none_points_to_sr_cancel(world):
    world.label = _never
    code, out, err = world.run("route", "a task", "--skill", "none")
    assert code == 2 and "sr cancel" in out


def test_a_recall_label_without_a_tag_still_comes_back(world):
    world.label = _never
    found = world.json("route", "what did we decide", "--skill", "recall")
    assert (found["status"], found["reason_code"]) == ("returned", "needs_tag")


# ---------- --answers ----------

def test_answers_routes_the_floor_rows_task_and_marks_the_row_answered(world):
    _floor(world)
    world.label, world.worker, world.chatgpt = _never, Scripted("the answer"), Chat("PASS")
    found = world.json("route", TEXT, "--skill", "writing", "--answers", "1")
    assert (found["exit"], found["n"], found["status"], found["outcome"]) == (0, 2, "done", "passed")
    floor, new = _row(1), _row(2)
    assert (floor["status"], floor["answered_by"], floor["jev_label"], floor["jev_confidence"]) == (
        "returned", new["task_id"], "writing", 0.5)
    conn = log.init_db(cli.DB_PATH)
    assert state.of(floor, log.calls_for(conn, floor["task_id"])) == state.State(None, "returned")
    conn.close()
    assert (new["task"], new["skill_source"], new["jev_status"]) == (TEXT, "owner", "not_asked")
    shown = json.loads(world.run("show", "1", "--json")[1])
    assert (shown["answered_by"], shown["waiting_on"], shown["outcome"]) == (new["task_id"], None, "returned")
    code, out, err = world.run("show", "1")
    assert f"Answered by #2 {new['task_id']} (your label: writing)." in out
    code, out, err = world.run("show", "2")
    assert f"Answers #1 {floor['task_id']} (Jev was unsure)." in out


@pytest.mark.parametrize("prepare, argv, code_word", [
    ("none", ["route", TEXT, "--skill", "writing", "--answers", "9"], "unknown_task"),
    ("done", ["route", "a done task", "--skill", "writing", "--answers", "1"], "wrong_state"),
    ("floor", ["route", TEXT + " but different", "--skill", "writing", "--answers", "1"], "bad_task"),
    ("floor", ["route", TEXT, "--skill", "writing", "--answers", "1", "--chat", "other"], "flag_refused"),
    ("floor", ["route", TEXT, "--skill", "writing", "--answers", "1", "--web"], "flag_refused"),
])
def test_answers_refusals(world, prepare, argv, code_word):
    if prepare == "floor":
        _floor(world)
    elif prepare == "done":
        world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("4")
        world.json("route", "a done task")
    world.label = _never
    before = _row(1)
    found = world.json(*argv)
    assert (found["exit"], found["reason_code"]) == (2, code_word)
    assert _row(2) is None or prepare == "none"
    if before is not None:
        assert _row(1)["answered_by"] is None


def test_a_floor_row_is_answered_once(world):
    _floor(world)
    world.label, world.worker, world.chatgpt = _never, Scripted("one", "two"), Chat("PASS", "PASS")
    world.json("route", TEXT, "--skill", "writing", "--answers", "1")
    found = world.json("route", TEXT, "--skill", "writing", "--answers", "1")
    assert (found["exit"], found["reason_code"]) == (2, "already_used") and _row(3) is None


def test_answers_keeps_the_floor_rows_tag(world):
    _floor(world, TEXT, "--chat", "trays")
    world.label, world.worker, world.chatgpt = _never, Scripted("the answer"), Chat("PASS")
    world.json("route", TEXT, "--skill", "writing", "--answers", "1")
    assert _row(2)["chat"] == "trays"
    _floor(world, TEXT + " again", "--chat", "trays")  # a floor row for the next one, #3
    world.label, world.worker, world.chatgpt = _never, Scripted("the answer"), Chat("PASS")
    found = world.json("route", TEXT + " again", "--skill", "writing", "--answers", "3", "--chat", "trays")
    assert found["exit"] == 0 and _row(4)["chat"] == "trays"  # given again, the same tag: allowed


def test_answers_carries_the_floor_rows_files(world, tmp_path):
    photo = tmp_path / "Tray photo.png"
    photo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    world.label = fake_label({**jev("read_media"), "status": "below_floor", "confidence": 0.4})
    world.json("route", "what is in this photo", "--file", str(photo))
    world.label, world.worker, world.chatgpt = _never, Scripted("a tray"), Chat("PASS")
    found = world.json("route", "what is in this photo", "--skill", "writing", "--answers", "1")
    new = _row(2)
    assert [(f["name"], f.get("original")) for f in log.files_of(new)] == [("Tray_photo.png", "Tray photo.png")]
    assert (media.in_dir(new["task_id"]) / "Tray_photo.png").exists()
    found = world.json("route", "what is in this photo", "--skill", "writing", "--answers", "1", "--file", str(photo))
    assert found["reason_code"] in ("flag_refused", "already_used")


# ---------- cancel on a floor row ----------

def test_cancel_closes_an_unanswered_floor_row_and_keeps_jevs_label(world):
    _floor(world)
    found = world.json("cancel", "1")
    assert (found["exit"], found["status"], found["outcome"]) == (0, "cancelled", "cancelled")
    row = _row(1)
    assert (row["status"], row["jev_label"], row["reason_code"]) == ("cancelled", "writing", "needs_label")
    world.label = _never
    assert world.json("route", TEXT, "--skill", "writing", "--answers", "1")["reason_code"] == "wrong_state"


def test_cancel_refuses_an_answered_floor_row(world):
    _floor(world)
    world.label, world.worker, world.chatgpt = _never, Scripted("x"), Chat("PASS")
    world.json("route", TEXT, "--skill", "writing", "--answers", "1")
    found = world.json("cancel", "1")
    assert (found["exit"], found["reason_code"]) == (1, "wrong_state") and _row(1)["status"] == "returned"
