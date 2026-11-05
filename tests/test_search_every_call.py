"""Brief 15 addendum, phase D2: search on every call (rules v2.22, Web search). Claude and ChatGPT may search on
every call they make, unless the call carries a file and the task has no --web; Grok gets nothing from the router.
Claude still needs the probe pass. A prompt sent with search off is byte for byte the prompt `main` sent (the
fixture `prompts_v9.json`, made by tests/prompt_snapshot.py on main at a260d48); a prompt sent with search on is
main's plus the search line (and, on a ChatGPT check that had search off before, the browse paragraph). Every
Claude or ChatGPT call row records its state (D6). The sanity label comes from the check call's real state.
Every value here is fake."""
import json
from pathlib import Path

import pytest

from router import __main__ as cli
from router import checking, log, presets, relay, search, split, teams
from tests import prompt_snapshot
from tests.helpers import count_lines_in, fake_label, shipped_roster
from tests.test_loop import Clock, Scripted
from tests.test_relay import CONFIG, Chat

ROSTER = shipped_roster()
LOADED = presets.load_presets(ROSTER, tuple(cli.SENDERS), relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
FIXTURE = json.loads((Path(prompt_snapshot.__file__).parent / "fixtures" / "prompts_v9.json").read_text())


def _without_count(snapshot):
    """Build brief 17, Phase W: every prompt with the word-count lines taken out (and how many there were), so the
    rest is still compared byte for byte with main's. Brief 33 (decision 5): and without the `## Next` line, which goes
    last (and whether it was there)."""
    found, tail = {}, "\n\n" + checking.NEXT_LINE
    for key, value in snapshot.items():
        prompt, removed = count_lines_in(value["prompt"])
        has_next = prompt.endswith(tail)
        found[key] = {**value, "prompt": prompt[:-len(tail)] if has_next else prompt, "count_lines": removed,
                      "next_line": has_next}
    return found


NOW = _without_count(prompt_snapshot.snapshot(LOADED))
OPEN = _without_count(prompt_snapshot.snapshot(LOADED, ready=lambda: True))
LINE = "\n\n" + checking.SEARCH_LINE_GENERAL


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def test_the_snapshot_covers_every_kind_and_both_agents():
    assert set(NOW) == set(FIXTURE) and len(NOW) == 62
    kinds = {key.rsplit("/", 1)[-1] for key in NOW if key.startswith("writing")}
    assert kinds == {"do", "check", "fix", "recheck"}
    roles = {key.split("/")[1].split("-", 1)[1] for key in NOW if key.split("/")[0] in ("research-build", "collab", "versus")}
    assert roles == {"research", "build", "plan", "amend", "execute", "edit", "review"}
    assert {"split/1-split_plan", "split/2-integrate"} <= set(NOW)
    assert {key.rsplit("/", 1)[-1] for key in NOW if "/" in key and key.split("/")[0] in ("collab",)} == {"stage", "reask"}


@pytest.mark.parametrize("key", sorted(FIXTURE))
def test_the_count_lines_are_on_checks_fixes_and_the_check_stage_only(key):
    """Phase W: a check or re-check gets the length rule and the count line, a fix round the count line, collab's
    check stage both; nothing else gets either."""
    kind = key.rsplit("/", 1)[-1]
    want = 2 if kind in ("check", "recheck") or ("4-edit" in key and kind == "stage") else 1 if kind == "fix" else 0
    assert NOW[key]["count_lines"] == OPEN[key]["count_lines"] == want, key


# Brief 33 (decision 5): the `## Next` line, last, on exactly the prompts whose result can be delivered (off a project):
# the routed doer and its fix rounds, research-build's build, each versus build, their re-asks, and a split's integration
NEXT_KEYS = {key for key in FIXTURE if key.rsplit("/", 1)[-1] in ("do", "fix")} | {
    key for key in FIXTURE if key.startswith(("research-build/2-build/", "versus/1-build/", "versus/2-build/"))} | {
    "split/2-integrate"}


@pytest.mark.parametrize("key", sorted(FIXTURE))
def test_the_next_line_is_last_on_the_delivering_prompts_only(key):
    assert NOW[key]["next_line"] == OPEN[key]["next_line"] == (key in NEXT_KEYS), key
    assert checking.NEXT_LINE not in NOW[key]["prompt"] and checking.NEXT_LINE not in OPEN[key]["prompt"], key


# Brief 29 (decision 16): the one prompt the snapshot sees change is the split planner's: its words (a team per piece,
# with a why) and the router's TEAMS list after them. Every other prompt, the integration's included, is main's.
PLANNER_KEY = "split/1-split_plan"
MAINS_PLAN_WORDS = (
    "Break this task into 2 to 4 pieces that can each be done on their own, by one agent, without any other piece's "
    "result. Each piece is a complete task in one or two sentences, with everything it needs stated in it. No two pieces "
    "may ask for the same search or the same work. Work that needs another part's result stays in one piece with that "
    "part: a function and its tests are one piece. Then say in one line how the finished pieces join into one result. "
    "Return exactly: `## Pieces` (a numbered list), `## Join` (one line). Do not do any piece. If the task is one chain, "
    "where each part needs the one before it, do not split it: return only `## No split` with one line saying why.")


def _as_brief_29(key, prompt, searching=None):
    """Main's prompt as this branch sends it: brief 29's planner words and TEAMS list; brief 29.1's check, re-check and fix
    words, and the deliverable line on the doer and every build that returns the deliverable (collab's execute in its
    `## Unfinished` form). Every other prompt, each stage's re-ask included, is main's byte for byte."""
    kind = key.rsplit("/", 1)[-1]
    if key == PLANNER_KEY:
        menu = teams.menu_block(teams.menu(LOADED, ROSTER, None, send_paths=tuple(cli.SENDERS)))
        assert prompt.count(MAINS_PLAN_WORDS) == 1
        return prompt.replace(MAINS_PLAN_WORDS, split.PLAN_INSTRUCTIONS + "\n\n" + menu, 1)
    if kind in ("check", "recheck"):
        return prompt_snapshot.as_check(prompt, recheck=kind == "recheck")
    if kind == "fix":
        return prompt_snapshot.as_fix(prompt, could=searching == search.ALLOWED, musts=prompt_snapshot.FIXES)
    if kind == "do":
        return f"{prompt}\n\n{checking.DELIVERABLE_LINE}"
    if kind == "reask":
        return prompt
    return prompt_snapshot.as_build(prompt)


CHANGED_291 = {key for key in FIXTURE if key.rsplit("/", 1)[-1] in ("check", "recheck", "fix", "do")} | {
    key for key in FIXTURE if key.endswith("/stage") and (key.startswith("research-build/2-build/")
                                                          or key.startswith("collab/3-execute/")
                                                          or (key.startswith("versus/") and "-build/" in key))} | {
    "split/2-integrate"}


def test_only_the_planner_and_the_decided_prompts_changed_and_only_by_their_lines():
    changed = {key for key in FIXTURE if NOW[key]["prompt"] != FIXTURE[key]["prompt"]
               and not (NOW[key]["searching"] == search.ALLOWED)}
    off = {key for key in CHANGED_291 if NOW[key]["searching"] != search.ALLOWED}
    assert changed == {PLANNER_KEY} | off
    assert NOW[PLANNER_KEY]["prompt"] == _as_brief_29(PLANNER_KEY, FIXTURE[PLANNER_KEY]["prompt"])
    assert "\nTEAMS a piece may take" in NOW[PLANNER_KEY]["prompt"] and "by one team" in NOW[PLANNER_KEY]["prompt"]
    for key in FIXTURE:  # the stages no decision names (research, plan, amend, edit, review, the re-asks) are main's
        if key not in CHANGED_291 and key != PLANNER_KEY and NOW[key]["searching"] != search.ALLOWED:
            assert NOW[key]["prompt"] == FIXTURE[key]["prompt"], key


@pytest.mark.parametrize("key", sorted(FIXTURE))
def test_a_prompt_sent_with_search_off_is_byte_for_byte_mains(key):
    now, before = NOW[key], FIXTURE[key]
    if now["searching"] == search.ALLOWED:
        pytest.skip("search on: see the next test")
    assert now["prompt"] == _as_brief_29(key, before["prompt"], now["searching"])
    if now["agent"] == "chatgpt":
        assert now["web_search"] == before["web_search"] == "disabled"


@pytest.mark.parametrize("key", sorted(FIXTURE))
def test_a_prompt_sent_with_search_on_is_mains_plus_the_search_line(key):
    now, before = NOW[key], FIXTURE[key]
    if now["searching"] != search.ALLOWED:
        pytest.skip("search off: see the test above")
    prompt = now["prompt"]
    before = {**before, "prompt": _as_brief_29(key, before["prompt"], now["searching"])}  # brief 29 and 29.1
    if checking.SEARCH_LINE in before["prompt"]:   # research-build's build by chatgpt searched on main already
        assert prompt == before["prompt"], key
        return
    assert prompt.count(LINE) == 1, key
    stripped = prompt.replace(LINE, "", 1)
    if checking.CAN_BROWSE_PARAGRAPH not in before["prompt"]:   # a ChatGPT check that had search off before
        stripped = stripped.replace("\n\n" + checking.CAN_BROWSE_PARAGRAPH, "", 1)
    assert stripped == before["prompt"], key
    assert now["web_search"] == "live"


def test_every_kind_searches_for_claude_and_chatgpt_with_no_file_and_the_gate_open():
    for key, entry in OPEN.items():
        if "-file/" in key:
            assert entry["searching"] == search.OFF_FILE, key
        else:
            assert entry["searching"] == search.ALLOWED, key


def test_with_the_gate_shut_claude_is_off_probe_and_chatgpt_still_searches():
    for key, entry in NOW.items():
        if "-file/" in key:
            assert entry["searching"] == search.OFF_FILE, key
        elif entry["agent"] == "claude":
            assert entry["searching"] == search.OFF_PROBE, key
        else:
            assert entry["searching"] == search.ALLOWED, key


def test_neither_agent_searches_on_a_file_call_without_web():
    for key in ("writing-claude-does-file", "writing-chatgpt-does-file"):
        for kind in ("do", "check", "fix", "recheck"):
            entry = OPEN[f"{key}/{kind}"]
            assert entry["searching"] == search.OFF_FILE and checking.SEARCH_LINE_GENERAL not in entry["prompt"]
            if entry["agent"] == "chatgpt":
                assert entry["web_search"] == "disabled"


def test_grok_gets_no_state_on_any_kind():
    for kind, role in (("do", None), ("check", None), ("stage", "research"), ("reask", "review")):
        assert search.state({"mode": "route"}, kind=kind, role=role, agent="grok", files=(), ready=lambda: True) is None


def test_the_claude_checker_with_search_gets_the_results_only_paragraph():
    entry = OPEN["writing-chatgpt-does/check"]
    assert checking.CLAUDE_SEARCH_PARAGRAPH in entry["prompt"] and checking.NO_TOOLS_PARAGRAPH not in entry["prompt"]
    assert "cannot open pages" in entry["prompt"] and LINE in entry["prompt"]


def test_the_notes_search_line_stays_where_it_was():
    build = OPEN["research-build/2-build/claude/stage"]["prompt"]
    assert checking.SEARCH_LINE in build and checking.SEARCH_LINE_GENERAL not in build
    assert checking.SEARCH_LINE not in OPEN["collab/1-plan/claude/stage"]["prompt"]


# ---------- the rows and the sanity label ----------

def _route(conn, task, skill, *, ready, claude=("PASS",), chat=("The answer: https://example.org",)):
    lines, clock = [], Clock()
    code = cli.cmd_route(task, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=fake_label({"status": "ok", "label": skill, "confidence": 0.95, "needs_split": 0.1,
                                           "tokens": 0}),
                         post=None, worker=Scripted(*claude), chatgpt=Chat(*chat), codex_login=lambda: True,
                         sleep=clock.sleep, clock=clock, wait=False, claude_ready=lambda: ready, out=lines.append)
    return code, "\n".join(lines), log.recent_tasks(conn)[0]


class SearchingWorker(Scripted):
    def __call__(self, prompt, **kw):
        from router import claude_worker
        text = super().__call__(prompt)
        return claude_worker.SearchAnswer(text, ["query"]) if kw.get("search") else text


def test_claude_checking_web_research_with_search_on_is_a_full_check(conn):
    lines, clock = [], Clock()
    cli.cmd_route("find the S and P 500 close with a link", conn=conn, config=CONFIG, roster=ROSTER, environ={},
                  settings_paths=[],
                  label=fake_label({"status": "ok", "label": "web_research", "confidence": 0.95, "needs_split": 0.1,
                                    "tokens": 0}),
                  post=None, worker=SearchingWorker("PASS"), chatgpt=Chat("6,700.12 https://example.org"),
                  codex_login=lambda: True, sleep=clock.sleep, clock=clock, wait=False, claude_ready=lambda: True,
                  out=lines.append)
    out, row = "\n".join(lines), log.recent_tasks(conn)[0]
    assert "CHECKED: passed." in out and "sanity" not in out
    states = [(c["kind"], c["agent"], log.search_of(c)["state"]) for c in log.calls_for(conn, row["task_id"])]
    assert states == [("do", "chatgpt", "allowed"), ("check", "claude", "allowed")]


def test_claude_checking_web_research_with_the_probe_gate_shut_is_still_a_sanity_check(conn):
    code, out, row = _route(conn, "find the S and P 500 close with a link", "web_research", ready=False)
    assert "CHECKED (sanity check only): passed." in out
    check = log.calls_for(conn, row["task_id"])[1]
    assert log.search_of(check) == {"state": "off (probe not passed)"}


def test_a_check_row_from_before_reads_by_the_old_rule():
    assert checking.web_sanity("web_research", "claude", record=None, recorded=True) is True
    assert checking.web_sanity("web_research", "chatgpt", record=None, recorded=True) is False
    assert checking.web_sanity("web_research", "claude", record={"state": "allowed"}, recorded=True) is False
    assert checking.web_sanity("web_research", "chatgpt", record={"state": "off (file without --web)"},
                               recorded=True) is True
    assert checking.web_sanity("x_social_pulse", "grok", record=None, recorded=True) is False
    assert checking.web_sanity("writing", "claude", record={"state": "off (probe not passed)"}, recorded=True) is False


def test_sr_show_prints_the_file_state(conn):
    assert cli._search_text({"state": "off (file without --web)"}) == "search: off (file without --web)"
