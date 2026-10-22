"""Build brief 20, phase C (rules v2.28, Cursor; decisions 6 and 7): where Cursor may run and where it is refused,
each before any row: `versus` a or b only; `--project` with a Cursor slot; a task too long for the command line;
`@cursor` refused while not live, an override when live, never with files; a routed task with files whose doer would
be Cursor comes back with the label shown; a stopped Cursor call is never resumed; a fallback never has Cursor check;
the owner's pick on a Cursor candidate; the Jev request byte for byte with and without the entry. Fakes only."""
import json

import pytest

from router import __main__ as cli
from router import cursor_worker, fallback, jev, log, presets, relay, resume, routing
from router.roster import Roster
from tests.helpers import fake_label, roster_with, shipped_roster
from tests.test_cursor_send import READY, SERVED, Cursor, Ready, answer
from tests.test_loop import Clock, Scripted
from tests.test_relay import CONFIG, SECRET, Chat, RelayHook

ROSTER = roster_with(cursor=True)
LOADED = presets.load_presets(ROSTER, tuple(cli.SENDERS), relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
TASK = "Write a Python function that parses durations. Code only, no prose."
REVIEW = "## Verdict\npass\n\n## Notes\n- fine"
OK = {"status": "ok", "label": "writing", "confidence": 0.93, "needs_split": 0.1, "tokens": 764}


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _relay(conn, preset, slots, *, task=TASK, project=None, roster=ROSTER, loaded=LOADED, cursor=None):
    lines, clock, hook = [], Clock(), RelayHook()
    cursor = cursor or Cursor(answer("built by cursor"), answer(REVIEW))
    code = cli.cmd_relay(preset, task, conn=conn, config=CONFIG, roster=roster, loaded=loaded, environ={}, settings_paths=[],
                         post=hook.post, worker=Scripted("built by claude", REVIEW), chatgpt=Chat("built by chatgpt", REVIEW),
                         codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True, slots=list(slots),
                         cursor=cursor, cursor_ready=Ready(), project=project, out=lines.append)
    rows = log.recent_tasks(conn)
    return code, "\n".join(lines), rows[0] if rows else None, hook, cursor


def _route(conn, task, *, files=(), roster=ROSTER, cursor=None, ready=None, worker=None, chatgpt=None, jev_answer=OK):
    lines, clock, hook = [], Clock(), RelayHook()
    cursor, label = cursor or Cursor(), fake_label(jev_answer)
    code = cli.cmd_route(task, conn=conn, config=CONFIG, roster=roster, environ={}, settings_paths=[], label=label,
                         post=hook.post, worker=worker or Scripted("claude did it"), chatgpt=chatgpt or Chat("PASS"),
                         codex_login=lambda: True, cursor=cursor, cursor_ready=ready or Ready(), fetch=hook.fetch,
                         close=hook.close, sleep=clock.sleep, clock=clock, wait=True, files=list(files), out=lines.append)
    rows = log.recent_tasks(conn)
    return code, "\n".join(lines), rows[0] if rows else None, cursor, label


def _png(tmp_path, name="a.png"):
    path = tmp_path / name
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    return path


# ---------- the slots (decision 6) ----------

@pytest.mark.parametrize("slot", ["a", "b"])
def test_cursor_may_fill_versus_a_or_b(conn, slot):
    code, out, row, hook, cursor = _relay(conn, "versus", [(slot, "cursor")])
    assert code == 0, out
    assert json.loads(row["slots"])[slot] == "cursor" and len(cursor.prompts) == 2


REFUSED = [("research-build", "research"), ("research-build", "build"), ("research-build", "check"),
           ("collab", "lead"), ("collab", "partner"),
           ("redteam", "build"), ("redteam", "attack"), ("redteam", "check"),
           ("vote", "a"), ("vote", "b"), ("vote", "c")]


@pytest.mark.parametrize("preset, slot", REFUSED)
def test_every_other_slot_is_refused_with_the_reason_before_any_row(conn, preset, slot):
    code, out, row, hook, cursor = _relay(conn, preset, [(slot, "cursor")])
    assert code == 2 and row is None and cursor.prompts == [] and hook.sent == []
    assert f"Refused: cursor may fill versus a or b only (rules v2.28, Cursor), not {preset} {slot}." in out
    assert "Nothing was logged or sent." in out


def test_a_not_live_cursor_is_refused_as_any_agent_is(conn):
    off = roster_with(cursor=False)  # the shipped flag is live since 2026-10-20; the refusal is tested with it off
    code, out, row, *_ = _relay(conn, "versus", [("b", "cursor")], roster=off,
                                 loaded=presets.load_presets(off, tuple(cli.SENDERS), relay.CONTRACTS,
                                                             roles=relay.ROLES, verdicts=relay.VERDICTS))
    assert code == 2 and row is None and "Refused: cursor is not live, so it can't fill slot b." in out


def test_the_allow_list_is_the_rules_v2_28_one():
    assert presets.SLOTS_FOR == {"cursor": {"versus": ("a", "b")}}
    assert presets.slot_allowed("cursor", "versus", "a") and not presets.slot_allowed("cursor", "versus", "c")
    assert presets.slot_allowed("grok", "collab", "lead") and presets.slot_allowed("chatgpt", "vote", "c")


# ---------- --project with a Cursor slot ----------

def test_project_with_a_cursor_slot_is_refused_with_the_cursor_reason_first(conn, tmp_path, monkeypatch):
    from router import projects
    monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "config" / "projects.json")
    folder = tmp_path / "demo"
    folder.mkdir()
    (folder / "HANDOFF.md").write_text(f"# demo\n\n{projects.START}\n\n{projects.END}\n")
    projects.add("demo", str(folder))
    code, out, row, hook, cursor = _relay(conn, "versus", [("b", "cursor")], project="demo")
    assert code == 2 and row is None and cursor.prompts == []
    assert ("Refused: --project with cursor in slot b is refused: a Cursor slot on a --project task (rules v2.28, Cursor). "
            "Nothing was logged or sent.") in out
    assert "research-build and redteam only" not in out  # the Cursor reason, not the preset's


