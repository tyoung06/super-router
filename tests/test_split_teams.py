"""Build brief 29 (rules 2.41, Split), A1: the piece menu and the count (router/teams.py). The menu is built from
config/presets.json and the availability handed in, with route's line the router's own; status's `split.teams`, the
planner's prompt and the edit's check read it through one function. The count is worked out from each preset's stages
and checker, and from the check loop the code runs for route and the join, never from a typed table. Pure: no agent is
called. Every value here is fake."""
import dataclasses
import re
from pathlib import Path

import pytest

from router import __main__ as cli
from router import availability, checking, log, presets, relay, routing, status, teams
from tests.helpers import shipped_roster

ROSTER = shipped_roster()
SEND = tuple(cli.SENDERS)


def _loaded():
    return presets.load_presets(ROSTER, SEND, relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)


LOADED = _loaded()
YES = availability.Availability(True)


def everyone(name):
    return YES


def without(*names, why="it is off", code="not_live"):
    def table(name):
        return availability.Availability(False, f"{name} {why}", code) if name in names else YES
    return table


def _menu(table=everyone, project=False, loaded=LOADED):
    return teams.menu(loaded, ROSTER, table, project=project, send_paths=SEND)


# ---------- the menu ----------

def test_the_menu_is_route_then_every_preset_in_the_files_order():
    found = _menu()
    assert [t["name"] for t in found] == ["route", "research-build", "collab", "versus", "redteam", "vote"]
    assert [t["name"] for t in found][1:] == list(LOADED.presets)


def test_routes_line_is_the_routers_own():
    route = _menu()[0]
    assert route == {"name": "route", "description": "Jev labels the task; the skill table picks who does it and who "
                                                     "checks it.",
                     "chain": "Jev's label → the skill table's doer → its checker", "ready": True, "why": None,
                     "project": True, "calls": 2, "max_calls": 4, "needs_you": None}


def test_each_preset_brings_its_description_chain_calls_and_whether_it_needs_you():
    by = {t["name"]: t for t in _menu()}
    for name, preset in LOADED.presets.items():
        assert by[name]["description"] == preset.description
        assert by[name]["chain"] == presets.chain(preset)
        assert by[name]["ready"] is True and by[name]["why"] is None
        assert by[name]["project"] is teams.piece_takes_project(preset)  # brief 29.1 (decision 11): the split's own rule
    assert {n: (t["calls"], t["max_calls"]) for n, t in by.items()} == {
        "route": (2, 4), "research-build": (3, 5), "collab": (4, 4), "versus": (4, 4), "redteam": (5, 7),  # 32: 5 to 7
        "vote": (3, 3)}
    assert {n: t["needs_you"] for n, t in by.items()} == {
        "route": None, "research-build": None, "collab": None, "versus": "pick", "redteam": None, "vote": "tie"}


def test_a_team_that_cant_run_now_says_why_and_leaves_the_prompt():
    table = without("grok", why="isn't set up: no inbox repo in settings", code="not_configured")
    by = {t["name"]: t for t in _menu(table)}
    # research-build's research slot is filled by ChatGPT (the chain as filled now); vote can't put a third agent in c
    assert by["research-build"]["ready"] is True and by["research-build"]["chain"].startswith("ChatGPT research")
    assert by["vote"]["ready"] is False and by["vote"]["why"].startswith("vote can't run now: slot c")
    block = teams.menu_block(list(by.values()))
    assert "- vote:" not in block and "- research-build:" in block
    assert teams.names(list(by.values())) == ["route", "research-build", "collab", "versus", "redteam"]


def test_a_projects_menu_holds_only_the_teams_that_take_a_project():
    found = _menu(project=True)  # brief 29.1 (decisions 11 and 13): collab and vote too, never versus; collab's project shape
    assert [t["name"] for t in found] == ["route", "research-build", "collab", "redteam", "vote"]
    assert [t["name"] for t in found] == ["route", *[n for n, p in LOADED.presets.items() if teams.piece_takes_project(p)]]
    collab = next(t for t in found if t["name"] == "collab")
    assert (collab["calls"], collab["max_calls"], collab["chain"]) == (4, 6, "Claude plan → ChatGPT amend → Claude build → "
                                                                       "ChatGPT check")


