"""Build brief 33.2, F (decisions 13 to 17): the six leftovers of briefs 33.1 and 34. (13) Build step k is offered only
while the step's needs are met; an unmet need is What now?'s line alone. (14) The handoff's one-line entries cut their
reason at a word at 400 characters; the open-task refusal says the state in words; the plan refusal's step text is cut at
a word at 80; `sr project add` shows the folder with `~`. (15) A plan that fails at a stage removes its copy unless Resume
can make the stopped Claude call again. (16) A run's entry ends with one tests line summed from its steps' build and fix
calls, each step judged by its last run. (17) `auto` installs the round-file writer, so a run's step has its answer files
beside its prompt files. Real git in temp folders, fake agents; every value here is fake."""
from pathlib import Path

import pytest

from router import __main__ as cli
from router import auto, context, copies, intake, landing, log, nextsteps, plan, projects, rounds, testrun, whatnow
from tests.helpers import ALL_AGENTS, fake_label
from tests.test_auto_run import STEP1, STEP2, _auto, _route_plan, _steps
from tests.test_filemode_flow import CODE, CopyWorker, conn, project, runner  # noqa: F401 (fixtures)
from tests.test_json_actions import World as MainWorld
from tests.test_plan_approval import _land
from tests.test_plan_chain import ReadWorker, World
from tests.test_plan_contract import GOOD
from tests.test_plan_steps import _approved
from tests.test_relay import CONFIG, Chat

JEV = {"status": "ok", "label": "code", "confidence": 0.9, "tokens": 0}
NOT_ASKED = {"status": "not_asked", "tokens": 0}


# ---------- decision 13: Build step k only while the step's needs are met (33.1's D5) ----------

def test_build_step_k_is_not_offered_while_the_steps_need_is_unmet(project, conn, runner):
    found = _approved(conn)  # step 1's need: the test command the plan proposes, not set on the project yet
    line = whatnow.for_project(conn, "garden")
    assert (line["rung"], line["control"], line["chip"]) == ("plan_need", "tests", None)
    assert line["words"] == "Before step 1: set the test command"
    assert plan.moves(conn, found) == ([], False)
    assert all(c["kind"] != "build_step" for c in nextsteps.chips(conn, found))
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    moves, from_this = plan.moves(conn, found)
    assert [m["kind"] for m in moves] == ["build_step"] and from_this is False
    line = whatnow.for_project(conn, "garden")
    assert (line["rung"], line["control"]) == ("plan_step", "chip") and line["chip"]["kind"] == "build_step"
    assert nextsteps.chips(conn, found)[0]["kind"] == "build_step"


# ---------- decision 14: the cuts and the words (33.1's D2 and D7) ----------

def test_a_one_line_entry_cuts_its_reason_at_a_word_at_400():
    reason = " ".join(f"word{i}" for i in range(120))
    assert len(reason) > 400
    line = context.line_entry(7, "2026-10-30", "failed", reason)
    tail = line.split("· failed: ", 1)[1]
    assert len(tail) <= 400 and tail.endswith("…") and tail == landing.cut_at_word(reason, 400)
    assert reason.startswith(tail[:-1]) and not tail[:-1].endswith(" ")  # at a word, never mid-word
    exact = "x" * 400
    assert context.line_entry(7, "2026-10-30", "stopped", exact) == f"### #7 · 2026-10-30 · stopped: {exact}"


def _busy(conn, name="garden"):
    return intake.project_refusal(conn, name)


def _row(conn, k, jev=JEV, **kw):
    task_id = f"sr-20261030-1000{k:02d}-ab{k:02d}"
    log.add_task(conn, task_id, f"task {k}", "cli", jev, project="garden", **kw)
    return task_id


def _route(conn, task_id, agent="claude", skill="code"):
    log.set_route(conn, task_id, agents=ALL_AGENTS, agent=agent, route_reason="best", skill=skill, checker="chatgpt",
                  check_state="pending")


