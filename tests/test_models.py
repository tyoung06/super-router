"""Build brief 33.3 (rules 2.48, Models; decisions 1 to 11): router/models.py. The tracked file and the local file, the
allowlists and aliases, the resolution's layers and precedence, decision 2's defaults, the Fable switch and its fallback,
the time limits, the effort layers, the served record and the credits check, and the local file's writes. Every value
here is fake; nothing calls a model."""
import json
import os
import stat

import pytest

from router import log, models

PINS = {"chatgpt": "gpt-6.1-sol", "cursor": "grok-4.7-high"}
OPUS, SONNET, HAIKU, FABLE = "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"


@pytest.fixture
def files(tmp_path, monkeypatch):
    """The real tracked file, and a local file of this test's own (conftest already points LOCAL_PATH at a temp file)."""
    monkeypatch.setattr(models, "LOCAL_PATH", tmp_path / "models.local.json")
    return models.TRACKED_PATH, tmp_path / "models.local.json"


def _task(mode="route", skill=None, preset=None, models_json=None, file_mode=False):
    files = json.dumps({"mode": "on", "state": "none", "copy": True}) if file_mode else None
    return {"mode": mode, "skill": skill, "preset": preset, "models": json.dumps(models_json) if models_json else None,
            "project_files": files, "task_id": "sr-t"}


def _seed(local, **sections):
    local.write_text(json.dumps(sections))


# ---------- the tracked file (decisions 3 and 5) ----------

def test_the_tracked_file_reads_clean_with_claudes_four_ids_and_the_pins_allowed():
    found = models.tracked()
    assert found.problems == ()
    assert found.default("claude") == SONNET
    assert found.allowed("claude") == [HAIKU, SONNET, OPUS, FABLE]
    assert found.aliases("claude") == {"haiku": HAIKU, "sonnet": SONNET, "opus": OPUS, "fable": FABLE}
    assert found.gated("claude") == [FABLE]
    assert found.efforts("claude") == ["low", "medium", "high", "xhigh", "max"]
    assert PINS["chatgpt"] in found.allowed("chatgpt") and PINS["cursor"] in found.allowed("cursor")
    assert "auto" not in found.allowed("cursor") and all(m.lstrip("cursor-").startswith("grok") for m in found.allowed("cursor"))
    assert found.display("claude", "opus") == "Opus 5.5" and found.display("claude", OPUS) == "Opus 5.5"


def test_a_tracked_file_that_is_missing_or_broken_reads_empty_with_why(tmp_path):
    assert models.tracked(tmp_path / "none.json").problems == ("config/models.json is missing",)
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    assert "could not be read" in models.tracked(bad).problems[0]
    bad.write_text(json.dumps({"agents": {"claude": {"default": OPUS, "allowed": [SONNET]}, "chatgpt": {"allowed": ["x"]},
                                          "cursor": {"allowed": ["auto"]}}}))
    found = models.tracked(bad)
    assert any("claude's default must be on" in p for p in found.problems)
    assert any("cursor's allowed list holds" in p for p in found.problems)
    assert found.allowed("claude") == [] and found.default("claude") is None


@pytest.mark.parametrize("agent, name, model, why", [
    ("claude", "opus", OPUS, None), ("claude", OPUS, OPUS, None), ("claude", "fable", FABLE, None),
    ("claude", "gpt-6.1-sol", None, "isn't on claude's allowed list"),
    ("chatgpt", "gpt-6.1-sol", "gpt-6.1-sol", None), ("chatgpt", "opus", None, "isn't on chatgpt's allowed list"),
    ("cursor", "auto", None, "isn't on cursor's allowed list"), ("cursor", "grok-4.7-high", "grok-4.7-high", None),
    ("grok", "fable", None, "Grok Bot has no model choice"), ("jev", "x", None, "Jev has no model choice"),
    ("claude", "", None, "must be a name"),
])
def test_canonical_maps_aliases_and_refuses_what_is_off_the_list(agent, name, model, why):
    got, reason = models.canonical(agent, name)
    assert got == model and (why is None or why in reason)


