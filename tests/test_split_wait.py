"""Build brief 11, phase C (rules v2.18, Split): the pieces run one after another through the usual routed path
(each its own task, label, doer, check loop); the split waits for every piece. A piece is done when delivered
(passed, fixed, unchecked, or a quick answer); a piece that failed its check twice, stopped, timed out, was
cancelled or came back blocks the split until the owner resolves it with its own commands or runs
`sr split --skip <piece>`, and then the integration prompt says it is missing. Plain `sr check` advances
waiting splits and prints each one's pieces (the owner's D3 and their addition). Fake agents and Jev only."""
import pytest

from router import __main__ as cli
from router import log, split
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_relay import CONFIG, ROSTER, Chat
from tests.test_split_approve import JOIN, P1, P2, P3, PLAN, PLAN3, Ask, Jev

PULSE = {"status": "ok", "label": "x_social_pulse", "confidence": 0.95, "needs_split": 0.2, "tokens": 640}
R1, R2, R3 = "INTRO RESULT: adjustable trays ...", "CHECKLIST RESULT:\n1. a\n2. b\n3. c\n4. d\n5. e", "GROK PULSE RESULT"
JOINED = "THE JOINED RESULT: intro, then the checklist."


class LateHook(Webhook):
    """A fake webhook whose inbox shows nothing on the first `n_empty` reads, then the scripted bodies."""

    def __init__(self, n_empty=1, **bodies):
        super().__init__(**bodies)
        self.n_empty = n_empty

    def fetch(self):
        self.n_empty -= 1
        return [] if self.n_empty >= 0 else super().fetch()


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


class Env:
    """One scripted world: Claude, ChatGPT, Jev and the webhook, shared by every command in a test."""

    def __init__(self, claude=(), chatgpt=(), jev=None, hook=None):
        self.worker, self.chat, self.jev = Scripted(*claude), Chat(*chatgpt), jev or Jev()
        self.hook, self.clock, self.lines = hook or Webhook(), Clock(), []

    def kw(self, ask=None):
        return dict(config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=self.jev, ask=ask,
                    post=self.hook.post, worker=self.worker, chatgpt=self.chat, codex_login=lambda: True,
                    fetch=self.hook.fetch, close=self.hook.close, sleep=self.clock.sleep, clock=self.clock,
                    wait=False, out=self.lines.append)

    def split(self, conn, task="Write an intro and a checklist. No prices.", ask=None):
        return cli.cmd_split(task, conn=conn, **self.kw(ask or Ask("y")))

    def go(self, conn, n, ask=None):
        return cli.cmd_split_go([str(n)], conn=conn, **self.kw(ask))

    def skip(self, conn, words):
        return cli.cmd_split_skip(words, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                                  label=self.jev, ask=None, post=self.hook.post, worker=self.worker, chatgpt=self.chat,
                                  codex_login=lambda: True, fetch=self.hook.fetch, close=self.hook.close,
                                  sleep=self.clock.sleep, clock=self.clock, wait=False, out=self.lines.append)

    def check(self, conn):
        return cli.cmd_check(conn=conn, config=CONFIG, environ={}, settings_paths=[], post=self.hook.post,
                             worker=self.worker, chatgpt=self.chat, codex_login=lambda: True, fetch=self.hook.fetch,
                             close=self.hook.close, roster=ROSTER, out=self.lines.append)

    @property
    def out(self):
        return "\n".join(self.lines)


def _split_row(conn):
    return next(r for r in log.recent_tasks(conn, 50) if r["mode"] == "split")


def _pieces(conn):
    return list(log.pieces_of(conn, _split_row(conn)["task_id"]))


# ---------- the pieces run one after another, as routed tasks ----------

def test_after_yes_each_piece_runs_its_own_loop_in_plan_order_then_the_split_integrates(conn):
    env = Env(claude=(PLAN, R1, R2, JOINED), chatgpt=("PASS", "PASS", "PASS"))
    assert env.split(conn) == 0, env.out
    assert env.worker.prompts[1:3] == [P1, P2], "each doer gets its piece text as the task, nothing more"
    first, second = _pieces(conn)
    assert [(c["kind"], c["agent"]) for c in log.calls_for(conn, first["task_id"])] == [("do", "claude"), ("check", "chatgpt")]
    assert (first["status"], first["check_state"], first["result"]) == ("done", "passed", R1)
    assert (second["status"], second["check_state"], second["result"]) == ("done", "passed", R2)
    order = [c["call_id"] for c in sorted(
        [c for p in (first, second) for c in log.calls_for(conn, p["task_id"])], key=lambda c: c["n"])]
    assert order == [first["task_id"], f"{first['task_id']}-c1", second["task_id"], f"{second['task_id']}-c1"]
    row = _split_row(conn)
    assert (row["status"], row["check_state"], row["result"]) == ("done", "passed", JOINED)


