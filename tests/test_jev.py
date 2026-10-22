"""router/jev.py with fake clients. No network, no real key: every key here is fake."""
from types import SimpleNamespace

import pytest
import typesafe_sdk
from typesafe_sdk import (TypeSafeAPIConnectionError, TypeSafeAPITimeoutError, TypeSafeAuthenticationError,
                          TypeSafeError, TypeSafeRateLimitError)

from router import jev
from tests.helpers import shipped_roster

ROSTER = shipped_roster()
TABLE = ROSTER.table
KEY = "FAKE-JEV-KEY-12345"


class FakeClient:
    """Stands in for TypeSafeClient. Records each call; returns one answer or raises."""

    def __init__(self, choice="code", confidence=0.93, noul=0.2, tokens=764, raises=None):
        self.answer = (choice, confidence, noul, tokens)
        self.raises, self.calls, self.closed = raises, [], False

    def system_one(self, state, questions, model=None):
        self.calls.append({"state": state, "questions": questions, "model": model})
        if self.raises:
            raise self.raises
        choice, confidence, noul, tokens = self.answer
        return SimpleNamespace(
            answers={"skill": SimpleNamespace(choice=choice, confidence=confidence, probabilities={choice: confidence}),
                     "needs_split": SimpleNamespace(noul=noul)},
            usage=SimpleNamespace(input_tokens=tokens),
        )

    def close(self):
        self.closed = True


def _label(client=None, *, task="Fix the bug in my script.", task_id="sr-20261008-120000-abcd", key=KEY, month=0):
    client = client or FakeClient()
    made = []

    def make_client(api_key):
        made.append(api_key)
        return client

    result = jev.label(task, task_id=task_id, roster=ROSTER, api_key=key, tokens_this_month=month,
                       make_client=make_client)
    return result, client, made


# ---------- what Jev is sent ----------

def test_jev_is_sent_only_the_task_text_two_questions_and_the_pinned_model():
    _, client, made = _label()
    (call,) = client.calls
    assert call["state"] == "Fix the bug in my script."
    assert set(call["questions"]) == {"skill", "needs_split"}
    assert call["model"] == "jev-1.13.0" == TABLE["labeler"]["jev_model"]
    assert made == [KEY] and client.closed


def test_the_two_questions_come_from_the_labeler_block():
    _, client, _ = _label()
    questions = client.calls[0]["questions"]
    assert questions["skill"].instructions == TABLE["labeler"]["question"]
    assert questions["needs_split"].instructions == TABLE["labeler"]["second_question"]["instructions"]


def test_the_options_are_every_skill_plus_none_of_these():
    _, client, _ = _label()
    criteria = client.calls[0]["questions"]["skill"].criteria
    assert set(criteria) == set(TABLE["skills"]) | {"none_of_these"}
    for key, skill in TABLE["skills"].items():
        if skill.get("not_for"):
            assert criteria[key] == {"what": skill["description"], "not_for": skill["not_for"]}
        else:
            assert criteria[key] == skill["description"]
    assert criteria["none_of_these"] == TABLE["labeler"]["fallback_description"]


def test_the_option_order_is_shuffled_by_task_id_and_can_be_rebuilt():
    orders = {tuple(jev.build_criteria(TABLE, f"sr-20261008-12000{i}-abcd")) for i in range(5)}
    assert len(orders) > 1
    first, again = FakeClient(), FakeClient()
    _label(first, task_id="sr-a")
    _label(again, task_id="sr-a")
    order = list(first.calls[0]["questions"]["skill"].criteria)
    assert order == list(again.calls[0]["questions"]["skill"].criteria)
    assert order == list(jev.build_criteria(TABLE, "sr-a"))


def test_the_client_is_pinned_to_the_default_address_with_no_retries(monkeypatch):
    seen = {}

    class Recorder:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(jev, "TypeSafeClient", Recorder)
    jev.make_client(KEY)
    assert seen["api_key"] == KEY
    assert seen["base_url"] == jev.BASE_URL == typesafe_sdk.constants.DEFAULT_BASE_URL == "https://api.typesafe.ai"
    assert seen["retry"].max_retries == 0


