"""Presets (rules v2.13, Relay): the chains `sr relay` may run, read from config/presets.json and
checked at startup against config/agents.json and the code. Every stage agent and the checker
must be live and have a sender in code; the checker may not be the last stage's agent; a chain
has at most 4 stages, numbered 1..n; every stage but the last names a contract the code has.

A preset either names a checker, or marks its last stage `is_check` (rules v2.13): then it names
no checker, the check stage's agent is not the agent of the stage before it, and the check stage
names a contract the code reads a verdict from. Both, neither, or `is_check` on another stage is
refused with the reason.

A preset may instead have review stages (rules v2.16): a stage may name its `input` (the task
alone, or one earlier stage's result; absent is the stage before), and a `review` stage names the
earlier stage it reviews (`review_of`), by another agent, never a review. Such a preset names no
checker and no check stage, reviews every other stage exactly once, and names the owner as the one who
picks (`pick`). A stage a review stage reviews needs no contract: the review is its check (the owner's D1).

A preset names its slots (rules v2.21, Relay → Slots): `slots` maps a slot name to the stages it covers, and
`"checker"` for the named checker. Every stage is in exactly one slot, the checker in exactly one when there is
one, and a slot's parts share one default agent: the agent the preset names there. `fill` puts other agents in
slots for one task; `for_task` builds a task's filled preset from its row, and every reader of a task calls it.

A bad preset is kept with its problems, so `sr relay --list` can mark it BAD and `sr relay` can
refuse it with the reason; the good presets still load. A broken file refuses every preset.
The runner never invents a stage: presets come only from this file.
"""
import json
import re
from dataclasses import dataclass, replace

from router import log, safety

PRESETS_PATH = safety.REPO_ROOT / "config" / "presets.json"
FILE_VERSIONS = ("1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6")  # 1.1 collab, 1.2 versus, 1.3 slots, 1.4 redteam, 1.5 vote, 1.6 descriptions
PRESET_NAME = re.compile(r"[a-z][a-z0-9-]*")   # typed on the command line, so plain lowercase words
ROLE_NAME = re.compile(r"[a-z][a-z0-9_-]*")
STAGE_FIELDS = {"n", "agent", "role", "contract", "is_check", "input", "review_of", "attack_of", "revise_of",
                "against"}
PRESET_FIELDS = {"stages", "checker", "pick", "slots", "description"}  # brief 21: description, one line, optional
CHECKER_PART = "checker"  # in a slot's list: the preset's named checker
# A slot becomes a flag on `sr relay` (--<slot> <agent>), so it may not be one of relay's own words.
RESERVED_SLOT_NAMES = ("list", "no-wait", "file", "source", "help", "h", "web", "preset", "task", "project", "chat", "json")
REVIEW_ROLE = "review"
REVIEW_CONTRACTS = ("review_note",)  # the contracts code reads a review verdict from (router/relay.py)
ATTACK_ROLE, REVISE_ROLE = "attack", "revise"   # brief 16 (rules v2.23)
ATTACK_CONTRACTS = ("attack_list",)  # router/relay.py: the attack list, counted and read by code
REVISE_CONTRACTS = ("revision",)     # router/relay.py: the deliverable and ## Answered
PICKER = "owner"                     # rules v2.16: the preset names the owner as the one who picks
TALLY = "tally"                      # rules v2.24: code counts the votes; no majority, the owner picks
VOTE_ROLE = "vote"
VOTE_CONTRACTS = ("vote",)           # router/relay.py: the answer line, read and normalised by code
TASK_INPUT = "task"
_STAGE_INPUT = re.compile(r"stage:([0-9]+)")


class PresetsError(safety.SafeError):
    """The presets file is missing, unreadable or malformed. `problems` lists every reason."""

    def __init__(self, problems):
        super().__init__(" ".join(problems))
        self.problems = list(problems)


@dataclass(frozen=True)
class Stage:
    n: int
    agent: str
    role: str
    contract: str | None  # a key of relay.CONTRACTS, or None for a last stage that a checker checks
    is_check: bool = False  # the last stage is the check (rules v2.13)
    input: str | None = None      # None: the stage before; "task": the task alone; "stage:k" (rules v2.16)
    review_of: int | None = None  # a review stage: the earlier stage it reviews (rules v2.16)
    attack_of: int | None = None  # an attack stage: the earlier stage it attacks (rules v2.23)
    revise_of: int | None = None  # a revise stage: the earlier stage it revises, by the same agent (rules v2.23)
    against: int | None = None    # ...against this other earlier stage's result

    @property
    def input_stage(self):
        """The earlier stage whose result this stage gets: k for "stage:k", n-1 by default, None for
        the task alone (or stage 1, which has no stage before)."""
        if self.input == TASK_INPUT:
            return None
        if self.input is None:
            return self.n - 1 if self.n > 1 else None
        return int(_STAGE_INPUT.fullmatch(self.input).group(1))


@dataclass(frozen=True)
class Slot:
    """One slot of a preset (rules v2.21): the stages it covers, whether it covers the named checker, the agent
    in it for this task, and its default (the agent config/presets.json names there)."""
    name: str
    stages: tuple
    checker: bool
    agent: str
    default: str


