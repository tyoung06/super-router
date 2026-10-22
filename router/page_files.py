"""The files the page server may open, the one file it may write, and Open in Finder (build brief 23, decisions 8, 9
and 11). A file is opened only when, resolved through links, it sits inside the task folder its path names: one of
`tasks/<task_id>/`, `media/in/<task_id>/`, `media/pages/<task_id>/`, `media/frames/<task_id>/` and
`media/out/<task_id>/`, for a task id of the router's shape. So a link that leads out of its task folder is refused,
into another task's folder too. Besides those: `report_path` exactly, and a registered project's `HANDOFF.md` exactly.
Never a hidden name (`.env*` among them), `router.db*`, `backups/` or `config/`. Text over 2 MB reads its first 2 MB.

The one write: a file dropped on the page goes into the drop folder, after Media's types and its 50 MB limit, with
exclusive create (a clash becomes " (2)", never an overwrite, never through a link). Open in Finder runs
`["open", "-R", <path>]` on an allowed path, on macOS only. Nothing here reads `.env` or the log."""
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

from router import drop, media

ROOT = Path(__file__).resolve().parent.parent
TASK_ID = re.compile(r"sr-\d{8}-\d{6}-[0-9a-f]{4}")
ROOTS = ("tasks", "media/in", "media/pages", "media/frames", "media/out")  # each followed by /<task_id>/
TEXT_LIMIT = 2 * 1024 * 1024
TEXT = (".md", ".txt", ".json", ".ndjson", ".log", ".csv", ".html", ".htm")
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
        ".pdf": "application/pdf", ".mp4": "video/mp4", ".mov": "video/quicktime"}
ROUND = re.compile(r"(\d+)-(.+)-([a-z]+)\.md")   # tasks/<task_id>/<NN>-<role>-<agent>.md (rules v2.30, Round outputs)


class Refused(ValueError):
    """A path the page may not open, or a drop that may not be written. Nothing was read or written."""


def _denied(name):
    return name.startswith(".") or name.startswith("router.db")


def kind(name):
    suffix = Path(name).suffix.lower()
    if suffix in TEXT:
        return "text"
    found = MIME.get(suffix, "")
    return found.split("/")[0] if found.startswith(("image/", "video/")) else ("pdf" if suffix == ".pdf" else "other")


def content_type(name):
    """Images, PDFs and videos by type; text and anything that could be read as a page, plain text, never HTML."""
    suffix = Path(name).suffix.lower()
    if suffix in MIME:
        return MIME[suffix]
    return "text/plain; charset=utf-8" if suffix in TEXT else "application/octet-stream"


def _task_folder(root, folder, task_id):
    """The task's folder under `folder` when it is a real folder there (not a link out), else None."""
    base = Path(root) / folder / task_id
    try:
        if not base.is_dir() or base.resolve().parent != (Path(root) / folder).resolve():
            return None
        return base.resolve()
    except OSError:
        return None


def task_files(root, task_id):
    """The files decision 9 allows for one task, its round files first: name, kind, size, path, root, and the round
    (order, role, agent) a round file's name gives. A link out of its folder is left out. Build brief 24 (decision 17):
    a PDF's page images sit one folder down, `media/pages/<task_id>/<folder>/`, and carry that `folder` (None for any
    other file, and for a task from before)."""
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
        raise Refused("not a task id of the router's shape")
    found = []
    for folder in ROOTS:
        base = _task_folder(root, folder, task_id)
        if base is None:
            continue
        for child in sorted(base.iterdir(), key=lambda p: p.name):
            if _denied(child.name):
                continue
            if folder == "media/pages" and _subfolder(child, base):
                found += [{**f, "folder": child.name} for f in _files_in(child.resolve(), folder, f"{task_id}/{child.name}")]
                continue
            found += _files_in(base, folder, task_id, only=child)
    return found


def _subfolder(child, base):
    """A real folder right inside `base` (a PDF's pages, brief 24), never a link out."""
    try:
        return not child.is_symlink() and child.is_dir() and child.resolve().parent == base
    except OSError:
        return False


def _files_in(base, folder, where, only=None):
    """The files right inside `base`, as task_files lists them, their paths `<folder>/<where>/<name>`; `only` one child."""
    found = []
    for child in [only] if only is not None else sorted(base.iterdir(), key=lambda p: p.name):
        if _denied(child.name):
            continue
        try:
            real = child.resolve()
            if not real.is_file() or real.parent != base:
                continue
            size = real.stat().st_size
        except OSError:
            continue
        m = ROUND.fullmatch(child.name) if folder == "tasks" else None
        found.append({"name": child.name, "kind": kind(child.name), "size": size, "path": f"{folder}/{where}/{child.name}",
                      "root": folder, "round": {"order": int(m.group(1)), "role": m.group(2), "agent": m.group(3)} if m else None,
                      "folder": None})
    return found


