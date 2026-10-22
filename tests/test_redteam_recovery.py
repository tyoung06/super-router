"""Build brief 16, phase D: resume, fallback and Grok's prompt limit on redteam (rules v2.23).
Resume: a stopped build or attack stage resumes as any stage, but the substitute for one of `build` / `attack` may
not be the agent in the other (an attacker never attacks its own build): refused before any call. A stopped revise
stage is refused (`revise stage can only be done by the agent that built stage 1`) and stage 1's result is unchecked.
The trap: after a stage-1 resume, stage 3 goes to the agent that built stage 1, never the slot's default.
Fallback: the `check` agent builds from the task and the attack list with the final fix list (never stage 1 or the
revision); the `build` agent checks with the attack list. Every value here is fake."""
import json

import pytest

from router import __main__ as cli
from router import checking, fallback, log, presets, relay, resume, settings
from router.claude_worker import WorkerError
from tests.test_redteam_chain import ATTACKS, BUILD, LOADED, REVISION, ROSTER, TASK, _relay, _rows
from tests.test_relay import CONFIG, Chat, Clock, RelayHook, Scripted

LIMIT = WorkerError("plan limit on claude: You've hit your session limit", code="plan_limit")


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _resume(conn, row, *, claude=(), chat=(), bodies=None):
    hook, worker, chatgpt, clock, lines = RelayHook(**(bodies or {})), Scripted(*claude), Chat(*chat), Clock(), []
    code = cli.cmd_resume([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                          settings_paths=[], post=hook.post, worker=worker, chatgpt=chatgpt, codex_login=lambda: True,
                          fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True,
                          out=lines.append)
    return code, "\n".join(lines), log.get_task(conn, row["task_id"]), worker, chatgpt, hook


# ---------- resume ----------

def test_on_the_default_slots_a_stage_1_stop_cannot_be_resumed_and_says_why(conn):
    code, out, row, *_ = _relay(conn, claude=[LIMIT], chat=[])
    assert (row["status"], row["failed_stage"]) == ("failed", 1)
    assert ("Plan limit on claude. Not resumable: chatgpt would build stage 1 and revise it at stage 3, but chatgpt "
            "attacks it at stage 2; an attacker does not attack its own build. Run it again") in out
    before = len(log.calls_for(conn, row["task_id"]))
    code, out, after, worker, chat, hook = _resume(conn, row, chat=["never"])
    assert code == 2 and "can't be resumed: chatgpt would build stage 1" in out
    assert chat.prompts == [] and worker.prompts == [] and len(log.calls_for(conn, row["task_id"])) == before
    assert after["status"] == "failed"


def test_a_stage_2_stop_whose_substitute_built_stage_1_cannot_be_resumed(conn):
    limit = WorkerError("plan limit on chatgpt: You've hit your usage limit", code="plan_limit")
    code, out, row, *_ = _relay(conn, claude=[BUILD], chat=[limit])
    assert row["failed_stage"] == 2
    plan = resume.decide(row, log.calls_for(conn, row["task_id"]), live=ROSTER.live,
                         preset=presets.for_task(row, LOADED)[0])
    assert not plan.ok and plan.reason == ("claude would attack stage 1, which claude built; an attacker does not "
                                           "attack its own build. Run it again")


def test_a_stopped_revise_stage_is_refused_and_stage_1_is_unchecked(conn):
    code, out, row, *_ = _relay(conn, claude=[BUILD, LIMIT], chat=[ATTACKS])
    assert (row["status"], row["failed_stage"], row["check_state"]) == ("failed", 3, "unchecked")
    assert row["check_note"] == ("revise stage 3 stopped on claude's plan limit; only claude, which built stage 1, can "
                                 "revise it; stage 1's result is unchecked")
    assert "Not resumable: revise stage can only be done by the agent that built stage 1" in out
    assert "Stage 1's result is unchecked." in out and BUILD in out and ATTACKS in out
    code, out, *_ = _resume(conn, row)
    assert code == 2 and "revise stage can only be done by the agent that built stage 1" in out


def test_the_trap_after_a_stage_1_resume_stage_3_goes_to_the_agent_that_built_stage_1(conn):
    # --attack grok leaves room: claude stops at stage 1, chatgpt builds; grok attacks; chatgpt must revise
    code, out, row, *_ = _relay(conn, claude=[LIMIT], chat=[], slots=[("attack", "grok")])
    plan = resume.decide(row, log.calls_for(conn, row["task_id"]), live=ROSTER.live,
                         preset=presets.for_task(row, LOADED)[0])
    assert plan.ok and (plan.substitute, plan.agent, plan.checker, plan.swapped) == ("chatgpt", "chatgpt", "claude", True)
    code, out, after, worker, chat, hook = _resume(conn, row, chat=[BUILD, REVISION], claude=["PASS"],
                                                   bodies={"s2": ATTACKS})
    assert code == 0, out
    assert [(r[1], r[3]) for r in _rows(conn, after)] == [(1, "claude"), (1, "chatgpt"), (2, "grok"), (3, "chatgpt"),
                                                          (None, "claude")]
    assert (after["agent"], after["checker"], after["check_state"]) == ("chatgpt", "claude", "passed")
    assert chat.prompts[1] == relay.revise_prompt(TASK, BUILD, against=ATTACKS, search=True)


def test_a_stopped_check_round_follows_the_existing_rule(conn):
    limit = WorkerError("plan limit on chatgpt: You've hit your usage limit", code="plan_limit")
    code, out, row, *_ = _relay(conn, claude=[BUILD, REVISION], chat=[ATTACKS, limit])
    assert (row["status"], row["check_state"]) == ("done", "unchecked")
    plan = resume.decide(row, log.calls_for(conn, row["task_id"]), live=ROSTER.live,
                         preset=presets.for_task(row, LOADED)[0])
    assert not plan.ok and plan.reason == "claude did the work, so it can't check it; the result stays unchecked"


# ---------- fallback ----------

def _double_fail(conn, slots=()):
    fixed = REVISION.replace("Change the budget", "Change it")
    code, out, row, worker, chat = _relay(conn, claude=[BUILD, REVISION, fixed], slots=slots,
                                          chat=[ATTACKS, "FIX\n1. Attack 1 is unanswered.", "FIX\n1. Attack 1 still open."])
    assert (row["status"], row["check_state"]) == ("done", "failed"), out
    return code, out, row


def _fallback(conn, row, *, claude=(), chat=()):
    hook, worker, chatgpt, clock, lines = RelayHook(), Scripted(*claude), Chat(*chat), Clock(), []
    code = cli.cmd_fallback([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                            settings_paths=[], post=hook.post, worker=worker, chatgpt=chatgpt, codex_login=lambda: True,
                            fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True,
                            out=lines.append)
    return code, "\n".join(lines), log.get_task(conn, row["task_id"]), worker, chatgpt


REDO = "A plan written from the task and the attacks.\n\n## Answered\nnone"


def test_the_fallback_check_agent_builds_from_the_task_and_the_attack_list_never_the_build_or_revision(conn):
    code, out, row = _double_fail(conn)
    assert "Run: sr fallback 1  (chatgpt redoes it; claude checks)" in out
    code, out, after, worker, chat = _fallback(conn, row, chat=[REDO], claude=["PASS"])
    assert code == 0, out
    redo = chat.prompts[0]
    assert redo == fallback.prompt(relay.redo_prompt(TASK, ATTACKS, search=True), "1. Attack 1 still open.")
    assert ATTACKS in redo and BUILD not in redo and "Review on Sundays" not in redo
    assert worker.prompts[0] == checking.checker_prompt(TASK, REDO, no_tools=True, relay=True, attacks=ATTACKS)
    assert (after["agent"], after["checker"], after["check_state"], after["result"]) == (
        "chatgpt", "claude", "passed", "A plan written from the task and the attacks.")
    assert after["check_note"] == "fallback of claude"


def test_no_fallback_when_grok_holds_the_check_slot(conn):
    fixed = REVISION.replace("Change the budget", "Change it")
    code, out, row, worker, chat = _relay(conn, claude=[BUILD, REVISION, fixed], slots=[("check", "grok")],
                                          chat=[ATTACKS],
                                          bodies={"c1": "FIX\n1. Attack 1 is unanswered.", "c2": "FIX\n1. Still."})
    assert row["check_state"] == "failed" and "No fallback: checker is grok: cannot redo" in out


# ---------- Grok's prompt limit ----------

@pytest.fixture
def small_limit(monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"grok_prompt_limit": 900}))
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)


