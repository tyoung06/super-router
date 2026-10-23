"""Build brief 19, phase A (rules v2.27, Memory): `sr memory start|stop|status` and the Hindsight client. The server
is never started here: the process start, the sleep, the clock and the request function are fakes. The router's
side holds no key and gives none. Every value here is fake."""
import json
import signal
import subprocess
from pathlib import Path

import pytest

from router import __main__ as cli
from router import memory, memory_server, settings
from tests.fake_hindsight import FakeHindsight, Reply, Ticker

URL = "http://127.0.0.1:8888"
SHELL = {"HOME": "/Users/t", "PATH": "/usr/bin", "USER": "t", "LANG": "C"}


class FakeProcess:
    def __init__(self, pid=4242, dies_after=None):
        self.pid, self.returncode, self.polls, self.dies_after = pid, None, 0, dies_after

    def poll(self):
        self.polls += 1
        if self.dies_after is not None and self.polls > self.dies_after:
            self.returncode = 1
        return self.returncode


class FakePopen:
    def __init__(self, process=None):
        self.calls, self.process = [], process or FakeProcess()

    def __call__(self, argv, **kwargs):
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv), "argv is a list of strings"
        self.calls.append((argv, kwargs))
        return self.process


@pytest.fixture
def home(tmp_path):
    """A home folder with Hindsight 'installed': the venv binary exists."""
    h = tmp_path / "home"
    binary = h / ".hindsight" / "venv" / "bin" / "hindsight-api"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    return h


def _client(fake, bank="super-router", url=URL):
    return memory.Client(url, bank, fake.request)


def _start(fake, home, *, popen=None, ticker=None, environ=None):
    out, popen, ticker = [], popen or FakePopen(), ticker or Ticker()
    code = memory_server.start(_client(fake), environ=environ or SHELL, home=home, popen=popen, sleep=ticker.sleep,
                               clock=ticker.now, out=out.append)
    return code, out, popen, ticker


# ---------- the command line and the environment (decisions 1 and 2; the amendments) ----------

def test_argv_runs_the_venv_binary_on_the_loopback_address_only(home):
    assert memory_server.argv(home, "127.0.0.1", 8888) == [
        str(home / ".hindsight" / "venv" / "bin" / "hindsight-api"), "--host", "127.0.0.1", "--port", "8888"]


def test_the_environment_is_built_from_scratch_and_holds_no_key():
    shell = {**SHELL, "SHELL": "/bin/zsh", "OPENAI_API_KEY": "FAKE", "ANTHROPIC_API_KEY": "FAKE", "JEV_API_KEY": "FAKE",
             "HINDSIGHT_API_LLM_API_KEY": "FAKE", "HINDSIGHT_API_LLM_PROVIDER": "openai", "GROK_WEBHOOK_KEY": "FAKE",
             "GROK_WEBHOOK_URL": "https://fake.invalid/hook"}
    env = memory_server.environment(shell, "127.0.0.1", 8888)
    assert env == {
        "HOME": "/Users/t", "PATH": "/usr/bin", "USER": "t", "LANG": "C",
        "HINDSIGHT_API_LLM_PROVIDER": "none",
        "HINDSIGHT_API_EMBEDDINGS_PROVIDER": "onnx",
        "HINDSIGHT_API_RERANKER_PROVIDER": "rrf",
        "HINDSIGHT_API_EMBEDDINGS_LOCAL_FORCE_CPU": "1",
        "HINDSIGHT_API_RERANKER_LOCAL_FORCE_CPU": "1",
        "HINDSIGHT_API_RETAIN_EXTRACTION_MODE": "chunks",
        "HINDSIGHT_API_HOST": "127.0.0.1",
        "HINDSIGHT_API_PORT": "8888",
    }
    assert not [k for k in env if k.endswith("_API_KEY")] and "GROK_WEBHOOK_URL" not in env