def log_folders(root, *, before=None, limit=30):
    """Log files (brief 23, F): the task folders under tasks/, newest first (a task id sorts by its time), each with
    its round files as `task_files` lists them; `limit` folders after `before`, and `next_before` when more remain.
    Only names of the router's shape, and only real folders there (a link out is left out)."""
    if before is not None and (not isinstance(before, str) or not TASK_ID.fullmatch(before)):
        raise Refused("before must be a task id of the router's shape")
    base = Path(root) / "tasks"
    try:
        names = sorted((p.name for p in base.iterdir() if TASK_ID.fullmatch(p.name)), reverse=True)
    except OSError:
        return {"folders": [], "next_before": None}
    if before is not None:
        names = [n for n in names if n < before]
    folders = []
    for name in names:
        if _task_folder(root, "tasks", name) is None:
            continue
        if len(folders) == limit:
            return {"folders": folders, "next_before": folders[-1]["task_id"]}
        folders.append({"task_id": name, "files": [f for f in task_files(root, name) if f["root"] == "tasks"]})
    return {"folders": folders, "next_before": None}


def _exactly(real, wanted):
    try:
        return wanted is not None and real == Path(wanted).expanduser().resolve()
    except OSError:
        return False


def resolve(root, path, *, report_path=None, handoffs=()):
    """The real file `path` names when decision 9 allows it; else Refused."""
    if not isinstance(path, str) or not path:
        raise Refused("no path")
    given = Path(path)
    if given.is_absolute():
        try:
            real = given.resolve(strict=True)
        except (OSError, RuntimeError):
            raise Refused("no such file") from None
        if real.is_file() and not _denied(real.name) and (
                _exactly(real, report_path) or any(_exactly(real, h) for h in handoffs or ())):
            return real
        raise Refused("not a file the page may open")
    parts = given.parts
    if ".." in parts:
        raise Refused("a path may not climb out with ..")
    for folder in ROOTS:
        head = Path(folder).parts
        if parts[:len(head)] != head or len(parts) < len(head) + 2:
            continue
        task_id = parts[len(head)]
        if not TASK_ID.fullmatch(task_id):
            raise Refused("not a task id of the router's shape")
        base = _task_folder(root, folder, task_id)
        if base is None:
            raise Refused("no such task folder")
        try:
            real = Path(root).joinpath(*parts).resolve(strict=True)
        except (OSError, RuntimeError):
            raise Refused("no such file") from None
        if not real.is_relative_to(base) or not real.is_file() or _denied(real.name):
            raise Refused("not a file the page may open")
        return real
    raise Refused("not a file the page may open")


def read(path, limit=None):
    """(bytes, total size when cut): a text file over 2 MB reads its first 2 MB; anything else whole."""
    limit = TEXT_LIMIT if limit is None else limit
    path = Path(path)
    if kind(path.name) == "text":
        size = path.stat().st_size
        with open(path, "rb") as f:
            data = f.read(limit)
        return (data, size) if size > limit else (data, None)
    return path.read_bytes(), None


def _name_problem(name):
    if not isinstance(name, str) or not name or name in (".", ".."):
        return "the file's name is empty"
    if "/" in name or "\\" in name or name.startswith("."):
        return "the file's name may not hold a folder or start with a dot"
    if any(unicodedata.category(c) == "Cc" for c in name):
        return "the file's name holds a control character"
    return None


def drop_write(drop_folder, name, data):
    """Write one dropped file into the drop folder (decision 8); returns its path. Media's types and its 50 MB limit
    first; exclusive create, never through a link; a clash becomes ` (2)`, ` (3)`, … never an overwrite."""
    if drop_folder is None:
        raise Refused("no drop folder is set (drop_folder in config/settings.json)")
    problem = _name_problem(name)
    if problem:
        raise Refused(problem)
    suffix = Path(name).suffix.lower().lstrip(".")
    if suffix not in media.EXTENSIONS + drop.CONVERTED:
        what = f"a .{suffix} file" if suffix else "a file with no type"
        raise Refused(f"{what} can't go on a task; the types are {', '.join(media.EXTENSIONS + drop.CONVERTED)}")
    if len(data) > media.MAX_BYTES:
        raise Refused("the file is over 50 MB")
    folder = Path(drop_folder).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    stem, ext = Path(name).stem, Path(name).suffix
    for n in range(1, 1000):
        target = folder / (name if n == 1 else f"{stem} ({n}){ext}")
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return target
    raise Refused("too many files of that name in the drop folder")


def reveal(root, path, *, report_path=None, handoffs=(), run=subprocess.run, platform=sys.platform):
    """Open in Finder (decision 11): `open -R` on a path decision 9 allows, on macOS only."""
    if platform != "darwin":
        raise Refused("Open in Finder is macOS only")
    real = resolve(root, path, report_path=report_path, handoffs=handoffs)
    run(["open", "-R", str(real)], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
    return real
