"""Build brief 23, A4 (decisions 15 and 6; the hard limit "never opens .env"): `sr serve --demo` starts before the
roster, the host check, the billing switches, `.env` and the log, so a fresh clone with its requirements installed shows
the page on any system; `sr serve` itself never reads `.env` (its lines are its own; the commands it runs redact their
own output); its help no longer says read-only, and it prints where the page is and that tasks outlive it. Fakes only:
no server is started here."""
import json

import pytest

from router import __main__ as cli
from router import page, status


def _boom(*a, **k):
    raise AssertionError("must not run for sr serve --demo")


@pytest.fixture
def served(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.page, "serve_demo", lambda port, **kw: seen.update(demo_port=port, **kw) or 0)
    monkeypatch.setattr(cli.page, "serve", lambda port, **kw: seen.update(port=port, **kw) or 0)
    return seen


def test_serve_demo_starts_before_the_roster_the_host_check_the_billing_switches_env_and_the_log(served, monkeypatch):
    for name in ("load_roster", "_workers", "dotenv_values", "_printer", "_read_log"):
        monkeypatch.setattr(cli, name, _boom)
    monkeypatch.setattr(cli.safety, "check_host", _boom)
    monkeypatch.setattr(cli.log, "init_db", _boom)
    assert cli.main(["serve", "--demo"], platform="linux") == 0
    assert served["demo_port"] == 8765 and "port" not in served


def test_serve_demo_takes_a_port(served, monkeypatch):
    monkeypatch.setattr(cli, "load_roster", _boom)
    assert cli.main(["serve", "--demo", "--port", "9100"]) == 0 and served["demo_port"] == 9100


def test_serve_demo_falls_back_to_the_default_port_when_settings_cannot_be_read(served, monkeypatch):
    def unreadable():
        raise OSError("no settings")
    monkeypatch.setattr(cli.settings, "serve_port", unreadable)
    assert cli.main(["serve", "--demo"]) == 0 and served["demo_port"] == page.DEFAULT_PORT


def test_sr_serve_never_reads_env(served, monkeypatch):
    monkeypatch.setattr(cli, "dotenv_values", _boom)
    monkeypatch.setattr(cli, "_printer", _boom)
    assert cli.main(["serve"], platform="darwin") == 0
    assert served["port"] == 8765 and set(served) == {"port", "out", "start_memory"}


def test_the_start_line_says_where_the_page_is_and_that_tasks_outlive_it():
    assert page.start_line(8765) == "Page: http://127.0.0.1:8765  (Ctrl+C stops the page; tasks it started keep running)"
    assert page.demo_line(8765) == "Demo: http://127.0.0.1:8765  (sample tasks, nothing runs; Ctrl+C stops it)"


def test_serve_prints_the_start_line(monkeypatch):
    class Server:
        server_address = ("127.0.0.1", 8123)
        reader = None  # the ticker's tick on it fails quietly; the server is stopped long before the first minute

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            self.closed = True
    lines = []
    monkeypatch.setattr(page, "make_server", lambda port, reader=None, **kw: Server())
    assert page.serve(8123, out=lines.append) == 0
    assert lines == [page.start_line(8123)]


def test_the_serve_help_is_no_longer_read_only_and_lists_demo():
    found = {c["name"]: c for c in status.commands_view(cli._parser(None))}
    assert "read-only" not in (found["serve"]["help"] or "")
    assert "--demo" in [a["name"] for a in found["serve"]["arguments"]]


def test_the_demo_reader_serves_the_demo_files_and_runs_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(page.subprocess, "run", _boom)
    monkeypatch.setattr(page.subprocess, "Popen", _boom)
    (tmp_path / "status.json").write_text(json.dumps({"api_version": 1, "agents": []}))
    (tmp_path / "log.json").write_text(json.dumps({"api_version": 1, "tasks": [], "next_before": None}))
    reader = page.DemoReader(tmp_path)
    assert reader.status() == (200, json.dumps({"api_version": 1, "agents": []}).encode())
    assert reader.log()[0] == 200
    empty = page.DemoReader(tmp_path / "missing")
    assert empty.status()[0] == 404
