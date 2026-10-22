"""Build brief 25 (P2): `sr status` reads the rules version from SUPER-ROUTER.md line 3, and where that file isn't (the
public clone, which never carries it) from docs/RULES.md, the cleaned copy made at each publish, whose line 3 keeps the
version. With neither, the version reads as unknown."""
import json

from router import __main__ as cli
from router import status

from tests.test_status import world  # noqa: F401  (the status world: fake checks, versions and store)

SOURCE = "# The rules\n\nVersion 2.34 · 2026-10-21 · the owner's file.\n"
COPY = "# Super Router rules\n\nVersion 2.34 · 2026-10-21 · A cleaned copy of the owner's rules, made at each publish.\n"


def test_super_router_md_wins_when_it_is_there(tmp_path):
    (tmp_path / "SUPER-ROUTER.md").write_text(SOURCE)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "RULES.md").write_text(COPY.replace("2.34", "9.99"))
    assert status.rules_file(tmp_path) == tmp_path / "SUPER-ROUTER.md"
    assert status.rules_version(status.rules_file(tmp_path)) == "2.34"


def test_without_it_the_cleaned_copy_is_read(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "RULES.md").write_text(COPY)
    assert status.rules_file(tmp_path) == tmp_path / "docs" / "RULES.md"
    assert status.rules_version(status.rules_file(tmp_path)) == "2.34"


def test_with_neither_the_version_is_unknown(tmp_path):
    assert status.rules_version(status.rules_file(tmp_path)) is None


def test_sr_status_reads_the_version_through_it(world, monkeypatch, tmp_path):  # noqa: F811
    root = tmp_path / "clone"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "RULES.md").write_text(COPY.replace("2.34", "7.01"))
    monkeypatch.setattr(cli, "ROOT", root)
    code, out, err = world.run("status", "--json")
    assert code == 0 and err == ""
    assert json.loads(out)["version"] == "7.01"
