"""Auto (build brief 34, rules 2.48's Auto section): one run per project that carries an approved plan's open steps one after
another, each a task of its team as Build step k sends it, in the run's one copy, held to the plan card's budget and to the
owner's stop-here marks, and landed as one commit by the owner. This module holds the pure parts: the run's record (log
version 21's `tasks.auto`), the budget, the stop-here marks on the plan's record, the states, the views for the JSON and the
page, the run's handoff entry. The commands and the loop live in router/__main__.py (`cmd_auto`, `_auto_run`)."""
import json
import math
import os
from dataclasses import dataclass

from router import log, plan as plan_mod, safety

MODE = "auto"
WAITING = "auto"                      # waiting_on for a stopped run (decision 1)
REFUSED = "auto_refused"              # the intake's refusal code (nothing written)
BUDGET = "budget"                     # the stop at the budget (decision 7), the run row's own reason code
BUDGET_ENV = "SR_AUTO_BUDGET"         # the test hook: the budget in calls, on a scratch log only
BUDGET_FACTOR = 1.5                   # D15: the plan card's upper estimate plus 50%
COUNTED_AGENTS = ("claude", "chatgpt", "cursor", "grok")  # every model call row counts (never Jev, never tokens)
STOP_NOTE = "auto stopped: "          # the run row's check_note while it waits on the owner
FINISHED_NOTE = "auto finished"
STEP_STATES = ("open", "running", "done", "failed", "stopped", "retried", "skipped")
# why a run stopped, each a code the JSON carries beside its words (decision 4)
STOPS = ("stop_here", "budget", "failed", "blocked", "unchecked", "stopped", "need", "cancelled", "off", "copy",
         "refused", "unavailable", "credits", "label", "finished",
         "spec_changed")  # brief 33.2 (decision 7.2): SPEC.md changed since the run started
SPEC_CHANGED = "spec_changed"
SPEC_STOP_WHY = "SPEC.md changed since the run started"
SPEC_ON_LINE = "The remaining steps will use the new SPEC.md."  # the on-again confirm's line


def spec_stop_ways(revise=True):
    """The run card's line after a `spec_changed` stop: the two ways on (with Revise plan built, or without)."""
    middle = ", then Revise plan" if revise else ""
    return (f"Land the run so far or Discard run{middle}; or turn the switch on again: the remaining steps use the new "
            "SPEC.md.")


class AutoError(ValueError):
    """A refusal with its code (REFUSED, or BUDGET for the hook's own refusals)."""

    def __init__(self, message, code=REFUSED):
        super().__init__(message)
        self.code = code


# ---------- the record (decision 14) ----------

def new_record(plan_row, steps, *, from_step, budget, estimate, marks=(), spec_hash=None):
    """A run's record at `--on`: the plan it runs, the steps it covers (k from `from_step` to the last), the budget, no
    calls used yet, no stop, no mark passed. `steps` are the plan record's steps (plan.steps_of); `estimate` the numbers
    the budget came from ({calls, max_calls, jev_labels} for the covered steps); `spec_hash` (brief 33.2, decision 7.2)
    the folder's SPEC.md hash at `--on`, or None without one."""
    return {"plan": plan_row["task_id"], "n": plan_row["n"], "from_step": from_step,
            "steps": [{"k": k, "task_id": None, "state": "done" if k < from_step else "open", "attempt": 0, "calls": 0,
                       "outcome": None, "team": (step.get("team") or "route")}
                      for k, step in enumerate(steps, 1)],
            "budget": budget, "used": 0, "estimate": estimate, "stop": None, "passed_marks": sorted(set(marks)),
            "off_requested": False, "hook": False, "spec_hash": spec_hash}


def step_entry(record, k):
    for step in record.get("steps") or ():
        if step.get("k") == k:
            return step
    return None


def covered(record):
    """The steps the run covers: from its first step on."""
    return [s for s in record.get("steps") or () if s.get("k", 0) >= record.get("from_step", 1)]