def test_a_piece_is_an_ordinary_task_with_its_own_number(conn):
    env = Env(claude=(PLAN, R1, R2, JOINED), chatgpt=("PASS", "PASS", "PASS"))
    env.split(conn)
    numbers = [p["n"] for p in _pieces(conn)]
    assert numbers == [_split_row(conn)["n"] + 1, _split_row(conn)["n"] + 2]
    assert "Piece 1 of 2: #2" in env.out and "Piece 2 of 2: #3" in env.out


# ---------- the wait: a Grok piece that comes back later ----------

def _grok_split(conn, n_empty=1):
    jev = Jev({P3: PULSE})
    hook = LateHook(n_empty=n_empty, do=R3)
    env = Env(claude=(PLAN3, R1, R2, JOINED), chatgpt=("PASS", "PASS", "PASS", "PASS"), jev=jev, hook=hook)
    env.split(conn)
    return env


def test_a_grok_piece_is_sent_and_the_next_piece_still_runs_without_waiting(conn):
    env = _grok_split(conn)
    p1, p2, p3 = _pieces(conn)
    assert (p3["agent"], p3["status"]) == ("grok", "sent")
    assert (p1["status"], p2["status"]) == ("done", "done")
    row = _split_row(conn)
    assert (row["status"], row["check_note"]) == ("returned", f"waiting: pieces #{p1['n']}, #{p2['n']}, #{p3['n']}")
    assert f"Split #{row['n']}: 2 of 3 pieces done." in env.out
    assert f"piece 3 #{p3['n']}: waiting (with grok)" in env.out


def test_sr_check_reports_waiting_then_integrates_once_the_grok_piece_is_in(conn):
    env = _grok_split(conn, n_empty=1)
    env.lines.clear()
    env.check(conn)  # first sr check: nothing in the inbox yet
    n = _split_row(conn)["n"]
    assert f"Split #{n}: 2 of 3 pieces done." in env.out and _split_row(conn)["status"] == "returned"
    env.lines.clear()
    env.check(conn)  # second: Grok's result arrives, ChatGPT checks it, the split integrates
    p3 = _pieces(conn)[2]
    assert (p3["status"], p3["result"]) == ("done", R3)
    assert f"Split #{n}: 3 of 3 pieces done." in env.out
    row = _split_row(conn)
    assert (row["status"], row["result"]) == ("done", JOINED)


def test_go_on_a_split_still_waiting_prints_its_pieces_and_sends_nothing(conn):
    env = _grok_split(conn, n_empty=5)
    sent = len(env.hook.sent)
    prompts = len(env.worker.prompts)
    env.lines.clear()
    assert env.go(conn, _split_row(conn)["n"]) == 0
    assert "2 of 3 pieces done." in env.out and len(env.hook.sent) == sent and len(env.worker.prompts) == prompts


# ---------- blocked pieces and --skip ----------

def _blocked_split(conn):
    """Piece 2 fails its check twice (NOT PASSED); piece 1 passes."""
    env = Env(claude=(PLAN, R1, R2, "R2 FIXED", JOINED),
              chatgpt=("PASS", "FIX\n1. add a fifth item", "FIX\n1. still four items", "PASS"))
    env.split(conn)
    return env


def test_a_piece_that_failed_its_check_twice_blocks_the_split(conn):
    env = _blocked_split(conn)
    p1, p2 = _pieces(conn)
    assert (p2["status"], p2["check_state"]) == ("done", "failed")
    row = _split_row(conn)
    assert row["status"] == "returned" and row["check_note"].startswith("waiting: pieces")
    assert (f"Piece {p2['task_id']} blocked: it failed its check twice. Resolve it (sr resume / sr fallback / "
            f"sr route again) or: sr split --skip {p2['task_id']}") in env.out
    assert len(env.worker.prompts) == 4, "no integration while a piece is blocked"


