"""Build brief 33.3 (decisions 3, 6 and 11): `sr models`, `sr models set`, `sr models clear` and `sr models fable on|off`,
each with --json, and status's `models` (the defaults with their files, the allowlists, the Fable switch, Claude's Opus and
Fable calls this week, what each role would use now, Setup's rows). Fakes only; every value here is fake."""
import json

import pytest

from router import __main__ as cli
from router import log, models, receipt
from tests.fixtures import json_shapes
from tests.helpers import shipped_roster
from tests.test_status import _status, world  # noqa: F401 (the status fixture: fake checks, versions and store)

ROSTER = shipped_roster()
LOADED = cli._presets_or_none(ROSTER)
OPUS, SONNET, HAIKU, FABLE = "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"


def _models(words=(), **flags):
    out = receipt.Receipt()
    code = cli.cmd_models(list(words), roster=ROSTER, loaded=LOADED, as_json=True, out=out, **flags)
    return code, out


def _run(argv):
    """`sr models …` through main, so the parser and the dispatch are the real ones."""
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(argv)
    return code, buf.getvalue()


# ---------- sr models (the read) ----------

def test_sr_models_prints_the_defaults_with_their_files_and_json_gives_the_document():
    code, out = _models()
    assert code == 0 and out.document["api_version"] == 1
    doc = out.document["models"]
    json_shapes.check(doc, json_shapes.MODELS)
    assert doc["agents"]["claude"]["default"] == SONNET and doc["agents"]["claude"]["file"] == "config/models.json"
    assert doc["agents"]["chatgpt"]["default"] == "gpt-6.1-sol" and doc["agents"]["chatgpt"]["file"] == "config/agents.json"
    assert doc["agents"]["cursor"]["default"] == "grok-4.7-high"
    assert doc["fable"]["on"] is False and doc["layers"] == [] and doc["problems"] == []
    assert doc["now"]["teams"]["redteam"][0] == {"agent": "claude", "model": SONNET, "name": "Sonnet 5.5", "layer": "agent",
                                                  "key": None, "effort": None, "note": None, "stage": 1, "role": "build"}
    assert doc["now"]["skills"]["quick_answer"]["do"]["model"] == SONNET and "check" not in doc["now"]["skills"]["quick_answer"]
    assert doc["now"]["file"]["build"]["model"] == SONNET
    code, text = _run(["models"])
    assert code == 0 and "claude: Sonnet 5.5 (claude-sonnet-5-5) · config/models.json" in text and "Fable: off" in text


def test_sr_models_with_a_flag_and_no_verb_is_a_usage_refusal():
    code, out = _models(agent="claude")
    assert (code, out.code) == (2, "usage")


# ---------- set, clear, fable ----------

def test_set_writes_the_full_id_and_the_json_carries_the_defaults_after():
    code, out = _models(["set"], skill="code", agent="claude", model="opus")
    assert code == 0 and "Set skill code for claude: Opus 5.5 (claude-opus-5-5) · config/models.local.json" in out.message
    assert out.extra["models"]["layers"] == [{"layer": "skill", "key": "code", "agent": "claude", "model": OPUS, "name": "Opus 5.5",
                                             "effort": None, "file": "config/models.local.json"}]
    assert json.loads(models.LOCAL_PATH.read_text()) == {"skills": {"code": {"claude": {"model": OPUS}}}}
    code, out = _models(["set"], team="file", role="build", agent="claude", model="opus", effort="high")
    assert code == 0 and "Set file build for claude: Opus 5.5 (claude-opus-5-5), effort high" in out.message
    code, out = _models(["set"], team="redteam", stage="2", agent="chatgpt", effort="ultra")
    assert code == 0 and "Set redteam stage 2 for chatgpt: no model, effort ultra" in out.message
    assert out.extra["models"]["now"]["teams"]["redteam"][1]["effort"] == "ultra"
    assert out.extra["models"]["now"]["file"]["build"] == {"agent": "claude", "model": OPUS, "name": "Opus 5.5", "layer": "file",
                                                           "key": "file.build", "effort": "high", "note": None}
    code, out = _models(["set"], team="plan", role="plan", agent="claude", model="fable")  # allowed while Fable is off
    assert code == 0
    assert out.extra["models"]["now"]["teams"]["plan"][0]["model"] == OPUS and out.extra["models"]["now"]["teams"]["plan"][0]["note"] == models.FABLE_OFF_NOTE


@pytest.mark.parametrize("flags, code, words", [
    (dict(skill="nope", agent="claude", model="opus"), "bad_model", "no skill nope"),
    (dict(team="nope", role="build", agent="claude", model="opus"), "bad_model", "no team nope"),
    (dict(team="redteam", role="paint", agent="claude", model="opus"), "bad_model", "no role"),
    (dict(team="redteam", stage="9", agent="claude", model="opus"), "bad_model", "no stage 9"),
    (dict(team="plan", stage="5", agent="claude", model="opus"), "bad_model", "no stage 5"),
    (dict(skill="code", agent="claude", model="gpt-6.1-sol"), "bad_model", "isn't on claude's allowed list"),
    (dict(skill="code", agent="grok", model="x"), "bad_model", "no model choice"),
    (dict(skill="code", agent="chatgpt", effort="turbo"), "bad_model", "effort levels"),
    (dict(skill="code", agent="claude"), "usage", "give --model, --effort or both"),
    (dict(skill="code", team="file", role="build", agent="claude", model="opus"), "usage", "goes alone"),
    (dict(team="file", agent="claude", model="opus"), "usage", "--role or --stage"),
    (dict(agent="claude", model="opus"), "usage", "name a --skill"),
])
def test_set_refuses_with_nothing_written(flags, code, words):
    exit_code, out = _models(["set"], **flags)
    assert (exit_code, out.code) == (2, code) and words in out.message and "Nothing was changed" in out.message
    assert not models.LOCAL_PATH.exists()


