"""Build brief 22, D2 (rules v2.31, Memory "Down"; decision 8; Phase 0 choices 10 and 11): with `memory: auto`, a tagged
task's first fresh recall that finds the store down starts it (`memory_server.start`, waiting up to 60 s for `/health`)
with `waiting_on: memory` and `memory.starting` true meanwhile, one start at a time by a lock; then the backfill stores
every delivered tagged task the bank is missing (what `sr memory rebuild` does, limited to the missing ones, idempotent
by `document_id`, never clearing the bank); then the recall. A failed start: the task runs without its block, a tagged
`recall` comes back `memory_down`, as today. `memory: off` never starts it. `sr memory start` backfills too; `sr serve`
starts it at launch. Fakes only: no real store, process or clock; every value is fake."""
import json
import os

import pytest

from router import __main__ as cli
from router import locks, log, memory, memory_auto, memory_server, page, runs, settings, state, status
from tests.fake_hindsight import FakeHindsight, Ticker
from tests.helpers import fake_label, shipped_roster
from tests.test_json_actions import World, jev
from tests.test_loop import Scripted
from tests.test_relay import Chat

ROSTER = shipped_roster()
SECRETS = ["FAKE-SECRET-VALUE-1234"]


def _delivered(conn, tid, tag_kind="chat", name="trays", text="t", result="r", n_offset=0):
    log.add_task(conn, tid, text, "cli", jev("writing"), **({tag_kind: name}))
    log.set_route(conn, tid, agents=ROSTER.names, agent="claude", route_reason="best", skill="writing",
                  skill_source="jev", checker="chatgpt", check_state="pending")
    log.add_call(conn, tid, tid, "do", "claude", status="done", text=result)
    log.add_call(conn, f"{tid}-c1", tid, "check", "chatgpt", status="done", text="PASS", verdict="PASS")
    log.set_done(conn, tid, result, check_state="passed")


# ---------- the listing and the backfill ----------

def test_the_bank_lists_its_task_documents_page_by_page():
    fake = FakeHindsight(documents={f"task-sr-{i}": {"tags": ["chat:x"], "content": "c"} for i in range(250)})
    fake.documents["other-doc"] = {"tags": [], "content": "c"}
    assert fake.client.document_ids() == {f"task-sr-{i}" for i in range(250)}
    pages = [r["path"] for r in fake.of("documents")]
    assert len(pages) == 3 and all("q=task-" in p and "limit=100" in p for p in pages)


def test_the_backfill_stores_only_what_the_bank_is_missing_oldest_first_and_never_clears():
    conn = log.init_db(":memory:")
    for i in range(1, 4):
        _delivered(conn, f"sr-{i}", result=f"result {i}")
    log.add_task(conn, "sr-u", "untagged", "cli", jev("writing"))  # never stored: no tag
    fake = FakeHindsight(documents={"task-sr-2": {"tags": ["chat:trays"], "content": "already"}})
    out = []
    assert memory.backfill(conn, fake.client, SECRETS, out.append) == (2, 0)
    assert [item["document_id"] for item in fake.retains] == ["task-sr-1", "task-sr-3"]
    assert fake.of("clear") == [] and fake.of("delete_document") == []
    assert out == ["memory: backfill: stored 2, skipped 0"]
    assert [w.get("document_id") for w in log.memory_of(log.get_task(conn, "sr-1"))] == ["task-sr-1"]
    out.clear()
    assert memory.backfill(conn, fake.client, SECRETS, out.append) == (0, 0)  # idempotent
    assert out == ["memory: backfill: stored 0, skipped 0"]


def test_a_backfill_that_cannot_list_the_bank_stores_nothing():
    conn = log.init_db(":memory:")
    _delivered(conn, "sr-1")
    fake = FakeHindsight(fail={"documents": 500})
    out = []
    assert memory.backfill(conn, fake.client, SECRETS, out.append) == (0, 0)
    assert fake.retains == [] and out[0].startswith("memory: backfill skipped: HTTP 500")


# ---------- the start on its own ----------

class Starter:
    """A fake memory_server.start: brings the fake store up (or not) and records the limit it was given."""

    def __init__(self, fake, works=True):
        self.fake, self.works, self.calls = fake, works, []

    def __call__(self, client, *, limit, out):
        self.calls.append(limit)
        if self.works:
            self.fake.online = True
            return 0
        return 1


def _auto(fake, starter, conn, out, mode="auto", folder=None, task=None):
    return memory_auto.AutoStore(fake.client, mode=mode, start=starter, conn=conn, secrets=SECRETS, out=out.append,
                                 folder=folder)


