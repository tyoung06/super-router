"""Build brief 33.2, A (decision 12): Add to plan. `sr plan --idea <id>` on a project whose current plan has open steps makes
a revision carrying the idea (the text is the ask; the planner keeps the open steps unless the idea requires changing
one, the keep-unless rule being prompt words); with no current plan, or all done, a new plan from the idea. The idea's
states derive as today: "sent as #n" while the plan task is open or waits to land, used when it lands, open again when it
is rejected. Refused by route's `--idea` rules (`bad_idea`). A planner answering `## One step` to an idea ends the plan
task as today, its Build it chip carrying the idea. Real git in temp folders, fake agents; every value here is fake."""
from router import __main__ as cli
from router import ideas, log, nextsteps, plan, projects, receipt
from tests.test_filemode_flow import CopyWorker, conn, project, runner  # noqa: F401 (fixtures)
from tests.test_plan_approval import _land
from tests.test_plan_chain import ReadWorker, World
from tests.test_plan_contract import ONE
from tests.test_plan_rest import NO_NEEDS, REVISED_NO_NEEDS
from tests.test_revise332 import REV, REV_ANSWERED, _first_plan
from tests.test_relay import CONFIG


def _idea(conn, text="Add c_to_k(c) to conv.py with a unittest."):
    out = receipt.Receipt()
    assert cli.cmd_ideas(["garden"], conn=conn, add=True, text=text, out=out) == 0, out.message
    return ideas.all_of(conn, "garden")[0]


def _state(conn, idea_id):
    return ideas.get(conn, idea_id).state


def test_add_to_plan_with_open_steps_is_a_revision_carrying_the_idea_and_the_keep_unless_words(project, conn, runner):
    old, step1 = _first_plan(conn, project)
    idea = _idea(conn)
    w = World(worker=ReadWorker(REV, REV_ANSWERED))
    code, row = w.plan(conn, task=idea.text, idea_ref=str(idea.id))
    assert code == 0, w.said
    rev = log.get_task(conn, row["task_id"])
    assert rev["idea"] == idea.id and plan.record_of(rev)["revises"] == old["task_id"]
    planner = w.worker.calls[0]["prompt"]
    assert plan.KEEP_UNLESS_LINE in planner and planner.startswith(idea.text)  # nothing added to the ask
    assert _state(conn, idea.id) == ideas.SENT and ideas.get(conn, idea.id).task["task_id"] == rev["task_id"]
    assert _land(conn, rev)[0] == 0
    assert _state(conn, idea.id) == ideas.USED


def test_rejecting_the_plan_opens_the_idea_again(project, conn, runner):
    old, step1 = _first_plan(conn, project)
    idea = _idea(conn)
    w = World(worker=ReadWorker(REV, REV_ANSWERED))
    code, row = w.plan(conn, task=idea.text, idea_ref=str(idea.id))
    assert code == 0 and _state(conn, idea.id) == ideas.SENT
    assert _land(conn, log.get_task(conn, row["task_id"]), verb="discard")[0] == 0
    assert _state(conn, idea.id) == ideas.OPEN


def test_without_a_current_plan_the_idea_makes_a_new_plan_without_the_keep_unless_words(project, conn, runner):
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    idea = _idea(conn, "Plan the converter.")
    w = World(worker=ReadWorker(NO_NEEDS, REVISED_NO_NEEDS))
    code, row = w.plan(conn, task=idea.text, idea_ref=str(idea.id))
    assert code == 0, w.said
    record = plan.record_of(log.get_task(conn, row["task_id"]))
    assert record["revises"] is None and plan.KEEP_UNLESS_LINE not in w.worker.calls[0]["prompt"]
    assert _state(conn, idea.id) == ideas.SENT


def test_the_ideas_refusals_hold_on_plan(project, conn, runner):
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    w = World()
    code, row = w.plan(conn, task="x", idea_ref="99")
    assert code == 2 and "there is no idea 99" in w.said
    idea = _idea(conn)
    out = receipt.Receipt()
    assert cli.cmd_ideas(["garden"], conn=conn, dismiss=idea.id, out=out) == 0
    w = World()
    code, row = w.plan(conn, task=idea.text, idea_ref=str(idea.id))
    assert code == 2 and "isn't open" in w.said
    from router import page_commands
    status = {"projects": [{"name": "garden"}], "presets": [], "plan": {"ready": True}}
    found = page_commands.build({"action": "send", "team": "plan", "text": "x", "project": "garden", "idea": 3}, status)
    assert "--idea" in found.args and found.args[found.args.index("--idea") + 1] == "3"


def test_one_step_to_an_idea_ends_the_plan_as_today_and_build_it_carries_the_idea(project, conn, runner):
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    idea = _idea(conn, "Add a one-line docstring to hello.py.")
    w = World(worker=ReadWorker(ONE))
    code, row = w.plan(conn, task=idea.text, idea_ref=str(idea.id))
    assert code == 1, w.said
    row = log.get_task(conn, row["task_id"])
    assert plan.one_step_reason(row) is not None
    chips = nextsteps.chips(conn, row)
    assert chips[0]["kind"] == "build_it" and chips[0]["fill"]["idea"] == idea.id
    assert _state(conn, idea.id) == ideas.OPEN  # the plan task ended without delivery: the idea is open again
