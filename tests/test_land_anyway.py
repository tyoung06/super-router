"""Brief 29.1 (decision 21, the checker's fix 7, reopening D1): a file-mode task whose check ended failed (FIX after the
fix round, or the fix round didn't run), with its copy kept and a change, offers Land anyway beside Discard:
`sr land <n> --anyway`, its own path; without the flag it is refused as today. Every check before a land still runs (the
key scan, the clashes). The commit message ends `(<task_id>, check not passed)`; the entry reads `landed (check not
passed)`; Undo as usual. Never a blocked, stopped or passed task, a piece, or a versus task. The JSON offers it as
`land_anyway`; the page's land request carries `anyway`. Real git in temp folders, fake agents; every value fake."""
import pytest

from router import __main__ as cli
from router import copies, jsonview, landing, log, page_commands, projects
from tests.test_copies import git
from tests.test_filemode_flow import BUILD, FIXED_CALC, Chat, CopyWorker, conn, project, route, runner  # noqa: F401
from tests.test_handoff_contract import HANDOFF
from tests.test_landing import head, land, show, state

FIRST = "FIX\n1. [must] add() has no docstring naming both parameters.\n2. [note] Shorter lines."
STILL = "FIX\n1. not fixed: the docstring still names only a."
FIXED = ("Added a docstring.\n\n## Handoff\n### Produced\ncalc.py changed\n### Status\nadd has a docstring\n### Next\nland",
         {"calc.py": '"""calc"""\n' + FIXED_CALC})


def failed(conn, worker=None, chatgpt=None):
    code, out, row = route(conn, worker=worker or CopyWorker(BUILD, FIXED), chatgpt=chatgpt or Chat(FIRST, STILL))
    row = log.get_task(conn, row["task_id"])
    assert (row["status"], row["check_state"]) == ("done", "failed"), out
    return row, out


def anyway(conn, row, config=None):
    lines = []
    code = cli.cmd_land([str(row["n"])], conn=conn, config=config or {}, verb="land", out=lines.append, anyway=True)
    return code, "\n".join(lines)


def test_a_failed_check_offers_land_anyway_and_plain_land_still_refuses(project, conn, runner):
    row, out = failed(conn)
    assert f"sr land {row['n']} --anyway lands it as it is" in out
    view = jsonview.task_view(conn, row)
    assert view["land_anyway"] is True
    assert view["open_musts"] == [{"n": 1, "text": "add() has no docstring naming both parameters. "
                                                   "(not fixed: the docstring still names only a.)"}]
    before = state(project)
    code, said = land(conn, row)
    assert code == 2 and "--anyway lands it as it is" in said and state(project) == before


def test_land_anyway_makes_one_commit_that_says_the_check_did_not_pass(project, conn, runner):
    row, _ = failed(conn)
    before = head(project)
    code, out = anyway(conn, row)
    assert code == 0, out
    after = head(project)
    subject, _, _, *names = show(project, after)
    assert subject.endswith(f"({row['task_id']}, check not passed)")
    assert sorted(n for n in names if n) == ["HANDOFF.md", "calc.py", "test_calc.py"]
    newest = projects.entries_of((project / "HANDOFF.md").read_text())[0]
    assert newest.splitlines()[0].endswith("· landed (check not passed)")
    assert "calc.py changed" in newest  # the fix round's own section
    record = log.project_files_of(log.get_task(conn, row["task_id"]))
    assert (record["state"], record["anyway"], record["copy"]) == ("landed", True, False)
    assert "(its check didn't pass)" in out and git(project, "rev-parse", "HEAD~1").decode().strip() == before
    code, out = land(conn, row, "undo")
    assert code == 0, out
    assert projects.entries_of((project / "HANDOFF.md").read_text())[0].endswith(f"undone ({after[:7]})")


def test_when_the_fix_round_did_not_run_the_entry_is_the_builds_section(project, conn, runner):
    row, _ = failed(conn, worker=CopyWorker(BUILD, RuntimeError("the fix call broke")), chatgpt=Chat(FIRST))
    code, out = anyway(conn, row)
    assert code == 0, out
    newest = projects.entries_of((project / "HANDOFF.md").read_text())[0]
    assert "calc.py and test_calc.py changed" in newest and newest.splitlines()[0].endswith("(check not passed)")


def test_the_key_scan_still_refuses_a_flagged_file(project, conn, runner):
    value = "".join(("sk", "-", "abcdefghijklmnop", "qrstuv"))
    leaky = ("Done.\n\n" + HANDOFF, {"calc.py": FIXED_CALC + f"API = '{value}'\n"})
    row, _ = failed(conn, worker=CopyWorker(leaky, leaky))
    before = state(project)
    code, out = anyway(conn, row)
    assert code == 2 and "calc.py line 3 looks like it holds a key" in out and value not in out
    assert state(project) == before and copies.exists(row["task_id"])


