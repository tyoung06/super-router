"""Build brief 34 (decisions 1 to 9): the run. `sr auto <project> --on` on an approved two-step plan, each step a task of its
team in the run's one copy with its `--step`, the ticks written in the copy and never committed mid-run, the run finished
and waiting to land; Land run as one commit with one entry; Undo; the refusals; the dry run; stop-here; the budget and its
hook; --off; the retry; going on; land so far; cancel as Discard run; land, undo and discard refused on a step. Fakes
only (a throwaway git project under tmp); no model call."""
import json
from pathlib import Path

import pytest

from router import __main__ as cli
from router import auto, copies, log, plan, plan_limit, receipt, state
from tests.helpers import fake_label
from tests.test_copies import git as _git_bytes
from tests.test_filemode_flow import CODE, CopyWorker, conn, project, runner  # noqa: F401 (fixtures)
from tests.test_handoff_contract import HANDOFF
from tests.test_loop import Clock, Webhook
from tests.test_plan_approval import _land, _planned
from tests.test_relay import CONFIG, ROSTER, Chat

LOADED = cli._presets_or_none(ROSTER)


class _Out:
    def __init__(self, text):
        self.stdout = text


def git(folder, *args):
    found = _git_bytes(folder, *args)
    return _Out(found.decode() if isinstance(found, bytes) else str(found))
STEP1 = ("Made the skeleton.\n\n## Handoff\n### Produced\ncli.py and test_cli.py added\n### Status\nruns\n### Next\n"
         "step 2", {"cli.py": "print('help')\n", "test_cli.py": "import unittest\n"})
STEP2 = ("Added the conversion.\n\n## Handoff\n### Produced\nconvert.py and test_convert.py added\n### Status\nboth steps "
         "done\n### Next\na README", {"convert.py": "def c_to_f(c):\n    return c * 9 / 5 + 32\n",
                                      "test_convert.py": "import unittest\n"})


def _approved(conn):
    w, row = _planned(conn)
    assert _land(conn, row)[0] == 0
    return log.get_task(conn, row["task_id"])


def _route_plan(conn, plan_row, *, keep_key=False):
    """The test plan's step 2 is redteam's (test_plan_contract.GOOD); for most runs both steps go as Route, by the owner's
    edit before the approval (`plan.edit`), so the fakes are the route loop's. Its needs: the test command is set on the
    project (Auto never starts a step with an unmet need), and step 2's key need is dropped unless `keep_key`."""
    from router import projects
    record = plan.record_of(plan_row)
    record, why = plan.edit(record, 2, "team", "route")
    assert record is not None, why
    if not keep_key:
        record["needs"] = [n for n in record.get("needs") or [] if n.get("kind") != "key"]
    log.set_plan(conn, plan_row["task_id"], record)
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    return log.get_task(conn, plan_row["task_id"])


NO_GROK = {k: v for k, v in CONFIG.items() if "GROK" not in k}  # Grok Bot not set up: no third agent to check


def _auto(conn, name="garden", *, worker=None, chatgpt=None, environ=None, on=True, off=False, status=False, dry_run=False,
          files_ready=None, hindsight=None, hook=None, chatgpt_given=True, available=None, config=CONFIG):
    clock, hook = Clock(), hook or Webhook()
    out = receipt.Receipt()
    chatgpt = (chatgpt or Chat("PASS", "PASS", "PASS", "PASS")) if chatgpt_given else None
    code = cli.cmd_auto([name], conn=conn, config=config, roster=ROSTER, loaded=LOADED, environ=environ or {},
                        settings_paths=[], label=fake_label(CODE), post=hook.post, worker=worker or CopyWorker(STEP1, STEP2),
                        chatgpt=chatgpt, codex_login=lambda: True, fetch=hook.fetch,
                        close=hook.close, sleep=clock.sleep, clock=clock, files_ready=files_ready or (lambda: (True, None)),
                        hindsight=hindsight, available=available, on=on, off=off, status=status, dry_run=dry_run, out=out)
    runs_ = [r for r in log.recent_tasks(conn, 50) if r["mode"] == "auto"]
    return code, out, runs_[0] if runs_ else None


def _steps(conn, run):
    return log.pieces_of(conn, run["task_id"])


# ---------- the run (decisions 1, 2 and 8) ----------

def test_a_run_carries_both_steps_in_one_copy_then_waits_to_land(project, conn, runner):
    plan_row = _route_plan(conn, _approved(conn))
    before = git(project, "rev-parse", "HEAD").stdout.strip()
    code, out, run = _auto(conn)
    assert code == 0, out.message
    assert run["mode"] == "auto" and run["status"] == "done" and run["project"] == "garden"
    record = log.auto_of(run)
    assert [s["state"] for s in record["steps"]] == ["done", "done"] and record["from_step"] == 1
    steps = _steps(conn, run)
    assert [(log.plan_step_of(s)["step"], s["parent"], s["mode"], s["status"]) for s in steps] == [
        (1, run["task_id"], "route", "done"), (2, run["task_id"], "route", "done")]
    # one copy: every step built in the run's copy from its snapshot; the step rows point at it
    files = log.project_files_of(steps[0])
    assert files["owner"] == run["task_id"] and files["start"] == "step-1-1-start"
    assert log.project_files_of(steps[1])["start"] == "step-2-1-start"
    assert copies.has_snapshot(run["task_id"], "step-1-1-start") and copies.has_snapshot(run["task_id"], "step-2-1-start")
    folder = copies.folder_of(run["task_id"])
    assert (folder / "cli.py").exists() and (folder / "convert.py").exists()
    # the tick in the copy's docs/PLAN.md, nothing committed in the folder mid-run
    text = (folder / "docs" / "PLAN.md").read_text()
    assert "- [x] **Step 1.**" in text and "- [x] **Step 2.**" in text and "2 of 2 steps done" in text
    assert git(project, "rev-parse", "HEAD").stdout.strip() == before
    assert git(project, "status", "--porcelain").stdout.strip() == ""
    # the run waits to land: it is the project's open task; its steps aren't; the plan line reads 0 of 2
    found = state.of(run, [])
    assert found.waiting_on == "land" and log.open_task_for(conn, "garden")["task_id"] == run["task_id"]
    assert plan.tick_numbers(plan.ticks(conn, plan_row)) == {}
    assert auto.view(conn, run)["state"] == "finished" and auto.words(run, record) == "Auto finished: land the run?"
    # the budget and the calls used
    assert record["budget"] == auto.budget_for(record["estimate"]["max_calls"]) and record["used"] >= 2
    # no entry mid-run: HANDOFF.md holds the plan's entry only
    handoff = (project / "HANDOFF.md").read_text()
    assert "auto" not in handoff.lower()


def test_land_run_is_one_commit_with_one_entry_and_the_ticks_then_undo_takes_it_back(project, conn, runner):
    plan_row = _route_plan(conn, _approved(conn))
    code, out, run = _auto(conn)
    assert code == 0, out.message
    before = git(project, "rev-parse", "HEAD").stdout.strip()
    code, text = _land(conn, run)
    assert code == 0, text
    after = git(project, "rev-parse", "HEAD").stdout.strip()
    assert after != before and git(project, "rev-parse", f"{after}~1").stdout.strip() == before  # one commit
    shown = git(project, "show", "--stat", "--format=", "HEAD").stdout
    for name in ("cli.py", "test_cli.py", "convert.py", "test_convert.py", "docs/PLAN.md", "HANDOFF.md"):
        assert name in shown, name
    handoff = (project / "HANDOFF.md").read_text()
    assert f"### #{run['n']} · " in handoff and "auto · plan #" in handoff
    assert "step 1 (#" in handoff and "cli.py and test_cli.py added" in handoff and "convert.py and test_convert.py added" in handoff
    assert "Status:\nboth steps done" in handoff and "Next:\na README" in handoff
    assert git(project, "status", "--porcelain").stdout.strip() == ""
    plan_md = (project / "docs" / "PLAN.md").read_text()
    assert "- [x] **Step 1.**" in plan_md and "- [x] **Step 2.**" in plan_md and "2 of 2 steps done" in plan_md
    steps = _steps(conn, run)
    assert plan.tick_numbers(plan.ticks(conn, log.get_task(conn, plan_row["task_id"]))) == {1: steps[0]["n"], 2: steps[1]["n"]}
    assert plan.first_open(conn, log.get_task(conn, plan_row["task_id"])) is None
    # Undo: one commit back, docs/PLAN.md with both steps open
    code, text = _land(conn, log.get_task(conn, run["task_id"]), verb="undo")
    assert code == 0, text
    assert git(project, "rev-parse", "HEAD~1").stdout.strip() == after
    plan_md = (project / "docs" / "PLAN.md").read_text()
    assert "- [ ] **Step 1.**" in plan_md and "- [ ] **Step 2.**" in plan_md and "0 of 2 steps done" in plan_md
    assert plan.tick_numbers(plan.ticks(conn, log.get_task(conn, plan_row["task_id"]))) == {}
    assert not (project / "convert.py").exists()