@dataclass(frozen=True)
class Preset:
    name: str
    stages: tuple
    checker: str | None  # None when the last stage is the check, or the preset has review stages
    pick: str | None = None  # "owner" on a preset with review stages (rules v2.16); "tally" on vote (rules v2.24)
    slots: tuple = ()        # Slot, in file order (rules v2.21); empty: the preset takes no slot flags
    description: str | None = None  # brief 21 (rules v2.30): one line the page shows; the owner writes it

    @property
    def review_stages(self):
        return tuple(s for s in self.stages if s.review_of is not None)

    @property
    def has_reviews(self):
        """Review stages (versus): no checker, no check stage; the owner picks a candidate."""
        return bool(self.review_stages)

    @property
    def tallies(self):
        """A tally preset (vote, rules v2.24): every stage a vote, no checker; code counts the answers."""
        return self.pick == TALLY

    @property
    def attack_stage(self):
        return next((s for s in self.stages if s.attack_of is not None), None)

    @property
    def revise_stage(self):
        """The one revise stage (rules v2.23), or None."""
        return next((s for s in self.stages if s.revise_of is not None), None)

    def reviewer_of(self, n):
        """The review stage that reviews stage n, or None."""
        return next((s for s in self.review_stages if s.review_of == n), None)

    @property
    def last_agent(self):
        return self.stages[-1].agent

    @property
    def doer(self):
        """The agent the task row names: the last stage's, or, when the last stage is the check, the
        agent of the stage it checks (log.set_route refuses an agent that checks its own work). On a
        preset with review stages, stage 1's agent while the chain runs: nothing is the result until
        the owner picks, and the pick names the doer (rules v2.16)."""
        if self.has_reviews or self.tallies:  # rules v2.24: on a tally, the winner's agent once code has counted
            return self.stages[0].agent
        return self.stages[-2].agent if self.check_stage else self.last_agent

    @property
    def check_agent(self):
        """Who checks the result: the check stage's agent, or the named checker (None on a preset with
        review stages: each review is the check of one candidate)."""
        return self.check_stage.agent if self.check_stage else self.checker

    @property
    def check_stage(self):
        """The last stage when it is the check, else None (the checker loop checks)."""
        return self.stages[-1] if self.stages[-1].is_check else None

    def stage(self, n):
        return self.stages[n - 1]


@dataclass(frozen=True)
class Presets:
    version: str
    presets: dict   # name -> Preset, the good ones, in file order
    problems: dict  # name -> [problem], the bad ones, in file order

    @property
    def names(self):
        return tuple(sorted(set(self.presets) | set(self.problems), key=self._order))

    def _order(self, name):
        return list(self.presets).index(name) if name in self.presets else len(self.presets) + list(self.problems).index(name)


def _agent_problems(what, name, roster, send_paths):
    """Build brief 24 (decision 8): an agent that isn't live no longer makes a preset bad at load; intake reads
    availability and fills its slot (`fill`). An agent the config doesn't have, or the router can't send to, still does."""
    if name not in roster.names:
        return [f"{what} names {name}, which agents.json doesn't have."]
    if name not in send_paths:
        return [f"{what} names {name}, but the router has no way to send it a task."]
    return []


def _input_problems(what, n, value):
    """The problems with a stage's `input` (rules v2.16): "task", or "stage:k" for one earlier stage."""
    if value == TASK_INPUT:
        return []
    text = value if isinstance(value, str) else None
    if isinstance(value, list) or (text and ("," in text or "+" in text or " and " in text)):
        return [f"{what} names more than one stage as its input ({value!r}); a stage gets the task alone or one "
                "earlier stage's result."]
    m = _STAGE_INPUT.fullmatch(text) if text else None
    if m is None or int(m.group(1)) < 1:
        return [f"{what} has input {value!r}; it must be 'task' or 'stage:k' with k an earlier stage."]
    if int(m.group(1)) >= n:
        return [f"{what} names stage {int(m.group(1))} as its input, a later stage or itself; a stage gets only an "
                "earlier stage's result."]
    return []


def _review_problems(name, stages, review_contracts):
    """The problems of a preset with review stages (rules v2.16), stage by stage, then as a whole."""
    found = []
    by_n = {s.get("n"): s for s in stages if isinstance(s, dict)}
    reviewed = {}
    for i, stage in enumerate(stages, 1):
        if not isinstance(stage, dict):
            continue
        what = f"preset {name}, stage {i}"
        has_of, is_review = "review_of" in stage, stage.get("role") == REVIEW_ROLE
        if is_review and not has_of:
            found.append(f"{what} has the role review but no review_of; a review names the stage it reviews.")
        if has_of and not is_review:
            found.append(f"{what} names review_of but not the role review.")
        if not has_of:
            continue
        k = stage["review_of"]
        if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k < i:
            found.append(f"{what} has review_of {k!r}; it must be the number of an earlier stage.")
            continue
        target = by_n.get(k, {})
        reviewed.setdefault(k, []).append(i)
        if stage.get("input") != f"stage:{k}":
            found.append(f"{what} has review_of {k} but input {stage.get('input')!r}; a review's input must be "
                         f"'stage:{k}', the stage it reviews.")
        if target.get("agent") and target.get("agent") == stage.get("agent"):
            found.append(f"{what} by {stage.get('agent')} reviews stage {k}, which is {stage.get('agent')}'s own work; "
                         "no agent checks its own work.")
        if "review_of" in target:
            found.append(f"{what} reviews stage {k}, but stage {k} is itself a review; a review reviews a candidate.")
        if stage.get("contract") not in review_contracts:
            found.append(f"{what} is a review and names contract {stage.get('contract')!r}; a review names "
                         f"{' or '.join(review_contracts)}, which code reads the verdict from.")
        if stage.get("is_check") is True:
            found.append(f"{what} is marked is_check; a preset with review stages has no check stage.")
    for i, stage in enumerate(stages, 1):
        if isinstance(stage, dict) and "review_of" not in stage and stage.get("role") != REVIEW_ROLE:
            by = reviewed.get(i, [])
            if not by:
                found.append(f"preset {name}: stage {i} is not reviewed; every stage of a preset with review stages "
                             "that is not a review is reviewed exactly once.")
            elif len(by) > 1:
                found.append(f"preset {name}: stage {i} is reviewed twice (by stages {' and '.join(map(str, by))}); "
                             "every candidate is reviewed exactly once.")
    return found


