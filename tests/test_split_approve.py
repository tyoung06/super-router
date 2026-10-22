"""Build brief 11, phase B (rules v2.18, Split): `sr split "task"`, the planner, the approval. Nothing runs before
the owner's yes: the plan step writes no piece row; `N` cancels with the plan kept; `y` makes exactly one piece row
per piece with the approved text byte for byte; `e` edits one piece and the log keeps both texts. Without a
terminal the split stops at the plan and `sr split --go <n>` approves it later. Fake agents and a fake Jev only;
every secret here is fake."""
import pytest

from router import __main__ as cli
from router import log, split
from tests.test_loop import Clock, Scripted
from tests.test_relay import CONFIG, ROSTER, Chat, RelayHook

TASK = ("Write a 100-word intro paragraph about adjustable garden seed trays, and a 5-item setup checklist for "
        "using one on a heat mat. No prices.")
P1 = "Write a 100-word intro paragraph about adjustable garden seed trays. No prices."
P2 = "Write a 5-item setup checklist for using an adjustable garden seed tray on a heat mat. No prices."
P3 = "Write “one” closing line — café-style, with  two spaces. No prices."
JOIN = "Put the intro paragraph first, then the checklist under it."
PLAN = f"## Pieces\n1. {P1}\n2. {P2}\n\n## Join\n{JOIN}\n"
PLAN3 = f"## Pieces\n1. {P1}\n2. {P2}\n3. {P3}\n\n## Join\n{JOIN}\n"
WRITING = {"status": "ok", "label": "writing", "confidence": 0.93, "needs_split": 0.2, "tokens": 700}
LOW = {"status": "below_floor", "label": "planning", "confidence": 0.55, "needs_split": 0.2, "tokens": 650}


class Jev:
    """A fake Jev: an answer per text (WRITING by default). Records each call."""

    def __init__(self, answers=None):
        self.answers, self.calls = dict(answers or {}), []

    def __call__(self, task_text, *, task_id, tokens_this_month):
        self.calls.append({"task": task_text, "task_id": task_id, "tokens_this_month": tokens_this_month})
        return dict(self.answers.get(task_text, WRITING))


class Ask:
    """The owner at the terminal: each prompt gets the next scripted reply; EOFError when they run out."""

    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if not self.replies:
            raise EOFError
        return self.replies.pop(0)


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _split(conn, task=TASK, *, claude=(PLAN,), chatgpt=(), ask=None, jev=None, files=(), preset=None, environ=None):
    lines, clock, hook = [], Clock(), RelayHook()
    worker, chat, jev = Scripted(*claude), Chat(*chatgpt), jev or Jev()
    code = cli.cmd_split(task, conn=conn, config=CONFIG, roster=ROSTER, environ=environ or {}, settings_paths=[],
                         label=jev, ask=ask, post=hook.post, worker=worker, chatgpt=chat, codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=False,
                         files=files, preset=preset, out=lines.append)
    return code, "\n".join(lines), worker, chat, jev, hook


def _go(conn, words, *, ask=None, jev=None, claude=(), chatgpt=()):
    lines, clock, hook = [], Clock(), RelayHook()
    worker, chat, jev = Scripted(*claude), Chat(*chatgpt), jev or Jev()
    code = cli.cmd_split_go(words, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=jev,
                            ask=ask, post=hook.post, worker=worker, chatgpt=chat, codex_login=lambda: True,
                            fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=False,
                            out=lines.append)
    return code, "\n".join(lines), worker, chat, jev


def _split_row(conn):
    return next(r for r in log.recent_tasks(conn, 50) if r["mode"] == "split")


def _pieces(conn):
    return [r for r in log.recent_tasks(conn, 50) if r["mode"] == "piece"]


# ---------- refusals: no row, nothing sent ----------

