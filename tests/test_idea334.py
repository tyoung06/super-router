"""Build brief 33.4, I (decisions 7, 8, 9, 9b and 15): a `--no-files` card, told from its files record alone, offers Save as
SPEC.md while the project has none; no Plan from #n on it; once the spec exists its first chip is Plan the project (no
`--from`), What now? rung 4 shows it. `idea_max` is served in status; the plural reads "(1 file)". Every value is fake."""
import pytest

from router import filecalls, jsonview, log, nextsteps, plan, settings, spec, whatnow
from tests.test_filemode_flow import conn, project, runner  # noqa: F401 (fixtures)

READ_ONLY = {"mode": "on", "read_only": True, "state": "none", "copy": False, "changed": [], "why": filecalls.READ_ONLY_WHY}
NO_GIT = {"mode": "off", "state": "none", "copy": False, "why": f"{spec.TEXT_ONLY}; no read-only copy: no git"}
PLAIN = {"mode": "on", "state": "none", "copy": False, "changed": []}
OFF = {"mode": "off", "state": "none", "copy": False, "why": "no git"}


def _delivered(conn, files, text="Write SPEC.md for this project."):
    task_id = "sr-20261102-120000-abcd"
    log.add_task(conn, task_id, text, "ui", {"status": "ok", "label": "write", "confidence": 0.9, "tokens": 1}, project="garden")
    log.set_route(conn, task_id, agents=("claude", "chatgpt"), agent="claude", checker="chatgpt", route_reason="best",
                  skill="write", check_state="pending")
    log.add_call(conn, f"{task_id}-1", task_id, "do", "claude", status="done", text="# The spec")
    log.add_call(conn, f"{task_id}-c1", task_id, "check", "chatgpt", status="done", text="PASS", verdict="PASS")
    log.set_done(conn, task_id, "# The spec", check_state="passed")
    log.set_project_files(conn, task_id, files)
    return log.get_task(conn, task_id)


@pytest.mark.parametrize("files, want", [(READ_ONLY, True), (NO_GIT, True), (PLAIN, False), (OFF, False), (None, False)])
def test_text_only_comes_from_the_files_record(files, want):
    assert spec.is_text_only(files) is want


@pytest.mark.parametrize("files", [READ_ONLY, NO_GIT])
def test_save_as_spec_is_offered_on_both_records(project, conn, files):
    row = _delivered(conn, files)
    found = jsonview.notes_offers(conn, row, jsonview.state_of(conn, row))
    assert found["text_only"] is True and found["save_spec"] == {"path": "SPEC.md"}


def test_it_is_never_detected_from_the_text(project, conn):
    row = _delivered(conn, PLAIN, text=__import__("router.projspec", fromlist=["x"]).DRAFT_TEXT)
    found = jsonview.notes_offers(conn, row, jsonview.state_of(conn, row))
    assert found["text_only"] is False and found["save_spec"] is None


def test_it_goes_once_the_spec_exists_and_save_to_project_stays(project, conn):
    row = _delivered(conn, READ_ONLY)
    (project / "SPEC.md").write_text("# Spec\n")
    found = jsonview.notes_offers(conn, row, jsonview.state_of(conn, row))
    assert found["save_spec"] is None and found["text_only"] is True and found["card_actions"]["save"] is True


def _kinds(conn, row):
    return [c["kind"] for c in nextsteps.chips(conn, row)]


def test_no_plan_from_on_a_draft_before_the_spec(project, conn):
    row = _delivered(conn, READ_ONLY)
    assert "plan_from" not in _kinds(conn, row) and "plan_project" not in _kinds(conn, row)


def test_plan_the_project_comes_first_once_the_spec_is_saved(project, conn):
    row = _delivered(conn, READ_ONLY)
    (project / "SPEC.md").write_text("# Spec\n")
    chips = nextsteps.chips(conn, row)
    assert chips[0]["kind"] == "plan_project" and chips[0]["words"] == "Plan the project"
    fill = chips[0]["fill"]
    assert (fill["team"], fill["project"], fill["text"], fill["from"]) == ("plan", "garden", "Plan this project from SPEC.md.", None)
    assert "plan_from" not in [c["kind"] for c in chips]


def test_what_now_rung_4_shows_it(project, conn):
    row = _delivered(conn, READ_ONLY)
    (project / "SPEC.md").write_text("# Spec\n")
    line = whatnow.for_project(conn, "garden")
    assert (line["rung"], line["words"], line["chip"]["kind"]) == (4, "Next: Plan the project", "plan_project")


def test_plan_the_project_shows_whatever_jev_labelled_the_draft(project, conn):
    row = _delivered(conn, READ_ONLY)
    conn.execute("UPDATE tasks SET skill = 'quick_answer' WHERE task_id = ?", (row["task_id"],))
    (project / "SPEC.md").write_text("# Spec\n")
    assert _kinds(conn, log.get_task(conn, row["task_id"]))[0] == "plan_project"


def test_every_other_card_keeps_plan_from(project, conn):
    row = _delivered(conn, PLAIN)
    (project / "SPEC.md").write_text("# Spec\n")
    assert _kinds(conn, row)[0] == "plan_from"


def test_the_plural_reads_one_file():
    base = {"mode": "on", "base": "a" * 40, "branch": "main", "left_out": [], "files": 1}
    assert "(1 file)" in filecalls.start_words("garden", {**base, "read_only": True})
    assert "(1 file)" in filecalls.start_words("garden", base)
    assert "(2 files)" in filecalls.start_words("garden", {**base, "files": 2})


def test_the_two_settings_have_their_defaults():
    assert settings.NEXT_STEPS_DEFAULTS["idea_max"] == 2000 and settings.NEXT_STEPS_DEFAULTS["suggest_ideas_chars"] == 6000
    assert settings.next_steps_setting("idea_max")[0] == 2000
