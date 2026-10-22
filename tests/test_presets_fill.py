"""Build brief 24, B3 (decision 8): at intake, a slot whose default agent isn't available is filled by the other of
Claude and ChatGPT (for a Grok slot: ChatGPT, then Claude), as long as every slot rule still holds (`slot_refusals`,
then `problems()` on the filled preset). Otherwise the task is refused before any row, naming the slot and why no other
agent can take it. A slot set by flag is never refilled. The live check left the loader, so a preset whose default
names an agent that isn't live stays listed. Fakes only."""
import pytest

from router import __main__ as cli
from router import availability, log, presets, relay
from tests.helpers import shipped_roster
from tests.test_loop import Clock, Scripted
from tests.test_relay import CONFIG, GOOD_NOTE, Chat, RelayHook
from tests.test_routing_availability import WHY, Gate, _table

ROSTER = shipped_roster()
SENDERS = tuple(cli.SENDERS)
LOADED = presets.load_presets(ROSTER, SENDERS, relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)


def _fill(name, out=(), flags=()):
    table = _table(set(out))
    return presets.fill_unavailable(LOADED.presets[name], list(flags), ROSTER, lambda n: table[n], send_paths=SENDERS,
                                    contracts=relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)


# preset -> what happens with each set of agents out: a dict of filled slots, or the words of the refusal
REFUSED = {
    "research-build": "research-build can't run now: slot check (ChatGPT): {chatgpt}; no other agent can check there "
                      "(Claude is in slot build)",
    "collab": "collab can't run now: slot partner (ChatGPT): {chatgpt}; no other agent can amend the plan there (Claude is "
              "in slot lead)",
    "versus": "versus can't run now: slot b (ChatGPT): {chatgpt}; no other agent can build there (Claude is in slot a)",
    "redteam": "redteam can't run now: slot attack (ChatGPT): {chatgpt}; no other agent can attack there (Claude is in "
               "slot build)",
    "vote": "vote can't run now: slot b (ChatGPT): {chatgpt}; no other agent can vote there (Claude is in slot a)",
}
TABLE = {
    (): {name: {} for name in LOADED.presets},
    ("cursor",): {name: {} for name in LOADED.presets},
    ("grok",): {"research-build": {"research": "chatgpt"}, "collab": {}, "versus": {}, "redteam": {},
                "vote": "vote can't run now: slot c (Grok Bot): {grok}; no other agent can vote there (ChatGPT is in slot "
                        "b; Claude is in slot a)"},
    ("chatgpt",): REFUSED,
    ("chatgpt", "grok"): REFUSED,
}


@pytest.mark.parametrize("out", list(TABLE), ids=lambda o: "+".join(o) or "none")
@pytest.mark.parametrize("name", ["research-build", "collab", "versus", "redteam", "vote"])
def test_every_shipped_preset_with_each_agent_out(name, out):
    filled, fills, why = _fill(name, out)
    want = TABLE[out][name]
    if isinstance(want, str):
        assert (filled, fills, why) == (None, [], want.format(**WHY))
        return
    assert {f["slot"]: f["agent"] for f in fills} == want
    assert all(f["why"] == WHY[f["default"]] for f in fills)
    assert all(s.agent != a for s in filled.slots for a in out)   # no slot holds an agent that is out


def test_a_slot_set_by_flag_is_never_refilled():
    filled, refused = presets.slot_refusals(LOADED.presets["vote"], [("c", "grok")], ROSTER,
                                            lambda n: _table({"grok"})[n])
    assert filled is None and refused == [f"grok can't fill slot c: {WHY['grok']}."]
    filled, fills, why = _fill("research-build", out={"grok"}, flags=[("research", "claude")])
    assert {s.name: s.agent for s in filled.slots}["research"] == "claude" and fills == []  # the flag stands, nothing filled


def test_a_cursor_or_grok_default_takes_chatgpt_then_claude():
    assert presets.fill_candidates("grok") == presets.fill_candidates("cursor") == ["chatgpt", "claude"]
    assert presets.fill_candidates("claude") == ["chatgpt"] and presets.fill_candidates("chatgpt") == ["claude"]


def test_the_fills_ride_on_route_reason_and_read_back():
    fills = [{"slot": "research", "agent": "chatgpt", "default": "grok",
              "why": "Grok Bot isn't set up: no GROK_WEBHOOK_URL in .env; no inbox repo in settings"},
             {"slot": "check", "agent": "claude", "default": "chatgpt", "why": "ChatGPT is signed out (codex login)"}]
    reason = presets.fills_reason(fills)
    assert reason.startswith("relay; research filled by chatgpt: ")
    assert presets.fills_of(reason) == [{k: f[k] for k in ("slot", "agent", "why")} for f in fills]
    assert presets.fills_reason([]) == "relay" and presets.fills_of("relay") == []


def test_a_preset_naming_an_agent_that_is_not_live_stays_listed():
    from tests.helpers import roster_with
    loaded = presets.load_presets(roster_with(grok=False), SENDERS, relay.CONTRACTS, roles=relay.ROLES,
                                  verdicts=relay.VERDICTS)
    assert list(loaded.presets) == list(LOADED.presets) and loaded.problems == {}


# ---------- intake through cmd_relay with a gate ----------

def _relay(preset, task, gate, *, worker=None, chatgpt=None, hook=None):
    conn, lines, clock, hook = log.init_db(":memory:"), [], Clock(), hook or RelayHook(s1=GOOD_NOTE)
    code = cli.cmd_relay(preset, task, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                         settings_paths=[], post=hook.post, worker=worker or Scripted("the build"),
                         chatgpt=chatgpt or Chat(GOOD_NOTE, "PASS"), codex_login=lambda: True, fetch=hook.fetch,
                         close=hook.close, sleep=clock.sleep, clock=clock, wait=True, available=gate, out=lines.append)
    rows = log.recent_tasks(conn)
    return code, lines, rows[0] if rows else None, hook


def test_research_build_without_grok_bot_researches_with_chatgpt_and_says_so():
    chat = Chat(GOOD_NOTE, "PASS")
    code, lines, row, hook = _relay("research-build", "what is the current stable python", Gate({"grok"}), chatgpt=chat)
    assert presets.slots_of(row) == {"research": "chatgpt", "build": "claude", "check": "chatgpt"}
    assert row["route_reason"] == f"relay; research filled by chatgpt: {WHY['grok']}"
    assert f"Slot research filled by chatgpt: {WHY['grok']}." in lines
    assert hook.sent == [] and (row["status"], row["check_state"]) == ("done", "passed")   # nothing went to the webhook


def test_vote_without_grok_bot_is_refused_before_any_row_naming_slot_c():
    code, lines, row, hook = _relay("vote", "one word: wood or rubber", Gate({"grok"}))
    assert code == 2 and row is None and hook.sent == []
    assert lines == [f"Refused: vote can't run now: slot c (Grok Bot): {WHY['grok']}; no other agent can vote there "
                     "(ChatGPT is in slot b; Claude is in slot a). Nothing was logged or sent."]
