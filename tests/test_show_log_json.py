"""Build brief 21, B3 (rules v2.30, Status and JSON and Router for the interface; the owner's B3 amendments): `sr show <n>
--json` (the task row with its state, every call in order with its round file, served record, memory line and
timestamps, Jev, slots, the tag, the handoff attached or not, the memory records as stored and the entries given, both
candidates with their reviews and the pick on versus, the votes and the tally on vote, the attacks with what the
reviser answered on redteam, the pieces on a split, the furthest result, and the rescue offers computed by the deciders,
never stored) and `sr log --json` (the same task keys per row, newest first, `--limit`, `--project`, `--chat`,
`--search`, `--before` for paging; the filters work in text too). Both read only and redacted. Fakes only; every value
here is fake."""
import json

import pytest

from router import __main__ as cli, online
from router import log, split
from tests.fake_hindsight import FakeHindsight
from tests.fixtures import json_shapes
from tests.helpers import fake_label, sha256
from tests.test_json_actions import FAKE_ENV, World, jev
from tests.test_loop import Scripted
from tests.test_redteam_chain import ATTACKS, BUILD, REVISION
from tests.test_relay import Chat, RelayHook
from tests.test_resume_run import claude_limit


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    return World(monkeypatch, tmp_path, capsys)


def _show(world, *words):
    code, out, err = world.run("show", *words, "--json")
    assert code == 0 and err == "" and len(out.splitlines()) == 1, (out, err)
    doc = json.loads(out)
    json_shapes.check(doc, json_shapes.SHOW)
    return doc


def _log(world, *words):
    code, out, err = world.run("log", *words, "--json")
    assert code == 0 and err == "", (out, err)
    doc = json.loads(out)
    json_shapes.check(doc, json_shapes.LOG)
    return doc


# ---------- show: a routed task ----------

def test_a_fixed_task_lists_its_calls_in_order_with_their_records(world):
    world.worker, world.chatgpt = Scripted("Draft one.", "Draft two."), Chat("FIX\n1. Make it rhyme.", "PASS")
    world.json("route", "write a two-line poem")
    doc = _show(world, "1")
    assert (doc["status"], doc["outcome"], doc["waiting_on"], doc["check_state"], doc["result"]) == (
        "done", "fixed", None, "fixed", "Draft two.")
    assert [(c["order"], c["kind"], c["agent"], c["status"], c["verdict"]) for c in doc["calls"]] == [
        (1, "do", "claude", "done", None), (2, "check", "chatgpt", "done", "FIX"), (3, "fix", "claude", "done", None),
        (4, "recheck", "chatgpt", "done", "PASS")]
    assert [c["round_file"] for c in doc["calls"]] == [  # brief 21, C1: each call's round file
        f"tasks/{doc['task_id']}/{c['order']:02d}-{c['kind']}-{c['agent']}.md" for c in doc["calls"]]
    assert all(c["served"] is None and c["memory"]["state"] == "not_kept" for c in doc["calls"])
    assert doc["jev"]["label"] == "writing" and doc["tag"] is None and doc["handoff"] is None
    assert doc["fallback"] == {"ok": False, "agent": None, "reason": "not a double fail: it passed after one fix"}
    assert doc["resume"]["ok"] is False and doc["memory_stored"] == [] and doc["memory_given"] == []
    assert (doc["candidates"], doc["votes"], doc["attacks"], doc["pieces"], doc["pick"]) == (None, None, None, None, None)


def test_a_double_fail_is_failed_check_and_offers_the_fallback(world):
    world.worker, world.chatgpt = Scripted("Draft one.", "Draft two."), Chat("FIX\n1. Rhyme.", "FIX\n1. Still no rhyme.")
    world.json("route", "write a two-line poem")
    doc = _show(world, "1")
    assert (doc["outcome"], doc["waiting_on"]) == ("failed_check", None)
    assert doc["fallback"] == {"ok": True, "agent": "chatgpt", "reason": None}


def test_a_plan_limit_stop_is_its_own_outcome_and_offers_the_resume(world, monkeypatch):
    # brief 24 (decision 14): the offer stays for what the takeover couldn't do; here ChatGPT signs out between the intake
    # and the stop, so the router can't take over, and `sr resume` can once it is signed in again
    answers = iter([True, False])
    monkeypatch.setitem(online.CHECKS, "chatgpt", lambda: online.chatgpt(login=lambda: next(answers, False)))
    world.worker = Scripted(claude_limit())
    world.json("route", "write a two-line poem")
    doc = _show(world, "1")
    assert (doc["status"], doc["outcome"]) == ("failed", "plan_limit")
    assert doc["calls"][0]["reason_code"] == "plan_limit"
    assert doc["resume"] == {"ok": True, "substitute": "chatgpt", "agent": "chatgpt", "checker": "claude", "reason": None}


