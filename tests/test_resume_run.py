"""Phase C of build brief 7: `sr resume <n>` runs the plan. The substitute is sent what the stopped
agent was sent (never its output), its row carries `resume_of`, and the existing step functions take
it from there: the rest of the chain, then the check, with the checker swapped where the substitute
would check its own work. Fake agents only; every secret here is fake."""
import pytest

from router import __main__ as cli
from router import chatgpt_worker, checking, claude_worker, log, media, relay, safety
from tests.helpers import fake_label
from tests.test_collab import AMENDED, DELIVERABLE, EDITED, LOADED, PLAN
from tests.test_collab import TASK as COLLAB_TASK
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_relay import CONFIG, GOOD_NOTE, ROSTER, SECRET, TASK, Chat, RelayHook

QUICK = {"status": "ok", "label": "quick_answer", "confidence": 0.95, "needs_split": 0.1, "tokens": 0}
WRITING = {"status": "ok", "label": "writing", "confidence": 0.95, "needs_split": 0.1, "tokens": 0}
XPULSE = {"status": "ok", "label": "x_social_pulse", "confidence": 0.95, "needs_split": 0.1, "tokens": 0}
ROUTE_TASK = "write two lines about seed trays"


def claude_limit():
    return claude_worker.WorkerError("plan limit on claude: You've hit your session limit · resets 3pm",
                                     code="plan_limit")


def codex_limit():
    return chatgpt_worker.WorkerError("plan limit on chatgpt: You've hit your usage limit.", code="plan_limit")


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _route(conn, jev, *, worker, chatgpt=None, hook=None, task=ROUTE_TASK):
    lines, clock, hook = [], Clock(), hook or Webhook()
    code = cli.cmd_route(task, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=fake_label(jev), post=hook.post, worker=worker, chatgpt=chatgpt or Chat("PASS"),
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=True, out=lines.append)
    return code, "\n".join(lines), log.recent_tasks(conn)[0]


def _relay(conn, preset, task, *, worker, chatgpt, hook=None):
    lines, clock, hook = [], Clock(), hook or RelayHook(s1=GOOD_NOTE)
    code = cli.cmd_relay(preset, task, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                         settings_paths=[], post=hook.post, worker=worker, chatgpt=chatgpt, codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True, out=lines.append)
    return code, "\n".join(lines), log.recent_tasks(conn)[0]