def test_host_and_port_come_from_the_url_and_must_be_loopback():
    assert memory_server.host_port("http://127.0.0.1:8888") == ("127.0.0.1", 8888)
    assert memory_server.host_port("http://localhost:9000/") == ("localhost", 9000)
    with pytest.raises(memory_server.ServerError, match="loopback"):
        memory_server.host_port("http://10.0.0.5:8888")


# ---------- start (decision 3) ----------

def test_start_detaches_the_server_writes_the_pid_and_waits_for_health(home):
    fake = FakeHindsight(online_after=3)
    code, out, popen, ticker = _start(fake, home)
    assert code == 0
    (argv, kwargs), = popen.calls
    assert argv == memory_server.argv(home, "127.0.0.1", 8888)
    assert kwargs["start_new_session"] is True
    assert kwargs["stdin"] == subprocess.DEVNULL and kwargs["stderr"] == subprocess.STDOUT
    assert Path(kwargs["stdout"].name) == home / ".hindsight" / "sr-daemon.log"
    assert kwargs["cwd"] == str(home / ".hindsight")
    assert kwargs["env"] == memory_server.environment(SHELL, "127.0.0.1", 8888)
    assert (home / ".hindsight" / "sr.pid").read_text() == "4242\n"
    assert ticker.sleeps == [2, 2]  # one refusal before the start, two polls refused, the third answered
    assert fake.banks["super-router"] == {"retain_extraction_mode": "chunks", "enable_observations": False}
    assert out[0] == ("memory: starting Hindsight: ~/.hindsight/venv/bin/hindsight-api --host 127.0.0.1 --port 8888 "
                      "(log ~/.hindsight/sr-daemon.log)")
    assert out[1:] == ["memory: online (http://127.0.0.1:8888, api 1.0.0)", "bank super-router: 0 documents",
                       "data: none yet (~/.pg0 appears on the first start)"]


def test_start_prints_a_line_every_20_seconds_and_gives_up_after_180(home):
    fake = FakeHindsight(online=False)
    code, out, popen, ticker = _start(fake, home)
    assert code == 1
    assert [line for line in out if line.startswith("memory: still starting")] == [
        f"memory: still starting ({s} s)" for s in range(20, 180, 20)]
    assert out[-1].startswith("memory: Hindsight has not answered after 180 s")
    assert "~/.hindsight/sr-daemon.log" in out[-1] and len(ticker.sleeps) == 90
    assert (home / ".hindsight" / "sr.pid").read_text() == "4242\n"  # kept: it may still be downloading


def test_start_reports_a_server_that_exits(home):
    fake = FakeHindsight(online=False)
    code, out, popen, ticker = _start(fake, home, popen=FakePopen(FakeProcess(dies_after=2)))
    assert code == 1
    assert out[-1] == "memory: Hindsight exited with code 1 before answering; see ~/.hindsight/sr-daemon.log"


def test_start_when_already_online_starts_nothing_and_still_makes_the_bank(home):
    fake = FakeHindsight()
    code, out, popen, _ = _start(fake, home)
    assert code == 0 and popen.calls == []
    assert fake.banks == {"super-router": memory.BANK_BODY}
    assert out[0] == "memory: already online (http://127.0.0.1:8888)"
    assert not (home / ".hindsight" / "sr.pid").exists()


def test_start_refuses_without_the_install(tmp_path):
    home = tmp_path / "bare"
    home.mkdir()
    fake = FakeHindsight(online=False)
    code, out, popen, _ = _start(fake, home)
    assert code == 2 and popen.calls == []
    assert out == [f"Refused: Hindsight is not installed at ~/.hindsight/venv/bin/hindsight-api. Install it with: "
                   f"{memory_server.INSTALL}. Nothing was started."]
    assert memory_server.INSTALL == ('python3 -m venv ~/.hindsight/venv && ~/.hindsight/venv/bin/pip install '
                                     '"hindsight-api-slim[local-onnx,embedded-db]"')


