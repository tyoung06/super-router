"""Brief 29.1, D's issue D6 (the owner's go, 28 Oct): a split hands Cursor's worker and its readiness check to every
piece it runs, from each of its five commands: `sr split` (its own approval), `--go`, `--edit` (which runs no piece, so it
hands them on), `--skip`, and the going on after a pick or a cancel (`_going_on`). Live, piece 2 of #149 (versus, Cursor
in `b`) failed at Cursor's build with "Cursor isn't configured": the split's commands never passed the worker. Fake
agents, a fake Cursor and a fake Jev; every value here is fake."""
import functools

import pytest

from router import __main__ as cli
from router import log
from tests.helpers import teamed
from tests.test_cursor_send import Cursor, Ready, answer
from tests.test_split_approve import Ask
from tests.test_split_pieces import JOIN, P1, P2, TASK, World, _pieces, _split
from tests.test_versus_run import A_TEXT, B_TEXT, REVIEW_OF_A, REVIEW_OF_B

NOT_CONFIGURED = "Cursor isn't configured"
P3 = "Write a two-line caption for the seed library's spring swap poster."


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


class CursorWorld(World):
    """World with a fake Cursor and its readiness check, handed to every split command as `_main` hands them."""

    def __init__(self, claude=(), chatgpt=(), cursor=()):
        super().__init__(claude=claude, chatgpt=chatgpt)
        self.cursor, self.ready = Cursor(*cursor), Ready()

    def kw(self, ask=None):
        return {**super().kw(ask), "cursor": self.cursor, "cursor_ready": self.ready}


def _plan(conn, w, teams_=("route", "versus"), pieces=(P1, P2)):
    """A split waiting at its plan (no terminal, so `sr split` stops there): its pieces with their teams, in order."""
    body = "\n".join(f"{k}. {t}" for k, t in enumerate(pieces, 1))
    w.worker.replies.insert(0, teamed(f"## Pieces\n{body}\n\n## Join\n{JOIN}\n", team=list(teams_)))
    assert cli.cmd_split(TASK, conn=conn, **w.kw()) == 0, w.out
    return _split(conn)


def _cursor_in_b(conn, w, row, piece="2"):
    code = cli.cmd_split_edit([str(row["n"])], piece=piece, slots=["b=cursor"], conn=conn, **w.kw())
    assert code == 0, w.out


def _cursor_ran(conn, w, piece):
    """Cursor built B and reviewed A on the versus piece, which now waits for its pick."""
    calls = [(c["stage"], c["role"], c["agent"], c["status"]) for c in log.calls_for(conn, piece["task_id"])]
    assert (2, "build", "cursor", "done") in calls and (3, "review", "cursor", "done") in calls, (calls, w.out)
    assert len(w.cursor.prompts) == 2 and w.ready.calls == 1, "one readiness check per command, then both calls"
    assert NOT_CONFIGURED not in w.out
    assert log.get_task(conn, piece["task_id"])["check_note"] == log.AWAITING_PICK


def _world():
    return CursorWorld(claude=("piece one", A_TEXT, REVIEW_OF_B), chatgpt=("PASS",),
                       cursor=(answer(B_TEXT), answer(REVIEW_OF_A)))


def test_sr_split_runs_a_cursor_piece_set_with_e_in_its_own_approval(conn):
    w = _world()
    w.worker.replies.insert(0, teamed(f"## Pieces\n1. {P1}\n2. {P2}\n\n## Join\n{JOIN}\n", team=["route", "versus"]))
    code = cli.cmd_split(TASK, conn=conn, **w.kw(Ask("e", "2", "", "", "", "cursor", "y")))
    assert code == 0, w.out
    _cursor_ran(conn, w, _pieces(conn)[1])


def test_split_go_runs_a_cursor_piece_whose_slot_the_edit_set(conn):
    w = _world()
    row = _plan(conn, w)
    _cursor_in_b(conn, w, row)
    assert cli.cmd_split_go([str(row["n"])], conn=conn, **w.kw(Ask("y"))) == 0, w.out
    _cursor_ran(conn, w, _pieces(conn)[1])


def test_split_edit_runs_no_piece_but_hands_cursor_and_its_check_on(conn, monkeypatch):
    w = _world()
    row = _plan(conn, w)
    seen, real = [], cli._split_deps
    monkeypatch.setattr(cli, "_split_deps", lambda *a, **k: seen.append(k) or real(*a, **k))
    _cursor_in_b(conn, w, row)
    assert seen and seen[-1]["cursor"] is w.cursor and seen[-1]["cursor_ready"] is w.ready
    assert w.cursor.prompts == [] and w.ready.calls == 0, "an edit calls no agent"


def _interrupted_at_piece_one(conn, teams_=("route", "versus"), pieces=(P1, P2)):
    """The approval stops with Ctrl+C in piece 1's doer, so the pieces after it stay queued, the last one versus with
    Cursor in b."""
    w = CursorWorld(claude=(KeyboardInterrupt, A_TEXT, REVIEW_OF_B), cursor=(answer(B_TEXT), answer(REVIEW_OF_A)))
    row = _plan(conn, w, teams_, pieces)
    _cursor_in_b(conn, w, row, piece=str(len(pieces)))
    assert cli.cmd_split_go([str(row["n"])], conn=conn, **w.kw(Ask("y"))) == 130, w.out
    found = _pieces(conn)
    assert all(p["status"] == "queued" for p in found[1:]) and w.cursor.prompts == []
    return w, found


def test_split_skip_runs_the_queued_cursor_piece(conn):
    w, (one, two) = _interrupted_at_piece_one(conn)
    assert cli.cmd_split_skip([one["task_id"]], conn=conn, **w.kw()) == 0, w.out
    _cursor_ran(conn, w, log.get_task(conn, two["task_id"]))


def test_going_on_after_a_cancel_runs_the_queued_cursor_piece(conn, monkeypatch):
    # piece 1 stopped by Ctrl+C; cancelling piece 2, still queued, ends it, and the split goes on to piece 3 (Cursor)
    w, (one, two, three) = _interrupted_at_piece_one(conn, ("route", "route", "versus"), (P1, P3, P2))
    monkeypatch.setattr(cli, "_claude_gate", lambda config, out: None)  # no probe of the real Claude Code here

    def no_webhook(*a, **k):
        raise AssertionError("nothing in this split goes to Grok")
    monkeypatch.setattr(cli.requests, "post", no_webhook)
    going_on = functools.partial(cli._going_on, conn=conn, config=w.kw()["config"], roster=w.kw()["roster"],
                                 worker=w.worker, chatgpt=w.chat, store=None, gate=None, codex=None, cursor=w.cursor,
                                 cursor_ready=w.ready, out=w.lines.append)
    assert cli.cmd_cancel(conn=conn, words=[two["task_id"]], go_on=going_on, out=w.lines.append) == 0, w.out
    _cursor_ran(conn, w, log.get_task(conn, three["task_id"]))