def test_a_grok_attack_past_the_limit_fails_and_nothing_reaches_the_webhook(conn, small_limit):
    long_build = BUILD.replace("Review on Sundays at 6pm.", "Review on Sundays at 6pm. " * 60)
    hook, clock = RelayHook(s2=ATTACKS), Clock()
    cli.cmd_relay("redteam", TASK, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                  settings_paths=[], post=hook.post, worker=Scripted(long_build), chatgpt=Chat(),
                  codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                  wait=True, slots=[("attack", "grok")], out=lambda *_: None)
    row = log.recent_tasks(conn)[0]
    assert hook.sent == []   # the fake webhook: zero posts
    assert row["failed_stage"] == 2 and "too long for Grok (" in row["result"]


def test_a_grok_revise_stage_past_the_limit_fails_and_nothing_reaches_the_webhook(conn, small_limit):
    hook, chatgpt, clock = RelayHook(s1=BUILD), Chat(ATTACKS.replace("Groceries only.", "Groceries only. " * 50)), Clock()
    cli.cmd_relay("redteam", TASK, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                  settings_paths=[], post=hook.post, worker=Scripted(), chatgpt=chatgpt, codex_login=lambda: True,
                  fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True,
                  slots=[("build", "grok"), ("attack", "chatgpt"), ("check", "chatgpt")], out=lambda *_: None)
    row = log.recent_tasks(conn)[0]
    assert [p["task_id"].rsplit("-", 1)[1] for p in hook.sent] == ["s1"]   # the build (task alone) went; not s3
    assert row["failed_stage"] == 3 and "too long for Grok (" in row["result"]