def _slot_problems(name, preset, stages):
    """The problems with a preset's `slots` map (rules v2.21). A preset without one takes no slot flags."""
    if "slots" not in preset:
        return []
    raw = preset["slots"]
    if not isinstance(raw, dict):
        return [f"preset {name}: slots must be an object of slot names to the stages they cover."]
    found, owners, checker_owners = [], {}, []
    checker = preset.get("checker")
    agents = {i: s.get("agent") for i, s in enumerate(stages, 1) if isinstance(s, dict)}
    for slot, parts in raw.items():
        if not isinstance(slot, str) or not PRESET_NAME.fullmatch(slot):
            found.append(f"preset {name}: slot name {slot!r} is not a plain lowercase word (letters, digits, dashes).")
            continue
        if slot in RESERVED_SLOT_NAMES:
            found.append(f"preset {name}: slot name {slot!r} is one of relay's own words "
                         f"({', '.join(RESERVED_SLOT_NAMES)}); pick another.")
            continue
        if not isinstance(parts, list):
            found.append(f"preset {name}: slot {slot} must be a list of stage numbers (or 'checker').")
            continue
        if not parts:
            found.append(f"preset {name}: slot {slot} covers nothing.")
            continue
        covered = []
        for part in parts:
            if part == CHECKER_PART:
                if checker is None:
                    found.append(f"preset {name}: slot {slot} names the checker, but preset {name} has none.")
                else:
                    checker_owners.append(slot)
                    covered.append(checker)
            elif isinstance(part, int) and not isinstance(part, bool) and 1 <= part <= len(stages):
                owners.setdefault(part, []).append(slot)
                covered.append(agents.get(part))
            else:
                found.append(f"preset {name}: slot {slot} names stage {part}, which the preset doesn't have.")
        distinct = list(dict.fromkeys(a for a in covered if a))
        if len(distinct) > 1:
            found.append(f"preset {name}: slot {slot} covers {' and '.join(distinct)}; a slot's parts share one "
                         "default agent.")
    for i in range(1, len(stages) + 1):
        by = owners.get(i, [])
        if not by:
            found.append(f"preset {name}: stage {i} is in no slot; every stage is in exactly one slot.")
        elif len(by) > 1:
            found.append(f"preset {name}: stage {i} is in more than one slot ({', '.join(by)}).")
    if checker is not None:
        if not checker_owners:
            found.append(f"preset {name}: the checker is in no slot; it is in exactly one.")
        elif len(checker_owners) > 1:
            found.append(f"preset {name}: the checker is in more than one slot ({', '.join(checker_owners)}).")
    return found


def _earlier(value, i):
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value < i


def _kind_problems(name, stages, attack_contracts, revise_contracts):
    """The problems of attack and revise stages (rules v2.23), each with its own sentence. Run on the chain as it
    stands, so on the filled preset at intake (brief 15: slots are applied before problems() is asked)."""
    found, revises = [], 0
    agents = {i: s.get("agent") for i, s in enumerate(stages, 1) if isinstance(s, dict)}
    for i, stage in enumerate(stages, 1):
        if not isinstance(stage, dict):
            continue
        what = f"preset {name}, stage {i}"
        role = stage.get("role")
        if role == ATTACK_ROLE and "attack_of" not in stage:
            found.append(f"{what} has the role attack but no attack_of; an attack names the stage it attacks.")
        if "attack_of" in stage:
            k = stage["attack_of"]
            if role != ATTACK_ROLE:
                found.append(f"{what} names attack_of but not the role attack.")
            if not _earlier(k, i):
                found.append(f"{what} has attack_of {k!r}; it must be the number of an earlier stage.")
            else:
                if stage.get("input") != f"stage:{k}":
                    found.append(f"{what} attacks stage {k} but has input {stage.get('input')!r}; an attack's input "
                                 f"must be 'stage:{k}', the result it attacks.")
                if stage.get("agent") and stage.get("agent") == agents.get(k):
                    found.append(f"{what} by {stage.get('agent')} attacks stage {k}, which is {stage.get('agent')}'s "
                                 "own work; an attacker does not attack its own build.")
            if stage.get("contract") not in attack_contracts:
                found.append(f"{what} is an attack and names contract {stage.get('contract')!r}; an attack names "
                             f"{' or '.join(attack_contracts)}, which code counts and reads.")
            for bad in ("is_check", "review_of", "revise_of"):
                if stage.get(bad) not in (None, False):
                    found.append(f"{what} is an attack stage and also names {bad}.")
        if role == REVISE_ROLE and "revise_of" not in stage:
            found.append(f"{what} has the role revise but no revise_of; a revise stage names the stage it revises.")
        if "revise_of" in stage:
            revises += 1
            k, against = stage["revise_of"], stage.get("against")
            if role != REVISE_ROLE:
                found.append(f"{what} names revise_of but not the role revise.")
            if "against" not in stage:
                found.append(f"{what} names revise_of but no against; a revise stage revises against one other stage.")
            if not _earlier(k, i):
                found.append(f"{what} has revise_of {k!r}; it must be the number of an earlier stage.")
            elif stage.get("agent") and stage.get("agent") != agents.get(k):
                found.append(f"{what} by {stage.get('agent')} revises stage {k}, which is {agents.get(k)}'s; a revise "
                             "stage is by the agent that made the stage it revises.")
            if "against" in stage and not _earlier(against, i):
                found.append(f"{what} has against {against!r}; it must be the number of an earlier stage.")
            elif "against" in stage and against == k:
                found.append(f"{what} revises stage {k} against stage {against}; against must be another stage.")
            if stage.get("is_check") is True:
                found.append(f"{what} is a revise stage and is marked is_check; the checker checks it.")
            if "input" in stage:
                found.append(f"{what} is a revise stage and names an input; it gets its own earlier result and the "
                             "against stage's result.")
            for bad in ("review_of", "attack_of"):
                if bad in stage:
                    found.append(f"{what} is a revise stage and also names {bad}.")
            if stage.get("contract") not in revise_contracts:
                found.append(f"{what} is a revise stage and names contract {stage.get('contract')!r}; a revise stage "
                             f"names {' or '.join(revise_contracts)}.")
    if revises > 1:
        found.append(f"preset {name} has {revises} revise stages; at most one.")
    return found


