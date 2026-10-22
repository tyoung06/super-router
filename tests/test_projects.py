"""Build brief 18, phase A (rules v2.25, Project context): the registry (`config/projects.json`, `sr project
add|list|remove`), the handoff file and the router's one block in it. Every value here is fake; every folder
is a temp folder. The real registry, the real home folder and any real `never_register` folder are never touched
(brief 25: the folder is a setting; here a fake one in this test's own settings file)."""
import builtins
import json
import os
from pathlib import Path

import pytest

from router import __main__ as cli
from router import log, projects

from helpers import JEV_OK, set_local

START, END = projects.START, projects.END


def off_limits_folder(tmp_path):
    """The fake never_register folder every test here works beside (brief 25, decision 5)."""
    return tmp_path / "home" / "Projects" / "off-limits"


@pytest.fixture
def registry(tmp_path, monkeypatch):
    path = tmp_path / "config" / "projects.json"
    monkeypatch.setattr(projects, "REGISTRY_PATH", path)
    set_local(never_register=[str(off_limits_folder(tmp_path))])
    return path


@pytest.fixture
def folder(tmp_path):
    f = tmp_path / "proj"
    f.mkdir()
    return f


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _entry(n, body="Produced: nothing written\nStatus: fine\nNext: more"):
    return f"### #{n} · 2026-10-16 · writing · claude\n{body}"


# ---------- the registry ----------

def test_a_missing_registry_reads_as_empty(registry):
    assert projects.read_registry() == {}


def test_add_registers_the_folder_and_creates_the_handoff_with_an_empty_block(registry, folder):
    done = projects.add("demo", str(folder))
    assert json.loads(registry.read_text()) == {"demo": str(folder.resolve())}
    text = (folder / "HANDOFF.md").read_text()
    assert text == f"{START}\n{END}\n"
    assert done.created is True and done.lines == 2 and done.block_start == 1


def test_add_requires_the_folder_to_exist(registry, tmp_path):
    with pytest.raises(projects.ProjectError, match="is not a folder"):
        projects.add("demo", str(tmp_path / "missing"))
    assert not registry.exists()


def test_add_refuses_a_bad_name(registry, folder):
    for bad in ("Demo", "my project", "a_b", "", "x/y"):
        with pytest.raises(projects.ProjectError, match="letters, digits and -"):
            projects.add(bad, str(folder))
    assert not registry.exists() and not (folder / "HANDOFF.md").exists()


def test_add_refuses_a_never_register_folder_by_name(registry, folder):
    with pytest.raises(projects.ProjectError, match="off-limits is never registered"):
        projects.add("off-limits", str(folder))
    assert not registry.exists() and not (folder / "HANDOFF.md").exists()


def test_add_refuses_a_never_register_folder_by_path_and_by_symlink(registry, tmp_path):
    off_limits = off_limits_folder(tmp_path)
    (off_limits / "inner").mkdir(parents=True)
    with pytest.raises(projects.ProjectError, match="off-limits is never registered"):
        projects.add("other", str(off_limits))
    with pytest.raises(projects.ProjectError, match="off-limits is never registered"):
        projects.add("other", str(off_limits / "inner"))
    link = tmp_path / "alias"
    link.symlink_to(off_limits)
    with pytest.raises(projects.ProjectError, match="off-limits is never registered"):
        projects.add("other", str(link))
    assert not registry.exists() and not (off_limits / "HANDOFF.md").exists()


def test_add_refuses_a_name_already_registered(registry, folder, tmp_path):
    projects.add("demo", str(folder))
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(projects.ProjectError, match="demo is already registered"):
        projects.add("demo", str(other))
    assert json.loads(registry.read_text()) == {"demo": str(folder.resolve())}


def test_add_appends_the_markers_to_a_file_without_them_and_changes_nothing_else(registry, folder):
    before = "# My notes\n\nThe owner's own lines.\n"
    (folder / "HANDOFF.md").write_text(before)
    done = projects.add("demo", str(folder))
    assert (folder / "HANDOFF.md").read_text() == before + f"\n{START}\n{END}\n"
    assert done.created is False and done.marked is True and done.block_start == 5


def test_add_appends_the_markers_after_a_file_with_no_final_newline(registry, folder):
    (folder / "HANDOFF.md").write_text("notes")
    projects.add("demo", str(folder))
    assert (folder / "HANDOFF.md").read_text() == f"notes\n\n{START}\n{END}\n"


def test_add_keeps_a_file_that_already_has_the_block_byte_for_byte(registry, folder):
    before = f"notes\n\n{START}\n\n{_entry(3)}\n\n{END}\n\ntrailing\n"
    (folder / "HANDOFF.md").write_bytes(before.encode())
    done = projects.add("demo", str(folder))
    assert (folder / "HANDOFF.md").read_bytes() == before.encode()
    assert done.created is False and done.marked is False


