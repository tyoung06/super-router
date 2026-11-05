"""Brief 30, decisions 12 to 14 (rules 2.43, Project context and Project files): a project's notes (the part of HANDOFF.md
above the router's block), Pin to notes and Save to project. Each writes exactly its commit (HANDOFF.md alone for notes
and a pin; the file and HANDOFF.md for a save), or the file alone with no commit where there is no git or HANDOFF.md isn't
tracked; each refusal writes nothing. The router's block stays byte for byte. Real git in temp folders; every value fake;
a key-shaped value is built at run time from pieces."""
import json
import os
import secrets as random_secrets

import pytest

from router import __main__ as cli
from router import landing, log, projects, projnotes, settings
from tests.helpers import ALL_AGENTS, set_local
from tests.test_copies import git, make_repo
from tests.test_landing import head, show, state

BLOCK = (f"{projects.START}\n\n### #7 · 2026-10-27 · writing · claude\nProduced:\nnothing written: ## Trays\nStatus:\nok\n"
         f"Next:\n—\n\n{projects.END}\n")


@pytest.fixture
def registry(real_git, tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "config" / "projects.json")
    monkeypatch.setattr(projects, "TESTS_PATH", tmp_path / "config" / "project_tests.json")
    return tmp_path


def gitted(tmp_path, name="garden", handoff=f"# Garden\n\nThe owner's notes.\n\n{BLOCK}"):
    folder = tmp_path / name
    make_repo(folder, {"README.md": "# Garden\n", "HANDOFF.md": handoff})
    projects.add(name, str(folder))
    return folder


def run(argv, capsys):
    code = cli.main(argv, platform="darwin")
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def run_json(argv, capsys):
    code = cli.main([*argv[:2], "--json", *argv[2:]] if "--" not in argv else
                    [*argv[:2], "--json", *argv[2:]], platform="darwin")
    captured = capsys.readouterr()
    return code, json.loads((captured.out or captured.err).strip().splitlines()[-1])


def block_of(text):
    return text[text.index(projects.START):]


# ---------- read (decision 12) ----------

def test_notes_are_the_part_above_the_block_with_their_hash_counts_and_the_cap(registry, capsys):
    gitted(registry)
    code, doc = run_json(["project", "notes", "garden"], capsys)
    found = doc["notes"]
    assert code == 0 and found["notes"] == "# Garden\n\nThe owner's notes."
    assert found["hash"] == projnotes.digest("# Garden\n\nThe owner's notes.") and found["chars"] == 28
    assert (found["lines"], found["max"], found["git"], found["tracked"]) == (3, 20000, True, True)
    assert found["block"] == BLOCK.rstrip("\n") and found["block"].startswith(projects.START)


# ---------- save (decision 12) ----------

def test_a_save_is_one_commit_holding_handoff_alone_with_the_block_byte_for_byte(registry, capsys):
    folder = gitted(registry)
    before = head(folder)
    hash_ = projnotes.digest("# Garden\n\nThe owner's notes.")
    code, out = run(["project", "notes", "garden", "--save", "--expect", hash_, "--", "# Garden\n\nNew notes.\n\n"], capsys)
    assert code == 0, out
    text = (folder / "HANDOFF.md").read_text()
    assert text == "# Garden\n\nNew notes.\n\n" + BLOCK  # the text, one blank line, the block byte for byte
    assert git(folder, "rev-parse", "HEAD~1").decode().strip() == before
    subject, _, _, *names = show(folder, head(folder))
    assert subject == "sr: notes edited" and [n for n in names if n] == ["HANDOFF.md"]
    assert git(folder, "status", "--porcelain=v1").decode() == ""
    assert projects.entries_of(text) == projects.entries_of(BLOCK)  # no entry in the block


