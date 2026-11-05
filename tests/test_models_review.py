"""Build brief 33.3, the review's items that need a project (before D's setup): a model choice through `sr plan`, a
refused `--model` before `--step`'s file check, and a split's choice staying off its pieces (decision 14: no model per
piece). Fakes only; the project is a throwaway git repository under tmp."""
import pytest

from router import __main__ as cli
from router import log, receipt
from tests.helpers import fake_label
from tests.test_filemode_flow import CODE, CopyWorker, conn, project, runner  # noqa: F401 (fixtures)
from tests.test_loop import Clock, Webhook
from tests.test_plan_chain import LOADED, World as PlanWorld
from tests.test_relay import CONFIG, ROSTER, Chat
from tests.helpers import shipped_roster
from tests.test_relay import RelayHook
from tests.test_split_pieces import World as SplitWorld, Ask, _pieces, TASK as SPLIT_TASK, teamed, JOIN, P1, P2

OPUS, SONNET = "claude-opus-5-5", "claude-sonnet-5-5"


def test_a_plan_takes_a_model_choice_for_its_agents_and_uses_it_on_every_call(project, conn, runner):
    refused = receipt.Receipt()
    code = cli.cmd_plan("x", conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[],
                        post=Webhook().post, worker=CopyWorker("x"), chatgpt=Chat(), codex_login=lambda: True,
                        project="garden", files_ready=lambda: (True, None), model_flags=["grok=x"], out=refused)
    assert (code, refused.code) == (2, "bad_model") and "Grok Bot has no model choice" in refused.message
    assert log.recent_tasks(conn, 50) == []  # nothing written for the refused one
    w = PlanWorld()
    code, row = w.plan(conn, model_flags=["claude=opus", "chatgpt=gpt-6-astra"])
    assert row is not None and code in (0, 5), w.said
    assert log.models_of(row) == {"claude": {"model": OPUS, "effort": None}, "chatgpt": {"model": "gpt-6-astra", "effort": None}}
    calls = [c for c in log.calls_for(conn, row["task_id"]) if c["agent"] in ("claude", "chatgpt")]
    assert calls and all(c["model"] == {"claude": OPUS, "chatgpt": "gpt-6-astra"}[c["agent"]] for c in calls)


def test_a_refused_cursor_model_on_redteam_runs_no_canary(conn):
    # review c2: `relay redteam --model cursor=auto` is refused before Cursor's readiness check (the canaries at intake)
    roster = shipped_roster()
    loaded = cli._presets_or_none(roster)
    seen = []
    out = receipt.Receipt()
    code = cli.cmd_relay("redteam", "x", conn=conn, config=CONFIG, roster=roster, loaded=loaded, environ={}, settings_paths=[],
                         post=RelayHook().post, worker=CopyWorker("x"), chatgpt=Chat("PASS"), codex_login=lambda: True,
                         cursor=CopyWorker("x"), cursor_ready=lambda: seen.append("canaries") or (True, None),
                         model_flags=["cursor=auto"], out=out)
    assert (code, out.code) == (2, "bad_model") and "isn't on cursor's allowed list" in out.message and seen == []
    assert log.recent_tasks(conn, 50) == []


def test_a_refused_model_runs_before_steps_file_check(project, conn, runner):
    seen = []
    out = receipt.Receipt()
    code = cli.cmd_route("x", conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=fake_label(CODE),
                         post=Webhook().post, worker=CopyWorker("x"), chatgpt=Chat("PASS"), codex_login=lambda: True,
                         project="garden", files_ready=lambda: seen.append("file check") or (True, None), step_ref="1:1",
                         model_flags=["claude=nope"], out=out)
    assert (code, out.code) == (2, "bad_model") and seen == [] and log.recent_tasks(conn) == []


def test_a_splits_choice_stays_off_its_pieces(conn):
    w = SplitWorld(claude=("piece one", "piece two", "joined"), chatgpt=("PASS", "PASS", "PASS"))
    w.worker.replies.insert(0, teamed(f"## Pieces\n1. {P1}\n2. {P2}\n\n## Join\n{JOIN}\n", team=["route", "route"]))
    code = cli.cmd_split(SPLIT_TASK, conn=conn, model_flags=["claude=haiku"], **w.kw(Ask("y")))
    assert code == 0, w.out
    split_row = next(r for r in log.recent_tasks(conn, 50) if r["mode"] == "split")
    assert log.models_of(split_row) == {"claude": {"model": "claude-haiku-5-5", "effort": None}}
    own = [c for c in log.calls_for(conn, split_row["task_id"]) if c["agent"] == "claude"]
    assert own and all(c["model"] == "claude-haiku-5-5" for c in own)  # the plan and the join: the split's own calls
    pieces = _pieces(conn)
    assert pieces and all(log.models_of(p) == {} for p in pieces)  # decision 14: no model per piece
    for p in pieces:
        for c in log.calls_for(conn, p["task_id"]):
            if c["agent"] == "claude":
                assert c["model"] == SONNET  # its team's defaults, never the split's Haiku
