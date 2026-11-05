"""Build brief 33.4, Q3 (decisions 6 and 6b): where the answers live. While the plan runs, one labeled data block on every later
call. At Approve, in the plan's own land commit: docs/PLAN.md's "Decided before planning" and the notes' one section, "Current
plan's decisions", replaced by each new plan, cleared by one with no questions, kept by a revision, put back by Undo from
the stored copy. Reject, discard or fail write nothing. Real git in temp folders, fake agents; every value is fake."""
import json
import subprocess

from router import log, plan, plansection, projects, projnotes
from tests.test_answers334 import _answer, _asked
from tests.test_filemode_flow import conn, project, runner  # noqa: F401 (fixtures)
from tests.test_plan_approval import _land
from tests.test_plan_chain import ReadWorker, World

SECTION = "## Current plan's decisions"
ANSWER = "Which units come after temperature?"


def _git(folder, *words):
    return subprocess.run(["git", "-C", str(folder), *words], capture_output=True, text=True, check=True).stdout


def _answered(conn, **kw):
    w, row = _asked(conn)
    code, said, row = _answer(w, conn, row, **(kw or {"picks": ["1=B"], "others": ["2=with flags"]}))
    assert code == 0, said
    return w, row


def _commits(folder):
    return int(_git(folder, "rev-list", "--count", "HEAD"))


def test_every_later_call_carries_the_answers_block(project, conn, runner):
    w, row = _answered(conn)
    prompts = [c["prompt"] for c in w.worker.calls[1:]] + w.chat.prompts + w.cursor.prompts
    assert len(prompts) == 5  # the answers call, the revise, the attack, the check, the second attack
    for prompt in prompts:
        assert f"===== {plan.ANSWERS_LABEL} =====" in prompt and "Answer: Weight" in prompt
        assert "with flags (the person's own words)" in prompt
    assert plan.ANSWERS_LABEL not in w.worker.calls[0]["prompt"]
    assert plan.ANSWERED_LINE in w.worker.calls[1]["prompt"] and plan.QUESTIONS_LINE not in w.worker.calls[1]["prompt"]
    kept = [log.context_of(c) for c in log.calls_for(conn, row["task_id"]) if c["kind"] != "questions"]
    assert all(plan.ANSWERS_LABEL in k["answers"]["text"] for k in kept)


def test_the_guesses_ride_as_the_answers(project, conn, runner):
    w, row = _answered(conn, best_guess=True)
    assert "Answer: Length (the planner's guess, which the person took)" in w.worker.calls[1]["prompt"]


def test_approve_writes_both_homes_in_its_one_commit_and_leaves_nothing_dirty(project, conn, runner):
    w, row = _answered(conn)
    before = _commits(project)
    code, said = _land(conn, row)
    assert code == 0, said
    assert _commits(project) == before + 1
    assert _git(project, "status", "--porcelain") == ""
    md = (project / plan.FILE).read_text()
    assert f"## {plan.DECIDED_TITLE}" in md and f"- {ANSWER}\n  - Answer: Weight" in md
    assert "with flags (the person's own words)" in md
    notes = projnotes.parts_of(projects.read_handoff(project)).notes
    assert SECTION in notes and f"{ANSWER} **Weight**" in notes
    assert notes.count(SECTION) == 1


def test_the_next_new_plan_replaces_the_section_never_appends(project, conn, runner):
    w, row = _answered(conn)
    assert _land(conn, row)[0] == 0
    assert _land(conn, log.get_task(conn, row["task_id"]), verb="undo")[0] == 0
    w2, row2 = _answered(conn, best_guess=True)
    assert _land(conn, row2)[0] == 0
    notes = projnotes.parts_of(projects.read_handoff(project)).notes
    assert notes.count(SECTION) == 1 and "**Length** (the planner's guess)" in notes and "Weight" not in notes


def test_a_new_plan_with_no_questions_clears_it(project, conn, runner):
    (project / "HANDOFF.md").write_text(plansection.replaced(projects.read_handoff(project), f"{SECTION}\n\nmarker"))
    _git(project, "add", "HANDOFF.md")
    _git(project, "commit", "-qm", "notes")
    w = World()
    code, row = w.plan(conn)
    assert _land(conn, log.get_task(conn, row["task_id"]))[0] == 0
    assert SECTION not in projects.read_handoff(project)
    assert f"## {plan.DECIDED_TITLE}" not in (project / plan.FILE).read_text()


