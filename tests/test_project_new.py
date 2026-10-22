"""Build brief 26, A (rules 2.36, Project context, Making a project): `projects.new` and `projects.plan_new`, the dry run.
Every folder is a temp folder, the registry a temp file, the settings this test's own local file; the real home folder,
registry and never_register folders are never touched. A secret- or key-shaped value is built at run time from pieces."""
import json
import os
import secrets as random_secrets

import pytest

from router import projects, settings

from helpers import set_local

START, END = projects.START, projects.END
NOTES = "What it is: a seed tray planner.\nDecided: no paid tools."


def off_limits_folder(tmp_path):
    return tmp_path / "home" / "Projects" / "off-limits"


@pytest.fixture
def registry(tmp_path, monkeypatch):
    path = tmp_path / "config" / "projects.json"
    monkeypatch.setattr(projects, "REGISTRY_PATH", path)
    set_local(never_register=[str(off_limits_folder(tmp_path))])
    return path


@pytest.fixture
def root(tmp_path, registry):
    r = tmp_path / "projects"
    r.mkdir()
    return r.resolve()


def tree(*folders):
    """Every path under the folders with its mtime and bytes (a folder: its mtime only), for "nothing written"."""
    found = {}
    for folder in folders:
        if not os.path.lexists(folder):
            continue
        for here, dirs, files in os.walk(folder):
            for name in dirs + files:
                p = os.path.join(here, name)
                st = os.lstat(p)
                found[p] = (st.st_mtime_ns, open(p, "rb").read() if os.path.isfile(p) and not os.path.islink(p) else None)
        found[str(folder)] = (os.lstat(folder).st_mtime_ns, None)
    return found


def registry_bytes(registry):
    return registry.read_bytes() if registry.exists() else None


# ---------- making a new folder ----------

def test_new_with_notes_makes_the_folder_the_file_and_the_entry(root, registry):
    made = projects.new("seed-trays", NOTES, root=root)
    folder = root / "seed-trays"
    assert (folder / "HANDOFF.md").read_bytes() == (NOTES + "\n\n" + START + "\n" + END + "\n").encode()
    assert json.loads(registry.read_text()) == {"seed-trays": str(folder)}
    assert (made.did, made.folder, made.lines) == ("created", folder, 5)
    assert sorted(os.listdir(folder)) == ["HANDOFF.md"]  # the one file the router makes there


def test_notes_ending_in_a_newline_get_no_second_one(root, registry):
    projects.new("seed-trays", NOTES + "\n", root=root)
    assert (root / "seed-trays" / "HANDOFF.md").read_text() == NOTES + "\n\n" + START + "\n" + END + "\n"


@pytest.mark.parametrize("notes", [None, ""])
def test_without_notes_the_file_is_the_bytes_add_makes(root, registry, tmp_path, notes):
    made = projects.new("seed-trays", notes, root=root)
    other = tmp_path / "other"
    other.mkdir()
    projects.add("other", str(other))
    assert (root / "seed-trays" / "HANDOFF.md").read_bytes() == (other / "HANDOFF.md").read_bytes() == (
        START + "\n" + END + "\n").encode()
    assert (made.did, made.lines) == ("created", 2)


def test_a_missing_root_is_made_with_its_parents(tmp_path, registry):
    deep = tmp_path / "a" / "b" / "projects"
    made = projects.new("seed-trays", None, root=deep)
    assert (deep / "seed-trays" / "HANDOFF.md").is_file() and made.folder == deep.resolve() / "seed-trays"


# ---------- a folder that is there ----------

def test_an_existing_folder_without_a_handoff_is_registered_as_add_does(root, registry):
    (root / "seed-trays").mkdir()
    made = projects.new("seed-trays", None, root=root)
    assert (root / "seed-trays" / "HANDOFF.md").read_text() == START + "\n" + END + "\n"
    assert (made.did, made.created) == ("registered", True)
    assert json.loads(registry.read_text()) == {"seed-trays": str(root / "seed-trays")}


def test_an_existing_handoff_gets_the_block_at_its_end_and_keeps_its_bytes(root, registry):
    (root / "seed-trays").mkdir()
    (root / "seed-trays" / "HANDOFF.md").write_bytes(b"# Mine\n")
    made = projects.new("seed-trays", None, root=root)
    assert (root / "seed-trays" / "HANDOFF.md").read_bytes() == b"# Mine\n\n" + (START + "\n" + END + "\n").encode()
    assert (made.did, made.marked, made.lines) == ("registered", True, 4)