def test_a_step_never_lands_on_its_own(project, conn, runner):
    _route_plan(conn, _approved(conn))
    code, out, run = _auto(conn)
    step = _steps(conn, run)[0]
    for verb in ("land", "undo", "discard"):
        lines = []
        code = cli.cmd_land([step["task_id"]], conn=conn, config=CONFIG, verb=verb, out=lines.append)
        assert code == 2 and "is a step of run" in "\n".join(lines), verb


# ---------- the refusals (decision 1) ----------

def test_on_is_refused_with_nothing_written_without_a_plan_a_step_or_file_mode(project, conn, runner):
    code, out, run = _auto(conn)
    assert (code, out.code) == (2, "auto_refused") and "no current plan" in out.message and run is None
    assert log.recent_tasks(conn, 50) == []
    plan_row = _route_plan(conn, _approved(conn))
    rows_before = len(log.recent_tasks(conn, 50))
    code, out, run = _auto(conn, files_ready=lambda: (False, "Claude's file check failed on this version"))
    assert (code, out.code) == (2, "auto_refused") and "file mode is off" in out.message
    assert len(log.recent_tasks(conn, 50)) == rows_before
    code, out, run = _auto(conn, name="nope")
    assert (code, out.code) == (2, "auto_refused") and "no project nope" in out.message
    # an open task of the project, other than its own run
    code, said, row = cli.cmd_route("x", conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                                    label=fake_label(CODE), post=Webhook().post, worker=CopyWorker(STEP1), chatgpt=Chat("PASS"),
                                    codex_login=lambda: True, wait=True, project="garden", files_ready=lambda: (True, None),
                                    step_ref=f"{plan_row['task_id']}:1", out=receipt.Receipt()), None, None
    waiting = log.open_task_for(conn, "garden")
    assert waiting is not None and waiting["mode"] == "route"
    code, out, run = _auto(conn)
    assert (code, out.code) == (2, "auto_refused") and f"task #{waiting['n']} is open" in out.message


def test_a_running_or_finished_run_refuses_a_second_on_and_the_steps_need_is_a_refusal_too(project, conn, runner):
    plan_row = _approved(conn)  # step 2 stays redteam: its need (WEATHER_KEY) is unmet
    plan_row = _route_plan(conn, plan_row)
    code, out, run = _auto(conn)
    assert code == 0 and auto.run_state(run, log.auto_of(run)) == "finished"
    code, out, again = _auto(conn)
    assert (code, out.code) == (2, "auto_refused") and "finished and waits to land" in out.message and again["task_id"] == run["task_id"]


def test_a_run_stops_before_a_step_with_an_unmet_need_and_on_is_refused_while_it_stays(project, conn, runner):
    plan_row = _route_plan(conn, _approved(conn), keep_key=True)  # test_plan_contract.GOOD: step 2 needs WEATHER_KEY
    code, out, run = _auto(conn)
    assert code == 4, out.message
    record = log.auto_of(run)
    assert record["stop"]["code"] == "need" and record["stop"]["step"] == 2 and "WEATHER_KEY" in record["stop"]["why"]
    assert [s["state"] for s in record["steps"]] == ["done", "open"]
    code, out, again = _auto(conn)
    assert (code, out.code) == (2, "auto_refused") and "WEATHER_KEY" in out.message and again["task_id"] == run["task_id"]
    from router import whatnow
    line = whatnow.for_project(conn, "garden", LOADED)
    assert line["rung"] == "auto_stopped" and line["control"] == "secrets" and line["need"]["name"] == "WEATHER_KEY"


def test_the_dry_run_names_the_steps_the_budget_and_the_first_stop_here_and_writes_nothing(project, conn, runner):
    plan_row = _route_plan(conn, _approved(conn))
    rows = len(log.recent_tasks(conn, 50))
    assert cli.cmd_plan_stop_here(f"{plan_row['n']}:2", ["on"], conn=conn, out=receipt.Receipt()) == 0
    code, out, run = _auto(conn, dry_run=True)
    assert code == 0 and run is None and len(log.recent_tasks(conn, 50)) == rows
    doc = out.extra_any["auto"]
    assert doc["steps"] == [1, 2] and doc["first_stop_here"] == 2 and doc["budget"] == auto.budget_for(doc["estimate"]["max_calls"])
    assert doc["words"].startswith("Auto runs steps 1 to 2 of plan #") and "stopping before step 2" in doc["words"]
    assert "up to one step's calls" in doc["overrun"]


# ---------- stop here (decision 6) ----------

def test_a_run_stops_before_a_marked_step_and_on_passes_the_mark(project, conn, runner):
    plan_row = _route_plan(conn, _approved(conn))
    out = receipt.Receipt()
    assert cli.cmd_plan_stop_here(f"{plan_row['n']}:2", ["on"], conn=conn, out=out) == 0 and out.extra["stop_here"] == [2]
    assert git(project, "status", "--porcelain").stdout.strip() == ""  # no commit, docs/PLAN.md untouched
    assert "- [ ] **Step 1.**" in (project / "docs" / "PLAN.md").read_text()
    code, out, run = _auto(conn)
    assert code == 4, out.message
    record = log.auto_of(run)
    assert record["stop"] == {"code": "stop_here", "why": "stop here before step 2", "step": 2}
    assert run["status"] == "returned" and state.of(run, []).waiting_on == "auto"
    assert [s["state"] for s in record["steps"]] == ["done", "open"] and len(_steps(conn, run)) == 1
    assert log.open_task_for(conn, "garden")["task_id"] == run["task_id"]  # a stopped run holds the project
    assert auto.words(run, record) == "Auto stopped: stop here before step 2"
    # --on goes on: the mark is passed for this run, step 2 runs in the same copy, the run finishes
    code, out, run = _auto(conn, worker=CopyWorker(STEP2))
    assert code == 0, out.message
    record = log.auto_of(run)
    assert record["passed_marks"] == [2] and [s["state"] for s in record["steps"]] == ["done", "done"]
    steps = _steps(conn, run)
    assert len(steps) == 2 and log.project_files_of(steps[1])["owner"] == run["task_id"]
    assert (copies.folder_of(run["task_id"]) / "cli.py").exists() and (copies.folder_of(run["task_id"]) / "convert.py").exists()
    assert auto.run_state(run, record) == "finished"
    # unmark: refused for a bad step
    out = receipt.Receipt()
    assert cli.cmd_plan_stop_here(f"{plan_row['n']}:9", ["off"], conn=conn, out=out) == 2 and out.code == "bad_step"
    assert cli.cmd_plan_stop_here(f"{plan_row['n']}:2", ["maybe"], conn=conn, out=receipt.Receipt()) == 2


# ---------- the budget (decision 7) ----------

