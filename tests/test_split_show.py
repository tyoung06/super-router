"""Build brief 11, phase E (rules v2.18, Split): what the owner sees. `sr show <n>` on a split prints the plan (each
piece with its task number and status), the joining line, the split's own stages, then the integrated result and
its check as any task; `--pieces` prints each piece's result; `sr show <piece>` says which split it belongs to;
`sr log` reads `split · k pieces`; the status page shows `pieces: done/total`. Fake agents and Jev only."""
import pytest

from router import __main__ as cli
from router import jsonview, log, page, split
from tests.test_relay import ROSTER
from tests.test_split_approve import JOIN, P1, P2, Ask
from tests.test_split_wait import R1, R2, JOINED, Env, _blocked_split

TASK = "Write an intro and a checklist. No prices."
PLAN = f"## Pieces\n1. {P1}\n2. {P2}\n\n## Join\n{JOIN}\n"


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _split_row(conn):
    return next(r for r in log.recent_tasks(conn, 50) if r["mode"] == "split")


def _show(conn, words, **kw):
    lines = []
    code = cli.cmd_show(conn=conn, words=words, roster=ROSTER, out=lines.append, **kw)
    return code, "\n".join(lines)


def _passed(conn):
    env = Env(claude=(PLAN, R1, R2, JOINED), chatgpt=("PASS", "PASS", "PASS"))
    env.split(conn, TASK)
    return _split_row(conn)


# ---------- sr show <split> ----------

def test_show_a_passed_split_prints_the_plan_the_stages_and_the_result(conn):
    row = _passed(conn)
    p1, p2 = log.pieces_of(conn, row["task_id"])
    code, out = _show(conn, [str(row["n"])])
    assert code == 0
    lines = out.splitlines()
    assert lines[0].startswith(f"#{row['n']}  {row['task_id']}  done")
    assert "Split: 2 pieces" in lines
    assert "Jev: not asked (split task; Jev labels each piece)" in lines
    assert f"  1. #{p1['n']} done · writing · claude / chatgpt: {P1}" in lines
    assert f"  2. #{p2['n']} done · writing · claude / chatgpt: {P2}" in lines
    assert f"Join: {JOIN}" in lines
    assert "  1. split_plan by claude: passed" in lines and "  2. integrate by claude: passed" in lines
    assert "Checker: chatgpt   Check: passed" in lines
    assert out.index("Task:") < out.index("Result:") and JOINED in out
    assert R1 not in out, "piece results only with --pieces"


def test_show_pieces_prints_each_pieces_result_in_plan_order(conn):
    row = _passed(conn)
    p1, p2 = log.pieces_of(conn, row["task_id"])
    code, out = _show(conn, [str(row["n"])], pieces=True)
    assert f"Piece 1 · #{p1['n']} · claude · passed:\n{R1}" in out
    assert f"Piece 2 · #{p2['n']} · claude · passed:\n{R2}" in out
    assert out.index("Piece 1 ·") < out.index("Piece 2 ·")


def test_show_a_plan_waiting_for_approval_shows_where_each_piece_would_go(conn):
    env = Env(claude=(PLAN,))
    cli.cmd_split(TASK, conn=conn, **env.kw(ask=None))
    row = _split_row(conn)
    code, out = _show(conn, [str(row["n"])])
    assert f"#{row['n']}  {row['task_id']}  approve plan" in out
    assert f"  1. (no task yet) → writing · claude / chatgpt: {P1}" in out
    assert f"(waiting for your approval: sr split --go {row['n']})" in out


def test_show_an_edited_piece_shows_both_texts(conn):
    edit = "Write a 5-item checklist for a heat mat. No prices."
    env = Env(claude=(PLAN, R1, R2, JOINED), chatgpt=("PASS", "PASS", "PASS"))
    env.split(conn, TASK, ask=Ask("e", "2", edit, "y"))
    code, out = _show(conn, [str(_split_row(conn)["n"])])
    assert f": {edit}" in out and f"     (edited; the planner wrote: {P2})" in out


