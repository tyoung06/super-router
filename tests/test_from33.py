"""Build brief 33, F (decisions 8 to 12 and 17): Build from this. `--from <task>` on `sr route` and `sr relay` names an
earlier task whose delivered result the new task carries as data. Refused at intake, before Jev and with nothing written
(`bad_from`), when the source isn't in the log, isn't delivered with a text result, or is forgotten; a second `--from` is
`usage`, and `--from` on `sr split` is `flag_refused`. The block (the source's result as `sr show` prints it, without
`## Handoff` and `## Next`, through the redactor, cut at `from_max` at a line end, labeled) goes after the task and before
the handoff and memory blocks on every call; a check, re-check, review or attack also gets the check line; the call row
keeps it as sent; the memory block leaves the source out; Grok's limit refuses a relay at intake and returns a routed task
after its label; `--answers` carries it; `from` and `from_given` in the JSON; the page's builder. Fake agents only; every
value here is fake."""
import json

import pytest

from router import __main__ as cli
from router import checking, context, fromblock, jsonview, log, memory, page_commands, settings
from tests.fake_hindsight import FakeHindsight
from tests.helpers import fake_label
from tests.test_collab import LOADED
from tests.test_json_actions import World, jev
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_memory_block import _done
from tests.test_relay import CONFIG, GOOD_NOTE, ROSTER, SECRET, Chat, RelayHook

WRITING = {"status": "ok", "label": "writing", "confidence": 0.95, "needs_split": 0.1, "tokens": 0}
XPULSE = {"status": "ok", "label": "x_social_pulse", "confidence": 0.95, "needs_split": 0.1, "tokens": 0}
TASK = "Write a planting calendar from the tray sizes."
SOURCE_TEXT = "Three tray sizes: 72-cell for brassicas, 128-cell for lettuce, 200-cell for herbs."
SOURCE_RESULT = f"{SOURCE_TEXT}\n\n## Next\n- Write a planting calendar from these sizes.\n- Compare tray brands."


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def setting(monkeypatch, tmp_path):
    def write(**values):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps(values))
        monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    return write


def _source(conn, result=SOURCE_RESULT, task_id="sr-20261029-090000-aa01", chat=None, **kw):
    return _done(conn, task_id, "List the tray sizes for a small greenhouse.", result, chat=chat, **kw)


def _route(conn, task=TASK, *, jev_answer=WRITING, worker=None, chatgpt=None, hook=None, from_ref=None, chat=None,
           hindsight=None, wait=True):
    lines, clock, hook = [], Clock(), hook or Webhook()
    label = fake_label(jev_answer)
    code = cli.cmd_route(task, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=label,
                         post=hook.post, worker=worker or Scripted(), chatgpt=chatgpt or Chat("PASS"),
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=wait, out=lines.append, chat=chat, hindsight=hindsight, from_ref=from_ref)
    rows = log.recent_tasks(conn)
    return code, "\n".join(lines), rows[0] if rows else None, label, hook


def _relay(conn, preset, task=TASK, *, worker=None, chatgpt=None, hook=None, from_ref=None, wait=True, slots=()):
    lines, clock, hook = [], Clock(), hook or RelayHook(s1=GOOD_NOTE)
    code = cli.cmd_relay(preset, task, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                         settings_paths=[], post=hook.post, worker=worker or Scripted(), chatgpt=chatgpt or Chat("PASS"),
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=wait, slots=list(slots), out=lines.append, from_ref=from_ref)
    rows = log.recent_tasks(conn)
    return code, "\n".join(lines), rows[0] if rows else None, hook


def _block(conn, source_id, secrets=()):
    return fromblock.make(log.get_task(conn, source_id), secrets)["text"]


# ---------- the refusals at intake (decision 8) ----------

def _word(row):
    return row["status"]


def test_a_source_not_in_the_log_or_not_a_task_ref_is_refused(conn):
    assert fromblock.refusal(conn, "99", _word) == (None, "No task #99")
    row, why = fromblock.refusal(conn, "tray", _word)
    assert row is None and why.startswith("--from takes a task's #, number or sr- id")


