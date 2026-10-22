"""route asks Jev once per task and logs the answer before anything else. Every key here is fake."""
import functools
import os
import signal

import pytest

from router import __main__ as cli
from router import jev, log
from tests.helpers import JEV_OK, add_row, fake_label, shipped_roster

JEV_KEY = "FAKE-JEV-KEY-12345"
CONFIG = {"GROK_WEBHOOK_URL": "https://example.invalid/hook", "GROK_WEBHOOK_KEY": "FAKE-KEY-123",
          "JEV_API_KEY": JEV_KEY}
ROSTER = shipped_roster()
LOW = {"status": "below_floor", "label": "web_research", "confidence": 0.62, "needs_split": 0.4, "tokens": 812}


class Recorder:
    def __init__(self, value=None, raises=None):
        self.value, self.raises, self.calls = value, raises, []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.raises:
            raise self.raises
        return self.value


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _route(conn, task, *, label=None, worker=None, environ=None):
    lines = []
    try:
        code = cli.cmd_route(
            task, conn=conn, config=CONFIG, roster=ROSTER, environ=environ or {}, settings_paths=[],
            label=label or fake_label(), post=Recorder(),
            worker=worker or Recorder("an answer"), out=lines.append,
        )
    except KeyboardInterrupt:
        pytest.fail("KeyboardInterrupt escaped cmd_route")
    return code, "\n".join(lines)


def _only_row(conn):
    rows = log.recent_tasks(conn)
    assert len(rows) == 1
    return rows[0]


def test_route_logs_jevs_answer(conn):
    code, _ = _route(conn, "look up the population of Lisbon", label=fake_label(LOW))
    row = _only_row(conn)
    assert (row["jev_status"], row["jev_label"], row["jev_confidence"]) == ("below_floor", "web_research", 0.62)
    assert (row["jev_needs_split"], row["jev_tokens"], row["jev_error"]) == (0.4, 812, None)


def test_jev_sees_the_task_without_the_override_tag(conn):
    label = fake_label()
    _route(conn, "@claude   Fix the bug in my script", label=label)
    (call,) = label.calls
    assert call["task"] == "Fix the bug in my script"
    assert call["task_id"] == _only_row(conn)["task_id"]


@pytest.mark.parametrize("task, environ", [
    ("@grok hi", {"ANTHROPIC_API_KEY": "FAKE"}),  # a billing switch
    ("   ", {}),                                   # empty
    ("/logout", {}),                               # a slash command
    ("@muse write a poem", {}),                    # an agent that isn't live
])
def test_jev_is_not_called_for_a_refused_task(conn, task, environ):
    label = fake_label()
    code, _ = _route(conn, task, label=label, environ=environ)
    assert code == 2 and label.calls == [] and log.recent_tasks(conn) == []


def test_the_labeler_is_told_this_months_tokens(conn):
    add_row(conn, "sr-1", jev={**JEV_OK, "tokens": 300})
    add_row(conn, "sr-2", jev={**JEV_OK, "tokens": 200})
    label = fake_label()
    _route(conn, "@claude hi", label=label)
    assert label.calls[0]["tokens_this_month"] == 500


def test_ctrl_c_during_the_jev_call_still_leaves_a_row_with_its_tokens(conn):
    original = signal.getsignal(signal.SIGINT)
    seen = []

    def label(task_text, *, task_id, tokens_this_month):
        signal.raise_signal(signal.SIGINT)  # The owner presses Ctrl+C while Jev answers
        seen.append(task_id)
        return dict(LOW)

    worker = Recorder("an answer")
    code, out = _route(conn, "look up the population of Lisbon", label=label, worker=worker)
    row = _only_row(conn)
    assert code == 130
    assert (row["status"], row["jev_tokens"], row["jev_label"]) == ("cancelled", 812, "web_research")
    assert worker.calls == [] and seen == [row["task_id"]]
    assert "cancelled" in out
    assert signal.getsignal(signal.SIGINT) is original


def test_ctrl_c_while_the_jev_row_is_written_is_held(conn, monkeypatch):
    real_add = log.add_task

    def add_task(*args, **kwargs):
        signal.raise_signal(signal.SIGINT)
        return real_add(*args, **kwargs)

    monkeypatch.setattr(log, "add_task", add_task)
    code, _ = _route(conn, "look this up", label=fake_label(LOW))
    row = _only_row(conn)
    assert code == 130 and (row["status"], row["jev_tokens"]) == ("cancelled", 812)


def test_a_fake_jev_key_inside_a_result_is_stored_and_printed_redacted(conn):
    code, out = _route(conn, "@claude hi", worker=Recorder(f"the key is {JEV_KEY} ok"))
    assert code == 0
    assert _only_row(conn)["result"] == "the key is [REDACTED] ok"
    assert JEV_KEY not in out and "[REDACTED]" in out


def test_main_reads_the_jev_key_from_dotenv_and_never_puts_it_in_the_environment(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f'GROK_WEBHOOK_URL="https://example.invalid/hook"\nGROK_WEBHOOK_KEY="FAKE"\n'
                        f'JEV_API_KEY="{JEV_KEY}"\n')
    monkeypatch.setattr(cli, "ENV_PATH", env_file)
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.setattr(cli.safety, "prepare_workspace", lambda *a, **k: None)
    seen = {}
    monkeypatch.setattr(cli, "cmd_route", lambda task, **kw: seen.update(kw) or 0)
    assert cli.main(["route", "hi"], platform="darwin") == 0
    label = seen["label"]
    assert isinstance(label, functools.partial) and label.func is jev.label
    assert label.keywords["api_key"] == JEV_KEY and label.keywords["roster"].live == ("claude", "grok", "chatgpt", "cursor")
    assert "JEV_API_KEY" not in os.environ
    assert JEV_KEY in cli._secrets(seen["config"])
