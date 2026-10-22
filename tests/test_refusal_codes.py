"""Build brief 21, A3 (rules v2.30, Router for the interface: "Every return and refusal has a reason_code"): the Phase 0
inventory as tests. Each refusal and return site marks its code on the command's `out` (a Receipt under --json), beside
the prose it prints, which never changes; a refusal writes no row. Fake agents, Jev and webhook only; every value here is
fake."""
import pytest

from router import __main__ as cli
from router import cursor_worker, log, projects, receipt
from tests.helpers import add_row, fake_label, roster_with, shipped_roster, set_local
from tests.test_context import HANDOFF_TEXT
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_relay import CONFIG, Chat, RelayHook
from tests.test_versus_run import LOADED, _versus

ROSTER = shipped_roster()
WRITING = {"status": "ok", "label": "writing", "confidence": 0.93, "needs_split": 0.1, "tokens": 0}


@pytest.fixture
def conn():
    c = log.init_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "config" / "projects.json")
    set_local(never_register=[str(tmp_path / "home" / "Projects" / "off-limits")])  # brief 25: a fake never_register folder
    folder = tmp_path / "demo"
    folder.mkdir()
    (folder / "HANDOFF.md").write_text(HANDOFF_TEXT)
    projects.add("demo", str(folder))
    return folder


def _route(conn, task="write a poem", *, label=WRITING, environ=None, config=CONFIG, roster=ROSTER, files=(), project=None,
           chat=None, cursor=None, cursor_ready=None):
    r, hook, clock = receipt.Receipt(), Webhook(), Clock()
    code = cli.cmd_route(task, conn=conn, config=config, roster=roster, environ=environ or {}, settings_paths=[],
                         label=fake_label(label), post=hook.post, worker=Scripted("done"), chatgpt=Chat("PASS"),
                         codex_login=lambda: True, cursor=cursor, cursor_ready=cursor_ready, fetch=hook.fetch,
                         close=hook.close, sleep=clock.sleep, clock=clock, wait=True, files=files, project=project,
                         chat=chat, out=r)
    return code, r


def _relay(conn, preset, task="write a poem", *, slots=(), files=(), project=None, roster=ROSTER, cursor_ready=None):
    r, hook, clock = receipt.Receipt(), RelayHook(), Clock()
    code = cli.cmd_relay(preset, task, conn=conn, config=CONFIG, roster=roster, loaded=LOADED, environ={},
                         settings_paths=[], post=hook.post, worker=Scripted(), chatgpt=Chat(), codex_login=lambda: True,
                         cursor=object(), cursor_ready=cursor_ready, fetch=hook.fetch, close=hook.close,
                         sleep=clock.sleep, clock=clock, wait=False, files=files, slots=slots, project=project, out=r)
    return code, r


def _assert_refused(conn, code, r, want, exit_code=2):
    assert (code, r.code) == (exit_code, want), r.message
    assert log.recent_tasks(conn) == [] or exit_code != 2


# ---------- route ----------

def test_a_missing_webhook_name_refuses_nothing(conn):
    code, r = _route(conn, config={})
    assert code == 0 and r.code is None and len(log.recent_tasks(conn)) == 1


@pytest.mark.parametrize("kwargs, want", [
    ({"environ": {"OPENAI_API_KEY": "sk-fake-not-a-key"}}, "billing_switch"),
    # brief 24 (decision 12): {"config": {}} refused `setup` here; a missing webhook name no longer refuses anything
    ({"task": "@muse write a poem"}, "not_live"),
    ({"task": "   "}, "bad_task"),
    ({"task": "/compact now"}, "bad_task"),
    ({"task": "@claude write a poem", "project": "demo"}, "override_refused"),
    ({"project": "nope"}, "project_unknown"),
    ({"chat": "Not A Name"}, "bad_name"),
    ({"task": "@cursor write code", "cursor": None}, "not_configured"),
])
def test_route_refusals(conn, registry, kwargs, want):
    code, r = _route(conn, **kwargs)
    _assert_refused(conn, code, r, want)


def test_a_billing_switch_wins_over_a_missing_value(conn):
    code, r = _route(conn, environ={"OPENAI_API_KEY": "sk-fake-not-a-key"}, config={})
    assert (code, r.code) == (2, "billing_switch")


def test_a_project_with_a_task_open_is_busy(conn, registry):
    log.add_task(conn, "sr-open", "t", "cli", WRITING, project="demo")
    code, r = _route(conn, project="demo")
    assert (code, r.code) == (2, "project_busy")


def test_a_project_whose_handoff_cannot_be_read_at_intake(conn, registry):
    (registry / "HANDOFF.md").unlink()
    code, r = _route(conn, project="demo")
    _assert_refused(conn, code, r, "handoff_unreadable")