def next_open(record):
    """The first covered step that is not done (its number: open, retried, or the one the run stopped on, which an
    `--on` resumes or starts again: decision 4), or None when every step is done."""
    for step in covered(record):
        if step.get("state") in ("open", "retried", "stopped"):
            return step["k"]
    return None


def passed_steps(record):
    """{k: task_id} of the steps the run passed (done), in order."""
    return {s["k"]: s.get("task_id") for s in covered(record) if s.get("state") == "done" and s.get("task_id")}


def land_message(record):
    """Brief 33.2 fix 3 (the owner's decision 3): the subject of a run's land commit, before its task id: the plan, the
    steps that land (Land the run so far: the passed ones only) and the plan's total, "Auto: plan #155, steps 1 to 2 of
    3". One step reads "step 2 of 3"; none, "no step of 3". The run row's own text (the planned range) stays as it is."""
    landed = sorted(passed_steps(record))
    total = len(record.get("steps") or ())
    head = f"Auto: plan #{record.get('n')}"
    if not landed:
        return f"{head}, no step of {total}"
    if landed[0] == landed[-1]:
        return f"{head}, step {landed[0]} of {total}"
    return f"{head}, steps {landed[0]} to {landed[-1]} of {total}"


def finished(record):
    return next_open(record) is None and all(s.get("state") == "done" for s in covered(record))


def with_stop(record, code, why, step=None):
    """The record stopped: `code` one of STOPS, `why` the words the card and Needs you show, `step` the step it stopped
    before or on."""
    if code not in STOPS:
        raise ValueError(f"no stop {code!r}")
    return {**record, "stop": {"code": code, "why": safety.one_line(str(why))[:300], "step": step}}


def cleared(record):
    """The record going on: its stop cleared, the off request too."""
    return {**record, "stop": None, "off_requested": False}


# ---------- the stop-here marks (decision 6), on the plan row's record ----------

MARKS_KEY = "stop_here"


def marks_of(plan_record):
    """The marked steps' numbers, sorted."""
    found = (plan_record or {}).get(MARKS_KEY) or []
    return sorted({int(k) for k in found if isinstance(k, int) and not isinstance(k, bool)})


def with_mark(plan_record, k, on):
    """The plan record with step k marked (on) or unmarked."""
    marks = set(marks_of(plan_record))
    if on:
        marks.add(k)
    else:
        marks.discard(k)
    return {**plan_record, MARKS_KEY: sorted(marks)}


def mark_blocks(record, plan_record, k):
    """Decision 6: a run stops before starting a marked step, unless the mark was passed for this run (an `--on` at it)."""
    return k in marks_of(plan_record) and k not in (record.get("passed_marks") or [])


def first_mark_ahead(record, plan_record, from_k):
    """The first marked step at or after `from_k` the run would stop before, or None."""
    for k in marks_of(plan_record):
        if k >= from_k and mark_blocks(record, plan_record, k):
            return k
    return None


# ---------- the budget (decision 7) ----------

def upper_estimate(plan_view, from_step):
    """U: the plan card's upper call estimate for the steps from `from_step` on (each step's `max_calls`, the plan view's;
    a step with no estimate counts its lower bound, else 0), and the Jev labels apart."""
    calls, labels = 0, 0
    for step in plan_view.get("steps") or ():
        if step.get("k", 0) < from_step:
            continue
        most = step.get("max_calls")
        if most is None:
            most = step.get("calls") or 0
        calls += int(most)
        if step.get("jev_label"):
            labels += 1
    return {"calls": calls, "max_calls": calls, "jev_labels": labels}


def budget_for(upper, used=0):
    """`ceil(1.5 × U)`, or, going on after a budget stop, `used + ceil(1.5 × U_left)`."""
    return int(used) + math.ceil(BUDGET_FACTOR * int(upper))