def test_skip_lets_the_split_integrate_with_the_piece_marked_missing(conn):
    env = _blocked_split(conn)
    p2 = _pieces(conn)[1]
    assert env.skip(conn, [p2["task_id"]]) == 0, env.out
    plan = log.split_plan_of(_split_row(conn))
    assert plan["pieces"][1]["skipped"] is True
    assert plan["inputs"] == [{"text": P1, "result": R1}, {"text": P2, "result": None}]
    integrate = env.worker.prompts[-1]
    assert f"===== piece 2: {P2} =====\n{split.SKIPPED}" in integrate and R1 in integrate and "R2 FIXED" not in integrate
    assert _split_row(conn)["result"] == JOINED
    assert log.get_task(conn, p2["task_id"])["status"] == "done", "the piece row is untouched"


@pytest.mark.parametrize("status, why", [
    ("failed", "it stopped"), ("timed_out", "it timed out"), ("cancelled", "it was cancelled")])
def test_a_stopped_timed_out_or_cancelled_piece_blocks(conn, status, why):
    env = _grok_split(conn, n_empty=99)
    p3 = _pieces(conn)[2]
    conn.execute("UPDATE tasks SET status = ? WHERE task_id = ?", (status, p3["task_id"]))
    conn.commit()
    env.lines.clear()
    env.go(conn, _split_row(conn)["n"])
    assert f"Piece {p3['task_id']} blocked: {why}." in env.out


def test_a_piece_that_came_back_at_the_approval_blocks(conn):
    env = Env(claude=(PLAN, R1), chatgpt=("PASS",), jev=Jev({P2: {"status": "below_floor", "label": "writing",
                                                                   "confidence": 0.5, "tokens": 3}}))
    env.split(conn, ask=Ask("y", "0"))
    p2 = _pieces(conn)[1]
    assert p2["status"] == "returned"
    assert f"Piece {p2['task_id']} blocked: it came back to you (no skill)." in env.out


def test_an_unchecked_or_quick_answer_piece_counts_as_delivered(conn):
    quick = {"status": "ok", "label": "quick_answer", "confidence": 0.95, "tokens": 5}
    env = Env(claude=(PLAN, R1, "391", JOINED), chatgpt=("PASS", "PASS"), jev=Jev({P2: quick}))
    env.split(conn)
    p2 = _pieces(conn)[1]
    assert (p2["status"], p2["check_state"]) == ("done", "not_needed")
    assert _split_row(conn)["status"] == "done"


@pytest.mark.parametrize("target, why", [
    ("route", "is not a piece"), ("delivered", "is delivered"), ("twice", "already skipped"),
    ("last", "at least one piece must be delivered"), ("nothing", "sr split --skip <piece>")])
def test_skip_refusals(conn, target, why):
    env = _blocked_split(conn)
    p1, p2 = _pieces(conn)
    if target == "route":
        log.add_task(conn, "sr-r", "t", "cli", {"status": "ok", "label": "writing", "confidence": 0.9, "tokens": 0})
        words = ["sr-r"]
    elif target == "delivered":
        words = [p1["task_id"]]
    elif target == "twice":
        plan = log.split_plan_of(_split_row(conn))
        plan["pieces"][1]["skipped"] = True
        log.set_split_plan(conn, _split_row(conn)["task_id"], plan)
        conn.execute("UPDATE tasks SET status = 'failed' WHERE task_id = ?", (p1["task_id"],))
        conn.commit()
        words = [p2["task_id"]]
    elif target == "last":
        conn.execute("UPDATE tasks SET status = 'failed' WHERE task_id = ?", (p1["task_id"],))
        plan = log.split_plan_of(_split_row(conn))
        plan["pieces"][0]["skipped"] = True
        log.set_split_plan(conn, _split_row(conn)["task_id"], plan)
        conn.commit()
        words = [p2["task_id"]]
    else:
        words = []
    before = len(env.worker.prompts)
    assert env.skip(conn, words) == 2
    assert why in env.out and len(env.worker.prompts) == before


def test_skip_refuses_a_piece_whose_split_is_not_waiting_for_pieces(conn):
    env = Env(claude=(PLAN, R1, R2, JOINED), chatgpt=("PASS", "PASS", "PASS"))
    env.split(conn)
    assert env.skip(conn, [_pieces(conn)[1]["task_id"]]) == 2
    assert "not waiting for its pieces" in env.out


