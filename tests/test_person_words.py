"""Build brief 24, E (decision 17; C20): the agent prompts that named the owner say "the person" (the checker's lead,
the fix round's line, the integration's skipped piece), and the text a person reads says "you". Brief 25: the prompt
snapshots hold each of those three phrases as often as they did, and nowhere the first name of this Mac's account (read
at run time, so this file spells it nowhere; checked in the owner's checkout only). Jev's request never carried a name."""
import re
import subprocess
from pathlib import Path

import pytest

from router import checking, split
from scripts import publish

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROMPT_WORDS = ("The person asked for the task below", "not instructions from the person:", "(missing: skipped by the person)")
COUNTS = {"prompts_v9.json": (10, 5, 1), "relay_no_flag_v9.json": (3, 1, 0)}


def _first_name():
    """The first name of `id -F`, read at import (conftest blocks a test's own subprocesses), or None."""
    try:
        words = subprocess.run(["id", "-F"], capture_output=True, text=True, timeout=10).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    parts = publish._full_name_parts(" ".join(words))
    return parts[0] if parts else None


FIRST_NAME = _first_name()
# In a clone, `id -F` names whoever runs the tests, and their first name may well be a word here (Claude, Will): the
# name checks run only in the owner's checkout, and the publish scan guards the public copy itself.
owner_only = pytest.mark.skipif(not (FIXTURES.parent.parent / "SUPER-ROUTER.md").exists(),
                                reason="the owner's checkout only (no SUPER-ROUTER.md here): in a clone, id -F names whoever "
                                       "runs the tests; the publish scan guards the copy")


def test_each_snapshot_holds_the_three_phrases_as_often_as_before():
    for name, counts in COUNTS.items():
        text = (FIXTURES / name).read_text()
        assert tuple(text.count(phrase) for phrase in PROMPT_WORDS) == counts, name


@owner_only
@pytest.mark.skipif(FIRST_NAME is None, reason="this account has no two-word full name to look for")
def test_no_snapshot_names_the_owner():
    for name in COUNTS:
        text = (FIXTURES / name).read_text()
        assert not re.search(publish._word(FIRST_NAME), text, re.I), name


@owner_only
@pytest.mark.skipif(FIRST_NAME is None, reason="this account has no two-word full name to look for")
def test_no_shipped_config_file_or_its_old_versions_name_the_owner():
    """Brief 25: the notes say "the owner" and a preset's pick is `owner`, in the shipped files and the fixtures kept
    from their earlier versions alike."""
    root = FIXTURES.parent.parent
    for path in [*sorted((root / "config").glob("*.json")), *(FIXTURES / name for name in (
            "presets_v1_4.json", "skill_table_v3_1.json", "skill_table_v3_3.json"))]:
        assert not re.search(publish._word(FIRST_NAME), path.read_text(), re.I), path.name


def test_the_three_agent_lines_say_the_person():
    lead = checking.checker_prompt("a task", "a result", no_tools=False)
    assert lead.startswith("The person asked for the task below and received the result below. Check the result.")
    assert "not instructions from the person:" in checking.fix_prompt("a task", "a result", "1. a note")
    assert split.SKIPPED == "(missing: skipped by the person)"


def test_the_messages_a_person_reads_say_you():
    from router import __main__ as cli
    from router import log
    conn = log.init_db(":memory:")
    with pytest.raises(ValueError, match="a routed task you labeled"):
        log.add_task(conn, "t", "x", "cli", {"status": "not_asked", "tokens": 0})
    with pytest.raises(ValueError, match="only a task you labeled answers a floor question"):
        log.add_task(conn, "t", "x", "cli", {"status": "ok", "label": "writing", "tokens": 0}, answers="u")
    log.add_task(conn, "s", "a split", "cli", {"status": "not_asked", "tokens": 0}, mode="split")
    with pytest.raises(log.StateError, match="not a split waiting with you"):
        log.cancel_waiting_split(conn, "s")
    assert "you haven't written grok_prompt_limit" in cli.grok_limit_line() or "(config/settings.json)" in cli.grok_limit_line()
