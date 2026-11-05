"""Brief 29.1 (decision 10, the owner's D18 fix 2): `--project` is taken on vote. Each voter gets the project's handoff and the
memory block as data; there is no copy and no file mode, with git or without; the tally is as today; a delivered answer's
handoff entry is the router's one line (the question, the answer and its tally), since no voter owns a handoff section. A
Grok voter's handoff is cut to fit its limit as Project context says. Fakes only; every value fake."""
from router import __main__ as cli
from router import copies, log, projects
from tests.test_context import HANDOFF_TEXT, project  # noqa: F401 (the fixture)
from tests.test_vote_run import LOADED, ROSTER, TASK, A, B, G, FRANCE, conn, vote, World  # noqa: F401
from tests.test_relay import CONFIG


def _vote(conn, world, project="demo", wait=True, slots=()):
    code = cli.cmd_relay("vote", TASK, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[],
                         post=world.hook.post, worker=world.worker, chatgpt=world.chat, codex_login=lambda: True,
                         fetch=world.hook.fetch, close=world.hook.close, sleep=world.clock.sleep, clock=world.clock,
                         wait=wait, slots=list(slots), out=world.lines.append, project=project)
    return code, log.recent_tasks(conn)[0]


def test_every_voter_gets_the_handoff_and_the_router_writes_the_one_line_entry(project, conn):
    world = World(claude=(A,), chatgpt=(B,), grok={"s3": G})
    code, row = _vote(conn, world)
    assert code == 0, world.out
    row = log.get_task(conn, row["task_id"])
    assert row["status"] == "done" and row["check_note"] == "checked-by-vote 3/0"
    assert "===== project handoff: demo =====" in world.worker.prompts[0]
    assert "===== project handoff: demo =====" in world.chat.prompts[0]
    assert "===== project handoff: demo =====" in world.hook.sent[0]["task"]
    assert log.project_files_of(row) is None and not copies.exists(row["task_id"])  # no copy, no file mode
    entry = projects.entries_of((project / "HANDOFF.md").read_text())[0]
    assert entry == (f"### #{row['n']} · {cli._now():%Y-%m-%d} · vote: Which of these is the largest by land area: Texas, "
                     "France, or Spain? Answer with the name only. → Texas (checked-by-vote 3/0)")


def test_a_tie_picked_by_hand_writes_its_answer_and_the_pick(project, conn):
    world = World(claude=(A,), chatgpt=(FRANCE,), grok={"s3": vote("Spain")})
    code, row = _vote(conn, world)
    assert log.get_task(conn, row["task_id"])["check_note"] == log.AWAITING_PICK
    assert cli.cmd_pick([str(row["n"]), "b"], conn=conn, loaded=LOADED, out=world.lines.append) == 0
    entry = projects.entries_of((project / "HANDOFF.md").read_text())[0]
    assert entry.endswith("· vote: Which of these is the largest by land area: Texas, France, or Spain? Answer with the "
                          "name only. → France (picked B; no majority)")


def test_a_grok_voters_handoff_is_cut_to_fit_its_limit(project, conn, monkeypatch):
    long = HANDOFF_TEXT.replace("The owner's note one.", "The owner's note one. " + "x" * 3000)
    (project / "HANDOFF.md").write_text(long)
    world = World(claude=(A,), chatgpt=(B,), grok={"s3": G})
    code, row = _vote(conn, world)
    assert code == 0, world.out
    sent = world.hook.sent[0]["task"]
    assert len(sent) <= 3662 and "x" * 3000 not in sent
    grok = next(c for c in log.calls_for(conn, row["task_id"]) if c["agent"] == "grok")
    record = log.context_of(grok)
    assert record["lines"] < record["total"]  # the owner's part was cut from its top


def test_status_says_vote_takes_a_project(conn):
    from router import presets
    assert all(presets.takes_project(p) for p in LOADED.presets.values())  # decision 27: true for all five
