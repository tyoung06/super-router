"""Build brief 32 (Tests, Prompts): redteam runs with fake agents, every prompt each agent got recorded as plain data, so
a run can be compared byte for byte with the same run on other code. Two runs: a check that fails, its fix round and a
passing re-check; and a re-check that fails too, then `sr fallback` (the checker redoes it, the builder checks).
`tests/fixtures/redteam_prompts_v1_6.json` is `snapshot(<presets 1.6>)` run on `main` at c030f8e (one attack list, before
this brief); `tests/fixtures/redteam_prompts_v1_7.json` is `snapshot(<presets 1.7>, cursor=...)` on this brief's code
(two lists, labeled); `tests/fixtures/redteam_prompts_v1_7_one_list.json` is presets 1.7 with the second attack left out
(one labeled list, the design chat's D fix of 29 Oct). tests/test_redteam2_snapshot.py compares. Not a test file itself.
Every value here is fake."""
import re

from router import __main__ as cli
from router import log
from tests.helpers import shipped_roster, today
from tests.test_relay import CONFIG, Chat, Clock, RelayHook, Scripted

TASK = "Write a one-page plan for a weekly budget review ritual. Plain text, under 400 words."
BUILD = "## Deliverable\nReview on Sundays at 6pm.\nCheck groceries.\n\n## Unfinished\nnone"
A_LIST = ("## Attacks\n1. [high] No trigger for a change is defined.\n2. [medium] Groceries only.\n"
          "3. [low] Sunday may clash with plans.\n\n## Strongest\nNo trigger for a change is defined.")
B_LIST = ("## Attacks\n1. [high] Nothing says who reviews when the owner is away.\n2. [medium] The plan never says where "
          "the numbers come from.\n3. [low] 6pm says no time zone.\n\n## Strongest\nNobody reviews when the owner is away.")
PLAN = ("Review on Sundays at 6pm.\nCheck groceries, rent and fun money.\nChange the budget when a line is 10% over two "
        "weeks running.")
REDO = "A plan written from the task and the attacks.\n\n## Answered\nnone"
# what each run's agents answer: one list (presets 1.6, answered by number) or two (1.7, answered by label)
ONE = {"revision": PLAN + "\n\n## Answered\n3. Sunday is the user's choice; the plan says to move it if needed.",
       "fix_list": "FIX\n1. [must] Attack 1 is neither fixed nor answered.",
       "fixed": PLAN.replace("Change the budget", "Change it") + "\n\n## Answered\n3. Sunday is the user's choice.",
       "still": "FIX\n1. not fixed: Attack 1 still open."}
# presets 1.7 with the second attack left out: one labeled list, answered by label (the design chat's D fix of 29 Oct)
ONE_LABELED = {"revision": PLAN + "\n\n## Answered\nA3: Sunday is the user's choice; the plan says to move it if needed.",
               "fix_list": "FIX\n1. [must] A1 is neither fixed nor answered.",
               "fixed": PLAN.replace("Change the budget", "Change it") + "\n\n## Answered\nA3: Sunday is the user's choice.",
               "still": "FIX\n1. not fixed: A1 still open."}
TWO = {"revision": PLAN + "\n\n## Answered\nA3: Sunday is the user's choice; the plan says to move it if needed.\n"
                          "B3: The owner's own clock is the plan's.",
       "fix_list": "FIX\n1. [must] A1 is neither fixed nor answered; B1 neither.",
       "fixed": PLAN.replace("Change the budget", "Change it") + "\n\n## Answered\nA3: Sunday is the user's choice.\n"
                                                                  "B1: The owner is the only reviewer.",
       "still": "FIX\n1. not fixed: A1 still open."}
_ID = re.compile(r"sr-\d{8}-\d{6}-[0-9a-f]{4}")


def _clean(prompts):
    date = today()
    return [_ID.sub("TASK", p).replace(date, "<DATE>") for p in prompts]


def _relay(conn, loaded, claude, chat, cursor, cursor_ready):
    hook, worker, chatgpt, clock = RelayHook(), Scripted(*claude), Chat(*chat), Clock()
    cli.cmd_relay("redteam", TASK, conn=conn, config=CONFIG, roster=shipped_roster(), loaded=loaded, environ={},
                  settings_paths=[], post=hook.post, worker=worker, chatgpt=chatgpt, codex_login=lambda: True,
                  fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True, cursor=cursor,
                  cursor_ready=cursor_ready, out=lambda line: None)
    return log.recent_tasks(conn)[0], worker, chatgpt


def _fallback(conn, loaded, row, claude, chat):
    hook, worker, chatgpt, clock = RelayHook(), Scripted(*claude), Chat(*chat), Clock()
    cli.cmd_fallback([str(row["n"])], conn=conn, config=CONFIG, roster=shipped_roster(), loaded=loaded, environ={},
                     settings_paths=[], post=hook.post, worker=worker, chatgpt=chatgpt, codex_login=lambda: True,
                     fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True, out=lambda line: None)
    return worker, chatgpt


def snapshot(loaded, *, cursor=None, cursor_ready=None, words=None):
    """{run: {agent: [prompt, …]}}; `cursor` makes a fresh fake Cursor per run (presets 1.7's second attack), or None;
    `words` what the agents answer (ONE_LABELED when Cursor is left out on 1.7)."""
    words = words or (TWO if cursor is not None else ONE)
    found = {}
    for name, recheck in (("fixed", "PASS"), ("fallback", words["still"])):
        conn = log.init_db(":memory:")
        try:
            agent = cursor() if cursor is not None else None
            row, worker, chat = _relay(conn, loaded, [BUILD, words["revision"], words["fixed"]],
                                       [A_LIST, words["fix_list"], recheck], agent, cursor_ready)
            run = {"claude": _clean(worker.prompts), "chatgpt": _clean(chat.prompts)}
            if agent is not None:
                run["cursor"] = _clean(agent.prompts)
            if name == "fallback":
                worker, chat = _fallback(conn, loaded, row, ["PASS"], [REDO])
                run["fallback"] = {"claude": _clean(worker.prompts), "chatgpt": _clean(chat.prompts)}
            run["rows"] = [[c["kind"], c["stage"], c["role"], c["agent"], c["status"]]
                           for c in log.calls_for(conn, row["task_id"])]
            found[name] = run
        finally:
            conn.close()
    return found