def test_a_store_that_is_up_is_never_started():
    fake, out = FakeHindsight(), []
    starter = Starter(fake)
    store = _auto(fake, starter, log.init_db(":memory:"), out)
    store.recall("q", "chat:trays", max_tokens=100)
    assert starter.calls == [] and out == []


def test_a_store_that_is_down_is_started_waited_for_60_s_backfilled_then_recalled():
    conn = log.init_db(":memory:")
    _delivered(conn, "sr-1")
    fake, out = FakeHindsight(online=False), []
    starter = Starter(fake)
    store = _auto(fake, starter, conn, out)
    store.recall("q", "chat:trays", max_tokens=100)
    assert starter.calls == [memory_auto.START_SECONDS] == [60]
    assert [i["document_id"] for i in fake.retains] == ["task-sr-1"] and len(fake.of("recall")) == 1
    assert out == ["memory: the store was down; starting it (up to 60 s)", "memory: started",
                   "memory: backfill: stored 1, skipped 0"]


def test_one_start_per_command_and_a_failed_start_leaves_the_recall_to_fail_as_today():
    fake, out = FakeHindsight(online=False), []
    starter = Starter(fake, works=False)
    store = _auto(fake, starter, log.init_db(":memory:"), out)
    for _ in range(2):
        with pytest.raises(memory.Unavailable):
            store.recall("q", "chat:trays", max_tokens=100)
    assert starter.calls == [60]
    assert "memory: could not start the store (no answer within 60 s); this task runs without its memory block" in out


def test_memory_off_never_starts_the_store():
    fake, out = FakeHindsight(online=False), []
    starter = Starter(fake)
    store = _auto(fake, starter, log.init_db(":memory:"), out, mode="off")
    with pytest.raises(memory.Unavailable):
        store.recall("q", "chat:trays", max_tokens=100)
    assert starter.calls == []


def test_while_the_store_starts_the_task_waits_on_memory_and_status_says_starting(tmp_path):
    folder = tmp_path / "run"
    conn = log.init_db(tmp_path / "router.db")
    log.add_task(conn, "sr-1", "t", "cli", jev("writing"), chat="trays", run=runs.me())
    runs.adopt("sr-1")
    fake, out, seen = FakeHindsight(online=False), [], []

    def start(client, *, limit, out):
        row = log.get_task(conn, "sr-1")
        seen.append((locks.waiting_on(folder, row), locks.holder(folder, "memory") is not None,
                     state.of(row, [], waiting=locks.waiting_on(folder, row)).waiting_on))
        fake.online = True
        return 0

    store = memory_auto.AutoStore(fake.client, mode="auto", start=start, conn=conn, secrets=SECRETS, out=out.append,
                                  folder=folder)
    store.recall("q", "chat:trays", max_tokens=100)
    assert seen == [("memory", True, "memory")]
    assert locks.waiting_on(folder, log.get_task(conn, "sr-1")) is None and locks.holder(folder, "memory") is None
    runs.release(conn, "sr-1")


def test_the_start_waits_up_to_the_limit_it_is_given(tmp_path):
    binary = tmp_path / ".hindsight" / "venv" / "bin" / "hindsight-api"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    fake, ticker, lines = FakeHindsight(online=False), Ticker(), []

    class Proc:
        pid = 777

        def poll(self):
            return None  # still starting

    code = memory_server.start(fake.client, environ={}, home=tmp_path, popen=lambda *a, **k: Proc(), sleep=ticker.sleep,
                               clock=ticker.now, out=lines.append, limit=60)
    assert code == 1 and 60 <= ticker.t < 63
    assert any("has not answered after 60 s" in line for line in lines)


# ---------- through the commands ----------

@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    return World(monkeypatch, tmp_path, capsys)


def test_a_tagged_task_finds_the_store_down_starts_it_and_its_call_carries_its_memory_record(world, monkeypatch):
    fake = FakeHindsight(online=False)
    monkeypatch.setattr(cli.memory, "client", lambda request, **kw: fake.client)
    monkeypatch.setattr(cli.memory_auto, "starter", lambda **kw: Starter(fake))
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("red, green and blue")
    found = world.json("route", "name the three primary colors of light", "--chat", "brief22")
    assert found["exit"] == 0
    assert "memory: backfill: stored 0, skipped 0" in found["message"]
    conn = log.init_db(cli.DB_PATH)
    call = log.calls_for(conn, log.task_by_number(conn, 1)["task_id"])[0]
    conn.close()
    record = log.call_memory_of(call)
    assert record["tag"] == "chat:brief22" and not record.get("unavailable")


