"""File-mode calls (rules 2.40, Project files; build brief 28, decisions 1, 3, 5, 8, 9, 10 and 18).

A task in file mode keeps its record on the task row (`tasks.project_files`): `mode` (on or off), `state` (none, waiting,
landed, discarded, undone), `copy` (whether the scratch copy is kept), the `base` commit and `branch`, the `changed`
files, the `diff` file, the `latest` snapshot, the latest `tests`, the land `commit` and `undo_commit`, `left_out`
(links and submodules not copied), and `why` when file mode was off.

Who touches the copy (decision 3): only Claude's build calls write in it (a routed doer's call and its re-ask, a fix
round, research-build's build stage, redteam's build and revise stages); Claude's check, re-check, attack and review
calls read it. Before every such call the copy is checked for a path it never carries (only an agent could have made
one: the task stops) and snapshotted (`before-<call_id>`, what a resume restores). After a build call the change is
computed against the base and its diff kept, redacted, as `tasks/<task_id>/changes.diff`; a change holding what a copy
never carries, a link or a file over the limit fails the call (`copy_problem`) and the task stops. Then the router runs
the project's tests on a throwaway copy (router/testrun.py) and keeps the output as `tests-<k>.txt`. ChatGPT, Grok and
Cursor never run in the copy: a checker or attacker gets the change and the tests as data (decision 9)."""
import os
import shlex
from collections import namedtuple
from pathlib import Path

from router import availability, copies, filemode, log, projects, rounds, safety, testrun

BUILD_ROLES = ("build", "revise", "execute")  # brief 29.1 (decision 8): collab's execute builds in the copy
JUDGE_ROLES = ("attack", "review")
# Brief 29 (decision 13): a project split's plan call reads the copy, as a check does, and judges nothing; brief 29.1
# (decision 8): so does collab's plan
READ_ROLES = JUDGE_ROLES + ("split_plan", "plan")
PLAN_READ_LINE = ("The working folder is a copy of the project {name} as of its last commit. Read it to plan; change "
                  "nothing: the build comes after the plan.")
DIFF_LIMIT = 60_000          # characters of the diff a prompt carries (decision 9)
DIFF_FILE = "changes.diff"
CopySpec = namedtuple("CopySpec", "folder write search")


class FileCallError(safety.SafeError):
    """A file-mode call that can't be made or kept: the copy holds what it never may, or the change broke a limit.
    Its code stops the task; nothing takes it over."""

    def __init__(self, message, code="copy_problem"):
        super().__init__(message)
        self.code = code


class Answered(str):
    """A file-mode call's answer with its tests record (a build call's), keeping the search queries a search answer
    carries. Brief 29.1 (issue 2): `cwd` is `copy` and `tools` the init event's list, for the call's row. Brief 33.3 (D1,
    task 155): `served`, the served record the stream gave, kept for the row as a plain call's is."""

    def __new__(cls, text, *, tests=None, queries=None, tools=None, cwd=None, files=None, served=None):
        found = super().__new__(cls, text)
        found.tests = tests
        found.tools, found.cwd = tools, cwd
        found.served = served
        found.file_outcome = files  # brief 29.1 (decision 9): what the router wrote from a file-view reply, or its misses
        if queries is not None:
            found.queries = queries
        return found


def _answered(answer, tests=None):
    return Answered(str(answer), tests=tests, queries=getattr(answer, "queries", None),
                    tools=getattr(answer, "tools", None), cwd="copy", served=getattr(answer, "served", None))


# ---------- the record ----------

def record(task):
    return log.project_files_of(task) if task is not None else None


def active(task):
    """In file mode with its copy kept: the calls go to the copy and the prompts carry the file blocks."""
    found = record(task)
    return bool(found) and found.get("mode") == "on" and bool(found.get("copy"))


def read_only(task):
    """Brief 33.2 fix 1 (the owner's decision 1): a `--no-files` task in file mode. Its copy is read, never written: the do
    call, a fix round and a re-ask get Read, Glob and Grep only, no tests run, and the change is always empty."""
    found = record(task)
    return bool(found) and found.get("mode") == "on" and bool(found.get("read_only"))


def copy_kind(task):
    """For the check's facts paragraph: False (no copy), "read" (a read-only copy) or True (a copy the doer edited)."""
    if not active(task):
        return False
    return "read" if read_only(task) else True


