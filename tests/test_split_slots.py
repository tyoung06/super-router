"""Brief 29.1 (decision 12): an agent per piece. `sr split --edit <n> --piece <k> --slot <slot>=<agent>` (repeatable;
`<slot>=default` puts the default back) sets a preset piece's slots while the split waits at its plan, checked by the one
pure function `sr relay <team> --<slot> <agent>` uses plus the piece's project rules; a team change clears them; the plan
keeps them; the approval checks them and the piece runs with them; the planner never sets them. Refusals write nothing
(`slot_refused`). Terminal's `e` asks each slot after the team. Fakes only; every value fake."""
import json

import pytest

from router import __main__ as cli
from router import log, page_commands, split
from tests.helpers import teamed
from tests.test_relay import CONFIG, ROSTER
from tests.test_split_approve import JOIN, P1, P2, Ask, Jev, _go, _split, _split_row
from tests.test_split_edit import conn, snapshot  # noqa: F401


def waiting(conn):
    _split(conn, claude=(teamed(f"## Pieces\n1. {P1}\n2. {P2}\n\n## Join\n{JOIN}\n", team=["route", "versus"]),))
    return _split_row(conn)


def edit(conn, row, piece, *, slots=None, team=None):
    lines = []
    code = cli.cmd_split_edit([str(row["n"])], piece=piece, team=team, slots=slots, conn=conn, config=CONFIG,
                              roster=ROSTER, environ={}, settings_paths=[], label=Jev(), out=lines.append)
    return code, "\n".join(lines)


def _piece(conn, row, k):
    return log.split_plan_of(log.get_task(conn, row["task_id"]))["pieces"][k - 1]


def test_a_versus_pieces_b_slot_can_be_cursor_and_the_plan_keeps_it(conn):
    row = waiting(conn)
    code, out = edit(conn, row, "2", slots=["b=cursor"])
    assert code == 0, out
    assert _piece(conn, row, 2)["slots"] == {"b": "cursor"}
    assert "Piece 2: slot b is cursor (you set it)." in out


def test_default_puts_the_slot_back(conn):
    row = waiting(conn)
    edit(conn, row, "2", slots=["b=cursor"])
    code, out = edit(conn, row, "2", slots=["b=default"])
    assert code == 0 and _piece(conn, row, 2).get("slots") in (None, {})
    assert "Piece 2: slot b is chatgpt again (its default)." in out


@pytest.mark.parametrize("piece, slots, words", [
    ("1", ["b=cursor"], "piece 1 is a route piece: slots go on a preset's piece"),
    ("2", ["zz=claude"], "versus has no slot zz"),
    ("2", ["a=cursor", "b=cursor"], "both hold cursor"),
    ("2", ["b"], "a slot is given as <slot>=<agent>"),
    ("2", ["b=nobody"], "no agent named nobody"),
])
def test_a_refused_slot_writes_nothing(conn, piece, slots, words):
    row = waiting(conn)
    before = snapshot(conn, row)
    code, out = edit(conn, row, piece, slots=slots)
    assert code == 2 and words in out and snapshot(conn, row) == before


def test_a_team_change_clears_the_slots(conn):
    row = waiting(conn)
    edit(conn, row, "2", slots=["b=cursor"])
    code, out = edit(conn, row, "2", team="collab")
    assert code == 0 and _piece(conn, row, 2).get("slots") in (None, {})


def test_the_approval_checks_the_slots_and_the_piece_runs_with_them(conn):
    row = waiting(conn)
    edit(conn, row, "2", slots=["b=cursor"])
    code, out, worker, chat, jev = _go(conn, [str(row["n"])], ask=Ask("y"))
    pieces = log.pieces_of(conn, row["task_id"])
    second = next(p for p in pieces if p["preset"] == "versus")
    assert json.loads(second["slots"]) == {"a": "claude", "b": "cursor"}, out


def test_the_planner_never_sets_slots(conn):
    row = waiting(conn)
    plan = log.split_plan_of(log.get_task(conn, row["task_id"]))
    assert all("slots" not in p or not p["slots"] for p in plan["pieces"])


def test_terminals_e_asks_each_slot_after_the_team(conn):
    row = waiting(conn)
    ask = Ask("e", "2", "", "", "", "cursor", "n")  # piece 2, keep the text and the team, keep a, b cursor; then no
    code, out, worker, chat, jev = _go(conn, [str(row["n"])], ask=ask)
    assert any(p.startswith("Slot a for piece 2") for p in ask.prompts)
    assert any(p.startswith("Slot b for piece 2") and "[chatgpt]" in p for p in ask.prompts)
    assert _piece(conn, row, 2)["slots"] == {"b": "cursor"}


def test_the_page_builds_the_slot_edit_as_one_command():
    status = {"split": {"teams": [{"name": "versus"}, {"name": "route"}]}}
    built = page_commands.build({"action": "split_edit", "task_id": "sr-20261027-101010-aaaa", "piece": 2,
                                 "slots": {"b": "cursor"}}, status)
    assert list(built.args) == ["split", "--json", "--edit", "sr-20261027-101010-aaaa", "--piece", "2", "--slot", "b=cursor"]
    with pytest.raises(page_commands.Refused):
        page_commands.build({"action": "split_edit", "task_id": "sr-20261027-101010-aaaa", "piece": 2,
                             "slots": {"b": "cursor --x"}}, status)


def test_the_command_line_takes_slot_flags_on_an_edit(monkeypatch):
    seen = {}

    def fake(words, *, piece, team=None, text=None, slots=None, **kw):
        seen.update(piece=piece, slots=slots)
        return 0
    monkeypatch.setattr(cli, "cmd_split_edit", fake)
    assert cli.main(["split", "--edit", "5", "--piece", "2", "--slot", "b=cursor", "--slot", "a=default"],
                    platform="darwin") == 0
    assert seen == {"piece": "2", "slots": ["b=cursor", "a=default"]}
