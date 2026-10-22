"""Brief 15 addendum, phase D2: every prompt the router builds, per call kind and agent, with the probe gate shut
(Claude's search off), recorded as plain data. `tests/fixtures/prompts_v9.json` is this run on `main` at a260d48
(before search on every call). tests/test_search_every_call.py compares: a prompt sent with search off now is byte
for byte the prompt main sent; a prompt sent with search on is main's prompt plus the search line.
Not a test file itself. Every value here is fake."""
import dataclasses

from router import __main__ as cli
from router import checking, log, relay, split
from tests.helpers import ALL_AGENTS

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


def _split_prompts(conn, ready=SHUT):
    found = {}
    log.add_task(conn, "sr-split", TASK, "cli", {"status": "not_asked", "tokens": 0}, mode="split")
    plan = split.new_plan(["Write line one.", "Write line two."], "One after the other.", ["sr-p1", "sr-p2"])
    plan["inputs"] = [{"text": "Write line one.", "result": "Line one."}, {"text": "Write line two.", "result": None}]
    log.set_split_plan(conn, "sr-split", plan)
    row = log.get_task(conn, "sr-split")
    for stage in split.PRESET.stages:
        step = relay.StageStep("stage", row["task_id"], stage.n, stage, prior=None, agent=stage.agent)
        prompt, kind, web_search, searching = cli._stage_call(row, step, ready)
        found[f"split/{stage.n}-{stage.role}"] = {"agent": stage.agent, "prompt": prompt, "web_search": web_search,
                                                  "searching": searching}
    return found


def snapshot(loaded, ready=SHUT):
    """Every prompt; `ready` is the probe gate (shut by default, as the fixture was made). `searching` is recorded
    only on this branch (the fixture from main has no such key)."""
    conn = log.init_db(":memory:")
    try:
        return {**_routed_prompts(conn, ready), **_stage_prompts(conn, loaded, ready), **_split_prompts(conn, ready)}
    finally:
        conn.close()
