"""Brief 29.1 (decisions 25 and 26, D18 fixes 3 and 4): the memory block starts with the tag's newest three delivered tasks,
newest first, read from the log and never ranked; then up to five search matches not among them, newest first: at most
eight memories, each at most 2,000 characters (`memory_newest` 3 and `memory_matches` 5 in config/settings.json, in place
of `memory_max_items`). A Grok call trims the matches first, oldest first, then the newest tasks from the oldest, and
leaves the block out only when the newest task alone can't fit. The recall query is the task's text, a line break and
the newest delivered task's text, cut to 1,500 characters by cutting the earlier text first; a tag's first task searches
with its own text. Fakes only; every value fake."""
import json
from datetime import timedelta

import pytest

from router import context, log, memory, settings
from tests.fake_hindsight import FakeHindsight
from tests.test_memory_block import T0, _attach, _done, _entry, _queued, conn  # noqa: F401 (the fixture)

TAG = "chat:tray"


def _rows(conn, k):
    return [_done(conn, f"sr-{i}", f"task {i}", f"result {i}", at=T0 + timedelta(hours=i)) for i in range(1, k + 1)]


def _results(*ns):
    return [FakeHindsight.result(f"task-sr-{n}", "x", tags=[TAG]) for n in ns]


def test_the_settings_are_newest_three_and_five_matches():
    doc = json.loads((settings.SETTINGS_PATH).read_text()) if settings.SETTINGS_PATH.exists() else {}
    assert (doc.get("memory_newest"), doc.get("memory_matches")) == (3, 5) and "memory_max_items" not in doc
    assert memory.caps() == {"newest": 3, "matches": 5, "max_chars": 2000, "query_chars": 1500}


def test_the_block_is_the_newest_three_then_up_to_five_matches_never_ranked(conn):
    rows = _rows(conn, 10)  # #1 .. #10, #10 the newest
    running = _queued(conn)
    fake = FakeHindsight(results=_results(1, 9, 2, 3, 4, 5, 6))  # #9 is among the newest three: deduped
    prompt, _, mem = _attach(conn, running, fake)
    want = [_entry(rows[9]), _entry(rows[8]), _entry(rows[7])] + [_entry(rows[n - 1]) for n in (6, 5, 4, 3, 2)]
    assert mem["text"] == memory.render(TAG, want, 2000)
    assert mem["sent"] == 8 and mem["found"] == 9  # the newest three and the six matches not among them, before the cap


def test_the_newest_three_ride_even_when_the_search_finds_nothing(conn):
    rows = _rows(conn, 4)
    running = _queued(conn)
    prompt, _, mem = _attach(conn, running, FakeHindsight(results=[]))
    assert mem["text"] == memory.render(TAG, [_entry(rows[3]), _entry(rows[2]), _entry(rows[1])], 2000)


def test_a_grok_call_trims_the_matches_oldest_first_then_the_newest_tasks_from_the_oldest(conn):
    rows = _rows(conn, 5)
    running = _queued(conn)
    fake = FakeHindsight(results=_results(1, 2))
    full = [_entry(rows[n - 1]) for n in (5, 4, 3, 2, 1)]  # newest three (#5, #4, #3), then the matches #2, #1

    def size(entries):
        return len("p") + 2 + len(context.memory_part(TAG, entries, 2000))
    for keep in (5, 4, 3, 2, 1):
        _, _, mem = _attach(conn, running, fake, agent="grok", limit=size(full[:keep]))
        assert mem["sent"] == keep and mem["text"] == memory.render(TAG, full[:keep], 2000), keep
    _, _, mem = _attach(conn, running, fake, agent="grok", limit=size(full[:1]) - 1)
    assert mem.get("left_out") is True  # only when the newest task alone can't fit


@pytest.mark.parametrize("own, before, want", [
    ("what about San Diego", "Give one line on the best time of day to go to each.",
     "what about San Diego\nGive one line on the best time of day to go to each."),
    ("x" * 1490, "y" * 50, "x" * 1490 + "\n" + "y" * 9),          # the earlier text is cut first
    ("x" * 1600, "y" * 50, "x" * 1500),                            # the own text alone passes the cap: cut, alone
    ("first task of the tag", None, "first task of the tag"),      # nothing before: its own text
])
def test_the_query_is_the_task_and_the_one_before_cut_at_1500(own, before, want):
    assert memory.query_of(own, 1500, before) == want and len(memory.query_of(own, 1500, before)) <= 1500


def test_the_recall_asks_with_this_tasks_text_and_the_newest_tasks(conn):
    _done(conn, "sr-1", "Name three taco spots in Santa Barbara.", "three spots", at=T0)
    _done(conn, "sr-2", "Give one line on the best time of day to go to each.", "three times", at=T0 + timedelta(hours=1))
    running = _queued(conn, task="what about San Diego")
    fake = FakeHindsight(results=[])
    _attach(conn, running, fake)
    assert fake.recalls[0]["query"] == "what about San Diego\nGive one line on the best time of day to go to each."


def test_a_tags_first_task_searches_with_its_own_text(conn):
    running = _queued(conn, task="Name three taco spots in Santa Barbara.")
    fake = FakeHindsight(results=[])
    _attach(conn, running, fake)
    assert fake.recalls[0]["query"] == "Name three taco spots in Santa Barbara."


def test_status_says_the_newest_and_the_matches(monkeypatch):
    from router import status
    found = status.memory_view(None)
    assert (found["newest"], found["matches"]) == (3, 5)
