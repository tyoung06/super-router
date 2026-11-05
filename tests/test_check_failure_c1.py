"""Cleanup 1 (2.1): the real worker, on the recorded shape of #159's stderr, through a task: the row, the note, the output
and the JSON's card fields name the capacity error and hold none of the prompt's words. Fakes only; no model call."""
import functools

from router import chatgpt_worker, log
from tests.test_chatgpt_worker import ENVIRON, MODEL, CodexFake
from tests.test_filemode_flow import BUILD, CopyWorker, conn, project, route, runner  # noqa: F401 (fixtures)

CAPACITY = "ERROR: Selected model is at capacity. Please try a different model."


class Echoing(CodexFake):
    """Codex's failure as #159's row shows it: its stderr holds the prompt it was given, then the error, twice."""

    def __call__(self, argv, **kwargs):
        self.stderr = f"{kwargs['input']}\n{CAPACITY}\n{CAPACITY}\n"
        return super().__call__(argv, **kwargs)


def test_a_capacity_error_on_a_check_names_itself_on_the_row_the_note_and_the_output(project, conn, runner):
    chat = functools.partial(chatgpt_worker.run, model=MODEL, run=Echoing(returncode=1), environ=ENVIRON)
    code, out, row = route(conn, worker=CopyWorker(BUILD), chatgpt=chat)
    failed = next(c for c in log.calls_for(conn, row["task_id"]) if c["kind"] == "check")
    words = f"codex exited 1: {CAPACITY}"
    assert failed["status"] == "failed" and failed["text"] == words
    assert row["check_state"] == "unchecked" and row["check_note"] == f"check round by chatgpt didn't run: {words}"
    assert words in out
    assert "what it says is done" not in failed["text"] and "what it says is done" not in row["check_note"]