def _make_state(conn, case):
    """A row of the project in the state its case names."""
    if case == "running":
        return _row(conn, 1)
    if case == "land":
        task_id = _row(conn, 2)
        _route(conn, task_id)
        log.set_done(conn, task_id, "done", check_state="passed")
        log.set_project_files(conn, task_id, {"mode": "on", "state": "waiting", "copy": True,
                                              "changed": [{"path": "a.py", "status": "added", "plus": 1, "minus": 0}]})
        return task_id
    if case == "plan":
        task_id = _row(conn, 3, mode="plan", preset="redteam", plan=plan.new_record(["route"]), jev=NOT_ASKED)
        _route(conn, task_id, skill=None)
        log.set_done(conn, task_id, "the plan", check_state="passed")
        log.set_project_files(conn, task_id, {"mode": "on", "state": "waiting", "copy": True,
                                              "changed": [{"path": "docs/PLAN.md", "status": "added", "plus": 1, "minus": 0}]})
        return task_id
    if case == "grok":
        task_id = _row(conn, 4)
        _route(conn, task_id, agent="grok", skill="x_social_pulse")
        log.add_call(conn, f"{task_id}-1", task_id, "do", "grok", status="sent")
        return task_id
    if case == "pick":
        task_id = _row(conn, 5, mode="relay", preset="versus", jev=NOT_ASKED)
        _route(conn, task_id, skill=None)
        log.add_call(conn, f"{task_id}-1", task_id, "stage", "claude", status="done", text="A", stage=1, role="build")
        log.add_call(conn, f"{task_id}-2", task_id, "stage", "chatgpt", status="done", text="B", stage=2, role="build")
        log.add_call(conn, f"{task_id}-3", task_id, "stage", "chatgpt", status="done", text="PASS", stage=3, role="review")
        log.add_call(conn, f"{task_id}-4", task_id, "stage", "claude", status="done", text="PASS", stage=4, role="review")
        log.set_awaiting_pick(conn, task_id)
        return task_id
    run_of = {"task_id": "sr-20261030-100003-ab03", "n": 3}
    task_id = _row(conn, 6, mode="auto", jev=NOT_ASKED, auto=auto.new_record(run_of, [{"team": "route"}, {"team": "route"}],
                                                                               from_step=1, budget=6, estimate={}))
    log.set_project_files(conn, task_id, {"mode": "on", "state": "none", "copy": True, "changed": []})
    log.set_returned(conn, task_id, "returned: stop here before step 2")
    return task_id


@pytest.mark.parametrize("case, words, tail", [
    ("running", "running", "Finish or cancel it first"),
    ("land", "waiting to land", "Finish or cancel it first"),
    ("plan", "waiting for your approval", "Finish or cancel it first"),
    ("grok", "waiting on Grok", "Finish or cancel it first"),
    ("pick", "waiting for your pick", "Finish or cancel it first"),  # brief 33.4 (decision 5): Fix 5 (a)'s case, back
    ("auto", "Auto stopped", "Land the run so far or Discard run first"),
])
def test_the_open_task_refusal_says_the_state_in_words(project, case, words, tail):
    conn = log.init_db(":memory:")
    task_id = _make_state(conn, case)
    code, why = _busy(conn)
    n = log.get_task(conn, task_id)["n"]
    assert code == "project_busy"
    assert why == f"project garden has task {n} open ({words}). {tail}", why


