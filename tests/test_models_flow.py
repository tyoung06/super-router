"""Build brief 33.3 (rules 2.48, Models; decisions 1, 4, 6, 7 and 10): the model choice through the router. `--model` and
`--effort` at intake (refused before Jev, before any probe and before any row); the choice kept on the task and used by
every call that agent makes, a resume and a fallback's redo included, never by a takeover's substitute; the records on
every call row; the credits stop; the probes on the agent default. Fake agents and a fake Jev only; every value here is
fake and nothing calls a model."""
import json

import pytest

from router import __main__ as cli
from router import chatgpt_worker, claude_worker, log, models, receipt
from tests.helpers import fake_label, set_local
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_relay import CONFIG, Chat, RelayHook, GOOD_NOTE
from tests.test_resume_run import LOADED, _resume, claude_limit
from tests.test_fallback_run import _fallback
from tests.test_routing_availability import ROSTER, Gate, jev
from tests.test_filemode_flow import conn as file_conn, project, runner  # noqa: F401 (fixtures; brief 33.3 D1)

HAIKU, OPUS, SONNET, FABLE = "claude-haiku-5-5", "claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


class Recorder(Scripted):
    """A fake agent that keeps every keyword the router handed it (the choice among them)."""

    def __init__(self, *replies):
        super().__init__(*replies)
        self.kwargs = []

    def __call__(self, prompt, **kwargs):
        self.kwargs.append(kwargs)
        return super().__call__(prompt, **kwargs)


def _route(conn, task="write a poem", *, label="writing", worker=None, chat=None, gate=None, model_flags=(), effort_flags=(),
           hook=None, skill=None, answers=None):
    lines, clock, hook = [], Clock(), hook or Webhook()
    worker, chat = worker or Recorder(), chat or Chat("PASS")
    out = receipt.Receipt()
    code = cli.cmd_route(task, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=fake_label(jev(label)), post=hook.post, worker=worker, chatgpt=chat,
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=True, available=gate, model_flags=list(model_flags), effort_flags=list(effort_flags),
                         skill=skill, answers=answers, out=out)
    rows = log.recent_tasks(conn)
    return code, out, rows[0] if rows else None, worker, chat


def _relay(conn, preset, task="build it", *, worker=None, chat=None, model_flags=(), effort_flags=(), slots=(), hook=None):
    lines, clock, hook = [], Clock(), hook or RelayHook(s1=GOOD_NOTE)
    worker, chat = worker or Recorder(), chat or Chat("PASS")
    out = receipt.Receipt()
    code = cli.cmd_relay(preset, task, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                         settings_paths=[], post=hook.post, worker=worker, chatgpt=chat, codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True, slots=list(slots),
                         model_flags=list(model_flags), effort_flags=list(effort_flags), out=out)
    rows = log.recent_tasks(conn)
    return code, out, rows[0] if rows else None, worker, chat


def _choices(worker):
    return [(k.get("choice").agent, k.get("choice").model, k.get("choice").effort, k.get("choice").timeout) for k in worker.kwargs]


# ---------- intake (decision 4): checked before Jev, before any probe and before any row ----------

@pytest.mark.parametrize("flags, code, words", [
    (["claude=gpt-6.1-sol"], "bad_model", "isn't on claude's allowed list"),
    (["grok=fable"], "bad_model", "Grok Bot has no model choice"),
    (["claude=fable"], "bad_model", "Fable is off"),
    (["claude=opus", "claude=sonnet"], "usage", "twice"),
    (["claude"], "usage", "<agent>=<name>"),
])
def test_route_refuses_a_bad_model_before_jev_with_no_row(conn, flags, code, words):
    label = fake_label(jev("writing"))
    out = receipt.Receipt()
    exit_code = cli.cmd_route("write a poem", conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                              label=label, post=Webhook().post, worker=Recorder(), chatgpt=Chat("PASS"),
                              codex_login=lambda: True, model_flags=flags, out=out)
    assert (exit_code, out.code) == (2, code) and words in out.message and "Nothing was logged or sent" in out.message
    assert label.calls == [] and log.recent_tasks(conn) == []


