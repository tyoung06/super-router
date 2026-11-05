"""Versus on a project in file mode (rules 2.42, Relay; build brief 29.1, decision 9; the owner's D21, option a).

The router makes two copies at intake from the project's head, `<task_id>-a` and `<task_id>-b`, each with its own record
under the task's `project_files.candidates` (its copy id, its change, `changes-<slot>.diff` and its tests); the task owns
both. The slots must be Claude and ChatGPT, in either order. The Claude slot builds in its own copy with brief 28's build
call; the ChatGPT slot builds from a file view of its copy (router/fileview.py) and the router writes its files there,
after the snapshot every file-mode call gets and once the key scan finds nothing in them. Each copy's tests run after its
build (none when its change is empty). Each review gets the other candidate's change and tests, as data; Claude reviews in
the reviewed copy, read only. The pick keeps the picked copy (the task's record becomes its candidate's, waiting to land
when it changed something) and removes the other at once; `none` removes both; a chain that stops or is cancelled removes
both. No takeover, resume or fallback, as any review preset."""
from router import copies, filecalls, fileview, filemode, log, projects, safety, testrun

SLOTS = ("a", "b")
DIFF_FILE = "changes-{slot}.diff"


def copy_id(task_id, slot):
    return f"{task_id}-{slot}"


def record(task):
    return log.project_files_of(task) if task is not None else None


def active(task):
    """A versus task in file mode whose candidates' copies are still the task's (before the pick)."""
    found = record(task) or {}
    return found.get("mode") == "on" and bool(found.get("versus")) and bool(found.get("candidates"))


def is_versus(preset):
    return bool(getattr(preset, "has_reviews", False))


# ---------- intake ----------

def slot_refusal(preset):
    """Decision 9: in file mode the slots are Claude and ChatGPT, in either order; any other agent is refused, naming the
    slot. None when they are."""
    from router import availability
    for slot in preset.slots:
        if slot.agent not in ("claude", "chatgpt"):
            return (f"versus in file mode takes Claude and ChatGPT only (slot {slot.name} holds "
                    f"{availability.name_of(slot.agent)})")
    return None


def view_refusal(folder, head, secrets):
    """Decision 9 at intake, before any call or row: the redactor and the key scan on every file the ChatGPT slot's view
    would show, and the view's size, from git at `head` (no copy made). (code, why) or None."""
    try:
        facts = fileview.facts_of_commit(folder, head)
    except copies.CopyError:
        return None  # too big for a copy, or two paths that differ only in case: file mode is off, said at the copy
    problem = fileview.intake_problem(facts, secrets)
    if problem is None:
        return None
    return ("too_long" if "would show" in problem else "bad_file"), problem


def start(conn, task_id, project, decision, preset):
    """The record a versus task with --project starts with. On: two copies from the head, one per slot. Off: the card's
    line. Returns the record (written on the row)."""
    if not decision.on:
        found = {"mode": "off", "state": "none", "copy": False, "why": decision.why}
        log.set_project_files(conn, task_id, found)
        return found
    repo = decision.repo
    candidates = {}
    try:
        for slot in preset.slots:
            made = copies.make(copy_id(task_id, slot.name), repo.folder, repo.head)
            candidates[slot.name] = {"copy_id": copy_id(task_id, slot.name), "agent": slot.agent, "copy": True,
                                     "changed": [], "diff": None, "latest": None, "tests": None, "files": made.files,
                                     "left_out": made.left_out}
    except (copies.CopyError, OSError) as e:
        for slot in preset.slots:
            copies.remove(copy_id(task_id, slot.name))
        found = {"mode": "off", "state": "none", "copy": False, "why": safety.one_line(str(e))[:300]}
        log.set_project_files(conn, task_id, found)
        return found
    first = next(iter(candidates.values()))
    found = {"mode": "on", "versus": True, "state": "none", "copy": True, "base": repo.head, "branch": repo.branch,
             "files": first["files"], "left_out": first["left_out"], "candidates": candidates, "changed": [], "diff": None,
             "latest": None, "tests": None, "commit": None, "undo_commit": None, "why": None}
    log.set_project_files(conn, task_id, found)
    return found


def start_words(name, found):
    if found.get("mode") == "on":
        return (f"Files: two copies of {name} at {found['base'][:7]} on {safety.one_line(found['branch'])} "
                f"({found['files']} files each), one per candidate; the router writes ChatGPT's files")
    return f"Files: handoff only ({found.get('why')})"


# ---------- which copy a stage works in ----------

def slot_of(preset, n):
    """The slot whose copy stage n works in: its own build slot, or for a review the slot of the stage it reviews."""
    stage = preset.stage(n)
    target = stage.review_of if stage.review_of is not None else n
    return next((s.name for s in preset.slots if target in s.stages), None)


def candidate(task, slot):
    return ((record(task) or {}).get("candidates") or {}).get(slot) or {}