def copy_id(task):
    """Brief 29 (decision 12): the task id whose copy a task works in: its own, or a piece's split's (the owner). Brief 29.1
    (decision 9): a picked versus candidate's (`copy_id`, `<task_id>-<slot>`)."""
    found = record(task) or {}
    return found.get("copy_id") or found.get("owner") or task["task_id"]


def is_piece(task):
    """A piece of a project split in file mode: its record points at its split's copy (brief 29, decision 13). Brief 34: a
    run's step too (its record points at its run's copy), which `is_split_piece` tells apart where the words, the tests
    and the check differ."""
    return bool((record(task) or {}).get("owner"))


def is_split_piece(task):
    """A split's piece, never a run's step (brief 34, decision 2: a step's prompts, tests and check are Build step k's)."""
    return is_piece(task) and not log.is_run_step(task)


PIECE_PREFIX = "piece-"


def piece_start(k):
    """The snapshot a piece's part is read from: the split's copy right before the piece's first call."""
    return f"{PIECE_PREFIX}{k}-start"


def piece_record(owner, k, found):
    """A piece's record at the approval (decision 13): a pointer to its split's copy, with its own part to come. `found`
    is the split's record."""
    return {"mode": "on", "owner": owner, "start": piece_start(k), "state": "none", "copy": True,
            "base": found.get("base"), "branch": found.get("branch"), "changed": [], "diff": None, "latest": None,
            "tests": None, "commit": None, "undo_commit": None, "why": None}


INTEGRATE_ROLE = "integrate"  # brief 29 (decision 15): a project split's join builds in its copy


def builds(kind, role, agent):
    return agent == "claude" and (kind in ("do", "fix") or (kind in log.STAGE_KINDS and role in BUILD_ROLES + (INTEGRATE_ROLE,)))


def reads(kind, role, agent):
    return agent == "claude" and (kind in ("check", "recheck") or (kind in log.STAGE_KINDS and role in READ_ROLES))


def judges(kind, role):
    """A checker, an attacker or a reviewer: the call that gets the change and the tests as data (decision 9c)."""
    return kind in ("check", "recheck") or (kind in log.STAGE_KINDS and role in JUDGE_ROLES)


def _plan(task):
    return task is not None and "mode" in task.keys() and task["mode"] == "plan"


def in_copy(task, kind, role, agent):
    if _plan(task):  # brief 33.1 (decision 3): every Claude call of a plan reads the copy; none writes it
        return active(task) and agent == "claude"
    return active(task) and (builds(kind, role, agent) or reads(kind, role, agent))


def plan_call(task, kind, role, agent):
    """Brief 33.1 (decision 7): a plan task's Claude plan, revise or fix call (or its re-ask): read only, but it needs the
    files, so it is never taken over, and Resume makes it again by Claude in the same copy."""
    from router import plan  # plan imports teams and relay; kept local
    return _plan(task) and agent == "claude" and (kind == "fix" or (
        kind in log.STAGE_KINDS and role in (plan.PLAN_ROLE, "revise")))


def build_call(task, call):
    """True when a stopped call row is a Claude build call on a file-mode task (decision 18: never taken over); brief
    33.1 (decision 7): also a plan's Claude plan, revise or fix call."""
    role = call["role"] if call["kind"] in log.STAGE_KINDS else None
    if bool(record(task) and record(task).get("mode") == "on") and plan_call(task, call["kind"], role, call["agent"]):
        return True
    return bool(record(task) and record(task).get("mode") == "on") and not _plan(task) and builds(
        call["kind"], role, call["agent"])


def _split_task(task):
    return "mode" in task.keys() and task["mode"] == "split"


# ---------- intake (decision 1) ----------

READ_ONLY_WHY = "read only, answers in text"  # brief 33.2 fix 1: `--no-files`'s why with its read-only copy
READ_ONLY_TESTS = "read only: no file can change"


