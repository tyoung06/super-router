"""Build brief 29 (rules 2.41, Split, "The approval"; decision 8): `sr split --edit <n> --piece <k> [--team <team>]
[-- <text>]` changes one piece of a plan that waits, as Terminal's `e` does. A new text passes the piece rules, is
labeled again by Jev in the same command (its tokens on the split row) and keeps the planner's text beside it; a new team
must be on this split's menu now, and calls no Jev; going back to the planner's reads as unedited. The edit takes the
split's run. Refusals write nothing: wrong_state, bad_task, bad_preset, usage. Fake agents and a fake Jev; every value
here is fake."""
import json
import os

import pytest

from router import __main__ as cli
from router import log, runs, split
from tests.helpers import teamed
from tests.test_relay import CONFIG, ROSTER, Chat
from tests.test_split_approve import JOIN, P1, P2, WRITING, Ask, Jev, _split, _split_row

QUICK = {"status": "ok", "label": "quick_answer", "confidence": 0.95, "needs_split": 0.1, "tokens": 400}
EDIT = "Write a 100-word intro paragraph about adjustable garden seed trays, for a homeowner. No prices."


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def edit(conn, row, piece, *, team=None, text=None, jev=None):
    lines, jev = [], jev or Jev()
    code = cli.cmd_split_edit([str(row["n"])], piece=piece, team=team, text=text, conn=conn, config=CONFIG,
                              roster=ROSTER, environ={}, settings_paths=[], label=jev, out=lines.append)
    return code, "\n".join(lines), jev


def waiting(conn, plan=None):
    _split(conn, claude=(plan or teamed(f"## Pieces\n1. {P1}\n2. {P2}\n\n## Join\n{JOIN}\n", team=["route", "vote"]),))
    return _split_row(conn)


def snapshot(conn, row):
    found = log.get_task(conn, row["task_id"])
    return found["split_plan"], found["jev_tokens"], found["status"], found["check_note"]


# ---------- the edits ----------

def test_a_new_text_is_labeled_once_with_its_tokens_on_the_split_row_and_the_planners_text_kept(conn):
    row = waiting(conn)
    tokens = row["jev_tokens"]
    code, out, jev = edit(conn, row, "1", text=EDIT, jev=Jev({EDIT: QUICK}))
    assert code == 0, out
    plan = log.split_plan_of(log.get_task(conn, row["task_id"]))
    first = plan["pieces"][0]
    assert (first["planner_text"], first["edited_text"], first["label"]["label"]) == (P1, EDIT, "quick_answer")
    assert [c["task"] for c in jev.calls] == [EDIT] and jev.calls[0]["task_id"] == first["id"]
    assert log.get_task(conn, row["task_id"])["jev_tokens"] == tokens + 400
    assert plan["jev_labels"] == 3
    assert "Piece 1: its text changed, labeled again by Jev." in out and "Jev: 3 labels so far" in out


def test_a_new_team_calls_no_jev_and_reads_as_the_owners(conn):
    row = waiting(conn)
    code, out, jev = edit(conn, row, "2", team="versus")
    assert code == 0, out
    second = log.split_plan_of(log.get_task(conn, row["task_id"]))["pieces"][1]
    assert (second["planner_team"], second["team"], second["team_source"]) == ("vote", "versus", "owner")
    assert jev.calls == []
    assert "Piece 2: its team is versus (you changed it from vote)." in out
    assert "team: versus (you changed it from vote) → " in out and "needs your pick" in out


def test_both_at_once(conn):
    row = waiting(conn)
    code, out, jev = edit(conn, row, "1", team="redteam", text=EDIT)
    first = log.split_plan_of(log.get_task(conn, row["task_id"]))["pieces"][0]
    assert code == 0 and (first["edited_text"], first["team"], first["team_source"]) == (EDIT, "redteam", "owner")
    assert len(jev.calls) == 1


def test_going_back_to_the_planners_text_or_team_reads_unedited(conn):
    row = waiting(conn)
    edit(conn, row, "1", text=EDIT)
    edit(conn, row, "2", team="versus")
    edit(conn, row, "1", text=P1)
    edit(conn, row, "2", team="vote")
    plan = log.split_plan_of(log.get_task(conn, row["task_id"]))
    assert plan["pieces"][0]["edited_text"] is None and plan["pieces"][1]["team_source"] == "planner"


def test_the_same_text_and_team_change_nothing(conn):
    row = waiting(conn)
    before = snapshot(conn, row)
    code, out, jev = edit(conn, row, "2", team="vote", text=P2)
    assert code == 0 and "already reads that; nothing changed" in out and snapshot(conn, row) == before and jev.calls == []


def test_a_team_name_in_any_case_is_read(conn):
    row = waiting(conn)
    code, out, _ = edit(conn, row, "1", team="Research-Build")
    assert code == 0 and log.split_plan_of(log.get_task(conn, row["task_id"]))["pieces"][0]["team"] == "research-build"


# ---------- the refusals write nothing ----------

