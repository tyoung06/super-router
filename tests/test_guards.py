"""Guards that keep every test away from the live log, real processes and real waiting."""
import subprocess

import pytest

from router import __main__ as cli


def test_every_test_uses_a_temp_log(tmp_path):
    assert cli.DB_PATH == tmp_path / "router.db"
    assert cli.BACKUPS_DIR == tmp_path / "backups"


def test_real_subprocesses_are_blocked():
    with pytest.raises(RuntimeError, match="real subprocess"):
        subprocess.run(["true"])


def test_real_http_requests_are_blocked():
    import requests
    with pytest.raises(RuntimeError, match="real HTTP request"):
        requests.post("https://example.invalid/hook", json={}, timeout=1)
    with pytest.raises(RuntimeError, match="real HTTP request"):
        requests.get("https://example.invalid/", timeout=1)


def test_real_typesafe_clients_are_blocked():
    import typesafe_sdk

    from router import jev
    with pytest.raises(RuntimeError, match="real TypeSafe client"):
        typesafe_sdk.TypeSafeClient(api_key="FAKE-JEV-KEY")
    with pytest.raises(RuntimeError, match="real TypeSafe client"):
        jev.make_client("FAKE-JEV-KEY")
