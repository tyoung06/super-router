"""Brief 29.1 (decision 22; Phase 0, call 7): every check, re-check and fix-round prompt, for every agent, is kept as a
round file beside its output, written before the send and redacted as round files are: `tasks/<task_id>/<NN>-<role>-
<agent>-prompt.md`, named by the call row's place, role and agent (no new column, no log version 18). `sr show` names it
after its output; the JSON gives each call `prompt_file`. Brief 30 (Phase 0's call 3): every call's prompt is kept, a
doer's and a stage's too, so the router notes each call was sent can be read where they went. Fakes only; every value
fake."""
import json
import os
import stat

import pytest

from router import __main__ as cli
from router import checking, log, rounds
from tests.test_json_actions import FAKE_ENV, World
from tests.test_loop import Scripted
from tests.test_relay import Chat


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    return World(monkeypatch, tmp_path, capsys)


def _row():
    conn = log.init_db(cli.DB_PATH)
    try:
        row = log.task_by_number(conn, 1)
        return row, log.calls_for(conn, row["task_id"])
    finally:
        conn.close()


def test_a_routed_tasks_check_fix_and_recheck_prompts_are_kept_beside_their_outputs(world):
    world.worker, world.chatgpt = Scripted("Draft one.", "Draft two."), Chat("FIX\n1. [must] Rhyme.", "PASS\n1. fixed")
    world.run("route", "write a poem")
    row, calls = _row()
    tid = row["task_id"]
    folder = cli.DB_PATH.parent / "tasks" / tid
    kept = sorted(p.name for p in folder.iterdir() if p.name.endswith("-prompt.md"))
    assert kept == ["01-do-claude-prompt.md", "02-check-chatgpt-prompt.md", "03-fix-claude-prompt.md",
                    "04-recheck-chatgpt-prompt.md"]  # brief 30: the doer's too
    check, fix, recheck = (folder / name for name in kept[1:])
    assert check.read_text() == world.chatgpt.prompts[0] and recheck.read_text() == world.chatgpt.prompts[1]
    assert fix.read_text() == world.worker.prompts[1]
    assert checking.REPLY_FORMAT in check.read_text() and checking.RECHECK_FORMAT in recheck.read_text()
    for path in (check, fix, recheck):
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert (folder / "01-do-claude-prompt.md").read_text() == world.worker.prompts[0]  # brief 30: every call's prompt


def test_sr_show_names_each_kept_prompt_and_the_json_gives_prompt_file(world):
    world.worker, world.chatgpt = Scripted("Draft one.", "Draft two."), Chat("FIX\n1. [must] Rhyme.", "PASS\n1. fixed")
    world.run("route", "write a poem")
    row, _ = _row()
    tid = row["task_id"]
    text = world.run("show", "1")[1]
    assert f"02 check by chatgpt: tasks/{tid}/02-check-chatgpt.md (prompt: tasks/{tid}/02-check-chatgpt-prompt.md)" in text
    assert f"01 do by claude: tasks/{tid}/01-do-claude.md (prompt: tasks/{tid}/01-do-claude-prompt.md)\n" in text + "\n"
    found = json.loads(world.run("show", "1", "--json")[1])
    files = [c["prompt_file"] for c in found["calls"]]
    assert files == [f"tasks/{tid}/01-do-claude-prompt.md", f"tasks/{tid}/02-check-chatgpt-prompt.md",
                     f"tasks/{tid}/03-fix-claude-prompt.md", f"tasks/{tid}/04-recheck-chatgpt-prompt.md"]  # brief 30
    check = found["calls"][1]
    assert (check["said"], check["verdict"]) == ("FIX", "FIX")
    assert check["items"] == [{"n": 1, "tag": "must", "text": "Rhyme.", "state": None}]
    assert found["calls"][3]["items"] == [{"n": 1, "tag": "must", "text": "", "state": "fixed"}]


def test_a_kept_prompt_is_redacted_as_round_files_are(world):
    secret = FAKE_ENV["JEV_API_KEY"]  # a fake .env value of 8 characters or more: the redactor's
    world.worker, world.chatgpt = Scripted(f"A draft with {secret} in it."), Chat("PASS")
    world.run("route", "write a poem")
    row, _ = _row()
    kept = cli.DB_PATH.parent / "tasks" / row["task_id"] / "02-check-chatgpt-prompt.md"
    assert secret not in kept.read_text() and "[REDACTED]" in kept.read_text()


def test_a_send_that_stopped_before_its_row_leaves_a_file_the_retry_replaces(tmp_path):
    db = tmp_path / "router.db"
    conn = log.init_db(db)
    try:
        log.add_task(conn, "sr-1", "t", "cli", {"status": "ok", "label": "writing", "confidence": 0.9, "tokens": 0})
        first = rounds.keep_prompt(conn, "sr-1", "sr-1-c1", "check", "chatgpt", "first try", [])
        again = rounds.keep_prompt(conn, "sr-1", "sr-1-c1", "check", "chatgpt", "second try", [])
        assert first == again == "tasks/sr-1/01-check-chatgpt-prompt.md"
        assert (tmp_path / again).read_text() == "second try"
        assert rounds.keep_prompt(conn, "sr-1", "sr-1", "do", "claude", "the doer", []) == "tasks/sr-1/01-do-claude-prompt.md"
        assert rounds.keep_prompt(log.init_db(":memory:"), "sr-1", "sr-1-c1", "check", "chatgpt", "x", []) is None
    finally:
        conn.close()
