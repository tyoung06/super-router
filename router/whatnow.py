"""Build brief 33, W (decision 13): What now?, one line in a project's pinned head with one move and its control. Code
chooses it in this order, the first that applies winning; it is computed on every read and never stored:
(1) a task of the project waits on the owner (a land, a pick, a split's plan, a skill to answer): "Waiting on you: #<n> ·
<what>", with Open; (2) a task of the project is open and not waiting on the owner: "#<n> is running · <who is on which
stage>", with no control; (3) the project's newest top-level task that wasn't cancelled, discarded or undone ended
without delivery: "#<n> <outcome in words>", with Open; (4) that task was delivered and has chips: "Next: <the first
agent chip's words>", with that chip, or "Next: Build from #<n>" with that one; (5) otherwise "Send a task to start." on
a project with no tasks, else "Nothing suggested", with the Ideas button when the list has open ideas."""
from router import availability, ideas, log, nextsteps, state

# Brief 33.1 (decision 17): the plan's rungs go between (3) and (4): (a) the next step's unmet key or test command, (b) Build
# step k, (c) the finish line; a plan waiting on approval is (1), a One step end is (3) in its own words.
PLAN_NEED, PLAN_STEP, FINISH = "plan_need", "plan_step", "finish"
SPEC_CHANGED = "spec_changed"  # brief 33.2 (decision 7.1): after the third rung, before the plan's need rung
AUTO_RUNNING, AUTO_STOPPED, AUTO_FINISHED = "auto_running", "auto_stopped", "auto_finished"  # brief 34 (decision 11)

# Decision 13 (1): what the owner is waited on for, in words
OWNER_WAITS = {"land": "a change ready to land", "pick": "pick A or B", "vote_pick": "pick an answer",
               "split_plan": "approve the split's plan", "needs_label": "pick a skill",
               "answers": "answer its questions"}  # brief 33.4 (decision 5); `_owner_words` gives the count
# Decision 13 (3): an ending without delivery, in words
ENDINGS = {"failed_check": "failed its check", "blocked": "was blocked", "plan_limit": "stopped on a plan limit",
           "process_ended": "stopped: its process ended", "stopped": "stopped", "returned": "came back to you",
           "timed_out": "timed out"}
PASSED_OVER = ("discarded", "undone")


def _line(rung, words, control=None, row=None, chip=None, *, need=None, chips=None, plan_md=None):
    """One What now? line. Brief 33.1: `need` (a plan's unmet key or test command), `chips` (the finish line's) and
    `plan_md` (docs/PLAN.md left out or written over, said) are null on every other line."""
    return {"rung": rung, "words": words, "control": control, "task_id": row["task_id"] if row is not None else None,
            "n": row["n"] if row is not None else None, "chip": chip, "need": need, "chips": chips, "plan_md": plan_md}


def _passed_over(row):
    found = log.project_files_of(row) if row["project_files"] else None
    return row["status"] == "cancelled" or bool(found and found.get("state") in PASSED_OVER)


def _running_words(row, calls, loaded):
    from router import jsonview  # it reads this module's neighbours; kept local
    preset = jsonview.preset_of(row, loaded)[0]
    who = jsonview.working(row, calls, preset)
    if not who or not who.get("agent"):
        return f"#{row['n']} is running"
    name = availability.NAMES.get(who["agent"], who["agent"])
    return f"#{row['n']} is running · {name}" + (f" on {who['doing']}" if who.get("doing") else "")


def _owner_words(row, waiting_on):
    """What the owner is waited on for, in words: brief 33.1, a plan to approve; brief 33.4 (decision 5), answer k questions."""
    if waiting_on == "answers":
        k = len((log.plan_of(row) or {}).get("questions") or [])
        return f"answer {k} question{'' if k == 1 else 's'}"
    return "a plan to approve" if row["mode"] == "plan" else OWNER_WAITS[waiting_on]


def for_project(conn, project, loaded=None):
    """The project's What now? line: {rung, words, control (open, chip, ideas or None), task_id, n, chip}."""
    # newest first, pieces included; brief 33.4 (decision 10b): a suggest is no task for What now?, running or ended
    rows = [r for r in log.project_tasks(conn, project) if r["mode"] != "suggest"]
    found_run = _auto_rung(conn, project, rows)  # brief 34 (decision 11): a run's lines come first, while it has one
    if found_run is not None:
        return found_run
    with_calls = [(row, log.calls_for(conn, row["task_id"])) for row in rows]
    for row, calls in with_calls:  # (1)
        found = state.of(row, calls)
        if found.waiting_on in OWNER_WAITS:
            what = _owner_words(row, found.waiting_on)
            return _line(1, f"Waiting on you: #{row['n']} · {what}", "open", row)
    for row, calls in with_calls:  # (2)
        if row["status"] in ("queued", "sent"):
            return _line(2, _running_words(row, calls, loaded), None, row)
    top = [(row, calls) for row, calls in with_calls if not log.is_piece(row) and not _passed_over(row)
           and row["mode"] != "auto"]  # brief 34 (decision 11): a run's lines are _auto_rung's; a landed one says nothing
    if top:
        row, calls = top[0]
        if not nextsteps.delivered(row, calls):  # (3)
            from router import plan  # plan imports teams; kept local
            one = plan.one_step_view(row, calls) if plan.is_plan(row) else None
            if one is not None:  # brief 33.1 (decision 6): a One step end, in its own words, with Build it
                return _line(3, f"One step: {one['task']}", "chip", row, plan.build_it_chip(row, one))
            outcome = state.of(row, calls).outcome
            return _line(3, f"#{row['n']} {ENDINGS.get(outcome, (outcome or 'ended').replace('_', ' '))}", "open", row)
        found = _plan_rung(conn, project, rows)  # brief 33.1 (decision 17): (a), (b) and (c)
        if found is not None:
            return found
        chips = nextsteps.chips(conn, row, calls, loaded, moved=ideas.moved_from(conn, row))  # (4)
        agent = next((c for c in chips if c["kind"] == "agent"), None)
        first = next((c for c in chips if c["kind"] == "plan_project"), None)  # brief 33.4 (decision 9): rung 4 shows it
        chip = first or agent or next((c for c in chips if c["kind"] == "build_from"), None)
        if chip is not None:
            return _line(4, f"Next: {chip['words']}", "chip", row, chip)
    if not rows:  # (5)
        return _line(5, "Send a task to start.")
    return _line(5, "Nothing suggested", "ideas" if ideas.open_count(conn, project) else None)