@pytest.mark.parametrize("kwargs, why", [
    ({"files": ["a.png"]}, "a split task carries no files"),
    ({"task": "@claude " + TASK}, "override prefix on a split task"),
    ({"preset": "collab"}, "a split task takes no preset"),
    ({"task": "   "}, "the task is empty"),
    ({"task": "/clear " + TASK}, "can't start with /"),
])
def test_refusals_write_no_row_and_call_no_one(conn, kwargs, why):
    code, out, worker, chat, jev, hook = _split(conn, **kwargs)
    assert code == 2 and why in out and "Nothing was logged or sent." in out
    assert log.recent_tasks(conn) == [] and worker.prompts == [] and chat.prompts == [] and jev.calls == []
    assert hook.sent == []


def test_a_billing_switch_refuses_a_split(conn):
    code, out, worker, *_ = _split(conn, environ={"ANTHROPIC_API_KEY": "fake"})
    assert code == 2 and log.recent_tasks(conn) == [] and worker.prompts == []


# ---------- the plan, no terminal ----------

def test_the_plan_step_asks_claude_once_with_the_plan_prompt_and_writes_no_piece_row(conn):
    code, out, worker, chat, jev, _ = _split(conn)
    assert code == 0, out
    assert worker.prompts == [split.plan_prompt(TASK)] and chat.prompts == []
    assert _pieces(conn) == []
    row = _split_row(conn)
    assert (row["mode"], row["jev_status"], row["agent"], row["checker"], row["route_reason"], row["status"],
            row["check_note"], row["check_state"]) == (
        "split", "not_asked", "claude", "chatgpt", "split", "returned", "awaiting approval", "pending")
    calls = log.calls_for(conn, row["task_id"])
    assert [(c["kind"], c["stage"], c["role"], c["agent"], c["status"]) for c in calls] == [
        ("stage", 1, "split_plan", "claude", "done")]


def test_the_plan_is_stored_with_a_task_id_per_piece_and_jev_labels_each_piece_by_that_id(conn):
    code, out, worker, chat, jev, _ = _split(conn)
    row = _split_row(conn)
    plan = log.split_plan_of(row)
    assert plan["join"] == JOIN and plan["approved"] is False
    assert [p["planner_text"] for p in plan["pieces"]] == [P1, P2]
    ids = [p["id"] for p in plan["pieces"]]
    assert len(set(ids)) == 2 and all(i.startswith("sr-") for i in ids)
    assert [(c["task"], c["task_id"]) for c in jev.calls] == [(P1, ids[0]), (P2, ids[1])]
    assert [p["label"]["label"] for p in plan["pieces"]] == ["writing", "writing"]


def test_plan_time_jev_tokens_sit_on_the_split_row_and_the_cap_sees_them(conn):
    code, out, worker, chat, jev, _ = _split(conn)
    assert _split_row(conn)["jev_tokens"] == 1400
    assert [c["tokens_this_month"] for c in jev.calls] == [0, 700]


def test_without_a_terminal_the_plan_is_printed_and_the_split_stops_at_it(conn):
    code, out, *_ = _split(conn)
    n = _split_row(conn)["n"]
    assert f"Task {n} · split · plan" in out
    assert f"1. {P1}  → writing · claude / chatgpt" in out
    assert f"2. {P2}  → writing · claude / chatgpt" in out
    assert f"Join: {JOIN}" in out
    assert f"No terminal to ask in. Approve it in Terminal: sr split --go {n}" in out
    assert "Run these" not in out


# ---------- the approval ----------

def test_n_cancels_the_split_with_the_plan_kept_and_no_piece_row(conn):
    ask = Ask("n")
    code, out, *_ = _split(conn, ask=ask)
    row = _split_row(conn)
    assert ask.prompts == ["Run these 2 pieces? [y/N/e] "]
    assert row["status"] == "cancelled" and log.split_plan_of(row)["pieces"][0]["planner_text"] == P1
    assert _pieces(conn) == []
    assert "Cancelled: no piece was made. The plan is kept" in out


@pytest.mark.parametrize("reply", ["", "N", "no", "maybe"])
def test_anything_but_y_or_e_is_no(conn, reply):
    _split(conn, ask=Ask(reply))
    assert _split_row(conn)["status"] == "cancelled" and _pieces(conn) == []


