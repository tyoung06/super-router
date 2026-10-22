"""Build brief 21, C1 (rules v2.30, Round outputs; decision 4, brief 13's Phase 0 decisions). Every call's output is its
own file, `tasks/<task_id>/<NN>-<role>-<agent>.md` beside the log (`NN` the call's place in the task; a re-ask
`reask-<role>`; versus `build-a`/`build-b`/`review-a`/`review-b`; votes `vote-a`/`vote-b`/`vote-c`), named on the call
row. Written after the row (a Grok call's when it is collected; a call with no text has none), through the redactor
with every `.env` value, owner-only, exclusive create: never overwritten, and a second write says so in one line and
leaves `round_file` empty. `sr show` names each file, text and JSON (`original_file` is the first build's: choice 21,
no new flag); rows from before read `not kept`; a JSON read writes none. Round files change no prompt. Fakes only; every
value here is fake."""
import json
import os
import stat

import pytest

from router import __main__ as cli
from router import log, rounds
from tests.helpers import fake_label
from tests.relay_snapshot import AMENDED, DELIVERABLE, EDITED, PLAN, REVIEW
from tests.test_json_actions import FAKE_ENV, World, jev
from tests.test_loop import Scripted
from tests.test_redteam_chain import ATTACKS, BUILD, REVISION
from tests.test_redteam_fixes import BAD_FIX, FIX_LIST, GOOD_FIX
from tests.test_relay import GOOD_NOTE, THIN, Chat, RelayHook

VOTE = "## Answer\nParis\n\n## Why\nIt is the capital.\n\n## Confidence\n90"
WRITER = rounds.writer


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    return World(monkeypatch, tmp_path, capsys)


def _calls(n=1):
    conn = log.init_db(cli.DB_PATH)
    try:
        row = log.task_by_number(conn, n)
        return row, [(c["kind"], c["agent"], c["round_file"]) for c in log.calls_for(conn, row["task_id"])]
    finally:
        conn.close()


def _names(calls):
    return [f and f.rsplit("/", 1)[1] for _, _, f in calls]


def _read(path):
    return (cli.DB_PATH.parent / path).read_text()


def _checks(world, times=6):
    for _ in range(times):
        world.run("check")


# ---------- the names, per kind of task ----------

def test_a_routed_task_writes_one_file_per_call_in_order(world):
    world.worker, world.chatgpt = Scripted("Draft one.", "Draft two."), Chat("FIX\n1. Rhyme.", "PASS")
    world.run("route", "write a poem")
    row, calls = _calls()
    tid = row["task_id"]
    assert calls == [("do", "claude", f"tasks/{tid}/01-do-claude.md"), ("check", "chatgpt", f"tasks/{tid}/02-check-chatgpt.md"),
                     ("fix", "claude", f"tasks/{tid}/03-fix-claude.md"), ("recheck", "chatgpt", f"tasks/{tid}/04-recheck-chatgpt.md")]
    assert [_read(f) for _, _, f in calls] == ["Draft one.", "FIX\n1. Rhyme.", "Draft two.", "PASS"]


def test_versus_names_the_candidates_and_the_reviews_of_them(world):
    world.worker, world.chatgpt = Scripted("A.", REVIEW), Chat("B.", REVIEW)
    world.run("relay", "versus", "a blurb")
    row, calls = _calls()
    assert _names(calls) == ["01-build-a-claude.md", "02-build-b-chatgpt.md", "03-review-a-chatgpt.md", "04-review-b-claude.md"]
    assert _read(calls[1][2]) == "B."


def test_a_vote_names_its_voters_and_a_grok_file_is_written_when_collected(world):
    world.worker, world.chatgpt, world.hook = Scripted(VOTE), Chat(VOTE), RelayHook(s3=VOTE)
    world.run("relay", "vote", "capital of France", "--no-wait")
    row, calls = _calls()
    assert _names(calls) == ["01-vote-a-claude.md", "02-vote-b-chatgpt.md", None]  # Grok's vote is still out
    world.run("check")
    row, calls = _calls()
    assert _names(calls)[2] == "03-vote-c-grok.md" and _read(calls[2][2]) == VOTE


def test_a_stage_reask_and_the_research_build_chain(world):
    world.worker, world.chatgpt = Scripted("A built result."), Chat("PASS")
    world.hook = RelayHook(s1=THIN, s1r=GOOD_NOTE)
    world.run("relay", "research-build", "trays", "--no-wait")
    _checks(world)
    row, calls = _calls()
    assert _names(calls) == ["01-research-grok.md", "02-reask-research-grok.md", "03-build-claude.md", "04-check-chatgpt.md"]
    assert _read(calls[0][2]) == THIN and _read(calls[1][2]) == GOOD_NOTE


def test_collab_names_its_four_stages(world):
    world.worker, world.chatgpt = Scripted(PLAN, DELIVERABLE), Chat(AMENDED, EDITED)
    world.run("relay", "collab", "a three-line note")
    row, calls = _calls()
    assert _names(calls) == ["01-plan-claude.md", "02-amend-chatgpt.md", "03-execute-claude.md", "04-edit-chatgpt.md"]


