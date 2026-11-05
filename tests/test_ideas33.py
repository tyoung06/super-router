"""Build brief 33, I (decisions 14 to 16, 18 and 19): each registered project's Ideas list, kept in the log. Later on a
project card's agent chip (`sr ideas <project> --add --source <task> -- <text>`) and Add (`--add -- <text>`) fill it;
the text is one line, not empty, at most 400 characters, not starting with @ or /, and nothing the key scan or a .env
value matches (`bad_idea`, named by the rule, never quoting a key); an add matching an open idea adds nothing; at most
`ideas_max` open ideas (`ideas_full`). Send carries `--idea <id>`, checked at intake before Jev (`bad_idea`; on a split
`flag_refused`); while that task is open the idea is sent, delivered it is used, ended any other way it is open again.
Dismiss takes it off the list; the log keeps it. Every `sr ideas` action prints the list after the eight keys. Every
value here is fake."""
import json

import pytest

from router import __main__ as cli
from router import ideas, jsonview, log, nextsteps, page_commands, projects, receipt, settings
from tests.helpers import ALL_AGENTS
from tests.test_context import HANDOFF_TEXT
from tests.test_json_actions import World, jev

PROJECT = "demo"
JEV = {"status": "ok", "label": "code", "confidence": 0.9, "tokens": 0}
HANDOFF = ("\n\n## Handoff\n### Produced\nnothing written: the table\n### Status\nthe table is in\n"
           "### Next\n- Add a --round option to the converter.\n- Write the tests for negative values.")


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _register(tmp_path, name):
    folder = tmp_path / name
    folder.mkdir()
    (folder / "HANDOFF.md").write_text(HANDOFF_TEXT)
    projects.add(name, str(folder))
    return folder


@pytest.fixture
def registered(monkeypatch, tmp_path):
    monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "config" / "projects.json")
    _register(tmp_path, "other")
    return _register(tmp_path, PROJECT)


@pytest.fixture
def setting(monkeypatch, tmp_path):
    def write(**values):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps(values))
        monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    return write


def _ideas(conn, *words, add=False, source=None, dismiss=None, text=None, secrets=()):
    out = receipt.Receipt()
    code = cli.cmd_ideas(list(words), conn=conn, add=add, source=source, dismiss=dismiss, text=text, secrets=secrets,
                         out=out)
    return code, out


def _task(conn, k, *, project=PROJECT, status="done", idea=None, files=None, check_state="passed"):
    task_id = f"sr-20261029-1200{k:02d}-cd{k:02d}"
    log.add_task(conn, task_id, f"task {k}", "cli", JEV, project=project, idea=idea)
    log.set_route(conn, task_id, agents=ALL_AGENTS, agent="claude", route_reason="best", skill="code", checker="chatgpt",
                  check_state="pending")
    if status == "done":
        log.add_call(conn, task_id, task_id, "do", "claude", status="done", text="The table." + HANDOFF)
        log.set_done(conn, task_id, "The table.", check_state=check_state)
    if files is not None:
        log.set_project_files(conn, task_id, files)
    return log.get_task(conn, task_id)


# ---------- what fills it (decision 15) ----------

def test_add_keeps_the_text_its_source_and_date_and_prints_the_list(conn, registered):
    code, out = _ideas(conn, PROJECT, add=True, text="Add a Kelvin column.")
    assert code == 0 and out.message.startswith(f"Added idea 1 to {PROJECT}: Add a Kelvin column.")
    card = _task(conn, 1)
    code, out = _ideas(conn, PROJECT, add=True, source=str(card["n"]), text="Add a --round option to the converter.")
    assert code == 0
    listed = out.extra_any["ideas"]
    assert [(i["id"], i["text"], i["source"]["kind"], i["state"]) for i in listed] == [
        (2, "Add a --round option to the converter.", "later", "open"), (1, "Add a Kelvin column.", "added", "open")]
    assert listed[0]["source"] == {"kind": "later", "task_id": card["task_id"], "n": card["n"], "suggested": False}  # 33.4
    assert out.extra_any["dismissed"] == 0