def test_a_base_url_or_key_in_the_shell_cannot_override_the_explicit_ones(monkeypatch):
    # The SDK's own settings resolver: explicit values win over the environment.
    from typesafe_sdk._core.config import Config
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://evil.invalid")
    monkeypatch.setenv("TYPESAFE_API_KEY", "FAKE-SHELL-KEY")
    resolved = Config.resolve(KEY, jev.BASE_URL, None, None, None)
    assert resolved.base_url == "https://api.typesafe.ai" and resolved.api_key == KEY


# ---------- how jev_status is set, first match wins ----------

def test_a_confident_label_is_ok():
    result, _, _ = _label(FakeClient(choice="code", confidence=0.93, noul=0.2, tokens=764))
    assert result == {"status": "ok", "label": "code", "confidence": 0.93, "needs_split": 0.2, "tokens": 764}


def test_the_floor_itself_is_ok_and_just_under_it_is_below_floor():
    assert _label(FakeClient(confidence=0.8))[0]["status"] == "ok"
    below = _label(FakeClient(choice="web_research", confidence=0.79))[0]
    assert (below["status"], below["label"], below["confidence"]) == ("below_floor", "web_research", 0.79)


def test_none_of_these_is_its_own_status_unless_it_is_below_the_floor():
    assert _label(FakeClient(choice="none_of_these", confidence=0.95))[0]["status"] == "none_of_these"
    assert _label(FakeClient(choice="none_of_these", confidence=0.5))[0]["status"] == "below_floor"


@pytest.mark.parametrize("month", [1_000_000, 1_500_000])
def test_at_or_past_the_monthly_cap_jev_is_not_called(month):
    result, client, made = _label(month=month)
    assert result == {"status": "over_cap"}
    assert client.calls == [] and made == []
    assert jev.MONTHLY_TOKEN_CAP == 1_000_000


def test_just_under_the_cap_jev_is_called():
    result, client, _ = _label(month=999_999)
    assert result["status"] == "ok" and len(client.calls) == 1


@pytest.mark.parametrize("error", [
    TypeSafeAuthenticationError(401, {"detail": "key FAKE-JEV-KEY-12345 rejected"}, {}),
    TypeSafeRateLimitError(429, {"detail": "slow down, see https://api.typesafe.ai/x"}, {}),
    TypeSafeAPITimeoutError(10.0),
    TypeSafeAPIConnectionError("Connection error: could not reach https://api.typesafe.ai"),
    TypeSafeError("something odd with FAKE-JEV-KEY-12345"),
    ValueError("unexpected FAKE-JEV-KEY-12345"),
])
def test_any_error_is_stored_as_its_type_name_only(error):
    result, client, _ = _label(FakeClient(raises=error))
    assert result == {"status": "error", "error": type(error).__name__, "tokens": 0}
    assert client.closed
    shown = repr(result)
    for text in ("FAKE-JEV-KEY", "rejected", "slow down", "typesafe.ai", "odd", "unexpected"):
        assert text not in shown


@pytest.mark.parametrize("key", [None, "", "   "])
def test_a_missing_key_is_not_set_up_and_no_client_is_built(key):
    # brief 24 (decision 13): no JEV_API_KEY is "Jev isn't set up" (was an `error` with `KeyMissing`); Jev isn't called
    result, client, made = _label(key=key)
    assert result == {"status": "not_set_up", "tokens": 0}
    assert made == [] and client.calls == []


def test_a_label_that_is_not_in_the_table_is_an_error_but_keeps_its_tokens():
    result, _, _ = _label(FakeClient(choice="teleport", confidence=0.99, tokens=700))
    assert result == {"status": "error", "error": "UnknownLabel", "tokens": 700}
