"""Presets (rules v2.12, Relay): `config/presets.json` is read and checked at startup. A preset
that names an agent that is not live, a checker equal to its last stage's agent, more than 4
stages, or a contract the code doesn't have is marked bad with the reason; `sr relay --list`
prints every preset. Every value here is fake except the shipped file."""
import json

import pytest

from router import __main__ as cli
from router import log, presets, relay
from tests.helpers import SHIPPED_PRESET_VERSIONS, roster_with, shipped_presets_doc, shipped_presets_text, shipped_roster

SENDERS = tuple(cli.SENDERS)
GOOD = {
    "version": "1.0",
    "presets": {
        "research-build": {
            "stages": [
                {"n": 1, "agent": "grok", "role": "research", "contract": "research_note"},
                {"n": 2, "agent": "claude", "role": "build", "contract": None},
            ],
            "checker": "chatgpt",
        }
    },
}


# Build brief 6, section 7: the collab entry, exactly.
COLLAB = {
    "stages": [
        {"n": 1, "agent": "claude", "role": "plan", "contract": "plan"},
        {"n": 2, "agent": "chatgpt", "role": "amend", "contract": "amended_plan"},
        {"n": 3, "agent": "claude", "role": "execute", "contract": "deliverable"},
        {"n": 4, "agent": "chatgpt", "role": "edit", "contract": "edit_check", "is_check": True},
    ],
    "checker": None,
}
# research-build's entry as config/presets.json 1.0 had it, byte for byte (brief 6: unchanged).
RESEARCH_BUILD_TEXT = """    "research-build": {
      "stages": [
        {"n": 1, "agent": "grok",   "role": "research", "contract": "research_note"},
        {"n": 2, "agent": "claude", "role": "build",    "contract": null}
      ],
      "checker": "chatgpt"
    }"""


def _load(doc, tmp_path, roster=None):
    path = tmp_path / "presets.json"
    path.write_text(json.dumps(doc))
    return presets.load_presets(roster or shipped_roster(), SENDERS, relay.CONTRACTS, path=path,
                                verdicts=relay.VERDICTS)


def _problems(preset, roster=None):
    return presets.problems("p", preset, roster or shipped_roster(), SENDERS, relay.CONTRACTS, verdicts=relay.VERDICTS)


def _collab():
    return json.loads(json.dumps(COLLAB))


# ---------- the shipped file ----------

