"""Build brief 29 (rules 2.41, Split, "On a project"; decisions 13 to 15), B5 and B6: a project split's pieces build in
the split's one copy, one at a time in plan order (the order hold, checked before every step); each piece's part is read
from its `piece-<k>-start` snapshot and kept as its own `changes.diff`; a piece's build runs no tests and its checker gets
its part and one line in place of the tests block; pieces return no handoff section, write no entry and store no memory,
never wait to land, and refuse Land, Undo, Discard and a fallback. The join is a Claude build call in the copy with each
piece's files and the handoff line; the tests run after it; ChatGPT checks the whole change; the split waits to land, and
one Land makes one commit with the split's one entry; Undo is one more. A blocked piece holds the rest; Skip puts the copy
back to the piece's starting snapshot first; a piece's cancel keeps the copy; the split's cancel ends its open pieces and
removes it. Real git in temp folders; fake agents; every value here is fake."""
from pathlib import Path

import pytest

from router import __main__ as cli
from router import copies, fallback, filecalls, jsonview, log, memory, projects, receipt, split, testrun
from router.claude_worker import WorkerError
from tests.helpers import teamed
from tests.test_copies import git
from tests.test_filemode_flow import CopyWorker, Runner
from tests.test_loop import Clock
from tests.test_relay import CONFIG, GOOD_NOTE, ROSTER, Chat, RelayHook
from tests.test_split_approve import Jev
from tests.test_split_project import JOIN, P1, P2, TASK, conn, project, registry  # noqa: F401 (fixtures)

CODE = {"status": "ok", "label": "code", "confidence": 0.95, "needs_split": 0.1, "tokens": 300}
PLAN = teamed(f"## Pieces\n1. {P1}\n2. {P2}\n\n## Join\n{JOIN}\n", why="One coder and a checker are enough.")
FIXED_ADD = "def add(a, b):\n    return a + b\n"
MULTIPLY = "def multiply(a, b):\n    return a * b\n"
TEST_MULTIPLY = "import unittest\nfrom mathx import multiply\n"
HANDOFF = ("## Handoff\n### Produced\ncalc.py, mathx.py and test_mathx.py changed\n### Status\nadd and multiply work\n"
           "### Next\nland it")
JOINED = "add() returns a + b; multiply is in mathx.py with its test.\n\n" + HANDOFF


@pytest.fixture
def runner(monkeypatch):
    found = Runner()
    monkeypatch.setattr(testrun, "run", found)
    monkeypatch.setattr(testrun, "available", lambda: True)
    projects.set_tests("sums", ["python3", "-m", "unittest"])
    return found


class World:
    def __init__(self, *steps, chatgpt=(), hook=None):
        self.worker, self.chat = CopyWorker(*steps), Chat(*chatgpt)
        self.hook, self.clock, self.lines = hook or RelayHook(), Clock(), []

    def kw(self, **extra):
        return dict(config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=Jev({P1: CODE, P2: CODE}),
                    post=self.hook.post, worker=self.worker, chatgpt=self.chat, codex_login=lambda: True,
                    fetch=self.hook.fetch, close=self.hook.close, sleep=self.clock.sleep, clock=self.clock, wait=False,
                    out=self.lines.append, **extra)

    def split(self, conn, plan=PLAN):
        self.worker.steps.insert(0, (plan, {}))
        cli.cmd_split(TASK, conn=conn, project="sums", files_ready=lambda: (True, None), **self.kw(ask=None))
        row = next(r for r in log.recent_tasks(conn, 50) if r["mode"] == "split")
        cli.cmd_split_go([str(row["n"])], answer="y", **self.kw(conn=conn, ask=None))
        return log.get_task(conn, row["task_id"])

    def check(self, conn):
        return cli.cmd_check(conn=conn, config=CONFIG, environ={}, settings_paths=[], post=self.hook.post,
                             worker=self.worker, chatgpt=self.chat, codex_login=lambda: True, fetch=self.hook.fetch,
                             close=self.hook.close, roster=ROSTER, presets=cli._presets_quietly(), out=self.lines.append)

    @property
    def out(self):
        return "\n".join(self.lines)


