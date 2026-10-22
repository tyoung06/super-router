"""Build brief 11.1, phase B (rules v2.19, Split): at most one piece of a split is out with Grok at a time. A piece
whose next call would go to Grok (its do, check, fix or re-check: the owner's E2) is not sent while another open,
unskipped piece of the same split has a Grok call out; it stays `queued`, and `sr check` sends it on the run where
that piece comes back, fails, times out, is cancelled or is skipped. Pieces for other agents never wait. Nothing
is written for the wait (E3): `sr log`, `sr show`, `sr check` and the split's lines read it from the rows as
`queued (after #n with grok)`. Fake agents and Jev only."""
from datetime import datetime, timedelta, timezone

import pytest

from router import __main__ as cli
from router import log
from tests.test_loop import Webhook
from tests.test_split_approve import P1, P2, P3, PLAN3, Ask, Jev
from tests.test_split_wait import Env, JOINED, PULSE

R1, R2, R3 = "GROK RESULT ONE", "GROK RESULT TWO", "CLAUDE RESULT THREE"
BULK = {"status": "ok", "label": "bulk_text", "confidence": 0.95, "needs_split": 0.2, "tokens": 5}


class Inbox(Webhook):
    """A fake webhook whose inbox shows a result only once the test puts it there (by call id)."""

    def __init__(self):
        super().__init__()
        self.ready = {}

    def fetch(self):
        self.calls += 1
        return [{"number": n, "title": p["task_id"], "body": self.ready[p["task_id"]],
                 "url": f"https://github.com/x/y/issues/{n}"}
                for n, p in enumerate(self.sent, 1) if p["task_id"] in self.ready]


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _split_row(conn):
    return next(r for r in log.recent_tasks(conn, 50) if r["mode"] == "split")


def _pieces(conn):
    return list(log.pieces_of(conn, _split_row(conn)["task_id"]))


def _two_grok(conn, chatgpt=("PASS", "PASS", "PASS", "PASS"), claude=(PLAN3, R3, JOINED)):
    """Pieces 1 and 2 go to Grok (x_social_pulse), piece 3 to Claude (writing)."""
    env = Env(claude=claude, chatgpt=chatgpt, jev=Jev({P1: PULSE, P2: PULSE}), hook=Inbox())
    env.split(conn, "Two X searches and a closing line.")
    return env


def _sent_ids(env):
    return [p["task_id"] for p in env.hook.sent]


# ---------- one out at a time ----------

def test_the_second_grok_piece_stays_queued_while_the_first_is_out_and_the_claude_piece_runs(conn):
    env = _two_grok(conn)
    p1, p2, p3 = _pieces(conn)
    assert _sent_ids(env) == [p1["task_id"]]
    assert (p1["status"], p2["status"], p3["status"]) == ("sent", "queued", "done")
    assert log.calls_for(conn, p2["task_id"]) == [], "nothing was sent or written for the held piece"
    assert p2["check_note"] is None, "E3: nothing written for the wait"
    assert f"#{p2['n']} {p2['task_id']} queued (after #{p1['n']} with grok)." in env.out
    assert f"  piece 2 #{p2['n']}: queued (after #{p1['n']} with grok)" in env.out


def test_sr_check_sends_the_second_on_the_run_where_the_first_comes_back(conn):
    env = _two_grok(conn)
    p1, p2, _ = _pieces(conn)
    env.check(conn)  # nothing back yet: still held
    assert _sent_ids(env) == [p1["task_id"]]
    env.hook.ready[p1["task_id"]] = R1
    env.check(conn)
    assert _sent_ids(env) == [p1["task_id"], p2["task_id"]]
    assert log.get_task(conn, p1["task_id"])["status"] == "done"
    env.hook.ready[p2["task_id"]] = R2
    env.check(conn)
    assert log.get_task(conn, p2["task_id"])["result"] == R2
    assert _split_row(conn)["result"] == JOINED


def test_a_first_grok_piece_that_times_out_releases_the_second(conn):
    env = _two_grok(conn)
    p1, p2, _ = _pieces(conn)
    later = datetime.now(timezone.utc) + timedelta(minutes=cli.TIMEOUT_MINUTES + 1)
    cli.cmd_check(conn=conn, config=env.kw()["config"], environ={}, settings_paths=[], post=env.hook.post,
                  worker=env.worker, chatgpt=env.chat, codex_login=lambda: True, fetch=env.hook.fetch,
                  close=env.hook.close, roster=env.kw()["roster"], now=later, out=env.lines.append)
    assert log.get_task(conn, p1["task_id"])["status"] == "timed_out"
    assert _sent_ids(env) == [p1["task_id"], p2["task_id"]]


