"""Build brief 29 (rules 2.41, Split, "On a project"), B1: `sr split --project <name>` is taken as `sr route --project`
is (decision 12): a name in the registry, a readable handoff, no open task on the project; `--chat` stays refused. In
file mode the router makes one copy at intake, owned by the split (its `project_files` record, the base the head then);
the plan call reads it, read only, with the handoff (decision 13); without git the split runs handoff only, saying why.
The split is the project's one open task from intake, at its plan and on its pieces too. A rejected plan, a `## No
split` answer and a plan that stops after its re-ask remove the copy. Real git in temp folders; fake agents; every value
here is fake."""
from pathlib import Path

import pytest

from router import __main__ as cli
from router import copies, filecalls, log, projects, split
from router.claude_worker import WorkerError
from tests.helpers import teamed
from tests.test_copies import git, make_repo
from tests.test_filemode_flow import CopyWorker, Runner
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_relay import CONFIG, ROSTER, Chat, RelayHook
from tests.test_split_approve import Ask, Jev

TASK = "In this project: fix add() in calc.py so its test passes; separately, add multiply in mathx.py with a test."
P1 = "Fix the bug in add() in calc.py so its test passes."
P2 = "Add multiply(a, b) in a new file mathx.py with a unittest test in test_mathx.py."
JOIN = "Both changes together, one after the other."
PLAN = teamed(f"## Pieces\n1. {P1}\n2. {P2}\n\n## Join\n{JOIN}\n", why="One coder and a checker are enough.")


@pytest.fixture
def conn(tmp_path):
    c = log.init_db(tmp_path / "router.db")
    yield c
    c.close()


@pytest.fixture
def registry(monkeypatch, tmp_path):
    monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "config" / "projects.json")
    monkeypatch.setattr(projects, "TESTS_PATH", tmp_path / "config" / "project_tests.json")


@pytest.fixture
def project(real_git, registry, tmp_path):
    folder = tmp_path / "sums"
    make_repo(folder, {"calc.py": "def add(a, b):\n    return a - b\n", "test_calc.py": "import unittest\n"})
    projects.add("sums", str(folder))
    git(folder, "add", "HANDOFF.md")
    git(folder, "commit", "-q", "-m", "handoff")
    return folder


def run_split(conn, *, worker, project="sums", task=TASK, ask=None, jev=None, files_ready=lambda: (True, None),
              chatgpt=None):
    lines, clock, hook = [], Clock(), RelayHook()
    code = cli.cmd_split(task, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=jev or Jev(), ask=ask, post=hook.post, worker=worker, chatgpt=chatgpt or Chat(),
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=False, project=project, files_ready=files_ready, out=lines.append)
    rows = [r for r in log.recent_tasks(conn, 50) if r["mode"] == "split"]
    return code, "\n".join(lines), rows[0] if rows else None


def route(conn, project="sums"):
    lines, clock, hook = [], Clock(), Webhook()
    code = cli.cmd_route("Another task on it.", conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=Jev(), post=hook.post, worker=Scripted("x"), chatgpt=Chat("PASS"),
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=False, project=project, out=lines.append)
    return code, "\n".join(lines)


# ---------- intake (decision 12) ----------

def test_an_unknown_project_is_refused_with_the_list_before_any_row(project, conn):
    worker = CopyWorker()
    code, out, row = run_split(conn, worker=worker, project="nope")
    assert code == 2 and row is None and worker.calls == []
    assert "Refused: no project nope. Projects: sums (sr project list). Nothing was logged or sent." in out


def test_a_busy_project_is_refused(project, conn, monkeypatch):
    log.add_task(conn, "sr-busy", "t", "cli", {"status": "ok", "label": "writing", "confidence": 0.9, "tokens": 0},
                 project="sums")
    code, out, row = run_split(conn, worker=CopyWorker())
    assert code == 2 and row is None and "Refused: project sums has task 1 open (running). Finish or cancel it first." in out


def test_chat_stays_refused_on_a_split(capsys):
    assert cli.main(["split", "--chat", "x", "--project", "sums", "plan this"], platform="darwin") == 2
    assert "Refused: --chat on sr split is refused" in capsys.readouterr().out


def test_in_file_mode_the_copy_is_made_at_intake_and_owned_by_the_split(project, conn):
    worker = CopyWorker((PLAN, {}))
    code, out, row = run_split(conn, worker=worker)
    assert code == 0, out
    found = log.project_files_of(row)
    head = git(project, "rev-parse", "HEAD").decode().strip()
    assert (found["mode"], found["state"], found["copy"], found["base"], found["branch"]) == ("on", "none", True, head,
                                                                                            "main")
    assert copies.exists(row["task_id"]) and sorted(p.name for p in copies.folder_of(row["task_id"]).iterdir()) == [
        "calc.py", "test_calc.py"]
    assert "Files: a copy of sums at" in out
    assert log.project_of(row) == "sums" and log.chat_of(row) is None


