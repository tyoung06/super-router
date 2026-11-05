"""Shared test helpers. Every secret here is fake."""
import os
import subprocess

import pytest

from router import __main__ as _cli
from router import online as _online

FAKE_START = "2026-10-20T12:00:00+00:00"  # build brief 22: this test process's start time in the fake process table


class FakeRun:
    """Stands in for subprocess.run. Enforces the subprocess rules on every call."""

    def __init__(self, stdout="", returncode=0, stderr="", raises=None):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr
        self.raises = raises
        self.calls = []

    def __call__(self, argv, **kwargs):
        assert isinstance(argv, list), "commands must be argument lists"
        assert all(isinstance(a, str) for a in argv), "every argument must be a string"
        assert not kwargs.get("shell"), "shell=True is not allowed"
        self.calls.append((argv, kwargs))
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


# Build brief 24: the real table of online checks, kept before `_every_agent_set_up` swaps in answers that run nothing.
REAL_ONLINE_CHECKS = dict(_online.CHECKS)
FAKE_INBOX = "owner/inbox"  # decision 11: tests use this inbox repo, never a real one
REAL_CODEX_GATE = _cli._codex_gate  # brief 24: kept before `_codex_probe_passed` swaps in a gate that runs nothing


@pytest.fixture
def fake_run():
    return FakeRun


