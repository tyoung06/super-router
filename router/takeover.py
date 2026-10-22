"""The takeover (build brief 24, decisions 6 and 7): when a call stops, the router hands it to the next agent at once, by
itself, once per task. Pure: it reads the task row, its calls, availability and the preset, and says who takes over and
who checks after; `__main__` runs it at every place a stop is written (route, relay, split, `sr check`, route's own
Grok wait). `sr resume` stays for what is still manual: a process that ended, and a stop the takeover couldn't take.

Three kinds of stop are covered: a failed call (a send that fails, a sign-out, "model at capacity", any agent error, a
local call at its 600 s, a stage the router won't send because it is too long for Grok), a plan limit on Claude or
ChatGPT, and a Grok call with no answer by overdue (2 × `grok_timeout_minutes`). Not covered, as today: a cancel, a
contract still missing after its re-ask, an error in the router's own code, a process that ended, a check failed twice,
an override, a Cursor call, a `versus` or `vote` task, a fallback's calls, and Grok's call on a skill that is Grok
Bot's alone (`make_media`, and `x_social_pulse` since the owner's decision of 21 Oct): it keeps the usual Grok timeout, its
overdue note only, and its answer whenever it comes. If the takeover's own call stops, the task ends with both reasons.

Who takes over. A routed task's (or a piece's) doer call (do, fix) goes to the skill's second agent, then Claude, then
ChatGPT; a check round goes to the next checker by decision 4. A relay stage or check round goes as Resume says today
(the other of Claude and ChatGPT, every slot rule kept); a Grok stage goes to ChatGPT, then Claude. A split's plan and
integration go to the other of the two. Every pick skips the agent that stopped, any agent already stopped in this
task, any agent that isn't available, Cursor, Grok on a task with files, and Grok when the prompt would pass its limit
(`exclude`, from the caller that built it). The checker after comes from decision 4; on a relay task it is the
preset's checker, else the other of Claude and ChatGPT when it isn't the doer and hasn't stopped; with nobody left the
result is unchecked, never checked by an agent that just stopped.

The rows: the stopped call stays (a failed row; an overdue Grok row becomes failed with code `overdue`); the takeover's
call is `<stopped call id>-takeover`, with `resume_of` naming the stopped call, so every reader that lets a resumed row
stand in reads it the same way; the task row's doer, checker and check state are updated while it is open. Once per
task: a row ending `-takeover`. The manual resume counts only `-resume` rows (router/resume.py)."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from router import availability, log, plan_limit, relay, resume, routing

SUFFIX = relay.TAKEOVER_SUFFIX
OVERDUE = "overdue"          # a Grok call still out at 2 × grok_timeout_minutes (decision 6)
TOO_LONG = "too_long"        # a call the router won't send: too long for Grok (decision 6)
LATE = "late"                # an overdue Grok call whose answer came after the takeover: stored, never used (decision 7)
INTERNAL = "internal_error"  # a call that failed in the router's own code: never taken over
COVERED = (plan_limit.CODE, OVERDUE, TOO_LONG, None)   # None: any other failed call
NEVER = ("cursor",)          # a takeover never goes to Cursor, and a Cursor call is never taken over
GROK_SKIPPED = "Grok skipped: "  # The owner's C11: a Grok check past its limit, skipped when the checker is chosen
LATE_MINUTES = 30            # decision 7: a late answer is looked for up to the 30-minute Grok timeout after its send
_TOO_LONG_WORDS = "too long for Grok ("
_OPEN = ("queued", "sent")


@dataclass(frozen=True)
class Plan:
    """What the takeover does, or why it doesn't. `to` makes the stopped call again as `call_id`; `agent`, `checker`,
    `check_state` and `check_note` are the task row after. `why` is the stop in words."""
    ok: bool
    reason: str | None = None
    stopped: object = None
    code: str | None = None
    to: str | None = None
    kind: str | None = None
    stage: int | None = None
    role: str | None = None
    call_id: str | None = None
    agent: str | None = None
    checker: str | None = None
    check_state: str | None = None
    check_note: str | None = None
    why: str | None = None
    nobody: bool = False   # declined because no agent could take it (said in Terminal); False for a rule's refusal

    @property
    def substitute(self):
        """Resume's prompt rebuild (`__main__._resume_call`) reads a plan's substitute: here, who takes over."""
        return self.to


def _no(reason, nobody=False, stopped=None):
    return Plan(False, reason, nobody=nobody, stopped=stopped)


def _mode(task):
    return task["mode"] if "mode" in task.keys() and task["mode"] else "route"


def call_id(stopped_id):
    return f"{stopped_id}{SUFFIX}"


def is_takeover(call):
    return relay.is_takeover(call)


def used(calls):
    """The task's one takeover: a row ending `-takeover`, whatever became of it."""
    return any(is_takeover(c) for c in calls)


