"""Build brief 31 (decisions 8 and 9): `sr project secrets <name>` lists the names in the project's `.env`, each set or
empty, never a value; `--set <NAME>` takes the value on stdin, never as an argument, and writes the file whole (a temp
file, then a rename), mode 600, every other line byte for byte, a new name at the end, so `dotenv_values` reads back
exactly what was sent; `--remove <NAME>` takes a name out. Under the project's lock. Every value here is fake, built at
run time."""
import io
import json
import os
import subprocess
from pathlib import Path

import pytest
from dotenv import dotenv_values

from router import __main__ as cli
from router import locks, projects, projsecrets

FAKE = "carrot-" + "seed-" + "0123456789"


@pytest.fixture
def garden(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "projects.json")
    monkeypatch.setattr(projects, "TESTS_PATH", tmp_path / "project_tests.json")
    folder = tmp_path / "garden"
    folder.mkdir()
    projects.add("garden", folder)
    return folder


def run(argv, capsys, stdin=None, monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin if stdin is not None else ""))
    code = cli.main(argv, platform="darwin")
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def git(folder, *args):
    subprocess.run(["git", "-C", str(folder), *args], check=True, capture_output=True)


# ---------- the list (decision 8) ----------

def test_the_list_names_each_set_or_empty_and_never_a_value(garden, capsys):
    (garden / ".env").write_text(f"# the garden's keys\nDEMO_KEY={FAKE}\n\nEMPTY=\nexport SPACED='a b'\n")
    found = projsecrets.names(garden)
    assert found == [{"name": "DEMO_KEY", "set": True}, {"name": "EMPTY", "set": False}, {"name": "SPACED", "set": True}]
    code, out, err = run(["project", "secrets", "garden", "--json"], capsys)
    assert code == 0 and FAKE not in out and FAKE not in err
    assert json.loads(out.strip().splitlines()[-1])["project"]["secrets"] == found
    code, out, err = run(["project", "secrets", "garden"], capsys)
    assert code == 0 and "DEMO_KEY (set)" in out and "EMPTY (empty)" in out and FAKE not in out


def test_no_env_lists_none(garden, capsys):
    code, out, err = run(["project", "secrets", "garden", "--json"], capsys)
    assert code == 0 and json.loads(out.strip().splitlines()[-1])["project"]["secrets"] == []


# ---------- --set on stdin, the round trip, every other line byte for byte (decision 8) ----------

SHAPES = ["plain", "with spaces inside", "has # a hash", "it's quoted", 'say "hi"', "a=b=c", "cost $5 or $VAR",
          "back\\slash and \\n", "both ' and \"", "tab\there", " leading and trailing ", "", "x" * 4096]


@pytest.mark.parametrize("value", SHAPES)
def test_every_shape_reads_back_exactly(garden, value):
    projsecrets.set_value("garden", "DEMO_KEY", value)
    assert dotenv_values(garden / ".env") == {"DEMO_KEY": value}
    assert oct((garden / ".env").stat().st_mode & 0o777) == "0o600"


def test_a_new_name_goes_at_the_end_and_every_other_line_is_kept_byte_for_byte(garden):
    before = "# keys for the garden\r\nFIRST=one\n\n  # an indented comment\nexport SECOND=\"two\"\nLAST='three'"
    (garden / ".env").write_bytes(before.encode())
    projsecrets.set_value("garden", "DEMO_KEY", FAKE)
    after = (garden / ".env").read_bytes().decode()
    assert after == before + "\nDEMO_KEY='" + FAKE + "'\n"
    projsecrets.set_value("garden", "SECOND", "changed")
    text = (garden / ".env").read_text()
    assert text.splitlines()[:4] == ["# keys for the garden", "FIRST=one", "", "  # an indented comment"]
    assert dotenv_values(garden / ".env") == {"FIRST": "one", "SECOND": "changed", "LAST": "three", "DEMO_KEY": FAKE}


def test_a_name_twice_keeps_its_first_place_and_drops_the_rest(garden):
    (garden / ".env").write_text("A=1\nDEMO_KEY=old\nB=2\nDEMO_KEY=older\n")
    projsecrets.set_value("garden", "DEMO_KEY", "new")
    assert (garden / ".env").read_text() == "A=1\nDEMO_KEY='new'\nB=2\n"


def test_sr_project_secrets_set_takes_the_value_on_stdin_and_never_prints_it(garden, capsys, monkeypatch):
    code, out, err = run(["project", "secrets", "garden", "--set", "DEMO_KEY", "--json"], capsys, stdin=FAKE + "\n",
                         monkeypatch=monkeypatch)
    assert code == 0, err
    assert dotenv_values(garden / ".env") == {"DEMO_KEY": FAKE}  # the trailing newline dropped
    assert FAKE not in out and FAKE not in err
    doc = json.loads(out.strip().splitlines()[-1])
    assert doc["project"]["secret"] == {"name": "DEMO_KEY", "created": True, "characters": len(FAKE)}


