"""Build brief 33 (decisions 2-7): next-step chips. A chip is a suggested next move a click puts in the composer, never
sent and never run. The router's own move comes first, chosen by code from the task's row and state (Build from this,
decision 4); then the agent's own, read by code from the delivered result on its call row: a project task's `### Next`
lines of its `## Handoff` section, any other task's optional `## Next` (decision 5). At most 3, a chip whose words match
an earlier one's dropped. Computed when the JSON is made and never stored, as the rescue offers are. Which card shows
them (the newest delivered one of a project or a chat) is the page's (decision 2); the router fills them on every
delivered task. Pure but for the reads it is handed."""
import re

from router import checking, context, log, memory, presets, relay, split, state

# Decision 4 and 5: no Build from this and no `## Next` line on these skills.
NO_NEXT_SKILLS = ("quick_answer", "recall", "make_media")
# Decision 5: the stages whose result can be delivered as the task's result, by preset; a split's is its integration.
DELIVERING = {"research-build": ("build",), "redteam": ("revise",), "versus": ("build",)}
# Decision 2: delivered means `done` with one of these outcomes, and not a change still waiting, discarded or undone.
DELIVERED_OUTCOMES = ("passed", "fixed", "unchecked", "picked", "tie")
NOT_DELIVERED_CHANGES = ("waiting", "discarded", "undone")
MAX_CHIPS = 3
_SPACES = re.compile(r"\s+")


def _get(row, key):
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def asks_next(task, kind, role=None):
    """Whether a call's prompt carries `checking.NEXT_LINE` (decision 5): a call whose result can be delivered as the
    task's result, off a project, never on a piece. `kind`: do, fix, stage, reask (a stage's) or redo (a fallback's);
    `role` a stage's. A routed doer and its fix rounds on every skill but those three; a relay task's fix rounds; the
    delivering stages and their re-asks; a split's integration; a fallback's redo. Never a check, a review, an attack,
    a vote, a stage whose result goes on, collab's stages, a split's plan, or any call of a project task (its handoff's
    `### Next` is the source there)."""
    if _get(task, "project") or _get(task, "parent"):
        return False
    mode = _get(task, "mode") or "route"
    if kind in ("do", "fix"):
        return mode != "route" or _get(task, "skill") not in NO_NEXT_SKILLS
    if kind in ("stage", "reask"):
        if mode == "split":
            return role == split.INTEGRATE_ROLE
        return role in DELIVERING.get(_get(task, "preset"), ())
    # a fallback's redo, but not collab's: its redo is followed by its edit stage, whose result is the one delivered
    return kind == "redo" and not (mode == "relay" and _get(task, "preset") == "collab")


def delivered(row, calls=()):
    """Decision 2: `done` with a delivered outcome, never a piece, never a change still waiting to land, discarded or
    undone (a landed change is delivered). Brief 34 (decision 12): never a run (it has no chips; its steps are pieces)."""
    if _get(row, "status") != "done" or log.is_piece(row) or _get(row, "mode") == "auto":
        return False
    if state.of(row, calls).outcome not in DELIVERED_OUTCOMES:
        return False
    found = log.project_files_of(row) if _get(row, "project_files") else None
    return not (found and found.get("state") in NOT_DELIVERED_CHANGES)


def delivered_text(row, calls, loaded=None):
    """The text a done task delivered, `## Handoff` and `## Next` sections and all: the check loop's furthest result,
    or a picked versus candidate's build (without its file blocks) when the presets are given; else the stored result."""
    if _get(row, "status") != "done":
        return None
    if (_get(row, "mode") or "route") == "relay" and relay.picked(row) in ("a", "b") and loaded is not None:
        preset = presets.for_task(row, loaded)[0]
        found = next((c for c in relay.candidates(log.fallback_view(calls), preset) if c.letter == relay.picked(row)),
                     None) if preset is not None else None
        build = relay.accepted(log.fallback_view(calls), found.stage) if found is not None else None
        if build is not None:
            return relay.without_file_blocks(build["text"])
    step = checking.ending_of(row, calls) if calls else None
    return step.result if step is not None and step.result is not None else _get(row, "result")


def same_words(a, b):
    """Decision 3: two chips' words match ignoring case, spacing and end punctuation."""
    return _norm(a) == _norm(b)


def _norm(words):
    return _SPACES.sub(" ", (words or "").strip()).rstrip(".!?;:,").strip().lower()


def agent_lines(row, calls, loaded=None):
    """The agent's own moves (decisions 3 and 5): a project task's `### Next` lines of its `## Handoff` section, any
    other task's `## Next` lines, each read with the same rules (list marks, @ and / dropped, 3 lines, 400 characters)."""
    text = delivered_text(row, calls, loaded) or ""
    if log.project_of(row):
        section = context.split_handoff(text)[1]
        if section is None:
            return []
        raw = context.handoff_parts(section).get("next") or []
        return checking.split_next("## Next\n" + "\n".join(raw))[1]
    return checking.split_next(text)[1]


def chips(conn, row, calls=None, loaded=None, moved=()):
    """The chips of one task (decisions 3, 4 and 7): [] unless delivered; Build from this first (a delivered result
    with text, but not on a quick answer, a recall, a media task or a forgotten task), then the agent's lines, at most 3,
    a chip whose words match an earlier one's dropped. Each chip: `kind`, `words`, `fill` (team, project, chat, text,
    from, idea) and `later` (an agent chip on a project card; `moved` the words already moved to the project's Ideas
    list from this card, which are not offered again)."""
    calls = log.calls_for(conn, row["task_id"]) if calls is None else calls
    if _get(row, "mode") == "suggest":  # brief 33.4 (decision 10): its result is the ideas; no card, no chips
        return []
    from router import plan  # plan imports teams, which reads this module's neighbours; kept local
    one = plan.one_step_view(row, calls) if plan.is_plan(row) else None
    if one is not None:  # brief 33.1 (decision 6): a One step card offers Build it
        return [plan.build_it_chip(row, one)]
    if not delivered(row, calls):
        return []
    project, chat = log.project_of(row), log.chat_of(row)
    forgotten = bool(memory.forgotten(row))
    found = []
    text = checking.without_next(context.split_handoff(_get(row, "result") or "")[0] or "")
    offered = text.strip() and _get(row, "skill") not in NO_NEXT_SKILLS and not forgotten
    from_this = True
    if project:  # brief 33.1 (decision 18): Build step k first (and no Build from this), else Plan from this first
        routers, from_this = plan.moves(conn, row)
        found += [m for m in routers if m["kind"] in ("build_step", "plan_project") or offered]  # 33.4 (decision 9)
    if offered and from_this:
        found.append({"kind": "build_from", "words": f"Build from #{row['n']}", "later": False,
                      "fill": _fill(project, chat, "", row["task_id"])})
    for line in agent_lines(row, calls, loaded):
        if any(same_words(line, m) for m in moved):
            continue
        source = None if project or forgotten else row["task_id"]  # decision 7
        found.append({"kind": "agent", "words": line, "later": bool(project),
                      "fill": _fill(project, chat, line, source)})
    kept = []
    for chip in found:
        if not any(same_words(chip["words"], k["words"]) for k in kept):
            kept.append(chip)
    return kept[:MAX_CHIPS]


def _fill(project, chat, text, source):
    return {"team": "route", "project": project, "chat": None if project else chat, "text": text, "from": source,
            "idea": None, "step": None}  # brief 33.1: a plan's moves fill a Step pill
