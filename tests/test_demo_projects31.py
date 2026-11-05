"""Build brief 31 (decision 12): the demo shows a project with a passed Test, a run going (invented output with its key
line masked) and Secrets with placeholder names; the page reads them as it reads the router's own answers, and no value
is anywhere in demo/. The demo answers 409 to every POST (tests/test_demo.py)."""
import json
from pathlib import Path

DEMO = Path(__file__).resolve().parent.parent / "demo"


def _project(name):
    return [p for p in json.loads((DEMO / "status.json").read_text())["projects"] if p["name"] == name][0]


def test_the_demo_project_has_a_passed_test_a_run_going_and_two_secrets():
    plots = _project("plot-planner")
    assert plots["last_test"]["outcome"] == "passed" and plots["run"]["running"] is True
    assert plots["run_command"] == ["python3", "planner.py", "--serve"] and plots["secrets"] == 2
    test = json.loads((DEMO / "project-output" / "plot-planner-test.json").read_text())["project"]["test_status"]
    assert test["running"] is False and "OK" in test["output"]
    run = json.loads((DEMO / "project-output" / "plot-planner-run.json").read_text())["project"]["run_status"]
    assert run["running"] is True and "[REDACTED]" in run["output"] and run["env_names"] == ["MAP_TILES_TOKEN", "WEATHER_API_KEY"]
    assert "log" not in run and run["folder"] == "~/Projects/plot-planner"
    names = json.loads((DEMO / "secrets" / "plot-planner.json").read_text())["project"]["secrets"]
    assert names == [{"name": "WEATHER_API_KEY", "set": True}, {"name": "MAP_TILES_TOKEN", "set": False}]


def test_no_secret_value_is_anywhere_in_the_demo():
    placeholder = "placeholder-" + "0000-0000"
    for path in DEMO.rglob("*"):
        if path.is_file() and path.suffix in (".json", ".md", ".txt"):
            assert placeholder not in path.read_text(encoding="utf-8", errors="replace"), path
