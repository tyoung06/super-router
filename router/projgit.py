"""Git for a project, and files into one (rules 2.40, Project files; build brief 28, decisions 14 to 16).

Files in (`sr project files <name> --file <path> …`): each file is copied to the project's top level and one commit holds
them and HANDOFF.md with a one-line entry (`files added: a.csv, b.png`), made as a land is (router/landing.py). Refused,
nothing written: a name already in the folder (never overwritten), a `.env` name or another path a copy never carries, a
file over 50 MB or a link, a text file the redactor or the key scan flags (file and line, never the value), a project
without git. Allowed while a task is open; its Land checks for a clash.

Turn on undo (`sr project git <name>`): for a registered folder without git. The dry run writes nothing: the files git
would track once the `.gitignore` lines are in place, their count and size, the key scan over every text file among them
and the copy's limits. Then the lines are added where missing (the file made if absent, nothing else in it touched), `git
init`, and one first commit of exactly the files the checks passed, HANDOFF.md included, built off any index and set as the
index after. A `.git` with no commit and no index (an interrupted run) is finished, not refused; one with a commit is.
`sr project new` sets up git the same way for the folder it makes, with `.gitignore` and HANDOFF.md alone."""
import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from router import copies, gitops, landing, projects, safety, spec

GITIGNORE = ".gitignore"
GITIGNORE_LINES = (".env", ".env.*", ".venv/", "venv/", "__pycache__/", "node_modules/", ".DS_Store")
FILE_LIMIT = 50 * 1024 * 1024
SHOWN_NAMES = 50


class Refused(landing.Refused):
    def __init__(self, message, code="project_refused"):
        super().__init__(message, code)


def _folder(name):
    try:
        folder = projects.folder_of(name)
    except projects.ProjectError as e:
        raise Refused(str(e)) from None
    if folder is None:
        raise Refused(f"no project {safety.one_line(str(name))}", "project_unknown")
    if not Path(folder).is_dir():
        raise Refused(f"the folder of {name} is not there")
    return Path(folder)


# ---------- files in (decision 14) ----------

def add_files(conn, name, paths, *, secrets=(), journal_dir, date, fault=None):
    """Copy the files into the project's top level as one commit with HANDOFF.md and its one-line entry. Returns
    landing.Done; raises Refused with nothing written."""
    folder = _folder(name)
    landing.recover(conn, folder, journal_dir, out=lambda line: None)
    repo = gitops.inspect(folder)
    if repo.why:
        raise Refused(f"{name} can't take files: {repo.why}")
    if not paths:
        raise Refused("no file was given")
    names, changes, seen = [], {}, set()
    for raw in paths:
        source = Path(raw)
        label = safety.one_line(source.name)
        try:
            info = source.lstat()
        except OSError:
            raise Refused(f"{label} is not there") from None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise Refused(f"{label} is not a plain file")
        if source.name.casefold() in seen:
            raise Refused(f"two files are named {label}")
        seen.add(source.name.casefold())
        why = copies.excluded(source.name)
        if why:
            raise Refused(f"{label} is a name a project's files never take ({why})")
        why = spec.case_twin(source.name)  # Cleanup 1 (2.4): the same gap as Save to project's
        if why:
            raise Refused(why)
        if os.path.lexists(folder / source.name):
            raise Refused(f"{label} is already in the folder; a file is never overwritten")
        if info.st_size > FILE_LIMIT:
            raise Refused(f"{label} is {info.st_size / 1_000_000:,.1f} MB; a file is at most 50 MB")
        data = source.read_bytes()
        problem = landing.scan_text(source.name, data, secrets)
        if problem:
            raise Refused(problem)
        names.append(source.name)
        mode = "100755" if info.st_mode & 0o111 else "100644"
        changes[source.name] = (mode, gitops.hash_file(folder, data))
    entry = f"### {date} · files added: {', '.join(names)}"
    text = projects.with_entry(projects.read_handoff(folder), entry)
    current = gitops.blob_at(folder, repo.head, projects.HANDOFF)
    changes[projects.HANDOFF] = (current[0] if current else "100644", gitops.hash_file(folder, text.encode("utf-8")))
    if any(os.path.lexists(folder / n) for n in names):  # once more, just before the branch moves
        raise Refused("a file appeared in the folder meanwhile; nothing was changed")
    message = "sr: " + landing.cut_at_word(f"files added: {', '.join(names)}", landing.SUBJECT_CHARS)  # issue 6
    commit = landing._commit(folder, repo.branch, repo.head, changes, message, journal_dir, "files", fault=fault)
    return landing.Done(commit, repo.branch, names, folder)


