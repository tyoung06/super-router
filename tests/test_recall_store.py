"""Rules v2.29 (the owner, 2026-10-20, after live #103, amended before the merge): a tagged recall task never calls an agent
without its memory. Only a call that does a fresh recall checks the store: the first call. When its recall finds the
store unreachable (or there is no store), the task comes back `returned`, `memory unavailable (the store could not be
started): nothing to recall from`, before any agent call (brief 23, decision 5: with `memory: off` in settings the store
is never started, so the words say memory is off in settings). A call that reuses a saved block (a re-ask, a check, fix or re-check round, a
fallback, a resume) uses that block without asking the store, so a store that went down after the first call changes
nothing; it is held back only when the saved block was itself unavailable (live #103's shape: its first call ran
without the block before this rule): the round comes back, a fallback or a resume is refused, with the same reason and
one more line, and neither is used up. Other skills run without the block as before (decision 12); an untagged override
runs as the Overrides section says. Fake agents, a fake store; every value here is fake."""
import json

import pytest

from router import __main__ as cli
from router import log, settings
from tests.fake_hindsight import FakeHindsight
from tests.helpers import ALL_AGENTS
from tests.test_chat_intake import _route
from tests.test_collab import LOADED
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_memory_block import _block, _done, _entry
from tests.test_relay import CONFIG, ROSTER, SECRET, Chat
from tests.test_resume_run import claude_limit
from tests.test_route_v2 import ok

RECALL, WRITING = ok("recall"), ok("writing")
QUESTION = "what did we decide about the tray last time"
BACK = "memory unavailable (the store could not be started): nothing to recall from"
REASON = "returned: " + BACK
REDO_LINE = ("Its first call ran without the memory block, so this one would too: send the task again as a new task; the "
             "router starts memory when that task needs it.")
# brief 23 (decision 5, the owner's change 1): with `memory: off` the store is never started, so the words say so
BACK_OFF = "memory unavailable (memory is off in settings): nothing to recall from"
REASON_OFF = "returned: " + BACK_OFF
REDO_LINE_OFF = ("Its first call ran without the memory block, so this one would too: memory is off in settings, so the "
                 "router never starts the store.")
BLIND = {"reason": "ConnectionError (POST /v1/default/banks/super-router/memories/recall)", "tag": "chat:tray", "unavailable": True}


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _offline():
    return FakeHindsight(online=False)


def _round_back(task_id, what, agent):
    return f"{task_id} came back to you: {BACK}. The {what} by {agent} was not sent; nothing was delivered."


def _blind_first_call(conn, task_id):
    """Make the first call's saved memory record unavailable, as on a task that ran before rules v2.29 (live #103: the
    store was down at its first call and the call went without the block). Every other part of the row is the real one."""
    conn.execute("UPDATE calls SET memory = ? WHERE call_id = ?", (json.dumps(BLIND), task_id))
    conn.commit()


class Flipping(Scripted):
    """A fake doer that takes the store offline as it answers: the next round finds it down."""

    def __init__(self, fake, *replies):
        super().__init__(*replies)
        self.fake = fake

    def __call__(self, prompt):
        self.fake.online = False
        return super().__call__(prompt)


def _check(conn, *, worker=None, chatgpt=None, hindsight=None):
    lines, hook = [], Webhook()
    code = cli.cmd_check(conn=conn, config=CONFIG, environ={}, settings_paths=[], post=hook.post, worker=worker or Scripted(),
                         chatgpt=chatgpt or Chat("PASS"), codex_login=lambda: True, fetch=hook.fetch, close=hook.close,
                         roster=ROSTER, hindsight=hindsight, out=lines.append)
    return code, "\n".join(lines)


