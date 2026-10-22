"""Build brief 21, A3 (rules v2.30, Router for the interface): every action takes `--json` (route, relay, split, resume,
fallback, pick, cancel, check, project, chat) and answers with one object, `{task_id, n, status, waiting_on, outcome,
reason_code, exit, message}`, `message` being the prose `sr` prints today; on stdout for exit 0, 3, 4 and 5, on stderr
(same shape) for 1, 2 and 130. Exit codes unchanged; without `--json` the prose is printed as before and no JSON line
appears. `--json` asks nothing and waits for nothing, as when output isn't a terminal. Ids everywhere: an `sr-` id or a
unique prefix of one names a task, an ambiguous prefix is refused. Everything through the redactor. Fake agents, Jev
and webhook, driven through the real `main`; every value here is fake."""
import json

import pytest

from router import __main__ as cli
from router import ids, log, projects
from tests.helpers import fake_label
from tests.test_loop import Scripted
from tests.test_relay import Chat, RelayHook

FAKE_ENV = {"GROK_WEBHOOK_URL": "https://example.invalid/hook-FAKEURL-31", "GROK_WEBHOOK_KEY": "FAKE-WEBHOOK-KEY-77",
            "JEV_API_KEY": "FAKE-JEV-KEY-55"}
KEYS = ["task_id", "n", "status", "waiting_on", "outcome", "reason_code", "exit", "message"]


def jev(label, confidence=0.93, status="ok"):
    return {"status": status, "label": label, "confidence": confidence, "needs_split": 0.1, "tokens": 700}


class World:
    """The real main with every outside thing faked: .env, Jev, the workers, the webhook and inbox, the workspace."""

    def __init__(self, monkeypatch, tmp_path, capsys):
        self.capsys, self.count = capsys, 0
        self.label, self.worker, self.chatgpt, self.hook = fake_label(jev("writing")), Scripted(), Chat("PASS"), RelayHook()
        monkeypatch.setattr(cli, "dotenv_values", lambda path: dict(FAKE_ENV))
        monkeypatch.setattr(cli.jev, "label", lambda text, *, task_id, roster, api_key, tokens_this_month:
                            self.label(text, task_id=task_id, tokens_this_month=tokens_this_month))
        monkeypatch.setattr(cli, "_workers", lambda environ, model, cursor_model=None: (self.worker, self.chatgpt, None))
        monkeypatch.setattr(cli.chatgpt_worker, "login_status", lambda *a, **k: True)
        monkeypatch.setattr(cli.inbox, "fetch_issues", lambda *a, **k: self.hook.fetch())
        monkeypatch.setattr(cli.inbox, "close_issue", lambda number, *a, **k: self.hook.close(number))
        monkeypatch.setattr(cli.requests, "post", lambda *a, **k: self.hook.post(*a, **k))
        monkeypatch.setattr(cli.safety, "prepare_workspace", lambda *a, **k: None)
        monkeypatch.setattr(cli, "_claude_gate", lambda config, out: (lambda mode=None: False))  # brief 22: no probe
        monkeypatch.setattr(cli.drop, "folder", lambda *a, **k: None)
        monkeypatch.setattr(cli, "_can_ask", lambda: True)              # a terminal: --json must still ask nothing
        monkeypatch.setattr(cli, "_stdout_is_terminal", lambda: True)   # ...and wait for nothing
        monkeypatch.setattr(ids, "new_task_id", self._next_id)
        monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "config" / "projects.json")

    def _next_id(self, now=None):
        self.count += 1
        return f"sr-20261020-0000{self.count:02d}-ab{self.count:02d}"

    def run(self, *argv):
        code = cli.main(list(argv))
        out, err = self.capsys.readouterr()
        return code, out, err

    def json(self, *argv):
        code, out, err = self.run(*argv, "--json") if "--" not in argv else self.run(*argv)
        stream = out if code in (0, 3, 4, 5) else err
        other = err if code in (0, 3, 4, 5) else out
        assert other == "", f"the other stream must stay empty: {other!r}"
        lines = stream.splitlines()
        assert len(lines) == 1, stream
        found = json.loads(lines[0])
        assert list(found) == KEYS or list(found) == KEYS + ["tasks"], list(found)
        assert found["exit"] == code
        return found

    def row(self, n=1):
        conn = log.init_db(cli.DB_PATH)
        try:
            return log.task_by_number(conn, n)
        finally:
            conn.close()


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    return World(monkeypatch, tmp_path, capsys)


def _json_objects(text):
    """Every line of `text` that parses as a JSON object."""
    found = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            found.append(value)
    return found


@pytest.mark.parametrize("argv", [["route", "what is 17 times 23"], ["route", "   "], ["relay", "nope", "x"], ["cancel"],
                                  ["check"], ["project", "list"], ["chat", "list"], ["log"], ["show"],
                                  ["route", "--build", "claude", "x"]])