@pytest.fixture(autouse=True)
def _temp_log_only(monkeypatch, tmp_path):
    """Every test gets its own empty log and backups folder, so no test can open or change
    the live router.db or anything in backups/."""
    from router import __main__ as cli
    from router import media
    monkeypatch.setattr(cli, "DB_PATH", tmp_path / "router.db")
    monkeypatch.setattr(cli, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(cli, "PROBE_STATE", tmp_path / "probe_state.json")  # build brief 8: never the real one
    monkeypatch.setattr(media, "MEDIA_ROOT", tmp_path / "media")  # build brief 20: a Cursor call's stream file never lands in the repo's media/
    from router import settings
    monkeypatch.setattr(settings, "LOCAL_PATH", tmp_path / "settings.local.json")  # brief 21: never the owner's own file
    from router import notes
    monkeypatch.setattr(notes, "PATH", tmp_path / "router-notes.md")  # brief 30: never the owner's own router notes
    from router import models
    monkeypatch.setattr(models, "LOCAL_PATH", tmp_path / "models.local.json")  # brief 33.3: never the owner's own defaults


@pytest.fixture(autouse=True)
def _temp_workspace(monkeypatch, tmp_path):
    """Brief 29.1 (brief 28's issue 4): no test reaches the repo's own workspace/. A command that runs agents prepares
    workspace/ first, and `git init` there wrote workspace/.git into the repo (and in a fresh clone, where it isn't there
    yet, the suite's guard refused the git and three tests failed). Every test's workspace is its own, already a git
    folder; a test of prepare_workspace itself passes its own folder."""
    from router import safety
    folder = tmp_path / "suite-workspace"  # never `workspace`, which tests make themselves
    (folder / ".git").mkdir(parents=True)
    real = safety.prepare_workspace
    monkeypatch.setattr(safety, "prepare_workspace", lambda workspace=folder, run=subprocess.run: real(workspace, run))


@pytest.fixture(autouse=True)
def _fake_process_table(monkeypatch):
    """Build brief 22 (decision 4): no test reads the real process table. This test's own process is alive and started
    at FAKE_START; every other pid is gone. Nothing is held when a test starts, and no run folder is set."""
    from router import runs
    monkeypatch.setattr(runs, "_ME", (os.getpid(), FAKE_START))
    monkeypatch.setattr(runs, "READ", lambda pid: FAKE_START if pid == os.getpid() else None)
    monkeypatch.setattr(runs, "_HELD", {})
    monkeypatch.setattr(runs, "FOLDER", None)


@pytest.fixture(autouse=True)
def _no_real_subprocesses(monkeypatch):
    """Block real gh, claude and git calls. Patching Popen also catches the
    subprocess.run defaults that router functions bind at import time."""
    def refuse(*args, **kwargs):
        raise RuntimeError("a test tried to start a real subprocess")
    monkeypatch.setattr(subprocess, "Popen", refuse)


@pytest.fixture(autouse=True)
def _no_real_http(monkeypatch):
    """Block every real HTTP call made through requests (the webhook), at the adapter every
    request passes through. Tests pass a fake `post`."""
    import requests.adapters

    def refuse(self, *args, **kwargs):
        raise RuntimeError("a test tried to make a real HTTP request")
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", refuse)


@pytest.fixture(autouse=True)
def _no_real_typesafe_client(monkeypatch):
    """Block building a real TypeSafe client, so no test can call Jev or reach the network.
    Patching the class itself also catches every module that imported it by name."""
    import typesafe_sdk

    def refuse(self, *args, **kwargs):
        raise RuntimeError("a test tried to build a real TypeSafe client")
    monkeypatch.setattr(typesafe_sdk.TypeSafeClient, "__init__", refuse)


@pytest.fixture(autouse=True)
def _every_agent_set_up(monkeypatch, tmp_path):
    """Build brief 24 (decisions 1 and 11): the default test world is a full setup with fake values: the inbox repo set
    (`owner/inbox`, in the temp settings.local.json `_temp_log_only` points at) and every online check answering yes
    without running anything. A test about a missing piece takes that piece away."""
    (tmp_path / "settings.local.json").write_text(f'{{"grok_inbox_repo": "{FAKE_INBOX}"}}\n')
    monkeypatch.setattr(_online, "CHECKS", {name: (lambda: _online.Answer((True, None))) for name in REAL_ONLINE_CHECKS})


@pytest.fixture(autouse=True)
def _codex_probe_passed(monkeypatch):
    """Build brief 24 (decision 10): no test runs the real Codex probe. The gate main hands ChatGPT's calls answers that
    the pass is on record; the tests of the gate itself build their own (router/probes.py, chatgpt_gate)."""
    from router import __main__ as cli
    monkeypatch.setattr(cli, "_codex_gate", lambda config, out, model: (lambda: (True, None)))


REAL_POPEN = subprocess.Popen  # build brief 28: taken at import, before `_no_real_subprocesses` swaps it in each test


@pytest.fixture(autouse=True)
def _no_real_copies(monkeypatch, tmp_path):
    """Build brief 28 (decision 2): every test's copies root is its own temp folder, never the owner's Application Support."""
    from router import copies
    monkeypatch.setattr(copies, "ROOT", tmp_path / "sr-root")


@pytest.fixture
def real_git(monkeypatch, tmp_path):
    """Build brief 28: real `git` (and only git) in this test, under a global config of the test's own (a name, an email
    and `main`), never the owner's. Returns the set of program names allowed; a test adds `sandbox-exec` to it."""
    allowed = {"git"}

    def popen(args, *a, **kw):
        argv = list(args) if isinstance(args, (list, tuple)) else [args]
        if os.path.basename(str(argv[0])) not in allowed:
            raise RuntimeError(f"a test tried to start a real {os.path.basename(str(argv[0]))}")
        return REAL_POPEN(args, *a, **kw)
    monkeypatch.setattr(subprocess, "Popen", popen)
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tname = Test Owner\n\temail = owner@example.invalid\n[init]\n\tdefaultBranch = main\n"
                      "[commit]\n\tgpgSign = false\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(name, raising=False)
    return allowed


from router import gitops as _gitops  # noqa: E402
REAL_GIT_INSTALLED = _gitops.installed


@pytest.fixture(autouse=True)
def _no_git_by_default(monkeypatch, request):
    """Build brief 28 (decision 1): a test reads no git unless it asks for `real_git`; for every other test git is not
    installed, so a --project task runs handoff only, as before, and nothing starts a git process."""
    if "real_git" not in request.fixturenames:
        monkeypatch.setattr(_gitops, "installed", lambda which=None: False)


@pytest.fixture
def grok_room(monkeypatch):
    """Brief 29.1 (decision 14): the check's new words alone pass Grok's prompt limit (3,729 of 3,662 characters), so on the
    real limit every Grok check is skipped and the next checker checks, as the brief accepts (tests/test_check_prompts.py
    pins that). A test of how a Grok check is sent, collected and read raises the limit with this fixture."""
    from router import settings
    monkeypatch.setattr(settings, "grok_prompt_limit", lambda: (50_000, "test"))