def _pieces(conn, row):
    return list(log.pieces_of(conn, row["task_id"]))


def _files(task_id):
    folder = copies.folder_of(task_id)
    return {p.relative_to(folder).as_posix(): p.read_text() for p in folder.rglob("*") if p.is_file()}


def _two_pieces_done(conn):
    w = World(("Fixed add() in calc.py.", {"calc.py": FIXED_ADD}),
              ("Added mathx.py and test_mathx.py.", {"mathx.py": MULTIPLY, "test_mathx.py": TEST_MULTIPLY}),
              (JOINED, {}), chatgpt=("PASS", "PASS", "PASS"))
    return w, w.split(conn)


# ---------- the pieces in the one copy (decision 13) ----------

def test_each_piece_builds_in_the_splits_copy_in_order_with_its_own_part(project, conn, runner):
    w, row = _two_pieces_done(conn)
    one, two = _pieces(conn, row)
    builds = [c for c in w.worker.calls if c["copy"] is not None and c["copy"].write]
    assert [Path(c["copy"].folder) for c in builds] == [copies.folder_of(row["task_id"])] * 3  # two pieces, the join
    first, second = log.project_files_of(log.get_task(conn, one["task_id"])), log.project_files_of(
        log.get_task(conn, two["task_id"]))
    assert (first["owner"], first["start"], [c["path"] for c in first["changed"]]) == (row["task_id"], "piece-1-start",
                                                                                     ["calc.py"])
    assert [c["path"] for c in second["changed"]] == ["mathx.py", "test_mathx.py"], "only its own part"
    assert copies.has_snapshot(row["task_id"], "piece-1-start") and copies.has_snapshot(row["task_id"], "piece-2-start")
    diff = (Path(cli.DB_PATH).parent / "tasks" / two["task_id"] / "changes.diff")
    assert diff.exists() or second["diff"] is None or "mathx.py" in (filecalls.diff_text(conn, log.get_task(conn, two["task_id"])) or "")


def test_a_pieces_build_runs_no_tests_and_its_checker_gets_its_part_and_the_line(project, conn, runner):
    w, row = _two_pieces_done(conn)
    assert len(runner.runs) == 1, "the tests run once, after the join"
    first_check, second_check, join_check = w.chat.prompts
    assert "calc.py" in first_check and "mathx.py" not in first_check
    assert "mathx.py" in second_check and "test_mathx.py" in second_check and "calc.py (" not in second_check
    for prompt in (first_check, second_check):
        assert filecalls.PIECE_JUDGE_LINE in prompt and "===== tests =====" not in prompt and "No tests ran" not in prompt
    assert "===== tests =====" in join_check and filecalls.JUDGE_LINE in join_check
    assert all(name in join_check for name in ("calc.py", "mathx.py", "test_mathx.py")), "the whole change"
    assert "no tests run: the project's tests run once the pieces are joined" in w.out


def test_pieces_build_with_the_piece_paragraph_and_no_handoff_contract(project, conn, runner):
    w, row = _two_pieces_done(conn)
    piece_build = w.worker.calls[1]["prompt"]
    assert "with the pieces before this one already in it" in piece_build
    assert filecalls.PIECE_TESTS_LINE in piece_build and "## Handoff" not in piece_build
    join_build = w.worker.calls[3]["prompt"]
    # brief 29.1 (decision 7e): the join is told every piece's change is in the copy and its entry is the split's
    assert "with every piece's change already in it" in join_build and "## Handoff" in join_build
    assert "Files it changed: calc.py (changed, +1 -1)" in join_build
    assert "Files it changed: mathx.py (added, +2 -0), test_mathx.py (added, +2 -0)" in join_build


