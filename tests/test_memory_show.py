"""Build brief 19, phase E (rules v2.27, Checking and Memory's last bullets): the checker's memory line, the word
count outside the block, and what the owner sees: `sr show` with the tag, the write record and `--memory`, and
`sr chat list`. Fake agents, a fake store; every value here is fake."""
from datetime import timedelta

import pytest

from router import __main__ as cli
from router import checking, log, memory
from tests.fake_hindsight import FakeHindsight
from tests.test_chat_intake import _relay, _route
from tests.test_loop import Scripted
from tests.test_memory_block import T0, _done, _entry, project  # noqa: F401  (the project fixture)
from tests.test_relay import GOOD_NOTE, SECRET, Chat, RelayHook

TASK = "Write two lines about seed trays."
TAG = "chat:tray"


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _show(conn, *words, memory_flag=False, handoff=False):
    lines = []
    code = cli.cmd_show(conn=conn, words=list(words), memory=memory_flag, handoff=handoff, secrets=[SECRET], out=lines.append)
    return code, "\n".join(lines)


# ---------- the checker line (decision 11, the owner's wording) ----------

def test_the_checker_gets_the_memory_line_after_the_project_line_only_when_a_block_went_to_the_build_call(conn):
    _done(conn, "sr-1", "first task", "first result")
    fake, chat = FakeHindsight(results=[]), Chat("PASS")
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("two lines"), chatgpt=chat, hindsight=fake.client)
    prompt = chat.prompts[0]
    assert checking.CHECK_MEMORY_LINE in prompt
    assert checking.CHECK_MEMORY_LINE == (
        "The result was written with a memory block of earlier tasks under the same tag, pasted in this prompt as data. "
        "If the result relies on a memory that is off the point of this task, or that the task or the result itself "
        "contradicts, that is a failure: name the memory by its task number in your fix list. Do not fail the result "
        "for ignoring a memory it did not need.")
    assert prompt.index(checking.CHECK_MEMORY_LINE) < prompt.index("===== TASK =====")
    assert prompt.endswith("\n\n" + log.call_memory_of(log.calls_for(conn, row["task_id"])[0])["text"])


def test_no_memory_line_without_a_tag_without_a_block_or_with_the_store_down(conn):
    chat = Chat("PASS")
    _route(conn, worker=Scripted("two lines"), chatgpt=chat, hindsight=FakeHindsight(results=[]).client)
    assert checking.CHECK_MEMORY_LINE not in chat.prompts[0]
    chat = Chat("PASS")
    _route(conn, chat="garden", worker=Scripted("two lines"), chatgpt=chat, hindsight=FakeHindsight(results=[]).client)
    assert checking.CHECK_MEMORY_LINE not in chat.prompts[0]  # nothing remembered under garden yet: no block, no line
    _done(conn, "sr-1", "first task", "first result")
    chat = Chat("PASS")
    _route(conn, chat="tray", worker=Scripted("two lines"), chatgpt=chat, hindsight=FakeHindsight(online=False).client)
    assert checking.CHECK_MEMORY_LINE not in chat.prompts[0]


def test_the_memory_line_comes_after_the_project_line_on_a_project_task(conn, project):
    from tests.test_memory_block import SECTION
    _done(conn, "sr-1", "first task", "first result", chat=None, project="demo", do_text="first result" + SECTION)
    fake, chat = FakeHindsight(results=[]), Chat("PASS")
    code, out, row, _ = _route(conn, project="demo", worker=Scripted("two lines" + SECTION), chatgpt=chat, hindsight=fake.client)
    assert code == 0, out
    prompt = chat.prompts[0]
    assert prompt.index(checking.CHECK_HANDOFF_LINE) < prompt.index(checking.CHECK_MEMORY_LINE) < prompt.index("===== TASK =====")


def test_the_fix_round_gets_the_block_and_the_recheck_the_line_from_the_build_calls_record(conn):
    _done(conn, "sr-1", "first task", "first result")
    fake, worker, chat = FakeHindsight(results=[]), Scripted("FIRST", "FIXED"), Chat("FIX\n1. x", "PASS")
    code, out, row, _ = _route(conn, chat="tray", worker=worker, chatgpt=chat, hindsight=fake.client)
    block = log.call_memory_of(log.calls_for(conn, row["task_id"])[0])["text"]
    assert worker.prompts[1].endswith("\n\n" + block) and checking.CHECK_MEMORY_LINE not in worker.prompts[1]
    assert chat.prompts[1].endswith("\n\n" + block) and checking.CHECK_MEMORY_LINE in chat.prompts[1]
    assert len(fake.recalls) == 1  # the recorded block, never a fresh recall