def test_one_description_change_reaches_status_the_prompt_and_the_edit(monkeypatch):
    changed = dict(LOADED.presets)
    changed["collab"] = dataclasses.replace(changed["collab"], description="Two agents pair up on it, a new line.")
    loaded = presets.Presets(LOADED.version, changed, LOADED.problems)
    menu = teams.menu(loaded, ROSTER, everyone, project=False, send_paths=SEND)
    entry = teams.split_entry(loaded, ROSTER, everyone, send_paths=SEND)
    assert [t for t in entry["teams"] if t["name"] == "collab"][0]["description"] == "Two agents pair up on it, a new line."
    assert "- collab: Two agents pair up on it, a new line. Chain:" in teams.menu_block(menu)
    assert teams.team_problem("collab", menu) is None  # the edit reads the same list
    assert teams.team_problem("nonsense", menu) == "nonsense is not a team a piece of this split can take now " \
                                                  "(route, research-build, collab, versus, redteam, vote)"


def test_the_edit_refuses_a_team_that_cant_run_now_with_its_why():
    menu = _menu(without("grok", why="isn't set up", code="not_configured"))
    assert teams.team_problem("vote", menu).startswith("vote can't run now: slot c")
    assert teams.team_problem("versus", _menu(project=True)) == ("versus is not a team a piece of this split can take "
                                                                  "now (route, research-build, collab, redteam, vote)")


def test_the_menu_block_is_one_line_per_ready_team_with_its_calls():
    block = teams.menu_block(_menu())
    lines = block.splitlines()
    assert lines[0] == ('TEAMS a piece may take (the router built this list from what can run now; "you" in a line is '
                        'the person who asked):')
    assert lines[1] == ("- route: Jev labels the task; the skill table picks who does it and who checks it. Chain: "
                        "Jev's label → the skill table's doer → its checker. About 2 calls.")
    assert lines[2].startswith("- research-build: ") and lines[2].endswith(
        "Chain: Grok research → Claude build → ChatGPT check. About 3 calls.")
    assert len(lines) == 7


def test_no_team_list_is_typed_in_the_routers_code_but_routes_name():
    names = [n for n in LOADED.presets]
    source = (Path(teams.__file__)).read_text()
    for name in names:
        assert f'"{name}"' not in source and f"'{name}'" not in source, name


# ---------- the readiness status and intake share ----------

def test_split_is_ready_exactly_when_claude_is_available():
    assert teams.split_ready(YES) == (True, None)
    assert teams.split_ready(availability.Availability(False, "Claude is signed out: claude auth login", "signed_out")) == (
        False, "Claude is signed out: claude auth login")


def test_status_split_entry_holds_the_briefs_keys():
    entry = teams.split_entry(LOADED, ROSTER, everyone, send_paths=SEND)
    assert set(entry) == {"ready", "why", "description", "chain", "checker", "unchecked", "project", "max_pieces", "teams"}
    assert entry["ready"] is True and entry["why"] is None and entry["project"] is True and entry["max_pieces"] == 4
    assert entry["description"] == ("Claude breaks the task into 2 to 4 pieces, each with its own team; you approve the "
                                    "plan; the pieces run one at a time; Claude joins the results and ChatGPT checks "
                                    "the whole.")
    assert entry["chain"] == "Claude plan → your approval → the pieces, one at a time → Claude join → ChatGPT check"
    assert entry["checker"] == "chatgpt" and entry["unchecked"] is None
    assert [t["name"] for t in entry["teams"]] == ["route", "research-build", "collab", "versus", "redteam", "vote"]


def test_without_chatgpt_the_join_goes_unchecked_and_says_so():
    entry = teams.split_entry(LOADED, ROSTER, without("chatgpt", why="is signed out", code="signed_out"), send_paths=SEND)
    assert entry["checker"] is None and entry["unchecked"] == "no other agent available to check (chatgpt is signed out)"
    assert entry["chain"].endswith("→ Claude join → unchecked")


def test_without_claude_split_is_not_ready():
    entry = teams.split_entry(LOADED, ROSTER, without("claude", why="is signed out", code="signed_out"), send_paths=SEND)
    assert entry["ready"] is False and entry["why"] == "claude is signed out"


# ---------- the count (decision 7) ----------

def test_a_presets_count_comes_from_its_stages_and_checker():
    for name, preset in LOADED.presets.items():
        base = len(preset.stages) + (len(checking.FIRST_CHECK) if preset.checker else 0)
        most = base + (len(checking.FIX_ROUND) if preset.checker else 0)
        assert teams.preset_calls(preset) == (base, most), name