def _tally_problems(name, preset, stages, vote_contracts=VOTE_CONTRACTS):
    """The problems of a tally preset (rules v2.24, decision 2), each with its own sentence. Asked of the filled
    chain at intake, so two slots holding one agent are refused here."""
    found = []
    count = len(stages)
    if count < 3 or count % 2 == 0:
        found.append(f"preset {name} has {count} stage{'s' if count != 1 else ''}; a tally needs an odd number of "
                     "voters, at least three (two answers are not a vote).")
    if preset.get("checker") is not None:
        found.append(f"preset {name} is a tally and names a checker ({preset.get('checker')}); the tally is the check.")
    seen = {}
    for i, stage in enumerate(stages, 1):
        if not isinstance(stage, dict):
            continue
        what = f"preset {name}, stage {i}"
        if stage.get("input") != TASK_INPUT:
            found.append(f"{what} has input {stage.get('input')!r}; a vote stage gets the task alone (input 'task'), "
                         "never another stage's result.")
        if stage.get("role") != VOTE_ROLE:
            found.append(f"{what} has the role {stage.get('role')!r}; every stage of a tally preset is a vote.")
        if stage.get("contract") not in vote_contracts:
            found.append(f"{what} names contract {stage.get('contract')!r}; a vote stage names "
                         f"{' or '.join(vote_contracts)}, which code reads the answer line from.")
        if stage.get("is_check") is True:
            found.append(f"{what} is marked is_check; a tally preset has no check stage.")
        for field, kind in (("review_of", "review"), ("attack_of", "attack"), ("revise_of", "revise")):
            if field in stage:
                found.append(f"{what} is a {kind} stage; a tally preset has no review, attack or revise stage.")
        agent = stage.get("agent")
        if isinstance(agent, str) and agent:
            if agent in seen:
                found.append(f"preset {name}: stages {seen[agent]} and {i} are both {agent}; every voter is a "
                             "different agent (one agent voting twice is not a vote).")
            else:
                seen[agent] = i
    return found


