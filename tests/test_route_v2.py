"""route in version 2: Jev's label (or the owner's answer) picks the skill, the skill table picks
the doer, and every unchecked result says so. Every secret here is fake."""
import pytest

from router import __main__ as cli
from router import log
from tests.helpers import add_row, fake_label, grok_era_roster, roster_with, shipped_roster

CONFIG = {"GROK_WEBHOOK_URL": "https://example.invalid/hook", "GROK_WEBHOOK_KEY": "FAKE-KEY-123"}
ROSTER = shipped_roster()
GROK_ERA = grok_era_roster()  # before ChatGPT went live: web_research went to Grok (the stand-in), checked by Claude
SKILL_NUMBER = {key: n for n, key in enumerate(ROSTER.skill_order, 1)}


def ok(skill, confidence=0.93):
    return {"status": "ok", "label": skill, "confidence": confidence, "needs_split": 0.1, "tokens": 764}


LOW = {"status": "below_floor", "label": "web_research", "confidence": 0.62, "needs_split": 0.4, "tokens": 812}


class _Reply:
    status_code = 200

    def json(self):
        return {"success": True, "runUuid": "uuid-abc"}


class Recorder:
    def __init__(self, value=None, raises=None):
        self.value, self.raises, self.calls = value, raises, []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.raises:
            raise self.raises
        return self.value


class Answers:
    """Fake keyboard: each ask() returns the next answer, or raises it if it's an exception."""

    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException) or isinstance(answer, type):
            raise answer
        return answer


def _never_asked(prompt):
    raise AssertionError("the router must not ask here")


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _route(conn, task, jev, *, ask=_never_asked, worker=None, post=None, roster=None):
    lines = []
    worker = worker or Recorder("the answer")
    post = post or Recorder(_Reply())
    try:
        code = cli.cmd_route(
            task, conn=conn, config=CONFIG, roster=roster or ROSTER, environ={}, settings_paths=[],
            label=fake_label(jev), post=post, worker=worker, ask=ask, out=lines.append,
        )
    except KeyboardInterrupt:
        pytest.fail("KeyboardInterrupt escaped cmd_route")
    rows = log.recent_tasks(conn)
    assert len(rows) == 1, "one row per task"
    return code, "\n".join(lines), rows[0], worker, post


# ---------- Jev's confident label picks the doer ----------

def test_a_confident_label_is_routed_by_the_skill_table(conn):
    code, out, row, worker, post = _route(conn, "find sources on the new EU AI rules", ok("web_research"), roster=GROK_ERA)
    assert code == 0 and len(post.calls) == 1 and worker.calls == []
    # brief 24 (decision 3): the interim is a stand-in like any other, and the row says for whom and why
    assert (row["skill"], row["skill_source"], row["agent"], row["route_reason"]) == (
        "web_research", "jev", "grok", "stand-in for chatgpt: ChatGPT is off: not live in config/agents.json")
    assert (row["checker"], row["check_state"], row["status"]) == ("claude", "pending", "sent")
    assert "web_research" in out and "0.93" in out and "grok" in out and "chatgpt" in out


def test_a_result_that_no_one_checked_says_UNCHECKED(conn):
    code, out, row, _, _ = _route(conn, "write a cover letter", ok("writing"), roster=GROK_ERA)
    assert code == 0 and row["check_state"] == "unchecked"
    assert out.index("the answer") < out.index("UNCHECKED")


def test_a_quick_answer_result_has_no_UNCHECKED_line(conn):
    code, out, row, _, _ = _route(conn, "what is 15% of 240", ok("quick_answer"))
    assert code == 0 and (row["agent"], row["checker"], row["check_state"]) == ("claude", None, "not_needed")
    assert "the answer" in out and "UNCHECKED" not in out


# ---------- tasks that come back ----------

@pytest.mark.parametrize("skill, reason", [
    ("computer_use", "returned: skill not routed in version 2"),
])
def test_a_task_no_live_agent_can_do_comes_back(conn, skill, reason):
    code, out, row, worker, post = _route(conn, "do it", ok(skill))
    assert code == 4 and worker.calls == [] and post.calls == []
    assert (row["status"], row["route_reason"], row["skill"], row["agent"]) == ("returned", reason, skill, None)
    assert "Nothing was sent to an agent." in out and skill in out and "0.93" in out


