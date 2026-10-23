"""Command line: python -m router route|relay|split|resume|check|log|show|cancel|serve|migrate|probe|project|memory

Exit codes: 0 OK (for route: the result was printed, or the task was sent without waiting),
1 failed, 2 refused before anything was logged, 3 sent to Grok but no result yet
(don't resend; run check later), 4 the task came back to you (nothing was sent to an agent),
5 the result was not passed by its checker after one fix round (you were shown both sides),
130 stopped with Ctrl+C. `sr show <n> --history` lists every call a task made.
"""
import argparse
import dataclasses
import functools
import os
import re
import shlex
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from pathlib import Path

import requests
from dotenv import dotenv_values

from router import availability, cardline, chatgpt_worker, checking, claude_probe, claude_worker, codex_probe, context, cursor_probe, cursor_worker, drop, fallback, grok, ids, inbox, jev, jsonview, locks, log, media, memory, memory_auto, memory_server, online, page, plan_limit, presets, probes, projects, receipt, relay, resume, rounds, routing, runs, safety, search, settings, split, state, status, takeover, web_files_probe
from router.roster import RosterError, load_roster

presets_mod = presets  # the module, inside functions whose `presets` parameter is the loaded file

TIMEOUT_MINUTES = 30
WAIT_SECONDS = 10 * 60   # how long route waits for Grok by default
POLL_SECONDS = 20
MAX_INBOX_ERRORS = 3     # inbox errors in a row before route stops waiting
GH_LOGGED_OUT = 4        # gh's exit code when it needs `gh auth login`
MAX_BAD_ANSWERS = 3      # answers in a row that aren't choices before a task comes back
UNCHECKED_LINE = "UNCHECKED: no other agent has checked this result yet."
SANITY_NOTE = "The checker can't open links or verify facts."
FILES_NOTE = "The checker could not open the files."
ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "router.db"
BACKUPS_DIR = ROOT / "backups"
ENV_PATH = ROOT / ".env"
PROBE_STATE = ROOT / "probe_state.json"   # gitignored: the Claude Code version `sr probe`'s search check passed on
CLAUDE_SETTINGS = [
    Path.home() / ".claude" / "settings.json",
    Path.home() / ".claude" / "settings.local.json",
]


def _secrets(config):
    """Build brief 22 (decision 10): every `.env` value of 8 characters or more, not only the three named keys; the same
    set the JSON and the round files redact with (safety.env_secrets)."""
    return safety.env_secrets(config)


def _file_holds_a_secret(paths, secrets):
    """Build brief 22 (decision 10): a file whose name holds a `.env` value is refused at intake (its copy is named from
    it, so it can't be renamed in the log alone)."""
    return any(secret in Path(path).name for path in paths for secret in secrets)


def _releases_its_runs(command):
    """Build brief 22 (decision 4): a command that runs tasks lets go of every run it took when it returns, however it
    returns (a result, a refusal, an error, Ctrl+C), so a row never keeps a run its process no longer has."""
    @functools.wraps(command)
    def wrapped(*args, **kwargs):
        before = set(runs._HELD)
        try:
            return command(*args, **kwargs)
        finally:
            for task_id in [t for t in list(runs._HELD) if t not in before]:
                runs.release_fully(kwargs.get("conn"), task_id)
    return wrapped


def _describe(e):
    if isinstance(e, safety.SafeError):
        return str(e)
    return f"unexpected error: {type(e).__name__}"


def _dedupe(items):
    return list(dict.fromkeys(items))


def _refusals(config, environ, settings_paths):
    """Every reason to refuse before anything is logged or sent. route and check share them."""
    return _dedupe(
        safety.check_env({**environ, **config})
        + safety.billing_problems(environ)
        + safety.billing_problems(config)
        + safety.check_claude_settings_files(settings_paths)
    )


CLAUDE_SETUP = "Claude is required for every task: see Setup, Claude (docs/SETUP.md)"


def _claude_refusal(available, out):
    """Build brief 24 (decision 2): `route`, `relay` and `split` refuse every task while Claude isn't available, before
    any row, with the reason and its Setup row. `available` is the command's availability gate (router/availability.py);
    None (a caller that hands none) checks nothing. True when it refused."""
    if available is None:
        return False
    found = available("claude")
    if found.available:
        if found.why:  # brief 24, the owner's decision 2 after F: a sign-in check that didn't answer; the call decides
            out(f"{found.why}.")
        return False
    receipt.mark(out, code=found.code)
    out(f"Refused: {found.why}. {CLAUDE_SETUP}. Nothing was logged or sent.")
    return True


def _gate(roster, config):
    """Build brief 24 (decision 1): this command's availability gate, with the checks router/online.py makes (never a
    model call, never the webhook), run side by side for the agents a task needs; an installed version is read only when
    a safety-check failure on record needs one."""
    return availability.Gate(roster, config, checks=online.CHECKS, run_all=online.run_all, probe_path=PROBE_STATE,
                             versions={"chatgpt": codex_probe.codex_version, "cursor": cursor_worker.installed_version})


def _refuse_problems(out, problems, config, environ, settings_paths, tail="Nothing was logged or sent."):
    """_refusals' problems and the tail line, printed as every command always has. Brief 21: the JSON's reason_code is
    billing_switch when a per-token switch is set, else setup (read from the switches, never from the lines)."""
    receipt.mark(out, code="billing_switch" if safety.bills_per_token(environ, config, settings_paths) else "setup",
                 command=True)
    for problem in problems:
        out(f"Refused: {problem}")
    out(tail)


# Which local call (Claude or ChatGPT) is running, so a Ctrl+C can tell a check round from the
# task's first call (and a relay stage from the chain's first call).
_STAGE = {"task_id": None, "kind": None, "agent": None, "stage": None, "role": None}
_CHECK = object()  # _relay_step's answer when every stage is done and the checker loop takes over
_TOOK = object()   # brief 24 (decision 6): _take_over made the takeover's call; the loop goes round
BACKDATE_MINUTES = None  # brief 24 (C8): SR_INJECT_OVERDUE; main sets it for one command on a scratch log only
GROK_SKIPPED = takeover.GROK_SKIPPED  # brief 24 (the owner's C11)
# Web search is on only for the calls that need the open web (build brief 3, the owner's choice;
# the three web skills since rules v2.9). The rules themselves live in router/checking.py.
LIVE_SEARCH_SKILLS = checking.WEB_SKILLS


SPLIT_PROJECT_REFUSAL = ("Refused: --project on sr split is refused in version 2; pieces carry no project. "
                         "Nothing was logged or sent.")
# Rules v2.27, Memory, "The tag": `--chat` is accepted by route and relay (and with an override), refused with --project
# (one tag per task) and on a split, as --project is. Both refusals come in main, before any row.
SPLIT_CHAT_REFUSAL = "Refused: --chat on sr split is refused in version 2; pieces carry no tag. Nothing was logged or sent."
ONE_TAG_REFUSAL = "Refused: one tag per task: --chat with --project. Nothing was logged or sent."


def _chat_refusal(chat):
    """Why `--chat <name>` cannot be taken, or None: the name's shape (lower case letters, digits and -)."""
    if not isinstance(chat, str) or not log.PROJECT_NAME.fullmatch(chat):
        return f"a chat name is lower case letters, digits and - (not {safety.one_line(str(chat))!r})"
    return None


def _say_new_chat(conn, chat, out):
    """`new chat: <name>` on the first task with a name the log has not seen (a typo is seen, not refused)."""
    if chat is not None and not log.chat_exists(conn, chat):
        out(f"new chat: {chat}")


def _project_refusal(conn, project):
    """Rules v2.25, intake: why `--project <name>` cannot be taken, or None. Before any row: the name is in the
    registry (else the list), its HANDOFF.md can be read, and no task of the project is open (queued or sent).
    Brief 21: (reason_code, the reason)."""
    try:
        registry = projects.read_registry()
    except projects.ProjectError as e:
        return "project_unknown", f"{safety.one_line(e)}"
    if project not in registry:
        if not registry:
            return "project_unknown", f"no project {safety.one_line(project)}: the registry is empty (sr project add <name> <path>)"
        return "project_unknown", f"no project {safety.one_line(project)}. Projects: {', '.join(sorted(registry))} (sr project list)"
    try:
        projects.read_handoff(registry[project])
    except projects.ProjectError as e:
        return "handoff_unreadable", f"project {project}: {safety.one_line(e)}"
    open_row = log.open_task_for(conn, project)
    if open_row is not None:
        return "project_busy", f"project {project} has task {open_row['n']} open ({open_row['status']}). Finish or cancel it first"
    return None


def _project_presets(loaded):
    """The presets `--project` may run on (rules v2.25, Relay): a named checker after a chain that ends in one
    agent's build; never a check stage, review stages or a tally."""
    return [name for name, p in loaded.presets.items() if presets.takes_project(p)]  # brief 23: status reads the same


def _now():
    """The local time, for the date on a handoff entry (patched in tests)."""
    return datetime.now()


def _project_entry(conn, task_id, out, *, force=False):
    """Rules v2.25, "When the entry is written": the one place the router writes a task's entry into its project's
    HANDOFF.md, called after every ending (delivered, failed check, failed, stopped, returned, timed out). Once per
    ending: the write record on the task row names the ending it was made for, so a fallback or a resume gets its own
    entry while the earlier line stays. Nothing on a cancel. `force` writes again (tests)."""
    row = log.get_task(conn, task_id)
    name = log.project_of(row) if row is not None else None
    if not name:
        return
    calls = log.calls_for(conn, task_id)
    state = f"{row['status']}/{row['check_state']}/{len(calls)}"
    writes = log.handoff_of(row)
    if writes and writes[-1].get("state") == state and not force:
        return
    step = checking.ending_of(row, calls) if row["status"] == "done" else None
    delivered = step.result if step is not None else None
    root = media.MEDIA_ROOT.parent  # the image paths as `sr show` prints them: media/out/<task-id>/<name>.png
    images = [str(p.relative_to(root)) if p.is_relative_to(root) else str(p) for p in media.outputs(task_id)]
    found = context.entry_for(row, calls, date=f"{_now():%Y-%m-%d}", delivered_text=delivered, images=images)
    if found is None:
        return
    entry, kind = found
    folder = projects.folder_of(name)
    if folder is None:
        out(f"No handoff entry for #{row['n']}: project {name} is no longer registered.")
        return
    try:
        lines, start = projects.write_entry(folder, entry)
    except projects.ProjectError as e:
        out(f"No handoff entry for #{row['n']}: {safety.one_line(e)}.")
        return
    log.add_handoff_write(conn, task_id, {"kind": kind, "text": entry, "lines": lines, "block_start": start,
                                          "state": state})
    out(f"HANDOFF.md: {'entry' if kind == 'entry' else 'line'} for #{row['n']} written ({name}, {lines} lines).")
    warning = projects.size_warning(lines, start)
    if warning:
        out(warning)


def _say_memory_unavailable(conn, task_id, record, out):
    """Rules v2.27, "Down": one line to the owner on the first call of a task that found the store unreachable."""
    if not record or not record.get("unavailable"):
        return
    earlier = [c for c in log.calls_for(conn, task_id) if (log.call_memory_of(c) or {}).get("unavailable")]
    if not earlier:
        out("memory: unavailable; this task runs without its memory block")  # brief 23 (decision 5): never "sr memory"


def _memory_store(conn, task_id, out, *, hindsight, secrets):
    """Rules v2.27, "When": right after the handoff entry at every ending, the one retain for a delivered tagged
    task (router/memory.py, store): once per ending, logged on the task row, one line to the owner, never a change to
    the task's status or output, nothing retried. No store given (tests): nothing happens."""
    if hindsight is None:
        return
    row = log.get_task(conn, task_id)
    if row is None or not log.tag_of(row):
        return
    found = memory.store(conn, row, log.calls_for(conn, task_id), hindsight, secrets)
    if found is None:
        return
    record, line = found
    log.add_memory_write(conn, task_id, record)
    out(line)


RECALL_REDO_LINE = ("Its first call ran without the memory block, so this one would too: send the task again as a new task; "
                    "the router starts memory when that task needs it.")
RECALL_REDO_LINE_OFF = ("Its first call ran without the memory block, so this one would too: memory is off in settings, so "
                        "the router never starts the store.")


def _recall_redo_line():
    """Brief 23 (decision 5, the owner's change 1): the redo line by the memory setting (`off` never starts the store)."""
    return RECALL_REDO_LINE_OFF if settings.memory_mode() == "off" else RECALL_REDO_LINE
_CALL_WORDS = {"do": "first call", "check": "check", "fix": "fix round", "recheck": "re-check"}


def _recall_memory_problem(task, mem, hindsight, reuse):
    """Rules v2.29 (the owner, 2026-10-20, after live #103; amended before the merge): a tagged recall task never calls
    an agent without its memory. Asked before every call such a task would make. Only a call that does a fresh recall
    (the first call) checks the store: "store" when there is no store or its recall found the store unreachable. A
    call that reuses a saved block (a re-ask, a check, fix or re-check round, a fallback, a resume) uses that block
    without asking the store; "record" only when the saved block was itself unavailable (its first call ran without
    one, as live #103 did before this rule). None when the call may go. Any other task, and an untagged one, is not
    asked (decision 12 stands)."""
    if task["skill"] != routing.NEEDS_TAG or not log.tag_of(task):
        return None
    if hindsight is None or mem is None:  # memory off: no block could ride, fresh or saved
        return "store"
    if mem.get("unavailable") or mem.get("off"):  # brief 27: an off record is no store, fresh or saved
        return "record" if reuse is not None else "store"
    return None


def _recall_came_back(conn, task, agent, kind, problem, out):
    """The task comes back before the call (rules v2.29): `returned` with the reason, one line, the project's stopped
    line. Returns _attach_context's refusal shape: (None, exit code, None)."""
    task_id, reason = task["task_id"], routing.no_store_for_recall(settings.memory_mode())
    with _hold_interrupts():
        try:
            log.return_for_memory(conn, task_id, reason)
        except log.StateError:
            receipt.mark(out, code="state_changed")
            out(f"{task_id} is already {_status_text(log.get_task(conn, task_id))}.")
            return None, 1, None
    receipt.mark(out, code="memory_down")
    if log.calls_for(conn, task_id):
        what = _CALL_WORDS.get(kind, kind or "call")
        out(f"{task_id} came back to you: {reason}. The {what} by {agent} was not sent; nothing was delivered.")
    else:
        out(f"{task_id} came back to you: {reason}. Nothing was sent to an agent.")
    if problem == "record":
        out(_recall_redo_line())
    _project_entry(conn, task_id, out)
    return None, 4, None


def _attach_context(conn, task, agent, prompt, secrets, out, *, hindsight=None, reuse=None, kind=None):
    """The handoff block, then the memory block, on a call about to be sent (rules v2.25 and v2.27): (prompt, context
    record, memory record), or (None, exit code 4, None) when the task came back to the owner instead (the handoff still
    looks like it holds a key, or the file is gone; or, rules v2.29, a tagged recall task's memory can't be had).
    `hindsight` is the store's client; `reuse` the earlier call row whose block this call gets again (router/memory.py,
    for_call); `kind` the call about to be sent (do, check, fix, recheck, stage, reask), for the come-back line."""
    try:
        prompt, record, mem = context.attach(prompt, task, agent, secrets, conn=conn, hindsight=hindsight, reuse=reuse)
    except (context.ContextRefused, projects.ProjectError) as e:
        task_id = task["task_id"]
        short = f"handoff line {e.line} looks like a key" if isinstance(e, context.ContextRefused) else safety.one_line(e)
        folder = projects.folder_of(log.project_of(task))
        where = f" (HANDOFF.md in {safety.one_line(str(folder))})" if folder else ""
        code = "handoff_key" if isinstance(e, context.ContextRefused) else "handoff_unreadable"  # brief 21: from the exception
        with _hold_interrupts():
            try:
                log.return_for_context(conn, task_id, short, code)
            except log.StateError:
                receipt.mark(out, code="state_changed")
                out(f"{task_id} is already {_status_text(log.get_task(conn, task_id))}.")
                return None, 1, None
        receipt.mark(out, code=code)
        out(f"{task_id} came back to you: {safety.one_line(e)}{where}. Nothing was sent. Fix the line and run the "
            "task again.")
        _project_entry(conn, task_id, out)
        return None, 4, None
    problem = _recall_memory_problem(task, mem, hindsight, reuse)
    if problem:
        return _recall_came_back(conn, task, agent, kind, problem, out)
    _say_memory_unavailable(conn, task["task_id"], mem, out)
    return prompt, record, mem


@_releases_its_runs
def cmd_route(task, *, conn, config, roster, environ, settings_paths, label, post, worker, chatgpt=None,
              codex_login=None, cursor=None, cursor_ready=None, ask=None, fetch=None, close=None, sleep=None, clock=None, wait=False, source="cli",
              files=(), frames=None, drop_folder=None, ask_attach=None, convert=None, pages=None, claude_ready=None,
              web=False, project=None, chat=None, hindsight=None, skill=None, answers=None, available=None,
              chatgpt_ready=None, out=print):
    """Route one task. `project` (rules v2.25) is the registered project name from --project, or None; `chat`
    (rules v2.27) the chat name from --chat, or None (main refuses both together); a task whose skill is recall
    with neither comes back after Jev's row, before any agent call (rules v2.28, Jev); `hindsight` the memory store's
    client (main passes memory.client(requests.request); None means no store, so no block and no retain).
    `config` is the .env values; `roster` is the checked config files;
    `label` asks Jev (main passes jev.label with the key from .env; tests pass a fake).
    `chatgpt` runs a prompt through Codex (None when ChatGPT isn't configured); `codex_login`
    says whether Codex is signed in with ChatGPT, checked once per command.
    `ask` reads the owner's answer when Jev can't label the task; None means there is no terminal
    to ask in, so the task comes back instead. With wait=True a Grok task is followed until its
    result arrives; fetch, close, sleep and clock are then required (main passes the real ones).
    `files` are the paths from --file; `frames` pulls still frames from a video (media.extract_frames).
    `drop_folder` is the drop folder from config/settings.json and `ask_attach` reads the owner's y/N
    (None without a terminal, and then the folder is ignored); `convert` turns a HEIC into a jpg;
    `pages` renders a PDF's first pages to png (media.extract_pages)."""
    problems = _refusals(config, environ, settings_paths)
    if problems:
        _refuse_problems(out, problems, config, environ, settings_paths)
        return 2
    if _claude_refusal(available, out):  # brief 24 (decision 2): before any row, Jev included
        return 2

    tag, clean = routing.parse_override(task, roster.names)
    clean = safety.redact(clean, _secrets(config))  # brief 22 (decision 10): before Jev and before the row
    if tag and tag not in roster.live:
        receipt.mark(out, code="not_live")
        out(f"Refused: {tag} is not live yet, so @{tag} can't be used. Nothing was logged or sent.")
        return 2
    if tag and available is not None and not available(tag).available:  # brief 24 (decision 5): never falls back
        found = available(tag)
        receipt.mark(out, code=found.code)
        out(f"Refused: @{tag} can't be used: {found.why}. An override never goes to another agent. "
            "Nothing was logged or sent.")
        return 2
    if not clean.strip():
        receipt.mark(out, code="bad_task")
        out("Refused: the task is empty. Nothing was logged or sent.")
        return 2
    if clean.lstrip().startswith("/"):
        receipt.mark(out, code="bad_task")
        out("Refused: a task can't start with / (claude could read it as a slash command). "
            "Nothing was logged or sent.")
        return 2
    floor = None
    if skill is not None or answers is not None:  # brief 22 (decision 2): the owner's answer by flag; Jev is skipped
        refused = _skill_refusal(conn, roster, tag, skill, answers, clean)
        if isinstance(refused, tuple):
            receipt.mark(out, code=refused[0])
            out(f"Refused: {refused[1]}. Nothing was logged or sent.")
            return 2
        floor = refused
        if floor is not None:  # the task as it was: its tag, --web and files come from the floor row
            given = {"--project": (project, log.project_of(floor)), "--chat": (chat, log.chat_of(floor)),
                     "--web": (web or None, log.web_of(floor) or None)}
            wrong = [flag for flag, (value, floor_value) in given.items() if value is not None and value != floor_value]
            if files or wrong:
                receipt.mark(out, code="flag_refused")
                what = "--file" if files else wrong[0]
                out(f"Refused: {what} with --answers: #{floor['n']}'s task goes again as it was (its tag, --web and files "
                    "come from it). Nothing was logged or sent.")
                return 2
            project, chat, web = log.project_of(floor), log.chat_of(floor), log.web_of(floor)
    if project is not None:  # rules v2.25: every --project refusal before any row or call
        if tag:
            receipt.mark(out, code="override_refused")
            out(f"Refused: an override prefix with --project is refused (@{tag}): an override may run unchecked, and a "
                "project's handoff is never written unchecked. Nothing was logged or sent.")
            return 2
        refused = _project_refusal(conn, project)
        if refused:
            receipt.mark(out, code=refused[0])
            out(f"Refused: {refused[1]}. Nothing was logged or sent.")
            return 2
    if chat is not None:  # rules v2.27: the shape only; no registry, nothing to create
        refused = _chat_refusal(chat)
        if refused:
            receipt.mark(out, code="bad_name")
            out(f"Refused: {refused}. Nothing was logged or sent.")
            return 2
    cursor_ok = None
    if tag == "cursor":  # rules v2.28 with the owner's 20 Oct change: ready before any row, or refused with the reason
        cursor_ok = _cursor_readiness(cursor, cursor_ready)
        if not cursor_ok[0]:
            receipt.mark(out, code=cursor_ok.code)
            out(f"Refused: {cursor_ok[1]}. Nothing was logged or sent.")
            return 2
    dropped = _offer_drop(drop_folder, ask_attach, out, skip=files) if floor is None else []
    # brief 23 (decision 8): a --file at the drop folder's top level moves to sent/<task_id>/ once attached, as a drop does
    given_in_folder = [Path(f) for f in files if drop.at_top_level(drop_folder, f)] if floor is None else []
    task_id = ids.new_task_id()
    receipt.mark(out, task_id=task_id)  # brief 21: the JSON names it once its row exists
    if floor is not None:  # brief 22: the floor row's own copies, taken in again under the new task
        files = [media.in_dir(floor["task_id"]) / f["name"] for f in log.files_of(floor)]
    with tempfile.TemporaryDirectory(prefix="sr-intake-") as temp:
        try:
            sources, originals = _convert_all(list(files) + dropped, Path(temp), convert or drop.convert_heic)
        except drop.DropError as e:
            receipt.mark(out, code="bad_file")
            out(f"Refused: {safety.one_line(e)}. Nothing was logged or sent.")
            return 2
        if _file_holds_a_secret(list(sources) + list(originals), _secrets(config)):
            receipt.mark(out, code="bad_file")
            out("Refused: a file name holds a value from .env; rename the file. Nothing was logged or sent.")
            return 2
        problems = media.check_files(sources)  # before the log row and before Jev (rules v2.10, Media)
        if problems:
            receipt.mark(out, code="bad_file")
            for problem in problems:  # a problem names the file as it is, so it prints through one_line
                out(f"Refused: {safety.one_line(problem)}")
            out("Nothing was logged or sent." + (" The drop folder is as it was." if dropped else ""))
            return 2
        if sources and tag in routing.NO_FILES_FOR:  # rules v2.10 and v2.28: never a file to Grok or Cursor
            receipt.mark(out, code="files_to_agent")
            out(f"Refused: @{tag} can't take files; a file goes only to Claude and ChatGPT. Nothing was logged or sent.")
            return 2
        records = []
        if sources:
            try:
                records = _take_in(task_id, sources, frames or media.extract_frames, pages or media.extract_pages)
            except media.MediaError as e:
                media.remove_task_folders(task_id)
                receipt.mark(out, code="bad_file")
                out(f"Refused: {e}. Nothing was logged or sent.")
                return 2
    moving = given_in_folder + dropped
    if moving:
        dest = drop.move_sent(drop_folder, task_id, moving)
        for record, original in zip(records, originals):
            if original in moving:
                record["moved_to"] = str(dest)
        out(f"Moved {len(moving)} file(s) from the drop folder to {dest}/.")
    for record, original in zip(records, originals):
        if original.name != record["name"]:
            record["original"] = original.name
    if floor is not None:  # what the owner's files were called, and where the drop folder moved them, as the floor row says
        for record, was in zip(records, log.files_of(floor)):
            for key in ("original", "moved_to"):
                if was.get(key):
                    record[key] = was[key]
    secrets = _secrets(config)
    deps = SimpleNamespace(config=config, post=post, worker=worker, chatgpt=chatgpt, codex_login=codex_login,
                           codex_ok=None, cursor=cursor, cursor_ready=cursor_ready, cursor_ok=cursor_ok, fetch=fetch, close=close,
                           sleep=sleep, clock=clock, wait=wait, presets=None,
                           live=roster.live, claude_ready=claude_ready, hindsight=hindsight, chatgpt_ready=chatgpt_ready,
                           available=available, roster=roster)
    _STAGE.update(task_id=None, kind=None, agent=None, stage=None, role=None)
    try:
        # Every Jev call that used tokens ends in a log row, so a Ctrl+C here waits until the
        # row is written. One row per task, logged before anything else happens.
        with _hold_interrupts() as held:
            if skill is not None:  # brief 22 (decision 2): the owner's label; Jev is not asked
                answer = {"status": "not_asked", "tokens": 0}
            else:  # Jev gets the owner's text plus one line per file; the log keeps the text and the files apart.
                answer = label(media.jev_text(clean, records), task_id=task_id,
                               tokens_this_month=log.jev_tokens_this_month(conn))
            first_of_chat = chat is not None and not log.chat_exists(conn, chat)
            try:
                log.add_task(conn, task_id, clean, source, answer, files=records, web=web, project=project, chat=chat,
                             run=runs.me(), owner_label=skill is not None,
                             answers=floor["task_id"] if floor is not None else None)  # brief 22: born with its run
            except log.StateError:
                receipt.mark(out, code="already_used")
                out(f"Refused: #{floor['n']} was answered or closed a moment ago. Nothing was logged or sent.")
                media.remove_task_folders(task_id)
                return 2
            runs.adopt(task_id)
        if first_of_chat:
            out(f"new chat: {chat}")
        if held.pressed:
            raise KeyboardInterrupt
        has_files, tagged = bool(records), project is not None or chat is not None
        table = _routing_table(available, roster, skill or answer.get("label"))  # brief 24: availability, side by side
        if skill is not None:  # brief 22: the skill table routes the owner's answer, as after the floor prompt
            decision = routing.decide(answer, roster, answer=skill, can_ask=False, files=has_files, tagged=tagged,
                                      available=table)
        else:
            decision = routing.decide(answer, roster, override=tag, can_ask=ask is not None, files=has_files, tagged=tagged,
                                      available=table)
        if decision.action == "ask":
            out(_jev_text(answer, roster))
            choice = _ask_for_skill(ask, roster, out)
            decision = routing.decide(answer, roster, override=tag, answer=choice, files=has_files, tagged=tagged,
                                      available=table)
        if decision.action == "return":
            return _came_back(conn, task_id, answer, decision, roster, out)
        try:
            _set_route(conn, task_id, decision, roster)
        except log.StateError:
            receipt.mark(out, code="state_changed")
            out(f"{task_id} is already {_status_text(log.get_task(conn, task_id))}. Nothing was sent.")
            return 1
        if decision.reason == "override" and decision.skill is None:
            out(_jev_text(answer, roster))
        out(_route_text(task_id, answer, decision, roster))
        return _run_loop(conn, task_id, deps, secrets, out)
    except KeyboardInterrupt:
        return _after_interrupt(conn, task_id, secrets, out, hindsight=hindsight)


def _routing_table(available, roster, skill=None):
    """Brief 24 (decisions 3 and 4): what routing.decide reads for availability: the command's gate, its answers for the
    skill's candidates (best, interim, second, Claude, ChatGPT) checked side by side first; None without a gate (today's
    table: a live agent is available)."""
    if available is None:
        return None
    row = roster.skills.get(skill) if skill else None
    if row is not None:
        available.of(list(dict.fromkeys(routing.doers(row) + routing.checkers(row))))
    return available


def _skill_refusal(conn, roster, tag, skill, answers, clean):
    """Brief 22 (decision 2, Phase 0 choice 8): (reason_code, why) when `--skill` / `--answers` can't be taken, else the
    floor row `--answers` names (None without it). Before any row and before Jev."""
    if skill is None:
        return "usage", "--answers <n> goes with --skill <key>: your label for the floor row's task"
    if tag:
        return "flag_refused", f"--skill with an override prefix (@{tag}): the agent is already chosen"
    if skill not in roster.skills:
        if skill.lower() in ("none", "0", "none_of_these"):
            return "usage", "--skill takes a skill; a task none of them fits is closed with sr cancel <n>"
        return "usage", f"no skill {safety.one_line(skill)}. Skills: {', '.join(roster.skill_order)}"
    if answers is None:
        return None
    row, missing, code = log.find_task(conn, str(answers))
    if row is None:
        return code, safety.one_line(missing).rstrip(".")
    n = row["n"]
    if _mode(row) == "piece":
        return "wrong_state", f"#{n} is a piece: its split's approval labels it (sr split --go <split> --answer y --skill <k>=<key>)"
    if not (row["status"] == "returned" and row["reason_code"] == "needs_label"):
        return "wrong_state", f"#{n} is not a Jev floor question waiting for its label (it is {_status_word(row)})"
    if row["answered_by"]:
        return "already_used", f"#{n} was answered already ({row['answered_by']})"
    if row["task"] != clean:
        return "bad_task", f"the text is not #{n}'s, byte for byte: --answers sends #{n}'s task again as it was"
    return row


def _set_route(conn, task_id, decision, roster):
    """Write a routing decision on a queued task: `route`'s, and a piece's at the approval (rules v2.18)."""
    log.set_route(conn, task_id, agents=roster.names, agent=decision.agent, route_reason=decision.reason,
                  skill=decision.skill, skill_source=decision.skill_source, checker=decision.checker,
                  check_state=decision.check_state, check_note=decision.check_note)


