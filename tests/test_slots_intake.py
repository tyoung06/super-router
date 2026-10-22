"""Build brief 15, phase B: intake on slots (rules v2.21, Relay → Intake on slots). `sr relay <preset> "<task>"
--<slot> <agent>` puts that agent in that slot for this task only. Refused at intake, with the reason, before any
call is made or any row is written: a slot the preset doesn't have, an agent name that doesn't exist, an agent that
is not live, a slot named twice, a flag with no agent, a filling that makes an agent check or review its own work
(build = check, lead = partner, a = b), or anything else a preset may not do. Slot flags on `sr route` or
`sr split` are refused. Every value here is fake."""
import hashlib
import json

import pytest

from router import __main__ as cli
from router import log, presets, relay
from tests.helpers import shipped_roster
from tests.test_relay import CONFIG, GOOD_NOTE, ROSTER, Chat, Clock, RelayHook, Scripted

SENDERS = tuple(cli.SENDERS)
LOADED = presets.load_presets(shipped_roster(), SENDERS, relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _relay(conn, preset_name, slots=(), task="Write a tagline for a garden seed tray."):
    lines, clock = [], Clock()
    hook = RelayHook(s1=GOOD_NOTE, s2="B's tagline.", s3="## Verdict\npass\n## Notes\nfine")
    worker, chatgpt = Scripted("A result."), Chat("PASS")
    code = cli.cmd_relay(preset_name, task, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                         settings_paths=[], post=hook.post, worker=worker, chatgpt=chatgpt, codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=False,
                         slots=list(slots), out=lines.append)
    rows = log.recent_tasks(conn)
    return code, "\n".join(lines), rows[0] if rows else None, hook, worker, chatgpt


# ---------- the row records the slots (D1) ----------

@pytest.mark.parametrize("name, expected", [
    ("research-build", {"research": "grok", "build": "claude", "check": "chatgpt"}),
    ("collab", {"lead": "claude", "partner": "chatgpt"}),
    ("versus", {"a": "claude", "b": "chatgpt"}),
])
def test_a_relay_task_with_no_flag_stores_its_full_default_slot_map(conn, name, expected):
    _, _, row, *_ = _relay(conn, name)
    assert json.loads(row["slots"]) == expected


def test_a_filled_slot_is_stored_and_the_row_names_the_filled_doer_and_checker(conn):
    code, out, row, *_ = _relay(conn, "research-build", [("build", "chatgpt"), ("check", "claude")])
    assert json.loads(row["slots"]) == {"research": "grok", "build": "chatgpt", "check": "claude"}
    assert (row["agent"], row["checker"]) == ("chatgpt", "claude")
    assert "relay research-build: research by grok -> build by chatgpt, checked by claude." in out


def test_versus_with_b_filled_by_grok_names_grok_for_build_b_and_review_a(conn):
    code, out, row, *_ = _relay(conn, "versus", [("b", "grok")])
    assert json.loads(row["slots"]) == {"a": "claude", "b": "grok"}
    assert (row["agent"], row["checker"]) == ("claude", None)
    assert ("build by claude -> build by grok -> review of stage 1 by grok -> review of stage 2 by claude, "
            "then your pick.") in out


def test_collab_with_lead_and_partner_swapped(conn):
    code, out, row, *_ = _relay(conn, "collab", [("lead", "chatgpt"), ("partner", "claude")])
    assert json.loads(row["slots"]) == {"lead": "chatgpt", "partner": "claude"}
    assert (row["agent"], row["checker"]) == ("chatgpt", "claude")
    assert "checked by stage 4 (claude)." in out


# ---------- every refusal: its own message, no row, no call ----------

REFUSALS = [
    ("collab", [("research", "grok")], "collab has no slot research (its slots: lead, partner)."),
    ("versus", [("b", "gemini")], "no agent named gemini (agents: "),
    ("versus", [("b", "muse")], "muse is not live, so it can't fill slot b."),
    ("versus", [("b", "grok"), ("b", "claude")], "--b is named twice; a slot holds one agent."),
    ("versus", [("b", None)], "--b needs an agent: --b <agent>."),
    ("versus", [("a", "claude"), ("b", "claude")],
     "slots a and b both hold claude; no agent checks or reviews its own work."),
    ("research-build", [("build", "chatgpt"), ("check", "chatgpt")],
     "slots build and check both hold chatgpt; no agent checks or reviews its own work."),
    ("research-build", [("check", "claude")],
     "slots build and check both hold claude; no agent checks or reviews its own work."),
    ("collab", [("lead", "grok"), ("partner", "grok")],
     "slots lead and partner both hold grok; no agent checks or reviews its own work."),
    ("collab", [("partner", "claude")],
     "slots lead and partner both hold claude; no agent checks or reviews its own work."),
]


@pytest.mark.parametrize("name, slots, words", REFUSALS)
def test_each_refusal_says_why_writes_no_row_and_calls_no_one(conn, name, slots, words):
    code, out, row, hook, worker, chatgpt = _relay(conn, name, slots)
    assert code == 2 and row is None
    assert f"Refused: {words}" in out and "Nothing was logged or sent." in out
    assert hook.sent == [] and worker.prompts == [] and chatgpt.prompts == []


def test_every_refusal_has_its_own_message():
    assert len({words for _, _, words in REFUSALS[:6]}) == 6


def test_a_slot_flag_on_a_preset_with_no_slots_is_refused(conn, tmp_path):
    doc = json.loads(presets.PRESETS_PATH.read_text())
    del doc["presets"]["versus"]["slots"]
    path = tmp_path / "presets.json"
    path.write_text(json.dumps(doc))
    loaded = presets.load_presets(shipped_roster(), SENDERS, relay.CONTRACTS, path=path, roles=relay.ROLES,
                                  verdicts=relay.VERDICTS)
    lines = []
    code = cli.cmd_relay("versus", "t", conn=conn, config=CONFIG, roster=ROSTER, loaded=loaded, environ={},
                         settings_paths=[], post=None, worker=None, slots=[("b", "grok")], out=lines.append)
    assert code == 2 and "Refused: versus has no slot b (it has no slots)." in lines and log.recent_tasks(conn) == []


# ---------- presets helpers ----------

@pytest.mark.parametrize("name", ["research-build", "collab", "versus"])
def test_a_shipped_preset_written_back_as_an_entry_has_no_problems(name):
    entry = presets.as_entry(LOADED.presets[name])
    assert presets.problems(name, entry, shipped_roster(), SENDERS, relay.CONTRACTS, roles=relay.ROLES,
                            verdicts=relay.VERDICTS) == []


def test_own_work_names_the_two_slots_that_hold_the_same_agent():
    assert presets.own_work(presets.fill(LOADED.presets["versus"], {"b": "claude"})) == [("a", "b", "claude")]
    assert presets.own_work(LOADED.presets["versus"]) == []


def test_slot_names_are_read_from_the_file():
    assert presets.slot_names() == ("research", "build", "check", "lead", "partner", "a", "b", "attack", "c")  # 16; 17: c


# ---------- the command line ----------

@pytest.mark.parametrize("argv, rest, found", [
    (["relay", "versus", "t", "--b", "grok"], ["relay", "versus", "t"], [("b", "grok")]),
    (["relay", "versus", "t", "--b=grok", "--no-wait"], ["relay", "versus", "t", "--no-wait"], [("b", "grok")]),
    (["relay", "versus", "--a", "chatgpt", "t"], ["relay", "versus", "t"], [("a", "chatgpt")]),
    (["relay", "versus", "t", "--b"], ["relay", "versus", "t"], [("b", None)]),
    (["relay", "versus", "t", "--b", "--no-wait"], ["relay", "versus", "t", "--no-wait"], [("b", None)]),
    (["relay", "versus", "t", "--file", "x.png", "--source", "page"], ["relay", "versus", "t", "--file", "x.png",
                                                                         "--source", "page"], []),
    (["relay", "--list"], ["relay", "--list"], []),
    (["relay", "versus", "t", "--", "--b", "grok"], ["relay", "versus", "t", "--", "--b", "grok"], []),
    (["route", "t", "--b", "grok"], ["route", "t", "--b", "grok"], []),
])
def test_slot_flags_are_taken_out_of_a_relay_command_before_argparse(argv, rest, found):
    assert cli._take_slot_flags(argv) == (rest, found)


def _db_hash():
    return hashlib.sha256(cli.DB_PATH.read_bytes()).hexdigest()


def _seed_log():
    c = log.init_db(cli.DB_PATH)
    log.add_task(c, "sr-seed", "an earlier task", "cli", {"status": "ok", "label": "writing", "confidence": 0.9})
    c.close()
    return _db_hash()


@pytest.mark.parametrize("argv, words", [
    (["route", "x", "--build", "claude"], "slot flags are for sr relay only (--build on sr route)."),
    (["split", "x", "--a=claude"], "slot flags are for sr relay only (--a on sr split)."),
])
def test_a_slot_flag_on_route_or_split_is_refused_and_the_log_is_unchanged(capsys, argv, words):
    before = _seed_log()
    assert cli.main(argv, platform="darwin") == 2
    out = capsys.readouterr().out
    assert f"Refused: {words} Nothing was logged or sent." in out
    assert _db_hash() == before


def test_a_refused_relay_slot_flag_leaves_the_log_byte_identical(monkeypatch, capsys):
    before = _seed_log()
    monkeypatch.setattr(cli.safety, "prepare_workspace", lambda *a, **k: None)
    monkeypatch.setattr(cli, "dotenv_values", lambda *_: dict(CONFIG))
    assert cli.main(["relay", "versus", "x", "--a", "claude", "--b", "claude"], platform="darwin") == 2
    out = capsys.readouterr().out
    assert "Refused: slots a and b both hold claude; no agent checks or reviews its own work." in out
    assert _db_hash() == before
