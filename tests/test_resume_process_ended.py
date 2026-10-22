"""Build brief 22, B3 (rules v2.31, Resume, "A process-ended stop"; decision 3 and the owner's Q1 (b) of 20 Oct): a
process-ended stop is resumed by the same agent, Cursor included, once per task: the call that was running is made again
with the inputs it had (the saved memory block; the handoff read fresh, as every resume reads it), then the task goes on.
Unlike a plan-limit stop, it may be resumed on `versus`, `vote` and an override too, since no substitute is involved;
the fallback's own redo is never resumed (it writes no note, so its process ending changes nothing). A Cursor stop on a
used-up pool is still never resumed. Fakes only; every value here is fake."""
import json

import pytest

from router import __main__ as cli
from router import checking, cursor_worker, log, presets, relay, resume, state
from tests.helpers import fake_label, shipped_roster
from tests.test_json_actions import FAKE_ENV, World, jev
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_relay import CONFIG, Chat

ROSTER = shipped_roster()
LOADED = presets.load_presets(ROSTER, tuple(cli.SENDERS), relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
PE = state.PROCESS_ENDED
ENDED = "process ended: the sr process (pid 4321) ended while this call was running"


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _routed(conn, tid="sr-1", agent="claude", checker="chatgpt", reason="best", skill="writing", **kw):
    log.add_task(conn, tid, "write two lines about trays", "cli", jev(skill), **kw)
    log.set_route(conn, tid, agents=ROSTER.names, agent=agent, route_reason=reason, skill=skill,
                  skill_source="jev", checker=checker, check_state="pending" if checker else "unchecked")


def _ended(conn, tid, call_id, kind, agent, stage=None, role=None, memory=None):
    """What `sr check` writes for a dead run (B2): the running call failed with process_ended, the task failed."""
    log.add_call(conn, call_id, tid, kind, agent, status="failed", text=ENDED, stage=stage, role=role, reason_code=PE,
                 memory=memory)
    log.set_failed(conn, tid, "stopped: process ended", failed_stage=stage if kind in log.STAGE_KINDS else None)


def _decide(conn, tid="sr-1", preset=None, live=ROSTER.live):
    return resume.decide(log.get_task(conn, tid), log.calls_for(conn, tid), live=live, preset=preset)


# ---------- the decision ----------

def test_a_process_ended_first_call_is_made_again_by_the_same_agent(conn):
    _routed(conn)
    _ended(conn, "sr-1", "sr-1", "do", "claude")
    plan = _decide(conn)
    assert (plan.ok, plan.substitute, plan.agent, plan.checker, plan.kind, plan.call_id) == (
        True, "claude", "claude", "chatgpt", "do", "sr-1-resume")
    assert not plan.swapped


def test_a_process_ended_check_round_is_made_again_by_the_same_checker(conn):
    _routed(conn)
    log.add_call(conn, "sr-1", "sr-1", "do", "claude", status="done", text="two lines")
    _ended(conn, "sr-1", "sr-1-c1", "check", "chatgpt")
    plan = _decide(conn)
    assert (plan.ok, plan.substitute, plan.agent, plan.checker, plan.kind, plan.check_state) == (
        True, "chatgpt", "claude", "chatgpt", "check", "pending")


def test_an_override_a_versus_and_a_vote_may_be_resumed_after_a_process_ended(conn):
    _routed(conn, reason="override")
    _ended(conn, "sr-1", "sr-1", "do", "claude")
    assert _decide(conn).ok
    for name, stage, agent, role in (("versus", 2, "cursor", "build"), ("vote", 1, "claude", "vote")):
        tid = f"sr-{name}"
        preset, _ = presets.for_task({"mode": "relay", "preset": name, "slots": None}, LOADED)
        if name == "versus":
            preset, _ = presets.slot_refusals(preset, [("b", "cursor")], ROSTER)
        log.add_task(conn, tid, "t", "cli", {"status": "not_asked", "tokens": 0}, mode="relay", preset=name,
                     slots=presets.slot_map(preset))
        log.set_route(conn, tid, agents=ROSTER.names, agent=preset.doer, route_reason="relay",
                      checker=preset.check_agent, check_state="pending")
        if stage > 1:
            log.add_call(conn, f"{tid}-s1", tid, "stage", "claude", status="done", text="candidate a", stage=1, role="build")
        _ended(conn, tid, f"{tid}-s{stage}", "stage", agent, stage=stage, role=role)
        plan = _decide(conn, tid, preset=preset)
        assert (plan.ok, plan.substitute, plan.kind, plan.stage, plan.role) == (True, agent, "stage", stage, role), name


def test_a_cursor_stop_that_was_not_a_process_ending_is_still_never_resumed(conn):
    _routed(conn, agent="cursor", reason="override")
    log.add_call(conn, "sr-1", "sr-1", "do", "cursor", status="failed", text="pool used up")
    log.set_failed(conn, "sr-1", "pool used up")
    plan = _decide(conn)
    assert not plan.ok and "cursor is never resumed" in plan.reason


def test_one_resume_per_task_holds_and_the_agent_must_be_live(conn):
    _routed(conn)
    log.add_call(conn, "sr-1", "sr-1", "do", "claude", status="failed", text="limit", reason_code="plan_limit")
    log.add_call(conn, "sr-1-resume", "sr-1", "do", "chatgpt", status="failed", text=ENDED, reason_code=PE,
                 resume_of="sr-1")
    log.set_failed(conn, "sr-1", "stopped: process ended")
    plan = _decide(conn)
    assert (plan.ok, plan.code) == (False, "already_used")
    _routed(conn, "sr-2")
    _ended(conn, "sr-2", "sr-2", "do", "claude")
    plan = _decide(conn, "sr-2", live=("chatgpt",))
    assert (plan.ok, plan.code) == (False, "not_live")


def test_a_later_round_of_a_task_that_fell_back_may_be_resumed_but_not_a_stopped_redo(conn):
    _routed(conn)
    log.add_call(conn, "sr-1", "sr-1", "do", "claude", status="done", text="draft")
    log.add_call(conn, "sr-1-c1", "sr-1", "check", "chatgpt", status="done", text="FIX\n1. a", verdict="FIX")
    log.add_call(conn, "sr-1-f1", "sr-1", "fix", "claude", status="done", text="draft two")
    log.add_call(conn, "sr-1-c2", "sr-1", "recheck", "chatgpt", status="done", text="FIX\n1. b", verdict="FIX")
    log.add_call(conn, "sr-1-fb1", "sr-1", "do", "chatgpt", status="done", text="the redo", fallback_of="sr-1")
    _ended(conn, "sr-1", "sr-1-fb1-c1", "check", "claude")
    plan = _decide(conn)
    assert (plan.ok, plan.substitute, plan.kind) == (True, "claude", "check")
    log.add_call(conn, "sr-2x", "sr-1", "do", "chatgpt", status="failed", text=ENDED, reason_code=PE, fallback_of="sr-1")
    assert not _decide(conn).ok  # a stopped redo itself: never resumed


def test_the_stop_line_names_the_same_agent(conn):
    _routed(conn)
    _ended(conn, "sr-1", "sr-1", "do", "claude")
    task, calls = log.get_task(conn, "sr-1"), log.calls_for(conn, "sr-1")
    assert resume.stop_line(task, calls, live=ROSTER.live) == (
        "Process ended on claude. Run: sr resume 1  (claude makes the call again)")
    assert resume.describe(task, _decide(conn))[:2] == [
        "Resuming #1 sr-1: the first call by claude stopped when its process ended.",
        "claude makes it again, with what it was sent."]


def test_the_json_offers_the_resume_with_the_same_agent(conn):
    from router import jsonview
    _routed(conn)
    _ended(conn, "sr-1", "sr-1", "do", "claude")
    view = jsonview.task_view(conn, log.get_task(conn, "sr-1"), live=ROSTER.live, loaded=LOADED)
    assert (view["outcome"], view["resume"]["ok"], view["resume"]["substitute"]) == ("process_ended", True, "claude")


# ---------- the command ----------

def _resume(conn, tid="sr-1", *, worker=None, chatgpt=None, cursor=None, cursor_ready=None, hindsight=None):
    lines, clock, hook = [], Clock(), Webhook()
    row = log.get_task(conn, tid)
    code = cli.cmd_resume([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                          settings_paths=[], post=hook.post, worker=worker or Scripted(), chatgpt=chatgpt or Chat(),
                          codex_login=lambda: True, cursor=cursor, cursor_ready=cursor_ready, fetch=hook.fetch,
                          close=hook.close, sleep=clock.sleep, clock=clock, wait=True, hindsight=hindsight,
                          out=lines.append)
    return code, "\n".join(lines)


def test_sr_resume_makes_the_first_call_again_with_what_it_was_sent_then_goes_on(conn):
    _routed(conn)
    expected = cli._plan_call(log.get_task(conn, "sr-1"), checking.Step("do"), (), searching=None)[3]
    _ended(conn, "sr-1", "sr-1", "do", "claude")
    worker, chatgpt = Scripted("two lines"), Chat("PASS")
    code, out = _resume(conn, worker=worker, chatgpt=chatgpt)
    assert code == 0 and worker.prompts == [expected]
    row = log.get_task(conn, "sr-1")
    assert (row["status"], row["check_state"], row["agent"], row["checker"]) == ("done", "passed", "claude", "chatgpt")
    assert [(c["call_id"], c["agent"], c["status"], c["resume_of"]) for c in log.calls_for(conn, "sr-1")] == [
        ("sr-1", "claude", "failed", None), ("sr-1-resume", "claude", "done", "sr-1"), ("sr-1-c1", "chatgpt", "done", None)]
    assert "Resuming #1 sr-1: the first call by claude stopped when its process ended." in out
    code, out = _resume(conn)
    assert code == 2 and "it is done" in out  # one resume per task: nothing left to resume
    lines = []
    cli.cmd_show(conn=conn, words=["1"], roster=ROSTER, out=lines.append)
    assert "Resumed: the first call by claude — replaces call sr-1 (claude stopped when its process ended)." in "\n".join(lines)


class _NoRecall:
    """A memory store that must not be asked: a resume reuses the stopped call's saved block."""

    def recall(self, *a, **k):
        raise AssertionError("a resume never recalls afresh")

    def retain(self, item, timeout=20):  # the delivered result is stored, as any delivery's
        return {"success": True}


def test_sr_resume_sends_the_saved_memory_block_of_the_stopped_call(conn):
    from router import memory
    _routed(conn, chat="trays")
    block = memory.render("chat:trays", [memory.Entry(7, "2026-10-19", "writing", "claude", None, "an earlier result")], 2000)
    _ended(conn, "sr-1", "sr-1", "do", "claude", memory={"tag": "chat:trays", "found": 1, "sent": 1, "text": block})
    worker = Scripted("two lines")
    code, out = _resume(conn, worker=worker, chatgpt=Chat("PASS"), hindsight=_NoRecall())
    assert code == 0 and "an earlier result" in worker.prompts[0] and block in worker.prompts[0]
    assert log.call_memory_of(log.get_call(conn, "sr-1-resume"))["from"] == "sr-1"


class FakeCursor:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def __call__(self, prompt, call_id=None):
        self.prompts.append((prompt, call_id))
        text = self.replies.pop(0)
        return cursor_worker.CursorAnswer(text, {"asked": "grok-4.7-high", "model": "Grok 4.7 256K High",
                                                 "tool_events": 0, "tools": []})


def test_sr_resume_makes_a_versus_cursor_stage_again_with_cursor_and_the_chain_goes_on(conn):
    preset, _ = presets.slot_refusals(LOADED.presets["versus"], [("b", "cursor")], ROSTER)
    log.add_task(conn, "sr-v", "write is_even", "cli", {"status": "not_asked", "tokens": 0}, mode="relay",
                 preset="versus", slots=presets.slot_map(preset))
    log.set_route(conn, "sr-v", agents=ROSTER.names, agent=preset.doer, route_reason="relay", checker=preset.check_agent,
                  check_state="pending")
    log.add_call(conn, "sr-v-s1", "sr-v", "stage", "claude", status="done", text="def is_even(n): return n % 2 == 0",
                 stage=1, role="build")
    _ended(conn, "sr-v", "sr-v-s2", "stage", "cursor", stage=2, role="build")
    review = "## Verdict\npass\n\n## Notes\n- fine"
    cursor = FakeCursor("def is_even(n): return not n % 2", review)
    code, out = _resume(conn, "sr-v", worker=Scripted(review), cursor=cursor,
                        cursor_ready=lambda: cursor_worker.Readiness((True, None)))
    assert [call_id for _, call_id in cursor.prompts] == ["sr-v-s2-resume", "sr-v-s3"]
    assert all(prompt.startswith(cursor_worker.opener()) for prompt, _ in cursor.prompts)
    row = log.get_task(conn, "sr-v")
    assert relay.awaiting_pick(row) and log.get_call(conn, "sr-v-s2-resume")["resume_of"] == "sr-v-s2"


def test_sr_resume_refuses_a_cursor_stage_when_cursor_is_not_ready(conn):
    preset, _ = presets.slot_refusals(LOADED.presets["versus"], [("b", "cursor")], ROSTER)
    log.add_task(conn, "sr-v", "write is_even", "cli", {"status": "not_asked", "tokens": 0}, mode="relay",
                 preset="versus", slots=presets.slot_map(preset))
    log.set_route(conn, "sr-v", agents=ROSTER.names, agent=preset.doer, route_reason="relay", checker=preset.check_agent,
                  check_state="pending")
    log.add_call(conn, "sr-v-s1", "sr-v", "stage", "claude", status="done", text="a", stage=1, role="build")
    _ended(conn, "sr-v", "sr-v-s2", "stage", "cursor", stage=2, role="build")
    cursor = FakeCursor()
    code, out = _resume(conn, "sr-v", cursor=cursor,
                        cursor_ready=lambda: cursor_worker.Readiness((False, "cursor: not signed in (agent login)"), "signed_out"))
    assert code == 2 and cursor.prompts == [] and "not signed in" in out
    assert log.get_task(conn, "sr-v")["status"] == "failed"


# ---------- end to end: a dead run, sr check, sr resume ----------

def test_a_crashed_first_call_is_marked_by_sr_check_and_made_again_by_sr_resume(monkeypatch, tmp_path, capsys):
    world = World(monkeypatch, tmp_path, capsys)
    from router import runs
    conn = log.init_db(cli.DB_PATH)
    _routed(conn, run=(4321, "2026-10-20T11:00:00+00:00"))
    conn.close()
    runs.write_note(cli.DB_PATH.parent / "run", "sr-1", {"call_id": "sr-1", "kind": "do", "agent": "claude",
                                                         "stage": None, "role": None, "search": None, "context": None,
                                                         "memory": None, "pid": 4321,
                                                         "started": "2026-10-20T11:00:00+00:00"})
    world.run("check")
    shown = json.loads(world.run("show", "1", "--json")[1])
    assert (shown["outcome"], shown["resume"]["ok"], shown["resume"]["substitute"]) == ("process_ended", True, "claude")
    world.worker, world.chatgpt = Scripted("two lines"), Chat("PASS")
    found = world.json("resume", "1")
    assert (found["exit"], found["status"], found["outcome"]) == (0, "done", "passed")
    assert world.json("resume", "1")["reason_code"] == "not_resumable"  # done: one resume per task, nothing stopped


def test_the_done_refusal_names_both_stops(conn):
    """The owner's F addition (deviation 6): a done task's refusal names both resumable stops."""
    _routed(conn)
    log.add_call(conn, "sr-1", "sr-1", "do", "claude", status="done", text="two lines")
    log.set_done(conn, "sr-1", "two lines", check_state="passed")
    plan = _decide(conn)
    assert (plan.ok, plan.reason) == (
        False, "it is done; only a task stopped by a plan limit or by a process that ended can be resumed")


@pytest.mark.parametrize("status", ["cancelled", "timed_out", "returned"])
def test_the_other_refusals_name_both_stops(conn, status):
    """The owner's go before the switch-over (open issue 2): a cancelled, timed-out or returned task's refusal names both
    resumable stops, as the done one does (F1)."""
    _routed(conn)
    if status == "cancelled":
        log.set_cancelled(conn, "sr-1")
    elif status == "timed_out":
        log.set_sent(conn, "sr-1", "uuid")
        log._move(conn, "sr-1", ("sent",), "timed_out")
    else:
        log.set_returned(conn, "sr-1", "returned: no agent can do it", reason_code="not_routed")
    plan = _decide(conn)
    assert (plan.ok, plan.reason) == (
        False, f"it is {status}; only a task stopped by a plan limit or by a process that ended can be resumed")
