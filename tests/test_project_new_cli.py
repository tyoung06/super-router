"""Build brief 26, A3 (rules 2.36, Making a project; Contracts): `sr project new <name> [--dry-run] [-- <notes>]` through the
real `main`. The text after `--` is the notes, one argument, never a flag; `--json` and `--dry-run` may stand anywhere
before it. A new project's envelope carries `project`; the dry run answers with its own document and exit 0, a refusal
included. Every value here is fake; a key-shaped one is built at run time."""
import json
import os
import secrets as random_secrets

import pytest

from router import __main__ as cli
from router import projects
from tests.helpers import set_local
from tests.test_json_actions import KEYS, World

NOTES = "What it is: a seed tray planner.\nDecided: no paid tools."
DRY_KEYS = ["api_version", "would", "name", "folder", "handoff", "reason_code", "message"]


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    w = World(monkeypatch, tmp_path, capsys)
    w.root = tmp_path / "garden-projects"
    w.registry = tmp_path / "config" / "projects.json"
    set_local(projects_root=str(w.root), never_register=[str(tmp_path / "off-limits")])
    return w


def one_object(text):
    lines = text.splitlines()
    assert len(lines) == 1, text
    return json.loads(lines[0])


# ---------- the parser ----------

@pytest.mark.parametrize("argv, head, notes", [
    (["project", "new", "--json", "x", "--", "a\nb"], ["project", "--json", "new", "x"], "a\nb"),
    (["project", "--json", "new", "x"], ["project", "--json", "new", "x"], None),
    (["project", "new", "x", "--dry-run", "--json"], ["project", "--dry-run", "--json", "new", "x"], None),
    (["project", "new", "x", "--", "-h"], ["project", "new", "x"], "-h"),
    (["project", "new", "x", "--", "--"], ["project", "new", "x"], "--"),
    (["project", "new", "x", "--", "--json"], ["project", "new", "x"], "--json"),
    (["route", "--json", "--", "task"], ["route", "--json", "--", "task"], None),
])
def test_the_notes_come_off_before_argparse(argv, head, notes):
    assert cli._take_project_notes(argv) == (head, notes, None)


def test_more_than_one_argument_after_dashes_says_to_quote_the_notes():
    _, notes, problem = cli._take_project_notes(["project", "new", "x", "--", "What", "it", "is"])
    assert notes is None and "in quotes" in problem
    _, notes, problem = cli._take_project_notes(["project", "new", "x", "--"])
    assert notes is None and "nothing follows --" in problem


def test_more_than_one_argument_is_a_usage_refusal(world):
    found = one_object(world.run("project", "new", "--json", "seed-trays", "--", "two", "words")[2])
    assert (found["reason_code"], found["exit"]) == ("usage", 2) and "in quotes" in found["message"]
    assert not world.root.exists()
    code, out, err = world.run("project", "new", "seed-trays", "--", "two", "words")
    assert code == 2 and "in quotes" in out and "Nothing was changed" in out


# ---------- new ----------

def test_new_with_notes_answers_with_the_envelope_and_the_project(world):
    code, out, err = world.run("project", "new", "--json", "seed-trays", "--", NOTES)
    assert code == 0 and err == ""
    found = one_object(out)
    assert list(found) == KEYS + ["project"]
    folder = (world.root / "seed-trays").resolve()
    assert found["project"] == {"name": "seed-trays", "folder": projects.tilde(folder), "handoff_lines": 5, "did": "created"}
    assert (found["task_id"], found["reason_code"], found["exit"]) == (None, None, 0)
    assert found["message"] == (f"Created seed-trays at {projects.tilde(folder)}. HANDOFF.md made: your notes, then the "
                                "router's block (5 lines).")
    assert (folder / "HANDOFF.md").read_text() == NOTES + "\n\n" + projects.START + "\n" + projects.END + "\n"
    assert json.loads(world.registry.read_text()) == {"seed-trays": str(folder)}


def test_new_without_json_prints_the_prose(world):
    code, out, err = world.run("project", "new", "seed-trays")
    folder = projects.tilde((world.root / "seed-trays").resolve())
    assert (code, err) == (0, "") and out == f"Created seed-trays at {folder}. HANDOFF.md made with an empty block (2 lines).\n"


