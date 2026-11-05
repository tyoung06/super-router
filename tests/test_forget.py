"""Brief 30, decision 15 (rules 2.43, Memory, Forget): `sr forget <n>` adds a `forgotten` record and `memory.storable`
refuses the task, so no block carries it (newest three or match), the query never takes its text, a recall naming it is
dropped, the backfill and the rebuild never store it; its document leaves the bank now, or with the next backfill.
`--undo` (Remember again) adds `remembered` and stores it again by today's rules (never a delivery made while memory was
off). The log keeps the task; a block already sent never changes; HANDOFF.md is never touched. A fake store; every value
here is fake."""
import json
from datetime import timedelta

import pytest

from router import __main__ as cli
from router import context, jsonview, log, memory, receipt
from tests.fake_hindsight import FakeHindsight
from tests.helpers import set_local
from tests.test_memory_block import T0, TAG, TASK, _done, _queued

DAY = "2026-10-28"


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _forget(conn, row, fake, undo=False):
    out = receipt.Receipt()
    code = cli.cmd_forget([str(row["n"])], conn=conn, undo=undo, client=fake.client if fake else None, out=out)
    return code, out


def test_forget_adds_its_record_and_the_task_is_no_longer_storable(conn):
    row = _done(conn, "sr-1", "first task", "first result", at=T0)
    assert memory.storable(row)
    code, out = _forget(conn, row, FakeHindsight())
    assert code == 0, out.message
    row = log.get_task(conn, "sr-1")
    assert log.memory_of(row)[-1]["forgotten"] and not memory.storable(row) and memory.forgotten(row)
    assert out.extra["memory"]["forgotten"] == memory.forgotten(row)
    assert log.get_task(conn, "sr-1")["result"] == "first result"  # the log keeps it


def test_no_block_carries_it_the_query_skips_it_and_a_recall_naming_it_is_dropped(conn):
    one = _done(conn, "sr-1", "first task", "first result", at=T0)
    two = _done(conn, "sr-2", "second task with a secret word", "second result", at=T0 + timedelta(hours=1))
    _forget(conn, two, FakeHindsight())
    running = _queued(conn)
    fake = FakeHindsight(results=[FakeHindsight.result("task-sr-2", "second result", tags=[TAG]),
                                  FakeHindsight.result("task-sr-1", "first result", tags=[TAG])])
    prompt, _, mem = context.attach("p", running, "claude", [], conn=conn, hindsight=fake.client)
    assert "second task" not in prompt and "first task" in prompt  # not among the newest, not a match
    assert fake.recalls[0]["query"] == f"{TASK}\nfirst task"  # the previous task's text is the newest storable's
    assert mem["found"] == 1 and one["n"] == 1


def test_the_document_is_deleted_now_when_the_store_answers_else_by_the_backfill(conn):
    row = _done(conn, "sr-1", "first task", "first result", at=T0)
    fake = FakeHindsight(documents={"task-sr-1": {"document_id": "task-sr-1", "tags": [TAG]}})
    code, out = _forget(conn, row, fake)
    assert code == 0 and "task-sr-1" not in fake.documents and "deleted from the bank" in out.message
    row2 = _done(conn, "sr-2", "second", "second result", at=T0)
    down = FakeHindsight(online=False)
    code, out = _forget(conn, row2, down)
    assert code == 0 and "the next backfill deletes task-sr-2" in out.message
    later = FakeHindsight(documents={"task-sr-2": {"document_id": "task-sr-2", "tags": [TAG]}})
    lines = []
    memory.backfill(conn, later.client, [], lines.append)
    assert "task-sr-2" not in later.documents and any("deleted 1 forgotten" in line for line in lines)
    assert all(item["document_id"] != "task-sr-2" for item in later.retains)  # never stored again


def test_the_rebuild_never_stores_a_forgotten_task(conn):
    row = _done(conn, "sr-1", "first task", "first result", at=T0)
    _done(conn, "sr-2", "second task", "second result", at=T0)
    _forget(conn, row, FakeHindsight())
    fake = FakeHindsight()
    memory.rebuild(conn, fake.client, [], lambda line: None)
    assert [item["document_id"] for item in fake.retains] == ["task-sr-2"]


