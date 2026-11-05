"""The one command builder (build brief 23, decisions 3, 4 and 12). A structured request from the page becomes the
argument list that follows `sr`, and its display, here in Python; the page never assembles a command. The server uses
it for the live command line (`POST /api/command`: the argv and its display, nothing run) and for the run
(`POST /api/run`), so what the page shows is what runs.

Every argv carries `--json`, and `--source ui` where the command takes it (route, relay and, since brief 29, split). Typed text goes after `--`, as one argument, byte for byte, so `--skill coding` or `-h` typed in the box is text,
never a flag. Any other value that starts with `-` or holds a control character is refused before anything runs. The
team, slots, agents and skills are checked against the current `sr status --json`; refs are task ids, never `#n`. A
file must sit at the drop folder's top level: the page attaches only what it dropped there (decision 8). The display
shows `sr` in place of the interpreter, quotes with `shlex.join` so a pasted copy is safe in a shell (a `$5` stays
`$5`), and marks the flags the page adds; Copy leaves those out, as a person would type it."""
import re
import shlex
import unicodedata
from dataclasses import dataclass, field

from router import drop, projects

TASK_ID = re.compile(r"sr-\d{8}-\d{6}-[0-9a-f]{4}")
ADDED = ("--json", "--source", "ui")            # the flags the page adds; dimmed on the command line, left out of Copy
ACTIONS = ("send", "floor", "pick", "resume", "fallback", "cancel", "check", "split_go", "split_skip",
           "split_edit",  # brief 29 (decision 8): `sr split --edit`, a piece's text or team before the approval
           "project_new",  # brief 26 (decision 9): `sr project new`
           "memory_switch",  # brief 27 (decision 10): `sr memory on|off`
           # brief 28 (decision 20): the router's own writes in a project, every one by the router, none by the page
           "land", "undo", "discard", "project_files", "project_git", "project_tests",
           # brief 30 (decisions 8 and 12 to 15): the router notes' save, a project's notes, a pin, a save into a
           # project, and Forget or Remember again; the typed text is one argument after `--`, never on the command line
           "notes_save", "project_notes_save", "project_pin", "project_save", "forget",
           "project_spec_save",  # brief 33.2 (decision 4): the Spec section of a project's Notes sheet
           # brief 31 (decisions 1 and 2): Test, on a throwaway copy of the project's head, in the sandbox; (decisions 3
           # to 7) the run command, Run (in the project's real folder, on the owner's click) and Stop
           "project_test", "project_run_command", "project_run", "project_stop",
           # brief 31 (decisions 8 and 9): a secret set (its value on stdin) or removed
           "project_secret_set", "project_secret_remove",
           # brief 33 (decisions 15 and 16): an idea added (Add, or Later on a card's chip) or dismissed
           "ideas_add", "ideas_dismiss", "ideas_suggest",
           # brief 33.1 (decision 11): one change to a plan's step before the approval (Plan itself is a send's team)
           "plan_edit", "plan_answer",
           # brief 33.3 (decisions 6 and 12): Setup's Models row: a default of the owner's own set or cleared, the Fable switch
           "models_set", "models_clear", "models_fable",
           # brief 34 (decisions 10 and 13): the Auto switch (on behind the page's confirm, off at once) and a step's stop-here
           "auto_on", "auto_off", "plan_stop_here")
PLAN_CHANGES = ("text", "done_when", "team", "up", "down", "drop", "covers")  # brief 33.1 (decision 11): one per command; 33.2: covers
STEP = re.compile(r"(sr-\d{8}-\d{6}-[0-9a-f]{4}):([0-9]{1,3})")  # brief 33.1 (decision 12): <plan task>:<k>
HASH = re.compile(r"[0-9a-f]{16}")  # brief 30: `--expect`, the hash `sr notes` and `sr project notes` give
SAVE_PATH_CHARS = 200  # decision 14: a saved file's path, at most this long (the router checks every other rule)
TESTS_LIMIT = 300  # characters, as `sr project tests` keeps them
SECRET_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")  # brief 31 (decision 8), as the router checks it
SECRET_LIMIT = 4096
MODEL_AGENTS = ("claude", "chatgpt", "cursor")  # brief 33.3: the agents with a model choice (the router's models.AGENTS)
MODEL_NAME = re.compile(r"[a-z][a-z0-9.-]{0,79}")  # a model id or alias, as the allowlists spell them (the router checks it too)
MODEL_WORD = re.compile(r"[a-z][a-z0-9_-]{0,39}")  # a team, role or skill word in a selector
PICKS = ("a", "b", "c", "none")
ANSWERS = ("y", "n")


