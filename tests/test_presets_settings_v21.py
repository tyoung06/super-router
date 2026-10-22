"""Build brief 21, B1 (decisions 6 and 7; the owner's B1 amendment). The preset loader learns one optional field,
`description`, one line of text shown by the page; every other unknown field is still refused, and file version 1.6
loads (the owner writes the five lines themselves). Settings gains `grok_timeout_minutes` 5, `memory` "auto" (shown only;
brief 22 acts on it) and `serve_port` (the port `sr serve` uses today). An optional, gitignored
`config/settings.local.json` overrides `config/settings.json` key by key; `report_path` lives only there, never in the
tracked file. Every value here is fake."""
import json
from pathlib import Path

import pytest

from router import __main__ as cli
from router import drop, page, presets, relay, settings
from tests.helpers import shipped_presets_doc, shipped_roster

ROSTER = shipped_roster()


def _load(tmp_path, doc):
    path = tmp_path / "presets.json"
    path.write_text(json.dumps(doc))
    return presets.load_presets(ROSTER, tuple(cli.SENDERS), relay.CONTRACTS, path=path, roles=relay.ROLES,
                                verdicts=relay.VERDICTS)


def _shipped_doc():
    return shipped_presets_doc()  # as 1.5, with no descriptions, before or after the owner's 1.6


# ---------- the preset description ----------

def test_a_description_is_loaded_and_kept_when_a_slot_is_filled(tmp_path):
    doc = _shipped_doc()
    doc["version"] = "1.6"
    doc["presets"]["versus"]["description"] = "Two builders, each reviews the other; you pick."
    loaded = _load(tmp_path, doc)
    assert loaded.version == "1.6" and loaded.presets["versus"].description == "Two builders, each reviews the other; you pick."
    assert loaded.presets["collab"].description is None
    filled = presets.fill(loaded.presets["versus"], {"b": "cursor"})
    assert filled.description == "Two builders, each reviews the other; you pick."


@pytest.mark.parametrize("bad", ["", "   ", "two\nlines", 5, None, ["a"]])
def test_a_description_that_is_not_one_line_of_text_is_refused_with_the_reason(tmp_path, bad):
    doc = _shipped_doc()
    doc["presets"]["versus"]["description"] = bad
    loaded = _load(tmp_path, doc)
    assert "versus" not in loaded.presets
    assert loaded.problems["versus"] == ["preset versus: description must be one line of text."]


def test_any_other_unknown_field_is_still_refused(tmp_path):
    doc = _shipped_doc()
    doc["presets"]["versus"]["blurb"] = "x"
    assert _load(tmp_path, doc).problems["versus"] == ["preset versus has an unknown field 'blurb'."]


