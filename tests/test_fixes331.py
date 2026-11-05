"""Build brief 33.1, F (decision 23): four fixes from brief 33's and brief 32's live checks, built first.
(a) The tests line: every file-mode build and fix prompt says whether the project has a test command and, when it has,
that the router runs it after the call and the checker sees the results, so the agent never asks for that run.
(b) `--from`'s refusal names why from the source's outcome, never its status (brief 33's D printed "(it is done)" for a task
that failed its check).
(c) A real Claude call with search on reads a refused tool as not run, with the probes' own function (brief 32's D8).
(d) `sr probe --json` carries `probe` (brief 32's D5): main hands the command its receipt.
Real git in temp folders where a copy is made; fake agents; every value here is fake."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from router import __main__ as cli
from router import claude_worker, filecalls, fromblock, log, projects, safety, testrun
from tests.test_claude_probe_refused import _stream
from tests.test_filemode_flow import BUILD, CopyWorker, conn, project, route, runner  # noqa: F401 (fixtures)
from tests.test_handoff_contract import HANDOFF
from tests.test_json_actions import World
from tests.test_loop import Scripted
from tests.test_memory_block import _done
from tests.test_relay import Chat

TESTS_LINE = ("After your reply the router runs the project's tests (`python3 -m unittest`), and the checker sees the "
              "results, so never ask for that run, in `### Next` or anywhere else.")


# ---------- (a) the tests line ----------

def test_a_the_build_prompt_says_the_tests_run_and_the_checker_sees_them(project, conn, runner):
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    worker = CopyWorker(BUILD)
    route(conn, worker=worker)
    prompt = worker.calls[0]["prompt"]
    assert TESTS_LINE in prompt and prompt.endswith(TESTS_LINE)


def test_a_the_fix_prompt_says_it_too(project, conn, runner):
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    runner.results = [testrun.Result(1, "failed", "FAILED (failures=1)", "FAILED (failures=1)"),
                      testrun.Result(0, "passed", "OK", "OK")]
    worker = CopyWorker(BUILD, ("Fixed the test.\n\n" + HANDOFF, {"test_calc.py": "import unittest  # fixed\n"}))
    route(conn, worker=worker, chatgpt=Chat("FIX\n1. the test fails", "PASS"))
    assert worker.calls[1]["prompt"].endswith(TESTS_LINE)


def test_a_without_a_test_command_the_prompt_says_none_run(project, conn, runner):
    worker = CopyWorker(BUILD)
    route(conn, worker=worker)
    prompt = worker.calls[0]["prompt"]
    assert prompt.endswith("The project has no test command, so no tests run.")
    assert "the checker sees the results" not in prompt


def test_a_off_file_mode_there_is_no_tests_line(project, conn, runner, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    projects.remove("garden")
    projects.add("garden", str(plain))
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    worker = Scripted("Two lines.\n\n" + HANDOFF)
    route(conn, worker=worker)
    prompt = worker.prompts[0]
    assert "router runs the project's tests" not in prompt and "no test command" not in prompt


# ---------- (b) --from's refusal, from the outcome ----------

def _word(row):
    return row["status"]


@pytest.fixture
def mem():
    c = log.init_db(":memory:")
    yield c
    c.close()


@pytest.mark.parametrize("make, words", [
    (lambda c: _done(c, "sr-20261029-100000-aa01", "Plan the beds.", "Beds.", check_state="failed"),
     "it failed its check"),
    (lambda c: _blocked(c, "sr-20261029-100000-aa02"), "it was blocked"),
    (lambda c: _ended(c, "sr-20261029-100000-aa03", "failed"), "it stopped"),
    (lambda c: _ended(c, "sr-20261029-100000-aa04", "cancelled"), "it was cancelled"),
])
def test_b_the_refusal_names_the_sources_outcome(mem, make, words):
    row = make(mem)
    found, why = fromblock.refusal(mem, str(row["n"]), _word)
    assert found is None
    assert why == f"#{row['n']} wasn't delivered, so there is no result to build from: {words}"
    assert "it is done" not in why


def _blocked(conn, task_id):
    row = _done(conn, task_id, "Plan the beds.", "Beds.")
    conn.execute("UPDATE tasks SET status = 'failed', check_state = 'blocked', reason_code = 'blocked' WHERE task_id = ?",
                 (task_id,))
    conn.commit()
    return log.get_task(conn, task_id)


def _ended(conn, task_id, status):
    log.add_task(conn, task_id, "Plan the beds.", "cli", {"status": "ok", "label": "writing", "confidence": 0.9})
    conn.execute("UPDATE tasks SET status = ? WHERE task_id = ?", (status, task_id))
    conn.commit()
    return log.get_task(conn, task_id)


def test_b_an_open_source_says_it_is_still_open(mem):
    log.add_task(mem, "sr-20261029-100000-aa05", "Plan the beds.", "cli", {"status": "ok", "label": "writing",
                                                                          "confidence": 0.9})
    row = log.get_task(mem, "sr-20261029-100000-aa05")
    assert fromblock.refusal(mem, str(row["n"]), _word)[1] == (
        f"#{row['n']} wasn't delivered, so there is no result to build from: it is still open (queued)")


def test_b_a_change_waiting_to_land_says_so(mem):
    row = _done(mem, "sr-20261029-100000-aa06", "Plan the beds.", "Beds.")
    log.set_project_files(mem, row["task_id"], {"state": "waiting"})
    assert fromblock.refusal(mem, str(row["n"]), _word)[1].endswith(": its change waits to land")


# ---------- (c) a refused tool never ran, on a real call ----------

ANSWER = "Two lines with a source (https://example.com/a)."
SEARCH = ("WebSearch", {"query": "tray sizes"}, False)


def _proc(stdout):
    return subprocess.CompletedProcess([], 0, stdout, "")


def test_c_a_search_call_where_claude_asked_for_a_tool_and_was_refused_passes():
    stdout = _stream([SEARCH, ("Bash", {"command": "ls"}, True), ("Read", {"file_path": "/x/.env"}, True)],
                     result=ANSWER)
    answer = claude_worker._search_answer(_proc(stdout))
    assert str(answer) == ANSWER and answer.queries == ["tray sizes"]


def test_c_a_search_call_where_a_tool_it_does_not_allow_ran_fails():
    stdout = _stream([SEARCH, ("Bash", {"command": "ls"}, False)], result=ANSWER)
    with pytest.raises(claude_worker.WorkerError, match="a tool other than WebSearch ran: Bash"):
        claude_worker._search_answer(_proc(stdout))


def test_c_a_tool_call_with_no_result_counts_as_ran():
    stdout = _stream([SEARCH, ("Write", {"file_path": "x.txt"}, None)], result=ANSWER)
    with pytest.raises(claude_worker.WorkerError, match="a tool other than WebSearch ran: Write"):
        claude_worker._search_answer(_proc(stdout))


def test_c_a_web_file_call_reads_a_refused_read_outside_as_not_run(tmp_path):
    folder = tmp_path / "copy"
    folder.mkdir()
    inside = ("Read", {"file_path": str(folder / "photo.png")}, False)
    refused = ("Read", {"file_path": "/elsewhere/.env"}, True)
    stdout = _stream([inside, refused, SEARCH], tools=("Read", "WebSearch"), result=ANSWER)
    answer = claude_worker._search_answer(_proc(stdout), allowed=claude_worker.WEB_FILE_TOOLS, folder=folder)
    assert str(answer) == ANSWER


def test_c_a_web_file_call_fails_on_a_read_outside_that_ran(tmp_path):
    folder = tmp_path / "copy"
    folder.mkdir()
    ran = ("Read", {"file_path": "/elsewhere/notes.txt"}, False)
    stdout = _stream([ran, SEARCH], tools=("Read", "WebSearch"), result=ANSWER)
    with pytest.raises(claude_worker.WorkerError, match="1 Read call\\(s\\) outside the task's copy folder"):
        claude_worker._search_answer(_proc(stdout), allowed=claude_worker.WEB_FILE_TOOLS, folder=folder)


def test_c_both_readers_use_the_probes_function(monkeypatch):
    seen = []
    real = claude_worker.ran_and_refused

    def spy(calls, allowed):
        seen.append(tuple(allowed))
        return real(calls, allowed)
    monkeypatch.setattr(claude_worker, "ran_and_refused", spy)
    claude_worker._search_answer(_proc(_stream([SEARCH], result=ANSWER)))
    copy = SimpleNamespace(folder="/tmp/none", write=False, search=False)
    claude_worker._files_answer(_proc(_stream([], tools=safety.CLAUDE_READ_TOOLS, result=ANSWER)), copy)
    assert seen == [claude_worker.SEARCH_TOOLS, tuple(safety.CLAUDE_READ_TOOLS)]


# ---------- (d) sr probe --json carries probe ----------

class _Check(SimpleNamespace):
    pass


def _result(passed, version="2.1.312", **extra):
    checks = [_Check(name="ran to the end", ok=True, detail="exit 0"),
              _Check(name="no other tool ran", ok=passed, detail="" if passed else "ran: Bash")]
    return SimpleNamespace(passed=passed, checks=checks, claude_version=version, seconds=1.0, queries=[],
                           first_failure=None if passed else checks[1], **extra)


@pytest.fixture
def probing(monkeypatch, tmp_path, capsys):
    world = World(monkeypatch, tmp_path, capsys)
    codex = SimpleNamespace(codex_version="0.162.1", seconds=1.0, checks=[], notes=[], passed=True)
    monkeypatch.setattr(cli.codex_probe, "probe", lambda **kw: codex)
    monkeypatch.setattr(cli.probes, "record_codex", lambda path, result: None)
    monkeypatch.setattr(cli.probes, "record_files", lambda path, result: None)
    monkeypatch.setattr(cli.web_files_probe, "command_check", lambda *a, **k: (lambda: _result(True)))
    monkeypatch.setattr(cli.cursor_probe, "command_check", lambda *a, **k: (lambda: SimpleNamespace(
        standing="2026.10.22-27dcf5f", skipped=None)))
    monkeypatch.setattr(cli.files_probe, "probe", lambda **kw: _result(True, calls=1, found=lambda: {}))
    return world


def _probe_json(world):
    code, out, err = world.run("probe", "--json")
    stream = out if code in (0, 3, 4, 5) else err
    lines = stream.splitlines()
    assert len(lines) == 1, stream
    found = json.loads(lines[0])
    assert list(found)[:8] == ["task_id", "n", "status", "waiting_on", "outcome", "reason_code", "exit", "message"]
    assert list(found)[8:] == ["probe"]
    return code, found


def test_d_sr_probe_json_carries_probe_on_a_pass(probing, monkeypatch):
    monkeypatch.setattr(cli.claude_probe, "command_check", lambda *a, **k: (lambda: _result(True)))
    code, found = _probe_json(probing)
    assert code == 0
    assert set(found["probe"]) == {"chatgpt", "claude_search", "claude_web_files", "claude_files", "cursor"}
    assert found["probe"]["claude_search"]["passed"] is True and "record" not in found["probe"]["claude_search"]


def test_d_sr_probe_json_carries_probe_and_its_record_on_a_failure(probing, monkeypatch):
    monkeypatch.setattr(cli.claude_probe, "command_check", lambda *a, **k: (lambda: _result(
        False, tools={"ran": ["Bash"], "refused": []})))
    code, found = _probe_json(probing)
    assert code == 1
    shown = found["probe"]["claude_search"]
    assert shown["passed"] is False and shown["tools"] == {"ran": ["Bash"], "refused": []}
    assert shown["record"] == {"kind": "ran_failed", "reason": "no other tool ran: ran: Bash"}
