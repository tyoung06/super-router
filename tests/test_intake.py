"""`sr route --file`: intake (rules v2.10, Media). Fakes stand in for Jev, the workers, ffmpeg and the
webhook; no test touches the real media/ folder."""
import json
from pathlib import Path

import pytest

from router import __main__ as cli
from router import log, media, routing, safety
from tests.helpers import JEV_OK, shipped_roster

CONFIG = {"GROK_WEBHOOK_URL": "https://example.invalid/hook", "GROK_WEBHOOK_KEY": "FAKE-KEY-123"}
ROSTER = shipped_roster()


@pytest.fixture(autouse=True)
def media_root(tmp_path, monkeypatch):
    root = tmp_path / "media"
    monkeypatch.setattr(media, "MEDIA_ROOT", root)
    return root


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


class Recorder:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.reply


def ok(skill):
    return {**JEV_OK, "label": skill}


def _file(tmp_path, name, size=1000):
    p = tmp_path / name
    p.write_bytes(b"x" * size)
    return p


def frames_ok(clip, dest):
    paths = [Path(dest) / f"frame_{i:02d}.jpg" for i in range(1, 13)]
    for p in paths:
        p.write_bytes(b"jpg")
    return paths


def frames_fail(clip, dest):
    raise media.MediaError(f"ffmpeg failed on {Path(clip).name}: moov atom not found")


def pages_ok(pdf, dest, total=3, count=3):
    paths = [Path(dest) / f"page-{i}.png" for i in range(1, count + 1)]
    for p in paths:
        p.write_bytes(b"png")
    return paths, total


def pages_cut(pdf, dest):
    return pages_ok(pdf, dest, total=30, count=12)


def pages_fail(pdf, dest):
    raise media.MediaError(f"pdftoppm failed on {Path(pdf).name}: Syntax Error")


def _route(conn, task, jev, files, *, frames=frames_ok, pages=pages_ok, worker=None, chatgpt=None, ask=None):
    lines, seen = [], []

    def label(text, *, task_id, tokens_this_month):
        seen.append(text)
        return dict(jev)
    worker = worker or Recorder("the answer")
    chatgpt = chatgpt or Recorder("PASS")
    code = cli.cmd_route(task, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=label,
                         post=Recorder(None), worker=worker, chatgpt=chatgpt, codex_login=lambda: True, ask=ask,
                         files=files, frames=frames, pages=pages, out=lines.append)
    rows = log.recent_tasks(conn)
    return code, "\n".join(lines), (rows[0] if rows else None), seen


# ---------- pages from a PDF (rules v2.11) ----------

def test_a_pdf_gets_its_pages_rendered_at_intake(conn, tmp_path, media_root):
    pdf = _file(tmp_path, "paper.pdf", size=4096)
    seen_pages = []

    def pages(copy, dest):
        seen_pages.append((copy, dest))
        return pages_ok(copy, dest)
    code, out, row, seen = _route(conn, "summarise this", ok("read_media"), [pdf], pages=pages)
    assert code == 0
    tid = row["task_id"]
    # brief 24 (decision 17): each PDF's pages in its own folder, its stem
    assert seen_pages == [(media_root / "in" / tid / "paper.pdf", media_root / "pages" / tid / "paper")]
    f = log.files_of(row)[0]
    assert (f["name"], f["pages"], f["total_pages"]) == ("paper.pdf", 3, 3)
    assert len(list((media_root / "pages" / tid / "paper").glob("page-*.png"))) == 3
    assert seen == ["summarise this\n[file: paper.pdf, application/pdf, 4 KB]"], "Jev learns nothing about pages"


def test_a_failed_page_render_refuses_the_task_before_jev_and_cleans_up(conn, tmp_path, media_root):
    code, out, row, seen = _route(conn, "summarise", ok("read_media"), [_file(tmp_path, "paper.pdf")], pages=pages_fail)
    assert code == 2 and row is None and seen == []
    assert "Refused: pdftoppm failed on paper.pdf: Syntax Error. Nothing was logged or sent." in out
    assert not list((media_root / "in").glob("*")) and not list((media_root / "pages").glob("*"))


def test_show_prints_the_page_count_for_a_pdf(conn, tmp_path):
    _, _, row, _ = _route(conn, "summarise", ok("read_media"), [_file(tmp_path, "long.pdf", size=2048)], pages=pages_cut)
    lines = []
    cli.cmd_show(conn=conn, words=[row["task_id"]], out=lines.append)
    assert "  long.pdf (application/pdf, 2 KB, 12 of 30 pages)" in "\n".join(lines)


# ---------- refusals: no log row, no Jev call ----------

def test_an_exe_is_refused_before_jev_and_the_log(conn, tmp_path):
    code, out, row, seen = _route(conn, "what is this", ok("read_media"), [_file(tmp_path, "setup.exe")])
    assert code == 2 and row is None and seen == []
    assert "Refused: setup.exe: not an allowed file type" in out and "Nothing was logged or sent." in out


