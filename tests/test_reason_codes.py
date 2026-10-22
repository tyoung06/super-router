"""Build brief 21, A1 (rules v2.30, Router for the interface; decision 1: store reason_code, derive the rest). Every
return writes its `reason_code` on the task row at the moment the task comes back, by the code that makes the return;
the reason's prose is never parsed back. A wait on the owner (a versus or vote pick, a split's plan or its pieces) is not a
return and writes none; a refusal writes no row at all. Fake agents and a fake Jev only; every value here is fake."""
import pytest

from router import __main__ as cli
from router import context, log, routing
from tests.helpers import fake_label, roster_with, shipped_roster
from tests.test_context import HANDOFF_TEXT, project  # noqa: F401 (the fixture)
from tests.test_context import _route as _project_route
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_relay import CONFIG, Chat
from tests.test_split_approve import Ask, Jev, _split

ROSTER = shipped_roster()


def jev(label="writing", confidence=0.93, status="ok"):
    return {"status": status, "label": label, "confidence": confidence, "needs_split": 0.1, "tokens": 700}


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


# ---------- routing names the code beside the reason ----------

@pytest.mark.parametrize("answer, kwargs, reason, code", [
    (jev("writing", 0.5, "below_floor"), {"can_ask": False}, "returned: needs your label", "needs_label"),
    ({"status": "error", "error": "Boom", "tokens": 0}, {"can_ask": False}, "returned: needs your label", "needs_label"),
    ({"status": "over_cap"}, {"can_ask": False}, "returned: needs your label", "needs_label"),
    (jev("none_of_these", 0.9, "none_of_these"), {"can_ask": False}, "returned: needs your label", "needs_label"),
    (jev("writing", 0.5, "below_floor"), {"answer": routing.NONE_OF_THESE}, "returned: no skill", "no_skill"),
    (jev("writing", 0.5, "below_floor"), {"answer": routing.NO_ANSWER}, "returned: no valid answer", "no_answer"),
    (jev("computer_use"), {}, "returned: skill not routed in version 2", "not_routed"),
    (jev("recall", 0.97), {}, routing.NO_TAG_FOR_RECALL, "needs_tag"),
    (jev("x_social_pulse"), {"files": True}, routing.NO_FILES_FOR_GROK, "files_to_agent"),
    (jev("writing"), {"override": "grok", "files": True}, routing.NO_FILES_FOR_GROK, "files_to_agent"),
])
def test_every_return_decision_carries_its_code(answer, kwargs, reason, code):
    decision = routing.decide(answer, ROSTER, **kwargs)
    assert (decision.action, decision.reason, decision.code) == ("return", reason, code)
    assert decision.code in log.RETURN_CODES


def test_a_skill_with_no_available_agent_comes_back_unavailable():
    # brief 24 (decision 3): a doer not live has a stand-in now (it came back `not_live`); only no agent at all comes back
    decision = routing.decide(jev("writing"), roster_with(claude=False))
    assert (decision.action, decision.agent) == ("send", "chatgpt")
    decision = routing.decide(jev("writing"), roster_with(claude=False, chatgpt=False))
    assert (decision.action, decision.reason, decision.code) == ("return", "returned: no agent available for it",
                                                                 "unavailable")


@pytest.mark.parametrize("answer, kwargs", [(jev("writing"), {}), (jev("quick_answer"), {}),
                                            (jev("recall"), {"tagged": True}), (jev("writing"), {"override": "chatgpt"})])
def test_a_decision_that_sends_has_no_code(answer, kwargs):
    decision = routing.decide(answer, ROSTER, **kwargs)
    assert decision.action == "send" and decision.code is None


# ---------- the log stores the code, and only a code it knows ----------

def _queued(conn, task_id="sr-1", chat=None):
    log.add_task(conn, task_id, "t", "cli", jev(), chat=chat)
    return log.get_task(conn, task_id)


def test_set_returned_stores_the_code_and_refuses_one_it_does_not_know(conn):
    _queued(conn)
    with pytest.raises(ValueError, match="reason_code 'made_up'"):
        log.set_returned(conn, "sr-1", "returned: no skill", reason_code="made_up")
    assert log.get_task(conn, "sr-1")["status"] == "queued"
    log.set_returned(conn, "sr-1", "returned: no skill", reason_code="no_skill")
    row = log.get_task(conn, "sr-1")
    assert (row["status"], row["route_reason"], row["reason_code"]) == ("returned", "returned: no skill", "no_skill")


def test_return_for_context_stores_the_code_it_is_given(conn):
    for task_id, code in (("sr-1", "handoff_key"), ("sr-2", "handoff_unreadable")):
        _queued(conn, task_id)
        log.return_for_context(conn, task_id, "a note", code)
        assert log.get_task(conn, task_id)["reason_code"] == code
    _queued(conn, "sr-3")
    with pytest.raises(ValueError):
        log.return_for_context(conn, "sr-3", "a note", "needs_label")  # not a handoff return


