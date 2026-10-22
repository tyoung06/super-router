"""Build brief 25 (decisions 2, 6 and 9): publish this repo's public copy into a clone of the public repo.

    python scripts/publish.py <clone>          export, scan, match the clone, commit there; never push
    python scripts/publish.py --check <clone>  export and scan only; touch nothing
    python scripts/publish.py --pre-push ...   the clone's pre-push hook: scan every outgoing commit

It runs only from `main` with no tracked file changed, and reads HEAD, never the working tree. It takes the allowlist,
makes docs/RULES.md (scripts/rules_copy.py) and places publish/ci.yml as the copy's workflow, scans the result, makes the
clone's files match it (never touching .git), commits there as "Publish <sha>: <subject>" under publish_author, and
installs the clone's pre-push hook. It prints the push command; the owner pushes. Any hit stops it before the clone is
touched, named by category and file, never by value.

The words come from this Mac at run time, never from a tracked file, so this file spells none of them: every .env value
of 8 characters or more (compared in memory), the home folder and its account name, the account's full name (`id -F`),
git's email and name (the GitHub handle, allowed in LICENSE alone), and from config/settings.local.json the inbox repo,
`private_remote`, `publish_forbidden` and `publish_author`."""
import dataclasses
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(__file__).resolve()
if str(ROOT) not in sys.path:  # run as a script (or by the hook) the repo root isn't on the path
    sys.path.insert(0, str(ROOT))

from scripts import rules_copy  # noqa: E402

# ---------- what goes public (decision 2) ----------

ALLOW_DIRS = ("router/", "static/", "scripts/", "docs/", "demo/", "tests/")
ALLOW_FILES = frozenset({"config/agents.json", "config/presets.json", "config/settings.json", "config/skill_table.json",
                         "requirements.txt", "pytest.ini", ".env.example", ".gitignore", ".gitleaksignore",
                         "README.md", "LICENSE"})
# The label-test files need labeltest/, so they stay private with it (decision 2).
LABEL_TESTS = ("tests/test_labeltest_claude.py", "tests/test_labeltest_jev.py", "tests/test_labeltest_report.py",
               "tests/test_labeltest_round3.py", "tests/test_labeltest_round4.py", "tests/test_labeltest_score.py")
NEVER_FILES = frozenset({"NOTES.md", "SUPER-ROUTER-HANDOFF.md", "SUPER-ROUTER.md", "CLAUDE.md", "AGENTS.md", *LABEL_TESTS})
NEVER_DIRS = ("labeltest/", ".claude/", "publish/")  # publish/: the workflow's source, placed in the copy, never copied
# Made at each publish, in the copy only: published path -> its source at HEAD.
MADE = {"docs/RULES.md": "SUPER-ROUTER.md", ".github/workflows/ci.yml": "publish/ci.yml"}

# The owner's rule of 21 Oct: a file that isn't text goes public only when named here with its SHA-256. The demo's samples
# are drawn by scripts/make_demo.py; docs/demo.png is the README's picture of `sr serve --demo`. Any other binary, or one
# of these whose bytes changed, stops the publish.
KNOWN_BINARIES = {
    "demo/files/media/frames/sr-20261019-105100-0019/frame_01.png": "2195bbbcdc962ced111b27e2cc68182cabda0c9d0d34abb693494a6bbd4a4dd4",
    "demo/files/media/frames/sr-20261019-105100-0019/frame_02.png": "f859772494cbf9adfbaef1e36599c8bfe6bf3c1e372c4ac0d60dd1dfa7312e20",
    "demo/files/media/in/sr-20261019-104100-0017/raised-bed.png": "eadc7dc760750a69179b823e3bf6f289b871859a92fa3e7ef67b85e8414c9fc6",
    "demo/files/media/in/sr-20261019-105100-0019/garden-walk.mp4": "05914299e71d67d4cee5f36127717b2e9945daa09f8e7cb39102365191d29b37",
    "demo/files/media/out/sr-20261019-105600-001a/tomato-badge.png": "5b6d018556c09b7c05953d2c8ea88ea30103fd3cd5cb4f4da127f970ec5291c1",
    "demo/files/media/pages/sr-20261019-104600-0018/menu/page-1.png": "c58e61bb5e37cee3954e4a1ddac9b26f49cd0dcb4c67fcaf18047989efec7397",
    "demo/files/media/pages/sr-20261019-104600-0018/menu/page-2.png": "d3df550903bd830d6509f57233475416170d618a8a22f37090e58f94ce8b569a",
    "docs/demo.png": "1134666f63df877009e9ca2194492dee9986c9f804cc98cd7e8b5a1c5b1a10d6",
}

