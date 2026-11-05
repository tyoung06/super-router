"""Build brief 33.2, T (decision 7): a spec changed after the plan. "Changed" is the folder's SPEC.md hashing differently
from the one the plan task read at its intake (`spec_hash`); a spec deleted since, or added to a project whose plan had
none, counts. What now? gets the `spec_changed` rung after the third and before the plan's need rung, with the Revise plan
chip; a plan still waiting for approval says so on its card (the JSON's `spec_changed`). An Auto run records the hash at
`--on`, compares before each step and each retry, stops before the step (`spec_changed`, "SPEC.md changed since the run
started"), and goes on with the new hash when the switch is turned on again, the confirm saying the remaining steps use
the new SPEC.md. Real git in temp folders, fake agents; every value here is fake."""
import pytest

from router import __main__ as cli
from router import auto, copies, log, plan, projects, receipt, spec, whatnow
from tests.test_auto_run import STEP1, STEP2, _auto, _route_plan, _steps
from tests.test_covers332 import COVERED, REVISED
from tests.test_filemode_flow import CopyWorker, conn, project, runner  # noqa: F401 (fixtures)
from tests.test_plan_approval import _land
from tests.test_plan_chain import ReadWorker, World
from tests.test_plan_steps import _approved
from tests.test_relay import CONFIG, Chat
from tests.test_spec332 import SPEC, TEXT_SPEC, _commit_spec
from tests.test_copies import git

CHANGED = SPEC.replace("c_to_f(-40) == -40", "c_to_f(0) == 32")


def _planned_with_spec(conn, project):
    _commit_spec(project)
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    w = World(worker=ReadWorker(COVERED, REVISED))
    code, row = w.plan(conn)
    assert code == 0, w.said
    return log.get_task(conn, row["task_id"])


def _now(conn):
    return whatnow.for_project(conn, "garden")


# ---------- the rung and its chip (decision 7.1) ----------

def test_a_changed_spec_is_the_rung_after_the_third_with_revise_plan_and_build_step_k_stays_on_the_card(project, conn, runner):
    row = _planned_with_spec(conn, project)
    assert _land(conn, row)[0] == 0
    found = log.get_task(conn, row["task_id"])
    assert plan.record_of(found)["spec_hash"] == spec.digest(SPEC)
    assert plan.spec_changed(project, plan.record_of(found)) is False
    assert _now(conn)["rung"] == "plan_step"
    _commit_spec(project, CHANGED, "spec edited")
    assert plan.spec_changed(project, plan.record_of(found)) is True
    line = _now(conn)
    assert (line["rung"], line["words"], line["control"]) == ("spec_changed", f"SPEC.md changed since plan #{found['n']} · Revise plan", "chip")
    assert line["chip"] == {"kind": "revise_plan", "words": "Revise plan", "later": False,
                            "fill": {"team": "plan", "project": "garden", "chat": None, "text": "Revise the plan for the current SPEC.md.",
                                     "from": None, "idea": None, "step": None}}
    assert line["task_id"] == found["task_id"]
    moves, from_this = plan.moves(conn, found)  # the newest card's chips are unchanged: Build step 1 stays offered
    assert [m["kind"] for m in moves] == ["build_step"]


def test_a_deleted_spec_and_a_spec_added_after_a_plan_with_none_count_as_changed(project, conn, runner):
    row = _planned_with_spec(conn, project)
    assert _land(conn, row)[0] == 0
    (project / "SPEC.md").unlink()
    git(project, "commit", "-q", "-am", "spec removed")
    assert plan.spec_changed(project, plan.record_of(log.get_task(conn, row["task_id"]))) is True
    assert _now(conn)["rung"] == "spec_changed"
    # a plan made with no spec, then one added
    assert _land(conn, log.get_task(conn, row["task_id"]), verb="undo")[0] == 0
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    w = World()
    code, other = w.plan(conn)
    assert code == 0, w.said
    assert _land(conn, log.get_task(conn, other["task_id"]))[0] == 0
    assert plan.record_of(log.get_task(conn, other["task_id"]))["spec_hash"] is None
    assert _now(conn)["rung"] == "plan_step"
    _commit_spec(project, TEXT_SPEC, "spec added")
    assert plan.spec_changed(project, plan.record_of(log.get_task(conn, other["task_id"]))) is True
    assert _now(conn)["rung"] == "spec_changed"


def test_the_rung_gives_way_to_a_task_waiting_on_the_owner_and_to_the_finish_line(project, conn, runner):
    row = _planned_with_spec(conn, project)  # waiting for approval: rung 1 first, the card's line says the change
    _commit_spec(project, CHANGED, "spec edited")
    line = _now(conn)
    assert line["rung"] == 1 and "a plan to approve" in line["words"]
    found = log.get_task(conn, row["task_id"])
    assert plan.view(conn, found)["spec_changed"] is True
    assert plan.spec_changed(project, plan.record_of(found)) is True
    assert _land(conn, found)[0] == 0  # nothing is refused
    assert plan.view(conn, log.get_task(conn, row["task_id"]))["spec_changed"] is True  # the landed plan read the old spec


def test_a_plan_waiting_for_approval_reads_false_while_the_spec_stands_true_once_changed_false_once_reverted(
        project, conn, runner):
    # brief 33.2 fix 5 (b) (the owner's decision 6): the flag follows the folder's SPEC.md each read, both ways
    row = _planned_with_spec(conn, project)

    def changed():
        return plan.view(conn, log.get_task(conn, row["task_id"]))["spec_changed"]

    assert changed() is False  # the spec stands
    _commit_spec(project, CHANGED, "spec edited")
    assert changed() is True  # changed since the plan read it
    _commit_spec(project, SPEC, "spec reverted")
    assert changed() is False  # back to the spec the plan read