# ---------- Turn on undo (decision 15) ----------

@dataclass(frozen=True)
class Plan:
    would: str                      # turn_on or refused
    name: str
    folder: object = None
    files: list = field(default_factory=list)   # the paths the first commit would hold, sorted
    bytes: int = 0
    gitignore: dict = None          # {"exists": bool, "adds": [lines]}
    code: str = None
    why: str = None

    def as_dict(self):
        return {"would": self.would, "name": self.name,
                "folder": projects.tilde(self.folder) if self.folder is not None else None,
                "files": len(self.files), "bytes": self.bytes, "names": self.files[:SHOWN_NAMES],
                "more": max(0, len(self.files) - SHOWN_NAMES), "gitignore": self.gitignore, "reason_code": self.code}


def missing_lines(text):
    have = {line.strip() for line in (text or "").splitlines()}
    return [line for line in GITIGNORE_LINES if line not in have]


def _gitignore_after(folder):
    path = Path(folder) / GITIGNORE
    text = path.read_text(errors="replace") if path.is_file() else None
    return text, missing_lines(text)


def gitignore_text(text, adds):
    """The .gitignore with the missing lines added at its end, nothing else in it touched."""
    if text is None:
        return "\n".join(adds) + "\n"
    if not adds:
        return text
    joint = "" if (not text or text.endswith("\n")) else "\n"
    return text + joint + "\n".join(adds) + "\n"


def _tracked_after(folder, adds):
    """The files git would track once the lines are in place: its own reading of every .gitignore in the folder, with the
    missing lines given as an excludes file. Run against a git folder made in a temp folder: nothing in the project is
    written."""
    with tempfile.TemporaryDirectory(prefix="sr-git-plan-") as temp:
        git_dir = Path(temp) / "plan.git"
        excludes = Path(temp) / "excludes"
        excludes.write_text("\n".join(adds) + "\n")
        gitops.run(["--git-dir", git_dir, "init", "--template=", "-q"])
        raw = gitops.out(["--git-dir", git_dir, "--work-tree", folder, "-c", f"core.excludesFile={excludes}",
                          "ls-files", "--others", "--exclude-standard", "-z"])
    return sorted({os.fsdecode(p) for p in raw.split(b"\0") if p} | {GITIGNORE})


def plan_git(name, *, secrets=()):
    """The dry run: every check Turn on undo makes, in its order, writing nothing. Never raises for a refusal."""
    try:
        folder = _folder(name)
    except Refused as e:
        return Plan("refused", name, code=e.code, why=str(e))
    if not gitops.installed():
        return Plan("refused", name, folder, code="setup", why="git isn't installed on this Mac (Setup, Git)")
    repo = gitops.inspect(folder)
    if repo.why == gitops.OWN_FOLDER:
        return Plan("refused", name, folder, why="this is the router's own folder")
    if repo.git and repo.head:
        return Plan("refused", name, folder, why=f"{name} already has git")
    if not repo.git and repo.why and "inside another git repository" in repo.why:
        return Plan("refused", name, folder, why="the folder is inside another git repository")
    if repo.git and (Path(folder) / ".git" / "index").exists():
        return Plan("refused", name, folder, why=f"{name} has git with files staged but no commit; commit once yourself")
    text, adds = _gitignore_after(folder)
    try:
        files = _tracked_after(folder, adds)
    except gitops.GitError as e:
        return Plan("refused", name, folder, why=f"its files could not be listed ({e})")
    ignore = {"exists": text is not None, "adds": adds}
    if len(files) > copies.MAX_FILES:
        return Plan("refused", name, folder, files, gitignore=ignore,
                    why=f"{len(files):,} files would be tracked; at most {copies.MAX_FILES:,}")
    total = 0
    for path in files:
        full = folder / path
        if path == GITIGNORE:
            data = gitignore_text(text, adds).encode()
        else:
            try:  # a link is what git keeps of it, its target's name: never followed
                data = os.fsencode(os.readlink(full)) if full.is_symlink() else full.read_bytes()
            except OSError:
                return Plan("refused", name, folder, files, gitignore=ignore, why=f"{safety.one_line(path)} could not be read")
        total += len(data)
        problem = landing.scan_text(path, data, secrets)
        if problem:
            return Plan("refused", name, folder, files, total, ignore, why=problem)
    if total > copies.MAX_BYTES:
        return Plan("refused", name, folder, files, total, ignore,
                    why=f"{total / 1_000_000:,.0f} MB would be tracked; at most {copies.MAX_BYTES // 1_000_000} MB")
    return Plan("turn_on", name, folder, files, total, ignore)