def test_check_choice_refuses_fable_while_off_and_takes_it_while_on():
    assert models.check_choice("claude", "fable", fable_on=False) == (None, models.FABLE_OFF_REFUSAL)
    assert models.check_choice("claude", "fable", fable_on=True) == (FABLE, None)
    assert models.check_choice("claude", "haiku", fable_on=False) == (HAIKU, None)


def test_check_effort_takes_each_agents_own_levels():
    assert models.check_effort("claude", "xhigh") == ("xhigh", None)
    assert models.check_effort("chatgpt", "ultra") == ("ultra", None)
    assert models.check_effort("claude", "ultra")[0] is None and models.check_effort("cursor", "high")[0] is None


# ---------- the flags (decision 4) ----------

def test_choices_from_flags_keep_each_agent_once_and_refuse_by_code():
    allowed = lambda agent: (agent in ("claude", "chatgpt"), None if agent in ("claude", "chatgpt") else f"{agent} makes no call here")
    found = models.choices_from_flags(["claude=haiku", "chatgpt=gpt-6-astra"], ["claude=max"], agents_allowed=allowed,
                                      fable_on=False)
    assert found == {"claude": {"model": HAIKU, "effort": "max"}, "chatgpt": {"model": "gpt-6-astra", "effort": None}}
    with pytest.raises(models.ModelsError) as err:
        models.choices_from_flags(["claude=opus", "claude=sonnet"], agents_allowed=allowed, fable_on=False)
    assert err.value.code == "usage" and "twice" in str(err.value)
    for flags, words in ((["claude=gpt-6.1-sol"], "isn't on claude's allowed list"), (["cursor=auto"], "makes no call here"),
                         (["grok=fable"], "Grok Bot has no model choice"), (["claude=fable"], "Fable is off")):
        with pytest.raises(models.ModelsError) as err:
            models.choices_from_flags(flags, agents_allowed=allowed, fable_on=False)
        assert err.value.code == "bad_model" and words in str(err.value)
    with pytest.raises(models.ModelsError) as err:
        models.choices_from_flags(["claude"], agents_allowed=allowed, fable_on=False)
    assert err.value.code == "usage"
    with pytest.raises(models.ModelsError) as err:
        models.choices_from_flags([], ["claude=ultra"], agents_allowed=allowed, fable_on=False)
    assert err.value.code == "bad_model" and "effort levels" in str(err.value)


# ---------- the resolution (decision 1) and the defaults (decision 2) ----------

def test_with_no_local_file_every_claude_call_asks_sonnet_and_the_others_their_pins(files):
    for kind, stage, role in (("do", None, None), ("check", None, None), ("stage", 1, "build"), ("stage", 2, "attack")):
        choice = models.resolve(_task("relay", preset="redteam"), "claude", kind=kind, stage=stage, role=role, pins=PINS)
        assert (choice.model, choice.layer, choice.file, choice.name, choice.timeout) == (SONNET, "agent", "config/models.json", "Sonnet 5.5", 600)
    chat = models.resolve(_task(), "chatgpt", kind="check", pins=PINS)
    assert (chat.model, chat.layer, chat.file) == ("gpt-6.1-sol", "agent", "config/agents.json")
    cur = models.resolve(_task("relay", preset="versus"), "cursor", kind="stage", stage=2, role="build", pins=PINS)
    assert (cur.model, cur.layer, cur.file) == ("grok-4.7-high", "agent", "config/agents.json")
    grok = models.resolve(_task(), "grok", kind="do", pins=PINS)
    assert grok.model is None and "no model choice" in grok.note


def _seed_decision_2(local):
    _seed(local, skills={"code": {"claude": {"model": OPUS}}, "quick_answer": {"claude": {"model": SONNET}}},
          roles={**{f"file.{r}": {"claude": {"model": OPUS}} for r in ("build", "revise", "execute", "fix", "integrate")},
                 **{f"plan.{r}": {"claude": {"model": FABLE}} for r in ("plan", "revise", "fix")}})