def hook_budget(environ, db_path, *, root, is_real_log):
    """The test hook `SR_AUTO_BUDGET=<n>`, read at every `--on`: the budget in calls from then, on a scratch log only
    (refused on the real log, as every injected hook is). None when the hook isn't set."""
    raw = (environ or {}).get(BUDGET_ENV)
    if raw is None or raw == "":
        return None
    try:
        n = int(raw)
    except ValueError:
        raise AutoError(f"{BUDGET_ENV} takes a number of calls, not {raw!r}.", BUDGET) from None
    if n < 0:
        raise AutoError(f"{BUDGET_ENV} takes a number of calls, not {raw!r}.", BUDGET)
    if is_real_log(db_path, root=root):
        raise AutoError(f"{BUDGET_ENV} is test-only and works only on a scratch log; this is the real log (router.db in the "
                        "main checkout), or git could not say which log it is.", BUDGET)
    return n


def used_calls(conn, run_id):
    """Every model call row of the run's tasks (its steps, every attempt; retries, takeovers and re-asks included)."""
    total = 0
    for row in log.pieces_of(conn, run_id):
        total += sum(1 for c in log.calls_for(conn, row["task_id"]) if c["agent"] in COUNTED_AGENTS)
    return total


def over_budget(record, used):
    return used >= int(record.get("budget") or 0)


def budget_words(record, used):
    return f"{used} of {record.get('budget')} calls"


# ---------- the views (decision 14) ----------

def step_views(conn, record):
    """Each covered step with its state, its task (number, status, outcome) and its calls, for the card and the JSON."""
    from router import state  # state reads log; kept local
    out = []
    for step in record.get("steps") or ():
        row = log.get_task(conn, step["task_id"]) if step.get("task_id") else None
        calls = log.calls_for(conn, row["task_id"]) if row is not None else []
        found = state.of(row, calls) if row is not None else None
        out.append({"k": step["k"], "state": step.get("state"), "attempt": step.get("attempt", 0), "team": step.get("team"),
                    "task_id": row["task_id"] if row is not None else None, "n": row["n"] if row is not None else None,
                    "status": row["status"] if row is not None else None,
                    "outcome": found.outcome if found is not None else None,
                    "waiting_on": found.waiting_on if found is not None else None,
                    "verdict": row["check_state"] if row is not None else None,
                    "calls": sum(1 for c in calls if c["agent"] in COUNTED_AGENTS),
                    "covered": step.get("k", 0) >= record.get("from_step", 1)})
    return out


def run_state(row, record):
    """running | stopped | finished | landed | discarded | ended, from the row and its record."""
    found = log.project_files_of(row) if "project_files" in row.keys() else None
    status = row["status"]
    if (found or {}).get("state") in ("discarded", "undone", "landed"):  # whatever stopped or finished it before
        return found["state"]
    if status in ("queued", "sent"):
        return "running"
    if status == "returned":
        return "stopped"
    if status == "done":
        state = (found or {}).get("state")
        if state == "waiting":
            return "finished"
        if state == "landed":
            return "landed"
        if state in ("discarded", "undone"):
            return state
        return "ended"
    return "ended"


def view(conn, row):
    """A run's `auto` on its JSON: its plan, the steps with their states and tasks, the budget, the calls used, the stop and
    the copy (decision 14)."""
    record = log.auto_of(row)
    if record is None:
        return None
    found = log.project_files_of(row) if "project_files" in row.keys() else None
    used = used_calls(conn, row["task_id"])  # live, from the rows (the record's count is as of the step's start)
    return {"plan": {"task_id": record.get("plan"), "n": record.get("n")}, "from_step": record.get("from_step"),
            "state": run_state(row, record), "steps": step_views(conn, record), "budget": record.get("budget"),
            "used": used, "estimate": record.get("estimate"), "stop": record.get("stop"),
            "passed_marks": record.get("passed_marks") or [], "off_requested": bool(record.get("off_requested")),
            "hook": bool(record.get("hook")), "copy": bool(found and found.get("copy")),
            "next": next_open(record), "words": words(row, record, used),
            "tests": tests_sum(step_test_runs(conn, record)),  # brief 33.2 (decision 16): the steps' test runs, summed
            "spec_hash": record.get("spec_hash"),  # brief 33.2 (decision 7.2): the SPEC.md the run runs under
            "ways": spec_stop_ways(True) if (record.get("stop") or {}).get("code") == SPEC_CHANGED else None}


