"""Build brief 18, phase C (rules v2.25, Project context, "What comes back"): the `handoff` contract on the build
call's result: `## Handoff` with `### Produced` (1+ lines), `### Status` (1+), `### Next` (1 to 3). Applied to the
doer on a routed task, the last stage before the checker on research-build and redteam, the fix round, the
substitute on a resume and the fallback doer; never when that agent is Grok. One re-ask naming the missing parts;
still missing, the task stops as any contract miss. Fake agents only; every secret here is fake."""
from pathlib import Path

import pytest

from router import __main__ as cli
from router import checking, context, log, projects, relay
from tests.helpers import fake_label, set_local
from tests.test_collab import LOADED
from tests.test_context import ATTACKS, BUILT, HANDOFF_TEXT, TASK, _block, _relay, _route
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_relay import CONFIG, GOOD_NOTE, ROSTER, Chat, RelayHook
from tests.test_resume_run import WRITING, claude_limit

HANDOFF = "## Handoff\n### Produced\nnothing written: ## Lines, the two lines\n### Status\nthe two lines exist\n### Next\nadd a third line"
GOOD = "Line one.\nLine two.\n\n" + HANDOFF
NO_NEXT = "Line one.\n\n## Handoff\n### Produced\nnothing written: ## Lines, the two lines\n### Status\nfine"
FOUR_NEXT = GOOD + "\nb\nc\nd"
REVISED_BOTH = "Line one, fixed.\nLine two.\n\n## Answered\n2 the task asked for dull lines\n\n" + HANDOFF
REVISED_HANDOFF_FIRST = "Line one, fixed.\nLine two.\n\n" + HANDOFF + "\n\n## Answered\n2 the task asked for dull lines"


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "config" / "projects.json")
    set_local(never_register=[str(tmp_path / "home" / "Projects" / "off-limits")])  # brief 25: a fake never_register folder
    folder = tmp_path / "demo"
    folder.mkdir()
    (folder / "HANDOFF.md").write_text(HANDOFF_TEXT)
    projects.add("demo", str(folder))
    return folder


# ---------- the contract, pure ----------

def test_a_complete_section_passes_and_its_parts_are_read():
    assert context.handoff_missing(GOOD) == []
    parts = context.handoff_parts(context.split_handoff(GOOD)[1])
    assert parts == {"produced": ["nothing written: ## Lines, the two lines"], "status": ["the two lines exist"], "next": ["add a third line"]}


def test_a_missing_section_is_named():
    assert context.handoff_missing("Line one.") == ["Handoff: section `## Handoff` is missing"]
    assert context.handoff_missing("") == ["Handoff: section `## Handoff` is missing"]


def test_each_missing_part_is_named_exactly():
    assert context.handoff_missing(NO_NEXT) == ["Handoff: `### Next` needs 1 to 3 lines, found 0"]
    assert context.handoff_missing(FOUR_NEXT) == ["Handoff: `### Next` needs 1 to 3 lines, found 4; the lines past the third: `d`"]
    five = GOOD + "\nb\nc\nd\n" + "x" * 70
    assert context.handoff_missing(five) == ["Handoff: `### Next` needs 1 to 3 lines, found 5; the lines past the third: "
                                             f"`d`, `{'x' * 60}`"]


def test_a_part_ends_at_its_first_blank_line_so_a_trailer_after_next_is_not_next():
    text = GOOD + "\n\nSources:\n- https://a.example\n- https://b.example"
    assert context.handoff_missing(text) == []
    parts = context.handoff_parts(context.split_handoff(text)[1])
    assert parts["next"] == ["add a third line"] and context.raw_parts(context.split_handoff(text)[1])["next"] == ["add a third line"]
    spaced = "x\n\n## Handoff\n### Produced\n\np\n### Status\ns\n\nmore status\n### Next\nn"
    assert context.handoff_parts(context.split_handoff(spaced)[1]) == {"produced": ["p"], "status": ["s"], "next": ["n"]}


LIVE3_FIX = (Path(__file__).parent / "fixtures" / "brief18_live3_fix.md").read_text()


