"""Build brief 24, E (decision 17): two PDFs on one task each get their own page images. Each PDF's pages are rendered
into `media/pages/<task_id>/<stem>/` (its whole name when two PDFs share a stem), ChatGPT gets each PDF's own pages in
order, a task from before (one flat pages folder) still reads, and the files rule lists the pages one folder down with
that folder named, never through a link. Fakes only."""
import os

import pytest

from router import __main__ as cli
from router import log, media
from router import page_files as pf
from tests.helpers import fake_label
from tests.test_intake import _file, ok, pages_ok
from tests.test_loop import Clock, Scripted
from tests.test_relay import CONFIG, ROSTER, Chat


@pytest.fixture
def media_root(tmp_path, monkeypatch):
    root = tmp_path / "media"
    monkeypatch.setattr(media, "MEDIA_ROOT", root)
    return root


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _two(conn, tmp_path, first="menu.pdf", second="prices.pdf"):
    files, lines, clock = [_file(tmp_path, first, size=1000), _file(tmp_path, second, size=1000)], [], Clock()

    def pages(pdf, dest):  # a different picture per PDF, so a mix-up shows
        dest.mkdir(parents=True, exist_ok=True)
        made = []
        for n in (1, 2):
            page = dest / f"page-{n}.png"
            page.write_bytes(f"{pdf.name} page {n}".encode())
            made.append(page)
        return made, 2
    cli.cmd_route("summarise both", conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                  label=fake_label(ok("read_media")), post=None, worker=Scripted("ok"), chatgpt=Chat("PASS"),
                  codex_login=lambda: True, sleep=clock.sleep, clock=clock, wait=False, files=files, pages=pages,
                  out=lines.append)
    row = log.recent_tasks(conn)[0]
    return row["task_id"], log.files_of(row)


def test_each_pdf_gets_its_own_pages_and_chatgpt_gets_each_pdfs_own_in_order(conn, tmp_path, media_root):
    tid, records = _two(conn, tmp_path)
    assert sorted(p.relative_to(media_root / "pages" / tid).as_posix()
                  for p in (media_root / "pages" / tid).rglob("*.png")) == [
        "menu/page-1.png", "menu/page-2.png", "prices/page-1.png", "prices/page-2.png"]
    items = media.layout(tid, records, agent="chatgpt")
    assert [(src.read_bytes().decode(), rel) for src, rel in items] == [
        ("menu.pdf page 1", "pages/menu-page-1.png"), ("menu.pdf page 2", "pages/menu-page-2.png"),
        ("prices.pdf page 1", "pages/prices-page-1.png"), ("prices.pdf page 2", "pages/prices-page-2.png")]


def test_two_pdfs_that_share_a_stem_would_each_get_a_folder_by_their_whole_name():
    # macOS's file system can't hold menu.pdf and menu.PDF in one folder, so this guards a case-sensitive disk only
    assert media.pages_folder("menu.pdf", ["menu.pdf", "prices.pdf"]) == "menu"
    assert media.pages_folder("menu.pdf", ["menu.pdf", "menu.PDF"]) == "menu.pdf"
    assert media.pages_folder("menu.PDF", ["menu.pdf", "menu.PDF"]) == "menu.PDF"
    assert media.pages_folder("menu.pdf", ["menu.pdf", "menu.png"]) == "menu"   # only another PDF can clash


def test_a_task_from_before_reads_its_one_flat_pages_folder(media_root):
    flat = media_root / "pages" / "sr-1"
    flat.mkdir(parents=True)
    for n in (2, 1, 10):
        (flat / f"page-{n}.png").write_bytes(b"png")
    (media_root / "in" / "sr-1").mkdir(parents=True)
    (media_root / "in" / "sr-1" / "old.pdf").write_bytes(b"%PDF")
    record = media.record(media_root / "in" / "sr-1" / "old.pdf", pages=3, total_pages=3)
    assert [rel for _, rel in media.layout("sr-1", [record], agent="chatgpt")] == [
        "pages/old-page-1.png", "pages/old-page-2.png", "pages/old-page-10.png"]
    assert not (media_root / "pages" / "sr-1" / "old").exists()   # reading makes no folder


TID = "sr-20261021-000803-3d77"


def test_the_files_rule_lists_each_pdfs_pages_one_folder_down_with_the_folder_named(tmp_path):
    root = tmp_path / "repo"
    (root / "media" / "in" / TID).mkdir(parents=True)
    (root / "media" / "in" / TID / "menu.pdf").write_bytes(b"%PDF")
    for name in ("menu", "prices"):
        (root / "media" / "pages" / TID / name).mkdir(parents=True)
        (root / "media" / "pages" / TID / name / "page-1.png").write_bytes(b"\x89PNG")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "page-1.png").write_bytes(b"secret")
    os.symlink(outside, root / "media" / "pages" / TID / "linked")      # a link out is never listed or opened
    found = pf.task_files(root, TID)
    assert [(f["path"], f["folder"]) for f in found] == [
        (f"media/in/{TID}/menu.pdf", None), (f"media/pages/{TID}/menu/page-1.png", "menu"),
        (f"media/pages/{TID}/prices/page-1.png", "prices")]
    assert pf.resolve(root, f"media/pages/{TID}/menu/page-1.png").read_bytes() == b"\x89PNG"
    with pytest.raises(pf.Refused):
        pf.resolve(root, f"media/pages/{TID}/linked/page-1.png")
