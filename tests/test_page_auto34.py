"""Build brief 34 (decisions 10 and 13): the page's Auto. The switch's actions (`auto_on`, `auto_off`) build one `sr auto
--json <project> --on|--off`; a step's Stop here toggle builds `sr plan --json --stop-here <plan>:<k> on|off`; the
switch's confirm is `GET /api/auto-check?name=` (the dry run, never cached, a bad name a 400, nothing run); each of the
three drops the kept status; the parser carries `sr auto` and `--stop-here` through main. No run starts here."""
import json
from types import SimpleNamespace

import pytest

from router import __main__ as cli
from router import page
from router import page_commands as pc
from tests.test_page_plan331 import STATUS, TID
from tests.test_page_server import Reads, _call, repo, world  # noqa: F401 (fixtures)


# ---------- the actions (decision 10) ----------

@pytest.mark.parametrize("action, flag", [("auto_on", "--on"), ("auto_off", "--off")])
def test_the_switch_is_one_sr_auto(action, flag):
    found = pc.build({"action": action, "name": "seed-trays"}, STATUS)
    assert found.args == ("auto", "--json", "--source", "ui", "seed-trays", flag) and found.added == frozenset({1, 2, 3})


@pytest.mark.parametrize("name", ["Seed", "-h", "--on", "a/b", "", None, "a.b"])
def test_the_switch_refuses_a_bad_project_name(name):
    with pytest.raises(pc.Refused, match="the project name"):
        pc.build({"action": "auto_on", **({"name": name} if name is not None else {})}, STATUS)


@pytest.mark.parametrize("to", ["on", "off"])
def test_stop_here_is_one_sr_plan_stop_here(to):
    found = pc.build({"action": "plan_stop_here", "step": f"{TID}:2", "to": to}, STATUS)
    assert found.args == ("plan", "--json", "--source", "ui", "--stop-here", f"{TID}:2", to) and found.added == frozenset({1, 2, 3})


@pytest.mark.parametrize("request_, words", [
    ({"step": "2", "to": "on"}, "a step is"),
    ({"step": f"{TID}:x", "to": "on"}, "a step is"),
    ({"step": 2, "to": "on"}, "a step is"),
    ({"step": f"{TID}:2", "to": "maybe"}, "on or off"),
    ({"step": f"{TID}:2"}, "on or off"),
])
def test_stop_here_refuses_anything_else(request_, words):
    with pytest.raises(pc.Refused, match=words):
        pc.build({"action": "plan_stop_here", **request_}, STATUS)


def test_the_three_actions_drop_the_kept_status():
    assert {"auto_on", "auto_off", "plan_stop_here"} <= set(page.DROPS_STATUS)
    assert {"auto_on", "auto_off", "plan_stop_here"} <= set(pc.ACTIONS)


# ---------- the confirm, GET /api/auto-check (decision 10) ----------

class CheckReads(Reads):
    """The fake reads plus the dry run: `sr auto --json <name> --on --dry-run` answers the run's cover."""

    def __call__(self, argv, **kw):
        if argv[3] == "auto":
            assert isinstance(argv, list) and not kw.get("shell")
            self.calls.append(argv)
            doc = {"api_version": 1, "auto": {"steps": [1, 2], "budget": 9, "estimate": {"max_calls": 6}, "first_stop_here": None,
                                              "words": "Auto runs steps 1 to 2 of plan #1: 2 steps, up to 9 calls."},
                   "reason_code": None, "message": "m"}
            return SimpleNamespace(returncode=0, stdout=json.dumps(doc) + "\n", stderr="")
        return super().__call__(argv, **kw)


@pytest.fixture
def checking(world):
    reads = CheckReads(world.tmp)
    world.srv.reader.run = reads
    return reads


def test_the_confirm_runs_only_the_dry_run_and_returns_its_json(world, checking):
    resp, body = _call(world.srv, "GET", "/api/auto-check?name=seed-trays")
    assert resp.status == 200 and json.loads(body)["auto"]["steps"] == [1, 2]
    assert [argv[3:] for argv in checking.calls] == [["auto", "--json", "seed-trays", "--on", "--dry-run"]]


