"""Phase D of build brief 4: Grok makes an image. The do prompt carries the Imagine instructions;
Grok commits the image to the inbox repo and names the path in its issue; the router pulls only
paths under media/out/<task-id>/ and appends the local paths to the result. No image back is a
failed round. No test runs gh or the webhook."""
import subprocess

import pytest

from router import __main__ as cli
from router import checking, grok, inbox, log, media, safety
from tests.helpers import JEV_OK, shipped_roster

CONFIG = {"GROK_WEBHOOK_URL": "https://example.invalid/hook", "GROK_WEBHOOK_KEY": "FAKE-KEY-123"}
PNG = inbox.PNG_MAGIC + b"\x00\x00\x00\rIHDR" + b"\x00" * 20
TASK = "Make a logo for a newsletter called Twenty Something"


@pytest.fixture(autouse=True)
def folders(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "MEDIA_ROOT", tmp_path / "media")
    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setattr(safety, "WORKSPACE", ws)
    return tmp_path


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


class Reply:
    status_code = 200

    def json(self):
        return {"success": True, "runUuid": "uuid-1"}


def post(url, **kwargs):
    return Reply()


class Scripted:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return self.replies.pop(0)


def _issue(task_id, body, number=7):
    return {"title": task_id, "body": body, "url": f"https://github.com/x/y/issues/{number}", "number": number}


# ---------- the prompt ----------

def test_the_imagine_instructions_cap_at_4_images_only_and_name_the_commit_folder():
    text = grok.imagine_instructions("sr-20261013-120000-ab12")
    assert "Grok Imagine" in text and "At most 4 images" in text
    assert "Images only" in text and "video" in text and "make nothing" in text
    assert "media/out/sr-20261013-120000-ab12/<short-name>.png" in text and "list each committed path" in text
    assert grok.make_media_prompt("sr-1", TASK) == f"{TASK}\n\n{grok.imagine_instructions('sr-1')}"


# Build brief 24 (decision 11): the sentence as it always read, the repo's name part now from `grok_inbox_repo`
INSTRUCTION = ("Make the image with Grok Imagine. At most 4 images. Images only: if the task asks for a video, say so and "
               "make nothing. Commit each image to the {name} repository at media/out/{task_id}/<short-name>.png, where "
               "<short-name> is a few plain words joined by dashes. Then return the result as usual, and list each committed "
               "path on its own line.")


def test_the_instruction_names_the_settings_repo_and_is_otherwise_unchanged():
    assert grok.imagine_instructions("sr-1") == INSTRUCTION.format(name="inbox", task_id="sr-1")  # conftest: owner/inbox
    assert grok.imagine_instructions("sr-2", repo="someone/pictures") == INSTRUCTION.format(name="pictures", task_id="sr-2")


def _make_media_task(conn, task_id="sr-20261013-120000-ab12"):
    log.add_task(conn, task_id, TASK, "cli", {**JEV_OK, "label": "make_media"})
    log.set_route(conn, task_id, agents=("claude", "grok", "chatgpt", "muse"), agent="grok", route_reason="best",
                  skill="make_media", skill_source="jev", checker="claude", check_state="pending")
    return log.get_task(conn, task_id)


def test_the_do_and_fix_calls_to_grok_carry_the_instructions_and_the_check_does_not(conn):
    task = _make_media_task(conn)
    _, kind, agent, prompt, _ = cli._plan_call(task, checking.Step("do"))
    assert (kind, agent) == ("do", "grok") and prompt == grok.make_media_prompt(task["task_id"], TASK)
    _, kind, agent, prompt, _ = cli._plan_call(task, checking.Step("fix", result="r", fix_list="1. bigger"))
    imagine = grok.imagine_instructions(task["task_id"])  # brief 11.1 (E1): right after the review notes
    assert (kind, agent) == ("fix", "grok") and imagine in prompt
    assert prompt.index("===== REVIEW NOTES =====") < prompt.index(imagine) < prompt.index("===== EARLIER RESULT =====")
    _, kind, agent, prompt, _ = cli._plan_call(task, checking.Step("check", result="r"))
    assert (kind, agent) == ("check", "claude") and "Grok Imagine" not in prompt


# ---------- the paths Grok names ----------

def test_listed_images_accepts_only_this_tasks_pngs_under_media_out():
    tid = "sr-20261013-120000-ab12"
    body = ("Done. media/out/sr-20261013-120000-ab12/blue-square.png and media/out/sr-20261013-120000-ab12/blue-square.png\n"
            "also media/out/sr-20261013-120000-ffff/other.png, media/in/sr-20261013-120000-ab12/x.png, "
            "media/out/sr-20261013-120000-ab12/photo.jpg, ../etc/thing.png, media/out/sr-20261013-120000-ab12/second-try.png")
    accepted, ignored = inbox.listed_images(body, tid)
    assert accepted == [f"media/out/{tid}/blue-square.png", f"media/out/{tid}/second-try.png"]
    assert f"media/out/sr-20261013-120000-ffff/other.png" in ignored and f"media/in/{tid}/x.png" in ignored
    assert f"media/out/{tid}/photo.jpg" in ignored and "../etc/thing.png" in ignored
    assert inbox.listed_images("no paths here", tid) == ([], [])
    assert inbox.listed_images(None, tid) == ([], [])


