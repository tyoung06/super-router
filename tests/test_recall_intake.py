"""Rules v2.28, Jev, "A 12th skill, recall", after label test round 4 (skill table 3.4): a task Jev labels `recall`, or
that the owner answers `recall` at the floor prompt, with no --project and no --chat comes back before any agent call with
`recall needs --project or --chat: nothing to recall from` (the row is `returned`, Jev's label and tokens on it); with a
tag it routes to Claude with ChatGPT checking like any skill, the memory block rides and the checker gets the memory
line; `@claude` on an untagged recall task is an override as the Overrides section says. Fake agents, a fake store;
every value here is fake."""
from datetime import timedelta

import pytest

from router import __main__ as cli
from router import checking, log, memory, routing
from tests.fake_hindsight import FakeHindsight
from tests.helpers import fake_label
from tests.test_chat_intake import _route
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_memory_block import SECTION, T0, _block, _done, _entry, project  # noqa: F401 (project is a fixture)
from tests.test_relay import CONFIG, ROSTER, Chat
from tests.test_route_v2 import LOW, Answers, ok

RECALL = ok("recall")
QUESTION = "what did we decide about the tray last time"
REASON = "returned: recall needs --project or --chat: nothing to recall from"
BACK = "recall needs --project or --chat: nothing to recall from"


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _route_asking(conn, task, jev, ask, *, chat=None, worker=None, chatgpt=None, hindsight=None):
    """cmd_route with a terminal to ask in (test_chat_intake's _route has none)."""
    lines, clock, hook = [], Clock(), Webhook()
    code = cli.cmd_route(task, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=fake_label(jev),
                         post=hook.post, worker=worker or Scripted("an answer"), chatgpt=chatgpt or Chat("PASS"),
                         codex_login=lambda: True, ask=ask, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=True, out=lines.append, chat=chat, hindsight=hindsight)
    rows = log.recent_tasks(conn)
    return code, "\n".join(lines), rows[0] if rows else None


# ---------- routing.decide: pure ----------

def test_an_untagged_recall_label_comes_back_with_the_reason():
    d = routing.decide(RECALL, ROSTER)
    assert (d.action, d.skill, d.skill_source, d.agent, d.checker, d.reason) == ("return", "recall", "jev", None, None, REASON)
    assert routing.decide(RECALL, ROSTER, tagged=False) == d
    assert routing.NO_TAG_FOR_RECALL == REASON and routing.NEEDS_TAG == "recall"


def test_a_tagged_recall_label_routes_to_claude_with_chatgpt_checking_like_any_skill():
    d = routing.decide(RECALL, ROSTER, tagged=True)
    assert (d.action, d.skill, d.skill_source, d.agent, d.reason, d.checker, d.check_state, d.check_note) == (
        "send", "recall", "jev", "claude", "best", "chatgpt", "pending", None)


def test_the_owners_recall_answer_at_the_floor_follows_the_same_rule():
    back = routing.decide(LOW, ROSTER, answer="recall")
    assert (back.action, back.skill, back.skill_source, back.reason) == ("return", "recall", "owner", REASON)
    sent = routing.decide(LOW, ROSTER, answer="recall", tagged=True)
    assert (sent.action, sent.skill_source, sent.agent, sent.checker, sent.check_state) == ("send", "owner", "claude", "chatgpt", "pending")


def test_no_other_skill_needs_a_tag():
    for skill in ROSTER.skills:
        if skill == "recall":
            continue
        assert routing.decide(ok(skill), ROSTER).reason != REASON, skill
        assert routing.decide(ok(skill), ROSTER) == routing.decide(ok(skill), ROSTER, tagged=True), skill


@pytest.mark.parametrize("agent, checker", [("claude", "chatgpt"), ("grok", "chatgpt"), ("chatgpt", "claude")])
def test_an_override_on_an_untagged_recall_task_runs_as_the_overrides_section_says(agent, checker):
    d = routing.decide(RECALL, ROSTER, override=agent)
    assert (d.action, d.agent, d.reason, d.skill, d.checker, d.check_state) == ("send", agent, "override", "recall", checker, "pending")
    assert routing.decide(RECALL, ROSTER, override=agent, tagged=True) == d


def test_the_approval_screen_says_a_recall_piece_would_come_back():
    assert cli._piece_route(RECALL, ROSTER) == f"comes back: {BACK}"  # a split carries no tag


# ---------- sr route, untagged: back after Jev's row, before any agent call ----------

def test_an_untagged_recall_task_comes_back_before_any_agent_call(conn):
    worker, chat = Scripted("never"), Chat("never")
    code, out, row, label = _route(conn, QUESTION, jev=RECALL, worker=worker, chatgpt=chat)
    assert code == 4
    assert (row["status"], row["route_reason"], row["skill"], row["skill_source"], row["agent"], row["checker"]) == (
        "returned", REASON, "recall", "jev", None, None)
    assert (row["jev_label"], row["jev_tokens"]) == ("recall", 764) and len(label.calls) == 1  # Jev's label and tokens are on the row
    assert worker.prompts == [] and chat.prompts == [] and log.calls_for(conn, row["task_id"]) == []
    assert f"{row['task_id']} came back to you: {BACK}." in out and "Nothing was sent to an agent." in out