# ---------- the command-line length (decision 2) ----------

def test_a_task_too_long_for_cursor_is_refused_at_intake_with_both_lengths(conn):
    long = "x" * (cursor_worker.PROMPT_LIMIT - 200)
    prompt = cursor_worker.wrap(relay.task_build_prompt(long))
    assert len(prompt) > cursor_worker.PROMPT_LIMIT
    code, out, row, hook, cursor = _relay(conn, "versus", [("b", "cursor")], task=long)
    assert code == 2 and row is None and cursor.prompts == []
    assert (f"Refused: the task is too long for cursor (slot b): its prompt would be {len(prompt)} characters, the task alone "
            f"{len(long)}; cursor's limit is 100000. Shorten the task, or put another agent in slot b. Nothing was logged or sent.") in out


def test_the_same_task_without_a_cursor_slot_is_not_measured(conn):
    long = "x" * (cursor_worker.PROMPT_LIMIT - 200)
    code, out, row, *_ = _relay(conn, "versus", [], task=long)
    assert code == 0 and row is not None


# ---------- @cursor (Overrides) ----------

def test_at_cursor_is_refused_while_not_live(conn):
    code, out, row, cursor, label = _route(conn, "@cursor write a haiku", roster=roster_with(cursor=False))
    assert code == 2 and row is None and cursor.prompts == [] and label.calls == []
    assert "Refused: cursor is not live yet, so @cursor can't be used. Nothing was logged or sent." in out


def test_at_cursor_live_is_an_override_cursor_does_it_and_the_skills_second_checks(conn):
    cursor = Cursor(answer("a haiku about trays"))
    code, out, row, cursor, label = _route(conn, "@cursor write a haiku", cursor=cursor)
    assert code == 0, out
    assert (row["agent"], row["route_reason"], row["checker"], row["check_state"], row["status"]) == (
        "cursor", "override", "chatgpt", "passed", "done")
    assert cursor.prompts == [cursor_worker.wrap("write a haiku")]  # the task alone, no search line, no files
    do = log.get_call(conn, row["task_id"])
    assert do["agent"] == "cursor" and log.served_of(do)["model"] == SERVED["model"]
    assert "you chose it with @cursor" in out and row["result"] == "a haiku about trays"


