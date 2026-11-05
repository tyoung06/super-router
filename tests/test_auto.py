"""Build brief 34 (decisions 1, 4, 6, 7, 10, 11 and 14): router/auto.py's pure parts. The run's record and its steps, the
stop-here marks on the plan's record, the budget (ceil(1.5 × U), going on with used + ceil(1.5 × U_left), the hook on a
scratch log only), the counted calls, the states and the words the page shows, the dry run's view, the run's one handoff
entry. Fakes only."""
import pytest

from router import auto as auto_mod

from router import auto, log

PLAN = {"task_id": "sr-plan", "n": 7}
STEPS = [{"text": "one", "team": "route", "done_when": "t1"}, {"text": "two", "team": "redteam", "done_when": "t2"},
         {"text": "three", "team": "route", "done_when": "t3"}]
VIEW_STEPS = [{"k": 1, "calls": 2, "max_calls": 4, "jev_label": True}, {"k": 2, "calls": 5, "max_calls": 7, "jev_label": False},
              {"k": 3, "calls": 2, "max_calls": 4, "jev_label": True}]


def _record(from_step=1, **changes):
    upper = auto.upper_estimate({"steps": VIEW_STEPS}, from_step)
    rec = auto.new_record(PLAN, STEPS, from_step=from_step, budget=auto.budget_for(upper["max_calls"]), estimate=upper)
    return {**rec, **changes}


def test_the_record_covers_the_steps_from_its_first_and_reads_the_next_open_one():
    rec = _record()
    assert [s["state"] for s in rec["steps"]] == ["open", "open", "open"] and rec["from_step"] == 1
    assert auto.next_open(rec) == 1 and auto.finished(rec) is False and auto.passed_steps(rec) == {}
    later = _record(from_step=3)
    assert [s["state"] for s in later["steps"]] == ["done", "done", "open"] and [s["k"] for s in auto.covered(later)] == [3]
    done = {**rec, "steps": [{**s, "state": "done", "task_id": f"sr-s{s['k']}"} for s in rec["steps"]]}
    assert auto.next_open(done) is None and auto.finished(done) and auto.passed_steps(done) == {1: "sr-s1", 2: "sr-s2", 3: "sr-s3"}
    retried = {**rec, "steps": [{**rec["steps"][0], "state": "retried"}, *rec["steps"][1:]]}
    assert auto.next_open(retried) == 1


def test_a_stop_names_its_code_and_words_and_going_on_clears_it():
    rec = auto.with_stop(_record(), "stop_here", "stop here before step 2", step=2)
    assert rec["stop"] == {"code": "stop_here", "why": "stop here before step 2", "step": 2}
    assert auto.cleared({**rec, "off_requested": True})["stop"] is None and auto.cleared(rec)["off_requested"] is False
    with pytest.raises(ValueError, match="no stop"):
        auto.with_stop(rec, "tea", "x")
    long = auto.with_stop(rec, "failed", "x" * 500)
    assert len(long["stop"]["why"]) == 300


def test_stop_here_marks_live_on_the_plan_record_and_a_passed_mark_no_longer_blocks():
    plan_record = {"steps": STEPS}
    marked = auto.with_mark(plan_record, 2, True)
    assert auto.marks_of(marked) == [2] and auto.marks_of(auto.with_mark(marked, 2, False)) == []
    assert auto.marks_of({"stop_here": [3, 1, "x", True, 1]}) == [1, 3]
    rec = _record()
    assert auto.mark_blocks(rec, marked, 2) is True and auto.mark_blocks(rec, marked, 1) is False
    passed = {**rec, "passed_marks": [2]}
    assert auto.mark_blocks(passed, marked, 2) is False
    assert auto.first_mark_ahead(rec, auto.with_mark(marked, 3, True), 1) == 2
    assert auto.first_mark_ahead(passed, auto.with_mark(marked, 3, True), 1) == 3
    assert auto.first_mark_ahead(rec, marked, 3) is None