def test_decision_2_code_builds_on_opus_off_a_project_and_in_file_mode(files):
    _seed_decision_2(files[1])
    do = models.resolve(_task(skill="code"), "claude", kind="do", pins=PINS)
    fix = models.resolve(_task(skill="code"), "claude", kind="fix", pins=PINS)
    assert (do.model, do.layer, do.key, do.file, do.timeout) == (OPUS, "skill", "code", "config/models.local.json", 1200)
    assert (fix.model, fix.layer) == (OPUS, "skill")
    check = models.resolve(_task(skill="code"), "claude", kind="check", pins=PINS)
    assert (check.model, check.layer) == (SONNET, "agent")  # checks stay on Sonnet
    # on a project in file mode: research-build's build, redteam's build and revise, collab's execute, a split's join
    for preset, kind, stage, role in (("research-build", "stage", 2, "build"), ("redteam", "stage", 4, "revise"),
                                      ("collab", "stage", 3, "execute"), ("redteam", "fix", None, None)):
        choice = models.resolve(_task("relay", preset=preset, file_mode=True), "claude", kind=kind, stage=stage, role=role, pins=PINS)
        assert (choice.model, choice.layer, choice.key) == (OPUS, "file", f"file.{models.word_of(kind, role)}"), (preset, kind)
    join = models.resolve(_task("split", file_mode=True), "claude", kind="stage", stage=2, role="integrate", pins=PINS)
    assert (join.model, join.key) == (OPUS, "file.integrate")
    plan_piece = models.resolve(_task("split", file_mode=True), "claude", kind="stage", stage=1, role="split_plan", pins=PINS)
    assert plan_piece.model == SONNET  # a split's plan reads the copy, it builds nothing
    off = models.resolve(_task("relay", preset="redteam", file_mode=False), "claude", kind="stage", stage=1, role="build", pins=PINS)
    assert (off.model, off.layer) == (SONNET, "agent")  # the file-mode default needs file mode


def test_decision_2_nothing_else_on_a_project_keeps_sonnet(files):
    # the review's a4: a routed task in file mode builds in its copy (a plan's routed steps included), so its do and fix
    # calls read the file-mode defaults; a routed recall or web_research doer there keeps Sonnet, and a quick answer its own
    _seed_decision_2(files[1])
    for skill in ("recall", "web_research"):
        choice = models.resolve(_task(skill=skill, file_mode=True), "claude", kind="do", pins=PINS)
        assert (choice.model, choice.layer) == (SONNET, "agent"), skill
    quick = models.resolve(_task(skill="quick_answer", file_mode=True), "claude", kind="do", pins=PINS)
    assert (quick.model, quick.layer) == (SONNET, "skill")
    for skill in ("writing", "planning"):
        for kind in ("do", "fix"):
            choice = models.resolve(_task(skill=skill, file_mode=True), "claude", kind=kind, pins=PINS)
            assert (choice.model, choice.layer, choice.key) == (OPUS, "file", f"file.{'build' if kind == 'do' else 'fix'}"), (skill, kind)
        check = models.resolve(_task(skill=skill, file_mode=True), "claude", kind="check", pins=PINS)
        assert (check.model, check.layer) == (SONNET, "agent")  # a check never builds
        off = models.resolve(_task(skill=skill, file_mode=False), "claude", kind="do", pins=PINS)
        assert (off.model, off.layer) == (SONNET, "agent")  # off a project: the skill's own layer, else the agent's
    piece = models.resolve(_task("piece", skill="writing", file_mode=True), "claude", kind="do", pins=PINS)
    assert (piece.model, piece.layer) == (OPUS, "file")  # a route piece of a project split builds in the split's copy
    attack = models.resolve(_task("relay", preset="redteam", file_mode=True), "chatgpt", kind="stage", stage=2, role="attack", pins=PINS)
    assert attack.model == "gpt-6.1-sol"