def test_a_source_that_was_not_delivered_or_has_no_text_is_refused(conn):
    failed = _source(conn, check_state="failed", task_id="sr-20261029-090000-aa02")
    row, why = fromblock.refusal(conn, str(failed["n"]), _word)
    assert row is None and why.startswith(f"#{failed['n']} wasn't delivered")
    empty = _source(conn, result="## Next\n- only a suggestion", task_id="sr-20261029-090000-aa03")
    assert fromblock.refusal(conn, str(empty["n"]), _word) == (None, f"#{empty['n']} delivered no text to build from")


def test_a_change_waiting_to_land_is_not_delivered_yet(conn):
    src = _source(conn)
    log.set_project_files(conn, src["task_id"], {"state": "waiting"})
    row, why = fromblock.refusal(conn, src["task_id"], _word)
    assert row is None and "wasn't delivered" in why


def test_a_forgotten_source_is_refused_until_remembered_again(conn):
    from router import receipt
    src = _source(conn, chat="tray")
    cli.cmd_forget([str(src["n"])], conn=conn, undo=False, client=None, out=receipt.Receipt())
    row, why = fromblock.refusal(conn, str(src["n"]), _word)
    assert row is None and "forgotten" in why and "Remember again" in why
    cli.cmd_forget([str(src["n"])], conn=conn, undo=True, client=None, out=receipt.Receipt())
    assert fromblock.refusal(conn, str(src["n"]), _word)[0]["task_id"] == src["task_id"]


def test_route_refuses_before_jev_with_nothing_written(conn):
    code, out, row, label, _ = _route(conn, from_ref="42")
    assert code == 2 and row is None and label.calls == []
    assert out == "Refused: --from: No task #42. Nothing was logged or sent."


def test_relay_refuses_before_any_row(conn):
    code, out, row, hook = _relay(conn, "versus", from_ref="42")
    assert code == 2 and row is None and hook.sent == []
    assert out == "Refused: --from: No task #42. Nothing was logged or sent."


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    w = World(monkeypatch, tmp_path, capsys)
    monkeypatch.setattr(cli.memory, "client", lambda request, **kw: None)  # no store
    return w


def test_a_second_from_is_usage_and_from_on_split_is_flag_refused(world):
    found = world.json("route", "--from", "1", "--from", "2", TASK)
    assert (found["exit"], found["reason_code"]) == (2, "usage") and "--from goes once" in found["message"]
    found = world.json("split", "--from", "1", "plan the greenhouse")
    assert (found["exit"], found["reason_code"]) == (2, "flag_refused") and "--from on sr split is refused" in found["message"]
    assert world.label.calls == []


def test_the_receipt_names_bad_from(world):
    found = world.json("route", "--from", "7", TASK)
    assert (found["exit"], found["reason_code"], found["task_id"]) == (2, "bad_from", None)
    assert found["message"] == "Refused: --from: No task #7. Nothing was logged or sent."


# ---------- accepted: the row and its own tag ----------

def test_the_row_keeps_the_source_and_its_own_tag(conn):
    src = _source(conn, chat="tray")
    code, out, row, label, _ = _route(conn, from_ref=f"#{src['n']}", chat="calendar", worker=Scripted("a calendar"))
    assert code == 0, out
    assert row["from_task"] == src["task_id"] and log.chat_of(row) == "calendar" and len(label.calls) == 1


# ---------- the block (decision 9) ----------

def test_the_block_is_the_result_without_handoff_or_next_redacted_and_labeled(conn):
    src = _source(conn, result=f"{SOURCE_TEXT} Key {SECRET}.\n\n## Next\n- Compare tray brands.")
    record = fromblock.make(log.get_task(conn, src["task_id"]), [SECRET])
    date = memory.local_date(src["updated_at"])
    assert record["text"] == (f"===== EARLIER RESULT · #{src['n']} ({date}, writing) =====\n"
                              f"{SOURCE_TEXT} Key [REDACTED].\n===== end earlier result =====\n\n{fromblock.BLOCK_LINE}")
    assert (record["task_id"], record["n"], record["cut"]) == (src["task_id"], src["n"], False)
    assert record["chars"] == len(f"{SOURCE_TEXT} Key [REDACTED].")
    assert "Compare tray brands" not in record["text"] and "## Next" not in record["text"]


