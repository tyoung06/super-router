"""Build brief 31 (decisions 3 to 7 and 10): the run command (`sr project run-command`, kept in the router's own gitignored
`config/project_runs.json`), Run (`sr project run`: an argument list in the project's real folder, never a shell, with
the router's environment less its `.env` names and the billing switches and the project's `.env` on top, under a
supervisor in its own session that redacts every line before writing it), Stop (the group, SIGTERM then SIGKILL, only
when the pid's start time matches) and `--status`. Real runs here start this Python only, on programs the tests write;
every value is fake, built at run time."""
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from router import __main__ as cli
from router import projects, projrun, runs, safety

FAKE = "carrot-" + "seed-" + "0123456789"  # a fake key, built from pieces


@pytest.fixture
def real_procs(real_git, monkeypatch):
    """git, ps and this Python run for real (the supervisor and the programs the tests write); the process table is
    read for real, so a start time is a real one."""
    real_git.update({os.path.basename(sys.executable), "python3", "ps"})
    monkeypatch.setattr(runs, "READ", runs.start_time)
    return real_git


@pytest.fixture
def garden(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "projects.json")
    monkeypatch.setattr(projects, "TESTS_PATH", tmp_path / "project_tests.json")
    monkeypatch.setattr(projrun, "RUNS_PATH", tmp_path / "project_runs.json")
    folder = tmp_path / "garden"
    folder.mkdir()
    projects.add("garden", folder)
    return folder


def git(folder, *args):
    subprocess.run(["git", "-C", str(folder), *args], check=True, capture_output=True)


def program(folder, body, name="app.py"):
    (folder / name).write_text(textwrap.dedent(body).lstrip())


