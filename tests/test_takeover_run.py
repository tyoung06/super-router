"""Build brief 24, C2 (decisions 4, 6 and 9): the router runs the takeover wherever a stop is written: route, relay,
split and `sr check`. The stopped row stays; the takeover's call is `<stopped>-takeover` naming it in `resume_of`; the
task row takes the new doer, checker and check state; Terminal prints the card's words on one line, and no `Run: sr
resume` follows a stop the router took over. If the takeover's own call stops, the task ends with both reasons. Nothing
is taken over without a gate (a direct call keeps today's stops) or on an override. Fakes only; every secret is fake."""
import pytest

from router import __main__ as cli
from router import checking, claude_worker, log
from tests.helpers import fake_label
from tests.test_collab import AMENDED, DELIVERABLE, PLAN
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_relay import CONFIG, GOOD_NOTE, Chat, RelayHook
from tests.test_resume_run import claude_limit, codex_limit
from tests.test_routing_availability import ROSTER, WHY, Gate, jev
from tests.test_presets_fill import LOADED

POEM = "write a two-line poem about rubber trays"


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _route(conn, task, label, *, worker=None, chat=None, gate=None, hook=None, wait=False):
    lines, clock, hook = [], Clock(), hook or Webhook()
    worker, chat = worker or Scripted(), chat or Chat("PASS")
    code = cli.cmd_route(task, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=fake_label(jev(label)), post=hook.post, worker=worker, chatgpt=chat,
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=wait, available=Gate() if gate is None else gate, out=lines.append)
    return code, "\n".join(lines), log.recent_tasks(conn)[0], hook, worker, chat


def _relay(conn, preset, task, *, worker, chat, hook=None, gate=None):
    lines, clock, hook = [], Clock(), hook or RelayHook(s1=GOOD_NOTE)
    code = cli.cmd_relay(preset, task, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                         settings_paths=[], post=hook.post, worker=worker, chatgpt=chat, codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True,
                         available=Gate() if gate is None else gate, out=lines.append)
    return code, "\n".join(lines), log.recent_tasks(conn)[0], hook


def _check(conn, *, worker=None, chat=None, hook=None, gate=None):
    lines = []
    code = cli.cmd_check(conn=conn, config=CONFIG, fetch=hook.fetch, close=hook.close, post=hook.post,
                         worker=worker or Scripted(), chatgpt=chat or Chat("PASS"), codex_login=lambda: True,
                         presets=LOADED, roster=ROSTER, available=Gate() if gate is None else gate, out=lines.append)
    return code, "\n".join(lines)


def _calls(conn, task_id):
    return [(c["call_id"].replace(task_id, "t"), c["kind"], c["agent"], c["status"], c["reason_code"],
             (c["resume_of"] or "").replace(task_id, "t") or None) for c in log.calls_for(conn, task_id)]


def unchecked(why):
    return f"no other agent available to check ({why})"


# ---------- routed tasks ----------

def test_claudes_plan_limit_is_taken_over_by_chatgpt_at_once_and_said_on_one_line(conn):
    code, out, row, *_, chat = _route(conn, POEM, "writing", worker=Scripted(claude_limit()), chat=Chat("Two lines."))
    assert code == 0 and (row["status"], row["result"]) == ("done", "Two lines.")
    assert (row["agent"], row["checker"], row["check_state"], row["check_note"]) == (
        "chatgpt", None, "unchecked", unchecked("Claude hit its plan limit"))
    assert _calls(conn, row["task_id"]) == [("t", "do", "claude", "failed", "plan_limit", None),
                                            ("t-takeover", "do", "chatgpt", "done", None, "t")]
    assert "ChatGPT took over the first call · Claude hit its plan limit" in out.splitlines()
    assert "sr resume" not in out
    assert POEM in chat.prompts[0] and "plan limit" not in chat.prompts[0]   # what Claude was sent; never its output


def test_any_agent_error_is_taken_over_too(conn):
    failed = claude_worker.WorkerError("claude exited 1: Overloaded")
    code, out, row, *_ = _route(conn, POEM, "writing", worker=Scripted(failed), chat=Chat("Two lines."))
    assert row["status"] == "done" and "ChatGPT took over the first call · Claude's call failed" in out


def test_when_the_takeovers_own_call_stops_the_task_ends_with_both_reasons(conn):
    code, out, row, *_ = _route(conn, POEM, "writing", worker=Scripted(claude_limit()), chat=Chat(codex_limit()))
    assert code == 1 and row["status"] == "failed"
    assert row["result"] == "plan limit on chatgpt: You've hit your usage limit.; it took over after Claude hit its plan limit"
    assert f"Plan limit on chatgpt too: it took over the stopped call. #{row['n']} stays stopped; it can't be resumed." in out