def test_show_a_split_waiting_on_a_blocked_piece_and_after_a_skip(conn):
    env = _blocked_split(conn)
    row = _split_row(conn)
    p2 = log.pieces_of(conn, row["task_id"])[1]
    code, out = _show(conn, [str(row["n"])])
    assert f"  2. #{p2['n']} blocked: it failed its check twice · writing · claude / chatgpt: {P2}" in out
    assert f"(waiting for its pieces: 1 of 2 done; `sr check` or `sr split --go {row['n']}` moves it on)" in out
    env.skip(conn, [p2["task_id"]])
    code, out = _show(conn, [str(row["n"])])
    assert f"  2. #{p2['n']} skipped · writing · claude / chatgpt: {P2}" in out


def test_show_a_cancelled_split_keeps_its_plan(conn):
    env = Env(claude=(PLAN,))
    env.split(conn, TASK, ask=Ask("n"))
    code, out = _show(conn, [str(_split_row(conn)["n"])])
    assert "cancelled" in out.splitlines()[0] and P1 in out and "(cancelled by you)" in out


def test_show_a_split_that_failed_at_its_plan(conn):
    env = Env(claude=("nothing", "still nothing"))
    env.split(conn, TASK)
    code, out = _show(conn, [str(_split_row(conn)["n"])])
    assert "SPLIT FAILED at stage 1 (split_plan by claude)" in out and "(no plan stored)" in out


def test_pieces_on_a_task_that_is_not_a_split(conn):
    log.add_task(conn, "sr-r", "t", "cli", {"status": "ok", "label": "writing", "confidence": 0.9, "tokens": 0})
    code, out = _show(conn, ["sr-r"], pieces=True)
    assert "This is not a split task, so it has no pieces." in out


# ---------- sr show <piece> ----------

def test_show_a_piece_says_which_split_it_belongs_to_on_its_first_line(conn):
    row = _passed(conn)
    p1 = log.pieces_of(conn, row["task_id"])[0]
    code, out = _show(conn, [str(p1["n"])])
    first = out.splitlines()[0]
    assert first.startswith(f"#{p1['n']}  {p1['task_id']}  done") and first.endswith(f"piece of task #{row['n']}")
    assert R1 in out and "Skill: writing" in out
    assert "Jev: writing, confidence 0.93 (ok, tokens counted on its split)" in out


# ---------- sr log ----------

def test_sr_log_reads_split_and_its_piece_count_with_the_pieces_beneath(conn):
    row = _passed(conn)
    lines = []
    cli.cmd_log(conn=conn, out=lines.append)
    split_line = next(line for line in lines if row["task_id"] in line)
    assert "split · 2 pieces" in split_line
    assert lines.index(split_line) + 2 < len(lines) and all("↳" in line for line in lines[lines.index(split_line) + 1:])


def test_sr_log_status_reads_approve_plan_while_the_plan_waits(conn):
    env = Env(claude=(PLAN,))
    cli.cmd_split(TASK, conn=conn, **env.kw(ask=None))
    lines = []
    cli.cmd_log(conn=conn, out=lines.append)
    assert "approve plan" in lines[1] and "split · 2 pieces" in lines[1]


# ---------- the status page ----------

def test_the_page_shows_pieces_done_over_total_on_a_split_and_the_parent_on_a_piece(conn):
    """Brief 21, B4: from `sr show --json` and `sr log --json` (jsonview): the split's pieces with their states, and each
    piece naming its split."""
    env = _blocked_split(conn)
    rows = jsonview.log_view(conn, log.recent_tasks(conn, 50), limit=50)["tasks"]
    s = next(r for r in rows if r["mode"] == "split")
    shown = jsonview.show_view(conn, log.get_task(conn, s["task_id"]))
    assert [p["outcome"] for p in shown["pieces"]].count("passed") + [p["outcome"] for p in shown["pieces"]].count(
        "fixed") == 1 and len(shown["pieces"]) == 2 and s["waiting_on"] == "piece"
    piece = next(r for r in rows if r["mode"] == "piece")
    assert piece["parent"] == s["task_id"]
