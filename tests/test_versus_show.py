"""Build brief 9, phase E: what the owner sees. The candidates block after `sr relay versus` and in
`sr show`, the pick line once picked, `--stages` with all four stages, `sr log` and the status page
saying `awaiting pick`, and (gate 7) the doer line of a resumed task whose substitute stopped too.
Fake agents only; every secret here is fake."""
import pytest

from router import __main__ as cli
from router import jsonview, log, page
from tests.test_pick import _pick
from tests.test_relay import SECRET
from tests.test_resume_run import WRITING, Chat, Scripted, _resume, _route, claude_limit, codex_limit
from tests.test_versus_run import A_TEXT, B_TEXT, LOADED, REVIEW_OF_A, REVIEW_OF_B, _versus


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _block(n, head):
    return [
        f"Task {n} · versus · {head}",
        "",
        "A — claude · reviewed by chatgpt: PASS",
        A_TEXT,
        "notes (chatgpt):",
        "- Wrong: nothing.\n- Strong: clear (review of A by chatgpt).",
        "",
        "B — chatgpt · reviewed by claude: FAIL",
        B_TEXT,
        "notes (claude):",
        "- Wrong: it invents a spec (review of B by claude).\n- Strong: short.",
        "",
    ]


def _show(conn, *words, stages=False):
    lines = []
    code = cli.cmd_show(conn=conn, words=list(words), secrets=[SECRET], stages=stages, presets=LOADED, out=lines.append)
    return code, lines


# ---------- sr relay versus ----------

def test_sr_relay_ends_with_both_candidates_their_reviews_and_the_pick_line(conn):
    code, out, row, *_ = _versus(conn)
    n = row["n"]
    assert out.split("\n", 1)[1] == "\n".join(_block(n, "awaiting your pick") + [f"Pick: sr pick {n} a | b | none"])


def test_the_stage_results_stay_hidden_apart_from_the_candidates_and_notes(conn):
    code, out, *_ = _versus(conn)
    assert "## Verdict" not in out and "## Notes" not in out


def test_a_secret_in_a_candidate_is_never_printed(conn):
    code, out, *_ = _versus(conn, claude=(f"{A_TEXT} {SECRET}", REVIEW_OF_B))
    assert SECRET not in out


# ---------- sr show ----------

def test_sr_show_on_an_awaiting_task_prints_the_block_and_the_pick_line(conn):
    code, out, row, *_ = _versus(conn)
    n = row["n"]
    code, lines = _show(conn, str(n))
    assert code == 0
    assert lines[0].startswith(f"#{n}  {row['task_id']}  awaiting pick  created ")
    assert "Relay: versus" in lines and "Jev: not asked (relay task)" in lines
    assert "  1. build by claude: passed" in lines and "  4. review by claude: passed" in lines
    at = lines.index(f"Task {n} · versus · awaiting your pick")
    assert lines[at - 1] == ""  # The owner: a blank line between the task text and the block
    assert "\n".join(lines[at:]) == "\n".join(_block(n, "awaiting your pick") + [f"Pick: sr pick {n} a | b | none"])
    assert "Result:" not in lines


def test_sr_show_after_pick_a_prints_the_block_and_the_pick(conn):
    code, out, row, *_ = _versus(conn)
    n = row["n"]
    _pick(conn, str(n), "a")
    code, lines = _show(conn, str(n))
    at = lines.index(f"Task {n} · versus · picked A")
    assert "\n".join(lines[at:]) == "\n".join(
        _block(n, "picked A") + ["Picked: A (claude), reviewed by chatgpt: PASS. It is the task's result."])
    assert lines[0].startswith(f"#{n}  {row['task_id']}  done  ")


def test_sr_show_after_a_pick_of_a_failed_candidate_says_so(conn):
    code, out, row, *_ = _versus(conn)
    _pick(conn, str(row["n"]), "b")
    code, lines = _show(conn, str(row["n"]))
    assert lines[-1] == "Picked: B (chatgpt), reviewed by claude: FAIL (picked anyway). It is the task's result."


def test_sr_show_after_pick_none(conn):
    code, out, row, *_ = _versus(conn)
    _pick(conn, str(row["n"]), "none")
    code, lines = _show(conn, str(row["n"]))
    assert lines[-1] == "Picked: none. The task failed (no pick); both candidates are kept."
    assert f"Task {row['n']} · versus · picked none" in lines


def test_sr_show_stages_prints_all_four_stage_results(conn):
    code, out, row, *_ = _versus(conn)
    code, lines = _show(conn, str(row["n"]), stages=True)
    text = "\n".join(lines)
    for piece in (A_TEXT, B_TEXT, REVIEW_OF_A, REVIEW_OF_B):
        assert piece in text
    for head in ("stage 1 build by claude: done", "stage 2 build by chatgpt: done",
                 "stage 3 review by chatgpt: done", "stage 4 review by claude: done"):
        assert head in lines


def test_a_failed_versus_chain_shows_as_any_failed_chain(conn):
    code, out, row, *_ = _versus(conn, chatgpt=(B_TEXT, "no verdict", "still none"))
    code, lines = _show(conn, str(row["n"]))
    text = "\n".join(lines)
    assert "RELAY FAILED at stage 3 (review by chatgpt)" in text and A_TEXT in text and B_TEXT in text
    assert "Pick:" not in text


# ---------- sr log ----------

