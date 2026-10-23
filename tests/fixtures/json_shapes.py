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
    "fallback": OFFER_FALLBACK, "resume": OFFER_RESUME,
    "pid": (INT, NULL), "run_started_at": (STR, NULL), "answered_by": (STR, NULL),  # brief 22
    "stand_in": (DICT, NULL), "filled": (LIST, NULL), "card_line": (STR, NULL),  # brief 24 (decision 14)
    "takeover": (DICT, NULL), "late": (DICT, NULL),  # brief 24 (decisions 6, 7 and 14)
}
PROBE = (DICT, NULL)
AGENT = {"name": STR, "live": BOOL, "configured": BOOL, "online": (BOOL, NULL), "checked_at": (STR, NULL),
         "reason": (STR, NULL), "model": (STR, NULL), "served_model": (STR, NULL), "version": (STR, NULL), "probe": PROBE,
         "calls_this_week": INT,
         "available": BOOL, "why": (STR, NULL), "why_code": (STR, NULL)}  # brief 24 (decision 14)
SLOT = {"name": STR, "default": STR, "allowed": LIST}
PRESET = {"name": STR, "description": (STR, NULL), "chain": STR, "agents": LIST, "slots": [SLOT],
          "project": BOOL, "project_refuses": LIST,  # brief 23 (decision 14)
          "ready": BOOL, "why": (STR, NULL), "filled": LIST}  # brief 24 (decision 14)
NOW = {"doer": (STR, NULL), "checker": (STR, NULL), "stand_in": (DICT, NULL), "unchecked": (STR, NULL),
       "note": (STR, NULL), "comes_back": (STR, NULL)}  # brief 24 (decision 14)
SKILL = {"key": STR, "description": (STR, NULL), "not_for": (STR, NULL), "best": (STR, NULL), "second": (STR, NULL),
         "now": NOW}
COMMAND = {"name": STR, "help": (STR, NULL), "arguments": LIST}
RUNNING = {"n": INT, "task_id": STR, "pid": INT, "alive": (BOOL, NULL), "since": (STR, NULL)}  # brief 22
STATUS = {
    "agents": [AGENT], "presets": [PRESET], "skills": [SKILL], "commands": [COMMAND], "open_tasks": [TASK],
    "running": [RUNNING],
    "jev": {"configured": BOOL, "tokens_month": INT, "cap": INT, "over_cap": BOOL, "floor": (NUM, NULL),  # brief 23
            "available": BOOL, "why": (STR, NULL)},  # brief 24 (decision 14)
    "memory": {"setting": STR, "online": BOOL, "starting": BOOL, "documents": (INT, NULL), "installed": BOOL},  # brief 27
    "projects": LIST, "chats": LIST, "drop_folder": (STR, NULL), "serve_port": INT,
    "projects_root": STR,  # brief 26 (decision 8): as written, ~/Projects when absent
    "version": (STR, NULL),
    "log_version": INT, "api_version": INT,
}


def check(value, shape, where="$", optional=()):
    """Raise AssertionError naming the first key that is missing, extra or of the wrong type. `optional` keys may be
    absent (report_path)."""
    assert isinstance(value, dict), f"{where}: not an object"
    missing = set(shape) - set(value) - set(optional)
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
               "limit": (INT, NULL)}
CALL = {"call_id": STR, "order": INT, "kind": STR, "stage": (INT, NULL), "role": (STR, NULL), "agent": STR, "status": STR,
        "verdict": (STR, NULL), "sent_at": STR, "finished_at": (STR, NULL), "round_file": (STR, NULL),
        "served": (DICT, NULL), "reason_code": (STR, NULL), "resume_of": (STR, NULL), "fallback_of": (STR, NULL),
        "takeover_of": (STR, NULL),  # brief 24 (decision 14)
        "search": (DICT, NULL), "memory": CALL_MEMORY}
MEMORY_GIVEN = {"n": INT, "date": STR, "kind": STR, "doer": STR, "status": (STR, NULL), "text": STR}  # brief 23: text
# Brief 23 (decision 14): what the plan holds per piece; `route` is null while Jev left the piece under the floor
PIECE = {"piece": INT, "task_id": STR, "n": (INT, NULL), "status": (STR, NULL), "waiting_on": (STR, NULL),
         "outcome": (STR, NULL), "skipped": BOOL, "text": STR, "result": (STR, NULL), "jev": (DICT, NULL),
         "route": (DICT, NULL), "needs_label": BOOL, "choice": (STR, NULL), "edited": BOOL,
         "piece_state": (STR, NULL), "why": (STR, NULL)}
SHOW = dict(TASK, api_version=INT, calls=[CALL], handoff=(DICT, NULL), memory_stored=LIST, memory_given=[MEMORY_GIVEN],
            candidates=(LIST, NULL), pick=(STR, NULL), votes=(LIST, NULL), tally=(DICT, NULL), attacks=(LIST, NULL),
            pieces=(LIST, NULL), join=(STR, NULL), original_file=(STR, NULL), result_file=(STR, NULL))
LOG = {"api_version": INT, "tasks": [TASK], "next_before": (STR, NULL)}
ATTACK = {"n": INT, "severity": STR, "text": STR, "answered": (STR, NULL)}
