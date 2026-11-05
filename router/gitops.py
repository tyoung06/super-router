"""Git, as the router runs it on a project (rules 2.40, Project files; build brief 28, decisions 1, 11, 12, 14, 15 and 16).

Every git command goes through `run`: an argument list, never a shell, with an environment that keeps the owner's own
git settings (their name and email, their default branch) but none of the `GIT_*` names that would point git at another
repository, index or work tree. The router's commits are made without ever touching the owner's index or any file but
the paths it names: a temporary index (`GIT_INDEX_FILE`), `hash-object -w`, `write-tree`, `commit-tree`, then
`update-ref` with the old value, which moves the branch only if nobody moved it meanwhile (Phase 0, item 7). No hook
runs (`core.hooksPath=/dev/null`). Nothing here resets, rebases, amends, forces or collects garbage, ever.
"""
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from router import safety

GIT = "git"
TIMEOUT = 120
NO_HOOKS = ("-c", "core.hooksPath=/dev/null")
ZERO = "0" * 40
# Phase 0 (decision 11): the identity of a router commit when the project's git has no name or email. `.invalid` is a
# top-level domain reserved never to exist (RFC 2606), so it can't be anybody's address.
ROUTER_NAME = "Super Router"
ROUTER_EMAIL = "super-router@localhost.invalid"
# Names a test (or the owner's shell) may set that keep git away from the owner's own settings; every other GIT_* name
# is dropped, so nothing can point a command at another repository.
KEPT = ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM")


class GitError(safety.SafeError):
    """A git command that failed or a repository state the router refuses: what, never a file's contents."""


def installed(which=shutil.which):
    return which(GIT) is not None


def version(run=subprocess.run):
    """`git --version`'s number and build (`2.50.1 (Apple Git-155)`), or None when git isn't installed or won't answer."""
    if not installed():
        return None
    try:
        proc = run([GIT, "--version"], capture_output=True, text=True, timeout=30, env=environment())
    except (OSError, subprocess.SubprocessError):
        return None
    words = (proc.stdout or "").strip()
    return words.removeprefix("git version ").strip() or None if proc.returncode == 0 else None


def environment(extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k in KEPT}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"})
    env.update(extra or {})
    return env


