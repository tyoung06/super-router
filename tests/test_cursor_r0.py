"""Build brief 32, R0 (the design chat's Proof 4 verdict: Cursor's command line loaded the router's own CLAUDE.md as
workspace rules, because its scratch folder sat inside the router's folder). Every Cursor call's scratch folder is made in
the system's temporary folder, and a call is refused when any folder above it holds an instruction file; the deny file
denies MCP tools too; the probe gains a third canary, instruction files holding a marker one and two folders above its
scratch folder (since the design chat's fix of 29 Oct it checks the per-call guard instead of failing on a marker that
shows: tests/test_cursor_guard_canary.py), and records the MCP tools Cursor lists; a pass records its canaries, so a pass from the two-canary probe is no pass and the router probes again. A rejected
tool call reads `rejected`, never `success`. Fakes only; every value here is fake."""
import json
import subprocess
from pathlib import Path

import pytest

from router import cursor_probe, cursor_worker, probes, search, status
from tests.test_cursor_probe import ENVIRON, MODEL, TOKEN, VERSION, ProbeAgent, event, stream

PROMPT = cursor_worker.wrap("Attack the result.")
PIN = stream("ok")


@pytest.fixture(autouse=True)
def temp_root(tmp_path, monkeypatch):
    """The system's temporary folder, for this test: a folder of its own, nothing above it but pytest's."""
    root = tmp_path / "systemp"
    root.mkdir()
    monkeypatch.setattr(cursor_worker, "temp_root", lambda: root)
    return root


class Agent:
    """Stands in for subprocess.run on `agent -p`: records the scratch folder, what is in it and what is above it."""

    def __init__(self, stdout=PIN):
        self.stdout, self.seen = stdout, []

    def __call__(self, argv, **kwargs):
        cwd = Path(kwargs["cwd"])
        self.seen.append({"cwd": cwd, "inside": sorted(str(p.relative_to(cwd)) for p in cwd.rglob("*")),
                          "deny": (cwd / ".cursor" / "cli.json").read_text(), "argv": argv})
        return subprocess.CompletedProcess(argv, 0, self.stdout, "")


# ---------- the scratch folder (R0, fix 1) ----------

def test_every_call_runs_from_a_fresh_folder_in_the_systems_temporary_folder(temp_root):
    fake = Agent()
    assert cursor_worker.run(PROMPT, model=MODEL, run=fake, environ=ENVIRON, call_id="sr-x-s3") == "ok"
    seen = fake.seen[0]
    assert seen["cwd"].parent == temp_root and seen["cwd"].name.startswith("sr-cursor-sr-x-s3-")
    assert seen["inside"] == [".cursor", ".cursor/cli.json"] and seen["deny"] == cursor_worker.deny_text()
    assert seen["argv"][seen["argv"].index("--workspace") + 1] == str(seen["cwd"])
    assert not seen["cwd"].exists() and list(temp_root.iterdir()) == []  # removed after; the temporary folder stays
    assert cursor_worker.instruction_files_above(seen["cwd"]) == []


def test_no_call_is_ever_made_inside_the_router_folder(temp_root):
    fake = Agent()
    cursor_worker.run(PROMPT, model=MODEL, run=fake, environ=ENVIRON, call_id="sr-x-s3")
    repo = Path(cursor_worker.__file__).resolve().parent.parent
    assert repo not in fake.seen[0]["cwd"].resolve().parents


@pytest.mark.parametrize("name", ["CLAUDE.md", "AGENTS.md", ".cursorrules", ".cursor"])
def test_a_call_is_refused_when_an_instruction_file_sits_above_its_folder(temp_root, name):
    above = temp_root.parent / name
    if name == ".cursor":
        (above / "rules").mkdir(parents=True)
    else:
        above.write_text("Be helpful.\n")
    fake = Agent()
    with pytest.raises(cursor_worker.WorkerError, match=rf"refused: {name.replace('.', '[.]')} sits above"):
        cursor_worker.run(PROMPT, model=MODEL, run=fake, environ=ENVIRON, call_id="sr-x-s3")
    assert fake.seen == [] and list(temp_root.iterdir()) == []  # no call, no folder left


