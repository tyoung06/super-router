"""Build brief 33.1, the rest (decisions 16 to 19): needs up front, What now?'s plan rungs, the router's moves, and the
JSON. What now? goes (1) waiting on you (a plan to approve), (2) running, (3) the newest task ended undelivered (a One step
end in its own words, with Build it), then the plan's rungs: (a) the next step's unmet key or test command, (b) Build step
k, (c) the finish line until a newer top-level task exists; then brief 33's (4) and (5). The router's moves gain Build
step k (first, and then no Build from this) and Plan from this. Real git in temp folders, fake agents; every value fake."""
import json

from router import __main__ as cli
from router import jsonview, log, nextsteps, plan, projects, whatnow
from tests.fixtures import json_shapes
from tests.test_filemode_flow import CopyWorker, conn, project, runner  # noqa: F401 (fixtures)
from tests.test_plan_approval import _land, _planned
from tests.test_plan_chain import World, ReadWorker
from tests.test_plan_contract import GOOD, ONE
from tests.test_plan_steps import RESEARCH, SKELETON, _approved, _route_step

NO_NEEDS = GOOD.split("## Needs from you")[0] + "## Needs from you\nnone\n"
REVISED_NO_NEEDS = NO_NEEDS + "\n## Answered\nA2, B2: small enough\n"


def _now(conn):
    return whatnow.for_project(conn, "garden")


# ---------- What now?'s rungs (decision 17) ----------

def test_a_plan_waiting_on_approval_is_rung_1(project, conn, runner):
    w, row = _planned(conn)
    found = _now(conn)
    assert (found["rung"], found["words"], found["control"]) == (1, f"Waiting on you: #{row['n']} · a plan to approve",
                                                                 "open")


def test_a_one_step_end_is_rung_3_in_its_own_words_with_build_it(project, conn, runner):
    w = World(worker=ReadWorker(ONE))
    code, row = w.plan(conn, task="Add a one-line docstring to hello.py.")
    found = _now(conn)
    assert found["rung"] == 3 and found["words"] == "One step: Add a one-line docstring to hello.py's greet function."
    assert found["control"] == "chip" and found["chip"]["kind"] == "build_it"
    assert found["chip"]["fill"] == {"team": "route", "project": "garden", "chat": None, "from": None, "idea": None,
                                     "step": None, "text": "Add a one-line docstring to hello.py's greet function."}


def test_a_key_the_next_step_needs_comes_before_its_step(project, conn, runner):
    w, row = _planned(conn)
    assert _land(conn, row)[0] == 0
    found = _now(conn)  # step 1 needs nothing but the test command the plan proposes
    assert (found["rung"], found["words"], found["control"]) == ("plan_need", "Before step 1: set the test command",
                                                                 "tests")
    assert found["need"] == {"kind": "test_command", "proposed": "python3 -m unittest",
                             "words": "Before step 1: set the test command"}
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    found = _now(conn)
    assert (found["rung"], found["control"]) == ("plan_step", "chip")
    assert found["words"].startswith("Build step 1: Make the skeleton")
    assert found["chip"]["fill"]["step"] == {"plan": row["task_id"], "n": row["n"], "k": 1}


def test_the_next_steps_unset_key_is_named(project, conn, runner):
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    found = _approved(conn)
    code, said, one = _route_step(conn, f"{found['n']}:1", worker=CopyWorker(SKELETON))
    assert _land(conn, one)[0] == 0
    line = _now(conn)
    assert (line["rung"], line["words"], line["control"]) == ("plan_need", "Before step 2: set WEATHER_KEY", "secrets")
    assert line["need"]["name"] == "WEATHER_KEY"
    (project / ".env").write_text("WEATHER_KEY=placeholder-value\n")
    assert _now(conn)["words"].startswith("Build step 2:")


def test_the_finish_line_shows_until_a_newer_task(project, conn, runner):
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    w = World(worker=ReadWorker(NO_NEEDS, REVISED_NO_NEEDS))
    code, row = w.plan(conn)
    assert _land(conn, log.get_task(conn, row["task_id"]))[0] == 0
    found = log.get_task(conn, row["task_id"])
    for k in (1, 2):
        code, said, step = _route_step(conn, f"{found['n']}:{k}", worker=CopyWorker(RESEARCH))
        assert code == 0, said
    line = _now(conn)
    assert (line["rung"], line["words"], line["control"]) == ("finish", "All 2 steps done", "chips")
    assert [c["kind"] for c in line["chips"]] == ["readme", "run_command", "what_next"]
    assert line["chips"][0]["fill"]["text"] == plan.README_TEXT and line["chips"][2]["fill"]["team"] == "plan"
    code, said, newer = _route_step(conn, None, worker=CopyWorker(RESEARCH), task="Tidy the help text.")
    assert _now(conn)["rung"] != "finish"


# ---------- the router's moves (decision 18) ----------

def test_build_step_k_comes_first_and_no_build_from_this_while_a_step_is_open(project, conn, runner):
    found = _approved(conn)
    projects.set_tests("garden", ["python3", "-m", "unittest"])  # brief 33.2 (decision 13): a step with an unmet need
    (project / ".env").write_text("WEATHER_KEY=placeholder-value\n")  # is never offered as Build step k
    code, said, step = _route_step(conn, f"{found['n']}:1", worker=CopyWorker(RESEARCH))
    chips = nextsteps.chips(conn, log.get_task(conn, step["task_id"]))
    assert chips[0]["kind"] == "build_step" and chips[0]["words"].startswith("Build step 2: Add the Celsius")
    assert all(c["kind"] != "build_from" for c in chips)