def test_a_60_mb_file_is_refused(conn, tmp_path):
    big = tmp_path / "big.png"
    with big.open("wb") as f:
        f.truncate(60 * 1024 * 1024)
    code, out, row, seen = _route(conn, "what is this", ok("read_media"), [big])
    assert code == 2 and row is None and seen == [] and "over the 50.0 MB limit" in out


def test_five_files_or_two_videos_are_refused(conn, tmp_path):
    five = [_file(tmp_path, f"f{i}.png") for i in range(5)]
    assert _route(conn, "t", ok("read_media"), five)[0] == 2
    two = [_file(tmp_path, "a.mp4"), _file(tmp_path, "b.mov")]
    code, out, row, seen = _route(conn, "t", ok("read_media"), two)
    assert code == 2 and row is None and seen == [] and "at most 1" in out


def test_at_grok_with_files_is_refused_at_intake(conn, tmp_path):
    code, out, row, seen = _route(conn, "@grok what is this", ok("read_media"), [_file(tmp_path, "a.png")])
    assert code == 2 and row is None and seen == []
    assert "Refused: @grok can't take files" in out


def test_a_task_without_files_runs_exactly_as_before(conn):
    code, out, row, seen = _route(conn, "write a haiku", ok("writing"), [])
    assert code == 0 and row["status"] == "done" and log.files_of(row) == [] and row["files"] is None
    assert seen == ["write a haiku"]


# ---------- accepted files ----------

def test_a_png_is_copied_in_logged_and_described_to_jev_only(conn, tmp_path, media_root):
    src = _file(tmp_path, "logo.png", size=1000)
    code, out, row, seen = _route(conn, "what is in this image", ok("read_media"), [src])
    assert code == 0 and (row["agent"], row["checker"], row["status"]) == ("claude", "chatgpt", "done")
    assert seen == ["what is in this image\n[file: logo.png, image/png, 1000 B]"]
    assert row["task"] == "what is in this image", "the log keeps the typed text, never the Jev copy"
    assert log.files_of(row) == [{"name": "logo.png", "type": "image/png", "size": 1000, "frames": None,
                                  "original": None, "moved_to": None, "pages": None, "total_pages": None}]
    copy = media_root / "in" / row["task_id"] / "logo.png"
    assert copy.read_bytes() == src.read_bytes() and src.exists()


def test_a_video_gets_frames_at_intake_and_the_clip_stays_in_media_in(conn, tmp_path, media_root):
    clip = _file(tmp_path, "clip.mp4", size=5000)
    seen_frames = []

    def frames(copy, dest):
        seen_frames.append((copy, dest))
        return frames_ok(copy, dest)
    code, out, row, seen = _route(conn, "what happens in this clip", ok("read_media"), [clip], frames=frames)
    assert code == 0
    task_id = row["task_id"]
    assert seen_frames == [(media_root / "in" / task_id / "clip.mp4", media_root / "frames" / task_id)]
    assert log.files_of(row) == [{"name": "clip.mp4", "type": "video/mp4", "size": 5000, "frames": 12,
                                  "original": None, "moved_to": None, "pages": None, "total_pages": None}]
    assert len(list((media_root / "frames" / task_id).glob("frame_*.jpg"))) == 12
    assert seen == ["what happens in this clip\n[file: clip.mp4, video/mp4, 5 KB]"]


def test_a_failed_frame_pull_refuses_the_task_before_jev_and_cleans_up(conn, tmp_path, media_root):
    code, out, row, seen = _route(conn, "what happens", ok("read_media"), [_file(tmp_path, "clip.mp4")], frames=frames_fail)
    assert code == 2 and row is None and seen == []
    assert "Refused: ffmpeg failed on clip.mp4: moov atom not found. Nothing was logged or sent." in out
    assert not list((media_root / "in").glob("*")) and not list((media_root / "frames").glob("*"))


def test_a_task_with_files_whose_doer_is_grok_comes_back_logged_like_a_not_routed_skill(conn, tmp_path):
    code, out, row, seen = _route(conn, "what are people on X saying about this chart", ok("x_social_pulse"),
                                  [_file(tmp_path, "chart.png")])
    assert code == 4 and row["status"] == "returned" and row["agent"] is None
    assert row["route_reason"] == routing.NO_FILES_FOR_GROK and row["skill"] == "x_social_pulse"
    assert "came back to you: a task with files can't go to grok" in out
    assert log.files_of(row)[0]["name"] == "chart.png"


def test_a_file_task_that_asks_the_owner_keeps_the_files_rule(conn, tmp_path):
    low = {**JEV_OK, "status": "below_floor", "label": "x_social_pulse", "confidence": 0.5}
    answers = iter(["x_social_pulse"])
    code, out, row, seen = _route(conn, "what is this", low, [_file(tmp_path, "a.png")], ask=lambda _prompt="": next(answers))
    assert code == 4 and row["route_reason"] == routing.NO_FILES_FOR_GROK


