"""Build brief 23, A7 (decisions 8, 9 and 11): the files the page server may open, resolved through links and inside one
of a task's folders (`tasks/<task_id>/`, `media/in|pages|frames|out/<task_id>/`, for a task id of the router's shape),
or `report_path` exactly, or a registered project's `HANDOFF.md` exactly; never a `.env*` name, `router.db*`, `backups/`
or `config/`; a link that leads out of the task folder it sits in is refused, another task's folder among the places it
could lead. Text over 2 MB reads its first 2 MB. A dropped file is written into the drop folder only, with exclusive
create (a clash becomes " (2)"), after Media's types and its 50 MB limit. Open in Finder runs `open -R` on an allowed
path, on macOS only. Temp folders only; no real file is read or written."""
import os
import subprocess

import pytest

from router import media, page_files as pf

TID, OTHER = "sr-20261021-000803-3d77", "sr-20261021-000901-ab12"


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "repo"
    for folder in ("tasks", "media/in", "media/pages", "media/frames", "media/out"):
        (r / folder / TID).mkdir(parents=True)
    (r / "tasks" / TID / "01-do-claude.md").write_text("the answer")
    (r / "tasks" / TID / "02-check-chatgpt.md").write_text("PASS")
    (r / "tasks" / TID / "03-build-a-claude.md").write_text("candidate a")
    (r / "media" / "in" / TID / "pic.png").write_bytes(b"\x89PNG")
    (r / "media" / "pages" / TID / "page-1.png").write_bytes(b"\x89PNG")
    (r / "media" / "frames" / TID / "frame_01.jpg").write_bytes(b"\xff\xd8")
    (r / "media" / "out" / TID / "tray.png").write_bytes(b"\x89PNG")
    (r / "tasks" / OTHER).mkdir()
    (r / "tasks" / OTHER / "01-do-grok.md").write_text("the other task")
    (r / ".env").write_text("JEV_API_KEY=FAKE-KEY")
    (r / "router.db").write_bytes(b"SQLite")
    (r / "backups").mkdir()
    (r / "backups" / "router-v14.db").write_bytes(b"SQLite")
    (r / "config").mkdir()
    (r / "config" / "agents.json").write_text("{}")
    return r


# ---------- the list for one task ----------

def test_a_tasks_files_come_from_its_folders_named_from_the_round_file(root):
    found = pf.task_files(root, TID)
    assert [f["path"] for f in found] == [
        f"tasks/{TID}/01-do-claude.md", f"tasks/{TID}/02-check-chatgpt.md", f"tasks/{TID}/03-build-a-claude.md",
        f"media/in/{TID}/pic.png", f"media/pages/{TID}/page-1.png", f"media/frames/{TID}/frame_01.jpg",
        f"media/out/{TID}/tray.png"]
    first = found[0]
    assert (first["name"], first["kind"], first["size"], first["root"]) == ("01-do-claude.md", "text", 10, "tasks")
    assert first["round"] == {"order": 1, "role": "do", "agent": "claude"}
    assert found[2]["round"] == {"order": 3, "role": "build-a", "agent": "claude"}
    assert [f["kind"] for f in found[3:]] == ["image", "image", "image", "image"] and found[3]["round"] is None


def test_a_task_id_not_of_the_routers_shape_lists_nothing(root):
    for bad in ("../repo", "sr-1", "#5", "sr-20261021-000803-3d77/..", ""):
        with pytest.raises(pf.Refused):
            pf.task_files(root, bad)


def test_a_task_with_no_folders_lists_nothing(root):
    assert pf.task_files(root, "sr-20261021-235959-0000") == []


# ---------- one file ----------

# ---------- Log files: the tasks/ folder, newest first (brief 23, F) ----------

def test_log_files_list_the_task_folders_newest_first_with_their_round_files(root):
    found = pf.log_folders(root)
    assert [f["task_id"] for f in found["folders"]] == [OTHER, TID] and found["next_before"] is None
    assert [x["name"] for x in found["folders"][1]["files"]] == ["01-do-claude.md", "02-check-chatgpt.md", "03-build-a-claude.md"]
    assert {x["root"] for f in found["folders"] for x in f["files"]} == {"tasks"}  # media stays on the task's own card


