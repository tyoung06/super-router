"""Build brief 25, A1 (decision 5): the folders `sr project add` never registers are a setting, `never_register` (a list
of paths in config/settings.local.json), not a folder spelled in the code. Refused by path (the folder, anything under
it, a link to it) and by name (a project named like the folder); an empty or missing setting refuses nothing; a
malformed one refuses every add until it is fixed. The tracked settings name no folder. This Mac's own folders are
checked through the pure function only, so no test reads, lists or writes them."""
import json
from pathlib import Path

import pytest

from router import __main__ as cli
from router import log, projects, settings

from tests.helpers import set_local

ROOT = Path(__file__).resolve().parent.parent
MALFORMED = "never_register in settings isn't a list of paths"


def real_never_register(root=ROOT):
    """This Mac's `never_register` from its own config/settings.local.json, read directly (conftest points the router's
    settings at a temp file): (folders, why), or None when the file or the key isn't there."""
    try:
        doc = json.loads((Path(root) / "config" / "settings.local.json").read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or "never_register" not in doc:
        return None
    return settings.never_register(doc)


needs_value = pytest.mark.skipif(real_never_register() is None,
                                 reason="no never_register in this Mac's config/settings.local.json")


@pytest.fixture
def registry(tmp_path, monkeypatch):
    path = tmp_path / "config" / "projects.json"
    monkeypatch.setattr(projects, "REGISTRY_PATH", path)
    return path


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _folder(tmp_path, *parts):
    folder = tmp_path.joinpath(*parts)
    folder.mkdir(parents=True)
    return folder


# ---------- the setting ----------

def test_absent_or_empty_refuses_nothing():
    assert settings.never_register({}) == ([], None)
    assert settings.never_register({"never_register": []}) == ([], None)


def test_paths_are_read_with_the_home_folder_expanded(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    folders, why = settings.never_register({"never_register": ["~/Projects/secret-project", "/srv/else"]})
    assert why is None and folders == [tmp_path / "Projects" / "secret-project", Path("/srv/else")]


@pytest.mark.parametrize("value", ["~/Projects/secret-project", ["~/x", 3], [""], ["Projects/relative"], {"a": "b"}, [None]])
def test_anything_but_a_list_of_absolute_or_home_paths_is_malformed(value):
    assert settings.never_register({"never_register": value}) == (None, MALFORMED)


def test_the_local_file_is_read(tmp_path):
    set_local(never_register=[str(tmp_path / "secret-project")])
    assert settings.never_register() == ([tmp_path / "secret-project"], None)


def test_the_tracked_settings_name_no_folder():
    doc = json.loads((ROOT / "config" / "settings.json").read_text())
    assert doc.get("never_register", []) == []


# ---------- the refusal, pure ----------

def test_the_pure_check_refuses_the_folder_anything_under_it_and_its_name():
    entries = [Path("/u/Projects/secret-project")]
    refused = "secret-project is never registered"
    assert projects.never_registered(Path("/u/Projects/secret-project"), "other", entries) == refused
    assert projects.never_registered(Path("/u/Projects/secret-project/a/b"), "other", entries) == refused
    assert projects.never_registered(Path("/elsewhere/x"), "secret-project", entries) == refused
    assert projects.never_registered(Path("/u/Projects/secret-projects"), "other", entries) is None  # another folder
    assert projects.never_registered(Path("/u/Projects"), "other", entries) is None  # the folder above it
    assert projects.never_registered(Path("/u/Projects/secret-project"), "other", []) is None


# ---------- sr project add ----------

def test_an_empty_setting_refuses_nothing(registry, tmp_path):
    set_local(never_register=[])
    folder = _folder(tmp_path, "home", "Projects", "secret-project")
    assert projects.add("secret-project", str(folder)).created is True


def test_a_missing_setting_refuses_nothing(registry, tmp_path):
    folder = _folder(tmp_path, "secret-project")
    assert projects.add("secret-project", str(folder)).created is True


def test_every_entry_is_refused_by_name_and_by_path(registry, tmp_path):
    one = tmp_path / "home" / "Projects" / "secret-project"
    two = tmp_path / "home" / "Projects" / "private-thing"
    set_local(never_register=[str(one), str(two)])
    elsewhere = _folder(tmp_path, "elsewhere")
    for folder in (one, two):
        folder.mkdir(parents=True)
        with pytest.raises(projects.ProjectError, match=f"^{folder.name} is never registered$"):
            projects.add("demo", str(folder))
        with pytest.raises(projects.ProjectError, match=f"^{folder.name} is never registered$"):
            projects.add(folder.name, str(elsewhere))
        assert not (folder / "HANDOFF.md").exists()
    assert not registry.exists() and not (elsewhere / "HANDOFF.md").exists()


def test_an_entry_given_with_a_tilde_is_refused(registry, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    folder = _folder(tmp_path, "home", "Projects", "secret-project")
    set_local(never_register=["~/Projects/secret-project"])
    with pytest.raises(projects.ProjectError, match="secret-project is never registered"):
        projects.add("demo", str(folder))


def test_an_entry_that_is_a_link_refuses_its_target(registry, tmp_path):
    real = _folder(tmp_path, "real", "secret-project")
    link = tmp_path / "home" / "Projects" / "secret-project"
    link.parent.mkdir(parents=True)
    link.symlink_to(real)
    set_local(never_register=[str(link)])
    with pytest.raises(projects.ProjectError, match="secret-project is never registered"):
        projects.add("demo", str(real))
    assert not (real / "HANDOFF.md").exists()


def test_a_malformed_setting_refuses_every_add_and_writes_nothing(registry, tmp_path):
    set_local(never_register="~/Projects/secret-project")
    folder = _folder(tmp_path, "demo")
    with pytest.raises(projects.ProjectError, match=f"^{MALFORMED}: nothing is registered until it is fixed$"):
        projects.add("demo", str(folder))
    assert not registry.exists() and not (folder / "HANDOFF.md").exists()


def test_sr_project_add_prints_the_refusal_and_changes_nothing(registry, tmp_path, conn):
    set_local(never_register=[str(tmp_path / "home" / "Projects" / "secret-project")])
    folder = _folder(tmp_path, "elsewhere")
    lines = []
    code = cli.cmd_project(["add", "secret-project", str(folder)], conn=conn, out=lines.append)
    assert code == 2 and lines == ["Refused: secret-project is never registered. Nothing was changed."]
    assert not registry.exists()


def test_setup_says_how_and_names_no_real_folder():
    text = (ROOT / "docs" / "SETUP.md").read_text()
    assert "`never_register`" in text and "config/settings.local.json" in text
    real = real_never_register()
    for folder in (real[0] or []) if real else []:
        assert folder.name.lower() not in text.lower()


# ---------- this Mac's own folders: the pure check only, nothing read on disk ----------

@needs_value
def test_this_macs_setting_is_well_formed():
    folders, why = real_never_register()
    assert why is None and folders


@needs_value
def test_this_macs_folders_are_refused_by_path_and_by_name():
    folders, _ = real_never_register()
    for folder in folders or []:
        refused = f"{folder.name} is never registered"
        assert projects.never_registered(folder, "other", folders) == refused
        assert projects.never_registered(folder / "inner", "other", folders) == refused
        assert projects.never_registered(Path("/elsewhere/x"), folder.name, folders) == refused