def test_the_hook_sets_the_budget_and_the_run_stops_at_it_before_the_next_step(project, conn, runner, monkeypatch):
    _route_plan(conn, _approved(conn))
    monkeypatch.setattr(plan_limit, "is_real_log", lambda path, root, run=None: False)
    code, out, run = _auto(conn, environ={"SR_AUTO_BUDGET": "2"})
    assert code == 4 and out.code == "budget", out.message
    record = log.auto_of(run)
    assert record["hook"] is True and record["budget"] == 2 and record["stop"]["code"] == "budget" and record["stop"]["step"] == 2
    assert run["reason_code"] == "budget" and [s["state"] for s in record["steps"]] == ["done", "open"]
    assert record["used"] == 2  # step 1's do and check
    # going on gives used + ceil(1.5 × U_left) without the hook
    code, out, run = _auto(conn, worker=CopyWorker(STEP2))
    assert code == 0, out.message
    record = log.auto_of(run)
    assert record["hook"] is False and record["budget"] == auto.budget_for(record["estimate"]["max_calls"], used=2)
    assert record["budget"] > 2 and [s["state"] for s in record["steps"]] == ["done", "done"]


def test_the_hook_is_refused_on_the_real_log(project, conn, runner, monkeypatch):
    _route_plan(conn, _approved(conn))
    monkeypatch.setattr(plan_limit, "is_real_log", lambda path, root, run=None: True)
    code, out, run = _auto(conn, environ={"SR_AUTO_BUDGET": "2"})
    assert (code, out.code) == (2, "budget") and "scratch log" in out.message and run is None


# ---------- --off, the retry, cancel, land so far (decisions 1, 3, 4 and 8) ----------

def test_off_stops_after_the_step_in_progress(project, conn, runner):
    _route_plan(conn, _approved(conn))

    class Switching(CopyWorker):
        def __call__(self, prompt, copy=None, search=False, **kw):
            found = super().__call__(prompt, copy=copy, search=search, **kw)
            run = next(r for r in log.recent_tasks(conn, 50) if r["mode"] == "auto")
            cli._auto_off(conn, "garden", receipt.Receipt())  # the switch turned off during step 1's call
            return found
    code, out, run = _auto(conn, worker=Switching(STEP1, STEP2))
    assert code == 4, out.message
    record = log.auto_of(run)
    assert record["stop"]["code"] == "off" and [s["state"] for s in record["steps"]] == ["done", "open"]
    assert "--off" not in out.message and len(_steps(conn, run)) == 1  # step 1 finished, step 2 never started
    assert cli._auto_off(conn, "garden", receipt.Receipt()) == 2  # nothing running now
    code, out, run = _auto(conn, worker=CopyWorker(STEP2))  # --on goes on from step 2
    assert code == 0 and auto.run_state(run, log.auto_of(run)) == "finished" and not log.auto_of(run)["off_requested"]


def test_a_step_that_fails_its_check_twice_is_retried_once_from_its_snapshot_then_the_run_stops(project, conn, runner):
    _route_plan(conn, _approved(conn))
    failing = CopyWorker(("bad\n\n" + HANDOFF, {"cli.py": "broken\n"}), ("bad again\n\n" + HANDOFF, {"cli.py": "broken2\n"}),
                         ("bad\n\n" + HANDOFF, {"cli.py": "broken3\n"}), ("bad again\n\n" + HANDOFF, {"cli.py": "broken4\n"}))
    code, out, run = _auto(conn, worker=failing, chatgpt=Chat("FIX\n1. [must] It is broken.", "FIX\n1. not fixed: still broken",
                                                                  "FIX\n1. [must] It is broken.", "FIX\n1. not fixed: still broken"))
    assert code == 4, out.message
    record = log.auto_of(run)
    assert record["stop"]["code"] == "failed" and record["stop"]["step"] == 1
    steps = _steps(conn, run)
    assert len(steps) == 2 and [log.plan_step_of(s)["step"] for s in steps] == [1, 1]  # two attempts, both step 1
    assert [s["status"] for s in steps] == ["done", "done"] and [s["check_state"] for s in steps] == ["failed", "failed"]
    assert record["steps"][0]["attempt"] == 2 and record["steps"][0]["state"] == "failed"
    assert log.project_files_of(steps[1])["start"] == "step-1-2-start"
    assert "retry" in out.message or "once more" in out.message
    assert record["used"] == auto.used_calls(conn, run["task_id"]) >= 8  # both attempts' calls count (do, check, fix, re-check each)
    assert (copies.folder_of(run["task_id"]) / "cli.py").read_text() != "broken2\n"  # the copy went back before the retry
    code, out, again = _auto(conn)  # --on is refused while the cause remains
    assert (code, out.code) == (2, "auto_refused") and "failed its check twice" in out.message


def test_cancel_on_a_stopped_run_is_discard_run(project, conn, runner):
    plan_row = _route_plan(conn, _approved(conn))
    cli.cmd_plan_stop_here(f"{plan_row['n']}:2", ["on"], conn=conn, out=receipt.Receipt())
    code, out, run = _auto(conn)
    assert code == 4 and copies.exists(run["task_id"])
    lines = []
    assert cli.cmd_cancel(conn=conn, words=[run["task_id"]], out=lines.append) == 0
    row = log.get_task(conn, run["task_id"])
    assert log.project_files_of(row)["state"] == "discarded" and not copies.exists(run["task_id"])
    assert "discarded" in (project / "HANDOFF.md").read_text() and log.open_task_for(conn, "garden") is None
    assert auto.run_state(row, log.auto_of(row)) == "discarded" and cli._project_auto(conn, "garden")["switch"] == "off"
    # a finished run's cancel is Discard run too (the mark cleared first, so the new run finishes)
    assert cli.cmd_plan_stop_here(f"{plan_row['n']}:2", ["off"], conn=conn, out=receipt.Receipt()) == 0
    code, out, run = _auto(conn)
    assert code == 0 and auto.run_state(run, log.auto_of(run)) == "finished"
    assert cli.cmd_cancel(conn=conn, words=[run["task_id"]], out=lines.append) == 0
    row = log.get_task(conn, run["task_id"])
    assert log.project_files_of(row)["state"] == "discarded" and not copies.exists(run["task_id"])
    assert (project / "HANDOFF.md").read_text().count("discarded") == 2 and log.open_task_for(conn, "garden") is None


def test_land_the_run_so_far_lands_the_passed_steps_only(project, conn, runner):
    plan_row = _route_plan(conn, _approved(conn))
    cli.cmd_plan_stop_here(f"{plan_row['n']}:2", ["on"], conn=conn, out=receipt.Receipt())
    code, out, run = _auto(conn)
    assert code == 4
    code, text = _land(conn, log.get_task(conn, run["task_id"]))
    assert code == 0, text
    shown = git(project, "show", "--stat", "--format=", "HEAD").stdout
    assert "cli.py" in shown and "convert.py" not in shown and "docs/PLAN.md" in shown
    plan_md = (project / "docs" / "PLAN.md").read_text()
    assert "- [x] **Step 1.**" in plan_md and "- [ ] **Step 2.**" in plan_md
    assert plan.tick_numbers(plan.ticks(conn, log.get_task(conn, plan_row["task_id"]))) == {1: _steps(conn, run)[0]["n"]}
    assert plan.first_open(conn, log.get_task(conn, plan_row["task_id"]))[0] == 2


