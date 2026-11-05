"""Build brief 29 (rules 2.41, Interface, "Split on the page"; decisions 1, 8 and 18), C1: the page's command builder
takes `split` as a team (`sr split --json --source ui [--project <name>] -- <text>`; slots, files, web, a chat tag and a
picked skill refused before anything runs) and one new action, `split_edit` (`sr split --json --edit <task> --piece <k>
[--team <team>] [-- <text>]`), each argv built by the server as every action is. The real `sr` parser reads both with the
text byte for byte; a refused request answers 400 before any run; the demo answers 409. Every value here is fake."""
import json

import pytest

from router import __main__ as cli
from router import page, page_commands as pc
from tests.test_page_commands import TEXT, TID, status  # noqa: F401 (the fixture)

TEAMS = [{"name": n, "ready": True, "project": n in ("route", "research-build", "redteam")}
         for n in ("route", "research-build", "collab", "versus", "redteam", "vote")]


@pytest.fixture
def split_status(status):
    return {**status, "split": {"ready": True, "why": None, "teams": TEAMS}}


def _args(request, status):
    return list(pc.build(request, status).args)


def test_split_is_a_team_and_its_argv_is_exact(split_status):
    assert _args({"action": "send", "team": "split", "text": TEXT}, split_status) == [
        "split", "--json", "--source", "ui", "--", TEXT]
    assert _args({"action": "send", "team": "split", "text": TEXT, "project": "brief29-demo"}, split_status) == [
        "split", "--json", "--source", "ui", "--project", "brief29-demo", "--", TEXT]


def test_the_split_display_dims_the_pages_own_flags_and_copy_leaves_them_out(split_status):
    built = pc.build({"action": "send", "team": "split", "text": "two things", "project": "brief29-demo"}, split_status)
    assert built.display() == "sr split --json --source ui --project brief29-demo -- 'two things'"
    assert built.copy() == "sr split --project brief29-demo -- 'two things'"
    assert [part["added"] for part in built.parts()] == [False, False, True, True, True, False, False, False, False]


@pytest.mark.parametrize("extra,why", [
    ({"slots": {"a": "claude"}}, "a split takes no slots"),
    ({"files": ["/x/pic.png"]}, "files go on Route only"),
    ({"web": True}, "web goes on Route only"),
    ({"chat": "chat-20261027-1040"}, "a split never carries a chat tag"),
    ({"skill": "writing"}, "a split takes no skill"),
])
def test_a_split_refuses_slots_files_web_a_chat_and_a_skill_before_anything_runs(split_status, extra, why):
    with pytest.raises(pc.Refused, match=why):
        pc.build({"action": "send", "team": "split", "text": TEXT, **extra}, split_status)


def test_split_edit_argv_for_a_team_a_text_and_both(split_status):
    assert _args({"action": "split_edit", "task_id": TID, "piece": 2, "team": "versus"}, split_status) == [
        "split", "--json", "--edit", TID, "--piece", "2", "--team", "versus"]
    assert _args({"action": "split_edit", "task_id": TID, "piece": "1", "text": TEXT}, split_status) == [
        "split", "--json", "--edit", TID, "--piece", "1", "--", TEXT]
    assert _args({"action": "split_edit", "task_id": TID, "piece": 1, "team": "redteam", "text": "-h"}, split_status) == [
        "split", "--json", "--edit", TID, "--piece", "1", "--team", "redteam", "--", "-h"]


@pytest.mark.parametrize("request_,why", [
    ({"piece": 1}, "give a team, a slot or a new text"),  # brief 29.1 (decision 12): a slot too
    ({"piece": 0, "team": "route"}, "a piece is 1 to 4"),
    ({"piece": 5, "team": "route"}, "a piece is 1 to 4"),
    ({"piece": "x", "team": "route"}, "a piece is 1 to 4"),
    ({"piece": 1, "team": "debate"}, "no team debate"),
    ({"piece": 1, "team": "--json"}, "no team --json"),
    ({"piece": 1, "text": "a\x00b"}, "NUL"),
    ({"task_id": "#5", "piece": 1, "team": "route"}, "must be a task id"),
])
def test_split_edit_refusals_before_anything_runs(split_status, request_, why):
    with pytest.raises(pc.Refused, match=why):
        pc.build({"action": "split_edit", "task_id": TID, **request_}, split_status)


