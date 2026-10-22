"""Build brief 16, phase C: the redteam chain end to end with fake agents (rules v2.23). Build (task alone) →
attack (stage 1's result) → revise (its own stage 1 and the attack list, nothing else) → the usual check loop, the
checker also getting the attack list labeled apart; a fix round goes to the `build` agent with the task, the attack
list as the stage before, its revision and the fix list (decision 8). The task's result is the revision's
deliverable without `## Answered`; `sr show` prints it, then `--- attacks ---` and `--- answered ---`.
Every value here is fake."""
import json

import pytest

from router import __main__ as cli
from router import checking, log, presets, relay
from tests.helpers import shipped_roster
from tests.test_relay import CONFIG, Chat, Clock, RelayHook, Scripted

SENDERS = tuple(cli.SENDERS)
ROSTER = shipped_roster()
LOADED = presets.load_presets(ROSTER, SENDERS, relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
TASK = "Write a one-page plan for a weekly budget review ritual. Plain text, under 400 words."
BUILD = "## Deliverable\nReview on Sundays at 6pm.\nCheck groceries.\n\n## Unfinished\nnone"
ATTACKS = ("## Attacks\n1. [high] No trigger for a change is defined.\n2. [medium] Groceries only.\n"
           "3. [low] Sunday may clash with plans.\n\n## Strongest\nNo trigger for a change is defined.")
REVISION = ("Review on Sundays at 6pm.\nCheck groceries, rent and fun money.\nChange the budget when a line is 10% "
            "over two weeks running.\n\n## Answered\n3. Sunday is the user's choice; the plan says to move it if needed.")
DELIVERED = REVISION.split("\n\n## Answered")[0]


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _relay(conn, *, claude, chat, slots=(), bodies=None, wait=True, ready=None):
    hook, worker, chatgpt, clock, lines = RelayHook(**(bodies or {})), Scripted(*claude), Chat(*chat), Clock(), []
    code = cli.cmd_relay("redteam", TASK, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                         settings_paths=[], post=hook.post, worker=worker, chatgpt=chatgpt, codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=wait,
                         slots=list(slots), claude_ready=ready, out=lines.append)
    return code, "\n".join(lines), log.recent_tasks(conn)[0], worker, chatgpt


def _rows(conn, row):
    return [(c["kind"], c["stage"], c["role"], c["agent"], c["status"]) for c in log.calls_for(conn, row["task_id"])]


# ---------- the chain ----------

def test_a_full_chain_writes_build_attack_revise_and_check_rows(conn):
    code, out, row, worker, chat = _relay(conn, claude=[BUILD, REVISION], chat=[ATTACKS, "PASS"])
    assert code == 0, out
    assert _rows(conn, row) == [("stage", 1, "build", "claude", "done"), ("stage", 2, "attack", "chatgpt", "done"),
                                ("stage", 3, "revise", "claude", "done"), ("check", None, None, "chatgpt", "done")]
    assert (row["status"], row["check_state"], row["agent"], row["checker"]) == ("done", "passed", "claude", "chatgpt")
    assert json.loads(row["slots"]) == {"build": "claude", "attack": "chatgpt", "check": "chatgpt"}


def test_each_stage_gets_exactly_its_inputs(conn):
    code, out, row, worker, chat = _relay(conn, claude=[BUILD, REVISION], chat=[ATTACKS, "PASS"])
    build, revise = worker.prompts
    attack, check = chat.prompts
    assert build == relay.prompt_for("build", TASK, None, task_alone=True, deliverable_shape=True)
    assert attack == relay.prompt_for("attack", TASK, BUILD, search=True)
    assert revise == relay.revise_prompt(TASK, BUILD, against=ATTACKS)
    assert revise.count(BUILD) == 1 and revise.count(ATTACKS) == 1 and "PASS" not in revise


def test_the_checker_gets_the_whole_revision_and_the_attack_list_once_labeled_apart(conn):
    code, out, row, worker, chat = _relay(conn, claude=[BUILD, REVISION], chat=[ATTACKS, "PASS"])
    check = chat.prompts[1]
    assert check == checking.checker_prompt(TASK, REVISION, no_tools=False, can_browse=True, relay=True, search=True,
                                            attacks=ATTACKS)
    assert check.count(ATTACKS) == 1 and checking._block(checking.ATTACKS_LABEL, ATTACKS) in check
    assert check.index("===== RESULT =====") < check.index(f"===== {checking.ATTACKS_LABEL} =====")
    for words in ("[high] attack that is neither fixed", "Do not fail it for an open [medium] or [low] attack",
                  "Do not add attacks of your own", "name the attack by its number"):
        assert words in check, words


def test_the_tasks_result_is_the_deliverable_without_answered(conn):
    code, out, row, *_ = _relay(conn, claude=[BUILD, REVISION], chat=[ATTACKS, "PASS"])
    assert row["result"] == DELIVERED and "## Answered" not in row["result"]


def test_the_finish_and_sr_show_print_the_attacks_and_the_answered_section_under_the_result(conn):
    code, out, row, *_ = _relay(conn, claude=[BUILD, REVISION], chat=[ATTACKS, "PASS"])
    assert out.index(DELIVERED) < out.index("--- attacks ---") < out.index("--- answered ---")
    assert ATTACKS in out and "3. Sunday is the user's choice" in out
    lines = []
    cli.cmd_show(conn=conn, words=[str(row["n"])], roster=ROSTER, presets=LOADED, out=lines.append)
    shown = "\n".join(lines)
    assert shown.index(DELIVERED) < shown.index("--- attacks ---") < shown.index(ATTACKS) < shown.index("--- answered ---")
    lines = []
    cli.cmd_show(conn=conn, words=[str(row["n"])], roster=ROSTER, presets=LOADED, stages=True, out=lines.append)
    shown = "\n".join(lines)
    assert "stage 1 build by claude: done" in shown and "stage 2 attack by chatgpt: done" in shown
    assert "stage 3 revise by claude: done" in shown


def test_sr_log_shows_the_preset_like_the_others(conn):
    code, out, row, *_ = _relay(conn, claude=[BUILD, REVISION], chat=[ATTACKS, "PASS"])
    assert cli._skill_text(row) == "relay:redteam"


# ---------- the fix round (decision 8) ----------

def test_a_fail_naming_attack_1_sends_the_fix_round_to_the_build_agent_with_the_attack_list(conn):
    fixed = REVISION.replace("Change the budget", "Change it")
    code, out, row, worker, chat = _relay(conn, claude=[BUILD, REVISION, fixed],
                                          chat=[ATTACKS, "FIX\n1. Attack 1 is neither fixed nor answered.", "PASS"])
    assert code == 0, out
    fix = worker.prompts[2]
    assert fix == checking.fix_prompt(TASK, REVISION, "1. Attack 1 is neither fixed nor answered.", prior=ATTACKS,
                                      prior_label=relay.ATTACK_LIST_LABEL, prior_lines=[relay.REDTEAM_FIX_LINE],
                                      count=True)
    assert chat.prompts[2] == checking.checker_prompt(TASK, fixed, no_tools=False, can_browse=True, relay=True,
                                                      search=True, attacks=ATTACKS)
    assert (row["check_state"], row["result"]) == ("fixed", fixed.split("\n\n## Answered")[0])


# ---------- re-asks and stops ----------

def test_a_thin_attack_list_gets_one_re_ask_then_the_chain_goes_on(conn):
    thin = "## Attacks\n1. [high] One thing.\n\n## Strongest\nOne thing."
    code, out, row, worker, chat = _relay(conn, claude=[BUILD, REVISION], chat=[thin, ATTACKS, "PASS"])
    assert code == 0 and [r[:3] for r in _rows(conn, row)][:3] == [("stage", 1, "build"), ("stage", 2, "attack"),
                                                                   ("reask", 2, "attack")]
    assert "Attacks: need 3 numbered items with a severity, found 1" in chat.prompts[1]
    assert relay.ATTACK_SHAPE in chat.prompts[1]


def test_an_attack_list_still_missing_after_the_re_ask_stops_the_chain_at_stage_2(conn):
    thin = "## Attacks\n1. [high] One thing.\n\n## Strongest\nOne thing."
    code, out, row, worker, chat = _relay(conn, claude=[BUILD], chat=[thin, thin])
    assert code == 1 and (row["status"], row["failed_stage"]) == ("failed", 2)
    assert "contract still missing after the re-ask" in row["result"]


def test_answering_an_attack_not_in_the_list_is_re_asked_with_the_numbers(conn):
    bad = REVISION.replace("3. Sunday", "7. Sunday")
    code, out, row, worker, chat = _relay(conn, claude=[BUILD, bad, REVISION], chat=[ATTACKS, "PASS"])
    assert code == 0, out
    assert "Answered: attack 7 is not in the attack list (1, 2, 3)" in worker.prompts[2]
    assert relay.REVISE_REPLY in worker.prompts[2]


def test_the_build_stage_misses_its_deliverable_contract_and_is_re_asked_for_the_redteam_shape(conn):
    code, out, row, worker, chat = _relay(conn, claude=["Just a plan.", BUILD, REVISION], chat=[ATTACKS, "PASS"])
    assert code == 0 and relay.TASK_DELIVERABLE_LINE in worker.prompts[1]


# ---------- search ----------

class Searching(Scripted):
    def __call__(self, prompt, **kw):
        from router import claude_worker
        text = super().__call__(prompt)
        return claude_worker.SearchAnswer(text, ["q"]) if kw.get("search") else text


def test_search_is_on_for_every_stage_and_the_prompts_differ_only_by_the_search_line(conn):
    hook, worker, chatgpt, clock = RelayHook(), Searching(BUILD, REVISION), Chat(ATTACKS, "PASS"), Clock()
    cli.cmd_relay("redteam", TASK, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                  settings_paths=[], post=hook.post, worker=worker, chatgpt=chatgpt, codex_login=lambda: True,
                  fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True,
                  claude_ready=lambda *a: True, out=lambda *_: None)
    row = log.recent_tasks(conn)[0]
    assert [json.loads(c["search"])["state"] for c in log.calls_for(conn, row["task_id"])] == ["allowed"] * 4
    line = "\n\n" + checking.SEARCH_LINE_GENERAL
    assert worker.prompts[1].replace(line, "", 1) == relay.revise_prompt(TASK, BUILD, against=ATTACKS)
    assert worker.prompts[0].replace(line, "", 1) == relay.prompt_for("build", TASK, None, task_alone=True,
                                                                         deliverable_shape=True)
    assert chatgpt.prompts[0].replace(line, "", 1) == relay.prompt_for("attack", TASK, BUILD)


def test_the_other_presets_checker_prompt_is_unchanged_without_an_attack_list():
    assert checking.checker_prompt("t", "r", no_tools=True, relay=True) == checking.checker_prompt(
        "t", "r", no_tools=True, relay=True, attacks=None)
