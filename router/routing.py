"""Who does a task, and who checks it. Pure: data in, a decision out. No calls, so every case
is a plain unit test.

An override tag (@claude, @grok) names the doer. Otherwise the skill comes from Jev's label, or
from the owner when Jev isn't sure, and the skill table picks the doer. A task whose skill is recall with
no --project and no --chat comes back (rules v2.28, Jev): there is nothing to recall from.

Build brief 24 (decisions 3 and 4) reads availability (router/availability.py) where the live flags were read:
- the doer is the skill's best agent, then its interim (when set), then its second, then Claude: the first that is
  available. A doer other than the best is a stand-in, and its route_reason says so: `stand-in for <agent>: <why>`.
  `make_media` and `x_social_pulse` are Grok's alone (a code constant; the skill table is not edited): without Grok
  Bot they come back (the owner, 21 Oct, after F: web search can't see X posts).
- the checker is the skill's second agent, then Claude, then ChatGPT: never the doer, never Cursor, Grok only where the
  skill table names it second (bulk_text). With nobody left the result is unchecked: `no other agent available to check
  (<why>)`. A quick_answer is never checked.
A caller that hands no availability gets today's table: a live agent is available (availability.everyone).
"""
import re
from dataclasses import dataclass

from router import availability

NEVER_CHECKED = "quick_answer"  # SUPER-ROUTER.md, Checking
NEEDS_TAG = "recall"            # SUPER-ROUTER.md v2.28, Jev: a recall task needs --project or --chat
NO_TAG_FOR_RECALL = "returned: recall needs --project or --chat: nothing to recall from"
# Rules v2.29 (the owner, 2026-10-20, after live #103): a tagged recall task never calls an agent without its memory. In
# router/__main__.py: the first call's fresh recall needs the store; a round, fallback or resume uses its saved block
# without asking the store and is held back only when that block was itself unavailable.
# Brief 23 (decision 5, the owner's change 1): plain words, by the memory setting; `off` never starts the store
NO_STORE_FOR_RECALL = "memory unavailable (the store could not be started): nothing to recall from"
NO_STORE_FOR_RECALL_OFF = "memory unavailable (memory is off in settings): nothing to recall from"
# brief 24 (decision 3): Grok's alone, nothing stands in for it; x_social_pulse too since the owner's decision of 21 Oct, after
# F (#106, #112: web search can't see X posts, and both stand-ins ended failed_check)
ONLY = {"make_media": "grok", "x_social_pulse": "grok"}
NEVER_CHECKS = ("cursor",)       # rules v2.28: Cursor never checks
STAND_IN = "stand-in for "       # route_reason of a stand-in: `stand-in for <agent>: <why>` (brief 24, decision 3)
NO_CHECKER = "no other agent available to check"
# decision 9; Meta: the owner. X research has no stand-in since 21 Oct: its note stays for the cards of tasks logged before
SOCIAL_NOTE = {"x_social_pulse": "done without X", "meta_social_trends": "done without Meta"}
NONE_OF_THESE = "none"          # The owner's answer: none of these skills
NO_ANSWER = "no answer"         # three answers in a row that weren't choices, or the input ended


@dataclass(frozen=True)
class Decision:
    action: str                 # "send", "return" (to the owner) or "ask" (the owner for the skill)
    skill: str | None = None
    skill_source: str | None = None  # "jev" or "owner"
    agent: str | None = None    # the doer
    reason: str | None = None   # route_reason: best, override, `stand-in for <agent>: <why>`, or "returned: <why>"
    checker: str | None = None
    check_state: str | None = None
    check_note: str | None = None  # why there is no check, when check_state is unchecked
    code: str | None = None     # build brief 21: a return's reason_code (log.RETURN_CODES), named beside `reason`


def parse_override(task, agents):
    """'@name rest' -> ('name', 'rest'); no tag -> (None, task). The tag is any agent name in
    `agents`, any case, then whitespace or the end of the text, so '@grokking' is not a tag.
    The caller refuses a tag for an agent that isn't live."""
    names = "|".join(re.escape(name) for name in agents)
    m = re.match(rf"@({names})(?:\s+|$)", task.lstrip(), re.IGNORECASE) if names else None
    if not m:
        return None, task
    return m.group(1).lower(), task.lstrip()[m.end():].strip()


