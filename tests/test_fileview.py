"""Brief 29.1 (decision 9): ChatGPT's file view on versus in file mode, its reply's contract and the router's write."""
import pytest

from router import fileview


def facts(**files):
    """Facts of a copy holding `files` ({path with __ for /: text or bytes})."""
    found = {}
    for key, value in files.items():
        path = key.replace("__", "/").replace("_dot_", ".")
        data = value if isinstance(value, bytes) else value.encode("utf-8")
        found[path] = fileview._info(path, data)
    return fileview.Facts(found)


CALC = "def add(a, b):\n    return a - b\n"
TEST = "import unittest\n\nfrom calc import add\n"


def project():
    return facts(**{"calc_dot_py": CALC, "test_calc_dot_py": TEST, "README_dot_md": "# calc\n"})


def test_the_view_lists_every_file_with_its_size_then_each_text_whole():
    text = fileview.render(project())
    head = text.splitlines()
    assert head[0] == "===== FILE VIEW: 3 files ====="
    assert "calc.py · 32 bytes" in head and "README.md · 7 bytes" in head
    assert "=== file: calc.py ===\ndef add(a, b):\n    return a - b\n=== end file ===" in text
    assert text.endswith("===== END FILE VIEW =====")


def test_a_binary_or_long_file_is_listed_with_its_size_and_not_shown():
    found = facts(**{"logo_dot_png": b"\x89PNG\x00\x01", "big_dot_txt": "x" * (fileview.VIEW_FILE_CHARS + 1),
                     "nul_dot_txt": "a\x00b"})
    text = fileview.render(found)
    assert "logo.png · 6 bytes (not shown: binary)" in text
    assert f"big.txt · {fileview.VIEW_FILE_CHARS + 1:,} bytes (not shown: too long)" in text
    assert "nul.txt · 3 bytes (not shown: binary)" in text
    assert "=== file:" not in text
    assert fileview.shown_chars(found) == 0


def test_a_text_file_at_the_limit_is_shown():
    found = facts(**{"edge_dot_txt": "y" * fileview.VIEW_FILE_CHARS})
    assert fileview.shown_chars(found) == fileview.VIEW_FILE_CHARS


def test_a_file_holding_a_marker_line_is_not_shown():
    found = facts(**{"odd_dot_md": "a\n=== end file ===\nb\n"})
    assert "(not shown: it holds a file-view line)" in fileview.render(found)


def test_the_view_round_trips_a_file_through_a_block():
    for text in ("one\ntwo\n", "no newline", "two blank\n\n", ""):
        found = facts(**{"f_dot_txt": text})
        view = fileview.render(found)
        block = view[view.index("=== file: f.txt ==="):view.index("=== end file ===") + len("=== end file ===")]
        parsed = fileview.parse("Done.\n" + block, facts(**{"f_dot_txt": "old\n"}))
        assert parsed.missing == ()
        want = text if text.endswith("\n") or not text else text + "\n"
        assert parsed.blocks[0].text == want


GOOD = """Fixed add() so it adds.

=== file: calc.py ===
def add(a, b):
    return a + b
=== end file ===
=== file: notes/new.txt ===
hello
=== end file ===
=== delete: README.md ===

## Handoff
### Produced
calc.py, notes/new.txt; README.md deleted
### Status
fixed
### Next
none
"""


def test_a_good_reply_parses_into_blocks_and_a_candidate_without_them():
    parsed = fileview.parse(GOOD, project())
    assert parsed.missing == ()
    assert [(b.path, b.text) for b in parsed.blocks] == [
        ("calc.py", "def add(a, b):\n    return a + b\n"), ("notes/new.txt", "hello\n"), ("README.md", None)]
    assert parsed.candidate.startswith("Fixed add() so it adds.\n\n## Handoff\n### Produced")
    assert "=== file:" not in parsed.candidate and "=== delete:" not in parsed.candidate
    assert fileview.candidate_text(GOOD) == parsed.candidate


def test_a_reply_with_no_block_changes_nothing_and_meets_the_contract():
    parsed = fileview.parse("Nothing needs to change.\n\n## Handoff\n### Produced\nnothing written: x\n", project())
    assert parsed.blocks == () and parsed.missing == ()


@pytest.mark.parametrize("path, words", [
    ("/etc/passwd", "not relative"), ("../calc.py", "leaves the project's folder"), ("a//b.py", "plain form"),
    ("./calc.py", "plain form"), ("~/x", "not relative"), (".env", "never carries (.env)"),
    ("config/.env.local", "never carries (.env)"), (".git/config", "never carries (.git)"),
    ("HANDOFF.md", "never carries (HANDOFF.md)"), (".claude/settings.json", "never carries (.claude)"),
    ("calc.py/x.py", "its folder calc.py is a file"), ("a\\b.py", "backslash"),
])
def test_a_path_the_copy_cant_take_is_a_miss_naming_it(path, words):
    reply = f"Done.\n=== file: {path} ===\nx\n=== end file ===\n"
    parsed = fileview.parse(reply, project())
    assert len(parsed.missing) == 1 and f"`{path}`" in parsed.missing[0] and words in parsed.missing[0]