def start(conn, task_id, project, decision, agent, *, read_only=False):
    """The record a task with --project starts with: on (its copy made now) when file mode holds and Claude builds; off
    with the card's one line otherwise. Returns the record (written on the row). Brief 33.2 fix 1: `read_only` (a
    `--no-files` task) makes the same copy for Claude to read, never write (`read_only: true`, its tests `not_run`);
    without file mode, or with another doer, the task runs handoff only as before, its why naming the reason."""
    from router.spec import TEXT_ONLY  # spec reads settings; kept local
    if decision.on and agent != "claude":
        found = {"mode": "off", "state": "none", "copy": False,
                 "why": (f"{TEXT_ONLY}; {availability.name_of(agent)} can't read the project's files" if read_only
                         else f"{availability.name_of(agent)} can't change project files: nothing to land")}
    elif decision.on:
        repo = decision.repo
        try:
            made = copies.make(task_id, repo.folder, repo.head)
        except (copies.CopyError, OSError) as e:
            why = safety.one_line(str(e))[:300]
            found = {"mode": "off", "state": "none", "copy": False,
                     "why": f"{TEXT_ONLY}; no read-only copy: {why}" if read_only else why}
        else:
            found = {"mode": "on", "state": "none", "copy": True, "base": repo.head, "branch": repo.branch,
                     "files": made.files, "left_out": made.left_out, "changed": [], "diff": None, "latest": None,
                     "tests": None, "commit": None, "undo_commit": None, "why": None}
            if read_only:
                found.update(read_only=True, why=READ_ONLY_WHY, tests={
                    "exit": None, "summary": None, "output": None, "command": projects.tests_of(project),
                    "outcome": "not_run", "why": READ_ONLY_TESTS})
    else:
        found = {"mode": "off", "state": "none", "copy": False,
                 "why": f"{TEXT_ONLY}; no read-only copy: {decision.why}" if read_only else decision.why}
    log.set_project_files(conn, task_id, found)
    return found


def _files_count(n):
    return f"{n} file{'' if n == 1 else 's'}"  # brief 33.4 (decision 7): "(1 file)"


def start_words(name, found):
    if found.get("mode") == "on":
        left = found.get("left_out") or []
        extra = f"; left out: {', '.join(safety.one_line(x['path']) for x in left[:5])}" if left else ""
        if found.get("read_only"):  # brief 33.2 fix 1
            return (f"Files: a read-only copy of {name} at {found['base'][:7]} on {safety.one_line(found['branch'])} "
                    f"({_files_count(found['files'])}{extra}); Claude reads it and answers in text, so nothing lands")
        return (f"Files: a copy of {name} at {found['base'][:7]} on {safety.one_line(found['branch'])} "
                f"({_files_count(found['files'])}{extra}); only Claude's build calls change it")
    return f"Files: handoff only ({found.get('why')})"


# ---------- the prompts (decision 9) ----------

JUDGE_LINE = ("The change is the diff above, made in a copy of the project. Judge the task against it and the test "
              "results; a failing test is a failure unless the result explains why it is expected.")
# Brief 29.1 (decision 2, the owner's answer to brief 28's issue 16): no file changed, no tests, and no tests block
NO_CHANGE = "no file changed"
NO_CHANGE_TESTS_LINE = "No file changed, so no tests ran."
NO_CHANGE_JUDGE_LINE = JUDGE_LINE.replace(" and the test results", "")


def _tests_words(task):
    """Brief 33.1 (decision 23a): whether the project has a test command and, when it has, that the router runs it after
    the call and the checker sees the results, so the agent never asks for that run (#156's `### Next` asked for one)."""
    name = log.project_of(task)
    words = projects.tests_of(name)
    if not words:
        return "The project has no test command, so no tests run."
    if not testrun.available():
        return "No tests run: this Mac has no test sandbox (sandbox-exec)."
    return (f"After your reply the router runs the project's tests (`{shlex.join(words)}`), and the checker sees the "
            "results, so never ask for that run, in `### Next` or anywhere else.")


# Brief 33.2 fix 1: a `--no-files` task's do call, fix round and re-ask read the copy in place of the build paragraph,
# and its checker judges the answer as text in place of the (always empty) change
READ_PARAGRAPH = ("The project's files are in your working folder, a copy of the project {name} as of its last commit, "
                  "read only: read what you need to answer. You can't change any file and no command can be run; "
                  "answer in text.")
READ_JUDGE_LINE = ("The doer read a read-only copy of the project's files and answered in text: no file can change and "
                   "no tests ran. Judge the answer as text.")
PIECE_TESTS_LINE = "The project's tests run once the pieces are joined."
PIECE_JUDGE_LINE = ("The change is the diff above: this piece's part of the work, made in a copy of the project. The "
                    "project's tests run once the pieces are joined; judge this piece's change against its own task.")


