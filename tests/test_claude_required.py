"""Build brief 24, A4 (decision 2): Claude is required. `route`, `relay` and `split` refuse every task while Claude isn't
available, before any row and before Jev, with the reason (`signed_out` or `not_configured`, or `unreachable` when its
check does not answer) and its Setup row. Every other agent is optional. Through the real main, every outside thing
faked."""
import pytest

from router import __main__ as cli
from router import log, online
from tests.helpers import fake_label
from tests.test_json_actions import World, jev

SETUP = "Claude is required for every task: see Setup, Claude (docs/SETUP.md). Nothing was logged or sent."


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    w = World(monkeypatch, tmp_path, capsys)
    w.asked = []
    real = w.label
    w.label = lambda *a, **k: w.asked.append(1) or real(*a, **k)
    return w


def _claude(monkeypatch, reason, code):
    checks = dict(cli.online.CHECKS)
    checks["claude"] = lambda: online.Answer((False, reason), code)
    monkeypatch.setattr(cli.online, "CHECKS", checks)


def _rows():
    conn = log.init_db(cli.DB_PATH)
    try:
        return log.recent_tasks(conn)
    finally:
        conn.close()


COMMANDS = [("route", "write a haiku about trays"), ("relay", "research-build", "write a haiku about trays"),
            ("split", "write a haiku and a limerick about trays")]


@pytest.mark.parametrize("argv", COMMANDS)
@pytest.mark.parametrize("reason, code, why", [
    ("not signed in (claude auth login)", "signed_out", "Claude is signed out (claude auth login)"),
    ("signed in with console, not the Claude plan", "not_configured",
     "Claude isn't set up: signed in with console, not the Claude plan"),
])  # a check that didn't answer twice goes ahead with a warning (the owner's decision 2 after F; test_check_retry.py)
def test_every_task_is_refused_before_any_row_while_claude_is_not_available(world, monkeypatch, argv, reason, code, why):
    _claude(monkeypatch, reason, code)
    found = world.json(*argv)
    assert (found["exit"], found["reason_code"], found["task_id"]) == (2, code, None)
    assert found["message"] == f"Refused: {why}. {SETUP}"
    assert _rows() == [] and world.asked == []        # no row, and Jev was never asked


def test_the_prose_is_the_same_line_without_json(world, monkeypatch):
    _claude(monkeypatch, "not signed in (claude auth login)", "signed_out")
    code, out, err = world.run("route", "write a haiku about trays")
    assert code == 2 and out.splitlines() == [f"Refused: Claude is signed out (claude auth login). {SETUP}"]


def test_with_claude_available_the_task_runs(world):
    world.label = fake_label(jev("quick_answer", 0.99))
    found = world.json("route", "what is 6 times 7")
    assert found["exit"] == 0 and found["outcome"] == "unchecked" and len(_rows()) == 1


def test_claude_is_checked_once_per_command_and_never_for_a_read(world, monkeypatch):
    ran = []
    checks = dict(cli.online.CHECKS)
    checks["claude"] = lambda: ran.append(1) or online.Answer((True, None))
    monkeypatch.setattr(cli.online, "CHECKS", checks)
    world.label = fake_label(jev("quick_answer", 0.99))
    world.json("route", "what is 6 times 7")
    assert ran == [1]
    world.run("log", "--json")
    world.run("show", "1", "--json")
    assert ran == [1]
