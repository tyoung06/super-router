"""The memory brief, step 5 (rules 2.56, Memory "What goes in"): after the newest 3, the block's matches are the 3
Hindsight ranks best, then the 2 newest of the rest, all shown newest first (`memory.select`, a pure function the
replay calls too); the block's line says the newer entry stands where two disagree. Every value here is invented."""
from router import memory

LINE = "Where two entries disagree, trust the newer one unless this task says otherwise."


def _e(n):
    return memory.Entry(n, "2026-10-01", "writing", "claude", None, f"text {n}")


def _ns(entries):
    return [e.n for e in entries]


def test_the_three_best_stay_even_when_old_then_the_two_newest_of_the_rest_all_newest_first():
    head = [_e(20), _e(19), _e(18)]
    ranked = [_e(2), _e(11), _e(5), _e(9), _e(15), _e(1), _e(14)]  # Hindsight's order: #2 ranks best
    assert _ns(memory.select(head, ranked, matches=5)) == [20, 19, 18, 15, 14, 11, 5, 2]


def test_fewer_matches_than_the_room_keeps_them_all_newest_first():
    assert _ns(memory.select([_e(9)], [_e(1), _e(4)], matches=5)) == [9, 4, 1]
    assert _ns(memory.select([], [_e(3), _e(7), _e(5), _e(6)], matches=5)) == [7, 6, 5, 3]
    assert _ns(memory.select([_e(9)], [], matches=5)) == [9]


def test_a_smaller_room_takes_the_best_first():
    ranked = [_e(2), _e(11), _e(5), _e(9)]
    assert _ns(memory.select([], ranked, matches=2)) == [11, 2]   # min(3, matches) best, none of the rest
    assert _ns(memory.select([], ranked, matches=4)) == [11, 9, 5, 2]
    assert _ns(memory.select([], ranked, matches=0)) == []


def test_select_is_pure():
    head, ranked = [_e(9)], [_e(1), _e(4), _e(2), _e(3)]
    memory.select(head, ranked, matches=3)
    assert _ns(head) == [9] and _ns(ranked) == [1, 4, 2, 3]
    assert memory.BEST == 3


def test_the_block_line_holds_the_conflict_sentence():
    assert memory.BLOCK_LINE.endswith(LINE)
    assert memory.render("chat:x", [_e(1)], 2000).endswith(LINE)
