"""Brief 29.1 (decision 24, D18 fix 1): a task with `--project` or `--chat` routes on Jev's top label from 0.4. Under 0.4,
or `none_of_these`, it runs as the router's follow-up with no question: Claude does it and ChatGPT checks (ChatGPT does it
and Claude checks when Claude isn't available), the row's skill `follow_up` with skill_source `router`, Jev's label and
confidence kept, and the doer gets one line to read the newest tasks in the memory block. Jev's stored status is judged
against the task's own floor. `follow_up` is never a `--skill`. Untagged tasks keep the 0.8 floor and the question. A
project split's route piece follows the same rule at the plan. Fakes only; every value fake."""
import pytest

from router import __main__ as cli
from router import availability, checking, jev, log, routing
from tests.helpers import fake_label, shipped_roster
from tests.test_chat_intake import TASK, _route, conn  # noqa: F401 (the fixture)
from tests.test_loop import Scripted
from tests.test_relay import Chat
from tests.test_status import _status, world  # noqa: F401 (the status fixture)

ROSTER = shipped_roster()


def jev_at(label, confidence):
    return {"status": "below_floor" if confidence < 0.8 else "ok", "label": label, "confidence": confidence,
            "needs_split": 0.1, "tokens": 300}


@pytest.mark.parametrize("label, confidence, tagged, status", [
    ("writing", 0.39, True, "below_floor"), ("writing", 0.4, True, "ok"), ("writing", 0.5, False, "below_floor"),
    ("none_of_these", 0.9, True, "none_of_these"), ("none_of_these", 0.3, True, "below_floor"),
])
def test_the_stored_status_is_judged_against_the_tasks_own_floor(label, confidence, tagged, status):
    answer = jev_at(label, confidence)
    if label == "none_of_these" and confidence >= 0.8:
        answer["status"] = "none_of_these"
    assert jev.judge(answer, ROSTER, tagged=tagged)["status"] == status
    assert jev.floor_of(ROSTER, True) == 0.4 and jev.floor_of(ROSTER, False) == 0.8


def test_a_tagged_task_under_04_runs_as_a_follow_up_with_no_question(conn):
    worker, chat = Scripted("Line one for the earlier trays."), Chat("PASS")
    code, out, row, _ = _route(conn, chat="tray", jev=jev_at("writing", 0.39), worker=worker, chatgpt=chat)
    assert code == 0, out
    assert (row["skill"], row["skill_source"], row["agent"], row["checker"], row["check_state"]) == (
        "follow_up", "router", "claude", "chatgpt", "passed")
    assert (row["jev_label"], row["jev_confidence"], row["jev_status"]) == ("writing", 0.39, "below_floor")
    assert worker.prompts[0].startswith(f"{TASK}\n\n{checking.FOLLOW_UP_LINE}\n\n{checking.DELIVERABLE_LINE}")
    assert "follow_up (the router: Jev's label writing at 0.39 is under the 0.4 floor for a tagged task" in out


def test_none_of_these_on_a_tagged_task_is_a_follow_up_too(conn):
    answer = {**jev_at("none_of_these", 0.9), "status": "none_of_these"}
    code, out, row, _ = _route(conn, chat="tray", jev=answer, worker=Scripted("done"), chatgpt=Chat("PASS"))
    assert code == 0 and (row["skill"], row["skill_source"]) == ("follow_up", "router"), out


def test_a_tagged_task_at_04_routes_on_its_label_and_never_stores_below_floor(conn):
    code, out, row, _ = _route(conn, chat="tray", jev=jev_at("writing", 0.4), worker=Scripted("done"), chatgpt=Chat("PASS"))
    assert code == 0 and (row["skill"], row["skill_source"], row["jev_status"]) == ("writing", "jev", "ok"), out
    assert checking.FOLLOW_UP_LINE not in out


def test_an_untagged_task_at_05_still_asks(conn):
    code, out, row, _ = _route(conn, jev=jev_at("writing", 0.5), worker=Scripted("done"), chatgpt=Chat("PASS"))
    assert code == 4 and row["status"] == "returned" and row["reason_code"] == "needs_label", out
    assert row["jev_status"] == "below_floor" and row["skill"] is None


