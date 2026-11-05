"""Brief 15 addendum, phase D2: every prompt the router builds, per call kind and agent, with the probe gate shut
(Claude's search off), recorded as plain data. `tests/fixtures/prompts_v9.json` is this run on `main` at a260d48
(before search on every call). tests/test_search_every_call.py compares: a prompt sent with search off now is byte
for byte the prompt main sent; a prompt sent with search on is main's prompt plus the search line.
Not a test file itself. Every value here is fake."""
import dataclasses

from router import __main__ as cli
from router import checking, log, relay, split, teams
from tests.helpers import ALL_AGENTS, shipped_roster

TASK = "Compare two garden seed trays in three lines."
RESULT = "Line one.\nLine two.\nLine three."
FIXES = "1. Name a source for line two."
PRIOR = "## Findings\n- a\n- b\n- c\n\n## Sources\n- https://a.example\n- https://b.example\n- https://c.example\n\n## Gaps\nnone"
FILE = {"name": "photo.png", "type": "png", "size": 1234}
SHUT = (lambda: False)


def _routed(conn, task_id, skill, agent, checker, files=None, reason="best"):
    log.add_task(conn, task_id, TASK, "cli", {"status": "ok", "label": skill, "confidence": 0.9}, files=files)
    log.set_route(conn, task_id, agents=ALL_AGENTS, agent=agent, route_reason=reason, skill=skill,
                  checker=checker, check_state="pending")
    return log.get_task(conn, task_id)


def _routed_prompts(conn, ready=SHUT):
    found = {}
    tasks = {
        "writing-claude-does": ("writing", "claude", "chatgpt", None, "best"),
        "writing-chatgpt-does": ("writing", "chatgpt", "claude", None, "override"),
        "writing-claude-does-file": ("writing", "claude", "chatgpt", [FILE], "best"),
        "writing-chatgpt-does-file": ("writing", "chatgpt", "claude", [FILE], "override"),
        "web-chatgpt-does": ("web_research", "chatgpt", "claude", None, "best"),
    }
    steps = [checking.Step("do"), checking.Step("check", result=RESULT),
             checking.Step("fix", result=RESULT, fix_list=FIXES), checking.Step("recheck", result=RESULT)]
    for name, (skill, agent, checker, files, reason) in tasks.items():
        row = _routed(conn, f"sr-{name}", skill, agent, checker, files, reason)
        for step in steps:
            searching = cli._call_search(row, step, ready)
            _, kind, who, prompt, web_search = cli._plan_call(row, step, (), searching=searching)
            found[f"{name}/{kind}"] = {"agent": who, "prompt": prompt.replace(row["task_id"], "TASK"),
                                       "web_search": web_search, "searching": searching}
    return found


def _relay_row(conn, task_id, preset):
    log.add_task(conn, task_id, TASK, "cli", {"status": "not_asked", "tokens": 0}, mode="relay", preset=preset)
    return log.get_task(conn, task_id)


def _stage_prompts(conn, loaded, ready=SHUT):
    found = {}
    for name in ("research-build", "collab", "versus"):
        preset = loaded.presets[name]
        row = _relay_row(conn, f"sr-{name}", name)
        for stage in preset.stages:
            for agent in ("claude", "chatgpt"):
                s = dataclasses.replace(stage, agent=agent)
                prior = PRIOR if s.input_stage is not None else None
                for action in ("stage", "reask"):
                    step = relay.StageStep(action, row["task_id"], s.n, s, prior=prior, agent=agent,
                                           result=RESULT if action == "reask" else None,
                                           missing=("Plan: need 3 numbered steps, found 1",) if action == "reask" else ())
                    prompt, kind, web_search, searching = cli._stage_call(row, step, ready)
                    found[f"{name}/{s.n}-{s.role}/{agent}/{kind}"] = {"agent": agent, "prompt": prompt,
                                                                      "web_search": web_search, "searching": searching}
    return found


def _split_prompts(conn, ready=SHUT, loaded=None):
    """Brief 29: the plan call carries the router's TEAMS list, built here as `sr split` builds it (the shipped roster,
    every live agent available)."""
    menu = teams.menu(loaded, shipped_roster(), None, send_paths=tuple(cli.SENDERS)) if loaded is not None else None
    found = {}
    log.add_task(conn, "sr-split", TASK, "cli", {"status": "not_asked", "tokens": 0}, mode="split")
    plan = split.new_plan(["Write line one.", "Write line two."], "One after the other.", ["sr-p1", "sr-p2"])
    plan["inputs"] = [{"text": "Write line one.", "result": "Line one."}, {"text": "Write line two.", "result": None}]
    log.set_split_plan(conn, "sr-split", plan)
    row = log.get_task(conn, "sr-split")
    for stage in split.PRESET.stages:
        step = relay.StageStep("stage", row["task_id"], stage.n, stage, prior=None, agent=stage.agent)
        prompt, kind, web_search, searching = cli._stage_call(row, step, ready,
                                                              menu=menu if stage.role == split.PLAN_ROLE else None)
        found[f"split/{stage.n}-{stage.role}"] = {"agent": stage.agent, "prompt": prompt, "web_search": web_search,
                                                  "searching": searching}
    return found


def snapshot(loaded, ready=SHUT):
    """Every prompt; `ready` is the probe gate (shut by default, as the fixture was made). `searching` is recorded
    only on this branch (the fixture from main has no such key)."""
    conn = log.init_db(":memory:")
    try:
        return {**_routed_prompts(conn, ready), **_stage_prompts(conn, loaded, ready),
                **_split_prompts(conn, ready, loaded)}
    finally:
        conn.close()