def test_decision_2_plans_planning_calls_on_fable_while_on_and_opus_with_the_note_while_off(files):
    _seed_decision_2(files[1])
    plan = _task("plan", preset="redteam", file_mode=True)
    for kind, stage, role in (("stage", 1, "plan"), ("stage", 4, "revise"), ("fix", None, None)):
        choice = models.resolve(plan, "claude", kind=kind, stage=stage, role=role, pins=PINS)
        assert (choice.model, choice.layer, choice.note, choice.timeout) == (OPUS, "role", models.FABLE_OFF_NOTE, 1200), kind
    models.set_fable(True)
    for kind, stage, role in (("stage", 1, "plan"), ("stage", 4, "revise"), ("fix", None, None)):
        choice = models.resolve(plan, "claude", kind=kind, stage=stage, role=role, pins=PINS)
        assert (choice.model, choice.layer, choice.key, choice.note) == (FABLE, "role", f"plan.{models.word_of(kind, role)}", None)
    check = models.resolve(plan, "chatgpt", kind="check", pins=PINS)
    assert check.model == "gpt-6.1-sol"
    attack = models.resolve(plan, "claude", kind="stage", stage=2, role="attack", pins=PINS)
    assert attack.model == SONNET  # the plan's attack by Claude (a resumed stage) is no planning call


def test_decision_2_quick_answer_on_sonnet_and_the_skill_layer_only_for_do_and_fix(files):
    _seed(files[1], skills={"quick_answer": {"claude": {"model": HAIKU}}, "writing": {"claude": {"model": OPUS}}})
    assert models.resolve(_task(skill="quick_answer"), "claude", kind="do", pins=PINS).model == HAIKU
    assert models.resolve(_task(skill="writing"), "claude", kind="check", pins=PINS).model == SONNET
    assert models.resolve(_task("piece", skill="writing"), "claude", kind="fix", pins=PINS).model == OPUS


def test_the_layers_precedence_task_then_stage_then_role_then_file_then_skill(files):
    _seed(files[1], skills={"code": {"claude": {"model": HAIKU}}},
          roles={"redteam.build": {"claude": {"model": OPUS}}, "file.build": {"claude": {"model": SONNET}}},
          stages={"redteam.1": {"claude": {"model": HAIKU}}})
    task = _task("relay", preset="redteam", file_mode=True)
    stage = models.resolve(task, "claude", kind="stage", stage=1, role="build", pins=PINS)
    assert (stage.model, stage.layer, stage.key) == (HAIKU, "stage", "redteam.1")
    role = models.resolve(task, "claude", kind="stage", stage=4, role="build", pins=PINS)  # no stage entry for 4
    assert (role.model, role.layer, role.key) == (OPUS, "role", "redteam.build")
    _seed(files[1], roles={"file.build": {"claude": {"model": OPUS}}}, skills={"code": {"claude": {"model": HAIKU}}})
    file = models.resolve(task, "claude", kind="stage", stage=1, role="build", pins=PINS)
    assert (file.model, file.layer) == (OPUS, "file")
    own = models.resolve({**task, "models": json.dumps({"claude": {"model": HAIKU, "effort": "low"}})}, "claude",
                         kind="stage", stage=1, role="build", pins=PINS)
    assert (own.model, own.layer, own.file, own.effort, own.effort_layer) == (HAIKU, "task", "the task", "low", "task")
    taken = models.resolve({**task, "models": json.dumps({"claude": {"model": HAIKU}})}, "claude", kind="stage", stage=1,
                           role="build", takeover=True, pins=PINS)
    assert (taken.model, taken.layer) == (OPUS, "file")  # a takeover's substitute uses its own defaults


