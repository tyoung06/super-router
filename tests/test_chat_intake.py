"""Build brief 19, phase B (rules v2.27, Memory, "The tag"): `--chat <name>` is a tag, not a refusal. Accepted by
`sr route` and `sr relay` and with an override; refused with `--project` (one tag per task) and on `sr split`; the
first task with a new name prints `new chat: <name>`; a resume and a fallback carry the tag from the row; Jev never
sees it; `sr log --chat` filters. Fake agents only; every value here is fake."""
import json

import pytest

from router import __main__ as cli
from router import log, settings
from tests.helpers import fake_label
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_collab import LOADED
from tests.test_relay import CONFIG, GOOD_NOTE, ROSTER, Chat, RelayHook
from tests.test_resume_run import WRITING, claude_limit

TASK = "Write two lines about seed trays."


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _route(conn, task=TASK, *, chat=None, project=None, jev=WRITING, worker=None, chatgpt=None, wait=True,
           hindsight=None):
    lines, clock, hook = [], Clock(), Webhook()
    label = fake_label(jev)
    code = cli.cmd_route(task, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=label,
                         post=hook.post, worker=worker or Scripted(), chatgpt=chatgpt or Chat("PASS"),
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=wait, out=lines.append, project=project, chat=chat, hindsight=hindsight)
    rows = log.recent_tasks(conn)
    return code, "\n".join(lines), rows[0] if rows else None, label


def _relay(conn, preset, task=TASK, *, chat=None, worker=None, chatgpt=None, hook=None, wait=False, hindsight=None,
           slots=()):
    lines, clock, hook = [], Clock(), hook or RelayHook(s1=GOOD_NOTE)
    code = cli.cmd_relay(preset, task, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                         settings_paths=[], post=hook.post, worker=worker or Scripted(), chatgpt=chatgpt or Chat("PASS"),
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=wait, slots=list(slots), out=lines.append, chat=chat, hindsight=hindsight)
    rows = log.recent_tasks(conn)
    return code, "\n".join(lines), rows[0] if rows else None, hook


# ---------- accepted ----------

def test_route_with_chat_tags_the_row_and_says_new_chat_once(conn):
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("two lines"))
    assert code == 0, out
    assert log.chat_of(row) == "tray" and log.tag_of(row) == "chat:tray" and log.project_of(row) is None
    assert out.splitlines()[0] == "new chat: tray"
    code, out, row2, _ = _route(conn, chat="tray", worker=Scripted("two more"))
    assert code == 0 and log.chat_of(row2) == "tray" and "new chat" not in out
    code, out, row3, _ = _route(conn, chat="garden", worker=Scripted("other"))
    assert out.splitlines()[0] == "new chat: garden"


@pytest.mark.parametrize("preset", ["research-build", "collab", "versus", "redteam", "vote"])
def test_relay_with_chat_is_accepted_on_every_preset(conn, preset):
    code, out, row, hook = _relay(conn, preset, chat="tray")
    assert row is not None and log.chat_of(row) == "tray" and row["mode"] == "relay" and row["preset"] == preset, out
    assert out.splitlines()[0] == "new chat: tray"
    assert "Refused" not in out


def test_chat_with_an_override_is_accepted(conn):
    code, out, row, _ = _route(conn, "@claude " + TASK, chat="tray", worker=Scripted("two lines"))
    assert code == 0, out
    assert log.chat_of(row) == "tray" and row["agent"] == "claude" and row["route_reason"] == "override"


def test_jev_gets_the_same_text_with_and_without_a_chat(conn):
    _, _, _, with_chat = _route(conn, chat="alpha", worker=Scripted("x"))
    _, _, _, without = _route(conn, worker=Scripted("x"))
    assert with_chat.calls[0]["task"] == without.calls[0]["task"] == TASK
    assert "chat" not in json.dumps(with_chat.calls).lower() and "alpha" not in json.dumps(with_chat.calls)


# ---------- refused ----------

def test_a_chat_name_must_be_plain(conn):
    code, out, row, label = _route(conn, chat="My Chat")
    assert code == 2 and row is None and label.calls == []
    assert out == "Refused: a chat name is lower case letters, digits and - (not 'My Chat'). Nothing was logged or sent."
    code, out, row, hook = _relay(conn, "research-build", chat="Tray!")
    assert code == 2 and row is None and hook.sent == []
    assert out == "Refused: a chat name is lower case letters, digits and - (not 'Tray!'). Nothing was logged or sent."


@pytest.mark.parametrize("argv", [["route", "--project", "demo", "--chat", "x", "hi"],
                                  ["relay", "redteam", "--project", "demo", "--chat", "x", "hi"],
                                  ["relay", "redteam", "--chat=x", "--project=demo", "hi"]])