@_releases_its_runs
def cmd_relay(preset_name, task, *, conn, config, roster, loaded, environ, settings_paths, post, worker, chatgpt=None,
              codex_login=None, cursor=None, cursor_ready=None, fetch=None, close=None, sleep=None, clock=None, wait=False, source="cli", files=(),
              claude_ready=None, slots=(), project=None, chat=None, hindsight=None, available=None, chatgpt_ready=None,
              out=print):
    """`sr relay <preset> "task"` (rules v2.13): run a preset's chain, then the usual check, or, on a
    preset whose last stage is the check, that stage's verdict (never both), or, on a preset with
    review stages (versus, rules v2.16), the candidates with their reviews, awaiting the owner's pick. Jev is never called. Refused before any log row: a file, no or unknown or bad preset, an override
    prefix, an empty task, a task starting with /. `loaded` is the checked config/presets.json.
    Waits like `route` (wait=True in a terminal); otherwise `sr check` continues the chain.
    `slots` are the `--<slot> <agent>` flags (rules v2.21), [(slot, agent)]: every refusal comes here, before any
    row or call; the row stores the whole slot map and names the filled preset's doer and checker."""
    if files:  # before anything else (build brief 5, hard limits)
        receipt.mark(out, code="flag_refused")
        out("Refused: a relay task carries no files (rules v2.12). Nothing was logged or sent.")
        return 2
    problems = _refusals(config, environ, settings_paths)
    if problems:
        _refuse_problems(out, problems, config, environ, settings_paths)
        return 2
    if _claude_refusal(available, out):  # brief 24 (decision 2)
        return 2
    if not preset_name:
        receipt.mark(out, code="bad_preset")
        out('Refused: name a preset: sr relay <preset> "task". `sr relay --list` prints them. Nothing was logged or sent.')
        return 2
    if preset_name in loaded.problems:
        receipt.mark(out, code="bad_preset")
        out(f"Refused: preset {preset_name} can't run:")
        for problem in loaded.problems[preset_name]:
            out(f"  - {problem}")
        out("Nothing was logged or sent.")
        return 2
    preset = loaded.presets.get(preset_name)
    if preset is None:
        receipt.mark(out, code="bad_preset")
        out(f"Refused: no preset {safety.one_line(preset_name)}. Presets: {', '.join(loaded.names)} (`sr relay --list`). "
            "Nothing was logged or sent.")
        return 2
    table = _relay_table(available, preset, slots)  # brief 24 (decision 8): the slots' agents, checked side by side
    flagged, refused = presets.slot_refusals(preset, slots, roster, table)
    if not refused:  # anything else a preset may not do, asked of the filled preset as of the file
        refused = presets.problems(flagged.name, presets.as_entry(flagged), roster, tuple(SENDERS), relay.CONTRACTS,
                                   roles=relay.ROLES, verdicts=relay.VERDICTS)
    if refused:
        receipt.mark(out, code="slot_refused")
        for reason in refused:
            out(f"Refused: {reason}")
        out("Nothing was logged or sent.")
        return 2
    fills = []
    if table is not None:  # brief 24 (decision 8): a slot whose default isn't available is filled, or the task refused
        filled, fills, why = presets.fill_unavailable(preset, slots, roster, table, send_paths=tuple(SENDERS),
                                                      contracts=relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
        if filled is None:
            receipt.mark(out, code="slot_refused")
            out(f"Refused: {why}. Nothing was logged or sent.")
            return 2
        flagged = filled
    preset = flagged
    tag, clean = routing.parse_override(task, roster.names)
    clean = safety.redact(clean, _secrets(config))  # brief 22 (decision 10): before the row
    if tag:
        receipt.mark(out, code="override_refused")
        out(f"Refused: an override prefix on a relay task is refused (@{tag}); the preset already names the agents. "
            "Nothing was logged or sent.")
        return 2
    if not clean.strip():
        receipt.mark(out, code="bad_task")
        out("Refused: the task is empty. Nothing was logged or sent.")
        return 2
    if clean.lstrip().startswith("/"):
        receipt.mark(out, code="bad_task")
        out("Refused: a task can't start with / (claude could read it as a slash command). Nothing was logged or sent.")
        return 2
    refused = _grok_vote_refusal(preset, clean) or _cursor_length_refusal(preset, clean)
    if refused:
        receipt.mark(out, code="too_long")
        out(f"Refused: {refused} Nothing was logged or sent.")
        return 2
    if project is not None:  # rules v2.25: research-build and redteam only; every refusal before any row
        held = [s for s, a in presets.slot_map(preset).items() if a in presets.PROJECT_REFUSES]  # rules v2.28: no handoff to Cursor
        if held:
            receipt.mark(out, code="tag_refused")
            out(f"Refused: --project with cursor in slot {', '.join(held)} is refused: a Cursor slot on a --project task "
                "(rules v2.28, Cursor). Nothing was logged or sent.")
            return 2
        if preset_name not in _project_presets(loaded):
            receipt.mark(out, code="tag_refused")
            out(f"Refused: --project is not allowed on {preset_name} ({' and '.join(_project_presets(loaded))} only). "
                "Nothing was logged or sent.")
            return 2
        refused = _project_refusal(conn, project)
        if refused:
            receipt.mark(out, code=refused[0])
            out(f"Refused: {refused[1]}. Nothing was logged or sent.")
            return 2
    if chat is not None:  # rules v2.27: any preset; the shape only
        refused = _chat_refusal(chat)
        if refused:
            receipt.mark(out, code="bad_name")
            out(f"Refused: {refused}. Nothing was logged or sent.")
            return 2
    cursor_ok = None
    if "cursor" in presets.slot_map(preset).values():  # rules v2.28 with the owner's 20 Oct change: ready before any row
        cursor_ok = _cursor_readiness(cursor, cursor_ready)
        if not cursor_ok[0]:
            receipt.mark(out, code=cursor_ok.code)
            out(f"Refused: {cursor_ok[1]}. Nothing was logged or sent.")
            return 2
    task_id = ids.new_task_id()
    receipt.mark(out, task_id=task_id)
    secrets = _secrets(config)
    deps = SimpleNamespace(config=config, post=post, worker=worker, chatgpt=chatgpt, codex_login=codex_login,
                           codex_ok=None, cursor=cursor, cursor_ready=cursor_ready, cursor_ok=cursor_ok, fetch=fetch, close=close,
                           sleep=sleep, clock=clock, wait=wait, presets=loaded,
                           live=roster.live, claude_ready=claude_ready, hindsight=hindsight, chatgpt_ready=chatgpt_ready,
                           available=available, roster=roster)
    with _hold_interrupts():  # the row is written whole, with its route, before anything is sent
        first_of_chat = chat is not None and not log.chat_exists(conn, chat)
        log.add_task(conn, task_id, clean, source, {"status": "not_asked", "tokens": 0}, mode="relay", preset=preset_name,
                     slots=presets.slot_map(preset), project=project, chat=chat, run=runs.me())
        runs.adopt(task_id)  # brief 22 (decision 4): born with its run
        log.set_route(conn, task_id, agents=roster.names, agent=preset.doer, route_reason=presets.fills_reason(fills),
                      checker=preset.check_agent, check_state="pending")
    if first_of_chat:
        out(f"new chat: {chat}")
    chain = " -> ".join(f"{_stage_words(stage)} by {stage.agent}" for stage in preset.stages)
    check = preset.check_stage
    if preset.has_reviews:  # rules v2.16: the reviews are the checks; the owner picks
        out(f"{task_id}: relay {preset_name}: {chain}, then your pick.")
    elif preset.tallies:  # rules v2.24: the tally is the check
        out(f"{task_id}: relay {preset_name}: {chain}, then the tally.")
    else:
        by = f"stage {check.n} ({check.agent})" if check else preset.checker
        out(f"{task_id}: relay {preset_name}: {chain}, checked by {by}.")
    for found in fills:  # brief 24 (decision 8): the card and Terminal say which slot was filled and why
        out(f"Slot {found['slot']} filled by {found['agent']}: {found['why']}.")
    return run_relay(conn, task_id, deps, secrets, out)


def _relay_table(available, preset, flags):
    """Brief 24 (decision 8): the command's gate with the preset's slot agents, the flagged ones and the fill candidates
    checked side by side first; None without a gate (today's table: live flags)."""
    if available is None:
        return None
    names = [s.agent for s in preset.slots] + [agent for _, agent in flags if agent] + ["chatgpt", "claude"]
    available.of(list(dict.fromkeys(names)))
    return available


def _grok_vote_refusal(preset, task):
    """Decision 13 with the owner's flag B: a Grok voter gets the task alone, so `grok_prompt_limit` is never applied
    to its send; instead the whole prompt it would get is measured here, before any row or call, and a task that
    would carry it past the limit is refused with both lengths. None when it fits (or no slot holds Grok)."""
    if not preset.tallies:
        return None
    most, _ = settings.grok_prompt_limit()
    for slot in preset.slots:
        for n in slot.stages:
            stage = preset.stage(n)
            if stage.agent != "grok":
                continue
            prompt = relay.prompt_for(stage.role, task, None, search=False, task_alone=True)
            if len(prompt) > most:
                return (f"the task is too long for grok's vote (slot {slot.name}): its prompt would be {len(prompt)} "
                        f"characters, the task alone {len(task)}; grok's limit is {most}. Shorten the task, or put "
                        f"another agent in slot {slot.name}.")
    return None


def _cursor_readiness(cursor, cursor_ready):
    """The owner's change of 2026-10-20 (after live #102): the Cursor readiness check at intake, before any row, whenever
    a task would reach Cursor: the worker is configured, the sandbox pass is on the installed agent version, the
    command is signed in (router/cursor_worker.py, ready: two local reads, never a model call). A stale pin then
    spends no other agent's stage first. (ok, reason); the stage-time check in _send_cursor stays for `sr check`."""
    if cursor is None:
        return cursor_worker.Readiness((False, "Cursor isn't configured (no model in config/agents.json, or the config "
                                               "didn't load)"), "not_configured")
    if cursor_ready is None:
        return cursor_worker.Readiness((False, "cursor: readiness unknown (no check given)"), "not_configured")
    found = cursor_ready()
    ok, reason = tuple(found)
    return cursor_worker.Readiness((ok, reason), getattr(found, "code", None) or (None if ok else "probe_failed"))


def _cursor_length_refusal(preset, task):
    """Decision 2 (rules v2.28, Cursor): the prompt is the command's one argument, so a task whose Cursor prompt would
    pass cursor_worker.PROMPT_LIMIT characters is refused at intake with both lengths, before any row (as a Grok vote
    is measured). Measured on the task-alone build prompt with the opener; a review prompt, which carries the other
    candidate too, is guarded again by the worker at send time. None when it fits, or when no slot holds Cursor."""
    for slot in preset.slots:
        if slot.agent != "cursor":
            continue
        for n in slot.stages:
            stage = preset.stage(n)
            if getattr(stage, "input", None) != "task":
                continue
            prompt = cursor_worker.wrap(relay.prompt_for(stage.role, task, None, search=False, task_alone=True))
            if len(prompt) > cursor_worker.PROMPT_LIMIT:
                return (f"the task is too long for cursor (slot {slot.name}): its prompt would be {len(prompt)} characters, "
                        f"the task alone {len(task)}; cursor's limit is {cursor_worker.PROMPT_LIMIT}. Shorten the task, or "
                        f"put another agent in slot {slot.name}.")
    return None


def cmd_pick(words, *, conn, loaded, secrets=(), hindsight=None, out=print):
    """`sr pick <n> a|b|none` (rules v2.16, Relay): the owner picks a candidate of a versus task whose
    reviews are in. a or b: that candidate's stored text becomes the task's result, byte for byte,
    with its review as the task's check; none: the task fails with both candidates kept. The owner's
    command is the consent; there is no y/N. One pick per task. Nothing is sent to anyone. Every
    refusal says why, changes nothing and exits 2."""
    words = list(words)
    if len(words) < 2:
        receipt.mark(out, code="usage")
        out("Refused: say which task and which candidate: sr pick <n> a|b|none. Nothing was changed.")
        return 2
    choice = words[-1].strip().lower()
    text = " ".join(words[:-1]).strip()
    row, missing, code = log.find_task(conn, text)  # brief 21: a number, an id or a unique prefix of one
    if row is None:
        if code != "ambiguous_task":  # not found: named as typed, as before
            number = re.fullmatch(r"#?([0-9]+)", text)
            missing, code = (f"No task #{number.group(1)}." if number else f"No task {safety.one_line(text)}."), "unknown_task"
        receipt.mark(out, code=code)
        out(f"Refused: {safety.for_terminal(missing)} Nothing was changed.")
        return 2
    receipt.mark(out, task_id=row["task_id"])
    n = row["n"]
    preset = None
    if _mode(row) == "relay":  # rules v2.21: the task's filled preset, never the defaults
        preset, problem = presets.for_task(row, loaded)
        if preset is None and (loaded is None or row["preset"] in loaded.problems or row["preset"] in loaded.presets):
            receipt.mark(out, code="bad_preset")
            out(f"Refused: #{n}'s preset {row['preset']} can't be read from config/presets.json: {problem}. "
                "Nothing was changed.")
            return 2
    if preset is not None and preset.tallies:  # rules v2.24, decision 9
        return _vote_pick(conn, row, preset, choice, out, secrets=secrets, hindsight=hindsight)
    if choice == "c" and preset is not None and preset.has_reviews:
        receipt.mark(out, code="usage")
        out(f"Refused: #{n} is not a vote task; c is the third voter on a vote. Nothing was changed.")
        return 2
    if preset is None or not preset.has_reviews:
        receipt.mark(out, code="wrong_state")
        out(f"Refused: #{n} is not a versus task. Nothing was changed.")
        return 2
    already = relay.picked(row)
    if already is not None:
        receipt.mark(out, code="already_used")
        out(f"Refused: #{n} already picked: {already}. Nothing was changed.")
        return 2
    if not relay.awaiting_pick(row):
        receipt.mark(out, code="wrong_state")
        out(f"Refused: #{n} is not awaiting a pick (it is {_status_text(row)}). Nothing was changed.")
        return 2
    found = relay.candidates(log.calls_for(conn, row["task_id"]), preset)
    if len(found) != len(preset.review_stages) or any(c.verdict == "missing" for c in found):
        receipt.mark(out, code="wrong_state")
        out(f"Refused: #{n} does not have both reviews in its log. Nothing was changed.")
        return 2
    if choice not in log.PICKS:
        receipt.mark(out, code="usage")
        out(f"Refused: pick a, b or none (not {safety.one_line(choice)!r}). Nothing was changed.")
        return 2
    task_id = row["task_id"]
    with _hold_interrupts():
        try:
            if choice == "none":
                log.set_pick(conn, task_id, agents=tuple({c.agent for c in found} | {c.reviewer for c in found}),
                             choice="none")
            else:
                pick = next(c for c in found if c.letter == choice)
                log.set_pick(conn, task_id, agents=(pick.agent, pick.reviewer), choice=choice, result=pick.text,
                             agent=pick.agent, checker=pick.reviewer, verdict=pick.verdict)
        except log.StateError:
            receipt.mark(out, code="state_changed")
            out(f"Refused: #{n} is already {_status_text(log.get_task(conn, task_id))}. Nothing was changed.")
            return 2
    if choice == "none":
        out(f"#{n} {task_id}: picked none. The task failed (no pick); both candidates are kept "
            f"(`sr show {n} --stages`).")
        return 0
    out(f"#{n} {task_id}: picked {choice.upper()} ({pick.agent}), reviewed by {pick.reviewer}: "
        f"{pick.verdict.upper()}. It is the task's result (`sr show {n}`).")
    if pick.verdict == "fail":
        out(f"Warning: {pick.reviewer}'s review of {choice.upper()} said FAIL; picked anyway.")
    _memory_store(conn, task_id, out, hindsight=hindsight, secrets=secrets)  # rules v2.27: a picked candidate is stored
    return 0


def _vote_pick(conn, row, preset, choice, out, *, secrets=(), hindsight=None):
    """`sr pick` on a vote (rules v2.24, decision 9): only when the tally found no majority. a, b or c delivers that
    voter's stored text, byte for byte, unchecked; none fails the task with every answer kept. Refused, with
    nothing changed: a vote the tally decided, a second pick, a vote not waiting, a letter it has no voter for."""
    n, task_id = row["n"], row["task_id"]
    if relay.CHECKED_BY_VOTE.fullmatch(row["check_note"] or ""):
        decided = row["check_note"].removeprefix("checked-by-vote ")
        receipt.mark(out, code="already_used")
        out(f"Refused: #{n} already decided by vote {decided}. Nothing was changed.")
        return 2
    already = relay.picked(row)
    if already is not None:
        receipt.mark(out, code="already_used")
        out(f"Refused: #{n} already picked: {already}. Nothing was changed.")
        return 2
    if not relay.awaiting_pick(row):
        receipt.mark(out, code="wrong_state")
        out(f"Refused: #{n} is not awaiting a pick (it is {_status_text(row)}). Nothing was changed.")
        return 2
    found = relay.voters(log.calls_for(conn, task_id), preset)
    letters = [v.letter for v in found]
    if len(found) != len(preset.stages):
        receipt.mark(out, code="wrong_state")
        out(f"Refused: #{n} does not have every vote in its log. Nothing was changed.")
        return 2
    if choice not in letters + ["none"]:
        receipt.mark(out, code="usage")
        out(f"Refused: pick {', '.join(letters)} or none (not {safety.one_line(choice)!r}). Nothing was changed.")
        return 2
    with _hold_interrupts():
        try:
            if choice == "none":
                log.set_vote_pick(conn, task_id, agents=tuple({v.agent for v in found}), choice="none")
            else:
                pick = next(v for v in found if v.letter == choice)
                log.set_vote_pick(conn, task_id, agents=tuple({v.agent for v in found}), choice=choice,
                                  result=pick.text, agent=pick.agent)
        except log.StateError:
            receipt.mark(out, code="state_changed")
            out(f"Refused: #{n} is already {_status_text(log.get_task(conn, task_id))}. Nothing was changed.")
            return 2
    if choice == "none":
        out(f"#{n} {task_id}: picked none. The task failed (no majority, no pick); every answer is kept "
            f"(`sr show {n}`).")
        return 0
    out(f"#{n} {task_id}: picked {choice.upper()} ({pick.agent}): {safety.for_terminal(pick.answer or '')}. It is the "
        f"task's result, unchecked: no two voters agreed on it (`sr show {n}`).")
    _memory_store(conn, task_id, out, hindsight=hindsight, secrets=secrets)  # unchecked: never stored (choice 14)
    return 0


def _stage_words(stage):
    """A stage's role in words: "build", or "review of stage 1" for a review stage."""
    of = getattr(stage, "review_of", None)
    return f"review of stage {of}" if of is not None else stage.role


@_releases_its_runs
def cmd_resume(words, *, conn, config, roster, loaded, environ, settings_paths, post, worker, chatgpt=None,
               codex_login=None, fetch=None, close=None, sleep=None, clock=None, wait=False, claude_ready=None,
               hindsight=None, cursor=None, cursor_ready=None, available=None, chatgpt_ready=None, out=print):
    """`sr resume <n>` (rules v2.15, Resume): continue task n after Claude or ChatGPT stopped it on its
    plan limit. router/resume.py decides from the log alone; a refusal says why, writes nothing and
    exits 2. Otherwise this prints the plan, then the other of the two (the substitute) is sent what
    the stopped agent was sent, never its output. Only once that call returns is anything written:
    the task is reopened with the plan's doer and checker, and the substitute's row names the stopped
    call in `resume_of`. Then the usual loop runs: the rest of the chain, then the check. The owner's
    command is the consent; there is no y/N. A Ctrl+C during the substitute's call changes nothing."""
    problems = _refusals(config, environ, settings_paths)
    if problems:
        _refuse_problems(out, problems, config, environ, settings_paths)
        return 2
    row = _resume_target(conn, words, out)
    if row is None:
        return 2
    task_id, n = row["task_id"], row["n"]
    if not _take_run(conn, row, out, "be resumed"):
        return 2
    calls = log.calls_for(conn, task_id)
    preset = split.PRESET if _mode(row) == "split" else None  # a split's plan and integration resume like any call
    if _mode(row) == "relay":  # rules v2.21: the task's filled preset, never the defaults
        preset, problem = presets.for_task(row, loaded)
        if preset is None:
            receipt.mark(out, code="bad_preset")
            out(f"Refused: #{n} can't be resumed: {problem}. Nothing was logged or sent.")
            return 2
    plan = resume.decide(row, calls, live=roster.live, preset=preset)
    if not plan.ok:
        receipt.mark(out, code=plan.code)
        out(f"Refused: #{n} can't be resumed: {plan.reason.rstrip('.')}.")
        made = re.search(r"stage ([0-9])'s result stays unchecked", plan.reason or "")
        if made:
            out(f"Stage {made.group(1)}'s result is unchecked; `sr show {n} --stages` prints it.")
        out("Nothing was logged or sent.")
        return 2
    sub, secrets = plan.substitute, _secrets(config)
    view = {**dict(row), "status": "queued", "agent": plan.agent, "checker": plan.checker,
            "check_state": plan.check_state, "check_note": plan.check_note, "result": None, "failed_stage": None}
    try:
        prompt, web_search, files, searching = _resume_call(view, calls, plan, preset, claude_ready)
        # rules v2.25: the handoff, last; rules v2.27: the block the stopped call got; both before any call
        prompt, record, mem = context.attach(prompt, view, sub, secrets, conn=conn, hindsight=hindsight, reuse=plan.stopped)
    except (ValueError, context.ContextRefused, projects.ProjectError) as e:
        receipt.mark(out, code=_attach_refusal_code(e))
        out(f"Refused: #{n} can't be resumed: {safety.one_line(e)}. Nothing was logged or sent.")
        return 2
    problem = _recall_memory_problem(view, mem, hindsight, plan.stopped)  # rules v2.29: never a recall call without memory
    if problem:
        receipt.mark(out, code="memory_down")
        out(f"Refused: #{n} can't be resumed: {routing.no_store_for_recall(settings.memory_mode())}. Nothing was logged or sent.")
        if problem == "record":
            out(_recall_redo_line())
        return 2
    _say_memory_unavailable(conn, task_id, mem, out)
    if sub == "chatgpt":
        if chatgpt is None:
            receipt.mark(out, code="not_configured")
            out(f"Refused: #{n} can't be resumed: ChatGPT isn't configured (no model in config/agents.json). "
                "Nothing was logged or sent.")
            return 2
        if not (codex_login() if codex_login is not None else False):
            receipt.mark(out, code="signed_out")
            out(f"Refused: #{n} can't be resumed: Codex isn't signed in with ChatGPT: run `codex login` in Terminal "
                "(never an API key). Nothing was logged or sent.")
            return 2
        probed, why = tuple(chatgpt_ready()) if chatgpt_ready is not None else (True, None)  # brief 24 (decision 10)
        if not probed:
            receipt.mark(out, code="probe_failed")
            out(f"Refused: #{n} can't be resumed: {why}. Nothing was logged or sent.")
            return 2
    if sub == "cursor":  # brief 22 (decision 3): a process-ended Cursor call is made again by Cursor, when it is ready
        ready = _cursor_readiness(cursor, cursor_ready)
        if not ready[0]:
            receipt.mark(out, code=ready.code)
            out(f"Refused: #{n} can't be resumed: {ready[1]}. Nothing was logged or sent.")
            return 2
    for line in resume.describe(row, plan):
        out(line)
    if sub == "claude":
        call = functools.partial(worker, search=True) if searching == search.ALLOWED else worker
    elif sub == "cursor":
        def call(text):  # the prompt the Claude worker would get for the role, opened as every Cursor prompt is
            try:
                found = cursor(cursor_worker.wrap(text), call_id=plan.call_id)
            except cursor_worker.WorkerError as e:
                _keep_stream(task_id, plan.call_id, e, secrets)
                raise
            _keep_stream(task_id, plan.call_id, found, secrets)
            return found
    else:
        call = functools.partial(chatgpt, web_search=web_search)
    answer = None
    reason_code = None
    try:
        answer = call(prompt, files=files, tag=task_id) if files else call(prompt)
        text, failed = safety.redact(answer, secrets), False
    except KeyboardInterrupt:
        out(f"Stopped during the resume (Ctrl+C). Nothing changed: #{n} is still stopped; run `sr resume {n}` again.")
        return 130
    except Exception as e:
        text, failed = safety.redact(_describe(e), secrets), True
        reason_code = getattr(e, "code", None) if isinstance(e, safety.SafeError) else None
        answer = e  # a Cursor failure keeps what answered (its served record) on the row
    stage_kind = plan.kind in log.STAGE_KINDS
    with _hold_interrupts() as held:  # the reopen and the row are written together
        try:
            log.reopen_for_resume(conn, task_id, agents=roster.names, agent=plan.agent, checker=plan.checker,
                                  check_state=plan.check_state, check_note=plan.check_note)
        except log.StateError:
            receipt.mark(out, code="state_changed")
            out(f"{task_id} changed while the resume ran (it is {_status_text(log.get_task(conn, task_id))}), "
                "so this answer was not saved:")
            out(safety.for_terminal(text, secrets))
            return 1
        verdict = checking.read_verdict(text)[0] if not failed and plan.kind in ("check", "recheck") else None
        log.add_call(conn, plan.call_id, task_id, plan.kind, sub, status="failed" if failed else "done", text=text,
                     verdict=verdict, stage=plan.stage if stage_kind else None, role=plan.role if stage_kind else None,
                     reason_code=reason_code, resume_of=plan.stopped["call_id"],
                     search=_search_record(searching, None if failed else answer), context=record, memory=mem,
                     served=getattr(answer, "served", None))  # rules v2.28: a Cursor call's served record
        if failed and plan.kind == "do":
            log.set_failed(conn, task_id, text)
    if failed and plan.kind == "do":
        out(f"{task_id} failed: {safety.for_terminal(text, secrets)}")
        _project_entry(conn, task_id, out)
        deps = SimpleNamespace(presets=loaded, live=roster.live)
        line = _plan_limit_line(conn, task_id, deps)
        if line:
            out(line)
        return 1
    deps = SimpleNamespace(config=config, post=post, worker=worker, chatgpt=chatgpt, codex_login=codex_login,
                           codex_ok=True if sub == "chatgpt" else None, fetch=fetch, close=close, sleep=sleep,
                           clock=clock, wait=wait, presets=loaded, live=roster.live, claude_ready=claude_ready, hindsight=hindsight,
                           cursor=cursor, cursor_ready=cursor_ready, cursor_ok=(True, None) if sub == "cursor" else None,
                           available=available, chatgpt_ready=chatgpt_ready, roster=roster,
                           codex_probe_ok=(True, None) if sub == "chatgpt" else None)
    if held.pressed:
        out(f"Stopped (Ctrl+C). {sub}'s call was saved and #{n} is open again; run `sr check` to finish it.")
        return 130
    code = run_relay(conn, task_id, deps, secrets, out)
    hint = _piece_hint(conn, log.get_task(conn, task_id))
    if hint:
        out(hint)
    return code


@_releases_its_runs
def cmd_fallback(words, *, conn, config, roster, loaded, environ, settings_paths, post, worker, chatgpt=None,
                 codex_login=None, fetch=None, close=None, sleep=None, clock=None, wait=False, claude_ready=None,
                 hindsight=None, available=None, chatgpt_ready=None, out=print):
    """`sr fallback <n>` (rules v2.17, Fallback): redo task n after its result failed its check twice. The
    task's checker redoes it from what the original doer was sent plus the stored final fix list, never the
    failed result; the original doer checks the redo with the usual loop (collab: as the check stage).
    router/fallback.py decides from the log alone; a refusal says why, writes nothing and exits 2. The owner's
    command is the consent; there is no y/N. Nothing is written until the redo's call returns: then the task
    is reopened with the swapped pair and the redo's row names the original doer's call in `fallback_of`. A
    redo stopped by a plan limit or an error is logged and does not count; a Ctrl+C changes nothing."""
    problems = _refusals(config, environ, settings_paths)
    if problems:
        _refuse_problems(out, problems, config, environ, settings_paths)
        return 2
    row = _task_target(conn, words, out, "fallback")
    if row is None:
        return 2
    task_id, n = row["task_id"], row["n"]
    if not _take_run(conn, row, out, "fall back"):
        return 2
    calls = log.calls_for(conn, task_id)
    preset = presets.for_task(row, loaded)[0] if _mode(row) == "relay" else None  # rules v2.21: the filled preset
    if _mode(row) == "split":  # rules v2.18: ChatGPT integrates from the same pieces; Claude checks
        preset = split.PRESET
    plan = fallback.decide(row, calls, live=roster.live, preset=preset)
    if not plan.ok:
        receipt.mark(out, code=plan.code)
        out(f"Refused: #{n} can't fall back: {plan.reason}. Nothing was logged or sent.")
        return 2
    secrets = _secrets(config)
    try:
        prompt, web_search, files, searching = _fallback_call(row, calls, plan, preset, claude_ready)
        # rules v2.25: the handoff, last; rules v2.27: the block the replaced call got; both before any call
        prompt, record, mem = context.attach(prompt, row, plan.doer, secrets, conn=conn, hindsight=hindsight,
                                             reuse=plan.replaces)
    except (ValueError, context.ContextRefused, projects.ProjectError) as e:
        receipt.mark(out, code=_attach_refusal_code(e))
        out(f"Refused: #{n} can't fall back: {safety.one_line(e)}. Nothing was logged or sent.")
        return 2
    problem = _recall_memory_problem(row, mem, hindsight, plan.replaces)  # rules v2.29: never a recall call without memory
    if problem:
        receipt.mark(out, code="memory_down")
        out(f"Refused: #{n} can't fall back: {routing.no_store_for_recall(settings.memory_mode())}. Nothing was logged or sent.")
        if problem == "record":
            out(_recall_redo_line())
        return 2
    _say_memory_unavailable(conn, task_id, mem, out)
    if plan.doer == "chatgpt":
        if chatgpt is None:
            receipt.mark(out, code="not_configured")
            out(f"Refused: #{n} can't fall back: ChatGPT isn't configured (no model in config/agents.json). "
                "Nothing was logged or sent.")
            return 2
        if not (codex_login() if codex_login is not None else False):
            receipt.mark(out, code="signed_out")
            out(f"Refused: #{n} can't fall back: Codex isn't signed in with ChatGPT: run `codex login` in Terminal "
                "(never an API key). Nothing was logged or sent.")
            return 2
        probed, why = tuple(chatgpt_ready()) if chatgpt_ready is not None else (True, None)  # brief 24 (decision 10)
        if not probed:
            receipt.mark(out, code="probe_failed")
            out(f"Refused: #{n} can't fall back: {why}. Nothing was logged or sent.")
            return 2
    for line in fallback.describe(row, plan):
        out(line)
    if plan.doer == "claude":
        call = functools.partial(worker, search=True) if searching == search.ALLOWED else worker
    else:
        call = functools.partial(chatgpt, web_search=web_search)
    answer, reason_code = None, None
    try:
        answer = call(prompt, files=files, tag=task_id) if files else call(prompt)
        text, failed = safety.redact(answer, secrets), False
    except KeyboardInterrupt:
        out(f"Stopped during the redo (Ctrl+C). Nothing changed and it doesn't count: run `sr fallback {n}` again.")
        return 130
    except Exception as e:
        text, failed = safety.redact(_describe(e), secrets), True
        reason_code = getattr(e, "code", None) if isinstance(e, safety.SafeError) else None
    relay_stage = plan.stage is not None
    kind = "stage" if relay_stage else "do"
    with _hold_interrupts() as held:  # the reopen and the row are written together
        if not failed:
            check_state = "pending" if plan.checker else "unchecked"
            note = None if plan.checker else f"{plan.original}, the original doer, isn't live"
            try:
                log.reopen_for_fallback(conn, task_id, agents=roster.names, agent=plan.doer, checker=plan.checker,
                                        check_state=check_state, check_note=note)
            except log.StateError:
                receipt.mark(out, code="state_changed")
                out(f"{task_id} changed while the redo ran (it is {_status_text(log.get_task(conn, task_id))}), "
                    "so this answer was not saved:")
                out(safety.for_terminal(text, secrets))
                return 1
        log.add_call(conn, plan.call_id, task_id, kind, plan.doer, status="failed" if failed else "done", text=text,
                     stage=plan.stage if relay_stage else None, role=plan.role if relay_stage else None,
                     reason_code=reason_code, fallback_of=plan.replaces["call_id"],
                     search=_search_record(searching, answer), context=record, memory=mem)
    if failed:
        out(f"{plan.doer}'s redo failed: {safety.for_terminal(text, secrets)}")
        line = _plan_limit_line(conn, task_id, SimpleNamespace(presets=loaded, live=roster.live))
        out(line or f"#{n} is as it was. It doesn't count: run `sr fallback {n}` again.")
        return 1
    deps = SimpleNamespace(config=config, post=post, worker=worker, chatgpt=chatgpt, codex_login=codex_login,
                           codex_ok=True if plan.doer == "chatgpt" else None, fetch=fetch, close=close, sleep=sleep,
                           clock=clock, wait=wait, presets=loaded, live=roster.live, claude_ready=claude_ready, hindsight=hindsight,
                           available=available, chatgpt_ready=chatgpt_ready, roster=roster,
                           codex_probe_ok=(True, None) if plan.doer == "chatgpt" else None)
    if held.pressed:
        out(f"Stopped (Ctrl+C). {plan.doer}'s redo was saved and #{n} is open again; run `sr check` to finish it.")
        return 130
    code = run_relay(conn, task_id, deps, secrets, out)
    after = log.get_task(conn, task_id)
    if after["status"] == "done" and after["check_state"] == "failed":
        for line in _both_attempts_lines(after, log.calls_for(conn, task_id), preset, secrets):
            out(line)
    hint = _piece_hint(conn, after)
    if hint:
        out(hint)
    return code


def _fallback_call(row, calls, plan, preset, claude_ready=None):
    """The redo's call: what the original doer was sent, rebuilt by the same prompt builders with the
    fallback doer as the doer, then the paragraph and the stored final fix list. Returns (prompt,
    web_search, files, search state). Raises ValueError when the prompt would carry the failed result."""
    view = {**dict(row), "status": "queued", "agent": plan.doer, "checker": plan.checker, "check_state": "pending",
            "check_note": None, "result": None, "failed_stage": None,
            "route_reason": checking.FALLBACK_VIEW}  # brief 24: a redo's prompt never carries decision 9's line
    ready = _ready_once(SimpleNamespace(claude_ready=claude_ready))
    allowed = [row["task"], plan.fix_list]
    if plan.stage is None:
        step = checking.Step("do")
        searching = _call_search(view, step, ready)
        _, _, _, base, web_search = _plan_call(view, step, (), searching=searching)
        files = _delivery(view, step)
    elif getattr(preset, "revise_stage", None) is not None and plan.stage == preset.revise_stage.n:
        # rules v2.23, decision 12: the check agent builds from the task and the same attack list, never stage 1 or
        # the revision; the attack is not run again
        attacks = relay.accepted(log.fallback_view(calls), preset.revise_stage.against)["text"]
        allowed.append(attacks)
        searching = search.state(view, kind="stage", role="revise", agent=plan.doer, files=(), ready=ready)
        on = searching == search.ALLOWED
        base = relay.redo_prompt(row["task"], attacks, search=on, handoff=context.needs_handoff(view, plan.doer))
        web_search, files = "live" if on else "disabled", ()
    else:
        prior = relay.accepted(log.fallback_view(calls), plan.input_stage)["text"] if plan.input_stage else None
        allowed.append(prior)
        if _mode(row) == "split":  # the redo gets the same pieces block; a piece's own text is not a failed result
            plan_ = log.split_plan_of(row)
            allowed.append(split.pieces_text(plan_["inputs"], plan_["join"]))
        step = relay.StageStep("stage", row["task_id"], plan.stage, preset.stage(plan.stage), prior=prior,
                               agent=plan.doer, handoff=context.needs_handoff(view, plan.doer))  # the redo is the build
        base, _, web_search, searching = _stage_call(view, step, ready)
        files = ()
    prompt = fallback.prompt(base, plan.fix_list)
    fallback.assert_clean(prompt, plan.failed_texts, allowed=allowed)
    return prompt, web_search, files, searching


def _both_attempts_lines(row, calls, preset, secrets):
    """After a redo also failed its check twice (rules v2.17): the original result and its final fix
    list, then the redo and its final fix list, original first."""
    attempts = fallback.attempts(row, calls, preset)
    if len(attempts) != 2:
        return []
    lines = ["", "Both attempts failed their checks twice."]
    for title, attempt in zip(("Original result", "Redo"), attempts):
        lines += [f"{title} ({attempt.doer}):", safety.for_terminal(attempt.result or "", secrets),
                  f"Its final fix list ({attempt.checker}):", safety.for_terminal(attempt.fix_list or "", secrets)]
    return lines


def _take_run(conn, row, out, doing):
    """Build brief 22 (decision 4): hold the task's run for this command, or refuse (nothing logged or sent) when another
    process's run holds it, alive or ended (`sr check` marks an ended one first)."""
    why = runs.refusal(row)
    if why is None and runs.claim(conn, row["task_id"]):
        return True
    receipt.mark(out, code="wrong_state")
    out(f"Refused: #{row['n']} can't {doing}: {why or 'another command took it a moment ago'}. Nothing was logged or sent.")
    return False


def _task_target(conn, words, out, command):
    """The task a command names: a number from `sr log` (#n too), a task_id, or a unique prefix of one (rules v2.30,
    ids everywhere: log.find_task). None, with the reason printed, when there is no such task or more than one."""
    row, missing, code = log.find_task(conn, " ".join(words))
    if code == "usage":
        receipt.mark(out, code="usage")
        out(f"Refused: give a task number from `sr log` (for example `sr {command} 5`) or a task_id. "
            "Nothing was logged or sent.")
        return None
    if row is None:
        receipt.mark(out, code=code)
        out(f"Refused: {safety.for_terminal(missing)} Nothing was logged or sent.")
        return None
    receipt.mark(out, task_id=row["task_id"])
    return row


def _resume_target(conn, words, out):
    """The task `sr resume` names, as _task_target finds it."""
    return _task_target(conn, words, out, "resume")


def _attach_refusal_code(e):
    """Brief 21: the reason_code of a resume or fallback refused while its context was attached."""
    if isinstance(e, context.ContextRefused):
        return "handoff_key"
    return "handoff_unreadable" if isinstance(e, projects.ProjectError) else "stuck"


def _resume_call(view, calls, plan, preset, claude_ready=None):
    """What the stopped agent was sent, rebuilt by the same prompt builders from the rows before the
    stop, with the task row as it will be after the reopen (`view`: the substitute is its doer or
    checker). Returns (prompt, web_search, files, search state); search follows the call's preset
    and role, whichever agent does it (rules v2.15, Resume). A stopped re-ask is rebuilt as a fresh stage
    (the owner's D8). ValueError when the rows don't lead to the stopped call (never expected)."""
    stopped = plan.stopped
    before = [c for c in calls if c["call_id"] != stopped["call_id"]]
    if stopped["kind"] in log.STAGE_KINDS:
        if stopped["kind"] == "reask":
            before = [c for c in before if not (c["kind"] in log.STAGE_KINDS and c["stage"] == stopped["stage"])]
        step = relay.next_stage(view, before, preset)
        if step.action != "stage" or step.n != stopped["stage"]:
            raise ValueError(f"the log does not lead to stage {stopped['stage']} (it leads to {step.action})")
        step = dataclasses.replace(step, agent=plan.substitute)
        prompt, _, web_search, searching = _stage_call(view, step, _ready_once(SimpleNamespace(claude_ready=claude_ready)))
        return prompt, web_search, (), searching
    if stopped["kind"] == "fix" and checking.FIX_REASK in stopped["call_id"]:
        before = [c for c in before if c["kind"] != "fix"]  # a stopped fix re-ask is redone as a fresh fix (D8's shape)
    if stopped["kind"] == "do" and context.DO_REASK in stopped["call_id"]:
        before = [c for c in before if c["kind"] != "do"]  # rules v2.25: a stopped do re-ask is redone as a fresh first call
    step = checking.next_step(view, before)
    if step.action != plan.kind:
        raise ValueError(f"the log does not lead to the {plan.kind} (it leads to {step.action})")
    searching = _call_search(view, step, _ready_once(SimpleNamespace(claude_ready=claude_ready)))
    _, _, agent, prompt, web_search = _plan_call(view, step, before, searching=searching)
    if agent != plan.substitute:
        raise ValueError(f"the {plan.kind} would go to {agent}, not {plan.substitute}")
    return prompt, web_search, _delivery(view, step), searching


def _offer_drop(drop_folder, ask_attach, out, skip=()):
    """With a terminal: create the drop folder if missing, and when it holds files, name them and
    ask whether to attach them. Returns the files to attach (none on anything but y). A file `--file` already
    names (`skip`) is not offered, so it is never attached twice (build brief 23, decision 8)."""
    if drop_folder is None or ask_attach is None:
        return []
    drop.prepare(drop_folder)
    given = {_resolved(f) for f in skip}
    found = [p for p in drop.waiting(drop_folder) if _resolved(p) not in given]
    if not found:
        return []
    out(f"The drop folder has {len(found)} file(s):")
    for path in found:
        out(f"  {safety.one_line(path.name)} ({media.human_size(path.stat().st_size)})")
    answer = ask_attach(f"Attach these {len(found)} files? [y/N] ")
    if (answer or "").strip().lower() in drop.YES:
        return found
    out("Running with no files from the drop folder.")
    return []


def _resolved(path):
    try:
        return Path(path).resolve()
    except OSError:
        return Path(path)


def _convert_all(paths, temp, convert):
    """HEIC and HEIF become jpg (in a temp folder) before the checks; everything else passes
    through. Returns the sources for intake and, in the same order, the originals."""
    sources, originals = [], []
    for path in paths:
        path = Path(path)
        sources.append(convert(path, temp) if drop.needs_conversion(path) else path)
        originals.append(path)
    return sources, originals


def _take_in(task_id, files, frames, pages):
    """Copy the accepted files to media/in/<task-id>/, pull frames from a video and pages from a
    PDF. Returns the file records for the log. Raises media.MediaError when a pull fails."""
    records = []
    copies = media.copy_in(task_id, files)
    names = [c.name for c in copies]
    for copy in copies:
        k = media.kind(copy.name)
        if k == "video":
            pulled = frames(copy, media.frames_dir(task_id))
            records.append(media.record(copy, frames=len(pulled)))
        elif k == "pdf":  # brief 24 (decision 17): each PDF's pages in their own folder
            folder = media.pages_dir(task_id) / media.pages_folder(copy.name, names)
            folder.mkdir(parents=True, exist_ok=True)
            rendered, total = pages(copy, folder)
            records.append(media.record(copy, pages=len(rendered), total_pages=total))
        else:
            records.append(media.record(copy))
    return records


def _files_lines(row):
    lines, moved = [], None
    for f in log.files_of(row):
        tail = f", {f['frames']} frames" if f.get("frames") else ""
        if f.get("pages"):
            tail = f", {f['pages']} of {f['total_pages']} pages"
        was = f" (from {safety.one_line(f['original'])})" if f.get("original") else ""
        lines.append(f"  {f['name']} ({f['type']}, {media.human_size(f['size'])}{tail}){was}")
        moved = f.get("moved_to") or moved
    if moved:
        lines.append(f"  moved from the drop folder to {moved}/")
    return lines


# ---------- the check loop ----------

def _run_loop(conn, task_id, deps, secrets, out):
    """Repeat the next step until the task ends, or waits on a Grok call that we don't wait for.
    A relay task runs its stages first (router/relay.py), then the same check loop.
    When a plan limit stopped the task, the last line names `sr resume <n>` and the substitute, or
    says why it can't be resumed (rules v2.15). Returns the exit code."""
    code = _steps(conn, task_id, deps, secrets, out)
    line = _plan_limit_line(conn, task_id, deps)
    if line:
        out(line)
    line = _fallback_line(conn, task_id, deps)
    if line:
        out(line)
    return code


def _fallback_line(conn, task_id, deps):
    """The line after a task ended with its check failed twice (rules v2.17): `Run: sr fallback <n>  (…)`
    or `No fallback: <reason>`; None otherwise, and None when a stopped fallback is the last call (its
    plan-limit line already names the command)."""
    task = log.get_task(conn, task_id)
    if task is None:
        return None
    calls = log.calls_for(conn, task_id)
    if calls and log.fallback_of(calls[-1]) and calls[-1]["status"] == "failed":
        return None
    preset = _preset_for(task, deps)[0] if _mode(task) in ("relay", "split") else None
    if _mode(task) in ("relay", "split") and preset is None:
        return None
    return fallback.stop_line(task, calls, live=getattr(deps, "live", None), preset=preset)


def _plan_limit_line(conn, task_id, deps):
    """The stop line for a task a plan limit just stopped, or None (router/resume.py)."""
    task = log.get_task(conn, task_id)
    if task is None:
        return None
    preset = _preset_for(task, deps)[0] if _mode(task) in ("relay", "split") else None
    return resume.stop_line(task, log.calls_for(conn, task_id), live=getattr(deps, "live", None), preset=preset)


def _steps(conn, task_id, deps, secrets, out):
    while True:
        code = _take_over(conn, task_id, deps, secrets, out)  # brief 24 (decision 6): before any stop is written
        if code is _TOOK:
            continue
        if code is not None:
            return code
        task = log.get_task(conn, task_id)
        calls = log.fallback_view(log.calls_for(conn, task_id))  # rules v2.17: the redo's rows after a fallback
        if _mode(task) in ("relay", "split"):
            stepper = _split_step if _mode(task) == "split" else _relay_step
            code = stepper(conn, task, calls, deps, secrets, out)
            if code is None:
                continue
            if code is not _CHECK:
                return code
        step = checking.next_step(task, calls)
        if step.action == "finish" and step.ending is None and task["status"] in ("queued", "sent"):
            failed = checking._result_call(task, calls)  # brief 24: a first call nobody took over ends the task here
            if failed is not None and failed["status"] == "failed":
                return _fail(conn, task_id, _stopped_reason(failed, log.calls_for(conn, task_id)), secrets, out)
        if step.action == "finish":
            return _finish(conn, task, step, secrets, out, hindsight=getattr(deps, "hindsight", None))
        if step.action == "stop":  # rules v2.25: the doer missed its handoff contract after the one re-ask
            return _fail(conn, task_id, safety.redact(step.reason, secrets), secrets, out)
        if step.action == "wait":
            _note_grok(conn, task, step.call, deps)
            if not deps.wait:
                out(f"{_call_text(step.call)} is with grok. Not waiting; run `sr check` later for it.")
                return 0
            code = _wait_for_call(conn, task_id, step.call, deps, secrets, out)
            if code is not None:
                return code
            continue
        searching = _call_search(task, step, _ready_once(deps))
        call_id, kind, agent, prompt, web_search = _plan_call(task, step, calls, searching=searching)
        if step.action == "fix" and step.missing:
            out(f"The fix round by {agent} missed its contract; re-asked once for: " + "; ".join(step.missing) + ".")
        if step.action == "do" and step.missing:
            out(f"The first call by {agent} missed its contract; re-asked once for: " + "; ".join(step.missing) + ".")
        if agent == "grok":  # rules v2.19: at most one piece of a split out with Grok at a time
            holder = _grok_holder(conn, task)
            if holder is not None:
                out(f"#{task['n']} {task['task_id']} {split.held_words(holder)}.")
                return 0
        reuse = _reused_call(task, step, calls)  # rules v2.27: the check, fix and re-check get the block the doer got
        prompt, record, mem = _attach_context(conn, task, agent, prompt, secrets, out,
                                              hindsight=getattr(deps, "hindsight", None), reuse=reuse, kind=kind)
        if prompt is None:
            return record
        if agent == "grok" and kind in ("check", "recheck") and len(prompt) > settings.grok_prompt_limit()[0]:
            _skip_grok_check(conn, task, calls, len(prompt), deps, out)  # brief 24 (the owner's C11)
            continue
        code = SENDERS[agent](conn, task, call_id, kind, prompt, deps, secrets=secrets, out=out, web_search=web_search,
                              files=_delivery(task, step), searching=searching,
                              limited=kind in ("check", "recheck"), context=record, memory=mem)  # rules v2.21: a fix round is exempt
        if code is not None:
            return code


def _takes_over(deps):
    """Brief 24 (decision 6): the router takes over a stopped call only in a command with a gate (main always has one;
    a direct call without one keeps today's stops)."""
    return getattr(deps, "available", None) is not None


def _take_over(conn, task_id, deps, secrets, out, own=False):
    """Brief 24 (decisions 6 and 7): when the task's newest call stopped for a covered reason, hand it to the next agent
    at once (router/takeover.py decides), once per task. The task row takes the new doer, checker and check state; the
    takeover's call is `<stopped>-takeover`, made with what the stopped agent was sent (its files, handoff and saved
    memory block; never its output), its row naming the stopped call in `resume_of`. Terminal gets the card's words on
    one line. Returns None when nothing was taken over (the caller goes on as today and writes the stop), _TOOK once the
    call was made, or an exit code from it. `own`: route's own wait may take over the Grok call this command sent;
    the loop's step never does (with the overdue hook, the next check is another command's, as the brief's key reads)."""
    if not _takes_over(deps):
        return None
    task = log.get_task(conn, task_id)
    calls = log.calls_for(conn, task_id) if task is not None else []
    stopped = takeover.pending(task, calls) if task is not None else None
    overdue = None
    if stopped is None and task is not None:
        overdue = _overdue(task, calls, deps, own)  # decision 6: a Grok call still out at 2N, read as a stop
        if overdue is None:
            return None
        stopped, calls = overdue, [overdue if c["call_id"] == overdue["call_id"] else c for c in calls]
    preset = _preset_for(task, deps)[0] if _mode(task) in ("relay", "split") else None
    roster, gate = getattr(deps, "roster", None), deps.available
    if hasattr(gate, "of"):
        gate.of(["claude", "chatgpt", "grok"], fresh=True)  # side by side, asked again: the stop came minutes later
    table, skills, exclude = routing._table(gate, roster), roster.skills if roster is not None else {}, {}
    while True:
        plan = takeover.decide(task, calls, stopped, available=table, skills=skills, preset=preset, exclude=exclude)
        if not plan.ok:
            if plan.nobody and overdue is None:  # an overdue call nobody can take keeps waiting, as today, quietly
                out(f"No takeover: {safety.one_line(plan.reason, secrets)}.")
            return None
        view = {**dict(task), "agent": plan.agent, "checker": plan.checker, "check_state": plan.check_state,
                "check_note": plan.check_note}
        try:
            prompt, web_search, files, searching = _resume_call(view, _before_stop(calls, stopped), plan, preset,
                                                                getattr(deps, "claude_ready", None))
        except ValueError as e:  # the rows don't lead to the stopped call (never expected): the stop stands
            out(f"No takeover: {safety.one_line(str(e), secrets)}.")
            return None
        if plan.to == "grok" and plan.kind in ("check", "recheck") and len(prompt) > settings.grok_prompt_limit()[0]:
            exclude["grok"] = f"too long for Grok Bot ({len(prompt)} characters)"  # decision 6: past its limit
            continue
        if plan.to == "grok" and _grok_holder(conn, task) is not None:  # rules v2.19: one Grok piece of a split out
            exclude["grok"] = "Grok Bot is out on another piece of this split"
            continue
        break
    if overdue is not None:  # decision 7: the Grok row stays as stopped (overdue); its answer, if it comes, is late
        with _hold_interrupts():
            if not log.mark_overdue(conn, overdue["call_id"]):
                return None  # its answer was collected a moment ago: nothing to take over
            log.set_grok_note(conn, task_id, None)
            if log.get_task(conn, task_id)["status"] == "sent":
                log.set_open_status(conn, task_id, "queued")
    prompt, record, mem = _attach_context(conn, view, plan.to, prompt, secrets, out,
                                          hindsight=getattr(deps, "hindsight", None), reuse=stopped, kind=plan.kind)
    if prompt is None:
        return record
    with _hold_interrupts():
        try:
            log.set_takeover(conn, task_id, agents=roster.names if roster is not None else tuple(availability.NAMES),
                             agent=plan.agent, checker=plan.checker, check_state=plan.check_state,
                             check_note=plan.check_note)
        except log.StateError:
            receipt.mark(out, code="state_changed")
            out(f"{task_id} is already {_status_text(log.get_task(conn, task_id))}.")
            return 1
    out(_takeover_line(plan, task))
    stage_kind = plan.kind in log.STAGE_KINDS
    code = SENDERS[plan.to](conn, log.get_task(conn, task_id), plan.call_id, plan.kind, prompt, deps, secrets=secrets,
                            out=out, web_search=web_search, files=files, stage=plan.stage if stage_kind else None,
                            role=plan.role if stage_kind else None, searching=searching, limited=False,
                            context=record, memory=mem, resume_of=stopped["call_id"])
    return _TOOK if code is None else code


def _overdue(task, calls, deps, own=False):
    """Brief 24 (decision 6): the task's newest call when it is a Grok call still out at 2 × grok_timeout_minutes, as
    the stop the takeover reads (failed, code `overdue`), or None. The row changes only when the takeover goes ahead.
    A call this command sent itself counts only for route's own wait (`own`), and under the overdue hook (the owner after F:
    the sending command takes over its own backdated call at once, since Grok Bot can answer before any other check)."""
    if task["status"] not in ("queued", "sent") or not calls:
        return None
    last = calls[-1]
    if last["agent"] != "grok" or last["status"] != "sent":
        return None
    if not own and not BACKDATE_MINUTES and last["call_id"] in (getattr(deps, "sent_here", None) or ()):
        return None
    n = getattr(deps, "grok_timeout", None)
    n = settings.grok_timeout_minutes() if n is None else n
    if not n or log.minutes_since(last["sent_at"], getattr(deps, "now", None)) < 2 * n:
        return None
    return {**dict(last), "status": "failed", "reason_code": takeover.OVERDUE}


def _skip_grok_check(conn, task, calls, size, deps, out):
    """Brief 24 (the owner's C11): a Grok check or re-check whose prompt would pass its limit is skipped when the checker
    is chosen: no failed row, the task's one takeover is not used, and `Grok skipped: the check is too long for Grok
    (<n> characters)` goes in check_note and on the card. The next checker by decision 4 (on a relay task, the other of
    Claude and ChatGPT when it isn't the doer) checks; with nobody left the result is unchecked."""
    note = f"{GROK_SKIPPED}the check is too long for Grok ({size} characters)"
    roster = getattr(deps, "roster", None)
    table = routing._table(getattr(deps, "available", None), roster)
    stopped = takeover.stopped_agents(calls)
    stopped.pop("grok", None)
    if _mode(task) in ("route", "piece"):
        row = (roster.skills.get(task["skill"]) if roster is not None else None) or {}
        # Grok left out of the order altogether, so the reason given is the others' (decision 4)
        checker, why = routing.pick_checker({**row, "second": None if row.get("second") == "grok" else row.get("second")},
                                            task["agent"], table, stopped=stopped)
    else:
        candidates = [relay.other_builder(task["agent"])] if relay.other_builder(task["agent"]) else ["chatgpt", "claude"]
        checker, why = takeover._first(candidates, stopped, table, False, skip=[task["agent"], "grok"])
        why = why or f"only {availability.name_of(task['agent'])} could"
    names = roster.names if roster is not None else tuple(availability.NAMES)
    with _hold_interrupts():
        if checker is not None:
            log.set_takeover(conn, task["task_id"], agents=names, agent=task["agent"], checker=checker,
                             check_state="pending", check_note=note)
        else:
            log.set_takeover(conn, task["task_id"], agents=names, agent=task["agent"], checker=None,
                             check_state="unchecked", check_note=f"{note}; {routing.NO_CHECKER} ({why})")
    then = (f"{availability.name_of(checker)} checks instead" if checker is not None
            else f"nobody else can check it ({why}), so the result is unchecked")
    out(f"{note}; {then}.")


def _before_stop(calls, stopped):
    """The rows the stopped call was built from: every row but those it replaced (a manual resume's stopped row before
    it). `_resume_call` leaves out the stopped row itself."""
    gone, at = set(), stopped
    while relay.resume_of(at):
        gone.add(relay.resume_of(at))
        at = next((c for c in calls if c["call_id"] == relay.resume_of(at)), None)
        if at is None:
            break
    return [c for c in calls if c["call_id"] not in gone]


def _takeover_line(plan, task):
    """Terminal's one line, the card's words: `ChatGPT took over the first call · Grok Bot was overdue · done without Meta`."""
    line = takeover.words(plan)
    extra = cardline.note(task, plan.to) if plan.kind in ("do", "fix") else None
    return f"{line} · {extra}" if extra else line


def _after_takeover(call, calls):
    """`; it took over after Claude hit its plan limit` when `call` is a takeover's row that stopped too (decision 6: the
    task ends with both reasons), else an empty string."""
    before = takeover.replaced(call, calls) if call is not None and relay.is_takeover(call) else None
    return f"; it took over after {takeover.why_words(before)}" if before is not None else ""


def _stopped_reason(call, calls):
    """Why a first call that nobody took over ends the task: its own text, then the stop it took over, when it did."""
    return f"{call['text'] or 'the call failed'}{_after_takeover(call, calls)}"


def _reused_call(task, step, calls):
    """The earlier call row whose memory block this step's call gets again (rules v2.27; decision 11): the build call's
    for a check, fix or re-check (and a fix re-ask); the first `do` row's for the doer's re-ask; none for a first call,
    which recalls afresh."""
    if step.action in ("check", "recheck", "fix"):
        return _build_call(task, calls)
    if step.action == "do" and step.missing:
        return checking._result_call(task, calls)
    return None


# ---------- the relay chain (rules v2.12) ----------

def _preset_for(task, deps):
    """A relay task's preset from the loaded presets, or (None, why not). A split task's chain is the
    code's own (split.PRESET), never one from config/presets.json."""
    if _mode(task) == "split":
        return split.PRESET, None
    return presets.for_task(task, getattr(deps, "presets", None))  # rules v2.21: the task's slots, never the defaults


def _relay_step(conn, task, calls, deps, secrets, out):
    """One step of a relay task's chain. Returns None to go round again, _CHECK when every stage is
    done (the check loop takes over), or an exit code."""
    task_id = task["task_id"]
    preset, problem = _preset_for(task, deps)
    if preset is None:
        receipt.mark(out, code="stuck")
        out(f"#{task['n']} {task_id} can't go on: {problem}. It stays open; fix config/presets.json or cancel it.")
        return 1
    step = relay.next_stage(task, calls, preset)
    if step.action in ("check", "finish"):
        return _CHECK
    if step.action == "verdict":  # rules v2.13: the check stage replaces the checker loop; never both
        return _finish_by_stage(conn, task, step, secrets, out, hindsight=getattr(deps, "hindsight", None))
    if step.action == "pick":  # rules v2.16: every candidate reviewed; no check loop, no check stage
        return _await_pick(conn, task, preset, secrets, out)
    if step.action == "tally":  # rules v2.24: every vote is in; code counts; no checker, no fix round
        return _finish_by_tally(conn, task, preset, secrets, out, hindsight=getattr(deps, "hindsight", None))
    if step.action == "wait":
        _note_grok(conn, task, step.call, deps)
        if not deps.wait:
            out(f"{_call_text(step.call)} is with grok. Not waiting; run `sr check` later for it.")
            return 0
        return _wait_for_call(conn, task_id, step.call, deps, secrets, out)
    if step.action == "stop":
        return _stop_chain(conn, task, step, secrets, out, preset)
    return _send_stage(conn, task, step, deps, secrets, out)


def _send_stage(conn, task, step, deps, secrets, out):
    """Send a stage or its re-ask to the stage's agent. Returns None to go round again, or an exit code."""
    stage, agent = step.stage, step.agent or step.stage.agent
    if step.action == "reask":
        out(f"Stage {step.n} ({stage.role} by {agent}) missed its contract; re-asked once for: "
            + "; ".join(step.missing) + ".")
    prompt, kind, web_search, searching = _stage_call(task, step, _ready_once(deps))
    reuse = None
    if step.action == "reask":  # rules v2.27: a re-ask gets the block its first row got
        reuse = relay.stage_rows(log.fallback_view(log.calls_for(conn, task["task_id"])), step.n)[0]
    prompt, record, mem = _attach_context(conn, task, agent, prompt, secrets, out,
                                          hindsight=getattr(deps, "hindsight", None), reuse=reuse, kind=kind)
    if prompt is None:
        return record
    return SENDERS[agent](conn, task, step.call_id, kind, prompt, deps, secrets=secrets, out=out,
                          web_search=web_search, files=(), stage=step.n, role=stage.role, searching=searching,
                          limited=step.action == "stage" and step.prior is not None, context=record, memory=mem)


# ---------- split (rules v2.18, build brief 11) ----------

def _split_step(conn, task, calls, deps, secrets, out):
    """One step of a split task's own chain: the plan (stage 1, its contract and one re-ask), then, once
    the plan is stored, it waits with the owner; once every piece is delivered or skipped, the integration
    (stage 2); then the usual check loop with ChatGPT. Returns None to go round again, _CHECK, or an exit code."""
    line = _no_split_answer(task, calls)
    if line is not None:
        return _no_split(conn, task, line, out)
    step = relay.next_stage(task, calls, split.PRESET)
    if step.action in ("check", "finish"):
        return _CHECK
    if step.action == "stop":
        return _stop_chain(conn, task, step, secrets, out, split.PRESET)
    if step.action == "wait":
        _note_grok(conn, task, step.call, deps)
        if not deps.wait:
            out(f"{_call_text(step.call)} is out. Not waiting; run `sr check` later for it.")
            return 0
        return _wait_for_call(conn, task["task_id"], step.call, deps, secrets, out)
    if step.n == 2 and step.action == "stage":
        plan = log.split_plan_of(task)
        if plan is None:  # stage 1 met its contract: store the plan; it waits for the owner's approval
            return _plan_ready(conn, task, step.prior, deps, out)
        if plan.get("inputs") is None:
            receipt.mark(out, code="stuck")
            out(f"#{task['n']} {task['task_id']} can't integrate: its piece results were never frozen. It stays open.")
            return 1
    return _send_stage(conn, task, step, deps, secrets, out)


def _grok_holder(conn, task):
    """The piece of the same split that is out with Grok, or None (also None for any task that is not a piece)."""
    if _mode(task) != "piece":
        return None
    parent = log.get_task(conn, task["parent"])
    plan = log.split_plan_of(parent) if parent is not None else None
    if plan is None:
        return None
    return split.grok_holder(task, log.pieces_of(conn, parent["task_id"]),
                             lambda tid: log.calls_for(conn, tid), plan)


def _held_by(conn, row):
    """The piece a queued piece waits for, when its next call would go to Grok (E2, E3); else None."""
    if _mode(row) != "piece" or row["status"] != "queued":
        return None
    step = checking.next_step(row, log.fallback_view(log.calls_for(conn, row["task_id"])))
    agent = row["agent"] if step.action in ("do", "fix") else (row["checker"] if step.action in ("check", "recheck")
                                                               else None)
    return _grok_holder(conn, row) if agent == "grok" else None


def _no_split_answer(task, calls):
    """The planner's `## No split` line (rules v2.19), read before the contract on stage 1's latest answer (its
    re-ask when there is one), while the split is open and has no plan; else None."""
    if task["status"] not in ("queued", "sent") or log.split_plan_of(task) is not None:
        return None
    first, reask, _ = relay.stage_rows(log.fallback_view(calls), 1)
    latest = reask if reask is not None else first
    if latest is None or latest["status"] != "done":
        return None
    return split.no_split(latest["text"])


def _no_split(conn, task, line, out):
    """`## No split` is an answer: the split ends `failed` at stage 1 with `no split: <line>`. No piece, no Jev
    call, no re-ask. The owner routes the task instead (quoted for zsh: the owner's E4)."""
    with _hold_interrupts():
        try:
            log.set_failed(conn, task["task_id"], f"no split: {line}", failed_stage=1)
        except log.StateError:
            receipt.mark(out, code="state_changed")
            out(f"{task['task_id']} is already {_status_text(log.get_task(conn, task['task_id']))}.")
            return 1
    for text in _no_split_lines(task, line):
        out(text)
    return 1


def _no_split_lines(task, line):
    return [f"No split: {safety.for_terminal(line)}", f"Route it instead: sr route {shlex.quote(task['task'])}"]


def _new_ids(conn, k):
    """k new task ids, none already in the log and no two the same (four can share a second)."""
    found = []
    while len(found) < k:
        candidate = ids.new_task_id()
        if candidate not in found and log.get_task(conn, candidate) is None:
            found.append(candidate)
    return found


def _plan_ready(conn, task, plan_text, deps, out):
    """Stage 1's accepted text met the contract: store the plan with a task id per piece and wait for
    the owner (`returned`, awaiting approval). No piece row is written here: only the approval writes one."""
    pieces, join = split.parse(plan_text)
    plan = split.new_plan(pieces, join, _new_ids(conn, len(pieces)))
    with _hold_interrupts():
        log.set_split_plan(conn, task["task_id"], plan)
        log.set_split_returned(conn, task["task_id"], log.AWAITING_APPROVAL)
    # `sr split` asks for the approval next; any other command (`sr resume`, `sr check`) names the way to it
    go = "" if getattr(deps, "label", None) else f" Approve it: sr split --go {task['n']}"
    out(f"Plan ready: {len(pieces)} pieces.{go}")
    return 0


def _piece_hint(conn, row):
    """After `sr resume` or `sr fallback` on a piece: the line naming its split and how it goes on."""
    if _mode(row) != "piece":
        return None
    parent = log.get_task(conn, row["parent"])
    k = split.piece_index(log.split_plan_of(parent) or {"pieces": []}, row["task_id"])
    return f"This is piece {k} of split #{parent['n']}: sr split --go {parent['n']} goes on."


def _piece_route(answer, roster, choice=None, available=None):
    """Where the skill table would send a piece, for the approval screen: `writing · claude / chatgpt`,
    `ask` when Jev is below the floor (asked at the yes), or why it would come back. `available` (brief 24): the preview's
    availability, the parts that run nothing."""
    decision = routing.decide(answer, roster, answer=choice, can_ask=choice is None, available=available)
    if decision.action == "ask":
        return "ask"
    if decision.action == "return":
        return "comes back: " + decision.reason.removeprefix("returned: ")
    if decision.check_state == "not_needed":
        check = "no check"
    elif decision.check_state == "pending":
        check = decision.checker
    else:
        check = f"unchecked ({decision.check_note})"
    return f"{decision.skill} · {decision.agent} / {check}"


def _plan_screen(row, plan, roster, secrets, preview=None):
    """The approval screen (brief 11, section 7): each piece's text as it would run, where it would go, and
    the joining line. Text made safe to print. `preview` (brief 24): availability from what runs nothing."""
    lines = [f"Task {row['n']} · split · plan", ""]
    for k, piece in enumerate(plan["pieces"], 1):
        text = safety.for_terminal(split.text_of(piece), secrets)
        lines.append(f"{k}. {text}  → {_piece_route(piece['label'], roster, piece.get('choice'), preview)}")
    lines += [f"Join: {safety.for_terminal(plan['join'], secrets)}", ""]
    return lines


def _label_pieces(conn, task_id, plan, label):
    """Jev labels each piece that has no stored label yet (its one Jev call; an edit clears the label, so
    the edited text is labeled again). The call is seeded by the piece's own task id. Its tokens go on the
    split row (the owner's D2); the label is stored in the plan and reused when the piece runs."""
    for piece in plan["pieces"]:
        if piece["label"] is not None:
            continue
        with _hold_interrupts():
            answer = label(split.text_of(piece), task_id=piece["id"], tokens_this_month=log.jev_tokens_this_month(conn))
            log.add_jev_tokens(conn, task_id, int(answer.get("tokens") or 0))
            piece["label"] = answer
            log.set_split_plan(conn, task_id, plan)


def _edit_piece(conn, task_id, plan, deps, out):
    """`e`: the owner edits one piece's text. The planner's text stays beside the edit; the edit is labeled
    again by Jev. An edit that breaks a piece's rules (split.piece_problem) is not taken."""
    k = len(plan["pieces"])
    reply = (deps.ask(f"Edit which piece? [1-{k}] ") or "").strip()
    if not re.fullmatch(r"[0-9]+", reply) or not 1 <= int(reply) <= k:
        out(f"Not a piece number: {_one_line(reply, 20) or '(empty)'}. Nothing changed.")
        return
    i = int(reply)
    text = safety.redact(deps.ask(f"New text for piece {i}: ") or "", _secrets(deps.config))  # brief 22 (decision 10)
    why = split.piece_problem(text)
    if why:
        out(f"Not changed: the new text {why}.")
        return
    piece = plan["pieces"][i - 1]
    if text == split.text_of(piece):
        out(f"Not changed: piece {i} already reads that.")
        return
    piece.update(edited_text=None if text == piece["planner_text"] else text, label=None, choice=None)
    with _hold_interrupts():
        log.set_split_plan(conn, task_id, plan)
    _label_pieces(conn, task_id, plan, deps.label)


def _approval(conn, row, deps, secrets, out):
    """The plan waits for the owner (rules v2.18): label what has no label, show the screen, ask y/N/e. Without
    a terminal, stop at the plan; `sr split --go <n>` asks later. `y` makes the pieces; anything else but `e`
    cancels the split with the plan kept; no answer at all leaves it waiting."""
    task_id, n = row["task_id"], row["n"]
    plan = log.split_plan_of(row)
    _label_pieces(conn, task_id, plan, deps.label)
    while True:
        for line in _plan_screen(row, plan, deps.roster, secrets, _preview(deps)):
            out(line)
        if deps.ask is None:
            out(f"No terminal to ask in. Approve it in Terminal: sr split --go {n}")
            return 0
        try:
            reply = (deps.ask(f"Run these {len(plan['pieces'])} pieces? [y/N/e] ") or "").strip().lower()
            if reply in ("e", "edit"):
                _edit_piece(conn, task_id, plan, deps, out)
                continue
        except EOFError:
            out("")
            out(f"No answer. The plan waits: sr split --go {n}")
            return 0
        if reply in drop.YES:
            return _approve(conn, task_id, plan, deps, secrets, out)
        with _hold_interrupts():
            log.set_cancelled(conn, task_id, allowed_from=("returned",))
        out(f"Cancelled: no piece was made. The plan is kept: sr show {n}.")
        return 0


NO_WORDS = ("n", "no")
PIECE_SKILL = re.compile(r"([0-9]+)=([a-z_]+)")


def _answer_plan(conn, row, deps, secrets, out, answer, skills):
    """Brief 22 (decisions 2 and 9; Phase 0 choice 9): `sr split --go <n> --answer y|n [--skill <k>=<key> ...]`, the
    plan's y/N without a terminal. Editing a piece stays Terminal-only. A piece Jev left under the floor needs its
    `--skill`; without one `--answer y` is refused before any piece row (`needs_label`). `n` cancels with the plan kept."""
    task_id, n, roster = row["task_id"], row["n"], deps.roster
    word = (answer or "").strip().lower()
    if word in ("e", "edit"):
        receipt.mark(out, code="usage")
        out(f"Refused: editing a piece is Terminal-only: run sr split --go {n} in Terminal. Nothing was logged or sent.")
        return 2
    if word not in drop.YES + NO_WORDS:
        receipt.mark(out, code="usage")
        out(f"Refused: --answer is y or n (sr split --go {n} --answer y). Nothing was logged or sent.")
        return 2
    plan = log.split_plan_of(row)
    _label_pieces(conn, task_id, plan, deps.label)  # as the screen does: a piece without a label is labeled first
    choices, problem = _piece_skills(plan, skills, roster)
    if problem is None and word in NO_WORDS and choices:
        problem = "--skill goes with --answer y"
    if problem is not None:
        receipt.mark(out, code="usage")
        out(f"Refused: {problem}. Nothing was logged or sent.")
        return 2
    if word in NO_WORDS:
        with _hold_interrupts():
            log.set_cancelled(conn, task_id, allowed_from=("returned",))
        out(f"Cancelled: no piece was made. The plan is kept: sr show {n}.")
        return 0
    under = [(k, piece) for k, piece in enumerate(plan["pieces"], 1)
             if routing.decide(piece["label"], roster, can_ask=True).action == "ask" and k not in choices]
    if under:
        receipt.mark(out, code="needs_label")
        named = "; ".join(f"piece {k} ({_jev_text(piece['label'], roster).rstrip('.')})" for k, piece in under)
        add = " ".join(f"--skill {k}=<key>" for k, _ in under)
        out(f"Refused: Jev was unsure: {named}. Add {add} to approve. Nothing was logged or sent.")
        return 2
    for line in _plan_screen(row, plan, roster, secrets, _preview(deps)):
        out(line)
    for k, key in choices.items():
        plan["pieces"][k - 1]["choice"] = key
    return _approve(conn, task_id, plan, deps, secrets, out)


def _piece_skills(plan, skills, roster):
    """({piece number: skill}, None) from `--skill <k>=<key>`, or (None, why not): each a piece of the plan Jev left under
    the floor, a skill in the table, once."""
    found = {}
    for given in skills or ():
        m = PIECE_SKILL.fullmatch((given or "").strip())
        if not m:
            return None, f"--skill on a split is <piece>=<skill>, such as 2=writing (not {safety.one_line(given)!r})"
        k, key = int(m.group(1)), m.group(2)
        if not 1 <= k <= len(plan["pieces"]):
            return None, f"the plan has {len(plan['pieces'])} pieces; there is no piece {k}"
        if key not in roster.skills:
            return None, f"no skill {key}. Skills: {', '.join(roster.skill_order)}"
        if k in found:
            return None, f"piece {k} is named twice"
        if routing.decide(plan["pieces"][k - 1]["label"], roster, can_ask=True).action != "ask":
            return None, (f"piece {k} has Jev's label ({_jev_text(plan['pieces'][k - 1]['label'], roster).rstrip('.')});"
                          " --skill is for a piece Jev left under the floor")
        found[k] = key
    return found, None


def _approve(conn, task_id, plan, deps, secrets, out):
    """The owner said yes. A piece Jev labeled below the floor gets the skill question first, naming the piece.
    Then, and only here, the piece rows: mode piece, parent the split, the approved text byte for byte,
    Jev's stored label (its tokens already on the split row), routed by the skill table. The split then
    waits for its pieces (`waiting: pieces #a, #b`)."""
    roster = deps.roster
    for k, piece in enumerate(plan["pieces"], 1):
        if routing.decide(piece["label"], roster, can_ask=True).action == "ask" and piece.get("choice") is None:
            out(f"Piece {k}: {_jev_text(piece['label'], roster)}")
            piece["choice"] = _ask_for_skill(deps.ask, roster, out)
    numbers = []
    with _hold_interrupts():
        for piece in plan["pieces"]:
            answer = {**piece["label"], "tokens": 0}
            log.add_task(conn, piece["id"], split.text_of(piece), "split", answer, mode="piece", parent=task_id)
            decision = routing.decide(answer, roster, answer=piece["choice"], can_ask=False,
                                      available=_routing_table(getattr(deps, "available", None), roster,
                                                               piece["choice"] or answer.get("label")))
            if decision.action == "return":
                log.set_returned(conn, piece["id"], decision.reason, reason_code=decision.code, skill=decision.skill,
                                 skill_source=decision.skill_source)
            else:
                _set_route(conn, piece["id"], decision, roster)
            numbers.append(log.get_task(conn, piece["id"])["n"])
        plan["approved"] = True
        log.set_split_plan(conn, task_id, plan)
        log.set_split_returned(conn, task_id, f"{log.WAITING_PIECES} " + ", ".join(f"#{x}" for x in numbers))
    out(f"Approved: {len(numbers)} pieces, " + ", ".join(f"#{x}" for x in numbers) + ".")
    if _run_pieces(conn, task_id, deps, secrets, out) == 130:
        return 130
    return _split_advance(conn, log.get_task(conn, task_id), deps, secrets, out)


def _run_pieces(conn, task_id, deps, secrets, out):
    """Each open piece, one after another in plan order, through the usual routed loop (rules v2.18): its own
    doer, check and fix round. A Grok piece that isn't waited for (D5) leaves the next piece free to start.
    A Ctrl+C stops here (130); the pieces not yet run stay queued for `sr check`."""
    rows = log.pieces_of(conn, task_id)
    for k, row in enumerate(rows, 1):
        if row["status"] not in ("queued", "sent"):
            continue
        out(f"Piece {k} of {len(rows)}: #{row['n']} {row['task_id']} · {row['skill'] or '-'} -> {row['agent']}")
        with runs.held(conn, row["task_id"]) as ok:  # brief 22 (decision 4): the piece's own run, cleared when it ends
            if not ok:
                out(f"#{row['n']} {row['task_id']} is running in another window; not run here.")
                continue
            if run_relay(conn, row["task_id"], deps, secrets, out) == 130:
                return 130
    return 0


BLOCKED_LINE = "Piece {id} blocked: {why}. Resolve it (sr resume / sr fallback / sr route again) or: sr split --skip {id}"


def _split_advance(conn, row, deps, secrets, out):
    """The split's wait (rules v2.18): print each piece as done, waiting, blocked or skipped, and a line per
    blocked piece. When every piece is delivered or skipped, freeze the inputs (each piece's approved text and
    result, in plan order) and integrate: stage 2, then the usual check loop. Returns an exit code."""
    plan, rows = log.split_plan_of(row), log.pieces_of(conn, row["task_id"])
    by_id = {r["task_id"]: r for r in rows}
    states, lines, blocked = [], [], []
    for k, piece in enumerate(plan["pieces"], 1):
        r = by_id.get(piece["id"])
        state, words = ("skipped", None) if piece["skipped"] else split.piece_state(r)
        states.append(state)
        holder = _held_by(conn, r) if state == "waiting" else None
        if holder is not None:
            lines.append(f"  piece {k} #{r['n']}: {split.held_words(holder)}")
        else:
            lines.append(f"  piece {k} #{r['n']}: {state}" + (f" ({words})" if state == "waiting" else "")
                         + (f": {words}" if state == "blocked" else ""))
        if state == "blocked":
            blocked.append((r["task_id"], words))
    done, skipped = states.count("done"), states.count("skipped")
    out(f"Split #{row['n']}: {done} of {len(states)} pieces done." + (f" {skipped} skipped." if skipped else ""))
    for line in lines:
        out(line)
    for task_id, why in blocked:
        out(BLOCKED_LINE.format(id=task_id, why=why))
    if any(state not in ("done", "skipped") for state in states):
        return 0
    plan["inputs"] = split.frozen_inputs(plan, rows)
    roster = getattr(deps, "roster", None)
    if roster is not None:  # brief 24 (decision 4): the integration's checker as it stands now
        checker, state, note = _split_checker(getattr(deps, "available", None), roster)
    else:  # a caller that hands no roster keeps the row's checker
        checker, state, note = row["checker"], None, None
    with _hold_interrupts():
        log.set_split_plan(conn, row["task_id"], plan)
        log.reopen_split(conn, row["task_id"], agents=roster.names if roster is not None else None, checker=checker,
                         check_state=state, check_note=note)
    joined = f"{split.CHECKER} checks" if checker else f"unchecked: {note}"
    out(f"All pieces are in. {split.PLANNER} joins them; {joined}.")
    return run_relay(conn, row["task_id"], deps, secrets, out)


@_releases_its_runs
def cmd_split_skip(words, *, conn, config, roster, environ, settings_paths, label=None, ask=None, post=None,
                   worker=None, chatgpt=None, codex_login=None, fetch=None, close=None, sleep=None, clock=None,
                   wait=False, claude_ready=None, hindsight=None, available=None, chatgpt_ready=None, out=print):
    """`sr split --skip <piece>` (rules v2.18): the owner tells a split to go on without one piece. The piece row is
    untouched; the plan marks it skipped, and the integration prompt says it is missing. Refused: not a piece,
    a split not waiting for its pieces, a piece already skipped or delivered, the last piece not skipped."""
    problems = _refusals(config, environ, settings_paths)
    if problems:
        _refuse_problems(out, problems, config, environ, settings_paths)
        return 2
    if not " ".join(words).strip():
        receipt.mark(out, code="usage")
        out("Refused: name the piece: sr split --skip <piece> (its # in `sr log`, or its task_id). "
            "Nothing was logged or sent.")
        return 2
    row = _task_target(conn, words, out, "split --skip")
    if row is None:
        return 2
    if _mode(row) != "piece":
        receipt.mark(out, code="wrong_state")
        out(f"Refused: #{row['n']} is not a piece of a split. Nothing was logged or sent.")
        return 2
    parent = log.get_task(conn, row["parent"])
    if not _take_run(conn, parent, out, "go on"):
        return 2
    if not (parent["status"] == "returned" and (parent["check_note"] or "").startswith(log.WAITING_PIECES)):
        receipt.mark(out, code="wrong_state")
        out(f"Refused: its split #{parent['n']} is not waiting for its pieces (it is {_status_word(parent)}). "
            "Nothing was logged or sent.")
        return 2
    plan = log.split_plan_of(parent)
    k = split.piece_index(plan, row["task_id"])
    piece = plan["pieces"][k - 1]
    if piece["skipped"]:
        receipt.mark(out, code="already_used")
        out(f"Refused: #{row['n']} is already skipped. Nothing was logged or sent.")
        return 2
    if split.piece_state(row)[0] == "done":
        receipt.mark(out, code="wrong_state")
        out(f"Refused: #{row['n']} is delivered; nothing to skip. Nothing was logged or sent.")
        return 2
    if all(p["skipped"] for p in plan["pieces"] if p is not piece):
        receipt.mark(out, code="wrong_state")
        out("Refused: at least one piece must be delivered for the split to join anything. Nothing was logged or sent.")
        return 2
    piece["skipped"] = True
    with _hold_interrupts():
        log.set_split_plan(conn, parent["task_id"], plan)
    out(f"Skipped piece {k} (#{row['n']}) of split #{parent['n']}: the integration will say it is missing.")
    deps = _split_deps(config, roster, label=label, ask=ask, post=post, worker=worker, chatgpt=chatgpt,
                       codex_login=codex_login, fetch=fetch, close=close, sleep=sleep, clock=clock, wait=wait,
                       claude_ready=claude_ready, hindsight=hindsight, available=available, chatgpt_ready=chatgpt_ready)
    return _split_advance(conn, log.get_task(conn, parent["task_id"]), deps, _secrets(config), out)


def _split_checker(available, roster):
    """Brief 24 (decision 4): a split's integration (Claude's) is checked by ChatGPT, as today; without ChatGPT it is
    delivered unchecked. (checker, check_state, check_note), asked at intake and again when the integration starts."""
    table = routing._table(available, roster)
    found = table(split.CHECKER)
    if found.available:
        return split.CHECKER, "pending", None
    return None, "unchecked", f"{routing.NO_CHECKER} ({found.why})"


def _preview(deps):
    """Brief 24: availability from what runs nothing (live, set up, the probe records), for a preview such as the plan
    screen; None without a gate (today's table)."""
    if getattr(deps, "available", None) is None:
        return None
    return preview_availability(deps.roster, deps.config)


def preview_availability(roster, config):
    """{agent: Availability} from the roster, the .env names present, the settings and probe_state.json: no check runs."""
    return availability.agents(roster, names=availability.env_names(config), doc=settings.read(),
                               probe_data=probes._read(PROBE_STATE))


def _split_deps(config, roster, *, label, ask, post, worker, chatgpt, codex_login, fetch, close, sleep, clock, wait,
                claude_ready, hindsight=None, available=None, chatgpt_ready=None):
    return SimpleNamespace(config=config, post=post, worker=worker, chatgpt=chatgpt, codex_login=codex_login,
                           codex_ok=None, fetch=fetch, close=close, sleep=sleep, clock=clock, wait=wait, presets=None,
                           live=roster.live, claude_ready=claude_ready, label=label, ask=ask, roster=roster,
                           hindsight=hindsight, available=available, chatgpt_ready=chatgpt_ready)


@_releases_its_runs
def cmd_split(task, *, conn, config, roster, environ, settings_paths, label, ask, post, worker, chatgpt=None,
              codex_login=None, fetch=None, close=None, sleep=None, clock=None, wait=False, source="cli", files=(),
              preset=None, claude_ready=None, hindsight=None, available=None, chatgpt_ready=None, out=print):
    """`sr split "task"` (rules v2.18): Claude plans 2 to 4 standalone pieces and a joining line; the owner
    approves the plan (y/N/e); each piece runs as its own routed task. Refused before any log row: a file, a
    preset, an override prefix, an empty task, a task starting with /. Jev is never asked about the split
    itself; it labels each piece. `ask` is None without a terminal: then the split stops at the plan."""
    if files:
        receipt.mark(out, code="flag_refused")
        out("Refused: a split task carries no files (rules v2.18). Nothing was logged or sent.")
        return 2
    if preset:
        receipt.mark(out, code="flag_refused")
        out("Refused: a split task takes no preset; its pieces are routed tasks (rules v2.18). "
            "Nothing was logged or sent.")
        return 2
    problems = _refusals(config, environ, settings_paths)
    if problems:
        _refuse_problems(out, problems, config, environ, settings_paths)
        return 2
    if _claude_refusal(available, out):  # brief 24 (decision 2): Claude plans and joins every split
        return 2
    tag, clean = routing.parse_override(task, roster.names)
    clean = safety.redact(clean, _secrets(config))  # brief 22 (decision 10): before the row
    if tag:
        receipt.mark(out, code="override_refused")
        out(f"Refused: an override prefix on a split task is refused (@{tag}); the skill table routes each piece. "
            "Nothing was logged or sent.")
        return 2
    if not clean.strip():
        receipt.mark(out, code="bad_task")
        out("Refused: the task is empty. Nothing was logged or sent.")
        return 2
    if clean.lstrip().startswith("/"):
        receipt.mark(out, code="bad_task")
        out("Refused: a task can't start with / (claude could read it as a slash command). Nothing was logged or sent.")
        return 2
    if split.PLANNER not in roster.live:  # without a gate (direct calls): Claude plans every split
        receipt.mark(out, code="not_live")
        out(f"Refused: a split needs {split.PLANNER} live. Nothing was logged or sent.")
        return 2
    checker, state, note = _split_checker(available, roster)  # brief 24 (decision 4)
    task_id = ids.new_task_id()
    receipt.mark(out, task_id=task_id)
    secrets = _secrets(config)
    deps = _split_deps(config, roster, label=label, ask=ask, post=post, worker=worker, chatgpt=chatgpt,
                       codex_login=codex_login, fetch=fetch, close=close, sleep=sleep, clock=clock, wait=wait,
                       claude_ready=claude_ready, hindsight=hindsight, available=available, chatgpt_ready=chatgpt_ready)
    with _hold_interrupts():  # the row is written whole, with its route, before anything is sent
        log.add_task(conn, task_id, clean, source, {"status": "not_asked", "tokens": 0}, mode="split", run=runs.me())
        runs.adopt(task_id)  # brief 22 (decision 4): born with its run
        log.set_route(conn, task_id, agents=roster.names, agent=split.PLANNER, route_reason="split",
                      checker=checker, check_state=state, check_note=note)
    joined = f"{split.CHECKER} checks" if checker else f"unchecked: {note}"
    out(f"{task_id}: split: {split.PLANNER} plans 2 to 4 pieces; you approve them; each runs as its own routed "
        f"task; {split.PLANNER} joins the results; {joined}.")
    code = run_relay(conn, task_id, deps, secrets, out)
    row = log.get_task(conn, task_id)
    if row["status"] == "returned" and row["check_note"] == log.AWAITING_APPROVAL:
        return _approval(conn, row, deps, secrets, out)
    return code


@_releases_its_runs
def cmd_split_go(words, *, conn, config, roster, environ, settings_paths, label, ask, post, worker, chatgpt=None,
                 codex_login=None, fetch=None, close=None, sleep=None, clock=None, wait=False, claude_ready=None,
                 hindsight=None, answer=None, skills=(), available=None, chatgpt_ready=None, out=print):
    """`sr split --go <n>`: a split waiting at its plan gets the approval (y/N/e, in a terminal); a split
    waiting for its pieces prints them and, once every piece is delivered or skipped, integrates."""
    problems = _refusals(config, environ, settings_paths)
    if problems:
        _refuse_problems(out, problems, config, environ, settings_paths)
        return 2
    if not " ".join(words).strip():
        receipt.mark(out, code="usage")
        out("Refused: name the split: sr split --go <n> (the # in `sr log`). Nothing was logged or sent.")
        return 2
    row = _task_target(conn, words, out, "split --go")
    if row is None:
        return 2
    if _mode(row) == "split" and not _take_run(conn, row, out, "go on"):
        return 2
    if _mode(row) != "split":
        receipt.mark(out, code="wrong_state")
        out(f"Refused: #{row['n']} is not a split task. Nothing was logged or sent.")
        return 2
    secrets = _secrets(config)
    deps = _split_deps(config, roster, label=label, ask=ask, post=post, worker=worker, chatgpt=chatgpt,
                       codex_login=codex_login, fetch=fetch, close=close, sleep=sleep, clock=clock, wait=wait,
                       claude_ready=claude_ready, hindsight=hindsight, available=available, chatgpt_ready=chatgpt_ready)
    if answer is not None or skills:  # brief 22 (decision 9): the approval by flag
        if not (row["status"] == "returned" and row["check_note"] == log.AWAITING_APPROVAL):
            receipt.mark(out, code="wrong_state")
            out(f"Refused: #{row['n']} isn't waiting at its plan (it is {_status_word(row)}). Nothing was logged or sent.")
            return 2
        return _answer_plan(conn, row, deps, secrets, out, answer, skills)
    if row["status"] == "returned" and row["check_note"] == log.AWAITING_APPROVAL:
        return _approval(conn, row, deps, secrets, out)
    if row["status"] == "returned" and (row["check_note"] or "").startswith(log.WAITING_PIECES):
        return _split_advance(conn, row, deps, secrets, out)
    receipt.mark(out, code="wrong_state")
    out(f"Refused: #{row['n']} is {_status_word(row)}; it isn't waiting for your approval or for its pieces. "
        "Nothing was logged or sent.")
    return 2


def _stage_call(task, step, ready=lambda: False):
    """The prompt, call kind, web-search setting and search state for a stage or re-ask step. Search is decided
    by router/search.py (rules v2.22): on for Claude (behind the probe gate, `ready()`) and ChatGPT on every
    stage, since a relay stage carries no file; the prompt then carries the search line."""
    stage = step.stage
    kind = "reask" if step.action == "reask" else "stage"
    agent = step.agent or stage.agent
    searching = search.state(task, kind=kind, role=stage.role, agent=agent, files=(), ready=ready)
    on = searching == search.ALLOWED
    deliverable_shape = getattr(stage, "input", None) == "task" and getattr(stage, "contract", None) == "deliverable"  # redteam's stage 1
    handoff = getattr(step, "handoff", False)  # rules v2.25: the build call on a project task
    if step.action == "reask":
        shape = (split.PLAN_SHAPE if stage.role == split.PLAN_ROLE
                 else relay.TASK_DELIVERABLE_LINE if deliverable_shape else None)
        if handoff:  # the handoff shape is asked for again, after the stage's own
            shape = f"{shape if shape is not None else relay.INSTRUCTIONS.get(stage.role, '')}\n\n{context.HANDOFF_LINE}".strip()
        prompt = relay.reask_prompt(stage.role, task["task"], step.result, step.missing, shape=shape, search=on)
    elif stage.role == split.PLAN_ROLE:
        prompt = split.plan_prompt(task["task"], search=on)
    elif stage.role == split.INTEGRATE_ROLE:  # the pieces block from the stored plan, never stage 1's text
        prompt = split.integrate_prompt(task["task"], log.split_plan_of(task), search=on)
    else:
        prompt = relay.prompt_for(stage.role, task["task"], step.prior, search=on,
                                  task_alone=getattr(stage, "input", None) == "task",
                                  deliverable_shape=deliverable_shape, against=getattr(step, "against", None),
                                  handoff=handoff)
    # `web_search` is ChatGPT's setting only; Claude's search comes from `searching` alone. Before rules v2.22 a
    # ChatGPT research, review or check stage searched; now every ChatGPT stage does, through the same state.
    return prompt, kind, "live" if on else "disabled", searching


def _ready_once(deps):
    """The probe gate for this command, asked at most once (it runs `claude --version`). Without a
    gate (tests, or a command that has none) Claude's search stays off."""
    def ready(mode=None):  # mode search.WEB_FILES: the --web file probe's pass (D9)
        cache = getattr(deps, "claude_search_ok", None)
        if not isinstance(cache, dict):
            cache = {}
            try:
                deps.claude_search_ok = cache
            except AttributeError:
                pass
        if mode not in cache:
            check = getattr(deps, "claude_ready", None)
            cache[mode] = (bool(check(mode)) if mode else bool(check())) if check is not None else False
        return cache[mode]
    return ready


def _stop_chain(conn, task, step, secrets, out, preset=None):
    """The chain failed at stage n: the task is `failed` with the stage, and the owner gets every
    stage result so far (rules v2.12). When the stage that failed is the check stage, the result of
    the stage before is marked unchecked (rules v2.13). Exit 1."""
    task_id, stage, agent = task["task_id"], step.stage, step.agent or step.stage.agent
    calls = log.calls_for(conn, task_id)
    reason = safety.redact(step.reason + _after_takeover(calls[-1] if calls else None, calls), secrets)
    what = "split" if _mode(task) == "split" else "relay"
    error = f"{what} failed at stage {step.n} ({stage.role} by {agent}): {reason}"
    at_check = preset is not None and preset.check_stage is not None and step.n == preset.check_stage.n
    revise = getattr(preset, "revise_stage", None) if preset is not None else None
    at_revise = revise is not None and step.n == revise.n  # rules v2.23: stage 1's build goes to the owner unchecked
    with _hold_interrupts():
        try:
            if at_check:
                log.set_check_state(conn, task_id, "unchecked", note=_check_stage_note(conn, task_id, step.n, agent))
            if at_revise:
                log.set_check_state(conn, task_id, "unchecked", note=_revise_stage_note(conn, task_id, revise))
            log.set_failed(conn, task_id, error, failed_stage=step.n)
        except log.StateError:
            receipt.mark(out, code="state_changed")
            out(f"{task_id} is already {_status_text(log.get_task(conn, task_id))}.")
            return 1
    out(f"{what.upper()} FAILED at stage {step.n} ({stage.role} by {agent}): {safety.for_terminal(reason, secrets)}")
    if at_check:
        out(f"Stage {step.n - 1}'s result is unchecked.")
    if at_revise:
        out(f"Stage {revise.revise_of}'s result is unchecked.")
    _print_stages(conn, task_id, secrets, out)
    _project_entry(conn, task_id, out)  # rules v2.25: the stopped line
    return 1


def _revise_stage_note(conn, task_id, revise):
    """Why the build is unchecked when the revise stage stopped (rules v2.23): only its builder could revise it."""
    calls = log.calls_for(conn, task_id)
    last = calls[-1] if calls else None
    built = relay.accepted(log.fallback_view(calls), revise.revise_of)
    who = built["agent"] if built is not None else "the builder"
    if last is not None and last["reason_code"] == plan_limit.CODE:
        return (f"revise stage {revise.n} stopped on {last['agent']}'s plan limit; only {who}, which built stage "
                f"{revise.revise_of}, can revise it; stage {revise.revise_of}'s result is unchecked")
    return f"revise stage {revise.n} gave no revision; stage {revise.revise_of}'s result is unchecked"


def _check_stage_note(conn, task_id, n, agent):
    """Why stage n-1's result is unchecked when check stage n stopped. On a plan limit whose other
    builder made the stage before, the resume is refused, and the note says so (rules v2.15)."""
    calls = log.calls_for(conn, task_id)
    last = calls[-1] if calls else None
    other = relay.other_builder(agent)
    before = relay.accepted(calls, n - 1)
    if (last is not None and last["reason_code"] == plan_limit.CODE and other is not None and before is not None
            and before["agent"] == other):
        return (f"check stage {n} stopped on {agent}'s plan limit; {other} made stage {n - 1}, so it can't take the "
                f"check; stage {n - 1}'s result stays unchecked")
    return f"check stage {n} gave no verdict; stage {n - 1}'s result is unchecked"


def _await_pick(conn, task, preset, secrets, out):
    """A review preset's chain is done: the task comes back to the owner awaiting their pick (the owner's D2),
    with no result chosen, and the owner sees each candidate with its reviewer's verdict and notes. Nothing
    more is sent to anyone. Exit 0."""
    task_id = task["task_id"]
    with _hold_interrupts():
        try:
            log.set_awaiting_pick(conn, task_id)
        except log.StateError:
            receipt.mark(out, code="state_changed")
            out(f"{task_id} is already {_status_text(log.get_task(conn, task_id))}.")
            return 1
    row = log.get_task(conn, task_id)
    for line in _versus_lines(row, log.calls_for(conn, task_id), preset, secrets):
        out(line)
    return 0


def _versus_lines(row, calls, preset, secrets):
    """The candidates block (brief 9, phase E): each candidate with its reviewer's verdict and notes, A
    first, then the pick line: how to pick while it waits, or what the owner picked. Text made safe."""
    n, choice = row["n"], relay.picked(row)
    head = "awaiting your pick" if choice is None else f"picked {'none' if choice == 'none' else choice.upper()}"
    lines = [f"Task {n} · {row['preset']} · {head}", ""]
    found = relay.candidates(calls, preset)
    for c in found:
        lines += [f"{c.letter.upper()} — {c.agent} · reviewed by {c.reviewer}: {c.verdict.upper()}",
                  safety.for_terminal(c.text, secrets)]
        if c.missing:  # the build's `## Missing` section, under the deliverable, never part of it
            lines += [f"missing ({c.agent}):", safety.for_terminal(c.missing, secrets)]
        lines += [f"notes ({c.reviewer}):", safety.for_terminal(c.notes or "(none)", secrets), ""]
    if choice is None:
        lines.append(f"Pick: sr pick {n} a | b | none")
    elif choice == "none":
        lines.append("Picked: none. The task failed (no pick); both candidates are kept.")
    else:
        c = next(c for c in found if c.letter == choice)
        anyway = " (picked anyway)" if c.verdict == "fail" else ""
        lines.append(f"Picked: {choice.upper()} ({c.agent}), reviewed by {c.reviewer}: {c.verdict.upper()}{anyway}. "
                     "It is the task's result.")
    return lines


def _finish_by_tally(conn, task, preset, secrets, out, hindsight=None):
    """A vote chain's three answers are in (rules v2.24, decision 6): code counts them. A majority: the task is
    `done` and `passed`, its result byte for byte the first agreeing stage's stored text, its doer that stage's agent,
    no checker, check note `checked-by-vote <for>/<against>`. No majority: it waits for the owner's pick, as versus
    does (the same `returned` + `awaiting pick`). Every voter is shown, the dissent first. Nothing is sent. Exit 0."""
    task_id = task["task_id"]
    calls = log.calls_for(conn, task_id)
    counted = relay.tally([(s.n, relay.accepted(calls, s.n)["text"]) for s in preset.stages])
    with _hold_interrupts():
        try:
            if counted.winner is None:
                log.set_awaiting_pick(conn, task_id)
            else:
                won = relay.accepted(calls, counted.winner)
                log.set_tally(conn, task_id, agents=tuple({c["agent"] for c in calls}), agent=won["agent"],
                              result=won["text"], note=counted.note)
        except log.StateError:
            receipt.mark(out, code="state_changed")
            out(f"{task_id} is already {_status_text(log.get_task(conn, task_id))}.")
            return 1
    row = log.get_task(conn, task_id)
    out("")
    for line in _vote_lines(row, log.calls_for(conn, task_id), preset, secrets):
        out(line)
    _project_entry(conn, task_id, out)  # a vote never has a project; the pair stays together (rules v2.25 and v2.27)
    _memory_store(conn, task_id, out, hindsight=hindsight, secrets=secrets)
    return 0


VOTE_PICKED = re.compile(r"picked (a|b|c|none); no majority")


def _vote_lines(row, calls, preset, secrets):
    """The vote block (decision 11): the answer and how it was decided, then every voter with its answer line,
    confidence when given, and `## Why`, the dissent first when there is a majority; then how to pick while it
    waits. Text made safe; nothing here was written by a model except the quoted answers and reasons."""
    n, found = row["n"], relay.voters(calls, preset)
    by_stage = {v.stage: v for v in found}
    picked = VOTE_PICKED.fullmatch(row["check_note"] or "")
    counted = relay.tally([(v.stage, v.text) for v in found]) if len(found) == len(preset.stages) else None
    if picked:
        head = f"picked {picked.group(1).upper() if picked.group(1) != 'none' else 'none'}; no majority"
    elif relay.awaiting_pick(row):
        head = "awaiting your pick (no majority)"
    elif counted is not None and counted.winner is not None:
        head = counted.note
    else:
        head = row["status"]
    lines = [f"Task {n} · {row['preset']} · {head}"]
    if picked and picked.group(1) != "none":
        v = next(v for v in found if v.letter == picked.group(1))
        lines.append(f"Answer: {safety.for_terminal(v.answer or '', secrets)} (picked {v.letter.upper()}; "
                     "no majority, unchecked)")
    elif picked:
        lines.append("Answer: none (picked none; no majority). Every answer is kept.")
    elif relay.awaiting_pick(row):
        lines.append("Answer: awaiting pick")
    elif counted is not None and counted.winner is not None:
        lines.append(f"Answer: {safety.for_terminal(by_stage[counted.winner].answer or '', secrets)} ({counted.note})")
    dissent = counted.dissent if counted is not None and counted.winner is not None else ()
    order = [by_stage[s] for s in dissent] + [v for v in found if v.stage not in dissent]
    for v in order:
        mark = " (dissent)" if v.stage in dissent else ""
        conf = f" · confidence {v.confidence}" if v.confidence is not None else ""
        lines += ["", f"{v.letter.upper()} — {v.agent}{mark}: {safety.for_terminal(v.answer or '(no answer line)', secrets)}"
                      f"{conf}",
                  f"why ({v.agent}):", safety.for_terminal(v.why or "(none)", secrets)]
    if relay.awaiting_pick(row):
        letters = " | ".join(v.letter for v in found)
        lines += ["", f"Pick: sr pick {n} {letters} | none"]
    return lines


def _pick_words(row, loaded):
    """`a|b|none` on versus, `a|b|c|none` on a three-voter tally (the letters a pick takes on this task)."""
    preset = presets.for_task(row, loaded)[0] if loaded is not None else None
    count = len(preset.stages) if preset is not None and preset.tallies else 2
    return "|".join([chr(ord("a") + i) for i in range(count)] + ["none"])


def _finish_by_stage(conn, task, step, secrets, out, hindsight=None):
    """The check stage met its contract: code reads the verdict from its `## Unresolved` (rules
    v2.13). The task's result is that stage's `## Deliverable` alone; the check is
    `checked-by-stage n` with the verdict in check_state, passed or failed. No fix round, and
    nothing is sent to anyone. Exit 0 on passed, 5 on failed, as for any check."""
    task_id = task["task_id"]
    verdict = relay.VERDICTS[step.stage.contract](step.result)
    deliverable = safety.redact(relay.check_parts(step.result)[0], secrets)
    with _hold_interrupts():
        try:
            log.set_done(conn, task_id, deliverable, None, check_state=verdict,
                         check_note=fallback.with_note(f"checked-by-stage {step.n}", log.calls_for(conn, task_id)))
        except log.StateError:
            receipt.mark(out, code="state_changed")
            out(f"{task_id} is already {_status_text(log.get_task(conn, task_id))}, so this result was not saved.")
            return 1
    row = log.get_task(conn, task_id)
    out(f"{task_id} done, checked by stage {step.n} ({step.agent or step.stage.agent}):")
    _print_done(conn, row, secrets, out)
    _project_entry(conn, task_id, out)
    _memory_store(conn, task_id, out, hindsight=hindsight, secrets=secrets)  # rules v2.27
    return 5 if verdict == "failed" else 0


def _print_stages(conn, task_id, secrets, out):
    """Every stage result so far, oldest first: the heading, then the text."""
    described = relay.describe_calls(log.calls_for(conn, task_id))
    if not described:
        out("No stage produced a result.")
        return
    out("Every stage result so far:")
    for head, text in described:
        out(head)
        if text:
            out(safety.for_terminal(text, secrets))


def run_relay(conn, task_id, deps, secrets, out):
    """Run or continue a relay task's chain and its check, with Ctrl+C handled by the task's
    real state in the log, as `route` does."""
    _STAGE.update(task_id=None, kind=None, agent=None, stage=None, role=None)
    try:
        return _run_loop(conn, task_id, deps, secrets, out)
    except KeyboardInterrupt:
        return _after_interrupt(conn, task_id, secrets, out, hindsight=getattr(deps, "hindsight", None))


def _delivery(task, step):
    """The files this call gets: (source, relative name) pairs, from the task's copies, frames and
    pages (a PDF goes to ChatGPT as page images), plus, for the checker of make_media, the images
    Grok made. Empty when there is nothing."""
    if step.action in ("check", "recheck"):
        return _check_items(task)
    records = log.files_of(task)
    return media.layout(task["task_id"], records, agent=task["agent"]) if records else []


def _check_items(task):
    """What the checker of a task gets: the doer's files, and Grok's images for make_media."""
    outputs = media.outputs(task["task_id"]) if task["skill"] == "make_media" else []
    records = log.files_of(task)
    if not records and not outputs:
        return []
    return media.layout(task["task_id"], records, outputs=outputs, agent=task["checker"])


def _call_search(task, step, ready=lambda: False):
    """The search state of the call a check-loop step asks for (router/search.py): on research-build's
    fix round, by preset and role, whichever agent fixes; None everywhere else."""
    agent = task["agent"] if step.action in ("do", "fix") else task["checker"]
    return search.state(task, kind=step.action, role=None, agent=agent, files=_delivery(task, step), ready=ready)


def _plan_call(task, step, calls=(), searching=None):
    """The id, kind, agent, prompt and web-search setting of the call a step asks for. A task
    with files adds the files paragraph: where the copies are, that they are data, and which
    ones this agent cannot open (then its check is a sanity check only). On a relay task the
    check and re-check run with web search on (the result cites sources; the owner's choice 6) and
    the fix round also carries the result of the stage before, as data (rules v2.12). `searching` is
    the call's search state (_call_search): when allowed, a ChatGPT call runs with its search live."""
    task_id, text, skill = task["task_id"], task["task"], task["skill"]
    base = log.fallback_base(task_id, calls)  # after `sr fallback` the redo's rounds are <task>-fb1-c1, …
    is_relay = _mode(task) in ("relay", "split")  # a split's integration is checked like a relay result (D7)
    agent = task["agent"] if step.action in ("do", "fix") else task["checker"]
    on = searching == search.ALLOWED  # rules v2.22: from the call's search state alone, never the skill or the role
    web_search = "live" if on else "disabled"   # ChatGPT's setting; Grok ignores it, Claude's comes from `searching`
    no_tools = agent == "claude" and not on     # Claude without search: no tools beyond Read on a call with files
    claude_search = agent == "claude" and on
    can_browse = agent == "grok" or (agent == "chatgpt" and on)
    files_text = media.files_paragraph(agent, _delivery(task, step), notes=media.page_notes(log.files_of(task), agent))
    imagine = skill == "make_media" and agent == "grok"  # Grok makes the image and commits it
    prior = _prior_result(calls) if is_relay and step.action == "fix" else None
    prior_label, prior_lines = relay.NOTE_LABEL, None
    attacks = relay.attack_text(calls) if is_relay else None  # redteam (rules v2.23): the checker gets it too
    if attacks is not None and step.action == "fix":  # decision 8: the attack list is the stage before
        prior, prior_label, prior_lines = attacks, relay.ATTACK_LIST_LABEL, [relay.REDTEAM_FIX_LINE]
    if _mode(task) == "split" and step.action == "fix":  # D8: the pieces block is the stage before
        plan = log.split_plan_of(task)
        prior, prior_label = split.pieces_text(plan["inputs"], plan["join"]), split.PIECES_LABEL
        prior_lines = [split.FIX_LINE]
    handoff = context.needs_handoff(task, agent)  # rules v2.25: the build call on a project task (never Grok)
    no_feed = checking.no_feed(task, agent, calls) and step.action in ("do", "fix")  # brief 24 (decision 9)
    # brief 24, the owner after F: the check and re-check of that work get the checker's line
    feed_check = checking.no_feed(task, task["agent"], calls) and step.action in ("check", "recheck")
    if step.action == "do" and step.missing:  # the doer's one contract re-ask: the task, its own result, the items
        prompt = relay.reask_prompt("build", text, step.result, step.missing, shape=context.HANDOFF_LINE, search=on)
        if files_text:
            prompt = f"{prompt}\n\n{files_text}"
        if no_feed:
            prompt = f"{prompt}\n\n{checking.NO_FEED_LINE}"
        return f"{base}{context.DO_REASK}", "do", agent, prompt, web_search
    if step.action == "do":
        prompt = f"{text}\n\n{files_text}" if files_text else text
        if on:  # D7: the general search line after the task
            prompt = f"{prompt}\n\n{checking.SEARCH_LINE_GENERAL}"
        if no_feed:  # brief 24 (decision 9): after the search line, before the image and handoff lines
            prompt = f"{prompt}\n\n{checking.NO_FEED_LINE}"
        if imagine:
            prompt = grok.make_media_prompt(task_id, prompt)
        if handoff:
            prompt = f"{prompt}\n\n{context.HANDOFF_LINE}"
        return task_id, "do", agent, prompt, web_search
    judges_handoff = context.needs_handoff(task, task["agent"])  # rules v2.25: the build agent's result has the section
    judges_memory = _build_carried_memory(task, calls)  # rules v2.27: the build call got a memory block
    if step.action == "check":
        prompt = checking.checker_prompt(text, step.result, no_tools=no_tools, can_browse=can_browse, files_text=files_text,
                                         relay=is_relay, claude_search=claude_search, search=on, attacks=attacks,
                                         handoff=judges_handoff, memory=judges_memory, no_feed=feed_check)
        return f"{base}-c1", "check", agent, prompt, web_search
    if step.action == "fix" and step.missing:  # a fix's one contract re-ask: the task, its own fix, the items
        shape = relay.REVISE_REPLY if attacks is not None else ""  # redteam keeps `## Answered`
        if handoff:  # rules v2.25: the handoff shape too (alone on a routed project task)
            shape = f"{shape}\n\n{context.HANDOFF_LINE}".strip()
        prompt = relay.reask_prompt("revise", text, step.result, step.missing, shape=shape or None,
                                    search=searching == search.ALLOWED)
        return f"{base}{checking.FIX_REASK}", "fix", agent, prompt, web_search
    if step.action == "fix":
        prompt = checking.fix_prompt(text, step.result, step.fix_list, files_text=files_text, prior=prior,
                                     prior_label=prior_label, search=searching == search.ALLOWED,
                                     prior_lines=prior_lines, count=True,
                                     after_notes=grok.imagine_instructions(task_id) if imagine else None,
                                     handoff=handoff, no_feed=no_feed)
        return f"{base}-f1", "fix", agent, prompt, web_search
    prompt = checking.checker_prompt(text, step.result, no_tools=no_tools, can_browse=can_browse, files_text=files_text,
                                     relay=is_relay, claude_search=claude_search, search=on, attacks=attacks,
                                     handoff=judges_handoff, memory=judges_memory, no_feed=feed_check)
    return f"{base}-c2", "recheck", agent, prompt, web_search


def _build_carried_memory(task, calls):
    """Whether the build call's row says a memory block went with it (`sent` at least 1): then the checker gets the
    memory line (rules v2.27, Checking) and the same block, from that row, through context.attach."""
    if not log.tag_of(task) or not calls:
        return False
    build = _build_call(task, calls)
    record = log.call_memory_of(build) if build is not None else None
    return bool(record and record.get("sent"))


def _prior_result(calls):
    """On a relay task, the accepted result of the stage before the last one (what the last stage
    was built from), or None when there was no stage before."""
    results = relay.stage_results(calls)
    if not results:
        return None
    return results.get(max(results) - 1)


def _call_text(call):
    if call["kind"] in log.STAGE_KINDS:
        what = f"stage {call['stage']} re-ask" if call["kind"] == "reask" else f"stage {call['stage']}"
        return f"{call['call_id']} ({what}, {call['role']} by {call['agent']})"
    return f"{call['call_id']} ({call['kind']} by {call['agent']})"


def _search_record(searching, answer=None):
    """The search record a call row keeps: its state, and the queries Claude ran when its tool log
    reported them (more than search.MAX_SEARCHES is kept as it is: logged, never refused)."""
    if searching is None:
        return None
    record = {"state": searching}
    queries = getattr(answer, "queries", None)
    if queries is not None:
        record.update(queries=list(queries), count=len(queries))
    return record


def _send_local(conn, task, call_id, kind, prompt, deps, agent, call, *, secrets, out, files=(), stage=None, role=None,
                searching=None, context=None, memory=None, resume_of=None):
    """Brief 22 (Phase 0 choice 1): the note of the call in flight beside the log, written before the call and removed once
    its row is written (or the call ends without one), so a process that dies during the call leaves `sr check` what it
    needs to write the process-ended stop. Then the call itself (_send_local_call)."""
    runs.note_call(task["task_id"], {"call_id": call_id, "kind": kind, "agent": agent, "stage": stage, "role": role,
                                     "search": _search_record(searching), "context": context, "memory": memory,
                                     "resume_of": resume_of})
    try:
        return _send_local_call(conn, task, call_id, kind, prompt, deps, agent, call, secrets=secrets, out=out,
                                files=files, stage=stage, role=role, searching=searching, context=context, memory=memory,
                                resume_of=resume_of)
    finally:
        runs.clear_call(task["task_id"], call_id)


def _send_local_call(conn, task, call_id, kind, prompt, deps, agent, call, *, secrets, out, files=(), stage=None, role=None,
                     searching=None, context=None, memory=None, resume_of=None):
    """One call to an agent that answers at once (Claude or ChatGPT), written to the log already
    finished. A Ctrl+C during a check, fix or re-check (or a relay stage after the first) leaves no
    row, so `sr check` runs that step again. `files` (media.layout pairs) go to the worker as copies
    for this call only; `stage` and `role` are set on a relay stage call.
    Returns None to continue the loop, or an exit code."""
    task_id = task["task_id"]
    _STAGE.update(task_id=task_id, kind=kind, agent=agent, stage=stage, role=role)
    try:
        answer = call(prompt, files=files, tag=task_id) if files else call(prompt)
        text = safety.redact(answer, secrets)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        _STAGE.update(task_id=None, kind=None, agent=None, stage=None, role=None)
        # brief 24 (C5): every agent's failure reaches here as a SafeError (the workers wrap them); anything else is an
        # error in the router's own code, `internal_error`, never taken over
        code = getattr(e, "code", None) if isinstance(e, safety.SafeError) else takeover.INTERNAL
        return _call_failed(conn, task_id, call_id, kind, agent, safety.redact(_describe(e), secrets), secrets, out,
                            stage=stage, role=role, reason_code=code, searching=searching, context=context, memory=memory,
                            served=getattr(e, "served", None), resume_of=resume_of,
                            deps=deps)  # rules v2.28: a Cursor failure keeps what answered
    _STAGE.update(task_id=None, kind=None, agent=None, stage=None, role=None)
    with _hold_interrupts() as held:  # the row is written whole
        row = log.get_task(conn, task_id)
        if row["status"] not in ("queued", "sent"):
            receipt.mark(out, code="state_changed")
            out(f"{task_id} is already {_status_text(row)}, so this answer was not saved:")
            out(safety.for_terminal(text, secrets))
            return 1
        verdict = checking.read_verdict(text)[0] if kind in ("check", "recheck") else None
        log.add_call(conn, call_id, task_id, kind, agent, status="done", text=text, verdict=verdict, stage=stage, role=role,
                     search=_search_record(searching, answer), context=context, memory=memory, resume_of=resume_of,
                     served=getattr(answer, "served", None))  # rules v2.28: a Cursor answer carries its served record
    if held.pressed:
        raise KeyboardInterrupt
    return None


def _call_failed(conn, task_id, call_id, kind, agent, error, secrets, out, *, stage=None, role=None,
                 reason_code=None, searching=None, context=None, memory=None, served=None, resume_of=None, deps=None):
    """A call that failed or couldn't be made, logged as a failed call row with its reason code
    (plan_limit, or none). The task fails when it was the first call; otherwise the row lets the
    loop (or the relay runner) end in the right row. Since build brief 7 a failed first call leaves
    its row too, so a plan limit there can be resumed. Build brief 24 (decision 6): with a gate, a failed first call
    leaves the task open, so the loop asks the takeover first; nobody taking it over fails the task there."""
    with _hold_interrupts():
        log.add_call(conn, call_id, task_id, kind, agent, status="failed", text=error, stage=stage, role=role,
                     reason_code=reason_code, search=_search_record(searching), context=context, memory=memory, served=served,
                     resume_of=resume_of)
    if kind == "do" and not _takes_over(deps):
        return _fail(conn, task_id, error, secrets, out)
    return None


def _send_claude(conn, task, call_id, kind, prompt, deps, *, secrets, out, web_search="disabled", files=(),
                 stage=None, role=None, searching=None, limited=False, context=None, memory=None, resume_of=None):
    """One Claude call. Claude's search comes only from router/search.py's state (`search`), never from
    `web_search`, which is ChatGPT's setting (a relay check is `live` for ChatGPT; a Claude checker
    never searches)."""
    call = functools.partial(deps.worker, search=True) if searching == search.ALLOWED else deps.worker
    return _send_local(conn, task, call_id, kind, prompt, deps, "claude", call, secrets=secrets, out=out,
                       files=files, stage=stage, role=role, searching=searching, context=context, memory=memory,
                       resume_of=resume_of)


def _send_chatgpt(conn, task, call_id, kind, prompt, deps, *, secrets, out, web_search="disabled", files=(),
                  stage=None, role=None, searching=None, limited=False, context=None, memory=None, resume_of=None):
    """One ChatGPT call through Codex. Before the first one in a command, `codex login status`
    must report a ChatGPT login; otherwise no call is made and the round fails with the reason,
    so nothing can fall back to an API key."""
    task_id = task["task_id"]
    if deps.chatgpt is None:
        return _call_failed(conn, task_id, call_id, kind, "chatgpt",
                            "ChatGPT isn't configured (no model in config/agents.json, or the config didn't load)",
                            secrets, out, stage=stage, role=role, searching=searching, context=context, memory=memory,
                            resume_of=resume_of, deps=deps)
    if deps.codex_ok is None:
        deps.codex_ok = bool(deps.codex_login()) if deps.codex_login is not None else False
    if not deps.codex_ok:
        return _call_failed(conn, task_id, call_id, kind, "chatgpt",
                            "Codex isn't signed in with ChatGPT: run `codex login` in Terminal (never an API key)",
                            secrets, out, stage=stage, role=role, searching=searching, context=context, memory=memory,
                            resume_of=resume_of, deps=deps)
    if getattr(deps, "codex_probe_ok", None) is None:  # brief 24 (decision 10): once per command, before the first call
        ready = getattr(deps, "chatgpt_ready", None)
        try:
            deps.codex_probe_ok = tuple(ready()) if ready is not None else (True, None)
        except AttributeError:
            pass
    ok, why = getattr(deps, "codex_probe_ok", None) or (True, None)
    if not ok:
        return _call_failed(conn, task_id, call_id, kind, "chatgpt", why, secrets, out, stage=stage, role=role,
                            searching=searching, context=context, memory=memory, resume_of=resume_of, deps=deps)
    return _send_local(conn, task, call_id, kind, prompt, deps, "chatgpt",
                       functools.partial(deps.chatgpt, web_search=web_search), secrets=secrets, out=out, files=files,
                       stage=stage, role=role, searching=searching, context=context, memory=memory, resume_of=resume_of)


def _keep_stream(task_id, call_id, found, secrets):
    """Choice 3 (build brief 20): a Cursor call's raw stream, redacted, under media/cursor/<task-id>/<call-id>.ndjson,
    owner-only; the served record names it. Nothing is kept when the command never ran (no stream) or no record came."""
    stream, served = getattr(found, "stream", None), getattr(found, "served", None)
    if stream is None or served is None:
        return
    folder = media.MEDIA_ROOT / "cursor" / task_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{call_id}.ndjson"
    path.write_text(safety.redact(stream, secrets))
    os.chmod(path, 0o600)
    served["stream"] = f"media/cursor/{task_id}/{call_id}.ndjson"


def _send_cursor(conn, task, call_id, kind, prompt, deps, *, secrets, out, web_search="disabled", files=(), stage=None,
                 role=None, searching=None, limited=False, context=None, memory=None, resume_of=None):
    """One Cursor call (rules v2.28, Cursor; build brief 20) through the Cursor worker: the prompt the Claude worker
    would get for the role, opened by the scope paragraph and the no-tools sentence (cursor_worker.wrap). Before the
    first one in a command, `cursor_ready` must say the sandbox probe's pass is on the installed agent and the command
    is signed in (asked once, kept in `deps.cursor_ok`); otherwise no call is made and the round fails with the reason.
    The served record rides on the row, done or failed; the raw stream is kept under media/cursor/. Cursor never
    searches and never takes a file."""
    task_id = task["task_id"]
    worker = getattr(deps, "cursor", None)
    if worker is None:
        return _call_failed(conn, task_id, call_id, kind, "cursor",
                            "Cursor isn't configured (no model in config/agents.json, or the config didn't load)",
                            secrets, out, stage=stage, role=role, context=context, memory=memory)
    if getattr(deps, "cursor_ok", None) is None:
        check = getattr(deps, "cursor_ready", None)
        deps.cursor_ok = tuple(check()) if check is not None else (False, "cursor: readiness unknown (no check given)")
    ok, reason = deps.cursor_ok
    if not ok:
        return _call_failed(conn, task_id, call_id, kind, "cursor", reason, secrets, out, stage=stage, role=role,
                            context=context, memory=memory)

    def call(text):
        try:
            found = worker(cursor_worker.wrap(text), call_id=call_id)
        except cursor_worker.WorkerError as e:
            _keep_stream(task_id, call_id, e, secrets)
            raise
        _keep_stream(task_id, call_id, found, secrets)
        return found

    return _send_local(conn, task, call_id, kind, prompt, deps, "cursor", call, secrets=secrets, out=out, files=(),
                       stage=stage, role=role, searching=None, context=context, memory=memory)


def _send_grok(conn, task, call_id, kind, prompt, deps, *, secrets, out, web_search="disabled", files=(),
               stage=None, role=None, searching=None, limited=False, context=None, memory=None, resume_of=None):
    """One Grok call through the webhook, logged as sent and collected later by its id (the
    issue's title). `files` are never sent: Grok gets no file, ever (rules v2.10).
    `limited` (rules v2.21): the call hands Grok an earlier result to judge or build on (a check, a re-check, a
    review, a stage given an earlier stage's result); past `grok_prompt_limit` it is never sent and the round or
    stage fails with `too long for Grok (<n> characters)`. The prompt is never trimmed.
    Returns None to continue the loop, or an exit code."""
    task_id = task["task_id"]
    if limited:
        most, _ = settings.grok_prompt_limit()
        if len(prompt) > most:
            reason = f"too long for Grok ({len(prompt)} characters)"
            with _hold_interrupts():
                log.add_call(conn, call_id, task_id, kind, "grok", status="failed", text=reason, stage=stage, role=role,
                             reason_code=takeover.TOO_LONG, context=context, memory=memory, resume_of=resume_of)
            out(f"{call_id} not sent: {reason}; the limit is {most}. Run the task again with another agent there.")
            return None
    sent_at = None
    if BACKDATE_MINUTES:  # brief 24 (C8): test-only, on a scratch log; the next check reads the call overdue
        sent_at = datetime.now(timezone.utc) - timedelta(minutes=BACKDATE_MINUTES)
    with _hold_interrupts() as held:  # a Ctrl+C here waits until the send is logged
        try:
            missing = [n for n in availability.WEBHOOK_NAMES if not (deps.config.get(n) or "").strip()]
            if missing:  # brief 24 (decision 12): Grok Bot isn't set up; nothing is sent
                raise grok.DispatchError(f"Grok Bot isn't set up: no {' or '.join(missing)} in .env")
            run_uuid = grok.send(call_id, prompt, deps.config["GROK_WEBHOOK_URL"], deps.config["GROK_WEBHOOK_KEY"],
                                 deps.post)
        except Exception as e:
            error = safety.redact(_describe(e), secrets)
            if kind == "do" and not _takes_over(deps):
                return _fail(conn, task_id, error, secrets, out)
            log.add_call(conn, call_id, task_id, kind, "grok", status="failed", text=error, stage=stage, role=role,
                         context=context, memory=memory, resume_of=resume_of)  # brief 24: a failed first send leaves its row
            return None
        try:
            if kind == "do" and call_id == task_id:
                log.set_sent(conn, task_id, run_uuid, now=sent_at, context=context, memory=memory)
            else:  # a takeover's first call (brief 24) is logged under its own id, as any other Grok call
                log.add_call(conn, call_id, task_id, kind, "grok", run_uuid=run_uuid, stage=stage, role=role,
                             now=sent_at, context=context, memory=memory, resume_of=resume_of)
                log.set_open_status(conn, task_id, "sent")
        except log.StateError:
            row = log.get_task(conn, task_id)
            receipt.mark(out, code="state_changed")
            out(f"{call_id} reached Grok, but the log already says {_status_text(row)}. "
                "Grok may still post a result; its issue will stay open.")
            return 1
    out(f"{call_id} sent to grok ({kind}).")
    try:  # brief 24: the calls this command sent; only route's own wait reads one of them overdue
        deps.sent_here = (getattr(deps, "sent_here", None) or set()) | {call_id}
    except AttributeError:
        pass
    if held.pressed:
        out("Stopped before waiting (Ctrl+C). Grok is still working; `sr check` will collect the result.")
        return 130
    return None


# Agent name -> the function that sends it a call. Every live agent in config/agents.json needs
# an entry here; load_roster refuses the config otherwise.
SENDERS = {"claude": _send_claude, "grok": _send_grok, "chatgpt": _send_chatgpt, "cursor": _send_cursor}


def _collect(conn, match, secrets, out, close):
    """A Grok call's issue arrived: finish the call, hand the task back to the loop, close the
    issue. For a make_media do or fix call the listed images are pulled first; none coming back
    is a failed round, Grok's text kept. Returns False when the call had already moved."""
    call = log.get_call(conn, match["task_id"])
    text = safety.redact(match["result"], secrets)
    task = log.get_task(conn, call["task_id"])
    status = "done"
    if task is not None and task["skill"] == "make_media" and call["kind"] in ("do", "fix"):
        text, status = _pull_images(task["task_id"], text, secrets, out)
    try:
        log.finish_call(conn, call["call_id"], status, text=text, url=match["url"],
                        verdict=checking.read_verdict(text)[0] if call["kind"] in ("check", "recheck") else None)
        log.set_open_status(conn, call["task_id"], "queued")  # no Grok call is out now
        log.set_grok_note(conn, call["task_id"], None)  # brief 21, C2: the return clears the Grok timeout note
    except log.StateError:
        return False
    out(f"{_call_text(call)} arrived (issue #{match['number']}).")
    if task is not None and _mode(task) == "relay" and call["kind"] in log.STAGE_KINDS:
        named = relay.named_files(text)
        if named:  # a relay stage takes no file (rules v2.12): said, never fetched
            shown = ", ".join(safety.one_line(n, secrets) for n in named)
            out(f"Ignored file(s) grok named in stage {call['stage']} (a relay stage takes no file): {shown}")
    if status == "failed" and call["kind"] == "do":
        _fail(conn, task["task_id"], f"no image came back from grok. Its text: {text[:300]}", secrets, out)
    try:
        close(match["number"])
    except Exception as e:
        out(f"Warning: could not close issue #{match['number']}: {safety.for_terminal(_describe(e), secrets)}")
    return True


def _store_late(conn, match, secrets, out, close):
    """Brief 24 (decision 7): a Grok answer that came after its call was taken over at overdue is stored on that row,
    marked late, its round file written and its issue closed. Nothing else changes: never the result, never sent to a
    checker, never in memory or the handoff."""
    text = safety.redact(match["result"], secrets)
    if not log.store_late(conn, match["task_id"], text, url=match["url"]):
        return
    call = log.get_call(conn, match["task_id"])
    out(f"{_call_text(call)}: its late answer came (issue #{match['number']}); kept on the log, not used.")
    try:
        close(match["number"])
    except Exception as e:
        out(f"Warning: could not close issue #{match['number']}: {safety.for_terminal(_describe(e), secrets)}")


def _pull_images(task_id, text, secrets, out):
    """Pull every image Grok listed for this task from the inbox repo into media/out/<task-id>/.
    Returns the call text with the local paths appended, and the call status: failed when no
    image came back. Paths outside media/out/<task-id>/ are ignored and said so."""
    accepted, ignored = inbox.listed_images(text, task_id)
    for path in ignored:
        out(f"Ignored a path grok listed outside media/out/{task_id}/: {safety.for_terminal(path, secrets)}")
    saved = []
    for path in accepted:
        name = path.rsplit("/", 1)[1]
        try:
            data = inbox.fetch_file(path)
        except Exception as e:
            out(f"Could not pull {name}: {safety.for_terminal(_describe(e), secrets)}")
            continue
        if not data.startswith(inbox.PNG_MAGIC):
            out(f"Ignored {name}: not a PNG.")
            continue
        saved.append(media.save_output(task_id, name, data))
    if not saved:
        out(f"No image came back for {task_id}: a failed round, never retried. Grok's text is kept.")
        return text, "failed"
    note = f"{len(saved)} image(s) pulled" + (f" (the cap is {grok.IMAGE_CAP})" if len(saved) > grok.IMAGE_CAP else "")
    out(f"{note} into media/out/{task_id}/.")
    listing = "\n".join(str(p.relative_to(safety.REPO_ROOT)) if p.is_relative_to(safety.REPO_ROOT) else str(p) for p in saved)
    return f"{text}\n\nImages:\n{listing}", "done"


def _note_grok(conn, task, call, deps):
    """The Grok timeout note (brief 21, C2; rules v2.30, Grok timeout) on a task whose Grok call is out: `waiting: grok,
    <m> min` from N minutes, `overdue: grok, <m> min` from 2N (N: `grok_timeout_minutes` in config/settings.json; none:
    no note). Never over a note that isn't a Grok note (C6). It changes nothing else: no retry, no cancel, no second
    send."""
    if task is None or call is None or call["agent"] != "grok" or call["status"] != "sent":
        return
    n = getattr(deps, "grok_timeout", None)
    note = log.grok_note(call["sent_at"], getattr(deps, "now", None), settings.grok_timeout_minutes() if n is None else n)
    if note is not None:
        log.set_grok_note(conn, task["task_id"], note)


def _wait_for_call(conn, task_id, call, deps, secrets, out):
    """Poll the inbox for one call's issue, until WAIT_SECONDS pass. Returns None once it has
    arrived (the loop goes on), or an exit code. Never marks anything failed because of an
    inbox error: the call WAS sent, and `check` can still collect it."""
    call_id = call["call_id"]
    out(f"Waiting up to {WAIT_SECONDS // 60} min for Grok. Ctrl+C stops waiting; the task keeps running.")
    deadline = deps.clock() + WAIT_SECONDS
    errors, tried = 0, False
    while True:
        row = log.get_task(conn, task_id)
        if row is None or row["status"] != "sent":
            return _moved_while_waiting(conn, row, task_id, secrets, out)
        try:
            issues = deps.fetch()
        except Exception as e:
            errors += 1
            out(f"Could not read the inbox: {safety.for_terminal(_describe(e), secrets)}")
            if getattr(e, "returncode", None) == GH_LOGGED_OUT or errors >= MAX_INBOX_ERRORS:
                out(f"Stopped waiting. {call_id} WAS sent; don't resend it. Run `sr check` later.")
                return 3
        else:
            errors = 0
            # An empty body means the issue exists but its result isn't written yet.
            matches = [m for m in inbox.match_results([call_id], issues) if m["result"].strip()]
            if matches:
                if not _collect(conn, matches[0], secrets, out, deps.close):
                    return _moved_while_waiting(conn, log.get_task(conn, task_id), task_id, secrets, out)
                return None
        _note_grok(conn, row, call, deps)  # brief 21, C2: the page sees the note while Terminal waits
        if not tried and _overdue(row, log.calls_for(conn, task_id), deps, own=True) is not None:  # brief 24 (decision 6)
            tried = True
            code = _take_over(conn, task_id, deps, secrets, out, own=True)
            if code is not None:
                return None if code is _TOOK else code
        left = deadline - deps.clock()
        if left <= 0:
            out(f"No result after {WAIT_SECONDS // 60} min. {_call_text(call)} is still out; don't resend it. "
                "Run `sr check` later.")
            return 3
        deps.sleep(min(POLL_SECONDS, left))


def _moved_while_waiting(conn, row, task_id, secrets, out):
    if row is not None and row["status"] == "done":
        out(f"{task_id} was collected by another command:")
        _print_done(conn, row, secrets, out)
        return 0
    receipt.mark(out, code="state_changed")
    out(f"{task_id} is now {_status_text(row)}. Stopped waiting.")
    return 1


def _finish(conn, task, step, secrets, out, hindsight=None):
    """The loop has ended: write the furthest result once, with the final check state and note,
    then show the owner the result and how the check went."""
    task_id = task["task_id"]
    if step.ending is None:
        row = log.get_task(conn, task_id)
        if row["status"] == "done":
            out(f"{task_id} is done:")
            _print_done(conn, row, secrets, out)
            return 5 if row["check_state"] == "failed" else 0
        out(f"{task_id} is {_status_text(row)}.")
        return 1
    calls = log.calls_for(conn, task_id)
    view = log.fallback_view(calls)
    do = next((c for c in reversed(view) if c["kind"] == "do" and c["status"] == "done"),  # brief 24: a takeover's
              next((c for c in view if c["kind"] == "do"), None))
    note = step.note
    skipped = task["check_note"] if (task["check_note"] or "").startswith(GROK_SKIPPED) else None
    if skipped and note and not note.startswith(GROK_SKIPPED):  # brief 24 (C11): the skip stays on the card
        note = f"{skipped.split('; ', 1)[0]}; {note}"
    if step.ending in (4, 5, 7):  # brief 24 (decision 6): the takeover's own round stopped too: both reasons
        note = (note or "") + _after_takeover(checking._by_kind(view, {4: "check", 5: "fix", 7: "recheck"}[step.ending]),
                                              calls) or None
    result = step.result
    if log.project_of(task):  # rules v2.25 (decision 17): the deliverable is the result; the ## Handoff section is not
        result = context.split_handoff(result or "")[0]
    if _mode(task) == "relay" and relay.attack_text(log.fallback_view(calls)) is not None:
        result = relay.split_answered(result or "")[0]  # rules v2.23: the deliverable is the result; ## Answered not
    with _hold_interrupts():
        try:
            log.set_done(conn, task_id, result, do["url"] if do else None, check_state=step.check_state,
                         check_note=fallback.with_note(note, calls))
        except log.StateError:
            receipt.mark(out, code="state_changed")
            out(f"{task_id} is already {_status_text(log.get_task(conn, task_id))}, so this result was not saved.")
            return 1
    row = log.get_task(conn, task_id)
    out(f"{task_id} done by {row['agent']}:")
    _print_done(conn, row, secrets, out)
    _project_entry(conn, task_id, out)  # rules v2.25: the entry (or the failed line) after the result is shown
    _memory_store(conn, task_id, out, hindsight=hindsight, secrets=secrets)  # rules v2.27: the retain, beside it
    return step.exit_code


def _print_done(conn, row, secrets, out):
    """A finished task's result, made safe, then the line that says how its check went. A task
    checked by a stage that did not pass shows the deliverable and the unresolved list, labelled."""
    n = relay.checked_by_stage(row)
    if n is not None and row["check_state"] == "failed":
        for line in _by_stage_failed_lines(conn, row, n, secrets):
            out(line)
        return
    out(safety.for_terminal(row["result"], secrets))
    for line in _ending_lines(conn, row, secrets):
        out(line)
    for line in _redteam_lines(conn, row, secrets):
        out(line)


def _redteam_lines(conn, row, secrets):
    """On a redteam task (rules v2.23): the attack list under the result, as stored, then the revision's
    `## Answered` (the owner's choice 6). Nothing on any other task."""
    if _mode(row) != "relay":
        return []
    calls = log.fallback_view(log.calls_for(conn, row["task_id"]))
    attacks = relay.attack_text(calls)
    if attacks is None:
        return []
    lines = ["--- attacks ---", safety.for_terminal(attacks, secrets)]
    revision = relay.final_revision(calls)
    answered = relay.split_answered(revision)[1] if revision else None
    if answered is not None:
        lines += ["--- answered ---", safety.for_terminal(answered, secrets)]
    return lines


def _ending_lines(conn, row, secrets):
    """How the check went, from the task's calls. A task from before the calls table gets the
    plain UNCHECKED line when it is unchecked, and nothing otherwise."""
    state = row["check_state"]
    n = relay.checked_by_stage(row)
    if n is not None:  # the check stage replaced the checker loop: its verdict is check_state
        return [f"CHECKED: by stage {n} ({row['checker']}): passed."] if state == "passed" else []
    step = checking.ending_of(row, log.calls_for(conn, row["task_id"]))
    if step is None:
        if state == "unchecked":
            return [f"UNCHECKED: {row['check_note']}." if row["check_note"] else UNCHECKED_LINE]
        return []
    e = step.ending
    items = _check_items(row)
    judged = _last_check_call(log.fallback_view(log.calls_for(conn, row["task_id"])), row["checker"])
    web = checking.web_sanity(row["skill"], row["checker"], record=log.search_of(judged) if judged else None,
                              recorded=judged is not None)  # rules v2.22: the checker's real search on that call
    files = checking.file_sanity(row["checker"], items)
    sanity = web or files
    checked = "CHECKED (sanity check only)" if sanity else "CHECKED"
    tail = (f" {SANITY_NOTE}" if web else "") + (f" {FILES_NOTE}" if files else "")
    if row["checker"] == "chatgpt":  # a PDF reaches ChatGPT as its first pages; say when pages were cut
        for name, seen, total in media.cut_pages(log.files_of(row)):
            tail += f" Pages 1 to {seen} of {total} of {name} were seen."
    reason = safety.for_terminal(step.reason, secrets)
    fix_list = safety.for_terminal(step.fix_list, secrets)
    if e == 1:
        return []
    if e == 2:
        return [f"UNCHECKED: {step.note}." if step.note else UNCHECKED_LINE]
    if e == 3:
        return [f"{checked}: passed.{tail}"]
    if e == 4:
        return [f"CHECK ROUND FAILED: {step.agent}, {reason}. This result is unchecked."]
    if e == 5:
        return [f"FIX ROUND FAILED: {step.agent}, {reason}.", "The checker's fix list:", fix_list]
    if e == 6:
        return [f"{checked}: passed after one fix.{tail}",
                f"`sr show {row['n']} --history` shows the original and the fix list."]
    if e == 7:
        return [f"CHECK ROUND FAILED: {step.agent} (the re-check), {reason}. "
                "The first check asked for fixes; this is the fixed result."]
    return ["NOT PASSED: after one fix round. What the checker still wants fixed:", fix_list]


def _by_stage_failed_lines(conn, row, n, secrets):
    """A failed check by stage n: the NOT PASSED line, the edited deliverable (the task's result)
    and the unresolved list read from that stage's accepted result, each labelled."""
    text = relay.stage_results(log.calls_for(conn, row["task_id"])).get(n)
    unresolved = relay.check_parts(text)[2] if text else None
    return [f"NOT PASSED: by stage {n} ({row['checker']}). The edited deliverable, then what it could not fix.",
            "Deliverable:", safety.for_terminal(row["result"], secrets),
            "Unresolved:", safety.for_terminal(unresolved or "(not found in the stage result)", secrets)]


def _last_check_call(calls, checker):
    """The last check or re-check row by the task's checker, or None."""
    return next((c for c in reversed(calls) if c["kind"] in ("check", "recheck") and c["agent"] == checker), None)


def _confidence(value):
    return f"{value:.2f}" if isinstance(value, (int, float)) else "-"


def _jev_text(answer, roster):
    """Jev's answer in words: the label and its confidence, or why there is none."""
    status = answer["status"]
    if status == "not_asked":  # brief 22 (decision 2): the owner gave the skill with --skill
        return "Jev wasn't asked: you gave the skill (--skill)."
    if status == "over_cap":
        return f"Jev wasn't asked: this month's {jev.MONTHLY_TOKEN_CAP:,} input tokens are used up."
    if status == "not_set_up":  # brief 24 (decision 13): no JEV_API_KEY; there is no second labeler
        return "Jev isn't set up: pick the skill."
    if status == "error":
        return f"Jev couldn't label it (error: {answer.get('error')})."
    text = f"Jev's label: {answer.get('label')}, confidence {_confidence(answer.get('confidence'))}"
    if status == "below_floor":
        text += f", under the {roster.labeler['min_confidence']} floor"
    return text + "."


def _route_text(task_id, answer, decision, roster):
    """Before the result: the skill, who chose it and how sure, the doer and why."""
    if decision.skill is None:
        skill = "no skill"
    elif decision.skill_source == "owner":
        skill = f"{decision.skill} (your choice)"
    else:
        skill = f"{decision.skill} (Jev, confidence {_confidence(answer.get('confidence'))})"
    stood = routing.stand_in_of(decision.reason)
    if stood is not None:  # brief 24 (decision 3): the stand-in and why
        why = f"standing in for {stood[0]} ({stood[1]})"
    elif decision.reason == "interim":
        why = f"standing in while {roster.skills[decision.skill]['best']} isn't live"
    elif decision.reason == "override":
        why = f"you chose it with @{decision.agent}"
    else:
        why = "the skill's best agent"
    return f"{task_id}: {skill} -> {decision.agent}, {why}."


def _ask_for_skill(ask, roster, out):
    """Show the skills and read the owner's choice: a skill key, routing.NONE_OF_THESE, or
    routing.NO_ANSWER after MAX_BAD_ANSWERS answers in a row that aren't choices, or when the
    input ends. Ctrl+C isn't caught here: it cancels the task like anywhere else in route."""
    out("Which skill does this task need?")
    for n, key in enumerate(roster.skill_order, 1):
        out(f"  {n:>2}  {key}: {_one_line(roster.skills[key]['description'], 70)}")
    out("   0  none of these (the task comes back to you)")
    for _ in range(MAX_BAD_ANSWERS):
        try:
            reply = ask("Number or skill name: ")
        except EOFError:
            out("")
            return routing.NO_ANSWER
        text = reply.strip().lower()
        if text in ("0", "none", "none_of_these"):
            return routing.NONE_OF_THESE
        if re.fullmatch(r"[0-9]+", text) and 1 <= int(text) <= len(roster.skill_order):
            return roster.skill_order[int(text) - 1]
        if text in roster.skills:
            return text
        out(f"Not a choice: {_one_line(reply, 40) or '(empty)'}. Type a number from the list or a skill name.")
    out(f"{MAX_BAD_ANSWERS} answers in a row weren't choices.")
    return routing.NO_ANSWER


def _came_back(conn, task_id, answer, decision, roster, out):
    """The task comes back to the owner: log it as returned and say why. Exit code 4."""
    try:
        log.set_returned(conn, task_id, decision.reason, reason_code=decision.code, skill=decision.skill,
                         skill_source=decision.skill_source)
    except log.StateError:
        receipt.mark(out, code="state_changed")
        out(f"{task_id} is already {_status_text(log.get_task(conn, task_id))}.")
        return 1
    receipt.mark(out, code=decision.code)
    out(f"{task_id} came back to you: {decision.reason.removeprefix('returned: ')}.")
    if decision.skill and decision.skill_source == "owner":
        out(f"Skill: {decision.skill} (your choice).")
    out(_jev_text(answer, roster))
    if decision.reason == "returned: needs your label":
        tags = " or ".join(f"@{name}" for name in roster.live)
        out(f"Run it in Terminal to choose the skill, or start it with {tags}.")
    out("Nothing was sent to an agent.")
    _project_entry(conn, task_id, out)  # rules v2.25: the stopped line
    return 4


@contextmanager
def _hold_interrupts():
    """Delay Ctrl+C until the block ends. Uses a flag-only handler, not SIG_IGN, because child
    processes inherit an ignored Ctrl+C. Off the main thread nothing can be held."""
    held = SimpleNamespace(pressed=False)
    if threading.current_thread() is not threading.main_thread():
        yield held
        return

    def note(signum, frame):
        held.pressed = True

    previous = signal.signal(signal.SIGINT, note)
    try:
        yield held
    finally:
        signal.signal(signal.SIGINT, previous if previous is not None else signal.default_int_handler)


def _after_interrupt(conn, task_id, secrets, out, hindsight=None):
    """Ctrl+C: undo any half-finished write, then act on what the log really says. A result
    that has already arrived is delivered. A task whose first call was interrupted is cancelled.
    A task interrupted during a check round stays open for `sr check`."""
    stage, _ = dict(_STAGE), _STAGE.update(task_id=None, kind=None, agent=None, stage=None, role=None)
    with _hold_interrupts():
        conn.rollback()
        row = log.get_task(conn, task_id)
        if row is None:
            out("Stopped. Nothing was logged.")
            return 130
        if row["status"] in ("queued", "sent") and _mode(row) in ("relay", "split"):
            return _relay_interrupted(conn, row, stage, out)
        if row["status"] in ("queued", "sent"):
            step = checking.next_step(row, log.calls_for(conn, task_id))
            if step.action == "finish" and step.ending:
                out("Stopped, but the result had already arrived:")
                _finish(conn, row, step, secrets, out, hindsight=hindsight)
                return 130
            if stage["task_id"] == task_id and stage["kind"] in ("check", "fix", "recheck"):
                out(f"Stopped during the {stage['kind']} by {stage['agent']} (Ctrl+C). The task stays open; "
                    "run `sr check` to finish it.")
                return 130
            if row["status"] == "queued" and step.action != "do":
                out(f"Stopped before the {step.action} (Ctrl+C). The task stays open; run `sr check` to finish it.")
                return 130
            if row["status"] == "queued":
                try:
                    log.set_cancelled(conn, task_id, allowed_from=("queued",))
                    out(f"{task_id} cancelled (Ctrl+C).")
                    return 130
                except log.StateError:
                    row = log.get_task(conn, task_id)  # it moved a moment ago; report what it is now
            if row["status"] == "sent":
                out(f"Stopped waiting. {task_id} is still running at Grok; `sr check` will collect the result.")
                return 130
        if row["status"] == "done":
            out(f"Stopped. {task_id} is done:")
            _print_done(conn, row, secrets, out)
        else:
            out(f"Stopped. {task_id} is {_status_text(row)}.")
        return 130


def _relay_interrupted(conn, row, stage, out):
    """Ctrl+C on a relay task: before its first call it is cancelled, as a route task is; from
    the first call on the task stays open and `sr check` continues the chain."""
    task_id = row["task_id"]
    if not log.calls_for(conn, task_id) and row["status"] == "queued":
        try:
            log.set_cancelled(conn, task_id, allowed_from=("queued",))
            out(f"{task_id} cancelled (Ctrl+C).")
            return 130
        except log.StateError:
            row = log.get_task(conn, task_id)
    if stage["task_id"] == task_id and stage["kind"] in log.STAGE_KINDS:
        out(f"Stopped during stage {stage['stage']} ({stage['role']} by {stage['agent']}) (Ctrl+C). "
            "The task stays open; run `sr check` to finish it.")
    elif stage["task_id"] == task_id and stage["kind"] in ("check", "fix", "recheck"):
        out(f"Stopped during the {stage['kind']} by {stage['agent']} (Ctrl+C). The task stays open; "
            "run `sr check` to finish it.")
    elif row["status"] == "sent":
        out(f"Stopped waiting. {task_id} is still running at Grok; `sr check` will collect the result.")
    else:
        out(f"Stopped before the next stage (Ctrl+C). {task_id} stays open; run `sr check` to finish it.")
    return 130


def _mode(row):
    """A task row's mode: `relay` or `route` (rows from before log version 5 read as route)."""
    return row["mode"] if "mode" in row.keys() and row["mode"] else "route"


def _status_text(row):
    return "missing" if row is None else row["status"]


def _agent_text(row):
    return row["agent"] or "-"


def _status_word(row):
    """The status as the owner reads it: `awaiting pick` for a versus task waiting for them (stored as
    `returned`, the owner's D2), else the stored status."""
    if _mode(row) == "split" and row["status"] == "returned":  # brief 11: what the split waits on, in 13 columns
        if row["check_note"] == log.AWAITING_APPROVAL:
            return "approve plan"
        if (row["check_note"] or "").startswith(log.WAITING_PIECES):
            return "waiting"
    return log.AWAITING_PICK if relay.awaiting_pick(row) else row["status"]


def _doer_text(row, calls):
    """The doer and why, for `sr show`. Gate 7 of brief 9: when the substitute of a resume stopped on
    its plan limit too, say so, since the row names the substitute while both calls stopped."""
    by_id = {c["call_id"]: c for c in calls}
    for c in calls:
        old = by_id.get(relay.resume_of(c))
        if (old is not None and c["status"] == "failed" and c["reason_code"] == plan_limit.CODE
                and old["reason_code"] == plan_limit.CODE):
            how = "took over from" if relay.is_takeover(c) else "resume of"  # brief 24 (decision 6)
            return f"{_agent_text(row)} ({how} {old['agent']}; both stopped)"
    return f"{_agent_text(row)} ({row['route_reason'] or '-'})"


def _fail(conn, task_id, error, secrets, out):
    try:
        log.set_failed(conn, task_id, error)
    except log.StateError:
        out(f"{task_id} is already {_status_text(log.get_task(conn, task_id))}.")
    out(f"{task_id} failed: {safety.for_terminal(error, secrets)}")
    _project_entry(conn, task_id, out)  # rules v2.25: the failed line
    return 1


@_releases_its_runs
def cmd_check(*, conn, config, fetch, close, environ=None, settings_paths=(), post=None, worker=None, chatgpt=None,
              codex_login=None, cursor=None, cursor_ready=None, now=None, presets=None, roster=None, claude_ready=None, hindsight=None,
              available=None, chatgpt_ready=None, out=print):
    """Move every open task forward: collect finished Grok calls, mark timeouts, then take each
    task's next steps until it ends or waits on Grok again. Claude steps run here; Grok calls are
    sent and collected on a later run. A relay task's chain continues the same way (`presets` is
    the loaded config/presets.json; None leaves relay tasks where they are). Exit 2 refused,
    1 inbox unreadable, 5 if a task it finished was not passed, else 0."""
    secrets = _secrets(config)
    problems = _refusals(config, environ or {}, settings_paths)
    if problems:
        _refuse_problems(out, problems, config, environ or {}, settings_paths, tail="Nothing was collected or sent.")
        return 2
    deps = SimpleNamespace(config=config, post=post, worker=worker, chatgpt=chatgpt, codex_login=codex_login,
                           codex_ok=None, cursor=cursor, cursor_ready=cursor_ready, cursor_ok=None, fetch=fetch, close=close, sleep=None, clock=None, wait=False, presets=presets,
                           live=roster.live if roster is not None else None, claude_ready=claude_ready,
                           hindsight=hindsight, available=available, chatgpt_ready=chatgpt_ready, roster=roster,
                           now=now)
    _dead_runs(conn, deps, secrets, out)  # brief 22 (decision 4): only `sr check` writes a dead run
    open_ids = log.open_grok_calls(conn)
    late_ids = log.late_grok_calls(conn, now=now, minutes=TIMEOUT_MINUTES)  # brief 24 (decision 7)
    if open_ids or late_ids:
        try:
            issues = fetch()
        except Exception as e:
            receipt.mark(out, code="inbox_unreadable", command=True)
            out(f"Could not read the inbox: {safety.for_terminal(_describe(e), secrets)}")
            out("No tasks were marked timed out.")
            return 1
        for match in inbox.match_results(open_ids, issues):
            call = log.get_call(conn, match["task_id"])
            task = log.get_task(conn, call["task_id"])
            if task["status"] not in ("queued", "sent"):
                out(f"{call['task_id']} is already {task['status']}; skipped issue #{match['number']}.")
                continue
            _collect(conn, match, secrets, out, close)
        for match in inbox.match_results(late_ids, issues):
            if match["result"].strip():
                _store_late(conn, match, secrets, out, close)
    for call_id in log.mark_timeouts(conn, now=now, minutes=TIMEOUT_MINUTES):
        out(f"{call_id} timed out (no result after {TIMEOUT_MINUTES} minutes).")
        timed = log.get_call(conn, call_id)
        if timed is not None and log.get_task(conn, timed["task_id"])["status"] == "timed_out":
            _project_entry(conn, timed["task_id"], out)  # rules v2.25: the stopped line
    worst = 0
    for row in reversed(log.open_tasks(conn)):  # oldest first
        if _runs_elsewhere(conn, row):  # brief 22 (decision 4): another process is running it; never a second writer
            continue
        if _at_the_floor(conn, row):  # a task left at the skill question (no terminal here): it comes back for its label
            _back_for_label(conn, row, out, why="its run ended at the skill question")
            continue
        with runs.held(conn, row["task_id"]) as ok:
            if ok and _run_loop(conn, row["task_id"], deps, secrets, out) == 5:
                worst = 5
    for row in log.waiting_splits(conn):  # rules v2.18 and the owner's D3: report each split's pieces; integrate when in
        if row["check_note"] == log.AWAITING_APPROVAL:
            out(f"#{row['n']} {row['task_id']} is awaiting your approval: sr split --go {row['n']}")
        elif _runs_elsewhere(conn, row):
            continue
        else:
            with runs.held(conn, row["task_id"]) as ok:
                if ok and _split_advance(conn, row, deps, secrets, out) == 5:
                    worst = 5
    still_open = list(reversed(log.open_tasks(conn)))
    for row in still_open:
        if runs.held_elsewhere(row):  # brief 22: its own process is on it
            out(f"#{row['n']} {row['task_id']} is running in another window (pid {row['pid']}).")
            continue
        holder = _held_by(conn, row)  # brief 11.1: a piece waiting for another piece's Grok call
        note = row["check_note"] if (row["check_note"] or "").startswith(log.GROK_NOTES) else None  # brief 21, C2
        out((f"#{row['n']} {row['task_id']} is {split.held_words(holder)}." if holder is not None
             else _open_task_text(row, log.calls_for(conn, row["task_id"]), deps)) + (f" ({note})" if note else ""))
    for row in log.awaiting_pick_tasks(conn):  # brief 9 (D8): sr check sends nothing for these
        out(f"#{row['n']} {row['task_id']} is awaiting your pick: sr pick {row['n']} {_pick_words(row, presets)}")
    out(f"{len(still_open)} task(s) still open.")
    return worst


PROCESS_ENDED_RESULT = "stopped: process ended"  # rules v2.31, Resume: what `sr check` marks a process-ended stop


def _dead_runs(conn, deps, secrets, out):
    """Brief 22 (decision 4; Phase 0 choices 1 and 3): every run whose process is gone (or whose pid now belongs to
    another process). An open task with a note of a call in flight: that call is written as a failed row with reason
    `process_ended` and the records it was sent, and the task `failed` (`state.of` reads `process_ended`, its resume
    offered). An open task at the Jev floor prompt: it comes back for its label. Any other: no call was running, so the
    run is cleared and the task goes on as any open task (a Grok wait keeps waiting). An ended row (a resume or fallback
    in flight) or one waiting with the owner: the run is cleared, nothing else. A run `ps` can't judge is left alone."""
    for row in log.running_tasks(conn):
        if not runs.dead(row):
            continue
        task_id, (pid, started) = row["task_id"], runs.holder(row)
        note = runs.read_note(runs.FOLDER, task_id)
        if note is not None and ((note.get("pid"), note.get("started")) != (pid, started)
                                 or log.get_call(conn, note.get("call_id")) is not None):
            note = None  # another run's note, or its call's row was written: nothing was running
        if row["status"] in ("queued", "sent") and note is not None:
            _process_ended(conn, row, note, pid, deps, secrets, out)
        elif row["status"] in ("queued", "sent") and _at_the_floor(conn, row):
            _back_for_label(conn, row, out, why=f"its run, pid {pid}, ended at the skill question")
        with _hold_interrupts():
            log.clear_run(conn, task_id, pid, started)
        runs.drop_note(runs.FOLDER, task_id)


def _process_ended(conn, row, note, pid, deps, secrets, out):
    """The call that was running when its process ended becomes a failed row (`process_ended`) with what it was sent, and
    the task `failed` at that stage; the project's stopped line; the resume line."""
    task_id, stage = row["task_id"], note.get("stage") if note.get("kind") in log.STAGE_KINDS else None
    text = f"process ended: the sr process (pid {pid}) ended while this call was running"
    with _hold_interrupts():
        log.add_call(conn, note["call_id"], task_id, note["kind"], note["agent"], status="failed", text=text,
                     stage=note.get("stage"), role=note.get("role"), reason_code=state.PROCESS_ENDED,
                     search=note.get("search"), context=note.get("context"), memory=note.get("memory"),
                     resume_of=note.get("resume_of"))
        log.set_failed(conn, task_id, PROCESS_ENDED_RESULT, failed_stage=stage)
    out(f"#{row['n']} {task_id} stopped: process ended (pid {pid}) during {resume.stopped_text(note)} by {note['agent']}.")
    _project_entry(conn, task_id, out)
    line = _plan_limit_line(conn, task_id, deps)
    if line:
        out(line)


def _at_the_floor(conn, row):
    """A routed task left at the Jev floor prompt: queued, no doer, no call, Jev under the floor (or none of these, in
    error, past its cap)."""
    return (row["status"] == "queued" and _mode(row) in ("route", "piece") and not row["agent"]
            and row["jev_status"] in state.FLOOR_STATUSES and not log.calls_for(conn, row["task_id"]))


def _back_for_label(conn, row, out, *, why):
    """Rules v2.28, Jev: when the router can't ask, the task comes back with its label shown (`needs_label`)."""
    with _hold_interrupts():
        try:
            log.set_returned(conn, row["task_id"], "returned: needs your label", reason_code="needs_label")
        except log.StateError:
            return
    out(f"#{row['n']} {row['task_id']} came back to you: needs your label ({why}).")
    _project_entry(conn, row["task_id"], out)


def _runs_elsewhere(conn, row):
    """Brief 22 (decision 4): a task another process runs (alive, or that `ps` can't judge), or a queued piece whose split
    another process is running (it runs its pieces in turn): `sr check` leaves both alone."""
    if runs.held_elsewhere(row):
        return True
    if _mode(row) == "piece" and row["status"] == "queued" and row["parent"]:
        parent = log.get_task(conn, row["parent"])
        return parent is not None and runs.held_elsewhere(parent)
    return False


def _open_task_text(row, calls, deps):
    """One line per open task after `sr check`: what it waits for, or why it is stuck."""
    head = f"#{row['n']} {row['task_id']}"
    if _mode(row) in ("relay", "split"):
        preset, problem = _preset_for(row, deps)
        if preset is None:
            return f"{head} is {row['status']}: {problem}."
        step = relay.next_stage(row, calls, preset)
        if step.action == "wait":
            return f"{head} waits for {_call_text(step.call)}."
        if step.action in ("stage", "reask"):
            return f"{head} is {row['status']} before stage {step.n}; run `sr check` again or cancel it."
        if step.action == "verdict":
            return f"{head} is {row['status']} with its check stage done; run `sr check` again to read the verdict."
    step = checking.next_step(row, calls)
    if step.action == "wait":
        return f"{head} waits for {_call_text(step.call)}."
    return f"{head} is {row['status']} with no call out; run `sr check` again or cancel it."


def _local(iso):
    return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M") if iso else ""


def _one_line(text, width):
    text = " ".join(safety.for_terminal(text).split())
    return text if len(text) <= width else text[: width - 1] + "…"


def cmd_log(*, conn, limit=20, chat=None, project=None, search=None, before=None, as_json=False, live=None,
            loaded=None, out=print):
    """Recent tasks; with `chat` (rules v2.27, `sr log --chat <name>`) only that chat's; with `project`, `search` or
    `before` (rules v2.30, build brief 21) only that project's, those whose text holds the words, those older than the
    task `before` names. `as_json`: the rows as JSON with their state (jsonview.log_view)."""
    older = None
    if before is not None:
        older, missing, code = log.find_task(conn, before)
        if older is None:
            receipt.mark(out, code="unknown_task" if code == "usage" else code)
            out(safety.for_terminal(missing or f"No task {before}."))
            return 1
    rows = log.task_rows(conn, limit, project=project, chat=chat, search=search, before=older)
    if as_json:
        receipt.deliver(out, jsonview.log_view(conn, rows, limit=limit, live=live, loaded=loaded))
        return 0
    if not rows:
        out(f"No tasks in chat {safety.one_line(chat)} yet." if chat else "No tasks in the log yet.")
        return 0
    out(f"{'#':>3}  {'created (local)':<16}  {'task_id':<23}  {'status':<13}  {'agent':<7}  {'skill':<20}  "
        f"{'check':<10}  task  |  result")
    shown = {r["task_id"] for r in rows}
    for r in rows:
        if _mode(r) == "piece" and r["parent"] in shown:
            continue  # printed under its split (rules v2.18)
        out(_log_line(conn, r))
        if _mode(r) == "split":
            for piece in log.pieces_of(conn, r["task_id"]):
                out(_log_line(conn, piece))
    return 0


def _log_line(conn, r):
    """One `sr log` line. A piece is indented under its split with `↳`, in plan order."""
    line = (f"{r['n']:>3}  {_local(r['created_at']):<16}  {r['task_id']:<23}  {_status_word(r):<13}  {_agent_text(r):<7}  "
            f"{_skill_text(r):<20}  {r['check_state'] or '-':<10}  "
            f"{'(resumed) ' if _was_resumed(conn, r) else ''}{'(taken over) ' if _was_taken_over(conn, r) else ''}"
            f"{'(fallback) ' if _fell_back(conn, r) else ''}"
            f"{_one_line(r['task'], 40)}  |  ")
    holder = _held_by(conn, r)
    line += split.held_words(holder) if holder is not None else _one_line(r["result"], 50)
    return f"  ↳ {line}" if _mode(r) == "piece" else line


def _fell_back(conn, row):
    """True when `sr fallback` redid the task (a fallback row whose doer's call came back)."""
    return fallback.active(log.calls_for(conn, row["task_id"])) is not None


def _was_taken_over(conn, row):
    """Brief 24 (decision 6): True when the router took a stopped call of the task over."""
    return takeover.used(log.calls_for(conn, row["task_id"]))


def _was_resumed(conn, row):
    """True when `sr resume` made a call on the task (a `-resume` row; a takeover's row carries resume_of too)."""
    return any(resume.is_resume(c) for c in log.calls_for(conn, row["task_id"]))


def _resume_lines(conn, row, calls, roster, presets):
    """For `sr show`: one line per call `sr resume` made, naming the call it replaced; or, on a
    task a plan limit stopped, the stop line (rules v2.15). A relay task whose preset can't be
    read gets no stop line (the check-stage rule needs the preset)."""
    by_id = {c["call_id"]: c for c in calls}
    lines, resumed = [], False
    for c in calls:
        old = by_id.get(relay.resume_of(c))
        if old is not None and relay.is_takeover(c):  # brief 24 (decision 6): the router's takeover, said as the card
            lines.append(f"Taken over: {availability.name_of(c['agent'])} took over {resume.stopped_text(old)} — "
                         f"replaces call {old['call_id']} ({takeover.why_words(old)}).")
            lines += _late_lines(old)
        elif old is not None:
            why = ("stopped when its process ended" if old["reason_code"] == state.PROCESS_ENDED  # brief 22
                   else "stopped on its plan limit")
            lines.append(f"Resumed: {resume.stopped_text(c)} by {c['agent']} — replaces call {old['call_id']} "
                         f"({old['agent']} {why}).")
            resumed = True
    if resumed:
        return lines
    preset = split.PRESET if _mode(row) == "split" else None
    if _mode(row) == "relay":
        preset = presets_mod.for_task(row, presets)[0]
        if preset is None:
            return []
    line = resume.stop_line(row, calls, live=roster.live if roster is not None else None, preset=preset)
    return lines + ([line] if line else [])


def _late_lines(call):
    """Brief 24 (decision 7): a Grok call taken over at overdue: its late answer, when it came, kept and never used; or
    until when it may still come."""
    if call["agent"] != "grok" or call["reason_code"] not in (takeover.OVERDUE, takeover.LATE):
        return []
    if call["reason_code"] == takeover.LATE:
        where = f" ({call['round_file']})" if call["round_file"] else ""
        return [f"Late answer: Grok Bot's answer came {_local(call['finished_at'])}; kept, not used{where}."]
    until = datetime.fromisoformat(call["sent_at"]) + timedelta(minutes=TIMEOUT_MINUTES)
    if until > datetime.now(timezone.utc):
        return [f"Grok Bot's answer may still come until {_local(until.isoformat())}; it won't be used."]
    return []


def _skill_text(row):
    """The skill column: the skill, or `relay:<preset>` for a relay task (display only; a relay
    task has no skill); on a tagged task the tag beside it, `project:<name>` or `chat:<name>` (rules v2.25, decision
    14; rules v2.27, Memory)."""
    text = _skill_word(row)
    tag = log.tag_of(row)
    return f"{text} {tag}" if tag else text


def _skill_word(row):
    if _mode(row) == "relay":  # rules v2.21 (D4): the filled slots only when one differs from its default
        return f"relay:{row['preset']}" + "".join(f" {k}={v}" for k, v in _changed_slots(row).items())
    if _mode(row) == "split":
        plan = log.split_plan_of(row)
        return f"split · {len(plan['pieces'])} pieces" if plan else "split · plan"
    return row["skill"] or "-"


def _changed_slots(row, loaded=None):
    """{slot: agent} for each slot whose agent differs from its default, read from the row's stored map against
    config/presets.json (D4: nothing is printed when every slot holds its default). {} when either can't be read."""
    if not presets_mod.slots_of(row):
        return {}
    filled = presets_mod.for_task(row, loaded if loaded is not None else _presets_quietly())[0]
    return presets_mod.changed(filled) if filled is not None else {}


def _presets_quietly():
    """The checked presets for display, or None; `sr log` and `sr show` work without them."""
    try:
        return presets_mod.load_presets(load_roster(send_paths=tuple(SENDERS)), tuple(SENDERS), relay.CONTRACTS,
                                        roles=relay.ROLES, verdicts=relay.VERDICTS)
    except (RosterError, presets_mod.PresetsError):
        return None


def _find(conn, words):
    """No words: the newest task. '5' or '#5': task #5. 'sr-...': that task_id, or a unique prefix of one.
    Anything else: the newest task whose text contains the words. Returns (row, message if missing, its code)."""
    text = " ".join(words).strip()
    if not text:
        return log.newest_task(conn), "No tasks in the log yet.", "unknown_task"
    row, missing, code = log.find_task(conn, text)  # a number, an id or a unique prefix of one (brief 21)
    if code != "usage":
        return row, missing, code
    return log.newest_task_containing(conn, text), f"No task contains '{text}'.", "unknown_task"


def _project_line(row):
    """`  project: <name>` or `  chat: <name>` for the first line of `sr show` on a tagged task, else nothing (rules
    v2.25 and v2.27)."""
    name, chat = log.project_of(row), log.chat_of(row)
    return f"  project: {name}" if name else f"  chat: {chat}" if chat else ""


def _build_call(row, calls):
    """The build call of a project task: the call whose result is the task's (a routed do, its re-ask, a resume or
    fallback row; on a relay the last stage's accepted row). None while there is none (jsonview.build_call)."""
    return jsonview.build_call(row, calls)


def _project_lines(conn, row, secrets, handoff=False, memory=False):
    """After the result on a tagged task: on a project task the entry the router wrote (or `none (<status>)`), and
    with `handoff` the handoff as it was sent to the build call (from the call row's context record; the file may
    have changed); on any tagged task the memory write record (rules v2.27: `memory: stored …`, `skipped …`, `none`),
    and with `memory` the block as it was sent to the build call, from the call row's memory record."""
    name, tag = log.project_of(row), log.tag_of(row)
    lines = []
    if not name and handoff:
        lines.append("This is not a project task, so no handoff was sent.")
    if name:
        lines += _handoff_lines(conn, row, secrets, name, handoff)
    if tag:
        lines += _memory_lines(conn, row, secrets, tag, memory)
    elif memory:
        lines.append("This is not a tagged task, so no memory block was sent.")
    return lines


def _memory_lines(conn, row, secrets, tag, memory):
    writes = log.memory_of(row)
    if writes:
        last = writes[-1]
        lines = [f"memory: stored {last['document_id']}, {last['chars']} characters" if "document_id" in last
                 else f"memory: skipped: {safety.for_terminal(last['skipped'], secrets)}"]
    else:
        lines = ["memory: none"]
    if not memory:
        return lines
    call = _build_call(row, log.calls_for(conn, row["task_id"]))
    record = log.call_memory_of(call) if call is not None else None
    if call is None:
        lines.append("Memory block: none yet (the build call has not been made).")
    elif record is None:
        lines.append("Memory block: not kept (a call from before log version 12, or made with no store).")
    elif record.get("unavailable"):
        lines.append(f"Memory block: the store was unavailable at {call['call_id']}; the call ran without it.")
    elif record.get("left_out"):
        lines.append(f"Memory block left out of {call['call_id']} (it could not fit Grok's prompt limit; {record.get('found', 0)} found).")
    elif not record.get("sent"):
        lines.append(f"Memory block: nothing remembered under {tag} when {call['call_id']} was sent.")
    else:
        lines += [f"Memory block as sent to {call['call_id']} ({record['sent']} of {record.get('found', record['sent'])} entries"
                  + (f", reused from {record['from']}" if record.get("from") else "") + "):",
                  safety.for_terminal(record.get("text", ""), secrets)]
    lines += _call_memory_lines(log.calls_for(conn, row["task_id"]))
    return lines


def _call_memory_lines(calls):
    """Rules 2.28 (Memory, the `sr show` bullet): after the block, one line per call on the task from its memory
    record: `<kind> <agent>: sent <n> of <found>`, `left out (<with> > <limit>)` on a Grok call (a record from before
    the numbers says `left out` alone), `unavailable`, `not kept` for a call with no record, and `, from <call_id>`
    when the block was the one an earlier call got. A stage names its number; a re-ask says so."""
    lines = []
    for c in calls:
        kind = c["kind"]
        if kind in log.STAGE_KINDS:
            kind = f"stage {c['stage']}" + (" re-ask" if c["kind"] == "reask" else "")
        record = log.call_memory_of(c)
        if record is None:
            state = "not kept"
        elif record.get("off"):  # brief 27: memory was off for this call
            state = "off"
        elif record.get("unavailable"):
            state = "unavailable"
        elif record.get("left_out"):
            state = "left out"
            if "with" in record and "limit" in record:
                state += f" ({record['with']} > {record['limit']})"
        else:
            state = f"sent {record.get('sent', 0)} of {record.get('found', 0)}"
        if record and record.get("from"):
            state += f", from {record['from']}"
        lines.append(f"{kind} {c['agent']}: {state}")
    return lines


def _handoff_lines(conn, row, secrets, name, handoff):
    lines = []
    writes = log.handoff_of(row)
    folder = projects.folder_of(name)
    where = f"HANDOFF.md in {safety.one_line(str(folder))}" if folder else f"project {name} is no longer registered"
    if writes:
        last = writes[-1]
        lines += [f"Handoff entry ({where}, {last['lines']} lines after the write):",
                  safety.for_terminal(last["text"], secrets)]
        for earlier in writes[:-1]:
            lines += [f"Earlier line ({earlier['lines']} lines after the write):", safety.for_terminal(earlier["text"], secrets)]
    else:
        lines.append(f"Handoff entry: none ({_status_word(row)})")
    if handoff:
        call = _build_call(row, log.calls_for(conn, row["task_id"]))
        record = log.context_of(call) if call is not None else None
        if record is None:
            lines.append("No handoff was sent yet: the build call has not been made.")
        elif record.get("left_out"):
            lines.append(f"Handoff left out of {call['call_id']} (it could not fit Grok's prompt limit; {record['total']} lines).")
        else:
            lines += [f"Handoff as sent to {call['call_id']} ({record['lines']} of {record['total']} lines):",
                      safety.for_terminal(record["text"], secrets)]
    return lines


def cmd_show(*, conn, words, secrets=(), history=False, stages=False, pieces=False, roster=None, presets=None,
             handoff=False, memory=False, as_json=False, config=None, out=print):
    """One task in full. The result shown is the furthest one; with history=True, every call
    the task made instead, the original result and the fix list among them. On a relay task:
    the preset, one line per stage, then the check; stages=True also prints each stage's text
    (rules v2.12: stage results are hidden unless the chain stopped or the owner asks)."""
    row, missing, code = _find(conn, words)
    if row is None:
        receipt.mark(out, code=code)
        out(safety.for_terminal(missing, secrets))
        return 1
    if as_json:  # brief 21, B3: one JSON document, read only
        preview = preview_availability(roster, config) if roster is not None and config is not None else None  # brief 24
        receipt.deliver(out, jsonview.show_view(conn, row, live=roster.live if roster else None, loaded=presets, roster=roster,
                                                available=preview))
        return 0
    if history:
        return _show_history(conn, row, secrets, out)
    if _mode(row) in ("relay", "split"):
        return _show_relay(conn, row, secrets, stages, out, roster=roster, presets=presets, pieces=pieces,
                           handoff=handoff, memory=memory)
    of = ""
    if _mode(row) == "piece":  # brief 11: a piece names its split on the first line
        parent = log.get_task(conn, row["parent"])
        of = f"  piece of task #{parent['n']}" if parent is not None else ""
    out(f"#{row['n']}  {row['task_id']}  {row['status']}  created {_local(row['created_at'])}{of}{_project_line(row)}")
    out(_jev_row_text(row))
    source = f" (chosen by {row['skill_source']})" if row["skill_source"] else ""
    out(f"Skill: {row['skill'] or '-'}{source}")
    for line in _answer_lines(conn, row):  # brief 22 (decision 2): a floor row and the task that answered it
        out(line)
    out(f"Doer: {_doer_text(row, log.calls_for(conn, row['task_id']))}   Checker: {row['checker'] or '-'}   "
        f"Check: {row['check_state'] or '-'}")
    if row["check_note"]:
        out(f"Note: {safety.for_terminal(row['check_note'], secrets)}")
    out("Task:")
    out(safety.for_terminal(row["task"], secrets))
    files_lines = _files_lines(row)
    if files_lines:
        out("Files:")
        for line in files_lines:
            out(line)
    if log.web_of(row):  # rules v2.22
        out("web: on (sent with --web)")
    result, status = row["result"], row["status"]
    holder = _held_by(conn, row)
    if holder is not None:
        out(f"(no result yet: {split.held_words(holder)}; `sr check` sends it once #{holder['n']} is back)")
    elif status in ("queued", "sent"):
        out(f"(no result yet, status {status}; run `sr check` to move it on)")
    elif status == "timed_out":
        out(f"(no result: timed out after {TIMEOUT_MINUTES} minutes)")
    elif status == "cancelled":
        out("(cancelled by you)")
    elif status == "returned":
        why = (row["route_reason"] or "returned: ").removeprefix("returned: ")
        if log.calls_for(conn, row["task_id"]):  # it came back between calls (rules v2.25 and v2.29)
            out(f"(came back to you: {why}. Its earlier calls stay in the log; nothing was delivered.)")
        else:
            out(f"(came back to you: {why}. Nothing was sent to an agent.)")
    elif status == "failed":
        out("Error:")
        out(safety.for_terminal(result, secrets))
    elif not result:
        out("(empty result)")
    else:
        out("Result:")
        _print_done(conn, row, secrets, out)
    url = row["result_url"]
    if isinstance(url, str) and url.startswith("https://"):
        out(f"Issue: {safety.for_terminal(url, secrets)}")
    calls = log.calls_for(conn, row["task_id"])
    for line in _round_lines(calls):  # brief 21, C1: before the project lines and the rescue offers, which stay last
        out(line)
    for line in _project_lines(conn, row, secrets, handoff, memory):  # rules v2.25 and v2.27: the entry, the write record
        out(line)
    for line in _fallback_lines(row, calls, None, secrets):
        out(line)
    for line in _resume_lines(conn, row, calls, roster, presets):
        out(line)
    line = _fallback_line(conn, row["task_id"], SimpleNamespace(presets=presets, live=roster.live if roster else None))
    if line:
        out(line)
    if stages:
        out("This is not a relay task, so it has no stages.")
    if pieces:
        out("This is not a split task, so it has no pieces.")
    return 0


def _answer_lines(conn, row):
    """Brief 22 (decision 2): the link between a Jev floor row and the task the owner sent to answer it."""
    new = log.answering_task(conn, row["task_id"])
    if new is not None:
        return [f"Answered by #{new['n']} {new['task_id']} (your label: {new['skill'] or '-'})."]
    floor = log.answered_task(conn, row["task_id"])
    if floor is not None:
        return [f"Answers #{floor['n']} {floor['task_id']} (Jev was unsure)."]
    return []


def _fallback_lines(row, calls, preset, secrets):
    """For `sr show`: one line per `sr fallback` row, naming the call it replaces (a stopped one says it
    doesn't count), then, when the redo also failed twice, both attempts, original first."""
    by_id = {c["call_id"]: c for c in calls}
    lines = []
    for c in calls:
        old = by_id.get(log.fallback_of(c))
        if old is None:
            continue
        what = resume.stopped_text(c)
        if c["status"] == "failed":
            why = "plan limit" if c["reason_code"] == plan_limit.CODE else "failed"
            lines.append(f"Fallback: {what} by {c['agent']} stopped ({why}) — it doesn't count.")
        else:
            lines.append(f"Fallback: {what} by {c['agent']} — replaces call {old['call_id']} "
                         f"({old['agent']}'s result failed its check twice).")
    if row["status"] == "done" and row["check_state"] == "failed":
        lines += _both_attempts_lines(row, calls, preset, secrets)
    return lines


def _split_plan_lines(conn, row, roster, secrets):
    """`sr show` on a split (brief 11, phase E): the piece count, the Jev line, then the plan: each piece with
    its task number and state (or `(no task yet)` before the approval) and where it goes, the text that runs,
    the owner's edit beside the planner's text, and the joining line."""
    plan = log.split_plan_of(row)
    lines = [f"Split: {len(plan['pieces'])} pieces" if plan else "Split: (no plan stored)",
             "Jev: not asked (split task; Jev labels each piece)"]
    if plan is None:
        return lines
    rows = {r["task_id"]: r for r in log.pieces_of(conn, row["task_id"])}
    lines.append("Plan:")
    for k, piece in enumerate(plan["pieces"], 1):
        text = safety.for_terminal(split.text_of(piece), secrets)
        r = rows.get(piece["id"])
        if r is None:
            where = _piece_route(piece["label"], roster, piece.get("choice")) if piece["label"] and roster else "-"
            lines.append(f"  {k}. (no task yet) → {where}: {text}")
        else:
            state, words = ("skipped", None) if piece["skipped"] else split.piece_state(r)
            holder = _held_by(conn, r) if state == "waiting" else None
            if holder is not None:
                state = split.held_words(holder)
            else:
                state = f"{state} ({words})" if state == "waiting" else (f"{state}: {words}" if words else state)
            check = r["checker"] or ("no check" if r["check_state"] == "not_needed" else "-")
            lines.append(f"  {k}. #{r['n']} {state} · {r['skill'] or '-'} · {r['agent'] or '-'} / {check}: {text}")
        if piece.get("edited_text") is not None:
            lines.append(f"     (edited; the planner wrote: {safety.for_terminal(piece['planner_text'], secrets)})")
    lines.append(f"Join: {safety.for_terminal(plan['join'], secrets)}")
    return lines


def _split_pieces_lines(conn, row, secrets):
    """`sr show <n> --pieces`: each piece's result, in plan order."""
    plan = log.split_plan_of(row)
    if plan is None:
        return ["(no plan stored, so no pieces)"]
    rows, lines = {r["task_id"]: r for r in log.pieces_of(conn, row["task_id"])}, ["Piece results:"]
    for k, piece in enumerate(plan["pieces"], 1):
        r = rows.get(piece["id"])
        if r is None:
            lines.append(f"Piece {k} · (no task yet)")
            continue
        state = "skipped" if piece["skipped"] else (r["check_state"] or r["status"])
        lines.append(f"Piece {k} · #{r['n']} · {r['agent'] or '-'} · {state}:")
        lines.append(safety.for_terminal(r["result"], secrets) if r["result"] else "(no result)")
    return lines


def _split_waiting_text(conn, row):
    """What a split waiting with the owner waits on, for `sr show`."""
    n = row["n"]
    if row["check_note"] == log.AWAITING_APPROVAL:
        return f"(waiting for your approval: sr split --go {n})"
    plan = log.split_plan_of(row) or {"pieces": []}
    rows = {r["task_id"]: r for r in log.pieces_of(conn, row["task_id"])}
    done = sum(1 for p in plan["pieces"] if not p["skipped"] and p["id"] in rows
               and split.piece_state(rows[p["id"]])[0] == "done")
    return (f"(waiting for its pieces: {done} of {len(plan['pieces'])} done; `sr check` or `sr split --go {n}` "
            "moves it on)")


def _show_relay(conn, row, secrets, stages, out, *, roster=None, presets=None, pieces=False, handoff=False, memory=False):
    """`sr show` on a relay task: the preset, the stage lines, the checker and check, the task,
    the stage results when asked for or when the chain stopped, then the result or the failure.
    On a split task (brief 11): the plan with each piece's task number and status, and the joining
    line, in place of the preset; `pieces` prints each piece's result."""
    calls = log.calls_for(conn, row["task_id"])
    is_split = _mode(row) == "split"
    out(f"#{row['n']}  {row['task_id']}  {_status_word(row)}  created {_local(row['created_at'])}{_project_line(row)}")
    if is_split:
        for line in _split_plan_lines(conn, row, roster, secrets):
            out(line)
    else:
        out(f"Relay: {row['preset']}")
        changed = _changed_slots(row, presets)
        if changed:  # D4: only when a slot differs from its default
            out("Slots: " + ", ".join(f"{k} {v}" for k, v in changed.items()) + " (the rest are the defaults)")
        out("Jev: not asked (relay task)")
    out("Stages:")
    lines = relay.stage_lines(row, calls)
    for line in lines or ["(none yet)"]:
        out(f"  {line}")
    n = relay.checked_by_stage(row)
    if n is not None:  # rules v2.13: the check was the chain's own stage n
        out(f"check: by stage {n} ({row['checker']}): {row['check_state']}")
    else:
        out(f"Checker: {row['checker'] or '-'}   Check: {row['check_state'] or '-'}")
        if row["check_note"]:
            out(f"Note: {safety.for_terminal(row['check_note'], secrets)}")
    out("Task:")
    out(safety.for_terminal(row["task"], secrets))
    if stages:
        out("Stage results:")
        described = relay.describe_calls(calls)
        stage_calls = [c for c in calls if c["kind"] in log.STAGE_KINDS]
        for (head, text), call in zip(described, stage_calls):
            out(head)
            record = log.search_of(call)
            if record is not None:
                out(_search_text(record))
            if text:
                out(safety.for_terminal(text, secrets))
        if not described:
            out("(none yet)")
    if is_split and pieces:
        for line in _split_pieces_lines(conn, row, secrets):
            out(line)
    elif pieces:
        out("This is not a split task, so it has no pieces.")
    vote_preset = presets_mod.for_task(row, presets)[0] if not is_split else None
    if vote_preset is not None and vote_preset.tallies and (
            relay.awaiting_pick(row) or relay.picked(row) is not None
            or relay.CHECKED_BY_VOTE.fullmatch(row["check_note"] or "")):  # rules v2.24, decision 11
        for line in _round_lines(calls) + [""] + _vote_lines(row, calls, vote_preset, secrets):
            out(line)
        return 0
    if not is_split and (relay.awaiting_pick(row) or relay.picked(row) is not None):  # rules v2.16: the pick
        preset = presets_mod.for_task(row, presets)[0]
        for line in _round_lines(calls):  # brief 21, C1: before the block, whose pick line stays last
            out(line)
        if preset is None:
            out(f"(the preset {row['preset']} can't be read, so the candidates can't be paired with their reviews; "
                f"`sr show {row['n']} --stages` prints every stage)")
        else:
            out("")  # The owner: a blank line between the task text and the block
            for line in _versus_lines(row, calls, preset, secrets):
                out(line)
        return 0
    result, status = row["result"], row["status"]
    if status in ("queued", "sent"):
        out(f"(no result yet, status {status}; run `sr check` to move it on)")
    elif status == "timed_out":
        out(f"(no result: timed out after {TIMEOUT_MINUTES} minutes)")
    elif status == "cancelled":
        out("(cancelled by you)")
    elif status == "returned" and is_split:
        out(_split_waiting_text(conn, row))
    elif status == "failed" and is_split and (result or "").startswith("no split: "):
        for line in _no_split_lines(row, result.removeprefix("no split: ")):
            out(line)
    elif status == "failed":
        shown = safety.for_terminal(result, secrets)
        prefix = "split failed" if is_split else "relay failed"
        out(prefix.upper() + shown[len(prefix):] if shown.startswith(prefix) else f"Error:\n{shown}")
        if not stages:
            _print_stages(conn, row["task_id"], secrets, out)
    elif not result:
        out("(empty result)")
    else:
        out("Result:")
        _print_done(conn, row, secrets, out)
    for line in _round_lines(calls):  # brief 21, C1: before the project lines and the rescue offers, which stay last
        out(line)
    for line in _project_lines(conn, row, secrets, handoff, memory):  # rules v2.25 and v2.27: the entry, the write record
        out(line)
    preset = split.PRESET if is_split else presets_mod.for_task(row, presets)[0]
    for line in _fallback_lines(row, calls, preset, secrets):
        out(line)
    for line in _resume_lines(conn, row, calls, roster, presets):
        out(line)
    line = _fallback_line(conn, row["task_id"], SimpleNamespace(presets=presets, live=roster.live if roster else None))
    if line:
        out(line)
    return 0


def _search_text(record):
    """One line for a call's search record (build brief 8): its state and how many queries Claude ran;
    more than search.MAX_SEARCHES is said, never refused."""
    if record.get("state") != search.ALLOWED:
        return f"search: {record.get('state')}"
    count = record.get("count")
    if count is None:
        return "search: allowed \u2014 queries not reported"
    more = f" (more than {search.MAX_SEARCHES})" if count > search.MAX_SEARCHES else ""
    return f"search: allowed \u2014 {count} {'query' if count == 1 else 'queries'}{more}"


def _round_text(call):
    """Where a call's round file is, or why there is none (rules v2.30, Round outputs)."""
    if call["round_file"]:
        return call["round_file"]
    if call["status"] == "sent":
        return "not back yet"
    return "no output" if call["text"] is None else "not kept"


def _round_lines(calls):
    """`sr show`: each call's round file in order; one line when none was kept (a task from before log version 14)."""
    if not calls:
        return []
    found = [_round_text(c) for c in calls]
    if all(f == "not kept" for f in found):
        return ["Round files: not kept"]
    return ["Round files:"] + [f"  {k:02d} {_history_kind(c)} by {c['agent']}: {f}"
                               for k, (c, f) in enumerate(zip(calls, found), 1)]


def _history_kind(call):
    if call["kind"] in log.STAGE_KINDS:
        return f"stage {call['stage']} re-ask" if call["kind"] == "reask" else f"stage {call['stage']} {call['role']}"
    if call["kind"] == "do" and context.DO_REASK in call["call_id"]:  # rules v2.25: the doer's one contract re-ask
        return "do re-ask"
    return call["kind"]


def _show_history(conn, row, secrets, out):
    """Every call a finished task made, oldest first: kind, agent, status, time, verdict, text."""
    out(f"#{row['n']}  {row['task_id']}  {row['status']}  Check: {row['check_state'] or '-'}")
    if row["status"] in ("queued", "sent"):
        out("This task is still open; run `sr check` to move it on. Its history shows once it has ended.")
        return 1
    calls = log.calls_for(conn, row["task_id"])
    if not calls:
        out("This task has no call history: it is from before the calls table (2026-10-13).")
        return 0
    for n, call in enumerate(calls, 1):
        when = _local(call["sent_at"])
        if call["finished_at"] and call["finished_at"] != call["sent_at"]:
            when += f" -> {_local(call['finished_at'])}"
        head = f"{n}. {_history_kind(call)} by {call['agent']}: {call['status']}"
        if call["verdict"]:
            head += f" {call['verdict']}"
        if call["reason_code"] == plan_limit.CODE:
            head += ", plan limit"
        if relay.resume_of(call):
            how = "took over" if relay.is_takeover(call) else "resumed"  # brief 24 (decision 6)
            head += f", {how} \u2014 replaces call {call['resume_of']}"
        if log.fallback_of(call):
            head += f", fallback \u2014 replaces call {call['fallback_of']}"
        served = relay.served_text(log.served_of(call))  # rules v2.28: a Cursor call names the model that answered
        if served:
            head += f", {served}"
        head += f", {when}"
        if call["url"]:
            head += f" ({safety.for_terminal(call['url'], secrets)})"
        out(head)
        record = log.search_of(call)
        if record is not None:
            out(f"  {_search_text(record)}")
            for query in record.get("queries") or []:
                out(f"    {safety.for_terminal(query, secrets)}")
        if call["text"]:
            out(safety.for_terminal(call["text"], secrets))
    return 0


def _jev_row_text(row):
    status = row["jev_status"]
    if status == "not_asked":
        return "Jev: not asked (relay task)"
    if status == "over_cap":
        return "Jev: not asked (this month's token cap was reached)"
    # brief 11 (D2): a piece's Jev tokens are counted on its split's row, labeled at plan time
    tokens = "tokens counted on its split" if _mode(row) == "piece" else f"{row['jev_tokens']} tokens"
    if status == "error":
        return f"Jev: error {row['jev_error'] or '-'} ({tokens})"
    return f"Jev: {row['jev_label']}, confidence {_confidence(row['jev_confidence'])} ({status}, {tokens})"


def _summary(row):
    return f"#{row['n']} {row['task_id']} {_agent_text(row)} {row['status']}: {_one_line(row['task'], 60)}"


CANCEL_WAIT_SECONDS = 10  # brief 22 (decision 5): how long `sr cancel` waits to see a signalled run stop
CANCEL_POLL_SECONDS = 0.25


def cmd_cancel(*, conn, words, kill=None, sleep=None, clock=None, out=print):
    """Cancel a queued or sent task. Stored as the status 'cancelled'. Build brief 22 (decision 5): when another
    process's run is on the task and that run is alive (its pid and its start time both match), the task is marked
    cancelled first and the run gets SIGINT, the path Ctrl+C takes; `kill`, `sleep` and `clock` are injected (main
    passes the real ones). A pid whose start time doesn't match, or one `ps` can't judge, is never signalled."""
    text = " ".join(words).strip()
    if not text:
        open_rows = log.open_tasks(conn)
        if not open_rows:
            receipt.mark(out, code="wrong_state")
            out("Nothing to cancel: no task is queued or sent.")
            return 1
        if len(open_rows) > 1:
            receipt.mark(out, code="ambiguous_task")
            out("More than one task is open. Say which one, for example `sr cancel 5`:")
            for r in open_rows:
                out(f"  {_summary(r)}")
            return 1
        row = open_rows[0]
    else:
        row, missing, code = log.find_task(conn, text)  # a number, an id or a unique prefix of one (brief 21)
        if code == "usage":
            receipt.mark(out, code="usage")
            out("Give a task number from `sr log` (for example `sr cancel 5`) or a task_id.")
            return 1
        if row is None:
            receipt.mark(out, code=code)
            out(safety.for_terminal(missing))
            return 1
    receipt.mark(out, task_id=row["task_id"])
    if _mode(row) == "split" and row["status"] == "returned":  # The owner, before phase F: a waiting split can end
        return _cancel_split(conn, row, out)  # never signalled: its pieces are untouched
    if row["status"] == "returned" and row["reason_code"] == "needs_label" and not row["answered_by"]:
        try:  # brief 22 (decision 2): a Jev floor question nobody will answer
            log.cancel_floor_row(conn, row["task_id"])
        except log.StateError:
            receipt.mark(out, code="state_changed")
            out(f"It just changed to {_status_text(log.get_task(conn, row['task_id']))}; nothing to cancel.")
            return 1
        out(f"Cancelled {_summary(row)}")
        out("Its Jev floor question is closed; Jev's label stays on the row.")
        return 0
    run = runs.holder(row)
    live = runs.alive(*run) if run is not None and run != runs.me() else False
    if row["status"] not in ("queued", "sent"):
        if live is True:  # brief 22: a resume or fallback in flight on an ended row: its own Ctrl+C, the row left alone
            stopped = _signal_run(conn, row, run, kill, sleep, clock)
            out(f"Sent Ctrl+C to the run on #{row['n']} (pid {run[0]}); {_stopped_words(stopped)}. "
                f"#{row['n']} is as it was ({row['status']}).")
            return 0
        receipt.mark(out, code="wrong_state")
        out(_summary(row))
        out(f"It is already {row['status']}; nothing to cancel.")
        return 1
    try:
        log.set_cancelled(conn, row["task_id"])
    except log.StateError:
        receipt.mark(out, code="state_changed")
        now = log.get_task(conn, row["task_id"])
        out(_summary(now))
        out(f"It just changed to {now['status']}; nothing to cancel.")
        return 1
    out(f"Cancelled {_summary(row)}")
    out("Logged as cancelled.")
    grok_out = any(c["agent"] == "grok" and c["status"] == "sent" for c in log.calls_for(conn, row["task_id"]))
    if live is True:  # brief 22 (decision 5): its run gets Ctrl+C; it stops without writing the call
        stopped = _signal_run(conn, row, run, kill, sleep, clock)
        out(f"Sent Ctrl+C to its run (pid {run[0]}); {_stopped_words(stopped)}.")
    elif live is None:
        out(f"Couldn't tell whether its run (pid {run[0]}) is still going, so it was not signalled; if it is, that "
            "window will say its answer was not saved.")
    elif run is not None and run != runs.me():  # a run that ended (or whose pid is another process now): cleared
        log.clear_run(conn, row["task_id"], *run)
    if live is not True:
        if grok_out or row["agent"] == "grok":
            out("Only the log changed: Grok may still run it, and its issue will stay open.")
        elif live is not None:
            out("If it is still running in another window, that window will say its answer was not saved.")
    return 0


def _signal_run(conn, row, run, kill, sleep, clock):
    """SIGINT to a run whose pid and start time were just seen to match, re-checked right before the signal; then wait up
    to CANCEL_WAIT_SECONDS for it to end (its process gone, or its row let go). True when it stopped, False when not yet,
    None when it was not signalled after all (it ended, or its pid changed hands, in between)."""
    if runs.alive(*run) is not True:
        return None
    (kill or os.kill)(run[0], signal.SIGINT)
    sleep, clock = sleep or time.sleep, clock or time.monotonic
    deadline = clock() + CANCEL_WAIT_SECONDS
    while True:
        now = log.get_task(conn, row["task_id"])
        if runs.alive(*run) is False or now is None or runs.holder(now) != run:
            return True
        if clock() >= deadline:
            return False
        sleep(CANCEL_POLL_SECONDS)


def _stopped_words(stopped):
    if stopped is True:
        return "it stopped"
    if stopped is False:
        return f"it hasn't stopped after {CANCEL_WAIT_SECONDS} s (it stops at its next step)"
    return "it had already ended"


def _cancel_split(conn, row, out):
    """`sr cancel` on a split waiting with the owner (its plan, or its pieces): the split only. Its piece rows are
    untouched (an open piece goes on, and `sr check` still finishes it); its plan is kept; it never integrates."""
    try:
        log.cancel_waiting_split(conn, row["task_id"])
    except log.StateError:
        receipt.mark(out, code="wrong_state")
        now = log.get_task(conn, row["task_id"])
        out(_summary(now))
        out(f"It is {_status_word(now)}; nothing to cancel.")
        return 1
    pieces = log.pieces_of(conn, row["task_id"])
    out(f"Cancelled {_summary(row)}")
    tail = (" (" + ", ".join(f"#{p['n']} {p['status']}" for p in pieces) + ")") if pieces else ""
    out(f"Cancelled the split only; its pieces are untouched{tail}. The plan is kept: sr show {row['n']}.")
    return 0


def cmd_migrate(*, db_path, backups_dir, now=None, out=print):
    """One time: move a version 1 log into backups/ and start an empty version 2 log."""
    try:
        done = log.migrate(db_path, backups_dir, now=now)
    except log.MigrateRefused as e:
        out(f"Refused: {e} Nothing was changed.")
        return 2
    except log.MigrateFailed as e:
        out(f"Stopped: {e}")
        return 1
    backup = done["backup"]
    shown = backup.relative_to(db_path.parent) if backup.is_relative_to(db_path.parent) else backup
    if done["job"] == "move":
        out(f"Old log: {db_path.name}, version 1, {done['rows']} rows, integrity ok, no open tasks.")
        out(f"Moved to {shown} (owner-only).")
        out(f"SHA-256 before and after the move: {done['sha256']}. Rows after the move: {done['rows']}.")
        out(f"New log: {db_path.name}, version {log.VERSION}, 0 rows. Task numbers start again at #1.")
        return 0
    out(f"Log: {db_path.name}, version {done['from']}, {done['rows']} rows (highest #{done['highest']}), integrity ok, no open tasks.")
    # Build brief 22 (decision 6): the copy is made with SQLite's backup API, so it is checked by its content, not its bytes
    checked = done["backup_check"]
    out(f"Backup copy: {shown} (owner-only), made with SQLite's backup API: integrity {checked['integrity']}, version "
        f"{checked['version']}, {checked['rows']} rows, {checked['calls']} calls, content the same as the log's. "
        f"SHA-256 of the log before: {done['sha256']}.")
    out(f"Upgraded in place: {done['added']}, now version {log.VERSION}.")
    out(f"Journal mode: {done['journal_mode']} (a JSON read and a running task can use the log at once).")
    out(f"Checked after: {done['rows']} rows, {done['calls']} calls, highest #{done['highest']}, every version {done['from']} "
        f"column unchanged (content hash {done['content_hash'][:16]}…).")
    return 0


PROJECT_USAGE = ("sr project add|list|remove|new (add <name> <path>; remove <name>; "
                 "new <name> [--dry-run] [-- '<notes>'])")
PROJECT_FLAGS = ("--json", "--dry-run")


def _take_project_notes(argv):
    """Brief 26 (decisions 1 and 9): for `sr project`, (argv for argparse, the notes or None, a usage problem or None).
    The one argument after the first bare `--` is the notes, taken off before argparse, so `-h` or `--skill coding` in
    them is text; `--json` and `--dry-run` before it move to just after `project`, so `new --json <name>` parses (the
    words are one positional). Any other command comes back unchanged."""
    argv = list(argv)
    if not argv or argv[0] != "project":
        return argv, None, None
    head, tail = (argv[:argv.index("--")], argv[argv.index("--") + 1:]) if "--" in argv else (argv, None)
    head = [head[0], *(t for t in head[1:] if t in PROJECT_FLAGS), *(t for t in head[1:] if t not in PROJECT_FLAGS)]
    if tail is None:
        return head, None, None
    if not tail:
        return head, None, "nothing follows --: the notes go after it, in quotes (sr project new <name> -- '<notes>')"
    if len(tail) > 1:
        return head, None, ("the notes after -- are one argument: put them in quotes "
                            "(sr project new <name> -- '<notes>')")
    return head, tail[0], None


def _handoff_words(created, marked):
    return ("HANDOFF.md created with an empty block" if created
            else "HANDOFF.md given the router's block at its end" if marked else "HANDOFF.md kept as it is")


def _dry_run_words(plan):
    """The dry run's prose (brief 26, decision 6): what `new` would do, or why it would refuse."""
    if plan.would == "refused":
        return f"Would refuse: {safety.one_line(plan.why)}. Nothing was changed."
    folder = safety.one_line(projects.tilde(plan.folder))
    if plan.would == "register":
        state = plan.handoff
        what = ("HANDOFF.md created with an empty block" if not state["exists"]
                else f"HANDOFF.md ({state['lines']} lines) kept as it is" if state["has_block"]
                else f"HANDOFF.md ({state['lines']} lines) given the router's block at its end")
        return f"Would register {folder} as it is: {what}. Nothing was changed."
    root = "" if plan.root.exists() else f"; the projects root {safety.one_line(projects.tilde(plan.root))} is made too"
    return f"Would create {folder} and its HANDOFF.md, and register {plan.name}{root}. Nothing was changed."


def _project_new(name, notes, *, dry_run, secrets, out):
    """`sr project new <name> [--dry-run] [-- <notes>]` (brief 26). The dry run answers with its document and exit 0,
    a refusal included; `new` answers 0 with `project` on the envelope, 2 refused (bad_name or project_refused, nothing
    changed) or 1 when a write failed after the folder was made (project_partial, what exists named)."""
    if dry_run:
        plan = projects.plan_new(name, secrets=secrets)
        words = _dry_run_words(plan)
        receipt.deliver(out, {"api_version": jsonview.API_VERSION, "would": plan.would, "name": plan.name,
                              "folder": projects.tilde(plan.folder) if plan.folder is not None else None,
                              "handoff": plan.handoff, "reason_code": plan.code, "message": words})
        out(words)
        return 0
    try:
        made = projects.new(name, notes or None, secrets=secrets)
    except projects.Partial as e:
        receipt.mark(out, code=e.code)
        out(f"Stopped: {safety.one_line(e)}.")
        return 1
    except projects.ProjectError as e:
        receipt.mark(out, code=e.code)
        out(f"Refused: {safety.one_line(e)}. Nothing was changed.")
        return 2
    folder = projects.tilde(made.folder)
    if made.did == "created":
        what = "HANDOFF.md made: your notes, then the router's block" if notes else "HANDOFF.md made with an empty block"
        out(f"Created {name} at {safety.one_line(folder)}. {what} ({made.lines} lines).")
    else:
        out(f"Added {name} at {safety.one_line(folder)}. {_handoff_words(made.created, made.marked)} ({made.lines} lines).")
    receipt.attach(out, project={"name": name, "folder": folder, "handoff_lines": made.lines, "did": made.did})
    text = projects.read_handoff(made.folder)
    warning = projects.size_warning(made.lines, projects.block_start(text))
    if warning:
        out(warning)
    return 0


def cmd_project(words, *, conn, as_json=False, out=print, notes=None, dry_run=False, secrets=()):
    """`sr project add|list|remove|new` (rules v2.25, Project context; build brief 18, decision 1; brief 26). Only the
    owner runs these. `add` registers a folder that exists, never one in never_register, and gives its HANDOFF.md the
    router's block; `list` prints each project with its path, line count and open task; `remove` drops the entry and
    touches no file; `new` (brief 26) makes `<projects_root>/<name>`, its HANDOFF.md (the `notes` above the block) and the
    entry, or registers the folder there, and `--dry-run` says which without writing. Exit 0, or 2 refused with the reason
    and nothing changed (1 for `new` stopped part way). `as_json` (brief 21): `list` gives the page its document
    (`sr project list --json`)."""
    words = list(words)
    verb = words[0] if words else None
    if verb == "new" and len(words) == 2 and not (dry_run and notes is not None):
        return _project_new(words[1], notes, dry_run=dry_run, secrets=secrets, out=out)
    if dry_run or notes is not None:
        receipt.mark(out, code="usage")
        out(f"Refused: {PROJECT_USAGE}; --dry-run takes the name alone. Nothing was changed.")
        return 2
    if verb == "add" and len(words) == 3:
        name, folder = words[1], words[2]
        try:
            done = projects.add(name, folder)
        except projects.ProjectError as e:
            receipt.mark(out, code="project_refused")
            out(f"Refused: {safety.one_line(e)}. Nothing was changed.")
            return 2
        what = _handoff_words(done.created, done.marked)
        out(f"Registered {name} at {safety.one_line(str(done.path))}. {what} ({done.lines} lines).")
        warning = projects.size_warning(done.lines, done.block_start)
        if warning:
            out(warning)
        return 0
    if verb == "list" and len(words) == 1:
        try:
            registry = projects.read_registry()
        except projects.ProjectError as e:
            receipt.mark(out, code="project_refused")
            out(f"Refused: {safety.one_line(e)}. Nothing was changed.")
            return 2
        open_rows = {name: log.open_task_for(conn, name) for name in registry}
        if as_json:
            receipt.deliver(out, {"api_version": jsonview.API_VERSION, "projects": _projects_json(registry, open_rows)})
            return 0
        for line in projects.listing(registry, open_rows):
            out(line)
        return 0
    if verb == "remove" and len(words) == 2:
        try:
            projects.remove(words[1])
        except projects.ProjectError as e:
            receipt.mark(out, code="project_unknown")
            out(f"Refused: {safety.one_line(e)}. Nothing was changed.")
            return 2
        out(f"Removed {words[1]} from the registry. Its HANDOFF.md is untouched.")
        return 0
    receipt.mark(out, code="usage")
    out(f"Refused: {PROJECT_USAGE}. Nothing was changed.")
    return 2


def _projects_json(registry, open_rows):
    """`sr project list --json` (brief 21): each registered project, its folder, its HANDOFF.md's line count (null when
    it can't be read) and its open task, if any. From the registry and the log; nothing written."""
    found = []
    for name in sorted(registry):
        folder = Path(registry[name])
        try:
            lines = projects.line_count(projects.read_handoff(folder))
        except projects.ProjectError:
            lines = None
        row = open_rows.get(name)
        found.append({"name": name, "path": str(folder), "handoff_lines": lines,
                      "open_task": {"task_id": row["task_id"], "n": row["n"], "status": row["status"]} if row else None})
    return found


CHAT_USAGE = "sr chat list"


def cmd_chat(words, *, conn, as_json=False, out=print):
    """`sr chat list` (rules v2.27, Memory, "The tag"): every chat name in the log with its task count and the date of
    its newest task, newest first. From the log alone; no store call, nothing created. Exit 0, or 2 refused.
    `as_json` (brief 21): the page's document (`sr chat list --json`)."""
    if list(words) != ["list"]:
        receipt.mark(out, code="usage")
        out(f"Refused: {CHAT_USAGE}. Nothing was changed.")
        return 2
    rows = log.chats(conn)
    if as_json:
        receipt.deliver(out, {"api_version": jsonview.API_VERSION,
                              "chats": [{"name": r["chat"], "tasks": r["count"], "newest": r["newest"]} for r in rows]})
        return 0
    if not rows:
        out('No chats yet. sr route "task" --chat <name> starts one.')
        return 0
    out("Chats (from the log):")
    for r in rows:
        out(f"  {r['chat']}  {r['count']} task{'' if r['count'] == 1 else 's'}  newest {_local(r['newest'])}")
    return 0


def cmd_memory(words, *, request, environ, home, popen, sleep, clock, kill, db_path=None, secrets=(), ask=None, out=print):
    """`sr memory start|stop|status|rebuild` (rules v2.27, Memory; build brief 19, phases A and D): Hindsight as a
    process the owner starts and stops, and the bank reloaded from the log. `request` is the HTTP function (main passes
    requests.request), `popen`, `sleep`, `clock` and `kill` the process tools (main passes the real ones); tests pass
    fakes, so nothing here ever starts for real. `rebuild` opens the log at `db_path`, asks y/N through `ask` (None
    means no terminal: refused), clears the bank and retains every storable tagged task, oldest first (decision 13).
    Exit 0, 1 when the server did not do what was asked, 2 refused with nothing changed."""
    words = list(words)
    verb = words[0] if len(words) == 1 else None
    if verb not in ("start", "stop", "status", "rebuild", "on", "off"):
        receipt.mark(out, code="usage")
        out(f"Refused: {memory_server.USAGE}. Nothing was changed.")
        return 2
    if verb in ("start", "rebuild") and settings.memory_mode() == "off":  # brief 27 (decision 8)
        receipt.mark(out, code="memory_off")
        out("Refused: memory is off; sr memory on turns it on. Nothing was changed.")
        return 2
    client = memory.client(request)
    if verb in ("on", "off"):
        return _memory_switch(verb, client, environ=environ, home=home, popen=popen, sleep=sleep, clock=clock, kill=kill,
                              db_path=db_path, secrets=secrets, out=out)
    if verb == "rebuild":
        return _memory_rebuild(client, db_path=db_path, secrets=secrets, ask=ask, out=out)
    if verb == "status" and settings.memory_mode() == "off":  # brief 27: status says so first, then the store's lines
        out("memory: off (sr memory on turns it on)")
    try:
        if verb == "start":  # brief 22 (decision 8): one start at a time by the lock; then what the bank is missing
            folder = Path(db_path).parent / runs.FOLDER_NAME if db_path is not None else None
            with locks.held("memory", folder=folder):
                code = memory_server.start(client, environ=environ, home=home, popen=popen, sleep=sleep, clock=clock,
                                           out=out)
            if code == 0:
                _memory_backfill(client, db_path=db_path, secrets=secrets, out=out)
            return code
        if verb == "stop":
            return memory_server.stop(client, home=home, kill=kill, sleep=sleep, clock=clock, out=out)
        return memory_server.status(client, home=home, out=out)
    except memory_server.ServerError as e:
        receipt.mark(out, code="setup")
        out(f"Refused: {e}. Nothing was changed.")
        return 2
    except memory.Unavailable as e:
        out(f"memory: Hindsight answered /health but then failed: {e}. See sr memory status.")
        return 1


def _memory_switch(verb, client, *, environ, home, popen, sleep, clock, kill, db_path, secrets, out):
    """`sr memory on|off` (brief 27, decisions 2 to 5): the setting first, in this Mac's local settings file; then `on`
    runs exactly `sr memory start`'s path (the start under the memory lock, then the backfill) and `off` stops the store
    `sr memory start` started, under the same lock (a store started another way is left running and said). Exit 0 once
    the setting is as asked, whatever the start or stop did; 2 refused, nothing written. The JSON adds `memory`."""
    to = "auto" if verb == "on" else "off"
    try:
        was, _ = settings.set_memory(to)
    except settings.SettingsError as e:
        receipt.mark(out, code="setup")
        out(f"Refused: {e}. Nothing was changed.")
        return 2
    word = lambda mode: "on" if mode == "auto" else "off"  # noqa: E731
    out(f"memory: {verb} (it was {'already ' + verb if was == to else word(was)})")
    installed = memory_server.paths(home)["binary"].exists()
    folder = Path(db_path).parent / runs.FOLDER_NAME if db_path is not None else None
    try:
        if verb == "on" and not installed:
            out("memory: Hindsight is not installed, so chat and project tasks run without memory until it is; "
                "the one-time install is on the Setup sheet (sr serve, then Setup, Memory).")
        elif verb == "on":
            with locks.held("memory", folder=folder):
                code = memory_server.start(client, environ=environ, home=home, popen=popen, sleep=sleep, clock=clock,
                                           out=out)
            if code == 0:
                _memory_backfill(client, db_path=db_path, secrets=secrets, out=out)
        else:
            with locks.held("memory", folder=folder):
                if memory_server.read_pid(home) is None and client.online():
                    out(f"memory: online at {client.url}, but not started by sr memory start; it is left running and "
                        "not used while memory is off.")
                else:
                    memory_server.stop(client, home=home, kill=kill, sleep=sleep, clock=clock, out=out)
    except memory_server.ServerError as e:  # the setting is as asked; the start or stop said why it didn't happen
        out(f"memory: {e}")
    except memory.Unavailable as e:
        out(f"memory: Hindsight answered /health but then failed: {e}. See sr memory status.")
    try:
        online = bool(client.online())
    except Exception:
        online = False
    receipt.attach(out, memory={"setting": to, "was": was, "online": online, "installed": installed})
    return 0


def _memory_backfill(client, *, db_path, secrets, out):
    """Brief 22 (decision 8): after `sr memory start`, every delivered tagged task the bank is missing; no log, nothing."""
    if db_path is None or not Path(db_path).exists():
        return
    try:
        conn = log.init_db(db_path)
    except log.VersionError as e:
        out(f"memory: backfill skipped: {e}")
        return
    try:
        memory.backfill(conn, client, secrets, out)
    finally:
        conn.close()


def _memory_rebuild(client, *, db_path, secrets, ask, out):
    """Decision 13: y/N (it clears the bank), the store online, then the log into the bank, oldest first."""
    if ask is None:
        out("Refused: sr memory rebuild asks y/N and needs a terminal. Nothing was changed.")
        return 2
    if not client.online():
        out(f"Refused: memory is offline ({client.url}); sr memory start first. Nothing was changed.")
        return 2
    answer = ask(f"Clear bank {client.bank} and reload every delivered tagged task from the log? [y/N] ")
    if (answer or "").strip().lower() != "y":
        out("Nothing was changed.")
        return 0
    try:
        conn = log.init_db(db_path)
    except log.VersionError as e:
        out(f"Refused: {e}")
        return 2
    try:
        memory.rebuild(conn, client, secrets, out)
    except memory.Unavailable as e:
        out(f"memory: rebuild stopped: {e}. Run it again once the store answers.")
        return 1
    finally:
        conn.close()
    return 0


def cmd_status(*, roster, as_json=False, out=print, now=None):
    """`sr status [--json]` (rules v2.30, Status and JSON; build brief 21, B2): the router's state for a page or a
    person. The log is opened read-only (no log yet: none), the online checks are commands run side by side for the
    configured agents (router/online.py), never a model; the `.env` values are read only to say whether something is
    configured and to redact. Writes nothing. Exit 0."""
    env = dotenv_values(ENV_PATH) or {}
    conn = _read_log()
    try:
        names = [n for n in status.AGENTS if status.configured(n, roster, env)]
        found = online.run_all({n: online.CHECKS[n] for n in names if n in online.CHECKS}, now=now)
        versions = {name: _quietly(read) for name, read in (("claude", search.claude_version),
                                                            ("chatgpt", codex_probe.codex_version),
                                                            ("cursor", cursor_worker.installed_version))}
        doc = status.build(conn, roster=roster, loaded=_presets_or_none(roster), env=env, parser=_parser(roster),
                           online=found, versions=versions, state_path=PROBE_STATE,
                           memory_client=memory.client(requests.request), drop_folder=drop.folder(),
                           memory_starting=locks.holder(DB_PATH.parent / runs.FOLDER_NAME, "memory") is not None,
                           memory_installed=memory_server.paths(Path.home())["binary"].exists(),  # brief 27
                           rules_path=status.rules_file(ROOT), log_version=log.file_version(DB_PATH),
                           send_paths=tuple(SENDERS), contracts=relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
    finally:
        if conn is not None:
            conn.close()
    if as_json:
        receipt.deliver(out, doc)
        return 0
    secrets = safety.env_secrets(env)
    for line in status.lines(doc):
        out(safety.for_terminal(line, secrets))
    return 0


def _quietly(read):
    """A version read for `sr status`: any failure reads as unknown, never a crash of the status page."""
    try:
        return read()
    except Exception:
        return "unknown"


def cmd_relay_list(*, loaded, out=print):
    """`sr relay --list`: every preset, its stages and its checker; a bad one marked BAD."""
    for line in presets.describe(loaded):
        out(line)
    return 0


def grok_limit_line():
    """`sr probe`'s Grok line (rules v2.21): the prompt limit in force and where it came from. No call is made."""
    most, source = settings.grok_prompt_limit()
    if source == "default":
        return f"grok prompt limit: {most} (default; you haven't written grok_prompt_limit in config/settings.json)"
    return f"grok prompt limit: {most} ({source})"


def cmd_probe(*, model, config, environ, home, login=None, run=subprocess.run, claude_check=None, web_files_check=None,
              cursor_check=None, out=print):
    """One real Codex run that must fail to read .env, list the home folder or write a file; then
    (`claude_check`, which main always passes; build brief 8) one real Claude run with the search
    command, which must search and do nothing else. Nothing is logged. Exit 0 when both pass, 1 when
    either fails, 2 refused. A failed Claude check turns Claude's search off; it never touches Codex."""
    problems = _dedupe(safety.billing_problems(environ) + safety.billing_problems(config))
    if problems:
        for problem in problems:
            out(f"Refused: {problem}")
        out("Nothing was run.")
        return 2
    if not model:
        out("Refused: ChatGPT isn't configured (no model in config/agents.json). Nothing was run.")
        return 2
    if login is not None and not login():
        out("Refused: codex is not logged in with ChatGPT. Sign in yourself with `codex login`, then run this again.")
        return 2
    out(grok_limit_line())  # brief 15: no call, the webhook is never probed
    result = codex_probe.probe(model=model, config=config, env_path=ENV_PATH, home=home, run=run, environ=environ)
    out(f"Probed chatgpt: codex {result.codex_version}, model {model}, {result.seconds:.0f} s")
    for check in result.checks:
        out(f"  {'ok  ' if check.ok else 'FAIL'}  {check.name}" + (f" ({check.detail})" if check.detail else ""))
    for note in result.notes:
        out(f"  note  {note}")
    probes.record_codex(PROBE_STATE, result)  # brief 24 (decision 10): kept per Codex version, as the router's own run keeps it
    if result.passed:
        out(f"PASS: ChatGPT could not read .env, list the home folder or write a file. The pass is kept for codex "
            f"{result.codex_version}.")
    else:
        out(f"FAIL: ChatGPT stays off on codex {result.codex_version} until a probe passes. Nothing was logged.")
    ok = result.passed
    if claude_check is not None:
        claude = claude_check()
        out(f"Probed claude search: claude {claude.claude_version}, model {claude_worker.WORKER_MODEL}, {claude.seconds:.0f} s")
        for check in claude.checks:
            out(f"  {'ok  ' if check.ok else 'FAIL'}  {check.name}" + (f" ({check.detail})" if check.detail else ""))
        for query in claude.queries:
            out(f"  query  {safety.for_terminal(query)}")
        if claude.passed:
            out(f"claude search: passed (version {claude.claude_version})")
        else:
            failed = claude.first_failure
            out(f"claude search: FAILED \u2014 {failed.name}" + (f" ({failed.detail})" if failed.detail else "") + "; search off")
        ok = ok and claude.passed
        if web_files_check is not None:
            files = web_files_check()  # brief 15 addendum, D9: Claude's --web file mode, its own pass
            out(f"Probed claude --web files: claude {files.claude_version}, model {claude_worker.WORKER_MODEL}, "
                f"{files.seconds:.0f} s")
            for check in files.checks:
                out(f"  {'ok  ' if check.ok else 'FAIL'}  {check.name}" + (f" ({check.detail})" if check.detail else ""))
            for query in files.queries:
                out(f"  query  {safety.for_terminal(query)}")
            if files.passed:
                out(f"claude --web files: passed (version {files.claude_version})")
            else:
                failed = files.first_failure
                out(f"claude --web files: FAILED \u2014 {failed.name}" + (f" ({failed.detail})" if failed.detail else "")
                    + "; Claude's --web file mode off (ChatGPT's still works)")
            ok = ok and files.passed
    if cursor_check is not None:  # build brief 20 (rules v2.28, Cursor; the owner's change 3): the two canaries, when needed
        cursor = cursor_check()
        if cursor.standing:
            out(f"cursor safety check: passed on agent {cursor.standing} stands (sr probe checks it again when agent moves)")
        elif cursor.skipped:
            out(f"cursor safety check: not run ({cursor.skipped})")
        else:
            out(f"cursor safety check: ran on agent {cursor.agent_version}, model {cursor.model}, {cursor.seconds:.0f} s")
            for check in cursor.checks:
                out(f"  {'ok  ' if check.ok else 'FAIL'}  {check.name}" + (f" ({check.detail})" if check.detail else ""))
            for note in cursor.notes:
                out(f"  note  {note}")
            if cursor.passed:
                out(f"cursor safety check: passed (version {cursor.agent_version})")
            else:
                failed = cursor.first_failure
                out(f"cursor safety check: FAILED \u2014 {failed.name}" + (f" ({failed.detail})" if failed.detail else "")
                    + "; Cursor stays off")
            ok = ok and cursor.passed
    return 0 if ok else 1


def _claude_gate(config, out):
    """Brief 22 (decision 7, Phase 0 choice 5): the probe gate a command hands its Claude calls. With no pass on the
    installed Claude Code version, Claude's two probes (the existing ones, called as `sr probe` calls them) run first, one
    at a time by the lock beside the log."""
    made = {search.SEARCH_KEY: lambda: claude_probe.command_check(PROBE_STATE, config=config, env_path=ENV_PATH,
                                                                   home=Path.home(), environ=os.environ),
            search.WEB_FILES: lambda: web_files_probe.command_check(PROBE_STATE, config=config, env_path=ENV_PATH,
                                                                     home=Path.home(), environ=os.environ)}
    return probes.claude_gate(PROBE_STATE, folder=DB_PATH.parent / runs.FOLDER_NAME, out=out, checks=made)


def _codex_gate(config, out, model):
    """Build brief 24 (decision 10): the gate a command hands its ChatGPT calls. With no Codex probe pass on the installed
    Codex version, the existing probe runs first (one ChatGPT call), one at a time by the lock beside the log."""
    def check():
        return codex_probe.probe(model=model, config=config, env_path=ENV_PATH, home=Path.home(), environ=os.environ)
    return probes.chatgpt_gate(PROBE_STATE, folder=DB_PATH.parent / runs.FOLDER_NAME, out=out, check=check,
                               version=codex_probe.codex_version)


def _stdout_is_terminal():
    """Waiting only makes sense in a terminal. In Claude Code (or a pipe) route doesn't wait."""
    return sys.stdout.isatty()


def _can_ask():
    """Asking the owner for a skill needs a terminal for both input and output: not Claude Code, not a pipe."""
    return sys.stdin.isatty() and sys.stdout.isatty()


WEB_REFUSAL = "--web is for a routed task with files"  # rules v2.22: refused on every other command


# Build brief 21 (rules v2.30, Router for the interface): the actions that answer with the JSON envelope, and the reads
# that print their own JSON document (a list here; status, show and log in phase B).
JSON_ACTIONS = ("route", "relay", "split", "resume", "fallback", "pick", "cancel", "check", "project", "chat", "memory")
JSON_READS = ("status", "show", "log")  # print their own document (brief 21, B2 and B3)
JSON_COMMANDS = JSON_ACTIONS + JSON_READS
JSON_HELP = ("answer with one JSON object (task_id, n, status, waiting_on, outcome, reason_code, exit, message): on stdout, "
             "or on stderr when refused or failed; asks nothing and waits for nothing")


class _ParseExit(Exception):
    """Under --json argparse prints nothing itself: an error or --help ends here with its text and its exit code."""

    def __init__(self, status, text):
        super().__init__(text)
        self.status, self.text = status, text


class _QuietParser(argparse.ArgumentParser):
    """The parser under --json (brief 21): what argparse would print becomes the JSON's message, never a stream line."""

    def _print_message(self, message, file=None):
        if message:
            self._said = getattr(self, "_said", "") + message

    def exit(self, status=0, message=None):
        self._print_message(message)
        raise _ParseExit(status, getattr(self, "_said", ""))


def _parser(roster, quiet=False):
    """The command line. The help text names the live agents from the config, when it loads. `quiet` (--json): see
    _QuietParser."""
    if roster is None:
        agents_text, tags_text = "a live agent", "@<agent> (config/agents.json could not be read)"
    else:
        agents_text = " or ".join(roster.live)
        tags_text = " or ".join(f"@{name}" for name in roster.live)
    parser = (_QuietParser if quiet else argparse.ArgumentParser)(prog="python -m router", allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    p_route = sub.add_parser("route", help=f"route a task: Jev labels it and the skill table picks {agents_text}",
                             allow_abbrev=False)
    p_route.add_argument("--no-wait", action="store_true",
                         help="return as soon as a Grok task is sent (also automatic when output isn't a terminal)")
    p_route.add_argument("task", nargs="+", help=f"the task text; start with {tags_text} to force that agent")
    p_route.add_argument("--file", action="append", default=[], metavar="PATH",
                         help="attach a file (up to 4; png, jpg, jpeg, webp, gif, pdf, mp4, mov; 50 MB each; "
                              "one video). Copies go to Claude or ChatGPT only, never to Grok")
    p_route.add_argument("--web", action="store_true",
                         help="let Claude and ChatGPT search the web on this task's calls with files too: say the files "
                              "are not private (rules v2.22); without files it changes nothing")
    p_route.add_argument("--source", default="cli")
    p_route.add_argument("--project", metavar="NAME", help="run the task with a registered project's HANDOFF.md as "
                                                           "context (rules v2.25); sr project list prints the names")
    p_route.add_argument("--chat", metavar="NAME", help="tag the task chat:<name> for memory (rules v2.27): lower case "
                                                        "letters, digits and -; nothing to create; never with --project")
    p_route.add_argument("--skill", metavar="KEY", help="label the task yourself with this skill; Jev is not asked "
                                                        "(build brief 22)")
    p_route.add_argument("--answers", metavar="N", help="with --skill: the Jev floor row this answers (its # or task_id); "
                                                        "the text must be that row's, its tag, --web and files come from it")
    p_route.add_argument("--json", action="store_true", help=JSON_HELP)
    p_relay = sub.add_parser("relay", help="run a preset chain (rules v2.16): sr relay research-build|collab|versus "
                                           "\"task\"; --list prints the presets; a versus task ends with `sr pick`",
                             allow_abbrev=False)
    p_relay.add_argument("--list", action="store_true", help="print every preset in config/presets.json")
    p_relay.add_argument("--no-wait", action="store_true",
                         help="return as soon as a Grok stage is sent (also automatic when output isn't a terminal)")
    p_relay.add_argument("preset", nargs="?", help="the preset name, from `sr relay --list`")
    p_relay.add_argument("task", nargs="*", help="the task text; no @agent prefix on a relay task")
    p_relay.add_argument("--file", action="append", default=[], metavar="PATH",
                         help="not allowed on a relay task (refused with the reason)")
    p_relay.add_argument("--source", default="cli")
    p_relay.add_argument("--web", action="store_true", help=WEB_REFUSAL)
    p_relay.add_argument("--project", metavar="NAME", help="research-build and redteam only (rules v2.25)")
    p_relay.add_argument("--chat", metavar="NAME", help="tag the task chat:<name> for memory (rules v2.27), any preset; "
                                                        "never with --project")
    p_relay.add_argument("--json", action="store_true", help=JSON_HELP)
    split_text = ("split a task (rules v2.18): Claude plans 2 to 4 pieces, you approve them (y/N/e), each runs as its "
                  "own routed task, Claude joins the results and ChatGPT checks: sr split \"task\"; "
                  "sr split --go <n> approves a plan that waited")
    p_split = sub.add_parser("split", help=split_text, description=split_text, allow_abbrev=False)
    p_split.add_argument("--no-wait", action="store_true",
                         help="return as soon as a Grok piece is sent (also automatic when output isn't a terminal)")
    p_split.add_argument("task", nargs="*", help="the task text; no @agent prefix on a split task")
    p_split.add_argument("--go", metavar="N", help="approve a plan that waited (needs a terminal), or report a "
                                                   "split's pieces and integrate once every piece is in")
    p_split.add_argument("--skip", metavar="PIECE", help="go on without a blocked piece (its # or task_id); the "
                                                       "integration says it is missing")
    p_split.add_argument("--file", action="append", default=[], metavar="PATH",
                         help="not allowed on a split task (refused with the reason)")
    p_split.add_argument("--preset", help="not allowed on a split task (refused with the reason)")
    p_split.add_argument("--source", default="cli")
    p_split.add_argument("--web", action="store_true", help=WEB_REFUSAL)
    p_split.add_argument("--project", metavar="NAME", help="not allowed on a split task (refused with the reason)")
    p_split.add_argument("--chat", metavar="NAME", help="not allowed on a split task (refused with the reason)")
    p_split.add_argument("--answer", metavar="Y|N", help="with --go: approve (y) or reject (n) a plan that waits, without "
                                                         "a terminal; editing a piece stays Terminal-only (build brief 22)")
    p_split.add_argument("--skill", action="append", default=[], metavar="K=KEY",
                         help="with --go --answer y: the skill for piece K when Jev was under the floor on it")
    p_split.add_argument("--json", action="store_true", help=JSON_HELP)
    resume_text = ("continue a task Claude or ChatGPT stopped on its plan limit, once, with the other of the two "
                   "(rules v2.15): sr resume 5")
    p_resume = sub.add_parser("resume", help=resume_text, description=resume_text, allow_abbrev=False)
    p_resume.add_argument("--no-wait", action="store_true",
                          help="return as soon as a Grok call is sent (also automatic when output isn't a terminal)")
    p_resume.add_argument("words", nargs="*", help="the task number from `sr log`, or a task_id")
    p_resume.add_argument("--web", action="store_true", help=WEB_REFUSAL)
    p_resume.add_argument("--json", action="store_true", help=JSON_HELP)
    pick_text = ("pick a versus candidate (rules v2.16): sr pick 5 a|b|none; the picked one becomes the "
                 "task's result, none fails the task; one pick per task")
    p_pick = sub.add_parser("pick", help=pick_text, description=pick_text, allow_abbrev=False)
    p_pick.add_argument("words", nargs="*", help="the task number from `sr log` (or a task_id), then a, b or none")
    p_pick.add_argument("--json", action="store_true", help=JSON_HELP)
    fallback_text = ("redo a task whose result failed its check twice, once (rules v2.17): its checker redoes it "
                     "from the task and the final fix list, never the failed result; the original doer checks: "
                     "sr fallback 5")
    p_fallback = sub.add_parser("fallback", help=fallback_text, description=fallback_text, allow_abbrev=False)
    p_fallback.add_argument("--no-wait", action="store_true",
                            help="return as soon as a Grok check is sent (also automatic when output isn't a terminal)")
    p_fallback.add_argument("words", nargs="*", help="the task number from `sr log`, or a task_id")
    p_fallback.add_argument("--web", action="store_true", help=WEB_REFUSAL)
    p_fallback.add_argument("--json", action="store_true", help=JSON_HELP)
    p_check = sub.add_parser("check", help="read Grok results from the inbox, mark done or timed out")
    p_check.add_argument("--web", action="store_true", help=WEB_REFUSAL)
    p_check.add_argument("--json", action="store_true", help=JSON_HELP + "; a `tasks` list says what became of each open task")
    p_log = sub.add_parser("log", help="print recent tasks")
    p_log.add_argument("-n", "--limit", type=int, default=20)
    p_log.add_argument("--chat", metavar="NAME", help="only that chat's tasks (rules v2.27)")
    p_log.add_argument("--project", metavar="NAME", help="only that project's tasks (rules v2.30)")
    p_log.add_argument("--search", metavar="TEXT", help="only tasks whose text holds TEXT (any case, plain text)")
    p_log.add_argument("--before", metavar="TASK", help="only tasks older than TASK (its # or task_id): the next page")
    p_log.add_argument("--json", action="store_true", help="the rows as JSON, newest first, with their state (rules v2.30)")
    p_show = sub.add_parser("show", help="print one task in full: newest, #n, a task_id, or the newest task containing words")
    p_show.add_argument("words", nargs="*")
    p_show.add_argument("--history", action="store_true",
                        help="list every call the task made (the original result and the fix list live here)")
    p_show.add_argument("--stages", action="store_true", help="on a relay task, also print each stage's result")
    p_show.add_argument("--pieces", action="store_true", help="on a split task, also print each piece's result")
    p_show.add_argument("--memory", action="store_true",
                        help="on a tagged task, also print the memory block as it was sent to the build call (rules v2.27)")
    p_show.add_argument("--handoff", action="store_true",
                        help="on a project task, also print the handoff as it was sent to the build call (rules v2.25)")
    p_show.add_argument("--json", action="store_true", help="the task, its calls and everything its kind has, as JSON "
                                                            "(rules v2.30); read only")
    p_cancel = sub.add_parser("cancel", help="cancel a queued or sent task: sr cancel 5 (the # column in log)")
    p_cancel.add_argument("words", nargs="*")
    p_cancel.add_argument("--json", action="store_true", help=JSON_HELP)
    p_status = sub.add_parser("status", help="the router's state: agents (online by a command, never a model), presets, "
                                              "skills, commands, open tasks, Jev's meter, memory; writes nothing")
    p_status.add_argument("--json", action="store_true", help="print one JSON object and nothing else (rules v2.30)")
    p_serve = sub.add_parser("serve", help="the page on 127.0.0.1: shows the log and runs sr commands with buttons "
                                           "(Ctrl+C stops the page; tasks it started keep running)")
    p_serve.add_argument("--port", type=int, default=None, help="the port (default: serve_port in config/settings.json)")
    p_serve.add_argument("--demo", action="store_true",
                         help="show the page on invented sample tasks; nothing runs (works with no setup)")
    sub.add_parser("migrate", help="one time: move a version 1 log into backups/ and start fresh, "
                                   "or upgrade a version 2 log in place after a backup copy")
    p_project = sub.add_parser("project", help="the project registry (rules v2.25): sr project add <name> <path>, "
                                               "sr project list, sr project remove <name>, sr project new <name> "
                                               "[--dry-run] [-- '<notes>'] (brief 26: makes <projects_root>/<name>)",
                               allow_abbrev=False)
    p_project.add_argument("words", nargs="*", help="add <name> <path> | list | remove <name> | new <name>")
    p_project.add_argument("--json", action="store_true", help=JSON_HELP + "; `list --json` prints the projects as JSON")
    p_project.add_argument("--dry-run", action="store_true", dest="dry_run",
                           help="with new: say what it would do (create, register or refuse) and write nothing")
    p_chat = sub.add_parser("chat", help="chats from the log (rules v2.27): sr chat list prints every chat name with its "
                                         "task count and newest date; nothing is created", allow_abbrev=False)
    p_chat.add_argument("words", nargs="*", help="list")
    p_chat.add_argument("--json", action="store_true", help=JSON_HELP + "; `list --json` prints the chats as JSON")
    p_memory = sub.add_parser("memory", help="the memory store (rules v2.27, 2.38): sr memory start|stop|status|rebuild|on|"
                                             "off; Hindsight on 127.0.0.1:8888 from ~/.hindsight/venv; on and off switch "
                                             "memory for this Mac (config/settings.local.json) and start or stop the store; "
                                             "rebuild reloads the bank from the log",
                              allow_abbrev=False)
    p_memory.add_argument("words", nargs="*", help="start | stop | status | rebuild | on | off")
    p_memory.add_argument("--json", action="store_true", help=JSON_HELP)
    sub.add_parser("probe", help="one real Codex run that must fail to read .env, list your home folder or write a file; "
                                 "run it after every Codex update, before routing tasks to ChatGPT; then one real Claude run "
                                 "that must web-search and do nothing else (run it after every Claude Code update: "
                                 "Claude's search stays off until it passes)")
    return parser


def _workers(environ, model, cursor_model=None):
    """The Claude, ChatGPT and Cursor workers main hands on (ChatGPT and Cursor None without a pinned model). With
    SR_INJECT_PLAN_LIMIT set (test-only, build brief 7) the named agent's next call stops on an
    injected plan limit at the worker's process boundary; plan_limit.injected raises InjectRefused
    on the real log, before anything runs."""
    agent = environ.get(plan_limit.ENV_NAME)
    hook = plan_limit.injected(agent, DB_PATH, root=ROOT) if agent is not None else None
    claude = functools.partial(claude_worker.run, run=hook(subprocess.run)) if agent == "claude" else claude_worker.run
    cursor = functools.partial(cursor_worker.run, model=cursor_model) if cursor_model else None  # rules v2.28, brief 20
    if not model:
        return claude, None, cursor
    if agent == "chatgpt":
        return claude, functools.partial(chatgpt_worker.run, model=model, run=hook(subprocess.run)), cursor
    return claude, functools.partial(chatgpt_worker.run, model=model), cursor


def _presets_or_none(roster, warn=False, out=print):
    """The checked presets for commands that only read them (`check`, `serve`): None when the
    file can't be used, with a warning when asked, so those commands still run."""
    if roster is None:
        return None
    try:
        return presets.load_presets(roster, tuple(SENDERS), relay.CONTRACTS, roles=relay.ROLES,
                                    verdicts=relay.VERDICTS)
    except presets.PresetsError as e:
        if warn:
            out(f"Warning: {' '.join(e.problems)} Relay tasks can't move on until it is fixed.")
        return None


# `sr relay`'s own flags; any other `--name` on a relay command is a slot flag (the owner's D2, brief 15).
RELAY_FLAGS = ("--list", "--no-wait", "--help", "-h", "--web", "--json")  # --web is refused on relay, not a slot
RELAY_VALUE_FLAGS = ("--file", "--source", "--project", "--chat")  # --project and --chat are intake's, never a slot


def _take_slot_flags(argv):
    """(argv without the slot flags, [(slot, agent or None)]) for a relay command; any other command unchanged.
    `--name agent` and `--name=agent` both count; a bare `--` ends the flags. Intake judges each one, so an
    unknown slot gets its own reason instead of argparse's."""
    argv = list(argv)
    if not argv or argv[0] != "relay":
        return argv, []
    rest, found, i = [argv[0]], [], 1
    while i < len(argv):
        token = argv[i]
        if token == "--":
            rest += argv[i:]
            break
        name = token.split("=", 1)[0]
        if not token.startswith("--") or name in RELAY_FLAGS or name in RELAY_VALUE_FLAGS:
            rest.append(token)
            if name in RELAY_VALUE_FLAGS and "=" not in token and i + 1 < len(argv):
                rest.append(argv[i + 1])
                i += 1
            i += 1
            continue
        if "=" in token:
            value = token.split("=", 1)[1] or None
        elif i + 1 < len(argv) and not argv[i + 1].startswith("-"):
            value = argv[i + 1]
            i += 1
        else:
            value = None
        found.append((name[2:], value))
        i += 1
    return rest, found


def _serve_demo(argv, out):
    """`sr serve --demo` (build brief 23, decision 15): the page on the invented sample in demo/, with nothing run,
    started before anything that needs setup (the config, the host check, the billing switches, .env, the log), so a
    fresh clone with its requirements installed shows it on any system. The port: --port, else serve_port, else 8765."""
    args = _parser(None).parse_args(argv)
    port = args.port
    if port is None:
        try:
            port = settings.serve_port()
        except (OSError, ValueError):
            port = page.DEFAULT_PORT
    return page.serve_demo(port, out=out)


def _slot_flag_elsewhere(argv):
    """The first slot flag (`--build`) on `sr route` or `sr split`, which take none (rules v2.21); else None."""
    if not argv or argv[0] not in ("route", "split"):
        return None
    names = presets.slot_names()
    for token in argv[1:]:
        if token == "--":
            return None
        if token.startswith("--") and token[2:].split("=", 1)[0] in names:
            return token.split("=", 1)[0]
    return None


def _main(argv, platform, out):
    """The command line, printing through `out`: print, or under --json a Receipt (brief 21), which keeps the prose for
    the JSON's message and asks nothing and waits for nothing, as when output isn't a terminal."""
    json_mode = isinstance(out, receipt.Receipt)
    if argv[:1] == ["serve"] and "--demo" in argv[1:]:  # brief 23 (decision 15): before the roster, host, .env and log
        return _serve_demo(argv, out)
    elsewhere = _slot_flag_elsewhere(argv)
    if elsewhere:
        receipt.mark(out, code="slot_refused", command=True)
        out(f"Refused: slot flags are for sr relay only ({elsewhere} on sr {argv[0]}). Nothing was logged or sent.")
        return 2
    argv, slot_flags = _take_slot_flags(argv)
    argv, project_notes, notes_problem = _take_project_notes(argv)  # brief 26: the notes are never a flag
    if notes_problem:
        receipt.mark(out, code="usage", command=True)
        out(f"Refused: {notes_problem}. Nothing was changed.")
        return 2
    try:
        roster, roster_error = load_roster(send_paths=tuple(SENDERS)), None
    except RosterError as e:
        roster, roster_error = None, e
    args = _parser(roster, quiet=json_mode).parse_args(argv)
    if args.command != "route" and getattr(args, "web", False):
        receipt.mark(out, code="flag_refused", command=True)
        out(f"Refused: {WEB_REFUSAL} (sr route --file <path> --web). Nothing was logged or sent.")
        return 2
    if args.command == "split" and args.project:  # rules v2.25, Split
        receipt.mark(out, code="tag_refused", command=True)
        out(SPLIT_PROJECT_REFUSAL)
        return 2
    if args.command == "split" and args.chat:  # rules v2.27, Memory: as --project
        receipt.mark(out, code="tag_refused", command=True)
        out(SPLIT_CHAT_REFUSAL)
        return 2
    if getattr(args, "chat", None) and getattr(args, "project", None):  # rules v2.27: one tag per task
        receipt.mark(out, code="tag_refused", command=True)
        out(ONE_TAG_REFUSAL)
        return 2

    host_problems = safety.check_host(platform)
    if host_problems:
        receipt.mark(out, code="setup", command=True)
        for problem in host_problems:
            out(f"Refused: {problem}")
        out("Nothing was logged or sent.")
        return 2

    global BACKDATE_MINUTES
    BACKDATE_MINUTES = None  # one command's hook: never carried into the next command in the same process
    try:  # the test-only injected limit is refused on the real log before anything runs
        worker, chatgpt, cursor = _workers(os.environ, roster.model("chatgpt") if roster else None,
                                           roster.model("cursor") if roster else None)
        if os.environ.get(plan_limit.OVERDUE_ENV) is not None:  # brief 24 (C8): so is the injected overdue
            BACKDATE_MINUTES = plan_limit.overdue_minutes(os.environ[plan_limit.OVERDUE_ENV], DB_PATH,
                                                          settings.grok_timeout_minutes(), root=ROOT)
            out(f"Test hook: each Grok call this command sends is logged {BACKDATE_MINUTES} minutes early, so the next "
                "check reads it overdue (scratch log).")
    except plan_limit.InjectRefused as e:
        receipt.mark(out, code="setup", command=True)
        out(f"Refused: {e} Nothing was logged or sent.")
        return 2
    # rules v2.28 and brief 22 (decision 7): the sandbox pass and the login, once per command; the canaries first when the
    # installed agent has no pass
    cursor_ready = functools.partial(probes.cursor_ready, PROBE_STATE, model=roster.model("cursor") if roster else None,
                                     folder=DB_PATH.parent / runs.FOLDER_NAME, out=out)
    if os.environ.get(plan_limit.ENV_NAME) is not None:
        out(f"Test hook: the next {os.environ[plan_limit.ENV_NAME]} call stops on an injected plan limit "
              f"(scratch log {DB_PATH}).")

    # Only route, relay, resume, serve and probe need the config, so log, show, cancel and check still work if it breaks.
    if args.command in ("route", "relay", "split", "resume", "fallback", "serve", "probe") and roster_error:
        receipt.mark(out, code="setup", command=True)
        for problem in roster_error.problems:
            out(f"Refused: {problem}")
        out("Nothing was logged or sent.")
        return 2

    if args.command == "status":  # brief 21: reads only; never a row, never an agent, nothing written
        return cmd_status(roster=roster, as_json=json_mode, out=out)

    if args.command == "serve":  # brief 21, B4: the page reads `sr status --json` and `sr log --json`, nothing else
        port = args.port if args.port is not None else settings.serve_port()  # brief 21: decision 7
        return page.serve(port, out=out,  # brief 22 (decision 8): `sr memory start` at launch when memory is auto
                          start_memory=page.start_memory if settings.memory_mode() == "auto" else None)

    if args.command == "migrate":
        return cmd_migrate(db_path=DB_PATH, backups_dir=BACKUPS_DIR)

    if args.command == "probe":  # runs codex in workspace/; needs no log
        try:
            safety.prepare_workspace()
        except safety.SafeError as e:
            out(f"Refused: {e}. Nothing was run.")
            return 2
        config = dotenv_values(ENV_PATH)
        return cmd_probe(model=roster.model("chatgpt"), config=config, environ=os.environ,
                         home=Path.home(), login=chatgpt_worker.login_status,
                         claude_check=claude_probe.command_check(PROBE_STATE, config=config, env_path=ENV_PATH,
                                                                 home=Path.home(), environ=os.environ),
                         web_files_check=web_files_probe.command_check(PROBE_STATE, config=config, env_path=ENV_PATH,
                                                                       home=Path.home(), environ=os.environ),
                         cursor_check=cursor_probe.command_check(PROBE_STATE, model=roster.model("cursor"), environ=os.environ))

    if args.command == "memory":  # rules v2.27: the store is the owner's to start and stop; no log is opened for it
        return cmd_memory(args.words, request=requests.request, environ=os.environ, home=Path.home(),
                          popen=subprocess.Popen, sleep=time.sleep, clock=time.monotonic, kill=os.kill, db_path=DB_PATH,
                          secrets=_secrets(dotenv_values(ENV_PATH)), ask=input if _can_ask() and not json_mode else None,
                          out=out)  # brief 27: memory takes --json, so its lines go through the receipt

    loaded = None
    if args.command in ("relay", "resume", "fallback"):  # the presets are checked before anything is logged
        try:
            loaded = presets.load_presets(roster, tuple(SENDERS), relay.CONTRACTS, roles=relay.ROLES,
                                          verdicts=relay.VERDICTS)
        except presets.PresetsError as e:
            receipt.mark(out, code="bad_preset", command=True)
            for problem in e.problems:
                out(f"Refused: {problem}")
            out("Nothing was logged or sent.")
            return 2
    if args.command == "check" and roster is not None:  # an open relay task needs its preset to go on
        loaded = _presets_or_none(roster, warn=True, out=out)

    runs_agents = args.command in ("route", "split", "check", "resume", "fallback") or (args.command == "relay" and not args.list)
    if runs_agents:  # all may run Claude in workspace/
        try:
            safety.prepare_workspace()
        except safety.SafeError as e:
            receipt.mark(out, code="setup", command=True)
            out(f"Refused: {e}. Nothing was logged or sent.")
            return 2

    try:  # brief 21: a JSON read opens the log read-only and never makes one
        conn = log.open_read_only(DB_PATH) if json_mode and args.command in JSON_READS else log.init_db(DB_PATH)
    except log.VersionError as e:
        receipt.mark(out, code="setup", command=True)
        out(f"Refused: {e}")
        return 2
    try:
        config = dotenv_values(ENV_PATH)
        gate = _gate(roster, config) if roster is not None else None  # brief 24 (decision 1): this command's checks
        codex = _codex_gate(config, out, roster.model("chatgpt") if roster else None)  # brief 24 (decision 10)
        if runs_agents:  # brief 21, C1 (rules v2.30, Round outputs): each call's output kept as its own file
            log.ROUND_WRITER = rounds.writer(secrets=safety.env_secrets(config), out=out, loaded=loaded)
        runs.FOLDER = DB_PATH.parent / runs.FOLDER_NAME  # brief 22: the run folder beside the log
        store = memory.client(requests.request)  # rules v2.27: the memory store, on the loopback address, no key
        if runs_agents:  # brief 22 (decision 8): memory starts on its own when a tagged task finds it down
            store = memory_auto.wrap(store, conn=conn, secrets=_secrets(config), out=out,
                                     folder=DB_PATH.parent / runs.FOLDER_NAME,
                                     start=memory_auto.starter(environ=os.environ, home=Path.home()))
        if args.command == "route":
            return cmd_route(
                " ".join(args.task), conn=conn, config=config, roster=roster, environ=os.environ,
                settings_paths=CLAUDE_SETTINGS,
                label=functools.partial(jev.label, roster=roster, api_key=config.get("JEV_API_KEY")),
                ask=input if _can_ask() and not json_mode else None, post=requests.post,
                worker=worker, chatgpt=chatgpt, codex_login=chatgpt_worker.login_status,
                cursor=cursor, cursor_ready=cursor_ready,
                fetch=inbox.fetch_issues, close=inbox.close_issue,
                sleep=time.sleep, clock=time.monotonic,
                wait=not args.no_wait and _stdout_is_terminal() and not json_mode, source=args.source,
                files=args.file, frames=media.extract_frames,
                drop_folder=drop.folder(), ask_attach=input if _can_ask() and not json_mode else None, convert=drop.convert_heic,
                pages=media.extract_pages, claude_ready=_claude_gate(config, out), hindsight=store, web=args.web,
                project=args.project, chat=args.chat, skill=args.skill, answers=args.answers, available=gate,
                chatgpt_ready=codex, out=out,
            )
        if args.command == "relay":
            if args.list:
                return cmd_relay_list(loaded=loaded, out=out)
            return cmd_relay(
                args.preset, " ".join(args.task), conn=conn, config=config, roster=roster, loaded=loaded,
                environ=os.environ, settings_paths=CLAUDE_SETTINGS, post=requests.post, worker=worker,
                chatgpt=chatgpt, codex_login=chatgpt_worker.login_status, cursor=cursor, cursor_ready=cursor_ready,
                fetch=inbox.fetch_issues, close=inbox.close_issue, sleep=time.sleep, clock=time.monotonic,
                wait=not args.no_wait and _stdout_is_terminal() and not json_mode, source=args.source, files=args.file, slots=slot_flags,
                claude_ready=_claude_gate(config, out), hindsight=store, project=args.project, chat=args.chat,
                available=gate, chatgpt_ready=codex, out=out,
            )
        if args.command == "split":
            common = dict(conn=conn, config=config, roster=roster, environ=os.environ, settings_paths=CLAUDE_SETTINGS,
                          label=functools.partial(jev.label, roster=roster, api_key=config.get("JEV_API_KEY")),
                          ask=input if _can_ask() and not json_mode else None, post=requests.post, worker=worker, chatgpt=chatgpt,
                          codex_login=chatgpt_worker.login_status, fetch=inbox.fetch_issues, close=inbox.close_issue,
                          sleep=time.sleep, clock=time.monotonic, wait=not args.no_wait and _stdout_is_terminal() and not json_mode,
                          claude_ready=_claude_gate(config, out), hindsight=store, available=gate,
                          chatgpt_ready=codex, out=out)
            if (args.answer is not None or args.skill) and args.go is None:  # brief 22 (decision 9)
                receipt.mark(out, code="usage", command=True)
                out("Refused: --answer and --skill go with sr split --go <n>. Nothing was logged or sent.")
                return 2
            if args.go is not None or args.skip is not None:
                if args.task or args.file or args.preset or (args.go is not None and args.skip is not None):
                    receipt.mark(out, code="usage", command=True)
                    out("Refused: `sr split --go <n>` and `sr split --skip <piece>` take one number only. "
                        "Nothing was logged or sent.")
                    return 2
                if args.skip is not None:
                    return cmd_split_skip([args.skip], **common)
                return cmd_split_go([args.go], answer=args.answer, skills=args.skill, **common)
            return cmd_split(" ".join(args.task), source=args.source, files=args.file, preset=args.preset, **common)
        if args.command == "resume":
            return cmd_resume(
                args.words, conn=conn, config=config, roster=roster, loaded=loaded, environ=os.environ,
                settings_paths=CLAUDE_SETTINGS, post=requests.post, worker=worker, chatgpt=chatgpt,
                codex_login=chatgpt_worker.login_status, fetch=inbox.fetch_issues, close=inbox.close_issue,
                sleep=time.sleep, clock=time.monotonic, wait=not args.no_wait and _stdout_is_terminal() and not json_mode,
                claude_ready=_claude_gate(config, out), hindsight=store, cursor=cursor, cursor_ready=cursor_ready,
                available=gate, chatgpt_ready=codex, out=out,
            )
        if args.command == "fallback":
            return cmd_fallback(
                args.words, conn=conn, config=config, roster=roster, loaded=loaded, environ=os.environ,
                settings_paths=CLAUDE_SETTINGS, post=requests.post, worker=worker, chatgpt=chatgpt,
                codex_login=chatgpt_worker.login_status, fetch=inbox.fetch_issues, close=inbox.close_issue,
                sleep=time.sleep, clock=time.monotonic, wait=not args.no_wait and _stdout_is_terminal() and not json_mode,
                claude_ready=_claude_gate(config, out), hindsight=store, available=gate, chatgpt_ready=codex, out=out,
            )
        if args.command == "check":
            if json_mode:  # brief 21: what became of each task open before the check
                out.open_before = _open_task_ids(conn)
            return cmd_check(conn=conn, config=config, environ=os.environ, settings_paths=CLAUDE_SETTINGS,
                             post=requests.post, worker=worker, chatgpt=chatgpt,
                             codex_login=chatgpt_worker.login_status, cursor=cursor, cursor_ready=cursor_ready,
                             fetch=inbox.fetch_issues, close=inbox.close_issue, presets=loaded, roster=roster,
                             claude_ready=_claude_gate(config, out), hindsight=store, available=gate,
                             chatgpt_ready=codex, out=out)
        if args.command == "log":
            return cmd_log(conn=conn, limit=args.limit, chat=args.chat, project=args.project, search=args.search,
                           before=args.before, as_json=json_mode, live=roster.live if roster else None,
                           loaded=_presets_or_none(roster), out=out)
        if args.command == "show":
            return cmd_show(conn=conn, words=args.words, secrets=_secrets(config), history=args.history, stages=args.stages,
                            pieces=args.pieces, handoff=args.handoff, memory=args.memory,
                            roster=roster, presets=_presets_or_none(roster), as_json=json_mode, config=config, out=out)
        if args.command == "cancel":
            return cmd_cancel(conn=conn, words=args.words, kill=os.kill, sleep=time.sleep, clock=time.monotonic, out=out)
        if args.command == "project":  # rules v2.25: the registry and the handoff file; nothing is sent
            return cmd_project(args.words, conn=conn, as_json=json_mode, out=out, notes=project_notes,
                               dry_run=args.dry_run, secrets=_secrets(config))
        if args.command == "chat":  # rules v2.27: from the log, no Hindsight call
            return cmd_chat(args.words, conn=conn, as_json=json_mode, out=out)
        if args.command == "pick":  # sends nothing; needs the presets to read the candidates
            return cmd_pick(args.words, conn=conn, loaded=_presets_or_none(roster), secrets=_secrets(config), hindsight=store,
                            out=out)
    finally:
        log.ROUND_WRITER = None
        runs.FOLDER = None
        conn.close()
    return 1



# ---------- --json (build brief 21, rules v2.30: Router for the interface) ----------

ENVELOPE_STDOUT = (0, 3, 4, 5)  # the action happened, or the task came back: stdout; refused, failed, stopped: stderr


def _json_requested(argv):
    """`--json` before any bare `--` on a command that takes it."""
    head = argv[:argv.index("--")] if "--" in argv else argv
    return bool(argv) and argv[0] in JSON_COMMANDS and "--json" in head[1:]


def _read_log():
    """The log opened read-only, or None (no file yet, or not a current-version log): the JSON never writes."""
    try:
        conn = log._read_only(DB_PATH)
    except sqlite3.Error:
        return None
    try:
        if log._version(conn) == log.VERSION:
            return conn
    except sqlite3.Error:
        pass
    conn.close()
    return None


def _task_state(conn, row):
    """state.of for one row, with what it needs from around it (jsonview.state_of)."""
    return jsonview.state_of(conn, row)


def _open_task_ids(conn):
    """The tasks that have not ended (state.of gives no outcome), oldest first."""
    rows = conn.execute("SELECT rowid AS n, * FROM tasks WHERE status IN ('queued', 'sent', 'returned') ORDER BY rowid")
    return [r["task_id"] for r in rows if not _task_state(conn, r).ended]


def _task_brief(conn, row):
    found = _task_state(conn, row)
    return {"task_id": row["task_id"], "n": row["n"], "status": row["status"], "waiting_on": found.waiting_on,
            "outcome": found.outcome, "reason_code": row["reason_code"]}


def _envelope(out, code):
    """The one object an action answers with: the task it acted on as the log has it now (its state computed, never
    stored), the reason_code it marked or the row's, the exit code and the prose. `sr check` adds `tasks`."""
    found = {"task_id": None, "n": None, "status": None, "waiting_on": None, "outcome": None, "reason_code": out.code,
             "exit": code, "message": out.message}
    conn = _read_log()
    if conn is not None:
        try:
            row = log.get_task(conn, out.task_id) if out.task_id else None
            if row is not None:
                brief = _task_brief(conn, row)
                found.update(brief, reason_code=out.code or brief["reason_code"])
            if out.multi:
                ids_ = list(dict.fromkeys(list(getattr(out, "open_before", [])) + _open_task_ids(conn)))
                found["tasks"] = [_task_brief(conn, log.get_task(conn, t)) for t in ids_ if log.get_task(conn, t)]
        finally:
            conn.close()
    elif out.multi:
        found["tasks"] = []
    if code == 0:
        found.update(out.extra)  # brief 26: a new project's `project`, after the envelope's own keys
    return found


def _emit_json(out, code):
    """Print the read command's document, or the envelope, through the redactor with every `.env` value: on stdout when
    the action happened or the task came back, else on stderr in the same shape."""
    secrets = safety.env_secrets(dotenv_values(ENV_PATH) or {})
    if out.document is not None and code == 0:
        print(jsonview.dumps(out.document, secrets))
        return
    print(jsonview.dumps(_envelope(out, code), secrets), file=sys.stdout if code in ENVELOPE_STDOUT else sys.stderr)


def _printer():
    """Build brief 22 (decision 10): the prose, line by line, through the redactor with every `.env` value of 8
    characters or more, so no line can show one whichever code printed it."""
    secrets = safety.env_secrets(dotenv_values(ENV_PATH) or {})

    def out(*args, **kwargs):
        print(*(safety.redact(a, secrets) for a in args), **kwargs)
    return out


def main(argv=None, platform=sys.platform):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not _json_requested(argv):
        # brief 23 (hard limit): `sr serve` never reads .env; its lines are its own, and every command it runs redacts its own
        return _main(argv, platform, print if argv[:1] == ["serve"] else _printer())
    out = receipt.Receipt(multi=argv[0] == "check")
    try:
        code = _main(argv, platform, out)
    except _ParseExit as e:  # an argparse error, or --help: its text is the message
        code = e.status
        out.lines += e.text.rstrip("\n").splitlines()
        if code:
            receipt.mark(out, code="usage", command=True)
    except KeyboardInterrupt:
        code = 130
        receipt.mark(out, code="interrupted", command=True)
    except Exception as e:  # unexpected: its type name only, never its text, which could quote anything
        code = 1
        out.lines, out.code = [f"unexpected error: {type(e).__name__}"], "internal_error"
    if code == 130:
        receipt.mark(out, code="interrupted", command=True)
    _emit_json(out, code)
    return code

if __name__ == "__main__":
    sys.exit(main())