def test_no_answer_at_all_leaves_the_split_waiting_for_its_approval(conn):
    code, out, *_ = _split(conn, ask=Ask())
    row = _split_row(conn)
    assert (row["status"], row["check_note"]) == ("returned", "awaiting approval") and _pieces(conn) == []
    assert f"sr split --go {row['n']}" in out


def test_y_makes_exactly_one_piece_row_per_piece_with_the_approved_text_byte_for_byte(conn):
    code, out, worker, chat, jev, _ = _split(conn, claude=(PLAN3,), ask=Ask("y"))
    row = _split_row(conn)
    plan = log.split_plan_of(row)
    pieces = sorted(_pieces(conn), key=lambda r: r["n"])
    assert [p["task"] for p in pieces] == [P1, P2, P3]
    assert [p["task_id"] for p in pieces] == [p["id"] for p in plan["pieces"]]
    for p in pieces:
        assert (p["mode"], p["parent"], p["source"], p["jev_status"], p["jev_label"], p["jev_tokens"]) == (
            "piece", row["task_id"], "split", "ok", "writing", 0)
    assert plan["approved"] is True
    assert f"Approved: 3 pieces, #{pieces[0]['n']}, #{pieces[1]['n']}, #{pieces[2]['n']}." in out
    assert row["jev_tokens"] == 2100 and log.jev_tokens_this_month(conn) == 2100, "no token counted twice"
    assert len(jev.calls) == 3, "the stored label is reused; no second Jev call"


def test_each_piece_row_is_routed_by_the_skill_table(conn):
    _split(conn, ask=Ask("y"))
    for p in _pieces(conn):  # phase C then runs them, so the check state is whatever their loop made
        assert (p["skill"], p["skill_source"], p["agent"], p["checker"], p["route_reason"]) == (
            "writing", "jev", "claude", "chatgpt", "best")


def test_e_edits_one_piece_the_edit_runs_and_both_texts_are_kept(conn):
    edit = "Write a 5-item checklist for a heat mat with an adjustable tray. No prices."
    ask = Ask("e", "2", edit, "y")
    code, out, worker, chat, jev, _ = _split(conn, ask=ask)
    plan = log.split_plan_of(_split_row(conn))
    assert plan["pieces"][1]["planner_text"] == P2 and plan["pieces"][1]["edited_text"] == edit
    assert plan["pieces"][0]["edited_text"] is None
    assert sorted((p["task"] for p in _pieces(conn)), key=[P1, edit].index) == [P1, edit]
    assert [c["task"] for c in jev.calls] == [P1, P2, edit], "an edited piece is relabeled"
    assert jev.calls[2]["task_id"] == plan["pieces"][1]["id"]
    assert out.count("Run these 2 pieces? [y/N/e]") == 0  # the prompt goes to ask(), not out
    assert ask.prompts == ["Run these 2 pieces? [y/N/e] ", "Edit which piece? [1-2] ", "New text for piece 2: ",
                           "Run these 2 pieces? [y/N/e] "]
    assert out.count(f"2. {edit}  → writing · claude / chatgpt") == 1, "the edit is shown before the yes"


def test_an_edit_that_breaks_the_piece_rules_is_not_taken(conn):
    ask = Ask("e", "1", "@grok " + P1, "e", "9", "n")
    code, out, worker, chat, jev, _ = _split(conn, ask=ask)
    plan = log.split_plan_of(_split_row(conn))
    assert all(p["edited_text"] is None for p in plan["pieces"])
    assert "Not changed: the new text starts with @ or /" in out and "Not a piece number" in out
    assert len(jev.calls) == 2