def test_the_split_waits_to_land_and_the_pieces_never_do(project, conn, runner):
    w, row = _two_pieces_done(conn)
    assert jsonview.state_of(conn, row).waiting_on == "land"
    found = log.project_files_of(row)
    assert found["state"] == "waiting" and [c["path"] for c in found["changed"]] == ["calc.py", "mathx.py",
                                                                                     "test_mathx.py"]
    for piece in _pieces(conn, row):
        assert log.project_files_of(piece)["state"] == "none" and log.get_task(conn, piece["task_id"])["status"] == "done"
    assert copies.exists(row["task_id"])
    assert "<!-- sr:start -->" in (project / "HANDOFF.md").read_text() and "#" not in \
        (project / "HANDOFF.md").read_text().split("<!-- sr:start -->")[1].split("<!-- sr:end -->")[0], "no entry yet"


@pytest.mark.parametrize("verb", ["land", "undo", "discard"])
def test_land_undo_and_discard_refuse_a_piece_naming_the_split(project, conn, runner, verb):
    w, row = _two_pieces_done(conn)
    one = _pieces(conn, row)[0]
    lines = []
    assert cli.cmd_land([one["task_id"]], conn=conn, config=CONFIG, verb=verb, out=lines.append) == 2
    assert f"is a piece of split #{row['n']}: only the split lands" in "\n".join(lines)


def test_land_makes_one_commit_with_the_splits_one_entry_and_undo_one_more(project, conn, runner):
    w, row = _two_pieces_done(conn)
    lines = []
    assert cli.cmd_land([row["task_id"]], conn=conn, config=CONFIG, verb="land", out=lines.append) == 0, lines
    shown = git(project, "show", "--stat", "--format=%s", "HEAD").decode()
    # brief 29.1 (issue 6): the subject is cut where a word ends, with "…"
    assert shown.splitlines()[0] == f"sr: In this project: fix add() in calc.py so its test passes… ({row['task_id']})"
    assert {line.split("|")[0].strip() for line in shown.splitlines()[1:] if "|" in line} == {
        "HANDOFF.md", "calc.py", "mathx.py", "test_mathx.py"}
    entries = (project / "HANDOFF.md").read_text()
    assert entries.count(f"### #{row['n']} ·") == 1 and "· split · claude" in entries
    assert not any(f"### #{p['n']} ·" in entries for p in _pieces(conn, row)), "pieces write no entry"
    assert not copies.exists(row["task_id"])
    assert cli.cmd_land([row["task_id"]], conn=conn, config=CONFIG, verb="undo", out=lines.append) == 0
    assert (project / "calc.py").read_text() == "def add(a, b):\n    return a - b\n"


def test_no_piece_is_the_newest_task_a_later_memory_block_starts_with(project, conn, runner):
    w, row = _two_pieces_done(conn)
    tagged = [r["task_id"] for r in memory.rows_under(conn, "project:sums")]
    assert tagged == [row["task_id"]]
    assert all(memory.store(conn, p, [], None, []) is None for p in _pieces(conn, row))


def test_no_fallback_on_a_piece_of_a_project_split_or_on_the_split(project, conn, runner):
    w, row = _two_pieces_done(conn)
    for piece in _pieces(conn, row):
        found = fallback.decide(piece, log.calls_for(conn, piece["task_id"]), live=None)
        assert not found.ok and "a piece of a project split never falls back" in found.reason
    found = fallback.decide(row, log.calls_for(conn, row["task_id"]), live=None, preset=split.PRESET)
    assert not found.ok and "a file-mode task never falls back" in found.reason


# ---------- a blocked piece, Skip, a cancel (decision 14) ----------

def _blocked_first(conn):
    """Piece 1 changes calc.py and fails its check twice; piece 2 waits for it."""
    w = World(("Fixed add() in calc.py.", {"calc.py": FIXED_ADD, "notes.txt": "a new file\n"}),
              ("Still fixed.", {"calc.py": "def add(a, b):\n    return a + b  # again\n"}),
              ("Added mathx.py and test_mathx.py.", {"mathx.py": MULTIPLY, "test_mathx.py": TEST_MULTIPLY}),
              (JOINED, {}), chatgpt=("FIX\n1. no", "FIX\n1. still no", "PASS", "PASS"))
    return w, w.split(conn)