def test_a_local_layer_naming_a_model_off_the_allowlist_is_ignored_and_named(files):
    _seed(files[1], skills={"code": {"claude": {"model": "gpt-6.1-sol"}, "chatgpt": {"model": "opus", "effort": "ultra"}},
                            "writing": {"grok": {"model": "x"}}},
          roles={"redteam.build": {"claude": {"effort": "turbo", "model": "opus"}}}, stages="no")
    found = models.local()
    assert models.resolve(_task(skill="code"), "claude", kind="do", pins=PINS).model == SONNET
    assert models.resolve(_task(skill="code"), "chatgpt", kind="do", pins=PINS).model == "gpt-6.1-sol"
    choice = models.resolve(_task("relay", preset="redteam"), "claude", kind="stage", stage=1, role="build", pins=PINS)
    assert (choice.model, choice.effort) == (OPUS, None)
    assert any("skills.code.claude: gpt-6.1-sol isn't on claude's allowed list" in p for p in found.problems)
    assert any("skills.code.chatgpt: opus isn't on chatgpt's allowed list" in p for p in found.problems)
    assert any("'turbo' isn't one of claude's effort levels" in p for p in found.problems)
    assert any("names grok, which has no model choice" in p for p in found.problems)
    assert any("stages must map keys to agents" in p for p in found.problems)
    files[1].write_text("[1, 2]")
    assert "not a JSON object" in models.local().problems[0] and models.resolve(_task(skill="code"), "claude", kind="do").model == SONNET


def test_a_tasks_own_fable_choice_falls_back_to_opus_once_fable_is_off_again(files):
    task = _task(models_json={"claude": {"model": FABLE}})
    choice = models.resolve(task, "claude", kind="do", pins=PINS)
    assert (choice.model, choice.layer, choice.note) == (OPUS, "task", models.FABLE_OFF_NOTE)


def test_time_limits_go_by_model_and_effort_rides_the_layers(files):
    _seed(files[1], skills={"code": {"claude": {"model": OPUS, "effort": "high"}}},
          roles={"route.check": {"chatgpt": {"effort": "ultra"}}})
    do = models.resolve(_task(skill="code"), "claude", kind="do", pins=PINS)
    assert (do.timeout, do.effort, do.effort_layer, do.effort_key) == (1200, "high", "skill", "code")
    assert models.resolve(_task(models_json={"claude": {"model": FABLE}}), "claude", kind="do", pins=PINS).timeout == 1200
    assert models.resolve(_task(models_json={"claude": {"model": HAIKU}}), "claude", kind="do", pins=PINS).timeout == 600
    check = models.resolve(_task(skill="code"), "chatgpt", kind="check", pins=PINS)
    assert (check.model, check.effort, check.effort_layer, check.timeout) == ("gpt-6.1-sol", "ultra", "role", 600)
    assert models.resolve(_task(), "cursor", kind="stage", stage=2, role="build", pins=PINS).timeout == 600
    assert models.resolve(_task(), "claude", kind="do", pins=PINS).effort is None  # no default effort (decision 9)


def test_word_and_team_of_each_call():
    assert models.word_of("do") == "build" and models.word_of("recheck") == "check" and models.word_of("fix") == "fix"
    assert models.word_of("stage", "split_plan") == "plan" and models.word_of("reask", "attack") == "attack"
    assert models.team_of({"mode": "plan"}) == "plan" and models.team_of({"mode": "split"}) == "split"
    assert models.team_of({"mode": "relay", "preset": "versus"}) == "versus" and models.team_of({"mode": "piece"}) == "route"


# ---------- the served record and the credits check (decisions 6 and 7) ----------

def _stream(model=SONNET, used=None, rate=None, effort=None):
    init = {"type": "system", "subtype": "init", "model": model, "tools": [], "mcp_servers": []}
    if effort:
        init["effort"] = effort
    events = [init]
    if rate is not None:
        events.append({"type": "rate_limit_event", "rate_limit_info": rate})
    result = {"type": "result", "subtype": "success", "result": "ok", "is_error": False, "total_cost_usd": 0.01}
    if used is not None:
        result["modelUsage"] = {m: {"costUSD": 0.0} for m in used}
    events.append(result)
    return events


