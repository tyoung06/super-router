"""Build brief 21: the JSON shapes as a test fixture, with no new dependency (brief 13's idea on `uiprep`, retyped): a
shape maps each key to the JSON types it may hold; `None` means null; a nested dict is a sub-shape; a one-item list is
"a list of this shape"; `ANY` is anything. `check` names the first key that is missing, extra or of the wrong type."""
STR, INT, NUM, BOOL, NULL, LIST, DICT = str, int, (int, float), bool, type(None), list, dict
ANY = object

OFFER_FALLBACK = {"ok": BOOL, "agent": (STR, NULL), "reason": (STR, NULL)}
OFFER_RESUME = {"ok": BOOL, "substitute": (STR, NULL), "agent": (STR, NULL), "checker": (STR, NULL), "reason": (STR, NULL)}
JEV = {"status": STR, "label": (STR, NULL), "confidence": (NUM, NULL), "tokens": INT, "needs_split": (NUM, NULL),
       "error": (STR, NULL)}
TASK = {
    "task_id": STR, "n": INT, "created_at": STR, "updated_at": STR, "sent_at": (STR, NULL), "source": STR, "text": STR,
    "status": STR, "waiting_on": (STR, NULL), "outcome": (STR, NULL), "reason_code": (STR, NULL), "mode": STR,
    "preset": (STR, NULL), "parent": (STR, NULL), "project": (STR, NULL), "chat": (STR, NULL), "tag": (STR, NULL),
    "skill": (STR, NULL), "skill_source": (STR, NULL), "agent": (STR, NULL), "checker": (STR, NULL),
    "check_state": (STR, NULL), "check_note": (STR, NULL), "route_reason": (STR, NULL), "failed_stage": (INT, NULL),
    "web": BOOL, "files": LIST, "result": (STR, NULL), "result_url": (STR, NULL), "jev": JEV, "slots": (DICT, NULL),
    "working": (DICT, NULL),
    "steps": (DICT, NULL),  # the small UI cleanup, row 1: the task's own chain and the call in progress, derived
    "fallback": OFFER_FALLBACK, "resume": OFFER_RESUME,
    "pid": (INT, NULL), "run_started_at": (STR, NULL), "answered_by": (STR, NULL),  # brief 22
    "stand_in": (DICT, NULL), "filled": (LIST, NULL), "card_line": (STR, NULL),  # brief 24 (decision 14)
    "takeover": (DICT, NULL), "late": (DICT, NULL),  # brief 24 (decisions 6, 7 and 14)
    "project_files": (DICT, NULL),  # brief 28 (decision 19, Phase 0 call 6): file mode's record
    "no_split": (STR, NULL), "piece_of": (DICT, NULL),  # brief 29 (decisions 3 and 17)
    # brief 29.1 (decisions 14, 15 and 21): the deciding check's notes, a failed check's open musts, Land anyway's offer
    "notes": [{"n": INT, "text": STR}], "open_musts": [{"n": INT, "text": STR}], "land_anyway": BOOL,
    "router_notes": (DICT, NULL),  # brief 30 (decision 9): the router notes copy the task's calls send from
    "spec": (DICT, NULL),  # brief 33.2 (decision 2.7): the SPEC.md copy the task's calls send from (hash, chars, file)
    # brief 30 (decisions 15 to 17): Forget's date, Save to project's path, the card's Pin, Save, Forget and Remember again
    "forgotten": (STR, NULL), "save_path": (STR, NULL),
    "card_actions": {"pin": BOOL, "save": BOOL, "forget": BOOL, "remember": BOOL},
    # brief 33 (decisions 3, 7 and 18): the chips, computed now; [] on a task that wasn't delivered
    "next": [{"kind": STR, "words": STR, "later": BOOL,
              "fill": {"team": STR, "project": (STR, NULL), "chat": (STR, NULL), "text": STR, "from": (STR, NULL),
                       "idea": (INT, NULL), "step": (DICT, NULL)}}],  # brief 33.1 (decision 12): a Build step chip's pill
    "from": (DICT, NULL),  # brief 33 (decisions 9 and 18): the earlier result it builds from (task_id, n, chars, cut)
    "idea": (DICT, NULL),  # brief 33 (decision 18): the project idea it was sent from (id, text, state)
    # brief 33.1 (decisions 6 and 19): a plan task's plan, a step task's plan and step, a One step end's task and team
    "plan": (DICT, NULL), "plan_step": (DICT, NULL), "one_step": (DICT, NULL),
    "questions": (DICT, NULL), "text_only": BOOL, "save_spec": (DICT, NULL),  # brief 33.4 (decisions 8 and 14)
    "models": (DICT, NULL),  # brief 33.3 (decision 4): the task's own model choices, or null
    "auto": (DICT, NULL),  # brief 34 (decision 14): a run's plan, steps, budget, calls used, stop and copy, or null
}
NEXT_CHIP = TASK["next"][0]
PROBE = (DICT, NULL)
AGENT = {"name": STR, "live": BOOL, "configured": BOOL, "online": (BOOL, NULL), "checked_at": (STR, NULL),
         "reason": (STR, NULL), "model": (STR, NULL), "served_model": (STR, NULL), "version": (STR, NULL), "probe": PROBE,
         "calls_this_week": INT,
         "available": BOOL, "why": (STR, NULL), "why_code": (STR, NULL)}  # brief 24 (decision 14)