def test_the_instruction_names_cover_the_usual_rule_files():
    for name in ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "AGENT.md", "GEMINI.md", ".cursorrules", ".cursor",
                 ".windsurfrules", ".clinerules"):
        assert name in cursor_worker.INSTRUCTION_NAMES


# ---------- the deny file (R0, fix 3) and a rejected tool call ----------

def test_the_deny_file_denies_mcp_tools_beside_shell_read_and_write():
    deny = cursor_worker.DENY["permissions"]["deny"]
    assert deny == ["Shell(*)", "Read(**)", "Write(**)", "Read(/**)", "Write(/**)", "Mcp(*:*)"]
    assert cursor_worker.DENY["permissions"]["allow"] == []


def _rejected(kind):
    return event(type="tool_call", subtype="completed", call_id="c",
                 tool_call={kind: {"args": {"searchTerm": "x"}, "result": {"rejected": {"reason": "User Rejected"}}}})


def test_a_rejected_tool_call_reads_rejected_and_never_fails_the_call():
    lines = [json.dumps({"type": "system", "subtype": "init", "model": "Grok 4.7 256K High"}),
             _rejected("webSearchToolCall"), _rejected("readToolCall"),
             json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}}),
             json.dumps({"type": "result", "result": "ok", "duration_ms": 5})]
    found = cursor_worker.run(PROMPT, model=MODEL, run=Agent("\n".join(lines) + "\n"), environ=ENVIRON, call_id="c1")
    assert found == "ok"
    assert found.served["tools"] == ["webSearchToolCall:completed:rejected", "readToolCall:completed:rejected"]


def _with_tools(*events):
    return "\n".join([json.dumps({"type": "system", "subtype": "init", "model": "Grok 4.7 256K High"}), *events,
                      json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}}),
                      json.dumps({"type": "result", "result": "ok"})]) + "\n"


def _listing(*names):
    content = "\n".join(json.dumps({"tool": n, "description": "d"}) for n in names)
    return event(type="tool_call", subtype="completed", call_id="m",
                 tool_call={"getMcpToolsToolCall": {"args": {}, "result": {"success": {"content": content}}}})


def test_the_mcp_tools_cursor_lists_are_read_from_the_stream():
    parsed = cursor_worker.parse(_with_tools(_listing("WebSearch", "Datadog"), _listing("WebSearch")))
    assert cursor_worker.mcp_tools(parsed) == ["Datadog", "WebSearch"]
    assert cursor_worker.mcp_tools(cursor_worker.parse(PIN)) == []


# ---------- the third canary (R0, fix 2) ----------

def rules_stream(text="none"):
    return stream(text)


def test_the_probe_runs_three_canaries_the_third_with_rules_above_its_folder(temp_root):
    fake = ProbeAgent(c=rules_stream())
    result = cursor_probe.probe(model=MODEL, run=fake, environ=ENVIRON, token=TOKEN)
    assert result.passed, [(c.name, c.detail) for c in result.checks]
    assert [c.name for c in result.checks][-5:] == [
        "rules canary: agent ran to the end", "rules canary: served the pinned model", "rules canary: the guard",
        "rules canary: the files Cursor read from above",
        "rules canary: no read, shell or write completed and no listing found files"]
    a, b, c = fake.seen
    for seen in (a, b, c):
        assert seen["cwd"].parent.parent.parent == temp_root  # <temp>/sr-cursor-probe-*/inner/<canary>/
        assert seen["inside"] == [".cursor", ".cursor/cli.json"]
    assert a["beside"] == ["canary.txt"] and b["beside"] == [f"SR-LS-{TOKEN}.txt"]
    one_up, two_up = c["above"]
    marks = cursor_probe.markers(TOKEN)  # the design chat's fix of 29 Oct: each file its own marker
    for name in ("CLAUDE.md", "AGENTS.md", ".cursorrules", ".cursor/rules/sr-probe.mdc"):
        assert marks[f"inner/{name}"] in one_up[name] and marks[name] in two_up[name], name
    assert not any(mark in c["prompt"] for mark in marks.values())
    assert list(temp_root.iterdir()) == []  # the probe's folders are gone