def test_live_3s_stored_fix_text_now_passes_the_contract_and_the_loop(project, conn):
    """Brief 18 Phase F, #3: Claude's fix round put `Sources:` and two links after `### Next`; the literal count read 5
    and the fix round failed twice. Replayed here as a fake agent: the Next part passes. Rules v2.27 (brief 19): its
    `Produced` reads `Nothing written. The deliverable is the inline answer: …`, a bare nothing-written line, so that
    is now the one miss; with the named form (`nothing written: …`) the fix passes, the task ends `fixed`, and the
    entry carries the two Next lines only."""
    assert "Sources:" in LIVE3_FIX.split("### Next")[1]
    assert context.handoff_missing(LIVE3_FIX) == [context.PRODUCED_REASK]
    named = LIVE3_FIX.replace("Nothing written. The deliverable is the inline answer:", "nothing written: the inline answer,", 1)
    assert context.handoff_missing(named) == []
    worker, chat = Scripted(GOOD, named), Chat("FIX\n1. name the inline deliverable under Produced", "PASS")
    code, out, row, _ = _route(conn, project="demo", worker=worker, chatgpt=chat)
    assert code == 0 and row["check_state"] == "fixed", out
    assert len(worker.prompts) == 2 and "missed its contract" not in out
    assert row["result"] == named.split("\n\n## Handoff")[0]
    entry = log.handoff_of(log.get_task(conn, row["task_id"]))[0]["text"]
    assert entry.endswith("Next:\n- Say whether you want `main.py` and `requirements.txt` scaffolded in the workspace.\n"
                          "- Supply the labels that #1 and #2 are waiting on.")
    assert "Sources" not in entry
    empty = "x\n\n## Handoff\n### Produced\n### Status\n### Next\n"
    assert context.handoff_missing(empty) == ["Handoff: `### Produced` needs at least 1 line, found 0",
                                              "Handoff: `### Status` needs at least 1 line, found 0",
                                              "Handoff: `### Next` needs 1 to 3 lines, found 0"]


def test_headings_match_any_case_one_or_two_hashes_and_a_colon():
    text = "x\n\n# HANDOFF:\n### produced\np\n### Status:\ns\n### NEXT\nn"
    assert context.handoff_missing(text) == []


def test_a_handoff_heading_inside_a_code_fence_is_not_a_section():
    text = "x\n\n```\n## Handoff\n### Produced\np\n### Status\ns\n### Next\nn\n```\n"
    assert context.handoff_missing(text) == ["Handoff: section `## Handoff` is missing"]
    assert context.split_handoff(text) == (text, None)


def test_split_handoff_cuts_the_section_off_and_stops_at_the_next_note_heading():
    rest, section = context.split_handoff(REVISED_HANDOFF_FIRST)
    assert section == HANDOFF
    assert rest == "Line one, fixed.\nLine two.\n\n## Answered\n2 the task asked for dull lines"
    rest, section = context.split_handoff(REVISED_BOTH)
    assert section == HANDOFF and rest == "Line one, fixed.\nLine two.\n\n## Answered\n2 the task asked for dull lines"


def test_the_revision_contract_and_the_handoff_contract_both_pass_in_either_order():
    for text in (REVISED_BOTH, REVISED_HANDOFF_FIRST):
        assert relay.revision(text, ATTACKS) == [] and context.handoff_missing(text) == []
    assert relay.split_answered(context.split_handoff(REVISED_HANDOFF_FIRST)[0])[1] == "2 the task asked for dull lines"


def test_the_word_count_excludes_the_handoff_section():
    assert checking.word_count(GOOD) == checking.word_count("Line one.\nLine two.") == 4
    assert checking.word_count(REVISED_HANDOFF_FIRST) == 5


def test_who_needs_the_contract(conn):
    log.add_task(conn, "sr-p", TASK, "cli", WRITING, project="demo")
    log.add_task(conn, "sr-n", TASK, "cli", WRITING)
    assert context.needs_handoff(log.get_task(conn, "sr-p"), "claude") is True
    assert context.needs_handoff(log.get_task(conn, "sr-p"), "grok") is False
    assert context.needs_handoff(log.get_task(conn, "sr-n"), "claude") is False


# ---------- the build line in the prompts ----------

def test_the_doer_prompt_ends_with_the_build_line_before_the_handoff_block(project, conn):
    worker = Scripted(GOOD)
    code, out, row, _ = _route(conn, project="demo", worker=worker, chatgpt=Chat("PASS"))
    assert code == 0, out
    assert worker.prompts[0] == f"{TASK}\n\n{context.HANDOFF_LINE}\n\n" + _block(HANDOFF_TEXT.rstrip("\n"))


