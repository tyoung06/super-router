"""Build brief 33.1 (Tests, Prompts): a plan's prompts recorded as plain data, so a run can be compared byte for byte with
the same run on later code. One run: `sr plan` on a project (Claude plans, ChatGPT and Cursor attack, Claude revises,
ChatGPT's check asks for a fix, Claude's fix round, ChatGPT's re-check passes), the plan lands, then step 1 is routed
with `--step` (Claude builds it with the STEP block, ChatGPT checks it with the step's check line).
`tests/fixtures/plan_prompts_33_1.json` is `snapshot(...)` on this brief's code; tests/test_plan_snapshot.py compares.
Needs the `project`, `conn` and `runner` fixtures of tests/test_filemode_flow.py. Not a test file itself. Every value
here is fake."""
import re

from router import __main__ as cli
from router import log, plan
from tests.helpers import today
from tests.test_cursor_send import Cursor, answer
from tests.test_filemode_flow import CopyWorker
from tests.test_plan_approval import _land
from tests.test_plan_chain import A_LIST, B_LIST, REVISED, ReadWorker, World
from tests.test_plan_contract import GOOD
from tests.test_plan_steps import SKELETON, _route_step
from tests.test_relay import Chat

FIX_LIST = "FIX\n1. [must] Step 2's done-when names no file."
FIXED = REVISED.replace("## Answered\n", "## Answered\nA1: step 2's done-when now names its test file\n", 1)
_ID = re.compile(r"sr-\d{8}-\d{6}-[0-9a-f]{4}")


def _clean(prompts, tmp):
    date = today()
    # Brief 33.4 (decision 3) adds one line to a new plan's stage-1 prompt, the one prompt it changes in these runs; the
    # older snapshots hold byte for byte without it, and plan_prompts_33_4.json records it
    return [_ID.sub("TASK", p).replace(str(tmp), "<TMP>").replace(date, "<DATE>").replace(plan.QUESTIONS_LINE + "\n\n", "")
            for p in prompts]


def snapshot(conn, tmp):
    """{"plan": {agent: [prompt, …]}, "step": {agent: [prompt, …]}, "rows": …}; `tmp` is the test's tmp_path."""
    w = World(worker=ReadWorker(GOOD, REVISED, FIXED), chat=Chat(A_LIST, FIX_LIST, "PASS"), cursor=Cursor(answer(B_LIST)))
    code, row = w.plan(conn)
    assert code == 0, w.said
    found = {"plan": {"claude": _clean([c["prompt"] for c in w.worker.calls], tmp), "chatgpt": _clean(w.chat.prompts, tmp),
                      "cursor": _clean(w.cursor.prompts, tmp)}}
    rows = [[c["kind"], c["stage"], c["role"], c["agent"], c["status"]] for c in log.calls_for(conn, row["task_id"])]
    code, said = _land(conn, log.get_task(conn, row["task_id"]))
    assert code == 0, said
    worker, chat = CopyWorker(SKELETON), Chat("PASS")
    code, said, step = _route_step(conn, f"{row['n']}:1", worker=worker, chatgpt=chat)
    assert code == 0, said
    found["step"] = {"claude": _clean([c["prompt"] for c in worker.calls], tmp), "chatgpt": _clean(chat.prompts, tmp)}
    found["rows"] = {"plan": rows, "step": [[c["kind"], c["stage"], c["role"], c["agent"], c["status"]]
                                            for c in log.calls_for(conn, step["task_id"])]}
    return found


# ---------- brief 33.4 (§4 Prompts): the new prompts' run ----------

def snapshot_334(conn, tmp):
    """Brief 33.4's run, recorded as `tests/fixtures/plan_prompts_33_4.json`: a new plan asks (the Questions words), the owner
    answers with one pick and one typed line, the plan runs (the answers block on the planner's next call, both attacks,
    the revise and the check), and last a suggest on the project with one idea already there."""
    from router import ideas
    from tests.test_answers334 import _answer
    from tests.test_questions334 import QUESTIONS
    from tests.test_suggest334 import Claude, _suggest

    def kept(prompts):
        date = today()
        return [_ID.sub("TASK", p).replace(str(tmp), "<TMP>").replace(date, "<DATE>") for p in prompts]
    w = World(worker=ReadWorker(QUESTIONS, GOOD, REVISED), chat=Chat(A_LIST, "PASS"), cursor=Cursor(answer(B_LIST)))
    code, row = w.plan(conn)
    assert code == 0, w.said
    code, said, row = _answer(w, conn, log.get_task(conn, row["task_id"]), picks=["1=B"], others=["2=with flags"])
    assert code == 0, said
    found = {"plan": {"claude": kept([c["prompt"] for c in w.worker.calls]), "chatgpt": kept(w.chat.prompts),
                      "cursor": kept(w.cursor.prompts)},
             "rows": [[c["kind"], c["stage"], c["role"], c["agent"], c["status"]] for c in log.calls_for(conn, row["task_id"])]}
    code, said = _land(conn, log.get_task(conn, row["task_id"]))
    assert code == 0, said
    ideas.add(conn, "garden", "An idea already there")
    worker = Claude()
    code, said, _ = _suggest(conn, worker)
    assert code == 0, said
    found["suggest"] = kept(worker.prompts)
    return found