def test_without_json_no_json_object_is_ever_printed(world, argv):
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("391")
    code, out, err = world.run(*argv)
    assert _json_objects(out) == [] and _json_objects(err) == [], (argv, out, err)


# ---------- route ----------

def test_a_quick_answer_is_one_json_object_with_the_prose_as_its_message(world):
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("391")
    found = world.json("route", "what is 17 times 23")
    row = world.row()
    assert found == {"task_id": row["task_id"], "n": 1, "status": "done", "waiting_on": None, "outcome": "unchecked",
                     "reason_code": None, "exit": 0, "message": found["message"]}
    assert found["message"].splitlines() == [f"{row['task_id']}: quick_answer (Jev, confidence 0.99) -> claude, the skill's "
                                             "best agent.", f"{row['task_id']} done by claude:", "391"]


def test_the_message_is_exactly_what_sr_prints_without_json(world, monkeypatch, tmp_path):
    world.label, world.worker, world.chatgpt = fake_label(jev("writing")), Scripted("A poem."), Chat("PASS")
    code, out, err = world.run("route", "write a poem")
    assert code == 0 and err == "" and _json_objects(out) == []  # without --json, no JSON object on stdout
    plain = out.splitlines()
    log.init_db(cli.DB_PATH).execute("DELETE FROM tasks").connection.commit()
    world.count, world.worker, world.chatgpt = 0, Scripted("A poem."), Chat("PASS")
    found = world.json("route", "write a poem")
    assert found["message"].splitlines() == plain and found["outcome"] == "passed" and found["exit"] == 0


def test_a_task_that_comes_back_for_its_tag(world):
    world.label = fake_label(jev("recall", 0.97))
    found = world.json("route", "what did we decide about the tray")
    assert (found["status"], found["outcome"], found["waiting_on"], found["reason_code"], found["exit"]) == (
        "returned", "returned", None, "needs_tag", 4)
    assert log.calls_for(log.init_db(cli.DB_PATH), found["task_id"]) == []


def test_json_never_asks_even_in_a_terminal_so_a_floor_comes_back_needing_its_label(world):
    world.label = fake_label(jev("writing", 0.5, "below_floor"))
    found = world.json("route", "write something")
    assert (found["status"], found["waiting_on"], found["outcome"], found["reason_code"], found["exit"]) == (
        "returned", "needs_label", None, "needs_label", 4)


def test_json_never_waits_for_grok(world):
    world.label = fake_label(jev("x_social_pulse", 0.95))
    found = world.json("route", "what are gardeners saying about trays on X")
    assert (found["status"], found["waiting_on"], found["outcome"], found["exit"]) == ("sent", "grok", None, 0)
    assert world.hook.calls == 0  # the inbox was never read: nothing waited


@pytest.mark.parametrize("argv, code", [(["route", "   "], "bad_task"), (["route", "@muse write"], "not_live"),
                                        (["route", "--build", "claude", "write"], "slot_refused"),
                                        (["relay", "versus", "write", "--web"], "flag_refused"),
                                        (["route", "write", "--chat", "tray", "--project", "demo"], "tag_refused"),
                                        (["split", "write", "--chat", "tray"], "tag_refused"),
                                        (["relay", "nope", "write"], "bad_preset")])
def test_a_refusal_is_the_same_shape_on_stderr_with_no_task(world, argv, code):
    found = world.json(*argv)
    assert (found["task_id"], found["n"], found["status"], found["reason_code"], found["exit"]) == (None, None, None, code, 2)
    assert found["message"].startswith("Refused:")


