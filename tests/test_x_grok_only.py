"""The owner's decision of 21 Oct, after brief 24's F (#106 and #112: web search can't see X posts; both ended
failed_check after about four calls, and #112's real Grok answer came late and was thrown away): `x_social_pulse` is
Grok Bot's alone, as `make_media` is. Without Grok Bot the task comes back `unavailable` ("x_social_pulse needs Grok Bot:
<why>") after Jev's row, with no agent call. Grok's x_social_pulse call is never taken over: at 2N it gets the overdue
note only, and its answer, whenever it comes within the usual Grok timeout, is the task's answer, checked as usual. A
failed send fails the task with its reason. `meta_social_trends` keeps its stand-in and both of its lines. Fakes only."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from router import __main__ as cli
from router import availability, log, routing, settings, takeover
from tests.helpers import fake_label, shipped_roster
from tests.test_json_actions import World, jev
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_relay import CONFIG, Chat
from tests.test_routing_availability import WHY, Gate, _table

ROSTER = shipped_roster()
X = "what are gardeners on X saying about rubber trays this week"
NO_INBOX = "Grok Bot isn't set up: no inbox repo in settings"


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    w = World(monkeypatch, tmp_path, capsys)
    w.label, w.hook = fake_label(jev("x_social_pulse")), Webhook()
    w.chatgpt, w.worker = Chat("PASS"), Scripted("PASS")
    return w


def _rows(n=1):
    conn = log.init_db(cli.DB_PATH)
    try:
        task = log.task_by_number(conn, n)
        return task, log.calls_for(conn, task["task_id"])
    finally:
        conn.close()


def test_routing_says_x_social_pulse_is_grok_bots_alone():
    assert routing.ONLY == {"make_media": "grok", "x_social_pulse": "grok"}
    decision = routing.decide(jev("x_social_pulse"), ROSTER, available=_table({"grok"}))
    assert (decision.action, decision.code, decision.reason) == (
        "return", "unavailable", f"returned: x_social_pulse needs Grok Bot: {WHY['grok']}")
    assert routing.decide(jev("meta_social_trends"), ROSTER, available=_table({"grok"})).agent == "chatgpt"


def test_without_grok_bot_the_task_comes_back_after_one_jev_call_and_no_agent_call(world, monkeypatch, tmp_path):
    local = tmp_path / "bare.local.json"
    local.write_text("{}")
    monkeypatch.setattr(settings, "LOCAL_PATH", local)
    found = world.json("route", X)
    task, calls = _rows()
    assert (task["status"], task["reason_code"], task["route_reason"]) == (
        "returned", "unavailable", f"returned: x_social_pulse needs Grok Bot: {NO_INBOX}")
    assert len(world.label.calls) == 1 and calls == [] and world.hook.sent == []
    assert world.worker.prompts == [] and world.chatgpt.prompts == []
    assert found["reason_code"] == "unavailable"


def test_status_says_x_social_pulse_needs_grok_bot_and_meta_research_still_has_its_stand_in(world, monkeypatch,
                                                                                           tmp_path):
    local = tmp_path / "bare.local.json"
    local.write_text("{}")
    monkeypatch.setattr(settings, "LOCAL_PATH", local)
    now = {s["key"]: s["now"] for s in json.loads(world.run("status", "--json")[1])["skills"]}
    assert (now["x_social_pulse"]["note"], now["x_social_pulse"]["comes_back"], now["x_social_pulse"]["doer"]) == (
        "needs Grok Bot", f"x_social_pulse needs Grok Bot: {NO_INBOX}", None)
    assert (now["meta_social_trends"]["doer"], now["meta_social_trends"]["note"]) == ("chatgpt", "done without Meta")


def _ago(minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")


def test_an_overdue_x_call_is_never_taken_over_and_its_answer_after_2n_is_used_and_checked(world):
    world.run("route", X, "--no-wait")
    conn = log.init_db(cli.DB_PATH)
    task = log.task_by_number(conn, 1)
    conn.execute("UPDATE calls SET sent_at = ? WHERE call_id = ?", (_ago(12), task["task_id"]))
    conn.commit()
    conn.close()
    code, out, err = world.run("check")
    task, calls = _rows()
    assert "took over" not in out and "No takeover" not in out
    assert (task["status"], task["check_note"], calls[0]["status"]) == ("sent", "overdue: grok, 12 min", "sent")
    world.hook.bodies["do"] = "Gardeners on X like rubber trays."
    code, out, err = world.run("check")
    task, calls = _rows()
    assert (task["status"], task["agent"], task["result"], task["check_state"]) == (
        "done", "grok", "Gardeners on X like rubber trays.", "passed")
    assert [(c["agent"], c["kind"], c["status"], c["reason_code"]) for c in calls] == [
        ("grok", "do", "done", None), ("chatgpt", "check", "done", None)]
    assert world.chatgpt.prompts and "Gardeners on X like rubber trays." in world.chatgpt.prompts[0]


def test_a_failed_x_send_fails_the_task_with_its_reason_and_nothing_takes_over():
    conn, lines, clock, hook = log.init_db(":memory:"), [], Clock(), Webhook(fail=("do",))
    chat, worker = Chat("never"), Scripted("never")
    code = cli.cmd_route(X, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=fake_label(jev("x_social_pulse")), post=hook.post, worker=worker, chatgpt=chat,
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=True, available=Gate(), out=lines.append)
    task = log.recent_tasks(conn)[0]
    calls = log.calls_for(conn, task["task_id"])
    assert code == 1 and task["status"] == "failed" and "500" in (task["result"] or "")
    assert [(c["agent"], c["status"]) for c in calls] == [("grok", "failed")]
    assert chat.prompts == [] and worker.prompts == [] and not any("took over" in line for line in lines)


def test_the_takeover_never_picks_up_grok_bots_x_call(tmp_path):
    conn = log.init_db(":memory:")
    log.add_task(conn, "t", X, "cli", jev("x_social_pulse"))
    log.set_route(conn, "t", agents=ROSTER.names, agent="grok", route_reason="best", skill="x_social_pulse",
                  skill_source="jev", checker="chatgpt", check_state="pending")
    log.add_call(conn, "t", "t", "do", "grok", status="failed", text="webhook answered 502")
    task, calls = log.get_task(conn, "t"), log.calls_for(conn, "t")
    plan = takeover.decide(task, calls, calls[-1], available=lambda a: availability.YES, skills=ROSTER.skills)
    assert not plan.ok and plan.reason == "Grok's x_social_pulse call is never taken over: x_social_pulse is Grok Bot's alone"
    assert not plan.nobody   # a rule's refusal: nothing is said in Terminal


def test_a_splits_x_piece_comes_back_without_grok_bot_as_a_make_media_piece_does():
    for skill in ("x_social_pulse", "make_media"):
        assert cli._piece_route(jev(skill), ROSTER, available=_table({"grok"})) == (
            f"comes back: {skill} needs Grok Bot: {WHY['grok']}")
    assert cli._piece_route(jev("meta_social_trends"), ROSTER, available=_table({"grok"})) == (
        "meta_social_trends · chatgpt / claude")
