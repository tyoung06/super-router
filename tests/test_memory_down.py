"""The memory brief, step 2 (rules 2.56, Memory "Down"): a store that can't be reached still gives a tagged task its
newest tasks, read from the log, with no search. The record stays `unavailable`, with what it sent; a check, fix or
re-check round reuses the same block; a tagged recall task still comes back; `memory: off` stays off. Fake agents, a
fake store; every value here is fake."""
from datetime import timedelta

import pytest

from router import __main__ as cli
from router import context, jsonview, log, memory
from tests.fake_hindsight import FakeHindsight
from tests.helpers import set_local
from tests.test_chat_intake import _route
from tests.test_loop import Scripted
from tests.test_memory_block import DOER, L, T0, TAG, _block, _done, _entry, _queued
from tests.test_relay import SECRET, Chat

DOWN_LINE = "memory: the store is down; this task gets its 2 newest tasks from the log, with no search"
OLD_LINE = "memory: unavailable; this task runs without its memory block"


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _two(conn):
    one = _done(conn, "sr-1", "first task", "first result", at=T0)
    two = _done(conn, "sr-2", "second task", "second result", at=T0 + timedelta(hours=1))
    return one, two


def test_store_down_the_newest_go_from_the_log_on_every_round_with_one_line(conn):
    one, two = _two(conn)
    fake = FakeHindsight(online=False)
    worker, chat = Scripted("FIRST", "FIXED"), Chat("FIX\n1. x", "PASS")
    code, out, row, _ = _route(conn, chat="tray", worker=worker, chatgpt=chat, hindsight=fake.client)
    assert code == 0 and row["status"] == "done" and row["check_state"] == "fixed", out
    block = _block([_entry(two), _entry(one)])
    assert worker.prompts[0] == f"{DOER}\n\n{L}{block}"
    assert chat.prompts[0].endswith("\n\n" + L + block) and worker.prompts[1].endswith("\n\n" + L + block)
    assert chat.prompts[1].endswith("\n\n" + L + block)
    assert out.count(DOWN_LINE) == 1 and OLD_LINE not in out
    calls = log.calls_for(conn, row["task_id"])
    first = log.call_memory_of(calls[0])
    assert first["unavailable"] is True and first["reason"] and first["sent"] == 2 and first["found"] == 2
    assert first["text"] == block and first["query"] == "Write two lines about seed trays.\nsecond task"
    for c in calls[1:]:
        assert log.call_memory_of(c) == {"tag": TAG, "from": row["task_id"], "unavailable": True, "found": 2, "sent": 2,
                                         "text": block}


def test_store_down_with_nothing_delivered_yet_keeps_todays_words_and_no_block(conn):
    worker = Scripted("two lines")
    code, out, row, _ = _route(conn, chat="tray", worker=worker, chatgpt=Chat("PASS"),
                               hindsight=FakeHindsight(online=False).client)
    assert code == 0 and memory.MARK not in worker.prompts[0] and out.count(OLD_LINE) == 1
    record = log.call_memory_of(log.calls_for(conn, row["task_id"])[0])
    assert record["unavailable"] is True and not record.get("sent") and "text" not in record


def test_a_tagged_recall_task_still_comes_back_with_the_store_down(conn):
    _two(conn)
    worker = Scripted("never")
    code, out, row, _ = _route(conn, "what did we decide about trays", chat="tray",
                               jev={"status": "ok", "label": "recall", "confidence": 0.9, "tokens": 0},
                               worker=worker, chatgpt=Chat("never"), hindsight=FakeHindsight(online=False).client)
    assert code == 4 and row["status"] == "returned" and worker.prompts == []
    assert log.calls_for(conn, row["task_id"]) == []


def test_memory_off_with_the_store_down_sends_no_block(conn):
    _two(conn)
    set_local(memory="off")
    worker = Scripted("two lines")
    code, out, row, _ = _route(conn, chat="tray", worker=worker, chatgpt=Chat("PASS"),
                               hindsight=FakeHindsight(online=False).client)
    assert code == 0 and memory.MARK not in worker.prompts[0] and "memory: the store is down" not in out


def test_an_old_unavailable_record_with_no_text_reused_gives_no_block(conn):
    _two(conn)
    running = _queued(conn)
    log.add_call(conn, "sr-run", "sr-run", "do", "claude", status="done", text="r",
                 memory={"tag": TAG, "unavailable": True, "reason": "ConnectionError (POST /x)"})
    prompt, _, mem = context.attach("p", running, "chatgpt", [SECRET], conn=conn, hindsight=FakeHindsight().client,
                                    reuse=log.get_call(conn, "sr-run"))
    assert prompt == "p" and mem == {"tag": TAG, "from": "sr-run", "unavailable": True}


def test_store_down_on_grok_a_block_that_cannot_fit_stays_unavailable_with_no_left_out(conn):
    _done(conn, "sr-1", "first task", "x" * 3000, at=T0)
    running = _queued(conn)
    prompt, _, mem = context.attach("p", running, "grok", [SECRET], limit=500, conn=conn,
                                    hindsight=FakeHindsight(online=False).client)
    assert prompt == "p" and mem["unavailable"] is True and "left_out" not in mem and "sent" not in mem


# ---------- what the owner sees ----------

def _show(conn, n):
    lines = []
    cli.cmd_show(conn=conn, words=[str(n)], memory=True, handoff=False, secrets=[SECRET], out=lines.append)
    return "\n".join(lines)


def test_show_json_and_lines_read_the_store_down_block(conn):
    _two(conn)
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("two lines"), chatgpt=Chat("PASS"),
                               hindsight=FakeHindsight(online=False).client)
    shown = _show(conn, row["n"])
    calls = log.calls_for(conn, row["task_id"])
    assert f"Memory block: the store was down at {calls[0]['call_id']}; it sent the newest 2 from the log:" in shown
    assert log.call_memory_of(calls[0])["text"] in shown
    assert "do claude: unavailable, sent 2 from the log" in shown
    assert f"check chatgpt: unavailable, sent 2 from the log, from {calls[0]['call_id']}" in shown
    view = jsonview._call_memory(calls[0])
    assert (view["state"], view["sent"], view["found"]) == ("unavailable", 2, 2)


def test_an_old_unavailable_record_keeps_todays_words(conn):
    _done(conn, "sr-1", "first task", "first result")
    running = _queued(conn)
    log.add_call(conn, "sr-run", "sr-run", "do", "claude", status="done", text="r",
                 memory={"tag": TAG, "unavailable": True, "reason": "x"})
    log.set_done(conn, "sr-run", "r", check_state="passed")
    shown = _show(conn, running["n"])
    assert "Memory block: the store was unavailable at sr-run; the call ran without it." in shown
    assert "do claude: unavailable" in shown and "from the log" not in shown
    view = jsonview._call_memory(log.calls_for(conn, "sr-run")[0])
    assert (view["state"], view["sent"], view["found"]) == ("unavailable", None, None)