@pytest.mark.parametrize("ready, want", [
    (cursor_worker.Readiness((False, "cursor: no sandbox probe pass on record; run sr probe"), code="probe_failed"),
     "probe_failed"),
    (cursor_worker.Readiness((False, "cursor: not signed in (agent login)"), code="signed_out"), "signed_out"),
])
def test_cursor_readiness_refusals_carry_their_code(conn, ready, want):
    code, r = _route(conn, task="@cursor write code", cursor=object(), cursor_ready=lambda: ready)
    _assert_refused(conn, code, r, want)
    code, r = _relay(conn, "versus", slots=[("b", "cursor")], cursor_ready=lambda: ready)
    _assert_refused(conn, code, r, want)


def test_a_bad_file_and_a_file_for_grok(conn, tmp_path):
    text = tmp_path / "notes.txt"
    text.write_text("hi")
    code, r = _route(conn, files=[text])
    _assert_refused(conn, code, r, "bad_file")
    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    code, r = _route(conn, task="@grok what is this", files=[png])
    _assert_refused(conn, code, r, "files_to_agent")


# ---------- relay ----------

@pytest.mark.parametrize("preset, kwargs, want", [
    ("versus", {"files": ("x.png",)}, "flag_refused"),
    (None, {}, "bad_preset"),
    ("nope", {}, "bad_preset"),
    ("versus", {"slots": [("zz", "claude")]}, "slot_refused"),
    ("versus", {"task": "@claude write"}, "override_refused"),
    ("versus", {"task": "   "}, "bad_task"),
    ("versus", {"project": "demo"}, "tag_refused"),
    ("vote", {"task": "x" * 4000}, "too_long"),
])
def test_relay_refusals(conn, registry, preset, kwargs, want):
    code, r = _relay(conn, preset, **kwargs)
    _assert_refused(conn, code, r, want)


def test_a_cursor_slot_with_a_project_is_a_tag_refusal(conn, registry):
    code, r = _relay(conn, "versus", slots=[("b", "cursor")], project="demo")
    _assert_refused(conn, code, r, "tag_refused")
    code, r = _relay(conn, "research-build", slots=[("build", "cursor")])  # a slot Cursor may not fill
    _assert_refused(conn, code, r, "slot_refused")


# ---------- split ----------

def _split(conn, task="list trays and write a haiku", *, files=(), preset=None, roster=ROSTER):
    r, hook, clock = receipt.Receipt(), RelayHook(), Clock()
    code = cli.cmd_split(task, conn=conn, config=CONFIG, roster=roster, environ={}, settings_paths=[],
                         label=fake_label(WRITING), ask=None, post=hook.post, worker=Scripted(), chatgpt=Chat(),
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         files=files, preset=preset, out=r)
    return code, r


@pytest.mark.parametrize("kwargs, want", [({"files": ("x.png",)}, "flag_refused"), ({"preset": "versus"}, "flag_refused"),
                                          ({"task": "@grok split this"}, "override_refused"), ({"task": "  "}, "bad_task"),
                                          ({"roster": roster_with(claude=False)}, "not_live")])
def test_split_refusals(conn, kwargs, want):
    code, r = _split(conn, **kwargs)
    _assert_refused(conn, code, r, want)


def _go(conn, command, words):
    r, hook, clock = receipt.Receipt(), RelayHook(), Clock()
    code = command(words, conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[],
                   label=fake_label(WRITING), ask=None, post=hook.post, worker=Scripted(), chatgpt=Chat(),
                   codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, out=r)
    return code, r


@pytest.mark.parametrize("command", [cli.cmd_split_go, cli.cmd_split_skip])
def test_split_go_and_skip_refusals(conn, command):
    assert _go(conn, command, [])[1].code == "usage"
    assert _go(conn, command, ["7"])[1].code == "unknown_task"
    add_row(conn, "sr-a", task="a routed task")
    code, r = _go(conn, command, ["1"])
    assert (code, r.code, r.task_id) == (2, "wrong_state", "sr-a")


# ---------- pick ----------

def _pick(conn, words):
    r = receipt.Receipt()
    return cli.cmd_pick(words, conn=conn, loaded=LOADED, out=r), r


def test_pick_refusals(conn):
    assert _pick(conn, ["1"])[1].code == "usage"
    assert _pick(conn, ["9", "a"])[1].code == "unknown_task"
    _versus(conn)
    assert _pick(conn, ["1", "q"])[1].code == "usage"
    code, r = _pick(conn, ["1", "c"])
    assert (code, r.code, r.task_id) == (2, "usage", log.task_by_number(conn, 1)["task_id"])
    assert _pick(conn, ["1", "a"])[0] == 0
    code, r = _pick(conn, ["1", "b"])
    assert (code, r.code) == (2, "already_used")
    add_row(conn, "sr-b", task="routed")
    assert _pick(conn, ["2", "a"])[1].code == "wrong_state"


