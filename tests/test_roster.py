"""config/agents.json and config/skill_table.json, read and checked together."""
import copy
import json
from pathlib import Path

import pytest

from router.roster import RosterError, load_roster, problems

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
AGENTS_DOC = json.loads((CONFIG_DIR / "agents.json").read_text())
TABLE = json.loads((CONFIG_DIR / "skill_table.json").read_text())
SEND_PATHS = ("claude", "grok", "chatgpt", "cursor")  # the four senders in router/__main__.py (brief 20 added cursor)
THREE_SEND_PATHS = ("claude", "grok", "chatgpt")      # the router before brief 20: no way to send cursor a task


def _docs():
    return copy.deepcopy(AGENTS_DOC), copy.deepcopy(TABLE)


def _one_problem(agents_doc, table, send_paths=SEND_PATHS):
    found = problems(agents_doc, table, send_paths)
    assert len(found) == 1, found
    return found[0]


# ---------- the shipped files ----------

def test_agents_json_is_what_brief_1_specified_plus_brief_3s_model_pin():
    assert AGENTS_DOC == {
        "note": "Only the owner changes a live flag. Rule 12: a new agent goes live only after its send test, "
                "its return test and 3 real tasks.",
        "agents": {
            "claude": {"live": True},
            "grok": {"live": True},
            "chatgpt": {"live": True, "model": "gpt-6.1-sol"},
            "cursor": {"live": True, "model": "grok-4.7-high"},  # brief 20 (rules v2.28); live since the owner's flip, 2026-10-20 (81b777a)
            "muse": {"live": False},
        },
        "skills_not_routed": ["computer_use"],
    }


def test_the_shipped_table_is_version_3_4_with_muse_deferred_and_no_interim():
    assert TABLE["version"] == 3.4 and TABLE["updated"] == "2026-10-20"
    assert "muse" in TABLE["models"] and AGENTS_DOC["agents"]["muse"] == {"live": False}  # the door stays open
    for key, skill in TABLE["skills"].items():
        assert "muse" not in (skill["best"], skill.get("second"), skill.get("interim")), key
        assert skill.get("interim") is None, key
    assert (TABLE["skills"]["bulk_text"]["best"], TABLE["skills"]["bulk_text"]["second"]) == ("claude", "grok")
    assert (TABLE["skills"]["meta_social_trends"]["best"], TABLE["skills"]["meta_social_trends"]["second"]) == ("grok", "chatgpt")
    assert (TABLE["skills"]["read_media"]["best"], TABLE["skills"]["read_media"]["second"]) == ("claude", "chatgpt")
    assert (TABLE["skills"]["make_media"]["best"], TABLE["skills"]["make_media"]["second"]) == ("grok", "claude")
    assert len(TABLE["changes_from_v3_1"]) == 7 and len(TABLE["changes_from_v3_2"]) == 4 and len(TABLE["changes_from_v3_3"]) == 6


def test_the_shipped_files_pass_every_check():
    assert problems(AGENTS_DOC, TABLE, SEND_PATHS) == []


def test_the_shipped_files_load():
    roster = load_roster(send_paths=SEND_PATHS)
    assert roster.names == ("claude", "grok", "chatgpt", "cursor", "muse")
    assert roster.live == ("claude", "grok", "chatgpt", "cursor")  # cursor since the owner's flip, 2026-10-20
    assert roster.not_routed == ("computer_use",)
    assert len(roster.skills) == 12 and roster.skill_order[0] == "x_social_pulse"
    assert roster.labeler["jev_model"] == "jev-1.13.0"
    assert roster.table == TABLE


# ---------- one failing case per check ----------

def test_an_agent_in_the_skill_table_must_be_in_agents_json():
    agents, table = _docs()
    table["skills"]["code"]["second"] = "gemini"
    assert "gemini" in _one_problem(agents, table)


def test_the_skill_tables_model_list_must_match_agents_json():
    agents, table = _docs()
    table["models"].append("gemini")
    assert "gemini" in _one_problem(agents, table)


def test_best_and_second_must_differ():
    agents, table = _docs()
    table["skills"]["code"]["second"] = "claude"
    assert "code" in _one_problem(agents, table)


def test_interim_must_differ_from_second():
    agents, table = _docs()
    table["skills"]["web_research"]["interim"] = "claude"
    assert "web_research" in _one_problem(agents, table)