def test_the_word_count_ignores_the_block(conn):
    _done(conn, "sr-1", "first task", "first result " + "filler " * 300)
    fake, chat = FakeHindsight(results=[]), Chat("PASS")
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("two lines here"), chatgpt=chat, hindsight=fake.client)
    prompt = chat.prompts[0]
    assert "The result is 3 words." in prompt and memory.MARK + " memory: chat:tray" in prompt
    assert checking.word_count("two lines here") == 3


# ---------- sr show (decision 15) ----------

def test_show_prints_the_chat_on_the_first_line_and_the_write_record(conn):
    fake = FakeHindsight()
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("two lines"), chatgpt=Chat("PASS"), hindsight=fake.client)
    code, shown = _show(conn, str(row["n"]))
    assert code == 0
    first = shown.splitlines()[0]
    assert first.startswith(f"#{row['n']}  {row['task_id']}  done  created ") and first.endswith("  chat: tray")
    assert f"memory: stored task-{row['task_id']}, {len(TASK) + 2 + len('two lines')} characters" in shown
    assert "Memory block" not in shown and "project:" not in shown


def test_show_prints_a_skipped_record_and_none(conn):
    fake = FakeHindsight(fail={"retain": 500})
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("two lines"), chatgpt=Chat("PASS"), hindsight=fake.client)
    code, shown = _show(conn, str(row["n"]))
    assert "memory: skipped: unavailable (HTTP 500 (POST /v1/default/banks/super-router/memories))" in shown
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("FIRST", "FIXED"), chatgpt=Chat("FIX\n1. x", "FIX\n1. y"),
                               hindsight=fake.client)
    code, shown = _show(conn, str(row["n"]))
    assert "memory: none" in shown  # a failed check is never stored


def test_show_memory_prints_the_block_as_sent_to_the_build_call(conn):
    one = _done(conn, "sr-1", "first task", "first result")
    fake = FakeHindsight(results=[])
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("two lines"), chatgpt=Chat("PASS"), hindsight=fake.client)
    code, shown = _show(conn, str(row["n"]), memory_flag=True)
    block = memory.render(TAG, [_entry(one)], 2000)
    assert f"Memory block as sent to {row['task_id']} (1 of 1 entries):\n{block}" in shown
    code, shown = _show(conn, str(row["n"]))
    assert "Memory block" not in shown


def test_show_memory_says_not_kept_on_an_old_row_and_nothing_remembered_on_an_empty_one(conn):
    old = _done(conn, "sr-old", "old task", "old result")  # a tagged row whose call has no memory record (before version 12)
    code, shown = _show(conn, "1", memory_flag=True)
    assert "memory: none" in shown and "Memory block: not kept (a call from before log version 12, or made with no store)." in shown
    fake = FakeHindsight(results=[])
    code, out, row, _ = _route(conn, chat="garden", worker=Scripted("two lines"), chatgpt=Chat("PASS"), hindsight=fake.client)
    code, shown = _show(conn, str(row["n"]), memory_flag=True)
    assert f"Memory block: nothing remembered under chat:garden when {row['task_id']} was sent." in shown


def test_show_memory_on_an_untagged_task_and_on_an_unavailable_store(conn):
    code, out, row, _ = _route(conn, worker=Scripted("two lines"), chatgpt=Chat("PASS"))
    code, shown = _show(conn, str(row["n"]), memory_flag=True)
    assert "This is not a tagged task, so no memory block was sent." in shown and "memory:" not in shown.replace("memory block", "")
    _done(conn, "sr-1", "first task", "first result")
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("two lines"), chatgpt=Chat("PASS"),
                               hindsight=FakeHindsight(online=False).client)
    code, shown = _show(conn, str(row["n"]), memory_flag=True)
    assert f"Memory block: the store was unavailable at {row['task_id']}; the call ran without it." in shown
    assert "memory: skipped: unavailable (" in shown


