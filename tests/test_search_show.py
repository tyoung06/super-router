"""Phase D of build brief 8: `sr show <n> --stages` puts one search line under a stage that searched or
could have; `--history` lists the queries. `sr log` is unchanged. Fake agents only."""
from router import __main__ as cli
from router import log
from tests.test_relay import Chat, ROSTER
from tests.test_collab import LOADED
from tests.test_search import SearchingClaude, _relay, conn  # noqa: F401


def _show(conn, *words, history=False, stages=False):
    lines = []
    cli.cmd_show(conn=conn, words=list(words), history=history, stages=stages, roster=ROSTER, presets=LOADED,
                 out=lines.append)
    return lines


def test_stages_name_the_searches_of_the_build_stage(conn):
    claude = SearchingClaude("a brief", queries=("K10 price", "Sprig Gen2 price"))
    _relay(conn, claude=claude, chatgpt=Chat("PASS"), ready=True)
    lines = _show(conn, "1", stages=True)
    at = lines.index("stage 2 build by claude: done")
    assert lines[at + 1] == "search: allowed — 2 queries"
    assert not any(line.startswith("search:") for line in lines[:at])     # the research stage never searches


def test_stages_say_when_search_was_off_for_the_probe(conn):
    _relay(conn, claude=SearchingClaude("a brief"), chatgpt=Chat("PASS"), ready=False)
    assert "search: off (probe not passed)" in _show(conn, "1", stages=True)


def test_one_query_and_more_than_five(conn):
    _relay(conn, claude=SearchingClaude("a brief", queries=("q",)), chatgpt=Chat("PASS"), ready=True)
    assert "search: allowed — 1 query" in _show(conn, "1", stages=True)
    _relay(conn, claude=SearchingClaude("a brief", queries=tuple(f"q{i}" for i in range(7))), chatgpt=Chat("PASS"),
           ready=True)
    assert "search: allowed — 7 queries (more than 5)" in _show(conn, "2", stages=True)


def test_history_lists_the_queries_of_the_build_and_the_fix(conn):
    claude = SearchingClaude("a brief", "a fixed brief", queries=("K10 price",))
    _relay(conn, claude=claude, chatgpt=Chat("FIX\n1. add a price", "PASS"), ready=True)
    lines = _show(conn, "1", history=True)
    build = next(i for i, line in enumerate(lines) if line.startswith("2. stage 2 build by claude"))
    assert lines[build + 1:build + 3] == ["  search: allowed — 1 query", "    K10 price"]
    fix = next(i for i, line in enumerate(lines) if line.startswith("4. fix by claude"))
    assert lines[fix + 1:fix + 3] == ["  search: allowed — 1 query", "    K10 price"]


def test_a_search_by_chatgpt_says_its_queries_are_not_reported():
    assert cli._search_text({"state": "allowed"}) == "search: allowed — queries not reported"


def test_sr_log_is_unchanged(conn):
    _relay(conn, claude=SearchingClaude("a brief"), chatgpt=Chat("PASS"), ready=True)
    lines = []
    cli.cmd_log(conn=conn, out=lines.append)
    assert not any("search:" in line or "quer" in line for line in lines)