def _auto_rung(conn, project, rows):
    """Brief 34 (decision 11): while the project has a run (running, stopped or finished, its open task), Auto's line:
    "Auto · step k of m · c of b calls" (the switch on beside it), "Auto stopped: <why>" with its one control (Open the
    step, or Set <NAME>), or "Auto finished: land the run?" with Open; the run's card is the line's task."""
    from router import auto  # auto reads log and plan; kept local
    run = next((r for r in rows if r["mode"] == auto.MODE and not r["parent"]), None)
    if run is None:
        return None
    record = log.auto_of(run) or {}
    state = auto.run_state(run, record)
    used = auto.used_calls(conn, run["task_id"])
    if state == "running":
        return _line(AUTO_RUNNING, auto.words(run, record, used), None, run)
    if state == "stopped":
        stop = record.get("stop") or {}
        need = None
        control = "open"
        if stop.get("code") == "need":
            plan_row = log.get_task(conn, record.get("plan"))
            from router import plan  # plan imports teams; kept local
            k = stop.get("step")
            need = plan.unmet_need(plan.record_of(plan_row), project, k) if plan_row is not None and k else None
            control = ("secrets" if need["kind"] == "key" else "tests") if need else "open"
        # Open the step: the stopped step's card when the stop has one (failed, blocked, unchecked, a stopped call);
        # the run's card when the run stopped before a step (stop here, the budget, a need, the switch)
        entry = auto.step_entry(record, stop.get("step")) if stop.get("step") else None
        step_row = log.get_task(conn, entry["task_id"]) if entry and entry.get("task_id") else None
        return _line(AUTO_STOPPED, auto.words(run, record, used), control, step_row or run, need=need)
    if state == "finished":
        return _line(AUTO_FINISHED, auto.words(run, record, used), "open", run)
    return None


def _folder_of(project):
    from router import projects  # projects reads the registry; kept local
    try:
        return projects.folder_of(project)
    except projects.ProjectError:
        return None


def _plan_rung(conn, project, rows):
    """Brief 33.1 (decisions 16 and 17): on a project with a current plan, (a) the next step's unmet key or test command,
    (b) Build step k with its chip, or (c) the finish line once every step is done, until a top-level task newer than
    the last step's exists; else None."""
    from router import plan, projrun  # plan imports teams; projrun reads the run settings; kept local
    found = plan.current(conn, project)
    if found is None:
        return None
    done = plan.ticks(conn, found)
    nxt = plan.first_open(conn, found, done)
    note = plan.newest_note(conn, found)
    said = {"plan_md": note}
    if nxt is not None:
        k, step = nxt
        folder = _folder_of(project)  # brief 33.2 (decision 7.1): a spec changed since the plan, while a step is open
        if folder is not None and plan.spec_changed(folder, plan.record_of(found)):
            return _line(SPEC_CHANGED, f"SPEC.md changed since plan #{found['n']} · Revise plan", "chip", found,
                         plan.revise_plan_chip(project), **said)
        need = plan.unmet_need(plan.record_of(found), project, k)
        if need is not None:  # (a): never a refusal; the step may be sent anyway. Brief 33.2 (decision 13): the line is
            control = "secrets" if need["kind"] == "key" else "tests"  # the move; no Build step chip while the need is unmet
            return _line(PLAN_NEED, need["words"], control, found, None, need=need, **said)
        chip = plan.build_step_chip(found, k, step)
        return _line(PLAN_STEP, chip["words"], "chip", found, chip, **said)
    last = max((row for row in done.values()), key=lambda r: r["n"], default=found)
    newer = [r for r in rows if not log.is_piece(r) and r["n"] > last["n"] and not _passed_over(r)]
    if newer:  # (c) gives way to brief 33's rungs once a newer top-level task exists
        return None
    total = len(plan.steps_of(plan.record_of(found)))
    from router import spec  # spec reads settings; kept local
    folder = _folder_of(project)
    done_when = folder is not None and spec.parse(spec.read_text(folder) or "").has_done_when  # brief 33.2 (decision 8)
    chips = plan.finish_chips(project, run_command_set=bool(projrun.run_command_of(project)), done_when=done_when,
                              readme_exists=folder is not None and (folder / "README.md").is_file())
    return _line(FINISH, f"All {total} steps done", "chips", found, None, chips=chips, **said)
