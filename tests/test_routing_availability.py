"""Build brief 24, B1 (decisions 3, 4 and 5): who does a routed task and who checks it, with availability.

The doer is the skill's best agent, then interim (when set), then second place, then Claude: the first available; any
other than the best is a stand-in, named on the row with why. `make_media` is Grok's alone: without Grok Bot it comes
back. The checker is the skill's second agent, then Claude, then ChatGPT: never the doer, never Cursor, Grok only on
`bulk_text`; with nobody left the result is unchecked, with why. A quick answer is never checked. An override of an
agent that isn't available is refused at intake. A task with files never goes to Grok or Cursor. Pure where it can be;
the intake cases through cmd_route with a fake gate. Fakes only."""
import itertools

import pytest

from router import __main__ as cli
from router import availability, log, online, routing
from tests.helpers import fake_label, shipped_roster
from tests.test_cli import CONFIG, Recorder, _Reply

ROSTER = shipped_roster()
WHY = {"chatgpt": "ChatGPT is signed out (codex login)", "grok": "Grok Bot isn't set up: no inbox repo in settings",
       "cursor": "Cursor is signed out (agent login)"}
CODE = {"chatgpt": "signed_out", "grok": "not_configured", "cursor": "signed_out"}


def _table(out):
    return {a: (availability.Availability(False, WHY[a], CODE[a]) if a in out else availability.YES)
            for a in ("claude", "chatgpt", "grok", "cursor", "muse")}


def jev(label):
    return {"status": "ok", "label": label, "confidence": 0.95, "needs_split": 0.1, "tokens": 0}


def _stand(best):
    return f"stand-in for {best}: {WHY[best]}"


def _unchecked(agent):
    return f"no other agent available to check ({WHY[agent]})"


# (doer, route_reason, checker, check_state, check_note) per skill, for each set of {ChatGPT, Grok Bot} unavailable.
# Cursor is in no skill's best or second, so it changes nothing: every row below must hold with Cursor out too.
SEND = "send"
EXPECTED = {
    (): {
        "x_social_pulse": ("grok", "best", "chatgpt", "pending", None),
        "meta_social_trends": ("grok", "best", "chatgpt", "pending", None),
        "read_media": ("claude", "best", "chatgpt", "pending", None),
        "web_research": ("chatgpt", "best", "claude", "pending", None),
        "code": ("claude", "best", "chatgpt", "pending", None),
        "writing": ("claude", "best", "chatgpt", "pending", None),
        "planning": ("claude", "best", "chatgpt", "pending", None),
        "make_media": ("grok", "best", "claude", "pending", None),
        "bulk_text": ("claude", "best", "grok", "pending", None),
        "quick_answer": ("claude", "best", None, "not_needed", None),
        "recall": ("claude", "best", "chatgpt", "pending", None),
    },
    ("grok",): {
        "x_social_pulse": "returned: x_social_pulse needs Grok Bot: Grok Bot isn't set up: no inbox repo in settings",  # Grok Bot's alone (the owner, 21 Oct)
        "meta_social_trends": ("chatgpt", _stand("grok"), "claude", "pending", None),
        "read_media": ("claude", "best", "chatgpt", "pending", None),
        "web_research": ("chatgpt", "best", "claude", "pending", None),
        "code": ("claude", "best", "chatgpt", "pending", None),
        "writing": ("claude", "best", "chatgpt", "pending", None),
        "planning": ("claude", "best", "chatgpt", "pending", None),
        "make_media": "returned: make_media needs Grok Bot: Grok Bot isn't set up: no inbox repo in settings",
        "bulk_text": ("claude", "best", "chatgpt", "pending", None),
        "quick_answer": ("claude", "best", None, "not_needed", None),
        "recall": ("claude", "best", "chatgpt", "pending", None),
    },
    ("chatgpt",): {
        "x_social_pulse": ("grok", "best", "claude", "pending", None),
        "meta_social_trends": ("grok", "best", "claude", "pending", None),
        "read_media": ("claude", "best", None, "unchecked", _unchecked("chatgpt")),
        "web_research": ("claude", _stand("chatgpt"), None, "unchecked", _unchecked("chatgpt")),
        "code": ("claude", "best", None, "unchecked", _unchecked("chatgpt")),
        "writing": ("claude", "best", None, "unchecked", _unchecked("chatgpt")),
        "planning": ("claude", "best", None, "unchecked", _unchecked("chatgpt")),
        "make_media": ("grok", "best", "claude", "pending", None),
        "bulk_text": ("claude", "best", "grok", "pending", None),
        "quick_answer": ("claude", "best", None, "not_needed", None),
        "recall": ("claude", "best", None, "unchecked", _unchecked("chatgpt")),
    },
    ("chatgpt", "grok"): {
        "x_social_pulse": "returned: x_social_pulse needs Grok Bot: Grok Bot isn't set up: no inbox repo in settings",
        "meta_social_trends": ("claude", _stand("grok"), None, "unchecked", _unchecked("chatgpt")),
        "read_media": ("claude", "best", None, "unchecked", _unchecked("chatgpt")),
        "web_research": ("claude", _stand("chatgpt"), None, "unchecked", _unchecked("chatgpt")),
        "code": ("claude", "best", None, "unchecked", _unchecked("chatgpt")),
        "writing": ("claude", "best", None, "unchecked", _unchecked("chatgpt")),
        "planning": ("claude", "best", None, "unchecked", _unchecked("chatgpt")),
        "make_media": "returned: make_media needs Grok Bot: Grok Bot isn't set up: no inbox repo in settings",
        "bulk_text": ("claude", "best", None, "unchecked", _unchecked("grok")),
        "quick_answer": ("claude", "best", None, "not_needed", None),
        "recall": ("claude", "best", None, "unchecked", _unchecked("chatgpt")),
    },
}
SETS = [frozenset(c) for r in range(4) for c in itertools.combinations(("chatgpt", "grok", "cursor"), r)]


