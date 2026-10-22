"""Is an agent available for a task (build brief 24, decisions 1, 2, 12 and 13)? All three must hold:

(a) its live flag is on in config/agents.json;
(b) it is set up and answering: Claude signed in with the plan; ChatGPT with a pinned model and `codex` signed in with
    ChatGPT; Grok Bot with GROK_WEBHOOK_URL and GROK_WEBHOOK_KEY in .env, the inbox repo set (`grok_inbox_repo`) and
    that repo answering a read; Cursor with a pinned Grok model and `agent` signed in;
(c) no safety check has failed on the installed version (Cursor's canaries, ChatGPT's Codex probe).

`of` is pure: it reads what it is handed (the roster; which .env names hold a value, never the values; the settings;
the online checks' answers from router/online.py; probe_state.json's contents; the installed versions) and runs
nothing. Status, intake, the takeover and the split's plan preview all read it. A preview hands it no online answers, so
it judges only what runs nothing (live, set up, the probe records). The reason is plain words for a person ("Grok Bot
isn't set up: no inbox repo in settings"), with a code beside it for the JSON and the refusals.

`Gate` is the one impure part: it gathers those inputs for one command, runs the online checks for the agents asked
about (side by side, each at most once per command unless asked fresh), and answers with `of`."""
from dataclasses import dataclass
from datetime import datetime, timezone

from router import probes, settings

NAMES = {"claude": "Claude", "chatgpt": "ChatGPT", "grok": "Grok Bot", "cursor": "Cursor", "muse": "Muse"}
CODES = ("not_live", "not_configured", "signed_out", "unreachable", "probe_failed")
MODEL_PINNED = {"chatgpt": "ChatGPT isn't set up: no model pinned in config/agents.json",
                "cursor": "Cursor isn't set up: no Grok model pinned in config/agents.json"}
WEBHOOK_NAMES = ("GROK_WEBHOOK_URL", "GROK_WEBHOOK_KEY")
SIGN_IN = {"claude": "claude auth login", "chatgpt": "codex login", "cursor": "agent login"}
PROBE = {"chatgpt": ("codex_sandbox", "codex"), "cursor": ("cursor_sandbox", "agent")}  # key, the tool's name
JEV_KEY = "JEV_API_KEY"


@dataclass(frozen=True)
class Availability:
    available: bool
    why: str | None = None   # plain words when it is not available
    code: str | None = None  # one of CODES when it is not available

    def as_dict(self):
        return {"available": self.available, "why": self.why, "why_code": self.code}


YES = Availability(True)


def name_of(agent):
    return NAMES.get(agent, agent)


def env_names(config):
    """The .env names that hold a value, never the values (decision 1: presence only)."""
    return frozenset(k for k, v in (config or {}).items() if isinstance(v, str) and v.strip())


def _no(why, code):
    return Availability(False, why, code)


def set_up(agent, roster, names, doc):
    """Why `agent` isn't set up (b's first half), or None: a pinned model (ChatGPT, Cursor); Grok's two webhook names in
    .env and a usable `grok_inbox_repo`. Status's `configured` reads it too."""
    if agent in MODEL_PINNED and not roster.model(agent):
        return MODEL_PINNED[agent]
    if agent == "grok":
        missing = [n for n in WEBHOOK_NAMES if n not in names]
        parts = [f"no {' or '.join(missing)} in .env"] if missing else []
        repo, problem = settings.inbox_repo(doc or {})
        if repo is None:
            parts.append(problem)
        if parts:
            return "Grok Bot isn't set up: " + "; ".join(parts)
    return None


def _probe(agent, data, versions, now):
    """Why `agent`'s safety check holds it back on the installed version (c), or None: a check that ran and failed stays
    for that version; one that could not run holds for an hour (router/probes.py)."""
    if agent not in PROBE:
        return None
    key, tool = PROBE[agent]
    version = (versions or {}).get(agent)
    if not version or version == "unknown":
        return None  # nothing to compare; the online check and the call itself still stand
    found = probes.held_back_in(data, key, version, now)
    if found is None:
        return None
    if found.get("kind") == probes.RAN_FAILED:
        return f"{name_of(agent)} is off: its safety check failed on {tool} {version}"
    return (f"{name_of(agent)} is off for now: its safety check could not run on {tool} {version}; it is tried again "
            f"{probes.retry_at(found)}")


def _answer(agent, check):
    """Why the online check says no (b's second half), with its code, or None when it answered yes or was not run."""
    if not check or check.get("online") is not False:
        return None
    reason, code = check.get("reason") or "it did not answer", check.get("code")
    name = name_of(agent)
    if code == "signed_out":
        return f"{name} is signed out ({SIGN_IN.get(agent, 'sign in again')})", code
    if code == "not_configured":
        return f"{name} isn't set up: {reason}", code
    return f"{name} can't be reached: {reason}", "unreachable"


