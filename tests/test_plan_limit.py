"""Phase A of build brief 7 (resume): a plan limit gets its own code, `plan_limit`, for both
workers, and the test-only injected limit works only on a scratch log. Every secret here is fake.

The limit texts below were read from the installed tools' own code on 2026-10-15 (claude 2.1.301,
codex 0.162.1), never seen live: they are the answer key for the detector, fixed before it was written."""
import subprocess
from pathlib import Path

import pytest

from router import chatgpt_worker, claude_worker, plan_limit

CLAUDE_SESSION = "You've hit your session limit · resets 3pm (Etc/UTC)"
CLAUDE_WEEKLY = "You’ve hit your weekly limit · resets Oct 20, 9am"
CLAUDE_SONNET = "You've hit your Sonnet limit · resets Oct 20, 9am"
CLAUDE_OTHERS = (
    "You've reached your Fable limit. Switch to another model to continue.",
    "You're out of usage credits. /model to switch models.",
    "You're out of extra usage",
)
CODEX_LIMIT = ("ERROR: You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit "
               "https://chatgpt.com/settings/usage to purchase more credits or try again at Oct 15th, 2026 3:00 PM.")
ENVIRON = {"HOME": "/h", "PATH": "/bin"}


# ---------- the detector ----------

@pytest.mark.parametrize("text", (CLAUDE_SESSION, CLAUDE_WEEKLY, CLAUDE_SONNET) + CLAUDE_OTHERS)
def test_claude_limit_lines_on_a_non_zero_exit_are_a_plan_limit(text):
    assert plan_limit.claude(1, f"{text}\n", "") == text.replace("’", "'")
    assert plan_limit.claude(1, "", f"{text}\n") == text.replace("’", "'")


def test_any_other_claude_failure_is_not_a_plan_limit():
    assert plan_limit.claude(1, "", "not logged in") is None
    assert plan_limit.claude(1, "API Error: 529 overloaded", "") is None
    assert plan_limit.claude(1, "", "") is None


def test_an_exit_0_answer_is_a_plan_limit_only_when_it_is_exactly_the_one_line():
    assert plan_limit.claude(0, CLAUDE_SESSION + "\n", "") == CLAUDE_SESSION
    assert plan_limit.claude(0, "You've hit your weekly limit", "") == "You've hit your weekly limit"
    # a real answer that happens to start the same way is an answer, not a limit
    assert plan_limit.claude(0, "You've reached your goal! Here are three ways to celebrate.", "") is None
    assert plan_limit.claude(0, "You've hit your stride.\nKeep going.", "") is None
    assert plan_limit.claude(0, CLAUDE_SESSION + "\nmore text", "") is None
    assert plan_limit.claude(0, "You're out of usage credits.", "") is None  # only the strict line on exit 0


def test_codex_usage_limit_on_a_non_zero_exit_is_a_plan_limit():
    assert plan_limit.codex(1, "", CODEX_LIMIT) == CODEX_LIMIT.replace("’", "'")
    assert plan_limit.codex(1, CODEX_LIMIT, "") == CODEX_LIMIT.replace("’", "'")


def test_any_other_codex_failure_is_not_a_plan_limit():
    assert plan_limit.codex(1, "", "ERROR: exceeded retry limit, last status: 429 Too Many Requests") is None
    assert plan_limit.codex(1, "", "Not logged in") is None
    assert plan_limit.codex(0, CODEX_LIMIT, "") is None  # exit 0 is an answer (it comes from the file)


def test_the_limit_texts_live_in_one_place_with_the_versions_they_were_read_from():
    assert plan_limit.CODE == "plan_limit"
    assert plan_limit.READ_FROM == {"claude": "2.1.301", "codex": "0.162.1"}
    assert "You've hit your" in plan_limit.CLAUDE_OPENINGS and plan_limit.CODEX_MARK == "hit your usage limit"


# ---------- the workers ----------

def test_the_claude_worker_raises_a_plan_limit_with_the_line_kept(fake_run, tmp_path, monkeypatch):
    monkeypatch.setattr(claude_worker, "WORKSPACE", tmp_path / "workspace")
    run = fake_run(returncode=1, stdout=CLAUDE_SESSION + "\n", stderr="")
    with pytest.raises(claude_worker.WorkerError) as err:
        claude_worker.run("hi", run=run, environ=ENVIRON)
    assert err.value.code == "plan_limit"
    assert str(err.value) == f"plan limit on claude: {CLAUDE_SESSION}"


def test_any_other_claude_worker_failure_has_no_code(fake_run, tmp_path, monkeypatch):
    monkeypatch.setattr(claude_worker, "WORKSPACE", tmp_path / "workspace")
    with pytest.raises(claude_worker.WorkerError) as err:
        claude_worker.run("hi", run=fake_run(returncode=1, stderr="not logged in"), environ=ENVIRON)
    assert err.value.code is None and "exited 1" in str(err.value)


def test_a_claude_failure_with_text_only_on_stdout_keeps_that_text(fake_run, tmp_path, monkeypatch):
    """Before this build the worker kept only stderr, so a message printed as the answer was lost."""
    monkeypatch.setattr(claude_worker, "WORKSPACE", tmp_path / "workspace")
    with pytest.raises(claude_worker.WorkerError) as err:
        claude_worker.run("hi", run=fake_run(returncode=1, stdout="API Error: 529 overloaded\n"), environ=ENVIRON)
    assert err.value.code is None and "API Error: 529 overloaded" in str(err.value)


