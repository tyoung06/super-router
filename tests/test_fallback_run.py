"""Build brief 10, phase B (rules v2.17, Fallback): `sr fallback <n>` runs the plan. The first attempt's
double fail is made with fake agents through the real loop; then the checker redoes the work from what
the original doer was sent plus the final fix list (never the failed result), and the original doer
checks with the usual loop (collab: as the check stage). Grok never redoes, and research-build's Grok
stage is never run again. Fake agents only; every secret here is fake."""
import pytest

from router import __main__ as cli
from router import checking, fallback, log, relay
from tests.helpers import roster_with
from tests.test_collab import AMENDED, DELIVERABLE, EDITED, PLAN
from tests.test_collab import TASK as COLLAB_TASK
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_relay import CONFIG, GOOD_NOTE, ROSTER, TASK as RB_TASK, Chat, RelayHook
from tests.test_resume_run import LOADED, WRITING, _relay, _route, claude_limit, codex_limit

ROUTE_TASK = "write two lines about seed trays"
FIRST, FIXED = "FIRST-x71 two lines that rhyme badly", "FIXED-x72 two lines that still rhyme badly"
CHECK1, FINAL = "FIX\n- the rhyme is forced", "FIX\n- line 1 is too long\n- no garden word\n- the rhyme is forced"
FINAL_LIST = "- line 1 is too long\n- no garden word\n- the rhyme is forced"
REDO = "REDO-x73 Trays stand tall at dawn; / the first drive flies on."
FAILED_EDIT = EDITED.replace("## Unresolved\nnone", "## Unresolved\n- the error cases are missing")


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _double_fail_route(conn):
    code, out, row = _route(conn, WRITING, worker=Scripted(FIRST, FIXED), chatgpt=Chat(CHECK1, FINAL))
    assert (row["status"], row["check_state"], row["agent"], row["checker"]) == ("done", "failed", "claude", "chatgpt")
    return row


def _fallback(conn, row, *, worker=None, chatgpt=None, hook=None, roster=ROSTER, words=None, wait=True):
    lines, clock, hook = [], Clock(), hook or RelayHook()
    worker, chatgpt = worker or Scripted(), chatgpt or Chat()
    code = cli.cmd_fallback(words or [str(row["n"])], conn=conn, config=CONFIG, roster=roster, loaded=LOADED,
                            environ={}, settings_paths=[], post=hook.post, worker=worker, chatgpt=chatgpt,
                            codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep,
                            clock=clock, wait=wait, out=lines.append)
    return code, "\n".join(lines), log.get_task(conn, row["task_id"]), worker, chatgpt, hook


def _rows(conn, row):
    tid = row["task_id"]
    return [(c["call_id"].removeprefix(tid) or "<id>", c["kind"], c["agent"], c["status"], c["fallback_of"] and
             (c["fallback_of"].removeprefix(tid) or "<id>")) for c in log.calls_for(conn, tid)]


# ---------- routed ----------

def test_a_routed_fallback_swaps_the_pair_and_passes(conn):
    row = _double_fail_route(conn)
    code, out, after, worker, chat, hook = _fallback(conn, row, chatgpt=Chat(REDO), worker=Scripted("PASS"))
    assert code == 0, out
    assert _rows(conn, row)[-2:] == [("-fb1", "do", "chatgpt", "done", "<id>"), ("-fb1-c1", "check", "claude", "done", None)]
    assert (after["status"], after["agent"], after["checker"], after["check_state"], after["result"], after["check_note"]) == (
        "done", "chatgpt", "claude", "passed", REDO, "fallback of claude")
    assert _rows(conn, row)[:4] == [("<id>", "do", "claude", "done", None), ("-c1", "check", "chatgpt", "done", None),
                                    ("-f1", "fix", "claude", "done", None), ("-c2", "recheck", "chatgpt", "done", None)]


