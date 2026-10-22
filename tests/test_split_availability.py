"""Build brief 24, B5 (decisions 2, 3, 4 and 14): a split with availability. Claude plans and joins every split and is
required (A4); ChatGPT checks the integration when it is available, and without it the integration is delivered
unchecked, said so on the row from the start. Each piece is routed at the yes by the same function as any routed task,
with the full check; the plan screen and `sr show --json` preview each piece's route from what runs nothing. Fakes
only; every secret here is fake."""
import json

import pytest

from router import __main__ as cli
from router import availability, jsonview, log
from tests.test_loop import Clock, Scripted
from tests.test_relay import CONFIG, ROSTER, Chat, RelayHook
from tests.test_routing_availability import WHY, Gate, _table
from tests.test_split_approve import JOIN, P1, P2, PLAN, TASK, Ask, Jev, _pieces, _split_row

# The owner, 21 Oct: x_social_pulse is Grok Bot's alone, so the stand-in piece is Meta research
XPULSE = {"status": "ok", "label": "meta_social_trends", "confidence": 0.95, "needs_split": 0.1, "tokens": 0}


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _split(conn, gate, *, ask=None, jev=None, claude=(PLAN,), chatgpt=()):
    lines, clock, hook = [], Clock(), RelayHook()
    worker, chat = Scripted(*claude), Chat(*chatgpt)
    code = cli.cmd_split(TASK, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=jev or Jev(), ask=ask, post=hook.post, worker=worker, chatgpt=chat, codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=False, available=gate,
                         out=lines.append)
    return code, lines, worker, chat, hook


def test_without_chatgpt_the_split_runs_and_says_its_integration_will_be_unchecked(conn):
    code, lines, worker, chat, hook = _split(conn, Gate({"chatgpt"}))
    row = _split_row(conn)
    note = f"no other agent available to check ({WHY['chatgpt']})"
    assert (row["agent"], row["checker"], row["check_state"]) == ("claude", None, "unchecked")
    assert lines[0].endswith(f"claude joins the results; unchecked: {note}.")
    assert (row["status"], row["check_note"]) == ("returned", log.AWAITING_APPROVAL)  # it waits at its plan as ever


def test_the_integrations_checker_is_asked_again_when_it_starts(conn):
    code, lines, worker, chat, hook = _split(conn, Gate({"chatgpt"}), ask=Ask("y"),
                                            claude=(PLAN, "the intro", "the checklist", "the joined result"))
    row = _split_row(conn)
    note = f"no other agent available to check ({WHY['chatgpt']})"
    assert (row["status"], row["checker"], row["check_state"], row["check_note"]) == ("done", None, "unchecked", note)
    assert f"All pieces are in. claude joins them; unchecked: {note}." in lines and chat.prompts == []


def test_with_chatgpt_up_its_checker_is_chatgpt_as_before(conn):
    _split(conn, Gate())
    row = _split_row(conn)
    assert (row["checker"], row["check_state"]) == ("chatgpt", "pending")


def test_each_piece_is_routed_at_the_yes_with_availability_and_the_screen_previews_it(conn, monkeypatch, tmp_path):
    from router import settings
    local = tmp_path / "bare.local.json"
    local.write_text("{}")
    monkeypatch.setattr(settings, "LOCAL_PATH", local)  # Grok Bot isn't set up: the preview sees it without a check
    jev = Jev({P1: XPULSE})
    code, lines, worker, chat, hook = _split(conn, Gate({"grok"}), ask=Ask("y"), jev=jev,
                                            chatgpt=("the X bullets", "PASS", "PASS"), claude=(PLAN, "PASS", "the checklist"))
    screen = "\n".join(lines)
    assert "meta_social_trends · chatgpt / claude" in screen    # the preview: Grok Bot out, ChatGPT stands in
    one, two = sorted(_pieces(conn), key=lambda r: r["rowid"] if "rowid" in r.keys() else r["n"])
    assert (one["agent"], one["route_reason"]) == ("chatgpt", f"stand-in for grok: {WHY['grok']}")  # the full check
    assert hook.sent == []                                       # nothing went to Grok Bot


def test_show_json_previews_a_piece_from_what_runs_nothing(conn, monkeypatch, tmp_path):
    from router import settings
    jev = Jev({P1: XPULSE})
    _split(conn, Gate(), jev=jev)  # no terminal: it stops at the plan, each piece labeled
    row = _split_row(conn)
    local = tmp_path / "bare.local.json"
    local.write_text("{}")
    monkeypatch.setattr(settings, "LOCAL_PATH", local)           # Grok Bot isn't set up any more
    preview = cli.preview_availability(ROSTER, CONFIG)
    assert preview["grok"].why == "Grok Bot isn't set up: no inbox repo in settings"
    view = jsonview.show_view(conn, row, roster=ROSTER, available=preview)
    assert view["pieces"][0]["route"]["agent"] == "chatgpt" and view["pieces"][1]["route"]["agent"] == "claude"
