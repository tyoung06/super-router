"""`sr status` (rules v2.30, Status and JSON and Router for the interface; build brief 21, B2): what the page reads
about the router itself: each agent (live, configured, online by a check that is never a model call, model, the model
that last served, version, probe state, calls this week), the presets intake accepts with their chains and slots, the
skills, the commands from the parser, the open tasks with what each waits on, Jev's monthly meter (never its key),
memory, projects, chats and the settings a page needs. Built from the config, the log (read-only), probe_state.json and
the checks it is handed; nothing here writes anything or calls an agent. The JSON goes through the redactor in main."""
import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path

from router import (auto, availability, claude_worker, cursor_worker, filemode, files_probe, gitops, ideas, jev, jsonview, log,
                    memory, models, notes, plan, presets, probes, projects, projrun, projsecrets, projtest, routing, runs, safety,
                    search, settings, teams, testrun, spec)

AGENTS = ("claude", "chatgpt", "grok", "cursor")  # rules: Claude, ChatGPT, Grok Bot and Cursor; Muse is deferred
NAMES = presets.CHAIN_NAMES  # brief 29: the chain's words live in router/presets.py, read by the split's menu too
ROLE_WORDS = presets.ROLE_WORDS
PROBE_KEYS = {"claude": search.SEARCH_KEY, "cursor": "cursor_sandbox", "chatgpt": "codex_sandbox"}  # brief 24: Codex too
RULES_VERSION = re.compile(r"^Version (\d+\.\d+)\b")


chain = presets.chain  # brief 29: one chain for status's presets and the split's menu


def preset_view(preset, live, fill=None):
    """A preset for the page. `live` are the agents a slot may offer: the available ones (brief 24, decision 14: a slot's
    `allowed` lists only available agents). `fill` (decision 8) answers (filled, fills, why) for it as intake would now:
    `ready`, the refusal's words in `why`, and how its slots are filled."""
    agents = list(dict.fromkeys([s.agent for s in preset.stages] + ([preset.checker] if preset.checker else [])))
    slots = [{"name": s.name, "default": s.default,
              "allowed": [a for a in live if presets.slot_allowed(a, preset.name, s.name)],
              # brief 32 (decision 13): the agents a --project task refuses in this slot, so the page offers the others
              "project_refuses": presets.project_refuses_in(preset.name, s.name)} for s in preset.slots]
    filled, fills, why = fill(preset) if fill is not None else (preset, [], None)
    return {"name": preset.name, "description": preset.description, "chain": chain(preset), "agents": agents,
            "slots": slots,
            # brief 23 (decision 14): whether intake takes --project on it, and which slot agents a project task refuses
            "project": presets.takes_project(preset), "project_refuses": list(presets.PROJECT_REFUSES),
            # brief 29.1 (decision 27): versus in file mode takes Claude and ChatGPT only, so Grok too is refused there
            "file_mode_refuses": ["grok"] if preset.has_reviews else [],
            "ready": filled is not None, "why": why, "filled": fills}


def skills_view(roster, available=None):
    """Each skill, and (brief 24, decision 14) what happens to it now: `now` from routing.now_for."""
    return [{"key": key, "description": skill.get("description"), "not_for": skill.get("not_for"),
             "best": skill.get("best"), "second": skill.get("second"), "now": routing.now_for(key, roster, available),
             "routed": key not in roster.not_routed}  # brief 29.1 (decision 3): the not_routed card's chips
            for key, skill in roster.skills.items()]


def commands_view(parser):
    """Every subcommand and its flags, read from the parser itself, so nothing outside `sr` has to know them."""
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    helps = {a.dest: a.help for a in sub._choices_actions}
    found = []
    for name, command in sub.choices.items():
        arguments = []
        for action in command._actions:
            if isinstance(action, argparse._HelpAction):
                continue
            if action.option_strings:
                kind = "flag" if action.nargs == 0 else "option"
                arguments.append({"name": action.option_strings[-1], "kind": kind, "help": action.help})
            else:
                arguments.append({"name": action.dest, "kind": "positional", "nargs": action.nargs, "help": action.help})
        found.append({"name": name, "help": helps.get(name), "arguments": arguments})
    return found


