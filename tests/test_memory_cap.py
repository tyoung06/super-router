"""The memory brief, step 6 (rules 2.56, Memory "Caps, in code"): each memory is at most 8,000 characters
(`memory_max_chars`, shipped and as the default); a longer one is cut there and ends with ` [cut]`. Fake store; every
value here is fake."""
import pytest

from router import context, log, memory, settings
from tests.fake_hindsight import FakeHindsight
from tests.test_memory_block import _done, _queued


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def test_the_cap_is_8000_shipped_and_by_default():
    assert settings.memory_setting("memory_max_chars") == (8000, "config/settings.json")
    assert settings.MEMORY_DEFAULTS["memory_max_chars"] == 8000
    assert memory.caps()["max_chars"] == 8000


def test_a_9000_character_memory_is_cut_at_8000_with_the_mark(conn):
    _done(conn, "sr-1", "t", "x" * 9000)
    running = _queued(conn)
    _, _, mem = context.attach("p", running, "claude", [], conn=conn, hindsight=FakeHindsight(results=[]).client)
    body = memory.entries_of_block(mem["text"])[0].text
    assert body == ("t\n\n" + "x" * 9000)[:8000] + memory.CUT and len(body) == 8000 + len(memory.CUT)


def test_a_7900_character_memory_goes_whole(conn):
    _done(conn, "sr-1", "t", "y" * 7900)
    running = _queued(conn)
    _, _, mem = context.attach("p", running, "claude", [], conn=conn, hindsight=FakeHindsight(results=[]).client)
    assert memory.CUT not in mem["text"] and "y" * 7900 in mem["text"]
