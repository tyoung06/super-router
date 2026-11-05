"""Cleanup 2, rows 8, 9 and 10: a finished run's stop words, the Auto confirm's words, and Land the run so far's words. Fakes only."""
import pytest

from router import __main__ as cli
from router import auto, log, plan, receipt
from tests.test_auto_run import CopyWorker, NO_GROK, STEP2, _approved, _auto, _route_plan, _stopped_before_2
from tests.test_filemode_flow import conn, project, runner  # noqa: F401 (fixtures)
from tests.test_plan_approval import _land


# ---------- row 8 (item 5): a finished run's stop words ----------

def test_a_run_that_stops_goes_on_and_finishes_has_no_stop_words_left(project, conn, runner):
    plan_row, run = _stopped_before_2(conn)
    assert run["route_reason"] == "returned: stop here before step 2"
    code, out, run = _auto(conn, worker=CopyWorker(STEP2))
    assert code == 0, out.message
    assert auto.run_state(run, log.auto_of(run)) == "finished"
    assert not run["route_reason"]


def test_land_the_run_so_far_keeps_its_stop_words_since_that_run_did_stop(project, conn, runner):
    plan_row, run = _stopped_before_2(conn)
    code, text = _land(conn, log.get_task(conn, run["task_id"]))
    assert code == 0, text
    assert log.get_task(conn, run["task_id"])["route_reason"] == "returned: stop here before step 2"


# ---------- row 9 (item 7): the Auto confirm's words ----------

STEPS3 = [{"k": k, "state": "open"} for k in (1, 2, 3)]
PLAN = {"task_id": "sr-p", "n": 155}


def _record(from_step=1, **extra):
    return {"n": 155, "budget": 14, "steps": [{"k": k, "state": "open" if k >= from_step else "done"} for k in (1, 2, 3)], "passed_marks": [], **extra}


def test_with_a_mark_ahead_the_span_ends_before_it():
    marked = auto.with_mark({"steps": STEPS3}, 3, True)
    found = auto.dry_run_view(PLAN, _record(from_step=2), marked)
    assert found["words"] == "Auto runs step 2 of plan #155, 14 calls at most, then stops before step 3 (stop here)."
    assert found["first_stop_here"] == 3
    two = auto.dry_run_view(PLAN, _record(), marked)
    assert two["words"] == "Auto runs steps 1 to 2 of plan #155, 14 calls at most, then stops before step 3 (stop here)."


def test_with_no_mark_the_words_stay_as_they_are():
    found = auto.dry_run_view(PLAN, _record(), {"steps": STEPS3})
    assert found["words"] == "Auto runs steps 1 to 3 of plan #155, 14 calls at most."


def test_a_mark_on_the_first_step_isnt_named_since_on_passes_it_and_the_next_mark_is():
    first = auto.with_mark({"steps": STEPS3}, 2, True)
    found = auto.dry_run_view(PLAN, _record(from_step=2), first)
    assert found["first_stop_here"] is None and "stop" not in found["words"]
    both = auto.with_mark(first, 3, True)
    found = auto.dry_run_view(PLAN, _record(from_step=2), both)
    assert found["first_stop_here"] == 3
    assert found["words"] == "Auto runs step 2 of plan #155, 14 calls at most, then stops before step 3 (stop here)."


# ---------- row 10 (item 8): Land the run so far's words ----------

def _steps_done(*done, total=3):
    return {"steps": [{"k": k, "state": "done" if k in done else "open"} for k in range(1, total + 1)]}


@pytest.mark.parametrize("code", ["stop_here", "budget", "off"])
def test_a_stop_before_a_step_names_the_steps_that_land(code):
    record = {**_steps_done(1, 2), "stop": {"code": code, "why": "x", "step": 3}}
    assert auto.so_far_words(record, "1 file changed") == ("Land the run so far: the run stopped before step 3, so steps 1 and 2 land; 1 file changed.")


def test_the_unchecked_stop_keeps_its_words():
    record = {**_steps_done(1, 2), "stop": {"code": "unchecked", "why": "x", "step": 2}}
    assert auto.so_far_words(record, "1 file changed") == ("Land the run so far: the run stopped after step 2 (delivered unchecked), so it lands as it "
                                                           "stands, that step included; 1 file changed.")


def test_one_step_three_steps_and_none_read_right():
    one = {**_steps_done(1), "stop": {"code": "off", "why": "x", "step": 2}}
    assert "so step 1 lands;" in auto.so_far_words(one, "c")
    three = {**_steps_done(1, 2, 3, total=4), "stop": {"code": "budget", "why": "x", "step": 4}}
    assert "so steps 1, 2 and 3 land;" in auto.so_far_words(three, "c")
    none = {**_steps_done(), "stop": {"code": "stop_here", "why": "x", "step": 1}}
    assert "so no step lands;" in auto.so_far_words(none, "c")


def test_a_real_stop_here_says_so_at_the_land(project, conn, runner):
    plan_row, run = _stopped_before_2(conn)
    code, text = _land(conn, log.get_task(conn, run["task_id"]))
    assert code == 0, text
    assert "the run stopped before step 2, so step 1 lands;" in text and "delivered unchecked" not in text


def test_a_real_unchecked_stop_keeps_its_words_at_the_land(project, conn, runner):
    _route_plan(conn, _approved(conn))
    code, out, run = _auto(conn, chatgpt_given=False, config=NO_GROK)
    assert code == 4 and log.auto_of(run)["stop"]["code"] == "unchecked"
    code, text = _land(conn, log.get_task(conn, run["task_id"]))
    assert code == 0, text
    assert "the run stopped after step 1 (delivered unchecked)" in text
