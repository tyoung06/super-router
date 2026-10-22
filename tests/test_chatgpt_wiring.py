"""ChatGPT wired into the loop: the pinned model in the roster, SENDERS["chatgpt"], web search per
call, the checker prompt for a checker that can browse, the login check once per command, and
what a test roster with chatgpt live routes. Fakes only."""
import functools
import json
import signal
from pathlib import Path

import pytest

from router import __main__ as cli
from router import checking, log, routing
from router.roster import Roster, load_roster, problems
from tests.helpers import fake_label, shipped_roster
from tests.test_loop import CONFIG, Scripted, Webhook, _calls

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
AGENTS_DOC = json.loads((CONFIG_DIR / "agents.json").read_text())
SEND_PATHS = ("claude", "grok", "chatgpt", "cursor")  # the four senders (brief 20 added cursor)


def ok(skill):
    return {"status": "ok", "label": skill, "confidence": 0.93, "needs_split": 0.1, "tokens": 764}


def live_chatgpt_roster():
    """The shipped roster with chatgpt switched on, as it will be after the owner flips the flag."""
    shipped = shipped_roster()
    agents = {name: dict(agent) for name, agent in shipped.agents.items()}
    agents["chatgpt"]["live"] = True
    return Roster(agents=agents, not_routed=shipped.not_routed, table=shipped.table)


