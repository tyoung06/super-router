"""Build brief 33.3 (decisions 4, 6, 12 and 13): the page's models parts on the Python side. `--model <agent>=<model>`
on a send from the Models sheet (route, a team, split, plan), the three actions Setup's Models row runs (`models_set`,
`models_clear`, `models_fable`), each an argument list the real parser reads; refused with the reason before anything
runs; status dropped after one of them ends well; the docs' section and the demo's additions. Nothing here calls a model."""
import json
from pathlib import Path

import pytest

from router import __main__ as cli
from router import page, page_commands as pc
from tests.test_page_commands import TEXT, TID, status  # noqa: F401 (the status fixture)

ROOT = Path(__file__).resolve().parents[1]
HAIKU, OPUS, FABLE = "claude-haiku-5-5", "claude-opus-5-5", "claude-fable-5-1"
MODELS = {"agents": {
    "claude": {"default": "claude-sonnet-5-5", "allowed": [HAIKU, "claude-sonnet-5-5", OPUS, FABLE],
               "aliases": {"haiku": HAIKU, "sonnet": "claude-sonnet-5-5", "opus": OPUS, "fable": FABLE}},
    "chatgpt": {"default": "gpt-6.1-sol", "allowed": ["gpt-6.1-sol", "gpt-6-astra"], "aliases": {}},
    "cursor": {"default": "grok-4.7-high", "allowed": ["grok-4.7-high"], "aliases": {}}}, "fable": {"on": False}}


def _args(request, st):
    return list(pc.build(request, st).args)


# ---------- --model on a send (decision 4) ----------

def test_a_send_carries_each_chosen_agents_model_in_agent_order_on_every_team(status):
    st = {**status, "models": MODELS}
    chosen = {"chatgpt": "gpt-6-astra", "claude": HAIKU}
    assert _args({"action": "send", "team": "route", "text": "x", "models": chosen}, st) == [
        "route", "--json", "--source", "ui", "--model", "chatgpt=gpt-6-astra", "--model", "claude=" + HAIKU, "--", "x"]
    assert _args({"action": "send", "team": "versus", "text": "x", "models": {"claude": "opus"}}, st) == [
        "relay", "versus", "--json", "--source", "ui", "--model", "claude=opus", "--", "x"]  # an alias is a name too
    assert _args({"action": "send", "team": "split", "text": "x", "project": "p", "models": {"claude": OPUS}}, st) == [
        "split", "--json", "--source", "ui", "--project", "p", "--model", "claude=" + OPUS, "--", "x"]
    assert _args({"action": "send", "team": "plan", "text": "x", "project": "p", "models": {"claude": OPUS}}, st) == [
        "plan", "--json", "--source", "ui", "--project", "p", "--model", "claude=" + OPUS, "--", "x"]
    for empty in (None, {}):
        assert "--model" not in _args({"action": "send", "team": "route", "text": "x", "models": empty}, st)
    assert pc.build({"action": "send", "team": "route", "text": TEXT, "models": {"claude": HAIKU}}, st).copy() == (
        f"sr route --model claude={HAIKU} -- " + pc.Command((TEXT,)).copy()[3:])


@pytest.mark.parametrize("models, why", [
    (["claude=opus"], "map an agent to a model"),
    ({"grok": "x"}, "grok has no model choice"),
    ({"claude": "claude opus"}, "plain name"),
    ({"claude": "-x"}, "plain name"),
    ({"claude": 7}, "plain name"),
    ({"claude": "gpt-6.1-sol"}, "isn't on claude's allowed list"),
    ({"chatgpt": "claude-opus-5-5"}, "isn't on chatgpt's allowed list"),
])
def test_a_bad_choice_is_refused_before_anything_runs(status, models, why):
    with pytest.raises(pc.Refused, match=why):
        pc.build({"action": "send", "team": "route", "text": "x", "models": models}, {**status, "models": MODELS})


def test_without_allowlists_in_status_the_name_goes_through_for_the_router_to_check(status):
    assert _args({"action": "send", "team": "route", "text": "x", "models": {"claude": "whatever-9"}}, status)[4:6] == [
        "--model", "claude=whatever-9"]


