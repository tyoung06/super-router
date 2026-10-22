"""Phase A of build brief 8: the search switch (rules v2.15, Web search). Search is decided in code
by preset and role only (the owner's amendment: never by agent): on research-build's build stage and
its fix round, with no files. Claude gets WebSearch only after `sr probe` passed on the installed
Claude Code version; ChatGPT doing that call on a resume gets its own search. No test runs claude."""
import json
import sqlite3
import subprocess
from datetime import datetime, timezone

import pytest

from router import __main__ as cli
from router import claude_worker, log, safety, search
from tests.helpers import ALL_AGENTS, make_v5_log, sha256
from tests.test_collab import AMENDED, DELIVERABLE, EDITED, LOADED, PLAN
from tests.test_collab import TASK as COLLAB_TASK
from tests.test_loop import Clock, Scripted
from tests.test_relay import CONFIG, GOOD_NOTE, ROSTER, TASK, Chat, RelayHook
from tests.helpers import fake_label

T0 = datetime(2026, 10, 15, 22, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _task(mode="relay", preset="research-build", web=None):
    return {"mode": mode, "preset": preset if mode == "relay" else None, "web": web}


# ---------- the switch (brief 15 addendum, rules v2.22: every call, unless a file without --web) ----------

FILE = (("a.png", "a.png"),)


@pytest.mark.parametrize("task, kind, role, files, expected", [
    (_task(), "stage", "build", (), True),
    (_task(), "reask", "build", (), True),
    (_task(), "fix", None, (), True),
    (_task(mode="route"), "fix", None, FILE, False),            # a file call without --web: no search
    (_task(mode="route"), "do", None, FILE, False),
    (_task(mode="route", web=1), "do", None, FILE, True),      # --web: the file call may search
    (_task(mode="route", web=1), "check", None, FILE, True),
    (_task(), "stage", "research", (), True),                    # before rules v2.22 these were all False
    (_task(), "check", None, (), True),
    (_task(), "recheck", None, (), True),
    (_task(preset="collab"), "stage", "execute", (), True),
    (_task(preset="collab"), "stage", "plan", (), True),
    (_task(preset="collab"), "stage", "edit", (), True),
    (_task(mode="route"), "do", None, (), True),
    (_task(mode="route"), "fix", None, (), True),
])
def test_search_is_allowed_on_every_call_unless_it_carries_a_file_without_web(task, kind, role, files, expected):
    assert search.allowed(task, kind=kind, role=role, files=files) is expected


@pytest.mark.parametrize("agent, ready, expected", [
    ("claude", True, "allowed"), ("claude", False, "off (probe not passed)"),
    ("chatgpt", True, "allowed"), ("chatgpt", False, "allowed"),   # ChatGPT's search has its own probe rule
])
def test_the_state_on_an_eligible_call_by_agent_and_probe(agent, ready, expected):
    assert search.state(_task(), kind="stage", role="build", agent=agent, files=(), ready=lambda: ready) == expected


def test_a_file_call_without_web_is_off_and_never_asks_the_probe_and_grok_has_no_state():
    asked = []
    for agent in ("claude", "chatgpt"):
        assert search.state(_task(mode="route"), kind="do", role=None, agent=agent, files=FILE,
                            ready=lambda: asked.append(1) or True) == "off (file without --web)"
    assert asked == []
    assert search.state(_task(preset="collab"), kind="stage", role="execute", agent="grok", files=(),
                        ready=lambda: asked.append(1) or True) is None and asked == []


# ---------- the probe gate: a pass is kept per Claude Code version ----------

def test_ready_only_when_a_pass_is_stored_for_the_installed_version(tmp_path):
    state = tmp_path / "probe_state.json"
    assert search.ready(state, "2.1.301") is False
    search.record_pass(state, "2.1.301", now=T0)
    assert search.ready(state, "2.1.301") is True
    assert search.ready(state, "2.1.302") is False, "a Claude Code update needs the probe again"
    assert search.ready(state, "unknown") is False
    search.clear(state)
    assert search.ready(state, "2.1.301") is False
    state.write_text("not json")
    assert search.ready(state, "2.1.301") is False


def test_the_installed_version_comes_from_claude_version(fake_run):
    assert search.claude_version(run=fake_run(stdout="2.1.301 (Claude Code)\n")) == "2.1.301"
    assert search.claude_version(run=fake_run(returncode=1)) == "unknown"
    assert search.claude_version(run=fake_run(raises=OSError("no claude"))) == "unknown"
    run = fake_run(stdout="2.1.301 (Claude Code)\n")
    search.claude_version(run=run)
    assert run.calls[0][0] == ["claude", "--version"]


# ---------- the worker ----------

def _events(*, tools=("WebSearch",), servers=(), uses=(("WebSearch", "soil sensor prices 2026"),),
            result="The brief.", is_error=False):
    lines = [{"type": "system", "subtype": "init", "tools": list(tools), "mcp_servers": list(servers)}]
    for name, query in uses:
        lines.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": name, "input": {"query": query}}]}})
    lines.append({"type": "result", "subtype": "success", "is_error": is_error, "result": result})
    return "\n".join(json.dumps(e) for e in lines) + "\n"


ENVIRON = {"HOME": "/h", "PATH": "/bin"}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_worker, "WORKSPACE", tmp_path / "workspace")
    return tmp_path / "workspace"