# ---------- the pull ----------

import base64
import json


class GhApi:
    """gh api answering the contents API, then the blob API, as JSON. `big` means the file is over
    1 MB: the contents document carries no content, only a sha, and the blob carries the bytes."""

    def __init__(self, data=PNG, returncode=0, raises=None, big=False, encoding="base64"):
        self.data, self.returncode, self.raises, self.big, self.encoding = data, returncode, raises, big, encoding
        self.calls = []

    def __call__(self, argv, **kwargs):
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv) and not kwargs.get("shell")
        assert kwargs.get("text") is True, "JSON through gh, never binary"
        self.calls.append(argv)
        if self.raises:
            raise self.raises
        b64 = base64.b64encode(self.data).decode()
        wrapped = "\n".join(b64[i:i + 60] for i in range(0, len(b64), 60)) + "\n"  # GitHub wraps base64 at 60
        if "/contents/" in argv[-1]:
            doc = {"sha": "abc123", "size": len(self.data), "encoding": "none", "content": ""} if self.big else \
                  {"sha": "abc123", "size": len(self.data), "encoding": self.encoding, "content": wrapped}
        else:
            doc = {"sha": "abc123", "size": len(self.data), "encoding": "base64", "content": wrapped}
        return subprocess.CompletedProcess(argv, self.returncode, json.dumps(doc), "boom")


def test_fetch_file_reads_the_contents_api_as_json_and_decodes_the_base64():
    run = GhApi()
    assert inbox.fetch_file("media/out/sr-1/blue.png", run=run) == PNG
    assert run.calls == [["gh", "api", "repos/owner/inbox/contents/media/out/sr-1/blue.png"]]
    assert "clone" not in " ".join(run.calls[0]) and "-H" not in run.calls[0]


def test_a_file_over_1_mb_comes_through_the_blob_api_by_sha():
    run = GhApi(big=True)
    assert inbox.fetch_file("media/out/sr-1/blue.png", run=run) == PNG
    assert run.calls[1] == ["gh", "api", "repos/owner/inbox/git/blobs/abc123"]


@pytest.mark.parametrize("run, words", [
    (GhApi(returncode=1), "failed: boom"),
    (GhApi(data=b""), "no content"),
    (GhApi(encoding="utf-8"), "not base64"),
    (GhApi(raises=OSError("no gh")), "could not start gh"),
    (GhApi(raises=subprocess.TimeoutExpired(["gh"], 60)), "timed out"),
], ids=["exit 1", "empty", "not base64", "no gh", "timeout"])
def test_a_failed_pull_raises_with_the_reason(run, words):
    with pytest.raises(inbox.InboxError, match=words):
        inbox.fetch_file("media/out/sr-1/blue.png", run=run)


# ---------- the round trip ----------

def _route(conn, task=TASK):
    lines = []
    code = cli.cmd_route(task, conn=conn, config=CONFIG, roster=shipped_roster(), environ={}, settings_paths=[],
                         label=lambda text, **kw: {**JEV_OK, "label": "make_media"}, post=post, worker=Scripted(),
                         codex_login=lambda: True, wait=False, out=lines.append)
    row = log.recent_tasks(conn)[0]
    return code, "\n".join(lines), row


def _check(conn, issues, worker, pulled=None, monkeypatch=None):
    lines = []
    code = cli.cmd_check(conn=conn, config=CONFIG, fetch=lambda: issues, close=lambda n: None, environ={}, settings_paths=[],
                         post=post, worker=worker, codex_login=lambda: True, out=lines.append)
    return code, "\n".join(lines)


def test_grok_makes_an_image_the_router_pulls_it_and_claude_checks(conn, monkeypatch, folders):
    code, out, row = _route(conn)
    assert code == 0 and row["status"] == "sent" and row["agent"] == "grok" and "sent to grok (do)" in out
    tid = row["task_id"]
    pulls = []

    def fetch_file(path):
        pulls.append(path)
        return PNG
    monkeypatch.setattr(cli.inbox, "fetch_file", fetch_file)
    worker = Scripted("PASS")
    issue = _issue(tid, f"Here is the logo.\nmedia/out/{tid}/twenty-something.png")
    code, out = _check(conn, [issue], worker)
    row = log.get_task(conn, tid)
    assert pulls == [f"media/out/{tid}/twenty-something.png"]
    saved = media.outputs(tid)
    assert [p.name for p in saved] == ["twenty-something.png"] and saved[0].read_bytes() == PNG
    assert "1 image(s) pulled into media/out/" in out
    assert row["status"] == "done" and row["check_state"] == "passed"
    assert row["result"] == f"{issue['body']}\n\nImages:\n{saved[0]}", "Grok's text, then the local paths"
    do = log.calls_for(conn, tid)[0]
    assert do["status"] == "done" and do["text"] == row["result"] and do["url"].endswith("/issues/7")
    assert "CHECKED: passed." in out and code == 0
    # the checker got Grok's image as a copy under out/ (Phase E)
    prompt, kwargs = worker.calls[0]
    assert kwargs == {"files": [(saved[0], "out/twenty-something.png")], "tag": tid}
    assert "in your working folder: out/twenty-something.png" in prompt and "Read tool" in prompt