def test_the_redo_gets_the_original_prompt_and_the_fix_list_never_the_failed_result(conn):
    row = _double_fail_route(conn)
    code, out, after, worker, chat, hook = _fallback(conn, row, chatgpt=Chat(REDO), worker=Scripted("PASS"))
    # rules v2.22: chatgpt's redo searches, so what the original doer was sent gains the search line
    assert chat.prompts[0] == fallback.prompt(f"{ROUTE_TASK}\n\n{checking.SEARCH_LINE_GENERAL}", FINAL_LIST)
    for failed in (FIRST, FIXED, "FIRST-x71", "FIXED-x72"):
        assert failed not in chat.prompts[0]
    # The checker gets the redo, never the original.
    assert REDO in worker.prompts[0] and FIXED not in worker.prompts[0]


def test_the_plan_is_printed_before_the_redo(conn):
    row = _double_fail_route(conn)
    code, out, *_ = _fallback(conn, row, chatgpt=Chat(REDO), worker=Scripted("PASS"))
    assert out.splitlines()[:2] == [
        f"Falling back on #{row['n']} {row['task_id']} (routed): chatgpt redoes it; claude checks "
        "(one check round, one fix round).",
        "chatgpt gets the task, plus the final fix list (3 lines); never the failed result."]


def test_a_redo_that_fails_twice_prints_four_blocks_original_first(conn):
    row = _double_fail_route(conn)
    code, out, after, *_ = _fallback(conn, row, chatgpt=Chat(REDO, "REDO-FIXED-x74"),
                                     worker=Scripted("FIX\n- still no garden word", "FIX\n- now too short"))
    assert code == 5
    assert (after["status"], after["check_state"], after["result"], after["check_note"]) == (
        "done", "failed", "REDO-FIXED-x74", "not passed after one fix round; fallback of claude")
    assert [r[0] for r in _rows(conn, row)[4:]] == ["-fb1", "-fb1-c1", "-fb1-f1", "-fb1-c2"]
    tail = out[out.index("Both attempts failed their checks twice."):]
    order = [tail.index(s) for s in ("Original result (claude):", FIXED, "Its final fix list (chatgpt):", FINAL_LIST,
                                     "Redo (chatgpt):", "REDO-FIXED-x74", "Its final fix list (claude):", "- now too short")]
    assert order == sorted(order)


def test_the_redo_is_never_sent_to_grok_and_nothing_goes_to_the_webhook(conn):
    row = _double_fail_route(conn)
    code, out, after, worker, chat, hook = _fallback(conn, row, chatgpt=Chat(REDO), worker=Scripted("PASS"))
    assert hook.sent == []


# ---------- R1: Grok as the original doer checks the redo ----------

class _GrokHook(Webhook):
    """Keyed by the call id's last part; the task's own id (three dashes) is the do call."""

    @staticmethod
    def _key(call_id):
        return "do" if call_id.count("-") == 3 else call_id.split("-")[-1]


def test_r1_grok_did_the_work_so_grok_checks_the_redo_and_never_redoes_it(conn):
    xpulse = {"status": "ok", "label": "x_social_pulse", "confidence": 0.95, "needs_split": 0.1, "tokens": 0}
    hook = _GrokHook(do="three posts", f1="three posts, fixed", c1="PASS")
    code, out, row = _route(conn, xpulse, worker=Scripted(), chatgpt=Chat(CHECK1, FINAL), hook=hook)
    assert (row["agent"], row["checker"], row["check_state"]) == ("grok", "chatgpt", "failed")
    sent_before = len(hook.sent)
    code, out, after, worker, chat, hook = _fallback(conn, row, chatgpt=Chat(REDO), hook=hook)
    new = [p["task_id"].removeprefix(row["task_id"]) for p in hook.sent[sent_before:]]
    assert new == ["-fb1-c1"]                      # Grok checks; it never redoes
    assert _rows(conn, row)[-2][:3] == ("-fb1", "do", "chatgpt")
    assert (after["agent"], after["checker"], after["check_state"]) == ("chatgpt", "grok", "passed"), out


# ---------- research-build ----------

def _double_fail_research(conn, hook):
    code, out, row = _relay(conn, "research-build", RB_TASK, worker=Scripted(FIRST, FIXED), chatgpt=Chat(CHECK1, FINAL),
                            hook=hook)
    assert (row["status"], row["check_state"]) == ("done", "failed"), out
    return row


