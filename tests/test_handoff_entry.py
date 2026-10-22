"""Build brief 18, phase D (rules v2.25, Project context): the checker judges `### Produced`; the task's result is
the deliverable without the `## Handoff` section while the build row keeps the whole text; the router writes the
entry into its block in HANDOFF.md when the task is delivered (passed or unchecked), a one-line entry when it
failed its check twice, stopped or came back, none on a cancel; the write is logged on the task row with the
file's line count; past 300 lines a warning. Fake agents only; every secret here is fake."""
from datetime import datetime, timezone

import pytest

from router import __main__ as cli
from router import checking, context, log, projects

from tests.helpers import set_local
from tests.test_collab import LOADED
from tests.test_context import ATTACKS, BUILT, HANDOFF_TEXT, SECTION, TASK, _relay, _route
from tests.test_handoff_contract import GOOD, HANDOFF, REVISED_BOTH
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_relay import CONFIG, GOOD_NOTE, ROSTER, Chat, RelayHook
from tests.test_resume_run import WRITING, claude_limit

QUICK = {**WRITING, "label": "quick_answer"}
GROK_SKILL = {**WRITING, "label": "x_social_pulse"}
NOW = datetime(2026, 10, 16, 22, 30, tzinfo=timezone.utc)
ENTRY = "Produced:\nnothing written: ## Lines, the two lines\nStatus:\nthe two lines exist\nNext:\nadd a third line"


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "config" / "projects.json")
    set_local(never_register=[str(tmp_path / "home" / "Projects" / "off-limits")])  # brief 25: a fake never_register folder
    folder = tmp_path / "demo"
    folder.mkdir()
    (folder / "HANDOFF.md").write_text(HANDOFF_TEXT)
    projects.add("demo", str(folder))
    return folder


def _file(project):
    return (project / "HANDOFF.md").read_text()


def _entries(project):
    return projects.entries_of(_file(project))


# ---------- the checker ----------

def test_the_checker_line_wording_is_decision_7():
    assert checking.CHECK_HANDOFF_LINE == (
        "The result ends with a `## Handoff` section. Judge its `### Produced` lines against the result: they must "
        "name what the result actually contains and where. A `Produced` that claims something the result does not "
        "contain, or omits what it does, is a failure and goes in your fix list. On a `nothing written` result, the "
        "heading or first line it names must be in the result and its clause must be true of it; a `Produced` that names "
        "nothing the result contains, or describes it wrongly, is a failure. The `## Handoff` section is a note, "
        "not part of the deliverable: never count it toward length or format.")


def test_the_checker_gets_the_line_before_the_blocks_and_the_count_excludes_the_section(project, conn):
    chat = Chat("PASS")
    code, out, row, _ = _route(conn, project="demo", worker=Scripted(GOOD), chatgpt=chat)
    assert code == 0, out
    prompt = chat.prompts[0]
    assert checking.CHECK_HANDOFF_LINE in prompt and prompt.index(checking.CHECK_HANDOFF_LINE) < prompt.index("===== TASK =====")
    assert "The result is 4 words." in prompt and "===== RESULT =====\n" + GOOD in prompt


def test_the_checker_of_a_grok_doer_or_a_plain_task_gets_no_line(project, conn):
    chat = Chat("PASS")
    _route(conn, project="demo", jev=GROK_SKILL, hook=Webhook(do="posts"), chatgpt=chat)
    assert checking.CHECK_HANDOFF_LINE not in chat.prompts[0]
    chat = Chat("PASS")
    _route(conn, worker=Scripted("two lines"), chatgpt=chat)
    assert checking.CHECK_HANDOFF_LINE not in chat.prompts[0]


def test_the_produced_path_check_is_dormant(conn):
    log.add_task(conn, "sr-p", TASK, "cli", WRITING, project="demo")
    section = "## Handoff\n### Produced\nmedia/out/sr-p/missing.png\n### Status\ns\n### Next\nn"
    assert context.produced_problems(log.get_task(conn, "sr-p"), section) == []


# ---------- the result and the row ----------