# ---------- resume, fallback ----------

def _rescue(conn, command, words):
    r, hook, clock = receipt.Receipt(), Webhook(), Clock()
    code = command(words, conn=conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[],
                   post=hook.post, worker=Scripted(), chatgpt=Chat(), codex_login=lambda: True, fetch=hook.fetch,
                   close=hook.close, sleep=clock.sleep, clock=clock, wait=True, out=r)
    return code, r


def _passed(conn):
    _route(conn, label=WRITING)
    return log.recent_tasks(conn)[0]


@pytest.mark.parametrize("command, want", [(cli.cmd_resume, "not_resumable"), (cli.cmd_fallback, "no_fallback")])
def test_resume_and_fallback_refusals(conn, command, want):
    assert _rescue(conn, command, ["abc"])[1].code == "usage"
    assert _rescue(conn, command, ["5"])[1].code == "unknown_task"
    row = _passed(conn)
    code, r = _rescue(conn, command, [str(row["n"])])
    assert (code, r.code, r.task_id) == (2, want, row["task_id"])


def test_resume_of_an_open_task_is_wrong_state(conn):
    add_row(conn, "sr-a")
    assert _rescue(conn, cli.cmd_resume, ["1"])[1].code == "wrong_state"


def test_the_deciders_name_their_codes():
    from router import fallback, resume
    assert resume.decide({"status": "queued", "n": 1}, [], live=None).code == "wrong_state"
    assert fallback.decide({"route_reason": "override", "mode": "route", "skill": "writing"}, [], live=None).code == "no_fallback"


# ---------- cancel, check ----------

def _cancel(conn, words):
    r = receipt.Receipt()
    return cli.cmd_cancel(conn=conn, words=words, out=r), r


def test_cancel_refusals(conn):
    assert _cancel(conn, [])[1].code == "wrong_state"  # nothing open
    add_row(conn, "sr-a")
    add_row(conn, "sr-b")
    assert _cancel(conn, [])[1].code == "ambiguous_task"
    assert _cancel(conn, ["abc"])[1].code == "usage"
    assert _cancel(conn, ["#9"])[1].code == "unknown_task"
    code, r = _cancel(conn, ["1"])
    assert (code, r.code, r.task_id) == (0, None, "sr-a")
    code, r = _cancel(conn, ["1"])
    assert (code, r.code, r.task_id) == (1, "wrong_state", "sr-a")


def test_check_marks_only_its_own_refusals(conn):
    hook = Webhook()
    r = receipt.Receipt(multi=True)
    code = cli.cmd_check(conn=conn, config=CONFIG, environ={"OPENAI_API_KEY": "sk-fake"}, settings_paths=[],
                         post=hook.post, worker=Scripted(), fetch=hook.fetch, close=hook.close, out=r)
    assert (code, r.code) == (2, "billing_switch")
    add_row(conn, "sr-g", agent="grok")
    log.set_sent(conn, "sr-g", "uuid")

    def broken():
        raise RuntimeError("gh is gone")
    r = receipt.Receipt(multi=True)
    code = cli.cmd_check(conn=conn, config=CONFIG, environ={}, settings_paths=[], post=hook.post, worker=Scripted(),
                         fetch=broken, close=hook.close, out=r)
    assert (code, r.code) == (1, "inbox_unreadable")


def test_a_return_inside_check_is_not_the_checks_code(conn):
    r = receipt.Receipt(multi=True)
    receipt.mark(r, code="needs_label", task_id="sr-x")  # a deeper mark, about one task
    assert (r.code, r.task_id) == (None, None)
    receipt.mark(r, code="inbox_unreadable", command=True)
    assert r.code == "inbox_unreadable"


# ---------- project, chat ----------

def test_project_and_chat_refusals(conn, registry, tmp_path):
    r = receipt.Receipt()
    assert (cli.cmd_project(["bogus"], conn=conn, out=r), r.code) == (2, "usage")
    r = receipt.Receipt()
    assert (cli.cmd_project(["add", "x", str(tmp_path / "missing")], conn=conn, out=r), r.code) == (2, "project_refused")
    r = receipt.Receipt()
    assert (cli.cmd_project(["remove", "nope"], conn=conn, out=r), r.code) == (2, "project_unknown")
    r = receipt.Receipt()
    assert (cli.cmd_chat(["bogus"], conn=conn, out=r), r.code) == (2, "usage")


# ---------- every code used is in the vocabulary ----------

def test_every_marked_code_is_known():
    import re
    from pathlib import Path
    text = Path(cli.__file__).read_text()
    found = set(re.findall(r'code="([a-z_]+)"', text)) | set(re.findall(r"code='([a-z_]+)'", text))
    assert found and found <= set(receipt.REFUSAL_CODES) | set(log.RETURN_CODES), found - set(receipt.REFUSAL_CODES)
