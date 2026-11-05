"""Build brief 28 (decisions 5 and 17; Tests, "The test runner"): the project's tests, run by the router in a sandbox it
builds. The sandboxed runs use the real `/usr/bin/sandbox-exec` and skip where it is missing; every fake key and nonce is
made here at run time. A run's "home folder" is a folder the test names, so no test writes under the owner's home."""
import os
import secrets
import socket
import sys
import textwrap
import threading
import time
import venv
from pathlib import Path

import pytest

from router import testrun

needs_sandbox = pytest.mark.skipif(not testrun.available(), reason="sandbox-exec is not on this machine")


# ---------- the words ----------

def test_the_words_are_split_as_a_shell_would_and_never_run_through_one():
    assert testrun.split_words("python3 -m unittest") == ["python3", "-m", "unittest"]
    assert testrun.split_words("pytest -k 'add and not slow'") == ["pytest", "-k", "add and not slow"]
    assert testrun.split_words("echo $HOME; rm -rf /") == ["echo", "$HOME;", "rm", "-rf", "/"]  # words, no shell


@pytest.mark.parametrize("text,why", [
    ("", "empty"), ("   ", "empty"), ("x" * 301, "at most 300"), ("python3 'unclosed", "can't be split"),
    ("python3\n-m", "control character"),
])
def test_a_command_that_cant_be_stored_is_refused(text, why):
    with pytest.raises(testrun.TestsError, match=why):
        testrun.split_words(text)


def test_an_environment_first_word_must_be_in_the_project(tmp_path):
    assert testrun.check_words(["python3", "-m", "unittest"], tmp_path) is None
    assert "is not in the project folder" in testrun.check_words([".venv/bin/python", "-m", "unittest"], tmp_path)
    (tmp_path / "venv" / "bin").mkdir(parents=True)
    (tmp_path / "venv" / "bin" / "python").write_text("")
    assert testrun.check_words(["venv/bin/python"], tmp_path) is None
    assert "leaves its environment folder" in testrun.check_words([".venv/../../outside"], tmp_path)
    assert testrun.env_folder([".venv/bin/python"], tmp_path) == tmp_path / ".venv"
    assert testrun.env_folder(["python3"], tmp_path) is None


# ---------- the profile and the environment ----------

def test_the_profile_denies_by_default_and_names_what_it_allows(tmp_path):
    home = tmp_path / "home"
    text = testrun.profile(tmp_path / "throw", home=home, env=home / "proj" / ".venv")
    lines = text.splitlines()
    assert lines[:2] == ["(version 1)", "(deny default)"]
    assert "network" not in text and "mach-lookup" not in text and "ipc-posix" not in text
    deny = next(i for i, line in enumerate(lines) if line.startswith("(deny file-read* (subpath"))
    system = next(i for i, line in enumerate(lines) if line.startswith('(allow file-read* (literal "/")'))
    env = next(i for i, line in enumerate(lines) if line == f'(allow file-read* (subpath "{home / "proj" / ".venv"}"))')
    assert system < deny < env  # the last rule that matches wins: the home folder's deny after the system reads
    writes = [line for line in lines if "file-write" in line]
    assert all(str(tmp_path / "throw") in line or "/dev/null" in line for line in writes)
    assert f'(subpath "{tmp_path / "throw"}")' not in text  # the throwaway's own folder is not writable, only its three


def test_the_environment_is_four_names_built_from_scratch(tmp_path):
    home = tmp_path / "home"
    (home / "bin").mkdir(parents=True)
    fake = "fake" + secrets.token_hex(12)
    environ = {"PATH": f"{home / 'bin'}:/usr/bin:/bin", "LANG": "en_GB.UTF-8", "FAKE_API_KEY": fake, "HOME": str(home),
               "SECRET_TOKEN": fake}
    env = testrun.environment(tmp_path / "throw", environ, home)
    assert sorted(env) == ["HOME", "LANG", "PATH", "TMPDIR"]
    assert env["PATH"] == "/usr/bin:/bin" and env["LANG"] == "en_GB.UTF-8"
    assert env["HOME"] == str(tmp_path / "throw" / "home") and env["TMPDIR"] == str(tmp_path / "throw" / "tmp") + "/"
    assert fake not in repr(env)


