"""Build brief 11.1, phase C (rules v2.19, Split: "What the planner may not split"). The planner prompt says no two
pieces ask for the same search or work, dependent work stays in one piece (a function and its tests), and a task
that is one chain gets `## No split` with one line. A valid `## No split` is an answer, read in code before the
contract: the split ends `failed` at stage 1 with `no split: <line>`, no piece rows, no Jev call, no re-ask, and the
message names `sr route` (quoted for zsh: the owner's E4). A malformed one, or one beside `## Pieces`, is a contract
miss with the usual one re-ask. Fake agents and Jev only."""
import pytest

from router import __main__ as cli
from router import log, split
from tests.test_split_approve import PLAN, P1, P2, Ask, Jev
from tests.test_split_wait import Env

TASK = "Find which soil sensor gardeners on X praised most this week, then write a three-sentence ad for that one."
WHY = "The ad depends on which monitor the X search finds, so the parts are one chain."
NO = f"## No split\n{WHY}\n"


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _split_row(conn):
    return next(r for r in log.recent_tasks(conn, 50) if r["mode"] == "split")


# ---------- the prompt ----------

def test_the_planner_prompt_says_what_may_not_be_split_and_offers_no_split():
    text = split.PLAN_INSTRUCTIONS
    assert "No two pieces may ask for the same search or the same work." in text
    assert "Work that needs another part's result stays in one piece with that part: a function and its tests are one piece." in text
    assert ("If the task is one chain, where each part needs the one before it, do not split it: return only "
            "`## No split` with one line saying why.") in text
    assert split.plan_prompt(TASK) == TASK + "\n\n" + text


def test_the_reask_shape_names_no_split_as_the_other_answer():
    assert "`## No split`" in split.PLAN_SHAPE and "Do not do any piece." in split.PLAN_SHAPE


# ---------- reading ## No split ----------

def test_a_valid_no_split_is_read_as_its_line():
    assert split.no_split(NO) == WHY
    assert split.no_split(f"Thinking about it:\n\n## No split\n\n  {WHY}  \n") == WHY.strip()


@pytest.mark.parametrize("text", [
    "## No split\n",                                     # no line
    f"## No split\n{WHY}\nAnd a second reason.\n",        # two lines
    f"{NO}\n## Pieces\n1. a\n2. b\n\n## Join\nj\n",      # beside pieces
    f"## Pieces\n1. a\n2. b\n\n## No split\n{WHY}\n",     # not the first heading
    f"```\n## No split\n{WHY}\n```\n",                    # inside a code fence
    PLAN,                                                # a normal plan
])
def test_anything_else_is_not_a_no_split_answer(text):
    assert split.no_split(text) is None


def test_a_malformed_no_split_is_a_contract_miss():
    assert split.split_plan("## No split\n") == ["No split: need one line saying why, found 0"]
    assert split.split_plan(f"## No split\n{WHY}\nAnother line.\n") == ["No split: need one line saying why, found 2"]
    assert split.split_plan(f"{NO}\n## Pieces\n1. {P1}\n2. {P2}\n\n## Join\nj\n") == [
        "Pieces and No split: return either `## Pieces` and `## Join`, or `## No split`, not both"]
    assert split.split_plan(PLAN) == []


# ---------- the split stops on it ----------

def test_a_no_split_answer_ends_the_split_with_no_piece_no_jev_and_no_reask(conn):
    env = Env(claude=(NO,))
    code = env.split(conn, TASK, ask=Ask("y"))
    row = _split_row(conn)
    assert code == 1
    assert (row["status"], row["failed_stage"], row["result"]) == ("failed", 1, f"no split: {WHY}")
    assert log.pieces_of(conn, row["task_id"]) == [] and log.split_plan_of(row) is None
    assert env.jev.calls == [] and len(env.worker.prompts) == 1, "no re-ask"
    assert [(c["kind"], c["role"]) for c in log.calls_for(conn, row["task_id"])] == [("stage", "split_plan")]
    assert f"No split: {WHY}" in env.out
    assert f"Route it instead: sr route '{TASK}'" in env.out


def test_the_route_it_instead_line_keeps_a_dollar_sign_safe_from_zsh(conn):
    task = "Find gardeners' favorite tray under $5, then write one line about it."
    env = Env(claude=(NO,))
    env.split(conn, task)
    assert "Route it instead: sr route 'Find gardeners'\"'\"' favorite tray under $5, then write one line about it.'" in env.out


@pytest.mark.parametrize("first", ["## No split\n", f"## No split\n{WHY}\nAnother line.\n",
                                   f"{NO}\n## Pieces\n1. {P1}\n2. {P2}\n\n## Join\nj\n"])
def test_a_malformed_no_split_gets_the_one_reask_and_a_good_plan_then_goes_on(conn, first):
    env = Env(claude=(first, PLAN))
    cli.cmd_split(TASK, conn=conn, **env.kw(ask=None))
    row = _split_row(conn)
    assert [(c["kind"], c["role"]) for c in log.calls_for(conn, row["task_id"])] == [
        ("stage", "split_plan"), ("reask", "split_plan")]
    assert "`## No split`" in env.worker.prompts[1]
    assert (row["status"], row["check_note"]) == ("returned", "awaiting approval")


def test_a_no_split_on_the_reask_is_an_answer_too(conn):
    env = Env(claude=("## No split\n", NO))
    env.split(conn, TASK)
    row = _split_row(conn)
    assert (row["status"], row["result"]) == ("failed", f"no split: {WHY}") and len(env.worker.prompts) == 2


def test_sr_show_prints_the_no_split_line_and_the_route_hint(conn):
    env = Env(claude=(NO,))
    env.split(conn, TASK)
    lines = []
    cli.cmd_show(conn=conn, words=[str(_split_row(conn)["n"])], out=lines.append)
    out = "\n".join(lines)
    assert f"No split: {WHY}" in out and f"Route it instead: sr route '{TASK}'" in out
    assert "SPLIT FAILED" not in out
