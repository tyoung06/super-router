"""Build brief 33.1, S (decisions 12 to 15): Build step k. `--step <plan task>:<k>` on `sr route` or `sr relay` runs the
current plan's first open step as a task of its team, refused at intake (`bad_step`) otherwise. Every call gets the STEP
block; the check and the re-check the finish-line line. A build's change to docs/PLAN.md is put back. A step is done when
its task landed and wasn't undone, or was delivered with no change: derived from the rows. The land commits docs/PLAN.md
with the tick; a delivery with no change gets its own commit; Undo writes docs/PLAN.md again with the step open. When
docs/PLAN.md isn't what the router last wrote: uncommitted edits leave it out (the tick counts), an outside commit is
written over, a link is left out. Real git in temp folders, fake agents; every value here is fake."""
import os

import pytest

from router import __main__ as cli
from router import copies, log, plan, projects
from tests.helpers import fake_label
from tests.test_copies import git
from tests.test_filemode_flow import CODE, CopyWorker, conn, project, runner  # noqa: F401 (fixtures)
from tests.test_handoff_contract import HANDOFF
from tests.test_loop import Clock, Webhook
from tests.test_plan_approval import _land, _planned
from tests.test_relay import CONFIG, ROSTER, Chat

SKELETON = ("Made the skeleton.\n\n## Handoff\n### Produced\ncli.py and test_cli.py added\n### Status\nruns\n### Next\n"
            "step 2", {"cli.py": "print('help')\n", "test_cli.py": "import unittest\n"})
RESEARCH = ("The conversion is F = C * 9/5 + 32.\n\n## Handoff\n### Produced\nnothing written: the conversion rule\n"
            "### Status\nfound\n### Next\nstep 2", {})


def _approved(conn):
    w, row = _planned(conn)
    assert _land(conn, row)[0] == 0
    return log.get_task(conn, row["task_id"])


def _route_step(conn, step, *, worker, chatgpt=None, task=None, project_name="garden", jev=CODE):
    lines, clock, hook = [], Clock(), Webhook()
    code = cli.cmd_route(task or "Make the skeleton.", conn=conn, config=CONFIG, roster=ROSTER, environ={},
                         settings_paths=[], label=fake_label(jev), post=hook.post, worker=worker,
                         chatgpt=chatgpt or Chat("PASS"), codex_login=lambda: True, fetch=hook.fetch, close=hook.close,
                         sleep=clock.sleep, clock=clock, wait=True, out=lines.append, project=project_name,
                         files_ready=lambda: (True, None), step_ref=step)
    rows = log.recent_tasks(conn)
    return code, "\n".join(lines), rows[0] if rows else None


# ---------- --step at intake (decision 12) ----------

def test_a_step_runs_as_its_team_and_its_row_records_the_plan_and_the_step(project, conn, runner):
    found = _approved(conn)
    code, said, row = _route_step(conn, f"{found['n']}:1", worker=CopyWorker(SKELETON))
    assert code == 0, said
    assert log.plan_step_of(row) == {"plan": found["task_id"], "step": 1}
    assert row["project"] == "garden" and log.project_files_of(row)["state"] == "waiting"


@pytest.mark.parametrize("ref, words", [
    ("{n}:2", "step 2 isn't plan #{n}'s next step: step 1 is"),
    ("{n}:9", "plan #{n} has no step 9"),
    ("{n}", "--step takes <plan task>:<step>"),
    ("99:1", "No task #99"),
])
def test_a_step_that_isnt_the_first_open_one_is_refused_before_jev(project, conn, runner, ref, words):
    found = _approved(conn)
    label = fake_label(CODE)
    lines, clock, hook = [], Clock(), Webhook()
    code = cli.cmd_route("x", conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=label,
                         post=hook.post, worker=CopyWorker(), chatgpt=Chat("PASS"), codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True, out=lines.append,
                         project="garden", files_ready=lambda: (True, None), step_ref=ref.format(n=found["n"]))
    assert code == 2 and label.calls == [] and log.recent_tasks(conn)[0]["task_id"] == found["task_id"]
    assert words.format(n=found["n"]) in "\n".join(lines)


