"""Cleanup 2, row 3: the 12 Models rows tell the truth about who does the work, and `sr models set` refuses a pick that can
never apply. "Never" means the router's own choice (the owner's option A, 4 Nov): `@agent` and `--no-files` still reach a
pick already in the file, so `resolve` doesn't change. Fakes only; every value here is fake."""
import json
import re
from pathlib import Path

import pytest

from router import __main__ as cli
from router import availability, models, receipt, routing
from tests.helpers import shipped_roster

ROSTER = shipped_roster()
LOADED = cli._presets_or_none(ROSTER)
OPUS = "claude-opus-5-5"
ACCEPTED = {
    "x_social_pulse": (), "make_media": (), "computer_use": (),
    "meta_social_trends": ("chatgpt", "claude"), "web_research": ("chatgpt", "claude"), "read_media": ("claude", "chatgpt"),
    "code": ("claude", "chatgpt"), "writing": ("claude", "chatgpt"), "planning": ("claude", "chatgpt"), "recall": ("claude", "chatgpt"),
    "bulk_text": ("claude", "chatgpt"), "quick_answer": ("claude", "chatgpt"),
}
MODEL = {"claude": "opus", "chatgpt": "gpt-6.1-sol", "cursor": "grok-4.7-low"}


def _models(words=(), **flags):
    out = receipt.Receipt()
    code = cli.cmd_models(list(words), roster=ROSTER, loaded=LOADED, as_json=True, out=out, **flags)
    return code, out


def _rows(available):
    """Setup's skill rows with this availability: a function of the agent's name, as routing's table is."""
    table = routing._table(available, ROSTER)
    now = {key: routing.now_for(key, ROSTER, table) for key in ROSTER.skills}
    found = models.tracked()
    rows = models.setup_rows({}, models.local(found=found), found, skills=tuple(ROSTER.skills), skills_now=now, roster=ROSTER)
    return {row["key"]: row for row in rows["skills"]}


def _up(*down):
    def table(name):
        return availability.Availability(name not in down, "down" if name in down else None, "not_live" if name in down else None)
    return table


def test_the_table_covers_every_skill_in_the_shipped_table():
    assert set(ACCEPTED) == set(ROSTER.skills)


@pytest.mark.parametrize("skill", sorted(ACCEPTED))
@pytest.mark.parametrize("agent", ["claude", "chatgpt", "cursor"])
def test_set_accepts_or_refuses_each_agent_on_each_skill(skill, agent):
    code, out = _models(["set"], skill=skill, agent=agent, model=MODEL[agent])
    if agent in ACCEPTED[skill]:
        assert code == 0, out.lines
        assert json.loads(models.LOCAL_PATH.read_text())["skills"][skill][agent]["model"]
    else:
        assert code == 2
        assert out.code == "bad_model"
        assert "can never apply" in out.message and out.message.endswith("Nothing was changed.")
        assert not models.LOCAL_PATH.exists()


def test_the_refusal_says_whose_it_is_and_the_way_for_one_task():
    _, out = _models(["set"], skill="x_social_pulse", agent="claude", model="opus")
    assert out.message == ("Refused: X research is Grok Bot's alone, so a default for Claude can never apply. For one task, "
                                       "send it as `@claude` with `--model claude=opus`. Nothing was changed.")
    _, out = _models(["set"], skill="computer_use", agent="chatgpt", model=MODEL["chatgpt"])
    assert out.message.startswith("Refused: Computer use isn't routed, so a default for ChatGPT can never apply.")
    _, out = _models(["set"], skill="code", agent="cursor", model="grok-4.7-low")
    assert out.message.startswith("Refused: The router never sends Code to Cursor, so a default for Cursor can never apply.")


def test_effort_alone_counts_as_a_pick_and_names_itself():
    code, out = _models(["set"], skill="make_media", agent="claude", effort="high")
    assert code == 2 and "`--effort claude=high`" in out.message
    assert not models.LOCAL_PATH.exists()


def test_an_agent_with_no_choice_keeps_its_own_refusal():
    code, out = _models(["set"], skill="x_social_pulse", agent="grok", model="anything")
    assert code == 2 and "can never apply" not in out.message