SLOT = {"name": STR, "default": STR, "allowed": LIST,
        "project_refuses": LIST}  # brief 32 (decision 13): the agents a --project task refuses in this slot
PRESET = {"name": STR, "description": (STR, NULL), "chain": STR, "agents": LIST, "slots": [SLOT],
          "project": BOOL, "project_refuses": LIST,  # brief 23 (decision 14)
          "file_mode_refuses": LIST,  # brief 29.1 (decision 27): versus refuses Grok in file mode
          "ready": BOOL, "why": (STR, NULL), "filled": LIST}  # brief 24 (decision 14)
NOW = {"doer": (STR, NULL), "checker": (STR, NULL), "stand_in": (DICT, NULL), "unchecked": (STR, NULL),
       "note": (STR, NULL), "comes_back": (STR, NULL)}  # brief 24 (decision 14)
SKILL = {"key": STR, "description": (STR, NULL), "not_for": (STR, NULL), "best": (STR, NULL), "second": (STR, NULL),
         "now": NOW, "routed": BOOL}  # brief 29.1 (decision 3): the not_routed card's chips
COMMAND = {"name": STR, "help": (STR, NULL), "arguments": LIST}
RUNNING = {"n": INT, "task_id": STR, "pid": INT, "alive": (BOOL, NULL), "since": (STR, NULL)}  # brief 22
# Brief 29 (decision 2): status's `split`, with the piece menu as it stands now
TEAM = {"name": STR, "description": (STR, NULL), "chain": STR, "ready": BOOL, "why": (STR, NULL), "project": BOOL,
        "calls": INT, "max_calls": INT, "needs_you": (STR, NULL)}
SPLIT = {"ready": BOOL, "why": (STR, NULL), "description": STR, "chain": STR, "checker": (STR, NULL),
         "unchecked": (STR, NULL), "project": BOOL, "max_pieces": INT, "teams": [TEAM]}
# Brief 33.1 (decision 19): status's `plan`, as `split` has it
PLAN = {"ready": BOOL, "why": (STR, NULL), "description": STR, "chain": (STR, NULL), "calls": (INT, NULL),
        "max_calls": (INT, NULL), "project": BOOL}
# Brief 33.3 (decision 11): status's `models` and `sr models --json`
MODELS = {"agents": DICT, "fable": {"on": BOOL, "changed_at": (STR, NULL), "off_by": (STR, NULL), "words": STR, "fallback": STR,
                                    "fallback_name": STR},
          "layers": LIST, "problems": LIST, "files": {"tracked": STR, "local": STR, "local_present": BOOL},
          "claude": {"opus_calls_this_week": INT, "fable_calls_this_week": INT},
          "now": {"teams": DICT, "skills": DICT, "project_skills": DICT, "file": DICT},
          "setup": {"skills": LIST, "roles": LIST, "stages": LIST}}
