"""The one command builder (build brief 23, decisions 3, 4 and 12). A structured request from the page becomes the
argument list that follows `sr`, and its display, here in Python; the page never assembles a command. The server uses
it for the live command line (`POST /api/command`: the argv and its display, nothing run) and for the run
(`POST /api/run`), so what the page shows is what runs.

Every argv carries `--json`, and `--source ui` where the command takes it (route and relay; the page sends no split
task). Typed text goes after `--`, as one argument, byte for byte, so `--skill coding` or `-h` typed in the box is text,
never a flag. Any other value that starts with `-` or holds a control character is refused before anything runs. The
team, slots, agents and skills are checked against the current `sr status --json`; refs are task ids, never `#n`. A
file must sit at the drop folder's top level: the page attaches only what it dropped there (decision 8). The display
shows `sr` in place of the interpreter, quotes with `shlex.join` so a pasted copy is safe in a shell (a `$5` stays
`$5`), and marks the flags the page adds; Copy leaves those out, as a person would type it."""
import re
import shlex
import unicodedata
from dataclasses import dataclass

from router import drop, projects

TASK_ID = re.compile(r"sr-\d{8}-\d{6}-[0-9a-f]{4}")
ADDED = ("--json", "--source", "ui")            # the flags the page adds; dimmed on the command line, left out of Copy
ACTIONS = ("send", "floor", "pick", "resume", "fallback", "cancel", "check", "split_go", "split_skip",
           "project_new")  # brief 26 (decision 9): `sr project new`
PICKS = ("a", "b", "c", "none")
ANSWERS = ("y", "n")


class Refused(ValueError):
    """A request the builder will not turn into a command (HTTP 400 with the reason). Nothing ran."""


@dataclass(frozen=True)
class Command:
    args: tuple                 # what follows `sr`
    added: frozenset = frozenset()  # positions in `args` the page added (--json, --source ui)

    def display(self):
        return shlex.join(["sr", *self.args])

    def copy(self):
        return shlex.join(["sr", *(a for i, a in enumerate(self.args) if i not in self.added)])

    def parts(self):
        """Each shown token, quoted, with whether the page added it (the page dims those)."""
        return [{"text": "sr", "added": False}] + [{"text": shlex.quote(a), "added": i in self.added}
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


def _send(request, status):
    team, text = request.get("team"), _text(request.get("text"))
    slots, files, web = request.get("slots") or {}, request.get("files") or [], request.get("web")
    if team == "route":
        if slots:
            raise Refused("slots go on a team, not on Route")
        args, marks = _head("route")
        args += _tag(request)
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
        return Command(tuple(args + ["--", text]), frozenset(marks))
    preset = _presets(status).get(team)
    if preset is None:
        raise Refused(f"no team {str(team)[:40]}; the teams are Route and {', '.join(_presets(status))}")
    if files:
        raise Refused("files go on Route only: a team task carries no files")
    if web:
        raise Refused("web goes on Route only")
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
    args += _tag(request)
    return Command(tuple(args + ["--", text]), frozenset(marks))


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
    if action == "project_new":
        return _project_new(request)
    task = _task_id(request.get("task_id"))
    if action == "pick":
        choice = request.get("choice")
        if choice not in PICKS:
            raise Refused("a pick is a, b, c or none")
        return Command(("pick", "--json", task, choice), frozenset({1}))
    if action in ("resume", "fallback", "cancel"):
        return Command((action, "--json", task), frozenset({1}))
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
