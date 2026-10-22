"""Build brief 25, B1 (decision 3): docs/RULES.md, the cleaned copy of SUPER-ROUTER.md made at each publish by one fixed
transform (scripts/rules_copy.py). Retitled; line 3 keeps the version; every "Changes from" section and any section whose
heading holds a forbidden word dropped; the personal lines generalised by a table anchored on words that are not private,
each row matching exactly once; the owner's first name (passed in at run time, never spelled in the transform) read as
"the owner", as a stored value as `owner`, and their pronouns as theirs. The words that must never reach the copy are
this Mac's (`publish_forbidden` in the local settings file, the first name of `id -F`), read at run time: this file
spells none, and its own cases use the invented name Quinn. The real file's checks are structural (headings and tables
intact), not a snapshot of its text."""
import json
import re
import subprocess
from pathlib import Path

import pytest

from router import status
from scripts import publish, rules_copy

ROOT = Path(__file__).resolve().parent.parent
NAME = "Quinn"  # the invented owner of every case below
SOURCE = ROOT / "SUPER-ROUTER.md"
COPY = ROOT / "docs" / "RULES.md"

ANCHORS = ("- No Examplebroker access of any kind. This project never touches real money.\n"
           "`~/Projects/secret-proj` is never registered.\n"
           "Files land in `~/Desktop/Router Drop` on Quinn's Mac.\n")


def _doc(body="", sections=""):
    return ("# SUPER-ROUTER.md — Quinn's demands\n\n"
            "Version 2.34 · 2026-10-21 · Only Quinn changes this file. Claude Code may propose edits, never make them.\n\n"
            "## What this project is\n\n" + body + "\n" + ANCHORS + sections)


def real_first_name():
    """The first name of this Mac's account (`id -F`), read at import (conftest blocks a test's own subprocesses), or None."""
    try:
        words = subprocess.run(["id", "-F"], capture_output=True, text=True, timeout=10).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    parts = publish._full_name_parts(" ".join(words))
    return parts[0] if parts else None


REAL_NAME = real_first_name()


def _holds(text, name):
    return bool(name) and re.search(rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])", text, re.I) is not None


def real_forbidden(root=ROOT):
    """This Mac's `publish_forbidden` words from its own config/settings.local.json, read directly, or None."""
    try:
        doc = json.loads((Path(root) / "config" / "settings.local.json").read_text())
    except (OSError, ValueError):
        return None
    words = doc.get("publish_forbidden") if isinstance(doc, dict) else None
    return [w for w in words if isinstance(w, str) and w.strip()] if isinstance(words, list) and words else None


needs_source = pytest.mark.skipif(not SOURCE.exists(), reason="SUPER-ROUTER.md is not in this copy (the public clone)")
needs_words = pytest.mark.skipif(real_forbidden() is None, reason="no publish_forbidden in this Mac's config/settings.local.json")


def _headings(text):
    return [line for line in text.splitlines() if line.startswith("#")]


def _tables(text):
    """Each table (a run of lines starting with |) as its row count and the pipes on each row."""
    found, run = [], []
    for line in text.splitlines() + [""]:
        if line.startswith("|"):
            run.append(line.count("|"))
        elif run:
            found.append((len(run), tuple(run)))
            run = []
    return found


# ---------- the fixed parts ----------

def test_the_title_and_the_version_line():
    out = rules_copy.transform(_doc(), name=NAME)
    lines = out.splitlines()
    assert lines[0] == "# Super Router rules"
    assert lines[2] == "Version 2.34 · 2026-10-21 · A cleaned copy of the owner's rules, made at each publish."
    assert status.RULES_VERSION.match(lines[2]).group(1) == "2.34"


def test_a_line_3_that_is_no_version_line_stops():
    with pytest.raises(rules_copy.RulesCopyError, match="line 3"):
        rules_copy.transform(_doc().replace("Version 2.34 · ", "Version two · "), name=NAME)


