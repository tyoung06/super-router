"""Brief 30, decisions 3 to 6 (rules 2.43, Router notes): the notes on every call. Read once at intake (refused before any
row when invalid), kept with the task, sent first in every agent call's prompt from that copy: `## All agents` and the
calling agent's own section; the judge line on a check, re-check, review or attack; `## Planner` on a split's plan call
and its re-ask; never Jev; a takeover's and a substitute's own section; on Grok, memory first, then the notes whole, then
the handoff. Through the real main with every outside thing faked; every value here is fake."""
import json

import pytest

from router import __main__ as cli
from router import checking, context, cursor_worker, log, notes, rounds
from tests.helpers import fake_label
from tests.test_json_actions import World, jev
from tests.test_loop import Scripted, Webhook
from tests.test_relay import Chat
from tests.test_resume_run import claude_limit
from tests.helpers import less_next

NOTES = ("## All agents\nUse metric units for distances.\n\n## Claude\nKeep answers under 80 words.\n\n"
         "## ChatGPT\nWhen you check, keep each item to one sentence.\n\n## Grok\nSay which X accounts you read.\n\n"
         "## Cursor\nUse only Python's standard library.\n\n## Planner\nFor a yes-or-no question, use vote.\n")
ALL, CLAUDE, CHATGPT = "Use metric units for distances.", "Keep answers under 80 words.", \
    "When you check, keep each item to one sentence."
GROK, CURSOR, PLANNER = "Say which X accounts you read.", "Use only Python's standard library.", \
    "For a yes-or-no question, use vote."
POEM = "write a two-line poem about rubber trays"


def block(own, *, judge=False, planner=False, shared=ALL):
    parts = ["\n".join([notes.LEAD, notes.OPEN, *([shared] if shared else []), *([""] if shared and own else []),
                        *([own] if own else []), notes.CLOSE])]
    if judge:
        parts.append(notes.JUDGE_LINE)
    if planner:
        parts.append("\n".join([notes.PLANNER_LEAD, notes.PLANNER_OPEN, PLANNER, notes.PLANNER_CLOSE]))
    return "\n\n".join(parts) + "\n\n"


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    w = World(monkeypatch, tmp_path, capsys)
    w.hook = Webhook()
    return w


def _calls(world, n=1):
    conn = log.init_db(cli.DB_PATH)
    try:
        row = log.task_by_number(conn, n)
        return row, log.calls_for(conn, row["task_id"])
    finally:
        conn.close()


# ---------- the words (decision 5) ----------

def test_the_words_are_decision_5s():
    assert notes.LEAD == ("Notes from the person who sent this task, kept for every task they send. They are part of this "
                          "message: follow them where they fit this task. The task, the instructions after these notes and "
                          "the reply format win any conflict.")
    assert (notes.OPEN, notes.CLOSE) == ("--- notes ---", "--- end of notes ---")
    assert notes.JUDGE_LINE == ("When you judge another agent's work, not following the person's notes is never on its own "
                                "a [must], a fail or a [high] attack; mention it as a [note] at most. The notes above were "
                                "written for you; the agent you judge had its own.")
    assert notes.PLANNER_LEAD == ("How the person likes a task split and its teams picked. The menu and its rules win any "
                                  "conflict: never a team the menu doesn't offer.")
    assert (notes.PLANNER_OPEN, notes.PLANNER_CLOSE) == ("--- planner notes ---", "--- end of planner notes ---")
    assert notes.GROK_LEFT_OUT == "Grok: router notes left out (over its limit)"


def test_one_part_alone_when_the_other_is_empty():
    assert notes.part_for({"claude": "c"}, "claude")[0] == "\n".join([notes.LEAD, notes.OPEN, "c", notes.CLOSE]) + "\n\n"
    assert notes.part_for({"all_agents": "a"}, "grok")[0] == "\n".join([notes.LEAD, notes.OPEN, "a", notes.CLOSE]) + "\n\n"
    assert notes.part_for({"all_agents": "a", "claude": "c"}, "chatgpt")[0] == (
        "\n".join([notes.LEAD, notes.OPEN, "a", notes.CLOSE]) + "\n\n")
    planner_only = notes.part_for({"planner": "p"}, "claude", plan=True)
    assert planner_only[0] == (notes.LEAD + "\n\n" + "\n".join([notes.PLANNER_LEAD, notes.PLANNER_OPEN, "p",
                                                              notes.PLANNER_CLOSE]) + "\n\n")
    assert notes.part_for({"planner": "p"}, "claude", plan=False) == ("", None)  # the planner part is the plan call's
    assert notes.part_for({"claude": "c"}, "claude", judge=True)[0].endswith(notes.JUDGE_LINE + "\n\n")
    assert notes.part_for({"chatgpt": "x"}, "claude", judge=True) == ("", None)  # no block, no judge line


