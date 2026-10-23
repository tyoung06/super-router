"""Build brief 27 (rules 2.38, Memory, The switch): `settings.set_memory`, the one write `sr memory on|off` makes. One key,
`memory`, in this Mac's `config/settings.local.json` (conftest points `settings.LOCAL_PATH` at a temp file); the tracked
file is never written. Every value here is fake."""
import json
import os
import stat

import pytest

from router import settings


@pytest.fixture
def files(tmp_path, monkeypatch):
    folder = tmp_path / "cfg"  # its own folder: conftest's local file (the fake inbox setting) sits in tmp_path
    folder.mkdir()
    tracked, local = folder / "settings.json", folder / "settings.local.json"
    tracked.write_text(json.dumps({"memory": "auto", "serve_port": 8765}) + "\n")
    monkeypatch.setattr(settings, "SETTINGS_PATH", tracked)
    monkeypatch.setattr(settings, "LOCAL_PATH", local)
    return tracked, local


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def test_a_missing_local_file_is_made_holding_memory_alone_mode_0600(files):
    tracked, local = files
    before = tracked.read_bytes()
    assert settings.set_memory("off") == ("auto", True)
    assert json.loads(local.read_text()) == {"memory": "off"} and _mode(local) == 0o600
    assert settings.memory_mode() == "off" and tracked.read_bytes() == before


def test_an_existing_file_keeps_every_other_key_and_its_mode(files):
    tracked, local = files
    doc = {"report_path": "~/Downloads/report.md", "never_register": ["~/Projects/example"], "serve_port": 8800,
           "nested": {"a": [1, 2, {"b": None}]}}
    local.write_text(json.dumps(doc))
    os.chmod(local, 0o640)
    before = tracked.read_bytes()
    assert settings.set_memory("off") == ("auto", True)
    assert json.loads(local.read_text()) == {**doc, "memory": "off"} and _mode(local) == 0o640
    assert list(json.loads(local.read_text())) == list(doc) + ["memory"]  # the keys keep their order
    assert settings.set_memory("auto") == ("off", True)
    assert json.loads(local.read_text()) == {**doc, "memory": "auto"} and tracked.read_bytes() == before


def test_already_as_asked_writes_nothing(files):
    tracked, local = files
    local.write_text('{"memory": "off",   "x": 1}')
    stamp, data = os.stat(local).st_mtime_ns, local.read_bytes()
    assert settings.set_memory("off") == ("off", False)
    assert (os.stat(local).st_mtime_ns, local.read_bytes()) == (stamp, data)
    local.unlink()
    assert settings.set_memory("auto") == ("auto", False) and not local.exists()  # the tracked file says auto already


@pytest.mark.parametrize("text", ["not json", "[1, 2]", '"off"', "", "{\"memory\": "])
def test_a_local_file_that_is_not_a_json_object_is_refused_unchanged(files, text):
    tracked, local = files
    local.write_text(text)
    before, tracked_before = local.read_bytes(), tracked.read_bytes()
    with pytest.raises(settings.SettingsError, match="config/settings.local.json"):
        settings.set_memory("off")
    assert local.read_bytes() == before and tracked.read_bytes() == tracked_before


def test_only_auto_and_off_are_written(files):
    with pytest.raises(ValueError):
        settings.set_memory("sometimes")


def test_no_temporary_file_is_left_beside_it(files):
    _, local = files
    local.write_text('{"x": 1}')
    settings.set_memory("off")
    assert sorted(p.name for p in local.parent.iterdir()) == ["settings.json", "settings.local.json"]


# ---------- sr memory on | off (decisions 1, 3, 4, 5, 8; choices 1, 3, 4, 10) ----------

import signal  # noqa: E402

from router import __main__ as cli  # noqa: E402
from router import log, memory_server  # noqa: E402
from tests.fake_hindsight import FakeHindsight, Ticker  # noqa: E402
from tests.test_json_actions import KEYS  # noqa: E402
from tests.test_memory_server import SHELL, FakePopen  # noqa: E402


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    binary = memory_server.paths(h)["binary"]
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    return h


def _run(words, fake, home, tmp_path, **over):
    out, ticker = [], Ticker()
    kwargs = dict(request=fake.request, environ=SHELL, home=home, popen=FakePopen(), sleep=ticker.sleep, clock=ticker.now,
                  kill=lambda *a: pytest.fail("killed something"), db_path=tmp_path / "router.db", out=out.append)
    kwargs.update(over)
    return cli.cmd_memory(words, **kwargs), out, kwargs


def _local():
    return json.loads(settings.LOCAL_PATH.read_text())


def test_on_writes_auto_then_starts_and_backfills_under_the_lock(files, home, tmp_path):
    files[1].write_text(json.dumps({"memory": "off", "serve_port": 8800}))
    db = tmp_path / "router.db"
    conn = log.init_db(db)
    conn.close()
    fake = FakeHindsight(online_after=1)
    popen = FakePopen()
    code, out, _ = _run(["on"], fake, home, tmp_path, popen=popen)
    assert code == 0 and _local() == {"memory": "auto", "serve_port": 8800}
    assert out[0] == "memory: on (it was off)" and len(popen.calls) == 1
    assert "memory: backfill: stored 0, skipped 0" in out


def test_on_when_already_online_starts_nothing_and_still_backfills(files, home, tmp_path):
    files[1].write_text(json.dumps({"memory": "off"}))
    fake, popen = FakeHindsight(), FakePopen()
    code, out, _ = _run(["on"], fake, home, tmp_path, popen=popen)
    assert code == 0 and popen.calls == [] and any(line.startswith("memory: already online") for line in out)


