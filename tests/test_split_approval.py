"""Build brief 29 (rules 2.41, Split), A3: the approval's facts and its per-piece intake (decision 7), and status's
`split` (decision 2). The approval screen shows each piece's team, the planner's why, where it goes, Jev's label and
the pick it will need, then the join, the project line, the router's call count and Jev's labels apart. Before any row
each piece passes the intake its own command would apply (router/intake.py: one pure function the card and `sr show`
read too), the open-task rule aside; one that fails refuses the approval, naming the piece and the reason. Fake agents
and a fake Jev only; every value here is fake."""
import json

import pytest

from router import __main__ as cli
from router import availability, intake, log, presets, projects, relay, settings, split, splitview, teams
from tests.helpers import shipped_roster, teamed
from tests.test_split_approve import JOIN, P1, P2, TASK, WRITING, Ask, Jev, _go, _split, _split_row
from tests.test_relay import ROSTER

SEND = tuple(cli.SENDERS)
LOADED = presets.load_presets(shipped_roster(), SEND, relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
QUICK = {"status": "ok", "label": "quick_answer", "confidence": 0.9, "needs_split": 0.1, "tokens": 300}


@pytest.fixture
def conn(monkeypatch, tmp_path):
    monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "config" / "projects.json")  # never the worktree's own
    c = log.init_db(":memory:")
    yield c
    c.close()


def _piece(text=P1, team="route", label=None, choice=None, planner_team=None):
    return {"id": "sr-p", "planner_text": text, "edited_text": None, "label": label, "choice": choice,
            "skipped": False, "planner_team": planner_team or team, "team": team,
            "team_source": "owner" if planner_team and planner_team != team else "planner", "team_why": "a reason"}


def _refusal(piece, conn, project=None, table=None):
    return intake.piece_refusal(piece, project=project, conn=conn, roster=ROSTER, loaded=LOADED, available=table,
                                send_paths=SEND)


def without(*names):
    def table(name):
        return availability.Availability(False, f"{name} isn't set up", "not_configured") if name in names else \
            availability.Availability(True)
    return table


# ---------- the one pure check (decision 7) ----------

def test_a_route_piece_and_a_ready_team_piece_pass(conn):
    assert _refusal(_piece(), conn) is None
    for team in ("research-build", "collab", "versus", "redteam", "vote"):
        assert _refusal(_piece(team=team), conn) is None, team


def test_a_team_that_cant_run_now_refuses_with_its_why(conn):
    found = _refusal(_piece(team="vote"), conn, table=without("grok"))
    assert found[0] == "slot_refused" and found[1].startswith("vote can't run now: slot c")


def test_a_team_the_menu_doesnt_have_refuses(conn):
    assert _refusal(_piece(team="debate"), conn) == (
        "bad_preset", "debate is not a team a piece of this split can take now (route, research-build, collab, versus, "
                      "redteam, vote)")


def test_a_piece_text_that_breaks_the_rules_refuses(conn):
    assert _refusal(_piece(text="@grok " + P1), conn) == (
        "bad_task", "its text starts with @ or /; a piece takes no override prefix and can't start with /")


def test_a_vote_piece_too_long_for_groks_vote_refuses_as_relay_would(conn, monkeypatch):
    monkeypatch.setattr(settings, "grok_prompt_limit", lambda: (300, "test"))
    found = _refusal(_piece(team="vote"), conn)
    assert found[0] == "too_long" and found[1].startswith("the task is too long for grok's vote (slot c)")
    assert _refusal(_piece(team="versus"), conn) is None


def test_on_a_project_a_team_off_the_projects_menu_refuses(conn, tmp_path, monkeypatch):
    folder = tmp_path / "garden-notes"
    folder.mkdir()
    (folder / "HANDOFF.md").write_text("# Garden notes\n")
    projects.add("garden-notes", folder)
    assert _refusal(_piece(team="versus"), conn, project="garden-notes") == (
        "bad_preset", "versus is not a team a piece of this split can take now (route, research-build, collab, redteam, "
        "vote)")  # brief 29.1 (decision 11): collab and vote pieces on a project
    assert _refusal(_piece(team="redteam"), conn, project="garden-notes") is None