def test_sr_log_says_relay_versus_and_awaiting_pick_until_picked(conn):
    code, out, row, *_ = _versus(conn)
    lines = []
    cli.cmd_log(conn=conn, out=lines.append)
    assert "relay:versus" in lines[1] and "awaiting pick" in lines[1]
    _pick(conn, str(row["n"]), "a")
    lines = []
    cli.cmd_log(conn=conn, out=lines.append)
    assert "relay:versus" in lines[1] and "awaiting pick" not in lines[1] and " done " in lines[1]


def test_sr_log_columns_stay_aligned_with_the_wider_status(conn):
    _versus(conn)
    lines = []
    cli.cmd_log(conn=conn, out=lines.append)
    assert lines[0].index("status") == lines[1].index("awaiting pick")
    assert lines[1][lines[0].index("agent")] == "-"  # the agent column starts where its header does


# ---------- the status page ----------

def test_the_page_marks_an_awaiting_task(conn):
    """Brief 21, B4: the page reads `waiting_on` (pick) and then the outcome (picked) from `sr log --json`."""
    code, out, row, *_ = _versus(conn)
    view = jsonview.task_view(conn, log.get_task(conn, row["task_id"]), loaded=LOADED)
    assert (view["waiting_on"], view["status"]) == ("pick", "returned")
    _pick(conn, str(row["n"]), "a")
    view = jsonview.task_view(conn, log.get_task(conn, row["task_id"]), loaded=LOADED)
    assert (view["waiting_on"], view["outcome"]) == (None, "picked")



# ---------- gate 7: the doer line after both builders stopped ----------

def test_the_doer_line_names_both_stops_after_a_failed_resume(conn):
    code, out, row = _route(conn, WRITING, worker=Scripted(claude_limit()))
    _resume(conn, row, chatgpt=Chat(codex_limit()))
    lines = []
    cli.cmd_show(conn=conn, words=["1"], secrets=[SECRET], out=lines.append)
    doer = next(line for line in lines if line.startswith("Doer:"))
    assert doer.startswith("Doer: chatgpt (resume of claude; both stopped)")


def test_the_doer_line_is_unchanged_after_a_resume_that_worked(conn):
    code, out, row = _route(conn, WRITING, worker=Scripted(claude_limit()))
    _resume(conn, row, worker=Scripted("PASS"), chatgpt=Chat("two lines by chatgpt"))
    lines = []
    cli.cmd_show(conn=conn, words=["1"], secrets=[SECRET], out=lines.append)
    doer = next(line for line in lines if line.startswith("Doer:"))
    assert "both stopped" not in doer and doer.startswith("Doer: chatgpt (")


# ---------- the owner (after the live chain): `## Missing` is apart from the deliverable ----------

from router import relay  # noqa: E402

BLURB = "Dial in your spacing. This adjustable tray works on any heat mat."
MISSING = "- The task gives no specs, so none are claimed.\n- No height range was given."
A_WITH_MISSING = f"{BLURB}\n\n## Missing\n{MISSING}\n"


def test_split_missing_takes_the_missing_section_off_the_deliverable():
    assert relay.split_missing(A_WITH_MISSING) == (BLURB, MISSING)


def test_without_a_missing_section_the_deliverable_is_the_whole_text_byte_for_byte():
    text = "  A blurb with odd spacing.\n\n\tAnd a tab ✓  \n"
    assert relay.split_missing(text) == (text, None)


def test_a_missing_heading_inside_a_code_fence_is_part_of_the_deliverable():
    text = "Here is the format:\n```\n## Missing\n- example\n```\nDone."
    assert relay.split_missing(text) == (text, None)


def test_an_empty_missing_section_is_no_missing_section():
    assert relay.split_missing(f"{BLURB}\n\n## Missing\n\n") == (BLURB, None)


def test_the_block_shows_the_deliverable_then_what_is_missing_then_the_notes(conn):
    code, out, row, *_ = _versus(conn, claude=(A_WITH_MISSING, REVIEW_OF_B))
    body = out.split("\n", 1)[1]
    a_part = body.split("\nB — ", 1)[0]
    assert a_part == "\n".join([
        f"Task {row['n']} · versus · awaiting your pick", "",
        "A — claude · reviewed by chatgpt: PASS",
        BLURB,
        "missing (claude):",
        MISSING,
        "notes (chatgpt):",
        "- Wrong: nothing.\n- Strong: clear (review of A by chatgpt).",
        ""])
    assert "## Missing" not in body


def test_a_pick_makes_the_deliverable_alone_the_result(conn):
    code, out, row, *_ = _versus(conn, claude=(A_WITH_MISSING, REVIEW_OF_B))
    _pick(conn, str(row["n"]), "a")
    after = log.get_task(conn, row["task_id"])
    assert after["result"] == BLURB
    assert "Missing" not in after["result"]
    stored = log.calls_for(conn, row["task_id"])[0]["text"]
    assert stored == A_WITH_MISSING  # the stage row keeps the whole answer; --stages prints it


def test_the_reviewer_still_sees_the_missing_section(conn):
    code, out, row, worker, chat = _versus(conn, claude=(A_WITH_MISSING, REVIEW_OF_B))
    assert MISSING in chat.prompts[1]  # it judges on the evidence, gaps stated openly included


def test_the_deliverable_is_what_a_word_count_sees():
    deliverable, missing = relay.split_missing(A_WITH_MISSING)
    assert len(deliverable.split()) == 12 and len(missing.split()) == 16
