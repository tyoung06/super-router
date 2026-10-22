"""Build brief 21, the test plan's secret sweep (Phase 0, section 7, approved with the go): fake .env values planted in
task text, a result, a check note, call text, a file name and a project path; every JSON output (`sr status`, `show`,
`log`, the project and chat lists, each action's envelope and each error) and every round file on disk is searched for
each value, raw and JSON-escaped. The fake .env holds a fourth key besides the three the router redacts call text with
(`_secrets`): the JSON and the round files redact every .env value (Phase 0 choice 22), so a value only they cover
proves their own redaction. Fakes only; every value here is fake."""
import json

from router import __main__ as cli
from router import log
from tests.helpers import fake_label
from tests.test_json_actions import FAKE_ENV, World, jev
from tests.test_loop import Scripted
from tests.test_relay import Chat

KEY, HOOK_KEY, URL = FAKE_ENV["JEV_API_KEY"], FAKE_ENV["GROK_WEBHOOK_KEY"], FAKE_ENV["GROK_WEBHOOK_URL"]
OTHER = "FAKE-OTHER-TOKEN-99"
ENV = dict(FAKE_ENV, OTHER_TOKEN=OTHER)
REVIEW = "## Verdict\npass\n\n## Notes\n- fine"


def _found(text):
    """The planted values in `text`, raw or JSON-escaped (names only, for the message)."""
    return sorted(name for name, value in ENV.items() if value in text or json.dumps(value)[1:-1] in text)


def test_no_env_value_in_any_json_output_or_round_file(monkeypatch, tmp_path, capsys):
    world = World(monkeypatch, tmp_path, capsys)
    monkeypatch.setattr(cli, "dotenv_values", lambda path: dict(ENV))
    seen = []

    def run(*argv):
        code, out, err = world.run(*argv, "--json")
        seen.append((argv, out + err))
        return code

    # a routed task: the value in its text and its result (the round file is written from the result)
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted(f"result with {KEY}, {URL} and {OTHER}")
    run("route", f"the task text holds {HOOK_KEY}")
    # a double fail whose fix lists carry values, then its fallback
    world.label = fake_label(jev("writing"))
    world.worker, world.chatgpt = Scripted("draft one", "draft two"), Chat(f"FIX\n1. drop {KEY}", f"FIX\n1. still {HOOK_KEY}")
    run("route", "write a poem")
    world.worker, world.chatgpt = Scripted(f"FIX\n1. now {URL}", "PASS"), Chat(f"a redo with {KEY}", "the fixed redo")
    run("fallback", "2")
    # versus, and the owner's pick
    world.worker, world.chatgpt = Scripted(f"A with {KEY}", REVIEW), Chat(f"B with {HOOK_KEY}", REVIEW)
    run("relay", "versus", f"a blurb about {URL}")
    run("pick", "3", "b")
    # a Grok task left open, checked, then cancelled
    world.label = fake_label(jev("x_social_pulse"))
    run("route", f"what are gardeners saying about {HOOK_KEY}")
    run("check")
    run("cancel", "4")
    # a split stopped at its plan, and the refusals and errors
    world.worker = Scripted("## Pieces\n1. one\n2. two")
    run("split", f"split this {KEY} task")
    run("resume", "1")
    run("show", "999")
    run("route")
    # planted straight into the log where the JSON reads: a check note, call text, a file name
    conn = log.init_db(cli.DB_PATH)
    conn.execute("UPDATE tasks SET check_note = ? WHERE rowid = 1", (f"a note with {KEY}",))
    conn.execute("UPDATE calls SET text = ? WHERE rowid = (SELECT max(rowid) FROM calls)", (f"call text with {URL}",))
    log.add_task(conn, "sr-files", "a task with a file", "cli", jev("read_media"),
                 files=[{"name": f"photo-{HOOK_KEY}.png", "type": "png", "size": 1}])
    conn.commit()
    conn.close()
    # a project whose folder name carries a value
    folder = tmp_path / f"project-{KEY}"
    folder.mkdir()
    (folder / "HANDOFF.md").write_text(f"# Handoff\nthe path holds {KEY}\n")
    run("project", "add", "demo", str(folder))
    # every read
    run("status")
    run("log")
    run("project", "list")
    run("chat", "list")
    conn = log.init_db(cli.DB_PATH)
    numbers = [row["n"] for row in log.recent_tasks(conn, 50)]
    conn.close()
    for n in numbers:
        run("show", str(n))

    assert len(seen) >= 20 and all(text.strip() for _, text in seen)
    for argv, text in seen:
        assert not _found(text), (argv, _found(text))
    files = list((cli.DB_PATH.parent / "tasks").rglob("*.md"))
    assert len(files) >= 8
    for path in files:
        assert not _found(path.read_text()), (path.name, _found(path.read_text()))
    shown = json.loads(next(text for argv, text in seen if argv == ("show", "1")))
    assert "[REDACTED]" in shown["text"] and "[REDACTED]" in shown["check_note"]
    conn = log.init_db(cli.DB_PATH)
    first = log.calls_for(conn, log.task_by_number(conn, 1)["task_id"])[0]
    conn.close()
    # brief 22 (decision 10): the log redacts every .env value too, so the row no longer keeps the fourth one
    assert OTHER not in first["text"] and "[REDACTED]" in first["text"]
    assert OTHER not in (cli.DB_PATH.parent / first["round_file"]).read_text()
