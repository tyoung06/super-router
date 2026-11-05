"""File mode (rules 2.40, Project files; build brief 28, decision 1): whether a task with `--project` works on a copy of
the project's files, and when it doesn't, why, in the card's one line.

A task runs in file mode when git is installed; the project's folder is the top level of a git repository with a commit,
on a branch; the folder is not the router's own folder, inside it or one of its worktrees; Claude's file check has passed
on the installed Claude Code version; and the copy fits the limits. The cheap checks come first and the file check last,
since it may cost a Claude call (run at intake by `probes.files_gate`). Otherwise the task runs as before, handoff only.
`view` is the same reading for `sr status` and the page: it never runs the file check, a test or a write, and it reads
file mode on while the check hasn't run on the installed version, since intake runs it first (only a fail reads off)."""
from dataclasses import dataclass

from router import copies, gitops, probes, search


@dataclass(frozen=True)
class Decision:
    on: bool
    why: object = None    # the card's line when file mode is off
    repo: object = None   # gitops.Repo, when git was read

    def as_dict(self):
        return {"files_mode": "on" if self.on else "off", "why": self.why}


def _fits(repo):
    """Why the copy wouldn't fit the limits (or can't be made), or None. Reads the tree; writes nothing."""
    try:
        copies.plan(["-C", repo.folder], repo.head)
    except copies.CopyError as e:
        return str(e)
    except gitops.GitError as e:
        return f"its files could not be read ({e})"
    return None


def decide(folder, *, files_ready):
    """The intake decision. `files_ready()` answers Claude's file check ((ok, why)); it runs only when every other
    condition holds, and it may run the check itself (one Claude call, under the probe lock)."""
    repo = gitops.inspect(folder)
    if repo.why:
        return Decision(False, repo.why, repo)
    too_big = _fits(repo)
    if too_big:
        return Decision(False, too_big, repo)
    ok, why = files_ready()
    if not ok:
        return Decision(False, why, repo)
    return Decision(True, None, repo)


def view(folder, *, state_path, version):
    """The same reading for status and the page, read only: the file check's state comes from probe_state.json alone,
    and a check not yet run reads on (`probes.files_view_why`)."""
    repo = gitops.inspect(folder)
    if repo.why:
        return Decision(False, repo.why, repo)
    too_big = _fits(repo)
    if too_big:
        return Decision(False, too_big, repo)
    why = probes.files_view_why(state_path, version)
    return Decision(why is None, why, repo)


def claude_version():
    return search.claude_version()