def test_a_first_grok_piece_that_is_cancelled_releases_the_second(conn):
    env = _two_grok(conn)
    p1, p2, _ = _pieces(conn)
    cli.cmd_cancel(conn=conn, words=[p1["task_id"]], out=env.lines.append)
    env.check(conn)
    assert _sent_ids(env) == [p1["task_id"], p2["task_id"]]


def test_a_first_grok_piece_that_is_skipped_releases_the_second(conn):
    env = _two_grok(conn)
    p1, p2, _ = _pieces(conn)
    assert env.skip(conn, [p1["task_id"]]) == 0
    env.check(conn)
    assert _sent_ids(env) == [p1["task_id"], p2["task_id"]]


def test_a_first_grok_piece_whose_send_fails_releases_the_second(conn):
    env = Env(claude=(PLAN3, R3), chatgpt=("PASS",), jev=Jev({P1: PULSE, P2: PULSE}), hook=Inbox())
    env.hook.fail = ("do",)
    env.split(conn, "Two X searches and a closing line.")
    p1, p2, _ = _pieces(conn)
    assert log.get_task(conn, p1["task_id"])["status"] == "failed"
    # a refused Grok `do` send writes no call row (as before this brief); p2 was tried: its send is the second one
    assert _sent_ids(env) == [p1["task_id"], p2["task_id"]] and log.get_task(conn, p2["task_id"])["status"] == "failed"


def test_skip_and_cancel_work_on_the_held_piece(conn):
    env = _two_grok(conn)
    p1, p2, _ = _pieces(conn)
    assert env.skip(conn, [p2["task_id"]]) == 0
    assert log.split_plan_of(_split_row(conn))["pieces"][1]["skipped"] is True
    env2 = Env()
    conn2 = log.init_db(":memory:")
    env2 = _two_grok(conn2)
    q2 = log.pieces_of(conn2, _split_row(conn2)["task_id"])[1]
    lines = []
    assert cli.cmd_cancel(conn=conn2, words=[q2["task_id"]], out=lines.append) == 0
    assert log.get_task(conn2, q2["task_id"])["status"] == "cancelled"
    conn2.close()


def test_a_grok_check_is_held_too(conn):
    """E2: piece 2 is bulk_text: Claude does it, Grok checks it. Its do runs at once; its check waits for piece 1."""
    env = Env(claude=(PLAN3, "BULK DONE", R3, JOINED), chatgpt=("PASS", "PASS", "PASS"),
              jev=Jev({P1: PULSE, P2: BULK}), hook=Inbox())
    env.split(conn, "An X search, a bulk job and a closing line.")
    p1, p2, p3 = _pieces(conn)
    assert [(c["kind"], c["agent"]) for c in log.calls_for(conn, p2["task_id"])] == [("do", "claude")]
    assert (log.get_task(conn, p2["task_id"])["status"], log.get_task(conn, p3["task_id"])["status"]) == ("queued", "done")
    assert _sent_ids(env) == [p1["task_id"]]
    env.hook.ready[p1["task_id"]] = R1
    env.check(conn)
    assert _sent_ids(env) == [p1["task_id"], f"{p2['task_id']}-c1"]


def test_two_grok_pieces_of_different_splits_do_not_hold_each_other(conn):
    _two_grok(conn)
    env = _two_grok(conn)
    firsts = [log.pieces_of(conn, r["task_id"])[0]["task_id"] for r in log.recent_tasks(conn, 50) if r["mode"] == "split"]
    assert all(t in [p["task_id"] for p in env.hook.sent] for t in firsts[:1])
    assert sum(1 for r in log.recent_tasks(conn, 50) if r["mode"] == "piece" and r["status"] == "sent") == 2


# ---------- what the owner sees (E3) ----------

def test_sr_show_sr_log_and_sr_check_name_the_piece_it_waits_for(conn):
    env = _two_grok(conn)
    p1, p2, _ = _pieces(conn)
    want = f"queued (after #{p1['n']} with grok)"
    lines = []
    cli.cmd_show(conn=conn, words=[str(p2["n"])], out=lines.append)
    assert f"(no result yet: {want}; `sr check` sends it once #{p1['n']} is back)" in "\n".join(lines)
    lines = []
    cli.cmd_show(conn=conn, words=[str(_split_row(conn)["n"])], out=lines.append)
    assert f"  2. #{p2['n']} {want} · x_social_pulse · grok / chatgpt: {P2}" in "\n".join(lines)
    lines = []
    cli.cmd_log(conn=conn, out=lines.append)
    assert any(p2["task_id"] in line and want in line for line in lines)
    env.lines.clear()
    env.check(conn)
    assert f"#{p2['n']} {p2['task_id']} is {want}." in env.out