@pytest.mark.parametrize("notes", ['say "hi"', "it's", "a `tick`", "$HOME stays", "one\ntwo\n\nfour",
                                   "--skill coding", "-h", "--json", "--"])
def test_notes_after_dashes_are_text_byte_for_byte(world, notes):
    code, out, err = world.run("project", "new", "--json", "seed-trays", "--", notes)
    assert code == 0, (out, err)
    text = (world.root / "seed-trays" / "HANDOFF.md").read_text()
    assert text == notes + ("" if notes.endswith("\n") else "\n") + "\n" + projects.START + "\n" + projects.END + "\n"


def test_empty_notes_are_no_notes(world):
    assert world.run("project", "new", "seed-trays", "--", "")[0] == 0
    assert (world.root / "seed-trays" / "HANDOFF.md").read_text() == projects.START + "\n" + projects.END + "\n"


def test_a_folder_that_is_there_is_added(world):
    (world.root / "seed-trays").mkdir(parents=True)
    (world.root / "seed-trays" / "HANDOFF.md").write_bytes(b"# Mine\n")
    found = one_object(world.run("project", "new", "--json", "seed-trays")[1])
    folder = projects.tilde((world.root / "seed-trays").resolve())
    assert found["project"] == {"name": "seed-trays", "folder": folder, "handoff_lines": 4, "did": "registered"}
    assert found["message"] == f"Added seed-trays at {folder}. HANDOFF.md given the router's block at its end (4 lines)."


def test_a_refusal_is_the_usual_envelope_on_stderr(world):
    (world.root / "seed-trays").mkdir(parents=True)
    code, out, err = world.run("project", "new", "--json", "seed-trays", "--", NOTES)
    found = one_object(err)
    assert (code, out, list(found)) == (2, "", KEYS)
    assert (found["reason_code"], found["exit"]) == ("project_refused", 2)
    assert found["message"].startswith("Refused: ") and found["message"].endswith(" Nothing was changed.")
    assert os.listdir(world.root / "seed-trays") == []


def test_a_bad_name_is_bad_name(world):
    found = one_object(world.run("project", "new", "--json", "Seed")[2])
    assert (found["reason_code"], found["exit"]) == ("bad_name", 2) and not world.root.exists()


def test_a_key_in_the_notes_is_refused_by_line_and_never_shown(world):
    value = random_secrets.token_hex(8)
    notes = "What it is: a test.\n" + "to" + "ken: " + value
    code, out, err = world.run("project", "new", "--json", "key-test", "--", notes)
    found = one_object(err)
    assert (code, found["reason_code"]) == (2, "project_refused") and "line 2" in found["message"]
    assert value not in out + err and not (world.root / "key-test").exists() and not world.registry.exists()
    code, out, err = world.run("project", "new", "key-test", "--", notes)
    assert code == 2 and "line 2" in out and value not in out + err


def test_an_env_value_in_the_notes_is_refused_by_line(world):
    found = one_object(world.run("project", "new", "--json", "key-test", "--", "one\ntwo FAKE-JEV-KEY-55 three")[2])
    assert (found["reason_code"], found["exit"]) == ("project_refused", 2) and "line 2" in found["message"]
    assert "FAKE-JEV-KEY-55" not in json.dumps(found) and not (world.root / "key-test").exists()


def test_a_fault_after_the_folder_is_project_partial_exit_1(world, monkeypatch):
    monkeypatch.setattr(projects, "_create_handoff", lambda path, data: (_ for _ in ()).throw(OSError("x")))
    code, out, err = world.run("project", "new", "--json", "seed-trays", "--", NOTES)
    found = one_object(err)
    assert (code, out, found["reason_code"], found["exit"]) == (1, "", "project_partial", 1)
    assert "What exists now" in found["message"] and "Nothing was deleted" in found["message"]
    assert (world.root / "seed-trays").is_dir()


# ---------- the dry run ----------

