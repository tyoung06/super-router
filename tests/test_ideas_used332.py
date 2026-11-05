"""Brief 33.2 fix 4 (the owner's decision 4, item 6 / D2 option B): a used idea leaves the open list for a folded Used
list on the Ideas sheet. `ideas.listing` gives the used ideas too, newest first, each with the task that used it
(`used: [{…the view…, "used_by": {"task_id", "n"}}]`); `ideas` still holds open and sent only, and the open counts in
status and the project list are unchanged. `sr ideas --json` carries `used` after the eight keys. Every value here is
fake."""
from router import ideas, log
from tests.test_addtoplan332 import _idea
from tests.test_filemode_flow import conn, project, runner  # noqa: F401 (fixtures: a log on disk)
from tests.test_ideas33 import PROJECT, _ideas, _task, registered  # noqa: F401 (fixtures)
from tests.test_plan_approval import _land
from tests.test_plan_chain import ReadWorker, World
from tests.test_revise332 import REV, REV_ANSWERED, _first_plan


def test_an_idea_used_by_a_delivered_task_is_listed_as_used_with_its_task(conn, registered):
    _ideas(conn, PROJECT, add=True, text="Add a Kelvin column.")
    _ideas(conn, PROJECT, add=True, text="Write the tests for negative values.")
    row = _task(conn, 1, idea=1)
    found = ideas.listing(conn, PROJECT)
    assert [i["text"] for i in found["ideas"]] == ["Write the tests for negative values."]  # the open list, as before
    assert [(i["id"], i["text"], i["state"]) for i in found.get("used", [])] == [(1, "Add a Kelvin column.", ideas.USED)]
    assert found["used"][0]["used_by"] == {"task_id": row["task_id"], "n": row["n"]}
    assert ideas.open_count(conn, PROJECT) == 1  # status's and the project list's count is unchanged


def test_used_is_newest_first_and_a_sent_or_dismissed_idea_is_not_in_it(conn, registered):
    for text in ("one", "two", "three", "four"):
        _ideas(conn, PROJECT, add=True, text=text)
    _task(conn, 1, idea=1)
    _task(conn, 2, idea=2)
    _task(conn, 3, idea=3, status="queued")  # sent
    _ideas(conn, PROJECT, dismiss="4")
    found = ideas.listing(conn, PROJECT)
    assert [i["text"] for i in found["used"]] == ["two", "one"]
    assert [i["text"] for i in found["ideas"]] == ["three"] and found["dismissed"] == 1


def test_no_used_idea_gives_an_empty_list(conn, registered):
    _ideas(conn, PROJECT, add=True, text="Add a Kelvin column.")
    assert ideas.listing(conn, PROJECT)["used"] == []


def test_the_json_carries_used_after_the_eight_keys(conn, registered):
    _ideas(conn, PROJECT, add=True, text="Add a Kelvin column.")
    row = _task(conn, 1, idea=1)
    code, out = _ideas(conn, PROJECT)
    assert code == 0
    assert out.extra_any["used"][0]["used_by"]["n"] == row["n"] and out.extra_any["ideas"] == []


def test_an_idea_used_by_a_landed_plan_is_listed_as_used_by_the_plan(project, conn, runner):
    old, step1 = _first_plan(conn, project)
    idea = _idea(conn)
    w = World(worker=ReadWorker(REV, REV_ANSWERED))
    code, row = w.plan(conn, task=idea.text, idea_ref=str(idea.id))
    assert code == 0, w.said
    assert _land(conn, log.get_task(conn, row["task_id"]))[0] == 0
    found = ideas.listing(conn, "garden")
    assert found["ideas"] == []
    assert [(i["text"], i["used_by"]["n"]) for i in found["used"]] == [(idea.text, log.get_task(conn, row["task_id"])["n"])]