@pytest.mark.parametrize("skill", list(ROSTER.skills))
@pytest.mark.parametrize("out", SETS, ids=lambda s: "+".join(sorted(s)) or "none")
def test_every_skill_with_every_set_of_agents_out(skill, out):
    decision = routing.decide(jev(skill), ROSTER, tagged=True, available=_table(out))
    if skill == "computer_use":  # not routed in version 2, whoever is up
        assert (decision.action, decision.code) == ("return", "not_routed")
        return
    want = EXPECTED[tuple(sorted(out - {"cursor"}))][skill]
    if isinstance(want, str):
        assert (decision.action, decision.reason, decision.code) == ("return", want, "unavailable")
        return
    got = (decision.agent, decision.reason, decision.checker, decision.check_state, decision.check_note)
    assert decision.action == SEND and got == want


def test_the_table_covers_every_skill_in_the_shipped_skill_table():
    assert set(EXPECTED[()]) | {"computer_use"} == set(ROSTER.skills)


def test_a_stand_in_record_reads_back_who_for_whom_and_why():
    decision = routing.decide(jev("meta_social_trends"), ROSTER, available=_table({"grok"}))
    assert routing.stand_in_of(decision.reason) == ("grok", WHY["grok"])
    assert routing.stand_in_of("best") is None and routing.stand_in_of("override") is None


def test_an_interim_is_tried_before_second_place(monkeypatch):
    table = {k: dict(v) for k, v in ROSTER.skills.items()}
    table["web_research"]["interim"] = "grok"
    roster = type(ROSTER)(agents=ROSTER.agents, not_routed=ROSTER.not_routed, table={**ROSTER.table, "skills": table})
    decision = routing.decide(jev("web_research"), roster, available=_table({"chatgpt"}))
    assert (decision.agent, decision.reason) == ("grok", _stand("chatgpt"))