def test_research_build_redoes_stage_2_from_the_stored_note_with_search_and_never_reruns_grok(conn):
    hook = RelayHook(s1=GOOD_NOTE)
    row = _double_fail_research(conn, hook)
    sent_before = len(hook.sent)
    code, out, after, worker, chat, hook = _fallback(conn, row, chatgpt=Chat(REDO), worker=Scripted("PASS"), hook=hook)
    assert code == 0, out
    assert len(hook.sent) == sent_before            # Grok's research stage is never run again
    note = relay.stage_results(log.calls_for(conn, row["task_id"]))[1]
    assert chat.prompts[0] == fallback.prompt(relay.build_prompt(RB_TASK, note, search=True), FINAL_LIST)
    assert chat.kwargs[0]["web_search"] == "live" and checking.SEARCH_LINE in chat.prompts[0]
    assert FIRST not in chat.prompts[0] and FIXED not in chat.prompts[0]
    fb = log.get_call(conn, f"{row['task_id']}-fb1")
    assert (fb["kind"], fb["stage"], fb["role"], fb["agent"], fb["fallback_of"]) == (
        "stage", 2, "build", "chatgpt", f"{row['task_id']}-s2")
    assert log.search_of(fb) == {"state": "allowed"}
    assert (after["agent"], after["checker"], after["check_state"], after["result"]) == ("chatgpt", "claude", "passed", REDO)


def test_a_research_build_redo_fix_round_carries_the_note_and_chatgpt_searches(conn):
    hook = RelayHook(s1=GOOD_NOTE)
    row = _double_fail_research(conn, hook)
    code, out, after, worker, chat, hook = _fallback(conn, row, chatgpt=Chat(REDO, "REDO-FIXED"),
                                                     worker=Scripted("FIX\n- a source is missing", "PASS"), hook=hook)
    assert code == 0 and after["check_state"] == "fixed", out
    assert relay.NOTE_LABEL in chat.prompts[1] and chat.kwargs[1]["web_search"] == "live"
    assert [r[0] for r in _rows(conn, row)[-4:]] == ["-fb1", "-fb1-c1", "-fb1-f1", "-fb1-c2"]


# ---------- collab ----------

def test_collab_redoes_stage_3_from_the_amended_plan_and_claude_checks_as_the_check_stage(conn):
    code, out, row = _relay(conn, "collab", COLLAB_TASK, worker=Scripted(PLAN, DELIVERABLE),
                            chatgpt=Chat(AMENDED, FAILED_EDIT))
    assert (row["check_state"], row["check_note"]) == ("failed", "checked-by-stage 4"), out
    code, out, after, worker, chat, hook = _fallback(conn, row, chatgpt=Chat(DELIVERABLE), worker=Scripted(EDITED))
    assert code == 0, out
    assert chat.prompts[0] == fallback.prompt(relay.execute_prompt(COLLAB_TASK, AMENDED, search=True),
                                              "- the error cases are missing")  # rules v2.22: chatgpt searches
    assert relay.check_parts(FAILED_EDIT)[0] not in chat.prompts[0]
    assert [r[:3] for r in _rows(conn, row)[-2:]] == [("-fb1", "stage", "chatgpt"), ("-fb1-s4", "stage", "claude")]
    assert (after["status"], after["check_state"], after["agent"], after["checker"], after["check_note"]) == (
        "done", "passed", "chatgpt", "claude", "checked-by-stage 4; fallback of claude")
    assert relay.checked_by_stage(after) == 4
    assert worker.prompts[0] == relay.edit_prompt(COLLAB_TASK, DELIVERABLE)


# ---------- stops: none of them uses up the one fallback ----------

def test_a_plan_limit_on_the_fallback_doer_leaves_the_task_as_it_was_and_may_run_again(conn):
    row = _double_fail_route(conn)
    before = dict(log.get_task(conn, row["task_id"]))
    code, out, after, *_ = _fallback(conn, row, chatgpt=Chat(codex_limit()))
    assert code == 1
    assert dict(after) == before
    assert _rows(conn, row)[-1] == ("-fb1", "do", "chatgpt", "failed", "<id>")
    assert log.get_call(conn, f"{row['task_id']}-fb1")["reason_code"] == "plan_limit"
    assert out.splitlines()[-1] == (f"Plan limit on chatgpt. Not resumable: fallback. Run sr fallback {row['n']} "
                                    "again when it lifts.")
    code, out, after, *_ = _fallback(conn, row, chatgpt=Chat(REDO), worker=Scripted("PASS"))
    assert code == 0 and after["result"] == REDO
    assert _rows(conn, row)[-2][0] == "-fb2"


