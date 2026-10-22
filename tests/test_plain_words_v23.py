"""Build brief 23, decision 5 with the owner's two changes of 20 Oct: no line a person reads tells them to run `sr probe` or
`sr memory`; Cursor's check has one name, its "safety check", in every Cursor line, and the router "checks it before
Cursor's next task" (a failed check is not run again until Cursor updates). The recall lines' branch on the memory
setting is in tests/test_recall_store.py. Choice 18 (the owner's yes): an `agent status` that doesn't answer reads as "did
not answer", never as signed out. Fakes only; no command runs."""
import ast
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from router import cursor_worker, probes, search
from tests.test_auto_probe import A1, A2, CursorCanaries, _cursor
from tests.test_cursor_worker import ENVIRON

ROUTER = Path(__file__).resolve().parent.parent / "router"
T0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
# What no person-readable router line may say any more (docstrings and comments are not lines a person reads).
FORBIDDEN = ("run sr probe", "(sr memory start)", "says online", "sandbox probe", "sandbox check", "cursor sandbox")


def _strings(tree):
    """Every string literal in a module, f-string parts included, except docstrings: (line, text)."""
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node.lineno, node.value


def test_no_router_line_tells_a_person_to_run_sr_probe_or_sr_memory_or_names_a_sandbox_check():
    found = []
    for path in sorted(ROUTER.glob("*.py")):
        for line, text in _strings(ast.parse(path.read_text(encoding="utf-8"))):
            found += [f"{path.name}:{line}: {phrase}" for phrase in FORBIDDEN if phrase in text.lower()]
    assert found == []


def test_the_sweep_would_catch_an_old_line():
    tree = ast.parse('"""a docstring may say run sr probe"""\nx = "cursor: no pass; run sr probe"\n')
    assert [text for _, text in _strings(tree)] == ["cursor: no pass; run sr probe"]


# ---------- Cursor: one name, and what the router does next ----------

def _state(tmp_path, version=None):
    path = tmp_path / "probe_state.json"
    if version is not None:
        search.record_pass(path, version, key=cursor_worker.SANDBOX_KEY)
    return path


class StatusFake:
    """`agent --version` answers; `agent status` answers `status`, or raises `raises`."""

    def __init__(self, raises=None, status="✓ Logged in as t@example.com", version="2026.10.16-e3cb207\n"):
        self.raises, self.status, self.version, self.calls = raises, status, version, []

    def __call__(self, argv, **kwargs):
        assert isinstance(argv, list) and not kwargs.get("shell")
        self.calls.append(argv)
        if argv[:2] == ["agent", "status"]:
            if self.raises is not None:
                raise self.raises
            return subprocess.CompletedProcess(argv, 0, self.status + "\n", "")
        if argv[:2] == ["agent", "--version"]:
            return subprocess.CompletedProcess(argv, 0, self.version, "")
        raise AssertionError(f"no model call in a readiness check: {argv}")


def test_the_three_readiness_reasons_say_safety_check_and_what_the_router_does(tmp_path):
    found = cursor_worker.ready(_state(tmp_path), run=StatusFake(), environ=ENVIRON)
    assert tuple(found) == (False, "cursor: no safety check on record for Cursor yet; the router checks it before Cursor's next "
                                   "task") and found.code == "probe_failed"
    moved = tmp_path / "moved"
    moved.mkdir()
    found = cursor_worker.ready(_state(moved, "2026.10.16-e3cb207"), run=StatusFake(version="2026.11.01-abcd\n"), environ=ENVIRON)
    assert tuple(found) == (False, "cursor: Cursor updated to 2026.11.01-abcd since its safety check; the router checks the new "
                                   "version before Cursor's next task") and found.code == "probe_failed"
    gone = tmp_path / "gone"
    gone.mkdir()
    found = cursor_worker.ready(_state(gone, "2026.10.16-e3cb207"), run=StatusFake(version=""), environ=ENVIRON)
    assert tuple(found) == (False, "cursor: Cursor's command line gave no version (is it installed?)") and found.code == "probe_failed"


def test_the_two_held_back_lines_say_safety_check(tmp_path):
    path = _state(tmp_path)
    probes.record_failure(path, cursor_worker.SANDBOX_KEY, A2, probes.RAN_FAILED, "read canary: x", now=T0)
    found = probes._cursor_held_back(path, A2, T0)
    assert found[1] == f"Cursor's safety check failed on agent {A2} (read canary: x); Cursor stays off on this version"
    probes.record_failure(path, cursor_worker.SANDBOX_KEY, A2, probes.COULD_NOT_RUN, "agent timed out", now=T0)
    found = probes._cursor_held_back(path, A2, T0)
    assert found[1].startswith(f"Cursor's safety check could not run on agent {A2} (agent timed out); it is tried again after ")
    assert found.code == "probe_failed"


def test_the_canary_progress_lines_say_safety_check(tmp_path):
    path = _state(tmp_path, A1)
    canaries, out = CursorCanaries(path, A2), []
    assert tuple(_cursor(path, A2, canaries, out)) == (True, None) and canaries.ran == 1
    assert out == [f"probe: Cursor's safety check has no pass on agent {A2}; running its two canaries (two pool calls)",
                   f"probe: Cursor's safety check passed on agent {A2}"]


# ---------- choice 18: a status check that doesn't answer is not "signed out" ----------

def test_cursor_online_reads_a_timeout_as_did_not_answer_never_as_signed_out():
    timeout = subprocess.TimeoutExpired(["agent", "status"], 10)
    assert cursor_worker.online(run=StatusFake(raises=timeout), environ=ENVIRON) == (False, "agent status did not answer (TimeoutExpired)")
    assert cursor_worker.online(run=StatusFake(raises=OSError("gone")), environ=ENVIRON) == (False, "agent status did not answer (OSError)")
    assert cursor_worker.online(run=StatusFake(status="Not logged in"), environ=ENVIRON) == (False, "not signed in (agent login)")
    assert cursor_worker.online(run=StatusFake(), environ=ENVIRON) == (True, None)


def test_the_readiness_check_reads_a_status_timeout_as_did_not_answer(tmp_path):
    fake = StatusFake(raises=subprocess.TimeoutExpired(["agent", "status"], 10))
    found = cursor_worker.ready(_state(tmp_path, "2026.10.16-e3cb207"), run=fake, environ=ENVIRON)
    assert tuple(found) == (False, "cursor: agent status did not answer (TimeoutExpired)") and found.code == "signed_out"
    assert fake.calls == [["agent", "--version"], ["agent", "status"]]


def test_login_status_stays_true_only_when_signed_in():
    assert cursor_worker.login_status(run=StatusFake(), environ=ENVIRON) is True
    assert cursor_worker.login_status(run=StatusFake(raises=subprocess.TimeoutExpired(["agent"], 10)), environ=ENVIRON) is False
    assert cursor_worker.login_status(run=StatusFake(status="Not logged in"), environ=ENVIRON) is False
