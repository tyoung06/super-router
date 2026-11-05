"""The scratch copy of a project (rules 2.40, Project files; build brief 28, decisions 2, 4, 7 and 8).

At intake the router writes the files git tracks at the project's head commit (the task's base) into a new folder
outside the project, under the router's own folder in Application Support (built from the home folder, never spelled):
blob by blob from `git cat-file`, so no attribute, filter or export rule changes a byte, and nothing untracked or
ignored is there. It never carries `.git`, `.env` or `.env.*`, `.claude/`, `.mcp.json`, `.cursor/`, `.codex/`, the top
level's `HANDOFF.md` (the handoff rides in the prompt) or a link (left out, and listed), at any depth and in any case.

The router keeps its own history of the copy in a git folder outside the copy's folder, where no agent can reach it:
`history/<task_id>`, a bare repository whose work tree is the copy, run with no settings of the owner's, no attributes
(`GIT_ATTR_SOURCE` is the empty tree) and no hooks, so a snapshot is the copy's bytes exactly. A snapshot is taken at
intake (`base`) and before every file-mode call (`before-<call_id>`); the change is the difference between `base` and
the copy after a build or fix call. Restoring a snapshot (a resume) is done here, file by file, never by git.
"""
import os
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from router import gitops, safety, settings

DEFAULT_ROOT = Path.home() / "Library" / "Application Support" / "super-router"
ROOT = None  # tests point it at a temp folder; None: `copies_root` in the settings, else DEFAULT_ROOT (brief 29.1, decision 6)
MAX_FILES = 5000
MAX_BYTES = 100 * 1024 * 1024
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_CHANGED = 500
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
EXCLUDED_ANYWHERE = (".git", ".claude", ".mcp.json", ".cursor", ".codex")
HANDOFF = "HANDOFF.md"
_HISTORY_CONFIG = ("-c", "core.autocrlf=false", "-c", "core.safecrlf=false", "-c", "core.symlinks=true",
                   "-c", "core.fileMode=true", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                   "-c", "core.excludesFile=/dev/null", "-c", "gc.auto=0", "-c", "commit.gpgSign=false",
                   "-c", "core.bare=false")
_HISTORY_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_ATTR_SOURCE": EMPTY_TREE,
                **gitops.identity_env("super-router", "copies@localhost.invalid")}


class CopyError(safety.SafeError):
    """The copy can't be made, or the copy holds something it never may: the reason, never a file's contents."""


class TooBig(CopyError):
    """The project is over the copy's limits: the task runs handoff only, with this as its reason."""


def root():
    """The router's own folder for copies and their history: `copies_root` from the settings (brief 29.1, decision 6: a
    live check's worktree sets its own, so nothing it does reaches the real copies), else the Application Support folder.
    A value that isn't an absolute or ~ path is a CopyError, never the default."""
    if ROOT is not None:
        return Path(ROOT)
    found, why = settings.copies_root()
    if why:
        raise CopyError(why)
    return found if found is not None else DEFAULT_ROOT


def copies_root():
    return root() / "copies"


def history_root():
    return root() / "history"


def folder_of(task_id):
    return copies_root() / task_id


def history_of(task_id):
    return history_root() / task_id


def _mkdir_private(path):
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def ensure_roots():
    """The router's folder and its copies and history folders, owner-only."""
    for path in (root(), copies_root(), history_root()):
        _mkdir_private(path)


# ---------- what a copy never carries (decision 2) ----------

def excluded(path):
    """Why `path` (relative, / between folders) is never in a copy, or None. Every part is compared without case: on
    this Mac `.ENV` and `.env` are one file name."""
    parts = PurePosixPath(path).parts
    if not parts:
        return None
    if len(parts) == 1 and parts[0].casefold() == HANDOFF.casefold():
        return HANDOFF
    for part in parts:
        low = part.casefold()
        if low in EXCLUDED_ANYWHERE:
            return part
        if low == ".env" or low.startswith(".env."):
            return ".env"
    return None


