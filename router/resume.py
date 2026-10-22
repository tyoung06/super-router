"""`sr resume <n>` (rules v2.15, Resume): decide from the log alone whether a task that stopped on
Claude's or ChatGPT's plan limit can be resumed, and who does what. Pure: no agent is called here;
`__main__.cmd_resume` runs the plan.

The stopped call is the task's last call: every way a plan limit ends a task (a failed first call,
a check, fix or re-check round that didn't run, a relay stage that stopped the chain) ends on that
row. The substitute is always the other of Claude and ChatGPT, and it is sent what the stopped
agent was sent, never the stopped agent's output (a stopped re-ask is replaced by a fresh stage:
The owner's D8). No agent checks its own work: when the checker would be the agent that now did the
work, the other builder checks instead.
"""
from dataclasses import dataclass

from router import checking, log, plan_limit, relay

PROCESS_ENDED = "process_ended"  # build brief 22: written by `sr check` on a call whose sr process ended while it ran
SAME_AGENT = ("claude", "chatgpt", "cursor")  # the local agents a process-ended stop can be made again by

ROUNDS = {"do": "the first call", "check": "the check round", "fix": "the fix round", "recheck": "the re-check"}


@dataclass(frozen=True)
class Plan:
    """What `sr resume` will do, or why it won't. `agent` and `checker` are the task row's doer and
    checker after the resume; `kind`, `stage`, `role` and `call_id` describe the substitute's call."""
    ok: bool
    reason: str | None = None
    stopped: object = None
    stopped_agent: str | None = None
    substitute: str | None = None
    agent: str | None = None
    checker: str | None = None
    check_state: str | None = None
    check_note: str | None = None
    swapped: bool = False
    kind: str | None = None
    stage: int | None = None
    role: str | None = None
    call_id: str | None = None
    both_at_limit: bool = False   # refused because the substitute's own call stopped on its limit too
    code: str | None = None       # build brief 21: a refusal's reason_code (not_resumable unless named)


SUFFIX = "-resume"


def call_id(stopped_id):
    """The substitute's call id: the stopped call's id plus `-resume` (one resume per task)."""
    return f"{stopped_id}{SUFFIX}"


def is_resume(call):
    """A row `sr resume` made. Build brief 24 (the owner's C3): a takeover's row carries `resume_of` too, so the one manual
    resume is counted from the call id, never from `resume_of`."""
    return call["call_id"].endswith(SUFFIX)


def _no(reason, code="not_resumable", **kw):
    return Plan(False, reason, code=code, **kw)


def _first_line(text, limit=160):
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return line[:limit]


def _mode(task):
    return task["mode"] if "mode" in task.keys() and task["mode"] else "route"