# ---------- Setup's three actions (decisions 6 and 12) ----------

@pytest.mark.parametrize("request_, argv", [
    ({"action": "models_set", "selector": {"skill": "code"}, "agent": "claude", "model": "opus"},
     ["models", "set", "--json", "--skill", "code", "--agent", "claude", "--model", "opus"]),
    ({"action": "models_set", "selector": {"team": "file", "role": "build"}, "agent": "claude", "model": OPUS},
     ["models", "set", "--json", "--team", "file", "--role", "build", "--agent", "claude", "--model", OPUS]),
    ({"action": "models_set", "selector": {"team": "redteam", "stage": 2}, "agent": "chatgpt", "model": "gpt-6-astra"},
     ["models", "set", "--json", "--team", "redteam", "--stage", "2", "--agent", "chatgpt", "--model", "gpt-6-astra"]),
    ({"action": "models_set", "selector": {"team": "redteam", "stage": "3"}, "agent": "cursor", "model": "grok-4.7-high"},
     ["models", "set", "--json", "--team", "redteam", "--stage", "3", "--agent", "cursor", "--model", "grok-4.7-high"]),
    ({"action": "models_clear", "selector": {"skill": "code"}, "agent": "claude"},
     ["models", "clear", "--json", "--skill", "code", "--agent", "claude"]),
    ({"action": "models_clear", "selector": {"team": "plan", "role": "plan"}, "agent": "claude"},
     ["models", "clear", "--json", "--team", "plan", "--role", "plan", "--agent", "claude"]),
    ({"action": "models_fable", "to": "on"}, ["models", "fable", "on", "--json"]),
    ({"action": "models_fable", "to": "off"}, ["models", "fable", "off", "--json"]),
])
def test_each_models_action_builds_its_argv(status, request_, argv):
    command = pc.build(request_, status)
    assert list(command.args) == argv
    assert [a for i, a in enumerate(argv) if i in command.added] == ["--json"]  # the page's one added flag, dimmed
    assert command.copy() == "sr " + " ".join(a for a in argv if a != "--json")


@pytest.mark.parametrize("request_, why", [
    ({"action": "models_set", "selector": "code", "agent": "claude", "model": "opus"}, "a selector is"),
    ({"action": "models_set", "selector": {}, "agent": "claude", "model": "opus"}, "a selector is"),
    ({"action": "models_set", "selector": {"skill": "code", "team": "file"}, "agent": "claude", "model": "opus"}, "a selector is"),
    ({"action": "models_set", "selector": {"team": "file"}, "agent": "claude", "model": "opus"}, "a selector is"),
    ({"action": "models_set", "selector": {"skill": "dancing"}, "agent": "claude", "model": "opus"}, "no skill dancing"),
    ({"action": "models_set", "selector": {"team": "Red Team", "role": "build"}, "agent": "claude", "model": "opus"}, "the team is a plain"),
    ({"action": "models_set", "selector": {"team": "redteam", "role": "-x"}, "agent": "claude", "model": "opus"}, "the role is a plain"),
    ({"action": "models_set", "selector": {"team": "redteam", "stage": 0}, "agent": "claude", "model": "opus"}, "1 to 12"),
    ({"action": "models_set", "selector": {"team": "redteam", "stage": True}, "agent": "claude", "model": "opus"}, "1 to 12"),
    ({"action": "models_set", "selector": {"team": "redteam", "stage": "two"}, "agent": "claude", "model": "opus"}, "1 to 12"),
    ({"action": "models_set", "selector": {"skill": "code"}, "agent": "grok", "model": "opus"}, "grok has no model choice"),
    ({"action": "models_set", "selector": {"skill": "code"}, "agent": "claude"}, "a model is a plain name"),
    ({"action": "models_set", "selector": {"skill": "code"}, "agent": "claude", "model": "--model"}, "a model is a plain name"),
    ({"action": "models_clear", "selector": {"skill": "code"}, "agent": "claude", "model": "opus"}, "a clear takes no model"),
    ({"action": "models_fable", "to": "maybe"}, "on or off"),
    ({"action": "models_fable"}, "on or off"),
])
def test_a_bad_models_request_is_refused_with_the_reason(status, request_, why):
    with pytest.raises(pc.Refused, match=why):
        pc.build(request_, status)


