"""Build brief 23, A5 (decisions 3, 4 and 12): the one command builder. A structured request from the page becomes the
argument list after `sr`, and its display, in Python; the page never assembles a command. Every argv carries `--json`,
and `--source ui` on route and relay; typed text goes after `--` as one argument, byte for byte, so `--skill coding` or
`-h` typed in the box is text; any other value that starts with `-` or holds a control character is refused before
anything runs; the team, slots, agents and skills are checked against the current status; refs are task ids. The
display shows `sr`, quotes with shlex, and marks the flags the page adds; Copy leaves them out. Every built argv is also
handed to the real `sr` parser (no command runs), so what the server would run is what `sr` reads."""
import json
from pathlib import Path

import pytest

from router import __main__ as cli
from router import page_commands as pc

TEXT = 'He said "hi" & it\'s `ls` $HOME $5\nline two --skill coding -h @grok'
TID, TID2 = "sr-20261021-000803-3d77", "sr-20261021-000901-ab12"


@pytest.fixture
def status(tmp_path):
    drop = tmp_path / "Router Drop"
    drop.mkdir()
    (drop / "pic.png").write_bytes(b"png")
    (drop / "sub").mkdir()
    (drop / "sub" / "deep.png").write_bytes(b"png")
    every = ["claude", "grok", "chatgpt"]
    return {
        "presets": [
            {"name": "research-build", "slots": [{"name": "research", "default": "grok", "allowed": every},
                                                 {"name": "build", "default": "claude", "allowed": every},
                                                 {"name": "check", "default": "chatgpt", "allowed": every}]},
            {"name": "versus", "slots": [{"name": "a", "default": "claude", "allowed": every + ["cursor"]},
                                         {"name": "b", "default": "chatgpt", "allowed": every + ["cursor"]}]},
            {"name": "vote", "slots": [{"name": "a", "default": "claude", "allowed": every},
                                       {"name": "b", "default": "chatgpt", "allowed": every},
                                       {"name": "c", "default": "grok", "allowed": every}]},
        ],
        "skills": [{"key": k} for k in ("writing", "code", "planning", "quick_answer", "recall")],
        "drop_folder": str(drop),
    }


def _args(request, status):
    return list(pc.build(request, status).args)


# ---------- each action's argv, exactly ----------

def test_a_route_send_with_a_chat(status):
    assert _args({"action": "send", "team": "route", "text": "what is 6 times 7", "chat": "brief23"}, status) == [
        "route", "--json", "--source", "ui", "--chat", "brief23", "--", "what is 6 times 7"]


def test_a_route_send_with_a_project_a_dropped_file_and_web(status):
    pic = status["drop_folder"] + "/pic.png"
    assert _args({"action": "send", "team": "route", "text": "describe it", "project": "super-router", "files": [pic],
                  "web": True}, status) == [
        "route", "--json", "--source", "ui", "--project", "super-router", "--file", pic, "--web", "--", "describe it"]


def test_a_route_send_with_your_skill_when_jev_is_not_set_up(status):
    # brief 24 (decision 13, C16): the page asks for the skill before Send; it goes on as `--skill`, checked against status
    assert _args({"action": "send", "team": "route", "text": "plan the supper", "chat": "garden", "skill": "planning"},
                 status) == ["route", "--json", "--source", "ui", "--chat", "garden", "--skill", "planning", "--",
                             "plan the supper"]
    with pytest.raises(pc.Refused, match="no skill nope; the skills are writing, code"):
        pc.build({"action": "send", "team": "route", "text": "x", "skill": "nope"}, status)
    with pytest.raises(pc.Refused):
        pc.build({"action": "send", "team": "route", "text": "x", "skill": "--help"}, status)


def test_a_team_send_with_slots_in_the_presets_order(status):
    assert _args({"action": "send", "team": "versus", "text": "write is_leap", "chat": "brief23",
                  "slots": {"b": "cursor", "a": "claude"}}, status) == [
        "relay", "versus", "--json", "--source", "ui", "--a", "claude", "--b", "cursor", "--chat", "brief23", "--",
        "write is_leap"]


def test_a_team_send_with_no_slots_and_no_tag(status):
    assert _args({"action": "send", "team": "vote", "text": "rubber or wood?"}, status) == [
        "relay", "vote", "--json", "--source", "ui", "--", "rubber or wood?"]


def test_the_floor_answer_sends_the_rows_text_with_skill_and_answers_and_nothing_else(status):
    assert _args({"action": "floor", "text": "redo the calendar", "skill": "planning", "answers": TID}, status) == [
        "route", "--json", "--source", "ui", "--skill", "planning", "--answers", TID, "--", "redo the calendar"]


