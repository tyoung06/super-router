"""Build brief 24, A6 (decision 13): without Jev (no JEV_API_KEY), Jev isn't called. A routed task asks for its skill in
Terminal, or comes back for your label on the page, as a Jev error does today, in plain words: "Jev isn't set up: pick
the skill". There is no second labeler. The row keeps `jev_status` `not_set_up` and 0 tokens. Fakes only."""
import functools

import pytest

from router import __main__ as cli
from router import jev, log, state
from tests.test_cli import CONFIG, ROSTER, Recorder, _Reply


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _route(conn, task="write two lines about trays", *, ask=None, skill=None):
    lines = []
    code = cli.cmd_route(task, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=functools.partial(jev.label, roster=ROSTER, api_key=None), ask=ask,
                         post=Recorder(_Reply(200, {"success": True, "runUuid": "uuid-1"})),
                         worker=Recorder("two lines"), chatgpt=lambda *a, **k: "PASS", codex_login=lambda: True,
                         skill=skill, out=lines.append)
    return code, lines, log.recent_tasks(conn)[0]


def test_in_terminal_the_task_asks_for_its_skill_in_plain_words(conn):
    answers = iter(["writing"])
    code, lines, row = _route(conn, ask=lambda prompt: next(answers))
    assert "Jev isn't set up: pick the skill." in lines and "Which skill does this task need?" in lines
    assert (row["jev_status"], row["jev_tokens"], row["skill"], row["skill_source"]) == ("not_set_up", 0, "writing", "owner")
    assert row["agent"] == "claude"


def test_without_a_terminal_it_comes_back_for_your_label(conn):
    code, lines, row = _route(conn)
    assert code == 4 and (row["status"], row["reason_code"]) == ("returned", "needs_label")
    assert "Jev isn't set up: pick the skill." in lines and not any("KeyMissing" in line for line in lines)
    assert state.of(row, []).as_dict() == {"waiting_on": "needs_label", "outcome": None}


def test_your_answer_by_flag_labels_it_without_jev(conn):
    code, lines, row = _route(conn, skill="writing")
    assert code == 0 and (row["jev_status"], row["skill_source"], row["status"]) == ("not_asked", "owner", "done")


def test_a_floor_row_left_by_a_dead_run_reads_needs_label():
    assert "not_set_up" in state.FLOOR_STATUSES and "not_set_up" in log.JEV_STATUSES
