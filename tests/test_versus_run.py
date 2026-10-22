"""Build brief 9, phase C (rules v2.16, Relay): the versus chain in the runner. Claude and ChatGPT each
build from the task alone; ChatGPT reviews Claude's candidate (stage 3) and Claude reviews ChatGPT's
(stage 4); then the chain stops with no result chosen, awaiting the owner's pick (the owner's D2: status
`returned`, check_note `awaiting pick`). A builder never receives the other builder's work and a reviewer
never receives the other candidate. A stage that stops fails the task; a versus task is never resumed.
Fake agents only; every secret here is fake."""
import json
import pytest

from router import __main__ as cli
from router import log, presets, relay
from tests.helpers import shipped_roster
from tests.test_loop import Clock, Scripted
from tests.test_relay import CONFIG, ROSTER, SECRET, Chat, RelayHook
from tests.test_resume_run import claude_limit, codex_limit

LOADED = presets.load_presets(shipped_roster(), tuple(cli.SENDERS), relay.CONTRACTS, roles=relay.ROLES,
                              verdicts=relay.VERDICTS)
VERSUS = LOADED.presets["versus"]
TASK = "Write a 120-word product blurb for an adjustable garden seed tray."
A_TEXT = "CANDIDATE-A from claude: the SimTee adjusts to any height on any mat."
B_TEXT = "CANDIDATE-B from chatgpt: one tray, every mat, every height."
REVIEW_OF_A = "## Verdict\npass\n\n## Notes\n- Wrong: nothing.\n- Strong: clear (review of A by chatgpt)."
REVIEW_OF_B = "## Verdict\nfail\n\n## Notes\n- Wrong: it invents a spec (review of B by claude).\n- Strong: short."
NO_VERDICT = "Looks fine to me."


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _versus(conn, *, claude=(A_TEXT, REVIEW_OF_B), chatgpt=(B_TEXT, REVIEW_OF_A), task=TASK, wait=True):
    lines, clock, hook = [], Clock(), RelayHook()
    worker, chat = Scripted(*claude), Chat(*chatgpt)
    code = cli.cmd_relay("versus", task, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                         settings_paths=[], post=hook.post, worker=worker, chatgpt=chat, codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=wait, out=lines.append)
    row = log.recent_tasks(conn)[0]
    return code, "\n".join(lines), row, worker, chat


def _calls(conn, row):
    return [(c["kind"], c["stage"], c["role"], c["agent"], c["status"]) for c in log.calls_for(conn, row["task_id"])]


# ---------- the chain ----------

def test_a_versus_chain_logs_four_stage_rows_in_order_and_ends_awaiting_the_pick(conn):
    code, out, row, worker, chat = _versus(conn)
    assert code == 0, out
    assert _calls(conn, row) == [
        ("stage", 1, "build", "claude", "done"), ("stage", 2, "build", "chatgpt", "done"),
        ("stage", 3, "review", "chatgpt", "done"), ("stage", 4, "review", "claude", "done")]
    assert (row["mode"], row["preset"], row["status"], row["check_note"], row["check_state"], row["agent"],
            row["checker"], row["route_reason"], row["result"], row["failed_stage"], row["jev_status"]) == (
        "relay", "versus", "returned", "awaiting pick", None, None, None, "relay", None, None, "not_asked")
    assert relay.awaiting_pick(row)


def test_no_check_or_fix_call_runs_after_the_reviews(conn):
    code, out, row, worker, chat = _versus(conn)
    kinds = {c["kind"] for c in log.calls_for(conn, row["task_id"])}
    assert kinds == {"stage"}
    assert len(worker.prompts) == 2 and len(chat.prompts) == 2


def test_the_intro_line_names_the_four_stages_and_the_pick(conn):
    code, out, *_ = _versus(conn)
    assert out.splitlines()[0].endswith(
        "relay versus: build by claude -> build by chatgpt -> review of stage 1 by chatgpt -> "
        "review of stage 2 by claude, then your pick.")


def test_while_the_chain_runs_the_row_names_claude_no_checker_and_a_pending_check(conn):
    # The first build fails, so the row is left as the intake wrote it, plus the failure.
    code, out, row, *_ = _versus(conn, claude=(RuntimeError("boom"),))
    assert (row["agent"], row["checker"], row["check_state"], row["status"], row["failed_stage"]) == (
        "claude", None, "pending", "failed", 1)


# ---------- isolation: exactly the input each stage names ----------

def test_each_builder_gets_the_task_alone(conn):
    code, out, row, worker, chat = _versus(conn)
    assert worker.prompts[0] == relay.task_build_prompt(TASK)               # claude, the probe gate shut
    assert chat.prompts[0] == relay.task_build_prompt(TASK, search=True)    # rules v2.22: chatgpt searches


