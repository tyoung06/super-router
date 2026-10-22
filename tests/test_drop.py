"""The drop folder: files in ~/Desktop/Router Drop/ are offered on every `sr route` with a terminal,
go through the same intake as --file, and move to sent/<task-id>/. HEIC and HEIF become jpg at intake.
Without a terminal the folder is ignored. No test runs sips or touches the real folder."""
import json
import subprocess
from pathlib import Path

import pytest

from router import __main__ as cli
from router import drop, log, media, safety
from tests.helpers import JEV_OK, shipped_roster

CONFIG = {"GROK_WEBHOOK_URL": "https://example.invalid/hook", "GROK_WEBHOOK_KEY": "FAKE-KEY-123"}
ROSTER = shipped_roster()


@pytest.fixture(autouse=True)
def media_root(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "MEDIA_ROOT", tmp_path / "media")


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def folder(tmp_path):
    f = tmp_path / "Router Drop"
    f.mkdir()
    return f


def _put(folder, name, size=1000):
    p = folder / name
    p.write_bytes(b"x" * size)
    return p


def fake_pages(pdf, dest):
    paths = [Path(dest) / f"page-{i}.png" for i in range(1, 3)]
    for p in paths:
        p.write_bytes(b"png")
    return paths, 2


def fake_convert(path, dest_dir):
    target = Path(dest_dir) / f"{Path(path).stem}.jpg"
    target.write_bytes(b"jpg-from-" + Path(path).name.encode())
    return target


def _route(conn, task, *, folder=None, answer="y", files=(), convert=fake_convert, terminal=True, label_skill="read_media"):
    lines, prompts, seen = [], [], []

    def label(text, **kw):
        seen.append(text)
        return {**JEV_OK, "label": label_skill}

    def ask_attach(prompt):
        prompts.append(prompt)
        return answer
    code = cli.cmd_route(task, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=label,
                         post=lambda *a, **k: None, worker=lambda p, **k: "the answer", chatgpt=lambda p, **k: "PASS",
                         codex_login=lambda: True, files=list(files), frames=lambda clip, dest: [], pages=fake_pages,
                         drop_folder=folder, ask_attach=ask_attach if terminal else None, convert=convert, out=lines.append)
    rows = log.recent_tasks(conn)
    return code, "\n".join(lines), (rows[0] if rows else None), prompts, seen


# ---------- the settings and the folder ----------

def test_the_folder_comes_from_settings_with_tilde_expanded(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"drop_folder": "~/Desktop/Router Drop"}))
    assert drop.folder(settings) == Path.home() / "Desktop" / "Router Drop"
    settings.write_text(json.dumps({"note": "no key"}))
    assert drop.folder(settings) is None
    assert drop.folder(tmp_path / "missing.json") is None
    settings.write_text("not json")
    assert drop.folder(settings) is None


def test_the_shipped_settings_name_the_desktop_drop_folder():
    assert drop.folder() == Path.home() / "Desktop" / "Router Drop"


def test_prepare_creates_the_folder_and_sent(tmp_path):
    f = tmp_path / "new" / "Router Drop"
    assert drop.prepare(f) == f and (f / "sent").is_dir()
    drop.prepare(f)  # a second time is fine


def test_waiting_lists_plain_files_only_by_name_and_skips_hidden_and_sent(folder):
    _put(folder, "b.png"); _put(folder, "A.pdf"); _put(folder, ".DS_Store")
    (folder / "sent" / "sr-old").mkdir(parents=True)
    _put(folder / "sent" / "sr-old", "old.png")
    (folder / "sub").mkdir()
    assert [p.name for p in drop.waiting(folder)] == ["A.pdf", "b.png"]
    assert drop.waiting(folder / "nope") == []


# ---------- the offer on sr route ----------