def test_an_existing_handoff_with_a_block_is_kept_byte_for_byte(root, registry):
    (root / "seed-trays").mkdir()
    handoff = root / "seed-trays" / "HANDOFF.md"
    handoff.write_bytes(b"# Mine\r\n" + (START + "\r\n" + END + "\r\n").encode())
    before = tree(root)
    made = projects.new("seed-trays", None, root=root)
    assert tree(root) == before and (made.did, made.created, made.marked) == ("registered", False, False)


def test_notes_with_an_existing_folder_are_refused_and_nothing_changes(root, registry):
    (root / "seed-trays").mkdir()
    (root / "seed-trays" / "HANDOFF.md").write_bytes(b"# Mine\n")
    before, reg = tree(root), registry_bytes(registry)
    with pytest.raises(projects.ProjectError) as e:
        projects.new("seed-trays", NOTES, root=root)
    assert "sr project add" not in str(e.value) and "yours to edit" in str(e.value)
    assert (tree(root), registry_bytes(registry)) == (before, reg)


def test_a_file_at_the_path_is_refused(root, registry):
    (root / "seed-trays").write_text("not a folder\n")
    before = tree(root)
    with pytest.raises(projects.ProjectError, match="not a folder"):
        projects.new("seed-trays", None, root=root)
    assert tree(root) == before and not registry.exists()


# ---------- refusals ----------

@pytest.mark.parametrize("name", ["Seed", "seed_trays", "seed.trays", "a/b", "..", ".", "", "seed trays", None])
def test_the_name_rule_is_bad_name(root, registry, name):
    with pytest.raises(projects.BadName):
        projects.new(name, None, root=root)
    assert os.listdir(root) == [] and not registry.exists()
    assert projects.BadName.code == "bad_name" and projects.ProjectError.code == "project_refused"


def test_never_register_by_name(root, registry):
    with pytest.raises(projects.ProjectError, match="off-limits is never registered"):
        projects.new("off-limits", None, root=root)
    assert os.listdir(root) == []


def test_never_register_by_path(root, registry, tmp_path):
    # the folder is <root>/<name>, so a path match that is not a name match is the root itself, reached by its path
    # or through a link to it
    set_local(never_register=[str(root)])
    with pytest.raises(projects.ProjectError, match="never registered"):
        projects.new("seed-trays", None, root=root)
    (tmp_path / "via-link").symlink_to(root)
    with pytest.raises(projects.ProjectError, match="never registered"):
        projects.new("seed-trays", None, root=tmp_path / "via-link")
    assert os.listdir(root) == []


def test_a_root_inside_a_never_register_folder_refuses_every_new(tmp_path, registry):
    inside = off_limits_folder(tmp_path) / "sub"
    for name in ("seed-trays", "anything"):
        with pytest.raises(projects.ProjectError, match="never registered"):
            projects.new(name, None, root=inside)
    assert not os.path.lexists(inside) and not os.path.lexists(off_limits_folder(tmp_path))