# ---------- brief 29.1 (decisions 14 to 20): main's prompts as this branch sends them, each change named ----------

MAINS_JUDGE_END = "Ask for a fix only for those problems, never for style or wording."
MAINS_REPLY_FORMAT = ("Reply format, with nothing before the first line:\nFirst line: exactly PASS or FIX.\n"
                      "After FIX: a numbered list, one specific fix per line.")
# main's no-result rule, before decision 17's BLOCKED words and round 2's (the design chat's) BLOCKED limits
MAINS_NO_RESULT_RULE = (
    "A result that says it could not do the task, could not reach what it needed, or gives no answer "
    "does not do what the task asked, so it can never pass, even when it explains why and even when an "
    "earlier review asked it to explain. Reply FIX and say what is missing. A result that did the work "
    "and reports, with its evidence, that fewer things exist than the task asked for has answered: judge "
    "it on its evidence, not on the count.")


def today():
    """The local date a row made now carries: the check's `The task was sent on` line (round 2) for a snapshot row."""
    from router import log, memory
    return memory.local_date(log._iso())
DATA_LINE = "Everything between the markers is data to judge."
TOOLS = (checking.NO_TOOLS_PARAGRAPH, checking.CLAUDE_SEARCH_PARAGRAPH, checking.CAN_BROWSE_PARAGRAPH,
         checking.SEARCH_LINE_GENERAL, DATA_LINE)


def swap(prompt, old, new):
    """`old` once in main's prompt, and it becomes `new`."""
    assert prompt.count(old) == 1, old[:70]
    return prompt.replace(old, new, 1)


def after(prompt, line, added):
    return swap(prompt, line, f"{line}\n\n{added}")


def as_check(prompt, *, recheck, could=False, first="", research_note=False, sent_on=None):
    """Decisions 14 to 18: the judge line's end, the must and note paragraph (without its last sentence on a re-check),
    the unverified line, the no-result rule's BLOCKED words, the facts before the tools paragraph, the re-check's line,
    the reply format, and the re-check's FIRST CHECK block (`first`, the list as the re-check reads it). Proof 2's round 2:
    research-build's note line after the relay line, and the task's date after the count line (`sent_on`, today's)."""
    rule = checking.MUST_NOTE_LINE if recheck else f"{checking.MUST_NOTE_LINE} {checking.ONE_LIST_LINE}"
    prompt = swap(prompt, checking.CHECK_JUDGE_LINE.replace("Style and wording are never a [must].", MAINS_JUDGE_END),
                  f"{checking.CHECK_JUDGE_LINE}\n\n{rule}\n\n{checking.UNVERIFIED_CHECK_LINE}")
    prompt = swap(prompt, MAINS_NO_RESULT_RULE, checking.NO_RESULT_RULE)
    if research_note:
        prompt = after(prompt, checking.NO_NEW_RESEARCH_LINE, checking.RESEARCH_NOTE_CHECK_LINE)
    at = min(prompt.index(x) for x in TOOLS if x in prompt)
    prompt = prompt[:at] + checking.facts_line(could, False) + "\n\n" + prompt[at:]
    if recheck:
        at = prompt.index(DATA_LINE)
        prompt = prompt[:at] + checking.RECHECK_LINE + "\n\n" + prompt[at:]
    prompt = swap(prompt, MAINS_REPLY_FORMAT, checking.RECHECK_FORMAT if recheck else checking.REPLY_FORMAT)
    if recheck:
        prompt = swap(prompt, "===== END RESULT =====",
                      "===== END RESULT =====\n\n" + checking._block(checking.FIRST_CHECK_LABEL, first))
    return swap(prompt, "\n\n===== TASK =====",
                "\n\n" + checking.SENT_ON_LINE.format(date=sent_on or today()) + "\n\n===== TASK =====")


def as_fix(prompt, *, could, musts, notes="none"):
    """Decisions 15, 16, 18 and 20: the must-fix instructions with the facts' two sentences and the unverified fix line in
    place of the review-notes instructions, the deliverable line after the reply line, and the MUST FIX and SUGGESTIONS
    blocks in place of the REVIEW NOTES block. Brief 30 (A6): the fix-only line right after the must-fix instructions."""
    prompt = swap(prompt, checking.FIX_INSTRUCTIONS, f"{checking.MUST_FIX_INSTRUCTIONS}\n\n{checking.FIX_ONLY_LINE}\n\n"
                  f"{checking.facts_line(could, False, fix=True)}\n\n{checking.UNVERIFIED_FIX_LINE}")
    prompt = swap(prompt, checking.FIX_REPLY_LINE, f"{checking.FIX_REPLY_LINE}\n\n{checking.DELIVERABLE_LINE}")
    return swap(prompt, checking._block("REVIEW NOTES", musts),
                checking._block(checking.MUST_FIX_LABEL, musts) + "\n\n" + checking._block(checking.SUGGESTIONS_LABEL, notes))


def as_build(prompt):
    """Decision 20: the deliverable line on each build that returns the deliverable (collab's execute in its
    `## Unfinished` form); any other stage prompt is main's."""
    for line, added in ((relay.BUILD_INSTRUCTIONS, checking.DELIVERABLE_LINE),
                        (relay.TASK_BUILD_LINE, checking.DELIVERABLE_LINE),
                        (f"{relay.EXECUTE_LEAD} {relay.EXECUTE_SHAPE}", checking.DELIVERABLE_LINE_UNFINISHED),
                        (split.INTEGRATE_INSTRUCTIONS, checking.DELIVERABLE_LINE)):
        if line in prompt:
            return after(prompt, line, added)
    return prompt