def problems(name, preset, roster, send_paths, contracts, roles=None, verdicts=(), review_contracts=REVIEW_CONTRACTS,
             attack_contracts=ATTACK_CONTRACTS, revise_contracts=REVISE_CONTRACTS):
    """Every problem with one preset, as plain sentences. An empty list means it may run.
    `roles`, when given, are the role words the code has a prompt for; `verdicts` are the
    contracts the code reads a verdict from, the only ones a check stage may name;
    `review_contracts` the ones a review stage may name."""
    found = []
    if not isinstance(name, str) or not PRESET_NAME.fullmatch(name):
        found.append(f"the preset name {name!r} is not a plain lowercase word (letters, digits, dashes).")
    if not isinstance(preset, dict):
        return found + [f"preset {name} is not an object."]
    for field in sorted(set(preset) - PRESET_FIELDS):
        found.append(f"preset {name} has an unknown field {field!r}.")
    if "description" in preset and not _one_line(preset["description"]):
        found.append(f"preset {name}: description must be one line of text.")
    stages = preset.get("stages")
    if not isinstance(stages, list) or not stages:
        return found + [f"preset {name} has no stages."]
    if len(stages) > log.MAX_STAGES:
        found.append(f"preset {name} has {len(stages)} stages; at most {log.MAX_STAGES} are allowed.")
    last = len(stages)
    last_stage = stages[-1] if isinstance(stages[-1], dict) else {}
    has_reviews = any(isinstance(s, dict) and ("review_of" in s or s.get("role") == REVIEW_ROLE) for s in stages)
    tally = preset.get("pick") == TALLY  # rules v2.24: _tally_problems judges every stage's kind and contract
    has_check = last_stage.get("is_check") is True and not has_reviews and not tally
    reviewed = {s.get("review_of") for s in stages if isinstance(s, dict) and "review_of" in s}
    for i, stage in enumerate(stages, 1):
        what = f"preset {name}, stage {i}"
        if not isinstance(stage, dict):
            found.append(f"{what} is not an object.")
            continue
        for field in sorted(set(stage) - STAGE_FIELDS):
            found.append(f"{what} has an unknown field {field!r}.")
        if stage.get("n") != i:
            found.append(f"{what} is numbered {stage.get('n')!r}; stage numbers must run 1..n in order.")
        agent = stage.get("agent")
        if not isinstance(agent, str) or not agent:
            found.append(f"{what} has no agent.")
        else:
            found += _agent_problems(what, agent, roster, send_paths)
        role = stage.get("role")
        if not isinstance(role, str) or not ROLE_NAME.fullmatch(role):
            found.append(f"{what} has no plain lowercase role word (found {role!r}).")
        elif roles is not None and role not in roles:
            found.append(f"{what} names the role {role!r}, which the code has no prompt for.")
        if "input" in stage:
            found += _input_problems(what, i, stage["input"])
        contract = stage.get("contract")
        is_check = stage.get("is_check", False)
        if is_check is not True and "is_check" in stage and is_check is not False:
            found.append(f"{what} has is_check {is_check!r}; it must be true when given.")
        if is_check is True and i != last:
            found.append(f"{what} is marked is_check but is not the last stage; only the last stage may be the check.")
        if tally:
            continue  # a vote stage's role, input and contract are checked in _tally_problems
        if has_reviews and ("review_of" in stage or stage.get("role") == REVIEW_ROLE):
            continue  # a review stage's contract is checked in _review_problems
        if i == last and has_check:
            if last == 1:
                found.append(f"{what} is the check, but a check stage needs a stage before it to check.")
            elif isinstance(stages[-2], dict) and agent and stages[-2].get("agent") == agent:
                found.append(f"preset {name}'s check stage {i} is by {agent}, the agent of stage {i - 1}; "
                             "no agent checks its own work.")
            if contract is None:
                found.append(f"{what} is the check and has no contract; code reads the verdict from it.")
            elif not isinstance(contract, str) or contract not in contracts:
                found.append(f"{what} names contract {contract!r}, which the code doesn't have.")
            elif contract not in verdicts:
                found.append(f"{what} is the check and names contract {contract!r}, which the code reads no verdict from.")
        elif i == last:
            if "revise_of" in stage:
                pass  # rules v2.23: a revise stage has its contract even when it is the last stage (_kind_problems)
            elif contract is not None:
                found.append(f"{what} is the last stage and names a contract; the last stage's result is checked "
                             "by the checker, not by a contract.")
        elif contract is None:
            if i not in reviewed:  # The owner's D1: a stage a review stage reviews needs no contract
                found.append(f"{what} has no contract; every stage but the last needs one.")
        elif not isinstance(contract, str) or contract not in contracts:
            found.append(f"{what} names contract {contract!r}, which the code doesn't have.")
    found += _slot_problems(name, preset, stages)
    if tally:  # The owner's choice 1: `pick: "tally"` is the fourth kind, beside checker, check stage and reviews
        return found + _tally_problems(name, preset, stages)
    found += _kind_problems(name, stages, attack_contracts, revise_contracts)
    checker = preset.get("checker")
    pick = preset.get("pick")
    if has_reviews:
        found += _review_problems(name, stages, review_contracts)
        if checker is not None:
            found.append(f"preset {name} has review stages and names a checker ({checker}); the reviews are the checks.")
        if pick is None:
            found.append(f"preset {name} has review stages and no pick; it must name {PICKER} as the one who picks.")
        elif pick != PICKER:
            found.append(f"preset {name} has pick {pick!r}; only {PICKER} picks.")
        return found
    if "pick" in preset:
        found.append(f"preset {name} has pick {preset['pick']!r} but no review stages; a pick is {PICKER} on a preset "
                     f"with review stages, or {TALLY} on a tally preset.")
    if has_check:
        if checker is not None:
            found.append(f"preset {name} marks a check stage and names a checker ({checker}); a preset has one or "
                         "the other, never both.")
    elif not isinstance(checker, str) or not checker:
        found.append(f"preset {name} has no checker, no check stage, no review stages and no tally; it needs one of them.")
    else:
        found += _agent_problems(f"preset {name}'s checker", checker, roster, send_paths)
        last_stage = stages[-1]
        if isinstance(last_stage, dict) and last_stage.get("agent") == checker:
            found.append(f"preset {name}'s checker {checker} is also its last stage's agent; no agent checks its own work.")
    return found


def _one_line(value):
    """A description (brief 21): a string with something in it and no line break."""
    return isinstance(value, str) and bool(value.strip()) and "\n" not in value and "\r" not in value


def _read(path):
    try:
        text = path.read_text()
    except OSError as e:
        raise PresetsError([f"Could not read {path.name} ({type(e).__name__})."]) from None
    try:
        return json.loads(text)
    except ValueError:
        raise PresetsError([f"{path.name} is not valid JSON."]) from None


def load_presets(roster, send_paths, contracts, path=None, roles=None, verdicts=()):
    """Read config/presets.json and check every preset. Raises PresetsError when the file itself
    is unusable; a bad preset is kept in `problems`, the good ones in `presets`."""
    path = path or PRESETS_PATH
    doc = _read(path)
    if not isinstance(doc, dict):
        raise PresetsError([f"{path.name} is not an object with version and presets."])
    version = doc.get("version")
    if version not in FILE_VERSIONS:
        raise PresetsError([f"{path.name} is version {version!r}; this router knows version "
                            f"{' and '.join(FILE_VERSIONS)}."])
    entries = doc.get("presets")
    if not isinstance(entries, dict) or not entries:
        raise PresetsError([f"{path.name} has no presets."])
    good, bad = {}, {}
    for name, preset in entries.items():
        found = problems(name, preset, roster, send_paths, contracts, roles, verdicts)
        if found:
            bad[name] = found
            continue
        stages = tuple(Stage(s["n"], s["agent"], s["role"], s["contract"], s.get("is_check", False),
                             s.get("input"), s.get("review_of"), s.get("attack_of"), s.get("revise_of"),
                             s.get("against"))
                       for s in preset["stages"])
        good[name] = Preset(name, stages, preset.get("checker"), preset.get("pick"), _slots(preset, stages),
                            preset.get("description"))
    return Presets(version, good, bad)