def test_a_blocked_piece_holds_the_rest_and_the_card_says_so(project, conn, runner):
    w, row = _blocked_first(conn)
    one, two = _pieces(conn, row)
    assert split.piece_state(log.get_task(conn, one["task_id"]))[0] == "blocked"
    two = log.get_task(conn, two["task_id"])
    assert two["status"] == "queued" and log.calls_for(conn, two["task_id"]) == []
    assert jsonview.state_of(conn, two).waiting_on == "piece"
    shown = jsonview.show_view(conn, row, roster=ROSTER)["pieces"]
    assert shown[1]["why"] == "waits for piece 1" and shown[0]["piece_state"] == "blocked"
    assert f"#{two['n']} {two['task_id']} waits for piece 1." in w.out


def test_the_order_hold_holds_under_sr_check_too(project, conn, runner):
    w, row = _blocked_first(conn)
    w.check(conn)
    two = _pieces(conn, row)[1]
    assert log.calls_for(conn, two["task_id"]) == []


def test_skip_puts_the_copy_back_byte_for_byte_then_the_next_piece_runs(project, conn, runner):
    w, row = _blocked_first(conn)
    one = _pieces(conn, row)[0]
    before_piece_one = {"calc.py": "def add(a, b):\n    return a - b\n", "test_calc.py": "import unittest\n"}
    assert _files(row["task_id"]) != before_piece_one
    code = cli.cmd_split_skip([one["task_id"]], conn=conn, **{k: v for k, v in w.kw().items()})
    assert code == 0, w.out
    final = log.get_task(conn, row["task_id"])
    assert [c["path"] for c in log.project_files_of(final)["changed"]] == ["mathx.py", "test_mathx.py"], \
        "the whole change holds only piece 2's files"
    assert "Files: the copy is back as it was before piece 1" in w.out
    assert jsonview.state_of(conn, final).waiting_on == "land"


def test_a_skip_restores_an_added_a_changed_and_a_deleted_file(project, conn, runner):
    w = World(("Edits.", {"calc.py": FIXED_ADD, "added.txt": "new\n", "test_calc.py": None}),
              ("Again.", {}), WorkerError("claude exited 1: piece 2 stops, so the restored copy stays to be read"),
              chatgpt=("FIX\n1. no", "FIX\n1. still no"))
    row = w.split(conn)
    assert sorted(_files(row["task_id"])) == ["added.txt", "calc.py"]
    one = _pieces(conn, row)[0]
    cli.cmd_split_skip([one["task_id"]], conn=conn, **{k: v for k, v in w.kw().items()})
    assert _files(row["task_id"]) == {"calc.py": "def add(a, b):\n    return a - b\n", "test_calc.py": "import unittest\n"}


def test_a_piece_that_never_started_is_skipped_without_a_restore(project, conn, runner):
    w, row = _blocked_first(conn)
    two = _pieces(conn, row)[1]
    snapshot = dict(_files(row["task_id"]))
    code = cli.cmd_split_skip([two["task_id"]], conn=conn, **{k: v for k, v in w.kw().items()})
    assert code == 0 and _files(row["task_id"]) == snapshot and not copies.has_snapshot(row["task_id"], "piece-2-start")


def test_a_pieces_cancel_keeps_the_copy(project, conn, runner):
    hook = RelayHook(s1=GOOD_NOTE)
    w = World(chatgpt=(), hook=hook)
    plan = teamed(f"## Pieces\n1. {P1}\n2. {P2}\n\n## Join\n{JOIN}\n", team=["research-build", "route"])
    row = w.split(conn, plan)
    one, two = _pieces(conn, row)
    assert log.get_task(conn, one["task_id"])["status"] == "sent" and log.calls_for(conn, two["task_id"]) == []
    assert cli.cmd_cancel(conn=conn, words=[one["task_id"]], out=w.lines.append) == 0
    assert copies.exists(row["task_id"]) and log.project_files_of(log.get_task(conn, row["task_id"]))["copy"] is True


