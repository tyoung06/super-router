"""Build brief 28 (decisions 3 and 7; Tests, "Claude's argv"): the Claude worker's file-mode call, with a fake `claude`
that records its command. The copy is the working folder; the tools are exactly the call's own; no tool that runs a
command; the flags keep settings, hooks, MCP servers and instruction files out. The stream is read as the file check reads
it: a tool Claude Code refused is not a run, but any other tool that ran, or a file tool that ran outside the copy, fails
the call and its answer is never used."""
import json
import subprocess

import pytest

from router import claude_worker, filecalls, plan_limit, safety

TOOLS_W = ["Read", "Edit", "Write", "Glob", "Grep", "WebSearch"]


class Fake:
    def __init__(self, events=(), returncode=0, result="done", init_tools=TOOLS_W, mcp=()):
        self.events, self.returncode, self.result = list(events), returncode, result
        self.init_tools, self.mcp, self.calls = init_tools, list(mcp), []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        stream = [{"type": "system", "subtype": "init", "tools": self.init_tools, "mcp_servers": self.mcp}]
        for i, (name, inp, error) in enumerate(self.events):
            stream.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"u{i}", "name": name,
                                                                          "input": inp}]}})
            stream.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"u{i}",
                                                                     "is_error": error, "content": "x"}]}})
        if self.result is not None:
            stream.append({"type": "result", "result": self.result, "is_error": False})
        return subprocess.CompletedProcess(argv, self.returncode, "\n".join(json.dumps(e) for e in stream), "")


def call(fake, folder, *, write=True, search=True):
    return claude_worker.run("the task", run=fake, environ={"HOME": "/h", "PATH": "/usr/bin", "SECRET": "x"},
                             copy=filecalls.CopySpec(folder, write, search))


def test_a_build_call_runs_in_the_copy_with_its_tools_and_answers(tmp_path):
    fake = Fake(events=[("Read", {"file_path": str(tmp_path / "a.py")}, False),
                        ("Edit", {"file_path": "a.py"}, False), ("WebSearch", {"query": "q"}, False)])
    answer = call(fake, tmp_path)
    argv, kw = fake.calls[0]
    assert argv == safety.claude_files_argv("sonnet", write=True, search=True)
    assert kw["cwd"] == tmp_path and kw["input"] == "the task" and sorted(kw["env"]) == ["HOME", "PATH"]
    assert str(answer) == "done" and answer.queries == ["q"]


def test_a_read_only_call_gets_the_read_tools(tmp_path):
    fake = Fake(init_tools=["Read", "Glob", "Grep"])
    call(fake, tmp_path, write=False, search=False)
    assert fake.calls[0][0] == safety.claude_files_argv("sonnet", write=False, search=False)


def test_a_command_claude_code_refused_is_not_a_run(tmp_path):
    assert call(Fake(events=[("Bash", {"command": "ls .."}, True)]), tmp_path) == "done"


@pytest.mark.parametrize("fake,words", [
    (dict(events=[("Bash", {"command": "ls"}, False)]), "a tool beyond the call's own ran: Bash"),
    (dict(events=[("Read", {"file_path": "/etc/hosts"}, False)]), "1 file tool call(s) outside the copy"),
    (dict(events=[("Glob", {"pattern": "*", "path": ".."}, False)]), "1 file tool call(s) outside the copy"),
    (dict(init_tools=TOOLS_W + ["Bash"]), "tools other than"),
    (dict(mcp=[{"name": "x"}]), "MCP server"),
])
def test_what_fails_a_file_mode_call(tmp_path, fake, words):
    with pytest.raises(claude_worker.WorkerError, match="file-mode call refused") as found:
        call(Fake(**fake), tmp_path)
    assert words in str(found.value)


def test_a_read_outside_that_claude_code_refused_is_fine(tmp_path):
    assert call(Fake(events=[("Read", {"file_path": "/etc/hosts"}, True)]), tmp_path) == "done"


def test_a_plan_limit_is_its_code(tmp_path):
    fake = Fake(result="You've hit your session limit · resets 3pm", returncode=1)
    with pytest.raises(claude_worker.WorkerError) as found:
        call(fake, tmp_path)
    assert found.value.code == plan_limit.CODE


def test_no_result_event_fails(tmp_path):
    with pytest.raises(claude_worker.WorkerError, match="no result event"):
        call(Fake(result=None, returncode=1), tmp_path)