def test_a_link_the_project_holds_is_a_miss():
    found = fileview.Facts(project().files, ({"path": "docs/link.md", "why": "link"}, {"path": "vendor", "why": "submodule"}))
    for path in ("docs/link.md", "vendor/x.py"):
        parsed = fileview.parse(f"=== file: {path} ===\nx\n=== end file ===\n", found)
        assert len(parsed.missing) == 1 and "which the copy doesn't carry" in parsed.missing[0]


def test_a_path_twice_a_missing_delete_and_a_non_text_block_are_misses():
    reply = ("=== file: calc.py ===\na\n=== end file ===\n=== delete: calc.py ===\n=== delete: gone.py ===\n"
             "=== file: bin.dat ===\nab\x01cd\n=== end file ===\n")
    missing = fileview.parse(reply, project()).missing
    assert any("`calc.py` is given twice" in m for m in missing)
    assert any("`gone.py` is deleted, but the copy has no such file" in m for m in missing)
    assert any("`bin.dat` is not text" in m for m in missing)


def test_a_block_with_no_end_line_or_a_stray_end_line_is_a_miss():
    missing = fileview.parse("=== file: calc.py ===\na\n=== file: b.py ===\nb\n=== end file ===\n", project()).missing
    assert any("`=== file: calc.py ===` has no `=== end file ===`" in m for m in missing)
    assert any("line 3 is `=== end file ===`" in m for m in fileview.parse("x\ny\n=== end file ===\n", project()).missing)


def test_a_fenced_block_or_a_not_shown_file_is_a_miss():
    found = facts(**{"calc_dot_py": CALC, "logo_dot_png": b"\x89PNG\x00"})
    missing = fileview.parse("=== file: calc.py ===\n```python\ndef add(): pass\n```\n=== end file ===\n"
                             "=== file: logo.png ===\nx\n=== end file ===\n", found).missing
    assert any("`calc.py` is wrapped in a code fence" in m for m in missing)
    assert any("`logo.png` was not shown to you (binary)" in m for m in missing)


def test_the_intake_check_refuses_a_key_by_file_and_line_and_the_limit_with_both_numbers():
    secret = "s" + "k-" + "proj" + "Z" * 40  # built at run time: never a key shape in a source line
    found = facts(**{"calc_dot_py": CALC, "keys_dot_txt": f"a\nkey = {secret}\n"})
    problem = fileview.intake_problem(found, secrets=[])
    assert problem is not None and "keys.txt line 2" in problem and secret not in problem
    value = "Q" * 12 + "w" * 9
    problem = fileview.intake_problem(facts(**{"x_dot_txt": f"one\ntwo {value}\n"}), secrets=[value])
    assert "x.txt line 2 holds a value from .env" in problem and value not in problem
    many = facts(**{f"f{k}_dot_txt": "z" * fileview.VIEW_FILE_CHARS for k in range(6)})
    problem = fileview.intake_problem(many, secrets=[])
    assert "120,000 characters" in problem and "at most 100,000" in problem
    assert fileview.intake_problem(project(), secrets=[]) is None


def test_the_key_scan_on_the_blocks_names_file_and_line_never_the_value():
    value = "V" * 20
    parsed = fileview.parse(f"=== file: calc.py ===\nok\nx = '{value}'\n=== end file ===\n", project())
    problem = fileview.scan_problem(parsed, [value])
    assert problem == "calc.py line 2 holds a value from .env"
    assert fileview.scan_problem(fileview.parse(GOOD, project()), [value]) is None


def test_the_router_writes_the_blocks_into_the_copy(tmp_path):
    tmp_path = tmp_path / "copy"  # the suite's own settings file sits in tmp_path itself
    tmp_path.mkdir()
    (tmp_path / "calc.py").write_text(CALC)
    (tmp_path / "README.md").write_text("# calc\n")
    (tmp_path / "calc.py").chmod(0o755)
    parsed = fileview.parse(GOOD, fileview.facts_of_folder(tmp_path))
    assert parsed.missing == ()
    assert fileview.write(tmp_path, parsed) == ["calc.py", "notes/new.txt", "README.md"]
    assert (tmp_path / "calc.py").read_text() == "def add(a, b):\n    return a + b\n"
    assert (tmp_path / "calc.py").stat().st_mode & 0o777 == 0o755
    assert (tmp_path / "notes" / "new.txt").read_text() == "hello\n"
    assert not (tmp_path / "README.md").exists()


def test_the_write_never_goes_through_a_link(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    copy = tmp_path / "copy"
    copy.mkdir()
    (copy / "docs").symlink_to(outside)
    parsed = fileview.Parsed((fileview.Block("docs/a.txt", "x\n", 1),), "")
    with pytest.raises(fileview.copies.CopyError):
        fileview.write(copy, parsed)
    assert not (outside / "a.txt").exists()


def test_the_facts_of_a_folder_skip_links(tmp_path):
    tmp_path = tmp_path / "copy"
    tmp_path.mkdir()
    (tmp_path / "a.txt").write_text("a\n")
    (tmp_path / "l.txt").symlink_to(tmp_path / "a.txt")
    assert list(fileview.facts_of_folder(tmp_path).files) == ["a.txt"]