def words(row, record, used=None):
    """One line: "Auto · step k of m · c of b calls" while it runs, "Auto stopped: <why>" once stopped, "Auto finished:
    land the run?" once finished (decision 11). `used` is the live count (`used_calls`) when the reader has the log; else
    the record's, written at each step's start and at each stop."""
    state = run_state(row, record)
    total = len(record.get("steps") or ())
    if state == "running":
        k = next_open(record)
        running = next((s["k"] for s in record.get("steps") or () if s.get("state") == "running"), k)
        count = record.get("used") or 0 if used is None else used
        return f"Auto · step {running or total} of {total} · {budget_words(record, count)}"
    if state == "stopped":
        stop = record.get("stop") or {}
        return f"Auto stopped: {stop.get('why') or 'it stopped'}"
    if state == "finished":
        return "Auto finished: land the run?"
    if state == "landed":
        return "Auto landed"
    return f"Auto {state}"


def project_auto(conn, project, run_row, *, can_start, why=None):
    """A project's `auto` on the project list and status (decision 10): on | stopped | finished | off, the run, and the
    switch's state: off when `--on` would be accepted, on while a run runs, hidden otherwise (never greyed)."""
    if run_row is not None:
        record = log.auto_of(run_row) or {}
        state = run_state(run_row, record)
        used = used_calls(conn, run_row["task_id"])
        run = {"task_id": run_row["task_id"], "n": run_row["n"], "state": state, "words": words(run_row, record, used),
               "stop": record.get("stop"), "used": used, "budget": record.get("budget"),
               "next": next_open(record)}
        if state == "running":
            return {"state": "on", "run": run, "switch": "on", "why": None}
        if state == "stopped":
            return {"state": "stopped", "run": run, "switch": "off" if can_start else "hidden", "why": why}
        if state == "finished":
            return {"state": "finished", "run": run, "switch": "hidden", "why": why}
    return {"state": "off", "run": None, "switch": "off" if can_start else "hidden", "why": why}


# ---------- the dry run (decision 10's confirm) ----------

def dry_run_view(plan_row, record, plan_record, *, used=0, spec_changed=False):
    """What `--on` would do: the steps the run covers, the budget (new, or going on), the first stop-here ahead, and the
    one-step overrun's words; the numbers come from here, never from the page. `spec_changed` (brief 33.2, decision
    7.2): going on after SPEC.md changed, so the confirm says the remaining steps use the new one."""
    steps = covered(record)
    first = next_open(record)
    # Cleanup 2, row 9: `--on` passes a mark on the step it starts at, so the confirm looks from the next step on
    mark = first_mark_ahead(record, plan_record, first + 1) if first else None
    total = len(record.get("steps") or ())
    return {"plan": {"task_id": plan_row["task_id"], "n": plan_row["n"]}, "from_step": first, "to_step": total,
            "steps": [s["k"] for s in steps if s.get("state") in ("open", "retried", "stopped")], "budget": record.get("budget"),
            "used": used, "estimate": record.get("estimate"), "first_stop_here": mark,
            "overrun": "A step already started finishes, so the run can pass its budget by up to one step's calls.",
            "words": _dry_words(first, total, record, mark),
            "spec_changed": bool(spec_changed), "spec_line": SPEC_ON_LINE if spec_changed else None}


def _dry_words(first, total, record, mark):
    if first is None:
        return "Every step is done: nothing to run."
    last = mark - 1 if mark else total  # Cleanup 2, row 9: with a mark ahead, the run stops before it
    span = f"step {first}" if first == last else f"steps {first} to {last}"
    line = f"Auto runs {span} of plan #{record.get('n')}, {record.get('budget')} calls at most"
    if mark:
        line += f", then stops before step {mark} (stop here)"
    return line + "."