def decide(task, calls, *, live, preset=None):
    """The plan for resuming `task` (its row and its calls, oldest first). `live` is the live agent
    names; `preset` is a relay task's preset. Eligibility is checked in the brief's order, each with
    its own reason; nothing here writes to the log."""
    status = task["status"]
    if status in ("queued", "sent"):
        return _no(f"it is still open ({status}); run `sr check` to finish it", code="wrong_state")
    stopped = calls[-1] if calls else None
    stopped_round = stopped is not None and stopped["status"] == "failed"
    # rules v2.17: a fallback is never resumed; a stopped fallback is run again with `sr fallback`
    if stopped_round and log.fallback_of(stopped):
        return _no(f"fallback. Run sr fallback {task['n']} again when it lifts.", stopped=stopped)
    # Build brief 22 (decision 3; the owner's Q1 (b)): a process-ended stop is made again by the same agent
    if stopped_round and stopped["reason_code"] == PROCESS_ENDED:
        return _process_ended(task, calls, stopped, live=live, preset=preset)
    if any(log.fallback_of(c) and c["status"] == "done" for c in calls):
        return _no("a fallback is never resumed", stopped=stopped)
    # Rules v2.28 (Resume): a stopped Cursor call is never resumed. Its stop is the pool's limit, or any other failure,
    # never a plan limit of Claude's or ChatGPT's; the owner runs the task again when the week resets, or with another agent.
    if stopped_round and stopped["agent"] == "cursor":
        return _no("cursor is never resumed: a Cursor stop is the pool's limit, not a plan limit; run the task again when "
                   "the week resets, or with another agent in the slot", stopped=stopped)
    if status == "done" and not (stopped_round and stopped["kind"] in ("check", "fix", "recheck")):
        return _no("it is done; only a task stopped by a plan limit or by a process that ended can be resumed")
    if status not in ("done", "failed"):
        return _no(f"it is {status}; only a task stopped by a plan limit or by a process that ended can be resumed")
    # 2. the call that stopped it stopped on a plan limit
    if not stopped_round or stopped["reason_code"] != plan_limit.CODE:
        why = _first_line(stopped["text"]) if stopped_round else _first_line(task["result"])
        if stopped is not None and stopped["status"] == "timed_out":
            why = "timed out"
        return _no(f"not a plan limit: {why or 'no reason was logged'}")
    # 2a. never a task on a preset with review stages (rules v2.16): the substitute for one builder is the
    # other builder, which already has its own candidate. The owner runs it again.
    if preset is not None and getattr(preset, "has_reviews", False):
        return _no(f"{preset.name} task. Run it again.", stopped=stopped)  # the stop line ends on its period
    # 2b. never a tally (rules v2.24, decision 10): one agent voting twice is not a vote
    if preset is not None and getattr(preset, "tallies", False):
        return _no("vote task: the substitute is already a voter", stopped=stopped)
    agent = stopped["agent"]
    # 3. Claude or ChatGPT only
    sub = relay.other_builder(agent)
    if sub is None:
        return _no(f"only Claude and ChatGPT can be resumed; the stopped call was {agent}'s", stopped=stopped)
    # 4. never an override task
    if task["route_reason"] == "override":
        return _no("an override task is never resumed: you chose the agent, so run it again when its plan limit "
                   "lifts", stopped=stopped)
    # brief 24 (decision 6): a stop of the takeover's own call ends the task with both reasons
    if relay.is_takeover(stopped):
        return _no("the router's takeover stopped too; the task ends with both reasons", stopped=stopped,
                   both_at_limit=True)
    # 5. one resume per task
    if any(is_resume(c) for c in calls):
        return _no("it was already resumed once", code="already_used", stopped=stopped,
                   both_at_limit=is_resume(stopped))
    # 6. the substitute is live (`live` None: not known here, as in `sr check` without the config)
    if live is not None and sub not in live:
        return _no(f"{sub} isn't live, so it can't take over", code="not_live", stopped=stopped)
    kind, n = stopped["kind"], stopped["stage"]
    refused = _redteam_refusal(preset, calls, kind, n, sub)
    if refused:
        return _no(refused, stopped=stopped)
    check_stage = preset.check_stage if preset is not None else None
    # 7. a check stage only by a builder that did not make the stage before
    if check_stage is not None and kind in log.STAGE_KINDS and n == check_stage.n:
        before = relay.accepted(calls, n - 1)
        if before is not None and before["agent"] == sub:
            return _no(f"{sub} made stage {n - 1}, so it can't check it; stage {n - 1}'s result stays unchecked",
                       stopped=stopped)
    # D4: a check round only by a builder that did not do the work it checks
    if kind in ("check", "recheck"):
        work = _work_checked(task, calls, kind)
        if work is not None and work["agent"] == sub:
            return _no(f"{sub} did the work, so it can't check it; the result stays unchecked", stopped=stopped)
    return _plan(task, stopped, sub, preset)


def _process_ended(task, calls, stopped, *, live, preset):
    """Build brief 22 (decision 3, the owner's Q1 (b) of 20 Oct): the call that was running when its process ended is made
    again by the same agent (Cursor included: Cursor's no-resume rule is for a used-up pool, not a crash), with what it
    was sent. No substitute is involved, so the rules that guard against one do not apply: a `versus`, a `vote`, an
    override and a later round of a task that fell back may be resumed this way; the fallback's own redo writes no note,
    so it is never a process-ended stop. One resume per task, as for a plan limit."""
    agent = stopped["agent"]
    if agent not in SAME_AGENT:
        return _no(f"{agent}'s calls are not made by this process; nothing to make again", stopped=stopped)
    if any(is_resume(c) for c in calls):
        return _no("it was already resumed once", code="already_used", stopped=stopped)
    if live is not None and agent not in live:
        return _no(f"{agent} isn't live, so it can't make the call again", code="not_live", stopped=stopped)
    return _plan(task, stopped, agent, preset)


REVISE_REFUSAL = "revise stage can only be done by the agent that built stage 1"


def _redteam_refusal(preset, calls, kind, n, sub):
    """Rules v2.23 on a preset with a revise stage: a stopped revise stage has no substitute; a stopped build or
    attack stage may not be taken by the agent in the other of the two (an attacker never attacks its own build).
    None when the resume may go on."""
    revise = getattr(preset, "revise_stage", None) if preset is not None else None
    if revise is None or kind not in log.STAGE_KINDS:
        return None
    if n == revise.n:
        return REVISE_REFUSAL
    attack = preset.attack_stage
    if attack is None:
        return None
    if n == revise.revise_of and sub == attack.agent:
        return (f"{sub} would build stage {n} and revise it at stage {revise.n}, but {sub} attacks it at stage "
                f"{attack.n}; an attacker does not attack its own build. Run it again")
    if n == attack.n:
        built = relay.accepted(calls, attack.attack_of)
        if built is not None and built["agent"] == sub:
            return (f"{sub} would attack stage {attack.attack_of}, which {sub} built; an attacker does not attack "
                    "its own build. Run it again")
    return None


def _work_checked(task, calls, kind):
    """The call whose result the stopped check round was judging: the result call for a check,
    the fix for a re-check."""
    if kind == "check":
        return checking._result_call(task, calls)
    fixes = [c for c in calls if c["kind"] == "fix"]
    return fixes[-1] if fixes else None


