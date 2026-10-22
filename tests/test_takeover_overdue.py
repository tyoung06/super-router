"""Build brief 24, C3 (decisions 6 and 7; the owner's C11 and C8). A Grok call still out at 2 × grok_timeout_minutes is
taken over by whichever process checks next (`sr check`, the page's minute check, or route's own wait); its row stays
as stopped (`overdue`). An answer collected first wins. When the overdue call's answer comes later, `sr check` stores
it on that row, marked `late`, writes its round file, closes the issue and changes nothing else; it looks for one up to
the 30-minute Grok timeout after the send. `SR_INJECT_OVERDUE=grok` logs a command's Grok sends 2N early, on a scratch
log only. Through the real main with every outside thing faked."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from router import __main__ as cli
from router import log, plan_limit
from tests.helpers import fake_label
from tests.test_json_actions import World, jev
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_relay import CONFIG, GOOD_NOTE, Chat, RelayHook
from tests.test_routing_availability import ROSTER, Gate

# The owner's decision of 21 Oct: x_social_pulse is Grok Bot's alone (never stood in for, never taken over), so these
# stand-in, takeover and late-answer cases use meta_social_trends (Grok best, ChatGPT second).
META = "what are gardeners on Instagram saying about rubber trays"


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    w = World(monkeypatch, tmp_path, capsys)
    w.label, w.hook = fake_label(jev("meta_social_trends")), Webhook()
    w.chatgpt, w.worker = Chat("Three bullets, sources named."), Scripted("PASS")
    return w


def _ago(minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")


def _db():
    return log.init_db(cli.DB_PATH)


def _backdate(minutes, n=1):
    conn = _db()
    try:
        task = log.task_by_number(conn, n)
        call = [c for c in log.calls_for(conn, task["task_id"]) if c["agent"] == "grok"][-1]
        conn.execute("UPDATE calls SET sent_at = ? WHERE call_id = ?", (_ago(minutes), call["call_id"]))
        conn.commit()
    finally:
        conn.close()


def _rows(n=1):
    conn = _db()
    try:
        task = log.task_by_number(conn, n)
        return task, log.calls_for(conn, task["task_id"])
    finally:
        conn.close()


def test_at_2n_sr_check_takes_the_grok_call_over_and_its_row_stays_overdue(world):
    world.run("route", META, "--no-wait")
    _backdate(11)
    code, out, err = world.run("check")
    task, calls = _rows()
    assert "ChatGPT took over the first call · Grok Bot was overdue · done without Meta" in out
    assert [(c["call_id"].replace(task["task_id"], "t"), c["agent"], c["status"], c["reason_code"]) for c in calls] == [
        ("t", "grok", "failed", "overdue"), ("t-takeover", "chatgpt", "done", None), ("t-c1", "claude", "done", None)]
    assert (task["status"], task["agent"], task["checker"], task["check_state"]) == ("done", "chatgpt", "claude", "passed")
    assert task["check_note"] is None   # the overdue note went with the Grok call


def test_before_2n_nothing_is_taken_over(world):
    world.run("route", META, "--no-wait")
    _backdate(6)
    code, out, err = world.run("check")
    task, calls = _rows()
    assert "took over" not in out and task["status"] == "sent" and calls[0]["status"] == "sent"


def test_an_answer_that_is_in_when_sr_check_runs_wins_over_the_takeover(world):
    world.run("route", META, "--no-wait")
    _backdate(11)
    world.hook.bodies["do"] = "Gardeners like rubber trays."
    code, out, err = world.run("check")
    task, calls = _rows()
    assert "took over" not in out and (task["agent"], task["result"]) == ("grok", "Gardeners like rubber trays.")


def test_a_late_answer_is_stored_on_its_row_closed_and_never_used(world):
    world.run("route", META, "--no-wait")
    _backdate(11)
    world.run("check")
    world.hook.bodies["do"] = "Gardeners like rubber trays."
    code, out, err = world.run("check")
    task, calls = _rows()
    late = calls[0]
    assert (late["status"], late["reason_code"], late["text"]) == ("failed", "late", "Gardeners like rubber trays.")
    assert f"{task['task_id']} (do by grok): its late answer came (issue #1); kept on the log, not used." in out
    assert world.hook.closed == [1]
    assert (task["result"], task["check_state"]) == ("Three bullets, sources named.", "passed")   # nothing else moved
    assert late["round_file"] == f"tasks/{task['task_id']}/01-late-do-grok.md"
    assert (cli.DB_PATH.parent / late["round_file"]).read_text() == "Gardeners like rubber trays."
    code, out, err = world.run("show", "1")
    assert "Late answer: Grok Bot's answer came " in out and "kept, not used (tasks/" in out
    world.hook.bodies["do"] = "A second copy."
    code, out, err = world.run("check")
    assert "late answer" not in out and _rows()[1][0]["text"] == "Gardeners like rubber trays."   # stored once


def test_while_the_late_answer_may_still_come_sr_show_says_until_when(world):
    world.run("route", META, "--no-wait")
    _backdate(11)
    world.run("check")
    code, out, err = world.run("show", "1")
    assert "Taken over: ChatGPT took over the first call — replaces call" in out
    assert "Grok Bot's answer may still come until " in out and "; it won't be used." in out


def test_a_late_answer_after_the_30_minute_timeout_is_not_looked_for(world):
    world.run("route", META, "--no-wait")
    _backdate(11)
    world.run("check")
    _backdate(31)
    world.hook.bodies["do"] = "Too late."
    world.hook.calls = 0
    code, out, err = world.run("check")
    assert _rows()[1][0]["reason_code"] == "overdue" and world.hook.calls == 0   # the inbox wasn't even read


def test_an_override_is_never_taken_over_at_2n_and_waits_as_today(world):
    world.run("route", "@grok " + META, "--no-wait")
    _backdate(11)
    code, out, err = world.run("check")
    task, calls = _rows()
    assert "took over" not in out and "No takeover" not in out
    assert task["status"] == "sent" and task["check_note"] == "overdue: grok, 11 min"


def test_a_relay_grok_stage_at_2n_is_researched_by_chatgpt(world):
    world.hook = RelayHook()
    world.chatgpt, world.worker = Chat(GOOD_NOTE, "PASS"), Scripted("the build")
    world.run("relay", "research-build", "what is the current stable python", "--no-wait")
    _backdate(11)
    code, out, err = world.run("check")
    task, calls = _rows()
    assert "ChatGPT took over stage 1 (research) · Grok Bot was overdue" in out
    assert (task["status"], task["check_state"], task["result"]) == ("done", "passed", "the build")


def test_routes_own_wait_takes_over_in_its_own_process(monkeypatch):
    monkeypatch.setattr(cli, "BACKDATE_MINUTES", 10)   # the Grok send is logged 2N early, as the hook does
    conn, lines, clock, hook = log.init_db(":memory:"), [], Clock(), Webhook()
    code = cli.cmd_route(META, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=fake_label(jev("meta_social_trends")), post=hook.post, worker=Scripted("PASS"),
                         chatgpt=Chat("Three bullets."), codex_login=lambda: True, fetch=hook.fetch, close=hook.close,
                         sleep=clock.sleep, clock=clock, wait=True, available=Gate(), out=lines.append)
    task = log.recent_tasks(conn)[0]
    assert code == 0 and (task["status"], task["agent"], task["result"]) == ("done", "chatgpt", "Three bullets.")
    assert "ChatGPT took over the first call · Grok Bot was overdue · done without Meta" in lines
    assert clock.sleeps == []   # it took over at the first poll, without waiting out the 10 minutes


# ---------- SR_INJECT_OVERDUE ----------

def test_the_overdue_hook_logs_the_grok_send_2n_early_on_a_scratch_log(world, monkeypatch, tmp_path):
    monkeypatch.setattr(plan_limit, "main_checkout", lambda root, run=None: tmp_path / "elsewhere")
    monkeypatch.setenv(plan_limit.OVERDUE_ENV, "grok")
    code, out, err = world.run("route", META, "--no-wait")
    assert "Test hook: each Grok call this command sends is logged 10 minutes early" in out
    sent = datetime.fromisoformat(_rows()[1][0]["sent_at"])
    assert timedelta(minutes=9.9) < datetime.now(timezone.utc) - sent < timedelta(minutes=10.5)
    # The owner after F (decision 3): under the hook the sending command reads its own backdated call overdue and takes it
    # over at once, so a Grok Bot that answers in seconds can't win the race the live check needs
    assert "ChatGPT took over the first call · Grok Bot was overdue" in out
    monkeypatch.delenv(plan_limit.OVERDUE_ENV)
    world.hook.bodies["do"] = "The real answer."
    code, out, err = world.run("check")
    assert "its late answer came" in out and _rows()[1][0]["reason_code"] == "late"


def test_without_the_hook_a_command_never_takes_over_the_grok_call_it_just_sent(world, monkeypatch):
    monkeypatch.setattr(log, "minutes_since", lambda sent_at, now=None: 11)   # as if 2N had passed in the same breath
    code, out, err = world.run("route", META, "--no-wait")
    assert "took over" not in out and _rows()[0]["status"] == "sent"
    code, out, err = world.run("check")                                       # the next command does
    assert "ChatGPT took over the first call · Grok Bot was overdue" in out


@pytest.mark.parametrize("value, where, words", [
    ("grok", "real", "test-only and works only on a scratch log"),
    ("claude", "scratch", "SR_INJECT_OVERDUE names grok, not 'claude'."),
])
def test_the_overdue_hook_is_refused_on_the_real_log_and_for_any_agent_but_grok(monkeypatch, tmp_path, capsys, value,
                                                                                   where, words):
    main = cli.DB_PATH.parent if where == "real" else tmp_path / "elsewhere"
    monkeypatch.setattr(plan_limit, "main_checkout", lambda root, run=None: main)
    monkeypatch.setenv(plan_limit.OVERDUE_ENV, value)
    assert cli.main(["log"], platform="darwin") == 2
    out = capsys.readouterr().out
    assert "Refused:" in out and words in out and "Nothing was logged or sent." in out


def test_the_hook_needs_n():
    with pytest.raises(plan_limit.InjectRefused, match="needs grok_timeout_minutes"):
        plan_limit.overdue_minutes("grok", "x.db", None, root=".")


# ---------- the owner's C11: a Grok check past its limit is skipped when the checker is chosen ----------

@pytest.fixture
def small_limit(monkeypatch, tmp_path):
    from router import settings
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"drop_folder": "~/x", "grok_prompt_limit": 600, "grok_timeout_minutes": 5}))
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)


def _bulk(gate, chat):
    conn, lines, clock, hook = log.init_db(":memory:"), [], Clock(), Webhook()
    cli.cmd_route("write sixty product lines", conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                  label=fake_label(jev("bulk_text")), post=hook.post, worker=Scripted("A product line. " * 60),
                  chatgpt=chat, codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep,
                  clock=clock, wait=False, available=gate, out=lines.append)
    task = log.recent_tasks(conn)[0]
    return task, log.calls_for(conn, task["task_id"]), "\n".join(lines), hook


def test_a_routed_grok_check_past_its_limit_goes_to_the_next_checker_with_no_row_and_no_takeover(small_limit):
    task, calls, out, hook = _bulk(Gate(), Chat("PASS"))
    assert hook.sent == [] and [(c["kind"], c["agent"], c["status"]) for c in calls] == [
        ("do", "claude", "done"), ("check", "chatgpt", "done")]
    assert (task["status"], task["checker"], task["check_state"]) == ("done", "chatgpt", "passed")
    assert task["check_note"].startswith("Grok skipped: the check is too long for Grok (")
    assert "ChatGPT checks instead." in out and "took over" not in out


def test_with_nobody_else_to_check_the_result_is_unchecked_and_says_both(small_limit):
    task, calls, out, hook = _bulk(Gate({"chatgpt"}), Chat())
    assert (task["status"], task["checker"], task["check_state"]) == ("done", None, "unchecked")
    assert task["check_note"].startswith("Grok skipped: the check is too long for Grok (")
    assert task["check_note"].endswith("; no other agent available to check (ChatGPT is signed out (codex login))")