def test_a_handoff_section_never_rides_in_the_block(conn):
    src = _source(conn, result=f"{SOURCE_TEXT}\n\n## Handoff\n### Produced\nnothing written: the list\n### Status\nok\n### Next\n- more")
    text = fromblock.make(log.get_task(conn, src["task_id"]), ())["text"]
    assert "## Handoff" not in text and "### Produced" not in text and SOURCE_TEXT in text


def test_a_long_result_is_cut_at_a_line_end_with_a_line_naming_the_source(conn, setting):
    setting(from_max=64)
    lines = [f"Line {k}: tray notes for week {k}." for k in range(1, 9)]
    src = _source(conn, result="\n".join(lines))
    record = fromblock.make(log.get_task(conn, src["task_id"]), ())
    kept = "\n".join(lines[:2])  # the first two lines fit in 64 characters; the third would not
    assert len(kept) <= 64 < len("\n".join(lines[:3]))
    total = len("\n".join(lines))
    assert record["cut"] is True
    assert (f"{kept}\n(Cut here at 64 characters: #{src['n']}'s whole result is {total:,} characters; sr show "
            f"{src['n']} prints it.)\n=====") in record["text"]


def test_the_block_comes_after_the_task_and_before_the_memory_block_and_judges_get_the_check_line(conn):
    src = _source(conn, chat="tray")
    other = _done(conn, "sr-20261029-090500-aa09", "Name the herbs.", "Basil, thyme, sage.", chat="tray")
    log.add_task(conn, "sr-20261029-100000-bb01", TASK, "cli", WRITING, chat="tray", from_task=src["task_id"])
    task = log.get_task(conn, "sr-20261029-100000-bb01")
    fake = FakeHindsight(results=[FakeHindsight.result(f"task-{src['task_id']}", SOURCE_TEXT, tags=["chat:tray"])])
    prompt, record, mem = context.attach("THE PROMPT", task, "claude", (), conn=conn, hindsight=fake.client, kind="do")
    block = _block(conn, src["task_id"])
    assert prompt.index("THE PROMPT") < prompt.index(block) < prompt.index(context.MEMORY_USE_LINE)
    assert fromblock.CHECK_LINE not in prompt
    assert record["from"]["task_id"] == src["task_id"] and record["from"]["text"] == block
    # decision 9: the memory block leaves the source out (it is in the block whole); the other task stays
    shown = [e.n for e in memory.entries_of_block(mem["text"])]
    assert other["n"] in shown and src["n"] not in shown
    judged, _, _ = context.attach("THE CHECK", task, "chatgpt", (), conn=conn, hindsight=fake.client, kind="check")
    assert f"{block}\n\n{fromblock.CHECK_LINE}\n\n{context.MEMORY_USE_LINE}" in judged
    review, _, _ = context.attach("THE REVIEW", task, "chatgpt", (), conn=conn, hindsight=None, kind="stage", role="review")
    assert review == f"THE REVIEW\n\n{block}\n\n{fromblock.CHECK_LINE}"


def test_an_untagged_task_gets_the_block_and_a_record_with_no_tag(conn):
    src = _source(conn)
    log.add_task(conn, "sr-20261029-100000-bb02", TASK, "cli", WRITING, from_task=src["task_id"])
    task = log.get_task(conn, "sr-20261029-100000-bb02")
    prompt, record, mem = context.attach("THE PROMPT", task, "claude", (), conn=conn, kind="do")
    assert prompt == f"THE PROMPT\n\n{_block(conn, src['task_id'])}" and mem is None
    assert set(record) == {"from"} and set(record["from"]) == {"task_id", "n", "chars", "cut", "text"}


def test_every_call_row_keeps_the_block_as_first_sent(conn):
    src = _source(conn)
    code, out, row, _, _ = _route(conn, from_ref=str(src["n"]), worker=Scripted("calendar v1", "calendar v2"),
                                  chatgpt=Chat("FIX\n1. [must] Add the sowing week.", "PASS\n1. fixed"))
    assert code == 0 and row["check_state"] == "fixed", out
    calls = log.calls_for(conn, row["task_id"])
    assert [c["kind"] for c in calls] == ["do", "check", "fix", "recheck"]
    records = [log.context_of(c)["from"] for c in calls]
    assert all(r == records[0] for r in records) and records[0]["text"] == _block(conn, src["task_id"])
    # decision 9: a later call sends the first call's block even when the source would read differently now
    conn.execute("UPDATE tasks SET result = ? WHERE task_id = ?", ("A different text now.", src["task_id"]))
    assert fromblock.for_call(conn, log.get_task(conn, row["task_id"]), ()) == records[0]