def scan(folder):
    """Every path in `folder` a copy never carries, and every link, as (path, why), sorted. Links are never followed."""
    folder = Path(folder)
    found = []
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        here = Path(dirpath)
        for name in sorted(dirnames + filenames):
            full = here / name
            rel = full.relative_to(folder).as_posix()
            why = excluded(rel)
            if full.is_symlink():
                found.append((rel, "a link"))
            elif why:
                found.append((rel, why))
        dirnames[:] = [d for d in dirnames if not (here / d).is_symlink() and not excluded((here / d).relative_to(folder).as_posix())]
    return sorted(set(found))


# ---------- making the copy ----------

@dataclass(frozen=True)
class Made:
    folder: Path
    files: int
    bytes: int
    left_out: list = field(default_factory=list)   # [{"path", "why"}]: links and submodules


def plan(repo_args, commit):
    """(the entries a copy of `commit` holds, the ones left out) with the limits checked before anything is written.
    TooBig over the limits; CopyError when two kept paths differ only in case (one would overwrite the other here)."""
    kept, left_out = [], []
    for entry in gitops.tree(repo_args, commit):
        if entry.kind != "blob":
            left_out.append({"path": entry.path, "why": "submodule"})
            continue
        if entry.link:
            left_out.append({"path": entry.path, "why": "link"})
            continue
        if excluded(entry.path):
            continue
        kept.append(entry)
    if len(kept) > MAX_FILES:
        raise TooBig(f"too big for a copy ({len(kept):,} files)")
    total = sum(e.size or 0 for e in kept)
    if total > MAX_BYTES:
        raise TooBig(f"too big for a copy ({total / 1_000_000:,.0f} MB)")
    seen = {}
    for entry in kept:
        parts = PurePosixPath(entry.path).parts
        for k in range(1, len(parts) + 1):
            key = "/".join(parts[:k]).casefold()
            name = "/".join(parts[:k])
            if seen.setdefault(key, name) != name:
                raise CopyError(f"two tracked paths differ only in case ({safety.one_line(seen[key])}); a copy can't "
                                "hold both on this Mac")
    return kept, left_out


def _write(dest, rel, data, mode):
    path = dest / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    os.chmod(path, 0o755 if mode == "100755" else 0o644)


def export(repo_args, commit, dest, *, blobs=None):
    """Write the copy of `commit` into `dest` (which must not exist), owner-only. Returns Made."""
    kept, left_out = plan(repo_args, commit)
    dest = Path(dest)
    dest.mkdir(mode=0o700)
    os.chmod(dest, 0o700)
    own = blobs is None
    blobs = blobs or gitops.Blobs(repo_args)
    try:
        for entry in kept:
            _write(dest, entry.path, blobs.read(entry.sha), entry.mode)
    finally:
        if own:
            blobs.close()
    return Made(dest, len(kept), sum(e.size or 0 for e in kept), left_out)


def make(task_id, folder, base):
    """The task's copy of the project `folder` at commit `base`, and its private history with the `base` snapshot.
    Nothing is left behind when it fails."""
    ensure_roots()
    dest = folder_of(task_id)
    if dest.exists() or history_of(task_id).exists():
        raise CopyError(f"a copy for {task_id} is there already")
    try:
        made = export(["-C", folder], base, dest)
        _init_history(task_id)
        snapshot(task_id, "base")
    except BaseException:
        remove(task_id)
        raise
    return made


# ---------- the router's own history of the copy ----------

def _h(task_id, args, **kw):
    return gitops.run([*_HISTORY_CONFIG, "--git-dir", history_of(task_id), "--work-tree", folder_of(task_id), *args],
                      extra=_HISTORY_ENV, **kw)


def _init_history(task_id):
    path = history_of(task_id)
    gitops.run(["--git-dir", path, "init", "--template=", "-q"], extra=_HISTORY_ENV)  # a git folder with no work tree
    os.chmod(path, 0o700)
    _h(task_id, ["hash-object", "-t", "tree", "-w", "--stdin"], input=b"")  # the empty tree GIT_ATTR_SOURCE names


