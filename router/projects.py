"""Project context (rules v2.25, Project context; build brief 18): the registry in `config/projects.json`,
the project's `HANDOFF.md`, and the router's one block in it.

The router reads one file in a project folder, `HANDOFF.md`, and writes one thing there: the text between
`<!-- sr:start -->` and `<!-- sr:end -->`. Everything outside the markers is the owner's and Claude Code's, kept
byte for byte (newline style included). `write_entry` is the one write path. A folder in the `never_register`
setting (brief 25: config/settings.local.json; the code spells no folder) is never registered, by name or by path. No
agent writes any of this; the router does, and only through here.

Brief 26 (rules 2.36, Making a project): `new` makes `<projects_root>/<name>`, a new `HANDOFF.md` holding the starting
notes above the empty block (the one write outside the block, in a file the router has just made), and the registry
entry; a folder already there is registered as `add` registers it. `plan_new` is its dry run: every check, nothing
written. Nothing here deletes anything.
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path

from router import safety, settings

REGISTRY_PATH = safety.REPO_ROOT / "config" / "projects.json"   # gitignored: the owner's machine's paths
REGISTRY_NAME = "config/projects.json"
NAME = re.compile(r"[a-z0-9-]+")
HANDOFF = "HANDOFF.md"
START = "<!-- sr:start -->"
END = "<!-- sr:end -->"
KEEP = 8            # entries the block holds, newest first
WARN_LINES = 300    # past this many lines the router warns after a write (and at `sr project add`)
ENTRY_HEAD = re.compile(r"^### #\d+ ")


class ProjectError(safety.SafeError):
    """A refusal or a failure with no secret in its text: names, paths and counts only."""
    code = "project_refused"


class BadName(ProjectError):
    """The name rule (brief 26: `new` answers it as `bad_name`; `add` still says project_refused)."""
    code = "bad_name"


class Partial(ProjectError):
    """Brief 26 (decision 7): a write failed after the folder was made. What exists is left and named."""
    code = "project_partial"


@dataclass(frozen=True)
class Added:
    """What `add` did: the folder as registered, the file's line count, whether the file was created, whether the
    markers were appended, and the line the block starts on."""
    path: Path
    lines: int
    created: bool
    marked: bool
    block_start: int


# ---------- the registry ----------

def read_registry(path=None):
    """{name: absolute path}. A missing file is an empty registry."""
    path = Path(path or REGISTRY_PATH)
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return {}
    except OSError:
        raise ProjectError(f"{REGISTRY_NAME} could not be read") from None
    try:
        data = json.loads(raw)
    except ValueError:
        raise ProjectError(f"{REGISTRY_NAME} could not be read: it is not JSON") from None
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise ProjectError(f"{REGISTRY_NAME} could not be read: it is not a map of names to paths")
    return data


def _write_registry(data, path=None):
    path = Path(path or REGISTRY_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def never_registered(folder, name, entries):
    """Why `name` at `folder` may not be registered, or None (brief 25, decision 5): `name` is an entry's folder name, or
    `folder` (None: not looked at yet) is a never_register entry or lies under one. Pure: the caller resolves the paths;
    nothing is read."""
    for entry in entries:
        if name == entry.name or (folder is not None and (folder == entry or entry in folder.parents)):
            return f"{entry.name} is never registered"
    return None


def _never_register():
    """The never_register folders, resolved where they can be (a link names its target). A malformed setting refuses
    every add: the protection is never dropped by a typo."""
    entries, why = settings.never_register()
    if why:
        raise ProjectError(f"{why}: nothing is registered until it is fixed")
    resolved = []
    for entry in entries:
        try:
            resolved.append(entry.resolve())
        except OSError:
            resolved.append(entry)
    return resolved


def check_name(name):
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise BadName("a project name is lower case letters, digits and - only")


def add(name, folder, *, path=None):
    """Register `name` at `folder` (which must exist) and make sure its HANDOFF.md has the router's block: the file
    is created with an empty block when missing, given the markers at its end when it has none, and left byte for
    byte when it has them. Refuses a never_register folder by name and by resolved path, and a name already registered."""
    check_name(name)
    entries = _never_register()
    refused = never_registered(None, name, entries)  # by name first, before the folder is even looked at
    if refused:
        raise ProjectError(refused)
    folder = Path(folder).expanduser()
    try:
        folder = folder.resolve()
    except OSError:
        raise ProjectError(f"{safety.one_line(str(folder))} could not be resolved") from None
    refused = never_registered(folder, name, entries)
    if refused:
        raise ProjectError(refused)
    if not folder.is_dir():
        raise ProjectError(f"{safety.one_line(str(folder))} is not a folder")
    registry = read_registry(path)
    if name in registry:
        raise ProjectError(f"{name} is already registered at {safety.one_line(registry[name])}; remove it first")
    handoff = folder / HANDOFF
    created = marked = False
    if not handoff.exists():
        _write_text(handoff, f"{START}\n{END}\n")
        created = True
    else:
        text = _read_text(handoff)
        if not has_block(text):
            nl = _newline(text)
            joint = "" if not text else nl if text.endswith("\n") else nl + nl  # a blank line before the block
            _write_text(handoff, text + joint + START + nl + END + nl)
            marked = True
    text = _read_text(handoff)
    registry[name] = str(folder)
    _write_registry(registry, path)
    return Added(folder, line_count(text), created, marked, block_start(text))


def remove(name, *, path=None):
    """Drop the entry. No file is touched."""
    registry = read_registry(path)
    if name not in registry:
        raise ProjectError(f"no project {safety.one_line(str(name))}")
    del registry[name]
    _write_registry(registry, path)


def folder_of(name, *, path=None):
    """The registered folder of `name`, or None."""
    found = read_registry(path).get(name)
    return Path(found) if found else None


# ---------- making a project (brief 26) ----------

NOTES_LIMIT = 4000


@dataclass(frozen=True)
class Plan:
    """What `new` would do: `would` is create, register or refused; `folder` the resolved `<root>/<name>` (None when no
    folder can be named: a bad name or an unusable root); `handoff` its state; `code` and `why` on a refusal."""
    would: str
    name: object
    folder: Path = None
    handoff: dict = None
    code: str = None
    why: str = None
    root: Path = None


@dataclass(frozen=True)
class Made:
    """What `new` did: `did` is created or registered; the folder, the file's line count, and (for a folder that was
    there) whether `add` created the file or appended the markers."""
    did: str
    folder: Path
    lines: int
    created: bool = False
    marked: bool = False


def tilde(path):
    """`path` with the home folder shown as `~` (the page and the prose show folders this way)."""
    path, home = Path(path), Path.home()
    for base in dict.fromkeys((home, home.resolve())):
        if path == base or base in path.parents:
            return "~" + ("/" + str(path.relative_to(base)) if path != base else "")
    return str(path)


def _notes_problem(notes, secrets):
    """Why the starting notes are refused, or None: past NOTES_LIMIT, a line that is one of the router's markers (the
    test `_marker_lines` uses), or a line the redactor would change or the key scan matches (the two checks a handoff
    passes before every call, context.load). Names the line; never the text."""
    if len(notes) > NOTES_LIMIT:
        return f"the starting notes are {len(notes):,} characters; at most {NOTES_LIMIT:,}"
    lines = notes.splitlines()
    for n, line in enumerate(lines, 1):
        if line.strip() in (START, END):
            return f"line {n} of the notes is the router's marker; it goes only in the router's block"
    for n, line in enumerate(lines, 1):
        if safety.redact(line, secrets) != line:
            return f"line {n} of the notes holds a value from .env"
    if safety.redact(notes, secrets) != notes:  # a secret across lines (none is, but never let one through)
        return "the notes hold a value from .env"
    found = safety.key_like(notes)
    if found is not None:
        return f"line {found} of the notes looks like it holds a key"
    return None


def _handoff_state(folder):
    handoff = handoff_path(folder)
    if not handoff.exists():
        return {"exists": False, "lines": None, "has_block": False}
    text = _read_text(handoff)
    return {"exists": True, "lines": line_count(text), "has_block": has_block(text)}


def plan_new(name, notes=None, *, secrets=(), root=None, path=None):
    """Every check `new` makes, in its order; reads the registry, the settings and the folder and writes nothing.
    `root` None reads projects_root from the settings. Never raises a ProjectError: a refusal is the Plan's answer."""
    try:
        check_name(name)
    except BadName as e:
        return Plan("refused", name, code=e.code, why=str(e))
    try:
        entries = _never_register()
        refused = never_registered(None, name, entries)
        if refused:
            raise ProjectError(refused)
        if root is None:
            root, why = settings.projects_root()
            if why:
                raise ProjectError(f"{why}: nothing is made until it is fixed")
        try:
            root = Path(root).expanduser().resolve()
        except OSError:
            raise ProjectError(f"the projects root {safety.one_line(str(root))} could not be resolved") from None
        for entry in entries:
            if root == entry or entry in root.parents:
                raise ProjectError(f"the projects root {safety.one_line(tilde(root))} is inside {entry.name}, which is "
                                   "never registered")
        if root.exists() and not root.is_dir():
            raise ProjectError(f"the projects root {safety.one_line(tilde(root))} is not a folder")
        folder = root / name
    except ProjectError as e:
        return Plan("refused", name, code=e.code, why=str(e))
    try:
        if folder.is_symlink():
            raise ProjectError(f"{name} in the projects root is a link; a folder kept elsewhere is registered with "
                               f"sr project add {name} <path>")
        refused = never_registered(folder, name, entries)
        if refused:
            raise ProjectError(refused)
        registry = read_registry(path)
        if name in registry:  # the owner (22 Oct): where it is registered, shown with ~, so the page prints no home path
            folder = Path(registry[name])
            raise ProjectError(f"{name} is already registered at {safety.one_line(tilde(folder))}; remove it first")
        if folder.exists() and not folder.is_dir():
            raise ProjectError(f"{safety.one_line(tilde(folder))} is there and is not a folder")
        if folder.is_dir():
            if notes:
                raise ProjectError(f"{safety.one_line(tilde(folder))} is there already, so its {HANDOFF} is yours to "
                                   "edit: starting notes go only in a file the router makes")
            return Plan("register", name, folder, _handoff_state(folder), root=root)
        problem = _notes_problem(notes, secrets) if notes else None
        if problem:
            raise ProjectError(problem)
        return Plan("create", name, folder, {"exists": False, "lines": None, "has_block": False}, root=root)
    except ProjectError as e:
        return Plan("refused", name, folder, code=e.code, why=str(e), root=root)