# The CI's gitleaks config, byte for byte (publish/ci.yml carries the same text): the default rules, and one allowlist on
# the match for the tests' deliberate fakes.
GITLEAKS_TOML = """title = "Super Router public copy"

[extend]
useDefault = true

[[allowlists]]
description = "Deliberate fakes in the tests: fake keys, example domains and alphabet runs"
regexTarget = "match"
regexes = [
  '''(?i)fake''',
  '''example\\.(com|invalid|org)''',
  '''(?i)abcdefghijkl''',
]
"""

HOOK_MARK = "# super-router publish hook"
MIN_WORD = 4  # a name, handle or word shorter than this is too common to look for
AUTHOR = re.compile(r"(.+?) <([^<>@\s]+@[^<>\s]+)>")
ZERO = "0" * 40
NOT_INSTALLED = "gitleaks: not installed here; it runs in the public repo's CI"


class PublishError(Exception):
    """A refusal or a stop; its text names categories and files, never a value."""


def classify(path, copy=False):
    """"allow", "never" or "neither" for a tracked path; `copy`: a path in the public copy, where MADE is allowed too."""
    if path in NEVER_FILES or path.startswith(NEVER_DIRS):
        return "never"
    if (copy and path in MADE) or path in ALLOW_FILES or path.startswith(ALLOW_DIRS):
        return "allow"
    return "neither"


def is_binary(data):
    """Not text: a NUL byte in its first 8,000 bytes (git's test), or bytes that aren't UTF-8."""
    if b"\0" in data[:8000]:
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


# ---------- the words ----------

@dataclasses.dataclass(frozen=True)
class Words:
    env: tuple = ()          # every .env value of 8 characters or more, compared in memory, never shown
    home: str = ""           # this Mac's home folder
    account: str = ""        # its account name
    full_name: str = ""      # the account's full name
    email: str = ""          # git's user.email
    handle: str = ""         # git's user.name: the GitHub handle, allowed in LICENSE alone
    inbox: str = ""          # grok_inbox_repo, owner/name
    private_remote: str = ""  # the private repo's name, or owner/name
    forbidden: tuple = ()    # publish_forbidden: exact names, never a bare common word
    author: str = ""         # publish_author: "Name <email>", GitHub's noreply address

    @classmethod
    def from_mac(cls, root=ROOT, run=subprocess.run):
        """Read from this Mac: the .env and the local settings file under `root`, the home folder, `id -F`, git config."""
        from dotenv import dotenv_values

        from router import safety
        root = Path(root)
        try:
            local = json.loads((root / "config" / "settings.local.json").read_text())
        except (OSError, ValueError):
            local = {}
        local = local if isinstance(local, dict) else {}

        def setting(key):
            value = local.get(key)
            return value.strip() if isinstance(value, str) else ""

        forbidden = local.get("publish_forbidden")
        forbidden = tuple(w.strip() for w in forbidden if isinstance(w, str)) if isinstance(forbidden, list) else ()
        env = dotenv_values(root / ".env") if (root / ".env").exists() else {}
        return cls(env=tuple(safety.env_secrets(env)), home=str(Path.home()), account=Path.home().name,
                   full_name=_quiet(run, ["id", "-F"]), email=_quiet(run, ["git", "-C", str(root), "config", "user.email"]),
                   handle=_quiet(run, ["git", "-C", str(root), "config", "user.name"]), inbox=setting("grok_inbox_repo"),
                   private_remote=setting("private_remote"), forbidden=forbidden, author=setting("publish_author"))

    def problems(self, committing=True):
        """What must be set before a publish (or a push through the hook) may run, in plain words."""
        found = []
        if len(self.private_remote.split("/")[-1]) < MIN_WORD:
            found.append("set private_remote (the private repo's name) in config/settings.local.json")
        if not self.forbidden or any(len(w) < MIN_WORD for w in self.forbidden):
            found.append("set publish_forbidden in config/settings.local.json: exact names, 4 characters or more each")
        if "@" not in self.email:
            found.append("git has no user.email to look for")
        # The design chat's review (21 Oct): a word the scan can't look for is a refusal, never a quiet skip.
        if _full_name_parts(self.full_name) is None:
            found.append("`id -F` gave no full name of two words or more to look for")
        if len(self.handle) < MIN_WORD:
            found.append(f"git's user.name (the GitHub handle) is under {MIN_WORD} characters, too short to look for")
        if committing:
            author = AUTHOR.fullmatch(self.author)
            if not author:
                found.append('set publish_author ("Name <email>", GitHub\'s noreply address) in config/settings.local.json')
            elif author.group(2).lower() == self.email.lower():
                found.append("publish_author's email is git's own email: use GitHub's noreply address")
        return found