def test_undo_puts_the_section_back_from_the_stored_copy_not_empty(project, conn, runner):
    (project / "HANDOFF.md").write_text(plansection.replaced(projects.read_handoff(project), f"{SECTION}\n\nmarker line"))
    _git(project, "add", "HANDOFF.md")
    _git(project, "commit", "-qm", "notes")
    w, row = _answered(conn)
    assert _land(conn, row)[0] == 0
    assert "marker line" not in projects.read_handoff(project)
    assert _land(conn, log.get_task(conn, row["task_id"]), verb="undo")[0] == 0
    assert plansection.read(projects.read_handoff(project)) == f"{SECTION}\n\nmarker line"
    assert _git(project, "status", "--porcelain") == ""


def test_undo_with_nothing_before_removes_the_section(project, conn, runner):
    w, row = _answered(conn)
    assert _land(conn, row)[0] == 0
    assert _land(conn, log.get_task(conn, row["task_id"]), verb="undo")[0] == 0
    assert SECTION not in projects.read_handoff(project)


def test_reject_and_cancel_and_failure_write_nothing(project, conn, runner):
    before = projects.read_handoff(project)
    w, row = _answered(conn)
    assert _land(conn, row, verb="discard")[0] == 0
    assert SECTION not in projects.read_handoff(project)
    assert plan.record_of(log.get_task(conn, row["task_id"]))["answers"]  # kept for good in the log
    assert before.split("<!--")[0] == projects.read_handoff(project).split("<!--")[0]


def test_cancel_writes_nothing_to_the_notes(project, conn, runner):
    from router import __main__ as cli
    before = projects.read_handoff(project)
    w, row = _asked(conn)
    assert cli.cmd_cancel(conn=conn, words=[str(row["n"])], out=lambda line: None) == 0
    assert projects.read_handoff(project) == before


def test_a_failed_plan_writes_nothing_to_the_notes(project, conn, runner):
    from tests.test_questions334 import QUESTIONS
    w, row = _asked(conn, QUESTIONS, QUESTIONS)
    code, said, row = _answer(w, conn, row, best_guess=True)
    assert row["status"] == "failed" and SECTION not in projects.read_handoff(project), said


def test_a_pin_after_the_section_survives_the_next_plan(project, conn, runner):
    w, row = _answered(conn)
    assert _land(conn, row)[0] == 0
    text = projects.read_handoff(project)
    pinned = plansection.replaced(text, plansection.read(text) + "\n\n### Pinned from #1 (2026-11-03)\nkeep me")
    assert plansection.read(pinned).endswith("keep me") is False
    (project / "HANDOFF.md").write_text(pinned)
    assert _git(project, "add", "HANDOFF.md") == ""
    _git(project, "commit", "-qm", "pin")
    assert _land(conn, log.get_task(conn, row["task_id"]), verb="undo")[0] == 0
    assert "keep me" in projects.read_handoff(project)


def test_a_new_plan_after_all_steps_are_done_may_ask(project, conn, runner, monkeypatch):
    monkeypatch.setattr(plan, "first_open", lambda *a, **k: None)
    w, row = _answered(conn)
    assert _land(conn, row)[0] == 0
    w2 = World(worker=ReadWorker(__import__("tests.test_questions334", fromlist=["QUESTIONS"]).QUESTIONS))
    code, second = w2.plan(conn)
    second = log.get_task(conn, second["task_id"])
    assert second["check_note"] == log.AWAITING_ANSWERS and plan.inherited_of(plan.record_of(second)) is None, w2.said


def test_add_to_plan_with_open_steps_never_asks(project, conn, runner):
    from router import ideas
    from tests.test_questions334 import QUESTIONS
    from tests.test_revise332 import REV, REV_ANSWERED, _first_plan
    _first_plan(conn, project)
    idea, _ = ideas.add(conn, "garden", "an idea")
    w = World(worker=ReadWorker(QUESTIONS, REV, REV_ANSWERED))
    code, row = w.plan(conn, idea_ref=str(idea.id))
    row = log.get_task(conn, row["task_id"])
    assert plan.QUESTIONS_LINE not in w.worker.calls[0]["prompt"] and log.project_files_of(row)["state"] == "waiting", w.said