def _fallback(conn, row, *, worker=None, chatgpt=None, hindsight=None):
    lines, clock, hook = [], Clock(), Webhook()
    code = cli.cmd_fallback([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[],
                            post=hook.post, worker=worker or Scripted("PASS"), chatgpt=chatgpt or Chat("REDO"), codex_login=lambda: True,
                            fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True, out=lines.append,
                            hindsight=hindsight)
    return code, "\n".join(lines), log.get_task(conn, row["task_id"])


def _resume(conn, row, *, worker=None, chatgpt=None, hindsight=None):
    lines, clock, hook = [], Clock(), Webhook()
    code = cli.cmd_resume([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[],
                          post=hook.post, worker=worker or Scripted("PASS"), chatgpt=chatgpt or Chat("resumed"), codex_login=lambda: True,
                          fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True, out=lines.append,
                          hindsight=hindsight)
    return code, "\n".join(lines), log.get_task(conn, row["task_id"])


def _show(conn, row):
    lines = []
    cli.cmd_show(conn=conn, words=[str(row["n"])], secrets=[SECRET], out=lines.append)
    return "\n".join(lines)


def _failed_recall_task(conn, memory_record, task_id="sr-103"):
    """A recall task that failed its check twice, its calls carrying `memory_record` (live #103's shape when the record
    says unavailable: the doer ran without the block before this rule)."""
    log.add_task(conn, task_id, QUESTION, "cli", {"status": "ok", "label": "recall", "confidence": 1.0, "tokens": 867}, chat="tray")
    log.set_route(conn, task_id, agents=ALL_AGENTS, agent="claude", route_reason="best", skill="recall", checker="chatgpt",
                  check_state="pending")
    reused = {**memory_record, "from": task_id}
    log.add_call(conn, task_id, task_id, "do", "claude", status="done", text="I can't find a decision.", memory=memory_record)
    log.add_call(conn, f"{task_id}-c1", task_id, "check", "chatgpt", status="done", text="FIX\n1. answer it", verdict="FIX", memory=reused)
    log.add_call(conn, f"{task_id}-f1", task_id, "fix", "claude", status="done", text="I still can't.", memory=reused)
    log.add_call(conn, f"{task_id}-c2", task_id, "recheck", "chatgpt", status="done", text="FIX\n1. answer it", verdict="FIX", memory=reused)
    log.set_done(conn, task_id, "I still can't.", check_state="failed", check_note="not passed after one fix round")
    return log.get_task(conn, task_id)


# ---------- sr route: the first call does a fresh recall, so it checks the store ----------

def test_route_a_tagged_recall_task_comes_back_when_the_store_is_offline(conn):
    _done(conn, "sr-1", "first task", "we decided rubber")
    fake, worker, chat = _offline(), Scripted("never"), Chat("never")
    code, out, row, _ = _route(conn, QUESTION, chat="tray", jev=RECALL, worker=worker, chatgpt=chat, hindsight=fake.client)
    assert code == 4
    assert (row["status"], row["route_reason"], row["check_note"], row["skill"], row["agent"], row["checker"], row["result"]) == (
        "returned", REASON, BACK, "recall", "claude", "chatgpt", None)
    assert worker.prompts == [] and chat.prompts == [] and log.calls_for(conn, row["task_id"]) == [] and fake.retains == []
    assert f"{row['task_id']} came back to you: {BACK}. Nothing was sent to an agent." in out
    assert "memory: unavailable" not in out and "sr fallback" not in out and REDO_LINE not in out  # one line says it
    assert fake.health_calls == 0 and len(fake.recalls) == 1  # the fresh recall is the check; no separate ping


def test_route_a_tagged_recall_task_comes_back_without_a_store_at_all(conn):
    worker = Scripted("never")
    code, out, row, _ = _route(conn, QUESTION, chat="tray", jev=RECALL, worker=worker, chatgpt=Chat("never"), hindsight=None)
    assert code == 4 and row["status"] == "returned" and row["route_reason"] == REASON and worker.prompts == []


def test_route_a_tagged_recall_task_runs_when_the_store_answers(conn):
    one = _done(conn, "sr-1", "first task", "we decided rubber")
    fake, worker, chat = FakeHindsight(results=[]), Scripted("Last time: rubber."), Chat("PASS")
    code, out, row, _ = _route(conn, QUESTION, chat="tray", jev=RECALL, worker=worker, chatgpt=chat, hindsight=fake.client)
    assert code == 0 and row["status"] == "done" and row["check_state"] == "passed"
    assert worker.prompts == [f"{QUESTION}\n\n{_block([_entry(one)])}"]
    assert fake.health_calls == 0 and len(fake.recalls) == 1  # the check round reuses the saved block: no ping, no recall


def test_a_writing_task_still_runs_without_the_store_as_decision_12_says(conn):
    _done(conn, "sr-1", "first task", "first result")
    worker = Scripted("two lines")
    code, out, row, _ = _route(conn, "write two lines about trays", chat="tray", jev=WRITING, worker=worker, chatgpt=Chat("PASS"),
                               hindsight=_offline().client)
    assert code == 0 and row["status"] == "done" and worker.prompts == ["write two lines about trays"]
    assert out.count("memory: unavailable; this task runs without its memory block") == 1


def test_an_untagged_override_recall_task_runs_as_the_overrides_section_says(conn):
    worker = Scripted("I have nothing to recall from.")
    code, out, row, _ = _route(conn, "@claude " + QUESTION, jev=RECALL, worker=worker, chatgpt=Chat("PASS"), hindsight=_offline().client)
    assert code == 0 and (row["status"], row["route_reason"], row["agent"]) == ("done", "override", "claude") and worker.prompts == [QUESTION]


def test_a_tagged_override_recall_task_comes_back_too(conn):
    worker = Scripted("never")
    code, out, row, _ = _route(conn, "@claude " + QUESTION, chat="tray", jev=RECALL, worker=worker, chatgpt=Chat("never"),
                               hindsight=_offline().client)
    assert code == 4 and row["status"] == "returned" and row["route_reason"] == REASON and worker.prompts == []


# ---------- the rounds reuse the saved block: a store that went down after the first call changes nothing ----------

def test_the_check_round_in_routes_loop_runs_with_the_saved_block_when_the_store_went_down(conn):
    one = _done(conn, "sr-1", "first task", "we decided rubber")
    fake = FakeHindsight(results=[])
    worker, chat = Flipping(fake, "Last time: rubber."), Chat("PASS")
    code, out, row, _ = _route(conn, QUESTION, chat="tray", jev=RECALL, worker=worker, chatgpt=chat, hindsight=fake.client)
    assert code == 0 and (row["status"], row["check_state"]) == ("done", "passed")
    block = _block([_entry(one)])
    assert worker.prompts == [f"{QUESTION}\n\n{block}"] and chat.prompts[0].endswith("\n\n" + block)
    assert fake.health_calls == 0 and BACK not in out


def test_sr_check_runs_the_check_round_with_the_saved_block_when_the_store_is_offline(conn):
    one = _done(conn, "sr-1", "first task", "we decided rubber")
    code, out, row, _ = _route(conn, QUESTION, chat="tray", jev=RECALL, worker=Scripted("Last time: rubber."),
                               chatgpt=Chat(KeyboardInterrupt), hindsight=FakeHindsight(results=[]).client)  # Ctrl+C at the check
    assert code == 130 and row["status"] == "queued" and [c["kind"] for c in log.calls_for(conn, row["task_id"])] == ["do"]
    off, chat = _offline(), Chat("PASS")
    code, out = _check(conn, chatgpt=chat, hindsight=off.client)
    row = log.get_task(conn, row["task_id"])
    assert (row["status"], row["check_state"]) == ("done", "passed")
    assert len(chat.prompts) == 1 and chat.prompts[0].endswith("\n\n" + _block([_entry(one)]))
    assert off.health_calls == 0 and BACK not in out


def test_sr_check_runs_the_fix_round_with_the_saved_block_when_the_store_is_offline(conn):
    one = _done(conn, "sr-1", "first task", "we decided rubber")
    code, out, row, _ = _route(conn, QUESTION, chat="tray", jev=RECALL, worker=Scripted("FIRST", KeyboardInterrupt),
                               chatgpt=Chat("FIX\n1. name the decision"), hindsight=FakeHindsight(results=[]).client)  # Ctrl+C at the fix
    assert code == 130 and row["status"] == "queued" and [c["kind"] for c in log.calls_for(conn, row["task_id"])] == ["do", "check"]
    off, worker = _offline(), Scripted("FIXED")
    code, out = _check(conn, worker=worker, chatgpt=Chat("PASS"), hindsight=off.client)
    row = log.get_task(conn, row["task_id"])
    assert (row["status"], row["check_state"]) == ("done", "fixed")
    assert worker.prompts[0].endswith("\n\n" + _block([_entry(one)])) and off.health_calls == 0 and BACK not in out


def test_sr_check_runs_the_recheck_round_with_the_saved_block_when_the_store_is_offline(conn):
    one = _done(conn, "sr-1", "first task", "we decided rubber")
    code, out, row, _ = _route(conn, QUESTION, chat="tray", jev=RECALL, worker=Scripted("FIRST", "FIXED"),
                               chatgpt=Chat("FIX\n1. name the decision", KeyboardInterrupt),
                               hindsight=FakeHindsight(results=[]).client)  # Ctrl+C at the re-check
    assert code == 130 and [c["kind"] for c in log.calls_for(conn, row["task_id"])] == ["do", "check", "fix"]
    off, chat = _offline(), Chat("PASS")
    code, out = _check(conn, chatgpt=chat, hindsight=off.client)
    row = log.get_task(conn, row["task_id"])
    assert (row["status"], row["check_state"]) == ("done", "fixed")
    assert chat.prompts[0].endswith("\n\n" + _block([_entry(one)])) and off.health_calls == 0 and BACK not in out


def test_sr_check_runs_the_round_when_the_store_answers(conn):
    _done(conn, "sr-1", "first task", "we decided rubber")
    fake = FakeHindsight(results=[])
    code, out, row, _ = _route(conn, QUESTION, chat="tray", jev=RECALL, worker=Scripted("Last time: rubber."),
                               chatgpt=Chat(KeyboardInterrupt), hindsight=fake.client)
    chat = Chat("PASS")
    code, out = _check(conn, chatgpt=chat, hindsight=fake.client)
    row = log.get_task(conn, row["task_id"])
    assert row["status"] == "done" and row["check_state"] == "passed" and len(chat.prompts) == 1


def test_a_round_whose_saved_block_was_unavailable_comes_back_even_with_the_store_up(conn):
    _done(conn, "sr-1", "first task", "we decided rubber")
    fake = FakeHindsight(results=[])
    code, out, row, _ = _route(conn, QUESTION, chat="tray", jev=RECALL, worker=Scripted("I can't find a decision."),
                               chatgpt=Chat(KeyboardInterrupt), hindsight=fake.client)  # Ctrl+C at the check
    assert code == 130 and row["status"] == "queued"
    _blind_first_call(conn, row["task_id"])
    chat = Chat("PASS")
    code, out = _check(conn, chatgpt=chat, hindsight=fake.client)
    row = log.get_task(conn, row["task_id"])
    assert (row["status"], row["route_reason"], row["check_note"], row["result"]) == ("returned", REASON, BACK, None)
    calls = log.calls_for(conn, row["task_id"])
    assert chat.prompts == [] and [c["kind"] for c in calls] == ["do"] and calls[0]["text"] == "I can't find a decision."
    assert _round_back(row["task_id"], "check", "chatgpt") in out and REDO_LINE in out
    assert fake.health_calls == 0 and "sr fallback" not in out


def test_sr_show_says_the_earlier_calls_stay_on_a_round_come_back_and_nothing_sent_on_a_first_call_one(conn):
    code, out, row, _ = _route(conn, QUESTION, chat="tray", jev=RECALL, worker=Scripted("I can't find a decision."),
                               chatgpt=Chat(KeyboardInterrupt), hindsight=FakeHindsight(results=[]).client)
    _blind_first_call(conn, row["task_id"])
    code, out = _check(conn, hindsight=FakeHindsight(results=[]).client)
    assert f"(came back to you: {BACK}. Its earlier calls stay in the log; nothing was delivered.)" in _show(conn, row)
    code, out, row, _ = _route(conn, QUESTION, chat="tray", jev=RECALL, worker=Scripted("never"), hindsight=_offline().client)
    assert code == 4 and f"(came back to you: {BACK}. Nothing was sent to an agent.)" in _show(conn, row)


# ---------- sr fallback ----------

def test_sr_fallback_runs_with_the_saved_block_when_the_store_is_offline(conn):
    one = _done(conn, "sr-1", "first task", "we decided rubber")
    code, out, row, _ = _route(conn, QUESTION, chat="tray", jev=RECALL, worker=Scripted("FIRST", "FIXED"), chatgpt=Chat("FIX\n1. x", "FIX\n1. y"),
                               hindsight=FakeHindsight(results=[]).client)
    assert row["check_state"] == "failed"
    off, redo = _offline(), Chat("REDO")
    code, out, after = _fallback(conn, row, chatgpt=redo, hindsight=off.client)
    assert code == 0, out
    assert len(redo.prompts) == 1 and redo.prompts[0].endswith("\n\n" + _block([_entry(one)]))
    assert log.get_call(conn, f"{row['task_id']}-fb1") is not None and off.health_calls == 0 and BACK not in out


def test_sr_fallback_of_a_task_whose_block_was_unavailable_is_refused_even_with_the_store_up(conn):
    row = _failed_recall_task(conn, BLIND)
    fake, redo = FakeHindsight(results=[]), Chat("REDO")
    code, out, after = _fallback(conn, row, chatgpt=redo, hindsight=fake.client)
    assert code == 2 and f"Refused: #{row['n']} can't fall back: {BACK}. Nothing was logged or sent." in out and REDO_LINE in out
    assert redo.prompts == [] and (after["status"], after["check_state"]) == ("done", "failed")  # nothing changed
    assert log.get_call(conn, f"{row['task_id']}-fb1") is None and fake.health_calls == 0


def test_sr_fallback_of_a_writing_task_runs_without_the_store(conn):
    _done(conn, "sr-1", "first task", "first result")
    code, out, row, _ = _route(conn, "write two lines about trays", chat="tray", jev=WRITING, worker=Scripted("FIRST", "FIXED"),
                               chatgpt=Chat("FIX\n1. x", "FIX\n1. y"), hindsight=FakeHindsight(results=[]).client)
    assert row["check_state"] == "failed"
    redo = Chat("REDO")
    code, out, after = _fallback(conn, row, chatgpt=redo, hindsight=_offline().client)
    assert code == 0, out
    assert len(redo.prompts) == 1


# ---------- sr resume (covered: the same rule) ----------

def test_sr_resume_runs_with_the_saved_block_when_the_store_is_offline(conn):
    one = _done(conn, "sr-1", "first task", "we decided rubber")
    code, out, row, _ = _route(conn, QUESTION, chat="tray", jev=RECALL, worker=Scripted(claude_limit()),
                               hindsight=FakeHindsight(results=[]).client)
    assert "sr resume" in out, out
    off, chat = _offline(), Chat("resumed")
    code, out, after = _resume(conn, row, chatgpt=chat, hindsight=off.client)
    assert len(chat.prompts) == 1 and chat.prompts[0].endswith("\n\n" + _block([_entry(one)])), out
    assert off.health_calls == 0 and BACK not in out


def test_sr_resume_of_a_task_whose_block_was_unavailable_is_refused_even_with_the_store_up(conn):
    _done(conn, "sr-1", "first task", "we decided rubber")
    fake = FakeHindsight(results=[])
    code, out, row, _ = _route(conn, QUESTION, chat="tray", jev=RECALL, worker=Scripted(claude_limit()), hindsight=fake.client)
    assert "sr resume" in out, out
    _blind_first_call(conn, row["task_id"])
    chat = Chat("resumed")
    code, out, after = _resume(conn, row, chatgpt=chat, hindsight=fake.client)
    assert code == 2 and f"Refused: #{row['n']} can't be resumed: {BACK}. Nothing was logged or sent." in out and REDO_LINE in out
    assert chat.prompts == [] and after["status"] == row["status"] and fake.health_calls == 0  # nothing changed: still resumable


# ---------- brief 23 (decision 5, the owner's change 1): the recall words branch on the memory setting ----------

def _memory_off():
    settings.LOCAL_PATH.write_text(json.dumps({"memory": "off"}))  # conftest points LOCAL_PATH at a temp file


def test_with_memory_off_a_first_call_come_back_says_memory_is_off_in_settings(conn):
    _memory_off()
    assert settings.memory_mode() == "off"
    _done(conn, "sr-1", "first task", "we decided rubber")
    fake, worker = _offline(), Scripted("never")
    code, out, row, _ = _route(conn, QUESTION, chat="tray", jev=RECALL, worker=worker, chatgpt=Chat("never"), hindsight=fake.client)
    assert code == 4 and (row["status"], row["route_reason"], row["check_note"]) == ("returned", REASON_OFF, BACK_OFF)
    assert f"{row['task_id']} came back to you: {BACK_OFF}. Nothing was sent to an agent." in out
    assert worker.prompts == [] and "could not be started" not in out and "sr memory" not in out


def test_with_memory_off_a_round_come_back_and_its_redo_line_say_memory_is_off(conn):
    _memory_off()
    _done(conn, "sr-1", "first task", "we decided rubber")
    fake = FakeHindsight(results=[])
    code, out, row, _ = _route(conn, QUESTION, chat="tray", jev=RECALL, worker=Scripted("I can't find a decision."),
                               chatgpt=Chat(KeyboardInterrupt), hindsight=fake.client)  # Ctrl+C at the check
    _blind_first_call(conn, row["task_id"])
    code, out = _check(conn, chatgpt=Chat("PASS"), hindsight=fake.client)
    row = log.get_task(conn, row["task_id"])
    assert (row["status"], row["route_reason"], row["check_note"]) == ("returned", REASON_OFF, BACK_OFF)
    assert f"{row['task_id']} came back to you: {BACK_OFF}. The check by chatgpt was not sent; nothing was delivered." in out
    assert REDO_LINE_OFF in out and REDO_LINE not in out and "starts memory" not in out


def test_with_memory_off_the_fallback_and_resume_refusals_say_memory_is_off(conn):
    _memory_off()
    row = _failed_recall_task(conn, BLIND)
    code, out, after = _fallback(conn, row, chatgpt=Chat("REDO"), hindsight=FakeHindsight(results=[]).client)
    assert code == 2 and f"Refused: #{row['n']} can't fall back: {BACK_OFF}. Nothing was logged or sent." in out
    assert REDO_LINE_OFF in out and "could not be started" not in out
    _done(conn, "sr-1", "first task", "we decided rubber")
    fake = FakeHindsight(results=[])
    code, out, row, _ = _route(conn, QUESTION, chat="tray", jev=RECALL, worker=Scripted(claude_limit()), hindsight=fake.client)
    _blind_first_call(conn, row["task_id"])
    code, out, after = _resume(conn, row, chatgpt=Chat("resumed"), hindsight=fake.client)
    assert code == 2 and f"Refused: #{row['n']} can't be resumed: {BACK_OFF}. Nothing was logged or sent." in out
    assert REDO_LINE_OFF in out


def test_with_memory_auto_the_words_say_the_store_could_not_be_started(conn):
    assert settings.memory_mode() == "auto"  # the tracked default
    code, out, row, _ = _route(conn, QUESTION, chat="tray", jev=RECALL, worker=Scripted("never"), hindsight=_offline().client)
    assert code == 4 and row["check_note"] == BACK and "memory is off" not in out
    assert "sr memory" not in out
