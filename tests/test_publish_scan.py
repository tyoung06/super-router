"""Build brief 25, C1 (decision 6; the owner's go of 21 Oct, item 1): every publish is scanned and any hit stops it. Each
word planted in a fake tree is caught and named by its category, never by its value: an .env value (compared in memory),
the home folder, the account name, the full name, git's email, the GitHub handle (allowed in LICENSE alone; checked in
files, file names and the commit message), the inbox repo, the private repo's name, each publish_forbidden word, and
gitleaks's findings when it is installed. The commit identity is checked against git's email only. Invented words only."""
import json
from pathlib import Path

import pytest

from scripts import publish
from tests.publish_fixtures import WORDS

ROOT = Path(__file__).resolve().parent.parent
CLEAN = {"router/core.py": (b"def hello():\n    return 'hi'\n", False),
         "LICENSE": (b"MIT License\n\nCopyright (c) 2026 zorblax06\n", False)}


def _scan(text, path="router/x.py", **kwargs):
    return publish.scan({**CLEAN, path: (text.encode(), False)}, WORDS, **kwargs)


def _report(found):
    return "\n".join(publish.report(found, WORDS))


def test_a_clean_tree_passes():
    assert publish.scan(CLEAN, WORDS, message="Publish abc1234: Brief 25 A1", identity=(WORDS.author,)) == {}


@pytest.mark.parametrize("category, planted, value", [
    ("an .env value", "key = FAKE-SECRET-VALUE-123", "FAKE-SECRET-VALUE-123"),
    ("the home folder", "open /Users/zorblax/notes", "/Users/zorblax"),
    ("the account name", "made by zorblax today", "zorblax"),
    ("the full name", "by Quinn Zorblax", "Quinn Zorblax"),
    ("the full name", "file quinn_zorblax.pdf", "quinn_zorblax"),
    ("git's email", "mail QUINN@zorblax.invalid", "QUINN@zorblax.invalid"),
    ("the GitHub handle", "see zorblax06 on GitHub", "zorblax06"),
    ("the inbox repo", "issues land in zorblax06/zorblax-inbox-repo", "zorblax-inbox-repo"),
    ("the private repo's name", "push to zorblax-private-dev", "zorblax-private-dev"),
    ("a publish_forbidden word", "about SecretProj", "SecretProj"),
    ("a publish_forbidden word", "trade on examplebroker", "examplebroker"),
])
def test_each_word_planted_in_a_file_is_caught_and_named_by_category_never_by_value(category, planted, value):
    found = _scan(planted)
    assert "router/x.py" in found[category]
    text = _report(found)
    assert category in text and "router/x.py" in text and value.lower() not in text.lower()


def test_a_binary_is_scanned_as_bytes():
    found = publish.scan({**CLEAN, "docs/a.png": (b"\x89PNG\x00\x00secretproj\x00", False)}, WORDS)
    assert found == {"a publish_forbidden word": ["docs/a.png"]}


def test_the_handle_is_allowed_in_license_alone_and_the_inbox_never():
    assert publish.scan(CLEAN, WORDS) == {}
    assert _scan("by zorblax06", path="README.md") == {"the GitHub handle": ["README.md"]}
    assert _scan("Copyright (c) 2026 zorblax06", path="docs/LICENSE") == {"the GitHub handle": ["docs/LICENSE"]}
    found = _scan("Copyright (c) 2026 zorblax06/zorblax-inbox-repo", path="LICENSE")
    assert "LICENSE" in found["the inbox repo"]


def test_a_file_name_is_scanned_and_shown_masked():
    found = _scan("nothing here", path="docs/secretproj-notes.md")
    assert found == {"a publish_forbidden word": ["docs/secretproj-notes.md"]}
    text = _report(found)
    assert "secretproj" not in text.lower() and "docs/**********-notes.md" in text


def test_the_commit_message_is_scanned_for_every_word_the_handle_included():
    found = publish.scan(CLEAN, WORDS, message="Publish abc1234: notes from zorblax06 on secretproj")
    assert found == {"the GitHub handle": ["the commit message"], "a publish_forbidden word": ["the commit message"]}


def test_the_identity_is_checked_against_gits_email_only():
    assert publish.scan(CLEAN, WORDS, identity=(WORDS.author, "zorblax06 <1+zorblax06@users.noreply.github.com>")) == {}
    found = publish.scan(CLEAN, WORDS, identity=("Quinn <Quinn@Zorblax.invalid>",))
    assert found == {"git's email": ["the commit's identity"]}


def test_env_values_are_compared_in_memory_and_counted():
    found = _scan("a FAKE-SECRET-VALUE-123 and FAKE-SECRET-VALUE-123 again")
    text = _report(found)
    assert found == {"an .env value": ["router/x.py"]} and "FAKE-SECRET" not in text


def test_a_short_value_or_word_is_never_a_word():
    words = publish.Words(env=("short",), account="pat", forbidden=("",), handle="t")
    assert publish.scan({"router/path.py": (b"a short pattern by t", False)}, words) == {}


# ---------- gitleaks, when it is installed ----------

def test_without_gitleaks_the_scan_says_so(tmp_path):
    found, line = publish.gitleaks(tmp_path, which=lambda name: None)
    assert found is None and line == "gitleaks: not installed here; it runs in the public repo's CI"


