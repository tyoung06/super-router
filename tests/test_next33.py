"""Build brief 33, N (decisions 1-7): next-step chips. `## Next` is the agent's optional note at the very end of a
reply: one line in exactly the prompts whose result can be delivered (off a project), read by code like the handoff's
parts, never a contract miss, never judged and never kept as work (taken out before any other call, memory, Save to
project and the word count; the call row keeps the reply as it came). The chips: the router's move (Build from this)
first, then the agent's lines (`## Next`, or a project task's `### Next`), at most 3, duplicates dropped, only on a
delivered task, never a piece. Fakes only; every value here is fake."""
import json

import pytest

from router import __main__ as cli
from router import checking, context, jsonview, log, memory, nextsteps, presets, projnotes, receipt, relay, split
from tests import prompt_snapshot
from tests.helpers import shipped_roster
from tests.test_memory_block import T0, _done

LOADED = presets.load_presets(shipped_roster(), tuple(cli.SENDERS), relay.CONTRACTS, roles=relay.ROLES,
                              verdicts=relay.VERDICTS)
RESULT = "Two free weather APIs:\n- Open-Meteo, 10,000 calls a day.\n- MET Norway, 20 calls a second."
NEXT = "## Next\n- Write a Python script that prints today's forecast from Open-Meteo.\n- Compare their licences."
LINES = ["Write a Python script that prints today's forecast from Open-Meteo.", "Compare their licences."]
SECTION = ("## Handoff\n### Produced\nwrote temps.py: c_to_f\n### Status\nok\n### Next\n"
           "- Add a --round option.\n- Add a test for -40.")


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


# ---------- the reader (decision 5) ----------

def test_the_reader_takes_the_heading_and_its_lines_and_leaves_the_rest():
    rest, lines = checking.split_next(f"{RESULT}\n\n{NEXT}")
    assert rest == RESULT and lines == LINES


@pytest.mark.parametrize("after", ["\n\nSources: https://open-meteo.com", "\n\n## Sources\n- https://open-meteo.com"])
def test_it_ends_at_a_blank_line_after_an_item_or_a_heading_and_what_follows_stays_in_the_reply(after):
    rest, lines = checking.split_next(f"{RESULT}\n\n{NEXT}{after}")
    assert lines == LINES and rest == f"{RESULT}{after}"


def test_list_marks_go_three_lines_at_most_each_cut_at_a_word_to_400_and_at_or_slash_lines_are_dropped():
    long = "Compare " + "the two licences in detail " * 30
    text = (f"{RESULT}\n\n## Next\n1. First move.\n* @claude do it\n/split it\n2) Second move.\n+ {long}\n- Fourth move.")
    _, lines = checking.split_next(text)
    assert lines[:2] == ["First move.", "Second move."] and len(lines) == 3
    assert len(lines[2]) <= 400 and long.startswith(lines[2]) and not lines[2].endswith(" ")
    assert long[len(lines[2])] == " "  # cut at a word


def test_a_heading_in_a_code_fence_is_not_read():
    text = f"{RESULT}\n\n```\n## Next\n- not a move\n```"
    assert checking.split_next(text) == (text, [])


@pytest.mark.parametrize("heading", ["## Next steps", "## Next actions", "### Next", "#### Next"])
def test_only_an_exact_one_or_two_hash_next_heading_is_read(heading):
    text = f"{RESULT}\n\n{heading}\n- Plant the trays."
    assert checking.split_next(text) == (text, [])


@pytest.mark.parametrize("heading", ["# Next", "## next", "## Next:", "##  NEXT  "])
def test_any_case_one_or_two_hashes_and_an_end_colon(heading):
    assert checking.split_next(f"{RESULT}\n\n{heading}\n- Plant the trays.")[1] == ["Plant the trays."]


def test_an_empty_or_missing_section_reads_no_lines():
    assert checking.split_next(RESULT) == (RESULT, [])
    assert checking.split_next(f"{RESULT}\n\n## Next\n") == (RESULT, [])


def test_the_word_count_ends_at_next_but_never_at_next_steps():
    assert checking.word_count(f"{RESULT}\n\n{NEXT}") == checking.word_count(RESULT)
    steps = f"{RESULT}\n\n## Next steps\nPlant the trays."
    assert checking.word_count(steps) == checking.word_count(RESULT) + len("Next steps Plant the trays.".split())


# ---------- never a contract miss (decision 5) ----------

