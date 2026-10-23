"""Build brief 27 (rules 2.38, Memory, The switch; decisions 6 and 7): off means off. With `memory: off` the router neither
starts the store nor recalls nor retains, even while the store runs: a tagged call carries no block and its record says
off; a delivery gets the write record `{"skipped": "off", "state": …}` and the line `memory: off; not saved`; a block a
round, a re-ask, a resume or a fallback reuses rides as before. A task delivered while off is never remembered later:
the backfill, the rebuild and entry one skip it; delivered again while on (a fallback), it is stored. The setting is read
at each fresh recall and each delivery. A fake store records every request; fake agents; every value here is fake."""
import pytest

from router import __main__ as cli
from router import jsonview, log, memory, memory_auto
from tests.fake_hindsight import FakeHindsight
from tests.helpers import set_local
from tests.test_chat_intake import _relay, _route
from tests.test_collab import LOADED
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_memory_block import TAG, TASK, _block, _done, _entry
from tests.test_relay import CONFIG, ROSTER, SECRET, Chat
from tests.test_resume_run import claude_limit
from tests.test_route_v2 import ok

OFF_LINE = "memory: off; not saved"
BACK_OFF = "memory unavailable (memory is off in settings): nothing to recall from"


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def off():
    set_local(memory="off")


def on():
    set_local(memory="auto")


def _writes(row):
    return [{k: v for k, v in w.items() if k != "at"} for w in log.memory_of(row)]


def _records(conn, task_id):
    return [log.call_memory_of(c) for c in log.calls_for(conn, task_id)]


class Switching(Scripted):
    """A fake agent that switches memory as it answers, so the next read of the setting sees the change."""

    def __init__(self, to, *replies):
        super().__init__(*replies)
        self.to = to

    def __call__(self, prompt):
        set_local(memory=self.to)
        return super().__call__(prompt)


# ---------- a routed task while off ----------

def test_a_routed_task_while_off_never_reaches_the_store(conn):
    _done(conn, "sr-1", "first task", "first result")
    off()
    fake = FakeHindsight(results=[])
    worker, chat = Scripted("two lines"), Chat("PASS")
    code, out, row, _ = _route(conn, chat="tray", worker=worker, chatgpt=chat, hindsight=fake.client)
    assert code == 0 and row["check_state"] == "passed", out
    assert fake.recalls == [] and fake.retains == []
    assert worker.prompts == [TASK] and memory.start_marker(TAG) not in chat.prompts[0]  # no block on any call
    assert _records(conn, row["task_id"]) == [{"tag": TAG, "off": True}, {"tag": TAG, "off": True, "from": row["task_id"]}]
    assert _writes(row) == [{"skipped": "off", "state": "done/passed/2"}]
    assert OFF_LINE in out.splitlines()


def test_a_relay_while_off_never_reaches_the_store(conn):
    _done(conn, "sr-1", "first task", "first result")
    off()
    fake = FakeHindsight(results=[])
    code, out, row, _ = _relay(conn, "collab", chat="tray", worker=Scripted("PLAN", "BUILT"),
                               chatgpt=Chat("AMENDED", "## Edited\nBUILT\n\n## Unresolved\nnone"), hindsight=fake.client, wait=True)
    assert fake.recalls == [] and fake.retains == [], out
    assert all(r is None or r.get("off") for r in _records(conn, row["task_id"]))