def _slots(preset, stages):
    """The Slot tuple of a preset that passed its checks, with today's agents as defaults."""
    found = []
    for slot, parts in (preset.get("slots") or {}).items():
        numbers = tuple(p for p in parts if p != CHECKER_PART)
        covers_checker = CHECKER_PART in parts
        agent = stages[numbers[0] - 1].agent if numbers else preset["checker"]
        found.append(Slot(slot, numbers, covers_checker, agent, agent))
    return tuple(found)


def slot_map(preset):
    """{slot: agent} for every slot of a (filled) preset, in file order."""
    return {s.name: s.agent for s in preset.slots}


def changed(preset):
    """{slot: agent} for each slot whose agent differs from its default."""
    return {s.name: s.agent for s in preset.slots if s.agent != s.default}


def fill(preset, chosen):
    """The preset with `chosen` agents ({slot: agent}) in its slots, for one task (rules v2.21). A slot left out
    keeps its agent. Stages, roles, contracts, inputs and reviews never change, and neither does `preset`.
    ValueError for a slot the preset doesn't have; whether the filled preset may run is problems()'s question."""
    names = [s.name for s in preset.slots]
    unknown = [k for k in chosen if k not in names]
    if unknown:
        raise ValueError(f"{preset.name} has no slot {unknown[0]} (its slots: {', '.join(names) or 'none'}).")
    by_stage, checker, slots = {}, preset.checker, []
    for slot in preset.slots:
        agent = chosen.get(slot.name, slot.agent)
        for n in slot.stages:
            by_stage[n] = agent
        if slot.checker:
            checker = agent
        slots.append(replace(slot, agent=agent))
    stages = tuple(replace(s, agent=by_stage.get(s.n, s.agent)) for s in preset.stages)
    return Preset(preset.name, stages, checker, preset.pick, tuple(slots), preset.description)


def as_entry(preset):
    """A (filled) preset written back as a config entry, so problems() can judge it as it judges the file."""
    entry = {"stages": [], "checker": preset.checker}
    if preset.pick is not None:
        entry["pick"] = preset.pick
        del entry["checker"]
    for s in preset.stages:
        stage = {"n": s.n, "agent": s.agent, "role": s.role, "contract": s.contract}
        if s.is_check:
            stage["is_check"] = True
        if s.input is not None:
            stage["input"] = s.input
        if s.review_of is not None:
            stage["review_of"] = s.review_of
        for key in ("attack_of", "revise_of", "against"):  # brief 16
            if getattr(s, key) is not None:
                stage[key] = getattr(s, key)
        entry["stages"].append(stage)
    return entry


def own_work(preset):
    """[(slot, slot, agent)]: two slots of a (filled) preset that hold the same agent where one judges the other's
    work: the checker and the last stage, a check stage and the stage before it, a review and the stage it
    reviews (rules v2.21: build = check, lead = partner, a = b). Read from the preset, never from preset names."""
    owner = {n: s.name for s in preset.slots for n in s.stages}
    checker_slot = next((s.name for s in preset.slots if s.checker), None)
    agent_of = {s.name: s.agent for s in preset.slots}
    pairs = []

    def judged(judge, work, how="check"):
        if judge and work and judge != work and agent_of[judge] == agent_of[work]:
            if not any({work, judge} == {a, b} for a, b, *_ in pairs):
                pairs.append((work, judge, agent_of[judge]) if how == "check" else (work, judge, agent_of[judge], how))

    last = preset.stages[-1]
    if preset.checker is not None:
        judged(checker_slot, owner.get(last.n))
    if preset.check_stage is not None:
        judged(owner.get(last.n), owner.get(last.n - 1))
    for review in preset.review_stages:
        judged(owner.get(review.n), owner.get(review.review_of))
    if preset.attack_stage is not None:  # rules v2.23: an attacker never attacks its own build
        judged(owner.get(preset.attack_stage.n), owner.get(preset.attack_stage.attack_of), how="attack")
    return pairs


# Rules v2.28 (Relay, slots; Cursor): until rule 12 is met, Cursor may fill `versus` a or b and nothing else (it
# builds a candidate and reviews the other, and the owner picks). An agent not named here may fill any slot it is live
# for. Read by slot_refusals; the shipped presets never place Cursor. Widened later by a rules edit, not by code.
SLOTS_FOR = {"cursor": {"versus": ("a", "b")}}


def slot_allowed(agent, preset_name, slot):
    allowed = SLOTS_FOR.get(agent)
    return allowed is None or slot in allowed.get(preset_name, ())


# Rules v2.28, Cursor: a slot one of these agents fills is refused on a --project task (no handoff to Cursor).
PROJECT_REFUSES = ("cursor",)


def takes_project(preset):
    """Whether `--project` may run on the preset (rules v2.25, Relay): a named checker after a chain that ends in one
    agent's build; never a check stage, review stages or a tally. Intake and `sr status` both read it (brief 23,
    decision 14), so the page greys the project selector from the same rule intake applies."""
    return bool(preset.checker) and not getattr(preset, "has_reviews", False) and not getattr(preset, "tallies", False)


