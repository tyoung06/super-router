"""Build brief 33.1, A (decisions 9 to 11): the plan waits to land. When the check ends the router keeps the plan on the
task row and writes docs/PLAN.md into the copy; Approve is Land, Reject is Discard, Approve anyway is Land anyway. The land
commits docs/PLAN.md and HANDOFF.md with the router's entry; a link at docs or docs/PLAN.md refuses it. Before Approve the
owner may change a step's text, team or done-when, move it or drop it (`sr plan --edit`), each edit checked by the
contract's rules, the needs renumbered, docs/PLAN.md rendered again, and logged beside the planner's version; never after.
The plan's own Undo is refused once a step has ticked. Real git in temp folders, fake agents; every value here is fake."""
import json
import os
from argparse import Namespace

import pytest

from router import __main__ as cli
from router import copies, gitops, landing, log, plan, projects
from tests.test_copies import git
from tests.test_filemode_flow import conn, project, runner  # noqa: F401 (fixtures)
from tests.test_plan_chain import A_LIST, REVISED, World
from tests.test_plan_contract import GOOD
from tests.test_relay import CONFIG, Chat


def _planned(conn, **kw):
    w = World(**kw)
    code, row = w.plan(conn)
    assert code in (0, 5), w.said
    return w, log.get_task(conn, row["task_id"])


def _land(conn, row, verb="land", anyway=False):
    lines = []
    code = cli.cmd_land([row["task_id"]], conn=conn, config=CONFIG, verb=verb, out=lines.append, anyway=anyway)
    return code, "\n".join(lines)


def _edit(conn, row, step, **change):
    args = Namespace(edit=row["task_id"], step=str(step), team=change.get("team"), text="text" in change,
                     done_when="done_when" in change, up=change.get("up", False), down=change.get("down", False),
                     drop=change.get("drop", False), task=[change.get("text") or change.get("done_when")]
                     if ("text" in change or "done_when" in change) else [])
    lines = []
    out = cli.receipt.Receipt()
    code = cli.cmd_plan_edit(args, conn=conn, config=CONFIG, roster=None, loaded=None, available=None, out=out)
    return code, out


# ---------- docs/PLAN.md in the copy (decision 9) ----------

def test_the_plan_is_kept_and_docs_plan_md_is_rendered_in_the_copy(project, conn, runner):
    w, row = _planned(conn)
    record = plan.record_of(row)
    assert record["planner"]["steps"] == record["steps"] and len(record["steps"]) == 2
    text = (copies.folder_of(row["task_id"]) / plan.FILE).read_text()
    assert text == plan.render(record, n=row["n"], date=plan.date_of(row))
    assert record["hash"] == plan.digest(text)
    assert log.project_files_of(row)["tests"]["why"] == plan.NO_TESTS


# ---------- Approve, Reject, Approve anyway (decision 9) ----------

