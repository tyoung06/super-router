"""What intake refuses before any row (rules v2.25, v2.28, 2.40, 2.41; build brief 29, decision 7), in one module that
`sr route`, `sr relay` and the split's approval read alike. Moved here from router/__main__.py, which keeps the old names.

`piece_refusal` is the approval's check of one piece: the refusal its own command would give it now (`sr route`, or
`sr relay <team>`, with the split's project), the open-task rule aside, since the split itself is the project's open
task. It is pure: it writes nothing, makes no copy, calls neither Jev nor a probe, and reads availability as the plan's
preview does, so the card and `sr show` show a piece's refusal before Approve from the same function the approval runs.
A route piece the skill table would send back is shown as it is today ("comes back: …") and is not a refusal."""
from router import cursor_worker, filecalls, gitops, log, presets, projects, relay, routing, safety, settings, split, state, teams

# Brief 33.2 (decision 14, 33.1's D7 (i)): an open task's state in words, from `state.of`, for the open-task refusal
OPEN_WORDS = {"land": "waiting to land", "grok": "waiting on Grok", "pick": "waiting for your pick",
              "vote_pick": "waiting for your pick", "auto": "Auto stopped", "split_plan": "waiting for your approval",
              "needs_label": "waiting for your label", "answers": "waiting for your answers", "piece": "running", "probe": "running", "memory": "running"}


def open_words(conn, row):
    """What an open task is doing, in words: "waiting to land", "waiting for your approval" (a plan or a split's plan),
    "running", "waiting on Grok", "waiting for your pick", "Auto stopped"."""
    found = state.of(row, log.calls_for(conn, row["task_id"]))
    if found.waiting_on == "land" and (row["mode"] if "mode" in row.keys() else None) == "plan":
        return "waiting for your approval"
    return OPEN_WORDS.get(found.waiting_on, "running")


def project_refusal(conn, project, *, open_rule=True):
    """Rules v2.25, intake: why `--project <name>` cannot be taken, or None. Before any row: the name is in the
    registry (else the list), its HANDOFF.md can be read, and no task of the project is open (queued or sent).
    Brief 21: (reason_code, the reason). Brief 29: `open_rule=False` for a split's own pieces at its approval."""
    try:
        registry = projects.read_registry()
    except projects.ProjectError as e:
        return "project_unknown", f"{safety.one_line(e)}"
    if project not in registry:
        if not registry:
            return "project_unknown", f"no project {safety.one_line(project)}: the registry is empty (sr project add <name> <path>)"
        return "project_unknown", f"no project {safety.one_line(project)}. Projects: {', '.join(sorted(registry))} (sr project list)"
    try:
        projects.read_handoff(registry[project])
    except projects.ProjectError as e:
        return "handoff_unreadable", f"project {project}: {safety.one_line(e)}"
    open_row = log.open_task_for(conn, project) if open_rule else None
    if open_row is not None:  # brief 33.2 (decision 14): the state in words, never the row's status
        words = open_words(conn, open_row)
        tail = "Land the run so far or Discard run first" if words == "Auto stopped" else "Finish or cancel it first"
        return "project_busy", f"project {project} has task {open_row['n']} open ({words}). {tail}"
    return None


def build_slot_refusal(preset, project):
    """Brief 28 (decision 3): why a relay task's filled build slots can't run on this project, or None. Only Claude
    changes project files, so on a project whose folder is a git repository's top level (file mode's ground) a build or
    revise stage given to another agent is refused before any row."""
    if getattr(preset, "has_reviews", False):  # brief 29.1 (decision 9): versus's ChatGPT build is the router's to write
        return None
    agents = sorted({s.agent for s in preset.stages if s.role in filecalls.BUILD_ROLES and s.agent != "claude"})
    if not agents:
        return None
    folder = projects.folder_of(project)
    if folder is None or not gitops.inspect(folder).git:
        return None
    return (f"the build slot is {', '.join(agents)} on {project}, a project with git: only Claude changes project files "
            "(file mode); leave the build slot to Claude")


def project_presets(loaded):
    """The presets `--project` may run on (rules v2.25, Relay): a named checker after a chain that ends in one
    agent's build; never a check stage, review stages or a tally."""
    return [name for name, p in loaded.presets.items() if presets.takes_project(p)]  # brief 23: status reads the same


def grok_vote_refusal(preset, task):
    """Decision 13 with the owner's flag B: a Grok voter gets the task alone, so `grok_prompt_limit` is never applied
    to its send; instead the whole prompt it would get is measured here, before any row or call, and a task that
    would carry it past the limit is refused with both lengths. None when it fits (or no slot holds Grok)."""
    if not preset.tallies:
        return None
    most, _ = settings.grok_prompt_limit()
    for slot in preset.slots:
        for n in slot.stages:
            stage = preset.stage(n)
            if stage.agent != "grok":
                continue
            prompt = relay.prompt_for(stage.role, task, None, search=False, task_alone=True)
            if len(prompt) > most:
                return (f"the task is too long for grok's vote (slot {slot.name}): its prompt would be {len(prompt)} "
                        f"characters, the task alone {len(task)}; grok's limit is {most}. Shorten the task, or put "
                        f"another agent in slot {slot.name}.")
    return None