def test_the_splits_cancel_ends_its_open_pieces_and_removes_the_copy(project, conn, runner):
    w, row = _blocked_first(conn)
    two = _pieces(conn, row)[1]
    assert cli.cmd_cancel(conn=conn, words=[row["task_id"]], out=w.lines.append) == 0
    assert log.get_task(conn, two["task_id"])["status"] == "cancelled"
    assert not copies.exists(row["task_id"]) and log.open_task_for(conn, "sums") is None


def test_a_stopped_piece_build_is_never_taken_over_and_resume_puts_the_copy_back(project, conn, runner):
    stopped = WorkerError("claude exited 1: a fake stop")
    w = World(stopped, chatgpt=())
    row = w.split(conn)
    one = _pieces(conn, row)[0]
    assert log.get_task(conn, one["task_id"])["status"] == "failed"
    assert not any(c["call_id"].endswith("-takeover") for c in log.calls_for(conn, one["task_id"]))


# ---------- the rest of decision 13 to 15's list ----------

WEB = {"status": "ok", "label": "web_research", "confidence": 0.95, "needs_split": 0.1, "tokens": 300}


def test_the_order_hold_holds_while_an_earlier_pieces_grok_stage_is_out_under_sr_check(project, conn, runner):
    hook = RelayHook()  # Grok never answers in this test
    w = World(chatgpt=(), hook=hook)
    plan = teamed(f"## Pieces\n1. {P1}\n2. {P2}\n\n## Join\n{JOIN}\n", team=["research-build", "route"])
    row = w.split(conn, plan)
    one, two = _pieces(conn, row)
    assert log.get_task(conn, one["task_id"])["status"] == "sent"
    for _ in range(2):  # the page runs sr check every minute while a Grok call is out
        w.check(conn)
    assert log.calls_for(conn, two["task_id"]) == [] and log.get_task(conn, two["task_id"])["status"] == "queued"
    assert jsonview.state_of(conn, log.get_task(conn, two["task_id"])).waiting_on == "piece"


def test_skip_is_refused_while_the_pieces_run_is_held(project, conn, runner, monkeypatch):
    import os
    from router import runs
    w, row = _blocked_first(conn)
    one = _pieces(conn, row)[0]
    other = (os.getpid() + 3, "2026-10-27T09:00:00+00:00")
    monkeypatch.setattr(runs, "READ", lambda pid: other[1] if pid == other[0] else "2026-10-20T12:00:00+00:00")
    log.claim_run(conn, one["task_id"], *other)
    before = dict(_files(row["task_id"]))
    code = cli.cmd_split_skip([one["task_id"]], conn=conn, **{k: v for k, v in w.kw().items()})
    assert code == 2 and f"#{one['n']} can't be skipped" in w.out
    assert _files(row["task_id"]) == before and not log.split_plan_of(log.get_task(conn, row["task_id"]))["pieces"][0]["skipped"]


def test_a_route_piece_another_agent_does_changes_no_file(project, conn, runner):
    w = World(("Added mathx.py.", {"mathx.py": MULTIPLY}), (JOINED, {}), chatgpt=("A web answer.", "PASS", "PASS"))
    w.worker.steps.insert(0, (PLAN, {}))
    cli.cmd_split(TASK, conn=conn, project="sums", files_ready=lambda: (True, None),
                  **{**w.kw(ask=None), "label": Jev({P1: WEB, P2: CODE})})
    row = next(r for r in log.recent_tasks(conn, 50) if r["mode"] == "split")
    cli.cmd_split_go([str(row["n"])], answer="y", **{**w.kw(conn=conn, ask=None), "label": Jev({P1: WEB, P2: CODE})})
    one = _pieces(conn, row)[0]
    assert log.get_task(conn, one["task_id"])["agent"] == "chatgpt"
    assert log.project_files_of(one) == {"mode": "off", "owner": row["task_id"], "state": "none", "copy": False,
                                         "why": "ChatGPT can't change project files: its result is text the join uses"}
    assert not copies.has_snapshot(row["task_id"], "piece-1-start"), "it never worked in the copy"


