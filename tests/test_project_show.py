"""Build brief 18, phase E (rules v2.25, Project context; decision 14): what the owner sees. `sr show <n>` on a project
task prints the project name on its first line, the entry the router wrote (or `no entry: <status>`), and with
`--handoff` the handoff as it was sent to the build call; `sr log` prints the project name beside the task, as the
preset is shown; `sr show --history` labels the doer's re-ask. Fake agents only; every secret here is fake."""
import pytest

from router import __main__ as cli
from router import log, projects

from tests.helpers import set_local
from tests.test_context import HANDOFF_TEXT, SECTION, TASK, _relay, _route
from tests.test_handoff_contract import GOOD
from tests.test_loop import Scripted, Webhook
from tests.test_relay import GOOD_NOTE, Chat
from tests.test_resume_run import WRITING

GROK_SKILL = {**WRITING, "label": "x_social_pulse"}


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "config" / "projects.json")
    set_local(never_register=[str(tmp_path / "home" / "Projects" / "off-limits")])  # brief 25: a fake never_register folder
    folder = tmp_path / "demo"
    folder.mkdir()
    (folder / "HANDOFF.md").write_text(HANDOFF_TEXT)
    projects.add("demo", str(folder))
    return folder


def _show(conn, *words, handoff=False, history=False):
    lines = []
    code = cli.cmd_show(conn=conn, words=list(words), handoff=handoff, history=history, out=lines.append)
    return code, "\n".join(lines)


def _log(conn):
    lines = []
    cli.cmd_log(conn=conn, out=lines.append)
    return "\n".join(lines)


def test_show_prints_the_project_on_the_first_line_and_the_entry_it_wrote(project, conn):
    code, out, row, _ = _route(conn, project="demo", worker=Scripted(GOOD), chatgpt=Chat("PASS"))
    code, shown = _show(conn, str(row["n"]))
    assert code == 0
    first = shown.splitlines()[0]
    assert first.startswith(f"#{row['n']}  {row['task_id']}  done  created ") and first.endswith("  project: demo")
    entry = log.handoff_of(log.get_task(conn, row["task_id"]))[0]["text"]
    assert f"Handoff entry (HANDOFF.md in {project.resolve()}, 24 lines after the write):\n{entry}" in shown
    assert "## Handoff" not in shown.split("Result:")[1].split("CHECKED")[0]


def test_show_says_no_entry_on_an_open_project_task(project, conn):
    code, out, row, _ = _route(conn, project="demo", jev=GROK_SKILL, hook=Webhook(), wait=False)
    code, shown = _show(conn, str(row["n"]))
    assert "  project: demo" in shown.splitlines()[0] and "Handoff entry: none (sent)" in shown


def test_show_on_a_relay_project_task(project, conn):
    code, out, row, hook = _relay(conn, "research-build", project="demo", worker=Scripted("built" + SECTION))
    code, shown = _show(conn, str(row["n"]))
    assert shown.splitlines()[0].endswith("  project: demo") and "Relay: research-build" in shown
    assert " · research-build · claude\nProduced:" in shown


def test_show_handoff_prints_the_handoff_as_sent_to_the_build_call(project, conn):
    code, out, row, _ = _route(conn, project="demo", worker=Scripted(GOOD), chatgpt=Chat("PASS"))
    code, shown = _show(conn, str(row["n"]), handoff=True)
    assert code == 0
    assert f"Handoff as sent to {row['task_id']} (16 of 16 lines):\n{HANDOFF_TEXT.rstrip()}" in shown


def test_show_handoff_on_a_relay_task_names_the_build_stage_and_a_left_out_handoff_says_so(project, conn, monkeypatch, tmp_path):
    import json
    from router import settings
    code, out, row, hook = _relay(conn, "research-build", project="demo", worker=Scripted("built" + SECTION))
    code, shown = _show(conn, str(row["n"]), handoff=True)
    assert f"Handoff as sent to {row['task_id']}-s2 (16 of 16 lines):" in shown
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"grok_prompt_limit": 10}))
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    code, out, row, hook = _relay(conn, "research-build", project="demo", worker=Scripted("built" + SECTION))
    code, shown = _show(conn, str(row["n"]), handoff=True)
    assert f"Handoff as sent to {row['task_id']}-s2 (" in shown  # stage 2 is claude: never trimmed
    assert log.context_of(log.get_call(conn, f"{row['task_id']}-s1"))["left_out"] is True  # stage 1 is grok: left out
    code, shown = _show(conn, str(row["n"]), history=True)
    assert "1. stage 1 research by grok: done" in shown


def test_show_handoff_on_a_task_without_a_project(conn):
    code, out, row, _ = _route(conn, worker=Scripted("x"), chatgpt=Chat("PASS"))
    code, shown = _show(conn, str(row["n"]), handoff=True)
    assert code == 0 and "project:" not in shown.splitlines()[0]
    assert "This is not a project task, so no handoff was sent." in shown and "Handoff entry" not in shown


def test_log_prints_the_project_beside_the_task_as_the_preset_is(project, conn):
    _route(conn, project="demo", worker=Scripted(GOOD), chatgpt=Chat("PASS"))
    _relay(conn, "research-build", project="demo", worker=Scripted("built" + SECTION))
    _route(conn, worker=Scripted("x"), chatgpt=Chat("PASS"))
    lines = _log(conn).splitlines()[1:]  # newest first
    assert "project:" not in lines[0]
    assert "relay:research-build project:demo" in lines[1] and "writing project:demo" in lines[2]


def test_history_labels_the_doers_re_ask(project, conn):
    code, out, row, _ = _route(conn, project="demo", worker=Scripted("one", GOOD), chatgpt=Chat("PASS"))
    code, shown = _show(conn, str(row["n"]), history=True)
    assert "2. do re-ask by claude: done" in shown and "1. do by claude: done" in shown


def test_main_takes_show_handoff(project, conn, capsys):
    assert cli.main(["show", "--handoff"], platform="darwin") in (0, 1)