def test_remember_again_stores_it_now_and_never_a_delivery_made_while_off(conn):
    row = _done(conn, "sr-1", "first task", "first result", at=T0)
    _forget(conn, row, FakeHindsight())
    fake = FakeHindsight()
    code, out = _forget(conn, log.get_task(conn, "sr-1"), fake, undo=True)
    assert code == 0 and "stored in the bank again" in out.message
    assert [item["document_id"] for item in fake.retains] == ["task-sr-1"]
    assert memory.storable(log.get_task(conn, "sr-1")) and memory.forgotten(log.get_task(conn, "sr-1")) is None
    off = _done(conn, "sr-2", "second task", "second result", at=T0)
    log.add_memory_write(conn, "sr-2", {"skipped": "off", "state": "done/passed/2"})  # delivered while memory was off
    _forget(conn, log.get_task(conn, "sr-2"), FakeHindsight())
    fake = FakeHindsight()
    code, out = _forget(conn, log.get_task(conn, "sr-2"), fake, undo=True)
    assert code == 0 and fake.retains == [] and "never storable" in out.message
    assert off["n"] == 2


def test_refusals_an_open_task_an_untagged_task_and_a_piece(conn):
    running = _queued(conn)
    code, out = _forget(conn, running, FakeHindsight())
    assert code == 2 and out.code == "wrong_state" and log.memory_of(log.get_task(conn, running["task_id"])) == []
    plain = _done(conn, "sr-p", "plain", "r", chat=None, at=T0)
    code, out = _forget(conn, plain, FakeHindsight())
    assert code == 2 and out.code == "nothing_stored"
    row = _done(conn, "sr-1", "first", "r", at=T0)
    _forget(conn, row, FakeHindsight())
    code, out = _forget(conn, log.get_task(conn, "sr-1"), FakeHindsight())
    assert code == 2 and out.code == "wrong_state" and "already forgotten" in out.message


def test_a_block_already_sent_never_changes(conn):
    one = _done(conn, "sr-1", "first task", "first result", at=T0)
    running = _queued(conn)
    fake = FakeHindsight(results=[])
    _, _, mem = context.attach("p", running, "claude", [], conn=conn, hindsight=fake.client)
    log.add_call(conn, "sr-run", "sr-run", "do", "claude", status="done", text="r", memory=mem)
    _forget(conn, one, FakeHindsight())
    prompt, _, again = context.attach("p", running, "chatgpt", [], conn=conn, hindsight=fake.client,
                                      reuse=log.get_call(conn, "sr-run"))
    assert "first task" in prompt and again["text"] == mem["text"]  # the check reuses what the doer was sent


def test_show_and_the_json_say_forgotten_and_offer_remember_again(conn):
    row = _done(conn, "sr-1", "first task", "first result", at=T0)
    view = jsonview.task_view(conn, log.get_task(conn, "sr-1"))
    assert view["forgotten"] is None and view["card_actions"] == {"pin": True, "save": True, "forget": True,
                                                                  "remember": False}
    _forget(conn, row, FakeHindsight())
    view = jsonview.task_view(conn, log.get_task(conn, "sr-1"))
    assert view["forgotten"] and view["card_actions"]["remember"] is True and view["card_actions"]["forget"] is False
    lines = []
    cli.cmd_show(conn=conn, words=["1"], out=lines.append)
    assert any(line.startswith(f"memory: forgotten {view['forgotten']}") for line in lines)


def test_memory_off_leaves_the_bank_alone_and_the_backfill_does_it(conn):
    set_local(memory="off")
    row = _done(conn, "sr-1", "first task", "first result", at=T0)
    fake = FakeHindsight(documents={"task-sr-1": {"document_id": "task-sr-1", "tags": [TAG]}})
    code, out = _forget(conn, row, fake)
    assert code == 0 and "task-sr-1" in fake.documents and "memory is off" in out.message
    assert json.dumps(out.extra) and memory.forgotten(log.get_task(conn, "sr-1"))
