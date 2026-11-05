"""Build brief 33.4, S (decisions 10 to 12 and 10b): Suggest ideas. One Claude call, text only, no Jev, never checked, no entry,
nothing retained; its ideas `later` with the suggest task as source. A running suggest leaves intake, Auto's refusals, status
and What now? exactly as they are without it. Real git in temp folders, a fake Claude; every value is fake."""
import json

import pytest

from router import __main__ as cli
from router import auto, context, ideas, intake, jsonview, locks, log, memory, nextsteps, page_commands, plan, projects, resume, runs, status, suggest, whatnow
from tests.test_filemode_flow import conn, project, runner  # noqa: F401 (fixtures)
from tests.test_plan_chain import ROSTER
from tests.test_relay import CONFIG

THREE = "## Ideas\n- Add miles and kilometres.\n- Add a --json flag.\n- Write a usage page.\n"


class Claude:
    def __init__(self, reply=THREE, during=None):
        self.reply, self.prompts, self.kw, self.during = reply, [], [], during

    def __call__(self, prompt, **kw):
        self.prompts.append(prompt)
        self.kw.append(kw)
        if self.during:
            self.during()
        if isinstance(self.reply, BaseException):
            raise self.reply
        return self.reply


def _suggest(conn, worker=None, name="garden", hindsight=None):
    lines = []
    worker = worker or Claude()
    code = cli.cmd_suggest([name], conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], worker=worker,
                           hindsight=hindsight, out=lines.append)
    return code, "\n".join(str(x) for x in lines), worker


def _row(conn):
    return next(r for r in log.project_tasks(conn, "garden") if r["mode"] == "suggest")


def test_one_call_no_jev_never_checked_and_three_ideas_added(project, conn):
    code, said, w = _suggest(conn)
    assert code == 0, said
    row = _row(conn)
    assert (row["status"], row["check_state"], row["jev_status"], row["agent"], row["checker"]) == ("done", "not_needed", "not_asked", "claude", None)
    assert [(c["kind"], c["agent"]) for c in log.calls_for(conn, row["task_id"])] == [("do", "claude")]
    assert row["result"] == "3 added" and len(w.prompts) == 1


def test_its_ideas_are_later_with_the_task_as_source_and_read_suggested_by(project, conn):
    _suggest(conn)
    row = _row(conn)
    found = ideas.listing(conn, "garden")["ideas"]
    assert [i["text"] for i in found] == ["Write a usage page.", "Add a --json flag.", "Add miles and kilometres."]
    assert all(i["source"]["kind"] == "later" and i["source"]["task_id"] == row["task_id"] and i["source"]["suggested"] for i in found)
    assert f"Suggested by #{row['n']}" in ideas.line(found[0])
    assert ideas.view(conn, ideas.add(conn, "garden", "mine")[0])["source"]["suggested"] is False


def test_text_only_no_copy_no_search_no_tools(project, conn):
    code, said, w = _suggest(conn)
    assert w.kw == [{"choice": w.kw[0]["choice"]}]
    assert log.project_files_of(_row(conn)) is None


def test_no_entry_no_card_chip_and_no_memory(project, conn):
    before = projects.read_handoff(project)
    _suggest(conn)
    row = _row(conn)
    assert projects.read_handoff(project) == before
    assert log.handoff_of(row) in ([], None)
    assert memory.storable(row) is False and nextsteps.chips(conn, row) == []


def test_it_reads_everything_it_should(project, conn):
    (project / "SPEC.md").write_text("# Spec\n\nthe spec words\n")
    (project / "docs").mkdir()
    (project / "docs" / "PLAN.md").write_text("# Plan\n- [x] done step\n")
    ideas.add(conn, "garden", "an older idea")
    gone, _ = ideas.add(conn, "garden", "a dismissed idea")
    ideas.dismiss(conn, "garden", gone.id)
    code, said, w = _suggest(conn)
    prompt = w.prompts[0]
    assert "the spec words" in prompt and "===== SPEC.md (garden) =====" in prompt
    assert "- [x] done step" in prompt
    assert "===== PROJECT FILES =====" in prompt and "calc.py" in prompt and "bytes)" not in prompt.split("PROJECT FILES")[1].split("=====")[1]
    assert "- an older idea" in prompt and "- a dismissed idea" in prompt


def test_the_ideas_block_is_capped_newest_first_whole_ideas():
    class I:
        def __init__(self, text):
            self.text = text
    lines = suggest.ideas_lines([I("new one"), I("x" * 10), I("older"), I("oldest")], 20)
    assert lines == ["- new one", f"- {'x' * 10}", "and 2 older not shown"]
    assert suggest.ideas_lines([], 20) == []


def test_the_file_list_is_capped_as_the_plans_is(project, conn, monkeypatch):
    monkeypatch.setattr(plan, "FILES_LISTED", 1)
    lines = suggest.file_paths(project)
    assert len(lines) == 2 and lines[1].startswith("(the list is cut here: 1 of ")