def test_interim_must_be_a_live_agent():
    agents, table = _docs()
    table["skills"]["meta_social_trends"]["interim"] = "muse"
    problem = _one_problem(agents, table)
    assert "meta_social_trends" in problem and "muse" in problem


def test_every_live_agent_needs_a_send_path_in_code():
    agents, table = _docs()
    agents["agents"]["muse"]["live"] = True
    assert "muse" in _one_problem(agents, table)


@pytest.mark.parametrize("model", ["jev-latest", "jev-1.13", "latest", "", None])
def test_the_jev_model_must_be_a_pinned_version(model):
    agents, table = _docs()
    table["labeler"]["jev_model"] = model
    assert "jev_model" in _one_problem(agents, table)


def test_a_live_flag_must_be_true_or_false():
    agents, table = _docs()
    agents["agents"]["grok"]["live"] = "yes"
    assert any("grok" in p and "live" in p for p in problems(agents, table, SEND_PATHS))


def test_skills_not_routed_must_be_skills_in_the_table():
    agents, table = _docs()
    agents["skills_not_routed"].append("teleport")
    assert "teleport" in _one_problem(agents, table)


def test_every_skill_needs_a_best_agent():
    agents, table = _docs()
    table["skills"]["planning"]["best"] = None
    assert "planning" in _one_problem(agents, table)


def test_agent_names_are_plain_lowercase_words():
    agents, table = _docs()
    agents["agents"]["Bad Name!"] = {"live": False}
    assert "Bad Name!" in _one_problem(agents, table)


@pytest.mark.parametrize("value", [1.5, 0, "high", None])
def test_the_confidence_floor_must_be_a_number_above_0_and_up_to_1(value):
    agents, table = _docs()
    table["labeler"]["min_confidence"] = value
    assert "min_confidence" in _one_problem(agents, table)


@pytest.mark.parametrize("field", ["question", "fallback_label", "fallback_description"])
def test_the_labeler_needs_its_question_and_fallback(field):
    agents, table = _docs()
    del table["labeler"][field]
    assert field in _one_problem(agents, table)


def test_the_labeler_needs_its_second_question():
    agents, table = _docs()
    table["labeler"]["second_question"] = {}
    assert "second_question" in _one_problem(agents, table)


def test_every_problem_is_reported_at_once():
    agents, table = _docs()
    table["skills"]["code"]["second"] = "claude"
    table["labeler"]["jev_model"] = "jev-latest"
    assert len(problems(agents, table, SEND_PATHS)) == 2


# ---------- reading the files ----------

def test_a_file_that_is_not_json_is_refused(tmp_path):
    bad = tmp_path / "agents.json"
    bad.write_text("{not json")
    with pytest.raises(RosterError) as err:
        load_roster(send_paths=SEND_PATHS, agents_path=bad)
    assert "agents.json" in str(err.value)


def test_a_missing_file_is_refused(tmp_path):
    with pytest.raises(RosterError) as err:
        load_roster(send_paths=SEND_PATHS, skills_path=tmp_path / "skill_table.json")
    assert "skill_table.json" in str(err.value)


def test_a_failed_check_lists_its_problems(tmp_path):
    agents, table = _docs()
    agents["agents"]["muse"]["live"] = True
    path = tmp_path / "agents.json"
    path.write_text(json.dumps(agents))
    with pytest.raises(RosterError) as err:
        load_roster(send_paths=SEND_PATHS, agents_path=path)
    assert len(err.value.problems) == 1 and "muse" in err.value.problems[0]


# ---------- build brief 20 (rules v2.28, Cursor): the cursor entry, its model name, never a checker or a stand-in ----------

from router import roster as roster_module  # noqa: E402

CURSOR_SEND_PATHS = SEND_PATHS  # kept by name: the brief 20 tests below read with it; cursor is one of the four senders now


def _cursor_live(doc, model="grok-4.7-high"):
    doc["agents"]["cursor"] = {"live": True, "model": model}
    return doc


def test_the_shipped_cursor_entry_is_live_with_grok_4_7_high_pinned_after_chatgpt():
    # The owner's flip, 2026-10-20 (81b777a): the sandbox probe passed, the send and return tests clean, two live versus tasks.
    assert AGENTS_DOC["agents"]["cursor"] == {"live": True, "model": "grok-4.7-high"}
    assert list(AGENTS_DOC["agents"]) == ["claude", "grok", "chatgpt", "cursor", "muse"]
    assert roster_module.MODEL_REQUIRED == ("chatgpt", "cursor")
    roster = load_roster(send_paths=CURSOR_SEND_PATHS)
    assert roster.model("cursor") == "grok-4.7-high" and "cursor" in roster.live