class Refused(ValueError):
    """A request the builder will not turn into a command (HTTP 400 with the reason). Nothing ran."""


@dataclass(frozen=True)
class Command:
    args: tuple                 # what follows `sr`
    added: frozenset = frozenset()  # positions in `args` the page added (--json, --source ui)
    hidden: tuple = ()          # brief 30 (decision 10): (position, what) of a text shown by its length, never itself
    # brief 31 (decision 9): a secret's value, handed to the command on stdin and nowhere else: never an argument, never in
    # this object's repr, never shown; `note` says how long it is
    stdin: object = field(default=None, repr=False, compare=False)

    def note(self):
        if self.stdin is None:
            return None
        return f"(the value goes on stdin: {len(self.stdin):,} characters, never shown)"

    def _shown(self, i, a):
        if self.hidden and i == self.hidden[0]:
            return f"<{self.hidden[1]}, {len(a):,} characters>"
        return shlex.quote(a)

    def display(self):
        return " ".join(["sr", *(self._shown(i, a) for i, a in enumerate(self.args))])

    def copy(self):
        return " ".join(["sr", *(self._shown(i, a) for i, a in enumerate(self.args) if i not in self.added)])

    def parts(self):
        """Each shown token, quoted, with whether the page added it (the page dims those)."""
        return [{"text": "sr", "added": False}] + [{"text": self._shown(i, a), "added": i in self.added}
                                                   for i, a in enumerate(self.args)]


def _control(text):
    return any(unicodedata.category(c) == "Cc" for c in text)


def _value(value, what):
    """A flag's value: a non-empty string that does not start with `-` and holds no control character."""
    if not isinstance(value, str) or not value:
        raise Refused(f"{what} must be text")
    if value.startswith("-"):
        raise Refused(f"{what} starts with -: {value[:40]!r}")
    if _control(value):
        raise Refused(f"{what} holds a control character")
    return value


def _text(value):
    """Typed text: anything, byte for byte, except what no command line can carry (a NUL)."""
    if not isinstance(value, str):
        raise Refused("the text must be text")
    if "\x00" in value:
        raise Refused("the text holds a NUL character, which no command line can carry")
    return value


def project_name(value):
    """Brief 26 (decisions 9 and 10): a project name the router's name rule takes, that is also a plain flag value."""
    if not isinstance(value, str) or not projects.NAME.fullmatch(value):
        raise Refused("the project name is lower case letters, digits and - only")
    return _value(value, "the project name")


def _project_new(request):
    """`sr project new --json <name> [-- <notes>]`: the notes as typed, one argument after `--` (they may hold newlines:
    the control-character rule is for flag values only), left off when empty."""
    args = ["project", "new", "--json", project_name(request.get("name"))]
    notes = request.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise Refused("the notes must be text")
    if notes:
        if "\x00" in notes:
            raise Refused("the notes hold a NUL character, which no command line can carry")
        args += ["--", notes]
    return Command(tuple(args), frozenset({2}))


def _project_files(request, status):
    """`sr project files --json <name> --file <path> …` (brief 28, decision 14): each file one the page dropped at the
    drop folder's top level, none twice."""
    args = ["project", "files", "--json", project_name(request.get("name"))]
    files = request.get("files")
    if not isinstance(files, list) or not files:
        raise Refused("name at least one dropped file")
    seen = set()
    for path in files:
        _value(path, "a file")
        if not drop.at_top_level(status.get("drop_folder"), path):
            raise Refused("a file must be one the page dropped at the drop folder's top level")
        if path in seen:
            raise Refused("a file is named twice")
        seen.add(path)
        args += ["--file", path]
    return Command(tuple(args), frozenset({2}))


def _project_tests(request):
    """`sr project tests --json <name> -- <words>` or `--clear` (brief 28, decision 17): the words as typed, one
    argument after `--`; the router splits them as a shell would and never runs them through one."""
    name = project_name(request.get("name"))
    if request.get("clear") is True:
        if request.get("words") not in (None, ""):
            raise Refused("clear the command or give words, not both")
        return Command(("project", "tests", "--json", "--clear", name), frozenset({2}))
    words = request.get("words")
    if not isinstance(words, str) or not words.strip():
        raise Refused("type the test command, or clear it")
    if len(words) > TESTS_LIMIT:
        raise Refused(f"the test command is {len(words):,} characters; at most {TESTS_LIMIT}")
    if _control(words):
        raise Refused("the test command holds a control character")
    return Command(("project", "tests", "--json", name, "--", words), frozenset({2}))


