"""The docs refresh (4 Nov): docs/SETUP.md is for setting up and docs/GUIDE.md for using the router. The page's Settings rows
read SETUP.md by section, so every piece stays there; what the docs say about teams and models is read from the config, so
the words and the router can't drift apart."""
import json
import re
from pathlib import Path

from scripts import publish

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
SETUP = (ROOT / "docs" / "SETUP.md").read_text(encoding="utf-8")
GUIDE = (ROOT / "docs" / "GUIDE.md").read_text(encoding="utf-8")
SETUP_TITLES = ["Before you start", "Claude", "ChatGPT", "Cursor", "Grok Bot", "Jev", "Memory", "Git", "Router notes", "Models"]
MOVED = ["Projects", "Project notes", "The spec", "Test, Run and Secrets", "Split", "The check", "Next steps", "The plan", "Auto"]


def _titles(text):
    return re.findall(r"^## (.+?)\s*$", text, re.M)


def _section(text, title):
    return text.split(f"\n## {title}\n", 1)[1].split("\n## ", 1)[0]


def _anchor(title):
    return re.sub(r"[^a-z0-9 -]", "", title.lower()).replace(" ", "-")


def test_setup_holds_the_pieces_and_only_the_pieces():
    assert _titles(SETUP) == SETUP_TITLES


def test_the_guide_holds_every_section_that_moved():
    for title in MOVED:
        assert title in _titles(GUIDE), title
        assert title not in _titles(SETUP), title


def test_the_guide_adds_the_page_teams_and_stops():
    for title in ("The page", "Teams", "When a task stops"):
        assert title in _titles(GUIDE), title


def test_the_contents_list_names_every_section_and_each_link_lands():
    links = re.findall(r"^- \[(.+?)\]\(#([a-z0-9-]+)\)$", GUIDE, re.M)
    assert [title for title, _ in links] == _titles(GUIDE)
    assert all(anchor == _anchor(title) for title, anchor in links)


def test_each_doc_links_the_other_and_the_readme_links_both():
    assert "(GUIDE.md)" in SETUP and "(SETUP.md)" in GUIDE
    assert "(docs/SETUP.md)" in README and "(docs/GUIDE.md)" in README


def test_the_guide_is_published_and_names_no_person_or_path():
    assert publish.classify("docs/GUIDE.md") == publish.classify("docs/SETUP.md")
    assert "/Users/" not in GUIDE


def test_the_setup_guide_reads_right_on_github_as_well_as_on_the_page():
    for stale in ("on this row", "On this row", "this row", "Setup sheet"):
        assert stale not in SETUP, stale


def test_the_words_the_page_outgrew_are_gone():
    assert "Create runs the command the sheet shows" not in GUIDE
    assert 'the composer reads "Project: <name>"' not in GUIDE
    assert "Route item fills the box, text only, and sends nothing; every other item sends at once" not in GUIDE
    assert "always shows the exact command" not in README


def test_models_says_what_a_clone_really_runs():
    # config/models.json's own default: the owner's Opus and Fable defaults live in a file that never goes public
    doc = json.loads((ROOT / "config" / "models.json").read_text(encoding="utf-8"))
    claude = doc["agents"]["claude"]
    section = _section(SETUP, "Models")
    assert f"Claude runs {claude['names'][claude['default']]} on every call" in section
    assert "Claude's checks and most of its calls on Sonnet 5.5" not in section


def test_planner_notes_reach_a_plan_as_well_as_a_split():
    assert "**Planner** goes to a split's plan and to a project plan's planning calls" in _section(SETUP, "Router notes")


def test_cursors_jobs_are_named_where_a_clone_decides_whether_to_set_it_up():
    assert "second attacker" in _section(SETUP, "Cursor") and "a plan" in _section(SETUP, "Cursor")
    line = next(l for l in README.splitlines() if l.startswith("- **Cursor (optional).**"))
    assert "`redteam`" in line and "Plan" in line and "`versus`" in line


def test_the_memory_section_names_the_control_page_and_never_starts_it():
    text = _section(SETUP, "Memory")
    assert "127.0.0.1:9999" in text and "never starts it" in text


def test_the_readme_and_the_guide_name_every_team():
    presets = json.loads((ROOT / "config" / "presets.json").read_text(encoding="utf-8"))["presets"]
    names = list(presets) if isinstance(presets, dict) else [p["name"] for p in presets]
    for name in [*names, "split", "plan"]:
        assert f"`{name}`" in README, name
        assert f"`{name}`" in _section(GUIDE, "Teams"), name


def test_the_readme_tells_the_project_path_in_order():
    path = _section(README, "Work on a project")
    words = ["spec", "Plan", "Auto", "Land"]
    assert [path.index(w) for w in words] == sorted(path.index(w) for w in words)


# ---------- the full check against the code (4 Nov): what the first pass missed ----------

def test_the_first_chip_is_the_routers_move_as_nextsteps_makes_it():
    chips = _section(GUIDE, "Next steps").split("**Build from this.**", 1)[0]
    assert "**Build step k**" in chips and "**Plan from #<n>**" in chips and "**Build from #<n>**" in chips
    assert "The first is the router's own, **Build from #<n>**" not in chips


def test_what_now_names_the_rungs_whatnow_has():
    line = _section(GUIDE, "Next steps").split("**What now?**", 1)[1].split("\n", 1)[0]
    for words in ("Auto run", "spec changed", "Build step"):
        assert words in line, words


def test_the_finish_line_says_check_against_the_spec_comes_first():
    assert "**Check against the spec**" in _section(GUIDE, "The plan")


def test_the_spec_says_covers_and_what_a_change_does():
    text = _section(GUIDE, "The spec")
    assert "`covers: E1, E3`" in text and "**Revise plan**" in text and "Auto" in text
    assert "the spec changed" in _section(GUIDE, "Auto")


def test_a_used_idea_goes_to_its_folded_list():
    assert "Used (n)" in _section(GUIDE, "Next steps")


def test_a_split_on_a_project_never_takes_versus():
    assert "never `versus`" in _section(GUIDE, "Split")


def test_grok_is_not_said_to_check_bulk_text():
    # its check prompts pass grok_prompt_limit, so the check is skipped and the next checker checks (CLAUDE.md, Checking)
    assert "and bulk text by Grok Bot" not in _section(SETUP, "ChatGPT")
    assert "and checking bulk text" not in _section(SETUP, "Grok Bot")


def test_cursor_missing_says_a_plan_runs_with_one_attacker():
    assert "Redteam and Plan run with one attacker" in _section(SETUP, "Cursor")


def test_the_readme_doesnt_promise_an_estimate_before_every_team():
    assert "each shows its estimate for your OK" not in README


def test_the_fable_limit_is_the_max_plans():
    assert "On the Max plan, Fable 5.1 can charge usage credits" in _section(SETUP, "Models")