def test_a_plan_no_longer_current_is_refused(project, conn, runner):
    found = _approved(conn)
    assert _land(conn, found, verb="undo")[0] == 0
    code, said, row = _route_step(conn, f"{found['n']}:1", worker=CopyWorker(SKELETON))
    assert code == 2 and f"plan #{found['n']} is no longer the project's current plan" in said


def test_a_step_on_another_project_is_refused(project, conn, runner, tmp_path):
    found = _approved(conn)
    code, said, row = _route_step(conn, f"{found['n']}:1", worker=CopyWorker(SKELETON), project_name=None)
    assert code == 2 and f"step 1 of plan #{found['n']} belongs to garden" in said


# ---------- the STEP block and the check line (decision 13) ----------

def test_every_call_of_a_step_gets_the_step_block_and_the_check_the_finish_line(project, conn, runner):
    found = _approved(conn)
    worker, chat = CopyWorker(SKELETON), Chat("PASS")
    code, said, row = _route_step(conn, f"{found['n']}:1", worker=worker, chatgpt=chat)
    done_when = plan.record_of(found)["steps"][0]["done_when"]
    block = (f"This task is step 1 of the project's plan (docs/PLAN.md, plan #{found['n']}). Its finish line: "
             f"{done_when}. docs/PLAN.md is the router's: don't change it.")
    assert block in worker.calls[0]["prompt"] and block in chat.prompts[0]
    assert plan.STEP_CHECK_LINE in chat.prompts[0] and plan.STEP_CHECK_LINE not in worker.calls[0]["prompt"]


def test_a_builds_change_to_docs_plan_md_is_put_back_and_said(project, conn, runner):
    found = _approved(conn)
    rogue = (SKELETON[0], {**SKELETON[1], plan.FILE: "# my own plan\n"})
    code, said, row = _route_step(conn, f"{found['n']}:1", worker=CopyWorker(rogue))
    record = log.project_files_of(row)
    assert plan.FILE not in [c["path"] for c in record["changed"]] and record.get("plan_md_restored") is True
    assert "docs/PLAN.md was changed by the build; the router put it back" in said


# ---------- ticks (decision 14) ----------

