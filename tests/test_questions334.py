"""Build brief 33.4, Q1 (decisions 2, 2b, 3, 4 and 17): a new plan's planner may ask up to 3 questions instead of planning.
The shape is read by code; a miss gets one re-ask; a Questions answer ends stage 1 (nothing attacked or checked while it
waits); the call that carries the answers may not ask again; a revision never asks. `SR_INJECT_QUESTIONS=plan` answers
stage 1 with three fixed questions on a scratch log and is refused on the real one. Fake agents; every value is fake."""
import pytest

from router import log, plan, plan_limit
from tests.test_filemode_flow import conn, project, runner  # noqa: F401 (fixtures)
from tests.test_plan_chain import REVISED, ReadWorker, World
from tests.test_plan_contract import GOOD, MENU, ONE

QUESTIONS = """## Questions
1. Which units come after temperature?
A. Length
B. Weight
C. Volume
guess: A
2. How does it take its input?
A. Arguments
B. A prompt
guess: B
"""


def _read(text, **kw):
    return plan.read(text, MENU, questions=True, **kw)


def _with(q="Which one?", options=("A. Yes", "B. No"), guess="guess: A"):
    return "\n".join(["## Questions", f"1. {q}", *options, *([guess] if guess else [])])


def test_the_reader_gives_each_question_its_options_and_its_guess():
    parsed, missing = _read(QUESTIONS)
    assert missing == []
    assert parsed.questions == [
        {"k": 1, "text": "Which units come after temperature?", "guess": "A",
         "options": [{"letter": "A", "text": "Length"}, {"letter": "B", "text": "Weight"}, {"letter": "C", "text": "Volume"}]},
        {"k": 2, "text": "How does it take its input?", "guess": "B",
         "options": [{"letter": "A", "text": "Arguments"}, {"letter": "B", "text": "A prompt"}]}]


@pytest.mark.parametrize("text, word", [
    ("## Questions\n", "need 1 to 3"),
    ("\n".join(["## Questions"] + [f"{k}. Q{k}?\nA. x\nB. y\nguess: A" for k in range(1, 5)]), "need 1 to 3"),
    (_with(q="x" * 300), "under 300"),
    (_with(options=("A. Only one",)), "2 to 4 options"),
    (_with(options=("A. a", "B. b", "C. c", "D. d", "E. e")), "2 to 4 options"),
    (_with(options=("A. Yes", "C. No")), "lettered"),
    (_with(options=("A. " + "x" * 120, "B. No")), "under 120"),
    (_with(guess=None), "no `guess:` line"),
    (_with(guess="guess: C"), "names C"),
    (_with(guess="guess: A\nguess: B"), "2 `guess:` lines"),
    (_with() + "\nAnd a note after.", "more line"),
    (_with() + "\n\n## Steps\n1. x", "not both"),
    (_with() + "\n\n## One step\nwhy\ntask: x\nteam: route", "not both"),
    (_with() + "\n\n## Notes\nx", "nothing else"),
])
def test_each_miss_of_the_shape_is_named(text, word):
    parsed, missing = _read(text)
    assert parsed.questions is None
    assert any(word in m for m in missing), missing


def test_the_limits_hold_just_under_them():
    assert _read(_with(q="x" * 299, options=("A. " + "y" * 119, "B. No")))[1] == []


def test_questions_are_refused_where_they_may_not_be_asked():
    assert any("not allowed now" in m for m in plan.read(QUESTIONS, MENU)[1])
    assert any("not allowed on a revision" in m for m in plan.read(QUESTIONS, MENU, questions=True, revision=1)[1])
    assert plan.one_step_of(QUESTIONS, MENU) is None


def test_the_answers_call_may_plan_or_give_one_step_and_a_plan_reads_as_before():
    assert plan.contract(GOOD, MENU, questions=False) == []
    assert plan.contract(ONE, MENU, questions=False) == []
    assert plan.contract(QUESTIONS, MENU, questions=False) != []
    assert plan.contract(QUESTIONS, MENU, questions=True) == []


def test_may_ask_is_a_new_plan_with_no_answers_yet():
    assert plan.may_ask(plan.new_record(MENU))
    assert not plan.may_ask({**plan.new_record(MENU), "revises": "x", "inherited": 0})
    assert not plan.may_ask({**plan.new_record(MENU), "answers": [{"k": 1}]})