def test_a_billing_switch(world, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-not-a-key")
    found = world.json("route", "write a poem")
    assert (found["reason_code"], found["exit"]) == ("billing_switch", 2)


def test_an_argparse_error_is_a_usage_refusal_in_json(world):
    found = world.json("route", "--bogus", "write")
    assert (found["reason_code"], found["exit"], found["task_id"]) == ("usage", 2, None)
    assert "unrecognized arguments: --bogus" in found["message"]


def test_help_under_json_is_one_object_too(world):
    found = world.json("route", "--help")
    assert found["exit"] == 0 and "usage:" in found["message"]


def test_an_unexpected_error_is_internal_error_with_the_type_name_only(world, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("something with FAKE-JEV-KEY-55 in it")
    monkeypatch.setattr(cli, "cmd_route", boom)
    found = world.json("route", "write a poem")
    assert (found["reason_code"], found["exit"], found["message"]) == ("internal_error", 1, "unexpected error: RuntimeError")


def test_source_ui_is_stored(world):
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("391")
    world.json("route", "what is 17 times 23", "--source", "ui")
    assert world.row()["source"] == "ui"


def test_no_env_value_reaches_the_json(world):
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("the key is FAKE-JEV-KEY-55 and "
                                                                               "FAKE-WEBHOOK-KEY-77")
    code, out, err = world.run("route", "repeat FAKE-WEBHOOK-KEY-77 and https://example.invalid/hook-FAKEURL-31", "--json")
    for value in FAKE_ENV.values():
        assert value not in out and value not in err and json.dumps(value)[1:-1] not in out
    assert "[REDACTED]" in json.loads(out)["message"]


# ---------- relay, split, pick, rescues, cancel, check ----------

A, B = "CANDIDATE-A", "CANDIDATE-B"
REVIEW = "## Verdict\npass\n\n## Notes\n- fine"


def test_relay_versus_waits_for_the_pick_and_pick_picks(world):
    world.worker, world.chatgpt = Scripted(A, REVIEW), Chat(B, REVIEW)
    found = world.json("relay", "versus", "a blurb")
    assert (found["status"], found["waiting_on"], found["outcome"], found["reason_code"], found["exit"]) == (
        "returned", "pick", None, None, 0)
    found = world.json("pick", "1", "a")
    assert (found["n"], found["status"], found["outcome"], found["exit"]) == (1, "done", "picked", 0)
    found = world.json("pick", "1", "b")
    assert (found["n"], found["reason_code"], found["exit"], found["outcome"]) == (1, "already_used", 2, "picked")


def test_split_stops_at_the_plan_without_asking(world):
    world.worker = Scripted("## Pieces\n1. List three tray brands.\n2. Write a haiku about trays.\n\n## Join\nList, then haiku.")
    found = world.json("split", "list trays and write a haiku")
    assert (found["status"], found["waiting_on"], found["exit"]) == ("returned", "split_plan", 0)


def test_resume_and_fallback_refusals_name_the_task(world):
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("391")
    done = world.json("route", "what is 17 times 23")
    for command, code in (("resume", "not_resumable"), ("fallback", "no_fallback")):
        found = world.json(command, "1")
        assert (found["task_id"], found["n"], found["outcome"], found["reason_code"], found["exit"]) == (
            done["task_id"], 1, "unchecked", code, 2)


def test_cancel_and_check(world):
    world.label = fake_label(jev("x_social_pulse", 0.95))
    sent = world.json("route", "what are gardeners saying about trays on X")
    found = world.json("check")
    assert (found["task_id"], found["status"], found["exit"]) == (None, None, 0)
    assert [(t["task_id"], t["waiting_on"]) for t in found["tasks"]] == [(sent["task_id"], "grok")]
    found = world.json("cancel", sent["task_id"])
    assert (found["task_id"], found["status"], found["outcome"], found["exit"]) == (sent["task_id"], "cancelled", "cancelled", 0)
    found = world.json("cancel")
    assert (found["reason_code"], found["exit"]) == ("wrong_state", 1)


def test_project_and_chat_lists_and_a_project_refusal(world, tmp_path):
    found = world.json("project", "add", "demo", str(tmp_path / "missing"))
    assert (found["reason_code"], found["exit"]) == ("project_refused", 2)
    code, out, err = world.run("project", "list", "--json")
    assert code == 0 and err == "" and json.loads(out) == {"api_version": 1, "projects": []}
    code, out, err = world.run("chat", "list", "--json")
    assert code == 0 and err == "" and json.loads(out) == {"api_version": 1, "chats": []}


# ---------- ids everywhere ----------

def test_an_id_or_a_unique_prefix_names_a_task_and_an_ambiguous_prefix_is_refused(world):
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("391", "392")
    first = world.json("route", "what is 17 times 23")
    second = world.json("route", "what is 17 times 23 plus one")
    assert world.json("resume", first["task_id"])["task_id"] == first["task_id"]
    assert world.json("resume", first["task_id"][:-2])["task_id"] == first["task_id"]  # a unique prefix
    found = world.json("resume", "sr-20261020")  # both tasks start so
    assert (found["task_id"], found["reason_code"], found["exit"]) == (None, "ambiguous_task", 2)
    assert first["task_id"] in found["message"] and second["task_id"] in found["message"]
    found = world.json("fallback", "sr-29991231")
    assert (found["reason_code"], found["exit"]) == ("unknown_task", 2)
    code, out, err = world.run("show", second["task_id"][:-1])
    assert code == 0 and second["task_id"] in out


def test_exit_codes_are_unchanged_by_json(world):
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted("391", "391")
    plain = world.run("route", "what is 17 times 23")[0]
    assert world.json("route", "what is 17 times 23")["exit"] == plain == 0
    assert world.run("route", "   ")[0] == world.json("route", "   ")["exit"] == 2