def _probe(name, state_path, current):
    """{passed_on, current, state}: `passed` when the pass on record is on the installed version, `moved` when it is on
    another, `missing` when there is none, `unknown` when the installed version can't be read; `failed` or `could_not_run`
    on the installed version (brief 22). ChatGPT's Codex probe keeps a pass per Codex version since brief 24 (decision
    10), as Cursor's does; Grok has none (None)."""
    if name == "grok":
        return None

    def passed(key):  # brief 32 (R0): a Cursor pass counts only with every canary of the probe it ran
        return cursor_worker.passed_version(state_path) if key == PROBE_KEYS["cursor"] else search.passed_version(state_path, key)

    def word(key):
        passed_on = passed(key)
        if current is not None and passed_on == current:
            return "passed"
        failed = probes.failure(state_path, key)  # brief 22: ran and failed, or could not run, on this version
        if current is not None and failed is not None and failed.get("version") == current:
            return "failed" if failed.get("kind") == probes.RAN_FAILED else "could_not_run"
        if passed_on is None:
            return "missing"
        return "unknown" if current is None else "moved"
    found = {"passed_on": passed(PROBE_KEYS[name]), "current": current,
             "state": word(PROBE_KEYS[name])}
    if name == "claude":
        found["web_files"] = word(search.WEB_FILES)
        found["files"] = word(files_probe.KEY)  # brief 28 (decision 19): Claude's file check, per version
        failed = probes.failure(state_path, files_probe.KEY)
        if failed is not None:  # brief 30 (A2): its record, with what a failed check found (names only)
            found["files_failure"] = failed
    return found


def monday(now):
    """Monday 00:00 of `now`'s week, local time (decision 9)."""
    local = now.astimezone()
    start = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=local.weekday())
    return start


def calls_this_week(conn, now):
    """Call rows per agent since Monday 00:00 local: calls, never tokens, never a plan percentage."""
    if conn is None:
        return {}
    since = log._iso(monday(now))
    return {r[0]: r[1] for r in conn.execute("SELECT agent, COUNT(*) FROM calls WHERE sent_at >= ? GROUP BY agent", (since,))}


def served_model(conn, name):
    """The model that served the agent's newest call that names one (calls.served, a Cursor call), or None."""
    if conn is None:
        return None
    row = conn.execute("SELECT served FROM calls WHERE agent = ? AND served IS NOT NULL ORDER BY rowid DESC LIMIT 1",
                       (name,)).fetchone()
    found = log.served_of(row) if row is not None else None
    return found.get("model") if found else None


def configured(name, roster, env, doc=None):
    """Whether an agent is set up to run: in config/agents.json, with its pinned model (ChatGPT, Cursor), or its webhook
    values in .env and the inbox repo in settings (Grok; build brief 24, decision 1). Only a configured agent is checked;
    the values are tested for presence, never shown. `doc` is the settings (read when not given)."""
    return _configured(name, roster, env, doc)


def _configured(name, roster, env, doc=None):
    if roster is None or name not in roster.agents:
        return False
    doc = settings.read() if doc is None else doc
    return availability.set_up(name, roster, availability.env_names(env), doc) is None


def agents_view(conn, roster, env, online, versions, state_path, now, avail=None):
    """Each agent's card. Build brief 24 (decision 14): `available` and `why` (with `why_code`) from
    router/availability.py, computed from the same checks, so the page reads availability and never works it out."""
    week = calls_this_week(conn, now)
    avail = avail or {}
    found = []
    for name in AGENTS:
        configured = _configured(name, roster, env)
        if roster is None:
            check = {"online": None, "checked_at": None, "reason": "config/agents.json could not be read"}
        elif not configured:
            check = {"online": None, "checked_at": None, "reason": "not configured"}
        else:
            check = online.get(name) or {"online": None, "checked_at": None, "reason": None}
        version = versions.get(name) if name != "grok" else None
        version = None if version in (None, "unknown") else version
        model = claude_worker.WORKER_MODEL if name == "claude" else roster.model(name) if roster is not None else None
        found.append({
            "name": name,
            "live": bool(roster is not None and name in roster.agents and roster.agents[name]["live"] is True),
            "configured": configured,
            "online": check["online"],
            "checked_at": check["checked_at"],
            "reason": check["reason"],
            "model": model if configured else None,
            "served_model": served_model(conn, name),
            "version": version,
            "probe": _probe(name, state_path, version),
            "calls_this_week": week.get(name, 0),
            **(avail.get(name) or availability.Availability(False, f"{availability.name_of(name)} isn't in "
                                                                    "config/agents.json", "not_live")).as_dict(),
        })
    return found