def test_the_lock_is_held_only_for_the_read(project, conn):
    seen = []

    def during():
        with locks.held("project-garden", folder=cli.DB_PATH.parent / runs.FOLDER_NAME, wait=False):
            seen.append("free")
    code, said, _ = _suggest(conn, Claude(during=during))
    assert seen == ["free"] and code == 0, said


# ---------- the shape (decision 12) ----------

@pytest.mark.parametrize("reply, words, count", [
    ("## Ideas\n- one\n- " + "x" * 401 + "\n- two\n", "2 added, 1 dropped: too long", 2),
    ("## Ideas\n- one\n- @grok do it\n", "1 added, 1 dropped: starts with @ or /", 1),
    ("## Ideas\n- a\n- b\n- c\n- d\n", "3 added, 1 dropped: too many", 3),
])
def test_a_bad_line_is_dropped_and_counted_and_never_shown(project, conn, reply, words, count):
    code, said, _ = _suggest(conn, Claude(reply))
    assert code == 0 and _row(conn)["result"] == words
    assert len(ideas.listing(conn, "garden")["ideas"]) == count
    assert "x" * 50 not in said and "@grok" not in said


def test_a_key_shaped_line_is_dropped_named_never_shown(project, conn):
    key = "sk-ant-" + "a" * 40
    code, said, _ = _suggest(conn, Claude(f"## Ideas\n- good one\n- {key}\n"))
    assert _row(conn)["result"] == "1 added, 1 dropped: looks like a key" and key not in said


def test_a_duplicate_of_an_open_idea_is_skipped(project, conn):
    ideas.add(conn, "garden", "Add a --json flag")
    code, said, _ = _suggest(conn)
    assert _row(conn)["result"] == "2 added, 1 already there"


@pytest.mark.parametrize("reply", ["Here are some ideas.", "## Ideas\nnone\n", "- a\n- b\n", "## Ideas\n- @x\n"])
def test_zero_usable_lines_fail_with_no_re_ask(project, conn, reply):
    w = Claude(reply)
    code, said, _ = _suggest(conn, w)
    row = _row(conn)
    assert code == 1 and row["status"] == "failed" and row["result"] == "no idea in the shape"
    assert len(w.prompts) == 1


def test_a_failed_call_fails_the_task(project, conn):
    from router import safety
    code, said, _ = _suggest(conn, Claude(safety.SafeError("claude exited 1")))
    assert code == 1 and _row(conn)["status"] == "failed", said


def test_no_resume_and_no_fallback(project, conn):
    _suggest(conn, Claude("nothing"))
    row = _row(conn)
    calls = log.calls_for(conn, row["task_id"])
    assert "never resumed" in resume.decide(row, calls, live=("claude",)).reason


# ---------- the refusals (decisions 10b and 12) ----------

def _fill(conn, k):
    for i in range(k):
        ideas.add(conn, "garden", f"idea number {i}")


def test_47_open_still_fits_all_three(project, conn):
    _fill(conn, 47)
    code, said, _ = _suggest(conn)
    assert code == 0 and ideas.open_count(conn, "garden") == 50


def test_48_open_is_refused_with_the_real_count(project, conn):
    _fill(conn, 48)
    code, said, w = _suggest(conn)
    assert code == 2 and "48 open ideas: dismiss some to get suggestions" in said
    assert w.prompts == [] and not [r for r in log.project_tasks(conn, "garden") if r["mode"] == "suggest"]
    assert suggest.state_of(conn, "garden")["off"] == "48 open ideas: dismiss some to get suggestions"


def test_claude_unavailable_is_refused(project, conn):
    lines, calls = [], []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cli, "_claude_refusal", lambda available, out: (out("Refused: Claude isn't available."), True)[1])
        code = cli.cmd_suggest(["garden"], conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                               worker=lambda p, **k: calls.append(p), out=lines.append)
    assert code == 2 and calls == [] and "Claude isn't available" in "\n".join(map(str, lines))


def test_a_second_running_is_refused_and_an_ended_process_is_not_in_the_way(project, conn, monkeypatch):
    said = []

    def second():
        code, words, _ = _suggest(conn, Claude())
        said.append((code, words))
    monkeypatch.setattr(runs, "alive", lambda *a: True)
    _suggest(conn, Claude(during=second))
    assert said[0][0] == 2 and "a suggest is already running on garden" in said[0][1]
    row_id = "sr-20261102-130000-abcd"
    log.add_task(conn, row_id, "x", "cli", {"status": "not_asked", "tokens": 0}, mode="suggest", project="garden", run=(1, "then"))
    monkeypatch.setattr(runs, "alive", lambda *a: False)
    assert suggest.refusal(conn, "garden") is None


def test_cancel_works_on_a_running_row(project, conn):
    row_id = "sr-20261102-130000-abce"
    log.add_task(conn, row_id, "x", "cli", {"status": "not_asked", "tokens": 0}, mode="suggest", project="garden")
    lines = []
    assert cli.cmd_cancel(conn=conn, words=[row_id], out=lines.append) == 0
    assert log.get_task(conn, row_id)["status"] == "cancelled"


