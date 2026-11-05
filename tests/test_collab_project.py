"""Brief 29.1 (decision 8; rules 2.42, Relay, collab on a project): `--project` is taken on collab. On a project its stages
are the lead's plan (in file mode read only in the copy), the partner's amend (text), the lead's build (in file mode brief
28's build call in the copy) with the handoff contract and its re-ask, and then the partner checks it with the usual loop:
no edit stage. In file mode the lead must be Claude; Cursor never fills a slot on a project. Without a project collab is
unchanged. The shape is derived in code; config/presets.json stays as it is. Real git in temp folders, fake agents; every
value fake."""
from pathlib import Path

from router import __main__ as cli
from router import filecalls, log, presets, projects, relay, teams
from tests.test_collab import AMENDED, LOADED, PLAN
from tests.test_context import SECTION
from tests.test_filemode_flow import FIXED_CALC, Chat, CopyWorker, conn, project, relay as run_relay, runner  # noqa: F401
from tests.test_landing import land

BUILT = "## Deliverable\nFixed add() in calc.py.\n\n## Unfinished\nnone" + SECTION


def collab(conn, *, worker, chatgpt, slots=(), files_ready=lambda: (True, None)):
    return run_relay(conn, "collab", worker=worker, chatgpt=chatgpt, slots=slots, files_ready=files_ready)


def test_the_project_shape_is_plan_amend_build_then_the_partner_checks():
    base = LOADED.presets["collab"]
    shaped = presets.project_shape(base)
    assert [(s.n, s.role, s.agent) for s in shaped.stages] == [(1, "plan", "claude"), (2, "amend", "chatgpt"),
                                                              (3, "execute", "claude")]
    assert shaped.checker == "chatgpt" and shaped.check_stage is None and shaped.doer == "claude"
    assert [(s.name, s.stages, s.checker) for s in shaped.slots] == [("lead", (1, 3), False), ("partner", (2,), True)]
    assert presets.chain(shaped) == "Claude plan → ChatGPT amend → Claude build → ChatGPT check"
    assert teams.preset_calls(shaped) == (4, 6)  # decision 13: three stages and the check loop
    assert presets.project_shape(LOADED.presets["research-build"]) is LOADED.presets["research-build"]
    assert presets.takes_project(base)  # decision 8: collab takes a project (versus and vote: B2, B3)


def test_collab_on_a_project_plans_read_only_builds_in_the_copy_and_the_partner_checks(project, conn, runner):
    worker = CopyWorker((PLAN, {}), (BUILT, {"calc.py": FIXED_CALC}))
    chat = Chat(AMENDED, "PASS")
    code, out, row, hook = collab(conn, worker=worker, chatgpt=chat)
    assert code == 0, out
    plan_call, build_call = worker.calls
    assert plan_call["copy"].write is False and Path(plan_call["copy"].folder).name == row["task_id"]
    assert filecalls.PLAN_READ_LINE.format(name="garden") in plan_call["prompt"]
    assert build_call["copy"].write is True
    assert build_call["prompt"].endswith(filecalls.build_paragraph(log.get_task(conn, row["task_id"])))
    assert "End your result with a section `## Handoff`" in build_call["prompt"]
    assert relay.EXECUTE_SHAPE_PROJECT in build_call["prompt"]
    amend, check = chat.prompts
    assert "===== project handoff: garden =====" in amend and "===== PLAN =====" in amend
    assert "===== change: 1 file =====\nchanged calc.py (+1 -1)" in check
    calls = log.calls_for(conn, row["task_id"])
    assert [(c["kind"], c["stage"], c["role"], c["agent"]) for c in calls] == [
        ("stage", 1, "plan", "claude"), ("stage", 2, "amend", "chatgpt"), ("stage", 3, "execute", "claude"),
        ("check", None, None, "chatgpt")]  # no edit stage
    task = log.get_task(conn, row["task_id"])
    assert (task["agent"], task["checker"], task["check_state"]) == ("claude", "chatgpt", "passed")
    assert log.project_files_of(task)["state"] == "waiting"
    assert "## Handoff" not in (task["result"] or "")
    code, out = land(conn, task)
    assert code == 0, out
    assert projects.entries_of((project / "HANDOFF.md").read_text())[0].splitlines()[0].endswith("· collab · claude · landed")


def test_the_build_missing_its_handoff_section_gets_the_one_re_ask(project, conn, runner):
    no_section = "## Deliverable\nFixed add().\n\n## Unfinished\nnone"
    worker = CopyWorker((PLAN, {}), (no_section, {"calc.py": FIXED_CALC}), (BUILT, {}))
    code, out, row, hook = collab(conn, worker=worker, chatgpt=Chat(AMENDED, "PASS"))
    assert code == 0, out
    reask = worker.calls[2]
    assert "Handoff: section `## Handoff` is missing" in reask["prompt"] and relay.EXECUTE_SHAPE_PROJECT in reask["prompt"]
    assert [c["kind"] for c in log.calls_for(conn, row["task_id"])] == ["stage", "stage", "stage", "reask", "check"]


def test_a_failed_check_gets_the_leads_fix_round_in_the_copy(project, conn, runner):
    worker = CopyWorker((PLAN, {}), (BUILT, {"calc.py": FIXED_CALC}),
                        (BUILT.replace("Fixed add()", "Fixed add() and its test"), {"test_calc.py": "import unittest\n"}))
    code, out, row, hook = collab(conn, worker=worker, chatgpt=Chat(AMENDED, "FIX\n1. add a test", "PASS"))
    assert code == 0, out
    fix = worker.calls[2]
    assert fix["copy"].write is True
    task = log.get_task(conn, row["task_id"])
    assert task["check_state"] == "fixed" and [c["path"] for c in log.project_files_of(task)["changed"]] == [
        "calc.py", "test_calc.py"]


def test_a_lead_other_than_claude_on_a_git_project_is_refused(project, conn, runner):
    code, out, row, hook = collab(conn, worker=CopyWorker(), chatgpt=Chat(), slots=[("lead", "chatgpt"), ("partner", "claude")])
    assert code == 2 and row is None and "only Claude changes project files" in out


def test_cursor_never_fills_a_collab_slot(project, conn, runner):
    code, out, row, hook = collab(conn, worker=CopyWorker(), chatgpt=Chat(), slots=[("partner", "cursor")])
    assert code == 2 and row is None


def test_handoff_only_collab_on_a_project_without_git(project, conn, runner, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    projects.remove("garden")
    projects.add("garden", str(plain))
    worker = CopyWorker((PLAN, {}), (BUILT, {}))
    code, out, row, hook = collab(conn, worker=worker, chatgpt=Chat(AMENDED, "PASS"))
    assert code == 0, out
    assert all(c["copy"] is None for c in worker.calls)
    task = log.get_task(conn, row["task_id"])
    assert task["check_state"] == "passed" and log.project_files_of(task)["mode"] == "off"
    assert [c["kind"] for c in log.calls_for(conn, row["task_id"])] == ["stage", "stage", "stage", "check"]
    assert projects.entries_of((plain / "HANDOFF.md").read_text())[0].splitlines()[0].endswith("· collab · claude")


def test_collab_without_a_project_is_unchanged(conn):
    found, why = presets.for_task({"preset": "collab", "slots": None, "project": None}, LOADED)
    assert found is LOADED.presets["collab"] and found.check_stage is not None
