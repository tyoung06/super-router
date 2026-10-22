"""The roster: which agents exist, which are live, and the skill table that says who does and
who checks each skill. Read from config/agents.json and config/skill_table.json, and checked
together. On any problem the router refuses and logs nothing.

Only the owner changes a live flag in config/agents.json.
"""
import json
import re
from dataclasses import dataclass

from router import safety

AGENTS_PATH = safety.REPO_ROOT / "config" / "agents.json"
SKILLS_PATH = safety.REPO_ROOT / "config" / "skill_table.json"

AGENT_NAME = re.compile(r"[a-z][a-z0-9_]*")  # used as an @tag, so plain lowercase words only
PINNED_MODEL = re.compile(r"jev-\d+\.\d+\.\d+")  # a fixed release, never the moving jev-latest
MODEL_REQUIRED = ("chatgpt", "cursor")  # agents whose worker needs a pinned model name from agents.json
MODEL_EXAMPLE = {"chatgpt": "gpt-6.1-sol", "cursor": "grok-4.7-high"}
# Rules v2.28 (Cursor, "The model"): one Grok model pinned by name, never `auto`, never a third-party model, which
# Cursor bills from the first use. The owner, 2026-10-19: a name starting with `grok` or `cursor-grok` (Cursor's own ids
# for Grok 4.7, and for Grok 4.6 and 4.5) and nothing else. Checked whether or not the entry is live.
CURSOR_MODEL = re.compile(r"(?:cursor-)?grok[-.0-9a-z]*")
MODEL_RULES = {"cursor": (CURSOR_MODEL, "grok or cursor-grok (never auto)")}
# Rules v2.28: Cursor is never a checker on a routed task and never a stand-in, so a skill table that names it as a
# skill's `second` or `interim` is refused at load. `best` is the owner's to set later (routed `code`), no code needed.
NEVER_SECOND = ("cursor",)
NEVER_INTERIM = ("cursor",)


class RosterError(safety.SafeError):
    """A config file is missing, unreadable, or fails a check. `problems` lists every one."""

    def __init__(self, problems):
        super().__init__(" ".join(problems))
        self.problems = list(problems)


@dataclass(frozen=True)
class Roster:
    agents: dict      # name -> {"live": true or false}, in config order
    not_routed: tuple  # skills that come back to the owner in version 2
    table: dict       # config/skill_table.json, exactly as read

    @property
    def names(self):
        return tuple(self.agents)

    @property
    def live(self):
        return tuple(name for name, agent in self.agents.items() if agent["live"] is True)

    def model(self, name):
        """The pinned model for an agent, or None when the config names none."""
        agent = self.agents.get(name) or {}
        return agent.get("model") or None

    @property
    def skills(self):
        return self.table["skills"]

    @property
    def skill_order(self):
        return tuple(self.table["skills"])

    @property
    def labeler(self):
        return self.table["labeler"]