def test_an_add_matching_an_open_idea_adds_nothing(conn, registered):
    _ideas(conn, PROJECT, add=True, text="Add a Kelvin column.")
    code, out = _ideas(conn, PROJECT, add=True, text="  add a kelvin COLUMN  ")
    assert code == 0 and out.message.startswith("Already there: idea 1") and len(out.extra_any["ideas"]) == 1


@pytest.mark.parametrize("text, rule", [
    ("", "an idea is one line of text, and this one is empty"),
    ("two\nlines", "an idea is one line: no line breaks"),
    ("x" * 401, "an idea is at most 400 characters (this one is 401)"),
    ("@claude do it", "an idea can't start with @ or /"),
    ("/review this", "an idea can't start with @ or /"),
])
def test_a_text_that_breaks_a_rule_is_refused_by_its_rule(conn, registered, text, rule):
    code, out = _ideas(conn, PROJECT, add=True, text=text)
    assert code == 2 and out.code == "bad_idea" and rule in out.message and "Nothing was written" in out.message
    assert conn.execute("SELECT COUNT(*) FROM ideas").fetchone()[0] == 0


def test_a_key_or_an_env_value_is_refused_and_never_quoted(conn, registered):
    secret = "gh" + "p_" + "b" * 36  # built at run time
    code, out = _ideas(conn, PROJECT, add=True, text=f"use {secret} for the API")
    assert code == 2 and out.code == "bad_idea" and secret not in out.message and "looks like a key" in out.message
    code, out = _ideas(conn, PROJECT, add=True, text="call it FAKE-VALUE-123", secrets=["FAKE-VALUE-123"])
    assert code == 2 and "FAKE-VALUE-123" not in out.message


def test_past_ideas_max_open_ideas_an_add_is_refused(conn, registered, setting):
    setting(ideas_max=2)
    _ideas(conn, PROJECT, add=True, text="one")
    _ideas(conn, PROJECT, add=True, text="two")
    code, out = _ideas(conn, PROJECT, add=True, text="three")
    assert code == 2 and out.code == "ideas_full" and len(out.extra_any["ideas"]) == 2
    _ideas(conn, PROJECT, dismiss="1")
    assert _ideas(conn, PROJECT, add=True, text="three")[0] == 0  # a dismissed idea isn't open


def test_an_unregistered_project_and_another_projects_card_are_refused(conn, registered):
    assert _ideas(conn, "nowhere", add=True, text="x")[1].code == "project_unknown"
    card = _task(conn, 1, project="other")
    code, out = _ideas(conn, PROJECT, add=True, source=card["task_id"], text="x")
    assert code == 2 and out.code == "bad_idea" and f"#{card['n']} isn't a task of {PROJECT}" in out.message


def test_flags_that_do_not_go_together_are_usage(conn, registered):
    assert _ideas(conn, PROJECT, add=True, dismiss="1", text="x")[1].code == "usage"
    assert _ideas(conn, PROJECT, source="1")[1].code == "usage"
    assert _ideas(conn, PROJECT, text="x")[1].code == "usage"
    assert _ideas(conn, PROJECT, add=True)[1].code == "usage"
    assert _ideas(conn)[1].code == "usage"


# ---------- Dismiss (decision 16) ----------

def test_dismiss_takes_it_off_the_list_and_the_log_keeps_it(conn, registered):
    _ideas(conn, PROJECT, add=True, text="Add a Kelvin column.")
    code, out = _ideas(conn, PROJECT, dismiss="1")
    assert code == 0 and out.extra_any["ideas"] == [] and out.extra_any["dismissed"] == 1
    assert conn.execute("SELECT dismissed_at FROM ideas WHERE id = 1").fetchone()[0] is not None
    assert _ideas(conn, PROJECT, dismiss="1")[1].code == "bad_idea"  # already dismissed
    assert _ideas(conn, "other", dismiss="1")[1].code == "bad_idea"  # another project's


# ---------- the states (decision 16) ----------