def test_questions_are_read_on_a_plan_alone():
    from router import __main__ as cli
    task = {"mode": "route", "status": "queued"}
    assert cli._questions_answer(task, []) is None


def test_a_revision_never_asks_keeps_the_section_and_carries_decided_over(project, conn, runner):
    from router.__main__ import cmd_plan  # noqa: F401
    from tests.test_plan_steps import RESEARCH, _route_step
    from tests.test_filemode_flow import CopyWorker
    from tests.test_revise332 import NO_NEEDS, REVISED_NO_NEEDS, _revise
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    from tests.test_questions334 import QUESTIONS
    w = World(worker=ReadWorker(QUESTIONS, NO_NEEDS, REVISED_NO_NEEDS))
    code, row = w.plan(conn)
    code, said, row = _answer(w, conn, log.get_task(conn, row["task_id"]), best_guess=True)
    assert code == 0, said
    assert _land(conn, row)[0] == 0
    section = plansection.read(projects.read_handoff(project))
    found = log.get_task(conn, row["task_id"])
    code, said, step = _route_step(conn, f"{found['n']}:1", worker=CopyWorker(RESEARCH))
    assert code == 0, said
    code, rev, w2 = _revise(conn)
    assert code == 0, w2.said
    assert plan.QUESTIONS_LINE not in w2.worker.calls[0]["prompt"]
    assert plan.record_of(rev).get("questions") is None
    assert _land(conn, rev)[0] == 0
    assert plansection.read(projects.read_handoff(project)) == section
    assert f"## {plan.DECIDED_TITLE}" in (project / plan.FILE).read_text()
    assert _land(conn, log.get_task(conn, rev["task_id"]), verb="undo")[0] == 0
    assert plansection.read(projects.read_handoff(project)) == section


def test_a_revision_returning_questions_is_a_contract_miss(project, conn, runner):
    from tests.test_questions334 import QUESTIONS
    from tests.test_revise332 import REV, REV_ANSWERED, _first_plan, _revise
    _first_plan(conn, project)
    code, rev, w = _revise(conn, worker=ReadWorker(QUESTIONS, REV, REV_ANSWERED))
    assert code == 0, w.said
    assert "not allowed on a revision" in w.worker.calls[1]["prompt"]
    assert log.project_files_of(rev)["state"] == "waiting"


def test_add_to_plan_with_no_current_plan_may_ask(project, conn, runner):
    from router import ideas
    from tests.test_questions334 import QUESTIONS
    idea, _ = ideas.add(conn, "garden", "an idea")
    w = World(worker=ReadWorker(QUESTIONS))
    code, row = w.plan(conn, idea_ref=str(idea.id))
    assert log.get_task(conn, row["task_id"])["check_note"] == log.AWAITING_ANSWERS, w.said


def test_the_hand_edit_line_shows_only_when_the_section_differs(project, conn, runner):
    w = World()
    code, row = w.plan(conn)
    row = log.get_task(conn, row["task_id"])
    assert plan.section_edited(conn, row) is False  # no section at all
    (project / "HANDOFF.md").write_text(plansection.replaced(projects.read_handoff(project), f"{SECTION}\n\nmine"))
    assert plan.section_edited(conn, row) is True  # a section the router never wrote
    assert plan.view(conn, row)["section_edited"] is True
    _git(project, "add", "HANDOFF.md")
    _git(project, "commit", "-qm", "notes")
    assert _land(conn, row)[0] == 0
    assert _land(conn, log.get_task(conn, row["task_id"]), verb="undo")[0] == 0
    w2 = World()
    code, row2 = w2.plan(conn)
    row2 = log.get_task(conn, row2["task_id"])
    assert plan.section_edited(conn, row2) is True  # Cleanup 2, row 6: Undo put your own words back, and the next plan would replace them
    (project / "HANDOFF.md").write_text(plansection.replaced(projects.read_handoff(project), f"{SECTION}\n\nedited again"))
    assert plan.section_edited(conn, row2) is True


