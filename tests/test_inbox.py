"""Inbox tests for the gh calls. No network."""
import json
import subprocess

import pytest

from router import inbox, safety, settings

LIST_ARGV = [
    "gh", "issue", "list", "--repo", "owner/inbox",
    "--state", "open", "--limit", "200", "--json", "number,title,body,url",
]


def test_inbox_fetch_issues_uses_the_gh_list_call(fake_run):
    issues = [{"number": 3, "title": "sr-1", "body": "pong", "url": "https://example.com/3"}]
    run = fake_run(stdout=json.dumps(issues))
    assert inbox.fetch_issues(run=run) == issues
    argv, kw = run.calls[0]
    assert argv == LIST_ARGV
    assert kw["timeout"] == 60


def test_inbox_fetch_issues_gh_failure_raises(fake_run):
    with pytest.raises(inbox.InboxError) as err:
        inbox.fetch_issues(run=fake_run(returncode=1, stderr="HTTP 401\n"))
    assert "401" in str(err.value)


def test_inbox_fetch_issues_bad_json_raises(fake_run):
    with pytest.raises(inbox.InboxError):
        inbox.fetch_issues(run=fake_run(stdout="not json"))


def test_inbox_fetch_issues_timeout_raises(fake_run):
    with pytest.raises(inbox.InboxError):
        inbox.fetch_issues(run=fake_run(raises=subprocess.TimeoutExpired(["gh"], 60)))


def test_inbox_close_issue_uses_the_gh_close_call(fake_run):
    run = fake_run()
    inbox.close_issue(3, run=run)
    argv, _ = run.calls[0]
    assert argv == ["gh", "issue", "close", "3", "--repo", "owner/inbox"]


def test_inbox_one_match_per_task_even_with_duplicate_issues():
    issues = [
        {"number": 3, "title": "sr-1", "body": "first", "url": "u3"},
        {"number": 4, "title": "sr-1", "body": "second", "url": "u4"},
    ]
    got = inbox.match_results(["sr-1"], issues)
    assert [g["number"] for g in got] == [3]


def test_inbox_error_is_a_safe_error():
    assert issubclass(inbox.InboxError, safety.SafeError)


# ---------- build brief 24 (decision 11): the inbox repo is a setting ----------

def test_every_gh_call_reads_the_inbox_setting_on_each_use(fake_run, monkeypatch, tmp_path):
    local = tmp_path / "elsewhere.local.json"
    local.write_text(json.dumps({"grok_inbox_repo": "someone/other-inbox"}))
    monkeypatch.setattr(settings, "LOCAL_PATH", local)
    run = fake_run(stdout="[]")
    inbox.fetch_issues(run=run)
    inbox.close_issue(4, run=run)
    assert run.calls[0][0][4] == "someone/other-inbox" and run.calls[1][0][-1] == "someone/other-inbox"


@pytest.mark.parametrize("doc, words", [({}, "no inbox repo in settings"),
                                        ({"grok_inbox_repo": "../x"}, "grok_inbox_repo in settings isn't owner/name")])
def test_without_a_usable_setting_no_gh_call_is_made(fake_run, monkeypatch, tmp_path, doc, words):
    local = tmp_path / "none.local.json"
    local.write_text(json.dumps(doc))
    monkeypatch.setattr(settings, "LOCAL_PATH", local)
    run = fake_run(stdout="[]")
    for call in (lambda: inbox.fetch_issues(run=run), lambda: inbox.close_issue(1, run=run),
                 lambda: inbox.fetch_file("media/out/sr-1/a.png", run=run)):
        with pytest.raises(inbox.InboxError) as err:
            call()
        assert str(err.value) == f"Grok Bot isn't set up: {words}"
    assert run.calls == []


def test_the_code_names_no_inbox_repo():
    assert not hasattr(inbox, "REPO")