def test_start_refuses_a_memory_url_off_the_loopback_address_before_anything(home):
    fake = FakeHindsight(online=False)
    popen = FakePopen()
    with pytest.raises(memory_server.ServerError, match="loopback"):
        memory_server.start(_client(fake, url="http://10.0.0.5:8888"), environ=SHELL, home=home, popen=popen,
                            sleep=lambda s: None, clock=lambda: 0.0, out=lambda *_: None)
    assert popen.calls == [] and fake.requests == []


# ---------- stop ----------

def test_stop_sends_term_and_waits_until_health_stops_answering(home):
    fake = FakeHindsight()
    (home / ".hindsight" / "sr.pid").write_text("4242\n")
    kills = []

    def kill(pid, sig):
        kills.append((pid, sig))
        fake.online = False
    out, ticker = [], Ticker()
    code = memory_server.stop(_client(fake), home=home, kill=kill, sleep=ticker.sleep, clock=ticker.now, out=out.append)
    assert code == 0 and kills == [(4242, signal.SIGTERM)] and out == ["memory: stopped (pid 4242)"]
    assert not (home / ".hindsight" / "sr.pid").exists()


def test_stop_with_nothing_running(home):
    fake = FakeHindsight(online=False)
    out = []
    code = memory_server.stop(_client(fake), home=home, kill=lambda *a: pytest.fail("killed something"),
                              sleep=lambda s: None, clock=lambda: 0.0, out=out.append)
    assert code == 0 and out == ["memory: offline; nothing to stop"]


def test_stop_when_the_pid_file_is_stale(home):
    fake = FakeHindsight(online=False)
    (home / ".hindsight" / "sr.pid").write_text("99999\n")

    def kill(pid, sig):
        raise ProcessLookupError
    out, ticker = [], Ticker()
    code = memory_server.stop(_client(fake), home=home, kill=kill, sleep=ticker.sleep, clock=ticker.now, out=out.append)
    assert code == 0 and out == ["memory: process 99999 is already gone", "memory: stopped (pid 99999)"]
    assert not (home / ".hindsight" / "sr.pid").exists()


def test_stop_never_kills_a_server_it_did_not_start(home):
    fake = FakeHindsight()
    out = []
    code = memory_server.stop(_client(fake), home=home, kill=lambda *a: pytest.fail("killed something"),
                              sleep=lambda s: None, clock=lambda: 0.0, out=out.append)
    assert code == 1
    assert out == ["memory: online at http://127.0.0.1:8888, but sr memory start did not start it (no ~/.hindsight/sr.pid); "
                   "stop it yourself."]


def test_stop_gives_up_after_30_seconds(home):
    fake = FakeHindsight()
    (home / ".hindsight" / "sr.pid").write_text("4242\n")
    out, ticker = [], Ticker()
    code = memory_server.stop(_client(fake), home=home, kill=lambda *a: None, sleep=ticker.sleep, clock=ticker.now,
                              out=out.append)
    assert code == 1 and out[-1].startswith("memory: still answering 30 s after TERM (pid 4242)")
    assert (home / ".hindsight" / "sr.pid").exists()


# ---------- status (decision 3, choice 5) ----------

def test_status_offline_names_the_start_command(home):
    fake = FakeHindsight(online=False)
    out = []
    assert memory_server.status(_client(fake), home=home, out=out.append) == 1
    assert out == ["memory: offline (http://127.0.0.1:8888); sr memory start starts it",
                   "data: none yet (~/.pg0 appears on the first start)"]
    assert fake.of("health")[0]["timeout"] == 2


def test_status_online_prints_version_documents_and_data_size(home):
    data = home / ".pg0" / "instances" / "hindsight" / "data"  # where pg0 0.15.2 really puts it (the first real start)
    data.mkdir(parents=True)
    (data / "pg").write_bytes(b"x" * 3 * 1024 * 1024)
    fake = FakeHindsight(documents={"task-a": {"content": "c", "tags": ["chat:t"]}})
    out = []
    assert memory_server.status(_client(fake), home=home, out=out.append) == 0
    assert out == ["memory: online (http://127.0.0.1:8888, api 1.0.0)", "bank super-router: 1 documents",
                   "data: 3.0M ~/.pg0"]


