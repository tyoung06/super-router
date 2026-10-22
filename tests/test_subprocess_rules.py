"""Source scan: router code never uses a shell, never skips permissions, never sleeps or opens processes directly."""
import re
from pathlib import Path

ROUTER = Path(__file__).resolve().parent.parent / "router"
# time.sleep( and subprocess.Popen( are banned too: waits and processes are passed in, so tests use fakes.
FORBIDDEN = re.compile(r"shell\s*=\s*True|os\.system\(|os\.popen\(|dangerously-skip-permissions|--bare\b"
                       r"|dangerously-bypass|danger-full-access|workspace-write"
                       r"|time\.sleep\(|subprocess\.Popen\(")


def test_router_source_never_uses_a_shell_or_unsafe_claude_flags():
    hits = [
        f"{path.name}:{number}"
        for path in sorted(ROUTER.glob("*.py"))
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if FORBIDDEN.search(line)
    ]
    assert hits == []