def so_far_words(record, change):
    """Cleanup 2, row 10: Land the run so far's line when the copy needed no putting back. "Delivered unchecked" only for the
    unchecked stop: any other stop came before its step, so the line names the steps that land."""
    stop = record.get("stop") or {}
    k = stop.get("step")
    if stop.get("code") == "unchecked":
        return (f"Land the run so far: the run stopped after step {k} (delivered unchecked), so it lands as it stands, that "
                f"step included; {change}.")
    done = [str(s["k"]) for s in record.get("steps") or () if s.get("state") == "done"]
    if not done:
        landing = "no step lands"
    elif len(done) == 1:
        landing = f"step {done[0]} lands"
    else:
        landing = f"steps {', '.join(done[:-1])} and {done[-1]} land"
    return f"Land the run so far: the run stopped before step {k}, so {landing}; {change}."


# ---------- the handoff entry at the land (decision 2) ----------

def run_entry(run_row, step_rows, sections, *, date):
    """One entry for the whole run: the heading names the plan; Produced holds each step's Produced line(s) in order;
    Status and Next are the last step's. `sections` maps a step's task id to its delivered `## Handoff` parts
    ({produced, status, next} lists), as context.raw_parts reads them; a step with none reads —."""
    from router import context  # context reads log; kept local
    record = log.auto_of(run_row) or {}
    head = context.heading(run_row["n"], date, f"auto · plan #{record.get('n')}", "router")
    produced, last = [], None
    for row in step_rows:
        parts = sections.get(row["task_id"]) or {}
        k = (log.plan_step_of(row) or {}).get("step")
        lines = parts.get("produced") or ["—"]
        produced += [f"step {k} (#{row['n']}): {lines[0]}"] + lines[1:]
        if parts:
            last = parts
    status = (last or {}).get("status") or ["—"]
    nxt = (last or {}).get("next") or ["—"]
    return "\n".join([head, "Produced:", *(produced or ["—"]), "Status:", *status, "Next:", *nxt])


# ---------- the steps' test runs (brief 33.2, decision 16: 34's D2) ----------

RAN = ("passed", "failed", "timed_out")
NO_TESTS = "No tests ran: no test command"


def step_test_runs(conn, record):
    """{k: [tests records]} of the run's passed steps in order: each step's build and fix calls' test runs (the `tests`
    record on the call row), oldest first. A step that landed so far is a passed one; a stopped or failed step is never
    counted."""
    found = {}
    for k, task_id in passed_steps(record).items():
        runs = []
        for call in log.calls_for(conn, task_id):
            tests = log.tests_of(call)
            if tests is not None:
                runs.append(tests)
        found[k] = runs
    return found


def _times(n):
    return "once" if n == 1 else "twice" if n == 2 else f"{n} times"


def tests_sum(by_step):
    """One line for the run's entry and its card, judging each step by its last run: "Tests: `<command>` · <n> runs across
    <m> steps, all passing at the end (step k fixed once)" (a failure cured by a fix round counts as fixed, not failed),
    "… step k failing" when its last run failed, or "No tests ran: no test command" when none ran."""
    import shlex
    steps, command = {}, None
    for k, runs in sorted((by_step or {}).items()):
        ran = [r for r in runs if (r or {}).get("outcome") in RAN]
        if not ran:
            continue
        steps[k] = ran
        if command is None and ran[0].get("command"):
            command = shlex.join(ran[0]["command"])
    if not steps:
        return NO_TESTS
    total = sum(len(r) for r in steps.values())
    head = (f"Tests: `{command or '-'}` · {total} run{'' if total == 1 else 's'} across {len(steps)} "
            f"step{'' if len(steps) == 1 else 's'}")
    failing = [k for k, runs in steps.items() if runs[-1].get("outcome") != "passed"]
    if failing:
        return f"{head}, {', '.join(f'step {k} failing' for k in failing)}"
    fixed = [(k, sum(1 for r in runs[:-1] if r.get("outcome") != "passed")) for k, runs in steps.items()]
    fixed = [(k, n) for k, n in fixed if n]
    words = f" ({', '.join(f'step {k} fixed {_times(n)}' for k, n in fixed)})" if fixed else ""
    return f"{head}, all passing at the end{words}"


def dumps(record):
    return json.dumps(record, sort_keys=True)