def test_route_refuses_a_bad_effort_and_an_effort_for_an_agent_without_levels(conn):
    for flags, words in ((["claude=ultra"], "effort levels"), (["grok=high"], "no model choice")):
        code, out, row, *_ = _route(conn, effort_flags=flags)
        assert (code, out.code) == (2, "bad_model") and words in out.message and row is None


def test_a_probe_never_runs_before_a_refused_model(conn, monkeypatch):
    ran = []
    monkeypatch.setattr(cli, "_claude_gate", lambda config, out: (lambda *a: ran.append("probe") or True))
    code, out, row, *_ = _route(conn, model_flags=["claude=nope"])
    assert code == 2 and out.code == "bad_model" and ran == [] and row is None


def test_relay_takes_only_an_agent_the_presets_slots_hold(conn):
    code, out, row, *_ = _relay(conn, "research-build", model_flags=["cursor=grok-4.7-high"])
    assert (code, out.code) == (2, "bad_model") and "makes no call on research-build" in out.message and row is None
    code, out, row, worker, chat = _relay(conn, "research-build", model_flags=["claude=haiku", "chatgpt=gpt-6-astra"])
    assert code == 0 and log.models_of(row) == {"claude": {"model": HAIKU, "effort": None}, "chatgpt": {"model": "gpt-6-astra", "effort": None}}


def test_split_takes_claude_and_chatgpt_only(conn):
    out = receipt.Receipt()
    code = cli.cmd_split("write two things", conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=fake_label(jev("writing")), ask=None, post=Webhook().post, worker=Recorder(), chatgpt=Chat(),
                         codex_login=lambda: True, loaded=LOADED, model_flags=["cursor=grok-4.7-high"], out=out)
    assert (code, out.code) == (2, "bad_model") and "a piece uses its team's defaults" in out.message
    assert log.recent_tasks(conn) == []


def test_the_floor_rows_choices_come_from_it_and_a_new_flag_with_answers_is_refused(conn):
    code, out, row, *_ = _route(conn, label="below", model_flags=["claude=haiku"], worker=Recorder())
    assert row["status"] == "returned" and log.models_of(row) == {"claude": {"model": HAIKU, "effort": None}}
    code, out, again, worker, _ = _route(conn, skill="writing", answers=str(row["n"]), model_flags=["claude=opus"])
    assert (code, out.code) == (2, "flag_refused") and "goes again as it was" in out.message
    code, out, again, worker, _ = _route(conn, skill="writing", answers=str(row["n"]))
    assert code == 0 and log.models_of(again) == {"claude": {"model": HAIKU, "effort": None}}
    assert _choices(worker)[0] == ("claude", HAIKU, None, 600)


# ---------- the choice on every call (decisions 1 and 7) ----------

def test_a_routed_tasks_choice_reaches_every_call_of_that_agent_and_the_rows_keep_it(conn):
    code, out, row, worker, chat = _route(conn, model_flags=["claude=haiku", "chatgpt=gpt-6-astra"], effort_flags=["claude=low"],
                                          chat=Chat("FIX\n1. [must] Name a source.", "PASS\n1. fixed"))
    assert code == 0 and row["status"] == "done"
    assert _choices(worker) == [("claude", HAIKU, "low", 600)] * 2  # the do call and the fix round
    assert all(c.model == "gpt-6-astra" and c.layer == "task" for c in chat.choices)  # both checks
    calls = log.calls_for(conn, row["task_id"])
    assert [(c["kind"], c["agent"], c["model"], c["effort"], c["time_limit"]) for c in calls] == [
        ("do", "claude", HAIKU, "low", 600), ("check", "chatgpt", "gpt-6-astra", None, 600),
        ("fix", "claude", HAIKU, "low", 600), ("recheck", "chatgpt", "gpt-6-astra", None, 600)]
    assert log.models_of(row) == {"claude": {"model": HAIKU, "effort": "low"}, "chatgpt": {"model": "gpt-6-astra", "effort": None}}