def test_redteam_names_its_stages_and_the_fix_reask(world):
    world.worker = Scripted(BUILD, REVISION, BAD_FIX, GOOD_FIX)
    world.chatgpt = Chat(ATTACKS, FIX_LIST, "PASS")
    world.run("relay", "redteam", "a budget ritual")
    row, calls = _calls()
    assert _names(calls) == ["01-build-claude.md", "02-attack-chatgpt.md", "03-revise-claude.md", "04-check-chatgpt.md",
                             "05-fix-claude.md", "06-reask-fix-claude.md", "07-recheck-chatgpt.md"]


def test_a_routed_doers_contract_reask_is_reask_do():
    call = {"kind": "do", "call_id": "sr-20261020-000001-ab01-dr", "agent": "claude"}
    assert rounds.file_name(call, 2) == "02-reask-do-claude.md"


# ---------- what is written, and how ----------

def test_a_failed_call_keeps_its_error_text_and_every_env_value_is_redacted(world):
    world.worker = Scripted(RuntimeError("boom"))
    world.run("route", "write a poem")
    row, calls = _calls()
    assert _names(calls) == ["01-do-claude.md"] and _read(calls[0][2]) == "unexpected error: RuntimeError"  # as its row
    world.worker = Scripted(f"the extra value {FAKE_ENV['JEV_API_KEY']} and {FAKE_ENV['GROK_WEBHOOK_URL']}")
    world.chatgpt = Chat("PASS")
    world.run("route", "write another poem")
    row, calls = _calls(2)
    text = _read(calls[0][2])
    assert all(v not in text for v in FAKE_ENV.values()) and text.count("[REDACTED]") == 2


def test_files_and_folders_are_owner_only(world):
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("391")
    world.run("route", "what is 17 times 23")
    row, calls = _calls()
    path = cli.DB_PATH.parent / calls[0][2]
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(path.parent.parent).st_mode) == 0o700


def test_a_second_write_fails_loudly_and_leaves_the_row_empty(world):
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("391")
    tid = "sr-20261020-000001-ab01"  # the first id World hands out
    folder = cli.DB_PATH.parent / "tasks" / tid
    folder.mkdir(parents=True)
    (folder / "01-do-claude.md").write_text("already here")
    code, out, err = world.run("route", "what is 17 times 23")
    assert code == 0 and f"round file not written: tasks/{tid}/01-do-claude.md already exists" in out
    row, calls = _calls()
    assert calls[0][2] is None and (folder / "01-do-claude.md").read_text() == "already here"
    assert row["status"] == "done"


def test_under_json_the_refusal_line_is_in_the_message(world):
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("391")
    folder = cli.DB_PATH.parent / "tasks" / "sr-20261020-000001-ab01"
    folder.mkdir(parents=True)
    (folder / "01-do-claude.md").write_text("already here")
    found = world.json("route", "what is 17 times 23")
    assert found["exit"] == 0 and "round file not written" in found["message"]


def test_an_in_memory_log_writes_no_file():
    conn = log.init_db(":memory:")
    write = rounds.writer(secrets=(), out=lambda line: None)
    log.add_task(conn, "sr-1", "t", "cli", jev("writing"))
    log.add_call(conn, "sr-1", "sr-1", "do", "claude", status="done", text="x")
    assert write(conn, "sr-1") is None and log.get_call(conn, "sr-1")["round_file"] is None


def test_a_timed_out_call_and_a_call_still_out_have_none(tmp_path):
    conn = log.init_db(tmp_path / "router.db")
    seen = []
    log.ROUND_WRITER = rounds.writer(secrets=(), out=seen.append)
    try:
        log.add_task(conn, "sr-1", "t", "cli", jev("writing"))
        log.add_call(conn, "sr-1-g", "sr-1", "do", "grok")  # sent: nothing yet
        assert log.get_call(conn, "sr-1-g")["round_file"] is None
        log.finish_call(conn, "sr-1-g", "timed_out")
        assert log.get_call(conn, "sr-1-g")["round_file"] is None and not (tmp_path / "tasks").exists()
    finally:
        log.ROUND_WRITER = None
    assert seen == []


def test_the_writer_is_never_left_set_after_a_command(world):
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("391")
    world.run("route", "what is 17 times 23")
    assert log.ROUND_WRITER is None


def test_tasks_is_gitignored():
    assert "tasks/" in (cli.safety.REPO_ROOT / ".gitignore").read_text().splitlines()


# ---------- sr show ----------

def test_sr_show_names_each_file_and_a_json_read_writes_none(world):
    world.worker, world.chatgpt = Scripted("Draft one.", "Draft two."), Chat("FIX\n1. Rhyme.", "PASS")
    world.run("route", "write a poem")
    row, calls = _calls()
    code, out, err = world.run("show", "1")
    assert "Round files:" in out and f"  01 do by claude: {calls[0][2]}" in out
    assert f"  04 recheck by chatgpt: {calls[3][2]}" in out
    doc = json.loads(world.run("show", "1", "--json")[1])
    assert [c["round_file"] for c in doc["calls"]] == [f for _, _, f in calls]
    assert doc["original_file"] == calls[0][2] and doc["result_file"] == calls[2][2]
    before = sorted(p.name for p in (cli.DB_PATH.parent / "tasks" / row["task_id"]).iterdir())
    world.run("status", "--json")
    world.run("log", "--json")
    assert sorted(p.name for p in (cli.DB_PATH.parent / "tasks" / row["task_id"]).iterdir()) == before