def snapshot(task_id, name):
    """Record the copy as it is now under `refs/sr/<name>` (every file, a `.gitignore` in the copy notwithstanding) and
    return the commit's id."""
    _h(task_id, ["add", "--all", "--force", "--", "."])
    tree = os.fsdecode(_h(task_id, ["write-tree"]).stdout).strip()
    previous = _h(task_id, ["rev-parse", "-q", "--verify", "refs/sr/latest"], check=False)
    args = ["commit-tree", tree, "-m", name]
    if previous.returncode == 0:
        args += ["-p", os.fsdecode(previous.stdout).strip()]
    commit = os.fsdecode(_h(task_id, args).stdout).strip()
    _h(task_id, ["update-ref", f"refs/sr/{name}", commit])
    _h(task_id, ["update-ref", "refs/sr/latest", commit])
    return commit


def files_at(task_id, name="base"):
    """Brief 33.1 (decision 3): [(path, size)] of every file snapshot `name` holds, read from the router's history of the
    copy (never the copy's folder, which an agent may have touched)."""
    git_args = [*_HISTORY_CONFIG, "--git-dir", history_of(task_id)]
    return [(e.path, e.size) for e in gitops.tree(git_args, f"refs/sr/{name}") if e.kind == "blob"]


def put_back(task_id, path, name="base"):
    """Brief 33.1 (decision 13): make `path` in the copy what snapshot `name` holds (its bytes, or absent), when it
    differs; a link there is removed, never followed. True when it was changed back."""
    git_args = [*_HISTORY_CONFIG, "--git-dir", history_of(task_id)]
    entry = next((e for e in gitops.tree(git_args, f"refs/sr/{name}") if e.path == path and e.kind == "blob"), None)
    target = folder_of(task_id) / path
    if entry is None:
        if target.is_symlink() or target.exists():
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
            return True
        return False
    with gitops.Blobs(git_args, extra=_HISTORY_ENV) as blobs:
        data = blobs.read(entry.sha)
    if not target.is_symlink() and target.is_file() and target.read_bytes() == data:
        return False
    if target.is_symlink():
        target.unlink()
    _write(folder_of(task_id), path, data, entry.mode)
    return True


def same_tree(task_id, a, b):
    """Brief 29.1 (decision 2): whether snapshots `a` and `b` hold exactly the same files (a call that changed nothing)."""
    trees = [os.fsdecode(_h(task_id, ["rev-parse", f"refs/sr/{name}^{{tree}}"]).stdout).strip() for name in (a, b)]
    return trees[0] == trees[1]


def has_snapshot(task_id, name):
    return _h(task_id, ["rev-parse", "-q", "--verify", f"refs/sr/{name}"], check=False).returncode == 0


def restore(task_id, name):
    """Make the copy hold exactly what snapshot `name` holds, byte for byte: every other file (or link) is removed and
    every file is written again from the history. Links are removed, never followed."""
    folder = folder_of(task_id)
    git_args = [*_HISTORY_CONFIG, "--git-dir", history_of(task_id)]
    entries = {e.path: e for e in gitops.tree(git_args, f"refs/sr/{name}") if e.kind == "blob"}
    for dirpath, dirnames, filenames in os.walk(folder, topdown=False, followlinks=False):
        here = Path(dirpath)
        for name_ in filenames + [d for d in dirnames if (here / d).is_symlink()]:
            full = here / name_
            if full.relative_to(folder).as_posix() not in entries or full.is_symlink():
                full.unlink()
        if here != folder and not any(here.iterdir()):
            here.rmdir()
    with gitops.Blobs(git_args, extra=_HISTORY_ENV) as blobs:
        for path, entry in entries.items():
            target = folder / path
            if target.is_symlink():
                target.unlink()
            _write(folder, path, blobs.read(entry.sha), entry.mode)


def remove(task_id):
    """The copy and its history gone (after Land, Discard or Cancel). True when nothing of either is left."""
    for path in (folder_of(task_id), history_of(task_id)):
        if path.is_symlink():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path, ignore_errors=True)
    return not folder_of(task_id).exists() and not history_of(task_id).exists()


def exists(task_id):
    return folder_of(task_id).is_dir() and history_of(task_id).is_dir()


# ---------- the change (decision 8) ----------