# ---------- a routed task (decision 3, 4 and 5) ----------

def test_a_routed_task_sends_each_agent_its_own_part_first_and_the_judge_line_only_to_its_judges(world):
    notes.PATH.write_text(NOTES)
    world.worker, world.chatgpt = Scripted("Draft one.", "Draft two."), Chat("FIX\n1. [must] Rhyme.", "PASS\n1. fixed")
    world.label = fake_label(jev("writing"))
    world.run("route", POEM)
    row, calls = _calls(world)
    assert [c["kind"] for c in calls] == ["do", "check", "fix", "recheck"]
    do, fix = world.worker.prompts
    check, recheck = world.chatgpt.prompts
    assert do.startswith(block(CLAUDE)) and less_next(do[len(block(CLAUDE)):]) == f"{POEM}\n\n{checking.DELIVERABLE_LINE}"
    assert fix.startswith(block(CLAUDE)) and notes.JUDGE_LINE not in fix
    assert check.startswith(block(CHATGPT, judge=True)) and recheck.startswith(block(CHATGPT, judge=True))
    for prompt in (do, fix, check, recheck):
        assert GROK not in prompt and CURSOR not in prompt and PLANNER not in prompt
    assert CHATGPT not in do and CLAUDE not in check
    assert all(NOTES.splitlines()[1] not in c["task"] for c in world.label.calls)  # Jev's request carries none
    folder = cli.DB_PATH.parent
    assert (folder / "tasks" / row["task_id"] / "router-notes.md").read_text() == NOTES  # the task's copy
    records = [json.loads(c["context"])["notes"] for c in calls]
    assert records[0] == {"sections": {"all_agents": len(ALL), "claude": len(CLAUDE)}, "judge": False, "planner": False,
                          "chars": len(block(CLAUDE)), "from": row["task_id"]}
    assert records[1]["judge"] is True and records[1]["sections"] == {"all_agents": len(ALL), "chatgpt": len(CHATGPT)}
    kept = (folder / "tasks" / row["task_id"] / "01-do-claude-prompt.md").read_text()
    assert kept == do  # the doer's kept prompt starts with the lead line (D's key 3)


def test_with_the_blank_default_every_prompt_is_as_before_and_no_copy_is_kept(world):
    world.worker, world.chatgpt = Scripted("Draft one."), Chat("PASS")
    world.run("route", POEM)
    row, calls = _calls(world)
    assert [less_next(p) for p in world.worker.prompts] == [f"{POEM}\n\n{checking.DELIVERABLE_LINE}"]
    assert not world.chatgpt.prompts[0].startswith(notes.LEAD)
    assert not (cli.DB_PATH.parent / "tasks" / row["task_id"] / "router-notes.md").exists()
    assert all(c["context"] is None for c in calls)


def test_an_edit_mid_task_never_changes_a_running_task(world):
    notes.PATH.write_text(NOTES)

    def edit_then_answer(prompt):
        notes.PATH.write_text("## All agents\nUse imperial units.\n")
        return "Draft one."
    world.worker, world.chatgpt = Scripted(), Chat("PASS")
    world.worker.replies = []
    original = world.worker.__call__
    world.worker = lambda prompt, **kw: (world.__dict__.setdefault("seen", []).append(prompt), edit_then_answer(prompt))[1]
    world.run("route", POEM)
    check = world.chatgpt.prompts[0]
    assert ALL in check and "imperial" not in check  # the check sends from the copy the doer read
    assert original is not None


