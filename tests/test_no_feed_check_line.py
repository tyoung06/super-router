"""Brief 24, after F (the owner's decision 1 of 21 Oct): on a stand-in's or takeover's check of X or Meta research, the
checker gets one line: the doer had no live feed, so an answer that names its sources and says plainly what the open web
could not show is an answer, judged on its evidence. In F (#106) the checker failed exactly that answer twice as a
non-answer. The line goes on the check and the re-check, right after the no-result rule it narrows; never on Grok Bot's
own work, an override, another skill, or a fallback's redo. Every other prompt is byte for byte as before: the prompt
with the line, the line taken out, is the prompt the builder makes without it (the brief 15 snapshots pass untouched).
Since the owner's decision of 21 Oct x_social_pulse has no stand-in and is never taken over: a new task gets the line on
Meta research only. Fakes only."""
import pytest

from router import __main__ as cli
from router import checking, log
from tests.helpers import fake_label, shipped_roster
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_relay import CONFIG, Chat
from tests.test_routing_availability import Gate

ROSTER = shipped_roster()
LINE = ("The doer had no live feed of X or Meta posts, only web search. An answer that names its sources and says "
        "plainly what the open web could not show is an answer: judge it on its evidence, and fail invented posts, "
        "unsourced claims, or a result that hides the gap.")
X = "what are people on X saying about rubber trays"
META = "what are people on Instagram and Facebook saying about rubber trays"


def jev(label):
    return {"status": "ok", "label": label, "confidence": 0.95, "needs_split": 0.1, "tokens": 0}


def _route(task, label, gate, *, worker, chatgpt, hook=None, wait=True):
    conn, lines, clock, hook = log.init_db(":memory:"), [], Clock(), hook or Webhook()
    cli.cmd_route(task, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=fake_label(label),
                  post=hook.post, worker=worker, chatgpt=chatgpt, codex_login=lambda: True, fetch=hook.fetch,
                  close=hook.close, sleep=clock.sleep, clock=clock, wait=wait, available=gate, out=lines.append)
    return conn, log.recent_tasks(conn)[0], lines


def test_the_line_is_the_owners_words():
    assert checking.NO_FEED_CHECK_LINE == LINE


@pytest.mark.parametrize("skill", ["meta_social_trends"])  # x_social_pulse has no stand-in: Grok's alone (the owner, 21 Oct)
def test_a_stand_ins_check_and_re_check_get_the_line_right_after_the_no_result_rule(skill):
    chat, worker = Chat("first pass", "fixed pass"), Scripted("FIX\n1. name the source of bullet 2", "PASS")
    conn, row, _ = _route(META, jev(skill), Gate({"grok"}), worker=worker, chatgpt=chat)
    assert (row["agent"], row["checker"], row["check_state"]) == ("chatgpt", "claude", "fixed")
    check, recheck = worker.prompts
    for prompt in (check, recheck):
        assert prompt.count(LINE) == 1
        assert prompt.index(checking.NO_RESULT_RULE) < prompt.index(LINE)
        assert f"{checking.NO_RESULT_RULE}\n\n{LINE}" in prompt                       # right after the rule it narrows
    assert all(LINE not in p for p in chat.prompts)                                   # never on the doer's own calls


def test_with_the_line_taken_out_the_checker_prompt_is_byte_for_byte_as_before():
    kwargs = dict(no_tools=False, claude_search=True, search=True)
    with_line = checking.checker_prompt(X, "three bullets", no_feed=True, **kwargs)
    assert with_line.replace(f"\n\n{LINE}", "", 1) == checking.checker_prompt(X, "three bullets", **kwargs)


def test_a_takeovers_check_gets_it_too():
    hook = Webhook(fail=("do",))
    worker = Scripted("PASS")
    conn, row, lines = _route(META, jev("meta_social_trends"), Gate(), worker=worker, chatgpt=Chat("Three bullets."),
                              hook=hook)
    assert row["agent"] == "chatgpt" and "took over" in "\n".join(lines)
    assert worker.prompts[0].count(LINE) == 1


def test_never_on_grok_bots_own_work_an_override_another_skill_or_a_fallback():
    hook = Webhook(do="bullet one\nbullet two\nbullet three")
    chat = Chat("PASS")
    _route(X, jev("x_social_pulse"), Gate(), worker=Scripted("PASS"), chatgpt=chat, hook=hook)
    assert row_has_no_line(chat.prompts)                                              # Grok did it; ChatGPT checked
    worker = Scripted("PASS")
    _route("@chatgpt " + X, jev("x_social_pulse"), Gate(), worker=worker, chatgpt=Chat("an answer"))
    assert row_has_no_line(worker.prompts)                                            # an override
    chat = Chat("PASS")
    _route("find sources on trays", jev("web_research"), Gate({"chatgpt"}), worker=Scripted("an answer"),
           chatgpt=chat)
    assert row_has_no_line(chat.prompts)                                              # another skill's stand-in
    row = {"skill": "x_social_pulse", "route_reason": checking.FALLBACK_VIEW, "agent": "claude"}
    assert not checking.no_feed(row, "claude")                                        # a fallback's redo, as before


def row_has_no_line(prompts):
    return all(LINE not in p for p in prompts)