# ---------- names (the owner, 2026-10-14): an odd name goes on under a safe copy name; the log keeps the original ----------

ODD = "Welcome Packet \u2013 Sample Name (1).pdf"  # the name intake refused on 2026-10-14
SAFE = "Welcome_Packet_Sample_Name_1_.pdf"


def test_an_odd_name_goes_on_as_a_safe_copy_name_and_the_log_keeps_the_original(conn, tmp_path, media_root):
    src = _file(tmp_path, ODD)
    code, out, row, seen = _route(conn, "summarise this", ok("read_media"), [src])
    assert code == 0 and row["status"] == "done"
    tid = row["task_id"]
    assert log.files_of(row) == [{"name": SAFE, "type": "application/pdf", "size": 1000, "frames": None,
                                  "original": ODD, "moved_to": None, "pages": 3, "total_pages": 3}]
    copy = media_root / "in" / tid / SAFE
    assert copy.read_bytes() == src.read_bytes() and src.exists() and not (media_root / "in" / tid / ODD).exists()
    assert seen == [f"summarise this\n[file: {SAFE}, application/pdf, 1000 B]"], "Jev sees the safe name only"


def test_the_workspace_copy_and_the_page_images_use_the_safe_name(conn, tmp_path, media_root):
    _, _, row, _ = _route(conn, "summarise this", ok("read_media"), [_file(tmp_path, ODD)])
    tid, records = row["task_id"], log.files_of(row)
    for_claude = media.layout(tid, records, agent="claude")
    assert for_claude == [(media_root / "in" / tid / SAFE, SAFE)]
    for_chatgpt = media.layout(tid, records, agent="chatgpt")
    assert [rel for _, rel in for_chatgpt] == [f"pages/Welcome_Packet_Sample_Name_1_-page-{i}.png" for i in (1, 2, 3)]
    with media.workspace_copy("t", for_claude, tmp_path / "ws") as folder:
        assert sorted(p.name for p in folder.iterdir()) == [SAFE]
    assert media.page_notes(records, "chatgpt") == [f"{SAFE}: pages 1 to 3 of 3."]


def test_show_prints_the_safe_name_and_the_original(conn, tmp_path):
    _, _, row, _ = _route(conn, "summarise this", ok("read_media"), [_file(tmp_path, ODD, size=2048)])
    lines = []
    cli.cmd_show(conn=conn, words=[row["task_id"]], out=lines.append)
    assert f"Files:\n  {SAFE} (application/pdf, 2 KB, 3 of 3 pages) (from {ODD})" in "\n".join(lines)


@pytest.mark.parametrize("name, words", [(".hidden.png", "a hidden file"), ("back\\slash.png", "path separator"),
                                         ("bad\x01.png", "control character")])
def test_a_hidden_name_a_separator_or_a_control_character_is_refused_before_jev(conn, tmp_path, name, words):
    code, out, row, seen = _route(conn, "what is this", ok("read_media"), [_file(tmp_path, name)])
    assert code == 2 and row is None and seen == []
    assert f"Refused: {safety.for_terminal(name)}: " in out and words in out and "Nothing was logged or sent." in out
    assert "\x01" not in out, "a control character never reaches the terminal"


def test_a_newline_in_a_name_cannot_fake_a_second_line_of_output(conn, tmp_path):
    name = "bad\nRefused: nothing\nSent.png"
    code, out, row, seen = _route(conn, "what is this", ok("read_media"), [_file(tmp_path, name)])
    assert code == 2 and row is None and seen == []
    assert name not in out and [line for line in out.split("\n") if line.startswith("Refused:")] == [
        "Refused: bad\ufffdRefused: nothing\ufffdSent.png: the file name has a control character."]


# ---------- sr show ----------

def test_show_prints_the_files_with_type_size_and_frames(conn, tmp_path):
    files = [_file(tmp_path, "shot.png", size=2048), _file(tmp_path, "clip.mov", size=4096)]
    _, _, row, _ = _route(conn, "describe these", ok("read_media"), files)
    lines = []
    assert cli.cmd_show(conn=conn, words=[row["task_id"]], out=lines.append) == 0
    out = "\n".join(lines)
    assert "Files:\n  shot.png (image/png, 2 KB)\n  clip.mov (video/quicktime, 4 KB, 12 frames)" in out


def test_show_prints_no_files_line_for_a_task_without_files(conn):
    _, _, row, _ = _route(conn, "write a haiku", ok("writing"), [])
    lines = []
    cli.cmd_show(conn=conn, words=[row["task_id"]], out=lines.append)
    assert "Files:" not in "\n".join(lines)


# ---------- the command line ----------

def test_route_takes_file_up_to_four_times():
    parser = cli._parser(ROSTER)
    args = parser.parse_args(["route", "--file", "a.png", "--file", "b.pdf", "what", "are", "these"])
    assert args.file == ["a.png", "b.pdf"] and args.task == ["what", "are", "these"]
    assert parser.parse_args(["route", "hi"]).file == []