def test_the_build_line_wording_is_decision_6():
    assert context.HANDOFF_LINE == (
        "End your result with a section `## Handoff` containing `### Produced` (what this result made and where it is: "
        "a path under the task folder, `sr show <n>`, or the words `nothing written`), `### Status` (where the project "
        "stands after this task, one or two lines), `### Next` (one to three lines). Keep it short; it goes into the "
        "project's handoff file. The `## Handoff` section is the last thing in your result; put sources in the "
        "deliverable, never after it. If nothing was written to disk, write `nothing written:` followed by the exact "
        "heading or first line of what the result contains and one clause on what it holds.")


def test_the_research_build_build_prompt_and_the_redteam_revise_prompt_carry_the_line(project, conn):
    worker = Scripted(GOOD)
    code, out, row, hook = _relay(conn, "research-build", project="demo", worker=worker, chatgpt=Chat("PASS"))
    assert code == 0, out
    assert worker.prompts[0].startswith(relay.build_prompt(TASK, GOOD_NOTE).split("\n\n===== RESEARCH NOTE")[0])
    assert f"\n\n{context.HANDOFF_LINE}\n\n===== RESEARCH NOTE =====" in worker.prompts[0]
    assert "Research this." in hook.sent[0]["task"] and context.HANDOFF_LINE not in hook.sent[0]["task"]
    worker = Scripted(BUILT, REVISED_BOTH)
    code, out, row, hook = _relay(conn, "redteam", project="demo", worker=worker, chatgpt=Chat(ATTACKS, "PASS"))
    assert code == 0, out
    assert context.HANDOFF_LINE not in worker.prompts[0]  # stage 1 builds under the deliverable contract; stage 3 is the build call
    assert f"{relay.REVISE_REPLY}\n\n{context.HANDOFF_LINE}\n\n" in worker.prompts[1]  # after the ## Answered instruction


def test_the_fix_prompt_carries_the_line_after_the_reply_line(project, conn):
    worker, chat = Scripted(GOOD, GOOD.replace("Line two.", "Line two, fixed.")), Chat("FIX\n1. fix line two", "PASS")
    code, out, row, _ = _route(conn, project="demo", worker=worker, chatgpt=chat)
    assert code == 0 and row["check_state"] == "fixed", out
    assert f"{checking.FIX_REPLY_LINE}\n\n{context.HANDOFF_LINE}\n\n" in worker.prompts[1]
    assert worker.prompts[1].index(context.HANDOFF_LINE) < worker.prompts[1].index("===== TASK =====")


def test_a_prompt_without_a_project_has_no_line(conn):
    worker = Scripted("two lines")
    _route(conn, worker=worker, chatgpt=Chat("PASS"))
    assert context.HANDOFF_LINE not in worker.prompts[0]


# ---------- the routed doer: one re-ask, then a stop ----------

def test_a_doer_result_without_the_section_is_re_asked_once_naming_the_missing_parts(project, conn):
    worker, chat = Scripted("Line one.\nLine two.", GOOD), Chat("PASS")
    code, out, row, _ = _route(conn, project="demo", worker=worker, chatgpt=chat)
    assert code == 0 and row["status"] == "done" and row["check_state"] == "passed", out
    assert f"The first call by claude missed its contract; re-asked once for: Handoff: section `## Handoff` is missing." in out
    reask = worker.prompts[1]
    assert reask.startswith("Your earlier result below misses part of what was asked.")
    assert "- Handoff: section `## Handoff` is missing" in reask and context.HANDOFF_LINE in reask
    assert "===== TASK =====\n" + TASK in reask and "===== YOUR EARLIER RESULT =====\nLine one.\nLine two." in reask
    assert reask.endswith("\n\n" + _block(HANDOFF_TEXT.rstrip("\n")))
    calls = [(c["call_id"].removeprefix(row["task_id"]) or "<id>", c["kind"], c["agent"]) for c in log.calls_for(conn, row["task_id"])]
    assert calls == [("<id>", "do", "claude"), ("-dr", "do", "claude"), ("-c1", "check", "chatgpt")]
    assert GOOD in chat.prompts[0] and "Line one.\nLine two.\n=====" not in chat.prompts[0]  # the re-ask's text is checked


