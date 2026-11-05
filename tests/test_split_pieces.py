"""Build brief 29 (rules 2.41, Split, "How pieces run"; decisions 9 and 10), B3: each piece runs as its team. A route
piece is made and runs as before; a piece of another team is a relay task with the split as its parent, its preset and
its slots as filled at the approval, and runs that preset's stages, contracts and checks as `sr relay <team>` does. Jev
labels every piece at plan time; on a team other than route the label stays in the plan and routes nothing. A versus
piece ends awaiting the owner's pick and a tied vote too: waiting, blocking nothing; the next pieces run and only the
join waits. One Grok piece of a split out at a time, across a vote piece and a research piece. Fake agents, a fake Jev and
a fake webhook; every value here is fake."""
import pytest

from router import __main__ as cli
from router import jsonview, log, presets, split, state
from tests.helpers import teamed
from tests.test_collab import AMENDED, DELIVERABLE, EDITED, PLAN as COLLAB_PLAN
from tests.test_loop import Clock, Scripted
from tests.test_redteam_chain import ATTACKS, BUILD, DELIVERED, REVISION
from tests.test_relay import CONFIG, GOOD_NOTE, ROSTER, Chat, RelayHook
from tests.test_split_approve import Ask, Jev
from tests.test_versus_run import A_TEXT, B_TEXT, REVIEW_OF_A, REVIEW_OF_B
from tests.test_vote_run import A as VOTE_A, B as VOTE_B, FRANCE, G as VOTE_G

TASK = "Two separate things: write a short explainer, and decide one thing."
P1 = "Write a 120-word plain-English explainer of how a heat pump heats a house."
P2 = "Decide whether a two-person team building a small command-line tool should use Python or Go."
JOIN = "The explainer, then the decision."


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


class World:
    """Claude, ChatGPT, Jev and the webhook, shared by every command in a test."""

    def __init__(self, claude=(), chatgpt=(), hook=None, jev=None):
        self.worker, self.chat = Scripted(*claude), Chat(*chatgpt)
        self.hook, self.clock, self.lines, self.jev = hook or RelayHook(), Clock(), [], jev or Jev()

    def kw(self, ask=None):
        return dict(config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=self.jev, ask=ask,
                    post=self.hook.post, worker=self.worker, chatgpt=self.chat, codex_login=lambda: True,
                    fetch=self.hook.fetch, close=self.hook.close, sleep=self.clock.sleep, clock=self.clock,
                    wait=False, out=self.lines.append)

    def split(self, conn, teams_, pieces=(P1, P2)):
        body = "\n".join(f"{k}. {t}" for k, t in enumerate(pieces, 1))
        self.worker.replies.insert(0, teamed(f"## Pieces\n{body}\n\n## Join\n{JOIN}\n", team=list(teams_)))
        return cli.cmd_split(TASK, conn=conn, **self.kw(Ask("y")))

    def check(self, conn):
        return cli.cmd_check(conn=conn, config=CONFIG, environ={}, settings_paths=[], post=self.hook.post,
                             worker=self.worker, chatgpt=self.chat, codex_login=lambda: True, fetch=self.hook.fetch,
                             close=self.hook.close, roster=ROSTER, presets=cli._presets_quietly(),
                             out=self.lines.append)

    @property
    def out(self):
        return "\n".join(self.lines)


def _split(conn):
    return next(r for r in log.recent_tasks(conn, 50) if r["mode"] == "split")


def _pieces(conn):
    return list(log.pieces_of(conn, _split(conn)["task_id"]))


def _stages(conn, row):
    return [(c["kind"], c["stage"], c["role"], c["agent"], c["status"]) for c in log.calls_for(conn, row["task_id"])]


# ---------- the rows (decision 9) ----------

def test_a_team_piece_is_a_relay_row_with_its_parent_its_preset_and_its_slots(conn):
    w = World(claude=("piece one", A_TEXT, REVIEW_OF_B), chatgpt=("PASS", B_TEXT, REVIEW_OF_A))
    w.split(conn, ["route", "versus"])
    first, second = _pieces(conn)
    split_row = _split(conn)
    assert (first["mode"], first["parent"], first["preset"], first["jev_status"]) == (
        "piece", split_row["task_id"], None, "ok")
    assert (second["mode"], second["parent"], second["preset"], second["jev_status"]) == (
        "relay", split_row["task_id"], "versus", "not_asked")
    assert presets.slots_of(second) == {"a": "claude", "b": "chatgpt"}
    assert second["task"] == P2 and second["source"] == "split" and log.is_piece(second) and log.runs_preset(second)
    plan = log.split_plan_of(split_row)
    assert plan["pieces"][1]["label"]["label"] == "writing", "Jev labels every piece, whatever its team"


def test_a_versus_piece_runs_its_four_stages_and_waits_for_a_pick_blocking_nothing(conn):
    w = World(claude=(A_TEXT, REVIEW_OF_B, "piece one"), chatgpt=(B_TEXT, REVIEW_OF_A, "PASS"))
    w.split(conn, ["versus", "route"], pieces=(P2, P1))
    versus, route = _pieces(conn)
    assert _stages(conn, versus) == [("stage", 1, "build", "claude", "done"), ("stage", 2, "build", "chatgpt", "done"),
                                     ("stage", 3, "review", "chatgpt", "done"), ("stage", 4, "review", "claude", "done")]
    versus = log.get_task(conn, versus["task_id"])
    assert (versus["status"], versus["check_note"]) == ("returned", "awaiting pick")
    assert split.piece_state(versus) == ("waiting", "waits for your pick")
    assert log.get_task(conn, route["task_id"])["status"] == "done", "the next piece ran meanwhile"
    assert jsonview.state_of(conn, _split(conn)).waiting_on == "piece"
    assert jsonview.state_of(conn, versus).waiting_on == "pick"
    shown = jsonview.show_view(conn, _split(conn), roster=ROSTER)["pieces"]
    assert shown[0]["piece_state"] == "waiting" and shown[0]["why"] == "waits for your pick"
    assert _split(conn)["status"] == "returned", "the join waits for the pick"