# ---------- show: versus, vote, redteam, split ----------

A, B = "CANDIDATE-A: one tray.", "CANDIDATE-B: two trays.\n\n## Missing\nno sizes"
PASS = "## Verdict\npass\n\n## Notes\n- fine"
FAIL = "## Verdict\nfail\n\n## Notes\n- invents a spec"


def test_versus_lists_both_candidates_with_their_reviews_and_the_pick(world):
    world.worker, world.chatgpt = Scripted(A, FAIL), Chat(B, PASS)
    world.json("relay", "versus", "a blurb")
    doc = _show(world, "1")
    assert (doc["waiting_on"], doc["pick"]) == ("pick", None)
    assert [(c["letter"], c["builder"], c["text"], c["missing"], c["review"]["reviewer"], c["review"]["verdict"])
            for c in doc["candidates"]] == [("a", "claude", A, None, "chatgpt", "pass"),
                                            ("b", "chatgpt", "CANDIDATE-B: two trays.", "no sizes", "claude", "fail")]
    world.json("pick", "1", "b")
    doc = _show(world, "1")
    assert (doc["outcome"], doc["pick"], doc["result"]) == ("picked", "b", "CANDIDATE-B: two trays.")


def _vote(answer):
    return f"## Answer\n{answer}\n\n## Why\nBecause.\n\n## Confidence\n70"


def test_vote_lists_the_answers_and_the_tally(world):
    world.worker, world.chatgpt = Scripted(_vote("Paris")), Chat(_vote("paris."))
    world.hook = RelayHook(s3=_vote("Lyon"))
    world.json("relay", "vote", "capital of France")
    world.json("check")  # collects grok's vote
    doc = _show(world, "1")
    assert doc["outcome"] == "passed"
    assert [(v["letter"], v["agent"], v["answer"], v["confidence"]) for v in doc["votes"]] == [
        ("a", "claude", "Paris", 70), ("b", "chatgpt", "paris.", 70), ("c", "grok", "Lyon", 70)]
    assert doc["tally"] == {"winner": "a", "for": 2, "against": 1, "note": "checked-by-vote 2/1", "dissent": ["c"]}


def test_redteam_lists_each_attack_with_what_the_reviser_answered(world):
    world.worker, world.chatgpt = Scripted(BUILD, REVISION), Chat(ATTACKS, "PASS")
    world.json("relay", "redteam", "a one-page budget ritual")
    doc = _show(world, "1")
    assert doc["outcome"] == "passed"
    assert doc["attacks"] == [
        {"n": 1, "severity": "high", "text": "No trigger for a change is defined.", "answered": None},
        {"n": 2, "severity": "medium", "text": "Groceries only.", "answered": None},
        {"n": 3, "severity": "low", "text": "Sunday may clash with plans.",
         "answered": "Sunday is the user's choice; the plan says to move it if needed."}]
    assert "## Answered" not in doc["result"]


def test_a_split_lists_its_pieces(world):
    conn = log.init_db(cli.DB_PATH)
    log.add_task(conn, "sr-s", "t", "cli", {"status": "not_asked", "tokens": 0}, mode="split")
    log.set_route(conn, "sr-s", agents=("claude", "chatgpt", "grok"), agent="claude", route_reason="split",
                  checker="chatgpt", check_state="pending")
    plan = split.new_plan(["piece one", "piece two"], "join", ["sr-p1", "sr-p2"])
    plan["approved"] = True
    plan["pieces"][1]["skipped"] = True
    log.set_split_plan(conn, "sr-s", plan)
    log.set_split_returned(conn, "sr-s", f"{log.WAITING_PIECES} #2")
    log.add_task(conn, "sr-p1", "piece one", "split", jev("writing"), mode="piece", parent="sr-s")
    conn.close()
    doc = _show(world, "1")
    assert doc["waiting_on"] == "piece"
    assert [(p["piece"], p["task_id"], p["n"], p["status"], p["skipped"], p["text"]) for p in doc["pieces"]] == [
        (1, "sr-p1", 2, "queued", False, "piece one"), (2, "sr-p2", None, None, True, "piece two")]


# ---------- show: memory, the handoff, errors ----------