def test_the_shipped_file_loads_with_or_without_descriptions():
    loaded = presets.load_presets(ROSTER, tuple(cli.SENDERS), relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
    assert loaded.version in presets.FILE_VERSIONS and not loaded.problems
    assert all(p.description is None or (p.description.strip() and "\n" not in p.description)
               for p in loaded.presets.values())  # 1.5 has none; the owner's 1.6 adds one line each
    assert "1.6" in presets.FILE_VERSIONS


def test_json_is_a_reserved_slot_name():
    assert "json" in presets.RESERVED_SLOT_NAMES


# ---------- settings ----------

@pytest.fixture
def files(tmp_path, monkeypatch):
    tracked, local = tmp_path / "settings.json", tmp_path / "settings.local.json"
    monkeypatch.setattr(settings, "SETTINGS_PATH", tracked)
    monkeypatch.setattr(settings, "LOCAL_PATH", local)
    return tracked, local


def test_the_shipped_file_holds_the_new_keys_and_no_report_path():
    doc = json.loads(settings.REPO_SETTINGS.read_text())
    assert (doc["grok_timeout_minutes"], doc["memory"], doc["serve_port"]) == (5, "auto", page.DEFAULT_PORT)
    assert "report_path" not in doc  # The owner's amendment: never in the tracked file (the repo goes public)


def test_the_readers_and_their_defaults(files):
    tracked, local = files
    tracked.write_text(json.dumps({"grok_timeout_minutes": 5, "memory": "auto", "serve_port": 8765}))
    assert (settings.grok_timeout_minutes(), settings.memory_mode(), settings.serve_port(), settings.report_path()) == (
        5, "auto", 8765, None)
    tracked.write_text("{}")
    assert (settings.grok_timeout_minutes(), settings.memory_mode(), settings.serve_port(), settings.report_path()) == (
        None, "auto", page.DEFAULT_PORT, None)


@pytest.mark.parametrize("key, bad, reader, default", [
    ("grok_timeout_minutes", 0, "grok_timeout_minutes", None), ("grok_timeout_minutes", "5", "grok_timeout_minutes", None),
    ("grok_timeout_minutes", True, "grok_timeout_minutes", None), ("grok_timeout_minutes", 2.5, "grok_timeout_minutes", None),
    ("memory", "sometimes", "memory_mode", "auto"), ("serve_port", 0, "serve_port", 8765),
    ("serve_port", 70000, "serve_port", 8765), ("serve_port", "8765", "serve_port", 8765),
    ("report_path", "", "report_path", None), ("report_path", 5, "report_path", None)])
def test_a_bad_value_reads_as_the_default(files, key, bad, reader, default):
    files[0].write_text(json.dumps({key: bad}))
    assert getattr(settings, reader)() == default


def test_memory_off_is_kept(files):
    files[0].write_text(json.dumps({"memory": "off"}))
    assert settings.memory_mode() == "off"


def test_the_local_file_overrides_key_by_key_and_holds_report_path(files):
    tracked, local = files
    tracked.write_text(json.dumps({"drop_folder": "~/Desktop/Router Drop", "serve_port": 8765, "grok_prompt_limit": 3662}))
    local.write_text(json.dumps({"serve_port": 8800, "report_path": "~/Downloads/claude-code-report.md"}))
    assert settings.serve_port() == 8800
    assert settings.report_path() == str(Path.home() / "Downloads" / "claude-code-report.md")
    assert settings.grok_prompt_limit() == (3662, settings.SOURCE)  # untouched keys come from the tracked file
    assert drop.folder() == Path.home() / "Desktop" / "Router Drop"
    local.write_text("not json")
    assert settings.serve_port() == 8765  # an unreadable local file is no override


def test_the_local_file_is_gitignored():
    assert "config/settings.local.json" in (settings.safety.REPO_ROOT / ".gitignore").read_text().splitlines()


def test_sr_serve_defaults_to_the_settings_port(files, monkeypatch):
    files[0].write_text(json.dumps({"serve_port": 8801}))
    seen = {}
    monkeypatch.setattr(cli.page, "serve", lambda *a, **k: seen.update(k, args=a) or 0)
    assert cli.main(["serve"]) == 0
    assert 8801 in seen["args"] or seen.get("port") == 8801


# ---------- brief 26 (decision 8): projects_root ----------

def test_projects_root_absent_reads_the_default_from_code(files):
    files[0].write_text("{}")
    assert settings.projects_root() == (Path.home() / "Projects", None)
    assert settings.projects_root_written() == "~/Projects"
    assert "projects_root" not in json.loads(settings.REPO_SETTINGS.read_text())  # the tracked file gets no key


def test_projects_root_expands_tilde_and_the_local_file_wins(files):
    tracked, local = files
    tracked.write_text(json.dumps({"projects_root": "/Users/you/Elsewhere"}))
    local.write_text(json.dumps({"projects_root": "~/Desktop/garden-projects"}))
    assert settings.projects_root() == (Path.home() / "Desktop" / "garden-projects", None)
    assert settings.projects_root_written() == "~/Desktop/garden-projects"


@pytest.mark.parametrize("bad", ["Projects", "./Projects", "", "   ", 5, None, ["~/Projects"]])
def test_a_projects_root_that_is_not_absolute_is_a_reason(files, bad):
    files[0].write_text(json.dumps({"projects_root": bad}))
    root, why = settings.projects_root()
    if bad is None:  # null is absent
        assert (root, why) == (Path.home() / "Projects", None)
        return
    assert root is None and "projects_root in settings" in why