def _expect(value):
    """Brief 30 (decisions 8 and 12): the hash the page read the notes with, so a save never overwrites an edit made
    meanwhile."""
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise Refused("the notes' hash must be the one the router gave (16 hex characters)")
    return value


def _notes_text(value, what):
    """A notes text, byte for byte (newlines kept), one argument after `--`; the router checks the rest."""
    if not isinstance(value, str):
        raise Refused(f"{what} must be text")
    if "\x00" in value:
        raise Refused(f"{what} hold a NUL character, which no command line can carry")
    return value


def _notes_save(request):
    """Brief 30 (decision 8): `sr notes save --json --expect <hash> -- <the whole file>`; shown by its length."""
    args = ("notes", "save", "--json", "--expect", _expect(request.get("expect")), "--",
            _notes_text(request.get("text"), "the router notes"))
    return Command(args, frozenset({2}), (6, "the notes"))


def _project_notes_save(request):
    """Brief 30 (decision 12): `sr project notes --json <name> --save --expect <hash> -- <the notes>`."""
    args = ("project", "notes", "--json", project_name(request.get("name")), "--save", "--expect",
            _expect(request.get("expect")), "--", _notes_text(request.get("text"), "the notes"))
    return Command(args, frozenset({2}), (8, "the notes"))


def _project_spec_save(request):
    """Brief 33.2 (decision 4): `sr project spec --json <name> --save --expect <hash> -- <the spec>`."""
    args = ("project", "spec", "--json", project_name(request.get("name")), "--save", "--expect",
            _expect(request.get("expect")), "--", _notes_text(request.get("text"), "the spec"))
    return Command(args, frozenset({2}), (8, "the spec"))


def _project_pin(request):
    """Brief 30 (decision 13): `sr project pin --json <name> --task <task_id> -- <text>`; the text as the sheet holds it."""
    text = _notes_text(request.get("text"), "the text")
    if not text.strip():
        raise Refused("pin some text: select it in the result, or keep the whole result")
    args = ("project", "pin", "--json", project_name(request.get("name")), "--task", _task_id(request.get("task_id")),
            "--", text)
    return Command(args, frozenset({2}), (7, "the text"))


def _project_save(request):
    """Brief 30 (decision 14): `sr project save --json <name> --task <task_id> --path <path>`; the router checks the path's
    rules (relative, inside the folder, .md or .txt, no part starting with ., not HANDOFF.md)."""
    path = _value(request.get("path"), "the path")
    if len(path) > SAVE_PATH_CHARS:
        raise Refused(f"the path is {len(path):,} characters; at most {SAVE_PATH_CHARS}")
    args = ("project", "save", "--json", project_name(request.get("name")), "--task", _task_id(request.get("task_id")),
            "--path", path)
    return Command(args, frozenset({2}))


def _task_id(value, what="the task"):
    if not isinstance(value, str) or not TASK_ID.fullmatch(value):
        raise Refused(f"{what} must be a task id (sr-YYYYMMDD-HHMMSS-xxxx), not {str(value)[:40]!r}")
    return value


def _skill(value, status):
    keys = [s.get("key") for s in status.get("skills") or []]
    if value not in keys:
        raise Refused(f"no skill {str(value)[:40]}; the skills are {', '.join(k for k in keys if k)}")
    return value


def _presets(status):
    return {p.get("name"): p for p in status.get("presets") or [] if isinstance(p, dict)}


def _head(*words):
    """The command's words, then the page's own flags, with their positions marked."""
    args = list(words) + list(ADDED)
    return args, set(range(len(words), len(args)))


def _tag(request):
    found = []
    if request.get("chat") is not None:
        found += ["--chat", _value(request["chat"], "the chat")]
    if request.get("project") is not None:
        found += ["--project", _value(request["project"], "the project")]
    return found


