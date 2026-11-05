"""Brief 29.1 (decision 3; brief 28's issue 12, the owner's answer, with issue 11's no: `computer_use` stays unrouted): a task
that came back `not_routed` (Jev's label is a skill version 2 doesn't route) is sent again as another skill exactly as a floor
answer: `sr route --skill <key> --answers <n>` with the row's text, its tag, `--web` and files. The row gets `answered_by`,
reads `returned` and keeps Jev's label. Every other refusal stays. Fakes only; every value is fake."""
import json

import pytest

from router import __main__ as cli
from router import log, status
from tests.helpers import fake_label
from tests.test_answer_by_flag import _never, _row, world  # noqa: F401 (the fixture)
from tests.test_json_actions import jev
from tests.test_loop import Scripted
from tests.test_relay import Chat

TEXT = "list the files in this folder and say which have tests"
SURE = {**jev("computer_use"), "status": "ok", "confidence": 0.93}


def _not_routed(world, *extra):
    world.label = fake_label(SURE)
    found = world.json("route", TEXT, *extra)
    assert (found["status"], found["outcome"], found["reason_code"]) == ("returned", "returned", "not_routed"), found
    return found


def test_answers_takes_a_not_routed_return_and_keeps_jevs_label(world):
    _not_routed(world)
    world.label, world.worker, world.chatgpt = _never, Scripted("calc.py has a test"), Chat("PASS")
    found = world.json("route", TEXT, "--skill", "code", "--answers", "1")
    assert (found["exit"], found["n"], found["status"], found["outcome"]) == (0, 2, "done", "passed")
    back, new = _row(1), _row(2)
    assert (back["status"], back["reason_code"], back["answered_by"], back["jev_label"], back["jev_confidence"]) == (
        "returned", "not_routed", new["task_id"], "computer_use", 0.93)
    assert (new["task"], new["skill"], new["skill_source"], new["jev_status"]) == (TEXT, "code", "owner", "not_asked")
    shown = json.loads(world.run("show", "1", "--json")[1])
    assert (shown["answered_by"], shown["waiting_on"], shown["outcome"]) == (new["task_id"], None, "returned")
    code, out, err = world.run("show", "2")
    assert f"Answers #1 {back['task_id']} (Jev labeled it computer_use, which version 2 doesn't route)." in out


def test_a_not_routed_return_keeps_its_tag(world):
    _not_routed(world, "--chat", "files")
    world.label, world.worker, world.chatgpt = _never, Scripted("two files"), Chat("PASS")
    world.json("route", TEXT, "--skill", "code", "--answers", "1")
    assert _row(2)["chat"] == "files"


def test_a_not_routed_return_is_answered_once(world):
    _not_routed(world)
    world.label, world.worker, world.chatgpt = _never, Scripted("one", "two"), Chat("PASS", "PASS")
    world.json("route", TEXT, "--skill", "code", "--answers", "1")
    found = world.json("route", TEXT, "--skill", "code", "--answers", "1")
    assert (found["exit"], found["reason_code"]) == (2, "already_used") and _row(3) is None


@pytest.mark.parametrize("label, code_word", [
    ({**jev("recall"), "status": "ok", "confidence": 0.95}, "needs_tag"),   # another return: refused as today
])
def test_answers_still_refuses_every_other_return(world, label, code_word):
    world.label = fake_label(label)
    found = world.json("route", "what did we decide last time")
    assert found["reason_code"] == code_word
    world.label = _never
    found = world.json("route", "what did we decide last time", "--skill", "writing", "--answers", "1")
    assert (found["exit"], found["reason_code"]) == (2, "wrong_state") and _row(1)["answered_by"] is None


def test_status_marks_which_skills_version_2_routes(world):
    shown = json.loads(world.run("status", "--json")[1])
    routed = {s["key"]: s["routed"] for s in shown["skills"]}
    assert routed["computer_use"] is False and routed["code"] is True and routed["writing"] is True


def test_the_page_sends_a_chip_as_the_floor_answer_command():
    from router import page_commands
    doc = {"skills": [{"key": "code"}, {"key": "computer_use"}]}
    built = page_commands.build({"action": "floor", "skill": "code", "answers": "sr-20261027-101010-aaaa", "text": TEXT},
                                doc)
    assert list(built.args) == ["route", "--json", "--source", "ui", "--skill", "code", "--answers",
                                "sr-20261027-101010-aaaa", "--", TEXT]