def test_claude_served_reads_init_and_model_usage_and_a_fallback_differs():
    choice = models.resolve(_task(models_json={"claude": {"model": FABLE}}), "claude", kind="do", pins=PINS,
                            local_doc=models.Local({"fable": {"on": True}}))
    assert choice.model == FABLE
    same = models.claude_served(_stream(FABLE, used=[FABLE], effort="high"), choice)
    assert (same["asked"], same["model"], same["models_used"], same["differs"], same["source"]) == (FABLE, FABLE, [FABLE], False, "stream: init and modelUsage")
    assert (same["credits"], same["effort_served"], same["time_limit"], same["layer"]) == ({"seen": False}, "high", 1200, "task")
    fell = models.claude_served(_stream(FABLE, used=[FABLE, "claude-opus-4-8"]), choice)
    assert (fell["model"], fell["differs"]) == ("claude-opus-4-8", True)
    init_only = models.claude_served(_stream("claude-sonnet-5-5-20260601"), models.resolve(_task(), "claude", kind="do"))
    assert (init_only["model"], init_only["differs"]) == ("claude-sonnet-5-5-20260601", False)  # a dated form of the id
    nothing = models.claude_served([{"type": "result", "result": "x"}], models.resolve(_task(), "claude", kind="do"))
    assert (nothing["model"], nothing["source"], nothing["differs"]) == (None, None, False)


@pytest.mark.parametrize("info, billed", [
    ({"status": "allowed"}, False),
    ({"status": "rejected", "errorCode": "credits_required", "canUserPurchaseCredits": True}, False),
    ({"status": "rejected", "overageStatus": "allowed"}, True),
    ({"status": "rejected", "overageStatus": "allowed_warning"}, True),
    ({"status": "rejected", "overageStatus": "rejected", "overageDisabledReason": "out_of_credits"}, False),
    ({"status": "allowed_warning", "isUsingOverage": True}, True),
    ({"status": "allowed", "isUsingOverage": False}, False),
    ("not a dict", False),
])
def test_billed_to_credits_reads_claude_codes_own_fields(info, billed):
    assert models.billed_to_credits(info) is billed


def test_the_credits_record_keeps_what_the_stream_said():
    found = models.credits_record(_stream(rate={"status": "rejected", "overageStatus": "allowed", "isUsingOverage": True,
                                                "resetsAt": 1, "rateLimitType": "seven_day"}))
    assert found == {"seen": True, "billed": True, "events": [{"status": "rejected", "overageStatus": "allowed",
                                                                "isUsingOverage": True, "rateLimitType": "seven_day"}]}
    assert models.credits_record(_stream()) == {"seen": False}
    assert models.credits_record(_stream(rate={"status": "allowed_warning"}))["billed"] is False


def test_codex_served_reads_the_header_line_and_never_sees_credits():
    choice = models.resolve(_task(), "chatgpt", kind="check", pins=PINS)
    found = models.codex_served("OpenAI Codex v0.162.1\n--------\nworkdir: /x\nmodel: gpt-6.1-sol\nprovider: openai\n", "", choice)
    assert (found["asked"], found["model"], found["source"], found["differs"], found["credits"]) == ("gpt-6.1-sol", "gpt-6.1-sol", "codex header", False, {"seen": False})
    other = models.codex_served("", "model: gpt-6.1-terra\n", choice)
    assert (other["model"], other["differs"]) == ("gpt-6.1-terra", True)
    none = models.codex_served("the answer", "", choice)
    assert (none["model"], none["source"]) == (None, None)


def test_asked_of_an_old_row_reads_sonnet_or_the_pin():
    assert models.asked_of({"agent": "claude"}, PINS) == "sonnet"
    assert models.asked_of({"agent": "chatgpt"}, PINS) == "gpt-6.1-sol"
    assert models.asked_of({"agent": "claude", "model": OPUS}, PINS) == OPUS
    assert models.asked_of({"agent": "grok"}, PINS) is None