def test_a_tagged_task_carries_its_memory_records_as_stored(world, monkeypatch):
    fake = FakeHindsight()
    monkeypatch.setattr(cli.memory, "client", lambda *a, **k: fake.client)
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("391")
    world.json("route", "what is 17 times 23", "--chat", "tray")
    doc = _show(world, "1")
    assert doc["tag"] == "chat:tray" and len(doc["memory_stored"]) == 1
    assert doc["memory_stored"][0]["document_id"] == f"task-{doc['task_id']}"
    assert doc["calls"][0]["memory"]["state"] == "sent" and doc["calls"][0]["memory"]["found"] == 0


def test_show_json_of_no_such_task_is_an_error_envelope(world):
    code, out, err = world.run("show", "7", "--json")
    found = json.loads(err)
    assert (code, out, found["reason_code"], found["message"]) == (1, "", "unknown_task", "No task #7.")


# ---------- log ----------

def test_log_json_rows_newest_first_with_their_state_and_offers(world):
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("391", "392", "393")
    for k in range(3):
        world.json("route", f"what is {k} times 23")
    doc = _log(world)
    assert [t["n"] for t in doc["tasks"]] == [3, 2, 1] and doc["next_before"] is None
    assert all(t["outcome"] == "unchecked" and t["fallback"]["ok"] is False for t in doc["tasks"])
    doc = _log(world, "--limit", "2")
    assert [t["n"] for t in doc["tasks"]] == [3, 2] and doc["next_before"] == doc["tasks"][-1]["task_id"]
    older = _log(world, "--limit", "2", "--before", doc["next_before"])
    assert [t["n"] for t in older["tasks"]] == [1] and older["next_before"] is None


def test_log_filters_in_json_and_in_text(world):
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("391", "392", "393")
    world.json("route", "what is 17 times 23", "--chat", "tray")
    world.json("route", "what is 18 times 23")
    world.json("route", "how tall is a tray", "--chat", "tray")
    assert [t["n"] for t in _log(world, "--chat", "tray")["tasks"]] == [3, 1]
    assert [t["n"] for t in _log(world, "--search", "TIMES")["tasks"]] == [2, 1]
    assert [t["n"] for t in _log(world, "--search", "%")["tasks"]] == []  # plain text, never a wildcard
    assert [t["n"] for t in _log(world, "--before", "3")["tasks"]] == [2, 1]
    code, out, err = world.run("log", "--search", "tall")
    assert code == 0 and "how tall is a tray" in out and "what is 17" not in out
    code, out, err = world.run("log", "--before", "sr-29991231", "--json")
    assert (code, json.loads(err)["reason_code"]) == (1, "unknown_task")


def test_log_project_filter(world, monkeypatch, tmp_path):
    conn = log.init_db(cli.DB_PATH)
    log.add_task(conn, "sr-a", "for the project", "cli", jev("writing"), project="demo")
    log.add_task(conn, "sr-b", "not for it", "cli", jev("writing"))
    conn.close()
    assert [t["task_id"] for t in _log(world, "--project", "demo")["tasks"]] == ["sr-a"]


def test_show_and_log_json_write_nothing_and_carry_no_env_value(world):
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("the key FAKE-JEV-KEY-55 leaked")
    world.json("route", "repeat FAKE-WEBHOOK-KEY-77")
    before = sha256(cli.DB_PATH)
    code, out1, err = world.run("show", "1", "--json")
    code, out2, err = world.run("log", "--json")
    assert sha256(cli.DB_PATH) == before
    for value in FAKE_ENV.values():
        assert value not in out1 + out2
    assert "[REDACTED]" in json.loads(out1)["result"] or "[REDACTED]" in json.loads(out1)["text"]


def test_a_json_read_with_no_log_makes_none(world):
    assert not cli.DB_PATH.exists()
    assert _log(world)["tasks"] == []
    code, out, err = world.run("show", "--json")
    assert (code, json.loads(err)["reason_code"]) == (1, "unknown_task")
    code, out, err = world.run("status", "--json")
    assert code == 0 and json.loads(out)["log_version"] == log.VERSION
    assert not cli.DB_PATH.exists()


def test_a_json_read_of_an_old_log_is_refused_and_changes_nothing(world):
    from tests.test_log_v14 import _make_v13
    _make_v13(cli.DB_PATH)
    before = sha256(cli.DB_PATH)
    for argv in (["log", "--json"], ["show", "1", "--json"]):
        code, out, err = world.run(*argv)
        found = json.loads(err)
        assert (code, found["reason_code"]) == (2, "setup") and "sr migrate" in found["message"]
    assert sha256(cli.DB_PATH) == before