def test_a_label_v2_does_not_route_still_comes_back_on_a_tagged_task(conn):
    code, out, row, _ = _route(conn, chat="tray", jev=jev_at("computer_use", 0.6), worker=Scripted("x"))
    assert code == 4 and row["reason_code"] == "not_routed", out


def test_with_claude_not_available_chatgpt_does_it_and_claude_checks():
    def table(name):
        if name == "claude":
            return availability.Availability(False, "Claude is signed out", "signed_out")
        return availability.Availability(True, None, None)
    decision = routing.decide(jev_at("writing", 0.2), ROSTER, tagged=True, available=table)
    assert (decision.skill, decision.skill_source, decision.agent) == ("follow_up", "router", "chatgpt")
    assert decision.reason.startswith("stand-in for claude") and decision.checker is None  # nobody else may check
    both = routing.decide(jev_at("writing", 0.2), ROSTER, tagged=True)
    assert (both.agent, both.checker, both.check_state) == ("claude", "chatgpt", "pending")


def test_follow_up_is_never_a_skill_to_pick(conn):
    lines = []
    code = cli.cmd_route(TASK, conn=conn, config={}, roster=ROSTER, environ={}, settings_paths=[], label=fake_label(),
                         post=None, worker=Scripted(), out=lines.append, skill="follow_up", chat="tray")
    assert code == 2 and "follow_up is the router's route for a tagged task Jev isn't sure of, not a skill" in "\n".join(lines)
    assert log.recent_tasks(conn) == []
    assert "follow_up" not in ROSTER.skills


def test_status_shows_the_tagged_floor_beside_the_floor(world):
    doc = _status(world)
    assert (doc["jev"]["floor"], doc["jev"]["tagged_floor"]) == (0.8, 0.4)


# ---------- a project split's route piece (decision 24) ----------

def test_a_project_splits_route_piece_under_04_is_a_follow_up_at_the_plan(tmp_path, monkeypatch):
    from router import jsonview, projects, split
    from tests.helpers import teamed
    from tests.test_split_approve import Jev
    from tests.test_split_project import JOIN, P1, P2, TASK as SPLIT_TASK
    from tests.test_split_project_flow import World
    monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "config" / "projects.json")
    folder = tmp_path / "sums"
    folder.mkdir()
    (folder / "HANDOFF.md").write_text("# sums\n\n<!-- sr:start -->\n<!-- sr:end -->\n")
    projects.add("sums", str(folder))
    conn = log.init_db(":memory:")
    low = {"status": "below_floor", "label": "code", "confidence": 0.3, "needs_split": 0.1, "tokens": 300}
    ok = {"status": "ok", "label": "code", "confidence": 0.95, "needs_split": 0.1, "tokens": 300}
    w = World(("piece one done", {}), ("piece two done", {}), ("joined", {}), chatgpt=("PASS", "PASS", "PASS"))
    plan = teamed(f"## Pieces\n1. {P1}\n2. {P2}\n\n## Join\n{JOIN}\n")
    w.worker.steps.insert(0, (plan, {}))
    kw = {k: v for k, v in w.kw().items() if k != "label"}
    cli.cmd_split(SPLIT_TASK, conn=conn, project="sums", files_ready=lambda: (False, "off for this test"),
                  label=Jev({P1: ok, P2: low}), **{**kw, "ask": None})
    row = next(r for r in log.recent_tasks(conn, 50) if r["mode"] == "split")
    pieces = jsonview.show_view(conn, row, roster=ROSTER)["pieces"]
    second = pieces[1]
    assert second["needs_label"] is False and second["route"]["skill"] == "follow_up", second
    assert log.split_plan_of(log.get_task(conn, row["task_id"]))["pieces"][1]["label"]["status"] == "below_floor"
    code = cli.cmd_split_go([str(row["n"])], answer="y", label=Jev({P1: ok, P2: low}), **{**kw, "conn": conn, "ask": None})
    made = log.pieces_of(conn, row["task_id"])
    assert [(p["skill"], p["skill_source"]) for p in made] == [("code", "jev"), ("follow_up", "router")], w.out
    conn.close()