def test_the_rest_of_the_notes_and_the_block_stay_byte_for_byte():
    block = f"{projects.START}\n### #1 · x\n{projects.END}\n"
    text = f"# Mine\n\nfirst\n\n## Later part\n\nkept\n\n{block}"
    added = plansection.replaced(text, f"{SECTION}\n\n- a")
    assert added.startswith("# Mine\n\nfirst\n\n## Later part\n\nkept\n\n## Current plan") and added.endswith(block)
    assert plansection.replaced(added, None) == text
    middle = f"# Mine\n\n{SECTION}\n\nold\n\n## Later part\n\nkept\n\n{block}"
    assert plansection.replaced(middle, f"{SECTION}\n\nnew") == f"# Mine\n\n{SECTION}\n\nnew\n\n## Later part\n\nkept\n\n{block}"
    assert plansection.replaced(middle, None) == f"# Mine\n\n## Later part\n\nkept\n\n{block}"
    assert plansection.read(middle) == f"{SECTION}\n\nold"
    assert plansection.replaced("".join(block), None) == block


# ---------- Cleanup 2, row 6 (item 4): Approve warns about your own words after an Undo ----------

def _commit_notes(project, words):
    (project / "HANDOFF.md").write_text(plansection.replaced(projects.read_handoff(project), f"{SECTION}\n\n{words}"))
    _git(project, "add", "HANDOFF.md")
    _git(project, "commit", "-qm", "notes")


def _next_plan(conn):
    code, row = World().plan(conn)
    return log.get_task(conn, row["task_id"])


def _fake_plan(task_id, state, written, before=None):
    """A plan's row as the walk reads it, newest first in the list: a second landed plan is only a new plan once the first has
    no open step, so these rows stand in for that long road."""
    return {"task_id": task_id, "mode": "plan", "project": "garden", "project_files": json.dumps({"state": state}),
            "plan": json.dumps({"section_written": plansection.digest(written), "section_before": before})}


def _walks(monkeypatch, project, notes_words, rows):
    (project / "HANDOFF.md").write_text(plansection.replaced(projects.read_handoff(project), notes_words))
    monkeypatch.setattr(log, "project_tasks", lambda conn, name: rows)
    now = {"task_id": "now", "mode": "plan", "project": "garden", "project_files": None, "plan": json.dumps({})}
    return plan.section_edited(None, now)


def test_hand_written_land_undo_then_the_next_plan_warns(project, conn, runner):
    code, row = World().plan(conn)
    row = log.get_task(conn, row["task_id"])
    _commit_notes(project, "my own words")
    assert _land(conn, row)[0] == 0
    assert _land(conn, log.get_task(conn, row["task_id"]), verb="undo")[0] == 0
    assert "my own words" in projects.read_handoff(project)  # Undo put them back
    assert plan.section_edited(conn, _next_plan(conn)) is True


def test_a_lands_b_lands_b_undone_no_warning(monkeypatch, project):
    a = f"{SECTION}\n\nplan A's"
    rows = [_fake_plan("b", "undone", f"{SECTION}\n\nplan B's", before=a), _fake_plan("a", "landed", a)]
    assert _walks(monkeypatch, project, a, rows) is False  # the section is plan A's, which is the router's own


def test_a_lands_a_hand_edit_b_lands_b_undone_warns(monkeypatch, project):
    a, edited = f"{SECTION}\n\nplan A's", f"{SECTION}\n\nedited by hand"
    rows = [_fake_plan("b", "undone", f"{SECTION}\n\nplan B's", before=edited), _fake_plan("a", "landed", a)]
    assert _walks(monkeypatch, project, edited, rows) is True


def test_every_plan_undone_warns_since_no_plan_still_landed_wrote_it(monkeypatch, project):
    rows = [_fake_plan("a", "undone", f"{SECTION}\n\nplan A's", before=None)]
    assert _walks(monkeypatch, project, f"{SECTION}\n\nanything", rows) is True


# ---------- Cleanup 2, row 18 (item 3): a land past the notes limit says so and never fails ----------

def test_a_land_that_takes_the_notes_past_the_limit_goes_through_and_says_so(project, conn, runner, monkeypatch):
    w, row = _answered(conn)
    notes = projnotes.parts_of(projects.read_handoff(project)).notes
    monkeypatch.setattr(projnotes, "max_chars", lambda: len(notes) + 5)  # just under it now; the section takes it over
    before = _commits(project)
    code, text = _land(conn, row)
    assert code == 0, text
    assert _commits(project) == before + 1
    assert "the notes are past their limit" in text and "trim them in Notes" in text


def test_a_land_under_the_limit_has_no_such_line(project, conn, runner):
    w, row = _answered(conn)
    code, text = _land(conn, row)
    assert code == 0, text
    assert "past their limit" not in text