@pytest.mark.parametrize("request_", [
    {"action": "send", "team": "split", "text": TEXT, "project": "brief29-demo"},
    {"action": "split_edit", "task_id": TID, "piece": 2, "team": "versus", "text": TEXT},
])
def test_the_real_parser_reads_both_with_the_text_byte_for_byte(split_status, request_):
    argv = _args(request_, split_status)
    assert cli._json_requested(argv)
    rest, slot_flags = cli._take_slot_flags(argv)
    assert slot_flags == [] and cli._slot_flag_elsewhere(argv) is None
    args = cli._parser(None, quiet=True).parse_args(rest)
    assert args.command == "split" and args.json is True and " ".join(args.task) == TEXT and len(args.task) == 1
    if request_["action"] == "send":
        assert (args.source, args.project) == ("ui", "brief29-demo")
    else:
        assert (args.edit, args.piece, args.team) == (TID, "2", "versus")


def test_split_edit_is_one_of_the_pages_actions_and_its_run_is_on_the_split():
    assert "split_edit" in pc.ACTIONS
    assert page._run_on({"action": "split_edit", "task_id": TID, "piece": 1}) == {"action": "split_edit", "task_id": TID}


# ---------- through the server (decision 18): the run, a refusal, the demo ----------

from tests.test_page_server import Reads, _call, _wait, repo, world  # noqa: E402,F401 (fixtures)


def _with_split(world):
    doc = json.loads(world.reads(["sr", "-m", "router", "status", "--json"]).stdout)
    doc["split"] = {"ready": True, "why": None, "teams": TEAMS}
    original = world.reads.__class__.__call__

    def reads(self, argv, **kw):
        found = original(self, argv, **kw)
        if argv[3] == "status":
            found.stdout = json.dumps(doc) + "\n"
        return found
    world.reads.__class__ = type("SplitReads", (Reads,), {"__call__": reads})


def test_a_split_send_and_an_edit_reach_sr_with_the_text_as_one_argument(world, monkeypatch):
    _with_split(world)
    out = world.tmp / "argv.jsonl"
    monkeypatch.setenv("FAKE_SR_OUT", str(out))
    resp, body = _call(world.srv, "POST", "/api/run", {"action": "send", "team": "split", "text": TEXT,
                                                        "project": "brief29-demo"})
    assert resp.status == 200, body
    _wait(world.runs)
    resp, body = _call(world.srv, "POST", "/api/run", {"action": "split_edit", "task_id": TID, "piece": 1, "text": TEXT})
    assert resp.status == 200, body
    _wait(world.runs)
    assert [json.loads(line) for line in out.read_text().splitlines()] == [
        ["split", "--json", "--source", "ui", "--project", "brief29-demo", "--", TEXT],
        ["split", "--json", "--edit", TID, "--piece", "1", "--", TEXT]]
    run = json.loads(_call(world.srv, "GET", "/api/runs")[1])["runs"][0]
    assert run["on"] == {"action": "split_edit", "task_id": TID}


@pytest.mark.parametrize("request_", [
    {"action": "send", "team": "split", "text": "x", "chat": "chat-1"},
    {"action": "send", "team": "split", "text": "x", "web": True},
    {"action": "split_edit", "task_id": TID, "piece": 1, "team": "debate"},
    {"action": "split_edit", "task_id": TID, "piece": 9, "team": "route"},
])
def test_a_refused_split_request_answers_400_and_runs_nothing(world, request_):
    _with_split(world)
    resp, body = _call(world.srv, "POST", "/api/run", request_)
    assert resp.status == 400 and json.loads(body)["error"] and world.runs.list() == []