# ---------- the completeness test (decision 10b) ----------

def _world(conn):
    """Everything a running suggest must leave alone, as plain data."""
    return {"intake": intake.project_refusal(conn, "garden"), "open": log.open_task_for(conn, "garden"),
            "what_now": whatnow.for_project(conn, "garden"), "project": status.projects_view(conn), "running": status._running(conn),
            "auto": auto.can_start(conn, "garden"), "run": auto.run_row_of(conn, "garden"),
            "open_tasks": [t["task_id"] for t in status.open_tasks(conn, None, None)]}


@pytest.mark.parametrize("state_name", ["fresh", "after_a_task"])
def test_a_running_suggest_leaves_every_reader_exactly_as_it_is(project, conn, state_name):
    if state_name == "after_a_task":
        task_id = "sr-20261102-120000-abcd"
        log.add_task(conn, task_id, "x", "ui", {"status": "ok", "label": "write", "confidence": 0.9, "tokens": 1}, project="garden")
        log.set_route(conn, task_id, agents=("claude", "chatgpt"), agent="claude", checker="chatgpt", route_reason="best",
                      check_state="pending")
        log.add_call(conn, f"{task_id}-1", task_id, "do", "claude", status="done", text="done")
        log.set_done(conn, task_id, "done", check_state="passed")
    before = _world(conn)
    row_id = "sr-20261102-130000-abcf"
    log.add_task(conn, row_id, "x", "cli", {"status": "not_asked", "tokens": 0}, mode="suggest", project="garden", run=runs.me())
    during = _world(conn)
    assert during == before
    log.set_failed(conn, row_id, "no idea in the shape")
    assert _world(conn) == before  # an ended suggest doesn't become the newest task for rungs (3) and (4)


def test_a_failed_call_writes_no_entry(project, conn):
    from router import safety
    before = projects.read_handoff(project)
    code, said, _ = _suggest(conn, Claude(safety.SafeError("claude exited 1")))
    assert code == 1 and projects.read_handoff(project) == before, said
    assert log.handoff_of(_row(conn)) in ([], None)


def test_a_zero_line_failure_writes_no_entry(project, conn):
    before = projects.read_handoff(project)
    _suggest(conn, Claude("nothing"))
    assert projects.read_handoff(project) == before


def test_a_line_that_is_no_list_line_is_dropped_and_counted(project, conn):
    code, said, _ = _suggest(conn, Claude("## Ideas\n- one\n* two\n"))
    assert _row(conn)["result"] == "1 added, 1 dropped: not a - line" and "two" not in said


def test_the_reads_are_under_the_projects_lock(project, conn, monkeypatch):
    held = []
    real = context.load

    def load(*a, **k):
        try:
            with locks.held("project-garden", folder=cli.DB_PATH.parent / runs.FOLDER_NAME, wait=False):
                held.append(False)
        except locks.Busy:
            held.append(True)
        return real(*a, **k)
    monkeypatch.setattr(context, "load", load)
    code, said, _ = _suggest(conn)
    assert held == [True] and code == 0, said


def test_it_gets_the_notes_and_the_memory_blocks(project, conn, monkeypatch):
    (project / "HANDOFF.md").write_text("the owner's notes words\n\n" + projects.read_handoff(project))
    code, said, w = _suggest(conn)
    assert "the owner's notes words" in w.prompts[0]
    assert memory.storable(_row(conn)) is False


def test_two_commands_starting_together_one_is_refused(project, conn):
    with locks.held("suggest-garden", folder=cli.DB_PATH.parent / runs.FOLDER_NAME):
        code, said, w = _suggest(conn)
    assert code == 2 and "already starting" in said and w.prompts == []


def test_auto_reads_through_the_same_open_task(project, conn):
    row_id = "sr-20261102-130000-abd0"
    log.add_task(conn, row_id, "x", "cli", {"status": "not_asked", "tokens": 0}, mode="suggest", project="garden")
    assert log.open_task_for(conn, "garden") is None


def test_a_route_goes_beside_a_running_suggest(project, conn):
    row_id = "sr-20261102-130000-abd1"
    log.add_task(conn, row_id, "x", "cli", {"status": "not_asked", "tokens": 0}, mode="suggest", project="garden")
    assert intake.project_refusal(conn, "garden") is None


def test_the_task_view_reads_as_unchecked_and_offers_no_rescue(project, conn):
    _suggest(conn)
    view = jsonview.task_view(conn, _row(conn), live=("claude",), loaded=None)
    assert view["outcome"] == "unchecked" and view["next"] == []
    assert view["mode"] == "suggest"
    json.dumps(view)


def test_the_builder_runs_it_as_a_list():
    assert page_commands.build({"action": "ideas_suggest", "name": "garden"}, {}).args == ("ideas", "--json", "garden", "--suggest")
