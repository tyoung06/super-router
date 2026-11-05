"""Secrets (build brief 31, decisions 8 and 9): a project's `.env`, from the page, without a value ever being shown.

`sr project secrets <name>` lists the names in the project's `.env`, each set or empty, never a value. `--set <NAME>`
takes the value on stdin, never as an argument (one line, a trailing newline dropped, no NUL, at most 4,096 characters);
`--remove <NAME>` takes a name out. The file is written whole (a temp file, then a rename), mode 600, every other line
kept byte for byte (comments, order, blank lines); a new name goes at the end; the value is written so `dotenv_values`
reads back exactly what was sent (call 7: single quotes, or double quotes with `\\` and `"` escaped when the value holds
a `'`; a value it can't read back, such as one holding `${…}`, which python-dotenv expands inside either, is refused).
Under the project's lock, refused at once while another write holds it.

Refused, nothing written: a name that isn't `[A-Z_][A-Z0-9_]*`; a `.env` that is a link or not a plain file; on a
project with git, a `.env` that git tracks or doesn't ignore; the router's own folder (its `.env` is the router's, never
written from the page); a value with NUL or a second line. A value is never in an argument list, a log row, JSON, the
report, the live command line, the Run log or a run's output."""
import io
import os
import re
from pathlib import Path

from dotenv import dotenv_values
from dotenv.parser import parse_stream

from router import gitops, locks, projects, projrun, runs, safety

NAME = re.compile(r"[A-Z_][A-Z0-9_]*")
VALUE_LIMIT = 4096
_EXPORT = re.compile(r"^\s*export\s+")


class Refused(safety.SafeError):
    """A Secrets write the router won't make: the reason (never the value), nothing written."""


class Unknown(Refused):
    """No project by that name."""


def folder_of(name, *, router_root=None):
    """The project's folder, once it may have its `.env` read or written here; else Refused."""
    try:
        folder = projects.folder_of(name)
    except projects.ProjectError as e:
        raise Refused(str(e)) from None
    if folder is None:
        raise Unknown(f"no project {name}")
    if gitops.inside_router(folder, router_root) or (gitops.installed() and gitops.own_folder(folder, router_root)):
        raise Refused("this is the router's own folder: the router's own .env is never written from here")
    return Path(folder)


def names(folder):
    """The names in the project's `.env`, in file order, each set or empty: [{name, set}]. Never a value."""
    env = Path(folder) / ".env"
    if env.is_symlink() or not env.is_file():
        return []
    raw = dotenv_values(env, interpolate=False) or {}
    return [{"name": key, "set": bool(value)} for key, value in raw.items()]


def count(folder):
    """How many names the project's `.env` holds, or None when it has none (decision 11: never which)."""
    env = Path(folder) / ".env"
    if env.is_symlink() or not env.is_file():
        return None
    try:
        return len(dotenv_values(env, interpolate=False) or {})
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _quoted(value):
    if "'" not in value:
        return "'" + value + "'"
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def check_value(value):
    """Why the value can't be kept, or None. The reason never holds the value."""
    if not isinstance(value, str):
        return "the value must be text"
    if "\x00" in value:
        return "the value holds a NUL character"
    if "\n" in value or "\r" in value:
        return "the value must be one line"
    if len(value) > VALUE_LIMIT:
        return f"the value is {len(value):,} characters; at most {VALUE_LIMIT:,}"
    return None


def _line(key, value, export=False):
    line = f"{'export ' if export else ''}{key}={_quoted(value)}"
    if dotenv_values(stream=io.StringIO(line + "\n")) != {key: value}:
        raise Refused("the value can't be written so .env reads it back exactly: it holds ${…}, which .env readers "
                      "expand even inside quotes")
    return line


def _check_file(folder):
    problem = projrun.env_problem(folder, creating=True)
    if problem:
        raise Refused(problem)


def _write(env, text):
    temp = env.with_name(f".env.sr-{os.getpid()}.tmp")
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.chmod(temp, 0o600)
        os.replace(temp, env)
    except OSError as e:
        try:
            temp.unlink()
        except OSError:
            pass
        raise Refused(f"the .env could not be written ({type(e).__name__}); the old file is as it was") from None
    os.chmod(env, 0o600)


def _bindings(text):
    """(the file's statements as dotenv parses them: each binding's key or None, and its original text)."""
    return [(b.key, b.original.string) for b in parse_stream(io.StringIO(text))]


def set_value(name, key, value, *, router_root=None):
    """Write `key` with `value` into the project's `.env`. Returns {name, created, characters}. Refused, nothing written."""
    if not isinstance(key, str) or not NAME.fullmatch(key):
        raise Refused("a name is capital letters, digits and _ only, not starting with a digit (like DEMO_KEY)")
    problem = check_value(value)
    if problem:
        raise Refused(problem)
    folder = folder_of(name, router_root=router_root)
    _check_file(folder)
    env = folder / ".env"
    try:
        with locks.held(f"project-{name}", folder=runs.FOLDER, wait=False):
            _check_file(folder)  # again, under the lock
            text = env.read_bytes().decode("utf-8") if env.exists() else ""  # bytes: a \r\n line stays one
            found = _bindings(text)
            place = next((i for i, (k, _) in enumerate(found) if k == key), None)
            if place is None:
                lead = "" if not text or text.endswith("\n") else "\n"
                new = text + lead + _line(key, value) + "\n"
            else:
                original = found[place][1]
                ending = "\r\n" if original.endswith("\r\n") else "\n" if original.endswith("\n") else ""
                parts = [original_text for k, original_text in found[:place]]
                parts.append(_line(key, value, export=bool(_EXPORT.match(original))) + (ending or "\n"))
                parts += [original_text for k, original_text in found[place + 1:] if k != key]
                new = "".join(parts)
            _write(env, new)
    except locks.Busy:
        raise Refused(f"another write holds {name} (a land, an undo, a notes save or another secret): try again when "
                      "it ends") from None
    return {"name": key, "created": place is None, "characters": len(value)}


def remove(name, key, *, router_root=None):
    """Take every line of `key` out of the project's `.env`. Refused, nothing written, when it holds no such name."""
    if not isinstance(key, str) or not NAME.fullmatch(key):
        raise Refused("a name is capital letters, digits and _ only, not starting with a digit (like DEMO_KEY)")
    folder = folder_of(name, router_root=router_root)
    _check_file(folder)
    env = folder / ".env"
    try:
        with locks.held(f"project-{name}", folder=runs.FOLDER, wait=False):
            _check_file(folder)
            text = env.read_bytes().decode("utf-8") if env.exists() else ""  # bytes: a \r\n line stays one
            found = _bindings(text)
            if not any(k == key for k, _ in found):
                raise Refused(f"no {key} in {name}'s .env")
            _write(env, "".join(original for k, original in found if k != key))
    except locks.Busy:
        raise Refused(f"another write holds {name}: try again when it ends") from None
    return {"name": key, "removed": True}