def test_a_skipped_piece_resolved_later_is_still_skipped(conn):
    env = _grok_split(conn, n_empty=0)
    p3 = _pieces(conn)[2]
    env.skip(conn, [str(p3["n"])])
    assert log.split_plan_of(_split_row(conn))["inputs"][2] == {"text": P3, "result": None}
    env.check(conn)  # Grok's piece now arrives and is checked as its own task
    assert log.get_task(conn, p3["task_id"])["status"] == "done"
    assert log.split_plan_of(_split_row(conn))["inputs"][2]["result"] is None


# ---------- sr check on waiting splits ----------

def test_sr_check_names_a_plan_awaiting_approval(conn):
    env = Env(claude=(PLAN,))
    cli.cmd_split("Write an intro and a checklist.", conn=conn, **env.kw(ask=None))
    env.lines.clear()
    env.check(conn)
    n = _split_row(conn)["n"]
    assert f"#{n} {_split_row(conn)['task_id']} is awaiting your approval: sr split --go {n}" in env.out


def test_sr_check_prints_each_waiting_splits_pieces_done_waiting_blocked(conn):
    env = _grok_split(conn, n_empty=99)
    p1, p2, p3 = _pieces(conn)
    conn.execute("UPDATE tasks SET status = 'failed', result = 'plan limit on claude' WHERE task_id = ?", (p2["task_id"],))
    conn.commit()
    env.lines.clear()
    env.check(conn)
    assert f"piece 1 #{p1['n']}: done" in env.out
    assert f"piece 2 #{p2['n']}: blocked: it stopped" in env.out
    assert f"piece 3 #{p3['n']}: waiting (with grok)" in env.out


def test_a_split_waiting_for_its_pieces_is_not_counted_open_and_not_sent_again(conn):
    env = _grok_split(conn, n_empty=99)
    sends = len(env.hook.sent)
    env.lines.clear()
    env.check(conn)
    assert len(env.hook.sent) == sends
    assert "1 task(s) still open." in env.out  # the Grok piece only


# ---------- sr cancel on a waiting split (the owner, before phase F) ----------

def _cancel(conn, words):
    lines = []
    code = cli.cmd_cancel(conn=conn, words=words, out=lines.append)
    return code, "\n".join(lines)


def test_cancel_ends_a_split_waiting_on_blocked_pieces_and_leaves_the_pieces_untouched(conn):
    env = _blocked_split(conn)
    row = _split_row(conn)
    before = [tuple(p) for p in _pieces(conn)]
    code, out = _cancel(conn, [str(row["n"])])
    assert code == 0, out
    assert _split_row(conn)["status"] == "cancelled"
    assert [tuple(p) for p in _pieces(conn)] == before, "piece rows untouched"
    assert "Cancelled the split only; its pieces are untouched" in out
    assert log.split_plan_of(_split_row(conn))["pieces"][0]["planner_text"] == P1, "the plan is kept"
    sends = len(env.worker.prompts)
    env.lines.clear()
    env.check(conn)
    assert "Split #" not in env.out and len(env.worker.prompts) == sends, "a cancelled split never integrates"


def test_cancel_ends_a_split_waiting_for_approval(conn):
    env = Env(claude=(PLAN,))
    cli.cmd_split("Write an intro and a checklist.", conn=conn, **env.kw(ask=None))
    code, out = _cancel(conn, [_split_row(conn)["task_id"]])
    assert code == 0 and _split_row(conn)["status"] == "cancelled" and _pieces(conn) == []


def test_cancel_leaves_an_open_piece_open_and_its_split_cancelled(conn):
    env = _grok_split(conn, n_empty=99)
    p3 = _pieces(conn)[2]
    code, out = _cancel(conn, [str(_split_row(conn)["n"])])
    assert code == 0 and log.get_task(conn, p3["task_id"])["status"] == "sent"


def test_cancel_still_refuses_a_returned_task_that_is_not_a_waiting_split(conn):
    log.add_task(conn, "sr-r", "t", "cli", {"status": "ok", "label": "writing", "confidence": 0.9, "tokens": 0})
    log.set_returned(conn, "sr-r", "returned: needs your label")
    code, out = _cancel(conn, ["sr-r"])
    assert code == 1 and "already returned" in out and log.get_task(conn, "sr-r")["status"] == "returned"


def test_cancel_refuses_a_finished_split(conn):
    env = Env(claude=(PLAN, R1, R2, JOINED), chatgpt=("PASS", "PASS", "PASS"))
    env.split(conn)
    code, out = _cancel(conn, [str(_split_row(conn)["n"])])
    assert code == 1 and _split_row(conn)["status"] == "done"