def _allowed_text(agent):
    return "; ".join(f"{name} {' or '.join(slots)}" for name, slots in SLOTS_FOR[agent].items())


def slot_refusals(preset, flags, roster, available=None):
    """(filled preset, []) for `--<slot> <agent>` flags ([(slot, agent or None)], in the order typed), or
    (None, [reason, ...]): each refusal of rules v2.21 in its own words. The caller still asks problems() of the
    filled preset (anything else a preset may not do). `available` (brief 24, decision 8): a function of an agent's name
    giving its availability; an agent that isn't available can't fill a slot, with the reason. None: the live flags."""
    names = [s.name for s in preset.slots]
    reasons, seen, chosen = [], set(), {}
    for slot, agent in flags:
        if slot not in names:
            have = f"its slots: {', '.join(names)}" if names else "it has no slots"
            reasons.append(f"{preset.name} has no slot {slot} ({have}).")
        elif slot in seen:
            reasons.append(f"--{slot} is named twice; a slot holds one agent.")
        elif agent is None or not agent.strip():
            reasons.append(f"--{slot} needs an agent: --{slot} <agent>.")
        elif agent not in roster.names:
            reasons.append(f"no agent named {agent} (agents: {', '.join(roster.names)}).")
        elif agent not in roster.live:
            reasons.append(f"{agent} is not live, so it can't fill slot {slot}.")
        elif available is not None and not available(agent).available:  # brief 24: a flag is never refilled
            reasons.append(f"{agent} can't fill slot {slot}: {available(agent).why}.")
        elif not slot_allowed(agent, preset.name, slot):  # rules v2.28, Cursor
            reasons.append(f"{agent} may fill {_allowed_text(agent)} only (rules v2.28, Cursor), not {preset.name} {slot}.")
        else:
            chosen[slot] = agent
        seen.add(slot)
    if reasons:
        return None, list(dict.fromkeys(reasons))
    filled = fill(preset, chosen)
    pairs = own_work(filled)
    if pairs:
        return None, [f"slots {p[0]} and {p[1]} both hold {p[2]}; "
                      + ("an attacker does not attack its own build." if len(p) > 3
                         else "no agent checks or reviews its own work.")
                      for p in pairs]
    return filled, []


def slot_names(path=None):
    """Every slot name config/presets.json declares, in file order, read raw (no checks); () when the file can't be
    read. `sr route` and `sr split` refuse these as flags (rules v2.21)."""
    try:
        doc = json.loads((path or PRESETS_PATH).read_text())
        found = []
        for entry in doc["presets"].values():
            for name in (entry.get("slots") or {}):
                if name not in found:
                    found.append(name)
        return tuple(found)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return ()


def slots_of(row):
    """A task row's stored slot map ({slot: agent}), or None (a row from before log version 10)."""
    raw = row["slots"] if "slots" in row.keys() else None
    return json.loads(raw) if raw else None


def for_task(row, loaded):
    """A relay task's filled preset, from its preset name and its stored slots: (preset, None), or (None, why
    not). Every reader of a task calls this, never the defaults (rules v2.21). A row with no slots (from before
    log version 10) ran with the defaults, so it gets the preset as it is."""
    name = row["preset"]
    if loaded is None:
        return None, f"config/presets.json could not be read, so its preset {name} is unknown"
    base = loaded.presets.get(name)
    if base is None:
        why = "; ".join(loaded.problems.get(name, [])) or "it is not in config/presets.json"
        return None, f"its preset {name} can't run: {why}"
    stored = slots_of(row)
    if not stored:
        return base, None
    names = [s.name for s in base.slots]
    if set(stored) - set(names):
        return None, f"its slots ({', '.join(stored)}) don't match preset {name}'s ({', '.join(names) or 'none'})"
    return fill(base, stored), None


def _parts(slot):
    numbers = list(slot.stages)
    words = ([f"stage{'s' if len(numbers) > 1 else ''} {', '.join(map(str, numbers))}"] if numbers else []) \
        + ([CHECKER_PART] if slot.checker else [])
    return ", ".join(words)


def describe(loaded):
    """The lines `sr relay --list` prints: each preset, its stages and its checker (or its check
    stage); a bad one marked BAD with every reason."""
    lines = [f"Presets ({PRESETS_PATH.name}, version {loaded.version}):"]
    for name in loaded.names:
        if name in loaded.presets:
            preset = loaded.presets[name]
            lines.append(name)
            for s in preset.stages:
                notes = ([f"input: {'task' if s.input == TASK_INPUT else f'stage {s.input_stage}'}"] if s.input else []) \
                    + ([f"contract {s.contract}"] if s.contract else [])
                tail = f" ({', '.join(notes)})" if notes else ""
                what = (f"review of stage {s.review_of}" if s.review_of is not None
                        else f"attack of stage {s.attack_of}" if s.attack_of is not None
                        else f"revise of stage {s.revise_of} against stage {s.against}" if s.revise_of is not None
                        else s.role)
                lines.append(f"  {s.n}. {what} by {s.agent}{tail}")
            check = preset.check_stage
            if preset.has_reviews:
                lines.append(f"  pick: {preset.pick}")
            elif preset.tallies:
                lines.append(f"  pick: {preset.pick} (code counts the answers; no majority: you pick)")
            else:
                lines.append(f"  check: stage {check.n} ({check.agent})" if check else f"  checker: {preset.checker}")
            if preset.slots:
                lines.append("  slots: " + ", ".join(f"{s.name} ({_parts(s)}) {s.default}" for s in preset.slots))
        else:
            lines.append(f"{name}: BAD")
            lines += [f"  - {p}" for p in loaded.problems[name]]
    if any(p.slots for p in loaded.presets.values()):
        lines.append('Fill a slot for one task: sr relay <preset> "task" --<slot> <agent>')
    return lines


