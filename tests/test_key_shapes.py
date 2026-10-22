"""Brief 25, D5: GitHub's secret scanning and the public copy's gitleaks read every source line, so no tracked public file
holds a value in a provider's key format, not even a fake one: a test that needs one builds it at run time from pieces
(tests/test_context.py's key-scan samples). These are the common providers' formats; gitleaks in CI is the wider net."""
import re
import subprocess
from pathlib import Path

import pytest

from scripts import publish
from tests.publish_fixtures import real_git

ROOT = Path(__file__).resolve().parent.parent
# Each format with a left edge, so a slug such as `task-sr-…` isn't read as a key.
FORMATS = {
    "a Google API key": r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_\-]{35}",
    "an AWS access key id": r"(?<![A-Za-z0-9])(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}(?![A-Za-z0-9])",
    "a GitHub token": r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})",
    "a Slack token": r"(?<![A-Za-z0-9])xox[abposr]-[A-Za-z0-9-]{10,}",
    "a Stripe key": r"(?<![A-Za-z0-9])(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{10,}",
    "an OpenAI or Anthropic key": r"(?<![A-Za-z0-9])sk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}",
    "a JSON web token": r"(?<![A-Za-z0-9])eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",
    "a private key block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
}


@pytest.mark.skipif(not (ROOT / ".git").exists(), reason="not a git checkout")
def test_no_public_source_line_holds_a_provider_key_format(monkeypatch):
    real_git(monkeypatch)
    names = subprocess.run(["git", "ls-files", "-z"], cwd=str(ROOT), capture_output=True, check=True).stdout.decode()
    found = []
    for name in names.split("\0"):
        if not name or publish.classify(name, copy=True) != "allow":
            continue
        try:
            text = (ROOT / name).read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            found += [f"{name}:{number}: {what}" for what, rx in FORMATS.items() if re.search(rx, line)]
    assert found == []


def test_the_key_scan_samples_are_whole_keys_at_run_time():
    from tests.test_context import KEY_LINES
    joined = "\n".join(KEY_LINES)
    for what in ("a Google API key", "an AWS access key id", "a GitHub token", "a Slack token", "a Stripe key",
                 "an OpenAI or Anthropic key"):
        assert re.search(FORMATS[what], joined), what