def test_with_nobody_to_take_over_the_stop_stands_and_the_manual_resume_is_offered(conn):
    code, out, row, *_ = _route(conn, POEM, "writing", worker=Scripted(claude_limit()), gate=Gate({"chatgpt"}))
    assert code == 1 and row["status"] == "failed" and len(log.calls_for(conn, row["task_id"])) == 1
    assert f"No takeover: no other agent can take it over ({WHY['chatgpt']})." in out
    assert f"Plan limit on claude. Run: sr resume {row['n']}  (continues with chatgpt)" in out


def test_meta_research_whose_grok_send_fails_goes_to_chatgpt_with_the_no_feed_line_and_claude_checks(conn):
    # Meta research (x_social_pulse is Grok's alone since the owner's decision of 21 Oct: its failed send fails the task)
    hook = Webhook(fail=("do",))
    code, out, row, hook, worker, chat = _route(conn, "what are people on Instagram saying about rubber trays", "meta_social_trends",
                                                hook=hook, worker=Scripted("PASS"), chat=Chat("Three bullets."))
    assert (row["status"], row["agent"], row["checker"], row["check_state"]) == ("done", "chatgpt", "claude", "passed")
    assert _calls(conn, row["task_id"])[:2] == [("t", "do", "grok", "failed", None, None),
                                               ("t-takeover", "do", "chatgpt", "done", None, "t")]
    assert "ChatGPT took over the first call · Grok Bot's call failed · done without Meta" in out.splitlines()
    assert checking.NO_FEED_LINE in chat.prompts[0]


def test_bulk_text_goes_to_grok_bot_whose_takeover_call_is_collected_by_sr_check(conn):
    hook = Webhook(takeover="Ten product lines.")
    code, out, row, hook, *_ = _route(conn, "write ten product lines", "bulk_text", worker=Scripted(claude_limit()),
                                      hook=hook)
    task_id = row["task_id"]
    assert code == 0 and row["status"] == "sent" and hook.sent[0]["task_id"] == f"{task_id}-takeover"
    assert "write ten product lines" in hook.sent[0]["task"]
    assert "Grok Bot took over the first call · Claude hit its plan limit" in out
    code, out = _check(conn, hook=hook, chat=Chat("PASS"))
    row = log.get_task(conn, task_id)
    assert (row["status"], row["agent"], row["checker"], row["check_state"], row["result"]) == (
        "done", "grok", "chatgpt", "passed", "Ten product lines.")


def test_a_check_round_whose_grok_send_fails_goes_to_the_next_checker(conn):
    hook = Webhook(fail=("c1",))
    code, out, row, *_ = _route(conn, "write ten product lines", "bulk_text", worker=Scripted("Ten lines."),
                                chat=Chat("PASS"), hook=hook)
    assert (row["status"], row["agent"], row["checker"], row["check_state"]) == ("done", "claude", "chatgpt", "passed")
    assert "ChatGPT took over the check round · Grok Bot's call failed" in out


def test_a_check_round_with_nobody_left_ends_unchecked_as_today(conn):
    code, out, row, *_ = _route(conn, POEM, "writing", worker=Scripted("Two lines."), chat=Chat(codex_limit()))
    assert (row["status"], row["check_state"]) == ("done", "unchecked")
    assert row["check_note"].startswith("check round by chatgpt didn't run: plan limit on chatgpt")
    assert "No takeover: no other agent can check it (ChatGPT hit its plan limit)." in out


def test_a_fix_round_taken_over_by_the_checker_is_delivered_unchecked_c12(conn):
    code, out, row, *_ = _route(conn, POEM, "writing", worker=Scripted("Draft one.", claude_limit()),
                                chat=Chat("FIX\n1. Rhyme.", "Draft two, rhymed."))
    assert (row["status"], row["agent"], row["checker"], row["check_state"], row["result"]) == (
        "done", "chatgpt", None, "unchecked", "Draft two, rhymed.")
    assert row["check_note"] == (unchecked("Claude hit its plan limit")
                                 + "; the first check asked for fixes; this is the fixed result")
    assert "ChatGPT took over the fix round · Claude hit its plan limit" in out


def test_an_override_is_never_taken_over(conn):
    code, out, row, *_ = _route(conn, "@claude " + POEM, "writing", worker=Scripted(claude_limit()))
    assert row["status"] == "failed" and "took over" not in out and "No takeover" not in out


def test_without_a_gate_a_stop_ends_the_task_as_today(conn):
    lines, clock, hook = [], Clock(), Webhook()
    cli.cmd_route(POEM, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                  label=fake_label(jev("writing")), post=hook.post, worker=Scripted(claude_limit()), chatgpt=Chat("x"),
                  codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                  out=lines.append)
    row = log.recent_tasks(conn)[0]
    assert row["status"] == "failed" and len(log.calls_for(conn, row["task_id"])) == 1