def test_the_chatgpt_worker_raises_a_plan_limit(fake_run, tmp_path, monkeypatch):
    monkeypatch.setattr(chatgpt_worker, "WORKSPACE", tmp_path / "workspace")
    with pytest.raises(chatgpt_worker.WorkerError) as err:
        chatgpt_worker.run("hi", model="gpt-6.1-sol", web_search="disabled",
                           run=fake_run(returncode=1, stderr=CODEX_LIMIT), environ=ENVIRON)
    assert err.value.code == "plan_limit"
    assert str(err.value).startswith("plan limit on chatgpt: ") and "hit your usage limit" in str(err.value)


def test_any_other_chatgpt_worker_failure_has_no_code(fake_run, tmp_path, monkeypatch):
    monkeypatch.setattr(chatgpt_worker, "WORKSPACE", tmp_path / "workspace")
    with pytest.raises(chatgpt_worker.WorkerError) as err:
        chatgpt_worker.run("hi", model="gpt-6.1-sol", web_search="disabled",
                           run=fake_run(returncode=2, stderr="boom"), environ=ENVIRON)
    assert err.value.code is None


# ---------- the injected limit (test-only, scratch log only) ----------

class Git:
    def __init__(self, common_dir=None, returncode=0, raises=None):
        self.common_dir, self.returncode, self.raises, self.calls = common_dir, returncode, raises, []

    def __call__(self, argv, **kwargs):
        assert isinstance(argv, list) and not kwargs.get("shell")
        self.calls.append(argv)
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, f"{self.common_dir}\n", "")


def test_the_real_log_is_the_main_checkouts_router_db(tmp_path):
    main = tmp_path / "super-router"
    git = Git(main / ".git")
    assert plan_limit.is_real_log(main / "router.db", root=main / ".worktrees" / "resume", run=git) is True
    assert plan_limit.is_real_log(main / ".worktrees" / "resume" / "router.db", root=main / ".worktrees" / "resume",
                                  run=git) is False
    assert git.calls[0][:2] == ["git", "-C"] and "--git-common-dir" in git.calls[0]


@pytest.mark.parametrize("git", (Git(returncode=128), Git(raises=OSError("no git")), Git(raises=subprocess.TimeoutExpired("git", 30))))
def test_when_git_cannot_say_where_the_main_checkout_is_the_log_counts_as_real(tmp_path, git):
    assert plan_limit.is_real_log(tmp_path / "router.db", root=tmp_path, run=git) is True


def test_the_injected_limit_is_refused_on_the_real_log(tmp_path):
    main = tmp_path / "super-router"
    with pytest.raises(plan_limit.InjectRefused, match="test-only.*scratch log"):
        plan_limit.injected("claude", main / "router.db", root=main, run=Git(main / ".git"))


def test_the_injected_limit_names_claude_or_chatgpt_only(tmp_path):
    with pytest.raises(plan_limit.InjectRefused, match="claude or chatgpt"):
        plan_limit.injected("grok", tmp_path / "scratch.db", root=tmp_path, run=Git(tmp_path / "main" / ".git"))


def test_the_injected_limit_fails_one_call_through_the_real_worker_then_lets_calls_through(fake_run, tmp_path,
                                                                                           monkeypatch):
    """The hook sits at the worker's process boundary, so the worker's own detector sees the limit."""
    monkeypatch.setattr(claude_worker, "WORKSPACE", tmp_path / "workspace")
    real = fake_run(stdout="a real answer")
    hook = plan_limit.injected("claude", tmp_path / "scratch.db", root=tmp_path, run=Git(tmp_path / "main" / ".git"))
    run = hook(real)
    with pytest.raises(claude_worker.WorkerError) as err:
        claude_worker.run("first", run=run, environ=ENVIRON)
    assert err.value.code == "plan_limit" and real.calls == []
    assert claude_worker.run("second", run=run, environ=ENVIRON) == "a real answer"
    assert len(real.calls) == 1


def test_the_injected_codex_limit_goes_through_the_chatgpt_worker(fake_run, tmp_path, monkeypatch):
    monkeypatch.setattr(chatgpt_worker, "WORKSPACE", tmp_path / "workspace")
    hook = plan_limit.injected("chatgpt", tmp_path / "scratch.db", root=tmp_path, run=Git(tmp_path / "main" / ".git"))
    with pytest.raises(chatgpt_worker.WorkerError) as err:
        chatgpt_worker.run("x", model="m", web_search="disabled", run=hook(fake_run(stdout="")), environ=ENVIRON)
    assert err.value.code == "plan_limit"


def test_the_injected_limit_reads_as_a_plan_limit_on_a_claude_search_call_too(fake_run, tmp_path, monkeypatch):
    """Brief 24, F: since rules v2.22 most Claude calls search, and a search call reads a stream-json result event, not
    plain text. The hook answers a stream-json call in that form, so the worker's own detector sees the limit there
    too (step 2 of F read "Claude's call failed" while the hook spoke plain text)."""
    monkeypatch.setattr(claude_worker, "WORKSPACE", tmp_path / "workspace")
    real = fake_run(stdout="")
    hook = plan_limit.injected("claude", tmp_path / "scratch.db", root=tmp_path, run=Git(tmp_path / "main" / ".git"))
    with pytest.raises(claude_worker.WorkerError) as err:
        claude_worker.run("first", run=hook(real), environ=ENVIRON, search=True)
    assert err.value.code == "plan_limit" and "You've hit your session limit" in str(err.value) and real.calls == []