def test_log_files_page_by_before_and_limit(root):
    first = pf.log_folders(root, limit=1)
    assert ([f["task_id"] for f in first["folders"]], first["next_before"]) == ([OTHER], OTHER)
    second = pf.log_folders(root, before=first["next_before"], limit=1)
    assert ([f["task_id"] for f in second["folders"]], second["next_before"]) == ([TID], None)


def test_log_files_leave_out_other_names_and_a_folder_that_links_out(root, tmp_path):
    outside = tmp_path / "elsewhere" / "sr-20261021-235959-ffff"
    outside.mkdir(parents=True)
    (outside / "01-do-claude.md").write_text("not the router's")
    (root / "tasks" / "sr-20261021-235959-ffff").symlink_to(outside, target_is_directory=True)
    (root / "tasks" / "notes").mkdir()
    (root / "tasks" / "sr-bad").mkdir()
    assert [f["task_id"] for f in pf.log_folders(root)["folders"]] == [OTHER, TID]


def test_log_files_refuse_a_before_that_is_not_a_task_id(root):
    with pytest.raises(pf.Refused):
        pf.log_folders(root, before="../../etc")


def test_log_files_with_no_tasks_folder_list_nothing(tmp_path):
    assert pf.log_folders(tmp_path) == {"folders": [], "next_before": None}


def test_an_allowed_file_resolves(root):
    assert pf.resolve(root, f"tasks/{TID}/01-do-claude.md") == (root / "tasks" / TID / "01-do-claude.md").resolve()
    assert pf.resolve(root, f"media/out/{TID}/tray.png").name == "tray.png"
    assert pf.resolve(root, f"tasks/{OTHER}/01-do-grok.md").name == "01-do-grok.md"  # its own folder: allowed


@pytest.mark.parametrize("path", [
    f"tasks/{TID}/../{OTHER}/01-do-grok.md", "../repo/.env", f"tasks/{TID}/../../.env", ".env", "router.db",
    "backups/router-v14.db", "config/agents.json", f"tasks/{TID}", "tasks/sr-1/x.md", "static/app.js", "README",
    f"media/cache/{TID}/x.png", f"tasks/{TID}/missing.md",
])
def test_each_path_outside_the_rule_is_refused(root, path):
    with pytest.raises(pf.Refused):
        pf.resolve(root, path)


def test_a_link_out_of_its_task_folder_is_refused_even_into_another_tasks_folder(root, tmp_path):
    folder = root / "tasks" / TID
    (folder / "to-env.md").symlink_to(root / ".env")
    (folder / "to-other.md").symlink_to(root / "tasks" / OTHER / "01-do-grok.md")
    (tmp_path / "outside.md").write_text("outside")
    (folder / "to-outside.md").symlink_to(tmp_path / "outside.md")
    for name in ("to-env.md", "to-other.md", "to-outside.md"):
        with pytest.raises(pf.Refused):
            pf.resolve(root, f"tasks/{TID}/{name}")
    assert not any(f["name"].startswith("to-") for f in pf.task_files(root, TID))


def test_a_task_folder_that_is_a_link_out_is_refused(root, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "x.md").write_text("x")
    (root / "tasks" / "sr-20261021-111111-aaaa").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(pf.Refused):
        pf.resolve(root, "tasks/sr-20261021-111111-aaaa/x.md")
    assert pf.task_files(root, "sr-20261021-111111-aaaa") == []


def test_a_denied_name_inside_a_task_folder_is_refused(root):
    (root / "media" / "in" / TID / ".env.local").write_text("x")
    (root / "media" / "in" / TID / "router.db-wal").write_bytes(b"x")
    for name in (".env.local", "router.db-wal"):
        with pytest.raises(pf.Refused):
            pf.resolve(root, f"media/in/{TID}/{name}")


def test_report_path_and_a_projects_handoff_exactly(root, tmp_path):
    report, handoff = tmp_path / "report.md", tmp_path / "proj" / "HANDOFF.md"
    report.write_text("the report")
    handoff.parent.mkdir()
    handoff.write_text("the handoff")
    (tmp_path / "proj" / "notes.md").write_text("not allowed")
    assert pf.resolve(root, str(report), report_path=str(report)) == report.resolve()
    assert pf.resolve(root, str(handoff), handoffs=[str(handoff)]) == handoff.resolve()
    for path in (str(tmp_path / "proj" / "notes.md"), str(report)):
        with pytest.raises(pf.Refused):
            pf.resolve(root, path, handoffs=[str(handoff)])