def _resume(conn, row, *, worker=None, chatgpt=None, hook=None, words=None, environ=None, codex_login=None):
    lines, clock, hook = [], Clock(), hook or Webhook()
    worker, chatgpt = worker or Scripted(), chatgpt or Chat()
    code = cli.cmd_resume(words or [str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED,
                          environ=environ or {}, settings_paths=[], post=hook.post, worker=worker, chatgpt=chatgpt,
                          codex_login=codex_login or (lambda: True), fetch=hook.fetch, close=hook.close,
                          sleep=clock.sleep, clock=clock, wait=True, out=lines.append)
    return code, "\n".join(lines), log.get_task(conn, row["task_id"]), worker, chatgpt


def _short(value, task_id):
    """A call id without the task id in front ("<id>" for the task id itself); None stays None."""
    return None if value is None else (value.removeprefix(task_id) or "<id>")


def _calls(conn, row):
    tid = row["task_id"]
    return [(_short(c["call_id"], tid), c["kind"], c["agent"], c["status"], c["reason_code"], _short(c["resume_of"], tid))
            for c in log.calls_for(conn, tid)]


# ---------- route: the doer ----------

def test_a_quick_answer_stopped_on_claude_is_answered_by_chatgpt_with_no_check(conn):
    code, out, row = _route(conn, QUICK, worker=Scripted(claude_limit()))
    assert code == 1
    code, out, row, worker, chat = _resume(conn, row, chatgpt=Chat("an answer from chatgpt"))
    assert code == 0, out
    assert (row["status"], row["result"], row["agent"], row["checker"], row["check_state"]) == (
        "done", "an answer from chatgpt", "chatgpt", None, "not_needed")
    # what claude was sent, plus the search line: the substitute's own search (rules v2.22) follows the Web search rules
    assert chat.prompts == [f"{ROUTE_TASK}\n\n{checking.SEARCH_LINE_GENERAL}"]
    assert worker.prompts == []
    assert _calls(conn, row) == [("<id>", "do", "claude", "failed", "plan_limit", None),
                                 ("-resume", "do", "chatgpt", "done", None, "<id>")]
    assert "Resuming #1" in out and "chatgpt does it instead" in out and "No check" in out
    assert "an answer from chatgpt" in out and "UNCHECKED" not in out


def test_a_writing_task_stopped_on_claude_is_built_by_chatgpt_and_checked_by_claude(conn):
    code, out, row = _route(conn, WRITING, worker=Scripted(claude_limit()))
    code, out, row, worker, chat = _resume(conn, row, worker=Scripted("PASS"), chatgpt=Chat("two lines by chatgpt"))
    assert code == 0, out
    assert (row["status"], row["result"], row["agent"], row["checker"], row["check_state"]) == (
        "done", "two lines by chatgpt", "chatgpt", "claude", "passed")
    assert _calls(conn, row) == [("<id>", "do", "claude", "failed", "plan_limit", None),
                                 ("-resume", "do", "chatgpt", "done", None, "<id>"),
                                 ("-c1", "check", "claude", "done", None, None)]
    assert "two lines by chatgpt" in worker.prompts[0], "claude checks chatgpt's result"
    assert "Checker: claude (chatgpt would otherwise check its own work)." in out and "CHECKED: passed." in out


def test_after_a_resume_a_fix_goes_to_the_substitute_and_the_recheck_to_the_swapped_checker(conn):
    code, out, row = _route(conn, WRITING, worker=Scripted(claude_limit()))
    code, out, row, worker, chat = _resume(conn, row, worker=Scripted("FIX\n1. add a rhyme", "PASS"),
                                           chatgpt=Chat("two lines", "two rhyming lines"))
    assert code == 0, out
    assert [c[1:3] for c in _calls(conn, row)] == [("do", "claude"), ("do", "chatgpt"), ("check", "claude"),
                                                  ("fix", "chatgpt"), ("recheck", "claude")]
    assert (row["result"], row["check_state"]) == ("two rhyming lines", "fixed")


def test_a_media_task_gives_the_substitute_its_files_the_way_media_delivers_them_to_it(conn, tmp_path, monkeypatch):
    """Choice 11: Claude gets the PDF itself; ChatGPT gets its pages as images."""
    monkeypatch.setattr(media, "MEDIA_ROOT", tmp_path / "media")
    pdf = tmp_path / "letter.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    def pages(copy, folder):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "page-1.png").write_bytes(b"png")
        return [folder / "page-1.png"], 1

    class FilesAgent(Chat):
        def __call__(self, prompt, **kwargs):
            self.kwargs.append(kwargs)
            return Scripted.__call__(self, prompt)

    lines, clock, hook = [], Clock(), Webhook()
    claude = FilesAgent(claude_limit())
    cli.cmd_route("summarize this letter", conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                  label=fake_label(QUICK), post=hook.post, worker=claude, chatgpt=Chat(), codex_login=lambda: True,
                  sleep=clock.sleep, clock=clock, wait=True, files=[pdf], pages=pages, out=lines.append)
    row = log.recent_tasks(conn)[0]
    assert [rel for _, rel in claude.kwargs[0]["files"]] == ["letter.pdf"]
    chat = FilesAgent("a summary")
    code, out, row, _, _ = _resume(conn, row, chatgpt=chat)
    assert code == 0, out
    assert [rel for _, rel in chat.kwargs[0]["files"]] == [f"{media.PAGES_SUBFOLDER}/letter-page-1.png"]
    assert "letter.pdf: pages 1 to 1 of 1" in chat.prompts[0]


# ---------- route: the check, fix and re-check rounds ----------

def test_a_stopped_check_round_is_taken_by_claude_when_grok_did_the_work(conn):
    hook = Webhook(do="what people on X say about trays")
    code, out, row = _route(conn, XPULSE, worker=Scripted(), chatgpt=Chat(codex_limit()), hook=hook)
    assert (row["status"], row["check_state"]) == ("done", "unchecked") and "Run: sr resume 1" in out
    code, out, row, worker, chat = _resume(conn, row, worker=Scripted("PASS"))
    assert code == 0, out
    assert (row["status"], row["agent"], row["checker"], row["check_state"]) == ("done", "grok", "claude", "passed")
    assert "what people on X say about trays" in worker.prompts[0]
    assert _calls(conn, row)[-2:] == [("-c1", "check", "chatgpt", "failed", "plan_limit", None),
                                      ("-c1-resume", "check", "claude", "done", None, "-c1")]


def test_a_stopped_fix_round_goes_to_chatgpt_with_the_task_the_result_and_the_fix_list(conn):
    code, out, row = _route(conn, WRITING, worker=Scripted("two lines", claude_limit()),
                            chatgpt=Chat("FIX\n1. add a rhyme"))
    assert (row["status"], row["check_state"]) == ("done", "failed")
    code, out, row, worker, chat = _resume(conn, row, worker=Scripted("PASS"), chatgpt=Chat("two rhyming lines"))
    assert code == 0, out
    assert ROUTE_TASK in chat.prompts[0] and "two lines" in chat.prompts[0] and "add a rhyme" in chat.prompts[0]
    assert (row["result"], row["agent"], row["checker"], row["check_state"]) == (
        "two rhyming lines", "chatgpt", "claude", "fixed")
    assert [c[1:3] for c in _calls(conn, row)][-2:] == [("fix", "chatgpt"), ("recheck", "claude")]


# ---------- relay ----------

def test_a_relay_build_stage_stopped_on_claude_is_built_by_chatgpt_then_checked_by_claude(conn):
    code, out, row = _relay(conn, "research-build", TASK, worker=Scripted(claude_limit()), chatgpt=Chat())
    assert code == 1 and row["failed_stage"] == 2 and "Run: sr resume 1  (continues with claude)" not in out
    assert "Plan limit on claude. Run: sr resume 1  (continues with chatgpt)" in out
    code, out, row, worker, chat = _resume(conn, row, worker=Scripted("PASS"), chatgpt=Chat("a built summary"))
    assert code == 0, out
    # the stage prompt claude was sent, with the search line: ChatGPT searches on this stage (brief 8, the amendment)
    assert chat.prompts == [relay.prompt_for("build", TASK, GOOD_NOTE, search=True)]
    # Brief 8 (the owner's amendment): search follows preset and role, whichever agent builds, so ChatGPT searches.
    assert chat.kwargs[0]["web_search"] == "live"
    assert "a built summary" in worker.prompts[0]
    assert (row["status"], row["failed_stage"], row["agent"], row["checker"], row["check_state"], row["result"]) == (
        "done", None, "chatgpt", "claude", "passed", "a built summary")
    assert _calls(conn, row)[1:] == [("-s2", "stage", "claude", "failed", "plan_limit", None),
                                     ("-s2-resume", "stage", "chatgpt", "done", None, "-s2"),
                                     ("-c1", "check", "claude", "done", None, None)]


BAD_PLAN = "I would plan it like this, but no headings."


def test_a_stopped_reask_is_redone_from_the_stage_prompt_never_the_reask_prompt(conn):
    """D8 (the owner): chatgpt gets the task alone at stage 1, never claude's first plan."""
    code, out, row = _relay(conn, "collab", COLLAB_TASK, worker=Scripted(BAD_PLAN, claude_limit()), chatgpt=Chat())
    assert row["failed_stage"] == 1
    code, out, row, worker, chat = _resume(conn, row, worker=Scripted(DELIVERABLE), chatgpt=Chat(PLAN, AMENDED, EDITED))
    assert code == 0, out
    assert chat.prompts[0] == relay.prompt_for("plan", COLLAB_TASK, None, search=True) and BAD_PLAN not in chat.prompts[0]
    assert row["check_state"] == "passed"


def test_a_resumed_reask_that_still_misses_its_contract_stops_the_chain(conn):
    """One re-ask per stage: the stopped re-ask used it, so the fresh stage gets no second one."""
    code, out, row = _relay(conn, "collab", COLLAB_TASK, worker=Scripted(BAD_PLAN, claude_limit()), chatgpt=Chat())
    code, out, row, worker, chat = _resume(conn, row, chatgpt=Chat(BAD_PLAN))
    assert code == 1 and row["status"] == "failed" and row["failed_stage"] == 1
    assert "re-ask was used" in row["result"] and len(chat.prompts) == 1


def test_a_resumed_stage_keeps_its_one_reask_for_the_substitute(conn):
    code, out, row = _relay(conn, "collab", COLLAB_TASK, worker=Scripted(claude_limit()), chatgpt=Chat())
    code, out, row, worker, chat = _resume(conn, row, worker=Scripted(DELIVERABLE),
                                           chatgpt=Chat(BAD_PLAN, PLAN, AMENDED, EDITED))
    assert code == 0, out
    assert [c[1:3] for c in _calls(conn, row)][:3] == [("stage", "claude"), ("stage", "chatgpt"), ("reask", "chatgpt")]


def test_collab_stage_3_resumed_by_chatgpt_moves_the_check_stage_to_claude(conn):
    code, out, row = _relay(conn, "collab", COLLAB_TASK, worker=Scripted(PLAN, claude_limit()), chatgpt=Chat(AMENDED))
    assert row["failed_stage"] == 3
    code, out, row, worker, chat = _resume(conn, row, worker=Scripted(EDITED), chatgpt=Chat(DELIVERABLE))
    assert code == 0, out
    assert [c[1:3] for c in _calls(conn, row)] == [("stage", "claude"), ("stage", "chatgpt"), ("stage", "claude"),
                                                  ("stage", "chatgpt"), ("stage", "claude")]
    assert (row["agent"], row["checker"], row["check_state"], row["check_note"]) == (
        "chatgpt", "claude", "passed", "checked-by-stage 4")
    assert "checked by stage 4 (claude)" in out and "CHECKED: by stage 4 (claude): passed." in out


def test_the_check_stage_swap_is_read_from_the_rows():
    rows = [{"kind": "stage", "stage": 3, "agent": "chatgpt", "status": "done", "text": "x", "call_id": "t-s3-resume",
             "resume_of": "t-s3", "role": "execute"}]
    check = LOADED.presets["collab"].check_stage
    assert relay.stage_agent(check, rows) == "claude"
    rows[0]["agent"] = "claude"
    assert relay.stage_agent(check, rows) == "chatgpt"


# ---------- both at their limit, refusals, interrupts ----------

def test_when_the_substitute_is_at_its_limit_too_the_task_stays_stopped_and_names_both(conn):
    code, out, row = _route(conn, WRITING, worker=Scripted(claude_limit()))
    code, out, row, worker, chat = _resume(conn, row, chatgpt=Chat(codex_limit()))
    assert code == 1 and row["status"] == "failed"
    assert "Plan limit on chatgpt too: claude and chatgpt are both at their plan limit." in out
    assert _calls(conn, row)[-1] == ("-resume", "do", "chatgpt", "failed", "plan_limit", "<id>")
    code, out, again, _, _ = _resume(conn, row)
    assert code == 2 and "already resumed once" in out and len(log.calls_for(conn, row["task_id"])) == 2


@pytest.mark.parametrize("setup, words", [
    ("passed", "it is done"), ("override", "override"), ("not_limit", "not a plan limit"),
])
def test_a_refusal_writes_nothing_and_exits_2(conn, setup, words):
    if setup == "passed":
        _, _, row = _route(conn, QUICK, worker=Scripted("fine"))
    elif setup == "override":
        _, _, row = _route(conn, WRITING, worker=Scripted(claude_limit()), task="@claude " + ROUTE_TASK)
    else:
        _, _, row = _route(conn, QUICK, worker=Scripted(claude_worker.WorkerError("claude exited 1: boom")))
    before = (dict(log.get_task(conn, row["task_id"])), [dict(c) for c in log.calls_for(conn, row["task_id"])])
    code, out, after, worker, chat = _resume(conn, row)
    assert code == 2 and words in out and "Nothing was logged or sent." in out
    assert (dict(after), [dict(c) for c in log.calls_for(conn, row["task_id"])]) == before
    assert worker.prompts == [] and chat.prompts == []


def test_a_check_stage_refusal_says_the_stage_before_is_unchecked(conn):
    code, out, row = _relay(conn, "collab", COLLAB_TASK, worker=Scripted(PLAN, DELIVERABLE),
                            chatgpt=Chat(AMENDED, codex_limit()))
    assert row["failed_stage"] == 4 and "Not resumable: claude made stage 3" in out
    assert "stage 3's result stays unchecked" in row["check_note"]
    code, out, row, worker, chat = _resume(conn, row)
    assert code == 2 and "claude made stage 3, so it can't check it" in out and "sr show 1 --stages" in out


def test_an_unknown_number_or_no_number_is_refused(conn):
    code, out, *_ = _resume(conn, {"n": 9, "task_id": "x"}, words=["9"])
    assert code == 2 and "No task #9." in out
    code, out, *_ = _resume(conn, {"n": 9, "task_id": "x"}, words=["fish"])
    assert code == 2 and "sr resume 5" in out


def test_a_billing_switch_refuses_the_resume(conn):
    _, _, row = _route(conn, QUICK, worker=Scripted(claude_limit()))
    code, out, after, worker, chat = _resume(conn, row, environ={"OPENAI_API_KEY": "FAKE"})
    assert code == 2 and after["status"] == "failed" and chat.prompts == []


def test_without_a_codex_login_nothing_changes(conn):
    _, _, row = _route(conn, QUICK, worker=Scripted(claude_limit()))
    code, out, after, worker, chat = _resume(conn, row, codex_login=lambda: False)
    assert code == 2 and "codex login" in out and after["status"] == "failed" and chat.prompts == []
    assert len(log.calls_for(conn, row["task_id"])) == 1


def test_ctrl_c_during_the_substitute_call_changes_nothing(conn):
    _, _, row = _route(conn, QUICK, worker=Scripted(claude_limit()))
    before = dict(log.get_task(conn, row["task_id"]))
    code, out, after, worker, chat = _resume(conn, row, chatgpt=Chat(KeyboardInterrupt))
    assert code == 130 and "Nothing changed" in out and f"sr resume {row['n']}" in out
    assert dict(after) == before and len(log.calls_for(conn, row["task_id"])) == 1


def test_reopen_is_only_for_a_failed_or_done_task_and_refuses_a_self_check(conn):
    from tests.helpers import ALL_AGENTS, add_row
    add_row(conn, "t")
    with pytest.raises(log.StateError):
        log.reopen_for_resume(conn, "t", agents=ALL_AGENTS, agent="chatgpt", checker="claude", check_state="pending")
    log.set_failed(conn, "t", "x", failed_stage=None)
    with pytest.raises(ValueError, match="own work"):
        log.reopen_for_resume(conn, "t", agents=ALL_AGENTS, agent="chatgpt", checker="chatgpt", check_state="pending")
    log.reopen_for_resume(conn, "t", agents=ALL_AGENTS, agent="chatgpt", checker="claude", check_state="pending")
    row = log.get_task(conn, "t")
    assert (row["status"], row["agent"], row["checker"], row["result"]) == ("queued", "chatgpt", "claude", None)


# ---------- main wiring ----------

from tests.test_relay import real_main  # noqa: E402,F401  (the fixture)


def test_main_resume_refuses_a_task_that_does_not_exist(real_main, capsys):
    assert real_main(["resume", "1"], platform="darwin") == 2
    assert "No task #1." in capsys.readouterr().out


def test_main_resume_refuses_a_task_that_did_not_stop_on_a_plan_limit(real_main, capsys):
    conn = log.init_db(cli.DB_PATH)
    _route(conn, QUICK, worker=Scripted("fine"))
    conn.close()
    assert real_main(["resume", "#1"], platform="darwin") == 2
    assert "it is done" in capsys.readouterr().out


def test_help_names_the_resume_command(capsys):
    with pytest.raises(SystemExit):
        cli.main(["resume", "--help"], platform="darwin")
    out = capsys.readouterr().out
    assert "plan limit" in out and "--no-wait" in out