def test_the_json_and_what_now_carry_the_run(project, conn, runner):
    plan_row = _route_plan(conn, _approved(conn))
    from router import jsonview, whatnow
    cli.cmd_plan_stop_here(f"{plan_row['n']}:2", ["on"], conn=conn, out=receipt.Receipt())
    code, out, run = _auto(conn)
    view = jsonview.task_view(conn, log.get_task(conn, run["task_id"]), loaded=LOADED)
    assert view["auto"]["state"] == "stopped" and view["auto"]["stop"]["code"] == "stop_here" and view["waiting_on"] == "auto"
    assert [s["state"] for s in view["auto"]["steps"]] == ["done", "open"] and view["auto"]["steps"][0]["verdict"] == "passed"
    assert view["piece_of"] is None and view["next"] == []  # a run is no piece and has no chips (decision 12)
    step = jsonview.task_view(conn, _steps(conn, run)[0], loaded=LOADED)  # a step names its run and its step
    assert step["piece_of"] == {"split": None, "run": run["task_id"], "n": run["n"], "piece": None, "step": 1, "team": "route"}
    assert step["next"] == [] and step["plan_step"]["step"] == 1
    line = whatnow.for_project(conn, "garden", LOADED)
    assert line["rung"] == "auto_stopped" and line["words"] == "Auto stopped: stop here before step 2" and line["control"] == "open"
    found = cli._project_auto(conn, "garden")
    assert found["state"] == "stopped" and found["switch"] == "off" and found["run"]["n"] == run["n"]
    code, out, run = _auto(conn, worker=CopyWorker(STEP2))
    line = whatnow.for_project(conn, "garden", LOADED)
    assert line["rung"] == "auto_finished" and line["words"] == "Auto finished: land the run?"
    assert cli._project_auto(conn, "garden")["switch"] == "hidden"
    assert jsonview.task_view(conn, log.get_task(conn, run["task_id"]), loaded=LOADED)["next"] == []
    assert _land(conn, run)[0] == 0  # landed: still no chips on the run; the plan's finish line is What now?'s
    assert jsonview.task_view(conn, log.get_task(conn, run["task_id"]), loaded=LOADED)["next"] == []
    assert whatnow.for_project(conn, "garden", LOADED)["rung"] == "finish"
    out = receipt.Receipt()
    assert cli.cmd_auto(["garden"], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[],
                        label=None, post=None, worker=None, status=True, out=out) == 0
    assert out.document["auto"]["state"] == "landed" and out.document["project"]["switch"] == "hidden"  # every step done


# ---------- going on from the step it stopped on (decisions 4 and 5) ----------

OTHER_PID, OTHER_START = 4321, "2026-10-20T11:00:00+00:00"   # gone in the fake process table (tests/conftest.py)


def _stopped_before_2(conn):
    plan_row = _route_plan(conn, _approved(conn))
    cli.cmd_plan_stop_here(f"{plan_row['n']}:2", ["on"], conn=conn, out=receipt.Receipt())
    code, out, run = _auto(conn)
    assert code == 4, out.message
    return plan_row, run


def _step_2_row(conn, run, plan_row, sid):
    """A row of step 2 made by hand, as the loop makes one: the run's step, in the run's copy from its snapshot."""
    from router import filecalls
    run_id = run["task_id"]
    copies.snapshot(run_id, "step-2-1-start")
    log.add_task(conn, sid, "Add the conversion.", "cli", CODE, mode="route", project="garden", parent=run_id,
                 plan_step={"plan": plan_row["task_id"], "step": 2}, run=(OTHER_PID, OTHER_START))
    log.set_route(conn, sid, agents=ROSTER.names, agent="claude", route_reason="best", skill="code", skill_source="jev",
                  checker="chatgpt", check_state="pending")
    log.set_project_files(conn, sid, {**filecalls.piece_record(run_id, 2, log.project_files_of(run)), "start": "step-2-1-start"})
    return log.get_task(conn, sid)


def _dead_during_step_2(conn, run, plan_row, folder, monkeypatch):
    """The run as `sr check` finds it after the Mac slept during step 2's build call: the run and its step held by a pid
    that is gone, the step's note beside the log, its before-call snapshot in the run's copy, a half-written file."""
    from router import runs, search
    run_id, sid = run["task_id"], "sr-20261030-120000-dead"
    record = auto.cleared(log.auto_of(run))
    auto.step_entry(record, 2).update(state="running", attempt=1, task_id=sid)
    log.set_auto(conn, run_id, record)
    log.reopen_run(conn, run_id, run=(OTHER_PID, OTHER_START))
    _step_2_row(conn, run, plan_row, sid)
    copies.snapshot(run_id, f"before-{sid}")
    (copies.folder_of(run_id) / "half-done.txt").write_text("partial\n")
    monkeypatch.setattr(runs, "FOLDER", folder)
    runs.write_note(folder, sid, {"call_id": sid, "kind": "do", "agent": "claude", "stage": None, "role": None,
                                  "search": {"state": search.OFF_FILE}, "context": None, "memory": None,
                                  "pid": OTHER_PID, "started": OTHER_START})
    return sid


def _check(conn, worker=None, chatgpt=None):
    from tests.test_loop import Scripted
    hook, lines = Webhook(), []
    worker = worker or Scripted("never")
    code = cli.cmd_check(conn=conn, config=CONFIG, environ={}, settings_paths=[], post=hook.post, worker=worker,
                         chatgpt=chatgpt or Chat("never"), codex_login=lambda: True, fetch=hook.fetch, close=hook.close,
                         out=lines.append)
    return code, lines, worker


def test_sr_check_leaves_a_stopped_run_alone(project, conn, runner):
    plan_row, run = _stopped_before_2(conn)
    code, lines, worker = _check(conn)
    assert code == 0 and worker.prompts == []
    again = log.get_task(conn, run["task_id"])
    assert dict(again) == dict(run) and len(_steps(conn, run)) == 1


def test_a_process_that_ended_is_a_stop_and_on_resumes_the_step_in_the_same_copy(project, conn, runner, tmp_path, monkeypatch):
    from router import resume
    plan_row, run = _stopped_before_2(conn)
    sid = _dead_during_step_2(conn, run, plan_row, tmp_path / "run", monkeypatch)
    code, lines, worker = _check(conn)
    assert code == 0 and worker.prompts == []
    run = log.get_task(conn, run["task_id"])
    record = log.auto_of(run)
    assert run["status"] == "returned" and run["pid"] is None and state.of(run, []).waiting_on == "auto"
    assert record["stop"]["code"] == "stopped" and "process ended" in record["stop"]["why"] and record["stop"]["step"] == 2
    assert auto.step_entry(record, 2)["state"] == "stopped" and auto.words(run, record).startswith("Auto stopped: the process ended")
    step = log.get_task(conn, sid)
    assert step["status"] == "failed" and log.calls_for(conn, sid)[-1]["reason_code"] == "process_ended"
    # --on: the step is resumed as Resume allows, in the run's copy, put back as it was before the stopped call
    worker = CopyWorker(STEP2)
    code, out, run = _auto(conn, worker=worker)
    assert code == 0, out.message
    assert "goes on where it stopped (Resume, claude)" in out.message
    calls = log.calls_for(conn, sid)
    assert any(resume.is_resume(c) for c in calls) and log.get_task(conn, sid)["status"] == "done"
    assert Path(worker.calls[0]["copy"].folder) == copies.folder_of(run["task_id"])
    assert not (copies.folder_of(run["task_id"]) / "half-done.txt").exists()
    assert (copies.folder_of(run["task_id"]) / "convert.py").exists()
    record = log.auto_of(run)
    assert [s["state"] for s in record["steps"]] == ["done", "done"] and auto.run_state(run, record) == "finished"
    assert len(_steps(conn, run)) == 2 and record["passed_marks"] == [2]  # no new row: the step's own row went on


def test_a_step_resumed_by_hand_is_taken_as_it_stands(project, conn, runner, tmp_path, monkeypatch):
    plan_row, run = _stopped_before_2(conn)
    sid = _dead_during_step_2(conn, run, plan_row, tmp_path / "run", monkeypatch)
    assert _check(conn)[0] == 0
    lines = []
    code = cli.cmd_resume([sid], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[],
                          post=Webhook().post, worker=CopyWorker(STEP2), chatgpt=Chat("PASS"), codex_login=lambda: True,
                          out=lines.append)
    assert code == 0, lines
    assert log.get_task(conn, sid)["status"] == "done" and log.get_task(conn, run["task_id"])["status"] == "returned"
    worker = CopyWorker()
    code, out, run = _auto(conn, worker=worker)
    assert code == 0, out.message
    assert worker.calls == [] and "read as it stands" in out.message
    assert auto.run_state(run, log.auto_of(run)) == "finished" and len(_steps(conn, run)) == 2


