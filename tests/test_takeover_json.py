"""Build brief 24, C4 (decisions 7, 14 and 15; the owner's C11 and C21). `sr show --json` and `sr log --json` carry the
takeover (which call, from, to, why, its code and its call's state) and a late Grok answer (out, arrived or expired;
until when; its round file), computed from the rows; each call row names the call a takeover replaced
(`takeover_of`); the card's one line says who took over and why, in the Terminal's words. The resume offer stays only
for what is still manual. The page's minute check keeps running while a late answer may still come, and its `sr check`
may take an hour now. Through the real main with every outside thing faked."""
import json

import pytest

from router import __main__ as cli
from router import log, online, page
from tests.fixtures import json_shapes
from tests.helpers import fake_label
from tests.test_json_actions import World, jev
from tests.test_loop import Scripted, Webhook
from tests.test_page_runs import _reader
from tests.test_relay import Chat
from tests.test_resume_run import claude_limit, codex_limit
from tests.test_takeover_overdue import _backdate

POEM = "write a two-line poem about rubber trays"
# The owner's decision of 21 Oct: x_social_pulse is Grok Bot's alone (never stood in for, never taken over), so these
# stand-in, takeover and late-answer cases use meta_social_trends (Grok best, ChatGPT second).
META = "what are gardeners on Instagram saying about rubber trays"


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    w = World(monkeypatch, tmp_path, capsys)
    w.hook = Webhook()
    return w


def _show(world, n=1):
    code, out, err = world.run("show", str(n), "--json")
    assert code == 0, err
    return json.loads(out)


def test_a_takeover_is_a_record_on_the_task_and_its_call_and_the_card_says_it(world):
    world.worker, world.chatgpt = Scripted(claude_limit()), Chat("Two lines.")
    world.json("route", POEM)
    doc = _show(world)
    task_id = doc["task_id"]
    assert doc["takeover"] == {"call_id": f"{task_id}-takeover", "stopped_call": task_id, "call": "the first call",
                               "from": "claude", "to": "chatgpt", "why": "Claude hit its plan limit",
                               "code": "plan_limit", "state": "done"}
    assert [c["takeover_of"] for c in doc["calls"]] == [None, task_id]
    assert doc["card_line"] == "ChatGPT took over the first call · Claude hit its plan limit"
    assert doc["late"] is None and doc["resume"]["ok"] is False   # nothing is left for a manual resume
    row = json.loads(world.run("log", "--json")[1])["tasks"][0]
    assert (row["takeover"], row["card_line"]) == (doc["takeover"], doc["card_line"])
    json_shapes.check(doc["calls"][1], json_shapes.CALL, "$.calls[1]")


def test_an_overdue_takeover_carries_its_late_answer_out_then_arrived(world):
    world.label, world.chatgpt, world.worker = fake_label(jev("meta_social_trends")), Chat("Three bullets."), Scripted("PASS")
    world.run("route", META, "--no-wait")
    _backdate(11)
    world.run("check")
    doc = _show(world)
    assert doc["card_line"] == "ChatGPT took over the first call · Grok Bot was overdue · done without Meta"
    assert (doc["takeover"]["code"], doc["takeover"]["why"]) == ("overdue", "Grok Bot was overdue")
    late = doc["late"]
    assert (late["call_id"], late["state"], late["arrived_at"], late["round_file"]) == (doc["task_id"], "out", None, None)
    world.hook.bodies["do"] = "Gardeners like rubber trays."
    world.run("check")
    doc = _show(world)
    assert doc["late"]["state"] == "arrived" and doc["late"]["round_file"].endswith("-late-do-grok.md")
    assert doc["takeover"]["code"] == "overdue" and doc["result"] == "Three bullets."   # the late answer changed nothing


def test_a_late_answer_that_never_came_reads_expired(world):
    world.label, world.chatgpt, world.worker = fake_label(jev("meta_social_trends")), Chat("Three bullets."), Scripted("PASS")
    world.run("route", META, "--no-wait")
    _backdate(11)
    world.run("check")
    _backdate(31)
    assert _show(world)["late"]["state"] == "expired"


def test_a_stand_in_whose_own_call_was_taken_over_is_said_by_the_takeover(world, monkeypatch):
    from router import settings
    settings.LOCAL_PATH.write_text("{}")   # Grok Bot isn't set up: ChatGPT stands in for it
    world.label, world.chatgpt, world.worker = fake_label(jev("meta_social_trends")), Chat(codex_limit()), Scripted("Bullets.")
    world.json("route", META)
    doc = _show(world)
    assert doc["stand_in"]["agent"] == "chatgpt" and doc["agent"] == "claude"
    assert doc["card_line"] == "Claude took over the first call · ChatGPT hit its plan limit · done without Meta"


def test_a_grok_check_skipped_past_its_limit_shows_on_the_card(world, monkeypatch, tmp_path):
    from router import settings
    path = tmp_path / "small.json"
    path.write_text(json.dumps({"drop_folder": "~/x", "grok_prompt_limit": 600, "grok_timeout_minutes": 5}))
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    world.label, world.worker, world.chatgpt = fake_label(jev("bulk_text")), Scripted("A line. " * 120), Chat("PASS")
    world.json("route", "write sixty product lines")
    doc = _show(world)
    assert doc["card_line"] == "ChatGPT did the check · the check was too long for Grok Bot"
    assert doc["takeover"] is None and doc["check_note"].startswith("Grok skipped: the check is too long for Grok (")


def test_the_resume_offer_stays_for_a_process_that_ended_during_the_takeovers_call(world):
    world.worker, world.chatgpt = Scripted(claude_limit()), Chat("Two lines.")
    world.json("route", POEM)
    conn = log.init_db(cli.DB_PATH)
    try:
        task = log.task_by_number(conn, 1)
        conn.execute("UPDATE calls SET status = 'failed', reason_code = 'process_ended', text = 'process ended'"
                     " WHERE call_id = ?", (f"{task['task_id']}-takeover",))
        conn.execute("UPDATE tasks SET status = 'failed' WHERE task_id = ?", (task["task_id"],))
        conn.commit()
    finally:
        conn.close()
    doc = _show(world)
    assert doc["resume"] == {"ok": True, "substitute": "chatgpt", "agent": "chatgpt", "checker": None, "reason": None}
    assert doc["takeover"]["state"] == "failed"


def test_sr_log_marks_a_task_the_router_took_over(world):
    world.worker, world.chatgpt = Scripted(claude_limit()), Chat("Two lines.")
    world.json("route", POEM)
    code, out, err = world.run("log")
    assert "(taken over) " in out and "(resumed) " not in out


# ---------- the page: the minute check while a late answer may come; an hour for `sr check` (C21) ----------

def test_the_minute_check_runs_while_a_late_answer_may_still_come():
    reader, run, clock, later = _reader([{"task_id": "sr-1", "outcome": "unchecked", "late": {"state": "out"}}])
    assert reader.tick() is True
    for late in ({"state": "arrived"}, {"state": "expired"}, None):
        reader, run, clock, later = _reader([{"task_id": "sr-1", "outcome": "unchecked", "late": late}])
        assert reader.tick() is False


def test_the_pages_sr_check_may_take_an_hour():
    assert page.CHECK_TIMEOUT == 60 * 60