def test_the_shipped_file_is_version_1_3_with_research_build_collab_and_versus():
    # Brief 6: version 1.1, collab added; research-build as it was. Brief 9: 1.2, versus added
    # (tests/test_versus_presets.py checks its entry).
    loaded = presets.load_presets(shipped_roster(), SENDERS, relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
    assert loaded.version in SHIPPED_PRESET_VERSIONS and loaded.names == ("research-build", "collab", "versus", "redteam", "vote") \
        and loaded.problems == {}  # brief 16: 1.4, redteam; 17: 1.5, vote (tests/test_vote_presets.py checks its entry)
    preset = loaded.presets["research-build"]
    assert [(s.n, s.agent, s.role, s.contract) for s in preset.stages] == [
        (1, "grok", "research", "research_note"), (2, "claude", "build", None)]
    assert preset.checker == "chatgpt" and preset.last_agent == "claude" and preset.check_stage is None
    collab = loaded.presets["collab"]
    assert [(s.n, s.agent, s.role, s.contract, s.is_check) for s in collab.stages] == [
        (1, "claude", "plan", "plan", False), (2, "chatgpt", "amend", "amended_plan", False),
        (3, "claude", "execute", "deliverable", False), (4, "chatgpt", "edit", "edit_check", True)]
    assert collab.checker is None and collab.check_stage is collab.stages[3] and collab.last_agent == "chatgpt"


def test_the_shipped_file_is_exactly_what_the_brief_specifies():
    doc = shipped_presets_doc()  # brief 21: 1.6's descriptions out
    from tests.test_versus_presets import VERSUS  # brief 9
    # brief 15: 1.3, each preset gains its slots map (rules v2.21) and nothing else changes
    doc["presets"].pop("redteam")  # brief 16 (tests/test_redteam_presets.py checks it)
    doc["presets"].pop("vote")  # brief 17 (tests/test_vote_presets.py checks it)
    slots = {name: doc["presets"][name].pop("slots") for name in doc["presets"]}
    assert slots == {"research-build": {"research": [1], "build": [2], "check": ["checker"]},
                     "collab": {"lead": [1, 3], "partner": [2, 4]}, "versus": {"a": [1, 4], "b": [2, 3]}}
    assert doc == {"version": "1.5", "presets": {"research-build": GOOD["presets"]["research-build"], "collab": COLLAB,
                                                 "versus": VERSUS}}


def test_research_builds_entry_is_unchanged_byte_for_byte():
    # brief 15: its stages and checker byte for byte; the checker line now ends with a comma, then the slots
    stages_and_checker = RESEARCH_BUILD_TEXT.removesuffix('\n    }')
    assert stages_and_checker + ',\n      "slots": {"research": [1], "build": [2], "check": ["checker"]}\n    }' \
        in shipped_presets_text()  # brief 21: 1.6's description lines out


def test_the_file_versions_read_are_1_0_to_1_3():
    assert presets.FILE_VERSIONS == ("1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6")  # brief 9: 1.2, 15: 1.3, 16: 1.4, 17: 1.5, 21: 1.6


# ---------- the validator, one rule at a time ----------

def test_a_good_preset_has_no_problems():
    assert _problems(GOOD["presets"]["research-build"]) == []


def test_more_than_four_stages_is_refused():
    stages = [{"n": i, "agent": "claude" if i % 2 else "grok", "role": "r", "contract": "research_note"} for i in range(1, 6)]
    stages[-1]["contract"] = None
    found = _problems({"stages": stages, "checker": "chatgpt"})
    assert any("5 stages" in p and "at most 4" in p for p in found)


def test_exactly_four_stages_is_allowed():
    stages = [{"n": i, "agent": "claude" if i % 2 else "grok", "role": "r", "contract": "research_note"} for i in range(1, 5)]
    stages[-1]["contract"] = None
    assert _problems({"stages": stages, "checker": "chatgpt"}) == []


def test_an_agent_that_is_not_live_no_longer_makes_a_preset_bad_but_one_with_no_sender_does():
    # brief 24 (decision 8): the live check left the loader (intake fills the slot); Muse has no sender in code
    preset = json.loads(json.dumps(GOOD["presets"]["research-build"]))
    assert _problems(preset, roster_with(grok=False)) == []
    preset["stages"][0]["agent"] = "muse"
    assert any("muse" in p and "no way to send" in p for p in _problems(preset))


def test_an_agent_the_config_does_not_have_is_refused():
    preset = json.loads(json.dumps(GOOD["presets"]["research-build"]))
    preset["stages"][0]["agent"] = "gemini"
    assert any("gemini" in p and "agents.json" in p for p in _problems(preset))


def test_a_live_agent_with_no_sender_in_code_is_refused():
    preset = GOOD["presets"]["research-build"]
    found = presets.problems("p", preset, shipped_roster(), ("claude", "chatgpt"), relay.CONTRACTS)
    assert any("grok" in p and "no way to send" in p for p in found)


def test_the_checker_may_not_be_the_last_stages_agent():
    preset = json.loads(json.dumps(GOOD["presets"]["research-build"]))
    preset["checker"] = "claude"
    assert any("claude" in p and "last stage" in p for p in _problems(preset))


def test_the_checker_must_be_sendable_and_present():
    preset = json.loads(json.dumps(GOOD["presets"]["research-build"]))
    assert _problems(preset, roster_with(chatgpt=False)) == []          # brief 24: a checker not live is filled at intake
    preset["checker"] = "muse"
    assert any("muse" in p and "no way to send" in p for p in _problems(preset))
    del preset["checker"]
    assert any("no checker" in p for p in _problems(preset))


def test_stage_numbers_must_run_1_to_n():
    preset = json.loads(json.dumps(GOOD["presets"]["research-build"]))
    preset["stages"][1]["n"] = 3
    assert any("1..n" in p or "run 1" in p for p in _problems(preset))


def test_a_contract_the_code_does_not_have_is_refused():
    preset = json.loads(json.dumps(GOOD["presets"]["research-build"]))
    preset["stages"][0]["contract"] = "poem"
    assert any("poem" in p and "contract" in p for p in _problems(preset))


def test_every_stage_but_the_last_needs_a_contract_and_the_last_has_none():
    preset = json.loads(json.dumps(GOOD["presets"]["research-build"]))
    preset["stages"][0]["contract"] = None
    assert any("stage 1" in p and "no contract" in p for p in _problems(preset))
    preset = json.loads(json.dumps(GOOD["presets"]["research-build"]))
    preset["stages"][1]["contract"] = "research_note"
    assert any("stage 2" in p and "last" in p for p in _problems(preset))


def test_an_unknown_stage_field_or_a_bad_role_is_refused():
    preset = json.loads(json.dumps(GOOD["presets"]["research-build"]))
    preset["stages"][0]["files"] = True
    assert any("files" in p and "unknown" in p for p in _problems(preset))
    preset = json.loads(json.dumps(GOOD["presets"]["research-build"]))
    preset["stages"][0]["role"] = "Re search"
    assert any("role" in p for p in _problems(preset))


def test_no_stages_is_one_problem():
    assert len(_problems({"stages": [], "checker": "chatgpt"})) == 1
    assert len(_problems({"checker": "chatgpt"})) == 1


# ---------- the file ----------

def test_a_bad_preset_is_marked_bad_and_the_good_ones_still_load(tmp_path):
    doc = json.loads(json.dumps(GOOD))
    doc["presets"]["too-long"] = {"stages": [{"n": i, "agent": "claude", "role": "r", "contract": "research_note"}
                                             for i in range(1, 6)], "checker": "grok"}
    loaded = _load(doc, tmp_path)
    assert loaded.names == ("research-build", "too-long")
    assert "research-build" in loaded.presets and "too-long" not in loaded.presets
    assert any("at most 4" in p for p in loaded.problems["too-long"])


def test_a_bad_preset_name_is_a_problem(tmp_path):
    doc = json.loads(json.dumps(GOOD))
    doc["presets"]["Research Build"] = doc["presets"].pop("research-build")
    loaded = _load(doc, tmp_path)
    assert any("name" in p for p in loaded.problems["Research Build"])


@pytest.mark.parametrize("doc, words", [
    ("not json", "not valid JSON"),
    ({"presets": GOOD["presets"]}, "version"),
    ({"version": "2.0", "presets": GOOD["presets"]}, "version"),
    ({"version": "1.0"}, "no presets"),
    ({"version": "1.0", "presets": {}}, "no presets"),
    ({"version": "1.0", "presets": []}, "no presets"),
])
def test_a_broken_file_refuses_everything_with_the_reason(tmp_path, doc, words):
    path = tmp_path / "presets.json"
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc))
    with pytest.raises(presets.PresetsError, match=words):
        presets.load_presets(shipped_roster(), SENDERS, relay.CONTRACTS, path=path)