def test_with_no_choice_every_call_runs_the_layers_defaults(conn):
    set_local()  # the local file of this test: empty
    models.set_default({"skill": "writing"}, "claude", model="opus")
    code, out, row, worker, chat = _route(conn)
    assert _choices(worker) == [("claude", OPUS, None, 1200)]
    assert [(c.model, c.layer, c.file) for c in chat.choices] == [("gpt-6.1-sol", "agent", "config/agents.json")]
    calls = log.calls_for(conn, row["task_id"])
    assert (calls[0]["model"], calls[0]["time_limit"], calls[1]["model"]) == (OPUS, 1200, "gpt-6.1-sol")
    assert log.models_of(row) == {}


def test_a_relay_stage_reads_its_team_and_stage_defaults(conn):
    models.set_default({"team": "research-build", "stage": 2}, "claude", model="haiku", effort="max")
    models.set_default({"team": "research-build", "role": "check"}, "chatgpt", effort="ultra")
    code, out, row, worker, chat = _relay(conn, "research-build")
    assert code == 0
    assert _choices(worker) == [("claude", HAIKU, "max", 600)]
    assert [(c.model, c.effort, c.layer, c.effort_key) for c in chat.choices] == [
        ("gpt-6.1-sol", "ultra", "agent", "research-build.check")]


def test_the_served_record_rides_on_the_row(conn):
    class Served(Recorder):
        def __call__(self, prompt, **kwargs):
            text = super().__call__(prompt, **kwargs)
            choice = kwargs["choice"]
            return claude_worker.Answer(text, served={**choice.record(), "model": "claude-opus-4-8", "source": "stream: init and modelUsage",
                                                     "credits": {"seen": False}, "differs": True})
    code, out, row, worker, chat = _route(conn, worker=Served(), model_flags=["claude=opus"])
    do = log.calls_for(conn, row["task_id"])[0]
    assert log.served_of(do)["model"] == "claude-opus-4-8" and log.served_of(do)["asked"] == OPUS and do["model"] == OPUS
    from router import cardline
    assert cardline.line(row, None, log.calls_for(conn, row["task_id"])) == "Opus 5.5 re-ran this on claude-opus-4-8"


def test_a_file_mode_build_calls_served_record_rides_on_the_row(project, file_conn, runner):
    # brief 33.3 D1 (task 155): a build call in a copy goes through filecalls.wrap, which rebuilds the answer; the served
    # record the stream gave must survive that, as a plain call's does
    from tests.test_filemode_flow import BUILD, CopyWorker, route

    class Served(CopyWorker):
        def __call__(self, prompt, copy=None, search=False, **kwargs):
            text = super().__call__(prompt, copy=copy, search=search, **kwargs)
            choice = kwargs["choice"]
            return claude_worker.Answer(str(text), served={**choice.record(), "model": "claude-opus-4-8",
                                                           "source": "stream: init and modelUsage", "credits": {"seen": False},
                                                           "differs": True})
    code, out, row = route(file_conn, worker=Served(BUILD))
    assert code == 0, out
    assert [c["path"] for c in log.project_files_of(row)["changed"]] == ["calc.py", "test_calc.py"]  # built in the copy
    do = log.calls_for(file_conn, row["task_id"])[0]
    served = log.served_of(do)
    assert served is not None, "the do row has no served record"
    assert served["model"] == "claude-opus-4-8" and served["source"] == "stream: init and modelUsage"
    assert served["asked"] == do["model"]


# ---------- resume, fallback and the takeover (decision 4) ----------

