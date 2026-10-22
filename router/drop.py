"""The drop folder (the owner, 2026-10-14). Files put in it are offered on every `sr route` run from a
terminal, go through the same intake as --file, and move to sent/<task-id>/ once attached. HEIC and
HEIF are converted to jpg at intake with sips (macOS); the original moves untouched. The folder's
path comes from config/settings.json, never from code. Without a terminal the folder is ignored."""
import json
import shutil
import subprocess
from pathlib import Path

from router import safety, settings

SETTINGS_PATH = safety.REPO_ROOT / "config" / "settings.json"
SENT = "sent"
CONVERTED = ("heic", "heif")
SIPS_TIMEOUT = 60
YES = ("y", "yes")


class DropError(safety.SafeError):
    """A drop-folder step failed. Nothing was logged or sent; the folder is as it was."""


def folder(settings_path=None):
    """The drop folder from the settings, ~ expanded (brief 21: config/settings.local.json over config/settings.json, key
    by key); from one file when `settings_path` is given. None when the file or the key is missing."""
    if settings_path is None:
        doc = settings.read()
    else:
        try:
            doc = json.loads(Path(settings_path).read_text())
        except (OSError, ValueError):
            return None
    value = doc.get("drop_folder") if isinstance(doc, dict) else None
    return Path(value).expanduser() if isinstance(value, str) and value.strip() else None


def prepare(drop_folder):
    """Create the folder and its sent/ subfolder when missing."""
    (Path(drop_folder) / SENT).mkdir(parents=True, exist_ok=True)
    return Path(drop_folder)


def waiting(drop_folder):
    """The files in the drop folder: regular files, not hidden, not inside sent/; by name."""
    drop_folder = Path(drop_folder)
    if not drop_folder.is_dir():
        return []
    return sorted((p for p in drop_folder.iterdir() if p.is_file() and not p.name.startswith(".")),
                  key=lambda p: p.name.lower())


def at_top_level(drop_folder, path):
    """True when `path` is a file directly in the drop folder (not in sent/ or a subfolder), judged on both resolved
    through links, so a link in the folder that points elsewhere is not the folder's (build brief 23, decision 8)."""
    if drop_folder is None:
        return False
    try:
        path = Path(path)
        return path.is_file() and path.resolve().parent == Path(drop_folder).expanduser().resolve()
    except OSError:
        return False


def move_sent(drop_folder, task_id, paths):
    """Move attached files to sent/<task-id>/. Returns that folder."""
    dest = Path(drop_folder) / SENT / task_id
    dest.mkdir(parents=True, exist_ok=True)
    for path in paths:
        shutil.move(str(path), str(dest / Path(path).name))
    return dest


def needs_conversion(path):
    return Path(path).suffix.lower().lstrip(".") in CONVERTED


def convert_heic(path, dest_dir, run=subprocess.run):
    """HEIC or HEIF to jpg with sips, into dest_dir. The original is untouched. Returns the jpg."""
    path, dest_dir = Path(path), Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"{path.stem}.jpg"
    argv = ["sips", "-s", "format", "jpeg", str(path.absolute()), "--out", str(target)]  # absolute: a name starting with - is never an option
    try:
        proc = run(argv, capture_output=True, text=True, timeout=SIPS_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise DropError(f"sips timed out after {SIPS_TIMEOUT} s on {path.name}") from None
    except OSError as e:
        raise DropError(f"could not start sips ({type(e).__name__})") from None
    if proc.returncode != 0 or not target.is_file():
        raise DropError(f"sips could not convert {path.name}: {(proc.stderr or '').strip()[-200:]}")
    return target
