"""routing.decide: who does a task and who checks it. Pure: plain data in, a decision out."""
import pytest

from router import routing
from tests.helpers import shipped_roster

ROSTER = shipped_roster()


def ok(skill, confidence=0.93):
    return {"status": "ok", "label": skill, "confidence": confidence, "needs_split": 0.1, "tokens": 764}


NOT_OK = [
    {"status": "below_floor", "label": "web_research", "confidence": 0.62, "tokens": 764},
    {"status": "none_of_these", "label": "none_of_these", "confidence": 0.91, "tokens": 764},
    {"status": "error", "error": "TypeSafeAuthenticationError", "tokens": 0},
    {"status": "over_cap"},
]

# The brief's table for the configs as shipped: action, doer, route_reason, checker, check_state.
# With claude, grok and chatgpt live (chatgpt since the owner's flag flip, 2026-10-13) and skill table v3.3
# (Muse deferred; read_media and make_media routed again by rules v2.10), plus recall from skill table v3.4 (2026-10-20):
SHIPPED = {
    "x_social_pulse": ("send", "grok", "best", "chatgpt", "pending"),
    "web_research": ("send", "chatgpt", "best", "claude", "pending"),
    "code": ("send", "claude", "best", "chatgpt", "pending"),
    "writing": ("send", "claude", "best", "chatgpt", "pending"),
    "planning": ("send", "claude", "best", "chatgpt", "pending"),
    "quick_answer": ("send", "claude", "best", None, "not_needed"),
    "recall": ("return", None, routing.NO_TAG_FOR_RECALL, None, None),  # untagged: nothing to recall from (rules v2.28, Jev)
    "meta_social_trends": ("send", "grok", "best", "chatgpt", "pending"),
    "bulk_text": ("send", "claude", "best", "grok", "pending"),
    "read_media": ("send", "claude", "best", "chatgpt", "pending"),
    "make_media": ("send", "grok", "best", "claude", "pending"),
    "computer_use": ("return", None, "returned: skill not routed in version 2", None, None),
}


def _shape(d):
    return d.action, d.agent, d.reason, d.checker, d.check_state


def test_the_table_covers_every_shipped_skill():
    assert set(SHIPPED) == set(ROSTER.skills) and len(SHIPPED) == 12


def test_a_tagged_recall_task_routes_to_claude_with_chatgpt_checking():
    d = routing.decide(ok("recall"), ROSTER, tagged=True)  # --project or --chat: the skill table as for any skill
    assert _shape(d) == ("send", "claude", "best", "chatgpt", "pending") and (d.skill, d.skill_source) == ("recall", "jev")


# ---------- no override ----------

@pytest.mark.parametrize("skill", SHIPPED)
def test_a_confident_jev_label_routes_by_the_shipped_table(skill):
    d = routing.decide(ok(skill), ROSTER)
    assert _shape(d) == SHIPPED[skill]
    assert (d.skill, d.skill_source) == (skill, "jev")


NOTES = {"x_social_pulse": None, "code": None, "writing": None, "planning": None, "web_research": None,
         "quick_answer": None, "meta_social_trends": None, "bulk_text": None, "read_media": None, "make_media": None,
         "recall": None}


@pytest.mark.parametrize("skill", NOTES)
def test_an_unchecked_result_carries_the_reason(skill):
    assert routing.decide(ok(skill), ROSTER).check_note == NOTES[skill]


@pytest.mark.parametrize("skill", SHIPPED)
def test_the_owners_answer_routes_by_the_same_table(skill):
    d = routing.decide(NOT_OK[0], ROSTER, answer=skill)
    assert _shape(d) == SHIPPED[skill]
    assert (d.skill, d.skill_source) == (skill, "owner")


@pytest.mark.parametrize("jev", NOT_OK, ids=lambda j: j["status"])
def test_without_a_confident_label_the_router_asks_the_owner(jev):
    assert routing.decide(jev, ROSTER).action == "ask"


@pytest.mark.parametrize("jev", NOT_OK, ids=lambda j: j["status"])
def test_with_no_terminal_the_task_comes_back(jev):
    d = routing.decide(jev, ROSTER, can_ask=False)
    assert (d.action, d.reason, d.agent, d.skill) == ("return", "returned: needs your label", None, None)


def test_answer_none_sends_the_task_back():
    d = routing.decide(NOT_OK[1], ROSTER, answer=routing.NONE_OF_THESE)
    assert (d.action, d.reason, d.skill, d.skill_source) == ("return", "returned: no skill", None, None)


def test_no_valid_answer_sends_the_task_back():
    d = routing.decide(NOT_OK[0], ROSTER, answer=routing.NO_ANSWER)
    assert (d.action, d.reason) == ("return", "returned: no valid answer")