def _plan(task, stopped, sub, preset):
    kind, n = stopped["kind"], stopped["stage"]
    agent, checker = task["agent"], task["checker"]
    check_state, check_note = task["check_state"], task["check_note"]
    check_stage = preset.check_stage if preset is not None else None
    if kind in ("do", "fix"):
        agent = sub
    elif kind in ("check", "recheck"):
        checker = sub
    elif preset is not None:  # a relay stage
        if check_stage is not None and n == check_stage.n:
            checker = sub
        elif n == preset.stages[-1].n or (check_stage is not None and n == check_stage.n - 1):
            agent = sub   # the stage whose result is the task's result, or is checked by the check stage
        elif getattr(preset, "revise_stage", None) is not None and n == preset.revise_stage.revise_of:
            agent = sub   # rules v2.23: the substitute's build is the one it revises, so its revision is the result
    swapped = checker is not None and checker == agent
    if swapped:
        checker = relay.other_builder(agent)
    rechecked = kind in ("check", "fix", "recheck") or (check_stage is not None and kind in log.STAGE_KINDS
                                                        and n == check_stage.n)
    if rechecked:
        check_state, check_note = "pending", None
    new_kind = "stage" if kind == "reask" else kind   # D8: a stopped re-ask is replaced by a fresh stage
    return Plan(True, stopped=stopped, stopped_agent=stopped["agent"], substitute=sub, agent=agent, checker=checker,
                check_state=check_state, check_note=check_note, swapped=swapped, kind=new_kind, stage=n,
                role=stopped["role"], call_id=call_id(stopped["call_id"]))


def stopped_text(call):
    """The stopped call in words: "the first call", "the check round", "stage 2 (build)",
    "stage 2's re-ask (build)"."""
    if call["kind"] == "stage":
        return f"stage {call['stage']} ({call['role']})"
    if call["kind"] == "reask":
        return f"stage {call['stage']}'s re-ask ({call['role']})"
    return ROUNDS[call["kind"]]


def describe(task, plan):
    """What the owner sees before the resume runs: the stopped call, the substitute, the checker."""
    stopped = plan.stopped
    head = f"Resuming #{task['n']} {task['task_id']}: {stopped_text(stopped)} by {plan.stopped_agent}"
    if stopped["reason_code"] == PROCESS_ENDED:  # brief 22: the same agent makes it again
        lines = [f"{head} stopped when its process ended.", f"{plan.substitute} makes it again, with what it was sent."]
    elif stopped["kind"] == "reask":
        lines = [f"{head} stopped on its plan limit.",
                 f"{plan.substitute} does stage {stopped['stage']} again from the start, with the task and the "
                 "stage before's result (never claude's or chatgpt's earlier output)."]
    else:
        lines = [f"{head} stopped on its plan limit.",
                 f"{plan.substitute} does it instead, with what {plan.stopped_agent} was sent."]
    if plan.kind in ("check", "recheck"):
        return lines
    if plan.check_state == "not_needed":
        lines.append("No check: a quick answer is never checked.")
    elif plan.check_state == "unchecked":
        lines.append(f"Unchecked: {plan.check_note or 'no checker'}.")
    elif plan.checker is not None:
        why = f" ({plan.agent} would otherwise check its own work)" if plan.swapped else ""
        lines.append(f"Checker: {plan.checker}{why}.")
    return lines


def stop_line(task, calls, *, live, preset=None):
    """The line that ends the message when a plan limit stops a task (rules v2.15: the router names
    the command and the substitute, or says why the task can't be resumed). None when the task did
    not stop on a plan limit."""
    if task["status"] in ("queued", "sent") or not calls:
        return None
    stopped = calls[-1]
    if stopped["status"] != "failed" or stopped["reason_code"] not in (plan_limit.CODE, PROCESS_ENDED):
        return None
    plan = decide(task, calls, live=live, preset=preset)
    agent = stopped["agent"]
    if stopped["reason_code"] == PROCESS_ENDED:  # brief 22
        if plan.ok:
            return f"Process ended on {agent}. Run: sr resume {task['n']}  ({agent} makes the call again)"
        return f"Process ended on {agent}. Not resumable: {plan.reason}"
    if plan.ok:
        return f"Plan limit on {agent}. Run: sr resume {task['n']}  (continues with {plan.substitute})"
    if plan.both_at_limit and relay.is_takeover(stopped):  # brief 24 (decision 6): both reasons, no resume
        return f"Plan limit on {agent} too: it took over the stopped call. #{task['n']} stays stopped; it can't be resumed."
    if plan.both_at_limit:
        first = relay.other_builder(agent)
        return (f"Plan limit on {agent} too: {first} and {agent} are both at their plan limit. "
                f"#{task['n']} stays stopped; it can't be resumed again.")
    return f"Plan limit on {agent}. Not resumable: {plan.reason}"