def test_a_revision_with_next_after_answered_meets_its_contract():
    a = relay.AttackList(2, "chatgpt", "A", items=(relay.AttackItem("A1", 1, "high", "x"),))
    revised = f"{RESULT}\n\n## Answered\nnone\n\n{NEXT}"
    assert relay.revision(revised, (a,)) == []
    assert relay.split_answered(revised) == (RESULT, "none")


def test_next_is_never_asked_for_again():
    built = "## Deliverable\nLine one.\n\n## Unfinished\nnone"
    for tail in ("", f"\n\n{NEXT}", "\n\n## Next\n", "\n\n## Next\n@claude go", "\n\n## Next\n" + "x" * 900):
        assert relay.contract_check("deliverable")(built + tail) == []


# ---------- which prompts ask for it (decision 5) ----------

def _routed(skill="writing", project=None, mode="route", preset=None):
    return {"task_id": "sr-x", "mode": mode, "skill": skill, "project": project, "parent": None, "preset": preset,
            "slots": None}


@pytest.mark.parametrize("skill", ["writing", "research", "code", "planning", "follow_up"])
def test_a_routed_doer_and_its_fix_rounds_ask_for_it_off_a_project(skill):
    for kind in ("do", "fix"):
        assert nextsteps.asks_next(_routed(skill), kind)
        assert not nextsteps.asks_next(_routed(skill, project="demo"), kind)


@pytest.mark.parametrize("skill", ["quick_answer", "recall", "make_media"])
def test_never_on_a_quick_answer_a_recall_or_a_media_task(skill):
    assert not nextsteps.asks_next(_routed(skill), "do") and not nextsteps.asks_next(_routed(skill), "fix")


@pytest.mark.parametrize("preset, role, asks", [
    ("research-build", "research", False), ("research-build", "build", True),
    ("redteam", "build", False), ("redteam", "attack", False), ("redteam", "revise", True),
    ("versus", "build", True), ("versus", "review", False), ("vote", "vote", False),
    ("collab", "plan", False), ("collab", "amend", False), ("collab", "execute", False), ("collab", "edit", False)])
def test_a_stage_asks_only_when_its_result_is_delivered(preset, role, asks):
    task = _routed(None, mode="relay", preset=preset)
    assert nextsteps.asks_next(task, "stage", role=role) is asks
    assert nextsteps.asks_next(task, "reask", role=role) is asks
    assert not nextsteps.asks_next({**task, "project": "demo"}, "stage", role=role)


def test_a_split_asks_on_its_integration_alone_and_a_piece_never():
    task = _routed(None, mode="split")
    assert nextsteps.asks_next(task, "stage", role=split.INTEGRATE_ROLE)
    assert not nextsteps.asks_next(task, "stage", role=split.PLAN_ROLE)
    piece = {**_routed("writing"), "parent": "sr-split"}
    assert not nextsteps.asks_next(piece, "do") and not nextsteps.asks_next(piece, "fix")


def test_a_fallback_redo_asks_and_a_check_never():
    assert nextsteps.asks_next(_routed(), "redo") and not nextsteps.asks_next(_routed(project="demo"), "redo")
    for preset in ("research-build", "redteam"):
        assert nextsteps.asks_next(_routed(None, mode="relay", preset=preset), "redo")
    # collab's redo is of its build stage, whose result goes to the edit stage: the edit is what is delivered
    assert not nextsteps.asks_next(_routed(None, mode="relay", preset="collab"), "redo")
    assert not nextsteps.asks_next(_routed(), "check") and not nextsteps.asks_next(_routed(), "recheck")


def _with_next(prompt):
    return prompt.endswith("\n\n" + checking.NEXT_LINE) and prompt.count(checking.NEXT_LINE) == 1


def test_the_snapshot_has_the_line_on_exactly_the_delivering_prompts():
    found = prompt_snapshot.snapshot(LOADED)
    asked = {key for key, value in found.items() if checking.NEXT_LINE in value["prompt"]}
    want = {key for key in found if key.rsplit("/", 1)[-1] in ("do", "fix") and key.startswith(("writing", "web"))} | {
        key for key in found if key.startswith(("research-build/2-build/", "versus/1-build/", "versus/2-build/"))} | {
        "split/2-integrate"}  # versus: both candidates' builds
    assert asked == want
    assert all(_with_next(found[key]["prompt"]) for key in want)


# ---------- taken out before any other call, memory and Save (decision 6) ----------