def _carried(request):
    """Brief 33 (decisions 8 and 16): `--from <task_id>`, the earlier result the task builds from, and `--idea <id>`, the
    project idea it is sent from, each from its pill in the composer. Brief 33.1 (decision 12): `--step <plan>:<k>`, the
    Step pill, with the project only."""
    found = []
    if request.get("from") is not None:
        found += ["--from", _task_id(request.get("from"), "the earlier task")]
    if request.get("idea") is not None:
        found += ["--idea", _idea_id(request.get("idea"))]
    if request.get("step") is not None:
        step = request.get("step")
        if not isinstance(step, str) or not STEP.fullmatch(step):
            raise Refused("a step is <plan task id>:<its number>, as the Step pill carries it")
        if request.get("project") is None:
            raise Refused("a step goes with its project")
        found += ["--step", step]
    return found


def _idea_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise Refused(f"an idea is its number, not {str(value)[:40]!r}")
    return str(value)


def _split_send(request, text, model_flags=()):
    """Brief 29 (decision 1): `sr split --json --source ui [--project <name>] -- <text>`. A split carries no slots (a
    piece's agents are its team's), no files, no web and never a chat tag, and Jev labels each piece, so no skill. Brief
    33.3: a model choice reaches its plan and its join."""
    if request.get("slots"):
        raise Refused("a split takes no slots: each piece runs with its team's agents")
    if request.get("files"):
        raise Refused("files go on Route only: a split carries no files")
    if request.get("web"):
        raise Refused("web goes on Route only")
    if request.get("chat") is not None:
        raise Refused("a split never carries a chat tag")
    if request.get("skill") is not None:
        raise Refused("a split takes no skill: Jev labels each piece once Claude plans them")
    if request.get("from") is not None:  # brief 33 (decision 8)
        raise Refused("a split builds from no earlier result: --from goes on Route or a team")
    if request.get("idea") is not None:  # brief 33 (decision 16)
        raise Refused("a split isn't sent from an idea: send it on Route or a team")
    args, marks = _head("split")
    if request.get("project") is not None:
        args += ["--project", _value(request["project"], "the project")]
    args += list(model_flags)
    return Command(tuple(args + ["--", text]), frozenset(marks))


def _split_edit(request, status):
    """Brief 29 (decision 8): `sr split --json --edit <task> --piece <k> [--team <team>] [-- <text>]`: a team named in
    status's split menu, the new text as typed after `--`, at least one of the two."""
    task = _task_id(request.get("task_id"))
    piece = request.get("piece")
    if isinstance(piece, bool) or not str(piece).isdigit() or not 1 <= int(piece) <= 4:
        raise Refused("a piece is 1 to 4")
    args = ["split", "--json", "--edit", task, "--piece", str(int(piece))]
    team, text, slots = request.get("team"), request.get("text"), request.get("slots")
    if team is None and text is None and not slots:
        raise Refused("give a team, a slot or a new text for the piece")
    if team is not None:
        names = [t.get("name") for t in ((status.get("split") or {}).get("teams") or []) if isinstance(t, dict)]
        if team not in names:
            raise Refused(f"no team {str(team)[:40]}; a piece may take {', '.join(n for n in names if n)}")
        args += ["--team", _value(team, "the team")]
    if slots:  # brief 29.1 (decision 12): {slot: agent or "default"}, each `--slot <slot>=<agent>`; the router checks them
        if not isinstance(slots, dict):
            raise Refused("slots are {slot: agent}")
        for slot, agent in slots.items():
            if not (isinstance(slot, str) and re.fullmatch(r"[a-z][a-z0-9-]*", slot)
                    and isinstance(agent, str) and re.fullmatch(r"[a-z][a-z0-9_-]*", agent)):
                raise Refused("a slot and its agent are plain lowercase words")
            args += ["--slot", f"{slot}={agent}"]
    if text is not None:
        args += ["--", _text(text)]
    return Command(tuple(args), frozenset({1}))


