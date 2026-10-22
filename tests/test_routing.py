"""Override tags. The tag names come from config/agents.json."""
from router import routing

ALL = ("claude", "grok", "chatgpt", "muse")


def test_routing_override_needs_space_or_end_after_tag():
    assert routing.parse_override("@grokking is fun", ALL) == (None, "@grokking is fun")


def test_routing_override_any_case():
    assert routing.parse_override("@Grok what is trending", ALL) == ("grok", "what is trending")
    assert routing.parse_override("@CLAUDE explain venvs", ALL) == ("claude", "explain venvs")


def test_routing_bare_tag_strips_to_empty():
    assert routing.parse_override("@grok", ALL) == ("grok", "")
    assert routing.parse_override("@grok   ", ALL) == ("grok", "")