def test_the_original_of_a_relay_task_is_its_deliverable_stage(world):
    world.worker, world.chatgpt = Scripted(PLAN, DELIVERABLE), Chat(AMENDED, EDITED)
    world.run("relay", "collab", "a three-line note")
    doc = json.loads(world.run("show", "1", "--json")[1])
    assert doc["original_file"].endswith("03-execute-claude.md")  # the check stage (4) checks it
    world.worker, world.chatgpt = Scripted("A.", REVIEW), Chat("B.", REVIEW)
    world.run("relay", "versus", "a blurb")
    assert json.loads(world.run("show", "2", "--json")[1])["original_file"] is None  # before the pick
    world.run("pick", "2", "b")
    assert json.loads(world.run("show", "2", "--json")[1])["original_file"].endswith("02-build-b-chatgpt.md")


def test_a_task_from_before_reads_not_kept(world):
    conn = log.init_db(cli.DB_PATH)
    log.add_task(conn, "sr-old", "an old task", "cli", jev("quick_answer", 0.99))
    log.set_route(conn, "sr-old", agents=("claude", "chatgpt"), agent="claude", route_reason="best", skill="quick_answer",
                  skill_source="jev", check_state="not_needed")
    log.add_call(conn, "sr-old", "sr-old", "do", "claude", status="done", text="old answer")  # no writer: as before 14
    log.set_done(conn, "sr-old", "old answer", check_state="not_needed")
    conn.close()
    code, out, err = world.run("show", "1")
    assert "Round files: not kept" in out
    assert json.loads(world.run("show", "1", "--json")[1])["original_file"] is None


def test_there_is_no_original_flag():  # Phase 0 choice 21 (approved): the page brief builds the button
    with pytest.raises(SystemExit) as stopped:
        cli.main(["show", "1", "--original"])
    assert stopped.value.code == 2

# ---------- round files change no prompt ----------

SCENARIOS = {
    # name: (command, label, claude replies, chatgpt replies, grok bodies)
    "routed": (["route", "write a poem"], "writing", ["Draft one.", "Draft two."], ["FIX\n1. Rhyme.", "PASS"], {}),
    "research-build": (["relay", "research-build", "trays"], None, ["A built result."], ["PASS"],
                       {"s1": THIN, "s1r": GOOD_NOTE}),
    "collab": (["relay", "collab", "a note"], None, [PLAN, DELIVERABLE], [AMENDED, EDITED], {}),
    "versus": (["relay", "versus", "a blurb"], None, ["A.", REVIEW], ["B.", REVIEW], {}),
    "redteam": (["relay", "redteam", "a budget ritual"], None, [BUILD, REVISION, BAD_FIX, GOOD_FIX],
                [ATTACKS, FIX_LIST, "PASS"], {}),
    "vote": (["relay", "vote", "capital of France"], None, [VOTE], [VOTE], {"s3": VOTE}),
}


def _prompts(monkeypatch, tmp_path, capsys, name, *, files, as_json):
    command, label, claude, chat, bodies = SCENARIOS[name]
    tmp_path.mkdir(parents=True)
    monkeypatch.setattr(cli, "DB_PATH", tmp_path / "router.db")
    world = World(monkeypatch, tmp_path, capsys)
    world.worker, world.chatgpt, world.hook = Scripted(*claude), Chat(*chat), RelayHook(**bodies)
    if label:
        world.label = fake_label(jev(label))
    monkeypatch.setattr(cli.rounds, "writer", WRITER if files else (lambda **kw: None))
    flag = ["--json"] if as_json else ["--no-wait"]
    world.run(*command, *flag)
    for _ in range(4):
        world.run("check", *(["--json"] if as_json else []))
    row, calls = _calls()
    kept = [f for _, _, f in calls if f]
    return {"claude": world.worker.prompts, "chatgpt": world.chatgpt.prompts, "kwargs": world.chatgpt.kwargs,
            "grok": world.hook.sent, "status": row["status"], "kept": len(kept), "calls": len(calls)}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_prompt_is_the_same_with_round_files_on_and_with_json(monkeypatch, tmp_path, capsys, name):
    off = _prompts(monkeypatch, tmp_path / "off", capsys, name, files=False, as_json=False)
    on = _prompts(monkeypatch, tmp_path / "on", capsys, name, files=True, as_json=False)
    as_json = _prompts(monkeypatch, tmp_path / "json", capsys, name, files=True, as_json=True)
    for key in ("claude", "chatgpt", "kwargs", "grok", "status", "calls"):
        assert off[key] == on[key] == as_json[key], key
    assert off["kept"] == 0 and on["kept"] == as_json["kept"] == on["calls"] > 0
    assert off["status"] in ("done", "returned")