def test_the_budget_is_the_upper_estimate_plus_half_and_going_on_adds_to_what_was_used():
    upper = auto.upper_estimate({"steps": VIEW_STEPS}, 1)
    assert upper == {"calls": 15, "max_calls": 15, "jev_labels": 2}  # Jev's labels apart
    assert auto.budget_for(15) == 23 and auto.budget_for(0) == 0
    left = auto.upper_estimate({"steps": VIEW_STEPS}, 2)
    assert left["max_calls"] == 11 and auto.budget_for(11, used=9) == 9 + 17
    assert auto.upper_estimate({"steps": [{"k": 1, "calls": 3, "max_calls": None}]}, 1)["max_calls"] == 3
    rec = _record()
    assert auto.over_budget(rec, 22) is False and auto.over_budget(rec, 23) is True and auto.budget_words(rec, 4) == "4 of 23 calls"


def test_the_hook_is_read_at_on_and_refused_on_the_real_log():
    real = lambda path, root: True  # noqa: E731
    scratch = lambda path, root: False  # noqa: E731
    assert auto.hook_budget({}, "db", root=".", is_real_log=scratch) is None
    assert auto.hook_budget({"SR_AUTO_BUDGET": "4"}, "db", root=".", is_real_log=scratch) == 4
    with pytest.raises(auto.AutoError, match="scratch log") as found:
        auto.hook_budget({"SR_AUTO_BUDGET": "4"}, "db", root=".", is_real_log=real)
    assert found.value.code == "budget"
    with pytest.raises(auto.AutoError, match="number of calls"):
        auto.hook_budget({"SR_AUTO_BUDGET": "many"}, "db", root=".", is_real_log=scratch)
    with pytest.raises(auto.AutoError, match="number of calls"):
        auto.hook_budget({"SR_AUTO_BUDGET": "-1"}, "db", root=".", is_real_log=scratch)


def test_every_model_call_row_of_the_runs_steps_counts_never_jev():
    c = log.init_db(":memory:")
    c.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, status, mode, project, plan) "
              "VALUES ('sr-plan', 'x', 'x', 'cli', 'p', 'not_asked', 'done', 'plan', 'g', '{}')")
    log.add_task(c, "sr-run", "run", "cli", {"status": "not_asked", "tokens": 0}, mode="auto", project="g", auto=_record())
    for k in (1, 2):
        log.add_task(c, f"sr-s{k}", f"step {k}", "cli", {"status": "ok", "label": "code", "confidence": 0.9, "needs_split": 0.1, "tokens": 9},
                     mode="route", project="g", parent="sr-run", plan_step={"plan": "sr-plan", "step": k})
    log.add_call(c, "sr-s1", "sr-s1", "do", "claude", status="done", text="x")
    log.add_call(c, "sr-s1-c1", "sr-s1", "check", "chatgpt", status="done", text="PASS")
    log.add_call(c, "sr-s1-takeover", "sr-s1", "do", "chatgpt", status="done", text="x")
    log.add_call(c, "sr-s2", "sr-s2", "do", "grok", status="sent", text=None, url="https://example.invalid/1")
    assert auto.used_calls(c, "sr-run") == 4