def test_differs_note_names_both_models():
    call = {"agent": "claude", "model": FABLE, "served": json.dumps({"asked": FABLE, "model": "claude-opus-4-8"})}
    assert models.differs_note(call) == "Fable 5.1 re-ran this on claude-opus-4-8"
    assert models.differs_note({"agent": "claude", "model": SONNET, "served": json.dumps({"asked": SONNET, "model": SONNET})}) is None
    assert models.differs_note({"agent": "claude", "model": None, "served": None}) is None


# ---------- the writes (decision 3): set, clear, fable ----------

def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def test_set_default_writes_the_full_id_mode_600_and_keeps_the_rest(files):
    _, local = files
    entry = models.set_default({"skill": "code"}, "claude", model="opus")
    assert entry == {"model": OPUS} and _mode(local) == 0o600
    assert json.loads(local.read_text()) == {"skills": {"code": {"claude": {"model": OPUS}}}}
    models.set_default({"team": "plan", "role": "plan"}, "claude", model="fable")  # allowed while Fable is off
    models.set_default({"team": "redteam", "stage": 2}, "chatgpt", effort="ultra")
    models.set_default({"skill": "code"}, "claude", effort="high")  # the model kept, the effort added
    doc = json.loads(local.read_text())
    assert doc["skills"]["code"]["claude"] == {"model": OPUS, "effort": "high"}
    assert doc["roles"]["plan.plan"]["claude"] == {"model": FABLE} and doc["stages"]["redteam.2"]["chatgpt"] == {"effort": "ultra"}
    assert [p.name for p in local.parent.iterdir() if "models" in p.name] == ["models.local.json"]  # no temp file left


def test_set_default_refuses_with_nothing_written(files):
    _, local = files
    for selector, agent, kw, code in (({"skill": "code"}, "claude", {"model": "gpt-6.1-sol"}, "bad_model"),
                                      ({"skill": "code"}, "grok", {"model": "x"}, "bad_model"),
                                      ({"skill": "code"}, "claude", {}, "usage"),
                                      ({"skill": "code"}, "chatgpt", {"effort": "turbo"}, "bad_model")):
        with pytest.raises(models.ModelsError) as err:
            models.set_default(selector, agent, **kw)
        assert err.value.code == code
    assert not local.exists()
    local.write_text("[]")
    with pytest.raises(models.ModelsError) as err:
        models.set_default({"skill": "code"}, "claude", model="opus")
    assert err.value.code == "setup" and local.read_text() == "[]"


def test_clear_default_takes_the_entry_out_and_empties_its_key(files):
    _, local = files
    models.set_default({"skill": "code"}, "claude", model="opus")
    models.set_default({"skill": "code"}, "chatgpt", model="gpt-6-astra")
    assert models.clear_default({"skill": "code"}, "claude") is True
    assert json.loads(local.read_text()) == {"skills": {"code": {"chatgpt": {"model": "gpt-6-astra"}}}}
    assert models.clear_default({"skill": "code"}, "chatgpt") is True and json.loads(local.read_text()) == {}
    assert models.clear_default({"skill": "code"}, "claude") is False


def test_the_fable_switch_is_one_key_with_when_and_by_whom(files):
    _, local = files
    assert models.local().fable_on is False
    assert models.set_fable(True) == (False, True)
    assert models.local().fable == {"on": True, "changed_at": json.loads(local.read_text())["fable"]["changed_at"], "off_by": None}
    assert models.set_fable(False, by=models.CREDITS_TURNED_OFF) == (True, False)
    assert models.local().fable["off_by"] == "credits" and models.local().fable_on is False
    models.set_default({"skill": "code"}, "claude", model="opus")
    assert json.loads(local.read_text())["fable"]["on"] is False  # a set keeps the switch


