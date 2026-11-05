"""Cleanup 2, row 13: `sr serve --demo all-up` and the demo's three data fixes. Everything here reads the invented demo/."""
import json
from pathlib import Path

import pytest

from router import __main__ as cli
from router import page

DEMO = Path(__file__).resolve().parent.parent / "demo"


def _read(name):
    return json.loads((DEMO / name).read_text(encoding="utf-8"))


def _task(n):
    row = next(t for t in _read("log.json")["tasks"] if t["n"] == n)
    return _read(f"tasks/{row['task_id']}.json")


@pytest.fixture
def served(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.page, "serve_demo", lambda port, **kw: seen.update(demo_port=port, **kw) or 0)
    return seen


def test_the_all_up_status_has_every_agent_available_jev_set_up_and_memory_online():
    status = _read("status-all-up.json")
    assert [(a["name"], a["available"], a["why_code"]) for a in status["agents"]] == [
        ("claude", True, None), ("chatgpt", True, None), ("grok", True, None), ("cursor", True, None)]
    assert all(a["online"] is True for a in status["agents"])
    assert (status["jev"]["configured"], status["jev"]["available"], status["jev"]["tokens_month"], status["jev"]["cap"]) == (True, True, 32000, 1000000)
    assert status["memory"]["online"] is True and status["memory"]["starting"] is False
    assert status["presets"] and all(p["ready"] for p in status["presets"]), [p["name"] for p in status["presets"] if not p["ready"]]
    assert status["version"] == "2.55"


def test_the_plain_demo_keeps_every_state():
    status = _read("status.json")
    assert [(a["available"], a["why_code"]) for a in status["agents"]] == [
        (True, None), (False, "signed_out"), (False, "not_configured"), (False, "probe_failed")]
    assert status["version"] == "2.55"


def test_the_all_up_file_holds_no_value_only_the_word_set():
    text = (DEMO / "status-all-up.json").read_text(encoding="utf-8")
    assert "invented-hook" not in text and "invented-key" not in text


def test_sr_serve_demo_stays_as_it_is(served):
    assert cli.main(["serve", "--demo", "--port", "9100"]) == 0
    assert served == {"demo_port": 9100, "out": served["out"]}


def test_sr_serve_demo_all_up_asks_for_the_all_up_status(served):
    assert cli.main(["serve", "--demo", "all-up", "--port", "9100"]) == 0
    assert served["demo_port"] == 9100 and served["status_name"] == "status-all-up.json"


def test_another_word_is_refused(served):
    with pytest.raises(SystemExit) as e:
        cli.main(["serve", "--demo", "sideways"])
    assert e.value.code == 2 and not served


def test_the_demo_reader_serves_the_status_file_it_was_given():
    assert json.loads(page.DemoReader(DEMO).status()[1])["agents"][1]["available"] is False
    assert json.loads(page.DemoReader(DEMO, status_name="status-all-up.json").status()[1])["agents"][1]["available"] is True
    assert page.DemoReader(DEMO, status_name="status-all-up.json").status_doc()["jev"]["configured"] is True


@pytest.mark.parametrize("n", [69, 68])
def test_a_redteam_step_has_two_attack_lists_and_no_fix_after_its_last_recheck(n):
    show = _task(n)
    assert len(show["attack_lists"]) == 2, show["attack_lists"]
    calls = [c["kind"] for c in show["calls"]]
    assert calls[-3:] == ["check", "fix", "recheck"], calls
    first = next(c for c in show["calls"] if c["kind"] == "check")
    assert first["verdict"] == "FIX"


def test_the_trellis_runs_budget_sentence_stays_true():
    run = next(t for t in _read("log.json")["tasks"] if t.get("mode") == "auto" and t.get("project") == "trellis-plan")
    record = run["auto"]
    assert (record["used"], record["budget"]) == (14, 14)
    assert "14 of 14" in record["stop"]["why"] and "budget is reached" in record["stop"]["why"]
