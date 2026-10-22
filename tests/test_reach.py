"""Rules v2.9: a checker that cannot reach what the result is about gives a sanity check only, and
says so. The web is what web_research, x_social_pulse and meta_social_trends are about. Who can
browse: Grok always, ChatGPT when its search is live, Claude never. Every call on a web skill, do,
fix or check, runs with search on. For every other skill, reading the result is the full check."""
import pytest

from router import __main__ as cli
from router import checking, log
from tests.helpers import ALL_AGENTS, JEV_OK

WEB = ("web_research", "x_social_pulse", "meta_social_trends")


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


# ---------- the pure rules ----------

def test_the_three_web_skills_get_live_search_and_nothing_else_does():
    assert checking.WEB_SKILLS == WEB and cli.LIVE_SEARCH_SKILLS == WEB
    for skill in WEB:
        assert checking.search_for(skill) == "live"
    for skill in ("code", "writing", "planning", "bulk_text", "quick_answer", "read_media", "make_media", None):
        assert checking.search_for(skill) == "disabled"


@pytest.mark.parametrize("agent, web_search, browses", [
    ("grok", "live", True), ("grok", "disabled", True),
    ("chatgpt", "live", True), ("chatgpt", "disabled", False),
    ("claude", "live", False), ("claude", "disabled", False),
    ("muse", "live", False), (None, "live", False),
])
def test_who_can_browse(agent, web_search, browses):
    assert checking.can_browse(agent, web_search) is browses


@pytest.mark.parametrize("skill, checker, sanity", [
    ("web_research", "claude", True),        # The owner's cell 1
    ("x_social_pulse", "chatgpt", False),    # cell 2: ChatGPT checks a web skill with search live
    ("code", "chatgpt", False),              # cell 3: search off, and reading the code is the full check
    ("meta_social_trends", "grok", False),   # cell 4: Grok always browses
    ("writing", "claude", False),            # cell 5: Claude on a text skill is a full check
    ("meta_social_trends", "claude", True),
    ("x_social_pulse", "claude", True),
    ("bulk_text", "grok", False),
    ("web_research", "chatgpt", False),
])
def test_sanity_check_cells(skill, checker, sanity):
    assert checking.sanity_check(skill, checker) is sanity


# ---------- the calls the planner makes ----------

def _task(skill, agent, checker):
    # brief 24: an override, which is how ChatGPT did X research before stand-ins (decision 9's line is never on one)
    return {"task_id": "sr-1", "task": "t", "skill": skill, "agent": agent, "checker": checker, "route_reason": "override"}


def _planned(task, step, ready=False):
    """A call as the check loop plans it: its search state first (rules v2.22), then the call."""
    return cli._plan_call(task, step, searching=cli._call_search(task, step, lambda: ready))


def test_do_and_fix_calls_run_with_search_on_for_every_skill():
    # rules v2.22: before, only the web skills searched; now every skill does (no file on these calls)
    for skill in WEB + ("code", "writing", "planning", "bulk_text"):
        _, kind, agent, text, web_search = _planned(_task(skill, "chatgpt", "claude"), checking.Step("do"))
        assert (kind, agent, text, web_search) == ("do", "chatgpt", "t\n\n" + checking.SEARCH_LINE_GENERAL, "live")
        _, kind, _, _, web_search = _planned(_task(skill, "chatgpt", "claude"),
                                             checking.Step("fix", result="r", fix_list="1. x"))
        assert (kind, web_search) == ("fix", "live")


def test_check_calls_run_with_search_on_and_the_prompt_follows_the_checkers_reach():
    step = checking.Step("check", result="the result")
    # Grok checking meta_social_trends (an @chatgpt task): may browse, always; no search line (the router leaves Grok be)
    _, kind, agent, prompt, ws = _planned(_task("meta_social_trends", "chatgpt", "grok"), step)
    assert (kind, agent) == ("check", "grok")
    assert prompt == checking.checker_prompt("t", "the result", no_tools=False, can_browse=True)
    # ChatGPT checking meta_social_trends: search on, may browse, the search line
    _, _, agent, prompt, ws = _planned(_task("meta_social_trends", "grok", "chatgpt"), step)
    assert (agent, ws) == ("chatgpt", "live")
    assert prompt == checking.checker_prompt("t", "the result", no_tools=False, can_browse=True, search=True)
    # Claude checking web_research with the probe gate shut: no tools, cannot browse (as before)
    _, _, agent, prompt, ws = _planned(_task("web_research", "chatgpt", "claude"), step)
    assert agent == "claude"
    assert prompt == checking.checker_prompt("t", "the result", no_tools=True, can_browse=False)
    # Claude checking web_research with the probe passed: search results only, the search line (rules v2.22)
    _, _, agent, prompt, ws = _planned(_task("web_research", "chatgpt", "claude"), step, ready=True)
    assert prompt == checking.checker_prompt("t", "the result", no_tools=False, claude_search=True, search=True)
    assert checking.CLAUDE_SEARCH_PARAGRAPH in prompt and "cannot open pages" in prompt
    # ChatGPT checking code: search on now (before rules v2.22 it was off)
    _, _, _, prompt, ws = _planned(_task("code", "claude", "chatgpt"), step)
    assert ws == "live" and prompt == checking.checker_prompt("t", "the result", no_tools=False, can_browse=True,
                                                              search=True)


# ---------- what the owner reads ----------

def _passed_task(conn, task_id, skill, agent, checker):
    log.add_task(conn, task_id, "task text", "cli", {**JEV_OK, "label": skill})
    log.set_route(conn, task_id, agents=ALL_AGENTS, agent=agent, route_reason="best", skill=skill, skill_source="jev",
                  checker=checker, check_state="pending")
    log.set_sent(conn, task_id, "uuid-do")
    log.finish_call(conn, task_id, "done", text="the result")
    log.add_call(conn, f"{task_id}-c1", task_id, "check", checker, status="done", text="PASS", verdict="PASS")
    log.set_done(conn, task_id, "the result", None, check_state="passed")


def _show(conn, task_id):
    lines = []
    assert cli.cmd_show(conn=conn, words=[task_id], out=lines.append) == 0
    return "\n".join(lines)


@pytest.mark.parametrize("skill, agent, checker, sanity", [
    ("web_research", "chatgpt", "claude", True),
    ("x_social_pulse", "grok", "chatgpt", False),
    ("code", "claude", "chatgpt", False),
    ("meta_social_trends", "chatgpt", "grok", False),
    ("writing", "chatgpt", "claude", False),
])
def test_the_check_line_says_sanity_check_only_exactly_when_the_checker_could_not_reach_the_web(conn, skill, agent,
                                                                                                 checker, sanity):
    _passed_task(conn, "sr-1", skill, agent, checker)
    out = _show(conn, "sr-1")
    if sanity:
        assert "CHECKED (sanity check only): passed. The checker can't open links or verify facts." in out
    else:
        assert "CHECKED: passed." in out and "sanity" not in out