def code_of(call):
    """A stopped row's code: plan_limit, overdue, too_long, process_ended, internal_error, or None (any other failure)."""
    return call["reason_code"] if "reason_code" in call.keys() else None


def why_words(call):
    """A stopped call in words: `Claude hit its plan limit`, `Grok Bot was overdue`, `too long for Grok Bot (4210
    characters)`, `ChatGPT's call failed: codex exited 1: model at capacity`."""
    name, code = availability.name_of(call["agent"]), code_of(call)
    if code == plan_limit.CODE:
        return f"{name} hit its plan limit"
    if code in (OVERDUE, LATE):  # a late answer doesn't change why the call was taken over
        return f"{name} was overdue"
    text = (call["text"] or "").strip()
    if text.startswith(_TOO_LONG_WORDS):
        return f"too long for {name} ({text[len(_TOO_LONG_WORDS):].split(' ', 1)[0]} characters)"
    first = text.splitlines()[0][:160] if text else "no reason was logged"
    return f"{name}'s call failed: {first}"


def stopped_agents(calls):
    """{agent: why} for every agent whose call stopped in this task for a covered reason (decision 6: never picked)."""
    found = {}
    for c in calls:
        if c["status"] == "failed" and (code_of(c) in COVERED or code_of(c) == LATE) and c["agent"] not in found:
            found[c["agent"]] = why_words(c)
    return found


def replaced(call, calls):
    """The row a takeover (or resume) row stands in for, or None."""
    named = relay.resume_of(call)
    return next((c for c in calls if c["call_id"] == named), None) if named else None


def both(call, calls):
    """The words when the takeover's own call stopped (decision 6, "the task ends with both reasons"): `ChatGPT hit its
    plan limit, after Claude hit its plan limit`. None for a row that is no takeover's."""
    before = replaced(call, calls) if is_takeover(call) else None
    if before is None:
        return None
    return f"{why_words(call)}, after {why_words(before)}"


def pending(task, calls):
    """The stopped call a takeover may still pick up, or None: the task is open, and its newest row failed for a covered
    reason, is no takeover itself, no fallback's, and nothing made it again. A process that dies between the stop and
    the takeover's row leaves exactly this, so the next `sr check` takes over."""
    if task["status"] not in _OPEN or not calls:
        return None
    last = calls[-1]
    if last["status"] != "failed" or log.fallback_of(last) or is_takeover(last) or code_of(last) not in COVERED:
        return None
    if any(relay.resume_of(c) == last["call_id"] for c in calls):
        return None
    return last


def _not_covered(task, calls, stopped, preset):
    if task["status"] not in _OPEN:
        return "the task is not open"
    if code_of(stopped) not in COVERED:
        return f"a {code_of(stopped)} stop is never taken over"
    if task["route_reason"] == "override":
        return "an override is never taken over: you chose the agent"
    if stopped["agent"] in NEVER:
        return "a Cursor call is never taken over"
    if preset is not None and (getattr(preset, "has_reviews", False) or getattr(preset, "tallies", False)):
        return f"a {preset.name} task is never taken over"
    if any(log.fallback_of(c) for c in calls):
        return "a fallback's calls are never taken over"
    only = routing.ONLY.get(task["skill"])
    if only is not None and stopped["agent"] == only:  # nothing stands in for a skill that is one agent's alone
        return (f"{availability.name_of(only).split()[0]}'s {task['skill']} call is never taken over: {task['skill']} "
                f"is {availability.name_of(only)}'s alone")
    if is_takeover(stopped):
        return "the takeover's own call stopped: the task ends with both reasons"
    if used(calls):
        return "the task's one takeover was used"
    return None


