"""Build brief 24, E (decision 16): docs/SETUP.md finished. Claude is required; every other piece is optional, each with
what happens without it. Grok Bot from scratch: a private inbox repo, `gh` signed in, the routine to copy (the owner's
instruction, their repo replaced by `owner/inbox`), its webhook into `.env`, and `grok_inbox_repo` in
config/settings.local.json; every grok.com step is marked to check there, with no button named. ChatGPT's safety check
runs itself. `.env.example` keeps placeholders and says the inbox repo is a setting, not a key."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETUP = (ROOT / "docs" / "SETUP.md").read_text()
ENV = (ROOT / ".env.example").read_text()
ROUTINE = ('A webhook fired with a JSON body. Do the work described in its "task" field. Then, without asking for '
           'approval, open a GitHub issue in the private repo owner/inbox whose title is exactly the "task_id" field and '
           'whose body is the result. Create it with a GitHub tool that creates the issue directly (on the setup this was '
           'written for, the cursor-github create_issue tool). Do NOT use any tool that shows a confirmation or Submit '
           'form; if one does, retry with the direct tool so the issue is actually created. If the task produces files '
           '(like images) that must be committed, use the authenticated gh CLI on the box to commit them. Afterward, post '
           'a brief note in this chat with the result and a link to the issue.')


def _section(title):
    return SETUP.split(f"## {title}\n", 1)[1].split("\n## ", 1)[0]


def test_claude_is_required_and_every_other_piece_says_what_happens_without_it():
    assert "**Claude is required. Every other piece is optional.**" in SETUP
    assert "**Without it.** Nothing runs" in _section("Claude")
    for title in ("ChatGPT", "Cursor", "Grok Bot", "Jev", "Memory"):
        assert "**Without it.**" in _section(title), title


def test_without_grok_bot_x_research_and_images_come_back_and_only_meta_research_has_a_stand_in():
    # The owner, 21 Oct: x_social_pulse is Grok Bot's alone, as make_media is
    without = _section("Grok Bot").split("**Without it.** ", 1)[1].split("\n", 1)[0]
    assert without.startswith("X research and images (Make media) come back to you")
    assert 'Meta research goes to ChatGPT (or Claude)' in without and '"done without Meta"' in without
    assert "X and Meta research goes to" not in SETUP and "done without X" not in SETUP


def test_grok_bot_from_scratch_with_the_routine_word_for_word():
    grok = _section("Grok Bot")
    assert ROUTINE in grok
    for step in ("private repository", "gh auth login", "gh auth status", "with a webhook trigger", "GROK_WEBHOOK_URL=",
                 "GROK_WEBHOOK_KEY=", '{"grok_inbox_repo": "owner/inbox"}', "config/settings.local.json",
                 "open issues and commit files"):
        assert step in grok, step
    grok_steps = [line for line in grok.splitlines() if "grok.com" in line]
    assert grok_steps and all("Check on grok.com" in line for line in grok_steps[1:])   # each step checks there
    assert not re.search(r"(click|press|tap) ", grok, re.IGNORECASE)                 # no button named


def test_chatgpts_safety_check_runs_itself():
    assert "ChatGPT's safety check runs itself" in _section("ChatGPT")


def test_env_example_holds_placeholders_only_and_says_the_inbox_repo_is_a_setting():
    values = [line.split("=", 1)[1] for line in ENV.splitlines() if "=" in line and not line.startswith("#")]
    assert values and all(v == '""' for v in values)
    assert "inbox repository is a setting, not a key: grok_inbox_repo in config/settings.local.json" in ENV
