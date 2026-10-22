"""Build brief 25 (decision 1): this repo's pre-push guard.

Once the private repo is renamed and its old name becomes the public repo, GitHub's redirect from the old URL ends, so a
clone still pointing at the old URL would push private history to the public repo. This hook refuses any push whose
remote URL isn't the private repo named in config/settings.local.json (`private_remote`: a name, or owner/name; no
tracked file names it), and every push while that is unset.

    python scripts/push_guard.py install              the owner runs it once: .git/hooks isn't tracked
    python scripts/push_guard.py check <remote> <url>  what the hook runs on every push
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(__file__).resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.publish import names_repo  # noqa: E402

HOOK_MARK = "# super-router push guard"
USAGE = "usage: python scripts/push_guard.py install | check <remote> <url>"


def private_remote(root=ROOT):
    """`private_remote` from the local settings file under `root`, or ""."""
    try:
        doc = json.loads((Path(root) / "config" / "settings.local.json").read_text())
    except (OSError, ValueError):
        return ""
    value = doc.get("private_remote") if isinstance(doc, dict) else None
    return value.strip() if isinstance(value, str) else ""


def allowed(url, wanted):
    """True only when `url` is the private repo `wanted`; nothing passes while `wanted` is empty."""
    return bool(wanted) and names_repo(url, wanted)


def check(root, remote, url, out=print):
    """The hook: 0 lets the push go, 1 refuses it with the reason (never the setting's value)."""
    wanted = private_remote(root)
    if not wanted:
        out("Push refused by the guard: private_remote isn't set in config/settings.local.json, so every push is "
            "refused until it is.")
        return 1
    if not allowed(url, wanted):
        out(f"Push refused by the guard: {url} isn't the private repo (private_remote in config/settings.local.json). "
            "Nothing was pushed.")
        return 1
    return 0


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=60)


def install(root=ROOT, out=print, python=None):
    """Write the shared pre-push hook (a worktree's too) unless a hook that isn't the guard's is there; then say whether
    `origin` would pass."""
    found = _git(root, "rev-parse", "--git-path", "hooks/pre-push")
    if found.returncode != 0:
        out(f"Refused: {Path(root).name} is not a git checkout.")
        return 1
    hook = Path(found.stdout.strip())
    hook = hook if hook.is_absolute() else Path(root) / hook
    if hook.exists() and HOOK_MARK not in hook.read_text(errors="replace"):
        out("Refused: a pre-push hook that isn't the guard's is already there; move it aside first.")
        return 1
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(f"#!/bin/sh\n{HOOK_MARK} (installed by scripts/push_guard.py): a push goes only to the private "
                    f"repo.\nexec \"{python or sys.executable}\" \"{SCRIPT}\" check \"$1\" \"$2\"\n")
    hook.chmod(0o755)
    out("The push guard is installed: a push goes only to the private repo named by private_remote.")
    origin = _git(root, "remote", "get-url", "origin")
    if origin.returncode == 0:
        good = allowed(origin.stdout.strip(), private_remote(root))
        out("origin passes the guard." if good else "origin would be refused: point it at the private repo first.")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv == ["install"]:
        return install()
    if len(argv) == 3 and argv[0] == "check":
        return check(ROOT, argv[1], argv[2])
    print(USAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main())
