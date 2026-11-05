"""Cleanup 1 (2.2): a result saved as `SPEC.md` leaves its `## Missing` section out, since the spec rides on every prompt
after it. Only that exact path, and never when a heading follows the section (`split_missing` takes everything to the
end, so the spec's own sections would go with it). Fakes only; no model call."""
import json

import pytest

from router import __main__ as cli
from router import log, projnotes
from tests.test_project_notes import _task, git, gitted, registry, run  # noqa: F401 (the fixture)

BODY = "# Trays\n\nThe app sizes seed trays.\n\n## Done when\n1. It prints a size.\n"
MISSING = "## Missing\nThe spec still needs to be saved.\n"


def _save(tmp_path, capsys, result, path="SPEC.md", task="Draft the spec"):
    folder = gitted(tmp_path)
    conn = log.init_db(cli.DB_PATH)
    try:
        row = _task(conn, result=result)
        conn.execute("UPDATE tasks SET task = ? WHERE task_id = ?", (task, row["task_id"]))
        conn.commit()
    finally:
        conn.close()
    code, out = run(["project", "save", "garden", "--task", row["task_id"], "--path", path], capsys)
    assert code == 0, out
    return folder / path, out


def test_a_draft_ending_in_missing_saves_without_it(registry, tmp_path, capsys):
    saved, out = _save(tmp_path, capsys, f"{BODY}\n{MISSING}")
    assert saved.read_text() == BODY
    assert "## Missing section" in out and "left out" in out


def test_a_handoff_after_missing_is_gone_too_and_the_section_with_it(registry, tmp_path, capsys):
    saved, out = _save(tmp_path, capsys, f"{BODY}\n{MISSING}\n## Handoff\n### Produced\nx\n### Status\ny\n### Next\nz")
    assert saved.read_text() == BODY


@pytest.mark.parametrize("after", ["## Examples\n1. A tray of six.\n", "### Examples\n1. A tray of six.\n", "# More\nwords\n"])
def test_a_heading_after_missing_keeps_everything_and_says_so(registry, tmp_path, capsys, after):
    text = f"{BODY}\n{MISSING}\n{after}"
    saved, out = _save(tmp_path, capsys, text)
    assert saved.read_text() == text
    assert "## Missing" in out and "kept" in out and "left out" not in out


def test_a_heading_in_a_fence_inside_missing_is_no_heading(registry, tmp_path, capsys):
    saved, out = _save(tmp_path, capsys, f"{BODY}\n## Missing\nStill to do:\n```\n## Examples\n```\n")
    assert saved.read_text() == BODY


def test_two_missing_sections_keep_everything_and_say_so(registry, tmp_path, capsys):
    text = f"{MISSING}\n{BODY}\n{MISSING}"
    saved, out = _save(tmp_path, capsys, text)
    assert saved.read_text() == text and "kept" in out


def test_only_a_missing_section_is_kept_whole_rather_than_saved_empty(registry, tmp_path, capsys):
    saved, out = _save(tmp_path, capsys, MISSING)
    assert saved.read_text() == MISSING and "kept" in out


@pytest.mark.parametrize("path", ["docs/notes.md", "docs/SPEC.md", "spec-notes.md"])
def test_any_other_path_keeps_missing(registry, tmp_path, capsys, path):
    text = f"{BODY}\n{MISSING}"
    saved, out = _save(tmp_path, capsys, text, path=path)
    assert saved.read_text() == text and "## Missing" not in out


def test_no_heading_is_byte_for_byte_and_says_nothing(registry, tmp_path, capsys):
    saved, out = _save(tmp_path, capsys, BODY)
    assert saved.read_text() == BODY and "## Missing" not in out


def test_the_tasks_own_words_never_decide(registry, tmp_path, capsys):
    """The saved text comes from the delivered result; a `## Missing` in the task's own text changes nothing."""
    saved, out = _save(tmp_path, capsys, BODY, task=f"Draft it.\n{MISSING}")
    assert saved.read_text() == BODY and "## Missing" not in out


def test_the_scan_reads_what_is_saved_and_the_json_says_what_happened(registry, tmp_path, capsys):
    folder = gitted(tmp_path)
    conn = log.init_db(cli.DB_PATH)
    try:
        row = _task(conn, result=f"{BODY}\n{MISSING}")
    finally:
        conn.close()
    code, out = run(["project", "save", "garden", "--json", "--task", row["task_id"], "--path", "SPEC.md"], capsys)
    assert code == 0 and json.loads(out)["project"]["missing"] == "left_out"
    assert git(folder, "status", "--porcelain=v1").decode() == ""


def test_the_words_function_alone():
    assert projnotes.spec_text(BODY) == (BODY, None)
    assert projnotes.spec_text(f"{BODY}\n{MISSING}") == (BODY, projnotes.MISSING_LEFT_OUT)
    whole = f"{BODY}\n{MISSING}\n## Examples\n1. x\n"
    assert projnotes.spec_text(whole) == (whole, projnotes.MISSING_KEPT)