def test_a_missing_file_refuses_with_the_reason(tmp_path):
    with pytest.raises(presets.PresetsError, match="Could not read"):
        presets.load_presets(shipped_roster(), SENDERS, relay.CONTRACTS, path=tmp_path / "none.json")


def test_a_preset_whose_agent_is_switched_off_stays_listed():
    # brief 24 (decision 8): it was refused at load; now intake fills the slot (or refuses the task, naming it)
    loaded = presets.load_presets(roster_with(grok=False), SENDERS, relay.CONTRACTS)
    assert "research-build" in loaded.presets and "research-build" not in loaded.problems


# ---------- sr relay --list ----------

def test_relay_list_prints_each_preset_its_stages_and_its_checker(capsys):
    assert cli.main(["relay", "--list"], platform="darwin") == 0
    out = capsys.readouterr().out
    assert "research-build" in out and any(f"version {v}" in out for v in SHIPPED_PRESET_VERSIONS)  # 6: 1.1; … 17: 1.5; 21: 1.6
    assert "1. research by grok (contract research_note)" in out
    assert "2. build by claude" in out and "checker: chatgpt" in out
    assert "BAD" not in out


def test_relay_list_prints_collab_with_its_check_stage_in_place_of_a_checker(capsys):
    assert cli.main(["relay", "--list"], platform="darwin") == 0
    out = capsys.readouterr().out.splitlines()
    i = out.index("collab")
    assert out[i + 1:i + 6] == [
        "  1. plan by claude (contract plan)",
        "  2. amend by chatgpt (contract amended_plan)",
        "  3. execute by claude (contract deliverable)",
        "  4. edit by chatgpt (contract edit_check)",
        "  check: stage 4 (chatgpt)",
    ]


def test_relay_list_marks_a_bad_preset_bad_with_the_reason(monkeypatch, tmp_path, capsys):
    doc = json.loads(json.dumps(GOOD))
    doc["presets"]["self-check"] = {"stages": [{"n": 1, "agent": "claude", "role": "build", "contract": None}],
                                    "checker": "claude"}
    path = tmp_path / "presets.json"
    path.write_text(json.dumps(doc))
    monkeypatch.setattr(presets, "PRESETS_PATH", path)
    assert cli.main(["relay", "--list"], platform="darwin") == 0
    out = capsys.readouterr().out
    assert "self-check: BAD" in out and "last stage" in out and "research-build" in out