def test_a_doer_still_missing_after_the_re_ask_stops_the_task(project, conn):
    worker, chat = Scripted("Line one.", NO_NEXT), Chat("PASS")
    code, out, row, _ = _route(conn, project="demo", worker=worker, chatgpt=chat)
    assert code == 1 and row["status"] == "failed" and chat.prompts == []
    assert row["result"] == "contract still missing after the re-ask: Handoff: `### Next` needs 1 to 3 lines, found 0"
    assert f"{row['task_id']} failed: contract still missing after the re-ask: Handoff: `### Next` needs 1 to 3 lines, found 0" in out


def test_a_grok_doer_result_without_the_section_is_not_re_asked(project, conn):
    hook = Webhook(do="Three posts about trays.", c1="PASS")
    code, out, row, _ = _route(conn, project="demo", jev={**WRITING, "label": "x_social_pulse"}, hook=hook,
                               chatgpt=Chat("PASS"))
    assert code == 0 and row["status"] == "done", out
    assert [c["kind"] for c in log.calls_for(conn, row["task_id"])] == ["do", "check"]
    assert context.HANDOFF_LINE not in hook.sent[0]["task"]


def test_a_routed_task_without_a_project_is_never_re_asked(conn):
    worker, chat = Scripted("Line one."), Chat("PASS")
    code, out, row, _ = _route(conn, worker=worker, chatgpt=chat)
    assert code == 0 and [c["kind"] for c in log.calls_for(conn, row["task_id"])] == ["do", "check"]


# ---------- the relay build stage ----------

def test_research_build_stage_2_without_the_section_is_re_asked_with_the_handoff_shape(project, conn):
    worker = Scripted("built from the note", GOOD)
    code, out, row, hook = _relay(conn, "research-build", project="demo", worker=worker, chatgpt=Chat("PASS"))
    assert code == 0 and row["status"] == "done", out
    assert "Stage 2 (build by claude) missed its contract; re-asked once for: Handoff: section `## Handoff` is missing." in out
    assert context.HANDOFF_LINE in worker.prompts[1] and "- Handoff: section `## Handoff` is missing" in worker.prompts[1]
    assert [(c["call_id"][-3:], c["kind"]) for c in log.calls_for(conn, row["task_id"])][:3] == [
        ("-s1", "stage"), ("-s2", "stage"), ("s2r", "reask")]


def test_research_build_stage_2_still_missing_stops_the_chain(project, conn):
    worker = Scripted("built", "built again")
    code, out, row, hook = _relay(conn, "research-build", project="demo", worker=worker, chatgpt=Chat("PASS"))
    assert code == 1 and row["status"] == "failed" and row["failed_stage"] == 2
    assert "contract still missing after the re-ask: Handoff: section `## Handoff` is missing" in row["result"]


def test_a_grok_build_slot_is_never_asked_for_the_section(project, conn):
    hook = RelayHook(s1=GOOD_NOTE, s2="built by grok", c1="PASS")
    code, out, row, hook = _relay(conn, "research-build", project="demo", hook=hook, slots=[("build", "grok")],
                                  chatgpt=Chat("PASS"))
    assert code == 0 and row["status"] == "done", out
    assert context.HANDOFF_LINE not in hook.sent[1]["task"]
    assert [c["kind"] for c in log.calls_for(conn, row["task_id"])] == ["stage", "stage", "check"]


def test_redteam_stage_3_is_read_with_both_contracts(project, conn):
    worker = Scripted(BUILT, "Line one, fixed.\n\n## Answered\nnone", REVISED_HANDOFF_FIRST)
    code, out, row, hook = _relay(conn, "redteam", project="demo", worker=worker, chatgpt=Chat(ATTACKS, "PASS"))
    assert code == 0 and row["status"] == "done", out
    assert "Stage 3 (revise by claude) missed its contract; re-asked once for: Handoff: section `## Handoff` is missing." in out
    assert f"{relay.REVISE_REPLY}\n\n{context.HANDOFF_LINE}" in worker.prompts[2]  # the re-ask asks for both shapes
    assert row["result"] == "Line one, fixed.\nLine two."  # neither note section is the deliverable


