"""The split's piece menu and its count (rules 2.41, Split; build brief 29, decisions 2, 4, 6 and 7). Pure: it reads
what it is handed (the loaded presets, the roster, an availability table) and runs nothing.

The menu: the teams a piece of a split may take now. Route's line is the router's own; every other team is a preset from
config/presets.json, with its description, its chain as it would be filled now (a slot whose default isn't available is
filled as intake fills it, or the team can't run now and says why) and its calls. One function, `menu`, feeds the
planner's prompt (the ready teams only, `menu_block`), status's `split.teams` and the edit's check (`team_problem`), so
no list of teams is typed anywhere else. On a project the menu holds only the teams `--project` already takes
(`presets.takes_project`): collab and versus on a project come with brief 29.1, and vote never takes one.

The count: the agent calls a team spends from the approval on, worked out from a preset's stages and checker, and for
route and the join from the check loop the code runs (`checking.FIRST_CHECK`, `checking.FIX_ROUND`); a check that can't
run now counts nothing. Contract re-asks and takeovers are not counted; Jev's labels are counted apart."""
from router import checking, presets, relay, routing, split

ROUTE = "route"
ROUTE_DESCRIPTION = "Jev labels the task; the skill table picks who does it and who checks it."
ROUTE_CHAIN = "Jev's label → the skill table's doer → its checker"
PLANNER, CHECKER = split.PLANNER, split.CHECKER  # rules 2.41, Split: Claude plans and joins; ChatGPT checks the whole
DESCRIPTION = ("Claude breaks the task into 2 to 4 pieces, each with its own team; you approve the plan; the pieces run "
               "one at a time; Claude joins the results and ChatGPT checks the whole.")
MENU_HEAD = ('TEAMS a piece may take (the router built this list from what can run now; "you" in a line is the person '
             'who asked):')


# ---------- the count (decision 7) ----------

def _loop(checked):
    """(calls, most) the check loop adds after a result: one check, then one fix round and its re-check; none when no
    check can run."""
    if not checked:
        return 0, 0
    return len(checking.FIRST_CHECK), len(checking.FIRST_CHECK) + len(checking.FIX_ROUND)


def preset_calls(preset, checked=True):
    """A preset's calls: one per stage, then its named checker's loop (a check stage, reviews or a tally add nothing)."""
    base = len(preset.stages)
    add, most = _loop(checked and bool(preset.checker))
    return base + add, base + most


def route_calls(check_state):
    """A routed piece's calls from its routing: the doer, then the check loop when a check is owed (`pending`); one call
    for a quick answer (`not_needed`) or with no checker (`unchecked`); none when it comes back (None)."""
    if check_state is None:
        return 0, 0
    add, most = _loop(check_state == "pending")
    return 1 + add, 1 + most


def route_piece_calls(label, roster, choice=None, available=None, tagged=False):
    """A route piece's calls from Jev's label (and the owner's skill when Jev was under the floor): the skill table's
    routing as it stands now (`tagged`: a project split's piece carries the project). A piece not labeled yet, or under
    the floor with no skill chosen, counts as a checked one."""
    if label is None:
        return route_calls("pending")
    decision = routing.decide(label, roster, answer=choice, can_ask=choice is None, available=available, tagged=tagged)
    if decision.action == "ask":
        return route_calls("pending")
    if decision.action == "return":
        return route_calls(None)
    return route_calls(decision.check_state)


def join_calls(checked=True):
    """The split's own calls after its pieces: Claude's integration, then ChatGPT's check loop when ChatGPT can check."""
    add, most = _loop(checked)
    return 1 + add, 1 + most


def total(pieces, join):
    """(calls, most) of the pieces and the join together."""
    return sum(p[0] for p in pieces) + join[0], sum(p[1] for p in pieces) + join[1]


def count_line(calls, most):
    word = "call" if calls == 1 else "calls"
    tail = f", up to {most} with fix rounds" if most > calls else ""
    return f"About {calls} agent {word} from here{tail}."


def jev_line(labels):
    return f"Jev: {labels} label{'' if labels == 1 else 's'} so far; an edited text adds one"


# ---------- the menu (decisions 4 and 6) ----------

def needs_you(preset):
    """`pick` on a preset with reviews (versus), `tie` on a tally (vote): the piece may wait for the owner's pick."""
    if preset is None:
        return None
    if preset.has_reviews:
        return "pick"
    return "tie" if preset.tallies else None