def test_clear_is_never_refused_so_an_old_pick_can_come_out():
    models.LOCAL_PATH.write_text(json.dumps({"skills": {"x_social_pulse": {"claude": {"model": OPUS}}}}))
    code, _ = _models(["clear"], skill="x_social_pulse", agent="claude")
    assert code == 0
    assert "x_social_pulse" not in json.dumps(json.loads(models.LOCAL_PATH.read_text()) if models.LOCAL_PATH.exists() else {})


@pytest.mark.parametrize("no_files", [False, True])
def test_resolve_still_reads_an_old_pick_on_the_two_doors(no_files):
    """Option A: `@claude` and a `--no-files` draft keep the skill on the task, so they reach the pick as they do today."""
    models.LOCAL_PATH.write_text(json.dumps({"skills": {"x_social_pulse": {"claude": {"model": OPUS}}}}))
    task = {"mode": "route", "preset": None, "skill": "x_social_pulse", "models": None, "task_id": "t",
            "project_files": json.dumps({"mode": "on", "state": "none", "copy": True, "read_only": True}) if no_files else None}
    choice = models.resolve(task, "claude", kind="do", found=models.tracked(), local_doc=models.local(), pins={})
    assert (choice.model, choice.layer) == (OPUS, "skill")


def test_every_row_with_everyone_up():
    rows = _rows(_up())
    want = {"x_social_pulse": ("grok", "service"), "meta_social_trends": ("grok", "service"), "make_media": ("grok", "service"),
            "computer_use": (None, "not_routed"), "web_research": ("chatgpt", "choice"), "read_media": ("claude", "choice"),
            "code": ("claude", "choice"), "writing": ("claude", "choice"), "planning": ("claude", "choice"),
            "bulk_text": ("claude", "choice"), "quick_answer": ("claude", "choice"), "recall": ("claude", "choice")}
    assert {key: (row["agent"], row["state"]) for key, row in rows.items()} == want
    assert all(row["unused"] == [] for row in rows.values())
    assert rows["x_social_pulse"]["comes_back"] is False


def test_a_row_follows_its_stand_in_with_grok_bot_down_then_chatgpt_too():
    rows = _rows(_up("grok"))
    assert (rows["meta_social_trends"]["agent"], rows["meta_social_trends"]["state"]) == ("chatgpt", "choice")
    for key in ("x_social_pulse", "make_media"):
        assert (rows[key]["agent"], rows[key]["state"], rows[key]["comes_back"]) == ("grok", "service", True)
    assert rows["computer_use"]["state"] == "not_routed"
    both = _rows(_up("grok", "chatgpt"))
    assert (both["meta_social_trends"]["agent"], both["meta_social_trends"]["state"]) == ("claude", "choice")
    assert (both["web_research"]["agent"], both["web_research"]["state"]) == ("claude", "choice")
    assert _rows(_up("chatgpt"))["web_research"]["agent"] == "claude"


def test_a_row_shows_its_doers_own_pick_and_lists_an_old_one_apart():
    models.LOCAL_PATH.write_text(json.dumps({"skills": {"x_social_pulse": {"claude": {"model": OPUS}},
                                                        "code": {"claude": {"model": OPUS}, "cursor": {"model": "grok-4.7-low"}}}}))
    rows = _rows(_up())
    assert rows["x_social_pulse"]["model"] is None
    assert rows["x_social_pulse"]["unused"] == [{"agent": "claude", "model": OPUS, "effort": None, "name": "Opus 5.5"}]
    assert rows["code"]["model"] == OPUS
    assert [u["agent"] for u in rows["code"]["unused"]] == ["cursor"]


def test_sr_models_names_each_old_pick_with_the_command_to_clear_it():
    models.LOCAL_PATH.write_text(json.dumps({"skills": {"x_social_pulse": {"claude": {"model": OPUS}}}}))
    doc = cli._models_doc(ROSTER, LOADED)
    words = "\n".join(models.lines(doc))
    assert "X research: your earlier pick for Claude (Opus 5.5) isn't used" in words
    assert "sr models clear --skill x_social_pulse --agent claude" in words
    assert doc["problems"] == []  # it isn't a problem: Models' light stays as it was


def test_the_page_and_the_router_name_the_skills_alike():
    source = (Path(__file__).parent.parent / "static" / "app.js").read_text(encoding="utf-8")
    block = re.search(r"const SKILL_NAMES = \{(.*?)\};", source, re.S).group(1)
    page = dict(re.findall(r'(\w+): "([^"]+)"', block))
    assert page == routing.SKILL_WORDS
    assert set(page) == set(ROSTER.skills)
