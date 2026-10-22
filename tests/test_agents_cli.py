"""Agents come from config/agents.json: override tags, the send lookup, the help text,
and refusing to run on a broken config. Every secret here is fake."""
import json

import pytest

from router import __main__ as cli
from router import log, roster, routing
from tests.helpers import shipped_roster, fake_label

CONFIG = {"GROK_WEBHOOK_URL": "https://example.invalid/hook", "GROK_WEBHOOK_KEY": "FAKE-KEY-123"}
ALL = ("claude", "grok", "chatgpt", "muse")


class Recorder:
    def __init__(self, value=None):
        self.value, self.calls = value, []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.value


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _count(conn):
    return conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]


def _route(conn, task, *, label=None, post=None, worker=None):
    lines = []
    code = cli.cmd_route(
        task, conn=conn, config=CONFIG, roster=shipped_roster(), label=label or fake_label(), environ={}, settings_paths=[],
        post=post or Recorder(), worker=worker or Recorder("an answer"),
        out=lines.append,
    )
    return code, "\n".join(lines)


# ---------- override tags ----------

@pytest.mark.parametrize("task", ["@muse write a poem", "@MUSE find trends on Threads", "  @Muse"])
def test_a_tag_for_an_agent_that_is_not_live_is_refused_before_anything(conn, task):
    label, post, worker = fake_label(), Recorder(), Recorder("x")
    code, out = _route(conn, task, label=label, post=post, worker=worker)
    assert code == 2 and "not live" in out and "Nothing was logged" in out
    assert _count(conn) == 0 and label.calls == [] and post.calls == [] and worker.calls == []


def test_override_tags_come_from_the_config():
    assert routing.parse_override("@muse find trends", ALL) == ("muse", "find trends")
    assert routing.parse_override("@testbot hi", ("claude", "testbot")) == ("testbot", "hi")
    assert routing.parse_override("@testbot hi", ALL) == (None, "@testbot hi")


def test_a_live_tag_still_works(conn):
    code, _ = _route(conn, "@claude explain venvs")
    row = log.recent_tasks(conn)[0]
    assert code == 0 and (row["agent"], row["route_reason"], row["task"]) == ("claude", "override", "explain venvs")


# ---------- one lookup from agent name to its send function ----------

def test_every_live_agent_has_a_send_function():
    assert set(shipped_roster().live) <= set(cli.SENDERS)


def test_sending_goes_through_the_lookup(conn, monkeypatch):
    seen = []

    def fake(conn_, task, call_id, kind, prompt, deps, *, secrets, out, web_search="disabled", **kwargs):
        seen.append((task["task_id"], call_id, kind, prompt))
        log.add_call(conn_, call_id, task["task_id"], kind, "claude", status="done", text="an answer")

    monkeypatch.setitem(cli.SENDERS, "claude", fake)
    code, _ = _route(conn, "@claude hi")
    row = log.recent_tasks(conn)[0]
    assert code == 0 and seen == [(row["task_id"], row["task_id"], "do", "hi")]


# ---------- main reads the config ----------

def _broken_config(monkeypatch, tmp_path):
    path = tmp_path / "agents.json"
    path.write_text(json.dumps({"agents": {"claude": {"live": True}}, "skills_not_routed": []}))
    monkeypatch.setattr(roster, "AGENTS_PATH", path)


@pytest.mark.parametrize("command", [["route", "hi"], ["serve"], ["probe"]])
def test_route_serve_and_probe_refuse_a_broken_config_and_log_nothing(monkeypatch, tmp_path, capsys, command):
    _broken_config(monkeypatch, tmp_path)
    monkeypatch.setattr(cli.safety, "prepare_workspace", lambda *a, **k: pytest.fail("must not prepare"))
    monkeypatch.setattr(cli.page, "serve", lambda *a, **k: pytest.fail("must not serve"))
    assert cli.main(command, platform="darwin") == 2
    out = capsys.readouterr().out
    assert "Refused" in out and "muse" in out
    assert not cli.DB_PATH.exists(), "nothing is logged"


@pytest.mark.parametrize("command", [["log"], ["show"], ["cancel"], ["check"]])
def test_other_commands_still_work_with_a_broken_config(monkeypatch, tmp_path, command):
    _broken_config(monkeypatch, tmp_path)
    env_file = tmp_path / ".env"  # check needs the webhook settings, like route; these are fake
    env_file.write_text('GROK_WEBHOOK_URL="https://example.invalid/hook"\nGROK_WEBHOOK_KEY="FAKE-KEY-123"\n')
    monkeypatch.setattr(cli, "ENV_PATH", env_file)
    monkeypatch.setattr(cli.safety, "prepare_workspace", lambda *a, **k: None)
    monkeypatch.setattr(cli.inbox, "fetch_issues", lambda: [])
    assert cli.main(command, platform="darwin") in (0, 1)  # 1 = nothing to show or cancel


def test_serve_gets_the_agents_and_the_presets_from_the_config(monkeypatch):
    """Brief 21, B4: the page reads the agents and the presets from `sr status --json`, which reads the config; the
    server itself gets only its port."""
    from router import presets, relay, status
    seen = {}
    monkeypatch.setattr(cli.page, "serve", lambda port, **kw: seen.update(port=port, **kw) or 0)
    assert cli.main(["serve"], platform="darwin") == 0 and set(seen) == {"port", "out", "start_memory"}  # brief 22
    roster = cli.load_roster(send_paths=tuple(cli.SENDERS))
    loaded = presets.load_presets(roster, tuple(cli.SENDERS), relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
    assert list(roster.agents) == ["claude", "grok", "chatgpt", "cursor", "muse"]  # brief 20 added cursor
    assert [p["name"] for p in (status.preset_view(p, roster.live) for p in loaded.presets.values())] == [
        "research-build", "collab", "versus", "redteam", "vote"]  # brief 6 collab, 9 versus, 16 redteam, 17 vote


def test_help_text_names_the_live_agents_from_the_config(capsys):
    with pytest.raises(SystemExit):
        cli.main(["route", "--help"], platform="darwin")
    out = capsys.readouterr().out
    assert "@claude" in out and "@grok" in out and "@chatgpt" in out
    assert "@muse" not in out
