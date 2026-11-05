"""Models (rules 2.48, Models; build brief 33.3, decisions 1 to 11): which model each agent's call asks for, where the
defaults live, the allowlists, the Fable switch, the time limits, the effort levels, and what a call's stream said
about the model that answered and about usage credits.

The layers (decision 1), the first that applies to a call: the task's own choice (`--model <agent>=<model>`, on the
task row; never on a takeover's call); the team's stage (`<team>.<n>`); the team's role (`<team>.<role>`); the
file-mode role (`file.<role>`, a relay or split task in file mode); the skill (a routed task's do and fix); the agent's
default (Claude's from the tracked file, ChatGPT's and Cursor's their pins in config/agents.json). Effort rides the same
layers, with no default of its own.

Two files. `config/models.json` (tracked; only the owner edits it) holds the public defaults: each agent's allowlist,
aliases and display names, Claude's default, the time limits and the effort levels; it carries no per-skill or per-stage
default, so a clone runs Sonnet everywhere. `config/models.local.json` (gitignored, mode 600) holds the owner's own
defaults and the Fable switch, written by `sr models` alone (a temp file and a rename, under the `models` lock), never by
hand from the page. A name off its agent's allowlist is refused on a task and in `sr models set`, and a local entry
naming one is ignored at load with why (`problems`).

Fable (decision 6): off until the owner turns it on; while it is off a Fable default falls back to Opus 5.5 (the choice
says so) and a typed Fable is refused. A Claude stream whose rate-limit event marks the call billed to usage credits
(`isUsingOverage`, or `rejected` with an overage status that lets it through) stops the task and turns Fable off
(`credits`)."""
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from router import locks, log, safety

TRACKED_PATH = safety.REPO_ROOT / "config" / "models.json"         # the owner's; tests point this elsewhere
LOCAL_PATH = safety.REPO_ROOT / "config" / "models.local.json"     # gitignored; tests point this elsewhere too
TRACKED_NAME, LOCAL_NAME, AGENTS_NAME = "config/models.json", "config/models.local.json", "config/agents.json"
TASK_FILE = "the task"  # a choice's `file` when it came from `--model` on the task
LOCK = "models"
AGENTS = ("claude", "chatgpt", "cursor")   # the agents with a model choice; Grok Bot and Jev have none (decision 2)
NO_CHOICE = {"grok": "Grok Bot has no model choice: its service picks", "jev": "Jev has no model choice: its service picks",
             "muse": "Muse is deferred and has no model choice"}
LAYERS = ("task", "stage", "role", "file", "skill", "agent")
# Decision 2: a routed task in file mode builds in its copy (its do and fix calls), so it reads the file-mode defaults,
# except the skills that research and never build: a routed recall or web_research doer on a project keeps Sonnet, and a
# quick answer stays on its own default (the social and media skills are Grok Bot's)
NO_FILE_SKILLS = ("quick_answer", "recall", "web_research", "x_social_pulse", "meta_social_trends", "make_media")
TEAMS_FIXED = ("route", "split", "plan", "file")  # `file`: any relay or split task in file mode (decision 2)
ROLE_WORDS = ("build", "fix", "check", "plan", "revise", "execute", "amend", "edit", "research", "attack", "review",
              "vote", "integrate")
WORDS_BY_KIND = {"do": "build", "fix": "fix", "check": "check", "recheck": "check"}
ROLE_ALIASES = {"split_plan": "plan"}  # a split's plan call reads as the role word `plan`
FABLE = "claude-fable-5-1"
FABLE_FALLBACK = "claude-opus-5-5"   # decision 6: while Fable is off, a Fable default falls back to Opus
FABLE_WORDS = ("Fable 5.1 can charge usage credits once you've used half your weekly limit on it, and the router's "
               "Claude calls pay them without asking. Turn this on only if usage credits are off on your account.")
FABLE_OFF_NOTE = "Fable is off: Opus 5.5 instead"   # the card's note when a Fable default fell back
FABLE_OFF_REFUSAL = "Fable is off: turn it on in Setup (sr models fable on) once usage credits are off on your account"
CREDITS = "credits"                  # the reason code: a call's stream marked it billed to usage credits
CREDITS_TURNED_OFF = "credits"       # the local file's `off_by` when the router turned Fable off
DEFAULT_TIMEOUT = 600
OLD_ASKED = {"claude": "sonnet"}      # decision 7: a Claude row from before log 20 asked for `sonnet`; the others their pins
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_KEY = re.compile(r"[a-z][a-z0-9_-]*")


class ModelsError(safety.SafeError):
    """A refusal with its reason code: `bad_model` for a model, agent or level that can't be used; `setup` for a file
    the router can't read or write."""

    def __init__(self, message, code="bad_model"):
        super().__init__(message)
        self.code = code


# ---------- the tracked file ----------

