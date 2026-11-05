"""Build brief 29 (rules 2.41, Split, "How pieces run" and "When a piece is done"; decisions 10 and 11), B4: whatever
ends a piece (its own run, `sr check`, a resume, a pick, a skip, a fallback, a cancel) goes on with its split in the same
command, under the split's run, after today's refusals and Claude's gate: the next queued piece starts, and when every
piece is in, the join. A pick of a candidate is the piece's result whatever its review said; `none` blocks it. `sr pick`
on a piece with a billing switch set keeps the pick and sends nothing. Never two joins: only the split's own run goes on.
The page's server runs `sr check` once a minute while a split waits on its pieces with none of them running. Fake agents,
a fake Jev and a fake webhook; every value here is fake."""
import json
import os

import pytest

from router import __main__ as cli
from router import availability, log, page, runs, split
from tests.test_loop import Clock, Scripted
from tests.test_relay import CONFIG, GOOD_NOTE, ROSTER, Chat, RelayHook
from tests.test_split_approve import Ask, Jev
from tests.test_split_pieces import P1, P2, World, _pieces, _split
from tests.test_versus_run import A_TEXT, B_TEXT, REVIEW_OF_A, REVIEW_OF_B

JOINED = "THE EXPLAINER, THEN THE DECISION."


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def go_on(conn, w, *, environ=None, available=None):
    deps = cli._split_deps(CONFIG, ROSTER, label=w.jev, ask=None, post=w.hook.post, worker=w.worker, chatgpt=w.chat,
                           codex_login=lambda: True, fetch=w.hook.fetch, close=w.hook.close, sleep=w.clock.sleep,
                           clock=w.clock, wait=False, claude_ready=None, available=available)
    return lambda row: cli._go_on(conn, row, deps, [], w.lines.append, environ=environ or {}, settings_paths=[])


def pick(conn, w, piece, choice, **kw):
    return cli.cmd_pick([piece["task_id"], choice], conn=conn, loaded=cli._presets_quietly(), go_on=go_on(conn, w, **kw),
                        out=w.lines.append)


def _versus_waiting(conn, claude=(), chatgpt=()):
    """Piece 1 a versus piece waiting for its pick, piece 2 a route piece delivered meanwhile."""
    w = World(claude=(A_TEXT, REVIEW_OF_B, "piece two", *claude), chatgpt=(B_TEXT, REVIEW_OF_A, "PASS", *chatgpt))
    w.split(conn, ["versus", "route"], pieces=(P2, P1))
    return w


# ---------- a pick (decisions 10 and 11) ----------

def test_a_pick_on_a_piece_makes_its_result_and_the_join_runs_in_the_same_command(conn):
    w = _versus_waiting(conn, claude=(JOINED,), chatgpt=("PASS",))
    versus, route = _pieces(conn)
    assert pick(conn, w, versus, "a") == 0
    versus = log.get_task(conn, versus["task_id"])
    assert (versus["status"], versus["result"]) == ("done", A_TEXT)
    row = _split(conn)
    assert (row["status"], row["check_state"], row["result"]) == ("done", "passed", JOINED)
    join = log.calls_for(conn, row["task_id"])[1]
    assert join["role"] == "integrate" and A_TEXT in w.worker.prompts[-1] and B_TEXT not in w.worker.prompts[-1]


def test_a_pick_of_a_candidate_whose_review_failed_is_done(conn):
    w = _versus_waiting(conn, claude=(JOINED,), chatgpt=("PASS",))
    versus, _ = _pieces(conn)
    assert pick(conn, w, versus, "b") == 0  # B's review (by claude) said fail
    versus = log.get_task(conn, versus["task_id"])
    assert (versus["status"], versus["check_state"], versus["result"]) == ("done", "failed", B_TEXT)
    assert split.piece_state(versus) == ("done", None)
    assert _split(conn)["status"] == "done"


def test_none_blocks_the_piece_and_the_split_waits(conn):
    w = _versus_waiting(conn)
    versus, _ = _pieces(conn)
    assert pick(conn, w, versus, "none") == 0
    versus = log.get_task(conn, versus["task_id"])
    assert split.piece_state(versus) == ("blocked", "you picked none")
    row = _split(conn)
    assert row["status"] == "returned" and f"Piece {versus['task_id']} blocked: you picked none" in "\n".join(w.lines)


def test_a_pick_with_a_billing_switch_set_stands_and_the_split_waits_sending_nothing(conn):
    w = _versus_waiting(conn)
    versus, _ = _pieces(conn)
    before = (len(w.worker.prompts), len(w.chat.prompts))
    assert pick(conn, w, versus, "a", environ={"ANTHROPIC_API_KEY": "fake"}) == 0
    assert log.get_task(conn, versus["task_id"])["status"] == "done", "the pick stands"
    assert (len(w.worker.prompts), len(w.chat.prompts)) == before, "nothing is sent"
    assert f"Split #{_split(conn)['n']} waits: " in "\n".join(w.lines) and f"sr split --go {_split(conn)['n']}" in \
        "\n".join(w.lines)
    assert _split(conn)["status"] == "returned"