def test_changes_sections_and_a_heading_with_a_forbidden_word_are_dropped():
    sections = ("\n## Secretproj\n\n- off limits.\n\n## Money\n\n- kept.\n\n## Changes from 2.33\n\n- gone.\n\n"
                "## Changes from 2.16\n\n- gone too.\n")
    out = rules_copy.transform(_doc(sections=sections), forbidden=["SECRETPROJ"], name=NAME)
    assert _headings(out) == ["# Super Router rules", "## What this project is", "## Money"]
    assert "gone" not in out and "off limits" not in out and "- kept." in out


def test_every_table_row_generalises_its_line():
    out = rules_copy.transform(_doc(), name=NAME)
    assert "- No brokerage access of any kind. This project never touches real money." in out
    assert "A folder named in the `never_register` setting is never registered." in out
    assert "Files land in `~/Desktop/Router Drop` by default." in out
    assert "Examplebroker" not in out and "secret-proj" not in out and "Secretproj" not in out


@pytest.mark.parametrize("row", range(len(rules_copy.TABLE)))
def test_a_row_that_matches_nothing_stops_and_names_it(row):
    what, pattern, _ = rules_copy.TABLE[row]
    text = pattern.sub("", _doc(), count=1)
    with pytest.raises(rules_copy.RulesCopyError, match=re.escape(what)):
        rules_copy.transform(text, name=NAME)


def test_a_row_that_matches_twice_stops():
    with pytest.raises(rules_copy.RulesCopyError, match="2 times"):
        rules_copy.transform(_doc(body="- No Otherbroker access of any kind. This project never touches real money.\n"), name=NAME)


# ---------- a list item that still holds a forbidden word, once the table has run ----------

def test_a_list_item_still_holding_a_forbidden_word_is_dropped():
    body = ("- Water the beds at dawn.\n- Never open Secretproj's folder.\n1. Sow in rows.\n2. Label SECRETPROJ trays.\n"
            "A plain line about secretproj stays, for the scan to stop.\n")
    out = rules_copy.transform(_doc(body=body), forbidden=["secretproj"], name=NAME)
    assert "- Water the beds at dawn." in out and "1. Sow in rows." in out
    assert "Never open" not in out and "Label" not in out
    assert "A plain line about secretproj stays, for the scan to stop." in out


def test_the_lines_indented_under_a_dropped_item_go_with_it():
    body = "- Keep secretproj apart,\n  and its notes too.\n- Kept.\n"
    out = rules_copy.transform(_doc(body=body), forbidden=["secretproj"], name=NAME)
    assert "apart" not in out and "its notes too" not in out and "- Kept." in out


def test_the_table_runs_first_so_a_line_it_generalises_stays():
    out = rules_copy.transform(_doc(), forbidden=["examplebroker"], name=NAME)
    assert "- No brokerage access of any kind. This project never touches real money." in out


def test_without_forbidden_words_no_item_is_dropped():
    out = rules_copy.transform(_doc(body="- Never open Secretproj's folder.\n"), name=NAME)
    assert "- Never open Secretproj's folder." in out


# ---------- the name and the pronouns ----------

@pytest.mark.parametrize("before, after", [
    ("Quinn types a task.", "The owner types a task."),
    ("- Quinn runs it.", "- The owner runs it."),
    ("| Quinn | one |", "| The owner | one |"),
    ("It ends. Quinn's file wins.", "It ends. The owner's file wins."),
    ('It hides the gap." Quinn, 21 Oct, after the check.', 'It hides the gap." The owner, 21 Oct, after the check.'),
    ("- **Who it is for.** Quinn, then people who clone it.", "- **Who it is for.** The owner, then people who clone it."),
    ("- **Quinn's rule (20 Oct).** Nobody runs it.", "- **The owner's rule (20 Oct).** Nobody runs it."),
    ("the router asks Quinn which skill", "the router asks the owner which skill"),
    ("(Quinn, 21 Oct)", "(the owner, 21 Oct)"),
    ("Jev's 30: Quinn did not write it", "Jev's 30: the owner did not write it"),
    ("`skill_source: quinn` is the stored value", "`skill_source: owner` is the stored value"),
    ("Quinnton and quinnish stay", "Quinnton and quinnish stay"),
])
def test_the_name(before, after):
    assert rules_copy.read_as_owner(before, NAME) == after