@pytest.mark.parametrize("request_, argv", [
    ({"action": "pick", "task_id": TID, "choice": "a"}, ["pick", "--json", TID, "a"]),
    ({"action": "pick", "task_id": TID, "choice": "none"}, ["pick", "--json", TID, "none"]),
    ({"action": "pick", "task_id": TID, "choice": "c"}, ["pick", "--json", TID, "c"]),
    ({"action": "resume", "task_id": TID}, ["resume", "--json", TID]),
    ({"action": "fallback", "task_id": TID}, ["fallback", "--json", TID]),
    ({"action": "cancel", "task_id": TID}, ["cancel", "--json", TID]),
    ({"action": "check"}, ["check", "--json"]),
    ({"action": "split_go", "task_id": TID, "choice": "y"}, ["split", "--json", "--go", TID, "--answer", "y"]),
    ({"action": "split_go", "task_id": TID, "choice": "y", "skills": {"2": "code", "1": "writing"}},
     ["split", "--json", "--go", TID, "--answer", "y", "--skill", "1=writing", "--skill", "2=code"]),
    ({"action": "split_go", "task_id": TID, "choice": "n"}, ["split", "--json", "--go", TID, "--answer", "n"]),
    ({"action": "split_skip", "task_id": TID2}, ["split", "--json", "--skip", TID2]),
])
def test_each_action_on_a_task(status, request_, argv):
    assert _args(request_, status) == argv


COPIES = json.loads((Path(__file__).parent / "fixtures" / "page_copies.json").read_text())


@pytest.mark.parametrize("case", COPIES, ids=[c["copy"][:40] for c in COPIES])
def test_copy_is_the_command_as_a_person_would_type_it(status, case):
    # The demo's confirms preview these same strings (tests/js/needs.test.js reads this file too), so the two can't drift.
    assert pc.build(case["request"], status).copy() == case["copy"]


# ---------- typed text is text (decision 3) ----------

@pytest.mark.parametrize("text", [TEXT, "--skill coding", "-h", "@grok write a haiku", "--", "  spaces kept  "])
def test_typed_text_goes_after_the_double_dash_as_one_argument_byte_for_byte(status, text):
    argv = _args({"action": "send", "team": "route", "text": text}, status)
    assert argv == ["route", "--json", "--source", "ui", "--", text]


def test_a_text_with_a_nul_character_is_refused(status):
    with pytest.raises(pc.Refused, match="NUL"):
        pc.build({"action": "send", "team": "route", "text": "a\x00b"}, status)


# ---------- refused before anything runs ----------

@pytest.mark.parametrize("request_, why", [
    ({"action": "send", "team": "route", "text": "x", "chat": "-x"}, "starts with -"),
    ({"action": "send", "team": "route", "text": "x", "project": "--skill"}, "starts with -"),
    ({"action": "send", "team": "route", "text": "x", "chat": "a\x07b"}, "control character"),
    ({"action": "send", "team": "route", "text": "x", "chat": "a\nb"}, "control character"),
    ({"action": "send", "team": "route", "text": "x", "files": ["-rf"]}, "starts with -"),
    ({"action": "send", "team": "collab", "text": "x"}, "no team collab"),
    ({"action": "send", "team": "versus", "text": "x", "slots": {"c": "claude"}}, "no slot c on versus"),
    ({"action": "send", "team": "versus", "text": "x", "slots": {"a": "muse"}}, "muse can't fill slot a on versus"),
    ({"action": "send", "team": "research-build", "text": "x", "slots": {"build": "cursor"}}, "cursor can't fill slot build"),
    ({"action": "send", "team": "versus", "text": "x", "files": ["/tmp/a.png"]}, "files go on Route only"),
    ({"action": "send", "team": "versus", "text": "x", "web": True}, "web goes on Route only"),
    ({"action": "send", "team": "route", "text": "x", "slots": {"a": "claude"}}, "slots go on a team"),
    ({"action": "send", "team": "route", "text": 7}, "text"),
    ({"action": "floor", "text": "x", "skill": "dancing", "answers": TID}, "no skill dancing"),
    ({"action": "floor", "text": "x", "skill": "code", "answers": "#5"}, "task id"),
    ({"action": "pick", "task_id": "5", "choice": "a"}, "task id"),
    ({"action": "pick", "task_id": TID, "choice": "d"}, "a, b, c or none"),
    ({"action": "split_go", "task_id": TID, "choice": "e"}, "y or n"),
    ({"action": "split_go", "task_id": TID, "choice": "n", "skills": {"1": "code"}}, "only with y"),
    ({"action": "split_go", "task_id": TID, "choice": "y", "skills": {"one": "code"}}, "piece number"),
    ({"action": "split_go", "task_id": TID, "choice": "y", "skills": {"1": "dancing"}}, "no skill dancing"),
    ({"action": "probe"}, "no action probe"),
    ({"action": "memory"}, "no action memory"),
])
def test_refused_with_the_reason(status, request_, why):
    with pytest.raises(pc.Refused, match=why.replace("(", r"\(")):
        pc.build(request_, status)


def test_a_file_must_sit_at_the_drop_folders_top_level(status, tmp_path):
    for path in (status["drop_folder"] + "/sub/deep.png", str(tmp_path / "elsewhere.png"), status["drop_folder"] + "/none.png"):
        with pytest.raises(pc.Refused, match="drop folder"):
            pc.build({"action": "send", "team": "route", "text": "x", "files": [path]}, status)