def test_relay_refuses_a_broken_presets_file_and_logs_nothing(monkeypatch, tmp_path, capsys):
    path = tmp_path / "presets.json"
    path.write_text("{")
    monkeypatch.setattr(presets, "PRESETS_PATH", path)
    assert cli.main(["relay", "--list"], platform="darwin") == 2
    out = capsys.readouterr().out
    assert "Refused" in out and "not valid JSON" in out and "Nothing was logged" in out
    assert not cli.DB_PATH.exists()


# ---------- the check stage (build brief 6, rules v2.13) ----------

def test_collab_has_no_problems():
    assert _problems(_collab()) == []


def _is_check_on_stage_2():
    preset = _collab()
    preset["stages"][1]["is_check"] = True
    del preset["stages"][3]["is_check"]
    preset["stages"][3]["contract"] = None
    preset["checker"] = "claude"
    return preset


def _check_and_checker():
    preset = _collab()
    preset["checker"] = "claude"
    return preset


def _neither():
    preset = _collab()
    del preset["stages"][3]["is_check"]
    preset["stages"][3]["contract"] = None
    return preset


def _check_agent_is_stage_3s():
    preset = _collab()
    preset["stages"][3]["agent"] = "claude"
    return preset


def _check_contract_without_a_verdict():
    preset = _collab()
    preset["stages"][3]["contract"] = "deliverable"
    return preset


REFUSALS = [
    (_is_check_on_stage_2, "stage 2 is marked is_check but is not the last stage"),
    (_check_and_checker, "marks a check stage and names a checker"),
    (_neither, "has no checker, no check stage, no review stages and no tally"),
    (_check_agent_is_stage_3s, "check stage 4 is by claude, the agent of stage 3"),
    (_check_contract_without_a_verdict, "contract 'deliverable', which the code reads no verdict from"),
]


@pytest.mark.parametrize("make, words", REFUSALS)
def test_each_check_stage_rule_is_refused_with_its_reason(make, words):
    found = _problems(make())
    assert any(words in p for p in found), found


def test_is_check_must_be_true_when_given():
    preset = _collab()
    preset["stages"][3]["is_check"] = "yes"
    assert any("is_check" in p and "true" in p for p in _problems(preset))


def test_a_check_stage_needs_a_stage_before_it():
    preset = {"stages": [{"n": 1, "agent": "chatgpt", "role": "edit", "contract": "edit_check", "is_check": True}],
              "checker": None}
    assert any("needs a stage before it" in p for p in _problems(preset))


def test_without_the_verdict_readers_a_check_stage_is_refused():
    found = presets.problems("p", _collab(), shipped_roster(), SENDERS, relay.CONTRACTS)
    assert any("no verdict" in p for p in found)


@pytest.fixture
def scratch_presets(monkeypatch, tmp_path):
    """A scratch presets file holding every refused shape beside the shipped presets. The real
    config/presets.json is never edited."""
    doc = json.loads(presets.PRESETS_PATH.read_text())
    for i, (make, _) in enumerate(REFUSALS, 1):
        doc["presets"][f"bad-{i}"] = make()
    path = tmp_path / "presets.json"
    path.write_text(json.dumps(doc))
    monkeypatch.setattr(presets, "PRESETS_PATH", path)
    env = tmp_path / ".env"
    env.write_text("GROK_WEBHOOK_URL=https://example.invalid/hook\nGROK_WEBHOOK_KEY=FAKE-KEY-123\n")
    monkeypatch.setattr(cli, "ENV_PATH", env)
    monkeypatch.setattr(cli.safety, "prepare_workspace", lambda *a, **k: None)
    return path


def test_relay_list_marks_each_refused_shape_bad_with_its_reason(scratch_presets, capsys):
    assert cli.main(["relay", "--list"], platform="darwin") == 0
    out = capsys.readouterr().out
    for i, (_, words) in enumerate(REFUSALS, 1):
        block = out.split(f"bad-{i}: BAD")[1].split(": BAD")[0]
        assert words in block, (i, block)
    assert "collab\n" in out and "research-build\n" in out  # the good ones still load


@pytest.mark.parametrize("i", range(1, len(REFUSALS) + 1))
def test_sr_relay_refuses_each_refused_shape_and_logs_nothing(scratch_presets, capsys, i):
    assert cli.main(["relay", f"bad-{i}", "write a spec"], platform="darwin") == 2
    out = capsys.readouterr().out
    assert f"preset bad-{i} can't run" in out and REFUSALS[i - 1][1] in out and "Nothing was logged or sent." in out
    conn = log.init_db(cli.DB_PATH)
    assert log.recent_tasks(conn) == []
    conn.close()
