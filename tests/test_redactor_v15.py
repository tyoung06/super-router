"""Build brief 22, A3 (rules v2.31, Secrets; decision 10 with the owner's amendment of 20 Oct): the log and the prose redact
every `.env` value, the same set the JSON and the round files use. A value of 8 characters or more is a secret and is
masked wherever text is stored or shown; a shorter value is not treated as a secret and is never masked. The task text
is redacted at intake, before Jev and before its row. The sweep plants a fourth fake key of normal length in a task's
text, a result, a fix list, an error, a file name, a handoff and a piece's edited text, then searches every column of
every log row, every prose line, every JSON output and every round file for it, raw and JSON-escaped; and proves a
short value typed in a task is left as it was. Fakes only; every value here is fake."""
import json
import sqlite3

import pytest

from router import __main__ as cli
from router import log, safety
from tests.helpers import fake_label
from tests.test_json_actions import FAKE_ENV, World, jev
from tests.test_loop import Scripted
from tests.test_relay import Chat

FOURTH = "FAKE-FOURTH-TOKEN-4242"          # a fourth key, normal length
SHORT = "west"                              # a short value: never a secret, never masked
ENV = dict(FAKE_ENV, FOURTH_TOKEN=FOURTH, REGION=SHORT)


# ---------- the set ----------

def test_a_secret_is_every_env_value_of_8_characters_or_more():
    assert safety.SECRET_MIN_LENGTH == 8
    found = safety.env_secrets({"A": "12345678", "B": "1234567", "C": "", "D": None, "E": "12345678", "F": "x" * 40})
    assert found == ["12345678", "x" * 40]  # in order, once each; 7 characters, empty and missing are not secrets


def test_the_log_and_prose_set_is_every_long_env_value_not_only_the_three_named():
    assert cli._secrets(ENV) == safety.env_secrets(ENV)
    assert FOURTH in cli._secrets(ENV) and SHORT not in cli._secrets(ENV)
    assert all(value in cli._secrets(ENV) for value in FAKE_ENV.values())


def test_redact_never_masks_a_short_value_given_to_it_through_the_set():
    text = f"the {SHORT} coast holds {FOURTH}"
    assert safety.redact(text, safety.env_secrets(ENV)) == f"the {SHORT} coast holds [REDACTED]"


# ---------- the sweep ----------

def _found(text):
    return [name for name, value in (("FOURTH_TOKEN", FOURTH),) if value in text or json.dumps(value)[1:-1] in text]


def _rows(db):
    """Every column of every row of both tables, as one text per row."""
    c = sqlite3.connect(db)
    try:
        found = []
        for table in ("tasks", "calls"):
            for row in c.execute(f"SELECT * FROM {table}"):
                found.append((table, " | ".join("" if v is None else str(v) for v in row)))
        return found
    finally:
        c.close()


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    w = World(monkeypatch, tmp_path, capsys)
    monkeypatch.setattr(cli, "dotenv_values", lambda path: dict(ENV))
    monkeypatch.setattr(cli.memory, "client", lambda request, **kw: None)  # no store: a tagged task runs without its block
    return w