def test_approve_lands_docs_plan_md_and_handoff_md_as_one_commit(project, conn, runner):
    w, row = _planned(conn)
    head = git(project, "rev-parse", "HEAD").decode().strip()
    code, said = _land(conn, row)
    assert code == 0, said
    new = git(project, "rev-parse", "HEAD").decode().strip()
    assert git(project, "rev-parse", "HEAD^").decode().strip() == head  # one commit
    names = git(project, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").decode().split()
    assert sorted(names) == ["HANDOFF.md", plan.FILE]
    assert (project / plan.FILE).read_text() == (plan.render(plan.record_of(row), n=row["n"], date=plan.date_of(row)))
    assert git(project, "status", "--porcelain").decode().strip() == ""
    handoff = projects.read_handoff(project)
    entry = handoff.split(f"### #{row['n']} ·", 1)[1]
    assert "· plan · claude · landed" in entry.splitlines()[0]
    assert "Produced:\ndocs/PLAN.md (2 steps)" in entry and f"Status:\nplan #{row['n']} approved" in entry
    assert "Next:\nMake the skeleton: a cli.py that prints its help" in entry
    assert f"No tests ran: {plan.NO_TESTS}" in entry
    assert plan.current(conn, "garden")["task_id"] == row["task_id"]
    assert new != head


def test_reject_is_discard_and_nothing_lands(project, conn, runner):
    w, row = _planned(conn)
    head = git(project, "rev-parse", "HEAD").decode().strip()
    code, said = _land(conn, row, verb="discard")
    assert code == 0 and git(project, "rev-parse", "HEAD~1").decode().strip() == head  # Cleanup 1 (2.5): the entry's commit,
    assert git(project, "show", "--name-only", "--format=", "HEAD").decode().split() == ["HANDOFF.md"]  # and nothing else
    assert not copies.exists(row["task_id"]) and plan.current(conn, "garden") is None


def test_approve_anyway_lands_a_plan_whose_check_failed(project, conn, runner):
    chat = Chat(A_LIST, "FIX\n1. [must] step 2 names no file", "FIX\n1. not fixed: still no file")
    w = World(chat=chat)
    w.worker.replies.append(REVISED)
    code, row = w.plan(conn)
    row = log.get_task(conn, row["task_id"])
    assert code == 5 and row["check_state"] == "failed"
    assert (copies.folder_of(row["task_id"]) / plan.FILE).exists()  # written after a failed check too
    assert _land(conn, row)[0] == 2  # Approve is refused after a failed check
    code, said = _land(conn, row, anyway=True)
    assert code == 0, said and "its check didn't pass" in said
    assert (project / plan.FILE).exists()


@pytest.mark.parametrize("link", ["docs", plan.FILE])
def test_a_link_at_docs_or_docs_plan_md_refuses_the_land_by_name(project, conn, runner, tmp_path, link):
    w, row = _planned(conn)
    target = tmp_path / "elsewhere"
    target.mkdir()
    (project / "docs").parent.mkdir(exist_ok=True)
    if link == "docs":
        os.symlink(target, project / "docs")
    else:
        (project / "docs").mkdir()
        os.symlink(target / "PLAN.md", project / plan.FILE)
    code, said = _land(conn, row)
    assert code == 2 and f"{link} in the folder is a link" in said and "the router never writes through a link" in said


# ---------- the edits (decision 11) ----------

def test_an_edit_changes_the_step_renders_again_and_is_logged(project, conn, runner):
    w, row = _planned(conn)
    code, out = _edit(conn, row, 2, text="Add the conversion and its test in convert.py.")
    assert code == 0, out.message
    row = log.get_task(conn, row["task_id"])
    record = plan.record_of(row)
    assert record["steps"][1]["text"] == "Add the conversion and its test in convert.py."
    assert record["planner"]["steps"][1]["text"].startswith("Add the Celsius")
    assert record["edits"][-1]["change"] == "text" and record["edits"][-1]["step"] == 2
    text = (copies.folder_of(row["task_id"]) / plan.FILE).read_text()
    assert "**Step 2.** Add the conversion and its test in convert.py." in text and record["hash"] == plan.digest(text)
    assert log.project_files_of(row)["state"] == "waiting"


def test_a_move_and_a_drop_renumber_the_needs_and_render_again(project, conn, runner):
    w, row = _planned(conn)
    assert _edit(conn, row, 2, up=True)[0] == 0
    record = plan.record_of(log.get_task(conn, row["task_id"]))
    assert record["steps"][0]["team"] == "redteam" and [n["step"] for n in record["needs"]][:3] == [1, 1, 1]
    assert _edit(conn, row, 1, drop=True)[0] == 0
    record = plan.record_of(log.get_task(conn, row["task_id"]))
    assert len(record["steps"]) == 1 and [n["step"] for n in record["needs"]][:3] == [None, None, None]
    text = (copies.folder_of(row["task_id"]) / plan.FILE).read_text()
    assert "0 of 1 steps done" in text  # decision 15: "<d> of <m> steps done"


@pytest.mark.parametrize("change, words", [
    (dict(team="vote"), "vote is not a team a step can take now"),
    (dict(text="@claude do it"), "starts with @ or /"),
    (dict(done_when="d" * 300), "has 300 characters"),
])
def test_an_edit_that_breaks_the_contract_is_refused_and_writes_nothing(project, conn, runner, change, words):
    w, row = _planned(conn)
    before = log.get_task(conn, row["task_id"])["plan"]
    code, out = _edit(conn, row, 2, **change)
    assert code == 2 and words in out.message and log.get_task(conn, row["task_id"])["plan"] == before


def test_one_change_per_command(project, conn, runner):
    w, row = _planned(conn)
    code, out = _edit(conn, row, 2, up=True, drop=True)
    assert code == 2 and out.code == "usage"


def test_no_edit_after_the_land(project, conn, runner):
    w, row = _planned(conn)
    assert _land(conn, row)[0] == 0
    code, out = _edit(conn, row, 1, drop=True)
    assert code == 2 and out.code == "wrong_state" and "a landed plan changes only by its ticks" in out.message


# ---------- the plan's own Undo (decision 9) ----------

def test_the_plans_own_undo_before_any_tick_and_the_plan_is_no_longer_current(project, conn, runner):
    w, row = _planned(conn)
    assert _land(conn, row)[0] == 0
    code, said = _land(conn, row, verb="undo")
    assert code == 0, said
    assert not (project / plan.FILE).exists() and plan.current(conn, "garden") is None