def test_show_on_a_relay_chat_task_prints_the_tag_and_the_block(conn):
    one = _done(conn, "sr-1", "first task", "first result")
    fake = FakeHindsight(results=[])
    code, out, row, hook = _relay(conn, "research-build", chat="tray", hook=RelayHook(s1=GOOD_NOTE), worker=Scripted("built"),
                                  chatgpt=Chat("PASS"), hindsight=fake.client, wait=True)
    assert code == 0, out
    code, shown = _show(conn, str(row["n"]), memory_flag=True)
    assert shown.splitlines()[0].endswith("  chat: tray")
    assert f"memory: stored task-{row['task_id']}," in shown
    assert f"Memory block as sent to {row['task_id']}-s2 (1 of 1 entries):" in shown


# ---------- sr chat list and sr log --chat ----------

def test_chat_list_prints_every_chat_with_its_count_and_newest_date_from_the_log(conn):
    _done(conn, "sr-1", "t", "r", chat="tray", at=T0)
    _done(conn, "sr-2", "t", "r", chat="garden", at=T0 + timedelta(hours=1))
    _done(conn, "sr-3", "t", "r", chat="tray", at=T0 + timedelta(days=1))
    _done(conn, "sr-4", "t", "r", chat=None, project="demo", at=T0 + timedelta(days=2))
    lines = []
    assert cli.cmd_chat(["list"], conn=conn, out=lines.append) == 0
    assert lines == ["Chats (from the log):",
                     f"  tray  2 tasks  newest {cli._local((T0 + timedelta(days=1)).isoformat())}",
                     f"  garden  1 task  newest {cli._local((T0 + timedelta(hours=1)).isoformat())}"]


def test_chat_list_with_no_chats_and_the_refusal(conn):
    lines = []
    assert cli.cmd_chat(["list"], conn=conn, out=lines.append) == 0
    assert lines == ['No chats yet. sr route "task" --chat <name> starts one.']
    for words in ([], ["show"], ["list", "tray"]):
        lines = []
        assert cli.cmd_chat(words, conn=conn, out=lines.append) == 2
        assert lines == ["Refused: sr chat list. Nothing was changed."]


def test_main_runs_sr_chat_list_and_sr_show_memory(monkeypatch, capsys):
    assert cli.main(["chat", "list"], platform="darwin") == 0
    assert capsys.readouterr().out == 'No chats yet. sr route "task" --chat <name> starts one.\n'
    assert cli.main(["show", "--memory"], platform="darwin") == 1
    assert "No tasks in the log yet." in capsys.readouterr().out


# ---------- rules 2.28, Memory, the `sr show` bullet: one line per call under --memory, after the block ----------

GROK_SKILL = {"status": "ok", "label": "x_social_pulse", "confidence": 0.95, "tokens": 0}


def _route_grok(conn, task, *, chat, hook, chatgpt, hindsight):
    """A routed task Grok does (x_social_pulse) and ChatGPT checks, waited for, with scripted webhook bodies."""
    from tests.test_relay import CONFIG, ROSTER
    from tests.test_loop import Clock
    lines, clock = [], Clock()
    code = cli.cmd_route(task, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=lambda *a, **k: dict(GROK_SKILL), post=hook.post, worker=Scripted(), chatgpt=chatgpt,
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=True, out=lines.append, chat=chat, hindsight=hindsight)
    return code, "\n".join(lines), log.recent_tasks(conn)[0]


