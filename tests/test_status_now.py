"""Build brief 24, B4 (decisions 8, 9, 14 and 15): what happens now, as JSON. `sr status --json` gains, per skill, `now`
(doer, checker, a stand-in, the unchecked reason, a note such as "done without X" or "needs Grok Bot", a come-back), and
per preset `ready`, `why` and `filled`, with each slot's `allowed` listing only available agents. Every task in `sr show
--json` and `sr log --json` carries `stand_in`, `filled` and `card_line`, computed from the row. A JSON read makes no
model call and writes nothing. Through the real main with every outside thing faked."""
import json

import pytest

from router import __main__ as cli
from router import cardline, log, settings
from tests.helpers import fake_label
from tests.test_json_actions import jev
from tests.test_relay import GOOD_NOTE
from tests.test_status import world  # noqa: F401  (the status world: fake checks, versions and store)

NO_INBOX = "Grok Bot isn't set up: no inbox repo in settings"


@pytest.fixture
def no_inbox(monkeypatch, tmp_path):
    local = tmp_path / "bare.local.json"
    local.write_text("{}")
    monkeypatch.setattr(settings, "LOCAL_PATH", local)


def _status(world):  # noqa: F811
    code, out, err = world.run("status", "--json")
    assert code == 0, err
    return json.loads(out)


def test_each_skill_says_what_happens_now_with_every_agent_up(world):  # noqa: F811
    now = {s["key"]: s["now"] for s in _status(world)["skills"]}
    assert now["x_social_pulse"] == {"doer": "grok", "checker": "chatgpt", "stand_in": None, "unchecked": None,
                                     "note": None, "comes_back": None}
    assert now["quick_answer"]["checker"] is None and now["computer_use"]["comes_back"] == "skill not routed in version 2"


def test_without_grok_bot_x_research_is_done_by_chatgpt_without_x_and_images_need_grok_bot(world, no_inbox):  # noqa: F811
    now = {s["key"]: s["now"] for s in _status(world)["skills"]}
    # The owner, 21 Oct: x_social_pulse is Grok Bot's alone, as make_media is; Meta research keeps its stand-in
    assert (now["x_social_pulse"]["note"], now["x_social_pulse"]["comes_back"]) == (
        "needs Grok Bot", f"x_social_pulse needs Grok Bot: {NO_INBOX}")
    assert now["meta_social_trends"] == {"doer": "chatgpt", "checker": "claude", "stand_in": {"for": "grok", "why": NO_INBOX},
                                         "unchecked": None, "note": "done without Meta", "comes_back": None}
    assert (now["make_media"]["note"], now["make_media"]["comes_back"]) == (
        "needs Grok Bot", f"make_media needs Grok Bot: {NO_INBOX}")
    assert now["bulk_text"]["checker"] == "chatgpt" and now["writing"]["checker"] == "chatgpt"


def test_each_preset_says_whether_it_can_run_now_and_how_its_slots_are_filled(world, no_inbox):  # noqa: F811
    by = {p["name"]: p for p in _status(world)["presets"]}
    assert (by["research-build"]["ready"], by["research-build"]["why"]) == (True, None)
    assert by["research-build"]["filled"] == [{"slot": "research", "agent": "chatgpt", "default": "grok", "why": NO_INBOX}]
    assert by["vote"]["ready"] is False and by["vote"]["filled"] == []
    assert by["vote"]["why"] == (f"vote can't run now: slot c (Grok Bot): {NO_INBOX}; no other agent can vote there "
                                 "(ChatGPT is in slot b; Claude is in slot a)")
    assert all("grok" not in s["allowed"] for p in by.values() for s in p["slots"])   # only available agents
    assert all(by[n]["ready"] for n in ("collab", "versus", "redteam"))


def test_a_stand_in_task_carries_who_for_whom_why_and_the_card_line(world, no_inbox):  # noqa: F811
    world.label = fake_label(jev("meta_social_trends"))
    world.chatgpt = type(world.chatgpt)("three bullets with sources", "PASS")
    world.worker = type(world.worker)("PASS")
    found = world.json("route", "what are people on Instagram saying about trays")
    show = json.loads(world.run("show", str(found["n"]), "--json")[1])
    assert show["stand_in"] == {"agent": "chatgpt", "for": "grok", "why": NO_INBOX}
    assert show["card_line"] == "ChatGPT did this · Grok Bot isn't set up · done without Meta"
    assert show["filled"] is None
    row = json.loads(world.run("log", "--json")[1])["tasks"][0]
    assert (row["stand_in"], row["card_line"]) == (show["stand_in"], show["card_line"])


def test_a_filled_relay_task_carries_its_fills_and_the_card_line(world, no_inbox):  # noqa: F811
    world.chatgpt = type(world.chatgpt)(GOOD_NOTE, "PASS")
    world.worker = type(world.worker)("the build")
    found = world.json("relay", "research-build", "what is the current stable python")
    show = json.loads(world.run("show", str(found["n"]), "--json")[1])
    assert show["filled"] == [{"slot": "research", "agent": "chatgpt", "why": NO_INBOX, "default": "grok"}]
    assert show["card_line"] == "ChatGPT did the research · Grok Bot isn't set up"
    assert show["stand_in"] is None


def test_the_usual_agents_leave_no_line(world):  # noqa: F811
    world.label = fake_label(jev("quick_answer", 0.99))
    found = world.json("route", "what is 6 times 7")
    show = json.loads(world.run("show", str(found["n"]), "--json")[1])
    assert (show["stand_in"], show["filled"], show["card_line"]) == (None, None, None)


def test_a_json_read_makes_no_call_and_writes_nothing(world, no_inbox):  # noqa: F811
    world.label = fake_label(jev("meta_social_trends"))
    world.chatgpt = type(world.chatgpt)("bullets", "PASS")
    world.worker = type(world.worker)("PASS")
    world.json("route", "what are people on Instagram saying about trays")
    before = cli.DB_PATH.read_bytes()
    calls = (len(world.chatgpt.prompts), len(world.worker.prompts))
    for argv in (("status", "--json"), ("show", "1", "--json"), ("log", "--json")):
        assert world.run(*argv)[0] == 0
    assert cli.DB_PATH.read_bytes() == before and (len(world.chatgpt.prompts), len(world.worker.prompts)) == calls


@pytest.mark.parametrize("why, short", [
    (NO_INBOX, "Grok Bot isn't set up"), ("ChatGPT is signed out (codex login)", "ChatGPT is signed out"),
    ("Cursor is off: its safety check failed on agent 2026.10.19", "Cursor is off"),
    ("Claude hit its plan limit", "Claude hit its plan limit")])
def test_the_card_line_carries_the_short_form_of_the_reason(why, short):
    assert cardline.short(why) == short