def test_text_over_2_mb_reads_its_first_2_mb(root, monkeypatch):
    monkeypatch.setattr(pf, "TEXT_LIMIT", 8)
    path = root / "tasks" / TID / "01-do-claude.md"
    path.write_text("0123456789abc")
    data, total = pf.read(path)
    assert (data, total) == (b"01234567", 13)
    assert pf.read(root / "media" / "in" / TID / "pic.png") == (b"\x89PNG", None)


def test_content_types_never_serve_html(root):
    assert pf.content_type("x.md") == pf.content_type("x.html") == "text/plain; charset=utf-8"
    assert (pf.content_type("x.png"), pf.content_type("x.jpg"), pf.content_type("x.pdf"), pf.content_type("x.mov")) == (
        "image/png", "image/jpeg", "application/pdf", "video/quicktime")
    assert pf.content_type("x.svg") == "application/octet-stream"


# ---------- the drop (decision 8) ----------

def test_a_dropped_file_is_written_into_the_drop_folder_and_never_overwrites(tmp_path):
    folder = tmp_path / "Router Drop"
    first = pf.drop_write(folder, "shot.png", b"one")
    second = pf.drop_write(folder, "shot.png", b"two")
    third = pf.drop_write(folder, "shot.png", b"three")
    assert (first.name, second.name, third.name) == ("shot.png", "shot (2).png", "shot (3).png")
    assert first.read_bytes() == b"one" and second.read_bytes() == b"two" and first.parent == folder
    assert pf.drop_write(folder, "photo.HEIC", b"x").name == "photo.HEIC"  # intake converts it, as for --file


@pytest.mark.parametrize("name, why", [
    ("notes.txt", "can't go on a task"), ("../escape.png", "name"), ("sub/dir.png", "name"), (".hidden.png", "name"),
    ("bad\x07.png", "name"), ("", "name"), ("noext", "can't go on a task"),
])
def test_a_drop_media_refuses_is_refused_and_nothing_is_written(tmp_path, name, why):
    folder = tmp_path / "Router Drop"
    with pytest.raises(pf.Refused, match=why):
        pf.drop_write(folder, name, b"x")
    assert not folder.exists() or list(folder.iterdir()) == []
    assert not (tmp_path / "escape.png").exists()


def test_a_drop_over_50_mb_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "MAX_BYTES", 4)
    with pytest.raises(pf.Refused, match="50 MB"):
        pf.drop_write(tmp_path / "Router Drop", "big.png", b"12345")


def test_without_a_drop_folder_nothing_is_written(tmp_path):
    with pytest.raises(pf.Refused, match="drop folder"):
        pf.drop_write(None, "shot.png", b"x")


def test_a_dropped_file_is_owner_only_and_not_through_a_link(tmp_path):
    folder = tmp_path / "Router Drop"
    folder.mkdir()
    (tmp_path / "target.png").write_bytes(b"keep")
    (folder / "shot.png").symlink_to(tmp_path / "target.png")
    written = pf.drop_write(folder, "shot.png", b"new")
    assert written.name == "shot (2).png" and (tmp_path / "target.png").read_bytes() == b"keep"
    assert oct(written.stat().st_mode & 0o777) == "0o600"


# ---------- Open in Finder (decision 11) ----------

def test_reveal_runs_open_r_on_an_allowed_path_on_macos_only(root):
    seen = []

    def run(argv, **kw):
        seen.append((argv, kw))
        return subprocess.CompletedProcess(argv, 0, "", "")
    pf.reveal(root, f"tasks/{TID}/01-do-claude.md", run=run, platform="darwin")
    argv, kw = seen[0]
    assert argv == ["open", "-R", str((root / "tasks" / TID / "01-do-claude.md").resolve())] and not kw.get("shell")
    with pytest.raises(pf.Refused, match="macOS"):
        pf.reveal(root, f"tasks/{TID}/01-do-claude.md", run=run, platform="linux")
    with pytest.raises(pf.Refused):
        pf.reveal(root, ".env", run=run, platform="darwin")
    assert len(seen) == 1


def test_the_files_module_never_reads_env_or_the_log():
    text = (pf.ROOT / "router" / "page_files.py").read_text(encoding="utf-8")
    assert "dotenv" not in text and "sqlite3" not in text and "shell=True" not in text
    assert os.path.basename(pf.__file__) == "page_files.py"