def test_a_check_that_cant_run_counts_nothing():
    preset = LOADED.presets["research-build"]
    assert teams.preset_calls(preset, checked=False) == (2, 2)
    assert teams.join_calls(checked=True) == (2, 4) and teams.join_calls(checked=False) == (1, 1)


@pytest.mark.parametrize("state,want", [("pending", (2, 4)), ("not_needed", (1, 1)), ("unchecked", (1, 1)),
                                        (None, (0, 0))])
def test_a_route_pieces_count_follows_its_check(state, want):
    assert teams.route_calls(state) == want


def test_a_route_piece_from_its_label():
    ok = {"status": "ok", "label": "writing", "confidence": 0.95, "tokens": 0}
    quick = {"status": "ok", "label": "quick_answer", "confidence": 0.95, "tokens": 0}
    low = {"status": "below_floor", "label": "writing", "confidence": 0.4, "tokens": 0}
    computer = {"status": "ok", "label": "computer_use", "confidence": 0.95, "tokens": 0}
    assert teams.route_piece_calls(ok, ROSTER) == (2, 4)
    assert teams.route_piece_calls(quick, ROSTER) == (1, 1)
    assert teams.route_piece_calls(low, ROSTER) == (2, 4)  # under the floor: counted as a checked piece (call 9)
    assert teams.route_piece_calls(low, ROSTER, choice="quick_answer") == (1, 1)
    assert teams.route_piece_calls(computer, ROSTER) == (0, 0)  # comes back: no agent call
    assert teams.route_piece_calls(None, ROSTER) == (2, 4)  # not labeled yet


def test_the_line_says_the_count_and_the_most():
    assert teams.count_line(11, 17) == "About 11 agent calls from here, up to 17 with fix rounds."
    assert teams.count_line(9, 9) == "About 9 agent calls from here."
    assert teams.count_line(1, 1) == "About 1 agent call from here."
    assert teams.jev_line(3) == "Jev: 3 labels so far; an edited text adds one"
    assert teams.jev_line(1) == "Jev: 1 label so far; an edited text adds one"


def test_the_screens_example_adds_up():
    """Frame 2: route 2 (up to 4) + versus 4 + research-build 3 (up to 5) + the join 2 (up to 4) = 11, up to 17."""
    pieces = [teams.route_calls("pending"), teams.preset_calls(LOADED.presets["versus"]),
              teams.preset_calls(LOADED.presets["research-build"])]
    assert teams.total(pieces, teams.join_calls(checked=True)) == (11, 17)


def test_the_check_loop_the_count_reads_is_the_one_next_step_walks():
    """The count's FIRST_CHECK and FIX_ROUND are the rounds checking.next_step asks for, in order."""
    conn = log.init_db(":memory:")
    log.add_task(conn, "sr-a", "t", "cli", {"status": "ok", "label": "writing", "confidence": 0.9, "tokens": 0})
    log.set_route(conn, "sr-a", agents=("claude", "chatgpt"), agent="claude", route_reason="best", skill="writing",
                  checker="chatgpt", check_state="pending")
    row = log.get_task(conn, "sr-a")
    walked = []
    log.add_call(conn, "sr-a", "sr-a", "do", "claude", status="done", text="r")
    for kind, call_id, verdict in (("check", "sr-a-c1", "FIX"), ("fix", "sr-a-f1", None), ("recheck", "sr-a-c2", "PASS")):
        step = checking.next_step(row, log.calls_for(conn, "sr-a"))
        walked.append(step.action)
        text = "FIX\n1. x" if verdict == "FIX" else "PASS" if verdict else "fixed"
        log.add_call(conn, call_id, "sr-a", kind, "chatgpt" if kind != "fix" else "claude", status="done", text=text,
                     verdict=verdict)
    assert checking.next_step(row, log.calls_for(conn, "sr-a")).action == "finish"
    assert tuple(walked) == checking.FIRST_CHECK + checking.FIX_ROUND
    conn.close()


# ---------- presets.chain moved from status (the menu and status read one) ----------

def test_status_chain_is_presets_chain():
    assert status.chain is presets.chain
    assert presets.chain(LOADED.presets["collab"]) == "Claude plan → ChatGPT amend → Claude build → ChatGPT edit (check)"