def test_the_task_result_has_no_handoff_while_the_build_row_keeps_the_whole_text(project, conn):
    code, out, row, _ = _route(conn, project="demo", worker=Scripted(GOOD), chatgpt=Chat("PASS"))
    assert row["result"] == "Line one.\nLine two." and "## Handoff" not in row["result"]
    assert log.get_call(conn, row["task_id"])["text"] == GOOD
    assert "## Handoff" not in out.split("done by claude:")[1].split("CHECKED")[0]


def test_a_redteam_result_has_neither_note_section_and_its_rows_keep_both(project, conn):
    worker = Scripted(BUILT, REVISED_BOTH)
    code, out, row, hook = _relay(conn, "redteam", project="demo", worker=worker, chatgpt=Chat(ATTACKS, "PASS"))
    assert code == 0 and row["result"] == "Line one, fixed.\nLine two."
    assert log.get_call(conn, row["task_id"] + "-s3")["text"] == REVISED_BOTH
    assert "--- answered ---\n2 the task asked for dull lines" in out and "## Handoff" not in out


# ---------- the entry ----------

def test_the_entry_is_written_on_pass_from_the_section_verbatim_apart_from_the_labels(project, conn, monkeypatch):
    monkeypatch.setattr(cli, "_now", lambda: NOW)
    code, out, row, _ = _route(conn, project="demo", worker=Scripted(GOOD), chatgpt=Chat("PASS"))
    assert code == 0, out
    entries = _entries(project)
    assert entries[0] == f"### #{row['n']} · 2026-10-16 · writing · claude\n{ENTRY}"
    assert len(entries) == 2 and entries[1].startswith("### #1 · 2026-10-16 · writing · claude")  # the fixture's own
    head, tail = _file(project).split(projects.START), _file(project).split(projects.END)
    assert head[0] == HANDOFF_TEXT.split(projects.START)[0] and tail[1] == "\n"
    writes = log.handoff_of(log.get_task(conn, row["task_id"]))
    assert len(writes) == 1 and writes[0]["kind"] == "entry" and writes[0]["text"] == entries[0]
    assert writes[0]["lines"] == 24 and writes[0]["block_start"] == 6
    assert f"HANDOFF.md: entry for #{row['n']} written (demo, 24 lines)." in out
    section_lines = HANDOFF.splitlines()[1:]
    assert [l for l in entries[0].splitlines()[1:] if not l.endswith(":")] == [l for l in section_lines if not l.startswith("###")]


def test_the_entry_comes_from_the_fixed_result_after_a_fix(project, conn):
    fixed = GOOD.replace("the two lines exist", "the two lines exist, fixed")
    code, out, row, _ = _route(conn, project="demo", worker=Scripted(GOOD, fixed), chatgpt=Chat("FIX\n1. fix it", "PASS"))
    assert row["check_state"] == "fixed"
    assert "Status:\nthe two lines exist, fixed\n" in _entries(project)[0] and len(_entries(project)) == 2


def test_the_entry_is_written_on_an_unchecked_delivery(project, conn):
    code, out, row, _ = _route(conn, project="demo", jev=QUICK, worker=Scripted(GOOD))
    assert row["check_state"] == "not_needed" and _entries(project)[0].startswith(f"### #{row['n']} · ")
    code, out, row, _ = _route(conn, project="demo", worker=Scripted(GOOD), chatgpt=Chat("no verdict here"))
    assert row["check_state"] == "unchecked" and _entries(project)[0].startswith(f"### #{row['n']} · ")
    assert "Produced:\nnothing written" in _entries(project)[0]


def test_a_relay_entry_names_the_preset(project, conn):
    code, out, row, hook = _relay(conn, "research-build", project="demo", worker=Scripted("built" + SECTION))
    assert code == 0 and _entries(project)[0].startswith(f"### #{row['n']} · ") and " · research-build · claude\n" in _entries(project)[0]