def test_a_landed_plan_offers_build_step_1(project, conn, runner):
    found = _approved(conn)
    projects.set_tests("garden", ["python3", "-m", "unittest"])  # brief 33.2 (decision 13): once step 1's need is met
    chips = nextsteps.chips(conn, found)
    assert chips[0]["kind"] == "build_step" and chips[0]["fill"]["team"] == "route"
    assert chips[0]["fill"]["step"] == {"plan": found["task_id"], "n": found["n"], "k": 1}


def test_plan_from_this_once_every_step_is_done(project, conn, runner):
    w = World(worker=ReadWorker(NO_NEEDS, REVISED_NO_NEEDS))
    code, row = w.plan(conn)
    assert _land(conn, log.get_task(conn, row["task_id"]))[0] == 0
    found = log.get_task(conn, row["task_id"])
    last = None
    for k in (1, 2):
        code, said, last = _route_step(conn, f"{found['n']}:{k}", worker=CopyWorker(RESEARCH))
    chips = nextsteps.chips(conn, log.get_task(conn, last["task_id"]))
    assert [c["kind"] for c in chips][:2] == ["plan_from", "build_from"]
    assert chips[0]["fill"] == {"team": "plan", "project": "garden", "chat": None, "from": last["task_id"], "idea": None,
                                "step": None, "text": f"Plan this project from #{last['n']}."}


# ---------- the JSON (decision 19) ----------

def test_a_plan_tasks_json_has_its_steps_needs_and_estimate(project, conn, runner):
    found = _approved(conn)
    code, said, one = _route_step(conn, f"{found['n']}:1", worker=CopyWorker(SKELETON))
    view = jsonview.task_view(conn, log.get_task(conn, found["task_id"]))
    json_shapes.check(view, json_shapes.TASK)
    shown = view["plan"]
    assert [s["state"] for s in shown["steps"]] == ["in_progress", "open"]
    assert shown["steps"][0]["task"]["n"] == one["n"] and shown["current"] is True
    assert [n["kind"] for n in shown["needs"]] == ["key", "account", "decision", "test_command"]
    assert shown["needs"][0]["set"] is False and shown["needs"][1]["set"] is None
    assert shown["test_command"] == {"proposed": "python3 -m unittest", "set": None}
    assert _land(conn, one)[0] == 0
    shown = jsonview.task_view(conn, log.get_task(conn, found["task_id"]))["plan"]
    assert [s["state"] for s in shown["steps"]] == ["done", "next"] and (shown["done"], shown["total"]) == (1, 2)


def test_show_carries_the_estimate_with_the_menu(project, conn, runner):
    from tests.test_plan_chain import LOADED, ROSTER
    found = _approved(conn)
    view = jsonview.show_view(conn, found, loaded=LOADED, roster=ROSTER, send_paths=tuple(cli.SENDERS))
    estimate = view["plan"]["estimate"]
    assert estimate["jev_labels"] == 1 and estimate["calls"] > 0 and estimate["max_calls"] >= estimate["calls"]
    assert plan.count_words(estimate).endswith("· Jev: 1 label")
    assert [s["calls"] for s in view["plan"]["steps"]][0] == 2


def test_a_step_tasks_json_names_its_plan_and_step(project, conn, runner):
    found = _approved(conn)
    code, said, one = _route_step(conn, f"{found['n']}:1", worker=CopyWorker(SKELETON))
    shown = jsonview.task_view(conn, log.get_task(conn, one["task_id"]))["plan_step"]
    assert (shown["plan"], shown["n"], shown["step"]) == (found["task_id"], found["n"], 1)
    assert shown["done_when"].startswith("test_cli.py's test_help passes")


def test_per_project_plan_and_status_plan(project, conn, runner):
    found = _approved(conn)
    view = plan.project_view(conn, "garden")
    assert (view["n"], view["done"], view["total"]) == (found["n"], 0, 2)
    assert view["next"]["k"] == 1 and view["file"] == plan.FILE
    # brief 34 (decision 13): the steps for the plan panel's Stop here toggles, with the marks
    assert [(s["k"], s["team"], s["done"], s["stop_here"]) for s in view["steps"]] == [(1, "route", False, False), (2, "redteam", False, False)]
    assert view["steps"][0]["text"].startswith("Make the skeleton") and view["stop_here"] == []
    from router import auto
    log.set_plan(conn, found["task_id"], auto.with_mark(plan.record_of(log.get_task(conn, found["task_id"])), 2, True))
    view = plan.project_view(conn, "garden")
    assert view["stop_here"] == [2] and [s["stop_here"] for s in view["steps"]] == [False, True]
    from tests.test_plan_chain import LOADED, ROSTER
    entry = plan.status_entry(LOADED, ROSTER, None, send_paths=tuple(cli.SENDERS))
    json_shapes.check(entry, json_shapes.PLAN)
    assert (entry["ready"], entry["calls"], entry["max_calls"]) == (True, 5, 7)
    assert entry["chain"] == "Claude plan → ChatGPT attack → Cursor attack → Claude revise → ChatGPT check"