def memory_view(client, starting=False, installed=False):
    """The setting, and the store's state from its /health and the bank's document count; `starting` while a start
    holds the memory lock (brief 22, decision 8), only while memory is on: `sr memory off` holds it to stop the store;
    `installed`, whether Hindsight's binary is there (brief 27, decision 9)."""
    setting = settings.memory_mode()
    found = {"setting": setting, "online": False, "starting": bool(starting) and setting != "off", "documents": None,
             "installed": bool(installed),
             # brief 29.1 (decision 25): the block's newest tasks and its search matches, from config/settings.json
             "newest": settings.memory_setting("memory_newest")[0],
             "matches": settings.memory_setting("memory_matches")[0],
             # the memory brief (fixes 1 and 2): a bad setting, or a memory_url off this Mac, said; None when fine
             "problem": settings.memory_problem()}
    if client is None:
        return found
    url = getattr(client, "url", None)  # a stand-in client may carry none
    if found["problem"] is None and url is not None and not memory.on_this_mac(url):
        found["problem"] = memory.OFF_HOST
    try:
        found["online"] = bool(client.online())
        if found["online"]:
            found["documents"] = client.stats().get("total_documents")
    except Exception:  # a store that answers /health and then fails reads as no count
        pass
    return found


def _files_view(folder, state_path, claude_version):
    """Brief 28 (decision 19): a project's git and file mode as the page reads them; read only (no check, no test, no
    write). `files_mode` off says why in the card's words."""
    try:
        decision = filemode.view(folder, state_path=state_path, version=claude_version)
    except Exception:  # a folder git can't read still lists; the page shows why
        return {"git": False, "branch": None, "head": None, "files_mode": "off", "why": "its git could not be read"}
    repo = decision.repo
    return {"git": bool(repo and repo.git), "branch": repo.branch if repo else None,
            "head": gitops.short(repo.head) if repo and repo.head else None, **decision.as_dict()}


def projects_view(conn, state_path=None, claude_version=None, run_folder=None, claude_ok=None):
    try:
        registry = projects.read_registry()
    except projects.ProjectError:
        return []
    found = []
    run_folder = run_folder if run_folder is not None else runs.FOLDER  # brief 31: Test and Run records beside the log
    for name in sorted(registry):
        row = log.open_task_for(conn, name) if conn is not None else None
        try:
            lines = projects.line_count(projects.read_handoff(registry[name]))
        except projects.ProjectError:
            lines = None
        files = _files_view(registry[name], state_path, claude_version)
        # brief 34 (decision 10): the switch's state judged with Claude's availability and the file check as status read
        # them, so Off means `--on` would be accepted now
        auto_entry = (auto.project_entry(conn, name, claude_ok=True if claude_ok is None else bool(claude_ok),
                                         files_ready=lambda f=files: (f.get("files_mode") == "on", f.get("why")))
                      if conn is not None else None)
        found.append({"name": name, "path": str(registry[name]), "handoff_lines": lines,
                      "open_task": {"task_id": row["task_id"], "n": row["n"], "status": row["status"]} if row else None,
                      "tests": projects.tests_of(name),  # brief 28 (decision 17): the words, or null
                      "last_test": projtest.last_view(name, run_folder),  # brief 31 (decision 11)
                      "test_running": projtest.running(name, run_folder=run_folder),  # break-ui 3
                      "run_command": projrun.run_command_of(name), "run": projrun.view(name, run_folder),
                      "secrets": projsecrets.count(registry[name]),  # brief 31 (decision 11): how many, never which
                      "ideas": ideas.open_count(conn, name) if conn is not None else 0,  # brief 33 (decision 18)
                      "plan": plan.project_view(conn, name) if conn is not None else None,  # brief 33.1 (decision 19)
                      "auto": auto_entry,  # brief 34 (decision 10)
                      "spec": spec.summary(registry[name]),  # brief 33.2 (decision 19): present, hash, the labels
                      **files})
    return found


def git_view():
    """Brief 28 (decision 19): whether git is installed on this Mac, and its version."""
    return {"installed": gitops.installed(), "version": gitops.version()}


def test_sandbox_view():
    """Brief 28 (decision 5): whether the router can run a project's tests here, and why not."""
    ok = testrun.available()
    return {"available": ok, "why": None if ok else "this Mac has no sandbox-exec, so no project's tests run"}


def chats_view(conn):
    if conn is None:
        return []
    return [{"name": r["chat"], "tasks": r["count"], "newest": r["newest"]} for r in log.chats(conn)]


def _running(conn):
    """Every run on a task but a suggest's (brief 33.4, decision 10b: a running suggest leaves status as it is)."""
    found = runs.running(conn)
    if conn is None or not found:
        return found
    hidden = {r["task_id"] for r in conn.execute("SELECT task_id FROM tasks WHERE mode = 'suggest'")}
    return [item for item in found if item["task_id"] not in hidden]