def test_the_search_command_allows_websearch_only_and_denies_the_rest_by_name():
    argv = safety.claude_search_argv("sonnet")
    assert argv[:2] == ["claude", "-p"] and argv[argv.index("--tools") + 1] == "WebSearch"
    assert argv[argv.index("--allowedTools") + 1] == "WebSearch"
    denied = argv[argv.index("--disallowedTools") + 1: argv.index("--output-format")]
    assert "WebFetch" in denied and {"Bash", "Read", "Write", "Edit"} <= set(denied) and "WebSearch" not in denied
    assert argv[argv.index("--output-format") + 1] == "stream-json" and "--verbose" in argv
    for flag in ("--strict-mcp-config", "--no-session-persistence", "--safe-mode"):
        assert flag in argv
    assert "--dangerously-skip-permissions" not in argv and "--bare" not in argv


def test_a_call_without_search_keeps_todays_command_byte_for_byte():
    assert safety.claude_argv("sonnet") == ["claude", "-p", "--model", "sonnet", "--strict-mcp-config",
                                            "--no-session-persistence", "--safe-mode", "--tools", ""]


def test_a_search_call_returns_the_result_and_the_queries(fake_run, ws):
    run = fake_run(stdout=_events(uses=(("WebSearch", "K10 price"), ("WebSearch", "Sprig Gen2 price"))))
    answer = claude_worker.run("build it", run=run, environ=ENVIRON, search=True)
    assert answer == "The brief." and answer.queries == ["K10 price", "Sprig Gen2 price"]
    argv, kw = run.calls[0]
    assert argv == safety.claude_search_argv("sonnet") and kw["input"] == "build it" and kw["cwd"] == ws


def test_a_search_call_with_files_runs_the_web_file_command_in_the_copy_folder(fake_run, ws, tmp_path):
    # rules v2.22 (brief 15 addendum, D8): before, a search call with files was refused; now it runs with Read and
    # WebSearch in the task's copy folder (tests/test_web_flag.py has the Read guard)
    (tmp_path / "a.png").write_bytes(b"png")
    run = fake_run(stdout=_events(tools=("Read", "WebSearch")))
    answer = claude_worker.run("x", run=run, environ=ENVIRON, files=[(tmp_path / "a.png", "a.png")], tag="t", search=True)
    argv, kw = run.calls[0]
    assert answer == "The brief." and argv == safety.claude_web_files_argv("sonnet") and kw["cwd"] == ws / "task-t"
    assert not (ws / "task-t").exists()


@pytest.mark.parametrize("events, words", [
    (_events(tools=("WebSearch", "Read")), "Read"),
    (_events(servers=({"name": "x"},)), "MCP"),
    (_events(uses=(("WebSearch", "q"), ("WebFetch", "https://x"))), "WebFetch"),
    ("not json at all\n", "no result"),
])
def test_a_search_call_that_had_any_other_tool_fails(fake_run, ws, events, words):
    with pytest.raises(claude_worker.WorkerError, match=words):
        claude_worker.run("x", run=fake_run(stdout=events), environ=ENVIRON, search=True)


def test_a_plan_limit_inside_the_stream_is_still_a_plan_limit(fake_run, ws):
    run = fake_run(returncode=1, stdout=_events(uses=(), result="You've hit your session limit · resets 3pm",
                                                is_error=True))
    with pytest.raises(claude_worker.WorkerError) as err:
        claude_worker.run("x", run=run, environ=ENVIRON, search=True)
    assert err.value.code == "plan_limit"


