"""Read Grok Bot results from GitHub issues in the inbox repo.

An issue's title is exactly the task_id; its body is the result.
Results are data. They are stored and shown, never run.
Build brief 24 (decision 11): the inbox repo is a setting, `grok_inbox_repo` (`owner/name`), read from
config/settings.local.json over the tracked file on every use; the code never spells one. Without it Grok Bot isn't
set up, and a read here says so.
"""
import base64
import binascii
import json
import re
import subprocess

from router import safety, settings

GH_TIMEOUT = 60


class InboxError(safety.SafeError):
    """A gh call failed or returned something unreadable. returncode is gh's exit code, if it ran."""

    def __init__(self, message, returncode=None):
        super().__init__(message)
        self.returncode = returncode


def repo():
    """The inbox repo from the settings, or InboxError when it isn't set (or isn't owner/name)."""
    found, problem = settings.inbox_repo()
    if found is None:
        raise InboxError(f"Grok Bot isn't set up: {problem}")
    return found


def _gh(argv, run):
    try:
        proc = run(argv, capture_output=True, text=True, timeout=GH_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise InboxError(f"{' '.join(argv[:3])} timed out after {GH_TIMEOUT} s") from None
    except OSError as e:
        raise InboxError(f"could not start gh ({type(e).__name__})") from None
    if proc.returncode != 0:
        raise InboxError(f"{' '.join(argv[:3])} failed: {proc.stderr.strip()[:300]}", proc.returncode)
    return proc


# A path Grok may name for an image it made: media/out/<task-id>/<short-name>.png, nothing else.
OUT_PATH = re.compile(r"media/out/(sr-\d{8}-\d{6}-[0-9a-f]{4})/([A-Za-z0-9][A-Za-z0-9_-]{0,63})\.png")
ANY_PATH = re.compile(r"[A-Za-z0-9_./-]*\.(?:png|jpe?g|webp|gif|mp4|mov)", re.IGNORECASE)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def listed_images(body, task_id):
    """The image paths an issue body names for this task, in order and without repeats, and the
    file-like paths it names that are ignored (another task, another folder, not a png)."""
    accepted, ignored = [], []
    for m in OUT_PATH.finditer(body or ""):
        path = m.group(0)
        if m.group(1) == task_id and path not in accepted:
            accepted.append(path)
    for m in ANY_PATH.finditer(body or ""):
        path = m.group(0)
        if path not in accepted and path not in ignored:
            ignored.append(path)
    return accepted, ignored


def fetch_file(path, run=subprocess.run):
    """One committed file from the inbox repo, as bytes, through the contents API as JSON with
    base64 content (files up to 1 MB), else the blob API by the file's sha (up to 100 MB). Both
    are JSON through gh, never a clone and never binary through gh, which gh cannot pass on
    (brief 4 Phase F: "transform: short source buffer"). Raises InboxError on any failure."""
    inbox = repo()
    doc = _gh_json(["gh", "api", f"repos/{inbox}/contents/{path}"], run, path)
    data = _decode(doc, path)
    if data is not None:
        return data
    sha = doc.get("sha") if isinstance(doc, dict) else None
    if not isinstance(sha, str) or not sha:
        raise InboxError(f"gh api gave no content and no sha for {path}")
    data = _decode(_gh_json(["gh", "api", f"repos/{inbox}/git/blobs/{sha}"], run, path), path)
    if data is None:
        raise InboxError(f"gh api gave no content for the blob of {path}")
    return data


def _gh_json(argv, run, path):
    try:
        doc = json.loads(_gh(argv, run).stdout)
    except ValueError:
        raise InboxError(f"gh api did not return JSON for {path}") from None
    if not isinstance(doc, dict):
        raise InboxError(f"gh api did not return an object for {path}")
    return doc


def _decode(doc, path):
    """The bytes of a contents or blob document, or None when it carries no content."""
    content, encoding = doc.get("content"), doc.get("encoding")
    if not isinstance(content, str) or not content.strip():
        return None
    if encoding != "base64":
        raise InboxError(f"gh api returned {encoding!r} content for {path}, not base64")
    try:
        data = base64.b64decode("".join(content.split()), validate=True)
    except (ValueError, binascii.Error):
        raise InboxError(f"the content of {path} was not valid base64") from None
    if not data:
        raise InboxError(f"gh api returned nothing for {path}")
    return data


def fetch_issues(run=subprocess.run):
    argv = [
        "gh", "issue", "list", "--repo", repo(),
        "--state", "open", "--limit", "200", "--json", "number,title,body,url",
    ]
    try:
        issues = json.loads(_gh(argv, run).stdout)
    except ValueError:
        raise InboxError("gh issue list did not return JSON") from None
    if not isinstance(issues, list):
        raise InboxError("gh issue list did not return a list")
    return issues


def close_issue(number, run=subprocess.run):
    _gh(["gh", "issue", "close", str(int(number)), "--repo", repo()], run)


def match_results(open_task_ids, issues):
    wanted = set(open_task_ids)
    matches = []
    for issue in issues:
        title = (issue.get("title") or "").strip()
        if title in wanted:
            wanted.discard(title)  # one result per task; later duplicates are left alone
            matches.append({
                "task_id": title,
                "result": issue.get("body") or "",
                "url": issue.get("url"),
                "number": issue.get("number"),
            })
    return matches