def test_status_online_without_the_bank_yet(home):
    fake = FakeHindsight(fail={"stats": 404})
    out = []
    assert memory_server.status(_client(fake), home=home, out=out.append) == 0
    assert out[1].startswith("bank super-router: not created yet (HTTP 404 (GET /v1/default/banks/super-router/stats)); ")
    assert out[1].endswith("sr memory start creates it")


def test_the_data_folder_is_pg0_first_then_the_documented_one(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    assert memory_server.data_folder(home) is None
    (home / ".hindsight" / "data").mkdir(parents=True)
    assert memory_server.data_folder(home) == home / ".hindsight" / "data"
    (home / ".pg0").mkdir()
    assert memory_server.data_folder(home) == home / ".pg0"


def test_human_sizes_read_like_du():
    sizes = (0, 512, 1024, 15 * 1024, 3 * 1024 ** 2, 412 * 1024 ** 2, int(1.5 * 1024 ** 3))
    assert [memory_server.human(n) for n in sizes] == ["0B", "512B", "1.0K", "15K", "3.0M", "412M", "1.5G"]


# ---------- the command ----------

def _cmd(words, fake, home, **over):
    out = []
    kwargs = dict(request=fake.request, environ=SHELL, home=home, popen=FakePopen(), sleep=lambda s: None,
                  clock=lambda: 0.0, kill=lambda *a: None, out=out.append)
    kwargs.update(over)
    return cli.cmd_memory(words, **kwargs), out


def test_sr_memory_refuses_other_words(home):
    for words in (["frob"], [], ["start", "now"], ["rebuild", "all"]):
        code, out = _cmd(words, FakeHindsight(online=False), home)
        # brief 27: the usage names on and off too
        assert code == 2 and out == ["Refused: sr memory start|stop|status|rebuild|on|off. Nothing was changed."], words


def test_sr_memory_start_refuses_a_url_off_the_loopback_through_the_command(home, monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"memory_url": "http://10.0.0.5:8888"}))
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    code, out = _cmd(["start"], FakeHindsight(online=False), home)
    assert code == 2
    assert out == ["Refused: memory_url must be on the loopback address (127.0.0.1), not 10.0.0.5. Nothing was changed."]


def test_sr_memory_status_through_the_command(home):
    code, out = _cmd(["status"], FakeHindsight(), home)
    assert code == 0 and out[0] == "memory: online (http://127.0.0.1:8888, api 1.0.0)"


def test_main_runs_sr_memory_status_without_touching_the_log(monkeypatch, home, capsys):
    fake = FakeHindsight(online=False)
    monkeypatch.setattr(cli.requests, "request", fake.request)
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: home))
    assert cli.main(["memory", "status"], platform="darwin") == 1
    assert "memory: offline (http://127.0.0.1:8888); sr memory start starts it" in capsys.readouterr().out
    assert not cli.DB_PATH.exists()  # the temp log of this test was never created


# ---------- the client (decision 12 at the client level) ----------

@pytest.mark.parametrize("mode, text", [("refused", "ConnectionError"), ("timeout", "timed out after 10 s"),
                                        (500, "HTTP 500"), ("bad json", "not JSON")])
def test_client_turns_every_failure_into_unavailable_with_a_safe_text(mode, text):
    fake = FakeHindsight(fail={"recall": mode})
    with pytest.raises(memory.Unavailable, match=text) as caught:
        _client(fake).recall("q", "chat:t", max_tokens=2000)
    assert "127.0.0.1" not in str(caught.value) and "boom" not in str(caught.value)


def test_client_recall_body_and_result_list():
    fake = FakeHindsight(results=[FakeHindsight.result("task-x", "t")])
    results = _client(fake).recall("the question", "chat:t", max_tokens=2000)
    assert results == fake.results
    assert fake.recalls == [{"query": "the question", "tags": ["chat:t"], "tags_match": "any_strict", "max_tokens": 2000,
                             "budget": "low"}]
    call = fake.of("recall")[0]
    assert call["timeout"] == 10 and call["path"] == "/v1/default/banks/super-router/memories/recall"