def _create_handoff(handoff, data):
    """Exclusive create: a file that appeared at the path is never overwritten (FileExistsError)."""
    with open(handoff, "xb") as f:
        f.write(data)


def _partial(step, root, made_root, folder, name, path):
    """The Partial for a write that failed at `step`: what exists now, read from the disk and the registry."""
    shown = [f"the projects root {tilde(root)} (made now)"] if made_root else []
    if folder.is_dir():
        shown.append(f"the folder {tilde(folder)}")
        shown.append(f"{HANDOFF} is there" if handoff_path(folder).exists() else f"{HANDOFF} is not there")
    try:
        registered = name in read_registry(path)
    except ProjectError:
        registered = False
    shown.append(f"{name} is registered" if registered else f"{name} is not registered")
    return Partial(f"{step}. What exists now: {', '.join(shown)}. Nothing was deleted")


def new(name, notes=None, *, secrets=(), root=None, path=None):
    """Make the project (brief 26, decision 7): every check first (`plan_new`); then the root if missing (with its
    parents), the folder (no parents), HANDOFF.md by exclusive create (the notes byte for byte, a newline added if
    missing, one blank line, then the two marker lines; no notes: the bytes `add` makes), then the registry entry through
    `add`. A folder already there goes to `add` as it is. Raises the plan's refusal (BadName or ProjectError, nothing
    written), or Partial when a write fails after the folder is made."""
    plan = plan_new(name, notes, secrets=secrets, root=root, path=path)
    if plan.would == "refused":
        raise (BadName if plan.code == BadName.code else ProjectError)(plan.why)
    if plan.would == "register":
        done = add(name, str(plan.folder), path=path)
        return Made("registered", done.path, done.lines, done.created, done.marked)
    root, folder = plan.root, plan.folder
    made_root = False
    if not root.exists():
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise ProjectError(f"the projects root {safety.one_line(tilde(root))} could not be made") from None
        made_root = True
    try:
        folder.mkdir()
    except FileExistsError:
        if made_root:
            raise _partial(f"{tilde(folder)} appeared while it was being made", root, True, folder, name, path) from None
        raise ProjectError(f"{safety.one_line(tilde(folder))} appeared while it was being made") from None
    except OSError:
        if made_root:
            raise _partial(f"the folder {tilde(folder)} could not be made", root, True, folder, name, path) from None
        raise ProjectError(f"the folder {safety.one_line(tilde(folder))} could not be made") from None
    body = f"{START}\n{END}\n"
    if notes:
        body = notes + ("" if notes.endswith("\n") else "\n") + "\n" + body
    try:
        _create_handoff(handoff_path(folder), body.encode("utf-8"))
    except OSError:
        raise _partial(f"{HANDOFF} could not be written", root, made_root, folder, name, path) from None
    try:
        done = add(name, str(folder), path=path)
    except (ProjectError, OSError):
        raise _partial("the registry entry could not be written", root, made_root, folder, name, path) from None
    return Made("created", done.path, done.lines)


