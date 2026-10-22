"""Brief 15 addendum, phase D3: `--web` (rules v2.22). A per-task flag on `sr route` only: with it, every call on
the task may search, file or not; without it, a call that carries a file has no search for any agent. Refused on
relay, split, resume, fallback and check. Stored on the row (`web` 1); `sr show` says `web: on (sent with --web)`.
Claude's --web file call runs with Read and WebSearch in its copy folder, and every Read must be inside it (the owner's
D8); the mode needs its own probe pass (D9), and without it Claude works with no search while ChatGPT's half still
works. No test runs claude or codex: commands are checked as argument lists. Every value here is fake."""
import functools
import hashlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from router import __main__ as cli
from router import chatgpt_worker, checking, claude_worker, log, media, safety, search, web_files_probe
from tests.helpers import ALL_AGENTS, JEV_OK, fake_label, shipped_roster

ENVIRON = {"HOME": "/h", "PATH": "/bin", "USER": "t", "LANG": "C"}
MODEL = "gpt-6.1-sol"
CONFIG = {"GROK_WEBHOOK_URL": "https://example.invalid/hook", "GROK_WEBHOOK_KEY": "FAKE-KEY-123"}
ROSTER = shipped_roster()


@pytest.fixture(autouse=True)
def folders(tmp_path, monkeypatch):
    ws = tmp_path / "workspace"
    ws.mkdir()
    for mod in (safety, claude_worker, chatgpt_worker):
        monkeypatch.setattr(mod, "WORKSPACE", ws)
    monkeypatch.setattr(media, "MEDIA_ROOT", tmp_path / "media")
    return ws


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _stream(tools, calls=(), result="The answer."):
    """Claude's stream-json: init, then (name, input, is_error) per tool call with its result, then the result."""
    lines = [{"type": "system", "subtype": "init", "tools": list(tools), "mcp_servers": []}]
    for i, (name, tool_input, error) in enumerate(calls):
        lines.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": f"t{i}", "name": name, "input": tool_input}]}})
        lines.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "is_error": error, "content": "x"}]}})
    lines.append({"type": "result", "subtype": "success", "is_error": False, "result": result})
    return "\n".join(json.dumps(e) for e in lines) + "\n"


class FakeRun:
    """Stands in for subprocess.run for claude and codex alike; records each argv and working folder."""

    def __init__(self, claude_stream=None, claude_text="The answer.", codex_text="PASS"):
        self.claude_stream, self.claude_text, self.codex_text, self.calls = claude_stream, claude_text, codex_text, []

    def __call__(self, argv, **kwargs):
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv) and not kwargs.get("shell")
        cwd = Path(kwargs["cwd"])
        self.calls.append((argv, cwd, sorted(p.name for p in cwd.iterdir())))
        if argv[0] == "codex":
            Path(argv[argv.index("--output-last-message") + 1]).write_text(self.codex_text)
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "--output-format" in argv:
            stream = self.claude_stream if self.claude_stream is not None else _stream(
                argv[argv.index("--tools") + 1: argv.index("--allowedTools")], [("WebSearch", {"query": "q"}, False)])
            return subprocess.CompletedProcess(argv, 0, stream, "")
        return subprocess.CompletedProcess(argv, 0, self.claude_text, "")


# ---------- the flag ----------

def test_route_takes_web_and_it_is_off_by_default():
    parser = cli._parser(ROSTER)
    assert parser.parse_args(["route", "x", "--web"]).web is True
    assert parser.parse_args(["route", "x"]).web is False


def _seed():
    c = log.init_db(cli.DB_PATH)
    log.add_task(c, "sr-seed", "an earlier task", "cli", {"status": "ok", "label": "writing", "confidence": 0.9})
    c.close()
    return hashlib.sha256(cli.DB_PATH.read_bytes()).hexdigest()


@pytest.mark.parametrize("argv", [["relay", "versus", "x", "--web"], ["split", "x", "--web"], ["resume", "1", "--web"],
                                  ["fallback", "1", "--web"], ["check", "--web"]])