def _open_after_do(conn, text, *, check=None):
    """A routed task still open after its do call (and a check, when given): what the next step plans from."""
    log.add_task(conn, "sr-1", "Find two weather APIs.", "cli", {"status": "ok", "label": "research", "confidence": 0.9,
                                                                 "tokens": 0}, chat="wx", now=T0)
    log.set_route(conn, "sr-1", agents=("claude", "chatgpt"), agent="claude", route_reason="best", skill="research",
                  checker="chatgpt", check_state="pending")
    log.add_call(conn, "sr-1", "sr-1", "do", "claude", status="done", text=text, now=T0)
    if check:
        log.add_call(conn, "sr-1-c1", "sr-1", "check", "chatgpt", status="done", text=check, verdict="FIX", now=T0)
    row = log.get_task(conn, "sr-1")
    return row, log.calls_for(conn, "sr-1")


@pytest.mark.parametrize("check, action", [(None, "check"), ("FIX\n1. [must] Name each rate limit's source.", "fix")])
def test_the_check_and_the_fix_round_get_the_result_without_it(conn, check, action):
    row, calls = _open_after_do(conn, f"{RESULT}\n\n{NEXT}", check=check)
    step = checking.next_step(row, calls)
    assert step.action == action
    _, _, _, prompt, _ = cli._plan_call(row, step, calls)
    assert NEXT not in prompt and LINES[0] not in prompt and LINES[1] not in prompt and RESULT in prompt
    assert (checking.NEXT_LINE in prompt) is (action == "fix")  # the fix round's own result can be delivered


def test_memory_and_save_to_project_keep_it_out(conn):
    row = _done(conn, "sr-1", "Find two weather APIs.", f"{RESULT}\n\n{NEXT}", chat="wx")
    calls = log.calls_for(conn, "sr-1")  # content_of is the one text the retain stores and a block's entry shows
    item = memory.item_for(row, calls, memory.content_of(row, calls))
    assert "## Next" not in json.dumps(item) and LINES[0] not in json.dumps(item) and RESULT in item["content"]
    assert projnotes.delivered_text(row) == RESULT + "\n"  # the saved file ends with a newline, as before


def test_the_integration_never_sees_a_pieces_next():
    block = split.pieces_block([{"id": "p1", "text": "one", "result": f"{RESULT}\n\n{NEXT}"}], "Join them.")
    assert "## Next" not in block and RESULT in block


# ---------- the chips (decisions 2-4 and 7) ----------

def _chips(conn, row):
    return nextsteps.chips(conn, log.get_task(conn, row["task_id"]), log.calls_for(conn, row["task_id"]))


def test_build_from_this_first_then_the_agents_lines_in_order(conn):
    row = _done(conn, "sr-1", "Find two weather APIs.", f"{RESULT}\n\n{NEXT}", chat="wx")
    chips = _chips(conn, row)
    assert [(c["kind"], c["words"]) for c in chips] == [("build_from", f"Build from #{row['n']}"),
                                                        ("agent", LINES[0]), ("agent", LINES[1])]
    assert chips[0]["fill"] == {"team": "route", "project": None, "chat": "wx", "text": "", "from": "sr-1", "idea": None,
                                "step": None}  # brief 33.1: a fill names its Step pill (none here)
    assert chips[1]["fill"] == {"team": "route", "project": None, "chat": "wx", "text": LINES[0], "from": "sr-1",
                                "idea": None, "step": None}
    assert not any(c["later"] for c in chips)  # a chat has no Ideas list


def test_at_most_three_and_a_line_like_an_earlier_one_is_dropped(conn):
    text = f"{RESULT}\n\n## Next\n- Build from #1\n- Compare their licences.\n- compare their licences\n- Map them."
    row = _done(conn, "sr-1", "Find two weather APIs.", text, chat="wx")  # the reader keeps 3 lines; then 2 match others
    assert [c["words"] for c in _chips(conn, row)] == ["Build from #1", "Compare their licences."]
    text = f"{RESULT}\n\n## Next\n- Map them.\n- Compare their licences.\n- Chart them."
    row = _done(conn, "sr-2", "Find two weather APIs.", text, chat="wx")
    assert [c["words"] for c in _chips(conn, row)] == ["Build from #2", "Map them.", "Compare their licences."]