def build_paragraph(task, has_spec=False):
    """Decision 9a: after today's blocks, on Claude's build, revise and fix calls in file mode. Brief 29 (decision 16): on
    a project split the copy holds the pieces before this one (a piece) or every piece (the integration); a piece's
    call says the tests run once the pieces are joined, and names its files in the reply (it has no `### Produced`).
    Brief 33.2 (decision 3): on a task that carries the project's spec, one more clause: SPEC.md is the person's."""
    name = log.project_of(task)
    if is_split_piece(task):
        found = (f"The working folder is a copy of the project {name} as of its last commit, with the pieces before this "
                 "one already in it. Make the change by editing files there: add, change or delete only what the task "
                 f"needs, and name the files you changed in your reply. No command can be run. {PIECE_TESTS_LINE}")
    elif _split_task(task):  # brief 29.1 (decision 7e): the pieces' changes are in the copy; the entry is the split's
        found = (f"The working folder is a copy of the project {name} as of its last commit, with every piece's change "
                 "already in it. Where the pieces don't fit together, make them fit by editing files there: add, change or "
                 "delete only what joining them needs. In `### Produced`, name every file the split changed, the pieces' "
                 "and yours, never `nothing written`: the entry is the whole split's. No command can be run. "
                 f"{_tests_words(task)}")
    else:
        found = (f"The working folder is a copy of the project {name} as of its last commit. Make the change by editing "
                 "files there: add, change or delete only what the task needs, and name the files you changed in `### "
                 f"Produced`. No command can be run. {_tests_words(task)}")
    if has_spec:
        from router import spec  # spec reads settings; kept local
        found = f"{found} {spec.BUILD_CLAUSE}"
    return found


def _has_spec(conn, task):
    """Brief 33.2: whether the task carries the project's spec (its copy, or its split's)."""
    from router import rounds, spec  # kept local
    return conn is not None and spec.copy_of(rounds.log_folder(conn), task)[0] is not None


def _sign(n):
    return "?" if n is None else str(n)


def change_block(found, diff, secrets=()):
    """Decision 9c: the change as data, the full file list first, the diff cut at DIFF_LIMIT characters with the cut
    said."""
    changed = found.get("changed") or []
    lines = [f"===== change: {len(changed)} {'file' if len(changed) == 1 else 'files'} ====="]
    for item in changed:
        lines.append(f"{item['status']} {safety.one_line(item['path'])} (+{_sign(item['plus'])} -{_sign(item['minus'])})")
    if not changed:
        lines.append("(no file changed)")
    text = safety.redact(diff or "", secrets).rstrip("\n")
    if text:
        lines.append("")
        if len(text) > DIFF_LIMIT:
            lines.append(text[:DIFF_LIMIT])
            lines.append(f"[the diff is cut here at {DIFF_LIMIT:,} characters; the list above names every changed file]")
        else:
            lines.append(text)
    lines.append("===== end change =====")
    return "\n".join(lines)


def tests_block(tests, output=None):
    """Decision 9b/9c: the latest test results as data, or the line that none ran."""
    if not tests or tests.get("outcome") == "not_run":
        why = (tests or {}).get("why") or "no test command"
        return f"No tests ran: {why}."
    head = f"exit {tests['exit']}" if tests.get("exit") is not None else "no exit code"
    lines = ["===== tests =====", f"command: {shlex.join(tests.get('command') or [])}",
             f"outcome: {tests['outcome']} ({head})"]
    lines.append(output.rstrip("\n") if output else "(the output was not kept)")
    lines.append("===== end tests =====")
    return "\n".join(lines)


def _read_kept(conn, relative):
    folder = rounds.log_folder(conn)
    if folder is None or not relative:
        return None
    try:
        return (folder / relative).read_text(errors="replace")
    except OSError:
        return None


def latest_tests(task):
    found = record(task)
    return (found or {}).get("tests")


def diff_text(conn, task):
    """The latest change's diff: the kept file, or read again from the router's history of the copy (a piece's from its
    starting snapshot, brief 29)."""
    found = record(task) or {}
    text = _read_kept(conn, found.get("diff"))
    owner = copy_id(task)
    if text is None and found.get("latest") and copies.exists(owner):
        try:
            text = copies.diff_text(owner, found["latest"], since=found.get("start") or "base")
        except Exception:
            text = None
    return text


