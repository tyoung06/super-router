"""Cleanup 1 (2.4): only an exact `SPEC.md` is read as the spec, so a top-level case twin is refused at Save to project and
at files in, naming the right spelling, rather than leaving the Spec section empty with no warning. Fakes only."""
import pytest

from router import __main__ as cli
from router import log, projnotes, spec
from tests.test_landing import state
from tests.test_project_notes import _task, gitted, registry, run  # noqa: F401 (the fixture)
from tests.test_projgit import fake_file


@pytest.mark.parametrize("path", ["spec.md", "Spec.md", "SPEC.MD", "spec.MD", "sPeC.md"])
def test_a_top_level_case_twin_is_refused_naming_the_spelling(path):
    assert "SPEC.md" in projnotes.path_problem(path) and path in projnotes.path_problem(path)


@pytest.mark.parametrize("path", ["SPEC.md", "docs/spec.md", "docs/SPEC.md", "docs/Spec.MD", "spec-notes.md", "spec.txt"])
def test_the_exact_name_and_anything_else_stay_allowed(path):
    assert projnotes.path_problem(path) is None


def test_save_to_project_refuses_it_with_nothing_written(registry, tmp_path, capsys):
    folder = gitted(tmp_path)
    conn = log.init_db(cli.DB_PATH)
    try:
        row = _task(conn)
    finally:
        conn.close()
    before = state(folder)
    code, out = run(["project", "save", "garden", "--task", row["task_id"], "--path", "spec.md"], capsys)
    assert code == 2 and "SPEC.md" in out and state(folder) == before
    code, out = run(["project", "save", "garden", "--task", row["task_id"], "--path", "docs/spec.md"], capsys)
    assert code == 0, out


@pytest.mark.parametrize("name", ["spec.md", "Spec.MD"])
def test_files_in_refuses_it_too(registry, tmp_path, capsys, name):
    folder = gitted(tmp_path)
    before = state(folder)
    source = tmp_path / "src"
    code, out = run(["project", "files", "garden", "--file", fake_file(source, name, "# a spec\n")], capsys)
    assert code == 2 and "SPEC.md" in out and state(folder) == before


def test_files_in_still_takes_the_exact_name(registry, tmp_path, capsys):
    folder = gitted(tmp_path)
    code, out = run(["project", "files", "garden", "--file", fake_file(tmp_path / "src", "SPEC.md", "# a spec\n")], capsys)
    assert code == 0 and spec.path_in(folder) == folder / "SPEC.md", out


def test_the_words_function():
    assert spec.case_twin("SPEC.md") is None and spec.case_twin("notes.md") is None
    assert "only a file named exactly SPEC.md" in spec.case_twin("spec.md")