def test_more_than_five_searches_is_counted_not_refused(fake_run, ws):
    uses = tuple(("WebSearch", f"q{i}") for i in range(7))
    answer = claude_worker.run("x", run=fake_run(stdout=_events(uses=uses)), environ=ENVIRON, search=True)
    assert len(answer.queries) == 7 and search.MAX_SEARCHES == 5


# ---------- log version 7: calls.search ----------

def test_a_new_log_is_version_7_with_the_search_column(tmp_path):
    c = log.init_db(tmp_path / "router.db")
    assert c.execute("PRAGMA user_version").fetchone()[0] == log.VERSION == 16
    assert [r[1] for r in c.execute("PRAGMA table_info(calls)")][-6:] == ["search", "fallback_of", "context", "memory", "served", "round_file"]
    assert log.V6_CALL_COLUMNS == log.V5_CALL_COLUMNS + ("reason_code", "resume_of")
    c.close()


def test_the_search_record_is_checked_and_read_back(conn):
    from tests.helpers import add_row
    add_row(conn, "t")
    log.add_call(conn, "t", "t", "do", "claude", status="done", text="x",
                 search={"state": "allowed", "queries": ["a", "b"], "count": 2})
    assert log.search_of(log.get_call(conn, "t")) == {"state": "allowed", "queries": ["a", "b"], "count": 2}
    with pytest.raises(ValueError, match="search"):
        log.add_call(conn, "t-c1", "t", "check", "claude", status="done", text="x", search={"state": "maybe"})
    log.add_call(conn, "t-c2", "t", "recheck", "claude", status="done", text="x")
    assert log.search_of(log.get_call(conn, "t-c2")) is None


