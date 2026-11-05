"""Brief 33.2 fix 1 (the owner's decision 1, D4 option A): `sr route --project <name> --no-files` reads, answers in text.
The router makes the project's copy as file mode does; Claude's do call (and a fix round, and a re-ask) runs in it read
only (Read, Glob and Grep; WebSearch where the call has it; no Edit, Write or command); no tests run; the change is always
empty and the copy is removed at delivery, so nothing waits to land. Without file mode, or with a doer that isn't Claude,
the task runs handoff only, as before, its why naming the reason. Real git in temp folders, fake agents; every value here
is fake."""
from pathlib import Path

from router import __main__ as cli
from router import checking, copies, filecalls, log, projects, safety, spec
from tests.helpers import as_recheck, fake_label
from tests.test_filemode_flow import CODE, conn, project, runner  # noqa: F401 (fixtures)
from tests.test_handoff_contract import HANDOFF
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_relay import CONFIG, ROSTER, Chat
from tests.test_resume_run import WRITING

TASK = "Write SPEC.md for this project"


class Reader:
    """A fake Claude that reads calc.py in its working folder and quotes it; it writes nothing."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, prompt, copy=None, search=False, **kw):
        quoted = (Path(copy.folder) / "calc.py").read_text() if copy else "(no folder)"
        self.calls.append({"prompt": prompt, "copy": copy, "search": search})
        reply = self.replies.pop(0) if self.replies else "calc.py reads:\n{quoted}\n\n" + HANDOFF
        return as_recheck(prompt, reply.format(quoted=quoted))


def _route(conn, worker, *, chatgpt=None, jev=CODE, files_ready=lambda: (True, None), project="garden"):
    lines, clock, hook = [], Clock(), Webhook()
    code = cli.cmd_route(TASK, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=fake_label(jev),
                         post=hook.post, worker=worker, chatgpt=chatgpt or Chat("PASS"), codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True,
                         out=lines.append, project=project, files_ready=files_ready, no_files=True)
    return code, "\n".join(lines), log.get_task(conn, log.recent_tasks(conn)[0]["task_id"])


def test_the_do_call_reads_a_read_only_copy_with_read_glob_and_grep_and_quotes_the_file(project, conn, runner):
    worker = Reader()
    code, said, row = _route(conn, worker)
    assert code == 0, said
    call = worker.calls[0]
    assert call["copy"] is not None and call["copy"].write is False  # the copy, write off
    argv = safety.claude_files_argv("sonnet", write=call["copy"].write, search=call["copy"].search)
    tools = argv[argv.index("--tools") + 1:argv.index("--disallowedTools")]
    assert [t for t in tools if t not in ("WebSearch", "--allowedTools")] == ["Read", "Glob", "Grep"]
    assert "--permission-mode" not in argv  # no acceptEdits: nothing can be written
    assert filecalls.READ_PARAGRAPH.format(name="garden") in call["prompt"]
    assert "Make the change by editing files there" not in call["prompt"]
    assert spec.BUILD_CLAUSE not in call["prompt"]
    assert "return a - b" in row["result"]  # the doer read calc.py from the copy and quoted it


def test_delivered_nothing_changed_no_tests_the_copy_gone_and_nothing_waits(project, conn, runner):
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    code, said, row = _route(conn, Reader())
    assert code == 0, said
    found = log.project_files_of(row)
    assert found["mode"] == "on" and found["read_only"] is True and found["why"] == filecalls.READ_ONLY_WHY
    assert found["changed"] == [] and found["state"] == "none" and found["copy"] is False
    assert (found["tests"] or {}).get("outcome") == "not_run"
    assert runner.runs == []  # the project has a test command, and still none ran
    assert not copies.exists(row["task_id"])
    assert not filecalls.waiting(row)
    assert "Files: no file changed; nothing to land." in said
    assert filecalls.READ_ONLY_WHY == "read only, answers in text"
    assert "### #" in (project / "HANDOFF.md").read_text()  # delivered as text: the entry is written at once


def test_the_start_line_says_read_only(project, conn, runner):
    code, said, row = _route(conn, Reader())
    assert "Files: a read-only copy of garden at" in said and "answers in text" in said


def test_the_checker_is_told_the_doer_read_a_read_only_copy_and_judges_text(project, conn, runner):
    chat = Chat("PASS")
    code, said, row = _route(conn, Reader(), chatgpt=chat)
    check = chat.prompts[0]
    assert "and a read-only copy of the project's files" in check
    assert filecalls.READ_JUDGE_LINE in check
    assert filecalls.NO_CHANGE_JUDGE_LINE not in check and "===== change:" not in check


def test_a_fix_round_is_read_only_too(project, conn, runner):
    worker = Reader("A first draft.\n\n" + HANDOFF, "calc.py reads:\n{quoted}\n\n" + HANDOFF)
    chat = Chat("FIX\n1. [must] say what calc.py does", "PASS")
    code, said, row = _route(conn, worker, chatgpt=chat)
    assert code == 0, said
    fix = worker.calls[1]
    assert fix["copy"] is not None and fix["copy"].write is False
    assert filecalls.READ_PARAGRAPH.format(name="garden") in fix["prompt"]
    assert "===== tests =====" not in fix["prompt"] and "Make the change by editing files there" not in fix["prompt"]
    assert log.project_files_of(log.get_task(conn, row["task_id"]))["changed"] == []
    assert log.get_task(conn, row["task_id"])["check_state"] == "fixed"


def test_without_git_it_runs_handoff_only_and_says_why(project, conn, runner, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    projects.remove("garden")
    projects.add("garden", str(plain))
    worker = Scripted("Two lines.\n\n" + HANDOFF, "PASS")
    code, said, row = _route(conn, worker)
    assert code == 0, said
    assert log.project_files_of(row) == {"mode": "off", "state": "none", "copy": False,
                                         "why": "text only, as asked; no read-only copy: no git yet: Turn on undo"}


def test_the_file_check_not_passed_runs_handoff_only(project, conn, runner):
    why = "Claude's file check hasn't passed on Claude Code 2.1.311"
    code, said, row = _route(conn, Scripted("Two lines.\n\n" + HANDOFF, "PASS"), files_ready=lambda: (False, why))
    found = log.project_files_of(row)
    assert found["mode"] == "off" and found["why"] == f"text only, as asked; no read-only copy: {why}"
    assert not copies.exists(row["task_id"])


def test_another_doers_label_still_reads_the_copy_with_claude(project, conn, runner):
    # brief 33.2 fix 1b (the owner's call on item (iii)): a --no-files task's doer is always Claude, so a label that would
    # pick ChatGPT no longer runs handoff only; filecalls.start keeps its "can't read" why for a caller that hands it one
    chat = Chat("PASS")
    code, said, row = _route(conn, Reader(), chatgpt=chat, jev={**WRITING, "label": "web_research"})
    assert code == 0, said
    found = log.project_files_of(row)
    assert row["agent"] == "claude" and found["mode"] == "on" and found["read_only"] is True
    assert not copies.exists(row["task_id"])