def test_set_without_an_agent_and_a_bad_verb_are_usage():
    assert _models(["set"], skill="code", model="opus")[1].code == "usage"
    assert _models(["paint"])[1].code == "usage"
    assert _models(["clear"], skill="code", agent="claude", model="opus")[1].code == "usage"


def test_clear_takes_the_entry_out_and_says_when_nothing_was_set():
    _models(["set"], skill="code", agent="claude", model="opus")
    code, out = _models(["clear"], skill="code", agent="claude")
    assert code == 0 and "Cleared skill code for claude" in out.message and out.extra["models"]["layers"] == []
    code, out = _models(["clear"], skill="code", agent="claude")
    assert code == 0 and "(nothing was set)" in out.message


def test_the_fable_switch_writes_one_key_and_says_the_words():
    code, out = _models(["fable", "on"])
    assert code == 0 and "Fable: on (it was off). " + models.FABLE_WORDS in out.message
    assert out.extra["models"]["fable"]["on"] is True and models.local().fable_on is True
    code, out = _models(["fable", "off"])
    assert code == 0 and "Fable: off (it was on). A Fable default runs on Opus 5.5 while it is off." in out.message
    assert models.local().fable_on is False
    for words in (["fable"], ["fable", "maybe"], ["fable", "on", "x"]):
        assert _models(words)[1].code == "usage"
    assert _models(["fable", "on"], agent="claude")[1].code == "usage"


def test_through_main_sr_models_set_and_json_answer_with_the_envelope():
    code, text = _run(["models", "set", "--json", "--skill", "code", "--agent", "claude", "--model", "opus"])
    assert code == 0
    doc = json.loads(text)
    assert doc["exit"] == 0 and doc["reason_code"] is None and "Set skill code for claude" in doc["message"]
    assert doc["models"]["layers"][0]["model"] == OPUS
    code, text = _run(["models", "--json"])
    assert code == 0 and json.loads(text)["models"]["layers"][0]["key"] == "code"
    code, text = _run(["models", "fable", "on", "--json"])
    assert code == 0 and json.loads(text)["models"]["fable"]["on"] is True


# ---------- status's models (decision 11) ----------

def test_status_carries_the_models_block_with_the_counts_now_and_setup(world):
    models.set_default({"skill": "code"}, "claude", model="opus")
    models.set_default({"team": "file", "role": "build"}, "claude", model="opus")
    conn = log.init_db(cli.DB_PATH)
    log.add_task(conn, "sr-a", "t", "cli", {"status": "ok", "label": "code", "confidence": 0.9, "needs_split": 0.1, "tokens": 0})
    log.add_call(conn, "sr-a", "sr-a", "do", "claude", status="done", text="x", model=OPUS, time_limit=1200,
                 served={"asked": OPUS, "model": OPUS, "credits": {"seen": False}})
    log.add_call(conn, "sr-a-f1", "sr-a", "fix", "claude", status="done", text="x", model=FABLE, time_limit=1200,
                 served={"asked": FABLE, "model": "claude-opus-4-8", "credits": {"seen": False}})
    conn.close()
    doc = _status(world)
    json_shapes.check(doc, json_shapes.STATUS, optional=("report_path",))
    found = doc["models"]
    assert found["claude"] == {"opus_calls_this_week": 2, "fable_calls_this_week": 0}  # by the model that answered
    assert found["agents"]["claude"]["allowed"] == [HAIKU, SONNET, OPUS, FABLE] and found["fable"]["on"] is False
    assert {e["key"] for e in found["layers"]} == {"code", "file.build"} and found["now"]["skills"]["code"]["do"]["model"] == OPUS
    assert found["now"]["skills"]["code"]["do"]["layer"] == "skill" and found["now"]["skills"]["code"]["check"]["model"] == "gpt-6.1-sol"
    skills = {r["key"]: r for r in found["setup"]["skills"]}
    assert skills["code"]["model"] == OPUS and skills["writing"]["model"] is None
    roles = {(r["team"], r["role"], r["agent"]) for r in found["setup"]["roles"]}
    assert ("file", "build", "claude") in roles and ("redteam", "attack", "chatgpt") in roles and ("plan", "plan", "claude") in roles
    assert ("vote", "vote", "claude") in roles and ("route", "check", "chatgpt") in roles
    assert not any(r["agent"] == "grok" for r in found["setup"]["roles"])
    # the review's a5: per-stage selects (a preset's and a plan's numbered stages) and each skill's doer as its agent
    stages = {(r["team"], r["stage"], r["agent"]) for r in found["setup"]["stages"]}
    assert ("plan", 1, "claude") in stages and {r["team"] for r in found["setup"]["stages"]} >= {"redteam", "collab", "plan"}
    assert all(isinstance(r["stage"], int) and r["role"] and r["agent"] in ("claude", "chatgpt", "cursor") for r in found["setup"]["stages"])
    assert not any(r["team"] in ("route", "split", "file") for r in found["setup"]["stages"])
    doers = {r["key"]: r["agent"] for r in found["setup"]["skills"]}
    assert doers["code"] == "claude" and "chatgpt" in doers.values()  # the ChatGPT-best skills get ChatGPT's select
    assert found["now"]["project_skills"]["writing"]["do"]["layer"] == "file"  # a routed build on a project: Opus
