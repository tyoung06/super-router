"""Build brief 23, A2 (decision 14 and choice 19): the page's facts come from the JSON. `sr status --json` gains
`jev.floor` (the labeler's min_confidence, so the Jev box never hardcodes 0.80) and, on each preset, whether it takes
`--project` (`project`) and which agents a project task refuses in a slot (`project_refuses`), both read from the code
intake uses. `sr show --json` on a split gains what the plan holds per piece (Jev's answer, where the skill table sends
it, whether Jev left it under the floor, the owner's choice, whether its text was edited) and the joining line; on a
tagged task each memory the build call was given carries its text as sent (choice 19). Fakes only."""
import pytest

from router import __main__ as cli
from router import log, memory, split
from tests.fake_hindsight import FakeHindsight
from tests.fixtures import json_shapes
from tests.helpers import fake_label, shipped_roster
from tests.test_json_actions import jev
from tests.test_loop import Scripted
from tests.test_show_log_json import _show
from tests.test_status import _status, world  # noqa: F401  (the status fixture: fake checks, versions and store)

ROSTER = shipped_roster()


# ---------- sr status --json ----------

def test_jev_floor_is_the_skill_tables_min_confidence(world):
    doc = _status(world)
    json_shapes.check(doc, json_shapes.STATUS, optional=("report_path",))
    assert doc["jev"]["floor"] == ROSTER.labeler["min_confidence"] == 0.8


def test_each_preset_says_whether_it_takes_project_from_the_code_intake_uses(world):
    doc = _status(world)
    got = {p["name"]: p["project"] for p in doc["presets"]}
    assert got == {"research-build": True, "collab": False, "versus": False, "redteam": True, "vote": False}
    assert all(p["project_refuses"] == ["cursor"] for p in doc["presets"])
    assert cli._project_presets(cli._presets_or_none(ROSTER)) == [name for name, takes in got.items() if takes]


def test_intake_refuses_project_where_status_says_no(world):
    found = world.json("relay", "versus", "write is_even", "--project", "anything")
    assert (found["exit"], found["reason_code"], found["task_id"]) == (2, "tag_refused", None)
    assert "research-build and redteam only" in found["message"]


# ---------- sr show --json: a split plan's pieces ----------

def _plan_waiting(world, *, choice=None):
    conn = log.init_db(cli.DB_PATH)
    log.add_task(conn, "sr-s", "build the watcher", "cli", {"status": "not_asked", "tokens": 0}, mode="split")
    log.set_route(conn, "sr-s", agents=("claude", "chatgpt", "grok"), agent="claude", route_reason="split",
                  checker="chatgpt", check_state="pending")
    plan = split.new_plan(["the watcher", "the readme section", "the one-line summary"], "Claude joins them",
                          ["sr-p1", "sr-p2", "sr-p3"])
    plan["pieces"][0]["label"] = jev("writing", 0.95)
    plan["pieces"][1]["label"] = jev("code", 0.5, "below_floor")  # under the floor: Approve needs --skill 2=<key>
    plan["pieces"][1]["choice"] = choice
    plan["pieces"][2]["label"] = jev("quick_answer", 0.99)
    plan["pieces"][2]["edited_text"] = "the one-line summary, shorter"
    log.set_split_plan(conn, "sr-s", plan)
    log.set_split_returned(conn, "sr-s", log.AWAITING_APPROVAL)
    conn.close()
    return _show(world, "1")


def test_a_split_plan_shows_each_pieces_label_route_floor_and_edit(world):
    doc = _plan_waiting(world)
    assert doc["waiting_on"] == "split_plan" and doc["join"] == "Claude joins them"
    for piece in doc["pieces"]:
        json_shapes.check(piece, json_shapes.PIECE)
    one, two, three = doc["pieces"]
    assert one["jev"] == {"status": "ok", "label": "writing", "confidence": 0.95}
    assert one["route"] == {"skill": "writing", "agent": "claude", "checker": "chatgpt", "check_state": "pending",
                            "comes_back": None}
    assert (one["needs_label"], one["choice"], one["edited"]) == (False, None, False)
    assert (two["needs_label"], two["route"], two["jev"]["confidence"]) == (True, None, 0.5)
    assert three["route"]["checker"] is None and three["route"]["check_state"] == "not_needed"
    assert (three["edited"], three["text"]) == (True, "the one-line summary, shorter")