@pytest.mark.parametrize("text,code", [("oops\n## Claude\nx\n", "notes_invalid"),
                                       ("## Claude\n" + "to" + "ken: 0123456789abcdef\n", "notes_key")])
def test_invalid_notes_refuse_the_task_before_any_row_or_jev_call(world, text, code):
    notes.PATH.write_text(text)
    found = world.json("route", POEM)
    assert found["exit"] == 2 and found["reason_code"] == code and found["task_id"] is None
    assert "Router notes" in found["message"] and "0123456789abcdef" not in found["message"]
    assert world.label.calls == [] and world.worker.prompts == []
    assert world.row(1) is None


def test_relay_and_split_refuse_invalid_notes_the_same_way(world):
    notes.PATH.write_text("## Somebody\nx\n")
    assert world.json("relay", "versus", POEM)["reason_code"] == "notes_invalid"
    assert world.json("split", POEM)["reason_code"] == "notes_invalid"
    assert world.row(1) is None


def test_a_task_with_no_copy_sends_none_and_the_send_scan_returns_a_copy_that_looks_like_a_key(world, tmp_path):
    world.worker, world.chatgpt = Scripted("Draft one."), Chat("PASS")
    conn = log.init_db(cli.DB_PATH)
    try:
        log.add_task(conn, "sr-old", "t", "cli", {"status": "ok", "label": "writing", "confidence": 0.9, "tokens": 0})
        row = log.get_task(conn, "sr-old")
        assert context.attach("p", row, "claude", [], conn=conn) == ("p", None, None)  # a task from before brief 30
        target = notes.copy_path(cli.DB_PATH.parent, "sr-old")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("## Claude\n" + "to" + "ken: 0123456789abcdef\n")
        with pytest.raises(notes.Refused) as e:
            context.attach("p", row, "claude", [], conn=conn)
        assert e.value.code == "notes_key" and "0123456789abcdef" not in str(e.value)
    finally:
        conn.close()


# ---------- relay stages: the judge line on reviews and attacks; each agent its own (decision 3) ----------

def test_versus_builds_get_their_own_part_and_reviews_the_judge_line(world):
    notes.PATH.write_text(NOTES)
    world.worker = Scripted("A candidate.", "## Verdict\npass\n\n## Notes\nfine")
    world.chatgpt = Chat("B candidate.", "## Verdict\npass\n\n## Notes\nfine")
    world.run("relay", "versus", POEM)
    claude_build, claude_review = world.worker.prompts
    chatgpt_build, chatgpt_review = world.chatgpt.prompts
    assert claude_build.startswith(block(CLAUDE)) and chatgpt_build.startswith(block(CHATGPT))
    assert claude_review.startswith(block(CLAUDE, judge=True)) and chatgpt_review.startswith(block(CHATGPT, judge=True))


def test_redteams_attack_judges_its_build_and_revise_do_not(world):
    notes.PATH.write_text(NOTES)
    attacks = "## Attacks\n1. [high] Wrong.\n2. [low] Dull.\n3. [medium] No source.\n\n## Strongest\n1"
    world.worker = Scripted("## Deliverable\nLine one.\n\n## Unfinished\nnone", "Line one, fixed.\n\n## Answered\nnone")
    world.chatgpt = Chat(attacks, "PASS")
    world.run("relay", "redteam", POEM)
    build, revise = world.worker.prompts
    attack, check = world.chatgpt.prompts
    assert notes.JUDGE_LINE not in build and notes.JUDGE_LINE not in revise
    assert attack.startswith(block(CHATGPT, judge=True)) and check.startswith(block(CHATGPT, judge=True))


def test_a_vote_sends_each_voter_its_own_part_and_grok_its_own(world):
    notes.PATH.write_text(NOTES)
    world.worker = Scripted("## Answer\nrubber\n\n## Why\nflexes")
    world.chatgpt = Chat("## Answer\nrubber\n\n## Why\nlasts")
    world.run("relay", "vote", "Rubber or plastic tee? One word.", "--no-wait")
    assert world.worker.prompts[0].startswith(block(CLAUDE)) and world.chatgpt.prompts[0].startswith(block(CHATGPT))
    sent = world.hook.sent[0]["task"]
    assert sent.startswith(block(GROK)) and len(sent) <= __import__("router").settings.grok_prompt_limit()[0]