@pytest.mark.parametrize("jev, shown", [
    (LOW, "0.62"),
    ({"status": "none_of_these", "label": "none_of_these", "confidence": 0.91, "tokens": 700}, "none_of_these"),
    ({"status": "error", "error": "TypeSafeAuthenticationError", "tokens": 0}, "TypeSafeAuthenticationError"),
    ({"status": "over_cap"}, "1,000,000"),
])
def test_with_no_terminal_a_task_that_needs_a_label_comes_back(conn, jev, shown):
    code, out, row, worker, post = _route(conn, "look this up", jev, ask=None)
    assert code == 4 and worker.calls == [] and post.calls == []
    assert (row["status"], row["route_reason"], row["skill"]) == ("returned", "returned: needs your label", None)
    assert shown in out and "Nothing was sent to an agent." in out


# ---------- asking the owner ----------

def test_in_a_terminal_the_router_asks_and_logs_the_answer(conn):
    ask = Answers(str(SKILL_NUMBER["code"]))
    code, out, row, worker, _ = _route(conn, "fix my script", LOW, ask=ask)
    assert code == 0 and len(worker.calls) == 1 and len(ask.prompts) == 1
    assert (row["skill"], row["skill_source"], row["agent"], row["route_reason"]) == ("code", "owner", "claude", "best")
    assert (row["jev_label"], row["jev_confidence"], row["jev_tokens"]) == ("web_research", 0.62, 812)
    assert "web_research" in out and "0.62" in out and "0.8" in out
    for key in ROSTER.skill_order:
        assert f"{SKILL_NUMBER[key]:>2}  {key}" in out
    assert "0  none of these" in out


def test_a_skill_name_is_an_answer_too(conn):
    code, _, row, _, _ = _route(conn, "write me a poem", LOW, ask=Answers("  Writing "))
    assert code == 0 and (row["skill"], row["skill_source"]) == ("writing", "owner")


def test_two_bad_answers_then_a_good_one(conn):
    code, out, row, _, _ = _route(conn, "explain DNS", LOW, ask=Answers(str(len(ROSTER.skill_order) + 1), "banana", "quick_answer"))  # one past the last number: 12 is recall since table 3.4
    assert code == 0 and row["skill"] == "quick_answer" and out.count("Not a choice") == 2


def test_three_bad_answers_send_the_task_back(conn):
    code, out, row, worker, _ = _route(conn, "explain DNS", LOW, ask=Answers("x", "99", ""))
    assert code == 4 and worker.calls == []
    assert (row["status"], row["route_reason"]) == ("returned", "returned: no valid answer")


@pytest.mark.parametrize("answer", ["0", "none", "None_Of_These"])
def test_answer_0_or_none_sends_the_task_back(conn, answer):
    code, out, row, worker, _ = _route(conn, "remind me at 5", LOW, ask=Answers(answer))
    assert code == 4 and worker.calls == []
    assert (row["status"], row["route_reason"], row["skill"]) == ("returned", "returned: no skill", None)


def test_ctrl_c_at_the_question_cancels_the_task_and_keeps_jevs_row(conn):
    code, out, row, worker, _ = _route(conn, "explain DNS", LOW, ask=Answers(KeyboardInterrupt))
    assert code == 130 and worker.calls == []
    assert (row["status"], row["jev_tokens"]) == ("cancelled", 812)


def test_end_of_input_at_the_question_counts_as_no_answer(conn):
    code, _, row, _, _ = _route(conn, "explain DNS", LOW, ask=Answers(EOFError))
    assert code == 4 and row["route_reason"] == "returned: no valid answer"


def test_a_chosen_skill_whose_doer_is_not_live_goes_to_its_stand_in(conn):
    # Brief 24 (decision 3): with Grok off, the skill's second agent stands in (it came back `doer not live` before);
    # only make_media and x_social_pulse, Grok's alone (the owner, 21 Oct), still come back
    code, out, row, worker, _ = _route(conn, "what is Instagram saying about it", LOW, ask=Answers("meta_social_trends"),
                                       roster=roster_with(grok=False))
    assert (row["agent"], row["skill"], row["skill_source"]) == ("chatgpt", "meta_social_trends", "owner")
    assert row["route_reason"] == "stand-in for grok: Grok Bot is off: not live in config/agents.json"
    second = log.init_db(":memory:")  # `_route` reads one row per log
    code, out, row, worker, _ = _route(second, "make an image of a tray", LOW, ask=Answers("make_media"),
                                       roster=roster_with(grok=False))
    assert code == 4 and worker.calls == []
    assert (row["route_reason"], row["reason_code"]) == (
        "returned: make_media needs Grok Bot: Grok Bot is off: not live in config/agents.json", "unavailable")


