"""Build brief 23 (Tests, Page): the page's logic is pure functions in static/app.js, tested with `node --test` and no npm
package (tests/js/). This runs them from pytest, as an argument list, so one `pytest` covers the page too; on a machine
without node it skips with the reason."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS_TESTS = ROOT / "tests" / "js"
REAL_POPEN = subprocess.Popen  # taken at import: conftest blocks real subprocesses in every test, and node is this test's one


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed: the page's logic tests need `node --test`")
def test_the_pages_logic_passes_node_test(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", REAL_POPEN)
    files = sorted(str(p) for p in JS_TESTS.glob("*.test.js"))
    assert files, "no tests/js/*.test.js"
    proc = subprocess.run(["node", "--test", *files], cwd=str(ROOT), capture_output=True, text=True, timeout=120,
                          stdin=subprocess.DEVNULL)
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]