@pytest.mark.parametrize("kwargs,code_word,why", [
    ({"piece": "1", "text": "@grok " + P1}, "bad_task", "the new text starts with @ or /"),
    ({"piece": "1", "text": "x" * 400}, "bad_task", "the new text has 400 characters"),
    ({"piece": "1", "text": ""}, "bad_task", "the new text is empty"),
    ({"piece": "1", "team": "debate"}, "bad_preset", "debate is not a team a piece of this split can take now"),
    ({"piece": "3", "team": "route"}, "usage", "the plan has 2 pieces; --piece is 1 to 2"),
    ({"piece": "x", "team": "route"}, "usage", "--piece is 1 to 2"),
    ({"piece": "1"}, "usage", "give --team <team>, --slot <slot>=<agent>, or the new text after --"),  # brief 29.1
])
def test_each_refusal_writes_nothing(conn, kwargs, code_word, why):
    row = waiting(conn)
    before = snapshot(conn, row)
    code, out, jev = edit(conn, row, kwargs.pop("piece"), **kwargs)
    assert code == 2 and why in out and "Nothing was logged or sent." in out
    assert snapshot(conn, row) == before and jev.calls == []


def test_an_edit_is_refused_once_the_plan_is_approved(conn):
    row = waiting(conn, teamed(f"## Pieces\n1. {P1}\n2. {P2}\n\n## Join\n{JOIN}\n"))
    lines = []
    cli.cmd_split_go([str(row["n"])], answer="n", conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                     label=Jev(), ask=None, post=None, worker=None, out=lines.append)
    code, out, _ = edit(conn, row, "1", team="redteam")
    assert code == 2 and "isn't waiting at its plan (it is cancelled)" in out


def test_an_edit_while_another_process_holds_the_splits_run_is_refused(conn, monkeypatch):
    row = waiting(conn)
    other = (os.getpid() + 1, "2026-10-27T09:00:00+00:00")
    monkeypatch.setattr(runs, "READ", lambda pid: other[1] if pid == other[0] else "2026-10-20T12:00:00+00:00")
    log.claim_run(conn, row["task_id"], *other)
    before = snapshot(conn, row)
    code, out, jev = edit(conn, row, "2", team="versus")
    assert code == 2 and f"Refused: #{row['n']} can't be edited" in out
    assert snapshot(conn, row) == before


def test_an_edit_of_a_task_that_is_not_a_split_is_refused(conn):
    log.add_task(conn, "sr-r", "t", "cli", WRITING)
    lines = []
    code = cli.cmd_split_edit(["sr-r"], piece="1", team="route", conn=conn, config=CONFIG, roster=ROSTER, environ={},
                              settings_paths=[], label=Jev(), out=lines.append)
    assert code == 2 and "is not a split task" in "\n".join(lines)


# ---------- Terminal's e: the piece, its text, its team (Enter keeps each) ----------

def test_e_asks_text_then_team_and_enter_keeps_each(conn):
    plan = teamed(f"## Pieces\n1. {P1}\n2. {P2}\n\n## Join\n{JOIN}\n", team=["route", "vote"])
    ask = Ask("e", "2", "", "versus", "", "", "e", "1", EDIT, "", "n")  # brief 29.1 (decision 12): Enter keeps each slot
    code, out, worker, chat, jev, _ = _split(conn, claude=(plan,), ask=ask)
    pieces = log.split_plan_of(_split_row(conn))["pieces"]
    assert (pieces[1]["edited_text"], pieces[1]["team"]) == (None, "versus")
    assert (pieces[0]["edited_text"], pieces[0]["team"]) == (EDIT, "route")
    assert ask.prompts[1:4] == ["Edit which piece? [1-2] ", "New text for piece 2 (Enter keeps it): ",
                                "Team for piece 2 (route, research-build, collab, versus, redteam, vote) [vote]: "]


def test_e_with_a_team_off_the_menu_changes_nothing(conn):
    ask = Ask("e", "1", EDIT, "debate", "n")
    code, out, worker, chat, jev, _ = _split(conn, ask=ask)
    first = log.split_plan_of(_split_row(conn))["pieces"][0]
    assert first["edited_text"] is None and "Not changed: debate is not a team" in out


# ---------- --answer e, and the command line ----------

def test_answer_e_names_the_edit_command(conn):
    row = waiting(conn)
    lines = []
    code = cli.cmd_split_go([str(row["n"])], answer="e", conn=conn, config=CONFIG, roster=ROSTER, environ={},
                            settings_paths=[], label=Jev(), ask=None, post=None, worker=None, out=lines.append)
    assert code == 2 and f"to change a piece: sr split --edit {row['n']} --piece <k>" in "\n".join(lines)


def test_the_command_line_takes_edit_piece_team_and_the_text_after_two_dashes(monkeypatch, capsys):
    seen = {}

    def fake(words, *, piece, team, text, **kw):
        seen.update(words=words, piece=piece, team=team, text=text)
        return 0
    monkeypatch.setattr(cli, "cmd_split_edit", fake)
    assert cli.main(["split", "--json", "--edit", "sr-20261027-104210-7c1a", "--piece", "1", "--team", "versus", "--",
                     "a text with -- and $5 in it"], platform="darwin") == 0
    assert seen == {"words": ["sr-20261027-104210-7c1a"], "piece": "1", "team": "versus",
                    "text": "a text with -- and $5 in it"}
    assert cli.main(["split", "--edit", "5", "--piece", "1"], platform="darwin") == 0 and seen["text"] is None


def test_the_command_line_refuses_edit_with_anything_else(capsys):
    assert cli.main(["split", "--edit", "5", "--piece", "1", "--go", "5"], platform="darwin") == 2
    assert "changes one piece of a plan that waits, and takes nothing else" in capsys.readouterr().out
    assert cli.main(["split", "--piece", "1", "--team", "route"], platform="darwin") == 2