def open_tasks(conn, live, loaded):
    """Every task that has not ended (no outcome), oldest first, as the log rows show them."""
    if conn is None:
        return []
    rows = conn.execute("SELECT rowid AS n, * FROM tasks WHERE mode != 'suggest' AND (status IN ('queued', 'sent', 'returned') OR "
                        "(status = 'done' AND json_extract(project_files, '$.state') = 'waiting')) ORDER BY rowid")  # brief 28: waiting to land
    found = []
    for row in rows:
        view = jsonview.task_view(conn, row, live=live, loaded=loaded)
        if view["outcome"] is None:
            found.append(view)
    return found


# Brief 25 (P2): the rules file, then its cleaned copy (made at each publish; a public clone carries only that one).
RULES_FILES = ("SUPER-ROUTER.md", "docs/RULES.md")


def rules_file(root):
    """Where `sr status` reads the rules version: the first of RULES_FILES under `root` that exists, else the first."""
    root = Path(root)
    return next((root / name for name in RULES_FILES if (root / name).is_file()), root / RULES_FILES[0])


def rules_version(path):
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return None
    m = RULES_VERSION.match(lines[2]) if len(lines) > 2 else None
    return m.group(1) if m else None


def availability_of(roster, env, online, versions, state_path, now=None):
    """{agent: Availability} for the four agents, from what `sr status` already read (decision 14): the .env names
    present, the settings, the online checks, probe_state.json and the installed versions. Runs nothing."""
    if roster is None:
        return {}
    data = probes._read(state_path) if state_path is not None else {}
    return {name: availability.of(name, roster=roster, names=availability.env_names(env), doc=settings.read(),
                                  online=online, probe_data=data, versions=versions,
                                  now=(now or datetime.now().astimezone()))
            for name in AGENTS if name in roster.agents}


def auto_entry(claude):
    """Brief 34: whether `sr auto --on` could start now on a project with a plan: Claude available (the steps' teams need
    it, as a split does) and the test sandbox available; the words say why not."""
    ready, why = teams.split_ready(claude) if claude is not None else (False, "Claude isn't checked")
    sandbox = test_sandbox_view()
    if ready and not sandbox.get("available"):
        ready, why = False, f"the test sandbox isn't available: {sandbox.get('why')}"
    return {"ready": bool(ready), "why": None if ready else why}


