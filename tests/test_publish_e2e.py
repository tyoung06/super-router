"""Build brief 25, C1 (decision 9): the publish script end to end against a temp bare repo, never GitHub. The first run
commits the copy in the clone as "Publish <sha>: <subject>" under publish_author and installs the clone's pre-push hook; a
second run with no change commits nothing; a file removed here disappears there; a hit stops it with the clone untouched;
`--check` touches nothing; it refuses a dirty tree, another branch, a clone that isn't one, sits inside this repo, points
at the private repo or carries a foreign hook, and missing or wrong words. The hook scans every outgoing commit. It never
pushes. Temp repos and invented words only."""
import dataclasses
import io
import os

import pytest

from scripts import publish
from tests.publish_fixtures import TREE, WORDS, commit, files_of, git, make_clone, make_private, real_git, write_tree

ZERO = "0" * 40
COPY = sorted([p for p in TREE if publish.classify(p) == "allow"] + ["docs/RULES.md", ".github/workflows/ci.yml"])


@pytest.fixture
def repos(tmp_path, monkeypatch):
    real_git(monkeypatch)
    return make_private(tmp_path), make_clone(tmp_path)


def _publish(private, clone, *flags, words=WORDS):
    lines = []
    code = publish.main([*flags, str(clone)], root=private, words=words, out=lines.append)
    return code, "\n".join(lines)


def _hook(private, clone, lines, words=WORDS):
    out = []
    code = publish.main(["--pre-push", "origin", "https://example.invalid/public.git"], root=private, words=words,
                        out=out.append, stdin=io.StringIO(lines), cwd=clone)
    return code, "\n".join(out)


# ---------- publishing ----------

def test_the_first_run_commits_the_copy_and_installs_the_hook(repos):
    private, clone = repos
    code, out = _publish(private, clone)
    assert code == 0, out
    assert files_of(clone) == COPY
    head = git(private, "rev-parse", "--short", "HEAD")
    assert git(clone, "log", "-1", "--format=%B") == f"Publish {head}"  # the private subject stays private
    assert git(clone, "log", "-1", "--format=%ai|%ci").split("|")[0].endswith("+0000")
    assert git(clone, "log", "-1", "--format=%ci").endswith("+0000")  # dated in UTC: no zone points anywhere
    assert git(clone, "log", "-1", "--format=%an <%ae>|%cn <%ce>") == f"{WORDS.author}|{WORDS.author}"
    assert git(clone, "rev-list", "--count", "HEAD") == "1" and git(clone, "status", "--porcelain") == ""
    hook = clone / ".git" / "hooks" / "pre-push"
    assert publish.HOOK_MARK in hook.read_text() and os.access(hook, os.X_OK)
    assert (clone / ".github" / "workflows" / "ci.yml").read_text() == "name: CI\n"
    rules = (clone / "docs" / "RULES.md").read_text()
    assert rules.startswith("# Super Router rules\n") and "secretproj" not in rules.lower() and "quinn" not in rules.lower()
    assert "Scan: clean" in out and f"git -C {clone} push -u origin main" in out and "pushed" not in out.lower()
    assert git(clone, "branch", "-r") == ""  # nothing went to the remote


def test_a_second_run_with_no_change_commits_nothing(repos):
    private, clone = repos
    _publish(private, clone)
    code, out = _publish(private, clone)
    assert code == 0 and "Nothing to publish" in out
    assert git(clone, "rev-list", "--count", "HEAD") == "1"


def test_a_removed_file_disappears_and_a_changed_one_follows(repos):
    private, clone = repos
    _publish(private, clone)
    git(private, "rm", "-q", "router/core.py")
    write_tree(private, {"static/app.js": "export const x = 2;\n"})
    head = commit(private, "Drop core, change app")
    code, out = _publish(private, clone)
    assert code == 0, out
    assert "router/core.py" not in files_of(clone) and (clone / "static" / "app.js").read_text() == "export const x = 2;\n"
    assert git(clone, "rev-list", "--count", "HEAD") == "2"
    assert git(clone, "log", "-1", "--format=%B") == f"Publish {head}"


def test_a_file_left_in_the_clone_by_hand_is_removed_and_git_is_never_touched(repos):
    private, clone = repos
    _publish(private, clone)
    write_tree(clone, {"stray.txt": "left by hand\n", "router/old.py": "x\n"})
    before = sorted(p.name for p in (clone / ".git").iterdir())
    _publish(private, clone)
    assert "stray.txt" not in files_of(clone) and "router/old.py" not in files_of(clone)
    assert sorted(p.name for p in (clone / ".git").iterdir()) == before