# ---------- the handoff file ----------

def handoff_path(folder):
    return Path(folder) / HANDOFF


def _read_text(handoff):
    try:
        return Path(handoff).read_bytes().decode("utf-8")
    except FileNotFoundError:
        raise ProjectError(f"{HANDOFF} is missing from {safety.one_line(str(Path(handoff).parent))}") from None
    except (OSError, UnicodeDecodeError):
        raise ProjectError(f"{HANDOFF} in {safety.one_line(str(Path(handoff).parent))} could not be read") from None


def _write_text(handoff, text):
    try:
        Path(handoff).write_bytes(text.encode("utf-8"))
    except OSError:
        raise ProjectError(f"{HANDOFF} in {safety.one_line(str(Path(handoff).parent))} could not be written") from None


def read_handoff(folder):
    """The whole file, as text. The one read the router makes in a project folder."""
    return _read_text(handoff_path(folder))


def _newline(text):
    return "\r\n" if "\r\n" in text else "\n"


def line_count(text):
    return len(text.splitlines())


def _marker_lines(text):
    """(index of the START line, index of the END line) in text.splitlines(), or (None, None)."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == START]
    ends = [i for i, line in enumerate(lines) if line.strip() == END]
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        return None, None
    return starts[0], ends[0]


def has_block(text):
    return _marker_lines(text)[0] is not None


def block_start(text):
    """The 1-based line the router's block starts on, or None."""
    at = _marker_lines(text)[0]
    return at + 1 if at is not None else None


