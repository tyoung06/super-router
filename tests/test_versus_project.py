"""Brief 29.1 (decision 9; the owner's D21, option a): versus on a project. In file mode the router makes two copies at intake,
`<task_id>-a` and `<task_id>-b`, each with its own record in the task's `project_files`. The slots must be Claude and
ChatGPT (either order); Grok and Cursor are refused. Claude's slot builds in its copy with brief 28's build call; ChatGPT's
slot builds from a file view and the router writes its files (ChatGPT never runs in a copy). Each copy's tests run after
its build; each review gets the other candidate's change and tests. The pick keeps one copy, which waits to land; `none`
removes both. Handoff only: both candidates return a `## Handoff` section and the picked one's is the entry. Real git in
temp folders, fake agents; every value fake."""
from pathlib import Path

import pytest

from router import __main__ as cli
from router import copies, fileview, log, projects, relay, testrun
from tests.test_filemode_flow import FIXED_CALC, Chat, CopyWorker, conn, project, relay as run_relay, runner  # noqa: F401
from tests.test_collab import LOADED
from tests.test_landing import land

SECTION = "\n\n## Handoff\n### Produced\ncalc.py\n### Status\nadd works\n### Next\nship it"
CLAUDE_BUILD = "Fixed add() to return the sum." + SECTION
CHATGPT_BUILD = ("Made add() return a + b.\n\n=== file: calc.py ===\ndef add(a, b):\n    return a + b\n=== end file ===\n"
                 + SECTION)
REVIEW_OF_A = "## Verdict\npass\n\n## Notes\n- Strong: one line."
REVIEW_OF_B = "## Verdict\npass\n\n## Notes\n- Strong: clear."


def versus(conn, *, worker, chatgpt, slots=(), files_ready=lambda: (True, None)):
    return run_relay(conn, "versus", worker=worker, chatgpt=chatgpt, slots=slots, files_ready=files_ready)


def _pick(conn, row, choice):
    lines = []
    code = cli.cmd_pick([str(row["n"]), choice], conn=conn, loaded=LOADED, out=lines.append)
    return code, "\n".join(lines)


def _run(conn, chatgpt_build=CHATGPT_BUILD, claude_build=(CLAUDE_BUILD, {"calc.py": FIXED_CALC}), slots=()):
    worker = CopyWorker(claude_build, (REVIEW_OF_B, {}))
    chat = Chat(chatgpt_build, REVIEW_OF_A)
    code, out, row, hook = versus(conn, worker=worker, chatgpt=chat, slots=slots)
    return code, out, log.get_task(conn, row["task_id"]) if row else None, worker, chat


# ---------- intake ----------

def test_two_copies_are_made_at_intake_each_with_its_own_record(project, conn, runner):
    code, out, row, worker, chat = _run(conn)
    assert code == 0, out
    found = log.project_files_of(row)
    assert found["mode"] == "on" and found["versus"] is True
    for slot in ("a", "b"):
        assert copies.exists(f"{row['task_id']}-{slot}")
        assert found["candidates"][slot]["copy_id"] == f"{row['task_id']}-{slot}"
    assert not copies.exists(row["task_id"])


@pytest.mark.parametrize("slots, words", [
    ([("b", "grok")], "versus in file mode takes Claude and ChatGPT only (slot b holds Grok Bot)"),
    ([("a", "cursor")], "cursor"),
    ([("a", "chatgpt"), ("b", "chatgpt")], "both hold chatgpt"),
])
def test_the_slot_rule_refuses_every_other_agent_in_file_mode(project, conn, runner, slots, words):
    code, out, row, worker, chat = _run(conn, slots=slots)
    assert code == 2 and row is None and words in out


def test_either_order_of_claude_and_chatgpt_is_taken(project, conn, runner):
    worker = CopyWorker((CLAUDE_BUILD, {"calc.py": FIXED_CALC}), (REVIEW_OF_A, {}))  # Claude builds B, then reviews A
    chat = Chat(CHATGPT_BUILD, REVIEW_OF_B)
    code, out, row, hook = versus(conn, worker=worker, chatgpt=chat, slots=[("a", "chatgpt"), ("b", "claude")])
    assert code == 0, out
    task = log.get_task(conn, row["task_id"])
    assert task["status"] == "returned" and task["check_note"] == log.AWAITING_PICK


def test_a_file_view_past_the_limit_refuses_at_intake_with_both_numbers(project, conn, runner, monkeypatch):
    monkeypatch.setattr(fileview, "VIEW_LIMIT", 10)
    code, out, row, worker, chat = _run(conn)
    assert code == 2 and row is None and log.recent_tasks(conn) == []
    assert "the file view would show" in out and "at most 10" in out