def _refusal(agent, stopped_by, available, files):
    """Why `agent` can't take over, or None when it can."""
    if agent in NEVER:
        return f"{availability.name_of(agent)} never takes over"
    if agent in stopped_by:
        return stopped_by[agent]
    found = available(agent)
    if not found.available:
        return found.why
    if agent == "grok" and files:
        return "a task with files never goes to Grok Bot"
    return None


def _first(candidates, stopped_by, available, files, skip=()):
    """(the first candidate that can take over, None), or (None, the first reason one couldn't)."""
    why = None
    for agent in dict.fromkeys(c for c in candidates if c):
        if agent in skip:
            continue
        refused = _refusal(agent, stopped_by, available, files)
        if refused is None:
            return agent, None
        why = why or refused
    return None, why


def _unchecked(why):
    return None, "unchecked", f"{routing.NO_CHECKER} ({why})"


def _kept_note(task):
    """The task's check note, kept across a takeover, except a Grok timeout note (the Grok call is no longer out)."""
    note = task["check_note"]
    return None if (note or "").startswith(log.GROK_NOTES) else note


def decide(task, calls, stopped, *, available, skills=None, preset=None, exclude=None):
    """The takeover of `stopped` (a failed row of `task`), or why not. `available` is a function of an agent's name giving
    its availability (checked fresh), `skills` the skill table's skills, `preset` a relay or split task's filled
    preset, `exclude` {agent: why} the caller rules out (Grok past its prompt limit)."""
    refused = _not_covered(task, calls, stopped, preset)
    if refused:
        return _no(refused, stopped=stopped)
    why = why_words(stopped)
    stopped_by = {**stopped_agents(calls), stopped["agent"]: why, **(exclude or {})}
    files = bool(log.files_of(task))
    if _mode(task) in ("route", "piece"):
        found = _routed(task, stopped, stopped_by, available, files, (skills or {}).get(task["skill"]) or {})
    else:
        found = _chained(task, calls, stopped, stopped_by, available, preset)
    if isinstance(found, str):
        return _no(found, nobody=True, stopped=stopped)
    to, agent, checker, state, note = found
    kind = "stage" if stopped["kind"] == "reask" else stopped["kind"]  # a stopped re-ask is made again as the stage (D8)
    return Plan(True, stopped=stopped, code=code_of(stopped), to=to, kind=kind, stage=stopped["stage"],
                role=stopped["role"], call_id=call_id(stopped["call_id"]), agent=agent, checker=checker,
                check_state=state, check_note=note, why=why)


def _routed(task, stopped, stopped_by, available, files, row):
    """A routed task or a piece: (to, agent, checker, state, note), or why nobody can take over."""
    if stopped["kind"] in ("check", "recheck"):
        to, why = routing.pick_checker(row, task["agent"], available, stopped=stopped_by)
        if to is None:
            return f"no other agent can check it ({why})"
        return to, task["agent"], to, "pending", _kept_note(task)
    to, why = _first([row.get("second"), "claude", "chatgpt"], stopped_by, available, files)
    if to is None:
        return f"no other agent can take it over ({why})"
    if task["check_state"] == "not_needed":  # a quick answer is never checked
        return to, to, None, "not_needed", None
    checker, why = routing.pick_checker(row, to, available, stopped=stopped_by)
    if checker is None:
        return (to, to) + _unchecked(why)
    return to, to, checker, "pending", _kept_note(task)


def _builders(agent):
    """Resume's substitute for Claude or ChatGPT (the other of the two); for a Grok stage, ChatGPT then Claude."""
    other = relay.other_builder(agent)
    return [other] if other else ["chatgpt", "claude"]


