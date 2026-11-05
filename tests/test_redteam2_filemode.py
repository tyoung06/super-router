"""Build brief 32, R (decision 13): on a project in file mode Cursor's attack gets the change as a diff and the test results
as text (as every attack does, filecalls.with_blocks), with the handoff; it never runs in the copy. Claude builds and
revises in the copy, and the check gets both lists. Fakes and a real git folder in tmp; every value here is fake."""
from router import __main__ as cli
from router import context, cursor_worker, filecalls, log, presets, relay
from tests.helpers import shipped_roster
from tests.test_context import TASK
from tests.test_cursor_send import Cursor, Ready, answer
from tests.test_filemode_flow import FIXED_CALC, CopyWorker, conn, project, runner  # noqa: F401  (fixtures)
from tests.test_loop import Clock
from tests.test_memory_block import ATTACKS, BUILT, SECTION
from tests.test_redteam2_chain import B_LIST
from tests.test_relay import CONFIG, Chat, RelayHook

ROSTER = shipped_roster()
LOADED = presets.load_presets(ROSTER, tuple(cli.SENDERS), relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
REVISED = "Line one, fixed.\nLine two.\n\n## Answered\nA2, B3: the task asked for dull lines" + SECTION


def test_in_file_mode_cursor_attacks_the_change_and_the_tests_as_text_and_never_runs_in_the_copy(project, conn, runner):
    worker = CopyWorker((BUILT + SECTION, {"calc.py": FIXED_CALC}), (REVISED, {"test_calc.py": "import unittest\n"}))
    chat, cursor = Chat(ATTACKS, "PASS"), Cursor(answer(B_LIST))
    lines, clock, hook = [], Clock(), RelayHook()
    code = cli.cmd_relay("redteam", TASK, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                         settings_paths=[], post=hook.post, worker=worker, chatgpt=chat, codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True, out=lines.append,
                         project="garden", files_ready=lambda: (True, None), cursor=cursor, cursor_ready=Ready())
    assert code == 0, "\n".join(lines)
    sent = cursor.prompts[0]
    assert sent.startswith(cursor_worker.opener()) and context.start_marker("garden") in sent
    assert "===== change: 1 file =====\nchanged calc.py (+1 -1)" in sent and sent.rstrip().endswith(filecalls.JUDGE_LINE)
    attack_a = chat.prompts[0]
    assert "===== change: 1 file =====" in attack_a
    assert [c["copy"].write for c in worker.calls] == [True, True]  # the build and the revise, in the copy
    task = log.get_task(conn, log.recent_tasks(conn)[0]["task_id"])
    assert not filecalls.in_copy(task, "stage", "attack", "cursor")
    check = chat.prompts[1]
    assert "ATTACK LIST A · ChatGPT (written by an attacker" in check and "ATTACK LIST B · Cursor (written by" in check
    assert log.project_files_of(task)["state"] == "waiting"