def test_sr_check_takes_over_a_stop_left_by_a_process_that_ended_before_it_could(conn):
    log.add_task(conn, "sr-1", POEM, "cli", jev("writing"))
    log.set_route(conn, "sr-1", agents=ROSTER.names, agent="claude", route_reason="best", skill="writing",
                  skill_source="jev", checker="chatgpt", check_state="pending")
    log.add_call(conn, "sr-1", "sr-1", "do", "claude", status="failed", text="plan limit on claude: x", reason_code="plan_limit")
    code, out = _check(conn, hook=Webhook(), chat=Chat("Two lines."))
    row = log.get_task(conn, "sr-1")
    assert (row["status"], row["agent"], row["result"]) == ("done", "chatgpt", "Two lines.")
    assert "ChatGPT took over the first call · Claude hit its plan limit" in out


def test_sr_show_says_who_took_over_which_call_and_why(conn):
    code, out, row, *_ = _route(conn, POEM, "writing", worker=Scripted(claude_limit()), chat=Chat("Two lines."))
    lines = []
    cli.cmd_show(conn=conn, words=[str(row["n"])], roster=ROSTER, out=lines.append)
    assert (f"Taken over: ChatGPT took over the first call — replaces call {row['task_id']} (Claude hit its plan "
            "limit).") in lines
    history = []
    cli.cmd_show(conn=conn, words=[str(row["n"])], history=True, roster=ROSTER, out=history.append)
    assert any(f", took over — replaces call {row['task_id']}" in line for line in history)


# ---------- relay tasks ----------

def test_a_grok_research_stage_whose_send_fails_is_researched_by_chatgpt_and_the_chain_goes_on(conn):
    hook = RelayHook(fail=("s1",))
    code, out, row, hook = _relay(conn, "research-build", "what is the current stable python",
                                  worker=Scripted("the build"), chat=Chat(GOOD_NOTE, "PASS"), hook=hook)
    assert (row["status"], row["agent"], row["checker"], row["check_state"]) == ("done", "claude", "chatgpt", "passed")
    assert [(c[0], c[2], c[3]) for c in _calls(conn, row["task_id"])] == [
        ("t-s1", "grok", "failed"), ("t-s1-takeover", "chatgpt", "done"), ("t-s2", "claude", "done"),
        ("t-c1", "chatgpt", "done")]
    assert "ChatGPT took over stage 1 (research) · Grok Bot's call failed" in out


def test_research_builds_stopped_build_is_built_by_chatgpt_and_delivered_unchecked_the_briefs_example(conn):
    code, out, row, hook = _relay(conn, "research-build", "what is the current stable python",
                                  worker=Scripted(claude_limit()), chat=Chat("ChatGPT's build."))
    assert (row["status"], row["agent"], row["checker"], row["check_state"], row["result"]) == (
        "done", "chatgpt", None, "unchecked", "ChatGPT's build.")
    assert row["check_note"] == unchecked("Claude hit its plan limit")
    assert "ChatGPT took over stage 2 (build) · Claude hit its plan limit" in out


def test_collab_a_stopped_execute_stage_is_taken_over_and_the_check_stage_is_left_out(conn):
    code, out, row, hook = _relay(conn, "collab", "write a short spec for sr open",
                                  worker=Scripted(PLAN, claude_limit()), chat=Chat(AMENDED, DELIVERABLE))
    assert (row["status"], row["agent"], row["checker"], row["check_state"]) == ("done", "chatgpt", None, "unchecked")
    assert row["check_note"] == unchecked("Claude hit its plan limit")
    assert [c[0] for c in _calls(conn, row["task_id"])] == ["t-s1", "t-s2", "t-s3", "t-s3-takeover"]


def test_a_relay_stage_whose_takeover_stops_too_ends_the_chain_with_both_reasons(conn):
    code, out, row, hook = _relay(conn, "research-build", "what is the current stable python",
                                  worker=Scripted(claude_limit()), chat=Chat(codex_limit()))
    assert row["status"] == "failed" and row["failed_stage"] == 2
    assert ("RELAY FAILED at stage 2 (build by chatgpt): plan limit on chatgpt: You've hit your usage limit.; it took "
            "over after Claude hit its plan limit") in out


# ---------- split ----------

def test_a_splits_stopped_plan_is_made_by_chatgpt_and_waits_for_your_yes_as_ever(conn):
    from tests.test_split_approve import PLAN as SPLIT_PLAN, TASK as SPLIT_TASK, Jev, _split_row
    lines, clock, hook = [], Clock(), RelayHook()
    chat = Chat(SPLIT_PLAN)
    cli.cmd_split(SPLIT_TASK, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=Jev(),
                  ask=None, post=hook.post, worker=Scripted(claude_limit()), chatgpt=chat, codex_login=lambda: True,
                  fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=False, available=Gate(),
                  out=lines.append)
    row = _split_row(conn)
    assert (row["status"], row["check_note"], row["agent"], row["checker"]) == (
        "returned", log.AWAITING_APPROVAL, "claude", "chatgpt")
    assert "ChatGPT took over stage 1 (split_plan) · Claude hit its plan limit" in lines
    assert [c[0] for c in _calls(conn, row["task_id"])] == ["t-s1", "t-s1-takeover"]
