"""Cleanup 1 (2.3): Haiku is Claude Code's side job, so it never reads as the model that answered while another model is
in the stream's `modelUsage`. `models_used` keeps the full list. The key order of `modelUsage` isn't meaningful [GUESS: no
two-model row survives on `main`'s log; D for 33.4 saw them on a scratch log]. No model call."""
import pytest

from router import models

OPUS, FABLE, HAIKU, SONNET = "claude-opus-5-5", "claude-fable-5-1", "claude-haiku-5-5", "claude-sonnet-5-5"


def _events(*used, init=None):
    return [{"type": "system", "subtype": "init", "model": init or used[0]},
            {"type": "result", "modelUsage": {name: {"outputTokens": 1} for name in used}}]


def _record(asked, *used, init=None):
    return models.claude_served(_events(*used, init=init), models.Choice("claude", asked, timeout=600))


@pytest.mark.parametrize("used", [(OPUS, HAIKU), (HAIKU, OPUS)])
def test_haiku_beside_the_model_asked_for_gives_no_note_and_the_list_stays_whole(used):
    record = _record(OPUS, *used, init=OPUS)
    assert record["model"] == OPUS and record["differs"] is False and record["models_used"] == list(used)


@pytest.mark.parametrize("used", [(FABLE, OPUS), (FABLE, HAIKU, OPUS), (HAIKU, FABLE, OPUS)])
def test_a_real_rerun_still_reads_as_one(used):
    record = _record(FABLE, *used, init=FABLE)
    assert record["model"] == OPUS and record["differs"] is True


def test_haiku_alone_is_real_and_still_gives_a_note():
    record = _record(OPUS, HAIKU, init=OPUS)
    assert record["model"] == HAIKU and record["differs"] is True


def test_haiku_asked_for_and_alone_gives_no_note():
    record = _record(HAIKU, HAIKU)
    assert record["model"] == HAIKU and record["differs"] is False


def test_no_model_usage_falls_back_to_init():
    events = [{"type": "system", "subtype": "init", "model": SONNET}, {"type": "result"}]
    record = models.claude_served(events, models.Choice("claude", SONNET, timeout=600))
    assert record["model"] == SONNET and record["models_used"] == [] and record["differs"] is False


def test_the_cards_note_reads_the_same_way():
    import json

    def note(record):
        return models.differs_note({"agent": "claude", "served": json.dumps(record), "model": record["asked"]})
    assert note(_record(OPUS, OPUS, HAIKU, init=OPUS)) is None
    assert note(_record(FABLE, FABLE, OPUS, init=FABLE)) == "Fable 5.1 re-ran this on Opus 5.5"
    assert note(_record(OPUS, HAIKU, init=OPUS)) == "Opus 5.5 re-ran this on Haiku 5.5"