def problems(agents_doc, table, send_paths):
    """Every problem with the two config files, as plain sentences. An empty list means OK.
    `send_paths` are the agent names the code can send a task to."""
    found = []
    agents = agents_doc.get("agents") if isinstance(agents_doc, dict) else None
    skills = table.get("skills") if isinstance(table, dict) else None
    if not isinstance(agents, dict) or not agents:
        return ["agents.json has no agents."]
    if not isinstance(skills, dict) or not skills:
        return ["skill_table.json has no skills."]

    for name, agent in agents.items():
        if not AGENT_NAME.fullmatch(name):
            found.append(f"agents.json: {name!r} is not a plain lowercase agent name.")
        if not isinstance(agent, dict) or not isinstance(agent.get("live"), bool):
            found.append(f"agents.json: {name}'s live flag must be true or false.")
            continue
        model = agent.get("model")
        if "model" in agent and (not isinstance(model, str) or not model.strip()):
            found.append(f"agents.json: {name}'s model must be a pinned model name.")
        elif name in MODEL_REQUIRED and agent.get("live") is True and "model" not in agent:
            found.append(f"agents.json: {name} is live but has no model. Pin one, for example \"{MODEL_EXAMPLE[name]}\".")
        elif name in MODEL_RULES and isinstance(model, str) and not MODEL_RULES[name][0].fullmatch(model.strip()):
            found.append(f"agents.json: {name}'s model must start with {MODEL_RULES[name][1]}, not {model!r}.")
    live = {name for name, agent in agents.items() if isinstance(agent, dict) and agent.get("live") is True}
    for name in sorted(live - set(send_paths)):
        found.append(f"{name} is live in agents.json, but the router has no way to send it a task.")

    for name in table.get("models", []):
        if name not in agents:
            found.append(f"skill_table.json names {name} in models, but agents.json has no {name}.")
    for key, skill in skills.items():
        best, second, interim = skill.get("best"), skill.get("second"), skill.get("interim")
        if not best:
            found.append(f"skill_table.json: {key} has no best agent.")
        for role, name in (("best", best), ("second", second), ("interim", interim)):
            if name and name not in agents:
                found.append(f"skill_table.json: {key}'s {role} is {name}, but agents.json has no {name}.")
        if second in NEVER_SECOND:
            found.append(f"skill_table.json: {key}'s second is {second}, but {second} never checks (rules v2.28, Cursor).")
        if interim in NEVER_INTERIM:
            found.append(f"skill_table.json: {key}'s interim is {interim}, but {interim} is never a stand-in (rules v2.28, Cursor).")
        if best and best == second:
            found.append(f"skill_table.json: {key}'s best and second are both {best}.")
        if interim and interim == second:
            found.append(f"skill_table.json: {key}'s interim and second are both {interim}.")
        if interim and interim in agents and interim not in live:
            found.append(f"skill_table.json: {key}'s interim is {interim}, which is not live.")

    not_routed = agents_doc.get("skills_not_routed", [])
    if not isinstance(not_routed, list):
        found.append("agents.json: skills_not_routed must be a list of skills.")
    else:
        for key in not_routed:
            if key not in skills:
                found.append(f"agents.json: skills_not_routed names {key}, which is not a skill in skill_table.json.")

    labeler = table.get("labeler") if isinstance(table.get("labeler"), dict) else {}
    model = labeler.get("jev_model")
    if not isinstance(model, str) or not PINNED_MODEL.fullmatch(model):
        found.append(f"skill_table.json: labeler.jev_model must be a pinned version like jev-1.13.0, not {model!r}.")
    floor = labeler.get("min_confidence")
    if isinstance(floor, bool) or not isinstance(floor, (int, float)) or not 0 < floor <= 1:
        found.append(f"skill_table.json: labeler.min_confidence must be a number above 0 and up to 1, not {floor!r}.")
    for field in ("question", "fallback_label", "fallback_description"):
        if not isinstance(labeler.get(field), str) or not labeler[field].strip():
            found.append(f"skill_table.json: labeler.{field} is missing.")
    second = labeler.get("second_question")
    if not isinstance(second, dict) or not isinstance(second.get("instructions"), str):
        found.append("skill_table.json: labeler.second_question.instructions is missing.")
    return found


def _read(path):
    try:
        text = path.read_text()
    except OSError as e:
        raise RosterError([f"Could not read {path.name} ({type(e).__name__})."]) from None
    try:
        return json.loads(text)
    except ValueError:
        raise RosterError([f"{path.name} is not valid JSON."]) from None


def load_roster(send_paths, agents_path=None, skills_path=None):
    """Read both config files and check them together. Raises RosterError on any problem."""
    agents_doc = _read(agents_path or AGENTS_PATH)
    table = _read(skills_path or SKILLS_PATH)
    found = problems(agents_doc, table, send_paths)
    if found:
        raise RosterError(found)
    return Roster(agents=dict(agents_doc["agents"]), not_routed=tuple(agents_doc.get("skills_not_routed", [])),
                  table=table)