@pytest.mark.parametrize("request_", [
    {"action": "send", "team": "route", "text": TEXT, "chat": "garden", "models": {"claude": HAIKU, "chatgpt": "gpt-6-astra"}},
    {"action": "send", "team": "versus", "text": TEXT, "slots": {"b": "cursor"}, "models": {"claude": "opus"}},
    {"action": "send", "team": "split", "text": TEXT, "project": "p", "models": {"claude": OPUS}},
    {"action": "send", "team": "plan", "text": TEXT, "project": "p", "models": {"claude": OPUS}},
    {"action": "models_set", "selector": {"skill": "code"}, "agent": "claude", "model": "opus"},
    {"action": "models_set", "selector": {"team": "redteam", "stage": 2}, "agent": "chatgpt", "model": "gpt-6-astra"},
    {"action": "models_clear", "selector": {"team": "file", "role": "build"}, "agent": "claude"},
    {"action": "models_fable", "to": "on"},
])
def test_the_real_parser_reads_every_built_argv(status, request_):
    argv = _args(request_, status)
    assert cli._json_requested(argv), argv
    rest, slot_flags = cli._take_slot_flags(argv)
    args = cli._parser(None, quiet=True).parse_args(rest)
    assert args.command == argv[0] and args.json is True
    if request_["action"] == "send":
        assert " ".join(args.task) == TEXT and len(args.task) == 1
        assert args.model == [f"{a}={m}" for a, m in sorted(request_["models"].items())]
        if request_.get("slots"):
            assert slot_flags == sorted(request_["slots"].items())
    else:
        assert args.words == [request_["action"].split("_")[1], *([request_["to"]] if "to" in request_ else [])]
        if "selector" in request_:
            assert args.agent == request_["agent"]
            assert args.skill == request_["selector"].get("skill")
            assert args.team == request_["selector"].get("team")
            assert args.model == request_.get("model")


def test_the_three_actions_drop_the_kept_status_once_they_end_well():
    assert {"models_set", "models_clear", "models_fable"} <= set(page.DROPS_STATUS)


# ---------- the docs and the demo (decision 13) ----------

def test_setup_md_has_the_models_section_and_names_no_person_or_path():
    text = (ROOT / "docs" / "SETUP.md").read_text(encoding="utf-8")
    assert "\n## Models\n" in text
    section = text.split("\n## Models\n", 1)[1].split("\n## ", 1)[0]
    for words in ("config/models.json", "config/models.local.json", "sr models set", "sr models fable on", "usage credits",
                  "Models…", "/model", "--model <agent>=<model>"):
        assert words in section, words
    assert "/Users/" not in section


def test_the_demo_holds_the_models_additions():
    status_doc = json.loads((ROOT / "demo" / "status.json").read_text(encoding="utf-8"))
    models = status_doc["models"]
    assert models["agents"]["claude"]["default"] == "claude-sonnet-5-5" and models["fable"]["on"] is False
    assert {(entry["layer"], entry["key"]) for entry in models["layers"]} >= {("skill", "code"), ("role", "file.build"), ("role", "plan.plan")}
    assert models["setup"]["skills"] and models["setup"]["roles"]
    shows = [json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "demo" / "tasks").glob("*.json")]
    opus = [s for s in shows if any(c["kind"] == "do" and c["model"] == OPUS and (c["served"] or {}).get("model") == OPUS for c in s["calls"])]
    assert opus, "a card whose do call ran Opus"
    differs = [s for s in shows if "re-ran this on" in (s.get("card_line") or "")]
    assert differs, "a card with a served-differs line"
    assert any(s["models"] for s in shows), "a task with its own choice"