def test_a_redteam_piece_runs_build_attack_revise_and_its_check(conn):
    # brief 32: presets 1.7; this world gives the pieces no Cursor, so the second attack's call fails and is skipped
    labeled = REVISION.replace("## Answered\n3.", "## Answered\nA3:")
    w = World(claude=("piece one", BUILD, labeled, "joined"), chatgpt=("PASS", ATTACKS, "PASS", "PASS"))
    w.split(conn, ["route", "redteam"])
    _, red = _pieces(conn)
    assert [s[:4] for s in _stages(conn, red)] == [("stage", 1, "build", "claude"), ("stage", 2, "attack", "chatgpt"),
                                                    ("stage", 3, "attack", "cursor"), ("stage", 4, "revise", "claude"),
                                                    ("check", None, None, "chatgpt")]
    assert log.calls_for(conn, red["task_id"])[2]["reason_code"] == "skipped"
    red = log.get_task(conn, red["task_id"])
    assert (red["status"], red["check_state"], red["result"]) == ("done", "passed", DELIVERED)
    row = _split(conn)
    assert (row["status"], row["check_state"], row["result"]) == ("done", "passed", "joined")


def test_a_collab_piece_runs_its_chain_and_its_check_stage(conn):
    w = World(claude=("piece one", COLLAB_PLAN, DELIVERABLE, "joined"), chatgpt=("PASS", AMENDED, EDITED, "PASS"))
    w.split(conn, ["route", "collab"])
    _, collab = _pieces(conn)
    assert [s[2] for s in _stages(conn, collab)] == ["plan", "amend", "execute", "edit"]
    collab = log.get_task(conn, collab["task_id"])
    assert (collab["status"], collab["check_state"], collab["check_note"]) == ("done", "passed", "checked-by-stage 4")


def test_a_vote_piece_goes_to_its_grok_stage_and_sr_check_tallies_it(conn):
    hook = RelayHook(s3=VOTE_G)
    w = World(claude=("piece one", VOTE_A, "joined"), chatgpt=("PASS", VOTE_B, "PASS"), hook=hook)
    w.split(conn, ["route", "vote"])
    _, vote = _pieces(conn)
    assert log.get_task(conn, vote["task_id"])["status"] == "sent" and hook.sent[-1]["task_id"].endswith("-s3")
    w.check(conn)
    vote = log.get_task(conn, vote["task_id"])
    assert (vote["status"], vote["check_state"], vote["check_note"]) == ("done", "passed", "checked-by-vote 3/0")
    assert split.piece_state(vote) == ("done", None)


def test_a_tied_vote_piece_waits_for_a_pick(conn):
    hook = RelayHook(s3=VOTE_G)
    w = World(claude=("piece one", FRANCE), chatgpt=("PASS", VOTE_B.replace("texas.", "Spain")), hook=hook)
    w.split(conn, ["route", "vote"])
    w.check(conn)
    _, vote = _pieces(conn)
    vote = log.get_task(conn, vote["task_id"])
    assert (vote["status"], vote["check_note"]) == ("returned", "awaiting pick")
    assert split.piece_state(vote, log.calls_for(conn, vote["task_id"])) == ("waiting", "a tie: waits for your pick")
    assert jsonview.state_of(conn, vote).waiting_on == "vote_pick"


def test_a_research_build_piece_runs_research_build_and_check(conn):
    hook = RelayHook(s1=GOOD_NOTE)
    w = World(claude=("piece one", "Built from the note.", "joined"), chatgpt=("PASS", "PASS", "PASS"), hook=hook)
    w.split(conn, ["route", "research-build"])
    w.check(conn)
    _, research = _pieces(conn)
    research = log.get_task(conn, research["task_id"])
    assert [s[2] for s in _stages(conn, research)][:2] == ["research", "build"]
    assert (research["status"], research["check_state"]) == ("done", "passed")


def test_one_grok_piece_out_at_a_time_across_a_research_piece_and_a_vote_piece(conn):
    hook = RelayHook(s1=GOOD_NOTE, s3=VOTE_G)
    w = World(claude=(VOTE_A, "Built from the note."), chatgpt=(VOTE_B, "PASS"), hook=hook)
    w.split(conn, ["research-build", "vote"], pieces=(P1, P2))
    research, vote = _pieces(conn)
    assert [p["task_id"] for p in hook.sent] == [f"{research['task_id']}-s1"], "the vote's Grok stage is held"
    vote = log.get_task(conn, vote["task_id"])
    assert vote["status"] == "queued" and [s[1] for s in _stages(conn, vote)] == [1, 2]
    assert f"queued (after #{research['n']} with grok)" in w.out
    assert jsonview.state_of(conn, vote, loaded=cli._presets_quietly()).waiting_on == "grok"


def test_jevs_label_on_a_team_piece_is_kept_and_routes_nothing(conn):
    w = World(claude=("piece one", A_TEXT, REVIEW_OF_B), chatgpt=("PASS", B_TEXT, REVIEW_OF_A),
              jev=Jev({P2: {"status": "below_floor", "label": "planning", "confidence": 0.5, "tokens": 100}}))
    w.split(conn, ["route", "versus"])
    assert "Which skill does this task need?" not in w.out, "a team piece under the floor asks nothing"
    _, versus = _pieces(conn)
    assert versus["skill"] is None and versus["jev_status"] == "not_asked"
    assert log.split_plan_of(_split(conn))["pieces"][1]["label"]["label"] == "planning"