def test_on_a_project_the_open_task_rule_is_aside_for_the_splits_own_pieces(conn, tmp_path):
    folder = tmp_path / "garden-notes"
    folder.mkdir()
    (folder / "HANDOFF.md").write_text("# Garden notes\n")
    projects.add("garden-notes", folder)
    log.add_task(conn, "sr-open", "busy", "cli", {"status": "ok", "label": "writing", "confidence": 0.9, "tokens": 0},
                 project="garden-notes")  # an open task on the project
    assert intake.project_refusal(conn, "garden-notes")[0] == "project_busy"
    assert _refusal(_piece(), conn, project="garden-notes") is None
    assert _refusal(_piece(team="research-build"), conn, project="garden-notes") is None


def test_on_a_project_that_left_the_registry_a_piece_refuses(conn):
    assert _refusal(_piece(), conn, project="gone-away")[0] == "project_unknown"


def test_the_check_writes_nothing_and_calls_neither_jev_nor_a_probe(conn, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no call")
    monkeypatch.setattr(cli.jev, "label", boom)
    monkeypatch.setattr(cli.probes, "claude_gate", boom)
    monkeypatch.setattr(cli.probes, "files_gate", boom)
    monkeypatch.setattr(cli.copies, "make", boom)
    before = conn.total_changes
    for team in ("route", "research-build", "versus", "vote"):
        _refusal(_piece(team=team, label=WRITING), conn)
    assert conn.total_changes == before


# ---------- the facts per piece and the count ----------

def test_a_route_pieces_facts(conn):
    view = splitview.piece_view(_piece(label=WRITING), project=None, conn=conn, roster=ROSTER, loaded=LOADED,
                                available=None, send_paths=SEND)
    assert view == {"team": "route", "planner_team": "route", "team_source": "planner", "team_why": "a reason",
                    "chain": None, "where": "writing · claude / chatgpt", "needs_you": None, "calls": 2, "max_calls": 4,
                    "jev_words": "Jev: writing 0.93", "refused": None}


def test_a_versus_piece_the_owner_changed_from_vote(conn):
    view = splitview.piece_view(_piece(team="versus", planner_team="vote", label=QUICK), project=None, conn=conn,
                                roster=ROSTER, loaded=LOADED, available=None, send_paths=SEND)
    assert (view["team"], view["planner_team"], view["team_source"], view["needs_you"], view["calls"],
            view["max_calls"]) == ("versus", "vote", "owner", "pick", 4, 4)
    assert view["chain"] == "Claude build → ChatGPT build → ChatGPT review → Claude review → your pick"
    assert view["jev_words"] == "Jev: quick_answer 0.90, not used: versus names its own agents"


def test_a_tied_vote_needs_a_pick_and_the_words_say_so():
    assert splitview.PICK_WORDS == {"pick": "needs your pick", "tie": "a tie needs your pick"}


def test_the_estimate_adds_each_teams_count_and_the_join(conn):
    plan = split.new_plan([P1, P2, "Find this year's heat pump install costs."], JOIN, ["sr-a", "sr-b", "sr-c"],
                          teams=[("route", "w"), ("versus", "p"), ("research-build", "r")])
    plan["pieces"][0]["label"] = WRITING
    plan["jev_labels"] = 3
    views = [splitview.piece_view(p, project=None, conn=conn, roster=ROSTER, loaded=LOADED, available=None,
                                  send_paths=SEND) for p in plan["pieces"]]
    assert splitview.estimate(plan, views, roster=ROSTER, available=None) == {"calls": 11, "max_calls": 17,
                                                                             "jev_labels": 3}


def test_without_chatgpt_the_joins_check_counts_nothing(conn):
    plan = split.new_plan([P1, P2], JOIN, ["sr-a", "sr-b"])
    for p in plan["pieces"]:
        p["label"] = WRITING
    views = [splitview.piece_view(p, project=None, conn=conn, roster=ROSTER, loaded=LOADED, available=without("chatgpt"),
                                  send_paths=SEND) for p in plan["pieces"]]
    found = splitview.estimate(plan, views, roster=ROSTER, available=without("chatgpt"))
    # each route piece is checked by another agent (Claude does, ChatGPT can't: Grok checks writing? no, unchecked)
    assert found["calls"] == sum(v["calls"] for v in views) + 1


# ---------- the screen and the approval ----------

def test_the_screen_marks_a_changed_team_and_a_pick(conn):
    plan_text = teamed(f"## Pieces\n1. {P1}\n2. {P2}\n\n## Join\n{JOIN}\n", team=["route", "versus"])
    code, out, *_ = _split(conn, claude=(plan_text,))
    assert "2. " + P2 + "\n   team: versus → Claude build → ChatGPT build → ChatGPT review → Claude review → your pick · " \
                        "needs your pick" in out
    assert "   Jev: writing 0.93, not used: versus names its own agents" in out
    assert "About 8 agent calls from here, up to 12 with fix rounds." in out  # route 2 (4) + versus 4 + join 2 (4)


def test_a_refused_piece_refuses_the_approval_and_makes_no_row(conn, monkeypatch):
    monkeypatch.setattr(settings, "grok_prompt_limit", lambda: (300, "test"))
    plan_text = teamed(f"## Pieces\n1. {P1}\n2. {P2}\n\n## Join\n{JOIN}\n", team=["route", "vote"])
    code, out, *_ = _split(conn, claude=(plan_text,))
    assert "   refused: the task is too long for grok's vote (slot c)" in out  # shown before the yes
    row = _split_row(conn)
    code, out, *_ = _go(conn, [str(row["n"])], ask=Ask("y"))
    assert code == 2 and "Refused: piece 2 can't run: the task is too long for grok's vote (slot c)" in out
    assert log.pieces_of(conn, row["task_id"]) == [] and _split_row(conn)["check_note"] == "awaiting approval"


def test_a_route_piece_that_would_come_back_does_not_refuse_the_approval(conn):
    jev = Jev({P2: {"status": "ok", "label": "computer_use", "confidence": 0.9, "tokens": 5}})
    code, out, *_ = _split(conn, jev=jev, ask=Ask("y"))
    pieces = log.pieces_of(conn, _split_row(conn)["task_id"])
    assert len(pieces) == 2 and "refused:" not in out


def test_only_a_route_piece_under_the_floor_asks_for_its_skill(conn):
    low = {"status": "below_floor", "label": "planning", "confidence": 0.55, "needs_split": 0.2, "tokens": 650}
    plan_text = teamed(f"## Pieces\n1. {P1}\n2. {P2}\n\n## Join\n{JOIN}\n", team=["route", "versus"])
    code, out, *_ = _split(conn, claude=(plan_text,), jev=Jev({P1: low, P2: low}))
    row = _split_row(conn)
    code, out, *_ = _go(conn, [str(row["n"]), ], ask=None)
    assert "your skill (Jev was unsure)" in out
    lines = []
    code = cli.cmd_split_go([str(row["n"])], answer="y", skills=["2=writing"], conn=conn, config={}, roster=ROSTER,
                            environ={}, settings_paths=[], label=Jev(), ask=None, post=None, worker=None,
                            out=lines.append)
    assert code == 2 and ("piece 2 runs as versus, which names its own agents; --skill is for a route piece"
                          in "\n".join(lines))
    lines = []
    code = cli.cmd_split_go([str(row["n"])], answer="y", conn=conn, config={}, roster=ROSTER, environ={},
                            settings_paths=[], label=Jev(), ask=None, post=None, worker=None, out=lines.append)
    assert code == 2 and "Jev was unsure: piece 1 (" in "\n".join(lines) and "piece 2" not in "\n".join(lines)


def test_each_jev_label_counts_on_the_plan(conn):
    code, out, worker, chat, jev, _ = _split(conn)
    plan = log.split_plan_of(_split_row(conn))
    assert plan["jev_labels"] == len(jev.calls) == 2


# ---------- status's split (decision 2) ----------

def test_status_split_reads_the_same_readiness_as_intake(monkeypatch):
    claude_off = availability.Availability(False, "Claude is signed out: claude auth login", "signed_out")
    assert teams.split_ready(claude_off) == (False, "Claude is signed out: claude auth login")
    lines = []
    code = cli.cmd_split(TASK, conn=log.init_db(":memory:"), config={}, roster=ROSTER, environ={}, settings_paths=[],
                         label=Jev(), ask=None, post=None, worker=None,
                         available=lambda name: claude_off if name == "claude" else availability.Availability(True),
                         out=lines.append)
    assert code == 2 and "Refused: Claude is signed out: claude auth login." in "\n".join(lines)
