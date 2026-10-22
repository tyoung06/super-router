"""Build brief 21, A0 (the brief's test plan line: prose output unchanged without --json). Each scenario in
tests/prose_scenarios.py prints exactly what main printed before brief 21, line for line, with the same exit code. The
fixture was recorded from main's code at 9bcde65, before any brief 21 change, by running this file with
SR_RECORD_PROSE=1. An intended change to the prose re-records only the scenario it touches, in the commit that makes
it, and says so. Every value here is fake."""
import json
import os
from pathlib import Path

import pytest

from tests import prose_scenarios

FIXTURE = Path(__file__).parent / "fixtures" / "prose_v13.json"
RECORD = os.environ.get("SR_RECORD_PROSE") == "1"


def _recorded():
    return json.loads(FIXTURE.read_text()) if FIXTURE.exists() else {}


@pytest.mark.parametrize("name", sorted(prose_scenarios.SCENARIOS))
def test_the_prose_is_what_main_printed_before_brief_21(name, monkeypatch, tmp_path):
    got = prose_scenarios.run(name, monkeypatch, tmp_path)
    if RECORD:
        doc = _recorded()
        doc[name] = got
        FIXTURE.write_text(json.dumps(dict(sorted(doc.items())), indent=1, ensure_ascii=False) + "\n")
        return
    assert got == _recorded()[name]


def test_every_recorded_scenario_still_runs():
    assert set(_recorded()) == set(prose_scenarios.SCENARIOS)


def test_no_prose_line_is_a_json_object():
    """The test plan's sweep (Phase 0, section 7): without --json no command prints a line that parses as a JSON object.
    Every scenario prints exactly its recorded lines (above), so checking the recording checks every run."""
    for name, got in _recorded().items():
        for line in got["lines"]:
            try:
                found = json.loads(line)
            except ValueError:
                continue
            assert not isinstance(found, dict), (name, line)