def blocks(conn, task, kind, role, agent, secrets=()):
    """What a file-mode call's prompt gets after today's blocks: the build paragraph (a fix round's with the latest test
    results first), or for a checker, attacker or reviewer the change, the tests and the line. [] when the task is not in
    file mode or the call is neither."""
    if not active(task):
        return []
    if _plan(task):  # brief 33.1 (decision 3): every call of a plan gets the copy's file list; Claude's read the copy
        return plan_blocks(task, kind, role, agent, secrets)
    if kind in log.STAGE_KINDS and role == "plan" and reads(kind, role, agent):  # brief 29.1 (decision 8): collab's plan
        return [PLAN_READ_LINE.format(name=log.project_of(task))]
    if read_only(task):  # brief 33.2 fix 1: the read paragraph in place of the build one; the judge's text line
        if builds(kind, role, agent):
            return [READ_PARAGRAPH.format(name=log.project_of(task))]
        return [READ_JUDGE_LINE] if judges(kind, role) else []
    if builds(kind, role, agent):
        parts = []
        if kind == "fix" and not is_split_piece(task):  # brief 29: a piece's build runs no tests, so its fix gets none
            tests = latest_tests(task)
            parts.append(tests_block(tests, _read_kept(conn, (tests or {}).get("output"))))
        return parts + [build_paragraph(task, has_spec=_has_spec(conn, task))]
    if judges(kind, role):
        if is_split_piece(task):  # brief 29 (decision 13): its own part, and the line in place of the tests block
            return [change_block(record(task), diff_text(conn, task), secrets), PIECE_JUDGE_LINE]
        if not (record(task) or {}).get("changed"):  # brief 29.1 (decision 2): nothing changed, so no tests ran
            return [change_block(record(task), diff_text(conn, task), secrets), NO_CHANGE_TESTS_LINE,
                    NO_CHANGE_JUDGE_LINE]
        tests = latest_tests(task)
        return [change_block(record(task), diff_text(conn, task), secrets),
                tests_block(tests, _read_kept(conn, (tests or {}).get("output"))), JUDGE_LINE]
    return []


PLAN_READ_LINE_PLAN = ("Your working folder is a copy of the project {name} as of its last commit: read what helps, and "
                       "change nothing.")


def plan_blocks(task, kind, role, agent, secrets=()):
    """Brief 33.1 (decision 3): a plan call's file blocks: the read line on Claude's calls in the copy but stage 1's (its
    prompt says it), then the copy's file list as data (paths and sizes, from the copy's base), on every call."""
    from router import plan  # plan imports teams and relay; kept local
    try:
        entries = copies.files_at(copy_id(task), "base")
    except Exception:  # a copy whose history can't be read: the list says so, and the call goes on
        entries = None
    listing = plan.files_block(entries, secrets) if entries is not None else "The project's file list could not be read."
    lead = []
    if agent == "claude" and not (kind in log.STAGE_KINDS and role == plan.PLAN_ROLE):
        lead = [PLAN_READ_LINE_PLAN.format(name=log.project_of(task))]
    return lead + [listing]


def with_blocks(conn, task, kind, role, agent, prompt, secrets=()):
    parts = blocks(conn, task, kind, role, agent, secrets)
    return prompt if not parts else prompt + "\n\n" + "\n\n".join(parts)


# ---------- the call in the copy ----------

def _task_folder(conn, task_id):
    folder = rounds.log_folder(conn)
    return None if folder is None else folder / rounds.FOLDER / task_id