def test_sent_while_its_task_is_open_used_once_delivered(conn, registered):
    _ideas(conn, PROJECT, add=True, text="Add a Kelvin column.")
    _task(conn, 1, status="queued", idea=1)
    found = ideas.get(conn, 1)
    assert found.state == ideas.SENT and ideas.view(conn, found)["sent_as"]["n"] == found.task["n"]
    conn.execute("DELETE FROM tasks")
    _task(conn, 2, idea=1)
    assert ideas.get(conn, 1).state == ideas.USED
    assert ideas.listing(conn, PROJECT)["ideas"] == []  # a used idea leaves the list


def test_open_again_when_its_task_ends_any_other_way(conn, registered):
    _ideas(conn, PROJECT, add=True, text="Add a Kelvin column.")
    _task(conn, 1, idea=1, check_state="failed")
    assert ideas.get(conn, 1).state == ideas.OPEN


def test_a_change_holds_it_until_it_lands_and_a_discard_frees_it(conn, registered):
    _ideas(conn, PROJECT, add=True, text="Add a Kelvin column.")
    row = _task(conn, 1, idea=1, files={"state": "waiting"})
    assert ideas.get(conn, 1).state == ideas.SENT
    log.set_project_files(conn, row["task_id"], {"state": "landed"})
    assert ideas.get(conn, 1).state == ideas.USED
    log.set_project_files(conn, row["task_id"], {"state": "discarded"})
    assert ideas.get(conn, 1).state == ideas.OPEN


# ---------- Later (decision 7) ----------

def test_a_line_moved_to_the_list_from_a_card_is_not_offered_again(conn, registered):
    card = _task(conn, 1)
    before = [c["words"] for c in nextsteps.chips(conn, card)]
    assert "Add a --round option to the converter." in before
    _ideas(conn, PROJECT, add=True, source=card["task_id"], text="Add a --round option to the converter.")
    view = jsonview.task_view(conn, log.get_task(conn, card["task_id"]))
    assert "Add a --round option to the converter." not in [c["words"] for c in view["next"]]
    assert "Write the tests for negative values." in [c["words"] for c in view["next"]]


# ---------- --idea at intake (decision 16) ----------

@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    w = World(monkeypatch, tmp_path, capsys)  # it points the registry at tmp_path/config/projects.json
    monkeypatch.setattr(cli.memory, "client", lambda request, **kw: None)
    _register(tmp_path, PROJECT)
    _register(tmp_path, "other")
    return w


def test_the_envelope_carries_the_list_after_the_eight_keys(world):
    code, out, err = world.run("ideas", PROJECT, "--add", "--json", "--", "Add a Kelvin column.")
    doc = json.loads(out)
    assert code == 0 and list(doc)[-4:] == ["ideas", "dismissed", "used", "suggest"] and doc["ideas"][0]["text"] == "Add a Kelvin column."
    code, out, err = world.run("ideas", PROJECT, "--json")
    assert code == 0 and [i["id"] for i in json.loads(out)["ideas"]] == [1]


def _intake_world(world, monkeypatch, tmp_path):
    conn = log.init_db(cli.DB_PATH)
    ideas.add(conn, PROJECT, "Add a Kelvin column.")
    ideas.add(conn, "other", "Not ours.")
    conn.close()


@pytest.mark.parametrize("argv, why", [
    (["route", "--idea", "1", "do it"], "idea 1 is demo's: send it with --project demo"),
    (["route", "--project", "demo", "--idea", "2", "do it"], "idea 2 is other's, not demo's"),
    (["route", "--project", "demo", "--idea", "9", "do it"], "there is no idea 9"),
    (["route", "--project", "demo", "--idea", "one", "do it"], "an idea is its number"),
])
def test_idea_is_refused_before_jev(world, monkeypatch, tmp_path, argv, why):
    _intake_world(world, monkeypatch, tmp_path)
    found = world.json(*argv)
    assert (found["exit"], found["reason_code"]) == (2, "bad_idea") and why in found["message"], found["message"]
    assert world.label.calls == []