@dataclass(frozen=True)
class Change:
    changed: list          # [{"path", "status" (added, changed, deleted), "plus", "minus"}], by path
    diff: str              # the unified diff, as git writes it (not yet redacted)
    problem: object = None  # why this change fails its call, or None


_STATUS = {"A": "added", "M": "changed", "D": "deleted", "T": "changed"}


def change(task_id, name, since="base"):
    """Snapshot the copy as `name` and compare it with `since` (`base`, or brief 29: a piece's starting snapshot): the
    files added, changed and deleted, with their line counts (None for a binary file), the unified diff, and the problem
    that fails the call, if any: a path the copy never carries, a link, a file over MAX_FILE_BYTES or more than
    MAX_CHANGED files."""
    found = scan(folder_of(task_id))
    commit = snapshot(task_id, name)
    flags = ["diff", "--no-renames", "--no-ext-diff", "--no-textconv", "--no-color", "-z"]
    counts = {}
    raw = _h(task_id, [*flags, "--numstat", f"refs/sr/{since}", commit]).stdout
    for record in raw.split(b"\0"):
        if not record:
            continue
        plus, minus, path = record.split(b"\t", 2)
        counts[os.fsdecode(path)] = (None if plus == b"-" else int(plus), None if minus == b"-" else int(minus))
    raw = _h(task_id, [*flags, "--name-status", f"refs/sr/{since}", commit]).stdout.split(b"\0")
    changed = []
    for i in range(0, len(raw) - 1, 2):
        letter, path = raw[i].decode()[:1], os.fsdecode(raw[i + 1])
        plus, minus = counts.get(path, (None, None))
        changed.append({"path": path, "status": _STATUS.get(letter, "changed"), "plus": plus, "minus": minus})
    changed.sort(key=lambda c: c["path"])
    diff = os.fsdecode(_h(task_id, ["diff", "--no-renames", "--no-ext-diff", "--no-textconv", "--no-color",
                                    f"refs/sr/{since}", commit]).stdout)
    return Change(changed, diff, _problem(task_id, changed, found))


def diff_text(task_id, name, since="base"):
    """The unified diff of snapshot `name` against `since` (`base`, or a piece's starting snapshot), read from the
    history; no new snapshot is taken."""
    return os.fsdecode(_h(task_id, ["diff", "--no-renames", "--no-ext-diff", "--no-textconv", "--no-color",
                                    f"refs/sr/{since}", f"refs/sr/{name}"]).stdout)


def _problem(task_id, changed, found):
    if found:
        path, why = found[0]
        what = "a link" if why == "a link" else f"a path the copy never carries ({why})"
        more = f" and {len(found) - 1} more" if len(found) > 1 else ""
        return f"the copy holds {what}: {safety.one_line(path)}{more}"
    if len(changed) > MAX_CHANGED:
        return f"the change is {len(changed):,} files; at most {MAX_CHANGED}"
    folder = folder_of(task_id)
    for item in changed:
        if item["status"] == "deleted":
            continue
        try:
            size = (folder / item["path"]).lstat().st_size
        except OSError:
            continue
        if size > MAX_FILE_BYTES:
            return f"{safety.one_line(item['path'])} is {size / 1_000_000:,.1f} MB; a changed file is at most 10 MB"
    return None


def problem_before_call(task_id):
    """Decision 7: the check before every file-mode call. A path the copy never carries or a link, which only an agent
    could have made, is the reason the task stops; None when the copy is clean."""
    found = scan(folder_of(task_id))
    if not found:
        return None
    path, why = found[0]
    what = "a link" if why == "a link" else f"a path the copy never carries ({why})"
    return f"the copy holds {what}: {safety.one_line(path)}"


def file_bytes(task_id, path):
    """The bytes of a file in the copy, read without following a link (a link is refused)."""
    full = folder_of(task_id) / path
    info = full.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise CopyError(f"{safety.one_line(path)} in the copy is not a plain file")
    with open(full, "rb") as f:
        return f.read()


def file_mode(task_id, path):
    return "100755" if (folder_of(task_id) / path).lstat().st_mode & 0o111 else "100644"
