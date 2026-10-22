"""Build brief 17, phase D (rules v2.24): `sr pick <n> a|b|c|none` on a vote with no majority (decision 9), what a
vote refuses (decision 10: resume, fallback, override, --project), and what the owner sees (decision 11): `sr show`
with the answer, every voter with the dissent first, `--stages`, and `sr log`. Every value here is fake."""
import pytest

from router import __main__ as cli
from router import fallback, log, presets, relay, resume
from tests.test_relay import CONFIG
from tests.test_vote_run import A, B, FRANCE, G, LOADED, ROSTER, World, vote

SPAIN = vote("Spain", why="GROK-SPAIN-x85 Smallest of the three.", confidence="20")


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


def _tie(conn):
    w = World(claude=[A], chatgpt=[FRANCE], grok={"s3": SPAIN})
    w.relay(conn)
    w.check(conn)
    row = log.recent_tasks(conn)[0]
    assert relay.awaiting_pick(row)
    return row


def _majority(conn, answers=(FRANCE, B, G)):
    w = World(claude=[answers[0]], chatgpt=[answers[1]], grok={"s3": answers[2]})
    w.relay(conn)
    w.check(conn)
    return log.recent_tasks(conn)[0]


def _pick(conn, row, choice):
    lines = []
    code = cli.cmd_pick([str(row["n"]), choice], conn=conn, loaded=LOADED, out=lines.append)
    return code, "\n".join(lines), log.get_task(conn, row["task_id"])


def _show(conn, row, stages=False):
    lines = []
    code = cli.cmd_show(conn=conn, words=[str(row["n"])], stages=stages, roster=ROSTER, presets=LOADED,
                        out=lines.append)
    return code, "\n".join(lines)


# ---------- sr pick (decision 9) ----------

@pytest.mark.parametrize("choice, stage, agent, text", [("a", 1, "claude", A), ("b", 2, "chatgpt", FRANCE),
                                                        ("c", 3, "grok", SPAIN)])
def test_a_pick_delivers_that_voters_raw_result_unchecked(conn, choice, stage, agent, text):
    row = _tie(conn)
    code, out, after = _pick(conn, row, choice)
    assert code == 0, out
    assert (after["status"], after["result"], after["check_state"], after["check_note"], after["agent"],
            after["checker"]) == ("done", text, "unchecked", f"picked {choice}; no majority", agent, None)
    assert f"picked {choice.upper()} ({agent})" in out and "unchecked" in out


def test_none_fails_the_task_with_every_answer_kept(conn):
    row = _tie(conn)
    code, out, after = _pick(conn, row, "none")
    assert code == 0
    assert (after["status"], after["check_note"], after["agent"], after["checker"], after["check_state"]) == (
        "failed", "picked none; no majority", None, None, None)
    assert len([c for c in log.calls_for(conn, row["task_id"]) if c["kind"] == "stage"]) == 3


def test_a_second_pick_is_refused(conn):
    row = _tie(conn)
    _pick(conn, row, "a")
    code, out, after = _pick(conn, row, "b")
    assert code == 2 and "already picked: a" in out and after["check_note"] == "picked a; no majority"


def test_a_pick_on_a_vote_decided_by_majority_is_refused(conn):
    row = _majority(conn)
    before = dict(row)
    code, out, after = _pick(conn, row, "a")
    assert code == 2
    assert f"Refused: #{row['n']} already decided by vote 2/1. Nothing was changed." in out
    assert dict(after) == before


def test_c_on_a_versus_task_is_refused(conn):
    row = _versus_awaiting(conn)
    code, out, after = _pick(conn, row, "c")
    assert code == 2 and f"Refused: #{row['n']} is not a vote task; c is the third voter on a vote." in out
    assert relay.awaiting_pick(after)


def test_an_unknown_letter_on_a_vote_is_refused(conn):
    row = _tie(conn)
    code, out, after = _pick(conn, row, "d")
    assert code == 2 and "pick a, b, c or none" in out and relay.awaiting_pick(after)


def test_a_pick_on_a_vote_still_running_is_refused(conn):
    w = World(claude=[A], chatgpt=[B], grok={})
    w.relay(conn)
    row = log.recent_tasks(conn)[0]
    code, out, after = _pick(conn, row, "a")
    assert code == 2 and "is not awaiting a pick" in out


def _versus_awaiting(conn):
    from tests.test_relay import Chat, Clock, RelayHook
    review = "## Verdict\npass\n\n## Notes\n- fine"
    hook, clock = RelayHook(), Clock()
    cli.cmd_relay("versus", "Write a tagline.", conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                  settings_paths=[], post=hook.post, worker=Chat("A's line.", review),
                  chatgpt=Chat("B's line.", review), codex_login=lambda: True, fetch=hook.fetch, close=hook.close,
                  sleep=clock.sleep, clock=clock, wait=False, out=lambda *_: None)
    return log.recent_tasks(conn)[0]


# ---------- what a vote refuses (decision 10) ----------

def test_a_vote_is_never_resumed(conn):
    from router.chatgpt_worker import WorkerError
    w = World(claude=[A], chatgpt=[WorkerError("You've hit your usage limit", code="plan_limit")])
    w.relay(conn)
    row = log.recent_tasks(conn)[0]
    preset = presets.for_task(row, LOADED)[0]
    plan = resume.decide(row, log.calls_for(conn, row["task_id"]), live=ROSTER.live, preset=preset)
    assert not plan.ok and plan.reason == "vote task: the substitute is already a voter"
    assert "Not resumable: vote task: the substitute is already a voter" in w.out