def test_going_on_from_a_step_that_cannot_be_resumed_starts_it_again_from_its_snapshot(project, conn, runner):
    plan_row, run = _stopped_before_2(conn)
    run_id, sid = run["task_id"], "sr-20261030-120000-canc"
    # the run as it stands after step 2 was cancelled mid-build (sr cancel): its row cancelled, the copy half-written
    record = auto.cleared(log.auto_of(run))
    auto.step_entry(record, 2).update(state="stopped", attempt=1, task_id=sid)
    log.set_auto(conn, run_id, auto.with_stop(record, "cancelled", "step 2 (#9) was cancelled", step=2))
    _step_2_row(conn, run, plan_row, sid)
    log.set_cancelled(conn, sid)
    (copies.folder_of(run_id) / "half-done.txt").write_text("partial\n")
    worker = CopyWorker(STEP2)
    code, out, run = _auto(conn, worker=worker)
    assert code == 0, out.message
    assert "can't be resumed" in out.message and "starts again" in out.message
    record = log.auto_of(run)
    assert auto.step_entry(record, 2)["attempt"] == 2 and auto.step_entry(record, 2)["state"] == "done"
    steps = _steps(conn, run)
    assert [(log.plan_step_of(s)["step"], s["status"]) for s in steps] == [(1, "done"), (2, "cancelled"), (2, "done")]
    assert log.project_files_of(steps[2])["start"] == "step-2-2-start" and copies.has_snapshot(run_id, "step-2-2-start")
    assert not (copies.folder_of(run_id) / "half-done.txt").exists() and (copies.folder_of(run_id) / "convert.py").exists()
    assert auto.run_state(run, record) == "finished"


# ---------- the rest of the brief's list (§4) ----------

def test_on_is_refused_while_the_run_is_running(project, conn, runner):
    _route_plan(conn, _approved(conn))
    seen = []

    class Asking(CopyWorker):
        def __call__(self, prompt, copy=None, search=False, **kw):
            code, out, run = _auto(conn, worker=CopyWorker())  # a second --on while step 1's call is out
            seen.append((code, out.code, out.message))
            return super().__call__(prompt, copy=copy, search=search, **kw)
    code, out, run = _auto(conn, worker=Asking(STEP1, STEP2))
    assert code == 0, out.message
    assert all(c == 2 and rc == "auto_refused" and "is running" in m for c, rc, m in seen) and len(seen) == 2


def test_undo_of_the_plans_land_is_refused_during_a_run(project, conn, runner):
    plan_row, run = _stopped_before_2(conn)
    code, text = _land(conn, log.get_task(conn, plan_row["task_id"]), verb="undo")
    assert code == 2 and f"run #{run['n']} is on garden (Auto, stopped)" in text and "land or discard the run first" in text


def test_a_steps_checker_judges_its_part_and_the_tests_run_after_each_build(project, conn, runner):
    _route_plan(conn, _approved(conn))
    chat = Chat("PASS", "PASS")
    code, out, run = _auto(conn, chatgpt=chat)
    assert code == 0, out.message
    first, second = chat.prompts[0], chat.prompts[1]
    assert "+print('help')" in first and "convert.py" not in first
    assert "c_to_f" in second and "+print('help')" not in second  # step 2's check sees step 2's part only
    assert len(runner.runs) == 2  # the project's tests after each build


def test_a_step_with_no_change_gets_its_tick_in_the_copy_and_no_commit(project, conn, runner):
    _route_plan(conn, _approved(conn))
    before = git(project, "rev-parse", "HEAD").stdout.strip()
    nothing = ("Nothing to add: the skeleton is there.\n\n## Handoff\n### Produced\nnothing written\n### Status\nchecked\n"
               "### Next\nstep 2", {})
    code, out, run = _auto(conn, worker=CopyWorker(nothing, STEP2))
    assert code == 0, out.message
    assert git(project, "rev-parse", "HEAD").stdout.strip() == before  # by hand, a no-change step gets a tick commit
    assert [s["state"] for s in log.auto_of(run)["steps"]] == ["done", "done"]
    assert "- [x] **Step 1.**" in (copies.folder_of(run["task_id"]) / "docs" / "PLAN.md").read_text()


def test_at_the_land_each_steps_memory_is_stored_and_none_on_discard(project, conn, runner):
    from tests.fake_hindsight import FakeHindsight
    _route_plan(conn, _approved(conn))
    fake = FakeHindsight()
    code, out, run = _auto(conn, hindsight=fake.client)
    assert code == 0 and fake.retains == []  # nothing before the run lands
    lines = []
    assert cli.cmd_land([run["task_id"]], conn=conn, config=CONFIG, verb="land", out=lines.append, hindsight=fake.client) == 0
    steps = _steps(conn, run)
    assert [r["document_id"] for r in fake.retains] == [f"task-{s['task_id']}" for s in steps]
    assert all(r["tags"] == ["project:garden"] for r in fake.retains)
    assert sum("memory: stored" in line for line in lines) == 2
    # a discarded run stores none
    fake2 = FakeHindsight()
    _land(conn, log.get_task(conn, run["task_id"]), verb="undo")
    code, out, run2 = _auto(conn, worker=CopyWorker(STEP1, STEP2), hindsight=fake2.client)
    assert code == 0
    assert cli.cmd_land([run2["task_id"]], conn=conn, config=CONFIG, verb="discard", out=lines.append, hindsight=fake2.client) == 0
    assert fake2.retains == []


def test_an_unchecked_step_stops_the_run_and_on_goes_on(project, conn, runner):
    _route_plan(conn, _approved(conn))
    code, out, run = _auto(conn, chatgpt_given=False, config=NO_GROK)  # no ChatGPT, no Grok Bot: nobody can check
    assert code == 4, out.message
    assert "unchecked" in out.message
    record = log.auto_of(run)
    assert record["stop"]["code"] == "unchecked" and record["stop"]["step"] == 1
    assert [s["state"] for s in record["steps"]] == ["done", "open"] and _steps(conn, run)[0]["check_state"] != "passed"
    assert "- [x] **Step 1.**" in (copies.folder_of(run["task_id"]) / "docs" / "PLAN.md").read_text()
    code, out, run = _auto(conn, worker=CopyWorker(STEP2), chatgpt_given=False, config=NO_GROK)
    assert code == 4 and log.auto_of(run)["stop"]["step"] == 2  # the owner decided to go on; step 2 is unchecked too
    code, out, run = _auto(conn, chatgpt_given=False, config=NO_GROK)
    assert code == 0 and auto.run_state(run, log.auto_of(run)) == "finished"


def test_a_blocked_step_stops_the_run_and_on_is_refused_while_it_stays(project, conn, runner):
    _route_plan(conn, _approved(conn))
    blocked = ("I can't: the skeleton needs the CLI's name.\n\n" + HANDOFF, {})
    code, out, run = _auto(conn, worker=CopyWorker(blocked), chatgpt=Chat("BLOCKED\n1. [must] It needs the CLI's name."))
    assert code == 4, out.message
    record = log.auto_of(run)
    assert record["stop"]["code"] == "blocked" and record["stop"]["step"] == 1 and record["steps"][0]["state"] == "failed"
    code, out, again = _auto(conn)
    assert (code, out.code) == (2, "auto_refused") and "was blocked" in out.message