def test_a_jev_label_that_is_not_in_the_table_is_treated_as_no_label():
    assert routing.decide(ok("teleport"), ROSTER).action == "ask"


def test_an_answer_that_is_not_a_skill_is_a_bug():
    with pytest.raises(ValueError):
        routing.decide(NOT_OK[0], ROSTER, answer="teleport")


# ---------- with an override ----------

def test_override_quick_answer_is_never_checked():
    d = routing.decide(ok("quick_answer"), ROSTER, override="grok")
    assert (d.action, d.agent, d.reason, d.skill, d.skill_source) == ("send", "grok", "override", "quick_answer", "jev")
    assert (d.checker, d.check_state, d.check_note) == (None, "not_needed", None)


@pytest.mark.parametrize("skill, agent, checker, state", [
    ("code", "grok", "chatgpt", "pending"),              # the skill's second checks
    ("x_social_pulse", "claude", "chatgpt", "pending"),
    ("web_research", "claude", "chatgpt", "pending"),    # claude is web_research's second, so its best checks
    ("bulk_text", "grok", "claude", "pending"),          # grok is bulk_text's second, so its best checks
    ("bulk_text", "claude", "grok", "pending"),          # claude is bulk_text's best, so its second checks
    ("meta_social_trends", "chatgpt", "grok", "pending"),  # chatgpt is the second, so the best checks
    ("meta_social_trends", "claude", "chatgpt", "pending"),
    ("read_media", "grok", "chatgpt", "pending"),        # grok is neither, so the second checks (files never reach grok: intake refuses @grok with files)
    ("make_media", "claude", "grok", "pending"),         # claude is make_media's second, so the best checks
    ("make_media", "chatgpt", "claude", "pending"),
])
def test_override_on_a_routed_skill_picks_the_checker(skill, agent, checker, state):
    d = routing.decide(ok(skill), ROSTER, override=agent)
    assert (d.action, d.agent, d.reason, d.skill) == ("send", agent, "override", skill)
    assert (d.checker, d.check_state) == (checker, state)
    assert d.check_note == (None if state == "pending" else f"checker {checker} isn't live yet")


@pytest.mark.parametrize("skill", ["computer_use"])
def test_override_on_a_skill_not_routed_in_version_2(skill):
    d = routing.decide(ok(skill), ROSTER, override="claude")
    assert (d.action, d.agent, d.skill, d.checker, d.check_state) == ("send", "claude", skill, None, "unchecked")
    assert d.check_note == "skill not routed in version 2"


@pytest.mark.parametrize("jev", NOT_OK, ids=lambda j: j["status"])
def test_override_without_a_confident_label_still_runs_and_never_asks(jev):
    d = routing.decide(jev, ROSTER, override="grok")
    assert (d.action, d.agent, d.reason) == ("send", "grok", "override")
    assert (d.skill, d.skill_source, d.checker, d.check_state) == (None, None, None, "unchecked")
    assert d.check_note == "override with no usable label"


def test_override_with_a_label_not_in_the_table():
    d = routing.decide(ok("teleport"), ROSTER, override="claude")
    assert (d.action, d.skill, d.checker, d.check_state) == ("send", None, None, "unchecked")


# ---------- rules that hold everywhere ----------

def test_no_agent_ever_checks_its_own_work():
    for skill in ROSTER.skills:
        for override in (None, *ROSTER.live):
            d = routing.decide(ok(skill), ROSTER, override=override)
            assert d.checker is None or d.checker != d.agent, (skill, override)


def test_only_live_agents_ever_do_the_work():
    for skill in ROSTER.skills:
        d = routing.decide(ok(skill), ROSTER)
        assert d.agent is None or d.agent in ROSTER.live


# ---------- files never go to Grok (rules v2.10, Media) ----------

@pytest.mark.parametrize("skill", ["x_social_pulse", "meta_social_trends", "make_media"])
def test_a_task_with_files_whose_doer_is_grok_comes_back(skill):
    d = routing.decide(ok(skill), ROSTER, files=True)
    assert (d.action, d.agent, d.skill, d.skill_source, d.reason) == ("return", None, skill, "jev", routing.NO_FILES_FOR_GROK)
    assert routing.decide(ok(skill), ROSTER, files=False).action == "send"


@pytest.mark.parametrize("skill", ["read_media", "code", "web_research", "bulk_text", "quick_answer"])
def test_a_task_with_files_whose_doer_is_claude_or_chatgpt_still_runs(skill):
    d = routing.decide(ok(skill), ROSTER, files=True)
    assert d.action == "send" and d.agent in ("claude", "chatgpt")


def test_an_override_to_grok_with_files_comes_back_too():
    # intake refuses @grok with files before this; the rule holds here as well
    d = routing.decide(ok("read_media"), ROSTER, override="grok", files=True)
    assert (d.action, d.reason) == ("return", routing.NO_FILES_FOR_GROK)