def test_the_doer_the_check_the_fix_and_the_recheck_each_carry_it(conn):
    src = _source(conn)
    worker, chat = Scripted("calendar v1", "calendar v2"), Chat("FIX\n1. [must] Add the sowing week.", "PASS\n1. fixed")
    code, out, row, _, _ = _route(conn, from_ref=str(src["n"]), worker=worker, chatgpt=chat)
    assert code == 0, out
    block = _block(conn, src["task_id"])
    do, fix = worker.prompts
    check, recheck = chat.prompts
    for prompt in (do, fix, check, recheck):
        assert prompt.count(block) == 1
    assert fromblock.CHECK_LINE not in do and fromblock.CHECK_LINE not in fix
    assert f"{block}\n\n{fromblock.CHECK_LINE}" in check and f"{block}\n\n{fromblock.CHECK_LINE}" in recheck
    assert do.index(TASK) < do.index(block) and do.index(checking.NEXT_LINE) < do.index(block)


def test_each_relay_stage_gets_it_and_a_review_gets_the_check_line(conn):
    src = _source(conn)
    review = "## Verdict\npass\n\n## Notes\n- Wrong: nothing.\n- Strong: clear."
    worker, chat = Scripted("CANDIDATE A", review), Chat("CANDIDATE B", review)
    code, out, row, _ = _relay(conn, "versus", from_ref=str(src["n"]), worker=worker, chatgpt=chat)
    assert code == 0 and row["from_task"] == src["task_id"], out  # both reviewed, waiting for the pick
    block = _block(conn, src["task_id"])
    builds = [worker.prompts[0], chat.prompts[0]]
    reviews = [worker.prompts[1], chat.prompts[1]]
    assert all(p.count(block) == 1 and fromblock.CHECK_LINE not in p for p in builds)
    assert all(f"{block}\n\n{fromblock.CHECK_LINE}" in p for p in reviews)


# ---------- Grok (decision 11) ----------

def test_a_relay_whose_grok_stage_the_block_pushes_past_the_limit_is_refused_at_intake(conn, setting):
    setting(grok_prompt_limit=1500)
    src = _source(conn, result="Tray note. " * 120)  # 1,320 characters, so the research stage's prompt passes 1,500
    code, out, row, hook = _relay(conn, "research-build", from_ref=str(src["n"]))
    assert code == 2 and row["task_id"] == src["task_id"] and hook.sent == []  # nothing new was logged
    assert out.startswith("Refused: the task is too long for grok in stage 1 (research): with the earlier result, its "
                          "prompt would be ")
    assert "without it); grok's limit is 1,500, and the earlier result is never cut to fit" in out
    assert out.endswith("Nothing was logged or sent.")


def test_a_relay_whose_grok_stage_fits_sends_grok_the_block(conn):
    src = _source(conn)
    code, out, row, hook = _relay(conn, "research-build", from_ref=str(src["n"]), worker=Scripted("THE BUILD"),
                                  chatgpt=Chat("PASS"))
    assert code == 0, out
    assert _block(conn, src["task_id"]) in hook.sent[0]["task"]


def test_a_routed_task_grok_would_do_comes_back_after_the_label_with_both_lengths(conn, setting):
    setting(grok_prompt_limit=1500)
    src = _source(conn, result="Gardeners talk trays. " * 70)
    code, out, row, label, hook = _route(conn, "What are gardeners on X saying about tray height?", jev_answer=XPULSE,
                                         from_ref=str(src["n"]))
    assert code == 4 and len(label.calls) == 1 and hook.sent == []  # after Jev's label, before any call
    assert (row["status"], row["reason_code"], row["from_task"]) == ("returned", "too_long", src["task_id"])
    assert "came back to you: too long for grok: with the earlier result, its prompt would be" in out
    assert "grok's limit is 1,500" in out


