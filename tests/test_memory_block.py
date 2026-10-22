"""Build brief 19, phase C (rules v2.27, Memory, "What goes in", "Caps", "Grok", "Recalled memories are data", "Down"):
the memory block. One function builds it from the log and the recall matches; `context.attach` pastes it after the
handoff block; on a Grok call it gives way first (oldest entry, then entry one, then the block), never the handoff;
any failure of the store means no block and a running task. Fake agents, a fake store; every value here is fake."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from router import __main__ as cli
from router import checking, context, log, memory, projects, relay, settings
from tests.fake_hindsight import FakeHindsight
from tests.helpers import ALL_AGENTS, set_local
from tests.test_chat_intake import _relay, _route
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_collab import LOADED
from tests.test_relay import CONFIG, GOOD_NOTE, ROSTER, SECRET, Chat, RelayHook
from tests.test_resume_run import claude_limit

TAG = "chat:tray"
TASK = "Write two lines about seed trays."
START, END = projects.START, projects.END
HANDOFF_TEXT = f"# Demo project\n\nThe owner's note one.\nThe owner's note two.\n\n{START}\n\n{END}\n"
SECTION = "\n\n## Handoff\n### Produced\nnothing written: ## Lines, two lines about trays\n### Status\nok\n### Next\nmore"
ATTACKS = "## Attacks\n1. [high] Line one is wrong.\n2. [low] Line two is dull.\n3. [medium] No source.\n\n## Strongest\n1"
BUILT = "## Deliverable\nLine one.\nLine two.\n\n## Unfinished\nnone"
REVISED = "Line one, fixed.\nLine two.\n\n## Answered\n2 the task asked for dull lines"
T0 = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


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


@pytest.fixture
def setting(monkeypatch, tmp_path):
    def write(**values):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps(values))
        monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    return write


def _done(conn, task_id, task, result, *, chat="tray", project=None, agent="claude", skill="writing", check_state="passed",
          check_note=None, at=T0, do_text=None, mode="route", preset=None):
    """A delivered task row with its do call (and a check call when it was checked)."""
    jev = {"status": "not_asked", "tokens": 0} if mode == "relay" else {"status": "ok", "label": skill, "confidence": 0.9, "tokens": 0}
    log.add_task(conn, task_id, task, "cli", jev, chat=chat, project=project, now=at, mode=mode, preset=preset)
    log.set_route(conn, task_id, agents=ALL_AGENTS, agent=agent, route_reason="best", skill=None if mode == "relay" else skill,
                  checker="chatgpt", check_state="pending")
    if mode == "route":
        log.add_call(conn, task_id, task_id, "do", agent, status="done", text=do_text or result, now=at)
        if check_state in ("passed", "fixed", "failed"):
            verdict = "PASS" if check_state == "passed" else "FIX"
            log.add_call(conn, f"{task_id}-c1", task_id, "check", "chatgpt", status="done", text=verdict, verdict=verdict, now=at)
    log.set_done(conn, task_id, result, check_state=check_state, check_note=check_note)
    return log.get_task(conn, task_id)


def _queued(conn, task_id="sr-run", task=TASK, *, chat="tray", project=None):
    log.add_task(conn, task_id, task, "cli", {"status": "ok", "label": "writing", "confidence": 0.9, "tokens": 0}, chat=chat,
                 project=project)
    log.set_route(conn, task_id, agents=ALL_AGENTS, agent="claude", route_reason="best", skill="writing", checker="chatgpt",
                  check_state="pending")
    return log.get_task(conn, task_id)


def _entry(row, status=None):
    return memory.Entry(row["n"], memory.local_date(row["updated_at"]), row["preset"] or row["skill"] or "-", row["agent"],
                        status, f"{row['task']}\n\n{row['result']}")


def _block(entries, tag=TAG, cap=2000):
    return memory.render(tag, entries, cap)


def _attach(conn, row, fake, agent="claude", limit=None, prompt="p", reuse=None):
    return context.attach(prompt, row, agent, [SECRET], limit=limit, conn=conn, hindsight=fake.client, reuse=reuse)


# ---------- what goes in (decision 8) ----------

def test_entry_one_is_the_newest_delivered_task_from_the_log_even_when_recall_omits_it(conn):
    one = _done(conn, "sr-1", "first task", "first result", at=T0)
    two = _done(conn, "sr-2", "second task", "second result", at=T0 + timedelta(hours=1))
    running = _queued(conn)
    fake = FakeHindsight(results=[FakeHindsight.result("task-sr-1", "whatever the store holds", tags=[TAG])])
    prompt, record, mem = _attach(conn, running, fake)
    block = _block([_entry(two), _entry(one)])
    assert prompt == "p\n\n" + block and record is None
    assert mem == {"tag": TAG, "found": 2, "sent": 2, "text": block}
    assert "whatever the store holds" not in prompt  # the entry's text is the log's, never the chunk


def test_the_task_being_run_is_never_in_its_own_block(conn):
    one = _done(conn, "sr-1", "first task", "first result")
    running = _queued(conn)
    log.add_call(conn, "sr-run", "sr-run", "do", "claude", status="done", text="half done")
    fake = FakeHindsight(results=[FakeHindsight.result("task-sr-run", "x", tags=[TAG]), FakeHindsight.result("task-sr-1", "y", tags=[TAG])])
    prompt, _, mem = _attach(conn, running, fake)
    assert prompt == "p\n\n" + _block([_entry(one)]) and mem["found"] == 1


def test_a_memory_from_another_tag_or_untagged_never_appears_and_the_request_says_so(conn):
    _done(conn, "sr-g", "garden task", "garden result", chat="garden")
    _done(conn, "sr-u", "plain task", "plain result", chat=None)
    one = _done(conn, "sr-1", "first task", "first result")
    running = _queued(conn)
    fake = FakeHindsight(results=[FakeHindsight.result("task-sr-g", "g", tags=["chat:garden"]),
                                  FakeHindsight.result("task-sr-u", "u", tags=[]),
                                  FakeHindsight.result("task-sr-1", "f", tags=[TAG])])
    prompt, _, mem = _attach(conn, running, fake)
    assert prompt == "p\n\n" + _block([_entry(one)]) and mem["found"] == 1
    assert fake.recalls == [{"query": TASK, "tags": [TAG], "tags_match": "any_strict", "max_tokens": 2000, "budget": "low"}]


def test_a_non_storable_source_task_is_dropped_and_a_picked_fail_candidate_is_kept_with_its_status(conn):
    _done(conn, "sr-f", "failed task", "failed result", check_state="failed", check_note="not passed after one fix round")
    _done(conn, "sr-un", "unchecked task", "unchecked result", check_state="unchecked", check_note="check round by chatgpt didn't run: x")
    log.add_task(conn, "sr-open", "open task", "cli", {"status": "ok", "label": "writing", "confidence": 0.9, "tokens": 0}, chat="tray")
    quick = _done(conn, "sr-q", "quick task", "quick result", skill="quick_answer", check_state="not_needed")
    picked = _done(conn, "sr-v", "versus task", "candidate a", mode="relay", preset="versus", check_state="failed",
                   check_note="picked a; review by chatgpt: fail", at=T0 + timedelta(hours=2))
    running = _queued(conn)
    fake = FakeHindsight(results=[FakeHindsight.result(f"task-{t}", "x", tags=[TAG]) for t in ("sr-f", "sr-un", "sr-open", "sr-q", "sr-v")])
    prompt, _, mem = _attach(conn, running, fake)
    expected = _block([_entry(picked, "picked a; review by chatgpt: fail"), _entry(quick, "not_needed")])
    assert prompt == "p\n\n" + expected and mem["found"] == 2
    assert "### #5 · " in expected and " · versus · claude · picked a; review by chatgpt: fail\n" in expected
    assert " · quick_answer · claude · not_needed\n" in expected


def test_a_matching_chunk_is_shown_and_an_unmatched_one_gives_the_content_head(conn):
    """The owner's refinement after Phase F: when Hindsight's chunk text is a byte-for-byte substring of the task's content
    from the log, the entry shows the chunk; otherwise the content's head, as before. Entry one, from the log, is always
    the head, even when recall returns one of its chunks."""
    para1, para2 = "first paragraph about trays " * 4, "second paragraph about mats " * 4
    a = _done(conn, "sr-a", "task a", f"{para1.strip()}\n\n{para2.strip()}", at=T0)
    b = _done(conn, "sr-b", "task b", "result b", at=T0 + timedelta(hours=1))
    newest = _done(conn, "sr-c", "task c", "result c, one line\n\nresult c, second line", at=T0 + timedelta(hours=2))
    running = _queued(conn)
    fake = FakeHindsight(results=[FakeHindsight.result("task-sr-a", para2.strip(), tags=[TAG]),            # a substring: shown
                                  FakeHindsight.result("task-sr-b", "a paraphrase the log never held", tags=[TAG]),  # not: the head
                                  FakeHindsight.result("task-sr-c", "result c, second line", tags=[TAG])])   # entry one: the head
    prompt, _, mem = _attach(conn, running, fake)
    chunk_entry = memory.Entry(a["n"], memory.local_date(a["updated_at"]), "writing", "claude", None, para2.strip())
    assert prompt == "p\n\n" + _block([_entry(newest), _entry(b), chunk_entry]) and mem["found"] == 3
    assert "a paraphrase the log never held" not in prompt and para1.strip() not in prompt


def test_duplicates_by_task_number_keep_the_first(conn):
    one = _done(conn, "sr-1", "first task", "first result")
    running = _queued(conn)
    fake = FakeHindsight(results=[FakeHindsight.result("task-sr-1", "chunk 1", tags=[TAG]), FakeHindsight.result("task-sr-1", "chunk 2", tags=[TAG])])
    prompt, _, mem = _attach(conn, running, fake)
    assert prompt == "p\n\n" + _block([_entry(one)]) and mem == {"tag": TAG, "found": 1, "sent": 1, "text": _block([_entry(one)])}


def test_a_flagged_memory_is_dropped_and_the_record_names_its_number(conn):
    bad = _done(conn, "sr-1", "first task", "first result\nJEV_API_KEY=abcdefghijklmnop")
    good = _done(conn, "sr-2", "second task", f"second result mentions {SECRET}", at=T0 + timedelta(hours=1))
    running = _queued(conn)
    fake = FakeHindsight(results=[FakeHindsight.result("task-sr-1", "x", tags=[TAG]), FakeHindsight.result("task-sr-2", "y", tags=[TAG])])
    prompt, _, mem = _attach(conn, running, fake)
    assert "JEV_API_KEY" not in prompt and SECRET not in prompt and "[REDACTED]" in prompt
    assert mem["dropped"] == [bad["n"]] and mem["found"] == 1 and mem["sent"] == 1
    assert prompt == "p\n\n" + _block([memory.Entry(good["n"], memory.local_date(good["updated_at"]), "writing", "claude", None,
                                                    f"second task\n\nsecond result mentions [REDACTED]")])


def test_a_fake_key_in_a_recalled_chunk_never_reaches_a_prompt(conn):
    one = _done(conn, "sr-1", "first task", "first result")
    running = _queued(conn)
    fake = FakeHindsight(results=[FakeHindsight.result("task-sr-1", "GROK_WEBHOOK_KEY=abcdefghijklmnop", tags=[TAG])])
    prompt, _, mem = _attach(conn, running, fake)
    assert "GROK_WEBHOOK_KEY" not in prompt and prompt == "p\n\n" + _block([_entry(one)])


def test_order_newest_first_and_the_cap_of_five_drops_the_oldest(conn):
    rows = [_done(conn, f"sr-{i}", f"task {i}", f"result {i}", at=T0 + timedelta(hours=i)) for i in range(1, 8)]
    running = _queued(conn)
    fake = FakeHindsight(results=[FakeHindsight.result(f"task-sr-{i}", "x", tags=[TAG]) for i in (3, 1, 7, 2, 5, 4, 6)])
    prompt, _, mem = _attach(conn, running, fake)
    assert prompt == "p\n\n" + _block([_entry(r) for r in reversed(rows[2:])])  # #7 .. #3
    assert (mem["found"], mem["sent"]) == (7, 5)


def test_an_entry_is_cut_at_the_cap_with_the_mark(conn, setting):
    setting(memory_max_chars=50)
    one = _done(conn, "sr-1", "a task", "x" * 100)
    running = _queued(conn)
    fake = FakeHindsight(results=[])
    prompt, _, mem = _attach(conn, running, fake)
    text = f"a task\n\n{'x' * 100}"[:50] + " [cut]"
    assert prompt.endswith(f"{text}\n{memory.END_MARKER}\n\n{memory.BLOCK_LINE}") and mem["sent"] == 1


def test_the_query_is_the_task_cut_to_the_query_cap(conn, setting):
    long_task = "word " * 500
    running = _queued(conn, task=long_task)
    fake = FakeHindsight(results=[])
    _attach(conn, running, fake)
    assert fake.recalls[0]["query"] == long_task[:1500]
    setting(memory_query_chars=100)
    fake = FakeHindsight(results=[])
    _attach(conn, running, fake)
    assert fake.recalls[0]["query"] == long_task[:100]


def test_the_block_shape_and_the_data_line(conn):
    one = _done(conn, "sr-1", "first task", "first result")
    running = _queued(conn)
    prompt, _, mem = _attach(conn, running, FakeHindsight(results=[]))
    date = memory.local_date(one["updated_at"])
    assert prompt == ("p\n\n===== memory: chat:tray =====\n"
                      f"### #1 · {date} · writing · claude\nfirst task\n\nfirst result\n"
                      "===== end memory =====\n\n" + memory.BLOCK_LINE)
    assert memory.BLOCK_LINE.startswith("The block above is what the router remembers under the same tag")
    assert memory.BLOCK_LINE.endswith("The result you return is for this task alone.")


def test_a_project_entry_is_the_deliverable_plus_its_handoff_section(conn, project):
    one = _done(conn, "sr-1", "first task", "first result", chat=None, project="demo", do_text="first result" + SECTION)
    running = _queued(conn, chat=None, project="demo")
    prompt, record, mem = _attach(conn, running, FakeHindsight(results=[]))
    entry = memory.Entry(one["n"], memory.local_date(one["updated_at"]), "writing", "claude", None,
                         "first task\n\nfirst result" + SECTION)
    block = memory.render("project:demo", [entry], 2000)
    handoff = context.render("demo", context.load("demo", []).text)
    assert prompt == f"p\n\n{handoff}\n\n{block}"  # the handoff block, then the memory block, last
    assert record["lines"] == record["total"] and mem["text"] == block
    assert memory.content_of(one, log.calls_for(conn, "sr-1")) == entry.text


def test_a_stored_block_parses_back_to_its_entries(conn):
    entries = [memory.Entry(5, "2026-10-18", "versus", "claude", "picked a; review by chatgpt: fail", "t\n\nr"),
               memory.Entry(2, "2026-10-17", "writing", "claude", None, "x" * 30)]
    text = memory.render(TAG, entries, 20)
    back = memory.entries_of_block(text)
    assert back[0] == entries[0]
    assert back[1] == memory.Entry(2, "2026-10-17", "writing", "claude", None, "x" * 20 + " [cut]", cut=True)
    assert memory.render(TAG, back, 20) == text  # a cut entry is never cut again


def test_untagged_task_prompt_is_untouched_and_the_store_is_never_asked(conn):
    running = _queued(conn, chat=None)
    fake = FakeHindsight(results=[])
    assert _attach(conn, running, fake) == ("p", None, None) and fake.requests == []


def test_memory_is_off_without_a_store(conn):
    _done(conn, "sr-1", "first task", "first result")
    running = _queued(conn)
    assert context.attach("p", running, "claude", [], conn=conn) == ("p", None, None)
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("two lines"))
    assert code == 0 and "memory:" not in out
    assert all(log.call_memory_of(c) is None for c in log.calls_for(conn, row["task_id"]))


# ---------- down and unreachable (decision 12) ----------

@pytest.mark.parametrize("mode", ["refused", "timeout", 500, "bad json"])
def test_a_failed_recall_means_no_block_a_record_and_one_line(conn, mode):
    _done(conn, "sr-1", "first task", "first result")
    fake = FakeHindsight(fail={"recall": mode})
    worker, chat = Scripted("FIRST", "FIXED"), Chat("FIX\n1. x", "PASS")
    code, out, row, _ = _route(conn, chat="tray", worker=worker, chatgpt=chat, hindsight=fake.client)
    assert code == 0 and row["status"] == "done" and row["check_state"] == "fixed", out
    assert worker.prompts == [TASK, worker.prompts[1]] and memory.MARK not in worker.prompts[0]
    assert out.count("memory: unavailable; this task runs without its memory block") == 1
    records = [log.call_memory_of(c) for c in log.calls_for(conn, row["task_id"])]
    assert records[0]["unavailable"] is True and records[0]["tag"] == TAG and "reason" in records[0]
    assert all(r.get("unavailable") for r in records) and all(r["from"] == row["task_id"] for r in records[1:])
    assert len(fake.recalls) == 1  # the check, fix and re-check reuse the doer's record: no second recall


def test_a_store_that_is_offline_is_one_line_and_a_running_task(conn):
    fake = FakeHindsight(online=False)
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("two lines"), hindsight=fake.client)
    assert code == 0 and row["status"] == "done" and out.count("memory: unavailable") == 1


# ---------- the block on every call of a task ----------

def test_the_block_rides_on_the_doer_the_checker_and_the_fix_byte_for_byte_with_one_recall(conn):
    one = _done(conn, "sr-1", "first task", "first result")
    fake = FakeHindsight(results=[])
    worker, chat = Scripted("FIRST", "FIXED"), Chat("FIX\n1. x", "PASS")
    code, out, row, _ = _route(conn, chat="tray", worker=worker, chatgpt=chat, hindsight=fake.client)
    assert code == 0 and row["check_state"] == "fixed", out
    block = _block([_entry(one)])
    assert worker.prompts[0] == f"{TASK}\n\n{block}"
    assert chat.prompts[0].endswith("\n\n" + block) and worker.prompts[1].endswith("\n\n" + block)
    assert chat.prompts[1].endswith("\n\n" + block)
    assert len(fake.recalls) == 1
    calls = log.calls_for(conn, row["task_id"])
    assert [c["kind"] for c in calls] == ["do", "check", "fix", "recheck"]
    assert log.call_memory_of(calls[0]) == {"tag": TAG, "found": 1, "sent": 1, "text": block}
    for c in calls[1:]:
        assert log.call_memory_of(c) == {"tag": TAG, "found": 1, "sent": 1, "text": block, "from": row["task_id"]}


def test_a_task_with_nothing_remembered_yet_gets_no_block_and_a_zero_record(conn):
    fake = FakeHindsight(results=[])
    worker = Scripted("two lines")
    code, out, row, _ = _route(conn, chat="tray", worker=worker, hindsight=fake.client)
    assert code == 0 and worker.prompts == [TASK]
    assert log.call_memory_of(log.calls_for(conn, row["task_id"])[0]) == {"tag": TAG, "found": 0, "sent": 0}


def test_every_research_build_stage_and_the_check_carry_the_block(conn):
    one = _done(conn, "sr-1", "first task", "first result")
    fake, worker, chat = FakeHindsight(results=[]), Scripted("built"), Chat("PASS")
    code, out, row, hook = _relay(conn, "research-build", chat="tray", hook=RelayHook(s1=GOOD_NOTE), worker=worker,
                                  chatgpt=chat, hindsight=fake.client, wait=True)
    assert code == 0, out
    block = _block([_entry(one)])
    assert hook.sent[0]["task"].endswith("\n\n" + block)
    assert worker.prompts[0].endswith("\n\n" + block) and chat.prompts[0].endswith("\n\n" + block)
    assert len(fake.recalls) == 2  # each stage recalls afresh; the check reuses stage 2's
    calls = log.calls_for(conn, row["task_id"])
    assert log.call_memory_of(calls[-1])["from"] == calls[1]["call_id"]


def test_every_redteam_stage_carries_the_block_after_the_attack_block(conn):
    one = _done(conn, "sr-1", "first task", "first result")
    fake, worker, chat = FakeHindsight(results=[]), Scripted(BUILT, REVISED), Chat(ATTACKS, "PASS")
    code, out, row, hook = _relay(conn, "redteam", chat="tray", worker=worker, chatgpt=chat, hindsight=fake.client, wait=True)
    assert code == 0, out
    block = _block([_entry(one)])
    for prompt in (worker.prompts[0], chat.prompts[0], worker.prompts[1], chat.prompts[1]):
        assert prompt.endswith("\n\n" + block)
    revise = worker.prompts[1]
    assert revise.index(relay.ATTACK_LIST_LABEL) < revise.index(memory.start_marker(TAG))
    assert len(fake.recalls) == 3


def test_the_doer_reask_gets_the_block_its_first_call_got(conn, project):
    one = _done(conn, "sr-1", "first task", "first result", chat=None, project="demo", do_text="first result" + SECTION)
    fake, worker = FakeHindsight(results=[]), Scripted("no section yet", "with" + SECTION)
    code, out, row, _ = _route(conn, project="demo", worker=worker, chatgpt=Chat("PASS"), hindsight=fake.client)
    assert code == 0, out
    calls = log.calls_for(conn, row["task_id"])
    assert [c["kind"] for c in calls][:2] == ["do", "do"] and calls[1]["call_id"].endswith(context.DO_REASK)
    first, reask = log.call_memory_of(calls[0]), log.call_memory_of(calls[1])
    assert reask == {**first, "from": calls[0]["call_id"]} and len(fake.recalls) == 1
    assert worker.prompts[1].endswith("\n\n" + first["text"])


def test_the_substitute_on_a_resume_gets_the_stopped_calls_block(conn):
    one = _done(conn, "sr-1", "first task", "first result")
    fake = FakeHindsight(results=[])
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted(claude_limit()), hindsight=fake.client)
    assert row["status"] == "failed"
    lines, clock, hook, chat = [], Clock(), Webhook(), Chat("two lines")
    code = cli.cmd_resume([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                          settings_paths=[], post=hook.post, worker=Scripted("PASS"), chatgpt=chat,
                          codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                          wait=True, out=lines.append, hindsight=fake.client)
    assert code == 0, "\n".join(lines)
    block = _block([_entry(one)])
    assert chat.prompts[0].endswith("\n\n" + block) and len(fake.recalls) == 1
    assert log.call_memory_of(log.get_call(conn, f"{row['task_id']}-resume"))["from"] == row["task_id"]


def test_the_fallback_doer_gets_the_replaced_calls_block(conn):
    one = _done(conn, "sr-1", "first task", "first result")
    fake = FakeHindsight(results=[])
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("FIRST", "FIXED"), chatgpt=Chat("FIX\n1. x", "FIX\n1. y"),
                               hindsight=fake.client)
    assert row["check_state"] == "failed"
    lines, clock, hook, redo = [], Clock(), Webhook(), Chat("REDO")
    code = cli.cmd_fallback([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                            settings_paths=[], post=hook.post, worker=Scripted("PASS"), chatgpt=redo,
                            codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep,
                            clock=clock, wait=True, out=lines.append, hindsight=fake.client)
    assert code == 0, "\n".join(lines)
    block = _block([_entry(one)])
    assert redo.prompts[0].endswith("\n\n" + block) and len(fake.recalls) == 1
    assert log.call_memory_of(log.get_call(conn, f"{row['task_id']}-fb1"))["from"] == row["task_id"]


# ---------- Grok: the memory block gives way first, never the handoff (decision 10 as amended) ----------

def _grok_setup(conn, project):
    one = _done(conn, "sr-1", "first task", "first result", chat=None, project="demo", do_text="first result" + SECTION)
    two = _done(conn, "sr-2", "second task", "second result", chat=None, project="demo", do_text="second result" + SECTION,
                at=T0 + timedelta(hours=1))
    running = _queued(conn, chat=None, project="demo")
    fake = FakeHindsight(results=[FakeHindsight.result("task-sr-1", "x", tags=["project:demo"])])
    handoff = context.load("demo", [])
    h_block = context.render("demo", handoff.text)
    entries, _ = memory.for_call(conn, running, fake.client, [])
    assert [e.n for e in entries] == [two["n"], one["n"]]
    return running, fake, handoff, h_block, entries


def test_a_grok_call_drops_the_oldest_memory_entry_first_and_keeps_the_whole_handoff(conn, project):
    running, fake, handoff, h_block, entries = _grok_setup(conn, project)
    m2, m1 = memory.render("project:demo", entries, 2000), memory.render("project:demo", entries[:1], 2000)
    full = len("p") + 2 + len(h_block) + 2 + len(m2)
    prompt, record, mem = _attach(conn, running, fake, agent="grok", limit=full)
    assert prompt == f"p\n\n{h_block}\n\n{m2}" and mem["sent"] == 2
    prompt, record, mem = _attach(conn, running, fake, agent="grok", limit=full - 1)
    assert prompt == f"p\n\n{h_block}\n\n{m1}"
    assert record["lines"] == record["total"] == handoff.total  # the handoff whole
    assert mem == {"tag": "project:demo", "found": 2, "sent": 1, "text": m1}


def test_a_grok_call_then_drops_entry_one_and_leaves_the_block_out_before_touching_the_handoff(conn, project):
    running, fake, handoff, h_block, entries = _grok_setup(conn, project)
    m2, m1 = memory.render("project:demo", entries, 2000), memory.render("project:demo", entries[:1], 2000)
    just_handoff = len("p") + 2 + len(h_block)
    limit = just_handoff + 2 + len(m1) - 1
    prompt, record, mem = _attach(conn, running, fake, agent="grok", limit=limit)
    assert prompt == f"p\n\n{h_block}" and record["lines"] == handoff.total
    assert mem == {"tag": "project:demo", "found": 2, "left_out": True, "with": just_handoff + 2 + len(m2), "limit": limit}


def test_only_with_the_block_out_is_the_handoff_cut_as_brief_18_built_it(conn, project):
    running, fake, handoff, h_block, entries = _grok_setup(conn, project)
    m2 = memory.render("project:demo", entries, 2000)
    just_handoff = len("p") + 2 + len(h_block)
    prompt, record, mem = _attach(conn, running, fake, agent="grok", limit=just_handoff - 1)
    assert mem == {"tag": "project:demo", "found": 2, "left_out": True, "limit": just_handoff - 1,
                   "with": len(f"p\n\n{context.render('demo', record['text'])}") + 2 + len(m2)}
    assert record["lines"] < record["total"] and "# Demo project" not in prompt  # The owner's part, from its top line
    assert memory.MARK + " memory" not in prompt
    fitted, lines = context.fit("p", handoff, just_handoff - 1)
    assert record["text"] == fitted and record["lines"] == lines


def test_claude_and_chatgpt_calls_are_never_trimmed(conn, project, setting):
    setting(grok_prompt_limit=60)
    running, fake, handoff, h_block, entries = _grok_setup(conn, project)
    m2 = memory.render("project:demo", entries, 2000)
    for agent in ("claude", "chatgpt"):
        prompt, record, mem = _attach(conn, running, fake, agent=agent)
        assert prompt == f"p\n\n{h_block}\n\n{m2}" and mem["sent"] == 2 and record["lines"] == handoff.total


def test_a_chat_task_on_grok_trims_the_block_alone(conn):
    one = _done(conn, "sr-1", "first task", "first result")
    running = _queued(conn)
    fake = FakeHindsight(results=[])
    m1 = _block([_entry(one)])
    prompt, record, mem = _attach(conn, running, fake, agent="grok", limit=len("p") + 2 + len(m1))
    assert prompt == f"p\n\n{m1}" and record is None and mem["sent"] == 1
    prompt, record, mem = _attach(conn, running, fake, agent="grok", limit=len("p") + 2 + len(m1) - 1)
    assert prompt == "p" and mem == {"tag": TAG, "found": 1, "left_out": True, "with": len("p") + 2 + len(m1),
                                     "limit": len("p") + 2 + len(m1) - 1}


def test_the_grok_length_rule_still_runs_after_the_trim(conn, setting):
    _done(conn, "sr-1", "first task", "first result")
    base = relay.prompt_for("build", TASK, GOOD_NOTE)
    setting(grok_prompt_limit=len(base) - 1)
    fake = FakeHindsight(results=[])
    code, out, row, hook = _relay(conn, "research-build", chat="tray", slots=[("build", "grok")], hindsight=fake.client, wait=True)
    assert code == 1 and row["status"] == "failed" and row["failed_stage"] == 2
    assert f"too long for Grok ({len(base)} characters)" in out
    stage2 = [c for c in log.calls_for(conn, row["task_id"]) if c["stage"] == 2][0]
    one = _block([_entry(log.get_task(conn, "sr-1"))])
    assert log.call_memory_of(stage2) == {"tag": TAG, "found": 1, "left_out": True, "with": len(base) + 2 + len(one),
                                          "limit": len(base) - 1}


def test_a_grok_stage_row_says_how_many_entries_went(conn, setting):
    rows = [_done(conn, f"sr-{i}", f"task {i}", f"result {i}", at=T0 + timedelta(hours=i)) for i in (1, 2, 3)]
    base = relay.prompt_for("research", TASK, None)
    one_entry = memory.render(TAG, [_entry(rows[2])], 2000)
    setting(grok_prompt_limit=len(base) + 2 + len(one_entry))
    fake = FakeHindsight(results=[FakeHindsight.result(f"task-sr-{i}", "x", tags=[TAG]) for i in (1, 2)])
    code, out, row, hook = _relay(conn, "research-build", chat="tray", hook=RelayHook(s1=GOOD_NOTE), worker=Scripted("built"),
                                  chatgpt=Chat("PASS"), hindsight=fake.client, wait=True)
    assert code == 0, out
    assert hook.sent[0]["task"] == f"{base}\n\n{one_entry}"
    first = log.call_memory_of(log.calls_for(conn, row["task_id"])[0])
    assert (first["found"], first["sent"]) == (3, 1)