def test_a_piece_below_jevs_floor_shows_ask_and_the_owner_names_its_skill_at_the_yes(conn):
    jev = Jev({P2: LOW})
    ask = Ask("y", "writing")
    code, out, worker, chat, jev, _ = _split(conn, ask=ask, jev=jev)
    assert f"2. {P2}  → ask" in out
    assert "Piece 2: " in out and "Which skill does this task need?" in out
    piece2 = next(p for p in _pieces(conn) if p["task"] == P2)
    assert (piece2["jev_status"], piece2["jev_label"], piece2["skill"], piece2["skill_source"], piece2["agent"]) == (
        "below_floor", "planning", "writing", "owner", "claude")


def test_a_piece_the_owner_answers_none_for_comes_back_and_still_gets_its_row(conn):
    code, out, *_ = _split(conn, ask=Ask("y", "0"), jev=Jev({P2: LOW}))
    piece2 = next(p for p in _pieces(conn) if p["task"] == P2)
    assert (piece2["status"], piece2["route_reason"]) == ("returned", "returned: no skill")


def test_a_piece_whose_skill_isnt_routed_shows_that_it_comes_back(conn):
    jev = Jev({P2: {"status": "ok", "label": "computer_use", "confidence": 0.9, "tokens": 5}})
    code, out, *_ = _split(conn, jev=jev)
    assert f"2. {P2}  → comes back: skill not routed in version 2" in out


# ---------- the plan's contract ----------

def test_a_missed_contract_is_re_asked_once_and_the_re_asks_pieces_are_used(conn):
    code, out, worker, chat, jev, _ = _split(conn, claude=("1. just a list", PLAN))
    assert len(worker.prompts) == 2 and split.PLAN_SHAPE in worker.prompts[1]
    calls = log.calls_for(conn, _split_row(conn)["task_id"])
    assert [(c["kind"], c["stage"], c["role"]) for c in calls] == [("stage", 1, "split_plan"), ("reask", 1, "split_plan")]
    assert [p["planner_text"] for p in log.split_plan_of(_split_row(conn))["pieces"]] == [P1, P2]


def test_still_missing_after_the_re_ask_stops_the_split_with_no_piece_and_no_jev_call(conn):
    code, out, worker, chat, jev, _ = _split(conn, claude=("nothing", "still nothing"), ask=Ask("y"))
    row = _split_row(conn)
    assert code == 1 and (row["status"], row["failed_stage"]) == ("failed", 1)
    assert "SPLIT FAILED at stage 1 (split_plan by claude)" in out and "contract still missing" in out
    assert _pieces(conn) == [] and jev.calls == [] and log.split_plan_of(row) is None


# ---------- sr split --go ----------

def test_go_approves_a_plan_that_waited_and_reuses_the_stored_labels(conn):
    _split(conn)
    n = _split_row(conn)["n"]
    code, out, worker, chat, jev = _go(conn, [str(n)], ask=Ask("y"))
    assert code == 0, out
    assert len(_pieces(conn)) == 2 and jev.calls == [] and worker.prompts[:2] == [P1, P2], "no second plan call"
    assert f"Task {n} · split · plan" in out


def test_go_without_a_terminal_prints_the_plan_and_changes_nothing(conn):
    _split(conn)
    n = _split_row(conn)["n"]
    code, out, *_ = _go(conn, [f"#{n}"])
    assert code == 0 and f"sr split --go {n}" in out and _pieces(conn) == []
    assert _split_row(conn)["check_note"] == "awaiting approval"


def test_go_refuses_a_task_that_is_not_a_split(conn):
    log.add_task(conn, "sr-r", "t", "cli", WRITING)
    code, out, *_ = _go(conn, ["1"], ask=Ask("y"))
    assert code == 2 and "not a split task" in out


def test_go_refuses_a_cancelled_split(conn):
    _split(conn, ask=Ask("n"))
    code, out, *_ = _go(conn, [str(_split_row(conn)["n"])], ask=Ask("y"))
    assert code == 2 and "cancelled" in out and _pieces(conn) == []


def test_go_needs_a_task(conn):
    code, out, *_ = _go(conn, [], ask=Ask("y"))
    assert code == 2 and "sr split --go <n>" in out