def test_a_plan_limit_stop_is_resumed_by_on_in_the_same_copy(project, conn, runner):
    from router import claude_worker, resume
    _route_plan(conn, _approved(conn))
    limit = claude_worker.WorkerError("plan limit on claude: You've hit your limit", code="plan_limit")

    class HalfThenStop(CopyWorker):
        def __call__(self, prompt, copy=None, **kw):
            (Path(copy.folder) / "half-done.txt").write_text("partial\n")
            raise limit
    code, out, run = _auto(conn, worker=HalfThenStop())
    assert code == 4, out.message
    record = log.auto_of(run)
    assert record["stop"]["code"] == "stopped" and "plan_limit" in record["stop"]["why"] and record["steps"][0]["state"] == "stopped"
    step = _steps(conn, run)[0]
    assert log.calls_for(conn, step["task_id"])[-1]["reason_code"] == "plan_limit"
    worker = CopyWorker(STEP1, STEP2)
    code, out, run = _auto(conn, worker=worker)
    assert code == 0, out.message
    assert "goes on where it stopped (Resume, claude)" in out.message
    calls = log.calls_for(conn, step["task_id"])
    assert any(resume.is_resume(c) for c in calls) and not (copies.folder_of(run["task_id"]) / "half-done.txt").exists()
    assert auto.run_state(run, log.auto_of(run)) == "finished" and len(_steps(conn, run)) == 2


def test_a_mark_is_passed_by_an_on_at_that_step_whatever_stopped_the_run(project, conn, runner, monkeypatch):
    plan_row = _route_plan(conn, _approved(conn))
    monkeypatch.setattr(plan_limit, "is_real_log", lambda path, root, run=None: False)
    code, out, run = _auto(conn, environ={"SR_AUTO_BUDGET": "2"})
    assert code == 4 and log.auto_of(run)["stop"]["code"] == "budget" and log.auto_of(run)["passed_marks"] == []
    # set, cleared and set again during the stopped run: no commit either way
    before = git(project, "rev-parse", "HEAD").stdout.strip()
    assert cli.cmd_plan_stop_here(f"{plan_row['n']}:2", ["on"], conn=conn, out=receipt.Receipt()) == 0
    assert cli.cmd_plan_stop_here(f"{plan_row['n']}:2", ["off"], conn=conn, out=receipt.Receipt()) == 0
    assert cli.cmd_plan_stop_here(f"{plan_row['n']}:2", ["on"], conn=conn, out=receipt.Receipt()) == 0
    assert git(project, "rev-parse", "HEAD").stdout.strip() == before
    assert git(project, "status", "--porcelain").stdout.strip() == ""
    code, out, run = _auto(conn, worker=CopyWorker(STEP2))  # --on at step 2: the mark is passed, whatever the stop before
    assert code == 0, out.message
    assert log.auto_of(run)["passed_marks"] == [2] and auto.run_state(run, log.auto_of(run)) == "finished"


def test_a_run_started_mid_plan_covers_the_steps_left(project, conn, runner):
    plan_row = _route_plan(conn, _approved(conn))
    step1 = plan.steps_of(plan.record_of(plan_row))[0]["text"]
    out = receipt.Receipt()
    code = cli.cmd_route(step1, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=fake_label(CODE),
                         post=Webhook().post, worker=CopyWorker(STEP1), chatgpt=Chat("PASS"), codex_login=lambda: True, wait=True,
                         project="garden", files_ready=lambda: (True, None), step_ref=f"{plan_row['task_id']}:1", out=out)
    assert code == 0, out.message
    assert _land(conn, log.get_task(conn, out.task_id))[0] == 0
    code, out, run = _auto(conn, dry_run=True)
    assert code == 0 and out.extra_any["auto"]["steps"] == [2]
    doc = out.extra_any["auto"]
    assert doc["budget"] == auto.budget_for(doc["estimate"]["max_calls"]) and doc["words"].startswith("Auto runs step 2 of plan #")
    code, out, run = _auto(conn, worker=CopyWorker(STEP2))
    assert code == 0, out.message
    record = log.auto_of(run)
    assert record["from_step"] == 2 and [s["k"] for s in auto.covered(record)] == [2] and auto.run_state(run, record) == "finished"
    assert _land(conn, run)[0] == 0
    plan_md = (project / "docs" / "PLAN.md").read_text()
    assert "- [x] **Step 1.**" in plan_md and "- [x] **Step 2.**" in plan_md and "2 of 2 steps done" in plan_md


def test_a_steps_prompts_are_build_step_ks_byte_for_byte(project, conn, runner):
    plan_row = _route_plan(conn, _approved(conn))
    step1 = plan.steps_of(plan.record_of(plan_row))[0]["text"]
    hand, hand_chat = CopyWorker(STEP1), Chat("PASS")
    out = receipt.Receipt()
    code = cli.cmd_route(step1, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=fake_label(CODE),
                         post=Webhook().post, worker=hand, chatgpt=hand_chat, codex_login=lambda: True, wait=True,
                         project="garden", files_ready=lambda: (True, None), step_ref=f"{plan_row['task_id']}:1", out=out)
    assert code == 0, out.message
    # the by-hand task is put aside with no entry and no commit, so the run's step 1 sees the same project
    log.set_cancelled(conn, out.task_id, allowed_from=("done",))
    log.update_project_files(conn, out.task_id, state="discarded")
    copies.remove(out.task_id)
    worker, chat = CopyWorker(STEP1, STEP2), Chat("PASS", "PASS")
    code, out, run = _auto(conn, worker=worker, chatgpt=chat)
    assert code == 0, out.message
    assert worker.calls[0]["prompt"] == hand.calls[0]["prompt"]
    assert chat.prompts[0] == hand_chat.prompts[0]


def _research_plan(conn):
    plan_row = _route_plan(conn, _approved(conn))
    record, why = plan.edit(plan.record_of(plan_row), 2, "team", "research-build")
    assert record is not None, why
    log.set_plan(conn, plan_row["task_id"], record)
    return log.get_task(conn, plan_row["task_id"])


def test_a_grok_research_stage_inside_a_run_is_waited_for(project, conn, runner):
    from tests.test_relay import GOOD_NOTE, RelayHook
    _research_plan(conn)
    hook = RelayHook(s1=GOOD_NOTE)
    code, out, run = _auto(conn, hook=hook, chatgpt=Chat("PASS", "PASS"))
    assert code == 0, out.message
    steps = _steps(conn, run)
    assert steps[1]["mode"] == "relay" and steps[1]["preset"] == "research-build"
    calls = log.calls_for(conn, steps[1]["task_id"])
    assert [(c["agent"], c["kind"], c["status"]) for c in calls] == [("grok", "stage", "done"), ("claude", "stage", "done"),
                                                                     ("chatgpt", "check", "done")]
    assert len(hook.sent) == 1 and hook.closed  # one Grok send, its issue closed
    record = log.auto_of(run)
    assert record["steps"][1]["calls"] == 3 and record["used"] == 5 and auto.run_state(run, record) == "finished"


def test_an_overdue_grok_stage_inside_a_run_is_taken_over(project, conn, runner, monkeypatch):
    from router import takeover
    from tests.test_relay import GOOD_NOTE, RelayHook
    _research_plan(conn)
    from tests.test_routing_availability import Gate
    monkeypatch.setattr(cli, "BACKDATE_MINUTES", 10)  # the overdue hook: the send is logged 2N early
    hook = RelayHook()  # Grok Bot never answers
    code, out, run = _auto(conn, hook=hook, chatgpt=Chat("PASS", GOOD_NOTE, "PASS"), available=Gate())  # a gate: main's
    assert code == 0, out.message
    steps = _steps(conn, run)
    calls = log.calls_for(conn, steps[1]["task_id"])
    assert any(takeover.is_takeover(c) for c in calls) and calls[0]["agent"] == "grok" and calls[1]["agent"] == "chatgpt"
    record = log.auto_of(run)
    assert record["steps"][1]["calls"] == 4 and record["used"] == 6 and auto.run_state(run, record) == "finished"


