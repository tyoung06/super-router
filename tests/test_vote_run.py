"""Build brief 17, phase C (rules v2.24, Relay: tally presets): the vote chain end to end with fake agents. Three
stages, each the task alone; the chain ends in the tally, never in a checker (decision 6); a stop leaves no tally
(decision 8); Grok at stage 3 waits and `sr check` collects, re-asks through the webhook once, and tallies
(decision 12); Grok at stage 2 waits and `sr check` runs stage 3 (choice 4); a Grok voter's whole prompt past
`grok_prompt_limit` is refused at intake with both lengths (decision 13, the owner's flag B). Every value here is fake."""
import pytest

from router import __main__ as cli
from router import checking, log, presets, relay, settings
from tests.helpers import shipped_roster
from tests.test_relay import CONFIG, Chat, Clock, RelayHook

SENDERS = tuple(cli.SENDERS)
ROSTER = shipped_roster()
LOADED = presets.load_presets(ROSTER, SENDERS, relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
TASK = "Which of these is the largest by land area: Texas, France, or Spain? Answer with the name only."


def vote(answer, why="Because.", confidence="80"):
    return f"## Answer\n{answer}\n\n## Why\n{why}\n\n## Confidence\n{confidence}"


A = vote("Texas", why="CLAUDE-WHY-x81 Texas is about 696,000 km².", confidence="90")
B = vote("texas.", why="CHATGPT-WHY-x82 France is about 551,000 km².", confidence="85")
G = vote("**Texas**", why="GROK-WHY-x83 Spain is about 506,000 km².", confidence="70")
FRANCE = vote("France", why="DISSENT-x84 Metropolitan France only.", confidence="40")


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


class World:
    """One scripted set of agents shared by `sr relay` and the `sr check` runs after it."""

    def __init__(self, claude=(), chatgpt=(), grok=None, fail=()):
        self.worker, self.chat = Chat(*claude), Chat(*chatgpt)  # Chat takes search= too
        self.hook, self.clock, self.lines = RelayHook(fail=fail, **(grok or {})), Clock(), []

    def relay(self, conn, slots=(), task=TASK, ready=None):
        code = cli.cmd_relay("vote", task, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                             settings_paths=[], post=self.hook.post, worker=self.worker, chatgpt=self.chat,
                             codex_login=lambda: True, fetch=self.hook.fetch, close=self.hook.close,
                             sleep=self.clock.sleep, clock=self.clock, wait=False, slots=list(slots),
                             claude_ready=ready, out=self.lines.append)
        return code, (log.recent_tasks(conn)[0] if log.recent_tasks(conn) else None)

    def check(self, conn):
        code = cli.cmd_check(conn=conn, config=CONFIG, environ={}, settings_paths=[], post=self.hook.post,
                             worker=self.worker, chatgpt=self.chat, codex_login=lambda: True, fetch=self.hook.fetch,
                             close=self.hook.close, presets=LOADED, roster=ROSTER, out=self.lines.append)
        return code

    @property
    def out(self):
        return "\n".join(self.lines)


def _rows(conn, row):
    return [(c["kind"], c["stage"], c["role"], c["agent"], c["status"]) for c in log.calls_for(conn, row["task_id"])]


def _row(conn, row):
    return log.get_task(conn, row["task_id"])


# ---------- defaults: Claude, ChatGPT, then Grok, which waits for `sr check` ----------

def test_the_chain_waits_on_grok_at_stage_3_and_sr_check_tallies_3_0(conn):
    w = World(claude=[A], chatgpt=[B, "PASS", "PASS"], grok={"s3": G})
    code, row = w.relay(conn)
    assert code == 0
    assert _rows(conn, row) == [("stage", 1, "vote", "claude", "done"), ("stage", 2, "vote", "chatgpt", "done"),
                                ("stage", 3, "vote", "grok", "sent")]
    assert _row(conn, row)["status"] == "sent"
    assert w.check(conn) == 0
    row = _row(conn, row)
    assert _rows(conn, row) == [("stage", 1, "vote", "claude", "done"), ("stage", 2, "vote", "chatgpt", "done"),
                                ("stage", 3, "vote", "grok", "done")]   # no checker, no fix round (decision 6)
    assert (row["status"], row["check_state"], row["checker"], row["agent"], row["check_note"]) == (
        "done", "passed", None, "claude", "checked-by-vote 3/0")
    assert row["result"] == A          # byte for byte the first stage that gave the answer
    assert len(w.chat.prompts) == 1    # the fake checker was never asked
    assert "Answer: Texas (checked-by-vote 3/0)" in w.out


def test_the_intro_line_names_the_tally(conn):
    w = World(claude=[A], chatgpt=[B], grok={"s3": G})
    w.relay(conn)
    assert ": relay vote: vote by claude -> vote by chatgpt -> vote by grok, then the tally." in w.out


@pytest.mark.parametrize("answers, winner, agent, note", [
    ((FRANCE, B, G), 2, "chatgpt", "checked-by-vote 2/1"),
    ((A, FRANCE, G), 1, "claude", "checked-by-vote 2/1"),
    ((A, B, vote("France")), 1, "claude", "checked-by-vote 2/1"),
])
def test_two_to_one_takes_the_first_agreeing_stage_raw(conn, answers, winner, agent, note):
    w = World(claude=[answers[0]], chatgpt=[answers[1]], grok={"s3": answers[2]})
    w.relay(conn)
    w.check(conn)
    row = log.recent_tasks(conn)[0]
    assert (row["status"], row["check_state"], row["agent"], row["checker"], row["check_note"]) == (
        "done", "passed", agent, None, note)
    assert row["result"] == answers[winner - 1]


def test_three_different_answers_wait_for_the_owners_pick_with_nothing_as_the_result(conn):
    w = World(claude=[A], chatgpt=[FRANCE], grok={"s3": vote("Spain")})
    w.relay(conn)
    assert w.check(conn) == 0
    row = log.recent_tasks(conn)[0]
    assert (row["status"], row["check_note"], row["result"], row["agent"], row["checker"], row["check_state"]) == (
        "returned", "awaiting pick", None, None, None, None)
    assert relay.awaiting_pick(row)
    assert "Pick: sr pick 1 a | b | c | none" in w.out


def test_sr_check_on_a_vote_awaiting_pick_does_nothing_and_says_so(conn):
    w = World(claude=[A], chatgpt=[FRANCE], grok={"s3": vote("Spain")})
    w.relay(conn)
    w.check(conn)
    before = dict(log.recent_tasks(conn)[0]), len(log.calls_for(conn, log.recent_tasks(conn)[0]["task_id"]))
    w.lines.clear()
    assert w.check(conn) == 0
    after = log.recent_tasks(conn)[0]
    assert dict(after) == before[0] and len(log.calls_for(conn, after["task_id"])) == before[1]
    assert f"#1 {after['task_id']} is awaiting your pick: sr pick 1 a|b|c|none" in w.out


# ---------- Grok's contract re-ask through the webhook (decision 12) ----------

def test_a_grok_miss_is_re_asked_through_the_webhook_then_tallied(conn):
    w = World(claude=[A], chatgpt=[B], grok={"s3": "Texas, surely.", "s3r": G})
    w.relay(conn)
    w.check(conn)                     # collects s3, finds the contract missed, sends s3r
    row = log.recent_tasks(conn)[0]
    assert _rows(conn, row)[-2:] == [("stage", 3, "vote", "grok", "done"), ("reask", 3, "vote", "grok", "sent")]
    reask = w.hook.sent[-1]
    assert reask["task_id"].endswith("-s3r") and "Answer: the ## Answer heading is missing" in reask["task"]
    w.check(conn)                     # collects s3r and tallies
    row = _row(conn, row)
    assert (row["status"], row["check_note"]) == ("done", "checked-by-vote 3/0")


def test_a_grok_miss_after_the_re_ask_stops_the_chain_with_no_tally(conn):
    w = World(claude=[A], chatgpt=[B], grok={"s3": "Texas.", "s3r": "Still Texas."})
    w.relay(conn)
    w.check(conn)
    w.check(conn)
    row = log.recent_tasks(conn)[0]
    assert (row["status"], row["failed_stage"]) == ("failed", 3)
    assert "contract still missing after the re-ask" in row["result"]
    assert "checked-by-vote" not in (row["check_note"] or "")
    assert "CLAUDE-WHY-x81" in w.out and "CHATGPT-WHY-x82" in w.out   # every answer so far is shown


# ---------- a stop (decision 8) ----------

def test_a_stop_at_stage_2_leaves_no_tally_and_shows_the_one_answer(conn):
    from router.chatgpt_worker import WorkerError
    w = World(claude=[A], chatgpt=[WorkerError("codex exited 1: boom")])
    code, row = w.relay(conn)
    assert code == 1
    row = _row(conn, row)
    assert (row["status"], row["failed_stage"]) == ("failed", 2)
    assert "checked-by-vote" not in (row["check_note"] or "") and row["check_state"] != "passed"
    assert "CLAUDE-WHY-x81" in w.out and w.hook.sent == []            # Grok never sent
    assert _rows(conn, row) == [("stage", 1, "vote", "claude", "done"), ("stage", 2, "vote", "chatgpt", "failed")]


# ---------- what each voter gets ----------

def test_each_voter_gets_the_task_alone_and_never_another_answer(conn):
    w = World(claude=[A], chatgpt=[B], grok={"s3": G})
    w.relay(conn, ready=lambda *a: True)
    claude, chatgpt, grok = w.worker.prompts[0], w.chat.prompts[0], w.hook.sent[0]["task"]
    assert claude == relay.vote_prompt(TASK, search=True)
    assert chatgpt == relay.vote_prompt(TASK, search=True)
    assert grok == relay.vote_prompt(TASK, search=False)   # the router never switches Grok's search on or off
    for marker in ("CLAUDE-WHY-x81", "696,000"):
        assert marker not in chatgpt and marker not in grok
    for marker in ("CHATGPT-WHY-x82", "551,000"):
        assert marker not in grok
    for prompt in (claude, chatgpt, grok):
        assert relay.VOTE_DATA_LINE in prompt and checking.SCOPE_PARAGRAPH in prompt
        assert "The result is" not in prompt   # no count line on a vote (decision 16)
    assert checking.SEARCH_LINE_GENERAL in claude and checking.SEARCH_LINE_GENERAL in chatgpt
    assert checking.SEARCH_LINE_GENERAL not in grok


# ---------- Grok at stage 2 (choice 4: no change; the chain waits there and `sr check` runs stage 3) ----------

def test_grok_at_stage_2_waits_then_sr_check_runs_claude_at_stage_3(conn):
    w = World(claude=[A], chatgpt=[B], grok={"s2": G})
    code, row = w.relay(conn, slots=[("a", "chatgpt"), ("b", "grok"), ("c", "claude")])
    assert code == 0
    assert _rows(conn, row) == [("stage", 1, "vote", "chatgpt", "done"), ("stage", 2, "vote", "grok", "sent")]
    assert w.worker.prompts == []      # Claude waits for Grok
    w.check(conn)
    row = _row(conn, row)
    assert _rows(conn, row) == [("stage", 1, "vote", "chatgpt", "done"), ("stage", 2, "vote", "grok", "done"),
                                ("stage", 3, "vote", "claude", "done")]
    assert (row["status"], row["agent"], row["check_note"], row["result"]) == ("done", "chatgpt", "checked-by-vote 3/0", B)
    assert "GROK-WHY-x83" not in w.worker.prompts[0] and "CHATGPT-WHY-x82" not in w.worker.prompts[0]


# ---------- the Grok prompt limit at intake (decision 13, the owner's flag B) ----------

def test_a_grok_voter_whose_whole_prompt_is_past_the_limit_is_refused_with_both_lengths(conn, monkeypatch):
    monkeypatch.setattr(settings, "grok_prompt_limit", lambda: (1200, "config/settings.json"))
    task = "Yes or no? " + "x" * 600
    w = World()
    code, row = w.relay(conn, task=task)
    prompt = relay.vote_prompt(task, search=False)
    assert code == 2 and row is None and w.hook.sent == [] and w.worker.prompts == []
    assert (f"Refused: the task is too long for grok's vote (slot c): its prompt would be {len(prompt)} characters, "
            f"the task alone {len(task)}; grok's limit is 1200. Shorten the task, or put another agent in slot c. "
            "Nothing was logged or sent.") in w.out


def test_the_limit_is_asked_of_whichever_slot_holds_grok(conn, monkeypatch):
    monkeypatch.setattr(settings, "grok_prompt_limit", lambda: (1200, "config/settings.json"))
    w = World()
    code, row = w.relay(conn, slots=[("a", "grok"), ("c", "claude")], task="Yes or no? " + "x" * 600)
    assert code == 2 and row is None and "(slot a)" in w.out


def test_a_task_under_the_limit_runs(conn, monkeypatch):
    monkeypatch.setattr(settings, "grok_prompt_limit", lambda: (3662, "config/settings.json"))
    w = World(claude=[A], chatgpt=[B], grok={"s3": G})
    code, row = w.relay(conn)
    assert code == 0 and len(w.hook.sent) == 1
    assert len(w.hook.sent[0]["task"]) < 3662