def test_a_piece_answered_by_choice_is_no_longer_under_the_floor(world):
    doc = _plan_waiting(world, choice="code")
    two = doc["pieces"][1]
    assert (two["needs_label"], two["choice"]) == (False, "code")
    assert two["route"] == {"skill": "code", "agent": "claude", "checker": "chatgpt", "check_state": "pending",
                            "comes_back": None}


def test_a_split_waiting_on_its_pieces_says_each_pieces_state_in_the_routers_words(world):
    # Brief 23, D: the page's Skip on a blocked piece is shown from the JSON, never worked out by the page, so each
    # piece carries split.piece_state's answer (done, waiting, blocked, or skipped from the plan) and its words.
    conn = log.init_db(cli.DB_PATH)
    log.add_task(conn, "sr-s", "t", "cli", {"status": "not_asked", "tokens": 0}, mode="split")
    log.set_route(conn, "sr-s", agents=("claude", "chatgpt", "grok"), agent="claude", route_reason="split",
                  checker="chatgpt", check_state="pending")
    plan = split.new_plan(["one", "two", "three", "four"], "join", ["sr-p1", "sr-p2", "sr-p3", "sr-p4"])
    plan["approved"] = True
    plan["pieces"][3]["skipped"] = True
    log.set_split_plan(conn, "sr-s", plan)
    log.set_split_returned(conn, "sr-s", f"{log.WAITING_PIECES} #2")
    for task_id, text in (("sr-p1", "one"), ("sr-p2", "two"), ("sr-p3", "three"), ("sr-p4", "four")):
        log.add_task(conn, task_id, text, "split", jev("writing"), mode="piece", parent="sr-s")
    for task_id, status, agent, check_state in (("sr-p1", "done", "claude", "passed"), ("sr-p2", "done", "claude", "failed"),
                                                 ("sr-p3", "sent", "grok", None), ("sr-p4", "failed", "claude", None)):
        conn.execute("UPDATE tasks SET status = ?, agent = ?, check_state = ? WHERE task_id = ?",
                     (status, agent, check_state, task_id))
    conn.commit()
    conn.close()
    doc = _show(world, "1")
    assert doc["waiting_on"] == "piece"
    assert [(p["piece"], p["piece_state"], p["why"]) for p in doc["pieces"]] == [
        (1, "done", None), (2, "blocked", "it failed its check twice"), (3, "waiting", "with grok"), (4, "skipped", None)]
    for piece in doc["pieces"]:
        json_shapes.check(piece, json_shapes.PIECE)


def test_a_plan_not_yet_approved_has_no_piece_rows_so_no_piece_state(world):
    doc = _plan_waiting(world)
    assert [(p["piece_state"], p["why"]) for p in doc["pieces"]] == [(None, None)] * 3


def test_a_routed_task_has_no_join(world):
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("391")
    world.json("route", "what is 17 times 23")
    doc = _show(world, "1")
    assert (doc["join"], doc["pieces"]) == (None, None)


# ---------- sr show --json: what the build call was given (choice 19) ----------

def test_each_memory_given_carries_its_text_as_sent(world, monkeypatch):
    fake = FakeHindsight()
    monkeypatch.setattr(cli.memory, "client", lambda *a, **k: fake.client)
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("391", "it was 391")
    world.json("route", "what is 17 times 23", "--chat", "tray")
    world.json("route", "what did we get last time", "--chat", "tray")
    doc = _show(world, "2")
    assert len(doc["memory_given"]) == 1
    given = doc["memory_given"][0]
    json_shapes.check(given, json_shapes.MEMORY_GIVEN)
    conn = log.init_db(cli.DB_PATH)
    record = log.call_memory_of(log.calls_for(conn, doc["task_id"])[0])
    conn.close()
    assert given["n"] == 1 and given["text"] == memory.entries_of_block(record["text"])[0].text
    assert given["text"].startswith("what is 17 times 23") and "391" in given["text"]


@pytest.mark.parametrize("words", [("1",)])
def test_a_task_without_memory_gives_an_empty_list(world, words):
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("391")
    world.json("route", "what is 17 times 23")
    assert _show(world, *words)["memory_given"] == []