def test_a_file_task_never_goes_to_grok_or_cursor():
    decision = routing.decide(jev("x_social_pulse"), ROSTER, files=True, available=_table(()))
    assert (decision.action, decision.code) == ("return", "files_to_agent")          # Grok would do it: comes back
    decision = routing.decide(jev("meta_social_trends"), ROSTER, files=True, available=_table({"grok"}))
    assert (decision.action, decision.agent) == ("send", "chatgpt")                    # ChatGPT stands in: it may read files


def test_an_overrides_checker_is_todays_pick_when_available_else_decision_4():
    decision = routing.decide(jev("x_social_pulse"), ROSTER, override="chatgpt", available=_table(()))
    assert (decision.agent, decision.checker) == ("chatgpt", "grok")                  # today's pick: the best checks
    decision = routing.decide(jev("x_social_pulse"), ROSTER, override="chatgpt", available=_table({"grok"}))
    assert (decision.agent, decision.checker) == ("chatgpt", "claude")                # else decision 4's order
    decision = routing.decide(jev("writing"), ROSTER, override="claude", available=_table({"chatgpt"}))
    assert (decision.checker, decision.check_note) == (None, _unchecked("chatgpt"))


def test_with_no_table_handed_a_live_agent_is_available():
    assert routing.decide(jev("x_social_pulse"), ROSTER).agent == "grok"


# ---------- intake through cmd_route with a gate ----------

class Gate:
    """A command's gate (router/availability.py) answering from a table, recording what it was asked."""

    def __init__(self, out=()):
        self.table, self.asked = _table(set(out)), []

    def of(self, names, fresh=False):
        self.asked.extend(names)
        return {n: self.table[n] for n in names}

    def __call__(self, name, fresh=False):
        return self.of([name])[name]


def _route(task, label, gate, *, worker=None):
    conn, lines = log.init_db(":memory:"), []
    code = cli.cmd_route(task, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=fake_label(label), post=Recorder(_Reply(200, {"success": True, "runUuid": "uuid-1"})),
                         worker=worker or Recorder("an answer"), chatgpt=lambda *a, **k: "PASS", codex_login=lambda: True,
                         available=gate, out=lines.append)
    rows = log.recent_tasks(conn)
    return code, lines, rows[0] if rows else None


@pytest.mark.parametrize("tag", ["grok", "chatgpt"])
def test_an_override_of_an_agent_that_is_not_available_is_refused_before_any_row(tag):
    code, lines, row = _route(f"@{tag} what is new on X about trays", jev("x_social_pulse"), Gate({tag}))
    assert code == 2 and row is None
    assert lines == [f"Refused: @{tag} can't be used: {WHY[tag]}. An override never goes to another agent. "
                     "Nothing was logged or sent."]


def test_make_media_without_grok_bot_comes_back_after_jevs_row_and_before_any_call():
    worker = Recorder("never")
    code, lines, row = _route("make an image of a red tray", jev("make_media"), Gate({"grok"}), worker=worker)
    assert code == 4 and worker.calls == [] and (row["status"], row["reason_code"]) == ("returned", "unavailable")
    assert row["route_reason"] == "returned: make_media needs Grok Bot: Grok Bot isn't set up: no inbox repo in settings"
    assert lines[0].endswith("came back to you: make_media needs Grok Bot: Grok Bot isn't set up: no inbox repo in settings.")


def test_the_route_line_names_the_stand_in_and_why():
    code, lines, row = _route("what is new on Instagram about trays", jev("meta_social_trends"), Gate({"grok"}))
    assert lines[0] == (f"{row['task_id']}: meta_social_trends (Jev, confidence 0.95) -> chatgpt, standing in for grok "
                        f"({WHY['grok']}).")


def test_only_the_skills_candidates_are_checked_never_cursor():
    gate = Gate()
    _route("write two lines about trays", jev("writing"), gate)
    assert "cursor" not in gate.asked and set(gate.asked) <= {"claude", "chatgpt"}
