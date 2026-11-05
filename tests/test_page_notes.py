"""Brief 30, decisions 10, 13 to 15 and 17 (the server's part): the five new actions build their argv exactly in Python
(`notes_save`, `project_notes_save`, `project_pin`, `project_save`, `forget`), every refusal answers 400 before anything
runs, the live command line and its Copy show a notes text by its length, never the text; the two new reads run
`sr notes --json` and `sr project notes <name> --json` as argument lists (a bad name is a 400). The actions run
tests/fake_sr.py (no router, no model); the reads are a fake. Every value here is fake."""
import json
from types import SimpleNamespace

import pytest

from router import page_commands as pc
from tests.test_page_server import _call, _wait, repo, world  # noqa: F401 (the fixtures)

HASH = "0123456789abcdef"
TASK = "sr-20261028-101500-abcd"
TEXT = "## All agents\nUse metric units.\n\n## Claude\nKeep it short; quote 'this' and $5 and `that`.\n"


def _ran(out):
    return [json.loads(line) for line in out.read_text().splitlines()] if out.exists() else []


# ---------- the argv (decisions 8, 12 to 15) ----------

def test_a_notes_save_is_one_argument_after_the_dashes_with_its_hash():
    command = pc.build({"action": "notes_save", "expect": HASH, "text": TEXT}, {})
    assert list(command.args) == ["notes", "save", "--json", "--expect", HASH, "--", TEXT]
    assert command.display() == f"sr notes save --json --expect {HASH} -- <the notes, {len(TEXT)} characters>"
    assert command.copy() == f"sr notes save --expect {HASH} -- <the notes, {len(TEXT)} characters>"
    assert "metric" not in json.dumps(command.parts())  # never the text on the command line


def test_a_project_notes_save_and_a_pin_hide_their_text_too():
    command = pc.build({"action": "project_notes_save", "name": "seed-trays", "expect": HASH, "text": TEXT}, {})
    assert list(command.args) == ["project", "notes", "--json", "seed-trays", "--save", "--expect", HASH, "--", TEXT]
    assert command.copy() == f"sr project notes seed-trays --save --expect {HASH} -- <the notes, {len(TEXT)} characters>"
    command = pc.build({"action": "project_pin", "name": "seed-trays", "task_id": TASK, "text": "rubber, 3 lines"}, {})
    assert list(command.args) == ["project", "pin", "--json", "seed-trays", "--task", TASK, "--", "rubber, 3 lines"]
    assert command.copy() == f"sr project pin seed-trays --task {TASK} -- <the text, 15 characters>"


def test_a_save_to_project_and_forget():
    command = pc.build({"action": "project_save", "name": "seed-trays", "task_id": TASK, "path": "docs/tray-sizes.md"}, {})
    assert list(command.args) == ["project", "save", "--json", "seed-trays", "--task", TASK, "--path", "docs/tray-sizes.md"]
    assert command.copy() == f"sr project save seed-trays --task {TASK} --path docs/tray-sizes.md"
    assert list(pc.build({"action": "forget", "task_id": TASK}, {}).args) == ["forget", "--json", TASK]
    assert list(pc.build({"action": "forget", "task_id": TASK, "undo": True}, {}).args) == ["forget", "--json", TASK,
                                                                                           "--undo"]


@pytest.mark.parametrize("request_", [
    {"action": "notes_save", "expect": "nothex", "text": "x"},
    {"action": "notes_save", "expect": HASH, "text": "a\x00b"},
    {"action": "notes_save", "text": "x"},
    {"action": "project_notes_save", "name": "Seed", "expect": HASH, "text": "x"},
    {"action": "project_pin", "name": "seed-trays", "task_id": "#4", "text": "x"},
    {"action": "project_pin", "name": "seed-trays", "task_id": TASK, "text": "   "},
    {"action": "project_save", "name": "seed-trays", "task_id": TASK, "path": "-h"},
    {"action": "project_save", "name": "seed-trays", "task_id": TASK, "path": "d/" + "x" * 200 + ".md"},
    {"action": "forget", "task_id": TASK, "undo": "yes"},
])
def test_each_bad_request_is_refused_before_anything_runs(request_):
    with pytest.raises(pc.Refused):
        pc.build(request_, {})


def test_the_argv_reaches_sr_exactly_and_a_refusal_answers_400(world, monkeypatch, tmp_path):
    out = tmp_path / "argv.jsonl"
    monkeypatch.setenv("FAKE_SR_OUT", str(out))
    resp, body = _call(world.srv, "POST", "/api/run", {"action": "notes_save", "expect": HASH, "text": TEXT})
    assert resp.status == 200 and json.loads(body)["display"].endswith(f"<the notes, {len(TEXT)} characters>")
    _wait(world.runs)
    assert _ran(out) == [["notes", "save", "--json", "--expect", HASH, "--", TEXT]]
    resp, body = _call(world.srv, "POST", "/api/run", {"action": "forget", "task_id": "#4"})
    assert resp.status == 400 and len(_ran(out)) == 1
    runs = json.loads(_call(world.srv, "GET", "/api/runs")[1])["runs"]
    # the Run log names the command by the text's length, never the text (the fake sr echoes its argv; the router never does)
    assert runs and all("metric" not in r["display"] and r.get("request") is None for r in runs)


# ---------- the two reads (decisions 10 and 17) ----------

class NotesReads:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        assert isinstance(argv, list) and not kw.get("shell")
        self.calls.append(argv[3:])
        doc = {"api_version": 1, "notes": {"state": "blank", "hash": HASH}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(doc) + "\n", stderr="")


def test_the_reads_run_sr_notes_and_sr_project_notes_and_are_never_kept(world):
    reads = NotesReads()
    world.srv.reader.run = reads
    for _ in range(2):
        assert _call(world.srv, "GET", "/api/notes")[0].status == 200
    resp, body = _call(world.srv, "GET", "/api/project-notes?name=seed-trays")
    assert resp.status == 200 and json.loads(body)["notes"]["hash"] == HASH
    assert reads.calls == [["notes", "--json"], ["notes", "--json"], ["project", "notes", "--json", "seed-trays"]]
    resp, body = _call(world.srv, "GET", "/api/project-notes?name=-h")
    assert resp.status == 400 and len(reads.calls) == 3
    assert _call(world.srv, "GET", "/api/notes", token=False)[0].status == 403
