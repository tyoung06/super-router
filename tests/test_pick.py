"""Build brief 9, phase D (rules v2.16, Relay): `sr pick <n> a|b|none`. The owner's command is the consent.
The picked candidate becomes the task's result, copied byte for byte from its stored call row, with its
review as the task's check; `none` fails the task with both candidates kept. One pick per task. The pick
lives in check_note (the owner's D3: no column). Fake agents only; every value here is fake."""
import pytest

from router import __main__ as cli
from router import log, relay
from tests.test_versus_run import (A_TEXT, B_TEXT, LOADED, REVIEW_OF_A, REVIEW_OF_B, _versus)
from tests.test_relay import _relay as _relay_research

FAILING_REVIEW_OF_A = REVIEW_OF_A.replace("## Verdict\npass", "## Verdict\nfail")


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _pick(conn, *words, loaded=LOADED):
    lines = []
    code = cli.cmd_pick(list(words), conn=conn, loaded=loaded, out=lines.append)
    return code, "\n".join(lines)


def _stage_text(conn, row, n):
    return next(c["text"] for c in log.calls_for(conn, row["task_id"]) if c["stage"] == n and c["kind"] == "stage")


# ---------- a, b, none ----------

def test_pick_a_makes_stage_1_the_result_byte_for_byte_with_chatgpts_review_as_the_check(conn):
    code, out, row, *_ = _versus(conn)
    calls_before = [dict(c) for c in log.calls_for(conn, row["task_id"])]
    code, out = _pick(conn, str(row["n"]), "a")
    assert code == 0, out
    after = log.get_task(conn, row["task_id"])
    assert after["result"] == _stage_text(conn, row, 1) == A_TEXT
    assert (after["status"], after["check_state"], after["checker"], after["agent"], after["check_note"]) == (
        "done", "passed", "chatgpt", "claude", "picked a; review by chatgpt: pass")
    assert [dict(c) for c in log.calls_for(conn, row["task_id"])] == calls_before  # the pick sends and adds nothing


def test_pick_b_makes_stage_2_the_result_with_claudes_review_as_the_check_and_warns_on_a_failed_review(conn):
    code, out, row, *_ = _versus(conn)
    code, out = _pick(conn, f"#{row['n']}", "b")
    assert code == 0, out
    after = log.get_task(conn, row["task_id"])
    assert after["result"] == _stage_text(conn, row, 2) == B_TEXT
    assert (after["status"], after["check_state"], after["checker"], after["agent"], after["check_note"]) == (
        "done", "failed", "claude", "chatgpt", "picked b; review by claude: fail")
    warnings = [line for line in out.splitlines() if line.startswith("Warning:")]
    assert warnings == ["Warning: claude's review of B said FAIL; picked anyway."]


def test_a_pick_of_a_passed_candidate_has_no_warning(conn):
    code, out, row, *_ = _versus(conn)
    code, out = _pick(conn, str(row["n"]), "a")
    assert "Warning" not in out
    assert f"#{row['n']} {row['task_id']}: picked A (claude), reviewed by chatgpt: PASS." in out


def test_the_byte_for_byte_copy_keeps_whitespace_and_unicode(conn):
    odd = "  Line one — with a dash\n\n\tTabbed line ✓  \n"
    code, out, row, *_ = _versus(conn, claude=(odd, REVIEW_OF_B))
    _pick(conn, str(row["n"]), "a")
    stored = _stage_text(conn, row, 1)
    assert log.get_task(conn, row["task_id"])["result"] == stored
    assert stored.encode() == log.get_task(conn, row["task_id"])["result"].encode()


def test_the_task_id_works_as_the_target(conn):
    code, out, row, *_ = _versus(conn)
    code, out = _pick(conn, row["task_id"], "A")
    assert code == 0 and log.get_task(conn, row["task_id"])["check_note"].startswith("picked a;")


def test_pick_none_fails_the_task_and_keeps_both_candidates(conn):
    code, out, row, *_ = _versus(conn)
    code, out = _pick(conn, str(row["n"]), "none")
    assert code == 0, out
    after = log.get_task(conn, row["task_id"])
    assert (after["status"], after["check_note"], after["result"], after["check_state"], after["agent"],
            after["checker"]) == ("failed", "picked none", "no pick", None, None, None)
    assert _stage_text(conn, row, 1) == A_TEXT and _stage_text(conn, row, 2) == B_TEXT
    assert "picked none" in out and "both candidates are kept" in out


# ---------- refusals, each with no change ----------

def _unchanged(conn, row):
    return dict(log.get_task(conn, row["task_id"]))