def test_the_plan_call_reads_the_copy_read_only_with_the_handoff_and_the_paragraph(project, conn):
    worker = CopyWorker((PLAN, {}))
    code, out, row = run_split(conn, worker=worker)
    call = worker.calls[0]
    assert call["copy"] is not None and call["copy"].write is False
    assert Path(call["copy"].folder) == copies.folder_of(row["task_id"])
    assert split.project_paragraph("sums", True) in call["prompt"]
    assert "TEAMS a piece may take" in call["prompt"] and "\n- route:" in call["prompt"]
    assert "\n- versus:" not in call["prompt"] and "\n- vote:" in call["prompt"]  # brief 29.1 (decision 11): a project's teams
    assert "HANDOFF.md" in call["prompt"] or "sums" in call["prompt"]  # the project's handoff rides as data
    assert copies.has_snapshot(row["task_id"], f"before-{row['task_id']}-s1")  # the snapshot before the call
    assert filecalls.blocks(conn, row, "stage", split.PLAN_ROLE, "claude") == []  # no change or tests block


def test_without_git_the_split_runs_handoff_only_and_says_why(real_git, registry, conn, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "HANDOFF.md").write_text("# Plain\n")
    projects.add("plain", str(plain))
    worker = Scripted(PLAN)
    code, out, row = run_split(conn, worker=worker, project="plain")
    assert code == 0, out
    assert log.project_files_of(row) == {"mode": "off", "state": "none", "copy": False, "why": "no git yet: Turn on undo"}
    assert split.project_paragraph("plain", False) in worker.prompts[0]


def test_a_versus_team_is_off_a_projects_plan_and_misses_its_contract(project, conn):
    off_menu = teamed(f"## Pieces\n1. {P1}\n2. {P2}\n\n## Join\n{JOIN}\n", team=["route", "versus"])
    worker = CopyWorker((off_menu, {}), (PLAN, {}))
    code, out, row = run_split(conn, worker=worker)
    assert len(worker.calls) == 2, "the one re-ask"
    assert "piece 2's team 'versus' is not on the TEAMS list (route, research-build, collab, redteam, vote)" in out
    assert [p["team"] for p in log.split_plan_of(row)["pieces"]] == ["route", "route"]


# ---------- the open-task rule (decision 12) ----------

def test_the_split_is_the_projects_open_task_at_its_plan(project, conn):
    code, out, row = run_split(conn, worker=CopyWorker((PLAN, {})))
    assert row["status"] == "returned" and row["check_note"] == "awaiting approval"
    assert log.open_task_for(conn, "sums")["task_id"] == row["task_id"]
    code, out = route(conn)
    assert code == 2 and f"project sums has task {row['n']} open (waiting for your approval)" in out


def test_the_pieces_carry_the_project_and_the_split_stays_its_open_task(project, conn):
    code, out, row = run_split(conn, worker=CopyWorker((PLAN, {})))
    lines = []
    stopped = WorkerError("claude exited 1: a fake stop")  # a Claude build on a project is never taken over: piece 1 stops
    cli.cmd_split_go([str(row["n"])], answer="y", conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                     label=Jev(), ask=None, post=None, worker=CopyWorker(stopped), chatgpt=Chat(), wait=False,
                     out=lines.append)
    pieces = log.pieces_of(conn, row["task_id"])
    assert [log.project_of(p) for p in pieces] == ["sums", "sums"]
    assert [p["status"] for p in pieces] == ["failed", "queued"], "piece 1 stopped and holds piece 2 (decision 14)"
    found = log.open_task_for(conn, "sums")
    assert found is not None and found["task_id"] == row["task_id"]


# ---------- the copy goes with a plan that never runs (decision 12) ----------

def test_a_rejected_plan_removes_the_copy(project, conn):
    code, out, row = run_split(conn, worker=CopyWorker((PLAN, {})), ask=Ask("n"))
    assert log.get_task(conn, row["task_id"])["status"] == "cancelled"
    assert not copies.exists(row["task_id"]) and log.project_files_of(log.get_task(conn, row["task_id"]))["copy"] is False
    assert log.open_task_for(conn, "sums") is None


def test_a_rejected_plan_by_flag_removes_the_copy(project, conn):
    code, out, row = run_split(conn, worker=CopyWorker((PLAN, {})))
    lines = []
    cli.cmd_split_go([str(row["n"])], answer="n", conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                     label=Jev(), ask=None, post=None, worker=None, out=lines.append)
    assert not copies.exists(row["task_id"])


def test_no_split_removes_the_copy(project, conn):
    code, out, row = run_split(conn, worker=CopyWorker(("## No split\nEach part needs the one before it.", {})))
    assert log.get_task(conn, row["task_id"])["status"] == "failed" and not copies.exists(row["task_id"])
    assert log.open_task_for(conn, "sums") is None


def test_a_plan_that_stops_after_its_re_ask_removes_the_copy(project, conn):
    code, out, row = run_split(conn, worker=CopyWorker(("nothing", {}), ("still nothing", {})))
    row = log.get_task(conn, row["task_id"])
    assert (row["status"], row["failed_stage"]) == ("failed", 1) and not copies.exists(row["task_id"])