def _full_name_parts(full_name):
    """(first, last) of a full name worth looking for: two words or more, each end 2 letters or more; else None.
    The scan and `Words.problems` both read it, so a name the scan can't look for always refuses the publish."""
    names = full_name.split()
    return (names[0], names[-1]) if len(names) >= 2 and len(names[0]) >= 2 and len(names[-1]) >= 2 else None


def _quiet(run, argv):
    try:
        done = run(argv, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


# A name's edges (the first name and the account name): none of the word's own characters beside it; or, on its left,
# the end of an escape, whose letter or hex digit sits against the name in source text ("\n<name>", "\x41<name>",
# "é<name>", "%2F<name>"); or a camelCase seam on either side, a capital against a lowercase letter (`ask<Name>`,
# `<name>Says`). The seam ignores the scan's case folding (`(?-i:...)`), so a run of capitals or of small letters
# stays one word.
_ESCAPED = r"(?<=\\[A-Za-z])|(?<=\\x[0-9A-Fa-f]{2})|(?<=\\u[0-9A-Fa-f]{4})|(?<=\\U[0-9A-Fa-f]{8})|(?<=%[0-9A-Fa-f]{2})"
_SEAM = r"(?-i:(?<=[a-z])(?=[A-Z]))"


def _word(text, inner="A-Za-z"):
    """The pattern for `text` as a whole word in any case: no `inner` character beside it, else an escape or a seam."""
    return rf"(?:(?<![{inner}])|{_ESCAPED}|{_SEAM}){re.escape(text)}(?:(?![{inner}])|{_SEAM})"


def _patterns(words):
    """[(category, the pattern's source, files exempt)] for each word long enough to look for. Never printed."""
    found = [("an .env value", re.escape(v), (), False) for v in words.env if len(v) >= 8]

    def literal(category, text, exempt=()):
        found.append((category, re.escape(text), exempt, True))

    if words.home:
        literal("the home folder", words.home)
    if len(words.account) >= MIN_WORD:
        # A digit or underscore beside it makes a longer word, so a handle made of it and digits (LICENSE's) isn't it.
        found.append(("the account name", _word(words.account, inner="A-Za-z0-9_"), (), True))
    names = _full_name_parts(words.full_name)
    if names:
        found.append(("the full name", re.escape(names[0]) + r"[\s_.\-]*" + re.escape(names[1]), (), True))
        # Only a letter beside it makes a longer word: `<name>_label`, "<name>'s" and `<name>2` all count.
        found.append(("the first name", _word(names[0]), (), True))
    if "@" in words.email:
        literal("git's email", words.email)
    if len(words.handle) >= MIN_WORD:
        literal("the GitHub handle", words.handle, exempt=("LICENSE",))
    if "/" in words.inbox:
        literal("the inbox repo", words.inbox)
        name = words.inbox.split("/", 1)[1]
        if len(name) >= 12:
            literal("the inbox repo", name)
    private = words.private_remote.split("/")[-1]
    if len(private) >= MIN_WORD:
        literal("the private repo's name", private)
    for word in words.forbidden:
        if len(word.strip()) >= MIN_WORD:
            literal("a publish_forbidden word", word.strip())
    return [(category, re.compile(source.encode(), re.I if folded else 0), re.compile(source, re.I if folded else 0), exempt)
            for category, source, exempt, folded in found]


def scan(files, words, message=None, identity=()):
    """{category: [places]} for every word found: in a file's text or bytes, in its name, in the commit message (the
    handle too), and git's email in the commit's identity (the identity holds the handle by design)."""
    found = {}
    patterns = _patterns(words)
    for path, (data, _executable) in files.items():
        name = path.encode()
        for category, as_bytes, _, exempt in patterns:
            if as_bytes.search(name) or (path not in exempt and as_bytes.search(data)):
                found.setdefault(category, set()).add(path)
    if message:
        for category, _, as_text, _ in patterns:
            if as_text.search(message):
                found.setdefault(category, set()).add("the commit message")
    if "@" in words.email and any(words.email.lower() in who.lower() for who in identity):
        found.setdefault("git's email", set()).add("the commit's identity")
    return {category: sorted(places) for category, places in found.items()}


def masked(text, words):
    """`text` with every word in it starred out: how a path is shown."""
    for _, _, as_text, _ in _patterns(words):
        text = as_text.sub(lambda m: "*" * len(m.group(0)), text)
    return text


def report(found, words):
    """One line per category: how many places and which, each shown masked. Never a value."""
    lines = []
    for category in sorted(found):
        places = found[category]
        lines.append(f"  {category}: {len(places)} {'place' if len(places) == 1 else 'places'}: "
                     + ", ".join(masked(p, words) for p in places))
    return lines


def gitleaks(staging, which=shutil.which, run=subprocess.run):
    """gitleaks's own patterns over the staged copy, when it is installed (decision 6), with the CI's config:
    ({"gitleaks: <rule>": [files]}, a line), or (None, the line saying it isn't installed)."""
    exe = which("gitleaks")
    if not exe:
        return None, NOT_INSTALLED
    staging = Path(staging)
    with tempfile.TemporaryDirectory() as folder:
        report_path = Path(folder) / "gitleaks.json"
        done = run([exe, "dir", str(staging), "--no-banner", "--redact", "--report-format", "json", "--report-path",
                    str(report_path), "--exit-code", "0"], capture_output=True, text=True, timeout=900,
                   env={**os.environ, "GITLEAKS_CONFIG_TOML": GITLEAKS_TOML})
        if done.returncode != 0:
            raise PublishError(f"gitleaks could not run (exit {done.returncode})")
        items = json.loads(report_path.read_text() or "[]") if report_path.exists() else []
    top = os.path.realpath(staging)
    found = {}
    for item in items:
        where = os.path.realpath(str(item.get("File", "")))
        place = os.path.relpath(where, top) if where.startswith(top + os.sep) else str(item.get("File", ""))
        found.setdefault(f"gitleaks: {item.get('RuleID', 'a rule')}", set()).add(place)
    line = f"gitleaks: {len(items)} finding{'s' if len(items) != 1 else ''}" if items else "gitleaks: clean"
    return {k: sorted(v) for k, v in found.items()}, line


# ---------- the export ----------

@dataclasses.dataclass
class Export:
    files: dict = dataclasses.field(default_factory=dict)    # path -> (bytes, executable)
    skipped: list = dataclasses.field(default_factory=list)  # (path, why): never copied, and said so
    stops: list = dataclasses.field(default_factory=list)    # (path, why): any one stops the publish


def _git(root, args, run=subprocess.run, input=None, env=None, check=True):
    done = run(["git", *args], cwd=str(root), capture_output=True, input=input, env=env, timeout=120)
    if check and done.returncode != 0:
        raise PublishError(f"git {args[0]} failed in {root.name}: "
                           + (done.stderr.decode(errors="replace").strip().splitlines() or ["no message"])[-1])
    return done


def _text(root, args, run=subprocess.run, **kwargs):
    return _git(root, args, run, **kwargs).stdout.decode(errors="replace").strip()


def _tree(root, rev, run):
    """[(mode, kind, sha, path)] for every entry of `rev`'s tree."""
    entries = []
    for raw in _git(root, ["ls-tree", "-r", "-z", "--full-tree", rev], run).stdout.split(b"\0"):
        if raw:
            meta, path = raw.split(b"\t", 1)
            mode, kind, sha = meta.decode().split()
            entries.append((mode, kind, sha, path.decode("utf-8", "surrogateescape")))
    return entries


def _blobs(root, shas, run):
    """{sha: bytes} for each blob, from one `git cat-file --batch`."""
    wanted = list(dict.fromkeys(shas))
    if not wanted:
        return {}
    out = _git(root, ["cat-file", "--batch"], run, input=("\n".join(wanted) + "\n").encode()).stdout
    blobs, at = {}, 0
    for sha in wanted:
        end = out.index(b"\n", at)
        size = int(out[at:end].split()[2])
        blobs[sha] = out[end + 1:end + 1 + size]
        at = end + 1 + size + 1
    return blobs


def _ignored(root, paths, run):
    """The paths .gitignore matches, tracked or not (git check-ignore --no-index)."""
    if not paths:
        return set()
    done = _git(root, ["check-ignore", "--no-index", "-z", "--stdin"], run,
                input=b"".join(p.encode("utf-8", "surrogateescape") + b"\0" for p in paths), check=False)
    return {p.decode("utf-8", "surrogateescape") for p in done.stdout.split(b"\0") if p}


def export(root=ROOT, rev="HEAD", run=subprocess.run):
    """The allowlist at `rev`: what would be copied, what is never copied and why, and what stops the publish."""
    root = Path(root)
    entries = _tree(root, rev, run)
    ignored = _ignored(root, [e[3] for e in entries], run)
    found, wanted = Export(), []
    for mode, kind, sha, path in entries:
        where = classify(path)
        if where == "never":
            continue
        if where == "neither":
            found.stops.append((path, "in neither list"))
        elif path in MADE:
            found.stops.append((path, "made at publish: it must not be tracked"))
        elif mode == "120000":
            found.skipped.append((path, "a symlink: never copied"))
        elif kind == "commit":
            found.skipped.append((path, "a submodule: never copied"))
        elif path in ignored:
            found.skipped.append((path, "matched by .gitignore: never copied"))
        else:
            wanted.append((mode, sha, path))
    blobs = _blobs(root, [sha for _, sha, _ in wanted], run)
    for mode, sha, path in wanted:
        data = blobs[sha]
        if is_binary(data):
            known = KNOWN_BINARIES.get(path)
            if known is None:
                found.stops.append((path, "a binary not in the list of known synthetic binaries"))
                continue
            if hashlib.sha256(data).hexdigest() != known:
                found.stops.append((path, "a known binary whose bytes changed"))
                continue
        found.files[path] = (data, mode == "100755")
    return found


def build(root, words, run=subprocess.run, rev="HEAD"):
    """(the copy's files, the export) at `rev`: the allowlist, docs/RULES.md made and the workflow placed."""
    found = export(root, rev, run)
    if found.stops:
        return None, found
    files = dict(found.files)
    for published, source in MADE.items():
        if not _git(root, ["cat-file", "-e", f"{rev}:{source}"], run, check=False).returncode == 0:
            raise PublishError(f"{source} is not in {rev}: the copy can't make {published}")
    rules = _git(root, ["show", f"{rev}:SUPER-ROUTER.md"], run).stdout.decode()
    try:
        name = (_full_name_parts(words.full_name) or (None,))[0]
        files["docs/RULES.md"] = (rules_copy.transform(rules, words.forbidden, name=name).encode(), False)
    except rules_copy.RulesCopyError as e:
        raise PublishError(f"docs/RULES.md: {e}") from None
    files[".github/workflows/ci.yml"] = (_git(root, ["show", f"{rev}:publish/ci.yml"], run).stdout, False)
    return files, found


# ---------- the clone ----------

def repo_of(url):
    """("owner", "name") from a GitHub-style remote URL (https, ssh or scp form, `.git` optional), or ("", last part)."""
    path = re.sub(r"^[a-z+]+://[^/]+/", "", url.strip().rstrip("/"))
    path = re.sub(r"^[^/@:]+@[^:/]+:", "", path)
    path = path[:-4] if path.endswith(".git") else path
    parts = [p for p in path.split("/") if p]
    return (parts[-2] if len(parts) > 1 else "", parts[-1] if parts else "")


def names_repo(url, wanted):
    """True when `url` names the repo `wanted` (a name, or owner/name), any case."""
    owner, name = repo_of(url)
    if "/" in wanted:
        want_owner, want_name = wanted.lower().split("/", 1)
        return (owner.lower(), name.lower()) == (want_owner, want_name)
    return name.lower() == wanted.lower() != ""


def _hook_path(clone, run):
    path = Path(_text(clone, ["rev-parse", "--git-path", "hooks/pre-push"], run))
    return path if path.is_absolute() else Path(clone) / path


def _clone_problems(root, clone, words, run):
    clone, root = Path(clone), Path(root).resolve()
    if not clone.is_dir() or not (clone / ".git").exists():
        return [f"{clone.name} is not a git checkout: clone the public repo there first"]
    top = clone.resolve()
    if top == root or root in top.parents:
        return ["the clone sits inside this repo: clone the public repo somewhere else"]
    if Path(_text(clone, ["rev-parse", "--show-toplevel"], run)).resolve() != top:
        return [f"{clone.name} is not the top of its own checkout"]
    found = []
    origin = _git(clone, ["remote", "get-url", "origin"], run, check=False)
    if origin.returncode == 0 and words.private_remote and names_repo(origin.stdout.decode(), words.private_remote):
        found.append("the clone's origin is the private repo: point it at the public one")
    head = _git(clone, ["symbolic-ref", "-q", "HEAD"], run, check=False).stdout.decode().strip()
    born = _git(clone, ["rev-parse", "-q", "--verify", "HEAD"], run, check=False).returncode == 0
    if born and head != "refs/heads/main":
        found.append(f"the clone is on {head.rsplit('/', 1)[-1] or 'a detached commit'}, not main")
    hook = _hook_path(clone, run)
    if hook.exists() and HOOK_MARK not in hook.read_text(errors="replace"):
        found.append("a pre-push hook that isn't publish's is in the clone: move it aside first")
    return found


def sync(clone, files):
    """Make the clone's files exactly `files`, never touching .git: (files written, files removed)."""
    clone = Path(clone)
    top = clone.resolve()
    present = set()
    for folder, dirs, names in os.walk(clone):
        here = Path(folder).relative_to(clone)
        if here == Path("."):
            dirs[:] = [d for d in dirs if d != ".git"]
        for d in list(dirs):
            if (Path(folder) / d).is_symlink():
                present.add(str(here / d))
                dirs.remove(d)
        present.update(str(here / n) for n in names)
    removed = 0
    for rel in sorted(present - set(files)):
        (clone / rel).unlink()
        removed += 1
    written = 0
    for rel, (data, executable) in sorted(files.items()):
        dest = clone / rel
        for parent in reversed(dest.relative_to(clone).parents[:-1]):
            step = clone / parent
            if step.is_symlink() or (step.exists() and not step.is_dir()):
                step.unlink()
        dest.parent.mkdir(parents=True, exist_ok=True)
        if top not in dest.parent.resolve().parents and dest.parent.resolve() != top:
            raise PublishError(f"{rel} would land outside the clone")
        if dest.is_symlink():
            dest.unlink()
        elif dest.is_dir():
            shutil.rmtree(dest)
        if not dest.exists() or dest.read_bytes() != data:
            dest.write_bytes(data)
            written += 1
        mode = 0o755 if executable else 0o644
        if dest.stat().st_mode & 0o777 != mode:
            os.chmod(dest, mode)
    for folder, dirs, names in sorted(os.walk(clone, topdown=False), key=lambda w: -len(Path(w[0]).parts)):
        here = Path(folder)
        if here != clone and ".git" not in here.relative_to(clone).parts[:1] and not any(here.iterdir()):
            here.rmdir()
    return written, removed


def _commit(clone, message, author, run):
    """Commit everything staged in the clone under `author`, on main; None when nothing changed."""
    if _git(clone, ["symbolic-ref", "-q", "HEAD"], run, check=False).stdout.decode().strip() != "refs/heads/main":
        _git(clone, ["symbolic-ref", "HEAD", "refs/heads/main"], run)  # an unborn clone whose default branch differs
    _git(clone, ["add", "-A"], run)
    if _git(clone, ["diff", "--cached", "--quiet"], run, check=False).returncode == 0:
        return None
    name, email = AUTHOR.fullmatch(author).groups()
    env = {**os.environ, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email, "TZ": "UTC"}  # no local zone in its dates
    _git(clone, ["commit", "-q", "--no-verify", "-m", message], run, env=env)
    return _text(clone, ["rev-parse", "--short", "HEAD"], run)


def install_hook(clone, run=subprocess.run, python=None):
    """The clone's pre-push hook: this script, on every push, scanning every outgoing commit."""
    path = _hook_path(clone, run)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{HOOK_MARK} (installed by scripts/publish.py): scans every outgoing commit before a "
                    f"push.\nexec \"{python or sys.executable}\" \"{SCRIPT}\" --pre-push \"$1\" \"$2\"\n")
    path.chmod(0o755)
    return path