def test_add_reads_and_writes_only_the_handoff_in_the_project_folder(registry, folder, monkeypatch):
    (folder / ".env").write_text("JEV_API_KEY=FAKE\n")
    (folder / "README.md").write_text("x\n")
    opened = []
    real_open = builtins.open

    def spy(file, *args, **kwargs):
        opened.append(Path(str(file)))
        return real_open(file, *args, **kwargs)
    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.setattr(Path, "open", lambda self, *a, **k: spy(self, *a, **k))
    projects.add("demo", str(folder))
    inside = [p for p in opened if folder.resolve() in p.resolve().parents or p.resolve() == folder.resolve()]
    assert inside and all(p.name == "HANDOFF.md" for p in inside), inside


def test_remove_drops_the_entry_and_touches_no_file(registry, folder):
    projects.add("demo", str(folder))
    stamp = (folder / "HANDOFF.md").stat().st_mtime_ns
    projects.remove("demo")
    assert json.loads(registry.read_text()) == {}
    assert (folder / "HANDOFF.md").stat().st_mtime_ns == stamp


def test_remove_refuses_an_unknown_name(registry, folder):
    projects.add("demo", str(folder))
    with pytest.raises(projects.ProjectError, match="no project other"):
        projects.remove("other")


def test_a_registry_that_is_not_json_is_refused_by_name(registry):
    registry.parent.mkdir(parents=True)
    registry.write_text("{not json")
    with pytest.raises(projects.ProjectError, match="projects.json could not be read"):
        projects.read_registry()


# ---------- the block writer ----------

def test_the_first_entry_goes_between_the_markers(registry, folder):
    projects.add("demo", str(folder))
    lines, start = projects.write_entry(folder, _entry(1))
    assert (folder / "HANDOFF.md").read_text() == f"{START}\n\n{_entry(1)}\n\n{END}\n"
    assert lines == 8 and start == 1  # start, blank, 4 entry lines, blank, end


def test_entries_are_newest_first_with_one_blank_line_between(registry, folder):
    projects.add("demo", str(folder))
    projects.write_entry(folder, _entry(1))
    projects.write_entry(folder, _entry(2))
    assert (folder / "HANDOFF.md").read_text() == f"{START}\n\n{_entry(2)}\n\n{_entry(1)}\n\n{END}\n"


def test_the_ninth_entry_drops_the_oldest(registry, folder):
    projects.add("demo", str(folder))
    for n in range(1, 10):
        projects.write_entry(folder, _entry(n))
    text = (folder / "HANDOFF.md").read_text()
    kept = projects.entries_of(text)
    assert [e.splitlines()[0] for e in kept] == [_entry(n).splitlines()[0] for n in range(9, 1, -1)]
    assert "### #1 " not in text and len(kept) == projects.KEEP == 8


def test_nothing_outside_the_block_changes_crlf_included(registry, folder):
    head = "# Notes\r\n\r\nThe owner's line é \r\n\r\n"
    tail = "\r\n\r\nafter the block\r\n"
    before = (head + START + "\r\n" + END + tail).encode("utf-8")
    (folder / "HANDOFF.md").write_bytes(before)
    projects.add("demo", str(folder))
    assert (folder / "HANDOFF.md").read_bytes() == before
    projects.write_entry(folder, _entry(1))
    after = (folder / "HANDOFF.md").read_bytes()
    assert after.startswith(head.encode()) and after.endswith(tail.encode())
    middle = after[len(head.encode()):-len(tail.encode())].decode()
    assert middle == START + "\r\n\r\n" + _entry(1).replace("\n", "\r\n") + "\r\n\r\n" + END
    assert b"\n" not in after.replace(b"\r\n", b"")


def test_a_second_write_keeps_the_text_outside_the_block_and_the_newline_style(registry, folder):
    head, tail = "head\n", "\ntail\n"
    (folder / "HANDOFF.md").write_text(head + START + "\n" + END + tail)
    projects.add("demo", str(folder))
    projects.write_entry(folder, _entry(1))
    projects.write_entry(folder, _entry(2))
    text = (folder / "HANDOFF.md").read_text()
    assert text == head + f"{START}\n\n{_entry(2)}\n\n{_entry(1)}\n\n{END}" + tail


def test_a_file_whose_markers_are_missing_or_reversed_is_refused_and_not_written(registry, folder):
    projects.add("demo", str(folder))
    path = folder / "HANDOFF.md"
    path.write_text(f"{END}\n{START}\n")
    with pytest.raises(projects.ProjectError, match="markers"):
        projects.write_entry(folder, _entry(1))
    assert path.read_text() == f"{END}\n{START}\n"
    path.write_text("no block at all\n")
    with pytest.raises(projects.ProjectError, match="markers"):
        projects.write_entry(folder, _entry(1))
    assert path.read_text() == "no block at all\n"


def test_write_entry_reports_the_line_count_and_block_start_after_the_write(registry, folder):
    (folder / "HANDOFF.md").write_text("one\ntwo\nthree\n")
    projects.add("demo", str(folder))
    lines, start = projects.write_entry(folder, _entry(1))
    assert start == 5 and lines == 12  # three lines, a blank, start, blank, 4 entry lines, blank, end


