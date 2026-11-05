"""Build brief 32's D, the design chat's fix of 29 Oct (item 2): Cursor's third canary checks R0's per-call guard. D's
step 1 showed Cursor's command line reads instruction files from the folders above its working folder, with or without
git, and no flag turns that off, so a canary that failed on any marker from above could never pass. The four rule files,
one and two folders above the scratch folder, each hold their own marker; the files whose markers show in Cursor's
stream are kept as `rules_from_above`, which alone never fails the probe; the probe fails when a marker came from a file
the guard doesn't look for, or when the guard, run where the probe's scratch folder is made with those files in place,
lets the call through (no model call). The reasons read plainly, and the failure the old rule recorded reads as no
record. Fakes only; every value here is fake."""
import json
import re
from pathlib import Path

import pytest

from router import __main__ as cli
from router import cursor_probe, cursor_worker, probes, status
from tests.test_cursor_probe import ENVIRON, MODEL, TOKEN, VERSION, ProbeAgent, stream

ONE_UP = [f"../{name}" for name in cursor_probe.RULE_FILES]
TWO_UP = [f"../../{name}" for name in cursor_probe.RULE_FILES]
OLD_REASON = "rules canary: the marker is nowhere in the stream: found"  # what the old rule wrote in D's step 1


@pytest.fixture(autouse=True)
def temp_root(tmp_path, monkeypatch):
    root = tmp_path / "systemp"
    root.mkdir()
    monkeypatch.setattr(cursor_worker, "temp_root", lambda: root)
    return root


def thinking(text):
    """A stream whose thinking carries `text`, its reply only `none`."""
    lines = stream("none").splitlines()
    lines.insert(1, json.dumps({"type": "thinking", "subtype": "delta", "text": text}))
    return "\n".join(lines) + "\n"


class ReadsAbove(ProbeAgent):
    """A fake `agent -p` that, on the rules canary, reads the rule files above its folder as the real one did in D's step
    1 and opens its reply with their code words. `reads`: the files it reads, as seen from the scratch folder, or None
    for every one; `where`: in its text or its thinking."""

    def __init__(self, reads=None, where="text", **kw):
        super().__init__(**kw)
        self.reads, self.where = reads, where

    def __call__(self, argv, **kwargs):
        if argv[:2] == ["agent", "-p"] and argv[-1] == cursor_probe.RULES_PROMPT:
            cwd, words = Path(kwargs["cwd"]), []
            for up, folder in (("../", Path(kwargs["cwd"]).parent), ("../../", Path(kwargs["cwd"]).parent.parent)):
                for name in cursor_probe.RULE_FILES:
                    if (folder / name).is_file() and (self.reads is None or up + name in self.reads):
                        words += re.findall(r"SR-RULES-[0-9a-f]+-\d\d", (folder / name).read_text())
            assert cwd.name == "probe-c"
            text = " ".join(words) or "none"
            self.streams[-1] = stream(text) if self.where == "text" else thinking(text)
        return super().__call__(argv, **kwargs)


def _failed(result):
    return [c.name for c in result.checks if not c.ok]


def _check(result, name):
    return next(c for c in result.checks if c.name == name)


def _probe(fake):
    return cursor_probe.probe(model=MODEL, run=fake, environ=ENVIRON, token=TOKEN)


# ---------- the files and their markers ----------

def test_each_rule_file_above_holds_its_own_marker_and_the_prompt_holds_none():
    fake = ProbeAgent()
    _probe(fake)
    one_up, two_up = fake.seen[2]["above"]
    marks = cursor_probe.markers(TOKEN)
    assert len(marks) == 8 and len(set(marks.values())) == 8
    for name in cursor_probe.RULE_FILES:
        assert marks[f"inner/{name}"] in one_up[name] and marks[name] in two_up[name]
    for text in [*one_up.values(), *two_up.values()]:
        assert sum(mark in text for mark in marks.values()) == 1
    assert not any(mark in fake.seen[2]["prompt"] for mark in marks.values())


def test_the_rules_canarys_checks_in_order():
    result = _probe(ProbeAgent())
    assert result.passed, [(c.name, c.detail) for c in result.checks]
    assert [c.name for c in result.checks][-5:] == [
        "rules canary: agent ran to the end", "rules canary: served the pinned model", "rules canary: the guard",
        "rules canary: the files Cursor read from above",
        "rules canary: no read, shell or write completed and no listing found files"]
    assert _check(result, "rules canary: the guard").detail == ("it refuses a call from this folder, with 8 instruction "
                                                                "files above")
    assert _check(result, "rules canary: the files Cursor read from above").detail == "Cursor read none of them"
    assert result.rules_from_above == [] and "rules: Cursor read none of the rule files above its folder" in result.notes