def test_a_key_in_a_file_to_be_shown_refuses_at_intake_by_file_and_line(project, conn, runner, real_git):
    from tests.test_copies import git
    secret = "gh" + "p_" + "b" * 36  # built at run time
    (project / "notes.txt").write_text(f"one\ntoken {secret}\n")
    git(project, "add", "notes.txt")
    git(project, "commit", "-q", "-m", "notes")
    code, out, row, worker, chat = _run(conn)
    assert code == 2 and row is None and "notes.txt line 2 looks like it holds a key" in out and secret not in out


# ---------- the builds ----------

def test_claude_builds_in_copy_a_and_the_router_writes_chatgpts_files_into_copy_b(project, conn, runner):
    code, out, row, worker, chat = _run(conn)
    assert code == 0, out
    build_a, review_b = worker.calls
    assert build_a["copy"].write is True and Path(build_a["copy"].folder).name == f"{row['task_id']}-a"
    assert review_b["copy"].write is False and Path(review_b["copy"].folder).name == f"{row['task_id']}-b"
    chatgpt_build = chat.prompts[0]
    assert "===== FILE VIEW: 2 files =====" in chatgpt_build and "=== file: calc.py ===" in chatgpt_build
    assert "copy" not in chat.kwargs[0] and "files" not in chat.kwargs[0]  # ChatGPT ran in no folder
    assert (copies.folder_of(f"{row['task_id']}-b") / "calc.py").read_text() == FIXED_CALC
    assert (project / "calc.py").read_text() == "def add(a, b):\n    return a - b\n"  # the folder is untouched
    found = log.project_files_of(row)["candidates"]
    assert [c["path"] for c in found["a"]["changed"]] == ["calc.py"] == [c["path"] for c in found["b"]["changed"]]
    assert found["b"]["diff"] == f"tasks/{row['task_id']}/changes-b.diff"
    calls = log.calls_for(conn, row["task_id"])
    assert log.context_of(calls[1])["files"] == {"written": ["calc.py"]}


def test_tests_run_on_each_copy_after_its_build(project, conn, runner):
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    code, out, row, worker, chat = _run(conn)
    assert code == 0, out
    assert [Path(r["folder"]).name for r in runner.runs] == [f"{row['task_id']}-a", f"{row['task_id']}-b"]
    found = log.project_files_of(row)["candidates"]
    assert found["a"]["tests"]["outcome"] == "passed" and found["b"]["tests"]["outcome"] == "passed"


def test_each_review_gets_the_other_candidates_change_and_tests(project, conn, runner):
    code, out, row, worker, chat = _run(conn)
    review_a = chat.prompts[1]  # ChatGPT reviews Claude's candidate, from the text
    assert "===== change: 1 file =====\nchanged calc.py (+1 -1)" in review_a and "Fixed add() to return the sum." in review_a
    review_b = worker.calls[1]["prompt"]  # Claude reviews ChatGPT's, in copy b, read only
    assert "===== change: 1 file =====" in review_b and "Made add() return a + b." in review_b
    assert "=== file: calc.py ===" not in review_b  # the candidate is the reply without its file blocks


@pytest.mark.parametrize("reply, words", [
    ("Done.\n=== file: .env ===\nX=1\n=== end file ===" + SECTION, "never carries (.env)"),
    ("Done.\n=== file: ../x.py ===\nx\n=== end file ===" + SECTION, "leaves the project's folder"),
    ("Done.\n=== delete: gone.py ===" + SECTION, "the copy has no such file"),
])
def test_a_file_reply_that_misses_its_contract_gets_the_one_re_ask_naming_it(project, conn, runner, reply, words):
    worker = CopyWorker((CLAUDE_BUILD, {"calc.py": FIXED_CALC}), (REVIEW_OF_B, {}))
    chat = Chat(reply, CHATGPT_BUILD, REVIEW_OF_A)
    code, out, row, hook = versus(conn, worker=worker, chatgpt=chat)
    assert code == 0, out
    reask = chat.prompts[1]
    assert words in reask and "===== FILE VIEW:" in reask and "=== end file ===" in reask
    calls = log.calls_for(conn, row["task_id"])
    assert [c["kind"] for c in calls] == ["stage", "stage", "reask", "stage", "stage"]
    assert (copies.folder_of(f"{row['task_id']}-b") / "calc.py").read_text() == FIXED_CALC  # written from the re-ask