# Brief 34 (decision 14): status's `auto`: whether a run could start now, and why not
AUTO_READY = {"ready": BOOL, "why": (STR, NULL)}
STATUS = {
    "agents": [AGENT], "presets": [PRESET], "split": SPLIT, "plan": PLAN, "skills": [SKILL], "commands": [COMMAND],
    "models": MODELS, "auto": AUTO_READY,
    "open_tasks": [TASK], "limits": {"idea_max": INT, "ideas_max": INT},  # brief 33.4 (decisions 12 and 15)
    "running": [RUNNING],
    "jev": {"configured": BOOL, "tokens_month": INT, "cap": INT, "over_cap": BOOL, "floor": (NUM, NULL), "tagged_floor": (NUM, NULL),  # brief 23; 29.1 (decision 24)
            "available": BOOL, "why": (STR, NULL)},  # brief 24 (decision 14)
    "memory": {"setting": STR, "online": BOOL, "starting": BOOL, "documents": (INT, NULL), "installed": BOOL,  # brief 27
               "newest": INT, "matches": INT,  # brief 29.1 (decision 25)
               "problem": (STR, NULL)},  # the memory brief (fixes 1 and 2): a bad setting or a memory_url off this Mac
    "projects": LIST, "chats": LIST, "drop_folder": (STR, NULL), "serve_port": INT,
    "projects_root": STR,  # brief 26 (decision 8): as written, ~/Projects when absent
    "git": {"installed": BOOL, "version": (STR, NULL)},  # brief 28 (decision 19)
    "test_sandbox": {"available": BOOL, "why": (STR, NULL)},  # brief 28 (decision 5)
    # brief 30 (decision 9): the router notes' state, counts, cap, Grok's share and hash; never their text
    "notes": {"state": STR, "why": (STR, NULL), "line": (INT, NULL), "reason_code": (STR, NULL), "sections": DICT,
              "total": INT, "max": INT, "grok": {"share": INT, "limit": INT, "line": STR}, "hash": STR, "default": BOOL},
    "version": (STR, NULL),
    "log_version": INT, "api_version": INT,
}


SOMETIMES = ("attack_lists",  # brief 32 (decision 16): only on a lettered redteam task, so an old task's JSON is as it was
             "what_now",  # brief 33 (decision 13): only on a log read with --project
             "plan_menu")  # brief 33.1 (decision 10): only on a plan task's show, with the roster


def check(value, shape, where="$", optional=()):
    """Raise AssertionError naming the first key that is missing, extra or of the wrong type. `optional` keys may be
    absent (report_path); so may SOMETIMES."""
    assert isinstance(value, dict), f"{where}: not an object"
    missing = set(shape) - set(value) - set(optional) - set(SOMETIMES)
    extra = set(value) - set(shape) - set(optional)
    assert not missing, f"{where}: missing {sorted(missing)}"
    assert not extra, f"{where}: unexpected {sorted(extra)}"
    for key, want in shape.items():
        if key not in value:
            continue
        got = value[key]
        if want is ANY:
            continue
        if isinstance(want, list):
            assert isinstance(got, list), f"{where}.{key}: not a list"
            for i, item in enumerate(got):
                check(item, want[0], f"{where}.{key}[{i}]")
        elif isinstance(want, dict):
            check(got, want, f"{where}.{key}")
        else:
            types = want if isinstance(want, tuple) else (want,)
            if bool not in types:
                assert not isinstance(got, bool), f"{where}.{key}: a boolean where {types} is wanted"
            assert isinstance(got, types), f"{where}.{key}: {type(got).__name__} is not {types}"

CALL_MEMORY = {"state": STR, "sent": (INT, NULL), "found": (INT, NULL), "from": (STR, NULL), "with": (INT, NULL),
               "limit": (INT, NULL), "query": (STR, NULL)}  # brief 30 (A3): the query a fresh recall sent