def test_show_memory_lists_one_line_per_call_in_96s_shape(conn, monkeypatch, tmp_path):
    """#96 (2026-10-18): the Grok doer got the whole block, the ChatGPT check reused it, Grok's fix round left it out
    because the fix prompt with the block passed the limit, the re-check reused it; NOT PASSED. The lines say so."""
    import json
    from tests.test_loop import Webhook
    from router import settings
    a = _done(conn, "sr-a", "task a", "result a", at=T0)
    b = _done(conn, "sr-b", "task b", "result b", at=T0 + timedelta(hours=1))
    task = "What are gardeners on X saying about tray height? Three themes."
    block = memory.render(TAG, [_entry(b), _entry(a)], 2000)
    limit = len(task) + 2 + len(block)  # the do call fits exactly; a fix prompt with the block cannot
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"grok_prompt_limit": limit}))
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    fake = FakeHindsight(results=[FakeHindsight.result("task-sr-a", "x", tags=[TAG])])  # recall finds a; b is entry one
    hook = Webhook(do="GROK first answer", f1="GROK fixed answer")
    chat = Chat("FIX\n1. tie the themes to soil sensors", "FIX\n1. still promotional")
    code, out, row = _route_grok(conn, task, chat="tray", hook=hook, chatgpt=chat, hindsight=fake.client)
    assert code == 5 and row["check_state"] == "failed", out
    calls = log.calls_for(conn, row["task_id"])
    assert [c["kind"] for c in calls] == ["do", "check", "fix", "recheck"]
    fix_prompt = checking.fix_prompt(task, "GROK first answer", checking.read_verdict(chat.prompts and "FIX\n1. tie the themes to soil sensors")[1], count=True)
    assert hook.sent[1]["task"] == fix_prompt  # the fix prompt went whole, without the block, never failed
    with_block = len(fix_prompt) + 2 + len(block)
    assert log.call_memory_of(calls[2]) == {"tag": TAG, "found": 2, "left_out": True, "with": with_block, "limit": limit,
                                            "from": row["task_id"]}
    code, shown = _show(conn, str(row["n"]), memory_flag=True)
    tid = row["task_id"]
    assert (f"{block}\n"
            f"do grok: sent 2 of 2\n"
            f"check chatgpt: sent 2 of 2, from {tid}\n"
            f"fix grok: left out ({with_block} > {limit}), from {tid}\n"
            f"recheck chatgpt: sent 2 of 2, from {tid}\n") in shown + "\n"  # the fallback hint follows on a failed task
    code, shown = _show(conn, str(row["n"]))
    assert "do grok:" not in shown and "left out" not in shown  # only under --memory


def test_show_memory_call_lines_for_every_record_shape(conn):
    from tests.helpers import ALL_AGENTS
    log.add_task(conn, "sr-r", "t", "cli", {"status": "ok", "label": "writing", "confidence": 0.9, "tokens": 0}, chat="tray")
    log.set_route(conn, "sr-r", agents=ALL_AGENTS, agent="claude", route_reason="best", skill="writing", checker="chatgpt",
                  check_state="pending")
    log.add_call(conn, "sr-r", "sr-r", "do", "claude", status="done", text="r", memory={"tag": TAG, "found": 0, "sent": 0})
    log.add_call(conn, "sr-r-c1", "sr-r", "check", "chatgpt", status="done", text="FIX\n1. x", verdict="FIX")
    log.add_call(conn, "sr-r-f1", "sr-r", "fix", "grok", status="done", text="r2",
                 memory={"tag": TAG, "found": 2, "left_out": True, "from": "sr-r"})  # a record from before the numbers
    log.add_call(conn, "sr-r-c2", "sr-r", "recheck", "chatgpt", status="done", text="PASS", verdict="PASS",
                 memory={"tag": TAG, "unavailable": True, "reason": "x"})
    log.set_done(conn, "sr-r", "r2", check_state="fixed")
    code, shown = _show(conn, "1", memory_flag=True)
    assert shown.endswith("do claude: sent 0 of 0\n"
                          "check chatgpt: not kept\n"
                          "fix grok: left out, from sr-r\n"
                          "recheck chatgpt: unavailable")
    log.add_task(conn, "sr-v", "q", "cli", {"status": "not_asked", "tokens": 0}, mode="relay", preset="vote", chat="tray")
    log.set_route(conn, "sr-v", agents=ALL_AGENTS, agent="claude", route_reason="relay", check_state="pending")
    for n, agent in ((1, "claude"), (2, "chatgpt"), (3, "grok")):
        rec = {"tag": TAG, "found": 3, "sent": 3, "text": "b"} if n < 3 else {"tag": TAG, "found": 3, "left_out": True, "with": 900, "limit": 800}
        log.add_call(conn, f"sr-v-s{n}", "sr-v", "stage", agent, status="done", text="## Answer\nx", stage=n, role="vote", memory=rec)
    log.add_call(conn, "sr-v-s3r", "sr-v", "reask", "grok", status="done", text="## Answer\nx", stage=3, role="vote",
                 memory={"tag": TAG, "found": 3, "sent": 1, "text": "b", "from": "sr-v-s3"})
    log.set_tally(conn, "sr-v", agents=ALL_AGENTS, agent="claude", result="## Answer\nx", note="checked-by-vote 3/0")
    code, shown = _show(conn, "2", memory_flag=True)
    assert shown.endswith("stage 1 claude: sent 3 of 3\n"
                          "stage 2 chatgpt: sent 3 of 3\n"
                          "stage 3 grok: left out (900 > 800)\n"
                          "stage 3 re-ask grok: sent 1 of 3, from sr-v-s3")