def _plan_send(request, text, model_flags=()):
    """Brief 33.1 (decision 1): `sr plan --json --source ui --project <name> [--from <task>] [--idea <id>] -- <text>`. A plan
    is on a project only and takes no slots, files, web, chat, skill or step: the router refuses each (`plan_refused`);
    the page never builds one. Brief 33.2 (decision 12): an idea rides as `--idea`, checked by the router."""
    for key, why in (("slots", "a plan takes no slots: it runs redteam's chain as it is filled now"),
                     ("files", "files go on Route only: a plan carries no files"), ("web", "web goes on Route only"),
                     ("chat", "a plan is on a project, never in a chat"), ("skill", "a plan takes no skill"),
                     ("step", "a plan is no step of a plan")):
        if request.get(key):
            raise Refused(why)
    if request.get("project") is None:
        raise Refused("Plan works on a project: pick one")
    args, marks = _head("plan")
    args += ["--project", _value(request["project"], "the project")]
    if request.get("from") is not None:
        args += ["--from", _task_id(request.get("from"), "the earlier task")]
    if request.get("idea") is not None:  # brief 33.2 (decision 12): Add to plan, the Idea pill
        args += ["--idea", _idea_id(request.get("idea"))]
    args += list(model_flags)  # brief 33.3 (decision 4): an agent of redteam's chain as filled now
    return Command(tuple(args + ["--", text]), frozenset(marks))


def _plan_answer(request):
    """Brief 33.4 (decisions 5 and 14): `sr plan --json --source ui --answer <task>` with `--pick <k>=<letter>` and `--other
    <k>=<words>`, or `--best-guess`. Each typed answer is one argument, never through a shell; the router checks them."""
    args, marks = _head("plan")
    args += ["--answer", _task_id(request.get("task_id"), "the plan")]
    if request.get("best_guess") is True:
        return Command(tuple(args + ["--best-guess"]), frozenset(marks))
    picks, others = request.get("picks") or {}, request.get("others") or {}
    if not isinstance(picks, dict) or not isinstance(others, dict) or not picks and not others:
        raise Refused("answers are {question number: letter} and {question number: words}")
    for flag, found in (("--pick", picks), ("--other", others)):
        for k, value in found.items():
            if not re.fullmatch(r"[1-3]", str(k)):
                raise Refused("a plan asks at most 3 questions")
            if flag == "--pick" and not (isinstance(value, str) and re.fullmatch(r"[A-D]", value)):
                raise Refused("a picked answer is a letter, A to D")
            args += [flag, f"{k}={_text(value)}"]
    return Command(tuple(args), frozenset(marks))


def _plan_edit(request):
    """Brief 33.1 (decision 11): `sr plan --json --edit <task> --step <k>` with one of `--team <team>`, `--up`, `--down`,
    `--drop`, or `--text`/`--done-when` with the words as one argument after `--`. The router checks the change."""
    task = _task_id(request.get("task_id"), "the plan")
    step = request.get("step")
    if isinstance(step, bool) or not isinstance(step, int) or not 1 <= step <= 99:
        raise Refused("a step is its number in the plan")
    change, value = request.get("change"), request.get("value")
    if change not in PLAN_CHANGES:
        raise Refused(f"a plan's change is one of {', '.join(PLAN_CHANGES)}")
    args = ["plan", "--json", "--edit", task, "--step", str(step)]
    if change == "team":
        args += ["--team", _value(value, "the team")]
    elif change in ("text", "done_when", "covers"):
        args += [{"text": "--text", "done_when": "--done-when", "covers": "--covers"}[change], "--", _text(value)]
    else:
        if value is not None:
            raise Refused(f"--{change} takes no value")
        args.append(f"--{change}")
    return Command(tuple(args), frozenset({1}))