def test_the_owners_recall_answer_at_the_floor_comes_back_untagged_and_routes_tagged(conn):
    code, out, row = _route_asking(conn, QUESTION, LOW, Answers("recall"))
    assert code == 4 and (row["status"], row["skill"], row["skill_source"], row["route_reason"]) == ("returned", "recall", "owner", REASON)
    assert "Skill: recall (your choice)." in out and BACK in out and log.calls_for(conn, row["task_id"]) == []
    worker, chat = Scripted("we decided the tray must hold the ball"), Chat("PASS")
    code, out, row = _route_asking(conn, QUESTION, LOW, Answers("recall"), chat="tray", worker=worker, chatgpt=chat,
                                   hindsight=FakeHindsight(results=[]).client)  # rules v2.29: a tagged recall task needs the store
    assert code == 0, out
    assert (row["status"], row["skill"], row["skill_source"], row["agent"], row["checker"], row["check_state"]) == (
        "done", "recall", "owner", "claude", "chatgpt", "passed")
    assert worker.prompts == [QUESTION] and chat.prompts  # nothing remembered under tray yet: no block, a check all the same


# ---------- sr route, tagged: Claude does it, the block rides, ChatGPT checks with the memory line ----------

def test_a_tagged_recall_task_routes_to_claude_the_block_rides_and_chatgpt_checks_with_the_memory_line(conn):
    one = _done(conn, "sr-1", "first task about the tray", "we decided a tray must hold the ball, drop free and survive a driver")
    two = _done(conn, "sr-2", "second task about the tray", "the tray sheet script is in the inbox repo", at=T0 + timedelta(hours=1))
    fake = FakeHindsight(results=[FakeHindsight.result("task-sr-1", "a paraphrase the log never held", tags=["chat:tray"])])
    worker, chat = Scripted("From the earlier task: a tray must hold the ball, drop free and survive a driver."), Chat("PASS")
    code, out, row, _ = _route(conn, QUESTION, chat="tray", jev=RECALL, worker=worker, chatgpt=chat, hindsight=fake.client)
    assert code == 0, out
    assert (row["status"], row["skill"], row["skill_source"], row["agent"], row["route_reason"], row["checker"], row["check_state"]) == (
        "done", "recall", "jev", "claude", "best", "chatgpt", "passed")
    block = _block([_entry(two), _entry(one)])                      # entry one from the log, then the recall match
    assert worker.prompts == [f"{QUESTION}\n\n{block}"]              # the block rides on the doer
    assert chat.prompts[0].endswith("\n\n" + block)                   # and on the checker, byte for byte
    assert checking.CHECK_MEMORY_LINE in chat.prompts[0]              # with the memory line
    assert chat.prompts[0].index(checking.CHECK_MEMORY_LINE) < chat.prompts[0].index("===== TASK =====")
    calls = log.calls_for(conn, row["task_id"])
    assert [c["kind"] for c in calls] == ["do", "check"]
    assert log.call_memory_of(calls[0]) == {"tag": "chat:tray", "found": 2, "sent": 2, "text": block}
    assert log.call_memory_of(calls[1]) == {"tag": "chat:tray", "found": 2, "sent": 2, "text": block, "from": row["task_id"]}
    assert len(fake.recalls) == 1 and len(fake.retains) == 1          # one recall for the doer; the delivered answer retained once


def test_a_project_tagged_recall_task_routes_too(conn, project):
    worker, chat = Scripted("From the handoff: note one and note two." + SECTION), Chat("PASS")
    code, out, row, _ = _route(conn, QUESTION, project="demo", jev=RECALL, worker=worker, chatgpt=chat,
                               hindsight=FakeHindsight(results=[]).client)  # rules v2.29: a tagged recall task needs the store
    assert code == 0, out
    assert (row["status"], row["skill"], row["agent"], row["checker"], row["check_state"]) == ("done", "recall", "claude", "chatgpt", "passed")


# ---------- @claude on an untagged recall task: the Overrides section as today ----------

def test_at_claude_on_an_untagged_recall_task_is_an_override_as_today(conn):
    worker, chat = Scripted("I have nothing to recall from."), Chat("PASS")
    code, out, row, _ = _route(conn, "@claude " + QUESTION, jev=RECALL, worker=worker, chatgpt=chat)
    assert code == 0, out
    assert (row["status"], row["agent"], row["route_reason"], row["skill"], row["skill_source"], row["checker"], row["check_state"]) == (
        "done", "claude", "override", "recall", "jev", "chatgpt", "passed")
    assert worker.prompts == [QUESTION] and memory.MARK not in worker.prompts[0]  # untagged: no block
    assert checking.CHECK_MEMORY_LINE not in chat.prompts[0] and "you chose it with @claude" in out