def test_a_file_reply_holding_a_key_fails_the_stage_and_writes_nothing(project, conn, runner):
    value = "Z" * 24
    from tests import test_filemode_flow
    reply = f"Done.\n=== file: calc.py ===\nKEY = '{value}'\n=== end file ===" + SECTION
    worker = CopyWorker((CLAUDE_BUILD, {"calc.py": FIXED_CALC}))
    chat = Chat(reply)
    lines, clock, hook = [], test_filemode_flow.Clock(), test_filemode_flow.RelayHook()
    code = cli.cmd_relay("versus", test_filemode_flow.TASK, conn=conn, config={**test_filemode_flow.CONFIG, "X": value},
                         roster=test_filemode_flow.ROSTER, loaded=test_filemode_flow.LOADED, environ={}, settings_paths=[],
                         post=hook.post, worker=worker, chatgpt=chat, codex_login=lambda: True, fetch=hook.fetch,
                         close=hook.close, sleep=clock.sleep, clock=clock, wait=True, slots=[], out=lines.append,
                         project="garden", files_ready=lambda: (True, None))
    row = log.recent_tasks(conn)[0]
    assert row["status"] == "failed" and value not in "\n".join(lines)
    stage = log.calls_for(conn, row["task_id"])[1]
    assert stage["status"] == "failed" and stage["reason_code"] == "copy_problem"
    assert not copies.exists(f"{row['task_id']}-a") and not copies.exists(f"{row['task_id']}-b"), "a stopped versus drops both"


# ---------- the pick ----------

def test_picking_b_keeps_its_copy_waiting_to_land_and_removes_a(project, conn, runner):
    code, out, row, worker, chat = _run(conn)
    code, said = _pick(conn, row, "b")
    assert code == 0, said
    task = log.get_task(conn, row["task_id"])
    found = log.project_files_of(task)
    assert found["state"] == "waiting" and found["copy_id"] == f"{row['task_id']}-b" and "candidates" not in found
    assert not copies.exists(f"{row['task_id']}-a") and copies.exists(f"{row['task_id']}-b")
    assert task["result"] == "Made add() return a + b." and "## Handoff" not in task["result"]
    code, said = land(conn, task)
    assert code == 0, said
    assert (project / "calc.py").read_text() == FIXED_CALC
    entry = projects.entries_of((project / "HANDOFF.md").read_text())[0]
    assert entry.splitlines()[0].endswith("· versus · chatgpt · landed") and "add works" in entry
    assert not copies.exists(f"{row['task_id']}-b")


def test_a_picked_candidate_lands_whatever_its_review_said(project, conn, runner):
    worker = CopyWorker((CLAUDE_BUILD, {"calc.py": FIXED_CALC}), (REVIEW_OF_B.replace("pass", "fail"), {}))
    chat = Chat(CHATGPT_BUILD, REVIEW_OF_A)
    code, out, row, hook = versus(conn, worker=worker, chatgpt=chat)
    code, said = _pick(conn, log.get_task(conn, row["task_id"]), "b")
    task = log.get_task(conn, row["task_id"])
    assert task["check_state"] == "failed" and land(conn, task)[0] == 0


def test_picking_none_removes_both_copies(project, conn, runner):
    code, out, row, worker, chat = _run(conn)
    code, said = _pick(conn, row, "none")
    assert code == 0
    assert not copies.exists(f"{row['task_id']}-a") and not copies.exists(f"{row['task_id']}-b")
    assert log.get_task(conn, row["task_id"])["status"] == "failed"


def test_versus_never_falls_back_or_resumes_on_a_project(project, conn, runner):
    code, out, row, worker, chat = _run(conn)
    shown = cli.jsonview.task_view(conn, row, loaded=LOADED)
    assert shown["fallback"]["ok"] is False and shown["resume"]["ok"] is False


# ---------- handoff only ----------

def test_handoff_only_versus_returns_both_sections_and_the_pick_writes_the_entry(project, conn, runner, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    projects.remove("garden")
    projects.add("garden", str(plain))
    worker = CopyWorker((CLAUDE_BUILD, {}), (REVIEW_OF_B, {}))
    chat = Chat("Use a + b." + SECTION, REVIEW_OF_A)
    code, out, row, hook = versus(conn, worker=worker, chatgpt=chat)
    assert code == 0, out
    assert "End your result with a section `## Handoff`" in worker.calls[0]["prompt"]
    assert "End your result with a section `## Handoff`" in chat.prompts[0] and "FILE VIEW" not in chat.prompts[0]
    task = log.get_task(conn, row["task_id"])
    assert log.project_files_of(task)["mode"] == "off"
    code, said = _pick(conn, task, "a")
    assert code == 0, said
    entry = projects.entries_of((plain / "HANDOFF.md").read_text())[0]
    assert entry.splitlines()[0].endswith("· versus · claude") and "add works" in entry


def test_a_missing_section_before_the_handoff_never_swallows_it():
    deliverable, missing = relay.split_missing("The answer.\n\n## Missing\n- a source\n" + SECTION)
    assert deliverable == "The answer." and missing == "- a source"