def test_a_resume_by_the_other_builder_uses_the_tasks_choice_for_it(conn):
    code, out, row, worker, chat = _route(conn, worker=Recorder(claude_limit()), model_flags=["chatgpt=gpt-6.1-terra"])
    assert row["status"] == "failed"  # no gate: the plan limit stands, offered to sr resume
    resumed = Chat("the answer")
    code, out2, after, *_ = _resume(conn, row, chatgpt=resumed, worker=Recorder())
    assert code == 0 and after["status"] == "done"
    assert resumed.choices[0].model == "gpt-6.1-terra" and resumed.choices[0].layer == "task"
    resume_row = next(c for c in log.calls_for(conn, row["task_id"]) if c["call_id"].endswith("-resume"))
    assert (resume_row["agent"], resume_row["model"]) == ("chatgpt", "gpt-6.1-terra")


def test_a_takeovers_substitute_uses_its_own_defaults_and_the_line_says_so(conn):
    models.set_default({"team": "route", "role": "build"}, "chatgpt", model="gpt-6.1-terra")
    code, out, row, worker, chat = _route(conn, worker=Recorder(claude_limit()), chat=Chat("the answer"), gate=Gate(),
                                          model_flags=["chatgpt=gpt-6-astra", "claude=haiku"])
    assert row["status"] == "done"
    taken = next(c for c in log.calls_for(conn, row["task_id"]) if c["call_id"].endswith("-takeover"))
    assert (taken["agent"], taken["model"]) == ("chatgpt", "gpt-6.1-terra")  # the layers, not the task's gpt-6-astra
    assert chat.choices[0].layer == "role" and chat.choices[0].model == "gpt-6.1-terra"
    assert "ChatGPT took over the first call · Claude hit its plan limit · ChatGPT on its own defaults, not the task's choice" in out.message


def test_a_fallbacks_redo_uses_the_tasks_choice(conn):
    code, out, row, worker, chat = _route(conn, chat=Chat("FIX\n1. [must] Fix it.", "FIX\n1. not fixed: still wrong"),
                                          model_flags=["chatgpt=gpt-6-astra"])
    assert row["check_state"] == "failed"
    redo = Chat("the redo")
    code, out2, after, *_ = _fallback(conn, row, chatgpt=redo, worker=Recorder("PASS"))
    assert code == 0
    assert redo.choices[0].model == "gpt-6-astra" and redo.choices[0].layer == "task"
    fb = next(c for c in log.calls_for(conn, row["task_id"]) if c["call_id"].endswith("-fb1"))
    assert (fb["agent"], fb["model"]) == ("chatgpt", "gpt-6-astra")


# ---------- the credits stop (decision 6) ----------

def test_a_call_billed_to_usage_credits_stops_the_task_turns_fable_off_and_nothing_is_retried(conn):
    models.set_fable(True)
    served = {"asked": FABLE, "model": FABLE, "credits": {"seen": True, "billed": True, "events": [{"status": "rejected", "overageStatus": "allowed"}]}}
    error = claude_worker.WorkerError("usage credits: " + claude_worker.CREDITS_WORDS, code=models.CREDITS, served=served)
    code, out, row, worker, chat = _route(conn, worker=Recorder(error), chat=Chat("x"), gate=Gate(), model_flags=["claude=fable"])
    assert row["status"] == "failed" and "usage credits" in (row["result"] or "")
    calls = log.calls_for(conn, row["task_id"])
    assert len(calls) == 1 and calls[0]["reason_code"] == "credits" and log.served_of(calls[0])["credits"]["billed"] is True
    assert not any(c["call_id"].endswith("-takeover") for c in calls) and chat.choices == []  # nothing took it over
    assert models.local().fable_on is False and models.local().fable["off_by"].startswith("credits")
    assert "the task stops and Fable is off (it was on)" in out.message
    from router import cardline
    assert cardline.CREDITS_LINE in cardline.line(row, None, calls)


# ---------- the probes (decision 10) ----------