def test_crlf_endings_are_kept_and_a_missing_block_is_added_and_a_missing_file_made(registry, capsys):
    folder = gitted(registry, handoff=f"Line one.\r\n\r\n{projects.START}\r\n{projects.END}\r\n")
    code, out = run(["project", "notes", "garden", "--save", "--", "One.\nTwo."], capsys)
    assert code == 0, out
    assert (folder / "HANDOFF.md").read_bytes() == f"One.\r\nTwo.\r\n\r\n{projects.START}\r\n{projects.END}\r\n".encode()
    plain = registry / "plain"
    plain.mkdir()
    projects.add("plain", str(plain))
    (plain / "HANDOFF.md").write_text("no block here\n")
    code, out = run(["project", "notes", "plain", "--save", "--", "Mine."], capsys)
    assert code == 0 and "nothing committed" in out
    assert (plain / "HANDOFF.md").read_text() == f"Mine.\n\n{projects.START}\n{projects.END}\n"
    (plain / "HANDOFF.md").unlink()
    code, out = run(["project", "notes", "plain", "--save", "--", "Made."], capsys)
    assert code == 0 and (plain / "HANDOFF.md").read_text() == f"Made.\n\n{projects.START}\n{projects.END}\n"


@pytest.mark.parametrize("text,words", [
    (f"ok\n{projects.START}\n", "line 2 of the notes is the router's marker"),
    ("to" + "ken: " + "0123456789abcdef", "line 1 of the notes looks like it holds a key"),
])
def test_each_refusal_writes_nothing_and_names_the_line(registry, capsys, text, words):
    folder = gitted(registry)
    before = state(folder)
    code, out = run(["project", "notes", "garden", "--save", "--", text], capsys)
    assert code == 2 and words in out and "0123456789abcdef" not in out
    assert state(folder) == before


def test_a_env_value_and_the_cap_are_refused(registry, capsys, monkeypatch):
    folder = gitted(registry)
    value = "fake-env-" + random_secrets.token_hex(6)
    monkeypatch.setattr(cli, "dotenv_values", lambda path: {"JEV_API_KEY": value})
    before = state(folder)
    code, out = run(["project", "notes", "garden", "--save", "--", f"mine\nis {value}"], capsys)
    assert code == 2 and "line 2 of the notes holds a value from .env" in out and value not in out
    monkeypatch.setattr(settings, "notes_setting", lambda name: (10, "test"))
    code, out = run(["project", "notes", "garden", "--save", "--", "x" * 11], capsys)
    assert code == 2 and "at most 10" in out and state(folder) == before


def test_expect_refuses_notes_changed_since(registry, capsys):
    folder = gitted(registry)
    before = state(folder)
    code, doc = run_json(["project", "notes", "garden", "--save", "--expect", "0" * 16, "--", "new"], capsys)
    assert code == 2 and doc["reason_code"] == "notes_changed" and state(folder) == before


def test_the_lock_held_refuses_at_once(registry, capsys, monkeypatch):
    folder = gitted(registry)

    class Busy:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            raise landing.Refused("another land, undo, discard or file change is running in garden; try again when "
                                  "it ends", "project_refused")

        def __exit__(self, *exc):
            return False
    monkeypatch.setattr(landing, "project_lock", Busy)
    before = state(folder)
    code, out = run(["project", "notes", "garden", "--save", "--", "new"], capsys)
    assert code == 2 and "another land" in out and state(folder) == before


def test_no_commit_without_git_and_in_the_routers_own_folder(registry, capsys, monkeypatch):
    folder = registry / "nogit"
    folder.mkdir()
    projects.add("nogit", str(folder))
    code, out = run(["project", "notes", "nogit", "--save", "--", "Hello."], capsys)
    assert code == 0 and "nothing committed" in out and not (folder / ".git").exists()
    gitted(registry, "untracked")
    folder = registry / "untracked"
    git(folder, "rm", "-q", "--cached", "HANDOFF.md")
    git(folder, "commit", "-q", "-m", "untrack")
    before = head(folder)
    code, out = run(["project", "notes", "untracked", "--save", "--", "Hello."], capsys)
    assert code == 0 and "nothing committed" in out and head(folder) == before