# ---------- the chain ----------

def _asked(conn, **kw):
    w = World(worker=ReadWorker(QUESTIONS, GOOD, REVISED), **kw)
    code, row = w.plan(conn)
    return w, code, log.get_task(conn, row["task_id"])


def test_a_questions_answer_ends_stage_1_with_nothing_attacked_or_checked(project, conn, runner):
    w, code, row = _asked(conn)
    assert code == 0, w.said
    assert row["status"] == "returned" and row["check_note"] == log.AWAITING_ANSWERS
    assert len(w.worker.calls) == 1 and w.chat.prompts == [] and w.cursor.prompts == []
    assert [(c["kind"], c["stage"], c["agent"]) for c in log.calls_for(conn, row["task_id"])] == [("questions", 1, "claude")]
    record = plan.record_of(row)
    assert [q["guess"] for q in record["questions"]] == ["A", "B"] and record["answers"] is None
    from router import copies
    assert copies.exists(row["task_id"])  # its copy is kept while it waits


def test_a_bad_questions_answer_gets_one_re_ask_then_the_plan_fails_and_its_copy_goes(project, conn, runner):
    bad = _with(guess="guess: Z")
    w = World(worker=ReadWorker(bad, bad))
    code, row = w.plan(conn)
    row = log.get_task(conn, row["task_id"])
    assert row["status"] == "failed", w.said
    assert [(c["kind"], c["stage"]) for c in log.calls_for(conn, row["task_id"])] == [("stage", 1), ("reask", 1)]
    assert "names Z" in w.worker.calls[1]["prompt"]
    from router import copies
    assert not copies.exists(row["task_id"])


def test_a_re_ask_may_come_back_with_good_questions(project, conn, runner):
    w = World(worker=ReadWorker(_with(guess=None), QUESTIONS))
    code, row = w.plan(conn)
    row = log.get_task(conn, row["task_id"])
    assert row["check_note"] == log.AWAITING_ANSWERS, w.said
    assert [(c["kind"], c["stage"]) for c in log.calls_for(conn, row["task_id"])] == [("questions", 1), ("questions", 1)]


def test_the_planners_prompt_says_ask_only_if_an_answer_changes_the_steps(project, conn, runner):
    w = World()
    w.plan(conn)
    first = w.worker.calls[0]["prompt"]
    assert "ask only if an answer changes the steps; if a reasonable guess will do, plan" in first.lower()
    assert plan.QUESTIONS_LINE in first
    assert plan.QUESTIONS_LINE not in w.worker.calls[1]["prompt"]  # the revise never asks


def test_terminal_prints_the_questions_and_the_exact_command_and_asks_nothing(project, conn, runner):
    w, code, row = _asked(conn)
    assert "1. Which units come after temperature?" in w.said and "A. Length" in w.said
    assert "(guess)" in w.said
    assert f"sr plan --answer {row['n']} --pick 1=<letter> --pick 2=<letter>" in w.said
    assert f"sr plan --answer {row['n']} --best-guess" in w.said


# ---------- the hook (decision 17) ----------

def test_the_hook_answers_stage_1_with_three_fixed_questions_and_no_model_call(project, conn, runner):
    w = World(worker=ReadWorker())
    code, row = w.plan(conn, inject_questions=True)
    row = log.get_task(conn, row["task_id"])
    assert row["check_note"] == log.AWAITING_ANSWERS, w.said
    assert w.worker.calls == []
    assert len(plan.record_of(row)["questions"]) == 3


def test_the_fixed_questions_meet_the_contract():
    assert plan.read(plan.INJECTED_QUESTIONS, MENU, questions=True)[1] == []


def test_the_hook_is_refused_on_the_real_log(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_limit, "is_real_log", lambda *a, **k: True)
    with pytest.raises(plan_limit.InjectRefused, match="test-only"):
        plan_limit.questions_injected("plan", tmp_path / "router.db", root=tmp_path)


def test_the_hook_runs_on_a_scratch_log_and_names_plan_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_limit, "is_real_log", lambda *a, **k: False)
    assert plan_limit.questions_injected("plan", tmp_path / "router.db", root=tmp_path)
    with pytest.raises(plan_limit.InjectRefused, match="names plan"):
        plan_limit.questions_injected("route", tmp_path / "router.db", root=tmp_path)