# ---------- the commands ----------

def _private_problems(root, run):
    found = []
    branch = _text(root, ["symbolic-ref", "--short", "-q", "HEAD"], run, check=False)
    if branch != "main":
        found.append(f"publish runs only from main; this checkout is on {branch or 'a detached commit'}")
    if _text(root, ["status", "--porcelain", "--untracked-files=no"], run):
        found.append("a tracked file changed: commit it or put it aside first (the export reads HEAD)")
    return found


def _refused(out, problems):
    for problem in problems:
        out(f"Refused: {problem}.")
    return 1


def _scan_all(files, words, message, run):
    found = scan(files, words, message=message, identity=(words.author,))
    line = NOT_INSTALLED
    if shutil.which("gitleaks"):
        with tempfile.TemporaryDirectory() as staging:
            for rel, (data, _) in files.items():
                (Path(staging) / rel).parent.mkdir(parents=True, exist_ok=True)
                (Path(staging) / rel).write_bytes(data)
            extra, line = gitleaks(staging, run=run)
        for category, places in (extra or {}).items():
            found[category] = sorted(set(found.get(category, [])) | set(places))
    return found, line


def _publish(root, clone, words, run, out, check):
    problems = _private_problems(root, run) + words.problems(committing=not check)
    if clone is not None and not check:
        problems += _clone_problems(root, clone, words, run)
    if problems:
        return _refused(out, problems)
    files, found = build(root, words, run)
    if files is None:
        out("Stopped: the export found files that can't go public; nothing was written to the clone.")
        for path, why in found.stops:
            out(f"  {masked(path, words)}: {why}")
        return 1
    short = _text(root, ["rev-parse", "--short", "HEAD"], run)
    message = f"Publish {short}"  # a private commit's subject often names its owner: it never goes
    hits, gitleaks_line = _scan_all(files, words, message, run)
    if hits:
        out("Stopped: the scan found something; nothing was written to the clone.")
        for line in report(hits, words):
            out(line)
        return 1
    out(f"Scan: clean ({len(files)} files, their names and the commit message; {gitleaks_line})")
    for path, why in found.skipped:
        out(f"Not copied: {masked(path, words)} ({why})")
    if check:
        out("Check only: nothing was written.")
        return 0
    written, removed = sync(clone, files)
    sha = _commit(clone, message, words.author, run)
    install_hook(clone, run)
    if sha is None:
        out(f"Nothing to publish: the clone already matches HEAD ({short}).")
        return 0
    out(f"Copy: {len(files)} files ({len(files) - len(MADE)} from HEAD, {' and '.join(MADE)} made); "
        f"{written} written, {removed} removed")
    out(f"Committed in the clone: {sha} {message}")
    out("Hook: the clone's pre-push hook scans every outgoing commit")
    out("Push it yourself once you've read it:")
    out(f"  git -C {clone} show --stat HEAD")
    out(f"  git -C {clone} push -u origin main")
    return 0


