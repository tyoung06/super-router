"""Build brief 33.2, K (decision 8): Check against the spec. When every step is done and the spec has a `## Done when`
list, the finish line's first chip is Check against the spec (Route, the project, the decision's text ending "Change no
files; report only."); the three-chip cap holds by dropping Set the run command from that line; without a `## Done when`
list the finish line is as today. Real git in temp folders, fake agents; every value here is fake."""
from router import __main__ as cli
from router import log, plan, projects, whatnow
from tests.test_filemode_flow import CopyWorker, conn, project, runner  # noqa: F401 (fixtures)
from tests.test_plan_approval import _land
from tests.test_plan_chain import ReadWorker, World
from tests.test_plan_rest import NO_NEEDS, REVISED_NO_NEEDS
from tests.test_plan_steps import RESEARCH, _route_step
from tests.test_spec332 import SPEC, TEXT_SPEC, _commit_spec

TEXT = ("Check the project against SPEC.md's `## Done when` list: for each item, D1 on, say met or not met, with the "
        "evidence (the test or the file), then what is missing. Change no files; report only.")


def _finished(conn, project, spec_text=None):
    if spec_text is not None:
        _commit_spec(project, spec_text)
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    w = World(worker=ReadWorker(NO_NEEDS, REVISED_NO_NEEDS))
    code, row = w.plan(conn)
    assert code == 0, w.said
    assert _land(conn, log.get_task(conn, row["task_id"]))[0] == 0
    found = log.get_task(conn, row["task_id"])
    for k in (1, 2):
        code, said, step = _route_step(conn, f"{found['n']}:{k}", worker=CopyWorker(RESEARCH))
        assert code == 0, said
    return whatnow.for_project(conn, "garden")


def test_the_chips_text_is_the_decisions_and_it_comes_first_with_set_the_run_command_out():
    found = plan.finish_chips("garden", run_command_set=False, done_when=True)
    assert [c["kind"] for c in found] == ["spec_check", "readme", "what_next"]
    assert found[0] == {"kind": "spec_check", "words": "Check against the spec", "later": False,
                        "fill": {"team": "route", "project": "garden", "chat": None, "text": TEXT, "from": None, "idea": None,
                                 "step": None}}
    assert plan.SPEC_CHECK_TEXT.endswith("Change no files; report only.")
    assert [c["kind"] for c in plan.finish_chips("garden", run_command_set=True, done_when=True)] == ["spec_check", "readme", "what_next"]
    assert [c["kind"] for c in plan.finish_chips("garden", run_command_set=False, done_when=False)] == ["readme", "run_command", "what_next"]
    assert [c["kind"] for c in plan.finish_chips("garden", run_command_set=True, done_when=False)] == ["readme", "what_next"]


DONE_ONLY = "# Converter\n\nA converter.\n\n## Done when\n- both functions pass their tests\n- README.md says how to run them\n"


def test_the_finish_line_offers_check_against_the_spec_first_with_a_done_when_list(project, conn, runner):
    line = _finished(conn, project, DONE_ONLY)  # a `## Done when` list alone: the plan needs no `covers:`
    assert (line["rung"], line["words"]) == ("finish", "All 2 steps done")
    assert [c["kind"] for c in line["chips"]] == ["spec_check", "readme", "what_next"]
    assert line["chips"][0]["words"] == "Check against the spec" and line["chips"][0]["fill"]["text"] == TEXT
    assert len(line["chips"]) == 3  # the cap holds: Set the run command dropped from this line, though none is set


def test_without_a_done_when_list_the_finish_line_is_as_today(project, conn, runner):
    line = _finished(conn, project, TEXT_SPEC)
    assert [c["kind"] for c in line["chips"]] == ["readme", "run_command", "what_next"]


def test_without_a_spec_the_finish_line_is_as_today(project, conn, runner):
    line = _finished(conn, project)
    assert [c["kind"] for c in line["chips"]] == ["readme", "run_command", "what_next"]