def test_without_a_status_nothing_is_built():
    with pytest.raises(pc.Refused, match="status"):
        pc.build({"action": "check"}, None)


# ---------- the display (decision 4) ----------

def test_the_display_shows_sr_quotes_with_shlex_and_copy_leaves_out_the_pages_own_flags(status):
    command = pc.build({"action": "send", "team": "route", "text": "what costs $5", "chat": "tray"}, status)
    assert command.display() == "sr route --json --source ui --chat tray -- 'what costs $5'"
    assert command.copy() == "sr route --chat tray -- 'what costs $5'"
    assert [(p["text"], p["added"]) for p in command.parts()] == [
        ("sr", False), ("route", False), ("--json", True), ("--source", True), ("ui", True), ("--chat", False),
        ("tray", False), ("--", False), ("'what costs $5'", False)]


def test_a_check_has_only_json_added(status):
    command = pc.build({"action": "check"}, status)
    assert command.copy() == "sr check" and command.display() == "sr check --json"


# ---------- what the server would run is what sr reads (no command runs) ----------

REQUESTS = [
    {"action": "send", "team": "route", "text": TEXT, "chat": "brief23"},
    {"action": "send", "team": "route", "text": "-h"},
    {"action": "send", "team": "versus", "text": TEXT, "slots": {"b": "cursor"}, "chat": "brief23"},
    {"action": "send", "team": "vote", "text": TEXT, "project": "super-router"},
    {"action": "floor", "text": TEXT, "skill": "planning", "answers": TID},
    {"action": "pick", "task_id": TID, "choice": "a"},
    {"action": "resume", "task_id": TID},
    {"action": "fallback", "task_id": TID},
    {"action": "cancel", "task_id": TID},
    {"action": "check"},
    {"action": "split_go", "task_id": TID, "choice": "y", "skills": {"1": "code"}},
    {"action": "split_skip", "task_id": TID2},
]


@pytest.mark.parametrize("request_", REQUESTS)
def test_the_real_parser_reads_every_built_argv_with_the_text_byte_for_byte(status, request_):
    argv = _args(request_, status)
    assert cli._json_requested(argv), argv
    rest, slot_flags = cli._take_slot_flags(argv)
    args = cli._parser(None, quiet=True).parse_args(rest)
    assert args.command == argv[0] and args.json is True
    if "text" in request_:
        assert " ".join(args.task) == request_["text"] and len(args.task) == 1
    if request_.get("slots"):
        assert slot_flags == sorted(request_["slots"].items())
    if request_["action"] in ("send", "floor"):
        assert args.source == "ui"
    if request_["action"] in ("pick", "resume", "fallback", "cancel"):
        assert args.words[0] == TID


# ---------- brief 26 (decision 9): project_new ----------

def test_project_new_without_notes(status):
    command = pc.build({"action": "project_new", "name": "seed-trays", "notes": ""}, status)
    assert (list(command.args), command.added) == (["project", "new", "--json", "seed-trays"], frozenset({2}))
    assert _args({"action": "project_new", "name": "seed-trays"}, status) == ["project", "new", "--json", "seed-trays"]
    assert command.display() == "sr project new --json seed-trays" and command.copy() == "sr project new seed-trays"
    assert [p["added"] for p in command.parts()] == [False, False, False, True, False]


def test_project_new_with_notes_after_dashes_as_typed(status):
    command = pc.build({"action": "project_new", "name": "seed-trays", "notes": TEXT}, status)
    assert list(command.args) == ["project", "new", "--json", "seed-trays", "--", TEXT]
    assert command.display() == "sr project new --json seed-trays -- " + __import__("shlex").quote(TEXT)  # as typed


@pytest.mark.parametrize("name", ["Seed", "-h", "--json", "", None, "a/b", "a.b", "seed trays", 5, "-seed"])
def test_project_new_refuses_a_bad_name_before_anything(status, name):
    with pytest.raises(pc.Refused, match="the project name"):
        pc.build({"action": "project_new", "name": name, "notes": ""}, status)


@pytest.mark.parametrize("notes", ["a\x00b", 5, ["x"]])
def test_project_new_refuses_notes_no_command_line_carries(status, notes):
    with pytest.raises(pc.Refused, match="the notes"):
        pc.build({"action": "project_new", "name": "seed-trays", "notes": notes}, status)


@pytest.mark.parametrize("notes", [TEXT, "-h", "--skill coding", "--", "--json", "line\n\nthree"])
def test_the_real_parser_reads_project_new_with_the_notes_byte_for_byte(status, notes):
    argv = _args({"action": "project_new", "name": "seed-trays", "notes": notes}, status)
    assert cli._json_requested(argv)
    rest, notes_seen, problem = cli._take_project_notes(cli._take_slot_flags(argv)[0])
    args = cli._parser(None, quiet=True).parse_args(rest)
    assert (args.command, args.words, args.json, args.dry_run, notes_seen, problem) == (
        "project", ["new", "seed-trays"], True, False, notes, None)