def run(args, *, cwd=None, extra=None, input=None, check=True, timeout=TIMEOUT):
    """One git command (bytes in, bytes out). GitError when it fails and `check` is set. No hook ever runs: a router command
    in a project (update-ref's reference-transaction, update-index's post-index-change, a commit's) runs with
    `core.hooksPath=/dev/null` (decision 11)."""
    argv = [GIT, *NO_HOOKS, *[os.fsdecode(a) if isinstance(a, bytes) else str(a) for a in args]]
    try:
        proc = subprocess.run(argv, cwd=None if cwd is None else str(cwd), env=environment(extra), input=input,
                              capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise GitError(f"git {argv[1] if len(argv) > 1 else ''} took longer than {timeout} s") from None
    except OSError as e:
        raise GitError(f"git could not start ({type(e).__name__})") from None
    if check and proc.returncode != 0:
        said = os.fsdecode(proc.stderr or b"").strip().splitlines()
        raise GitError(f"git {_verb(args)} failed: {safety.one_line(said[-1] if said else 'no message')[:200]}")
    return proc


def _verb(args):
    words = [str(a) for a in args]
    i = 0
    while i < len(words) and words[i] in ("-C", "-c", "--git-dir", "--work-tree"):
        i += 2
    return words[i] if i < len(words) else "?"


def out(args, **kw):
    return run(args, **kw).stdout


def text(args, **kw):
    return os.fsdecode(out(args, **kw)).strip()


# ---------- a project's repository (decision 1) ----------

@dataclass(frozen=True)
class Repo:
    folder: Path
    git: bool              # the folder is a git repository's top level
    branch: object = None  # the branch it is on, or None (detached, or no git)
    head: object = None    # the full id of its newest commit, or None (no commit yet)
    why: object = None     # why file mode can't run on it for a git reason, or None


def common_dir(folder):
    """The repository's common git folder (the same for a repository and all its worktrees), resolved, or None."""
    proc = run(["-C", folder, "rev-parse", "--path-format=absolute", "--git-common-dir"], check=False)
    if proc.returncode != 0:
        return None
    try:
        return Path(os.fsdecode(proc.stdout).strip()).resolve()
    except OSError:
        return None


OWN_FOLDER = "this is the router's own folder"


def inside_router(folder, router_root=None):
    """True when `folder` is the router's own folder or inside it, by path alone (no git asked)."""
    folder, root = Path(folder).resolve(), Path(router_root or safety.REPO_ROOT).resolve()
    return folder == root or root in folder.parents


def own_folder(folder, router_root=None):
    """True when `folder` is the router's own folder, inside it, or one of its worktrees (decision 1, the owner's D4)."""
    if inside_router(folder, router_root):
        return True
    mine = common_dir(router_root or safety.REPO_ROOT)
    return mine is not None and common_dir(folder) == mine


def inspect(folder, *, router_root=None):
    """What file mode needs to know about a project folder's git, read only (no command here writes)."""
    folder = Path(folder).resolve()
    if inside_router(folder, router_root):
        return Repo(folder, False, why=OWN_FOLDER)
    if not installed():
        return Repo(folder, False, why="git isn't installed")
    proc = run(["-C", folder, "rev-parse", "--show-toplevel"], check=False)
    if proc.returncode != 0:
        return Repo(folder, False, why="no git yet: Turn on undo")
    try:
        top = Path(os.fsdecode(proc.stdout).strip()).resolve()
    except OSError:
        return Repo(folder, False, why="its git folder could not be read")
    if own_folder(folder, router_root):
        return Repo(folder, top == folder, why=OWN_FOLDER)
    if top != folder:
        return Repo(folder, False, why="it is inside another git repository, not at its top level")
    head = run(["-C", folder, "rev-parse", "-q", "--verify", "HEAD^{commit}"], check=False)
    branch = run(["-C", folder, "symbolic-ref", "-q", "--short", "HEAD"], check=False)
    name = os.fsdecode(branch.stdout).strip() if branch.returncode == 0 else None
    if head.returncode != 0:
        return Repo(folder, True, name, None, why="no commit yet: Turn on undo")
    sha = os.fsdecode(head.stdout).strip()
    if name is None:
        return Repo(folder, True, None, sha, why="it is on a detached head")
    return Repo(folder, True, name, sha)


def short(sha):
    return (sha or "")[:7]


def identity(folder):
    """(name, email) for a router commit in `folder`: the project's git name and email (its own, the owner's global or the
    system's, as git reads them), or the router's identity when either is missing (decision 11)."""
    name = run(["-C", folder, "config", "--get", "user.name"], check=False)
    email = run(["-C", folder, "config", "--get", "user.email"], check=False)
    name = os.fsdecode(name.stdout).strip() if name.returncode == 0 else ""
    email = os.fsdecode(email.stdout).strip() if email.returncode == 0 else ""
    if not name or not email:
        return ROUTER_NAME, ROUTER_EMAIL
    return name, email


def identity_env(name, email):
    return {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email}


# ---------- reading a tree ----------

@dataclass(frozen=True)
class Entry:
    mode: str
    kind: str     # blob or commit (a submodule)
    sha: str
    size: object  # bytes, or None for a submodule
    path: str     # relative, with / between folders

    @property
    def link(self):
        return self.mode == "120000"


def tree(git_args, commit):
    """Every entry of `commit`'s tree, recursively, as Entry. `git_args` names the repository (`-C <folder>` or
    `--git-dir <dir>`)."""
    raw = out([*git_args, "ls-tree", "-r", "-z", "--long", "--full-tree", commit])
    found = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        head, _, path = record.partition(b"\t")
        mode, kind, sha, size = head.decode().split(None, 3)
        found.append(Entry(mode, kind, sha, None if size.strip() == "-" else int(size), os.fsdecode(path)))
    return found


class Blobs:
    """One `git cat-file --batch` for many objects: read(sha) returns the object's bytes."""

    def __init__(self, git_args, extra=None, popen=None):
        popen = popen or subprocess.Popen
        self.proc = popen([GIT, *NO_HOOKS, *map(str, git_args), "cat-file", "--batch"], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment(extra))

    def read(self, sha):
        self.proc.stdin.write(sha.encode() + b"\n")
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().split()
        if len(header) != 3:
            raise GitError(f"git cat-file could not read object {sha[:12]}")
        size = int(header[2])
        data = self.proc.stdout.read(size)
        self.proc.stdout.read(1)
        return data

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ---------- commits made without touching the owner's index or other files ----------

def hash_file(folder, data):
    """Write `data` as a blob in the project's objects, exactly (no filters), and return its id."""
    return text(["-C", folder, "hash-object", "-w", "--no-filters", "--stdin"], input=data)


def commit_paths(folder, parent, changes, message, ident):
    """Build a commit on `parent` (None for a first commit) whose tree is the parent's with `changes` applied, in a
    temporary index that is removed after: {path: (mode, blob id)} for a new or changed file, {path: None} for a
    deleted one. Returns the commit's id. Writes objects only: no ref, no index of the owner's, no file in the folder."""
    with tempfile.TemporaryDirectory(prefix="sr-index-") as temp:
        index = {"GIT_INDEX_FILE": str(Path(temp) / "index")}
        if parent is not None:
            run(["-C", folder, "read-tree", parent], extra=index)
        adds = [f"{mode} {sha}\t{path}".encode() for path, value in sorted(changes.items()) if value
                for mode, sha in [value]]
        removes = [path for path, value in sorted(changes.items()) if not value]
        if adds:
            run(["-C", folder, "update-index", "--add", "--index-info"], extra=index,
                input=b"\n".join(adds) + b"\n")
        if removes:
            run(["-C", folder, "update-index", "--force-remove", "-z", "--stdin"], extra=index,
                input=b"\0".join(os.fsencode(p) for p in removes) + b"\0")
        tree_id = text(["-C", folder, "write-tree"], extra=index)
    args = ["-C", folder, "commit-tree", tree_id, "-m", message]
    if parent is not None:
        args += ["-p", parent]
    return text(args, extra=identity_env(*ident))


def move_branch(folder, branch, new, old, message="super-router"):
    """Point `branch` at `new` only if it still points at `old` (ZERO: only if it does not exist yet). GitError when it
    moved meanwhile: nothing was changed. `message` is the reflog's line: brief 29.1 (issue 10) passes the commit's
    subject."""
    run(["-C", folder, "update-ref", "-m", message, f"refs/heads/{branch}", new, old or ZERO])


def changed_since(folder, base, head, paths):
    """The paths among `paths` whose contents differ between two commits."""
    if base == head or not paths:
        return []
    raw = out(["-C", folder, "diff", "--no-renames", "--no-ext-diff", "--no-textconv", "-z", "--name-only", base, head,
               "--", *paths])
    return [os.fsdecode(p) for p in raw.split(b"\0") if p]


def dirty(folder, paths):
    """The paths among `paths` with anything uncommitted in the folder: staged, changed, untracked or ignored."""
    if not paths:
        return []
    raw = out(["-C", folder, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored=matching",
               "--no-renames", "--", *paths])
    found = []
    for record in raw.split(b"\0"):
        if len(record) > 3:
            found.append(os.fsdecode(record[3:]))
    return found


def blob_at(folder, commit, path):
    """(mode, blob id) of `path` in `commit`, or None when it isn't there."""
    raw = out(["-C", folder, "ls-tree", "-z", "--full-tree", commit, "--", path])
    for record in raw.split(b"\0"):
        if not record:
            continue
        head, _, name = record.partition(b"\t")
        mode, kind, sha = head.decode().split()
        if os.fsdecode(name) == path and kind == "blob":
            return mode, sha
    return None


def set_index(folder, entries):
    """Bring the owner's index in line with a commit the router made, for these paths only: {path: (mode, blob id)}
    or {path: None} for a removed one. Other entries, staged changes included, stay as they are."""
    adds = [f"{mode} {sha}\t{path}".encode() for path, value in sorted(entries.items()) if value for mode, sha in [value]]
    removes = [path for path, value in sorted(entries.items()) if not value]
    if adds:
        run(["-C", folder, "update-index", "--add", "--index-info"], input=b"\n".join(adds) + b"\n")
    if removes:
        run(["-C", folder, "update-index", "--force-remove", "-z", "--stdin"],
            input=b"\0".join(os.fsencode(p) for p in removes) + b"\0")
    run(["-C", folder, "update-index", "-q", "--refresh"], check=False)