def test_the_confirm_is_not_cached(world, checking):
    for _ in range(3):
        assert _call(world.srv, "GET", "/api/auto-check?name=seed-trays")[0].status == 200
    assert checking.count("auto") == 3


@pytest.mark.parametrize("query", ["name=Seed", "name=-h", "name=--on", "name=a%2Fb", "name=", "", "name=a.b"])
def test_a_bad_name_answers_400_before_any_run(world, checking, query):
    resp, body = _call(world.srv, "GET", "/api/auto-check?" + query)
    assert resp.status == 400 and "the project name" in json.loads(body)["error"] and checking.calls == []


def test_the_confirm_needs_the_token(world, checking):
    assert _call(world.srv, "GET", "/api/auto-check?name=seed-trays", token=False)[0].status == 403
    assert checking.calls == []


def test_a_refused_dry_run_is_a_502_with_its_words(world):
    world.srv.reader.run = lambda argv, **kw: SimpleNamespace(
        returncode=2, stdout="", stderr=json.dumps({"exit": 2, "reason_code": "auto_refused", "message": "Refused: no plan"}) + "\n")
    resp, body = _call(world.srv, "GET", "/api/auto-check?name=seed-trays")
    assert resp.status == 502 and json.loads(body)["reason_code"] == "auto_refused"


def test_the_demo_answers_the_confirm_from_its_own_file(tmp_path):
    folder = tmp_path / "demo"
    (folder / "auto-check").mkdir(parents=True)
    (folder / "auto-check" / "seed-trays.json").write_text(json.dumps({"auto": {"steps": [3]}}))
    reader = page.DemoReader(folder)
    code, body = reader.auto_check("seed-trays")
    assert code == 200 and json.loads(body)["auto"]["steps"] == [3]
    assert reader.auto_check("other")[0] == 404


# ---------- the parser (decisions 1 and 6) ----------

def test_main_hands_sr_auto_its_flags_and_gates(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.safety, "prepare_workspace", lambda *a, **k: None)
    monkeypatch.setattr(cli, "cmd_auto", lambda words, **kw: seen.update(kw, words=words) or 0)
    assert cli.main(["auto", "seed-trays", "--on", "--dry-run"], platform="darwin") == 0
    assert seen["words"] == ["seed-trays"] and seen["on"] and seen["dry_run"] and not seen["off"] and not seen["status"]
    for key in ("claude_ready", "files_ready", "available", "cursor_ready", "chatgpt_ready", "hindsight", "label"):
        assert key in seen, key
    seen.clear()
    assert cli.main(["auto", "seed-trays", "--off"], platform="darwin") == 0
    assert seen["off"] and not seen["on"]


def test_main_hands_stop_here_to_its_command(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.safety, "prepare_workspace", lambda *a, **k: None)
    monkeypatch.setattr(cli, "cmd_plan_stop_here", lambda ref, words, **kw: seen.update(ref=ref, words=words) or 0)
    monkeypatch.setattr(cli, "cmd_plan", lambda *a, **kw: seen.update(plan=True) or 0)
    assert cli.main(["plan", "--stop-here", f"{TID}:2", "on"], platform="darwin") == 0
    assert seen == {"ref": f"{TID}:2", "words": ["on"]}


def test_sr_auto_needs_exactly_one_of_its_flags(monkeypatch, tmp_path):
    out = []
    code = cli.cmd_auto(["seed-trays"], conn=None, config={}, roster=None, loaded=None, environ={}, settings_paths=[],
                        label=None, post=None, worker=None, out=out.append)
    assert code == 2 and "sr auto <project>" in "\n".join(out)
    code = cli.cmd_auto(["seed-trays"], conn=None, config={}, roster=None, loaded=None, environ={}, settings_paths=[],
                        label=None, post=None, worker=None, on=True, off=True, out=out.append)
    assert code == 2
    code = cli.cmd_auto(["seed-trays"], conn=None, config={}, roster=None, loaded=None, environ={}, settings_paths=[],
                        label=None, post=None, worker=None, status=True, dry_run=True, out=out.append)
    assert code == 2