CLAUDE_TRYING = "Claude's sign-in check didn't answer; trying anyway"  # The owner's decision 2 after F


def of(agent, *, roster, names, doc=None, online=None, probe_data=None, versions=None, now=None):
    """The availability of one agent. `names` are the .env names that hold a value (`env_names`); `doc` the settings
    (router/settings.py, read); `online` {agent: run_all's answer} (None, or an agent missing from it: not checked, as a
    preview); `probe_data` probe_state.json's contents; `versions` {agent: installed version}."""
    if roster is None or agent not in roster.agents or roster.agents[agent].get("live") is not True:
        return _no(f"{name_of(agent)} is off: not live in config/agents.json", "not_live")
    why = set_up(agent, roster, names, doc)
    if why:
        return _no(why, "not_configured")
    why = _probe(agent, probe_data, versions, now)
    if why:
        return _no(why, "probe_failed")
    found = _answer(agent, (online or {}).get(agent))
    if found and agent == "claude" and found[1] == "unreachable":
        # The owner (brief 24, after F): Claude is required, so a sign-in check that didn't answer twice never refuses on
        # its own; the task goes ahead with this warning, the call itself decides, and a real failure is taken over
        return Availability(True, CLAUDE_TRYING, "unreachable")
    if found:
        return _no(*found)
    return YES


def agents(roster, *, names, doc=None, online=None, probe_data=None, versions=None, now=None):
    """{agent: Availability} for every agent in the roster, in its order."""
    return {a: of(a, roster=roster, names=names, doc=doc, online=online, probe_data=probe_data, versions=versions,
                  now=now) for a in (roster.agents if roster is not None else ())}


def jev(names):
    """Jev is available when JEV_API_KEY holds a value (decision 13; presence only, never a call)."""
    if JEV_KEY in names:
        return YES
    return _no(f"Jev isn't set up: no {JEV_KEY} in .env", "not_configured")


def everyone(roster):
    """A table that says every live agent is available and every other one is not live, for the code paths and tests
    that hand no gate (today's behaviour before this brief: live was enough)."""
    return {a: (YES if roster.agents[a].get("live") is True else
                _no(f"{name_of(a)} is off: not live in config/agents.json", "not_live")) for a in roster.agents}


class Gate:
    """One command's availability (decision 1), checked when the task comes in with the checks router/online.py makes
    (never a model call, never the webhook). `of(names)` runs the online checks of the named agents that have not been
    checked in this command yet, side by side, and answers for each; `fresh=True` checks them again (a takeover, minutes
    later). Every input is read here: the .env names (presence only), the settings, probe_state.json and the installed
    versions (only when a failure on record needs one). A version that can't be read is unknown, never a crash."""

    def __init__(self, roster, config, *, checks, run_all, probe_path=None, versions=None, read_settings=None,
                 now=None):
        self.roster, self.names = roster, env_names(config)
        self.checks, self.run_all = checks, run_all
        self.probe_path, self.versions = probe_path, versions or {}
        self.read_settings = read_settings or settings.read
        self.now = now
        self._answers, self._versions = {}, {}

    def _probe_data(self):
        if self.probe_path is None:
            return {}
        return probes._read(self.probe_path)

    def _version(self, agent, data):
        """The installed version, read once per command and only when a failure on record needs comparing."""
        key = PROBE.get(agent, (None,))[0]
        if key is None or f"{key}_failure" not in data or agent not in self.versions:
            return None
        if agent not in self._versions:
            try:
                self._versions[agent] = self.versions[agent]()
            except Exception:  # a version read that blows up is unknown, never a crash of a command
                self._versions[agent] = "unknown"
        return self._versions[agent]

    def of(self, names, fresh=False):
        wanted = [n for n in dict.fromkeys(names) if n is not None]
        doc, data = self.read_settings(), self._probe_data()
        configured = [n for n in wanted if n in self.checks and (fresh or n not in self._answers)
                      and of(n, roster=self.roster, names=self.names, doc=doc).available]
        if configured:
            self._answers.update(self.run_all({n: self.checks[n] for n in configured}))
        now = self.now() if callable(self.now) else (self.now or datetime.now(timezone.utc))
        return {n: of(n, roster=self.roster, names=self.names, doc=doc, online=self._answers,
                      probe_data=data, versions={n: self._version(n, data)}, now=now) for n in wanted}

    def __call__(self, name, fresh=False):
        return self.of([name], fresh=fresh)[name]