# ---------- the Auto stop (decision 7.2) ----------

def _run_with_spec(conn, project, stop_at=None, **kw):
    row = _planned_with_spec(conn, project)
    assert _land(conn, row)[0] == 0
    plan_row = _route_plan(conn, log.get_task(conn, row["task_id"]))
    if stop_at:
        cli.cmd_plan_stop_here(f"{plan_row['n']}:{stop_at}", ["on"], conn=conn, out=receipt.Receipt())
    return plan_row


def test_on_records_the_specs_hash_and_a_change_stops_the_run_before_its_next_step(project, conn, runner):
    plan_row = _run_with_spec(conn, project)

    def edit_during_step_1(prompt, copy=None, search=False, **kw):
        _commit_spec(project, CHANGED, "edited mid-run")
        return CopyWorker(STEP1)(prompt, copy=copy, search=search, **kw)
    code, out, run = _auto(conn, worker=edit_during_step_1)
    assert code == 4, out.message
    record = log.auto_of(log.get_task(conn, run["task_id"]))
    assert record["spec_hash"] == spec.digest(SPEC)  # as at --on
    assert record["stop"] == {"code": "spec_changed", "why": "SPEC.md changed since the run started", "step": 2}
    assert auto.step_entry(record, 1)["state"] == "done" and auto.step_entry(record, 2)["state"] == "open"
    line = _now(conn)
    assert (line["rung"], line["words"], line["control"]) == ("auto_stopped", "Auto stopped: SPEC.md changed since the run started", "open")
    view = auto.view(conn, log.get_task(conn, run["task_id"]))
    assert view["spec_hash"] == spec.digest(SPEC) and view["stop"]["code"] == "spec_changed"
    assert "Auto stopped: SPEC.md changed since the run started" in out.message
    assert copies.exists(run["task_id"])
    assert auto.can_start(conn, "garden", log.get_task(conn, run["task_id"])) is None  # the switch may go on again


def test_on_again_takes_the_new_hash_and_the_dry_run_says_the_remaining_steps_use_the_new_spec(project, conn, runner):
    plan_row = _run_with_spec(conn, project, stop_at=2)
    code, out, run = _auto(conn)
    assert code == 4 and "stop here before step 2" in out.message
    _commit_spec(project, CHANGED, "edited while stopped")
    code, out, run = _auto(conn, dry_run=True)  # the switch on again: its confirm
    assert code == 0, out.message
    doc = out.extra_any["auto"]
    assert doc["spec_line"] == "The remaining steps will use the new SPEC.md."
    assert doc["spec_changed"] is True
    code, out, run = _auto(conn, worker=CopyWorker(STEP2))
    assert code == 0, out.message  # the run went on and finished (step 2 passed the mark)
    record = log.auto_of(log.get_task(conn, run["task_id"]))
    assert record["spec_hash"] == spec.digest(CHANGED)
    step2 = _steps(conn, run)[-1]
    assert log.project_files_of(step2)["run"] == run["task_id"]
    from router import rounds
    assert (rounds.log_folder(conn) / "tasks" / step2["task_id"] / "SPEC.md").read_text() == CHANGED  # read at its intake
    assert auto.view(conn, log.get_task(conn, run["task_id"]))["state"] == "finished"


def test_the_dry_run_without_a_change_has_no_spec_line(project, conn, runner):
    _run_with_spec(conn, project)
    code, out, run = _auto(conn, dry_run=True)
    assert code == 0 and out.extra_any["auto"]["spec_line"] is None and out.extra_any["auto"]["spec_changed"] is False


def test_the_change_is_checked_before_a_retry_too(project, conn, runner):
    plan_row = _run_with_spec(conn, project)
    chat = Chat("FIX\n1. [must] wrong", "FIX\n1. [must] still wrong")  # step 1 fails its check twice: one retry

    def edit_during_step_1(prompt, copy=None, search=False, **kw):
        _commit_spec(project, CHANGED, "edited during step 1")
        return CopyWorker(STEP1)(prompt, copy=copy, search=search, **kw)
    code, out, run = _auto(conn, worker=edit_during_step_1, chatgpt=chat)
    assert code == 4, out.message
    record = log.auto_of(log.get_task(conn, run["task_id"]))
    assert record["stop"]["code"] == "spec_changed" and record["stop"]["step"] == 1
    assert auto.step_entry(record, 1)["state"] == "retried"  # the retry waits for the switch
    assert "SPEC.md changed since the run started" in out.message


def test_a_run_on_a_project_without_a_spec_stops_when_one_is_added(project, conn, runner):
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    plan_row = _route_plan(conn, _approved(conn))

    def add_during_step_1(prompt, copy=None, search=False, **kw):
        _commit_spec(project, TEXT_SPEC, "spec added mid-run")
        return CopyWorker(STEP1)(prompt, copy=copy, search=search, **kw)
    code, out, run = _auto(conn, worker=add_during_step_1)
    assert code == 4, out.message
    record = log.auto_of(log.get_task(conn, run["task_id"]))
    assert record["spec_hash"] is None and record["stop"]["code"] == "spec_changed"


def test_the_stops_card_words_name_the_two_ways_on_with_and_without_revise_plan():
    assert auto.spec_stop_ways(True) == ("Land the run so far or Discard run, then Revise plan; or turn the switch on again: "
                                         "the remaining steps use the new SPEC.md.")
    assert auto.spec_stop_ways(False) == ("Land the run so far or Discard run; or turn the switch on again: the remaining "
                                          "steps use the new SPEC.md.")
    assert "spec_changed" in auto.STOPS