def test_a_pick_while_claude_isnt_available_stands_and_the_split_waits(conn):
    w = _versus_waiting(conn)
    versus, _ = _pieces(conn)
    off = availability.Availability(False, "Claude is signed out: claude auth login", "signed_out")
    assert pick(conn, w, versus, "a", available=lambda name: off if name == "claude" else availability.YES) == 0
    assert "waits: Claude is signed out: claude auth login" in "\n".join(w.lines)
    assert _split(conn)["status"] == "returned"


def test_never_two_joins_another_process_holding_the_splits_run_goes_on_there(conn, monkeypatch):
    w = _versus_waiting(conn)
    versus, _ = _pieces(conn)
    other = (os.getpid() + 7, "2026-10-27T09:00:00+00:00")
    monkeypatch.setattr(runs, "READ", lambda pid: other[1] if pid == other[0] else "2026-10-20T12:00:00+00:00")
    log.claim_run(conn, _split(conn)["task_id"], *other)
    assert pick(conn, w, versus, "a") == 0
    assert "is running in another window; it goes on there" in "\n".join(w.lines)
    assert _split(conn)["status"] == "returned" and len(log.calls_for(conn, _split(conn)["task_id"])) == 1


# ---------- a skip, a cancel, a resume, a fallback, sr check ----------

def test_a_cancelled_piece_blocks_only_the_join_then_a_skip_goes_on_to_it(conn):
    hook = RelayHook(s1=GOOD_NOTE)
    w = World(claude=("piece two", JOINED), chatgpt=("PASS", "PASS"), hook=hook)
    w.split(conn, ["research-build", "route"])
    research, route = _pieces(conn)
    assert log.get_task(conn, route["task_id"])["status"] == "done", "the Grok piece waits; the next one ran"
    assert cli.cmd_cancel(conn=conn, words=[research["task_id"]], go_on=go_on(conn, w), out=w.lines.append) == 0
    assert split.piece_state(log.get_task(conn, research["task_id"]))[0] == "blocked"
    assert _split(conn)["status"] == "returned"
    cli.cmd_split_skip([research["task_id"]], conn=conn, **{k: v for k, v in w.kw().items() if k != "ask"})
    row = _split(conn)
    assert (row["status"], row["result"]) == ("done", JOINED)


def test_sr_check_collecting_a_pieces_grok_answer_goes_on_to_the_join(conn):
    hook = RelayHook(s1=GOOD_NOTE)
    w = World(claude=("piece two", "Built from the note.", JOINED), chatgpt=("PASS", "PASS", "PASS"), hook=hook)
    w.split(conn, ["research-build", "route"])
    w.check(conn)
    assert (_split(conn)["status"], _split(conn)["result"]) == ("done", JOINED)


def test_split_go_on_a_split_waiting_on_its_pieces_still_works(conn):
    w = _versus_waiting(conn)
    lines = []
    code = cli.cmd_split_go([str(_split(conn)["n"])], conn=conn, **{**w.kw(), "out": lines.append})
    assert code == 0 and "1 of 2 pieces done" in "\n".join(lines) and "waiting (waits for your pick)" in "\n".join(lines)


# ---------- the page's server: nothing stalls (decision 11) ----------

def _log_body(*tasks):
    return 200, json.dumps({"tasks": list(tasks)})


def test_the_server_checks_once_a_minute_while_a_split_waits_with_nothing_running():
    waiting = {"task_id": "sr-s", "mode": "split", "waiting_on": "piece", "pid": None}
    piece = {"task_id": "sr-p", "mode": "relay", "parent": "sr-s", "waiting_on": "pick", "pid": None}
    assert page.split_stalled([waiting, piece]) is True
    assert page.split_stalled([waiting, {**piece, "pid": 4242}]) is False, "one of its tasks is running"
    assert page.split_stalled([{**waiting, "pid": 4242}, piece]) is False, "the split itself is running"
    assert page.split_stalled([{**waiting, "waiting_on": "split_plan"}]) is False


def test_the_tick_starts_one_check_for_a_stalled_split(tmp_path):
    started = []
    reader = page.Reader(run=None, clock=lambda: 1000.0, start=started.append)
    reader.log = lambda flags=(): _log_body({"task_id": "sr-s", "mode": "split", "waiting_on": "piece", "pid": None})
    assert reader.tick() is True and len(started) == 1
    reader._checking = False
    assert reader.tick() is False, "at most once a minute"
    reader.log = lambda flags=(): _log_body({"task_id": "sr-s", "mode": "split", "waiting_on": "piece", "pid": 99})
    reader._last_grok = None
    assert reader.tick() is False