def test_a_vote_never_falls_back(conn):
    row = _majority(conn)
    preset = presets.for_task(row, LOADED)[0]
    plan = fallback.decide(row, log.calls_for(conn, row["task_id"]), live=ROSTER.live, preset=preset)
    assert not plan.ok and plan.reason == "not eligible: a vote task; nothing checked it, so nothing failed it"


def test_an_override_prefix_on_a_vote_is_refused(conn):
    w = World()
    code, row = w.relay(conn, task="@claude Yes or no?")
    assert code == 2 and row is None and "an override prefix on a relay task is refused (@claude)" in w.out


def test_project_on_a_vote_is_refused_with_no_row(monkeypatch, capsys):
    # --project is not built on any command yet (brief 12); on relay it reads as a slot vote does not have
    monkeypatch.setattr(cli.safety, "prepare_workspace", lambda *a, **k: None)
    monkeypatch.setattr(cli, "dotenv_values", lambda *_: dict(CONFIG))
    assert cli.main(["relay", "vote", "Yes or no?", "--project", "budget"], platform="darwin") == 2
    assert "Nothing was logged or sent." in capsys.readouterr().out
    c = log.init_db(cli.DB_PATH)
    assert log.recent_tasks(c) == []
    c.close()


# ---------- sr show, --stages, sr log (decision 11) ----------

def test_show_on_a_2_1_vote_prints_the_answer_then_the_dissent_first(conn):
    row = _majority(conn)
    code, out = _show(conn, row)
    assert code == 0
    assert "Answer: texas. (checked-by-vote 2/1)" in out
    dissent, b, c = out.index("A — claude (dissent): France · confidence 40"), out.index("B — chatgpt: texas."), \
        out.index("C — grok: **Texas**")
    assert dissent < b < c
    assert "DISSENT-x84 Metropolitan France only." in out and "GROK-WHY-x83" in out
    assert "Pick:" not in out


def test_show_on_a_3_0_vote_prints_the_voters_in_order(conn):
    row = _majority(conn, answers=(A, B, G))
    code, out = _show(conn, row)
    assert "Answer: Texas (checked-by-vote 3/0)" in out and "(dissent)" not in out
    assert out.index("A — claude") < out.index("B — chatgpt") < out.index("C — grok")


def test_show_on_a_tie_waits_and_names_the_pick(conn):
    row = _tie(conn)
    code, out = _show(conn, row)
    assert "Answer: awaiting pick" in out and f"Pick: sr pick {row['n']} a | b | c | none" in out
    assert "awaiting pick" in out.splitlines()[0]
    assert out.index("A — claude") < out.index("B — chatgpt") < out.index("C — grok") and "(dissent)" not in out


def test_show_after_a_pick_says_unchecked(conn):
    row = _tie(conn)
    _pick(conn, row, "c")
    code, out = _show(conn, row)
    assert "Answer: Spain (picked C; no majority, unchecked)" in out and "Pick:" not in out


def test_show_after_none_says_so(conn):
    row = _tie(conn)
    _pick(conn, row, "none")
    code, out = _show(conn, row)
    assert "Answer: none (picked none; no majority). Every answer is kept." in out


def test_show_stages_prints_the_three_raw_results(conn):
    row = _majority(conn)
    code, out = _show(conn, row, stages=True)
    for text in (FRANCE, B, G):
        assert text in out


def test_a_voter_with_no_readable_confidence_shows_none(conn):
    row = _majority(conn, answers=(vote("Texas", confidence="very"), B, G))
    code, out = _show(conn, row)
    assert "A — claude: Texas\n" in out + "\n"


def test_sr_log_reads_relay_vote_and_awaiting_pick_until_decided(conn):
    row = _tie(conn)
    lines = []
    cli.cmd_log(conn=conn, out=lines.append)
    line = next(l for l in lines if row["task_id"] in l)
    assert "awaiting pick" in line and "relay:vote" in line
    _pick(conn, row, "b")
    lines = []
    cli.cmd_log(conn=conn, out=lines.append)
    line = next(l for l in lines if row["task_id"] in l)
    assert "awaiting pick" not in line and "relay:vote" in line and "unchecked" in line and "chatgpt" in line


def test_sr_log_on_a_majority_names_the_winner_and_passed(conn):
    row = _majority(conn)
    lines = []
    cli.cmd_log(conn=conn, out=lines.append)
    line = next(l for l in lines if row["task_id"] in l)
    assert "relay:vote" in line and "passed" in line and " chatgpt " in line


def test_a_vote_stage_reads_answered_not_passed_in_the_stages_list(conn):
    # The owner, after phase E: "passed" read like a verdict on the vote; display only
    row = _majority(conn)
    code, out = _show(conn, row)
    assert "  1. vote by claude: answered" in out and "  3. vote by grok: answered" in out
    assert "vote by claude: passed" not in out


def test_a_re_asked_vote_stage_reads_re_asked_answered(conn):
    w = World(claude=[A], chatgpt=[B], grok={"s3": "Texas.", "s3r": G})
    w.relay(conn)
    w.check(conn)
    w.check(conn)
    code, out = _show(conn, log.recent_tasks(conn)[0])
    assert "  3. vote by grok: re-asked, answered" in out