def route_entry():
    calls, most = route_calls("pending")
    return {"name": ROUTE, "description": ROUTE_DESCRIPTION, "chain": ROUTE_CHAIN, "ready": True, "why": None,
            "project": True, "calls": calls, "max_calls": most, "needs_you": None}


def filled(preset, roster, available, *, send_paths, flags=()):
    """(the preset as it would be filled now, why not): intake's own fill (presets.fill_unavailable); `flags` (brief 29.1,
    decision 12) are a piece's owner-set slots, never refilled."""
    found, _, why = presets.fill_unavailable(preset, list(flags), roster, available, send_paths=send_paths,
                                             contracts=relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
    return found, why


def piece_takes_project(preset):
    """Brief 29.1 (decision 11): a piece of a project split may take any preset but versus, since the split has one shared
    copy and two candidates would need two."""
    return not getattr(preset, "has_reviews", False)


def preset_entry(name, preset, roster, available, *, send_paths, project=False):
    found, why = filled(preset, roster, available, send_paths=send_paths)
    shown = found or preset
    if project:  # brief 29.1 (decision 13): a piece on a project runs in the preset's project shape, and counts it
        shown = presets.project_shape(shown)
    calls, most = preset_calls(shown)
    return {"name": name, "description": preset.description, "chain": presets.chain(shown), "ready": found is not None,
            "why": why, "project": piece_takes_project(preset), "calls": calls, "max_calls": most,
            "needs_you": needs_you(preset)}


def menu(loaded, roster, available, *, project=False, send_paths):
    """The teams a piece may take now, route first, then the presets in config/presets.json's order. `project`: only the
    teams a piece on a project may take."""
    table = routing._table(available, roster)  # a gate, a dict or nothing (the live flags), as routing reads it
    found = [route_entry()]
    for name, preset in (loaded.presets.items() if loaded is not None else ()):
        found.append(preset_entry(name, preset, roster, table, send_paths=send_paths, project=project))
    return [t for t in found if t["project"]] if project else found


def names(teams):
    """The names of the teams that can run now: the planner's choices."""
    return [t["name"] for t in teams if t["ready"]]


def team_problem(name, teams):
    """Why a piece of this split can't take `name` now, or None (the edit's check; the approval's too)."""
    found = next((t for t in teams if t["name"] == name), None)
    if found is None:
        return f"{name} is not a team a piece of this split can take now ({', '.join(t['name'] for t in teams)})"
    if not found["ready"]:
        return found["why"] or f"{name} can't run now"
    return None


def menu_block(teams):
    """The planner's TEAMS list: one line per team that can run now, with its description, its chain and its calls."""
    lines = [MENU_HEAD]
    for t in teams:
        if t["ready"]:
            calls = t["calls"]
            lines.append(f"- {t['name']}: {t['description']} Chain: {t['chain']}. About {calls} "
                         f"call{'' if calls == 1 else 's'}.")
    return "\n".join(lines)


# ---------- status's `split` (decision 2) ----------

def split_ready(claude):
    """(ready, why) from Claude's availability: a split needs Claude, who plans and joins (brief 24, decision 2). `sr split`'s
    intake and `sr status` both read it, so they can't disagree."""
    return (True, None) if claude.available else (False, claude.why)


def join_checker(roster, available):
    """(checker, check_state, unchecked) for the join as it stands now: ChatGPT, or nobody with the reason."""
    found = routing._table(available, roster)(CHECKER)
    if found.available:
        return CHECKER, "pending", None
    return None, "unchecked", f"{routing.NO_CHECKER} ({found.why})"


def split_chain(checker):
    words = f"{presets.CHAIN_NAMES[CHECKER]} check" if checker else "unchecked"
    planner = presets.CHAIN_NAMES[PLANNER]
    return f"{planner} plan → your approval → the pieces, one at a time → {planner} join → {words}"


def split_entry(loaded, roster, available, *, send_paths):
    """`sr status --json`'s `split`: whether it can run now and why not, its words, its chain with the checker as it
    stands, the piece menu."""
    table = routing._table(available, roster)
    ready, why = split_ready(table(PLANNER))
    checker, _, unchecked = join_checker(roster, table)
    return {"ready": ready, "why": why, "description": DESCRIPTION, "chain": split_chain(checker), "checker": checker,
            "unchecked": unchecked, "project": True, "max_pieces": split.MAX_PIECES,
            "teams": menu(loaded, roster, table, send_paths=send_paths)}