def test_idea_on_split_is_flag_refused_and_twice_is_usage(world, monkeypatch, tmp_path):
    _intake_world(world, monkeypatch, tmp_path)
    assert world.json("split", "--idea", "1", "plan it")["reason_code"] == "flag_refused"
    assert world.json("route", "--project", "demo", "--idea", "1", "--idea", "1", "do it")["reason_code"] == "usage"


def test_an_idea_that_is_not_open_is_refused(conn, registered):
    ideas.add(conn, PROJECT, "Add a Kelvin column.")
    _task(conn, 1, status="queued", idea=1)
    assert ideas.intake_refusal(conn, 1, PROJECT).startswith("idea 1 isn't open (it is sent as #")


def test_the_json_names_the_idea_a_task_was_sent_from(conn, registered):
    ideas.add(conn, PROJECT, "Add a Kelvin column.")
    row = _task(conn, 1, idea=1)
    assert jsonview.task_view(conn, row)["idea"] == {"id": 1, "text": "Add a Kelvin column.", "state": "used"}
    assert jsonview.task_view(conn, _task(conn, 2))["idea"] is None


def test_status_and_the_project_list_give_each_project_its_open_idea_count(conn, registered):
    ideas.add(conn, PROJECT, "one")
    ideas.add(conn, PROJECT, "two")
    from router import status
    found = {p["name"]: p["ideas"] for p in status.projects_view(conn)}
    assert found[PROJECT] == 2 and found["other"] == 0
    listed = cli._projects_json({PROJECT: str(registered)}, {}, conn=conn)
    assert listed[0]["ideas"] == 2


# ---------- the page's builder (decision 19) ----------

STATUS = {"presets": [], "skills": [{"key": "code"}], "drop_folder": None}


def test_the_builder_makes_each_ideas_command():
    add = page_commands.build({"action": "ideas_add", "name": PROJECT, "text": "Add a Kelvin column."}, STATUS)
    assert list(add.args) == ["ideas", "--json", PROJECT, "--add", "--", "Add a Kelvin column."]
    later = page_commands.build({"action": "ideas_add", "name": PROJECT, "text": "Add a --round option.",
                                 "source": "sr-20261029-120001-cd01"}, STATUS)
    assert list(later.args) == ["ideas", "--json", PROJECT, "--add", "--source", "sr-20261029-120001-cd01", "--",
                                "Add a --round option."]
    gone = page_commands.build({"action": "ideas_dismiss", "name": PROJECT, "id": 3}, STATUS)
    assert list(gone.args) == ["ideas", "--json", PROJECT, "--dismiss", "3"]
    sent = page_commands.build({"action": "send", "team": "route", "text": "Add a Kelvin column.", "project": PROJECT,
                                "idea": 3}, STATUS)
    assert list(sent.args) == ["route", "--json", "--source", "ui", "--project", PROJECT, "--idea", "3", "--",
                               "Add a Kelvin column."]
    with pytest.raises(page_commands.Refused):
        page_commands.build({"action": "send", "team": "split", "text": "x", "project": PROJECT, "idea": 3}, STATUS)
    with pytest.raises(page_commands.Refused):
        page_commands.build({"action": "ideas_dismiss", "name": PROJECT, "id": "3; rm"}, STATUS)
    for built in (add, later, gone, sent):
        cli._parser(None, quiet=True).parse_args(cli._take_project_notes(list(built.args))[0])


def test_an_add_or_a_dismiss_that_ran_drops_the_pages_kept_status():
    """The bar's "Ideas · <k>" reads status, which the page server keeps for a minute: an idea added (Later, Add) or
    dismissed changes the count, so a run that exited 0 drops it, as a secret set does; a refused one keeps it."""
    from router import page
    assert {"ideas_add", "ideas_dismiss"} <= set(page.DROPS_STATUS)
    dropped = []
    reader = type("Reader", (), {"forget_status": lambda self: dropped.append(True)})()
    page._after_run(reader, {"request": {"action": "ideas_add"}}, 2)
    assert dropped == []
    page._after_run(reader, {"request": {"action": "ideas_dismiss"}}, 0)
    assert dropped == [True]