def test_return_for_memory_stores_memory_down(conn):
    _queued(conn, chat="tray")
    log.return_for_memory(conn, "sr-1", routing.NO_STORE_FOR_RECALL)
    assert log.get_task(conn, "sr-1")["reason_code"] == "memory_down"


# ---------- through the commands: every return writes its code; waits and refusals write none ----------

def _route(conn, answer, *, ask=None, task="write a poem", roster=ROSTER, worker=None):
    lines, clock, hook = [], Clock(), Webhook()
    code = cli.cmd_route(task, conn=conn, config=CONFIG, roster=roster, environ={}, settings_paths=[],
                         label=fake_label(answer), post=hook.post, worker=worker or Scripted("x"), chatgpt=Chat("PASS"),
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=True, ask=ask, out=lines.append)
    rows = log.recent_tasks(conn)
    return code, rows[0] if rows else None


@pytest.mark.parametrize("answer, ask, code", [
    (jev("writing", 0.5, "below_floor"), None, "needs_label"),
    (jev("writing", 0.5, "below_floor"), Ask("0"), "no_skill"),
    (jev("writing", 0.5, "below_floor"), Ask(), "no_answer"),     # the input ended
    (jev("computer_use"), None, "not_routed"),
    (jev("recall", 0.97), None, "needs_tag"),
])
def test_route_writes_the_code_of_every_return(conn, answer, ask, code):
    exit_code, row = _route(conn, answer, ask=ask)
    assert exit_code == 4 and row["status"] == "returned" and row["reason_code"] == code
    assert log.calls_for(conn, row["task_id"]) == []


def test_no_agent_for_the_skill_writes_unavailable(conn):
    exit_code, row = _route(conn, jev("writing"), roster=roster_with(claude=False, chatgpt=False))
    assert exit_code == 4 and row["reason_code"] == "unavailable"


def test_a_key_like_handoff_line_writes_handoff_key(project, conn):  # noqa: F811
    (project / "HANDOFF.md").write_text(HANDOFF_TEXT.replace("note two.", "note two.\nJEV_API_KEY=abcdefghijklmnop"))
    code, out, row, label = _project_route(conn, project="demo", worker=Scripted("x"))
    assert code == 4 and row["status"] == "returned" and row["reason_code"] == "handoff_key"


def test_a_handoff_gone_before_the_call_writes_handoff_unreadable(project, conn):  # noqa: F811
    class Gone(Scripted):
        def __call__(self, prompt):
            raise AssertionError("no call is made")
    real_attach = context.attach

    def attach(prompt, task, agent, secrets, **kw):
        (project / "HANDOFF.md").unlink()  # the file goes after intake, before the first call
        return real_attach(prompt, task, agent, secrets, **kw)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(context, "attach", attach)
        code, out, row, label = _project_route(conn, project="demo", worker=Gone())
    assert code == 4 and row["status"] == "returned" and row["reason_code"] == "handoff_unreadable"


def test_a_tagged_recall_task_without_its_memory_writes_memory_down(conn):
    log.add_task(conn, "sr-1", "what did we decide", "cli", jev("recall", 0.97), chat="tray")
    log.set_route(conn, "sr-1", agents=ROSTER.names, agent="claude", route_reason="best", skill="recall",
                  skill_source="jev", checker="chatgpt", check_state="pending")
    lines = []
    assert cli._recall_came_back(conn, log.get_task(conn, "sr-1"), "claude", "do", "store", lines.append) == (None, 4, None)
    assert log.get_task(conn, "sr-1")["reason_code"] == "memory_down"


def test_a_piece_that_comes_back_at_the_approval_writes_its_code(conn):
    from tests.test_split_approve import P1, P2
    code, out, *_ = _split(conn, ask=Ask("y"), jev=Jev({P2: jev("recall", 0.97)}))
    pieces = {r["task"]: r for r in log.recent_tasks(conn, 10) if r["mode"] == "piece"}
    assert pieces[P2]["status"] == "returned" and pieces[P2]["reason_code"] == "needs_tag"  # a piece carries no tag
    assert pieces[P1]["reason_code"] is None


def test_a_wait_on_the_owner_is_not_a_return_and_writes_no_code(conn):
    from tests.test_versus_run import _versus
    code, out, row, worker, chat = _versus(conn)
    assert row["status"] == "returned" and row["reason_code"] is None  # awaiting the pick
    code, out, *_ = _split(conn)
    split_row = next(r for r in log.recent_tasks(conn, 10) if r["mode"] == "split")
    assert split_row["status"] == "returned" and split_row["reason_code"] is None  # awaiting approval


def test_a_refusal_writes_no_row(conn):
    exit_code, row = _route(conn, jev("writing"), task="   ")
    assert exit_code == 2 and row is None
