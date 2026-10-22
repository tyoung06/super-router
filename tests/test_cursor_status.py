"""Build brief 20, phase C (decision 9 with amendment 4), as build brief 21 carries it: each agent's online state,
Cursor's among them. `online` is true, false or null (not checked) with `checked_at` and `reason`; Cursor's check is
`agent status`, never a model call; the checks run inside `sr status --json`, which `sr serve` runs at most once a
minute while the page polls every five seconds (tests/test_page.py). Fakes only."""
import json

from router import __main__ as cli
from router import online, page, status
from tests.conftest import REAL_ONLINE_CHECKS
from tests.helpers import roster_with, shipped_roster
from tests.test_page import Commands, Clock, _request, _serve

ROSTER = shipped_roster()
STATE = {"online": True, "reason": None, "checked_at": "2026-10-20T00:00:00+00:00"}
ENV = {"GROK_WEBHOOK_URL": "u", "GROK_WEBHOOK_KEY": "k"}


def _agents(roster=ROSTER, found=None, conn=None):
    from datetime import datetime
    from pathlib import Path
    view = status.agents_view(conn, roster, ENV, found or {}, {}, Path("/nowhere/probe_state.json"), datetime.now().astimezone())
    return {a["name"]: a for a in view}


def test_an_agent_carries_online_checked_at_and_reason_when_given():
    cards = _agents(found={"cursor": STATE})
    assert (cards["cursor"]["online"], cards["cursor"]["checked_at"], cards["cursor"]["reason"]) == (True, STATE["checked_at"], None)
    assert cards["claude"]["online"] is None and cards["claude"]["checked_at"] is None and cards["claude"]["reason"] is None
    assert cards["cursor"]["live"] is True  # live since the owner's flip, 2026-10-20
    cards = _agents(roster_with(cursor=False), found={"cursor": STATE})  # the check shows while not live too
    assert (cards["cursor"]["live"], cards["cursor"]["online"]) == (False, True)


def test_the_checks_run_and_an_offline_one_says_why():
    found = online.run_all({"cursor": lambda: (False, "not signed in (agent login)")})
    assert found["cursor"]["online"] is False and found["cursor"]["reason"] == "not signed in (agent login)"
    assert found["cursor"]["checked_at"]


def test_the_checks_run_at_most_once_a_minute_per_server():
    commands, clock = Commands(), Clock()
    reader = page.Reader(run=commands, clock=clock)
    for _ in range(12):  # the page polls every 5 s; the checks live inside sr status --json
        reader.status()
        clock.t += 5
    assert [argv[3] for argv, _ in commands.calls] == ["status"]
    clock.t = 61
    reader.status()
    assert len(commands.calls) == 2 and page.STATUS_SECONDS == 60


def test_a_check_that_blows_up_reads_as_offline_with_the_type():
    def boom():
        raise OSError("gone")
    found = online.run_all({"cursor": boom})
    assert found["cursor"]["online"] is False and found["cursor"]["reason"] == "check failed (OSError)"


def test_a_missing_log_still_shows_the_online_state():
    cards = _agents(found={"cursor": {"online": True, "reason": None, "checked_at": "t"}}, conn=None)
    assert cards["cursor"]["online"] is True and cards["cursor"]["calls_this_week"] == 0


def test_the_server_serves_the_online_state_and_keeps_it_between_requests():
    commands = Commands(status={"agents": [{"name": "cursor", "online": True, "checked_at": "t"}]})
    srv = _serve(page.Reader(run=commands, clock=Clock()))
    try:
        for _ in range(3):
            resp, body = _request(srv, "/api/status")
            card = next(a for a in json.loads(body)["agents"] if a["name"] == "cursor")
            assert resp.status == 200 and card["online"] is True and card["checked_at"]
        assert len(commands.calls) == 1
    finally:
        srv.shutdown()
        srv.server_close()



def test_cursors_check_in_sr_status_is_agent_status():
    assert REAL_ONLINE_CHECKS["cursor"] is online.cursor  # brief 24: conftest swaps the table for answers that run nothing
    assert online.cursor(check=lambda: (True, None)) == (True, None)
    import inspect
    assert inspect.signature(online.cursor).parameters["check"].default is cli.cursor_worker.online
