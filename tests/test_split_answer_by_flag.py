"""Build brief 22, C2 (rules v2.31, Router for the interface, "Answers without a terminal"; decisions 2 and 9; Phase 0
choice 9): `sr split --go <n> --answer y|n` approves or rejects a plan that waits; editing a piece (`e`) stays
Terminal-only. A piece Jev left under the floor is answered on the same command with `--skill <k>=<key>`; `--answer y`
while such a piece has no answer is refused before any piece row (`needs_label`, naming the pieces), and `--skill` is
only for such a piece. Fakes only; every value here is fake."""
import json

import pytest

from router import __main__ as cli
from router import log
from tests.test_json_actions import World, jev
from tests.test_loop import Scripted
from tests.test_relay import Chat

PLAN = "## Pieces\n1. piece one\n2. piece two\n\n## Join\nput them together"


def _labels(low=()):
    """Jev: confident on every piece but the ones named in `low` (under the floor), the split itself never asked."""
    def label(text, *, task_id, tokens_this_month):
        if text in low:
            return {**jev("writing"), "status": "below_floor", "confidence": 0.55}
        return jev("writing", 0.95)
    return label


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    return World(monkeypatch, tmp_path, capsys)


def _waiting_split(world, low=()):
    world.label, world.worker = _labels(low), Scripted(PLAN)
    found = world.json("split", "two pieces of work")
    assert (found["status"], found["waiting_on"]) == ("returned", "split_plan")
    return found


def _rows():
    conn = log.init_db(cli.DB_PATH)
    try:
        return [dict(r) for r in log.recent_tasks(conn, 20)][::-1]
    finally:
        conn.close()


def test_answer_y_approves_the_plan_and_runs_the_pieces(world):
    _waiting_split(world)
    world.worker = Scripted("piece one done", "piece two done", "joined")
    world.chatgpt = Chat("PASS", "PASS", "PASS")
    found = world.json("split", "--go", "1", "--answer", "y")
    assert (found["exit"], found["status"], found["outcome"]) == (0, "done", "passed")
    rows = _rows()
    assert [(r["mode"], r["status"]) for r in rows] == [("split", "done"), ("piece", "done"), ("piece", "done")]


def test_answer_n_cancels_with_the_plan_kept(world):
    _waiting_split(world)
    found = world.json("split", "--go", "1", "--answer", "n")
    assert (found["exit"], found["status"], found["outcome"]) == (0, "cancelled", "cancelled")
    rows = _rows()
    assert len(rows) == 1 and log.split_plan_of(rows[0]) is not None


@pytest.mark.parametrize("argv", [
    ["split", "--go", "1", "--answer", "e"],
    ["split", "--go", "1", "--answer", "maybe"],
    ["split", "--answer", "y"],
    ["split", "--skill", "2=writing"],
    ["split", "--go", "1", "--answer", "n", "--skill", "2=writing"],
])
def test_usage_refusals_change_nothing(world, argv):
    _waiting_split(world, low=("piece two",))
    found = world.json(*argv)
    assert (found["exit"], found["reason_code"]) == (2, "usage")
    rows = _rows()
    assert len(rows) == 1 and rows[0]["check_note"] == log.AWAITING_APPROVAL


def test_edit_stays_terminal_only(world):
    _waiting_split(world)
    code, out, err = world.run("split", "--go", "1", "--answer", "e", "--json")
    assert code == 2 and "Terminal-only" in json.loads(err)["message"]


def test_a_piece_under_the_floor_needs_its_answer_before_any_piece_row(world):
    _waiting_split(world, low=("piece two",))
    found = world.json("split", "--go", "1", "--answer", "y")
    assert (found["exit"], found["reason_code"]) == (2, "needs_label")
    assert "piece 2" in found["message"] and "--skill 2=<key>" in found["message"]
    assert len(_rows()) == 1


def test_skill_answers_a_piece_under_the_floor(world):
    _waiting_split(world, low=("piece two",))
    world.worker = Scripted("piece one done", "piece two done", "joined")
    world.chatgpt = Chat("PASS", "PASS", "PASS")
    found = world.json("split", "--go", "1", "--answer", "y", "--skill", "2=planning")
    assert found["exit"] == 0
    pieces = [r for r in _rows() if r["mode"] == "piece"]
    assert [(p["skill"], p["skill_source"]) for p in pieces] == [("writing", "jev"), ("planning", "owner")]


@pytest.mark.parametrize("skill", ["1=planning", "3=planning", "2=nope", "2planning", "2=planning,2=writing"])
def test_skill_refusals(world, skill):
    _waiting_split(world, low=("piece two",))
    argv = ["split", "--go", "1", "--answer", "y"]
    for one in skill.split(","):
        argv += ["--skill", one]
    found = world.json(*argv)
    assert (found["exit"], found["reason_code"]) == (2, "usage")
    assert len(_rows()) == 1


def test_answer_on_a_split_that_is_not_waiting_at_its_plan(world):
    _waiting_split(world)
    world.json("split", "--go", "1", "--answer", "n")
    found = world.json("split", "--go", "1", "--answer", "y")
    assert (found["exit"], found["reason_code"]) == (2, "wrong_state")


def test_without_answer_and_without_a_terminal_the_plan_still_waits(world, monkeypatch):
    _waiting_split(world)
    found = world.json("split", "--go", "1")
    assert (found["exit"], found["status"], found["waiting_on"]) == (0, "returned", "split_plan")