def test_the_states_and_the_words_follow_the_row_and_the_record():
    c = log.init_db(":memory:")
    c.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, status, mode, project, plan) "
              "VALUES ('sr-plan', 'x', 'x', 'cli', 'p', 'not_asked', 'done', 'plan', 'g', '{}')")
    rec = _record()
    log.add_task(c, "sr-run", "run", "cli", {"status": "not_asked", "tokens": 0}, mode="auto", project="g", auto=rec)
    row = log.get_task(c, "sr-run")
    assert auto.run_state(row, rec) == "running" and auto.words(row, rec) == "Auto · step 1 of 3 · 0 of 23 calls"
    running = {**rec, "used": 4, "steps": [{**rec["steps"][0], "state": "running"}, *rec["steps"][1:]]}
    assert auto.words(row, running) == "Auto · step 1 of 3 · 4 of 23 calls"
    c.execute("UPDATE tasks SET status = 'returned', check_note = 'auto stopped: stop here before step 2' WHERE task_id = 'sr-run'")
    c.commit()
    stopped = auto.with_stop(rec, "stop_here", "stop here before step 2", step=2)
    row = log.get_task(c, "sr-run")
    assert auto.run_state(row, stopped) == "stopped" and auto.words(row, stopped) == "Auto stopped: stop here before step 2"
    c.execute("UPDATE tasks SET status = 'done' WHERE task_id = 'sr-run'")
    log.set_project_files(c, "sr-run", {"mode": "on", "state": "waiting", "copy": True, "base": "abc", "branch": "main",
                                        "changed": [{"path": "a.py", "status": "added", "plus": 1, "minus": 0}], "diff": None,
                                        "latest": None, "tests": None, "commit": None, "undo_commit": None, "why": None})
    row = log.get_task(c, "sr-run")
    assert auto.run_state(row, rec) == "finished" and auto.words(row, rec) == "Auto finished: land the run?"
    log.update_project_files(c, "sr-run", state="landed")
    assert auto.run_state(log.get_task(c, "sr-run"), rec) == "landed"
    view = auto.view(c, log.get_task(c, "sr-run"))
    assert view["plan"] == {"task_id": "sr-plan", "n": 7} and view["budget"] == 23 and len(view["steps"]) == 3
    assert view["steps"][0]["task_id"] is None and view["state"] == "landed" and view["copy"] is True


def test_the_projects_switch_is_on_while_it_runs_off_when_on_would_be_accepted_and_hidden_otherwise():
    c = log.init_db(":memory:")
    assert auto.project_auto(c, "g", None, can_start=True) == {"state": "off", "run": None, "switch": "off", "why": None}
    assert auto.project_auto(c, "g", None, can_start=False, why="no current plan")["switch"] == "hidden"
    c.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, status, mode, project, plan) "
              "VALUES ('sr-plan', 'x', 'x', 'cli', 'p', 'not_asked', 'done', 'plan', 'g', '{}')")
    rec = _record()
    log.add_task(c, "sr-run", "run", "cli", {"status": "not_asked", "tokens": 0}, mode="auto", project="g", auto=rec)
    row = log.get_task(c, "sr-run")
    found = auto.project_auto(c, "g", row, can_start=False)
    assert (found["state"], found["switch"], found["run"]["n"], found["run"]["words"]) == ("on", "on", 2, "Auto · step 1 of 3 · 0 of 23 calls")
    c.execute("UPDATE tasks SET status = 'returned' WHERE task_id = 'sr-run'")
    log.set_auto(c, "sr-run", auto.with_stop(rec, "budget", "3 of 3 calls", step=2))
    c.commit()
    row = log.get_task(c, "sr-run")
    assert auto.project_auto(c, "g", row, can_start=True)["switch"] == "off"
    assert auto.project_auto(c, "g", row, can_start=False, why="Claude isn't available")["switch"] == "hidden"
    assert auto.project_auto(c, "g", row, can_start=True)["run"]["stop"]["code"] == "budget"


def test_the_dry_run_names_the_steps_the_budget_the_first_stop_here_and_the_overrun():
    rec = _record()
    plan_record = auto.with_mark({"steps": STEPS}, 2, True)
    found = auto.dry_run_view(PLAN, rec, plan_record)
    assert (found["from_step"], found["to_step"], found["steps"], found["budget"], found["first_stop_here"]) == (1, 3, [1, 2, 3], 23, 2)
    assert found["words"] == "Auto runs steps 1 to 3 of plan #7, 23 calls at most, stopping before step 2 (stop here)."
    assert "up to one step's calls" in found["overrun"]
    later = _record(from_step=3)
    assert auto.dry_run_view(PLAN, later, {"steps": STEPS})["words"] == "Auto runs step 3 of plan #7, 6 calls at most."
    done = {**rec, "steps": [{**s, "state": "done"} for s in rec["steps"]]}
    assert auto.dry_run_view(PLAN, done, {"steps": STEPS})["words"] == "Every step is done: nothing to run."