def test_a_fourth_key_is_nowhere_in_the_log_the_prose_the_json_or_the_round_files(world, tmp_path):
    seen = []

    def run(*argv):
        code, out, err = world.run(*argv)
        seen.append((argv, out + err))
        return code

    # a routed task: the key in its text; the doer's result and the checker's fix list carry it too
    world.label = fake_label(jev("writing"))
    world.worker = Scripted(f"draft holding {FOURTH}", f"fixed draft with {FOURTH} again")
    world.chatgpt = Chat(f"FIX\n1. drop {FOURTH}", "PASS")
    run("route", f"write about the {SHORT} coast and {FOURTH}")
    # an agent error that quotes it: the first call fails, the reason is stored
    world.label = fake_label(jev("writing"))
    world.worker = Scripted(safety.SafeError(f"claude said {FOURTH}"))
    run("route", "a task whose agent errors")
    # a quick answer, prose and JSON
    world.label, world.worker = fake_label(jev("quick_answer", 0.99)), Scripted(f"answer {FOURTH}")
    run("route", "what is the key", "--json")
    # a project whose handoff holds it
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "HANDOFF.md").write_text(f"# Handoff\nthe old key was {FOURTH}\n")
    run("project", "add", "demo", str(folder))
    world.label = fake_label(jev("writing"))
    world.worker = Scripted(f"result {FOURTH}\n\n## Handoff\n### Produced\nnothing written: result {FOURTH} — one line\n"
                            "### Status\nok\n### Next\n- more")
    world.chatgpt = Chat("PASS")
    run("route", "write for the project", "--project", "demo")
    # a file whose name carries it, planted straight into the log as intake would (its copy is not needed here)
    conn = log.init_db(cli.DB_PATH)
    conn.close()
    # every read, prose and JSON
    for argv in (("log",), ("log", "--json"), ("status",), ("status", "--json")):
        run(*argv)
    conn = log.init_db(cli.DB_PATH)
    numbers = [row["n"] for row in log.recent_tasks(conn, 50)]
    conn.close()
    for n in numbers:
        run("show", str(n))
        run("show", str(n), "--history")
        run("show", str(n), "--json")

    assert len(seen) >= 15
    for argv, text in seen:
        assert not _found(text), (argv, _found(text))
    for table, text in _rows(cli.DB_PATH):
        assert not _found(text), (table, text[:200])
    files = list((cli.DB_PATH.parent / "tasks").rglob("*.md"))
    assert files
    for path in files:
        assert not _found(path.read_text()), path.name
    # the short value is not a secret: the task text keeps it in the log and on screen
    conn = log.init_db(cli.DB_PATH)
    first = log.task_by_number(conn, 1)
    conn.close()
    assert first["task"] == f"write about the {SHORT} coast and [REDACTED]"
    assert any(f"the {SHORT} coast" in text for argv, text in seen if argv[:1] == ("show",))


def test_the_task_text_reaches_jev_already_redacted(world):
    asked = []

    def label(text, *, task_id, tokens_this_month):
        asked.append(text)
        return jev("quick_answer", 0.99)

    world.label, world.worker = label, Scripted("ok")
    world.run("route", f"what about {FOURTH} on the {SHORT} side")
    assert asked == [f"what about [REDACTED] on the {SHORT} side"]


def test_a_relay_and_a_split_task_text_is_redacted_before_its_row(world):
    world.worker, world.chatgpt = Scripted("## Plan\n1. a\n2. b"), Chat("## Amended plan\n1. a")
    world.run("relay", "collab", f"plan around {FOURTH}", "--json")
    world.worker = Scripted("## Pieces\n1. one\n2. two\n\n## Join\nput them together")
    world.run("split", f"split around {FOURTH}", "--json")
    for table, text in _rows(cli.DB_PATH):
        assert not _found(text), (table, text[:200])


def test_a_file_whose_name_holds_a_value_is_refused_at_intake(world, tmp_path):
    """A copy is named from its file, so a name holding a `.env` value can't be fixed in the log alone: it is refused
    before Jev and before any row (bad_file), and the refusal never prints the name."""
    path = tmp_path / f"photo-{FOURTH}.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    code, out, err = world.run("route", "describe this photo", "--file", str(path))
    assert code == 2 and "Refused: a file name holds a value from .env; rename the file. Nothing was logged or sent." in out
    assert FOURTH not in out + err
    conn = log.init_db(cli.DB_PATH)
    assert log.recent_tasks(conn) == []
    conn.close()
    found = world.json("route", "describe this photo", "--file", str(path))
    assert (found["exit"], found["reason_code"], found["task_id"]) == (2, "bad_file", None)


def test_every_prose_line_main_prints_goes_through_the_redactor(monkeypatch, capsys):
    monkeypatch.setattr(cli, "dotenv_values", lambda path: dict(ENV))

    def fake_main(argv, platform, out):
        out(f"a line with {FOURTH} and the {SHORT} side")
        out()
        return 0

    monkeypatch.setattr(cli, "_main", fake_main)
    assert cli.main(["log"]) == 0
    assert capsys.readouterr().out == f"a line with [REDACTED] and the {SHORT} side\n\n"