def test_an_argument_holding_a_value_is_refused_by_the_parser(garden, capsys, monkeypatch):
    code, out, err = run(["project", "secrets", "garden", "--set", "DEMO_KEY", FAKE], capsys, stdin="", monkeypatch=monkeypatch)
    assert code == 2 and not (garden / ".env").exists()
    assert FAKE not in out + err  # the refusal never echoes what was typed


def test_the_whole_file_write_leaves_the_old_file_when_it_fails_part_way(garden, monkeypatch):
    (garden / ".env").write_text("FIRST=one\n")
    monkeypatch.setattr(projsecrets.os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(projsecrets.Refused, match="could not be written"):
        projsecrets.set_value("garden", "DEMO_KEY", FAKE)
    assert (garden / ".env").read_text() == "FIRST=one\n" and not list(garden.glob(".env.*"))


def test_remove_takes_every_line_of_the_name_out(garden, capsys):
    (garden / ".env").write_text("A=1\nDEMO_KEY=x\nB=2\nDEMO_KEY=y\n")
    code, out, err = run(["project", "secrets", "garden", "--remove", "DEMO_KEY", "--json"], capsys)
    assert code == 0 and (garden / ".env").read_text() == "A=1\nB=2\n"
    code, out, err = run(["project", "secrets", "garden", "--remove", "DEMO_KEY", "--json"], capsys)
    assert code == 2 and "no DEMO_KEY" in json.loads(err.strip().splitlines()[-1])["message"]


# ---------- refusals, nothing written (decision 8) ----------

@pytest.mark.parametrize("key", ["bad-name", "lower", "9STARTS", "", "A B"])
def test_a_bad_name_is_refused(garden, key):
    with pytest.raises(projsecrets.Refused, match="a name is"):
        projsecrets.set_value("garden", key, "x")
    assert not (garden / ".env").exists()


@pytest.mark.parametrize("value, why", [("a\x00b", "NUL"), ("one\ntwo", "one line"), ("one\rtwo", "one line"),
                                        ("x" * 4097, "4,096"), ("${HOME}/x", "reads it back exactly")])
def test_a_value_that_cant_be_kept_is_refused(garden, value, why):
    with pytest.raises(projsecrets.Refused, match=why):
        projsecrets.set_value("garden", "DEMO_KEY", value)
    assert not (garden / ".env").exists()


def test_a_link_or_a_folder_at_env_is_refused(garden, tmp_path):
    (tmp_path / "elsewhere").write_text("X=1\n")
    (garden / ".env").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(projsecrets.Refused, match="a link"):
        projsecrets.set_value("garden", "DEMO_KEY", "x")
    (garden / ".env").unlink()
    (garden / ".env").mkdir()
    with pytest.raises(projsecrets.Refused, match="not a plain file"):
        projsecrets.set_value("garden", "DEMO_KEY", "x")
    assert (tmp_path / "elsewhere").read_text() == "X=1\n"


def test_with_git_an_env_git_tracks_or_doesnt_ignore_is_refused(real_git, garden):
    git(garden, "init", "-q")
    with pytest.raises(projsecrets.Refused, match="doesn't ignore its .env"):
        projsecrets.set_value("garden", "DEMO_KEY", "x")
    assert not (garden / ".env").exists()
    (garden / ".gitignore").write_text(".env\n")
    projsecrets.set_value("garden", "DEMO_KEY", "x")  # ignored: written
    git(garden, "add", "-f", ".env")
    with pytest.raises(projsecrets.Refused, match="git tracks its .env"):
        projsecrets.set_value("garden", "DEMO_KEY", "y")
    assert dotenv_values(garden / ".env") == {"DEMO_KEY": "x"}


def test_the_routers_own_folder_is_refused(garden, monkeypatch):
    monkeypatch.setattr(projects, "folder_of", lambda name: Path(cli.__file__).resolve().parent.parent)
    with pytest.raises(projsecrets.Refused, match="the router's own .env"):
        projsecrets.set_value("garden", "DEMO_KEY", "x")


def test_another_write_holding_the_project_is_refused_at_once(garden, tmp_path, monkeypatch):
    from router import runs
    monkeypatch.setattr(runs, "FOLDER", tmp_path / "run")
    (tmp_path / "run").mkdir()
    with locks.held("project-garden", folder=tmp_path / "run", wait=False):
        with pytest.raises(projsecrets.Refused, match="another write"):
            projsecrets.set_value("garden", "DEMO_KEY", "x")
    assert not (garden / ".env").exists()


def test_status_gives_how_many_names_never_which(garden, capsys):
    (garden / ".env").write_text(f"DEMO_KEY={FAKE}\nOTHER=\n")
    assert projsecrets.count(garden) == 2
    code, out, err = run(["project", "list", "--json"], capsys)
    found = [p for p in json.loads(out)["projects"] if p["name"] == "garden"][0]
    assert found["secrets"] == 2 and "DEMO_KEY" not in out and FAKE not in out