@pytest.mark.parametrize("skill", ["quick_answer", "recall", "make_media"])
def test_build_from_this_is_never_offered_on_a_quick_answer_a_recall_or_a_media_task(conn, skill):
    row = _done(conn, "sr-1", "What is 2+2?", f"4.\n\n{NEXT}", chat="wx", skill=skill, check_state="not_needed")
    assert all(c["kind"] != "build_from" for c in _chips(conn, row))


def test_a_forgotten_task_offers_no_build_from_and_its_chips_carry_no_from(conn):
    row = _done(conn, "sr-1", "Find two weather APIs.", f"{RESULT}\n\n{NEXT}", chat="wx")
    assert cli.cmd_forget([str(row["n"])], conn=conn, undo=False, client=None, out=receipt.Receipt()) == 0
    chips = _chips(conn, row)
    assert [c["kind"] for c in chips] == ["agent", "agent"] and all(c["fill"]["from"] is None for c in chips)


def test_a_project_tasks_chips_are_its_handoff_next_lines_with_later_and_no_from(conn):
    row = _done(conn, "sr-1", "Add c_to_f.", "Added c_to_f.", chat=None, project="demo",
                do_text=f"Added c_to_f.\n\n{SECTION}")
    chips = _chips(conn, row)
    # brief 33.1 (decision 18): on a project with no current plan, Plan from this comes first, then Build from this
    assert [(c["kind"], c["words"], c["later"]) for c in chips] == [
        ("plan_from", f"Plan from #{row['n']}", False), ("build_from", f"Build from #{row['n']}", False),
        ("agent", "Add a --round option.", True)]
    assert chips[2]["fill"] == {"team": "route", "project": "demo", "chat": None, "text": "Add a --round option.",
                                "from": None, "idea": None, "step": None}


@pytest.mark.parametrize("change", ["failed_check", "stopped", "blocked", "cancelled", "waiting", "discarded", "undone"])
def test_no_chips_on_a_card_that_was_not_delivered(conn, change):
    row = _done(conn, "sr-1", "Add c_to_f.", "Added c_to_f.", chat=None, project="demo",
                do_text=f"Added c_to_f.\n\n{SECTION}", check_state="failed" if change == "failed_check" else "passed")
    if change in ("stopped", "blocked", "cancelled"):
        conn.execute("UPDATE tasks SET status = ?, check_state = ? WHERE task_id = 'sr-1'",
                     ("cancelled" if change == "cancelled" else "failed", log.BLOCKED if change == "blocked" else "passed"))
    if change in ("waiting", "discarded", "undone"):
        log.set_project_files(conn, "sr-1", {"state": change, "paths": ["temps.py"]})
    assert _chips(conn, row) == []


def test_a_landed_change_is_delivered(conn):
    row = _done(conn, "sr-1", "Add c_to_f.", "Added c_to_f.", chat=None, project="demo",
                do_text=f"Added c_to_f.\n\n{SECTION}")
    log.set_project_files(conn, "sr-1", {"state": "landed", "paths": ["temps.py"]})
    assert [c["kind"] for c in _chips(conn, row)] == ["plan_from", "build_from", "agent"]  # brief 33.1 (decision 18)


def test_never_on_a_piece(conn):
    row = _done(conn, "sr-1", "Find two weather APIs.", f"{RESULT}\n\n{NEXT}", chat="wx")
    conn.execute("UPDATE tasks SET parent = 'sr-split' WHERE task_id = 'sr-1'")
    assert _chips(conn, row) == []


# ---------- the JSON (decision 18) ----------

def test_the_json_gives_next_and_the_result_without_its_section(conn):
    row = _done(conn, "sr-1", "Find two weather APIs.", f"{RESULT}\n\n{NEXT}", chat="wx")
    view = jsonview.task_view(conn, log.get_task(conn, "sr-1"))
    assert view["result"] == RESULT and [c["words"] for c in view["next"]] == [f"Build from #{row['n']}", *LINES]
    assert log.get_task(conn, "sr-1")["result"] == f"{RESULT}\n\n{NEXT}"  # the stored result is unchanged


def test_sr_show_prints_the_lines_under_next(conn):
    _done(conn, "sr-1", "Find two weather APIs.", f"{RESULT}\n\n{NEXT}", chat="wx")
    lines = []
    cli.cmd_show(conn=conn, words=["1"], out=lines.append)
    text = "\n".join(lines)
    assert "## Next" not in text and "Next:" in text and all(f"  {line}" in text for line in LINES)