def _pre_push(clone, lines, words, run, out):
    """The clone's hook: every commit the push would send, its files, their names, its message and identity."""
    problems = words.problems(committing=False)
    if problems:
        return _refused(out, [f"the publish hook can't scan: {p}" for p in problems])
    commits = []
    for line in lines.splitlines():
        parts = line.split()
        if len(parts) != 4 or set(parts[1]) == {"0"}:
            continue  # not a ref line, or a deletion
        local, remote = parts[1], parts[3]
        span = [local, "--not", "--remotes"] if set(remote) == {"0"} else [f"{remote}..{local}"]
        commits += _text(clone, ["rev-list", *span], run).split()
    hits = {}
    for commit in dict.fromkeys(commits):
        entries = _tree(clone, commit, run)
        blobs = _blobs(clone, [sha for _, kind, sha, _ in entries if kind == "blob"], run)
        files = {}
        for mode, kind, sha, path in entries:
            where = classify(path, copy=True)
            if where != "allow":
                hits.setdefault("a never-public file" if where == "never" else "a file in neither list", set()).add(path)
            if kind != "blob" or mode == "120000":
                hits.setdefault("a symlink or a submodule", set()).add(path)
                continue
            data = blobs[sha]
            if is_binary(data) and KNOWN_BINARIES.get(path) != hashlib.sha256(data).hexdigest():
                hits.setdefault("a binary not in the list of known synthetic binaries", set()).add(path)
            files[path] = (data, mode == "100755")
        message = _git(clone, ["log", "-1", "--format=%B", commit], run).stdout.decode(errors="replace")
        identity = _text(clone, ["log", "-1", "--format=%an <%ae>%n%cn <%ce>", commit], run).splitlines()
        if any(not date.endswith("+0000") for date in _text(clone, ["log", "-1", "--format=%ai%n%ci", commit], run).splitlines()):
            hits.setdefault("the commit's time zone", set()).add("the commit's dates")
        for category, places in scan(files, words, message=message, identity=identity).items():
            hits.setdefault(category, set()).update(places)
    if hits:
        out("Push stopped by the publish hook: an outgoing commit holds something that can't go public.")
        for line in report({k: sorted(v) for k, v in hits.items()}, words):
            out(line)
        return 1
    out(f"Publish hook: {len(set(commits))} outgoing commit{'s' if len(set(commits)) != 1 else ''} scanned, clean")
    return 0


USAGE = ("usage: python scripts/publish.py <clone>\n"
         "       python scripts/publish.py --check <clone>\n"
         "       python scripts/publish.py --pre-push <remote> <url>   (the clone's hook)")


def main(argv=None, *, root=ROOT, words=None, run=subprocess.run, out=print, stdin=None, cwd=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    root = Path(root)
    try:
        if argv[:1] == ["--pre-push"] and len(argv) == 3:
            return _pre_push(Path(cwd or os.getcwd()), (stdin or sys.stdin).read(),
                             words or Words.from_mac(root, run), run, out)
        check = argv[:1] == ["--check"]
        rest = argv[1:] if check else argv
        if len(rest) != 1 or rest[0].startswith("-"):
            out(USAGE)
            return 2
        return _publish(root, Path(rest[0]).expanduser(), words or Words.from_mac(root, run), run, out, check)
    except PublishError as e:
        out(f"Stopped: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