def test_a_hit_stops_and_leaves_the_clone_untouched(repos):
    private, clone = repos
    _publish(private, clone)
    head = git(clone, "rev-parse", "HEAD")
    write_tree(private, {"router/leak.py": "# by Quinn Zorblax\n"})
    commit(private, "A leak")
    code, out = _publish(private, clone)
    assert code == 1 and "the full name" in out and "router/leak.py" in out and "Zorblax" not in out
    assert git(clone, "rev-parse", "HEAD") == head and "router/leak.py" not in files_of(clone)
    assert git(clone, "status", "--porcelain") == ""


def test_the_private_subject_never_reaches_the_copy(repos):
    private, clone = repos
    write_tree(private, {"router/core.py": "def hello():\n    return 'hello'\n"})
    head = commit(private, "Quinn's notes on secretproj")
    code, out = _publish(private, clone)
    assert code == 0, out
    assert git(clone, "log", "-1", "--format=%B") == f"Publish {head}" and "secretproj" not in out.lower()


def test_check_scans_and_touches_nothing(repos):
    private, clone = repos
    code, out = _publish(private, clone, "--check")
    assert code == 0 and "Scan: clean" in out
    assert files_of(clone) == [] and not (clone / ".git" / "hooks" / "pre-push").exists()


# ---------- refusals ----------

def test_a_changed_tracked_file_refuses_but_an_untracked_one_does_not(repos):
    private, clone = repos
    write_tree(private, {"AGENTS.md": "untracked, never read\n"})
    assert _publish(private, clone)[0] == 0
    write_tree(private, {"router/core.py": "edited\n"})
    code, out = _publish(private, clone)
    assert code == 1 and "a tracked file changed" in out


def test_another_branch_refuses(repos):
    private, clone = repos
    git(private, "checkout", "-q", "-b", "other")
    code, out = _publish(private, clone)
    assert code == 1 and "only from main" in out and files_of(clone) == []


def test_a_clone_on_another_branch_refuses(repos):
    private, clone = repos
    write_tree(clone, {"x.txt": "x\n"})
    git(clone, "checkout", "-q", "-b", "draft")
    commit(clone, "a branch of its own")
    code, out = _publish(private, clone)
    assert code == 1 and "main" in out


def test_a_foreign_pre_push_hook_refuses(repos):
    private, clone = repos
    (clone / ".git" / "hooks" / "pre-push").write_text("#!/bin/sh\nexit 0\n")
    code, out = _publish(private, clone)
    assert code == 1 and "pre-push hook" in out and files_of(clone) == []


def test_a_folder_that_isnt_a_clone_refuses(repos, tmp_path):
    private, _ = repos
    plain = tmp_path / "plain"
    plain.mkdir()
    code, out = _publish(private, plain)
    assert code == 1 and "not a git checkout" in out


def test_a_clone_inside_this_repo_refuses(repos):
    private, _ = repos
    inside = private / ".worktrees" / "public"
    git(private, "clone", "-q", str(private), str(inside))
    code, out = _publish(private, inside)
    assert code == 1 and "inside this repo" in out


def test_a_clone_of_the_private_repo_refuses(repos):
    private, clone = repos
    git(clone, "remote", "set-url", "origin", "https://github.com/someone/zorblax-private-dev.git")
    code, out = _publish(private, clone)
    assert code == 1 and "the private repo" in out


@pytest.mark.parametrize("change, said", [
    ({"private_remote": ""}, "private_remote"),
    ({"forbidden": ()}, "publish_forbidden"),
    ({"forbidden": ("ab",)}, "publish_forbidden"),
    ({"author": ""}, "publish_author"),
    ({"author": "no address"}, "publish_author"),
    ({"author": "Quinn <quinn@zorblax.invalid>"}, "git's own email"),
])
def test_missing_or_wrong_words_refuse(repos, change, said):
    private, clone = repos
    code, out = _publish(private, clone, words=dataclasses.replace(WORDS, **change))
    assert code == 1 and said in out and files_of(clone) == []


# ---------- the clone's hook ----------