def test_the_plan_refusal_is_gone_with_revise_plan_and_the_cut_stands_for_the_drop_case(project, conn, runner):
    """D7 (ii): the open-step refusal cut the step's text mid-word at 80. With Revise plan built (decision 9) that
    refusal is gone: a plan on a project whose current plan has an open step is a revision. `landing.cut_at_word` is the
    cut the drop case would use."""
    found = _approved(conn)
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    from tests.test_revise332 import REV, REV_ANSWERED
    w = World(worker=ReadWorker(REV.replace("## Steps\n2.", "## Steps\n1.").replace("\n3. Add c_to_k", "\n2. Add c_to_k")
                                .replace("step 2: its team", "step 1: its team"),
                                REV_ANSWERED.replace("## Steps\n2.", "## Steps\n1.").replace("\n3. Add c_to_k", "\n2. Add c_to_k")
                                .replace("step 2: its team", "step 1: its team")))
    code, row = w.plan(conn)
    assert code == 0, w.said
    assert "still has an open step" not in w.said and plan.record_of(log.get_task(conn, row["task_id"]))["revises"] == found["task_id"]
    long_text = "Make the skeleton of the converter with its one test, " * 6
    cut = landing.cut_at_word(long_text.strip(), 80)
    assert len(cut) <= 80 and cut.endswith("…") and not cut[:-1].endswith(" ") and long_text.startswith(cut[:-1])


def test_project_add_shows_the_folder_with_a_tilde(project, conn, tmp_path, monkeypatch):
    home = tmp_path / "home"
    folder = home / "Projects" / "herbs"
    folder.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    lines = []
    code = cli.cmd_project(["add", "herbs", str(folder)], conn=conn, out=lines.append)
    assert code == 0, lines
    assert lines[0].startswith("Registered herbs at ~/Projects/herbs.") and str(home) not in lines[0]


# ---------- decision 15: a failed plan's copy (33.1's D3) ----------

def test_a_plan_that_misses_its_contract_past_the_reask_removes_its_copy_and_says_so(project, conn, runner):
    w = World(worker=ReadWorker("no plan here", "still no plan"))
    code, row = w.plan(conn)
    assert code == 1
    task = log.get_task(conn, row["task_id"])
    assert task["status"] == "failed" and task["failed_stage"] == 1
    assert not copies.exists(row["task_id"])
    assert "copy is removed" in w.said
    files = log.project_files_of(task)
    assert files["copy"] is False


def test_a_plan_stopped_on_a_claude_call_keeps_its_copy_for_resume_and_says_so(project, conn, runner):
    from router import claude_worker
    stop = claude_worker.WorkerError("plan limit on claude: you have reached your limit", code="plan_limit")
    w = World(worker=ReadWorker(stop))
    code, row = w.plan(conn, available=_everyone())
    assert code == 1
    assert copies.exists(row["task_id"]) and "copy is kept for sr resume" in w.said
    assert log.project_files_of(log.get_task(conn, row["task_id"]))["copy"] is True


def _everyone():
    from tests.test_routing_availability import Gate
    return Gate()


# ---------- decision 16: the run's tests line (34's D2) ----------

def _tests(outcome, k=1):
    return {"exit": 0 if outcome == "passed" else 1, "outcome": outcome, "summary": "s", "output": f"tests-{k}.txt",
            "command": ["python3", "-m", "unittest"]}


def test_the_tests_sum_judges_each_step_by_its_last_run():
    all_good = {1: [_tests("passed")], 2: [_tests("passed")]}
    assert auto.tests_sum(all_good) == "Tests: `python3 -m unittest` · 2 runs across 2 steps, all passing at the end"
    fixed = {1: [_tests("failed"), _tests("passed", 2)], 2: [_tests("passed")]}
    assert auto.tests_sum(fixed) == ("Tests: `python3 -m unittest` · 3 runs across 2 steps, all passing at the end "
                                     "(step 1 fixed once)")
    failing = {1: [_tests("passed")], 2: [_tests("passed"), _tests("failed", 2)]}
    assert auto.tests_sum(failing) == "Tests: `python3 -m unittest` · 3 runs across 2 steps, step 2 failing"
    twice = {1: [_tests("failed"), _tests("failed", 2), _tests("passed", 3)], 2: [_tests("failed"), _tests("passed", 2)]}
    assert auto.tests_sum(twice) == ("Tests: `python3 -m unittest` · 5 runs across 2 steps, all passing at the end "
                                     "(step 1 fixed twice, step 2 fixed once)")
    assert auto.tests_sum({1: [], 2: []}) == "No tests ran: no test command"
    assert auto.tests_sum({}) == "No tests ran: no test command"
    none_ran = {1: [{"outcome": "not_run", "why": "no file changed", "command": None}]}
    assert auto.tests_sum(none_ran) == "No tests ran: no test command"


