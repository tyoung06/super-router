"""Build brief 19, phase E, decision 16 (rules v2.27, Project context "What comes back" and Checking): on a nothing-written
result, `### Produced` names the inline deliverable by its exact heading or first line and one clause on what it
holds, on the same line, after `nothing written:`. A bare `nothing written` is a contract miss (re-asked once); the
build line asks for the shape; the checker judges what it names. Fake agents only; every value here is fake."""
import pytest

from router import __main__ as cli
from router import checking, context, log
from tests.test_context import TASK, _route, project  # noqa: F401  (the project fixture)
from tests.test_loop import Scripted
from tests.test_relay import Chat

BARE = "\n\n## Handoff\n### Produced\nnothing written\n### Status\nok\n### Next\nmore"
NO_HEADING = "\n\n## Handoff\n### Produced\nnothing written. The section is in this reply only.\n### Status\nok\n### Next\nmore"
NAMED = "\n\n## Handoff\n### Produced\nnothing written: ## Presets, the five presets one line each\n### Status\nok\n### Next\nmore"
REASK = ("Handoff: `### Produced`: on a nothing-written result, name the inline deliverable by its exact heading or first "
         "line and one clause on what it holds, on the same line")


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


@pytest.mark.parametrize("produced, missing", [
    ("nothing written", [REASK]),
    ("Nothing Written.", [REASK]),
    ("nothing written!", [REASK]),
    ("nothing written. The section is in this reply only.", [REASK]),
    ("nothing written:", [REASK]),
    ("nothing written: ## Presets, the five presets one line each", []),
    ("Nothing written: the first line `A preset is a fixed chain`, one table of five", []),
    ("media/out/x/a.png", []),
    ("sr show 5", []),
    ("the section is in this reply", []),
])
def test_a_bare_nothing_written_is_a_contract_miss_and_a_named_one_is_not(produced, missing):
    text = f"## Presets\n\nbody\n\n## Handoff\n### Produced\n{produced}\n### Status\nok\n### Next\nmore"
    assert context.handoff_missing(text) == missing


def test_the_other_contract_items_still_come_first():
    text = "body\n\n## Handoff\n### Produced\nnothing written\n### Status\n### Next\nmore"
    assert context.handoff_missing(text) == ["Handoff: `### Status` needs at least 1 line, found 0", REASK]


def test_the_build_line_and_the_checker_line_carry_the_new_sentences():
    assert context.HANDOFF_LINE.endswith(
        "If nothing was written to disk, write `nothing written:` followed by the exact heading or first line of what "
        "the result contains and one clause on what it holds.")
    assert ("On a `nothing written` result, the heading or first line it names must be in the result and its clause must "
            "be true of it; a `Produced` that names nothing the result contains, or describes it wrongly, is a failure."
            in checking.CHECK_HANDOFF_LINE)
    prompt = checking.checker_prompt("t", "r", no_tools=True, handoff=True)
    assert "On a `nothing written` result" in prompt and prompt.index("On a `nothing written`") < prompt.index("===== TASK =====")


def test_a_bare_nothing_written_is_re_asked_once_and_the_named_one_reaches_the_entry(project, conn):
    worker, chat = Scripted("## Presets\n\nfive presets" + BARE, "## Presets\n\nfive presets" + NAMED), Chat("PASS")
    code, out, row, _ = _route(conn, project="demo", worker=worker, chatgpt=chat)
    assert code == 0, out
    assert f"The first call by claude missed its contract; re-asked once for: {REASK}." in out
    reask = worker.prompts[1]
    assert REASK in reask and context.HANDOFF_LINE in reask
    calls = log.calls_for(conn, row["task_id"])
    assert [c["kind"] for c in calls][:2] == ["do", "do"] and calls[1]["call_id"].endswith(context.DO_REASK)
    entry = log.handoff_of(log.get_task(conn, row["task_id"]))[0]["text"]
    assert "Produced:\nnothing written: ## Presets, the five presets one line each\n" in entry
    assert (project / "HANDOFF.md").read_text().count("nothing written: ## Presets, the five presets one line each") == 1
    assert "On a `nothing written` result" in chat.prompts[0]  # the checker's project line carries the new sentence


def test_a_bare_nothing_written_after_the_re_ask_still_stops_the_task(project, conn):
    worker = Scripted("body" + BARE, "body" + NO_HEADING)
    code, out, row, _ = _route(conn, project="demo", worker=worker, chatgpt=Chat("PASS"))
    assert code == 1 and row["status"] == "failed", out
    assert "contract still missing after the re-ask" in row["result"] and REASK in row["result"]
