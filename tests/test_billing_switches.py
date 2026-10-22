"""Problem H: OPENAI_API_KEY and CODEX_API_KEY are billing switches too. Set anywhere the router
looks (the shell or .env), they stop route and sr check before anything is logged or sent, by
name and never by value, and the message names the agent they would bill. Every value is fake."""
from pathlib import Path

import pytest

from router import __main__ as cli
from router import claude_worker, log, safety
from tests.helpers import fake_label, shipped_roster

CONFIG = {"GROK_WEBHOOK_URL": "https://example.invalid/hook", "GROK_WEBHOOK_KEY": "FAKE-KEY-123"}
ROSTER = shipped_roster()
OPENAI = ("OPENAI_API_KEY", "CODEX_API_KEY")
ANTHROPIC = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")


class Recorder:
    def __init__(self, value=None):
        self.value, self.calls = value, []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.value


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def test_the_billing_switches_are_the_seven_names():
    # Brief 20 (rules v2.28, Money): CURSOR_API_KEY joins the six; it would bill Cursor per token instead of the pool.
    assert set(safety.BILLING_SWITCHES) == set(ANTHROPIC) | set(OPENAI) | {"CURSOR_API_KEY"}
    assert safety.BILLED_AGENT == {**{name: "claude" for name in ANTHROPIC}, **{name: "chatgpt" for name in OPENAI},
                                   "CURSOR_API_KEY": "cursor"}


def test_cursor_api_key_is_flagged_by_name_and_names_cursor():
    problems = safety.billing_problems({"CURSOR_API_KEY": "fake"})
    assert problems == ["CURSOR_API_KEY is set. It would make cursor bill per token. Unset it and run again."]
    assert safety.check_env({**CONFIG, "CURSOR_API_KEY": "fake"}) == problems


@pytest.mark.parametrize("name", OPENAI)
def test_an_openai_key_is_flagged_by_name_and_names_chatgpt(name):
    problems = safety.billing_problems({name: "sk-FAKE-OPENAI-VALUE"})
    assert len(problems) == 1
    assert name in problems[0] and "chatgpt" in problems[0] and "claude" not in problems[0]
    assert "FAKE-OPENAI-VALUE" not in problems[0]


@pytest.mark.parametrize("name", ANTHROPIC)
def test_an_anthropic_switch_still_names_claude(name):
    problems = safety.billing_problems({name: "FAKE"})
    assert len(problems) == 1 and name in problems[0] and "claude" in problems[0] and "chatgpt" not in problems[0]


@pytest.mark.parametrize("name", OPENAI)
def test_check_env_catches_an_openai_key_in_dotenv(name):
    problems = safety.check_env({**CONFIG, name: "sk-FAKE"})
    assert len(problems) == 1 and name in problems[0] and "sk-FAKE" not in problems[0]


@pytest.mark.parametrize("name", OPENAI)
@pytest.mark.parametrize("where", ["shell", "dotenv"])
def test_route_refuses_an_openai_key_before_anything_is_logged(conn, name, where):
    environ = {name: "sk-FAKE"} if where == "shell" else {}
    config = {**CONFIG, name: "sk-FAKE"} if where == "dotenv" else CONFIG
    label, worker, post = fake_label(), Recorder("x"), Recorder()
    lines = []
    code = cli.cmd_route("@claude hi", conn=conn, config=config, roster=ROSTER, environ=environ, settings_paths=[],
                         label=label, post=post, worker=worker, out=lines.append)
    out = "\n".join(lines)
    assert code == 2 and name in out and "sk-FAKE" not in out and "chatgpt" in out
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    assert label.calls == [] and worker.calls == [] and post.calls == []


@pytest.mark.parametrize("name", OPENAI)
def test_sr_check_refuses_an_openai_key_and_sends_nothing(conn, name):
    fetch, worker, post = Recorder([]), Recorder("x"), Recorder()
    lines = []
    code = cli.cmd_check(conn=conn, config=CONFIG, environ={name: "sk-FAKE"}, settings_paths=[], post=post,
                         worker=worker, fetch=fetch, close=Recorder(), out=lines.append)
    assert code == 2 and name in "\n".join(lines) and "sk-FAKE" not in "\n".join(lines)
    assert fetch.calls == [] and worker.calls == [] and post.calls == []


@pytest.mark.parametrize("name", OPENAI)
def test_the_claude_worker_refuses_on_an_openai_key_too(fake_run, name):
    run = fake_run(stdout="never")
    with pytest.raises(claude_worker.WorkerError) as err:
        claude_worker.run("hi", run=run, environ={"HOME": "/h", "PATH": "/bin", name: "sk-FAKE"})
    assert name in str(err.value) and "sk-FAKE" not in str(err.value) and run.calls == []


def test_env_example_says_no_openai_key_belongs_there():
    text = (Path(__file__).resolve().parent.parent / ".env.example").read_text()
    assert "OPENAI_API_KEY" in text and "CODEX_API_KEY" in text
    comment = next(line for line in text.splitlines() if "OPENAI_API_KEY" in line)
    assert comment.startswith("#"), "the names appear only in a comment, never as a setting"
    assert "never" in comment.lower() or "no " in comment.lower()