def test_the_size_warning_names_the_count_and_the_block_start():
    assert projects.size_warning(301, 290) == ("HANDOFF.md is 301 lines (the router warns past 300); the router's "
                                              "block starts at line 290. Trim the part above the block.")
    assert projects.size_warning(300, 1) is None


def test_write_entry_opens_only_the_handoff(registry, folder, monkeypatch):
    (folder / ".env").write_text("JEV_API_KEY=FAKE\n")
    projects.add("demo", str(folder))
    opened = []
    real_open = builtins.open

    def spy(file, *args, **kwargs):
        opened.append(Path(str(file)))
        return real_open(file, *args, **kwargs)
    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.setattr(Path, "open", lambda self, *a, **k: spy(self, *a, **k))
    projects.write_entry(folder, _entry(1))
    inside = [p for p in opened if folder.resolve() in p.resolve().parents]
    assert inside and all(p.name == "HANDOFF.md" for p in inside), inside


# ---------- sr project ----------

def _project(conn, words):
    lines = []
    code = cli.cmd_project(words, conn=conn, out=lines.append)
    return code, "\n".join(lines)


def test_sr_project_add_prints_the_line_count(registry, folder, conn):
    code, out = _project(conn, ["add", "demo", str(folder)])
    assert code == 0
    assert out == f"Registered demo at {folder.resolve()}. HANDOFF.md created with an empty block (2 lines)."


def test_sr_project_add_on_a_file_without_markers_says_so(registry, folder, conn):
    (folder / "HANDOFF.md").write_text("notes\n")
    code, out = _project(conn, ["add", "demo", str(folder)])
    assert code == 0
    assert out == f"Registered demo at {folder.resolve()}. HANDOFF.md given the router's block at its end (4 lines)."


def test_sr_project_add_on_a_long_file_warns(registry, folder, conn):
    (folder / "HANDOFF.md").write_text("x\n" * 320)
    code, out = _project(conn, ["add", "demo", str(folder)])
    assert code == 0
    assert "HANDOFF.md given the router's block at its end (323 lines)." in out
    assert "HANDOFF.md is 323 lines (the router warns past 300); the router's block starts at line 322." in out


def test_sr_project_add_refusals_print_the_reason_and_write_nothing(registry, folder, conn, tmp_path):
    code, out = _project(conn, ["add", "off-limits", str(folder)])
    assert code == 2 and out == "Refused: off-limits is never registered. Nothing was changed."
    code, out = _project(conn, ["add", "demo", str(tmp_path / "nope")])
    assert code == 2 and out.startswith("Refused: ") and "is not a folder" in out
    code, out = _project(conn, ["add", "demo"])
    assert code == 2 and "add <name> <path>" in out
    assert not registry.exists()


def test_sr_project_list_prints_name_path_lines_and_open_task(registry, folder, conn, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    _project(conn, ["add", "demo", str(folder)])
    _project(conn, ["add", "second", str(other)])
    log.add_task(conn, "sr-1", "t", "cli", JEV_OK, project="demo")
    code, out = _project(conn, ["list"])
    assert code == 0
    assert out.splitlines() == [
        "Projects (config/projects.json):",
        f"  demo  {folder.resolve()}  HANDOFF.md 2 lines  open: task #1 (queued)",
        f"  second  {other.resolve()}  HANDOFF.md 2 lines",
    ]


def test_sr_project_list_on_an_empty_registry(registry, conn):
    code, out = _project(conn, ["list"])
    assert code == 0 and out == "No projects registered. sr project add <name> <path> registers one."


def test_sr_project_list_says_when_a_handoff_file_is_missing(registry, folder, conn):
    _project(conn, ["add", "demo", str(folder)])
    (folder / "HANDOFF.md").unlink()
    code, out = _project(conn, ["list"])
    assert code == 0 and f"  demo  {folder.resolve()}  HANDOFF.md missing" in out


def test_sr_project_remove_drops_the_entry_only(registry, folder, conn):
    _project(conn, ["add", "demo", str(folder)])
    code, out = _project(conn, ["remove", "demo"])
    assert code == 0 and out == "Removed demo from the registry. Its HANDOFF.md is untouched."
    assert json.loads(registry.read_text()) == {} and (folder / "HANDOFF.md").exists()
    code, out = _project(conn, ["remove", "demo"])
    assert code == 2 and out == "Refused: no project demo. Nothing was changed."


def test_sr_project_needs_a_subcommand(registry, conn):
    code, out = _project(conn, [])
    assert code == 2 and "sr project add|list|remove" in out
    code, out = _project(conn, ["frob"])
    assert code == 2 and "sr project add|list|remove" in out


def test_main_routes_sr_project(registry, folder, monkeypatch, tmp_path, capsys):
    assert cli.main(["project", "add", "demo", str(folder)], platform="darwin") == 0
    assert "Registered demo" in capsys.readouterr().out
    assert cli.main(["project", "list"], platform="darwin") == 0
    assert "  demo  " in capsys.readouterr().out