def env_hook_set(environ):
    return bool((environ or os.environ).get(BUDGET_ENV))


# ---------- can a run start? (decision 1), for `sr auto --on`, the project list, status and the page's switch ----------

def run_row_of(conn, project):
    """The project's run while it holds the project: its open task when that is a run (running, stopped or finished)."""
    row = log.open_task_for(conn, project)
    return row if row is not None and row["mode"] == MODE else None


def passed_rows(conn, run_id):
    """Decision 2: a run's passed steps, {k: row}, counted as done for its next step's --step; None without a run."""
    if run_id is None:
        return None
    run = log.get_task(conn, run_id)
    found = {}
    for k, task_id in passed_steps(log.auto_of(run) or {}).items():
        row = log.get_task(conn, task_id)
        if row is not None:
            found[k] = row
    return found


def can_start(conn, project, run=None, *, claude_ok=True, files_ready=None):  # noqa: C901
    """Decision 1: why `sr auto <project> --on` would be refused now, or None. The page's switch and status read it
    without the online checks (`claude_ok` True, Claude's file check taken as passed); the command passes its gate. Reads
    only: nothing here writes or sends."""
    from router import filemode, intake, plan, projects  # each reads most of the router; kept local
    refused = intake.project_refusal(conn, project, open_rule=False)
    if refused:
        return refused[1]
    open_row = log.open_task_for(conn, project)
    if open_row is not None and open_row["mode"] != MODE:
        return f"task #{open_row['n']} is open on {project}: finish or cancel it first"
    if open_row is not None:
        record = log.auto_of(open_row) or {}
        state = run_state(open_row, record)
        if state == "running":
            return f"run #{open_row['n']} is running"
        if state == "finished":
            return f"run #{open_row['n']} is finished and waits to land: Land run or Discard run first"
        stop = record.get("stop") or {}
        if stop.get("code") == "failed":  # the run holds the project, so a by-hand build waits for its end
            return (f"step {stop.get('step')} failed its check twice (run #{open_row['n']}): Land the run so far or "
                    "Discard run, then build it by hand")
        if stop.get("code") == "blocked":
            return f"step {stop.get('step')} was blocked (run #{open_row['n']}): {stop.get('why')}"
    plan_row = plan.current(conn, project)
    if plan_row is None:
        return f"{project} has no current plan: approve one first"
    passed = passed_rows(conn, open_row["task_id"]) if open_row is not None else None
    nxt = plan.first_open(conn, plan_row, found={**plan.ticks(conn, plan_row), **(passed or {})})
    if nxt is None:
        if open_row is not None and passed:  # the run stopped on its last step (unchecked): --on finishes it
            return None
        return f"every step of plan #{plan_row['n']} is done"
    k, _ = nxt
    need = plan.unmet_need(plan.record_of(plan_row), project, k)
    if need is not None:
        return f"{need['words']} (Auto never starts a step with an unmet need)"
    folder = projects.folder_of(project)
    decision = filemode.decide(folder, files_ready=files_ready or (lambda: (True, None)))
    if not decision.on:
        return f"file mode is off on {project}: {decision.why}"
    if not claude_ok:
        return "Claude isn't available"
    return None


def project_entry(conn, project, *, claude_ok=True, files_ready=None):
    """Decision 10: a project's `auto` for the project list, status and the page: its run, and whether the switch shows
    off (an --on would be accepted now) or hidden, with why. Status passes Claude's availability and the file check as
    it read them (`projects_view`); the project list alone judges offline."""
    run = run_row_of(conn, project)
    why = can_start(conn, project, run, claude_ok=claude_ok, files_ready=files_ready)
    return project_auto(conn, project, run, can_start=why is None, why=why)


def stale_running_stopped(record):
    """A `running` step entry read by a new process can only be stale (the process that ran it is gone, or was
    interrupted before the step's own command took over): it reads as stopped, so `--on` resumes or restarts it."""
    for step in record.get("steps") or ():
        if step.get("state") == "running":
            step["state"] = "stopped"
    return record
