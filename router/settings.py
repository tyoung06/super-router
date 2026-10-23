"""Router settings that are neither agents nor skills, from config/settings.json (the owner's file: the router reads
it, never writes it). Brief 15 (rules v2.21, Relay): `grok_prompt_limit`, the longest prompt Grok Bot delivers
whole, measured once by Claude Code and written by the owner; until the owner does, the router uses 3,800.
Brief 21 (rules v2.30, Router for the interface; the owner's B1 amendment): `config/settings.local.json`, gitignored and
optional, overrides the tracked file key by key; it holds this Mac's own values, such as `report_path`, which never
goes in the tracked file (the repo goes public). `grok_timeout_minutes` (the Grok note's N), `memory` (auto or off,
shown; brief 22 acts on it) and `serve_port` (the port `sr serve` uses). Brief 26: `projects_root`."""
import json
import os
import re
import stat
import tempfile
from pathlib import Path

from router import safety

REPO_SETTINGS = safety.REPO_ROOT / "config" / "settings.json"
SETTINGS_PATH = REPO_SETTINGS                                       # tests point this elsewhere
LOCAL_PATH = safety.REPO_ROOT / "config" / "settings.local.json"    # gitignored; tests point this elsewhere too
DEFAULT_GROK_PROMPT_LIMIT = 3800
DEFAULT_SERVE_PORT = 8765  # the port `sr serve` used before brief 21 (router/page.py)
MEMORY_MODES = ("auto", "off")
SOURCE = "config/settings.json"
# Build brief 24 (decision 11): the repo Grok Bot's results land in is a setting, `owner/name`, never spelled in the code.
# GitHub's own characters: an owner of letters, digits and single dashes (no dash at either end, at most 39), a name of
# letters, digits, `.`, `_` and `-` (never `.` or `..`). It goes into gh's argument list and an API path, so its shape is
# checked before any reader uses it.
INBOX_KEY = "grok_inbox_repo"
INBOX_REPO = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}/(?!\.\.?$)[A-Za-z0-9._-]{1,100}")
# Build brief 25 (decision 5): the folders `sr project add` never registers, by path and by name. A list of absolute or
# `~` paths in the local file only (the owner's holds their own folder); the tracked file names none, so the code spells none.
NEVER_KEY = "never_register"


def _load(path):
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _read():
    """The tracked settings with the local file's keys over them (brief 21). An unreadable local file overrides nothing."""
    return {**_load(SETTINGS_PATH), **_load(LOCAL_PATH)}


def read():
    """Every setting, the local file's over the tracked file's."""
    return _read()


def _positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def inbox_repo(doc=None):
    """(the inbox repo `owner/name`, None) from the settings (the local file's over the tracked one), or (None, why not)
    in words: unset, or not owner/name. `doc` is the settings already read (availability is pure); None reads them."""
    value = (_read() if doc is None else doc).get(INBOX_KEY)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "no inbox repo in settings"
    if not isinstance(value, str) or not INBOX_REPO.fullmatch(value.strip()):
        return None, f"{INBOX_KEY} in settings isn't owner/name"
    return value.strip(), None


def never_register(doc=None):
    """(the never_register folders, None) with `~` expanded; absent or [] is ([], None): nothing is refused. Anything but
    a list of absolute or `~` paths is (None, why), and the registry then refuses every add until it is fixed (a typo
    never quietly drops the protection). `doc` is the settings already read; None reads them."""
    value = (_read() if doc is None else doc).get(NEVER_KEY)
    if value is None:
        return [], None
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip()
                                              and (v.strip().startswith("~") or Path(v.strip()).is_absolute())
                                              for v in value):
        return None, f"{NEVER_KEY} in settings isn't a list of paths"
    return [Path(v.strip()).expanduser() for v in value], None


# Build brief 26 (decision 8): where `sr project new` makes a project's folder. Optional; the default lives here, so the
# tracked settings file needs no key. A value that is not absolute once `~` is expanded refuses every `new`.
PROJECTS_ROOT_KEY = "projects_root"
DEFAULT_PROJECTS_ROOT = "~/Projects"


def projects_root_written(doc=None):
    """projects_root as written in the settings (shown in status), or the default when it is absent."""
    value = (_read() if doc is None else doc).get(PROJECTS_ROOT_KEY)
    return DEFAULT_PROJECTS_ROOT if value is None else value if isinstance(value, str) else json.dumps(value)