def test_with_a_terminal_the_files_are_named_and_y_attaches_them_through_intake(conn, folder, tmp_path):
    _put(folder, "shot.png", 2048); _put(folder, "paper.pdf", 4096)
    code, out, row, prompts, seen = _route(conn, "what are these", folder=folder)
    assert code == 0 and row["status"] == "done"
    assert "The drop folder has 2 file(s):" in out and "  paper.pdf (4 KB)" in out and "  shot.png (2 KB)" in out
    assert prompts == ["Attach these 2 files? [y/N] "]
    files = log.files_of(row)
    assert [f["name"] for f in files] == ["paper.pdf", "shot.png"]
    sent = folder / "sent" / row["task_id"]
    assert all(f["moved_to"] == str(sent) for f in files)
    assert sorted(p.name for p in sent.iterdir()) == ["paper.pdf", "shot.png"] and drop.waiting(folder) == []
    assert (media.MEDIA_ROOT / "in" / row["task_id"] / "shot.png").stat().st_size == 2048
    assert seen[0].endswith("[file: paper.pdf, application/pdf, 4 KB]\n[file: shot.png, image/png, 2 KB]")
    assert f"Moved 2 file(s) from the drop folder to {sent}/." in out


@pytest.mark.parametrize("answer", ["n", "", "N", "no", "maybe"])
def test_anything_but_y_runs_with_no_files_and_leaves_the_folder(conn, folder, answer):
    _put(folder, "shot.png")
    code, out, row, prompts, _ = _route(conn, "write a haiku", folder=folder, answer=answer, label_skill="writing")
    assert code == 0 and log.files_of(row) == [] and prompts == ["Attach these 1 files? [y/N] "]
    assert "Running with no files from the drop folder." in out
    assert [p.name for p in drop.waiting(folder)] == ["shot.png"]


def test_yes_spelled_out_attaches_too(conn, folder):
    _put(folder, "shot.png")
    code, _, row, _, _ = _route(conn, "what is this", folder=folder, answer="YES")
    assert code == 0 and log.files_of(row)[0]["name"] == "shot.png"


def test_without_a_terminal_the_folder_is_ignored(conn, folder):
    _put(folder, "shot.png")
    code, out, row, prompts, _ = _route(conn, "write a haiku", folder=folder, terminal=False, label_skill="writing")
    assert code == 0 and log.files_of(row) == [] and prompts == [] and "drop folder" not in out
    assert [p.name for p in drop.waiting(folder)] == ["shot.png"]


def test_an_empty_folder_asks_nothing_and_is_created_if_missing(conn, tmp_path):
    f = tmp_path / "Router Drop"
    code, out, row, prompts, _ = _route(conn, "write a haiku", folder=f, label_skill="writing")
    assert code == 0 and prompts == [] and (f / "sent").is_dir() and "drop folder" not in out


def test_file_and_the_drop_folder_count_together_against_the_cap(conn, folder, tmp_path):
    extra = [_put(tmp_path, f"f{i}.png") for i in range(2)]
    for i in range(3):
        _put(folder, f"d{i}.png")
    code, out, row, prompts, seen = _route(conn, "what", folder=folder, files=extra)
    assert code == 2 and row is None and seen == [] and "5 files; at most 4" in out
    assert "The drop folder is as it was." in out and len(drop.waiting(folder)) == 3


def test_two_videos_across_both_sources_are_refused_and_nothing_moves(conn, folder, tmp_path):
    clip = _put(tmp_path, "a.mp4")
    _put(folder, "b.mov")
    code, out, row, _, _ = _route(conn, "what", folder=folder, files=[clip])
    assert code == 2 and row is None and "at most 1" in out and [p.name for p in drop.waiting(folder)] == ["b.mov"]


def test_file_still_works_with_the_folder_and_its_originals_never_move(conn, folder, tmp_path):
    mine = _put(tmp_path, "mine.png")
    _put(folder, "dropped.png")
    code, _, row, _, _ = _route(conn, "what", folder=folder, files=[mine])
    assert code == 0
    files = {f["name"]: f for f in log.files_of(row)}
    assert files["mine.png"]["moved_to"] is None and mine.exists()
    assert files["dropped.png"]["moved_to"] == str(folder / "sent" / row["task_id"])


# ---------- HEIC ----------

def test_a_heic_in_the_drop_folder_is_converted_to_jpg_and_the_original_moves_untouched(conn, folder):
    heic = _put(folder, "IMG_0001.HEIC", 3000)
    original_bytes = heic.read_bytes()
    code, out, row, _, seen = _route(conn, "what is in this photo", folder=folder)
    assert code == 0
    files = log.files_of(row)
    assert files[0]["name"] == "IMG_0001.jpg" and files[0]["type"] == "image/jpeg" and files[0]["original"] == "IMG_0001.HEIC"
    assert (media.MEDIA_ROOT / "in" / row["task_id"] / "IMG_0001.jpg").read_bytes() == b"jpg-from-IMG_0001.HEIC"
    moved = folder / "sent" / row["task_id"] / "IMG_0001.HEIC"
    assert moved.read_bytes() == original_bytes and drop.waiting(folder) == []
    assert "[file: IMG_0001.jpg, image/jpeg," in seen[0]