def _send(request, status):
    team, text = request.get("team"), _text(request.get("text"))
    if team == "split":  # brief 29 (decision 1): the last team
        return _split_send(request, text, _models_flags(request, status))
    if team == "plan":  # brief 33.1 (decision 1): after Split, on a project only
        return _plan_send(request, text, _models_flags(request, status))
    slots, files, web = request.get("slots") or {}, request.get("files") or [], request.get("web")
    model_flags = _models_flags(request, status)  # brief 33.3 (decision 4): the Models sheet's choices, on every team
    if team == "route":
        if slots:
            raise Refused("slots go on a team, not on Route")
        args, marks = _head("route")
        args += _tag(request) + _carried(request) + model_flags
        skill = request.get("skill")
        if skill is not None:  # brief 24 (decision 13): without Jev the page asks you for the skill first
            keys = [s.get("key") for s in status.get("skills") or [] if isinstance(s, dict)]
            if skill not in keys:
                raise Refused(f"no skill {str(skill)[:40]}; the skills are {', '.join(k for k in keys if k)}")
            args += ["--skill", skill]
        for path in files:
            _value(path, "a file")
            if not drop.at_top_level(status.get("drop_folder"), path):
                raise Refused("a file must be one the page dropped at the drop folder's top level")
            args += ["--file", path]
        if web:
            args.append("--web")
        if request.get("no_files"):  # brief 33.2 (decision 5): the Draft chip's text-only task
            if request.get("project") is None:
                raise Refused("text only goes with a project")
            args.append("--no-files")
        return Command(tuple(args + ["--", text]), frozenset(marks))
    preset = _presets(status).get(team)
    if preset is None:
        raise Refused(f"no team {str(team)[:40]}; the teams are Route and {', '.join(_presets(status))}")
    if files:
        raise Refused("files go on Route only: a team task carries no files")
    if web:
        raise Refused("web goes on Route only")
    if request.get("no_files"):  # brief 33.2 (decision 5)
        raise Refused("text only goes on Route")
    if not isinstance(slots, dict):
        raise Refused("slots must map a slot to an agent")
    by_name = {s.get("name"): s for s in preset.get("slots") or []}
    for slot, agent in slots.items():
        if slot not in by_name:
            raise Refused(f"no slot {str(slot)[:40]} on {team}; its slots are {', '.join(by_name)}")
        if agent not in (by_name[slot].get("allowed") or []):
            raise Refused(f"{str(agent)[:40]} can't fill slot {slot} on {team}")
    args, marks = _head("relay", team)
    for name in by_name:  # the preset's own slot order, so the command line is stable
        if name in slots:
            args += [f"--{name}", slots[name]]
    args += _tag(request) + _carried(request) + model_flags
    return Command(tuple(args + ["--", text]), frozenset(marks))


def _models_flags(request, status):
    """Brief 33.3 (decision 4): `--model <agent>=<model>` per chosen agent from the Models sheet, in agent order (so the
    line is stable): only an agent with a model choice, a plain name, and, where status carries the allowlists, a name on
    that agent's; the router checks it all again at intake (`bad_model`, nothing written)."""
    chosen = request.get("models")
    if chosen in (None, {}):
        return []
    if not isinstance(chosen, dict):
        raise Refused("models map an agent to a model")
    lists = (status.get("models") or {}).get("agents") or {}
    found = []
    for agent in sorted(chosen):
        model = chosen[agent]
        if agent not in MODEL_AGENTS:
            raise Refused(f"{str(agent)[:40]} has no model choice; the agents are {', '.join(MODEL_AGENTS)}")
        if not isinstance(model, str) or not MODEL_NAME.fullmatch(model):
            raise Refused(f"a model is a plain name, like claude-opus-5-5 (for {agent})")
        doc = lists.get(agent) if isinstance(lists.get(agent), dict) else {}
        names = list(doc.get("allowed") or []) + list((doc.get("aliases") or {}).keys())
        if names and model not in names:
            raise Refused(f"{model} isn't on {agent}'s allowed list ({', '.join(doc.get('allowed') or [])})")
        found += ["--model", f"{agent}={model}"]
    return found


def _models_default(request, status, *, clear):
    """Brief 33.3 (decision 12): Setup's selects: `sr models set --json <selector> --agent <agent> --model <model>`, or
    `sr models clear --json <selector> --agent <agent>` for Default; the selector a skill (a key in status), a team and
    role, or a team and stage; the router checks every word again."""
    selector = request.get("selector")
    if not isinstance(selector, dict):
        raise Refused("a selector is {skill}, {team, role} or {team, stage}")
    agent = request.get("agent")
    if agent not in MODEL_AGENTS:
        raise Refused(f"{str(agent)[:40]} has no model choice; the agents are {', '.join(MODEL_AGENTS)}")
    args = ["models", "clear" if clear else "set", "--json"]
    keys = set(selector)
    if keys == {"skill"}:
        args += ["--skill", _skill(selector["skill"], status)]
    elif keys == {"team", "role"}:
        args += ["--team", _word(selector["team"], "the team"), "--role", _word(selector["role"], "the role")]
    elif keys == {"team", "stage"}:
        stage = selector["stage"]
        if isinstance(stage, bool) or not str(stage).isdigit() or not 1 <= int(str(stage)) <= 12:
            raise Refused("a stage is 1 to 12")
        args += ["--team", _word(selector["team"], "the team"), "--stage", str(int(str(stage)))]
    else:
        raise Refused("a selector is {skill}, {team, role} or {team, stage}")
    args += ["--agent", agent]
    if clear:
        if request.get("model") is not None:
            raise Refused("a clear takes no model")
    else:
        model = request.get("model")
        if not isinstance(model, str) or not MODEL_NAME.fullmatch(model):
            raise Refused("a model is a plain name, like claude-opus-5-5")
        args += ["--model", model]
    return Command(tuple(args), frozenset({2}))