def test_redteam_stage_1_is_not_a_build_call_for_the_handoff(project, conn):
    worker = Scripted(BUILT, REVISED_BOTH)
    code, out, row, hook = _relay(conn, "redteam", project="demo", worker=worker, chatgpt=Chat(ATTACKS, "PASS"))
    assert code == 0 and "Stage 1" not in out


# ---------- the fix round ----------

def test_a_fix_without_the_section_is_re_asked_then_fails_as_brief_16_built(project, conn):
    worker = Scripted(GOOD, "Line one, fixed.\nLine two.", "Line one, fixed again.")
    chat = Chat("FIX\n1. fix line one", "PASS")
    code, out, row, _ = _route(conn, project="demo", worker=worker, chatgpt=chat)
    assert code == 5 and row["check_state"] == "failed", out
    assert "The fix round by claude missed its contract; re-asked once for: Handoff: section `## Handoff` is missing." in out
    reask = worker.prompts[2]
    assert context.HANDOFF_LINE in reask and relay.REVISE_REPLY not in reask  # no attack list on a routed task
    assert row["check_note"] == "fix round by claude failed its contract after the re-ask: Handoff: section `## Handoff` is missing"
    assert len(chat.prompts) == 1  # no re-check
    kinds = [(c["call_id"].removeprefix(row["task_id"]), c["kind"]) for c in log.calls_for(conn, row["task_id"])]
    assert kinds == [("", "do"), ("-c1", "check"), ("-f1", "fix"), ("-f1r", "fix")]


def test_a_redteam_fix_re_ask_asks_for_both_shapes(project, conn):
    worker = Scripted(BUILT, REVISED_BOTH, "Line one, fixed twice.\n\n## Answered\nnone", REVISED_BOTH)
    chat = Chat(ATTACKS, "FIX\n1. attack 1 is not fixed", "PASS")
    code, out, row, hook = _relay(conn, "redteam", project="demo", worker=worker, chatgpt=chat)
    assert code == 0 and row["check_state"] == "fixed", out
    assert f"{relay.REVISE_REPLY}\n\n{context.HANDOFF_LINE}" in worker.prompts[3]


# ---------- resume and fallback ----------

def test_the_substitutes_prompt_carries_the_line_and_its_result_is_read_with_the_contract(project, conn):
    code, out, row, _ = _route(conn, project="demo", worker=Scripted(claude_limit()))
    lines, clock, hook, chat = [], Clock(), Webhook(), Chat("two lines, no section", GOOD)
    code = cli.cmd_resume([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                          settings_paths=[], post=hook.post, worker=Scripted("PASS"), chatgpt=chat,
                          codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                          wait=True, out=lines.append)
    assert code == 0, "\n".join(lines)
    assert context.HANDOFF_LINE in chat.prompts[0] and "- Handoff: section `## Handoff` is missing" in chat.prompts[1]
    after = log.get_task(conn, row["task_id"])
    assert after["status"] == "done" and after["result"] == "Line one.\nLine two."  # phase D: the section is not the result
    assert log.get_call(conn, f"{row['task_id']}-dr")["text"] == GOOD


def test_the_fallback_doers_prompt_carries_the_line_and_its_result_is_read_with_the_contract(project, conn):
    worker, chat = Scripted(GOOD, GOOD), Chat("FIX\n1. rhyme", "FIX\n1. still no rhyme")
    code, out, row, _ = _route(conn, project="demo", worker=worker, chatgpt=chat)
    assert row["check_state"] == "failed"
    lines, clock, hook, redo = [], Clock(), Webhook(), Chat("REDO without a section", "REDO\n\n" + HANDOFF)
    code = cli.cmd_fallback([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                            settings_paths=[], post=hook.post, worker=Scripted("PASS"), chatgpt=redo,
                            codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep,
                            clock=clock, wait=True, out=lines.append)
    assert code == 0, "\n".join(lines)
    assert context.HANDOFF_LINE in redo.prompts[0] and redo.prompts[0].index(context.HANDOFF_LINE) < redo.prompts[0].index("===== FIX LIST =====")
    assert "- Handoff: section `## Handoff` is missing" in redo.prompts[1]
    after = log.get_task(conn, row["task_id"])
    assert after["status"] == "done" and after["check_state"] == "passed" and after["result"] == "REDO"
    assert log.get_call(conn, f"{row['task_id']}-fb1-dr")["text"] == "REDO\n\n" + HANDOFF
