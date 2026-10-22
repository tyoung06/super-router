"""Build brief 23, decisions 15 and 18: `sr serve --demo` shows demo/, invented JSON and files made by
scripts/make_demo.py through the router's own commands (with fakes) and its real serializers, on a fixed clock with fixed
task ids. A fresh run must equal demo/ byte for byte (any drift fails here: run `python scripts/make_demo.py`). demo/ names
no home folder, no real user and no inbox repo, and holds one task of every kind the page draws. The run puts back every
module attribute it changes and reaches no command, model, webhook or network."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from router import ids, inbox, log, media, projects, runs, settings
from scripts import make_demo
from tests.test_inbox_setting import real_inbox_words

DEMO = Path(__file__).resolve().parent.parent / "demo"
REAL_POPEN = subprocess.Popen  # taken at import: conftest blocks real subprocesses, and git is this test's one


def _files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_the_demo_equals_a_fresh_make_demo_run(tmp_path):
    make_demo.build(tmp_path / "demo")
    fresh, kept = _files(tmp_path / "demo"), _files(DEMO)
    assert sorted(fresh) == sorted(kept), "demo/ is stale: run `python scripts/make_demo.py`"
    changed = [name for name in fresh if fresh[name] != kept[name]]
    assert changed == [], f"demo/ is stale ({changed[:5]}): run `python scripts/make_demo.py`"


@pytest.mark.skipif(shutil.which("git") is None or not (DEMO.parent / ".git").exists(), reason="not a git checkout")
def test_git_ignores_no_demo_file(monkeypatch):
    # The repo ignores media/ and tasks/ (real files, never committed). The demo's invented ones must be committed, or
    # a fresh clone's demo shows cards with no details and files that 404 (decision 15).
    monkeypatch.setattr(subprocess, "Popen", REAL_POPEN)
    names = [str(p.relative_to(DEMO.parent)) for p in sorted(DEMO.rglob("*")) if p.is_file()]
    proc = subprocess.run(["git", "check-ignore", "--no-index", "--stdin"], cwd=str(DEMO.parent), input="\n".join(names),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode in (0, 1), proc.stderr
    assert proc.stdout.split() == [], f"git ignores demo files: {proc.stdout.split()[:5]}"


def test_the_demo_names_no_home_folder_no_real_user_and_no_inbox_repo():
    # Build brief 24 (decision 11): the inbox repo and its owner come from this Mac's own settings file at run time, so
    # this test spells neither; without that file only the home folder and the temp folders are checked
    banned = [str(Path.home()), "/Users/", "/var/folders", *real_inbox_words()]
    found = [(name, word) for name, data in _files(DEMO).items() for word in banned if word.encode() in data]
    assert found == []


def test_the_demo_holds_one_task_of_every_kind():
    tasks = json.loads((DEMO / "log.json").read_text())["tasks"]
    states = {(t["mode"], t["preset"], t["waiting_on"], t["outcome"]) for t in tasks}
    for want in [("route", None, None, "passed"), ("route", None, None, "fixed"), ("route", None, None, "failed_check"),
                 ("route", None, None, "unchecked"), ("relay", "versus", "pick", None), ("relay", "versus", None, "picked"),
                 ("relay", "vote", None, "passed"), ("relay", "vote", "vote_pick", None), ("relay", "redteam", None, "passed"),
                 ("route", None, None, "plan_limit"), ("route", None, None, "process_ended"), ("route", None, "grok", None),
                 ("split", None, "split_plan", None), ("split", None, "piece", None), ("route", None, "needs_label", None),
                 ("route", None, None, "cancelled")]:
        assert want in states, want
    notes = {t["check_note"] for t in tasks}
    assert {"waiting: grok, 6 min", "overdue: grok, 12 min"} <= notes
    assert any(t["fallback"]["ok"] for t in tasks) and sum(t["resume"]["ok"] for t in tasks) == 2
    assert any(t["chat"] for t in tasks) and any(t["project"] for t in tasks)
    shows = {p.stem: json.loads(p.read_text()) for p in (DEMO / "tasks").glob("*.json")}
    assert any(s["memory_given"] for s in shows.values()) and any(s["memory_stored"] for s in shows.values())
    assert any(s["attacks"] for s in shows.values()) and any(s["candidates"] for s in shows.values())
    assert any(s["tally"] for s in shows.values()) and any(s["handoff"] for s in shows.values())
    assert any(p["needs_label"] for s in shows.values() for p in s["pieces"] or [])
    runs_doc = json.loads((DEMO / "runs.json").read_text())["runs"]
    assert any(r["exit"] == 2 and r["envelope"]["reason_code"] == "override_refused" for r in runs_doc)  # a refused send
    # brief 24 (decision 15's demo): a stand-in, a takeover after a plan limit, an overdue takeover with its late answer,
    # make_media back without Grok Bot, a team refused for a missing agent, Jev not set up
    lines = {t["card_line"] for t in tasks}
    assert {"ChatGPT did this · Grok Bot isn't set up · done without Meta",
            "ChatGPT took over the first call · Claude hit its plan limit",
            "ChatGPT took over the first call · Grok Bot was overdue · done without Meta"} <= lines
    # The owner, 21 Oct: X research is Grok Bot's alone, so without it the task comes back, as make_media does
    assert any(t["reason_code"] == "unavailable" and t["skill"] == "x_social_pulse" for t in tasks)
    assert any(t["late"] and t["late"]["state"] == "arrived" and t["late"]["round_file"] for t in tasks)
    assert any(t["reason_code"] == "unavailable" and t["skill"] == "make_media" for t in tasks)
    assert any(r["exit"] == 2 and r["envelope"]["reason_code"] == "slot_refused" for r in runs_doc)
    assert any(t["jev"]["status"] == "not_set_up" and t["waiting_on"] == "needs_label" for t in tasks)
    for folder in ("tasks", "media/in", "media/pages", "media/frames", "media/out"):
        assert list((DEMO / "files" / folder).glob("sr-*/*")), folder


def test_the_demos_agents_show_every_state():
    status = json.loads((DEMO / "status.json").read_text())
    agents = {a["name"]: a for a in status["agents"]}
    assert agents["claude"]["online"] is True and agents["chatgpt"]["online"] is False
    assert agents["grok"]["reason"] == "not configured" and agents["cursor"]["probe"]["state"] == "failed"
    # brief 24: each with the router's own words, and Jev not set up
    assert [(a["available"], a["why_code"]) for a in status["agents"]] == [
        (True, None), (False, "signed_out"), (False, "not_configured"), (False, "probe_failed")]
    assert (status["jev"]["available"], status["jev"]["why"]) == (False, "Jev isn't set up: no JEV_API_KEY in .env")
    assert status["memory"]["starting"] is True and status["jev"]["floor"] == 0.8
    assert status["drop_folder"] == "~/Desktop/Router Drop" and status["report_path"].startswith("~/")


def test_make_demo_puts_back_everything_it_changes(tmp_path):
    before = (log._utc, ids.new_task_id, runs.FOLDER, media.MEDIA_ROOT, settings.LOCAL_PATH, projects.REGISTRY_PATH,
              inbox.fetch_file, log.ROUND_WRITER)
    make_demo.build(tmp_path / "demo")
    assert (log._utc, ids.new_task_id, runs.FOLDER, media.MEDIA_ROOT, settings.LOCAL_PATH, projects.REGISTRY_PATH,
            inbox.fetch_file, log.ROUND_WRITER) == before