def test_gitleaks_findings_are_named_by_rule_and_file(tmp_path):
    seen = {}

    def run(argv, **kwargs):
        seen["argv"], seen["env"] = argv, kwargs.get("env", {})
        report = Path(argv[argv.index("--report-path") + 1])
        report.write_text(json.dumps([{"RuleID": "aws-access-token", "File": str(tmp_path / "router" / "x.py"),
                                       "Secret": "REDACTED", "Match": "REDACTED"}]))

        class Done:
            returncode, stdout, stderr = 0, "", ""
        return Done()

    found, line = publish.gitleaks(tmp_path, which=lambda name: "/usr/local/bin/gitleaks", run=run)
    assert found == {"gitleaks: aws-access-token": ["router/x.py"]} and "1 finding" in line
    assert seen["argv"][:3] == ["/usr/local/bin/gitleaks", "dir", str(tmp_path)] and "--redact" in seen["argv"]
    assert seen["env"]["GITLEAKS_CONFIG_TOML"] == publish.GITLEAKS_TOML


def test_the_local_gitleaks_config_is_the_one_ci_uses():
    source = ROOT / "publish" / "ci.yml"
    ci = (source if source.exists() else ROOT / ".github" / "workflows" / "ci.yml").read_text()
    block = ci.split("GITLEAKS_CONFIG_TOML: |\n")[1].split("        run: |")[0]
    lines = [line[12:] for line in block.rstrip("\n").splitlines()]
    assert "\n".join(lines).strip() + "\n" == publish.GITLEAKS_TOML


def test_the_words_are_read_from_this_macs_files_at_run_time(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.local.json").write_text(json.dumps({
        "grok_inbox_repo": "zorblax06/zorblax-inbox-repo", "private_remote": " zorblax-private-dev ",
        "publish_forbidden": ["secretproj", 3, " examplebroker "], "publish_author": WORDS.author}))
    (tmp_path / ".env").write_text("JEV_API_KEY=FAKE-SECRET-VALUE-123\nSHORT=abc\n")
    answers = {"id -F": "Quinn Zorblax\n", "config user.email": "quinn@zorblax.invalid\n", "config user.name": "zorblax06\n"}

    class Done:
        def __init__(self, out):
            self.returncode, self.stdout, self.stderr = 0, out, ""

    def run(argv, **kwargs):
        key = " ".join(argv[-2:]) if argv[0] == "git" else " ".join(argv)
        return Done(answers[key])

    words = publish.Words.from_mac(tmp_path, run=run)
    assert words == publish.Words(env=("FAKE-SECRET-VALUE-123",), home=str(Path.home()), account=Path.home().name,
                                  full_name="Quinn Zorblax", email="quinn@zorblax.invalid", handle="zorblax06",
                                  inbox="zorblax06/zorblax-inbox-repo", private_remote="zorblax-private-dev",
                                  forbidden=("secretproj", "examplebroker"), author=WORDS.author)
    assert words.problems() == []


@pytest.mark.parametrize("planted", ["by Quinn today", "Quinn's notes", "quinn_label = 1", "QUINN in capitals", "call quinn()"])
def test_the_first_name_is_caught_as_a_whole_word_in_any_case(planted):
    found = _scan(planted)
    assert found.get("the first name") == ["router/x.py"] and "quinn" not in _report(found).lower()


def test_a_longer_word_that_starts_with_the_first_name_is_not_it():
    assert "the first name" not in _scan("Quinnton and quinnish stay")


def test_the_first_name_is_looked_for_in_the_commit_message_too():
    assert publish.scan(CLEAN, WORDS, message="Publish abc1234 for Quinn") == {"the first name": ["the commit message"]}


# ---------- the design chat's scrub (21 Oct): a name against an escape's letter, or at a camelCase seam ----------
# In source text "\n" puts the letter n right against a name and `askQuinn` a lowercase letter: both hid a name from
# edges that only asked for no letter beside it. Each is planted as it sits in a file (raw strings: the backslash is text).

ESCAPES = [r"'\nQuinn'", r"'\rQuinn'", r"'\tquinn'", r"'\\Quinn'", r"'\x41Quinn'", r"'\xAAQuinn'", r"'êquinn'",
           r"url = 'a%2Fquinn'"]
SEAMS = ["askQuinn()", "myQuinnLabel = 1", "quinnSays = 1", "QuinnSays()"]


@pytest.mark.parametrize("planted", ESCAPES + SEAMS)
def test_the_first_name_right_after_an_escape_or_at_a_camel_case_seam_is_caught(planted):
    found = _scan(planted)
    assert found.get("the first name") == ["router/x.py"] and "quinn" not in _report(found).lower()


@pytest.mark.parametrize("planted", [p.replace("Quinn", "Zorblax").replace("quinn", "zorblax") for p in ESCAPES + SEAMS])
def test_the_account_name_right_after_an_escape_or_at_a_camel_case_seam_is_caught(planted):
    found = _scan(planted)
    assert found.get("the account name") == ["router/x.py"] and "zorblax" not in _report(found).lower()


@pytest.mark.parametrize("text", ["squinny", "aquinnt", "SQUINNY", "McQuinnish", r"'\nQuinnton'", "askQuinnton",
                                  "zorblaxian", "unzorblaxed", r"'\tzorblaxish'", "theZorblaxite"])
def test_an_escape_or_a_seam_never_makes_a_longer_word_count(text):
    found = _scan(text)
    assert "the first name" not in found and "the account name" not in found