def test_a_resume_and_a_fallback_while_off_never_reach_the_store(conn):
    _done(conn, "sr-1", "first task", "first result")
    off()
    fake = FakeHindsight(results=[])
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted(claude_limit()), hindsight=fake.client)
    lines, clock, hook = [], Clock(), Webhook()
    cli.cmd_resume([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[],
                   post=hook.post, worker=Scripted("PASS"), chatgpt=Chat("two lines"), codex_login=lambda: True,
                   fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True, out=lines.append,
                   hindsight=fake.client)
    code, out, row2, _ = _route(conn, "Two more lines.", chat="tray", worker=Scripted("FIRST", "FIXED"),
                                chatgpt=Chat("FIX\n1. x", "FIX\n1. y"), hindsight=fake.client)
    assert row2["check_state"] == "failed"
    cli.cmd_fallback([str(row2["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[],
                     post=hook.post, worker=Scripted("PASS"), chatgpt=Chat("REDO"), codex_login=lambda: True,
                     fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True, out=lines.append,
                     hindsight=fake.client)
    assert fake.recalls == [] and fake.retains == [], "\n".join(lines)
    assert _writes(log.get_task(conn, row["task_id"]))[-1]["skipped"] == "off"
    assert _writes(log.get_task(conn, row2["task_id"]))[-1]["skipped"] == "off"


def test_a_tagged_recall_task_while_off_comes_back_before_any_call(conn):
    _done(conn, "sr-1", "first task", "we decided rubber")
    off()
    fake, worker = FakeHindsight(results=[]), Scripted("never")
    code, out, row, _ = _route(conn, "what did we decide", chat="tray", jev=ok("recall"), worker=worker, hindsight=fake.client)
    assert code == 4 and row["status"] == "returned" and row["check_note"] == BACK_OFF and row["reason_code"] == "memory_down"
    assert worker.prompts == [] and fake.recalls == []


# ---------- a switch between calls ----------

def test_a_block_recalled_while_on_still_rides_on_the_check_after_a_switch_to_off_and_is_not_stored(conn):
    one = _done(conn, "sr-1", "first task", "first result")
    fake = FakeHindsight(results=[])
    chat = Chat("PASS")
    code, out, row, _ = _route(conn, chat="tray", worker=Switching("off", "two lines"), chatgpt=chat, hindsight=fake.client)
    block = _block([_entry(one)])
    assert len(fake.recalls) == 1 and chat.prompts[0].endswith("\n\n" + block)  # the reused block rides
    assert fake.retains == [] and _writes(row) == [{"skipped": "off", "state": "done/passed/2"}]


def test_a_call_made_while_off_then_delivered_while_on_is_stored(conn):
    _done(conn, "sr-1", "first task", "first result")
    off()
    fake = FakeHindsight(results=[])
    code, out, row, _ = _route(conn, chat="tray", worker=Switching("auto", "two lines"), hindsight=fake.client)
    assert fake.recalls == [] and _records(conn, row["task_id"])[0] == {"tag": TAG, "off": True}
    assert len(fake.retains) == 1 and _writes(row)[-1]["document_id"] == f"task-{row['task_id']}"


# ---------- never remembered later ----------

def _off_task(conn, task_id="sr-2", task="second task"):
    row = _done(conn, task_id, task, "second result")
    log.add_memory_write(conn, task_id, {"skipped": "off", "state": "done/passed/2"})
    return log.get_task(conn, task_id)


def test_a_task_delivered_while_off_is_not_storable_but_store_judges_by_the_setting_now(conn):
    row = _off_task(conn)
    assert memory.storable(row) is False and memory.storable(row, off_counts=False) is True
    other = _done(conn, "sr-3", "third", "r")
    log.add_memory_write(conn, "sr-3", {"skipped": "unavailable (down)", "state": "done/passed/2"})
    assert memory.storable(log.get_task(conn, "sr-3")) is True  # only off keeps it out


def test_entry_one_skips_a_task_delivered_while_off(conn):
    one = _done(conn, "sr-1", "first task", "first result")
    _off_task(conn)
    assert memory.newest_storable(conn, TAG, "sr-run")["task_id"] == one["task_id"]


def test_the_backfill_and_the_rebuild_skip_a_task_delivered_while_off(conn):
    _done(conn, "sr-1", "first task", "first result")
    _off_task(conn)
    fake = FakeHindsight(results=[])
    lines = []
    assert memory.backfill(conn, fake.client, [SECRET], lines.append) == (1, 0)
    assert [r["document_id"] for r in fake.retains] == ["task-sr-1"]
    assert memory.rebuild(conn, fake.client, [SECRET], lines.append) == (1, 0)
    assert [r["document_id"] for r in fake.retains] == ["task-sr-1", "task-sr-1"]
    assert _writes(log.get_task(conn, "sr-2")) == [{"skipped": "off", "state": "done/passed/2"}]  # still only its off record


def test_a_task_delivered_while_off_and_again_while_on_is_stored(conn):
    off()
    fake = FakeHindsight(results=[])
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("FIRST", "FIXED"), chatgpt=Chat("FIX\n1. x", "FIX\n1. y"),
                               hindsight=fake.client)
    assert row["check_state"] == "failed" and fake.retains == []
    on()
    lines, clock, hook = [], Clock(), Webhook()
    code = cli.cmd_fallback([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                            settings_paths=[], post=hook.post, worker=Scripted("PASS"), chatgpt=Chat("REDO"),
                            codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                            wait=True, out=lines.append, hindsight=fake.client)
    assert code == 0, "\n".join(lines)
    row = log.get_task(conn, row["task_id"])
    assert [r["document_id"] for r in fake.retains] == [f"task-{row['task_id']}"]
    assert _writes(row)[-1]["document_id"] == f"task-{row['task_id']}" and memory.storable(row)


# ---------- the store's own start, and the words ----------

def test_the_autostore_reads_the_setting_at_each_start_not_once(conn, tmp_path):
    fake = FakeHindsight(online=False)
    started = []
    store = memory_auto.wrap(fake.client, conn=conn, secrets=[], out=lambda *a: None, folder=tmp_path,
                             start=lambda client, **k: started.append(1) or 2)
    off()
    store.ensure()
    assert started == []
    on()
    store.ensure()
    assert started == [1]


def test_store_while_off_writes_the_skip_record_once_per_ending_and_never_asks_the_store(conn):
    off()
    row = _done(conn, "sr-1", "first task", "first result")
    fake = FakeHindsight(results=[])
    calls = log.calls_for(conn, "sr-1")
    assert memory.store(conn, row, calls, fake.client, [SECRET]) == ({"skipped": "off", "state": "done/passed/2"}, OFF_LINE)
    log.add_memory_write(conn, "sr-1", {"skipped": "off", "state": "done/passed/2"})
    assert memory.store(conn, log.get_task(conn, "sr-1"), calls, fake.client, [SECRET]) is None
    unchecked = _done(conn, "sr-2", "second", "r", check_state="unchecked")
    assert memory.store(conn, unchecked, log.calls_for(conn, "sr-2"), fake.client, [SECRET]) is None
    assert fake.requests == []


def test_show_memory_and_the_json_say_off(conn):
    off()
    fake = FakeHindsight(results=[])
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("two lines"), hindsight=fake.client)
    calls = log.calls_for(conn, row["task_id"])
    assert cli._call_memory_lines(calls) == ["do claude: off", f"check chatgpt: off, from {row['task_id']}"]
    assert jsonview._call_memory(calls[0])["state"] == "off"
    assert jsonview._call_memory(calls[1])["from"] == row["task_id"]
