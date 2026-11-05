"""Brief 29.1 (decision 21): Land anyway is also offered on a project split whose join check failed; one commit for the
whole split, the entry saying the check didn't pass. Real git in temp folders, fake agents; every value fake."""
from router import __main__ as cli
from router import jsonview, log, projects
from tests.test_copies import git
from tests.test_split_project import conn, project, registry  # noqa: F401 (fixtures)
from tests.test_split_project_flow import FIXED_ADD, JOINED, MULTIPLY, TEST_MULTIPLY, World, runner  # noqa: F401

FIRST = "FIX\n1. [must] The join's handoff names a file the change doesn't touch."
STILL = "FIX\n1. not fixed: it still names notes.md."


def test_a_split_whose_join_check_failed_lands_anyway_as_one_commit(project, conn, runner):
    w = World(("Fixed add() in calc.py.", {"calc.py": FIXED_ADD}),
              ("Added mathx.py and test_mathx.py.", {"mathx.py": MULTIPLY, "test_mathx.py": TEST_MULTIPLY}),
              (JOINED, {}), (JOINED, {}), chatgpt=("PASS", "PASS", FIRST, STILL))
    row = w.split(conn)
    row = log.get_task(conn, row["task_id"])
    assert (row["status"], row["check_state"]) == ("done", "failed"), w.out
    assert jsonview.task_view(conn, row)["land_anyway"] is True
    lines = []
    assert cli.cmd_land([str(row["n"])], conn=conn, config={}, verb="land", out=lines.append, anyway=True) == 0, lines
    subject = git(project, "log", "-1", "--format=%s").decode().strip()
    assert subject.endswith(f"({row['task_id']}, check not passed)")
    names = git(project, "show", "--name-only", "--format=", "HEAD").decode().split()
    assert sorted(names) == ["HANDOFF.md", "calc.py", "mathx.py", "test_mathx.py"]
    assert projects.entries_of((project / "HANDOFF.md").read_text())[0].splitlines()[0].endswith("(check not passed)")
