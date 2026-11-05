"""Brief 33.2 fix 3 (the owner's decision 3, item 5 option C): a run's land commit names the steps that landed and the
plan's total: `sr: Auto: plan #<n>, steps <a> to <b> of <m> (<run task_id>)`. Land the run so far on steps 1 and 2 of a
3-step plan reads `steps 1 to 2 of 3`; a finished run from step 3 of a 4-step plan, `steps 3 to 4 of 4`. The run row's
text, its card, `sr show` and Undo's message are unchanged. Real git in temp folders, fake agents; every value here is
fake."""
from router import auto, log, receipt
from router import __main__ as cli
from tests.test_auto_run import STEP1, STEP2, _approved, _auto, _route_plan, git
from tests.test_filemode_flow import CODE, CopyWorker, conn, project, runner  # noqa: F401 (fixtures)
from tests.test_loop import Webhook
from tests.test_plan_approval import _land
from tests.test_relay import CONFIG, ROSTER, Chat
from tests.helpers import fake_label

PLAN = {"task_id": "sr-20261031-100000-aa01", "n": 155}


def _record(total, *, from_step=1, done=()):
    record = auto.new_record(PLAN, [{"team": "route"}] * total, from_step=from_step, budget=20, estimate={})
    for step in record["steps"]:
        if step["k"] in done:
            step.update(state="done", task_id=f"sr-step-{step['k']}")
    return record


def _subject(folder):
    return git(folder, "log", "-1", "--format=%s").stdout.strip()


# ---------- the words (pure) ----------

def test_land_the_run_so_far_on_steps_1_and_2_of_3_names_those_and_the_total():
    record = _record(3, done=(1, 2))
    assert auto.land_message(record) == "Auto: plan #155, steps 1 to 2 of 3"


def test_a_finished_run_from_step_3_of_4_reads_steps_3_to_4_of_4():
    record = _record(4, from_step=3, done=(1, 2, 3, 4))
    assert auto.land_message(record) == "Auto: plan #155, steps 3 to 4 of 4"


def test_one_step_landed_reads_step_k_of_m_and_none_reads_none():
    assert auto.land_message(_record(3, done=(1,))) == "Auto: plan #155, step 1 of 3"
    assert auto.land_message(_record(3)) == "Auto: plan #155, no step of 3"


# ---------- the commits ----------

def test_land_the_run_so_far_commits_only_the_landed_steps_and_the_total(project, conn, runner):
    plan_row = _route_plan(conn, _approved(conn))
    cli.cmd_plan_stop_here(f"{plan_row['n']}:2", ["on"], conn=conn, out=receipt.Receipt())
    code, out, run = _auto(conn)
    assert code == 4, out.message
    assert run["task"] == f"Auto: plan #{plan_row['n']}, steps 1 to 2"  # the run row's text: the planned range, unchanged
    code, text = _land(conn, log.get_task(conn, run["task_id"]))
    assert code == 0, text
    assert _subject(project) == f"sr: Auto: plan #{plan_row['n']}, step 1 of 2 ({run['task_id']})"


def test_a_finished_runs_land_names_every_step_it_ran_and_undo_is_unchanged(project, conn, runner):
    plan_row = _route_plan(conn, _approved(conn))
    code, out, run = _auto(conn)
    assert code == 0, out.message
    code, text = _land(conn, log.get_task(conn, run["task_id"]))
    assert code == 0, text
    assert _subject(project) == f"sr: Auto: plan #{plan_row['n']}, steps 1 to 2 of 2 ({run['task_id']})"
    landed = git(project, "rev-parse", "--short", "HEAD").stdout.strip()
    code, text = _land(conn, log.get_task(conn, run["task_id"]), verb="undo")
    assert code == 0, text
    assert _subject(project).startswith(f"sr: undo {landed}, Auto: plan #{plan_row['n']}, steps 1 to 2 (")


def test_a_run_started_at_a_later_step_names_its_own_steps(project, conn, runner):
    plan_row = _route_plan(conn, _approved(conn))
    from router import plan
    step1 = plan.steps_of(plan.record_of(plan_row))[0]["text"]
    out = receipt.Receipt()
    code = cli.cmd_route(step1, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=fake_label(CODE),
                         post=Webhook().post, worker=CopyWorker(STEP1), chatgpt=Chat("PASS"), codex_login=lambda: True, wait=True,
                         project="garden", files_ready=lambda: (True, None), step_ref=f"{plan_row['task_id']}:1", out=out)
    assert code == 0, out.message
    assert _land(conn, log.get_task(conn, out.task_id))[0] == 0
    code, out, run = _auto(conn, worker=CopyWorker(STEP2))
    assert code == 0, out.message
    assert _land(conn, log.get_task(conn, run["task_id"]))[0] == 0
    assert _subject(project) == f"sr: Auto: plan #{plan_row['n']}, step 2 of 2 ({run['task_id']})"
