"""Build brief 25, B5 (decision 7): the public copy's CI. It lives in the private repo at publish/ci.yml (so the private
repo spends no Actions minutes) and the publish script places it at .github/workflows/ci.yml in the copy. macos-latest,
Python 3.14 (the README's), node 26, the pinned requirements, the fake-only suite and `node --test`, and gitleaks from a
pinned release whose checksum is checked before it is unpacked. Read-only token, no secrets, only GitHub's own actions,
each pinned by commit."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE, PLACED = ROOT / "publish" / "ci.yml", ROOT / ".github" / "workflows" / "ci.yml"
CI = (SOURCE if SOURCE.exists() else PLACED).read_text()
README = (ROOT / "README.md").read_text()


def test_only_githubs_own_actions_each_pinned_by_commit():
    uses = re.findall(r"uses:\s*(\S+)", CI)
    assert sorted({u.split("@")[0] for u in uses}) == ["actions/checkout", "actions/setup-node", "actions/setup-python"]
    assert all(re.fullmatch(r"[\w-]+/[\w-]+@[0-9a-f]{40}", u) for u in uses)


def test_a_read_only_token_no_secrets_and_no_kept_credentials():
    assert re.search(r"(?m)^permissions:\n  contents: read\n(?!  )", CI)
    assert "write" not in CI.split("jobs:")[0] and "secrets." not in CI
    assert "persist-credentials: false" in CI


def test_the_runner_and_the_versions():
    assert "runs-on: macos-latest" in CI
    python = re.search(r'python-version: "([\d.]+)"', CI).group(1)
    assert python == "3.14" and f"Python {python}" in README
    assert re.search(r'node-version: "26"', CI)


def test_the_suite_and_the_pages_logic_run():
    assert "python -m pip install -r requirements.txt" in CI
    assert "python -m pytest -q" in CI and "node --test tests/js/" in CI


def test_gitleaks_is_a_pinned_release_checked_by_its_checksum_before_it_runs():
    assert re.search(r'GITLEAKS_VERSION: "8\.30\.1"', CI)
    assert re.search(r'GITLEAKS_SHA256: "[0-9a-f]{64}"', CI)
    check, unpack, run = CI.index("shasum -a 256 -c"), CI.index("tar -xzf"), CI.index('/gitleaks" git')
    assert check < unpack < run
    assert "--redact" in CI and "--exit-code 1" in CI


def test_the_fakes_allowlist_targets_the_match_and_no_path():
    toml = CI.split("GITLEAKS_CONFIG_TOML: |")[1].split("run:")[0]
    assert "useDefault = true" in toml and "[[allowlists]]" in toml and 'regexTarget = "match"' in toml
    assert "paths" not in toml