# ---------- build brief 24 (decision 8): a slot whose default agent isn't available is filled at intake ----------

FILL_VERBS = {"research": "research", "build": "build", "plan": "plan", "amend": "amend the plan", "execute": "build",
              "edit": "check", "review": "review", "attack": "attack", "revise": "revise", "vote": "vote"}


def fill_candidates(agent):
    """Decision 8: the other of Claude and ChatGPT; for a Grok slot (and any other agent's, C14), ChatGPT then Claude."""
    if agent in ("claude", "chatgpt"):
        return ["chatgpt" if agent == "claude" else "claude"]
    return ["chatgpt", "claude"]


def _verb(preset, slot):
    if not slot.stages:
        return "check"
    return FILL_VERBS.get(preset.stage(slot.stages[0]).role, "take it")


def _judged(preset, flags, roster, available, send_paths, contracts, roles, verdicts):
    """(filled, []) when the flags give a preset that may run, else (None, [reasons])."""
    filled, refused = slot_refusals(preset, flags, roster, available)
    if not refused:
        refused = problems(filled.name, as_entry(filled), roster, send_paths, contracts, roles=roles, verdicts=verdicts)
    return (filled, []) if not refused else (None, refused)


def fill_unavailable(preset, flags, roster, available, *, send_paths, contracts, roles=None, verdicts=()):
    """Decision 8 at intake: (filled preset, fills, None) or (None, [], why not). `flags` are the slots set by
    `--<slot> <agent>` ([(slot, agent)]), never refilled. Every other slot whose agent isn't available is filled from
    `fill_candidates`, trying the combinations in that order; the first that `slot_refusals` and `problems()` both pass
    is the task's preset. `fills` is [{"slot", "agent", "default", "why"}]. With no combination left, the words name the
    slot, why its agent can't run, and why no other agent can take it."""
    flagged = {slot for slot, _ in flags}
    need = [s for s in preset.slots if s.name not in flagged and not available(s.agent).available]
    if not need:
        filled, refused = _judged(preset, list(flags), roster, available, send_paths, contracts, roles, verdicts)
        return (filled, [], None) if filled is not None else (None, [], refused[0])
    options = [fill_candidates(s.agent) for s in need]
    for combo in _combinations(options):
        tried = list(flags) + [(s.name, a) for s, a in zip(need, combo)]
        if any(not available(a).available for a in combo):
            continue
        filled, refused = _judged(preset, tried, roster, available, send_paths, contracts, roles, verdicts)
        if filled is not None:
            fills = [{"slot": s.name, "agent": a, "default": s.agent, "why": available(s.agent).why}
                     for s, a in zip(need, combo)]
            return filled, fills, None
    return None, [], _no_fill_words(preset, flags, need, roster, available, send_paths, contracts, roles, verdicts)


def _combinations(options):
    if not options:
        yield ()
        return
    for first in options[0]:
        for rest in _combinations(options[1:]):
            yield (first,) + rest


def _no_fill_words(preset, flags, need, roster, available, send_paths, contracts, roles, verdicts):
    """Why no agent can take a slot, in words: the first slot (in the preset's order) whose every candidate is either not
    available or breaks a slot rule against the slots as they stand. `vote can't run now: slot c (Grok Bot): Grok Bot
    isn't set up: ...; no other agent can vote there (ChatGPT is in slot b; Claude is in slot a)`."""
    from router import availability
    current = dict(slot_map(preset))
    current.update(dict(flags))
    blocker, details = None, []
    for slot in need:
        reasons = []
        for agent in fill_candidates(slot.agent):
            found = available(agent)
            if not found.available:
                reasons.append(found.why)
                continue
            filled, refused = _judged(preset, list(flags) + [(slot.name, agent)], roster, available, send_paths, contracts,
                                      roles, verdicts)
            if filled is not None:
                reasons = None
                break
            other = next((name for name, held in current.items() if held == agent and name != slot.name), None)
            reasons.append(f"{availability.name_of(agent)} is in slot {other}" if other else refused[0].rstrip("."))
        if reasons is not None:
            blocker, details = slot, reasons
            break
    blocker = blocker or need[0]
    why = available(blocker.agent).why
    tail = f" ({'; '.join(details)})" if details else ""
    return (f"{preset.name} can't run now: slot {blocker.name} ({availability.name_of(blocker.agent)}): {why}; no other "
            f"agent can {_verb(preset, blocker)} there{tail}")


FILLED = " filled by "


def fills_reason(fills):
    """The route_reason of a relay task (C6): `relay`, or `relay; <slot> filled by <agent>: <why>`, the fills joined by
    ` · ` (a mark no reason of the router's uses)."""
    if not fills:
        return "relay"
    return "relay; " + " · ".join(f"{f['slot']}{FILLED}{f['agent']}: {f['why']}" for f in fills)


def fills_of(route_reason):
    """[{"slot", "agent", "why"}] read back from a relay task's route_reason; [] when nothing was filled."""
    text = route_reason or ""
    if not text.startswith("relay; "):
        return []
    found = []
    for part in text[len("relay; "):].split(" · "):
        head, _, why = part.partition(": ")
        slot, _, agent = head.partition(FILLED)
        if slot and agent:
            found.append({"slot": slot, "agent": agent, "why": why})
    return found
