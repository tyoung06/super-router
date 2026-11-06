"""The memory brief, step 4 (rules 2.56, Memory "Caps, in code"): a recall asks Hindsight for up to
`memory_fetch_tokens` tokens of matching text, a setting (2,000 shipped: the answer key's choice, the owner's option A
at stop 3), never a number in the code. Fake store; every value here is fake."""
import pytest

from router import context, log, memory, settings
from tests.fake_hindsight import FakeHindsight
from tests.helpers import set_local
from tests.test_memory_block import TAG, _done, _queued


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def test_the_shipped_fetch_size_is_2000_and_caps_carry_it():
    assert settings.memory_setting("memory_fetch_tokens") == (2000, "config/settings.json")
    assert memory.caps()["fetch_tokens"] == 2000
    assert not hasattr(memory, "RECALL_MAX_TOKENS")  # the setting, never a number in the code


def test_the_recall_request_carries_the_setting(conn):
    _done(conn, "sr-1", "first task", "first result")
    running = _queued(conn)
    fake = FakeHindsight(results=[])
    context.attach("p", running, "claude", [], conn=conn, hindsight=fake.client)
    assert [r["max_tokens"] for r in fake.recalls] == [2000]
    set_local(memory_fetch_tokens=4000)
    fake = FakeHindsight(results=[])
    context.attach("p", running, "claude", [], conn=conn, hindsight=fake.client)
    assert [r["max_tokens"] for r in fake.recalls] == [4000]


@pytest.mark.parametrize("bad", ["lots", 0, -5, 2.5, True])
def test_a_bad_value_falls_back_to_the_default_with_its_reason(bad):
    set_local(memory_fetch_tokens=bad)
    value, why = settings.memory_setting("memory_fetch_tokens")
    assert value == 2000 and why.startswith("default; memory_fetch_tokens") and "positive whole number" in why


def test_gather_reads_the_setting_when_not_given(conn):
    _done(conn, "sr-1", "first task", "first result")
    running = _queued(conn)
    fake = FakeHindsight(results=[])
    caps = {k: v for k, v in memory.caps().items() if k != "fetch_tokens"}
    memory.gather(conn, running, fake.client, [], **caps)
    assert fake.recalls[0]["max_tokens"] == 2000 and fake.recalls[0]["tags"] == [TAG]