@pytest.mark.parametrize("kind", ["passed", "blocked", "no change"])
def test_land_anyway_refuses_what_it_is_not_for(project, conn, runner, kind):
    if kind == "passed":
        code, out, row = route(conn, worker=CopyWorker(BUILD), chatgpt=Chat("PASS"))
        words = "waits to land as checked"
    elif kind == "blocked":
        code, out, row = route(conn, worker=CopyWorker(BUILD), chatgpt=Chat("BLOCKED: the owner's style guide"))
        words = "a blocked task offers Discard only"
    else:
        code, out, row = route(conn, worker=CopyWorker(("Nothing to change.\n\n" + HANDOFF, {}), ("Still nothing.\n\n"
                                                       + HANDOFF, {})), chatgpt=Chat(FIRST, STILL))
        words = "changed no file"  # brief 29.1 (decision 2): its copy went at delivery too
    row = log.get_task(conn, row["task_id"])
    before = state(project)
    code, said = anyway(conn, row)
    assert code == 2 and words in said, said
    assert state(project) == before
    assert jsonview.task_view(conn, row)["land_anyway"] is False


def test_a_piece_and_a_versus_task_are_never_landed_anyway():
    piece = {"n": 4, "parent": "sr-1", "mode": "route", "status": "done", "check_state": "failed"}
    picked = {"n": 5, "parent": None, "mode": "relay", "status": "done", "check_state": "failed"}

    class Row(dict):
        def keys(self):
            return super().keys()
    record = {"mode": "on", "copy": True, "changed": [{"path": "a"}], "state": None}
    assert "a piece" in landing.anyway_refusal(Row(piece), record)
    assert "versus" in landing.anyway_refusal(Row(picked), {**record, "picked": "a"})
    assert "versus" in landing.anyway_refusal(Row(picked), {**record, "versus": True, "candidates": {}})


def test_the_page_builds_land_anyway_as_one_flag():
    status = {}
    built = page_commands.build({"action": "land", "task_id": "sr-20261027-101010-aaaa", "anyway": True}, status)
    assert list(built.args) == ["land", "--json", "sr-20261027-101010-aaaa", "--anyway"]
    plain = page_commands.build({"action": "land", "task_id": "sr-20261027-101010-aaaa"}, status)
    assert list(plain.args) == ["land", "--json", "sr-20261027-101010-aaaa"]
    for bad in ({"action": "discard", "anyway": True}, {"action": "land", "anyway": "yes"}):
        with pytest.raises(page_commands.Refused):
            page_commands.build({**bad, "task_id": "sr-20261027-101010-aaaa"}, status)


def test_the_command_line_takes_anyway_on_land_only(monkeypatch):
    seen = {}

    def fake(words, *, conn, config, verb, out, anyway=False, **kw):  # brief 34: the land takes the memory store too
        seen.update(verb=verb, anyway=anyway)
        return 0
    monkeypatch.setattr(cli, "cmd_land", fake)
    assert cli.main(["land", "5", "--anyway"], platform="darwin") == 0 and seen == {"verb": "land", "anyway": True}
    with pytest.raises(SystemExit):
        cli.main(["discard", "5", "--anyway"], platform="darwin")


# ---------- brief 30 (A5): Land anyway's entry takes the failed line's place ----------

def test_land_anyways_entry_takes_the_failed_lines_place_and_undo_marks_it_there(project, conn, runner):
    row, _ = failed(conn)
    n = row["n"]
    entries = projects.entries_of((project / "HANDOFF.md").read_text())
    assert entries[0].startswith(f"### #{n} ") and "· failed: " in entries[0].splitlines()[0]
    projects.write_entry(project, "### #200 · 2026-10-28 · writing · claude\nProduced:\nsomething\nStatus:\n—\nNext:\n—")
    code, out = anyway(conn, row)
    assert code == 0, out
    entries = projects.entries_of((project / "HANDOFF.md").read_text())
    ours = [e for e in entries if e.startswith(f"### #{n} ")]
    assert len(ours) == 1 and ours[0].splitlines()[0].endswith("· landed (check not passed)")  # one entry per task
    assert entries[0].startswith("### #200 ") and entries[1] == ours[0]  # where the failed line stood
    assert not any("· failed: " in e for e in entries)
    landed = head(project)
    code, out = land(conn, row, "undo")
    assert code == 0, out
    entries = projects.entries_of((project / "HANDOFF.md").read_text())
    assert entries[0].startswith("### #200 ") and entries[1] == f"### #{n} · {entries[1].split(' · ')[1]} · undone ({landed[:7]})"