def test_a_wrapped_line_is_not_a_sentence_start():
    text = "A task may belong to one of\nQuinn's projects; then it reads.\n\nQuinn types a task.\n"
    assert rules_copy.read_as_owner(text, NAME) == ("A task may belong to one of\nthe owner's projects; then it reads.\n\n"
                                              "The owner types a task.\n")


# Invented sentences, each read with the he set and with the she set: both come out alike.
SETS = {"he": dict(S="He", s="he", o="him", P="His", p="his", pp="his", r="himself"),
        "she": dict(S="She", s="she", o="her", P="Her", p="her", pp="hers", r="herself")}


@pytest.mark.parametrize("pronouns", sorted(SETS))
@pytest.mark.parametrize("before, after", [
    ("{S} picks the seeds.", "The owner picks the seeds."),
    ("The trays are sown. Then {s} labels each one.", "The trays are sown. Then the owner labels each one."),
    ("- {S} waters the beds at dawn.", "- The owner waters the beds at dawn."),
    ("Quinn plants a row, and {s} waters it.", "The owner plants a row, and the owner waters it."),
    ("The router asks {o} first.", "The router asks them first."),
    ("A note reaches {o} before noon.", "A note reaches them before noon."),
    ("It asks {o} to confirm, then waits.", "It asks them to confirm, then waits."),
    ("The last tray goes to {o}.", "The last tray goes to them."),
    ("{P} list is kept.", "Their list is kept."),
    ("It keeps {p} list and {p} own notes.", "It keeps their list and their own notes."),
    ("The last word is {pp}.", "The last word is theirs."),
    ("Nobody else sows it; {s} sows it {r}.", "Nobody else sows it; the owner sows it themselves."),
])
def test_the_pronouns_of_either_set_read_as_the_singular_they(pronouns, before, after):
    assert rules_copy.read_as_owner(before.format(**SETS[pronouns]), NAME) == after


def test_a_word_that_merely_holds_a_pronoun_stays():
    text = "Here the chef said when the theme of the herbs sheds light."
    assert rules_copy.read_as_owner(text, NAME) == text


def test_without_a_name_no_name_is_read():
    assert rules_copy.read_as_owner("Quinn types a task.", None) == "Quinn types a task."
    assert rules_copy.transform(_doc()).splitlines()[0] == "# Super Router rules"


# ---------- the real file: structure, not a snapshot ----------

@needs_source
def test_the_real_file_keeps_every_heading_but_the_dropped_ones_and_every_table():
    words = real_forbidden() or []
    src = SOURCE.read_text()
    out = rules_copy.transform(src, forbidden=words, name=REAL_NAME)
    keep, kept_text = True, []
    for line in src.splitlines():
        if line.startswith("## "):
            keep = not line.startswith("## Changes from ") and not any(w.lower() in line.lower() for w in words)
        if keep:
            kept_text.append(line)
    kept_text = "\n".join(kept_text)
    assert _headings(out) == ["# Super Router rules"] + _headings(kept_text)[1:]
    assert _tables(out) == _tables(kept_text) and _tables(out)
    assert "## Changes from" not in out and not _holds(out, REAL_NAME)
    assert status.RULES_VERSION.match(out.splitlines()[2]).group(1) == status.rules_version(SOURCE)


@needs_source
@needs_words
def test_the_real_file_holds_no_forbidden_word_once_cleaned():
    words = real_forbidden()
    out = rules_copy.transform(SOURCE.read_text(), forbidden=words, name=REAL_NAME).lower()
    assert [w for w in words if w.lower() in out] == []
    assert len(out.splitlines()) < len(SOURCE.read_text().splitlines())


# ---------- the public copy, where it is the only rules file ----------

@pytest.mark.skipif(not COPY.exists(), reason="docs/RULES.md is made at publish, in the public clone only")
def test_the_published_copy_reads_as_the_copy():
    """No name check here: in a clone `id -F` names whoever runs the tests, whose first name may be a word in the rules
    (Claude, Will); the publish scan and the clone's hook guard the copy's names."""
    text = COPY.read_text()
    assert text.splitlines()[0] == "# Super Router rules"
    assert text.splitlines()[2].endswith(rules_copy.VERSION_TAIL)
    assert "## Changes from" not in text