@dataclass(frozen=True)
class Tracked:
    doc: dict
    problems: tuple = ()

    def agent(self, name):
        found = (self.doc.get("agents") or {}).get(name)
        return found if isinstance(found, dict) else {}

    def allowed(self, name):
        return [m for m in self.agent(name).get("allowed") or [] if isinstance(m, str)]

    def aliases(self, name):
        found = self.agent(name).get("aliases") or {}
        return {k: v for k, v in found.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(found, dict) else {}

    def names(self, name):
        found = self.agent(name).get("names") or {}
        return found if isinstance(found, dict) else {}

    def gated(self, name):
        return [m for m in self.agent(name).get("gated") or [] if isinstance(m, str)]

    def efforts(self, name):
        return [e for e in self.agent(name).get("efforts") or [] if isinstance(e, str)]

    def default(self, name):
        found = self.agent(name).get("default")
        return found if isinstance(found, str) and found else None

    def timeout(self, name, model):
        found = self.agent(name).get("timeouts") or {}
        if not isinstance(found, dict):
            return DEFAULT_TIMEOUT
        value = found.get(model) if model else None
        value = value if _seconds(value) else found.get("default")
        return value if _seconds(value) else DEFAULT_TIMEOUT

    def display(self, name, model):
        """The display name of a model id, or the id (an alias becomes its id's name)."""
        if model is None:
            return None
        model = self.aliases(name).get(model, model)
        return self.names(name).get(model) or model


def _seconds(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return False


def tracked_problems(doc):
    """What is wrong with the tracked file, as plain sentences; [] means OK."""
    if not isinstance(doc, dict) or not isinstance(doc.get("agents"), dict):
        return [f"{TRACKED_NAME} has no agents"]
    found = []
    for name in AGENTS:
        entry = doc["agents"].get(name)
        if not isinstance(entry, dict):
            found.append(f"{TRACKED_NAME}: no entry for {name}")
            continue
        allowed = entry.get("allowed")
        if not isinstance(allowed, list) or not allowed or not all(isinstance(m, str) and _ID.fullmatch(m) for m in allowed):
            found.append(f"{TRACKED_NAME}: {name}'s allowed list must name at least one model")
            continue
        if name == "claude":
            default = entry.get("default")
            if default not in allowed:
                found.append(f"{TRACKED_NAME}: claude's default must be on its allowed list")
            for alias, model in (entry.get("aliases") or {}).items():
                if model not in allowed:
                    found.append(f"{TRACKED_NAME}: claude's alias {alias} names {model}, which isn't on its allowed list")
        if name == "cursor" and any(m == "auto" or not re.fullmatch(r"(?:cursor-)?grok[-.0-9a-z]*", m) for m in allowed):
            found.append(f"{TRACKED_NAME}: cursor's allowed list holds a model that isn't a pinned Grok model")
        for model in entry.get("gated") or []:
            if model not in allowed:
                found.append(f"{TRACKED_NAME}: {name}'s gated list names {model}, which isn't on its allowed list")
        timeouts = entry.get("timeouts")
        if timeouts is not None and (not isinstance(timeouts, dict) or not all(_seconds(v) for v in timeouts.values())):
            found.append(f"{TRACKED_NAME}: {name}'s timeouts must be whole seconds above 0")
    return found


def tracked(path=None):
    """The tracked file as the router reads it, with its problems (a bad file is read as empty: every agent keeps its pin
    or `sonnet`, and status says why)."""
    doc = _load(path or TRACKED_PATH)
    if doc is None:
        return Tracked({}, (f"{TRACKED_NAME} is missing",))
    if doc is False:
        return Tracked({}, (f"{TRACKED_NAME} could not be read as JSON",))
    problems = tracked_problems(doc)
    return Tracked(doc if not problems else {}, tuple(problems))


# ---------- the local file ----------

@dataclass(frozen=True)
class Local:
    doc: dict
    problems: tuple = ()  # entries ignored at load, each named, never the whole file dropped for one bad entry
    missing: bool = False

    @property
    def fable_on(self):
        fable = self.doc.get("fable")
        return bool(fable.get("on")) if isinstance(fable, dict) else fable is True

    @property
    def fable(self):
        found = self.doc.get("fable")
        found = dict(found) if isinstance(found, dict) else {"on": found is True}
        return {"on": bool(found.get("on")), "changed_at": found.get("changed_at"), "off_by": found.get("off_by")}

    def entry(self, section, key, agent):
        found = ((self.doc.get(section) or {}).get(key) or {}).get(agent) if isinstance(self.doc.get(section), dict) else None
        return found if isinstance(found, dict) else None

    def entries(self):
        """Every (section, key, agent, entry) in file order."""
        for section in ("skills", "roles", "stages"):
            table = self.doc.get(section)
            if not isinstance(table, dict):
                continue
            for key, agents in table.items():
                if isinstance(agents, dict):
                    for agent, entry in agents.items():
                        if isinstance(entry, dict):
                            yield section, key, agent, entry


def _section_of(selector):
    """The local file's section and key for a selector: {"skill": k} | {"team": t, "role": r} | {"team": t, "stage": n}."""
    if selector.get("skill") is not None:
        return "skills", selector["skill"]
    if selector.get("stage") is not None:
        return "stages", f"{selector['team']}.{int(selector['stage'])}"
    return "roles", f"{selector['team']}.{selector['role']}"


def _clean(doc, found):
    """The local document with every entry that can't be used taken out, and why, one line each (decision 5)."""
    problems = []
    if not isinstance(doc, dict):
        return {}, [f"{LOCAL_NAME} is not a JSON object; every layer in it is ignored"]
    out = {}
    fable = doc.get("fable")
    if fable is not None:
        if isinstance(fable, dict) or isinstance(fable, bool):
            out["fable"] = fable
        else:
            problems.append(f"{LOCAL_NAME}: fable must be on or off; read as off")
    for section in ("skills", "roles", "stages"):
        table = doc.get(section)
        if table is None:
            continue
        if not isinstance(table, dict):
            problems.append(f"{LOCAL_NAME}: {section} must map keys to agents; ignored")
            continue
        kept = {}
        for key, agents in table.items():
            if not isinstance(agents, dict):
                problems.append(f"{LOCAL_NAME}: {section}.{key} must map agents to entries; ignored")
                continue
            for agent, entry in agents.items():
                if agent not in AGENTS:
                    problems.append(f"{LOCAL_NAME}: {section}.{key} names {agent}, which has no model choice; ignored")
                    continue
                if not isinstance(entry, dict):
                    problems.append(f"{LOCAL_NAME}: {section}.{key}.{agent} must be an entry (model, effort); ignored")
                    continue
                model, effort = entry.get("model"), entry.get("effort")
                clean = {}
                if model is not None:
                    canon, why = canonical(agent, model, found)
                    if canon is None:
                        problems.append(f"{LOCAL_NAME}: {section}.{key}.{agent}: {why}; its model is ignored")
                    else:
                        clean["model"] = canon
                if effort is not None:
                    if effort in found.efforts(agent):
                        clean["effort"] = effort
                    else:
                        problems.append(f"{LOCAL_NAME}: {section}.{key}.{agent}: {effort!r} isn't one of {agent}'s effort "
                                        f"levels ({', '.join(found.efforts(agent)) or 'none'}); its effort is ignored")
                if clean:
                    kept.setdefault(key, {})[agent] = clean
        if kept:
            out[section] = kept
    return out, problems


def local(path=None, found=None):
    """The local file as the router reads it: the entries that can be used, the rest named in `problems`."""
    found = found or tracked()
    doc = _load(path or LOCAL_PATH)
    if doc is None:
        return Local({}, (), missing=True)
    if doc is False:
        return Local({}, (f"{LOCAL_NAME} could not be read as JSON; every layer in it is ignored",))
    clean, problems = _clean(doc, found)
    return Local(clean, tuple(problems))


# ---------- names, aliases and allowlists (decision 5) ----------

def canonical(agent, name, found=None):
    """(the full id a name means on `agent`'s allowlist, None), or (None, why not). An alias becomes its id; a pin that
    config/agents.json names is `pins`' to allow (resolve passes it); Fable's gate is checked apart (check_choice)."""
    found = found or tracked()
    if agent not in AGENTS:
        return None, NO_CHOICE.get(agent, f"{agent} has no model choice")
    if not isinstance(name, str) or not name.strip():
        return None, f"{agent}'s model must be a name"
    name = name.strip()
    model = found.aliases(agent).get(name, name)
    allowed = found.allowed(agent)
    if model not in allowed:
        listed = ", ".join(allowed) if allowed else f"none ({TRACKED_NAME} is unreadable)"
        return None, f"{name} isn't on {agent}'s allowed list ({listed})"
    return model, None


def check_choice(agent, name, *, fable_on, found=None):
    """Intake's check of one `--model <agent>=<name>` (decision 4): (id, None) or (None, why). Fable while off is refused."""
    found = found or tracked()
    model, why = canonical(agent, name, found)
    if model is None:
        return None, why
    if model in found.gated(agent) and not fable_on:
        return None, FABLE_OFF_REFUSAL
    return model, None


def check_effort(agent, level, found=None):
    found = found or tracked()
    if agent not in AGENTS:
        return None, NO_CHOICE.get(agent, f"{agent} has no model choice")
    levels = found.efforts(agent)
    if not isinstance(level, str) or level.strip() not in levels:
        return None, f"{level!r} isn't one of {agent}'s effort levels ({', '.join(levels) or 'none'})"
    return level.strip(), None


def parse_flag(value, what="--model"):
    """`<agent>=<name>` as (agent, name); ModelsError (`usage`) for any other shape."""
    if not isinstance(value, str) or value.count("=") != 1 or not all(value.split("=")):
        raise ModelsError(f"{what} takes <agent>=<name>, not {str(value)[:60]!r}", code="usage")
    agent, name = value.split("=", 1)
    return agent.strip().lower(), name.strip()


def choices_from_flags(models=(), efforts=(), *, agents_allowed, fable_on, found=None):
    """The task's own choices from its `--model` and `--effort` flags (decision 4): {agent: {"model", "effort"}}.
    `agents_allowed` is a function of an agent's name giving (True, None) or (False, why) for this task. Raises
    ModelsError with `usage` (a doubled agent, a bad shape) or `bad_model` (an agent that can't make a call here, a model
    off its allowlist, Fable while off, a level the agent doesn't take)."""
    found = found or tracked()
    out = {}
    seen = set()
    for value in models or ():
        agent, name = parse_flag(value, "--model")
        if agent in seen:
            raise ModelsError(f"--model names {agent} twice: each agent at most once", code="usage")
        seen.add(agent)
        if agent not in AGENTS:
            raise ModelsError(f"--model {agent}: {NO_CHOICE.get(agent, f'{agent} has no model choice')}")
        ok, why = agents_allowed(agent)
        if not ok:
            raise ModelsError(f"--model {agent}: {why}")
        model, why = check_choice(agent, name, fable_on=fable_on, found=found)
        if model is None:
            raise ModelsError(f"--model {agent}: {why}")
        out.setdefault(agent, {"model": None, "effort": None})["model"] = model
    seen = set()
    for value in efforts or ():
        agent, level = parse_flag(value, "--effort")
        if agent in seen:
            raise ModelsError(f"--effort names {agent} twice: each agent at most once", code="usage")
        seen.add(agent)
        if agent not in AGENTS:
            raise ModelsError(f"--effort {agent}: {NO_CHOICE.get(agent, f'{agent} has no model choice')}")
        ok, why = agents_allowed(agent)
        if not ok:
            raise ModelsError(f"--effort {agent}: {why}")
        level, why = check_effort(agent, level, found)
        if level is None:
            raise ModelsError(f"--effort {agent}: {why}")
        out.setdefault(agent, {"model": None, "effort": None})["effort"] = level
    return out


# ---------- the resolution (decision 1) ----------

@dataclass(frozen=True)
class Choice:
    agent: str
    model: str | None          # the model asked for (None for an agent with no choice)
    effort: str | None = None
    timeout: int = DEFAULT_TIMEOUT
    layer: str = "agent"       # which layer set the model
    key: str | None = None     # the layer's key (`code`, `redteam.2`, `plan.plan`, `file.build`)
    file: str | None = None    # where the model came from
    name: str | None = None    # the model's display name
    note: str | None = None    # "Fable is off: Opus 5.5 instead" when a Fable default fell back
    effort_layer: str | None = None
    effort_key: str | None = None

    def record(self):
        """The call row's served record's own part: what was asked and where it came from (decision 7)."""
        return {"asked": self.model, "layer": self.layer, "key": self.key, "file": self.file, "note": self.note,
                "effort": self.effort, "time_limit": self.timeout}


def word_of(kind, role=None):
    """The role word a call reads the layers with: a stage's role (`split_plan` as `plan`), else the kind's word."""
    if kind in log.STAGE_KINDS and role:
        return ROLE_ALIASES.get(role, role)
    return WORDS_BY_KIND.get(kind)


def team_of(task):
    mode = task["mode"] if "mode" in task.keys() and task["mode"] else "route"
    if mode == "plan":
        return "plan"
    if mode == "split":
        return "split"
    if mode == "relay":
        return task["preset"] if "preset" in task.keys() and task["preset"] else "relay"
    return "route"


def models_of(task):
    """A task's own choices (decision 4, `tasks.models`), or {} (a row from before log 20 too)."""
    try:
        raw = task["models"]
    except (KeyError, IndexError):
        return {}
    found = json.loads(raw) if raw else {}
    return found if isinstance(found, dict) else {}


def file_mode_on(task):
    found = log.project_files_of(task) if "project_files" in task.keys() else None
    return bool(found) and found.get("mode") == "on"


def _candidates(task, agent, kind, stage, role, takeover, local_doc):
    """The layers' entries for this call, in order: (layer, key, entry)."""
    mode = task["mode"] if "mode" in task.keys() and task["mode"] else "route"
    team, word = team_of(task), word_of(kind, role)
    found = []
    if not takeover:
        own = models_of(task).get(agent)
        if isinstance(own, dict):
            found.append(("task", None, own))
    if mode in ("relay", "plan") and stage:
        entry = local_doc.entry("stages", f"{team}.{stage}", agent)
        if entry:
            found.append(("stage", f"{team}.{stage}", entry))
    if word:
        entry = local_doc.entry("roles", f"{team}.{word}", agent)
        if entry:
            found.append(("role", f"{team}.{word}", entry))
        skill_now = task["skill"] if "skill" in task.keys() else None
        builds = mode in ("relay", "split") or (mode in ("route", "piece") and kind in ("do", "fix")
                                                 and skill_now not in NO_FILE_SKILLS)
        if builds and file_mode_on(task):  # decision 2: file-mode builds, a plan's routed steps included
            entry = local_doc.entry("roles", f"file.{word}", agent)
            if entry:
                found.append(("file", f"file.{word}", entry))
    skill = task["skill"] if "skill" in task.keys() else None
    if mode in ("route", "piece") and kind in ("do", "fix") and skill:
        entry = local_doc.entry("skills", skill, agent)
        if entry:
            found.append(("skill", skill, entry))
    return found


def _file_of(layer):
    return TASK_FILE if layer == "task" else LOCAL_NAME


def resolve(task, agent, *, kind=None, stage=None, role=None, takeover=False, found=None, local_doc=None, pins=None):
    """The model, effort and time limit of one call by `agent` on `task` (decision 1). `pins` is {agent: model} from
    config/agents.json (ChatGPT's and Cursor's defaults). A layer naming a model off the allowlist was dropped at load;
    the task's own choice is checked again here (a row from before the allowlist changed). Fable while off becomes Opus
    with the note. Grok and Jev get a Choice with no model."""
    found = found or tracked()
    local_doc = local_doc or local(found=found)
    pins = pins or {}
    if agent not in AGENTS:
        return Choice(agent, None, timeout=found.timeout(agent, None), layer="agent", file=None, name=None,
                      note=NO_CHOICE.get(agent))
    model = layer = key = note = None
    effort = effort_layer = effort_key = None
    for layer_name, layer_key, entry in _candidates(task, agent, kind, stage, role, takeover, local_doc):
        if model is None and entry.get("model"):
            canon, _ = canonical(agent, entry["model"], found)
            if canon is not None:
                model, layer, key = canon, layer_name, layer_key
        if effort is None and entry.get("effort") in found.efforts(agent):
            effort, effort_layer, effort_key = entry["effort"], layer_name, layer_key
    if model is None:
        if agent == "claude":
            model, layer, key = found.default("claude") or OLD_ASKED["claude"], "agent", None
        else:
            model, layer, key = pins.get(agent), "agent", None
    if model in found.gated(agent) and not local_doc.fable_on:
        model, note = FABLE_FALLBACK if agent == "claude" else model, FABLE_OFF_NOTE
    file = _file_of(layer) if layer != "agent" else (TRACKED_NAME if agent == "claude" else AGENTS_NAME)
    return Choice(agent, model, effort=effort, timeout=found.timeout(agent, model), layer=layer, key=key, file=file,
                  name=found.display(agent, model), note=note, effort_layer=effort_layer, effort_key=effort_key)


def asked_of(call, pins=None):
    """What a call row asked for (decision 7): its `model` column, else how its agent ran before log 20 (Claude `sonnet`,
    ChatGPT and Cursor their pins), else None."""
    model = call["model"] if "model" in call.keys() else None
    if model:
        return model
    agent = call["agent"]
    if agent == "claude":
        return OLD_ASKED["claude"]
    return (pins or {}).get(agent)


# ---------- the served record and the credits check (decisions 6 and 7) ----------

RATE_LIMIT_EVENT = "rate_limit_event"
OVERAGE_LETS_THROUGH = ("allowed", "allowed_warning")


def billed_to_credits(info):
    """Decision 6: whether a rate-limit event's `rate_limit_info` marks the call billed to usage credits: Claude Code's
    own `isUsingOverage`, or a `rejected` plan limit whose overage status lets the call through (paid extra usage covers
    the overflow). A `credits_required` rejection is the opposite: nothing ran and nothing was billed."""
    if not isinstance(info, dict):
        return False
    if info.get("isUsingOverage") is True:
        return True
    return info.get("status") == "rejected" and info.get("overageStatus") in OVERAGE_LETS_THROUGH


def credits_record(events):
    """What the stream said about usage credits: {"seen": False} with no rate-limit event; else the events' facts and
    whether any marked the call billed."""
    infos = [e.get("rate_limit_info") for e in events if isinstance(e, dict) and e.get("type") == RATE_LIMIT_EVENT]
    infos = [i for i in infos if isinstance(i, dict)]
    if not infos:
        return {"seen": False}
    kept = [{k: i.get(k) for k in ("status", "overageStatus", "isUsingOverage", "errorCode", "rateLimitType")
             if i.get(k) is not None} for i in infos]
    return {"seen": True, "billed": any(billed_to_credits(i) for i in infos), "events": kept[:5]}


def same_model(asked, served, found=None):
    """Whether a served id is the model asked for: the same id, a dated form of it, or its alias's id."""
    if not asked or not served:
        return False
    found = found or tracked()
    for agent in AGENTS:
        asked = found.aliases(agent).get(asked, asked)
    return served == asked or served.startswith(asked + "-") or asked.startswith(served + "-")


def claude_served(events, choice):
    """The served record of a Claude call from its stream (decision 7): the init event's model, the models that answered
    (the result event's modelUsage keys, the last one the model that answered), the credits facts, and the choice."""
    init = next((e for e in events if isinstance(e, dict) and e.get("type") == "system" and e.get("subtype") == "init"), None)
    result = next((e for e in reversed(events) if isinstance(e, dict) and e.get("type") == "result"), None)
    used = list(((result or {}).get("modelUsage") or {}).keys()) if isinstance((result or {}).get("modelUsage"), dict) else []
    init_model = (init or {}).get("model") if isinstance((init or {}).get("model"), str) else None
    # Cleanup 1 (2.3): Haiku beside another model is Claude Code's side job, never the model that answered
    answering = [name for name in used if "haiku" not in name.lower()] or used
    served = answering[-1] if answering else init_model
    record = {**choice.record(), "model": served, "init_model": init_model, "models_used": used,
              "source": "stream: init and modelUsage" if (init_model or used) else None,
              "effort_served": (init or {}).get("effort") if isinstance((init or {}).get("effort"), str) else None,
              "credits": credits_record(events)}
    record["differs"] = bool(served and choice.model and not same_model(choice.model, served))
    return record


_HEADER_MODEL = re.compile(r"^\s*model:\s*(\S+)\s*$", re.MULTILINE)


def codex_served(stdout, stderr, choice):
    """The served record of a ChatGPT call: the model Codex's own header printed (`model: <name>`), as reported; Codex's
    stream names no model that answered and no charge, so `credits` is never seen there."""
    text = f"{stdout or ''}\n{stderr or ''}"
    found = _HEADER_MODEL.search(text)
    served = found.group(1) if found else None
    record = {**choice.record(), "model": served, "source": "codex header" if served else None,
              "credits": {"seen": False}}
    record["differs"] = bool(served and choice.model and not same_model(choice.model, served))
    return record


def differs_note(call, pins=None, found=None):
    """The card's one-line note when a served model differs from the one asked (decision 7): `Fable re-ran this on Opus`."""
    if call["agent"] not in ("claude", "chatgpt"):  # Cursor's own check fails a call served by another model (brief 20)
        return None
    served = log.served_of(call)
    if not served or not served.get("model"):
        return None
    asked = served.get("asked") or asked_of(call, pins)
    if not asked or same_model(asked, served["model"], found):
        return None
    found = found or tracked()
    return f"{found.display(call['agent'], asked)} re-ran this on {found.display(call['agent'], served['model'])}"


# ---------- the local file's writes (decision 3): sr models set, clear, fable ----------

def _write_local(doc, path=None):
    path = Path(path or LOCAL_PATH)
    perms = stat.S_IMODE(os.stat(path).st_mode) if path.exists() else 0o600
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=str(path.parent), prefix=".models.local.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        os.chmod(temp, perms)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def _read_raw(path=None):
    """The local file's document as it is, for a write: {} when missing; ModelsError (`setup`) when it isn't an object."""
    doc = _load(path or LOCAL_PATH)
    if doc is None:
        return {}
    if doc is False or not isinstance(doc, dict):
        raise ModelsError(f"{LOCAL_NAME} is not a JSON object; fix or remove it first", code="setup")
    return doc


def check_selector(selector, *, skills=(), teams=(), stages=None):
    """A selector as `sr models set` takes it: {"skill": key} or {"team": name, "role": word} or {"team": name, "stage": n}.
    `skills` and `teams` are the names the router knows (the skill table's keys; the presets' names), `stages` {team:
    count}. ModelsError (`usage`, or `bad_model` for an unknown name)."""
    skill, team, role, stage = selector.get("skill"), selector.get("team"), selector.get("role"), selector.get("stage")
    if skill is not None and (team or role or stage is not None):
        raise ModelsError("--skill goes alone: a skill default, or --team with --role or --stage", code="usage")
    if skill is not None:
        if not isinstance(skill, str) or not _KEY.fullmatch(skill):
            raise ModelsError(f"a skill is a key from the skill table, not {str(skill)[:40]!r}", code="usage")
        if skills and skill not in skills:
            raise ModelsError(f"no skill {skill}; the skills are {', '.join(skills)}")
        return {"skill": skill}
    if not team:
        raise ModelsError("name a --skill, or a --team with --role or --stage", code="usage")
    if not isinstance(team, str) or not _KEY.fullmatch(team):
        raise ModelsError(f"a team is route, split, plan, file or a preset name, not {str(team)[:40]!r}", code="usage")
    known = tuple(TEAMS_FIXED) + tuple(teams)
    if team not in known:
        raise ModelsError(f"no team {team}; the teams are {', '.join(known)}")
    if (role is None) == (stage is None):
        raise ModelsError("a team default names one of --role or --stage", code="usage")
    if role is not None:
        if role not in ROLE_WORDS:
            raise ModelsError(f"no role {str(role)[:40]!r}; the roles are {', '.join(ROLE_WORDS)}")
        return {"team": team, "role": role}
    try:
        n = int(stage)
    except (TypeError, ValueError):
        raise ModelsError("--stage takes the stage's number", code="usage") from None
    if team in TEAMS_FIXED and team != "plan":
        raise ModelsError(f"{team} has no numbered stages: name a --role")
    most = (stages or {}).get(team)
    if n < 1 or (most is not None and n > most):
        raise ModelsError(f"{team} has no stage {n}" + (f" (it has {most})" if most else ""))
    return {"team": team, "stage": n}


def set_default(selector, agent, *, model=None, effort=None, found=None, path=None, lock_folder=None):
    """`sr models set`: one entry in the local file, the model stored as its full id (decision 3). Returns the entry as
    written. ModelsError for an agent with no choice, a model off the allowlist, a level the agent doesn't take, or
    nothing to set. A Fable default may be set while Fable is off (it falls back to Opus until it is on)."""
    found = found or tracked()
    if agent not in AGENTS:
        raise ModelsError(NO_CHOICE.get(agent, f"{agent} has no model choice"))
    if model is None and effort is None:
        raise ModelsError("give --model, --effort or both", code="usage")
    entry = {}
    if model is not None:
        canon, why = canonical(agent, model, found)
        if canon is None:
            raise ModelsError(why)
        entry["model"] = canon
    if effort is not None:
        level, why = check_effort(agent, effort, found)
        if level is None:
            raise ModelsError(why)
        entry["effort"] = level
    section, key = _section_of(selector)
    with locks.held(LOCK, folder=lock_folder):
        doc = _read_raw(path)
        table = doc.setdefault(section, {}) if isinstance(doc.get(section), dict) or section not in doc else None
        if table is None:
            raise ModelsError(f"{LOCAL_NAME}: {section} isn't an object; fix or remove it first", code="setup")
        agents = table.get(key) if isinstance(table.get(key), dict) else {}
        current = agents.get(agent) if isinstance(agents.get(agent), dict) else {}
        agents[agent] = {**current, **entry}
        table[key] = agents
        _write_local(doc, path)
    return agents[agent]


def clear_default(selector, agent, *, path=None, lock_folder=None):
    """`sr models clear`: the entry taken out (the key and section too when empty). Returns whether anything was there."""
    if agent not in AGENTS:
        raise ModelsError(NO_CHOICE.get(agent, f"{agent} has no model choice"))
    section, key = _section_of(selector)
    with locks.held(LOCK, folder=lock_folder):
        doc = _read_raw(path)
        table = doc.get(section)
        agents = table.get(key) if isinstance(table, dict) and isinstance(table.get(key), dict) else None
        if not agents or agent not in agents:
            return False
        del agents[agent]
        if not agents:
            del table[key]
        if not table:
            del doc[section]
        _write_local(doc, path)
    return True


def set_fable(on, *, by=None, now=None, path=None, lock_folder=None):
    """`sr models fable on|off` (decision 6), and the router's own off on a `credits` stop (`by`). Returns (was, now)."""
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")
    with locks.held(LOCK, folder=lock_folder):
        doc = _read_raw(path)
        fable = doc.get("fable")
        was = bool(fable.get("on")) if isinstance(fable, dict) else fable is True
        doc["fable"] = {"on": bool(on), "changed_at": stamp, "off_by": None if on else by}
        _write_local(doc, path)
    return was, bool(on)


# ---------- the views: `sr models --json` and status's `models` (decisions 3 and 11) ----------

def _entry_view(section, key, agent, entry, found):
    layer = {"skills": "skill", "roles": "role", "stages": "stage"}[section]
    model = entry.get("model")
    return {"layer": layer, "key": key, "agent": agent, "model": model, "name": found.display(agent, model) if model else None,
            "effort": entry.get("effort"), "file": LOCAL_NAME}


def view(found=None, local_doc=None, pins=None):
    """The defaults in effect, each with its layer and file (decision 3): the document `sr models --json` prints and
    status's `models` is built from."""
    found = found or tracked()
    local_doc = local_doc or local(found=found)
    pins = pins or {}
    agents = {}
    for name in AGENTS:
        default = found.default("claude") if name == "claude" else pins.get(name)
        agents[name] = {"default": default, "name": found.display(name, default) if default else None,
                        "file": TRACKED_NAME if name == "claude" else AGENTS_NAME,
                        "allowed": found.allowed(name), "aliases": found.aliases(name), "names": found.names(name),
                        "gated": found.gated(name), "efforts": found.efforts(name),
                        "timeouts": {m: found.timeout(name, m) for m in found.allowed(name)}}
    fable = local_doc.fable
    return {"agents": agents,
            "fable": {**fable, "words": FABLE_WORDS, "fallback": FABLE_FALLBACK,
                      "fallback_name": found.display("claude", FABLE_FALLBACK)},
            "layers": [_entry_view(s, k, a, e, found) for s, k, a, e in local_doc.entries()],
            "problems": list(found.problems) + list(local_doc.problems),
            "files": {"tracked": TRACKED_NAME, "local": LOCAL_NAME, "local_present": not local_doc.missing}}


def family(model):
    """`opus`, `fable`, `sonnet`, `haiku` or None, from an id or an alias (decision 11's counts go by family)."""
    if not isinstance(model, str):
        return None
    for word in ("fable", "opus", "sonnet", "haiku"):
        if word in model.lower():
            return word
    return None


def claude_calls_this_week(conn, since):
    """(opus, fable): Claude's call rows since `since` by the model that answered, the one asked when that is unknown
    (decision 11); calls, never tokens."""
    if conn is None:
        return 0, 0
    counts = {"opus": 0, "fable": 0}
    columns = [r[1] for r in conn.execute("PRAGMA table_info(calls)")]
    column = "model" if "model" in columns else "NULL AS model"
    for row in conn.execute(f"SELECT served, {column} FROM calls WHERE agent = 'claude' AND sent_at >= ?", (since,)):
        served = json.loads(row[0]) if row[0] else {}
        model = (served or {}).get("model") or (served or {}).get("asked") or row[1] or OLD_ASKED["claude"]
        kind = family(model)
        if kind in counts:
            counts[kind] += 1
    return counts["opus"], counts["fable"]


def lines(doc):
    """`sr models` without --json: the same document, a few lines a person reads."""
    out = [f"Models ({doc['files']['tracked']}, {doc['files']['local']}{'' if doc['files']['local_present'] else ' (not made yet)'}):"]
    for name, agent in doc["agents"].items():
        default = f"{agent['name']} ({agent['default']})" if agent["default"] else "no default"
        out.append(f"  {name}: {default} · {agent['file']}")
        for layer in doc["layers"]:
            if layer["agent"] != name:
                continue
            what = f"{layer['name']} ({layer['model']})" if layer["model"] else "no model"
            effort = f", effort {layer['effort']}" if layer["effort"] else ""
            out.append(f"    {layer['layer']} {layer['key']}: {what}{effort} · {layer['file']}")
    fable = doc["fable"]
    out.append(f"  Fable: {'on' if fable['on'] else 'off'}" + (f" (turned off by the router: {fable['off_by']})"
                                                               if not fable["on"] and fable.get("off_by") else "")
               + ("" if fable["on"] else f"; a Fable default runs on {fable['fallback_name']} (sr models fable on)"))
    for problem in doc["problems"]:
        out.append(f"  ignored: {problem}")
    return out


# ---------- what each role would use now (decision 11): status's `models.now` and Setup's matrix ----------

def _fake_task(mode="route", preset=None, skill=None, file_mode=False):
    files = json.dumps({"mode": "on", "state": "none", "copy": True}) if file_mode else None
    return {"mode": mode, "preset": preset, "skill": skill, "models": None, "project_files": files, "task_id": "now"}


def _entry(choice, **extra):
    return {"agent": choice.agent, "model": choice.model, "name": choice.name, "layer": choice.layer, "key": choice.key,
            "effort": choice.effort, "note": choice.note, **extra}


def _chain_now(name, preset, found, local_doc, pins, file_mode=False):
    """A preset's stages and its checker, each with the model its agent would use now."""
    task = _fake_task("relay" if name not in ("plan", "split") else name, preset=name, file_mode=file_mode)
    rows = []
    for stage in preset.stages:
        choice = resolve(task, stage.agent, kind="stage", stage=stage.n, role=stage.role, found=found, local_doc=local_doc, pins=pins)
        rows.append(_entry(choice, stage=stage.n, role=stage.role))
    if preset.check_agent and preset.check_stage is None:
        choice = resolve(task, preset.check_agent, kind="check", found=found, local_doc=local_doc, pins=pins)
        rows.append(_entry(choice, stage=None, role="check"))
    return rows


def now_view(found, local_doc, roster, loaded, table, *, send_paths, pins, skills_now=None):
    """Per team and per skill the model each role would use now (decision 11), so the page never works one out.
    `table` is an availability function (the fills follow it); `skills_now` {key: {doer, checker}} from routing.now_for."""
    from router import plan as plan_mod, presets, split, teams  # they read this module's neighbours; kept local
    out = {"teams": {}, "skills": {}, "file": {}}
    if loaded is not None and roster is not None:
        for name, preset in loaded.presets.items():
            filled, _ = teams.filled(preset, roster, table, send_paths=send_paths)
            shown = filled or preset
            out["teams"][name] = _chain_now(name, shown, found, local_doc, pins)
        base = loaded.presets.get(plan_mod.PRESET)
        if base is not None:
            filled, _ = teams.filled(base, roster, table, send_paths=send_paths)
            shown = presets.plan_shape(filled or base)
            out["teams"]["plan"] = _chain_now("plan", shown, found, local_doc, pins)
    task = _fake_task("split")
    out["teams"]["split"] = [
        _entry(resolve(task, split.PLANNER, kind="stage", stage=1, role=split.PLAN_ROLE, found=found, local_doc=local_doc, pins=pins), stage=1, role="plan"),
        _entry(resolve(task, split.PLANNER, kind="stage", stage=2, role=split.INTEGRATE_ROLE, found=found, local_doc=local_doc, pins=pins), stage=2, role="integrate"),
        _entry(resolve(task, split.CHECKER, kind="check", found=found, local_doc=local_doc, pins=pins), stage=None, role="check")]
    out["project_skills"] = {}  # decision 2: the same on a project in file mode (the doer builds in the copy)
    for key, now in (skills_now or {}).items():
        for name, on_project in (("skills", False), ("project_skills", True)):
            task = _fake_task("route", skill=key, file_mode=on_project)
            entry = {}
            if now.get("doer"):
                entry["do"] = _entry(resolve(task, now["doer"], kind="do", found=found, local_doc=local_doc, pins=pins))
            if now.get("checker"):
                entry["check"] = _entry(resolve(task, now["checker"], kind="check", found=found, local_doc=local_doc, pins=pins))
            out[name][key] = entry
    file_task = _fake_task("relay", preset="any", file_mode=True)
    for role in ("build", "revise", "execute", "fix", "integrate"):
        kind = "fix" if role == "fix" else "stage"
        choice = resolve(file_task, "claude", kind=kind, stage=None if kind == "fix" else 1, role=None if kind == "fix" else role,
                         found=found, local_doc=local_doc, pins=pins)
        out["file"][role] = _entry(choice)
    return out


# The roles each team's calls can have, with the agent that makes them as the chain is filled now, for Setup's selects
# (decision 12): read from `now` so nothing here types a chain.
def setup_rows(now, local_doc, found, skills=(), skills_now=None):
    """Setup's Models row (decision 12): one row per skill (its doer's do and fix calls, the doer as the skill table
    picks it now), one per team, role and agent, and one per numbered stage of a preset (and of a plan), each with the
    local default in force (model, effort) or none."""
    rows = {"skills": [], "roles": [], "stages": []}
    for key in skills:
        doer = ((skills_now or {}).get(key) or {}).get("doer")
        agent = doer if doer in AGENTS else "claude"
        entry = local_doc.entry("skills", key, agent) or {}
        rows["skills"].append({"key": key, "agent": agent, "model": entry.get("model"), "effort": entry.get("effort"),
                               "name": found.display(agent, entry.get("model")) if entry.get("model") else None})
    for team, entries in (now.get("teams") or {}).items():
        if team in TEAMS_FIXED and team != "plan":  # route, split and file have no numbered stages (check_selector)
            continue
        for item in entries:
            if item.get("stage") is None or item["agent"] not in AGENTS:
                continue
            entry = local_doc.entry("stages", f"{team}.{item['stage']}", item["agent"]) or {}
            rows["stages"].append({"team": team, "stage": item["stage"], "role": item["role"], "agent": item["agent"],
                                   "model": entry.get("model"), "effort": entry.get("effort"),
                                   "name": found.display(item["agent"], entry.get("model")) if entry.get("model") else None})
    seen = set()
    teams_now = dict(now.get("teams") or {})
    for agent in ("claude", "chatgpt"):  # route's calls: whoever the skill table picks
        for role in ("build", "fix", "check"):
            seen.add(("route", role, agent))
    for team, entries in teams_now.items():
        for item in entries:
            if item["agent"] in AGENTS:
                word = ROLE_ALIASES.get(item["role"], item["role"])
                seen.add((team, word, item["agent"]))
                if word in ("build", "execute", "integrate") or (team in ("research-build", "redteam", "plan", "split") and word == "build"):
                    seen.add((team, "fix", item["agent"]))
    for role in ("build", "revise", "execute", "fix", "integrate"):
        seen.add(("file", role, "claude"))
    order = ["route"] + [t for t in teams_now if t not in ("plan", "split")] + ["split", "plan", "file"]
    for team in order:
        for role in ROLE_WORDS:
            for agent in AGENTS:
                if (team, role, agent) not in seen:
                    continue
                entry = local_doc.entry("roles", f"{team}.{role}", agent) or {}
                rows["roles"].append({"team": team, "role": role, "agent": agent, "model": entry.get("model"),
                                      "effort": entry.get("effort"),
                                      "name": found.display(agent, entry.get("model")) if entry.get("model") else None})
    return rows


def status_view(conn, roster, loaded, table, *, send_paths, since, skills_now=None):
    """`sr status --json`'s `models` (decision 11): the defaults, the allowlists, the Fable switch, Claude's Opus and Fable
    calls this week, what each role would use now, and Setup's rows."""
    found = tracked()
    local_doc = local(found=found)
    pins = {name: roster.model(name) for name in ("chatgpt", "cursor")} if roster is not None else {}
    doc = view(found, local_doc, pins)
    opus, fable = claude_calls_this_week(conn, since)
    doc["claude"] = {"opus_calls_this_week": opus, "fable_calls_this_week": fable}
    doc["now"] = now_view(found, local_doc, roster, loaded, table, send_paths=send_paths, pins=pins, skills_now=skills_now)
    doc["setup"] = setup_rows(doc["now"], local_doc, found, skills=tuple(roster.skills) if roster is not None else (),
                              skills_now=skills_now)
    return doc
