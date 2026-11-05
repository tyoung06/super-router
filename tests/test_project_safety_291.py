"""Brief 29.1 (decision 6, from brief 28's overnight run): an ordinary project task's handoff write at delivery takes the
project's lock and waits for it (Land, Undo and Discard keep refusing at once), so one entry is never lost; a project drop
whose Add is refused moves its files from the drop folder's top level into `refused/`, so a later `sr route` never offers
them; the copies root is a setting (`copies_root`, default the Application Support folder); and `sr land`, `sr discard` and
`sr cancel` on a file-mode task refuse, with nothing removed, when the task's project isn't in the registry. Real git in
temp folders, fake agents; every value fake."""
import threading
import time

import pytest

from router import __main__ as cli
from router import copies, locks, log, projects, runs, settings
from tests.helpers import set_local
from tests.test_filemode_flow import BUILD, Chat, CopyWorker, conn, project, route, runner  # noqa: F401
from tests.test_handoff_contract import HANDOFF
from tests.test_landing import land, waiting
from tests.test_projgit import fake_file, gitted, registry, run  # noqa: F401


# ---------- the delivery's handoff write waits for the project's lock ----------

def test_the_delivery_entry_waits_for_the_projects_lock_and_is_never_lost(project, conn, runner, monkeypatch):
    monkeypatch.setattr(locks, "POLL_SECONDS", 0.05)
    folder = cli.DB_PATH.parent / runs.FOLDER_NAME
    held, took = threading.Event(), {}

    def holder():  # another router write in the project (a land, a files in) holding the lock for a moment
        with locks.held("project-garden", folder=folder, wait=False):
            held.set()
            time.sleep(0.6)
            took["released"] = time.monotonic()

    thread = threading.Thread(target=holder)
    thread.start()
    held.wait(5)
    code, out, row = route(conn, worker=CopyWorker(("Two lines.\n\n" + HANDOFF, {})), chatgpt=Chat("PASS"),
                           files_ready=lambda: (False, "the file check is off for this test"))
    after = time.monotonic()
    thread.join(5)
    assert code == 0, out
    assert after >= took["released"], "the write waited for the lock"
    entries = projects.entries_of((project / "HANDOFF.md").read_text())
    assert entries and entries[0].startswith(f"### #{row['n']} ·")


def test_land_still_refuses_at_once_while_the_lock_is_held(project, conn, runner):
    row = waiting(conn)
    with locks.held("project-garden", folder=cli.DB_PATH.parent / runs.FOLDER_NAME, wait=False):
        code, out = land(conn, row)
    assert code == 2 and "another land, undo, discard or file change is running in garden" in out


# ---------- a refused Add moves its files into refused/ ----------

def test_a_refused_add_moves_the_drops_files_into_refused(registry, capsys):
    folder = gitted(registry)
    drop = registry / "drop"
    set_local(drop_folder=str(drop))
    clash = fake_file(drop, "README.md", "# a second readme\n")  # the folder holds one already: refused
    other = fake_file(drop, "notes.txt", "notes\n")
    code, out = run(["project", "files", "garden", "--file", clash, "--file", other], capsys)
    assert code == 2 and "README.md is already in the folder" in out
    assert sorted(p.name for p in drop.iterdir() if p.is_file()) == [], "nothing waits at the top level"
    refused = [p for p in (drop / "refused").iterdir()]
    assert len(refused) == 1 and sorted(p.name for p in refused[0].iterdir()) == ["README.md", "notes.txt"]
    assert "refused/" in out and (folder / "README.md").read_text() == "# Garden\n"


def test_a_refused_add_of_files_outside_the_drop_folder_moves_nothing(registry, capsys, tmp_path):
    gitted(registry)
    set_local(drop_folder=str(registry / "drop"))
    elsewhere = fake_file(tmp_path / "elsewhere", "README.md", "# mine\n")
    code, out = run(["project", "files", "garden", "--file", elsewhere], capsys)
    assert code == 2 and (tmp_path / "elsewhere" / "README.md").exists()
    assert not (registry / "drop" / "refused").exists()


# ---------- the copies root is a setting ----------

def test_the_copies_root_comes_from_the_local_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(copies, "ROOT", None)  # the suite's own temp root off: the setting decides
    assert copies.root() == copies.DEFAULT_ROOT  # no setting: the Application Support folder, as before
    set_local(copies_root=str(tmp_path / "scratch-copies"))
    assert copies.root() == tmp_path / "scratch-copies"
    assert copies.copies_root() == tmp_path / "scratch-copies" / "copies"
    assert copies.history_root() == tmp_path / "scratch-copies" / "history"
    set_local(copies_root="~/sr-copies-here")
    assert copies.root() == (tmp_path / "x").home() / "sr-copies-here"
    set_local(copies_root="relative/folder")
    with pytest.raises(copies.CopyError, match="copies_root in settings isn't an absolute or ~ path"):
        copies.root()


def test_the_tracked_settings_hold_no_copies_root():
    assert "copies_root" not in settings._load(settings.SETTINGS_PATH)


# ---------- land, discard and cancel refuse when the project isn't registered ----------

@pytest.mark.parametrize("verb", ["land", "discard"])
def test_land_and_discard_refuse_with_nothing_removed_when_the_project_is_gone(project, conn, runner, verb):
    row = waiting(conn)
    projects.remove("garden")
    code, out = land(conn, row, verb)
    assert code == 2 and "project garden is no longer registered" in out
    assert copies.exists(row["task_id"]) and log.project_files_of(log.get_task(conn, row["task_id"]))["state"] == "waiting"


def test_cancel_refuses_with_nothing_removed_when_the_project_is_gone(project, conn, runner, grok_room):
    code, out, row = route(conn, worker=CopyWorker(BUILD), wait=False,
                           jev={"status": "ok", "label": "bulk_text", "confidence": 0.95, "needs_split": 0.1, "tokens": 10})
    row = log.get_task(conn, row["task_id"])
    assert row["status"] in ("queued", "sent") and copies.exists(row["task_id"]), out  # Grok checks it: it stays open
    projects.remove("garden")
    lines = []
    assert cli.cmd_cancel(conn=conn, words=[str(row["n"])], out=lines.append) == 2
    assert "project garden is no longer registered" in "\n".join(lines)
    assert copies.exists(row["task_id"]) and log.get_task(conn, row["task_id"])["status"] == row["status"]