CALL = {"call_id": STR, "order": INT, "kind": STR, "stage": (INT, NULL), "role": (STR, NULL), "agent": STR, "status": STR,
        "verdict": (STR, NULL), "sent_at": STR, "finished_at": (STR, NULL), "round_file": (STR, NULL),
        "served": (DICT, NULL), "reason_code": (STR, NULL), "resume_of": (STR, NULL), "fallback_of": (STR, NULL),
        "takeover_of": (STR, NULL),  # brief 24 (decision 14)
        "search": (DICT, NULL), "memory": CALL_MEMORY,
        "tests": (DICT, NULL),  # brief 28 (decision 19): a file-mode build call's tests
        "cwd": (STR, NULL), "tools": (LIST, NULL),  # brief 29.1 (issue 2): a call in the copy, its init event's tools
        # brief 29.1 (decisions 14, 15, 17 and 22): how code read a check, and the kept prompt
        "said": (STR, NULL), "items": [{"n": INT, "tag": STR, "text": STR, "state": (STR, NULL)}],
        "blocked": (STR, NULL), "prompt_file": (STR, NULL),
        "router_notes": (DICT, NULL),  # brief 30 (decision 9): what the call was sent of the router notes
        "spec": (DICT, NULL),  # brief 33.2 (decision 2.7): the spec as sent (hash, chars, from) or left out
        # brief 33.3 (decision 7): the model asked (an older row as it ran then), the effort and the time limit
        "model": (STR, NULL), "effort": (STR, NULL), "time_limit": (INT, NULL)}
MEMORY_GIVEN = {"n": INT, "date": STR, "kind": STR, "doer": STR, "status": (STR, NULL), "text": STR}  # brief 23: text
# Brief 23 (decision 14): what the plan holds per piece; `route` is null while Jev left the piece under the floor
PIECE = {"piece": INT, "task_id": STR, "n": (INT, NULL), "status": (STR, NULL), "waiting_on": (STR, NULL),
         "outcome": (STR, NULL), "skipped": BOOL, "text": STR, "result": (STR, NULL), "jev": (DICT, NULL),
         "route": (DICT, NULL), "needs_label": BOOL, "choice": (STR, NULL), "edited": BOOL,
         "piece_state": (STR, NULL), "why": (STR, NULL),
         # brief 29 (decision 17): the team, who chose it and why, where it goes, the pick, the count, the refusal, its part
         "team": STR, "planner_team": STR, "team_source": STR, "team_why": (STR, NULL), "chain": (STR, NULL),
         "needs_you": (STR, NULL), "calls": (INT, NULL), "max_calls": (INT, NULL), "refused": (DICT, NULL),
         "project_files": (DICT, NULL),
         "slots": DICT, "slot_map": (DICT, NULL)}  # brief 29.1 (decision 12): the owner's slots; every slot as it runs now
SHOW = dict(TASK, api_version=INT, calls=[CALL], handoff=(DICT, NULL), memory_stored=LIST, memory_given=[MEMORY_GIVEN],
            candidates=(LIST, NULL), pick=(STR, NULL), votes=(LIST, NULL), tally=(DICT, NULL), attacks=(LIST, NULL),
            pieces=(LIST, NULL), join=(STR, NULL), original_file=(STR, NULL), result_file=(STR, NULL),
            from_given=(DICT, NULL),  # brief 33 (decision 12): the from-block as first sent
            plan_menu=(LIST, NULL),  # brief 33.1 (decision 10): a plan's menu as it stands now (SOMETIMES)
            estimate=(DICT, NULL), menu=(LIST, NULL),  # brief 29 (decision 17)
            attack_lists=[{"stage": (INT, NULL), "agent": (STR, NULL), "letter": (STR, NULL), "items": LIST,
                           "strongest": (STR, NULL), "state": STR, "why": (STR, NULL), "line": (STR, NULL),
                           "round_file": (STR, NULL)}])  # brief 32 (decision 16)
# brief 33 (decision 13): a project's What now?, on `sr log --json --project <name>` only (SOMETIMES)
WHAT_NOW = {"rung": (INT, STR), "words": STR, "control": (STR, NULL), "task_id": (STR, NULL), "n": (INT, NULL),
            "chip": (DICT, NULL),
            # brief 33.1 (decisions 16 and 17): the plan's rungs (plan_need, plan_step, finish) and what they carry
            "need": (DICT, NULL), "chips": (LIST, NULL), "plan_md": (DICT, NULL)}
LOG = {"api_version": INT, "tasks": [TASK], "next_before": (STR, NULL), "what_now": WHAT_NOW}
ATTACK = {"n": INT, "severity": STR, "text": STR, "answered": (STR, NULL)}