def test_web_is_refused_everywhere_but_route_and_the_log_is_unchanged(argv, capsys, monkeypatch):
    before = _seed()
    assert cli.main(argv, platform="darwin") == 2
    out = capsys.readouterr().out
    assert ("Refused: --web is for a routed task with files (sr route --file <path> --web). "
            "Nothing was logged or sent.") in out
    assert hashlib.sha256(cli.DB_PATH.read_bytes()).hexdigest() == before


def test_web_on_relay_is_the_refusal_not_a_slot_flag():
    assert cli._take_slot_flags(["relay", "versus", "x", "--web"]) == (["relay", "versus", "x", "--web"], [])


def test_web_with_no_files_is_accepted_logged_and_changes_nothing(conn):
    lines = []
    worker = functools.partial(claude_worker.run, run=FakeRun(), environ=ENVIRON)
    chatgpt = functools.partial(chatgpt_worker.run, model=MODEL, run=FakeRun(), environ=ENVIRON)
    code = cli.cmd_route("write two lines", conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=fake_label({**JEV_OK, "label": "writing"}), post=None, worker=worker, chatgpt=chatgpt,
                         codex_login=lambda: True, wait=False, claude_ready=lambda *a: True, web=True, out=lines.append)
    row = log.recent_tasks(conn)[0]
    assert code == 0 and row["web"] == 1
    states = [log.search_of(c)["state"] for c in log.calls_for(conn, row["task_id"])]
    assert states == ["allowed", "allowed"]   # what any task without files gets
    shown = []
    cli.cmd_show(conn=conn, words=[str(row["n"])], roster=ROSTER, out=shown.append)
    assert "web: on (sent with --web)" in shown


def test_a_task_without_web_shows_no_web_line(conn):
    log.add_task(conn, "sr-n", "t", "cli", {**JEV_OK, "label": "writing"})
    shown = []
    cli.cmd_show(conn=conn, words=["sr-n"], roster=ROSTER, out=shown.append)
    assert not any(line.startswith("web:") for line in shown)


# ---------- the commands each call runs, with and without --web ----------

def _file_task(conn, tmp_path, web, task_id="sr-f"):
    src = tmp_path / "photo.png"
    src.write_bytes(b"png")
    media.copy_in(task_id, [src])
    records = [media.record(media.in_dir(task_id) / "photo.png")]
    log.add_task(conn, task_id, "what is in this photo", "cli", {**JEV_OK, "label": "writing"}, files=records, web=web)
    log.set_route(conn, task_id, agents=ALL_AGENTS, agent="claude", route_reason="best", skill="writing",
                  skill_source="jev", checker="chatgpt", check_state="pending")
    return task_id


def _run(conn, task_id, run, ready):
    deps = SimpleNamespace(config=CONFIG, post=None, fetch=None, close=None, sleep=None, clock=None, wait=False,
                           worker=functools.partial(claude_worker.run, run=run, environ=ENVIRON),
                           chatgpt=functools.partial(chatgpt_worker.run, model=MODEL, run=run, environ=ENVIRON),
                           codex_login=lambda: True, codex_ok=None, presets=None, live=ROSTER.live, claude_ready=ready)
    return cli._run_loop(conn, task_id, deps, [], lambda *_: None)


def _web_search_setting(argv):
    return next(a for a in argv if a.startswith("web_search="))


def test_a_file_task_without_web_makes_no_search_command_and_chatgpt_disabled(conn, tmp_path):
    task_id, run = _file_task(conn, tmp_path, web=False), FakeRun()
    assert _run(conn, task_id, run, ready=lambda *a: True) == 0
    claude_argv, codex_argv = run.calls[0][0], run.calls[1][0]
    assert claude_argv == safety.claude_argv("sonnet", tools="Read") and "WebSearch" not in claude_argv
    assert _web_search_setting(codex_argv) == 'web_search="disabled"'
    assert [log.search_of(c)["state"] for c in log.calls_for(conn, task_id)] == ["off (file without --web)"] * 2
    prompts = [c["text"] for c in log.calls_for(conn, task_id)]
    assert checking.SEARCH_LINE_GENERAL not in "".join(p or "" for p in prompts)


