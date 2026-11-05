"""Build brief 33.4: the new commands through `main`'s parser and routing, on refusal paths only, so no model is called: `sr
plan --answer` and `sr ideas --suggest` with `--json`, what a run of them may read, the hook on the real log, and the limits
in status. Every value is fake."""
import json

from router import __main__ as cli
from router import ideas, log, plan_limit
from tests.test_ideas33 import PROJECT, world  # noqa: F401 (the fixture)


def test_answer_on_a_task_not_waiting_is_refused_as_json(world):
    code, out, err = world.run("plan", "--answer", "99", "--best-guess", "--json")
    doc = json.loads(err or out)
    assert code == 2 and doc["exit"] == 2 and doc["reason_code"]


def test_pick_without_answer_is_a_usage_refusal(world):
    code, out, err = world.run("plan", "--pick", "1=A", "--json")
    assert code == 2 and json.loads(err or out)["reason_code"] == "usage"


def test_answer_with_a_task_text_is_a_usage_refusal(world):
    code, out, err = world.run("plan", "--answer", "1", "words", "--json")
    assert code == 2 and json.loads(err or out)["reason_code"] == "usage"


def test_suggest_past_the_limit_is_refused_through_main_with_nothing_written(world):
    code, out, err = world.run("ideas", PROJECT, "--add", "--json", "--", "first")
    assert code == 0
    conn = log.init_db(str(cli.DB_PATH))
    for k in range(47):
        ideas.add(conn, PROJECT, f"idea number {k}")
    code, out, err = world.run("ideas", PROJECT, "--suggest", "--json")
    doc = json.loads(err or out)
    assert code == 2 and doc["reason_code"] == "suggest_refused" and "48 open ideas" in doc["message"]
    assert not [r for r in log.project_tasks(conn, PROJECT) if r["mode"] == "suggest"]


def test_suggest_goes_alone(world):
    code, out, err = world.run("ideas", PROJECT, "--suggest", "--dismiss", "1", "--json")
    assert code == 2 and json.loads(err or out)["reason_code"] == "usage"


def test_the_hook_is_refused_on_the_real_log_through_main(monkeypatch, capsys):
    monkeypatch.setenv(plan_limit.QUESTIONS_ENV, "plan")
    monkeypatch.setattr(plan_limit, "main_checkout", lambda root, run=None: cli.DB_PATH.parent)
    assert cli.main(["log"], platform="darwin") == 2
    assert "Refused: SR_INJECT_QUESTIONS is test-only" in capsys.readouterr().out


def test_status_serves_the_limits(world):
    code, out, err = world.run("status", "--json")
    assert code == 0 and json.loads(out)["limits"] == {"idea_max": 2000, "ideas_max": 50}