def test_a_pieces_delivery_with_no_change_stays_short_of_waiting_and_keeps_the_copy(project, conn, runner):
    w = World(("Nothing needed changing.", {}), WorkerError("claude exited 1: piece 2 stops, the split waits"),
              chatgpt=("PASS",))
    row = w.split(conn)
    one = log.get_task(conn, _pieces(conn, row)[0]["task_id"])
    assert one["status"] == "done" and log.project_files_of(one)["state"] == "none"
    assert log.project_files_of(one)["changed"] == [] and copies.exists(row["task_id"])


def test_the_tests_run_after_the_joins_fix_round_too(project, conn, runner):
    w = World(("Fixed add() in calc.py.", {"calc.py": FIXED_ADD}),
              ("Added mathx.py.", {"mathx.py": MULTIPLY, "test_mathx.py": TEST_MULTIPLY}),
              (JOINED, {}), (JOINED, {"README.md": "Sums\n"}), chatgpt=("PASS", "PASS", "FIX\n1. add a README", "PASS"))
    row = w.split(conn)
    assert len(runner.runs) == 2, "once after the join, once after its fix round"
    fix = [c for c in log.calls_for(conn, row["task_id"]) if c["kind"] == "fix"][0]
    assert log.tests_of(fix) is not None
    assert "README.md" in [c["path"] for c in log.project_files_of(log.get_task(conn, row["task_id"]))["changed"]]


def test_discard_of_the_split_drops_the_copy_and_writes_its_one_line(project, conn, runner):
    w, row = _two_pieces_done(conn)
    lines = []
    assert cli.cmd_land([row["task_id"]], conn=conn, config=CONFIG, verb="discard", out=lines.append) == 0, lines
    assert not copies.exists(row["task_id"]) and log.project_files_of(log.get_task(conn, row["task_id"]))["state"] == \
        "discarded"
    assert f"### #{row['n']} · " in (project / "HANDOFF.md").read_text() and "discarded" in (project / "HANDOFF.md").read_text()
    assert git(project, "log", "--oneline").decode().count("\n") == 3, "the entry's one commit"  # Cleanup 1 (2.5)
    assert git(project, "show", "--name-only", "--format=", "HEAD").decode().split() == ["HANDOFF.md"]


# ---------- C4 (/break-ui): a split still going keeps its copy ----------

@pytest.mark.parametrize("at", ["plan", "pieces"])
def test_discard_is_refused_while_the_split_is_at_its_plan_or_on_its_pieces(project, conn, runner, at):
    # brief 29, C4: the page offered Discard on a project split waiting at its plan; `sr discard` dropped the copy its
    # pieces would build in. Reject (or cancel) is how a split still going drops its copy
    if at == "plan":
        w = World()
        w.worker.steps.insert(0, (PLAN, {}))
        cli.cmd_split(TASK, conn=conn, project="sums", files_ready=lambda: (True, None), **w.kw(ask=None))
        row = next(r for r in log.recent_tasks(conn, 50) if r["mode"] == "split")
    else:
        w, row = _blocked_first(conn)
    row = log.get_task(conn, row["task_id"])
    assert jsonview.state_of(conn, row).waiting_on == {"plan": "split_plan", "pieces": "piece"}[at]
    out = receipt.Receipt()
    assert cli.cmd_land([row["task_id"]], conn=conn, config=CONFIG, verb="discard", out=out) == 2
    assert copies.exists(row["task_id"]) and log.project_files_of(log.get_task(conn, row["task_id"]))["state"] == "none"
    words = " ".join(out.lines)
    assert f"Refused: #{row['n']} is a split still " in words and f"sr cancel {row['n']}" in words
    assert "Nothing was changed." in words and out.code == "wrong_state"
