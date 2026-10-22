"""Build brief 15, phase C: every reader uses the task's filled preset, never the defaults (rules v2.21). The chain,
the check loop's checker, the re-ask, `sr check`'s continuation, resume, fallback (the owner's D5: a fallback row is
expected from the fallback doer, the check slot, never other_builder of a Grok slot; after it, a check stage goes to
the stage before's original agent), `sr show`, `sr log`, `sr relay --list` and the status page. A relay task with no
flag is byte for byte what it was before slots, in prompts and rows (the snapshot from `main` at a260d48).
Every value here is fake."""
import json
from pathlib import Path

import pytest

from router import __main__ as cli
from router import fallback, log, page, presets, relay, resume
from router.chatgpt_worker import WorkerError
from tests import relay_snapshot
from tests.helpers import count_lines_in, shipped_roster
from tests.test_relay import CONFIG, GOOD_NOTE, THIN, Chat, Clock, RelayHook, Scripted
from tests.relay_snapshot import AMENDED, DELIVERABLE, EDITED, PLAN, REVIEW

SENDERS = tuple(cli.SENDERS)
ROSTER = shipped_roster()
LOADED = presets.load_presets(ROSTER, SENDERS, relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
FIXTURE = json.loads((Path(relay_snapshot.__file__).parent / "fixtures" / "relay_no_flag_v9.json").read_text())


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _relay(conn, preset_name, slots, *, bodies=None, claude=(), chat=(), wait=True,
           task="Write a three-line note on garden seed trays, with one source."):
    hook, worker, chatgpt, clock, lines = RelayHook(**(bodies or {})), Scripted(*claude), Chat(*chat), Clock(), []
    code = cli.cmd_relay(preset_name, task, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                         settings_paths=[], post=hook.post, worker=worker, chatgpt=chatgpt, codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=wait,
                         slots=list(slots), out=lines.append)
    return code, "\n".join(lines), log.recent_tasks(conn)[0], hook, worker, chatgpt


def _calls(conn, row):
    return [(c["kind"], c["stage"], c["role"], c["agent"], c["status"]) for c in log.calls_for(conn, row["task_id"])]


# ---------- no flag: byte for byte as before slots ----------

@pytest.mark.parametrize("name", sorted(relay_snapshot.SCENARIOS))
def test_a_relay_task_with_no_flag_is_byte_identical_to_before_slots(name):
    """Brief 15's phase C test, read with the addendum (rules v2.22): Claude's and Grok's prompts byte for byte
    (Claude's search is off here: the probe gate is shut); each ChatGPT prompt is main's plus the one search line,
    and nothing else; every row as main wrote it, plus the search record each Claude or ChatGPT row now carries."""
    from router import checking
    now = json.loads(json.dumps(relay_snapshot.run(name), sort_keys=True, ensure_ascii=False))
    for agent in ("claude", "chatgpt", "grok"):  # brief 17, Phase W: the count lines out, the rest byte for byte
        now[agent] = [{**p, "task": count_lines_in(p["task"])[0]} if isinstance(p, dict) else count_lines_in(p)[0]
                      for p in now[agent]]
    before = FIXTURE[name]
    assert now["claude"] == before["claude"] and now["grok"] == before["grok"]
    line = "\n\n" + checking.SEARCH_LINE_GENERAL
    assert all(p.count(line) == 1 for p in now["chatgpt"])
    assert [p.replace(line, "", 1) for p in now["chatgpt"]] == before["chatgpt"]
    assert now["chatgpt_kwargs"] == [{"web_search": "live"}] * len(before["chatgpt_kwargs"])
    states = [(c["agent"], json.loads(c["search"])["state"] if c["search"] else None) for c in now["calls"]]
    assert all(state == {"claude": "off (probe not passed)", "chatgpt": "allowed", "grok": None}[agent]
               for agent, state in states)
    assert [{k: v for k, v in c.items() if k not in ("search", "context", "memory", "served", "round_file")}
            for c in now["calls"]] == [{k: v for k, v in c.items() if k != "search"} for c in before["calls"]]
    assert all(c["context"] is None for c in now["calls"])  # brief 18: no --project, so no context record
    assert all(c["memory"] is None for c in now["calls"])  # brief 19: no tag, so no memory record
    assert all(c["served"] is None for c in now["calls"])  # brief 20: no Cursor call, so no served record
    assert all(c["round_file"] is None for c in now["calls"])  # brief 21: no round writer in a test, so no file
    assert now["out"] == before["out"] and now["code"] == before["code"]
    slots = now["task"].pop("slots")
    now["task"].pop("web")
    assert now["task"].pop("project") is None and now["task"].pop("handoff") is None  # brief 18's columns
    assert now["task"].pop("chat") is None and now["task"].pop("memory") is None  # brief 19's columns
    assert now["task"].pop("reason_code") is None  # brief 21's column: the task was not returned
    assert [now["task"].pop(k) for k in ("pid", "run_started_at", "answered_by")] == [None] * 3  # brief 22's columns
    assert now["task"] == before["task"]  # every column the row had before; D1 adds the full slot map
    assert json.loads(slots) == presets.slot_map(LOADED.presets[relay_snapshot.SCENARIOS[name][0]])


def test_naming_every_slot_with_its_default_is_the_same_run_as_no_flag():
    preset = LOADED.presets["collab"]
    named = relay_snapshot.run("collab", slots=list(presets.slot_map(preset).items()))
    plain = relay_snapshot.run("collab")
    assert named == plain


# ---------- the chain, the re-ask, the check loop ----------

def test_research_by_chatgpt_then_build_by_claude_then_check_by_chatgpt(conn):
    code, out, row, hook, worker, chatgpt = _relay(conn, "research-build", [("research", "chatgpt")],
                                                   claude=["Built."], chat=[GOOD_NOTE, "PASS"])
    assert _calls(conn, row) == [("stage", 1, "research", "chatgpt", "done"), ("stage", 2, "build", "claude", "done"),
                                 ("check", None, None, "chatgpt", "done")]
    assert hook.sent == [] and relay.RESEARCH_INSTRUCTIONS in chatgpt.prompts[0]
    assert chatgpt.kwargs[0] == {"web_search": "live"}  # a research stage searches, as Grok's always did
    assert (row["status"], row["check_state"]) == ("done", "passed")


def test_the_re_ask_goes_to_the_agent_in_the_slot(conn):
    code, out, row, hook, worker, chatgpt = _relay(conn, "research-build", [("research", "chatgpt")],
                                                   claude=["Built."], chat=[THIN, GOOD_NOTE, "PASS"])
    assert _calls(conn, row)[:2] == [("stage", 1, "research", "chatgpt", "done"), ("reask", 1, "research", "chatgpt", "done")]
    assert "misses part of what was asked" in chatgpt.prompts[1]


def test_the_check_loop_asks_the_agent_in_the_check_slot(conn):
    code, out, row, hook, worker, chatgpt = _relay(conn, "research-build", [("check", "grok")],
                                                   bodies={"s1": GOOD_NOTE, "c1": "PASS"}, claude=["Built."])
    assert _calls(conn, row) == [("stage", 1, "research", "grok", "done"), ("stage", 2, "build", "claude", "done"),
                                 ("check", None, None, "grok", "done")]
    assert chatgpt.prompts == [] and row["checker"] == "grok" and row["check_state"] == "passed"


def test_collab_with_lead_chatgpt_and_partner_claude(conn):
    code, out, row, hook, worker, chatgpt = _relay(conn, "collab", [("lead", "chatgpt"), ("partner", "claude")],
                                                   claude=[AMENDED, EDITED], chat=[PLAN, DELIVERABLE])
    assert [(c[1], c[3]) for c in _calls(conn, row)] == [(1, "chatgpt"), (2, "claude"), (3, "chatgpt"), (4, "claude")]
    assert (row["agent"], row["checker"], row["check_state"]) == ("chatgpt", "claude", "passed")


def test_versus_with_b_grok_waits_for_grok_and_sr_check_reads_the_slots(conn):
    bodies = {"s2": "B's note.", "s3": REVIEW}
    code, out, row, hook, worker, chatgpt = _relay(conn, "versus", [("b", "grok")], bodies=bodies,
                                                   claude=["A's note.", REVIEW], wait=False)
    assert _calls(conn, row) == [("stage", 1, "build", "claude", "done"), ("stage", 2, "build", "grok", "sent")]
    deps_hook = hook
    from types import SimpleNamespace
    clock = Clock()
    deps = SimpleNamespace(config=CONFIG, post=deps_hook.post, worker=worker, chatgpt=chatgpt, codex_login=lambda: True,
                           codex_ok=None, fetch=deps_hook.fetch, close=deps_hook.close, sleep=clock.sleep, clock=clock,
                           wait=True, presets=LOADED, live=ROSTER.live)
    row = log.get_task(conn, row["task_id"])
    assert cli._open_task_text(row, log.calls_for(conn, row["task_id"]), deps).endswith("(stage 2, build by grok).")
    assert cli._run_loop(conn, row["task_id"], deps, [], lambda *_: None) == 0
    row = log.get_task(conn, row["task_id"])
    assert _calls(conn, row) == [("stage", 1, "build", "claude", "done"), ("stage", 2, "build", "grok", "done"),
                                 ("stage", 3, "review", "grok", "done"), ("stage", 4, "review", "claude", "done")]
    assert relay.awaiting_pick(row) and chatgpt.prompts == []
    found = relay.candidates(log.calls_for(conn, row["task_id"]), presets.for_task(row, LOADED)[0])
    assert [(c.letter, c.agent, c.reviewer) for c in found] == [("a", "claude", "grok"), ("b", "grok", "claude")]
    lines = []
    assert cli.cmd_pick([str(row["n"]), "b"], conn=conn, loaded=LOADED, out=lines.append) == 0
    assert "picked B (grok), reviewed by claude: PASS" in "\n".join(lines)


# ---------- resume ----------

def test_resume_substitutes_in_the_slot_that_stopped_and_swaps_a_checker_that_would_check_itself(conn):
    stopped = WorkerError("plan limit on chatgpt: You've hit your usage limit", code="plan_limit")
    code, out, row, *_ = _relay(conn, "research-build", [("build", "chatgpt"), ("check", "claude")],
                                bodies={"s1": GOOD_NOTE}, chat=[stopped])
    assert row["status"] == "failed" and "Run: sr resume" in out and "(continues with claude)" in out
    preset = presets.for_task(row, LOADED)[0]
    plan = resume.decide(row, log.calls_for(conn, row["task_id"]), live=ROSTER.live, preset=preset)
    assert (plan.ok, plan.substitute, plan.agent, plan.checker, plan.swapped) == (True, "claude", "claude", "chatgpt", True)


# ---------- fallback (D5) ----------

def _fallback(conn, row, *, bodies=None, claude=(), chat=()):
    hook, worker, chatgpt, clock, lines = RelayHook(**(bodies or {})), Scripted(*claude), Chat(*chat), Clock(), []
    code = cli.cmd_fallback([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                            settings_paths=[], post=hook.post, worker=worker, chatgpt=chatgpt, codex_login=lambda: True,
                            fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True,
                            out=lines.append)
    return code, "\n".join(lines), log.get_task(conn, row["task_id"]), hook, worker, chatgpt


def test_fallback_with_grok_in_build_claude_redoes_and_grok_checks_the_redo(conn):
    code, out, row, *_ = _relay(conn, "research-build", [("build", "grok"), ("check", "claude")],
                                bodies={"s1": GOOD_NOTE, "s2": "R1", "f1": "R2"},
                                claude=["FIX\n1. Name the source.", "FIX\n1. Still no source."])
    assert (row["status"], row["check_state"]) == ("done", "failed")
    assert "Run: sr fallback" in out and "(claude redoes it; grok checks)" in out
    plan = fallback.decide(row, log.calls_for(conn, row["task_id"]), live=ROSTER.live,
                           preset=presets.for_task(row, LOADED)[0])
    assert (plan.ok, plan.doer, plan.checker) == (True, "claude", "grok")
    code, out, row, hook, worker, _ = _fallback(conn, row, bodies={"c1": "PASS"}, claude=["R3, with its source."])
    assert code == 0, out
    calls = log.calls_for(conn, row["task_id"])
    assert [(c["kind"], c["stage"], c["agent"]) for c in calls[-2:]] == [("stage", 2, "claude"), ("check", None, "grok")]
    assert (row["agent"], row["checker"], row["check_state"], row["result"]) == ("claude", "grok", "passed",
                                                                                 "R3, with its source.")


def test_fallback_on_collab_with_grok_as_lead_hands_the_check_stage_back_to_grok(conn):
    unresolved = EDITED.replace("## Unresolved\nnone", "## Unresolved\n- Line two is wrong.")
    code, out, row, *_ = _relay(conn, "collab", [("lead", "grok")], bodies={"s1": PLAN, "s3": DELIVERABLE},
                                chat=[AMENDED, unresolved])
    assert (row["status"], row["check_state"]) == ("done", "failed") and "(chatgpt redoes it; grok checks)" in out
    code, out, row, hook, worker, chatgpt = _fallback(conn, row, bodies={"s4": EDITED}, chat=[DELIVERABLE])
    assert code == 0, out
    calls = log.calls_for(conn, row["task_id"])
    assert [(c["stage"], c["agent"]) for c in calls[-2:]] == [(3, "chatgpt"), (4, "grok")]
    assert worker.prompts == [] and (row["check_state"], row["checker"]) == ("passed", "grok")


def test_no_fallback_when_grok_holds_the_partner_slot(conn):
    unresolved = EDITED.replace("## Unresolved\nnone", "## Unresolved\n- Line two is wrong.")
    code, out, row, *_ = _relay(conn, "collab", [("partner", "grok")], bodies={"s2": AMENDED, "s4": unresolved},
                                claude=[PLAN, DELIVERABLE])
    assert row["check_state"] == "failed" and "No fallback: checker is grok: cannot redo" in out


def test_the_default_fallback_is_unchanged_by_d5():
    preset = LOADED.presets["research-build"]
    row = {"call_id": "x-fb1", "fallback_of": "x-s2", "resume_of": None, "agent": "chatgpt"}
    assert relay._expected_agent(row, "claude", preset) == "chatgpt" == relay.other_builder("claude")
    collab = LOADED.presets["collab"]
    assert relay._expected_agent(row, "claude", collab) == "chatgpt"


# ---------- show, log, list, page ----------

def test_sr_log_and_sr_show_name_a_filled_slot_and_only_a_filled_one(conn, capsys):
    _relay(conn, "versus", [("b", "grok")], bodies={"s2": "B.", "s3": REVIEW}, claude=["A.", REVIEW])
    _relay(conn, "collab", [], claude=[PLAN, DELIVERABLE], chat=[AMENDED, EDITED])
    rows = log.recent_tasks(conn)
    collab_row, versus_row = rows[0], rows[1]
    assert cli._skill_text(versus_row) == "relay:versus b=grok" and cli._skill_text(collab_row) == "relay:collab"
    lines = []
    cli.cmd_show(conn=conn, words=[str(versus_row["n"])], roster=ROSTER, presets=LOADED, out=lines.append)
    assert "Slots: b grok (the rest are the defaults)" in lines
    lines = []
    cli.cmd_show(conn=conn, words=[str(collab_row["n"])], roster=ROSTER, presets=LOADED, out=lines.append)
    assert not any(line.startswith("Slots:") for line in lines)


def test_the_status_page_shows_an_open_filled_task_on_the_card_of_the_agent_in_the_slot(conn):
    code, out, row, *_ = _relay(conn, "versus", [("b", "grok")], claude=["A."], wait=False)
    from router import jsonview, presets  # brief 21, B4: the page reads `working` from sr log --json
    task = log.get_task(conn, row["task_id"])
    assert jsonview.working(task, log.calls_for(conn, row["task_id"]), presets.for_task(task, LOADED)[0]) == {
        "agent": "grok", "doing": "stage 2 of 4 (build), with grok"}


def test_for_task_is_the_one_place_a_tasks_preset_is_built():
    import inspect
    from router import jsonview
    source = inspect.getsource(cli) + inspect.getsource(page) + inspect.getsource(jsonview)
    assert "presets.presets.get(row" not in source and "loaded.presets.get(row" not in source
    assert "loaded.presets[row" not in source


# ---------- search follows the slot ----------

def test_chatgpt_in_the_build_slot_searches_and_grok_in_it_gets_nothing_from_the_router(conn):
    from router import checking
    code, out, row, hook, worker, chatgpt = _relay(conn, "research-build", [("build", "chatgpt"), ("check", "claude")],
                                                   bodies={"s1": GOOD_NOTE}, claude=["PASS"], chat=["Built."])
    build = next(c for c in log.calls_for(conn, row["task_id"]) if c["stage"] == 2)
    assert chatgpt.kwargs[0] == {"web_search": "live"} and checking.SEARCH_LINE in chatgpt.prompts[0]
    assert json.loads(build["search"]) == {"state": "allowed"}
    code, out, row, hook, worker, chatgpt = _relay(conn, "research-build", [("build", "grok")],
                                                   bodies={"s1": GOOD_NOTE, "s2": "Built."}, chat=["PASS"])
    build = next(c for c in log.calls_for(conn, row["task_id"]) if c["stage"] == 2)
    assert build["agent"] == "grok" and build["search"] is None
    assert checking.SEARCH_LINE not in hook.sent[1]["task"]
