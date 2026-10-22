"""router/media.py: the whitelist and cap, safe names, the folders, the line per file Jev sees.
No test touches the real media/ folder."""
import pytest

from router import media


@pytest.fixture(autouse=True)
def media_root(tmp_path, monkeypatch):
    root = tmp_path / "media"
    monkeypatch.setattr(media, "MEDIA_ROOT", root)
    return root


def _file(tmp_path, name, size=1000):
    p = tmp_path / name
    p.write_bytes(b"x" * size)
    return p


def test_the_whitelist_and_caps_are_the_rules():
    assert media.EXTENSIONS == ("png", "jpg", "jpeg", "webp", "gif", "pdf", "mp4", "mov")
    assert media.MAX_FILES == 4 and media.MAX_BYTES == 50 * 1024 * 1024 and media.MAX_VIDEOS == 1


@pytest.mark.parametrize("name, k", [("a.png", "image"), ("b.JPG", "image"), ("c.jpeg", "image"), ("d.webp", "image"),
                                     ("e.gif", "image"), ("f.pdf", "pdf"), ("g.mp4", "video"), ("h.MOV", "video"),
                                     ("i.exe", None), ("j.mp3", None), ("k", None)])
def test_kind_follows_the_extension_in_any_case(name, k):
    assert media.kind(name) == k


def test_accepted_files_give_no_problem(tmp_path):
    files = [_file(tmp_path, "logo.png"), _file(tmp_path, "paper.pdf"), _file(tmp_path, "clip.mp4"),
             _file(tmp_path, "shot 2.webp")]
    assert media.check_files(files) == []


def test_an_exe_is_refused_by_type(tmp_path):
    problems = media.check_files([_file(tmp_path, "setup.exe")])
    assert len(problems) == 1 and "setup.exe" in problems[0] and "not an allowed file type" in problems[0]


def test_a_file_over_the_cap_is_refused_by_size(tmp_path):
    big = tmp_path / "big.png"
    with big.open("wb") as f:
        f.truncate(media.MAX_BYTES + 1)
    problems = media.check_files([big])
    assert len(problems) == 1 and "over the 50.0 MB limit" in problems[0]


def test_a_file_at_the_cap_is_accepted(tmp_path):
    ok = tmp_path / "ok.png"
    with ok.open("wb") as f:
        f.truncate(media.MAX_BYTES)
    assert media.check_files([ok]) == []


def test_five_files_are_refused_by_count(tmp_path):
    files = [_file(tmp_path, f"f{i}.png") for i in range(5)]
    assert any("at most 4" in p for p in media.check_files(files))


def test_two_videos_are_refused(tmp_path):
    files = [_file(tmp_path, "a.mp4"), _file(tmp_path, "b.mov")]
    problems = media.check_files(files)
    assert len(problems) == 1 and "at most 1" in problems[0]


# ---------- names (the owner, 2026-10-14): the copy's name is made safe; only four kinds of name are refused ----------

ODD = "Welcome Packet \u2013 Sample Name (1).pdf"  # the name intake refused on 2026-10-14: an en dash, parentheses
SAFE = "Welcome_Packet_Sample_Name_1_.pdf"


@pytest.mark.parametrize("name, expected", [
    (ODD, SAFE),
    ("logo.png", "logo.png"),
    ("shot 2.webp", "shot_2.webp"),
    ("r\u00e9sum\u00e9.pdf", "r_sum_.pdf"),
    ("a  \u2013  b.png", "a_b.png"),           # a run of odd characters is one underscore
    ("a__b.png", "a_b.png"),                    # and so is a run of underscores
    ("semi;colon.png", "semi_colon.png"),
    ("-lead.png", "-lead.png"),                 # a dash is a plain character, first or not
    ("Report.Final.PDF", "Report.Final.PDF"),   # dots and case are kept, so the extension is
    ("\u65e5\u672c\u8a9e.jpg", "_.jpg"),
    ("x" * 120 + ".png", "x" * 120 + ".png"),   # a stem of 120 is kept whole
    ("x" * 245 + ".pdf", "x" * 120 + ".pdf"),   # a longer stem is cut at 120, the extension kept
    ("a b.c " + "y" * 200 + ".jpeg", "a_b.c_" + "y" * 114 + ".jpeg"),
])
def test_the_safe_name_keeps_plain_characters_and_the_extension(name, expected):
    assert media.safe_name(name) == expected