def _chained(task, calls, stopped, stopped_by, available, preset):
    """A relay or split task: (to, agent, checker, state, note), or why nobody can take over."""
    if preset is None:
        return "its preset can't be read"
    kind, n = stopped["kind"], stopped["stage"]
    view = log.fallback_view(calls)
    skip = []
    if kind in log.STAGE_KINDS:
        check_stage = preset.check_stage
        before = relay.accepted(view, n - 1) if check_stage is not None and n == check_stage.n else None
        for agent in _builders(stopped["agent"]):
            if resume._redteam_refusal(preset, view, kind, n, agent):
                skip.append(agent)   # every slot rule: an attacker never attacks its own build; a revise stage, nobody
            if before is not None and before["agent"] == agent:
                skip.append(agent)   # a check stage only by a builder that did not make the stage before
    else:
        work = resume._work_checked(task, view, kind)
        if work is not None:
            skip.append(work["agent"])  # a check round only by an agent that did not do the work it checks
    to, why = _first(_builders(stopped["agent"]), stopped_by, available, False, skip=skip)
    if to is None:
        return f"no other agent can take it over ({why or 'every one that could would break a slot rule'})"
    if kind in ("check", "recheck"):
        return to, task["agent"], to, "pending", _kept_note(task)
    plan = resume._plan(task, stopped, to, preset)
    agent, checker = plan.agent, plan.checker
    if (not plan.swapped and checker is not None and checker != agent
            and _refusal(checker, stopped_by, available, False) is None):
        return to, agent, checker, plan.check_state, _kept_note(task) if plan.check_state != "pending" else None
    if checker is None and plan.check_state != "pending":
        return to, agent, None, plan.check_state, plan.check_note
    # decision 6: the checker after is the preset's checker, else the other of Claude and ChatGPT when it isn't the doer
    # and hasn't stopped; never Resume's swap to an agent that has just stopped
    checker, why = _first([preset.check_agent, relay.other_builder(agent)], stopped_by, available, False, skip=[agent])
    if checker is None:
        return (to, agent) + _unchecked(why or f"only {availability.name_of(agent)} could")
    return to, agent, checker, "pending", None


def found(calls):
    """(the takeover's row, the row it stands in for), or (None, None)."""
    row = next((c for c in calls if is_takeover(c)), None)
    before = replaced(row, calls) if row is not None else None
    return (row, before) if before is not None else (None, None)


def record(calls):
    """The task's takeover for the JSON (decision 14): {call_id, stopped_call, call, from, to, why, code, state}, or None.
    `code` is why it was taken over (a late answer keeps `overdue`); `state` the takeover call's status."""
    row, before = found(calls)
    if row is None:
        return None
    code = OVERDUE if code_of(before) == LATE else code_of(before)
    return {"call_id": row["call_id"], "stopped_call": before["call_id"], "call": resume.stopped_text(before),
            "from": before["agent"], "to": row["agent"], "why": why_words(before), "code": code, "state": row["status"]}


def late(calls, now=None):
    """A Grok call taken over at overdue, for the JSON (decision 7): {call_id, state, until, arrived_at, round_file} or
    None. `state` is `out` while its answer may still come (up to LATE_MINUTES after the send), `arrived` once it came
    (stored, never used), `expired` after."""
    row = next((c for c in calls if c["agent"] == "grok" and code_of(c) in (OVERDUE, LATE)), None)
    if row is None:
        return None
    until = datetime.fromisoformat(row["sent_at"]) + timedelta(minutes=LATE_MINUTES)
    if code_of(row) == LATE:
        state = "arrived"
    else:
        state = "out" if (now or datetime.now(timezone.utc)) < until else "expired"
    round_file = row["round_file"] if "round_file" in row.keys() else None
    return {"call_id": row["call_id"], "state": state, "until": until.isoformat(timespec="seconds"),
            "arrived_at": row["finished_at"] if state == "arrived" else None, "round_file": round_file}


def words(plan):
    """The one line Terminal prints and the card shows: `ChatGPT took over the first call · Claude hit its plan limit`."""
    return f"{availability.name_of(plan.to)} took over {resume.stopped_text(plan.stopped)} · {_short(plan.why)}"


def _short(why):
    from router import cardline  # cardline reads takeover records too
    return cardline.short(why)