def test_a_name_already_registered_is_refused(root, registry, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    projects.add("seed-trays", str(other))
    reg = registry_bytes(registry)
    with pytest.raises(projects.ProjectError, match="already registered"):
        projects.new("seed-trays", None, root=root)
    assert os.listdir(root) == [] and registry_bytes(registry) == reg


@pytest.mark.parametrize("inside", [False, True])
def test_a_link_at_the_name_is_refused_and_points_to_add(root, registry, tmp_path, inside):
    target = root / "real-one" if inside else tmp_path / "elsewhere"
    target.mkdir()
    (root / "seed-trays").symlink_to(target)
    before = tree(root, target)
    with pytest.raises(projects.ProjectError) as e:
        projects.new("seed-trays", None, root=root)
    assert "is a link" in str(e.value) and "sr project add seed-trays <path>" in str(e.value)
    assert tree(root, target) == before and not registry.exists()


def test_notes_up_to_4000_characters_and_no_more(root, registry):
    with pytest.raises(projects.ProjectError, match="4,001 characters"):
        projects.new("long-one", "x" * 4001, root=root)
    assert os.listdir(root) == []
    projects.new("long-one", "x" * 4000, root=root)
    assert (root / "long-one" / "HANDOFF.md").read_text().startswith("x" * 4000 + "\n\n")


@pytest.mark.parametrize("line", [START, END, "  " + START + "  ", "\t" + END])
def test_a_notes_line_that_is_a_marker_is_refused_by_number(root, registry, line):
    with pytest.raises(projects.ProjectError, match="line 3 of the notes is the router's marker"):
        projects.new("seed-trays", "one\ntwo\n" + line + "\nfour", root=root)
    assert os.listdir(root) == []


def test_a_marker_inside_a_line_is_just_text(root, registry):
    projects.new("seed-trays", "the block starts at " + START + " in the file", root=root)
    text = (root / "seed-trays" / "HANDOFF.md").read_text()
    assert projects.has_block(text) and projects.block_start(text) == 3


def test_notes_holding_an_env_value_are_refused_by_line_and_never_echoed(root, registry):
    value = "fake" + random_secrets.token_hex(6)  # 16 characters, built now
    notes = "What it is: a test.\nLogin: " + value + "\nDecided: nothing."
    with pytest.raises(projects.ProjectError) as e:
        projects.new("seed-trays", notes, secrets=[value], root=root)
    assert "line 2" in str(e.value) and value not in str(e.value) and "Login" not in str(e.value)
    assert os.listdir(root) == [] and not registry.exists()


def test_notes_a_key_scan_matches_are_refused_by_line_and_never_echoed(root, registry):
    value = "to" + "ken: " + random_secrets.token_hex(8)  # a key shape, built now
    notes = "What it is: a test.\nStack: Python.\n" + value
    with pytest.raises(projects.ProjectError) as e:
        projects.new("seed-trays", notes, root=root)
    assert "line 3" in str(e.value) and value.split()[1] not in str(e.value)
    assert os.listdir(root) == [] and not registry.exists()


def test_a_short_env_value_is_not_a_secret(root, registry):
    projects.new("seed-trays", "Seven: abcdefg", secrets=[], root=root)  # env_secrets keeps 8+ only; nothing passed
    assert (root / "seed-trays").is_dir()


# ---------- projects_root from the settings ----------

def test_projects_root_absent_is_tilde_projects(tmp_path, registry, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    plan = projects.plan_new("seed-trays")
    assert (plan.would, plan.folder) == ("create", (tmp_path / "home").resolve() / "Projects" / "seed-trays")
    assert not (tmp_path / "home" / "Projects").exists()  # a plan makes nothing


def test_projects_root_with_tilde_is_expanded(tmp_path, registry, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    set_local(projects_root="~/Desktop/garden-projects")
    made = projects.new("seed-trays", None)
    assert made.folder == (tmp_path / "home").resolve() / "Desktop" / "garden-projects" / "seed-trays"
    assert projects.tilde(made.folder) == "~/Desktop/garden-projects/seed-trays"


def test_a_projects_root_that_is_not_absolute_refuses_every_new(tmp_path, registry, monkeypatch):
    monkeypatch.chdir(tmp_path)
    set_local(projects_root="Projects")
    for name in ("seed-trays", "other"):
        plan = projects.plan_new(name)
        assert (plan.would, plan.folder) == ("refused", None) and "projects_root in settings" in plan.why
        with pytest.raises(projects.ProjectError, match="projects_root in settings"):
            projects.new(name, None)
    assert not (tmp_path / "Projects").exists()


def test_a_root_that_is_a_file_is_refused(tmp_path, registry):
    (tmp_path / "rootfile").write_text("x")
    with pytest.raises(projects.ProjectError, match="not a folder"):
        projects.new("seed-trays", None, root=tmp_path / "rootfile")


# ---------- the dry run ----------

def _scenarios(tmp_path, root):
    (root / "has-folder").mkdir()
    (root / "has-folder" / "HANDOFF.md").write_bytes(b"# Mine\nline two\n")
    (root / "a-file").write_text("x")
    other = tmp_path / "other"
    other.mkdir()
    projects.add("taken", str(other))
    return [("brand-new", None, "create", None), ("has-folder", None, "register", None),
            ("Bad Name", None, "refused", "bad_name"), ("taken", None, "refused", "project_refused"),
            ("off-limits", None, "refused", "project_refused"), ("a-file", None, "refused", "project_refused"),
            ("brand-new", "x" * 4001, "refused", "project_refused")]


def test_the_dry_run_writes_nothing_and_answers_rightly(tmp_path, root, registry):
    cases = _scenarios(tmp_path, root)
    before, reg = tree(root, tmp_path / "other"), registry_bytes(registry)
    for name, notes, would, code in cases:
        plan = projects.plan_new(name, notes, root=root)
        assert (plan.would, plan.code) == (would, code), name
        assert (plan.why is None) == (would != "refused"), name
    assert (tree(root, tmp_path / "other"), registry_bytes(registry)) == (before, reg)


def test_the_dry_run_describes_the_handoff(tmp_path, root, registry):
    _scenarios(tmp_path, root)
    assert projects.plan_new("brand-new", root=root).handoff == {"exists": False, "lines": None, "has_block": False}
    plan = projects.plan_new("has-folder", root=root)
    assert (plan.handoff, plan.folder) == ({"exists": True, "lines": 2, "has_block": False}, root / "has-folder")
    (root / "no-file").mkdir()
    assert projects.plan_new("no-file", root=root).handoff == {"exists": False, "lines": None, "has_block": False}


def test_the_dry_run_of_a_missing_root_makes_nothing(tmp_path, registry):
    plan = projects.plan_new("seed-trays", root=tmp_path / "not-yet")
    assert plan.would == "create" and not (tmp_path / "not-yet").exists()


# ---------- a fault after the folder is made ----------

def test_a_fault_writing_the_handoff_leaves_the_folder_and_says_so(root, registry, monkeypatch):
    def broken(path, data):
        raise OSError("disk full")
    monkeypatch.setattr(projects, "_create_handoff", broken)
    with pytest.raises(projects.Partial) as e:
        projects.new("seed-trays", NOTES, root=root)
    message = str(e.value)
    assert projects.Partial.code == "project_partial"
    assert (root / "seed-trays").is_dir() and not (root / "seed-trays" / "HANDOFF.md").exists()
    assert "seed-trays" in message and "HANDOFF.md is not there" in message and "not registered" in message
    assert "Nothing was deleted" in message and "disk full" not in message and not registry.exists()


def test_a_fault_writing_the_registry_leaves_the_folder_and_its_file(root, registry, monkeypatch):
    def broken(data, path=None):
        raise OSError("read-only")
    monkeypatch.setattr(projects, "_write_registry", broken)
    with pytest.raises(projects.Partial) as e:
        projects.new("seed-trays", NOTES, root=root)
    assert (root / "seed-trays" / "HANDOFF.md").read_text().startswith(NOTES)
    assert "HANDOFF.md is there" in str(e.value) and "not registered" in str(e.value)


def test_a_root_made_on_the_way_is_named_in_a_fault(tmp_path, registry, monkeypatch):
    monkeypatch.setattr(projects, "_create_handoff", lambda path, data: (_ for _ in ()).throw(OSError("x")))
    with pytest.raises(projects.Partial) as e:
        projects.new("seed-trays", None, root=tmp_path / "fresh-root")
    assert "the projects root" in str(e.value) and "(made now)" in str(e.value)


# ---------- the owner's tweak (22 Oct): a taken name names its registered folder with ~ ----------

def test_a_taken_name_answers_with_its_registered_folder_shown_with_tilde(tmp_path, registry, monkeypatch):
    home = (tmp_path / "home").resolve()
    monkeypatch.setenv("HOME", str(home))
    kept = home / "Code" / "seed-trays"
    kept.mkdir(parents=True)
    projects.add("seed-trays", str(kept))
    plan = projects.plan_new("seed-trays", root=tmp_path / "projects")
    assert (plan.would, plan.folder) == ("refused", kept)
    assert "already registered at ~/Code/seed-trays" in plan.why and str(home) not in plan.why
    with pytest.raises(projects.ProjectError) as e:
        projects.new("seed-trays", None, root=tmp_path / "projects")
    assert "~/Code/seed-trays" in str(e.value) and str(home) not in str(e.value)