def test_a_heic_by_file_is_converted_too_and_the_original_stays(conn, tmp_path):
    heic = _put(tmp_path, "photo.heif")
    code, _, row, _, _ = _route(conn, "what", files=[heic])
    assert code == 0 and log.files_of(row)[0]["name"] == "photo.jpg" and heic.exists()


def test_a_failed_conversion_refuses_the_task_and_leaves_the_folder(conn, folder):
    _put(folder, "bad.heic")

    def broken(path, dest_dir):
        raise drop.DropError("sips could not convert bad.heic: corrupt file")
    code, out, row, _, seen = _route(conn, "what", folder=folder, convert=broken)
    assert code == 2 and row is None and seen == [] and "Refused: sips could not convert bad.heic" in out
    assert [p.name for p in drop.waiting(folder)] == ["bad.heic"]


class Sips:
    def __init__(self, returncode=0, stderr="", raises=None, writes=True):
        self.returncode, self.stderr, self.raises, self.writes, self.calls = returncode, stderr, raises, writes, []

    def __call__(self, argv, **kwargs):
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv) and not kwargs.get("shell")
        self.calls.append((argv, kwargs))
        if self.raises:
            raise self.raises
        if self.writes:
            Path(argv[-1]).write_bytes(b"jpg")
        return subprocess.CompletedProcess(argv, self.returncode, "", self.stderr)


def test_convert_heic_calls_sips_with_the_jpeg_format_and_an_out_path(tmp_path):
    heic = _put(tmp_path, "IMG_1.heic")
    run = Sips()
    target = drop.convert_heic(heic, tmp_path / "tmp", run=run)
    assert target == tmp_path / "tmp" / "IMG_1.jpg" and target.read_bytes() == b"jpg"
    argv, kwargs = run.calls[0]
    assert argv == ["sips", "-s", "format", "jpeg", str(heic), "--out", str(target)] and kwargs["timeout"] == 60