def test_the_probes_keep_the_agent_default_whatever_the_layers_say(tmp_path):
    from router import claude_probe, files_probe, web_files_probe, safety
    models.set_default({"team": "route", "role": "build"}, "claude", model="opus")
    assert claude_worker.WORKER_MODEL == "sonnet"
    assert claude_probe.WORKER_MODEL == files_probe.WORKER_MODEL == web_files_probe.WORKER_MODEL == "sonnet"
    assert safety.claude_search_argv(claude_probe.WORKER_MODEL)[3] == "sonnet"
    assert claude_worker.default_choice().model == "sonnet" and claude_worker.default_choice().timeout == 600


# ---------- sr show and the JSON ----------

def test_sr_show_prints_the_models_and_each_calls_model_asked_and_served(conn, capsys):
    code, out, row, worker, chat = _route(conn, model_flags=["claude=haiku"], effort_flags=["claude=low"])
    assert cli.cmd_show(conn=conn, words=[str(row["n"])], roster=ROSTER) == 0
    text = capsys.readouterr().out
    assert "models: claude=claude-haiku-5-5 (effort low)" in text
    assert cli.cmd_show(conn=conn, words=[str(row["n"])], roster=ROSTER, history=True) == 0
    text = capsys.readouterr().out
    assert "  model: claude-haiku-5-5 -> served unknown, limit 600 s, effort low" in text
    assert "  model: gpt-6.1-sol -> served unknown, limit 600 s" in text


# ---------- the review's items (before D's setup) ----------

def test_a_refused_model_runs_no_probe_before_it(conn):
    # review a1 and c2: the check comes before Cursor's canaries (decision 4: before any probe); --step's file check is
    # covered in tests/test_models_review.py (it needs a project)
    seen = []
    code, out, row, *_ = _route(conn, model_flags=["claude=nope"])
    assert (code, out.code) == (2, "bad_model") and row is None
    out = receipt.Receipt()
    code = cli.cmd_relay("redteam", "x", conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[],
                         post=RelayHook().post, worker=Recorder(), chatgpt=Chat("PASS"), codex_login=lambda: True,
                         cursor=Recorder(), cursor_ready=lambda: seen.append("canaries") or (True, None),
                         model_flags=["cursor=auto"], out=out)
    assert (code, out.code) == (2, "bad_model") and seen == []  # this roster has no Cursor: "makes no call on redteam"
    assert log.recent_tasks(conn) == []


def test_a_model_choice_never_changes_a_prompt(conn):
    plain = Recorder("the answer")
    _route(conn, worker=plain, chat=Chat("FIX\n1. [must] Name a source.", "PASS\n1. fixed"))
    chosen = Recorder("the answer")
    _route(conn, worker=chosen, chat=Chat("FIX\n1. [must] Name a source.", "PASS\n1. fixed"),
           model_flags=["claude=haiku", "chatgpt=gpt-6-astra"], effort_flags=["claude=max"])
    assert [p for p in plain.prompts] == [p for p in chosen.prompts]  # the do and the fix prompts, byte for byte


def test_sr_show_history_names_an_old_rows_pin_for_chatgpt_and_cursor(conn, capsys):
    log.add_task(conn, "sr-old", "t", "cli", {"status": "ok", "label": "writing", "confidence": 0.9, "needs_split": 0.1, "tokens": 0})
    log.set_route(conn, "sr-old", agents=["claude", "chatgpt"], agent="chatgpt", route_reason="best", skill="writing",
                  skill_source="jev", checker="claude", check_state="passed")
    log.add_call(conn, "sr-old", "sr-old", "do", "chatgpt", status="done", text="x")  # a row from before log 20: no model
    log.add_call(conn, "sr-old-c1", "sr-old", "check", "claude", status="done", text="PASS")
    log.set_done(conn, "sr-old", "x")
    assert cli.cmd_show(conn=conn, words=["sr-old"], roster=ROSTER, history=True) == 0
    text = capsys.readouterr().out
    assert "  model: gpt-6.1-sol -> served unknown" in text  # the pin (review a6)
    assert "  model: sonnet -> served unknown" in text  # Claude's rows from before read as `sonnet`