# ---------- the split's plan: the planner part (decision 3) ----------

def test_the_splits_plan_call_gets_the_planner_part_and_no_other_call_does(world):
    notes.PATH.write_text(NOTES)
    plan = ("## Pieces\n1. Write line one.\nteam: route\nwhy: one line\n2. Write line two.\nteam: route\nwhy: one line\n\n"
            "## Join\nPut the lines together.")
    world.worker = Scripted(plan)
    world.label = fake_label(jev("writing"))
    world.run("split", POEM, "--json")
    assert world.worker.prompts[0].startswith(block(CLAUDE, planner=True))
    kinds = notes.planning("stage", "split_plan"), notes.planning("reask", "split_plan"), notes.planning("stage", "integrate")
    assert kinds == (True, True, False)


def test_a_piece_sends_from_its_splits_copy(tmp_path):
    folder = tmp_path
    target = notes.copy_path(folder, "sr-split")
    target.parent.mkdir(parents=True)
    target.write_text(NOTES)
    piece = {"task_id": "sr-piece", "parent": "sr-split"}
    text, record = notes.for_call(folder, piece, "chatgpt", kind="check")
    assert text == block(CHATGPT, judge=True) and record["from"] == "sr-split"


# ---------- a takeover, a resume: the agent making the call (decision 3) ----------

def test_a_takeover_gets_its_own_section_never_the_stopped_agents(world):
    notes.PATH.write_text(NOTES)
    world.worker, world.chatgpt = Scripted(claude_limit()), Chat("Two lines.")
    world.run("route", POEM)
    took = world.chatgpt.prompts[0]
    assert took.startswith(block(CHATGPT)) and CLAUDE not in took and notes.JUDGE_LINE not in took


def test_a_resumed_call_gets_the_substitutes_own_section(tmp_path):
    folder = tmp_path
    notes.copy_path(folder, "sr-r").parent.mkdir(parents=True)
    notes.copy_path(folder, "sr-r").write_text(NOTES)
    text, _ = notes.for_call(folder, {"task_id": "sr-r"}, "chatgpt", kind="do")
    assert text == block(CHATGPT)


# ---------- Cursor: the opener, then the notes, then the prompt ----------

def test_a_cursor_prompt_opens_with_the_opener_then_the_notes():
    text, _ = notes.part_for(notes.parse(NOTES).sections, "cursor")
    wrapped = cursor_worker.wrap(text + "Write median(xs).")
    assert wrapped.startswith(cursor_worker.opener() + "\n\n" + block(CURSOR))
    assert cursor_worker.first_token_problem(wrapped) is None


# ---------- Grok: memory first, then the notes whole, then the handoff (decision 6) ----------

def test_grok_drops_the_notes_whole_when_they_dont_fit_and_never_fails_the_call(tmp_path):
    conn = log.init_db(tmp_path / "router.db")
    try:
        log.add_task(conn, "sr-g", "t", "cli", {"status": "ok", "label": "web_research", "confidence": 0.9, "tokens": 0})
        notes.copy_path(tmp_path, "sr-g").parent.mkdir(parents=True)
        notes.copy_path(tmp_path, "sr-g").write_text(NOTES)
        row = log.get_task(conn, "sr-g")
        lead = block(GROK)
        prompt, record, _ = context.attach("p" * 10, row, "grok", [], conn=conn, limit=len(lead) + 10)
        assert prompt == lead + "p" * 10 and record["notes"]["sections"]["grok"] == len(GROK)
        prompt, record, _ = context.attach("p" * 10, row, "grok", [], conn=conn, limit=len(lead) + 9)
        assert prompt == "p" * 10 and record == {"notes": {"left_out": "grok_limit", "chars": len(lead), "from": "sr-g"}}
    finally:
        conn.close()