def test_a_name_at_the_file_system_limit_still_fits_as_a_page_image_name(tmp_path, media_root):
    """A 255-byte PDF name (the APFS limit) is accepted; without the stem cap its ChatGPT page-image
    name `pages/<stem>-page-N.png` would be too long for the file system at delivery."""
    name = "x" * 251 + ".pdf"
    copy = media.copy_in("sr-1", [_file(tmp_path, name)])[0]
    (media.pages_dir("sr-1") / "page-1.png").write_bytes(b"png")
    records = [media.record(copy, pages=1, total_pages=1)]
    items = media.layout("sr-1", records, agent="chatgpt")
    assert [rel for _, rel in items] == ["pages/" + "x" * 120 + "-page-1.png"]
    with media.workspace_copy("t", items + media.layout("sr-1", records, agent="claude"), tmp_path / "ws") as folder:
        assert (folder / "pages" / ("x" * 120 + "-page-1.png")).is_file() and (folder / ("x" * 120 + ".pdf")).is_file()


def test_two_long_names_that_are_cut_to_the_same_stem_are_refused(tmp_path):
    a, b = _file(tmp_path, "x" * 130 + "a.pdf"), _file(tmp_path, "x" * 130 + "b.pdf")
    assert media.check_files([a, b]) == [f"{b.name} and {a.name} would both be copied as {'x' * 120}.pdf."]


@pytest.mark.parametrize("name, words", [
    ("", "the file name is empty"),
    (".hidden.png", "a hidden file"),
    (".", "a hidden file"),
    ("..", "a hidden file"),
    ("back\\slash.png", "path separator"),
    ("fwd/slash.png", "path separator"),
    ("bad\x01.png", "control character"),
    ("del\x7f.png", "control character"),
    ("c1\x85.png", "control character"),
])
def test_only_an_empty_hidden_separator_or_control_name_is_refused(name, words):
    assert words in media.name_problem(name)


@pytest.mark.parametrize("name", [ODD, "-lead.png", "semi;colon.png", "x" * 121 + ".png", "r\u00e9sum\u00e9.pdf", "shot 2.webp"])
def test_an_odd_but_harmless_name_is_accepted(tmp_path, name):
    assert media.name_problem(name) is None
    assert media.check_files([_file(tmp_path, name)]) == []


@pytest.mark.parametrize("name, words", [(".hidden.png", "a hidden file"), ("bad\x01.png", "control character"),
                                         ("back\\slash.png", "path separator")])
def test_an_unsafe_name_is_refused(tmp_path, name, words):
    problems = media.check_files([_file(tmp_path, name)])
    assert len(problems) == 1 and problems[0].startswith(name) and words in problems[0]


def test_a_hidden_name_is_refused_before_its_type_is_looked_at(tmp_path):
    assert media.check_files([_file(tmp_path, ".pdf")]) == [".pdf: a hidden file (its name starts with a dot)."]


def test_a_missing_or_empty_file_is_refused(tmp_path):
    assert "no such file" in media.check_files([tmp_path / "gone.png"])[0]
    assert "empty" in media.check_files([_file(tmp_path, "empty.png", size=0)])[0]


def test_two_files_with_the_same_name_are_refused(tmp_path):
    a = _file(tmp_path, "same.png")
    (tmp_path / "other").mkdir()
    b = _file(tmp_path / "other", "same.png")
    assert any("same name" in p for p in media.check_files([a, b]))


def test_two_names_that_become_the_same_safe_name_are_refused(tmp_path):
    problems = media.check_files([_file(tmp_path, "shot 2.webp"), _file(tmp_path, "shot_2.webp")])
    assert problems == ["shot_2.webp and shot 2.webp would both be copied as shot_2.webp."]


def test_the_jev_line_names_the_file_its_type_and_its_size_and_never_its_contents(tmp_path):
    files = [media.record(_file(tmp_path, "logo.png", size=1_258_291)), media.record(_file(tmp_path, "paper.pdf", size=2048))]
    assert media.describe(files) == "[file: logo.png, image/png, 1.2 MB]\n[file: paper.pdf, application/pdf, 2 KB]"
    assert media.jev_text("what is this", files) == "what is this\n[file: logo.png, image/png, 1.2 MB]\n[file: paper.pdf, application/pdf, 2 KB]"
    assert media.jev_text("what is this", []) == "what is this"


