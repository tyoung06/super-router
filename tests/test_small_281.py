"""Brief 29.1 (decision 5): brief 28's small live-check issues. Issue 2: a file-mode call's row records its working folder
(`cwd: copy`) and the tool list Claude's init event reported. Issue 3: before a call the router runs only the Claude check that
call needs, never the `--web` file check for a call without `--web`. Issue 4: no test writes the repo's own `workspace/` (its
`.git` made a fresh clone fail three tests). Issue 8: a call row records when it was sent and when it ended. Issue 15: a
project task that comes back before any agent call writes no handoff entry. Issue 18: every test run removes its own
throwaway folder, whatever goes wrong. Fakes only; every value is fake."""
import os
from pathlib import Path

import pytest

from router import __main__ as cli
from router import claude_worker, log, probes, safety, search, testrun
from tests.test_auto_probe import V1, ClaudeProbes, _gate, state_path  # noqa: F401 (the fixture)
from tests.test_filemode_flow import BUILD, Chat, CopyWorker, conn, project, route, runner  # noqa: F401


# ---------- issue 2: the working folder and the tools on a file-mode call's row ----------

def test_the_file_mode_answer_carries_the_init_events_tools():
    stream = ('{"type": "system", "subtype": "init", "tools": ["Read", "Edit", "Write", "Glob", "Grep"], "mcp_servers": []}\n'
              '{"type": "result", "result": "Done.", "is_error": false}\n')
    proc = type("Proc", (), {"stdout": stream, "stderr": "", "returncode": 0})()
    spec = type("Spec", (), {"write": True, "search": False, "folder": "/tmp/copy"})()
    answer = claude_worker._files_answer(proc, spec)
    assert str(answer) == "Done." and answer.tools == ["Read", "Edit", "Write", "Glob", "Grep"]


class ToolsWorker(CopyWorker):
    def __call__(self, prompt, copy=None, search=False, **kw):
        text = super().__call__(prompt, copy=copy, search=search, **kw)
        return claude_worker.SearchAnswer(text, (), tools=["Read", "Edit", "Write", "Glob", "Grep"])


def test_a_file_mode_calls_row_says_it_ran_in_the_copy_with_its_tools(project, conn, runner):
    code, out, row = route(conn, worker=ToolsWorker(BUILD), chatgpt=Chat("PASS"))
    do = next(c for c in log.calls_for(conn, row["task_id"]) if c["kind"] == "do")
    record = log.context_of(do)
    assert record["cwd"] == "copy" and record["tools"] == ["Read", "Edit", "Write", "Glob", "Grep"]
    check = next(c for c in log.calls_for(conn, row["task_id"]) if c["kind"] == "check")
    assert "cwd" not in (log.context_of(check) or {})  # ChatGPT never runs in the copy
    shown = cli.jsonview.call_view(do, 1)
    assert (shown["cwd"], shown["tools"]) == ("copy", ["Read", "Edit", "Write", "Glob", "Grep"])


# ---------- issue 3: only the check a call needs ----------

def test_a_call_without_web_runs_only_the_search_probe(tmp_path, state_path):
    fakes, out = ClaudeProbes(state_path, V1), []
    assert _gate(tmp_path, V1, fakes, out)() is True
    assert fakes.ran == [search.SEARCH_KEY], "never the --web file check for a call without --web"
    assert search.passed_version(state_path, search.WEB_FILES) is None


def test_a_web_file_call_runs_its_own_probe_when_it_needs_it(tmp_path, state_path):
    fakes, out = ClaudeProbes(state_path, V1), []
    gate = _gate(tmp_path, V1, fakes, out)
    assert gate() is True and gate(search.WEB_FILES) is True
    assert fakes.ran == [search.SEARCH_KEY, search.WEB_FILES]


# ---------- issue 4: the repo's workspace/ is never a test's ----------

def test_a_command_that_runs_agents_never_touches_the_repos_workspace():
    real = safety.REPO_ROOT / "workspace"
    before = (real / ".git").exists()
    assert cli.main(["split", "--edit", "5", "--piece", "1", "--go", "5"], platform="darwin") == 2
    assert (real / ".git").exists() == before
    safety.prepare_workspace()  # the suite's own, already a git folder: nothing to make
    assert (real / ".git").exists() == before


# ---------- issue 8: sent_at when sent, finished_at when it ends ----------

def test_a_local_calls_row_records_when_it_was_sent_and_when_it_ended(project, conn, runner, monkeypatch):
    from datetime import datetime, timedelta, timezone
    ticks = iter(range(10_000))  # every stamp the log takes is one second after the one before
    real_iso = log._iso
    start = datetime(2026, 10, 27, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(log, "_iso", lambda now=None: real_iso(start + timedelta(seconds=next(ticks))) if now is None
                        else real_iso(now))
    code, out, row = route(conn, worker=CopyWorker(BUILD), chatgpt=Chat("PASS"))
    do, check = [c for c in log.calls_for(conn, row["task_id"]) if c["kind"] in ("do", "check")]
    assert do["sent_at"] < do["finished_at"] and check["sent_at"] < check["finished_at"]
    assert do["finished_at"] <= check["sent_at"]


# ---------- issue 15: no entry for a project task that came back before any call ----------

def test_a_project_task_that_comes_back_before_any_call_writes_no_entry(project, conn, runner):
    before = (project / "HANDOFF.md").read_text()
    code, out, row = route(conn, worker=CopyWorker(BUILD), jev={"status": "error", "error": "Timeout", "tokens": 0})
    row = log.get_task(conn, row["task_id"])
    assert row["status"] == "returned" and not log.calls_for(conn, row["task_id"])
    assert (project / "HANDOFF.md").read_text() == before and log.handoff_of(row) == []
    assert "HANDOFF.md:" not in out


# ---------- issue 18: every run removes its own throwaway ----------

def test_a_throwaway_whose_copy_fails_is_removed(tmp_path):
    root = tmp_path / "temp"
    root.mkdir()
    with pytest.raises(OSError):
        testrun.make_throwaway(tmp_path / "no-such-copy", temp_root=root)
    assert list(root.iterdir()) == []


def test_a_throwaway_the_tests_left_unwritable_is_removed(tmp_path):
    root = tmp_path / "temp"
    root.mkdir()
    copy = tmp_path / "copy"
    copy.mkdir()
    (copy / "a.txt").write_text("a\n")
    made = testrun.make_throwaway(copy, temp_root=root)
    locked = made / "tmp" / "locked"
    locked.mkdir()
    (locked / "inside.txt").write_text("x\n")
    os.chmod(locked, 0o500)  # what a test can leave behind: a folder nothing can be removed from
    testrun.remove_throwaway(made)
    assert not made.exists() and list(root.iterdir()) == []