def test_client_recall_refuses_a_reply_without_a_result_list():
    class Odd(FakeHindsight):
        def _answer(self, route, method, path, json):
            return Reply(200, {"results": "nope"}) if route == "recall" else super()._answer(route, method, path, json)
    with pytest.raises(memory.Unavailable, match="no result list"):
        _client(Odd()).recall("q", "chat:t", max_tokens=2000)


def test_client_retain_needs_success_true():
    fake = FakeHindsight()
    item = {"content": "c", "document_id": "task-x", "tags": ["chat:t"]}
    assert _client(fake).retain(item)["success"] is True
    assert fake.retains == [item] and fake.of("retain")[0]["timeout"] == 20
    assert fake.of("retain")[0]["path"] == "/v1/default/banks/super-router/memories"

    class Odd(FakeHindsight):
        def _answer(self, route, method, path, json):
            return Reply(200, {"success": False}) if route == "retain" else super()._answer(route, method, path, json)
    with pytest.raises(memory.Unavailable, match="did not confirm"):
        _client(Odd()).retain(item)


def test_client_health_version_stats_bank_and_deletes():
    fake = FakeHindsight(documents={"task-a": {"content": "c", "tags": ["chat:t"]}})
    c = _client(fake)
    assert c.online() and c.version() == "1.0.0" and c.stats()["total_documents"] == 1
    assert c.ensure_bank()["bank_id"] == "super-router"
    assert fake.banks["super-router"] == {"retain_extraction_mode": "chunks", "enable_observations": False}
    assert fake.of("bank")[0] == {"method": "PUT", "path": "/v1/default/banks/super-router", "json": memory.BANK_BODY,
                                  "timeout": 10, "route": "bank"}
    assert c.delete_document("task-a")["memory_units_deleted"] == 1 and fake.documents == {}
    assert fake.of("delete_document")[0]["path"] == "/v1/default/banks/super-router/documents/task-a"
    assert c.clear()["success"] is True and fake.of("clear")[0]["method"] == "DELETE"
    assert c.delete_bank("sr-scratch")["success"] is True
    assert fake.of("delete_bank")[0] == {"method": "DELETE", "path": "/v1/default/banks/sr-scratch", "json": None,
                                         "timeout": 10, "route": "delete_bank"}
    assert fake.of("health")[0]["timeout"] == 2


def test_client_from_settings(monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"memory_url": "http://127.0.0.1:9999/", "memory_bank": "other"}))
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    c = memory.client(FakeHindsight().request)
    assert (c.url, c.bank) == ("http://127.0.0.1:9999", "other")
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "none.json")
    c = memory.client(FakeHindsight().request)
    assert (c.url, c.bank) == ("http://127.0.0.1:8888", "super-router")


def test_memory_settings_defaults_and_file(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "none.json")
    assert settings.memory_setting("memory_url") == ("http://127.0.0.1:8888", "default")
    assert settings.memory_setting("memory_bank") == ("super-router", "default")
    assert settings.memory_setting("memory_max_items") == (5, "default")
    assert settings.memory_setting("memory_max_chars") == (2000, "default")
    assert settings.memory_setting("memory_query_chars") == (1500, "default")
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"memory_url": "http://127.0.0.1:8888", "memory_bank": "b", "memory_max_items": 3,
                                "memory_max_chars": "x", "memory_query_chars": 0}))
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    assert settings.memory_setting("memory_max_items") == (3, "config/settings.json")
    assert settings.memory_setting("memory_max_chars") == (
        2000, "default; memory_max_chars in config/settings.json is not a positive whole number")
    assert settings.memory_setting("memory_query_chars")[0] == 1500
    assert settings.memory_setting("memory_bank") == ("b", "config/settings.json")
    with pytest.raises(KeyError):
        settings.memory_setting("memory_other")