def test_the_order_on_grok_is_memory_then_notes_then_the_handoff():
    from router import projects
    handoff = context.Handoff("demo", f"Notes.\n\n{projects.START}\n\n{projects.END}", 4)
    entries = [object()]

    def fit(limit, lead):
        import router.context as c
        real = c.memory_part
        c.memory_part = lambda tag, kept, cap: "M" * 50
        try:
            return context.fit_all("p", handoff, entries, "chat:x", limit, 2000, lead=lead)
        finally:
            c.memory_part = real
    lead = "L" * 30 + "\n\n"
    base = len("p") + 2 + len(context.render("demo", handoff.text))
    assert fit(base + len(lead) + 2 + 50, lead)[2:] == (entries, True)     # everything fits
    assert fit(base + len(lead), lead)[2:] == ([], True)                   # memory gives way first
    assert fit(base, lead)[0] == handoff.text and fit(base, lead)[2:] == ([], False)  # then the notes, whole
    text, lines, kept, notes_in = fit(base - 1, lead)                       # only then the handoff is cut
    assert text != handoff.text and notes_in is False
    assert fit(base + 10, "")[2:] == ([], True)                            # no notes: today's order exactly


def test_the_card_says_when_grok_left_the_notes_out(tmp_path):
    from router import cardline
    conn = log.init_db(tmp_path / "router.db")
    try:
        log.add_task(conn, "sr-g", "t", "cli", {"status": "ok", "label": "web_research", "confidence": 0.9, "tokens": 0})
        log.add_call(conn, "sr-g", "sr-g", "do", "grok", status="done", text="r",
                     context={"notes": {"left_out": "grok_limit", "chars": 400, "from": "sr-g"}})
        row = log.get_task(conn, "sr-g")
        assert notes.GROK_LEFT_OUT in cardline.line(row, calls=log.calls_for(conn, "sr-g"))
    finally:
        conn.close()


# ---------- the records (decision 9) ----------

def test_status_holds_the_notes_state_counts_cap_grok_share_and_hash_never_the_text(world):
    notes.PATH.write_text(NOTES)
    code, out, err = world.run("status", "--json")
    doc = json.loads(out)["notes"]
    assert doc["state"] == "set" and doc["hash"] == notes.digest(NOTES) and doc["max"] == 6000
    assert doc["sections"] == {"all_agents": len(ALL), "claude": len(CLAUDE), "chatgpt": len(CHATGPT), "grok": len(GROK),
                               "cursor": len(CURSOR), "planner": len(PLANNER)}
    assert doc["grok"]["share"] == len(ALL) + len(GROK) and ALL not in out
    notes.PATH.write_text("## Nobody\nx\n")
    doc = json.loads(world.run("status", "--json")[1])["notes"]
    assert (doc["state"], doc["line"], doc["reason_code"]) == ("invalid", 1, "notes_invalid")


def test_show_json_gives_the_tasks_copy_and_each_calls_sections(world):
    notes.PATH.write_text(NOTES)
    world.worker, world.chatgpt = Scripted("Draft one."), Chat("PASS")
    world.run("route", POEM)
    doc = json.loads(world.run("show", "1", "--json")[1])
    assert doc["router_notes"] == {"hash": notes.digest(NOTES), "chars": len(NOTES),
                                   "file": f"tasks/{doc['task_id']}/router-notes.md"}
    assert doc["calls"][0]["router_notes"]["sections"] == {"all_agents": len(ALL), "claude": len(CLAUDE)}
    assert doc["calls"][1]["router_notes"]["judge"] is True
    assert isinstance(doc["notes"], list)  # the deciding check's notes, as brief 29.1 made them


def test_show_notes_prints_the_copy_and_what_each_call_was_sent(world):
    notes.PATH.write_text(NOTES)
    world.worker, world.chatgpt = Scripted("Draft one."), Chat("PASS")
    world.run("route", POEM)
    text = world.run("show", "1", "--notes")[1]
    assert f"Router notes kept with this task ({notes.digest(NOTES)}, {len(NOTES):,} characters):" in text
    assert ALL in text and PLANNER in text  # the whole copy
    assert f"do claude: sent All agents {len(ALL)}, Claude {len(CLAUDE)}\n" in text
    assert f"check chatgpt: sent All agents {len(ALL)}, ChatGPT {len(CHATGPT)} + the judge line" in text


def test_show_notes_on_a_task_with_none(world):
    world.worker, world.chatgpt = Scripted("Draft one."), Chat("PASS")
    world.run("route", POEM)
    assert "Router notes: none kept with this task" in world.run("show", "1", "--notes")[1]