def _update_candidate(conn, task_id, slot, **fields):
    found = record(log.get_task(conn, task_id))
    found["candidates"][slot].update(fields)
    log.set_project_files(conn, task_id, found)
    return found["candidates"][slot]


def view_facts(task, slot):
    found = candidate(task, slot)
    return fileview.facts_of_folder(copies.folder_of(found["copy_id"]), found.get("left_out") or ())


def builds_from_view(task, stage, agent):
    """The ChatGPT slot's build on a file-mode versus: its prompt is the file view's, its files the router's to write."""
    return active(task) and stage.role == "build" and stage.review_of is None and agent == "chatgpt"


# ---------- the prompts ----------

def judge_blocks(conn, task, slot, secrets=()):
    """A review's blocks (decision 9): the reviewed candidate's change and its tests as data, with brief 28's judge line
    (the no-change line when it changed nothing, brief 29.1 decision 2)."""
    found = candidate(task, slot)
    diff = filecalls._read_kept(conn, found.get("diff"))
    if diff is None and found.get("latest") and copies.exists(found["copy_id"]):
        diff = copies.diff_text(found["copy_id"], found["latest"])
    if not found.get("changed"):
        return [filecalls.change_block(found, diff, secrets), filecalls.NO_CHANGE_TESTS_LINE, filecalls.NO_CHANGE_JUDGE_LINE]
    tests = found.get("tests")
    return [filecalls.change_block(found, diff, secrets),
            filecalls.tests_block(tests, filecalls._read_kept(conn, (tests or {}).get("output"))), filecalls.JUDGE_LINE]


def with_blocks(conn, task, preset, n, agent, prompt, secrets=()):
    """What a file-mode versus stage's prompt gets after today's blocks: Claude's build its paragraph; a review the other
    candidate's change and tests. ChatGPT's build carries its file view in the prompt itself."""
    stage = preset.stage(n)
    if stage.review_of is not None:
        return prompt + "\n\n" + "\n\n".join(judge_blocks(conn, task, slot_of(preset, n), secrets))
    if agent == "claude":
        return prompt + "\n\n" + filecalls.build_paragraph(task)
    return prompt


# ---------- the calls ----------