@pytest.mark.parametrize("reason", ["cursor: agent moved to 2026.10.19-6bbf2c4 since the sandbox probe; run sr probe",
                                    "cursor: not signed in (agent login)"])
def test_at_cursor_not_ready_is_refused_at_intake_before_jev(conn, reason):
    code, out, row, cursor, label = _route(conn, "@cursor write a haiku", ready=Ready((False, reason)))
    assert code == 2 and row is None and cursor.prompts == [] and label.calls == []
    assert out == f"Refused: {reason}. Nothing was logged or sent."


def test_at_cursor_live_asks_readiness_once_at_intake_and_not_again_at_the_call(conn):
    ready = Ready()
    code, out, row, cursor, label = _route(conn, "@cursor write a haiku", ready=ready)
    assert code == 0 and ready.calls == 1 and len(cursor.prompts) == 1


def test_at_cursor_with_files_is_refused_at_intake(conn, tmp_path):
    code, out, row, cursor, label = _route(conn, "@cursor what is this", files=[_png(tmp_path)],
                                           jev_answer={**OK, "label": "read_media"})
    assert code == 2 and row is None and cursor.prompts == [] and label.calls == []
    assert "Refused: @cursor can't take files; a file goes only to Claude and ChatGPT. Nothing was logged or sent." in out


def test_a_routed_task_with_files_whose_doer_would_be_cursor_comes_back_with_the_label_shown(conn, tmp_path):
    # Not reachable today (no skill names cursor as best); built anyway (decision 6): a table copy with cursor best for code.
    table = json.loads(json.dumps(ROSTER.table))
    table["skills"]["code"]["best"] = "cursor"
    roster = Roster(agents=ROSTER.agents, not_routed=ROSTER.not_routed, table=table)
    decision = routing.decide({**OK, "label": "code"}, roster, files=True)
    assert decision.action == "return" and decision.skill == "code"
    assert decision.reason == "returned: a task with files can't go to cursor (a file goes only to Claude and ChatGPT)"
    assert routing.decide({**OK, "label": "code"}, roster, files=False).agent == "cursor"
    code, out, row, cursor, label = _route(conn, "fix this", files=[_png(tmp_path)], roster=roster,
                                           jev_answer={**OK, "label": "code"})
    assert code == 4 and row["status"] == "returned" and cursor.prompts == []
    assert "a task with files can't go to cursor" in out and "code" in out
    assert routing.NO_FILES_FOR["grok"] == routing.NO_FILES_FOR_GROK


# ---------- never resumed, never a checker on a fallback (decision 7) ----------