def test_a_record_holds_name_type_size_and_frames(tmp_path):
    assert media.record(_file(tmp_path, "clip.mov", size=10), frames=12) == {
        "name": "clip.mov", "type": "video/quicktime", "size": 10, "frames": 12, "original": None, "moved_to": None,
        "pages": None, "total_pages": None}
    assert media.record(_file(tmp_path, "a.jpeg", size=3))["frames"] is None


def test_folders_are_created_on_demand_under_media_root(media_root):
    assert not media_root.exists()
    assert media.in_dir("sr-1") == media_root / "in" / "sr-1" and (media_root / "in" / "sr-1").is_dir()
    assert media.frames_dir("sr-1") == media_root / "frames" / "sr-1"
    assert media.out_dir("sr-1") == media_root / "out" / "sr-1"


def test_copy_in_copies_the_files_and_leaves_the_originals(tmp_path, media_root):
    src = _file(tmp_path, "logo.png", size=5)
    copies = media.copy_in("sr-1", [src])
    assert copies == [media_root / "in" / "sr-1" / "logo.png"]
    assert copies[0].read_bytes() == b"xxxxx" and src.read_bytes() == b"xxxxx"


def test_copy_in_names_the_copy_safely_and_leaves_the_original_as_it_was(tmp_path, media_root):
    src = _file(tmp_path, ODD, size=5)
    copies = media.copy_in("sr-1", [src])
    assert copies == [media_root / "in" / "sr-1" / SAFE]
    assert copies[0].read_bytes() == b"xxxxx" and src.read_bytes() == b"xxxxx" and src.name == ODD
    assert media.record(copies[0])["name"] == SAFE


def test_media_is_ignored_by_git():
    from router import safety
    assert "\nmedia/\n" in (safety.REPO_ROOT / ".gitignore").read_text()


# ---------- frames ----------

class Ffmpeg:
    """Stands in for subprocess.run: writes `count` jpgs where ffmpeg would."""

    def __init__(self, count=12, returncode=0, stderr="", raises=None):
        self.count, self.returncode, self.stderr, self.raises = count, returncode, stderr, raises
        self.calls = []

    def __call__(self, argv, **kwargs):
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv) and not kwargs.get("shell")
        self.calls.append((argv, kwargs))
        if self.raises:
            raise self.raises
        pattern = argv[-1]
        for i in range(1, self.count + 1):
            (pattern.parent if hasattr(pattern, "parent") else __import__("pathlib").Path(pattern).parent).joinpath(
                f"frame_{i:02d}.jpg").write_bytes(b"jpg")
        import subprocess
        return subprocess.CompletedProcess(argv, self.returncode, "", self.stderr)


def test_frames_are_pulled_one_every_5_seconds_720_wide_at_most_12(tmp_path, media_root):
    clip = _file(tmp_path, "clip.mp4")
    run = Ffmpeg(count=4)
    frames = media.extract_frames(clip, media.frames_dir("sr-1"), run=run)
    assert [f.name for f in frames] == ["frame_01.jpg", "frame_02.jpg", "frame_03.jpg", "frame_04.jpg"]
    assert all(f.parent == media_root / "frames" / "sr-1" for f in frames)
    argv, kwargs = run.calls[0]
    assert argv[:6] == ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i"] and argv[6] == str(clip)
    assert ("-vf", "fps=1/5,scale=720:-2") in list(zip(argv, argv[1:]))
    assert ("-frames:v", "12") in list(zip(argv, argv[1:]))
    assert argv[-1].endswith("frame_%02d.jpg") and kwargs["timeout"] == 120 and kwargs["capture_output"]


@pytest.mark.parametrize("run, words", [
    (Ffmpeg(returncode=1, stderr="moov atom not found"), "ffmpeg failed on clip.mp4: moov atom not found"),
    (Ffmpeg(count=0), "made no frames"),
    (Ffmpeg(raises=OSError("no ffmpeg")), "could not start ffmpeg"),
    (Ffmpeg(raises=__import__("subprocess").TimeoutExpired(["ffmpeg"], 120)), "timed out after 120 s"),
], ids=["exit 1", "no frames", "not installed", "timeout"])
def test_a_failed_frame_pull_raises_with_the_reason(tmp_path, media_root, run, words):
    clip = _file(tmp_path, "clip.mp4")
    with pytest.raises(media.MediaError) as err:
        media.extract_frames(clip, media.frames_dir("sr-1"), run=run)
    assert words in str(err.value)


