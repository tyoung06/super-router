"""Build brief 33.1 (decisions 1, 11, 12 and 20): the plan's commands on the page and its one read. Send · Plan builds
`sr plan --json --source ui --project <name> [--from <task>] -- <text>` and nothing else; the Step pill rides as `--step
<plan task>:<k>` with the project only; an edit is one `sr plan --edit`. `/api/plan/<name>` reads a registered project's
docs/PLAN.md, read only, never through a link. Every value here is fake."""
import os

import pytest

from router import page_commands as pc
from router import page_files
from tests.test_page_server import _call, repo, world  # noqa: F401 (fixtures)

TID = "sr-20261029-101010-abcd"
STATUS = {"presets": [{"name": "redteam", "slots": []}], "skills": []}


def test_send_plan_builds_sr_plan_with_the_project_and_from():
    found = pc.build({"action": "send", "team": "plan", "text": "Plan the first version.", "project": "garden",
                      "from": TID}, STATUS)
    assert found.args == ("plan", "--json", "--source", "ui", "--project", "garden", "--from", TID, "--",
                          "Plan the first version.")
    assert found.copy() == f"sr plan --project garden --from {TID} -- 'Plan the first version.'"


@pytest.mark.parametrize("extra, words", [
    ({"project": None}, "Plan works on a project"),
    ({"slots": {"attack": "chatgpt"}}, "a plan takes no slots"),
    ({"files": ["a.png"]}, "files go on Route only"),
    ({"chat": "tray"}, "never in a chat"),
    ({"step": f"{TID}:1"}, "a plan is no step of a plan"),
])
def test_send_plan_refuses_what_a_plan_never_takes(extra, words):
    request = {"action": "send", "team": "plan", "text": "x", "project": "garden", **extra}
    with pytest.raises(pc.Refused, match=words):
        pc.build(request, STATUS)


def test_the_step_pill_rides_on_route_and_a_team_with_the_project():
    found = pc.build({"action": "send", "team": "route", "text": "Make the skeleton.", "project": "garden",
                      "step": f"{TID}:1"}, STATUS)
    assert found.args[-4:] == ("--step", f"{TID}:1", "--", "Make the skeleton.")
    relay = pc.build({"action": "send", "team": "redteam", "text": "Add it.", "project": "garden", "step": f"{TID}:2"}, STATUS)
    assert "--step" in relay.args and relay.args[0] == "relay"
    for bad in ("12:1", f"{TID}", f"{TID}:x", f"{TID}:1; rm"):
        with pytest.raises(pc.Refused, match="a step is <plan task id>:<its number>"):
            pc.build({"action": "send", "team": "route", "text": "x", "project": "garden", "step": bad}, STATUS)
    with pytest.raises(pc.Refused, match="a step goes with its project"):
        pc.build({"action": "send", "team": "route", "text": "x", "chat": "tray", "step": f"{TID}:1"}, STATUS)


@pytest.mark.parametrize("change, value, tail", [
    ("text", "New words -h", ("--text", "--", "New words -h")),
    ("done_when", "test_x passes", ("--done-when", "--", "test_x passes")),
    ("team", "route", ("--team", "route")),
    ("up", None, ("--up",)),
    ("drop", None, ("--drop",)),
])
def test_a_plan_edit_is_one_sr_plan_edit(change, value, tail):
    request = {"action": "plan_edit", "task_id": TID, "step": 2, "change": change, **({"value": value} if value else {})}
    found = pc.build(request, STATUS)
    assert found.args == ("plan", "--json", "--edit", TID, "--step", "2", *tail)


@pytest.mark.parametrize("request_, words", [
    ({"change": "rename"}, "a plan's change is one of"),
    ({"change": "up", "value": "x"}, "--up takes no value"),
    ({"change": "team", "value": "-x"}, "starts with -"),
    ({"change": "up", "step": True}, "a step is its number"),
])
def test_a_plan_edit_refuses_anything_else(request_, words):
    with pytest.raises(pc.Refused, match=words):
        pc.build({"action": "plan_edit", "task_id": TID, "step": 2, **request_}, STATUS)


def test_the_plan_file_reads_docs_plan_md_exactly_and_never_through_a_link(world):
    folder = world.tmp / "proj"
    assert _call(world.srv, "GET", "/api/plan/proj")[0].status == 404  # no docs/PLAN.md yet
    (folder / "docs").mkdir()
    (folder / "docs" / "PLAN.md").write_text("# Plan\n")
    resp, body = _call(world.srv, "GET", "/api/plan/proj")
    assert resp.status == 200 and body == b"# Plan\n"
    assert _call(world.srv, "GET", "/api/plan/nope")[0].status == 404
    (folder / "docs" / "PLAN.md").unlink()
    elsewhere = world.tmp / "elsewhere.md"
    elsewhere.write_text("private")
    os.symlink(elsewhere, folder / "docs" / "PLAN.md")
    resp, body = _call(world.srv, "GET", "/api/plan/proj")
    assert resp.status == 404 and b"private" not in body


def test_the_files_rule_names_the_plan_file():
    assert page_files.PLAN_FILE == "docs/PLAN.md"
