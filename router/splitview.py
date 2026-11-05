"""The approval's facts about a split's plan (rules 2.41, Split; build brief 29, decisions 7 and 17), worked out once, in
code, for Terminal's approval screen and for `sr show --json` alike. Pure: it reads the stored plan, the piece rows, the
presets, the roster and the preview's availability (what runs nothing), and writes and calls nothing.

Per piece: its team (marked when the owner changed it), the planner's why, where it goes (a route piece: the skill
table's doer and checker from Jev's label, or the skill question when Jev was under the floor; another team: its chain as
filled now), Jev's label (on a team other than route, "not used"), whether it will need the owner's pick, its calls by
the count, and the refusal its own intake would give it now. For the plan: the call count from here (the pieces as their
teams stand, then the join), and Jev's labels apart."""
from router import availability, intake, log, routing, split, teams

PICK_WORDS = {"pick": "needs your pick", "tie": "a tie needs your pick"}


def confidence(value):
    return f"{value:.2f}" if isinstance(value, (int, float)) else "-"


def jev_words(label, team):
    """Jev's label for a piece: `Jev: writing 0.94`; on a team other than route, `…, not used: <team> names its own
    agents`; None before Jev labels it."""
    if not label:
        return None
    if label.get("status") in ("ok", "below_floor", "none_of_these"):
        words = f"Jev: {label.get('label') or 'none of these'} {confidence(label.get('confidence'))}"
    elif label.get("status") == "not_set_up":
        words = "Jev isn't set up"
    elif label.get("status") == "over_cap":
        words = "Jev: past this month's cap"
    else:
        words = "Jev couldn't label it"
    if team != teams.ROUTE:
        words += f", not used: {team} names its own agents"
    return words


def follow_up_words(decision):
    """Brief 29.1 (decision 24): a route piece of a project split that runs as a follow-up, in the plan card's words."""
    return f"follow-up: {availability.name_of(decision.agent)}, with memory"


def route_where(label, roster, choice=None, available=None, tagged=False):
    """Where the skill table sends a route piece now, in words: `writing · claude / chatgpt`, `your skill (Jev was
    unsure)`, or `comes back: <why>`. `tagged`: a project split's piece carries the project."""
    if label is None:
        return "Jev labels it first"
    decision = routing.decide(label, roster, answer=choice, can_ask=choice is None, available=available, tagged=tagged)
    if decision.action == "ask":
        return "your skill (Jev was unsure)"
    if decision.skill == routing.FOLLOW_UP and decision.action == "send":
        return follow_up_words(decision)
    if decision.action == "return":
        return "comes back: " + decision.reason.removeprefix("returned: ")
    if decision.check_state == "not_needed":
        check = "no check"
    elif decision.check_state == "pending":
        check = decision.checker
    else:
        check = f"unchecked ({decision.check_note})"
    return f"{decision.skill} · {decision.agent} / {check}"


def piece_view(piece, *, project, conn, roster, loaded, available, send_paths, menu=None):
    """The approval's facts for one stored piece (decision 7), as fields."""
    team = split.team_of(piece)
    menu = menu if menu is not None else teams.menu(loaded, roster, available, project=project is not None,
                                                    send_paths=send_paths)
    entry = next((t for t in menu if t["name"] == team), None)
    label, choice = piece.get("label"), piece.get("choice")
    if team == teams.ROUTE:
        calls = teams.route_piece_calls(label, roster, choice, available, tagged=project is not None)
        chain, needs = None, None
        where = route_where(label, roster, choice, available, tagged=project is not None)
    else:
        calls = (entry["calls"], entry["max_calls"]) if entry is not None else (0, 0)
        chain = entry["chain"] if entry is not None else None
        needs = entry["needs_you"] if entry is not None else None
        where = chain or "can't run now"
    refused = intake.piece_refusal(piece, project=project, conn=conn, roster=roster, loaded=loaded, available=available,
                                   send_paths=send_paths)
    planner_team = piece.get("planner_team") or teams.ROUTE
    return {"team": team, "planner_team": planner_team, "team_source": piece.get("team_source") or "planner",
            "team_why": piece.get("team_why"), "chain": chain, "where": where, "needs_you": needs,
            "calls": calls[0], "max_calls": calls[1], "jev_words": jev_words(label, team),
            "refused": {"code": refused[0], "reason": refused[1]} if refused else None}


def jev_labels(plan):
    """Jev's labels made for this plan so far: the count the plan keeps, or (a plan from before) its labels."""
    if isinstance(plan.get("jev_labels"), int):
        return plan["jev_labels"]
    return sum(1 for p in plan["pieces"] if p.get("label"))


def estimate(plan, views, *, roster, available):
    """The call count from here (decision 7): each piece as its team stands, then the join and its check as the checker
    stands now; Jev's labels apart."""
    checker, _, _ = teams.join_checker(roster, available)
    calls, most = teams.total([(v["calls"], v["max_calls"]) for v in views], teams.join_calls(checked=checker is not None))
    return {"calls": calls, "max_calls": most, "jev_labels": jev_labels(plan)}


def project_line(row):
    """The card's project line (decision 12): the one copy and the one land, or the handoff-only reason."""
    name = log.project_of(row)
    if not name:
        return None
    found = log.project_files_of(row) or {}
    if found.get("mode") == "on":
        return f"On {name} · one copy · you land once at the end"
    return f"On {name} · handoff only ({found.get('why') or 'no copy'})"


def screen(row, plan, *, conn, roster, loaded, available, send_paths, secrets, safe):
    """Terminal's approval screen (decision 7): each piece, the joining line, the project line, the count, Jev's labels.
    `safe(text)` makes a text safe to print."""
    project = log.project_of(row)
    menu = teams.menu(loaded, roster, available, project=project is not None, send_paths=send_paths)
    lines, views = [f"Task {row['n']} · split · plan", ""], []
    for k, piece in enumerate(plan["pieces"], 1):
        view = piece_view(piece, project=project, conn=conn, roster=roster, loaded=loaded, available=available,
                          send_paths=send_paths, menu=menu)
        views.append(view)
        changed = f" (you changed it from {view['planner_team']})" if view["team_source"] == "owner" else ""
        mark = f" · {PICK_WORDS[view['needs_you']]}" if view["needs_you"] else ""
        lines.append(f"{k}. {safe(split.text_of(piece))}")
        lines.append(f"   team: {view['team']}{changed} → {safe(view['where'])}{mark}")
        if view["team_why"]:
            lines.append(f"   why: {safe(view['team_why'])}")
        if view["jev_words"]:
            lines.append(f"   {view['jev_words']}")
        if view["refused"]:
            lines.append(f"   refused: {safe(view['refused']['reason'])}")
    found = estimate(plan, views, roster=roster, available=available)
    lines.append(f"Join: {safe(plan['join'])}")
    line = project_line(row)
    if line:
        lines.append(safe(line))
    lines += [teams.count_line(found["calls"], found["max_calls"]), teams.jev_line(found["jev_labels"]), ""]
    return lines, views