def _word(value, what):
    if not isinstance(value, str) or not MODEL_WORD.fullmatch(value):
        raise Refused(f"{what} is a plain lowercase word")
    return value


def build(request, status):
    """The Command for `request` (a dict from the page), checked against `status` (`sr status --json`)."""
    if not isinstance(status, dict):
        raise Refused("the router's status could not be read, so nothing can be checked or run")
    if not isinstance(request, dict):
        raise Refused("the request must be an object")
    action = request.get("action")
    if action not in ACTIONS:
        raise Refused(f"no action {str(action)[:40]}; the page runs {', '.join(ACTIONS)}")
    if action == "send":
        return _send(request, status)
    if action == "floor":  # decision 12: the row's text with --skill and --answers, nothing else
        args, marks = _head("route")
        args += ["--skill", _skill(request.get("skill"), status), "--answers", _task_id(request.get("answers"), "the floor row"),
                 "--", _text(request.get("text"))]
        return Command(tuple(args), frozenset(marks))
    if action == "check":
        return Command(("check", "--json"), frozenset({1}))
    if action == "split_edit":
        return _split_edit(request, status)
    if action == "plan_answer":  # brief 33.4 (decision 14): the questions card
        return _plan_answer(request)
    if action == "plan_edit":  # brief 33.1 (decision 11)
        return _plan_edit(request)
    if action == "project_new":
        return _project_new(request)
    if action == "project_files":
        return _project_files(request, status)
    if action == "project_git":  # brief 28 (decision 15): Turn on undo, after its dry run (`/api/project-git-check`)
        return Command(("project", "git", "--json", project_name(request.get("name"))), frozenset({2}))
    if action == "project_tests":
        return _project_tests(request)
    if action == "notes_save":  # brief 30: the Setup sheet's Router notes editor
        return _notes_save(request)
    if action == "project_notes_save":  # brief 30: a project's Notes editor
        return _project_notes_save(request)
    if action == "project_spec_save":  # brief 33.2 (decision 4): the Spec section
        return _project_spec_save(request)
    if action == "project_pin":  # brief 30: Pin to notes on a result card
        return _project_pin(request)
    if action == "project_save":  # brief 30: Save to project on a done card
        return _project_save(request)
    if action == "ideas_add":  # brief 33 (decision 15): the line as typed, one argument after `--`; Later names its card
        name = project_name(request.get("name"))
        args = ["ideas", "--json", name, "--add"]
        if request.get("source") is not None:
            args += ["--source", _task_id(request.get("source"), "the card")]
        return Command(tuple(args + ["--", _text(request.get("text"))]), frozenset({1}))
    if action == "ideas_suggest":  # brief 33.4 (decision 13): runs at once; a suggest changes no file
        return Command(("ideas", "--json", project_name(request.get("name")), "--suggest"), frozenset({1}))
    if action == "ideas_dismiss":  # brief 33 (decision 16): the page asks once before it sends this
        return Command(("ideas", "--json", project_name(request.get("name")), "--dismiss", _idea_id(request.get("id"))),
                       frozenset({1}))
    if action == "project_test":  # brief 31 (decision 1): no confirm, it changes nothing in the project
        return Command(("project", "test", "--json", project_name(request.get("name"))), frozenset({2}))
    if action == "project_run_command":  # brief 31 (decision 3): the words as typed, one argument after `--`
        name = project_name(request.get("name"))
        if request.get("clear") is True:
            if request.get("words") not in (None, ""):
                raise Refused("clear the command or give words, not both")
            return Command(("project", "run-command", "--json", "--clear", name), frozenset({2}))
        words = request.get("words")
        if not isinstance(words, str) or not words.strip():
            raise Refused("type the run command, or clear it")
        if len(words) > TESTS_LIMIT:
            raise Refused(f"the run command is {len(words):,} characters; at most {TESTS_LIMIT}")
        if _control(words):
            raise Refused("the run command holds a control character")
        return Command(("project", "run-command", "--json", name, "--", words), frozenset({2}))
    if action in ("project_secret_set", "project_secret_remove"):  # brief 31 (decisions 8 and 9)
        name = project_name(request.get("name"))
        key = request.get("key")
        if not isinstance(key, str) or not SECRET_NAME.fullmatch(key):
            raise Refused("a name is capital letters, digits and _ only, not starting with a digit (like DEMO_KEY)")
        if action == "project_secret_remove":
            if request.get("value") is not None:
                raise Refused("a remove takes no value")
            return Command(("project", "secrets", "--json", name, "--remove", key), frozenset({2}))
        value = request.get("value")
        if not isinstance(value, str):
            raise Refused("the value must be text")
        if "\x00" in value or "\n" in value or "\r" in value:
            raise Refused("the value must be one line, with no NUL")
        if len(value) > SECRET_LIMIT:
            raise Refused(f"the value is {len(value):,} characters; at most {SECRET_LIMIT:,}")
        return Command(("project", "secrets", "--json", name, "--set", key), frozenset({2}), stdin=value)
    if action in ("project_run", "project_stop"):  # brief 31 (decisions 4 to 7): each asks once on the page first
        return Command(("project", "run" if action == "project_run" else "stop", "--json",
                        project_name(request.get("name"))), frozenset({2}))
    if action == "forget":  # brief 30 (decision 15): Forget, or Remember again (`undo`)
        undo = request.get("undo")
        if undo not in (None, False, True):
            raise Refused("undo is true or false")
        return Command(("forget", "--json", _task_id(request.get("task_id")), *(("--undo",) if undo else ())),
                       frozenset({1}))
    if action in ("auto_on", "auto_off"):  # brief 34 (decision 10): the project's Auto switch; --on confirmed on the page first
        return Command(("auto", "--json", "--source", "ui", project_name(request.get("name")),
                        "--on" if action == "auto_on" else "--off"), frozenset({1, 2, 3}))
    if action == "plan_stop_here":  # brief 34 (decision 13): a step's Stop here toggle in the plan's panel
        step = request.get("step")
        if not isinstance(step, str) or not STEP.fullmatch(step):
            raise Refused("a step is <plan task id>:<its number>, as the plan's panel carries it")
        to = request.get("to")
        if to not in ("on", "off"):
            raise Refused("stop here goes on or off")
        return Command(("plan", "--json", "--source", "ui", "--stop-here", step, to), frozenset({1, 2, 3}))
    if action in ("models_set", "models_clear"):  # brief 33.3 (decision 12): Setup's Models selects
        return _models_default(request, status, clear=action == "models_clear")
    if action == "models_fable":  # brief 33.3 (decision 6): the Fable switch; any other `to` runs nothing
        to = request.get("to")
        if to not in ("on", "off"):
            raise Refused("the Fable switch goes on or off")
        return Command(("models", "fable", to, "--json"), frozenset({3}))
    if action == "memory_switch":  # brief 27 (decision 10): the Setup sheet's switch; any other `to` runs nothing
        to = request.get("to")
        if to not in ("on", "off"):
            raise Refused("the memory switch goes on or off")
        return Command(("memory", to, "--json"), frozenset({2}))
    task = _task_id(request.get("task_id"))
    if action == "pick":
        choice = request.get("choice")
        if choice not in PICKS:
            raise Refused("a pick is a, b, c or none")
        return Command(("pick", "--json", task, choice), frozenset({1}))
    if action in ("resume", "fallback", "cancel", "land", "undo", "discard"):  # brief 28: land, undo, discard by id
        anyway = request.get("anyway")
        if anyway not in (None, False, True) or (anyway and action != "land"):  # brief 29.1 (decision 21)
            raise Refused("anyway goes only with land, as true")
        return Command((action, "--json", task, *(("--anyway",) if anyway else ())), frozenset({1}))
    if action == "split_skip":
        return Command(("split", "--json", "--skip", task), frozenset({1}))
    choice, skills = request.get("choice"), request.get("skills") or {}
    if choice not in ANSWERS:
        raise Refused("a split plan's answer is y or n")
    if skills and choice != "y":
        raise Refused("a piece's skill goes only with y")
    if not isinstance(skills, dict):
        raise Refused("skills must map a piece number to a skill")
    args = ["split", "--json", "--go", task, "--answer", choice]
    for piece in sorted(skills, key=lambda k: int(k) if str(k).isdigit() else 0):
        if not str(piece).isdigit():
            raise Refused(f"{str(piece)[:20]!r} is not a piece number")
        args += ["--skill", f"{int(piece)}={_skill(skills[piece], status)}"]
    return Command(tuple(args), frozenset({1}))
