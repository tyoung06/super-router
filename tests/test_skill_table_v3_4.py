"""Skill table 3.4 (2026-10-20): the 12th skill `recall`, exactly the entry in the owner's round 4 task file
(`recall_entry_for_skill_table_3_4`, the round 3 text sharpened after m11), after quick_answer; nothing on any other
skill changed from 3.3.
tests/fixtures/skill_table_v3_3.json is config/skill_table.json as shipped on 2026-10-13 (version 3.3), copied
before this change (brief 25 read the owner's first name in it and in the shipped file as "the owner", one rewrite
for both). Rules v2.28, Jev: "A 12th skill, recall". Brief 25: `interim_note` carries the owner's words for what
brief 24 built (a switched-off agent's skills go to a stand-in); nothing else moved."""
import json
from pathlib import Path

from router import __main__ as cli
from router.roster import AGENTS_PATH, SKILLS_PATH, problems

ROOT = Path(__file__).resolve().parent.parent
TABLE = json.loads(SKILLS_PATH.read_text())
V3_3 = json.loads((ROOT / "tests" / "fixtures" / "skill_table_v3_3.json").read_text())
AGENTS_DOC = json.loads(AGENTS_PATH.read_text())

RECALL = {
    "description": "Answer a question about earlier tasks in the same project or chat from what the router remembers: what was done, decided, produced or said, or what was planned next. The answer reports; it makes nothing new.",
    "not_for": "Any task that produces something, even from an earlier result or 'from memory': writing, rewriting, shortening or redoing a text, planning, code, or anything needing new facts from the web or social media.",
    "best": "claude",
    "second": "chatgpt",
    "confidence": "medium",
    "note": "Rules 2.28, Jev. Text sharpened after label test round 3 (m11, a rewrite 'from memory', went recall at 0.86). Live only after round 4 of the label test; a recall task with no --project and no --chat comes back to the owner: nothing to recall from.",
    "interim": None,
}


def test_the_fixture_is_version_3_3_as_shipped_on_2026_10_13():
    assert V3_3["version"] == 3.3 and V3_3["updated"] == "2026-10-13" and len(V3_3["skills"]) == 11
    assert list(V3_3["skills"])[-1] == "quick_answer"


def test_version_3_4_adds_recall_after_quick_answer_exactly_as_the_owners_file_gives_it():
    assert TABLE["version"] == 3.4 and TABLE["updated"] == "2026-10-20"
    assert list(TABLE["skills"]) == list(V3_3["skills"]) + ["recall"]
    assert TABLE["skills"]["recall"] == RECALL and list(TABLE["skills"]["recall"]) == list(RECALL)


def test_no_other_skill_and_nothing_else_changed_from_3_3():
    for name, skill in V3_3["skills"].items():
        assert TABLE["skills"][name] == skill, name  # description, not_for, best, second, confidence, note, interim
    for field in ("models", "labeler", "changes_from_v2", "changes_from_v3", "changes_from_v3_1", "changes_from_v3_2"):
        assert TABLE[field] == V3_3[field], field
    assert set(TABLE) == set(V3_3) | {"changes_from_v3_3"}


# Brief 25 (B): the owner's words, set by their own command; the 3.3 note said a switched-off agent's skills came back to them.
INTERIM_NOTE = ("All null since 2026-10-13. Since brief 24 (rules 2.34) a skill whose best agent isn't available (not live, not set "
                "up, signed out, or off after a failed safety check) goes to the next available agent in the order best, interim, "
                "second, Claude, and the card names the stand-in and why; make_media and x_social_pulse alone come back, since "
                "nothing stands in for Grok Imagine or X search. A non-null interim still goes before second place.")


def test_the_interim_note_says_what_brief_24_built():
    assert TABLE["interim_note"] == INTERIM_NOTE and V3_3["interim_note"] != INTERIM_NOTE


def test_the_status_and_the_change_list_name_the_change():
    assert "3.4" in TABLE["status"] and "recall" in TABLE["status"]
    changes = TABLE["changes_from_v3_3"]
    assert isinstance(changes, list) and len(changes) >= 3 and all(isinstance(line, str) and line for line in changes)
    assert any("recall" in line for line in changes)
    assert any("No other skill" in line or "no other skill" in line for line in changes)


def test_round_4_sharpened_the_recall_text_and_the_change_list_says_so():
    recall = TABLE["skills"]["recall"]
    assert recall["description"].endswith("The answer reports; it makes nothing new.")
    assert recall["not_for"].startswith("Any task that produces something, even from an earlier result or 'from memory'")
    assert "round 3" in recall["note"] and "m11" in recall["note"]
    changes = TABLE["changes_from_v3_3"]
    assert len(changes) == 6 and "sharpened" in changes[-1] and "m11" in changes[-1] and "round 3" in changes[-1]


def test_the_shipped_files_pass_every_roster_check_with_recall():
    assert problems(AGENTS_DOC, TABLE, tuple(cli.SENDERS)) == []