def test_remove_task_folders_undoes_an_intake(tmp_path, media_root):
    media.copy_in("sr-9", [_file(tmp_path, "a.png")])
    media.frames_dir("sr-9")
    media.remove_task_folders("sr-9")
    assert not (media_root / "in" / "sr-9").exists() and not (media_root / "frames" / "sr-9").exists()



# ---------- pages from a PDF (rules v2.11) ----------

class Poppler:
    """Stands in for subprocess.run for pdfinfo and pdftoppm: writes `count` pngs where pdftoppm would."""

    def __init__(self, total=3, count=3, returncode=0, stderr="", raises=None, info="Pages:          3\n"):
        self.total, self.count, self.returncode, self.stderr, self.raises, self.info = total, count, returncode, stderr, raises, info
        self.calls = []

    def __call__(self, argv, **kwargs):
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv) and not kwargs.get("shell")
        self.calls.append((argv, kwargs))
        if self.raises:
            raise self.raises
        import subprocess
        if argv[0] == "pdfinfo":
            return subprocess.CompletedProcess(argv, 0, self.info, "")
        prefix = __import__("pathlib").Path(argv[-1])
        width = 2 if self.total >= 10 else 1
        for i in range(1, self.count + 1):
            prefix.parent.joinpath(f"page-{i:0{width}d}.png").write_bytes(b"png")
        return subprocess.CompletedProcess(argv, self.returncode, "", self.stderr)


def test_pages_are_rendered_at_110_dpi_first_12_only_and_counted(tmp_path, media_root):
    pdf = _file(tmp_path, "paper.pdf")
    run = Poppler(total=30, count=12, info="Title: x\nPages:          30\nEncrypted: no\n")
    pages, total = media.extract_pages(pdf, media.pages_dir("sr-1"), run=run)
    assert total == 30 and [p.name for p in pages] == [f"page-{i:02d}.png" for i in range(1, 13)]
    info_argv, _ = run.calls[0]
    assert info_argv == ["pdfinfo", str(pdf)]
    argv, kwargs = run.calls[1]
    assert argv == ["pdftoppm", "-r", "110", "-png", "-f", "1", "-l", "12", str(pdf), str(media_root / "pages" / "sr-1" / "page")]
    assert kwargs["timeout"] == 120 and kwargs["capture_output"]


def test_pages_sort_by_number_not_by_name(tmp_path, media_root):
    pdf = _file(tmp_path, "paper.pdf")
    pages, total = media.extract_pages(pdf, media.pages_dir("sr-2"), run=Poppler(total=11, count=11, info="Pages: 11\n"))
    assert total == 11 and [media._page_number(p) for p in pages] == list(range(1, 12))


@pytest.mark.parametrize("run, words", [
    (Poppler(returncode=1, stderr="Syntax Error: broken"), "pdftoppm failed on paper.pdf: Syntax Error: broken"),
    (Poppler(count=0), "made no pages"),
    (Poppler(info="no page line\n"), "gave no page count"),
    (Poppler(raises=OSError("no poppler")), "could not start pdfinfo"),
    (Poppler(raises=__import__("subprocess").TimeoutExpired(["pdfinfo"], 120)), "timed out"),
], ids=["exit 1", "no pages", "no count", "not installed", "timeout"])
def test_a_failed_page_render_raises_with_the_reason(tmp_path, media_root, run, words):
    pdf = _file(tmp_path, "paper.pdf")
    with pytest.raises(media.MediaError) as err:
        media.extract_pages(pdf, media.pages_dir("sr-1"), run=run)
    assert words in str(err.value)


def test_no_test_can_run_pdftoppm_or_ffmpeg_for_real(tmp_path, media_root):
    # conftest patches subprocess.Popen; the default `run` of both helpers goes through it.
    with pytest.raises(RuntimeError, match="real subprocess"):
        media.extract_pages(_file(tmp_path, "p.pdf"), media.pages_dir("sr-g"))
    with pytest.raises(RuntimeError, match="real subprocess"):
        media.extract_frames(_file(tmp_path, "c.mp4"), media.frames_dir("sr-g"))


def test_remove_task_folders_removes_pages_too(tmp_path, media_root):
    media.pages_dir("sr-9")
    media.remove_task_folders("sr-9")
    assert not (media_root / "pages" / "sr-9").exists()
