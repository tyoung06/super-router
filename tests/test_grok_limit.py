"""Build brief 15, phase D: Grok's prompt limit (rules v2.21, Relay). A Grok call that hands Grok an earlier result
to judge or build on (a check, a re-check, a review, or a relay stage given an earlier stage's result) is never sent
past `grok_prompt_limit` in config/settings.json: the round or stage fails with `too long for Grok (<n> characters)`.
A Grok fix round is exempt (its fix list comes first), and so are a `do`, a stage from the task alone and a re-ask
(the owner's D3). Until the owner writes the number the router uses 3,800 and `sr probe` says so, with no call.
Every value here is fake."""
import json

import pytest

from router import __main__ as cli
from router import log, settings
from tests.test_loop import Scripted, Webhook, _route
from tests.test_relay import GOOD_NOTE
from tests.test_slots_readers import REVIEW, _relay

BULK = {"status": "ok", "label": "bulk_text", "confidence": 0.93, "needs_split": 0.1, "tokens": 764}


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def limit(monkeypatch, tmp_path):
    """Write grok_prompt_limit into a scratch settings file."""
    def set_to(value):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"drop_folder": "~/x", "grok_prompt_limit": value}))
        monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    return set_to


# ---------- the setting ----------

def test_the_default_is_3800_until_the_owner_writes_the_number(monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"drop_folder": "~/x"}))
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    assert settings.grok_prompt_limit() == (3800, "default")
    assert settings.DEFAULT_GROK_PROMPT_LIMIT == 3800


def test_the_number_the_owner_writes_is_used(limit):
    limit(3650)
    assert settings.grok_prompt_limit() == (3650, "config/settings.json")


@pytest.mark.parametrize("value", ["3800", 0, -5, 3.5, True, None])
def test_a_value_that_is_not_a_positive_whole_number_falls_back_to_the_default_and_says_so(limit, value):
    limit(value)
    number, source = settings.grok_prompt_limit()
    assert number == 3800 and source.startswith("default") and "not a positive whole number" in source


def test_the_shipped_settings_file_holds_the_owners_measured_limit():
    # brief 15: Claude Code measured M037 (3,862 to 3,961 characters); the owner wrote measured minus 200 (a36a2d0)
    assert json.loads(settings.SETTINGS_PATH.read_text())["grok_prompt_limit"] == 3662
    assert settings.grok_prompt_limit() == (3662, "config/settings.json")


def test_the_probe_line_says_which_number_and_where_it_came_from(limit, monkeypatch, tmp_path):
    path = tmp_path / "plain.json"
    path.write_text(json.dumps({"drop_folder": "~/x"}))
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    assert cli.grok_limit_line() == ("grok prompt limit: 3800 (default; you haven't written grok_prompt_limit in "
                                     "config/settings.json)")
    limit(3650)
    assert cli.grok_limit_line() == "grok prompt limit: 3650 (config/settings.json)"


def test_sr_probe_prints_the_line_and_makes_no_call_for_it(limit, monkeypatch):
    limit(3650)
    from types import SimpleNamespace
    fake = SimpleNamespace(codex_version="0.162.1", seconds=1.0, checks=[], notes=[], passed=True)
    monkeypatch.setattr(cli.codex_probe, "probe", lambda **kw: fake)
    lines = []
    assert cli.cmd_probe(model="gpt-x", config={}, environ={}, home=None, login=lambda: True, out=lines.append) == 0
    assert "grok prompt limit: 3650 (config/settings.json)" in lines


# ---------- refused past the limit ----------

