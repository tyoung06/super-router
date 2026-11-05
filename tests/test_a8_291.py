"""Brief 29.1 A8 (decision 7's (e), (f) and (h): brief 29's live-check issues 2, 3 and 5, the owner's mid-run addition).
(e) A project split's join is told the pieces' changes are already in the copy, that its `## Handoff` names every file the
split changed (never "nothing written"), and that the router runs the tests after it. (f) A piece's cancel never says its
copy was removed: the split's copy is kept, and said so. (h) The join never redoes a skipped piece: on a project split its
words say the skipped piece's work stays undone, in the files and in the text, and its checker is told which piece was
skipped, so it doesn't count that part as missing; a split without a project is byte for byte as before. Real git in temp
folders, fake agents; every value fake."""
from router import __main__ as cli
from router import checking, filecalls, log, split
from tests.helpers import teamed
from tests.test_relay import GOOD_NOTE, RelayHook
from tests.test_split_project import JOIN, P1, P2, conn, project, registry  # noqa: F401 (fixtures)
from tests.test_split_project_flow import World, _blocked_first, _pieces, runner  # noqa: F401


def test_e_the_joins_build_paragraph_says_what_is_in_the_copy_and_what_its_handoff_names(project, conn, runner):
    w, row = _blocked_first(conn)
    text = filecalls.build_paragraph(log.get_task(conn, row["task_id"]))
    assert "with every piece's change already in it" in text
    assert "In `### Produced`, name every file the split changed, the pieces' and yours, never `nothing written`" in text
    assert "After your reply the router runs the project's tests (`python3 -m unittest`), and the checker sees" in text


def test_f_a_pieces_cancel_says_the_splits_copy_is_kept(project, conn, runner):
    w = World(chatgpt=(), hook=RelayHook(s1=GOOD_NOTE))
    row = w.split(conn, teamed(f"## Pieces\n1. {P1}\n2. {P2}\n\n## Join\n{JOIN}\n", team=["research-build", "route"]))
    one = _pieces(conn, row)[0]
    lines = []
    assert cli.cmd_cancel(conn=conn, words=[one["task_id"]], out=lines.append) == 0
    said = "\n".join(lines)
    assert "Its copy of the project is removed" not in said
    assert "The split's copy of the project is kept: its other pieces and its join build there." in said


def test_f_the_splits_own_cancel_still_says_its_copy_is_removed(project, conn, runner):
    w, row = _blocked_first(conn)
    lines = []
    assert cli.cmd_cancel(conn=conn, words=[row["task_id"]], out=lines.append) == 0
    assert "Its copy of the project is removed; the folder is as it was." in "\n".join(lines)


def test_h_the_join_and_its_checker_are_told_a_skipped_piece_stays_undone(project, conn, runner):
    w, row = _blocked_first(conn)
    one = _pieces(conn, row)[0]
    cli.cmd_split_skip([one["task_id"]], conn=conn, **{k: v for k, v in w.kw().items()})
    join = next(c for c in w.worker.calls if c["prompt"].startswith(log.get_task(conn, row["task_id"])["task"])
                and split.INTEGRATE_INSTRUCTIONS in c["prompt"])["prompt"]
    line = split.SKIPPED_JOIN_LINE.format(which="Piece 1 was")
    assert line in join and join.index(split.INTEGRATE_INSTRUCTIONS) < join.index(line) < join.index("===== PIECES =====")
    check = w.chat.prompts[-1]
    named = split.SKIPPED_CHECK_LINE.format(which=f'piece 1 ("{P1}")')
    assert named in check and check.index(named) < check.index("===== TASK =====")


def test_h_a_split_without_a_project_keeps_its_words():
    plan = {"inputs": [{"text": "a", "result": "A."}, {"text": "b", "result": None}], "join": "Both.",
            "pieces": [{"planner_text": "a", "edited_text": None, "skipped": False},
                       {"planner_text": "b", "edited_text": None, "skipped": True}]}
    prompt = split.integrate_prompt("The task.", plan)
    assert "skipped by the person: its work stays undone" not in prompt
    assert split.skipped_check_line(plan) == ('The person skipped piece 2 ("b"), so that part of the task is left undone on '
                                              "purpose: don't count it as missing, and fail the result if it does that part "
                                              "anyway. Judge the rest.")
    with_project = split.integrate_prompt("The task.", plan, project=True)
    assert split.SKIPPED_JOIN_LINE.format(which="Piece 2 was") in with_project
    two = {**plan, "pieces": [{**p, "skipped": True} for p in plan["pieces"]]}
    assert split.skipped_join_line(two).startswith("Piece 1 and piece 2 were skipped by the person")
    assert checking.checker_prompt("t", "r", no_tools=False, skipped=None) == checking.checker_prompt("t", "r", no_tools=False)
