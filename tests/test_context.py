"""Build brief 18, phase B (rules v2.25, Project context): intake and the handoff in the prompt. The handoff is
read fresh at every call, redacted, scanned for anything that still looks like a key, then pasted as the last
block of every agent call on the task (never Jev); on a Grok call it is trimmed to fit the prompt limit, never
failed. `--project` and `--chat` are judged at intake before any row. Fake agents only; every secret here is fake."""
import json
from pathlib import Path

import pytest

from router import __main__ as cli
from router import checking, context, log, projects, relay, safety, settings
from tests.helpers import fake_label, set_local
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_collab import LOADED
from tests.test_relay import CONFIG, GOOD_NOTE, ROSTER, SECRET, Chat, RelayHook
from tests.test_resume_run import WRITING, claude_limit

START, END = projects.START, projects.END
TASK = "Write two lines about seed trays."
ENTRY = "### #1 · 2026-10-16 · writing · claude\nProduced:\nnothing written\nStatus:\nstarted\nNext:\nmore"
HANDOFF_TEXT = f"# Demo project\n\nThe owner's note one.\nThe owner's note two.\n\n{START}\n\n{ENTRY}\n\n{END}\n"
ATTACKS = "## Attacks\n1. [high] Line one is wrong.\n2. [low] Line two is dull.\n3. [medium] No source.\n\n## Strongest\n1"
BUILT = "## Deliverable\nLine one.\nLine two.\n\n## Unfinished\nnone"
SECTION = "\n\n## Handoff\n### Produced\nnothing written: ## Lines, two lines about trays\n### Status\nok\n### Next\nmore"  # phase C: the build contract (named, rules v2.27)
REVISED = "Line one, fixed.\nLine two.\n\n## Answered\n2 the task asked for dull lines" + SECTION


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A registered project `demo` with a handoff file; returns its folder."""
    monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "config" / "projects.json")
    set_local(never_register=[str(tmp_path / "home" / "Projects" / "off-limits")])  # brief 25: a fake never_register folder
    folder = tmp_path / "demo"
    folder.mkdir()
    (folder / "HANDOFF.md").write_text(HANDOFF_TEXT)
    projects.add("demo", str(folder))
    return folder


@pytest.fixture
def limit(monkeypatch, tmp_path):
    def set_limit(value):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"grok_prompt_limit": value}))
        monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    return set_limit


def _block(text, name="demo"):
    return f"===== project handoff: {name} =====\n{text}\n===== end handoff =====\n\n{context.BLOCK_LINE}"


def _route(conn, task=TASK, *, project=None, jev=WRITING, worker=None, chatgpt=None, hook=None, wait=True):
    lines, clock, hook = [], Clock(), hook or Webhook()
    label = fake_label(jev)
    code = cli.cmd_route(task, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=label,
                         post=hook.post, worker=worker or Scripted(), chatgpt=chatgpt or Chat("PASS"),
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=wait, out=lines.append, project=project)
    rows = log.recent_tasks(conn)
    return code, "\n".join(lines), rows[0] if rows else None, label


def _relay(conn, preset, task=TASK, *, project=None, worker=None, chatgpt=None, hook=None, slots=(), wait=True):
    lines, clock, hook = [], Clock(), hook or RelayHook(s1=GOOD_NOTE)
    code = cli.cmd_relay(preset, task, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                         settings_paths=[], post=hook.post, worker=worker or Scripted(), chatgpt=chatgpt or Chat("PASS"),
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=wait, slots=list(slots), out=lines.append, project=project)
    rows = log.recent_tasks(conn)
    return code, "\n".join(lines), rows[0] if rows else None, hook


# ---------- the key scan ----------

@pytest.mark.parametrize("line", [
    "JEV_API_KEY=abcdef1234567890",
    "GROK_WEBHOOK_KEY: 'abcdef1234567890'",
    "api_key = sk_live_abcdefghijklmnop",
    "token: ghp_abcdefghijklmnopqrstuvwxyz0123",
    "password=hunter2hunter2",
    "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9abc",
    "use sk-abcdefghijklmnopqrstuvwxyz for it",
    "AKIAABCDEFGHIJKLMNOP",
    "AIzaSyA-abcdefghijklmnopqrstuvwxyz01234",
    "xoxb-123456789012-abcdefghijkl",
    "https://example.invalid/hook?key=abcdef123456",
    "webhook_url=https://example.invalid/x/abcdef",
])
def test_key_like_catches_a_key_shaped_line_and_names_it(line):
    text = f"# Notes\n\n```\n{line}\n```\nmore\n"
    assert safety.key_like(text) == 4


@pytest.mark.parametrize("line", [
    "JEV_API_KEY=[REDACTED]",
    "the key lives in .env, never here",
    "token: 5",
    "password: see the vault",
    "secret: nobody",
    "A sentence about api keys in general.",
    "https://example.invalid/page?id=12345678",
    "JEV_API_KEY is set in .env",
])
def test_key_like_leaves_prose_and_redacted_values_alone(line):
    assert safety.key_like(f"a\n{line}\nb\n") is None


def test_key_like_names_the_first_matching_line():
    assert safety.key_like("ok\nJEV_API_KEY=abcdefghij\nJEV_API_KEY=klmnopqrst\n") == 2


# ---------- context.load: fresh, redacted, scanned ----------

def test_load_reads_the_file_fresh_each_time(project):
    first = context.load("demo", [SECRET])
    (project / "HANDOFF.md").write_text(HANDOFF_TEXT.replace("note two", "note two, edited"))
    second = context.load("demo", [SECRET])
    assert "note two, edited" in second.text and "edited" not in first.text
    assert (first.project, first.total) == ("demo", 16)


def test_load_redacts_a_real_secret_value(project):
    (project / "HANDOFF.md").write_text(HANDOFF_TEXT.replace("note one", f"note one {SECRET}"))
    found = context.load("demo", [SECRET])
    assert SECRET not in found.text and "[REDACTED]" in found.text


def test_load_refuses_a_handoff_that_still_looks_like_it_holds_a_key(project):
    (project / "HANDOFF.md").write_text(HANDOFF_TEXT.replace("note two.", "note two.\nJEV_API_KEY=abcdefghijklmnop"))
    with pytest.raises(context.ContextRefused) as e:
        context.load("demo", [SECRET])
    assert e.value.line == 5 and "line 5" in str(e.value) and "abcdefghijklmnop" not in str(e.value)


def test_load_refuses_an_unregistered_project_or_a_missing_file(project):
    with pytest.raises(projects.ProjectError, match="no project other"):
        context.load("other", [])
    (project / "HANDOFF.md").unlink()
    with pytest.raises(projects.ProjectError, match="HANDOFF.md is missing"):
        context.load("demo", [])


# ---------- context.attach: the block, last ----------

def test_attach_puts_the_block_last_with_the_data_line_after_it(project, conn):
    log.add_task(conn, "sr-p", TASK, "cli", WRITING, project="demo")
    prompt, record, _ = context.attach("the prompt", log.get_task(conn, "sr-p"), "claude", [SECRET])
    assert prompt == "the prompt\n\n" + _block(HANDOFF_TEXT.rstrip("\n"))
    assert record == {"project": "demo", "lines": 16, "total": 16, "text": HANDOFF_TEXT.rstrip("\n")}


def test_attach_leaves_a_task_without_a_project_alone(conn):
    log.add_task(conn, "sr-n", TASK, "cli", WRITING)
    assert context.attach("the prompt", log.get_task(conn, "sr-n"), "claude", []) == ("the prompt", None, None)


def test_claude_and_chatgpt_calls_are_never_trimmed(project, conn, limit):
    limit(50)
    log.add_task(conn, "sr-p", TASK, "cli", WRITING, project="demo")
    for agent in ("claude", "chatgpt"):
        prompt, record, _ = context.attach("the prompt", log.get_task(conn, "sr-p"), agent, [])
        assert record["lines"] == 16 and HANDOFF_TEXT.rstrip("\n") in prompt


def test_a_grok_call_that_fits_gets_the_whole_handoff(project, conn, limit):
    limit(2000)
    log.add_task(conn, "sr-p", TASK, "cli", WRITING, project="demo")
    prompt, record, _ = context.attach("the prompt", log.get_task(conn, "sr-p"), "grok", [])
    assert record["lines"] == 16 and len(prompt) <= 2000


def _lines(text):
    return text.splitlines()


def test_a_grok_call_cuts_the_owners_part_from_the_top_line_by_line_and_keeps_the_block(project, conn, limit):
    log.add_task(conn, "sr-p", TASK, "cli", WRITING, project="demo")
    row = log.get_task(conn, "sr-p")
    whole = context.attach("p", row, "claude", [])[0]
    limit(len(whole) - 1)  # one character short of the whole handoff
    prompt, record, _ = context.attach("p", row, "grok", [])
    sent = _lines(record["text"])
    assert sent == _lines(HANDOFF_TEXT)[1:] and record["lines"] == 15 and len(prompt) <= len(whole) - 1
    limit(len("p\n\n" + _block("\n".join(_lines(HANDOFF_TEXT)[5:]))))  # room for the block alone
    prompt, record, _ = context.attach("p", row, "grok", [])
    assert _lines(record["text"]) == _lines(HANDOFF_TEXT)[5:] and _lines(record["text"])[0] == START
    assert ENTRY in record["text"] and record["lines"] == 11


def test_a_grok_call_whose_block_alone_does_not_fit_loses_its_oldest_entries_first(project, conn, limit):
    e2 = ENTRY.replace("#1", "#2").replace("started", "second")
    e3 = ENTRY.replace("#1", "#3").replace("started", "third")
    (project / "HANDOFF.md").write_text(f"{START}\n\n{e3}\n\n{e2}\n\n{ENTRY}\n\n{END}\n")
    log.add_task(conn, "sr-p", TASK, "cli", WRITING, project="demo")
    row = log.get_task(conn, "sr-p")
    two = f"{START}\n\n{e3}\n\n{e2}\n\n{END}"
    limit(len("p\n\n" + _block(two)))
    prompt, record, _ = context.attach("p", row, "grok", [])
    assert record["text"] == two and record["lines"] == 19 and ENTRY not in prompt
    one = f"{START}\n\n{e3}\n\n{END}"
    limit(len("p\n\n" + _block(one)))
    prompt, record, _ = context.attach("p", row, "grok", [])
    assert record["text"] == one and e2 not in prompt


def test_a_grok_call_that_cannot_fit_one_entry_leaves_the_handoff_out_and_says_so(project, conn, limit):
    limit(len("p") + 40)
    log.add_task(conn, "sr-p", TASK, "cli", WRITING, project="demo")
    prompt, record, _ = context.attach("p", log.get_task(conn, "sr-p"), "grok", [])
    assert prompt == "p" and record == {"project": "demo", "left_out": True, "total": 16}


def test_the_trim_never_changes_the_file(project, conn, limit):
    before = (project / "HANDOFF.md").read_bytes()
    log.add_task(conn, "sr-p", TASK, "cli", WRITING, project="demo")
    limit(60)
    context.attach("p", log.get_task(conn, "sr-p"), "grok", [])
    assert (project / "HANDOFF.md").read_bytes() == before


def test_crlf_in_the_file_reaches_the_prompt_as_plain_newlines(project, conn):
    (project / "HANDOFF.md").write_bytes(HANDOFF_TEXT.replace("\n", "\r\n").encode())
    log.add_task(conn, "sr-p", TASK, "cli", WRITING, project="demo")
    prompt, record, _ = context.attach("p", log.get_task(conn, "sr-p"), "claude", [])
    assert "\r" not in prompt and record["text"] == HANDOFF_TEXT.rstrip("\n")


# ---------- sr route --project ----------

def test_a_routed_project_task_carries_the_block_on_the_doer_the_checker_and_the_fix(project, conn):
    worker, chat = Scripted("two lines" + SECTION, "two better lines" + SECTION), Chat("FIX\n1. make it rhyme", "PASS")
    code, out, row, label = _route(conn, project="demo", worker=worker, chatgpt=chat)
    assert code == 0, out
    assert row["project"] == "demo" and row["status"] == "done" and row["check_state"] == "fixed"
    block = _block(HANDOFF_TEXT.rstrip("\n"))
    assert worker.prompts[0] == f"{TASK}\n\n{context.HANDOFF_LINE}\n\n{block}"  # the doer: the task, the line, the block last
    assert worker.prompts[1].endswith("\n\n" + block)                      # the fix round
    assert all(p.endswith("\n\n" + block) for p in chat.prompts)          # the check and the re-check
    assert chat.prompts[0].count("===== project handoff: demo =====") == 1
    for call in log.calls_for(conn, row["task_id"]):
        assert log.context_of(call) == {"project": "demo", "lines": 16, "total": 16, "text": HANDOFF_TEXT.rstrip("\n")}


def test_the_doer_prompt_without_a_project_is_byte_for_byte_as_before(conn):
    worker = Scripted("two lines")
    _route(conn, worker=worker, chatgpt=Chat("PASS"))
    assert worker.prompts[0] == TASK
    assert all(log.context_of(c) is None for c in log.calls_for(conn, log.recent_tasks(conn)[0]["task_id"]))


def test_jev_gets_the_same_text_with_and_without_a_project(project, conn):
    _, _, _, with_project = _route(conn, project="demo", worker=Scripted("x"))
    _, _, _, without = _route(conn, worker=Scripted("x"))
    assert with_project.calls[0]["task"] == without.calls[0]["task"] == TASK
    assert "handoff" not in json.dumps(with_project.calls).lower()


def test_the_handoff_is_read_again_before_every_call(project, conn):
    class Editing(Scripted):
        def __call__(self, prompt):
            (project / "HANDOFF.md").write_text(HANDOFF_TEXT.replace("note one", "note one, edited by the owner"))
            return super().__call__(prompt)
    chat = Chat("PASS")
    _route(conn, project="demo", worker=Editing("two lines" + SECTION), chatgpt=chat)
    assert "edited by the owner" in chat.prompts[0]


def test_a_key_like_line_in_the_handoff_returns_the_task_before_any_call(project, conn):
    (project / "HANDOFF.md").write_text(HANDOFF_TEXT.replace("note two.", "note two.\nJEV_API_KEY=abcdefghijklmnop"))
    worker, label = Scripted("x"), None
    code, out, row, label = _route(conn, project="demo", worker=worker)
    assert code == 4 and worker.prompts == [] and label.calls, out
    assert row["status"] == "returned" and row["check_note"] == "handoff line 5 looks like a key"
    assert row["route_reason"] == "returned: handoff line 5 looks like a key" and row["agent"] == "claude"
    assert f"{row['task_id']} came back to you: the project's handoff holds something that looks like a key at line 5 " \
           f"(HANDOFF.md in {project.resolve()}). Nothing was sent. Fix the line and run the task again." in out
    assert "abcdefghijklmnop" not in out and log.calls_for(conn, row["task_id"]) == []


def test_a_key_like_line_added_between_calls_returns_the_task_mid_chain(project, conn):
    hook = RelayHook(s1=GOOD_NOTE)
    code, out, row, hook = _relay(conn, "research-build", project="demo", hook=hook, wait=False)
    assert code == 0 and row["status"] == "sent" and len(hook.sent) == 1
    (project / "HANDOFF.md").write_text(HANDOFF_TEXT + "\nJEV_API_KEY=abcdefghijklmnop\n")
    worker, lines = Scripted("built"), []
    cli.cmd_check(conn=conn, config=CONFIG, fetch=hook.fetch, close=hook.close, post=hook.post, worker=worker,
                  chatgpt=Chat("PASS"), codex_login=lambda: True, presets=LOADED, roster=ROSTER, out=lines.append)
    row = log.get_task(conn, row["task_id"])
    assert worker.prompts == [] and row["status"] == "returned"
    assert row["check_note"] == "handoff line 18 looks like a key"
    assert [c["kind"] for c in log.calls_for(conn, row["task_id"])] == ["stage"]


def test_a_handoff_file_deleted_between_calls_returns_the_task(project, conn):
    class Deleting(Scripted):
        def __call__(self, prompt):
            (project / "HANDOFF.md").unlink()
            return super().__call__(prompt)
    chat = Chat("PASS")
    code, out, row, _ = _route(conn, project="demo", worker=Deleting("two lines"), chatgpt=chat)
    assert code == 4 and chat.prompts == [] and row["status"] == "returned"
    assert row["check_note"].startswith("HANDOFF.md is missing from")


# ---------- refusals at intake ----------

def test_an_unknown_project_is_refused_with_the_list(project, conn):
    code, out, row, label = _route(conn, project="other")
    assert code == 2 and row is None and label.calls == []
    assert out == "Refused: no project other. Projects: demo (sr project list). Nothing was logged or sent."


def test_an_unknown_project_on_an_empty_registry_says_so(project, conn):
    projects.remove("demo")
    code, out, row, _ = _route(conn, project="demo")
    assert code == 2 and row is None
    assert out == "Refused: no project demo: the registry is empty (sr project add <name> <path>). Nothing was logged or sent."


def test_an_override_with_a_project_is_refused(project, conn):
    code, out, row, label = _route(conn, "@grok " + TASK, project="demo")
    assert code == 2 and row is None and label.calls == []
    assert out == ("Refused: an override prefix with --project is refused (@grok): an override may run unchecked, and a "
                   "project's handoff is never written unchecked. Nothing was logged or sent.")


def test_a_missing_handoff_file_is_refused_at_intake(project, conn):
    (project / "HANDOFF.md").unlink()
    code, out, row, label = _route(conn, project="demo")
    assert code == 2 and row is None and label.calls == []
    assert out == f"Refused: project demo: HANDOFF.md is missing from {project.resolve()}. Nothing was logged or sent."


def test_a_second_project_task_is_refused_while_one_is_open_and_allowed_after_a_cancel(project, conn):
    code, out, first, _ = _route(conn, project="demo", hook=Webhook(), worker=Scripted("x"), wait=False,
                                 jev={**WRITING, "label": "x_social_pulse"})
    assert code == 0 and first["status"] == "sent", out  # a Grok task out: open
    code, out, row, label = _route(conn, project="demo")
    assert code == 2 and label.calls == [] and row["task_id"] == first["task_id"]
    assert out == (f"Refused: project demo has task {first['n']} open (sent). Finish or cancel it first. "
                   "Nothing was logged or sent.")
    cli.cmd_cancel(conn=conn, words=[str(first["n"])], out=lambda *_: None)
    code, out, row, _ = _route(conn, project="demo", worker=Scripted("x" + SECTION))
    assert code == 0 and row["task_id"] != first["task_id"] and row["project"] == "demo"


def test_a_returned_project_task_does_not_block_the_next(project, conn):
    (project / "HANDOFF.md").write_text(HANDOFF_TEXT + "\nJEV_API_KEY=abcdefghijklmnop\n")
    code, _, first, _ = _route(conn, project="demo")
    assert code == 4 and first["status"] == "returned"
    (project / "HANDOFF.md").write_text(HANDOFF_TEXT)
    code, out, row, _ = _route(conn, project="demo", worker=Scripted("x" + SECTION))
    assert code == 0 and row["task_id"] != first["task_id"]


@pytest.mark.parametrize("preset", ["collab", "versus", "vote"])
def test_project_is_refused_on_collab_versus_and_vote(project, conn, preset):
    code, out, row, hook = _relay(conn, preset, project="demo")
    assert code == 2 and row is None and hook.sent == []
    assert out == f"Refused: --project is not allowed on {preset} (research-build and redteam only). Nothing was logged or sent."


def test_project_is_refused_on_sr_split(project, monkeypatch, tmp_path, capsys):
    assert cli.main(["split", "--project", "demo", "plan this"], platform="darwin") == 2
    assert capsys.readouterr().out == ("Refused: --project on sr split is refused in version 2; pieces carry no project. "
                                       "Nothing was logged or sent.\n")


def test_relay_keeps_project_out_of_the_slot_flags():
    rest, found = cli._take_slot_flags(["relay", "redteam", "--project", "demo", "--build", "chatgpt", "task"])
    assert rest == ["relay", "redteam", "--project", "demo", "task"] and found == [("build", "chatgpt")]
    rest, found = cli._take_slot_flags(["relay", "redteam", "--project=demo", "task"])
    assert rest == ["relay", "redteam", "--project=demo", "task"] and found == []


def test_project_and_chat_are_reserved_slot_names():
    from router import presets
    assert "project" in presets.RESERVED_SLOT_NAMES and "chat" in presets.RESERVED_SLOT_NAMES


# ---------- relay: every stage ----------

def test_every_research_build_stage_and_the_check_carry_the_block(project, conn):
    worker, chat = Scripted("built" + SECTION), Chat("PASS")
    hook = RelayHook(s1=GOOD_NOTE)
    code, out, row, hook = _relay(conn, "research-build", project="demo", worker=worker, chatgpt=chat, hook=hook)
    assert code == 0, out
    block = _block(HANDOFF_TEXT.rstrip("\n"))
    assert hook.sent[0]["task"].endswith("\n\n" + block)                                   # stage 1, grok
    assert worker.prompts[0] == relay.prompt_for("build", TASK, GOOD_NOTE, handoff=True) + "\n\n" + block  # stage 2, after the note
    assert chat.prompts[0].endswith("\n\n" + block)                                        # the check
    assert all(log.context_of(c)["lines"] == 16 for c in log.calls_for(conn, row["task_id"]))


def test_every_redteam_stage_carries_the_block_the_revise_stage_after_its_attack_and_own_result(project, conn):
    worker, chat = Scripted(BUILT, REVISED), Chat(ATTACKS, "PASS")
    code, out, row, hook = _relay(conn, "redteam", project="demo", worker=worker, chatgpt=chat)
    assert code == 0, out
    block = _block(HANDOFF_TEXT.rstrip("\n"))
    assert worker.prompts[0].endswith("\n\n" + block) and chat.prompts[0].endswith("\n\n" + block)
    revise = worker.prompts[1]
    assert revise.endswith("\n\n" + block)
    assert revise.index("===== ATTACK LIST =====") < revise.index("===== YOUR EARLIER RESULT =====") < revise.index(block)
    assert chat.prompts[1].endswith("\n\n" + block)  # the checker, after the attack list block
    assert chat.prompts[1].index("ATTACK LIST (written by the attacker") < chat.prompts[1].index(block)


def test_a_stage_reask_carries_the_block_too(project, conn):
    thin = "## Findings\n- one\n\n## Sources\n- https://x.com/a/1\n\n## Gaps\nnone"
    hook = RelayHook(s1=thin, s1r=GOOD_NOTE)
    code, out, row, hook = _relay(conn, "research-build", project="demo", hook=hook, worker=Scripted("built" + SECTION))
    assert code == 0 and len(hook.sent) == 2
    assert hook.sent[1]["task"].endswith("\n\n" + _block(HANDOFF_TEXT.rstrip("\n")))


# ---------- Grok: trimmed, never failed; `limited=` still applies after ----------

def test_a_grok_stage_gets_a_trimmed_handoff_and_the_row_says_how_many_lines(project, conn, limit):
    base = relay.prompt_for("research", TASK, None)
    limit(len(base) + len("\n\n" + _block("\n".join(HANDOFF_TEXT.splitlines()[5:]))))
    code, out, row, hook = _relay(conn, "research-build", project="demo", worker=Scripted("built" + SECTION))
    assert code == 0, out
    sent = hook.sent[0]["task"]
    assert sent.startswith(base) and START in sent and "The owner's note" not in sent
    record = log.context_of(log.calls_for(conn, row["task_id"])[0])
    assert (record["lines"], record["total"]) == (11, 16)


def test_a_grok_stage_whose_handoff_cannot_fit_sends_without_it_and_is_never_failed(project, conn, limit):
    base = relay.prompt_for("research", TASK, None)
    limit(len(base) + 10)
    code, out, row, hook = _relay(conn, "research-build", project="demo", worker=Scripted("built" + SECTION))
    assert code == 0, out
    assert hook.sent[0]["task"] == base
    assert log.context_of(log.calls_for(conn, row["task_id"])[0]) == {"project": "demo", "left_out": True, "total": 16}
    assert row["status"] == "done"


def test_a_grok_build_stage_past_the_limit_after_the_trim_still_fails_as_today(project, conn, limit):
    base = relay.prompt_for("build", TASK, GOOD_NOTE)
    limit(len(base) - 1)
    code, out, row, hook = _relay(conn, "research-build", project="demo", slots=[("build", "grok")])
    assert code == 1 and row["status"] == "failed" and row["failed_stage"] == 2
    assert f"too long for Grok ({len(base)} characters)" in out and len(hook.sent) == 1


# ---------- resume and fallback ----------

def test_the_substitute_on_a_resume_gets_the_block(project, conn):
    code, out, row, _ = _route(conn, project="demo", worker=Scripted(claude_limit()))
    assert row["status"] == "failed"
    lines, clock, hook, chat = [], Clock(), Webhook(), Chat("two lines" + SECTION)
    code = cli.cmd_resume([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                          settings_paths=[], post=hook.post, worker=Scripted("PASS"), chatgpt=chat,
                          codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                          wait=True, out=lines.append)
    assert code == 0, "\n".join(lines)
    now = log.context_of(log.get_call(conn, f"{row['task_id']}-resume"))["text"]  # as sent: the stop line is in it (phase D)
    assert "stopped: plan limit on claude" in now
    assert chat.prompts[0] == f"{TASK}\n\n{checking.SEARCH_LINE_GENERAL}\n\n{context.HANDOFF_LINE}\n\n" + _block(now)
    resumed = log.get_call(conn, f"{row['task_id']}-resume")
    assert log.context_of(resumed)["lines"] == 18  # the file plus the stop line and its blank line


def test_a_resume_is_refused_before_any_call_when_the_handoff_looks_like_a_key(project, conn):
    code, out, row, _ = _route(conn, project="demo", worker=Scripted(claude_limit()))
    (project / "HANDOFF.md").write_text(HANDOFF_TEXT + "\nJEV_API_KEY=abcdefghijklmnop\n")
    lines, clock, hook, chat = [], Clock(), Webhook(), Chat("two lines")
    code = cli.cmd_resume([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                          settings_paths=[], post=hook.post, worker=Scripted(), chatgpt=chat, codex_login=lambda: True,
                          fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True, out=lines.append)
    assert code == 2 and chat.prompts == []
    assert lines[-1] == (f"Refused: #{row['n']} can't be resumed: the project's handoff holds something that looks like a "
                         "key at line 18. Nothing was logged or sent.")
    assert log.get_task(conn, row["task_id"])["status"] == "failed"


def test_the_fallback_doer_gets_the_block_after_the_fix_list(project, conn):
    worker, chat = Scripted("FIRST two lines" + SECTION, "FIXED two lines" + SECTION), Chat("FIX\n1. rhyme", "FIX\n1. still no rhyme")
    code, out, row, _ = _route(conn, project="demo", worker=worker, chatgpt=chat)
    assert row["check_state"] == "failed"
    lines, clock, hook, redo = [], Clock(), Webhook(), Chat("REDO two lines" + SECTION)
    code = cli.cmd_fallback([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                            settings_paths=[], post=hook.post, worker=Scripted("PASS"), chatgpt=redo,
                            codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep,
                            clock=clock, wait=True, out=lines.append)
    assert code == 0, "\n".join(lines)
    block = _block(log.context_of(log.get_call(conn, f"{row['task_id']}-fb1"))["text"])  # as sent (phase D: the failed line)
    assert "failed: not passed after one fix round" in block
    assert redo.prompts[0].endswith("\n\n" + block) and redo.prompts[0].index("===== FIX LIST =====") < redo.prompts[0].index(block)
    assert log.context_of(log.get_call(conn, f"{row['task_id']}-fb1"))["lines"] == 18  # plus the failed line