def _keep_diff(conn, task_id, text, secrets):
    """`tasks/<task_id>/changes.diff`, redacted, owner-only, replaced after each build call. The path relative to the log's
    folder, or None for a log in memory."""
    folder = _task_folder(conn, task_id)
    if folder is None:
        return None
    for d in (folder.parent, folder):
        d.mkdir(mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)
    temp = folder / (DIFF_FILE + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(safety.redact(text, secrets))
    os.replace(temp, folder / DIFF_FILE)
    return f"{rounds.FOLDER}/{task_id}/{DIFF_FILE}"


def _keep_tests(conn, task_id, output):
    folder = _task_folder(conn, task_id)
    if folder is None:
        return None
    k = 1
    while (folder / f"tests-{k}.txt").exists():
        k += 1
    try:
        rounds._create(folder, f"tests-{k}.txt", output)
    except OSError:
        return None
    return f"{rounds.FOLDER}/{task_id}/tests-{k}.txt"


def run_tests(conn, task, secrets=(), *, runner=None, available=None):
    """Decision 5: the project's test command on a throwaway copy of the copy, in the sandbox; the record the call row
    and the task's record keep. Never raises: a run that can't happen is `not_run` with why."""
    name = log.project_of(task)
    words = projects.tests_of(name)
    base = {"exit": None, "summary": None, "output": None, "command": words}
    if not words:
        return {**base, "outcome": "not_run", "why": "the project has no test command"}
    if not (available or testrun.available)():
        return {**base, "outcome": "not_run", "why": "this Mac has no test sandbox (sandbox-exec)"}
    folder = projects.folder_of(name)
    problem = testrun.check_words(words, folder) if folder is not None else "the project is not registered"
    if problem:
        return {**base, "outcome": "not_run", "why": problem}
    result = (runner or testrun.run)(copies.folder_of(copy_id(task)), words, project_folder=folder, secrets=secrets)
    return {**base, "exit": result.exit, "outcome": result.outcome, "summary": result.summary,
            "output": _keep_tests(conn, task["task_id"], result.output)}


def after_build(conn, task, call_id, secrets=()):
    """Decision 8: the change after a build call, its diff kept, the record updated. Returns copies.Change. Brief 29: a
    piece's part is read from its starting snapshot in its split's copy, and kept as the piece's own `changes.diff`."""
    task_id = task["task_id"]
    since = (record(task) or {}).get("start") or "base"
    found = copies.change(copy_id(task), f"after-{call_id}", since=since)
    diff = _keep_diff(conn, task_id, found.diff, secrets) if found.diff else None
    log.update_project_files(conn, task_id, changed=found.changed, diff=diff, latest=f"after-{call_id}")
    return found


def change_words(found):
    changed = found.get("changed") or []
    if not changed:
        return "Files: no file changed"
    plus = sum(c["plus"] or 0 for c in changed)
    minus = sum(c["minus"] or 0 for c in changed)
    names = ", ".join(safety.one_line(c["path"]) for c in changed[:6]) + (f" and {len(changed) - 6} more" if len(changed) > 6 else "")
    return f"Files: {len(changed)} changed (+{plus} −{minus}): {names}"


def wrap(conn, task, call_id, kind, role, worker, *, search=False, secrets=(), out=print, runner=None, available=None):
    """The Claude call in the copy (decision 3): the before-call check and snapshot, the call with the copy as its working
    folder, then (on a build call) the change, its diff and the tests. Returns a function of the prompt."""
    task_id, owner = task["task_id"], copy_id(task)
    write = builds(kind, role, "claude") and not _plan(task) and not read_only(task)  # brief 33.1: a plan's calls read the
    # copy, never write it; brief 33.2 fix 1: nor does a `--no-files` task's
    start = (record(task) or {}).get("start")

    def call(prompt):
        problem = copies.problem_before_call(owner)
        if problem:
            raise FileCallError(f"stopped before the call: {problem}")
        if start and not copies.has_snapshot(owner, start):  # brief 29 (decision 13): right before a piece's first call
            copies.snapshot(owner, start)
        copies.snapshot(owner, f"before-{call_id}")
        answer = worker(prompt, copy=CopySpec(copies.folder_of(owner), write, search))
        if not write:
            return _answered(answer)
        if log.plan_step_of(task):  # brief 33.1 (decision 13): docs/PLAN.md is the router's; a build's change goes back
            from router import plan  # plan imports teams and relay; kept local
            # brief 34 (D1, run #156): to the file as it stood when this step started, never the run's base, which predates
            # the ticks the router wrote for the steps before; a step built by hand has no start and keeps the base
            if copies.put_back(owner, plan.FILE, name=start or "base"):
                log.update_project_files(conn, task_id, plan_md_restored=True)
                out(plan.PUT_BACK_LINE)
        if log.project_of(task):  # brief 33.2 (decision 3): SPEC.md is the person's; a build's change to it goes back
            from router import spec  # spec reads settings; kept local as plan is
            if copies.put_back(owner, spec.FILE, name=start or "base"):
                log.update_project_files(conn, task_id, spec_restored=True)
                out(spec.PUT_BACK_LINE)
        found = after_build(conn, task, call_id, secrets)
        if found.problem:
            raise FileCallError(f"the change can't be kept: {found.problem}")
        out(change_words(log.project_files_of(log.get_task(conn, task_id))))
        if is_split_piece(task):  # brief 29 (decision 13): the project's tests run once the pieces are joined
            out(f"no tests run: {PIECE_TESTS_LINE[0].lower()}{PIECE_TESTS_LINE[1:-1]}")
            return _answered(answer)
        if not found.changed:  # brief 29.1 (decision 2): no file changed since the base, so no tests
            tests = {"exit": None, "summary": None, "output": None, "command": projects.tests_of(log.project_of(task)),
                     "outcome": "not_run", "why": NO_CHANGE}
        elif (copies.same_tree(owner, f"before-{call_id}", f"after-{call_id}")
              and latest_tests(log.get_task(conn, task_id)) is not None):  # this call changed nothing: the task keeps
            out("no tests run: this call changed no file")  # its last test record, which its checker gets (a split's
            return _answered(answer)  # join, the first, runs)
        else:
            tests = run_tests(conn, task, secrets, runner=runner, available=available)
        log.update_project_files(conn, task_id, tests=tests)
        out(f"no tests run: {tests['why']}" if tests["outcome"] == "not_run" else testrun.line(tests))
        return _answered(answer, tests)
    return call


# ---------- delivery (decision 10) ----------

def _stopped(conn, task_id):
    """The task's newest call stopped (failed or timed out): its copy is kept for Resume (brief 29.1, decision 2)."""
    calls = log.calls_for(conn, task_id)
    return bool(calls) and calls[-1]["status"] in ("failed", "timed_out")


def deliver(conn, task_id, out=print):
    """At a delivery (`_finish`): a change waits to land; a failed check keeps its change for Discard. Brief 29.1 (decision
    2): with no file changed the copy goes, whether the task passed or failed, unless its newest call stopped (kept for
    Resume). Returns the record, or None for a task not in file mode. Brief 29 (decision 13): a piece never waits to land
    and never removes its split's copy; only the split lands."""
    row = log.get_task(conn, task_id)
    found = record(row)
    if not found or found.get("mode") != "on" or not found.get("copy"):
        return None
    if is_piece(row):
        out(f"{change_words(found)} (this step's part; the run lands the whole change once)" if log.is_run_step(row)
            else f"{change_words(found)} (this piece's part; its split lands the whole change once)")
        return found
    if row["status"] == "done" and row["check_state"] != "failed" and found.get("changed"):
        found = log.update_project_files(conn, task_id, state="waiting")
        out(f"{change_words(found)}. Waiting to land: sr land {row['n']} puts it in the folder as one commit; "
            f"sr discard {row['n']} drops it.")
        return found
    if not found.get("changed") and not _stopped(conn, task_id):
        copies.remove(task_id)
        found = log.update_project_files(conn, task_id, copy=False)
        out("Files: no file changed; nothing to land." if row["check_state"] != "failed"
            else "Files: no file changed; the copy is removed.")
        return found
    if not found.get("changed"):
        out(f"Files: no file changed; the copy is kept for sr resume {row['n']} (sr discard {row['n']} drops it).")
        return found
    if row["check_state"] == "failed":  # brief 29.1 (decision 21): Land anyway, behind its own flag
        out(f"Files: the check didn't pass, so the change waits for you: sr land {row['n']} --anyway lands it as it is; "
            f"sr discard {row['n']} drops the copy.")
        return found
    out(f"Files: the change can't land (the check {'was blocked' if row['check_state'] == log.BLOCKED else 'did not end'}); "
        f"sr discard {row['n']} drops the copy.")
    return found


def waiting(task):
    found = record(task)
    return bool(found) and found.get("state") == "waiting"


def remove_copy(conn, task_id):
    """The copy and its history gone (a cancel of an open task); the record says so. Brief 29 (decision 14): a piece's
    cancel never removes its split's copy (the split owns it)."""
    if is_piece(log.get_task(conn, task_id)):
        return False
    if (record(log.get_task(conn, task_id)) or {}).get("candidates"):  # brief 29.1 (decision 9): both versus copies
        from router import versusfiles
        return versusfiles.remove_all(conn, task_id)
    removed = copies.remove(copy_id(log.get_task(conn, task_id)))
    if record(log.get_task(conn, task_id)):
        log.update_project_files(conn, task_id, copy=not removed)
    return removed


def view(folder, *, state_path, version):
    return filemode.view(folder, state_path=state_path, version=version)