def cursor_length_refusal(preset, task):
    """Decision 2 (rules v2.28, Cursor): the prompt is the command's one argument, so a task whose Cursor prompt would
    pass cursor_worker.PROMPT_LIMIT characters is refused at intake with both lengths, before any row (as a Grok vote
    is measured). Measured on the task-alone build prompt with the opener; a review prompt, which carries the other
    candidate too, is guarded again by the worker at send time. None when it fits, or when no slot holds Cursor."""
    for slot in preset.slots:
        if slot.agent != "cursor":
            continue
        for n in slot.stages:
            stage = preset.stage(n)
            if getattr(stage, "input", None) != "task":
                continue
            prompt = cursor_worker.wrap(relay.prompt_for(stage.role, task, None, search=False, task_alone=True))
            if len(prompt) > cursor_worker.PROMPT_LIMIT:
                return (f"the task is too long for cursor (slot {slot.name}): its prompt would be {len(prompt)} characters, "
                        f"the task alone {len(task)}; cursor's limit is {cursor_worker.PROMPT_LIMIT}. Shorten the task, or "
                        f"put another agent in slot {slot.name}.")
    return None


# ---------- a piece's slots (brief 29.1, decision 12) ----------

def piece_slots_refusal(piece, *, project, conn, roster, loaded, available, send_paths):
    """(reason_code, reason) when the owner's slots on this piece can't run, else None: the check `sr relay <team>
    --<slot> <agent>` makes (presets.slot_refusals, then the filled preset's problems), then the piece's project rules (no
    Cursor on a project piece; on a project with git, the build slots stay Claude's). Pure, as piece_refusal is."""
    slots = piece.get("slots") or {}
    if not slots:
        return None
    team = split.team_of(piece)
    if team == teams.ROUTE or loaded is None or team not in loaded.presets:
        return "slot_refused", f"slots go on a preset's piece, not on {team}"
    table = routing._table(available, roster)
    filled, refused = presets.slot_refusals(loaded.presets[team], list(slots.items()), roster, table)
    if not refused:
        refused = presets.problems(filled.name, presets.as_entry(filled), roster, send_paths, relay.CONTRACTS,
                                   roles=relay.ROLES, verdicts=relay.VERDICTS)
    if refused:
        return "slot_refused", refused[0].rstrip(".")
    if project is None:
        return None
    held = presets.project_held(filled)  # brief 32 (decision 13): Cursor only in redteam's attack slots on a project
    if held:
        return "slot_refused", f"cursor in slot {', '.join(held)} on a project piece is refused (rules v2.28, Cursor)"
    found = build_slot_refusal(presets.project_shape(filled), project)
    return ("slot_refused", found) if found else None


# ---------- the split's approval, one piece (brief 29, decision 7) ----------

def piece_flags(piece):
    """A piece's owner-set slots as `--<slot> <agent>` flags would give them: [(slot, agent)]."""
    return list((piece.get("slots") or {}).items())


def piece_refusal(piece, *, project, conn, roster, loaded, available, send_paths):
    """(reason_code, reason) when this piece's own command would refuse it now, else None. `piece` is the stored plan's
    entry (its text and team as they stand); `project` the split's; `available` the preview's availability (what runs
    nothing). Each check is the one `sr route` or `sr relay <team>` makes at intake, in its order, the open-task rule
    aside."""
    text = split.text_of(piece)
    why = split.piece_problem(text)
    if why:
        return "bad_task", f"its text {why}"
    team = split.team_of(piece)
    table = routing._table(available, roster)
    if team == teams.ROUTE:
        return project_refusal(conn, project, open_rule=False) if project is not None else None
    menu = teams.menu(loaded, roster, table, project=project is not None, send_paths=send_paths)
    problem = teams.team_problem(team, menu)
    if problem:
        known = any(t["name"] == team for t in menu)
        return ("slot_refused" if known else "bad_preset"), problem
    found = piece_slots_refusal(piece, project=project, conn=conn, roster=roster, loaded=loaded, available=available,
                                send_paths=send_paths)  # brief 29.1 (decision 12): the owner's slots, as relay checks them
    if found:
        return found
    filled, _ = teams.filled(loaded.presets[team], roster, table, send_paths=send_paths, flags=piece_flags(piece))
    refused = grok_vote_refusal(filled, text) or cursor_length_refusal(filled, text)
    if refused:
        return "too_long", refused
    if project is None:
        return None
    held = presets.project_held(filled)  # brief 32 (decision 13)
    if held:
        return "tag_refused", (f"--project with cursor in slot {', '.join(held)} is refused: a Cursor slot on a --project "
                               "task (rules v2.28, Cursor)")
    found = project_refusal(conn, project, open_rule=False)
    if found:
        return found
    refused = build_slot_refusal(filled, project)
    return ("slot_refused", refused) if refused else None