# ---------- what Cursor reads from above is kept, and never fails the probe by itself ----------

@pytest.mark.parametrize("where", ["text", "thinking"])
def test_cursor_reading_every_file_above_passes_and_is_kept_as_rules_from_above(where):
    result = _probe(ReadsAbove(where=where))
    assert result.passed, [(c.name, c.detail) for c in result.checks]
    assert result.rules_from_above == ONE_UP + TWO_UP
    assert _check(result, "rules canary: the files Cursor read from above").detail == (
        f"Cursor read {', '.join(ONE_UP + TWO_UP)}; the guard looks for each")
    assert (f"rules: Cursor read {', '.join(ONE_UP + TWO_UP)} from the folders above its folder; the guard refuses a real "
            "call made below such a file") in result.notes


def test_a_pass_records_the_files_cursor_read_from_above(tmp_path):
    path = tmp_path / "probe_state.json"
    result = cursor_probe.command_check(path, model=MODEL, environ=ENVIRON, run=ReadsAbove(reads={"../CLAUDE.md"}))()
    entry = json.loads(path.read_text())["cursor_sandbox"]
    assert result.passed and entry["rules_from_above"] == ["../CLAUDE.md"]
    assert entry["canaries"] == ["read", "list", "rules"] and cursor_worker.passed_version(path) == VERSION


# ---------- what fails it ----------

def test_a_marker_from_a_file_the_guard_does_not_look_for_fails_the_probe(monkeypatch):
    monkeypatch.setattr(cursor_worker, "INSTRUCTION_NAMES",
                        tuple(n for n in cursor_worker.INSTRUCTION_NAMES if n != "AGENTS.md"))
    result = _probe(ReadsAbove(reads={"../CLAUDE.md", "../AGENTS.md"}))
    assert not result.passed and _failed(result) == ["rules canary: the files Cursor read from above"]
    assert probes._reason(result) == ("rules canary: the files Cursor read from above: Cursor read ../AGENTS.md, which the "
                                      "guard doesn't look for")
    assert result.rules_from_above == ["../CLAUDE.md", "../AGENTS.md"]


def test_a_guard_that_lets_the_call_through_fails_the_probe_with_no_extra_model_call(monkeypatch):
    monkeypatch.setattr(cursor_worker, "guard", lambda folder: None)
    fake = ProbeAgent()
    result = _probe(fake)
    assert _failed(result) == ["rules canary: the guard"] and len(fake.prompt_calls) == 3
    assert probes._reason(result) == ("rules canary: the guard: it let a call from this folder through, with 8 instruction "
                                      "files above")


def test_the_guard_is_asked_where_the_scratch_folder_is_made_with_the_files_in_place(monkeypatch):
    asked, real = [], cursor_worker.guard

    def spy(folder):
        asked.append((Path(folder), sorted(p.name for p in Path(folder).iterdir()), real(folder)))
        return asked[-1][2]
    monkeypatch.setattr(cursor_worker, "guard", spy)
    fake = ProbeAgent()
    _probe(fake)
    assert [folder for folder, _, _ in asked] == [seen["cwd"].parent for seen in fake.seen]  # <probe>/inner, each canary
    folder, names, refusal = asked[2]
    assert set(cursor_probe.RULE_FILES[:3]) | {".cursor"} <= set(names)
    assert refusal.startswith("refused: ") and refusal.endswith("Cursor would read it as rules, so no call was made")
    assert asked[0][2] is None and asked[1][2] is None  # nothing above the read and list canaries' folder


def test_the_guard_is_what_refuses_a_real_call(temp_root):
    assert cursor_worker.guard(temp_root) is None
    (temp_root.parent / "AGENTS.md").write_text("Be brief.\n")
    refusal = cursor_worker.guard(temp_root)
    with pytest.raises(cursor_worker.WorkerError) as err:
        cursor_worker.run(cursor_worker.wrap("x"), model=MODEL, run=ProbeAgent(), environ=ENVIRON, call_id="c")
    assert str(err.value) == refusal and refusal.startswith("refused: AGENTS.md sits above Cursor's scratch folder")


# ---------- the words ----------

def test_the_first_two_canaries_reasons_read_plainly():
    read = _probe(ProbeAgent(a=stream(f"The file says {TOKEN}")))
    assert probes._reason(read) == ("read canary: the file one folder up: its word showed in Cursor's output, so Cursor "
                                    "read it")
    listed = _probe(ProbeAgent(b=stream(f"SR-LS-{TOKEN}.txt")))
    assert probes._reason(listed) == ("list canary: the folder above: the planted file's name showed in Cursor's output, so "
                                      "Cursor listed it")


