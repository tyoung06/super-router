"""Build brief 33.4, Q2 (decisions 1b and 5): a plan with questions waits on the owner as `waiting_on: answers`: it holds the
project, writes no entry, What now? and the open-task refusal say so, Cancel ends it and removes the copy. `sr plan
--answer` takes the answers (a chip, typed words or the planner's guesses) and the plan goes on from them, once. The pick
gap closes beside it: a versus or tied vote awaiting its pick holds its project. Fake agents; every value is fake."""
import pytest

from router import __main__ as cli
from router import copies, intake, log, page_commands, plan, projects, state, whatnow
from tests.helpers import shipped_roster
from tests.test_filemode_flow import conn, project, runner  # noqa: F401 (fixtures)
from tests.test_loop import Clock
from tests.test_plan_chain import LOADED, REVISED, ROSTER, ReadWorker, World
from tests.test_plan_contract import GOOD, ONE
from tests.test_questions334 import QUESTIONS
from tests.test_relay import CONFIG, RelayHook


def _asked(conn, *replies):
    w = World(worker=ReadWorker(QUESTIONS, *(replies or (GOOD, REVISED))))
    code, row = w.plan(conn)
    assert code == 0, w.said
    return w, log.get_task(conn, row["task_id"])


def _answer(w, conn, row, **kw):
    clock, hook = Clock(), RelayHook()
    lines = []
    code = cli.cmd_plan_answer(str(row["n"]), conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[],
                               post=hook.post, worker=w.worker, chatgpt=w.chat, codex_login=lambda: True, cursor=w.cursor,
                               cursor_ready=w.ready, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                               wait=True, out=lines.append, **kw)
    return code, "\n".join(str(x) for x in lines), log.get_task(conn, row["task_id"])


def test_the_state_is_answers_and_it_holds_the_project(project, conn, runner):
    w, row = _asked(conn)
    calls = log.calls_for(conn, row["task_id"])
    assert state.of(row, calls).waiting_on == "answers" and not state.of(row, calls).ended
    held = log.open_task_for(conn, "garden")
    assert held is not None and held["task_id"] == row["task_id"]
    code, why = intake.project_refusal(conn, "garden")
    assert code == "project_busy" and f"task {row['n']} open (waiting for your answers)" in why


def test_what_now_rung_1_counts_the_questions(project, conn, runner):
    w, row = _asked(conn)
    found = whatnow.for_project(conn, "garden")
    assert (found["rung"], found["control"]) == (1, "open")
    assert found["words"] == f"Waiting on you: #{row['n']} · answer 2 questions"


def test_no_entry_is_written_while_it_waits(project, conn, runner):
    before = projects.read_handoff(project)
    w, row = _asked(conn)
    assert projects.read_handoff(project) == before
    assert log.handoff_of(row) in ([], None)


def test_cancel_ends_it_and_removes_the_copy(project, conn, runner):
    w, row = _asked(conn)
    assert copies.exists(row["task_id"])
    lines = []
    assert cli.cmd_cancel(conn=conn, words=[str(row["n"])], out=lines.append) == 0
    row = log.get_task(conn, row["task_id"])
    assert row["status"] == "cancelled" and not copies.exists(row["task_id"])
    assert log.open_task_for(conn, "garden") is None


def test_discard_is_refused_while_it_waits(project, conn, runner):
    w, row = _asked(conn)
    lines = []
    assert cli.cmd_land([str(row["n"])], conn=conn, config=CONFIG, verb="discard", out=lines.append) == 2
    assert copies.exists(row["task_id"])


def test_it_never_times_out_a_check_leaves_it(project, conn, runner):
    w, row = _asked(conn)
    assert row["task_id"] not in [r["task_id"] for r in log.open_tasks(conn)]


# ---------- sr plan --answer ----------

def test_a_chip_and_typed_words_answer_it_and_the_plan_goes_on_to_land(project, conn, runner):
    w, row = _asked(conn)
    code, said, row = _answer(w, conn, row, picks=["1=b"], others=["2=  with   flags "])
    assert code == 0, said
    record = plan.record_of(row)
    assert record["answers"] == [
        {"k": 1, "question": "Which units come after temperature?", "answer": "Weight", "how": "picked", "letter": "B"},
        {"k": 2, "question": "How does it take its input?", "answer": "with flags", "how": "other", "letter": None}]
    assert log.project_files_of(row)["state"] == "waiting"
    calls = log.calls_for(conn, row["task_id"])
    assert [(c["kind"], c["stage"], c["role"]) for c in calls] == [
        ("questions", 1, "plan"), ("stage", 1, "plan"), ("stage", 2, "attack"), ("stage", 3, "attack"),
        ("stage", 4, "revise"), ("check", None, None)]
    assert len({c["call_id"] for c in calls}) == len(calls)


def test_use_your_best_guess_takes_every_guess_with_one_stage_1_call_and_no_second_wait(project, conn, runner):
    w, row = _asked(conn)
    code, said, row = _answer(w, conn, row, best_guess=True)
    assert code == 0, said
    answers = plan.record_of(row)["answers"]
    assert [(a["how"], a["letter"], a["answer"]) for a in answers] == [("guess", "A", "Length"), ("guess", "B", "A prompt")]
    assert [c["kind"] for c in log.calls_for(conn, row["task_id"])].count("stage") == 4
    assert log.project_files_of(row)["state"] == "waiting" and row["check_note"] != log.AWAITING_ANSWERS


def test_the_answers_call_may_return_one_step(project, conn, runner):
    w, row = _asked(conn, ONE)
    code, said, row = _answer(w, conn, row, best_guess=True)
    assert row["status"] == "failed" and row["result"].startswith(plan.ONE_STEP_REASON), said
    assert not copies.exists(row["task_id"])