def test_the_runs_entry_and_card_carry_the_tests_sum(project, conn, runner):
    plan_row = _route_plan(conn, _approved(conn))
    runner.results = [testrun.Result(1, "failed", "1 failed", "FAILED"), testrun.Result(0, "passed", "OK", "OK"),
                      testrun.Result(0, "passed", "OK", "OK")]
    chat = Chat("FIX\n1. [must] test_cli fails: fix it", "PASS", "PASS")
    fixed = (STEP1[0], {"cli.py": "print('help, fixed')\n"})  # the fix changes a file, so the tests run again
    worker = CopyWorker(STEP1, fixed, STEP2)  # step 1's build, its fix round, step 2's build
    code, out, run = _auto(conn, worker=worker, chatgpt=chat)
    assert code == 0, out.message
    steps = _steps(conn, run)
    assert [c["kind"] for c in log.calls_for(conn, steps[0]["task_id"])] == ["do", "check", "fix", "recheck"]
    expected = "Tests: `python3 -m unittest` · 3 runs across 2 steps, all passing at the end (step 1 fixed once)"
    assert auto.view(conn, log.get_task(conn, run["task_id"]))["tests"] == expected
    code, text = _land(conn, log.get_task(conn, run["task_id"]))
    assert code == 0, text
    entry = _entry(project, run["n"])
    assert entry.rstrip().endswith(expected), entry
    assert "No tests ran" not in entry


def test_land_the_run_so_far_sums_the_landed_steps_only(project, conn, runner):
    plan_row = _route_plan(conn, _approved(conn))
    plan.stop_here(conn, plan_row, 2, True)
    code, out, run = _auto(conn)
    assert code == 4, out.message  # stopped before step 2
    expected = "Tests: `python3 -m unittest` · 1 run across 1 step, all passing at the end"
    assert auto.view(conn, log.get_task(conn, run["task_id"]))["tests"] == expected
    code, text = _land(conn, log.get_task(conn, run["task_id"]))
    assert code == 0, text
    entry = _entry(project, run["n"])
    assert entry.rstrip().endswith(expected), entry
    assert "step 2 (#" not in entry  # the stopped step's section never describes what landed


def _entry(project, n):
    return next(e for e in projects.entries_of((project / "HANDOFF.md").read_text()) if e.startswith(f"### #{n} · "))


# ---------- decision 17: the round-file writer on `auto` (34's E1) ----------

def test_a_runs_step_has_its_answer_files_beside_its_prompt_files(project, conn, runner, monkeypatch):
    monkeypatch.setattr(log, "ROUND_WRITER", rounds.writer(secrets=(), out=lambda line: None))
    _route_plan(conn, _approved(conn))
    code, out, run = _auto(conn)
    assert code == 0, out.message
    for step in _steps(conn, run):
        folder = rounds.log_folder(conn) / "tasks" / step["task_id"]
        names = sorted(p.name for p in folder.iterdir())
        assert "01-do-claude.md" in names and "02-check-chatgpt.md" in names, names
        assert "01-do-claude-prompt.md" in names
        for call in log.calls_for(conn, step["task_id"]):
            assert call["round_file"] and (rounds.log_folder(conn) / call["round_file"]).exists()


def test_main_installs_the_round_file_writer_for_auto(tmp_path, monkeypatch, capsys):
    world = MainWorld(monkeypatch, tmp_path, capsys)
    installed = []
    monkeypatch.setattr(cli.rounds, "writer", lambda **kw: installed.append("writer") or (lambda conn, call_id: None))
    world.run("status")
    assert installed == []
    world.run("auto", "garden", "--status")
    assert installed == ["writer"]