NO_FILES_FOR_GROK = "returned: a task with files can't go to grok (a file goes only to Claude and ChatGPT)"
# Rules v2.10 and v2.28 (Media): a task with files whose doer would be Grok or Cursor comes back with the label shown.
NO_FILES_FOR = {"grok": NO_FILES_FOR_GROK,
                "cursor": "returned: a task with files can't go to cursor (a file goes only to Claude and ChatGPT)"}


def decide(jev, roster, *, override=None, answer=None, can_ask=True, files=False, tagged=False, available=None):
    """jev: Jev's answer (router/jev.py). override: the tagged agent, if any. answer: the owner's
    skill key, NONE_OF_THESE or NO_ANSWER, once the owner was asked. can_ask: False when there is no
    terminal to ask in. files: True when the task carries files, which Grok may never get
    (rules v2.10, Media): such a task comes back to the owner when Grok would do it. tagged: True when the task
    carries --project or --chat; without a tag a recall task comes back (rules v2.28, Jev), an override apart.
    available: {agent: Availability}, or a function of an agent's name giving one (brief 24); None: today's table."""
    table = _table(available, roster)
    decision = _decide(jev, roster, override=override, answer=answer, can_ask=can_ask, tagged=tagged, table=table)
    if files and decision.action == "send" and decision.agent in NO_FILES_FOR:
        return Decision("return", decision.skill, decision.skill_source, reason=NO_FILES_FOR[decision.agent],
                        code="files_to_agent")
    return decision


def _table(available, roster):
    """One way to ask availability, whatever the caller handed: a function of a name, a dict, or nothing."""
    if available is None:
        found = availability.everyone(roster)
        return lambda name: found.get(name) or availability.Availability(False, f"{availability.name_of(name)} is off",
                                                                         "not_live")
    if callable(available):
        return available
    return lambda name: available.get(name) or availability.Availability(
        False, f"{availability.name_of(name)} isn't in config/agents.json", "not_live")


def _decide(jev, roster, *, override, answer, can_ask, tagged, table):
    if override:
        return _for_override(jev, roster, override, table)
    if jev["status"] == "ok" and jev.get("label") in roster.skills:
        return _for_skill(jev["label"], "jev", roster, tagged, table)
    if answer is None:
        return Decision("ask") if can_ask else Decision("return", reason="returned: needs your label", code="needs_label")
    if answer == NONE_OF_THESE:
        return Decision("return", reason="returned: no skill", code="no_skill")
    if answer == NO_ANSWER:
        return Decision("return", reason="returned: no valid answer", code="no_answer")
    if answer not in roster.skills:
        raise ValueError(f"{answer!r} is not a skill in the skill table.")
    return _for_skill(answer, "owner", roster, tagged, table)


def doers(row):
    """Decision 3's order for a skill: best, interim (when set), second, then Claude; once each."""
    return list(dict.fromkeys(a for a in (row.get("best"), row.get("interim"), row.get("second"), "claude") if a))


def checkers(row, first=None):
    """Decision 4's order: the skill's second agent, then Claude, then ChatGPT (`first` before them: an override's own
    pick, C13); once each."""
    return list(dict.fromkeys(a for a in (first, row.get("second"), "claude", "chatgpt") if a))


def stand_in_reason(agent, why):
    return f"{STAND_IN}{agent}: {why}"


def stand_in_of(route_reason):
    """(the agent stood in for, why) from a route_reason, or None when the doer was not a stand-in."""
    text = route_reason or ""
    if not text.startswith(STAND_IN) or ": " not in text:
        return None
    agent, why = text[len(STAND_IN):].split(": ", 1)
    return agent, why


def pick_checker(row, doer, table, *, stopped=None, first=None, fits=None):
    """(checker, None) by decision 4, or (None, why nobody can check): never the doer, an agent that stopped in this task
    (`stopped`: {agent: why}), Cursor, or Grok unless the skill table names it second (or it is `first`, an override's
    own pick); never an agent that isn't available, or that `fits` says can't take this check (Grok past its limit). The
    why is the first reason a candidate was passed over that is not "it is the doer"."""
    stopped = stopped or {}
    why = None
    for agent in checkers(row, first):
        if agent == doer or agent in NEVER_CHECKS:
            continue
        if agent == "grok" and row.get("second") != "grok" and agent != first:
            continue
        if agent in stopped:
            why = why or stopped[agent]
            continue
        found = table(agent)
        if not found.available:
            why = why or found.why
            continue
        if fits is not None:
            refused = fits(agent)
            if refused:
                why = why or refused
                continue
        return agent, None
    return None, why or f"only {availability.name_of(doer)} could"