def default_branch(folder):
    found = gitops.run(["-C", folder, "config", "--get", "init.defaultBranch"], check=False)
    word = os.fsdecode(found.stdout).strip() if found.returncode == 0 else ""
    return word or "main"


def first_commit(folder, files, *, journal_dir, message):
    """`git init` (when there is no .git yet) and one first commit of exactly `files`, built in a temporary index, the
    branch created only if it isn't there, then the index set to it. The working tree is not written."""
    folder = Path(folder)
    if not (folder / ".git").exists():
        gitops.run(["-C", folder, "init", "-q", "-b", default_branch(folder)])
    branch = gitops.text(["-C", folder, "symbolic-ref", "--short", "HEAD"])
    with tempfile.TemporaryDirectory(prefix="sr-index-") as temp:
        index = {"GIT_INDEX_FILE": str(Path(temp) / "index")}
        gitops.run(["-C", folder, "add", "--pathspec-from-file=-", "--pathspec-file-nul", "--force"], extra=index,
                   input=b"\0".join(os.fsencode(p) for p in files) + b"\0")
        tree = gitops.text(["-C", folder, "write-tree"], extra=index)
    commit = gitops.text(["-C", folder, "commit-tree", tree, "-m", message],
                         extra=gitops.identity_env(*gitops.identity(folder)))
    journal = landing._write_journal(journal_dir, folder, {"kind": "git", "task_id": None, "folder": str(folder),
                                                           "branch": branch, "old": gitops.ZERO, "new": commit,
                                                           "paths": [], "index_only": True})
    try:
        gitops.move_branch(folder, branch, commit, None, message=message.splitlines()[0])  # brief 29.1, issue 10
    except gitops.GitError:
        journal.unlink(missing_ok=True)
        raise Refused("a first commit appeared meanwhile; nothing was changed") from None
    gitops.run(["-C", folder, "read-tree", commit])
    journal.unlink(missing_ok=True)
    return landing.Done(commit, branch, list(files), folder)


def turn_on(name, *, secrets=(), journal_dir):
    """Turn on undo: the checks (the dry run's), then the .gitignore lines, git init and the first commit."""
    plan = plan_git(name, secrets=secrets)
    if plan.would == "refused":
        raise Refused(plan.why, plan.code or "project_refused")
    folder = plan.folder
    text, adds = _gitignore_after(folder)
    if adds != plan.gitignore["adds"]:
        raise Refused(".gitignore changed meanwhile; nothing was changed")
    if adds:
        path = folder / GITIGNORE
        new = gitignore_text(text, adds)
        fd, temp = tempfile.mkstemp(dir=folder, prefix=".sr-gitignore-")
        with os.fdopen(fd, "w") as f:
            f.write(new)
        os.chmod(temp, (path.stat().st_mode & 0o777) if path.exists() else 0o644)
        os.replace(temp, path)
    return first_commit(folder, plan.files, journal_dir=journal_dir, message="sr: turn on undo (git for this project)")


# ---------- New project (decision 16) ----------

def set_up_new(folder, *, journal_dir):
    """Git for a folder `sr project new` has just made: the .gitignore lines, git init, a first commit of .gitignore and
    HANDOFF.md. None when git isn't installed (the project is made as before)."""
    if not gitops.installed():
        return None
    folder = Path(folder)
    path = folder / GITIGNORE
    if not path.exists():
        with open(path, "x") as f:
            f.write(gitignore_text(None, list(GITIGNORE_LINES)))
    return first_commit(folder, [GITIGNORE, projects.HANDOFF], journal_dir=journal_dir, message="sr: new project")