def test_the_tests_line():
    assert testrun.line(None) == "no tests run: no test command"
    assert testrun.line({"outcome": "passed", "exit": 0}) == "tests passed"
    assert testrun.line({"outcome": "failed", "exit": 1}) == "tests failed (exit 1)"
    assert testrun.line({"outcome": "timed_out", "exit": None}) == "tests timed out"


# ---------- real runs ----------

@pytest.fixture
def sandbox(real_git):
    real_git.add("sandbox-exec")
    return real_git


def project(tmp_path, tests):
    folder = tmp_path / "copy"
    folder.mkdir()
    for name, body in tests.items():
        (folder / name).write_text(textwrap.dedent(body).lstrip())
    return folder


def run(folder, words, tmp_path, **kw):
    kw.setdefault("home", tmp_path / "home")
    return testrun.run(folder, words, project_folder=kw.pop("project_folder", folder), **kw)


def digest(folder):
    return sorted((p.relative_to(folder).as_posix(), p.read_bytes() if p.is_file() else b"")
                  for p in Path(folder).rglob("*") if "__pycache__" not in p.parts)


PASSING = """
    import unittest

    class Passing(unittest.TestCase):
        def test_adds(self):
            self.assertEqual(1 + 1, 2)
    """


@needs_sandbox
def test_a_passing_suite_passes_and_the_copy_is_unchanged(sandbox, tmp_path):
    folder = project(tmp_path, {"test_ok.py": PASSING})
    before = digest(folder)
    result = run(folder, ["python3", "-m", "unittest"], tmp_path)
    assert (result.exit, result.outcome, result.summary) == (0, "passed", "OK")
    assert "Ran 1 test" in result.output
    assert digest(folder) == before and not (folder / "__pycache__").exists()


@needs_sandbox
def test_a_failing_suite_fails_with_its_exit_code(sandbox, tmp_path):
    folder = project(tmp_path, {"test_bad.py": PASSING.replace("1 + 1, 2", "1 + 1, 3")})
    result = run(folder, ["python3", "-m", "unittest"], tmp_path)
    assert (result.exit, result.outcome) == (1, "failed") and result.summary == "FAILED (failures=1)"


@needs_sandbox
def test_reads_under_the_home_folder_fail_even_where_the_system_reads_are_allowed(sandbox, tmp_path):
    # the run's "home folder" is a system folder python never needs: only the home rule can refuse this read
    folder = project(tmp_path, {"test_read.py": """
        import unittest

        class Reads(unittest.TestCase):
            def test_reads(self):
                print(open("/usr/share/dict/words").read(10))
        """})
    if not Path("/usr/share/dict/words").exists():
        pytest.skip("no /usr/share/dict/words to read")
    allowed = run(folder, ["python3", "-m", "unittest"], tmp_path)
    assert allowed.outcome == "passed"
    refused = run(folder, ["python3", "-m", "unittest"], tmp_path, home="/usr/share/dict")
    assert refused.outcome == "failed" and "Operation not permitted" in refused.output


@needs_sandbox
def test_a_canary_beside_the_throwaway_and_a_siblings_env_cant_be_read(sandbox, tmp_path):
    canary = "canary-" + secrets.token_hex(12)
    env_nonce = "env-" + secrets.token_hex(12)
    (tmp_path / "canary.txt").write_text(canary)
    (tmp_path / "sibling").mkdir()
    (tmp_path / "sibling" / ".env").write_text(f"TOKEN={env_nonce}\n")
    folder = project(tmp_path, {"test_read.py": f"""
        import unittest

        class Reads(unittest.TestCase):
            def test_canary(self):
                print(open({str(tmp_path / 'canary.txt')!r}).read())

            def test_sibling_env(self):
                print(open({str(tmp_path / 'sibling' / '.env')!r}).read())
        """})
    result = run(folder, ["python3", "-m", "unittest"], tmp_path, home=tmp_path)
    assert result.outcome == "failed" and result.output.count("Operation not permitted") == 2
    assert canary not in result.output and env_nonce not in result.output


@needs_sandbox
def test_writing_one_folder_up_fails(sandbox, tmp_path):
    folder = project(tmp_path, {"test_write.py": """
        import os, unittest

        class Writes(unittest.TestCase):
            def test_up(self):
                open(os.path.join("..", "escaped.txt"), "w").write("x")
        """})
    result = run(folder, ["python3", "-m", "unittest"], tmp_path)
    assert result.outcome == "failed" and "Operation not permitted" in result.output


