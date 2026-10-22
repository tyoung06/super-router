"""Build brief 24, A1 (decisions 1, 12 and 13): an agent is available when its live flag is on, it is set up and answering,
and no safety check has failed on the installed version. `availability.of` is pure: each agent × each missing piece
reads `available` false with its own words and code, from the roster, the .env names present (never a value), the
settings, the online answers, probe_state.json and the installed versions. `Gate` runs only the checks it is asked
for, side by side, once per command unless asked fresh. Fakes only; every value here is fake."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from router import availability, online, probes
from tests.helpers import roster_with, shipped_roster

ROSTER = shipped_roster()
NAMES = frozenset({"GROK_WEBHOOK_URL", "GROK_WEBHOOK_KEY", "JEV_API_KEY"})
DOC = {"grok_inbox_repo": "owner/inbox"}
NOW = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)
UP = {name: {"online": True, "reason": None, "checked_at": "t", "code": None} for name in ("claude", "chatgpt", "grok",
                                                                                             "cursor")}


def _of(agent, roster=ROSTER, names=NAMES, doc=DOC, online_=UP, probe_data=None, versions=None):
    return availability.of(agent, roster=roster, names=names, doc=doc, online=online_, probe_data=probe_data,
                           versions=versions, now=NOW)


def _down(agent, reason, code):
    return {**UP, agent: {"online": False, "reason": reason, "checked_at": "t", "code": code}}


def _without_model(agent):
    agents = {n: dict(a) for n, a in ROSTER.agents.items()}
    agents[agent].pop("model")
    return replace(ROSTER, agents=agents)


def test_every_agent_is_available_when_live_set_up_answering_and_no_check_failed():
    for agent in ("claude", "chatgpt", "grok", "cursor"):
        assert _of(agent) == availability.Availability(True), agent
    assert _of("muse").as_dict() == {"available": False, "why": "Muse is off: not live in config/agents.json",
                                     "why_code": "not_live"}


@pytest.mark.parametrize("agent, name", [("claude", "Claude"), ("chatgpt", "ChatGPT"), ("grok", "Grok Bot"),
                                         ("cursor", "Cursor")])
def test_an_agent_that_is_not_live_is_off_whatever_else_holds(agent, name):
    found = _of(agent, roster=roster_with(**{agent: False}))
    assert found.as_dict() == {"available": False, "why": f"{name} is off: not live in config/agents.json",
                               "why_code": "not_live"}


@pytest.mark.parametrize("agent, why", [
    ("chatgpt", "ChatGPT isn't set up: no model pinned in config/agents.json"),
    ("cursor", "Cursor isn't set up: no Grok model pinned in config/agents.json")])
def test_no_pinned_model_is_not_set_up(agent, why):
    assert _of(agent, roster=_without_model(agent)).as_dict() == {"available": False, "why": why,
                                                                  "why_code": "not_configured"}


@pytest.mark.parametrize("names, doc, why", [
    (NAMES, {}, "Grok Bot isn't set up: no inbox repo in settings"),
    (NAMES, {"grok_inbox_repo": "  "}, "Grok Bot isn't set up: no inbox repo in settings"),
    (NAMES, {"grok_inbox_repo": "not a repo"}, "Grok Bot isn't set up: grok_inbox_repo in settings isn't owner/name"),
    (NAMES - {"GROK_WEBHOOK_URL"}, DOC, "Grok Bot isn't set up: no GROK_WEBHOOK_URL in .env"),
    (NAMES - {"GROK_WEBHOOK_KEY"}, DOC, "Grok Bot isn't set up: no GROK_WEBHOOK_KEY in .env"),
    (frozenset(), {}, "Grok Bot isn't set up: no GROK_WEBHOOK_URL or GROK_WEBHOOK_KEY in .env; no inbox repo in settings"),
])
def test_grok_bot_needs_its_two_env_names_and_the_inbox_setting(names, doc, why):
    found = _of("grok", names=names, doc=doc)
    assert (found.available, found.why, found.code) == (False, why, "not_configured")


def test_the_env_names_are_presence_only_and_never_their_values():
    names = availability.env_names({"GROK_WEBHOOK_URL": "https://example.invalid/hook-FAKE", "GROK_WEBHOOK_KEY": "  ",
                                    "JEV_API_KEY": None, "OTHER": "FAKE-OTHER-VALUE"})
    assert names == frozenset({"GROK_WEBHOOK_URL", "OTHER"})
    found = _of("grok", names=names)
    assert "FAKE" not in found.why and "example.invalid" not in found.why
    assert found.why == "Grok Bot isn't set up: no GROK_WEBHOOK_KEY in .env"


@pytest.mark.parametrize("agent, reason, code, why, want", [
    ("claude", "not signed in (claude auth login)", "signed_out", "Claude is signed out (claude auth login)", "signed_out"),
    ("claude", "signed in with console, not the Claude plan", "not_configured",
     "Claude isn't set up: signed in with console, not the Claude plan", "not_configured"),
    ("chatgpt", "not signed in with ChatGPT (codex login)", "signed_out", "ChatGPT is signed out (codex login)", "signed_out"),
    ("cursor", "not signed in (agent login)", "signed_out", "Cursor is signed out (agent login)", "signed_out"),
    ("cursor", "agent status did not answer (TimeoutExpired)", "unreachable",
     "Cursor can't be reached: agent status did not answer (TimeoutExpired)", "unreachable"),
    ("grok", "the inbox repo did not answer (gh)", "unreachable",
     "Grok Bot can't be reached: the inbox repo did not answer (gh)", "unreachable"),
    ("grok", "check failed (RuntimeError)", None, "Grok Bot can't be reached: check failed (RuntimeError)", "unreachable"),
])
def test_an_online_check_that_says_no_names_why(agent, reason, code, why, want):
    found = _of(agent, online_=_down(agent, reason, code))
    assert (found.available, found.why, found.code) == (False, why, want)


def test_claudes_check_that_did_not_answer_reads_available_with_the_warning():
    # The owner's decision 2 after F: Claude is required, so its silent check never refuses on its own (test_check_retry.py)
    found = _of("claude", online_=_down("claude", "claude auth status did not answer (TimeoutExpired)", "unreachable"))
    assert (found.available, found.why, found.code) == (True, "Claude's sign-in check didn't answer; trying anyway",
                                                        "unreachable")


def test_an_agent_not_checked_yet_is_judged_on_what_runs_nothing():
    assert _of("grok", online_=None).available is True                       # a preview: live, set up, no failure
    assert _of("grok", online_=None, doc={}).why == "Grok Bot isn't set up: no inbox repo in settings"


def _failure(key, version, kind, at=NOW):
    return {f"{key}_failure": {"version": version, "kind": kind, "reason": "codex ran to the end: exit 1",
                               "at": at.isoformat(timespec="seconds")}}


@pytest.mark.parametrize("agent, key, tool", [("chatgpt", "codex_sandbox", "codex"), ("cursor", "cursor_sandbox", "agent")])
def test_a_safety_check_that_ran_and_failed_keeps_the_agent_off_on_that_version(agent, key, tool):
    data = _failure(key, "9.9.9", probes.RAN_FAILED, at=NOW - timedelta(days=3))
    found = _of(agent, probe_data=data, versions={agent: "9.9.9"})
    name = availability.name_of(agent)
    assert (found.available, found.why, found.code) == (False, f"{name} is off: its safety check failed on {tool} 9.9.9",
                                                        "probe_failed")
    assert _of(agent, probe_data=data, versions={agent: "9.9.10"}).available is True   # the tool moved: checked again
    assert _of(agent, probe_data=data, versions={agent: "unknown"}).available is True  # nothing to compare


def test_a_safety_check_that_could_not_run_holds_for_an_hour():
    data = _failure("codex_sandbox", "0.162.1", probes.COULD_NOT_RUN, at=NOW - timedelta(minutes=20))
    found = _of("chatgpt", probe_data=data, versions={"chatgpt": "0.162.1"})
    assert found.available is False and found.code == "probe_failed"
    assert found.why.startswith("ChatGPT is off for now: its safety check could not run on codex 0.162.1; it is tried "
                                "again after ")
    later = _failure("codex_sandbox", "0.162.1", probes.COULD_NOT_RUN, at=NOW - timedelta(minutes=61))
    assert _of("chatgpt", probe_data=later, versions={"chatgpt": "0.162.1"}).available is True


def test_the_order_not_live_then_set_up_then_safety_then_the_check():
    gone = roster_with(chatgpt=False)
    data = _failure("codex_sandbox", "1", probes.RAN_FAILED)
    down = _down("chatgpt", "not signed in with ChatGPT (codex login)", "signed_out")
    assert _of("chatgpt", roster=gone, probe_data=data, versions={"chatgpt": "1"}, online_=down).code == "not_live"
    assert _of("chatgpt", roster=_without_model("chatgpt"), probe_data=data, versions={"chatgpt": "1"},
               online_=down).code == "not_configured"
    assert _of("chatgpt", probe_data=data, versions={"chatgpt": "1"}, online_=down).code == "probe_failed"
    assert _of("chatgpt", online_=down).code == "signed_out"


def test_jev_is_available_only_with_its_key_present():
    assert availability.jev(NAMES).available is True
    assert availability.jev(NAMES - {"JEV_API_KEY"}).as_dict() == {
        "available": False, "why": "Jev isn't set up: no JEV_API_KEY in .env", "why_code": "not_configured"}


def test_everyone_is_todays_live_table():
    table = availability.everyone(roster_with(grok=False))
    assert table["claude"].available and not table["grok"].available and table["grok"].code == "not_live"


# ---------- the gate: one command's checks ----------

class Checks:
    def __init__(self, answers=None):
        self.answers, self.ran = answers or {}, []

    def table(self):
        def make(name):
            def check():
                self.ran.append(name)
                return self.answers.get(name, online.Answer((True, None)))
            return check
        return {name: make(name) for name in ("claude", "chatgpt", "grok", "cursor")}


def _gate(checks, roster=ROSTER, config=None, doc=None, probe_path=None, versions=None):
    config = {"GROK_WEBHOOK_URL": "https://example.invalid/FAKE", "GROK_WEBHOOK_KEY": "FAKE-KEY-0001"} if config is None else config
    return availability.Gate(roster, config, checks=checks.table(), run_all=online.run_all, probe_path=probe_path,
                             versions=versions, read_settings=lambda: DOC if doc is None else doc, now=NOW)


def test_the_gate_checks_only_what_it_is_asked_once_per_command():
    checks = Checks()
    gate = _gate(checks)
    assert gate("claude").available is True and checks.ran == ["claude"]
    assert gate.of(["claude", "chatgpt"])["chatgpt"].available is True
    assert sorted(checks.ran) == ["chatgpt", "claude"]          # claude's answer is kept for the command
    gate.of(["claude"], fresh=True)                             # a takeover, minutes later: checked again
    assert checks.ran.count("claude") == 2


def test_the_gate_never_checks_an_agent_that_is_not_live_or_not_set_up():
    checks = Checks()
    gate = _gate(checks, roster=roster_with(cursor=False), doc={})
    found = gate.of(["cursor", "grok"])
    assert found["cursor"].code == "not_live" and found["grok"].why == "Grok Bot isn't set up: no inbox repo in settings"
    assert checks.ran == []


def test_the_gate_reads_a_version_only_for_a_failure_on_record_and_survives_a_read_that_blows_up(tmp_path):
    path = tmp_path / "probe_state.json"
    read = []

    def version():
        read.append(1)
        raise RuntimeError("no codex")
    gate = _gate(Checks(), probe_path=path, versions={"chatgpt": version})
    assert gate("chatgpt").available is True and read == []           # no failure on record: no version read
    path.write_text('{"codex_sandbox_failure": {"version": "0.1.0", "kind": "ran_failed", "reason": "x", "at": "2026-10-21T17:00:00+00:00"}}')
    assert gate("chatgpt", fresh=True).available is True and read == [1]  # read once, unknown, nothing to compare
    gate("chatgpt", fresh=True)
    assert read == [1]


def test_the_gate_answers_an_offline_check_in_words():
    checks = Checks({"chatgpt": online.Answer((False, "not signed in with ChatGPT (codex login)"), "signed_out")})
    assert _gate(checks)("chatgpt").why == "ChatGPT is signed out (codex login)"


# ---------- A3 (decision 12): REQUIRED_ENV is gone; Grok's names matter only for Grok ----------

def test_status_configured_reads_the_same_set_up_rule(monkeypatch, tmp_path):
    from router import settings, status
    env = {"GROK_WEBHOOK_URL": "https://example.invalid/FAKE", "GROK_WEBHOOK_KEY": "FAKE-KEY-0002"}
    assert status.configured("grok", ROSTER, env, doc=DOC) is True
    assert status.configured("grok", ROSTER, env, doc={}) is False                       # no inbox repo in settings
    assert status.configured("grok", ROSTER, {**env, "GROK_WEBHOOK_KEY": " "}, doc=DOC) is False
    assert status.configured("chatgpt", _without_model("chatgpt"), env, doc=DOC) is False
    assert status.configured("claude", ROSTER, {}, doc={}) is True                        # Claude needs no .env name
    assert status.configured("grok", ROSTER, env) is True                                 # conftest: owner/inbox


def test_a_grok_send_without_its_webhook_names_sends_nothing_and_fails_the_call(tmp_path):
    from types import SimpleNamespace
    from router import __main__ as cli
    from router import log
    conn = log.init_db(":memory:")
    log.add_task(conn, "sr-20261021-120000-aa01", "what is new on X", "cli", {"status": "ok", "label": "x_social_pulse",
                                                                            "confidence": 0.9, "tokens": 0})
    log.set_route(conn, "sr-20261021-120000-aa01", agents=tuple(ROSTER.agents), agent="grok", route_reason="best",
                  skill="x_social_pulse", checker="chatgpt", check_state="pending")
    posted, lines = [], []
    deps = SimpleNamespace(config={"GROK_WEBHOOK_URL": "https://example.invalid/FAKE"}, post=lambda *a, **k: posted.append(a))
    task = log.get_task(conn, "sr-20261021-120000-aa01")
    code = cli._send_grok(conn, task, "sr-20261021-120000-aa01-c1", "check", "a check", deps, secrets=(), out=lines.append)
    assert code is None and posted == []
    row = log.get_call(conn, "sr-20261021-120000-aa01-c1")
    assert (row["status"], row["text"]) == ("failed", "Grok Bot isn't set up: no GROK_WEBHOOK_KEY in .env")