# ---------- the review's fixes (brief 34): cancel as a stop, Land's refusals on so far, a stale running step, an intake
# refusal, Claude unavailable, a credits stop, the models, --source, the stopped line's Open, a non-Claude step ----------

def test_sr_cancel_on_a_running_run_is_a_stop_that_keeps_the_copy(project, conn, runner):
    _route_plan(conn, _approved(conn))
    said = []

    class Cancelling(CopyWorker):
        def __call__(self, prompt, copy=None, search=False, **kw):
            run = next(r for r in log.recent_tasks(conn, 50) if r["mode"] == "auto")
            (Path(copy.folder) / "half.txt").write_text("partial\n")
            code = cli.cmd_cancel(conn=conn, words=[run["task_id"]], kill=lambda pid, sig: (_ for _ in ()).throw(KeyboardInterrupt()),
                                  out=said.append)
            return super().__call__(prompt, copy=copy, search=search, **kw)  # never reached: the interrupt is raised
    code, out, run = _auto(conn, worker=Cancelling(STEP1, STEP2))
    assert code in (4, 130), out.message
    record = log.auto_of(run)
    assert run["status"] == "returned" and record["stop"]["code"] == "cancelled" and record["stop"]["step"] == 1
    assert record["steps"][0]["state"] == "stopped" and copies.exists(run["task_id"])
    assert any("keeps its copy" in line for line in said)
    code, out, run = _auto(conn, worker=CopyWorker(STEP1, STEP2))  # --on goes on: step 1 started again from its snapshot
    assert code == 0, out.message
    assert auto.run_state(run, log.auto_of(run)) == "finished" and not (copies.folder_of(run["task_id"]) / "half.txt").exists()


def test_sr_cancel_on_a_running_run_whose_process_is_gone_writes_the_stop(project, conn, runner, monkeypatch):
    from router import runs
    plan_row, run = _stopped_before_2(conn)
    sid = "sr-20261030-120000-gone"
    record = auto.cleared(log.auto_of(run))
    auto.step_entry(record, 2).update(state="running", attempt=1, task_id=sid)
    log.set_auto(conn, run["task_id"], record)
    log.reopen_run(conn, run["task_id"], run=(OTHER_PID, OTHER_START))  # a pid the fake process table says is gone
    _step_2_row(conn, run, plan_row, sid)
    lines = []
    assert cli.cmd_cancel(conn=conn, words=[run["task_id"]], out=lines.append) == 0
    run = log.get_task(conn, run["task_id"])
    record = log.auto_of(run)
    assert run["status"] == "returned" and run["pid"] is None and record["stop"]["code"] == "cancelled"
    assert record["steps"][1]["state"] == "stopped" and copies.exists(run["task_id"])
    assert cli._project_auto(conn, "garden")["switch"] == "off"


def test_a_land_refused_after_so_far_leaves_the_run_stopped_as_it_was(project, conn, runner):
    plan_row, run = _stopped_before_2(conn)
    sid = "sr-20261030-120000-half"
    record = auto.cleared(log.auto_of(run))
    auto.step_entry(record, 2).update(state="stopped", attempt=1, task_id=sid)
    log.set_auto(conn, run["task_id"], auto.with_stop(record, "cancelled", "step 2 was cancelled", step=2))
    _step_2_row(conn, run, plan_row, sid)
    log.set_cancelled(conn, sid)
    (copies.folder_of(run["task_id"]) / "half.txt").write_text("partial\n")  # step 2's half-done work in the copy
    (project / "cli.py").write_text("an uncommitted edit\n")  # the land refuses: the folder has edits on a path it changes
    code, text = _land(conn, log.get_task(conn, run["task_id"]))
    assert code == 2 and "stopped again as it was" in text, text
    run = log.get_task(conn, run["task_id"])
    assert run["status"] == "returned" and state.of(run, []).waiting_on == "auto" and log.auto_of(run)["stop"]["code"] == "cancelled"
    assert log.project_files_of(run)["state"] == "none" and (copies.folder_of(run["task_id"]) / "half.txt").exists()
    (project / "cli.py").unlink()
    code, out, again = _auto(conn, worker=CopyWorker(STEP2))  # --on still goes on, in the same copy
    assert code == 0, out.message
    assert auto.run_state(again, log.auto_of(again)) == "finished"


def test_land_so_far_then_undo_puts_the_folder_back(project, conn, runner):
    plan_row, run = _stopped_before_2(conn)
    code, text = _land(conn, log.get_task(conn, run["task_id"]))
    assert code == 0, text
    landed = git(project, "rev-parse", "HEAD").stdout.strip()
    assert (project / "cli.py").exists()
    code, text = _land(conn, log.get_task(conn, run["task_id"]), verb="undo")
    assert code == 0, text
    assert git(project, "rev-parse", "HEAD~1").stdout.strip() == landed and not (project / "cli.py").exists()
    assert log.project_files_of(log.get_task(conn, run["task_id"]))["state"] == "undone"
    assert "- [ ] **Step 1.**" in (project / "docs" / "PLAN.md").read_text()
    assert plan.tick_numbers(plan.ticks(conn, log.get_task(conn, plan_row["task_id"]))) == {}


def test_a_stale_running_step_at_on_is_started_again(project, conn, runner):
    plan_row, run = _stopped_before_2(conn)
    sid = "sr-20261030-120000-stal"
    record = auto.cleared(log.auto_of(run))
    auto.step_entry(record, 2).update(state="running", attempt=1, task_id=sid)  # as an interrupt outside the step left it
    log.set_auto(conn, run["task_id"], auto.with_stop(record, "cancelled", "Ctrl+C", step=2))
    _step_2_row(conn, run, plan_row, sid)
    code, out, run = _auto(conn, worker=CopyWorker(STEP2))
    assert code == 0, out.message
    assert auto.run_state(run, log.auto_of(run)) == "finished" and log.get_task(conn, sid)["status"] == "cancelled"