def test_chat_with_project_is_refused_before_anything(argv, capsys):
    assert cli.main(argv, platform="darwin") == 2
    assert capsys.readouterr().out == "Refused: one tag per task: --chat with --project. Nothing was logged or sent.\n"
    assert not cli.DB_PATH.exists()


def test_chat_is_refused_on_sr_split(capsys):
    assert cli.main(["split", "--chat", "x", "plan this"], platform="darwin") == 2
    assert capsys.readouterr().out == ("Refused: --chat on sr split is refused in version 2; pieces carry no tag. "
                                       "Nothing was logged or sent.\n")
    assert not cli.DB_PATH.exists()


@pytest.mark.parametrize("argv", [["resume", "--chat", "x", "5"], ["fallback", "--chat=x", "5"], ["check", "--chat", "x"],
                                  ["show", "--chat", "x"], ["pick", "--chat", "x", "5", "a"]])
def test_chat_on_other_commands_is_not_an_option(argv, capsys):
    with pytest.raises(SystemExit) as stop:
        cli.main(argv, platform="darwin")
    assert stop.value.code == 2
    assert "unrecognized arguments: --chat" in capsys.readouterr().err
    assert not cli.DB_PATH.exists()


def test_relay_keeps_chat_out_of_the_slot_flags():
    rest, found = cli._take_slot_flags(["relay", "redteam", "--chat", "tray", "--build", "chatgpt", "task"])
    assert rest == ["relay", "redteam", "--chat", "tray", "task"] and found == [("build", "chatgpt")]
    rest, found = cli._take_slot_flags(["relay", "redteam", "--chat=tray", "task"])
    assert rest == ["relay", "redteam", "--chat=tray", "task"] and found == []


def test_the_old_chat_refusal_is_gone():
    assert not hasattr(cli, "CHAT_REFUSAL")


# ---------- carried by a resume and a fallback ----------

def test_a_resume_carries_the_tag(conn):
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted(claude_limit()))
    assert row["status"] == "failed" and log.chat_of(row) == "tray"
    lines, clock, hook, chat = [], Clock(), Webhook(), Chat("two lines")
    code = cli.cmd_resume([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                          settings_paths=[], post=hook.post, worker=Scripted("PASS"), chatgpt=chat,
                          codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                          wait=True, out=lines.append)
    assert code == 0, "\n".join(lines)
    after = log.get_task(conn, row["task_id"])
    assert after["status"] == "done" and log.tag_of(after) == "chat:tray"


def test_a_fallback_carries_the_tag(conn):
    worker, chat = Scripted("FIRST two lines", "FIXED two lines"), Chat("FIX\n1. rhyme", "FIX\n1. still no rhyme")
    code, out, row, _ = _route(conn, chat="tray", worker=worker, chatgpt=chat)
    assert row["check_state"] == "failed" and log.chat_of(row) == "tray"
    lines, clock, hook, redo = [], Clock(), Webhook(), Chat("REDO two lines")
    code = cli.cmd_fallback([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                            settings_paths=[], post=hook.post, worker=Scripted("PASS"), chatgpt=redo,
                            codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep,
                            clock=clock, wait=True, out=lines.append)
    assert code == 0, "\n".join(lines)
    after = log.get_task(conn, row["task_id"])
    assert after["check_state"] == "passed" and log.tag_of(after) == "chat:tray"


# ---------- what the log shows (the tag beside the task; `sr log --chat`) ----------

def test_sr_log_shows_the_chat_beside_the_skill_and_filters_by_chat(conn):
    _route(conn, chat="alpha", worker=Scripted("one"))
    _route(conn, chat="beta", worker=Scripted("two"))
    _route(conn, worker=Scripted("three"))
    rows = log.recent_tasks(conn)
    assert cli._skill_text(rows[2]).endswith(" chat:alpha") and cli._skill_text(rows[0]) == "writing"
    lines = []
    assert cli.cmd_log(conn=conn, chat="alpha", out=lines.append) == 0
    body = [line for line in lines[1:]]
    assert len(body) == 1 and "chat:alpha" in body[0] and "beta" not in "\n".join(lines)
    lines = []
    assert cli.cmd_log(conn=conn, chat="none", out=lines.append) == 0
    assert lines == ["No tasks in chat none yet."]
    lines = []
    assert cli.cmd_log(conn=conn, out=lines.append) == 0 and len(lines) == 4


# ---------- the settings file (decision 9) ----------

def test_the_five_memory_keys_are_in_the_shipped_settings_file():
    assert settings.memory_setting("memory_url") == ("http://127.0.0.1:8888", "config/settings.json")
    assert settings.memory_setting("memory_bank") == ("super-router", "config/settings.json")
    assert settings.memory_setting("memory_max_items") == (5, "config/settings.json")
    assert settings.memory_setting("memory_max_chars") == (2000, "config/settings.json")
    assert settings.memory_setting("memory_query_chars") == (1500, "config/settings.json")
    assert settings.grok_prompt_limit() == (3662, "config/settings.json")
