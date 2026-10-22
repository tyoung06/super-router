"""Build brief 20, phase B (rules v2.28, Cursor): the send path. `_send_cursor` goes through `_send_local` with its
own worker and parser: the readiness check once per command (the sandbox pass on the installed agent, the login),
not configured and not ready each a failed row with the reason and no call, the served record on the done and the
failed row, the text through the redactor, the raw stream kept under media/cursor/, `sr show` naming the served
model and the tool count, the wiring in route, relay, check and main. A versus task with `--b cursor` runs stages 2
and 3 on Cursor with the opener before Claude's prompt for the role, byte for byte. Fake agents only; every value
here is fake."""
import functools
import json
import stat

import pytest

from router import __main__ as cli
from router import cursor_worker, log, media, presets, relay
from tests.fake_hindsight import FakeHindsight
from tests.helpers import roster_with, shipped_roster
from tests.test_loop import Clock, Scripted
from tests.test_relay import CONFIG, SECRET, Chat, RelayHook

ROSTER = roster_with(cursor=True)
LOADED = presets.load_presets(ROSTER, tuple(cli.SENDERS), relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
TASK = "Write a Python function that parses durations. Code only, no prose."
A_TEXT = "CANDIDATE-A from claude: def parse_duration(s): ..."
B_TEXT = "CANDIDATE-B from cursor: def parse_duration(s): return 0"
REVIEW_OF_A = "## Verdict\npass\n\n## Notes\n- Wrong: nothing.\n- Strong: clear (review of A by cursor)."
REVIEW_OF_B = "## Verdict\nfail\n\n## Notes\n- Wrong: it returns 0 (review of B by claude).\n- Strong: short."
SERVED = {"model": "Grok 4.7 256K High", "asked": "grok-4.7-high", "tool_events": 0, "tools": [], "duration_ms": 21888,
          "permission_mode": "default", "usage": {"inputTokens": 14183, "outputTokens": 78, "cacheReadTokens": 6272,
                                                  "cacheWriteTokens": 0}}
STREAM = '{"type":"system","subtype":"init","model":"Grok 4.7 256K High"}\n{"type":"result","result":"%s"}\n'
READY = (True, None)


def answer(text, served=None, stream=None):
    found = cursor_worker.CursorAnswer(text, served or SERVED)
    found.stream = STREAM % text if stream is None else stream
    return found


class Cursor:
    """A fake Cursor worker: records prompts and call ids; returns the scripted CursorAnswer or raises."""

    def __init__(self, *replies):
        self.replies, self.prompts, self.call_ids = list(replies), [], []

    def __call__(self, prompt, *, call_id="call"):
        self.prompts.append(prompt)
        self.call_ids.append(call_id)
        reply = self.replies.pop(0) if self.replies else answer("a cursor answer")
        if isinstance(reply, BaseException) or isinstance(reply, type):
            raise reply
        return reply


class Ready:
    def __init__(self, value=READY):
        self.value, self.calls = value, 0

    def __call__(self):
        self.calls += 1
        return self.value


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


@pytest.fixture(autouse=True)
def media_root(tmp_path, monkeypatch):
    root = tmp_path / "media"
    monkeypatch.setattr(media, "MEDIA_ROOT", root)
    return root


def _versus(conn, *, slots=(("b", "cursor"),), claude=(A_TEXT, REVIEW_OF_B), cursor=None, ready=None, wait=True, chat=None,
            hindsight=None, hook=None, chatgpt=None):
    lines, clock, hook = [], Clock(), hook or RelayHook()
    worker, cursor, ready = Scripted(*claude), cursor or Cursor(answer(B_TEXT), answer(REVIEW_OF_A)), ready or Ready()
    code = cli.cmd_relay("versus", TASK, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                         settings_paths=[], post=hook.post, worker=worker, chatgpt=chatgpt or Chat(), codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=wait, slots=list(slots),
                         cursor=cursor, cursor_ready=ready, chat=chat, hindsight=hindsight, out=lines.append)
    row = log.recent_tasks(conn)[0]
    return code, "\n".join(lines), row, worker, cursor, ready, hook


def _calls(conn, row):
    return [(c["kind"], c["stage"], c["role"], c["agent"], c["status"]) for c in log.calls_for(conn, row["task_id"])]


def _show(conn, row, **flags):
    lines = []
    cli.cmd_show(conn=conn, words=[str(row["n"])], secrets=[SECRET], roster=ROSTER, presets=LOADED, out=lines.append, **flags)
    return "\n".join(lines)


# ---------- the chain with Cursor in slot b ----------

def test_versus_with_b_cursor_runs_stages_2_and_3_on_cursor_and_keeps_the_served_record(conn):
    code, out, row, worker, cursor, ready, _ = _versus(conn)
    assert code == 0, out
    assert _calls(conn, row) == [("stage", 1, "build", "claude", "done"), ("stage", 2, "build", "cursor", "done"),
                                 ("stage", 3, "review", "cursor", "done"), ("stage", 4, "review", "claude", "done")]
    calls = {c["call_id"]: c for c in log.calls_for(conn, row["task_id"])}
    tid = row["task_id"]
    assert log.served_of(calls[f"{tid}-s2"]) == {**SERVED, "stream": f"media/cursor/{tid}/{tid}-s2.ndjson"}
    assert log.served_of(calls[f"{tid}-s3"])["stream"] == f"media/cursor/{tid}/{tid}-s3.ndjson"
    assert log.served_of(calls[f"{tid}-s1"]) is None and log.served_of(calls[f"{tid}-s4"]) is None
    assert relay.awaiting_pick(row) and json.loads(row["slots"]) == {"a": "claude", "b": "cursor"}
    assert "B — cursor · reviewed by claude: FAIL" in out and B_TEXT in out
    assert cursor.call_ids == [f"{tid}-s2", f"{tid}-s3"]


def test_the_cursor_prompts_are_the_opener_then_claudes_prompt_for_the_role_byte_for_byte(conn):
    code, out, row, worker, cursor, *_ = _versus(conn)
    # Decision 8: never a search line (the router asks Cursor for no search), the task alone on the build, the one
    # candidate on the review; Claude's own prompts are untouched (the probe gate is shut here, so no search line).
    assert cursor.prompts[0] == cursor_worker.wrap(relay.task_build_prompt(TASK))
    assert cursor.prompts[1] == cursor_worker.wrap(relay.review_prompt(TASK, A_TEXT))
    assert worker.prompts[0] == relay.task_build_prompt(TASK) and worker.prompts[1] == relay.review_prompt(TASK, B_TEXT)
    assert A_TEXT not in cursor.prompts[0] and B_TEXT not in cursor.prompts[1] and "web search" not in cursor.prompts[0]
    assert cursor.prompts[0].startswith(cursor_worker.opener() + "\n\n" + TASK)


def test_the_readiness_check_runs_once_per_command_before_the_first_cursor_call(conn):
    code, out, row, worker, cursor, ready, _ = _versus(conn)
    assert ready.calls == 1 and len(cursor.prompts) == 2


REASONS = ["cursor: no sandbox probe pass on record; run sr probe",
           "cursor: agent moved to 2026.11.01-abcd since the sandbox probe; run sr probe",
           "cursor: not signed in (agent login)"]


@pytest.mark.parametrize("reason", REASONS)
def test_not_ready_is_refused_at_intake_before_any_row_so_claudes_stage_is_not_spent(conn, reason):
    # The owner's change of 20 Oct, after live #102 (the agent self-updated between two tasks and Claude's build was spent).
    lines, clock, hook = [], Clock(), RelayHook()
    worker, cursor = Scripted(A_TEXT, REVIEW_OF_B), Cursor()
    code = cli.cmd_relay("versus", TASK, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[],
                         post=hook.post, worker=worker, chatgpt=Chat(), codex_login=lambda: True, fetch=hook.fetch,
                         close=hook.close, sleep=clock.sleep, clock=clock, wait=True, slots=[("b", "cursor")], cursor=cursor,
                         cursor_ready=Ready((False, reason)), out=lines.append)
    assert code == 2 and log.recent_tasks(conn) == [] and worker.prompts == [] and cursor.prompts == []
    assert "\n".join(lines) == f"Refused: {reason}. Nothing was logged or sent."


@pytest.mark.parametrize("reason", REASONS)
def test_at_stage_time_not_ready_fails_the_stage_before_any_call_with_the_reason(conn, reason):
    # The stage-time check stays: `sr check` continues a chain with no intake (here after Grok's stage 1).
    hook = RelayHook(s1="CANDIDATE-A from grok")
    code, out, row, worker, cursor, ready, hook = _versus(conn, slots=(("a", "grok"), ("b", "cursor")), wait=False, hook=hook)
    assert code == 0 and ready.calls == 1
    lines = []
    cli.cmd_check(conn=conn, config=CONFIG, environ={}, settings_paths=[], post=hook.post, worker=worker, chatgpt=Chat(),
                  codex_login=lambda: True, fetch=hook.fetch, close=hook.close, presets=LOADED, roster=ROSTER, cursor=cursor,
                  cursor_ready=Ready((False, reason)), out=lines.append)
    assert cursor.prompts == []
    assert _calls(conn, row) == [("stage", 1, "build", "grok", "done"), ("stage", 2, "build", "cursor", "failed")]
    failed = log.calls_for(conn, row["task_id"])[-1]
    assert failed["text"] == reason and failed["reason_code"] is None and log.served_of(failed) is None
    assert f"RELAY FAILED at stage 2 (build by cursor): {reason}" in "\n".join(lines)
    row = log.get_task(conn, row["task_id"])
    assert row["status"] == "failed" and row["failed_stage"] == 2


def test_cursor_not_configured_is_refused_at_intake_and_fails_the_stage_on_sr_check(conn):
    lines, clock, hook = [], Clock(), RelayHook()
    code = cli.cmd_relay("versus", TASK, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[],
                         post=hook.post, worker=Scripted(A_TEXT), chatgpt=Chat(), codex_login=lambda: True, fetch=hook.fetch,
                         close=hook.close, sleep=clock.sleep, clock=clock, wait=True, slots=[("b", "cursor")], out=lines.append)
    assert code == 2 and log.recent_tasks(conn) == []
    assert lines == ["Refused: Cursor isn't configured (no model in config/agents.json, or the config didn't load). "
                     "Nothing was logged or sent."]
    hook = RelayHook(s1="CANDIDATE-A from grok")
    code, out, row, worker, cursor, ready, hook = _versus(conn, slots=(("a", "grok"), ("b", "cursor")), wait=False, hook=hook)
    lines = []
    cli.cmd_check(conn=conn, config=CONFIG, environ={}, settings_paths=[], post=hook.post, worker=worker, chatgpt=Chat(),
                  codex_login=lambda: True, fetch=hook.fetch, close=hook.close, presets=LOADED, roster=ROSTER, out=lines.append)
    assert _calls(conn, row)[-1] == ("stage", 2, "build", "cursor", "failed")
    assert log.calls_for(conn, row["task_id"])[-1]["text"] == ("Cursor isn't configured (no model in config/agents.json, "
                                                                "or the config didn't load)")


def test_a_served_mismatch_fails_the_stage_and_the_row_keeps_both_names(conn):
    served = {**SERVED, "model": "Composer 2.5"}
    error = cursor_worker.WorkerError("served model 'Composer 2.5' is not the one asked for (grok-4.7-high); the text was not used",
                                      served=served)
    error.stream = STREAM % "a third-party answer"
    code, out, row, worker, cursor, *_ = _versus(conn, cursor=Cursor(error))
    failed = log.calls_for(conn, row["task_id"])[-1]
    assert (failed["agent"], failed["status"], failed["stage"]) == ("cursor", "failed", 2)
    assert failed["text"].startswith("served model 'Composer 2.5' is not the one asked for (grok-4.7-high)")
    tid = row["task_id"]
    assert log.served_of(failed) == {**served, "stream": f"media/cursor/{tid}/{tid}-s2.ndjson"}
    assert "RELAY FAILED at stage 2 (build by cursor): served model 'Composer 2.5'" in out
    assert "a third-party answer" not in out and "a third-party answer" not in (failed["text"] or "")


def test_a_timed_out_cursor_call_is_stored_as_todays_timeouts_are(conn):
    code, out, row, *_ = _versus(conn, cursor=Cursor(cursor_worker.WorkerError("cursor timed out after 600 s")))
    failed = log.calls_for(conn, row["task_id"])[-1]
    assert failed["status"] == "failed" and failed["text"] == "cursor timed out after 600 s" and failed["reason_code"] is None
    assert log.served_of(failed) is None and "RELAY FAILED at stage 2 (build by cursor): cursor timed out after 600 s" in out


def test_a_tool_that_ran_fails_the_stage_with_its_count_on_the_row(conn):
    served = {**SERVED, "tool_events": 2, "tools": ["shellToolCall:started", "shellToolCall:completed:success"]}
    code, out, row, *_ = _versus(conn, cursor=Cursor(cursor_worker.WorkerError("a tool ran: shellToolCall", served=served)))
    failed = log.calls_for(conn, row["task_id"])[-1]
    assert failed["text"] == "a tool ran: shellToolCall" and log.served_of(failed)["tool_events"] == 2


# ---------- the redactor and the raw stream (decision 4, choice 3) ----------

def test_the_text_goes_through_the_redactor_and_a_fake_key_in_the_result_never_reaches_the_row_or_the_output(conn, media_root):
    leaky = answer(f"CANDIDATE-B leaks {SECRET} here", stream=STREAM % f"CANDIDATE-B leaks {SECRET} here")
    code, out, row, *_ = _versus(conn, cursor=Cursor(leaky, answer(REVIEW_OF_A)))
    tid = row["task_id"]
    s2 = log.get_call(conn, f"{tid}-s2")
    assert SECRET not in s2["text"] and "[REDACTED]" in s2["text"]
    assert SECRET not in out and "[REDACTED]" in out
    kept = (media_root / "cursor" / tid / f"{tid}-s2.ndjson").read_text()
    assert SECRET not in kept and "[REDACTED]" in kept


def test_the_raw_stream_is_kept_under_media_cursor_owner_only_and_named_on_the_record(conn, media_root):
    code, out, row, *_ = _versus(conn)
    tid = row["task_id"]
    for n, text in ((2, B_TEXT), (3, REVIEW_OF_A)):
        path = media_root / "cursor" / tid / f"{tid}-s{n}.ndjson"
        assert path.read_text() == STREAM % text
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert log.served_of(log.get_call(conn, f"{tid}-s{n}"))["stream"] == f"media/cursor/{tid}/{tid}-s{n}.ndjson"


def test_a_failed_calls_stream_is_kept_too_and_a_call_without_one_names_none(conn, media_root):
    error = cursor_worker.WorkerError("agent reported an error: rate limited", served={**SERVED, "duration_ms": 5})
    error.stream = '{"type":"system","subtype":"init","model":"Grok 4.7 256K High"}\n{"type":"result","is_error":true,"result":"rate limited"}\n'
    code, out, row, *_ = _versus(conn, cursor=Cursor(error))
    tid = row["task_id"]
    assert (media_root / "cursor" / tid / f"{tid}-s2.ndjson").read_text() == error.stream
    assert log.served_of(log.get_call(conn, f"{tid}-s2"))["stream"] == f"media/cursor/{tid}/{tid}-s2.ndjson"
    gone = cursor_worker.WorkerError("could not start agent (FileNotFoundError)")
    code, out, row, *_ = _versus(conn, cursor=Cursor(gone))
    assert log.served_of(log.get_call(conn, f"{row['task_id']}-s2")) is None
    assert not (media_root / "cursor" / row["task_id"]).exists()


# ---------- the memory block rides as on any agent (decision 8) ----------

def test_a_chat_tasks_cursor_call_carries_the_memory_block_as_claudes_does(conn):
    log.add_task(conn, "sr-old", "an earlier tray task", "cli", {"status": "ok", "label": "writing", "confidence": 0.9, "tokens": 0},
                 chat="tray")
    log.set_route(conn, "sr-old", agents=ROSTER.names, agent="claude", route_reason="best", skill="writing", checker="chatgpt",
                  check_state="pending")
    log.add_call(conn, "sr-old", "sr-old", "do", "claude", status="done", text="the earlier result")
    log.set_done(conn, "sr-old", "the earlier result", check_state="passed")
    fake = FakeHindsight(results=[])
    code, out, row, worker, cursor, *_ = _versus(conn, chat="tray", hindsight=fake.client)
    assert code == 0, out
    tid = row["task_id"]
    s1, s2 = log.get_call(conn, f"{tid}-s1"), log.get_call(conn, f"{tid}-s2")
    assert log.call_memory_of(s1)["sent"] == 1 and log.call_memory_of(s2)["sent"] == 1
    assert log.call_memory_of(s2)["text"] == log.call_memory_of(s1)["text"]
    block = log.call_memory_of(s2)["text"]
    assert cursor.prompts[0].endswith(block) and worker.prompts[0].endswith(block)
    assert cursor.prompts[0] == cursor_worker.wrap(worker.prompts[0])


# ---------- sr show (decision 10) ----------

def test_sr_show_names_the_served_model_and_the_tool_count_on_the_cursor_lines(conn):
    code, out, row, *_ = _versus(conn)
    shown = _show(conn, row)
    assert "  2. build by cursor: passed; served Grok 4.7 256K High, 0 tool events" in shown
    assert "  3. review by cursor: passed; served Grok 4.7 256K High, 0 tool events" in shown
    assert "  1. build by claude: passed\n" in shown and "served" not in shown.split("1. build by claude: passed")[0]
    staged = _show(conn, row, stages=True)
    assert "stage 2 build by cursor: done; served Grok 4.7 256K High, 0 tool events" in staged
    assert "stage 1 build by claude: done\n" in staged
    history = _show(conn, row, history=True)
    assert "2. stage 2 build by cursor: done, served Grok 4.7 256K High, 0 tool events, " in history


def test_sr_show_on_a_failed_cursor_stage_says_which_model_answered(conn):
    served = {**SERVED, "model": "Composer 2.5", "tool_events": 1, "tools": ["globToolCall:completed:success (3 files)"]}
    error = cursor_worker.WorkerError("served model 'Composer 2.5' is not the one asked for (grok-4.7-high); the text was not used",
                                      served=served)
    code, out, row, *_ = _versus(conn, cursor=Cursor(error))
    shown = _show(conn, row)
    assert "  2. build by cursor: failed; served Composer 2.5, 1 tool event" in shown
    assert "RELAY FAILED at stage 2 (build by cursor): served model 'Composer 2.5' is not the one asked for" in shown


# ---------- sr check continues a chain with a Cursor stage ----------

def test_sr_check_runs_the_cursor_stage_after_grok_returns(conn):
    # --a grok --b cursor: stage 1 goes to Grok and waits; `sr check` collects it and runs stage 2 on Cursor.
    hook = RelayHook(s1="CANDIDATE-A from grok", s4="## Verdict\npass\n\n## Notes\n- fine")
    code, out, row, worker, cursor, ready, hook = _versus(conn, slots=(("a", "grok"), ("b", "cursor")), wait=False, hook=hook)
    assert code == 0 and cursor.prompts == [] and _calls(conn, row) == [("stage", 1, "build", "grok", "sent")]
    lines = []
    code = cli.cmd_check(conn=conn, config=CONFIG, environ={}, settings_paths=[], post=hook.post, worker=worker, chatgpt=Chat(),
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, presets=LOADED, roster=ROSTER,
                         cursor=cursor, cursor_ready=ready, out=lines.append)
    assert _calls(conn, row)[:3] == [("stage", 1, "build", "grok", "done"), ("stage", 2, "build", "cursor", "done"),
                                     ("stage", 3, "review", "cursor", "done")]
    assert cursor.prompts[0] == cursor_worker.wrap(relay.task_build_prompt(TASK))
    assert cursor.prompts[1] == cursor_worker.wrap(relay.review_prompt(TASK, "CANDIDATE-A from grok"))


# ---------- the wiring in main ----------

@pytest.mark.parametrize("command, name", [(["route", "hi"], "cmd_route"), (["relay", "versus", "hi"], "cmd_relay"),
                                           (["check"], "cmd_check")])
def test_main_hands_route_relay_and_check_the_cursor_worker_and_the_readiness_check(monkeypatch, command, name):
    seen = {}
    monkeypatch.setattr(cli.safety, "prepare_workspace", lambda *a, **k: None)
    monkeypatch.setattr(cli, name, lambda *a, **kw: seen.update(kw) or 0)
    assert cli.main(command, platform="darwin") == 0
    cursor = seen["cursor"]
    assert isinstance(cursor, functools.partial) and cursor.func is cursor_worker.run
    assert cursor.keywords == {"model": "grok-4.7-high"}
    ready = seen["cursor_ready"]  # brief 22 (decision 7): the readiness that runs the canaries when they are missing
    assert isinstance(ready, functools.partial) and ready.func is cli.probes.cursor_ready and ready.args == (cli.PROBE_STATE,)


def test_the_senders_name_cursor_and_the_shipped_roster_still_loads():
    assert cli.SENDERS["cursor"] is cli._send_cursor and list(cli.SENDERS) == ["claude", "grok", "chatgpt", "cursor"]
    assert shipped_roster().live == ("claude", "grok", "chatgpt", "cursor")  # cursor since the owner's flip, 2026-10-20
    assert cli._workers({}, "gpt-6.1-sol", "grok-4.7-high")[2].keywords == {"model": "grok-4.7-high"}
    assert cli._workers({}, "gpt-6.1-sol", None)[2] is None