def test_a_live_cursor_needs_a_pinned_model_and_the_example_is_grok_4_7_high():
    doc, table = _docs()
    doc["agents"]["cursor"] = {"live": True}
    problem = _one_problem(doc, table, CURSOR_SEND_PATHS)
    assert problem == 'agents.json: cursor is live but has no model. Pin one, for example "grok-4.7-high".'


@pytest.mark.parametrize("model", ["grok-4.7-high", "grok-4.7-high-fast", "grok-4.7-xhigh", "grok-4.7-medium",
                                   "cursor-grok-4.6-high", "cursor-grok-4.6-low-fast", "cursor-grok-4.5-high"])
def test_a_model_starting_with_grok_or_cursor_grok_passes(model):
    doc, table = _docs()
    assert problems(_cursor_live(doc, model), table, CURSOR_SEND_PATHS) == []


@pytest.mark.parametrize("model", ["auto", "gpt-5.2", "Grok 4.7", "claude-opus-5-5-high", "composer-2.5", "cursor-auto",
                                   "xgrok-4.7", "gemini-3.7-flash-high", "grok 4.7"])
def test_any_other_name_is_a_load_error_with_the_reason(model):
    doc, table = _docs()
    problem = _one_problem(_cursor_live(doc, model), table, CURSOR_SEND_PATHS)
    assert problem == f"agents.json: cursor's model must start with grok or cursor-grok (never auto), not {model!r}."


def test_the_name_rule_holds_while_cursor_is_not_live_too():
    doc, table = _docs()
    doc["agents"]["cursor"] = {"live": False, "model": "auto"}
    assert "must start with grok or cursor-grok" in _one_problem(doc, table, SEND_PATHS)
    with pytest.raises(RosterError, match="cursor's model must start with grok or cursor-grok"):
        load_roster(send_paths=SEND_PATHS, agents_path=_write(doc))


def _write(doc):
    import tempfile
    path = Path(tempfile.mkdtemp()) / "agents.json"
    path.write_text(json.dumps(doc))
    return path


def test_an_empty_or_non_string_cursor_model_keeps_the_pinned_name_message():
    doc, table = _docs()
    doc["agents"]["cursor"] = {"live": True, "model": " "}
    assert _one_problem(doc, table, CURSOR_SEND_PATHS) == "agents.json: cursor's model must be a pinned model name."


def test_the_chatgpt_rules_are_as_before():
    doc, table = _docs()
    doc["agents"]["chatgpt"] = {"live": True}
    assert 'for example "gpt-6.1-sol"' in _one_problem(doc, table, SEND_PATHS)
    doc["agents"]["chatgpt"] = {"live": True, "model": "auto"}  # no name rule for chatgpt
    assert problems(doc, table, SEND_PATHS) == []


def test_cursor_as_a_skills_second_is_refused_at_load_it_never_checks():
    doc, table = _docs()
    table["skills"]["code"]["second"] = "cursor"
    assert _one_problem(_cursor_live(doc), table, CURSOR_SEND_PATHS) == (
        "skill_table.json: code's second is cursor, but cursor never checks (rules v2.28, Cursor).")


def test_cursor_as_a_skills_interim_is_refused_at_load_it_is_never_a_stand_in():
    doc, table = _docs()
    table["skills"]["code"]["interim"] = "cursor"
    assert _one_problem(_cursor_live(doc), table, CURSOR_SEND_PATHS) == (
        "skill_table.json: code's interim is cursor, but cursor is never a stand-in (rules v2.28, Cursor).")


def test_cursor_as_a_skills_best_passes_the_roster_that_change_is_the_owners_later():
    doc, table = _docs()
    table["skills"]["code"]["best"] = "cursor"
    assert problems(_cursor_live(doc), table, CURSOR_SEND_PATHS) == []


def test_a_live_cursor_with_no_send_path_is_refused_like_any_agent():
    doc, table = _docs()
    assert _one_problem(_cursor_live(doc), table, THREE_SEND_PATHS) == (
        "cursor is live in agents.json, but the router has no way to send it a task.")