def test_stage_2_gets_no_trace_of_stage_1(conn):
    code, out, row, worker, chat = _versus(conn)
    assert A_TEXT not in chat.prompts[0] and "CANDIDATE-A" not in chat.prompts[0]


def test_stage_3_gets_stage_1_and_never_stage_2(conn):
    code, out, row, worker, chat = _versus(conn)
    assert chat.prompts[1] == relay.review_prompt(TASK, A_TEXT, search=True)
    assert B_TEXT not in chat.prompts[1] and "CANDIDATE-B" not in chat.prompts[1]


def test_stage_4_gets_stage_2_and_never_stage_1(conn):
    code, out, row, worker, chat = _versus(conn)
    assert worker.prompts[1] == relay.review_prompt(TASK, B_TEXT)
    assert A_TEXT not in worker.prompts[1] and "CANDIDATE-A" not in worker.prompts[1]


def test_no_prompt_carries_a_review_back_to_a_builder(conn):
    code, out, row, worker, chat = _versus(conn)
    for prompt in worker.prompts + chat.prompts:
        assert "review of A" not in prompt and "review of B" not in prompt


def test_the_step_function_hands_each_stage_its_named_input_only():
    task = {"task_id": "sr-v", "status": "queued", "mode": "relay", "preset": "versus"}
    rows = []

    def row(n, agent, text):
        rows.append({"call_id": f"sr-v-s{n}", "kind": "stage", "stage": n, "role": VERSUS.stage(n).role,
                     "agent": agent, "status": "done", "text": text, "resume_of": None})

    step = relay.next_stage(task, rows, VERSUS)
    assert (step.action, step.n, step.prior) == ("stage", 1, None)
    row(1, "claude", A_TEXT)
    step = relay.next_stage(task, rows, VERSUS)
    assert (step.action, step.n, step.prior) == ("stage", 2, None)
    row(2, "chatgpt", B_TEXT)
    step = relay.next_stage(task, rows, VERSUS)
    assert (step.action, step.n, step.prior) == ("stage", 3, A_TEXT)
    row(3, "chatgpt", REVIEW_OF_A)
    step = relay.next_stage(task, rows, VERSUS)
    assert (step.action, step.n, step.prior) == ("stage", 4, B_TEXT)
    row(4, "claude", REVIEW_OF_B)
    assert relay.next_stage(task, rows, VERSUS).action == "pick"


def test_the_two_builds_run_one_after_the_other(conn):
    code, out, row, worker, chat = _versus(conn)
    calls = log.calls_for(conn, row["task_id"])
    first, second = calls[0], calls[1]
    assert (first["stage"], second["stage"]) == (1, 2)
    assert first["finished_at"] <= second["sent_at"]


# ---------- web search ----------

def test_chatgpts_build_and_review_both_search(conn):
    # rules v2.22: before, chatgpt's build had search off
    code, out, row, worker, chat = _versus(conn)
    assert [k["web_search"] for k in chat.kwargs] == ["live", "live"]


def test_every_versus_call_row_carries_its_search_state(conn):
    # rules v2.22 (D6): before, no versus row carried one
    code, out, row, *_ = _versus(conn)
    assert [(c["agent"], json.loads(c["search"])["state"]) for c in log.calls_for(conn, row["task_id"])] == [
        ("claude", "off (probe not passed)"), ("chatgpt", "allowed"), ("chatgpt", "allowed"),
        ("claude", "off (probe not passed)")]


# ---------- the candidates, read from the rows ----------

def test_the_candidates_pair_each_build_with_its_review(conn):
    code, out, row, *_ = _versus(conn)
    found = relay.candidates(log.calls_for(conn, row["task_id"]), VERSUS)
    assert [(c.letter, c.stage, c.agent, c.text, c.reviewer, c.verdict) for c in found] == [
        ("a", 1, "claude", A_TEXT, "chatgpt", "pass"), ("b", 2, "chatgpt", B_TEXT, "claude", "fail")]
    assert found[0].notes == "- Wrong: nothing.\n- Strong: clear (review of A by chatgpt)."


# ---------- re-asks and stops ----------