def test_an_interrupted_commit_is_finished_by_the_journal(registry, capsys):
    folder = gitted(registry)
    with pytest.raises(RuntimeError):
        projnotes.save(None, "garden", "Interrupted.", journal_dir=cli._journal_dir(),
                       lock_folder=cli.DB_PATH.parent / "run", fault="after_branch")
    assert (folder / "HANDOFF.md").read_text().startswith("# Garden")  # the branch moved, the file not yet
    code, out = run(["project", "notes", "garden"], capsys)
    landing.recover(None, folder, cli._journal_dir(), out=lambda line: None)
    assert (folder / "HANDOFF.md").read_text().startswith("Interrupted.") and git(folder, "status", "--porcelain=v1") == b""


def test_the_300_line_warning_as_today(registry, capsys):
    gitted(registry)
    code, out = run(["project", "notes", "garden", "--save", "--", "\n".join(f"line {i}" for i in range(320))], capsys)
    assert code == 0 and "the router warns past 300" in out


# ---------- Pin to notes (decision 13) ----------

def _task(conn, task_id="sr-20261028-101500-aaaa", *, status="done", result="Use euros for prices.", project=None,
          chat=None, check_state="passed"):
    log.add_task(conn, task_id, "What currency?", "cli", {"status": "ok", "label": "writing", "confidence": 0.9,
                                                          "tokens": 0}, project=project, chat=chat)
    log.set_route(conn, task_id, agents=ALL_AGENTS, agent="claude", route_reason="best", skill="writing",
                  checker="chatgpt", check_state="pending")
    if status == "done":
        log.add_call(conn, task_id, task_id, "do", "claude", status="done", text=result)
        log.set_done(conn, task_id, result, check_state=check_state)
    return log.get_task(conn, task_id)


def test_a_pin_appends_a_blank_line_its_heading_and_the_text_as_one_commit(registry, capsys):
    folder = gitted(registry)
    conn = log.init_db(cli.DB_PATH)
    try:
        row = _task(conn)  # untagged: pinned into a chosen project
    finally:
        conn.close()
    code, out = run(["project", "pin", "garden", "--task", row["task_id"], "--", "Use euros."], capsys)
    assert code == 0, out
    text = (folder / "HANDOFF.md").read_text()
    today = f"{cli._now():%Y-%m-%d}"
    assert text == f"# Garden\n\nThe owner's notes.\n\n### Pinned from #{row['n']} ({today})\nUse euros.\n\n" + BLOCK
    subject, _, _, *names = show(folder, head(folder))
    assert subject == f"sr: pinned #{row['n']} to the notes" and [n for n in names if n] == ["HANDOFF.md"]


def test_an_open_task_is_refused_and_writes_nothing(registry, capsys):
    folder = gitted(registry)
    conn = log.init_db(cli.DB_PATH)
    try:
        row = _task(conn, status="queued")
    finally:
        conn.close()
    before = state(folder)
    code, doc = run_json(["project", "pin", "garden", "--task", row["task_id"], "--", "x"], capsys)
    assert code == 2 and doc["reason_code"] == "wrong_state" and state(folder) == before


# ---------- Save to project (decision 14) ----------

def test_save_writes_the_result_without_its_handoff_section_as_one_commit_with_the_entry(registry, capsys):
    folder = gitted(registry)
    conn = log.init_db(cli.DB_PATH)
    try:
        row = _task(conn, result="# Tray sizes\n\nSmall, medium.\n\n## Handoff\n### Produced\nx\n### Status\ny\n### Next\nz")
    finally:
        conn.close()
    before = head(folder)
    code, out = run(["project", "save", "garden", "--task", row["task_id"], "--path", "docs/notes/tray-sizes.md"], capsys)
    assert code == 0, out
    assert (folder / "docs" / "notes" / "tray-sizes.md").read_text() == "# Tray sizes\n\nSmall, medium.\n"
    subject, _, _, *names = show(folder, head(folder))
    assert sorted(n for n in names if n) == ["HANDOFF.md", "docs/notes/tray-sizes.md"]
    assert git(folder, "rev-parse", "HEAD~1").decode().strip() == before
    today = f"{cli._now():%Y-%m-%d}"
    assert projects.entries_of((folder / "HANDOFF.md").read_text())[0] == \
        f"### {today} · saved: docs/notes/tray-sizes.md (from #{row['n']})"
    assert git(folder, "status", "--porcelain=v1").decode() == ""


