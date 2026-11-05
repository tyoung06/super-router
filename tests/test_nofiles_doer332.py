"""Brief 33.2 fix 1b (the owner's call on Phase 0 item (iii), 31 Oct): a `--no-files` task's doer is always Claude and its
checker ChatGPT, whatever Jev's label or the owner's `--skill` would pick; it is never refused for that. When the label or
skill would have picked another doer (or come back), the record's route reason and the card say so in one line: "Doer
set to Claude: --no-files reads the project's files (…)". Jev is still asked: its label stays the task's skill. A task
without `--no-files` routes as before. Real git in temp folders, fake agents; every value here is fake."""
from router import __main__ as cli
from router import availability, cardline, copies, log, routing
from tests.helpers import fake_label
from tests.test_filemode_flow import conn, project, runner  # noqa: F401 (fixtures)
from tests.test_handoff_contract import HANDOFF
from tests.test_loop import Clock, Webhook
from tests.test_nofiles_read332 import TASK, Reader
from tests.test_relay import CONFIG, ROSTER, Chat
from tests.test_resume_run import WRITING

WEB = {**WRITING, "label": "web_research"}
REASON = "Doer set to Claude: --no-files reads the project's files (web_research would have gone to ChatGPT)"


def _route(conn, worker, *, chatgpt=None, jev=WEB, skill=None, no_files=True, available=None):
    lines, clock, hook = [], Clock(), Webhook()
    label = fake_label(jev)
    code = cli.cmd_route(TASK, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=label,
                         post=hook.post, worker=worker, chatgpt=chatgpt or Chat("PASS"), codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True, skill=skill,
                         available=available, out=lines.append, project="garden", files_ready=lambda: (True, None),
                         no_files=no_files)
    return code, "\n".join(lines), log.get_task(conn, log.recent_tasks(conn)[0]["task_id"]), label


def _do_agents(conn, row):
    return [c["agent"] for c in log.calls_for(conn, row["task_id"]) if c["kind"] == "do"]


def test_a_web_research_label_ends_with_claude_doing_it_in_the_read_only_copy(project, conn, runner):
    worker, chat = Reader(), Chat("PASS")
    code, said, row, label = _route(conn, worker, chatgpt=chat)
    assert code == 0, said
    assert (row["agent"], row["checker"], row["skill"], row["skill_source"]) == ("claude", "chatgpt", "web_research", "jev")
    assert row["route_reason"] == REASON
    assert _do_agents(conn, row) == ["claude"] and worker.calls[0]["copy"].write is False
    assert log.project_files_of(row)["read_only"] is True
    assert row["status"] == "done" and not copies.exists(row["task_id"])
    assert len(label.calls) == 1  # Jev is still asked: its label stays the task's skill
    assert f"web_research (Jev, confidence 0.95) -> claude, {REASON[0].lower()}{REASON[1:]}." in said


def test_an_owner_skill_web_research_ends_with_claude_too(project, conn, runner):
    code, said, row, _ = _route(conn, Reader(), jev={"status": "below_floor", "label": None}, skill="web_research")
    assert code == 0, said
    assert (row["agent"], row["checker"], row["skill"], row["skill_source"]) == ("claude", "chatgpt", "web_research", "owner")
    assert row["route_reason"] == REASON


def test_the_card_says_it_in_one_line(project, conn, runner):
    code, said, row, _ = _route(conn, Reader())
    assert code == 0, said
    assert REASON in cardline.parts(row, None, log.calls_for(conn, row["task_id"]))


def test_a_grok_label_ends_with_claude_and_chatgpt_checks(project, conn, runner):
    code, said, row, _ = _route(conn, Reader(), jev={**WRITING, "label": "make_media"})
    assert code == 0, said
    assert (row["agent"], row["checker"]) == ("claude", "chatgpt")
    assert row["route_reason"] == ("Doer set to Claude: --no-files reads the project's files "
                                   "(make_media would have gone to Grok Bot)")


def test_a_skill_that_would_come_back_runs_with_claude_and_is_never_refused(project, conn, runner):
    code, said, row, _ = _route(conn, Reader(), jev={**WRITING, "label": "computer_use"})
    assert code == 0, said
    assert (row["status"], row["agent"], row["checker"]) == ("done", "claude", "chatgpt")
    assert row["route_reason"] == ("Doer set to Claude: --no-files reads the project's files "
                                   "(computer_use would have come back: skill not routed in version 2)")


def test_a_label_that_picks_claude_is_unchanged(project, conn, runner):
    code, said, row, _ = _route(conn, Reader(), jev=WRITING)
    assert code == 0, said
    assert (row["agent"], row["checker"], row["route_reason"]) == ("claude", "chatgpt", "best")
    assert not any(p.startswith(routing.NO_FILES_DOER) for p in cardline.parts(row, None, ()))


def test_without_chatgpt_a_redirected_task_runs_unchecked_and_says_why(project, conn, runner):
    class NoChatGPT:  # a gate with ChatGPT signed out; Claude stays (it is required)
        def __call__(self, name, fresh=False):
            down = name == "chatgpt"
            return availability.Availability(not down, "ChatGPT is signed out" if down else None,
                                             "signed_out" if down else None)

        def of(self, names, fresh=False):
            return {n: self(n) for n in names}
    code, said, row, _ = _route(conn, Reader("Two lines.\n\n" + HANDOFF), jev={**WRITING, "label": "make_media"},
                                available=NoChatGPT())
    assert code == 0, said
    assert (row["agent"], row["checker"], row["check_state"]) == ("claude", None, "unchecked")
    assert row["check_note"] == "no other agent available to check (ChatGPT is signed out)"
    assert row["route_reason"].startswith(routing.NO_FILES_DOER)


def test_without_no_files_a_web_research_label_still_goes_to_chatgpt(project, conn, runner):
    chat = Chat("Done by ChatGPT.\n\n" + HANDOFF, "PASS")
    code, said, row, _ = _route(conn, Reader(), chatgpt=chat, no_files=False)
    assert (row["agent"], row["route_reason"]) == ("chatgpt", "best")