def test_a_stopped_cursor_stage_is_never_resumed_and_says_why(conn):
    code, out, row, hook, cursor = _relay(conn, "versus", [("b", "cursor")],
                                          cursor=Cursor(cursor_worker.WorkerError("agent reported an error: usage limit reached")))
    assert row["status"] == "failed" and row["failed_stage"] == 2
    calls = log.calls_for(conn, row["task_id"])
    plan = resume.decide(row, calls, live=ROSTER.live, preset=LOADED.presets["versus"])
    assert not plan.ok
    assert plan.reason == ("cursor is never resumed: a Cursor stop is the pool's limit, not a plan limit; run the task again "
                           "when the week resets, or with another agent in the slot")
    assert resume.stop_line(row, calls, live=ROSTER.live, preset=LOADED.presets["versus"]) is None  # no plan-limit line
    lines = []
    assert cli.cmd_resume([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[],
                          post=hook.post, worker=Scripted(), out=lines.append) != 0
    assert "cursor is never resumed" in "\n".join(lines)


def test_a_stopped_at_cursor_override_is_never_resumed(conn):
    code, out, row, cursor, label = _route(conn, "@cursor write a haiku", cursor=Cursor(cursor_worker.WorkerError("cursor timed out after 600 s")))
    assert row["status"] == "failed"
    plan = resume.decide(row, log.calls_for(conn, row["task_id"]), live=ROSTER.live)
    assert not plan.ok and plan.reason.startswith("cursor is never resumed")


def _double_failed_cursor_route(conn, tid="sr-cf"):
    log.add_task(conn, tid, TASK, "cli", {**OK, "label": "code"})
    log.set_route(conn, tid, agents=ROSTER.names, agent="cursor", route_reason="best", skill="code", skill_source="jev",
                  checker="chatgpt", check_state="pending")
    log.add_call(conn, tid, tid, "do", "cursor", "done", text="first", served=SERVED)
    log.add_call(conn, f"{tid}-c1", tid, "check", "chatgpt", "done", text="FIX\n- wrong", verdict="FIX")
    log.add_call(conn, f"{tid}-f1", tid, "fix", "cursor", "done", text="second", served=SERVED)
    log.add_call(conn, f"{tid}-c2", tid, "recheck", "chatgpt", "done", text="FIX\n- still wrong\n- and this", verdict="FIX")
    log.set_done(conn, tid, "second", check_state="failed", check_note="not passed after one fix round")
    return log.get_task(conn, tid)


def test_a_fallback_on_cursors_work_has_chatgpt_redo_it_and_nobody_check_it(conn):
    row = _double_failed_cursor_route(conn)
    plan = fallback.decide(row, log.calls_for(conn, row["task_id"]), live=ROSTER.live)
    assert plan.ok and plan.doer == "chatgpt" and plan.original == "cursor" and plan.checker is None
    lines = fallback.describe(row, plan)
    assert "chatgpt redoes it; unchecked: cursor, the original doer, never checks." in lines[0]
    assert fallback.stop_line(row, log.calls_for(conn, row["task_id"]), live=ROSTER.live) == (
        f"Run: sr fallback {row['n']}  (chatgpt redoes it; nobody checks)")


# ---------- the pick on a Cursor candidate (versus, unchanged) ----------

def test_the_owners_pick_of_the_cursor_candidate_is_its_stored_text(conn):
    code, out, row, hook, cursor = _relay(conn, "versus", [("b", "cursor")], cursor=Cursor(answer("CANDIDATE-B by cursor"),
                                                                                         answer("## Verdict\npass\n\n## Notes\n- fine")))
    assert relay.awaiting_pick(row)
    lines = []
    assert cli.cmd_pick([str(row["n"]), "b"], conn=conn, loaded=LOADED, secrets=[SECRET], out=lines.append) == 0
    picked = log.get_task(conn, row["task_id"])
    assert picked["result"] == "CANDIDATE-B by cursor" and picked["status"] == "done" and "picked b" in picked["check_note"]


# ---------- byte for byte (the brief's item 10) ----------

def test_the_jev_request_is_byte_identical_with_and_without_cursor_in_the_roster():
    with_cursor = shipped_roster()
    without = Roster(agents={k: v for k, v in with_cursor.agents.items() if k != "cursor"}, not_routed=with_cursor.not_routed,
                     table=with_cursor.table)
    assert "cursor" in with_cursor.names and "cursor" not in without.names
    for seed in ("sr-20261019-000001-abcd", "sr-20261019-000002-abcd", "sr-20261020-121212-ffff"):
        assert jev.build_criteria(with_cursor.table, seed) == jev.build_criteria(without.table, seed)
    assert with_cursor.labeler == without.labeler and list(with_cursor.skills) == list(without.skills)


def test_the_cursor_entry_changes_no_other_agents_prompt():
    # The brief 15 snapshots (tests/test_search_every_call.py, tests/test_slots_readers.py) compare every Claude, ChatGPT
    # and Grok prompt and row with the fixtures made before this brief; they run in the suite. This pins the reason:
    # a Cursor call is the only place the opener and the no-tools sentence are added.
    from router import checking
    assert cursor_worker.NO_TOOLS_SENTENCE not in relay.task_build_prompt(TASK)
    assert cursor_worker.NO_TOOLS_SENTENCE not in relay.review_prompt(TASK, "x")
    assert cursor_worker.NO_TOOLS_SENTENCE not in checking.checker_prompt(TASK, "r", no_tools=True)
    assert cursor_worker.NO_TOOLS_SENTENCE not in checking.fix_prompt(TASK, "r", "1. x")
