"""A task's state as two fields (rules v2.30, Router for the interface, "States are fields"; build brief 21, decision 1):
`waiting_on`, what an open task is blocked on, or `outcome`, how an ended task ended; never both. Computed by one
function, `of`, from the task row and its call rows, and never stored, so there is no second copy of state to drift.
Never read from check_note, which stays for people. Pure: no call, no write.

The owner's go of 20 Oct (Q1 to Q4): a delivered result no check passed or failed is `unchecked` (a quick answer reads
`unchecked` with check_state `not_needed`); `picked` is a versus task ended by their pick, none included, and `tie` a vote
with no majority ended by their pick; a double fail is `failed_check` and a plan-limit stop `plan_limit`, both ended: the
fallback and resume offers ride beside the state (router/jsonview.py), never as a wait. Brief 22: `process_ended` is a
process-ended stop (`sr check` writes it from a dead run), with the resume offer beside it; `probe` and `memory` are
reserved until brief 22's D makes them happen. Decision 1: `attack` left the vocabulary (nothing waits on the owner during an
attack stage; `working` names the stage)."""
from dataclasses import dataclass

from router import log, plan_limit

WAITING_ON = ("needs_label", "split_plan", "pick", "vote_pick", "grok", "piece", "probe", "memory")
OUTCOMES = ("passed", "fixed", "failed_check", "returned", "cancelled", "timed_out", "picked", "tie", "skipped",
            "stopped", "unchecked", "plan_limit", "process_ended")
RESERVED = ()  # brief 22 made every reserved word happen
# Jev answers that leave a task waiting for the owner's label (rules v2.28, Jev): the terminal asks, or it comes back.
FLOOR_STATUSES = ("below_floor", "none_of_these", "error", "over_cap", "not_set_up")  # brief 24: no Jev key
PROCESS_ENDED = "process_ended"  # brief 22: a call whose sr process ended while it ran (log.REASON_CODES)
_CHECK_OUTCOMES = {"passed": "passed", "fixed": "fixed", "failed": "failed_check"}  # any other check state: unchecked


@dataclass(frozen=True)
class State:
    waiting_on: str | None
    outcome: str | None

    @property
    def ended(self):
        return self.outcome is not None

    def as_dict(self):
        return {"waiting_on": self.waiting_on, "outcome": self.outcome}


def _get(row, key):
    return row[key] if key in row.keys() else None


def _skipped(plan, task_id):
    return bool(plan) and any(p["id"] == task_id and p["skipped"] for p in plan.get("pieces", []))


def of(task, calls, *, plan=None, held=False, waiting=None):
    """The state of one task. `calls` are its call rows, oldest first. `plan` is the stored plan of a piece's split (for
    `skipped`); `held` says a queued piece waits for another piece's Grok call (the caller reads the siblings); `waiting`
    (brief 22) is `probe` or `memory` when the task's own run waits on that lock (router/locks.py, read by the caller).
    First match wins; every row shape lands on exactly one value."""
    status, mode = task["status"], _get(task, "mode") or "route"
    roles = {c["role"] for c in calls if c["kind"] in log.STAGE_KINDS}
    review, vote = "review" in roles, "vote" in roles   # a preset with review stages (versus), or a tally (vote)
    is_open = status in ("queued", "sent")
    if mode == "piece" and not is_open and _skipped(plan, task["task_id"]):
        return State(None, "skipped")
    if status in ("cancelled", "timed_out"):
        return State(None, status)
    if status == "returned":
        code = _get(task, "reason_code")
        if code:  # a return: the code its maker stored (brief 21); only a label can still be given
            if code == "needs_label" and not _get(task, "answered_by"):
                return State("needs_label", None)
            return State(None, "returned")  # brief 22 (decision 2): a floor row answered by flag waits no more
        if mode == "split":
            stored = log.split_plan_of(task)
            if stored is not None:
                return State("piece" if stored.get("approved") else "split_plan", None)
        if mode == "relay" and review:
            return State("pick", None)
        if mode == "relay" and vote:
            return State("vote_pick", None)
        return State(None, "returned")  # a row from before version 14: nothing is reconstructed (decision 3)
    if is_open:
        if waiting in ("probe", "memory"):  # brief 22 (decisions 7 and 8): its run waits on a probe or a memory start
            return State(waiting, None)
        if held or any(c["agent"] == "grok" and c["status"] == "sent" for c in calls):
            return State("grok", None)
        if (mode in ("route", "piece") and not calls and not _get(task, "agent")
                and _get(task, "jev_status") in FLOOR_STATUSES):
            return State("needs_label", None)  # the terminal prompt is up (or its process ended there: brief 22)
        return State(None, None)  # in progress: a call is running, or the next step waits for `sr check`
    view = log.fallback_view(calls)  # a fallback that stopped changes nothing (rules v2.17)
    if view and view[-1]["status"] == "failed" and view[-1]["reason_code"] == plan_limit.CODE:
        return State(None, "plan_limit")
    if view and view[-1]["status"] == "failed" and view[-1]["reason_code"] == PROCESS_ENDED:
        return State(None, "process_ended")  # brief 22 (decision 4): written only by `sr check`, from a dead run
    if status == "failed":
        if mode == "relay" and (review or vote) and _get(task, "failed_stage") is None:
            return State(None, "tie" if vote else "picked")  # The owner picked none
        return State(None, "stopped")
    if mode == "relay" and review:
        return State(None, "picked")
    if mode == "relay" and vote:
        return State(None, "passed" if task["check_state"] == "passed" else "tie")
    return State(None, _CHECK_OUTCOMES.get(task["check_state"], "unchecked"))