def _checking(skill, row, doer, table, first=None):
    """(checker, check_state, check_note) for a doer by decision 4."""
    if skill == NEVER_CHECKED:
        return None, "not_needed", None
    checker, why = pick_checker(row, doer, table, first=first)
    if checker is not None:
        return checker, "pending", None
    return None, "unchecked", f"{NO_CHECKER} ({why})"


def _for_skill(skill, source, roster, tagged=False, table=None):
    if skill in roster.not_routed:
        return Decision("return", skill, source, reason="returned: skill not routed in version 2", code="not_routed")
    if skill == NEEDS_TAG and not tagged:  # rules v2.28, Jev: before any agent call; Jev's row already stands
        return Decision("return", skill, source, reason=NO_TAG_FOR_RECALL, code="needs_tag")
    table = table or _table(None, roster)
    row = roster.skills[skill]
    only = ONLY.get(skill)
    if only is not None:  # decision 3 (and the owner, 21 Oct): make_media and x_social_pulse are Grok's alone
        found = table(only)
        if not found.available:
            return Decision("return", skill, source, reason=f"returned: {skill} needs {availability.name_of(only)}: "
                            f"{found.why}", code="unavailable")
        agent, reason = only, "best"
    else:
        agent = next((a for a in doers(row) if table(a).available), None)
        if agent is None:  # never with Claude available (decision 2); kept for a caller that checked nothing
            return Decision("return", skill, source, reason="returned: no agent available for it", code="unavailable")
        best = row["best"]
        reason = "best" if agent == best else stand_in_reason(best, table(best).why)
    checker, state, note = _checking(skill, row, agent, table)
    return Decision("send", skill, source, agent, reason, checker, state, note)


def _for_override(jev, roster, agent, table=None):
    """The named agent does it, whatever the label. Jev's label only picks the checker: today's pick (the skill's second,
    or its best when the named agent is the second) when it is available, else decision 4's order (C13)."""
    table = table or _table(None, roster)
    skill = jev.get("label")
    if jev["status"] != "ok" or skill not in roster.skills:
        return Decision("send", agent=agent, reason="override", check_state="unchecked",
                        check_note="override with no usable label")
    row = roster.skills[skill]
    if skill in roster.not_routed and skill != NEVER_CHECKED:
        return Decision("send", skill, "jev", agent, "override", None, "unchecked", "skill not routed in version 2")
    first = row["best"] if agent == row.get("second") else row.get("second")
    checker, state, note = _checking(skill, row, agent, table, first=first)
    return Decision("send", skill, "jev", agent, "override", checker, state, note)


def now_for(skill, roster, available=None):
    """What happens to a task with this skill now (brief 24, decision 14), for status: {doer, checker, stand_in
    ({for, why}) or None, unchecked (why) or None, note ("done without Meta", "needs Grok Bot") or None, comes_back (why) or
    None}. Read with a tag (a recall task needs one; that is intake's to say, not availability's)."""
    table = _table(available, roster)
    found = {"doer": None, "checker": None, "stand_in": None, "unchecked": None, "note": None, "comes_back": None}
    decision = _for_skill(skill, "jev", roster, tagged=True, table=table)
    if decision.action == "return":
        only = ONLY.get(skill)
        found.update(comes_back=decision.reason.removeprefix("returned: "),
                     note=f"needs {availability.name_of(only)}" if only else None)
        return found
    stood = stand_in_of(decision.reason)
    found.update(doer=decision.agent, checker=decision.checker,
                 stand_in={"for": stood[0], "why": stood[1]} if stood else None,
                 unchecked=decision.check_note if decision.check_state == "unchecked" else None,
                 note=SOCIAL_NOTE.get(skill) if skill in SOCIAL_NOTE and decision.agent != "grok" else None)
    return found


def no_store_for_recall(mode):
    """The words a tagged recall task comes back with when its memory can't be had (rules v2.29): with `memory: off` in
    settings the router never started the store, so they say memory is off; with `auto` the start was tried."""
    return NO_STORE_FOR_RECALL_OFF if mode == "off" else NO_STORE_FOR_RECALL
