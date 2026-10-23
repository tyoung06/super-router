"""Build brief 21, B2 (rules v2.30, Status and JSON and Router for the interface; decisions 8 and 9): `sr status
[--json]`. One JSON object and nothing else with --json; written by nothing, calling no model: the online checks are
commands (Claude's `claude auth status`, Phase 0 C1), each agent's live, configured, model, served model, version, probe
state and calls this week; the presets with their chains and slots, the skills, the commands from the parser, the open
tasks with what they wait on, Jev's meter (never its key), memory, projects, chats and the settings. No `.env` value
anywhere in the output. Fakes only; every value here is fake."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from router import __main__ as cli
from router import cursor_worker, log, online, search, status
from tests.fixtures import json_shapes
from tests.helpers import shipped_roster
from tests.test_json_actions import FAKE_ENV, World, jev
from tests.test_loop import Scripted
from tests.test_relay import Chat
from tests.helpers import fake_label

ROSTER = shipped_roster()
# Brief 22, decision 11: the rules version is read from SUPER-ROUTER.md line 3, so a rules bump never breaks a pin.
# Brief 25 (P2): through the same reader `sr status` uses, which falls back to docs/RULES.md, the cleaned copy a public
# clone carries in place of SUPER-ROUTER.md.
RULES = status.rules_version(status.rules_file(Path(cli.ROOT)))


class FakeStore:
    def __init__(self, up=True, documents=13):
        self.up, self.documents = up, documents

    def online(self, timeout=2):
        return self.up

    def stats(self):
        return {"total_documents": self.documents}


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    w = World(monkeypatch, tmp_path, capsys)
    w.checked = []

    def check(name, ok=True, reason=None):
        def run():
            w.checked.append(name)
            return online.Answer((ok, reason), None if ok else "signed_out")  # brief 24: the real checks' shape
        return run
    monkeypatch.setattr(cli.online, "CHECKS", {"claude": check("claude"), "chatgpt": check("chatgpt"),
                                               "grok": check("grok"), "cursor": check("cursor", False, "not signed in (agent login)")})
    monkeypatch.setattr(cli.search, "claude_version", lambda *a, **k: "2.1.305")
    monkeypatch.setattr(cli.codex_probe, "codex_version", lambda *a, **k: "0.162.1")
    monkeypatch.setattr(cli.cursor_worker, "installed_version", lambda *a, **k: "2026.10.19-6bbf2c4")
    monkeypatch.setattr(cli.memory, "client", lambda *a, **k: FakeStore())
    cli.PROBE_STATE.write_text(json.dumps({"claude_search": {"version": "2.1.305"}, "claude_web_files": {"version": "2.1.304"},
                                           "cursor_sandbox": {"version": "2026.10.19-6bbf2c4"}}))
    return w


def _status(world):
    code, out, err = world.run("status", "--json")
    assert code == 0 and err == "" and len(out.splitlines()) == 1, (out, err)
    return json.loads(out)


def test_the_document_has_every_key_and_type(world):
    doc = _status(world)
    json_shapes.check(doc, json_shapes.STATUS, optional=("report_path",))
    assert (doc["api_version"], doc["log_version"], doc["version"]) == (1, log.VERSION, RULES)


def test_the_four_agents_live_with_their_checks_models_versions_and_probes(world):
    doc = _status(world)
    by = {a["name"]: a for a in doc["agents"]}
    assert list(by) == ["claude", "chatgpt", "grok", "cursor"] and "muse" not in by
    assert all(a["live"] and a["configured"] for a in by.values())
    assert (by["cursor"]["model"], by["chatgpt"]["model"], by["claude"]["model"], by["grok"]["model"]) == (
        "grok-4.7-high", "gpt-6.1-sol", "sonnet", None)
    assert (by["claude"]["online"], by["cursor"]["online"], by["cursor"]["reason"]) == (True, False, "not signed in (agent login)")
    assert by["claude"]["checked_at"] and by["claude"]["reason"] is None
    assert by["claude"]["probe"] == {"passed_on": "2.1.305", "current": "2.1.305", "state": "passed", "web_files": "moved"}
    assert by["cursor"]["probe"] == {"passed_on": "2026.10.19-6bbf2c4", "current": "2026.10.19-6bbf2c4", "state": "passed"}
    # brief 24 (decision 10): ChatGPT's Codex probe keeps a pass per Codex version, so its state reads as Cursor's does
    assert by["chatgpt"]["probe"] == {"passed_on": None, "current": "0.162.1", "state": "missing"}
    assert by["grok"]["probe"] is None and by["grok"]["version"] is None
    assert sorted(world.checked) == ["chatgpt", "claude", "cursor", "grok"]


def test_an_agent_absent_from_the_config_reads_not_configured_and_is_never_checked(world, monkeypatch):
    from tests.helpers import roster_with
    from router.roster import Roster
    agents = {k: v for k, v in ROSTER.agents.items() if k != "cursor"}
    monkeypatch.setattr(cli, "load_roster", lambda **k: Roster(agents=agents, not_routed=ROSTER.not_routed, table=ROSTER.table))
    by = {a["name"]: a for a in _status(world)["agents"]}
    assert (by["cursor"]["online"], by["cursor"]["reason"], by["cursor"]["configured"], by["cursor"]["live"]) == (
        None, "not configured", False, False)
    assert "cursor" not in world.checked


def test_the_presets_their_chains_and_slots(world):
    doc = _status(world)
    by = {p["name"]: p for p in doc["presets"]}
    assert list(by) == ["research-build", "collab", "versus", "redteam", "vote"]
    assert {name: p["chain"] for name, p in by.items()} == {
        "research-build": "Grok research → Claude build → ChatGPT check",
        "collab": "Claude plan → ChatGPT amend → Claude build → ChatGPT edit (check)",
        "versus": "Claude build → ChatGPT build → ChatGPT review → Claude review → your pick",
        "redteam": "Claude build → ChatGPT attack → Claude revise → ChatGPT check",
        "vote": "Claude vote → ChatGPT vote → Grok vote → tally"}
    assert all(p["description"] is None or (p["description"].strip() and "\n" not in p["description"])
               for p in by.values())  # 1.5 has none; the owner's 1.6 adds one line each
    slots = {(p, s["name"]): s for p, preset in by.items() for s in preset["slots"]}
    # brief 24 (decision 14): a slot offers only available agents; this world's Cursor check says signed out
    assert slots[("versus", "a")] == {"name": "a", "default": "claude", "allowed": ["claude", "grok", "chatgpt"]}
    assert "cursor" not in slots[("research-build", "build")]["allowed"] and "cursor" not in slots[("vote", "c")]["allowed"]
    assert by["research-build"]["agents"] == ["grok", "claude", "chatgpt"]


def test_the_skills_and_the_commands(world):
    doc = _status(world)
    assert len(doc["skills"]) == 12 and doc["skills"][-1]["key"] == "recall"
    assert {s["key"]: (s["best"], s["second"]) for s in doc["skills"]}["recall"] == ("claude", "chatgpt")
    commands = {c["name"]: c for c in doc["commands"]}
    assert {"route", "relay", "split", "resume", "pick", "fallback", "check", "log", "show", "cancel", "serve", "status",
            "project", "chat"} <= set(commands)
    assert {"--json", "--no-wait", "--source", "--chat", "--project", "--file", "--web"} <= {
        a["name"] for a in commands["route"]["arguments"]}


def test_the_open_tasks_and_what_they_wait_on(world):
    world.label = fake_label(jev("x_social_pulse", 0.95))
    sent = world.json("route", "what are gardeners saying about trays on X")
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("391")
    world.json("route", "what is 17 times 23")
    doc = _status(world)
    assert [(t["task_id"], t["waiting_on"], t["outcome"]) for t in doc["open_tasks"]] == [(sent["task_id"], "grok", None)]
    json_shapes.check(doc["open_tasks"][0], json_shapes.TASK)


def test_jev_s_meter_and_never_its_key(world):
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("391")
    world.json("route", "what is 17 times 23")
    code, out, err = world.run("status", "--json")
    doc = json.loads(out)
    assert doc["jev"] == {"configured": True, "tokens_month": 700, "cap": 1_000_000, "over_cap": False,
                          "floor": 0.8,  # brief 23 (decision 14): the floor from the skill table
                          "available": True, "why": None}  # brief 24 (decision 14)
    for value in FAKE_ENV.values():
        assert value not in out and json.dumps(value)[1:-1] not in out


def test_memory_projects_chats_and_the_settings(world, monkeypatch, tmp_path):
    from router import settings
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path / "home"))  # brief 27: no install there
    doc = _status(world)
    assert doc["memory"] == {"setting": "auto", "online": True, "starting": False, "documents": 13, "installed": False}
    assert (doc["projects"], doc["chats"], doc["serve_port"]) == ([], [], 8765)
    assert "report_path" not in doc
    assert doc["projects_root"] == "~/Projects"  # brief 26 (decision 8): the default, from code
    settings.LOCAL_PATH.write_text(json.dumps({"report_path": "~/Downloads/claude-code-report.md",
                                               "projects_root": "~/Desktop/garden-projects"}))
    assert _status(world)["report_path"].endswith("Downloads/claude-code-report.md")
    assert _status(world)["projects_root"] == "~/Desktop/garden-projects"  # as written, `~` and all
    monkeypatch.setattr(cli.memory, "client", lambda *a, **k: FakeStore(up=False))
    assert _status(world)["memory"] == {"setting": "auto", "online": False, "starting": False, "documents": None,
                                        "installed": False}


def test_memory_installed_reads_the_hindsight_binary_in_the_home_folder(world, monkeypatch, tmp_path):
    # brief 27 (decision 9): whether memory_server.paths(home)["binary"] exists
    from router import memory_server
    home = tmp_path / "home"
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: home))
    assert _status(world)["memory"]["installed"] is False
    binary = memory_server.paths(home)["binary"]
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    assert _status(world)["memory"]["installed"] is True


def test_memory_starting_only_while_memory_is_on(world):
    # brief 27 E (the owner): `sr memory off` holds the memory lock while it stops the store (up to 30 s); that is not
    # a start, so `starting` reads true only while the lock is held and the setting isn't off
    from router import locks, runs, settings
    folder = cli.DB_PATH.parent / runs.FOLDER_NAME
    with locks.held("memory", folder=folder):
        assert _status(world)["memory"]["starting"] is True
        settings.LOCAL_PATH.write_text(json.dumps({"memory": "off"}))
        assert _status(world)["memory"]["starting"] is False
    settings.LOCAL_PATH.write_text(json.dumps({"memory": "auto"}))
    assert _status(world)["memory"]["starting"] is False


def test_status_writes_nothing_and_needs_no_log(world):
    assert not cli.DB_PATH.exists()
    doc = _status(world)
    assert not cli.DB_PATH.exists() and doc["open_tasks"] == [] and doc["jev"]["tokens_month"] == 0
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("391")
    world.json("route", "what is 17 times 23")
    from tests.helpers import sha256
    before = sha256(cli.DB_PATH)
    _status(world)
    world.run("status")
    assert sha256(cli.DB_PATH) == before


def test_without_json_it_prints_lines_and_no_json(world):
    code, out, err = world.run("status")
    assert code == 0 and err == "" and out.startswith("Agents:\n") and "{" not in out
    assert "cursor   live  offline (not signed in (agent login))" in out and f"Rules {RULES}, log version {log.VERSION}" in out


# ---------- the checks themselves: commands, never a model ----------

class Run:
    def __init__(self, stdout="", returncode=0, raises=None):
        self.stdout, self.returncode, self.raises, self.calls = stdout, returncode, raises, []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        if self.raises:
            raise self.raises
        return SimpleNamespace(stdout=self.stdout, stderr="", returncode=self.returncode)


SIGNED_IN = json.dumps({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty",
                        "email": "someone@example.invalid", "orgName": "Someone's Organization", "subscriptionType": "max"})


@pytest.mark.parametrize("run, want", [
    (Run(SIGNED_IN), (True, None)),
    (Run(json.dumps({"loggedIn": False, "authMethod": "none"}), 1), (False, "not signed in (claude auth login)")),
    (Run(json.dumps({"loggedIn": True, "authMethod": "console"})), (False, "signed in with console, not the Claude plan")),
    (Run("not json"), (False, "claude auth status gave no answer")),
    (Run(raises=OSError("no claude")), (False, "claude auth status did not answer (OSError)")),
])
def test_claudes_check_is_claude_auth_status(run, want):
    assert online.claude(run=run, environ={"HOME": "/h", "PATH": "/p", "ANTHROPIC_API_KEY": "sk-fake"}) == want
    argv, kw = run.calls[0]
    assert argv == ["claude", "auth", "status"] and "ANTHROPIC_API_KEY" not in kw["env"]
    assert "someone@example.invalid" not in str(want)


@pytest.mark.parametrize("run, want", [(Run("owner/inbox\n"), (True, None)),
                                       (Run("Owner/Inbox\n"), (True, None)),  # brief 24: GitHub's own case
                                       (Run("", 1), (False, "the inbox repo did not answer (gh)")),
                                       (Run(raises=OSError()), (False, "the inbox repo did not answer (OSError)"))])
def test_groks_check_reads_the_inbox_repo_and_never_the_webhook(run, want):
    assert online.grok(run=run) == want
    assert run.calls[0][0] == ["gh", "api", "repos/owner/inbox", "--jq", ".full_name"]  # conftest: the setting


def test_groks_check_without_the_setting_runs_nothing_and_says_so(monkeypatch, tmp_path):
    from router import settings
    local = tmp_path / "bare.local.json"
    local.write_text("{}")
    monkeypatch.setattr(settings, "LOCAL_PATH", local)
    run = Run("owner/inbox\n")
    found = online.grok(run=run)
    assert (found, found.code, run.calls) == ((False, "no inbox repo in settings"), "not_configured", [])


def test_chatgpt_and_cursor_checks_reuse_the_workers_own():
    assert online.chatgpt(login=lambda: True) == (True, None)
    assert online.chatgpt(login=lambda: False) == (False, "not signed in with ChatGPT (codex login)")
    assert online.cursor(check=lambda: (False, "not signed in (agent login)")) == (False, "not signed in (agent login)")


def test_a_check_that_raises_reads_offline_by_its_type():
    def boom():
        raise RuntimeError("secret detail")
    found = online.run_all({"claude": boom, "grok": lambda: (True, None)}, now=datetime(2026, 10, 20, tzinfo=timezone.utc))
    # brief 24 (A1): each answer carries its code too; a check that blows up is `unreachable`
    assert found["claude"] == {"online": False, "reason": "check failed (RuntimeError)", "checked_at": "2026-10-20T00:00:00+00:00",
                               "code": "unreachable"}
    assert found["grok"]["online"] is True


def test_calls_this_week_count_from_monday_local():
    conn = log.init_db(":memory:")
    log.add_task(conn, "sr-1", "t", "cli", jev("writing"))
    now = datetime(2026, 10, 21, 12, 0).astimezone()  # a Wednesday
    monday = status.monday(now)
    assert monday.weekday() == 0 and (monday.hour, monday.minute) == (0, 0)
    log.add_call(conn, "sr-1-a", "sr-1", "do", "claude", status="done", text="x", now=monday)
    log.add_call(conn, "sr-1-b", "sr-1", "check", "chatgpt", status="done", text="PASS",
                 now=monday.replace(day=monday.day - 1))  # the Sunday before: last week
    assert status.calls_this_week(conn, now) == {"claude": 1}


# ---------- build brief 24, A7 (decisions 1, 13 and 14): available and why ----------

def test_each_agent_says_whether_it_is_available_and_why_not(world):
    by = {a["name"]: a for a in _status(world)["agents"]}
    assert {n: (a["available"], a["why"], a["why_code"]) for n, a in by.items()} == {
        "claude": (True, None, None), "chatgpt": (True, None, None), "grok": (True, None, None),
        "cursor": (False, "Cursor is signed out (agent login)", "signed_out")}  # the world's Cursor check says no
    doc = _status(world)
    assert (doc["jev"]["available"], doc["jev"]["why"]) == (True, None)


def test_grok_bot_without_the_inbox_setting_reads_not_set_up_and_is_never_checked(world, monkeypatch, tmp_path):
    from router import settings
    local = tmp_path / "bare.local.json"
    local.write_text("{}")
    monkeypatch.setattr(settings, "LOCAL_PATH", local)
    by = {a["name"]: a for a in _status(world)["agents"]}
    assert (by["grok"]["configured"], by["grok"]["online"], by["grok"]["available"], by["grok"]["why_code"]) == (
        False, None, False, "not_configured")
    assert by["grok"]["why"] == "Grok Bot isn't set up: no inbox repo in settings"
    assert "grok" not in world.checked


def test_a_failed_codex_probe_on_the_installed_version_reads_chatgpt_off(world):
    state = json.loads(cli.PROBE_STATE.read_text())
    state["codex_sandbox_failure"] = {"version": "0.162.1", "kind": "ran_failed", "reason": "workspace/ unchanged: new",
                                      "at": "2026-10-21T12:00:00+00:00"}
    cli.PROBE_STATE.write_text(json.dumps(state))
    by = {a["name"]: a for a in _status(world)["agents"]}
    assert (by["chatgpt"]["available"], by["chatgpt"]["why"], by["chatgpt"]["probe"]["state"]) == (
        False, "ChatGPT is off: its safety check failed on codex 0.162.1", "failed")


def test_jev_without_its_key_is_not_available(world, monkeypatch):
    env = {k: v for k, v in world_env().items() if k != "JEV_API_KEY"}
    monkeypatch.setattr(cli, "dotenv_values", lambda path: dict(env))
    doc = _status(world)
    assert (doc["jev"]["configured"], doc["jev"]["available"], doc["jev"]["why"]) == (
        False, False, "Jev isn't set up: no JEV_API_KEY in .env")


def world_env():
    from tests.test_json_actions import FAKE_ENV
    return dict(FAKE_ENV)
