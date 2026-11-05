"""Build brief 29 (rules 2.41, Router for the interface; decisions 3 and 17), B7: the JSON a page reads. Every task
carries `no_split` (the planner's one line, read from the rows, never the result text) and a piece `piece_of` (its split,
its place and its team). `sr show <split> --json` gives each piece its team, the planner's team, who chose it and why,
its chain as filled now, the pick it may need, its calls by the count, the approval's refusal and, on a project split,
its part of the change; the split its `estimate` and its `menu`. Fake agents, a fake Jev; every value here is fake."""
import json

import pytest

from router import __main__ as cli
from router import jsonview, log
from tests.fixtures import json_shapes
from tests.helpers import teamed
from tests.test_relay import ROSTER
from tests.test_split_approve import JOIN, P1, P2, Jev, _split, _split_row
from tests.test_split_pieces import World, _pieces
from tests.test_versus_run import A_TEXT, B_TEXT, REVIEW_OF_A, REVIEW_OF_B

SEND = tuple(cli.SENDERS)


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def show(conn, row):
    return jsonview.show_view(conn, row, live=ROSTER.live, loaded=cli._presets_quietly(), roster=ROSTER,
                              send_paths=SEND)


def test_a_waiting_plans_pieces_carry_their_teams_count_and_refusal(conn):
    _split(conn, claude=(teamed(f"## Pieces\n1. {P1}\n2. {P2}\n\n## Join\n{JOIN}\n", team=["route", "vote"]),))
    row = _split_row(conn)
    cli.cmd_split_edit([row["task_id"]], piece="2", team="versus", conn=conn, config={}, roster=ROSTER, environ={},
                       settings_paths=[], label=Jev(), out=lambda line: None)
    doc = show(conn, log.get_task(conn, row["task_id"]))
    json_shapes.check(doc, json_shapes.SHOW)
    first, second = doc["pieces"]
    assert (first["team"], first["planner_team"], first["team_source"], first["chain"], first["needs_you"],
            first["calls"], first["max_calls"], first["refused"]) == ("route", "route", "planner", None, None, 2, 4, None)
    assert (second["team"], second["planner_team"], second["team_source"], second["needs_you"], second["calls"]) == (
        "versus", "vote", "owner", "pick", 4)
    assert second["chain"] == "Claude build → ChatGPT build → ChatGPT review → Claude review → your pick"
    assert second["team_why"] == "One writer and a checker are enough." and first["project_files"] is None
    assert doc["estimate"] == {"calls": 8, "max_calls": 12, "jev_labels": 2}
    assert [t["name"] for t in doc["menu"]] == ["route", "research-build", "collab", "versus", "redteam", "vote"]
    assert doc["no_split"] is None and doc["piece_of"] is None and doc["waiting_on"] == "split_plan"


def test_a_refused_piece_shows_its_refusal_before_approve(conn, monkeypatch):
    from router import settings
    monkeypatch.setattr(settings, "grok_prompt_limit", lambda: (300, "test"))
    _split(conn, claude=(teamed(f"## Pieces\n1. {P1}\n2. {P2}\n\n## Join\n{JOIN}\n", team=["route", "vote"]),))
    second = show(conn, _split_row(conn))["pieces"][1]
    assert second["refused"]["code"] == "too_long" and second["refused"]["reason"].startswith(
        "the task is too long for grok's vote")


def test_no_split_is_a_field_read_from_the_rows(conn):
    _split(conn, claude=("## No split\nEach part needs the one before it.",))
    row = _split_row(conn)
    doc = show(conn, row)
    assert doc["no_split"] == "Each part needs the one before it." and doc["pieces"] is None
    listed = jsonview.log_view(conn, [row], limit=10)["tasks"][0]
    assert listed["no_split"] == "Each part needs the one before it."


def test_a_pieces_own_json_names_its_split_its_place_and_its_team(conn):
    w = World(claude=("piece one", A_TEXT, REVIEW_OF_B), chatgpt=("PASS", B_TEXT, REVIEW_OF_A))
    w.split(conn, ["route", "versus"])
    route, versus = _pieces(conn)
    split_row = next(r for r in log.recent_tasks(conn, 50) if r["mode"] == "split")
    assert jsonview.task_view(conn, versus)["piece_of"] == {"split": split_row["task_id"], "n": split_row["n"],
                                                             "piece": 2, "team": "versus"}
    assert jsonview.task_view(conn, route)["piece_of"]["team"] == "route"
    doc = jsonview.show_view(conn, log.get_task(conn, versus["task_id"]), live=ROSTER.live,
                             loaded=cli._presets_quietly(), roster=ROSTER, send_paths=SEND)
    json_shapes.check(doc, json_shapes.SHOW)
    assert doc["candidates"] is not None and doc["waiting_on"] == "pick", "a versus piece's board, as sr relay versus"


def test_the_split_card_reads_each_pieces_state_and_team_after_the_approval(conn):
    w = World(claude=("piece one", A_TEXT, REVIEW_OF_B), chatgpt=("PASS", B_TEXT, REVIEW_OF_A))
    w.split(conn, ["route", "versus"])
    split_row = next(r for r in log.recent_tasks(conn, 50) if r["mode"] == "split")
    doc = show(conn, split_row)
    assert [(p["team"], p["piece_state"], p["why"]) for p in doc["pieces"]] == [
        ("route", "done", None), ("versus", "waiting", "waits for your pick")]
    assert doc["waiting_on"] == "piece"


def test_sr_show_names_a_team_pieces_split_and_its_label(conn):
    w = World(claude=("piece one", A_TEXT, REVIEW_OF_B), chatgpt=("PASS", B_TEXT, REVIEW_OF_A))
    w.split(conn, ["route", "versus"])
    _, versus = _pieces(conn)
    split_row = next(r for r in log.recent_tasks(conn, 50) if r["mode"] == "split")
    lines = []
    cli.cmd_show(conn=conn, words=[versus["task_id"]], roster=ROSTER, presets=cli._presets_quietly(), out=lines.append)
    out = "\n".join(lines)
    assert f"piece 2 of task #{split_row['n']}" in out
    assert "Jev: writing 0.93, not used: versus names its own agents (labeled at plan time" in out
    lines = []
    cli.cmd_show(conn=conn, words=[split_row["task_id"]], roster=ROSTER, presets=cli._presets_quietly(), out=lines.append)
    assert f"  2. #{versus['n']} waiting (waits for your pick) · versus · " in "\n".join(lines)
