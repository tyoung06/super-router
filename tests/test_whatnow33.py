"""Build brief 33, W (decision 13): What now?, one line in a project's pinned head with one move and its control, chosen by
code in a fixed order, the first that applies winning, recomputed on every read and never stored: (1) a task waits on
the owner, (2) a task is running, (3) the newest top-level task that wasn't cancelled, discarded or undone ended without
delivery, (4) that task was delivered and has chips, (5) otherwise. `what_now` in `sr log --json --project <name>` and in
each project of `sr project list --json`; never on a chat or without --project. Every value here is fake."""
import json

import pytest

from router import __main__ as cli
from router import ideas, log, receipt, whatnow
from tests.helpers import ALL_AGENTS

PROJECT = "demo"
JEV = {"status": "ok", "label": "code", "confidence": 0.9, "tokens": 0}
HANDOFF = ("\n\n## Handoff\n### Produced\nnothing written: the temperature table\n### Status\nthe table is in\n"
           "### Next\n- Add a --round option to the converter.\n- Write the tests for negative values.")


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _task(conn, k, *, status="done", check_state="passed", result="The table.", skill="code", files=None, mode="route",
          text=None, parent=None):
    task_id = f"sr-20261029-1000{k:02d}-ab{k:02d}"
    log.add_task(conn, task_id, text or f"task {k}", "cli", JEV, project=PROJECT, mode=mode)
    log.set_route(conn, task_id, agents=ALL_AGENTS, agent="claude", route_reason="best", skill=skill, checker="chatgpt",
                  check_state="pending")
    if status == "done":
        log.add_call(conn, task_id, task_id, "do", "claude", status="done", text=result + HANDOFF)
        log.add_call(conn, f"{task_id}-c1", task_id, "check", "chatgpt", status="done", text="PASS", verdict="PASS")
        log.set_done(conn, task_id, result, check_state=check_state)
    elif status == "cancelled":
        log.set_cancelled(conn, task_id)
    if files is not None:
        log.set_project_files(conn, task_id, files)
    return log.get_task(conn, task_id)


def test_a_project_with_no_tasks_says_to_send_one(conn):
    assert whatnow.for_project(conn, PROJECT) == {"rung": 5, "words": "Send a task to start.", "control": None,
                                                  "task_id": None, "n": None, "chip": None,
                                                  "need": None, "chips": None, "plan_md": None}


def test_a_delivered_task_offers_its_first_handoff_next_line_with_that_chip(conn):
    row = _task(conn, 1)
    found = whatnow.for_project(conn, PROJECT)
    assert (found["rung"], found["words"], found["control"], found["n"]) == (
        4, "Next: Add a --round option to the converter.", "chip", row["n"])
    assert found["chip"]["kind"] == "agent" and found["chip"]["fill"]["project"] == PROJECT and found["chip"]["later"]


def test_without_an_agent_line_it_offers_build_from(conn):
    row = _task(conn, 1)
    conn.execute("UPDATE calls SET text = ? WHERE task_id = ?", ("The table.", row["task_id"]))
    found = whatnow.for_project(conn, PROJECT)
    assert (found["rung"], found["words"], found["chip"]["kind"]) == (4, f"Next: Build from #{row['n']}", "build_from")


def test_a_delivered_task_with_no_chips_says_nothing_suggested_and_offers_ideas_when_there_are_some(conn):
    _task(conn, 1, skill="quick_answer", result="42")
    conn.execute("UPDATE calls SET text = '42'")
    assert whatnow.for_project(conn, PROJECT)["words"] == "Nothing suggested"
    assert whatnow.for_project(conn, PROJECT)["control"] is None
    ideas.add(conn, PROJECT, "Add a Kelvin column.")
    assert whatnow.for_project(conn, PROJECT)["control"] == "ideas"


@pytest.mark.parametrize("check_state, words", [("failed", "failed its check")])
def test_the_newest_task_that_ended_without_delivery_says_how_with_open(conn, check_state, words):
    _task(conn, 1)
    row = _task(conn, 2, check_state=check_state)
    found = whatnow.for_project(conn, PROJECT)
    assert (found["rung"], found["words"], found["control"], found["task_id"]) == (3, f"#{row['n']} {words}", "open",
                                                                                 row["task_id"])


def test_a_cancelled_discarded_or_undone_newest_task_is_passed_over(conn):
    first = _task(conn, 1)
    _task(conn, 2, status="cancelled")
    _task(conn, 3, files={"state": "discarded"})
    _task(conn, 4, files={"state": "undone"})
    found = whatnow.for_project(conn, PROJECT)
    assert (found["rung"], found["n"]) == (4, first["n"])


def test_a_running_task_says_who_is_on_it_with_no_control(conn):
    _task(conn, 1)
    row = _task(conn, 2, status="queued")
    found = whatnow.for_project(conn, PROJECT)
    assert (found["rung"], found["words"], found["control"]) == (2, f"#{row['n']} is running · Claude", None)


def test_a_change_waiting_to_land_waits_on_the_owner_first(conn):
    row = _task(conn, 1, files={"state": "waiting"})
    found = whatnow.for_project(conn, PROJECT)
    assert (found["rung"], found["words"], found["control"], found["task_id"]) == (
        1, f"Waiting on you: #{row['n']} · a change ready to land", "open", row["task_id"])


def test_a_floor_row_waiting_for_its_skill_waits_on_the_owner(conn):
    task_id = "sr-20261029-100099-ab99"
    log.add_task(conn, task_id, "do the vague thing", "cli", {**JEV, "status": "below_floor", "confidence": 0.3},
                 project=PROJECT)
    log.set_returned(conn, task_id, "returned: needs your label", reason_code="needs_label")
    found = whatnow.for_project(conn, PROJECT)
    assert (found["rung"], found["words"]) == (1, f"Waiting on you: #{log.get_task(conn, task_id)['n']} · pick a skill")


def test_another_project_and_a_chat_never_count(conn):
    _task(conn, 1)
    log.add_task(conn, "sr-20261029-110000-cc01", "a chat task", "cli", JEV, chat="tray")
    assert whatnow.for_project(conn, "other") == {"rung": 5, "words": "Send a task to start.", "control": None,
                                                 "task_id": None, "n": None, "chip": None,
                                                  "need": None, "chips": None, "plan_md": None}


# ---------- the JSON ----------

def test_sr_log_json_carries_it_with_project_only(conn):
    _task(conn, 1)
    out = receipt.Receipt()
    assert cli.cmd_log(conn=conn, project=PROJECT, as_json=True, out=out) == 0
    doc = out.document
    assert doc["what_now"] == whatnow.for_project(conn, PROJECT)
    plain = receipt.Receipt()
    cli.cmd_log(conn=conn, as_json=True, out=plain)
    assert "what_now" not in plain.document


def test_each_project_in_the_list_carries_it():
    found = cli._projects_json({PROJECT: "/nowhere/demo"}, {}, conn=log.init_db(":memory:"))
    assert found[0]["what_now"]["words"] == "Send a task to start."
    assert set(found[0]) >= {"name", "what_now", "ideas"}


def test_the_demo_serves_each_projects_line_with_its_log():
    from router import page
    reader = page.DemoReader()
    code, body = reader.log(["--project=garden-site"])
    doc = json.loads(body)
    assert code == 200 and doc["what_now"]["words"] == "Next: Add the opening hours."
    assert all(t["project"] == "garden-site" for t in doc["tasks"])
    assert "what_now" not in json.loads(reader.log()[1])
