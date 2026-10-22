"""Build brief 25, B4 (decision 8): README.md, the design chat's draft corrected to what the code does. Its links resolve
(docs/RULES.md is made at publish), it says it is tested on macOS and shared as is, and the facts it states are read from
the code, so the README and the router cannot drift apart: the billing switches, Jev's monthly cap, and the Python
version (the same in README, SETUP and CI)."""
import re
from pathlib import Path

from router import jev, safety

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text()
SETUP = (ROOT / "docs" / "SETUP.md").read_text()
MADE_AT_PUBLISH = {"docs/RULES.md"}
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


def test_every_link_resolves():
    targets = [t for t in LINK.findall(README) if not re.match(r"[a-z]+:", t)]
    assert targets and "docs/demo.png" in targets and "docs/SETUP.md" in targets and "docs/RULES.md" in targets
    assert [t for t in targets if t not in MADE_AT_PUBLISH and not (ROOT / t).exists()] == []


def test_it_says_macos_and_shared_as_is():
    assert "Tested on macOS only" in README and "A personal project, shared as is." in README


def test_the_billing_switches_are_the_routers():
    named = set(re.findall(r"`([A-Z][A-Z_]+)`", README.split("## What it costs")[1].split("##")[0]))
    assert named == set(safety.BILLED_AGENT) and "apiKeyHelper" in README


def test_jevs_cap_is_the_routers():
    assert f"{jev.MONTHLY_TOKEN_CAP:,} input tokens a month" in README


def test_readme_and_setup_name_the_same_python():
    for text in (README, SETUP):
        assert "Python 3.14" in text and "python3.14 -m venv .venv" in text
        assert "python3 -m venv .venv" not in text


def test_an_override_is_still_checked_and_the_page_asks_for_the_skill():
    assert "Jev still labels the task to pick who checks it" in README
    assert "the page asks for it before Send" in README
    assert "never goes to anyone else" not in README and "waits for your label" not in README
