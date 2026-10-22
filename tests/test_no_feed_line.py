"""Build brief 24, B2 (decision 9): X and Meta research done by another agent. A stand-in (or a takeover) on
`x_social_pulse` or `meta_social_trends` gets one added prompt line, on its first call, that call's re-ask and its fix
round: it has no live X or Meta feed, must name where each claim came from, and must say when the open web could not
show what people are saying now. The one new prompt line of the brief: never on Grok Bot's own call, never on an
override, never on a check, never on another skill. Every other prompt is byte for byte as before (the brief 15
snapshots, tests/test_search_every_call.py and friends, pass untouched). Since the owner's decision of 21 Oct
x_social_pulse has no stand-in and is never taken over, so a new task gets the line on Meta research only; an X task
logged before then (a stand-in such as F's #106) keeps it. Fakes only."""
import pytest

from router import __main__ as cli
from router import checking, log
from tests.helpers import fake_label, shipped_roster
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_relay import CONFIG, Chat
from tests.test_routing_availability import Gate

ROSTER = shipped_roster()
LINE = ("You have no live feed of X or Meta posts, only web search. Name where each claim came from, and say plainly "
        "when the open web could not show what people are saying now.")


def jev(label):
    return {"status": "ok", "label": label, "confidence": 0.95, "needs_split": 0.1, "tokens": 0}


def _route(task, label, gate, *, worker, chatgpt, hook=None):
    conn, lines, clock, hook = log.init_db(":memory:"), [], Clock(), hook or Webhook()
    code = cli.cmd_route(task, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=fake_label(label), post=hook.post, worker=worker, chatgpt=chatgpt,
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=True, available=gate, out=lines.append)
    return code, lines, log.recent_tasks(conn)[0], hook


def test_the_line_is_the_one_the_owner_approved():
    assert checking.NO_FEED_LINE == LINE


@pytest.mark.parametrize("skill", ["meta_social_trends"])  # x_social_pulse has no stand-in: Grok's alone (the owner, 21 Oct)
def test_a_stand_in_for_grok_gets_the_line_on_its_first_call_and_fix_round_only(skill):
    chat, worker = Chat("first pass", "fixed pass"), Scripted("FIX\n1. name the source of bullet 2", "PASS")
    code, lines, row, _ = _route("what are people on Instagram saying about trays", jev(skill), Gate({"grok"}),
                                 worker=worker, chatgpt=chat)
    assert (row["agent"], row["checker"], row["check_state"]) == ("chatgpt", "claude", "fixed")
    do, fix = chat.prompts
    assert do.count(LINE) == 1 and fix.count(LINE) == 1
    assert do.index(checking.SEARCH_LINE_GENERAL) < do.index(LINE)            # after the search line
    assert fix.index(LINE) < fix.index(checking.FIX_REPLY_LINE)                  # before the reply line and the blocks
    assert all(LINE not in p for p in worker.prompts)                            # the checker never gets it


def test_grok_bots_own_call_never_gets_it():
    hook = Webhook(do="bullet one\nbullet two\nbullet three")
    code, lines, row, hook = _route("what are people on X saying about trays", jev("x_social_pulse"), Gate(),
                                    worker=Scripted("PASS"), chatgpt=Chat("PASS"), hook=hook)
    assert row["agent"] == "grok" and hook.sent and all(LINE not in payload["task"] for payload in hook.sent)


def test_an_override_and_another_skills_stand_in_never_get_it():
    chat = Chat("an answer", "PASS")
    _route("@chatgpt what are people on X saying about trays", jev("x_social_pulse"), Gate(), worker=Scripted("PASS"),
           chatgpt=chat)
    assert all(LINE not in p for p in chat.prompts)
    worker = Scripted("an answer")
    _route("find sources on trays", jev("web_research"), Gate({"chatgpt"}), worker=worker, chatgpt=Chat())
    assert all(LINE not in p for p in worker.prompts)


def test_no_feed_reads_the_row_alone():
    row = {"skill": "x_social_pulse", "route_reason": "best"}   # an X row by another agent: logged before 21 Oct
    assert checking.no_feed(row, "chatgpt") and checking.no_feed(row, "claude") and not checking.no_feed(row, "grok")
    assert not checking.no_feed({**row, "route_reason": "override"}, "chatgpt")
    assert not checking.no_feed({"skill": "writing", "route_reason": "best"}, "chatgpt")
    assert not checking.no_feed({"skill": None, "route_reason": "relay"}, "chatgpt")


def test_a_fallbacks_redo_never_gets_it():
    row = {"skill": "x_social_pulse", "route_reason": "best"}
    assert not checking.no_feed({**row, "route_reason": checking.FALLBACK_VIEW}, "chatgpt")   # the redo's own call
    assert not checking.no_feed(row, "chatgpt", calls=[{"fallback_of": "sr-1"}])              # its fix round after