def test_the_answers_call_returning_questions_is_a_contract_miss_then_the_plan_fails_its_copy_removed(project, conn, runner):
    w, row = _asked(conn, QUESTIONS, QUESTIONS)
    code, said, row = _answer(w, conn, row, best_guess=True)
    assert row["status"] == "failed", said
    calls = log.calls_for(conn, row["task_id"])
    assert [(c["kind"], c["stage"]) for c in calls] == [("questions", 1), ("stage", 1), ("reask", 1)]
    assert "not allowed now" in w.worker.calls[2]["prompt"]
    assert not copies.exists(row["task_id"])
    assert plan.record_of(row)["answers"]


def test_a_miss_then_a_plan_on_the_answers_call_uses_its_own_re_ask(project, conn, runner):
    w, row = _asked(conn, QUESTIONS, GOOD, REVISED)
    code, said, row = _answer(w, conn, row, best_guess=True)
    assert code == 0, said
    assert log.project_files_of(row)["state"] == "waiting"


@pytest.mark.parametrize("kw, word", [
    ({"picks": ["1=A"]}, "question 2 still has no answer"),
    ({}, "questions 1, 2 still have no answer"),
    ({"picks": ["1=Z", "2=A"]}, "question 1 has no option Z"),
    ({"picks": ["9=A"]}, "there is no question 9"),
    ({"picks": ["1=A", "1=B", "2=A"]}, "more than one answer"),
    ({"picks": ["1=A", "2=A"], "others": ["2=mine"]}, "more than one answer"),
    ({"picks": ["1"]}, "--pick takes"),
    ({"picks": ["1=A"], "best_guess": True}, "--best-guess takes no"),
])
def test_each_bad_answer_is_refused_with_nothing_changed(project, conn, runner, kw, word):
    w, row = _asked(conn)
    code, said, after = _answer(w, conn, row, **kw)
    assert code == 2 and word in said, said
    assert after["status"] == "returned" and plan.record_of(after)["answers"] is None


@pytest.mark.parametrize("words, rule", [
    ("two\nlines", "one line"),
    ("x" * 401, "at most 400"),
    ("sk-ant-" + "a" * 40, "looks like a key"),
])
def test_a_typed_answer_is_checked_named_and_never_quoted(project, conn, runner, words, rule):
    w, row = _asked(conn)
    code, said, after = _answer(w, conn, row, picks=["1=A"], others=[f"2={words}"])
    assert code == 2 and rule in said, said
    assert words not in said and plan.record_of(after)["answers"] is None


def test_a_dotenv_value_is_refused_and_not_quoted():
    record = {"questions": [{"k": 1, "text": "Q", "guess": "A", "options": [{"letter": "A", "text": "x"}]}]}
    found, why = plan.answers_from(record, others=["1=the-secret-value"], secrets=("the-secret-value",))
    assert found is None and "looks like a key" in why and "the-secret-value" not in why


def test_a_task_not_waiting_is_refused(project, conn, runner):
    w = World()
    code, row = w.plan(conn)
    code, said, after = _answer(w, conn, row, best_guess=True)
    assert code == 2 and "isn't a plan waiting for your answers" in said


def test_the_json_gives_the_questions_and_the_exact_commands(project, conn, runner):
    w, row = _asked(conn)
    found = plan.questions_view(row)
    assert found["waiting"] and found["k"] == 2 and not found["planning"]
    assert found["command"] == f"sr plan --answer {row['n']} --pick 1=<letter> --pick 2=<letter>"
    assert found["best_guess_command"] == f"sr plan --answer {row['n']} --best-guess"
    assert found["asked"][0]["options"][0] == {"letter": "A", "text": "Length"}


# ---------- the page's builder ----------

TASK_ID = "sr-20261102-100000-abcd"


def test_the_builder_passes_each_typed_answer_as_one_argument():
    found = page_commands.build({"action": "plan_answer", "task_id": TASK_ID, "picks": {"1": "A"},
                                 "others": {"2": "a; rm -rf / $(x)"}}, {})
    assert found.args[:1] == ("plan",) and "--answer" in found.args
    assert found.args[-4:] == ("--pick", "1=A", "--other", "2=a; rm -rf / $(x)")


def test_the_builder_for_best_guess_and_its_refusals():
    found = page_commands.build({"action": "plan_answer", "task_id": TASK_ID, "best_guess": True}, {})
    assert found.args[-1] == "--best-guess"
    for bad in ({"picks": {"9": "A"}}, {"picks": {"1": "AA"}}, {"picks": {"1": "-x"}}, {}):
        with pytest.raises(page_commands.Refused):
            page_commands.build({"action": "plan_answer", "task_id": TASK_ID, **bad}, {})


# ---------- the pick gap (decision 5) ----------

def _waiting_vote(conn, preset, note=log.AWAITING_PICK):
    task_id = "sr-20261102-100001-abcd"
    log.add_task(conn, task_id, "x", "cli", {"status": "not_asked", "tokens": 0}, mode="relay", preset=preset, project="garden")
    log.set_awaiting_pick(conn, task_id)
    return task_id


@pytest.mark.parametrize("preset", ["versus", "vote"])
def test_a_pick_holds_its_project(conn, preset):
    task_id = _waiting_vote(conn, preset)
    assert log.open_task_for(conn, "garden")["task_id"] == task_id


def test_a_pick_taken_lets_the_project_go(conn):
    task_id = _waiting_vote(conn, "versus")
    log.set_pick(conn, task_id, agents=("claude", "chatgpt"), choice="none")
    assert log.open_task_for(conn, "garden") is None
