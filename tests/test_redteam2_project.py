"""Build brief 32, R (decision 13, reopening D21 for the attack slots alone): on a --project task Cursor may fill redteam's
`attack` or `attack2` and gets, as text in its prompt, what an attack stage gets there today: the task, the build, the
handoff, the memory block and its router notes; never a file, a copy or a tool. Every other Cursor slot on a project
stays refused, and status says which slots a project refuses to which agent. Fakes only; every value here is fake."""
import json

import pytest

from router import __main__ as cli
from router import context, cursor_worker, log, presets, relay, status
from tests.helpers import shipped_roster
from tests.test_cursor_send import Cursor, Ready, answer
from tests.test_loop import Clock, Scripted
from tests.test_memory_block import SECTION, project  # noqa: F401  (the project fixture: "demo", a handoff and no git)
from tests.test_redteam2_chain import A_LIST, B_LIST, BUILD, REVISION_A, TASK
from tests.test_relay import CONFIG, Chat, RelayHook

ROSTER = shipped_roster()
LOADED = presets.load_presets(ROSTER, tuple(cli.SENDERS), relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
REVISION_AB = REVISION_A.replace("A3:", "A3, B3:")


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _relay(conn, *, slots=(), claude=(BUILD, REVISION_AB + SECTION), chat=(A_LIST, "PASS"), cursor=None, preset="redteam"):
    hook, worker, chatgpt, clock, lines = RelayHook(), Scripted(*claude), Chat(*chat), Clock(), []
    cursor = cursor if cursor is not None else Cursor(answer(B_LIST))
    code = cli.cmd_relay(preset, TASK, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                         settings_paths=[], post=hook.post, worker=worker, chatgpt=chatgpt, codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True,
                         slots=list(slots), cursor=cursor, cursor_ready=Ready(), project="demo", out=lines.append)
    rows = log.recent_tasks(conn)
    return code, "\n".join(lines), rows[0] if rows else None, worker, chatgpt, cursor


def test_on_a_project_cursor_attacks_with_the_handoff_as_text_and_the_revise_returns_the_section(conn, project):
    code, out, row, worker, chat, cursor = _relay(conn)
    assert code == 0, out
    assert json.loads(row["slots"])["attack2"] == "cursor" and log.project_of(row) == "demo"
    sent = cursor.prompts[0]
    assert sent.startswith(cursor_worker.opener()) and context.start_marker("demo") in sent
    assert "The owner's note one." in sent and BUILD in sent and "A1 " not in sent
    assert chat.prompts[0].replace(relay.checking.SEARCH_LINE_GENERAL + "\n\n", "") == sent.removeprefix(
        cursor_worker.opener() + "\n\n")  # the same text ChatGPT's attack got, less its search line
    assert row["status"] == "done" and log.get_task(conn, row["task_id"])["check_state"] == "passed"


def test_cursor_may_take_the_first_attack_slot_on_a_project_too(conn, project):
    code, out, row, worker, chat, cursor = _relay(conn, slots=[("attack", "cursor"), ("attack2", "chatgpt")],
                                                  chat=(B_LIST, "PASS"), cursor=Cursor(answer(A_LIST)))
    assert code == 0, out
    assert json.loads(row["slots"]) == {"build": "claude", "attack": "cursor", "attack2": "chatgpt", "check": "chatgpt"}


def test_every_other_cursor_slot_on_a_project_stays_refused_before_any_row(conn, project):
    code, out, row, *_ = _relay(conn, preset="versus", slots=[("b", "cursor")])
    assert code == 2 and row is None
    assert "Refused: --project with cursor in slot b is refused" in out and "redteam's attack or attack2 only" in out


def test_status_says_which_slots_a_project_refuses_to_which_agent():
    view = status.preset_view(LOADED.presets["redteam"], ROSTER.live)
    refuses = {s["name"]: s["project_refuses"] for s in view["slots"]}
    assert refuses == {"build": ["cursor"], "attack": [], "attack2": [], "check": ["cursor"]}
    allowed = {s["name"]: s["allowed"] for s in view["slots"]}
    assert "cursor" in allowed["attack"] and "cursor" in allowed["attack2"] and "cursor" not in allowed["check"]
    versus = {s["name"]: s["project_refuses"] for s in status.preset_view(LOADED.presets["versus"], ROSTER.live)["slots"]}
    assert versus == {"a": ["cursor"], "b": ["cursor"]}
    assert view["chain"] == "Claude build → ChatGPT attack → Cursor attack → Claude revise → ChatGPT check"
    assert view["description"].startswith("One agent builds, two others attack it on their own")


def test_attack2_is_refused_on_any_other_preset_with_no_row(conn, project):
    code, out, row, *_ = _relay(conn, preset="research-build", slots=[("attack2", "cursor")])
    assert code == 2 and row is None and "research-build has no slot attack2" in out