def projects_root(doc=None):
    """(the projects root with `~` expanded, None), or (None, why not) in words. Absent is the default, ~/Projects."""
    value = (_read() if doc is None else doc).get(PROJECTS_ROOT_KEY)
    if value is None:
        return Path(DEFAULT_PROJECTS_ROOT).expanduser(), None
    if not isinstance(value, str) or not value.strip() or not Path(value.strip()).expanduser().is_absolute():
        return None, f"{PROJECTS_ROOT_KEY} in settings isn't an absolute or ~ path"
    return Path(value.strip()).expanduser(), None


def grok_timeout_minutes():
    """N for the Grok timeout note (decision 5; the owner, 15 Oct: 5): a whole number of minutes above 0, or None (no note)."""
    value = _read().get("grok_timeout_minutes")
    return value if _positive_int(value) else None


def memory_mode():
    """`auto` (the default) or `off` (rules v2.30, Memory, Down). Read and shown in brief 21; brief 22 acts on it."""
    value = _read().get("memory")
    return value if value in MEMORY_MODES else "auto"


class SettingsError(safety.SafeError):
    """Brief 27: the local settings file can't take the write (not a JSON object). Its bytes are left as they were."""


LOCAL_NAME = "config/settings.local.json"


def set_memory(mode):
    """Brief 27 (decision 2): `memory` in this Mac's local settings file, the one key `sr memory on|off` writes. Returns
    (the mode before, whether anything was written); already as asked writes nothing. A missing file is made holding the
    key alone, mode 0600; an existing one keeps every other key and value, in order, and its mode, rewritten through a
    temporary file beside it and `os.replace`, so it is never half-written. Not a JSON object: SettingsError, nothing
    written. The tracked file is never written."""
    if mode not in MEMORY_MODES:
        raise ValueError(f"memory is one of {', '.join(MEMORY_MODES)}")
    path = Path(LOCAL_PATH)
    try:
        raw = path.read_text()
    except FileNotFoundError:
        raw = None
    except OSError:
        raise SettingsError(f"{LOCAL_NAME} could not be read") from None
    if raw is None:
        doc, perms = {}, 0o600
    else:
        try:
            doc = json.loads(raw)
        except ValueError:
            raise SettingsError(f"{LOCAL_NAME} is not JSON") from None
        if not isinstance(doc, dict):
            raise SettingsError(f"{LOCAL_NAME} is not a JSON object")
        perms = stat.S_IMODE(os.stat(path).st_mode)
    was = memory_mode()
    if was == mode:
        return was, False
    doc["memory"] = mode
    fd, temp = tempfile.mkstemp(dir=str(path.parent), prefix=".settings.local.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(doc, indent=2) + "\n")
        os.chmod(temp, perms)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
    return was, True


def serve_port():
    """The port `sr serve` listens on, 127.0.0.1 only: a port number, else the default."""
    value = _read().get("serve_port")
    return value if _positive_int(value) and value <= 65535 else DEFAULT_SERVE_PORT


def report_path():
    """Where Claude Code's report is written (`~` expanded), or None when unset: then the page has no report button.
    The owner sets it in config/settings.local.json, never in the tracked file."""
    value = _read().get("report_path")
    return str(Path(value).expanduser()) if isinstance(value, str) and value.strip() else None


def grok_prompt_limit():
    """(the limit in characters, where it came from): the owner's number from config/settings.json, or the default
    with the reason. Read on every Grok send, so a number the owner writes counts from the next call."""
    doc = _read()
    if "grok_prompt_limit" not in doc:
        return DEFAULT_GROK_PROMPT_LIMIT, "default"
    value = doc["grok_prompt_limit"]
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value, SOURCE
    return DEFAULT_GROK_PROMPT_LIMIT, f"default; grok_prompt_limit in {SOURCE} is not a positive whole number"


# Build brief 19 (rules v2.27, Memory, "Caps, in code"; decision 9): where the store is and the caps on the block.
# The owner's file is read on every use; a missing or bad key falls back to the default with the reason.
MEMORY_DEFAULTS = {
    "memory_url": "http://127.0.0.1:8888",
    "memory_bank": "super-router",
    "memory_max_items": 5,
    "memory_max_chars": 2000,
    "memory_query_chars": 1500,
}


def memory_setting(name):
    """(value, where it came from) for one of the five memory keys. KeyError on any other name."""
    default = MEMORY_DEFAULTS[name]
    doc = _read()
    if name not in doc:
        return default, "default"
    value = doc[name]
    if isinstance(default, int):
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value, SOURCE
        return default, f"default; {name} in {SOURCE} is not a positive whole number"
    if isinstance(value, str) and value.strip():
        return value.strip(), SOURCE
    return default, f"default; {name} in {SOURCE} is not a non-empty string"