def test_a_cancel_from_another_window_while_asking_is_reported(conn):
    def ask(prompt):
        log.set_cancelled(conn, log.recent_tasks(conn)[0]["task_id"])
        return "0"

    code, out, row, worker, _ = _route(conn, "explain DNS", LOW, ask=ask)
    assert code == 1 and row["status"] == "cancelled" and "cancelled" in out


# ---------- overrides ----------

def test_an_override_never_asks_and_runs_unchecked(conn):
    code, out, row, worker, _ = _route(conn, "@claude explain DNS", LOW)
    assert code == 0 and len(worker.calls) == 1
    assert (row["agent"], row["route_reason"], row["skill"], row["checker"], row["check_state"]) == (
        "claude", "override", None, None, "unchecked")
    assert row["check_note"] == "override with no usable label"
    assert "UNCHECKED: override with no usable label" in out


def test_an_override_where_the_named_agent_is_the_second(conn):
    code, _, row, _, _ = _route(conn, "@claude check this claim", ok("web_research"))
    assert (row["agent"], row["skill"], row["checker"], row["check_state"]) == (
        "claude", "web_research", "chatgpt", "unchecked")


# ---------- what check, show and log print ----------

def _routed(conn, task_id, check_state, agent="grok"):
    log.add_task(conn, task_id, "t", "cli", ok("web_research"))
    log.set_route(conn, task_id, agents=ROSTER.names, agent=agent, route_reason="interim", skill="web_research",
                  skill_source="jev", checker="claude" if check_state == "unchecked" else None,
                  check_state=check_state)


def test_check_marks_each_unchecked_result(conn):
    _routed(conn, "sr-u", "unchecked")
    _routed(conn, "sr-n", "not_needed")
    for task_id in ("sr-u", "sr-n"):
        log.set_sent(conn, task_id, "uuid")
    lines = []
    issues = [{"number": 1, "title": "sr-u", "body": "checked? no", "url": "u1"},
              {"number": 2, "title": "sr-n", "body": "fine as is", "url": "u2"}]
    cli.cmd_check(conn=conn, config=CONFIG, fetch=lambda: issues, close=lambda n: None, out=lines.append)
    out = "\n".join(lines)
    assert out.count("UNCHECKED") == 1 and out.index("checked? no") < out.index("UNCHECKED") < out.index("fine as is")


def test_show_prints_the_label_its_source_the_doer_the_checker_and_the_check_state(conn):
    _routed(conn, "sr-1", "unchecked")
    log.set_done(conn, "sr-1", "the result")
    lines = []
    assert cli.cmd_show(conn=conn, words=["1"], out=lines.append) == 0
    out = "\n".join(lines)
    for text in ["web_research", "0.93", "jev", "grok", "interim", "claude", "unchecked", "the result", "UNCHECKED"]:
        assert text in out, text


def test_show_says_a_returned_task_came_back(conn):
    log.add_task(conn, "sr-1", "t", "cli", LOW)
    log.set_returned(conn, "sr-1", "returned: needs your label")
    lines = []
    cli.cmd_show(conn=conn, words=["1"], out=lines.append)
    out = "\n".join(lines)
    assert "came back" in out and "needs your label" in out and "Nothing was sent" in out


def test_log_has_skill_and_check_columns(conn):
    _routed(conn, "sr-1", "unchecked")
    add_row(conn, "sr-2")
    lines = []
    cli.cmd_log(conn=conn, out=lines.append)
    assert "skill" in lines[0] and "check" in lines[0]
    assert "web_research" in lines[2] and "unchecked" in lines[2]


# ---------- main ----------

def _capture_route(monkeypatch, can_ask):
    seen = {}
    monkeypatch.setattr(cli.safety, "prepare_workspace", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_can_ask", lambda: can_ask)
    monkeypatch.setattr(cli, "cmd_route", lambda task, **kw: seen.update(kw) or 0)
    assert cli.main(["route", "hi"], platform="darwin") == 0
    return seen


def test_main_asks_only_when_input_and_output_are_a_terminal(monkeypatch):
    assert _capture_route(monkeypatch, True)["ask"] is input
    assert _capture_route(monkeypatch, False)["ask"] is None


def test_main_no_longer_passes_a_classifier(monkeypatch):
    assert "classify" not in _capture_route(monkeypatch, False)


def test_exit_code_4_is_documented():
    assert "4 the task came back to you" in cli.__doc__