def test_the_dry_run_document_for_create(world):
    code, out, err = world.run("project", "new", "--json", "--dry-run", "seed-trays")
    found = one_object(out)
    assert (code, err, list(found)) == (0, "", DRY_KEYS)
    folder = projects.tilde(world.root.resolve() / "seed-trays")
    assert found == {"api_version": 1, "would": "create", "name": "seed-trays", "folder": folder,
                     "handoff": {"exists": False, "lines": None, "has_block": False}, "reason_code": None,
                     "message": f"Would create {folder} and its HANDOFF.md, and register seed-trays; the projects root "
                                f"{projects.tilde(world.root.resolve())} is made too. Nothing was changed."}
    assert not world.root.exists()


def test_the_dry_run_for_a_folder_that_is_there(world):
    (world.root / "seed-trays").mkdir(parents=True)
    (world.root / "seed-trays" / "HANDOFF.md").write_bytes(b"# Mine\nline two\n")
    found = one_object(world.run("project", "--json", "new", "seed-trays", "--dry-run")[1])
    assert (found["would"], found["handoff"], found["reason_code"]) == (
        "register", {"exists": True, "lines": 2, "has_block": False}, None)
    assert "HANDOFF.md (2 lines) given the router's block at its end" in found["message"]


@pytest.mark.parametrize("name, code", [("Seed", "bad_name"), ("off-limits", "project_refused")])
def test_a_refused_dry_run_still_exits_0(world, name, code):
    exit_code, out, err = world.run("project", "new", "--json", "--dry-run", name)
    found = one_object(out)
    assert (exit_code, err, found["would"], found["reason_code"]) == (0, "", "refused", code)
    assert found["message"].startswith("Would refuse: ") and found["folder"] is None
    assert not world.root.exists()


def test_the_dry_run_prose(world):
    code, out, err = world.run("project", "new", "seed-trays", "--dry-run")
    assert code == 0 and out.startswith("Would create ") and err == ""


def test_a_dry_run_with_notes_is_a_usage_refusal(world):
    found = one_object(world.run("project", "new", "--json", "--dry-run", "seed-trays", "--", "notes")[2])
    assert (found["reason_code"], found["exit"]) == ("usage", 2) and not world.root.exists()


@pytest.mark.parametrize("words", [["list", "--dry-run"], ["remove", "x", "--dry-run"], ["add", "x", "/tmp", "--dry-run"],
                                   ["list", "--", "notes"]])
def test_dry_run_and_notes_belong_to_new_only(world, words):
    found = one_object(world.run("project", "--json", *words)[2])
    assert (found["reason_code"], found["exit"]) == ("usage", 2)


def test_add_list_and_remove_are_unchanged(world, tmp_path):
    folder = tmp_path / "elsewhere"
    folder.mkdir()
    assert world.run("project", "add", "demo", str(folder))[0] == 0
    assert one_object(world.run("project", "list", "--json")[1])["projects"][0]["name"] == "demo"
    assert world.run("project", "remove", "demo")[0] == 0
    code, out, _ = world.run("project", "frob")
    assert code == 2 and "sr project add|list|remove|new" in out


def test_a_refused_dry_run_names_the_folder_when_it_has_one(world):
    (world.root / "seed-trays").mkdir(parents=True)
    (world.root / "seed-trays" / "HANDOFF.md").write_text("x")
    other = world.root.parent / "elsewhere"
    other.mkdir()
    world.run("project", "add", "seed-trays", str(other))
    found = one_object(world.run("project", "new", "--json", "--dry-run", "seed-trays")[1])
    # the owner's tweak (22 Oct): a taken name answers with where it is registered, shown with ~
    assert (found["would"], found["folder"]) == ("refused", projects.tilde(other.resolve()))
    assert f"already registered at {projects.tilde(other.resolve())}" in found["message"]


def test_a_taken_name_never_prints_the_home_folder(world, monkeypatch, tmp_path):
    home = (tmp_path / "home").resolve()
    monkeypatch.setenv("HOME", str(home))
    (home / "Code" / "seed-trays").mkdir(parents=True)
    world.run("project", "add", "seed-trays", str(home / "Code" / "seed-trays"))
    code, out, err = world.run("project", "new", "--json", "--dry-run", "seed-trays")
    found = one_object(out)
    assert (code, found["folder"]) == (0, "~/Code/seed-trays") and str(home) not in out + err
    code, out, err = world.run("project", "new", "seed-trays")
    assert code == 2 and "~/Code/seed-trays" in out and str(home) not in out + err