# ---------- brief 33.2 (§4 Prompts): the new prompts' run ----------

def snapshot_332(conn, tmp, project):
    """Brief 33.2's run, recorded as `tests/fixtures/plan_prompts_33_2.json`: the project has SPEC.md (the spec block on every
    call, `covers:` in the shape), a plan whose check asks for a fix (plan, two attacks, revise, check, fix, re-check), the
    plan lands, step 1 is routed with `--step` (the STEP block quotes its example; no change, so step 2 stays open), then
    Add to plan: an idea sent as a revision (`PLAN SO FAR`, `## Changed`, the keep-unless words), and last the Draft chip's
    task, a routed `--no-files` task with the chip's text. `project` is the test's project folder."""
    from router import ideas, receipt
    from tests.test_covers332 import COVERED, REVISED
    from tests.test_plan_steps import RESEARCH
    from tests.test_review332 import REV_SPEC, REV_SPEC_ANSWERED
    from tests.test_spec332 import _commit_spec
    _commit_spec(project)
    fixed = REVISED.replace("## Answered\n", "## Answered\nA1: step 2's done-when now names its test file\n", 1)
    w = World(worker=ReadWorker(COVERED, REVISED, fixed), chat=Chat(A_LIST, FIX_LIST, "PASS"), cursor=Cursor(answer(B_LIST)))
    code, row = w.plan(conn)
    assert code == 0, w.said
    found = {"plan": {"claude": _clean([c["prompt"] for c in w.worker.calls], tmp), "chatgpt": _clean(w.chat.prompts, tmp),
                      "cursor": _clean(w.cursor.prompts, tmp)}}
    rows = {"plan": [[c["kind"], c["stage"], c["role"], c["agent"], c["status"]] for c in log.calls_for(conn, row["task_id"])]}
    code, said = _land(conn, log.get_task(conn, row["task_id"]))
    assert code == 0, said
    worker, chat = CopyWorker(RESEARCH), Chat("PASS")
    code, said, step = _route_step(conn, f"{row['n']}:1", worker=worker, chatgpt=chat)
    assert code == 0, said
    found["step"] = {"claude": _clean([c["prompt"] for c in worker.calls], tmp), "chatgpt": _clean(chat.prompts, tmp)}
    rows["step"] = [[c["kind"], c["stage"], c["role"], c["agent"], c["status"]] for c in log.calls_for(conn, step["task_id"])]
    out = receipt.Receipt()
    assert cli.cmd_ideas(["garden"], conn=conn, add=True, text="Add c_to_k(c) to conv.py with a unittest.", out=out) == 0, out.message
    idea = ideas.all_of(conn, "garden")[0]
    w2 = World(worker=ReadWorker(REV_SPEC, REV_SPEC_ANSWERED), chat=Chat(A_LIST, "PASS"), cursor=Cursor(answer(B_LIST)))
    code, rev = w2.plan(conn, task=idea.text, idea_ref=str(idea.id))
    assert code == 0, w2.said
    found["revision"] = {"claude": _clean([c["prompt"] for c in w2.worker.calls], tmp), "chatgpt": _clean(w2.chat.prompts, tmp),
                         "cursor": _clean(w2.cursor.prompts, tmp)}
    rows["revision"] = [[c["kind"], c["stage"], c["role"], c["agent"], c["status"]] for c in log.calls_for(conn, rev["task_id"])]
    code, said = _land(conn, log.get_task(conn, rev["task_id"]), verb="discard")  # the project is free for the Draft task
    assert code == 0, said
    worker, chat = CopyWorker(("# Converter\n\nA draft.\n\n## Handoff\n### Produced\nnothing: text only\n### Status\ndrafted\n### Next\nsave it", {})), Chat("PASS")
    code, said, draft = _route_draft(conn, worker=worker, chatgpt=chat)
    assert code == 0, said
    found["draft"] = {"claude": _clean([c["prompt"] for c in worker.calls], tmp), "chatgpt": _clean(chat.prompts, tmp)}
    rows["draft"] = [[c["kind"], c["stage"], c["role"], c["agent"], c["status"]] for c in log.calls_for(conn, draft["task_id"])]
    found["rows"] = rows
    return found


def _route_draft(conn, *, worker, chatgpt):
    """The Draft chip's task as the page sends it: `sr route --project garden --no-files` with the chip's text."""
    from router import projspec
    from tests.helpers import fake_label
    from tests.test_filemode_flow import CODE, CONFIG, ROSTER, Clock, Webhook
    lines, clock, hook = [], Clock(), Webhook()
    code = cli.cmd_route(projspec.DRAFT_TEXT, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                         label=fake_label(CODE), post=hook.post, worker=worker, chatgpt=chatgpt, codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True, out=lines.append,
                         project="garden", files_ready=lambda: (True, None), no_files=True)
    return code, "\n".join(lines), log.recent_tasks(conn)[0]