def test_a_grok_call_carrying_the_block_is_held_to_the_limit_but_a_fix_and_a_reask_stay_exempt():
    record = {"from": {"task_id": "sr-x", "text": "B"}}
    assert cli._from_limited(record, "do", "sr-x") and cli._from_limited(record, "stage", "sr-x-s2")
    assert cli._from_limited(record, "check", "sr-x-c1")
    assert not cli._from_limited(record, "fix", "sr-x-f1") and not cli._from_limited(record, "reask", "sr-x-s1r")
    assert not cli._from_limited(record, "do", f"sr-x{context.DO_REASK}")
    assert not cli._from_limited({"notes": {}}, "do", "sr-x") and not cli._from_limited(None, "stage", "sr-x-s1")


# ---------- --answers carries it (decision 8) ----------

LOW = {**jev("writing"), "status": "below_floor", "confidence": 0.5}


def test_answers_carries_the_floor_rows_from_and_refuses_another(world):
    world.worker, world.chatgpt = Scripted("tray list"), Chat("PASS")
    assert world.json("route", "List the tray sizes.")["status"] == "done"
    world.label = fake_label(LOW)
    floor = world.json("route", "--from", "1", "make sense of this vague thing")
    assert (floor["status"], floor["reason_code"]) == ("returned", "needs_label")
    assert world.row(floor["n"])["from_task"] == world.row(1)["task_id"]
    other = world.json("route", "--skill", "writing", "--answers", str(floor["n"]), "--from", str(floor["n"]),
                       "make sense of this vague thing")
    assert (other["exit"], other["reason_code"]) == (2, "flag_refused") and "--from" in other["message"]
    world.worker = Scripted("an answer")
    found = world.json("route", "--skill", "writing", "--answers", str(floor["n"]), "make sense of this vague thing")
    assert found["status"] == "done"
    assert world.row(found["n"])["from_task"] == world.row(1)["task_id"]


# ---------- the JSON (decision 18) and Details (decision 12) ----------

def test_the_json_names_the_source_and_show_gives_the_block_as_sent(conn):
    src = _source(conn)
    code, out, row, _, _ = _route(conn, from_ref=str(src["n"]), worker=Scripted("a calendar"))
    view = jsonview.task_view(conn, log.get_task(conn, row["task_id"]))
    record = fromblock.make(log.get_task(conn, src["task_id"]), ())
    assert view["from"] == {"task_id": src["task_id"], "n": src["n"], "chars": record["chars"], "cut": False}
    shown = jsonview.show_view(conn, log.get_task(conn, row["task_id"]))
    assert shown["from_given"]["text"] == record["text"]
    plain = jsonview.task_view(conn, src)
    assert plain["from"] is None and jsonview.show_view(conn, src)["from_given"] is None


# ---------- the page's builder (decision 12) ----------

STATUS = {"presets": [{"name": "versus", "slots": [{"name": "a", "default": "claude", "allowed": ["claude", "chatgpt"]},
                                                   {"name": "b", "default": "chatgpt", "allowed": ["claude", "chatgpt"]}]}],
          "skills": [{"key": "writing"}], "drop_folder": None}
TID = "sr-20261029-090000-aa01"


def test_the_page_builder_adds_from_on_route_and_a_team_and_refuses_it_on_a_split():
    route = page_commands.build({"action": "send", "team": "route", "text": "a calendar", "from": TID}, STATUS).args
    assert list(route) == ["route", "--json", "--source", "ui", "--from", TID, "--", "a calendar"]
    team = page_commands.build({"action": "send", "team": "versus", "text": "a calendar", "from": TID}, STATUS).args
    assert list(team) == ["relay", "versus", "--json", "--source", "ui", "--from", TID, "--", "a calendar"]
    with pytest.raises(page_commands.Refused, match="a split builds from no earlier result"):
        page_commands.build({"action": "send", "team": "split", "text": "plan it", "from": TID}, STATUS)
    with pytest.raises(page_commands.Refused, match="the earlier task must be a task id"):
        page_commands.build({"action": "send", "team": "route", "text": "x", "from": "--help"}, STATUS)


def test_every_built_from_command_parses_with_the_real_parser():
    for request in ({"action": "send", "team": "route", "text": "a calendar", "from": TID},
                    {"action": "send", "team": "versus", "text": "a calendar", "from": TID}):
        args = list(page_commands.build(request, STATUS).args)
        parsed = cli._parser(None, quiet=True).parse_args(args)
        assert parsed.from_task == [TID]