def test_upgrade_from_version_6_adds_the_search_column_and_keeps_every_row(tmp_path):
    db, backups = tmp_path / "router.db", tmp_path / "backups"
    c = sqlite3.connect(db)
    from tests.helpers import V5_SCHEMA, V5_CALLS_SCHEMA
    calls6 = V5_CALLS_SCHEMA.replace("    role        TEXT\n)", "    role        TEXT,\n    reason_code TEXT,\n"
                                                               "    resume_of   TEXT\n)")
    c.executescript(f"{V5_SCHEMA}; {calls6}; PRAGMA user_version = 6;")
    c.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, status)"
              " VALUES ('sr-1', 'x', 'x', 'cli', 't', 'ok', 'done')")
    c.execute("INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at, text, reason_code)"
              " VALUES ('sr-1', 'sr-1', 'do', 'claude', 'failed', 'x', 'plan limit', 'plan_limit')")
    c.commit(); c.close()
    before = sha256(db)
    done = log.migrate(db, backups, now=T0)
    assert (done["from"], done["rows"], done["calls"]) == (6, 1, 1)
    assert done["added"] == "search and fallback_of columns added to calls; parent and split_plan columns added to tasks; slots and web columns added to tasks; project and handoff columns added to tasks; context column added to calls; chat and memory columns added to tasks; memory column added to calls; served column added to calls; reason_code column added to tasks; round_file column added to calls; pid, run_started_at and answered_by columns added to tasks; skill_source set to owner where it named the one who labeled the task"
    assert done["backup_check"]["content"] == "same"  # brief 22: the backup API copy is checked by its content, not its bytes
    c = sqlite3.connect(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 16
    assert c.execute("SELECT reason_code, search FROM calls").fetchone() == ("plan_limit", None)
    c.close()


# ---------- through the commands ----------

class SearchingClaude(Scripted):
    """A fake Claude worker that takes search= like the real one and answers with queries when on."""

    def __init__(self, *replies, queries=("K10 price 2026",)):
        super().__init__(*replies)
        self.kwargs, self.queries = [], list(queries)

    def __call__(self, prompt, **kw):
        self.kwargs.append(kw)
        text = super().__call__(prompt)
        return claude_worker.SearchAnswer(text, self.queries) if kw.get("search") else text


def _relay(conn, *, claude, chatgpt, ready, preset="research-build", task=TASK):
    lines, clock, hook = [], Clock(), RelayHook(s1=GOOD_NOTE)
    code = cli.cmd_relay(preset, task, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                         settings_paths=[], post=hook.post, worker=claude, chatgpt=chatgpt, codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True,
                         claude_ready=lambda: ready, out=lines.append)
    row = log.recent_tasks(conn)[0]
    return code, "\n".join(lines), row, {c["call_id"].removeprefix(row["task_id"]): c for c in log.calls_for(conn, row["task_id"])}


def test_with_the_probe_passed_claude_searches_on_the_build_stage_and_the_fix_round(conn):
    claude, chat = SearchingClaude("a brief", "a fixed brief"), Chat("FIX\n1. add a price", "PASS")
    code, out, row, calls = _relay(conn, claude=claude, chatgpt=chat, ready=True)
    assert code == 0, out
    assert [kw.get("search", False) for kw in claude.kwargs] == [True, True]          # build, fix
    assert log.search_of(calls["-s2"]) == {"state": "allowed", "queries": ["K10 price 2026"], "count": 1}
    assert log.search_of(calls["-f1"])["state"] == "allowed"
    assert log.search_of(calls["-s1"]) is None                                          # grok: nothing logged
    assert log.search_of(calls["-c1"]) == {"state": "allowed"}                          # rules v2.22: ChatGPT's row too
    assert [kw["web_search"] for kw in chat.kwargs] == ["live", "live"]                  # the relay checker, as before


def test_without_a_probe_pass_claude_runs_as_before_and_the_row_says_so(conn):
    claude, chat = SearchingClaude("a brief"), Chat("PASS")
    code, out, row, calls = _relay(conn, claude=claude, chatgpt=chat, ready=False)
    assert code == 0 and claude.kwargs == [{}], "today's call, no search argument at all"
    assert log.search_of(calls["-s2"]) == {"state": "off (probe not passed)"}


def test_collab_searches_on_every_stage_with_the_probe_passed(conn):
    # rules v2.22 (brief 15 addendum): before, collab never searched; now every stage may
    claude, chat = SearchingClaude(PLAN, DELIVERABLE), Chat(AMENDED, EDITED)
    code, out, row, calls = _relay(conn, claude=claude, chatgpt=chat, ready=True, preset="collab", task=COLLAB_TASK)
    assert code == 0, out
    assert claude.kwargs == [{"search": True}, {"search": True}]
    assert all(log.search_of(c)["state"] == "allowed" for c in calls.values())
    assert [kw["web_search"] for kw in chat.kwargs] == ["live", "live"]


def test_a_route_task_searches_on_every_call(conn):
    claude = SearchingClaude("two lines")
    lines, clock = [], Clock()
    cli.cmd_route("write two lines", conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                  label=fake_label({"status": "ok", "label": "writing", "confidence": 0.9, "needs_split": 0.1, "tokens": 0}),
                  post=None, worker=claude, chatgpt=Chat("PASS"), codex_login=lambda: True, sleep=clock.sleep,
                  clock=clock, wait=False, claude_ready=lambda: True, out=lines.append)
    assert claude.kwargs == [{"search": True}]   # rules v2.22: before, a route task never searched
    assert [log.search_of(c) for c in log.calls_for(conn, log.recent_tasks(conn)[0]["task_id"])] == [
        {"state": "allowed", "queries": ["K10 price 2026"], "count": 1}, {"state": "allowed"}]  # claude's do, chatgpt's check


def test_a_resumed_build_stage_by_chatgpt_searches_and_so_does_its_fix_round(conn):
    """The owner's amendment: by preset and role, not agent."""
    from router import chatgpt_worker
    limit = claude_worker.WorkerError("plan limit on claude: You've hit your session limit", code="plan_limit")
    code, out, row, calls = _relay(conn, claude=SearchingClaude(limit), chatgpt=Chat(), ready=True)
    assert row["failed_stage"] == 2
    lines, clock = [], Clock()
    claude, chat = SearchingClaude("FIX\n1. add a price", "PASS"), Chat("a brief by chatgpt", "a fixed brief")
    code = cli.cmd_resume([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                          settings_paths=[], post=None, worker=claude, chatgpt=chat, codex_login=lambda: True,
                          sleep=clock.sleep, clock=clock, wait=False, claude_ready=lambda: True, out=lines.append)
    assert code == 0, "\n".join(lines)
    assert [kw["web_search"] for kw in chat.kwargs] == ["live", "live"]            # the resumed build, then its fix
    assert claude.kwargs == [{"search": True}, {"search": True}], "rules v2.22: claude's check searches too"
    calls = {c["call_id"].removeprefix(row["task_id"]): c for c in log.calls_for(conn, row["task_id"])}
    assert log.search_of(calls["-s2-resume"]) == {"state": "allowed"}
    assert log.search_of(calls["-f1"]) == {"state": "allowed"}
    assert chatgpt_worker  # (imported for the reader: ChatGPT's search is codex's web_search, not WebSearch)