def split_block(text):
    """(before, inside, after, newline): the text up to and including the START line, the lines between the
    markers, the text from the END line on. ProjectError without exactly one block."""
    start, end = _marker_lines(text)
    if start is None:
        raise ProjectError(f"{HANDOFF} has no router block: its markers are missing or out of order")
    nl = _newline(text)
    lines = text.splitlines(keepends=True)
    before = "".join(lines[:start + 1])
    inside = [line.rstrip("\r\n") for line in lines[start + 1:end]]
    after = "".join(lines[end:])
    return before, inside, after, nl


def entries_of(text):
    """The entries in the router's block, newest first, each as its lines joined by \\n. [] with no block."""
    start, end = _marker_lines(text)
    if start is None:
        return []
    lines = text.splitlines()[start + 1:end]
    found, current = [], None
    for line in lines:
        if ENTRY_HEAD.match(line):
            if current is not None:
                found.append(current)
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        found.append(current)
    return ["\n".join(e).strip("\n") for e in found if "\n".join(e).strip()]


def render_block(entries, nl="\n"):
    """The lines between the markers for these entries (newest first): a blank line, each entry, a blank line."""
    if not entries:
        return ""
    body = (nl + nl).join(e.replace("\n", nl) for e in entries)
    return nl + body + nl + nl


def write_entry(folder, entry):
    """The one write the router makes in a project folder: read HANDOFF.md, put `entry` at the top of the block,
    keep the newest KEEP entries, write back with nothing outside the markers changed. Returns (the file's line
    count after, the line the block starts on)."""
    handoff = handoff_path(folder)
    text = _read_text(handoff)
    before, _, after, nl = split_block(text)
    entries = [entry.strip("\n")] + entries_of(text)
    new = before + render_block(entries[:KEEP], nl) + after
    if not before.endswith(nl):  # the START line was the file's last line, without a newline
        new = before + nl + render_block(entries[:KEEP], nl) + after
    _write_text(handoff, new)
    return line_count(new), block_start(new)


def size_warning(lines, start):
    """The warning when the file is past WARN_LINES, or None."""
    if lines <= WARN_LINES:
        return None
    return (f"{HANDOFF} is {lines} lines (the router warns past {WARN_LINES}); the router's block starts at line "
            f"{start}. Trim the part above the block.")


# ---------- what the owner sees ----------

def listing(registry, open_by_name):
    """The `sr project list` lines. `open_by_name` maps a name to its open task row (or None)."""
    if not registry:
        return ["No projects registered. sr project add <name> <path> registers one."]
    lines = [f"Projects ({REGISTRY_NAME}):"]
    for name in sorted(registry):
        folder = Path(registry[name])
        try:
            count = f"{HANDOFF} {line_count(read_handoff(folder))} lines"
        except ProjectError:
            count = f"{HANDOFF} missing"
        line = f"  {name}  {safety.one_line(str(folder))}  {count}"
        row = open_by_name.get(name)
        if row is not None:
            line += f"  open: task #{row['n']} ({row['status']})"
        lines.append(line)
    return lines