def test_no_check_says_nowhere_in_the_stream_or_found_alone():
    result = _probe(ReadsAbove())
    for c in result.checks:
        assert "nowhere in the stream" not in c.name and c.detail not in ("found", "not found"), c


# ---------- the failure the old rule recorded ----------

def test_the_old_rules_failure_reads_as_no_record_and_the_router_probes_again(tmp_path):
    path = tmp_path / "probe_state.json"
    probes.record_failure(path, cursor_worker.SANDBOX_KEY, VERSION, probes.RAN_FAILED, OLD_REASON)
    assert probes.failure(path, cursor_worker.SANDBOX_KEY) is None
    assert probes.held_back(path, cursor_worker.SANDBOX_KEY, VERSION) is None
    assert status._probe("cursor", path, VERSION)["state"] == "missing"
    lines = []
    found = probes.cursor_ready(path, model=MODEL, folder=None, out=lines.append,
                                ready=lambda p: cursor_worker.ready(p, run=ProbeAgent(), environ=ENVIRON),
                                check=cursor_probe.command_check(path, model=MODEL, environ=ENVIRON, run=ReadsAbove()),
                                installed=lambda: VERSION)
    assert found == (True, None) and lines[0].endswith("running its three canaries (three pool calls)")
    assert json.loads(path.read_text())["cursor_sandbox"]["rules_from_above"] == ONE_UP + TWO_UP


@pytest.mark.parametrize("reason", ["read canary: the nonce is nowhere in the stream: found",
                                    "rules canary: agent ran to the end: cursor timed out after 600 s",
                                    "rules canary: no read, shell or write completed and no listing found files: x"])
def test_a_failure_of_any_other_check_still_stands(tmp_path, reason):
    path = tmp_path / "probe_state.json"
    probes.record_failure(path, cursor_worker.SANDBOX_KEY, VERSION, probes.RAN_FAILED, reason)
    assert probes.failure(path, cursor_worker.SANDBOX_KEY)["reason"] == reason
    assert probes.held_back(path, cursor_worker.SANDBOX_KEY, VERSION)["reason"] == reason
    assert status._probe("cursor", path, VERSION)["state"] == "failed"


def test_the_old_words_on_another_probe_are_left_alone(tmp_path):
    path = tmp_path / "probe_state.json"
    probes.record_failure(path, "claude_search", "2.1.312", probes.RAN_FAILED, OLD_REASON)
    assert probes.failure(path, "claude_search")["reason"] == OLD_REASON


def test_a_failure_the_gate_records_keeps_the_files_cursor_read(tmp_path, monkeypatch):
    monkeypatch.setattr(cursor_worker, "INSTRUCTION_NAMES",
                        tuple(n for n in cursor_worker.INSTRUCTION_NAMES if n != "AGENTS.md"))
    path = tmp_path / "probe_state.json"
    found = probes.cursor_ready(path, model=MODEL, folder=None, out=lambda line: None,
                                ready=lambda p: cursor_worker.ready(p, run=ProbeAgent(), environ=ENVIRON),
                                check=cursor_probe.command_check(path, model=MODEL, environ=ENVIRON,
                                                                 run=ReadsAbove(reads={"../AGENTS.md"})),
                                installed=lambda: VERSION)
    assert found[0] is False and "Cursor read ../AGENTS.md, which the guard doesn't look for" in found[1]
    record = json.loads(path.read_text())["cursor_sandbox_failure"]
    assert record["found"] == {"rules_from_above": ["../AGENTS.md"]} and record["kind"] == probes.RAN_FAILED


def test_sr_probe_json_shows_the_files_cursor_read_from_above(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.codex_probe, "probe", lambda **kw: type("R", (), {
        "codex_version": "0.162.1", "seconds": 1.0, "checks": [], "notes": [], "passed": True})())
    monkeypatch.setattr(cli.probes, "record_codex", lambda path, result: None)
    result = _probe(ReadsAbove(reads={"../../CLAUDE.md"}))
    out = cli.receipt.Receipt()
    code = cli.cmd_probe(model="gpt", config={}, environ={}, home=tmp_path, cursor_check=lambda: result, out=out)
    found = cli._envelope(out, code)["probe"]["cursor"]
    assert code == 0 and found["passed"] is True and found["rules_from_above"] == ["../../CLAUDE.md"]