def test_a_step_refused_at_intake_stops_the_run_and_gives_the_attempt_back(project, conn, runner, monkeypatch):
    _route_plan(conn, _approved(conn))
    real = cli.cmd_route
    calls = {"n": 0}

    def once(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            kw["out"]("Refused: something at intake. Nothing was logged or sent.")
            return 2
        return real(*a, **kw)
    monkeypatch.setattr(cli, "cmd_route", once)
    code, out, run = _auto(conn)
    assert code == 4 and log.auto_of(run)["stop"]["code"] == "refused"
    assert log.auto_of(run)["steps"][0] == {**log.auto_of(run)["steps"][0], "state": "open", "attempt": 0}
    code, out, run = _auto(conn, worker=CopyWorker(STEP1, STEP2))
    assert code == 0 and log.auto_of(run)["steps"][0]["attempt"] == 1 and auto.run_state(run, log.auto_of(run)) == "finished"


def test_claude_unavailable_refuses_on_and_stops_a_run_before_its_next_step(project, conn, runner):
    from router import availability
    _route_plan(conn, _approved(conn))

    class Down:  # Claude unavailable (the fake Gate never takes Claude out: it is required everywhere else)
        def __call__(self, name, fresh=False):
            return availability.Availability(name != "claude", "Claude: not signed in" if name == "claude" else None,
                                             "signed_out" if name == "claude" else None)

        def of(self, names, fresh=False):
            return {n: self(n) for n in names}
    code, out, run = _auto(conn, available=Down())
    assert (code, out.code) == (2, "auto_refused") and "Claude isn't available" in out.message and run is None

    class Flipping:  # Claude available through step 1, gone once a step of the run is done (before step 2's checks)
        def __call__(self, name, fresh=False):
            gone = any(r["parent"] and r["status"] == "done" for r in log.recent_tasks(conn, 50))
            if name == "claude" and gone:
                return availability.Availability(False, "Claude: not signed in", "signed_out")
            return availability.Availability(True, None, None)

        def of(self, names, fresh=False):
            return {n: self(n) for n in names}
    code, out, run = _auto(conn, available=Flipping())
    assert code == 4, out.message
    record = log.auto_of(run)
    assert record["stop"]["code"] == "unavailable" and record["stop"]["step"] == 2 and [s["state"] for s in record["steps"]] == ["done", "open"]
    code, out, again = _auto(conn, available=Down())
    assert (code, out.code) == (2, "auto_refused") and again["task_id"] == run["task_id"]


def test_a_credits_stop_is_started_again_by_on(project, conn, runner):
    from router import claude_worker
    _route_plan(conn, _approved(conn))
    credits = claude_worker.WorkerError("Claude: out of credits", code="credits")

    class Broke(CopyWorker):
        def __call__(self, prompt, copy=None, **kw):
            raise credits
    code, out, run = _auto(conn, worker=Broke())
    assert code == 4, out.message
    record = log.auto_of(run)
    assert record["stop"]["code"] == "stopped" and record["steps"][0]["state"] == "stopped"
    code, out, run = _auto(conn, worker=CopyWorker(STEP1, STEP2))
    assert code == 0, out.message
    assert ("starts again" in out.message or "goes on where it stopped" in out.message)  # as Resume allows
    assert auto.run_state(run, log.auto_of(run)) == "finished"


def test_a_steps_models_and_source_are_build_step_ks_and_the_switchs(project, conn, runner):
    plan_row = _route_plan(conn, _approved(conn))
    step1 = plan.steps_of(plan.record_of(plan_row))[0]["text"]
    out = receipt.Receipt()
    code = cli.cmd_route(step1, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=fake_label(CODE),
                         post=Webhook().post, worker=CopyWorker(STEP1), chatgpt=Chat("PASS"), codex_login=lambda: True, wait=True,
                         project="garden", files_ready=lambda: (True, None), step_ref=f"{plan_row['task_id']}:1", out=out)
    assert code == 0, out.message
    by_hand = [(c["kind"], c["agent"], c["model"], c["effort"]) for c in log.calls_for(conn, out.task_id)]
    log.set_cancelled(conn, out.task_id, allowed_from=("done",))
    log.update_project_files(conn, out.task_id, state="discarded")
    copies.remove(out.task_id)
    clock, hook = Clock(), Webhook()
    said = receipt.Receipt()
    code = cli.cmd_auto(["garden"], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[],
                        label=fake_label(CODE), post=hook.post, worker=CopyWorker(STEP1, STEP2), chatgpt=Chat("PASS", "PASS"),
                        codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                        files_ready=lambda: (True, None), on=True, source="ui", out=said)
    assert code == 0, said.message
    run = log.get_task(conn, said.task_id)
    steps = _steps(conn, run)
    assert [(c["kind"], c["agent"], c["model"], c["effort"]) for c in log.calls_for(conn, steps[0]["task_id"])] == by_hand
    assert run["source"] == "ui" and [s["source"] for s in steps] == ["ui", "ui"]


def test_status_with_no_run_and_the_stopped_lines_open_on_the_step(project, conn, runner):
    from router import whatnow
    plan_row = _route_plan(conn, _approved(conn))
    out = receipt.Receipt()
    assert cli.cmd_auto(["garden"], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[],
                        label=None, post=None, worker=None, status=True, out=out) == 0
    assert "no run yet" in out.message and out.document["auto"] is None and out.document["project"]["switch"] == "off"
    failing = CopyWorker(("bad\n\n" + HANDOFF, {"cli.py": "broken\n"}), ("bad again\n\n" + HANDOFF, {"cli.py": "broken2\n"}),
                         ("bad\n\n" + HANDOFF, {"cli.py": "broken3\n"}), ("bad again\n\n" + HANDOFF, {"cli.py": "broken4\n"}))
    code, out, run = _auto(conn, worker=failing, chatgpt=Chat("FIX\n1. [must] It is broken.", "FIX\n1. not fixed: still broken",
                                                                  "FIX\n1. [must] It is broken.", "FIX\n1. not fixed: still broken"))
    assert code == 4
    line = whatnow.for_project(conn, "garden", LOADED)
    assert line["rung"] == "auto_stopped" and line["control"] == "open" and line["task_id"] == _steps(conn, run)[-1]["task_id"]
    assert line["words"].startswith("Auto stopped: step 1")


def test_a_step_by_another_doer_keeps_the_run_and_its_handoff(project, conn, runner):
    from router import context
    plan_row = _route_plan(conn, _approved(conn))
    cli.cmd_plan_stop_here(f"{plan_row['n']}:2", ["on"], conn=conn, out=receipt.Receipt())
    code, out, run = _auto(conn)
    sid = "sr-20261030-120000-chat"
    log.add_task(conn, sid, "Write the README.", "cli", CODE, mode="route", project="garden", parent=run["task_id"],
                 plan_step={"plan": plan_row["task_id"], "step": 2})
    lines = []
    found = cli._auto_file_mode(conn, sid, run["task_id"], "step-2-1-start", "chatgpt", lines.append)
    row = log.get_task(conn, sid)
    assert found["mode"] == "off" and found["run"] == run["task_id"] and log.is_run_step(row)
    assert context.needs_handoff(row, "chatgpt") and log.is_piece(row)


# ---------- D 34 (step 6, run #156): docs/PLAN.md inside a run (brief 34 D1) ----------
# After step 1 passed the router ticked docs/PLAN.md in the run's copy. Step 2's build then had the file put back to the
# run's base (where step 1 is open), so its diff showed the tick reverted and its checker failed it, twice and on the retry.

BLOCKED_CHECK = "BLOCKED\n1. [must] It needs the bed's name."


def test_a_steps_build_keeps_the_ticks_the_run_wrote_in_docs_plan_md(project, conn, runner):
    from router import filecalls
    _route_plan(conn, _approved(conn))
    # step 2's check is BLOCKED, so the run stops right after step 2's build and nothing renders the file again
    code, out, run = _auto(conn, worker=CopyWorker(STEP1, STEP2), chatgpt=Chat("PASS", BLOCKED_CHECK))
    assert code == 4 and log.auto_of(run)["stop"]["code"] == "blocked", out.message
    one, two = _steps(conn, run)
    files = log.project_files_of(two)
    assert [c["path"] for c in files["changed"]] == ["convert.py", "test_convert.py"], files["changed"]  # no docs/PLAN.md
    assert "docs/PLAN.md" not in (filecalls.diff_text(conn, two) or "")
    assert not files.get("plan_md_restored")
    text = (copies.folder_of(run["task_id"]) / "docs" / "PLAN.md").read_text()
    assert "- [x] **Step 1.**" in text and f"Done by #{one['n']}" in text and "- [ ] **Step 2.**" in text


def test_a_steps_own_edit_of_docs_plan_md_is_put_back_to_the_steps_start(project, conn, runner):
    from router import filecalls
    _route_plan(conn, _approved(conn))
    meddling = ("Added the conversion and rewrote the plan.\n\n" + HANDOFF,
                {**STEP2[1], "docs/PLAN.md": "# Plan\n\nrewritten by the build\n"})
    code, out, run = _auto(conn, worker=CopyWorker(STEP1, meddling), chatgpt=Chat("PASS", BLOCKED_CHECK))
    assert code == 4 and log.auto_of(run)["stop"]["code"] == "blocked", out.message
    one, two = _steps(conn, run)
    files = log.project_files_of(two)
    assert files.get("plan_md_restored") is True and plan.PUT_BACK_LINE in out.message
    assert "docs/PLAN.md" not in [c["path"] for c in files["changed"]]
    assert "docs/PLAN.md" not in (filecalls.diff_text(conn, two) or "")
    text = (copies.folder_of(run["task_id"]) / "docs" / "PLAN.md").read_text()
    assert "rewritten by the build" not in text  # put back, to the version at step 2's start: step 1 ticked, named
    assert "- [x] **Step 1.**" in text and f"Done by #{one['n']}" in text