@pytest.mark.parametrize("where", ["text", "thinking"])
def test_a_marker_in_the_text_or_the_thinking_is_kept_and_no_longer_fails_the_rules_canary(where):
    # the design chat's fix of 29 Oct: Cursor reads the folders above whatever the router does; the guard keeps them out
    leak = cursor_probe.markers(TOKEN)["inner/CLAUDE.md"]
    if where == "text":
        c = rules_stream(f"My rules say {leak}")
    else:
        c = PIN.replace('{"type": "assistant"', json.dumps({"type": "thinking", "subtype": "delta",
                                                             "text": f"the rules mention {leak}"}) + '\n{"type": "assistant"', 1)
    result = cursor_probe.probe(model=MODEL, run=ProbeAgent(c=c), environ=ENVIRON, token=TOKEN)
    assert result.passed and result.rules_from_above == ["../CLAUDE.md"]


def test_the_probe_records_the_mcp_tools_cursor_listed(temp_root):
    c = _with_tools(_listing("WebSearch"))
    result = cursor_probe.probe(model=MODEL, run=ProbeAgent(c=c), environ=ENVIRON, token=TOKEN)
    assert result.passed and result.mcp_tools == ["WebSearch"]
    assert any(n == "mcp: Cursor listed 1 MCP tool: WebSearch" for n in result.notes)


# ---------- a pass records its canaries; a two-canary pass is no pass ----------

def test_a_pass_records_its_three_canaries_and_the_mcp_tools(tmp_path):
    path = tmp_path / "probe_state.json"
    result = cursor_probe.command_check(path, model=MODEL, environ=ENVIRON, run=ProbeAgent(c=_with_tools(_listing("WebSearch"))))()
    assert result.passed
    entry = json.loads(path.read_text())["cursor_sandbox"]
    assert entry["version"] == VERSION and entry["canaries"] == ["read", "list", "rules"] and entry["mcp_tools"] == ["WebSearch"]
    assert cursor_worker.passed_version(path) == VERSION


def test_a_pass_from_the_two_canary_probe_is_no_pass_and_the_router_probes_again(tmp_path):
    path = tmp_path / "probe_state.json"
    search.record_pass(path, VERSION, key=cursor_worker.SANDBOX_KEY)  # brief 20's record: no canaries named
    assert cursor_worker.passed_version(path) is None
    assert cursor_worker.ready(path, run=ProbeAgent(), environ=ENVIRON) == (
        False, "cursor: Cursor's safety check gained a canary since its pass on record; the router checks it again before "
               "Cursor's next task")
    fake = ProbeAgent()
    result = cursor_probe.command_check(path, model=MODEL, environ=ENVIRON, run=fake)()
    assert result.passed and len(fake.prompt_calls) == 3 and cursor_worker.passed_version(path) == VERSION
    assert status._probe("cursor", path, VERSION)["state"] == "passed"


def test_the_router_says_three_canaries_when_it_runs_them(tmp_path):
    lines = []
    path = tmp_path / "probe_state.json"
    probes.cursor_ready(path, model=MODEL, folder=None, out=lines.append,
                        ready=lambda p: cursor_worker.ready(p, run=ProbeAgent(), environ=ENVIRON),
                        check=cursor_probe.command_check(path, model=MODEL, environ=ENVIRON, run=ProbeAgent()),
                        installed=lambda: VERSION)
    assert lines[0] == (f"probe: Cursor's safety check has no pass on agent {VERSION}; running its three canaries "
                        "(three pool calls)")
