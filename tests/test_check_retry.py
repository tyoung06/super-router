"""Brief 24, after F (the owner's decision 2 of 21 Oct): an online check that didn't answer is run once more. If Claude's
still doesn't answer, the task goes ahead with a warning ("Claude's sign-in check didn't answer; trying anyway"): the
call itself decides, and a real failure is taken over. Any other agent whose check still doesn't answer stays
unavailable for that task. In F, `claude auth status` (normally under 1.2 s) didn't answer in 15 s once, and Cursor's
`agent status` twice. Fakes only."""
import json

import pytest

from router import __main__ as cli
from router import availability, log, online
from tests.helpers import fake_label, shipped_roster
from tests.test_json_actions import World, jev
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_relay import CONFIG, Chat

ROSTER = shipped_roster()
TRYING = "Claude's sign-in check didn't answer; trying anyway"
NO_ANSWER = online.Answer((False, "claude auth status did not answer (TimeoutExpired)"), "unreachable")


class Flaky:
    """A check that answers from a list, one per run; records how often it ran."""

    def __init__(self, *answers):
        self.answers, self.runs = list(answers), 0

    def __call__(self):
        self.runs += 1
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


# ---------- the retry ----------

def test_a_check_that_did_not_answer_is_run_once_more_and_its_second_answer_counts():
    flaky = Flaky(NO_ANSWER, online.Answer((True, None)))
    found = online.run_all({"claude": flaky})
    assert flaky.runs == 2 and found["claude"]["online"] is True and found["claude"]["code"] is None


def test_a_check_that_still_does_not_answer_reads_unreachable_after_two_runs():
    flaky = Flaky(online.Answer((False, "agent status did not answer (TimeoutExpired)"), "unreachable"))
    found = online.run_all({"cursor": flaky})
    assert flaky.runs == 2 and (found["cursor"]["online"], found["cursor"]["code"]) == (False, "unreachable")


def test_an_answer_is_never_run_again():
    signed_out = Flaky(online.Answer((False, "not signed in with ChatGPT (codex login)"), "signed_out"))
    up = Flaky(online.Answer((True, None)))
    found = online.run_all({"chatgpt": signed_out, "claude": up})
    assert (signed_out.runs, up.runs) == (1, 1) and found["chatgpt"]["code"] == "signed_out"


# ---------- Claude goes ahead; every other agent stays out ----------

def _online(code_for):
    return {name: {"online": code is None, "reason": None if code is None else "did not answer", "code": code}
            for name, code in code_for.items()}


def test_claudes_check_that_never_answered_reads_available_with_the_warning():
    names = availability.env_names(CONFIG)
    found = availability.of("claude", roster=ROSTER, names=names, online=_online({"claude": "unreachable"}))
    assert (found.available, found.why, found.code) == (True, TRYING, "unreachable")
    assert availability.of("claude", roster=ROSTER, names=names, online=_online({"claude": "signed_out"})).available is False


@pytest.mark.parametrize("agent", ["chatgpt", "cursor"])
def test_any_other_agent_whose_check_never_answered_stays_unavailable(agent):
    found = availability.of(agent, roster=ROSTER, names=availability.env_names(CONFIG),
                            online=_online({agent: "unreachable"}))
    assert (found.available, found.code) == (False, "unreachable")


class Gate:
    def __init__(self, table):
        self.table = table

    def of(self, names, fresh=False):
        return {n: self.table.get(n, availability.YES) for n in names if n}

    def __call__(self, name, fresh=False):
        return self.of([name])[name]


def test_route_goes_ahead_with_the_warning_and_the_call_decides():
    conn, lines, clock, hook = log.init_db(":memory:"), [], Clock(), Webhook()
    gate = Gate({"claude": availability.Availability(True, TRYING, "unreachable")})
    code = cli.cmd_route("write two lines about trays", conn=conn, config=CONFIG, roster=ROSTER, environ={},
                         settings_paths=[], label=fake_label(jev("writing")), post=hook.post, worker=Scripted("Two lines."),
                         chatgpt=Chat("PASS"), codex_login=lambda: True, fetch=hook.fetch, close=hook.close,
                         sleep=clock.sleep, clock=clock, available=gate, out=lines.append)
    row = log.recent_tasks(conn)[0]
    assert code == 0 and lines[0] == f"{TRYING}." and (row["agent"], row["check_state"]) == ("claude", "passed")


def test_through_main_claudes_silent_check_is_retried_then_the_task_runs(monkeypatch, tmp_path, capsys):
    world = World(monkeypatch, tmp_path, capsys)
    claude = Flaky(NO_ANSWER)
    monkeypatch.setitem(online.CHECKS, "claude", claude)
    world.worker, world.chatgpt = Scripted("Two lines."), Chat("PASS")
    found = world.json("route", "write two lines about trays")
    assert claude.runs == 2 and found["exit"] == 0 and TRYING in found["message"]
    status = json.loads(world.run("status", "--json")[1])
    agent = next(a for a in status["agents"] if a["name"] == "claude")
    assert (agent["available"], agent["why"], agent["why_code"]) == (True, TRYING, "unreachable")