def test_the_hook_passes_a_clean_push_and_stops_a_leak_or_a_never_public_file(repos):
    private, clone = repos
    _publish(private, clone)
    first = git(clone, "rev-parse", "HEAD")
    assert _hook(private, clone, f"refs/heads/main {first} refs/heads/main {ZERO}\n")[0] == 0
    write_tree(clone, {"router/x.py": "by Quinn Zorblax\n"})
    leak = commit(clone, "by hand")
    code, out = _hook(private, clone, f"refs/heads/main {git(clone, 'rev-parse', 'HEAD')} refs/heads/main {first}\n")
    assert code == 1 and "the full name" in out and "Zorblax" not in out and leak
    git(clone, "reset", "-q", "--hard", first)
    write_tree(clone, {"NOTES.md": "notes\n"})
    commit(clone, "a never-public file")
    code, out = _hook(private, clone, f"refs/heads/main {git(clone, 'rev-parse', 'HEAD')} refs/heads/main {first}\n")
    assert code == 1 and "NOTES.md" in out


def test_the_hook_checks_the_identity_against_gits_email_and_ignores_a_deletion(repos):
    private, clone = repos
    _publish(private, clone)
    first = git(clone, "rev-parse", "HEAD")
    write_tree(clone, {"router/y.py": "x\n"})
    git(clone, "add", "-A")
    git(clone, "-c", "user.email=quinn@zorblax.invalid", "commit", "-q", "-m", "as git's own email")
    code, out = _hook(private, clone, f"refs/heads/main {git(clone, 'rev-parse', 'HEAD')} refs/heads/main {first}\n")
    assert code == 1 and "git's email" in out
    assert _hook(private, clone, f"(delete) {ZERO} refs/heads/old {first}\n")[0] == 0


def test_the_hook_runs_this_script_on_every_push(repos):
    private, clone = repos
    _publish(private, clone)
    text = (clone / ".git" / "hooks" / "pre-push").read_text()
    assert text.startswith("#!/bin/sh\n") and publish.HOOK_MARK in text
    assert str(publish.SCRIPT) in text and '--pre-push "$1" "$2"' in text


# ---------- words the scan must never silently stop looking for (the design chat's review, 21 Oct) ----------

def test_a_full_name_under_two_words_refuses_the_publish_and_the_hook(repos):
    private, clone = repos
    for name in ("", "Quinn", "Q Zorblax"):  # nothing, one word, or an end too short to look for
        words = dataclasses.replace(WORDS, full_name=name)
        for committing in (True, False):
            assert any("full name" in p for p in words.problems(committing=committing))
        code, out = _publish(private, clone, words=words)
        assert code == 1 and "id -F" in out and files_of(clone) == []
    assert _publish(private, clone)[0] == 0
    head = git(clone, "rev-parse", "HEAD")
    code, out = _hook(private, clone, f"refs/heads/main {head} refs/heads/main {ZERO}\n",
                      words=dataclasses.replace(WORDS, full_name="Quinn"))
    assert code == 1 and "full name" in out


def test_a_handle_under_four_characters_refuses_the_publish_and_the_hook(repos):
    private, clone = repos
    for handle in ("", "zx", "zor"):
        words = dataclasses.replace(WORDS, handle=handle)
        for committing in (True, False):
            assert any("user.name" in p for p in words.problems(committing=committing))
        code, out = _publish(private, clone, words=words)
        assert code == 1 and "user.name" in out and files_of(clone) == []
    assert _publish(private, clone)[0] == 0
    head = git(clone, "rev-parse", "HEAD")
    code, out = _hook(private, clone, f"refs/heads/main {head} refs/heads/main {ZERO}\n",
                      words=dataclasses.replace(WORDS, handle="zx"))
    assert code == 1 and "user.name" in out


def test_the_hook_refuses_a_commit_dated_in_another_zone(repos):
    private, clone = repos
    _publish(private, clone)
    first = git(clone, "rev-parse", "HEAD")
    write_tree(clone, {"router/z.py": "x = 1\n"})
    git(clone, "add", "-A")
    git(clone, "-c", "user.email=t@example.invalid", "commit", "-q", "--date=2026-10-21T12:00:00+0900", "-m", "by hand")
    code, out = _hook(private, clone, f"refs/heads/main {git(clone, 'rev-parse', 'HEAD')} refs/heads/main {first}\n")
    assert code == 1 and "the commit's time zone" in out
