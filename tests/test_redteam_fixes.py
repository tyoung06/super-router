"""Brief 16, the owner's two fixes after Phase E (0 live calls). (1) The redteam checker prompt (check, re-check and the
fallback check) says `## Answered` is the reviser's note, not part of the deliverable, never counted toward the task's
length or format (#5's re-check counted it). (2) A redteam fix round's result is read with the revision contract:
`## Answered` numbers must be in the attack list (#5's fix cited 7 and 8); one re-ask (a second `fix` row, `-f1r`);
still missing, the round fails as a fix-round failure does today (ending 5). A stopped fix re-ask resumes as a fresh
fix round (the owner's D8 shape). Every value here is fake."""
import pytest

from router import __main__ as cli
from router import checking, log, relay, resume
from router.claude_worker import WorkerError
from tests.test_redteam_chain import ATTACKS, BUILD, LOADED, REVISION, ROSTER, TASK, _relay, _rows

FIX_LIST = "FIX\n1. Attack 1 is neither fixed nor answered."
BAD_FIX = "The fixed plan.\n\n## Answered\n7. Not relevant.\n8. Covered."
GOOD_FIX = "The fixed plan, now with a trigger.\n\n## Answered\n3. Sunday is the user's choice."


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


# ---------- (1) the checker line ----------

def test_the_redteam_checker_prompt_says_answered_is_not_part_of_the_deliverable():
    p = checking.checker_prompt(TASK, REVISION, no_tools=False, relay=True, attacks=ATTACKS)
    assert checking.ANSWERED_NOTE_LINE in p
    assert "never count it toward the task's length or format" in checking.ANSWERED_NOTE_LINE
    assert p.index(checking.REDTEAM_CHECK_LINE) < p.index(checking.ANSWERED_NOTE_LINE) < p.index("===== TASK =====")
    assert checking.ANSWERED_NOTE_LINE not in checking.checker_prompt(TASK, REVISION, no_tools=False, relay=True)


def test_the_check_and_the_re_check_both_carry_it(conn):
    code, out, row, worker, chat = _relay(conn, claude=[BUILD, REVISION, GOOD_FIX], chat=[ATTACKS, FIX_LIST, "PASS"])
    assert code == 0, out
    assert checking.ANSWERED_NOTE_LINE in chat.prompts[1] and checking.ANSWERED_NOTE_LINE in chat.prompts[2]


def test_the_fallback_check_carries_it(conn):
    from tests.test_redteam_recovery import REDO, _double_fail, _fallback
    code, out, row = _double_fail(conn)
    code, out, after, worker, chat = _fallback(conn, row, chat=[REDO], claude=["PASS"])
    assert code == 0 and checking.ANSWERED_NOTE_LINE in worker.prompts[0]


# ---------- (2) the revision contract on the fix round ----------

def test_a_fix_whose_answered_cites_numbers_not_in_the_list_is_re_asked_once(conn):
    code, out, row, worker, chat = _relay(conn, claude=[BUILD, REVISION, BAD_FIX, GOOD_FIX],
                                          chat=[ATTACKS, FIX_LIST, "PASS"])
    assert code == 0, out
    calls = log.calls_for(conn, row["task_id"])
    assert [(c["call_id"].removeprefix(row["task_id"]), c["kind"], c["agent"]) for c in calls[-3:]] == [
        ("-f1", "fix", "claude"), ("-f1r", "fix", "claude"), ("-c2", "recheck", "chatgpt")]
    reask = worker.prompts[3]
    assert reask == relay.reask_prompt("revise", TASK, BAD_FIX, (
        "Answered: attack 7 is not in the attack list (1, 2, 3)", "Answered: attack 8 is not in the attack list (1, 2, 3)"))
    assert "re-asked once" in out and "fix round" in out
    assert chat.prompts[2] == checking.checker_prompt(TASK, GOOD_FIX, no_tools=False, can_browse=True, relay=True,
                                                      search=True, attacks=ATTACKS)
    assert (row["check_state"], row["result"]) == ("fixed", "The fixed plan, now with a trigger.")


def test_still_missing_after_the_re_ask_the_round_fails_as_a_fix_round_failure(conn):
    code, out, row, worker, chat = _relay(conn, claude=[BUILD, REVISION, BAD_FIX, BAD_FIX], chat=[ATTACKS, FIX_LIST])
    assert code == 5
    assert [c[0] for c in _rows(conn, row)] == ["stage", "stage", "stage", "check", "fix", "fix"]   # no re-check
    assert (row["status"], row["check_state"]) == ("done", "failed")
    assert row["check_note"].startswith("fix round by claude failed its contract after the re-ask: Answered: attack 7")
    assert row["result"] == REVISION.split("\n\n## Answered")[0]   # the furthest result that met its contract
    assert "FIX ROUND FAILED" in out
    shown = []
    cli.cmd_show(conn=conn, words=[str(row["n"])], roster=ROSTER, presets=LOADED, out=shown.append)
    assert "3. Sunday is the user's choice" in "\n".join(shown)   # --- answered --- is the delivered revision's


def test_a_fix_that_meets_the_contract_is_not_re_asked(conn):
    code, out, row, worker, chat = _relay(conn, claude=[BUILD, REVISION, GOOD_FIX], chat=[ATTACKS, FIX_LIST, "PASS"])
    assert [c["call_id"].removeprefix(row["task_id"]) for c in log.calls_for(conn, row["task_id"])
            if c["kind"] == "fix"] == ["-f1"]


def test_a_fix_on_any_other_preset_is_never_read_with_the_revision_contract(conn):
    from tests.test_relay import CONFIG, Chat, Clock, GOOD_NOTE, RelayHook, Scripted
    hook, worker, chat, clock = RelayHook(s1=GOOD_NOTE), Scripted("Built.", "Fixed.\n## Answered\n7. x"), \
        Chat("FIX\n1. Add a source.", "PASS"), Clock()
    cli.cmd_relay("research-build", TASK, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                  settings_paths=[], post=hook.post, worker=worker, chatgpt=chat, codex_login=lambda: True,
                  fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True, out=lambda *_: None)
    row = log.recent_tasks(conn)[0]
    assert [c["kind"] for c in log.calls_for(conn, row["task_id"])].count("fix") == 1 and row["check_state"] == "fixed"


def test_a_stopped_fix_re_ask_resumes_as_a_fresh_fix_round(conn):
    limit = WorkerError("plan limit on claude: You've hit your session limit", code="plan_limit")
    code, out, row, worker, chat = _relay(conn, claude=[BUILD, REVISION, BAD_FIX, limit], chat=[ATTACKS, FIX_LIST])
    assert "Run: sr resume" in out and "(continues with chatgpt)" in out
    calls = log.calls_for(conn, row["task_id"])
    preset = cli.presets.for_task(row, LOADED)[0]
    plan = resume.decide(row, calls, live=ROSTER.live, preset=preset)
    assert plan.ok and (plan.kind, plan.substitute, plan.checker) == ("fix", "chatgpt", "claude")
    view = {**dict(row), "status": "queued", "agent": plan.agent, "checker": plan.checker,
            "check_state": plan.check_state, "check_note": plan.check_note, "result": None, "failed_stage": None}
    prompt, *_ = cli._resume_call(view, calls, plan, preset)
    assert prompt == checking.fix_prompt(TASK, REVISION, "1. Attack 1 is neither fixed nor answered.", prior=ATTACKS,
                                         prior_label=relay.ATTACK_LIST_LABEL, prior_lines=[relay.REDTEAM_FIX_LINE],
                                         search=True, count=True)
    assert BAD_FIX not in prompt and "Not relevant" not in prompt