class ChatGPT:
    """A fake ChatGPT worker: records prompts and web_search; returns scripted replies."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, prompt, *, web_search):
        self.calls.append((prompt, web_search))
        reply = self.replies.pop(0) if self.replies else "a chatgpt answer"
        if isinstance(reply, BaseException) or isinstance(reply, type):
            raise reply
        return reply


class Login:
    def __init__(self, ok=True):
        self.ok, self.calls = ok, 0

    def __call__(self):
        self.calls += 1
        return self.ok


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _route(conn, task, jev, *, chatgpt=None, login=None, worker=None, hook=None, roster=None, wait=True):
    lines = []
    hook, worker, chatgpt, login = hook or Webhook(), worker or Scripted(), chatgpt or ChatGPT(), login or Login()
    from tests.test_loop import Clock
    clock = Clock()
    try:
        code = cli.cmd_route(
            task, conn=conn, config=CONFIG, roster=roster or live_chatgpt_roster(), environ={}, settings_paths=[],
            label=fake_label(jev), post=hook.post, worker=worker, chatgpt=chatgpt, codex_login=login,
            fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=wait, out=lines.append,
        )
    except KeyboardInterrupt:
        pytest.fail("KeyboardInterrupt escaped cmd_route")
    return code, "\n".join(lines), log.recent_tasks(conn)[0], chatgpt, login


# ---------- the roster: the pinned model ----------

def test_the_shipped_agents_json_pins_a_model_for_chatgpt_and_switches_it_on():
    # The owner flipped the flag on 2026-10-13 (commit "agents.json: chatgpt live").
    assert AGENTS_DOC["agents"]["chatgpt"] == {"live": True, "model": "gpt-6.1-sol"}
    assert shipped_roster().model("chatgpt") == "gpt-6.1-sol" and shipped_roster().model("claude") is None
    assert shipped_roster().live == ("claude", "grok", "chatgpt", "cursor")  # cursor since the owner's flip, 2026-10-20


def test_the_shipped_files_still_pass_with_chatgpt_switched_on():
    doc = json.loads(json.dumps(AGENTS_DOC))
    doc["agents"]["chatgpt"]["live"] = True
    assert problems(doc, shipped_roster().table, SEND_PATHS) == []


@pytest.mark.parametrize("model", [None, "", "  ", 7])
def test_a_live_chatgpt_needs_a_pinned_model(model):
    doc = json.loads(json.dumps(AGENTS_DOC))
    doc["agents"]["chatgpt"] = {"live": True, "model": model}
    if model is None:
        del doc["agents"]["chatgpt"]["model"]
    found = problems(doc, shipped_roster().table, SEND_PATHS)
    assert len(found) == 1 and "chatgpt" in found[0] and "model" in found[0]


def test_a_model_on_an_agent_that_is_not_live_is_still_checked_when_wrong():
    doc = json.loads(json.dumps(AGENTS_DOC))
    doc["agents"]["chatgpt"]["model"] = 7
    found = problems(doc, shipped_roster().table, SEND_PATHS)
    assert len(found) == 1 and "model" in found[0]


def test_main_builds_the_chatgpt_worker_with_the_pinned_model(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.safety, "prepare_workspace", lambda *a, **k: None)
    monkeypatch.setattr(cli, "cmd_route", lambda task, **kw: seen.update(kw) or 0)
    assert cli.main(["route", "hi"], platform="darwin") == 0
    chatgpt = seen["chatgpt"]
    assert isinstance(chatgpt, functools.partial) and chatgpt.func is cli.chatgpt_worker.run
    assert chatgpt.keywords == {"model": "gpt-6.1-sol"}
    assert seen["codex_login"] is cli.chatgpt_worker.login_status


# ---------- what a roster with chatgpt live routes ----------

@pytest.mark.parametrize("skill, agent, reason, checker", [
    ("web_research", "chatgpt", "best", "claude"),
    ("code", "claude", "best", "chatgpt"),
    ("writing", "claude", "best", "chatgpt"),
    ("planning", "claude", "best", "chatgpt"),
    ("x_social_pulse", "grok", "best", "chatgpt"),
])
def test_with_chatgpt_live_its_skills_route_to_it_and_claudes_work_is_checked(skill, agent, reason, checker):
    d = routing.decide(ok(skill), live_chatgpt_roster())
    assert (d.agent, d.reason, d.checker, d.check_state, d.check_note) == (agent, reason, checker, "pending", None)


def test_senders_has_chatgpt():
    assert set(cli.SENDERS) == {"claude", "grok", "chatgpt", "cursor"}  # brief 20 added cursor


# ---------- web search per call, and the prompts ----------

def test_chatgpt_does_web_research_with_live_search_and_claude_sanity_checks_it(conn):
    chatgpt = ChatGPT("The answer, with a link: https://example.org/x")
    code, out, row, chatgpt, _ = _route(conn, "find sources on the new EU AI rules", ok("web_research"),
                                        chatgpt=chatgpt, worker=Scripted("PASS"))
    assert code == 0 and (row["agent"], row["checker"], row["check_state"]) == ("chatgpt", "claude", "passed")
    # rules v2.22: the do prompt carries the search line; claude's check, with the probe gate shut here, is still a
    # sanity check only (its row records `off (probe not passed)`)
    assert chatgpt.calls == [("find sources on the new EU AI rules\n\n" + checking.SEARCH_LINE_GENERAL, "live")]
    assert "CHECKED (sanity check only): passed." in out
    assert _calls(conn, row["task_id"])[0] == (row["task_id"], "do", "chatgpt", "done", None)


def test_chatgpt_checks_claudes_code_with_search_on_and_may_browse(conn):
    # rules v2.22: before, a check on a non-web skill ran with search off
    chatgpt = ChatGPT("PASS")
    code, out, row, chatgpt, _ = _route(conn, "write a parser for the log", ok("code"), chatgpt=chatgpt,
                                        worker=Scripted("def parse(): ..."))
    assert code == 0 and (row["agent"], row["checker"], row["check_state"]) == ("claude", "chatgpt", "passed")
    prompt, web_search = chatgpt.calls[0]
    assert web_search == "live"
    assert prompt == checking.checker_prompt("write a parser for the log", "def parse(): ...", no_tools=False,
                                             can_browse=True, search=True)
    assert "can't open links" not in prompt and "may open links" in prompt
    assert "CHECKED: passed." in out and "sanity" not in out


def test_chatgpt_checks_groks_x_chatter_with_live_search_and_may_browse(conn):
    hook = Webhook(do="People on X are saying... https://x.com/post/1")
    chatgpt = ChatGPT("PASS")
    code, out, row, chatgpt, _ = _route(conn, "what is X saying about NVDA today", ok("x_social_pulse"), chatgpt=chatgpt, hook=hook)
    assert code == 0 and (row["agent"], row["checker"], row["check_state"]) == ("grok", "chatgpt", "passed")
    prompt, web_search = chatgpt.calls[0]
    assert web_search == "live"
    assert prompt == checking.checker_prompt("what is X saying about NVDA today", "People on X are saying... https://x.com/post/1",
                                             no_tools=False, can_browse=True, search=True)  # rules v2.22: the line
    assert "may open links" in prompt.lower() and "verify" in prompt.lower()


def test_the_browse_paragraph_still_names_nobody():
    prompt = checking.checker_prompt("a task", "a result", no_tools=False, can_browse=True).lower()
    for name in ("claude", "grok", "chatgpt", "openai", "gpt", "codex", "muse", "jev"):
        assert name not in prompt


def test_the_fix_round_goes_back_to_chatgpt_with_the_doers_search_setting(conn):
    chatgpt = ChatGPT("answer v1", "answer v2")
    code, out, row, chatgpt, _ = _route(conn, "find sources on the new EU AI rules", ok("web_research"),
                                        chatgpt=chatgpt, worker=Scripted("FIX\n1. Add a date.", "PASS"))
    assert code == 0 and row["check_state"] == "fixed" and row["result"] == "answer v2"
    assert chatgpt.calls[1][1] == "live" and chatgpt.calls[1][0] == checking.fix_prompt(
        "find sources on the new EU AI rules", "answer v1", "1. Add a date.", search=True, count=True)  # rules v2.22: the line


def test_an_override_for_chatgpt_works_once_it_is_live(conn):
    chatgpt = ChatGPT("36")
    code, out, row, chatgpt, _ = _route(conn, "@chatgpt what is 15% of 240", ok("quick_answer"), chatgpt=chatgpt)
    assert code == 0 and (row["agent"], row["route_reason"], row["check_state"]) == ("chatgpt", "override", "not_needed")
    assert chatgpt.calls == [("what is 15% of 240\n\n" + checking.SEARCH_LINE_GENERAL, "live")]  # rules v2.22


# ---------- the login check ----------

def test_a_missing_chatgpt_login_fails_the_task_before_any_codex_call(conn):
    chatgpt, login = ChatGPT("never"), Login(ok=False)
    code, out, row, chatgpt, login = _route(conn, "find sources on the new EU AI rules", ok("web_research"),
                                            chatgpt=chatgpt, login=login)
    assert code == 1 and row["status"] == "failed" and chatgpt.calls == [] and login.calls == 1
    assert "ChatGPT" in row["result"] and "codex login" in row["result"]
    # Since build brief 7 a failed first call leaves a failed `do` row; no Codex call was made (chatgpt.calls above).
    assert _calls(conn, row["task_id"]) == [(row["task_id"], "do", "chatgpt", "failed", None)]
    assert log.calls_for(conn, row["task_id"])[0]["reason_code"] is None  # not a plan limit


def test_a_missing_login_at_the_check_is_a_failed_check_round(conn):
    chatgpt, login = ChatGPT("never"), Login(ok=False)
    code, out, row, chatgpt, _ = _route(conn, "write a parser", ok("code"), chatgpt=chatgpt, login=login,
                                        worker=Scripted("def parse(): ..."))
    assert code == 0 and (row["check_state"], row["result"]) == ("unchecked", "def parse(): ...")
    assert chatgpt.calls == [] and "CHECK ROUND FAILED: chatgpt" in out and "codex login" in out
    assert _calls(conn, row["task_id"])[-1][1:4] == ("check", "chatgpt", "failed")


def test_the_login_is_checked_once_per_command(conn):
    hook = Webhook()
    chatgpt, login = ChatGPT("PASS", "PASS"), Login()
    lines = []
    for task_id in ("sr-a", "sr-b"):
        log.add_task(conn, task_id, "write code", "cli", ok("code"))
        log.set_route(conn, task_id, agents=("claude", "grok", "chatgpt", "muse"), agent="claude", route_reason="best",
                      skill="code", skill_source="jev", checker="chatgpt", check_state="pending")
        log.add_call(conn, task_id, task_id, "do", "claude", status="done", text="code")
    code = cli.cmd_check(conn=conn, config=CONFIG, environ={}, settings_paths=[], post=hook.post, worker=Scripted(),
                         chatgpt=chatgpt, codex_login=login, fetch=hook.fetch, close=hook.close, out=lines.append)
    assert code == 0 and len(chatgpt.calls) == 2 and login.calls == 1
    assert all(log.get_task(conn, t)["check_state"] == "passed" for t in ("sr-a", "sr-b"))


def test_no_chatgpt_worker_means_chatgpt_is_not_configured(conn):
    lines = []
    log.add_task(conn, "sr-a", "write code", "cli", ok("code"))
    log.set_route(conn, "sr-a", agents=("claude", "grok", "chatgpt", "muse"), agent="claude", route_reason="best",
                  skill="code", skill_source="jev", checker="chatgpt", check_state="pending")
    log.add_call(conn, "sr-a", "sr-a", "do", "claude", status="done", text="code")
    hook = Webhook()
    code = cli.cmd_check(conn=conn, config=CONFIG, environ={}, settings_paths=[], post=hook.post, worker=Scripted(),
                         chatgpt=None, codex_login=Login(), fetch=hook.fetch, close=hook.close, out=lines.append)
    out = "\n".join(lines)
    assert code == 0 and "CHECK ROUND FAILED: chatgpt" in out and "configured" in out
    assert log.get_task(conn, "sr-a")["check_state"] == "unchecked"


# ---------- Ctrl+C during a ChatGPT call ----------

def test_ctrl_c_during_a_chatgpt_check_leaves_the_task_open(conn):
    original = signal.getsignal(signal.SIGINT)
    code, out, row, _, _ = _route(conn, "write a parser", ok("code"), chatgpt=ChatGPT(KeyboardInterrupt),
                                  worker=Scripted("def parse(): ..."))
    assert code == 130 and row["status"] == "queued" and row["result"] is None
    assert "by chatgpt" in out and "sr check" in out
    assert _calls(conn, row["task_id"]) == [(row["task_id"], "do", "claude", "done", None)]
    assert signal.getsignal(signal.SIGINT) is original


def test_ctrl_c_during_chatgpts_first_call_cancels(conn):
    code, out, row, _, _ = _route(conn, "find sources", ok("web_research"), chatgpt=ChatGPT(KeyboardInterrupt))
    assert code == 130 and row["status"] == "cancelled"


# ---------- the shipped config is unchanged for today's routing ----------

def test_the_shipped_roster_still_refuses_at_muse(conn):
    lines = []
    code = cli.cmd_route("@muse hi", conn=conn, config=CONFIG, roster=shipped_roster(), environ={}, settings_paths=[],
                         label=fake_label(), post=Webhook().post, worker=Scripted(), chatgpt=ChatGPT(), codex_login=Login(),
                         out=lines.append)
    assert code == 2 and "not live" in "\n".join(lines)


def test_a_failed_login_is_a_failed_round_for_a_fix_too(conn):
    chatgpt = ChatGPT("answer v1")
    login = Login()
    hook = Webhook()
    worker = Scripted("FIX\n1. Add a date.")
    lines = []
    from tests.test_loop import Clock
    clock = Clock()

    def login_then_fail():
        login.calls += 1
        return login.calls == 1  # signed in for the first call, gone by the fix

    code = cli.cmd_route("find sources", conn=conn, config=CONFIG, roster=live_chatgpt_roster(), environ={},
                         settings_paths=[], label=fake_label(ok("web_research")), post=hook.post, worker=worker,
                         chatgpt=chatgpt, codex_login=login_then_fail, fetch=hook.fetch, close=hook.close,
                         sleep=clock.sleep, clock=clock, wait=True, out=lines.append)
    # the login is checked once per command, so the fix still runs with the first answer
    assert code == 0 and login.calls == 1 and len(chatgpt.calls) == 2