def _keep_diff(conn, task_id, slot, text, secrets):
    folder = filecalls._task_folder(conn, task_id)
    if folder is None:
        return None
    import os
    for d in (folder.parent, folder):
        d.mkdir(mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)
    name = DIFF_FILE.format(slot=slot)
    temp = folder / (name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(safety.redact(text, secrets))
    os.replace(temp, folder / name)
    return f"{filecalls.rounds.FOLDER}/{task_id}/{name}"


def _after_build(conn, task, slot, call_id, secrets, out, runner=None, available=None):
    """The candidate's change after its build, its diff kept as changes-<slot>.diff, then its tests (none when nothing
    changed). FileCallError when the change breaks a limit or holds what a copy never carries."""
    task_id, cid = task["task_id"], candidate(task, slot)["copy_id"]
    found = copies.change(cid, f"after-{call_id}")
    if found.problem:
        raise filecalls.FileCallError(f"the change can't be kept: {found.problem}")
    diff = _keep_diff(conn, task_id, slot, found.diff, secrets) if found.diff else None
    _update_candidate(conn, task_id, slot, changed=found.changed, diff=diff, latest=f"after-{call_id}")
    out(f"Candidate {slot.upper()}: " + filecalls.change_words({"changed": found.changed})[len("Files: "):])
    if not found.changed:
        tests = {"exit": None, "summary": None, "output": None, "command": projects.tests_of(log.project_of(task)),
                 "outcome": "not_run", "why": filecalls.NO_CHANGE}
    else:
        tests = _run_tests(conn, task, cid, secrets, runner=runner, available=available)
    _update_candidate(conn, task_id, slot, tests=tests)
    out(f"Candidate {slot.upper()}: " + (f"no tests run: {tests['why']}" if tests["outcome"] == "not_run" else testrun.line(tests)))
    return tests


def _run_tests(conn, task, cid, secrets, runner=None, available=None):
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
    result = (runner or testrun.run)(copies.folder_of(cid), words, project_folder=folder, secrets=secrets)
    return {**base, "exit": result.exit, "outcome": result.outcome, "summary": result.summary,
            "output": filecalls._keep_tests(conn, task["task_id"], result.output)}


def claude_wrap(conn, task, call_id, slot, worker, *, write, search=False, secrets=(), out=print):
    """Claude's call in a candidate's copy: the before-call check and snapshot, the call with that copy as its working
    folder (its file tools; read only on a review), then on its build the change and the tests."""
    cid = candidate(task, slot)["copy_id"]

    def call(prompt):
        problem = copies.problem_before_call(cid)
        if problem:
            raise filecalls.FileCallError(f"stopped before the call: {problem}")
        copies.snapshot(cid, f"before-{call_id}")
        answer = worker(prompt, copy=filecalls.CopySpec(copies.folder_of(cid), write, search))
        if not write:
            return filecalls._answered(answer)
        _put_back_spec(conn, task, slot, cid, call_id, out)  # brief 33.2 (decision 3)
        tests = _after_build(conn, log.get_task(conn, task["task_id"]), slot, call_id, secrets, out)
        return filecalls._answered(answer, tests)
    return call


def _put_back_spec(conn, task, slot, cid, call_id, out):
    """Brief 33.2 (decision 3): SPEC.md is the person's; a candidate's change to it goes back to the call's snapshot before
    the change is read, the candidate's record says so, and the card's line is printed."""
    from router import spec  # spec reads settings; kept local
    if copies.put_back(cid, spec.FILE, name=f"before-{call_id}"):
        _update_candidate(conn, task["task_id"], slot, spec_restored=True)
        out(spec.PUT_BACK_LINE)


def view_wrap(conn, task, call_id, slot, call, *, secrets=(), out=print):
    """ChatGPT's build from the file view (decision 9): the call as today (in workspace/, never a copy), then the reply's
    contract read by code. A miss writes nothing (the stage's one re-ask names it); a key in a block fails the stage as a
    copy problem; otherwise the router writes the blocks into the candidate's copy, after its snapshot, from the reply
    as it came back, and reads the change and runs the tests like any build. The answer carries what happened, for the
    call's row (`files`: written or missing)."""
    cid = candidate(task, slot)["copy_id"]

    def wrapped(prompt):
        facts = view_facts(task, slot)
        problem = copies.problem_before_call(cid)
        if problem:
            raise filecalls.FileCallError(f"stopped before the call: {problem}")
        copies.snapshot(cid, f"before-{call_id}")
        reply = call(prompt)
        parsed = fileview.parse(str(reply), facts)
        if parsed.missing:
            return filecalls.Answered(str(reply), files={"missing": list(parsed.missing)})
        found = fileview.scan_problem(parsed, secrets)
        if found:
            raise filecalls.FileCallError(f"ChatGPT's files can't be written: {found}")
        written = fileview.write(copies.folder_of(cid), parsed)
        _put_back_spec(conn, task, slot, cid, call_id, out)  # brief 33.2 (decision 3): the router wrote it; it goes back
        tests = _after_build(conn, log.get_task(conn, task["task_id"]), slot, call_id, secrets, out)
        return filecalls.Answered(str(reply), tests=tests, files={"written": written})
    return wrapped


def files_missing(row):
    """What a file-view build's reply missed of its contract, from its row (the wrapper read it before any write)."""
    return list(((log.context_of(row) or {}).get("files") or {}).get("missing") or [])


# ---------- the pick, a stop, a cancel ----------

def remove_all(conn, task_id):
    """Both candidates' copies gone (a stopped or cancelled chain, a pick of none); the record says so."""
    row = log.get_task(conn, task_id)
    found = record(row)
    if not found or not found.get("candidates"):
        return False
    for slot, item in found["candidates"].items():
        copies.remove(item["copy_id"])
        item["copy"] = False
    found["copy"] = False
    log.set_project_files(conn, task_id, found)
    return True


def picked(conn, task_id, choice, out=print):
    """After `sr pick` (decision 9): the picked candidate's record becomes the task's, waiting to land when it changed a
    file (with no change its copy goes too, brief 29.1 decision 2); the other copy is removed at once. `none` removes both.
    Returns the record, or None for a task not in file mode."""
    row = log.get_task(conn, task_id)
    found = record(row)
    if not found or not found.get("candidates"):
        return None
    if choice not in found["candidates"]:
        remove_all(conn, task_id)
        out("Files: both candidates' copies are removed; nothing lands.")
        return log.project_files_of(log.get_task(conn, task_id))
    for slot, item in found["candidates"].items():
        if slot != choice:
            copies.remove(item["copy_id"])
    item = found["candidates"][choice]
    record_ = {key: value for key, value in found.items() if key != "candidates"}
    record_.update({"copy_id": item["copy_id"], "changed": item.get("changed") or [], "diff": item.get("diff"),
                    "latest": item.get("latest"), "tests": item.get("tests"), "picked": choice})
    if record_["changed"]:
        record_.update(state="waiting", copy=True)
        log.set_project_files(conn, task_id, record_)
        out(f"{filecalls.change_words(record_)}. Waiting to land: sr land {row['n']} puts candidate {choice.upper()}'s change "
            f"in the folder as one commit; sr discard {row['n']} drops it. Candidate "
            f"{'B' if choice == 'a' else 'A'}'s copy is removed.")
    else:
        copies.remove(item["copy_id"])
        record_.update(state="none", copy=False)
        log.set_project_files(conn, task_id, record_)
        out("Files: no file changed; nothing to land. Both copies are removed.")
    return record_


def decide(folder, files_ready):
    return filemode.decide(folder, files_ready=files_ready)
