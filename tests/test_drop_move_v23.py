"""Build brief 23, decision 8: a file the page drops goes into the drop folder and the send carries `--file <that path>`.
A `--file` at the drop folder's top level (resolved through links) moves to `sent/<task_id>/` once attached, as a
y-answered drop does, so the next `sr route` in Terminal never offers it again; the row records `moved_to` the same way.
A file in `sent/`, in a subfolder, or outside the folder stays put, and so does a link in the folder that points
elsewhere. The Terminal offer skips a file `--file` already names, so it is never attached twice. Fake agents, a temp
folder; no test touches the real drop folder."""
from router import drop, log, media
from tests.test_drop import _put, _route, conn, folder, media_root  # noqa: F401  (the drop folder fixtures)


def test_a_file_at_the_drop_folders_top_level_moves_to_sent_once_attached(conn, folder):
    given = _put(folder, "pic.png", 2048)
    code, out, row, prompts, _ = _route(conn, "describe this", folder=folder, files=[given], terminal=False)
    assert code == 0 and prompts == []
    sent = folder / "sent" / row["task_id"]
    files = log.files_of(row)
    assert [(f["name"], f["moved_to"]) for f in files] == [("pic.png", str(sent))]
    assert (sent / "pic.png").stat().st_size == 2048 and not given.exists() and drop.waiting(folder) == []
    assert (media.MEDIA_ROOT / "in" / row["task_id"] / "pic.png").stat().st_size == 2048  # the copy was made first
    assert f"Moved 1 file(s) from the drop folder to {sent}/." in out


def test_a_file_in_sent_in_a_subfolder_or_outside_stays_put(conn, folder, tmp_path):
    (folder / "sub").mkdir()
    (folder / "sent" / "sr-old").mkdir(parents=True)
    inside_sub, in_sent, outside = _put(folder / "sub", "a.png"), _put(folder / "sent" / "sr-old", "b.png"), _put(tmp_path, "c.png")
    code, out, row, _, _ = _route(conn, "describe these", folder=folder, files=[inside_sub, in_sent, outside], terminal=False)
    assert code == 0 and all(p.exists() for p in (inside_sub, in_sent, outside))
    assert [f["moved_to"] for f in log.files_of(row)] == [None, None, None] and "Moved" not in out


def test_a_link_in_the_drop_folder_that_points_elsewhere_stays_put(conn, folder, tmp_path):
    target = _put(tmp_path, "real.png")
    link = folder / "link.png"
    link.symlink_to(target)
    code, out, row, _, _ = _route(conn, "describe this", folder=folder, files=[link], terminal=False)
    assert code == 0 and link.is_symlink() and target.exists() and log.files_of(row)[0]["moved_to"] is None


def test_the_terminal_offer_skips_a_file_already_given_by_file(conn, folder):
    given, other = _put(folder, "a.png"), _put(folder, "b.png")
    code, out, row, prompts, _ = _route(conn, "what are these", folder=folder, files=[given], terminal=True, answer="y")
    assert code == 0 and prompts == ["Attach these 1 files? [y/N] "] and "  a.png" not in out and "  b.png (" in out
    sent = folder / "sent" / row["task_id"]
    assert sorted(f["name"] for f in log.files_of(row)) == ["a.png", "b.png"]
    assert sorted(p.name for p in sent.iterdir()) == ["a.png", "b.png"] and drop.waiting(folder) == []


def test_with_every_waiting_file_already_given_the_offer_asks_nothing(conn, folder):
    given = _put(folder, "a.png")
    code, out, row, prompts, _ = _route(conn, "describe this", folder=folder, files=[given], terminal=True, answer="y")
    assert code == 0 and prompts == [] and "The drop folder has" not in out
    assert log.files_of(row)[0]["moved_to"] == str(folder / "sent" / row["task_id"])


def test_a_refused_file_moves_nothing(conn, folder):
    given = _put(folder, "notes.txt")
    code, out, row, _, _ = _route(conn, "read this", folder=folder, files=[given], terminal=False)
    assert code == 2 and row is None and given.exists() and drop.waiting(folder) == [given]


def test_without_a_drop_folder_a_file_stays_put(conn, tmp_path):
    given = _put(tmp_path, "pic.png")
    code, out, row, _, _ = _route(conn, "describe this", folder=None, files=[given], terminal=False)
    assert code == 0 and given.exists() and log.files_of(row)[0]["moved_to"] is None


def test_at_top_level_reads_the_resolved_parent(folder, tmp_path):
    assert drop.at_top_level(folder, _put(folder, "x.png")) is True
    (folder / "sub").mkdir()
    assert drop.at_top_level(folder, _put(folder / "sub", "y.png")) is False
    assert drop.at_top_level(folder, _put(tmp_path, "z.png")) is False
    assert drop.at_top_level(None, folder / "x.png") is False
    assert drop.at_top_level(folder, folder / "missing.png") is False
