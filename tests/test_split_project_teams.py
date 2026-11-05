"""Brief 29.1 (decision 11): a project split's menu gains collab and vote pieces (never versus: one shared copy can't hold
two candidates). A collab piece on a file-mode project split plans read only in the split's copy, builds in it, and is
checked on its own part with brief 29's piece line in place of the tests, returning no handoff section as every piece; a
vote piece reads the handoff and memory and changes nothing. Real git in temp folders, fake agents; every value fake."""
from pathlib import Path

from router import copies, filecalls, log
from tests.helpers import teamed
from tests.test_collab import AMENDED, PLAN as COLLAB_PLAN
from tests.test_split_project import JOIN, P1, P2, conn, project, registry  # noqa: F401 (fixtures)
from tests.test_split_project_flow import FIXED_ADD, JOINED, MULTIPLY, TEST_MULTIPLY, World, _pieces, runner  # noqa: F401
from tests.test_relay import RelayHook
from tests.test_vote_run import vote

EXECUTED = "## Deliverable\nFixed add() in calc.py.\n\n## Unfinished\nnone"


def test_a_collab_piece_plans_read_only_and_builds_in_the_splits_copy_checked_on_its_part(project, conn, runner):
    plan = teamed(f"## Pieces\n1. {P1}\n2. {P2}\n\n## Join\n{JOIN}\n", team=["collab", "route"])
    w = World((COLLAB_PLAN, {}), (EXECUTED, {"calc.py": FIXED_ADD}),
              ("Added mathx.py.", {"mathx.py": MULTIPLY, "test_mathx.py": TEST_MULTIPLY}), (JOINED, {}),
              chatgpt=(AMENDED, "PASS", "PASS", "PASS"))
    row = w.split(conn, plan=plan)
    one, two = _pieces(conn, row)
    assert one["preset"] == "collab" and log.get_task(conn, one["task_id"])["check_state"] == "passed", w.out
    copy = copies.folder_of(row["task_id"])
    plan_call, build_call = w.worker.calls[1], w.worker.calls[2]
    assert plan_call["copy"].write is False and Path(plan_call["copy"].folder) == copy
    assert build_call["copy"].write is True and Path(build_call["copy"].folder) == copy
    assert "End your result with a section `## Handoff`" not in build_call["prompt"]  # a piece returns no section
    amend, check = w.chat.prompts[0], w.chat.prompts[1]
    assert "===== PLAN =====" in amend
    assert filecalls.PIECE_JUDGE_LINE in check and "===== tests =====" not in check and "calc.py (" in check
    calls = log.calls_for(conn, one["task_id"])
    assert [c["kind"] for c in calls] == ["stage", "stage", "stage", "check"]  # plan, amend, build, then the check
    assert [c["path"] for c in log.project_files_of(log.get_task(conn, one["task_id"]))["changed"]] == ["calc.py"]


def test_a_vote_piece_reads_the_handoff_and_changes_nothing(project, conn, runner):
    plan = teamed(f"## Pieces\n1. {P1}\n2. Which file should hold multiply, mathx.py or calc.py?\n\n## Join\n{JOIN}\n",
                  team=["route", "vote"])
    w = World(("Fixed add() in calc.py.", {"calc.py": FIXED_ADD}), (vote("mathx.py"), {}), (JOINED, {}),
              chatgpt=("PASS", vote("mathx.py"), "PASS"), hook=RelayHook(s3=vote("mathx.py")))
    row = w.split(conn, plan=plan)
    w.check(conn)
    pieces = _pieces(conn, row)
    voted = next(p for p in pieces if p["preset"] == "vote")
    calls = log.calls_for(conn, voted["task_id"])
    assert [c["role"] for c in calls] == ["vote", "vote", "vote"], w.out
    assert "===== project handoff: sums =====" in w.chat.prompts[1]
    record = log.project_files_of(log.get_task(conn, voted["task_id"])) or {}
    assert not record.get("changed")