def test_no_image_back_is_a_failed_round_with_groks_text_kept(conn, monkeypatch):
    _, _, row = _route(conn)
    tid = row["task_id"]
    monkeypatch.setattr(cli.inbox, "fetch_file", lambda path: PNG)
    code, out = _check(conn, [_issue(tid, "I can't make a video, so I made nothing.")], Scripted("PASS"))
    row = log.get_task(conn, tid)
    assert row["status"] == "failed" and row["result"].startswith("no image came back from grok. Its text: I can't make a video")
    do = log.calls_for(conn, tid)[0]
    assert do["status"] == "failed" and do["text"] == "I can't make a video, so I made nothing."
    assert "No image came back" in out and "never retried" in out and media.outputs(tid) == []


def test_a_path_outside_the_tasks_folder_is_ignored_and_said_so(conn, monkeypatch):
    _, _, row = _route(conn)
    tid = row["task_id"]
    pulls = []
    monkeypatch.setattr(cli.inbox, "fetch_file", lambda path: pulls.append(path) or PNG)
    body = f"media/out/sr-20261013-000000-ffff/not-mine.png and media/in/{tid}/sneaky.png and media/out/{tid}/mine.png"
    code, out = _check(conn, [_issue(tid, body)], Scripted("PASS"))
    assert pulls == [f"media/out/{tid}/mine.png"]
    assert "Ignored a path grok listed outside media/out/" in out and "not-mine.png" in out and "sneaky.png" in out
    assert [p.name for p in media.outputs(tid)] == ["mine.png"]


def test_a_payload_that_is_not_a_png_is_ignored(conn, monkeypatch):
    _, _, row = _route(conn)
    tid = row["task_id"]
    monkeypatch.setattr(cli.inbox, "fetch_file", lambda path: b"<html>not found</html>")
    code, out = _check(conn, [_issue(tid, f"media/out/{tid}/blue.png")], Scripted("PASS"))
    assert "Ignored blue.png: not a PNG." in out and log.get_task(conn, tid)["status"] == "failed"


def test_more_than_four_images_are_pulled_and_logged_not_refused(conn, monkeypatch):
    _, _, row = _route(conn)
    tid = row["task_id"]
    monkeypatch.setattr(cli.inbox, "fetch_file", lambda path: PNG)
    body = "\n".join(f"media/out/{tid}/v{i}.png" for i in range(1, 6))
    code, out = _check(conn, [_issue(tid, body)], Scripted("PASS"))
    assert len(media.outputs(tid)) == 5 and "5 image(s) pulled (the cap is 4)" in out


def test_a_pull_that_fails_is_reported_and_the_rest_still_count(conn, monkeypatch):
    _, _, row = _route(conn)
    tid = row["task_id"]

    def fetch_file(path):
        if path.endswith("a.png"):
            raise inbox.InboxError("gh api failed on a.png: 404")
        return PNG
    monkeypatch.setattr(cli.inbox, "fetch_file", fetch_file)
    code, out = _check(conn, [_issue(tid, f"media/out/{tid}/a.png media/out/{tid}/b.png")], Scripted("PASS"))
    assert "Could not pull a.png: gh api failed on a.png: 404" in out
    assert [p.name for p in media.outputs(tid)] == ["b.png"] and log.get_task(conn, tid)["status"] == "done"


def test_a_fix_round_that_brings_no_image_back_fails_and_the_first_image_is_delivered(conn, monkeypatch):
    _, _, row = _route(conn)
    tid = row["task_id"]
    monkeypatch.setattr(cli.inbox, "fetch_file", lambda path: PNG)
    # the do round brings an image; Claude asks for a fix; the fix round is sent to Grok
    code, out = _check(conn, [_issue(tid, f"media/out/{tid}/v1.png")], Scripted("FIX\n1. Make the text larger."))
    assert "sent to grok (fix)" in out and log.get_task(conn, tid)["status"] == "sent"
    # the fix issue names nothing: the fix round failed; the original result stands, with the fix list
    code, out = _check(conn, [_issue(f"{tid}-f1", "Imagine is down today.", number=8)], Scripted("PASS"))  # the fix call's id
    row = log.get_task(conn, tid)
    assert row["status"] == "done" and row["check_state"] == "failed" and code == 5
    assert row["result"].endswith("v1.png") and "FIX ROUND FAILED: grok" in out
    fix = [c for c in log.calls_for(conn, tid) if c["kind"] == "fix"][0]
    assert fix["status"] == "failed" and fix["text"] == "Imagine is down today."
