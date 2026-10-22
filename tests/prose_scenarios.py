"""Build brief 21, A0: what `sr` prints today, recorded before any brief 21 code, so every later phase can prove the
prose is unchanged without `--json` (the brief's "prose output unchanged without --json"). Each scenario runs the real
command functions with fake agents, a fake Jev and a fake webhook, and returns (exit code, the lines printed). Task ids
come from a counter and local times are masked, so a run is the same every time. Not a test file itself:
tests/test_prose_unchanged.py runs these against tests/fixtures/prose_v13.json. Every value here is fake."""
import contextlib
import io
import re

from router import __main__ as cli
from router import ids, log, presets, projects, relay
from tests.helpers import add_row, fake_label, shipped_roster
from tests.test_loop import Clock, Scripted, Webhook
from tests.test_relay import Chat, RelayHook

CONFIG = {"GROK_WEBHOOK_URL": "https://example.invalid/hook", "GROK_WEBHOOK_KEY": "FAKE-KEY-123"}
ROSTER = shipped_roster()
LOADED = presets.load_presets(ROSTER, tuple(cli.SENDERS), relay.CONTRACTS, roles=relay.ROLES, verdicts=relay.VERDICTS)
TIME = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")


def jev(label, confidence=0.93, status="ok"):
    return {"status": status, "label": label, "confidence": confidence, "needs_split": 0.1, "tokens": 700}


A_TEXT = "CANDIDATE-A: the SimTee adjusts to any height on any mat."
B_TEXT = "CANDIDATE-B: one tray, every mat, every height."
REVIEW_OF_A = "## Verdict\npass\n\n## Notes\n- Wrong: nothing.\n- Strong: clear."
REVIEW_OF_B = "## Verdict\nfail\n\n## Notes\n- Wrong: it invents a spec.\n- Strong: short."
PLAN = "## Pieces\n1. List three garden seed tray brands.\n2. Write a haiku about trays.\n\n## Join\nPut the list above the haiku."


def vote_answer(answer):
    return f"## Answer\n{answer}\n\n## Why\nBecause it is.\n\n## Confidence\n80"


class Run:
    """One scenario's world: an in-memory log, deterministic task ids, the lines printed."""

    def __init__(self, monkeypatch, tmp_path):
        self.conn = log.init_db(":memory:")
        self.lines = []
        self.count = 0
        monkeypatch.setattr(ids, "new_task_id", self._next_id)
        monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "config" / "projects.json")

    def _next_id(self, now=None):
        self.count += 1
        return f"sr-20261020-000000-{self.count:04x}"

    def out(self, line=""):
        self.lines.append(TIME.sub("<time>", str(line)))

    def result(self, code):
        return {"exit": code, "lines": list(self.lines)}

    def route(self, task, label, *, worker=None, chatgpt=None, hook=None, wait=True, environ=None, ask=None):
        clock, hook = Clock(), hook or Webhook()
        return cli.cmd_route(task, conn=self.conn, config=CONFIG, roster=ROSTER, environ=environ or {}, settings_paths=[],
                             label=fake_label(label), post=hook.post, worker=worker or Scripted(),
                             chatgpt=chatgpt or Chat("PASS"), codex_login=lambda: True, fetch=hook.fetch,
                             close=hook.close, sleep=clock.sleep, clock=clock, wait=wait, ask=ask, out=self.out)

    def relay(self, preset, task, *, worker, chatgpt, hook=None, wait=True):
        clock, hook = Clock(), hook or RelayHook()
        return cli.cmd_relay(preset, task, conn=self.conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={},
                             settings_paths=[], post=hook.post, worker=worker, chatgpt=chatgpt, codex_login=lambda: True,
                             fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=wait, out=self.out)

    def rescue(self, command, words):
        clock, hook = Clock(), Webhook()
        return command(words, conn=self.conn, config=CONFIG, roster=ROSTER, loaded=LOADED, environ={}, settings_paths=[],
                       post=hook.post, worker=Scripted(), chatgpt=Chat(), codex_login=lambda: True, fetch=hook.fetch,
                       close=hook.close, sleep=clock.sleep, clock=clock, wait=True, out=self.out)

    def passed_task(self):
        """A routed writing task Claude did and ChatGPT passed, made quietly (its lines are not the scenario's)."""
        keep, self.lines = self.lines, []
        self.route("write a two-line poem about trays", jev("writing"), worker=Scripted("Trays stand tall.\nGarden goes on."))
        self.lines = keep

    def versus_task(self):
        keep, self.lines = self.lines, []
        self.relay("versus", "a 20-word blurb for a seed tray", worker=Scripted(A_TEXT, REVIEW_OF_B),
                   chatgpt=Chat(B_TEXT, REVIEW_OF_A))
        self.lines = keep


# ---------- the scenarios: name -> function(run) -> exit code ----------

def route_refused_billing_switch(r):
    return r.route("write a poem", jev("writing"), environ={"OPENAI_API_KEY": "sk-fake-not-a-key"})


def route_refused_empty(r):
    return r.route("   ", jev("writing"))


def route_refused_agent_not_live(r):
    return r.route("@muse write a poem", jev("writing"))


def route_returned_needs_label(r):
    return r.route("write something", jev("writing", 0.5, "below_floor"))


def route_returned_needs_tag(r):
    return r.route("what did we decide about the tray", jev("recall", 0.97))


def route_quick_answer(r):
    return r.route("what is 17 times 23", jev("quick_answer", 0.99), worker=Scripted("391"))