def build(conn, *, roster, loaded, env, parser, online, versions, state_path, memory_client, drop_folder, rules_path,
          now=None, log_version=None, memory_starting=False, send_paths=None, contracts=None, roles=None, verdicts=(),
          memory_installed=False, run_folder=None):
    """The `sr status --json` document. `conn` is the log read-only, or None when there is none yet (or it is not this
    router's version). `log_version` is the log file's own version (the code's when there is no file yet), so a page sees
    a log that wants `sr migrate`."""
    now = now or datetime.now().astimezone()
    live = roster.live if roster is not None else ()
    tokens = log.jev_tokens_this_month(conn) if conn is not None else 0
    avail = availability_of(roster, env, online, versions, state_path, now)
    jev_avail = availability.jev(availability.env_names(env))
    table = (lambda name: avail.get(name) or availability.Availability(False, f"{availability.name_of(name)} is off",
                                                                       "not_live"))
    offered = [a for a in live if table(a).available]  # brief 24: a slot offers only available agents

    def fill(preset):
        if send_paths is None or roster is None:
            return preset, [], None
        return presets.fill_unavailable(preset, [], roster, table, send_paths=send_paths, contracts=contracts,
                                        roles=roles, verdicts=verdicts)
    found = {
        "agents": agents_view(conn, roster, env, online, versions, state_path, now, avail),
        "presets": [preset_view(p, offered, fill) for p in loaded.presets.values()] if loaded is not None else [],
        # brief 29 (decision 2): split's readiness (the function `sr split`'s intake calls), its words, chain and menu
        "split": teams.split_entry(loaded, roster, table, send_paths=send_paths) if roster is not None and send_paths
        else None,
        # brief 33.1 (decision 19): Plan's readiness, its words, its chain (redteam's as filled now, in its plan shape) and
        # its calls, as `split` has them
        "plan": plan.status_entry(loaded, roster, table, send_paths=send_paths) if roster is not None and send_paths
        else None,
        # brief 34 (decision 14): Auto's readiness: Claude available and the test sandbox there (each step runs the tests)
        "auto": auto_entry(table("claude") if roster is not None else None) if roster is not None else None,
        "skills": skills_view(roster, table) if roster is not None else [],
        "commands": commands_view(parser),
        # brief 33.4 (decisions 12 and 15): the caps the page enforces or states; the router never refuses an over-cap idea
        "limits": {"idea_max": settings.next_steps_setting("idea_max")[0], "ideas_max": settings.next_steps_setting("ideas_max")[0]},
        "open_tasks": open_tasks(conn, live if roster is not None else None, loaded),
        "running": _running(conn),  # brief 22 (decision 4): every run on a task; a JSON read never writes
        "jev": {"configured": bool((env.get("JEV_API_KEY") or "").strip()), "tokens_month": tokens,
                "cap": jev.MONTHLY_TOKEN_CAP, "over_cap": tokens >= jev.MONTHLY_TOKEN_CAP,
                # brief 23 (decision 14): the labeler's floor, so the page never hardcodes 0.80
                "floor": roster.labeler.get("min_confidence") if roster is not None else None,
                # brief 29.1 (decision 24): a tagged task's floor, beside it
                "tagged_floor": roster.labeler.get("tagged_min_confidence") if roster is not None else None,
                # brief 24 (decisions 13 and 14): whether Jev labels at all, and why not in words
                "available": jev_avail.available, "why": jev_avail.why},
        "memory": memory_view(memory_client, starting=memory_starting, installed=memory_installed),
        "projects": projects_view(conn, state_path, (versions or {}).get("claude"), run_folder,
                                  claude_ok=table("claude").available if roster is not None else None),
        "git": git_view(),  # brief 28 (decision 19)
        "test_sandbox": test_sandbox_view(),  # brief 28 (decision 5): status says why tests are off
        # brief 30 (decision 9): the router notes' state (with why and line), each section's characters, the total, the
        # cap, Grok's share and limit, and the hash; never their text
        "notes": notes.view(notes.read(safety.env_secrets(env or {}))),
        # brief 33.3 (decision 11): the model defaults, the allowlists, the Fable switch, Claude's Opus and Fable calls this
        # week, what each role would use now and Setup's rows
        "models": models.status_view(conn, roster, loaded, table, send_paths=send_paths or tuple(),
                                     since=log._iso(monday(now)),
                                     skills_now={key: routing.now_for(key, roster, table) for key in roster.skills}
                                     if roster is not None else {}),
        "chats": chats_view(conn),
        "drop_folder": str(drop_folder) if drop_folder else None,
        "serve_port": settings.serve_port(),
        "projects_root": settings.projects_root_written(),  # brief 26 (decision 8): as written
    }
    report = settings.report_path()
    if report:
        found["report_path"] = report
    found.update({"version": rules_version(rules_path),
                  "log_version": log.VERSION if log_version is None else log_version, "api_version": jsonview.API_VERSION})
    return found


def lines(doc):
    """`sr status` without --json: the same document, a few lines a person reads."""
    out = ["Agents:"]
    for a in doc["agents"]:
        online = ("online" if a["online"] else f"offline ({a['reason']})" if a["online"] is False
                  else a["reason"] or "not checked")
        probe = f", probe {a['probe']['state']}" if a["probe"] else ""
        out.append(f"  {a['name']:<8} {'live' if a['live'] else 'off':<5} {online}; version {a['version'] or '-'}{probe}; "
                   f"{a['calls_this_week']} calls this week")
    out.append(f"Open tasks: {len(doc['open_tasks'])}")
    for t in doc["open_tasks"]:
        out.append(f"  #{t['n']} {t['task_id']}  {t['waiting_on'] or 'in progress'}")
    for r in doc.get("running", []):  # brief 22
        how = {True: "alive", False: "ended; sr check marks it", None: "can't tell"}[r["alive"]]
        out.append(f"Running: #{r['n']} {r['task_id']} pid {r['pid']} since {r['since']} ({how})")
    j = doc["jev"]
    out.append(f"Jev: {j['tokens_month']:,} of {j['cap']:,} input tokens this month" + (" (over the cap)" if j["over_cap"] else ""))
    m = doc["memory"]
    out.append(f"Memory: {m['setting']}, {'online' if m['online'] else 'offline'}"
               + (f", {m['documents']} documents" if m["documents"] is not None else "")
               + (f" ({m['problem']})" if m.get("problem") else ""))
    out.append(f"Rules {doc['version'] or '?'}, log version {doc['log_version']}")
    return out