def test_an_error_on_the_fallback_doer_does_not_count(conn):
    row = _double_fail_route(conn)
    code, out, after, *_ = _fallback(conn, row, chatgpt=Chat(RuntimeError("codex broke")))
    assert code == 1 and after["result"] == FIXED
    assert f"It doesn't count: run `sr fallback {row['n']}` again." in out
    assert fallback.decide(after, log.calls_for(conn, row["task_id"]), live=ROSTER.live).ok


def test_ctrl_c_during_the_redo_changes_nothing(conn):
    row = _double_fail_route(conn)
    calls_before = len(log.calls_for(conn, row["task_id"]))
    code, out, after, *_ = _fallback(conn, row, chatgpt=Chat(KeyboardInterrupt))
    assert code == 130 and len(log.calls_for(conn, row["task_id"])) == calls_before
    assert "Nothing changed" in out


def test_sr_resume_refuses_a_stopped_fallback(conn):
    row = _double_fail_route(conn)
    _fallback(conn, row, chatgpt=Chat(codex_limit()))
    lines, clock, hook = [], Clock(), RelayHook()
    code = cli.cmd_resume([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                          settings_paths=[], post=hook.post, worker=Scripted(), chatgpt=Chat(), codex_login=lambda: True,
                          fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True, out=lines.append)
    assert code == 2
    assert f"Refused: #{row['n']} can't be resumed: fallback. Run sr fallback {row['n']} again when it lifts." in lines


def test_a_plan_limit_on_the_redos_check_is_not_resumed(conn):
    row = _double_fail_route(conn)
    code, out, after, *_ = _fallback(conn, row, chatgpt=Chat(REDO), worker=Scripted(claude_limit()))
    assert after["check_state"] == "unchecked"
    assert "Not resumable: a fallback is never resumed" in out


# ---------- refusals and the unchecked case ----------

def test_a_refused_fallback_writes_nothing_and_exits_2(conn):
    code, out, row = _route(conn, WRITING, worker=Scripted(FIRST), chatgpt=Chat("PASS"))
    calls_before = len(log.calls_for(conn, row["task_id"]))
    code, out, after, *_ = _fallback(conn, row)
    assert code == 2
    assert out == (f"Refused: #{row['n']} can't fall back: not a double fail: it passed. Nothing was logged or sent.")
    assert len(log.calls_for(conn, row["task_id"])) == calls_before


def test_a_second_fallback_is_refused(conn):
    row = _double_fail_route(conn)
    _fallback(conn, row, chatgpt=Chat(REDO), worker=Scripted("PASS"))
    code, out, *_ = _fallback(conn, row)
    assert code == 2 and "already fell back once" in out


def test_no_such_task_is_refused(conn):
    lines = []
    code = cli.cmd_fallback(["9"], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                            settings_paths=[], post=None, worker=Scripted(), chatgpt=Chat(), codex_login=lambda: True,
                            out=lines.append)
    assert code == 2 and lines == ["Refused: No task #9. Nothing was logged or sent."]


def test_the_original_doer_not_live_means_the_redo_is_delivered_unchecked(conn):
    row = _double_fail_route(conn)
    roster = roster_with(claude=False, grok=True, chatgpt=True)
    code, out, after, worker, chat, hook = _fallback(conn, row, chatgpt=Chat(REDO), roster=roster)
    assert (after["status"], after["result"], after["check_state"], after["checker"]) == ("done", REDO, "unchecked", None)
    assert after["check_note"] == "claude, the original doer, isn't live; fallback of claude"
    assert worker.prompts == []


def test_the_billing_switch_refuses_before_anything(conn):
    row = _double_fail_route(conn)
    lines = []
    code = cli.cmd_fallback([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED,
                            environ={"OPENAI_API_KEY": "x"}, settings_paths=[], post=None, worker=Scripted(),
                            chatgpt=Chat(), codex_login=lambda: True, out=lines.append)
    assert code == 2 and lines[-1] == "Nothing was logged or sent."