def test_the_runs_one_entry_holds_each_steps_produced_line_and_the_last_steps_status_and_next():
    c = log.init_db(":memory:")
    c.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, status, mode, project, plan) "
              "VALUES ('sr-plan', 'x', 'x', 'cli', 'p', 'not_asked', 'done', 'plan', 'g', '{}')")
    log.add_task(c, "sr-run", "run", "cli", {"status": "not_asked", "tokens": 0}, mode="auto", project="g", auto=_record())
    for k in (1, 2):
        log.add_task(c, f"sr-s{k}", f"step {k}", "cli", {"status": "ok", "label": "code", "confidence": 0.9, "needs_split": 0.1, "tokens": 0},
                     mode="route", project="g", parent="sr-run", plan_step={"plan": "sr-plan", "step": k})
    run = log.get_task(c, "sr-run")
    steps = log.pieces_of(c, "sr-run")
    sections = {"sr-s1": {"produced": ["conv.py: c_to_f", "test_conv.py: one test"], "status": ["c_to_f done"], "next": ["f_to_c"]},
                "sr-s2": {"produced": ["conv.py: f_to_c"], "status": ["both converters done"], "next": ["a README"]}}
    entry = auto.run_entry(run, steps, sections, date="2026-10-30")
    assert entry.splitlines() == [f"### #{run['n']} · 2026-10-30 · auto · plan #7 · router", "Produced:",
                                  "step 1 (#3): conv.py: c_to_f", "test_conv.py: one test", "step 2 (#4): conv.py: f_to_c",
                                  "Status:", "both converters done", "Next:", "a README"]
    bare = auto.run_entry(run, steps, {}, date="2026-10-30")
    assert bare.splitlines()[1:] == ["Produced:", "step 1 (#3): —", "step 2 (#4): —", "Status:", "—", "Next:", "—"]


# ---------- the review's fixes (decisions 4, 11 and 14) ----------

def test_the_running_words_take_the_live_count_and_the_dry_run_counts_a_stopped_step():
    record = {"plan": "sr-p", "n": 3, "from_step": 1, "budget": 14, "used": 2,
              "steps": [{"k": 1, "state": "done", "attempt": 1, "task_id": "sr-a"}, {"k": 2, "state": "running", "attempt": 1, "task_id": "sr-b"},
                        {"k": 3, "state": "open", "attempt": 0}], "stop": None}
    row = {"status": "queued", "task_id": "sr-r", "n": 9}
    assert auto_mod.words(row, record) == "Auto · step 2 of 3 · 2 of 14 calls"
    assert auto_mod.words(row, record, used=7) == "Auto · step 2 of 3 · 7 of 14 calls"  # live, from the rows
    stopped = {**record, "steps": [{"k": 1, "state": "done", "attempt": 1, "task_id": "sr-a"}, {"k": 2, "state": "stopped", "attempt": 1, "task_id": "sr-b"},
                                   {"k": 3, "state": "open", "attempt": 0}], "stop": {"code": "stopped", "why": "x", "step": 2}}
    plan_row = {"task_id": "sr-p", "n": 3}
    view = auto_mod.dry_run_view(plan_row, stopped, {"steps": [{}, {}, {}]}, used=5)
    assert view["steps"] == [2, 3] and view["from_step"] == 2 and view["words"].startswith("Auto runs steps 2 to 3 of plan #3")
    assert auto_mod.stale_running_stopped(dict(record))["steps"][1]["state"] == "stopped"