@needs_sandbox
def test_a_local_listener_cant_be_reached(sandbox, tmp_path):
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(0.2)
    got = []

    def accept():
        for _ in range(30):
            try:
                got.append(server.accept())
            except OSError:
                continue
    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    folder = project(tmp_path, {"test_net.py": f"""
        import socket, unittest

        class Net(unittest.TestCase):
            def test_connect(self):
                socket.create_connection(("127.0.0.1", {server.getsockname()[1]}), timeout=2).close()
        """})
    result = run(folder, ["python3", "-m", "unittest"], tmp_path)
    thread.join()
    server.close()
    assert result.outcome == "failed" and "Operation not permitted" in result.output and got == []


@needs_sandbox
def test_the_child_environment_holds_no_key(sandbox, tmp_path):
    fake = "fakekey" + secrets.token_hex(12)
    folder = project(tmp_path, {"test_env.py": """
        import os, unittest

        class Env(unittest.TestCase):
            def test_env(self):
                print("ENV", sorted(os.environ))
                print("VALUES", sorted(os.environ.values()))
        """})
    environ = {**os.environ, "SR_FAKE_API_KEY": fake, "OTHER_TOKEN": fake}
    result = run(folder, ["python3", "-m", "unittest"], tmp_path, environ=environ)
    assert result.outcome == "passed"
    assert "ENV ['HOME', 'LANG', 'PATH', 'TMPDIR']" in result.output and fake not in result.output


@needs_sandbox
def test_the_time_limit_kills_the_whole_group(sandbox, tmp_path):
    folder = project(tmp_path, {"test_sleep.py": """
        import subprocess, sys, time, unittest

        class Sleeps(unittest.TestCase):
            def test_sleeps(self):
                child = subprocess.Popen([sys.executable, "-c",
                    "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"])
                print("CHILD", child.pid, flush=True)
                time.sleep(60)
        """})
    started = time.monotonic()
    result = run(folder, ["python3", "-m", "unittest"], tmp_path, timeout=2)
    assert time.monotonic() - started < 10
    assert (result.exit, result.outcome, result.summary) == (None, "timed_out", "timed out after 2 s")
    pid = int(result.output.split("CHILD", 1)[1].split()[0])
    for _ in range(40):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("the test's child outlived the time limit")


@needs_sandbox
def test_the_output_is_redacted_and_cut_to_its_tail(sandbox, tmp_path):
    secret = "secretvalue" + secrets.token_hex(8)
    folder = project(tmp_path, {"test_noise.py": f"""
        import unittest

        class Noise(unittest.TestCase):
            def test_noise(self):
                print("head-marker " + "x" * 30000)
                print("the value is {secret}")
        """})
    result = run(folder, ["python3", "-m", "unittest"], tmp_path, secrets=(secret,))
    assert len(result.output) == testrun.OUTPUT_CHARS
    assert secret not in result.output and "[REDACTED]" in result.output and "head-marker" not in result.output


@needs_sandbox
def test_a_venv_first_word_runs_the_projects_environment_read_only(sandbox, tmp_path):
    home = tmp_path / "home"
    proj = home / "proj"
    proj.mkdir(parents=True)
    venv.create(proj / ".venv", with_pip=False)
    nonce = "projenv-" + secrets.token_hex(12)
    (proj / ".env").write_text(f"TOKEN={nonce}\n")
    folder = project(tmp_path, {"test_venv.py": f"""
        import sys, unittest

        class Venv(unittest.TestCase):
            def test_prefix(self):
                self.assertTrue(sys.prefix.endswith(".venv"), sys.prefix)

            def test_reads_project_env(self):
                print(open({str(proj / '.env')!r}).read())

            def test_writes_into_venv(self):
                open({str(proj / '.venv' / 'planted.txt')!r}, "w").write("x")
        """})
    result = run(folder, [".venv/bin/python", "-m", "unittest", "-v"], tmp_path, home=home, project_folder=proj)
    assert "test_prefix (test_venv.Venv.test_prefix) ... ok" in result.output
    assert result.output.count("Operation not permitted") == 2 and nonce not in result.output
    assert not (proj / ".venv" / "planted.txt").exists()


def test_a_missing_sandbox_is_said(monkeypatch):
    monkeypatch.setattr(testrun, "SANDBOX_EXEC", "/nonexistent/sandbox-exec")
    assert testrun.available() is False
