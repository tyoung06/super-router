"""The Spec editor (build brief 33.2, decision 4): `sr project spec <name> [--json]` prints `SPEC.md` with its hash and the
items as code labels them; `--save [--expect <hash>] -- <text>` writes the file whole at the project's top level, under
the project's lock, as one commit `sr: spec edited` (`sr: spec added` for a first one) when the folder has git with a
commit on a branch, else written with no commit, as the project notes are. Refused with nothing written: over `spec_max`,
a `.env` value or a key-shaped line (named by line), an empty text, or a file whose hash moved since it was read
(`--expect`). The page's Spec section in the project's Notes sheet runs it. The owner's writes only: no agent and no
other router command writes the file (Save to project at `SPEC.md` is `projnotes.save_result`, refused when the file
exists; files in is `projgit.add_files`)."""
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from router import gitops, landing, projects, spec

FILE = spec.FILE
EDITED = "sr: spec edited"
ADDED = "sr: spec added"
# Decision 5: the Draft chip's task, a routed text-only task on the project (`--no-files`); Save to project at SPEC.md keeps it
DRAFT_TEXT = ("Write SPEC.md for this project: what it is and why, what is not in it, then `## Examples` and `## Done when`, "
              "each a numbered list, one line per item.")


def draft_chip(name):
    """Decision 5: Draft it, shown in the Spec section while the project has no SPEC.md: it fills the composer with a
    routed task on the project that answers as text (`--no-files`, so the put-back can't undo it)."""
    return {"kind": "draft_spec", "words": "Draft it", "later": False,
            "fill": {"team": "route", "project": name, "chat": None, "text": DRAFT_TEXT, "from": None, "idea": None,
                     "step": None, "no_files": True}}


class Refused(landing.Refused):
    """Nothing was written: why (a line number, never a value)."""

    def __init__(self, message, code=spec.REFUSED):
        super().__init__(message, code)


def _folder(name):
    try:
        folder = projects.folder_of(name)
    except projects.ProjectError as e:
        raise Refused(str(e), "project_refused") from None
    if folder is None:
        raise Refused(f"no project {name}", "project_unknown")
    if not Path(folder).is_dir():
        raise Refused(f"the folder of {name} is not there", "project_refused")
    return Path(folder)


def _repo_state(folder):
    """(the repo, whether a save commits, whether SPEC.md is tracked at the head): git with a commit on a branch, not the
    router's own folder."""
    repo = gitops.inspect(folder)
    commits = bool(repo.git and not repo.why and repo.head and repo.branch)
    tracked = bool(commits and gitops.blob_at(folder, repo.head, FILE))
    return repo, commits, tracked


def view(name, *, secrets=()):
    """`sr project spec <name> --json`'s document: the file (or none), its hash (the empty text's for none, so a first
    save's `--expect` works), characters, the cap, the labels as read, and whether a save commits."""
    folder = _folder(name)
    text = spec.read_text(folder)
    parsed = spec.parse(text or "")
    repo, commits, tracked = _repo_state(folder)
    return {"name": name, "folder": projects.tilde(folder), "exists": text is not None, "text": text or "",
            "hash": spec.digest(text or ""), "chars": len(text or ""), "lines": len((text or "").splitlines()),
            "max": spec.max_chars(), "git": bool(repo.git), "commits": commits, "tracked": tracked,
            **spec.labels_view(parsed), "labeled": parsed.labeled,
            "draft": None if text is not None else draft_chip(name),  # decision 5: only while there is no spec
            "commit_words": ("Save makes one commit holding SPEC.md alone." if commits
                             else "Save writes SPEC.md and commits nothing (no git here, or no commit yet).")}


@dataclass(frozen=True)
class Written:
    commit: object      # the commit id, or None when the file was written with no commit
    message: str        # EDITED or ADDED
    folder: Path
    hash: str

    @property
    def short(self):
        return gitops.short(self.commit) if self.commit else None


def _write_whole(path, text):
    fd, temp = tempfile.mkstemp(dir=Path(path).parent, prefix=".sr-spec-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8"))
        os.chmod(temp, (Path(path).stat().st_mode & 0o777) if Path(path).exists() else 0o644)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def save(conn, name, text, *, expect=None, secrets=(), journal_dir, lock_folder, fault=None):
    """Decision 4: replace the project's SPEC.md with `text`. Returns Written; raises Refused with nothing written."""
    folder = _folder(name)
    text = spec._normal(text)
    with landing.project_lock(name, folder=lock_folder, conn=conn, code="project_refused"):
        landing.recover(conn, folder, journal_dir, out=lambda line: None)
        current = spec.read_text(folder)
        if expect is not None and spec.digest(current or "") != expect:
            raise Refused(f"SPEC.md of {name} changed since you opened it; open it again, then save")
        if not text.strip():
            raise Refused("SPEC.md was not saved: the text is empty (remove the file by hand to drop the spec)")
        found = spec.problem(text, secrets)
        if found:
            raise Refused(f"SPEC.md was not saved: {found[0]}")
        target = folder / FILE
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise Refused("SPEC.md in the folder is a link or a folder; the router never writes through one")
        repo, commits, tracked = _repo_state(folder)
        message = EDITED if tracked else ADDED
        commit = None
        if commits:
            found_at = gitops.blob_at(folder, repo.head, FILE)
            changes = {FILE: (found_at[0] if found_at else "100644", gitops.hash_file(folder, text.encode("utf-8")))}
            commit = landing._commit(folder, repo.branch, repo.head, changes, message, journal_dir, "spec", fault=fault)
        else:
            _write_whole(target, text)
    return Written(commit, message, folder, spec.digest(text))