def test_a_grok_doer_gets_the_router_written_entry(project, conn, monkeypatch, tmp_path):
    from router import media
    monkeypatch.setattr(media, "MEDIA_ROOT", tmp_path / "media")
    hook = Webhook(do="Three posts about trays.", c1="PASS")
    code, out, row, _ = _route(conn, project="demo", jev=GROK_SKILL, hook=hook, chatgpt=Chat("PASS"))
    assert code == 0 and row["status"] == "done", out
    entry = _entries(project)[0]
    assert entry.endswith(f" · x_social_pulse · grok\nProduced:\nsr show {row['n']}\nStatus:\n—\nNext:\n—")
    media.save_output(row["task_id"], "pic.png", b"\x89PNG")
    out_lines = []
    cli._project_entry(conn, row["task_id"], out_lines.append, force=True)
    assert f"Produced:\nsr show {row['n']}\nmedia/out/{row['task_id']}/pic.png\nStatus:" in _entries(project)[0]


def test_failed_twice_writes_one_line_then_a_fallback_adds_an_entry_and_keeps_the_line(project, conn):
    worker, chat = Scripted(GOOD, GOOD), Chat("FIX\n1. rhyme", "FIX\n1. still no rhyme")
    code, out, row, _ = _route(conn, project="demo", worker=worker, chatgpt=chat)
    assert code == 5
    assert _entries(project)[0] == f"### #{row['n']} · {cli._now():%Y-%m-%d} · failed: not passed after one fix round"
    lines, clock, hook, redo = [], Clock(), Webhook(), Chat("REDO\n\n" + HANDOFF)
    code = cli.cmd_fallback([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                            settings_paths=[], post=hook.post, worker=Scripted("PASS"), chatgpt=redo,
                            codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep,
                            clock=clock, wait=True, out=lines.append)
    assert code == 0
    entries = _entries(project)
    assert entries[0].startswith(f"### #{row['n']} · ") and " · writing · chatgpt\nProduced:" in entries[0]
    assert entries[1].endswith("· failed: not passed after one fix round") and len(entries) == 3
    assert [w["kind"] for w in log.handoff_of(log.get_task(conn, row["task_id"]))] == ["line", "entry"]


def test_a_failed_first_call_writes_a_failed_line(project, conn):
    code, out, row, _ = _route(conn, project="demo", worker=Scripted(RuntimeError("boom")))
    assert row["status"] == "failed"
    assert _entries(project)[0] == f"### #{row['n']} · {cli._now():%Y-%m-%d} · failed: unexpected error: RuntimeError"


def test_a_plan_limit_stop_writes_a_stopped_line_and_the_resume_writes_one_entry(project, conn):
    code, out, row, _ = _route(conn, project="demo", worker=Scripted(claude_limit()))
    assert _entries(project)[0] == (f"### #{row['n']} · {cli._now():%Y-%m-%d} · stopped: plan limit on claude: "
                                    "You've hit your session limit · resets 3pm")
    lines, clock, hook, chat = [], Clock(), Webhook(), Chat(GOOD)
    code = cli.cmd_resume([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                          settings_paths=[], post=hook.post, worker=Scripted("PASS"), chatgpt=chat,
                          codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                          wait=True, out=lines.append)
    assert code == 0
    entries = _entries(project)
    assert " · writing · chatgpt\nProduced:" in entries[0] and entries[1].endswith("resets 3pm") and len(entries) == 3


def test_a_relay_stop_writes_a_stopped_line(project, conn):
    code, out, row, hook = _relay(conn, "research-build", project="demo", worker=Scripted("built", "built again"))
    assert row["status"] == "failed"
    assert _entries(project)[0] == (f"### #{row['n']} · {cli._now():%Y-%m-%d} · stopped: relay failed at stage 2 (build by "
                                    "claude): contract still missing after the re-ask: Handoff: section `## Handoff` is missing")


def test_a_contract_miss_on_a_routed_doer_writes_a_failed_line(project, conn):
    code, out, row, _ = _route(conn, project="demo", worker=Scripted("one", "two"))
    assert _entries(project)[0].endswith("· failed: contract still missing after the re-ask: Handoff: section `## Handoff` is missing")


def test_a_task_that_came_back_writes_a_stopped_line(project, conn):
    (project / "HANDOFF.md").write_text(HANDOFF_TEXT + "\nJEV_API_KEY=abcdefghijklmnop\n")
    code, out, row, _ = _route(conn, project="demo")
    assert code == 4
    assert _entries(project)[0] == f"### #{row['n']} · {cli._now():%Y-%m-%d} · stopped: handoff line 18 looks like a key"
    assert "JEV_API_KEY=abcdefghijklmnop" in _file(project)  # The owner's part is theirs; the router wrote only its block
    (project / "HANDOFF.md").write_text(HANDOFF_TEXT)
    code, out, row, _ = _route(conn, project="demo", jev={**WRITING, "status": "below_floor", "confidence": 0.2})  # no terminal
    assert code == 4 and _entries(project)[0] == f"### #{row['n']} · {cli._now():%Y-%m-%d} · stopped: needs your label"


def test_a_timed_out_grok_task_writes_a_stopped_line(project, conn):
    hook = Webhook()
    code, out, row, _ = _route(conn, project="demo", jev=GROK_SKILL, hook=hook, wait=False)
    assert row["status"] == "sent"
    lines = []
    cli.cmd_check(conn=conn, config=CONFIG, fetch=hook.fetch, close=hook.close, now=NOW.replace(year=2027),
                  presets=LOADED, roster=ROSTER, out=lines.append)
    assert log.get_task(conn, row["task_id"])["status"] == "timed_out"
    assert _entries(project)[0] == f"### #{row['n']} · {cli._now():%Y-%m-%d} · stopped: timed out"


def test_a_cancelled_task_gets_no_entry(project, conn):
    hook = Webhook()
    code, out, row, _ = _route(conn, project="demo", jev=GROK_SKILL, hook=hook, wait=False)
    before = _file(project)
    cli.cmd_cancel(conn=conn, words=[str(row["n"])], out=lambda *_: None)
    assert log.get_task(conn, row["task_id"])["status"] == "cancelled" and _file(project) == before
    assert log.handoff_of(log.get_task(conn, row["task_id"])) == []


def test_a_write_happens_once_per_ending(project, conn):
    code, out, row, _ = _route(conn, project="demo", worker=Scripted(GOOD), chatgpt=Chat("PASS"))
    lines = []
    cli._project_entry(conn, row["task_id"], lines.append)
    cli._project_entry(conn, row["task_id"], lines.append)
    assert lines == [] and len(_entries(project)) == 2 and len(log.handoff_of(log.get_task(conn, row["task_id"]))) == 1


def test_the_size_warning_prints_after_a_write_past_300_lines(project, conn):
    (project / "HANDOFF.md").write_text("x\n" * 295 + f"{projects.START}\n{projects.END}\n")
    code, out, row, _ = _route(conn, project="demo", worker=Scripted(GOOD), chatgpt=Chat("PASS"))
    assert code == 0
    assert "HANDOFF.md is 306 lines (the router warns past 300); the router's block starts at line 296." in out
    assert log.handoff_of(log.get_task(conn, row["task_id"]))[0]["lines"] == 306


def test_after_nine_deliveries_the_block_keeps_eight_and_the_first_section_is_still_on_its_row(project, conn):
    (project / "HANDOFF.md").write_text(f"{projects.START}\n{projects.END}\n")
    rows = []
    for i in range(9):
        good = GOOD.replace("the two lines exist", f"delivery {i}")
        code, out, row, _ = _route(conn, project="demo", worker=Scripted(good), chatgpt=Chat("PASS"))
        assert code == 0, out
        rows.append(row)
    entries = _entries(project)
    assert len(entries) == 8 and "delivery 0" not in _file(project) and entries[0].count("delivery 8") == 1
    first = log.get_task(conn, rows[0]["task_id"])
    assert "delivery 0" in log.get_call(conn, first["task_id"])["text"]  # the build row keeps the whole text
    assert log.handoff_of(first)[0]["text"].endswith("Status:\ndelivery 0\nNext:\nadd a third line")  # and the write record


def test_a_project_removed_before_delivery_is_said_and_nothing_is_written(project, conn):
    class Removing(Scripted):
        def __call__(self, prompt):
            projects.remove("demo")
            return super().__call__(prompt)
    code, out, row, _ = _route(conn, project="demo", worker=Removing(GOOD), chatgpt=Chat("PASS"))
    assert code == 4 and row["status"] == "returned"  # the next call could not read the handoff: back to the owner
    assert "no project demo" in out and _file(project) == HANDOFF_TEXT