def wait_for(check, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        found = check()
        if found:
            return found
        time.sleep(0.05)
    raise AssertionError("waited too long")


def start(name="garden", tmp_path=None, **kw):
    kw.setdefault("router_env", tmp_path / "router.env")
    if not Path(kw["router_env"]).exists():
        Path(kw["router_env"]).write_text("")
    return projrun.start(name, run_folder=tmp_path / "run", **kw)


def ended(name, tmp_path):
    found = projrun.status(name, run_folder=tmp_path / "run")
    return found if not found["running"] and found["state"] in ("exited", "stopped") else None


# ---------- the run command (decision 3) ----------

def test_set_show_and_clear_the_run_command(garden, tmp_path):
    projrun.set_run_command("garden", projrun.split_words("python3 app.py --port 8000"))
    assert json.loads((tmp_path / "project_runs.json").read_text()) == {"garden": ["python3", "app.py", "--port", "8000"]}
    assert projrun.run_command_of("garden") == ["python3", "app.py", "--port", "8000"]
    assert projrun.clear_run_command("garden") and projrun.run_command_of("garden") is None


@pytest.mark.parametrize("text, why", [
    ("", "type the run command"),
    ("x" * 301, "301 characters"),
    ("python3 app.py\x07", "control character"),
    ("python3 'app.py", "quote"),
])
def test_a_run_command_that_cant_be_kept_is_refused(text, why):
    with pytest.raises(projrun.Refused, match=why):
        projrun.split_words(text)


def test_sr_project_run_command_sets_shows_and_clears(garden, capsys, tmp_path):
    assert cli.main(["project", "run-command", "garden", "--", "python3 app.py"], platform="darwin") == 0
    assert "Run command for garden: python3 app.py" in capsys.readouterr().out
    assert cli.main(["project", "run-command", "garden", "--json"], platform="darwin") == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["project"]["run_command"] == ["python3", "app.py"]
    assert cli.main(["project", "run-command", "garden", "--clear"], platform="darwin") == 0
    assert projrun.run_command_of("garden") is None


# ---------- the environment (decision 4) ----------

def test_the_environment_drops_the_routers_names_and_the_billing_switches_and_lays_the_projects_on_top():
    base = {"PATH": "/usr/bin", "HOME": "/home/x", "JEV_API_KEY": "router-" + "secret", "OPENAI_API_KEY": "billed",
            "LANG": "en_US.UTF-8", "SHARED": "router's"}
    env = projrun.environment(base, router_names={"JEV_API_KEY", "SHARED"}, project={"DEMO_KEY": FAKE, "SHARED": "mine"})
    assert env["PATH"] == "/usr/bin" and env["HOME"] == "/home/x" and env["LANG"] == "en_US.UTF-8"
    assert "JEV_API_KEY" not in env and "OPENAI_API_KEY" not in env
    assert env["DEMO_KEY"] == FAKE and env["SHARED"] == "mine"  # a router name the project also sets: the project's value
    assert all(name not in env for name in safety.BILLING_SWITCHES if name not in ("OPENAI_API_KEY",))


# ---------- the redaction before writing, and the 5 MB tail (decision 4) ----------

def test_a_value_printed_whole_mid_line_twice_and_split_across_reads_is_masked_before_it_is_written(tmp_path):
    log = tmp_path / "run.log"
    writer = projrun.Redacted(log, [FAKE])
    writer.add(f"{FAKE}\nkey in the middle: {FAKE}!\ntwice {FAKE} {FAKE}\nsplit {FAKE[:6]}".encode())
    writer.add(f"{FAKE[6:]} done\n".encode())
    writer.close()
    text = log.read_text()
    assert FAKE not in text and FAKE[:9] not in text
    assert text == ("[REDACTED]\nkey in the middle: [REDACTED]!\ntwice [REDACTED] [REDACTED]\nsplit [REDACTED] done\n")
    assert oct(log.stat().st_mode & 0o777) == "0o600"


def test_the_log_keeps_its_newest_five_megabytes_from_a_line_start(tmp_path, monkeypatch):
    monkeypatch.setattr(projrun, "LOG_KEEP", 1000)
    monkeypatch.setattr(projrun, "LOG_CUT", 1500)
    log = tmp_path / "run.log"
    writer = projrun.Redacted(log, [])
    for k in range(400):
        writer.add(f"tick {k}\n".encode())
    writer.close()
    text = log.read_text()
    assert len(text.encode()) <= 1500 and text.startswith("tick ") and text.endswith("tick 399\n")
    assert "tick 0\n" not in text


# ---------- real runs (decisions 4 to 7) ----------

def test_a_run_records_its_exit_its_redacted_output_and_its_arguments_as_text(real_procs, garden, tmp_path):
    (garden / ".env").write_text(f"DEMO_KEY={FAKE}\n")
    program(garden, """
        import os, sys
        print("key length:", len(os.environ["DEMO_KEY"]), flush=True)
        print(os.environ["DEMO_KEY"], flush=True)
        print("args:", sys.argv[1:], flush=True)
        print("jev:", os.environ.get("JEV_API_KEY"), flush=True)
        """)
    (tmp_path / "router.env").write_text("JEV_API_KEY=router-" + "secret-0123456789\n")
    projrun.set_run_command("garden", ["python3", "app.py", "a;b", "$(echo hi)", "&&", "rm"])
    record = start(tmp_path=tmp_path, base={"PATH": os.environ["PATH"], "JEV_API_KEY": "router-" + "secret-0123456789"})
    assert record["state"] in ("running", "exited") and record["command"][0] == "python3"
    done = wait_for(lambda: ended("garden", tmp_path))
    assert done["state"] == "exited" and done["exit"] == 0 and done["ended"]
    log_text = Path(done["log"]).read_text()
    assert f"key length: {len(FAKE)}" in log_text and "[REDACTED]" in log_text and FAKE not in log_text
    assert "args: ['a;b', '$(echo hi)', '&&', 'rm']" in log_text  # passed as text: no shell ran
    assert "jev: None" in log_text  # the router's own key never reaches the program
    assert FAKE not in json.dumps(done) and FAKE not in (tmp_path / "run" / "projects" / "garden" / "run.json").read_text()


def test_the_run_goes_on_after_the_starter_returns_and_stop_ends_its_group(real_procs, garden, tmp_path):
    program(garden, """
        import time
        k = 0
        while True:
            print("tick", k, flush=True)
            k += 1
            time.sleep(0.2)
        """)
    projrun.set_run_command("garden", ["python3", "app.py"])
    record = start(tmp_path=tmp_path)
    assert record["state"] == "running"
    status = projrun.status("garden", run_folder=tmp_path / "run")
    assert status["running"] and status["started"] and status["command"] == ["python3", "app.py"]
    wait_for(lambda: "tick 3" in projrun.status("garden", run_folder=tmp_path / "run")["output"])
    with pytest.raises(projrun.Refused, match="already going on garden"):
        start(tmp_path=tmp_path)
    pid = record["pid"]
    stopped = projrun.stop("garden", run_folder=tmp_path / "run")
    assert stopped["state"] == "stopped" and stopped["ended"]
    with pytest.raises(ProcessLookupError):
        os.killpg(pid, 0)  # the group is gone
    final = wait_for(lambda: ended("garden", tmp_path))
    assert final["state"] == "stopped" and not final["running"]


def test_stop_sends_sigkill_after_the_wait_when_sigterm_is_ignored(real_procs, garden, tmp_path, monkeypatch):
    monkeypatch.setattr(projrun, "STOP_WAIT", 1.0)
    program(garden, """
        import signal, time
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        print("ignoring SIGTERM", flush=True)
        time.sleep(60)
        """)
    projrun.set_run_command("garden", ["python3", "app.py"])
    record = start(tmp_path=tmp_path)
    wait_for(lambda: "ignoring" in projrun.status("garden", run_folder=tmp_path / "run")["output"])
    began = time.monotonic()
    stopped = projrun.stop("garden", run_folder=tmp_path / "run")
    assert stopped["state"] == "stopped" and time.monotonic() - began >= 1.0
    with pytest.raises(ProcessLookupError):
        os.killpg(record["pid"], 0)


def test_a_reused_pid_is_never_signalled(garden, tmp_path, monkeypatch):
    where = tmp_path / "run" / "projects" / "garden"
    where.mkdir(parents=True)
    (where / "run.json").write_text(json.dumps({"state": "running", "pid": 424242, "pid_started": "2026-10-28T10:00:00+00:00",
                                                "command": ["python3", "app.py"], "started": "2026-10-28T10:00:00+00:00"}))
    monkeypatch.setattr(runs, "READ", lambda pid: "2026-10-28T11:11:11+00:00")  # another process holds the pid now
    sent = []
    monkeypatch.setattr(projrun, "KILL", lambda pid, sig: sent.append((pid, sig)))
    with pytest.raises(projrun.Refused, match="no run is going on garden"):
        projrun.stop("garden", run_folder=tmp_path / "run")
    monkeypatch.setattr(runs, "READ", lambda pid: runs.UNKNOWN)  # ps can't say: never signalled either
    with pytest.raises(projrun.Refused, match="couldn't tell"):
        projrun.stop("garden", run_folder=tmp_path / "run")
    assert sent == []


# ---------- refusals, nothing started (decisions 4 and 10) ----------

def test_no_run_command_is_refused(garden, tmp_path):
    with pytest.raises(projrun.Refused, match="garden has no run command"):
        start(tmp_path=tmp_path)


def test_the_routers_own_folder_is_refused(garden, tmp_path, monkeypatch):
    projrun.set_run_command("garden", ["python3", "app.py"])
    monkeypatch.setattr(projects, "folder_of", lambda name: Path(cli.__file__).resolve().parent.parent)
    with pytest.raises(projrun.Refused, match="never runs itself"):
        start(tmp_path=tmp_path)


def test_an_env_git_tracks_or_doesnt_ignore_is_refused_and_a_link_too(real_git, garden, tmp_path):
    projrun.set_run_command("garden", ["python3", "app.py"])
    (garden / ".env").write_text("DEMO_KEY=x\n")
    git(garden, "init", "-q")
    with pytest.raises(projrun.Refused, match="doesn't ignore its .env"):
        start(tmp_path=tmp_path)
    git(garden, "add", ".env")
    git(garden, "commit", "-q", "-m", "oops")
    with pytest.raises(projrun.Refused, match="git tracks its .env"):
        start(tmp_path=tmp_path)
    linked = tmp_path / "elsewhere.env"
    linked.write_text("X=1\n")
    git(garden, "rm", "-q", "--cached", ".env")
    (garden / ".env").unlink()
    (garden / ".env").symlink_to(linked)
    with pytest.raises(projrun.Refused, match="a link"):
        start(tmp_path=tmp_path)


def test_never_run_env_refuses_naming_the_part_and_a_bad_setting_refuses_every_run(garden, tmp_path):
    projrun.set_run_command("garden", ["python3", "app.py"])
    (garden / ".env").write_text("FAKEBROKER_KEY=x\nOTHER=y\n")
    (tmp_path / "settings.local.json").write_text(json.dumps({"never_run_env": ["fakebroker"]}))
    with pytest.raises(projrun.Refused, match='a name containing "fakebroker"'):
        start(tmp_path=tmp_path)
    (tmp_path / "settings.local.json").write_text(json.dumps({"never_run_env": "FAKEBROKER"}))
    with pytest.raises(projrun.Refused, match="never_run_env"):
        start(tmp_path=tmp_path)
    assert not (tmp_path / "run" / "projects" / "garden" / "run.json").exists()


def test_sr_project_run_refusals_exit_2_with_nothing_started(garden, capsys):
    code = cli.main(["project", "run", "garden", "--json"], platform="darwin")
    doc = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert code == 2 and doc["reason_code"] == "project_refused" and "no run command" in doc["message"]
    code = cli.main(["project", "stop", "garden", "--json"], platform="darwin")
    doc = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert code == 2 and "no run is going on garden" in doc["message"]


def test_status_gives_the_tail_at_most_2000_lines(garden, tmp_path):
    where = tmp_path / "run" / "projects" / "garden"
    where.mkdir(parents=True)
    log = where / "run-20261028T100000.log"
    log.write_text("".join(f"line {k}\n" for k in range(3000)))
    (where / "run.json").write_text(json.dumps({"state": "exited", "exit": 0, "pid": 1, "pid_started": None,
                                                "command": ["python3", "app.py"], "log": str(log),
                                                "started": "2026-10-28T10:00:00+00:00", "ended": "2026-10-28T10:01:00+00:00"}))
    found = projrun.status("garden", run_folder=tmp_path / "run")
    lines = found["output"].splitlines()
    assert len(lines) == 2000 and lines[-1] == "line 2999" and found["state"] == "exited" and found["exit"] == 0