@pytest.mark.parametrize("path,words", [
    ("/abs/x.md", "must be relative"), ("../out.md", "inside the project's folder"), ("docs/x.py", "end .md or .txt"),
    (".hidden/x.md", "start with ."), ("HANDOFF.md", "router's notes file"), ("README.md", "never overwritten"),
    ("docs/" + "x" * 200 + ".md", "at most 200"), (".env.md", "start with ."),
])
def test_each_path_rule_refuses_with_nothing_written(registry, capsys, path, words):
    folder = gitted(registry)
    conn = log.init_db(cli.DB_PATH)
    try:
        row = _task(conn)
    finally:
        conn.close()
    before = state(folder)
    code, out = run(["project", "save", "garden", "--task", row["task_id"], "--path", path], capsys)
    assert code == 2 and words in out and state(folder) == before


def test_save_refuses_a_flagged_text_no_git_a_task_not_done_and_no_text(registry, capsys):
    folder = gitted(registry)
    conn = log.init_db(cli.DB_PATH)
    try:
        leaky = _task(conn, "sr-20261028-101500-bbbb", result="key: " + "to" + "ken: 0123456789abcdef")
        open_ = _task(conn, "sr-20261028-101500-cccc", status="queued")
        failed = _task(conn, "sr-20261028-101500-dddd", check_state="failed")
        empty = _task(conn, "sr-20261028-101500-eeee", result="   ")
    finally:
        conn.close()
    before = state(folder)
    for row, words in ((leaky, "looks like it holds a key"), (open_, "isn't done"), (failed, "didn't pass"),
                       (empty, "no text result")):
        code, out = run(["project", "save", "garden", "--task", row["task_id"], "--path", "docs/x.md"], capsys)
        assert code == 2 and words in out and "0123456789abcdef" not in out, (row["task_id"], out)
    assert state(folder) == before
    nogit = registry / "nogit"
    nogit.mkdir()
    projects.add("nogit", str(nogit))
    conn = log.init_db(cli.DB_PATH)
    try:
        ok = _task(conn, "sr-20261028-101500-ffff")
    finally:
        conn.close()
    code, out = run(["project", "save", "nogit", "--task", ok["task_id"], "--path", "docs/x.md"], capsys)
    assert code == 2 and "Turn on undo first" in out and not (nogit / "docs").exists()


@pytest.mark.parametrize("result,task,expected", [
    ("# Tray Sizes: Small & Medium\n\nx", "anything", "docs/tray-sizes-small-medium.md"),
    ("## Answer\nrubber\n\n## Why\nflexes", "Is a rubber tee or a plastic tee more durable on a mat?",
     "docs/is-a-rubber-tee-or-a.md"),  # the task's first six words; `## Answer` is the router's own heading
    ("no heading at all", "Write a Python function slugify(title) now please", "docs/write-a-python-function-slugify-title.md"),
    ("```\n# not a heading\n```\nplain", "!!! ???", "docs/task-{n}.md"),
    ("# " + "word " * 30, "x", "docs/word-word-word-word-word-word-word-word.md"),
])
def test_save_path_from_a_heading_from_the_tasks_words_or_neither(result, task, expected):
    row = {"n": 9, "task": task, "result": result}
    assert projnotes.save_path(row) == expected.format(n=9)
    assert len(projnotes.save_path(row)) <= len("docs/") + 40 + len(".md")


def test_a_later_land_clashes_with_a_saved_path(registry, capsys):
    folder = gitted(registry)
    (folder / "docs").mkdir()
    (folder / "docs" / "x.md").write_text("saved\n")  # as a save leaves it: a new path in the folder
    with pytest.raises(landing.Refused, match="already in the folder"):
        landing._clean(folder, ["docs/x.md"], ["docs/x.md"])