def test_a_second_pick_is_refused(conn):
    code, out, row, *_ = _versus(conn)
    _pick(conn, str(row["n"]), "a")
    before = _unchanged(conn, row)
    code, out = _pick(conn, str(row["n"]), "b")
    assert code == 2
    assert out == f"Refused: #{row['n']} already picked: a. Nothing was changed."
    assert _unchanged(conn, row) == before


def test_a_second_pick_after_none_is_refused(conn):
    code, out, row, *_ = _versus(conn)
    _pick(conn, str(row["n"]), "none")
    code, out = _pick(conn, str(row["n"]), "a")
    assert code == 2 and "already picked: none" in out


def test_pick_on_a_research_build_task_is_refused(conn):
    code, out, row, *_ = _relay_research(conn, "research-build", "Three things people said about trays.")
    before = _unchanged(conn, row)
    code, out = _pick(conn, str(row["n"]), "a")
    assert code == 2 and out == f"Refused: #{row['n']} is not a versus task. Nothing was changed."
    assert _unchanged(conn, row) == before


def test_pick_on_a_route_task_is_refused(conn):
    from tests.helpers import add_row
    add_row(conn, "sr-route-1")
    code, out = _pick(conn, "1", "a")
    assert code == 2 and "is not a versus task" in out


def test_pick_on_a_failed_versus_chain_is_refused(conn):
    code, out, row, *_ = _versus(conn, chatgpt=(RuntimeError("codex broke"),))
    before = _unchanged(conn, row)
    code, out = _pick(conn, str(row["n"]), "a")
    assert code == 2 and f"#{row['n']} is not awaiting a pick (it is failed)" in out
    assert _unchanged(conn, row) == before


@pytest.mark.parametrize("choice", ["c", "", "both", "1"])
def test_anything_but_a_b_or_none_is_refused(conn, choice):
    code, out, row, *_ = _versus(conn)
    before = _unchanged(conn, row)
    code, out = _pick(conn, str(row["n"]), choice)
    # brief 17, decision 9: c is a vote's third voter, so on versus it says so; still refused, nothing changed
    assert code == 2 and ("is not a vote task; c is the third voter on a vote" if choice == "c" else "pick a, b or none") in out
    assert _unchanged(conn, row) == before


def test_no_such_task_and_no_words_are_refused(conn):
    assert _pick(conn, "9", "a") == (2, "Refused: No task #9. Nothing was changed.")
    code, out = _pick(conn)
    assert code == 2 and "sr pick <n> a|b|none" in out


def test_a_versus_task_whose_preset_cannot_be_read_is_refused(conn):
    code, out, row, *_ = _versus(conn)
    code, out = _pick(conn, str(row["n"]), "a", loaded=None)
    assert code == 2 and "can't be read" in out
    assert log.get_task(conn, row["task_id"])["check_note"] == "awaiting pick"


def test_a_task_awaiting_a_pick_with_a_review_missing_is_refused(conn):
    # Made by hand: rows that say awaiting pick but lack stage 4 (never written by the runner).
    code, out, row, *_ = _versus(conn)
    conn.execute("DELETE FROM calls WHERE call_id = ?", (f"{row['task_id']}-s4",))
    conn.commit()
    code, out = _pick(conn, str(row["n"]), "a")
    assert code == 2 and "both reviews" in out


# ---------- the log function ----------

def test_set_pick_moves_only_an_awaiting_task(conn):
    code, out, row, *_ = _versus(conn, chatgpt=(RuntimeError("codex broke"),))
    with pytest.raises(log.StateError):
        log.set_pick(conn, row["task_id"], agents=("claude", "chatgpt"), choice="a", result="x", agent="claude",
                     checker="chatgpt", verdict="pass")


def test_set_pick_refuses_a_doer_that_reviews_itself(conn):
    code, out, row, *_ = _versus(conn)
    with pytest.raises(ValueError):
        log.set_pick(conn, row["task_id"], agents=("claude", "chatgpt"), choice="a", result="x", agent="claude",
                     checker="claude", verdict="pass")


def test_picked_reads_the_pick_from_check_note():
    assert relay.picked({"check_note": "picked a; review by chatgpt: pass"}) == "a"
    assert relay.picked({"check_note": "picked none"}) == "none"
    assert relay.picked({"check_note": "awaiting pick"}) is None
    assert relay.picked({"check_note": None}) is None


# ---------- the command line ----------

def test_sr_pick_is_a_command_with_its_help(capsys):
    with pytest.raises(SystemExit):
        cli.main(["pick", "--help"], platform="darwin")
    out = capsys.readouterr().out
    assert "a|b|none" in out
