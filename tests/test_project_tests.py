"""Build brief 28 (decision 17): `sr project tests <name> -- "<command>"` stores a project's test command as words in a
gitignored file beside the registry (never in the project), `--clear` removes it, and the name alone shows it. The words
are split as a shell would split them and never run through one; a `.venv/` or `venv/` first word must be in the
project folder. Nothing here runs a test."""
import json
from pathlib import Path

import pytest

from router import __main__ as cli
from router import projects, safety


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "projects.json")
    monkeypatch.setattr(projects, "TESTS_PATH", tmp_path / "project_tests.json")
    folder = tmp_path / "garden"
    folder.mkdir()
    projects.add("garden", folder)
    return folder


def run(argv, capsys):
    code = cli.main(argv, platform="darwin")
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_set_show_and_clear_a_test_command(registry, capsys, tmp_path):
    code, said = run(["project", "tests", "garden", "--", "python3 -m unittest -v"], capsys)
    assert code == 0 and "Tests for garden: python3 -m unittest -v" in said
    assert json.loads((tmp_path / "project_tests.json").read_text()) == {"garden": ["python3", "-m", "unittest", "-v"]}
    assert projects.tests_of("garden") == ["python3", "-m", "unittest", "-v"]
    code, said = run(["project", "tests", "garden"], capsys)
    assert code == 0 and "Tests for garden: python3 -m unittest -v" in said
    code, said = run(["project", "tests", "garden", "--clear"], capsys)
    assert code == 0 and "Cleared the test command of garden" in said and projects.tests_of("garden") is None
    code, said = run(["project", "tests", "garden"], capsys)
    assert code == 0 and "No test command for garden" in said
    assert not any(p.name == "project_tests.json" for p in registry.iterdir())  # never in the project


def test_the_words_are_kept_as_a_shell_would_split_them(registry, capsys):
    code, _ = run(["project", "tests", "garden", "--", "pytest -k 'add and not slow' tests/"], capsys)
    assert code == 0 and projects.tests_of("garden") == ["pytest", "-k", "add and not slow", "tests/"]


@pytest.mark.parametrize("words,why", [
    ("x" * 301, "at most 300"), ("python3 'oops", "can't be split"), ("   ", "empty"),
    (".venv/bin/python -m unittest", ".venv/bin/python is not in the project folder"),
])
def test_a_command_that_cant_be_kept_is_refused_and_nothing_is_written(registry, capsys, tmp_path, words, why):
    code, said = run(["project", "tests", "garden", "--json", "--", words], capsys)
    found = json.loads(said.strip().splitlines()[-1])
    assert code == 2 and found["reason_code"] == "project_refused" and why in found["message"]
    assert not (tmp_path / "project_tests.json").exists()


def test_a_venv_first_word_in_the_project_is_kept(registry, capsys):
    (registry / ".venv" / "bin").mkdir(parents=True)
    (registry / ".venv" / "bin" / "python").write_text("")
    code, _ = run(["project", "tests", "garden", "--", ".venv/bin/python -m pytest"], capsys)
    assert code == 0 and projects.tests_of("garden") == [".venv/bin/python", "-m", "pytest"]


def test_an_unknown_project_and_a_double_answer_are_refused(registry, capsys):
    code, said = run(["project", "tests", "nope", "--", "python3 -m unittest"], capsys)
    assert code == 2 and "no project nope" in said
    code, said = run(["project", "tests", "garden", "--clear", "--", "python3 -m unittest"], capsys)
    assert code == 2 and "Refused" in said


def test_the_json_envelope_names_the_words(registry, capsys):
    code, said = run(["project", "tests", "garden", "--json", "--", "python3 -m unittest"], capsys)
    found = json.loads(said.strip().splitlines()[-1])
    assert code == 0 and found["exit"] == 0 and found["project"] == {"name": "garden", "tests": ["python3", "-m", "unittest"]}


def test_removing_a_project_drops_its_test_command(registry, capsys):
    run(["project", "tests", "garden", "--", "python3 -m unittest"], capsys)
    code, said = run(["project", "remove", "garden"], capsys)
    assert code == 0 and projects.tests_of("garden") is None and "test command" in said


def test_the_tests_file_is_gitignored():
    lines = (safety.REPO_ROOT / ".gitignore").read_text().splitlines()
    assert "config/project_tests.json" in lines
    assert projects.TESTS_NAME == "config/project_tests.json"