def test_a_grok_check_past_the_limit_is_skipped_and_the_next_checker_checks_c11(conn, limit):
    """Brief 24 (the owner's C11): a Grok check that would pass its limit is skipped when the checker is chosen. No failed
    row, the task's one takeover is not used, and the skip goes in check_note (and on the card)."""
    limit(600)
    long = "A built result. " * 60   # the check prompt carries it
    code, out, row, hook, *_ = _relay(conn, "research-build", [("check", "grok")],
                                      bodies={"s1": GOOD_NOTE, "c1": "PASS"}, claude=[long], chat=["PASS"])
    assert [s["task_id"].rsplit("-", 1)[1] for s in hook.sent] == ["s1"]   # the check never left for Grok
    checks = [c for c in log.calls_for(conn, row["task_id"]) if c["kind"] == "check"]
    assert [(c["call_id"].rsplit("-", 1)[1], c["agent"], c["status"]) for c in checks] == [("c1", "chatgpt", "done")]
    assert row["check_note"].startswith("Grok skipped: the check is too long for Grok (")
    assert int(row["check_note"].split("(")[1].split()[0]) > 600
    assert (row["checker"], row["check_state"]) == ("chatgpt", "passed")
    assert "Grok skipped: the check is too long for Grok (" in out and "ChatGPT checks instead." in out


def test_a_grok_review_past_the_limit_stops_the_chain_with_the_reason(conn, limit):
    limit(900)
    long_a = "Candidate A says a lot. " * 60
    code, out, row, hook, *_ = _relay(conn, "versus", [("b", "grok")], bodies={"s2": "B.", "s3": REVIEW},
                                      claude=[long_a, REVIEW])
    keys = [s["task_id"].rsplit("-", 1)[1] for s in hook.sent]
    assert keys == ["s2"]   # build B (the task alone) went; the review of A did not
    assert row["status"] == "failed" and row["failed_stage"] == 3
    assert "relay failed at stage 3 (review by grok): too long for Grok (" in row["result"]
    assert "RELAY FAILED at stage 3 (review by grok): too long for Grok (" in out


def test_a_grok_stage_given_an_earlier_result_past_the_limit_stops_the_chain(conn, limit):
    limit(500)
    code, out, row, hook, *_ = _relay(conn, "research-build", [("research", "chatgpt"), ("build", "grok"),
                                                               ("check", "claude")], chat=[GOOD_NOTE * 3])
    assert hook.sent == [] and row["failed_stage"] == 2
    assert "relay failed at stage 2 (build by grok): too long for Grok (" in row["result"]


# ---------- sent ----------

def test_a_grok_fix_round_past_the_limit_is_sent(conn, limit):
    limit(10)   # every Grok prompt here is longer; only the do and the fix go to Grok, and both are exempt
    hook = Webhook(do="Grok's first text.", f1="Grok's fixed text.")
    worker = Scripted("FIX\n1. Shorter, please.", "PASS")
    code, out, row, worker, hook = _route(conn, "@grok Reword these three lines.", BULK, worker=worker, hook=hook)
    kinds = [c["kind"] for c in log.calls_for(conn, row["task_id"])]
    assert kinds == ["do", "check", "fix", "recheck"] and len(hook.sent) == 2 and len(hook.sent[1]["task"]) > 10
    assert (row["status"], row["check_state"]) == ("done", "fixed")


def test_a_grok_re_ask_is_exempt(conn, limit):
    limit(300)  # the re-ask carries Grok's own thin note; research by Grok gets the task alone
    from tests.test_relay import THIN
    code, out, row, hook, *_ = _relay(conn, "research-build", [], bodies={"s1": THIN * 4, "s1r": GOOD_NOTE},
                                      claude=["Built."], chat=["PASS"])
    keys = [s["task_id"].rsplit("-", 1)[1] for s in hook.sent]
    assert keys == ["s1", "s1r"] and len(hook.sent[1]["task"]) > 300 and row["check_state"] == "passed"


def test_under_the_limit_every_grok_call_is_sent(conn):
    code, out, row, hook, *_ = _relay(conn, "versus", [("b", "grok")], bodies={"s2": "B.", "s3": REVIEW},
                                      claude=["A.", REVIEW])
    assert [s["task_id"].rsplit("-", 1)[1] for s in hook.sent] == ["s2", "s3"] and relay_awaiting(row)


def relay_awaiting(row):
    from router import relay
    return relay.awaiting_pick(row)