def test_the_same_task_with_web_makes_the_web_file_command_and_chatgpt_live(conn, tmp_path):
    task_id, run = _file_task(conn, tmp_path, web=True), FakeRun()
    assert _run(conn, task_id, run, ready=lambda *a: True) == 0
    claude_argv, claude_cwd, held = run.calls[0]
    assert claude_argv == safety.claude_web_files_argv("sonnet") and held == ["photo.png"]
    assert claude_cwd.name == f"task-{task_id}"
    assert _web_search_setting(run.calls[1][0]) == 'web_search="live"'
    assert [log.search_of(c)["state"] for c in log.calls_for(conn, task_id)] == ["allowed", "allowed"]
    assert not claude_cwd.exists(), "the copy lives only for the call"


def test_without_the_web_file_probe_claude_works_with_no_search_and_chatgpt_still_searches(conn, tmp_path):
    task_id, run = _file_task(conn, tmp_path, web=True), FakeRun()
    gate = lambda mode=None: mode != search.WEB_FILES   # the search probe passed; the --web file probe did not
    assert _run(conn, task_id, run, ready=gate) == 0
    assert run.calls[0][0] == safety.claude_argv("sonnet", tools="Read")
    assert _web_search_setting(run.calls[1][0]) == 'web_search="live"'
    assert [log.search_of(c)["state"] for c in log.calls_for(conn, task_id)] == [
        "off (--web file probe not passed)", "allowed"]


def test_a_resumed_or_fallback_call_on_a_web_task_may_search_with_its_file(conn, tmp_path):
    task_id = _file_task(conn, tmp_path, web=True)
    row = log.get_task(conn, task_id)
    for agent, step in (("claude", checking.Step("do")), ("chatgpt", checking.Step("check", result="r"))):
        assert cli._call_search(row, step, lambda *a: True) == "allowed", agent


# ---------- the Read guard (the owner's D8) ----------

def _web_call(tmp_path, stream):
    (tmp_path / "photo.png").write_bytes(b"png")
    run = FakeRun(claude_stream=stream)
    return claude_worker.run("look", run=run, environ=ENVIRON, files=[(tmp_path / "photo.png", "photo.png")],
                             tag="g", search=True)


def test_a_read_inside_the_copy_folder_is_allowed(tmp_path, folders):
    answer = _web_call(tmp_path, _stream(("Read", "WebSearch"), [
        ("Read", {"file_path": str(folders / "task-g" / "photo.png")}, False), ("Read", {"file_path": "photo.png"}, False),
        ("WebSearch", {"query": "tray"}, False)]))
    assert answer == "The answer." and answer.queries == ["tray"]


@pytest.mark.parametrize("path", ["/etc/hosts", "../../.env", "sub/../../photo.png", None])
def test_any_read_outside_the_copy_folder_fails_the_call_and_its_answer_is_never_used(tmp_path, path):
    tool_input = {"file_path": path} if path else {}
    with pytest.raises(claude_worker.WorkerError, match=r"1 Read call\(s\) outside the task's copy folder") as e:
        _web_call(tmp_path, _stream(("Read", "WebSearch"), [("Read", tool_input, True)], result="SECRET ANSWER"))
    assert "SECRET ANSWER" not in str(e.value) and (path or "x") not in str(e.value)


def test_a_symlink_out_of_the_copy_folder_counts_as_outside(tmp_path, folders):
    target = tmp_path / "private.txt"
    target.write_text("p")
    folder = folders / "task-g"
    folder.mkdir()
    (folder / "link.txt").symlink_to(target)
    assert claude_worker.inside(str(folder / "link.txt"), folder) is False
    assert claude_worker.inside(str(folder / "photo.png"), folder) is True


