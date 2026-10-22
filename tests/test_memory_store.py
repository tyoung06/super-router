"""Build brief 19, phase D (rules v2.27, Memory, "What is stored", "When"): the retain at delivery and `sr memory
rebuild`. One write per delivered tagged task, beside the handoff entry, logged on the task row; never on a result
the rules keep from the owner; a failed retain never changes the task; the bank can always be cleared and reloaded from
the log. Fake agents, a fake store; every value here is fake."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from router import __main__ as cli
from router import log, memory
from tests.fake_hindsight import FakeHindsight
from tests.test_chat_intake import _relay, _route
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_collab import AMENDED, DELIVERABLE, EDITED, LOADED, PLAN
from tests.test_memory_block import SECTION, T0, _done, project  # noqa: F401  (the project fixture)
from tests.test_pick import FAILING_REVIEW_OF_A
from tests.test_relay import CONFIG, ROSTER, SECRET, Chat, RelayHook
from tests.test_resume_run import WRITING, claude_limit
from tests.test_versus_run import A_TEXT, B_TEXT, REVIEW_OF_A, REVIEW_OF_B
from tests.test_vote_run import A as VOTE_A, B as VOTE_B, G as VOTE_G

TASK = "Write two lines about seed trays."
TAG = "chat:tray"


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _retain_of(fake):
    assert len(fake.retains) == 1, fake.retains
    return fake.retains[0]


def _expected_item(row, content, status, kind="writing", doer="claude", tag=TAG):
    return {"content": content, "context": f"super-router task {row['n']}: {kind} by {doer}",
            "timestamp": row["updated_at"],
            "metadata": {"n": str(row["n"]), "date": memory.local_date(row["updated_at"]), "kind": kind, "doer": doer,
                         "status": status, "tag": tag},
            "tags": [tag], "document_id": f"task-{row['task_id']}"}


# ---------- stored (decisions 4, 5, 6) ----------

def test_a_passed_routed_task_is_stored_with_the_exact_body_and_logged_on_its_row(conn):
    fake = FakeHindsight()
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("two lines"), chatgpt=Chat("PASS"), hindsight=fake.client)
    assert code == 0 and row["check_state"] == "passed", out
    item = _retain_of(fake)
    assert item == _expected_item(row, f"{TASK}\n\ntwo lines", "passed")
    assert all(isinstance(v, str) for v in item["metadata"].values()) and len(item["metadata"]) == 6
    assert fake.of("retain")[0]["timeout"] == 20 and fake.of("retain")[0]["path"] == "/v1/default/banks/super-router/memories"
    writes = log.memory_of(row)
    assert len(writes) == 1 and writes[0]["document_id"] == f"task-{row['task_id']}" and writes[0]["chars"] == len(item["content"])
    assert writes[0]["state"] == "done/passed/2" and "at" in writes[0]
    assert out.splitlines()[-1] == f"memory: stored task-{row['task_id']}, {len(item['content'])} characters"
    assert out.index("two lines") < out.index("memory: stored")  # after the result is shown
    assert f"task-{row['task_id']}" in fake.documents


def test_a_fixed_result_is_stored_with_the_fixed_text_and_status_fixed(conn):
    fake = FakeHindsight()
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("FIRST", "FIXED"), chatgpt=Chat("FIX\n1. x", "PASS"),
                               hindsight=fake.client)
    assert row["check_state"] == "fixed"
    assert _retain_of(fake) == _expected_item(row, f"{TASK}\n\nFIXED", "fixed")
    assert log.memory_of(row)[0]["state"] == "done/fixed/4"


def test_a_quick_answer_is_stored_unchecked_by_rule(conn):
    fake = FakeHindsight()
    code, out, row, _ = _route(conn, chat="tray", jev={"status": "ok", "label": "quick_answer", "confidence": 0.95, "tokens": 0},
                               worker=Scripted("Athens"), hindsight=fake.client)
    assert code == 0 and row["check_state"] == "not_needed"
    assert _retain_of(fake) == _expected_item(row, f"{TASK}\n\nAthens", "not_needed", kind="quick_answer")


def test_a_project_task_stores_the_deliverable_with_its_handoff_section(conn, project):
    fake = FakeHindsight()
    code, out, row, _ = _route(conn, project="demo", worker=Scripted("two lines" + SECTION), chatgpt=Chat("PASS"),
                               hindsight=fake.client)
    assert code == 0 and row["check_state"] == "passed", out
    item = _retain_of(fake)
    assert item["content"] == f"{TASK}\n\ntwo lines" + SECTION and row["result"] == "two lines"
    assert item["tags"] == ["project:demo"] and item["metadata"]["tag"] == "project:demo"
    assert out.index("HANDOFF.md: entry for") < out.index("memory: stored")  # the entry first, the retain beside it


def test_a_collab_result_checked_by_its_stage_is_stored(conn):
    fake = FakeHindsight()
    code, out, row, hook = _relay(conn, "collab", chat="tray", worker=Scripted(PLAN, DELIVERABLE), chatgpt=Chat(AMENDED, EDITED),
                                  hindsight=fake.client, wait=True)
    assert code == 0 and row["check_state"] == "passed" and row["check_note"] == "checked-by-stage 4", out
    item = _retain_of(fake)
    assert item["metadata"]["status"] == "passed: checked-by-stage 4" and item["metadata"]["kind"] == "collab"
    assert item["content"] == f"{row['task']}\n\n{row['result']}"
    assert "memory: stored" in out


def test_a_picked_versus_candidate_is_stored_at_the_pick_whatever_its_review_said(conn):
    for review, status in ((REVIEW_OF_A, "passed: picked a; review by chatgpt: pass"),
                           (FAILING_REVIEW_OF_A, "failed: picked a; review by chatgpt: fail")):
        c = log.init_db(":memory:")
        fake = FakeHindsight()
        code, out, row, hook = _relay(c, "versus", chat="tray", worker=Scripted(A_TEXT, REVIEW_OF_B), chatgpt=Chat(B_TEXT, review),
                                      hindsight=fake.client, wait=True)
        assert row["status"] == "returned" and fake.retains == [], out
        lines = []
        assert cli.cmd_pick([str(row["n"]), "a"], conn=c, loaded=LOADED, secrets=[SECRET], hindsight=fake.client,
                            out=lines.append) == 0
        after = log.get_task(c, row["task_id"])
        item = _retain_of(fake)
        assert item["content"] == f"{row['task']}\n\n{A_TEXT}" and item["metadata"]["status"] == status
        assert item["metadata"]["kind"] == "versus" and item["metadata"]["doer"] == "claude"
        assert log.memory_of(after)[0]["document_id"] == f"task-{row['task_id']}"
        assert lines[-1].startswith("memory: stored")
        c.close()


def test_pick_none_stores_nothing(conn):
    fake = FakeHindsight()
    code, out, row, hook = _relay(conn, "versus", chat="tray", worker=Scripted(A_TEXT, REVIEW_OF_B), chatgpt=Chat(B_TEXT, REVIEW_OF_A),
                                  hindsight=fake.client, wait=True)
    lines = []
    assert cli.cmd_pick([str(row["n"]), "none"], conn=conn, loaded=LOADED, hindsight=fake.client, out=lines.append) == 0
    assert fake.retains == [] and log.memory_of(log.get_task(conn, row["task_id"])) == []


def _vote(conn, fake, *, claude, chatgpt, grok):
    hook, clock, lines = RelayHook(s3=grok), Clock(), []
    worker, chat = Chat(claude), Chat(chatgpt)
    code = cli.cmd_relay("vote", "Which is largest: Texas, France, or Spain? Name only.", conn=conn, config=CONFIG,
                         roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[], post=hook.post, worker=worker,
                         chatgpt=chat, codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep,
                         clock=clock, wait=False, slots=[], out=lines.append, chat="tray", hindsight=fake.client)
    row = log.recent_tasks(conn)[0]
    code = cli.cmd_check(conn=conn, config=CONFIG, environ={}, settings_paths=[], post=hook.post, worker=worker,
                         chatgpt=chat, codex_login=lambda: True, fetch=hook.fetch, close=hook.close, presets=LOADED,
                         roster=ROSTER, hindsight=fake.client, out=lines.append)
    return log.get_task(conn, row["task_id"]), "\n".join(lines)


def test_a_vote_majority_is_stored_and_a_picked_vote_answer_is_not(conn):
    fake = FakeHindsight()
    row, out = _vote(conn, fake, claude=VOTE_A, chatgpt=VOTE_B, grok=VOTE_G)
    assert row["status"] == "done" and row["check_note"] == "checked-by-vote 3/0", out
    item = _retain_of(fake)
    assert item["metadata"]["status"] == "passed: checked-by-vote 3/0" and item["metadata"]["kind"] == "vote"
    assert item["content"] == f"{row['task']}\n\n{row['result']}"
    c = log.init_db(":memory:")
    fake = FakeHindsight()
    row, out = _vote(c, fake, claude=VOTE_A, chatgpt=VOTE_B.replace("texas.", "France"), grok=VOTE_G.replace("Texas", "Spain"))
    assert row["status"] == "returned" and fake.retains == [], out
    lines = []
    assert cli.cmd_pick([str(row["n"]), "a"], conn=c, loaded=LOADED, hindsight=fake.client, out=lines.append) == 0
    assert log.get_task(c, row["task_id"])["check_state"] == "unchecked" and fake.retains == []
    assert log.memory_of(log.get_task(c, row["task_id"])) == [] and "memory:" not in "\n".join(lines)
    c.close()


# ---------- not stored ----------

def test_a_failed_check_is_never_stored_and_leaves_no_record(conn):
    fake = FakeHindsight()
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("FIRST", "FIXED"), chatgpt=Chat("FIX\n1. x", "FIX\n1. y"),
                               hindsight=fake.client)
    assert code == 5 and row["check_state"] == "failed"
    assert fake.retains == [] and log.memory_of(row) == [] and "memory:" not in out


def test_an_unchecked_delivery_is_not_stored(conn):
    fake, lines, clock, hook = FakeHindsight(), [], Clock(), Webhook()
    code = cli.cmd_route(TASK, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=lambda *a, **k: dict(WRITING), post=hook.post, worker=Scripted("two lines"), chatgpt=None,
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=True, out=lines.append, chat="tray", hindsight=fake.client)
    row = log.recent_tasks(conn)[0]
    assert row["status"] == "done" and row["check_state"] == "unchecked", "\n".join(lines)
    assert fake.retains == [] and log.memory_of(row) == []


def test_a_returned_task_and_a_failed_first_call_are_not_stored(conn):
    fake = FakeHindsight()
    code, out, row, _ = _route(conn, chat="tray", jev={"status": "below_floor", "label": "writing", "confidence": 0.5, "tokens": 0})
    assert row["status"] == "returned"
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted(claude_limit()), hindsight=fake.client)
    assert row["status"] == "failed" and fake.retains == [] and log.memory_of(row) == []


def test_an_untagged_task_is_never_stored_and_never_asks_the_store(conn):
    fake = FakeHindsight()
    code, out, row, _ = _route(conn, worker=Scripted("two lines"), chatgpt=Chat("PASS"), hindsight=fake.client)
    assert code == 0 and fake.requests == [] and "memory:" not in out


# ---------- the key scan and a failed retain ----------

def test_a_result_that_still_looks_like_a_key_is_not_stored_and_the_row_says_so(conn):
    fake = FakeHindsight()
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("done\nJEV_API_KEY=abcdefghijklmnop"), chatgpt=Chat("PASS"),
                               hindsight=fake.client)
    assert code == 0 and row["status"] == "done"
    assert fake.retains == []
    writes = log.memory_of(row)
    assert writes == [{"skipped": "looks like a key", "state": "done/passed/2", "at": writes[0]["at"]}]
    assert out.splitlines()[-1] == "memory: skipped: looks like a key"


def test_a_real_secret_in_a_result_is_redacted_before_the_retain(conn):
    fake = FakeHindsight()
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted(f"the key is {SECRET}"), chatgpt=Chat("PASS"), hindsight=fake.client)
    item = _retain_of(fake)
    assert SECRET not in json.dumps(item) and "[REDACTED]" in item["content"]


@pytest.mark.parametrize("mode", ["refused", "timeout", 500, "bad json"])
def test_a_failed_retain_is_skipped_and_the_task_is_delivered_unchanged(conn, mode):
    fake = FakeHindsight(fail={"retain": mode})
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("two lines"), chatgpt=Chat("PASS"), hindsight=fake.client)
    assert code == 0 and row["status"] == "done" and row["result"] == "two lines" and "two lines" in out
    assert len(fake.of("retain")) == 1  # nothing retries
    writes = log.memory_of(row)
    assert len(writes) == 1 and writes[0]["skipped"].startswith("unavailable (") and writes[0]["state"] == "done/passed/2"
    assert out.splitlines()[-1].startswith("memory: skipped: unavailable (")
    assert "boom" not in out and "127.0.0.1" not in out


def test_the_delivered_output_is_the_same_with_the_store_down_as_with_it_up(conn):
    up, down = FakeHindsight(), FakeHindsight(fail={"retain": "refused", "recall": "refused"})
    a = _route(conn, chat="tray", worker=Scripted("two lines"), chatgpt=Chat("PASS"), hindsight=up.client)
    b = _route(conn, chat="tray", worker=Scripted("two lines"), chatgpt=Chat("PASS"), hindsight=down.client)
    strip = lambda out, tid: "\n".join(l for l in out.replace(tid, "ID").splitlines() if not l.startswith("memory:") and not l.startswith("new chat"))
    assert strip(a[1], a[2]["task_id"]) == strip(b[1], b[2]["task_id"])


# ---------- once per ending; again on a new ending under the same document_id ----------

def test_the_store_runs_once_per_ending_and_again_for_a_new_ending_under_the_same_document_id(conn):
    fake = FakeHindsight()
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("two lines"), chatgpt=Chat("PASS"), hindsight=fake.client)
    lines = []
    cli._memory_store(conn, row["task_id"], lines.append, hindsight=fake.client, secrets=[])
    assert lines == [] and len(fake.retains) == 1 and len(log.memory_of(log.get_task(conn, row["task_id"]))) == 1
    log.add_call(conn, f"{row['task_id']}-x", row["task_id"], "check", "chatgpt", status="done", text="PASS", verdict="PASS")
    cli._memory_store(conn, row["task_id"], lines.append, hindsight=fake.client, secrets=[])
    assert len(fake.retains) == 2 and fake.retains[1]["document_id"] == fake.retains[0]["document_id"]
    assert list(fake.documents) == [f"task-{row['task_id']}"]  # replaced, never duplicated
    assert [w["state"] for w in log.memory_of(log.get_task(conn, row["task_id"]))] == ["done/passed/2", "done/passed/3"]


def test_a_fallback_that_delivers_stores_under_the_tasks_document_id(conn):
    fake = FakeHindsight()
    code, out, row, _ = _route(conn, chat="tray", worker=Scripted("FIRST", "FIXED"), chatgpt=Chat("FIX\n1. x", "FIX\n1. y"),
                               hindsight=fake.client)
    assert row["check_state"] == "failed" and fake.retains == []
    lines, clock, hook, redo = [], Clock(), Webhook(), Chat("REDO two lines")
    code = cli.cmd_fallback([str(row["n"])], conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                            settings_paths=[], post=hook.post, worker=Scripted("PASS"), chatgpt=redo,
                            codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep,
                            clock=clock, wait=True, out=lines.append, hindsight=fake.client)
    assert code == 0, "\n".join(lines)
    after = log.get_task(conn, row["task_id"])
    item = _retain_of(fake)
    assert item["document_id"] == f"task-{row['task_id']}" and item["content"] == f"{TASK}\n\nREDO two lines"
    assert item["metadata"]["doer"] == "chatgpt" and item["metadata"]["status"].startswith("passed")
    assert log.memory_of(after)[0]["state"].startswith("done/passed/")


# ---------- sr memory rebuild (decision 13) ----------

def _populated(path):
    c = log.init_db(path)
    rows = [_done(c, f"sr-{i}", f"task {i}", f"result {i}", at=T0 + timedelta(hours=i)) for i in (1, 2)]
    _done(c, "sr-f", "failed task", "failed result", check_state="failed", check_note="not passed", at=T0 + timedelta(hours=3))
    _done(c, "sr-u", "plain task", "plain result", chat=None, at=T0 + timedelta(hours=4))
    rows.append(_done(c, "sr-p", "project task", "project result", chat=None, project="demo", do_text="project result" + SECTION,
                      at=T0 + timedelta(hours=5)))
    rows.append(_done(c, "sr-k", "key task", "result\nJEV_API_KEY=abcdefghijklmnop", at=T0 + timedelta(hours=6)))
    c.close()
    return rows


def _rebuild(fake, path, ask=lambda q: "y"):
    lines = []
    code = cli.cmd_memory(["rebuild"], request=fake.request, environ={}, home=path.parent, popen=None, sleep=None, clock=None,
                          kill=None, db_path=path, secrets=[SECRET], ask=ask, out=lines.append)
    return code, lines


def test_rebuild_clears_the_bank_then_stores_every_storable_tagged_task_oldest_first(tmp_path):
    path = tmp_path / "router.db"
    rows = _populated(path)
    fake = FakeHindsight(documents={"task-old": {"content": "stale", "tags": ["chat:tray"]}})
    code, lines = _rebuild(fake, path)
    assert code == 0, lines
    assert [r["route"] for r in fake.requests] == ["health", "clear", "retain", "retain", "retain"]
    assert [i["document_id"] for i in fake.retains] == ["task-sr-1", "task-sr-2", "task-sr-p"]
    assert fake.retains[2]["content"].endswith(SECTION) and fake.retains[2]["tags"] == ["project:demo"]
    assert "task-old" not in fake.documents and len(fake.documents) == 3
    assert lines[0] == "memory: bank super-router cleared (1 memories deleted)"
    assert lines[-2] == "memory: rebuilt: stored 3, skipped 1" and lines[-1] == "  skipped (looks like a key): #6"
    c = log.init_db(path)
    assert [log.memory_of(log.get_task(c, t))[-1].get("document_id") for t in ("sr-1", "sr-2", "sr-p")] == ["task-sr-1", "task-sr-2", "task-sr-p"]
    assert log.memory_of(log.get_task(c, "sr-k"))[-1]["skipped"] == "looks like a key"
    assert log.memory_of(log.get_task(c, "sr-f")) == [] and log.memory_of(log.get_task(c, "sr-u")) == []
    c.close()


def test_rebuild_is_idempotent_and_counts_every_ten(tmp_path):
    path = tmp_path / "router.db"
    c = log.init_db(path)
    for i in range(1, 13):
        _done(c, f"sr-{i}", f"task {i}", f"result {i}", at=T0 + timedelta(hours=i))
    c.close()
    fake = FakeHindsight()
    code, lines = _rebuild(fake, path)
    assert code == 0 and "memory: stored 10 so far" in lines and lines[-1] == "memory: rebuilt: stored 12, skipped 0"
    assert len(fake.documents) == 12
    code, lines = _rebuild(fake, path)
    assert code == 0 and len(fake.documents) == 12 and len(fake.retains) == 24


def test_rebuild_keeps_going_past_a_failed_retain_and_groups_the_reasons(tmp_path):
    path = tmp_path / "router.db"
    _populated(path)

    class Flaky(FakeHindsight):
        def _answer(self, route, method, path_, json):
            if route == "retain" and json["items"][0]["document_id"] == "task-sr-2":
                raise __import__("requests").exceptions.Timeout("slow")
            return super()._answer(route, method, path_, json)
    fake = Flaky()
    code, lines = _rebuild(fake, path)
    assert code == 0 and lines[-3] == "memory: rebuilt: stored 2, skipped 2"
    assert sorted(lines[-2:]) == sorted(["  skipped (looks like a key): #6",
                                         "  skipped (unavailable (timed out after 20 s (POST /v1/default/banks/super-router/memories))): #2"])


def test_rebuild_refuses_without_y_a_terminal_or_the_store(tmp_path):
    path = tmp_path / "router.db"
    _populated(path)
    fake = FakeHindsight()
    code, lines = _rebuild(fake, path, ask=lambda q: "n")
    assert code == 0 and lines == ["Nothing was changed."] and fake.of("clear") == [] and fake.retains == []
    code, lines = _rebuild(fake, path, ask=None)
    assert code == 2 and lines == ["Refused: sr memory rebuild asks y/N and needs a terminal. Nothing was changed."]
    code, lines = _rebuild(FakeHindsight(online=False), path)
    assert code == 2 and lines == ["Refused: memory is offline (http://127.0.0.1:8888); sr memory start first. Nothing was changed."]
    asked = []
    _rebuild(fake, path, ask=lambda q: asked.append(q) or "y")
    assert asked == ["Clear bank super-router and reload every delivered tagged task from the log? [y/N] "]