def test_a_tagged_recall_task_whose_store_cannot_start_comes_back_as_today(world, monkeypatch):
    fake = FakeHindsight(online=False)
    monkeypatch.setattr(cli.memory, "client", lambda request, **kw: fake.client)
    monkeypatch.setattr(cli.memory_auto, "starter", lambda **kw: Starter(fake, works=False))
    world.label, world.worker = fake_label(jev("recall", 0.99)), Scripted("never")
    found = world.json("route", "what did we decide", "--chat", "trays")
    assert (found["status"], found["reason_code"]) == ("returned", "memory_down") and world.worker.prompts == []


def test_status_says_memory_is_starting_while_the_lock_is_held(world, monkeypatch, tmp_path):
    monkeypatch.setattr(cli.online, "run_all", lambda checks, now=None: {})
    monkeypatch.setattr(cli.memory, "client", lambda request, **kw: FakeHindsight(online=False).client)
    folder = cli.DB_PATH.parent / runs.FOLDER_NAME
    with locks.held("memory", folder=folder):
        doc = json.loads(world.run("status", "--json")[1])
    assert doc["memory"]["starting"] is True
    doc = json.loads(world.run("status", "--json")[1])
    assert doc["memory"]["starting"] is False


def test_sr_memory_start_backfills_after_the_start_and_when_already_online(tmp_path):
    db = tmp_path / "router.db"
    conn = log.init_db(db)
    _delivered(conn, "sr-1")
    conn.close()
    fake = FakeHindsight()
    lines = []
    code = cli.cmd_memory(["start"], request=fake.request, environ={}, home=tmp_path, popen=None, sleep=None, clock=None,
                          kill=None, db_path=db, secrets=SECRETS, out=lines.append)
    assert code == 0 and "memory: backfill: stored 1, skipped 0" in lines
    assert [i["document_id"] for i in fake.retains] == ["task-sr-1"]


def test_sr_serve_starts_memory_at_launch_when_it_is_auto(monkeypatch):
    ran = []

    def run(argv, **kw):
        ran.append(argv)
        return type("P", (), {"returncode": 0, "stdout": "memory: online\n", "stderr": ""})()

    lines = []
    page.start_memory(run=run, out=lines.append)
    assert ran == [page.sr("memory", "start")] and lines == ["memory: online"]
    seen = {}
    monkeypatch.setattr(cli.page, "serve", lambda port, out=print, start_memory=None: seen.update(start=start_memory) or 0)
    monkeypatch.setattr(cli.settings, "memory_mode", lambda: "auto")
    cli.main(["serve"], platform="darwin")
    assert seen["start"] is page.start_memory
    monkeypatch.setattr(cli.settings, "memory_mode", lambda: "off")
    cli.main(["serve"], platform="darwin")
    assert seen["start"] is None


def test_memory_is_no_longer_reserved():
    assert state.RESERVED == () and "memory" in state.WAITING_ON


def test_a_backfilled_task_keeps_its_delivery_date_in_its_memory_heading():
    """The owner's go before the switch-over (open issue 1): a memory write never moves the row's `updated_at`, so a task
    the backfill stores long after its delivery still heads its memory entry with its delivery date, and a later rebuild
    stores that date again."""
    conn = log.init_db(":memory:")
    _delivered(conn, "sr-1", result="trays: two lines")
    delivered = "2026-10-01T12:00:00+00:00"  # delivered on 1 Oct while the store was down: nothing retained then
    conn.execute("UPDATE tasks SET updated_at = ? WHERE task_id = ?", (delivered, "sr-1"))
    conn.commit()
    assert memory.local_date(delivered) != memory.local_date(log._iso())  # a moved date would show
    fake = FakeHindsight()
    assert memory.backfill(conn, fake.client, SECRETS, [].append) == (1, 0)
    row = log.get_task(conn, "sr-1")
    assert row["updated_at"] == delivered and log.memory_of(row)[0]["document_id"] == "task-sr-1"
    assert fake.retains[-1]["timestamp"] == delivered
    log.add_task(conn, "sr-2", "what did we say about trays", "cli", jev("writing"), chat="trays")
    found = memory.gather(conn, log.get_task(conn, "sr-2"), fake.client, SECRETS, max_items=5, max_chars=2000,
                          query_chars=500)
    assert found.entries[0].heading().startswith(f"### #1 · {memory.local_date(delivered)} · writing · claude")
    memory.rebuild(conn, fake.client, SECRETS, [].append)
    assert fake.retains[-1]["timestamp"] == delivered and log.get_task(conn, "sr-1")["updated_at"] == delivered