def test_convert_heic_gives_sips_an_absolute_path_so_a_leading_dash_is_never_an_option(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _put(tmp_path, "-lead.HEIC")
    run = Sips()
    drop.convert_heic(Path("-lead.HEIC"), tmp_path / "tmp", run=run)
    given = run.calls[0][0][4]
    assert given == str(tmp_path / "-lead.HEIC") and given.startswith("/")


@pytest.mark.parametrize("run, words", [
    (Sips(returncode=1, stderr="Error: corrupt"), "sips could not convert IMG_1.heic: Error: corrupt"),
    (Sips(writes=False), "sips could not convert IMG_1.heic"),
    (Sips(raises=OSError("no sips")), "could not start sips"),
    (Sips(raises=subprocess.TimeoutExpired(["sips"], 60)), "timed out"),
], ids=["exit 1", "no output", "no sips", "timeout"])
def test_a_failed_sips_raises_with_the_reason(tmp_path, run, words):
    heic = _put(tmp_path, "IMG_1.heic")
    with pytest.raises(drop.DropError, match=words):
        drop.convert_heic(heic, tmp_path / "tmp", run=run)


def test_needs_conversion_is_case_insensitive():
    assert drop.needs_conversion("a.HEIC") and drop.needs_conversion("b.heif") and not drop.needs_conversion("c.jpg")


# ---------- odd names (the owner, 2026-10-14): sent/ keeps the original name; the copy and the Jev line use the safe one ----------

ODD = "Welcome Packet \u2013 Sample Name (1).pdf"
SAFE = "Welcome_Packet_Sample_Name_1_.pdf"


def test_a_drop_file_with_an_odd_name_moves_to_sent_under_its_own_name_and_goes_on_under_the_safe_one(conn, folder):
    src = _put(folder, ODD, 4096)
    original_bytes = src.read_bytes()
    code, out, row, prompts, seen = _route(conn, "summarise this", folder=folder)
    assert code == 0 and f"  {ODD} (4 KB)" in out and prompts == ["Attach these 1 files? [y/N] "]
    sent = folder / "sent" / row["task_id"]
    assert log.files_of(row) == [{"name": SAFE, "type": "application/pdf", "size": 4096, "frames": None,
                                  "original": ODD, "moved_to": str(sent), "pages": 2, "total_pages": 2}]
    assert (sent / ODD).read_bytes() == original_bytes and sorted(p.name for p in sent.iterdir()) == [ODD]
    assert drop.waiting(folder) == [] and (media.MEDIA_ROOT / "in" / row["task_id"] / SAFE).stat().st_size == 4096
    assert seen[0].endswith(f"[file: {SAFE}, application/pdf, 4 KB]")
    lines = []
    cli.cmd_show(conn=conn, words=[row["task_id"]], out=lines.append)
    assert f"  {SAFE} (application/pdf, 4 KB, 2 of 2 pages) (from {ODD})" in "\n".join(lines)


BIDI = "a\u202eb.png"  # a right-to-left override: accepted (not a control character), marked wherever it is printed


def test_a_direction_override_in_a_name_is_marked_in_the_listing_and_in_show_and_kept_raw_in_the_log(conn, folder):
    _put(folder, BIDI, 4096)
    code, out, row, _, seen = _route(conn, "what is this", folder=folder)
    assert code == 0 and f"  {safety.for_terminal(BIDI)} (4 KB)" in out and "\u202e" not in out
    f = log.files_of(row)[0]
    assert (f["name"], f["original"]) == ("a_b.png", BIDI) and "[file: a_b.png, image/png, 4 KB]" in seen[0]
    lines = []
    cli.cmd_show(conn=conn, words=[row["task_id"]], out=lines.append)
    shown = "\n".join(lines)
    assert "  a_b.png (image/png, 4 KB) (from a\ufffdb.png)" in shown and "\u202e" not in shown


def test_a_newline_in_a_drop_name_is_listed_on_one_line_and_refused_on_one_line(conn, folder):
    _put(folder, "a\nb.png")
    code, out, row, prompts, seen = _route(conn, "what is this", folder=folder)
    assert code == 2 and row is None and seen == [] and prompts == ["Attach these 1 files? [y/N] "]
    assert "  a\ufffdb.png (1000 B)" in out and "Refused: a\ufffdb.png: the file name has a control character." in out
    assert "a\nb.png" not in out and [p.name for p in drop.waiting(folder)] == ["a\nb.png"]


def test_a_failed_conversion_prints_the_name_marked(conn, folder):
    _put(folder, "a\u202eb.heic")

    def broken(path, dest_dir):
        raise drop.DropError(f"sips could not convert {path.name}: corrupt file")
    code, out, row, _, seen = _route(conn, "what", folder=folder, convert=broken)
    assert code == 2 and row is None and seen == []
    assert "Refused: sips could not convert a\ufffdb.heic: corrupt file. Nothing was logged or sent." in out and "\u202e" not in out


def test_a_heic_with_an_odd_name_is_converted_and_its_copy_made_safe(conn, folder):
    _put(folder, "My Photo (1).HEIC", 3000)
    code, _, row, _, seen = _route(conn, "what is in this photo", folder=folder)
    assert code == 0
    f = log.files_of(row)[0]
    assert (f["name"], f["type"], f["original"]) == ("My_Photo_1_.jpg", "image/jpeg", "My Photo (1).HEIC")
    assert (media.MEDIA_ROOT / "in" / row["task_id"] / "My_Photo_1_.jpg").read_bytes() == b"jpg-from-My Photo (1).HEIC"
    assert (folder / "sent" / row["task_id"] / "My Photo (1).HEIC").stat().st_size == 3000
    assert "[file: My_Photo_1_.jpg, image/jpeg," in seen[0]


# ---------- sr show ----------

def test_show_prints_where_the_drop_files_went_and_the_heic_origin(conn, folder):
    _put(folder, "IMG_7.heic"); _put(folder, "shot.png")
    _, _, row, _, _ = _route(conn, "what are these", folder=folder)
    lines = []
    cli.cmd_show(conn=conn, words=[row["task_id"]], out=lines.append)
    out = "\n".join(lines)
    sent = folder / "sent" / row["task_id"]
    assert "Files:\n  IMG_7.jpg (image/jpeg, 19 B) (from IMG_7.heic)\n  shot.png (image/png, 1000 B)\n" in out  # the fake jpg is 19 bytes
    assert f"  moved from the drop folder to {sent}/" in out