def route_passed(r):
    return r.route("write a two-line poem about trays", jev("writing"), worker=Scripted("Trays stand tall.\nGarden goes on."))


def route_fixed(r):
    return r.route("write a two-line poem about trays", jev("writing"), worker=Scripted("Draft one.", "Draft two."),
                   chatgpt=Chat("FIX\n1. Make it rhyme.", "PASS"))


def route_not_passed(r):
    return r.route("write a two-line poem about trays", jev("writing"), worker=Scripted("Draft one.", "Draft two."),
                   chatgpt=Chat("FIX\n1. Make it rhyme.", "FIX\n1. It still does not rhyme."))


def route_failed_first_call(r):
    return r.route("write a two-line poem about trays", jev("writing"), worker=Scripted(RuntimeError("boom")))


def route_grok_not_waiting(r):
    return r.route("what are gardeners saying about trays on X", jev("x_social_pulse", 0.95), wait=False)


def relay_refused_no_preset(r):
    return r.relay(None, "a task", worker=Scripted(), chatgpt=Chat())


def relay_versus_awaiting_pick(r):
    return r.relay("versus", "a 20-word blurb for a seed tray", worker=Scripted(A_TEXT, REVIEW_OF_B),
                   chatgpt=Chat(B_TEXT, REVIEW_OF_A))


def relay_vote_majority(r):
    return r.relay("vote", "what is the capital of France", worker=Scripted(vote_answer("Paris")),
                   chatgpt=Chat(vote_answer("Paris")), hook=RelayHook(s3=vote_answer("Lyon")))


def split_plan_without_a_terminal(r):
    clock, hook = Clock(), Webhook()
    return cli.cmd_split("list three tray brands and write a haiku about trays", conn=r.conn, config=CONFIG, roster=ROSTER,
                         environ={}, settings_paths=[], label=fake_label(jev("writing")), ask=None, post=hook.post,
                         worker=Scripted(PLAN), chatgpt=Chat(), codex_login=lambda: True, fetch=hook.fetch,
                         close=hook.close, sleep=clock.sleep, clock=clock, wait=True, out=r.out)


def pick_a(r):
    r.versus_task()
    return cli.cmd_pick(["1", "a"], conn=r.conn, loaded=LOADED, out=r.out)


def pick_refused_not_versus(r):
    r.passed_task()
    return cli.cmd_pick(["1", "a"], conn=r.conn, loaded=LOADED, out=r.out)


def resume_refused_passed(r):
    r.passed_task()
    return r.rescue(cli.cmd_resume, ["1"])


def resume_refused_unknown(r):
    return r.rescue(cli.cmd_resume, ["7"])


def fallback_refused_passed(r):
    r.passed_task()
    return r.rescue(cli.cmd_fallback, ["#1"])


def cancel_nothing_open(r):
    return cli.cmd_cancel(conn=r.conn, words=[], out=r.out)


def cancel_a_queued_task(r):
    add_row(r.conn, "sr-20261020-000000-00aa", task="write a poem")
    return cli.cmd_cancel(conn=r.conn, words=["1"], out=r.out)


def check_nothing_open(r):
    hook = Webhook()
    return cli.cmd_check(conn=r.conn, config=CONFIG, environ={}, settings_paths=[], post=hook.post, worker=Scripted(),
                         chatgpt=Chat(), codex_login=lambda: True, fetch=hook.fetch, close=hook.close, presets=LOADED,
                         roster=ROSTER, out=r.out)


def project_list_empty(r):
    return cli.cmd_project(["list"], conn=r.conn, out=r.out)


def project_usage(r):
    return cli.cmd_project(["bogus"], conn=r.conn, out=r.out)


def chat_list_empty(r):
    return cli.cmd_chat(["list"], conn=r.conn, out=r.out)


def show_passed(r):
    r.passed_task()
    return cli.cmd_show(conn=r.conn, words=["1"], roster=ROSTER, presets=LOADED, out=r.out)


def show_versus_awaiting(r):
    r.versus_task()
    return cli.cmd_show(conn=r.conn, words=["1"], roster=ROSTER, presets=LOADED, out=r.out)


def log_two_tasks(r):
    r.passed_task()
    r.versus_task()
    return cli.cmd_log(conn=r.conn, out=r.out)


def _main(r, argv):
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        code = cli.main(argv)
    for line in printed.getvalue().splitlines():
        r.out(line)
    return code


def main_slot_flag_on_route(r):
    return _main(r, ["route", "--build", "claude", "write a poem"])


def main_web_on_relay(r):
    return _main(r, ["relay", "versus", "write a poem", "--web"])


SCENARIOS = {f.__name__: f for f in (
    route_refused_billing_switch, route_refused_empty, route_refused_agent_not_live, route_returned_needs_label,
    route_returned_needs_tag, route_quick_answer, route_passed, route_fixed, route_not_passed, route_failed_first_call,
    route_grok_not_waiting, relay_refused_no_preset, relay_versus_awaiting_pick, relay_vote_majority,
    split_plan_without_a_terminal, pick_a, pick_refused_not_versus, resume_refused_passed, resume_refused_unknown,
    fallback_refused_passed, cancel_nothing_open, cancel_a_queued_task, check_nothing_open, project_list_empty,
    project_usage, chat_list_empty, show_passed, show_versus_awaiting, log_two_tasks, main_slot_flag_on_route,
    main_web_on_relay,
)}


def run(name, monkeypatch, tmp_path):
    r = Run(monkeypatch, tmp_path)
    try:
        return r.result(SCENARIOS[name](r))
    finally:
        r.conn.close()
