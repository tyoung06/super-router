"""Build brief 15, phase C: a no-flag relay run of each preset with fake agents, recorded as plain data (every
prompt each agent got, every row) so it can be compared byte for byte with the same run on the code before slots.
`tests/fixtures/relay_no_flag_v9.json` was made by running `snapshot()` against `main` at a260d48 (log version 9).
Not a test file itself: tests/test_slots_readers.py compares. Every value here is fake."""
from router import __main__ as cli
from router import log, presets, relay
from tests.helpers import shipped_roster
from tests.test_relay import CONFIG, GOOD_NOTE, THIN, Chat, Clock, RelayHook, Scripted

TASK = "Write a three-line note on garden seed trays, with one source."
PLAN = "## Plan\n1. Pick the three points.\n2. Write the lines.\n3. Add the source.\n\n## Open questions\nnone"
AMENDED = "## Changes\nnone\n\n## Plan\n1. Pick the three points.\n2. Write the lines.\n3. Add the source."
DELIVERABLE = "## Deliverable\nLine one.\nLine two.\nLine three.\n\n## Unfinished\nnone"
EDITED = "## Deliverable\nLine one.\nLine two.\nLine three.\n\n## Edits\nnone\n\n## Unresolved\nnone"
REVIEW = "## Verdict\npass\n\n## Notes\n- clear"

SCENARIOS = {
    # name: (preset, grok bodies by call key, claude replies, chatgpt replies)
    "research-build": ("research-build", {"s1": GOOD_NOTE}, ["A built result.", "The fixed result."],
                       ["FIX\n1. Name the source.", "PASS"]),
    "research-build-reask": ("research-build", {"s1": THIN, "s1r": GOOD_NOTE}, ["A built result."], ["PASS"]),
    "collab": ("collab", {}, [PLAN, DELIVERABLE], [AMENDED, EDITED]),
    "versus": ("versus", {}, ["A's note.", REVIEW], ["B's note.", REVIEW]),
}
ROW_SKIP = ("created_at", "updated_at", "sent_at", "n")
CALL_SKIP = ("sent_at", "finished_at", "run_uuid", "url")


def _clean(value, task_id):
    return value.replace(task_id, "TASK") if isinstance(value, str) else value


def run(name, slots=None):
    preset_name, bodies, claude, chat = SCENARIOS[name]
    roster = shipped_roster()
    loaded = presets.load_presets(roster, tuple(cli.SENDERS), relay.CONTRACTS, roles=relay.ROLES,
                                  verdicts=relay.VERDICTS)
    conn = log.init_db(":memory:")
    hook, worker, chatgpt, clock, lines = RelayHook(**bodies), Scripted(*claude), Chat(*chat), Clock(), []
    extra = {} if slots is None else {"slots": slots}
    code = cli.cmd_relay(preset_name, TASK, conn=conn, config=CONFIG, roster=roster, loaded=loaded, environ={},
                         settings_paths=[], post=hook.post, worker=worker, chatgpt=chatgpt, codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True,
                         out=lines.append, **extra)
    row = log.recent_tasks(conn)[0]
    tid = row["task_id"]
    calls = log.calls_for(conn, tid)
    record = {
        "code": code,
        "out": [_clean(line, tid) for line in lines],
        "grok": [{k: _clean(v, tid) for k, v in sent.items()} for sent in hook.sent],
        "claude": [_clean(p, tid) for p in worker.prompts],
        "chatgpt": [_clean(p, tid) for p in chatgpt.prompts],
        "chatgpt_kwargs": chatgpt.kwargs,
        "task": {k: _clean(row[k], tid) for k in row.keys() if k not in ROW_SKIP},
        "calls": [{k: _clean(c[k], tid) for k in c.keys() if k not in CALL_SKIP} for c in calls],
    }
    conn.close()
    return record


def snapshot():
    return {name: run(name) for name in SCENARIOS}