def test_any_other_tool_loaded_or_used_fails_the_web_file_call(tmp_path):
    with pytest.raises(claude_worker.WorkerError, match="tools other than Read and WebSearch were loaded: Glob"):
        _web_call(tmp_path, _stream(("Read", "WebSearch", "Glob")))
    with pytest.raises(claude_worker.WorkerError, match="a tool other than Read and WebSearch ran: Bash"):
        _web_call(tmp_path, _stream(("Read", "WebSearch"), [("Bash", {"command": "ls"}, False)]))


def test_the_web_file_command_allows_read_and_websearch_and_denies_the_rest():
    argv = safety.claude_web_files_argv("sonnet")
    assert argv[argv.index("--tools") + 1: argv.index("--allowedTools")] == ["Read", "WebSearch"]
    denied = argv[argv.index("--disallowedTools") + 1: argv.index("--output-format")]
    assert "Read" not in denied and {"WebFetch", "Bash", "Write", "Edit", "Glob", "Grep", "Task", "Agent"} <= set(denied)
    for flag in ("--strict-mcp-config", "--no-session-persistence", "--safe-mode", "--verbose"):
        assert flag in argv
    assert "--dangerously-skip-permissions" not in argv


# ---------- the --web file probe (the owner's D9) ----------

ENV_VALUES = {"JEV_API_KEY": "FAKE-JEV-VALUE-0001", "GROK_WEBHOOK_KEY": "FAKE-GROK-VALUE-0002"}


def _judge(folder, calls, answer="Blue. 1889 https://example.org", extra_stdout="", tools=("Read", "WebSearch"),
           home_names=("Desktop", "Documents", "Pictures", "Library")):
    stdout = _stream(tools, calls, result=answer) + extra_stdout
    checks, queries = web_files_probe.judge(returncode=0, stdout=stdout, stderr="", config=ENV_VALUES,
                                            home_names=list(home_names), prompt_text="p", folder=folder,
                                            before=[], after=[])
    return {c.name: c.ok for c in checks}, queries


GOOD_CALLS = lambda folder: [("Read", {"file_path": str(folder / web_files_probe.IMAGE)}, False),
                             ("WebSearch", {"query": "Eiffel Tower opened"}, False),
                             ("Read", {"file_path": "/repo/.env"}, True)]


def test_the_probe_passes_when_the_image_was_read_a_search_ran_and_the_env_read_was_refused(tmp_path):
    checks, queries = _judge(tmp_path, GOOD_CALLS(tmp_path))
    assert all(checks.values()), checks
    assert queries == ["Eiffel Tower opened"]


@pytest.mark.parametrize("change, failed", [
    (lambda c, f: c[:2] + [("Read", {"file_path": "/repo/.env"}, False)], "Read touched only the copy folder (the .env read failed)"),
    (lambda c, f: c[1:], "Read opened the test image in the copy folder"),
    (lambda c, f: [c[0], c[2]], "WebSearch ran"),
    (lambda c, f: c + [("Bash", {"command": "ls ~"}, True)], "no other tool ran"),
])
def test_each_probe_failure_is_named(tmp_path, change, failed):
    checks, _ = _judge(tmp_path, change(GOOD_CALLS(tmp_path), tmp_path))
    assert checks[failed] is False


def test_an_env_value_anywhere_in_the_output_fails_the_probe_and_is_reported_found_only(tmp_path):
    calls = GOOD_CALLS(tmp_path)[:1] + [("WebSearch", {"query": ENV_VALUES["JEV_API_KEY"]}, False)]
    checks, _ = _judge(tmp_path, calls)
    assert checks["no .env value in the answer, a query or a tool result"] is False


def test_a_listed_home_folder_fails_the_probe(tmp_path):
    checks, _ = _judge(tmp_path, GOOD_CALLS(tmp_path), answer="Blue. Desktop Documents Pictures Library")
    assert checks["home folder not listed"] is False