def test_a_steps_land_ticks_it_in_the_same_commit(project, conn, runner):
    found = _approved(conn)
    code, said, row = _route_step(conn, f"{found['n']}:1", worker=CopyWorker(SKELETON))
    code, said = _land(conn, row)
    assert code == 0, said
    names = sorted(git(project, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").decode().split())
    assert names == ["HANDOFF.md", "cli.py", plan.FILE, "test_cli.py"]
    text = (project / plan.FILE).read_text()
    assert f"- [x] **Step 1.**" in text and f"  - Done by #{row['n']}" in text and "1 of 2 steps done" in text
    assert plan.first_open(conn, found)[0] == 2


def test_a_delivery_with_no_change_ticks_in_its_own_commit(project, conn, runner):
    found = _approved(conn)
    head = git(project, "rev-parse", "HEAD").decode().strip()
    code, said, row = _route_step(conn, f"{found['n']}:1", worker=CopyWorker(RESEARCH))
    assert code == 0, said
    assert git(project, "rev-parse", "HEAD~2").decode().strip() == head  # Cleanup 1 (2.5): the entry's commit, then the tick's
    names = git(project, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").decode().split()
    assert names == [plan.FILE]
    assert git(project, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD~1").decode().split() == ["HANDOFF.md"]
    assert "- [x] **Step 1.**" in (project / plan.FILE).read_text()


def test_an_undo_writes_docs_plan_md_again_with_the_step_open(project, conn, runner):
    found = _approved(conn)
    code, said, row = _route_step(conn, f"{found['n']}:1", worker=CopyWorker(SKELETON))
    assert _land(conn, row)[0] == 0
    code, said = _land(conn, row, verb="undo")
    assert code == 0, said
    assert not (project / "cli.py").exists()
    text = (project / plan.FILE).read_text()
    assert "- [ ] **Step 1.**" in text and "0 of 2 steps done" in text
    assert plan.first_open(conn, found)[0] == 1


def test_an_earlier_step_can_be_undone_after_a_later_tick(project, conn, runner):
    found = _approved(conn)
    code, said, one = _route_step(conn, f"{found['n']}:1", worker=CopyWorker(SKELETON))
    assert _land(conn, one)[0] == 0
    step2 = ("Added the conversion.\n\n## Handoff\n### Produced\nconvert.py added\n### Status\nok\n### Next\nnone",
             {"convert.py": "def c_to_f(c):\n    return c * 9 / 5 + 32\n"})
    code, said, two = _route_step(conn, f"{found['n']}:2", worker=CopyWorker(step2), task="Add the conversion.")
    assert _land(conn, two)[0] == 0
    code, said = _land(conn, one, verb="undo")
    assert code == 0, said
    text = (project / plan.FILE).read_text()
    assert "- [ ] **Step 1.**" in text and "- [x] **Step 2.**" in text


@pytest.mark.parametrize("ending", ["failed_check", "discard"])
def test_a_step_that_failed_or_was_discarded_stays_open(project, conn, runner, ending):
    found = _approved(conn)
    if ending == "failed_check":
        chat = Chat("FIX\n1. [must] no test", "FIX\n1. not fixed: still none")
        worker = CopyWorker(SKELETON, ("Tried.\n\n" + HANDOFF, {"cli.py": "print('help!')\n"}))
        code, said, row = _route_step(conn, f"{found['n']}:1", worker=worker, chatgpt=chat)
    else:
        code, said, row = _route_step(conn, f"{found['n']}:1", worker=CopyWorker(SKELETON))
        assert _land(conn, row, verb="discard")[0] == 0
    assert plan.first_open(conn, found)[0] == 1


# ---------- docs/PLAN.md isn't what the router last wrote (decision 14) ----------

def test_uncommitted_edits_leave_it_out_and_the_tick_still_counts(project, conn, runner):
    found = _approved(conn)
    code, said, row = _route_step(conn, f"{found['n']}:1", worker=CopyWorker(SKELETON))
    (project / plan.FILE).write_text("my notes\n")
    code, said = _land(conn, row)
    assert code == 0, said
    names = git(project, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").decode().split()
    assert plan.FILE not in names and (project / plan.FILE).read_text() == "my notes\n"
    assert log.project_files_of(log.get_task(conn, row["task_id"]))["plan_md"]["state"] == "left_out"
    assert "docs/PLAN.md has uncommitted edits in the folder" in said
    assert plan.first_open(conn, found)[0] == 2


def test_an_outside_commit_is_written_over_in_the_same_commit(project, conn, runner):
    found = _approved(conn)
    (project / plan.FILE).write_text("someone else's plan\n")
    git(project, "add", plan.FILE)
    git(project, "commit", "-q", "-m", "outside")
    code, said, row = _route_step(conn, f"{found['n']}:1", worker=CopyWorker(SKELETON))
    code, said = _land(conn, row)
    assert code == 0, said
    assert "- [x] **Step 1.**" in (project / plan.FILE).read_text()
    assert log.project_files_of(log.get_task(conn, row["task_id"]))["plan_md"]["state"] == "overwritten"
    assert "docs/PLAN.md had changed in a commit outside the router" in said


def test_a_link_is_left_out_and_said(project, conn, runner, tmp_path):
    found = _approved(conn)
    code, said, row = _route_step(conn, f"{found['n']}:1", worker=CopyWorker(SKELETON))
    (project / plan.FILE).unlink()
    target = tmp_path / "PLAN.md"
    target.write_text("x\n")
    os.symlink(target, project / plan.FILE)
    code, said = _land(conn, row)
    assert code == 0, said and "docs/PLAN.md is a link in the folder" in said
    assert target.read_text() == "x\n"  # never written through
    assert log.project_files_of(log.get_task(conn, row["task_id"]))["plan_md"]["state"] == "left_out"
