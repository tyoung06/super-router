"""Round files (rules v2.30, Round outputs; build brief 21, C1, with brief 13's Phase 0 decisions).

Every call's output is its own file in the task's folder beside the log: `tasks/<task_id>/<NN>-<role>-<agent>.md`.
`NN` is the call's place among the task's calls; the role is the call's (`do`, `check`, `fix`, `recheck`, or a stage's
role), a re-ask `reask-<role>` (a routed doer's `reask-do`, a fix round's `reask-fix`), and where a preset gives one role
to more than one stage, the candidate or voter the stage is (`build-a`, `review-b` (the review of candidate b),
`vote-c`). The call's row names the file, relative to the log's folder.

A file is written once, after its row: the call's text through the redactor with every .env value, created
exclusively and owner-only (folders 0700, files 0600). A second write never overwrites: it says so in one line and the
row names no file. A call with no text (a Grok call still out, a timed-out call) has none; a Grok call's file is
written when it is collected. A log in memory has none. Tasks from before have no files; nothing is reconstructed
(`sr show` says `not kept`)."""
import os
from pathlib import Path

from router import checking, context, log, presets, safety, split

FOLDER = "tasks"


def log_folder(conn):
    """The folder of the log file this connection has open, or None for a log in memory."""
    for row in conn.execute("PRAGMA database_list"):
        if row[1] == "main":
            return Path(row[2]).parent if row[2] else None
    return None


def _preset(row, loaded):
    if row["mode"] == "split":
        return split.PRESET
    if row["mode"] == "relay" and loaded is not None:
        return presets.for_task(row, loaded)[0]
    return None


def _letter(n, preset):
    """Where a preset gives one role to more than one stage (versus, vote): `-<slot>` of the stage, or for a review
    the slot of the stage it reviews; "" otherwise, or when the preset can't be read."""
    if preset is None:
        return ""
    stage = next((s for s in preset.stages if s.n == n), None)
    if stage is None or sum(s.role == stage.role for s in preset.stages) < 2:
        return ""
    target = stage.review_of if stage.review_of is not None else n
    slot = next((s.name for s in preset.slots if target in s.stages), None)
    return f"-{slot}" if slot else ""


def role_of(call, preset=None):
    """The role part of a call's file name. A late Grok answer (build brief 24, decision 7) is `late-<role>`."""
    if "reason_code" in call.keys() and call["reason_code"] == "late":
        return "late-" + role_of({**dict(call), "reason_code": None}, preset)
    if call["kind"] in log.STAGE_KINDS:
        role = call["role"] + _letter(call["stage"], preset)
        return f"reask-{role}" if call["kind"] == "reask" else role
    if call["kind"] == "do" and context.DO_REASK in call["call_id"]:
        return "reask-do"
    if call["kind"] == "fix" and checking.FIX_REASK in call["call_id"]:
        return "reask-fix"
    return call["kind"]


def file_name(call, order, preset=None):
    return f"{order:02d}-{role_of(call, preset)}-{call['agent']}.md"


def _create(folder, name, text):
    """Exclusive create, owner-only; FileExistsError when the file is already there."""
    for d in (folder.parent, folder):
        d.mkdir(mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)
    fd = os.open(folder / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(text)


def writer(*, secrets, out, loaded=None):
    """The hook main sets for one command (log.ROUND_WRITER): writes one call's round file after its row and names it
    on the row. `secrets`: every .env value; `loaded`: the presets, for a relay task's slot letters."""
    secrets = [s for s in secrets if s]

    def write(conn, call_id):
        folder = log_folder(conn)
        call = log.get_call(conn, call_id)
        if folder is None or call is None or call["text"] is None or call["round_file"] is not None:
            return None
        calls = log.calls_for(conn, call["task_id"])
        order = next(i for i, c in enumerate(calls, 1) if c["call_id"] == call_id)
        name = file_name(call, order, _preset(log.get_task(conn, call["task_id"]), loaded))
        relative = f"{FOLDER}/{call['task_id']}/{name}"
        try:
            _create(folder / FOLDER / call["task_id"], name, safety.redact(call["text"], secrets))
        except FileExistsError:
            out(f"round file not written: {relative} already exists")
            return None
        except OSError as e:
            out(f"round file not written: {relative} ({type(e).__name__})")
            return None
        log.set_round_file(conn, call_id, relative)
        return relative
    return write