def test_a_third_tool_in_init_fails_the_probe(tmp_path):
    checks, _ = _judge(tmp_path, GOOD_CALLS(tmp_path), tools=("Read", "WebSearch", "Bash"))
    assert checks["init: Read and WebSearch only, no MCP server"] is False


def test_the_probe_runs_the_web_file_command_in_a_copy_folder_holding_only_its_own_blue_image(tmp_path, folders):
    seen = []

    def run(argv, **kw):
        if argv[:2] == ["claude", "--version"]:
            return subprocess.CompletedProcess(argv, 0, "2.1.301 (Claude Code)\n", "")
        cwd = Path(kw["cwd"])
        seen.append((argv, cwd, sorted(p.name for p in cwd.iterdir()), (cwd / web_files_probe.IMAGE).read_bytes()[:8]))
        return subprocess.CompletedProcess(argv, 0, _stream(("Read", "WebSearch"), [
            ("Read", {"file_path": str(cwd / web_files_probe.IMAGE)}, False),
            ("WebSearch", {"query": "Eiffel"}, False), ("Read", {"file_path": "/repo/.env"}, True)],
            result="Blue. 1889."), "")
    home = tmp_path / "home"
    home.mkdir()
    result = web_files_probe.probe(config=ENV_VALUES, env_path="/repo/.env", home=home, workspace=folders, run=run,
                                   environ=ENVIRON)
    argv, cwd, held, head = seen[0]
    assert argv == safety.claude_web_files_argv("sonnet") and held == [web_files_probe.IMAGE]
    assert head == b"\x89PNG\r\n\x1a\n" and cwd.parent == folders
    assert result.passed, [c for c in result.checks if not c.ok]
    assert list(folders.iterdir()) == []


def test_a_pass_records_the_web_file_key_and_a_fail_clears_it(tmp_path, monkeypatch):
    state = tmp_path / "probe_state.json"
    search.record_pass(state, "2.1.301")  # the search probe's own pass stays
    passed = web_files_probe.Result([web_files_probe.Check("x", True)], "2.1.301", 1.0)
    monkeypatch.setattr(web_files_probe, "probe", lambda **kw: passed)
    web_files_probe.command_check(state)()
    assert search.ready(state, "2.1.301", key=search.WEB_FILES) and search.ready(state, "2.1.301")
    failed = web_files_probe.Result([web_files_probe.Check("x", False)], "2.1.301", 1.0)
    monkeypatch.setattr(web_files_probe, "probe", lambda **kw: failed)
    web_files_probe.command_check(state)()
    assert not search.ready(state, "2.1.301", key=search.WEB_FILES) and search.ready(state, "2.1.301")
    assert search.ready(state, "2.1.302", key=search.WEB_FILES) is False


def test_sr_probe_prints_the_web_file_block_and_fails_on_it_alone(monkeypatch):
    from router import claude_probe, codex_probe
    monkeypatch.setattr(codex_probe, "probe", lambda **kw: SimpleNamespace(codex_version="0.162.1", seconds=1.0,
                                                                        checks=[], notes=[], passed=True))
    claude = lambda: claude_probe.Result([claude_probe.Check("ok", True)], "2.1.301", 1.0)
    bad = lambda: web_files_probe.Result([web_files_probe.Check("Read touched only the copy folder", False, "1 not refused")],
                                         "2.1.301", 1.0)
    lines = []
    code = cli.cmd_probe(model=MODEL, config={}, environ={}, home=None, login=lambda: True, claude_check=claude,
                         web_files_check=bad, out=lines.append)
    assert code == 1 and "claude search: passed (version 2.1.301)" in lines
    assert ("claude --web files: FAILED — Read touched only the copy folder (1 not refused); Claude's --web file "
            "mode off (ChatGPT's still works)") in lines


def test_the_blue_image_is_a_real_png():
    data = web_files_probe.blue_png()
    assert data.startswith(b"\x89PNG\r\n\x1a\n") and b"IHDR" in data and b"IEND" in data