def test_on_without_the_install_writes_the_setting_and_names_the_setup_sheet(files, tmp_path):
    files[1].write_text(json.dumps({"memory": "off"}))
    popen = FakePopen()
    code, out, _ = _run(["on"], FakeHindsight(online=False), tmp_path / "bare-home", tmp_path, popen=popen)
    assert code == 0 and _local() == {"memory": "auto"} and popen.calls == []
    assert any("not installed" in line and "Setup sheet" in line for line in out)


def test_on_whose_start_never_answers_still_exits_0_with_its_words(files, home, tmp_path):
    files[1].write_text(json.dumps({"memory": "off"}))
    code, out, _ = _run(["on"], FakeHindsight(online=False), home, tmp_path)
    assert code == 0 and _local() == {"memory": "auto"} and any("has not answered after 180 s" in line for line in out)


def test_off_writes_off_then_stops_the_store_the_pid_file_names(files, home, tmp_path):
    fake = FakeHindsight()
    memory_server.paths(home)["pid"].write_text("4242\n")
    kills = []

    def kill(pid, sig):
        kills.append((pid, sig))
        fake.online = False
    code, out, _ = _run(["off"], fake, home, tmp_path, kill=kill)
    assert code == 0 and _local() == {"memory": "off"} and kills == [(4242, signal.SIGTERM)]
    assert out[0] == "memory: off (it was on)" and "memory: stopped (pid 4242)" in out


def test_off_leaves_a_store_it_did_not_start_running_and_says_so(files, home, tmp_path):
    code, out, _ = _run(["off"], FakeHindsight(), home, tmp_path)
    assert code == 0 and _local() == {"memory": "off"}
    assert any("not started by sr memory start" in line and "not used while memory is off" in line for line in out)


def test_already_as_asked_writes_nothing_but_still_starts_or_stops(files, home, tmp_path):
    local = files[1]
    assert not local.exists()
    fake, popen = FakeHindsight(online_after=1), FakePopen()
    code, out, _ = _run(["on"], fake, home, tmp_path, popen=popen)
    assert code == 0 and not local.exists() and out[0] == "memory: on (it was already on)" and len(popen.calls) == 1


def test_a_local_file_that_is_not_an_object_is_refused_with_nothing_done(files, home, tmp_path):
    files[1].write_text("[1]")
    for verb in ("on", "off"):
        popen = FakePopen()
        code, out, _ = _run([verb], FakeHindsight(online=False), home, tmp_path, popen=popen)
        assert code == 2 and files[1].read_text() == "[1]" and popen.calls == []
        assert out == ["Refused: config/settings.local.json is not a JSON object. Nothing was changed."]


def test_start_and_rebuild_are_refused_while_off(files, home, tmp_path):
    files[1].write_text(json.dumps({"memory": "off"}))
    fake, popen = FakeHindsight(), FakePopen()
    for verb in ("start", "rebuild"):
        code, out, _ = _run([verb], fake, home, tmp_path, popen=popen, ask=lambda q: "y")
        assert code == 2 and out == [f"Refused: memory is off; sr memory on turns it on. Nothing was changed."]
    assert popen.calls == [] and fake.requests == []  # nothing started, nothing cleared


def test_status_while_off_says_so_first(files, home, tmp_path):
    files[1].write_text(json.dumps({"memory": "off"}))
    code, out, _ = _run(["status"], FakeHindsight(online=False), home, tmp_path)
    assert out[0] == "memory: off (sr memory on turns it on)"
    # brief 27 E (the owner): offline while off names no `sr memory start`, which is refused while off
    assert out[1] == "memory: offline (http://127.0.0.1:8888)"


def test_the_usage_names_all_six_verbs(files, home, tmp_path):
    code, out, _ = _run(["frob"], FakeHindsight(online=False), home, tmp_path)
    assert code == 2 and out == ["Refused: sr memory start|stop|status|rebuild|on|off. Nothing was changed."]
    text = cli._parser(None).format_help() + cli._parser(None)._subparsers._group_actions[0].choices["memory"].format_help()
    for verb in ("start", "stop", "status", "rebuild", "on", "off"):
        assert verb in text
    assert "never starts" not in text and "the router never does" not in text


# ---------- --json (decision 5; choice 1) ----------

def _main(monkeypatch, home, fake, capsys, *argv):
    monkeypatch.setattr(cli.requests, "request", fake.request)
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(cli.subprocess, "Popen", FakePopen())
    code = cli.main(list(argv), platform="darwin")
    out, err = capsys.readouterr()
    return code, out, err


def test_off_json_is_the_envelope_with_memory(files, home, monkeypatch, capsys):
    code, out, err = _main(monkeypatch, home, FakeHindsight(online=False), capsys, "memory", "off", "--json")
    found = json.loads(out)
    assert (code, err) == (0, "") and list(found) == KEYS + ["memory"]
    assert found["memory"] == {"setting": "off", "was": "auto", "online": False, "installed": True}
    assert (found["reason_code"], found["exit"]) == (None, 0) and found["message"].startswith("memory: off (it was on)")


def test_the_refusals_have_their_codes(files, home, monkeypatch, capsys):
    files[1].write_text(json.dumps({"memory": "off"}))
    code, out, err = _main(monkeypatch, home, FakeHindsight(), capsys, "memory", "start", "--json")
    assert (code, out, json.loads(err)["reason_code"]) == (2, "", "memory_off")
    files[1].write_text('"off"')
    code, out, err = _main(monkeypatch, home, FakeHindsight(), capsys, "memory", "on", "--json")
    assert (code, json.loads(err)["reason_code"]) == (2, "setup")
    code, out, err = _main(monkeypatch, home, FakeHindsight(), capsys, "memory", "frob", "--json")
    assert (code, json.loads(err)["reason_code"]) == (2, "usage")