def test_a_review_with_no_verdict_is_re_asked_once_and_the_chain_goes_on(conn):
    code, out, row, worker, chat = _versus(conn, chatgpt=(B_TEXT, NO_VERDICT, REVIEW_OF_A))
    assert code == 0, out
    assert _calls(conn, row) == [
        ("stage", 1, "build", "claude", "done"), ("stage", 2, "build", "chatgpt", "done"),
        ("stage", 3, "review", "chatgpt", "done"), ("reask", 3, "review", "chatgpt", "done"),
        ("stage", 4, "review", "claude", "done")]
    reask = chat.prompts[2]
    assert relay.REVIEW_SHAPE in reask and B_TEXT not in reask
    assert row["check_note"] == "awaiting pick"
    found = relay.candidates(log.calls_for(conn, row["task_id"]), VERSUS)
    assert found[0].verdict == "pass"


def test_a_review_still_missing_after_the_reask_fails_the_task_and_shows_both_candidates(conn):
    code, out, row, worker, chat = _versus(conn, chatgpt=(B_TEXT, NO_VERDICT, NO_VERDICT))
    assert code == 1
    assert (row["status"], row["failed_stage"]) == ("failed", 3)
    assert "RELAY FAILED at stage 3 (review by chatgpt)" in out
    assert A_TEXT in out and B_TEXT in out
    assert len(worker.prompts) == 1  # stage 4 never ran


def test_a_failed_build_stops_the_chain(conn):
    code, out, row, worker, chat = _versus(conn, chatgpt=(RuntimeError("codex broke"),))
    assert code == 1 and (row["status"], row["failed_stage"]) == ("failed", 2)
    assert A_TEXT in out


def test_secrets_in_a_candidate_are_redacted_before_they_are_stored(conn):
    code, out, row, *_ = _versus(conn, claude=(f"{A_TEXT} {SECRET}", REVIEW_OF_B))
    stored = log.calls_for(conn, row["task_id"])[0]["text"]
    assert SECRET not in stored


# ---------- a versus task is never resumed (D6) ----------

def test_a_plan_limit_on_a_versus_build_is_not_resumable(conn):
    code, out, row, worker, chat = _versus(conn, chatgpt=(codex_limit(),))
    assert (row["status"], row["failed_stage"]) == ("failed", 2)
    assert out.splitlines()[-1] == "Plan limit on chatgpt. Not resumable: versus task. Run it again."


def test_a_plan_limit_on_a_versus_review_is_not_resumable(conn):
    code, out, row, worker, chat = _versus(conn, claude=(A_TEXT, claude_limit()))
    assert (row["status"], row["failed_stage"]) == ("failed", 4)
    assert out.splitlines()[-1] == "Plan limit on claude. Not resumable: versus task. Run it again."


def test_sr_resume_refuses_a_versus_task_and_writes_nothing(conn):
    code, out, row, worker, chat = _versus(conn, chatgpt=(codex_limit(),))
    before = len(log.calls_for(conn, row["task_id"]))
    lines, clock, hook = [], Clock(), RelayHook()
    code = cli.cmd_resume([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                          settings_paths=[], post=hook.post, worker=Scripted(), chatgpt=Chat(), codex_login=lambda: True,
                          fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True,
                          out=lines.append)
    assert code == 2
    assert f"Refused: #{row['n']} can't be resumed: versus task. Run it again." in lines
    assert len(log.calls_for(conn, row["task_id"])) == before
    assert log.get_task(conn, row["task_id"])["status"] == "failed"


# ---------- sr check leaves an awaiting task alone ----------

def _check(conn, worker=None, chatgpt=None):
    lines, hook = [], RelayHook()
    code = cli.cmd_check(conn=conn, config=CONFIG, environ={}, settings_paths=[], post=hook.post,
                         worker=worker or Scripted(), chatgpt=chatgpt or Chat(), codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, presets=LOADED, roster=ROSTER, out=lines.append)
    return code, lines


def test_sr_check_does_nothing_to_a_task_awaiting_its_pick_and_says_so(conn):
    code, out, row, *_ = _versus(conn)
    before = [dict(c) for c in log.calls_for(conn, row["task_id"])]
    worker, chat = Scripted(), Chat()
    code, lines = _check(conn, worker, chat)
    assert code == 0
    assert f"#{row['n']} {row['task_id']} is awaiting your pick: sr pick {row['n']} a|b|none" in lines
    assert [dict(c) for c in log.calls_for(conn, row["task_id"])] == before
    assert worker.prompts == [] and chat.prompts == []
    assert dict(log.get_task(conn, row["task_id"])) == dict(row)


def test_awaiting_pick_lists_only_versus_tasks_waiting_for_the_owner(conn):
    code, out, row, *_ = _versus(conn)
    _versus(conn, chatgpt=(RuntimeError("codex broke"),))
    assert [r["task_id"] for r in log.awaiting_pick_tasks(conn)] == [row["task_id"]]