def test_check_selector_names_the_shapes_and_refuses_the_rest():
    skills, teams = ("code", "writing"), ("research-build", "redteam")
    assert models.check_selector({"skill": "code"}, skills=skills, teams=teams) == {"skill": "code"}
    assert models.check_selector({"team": "file", "role": "build"}, skills=skills, teams=teams) == {"team": "file", "role": "build"}
    assert models.check_selector({"team": "redteam", "stage": "2"}, skills=skills, teams=teams, stages={"redteam": 4}) == {"team": "redteam", "stage": 2}
    for selector, code in (({"skill": "nope"}, "bad_model"), ({"team": "nope", "role": "build"}, "bad_model"),
                           ({"team": "redteam", "role": "paint"}, "bad_model"), ({"team": "redteam", "stage": 9}, "bad_model"),
                           ({"team": "file", "stage": 1}, "bad_model"), ({"skill": "code", "team": "x"}, "usage"),
                           ({"team": "redteam"}, "usage"), ({"team": "redteam", "role": "build", "stage": 1}, "usage"),
                           ({}, "usage"), ({"team": "redteam", "stage": "two"}, "usage")):
        with pytest.raises(models.ModelsError) as err:
            models.check_selector(selector, skills=skills, teams=teams, stages={"redteam": 4})
        assert err.value.code == code, selector


# ---------- the views (decisions 3 and 11) ----------

def test_the_view_lists_each_layer_with_its_file_and_the_lines_read_it(files):
    models.set_default({"skill": "code"}, "claude", model="opus")
    doc = models.view(pins=PINS)
    assert doc["agents"]["claude"]["default"] == SONNET and doc["agents"]["claude"]["file"] == "config/models.json"
    assert doc["agents"]["chatgpt"]["default"] == "gpt-6.1-sol" and doc["agents"]["chatgpt"]["file"] == "config/agents.json"
    assert doc["layers"] == [{"layer": "skill", "key": "code", "agent": "claude", "model": OPUS, "name": "Opus 5.5",
                              "effort": None, "file": "config/models.local.json"}]
    assert doc["fable"]["on"] is False and doc["fable"]["words"] == models.FABLE_WORDS and doc["problems"] == []
    text = "\n".join(models.lines(doc))
    assert "claude: Sonnet 5.5 (claude-sonnet-5-5) · config/models.json" in text
    assert "skill code: Opus 5.5 (claude-opus-5-5) · config/models.local.json" in text
    assert "Fable: off; a Fable default runs on Opus 5.5 (sr models fable on)" in text


def test_the_week_counts_go_by_the_served_model_then_the_asked_one():
    conn = log.init_db(":memory:")
    conn.execute("INSERT INTO tasks (task_id, created_at, updated_at, source, task, jev_status, status) VALUES "
                 "('sr-a', '2026-10-28T00:00:00+00:00', '2026-10-28T00:00:00+00:00', 'cli', 't', 'ok', 'done')")
    rows = [("c1", json.dumps({"asked": FABLE, "model": "claude-opus-4-8"}), FABLE, "2026-10-28T10:00:00+00:00"),
            ("c2", json.dumps({"asked": OPUS, "model": OPUS}), OPUS, "2026-10-28T11:00:00+00:00"),
            ("c3", None, None, "2026-10-28T12:00:00+00:00"),  # an old row: sonnet
            ("c4", json.dumps({"asked": FABLE, "model": None}), FABLE, "2026-10-28T13:00:00+00:00"),
            ("c5", json.dumps({"asked": OPUS, "model": OPUS}), OPUS, "2026-10-20T13:00:00+00:00")]  # last week
    for cid, served, model, sent in rows:  # the served record alone: log 20's `model` column is read when it is there
        conn.execute("INSERT INTO calls (call_id, task_id, kind, agent, status, sent_at, served) VALUES (?, 'sr-a', 'do', "
                     "'claude', 'done', ?, ?)", (cid, sent, served))
    assert models.claude_calls_this_week(conn, "2026-10-26T00:00:00+00:00") == (2, 1)
    assert models.claude_calls_this_week(None, "x") == (0, 0)
