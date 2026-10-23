"""The JSON the interface reads (rules v2.30, Status and JSON and Router for the interface; build brief 21). Every
string, and every key, goes through the redactor before it is printed or served, with every value in `.env` (not only
the three secrets the prompts know). Pure reads: nothing here writes a row or calls an agent.

One serializer for a task, `task_view`, shared by `sr status` (its open tasks), `sr log --json` (each row) and
`sr show --json` (the task-level keys): the row, its state (router/state.py, computed, never stored), and the two rescue
offers, computed by the code that decides them (fallback.decide and resume.decide), never stored (the owner's B3
amendment): a double fail or a plan-limit stop is an ended task whose card offers the rescue."""
import json

from router import cardline, checking, fallback, locks, log, presets, relay, resume, routing, runs, safety, split, state, takeover

API_VERSION = 1


def redact_all(value, secrets):
    """A JSON value with every string and every key through the redactor."""
    if isinstance(value, str):
        return safety.redact(value, secrets)
    if isinstance(value, list | tuple):
        return [redact_all(v, secrets) for v in value]
    if isinstance(value, dict):
        return {redact_all(k, secrets) if isinstance(k, str) else k: redact_all(v, secrets) for k, v in value.items()}
    return value


def dumps(value, secrets):
    """One line of JSON, redacted."""
    return json.dumps(redact_all(value, secrets), ensure_ascii=False)


def _get(row, key):
    return row[key] if key in row.keys() else None


def _mode(row):
    return _get(row, "mode") or "route"


def held(conn, row, calls):
    """A queued piece whose next call would go to Grok while another piece of its split has a Grok call out (rules v2.19):
    it waits on Grok too. The same reading `sr log` and `sr check` make (split.grok_holder)."""
    if _mode(row) != "piece" or row["status"] != "queued" or not _get(row, "parent"):
        return False
    step = checking.next_step(row, log.fallback_view(calls))
    agent = row["agent"] if step.action in ("do", "fix") else row["checker"] if step.action in ("check", "recheck") else None
    if agent != "grok":
        return False
    parent = log.get_task(conn, row["parent"])
    plan = log.split_plan_of(parent) if parent is not None else None
    if plan is None:
        return False
    return split.grok_holder(row, log.pieces_of(conn, parent["task_id"]), lambda tid: log.calls_for(conn, tid), plan) is not None


def state_of(conn, row, calls=None):
    """state.of with what it needs from around the row: its split's plan (a skipped piece) and the Grok hold."""
    calls = log.calls_for(conn, row["task_id"]) if calls is None else calls
    parent = log.get_task(conn, row["parent"]) if _mode(row) == "piece" and _get(row, "parent") else None
    return state.of(row, calls, plan=log.split_plan_of(parent) if parent is not None else None,
                    held=held(conn, row, calls), waiting=locks.waiting_on(runs.folder_of(conn), row))


def preset_of(row, loaded):
    """(the task's filled preset, None) for a relay or split task, (None, why) when it can't be read, (None, None) else."""
    if _mode(row) == "split":
        return split.PRESET, None
    if _mode(row) == "relay":
        return presets.for_task(row, loaded)
    return None, None


def offers(row, calls, *, live, loaded):
    """The two rescues as the commands would decide them now: `sr fallback` and `sr resume`. Never stored."""
    preset, problem = preset_of(row, loaded)
    plan = fallback.decide(row, calls, live=live, preset=preset)
    fall = {"ok": plan.ok, "agent": plan.doer if plan.ok else None, "reason": None if plan.ok else plan.reason}
    if _mode(row) == "relay" and preset is None:
        back = {"ok": False, "substitute": None, "agent": None, "checker": None, "reason": problem}
    else:
        plan = resume.decide(row, calls, live=live, preset=preset)
        back = {"ok": plan.ok, "substitute": plan.substitute if plan.ok else None, "agent": plan.agent if plan.ok else None,
                "checker": plan.checker if plan.ok else None, "reason": None if plan.ok else plan.reason}
    return {"fallback": fall, "resume": back}


def working(row, calls, preset):
    """Who an open task is with now, and the words for it (the page's agent cards, as the status page has shown them
    since rules v2.12): {"agent", "doing"}, or None when the task has ended, its preset can't be read, or a check
    stage's verdict only waits to be read. Derived from the rows, never stored."""
    if row["status"] not in ("queued", "sent"):
        return None
    if _mode(row) not in ("relay", "split"):
        return {"agent": row["agent"], "doing": None}
    if preset is None:
        return None
    from router import relay
    total = len(preset.stages)
    step = relay.next_stage(row, calls, preset)
    if step.action in ("stage", "reask"):
        return {"agent": step.agent or step.stage.agent, "doing": f"stage {step.n} of {total} ({step.stage.role})"}
    if step.action == "wait":
        return {"agent": step.call["agent"],
                "doing": f"stage {step.n} of {total} ({step.stage.role}), with {step.call['agent']}"}
    if step.action == "check":
        nxt = checking.next_step(row, calls)
        if nxt.action in ("check", "recheck"):
            return {"agent": row["checker"], "doing": "check" if nxt.action == "check" else "re-check"}
        if nxt.action == "fix":
            return {"agent": row["agent"], "doing": "fix round"}
        if nxt.action == "wait":
            return {"agent": nxt.call["agent"], "doing": f"{nxt.call['kind']}, with {nxt.call['agent']}"}
    return None


def task_view(conn, row, *, live=None, loaded=None, calls=None):
    """The task-level keys: the row as stored, its state, its tag, Jev's answer, its slots and the rescue offers."""
    calls = log.calls_for(conn, row["task_id"]) if calls is None else calls
    found = state_of(conn, row, calls)
    preset = preset_of(row, loaded)[0]
    jev = {"status": row["jev_status"], "label": row["jev_label"], "confidence": row["jev_confidence"],
           "tokens": row["jev_tokens"], "needs_split": row["jev_needs_split"], "error": row["jev_error"]}
    return {
        "task_id": row["task_id"], "n": row["n"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        "sent_at": row["sent_at"], "source": row["source"], "text": row["task"], "status": row["status"],
        "waiting_on": found.waiting_on, "outcome": found.outcome, "reason_code": _get(row, "reason_code"),
        "mode": _mode(row), "preset": _get(row, "preset"), "parent": _get(row, "parent"),
        "project": log.project_of(row), "chat": log.chat_of(row), "tag": log.tag_of(row),
        "skill": row["skill"], "skill_source": row["skill_source"], "agent": row["agent"], "checker": row["checker"],
        "check_state": row["check_state"], "check_note": _get(row, "check_note"), "route_reason": row["route_reason"],
        "failed_stage": _get(row, "failed_stage"), "web": log.web_of(row), "files": log.files_of(row),
        "result": row["result"], "result_url": row["result_url"] if str(row["result_url"] or "").startswith("https://") else None,
        "jev": jev, "slots": presets.slots_of(row), "working": working(row, calls, preset),
        **offers(row, calls, live=live, loaded=loaded),
        "pid": _get(row, "pid"), "run_started_at": _get(row, "run_started_at"), "answered_by": _get(row, "answered_by"),
        # brief 24 (decision 14): who stood in, for whom and why; a relay task's filled slots; the card's one line
        "stand_in": cardline.stand_in(row, calls), "filled": cardline.filled(row, preset),
        "card_line": cardline.line(row, preset, calls),
        # brief 24 (decisions 6, 7 and 14): the takeover (which call, from, to, why) and a late Grok answer, from the rows
        "takeover": takeover.record(calls), "late": takeover.late(calls),
    }


# ---------- sr show --json and sr log --json (build brief 21, B3) ----------

def build_call(row, calls):
    """The call whose result is the task's (rules v2.25): the routed doer (its re-ask, a resume or a fallback row), or a
    relay task's last stage's accepted row. None while there is none."""
    from router import relay  # relay imports checking, which imports this module's neighbours; kept local
    view = log.fallback_view(calls)
    if _mode(row) == "relay":
        stages = [c for c in view if c["kind"] in log.STAGE_KINDS]
        return relay.accepted(view, max(c["stage"] for c in stages)) if stages else None
    return checking._result_call(row, view)


def _call_memory(call):
    """The call's memory line as fields (rules v2.28, `sr show --memory`): sent of found, left out (with the lengths),
    unavailable, or not kept; `from` when the block was an earlier call's."""
    record = log.call_memory_of(call)
    found = {"state": "not_kept", "sent": None, "found": None, "from": None, "with": None, "limit": None}
    if record is None:
        return found
    if record.get("off"):  # brief 27: memory was off for this call
        found["state"] = "off"
    elif record.get("unavailable"):
        found["state"] = "unavailable"
    elif record.get("left_out"):
        found.update(state="left_out", found=record.get("found"), **{"with": record.get("with"), "limit": record.get("limit")})
    else:
        found.update(state="sent", sent=record.get("sent", 0), found=record.get("found", 0))
    found["from"] = record.get("from")
    return found


def call_view(call, order):
    search = log.search_of(call)
    return {"call_id": call["call_id"], "order": order, "kind": call["kind"], "stage": call["stage"], "role": call["role"],
            "agent": call["agent"], "status": call["status"], "verdict": call["verdict"], "sent_at": call["sent_at"],
            "finished_at": call["finished_at"], "round_file": _get(call, "round_file"), "served": log.served_of(call),
            "reason_code": call["reason_code"], "resume_of": _get(call, "resume_of"), "fallback_of": _get(call, "fallback_of"),
            "takeover_of": _get(call, "resume_of") if relay.is_takeover(call) else None,  # brief 24 (decision 14)
            "search": {"state": search.get("state"), "count": search.get("count")} if search else None,
            "memory": _call_memory(call)}


def _letter_of(items, agent):
    return next((item.letter for item in items if item.agent == agent), None)


def _candidates(row, calls, preset):
    """Versus (a preset with review stages): each candidate with its review, and the owner's pick, read from the row's
    doer (the pick names the picked builder; the two builders always differ) or `none` (failed with no stage)."""
    from router import relay
    found = relay.candidates(calls, preset)
    items = []
    for c in found:
        build, review = relay.accepted(calls, c.stage), relay.accepted(calls, c.review_stage)
        items.append({"letter": c.letter, "stage": c.stage, "builder": c.agent, "text": c.text, "missing": c.missing,
                      "round_file": _get(build, "round_file") if build is not None else None,
                      "review": {"stage": c.review_stage, "reviewer": c.reviewer, "verdict": c.verdict, "notes": c.notes,
                                 "round_file": _get(review, "round_file") if review is not None else None}})
    return items, _pick(row, found)


def _pick(row, found):
    if row["status"] == "done":
        return _letter_of(found, row["agent"])
    if row["status"] == "failed" and _get(row, "failed_stage") is None:
        return "none"
    return None


def _votes(row, calls, preset):
    """Vote (a tally preset): every answer with its reasons and confidence, the tally code made, and the pick on a tie."""
    from router import relay
    found = relay.voters(calls, preset)
    items = [{"letter": v.letter, "stage": v.stage, "agent": v.agent, "answer": v.answer, "why": v.why,
              "confidence": v.confidence, "round_file": _get(relay.accepted(calls, v.stage), "round_file")} for v in found]
    tally = None
    if len(found) == len(preset.stages):
        counted = relay.tally([(v.stage, v.text) for v in found])
        letter = {v.stage: v.letter for v in found}
        tally = {"winner": letter.get(counted.winner), "for": counted.votes_for, "against": counted.votes_against,
                 "note": counted.note, "dissent": [letter[s] for s in counted.dissent]}
    pick = _pick(row, found) if tally is not None and tally["winner"] is None else None
    return items, tally, pick


def _attacks(calls):
    """Redteam (the owner's B3 amendment): each attack with its severity, and the reviser's reason for an attack it
    rejected in `## Answered` (null when it took the attack). The check's verdict stays the task's."""
    from router import relay
    text = relay.attack_text(calls)
    if text is None:
        return None
    revision = relay.final_revision(calls)
    answered = relay.answered_items(relay.split_answered(revision)[1]) if revision else {}
    return [{"n": n, "severity": severity, "text": said, "answered": answered.get(n)}
            for n, severity, said in relay.parse_attacks(text)[0]]


def piece_route(label, roster, choice=None, available=None):
    """Brief 23 (decision 14): where the skill table sends a piece now, as fields (the approval screen's `_piece_route`
    in Terminal): None while Jev left it under the floor and the owner has not chosen; `comes_back` when it would come back
    instead of running. `available` (brief 24): what runs nothing says who is available (a JSON read checks nothing)."""
    if roster is None or label is None:
        return None
    decision = routing.decide(label, roster, answer=choice, can_ask=choice is None, available=available)
    if decision.action == "ask":
        return None
    return {"skill": decision.skill, "agent": decision.agent if decision.action != "return" else None,
            "checker": decision.checker if decision.action != "return" else None,
            "check_state": decision.check_state if decision.action != "return" else None,
            "comes_back": decision.reason.removeprefix("returned: ") if decision.action == "return" else None}


def _pieces(conn, row, roster=None, available=None):
    plan = log.split_plan_of(row)
    if plan is None:
        return None
    rows = {r["task_id"]: r for r in log.pieces_of(conn, row["task_id"])}
    found = []
    for k, piece in enumerate(plan["pieces"], 1):
        r = rows.get(piece["id"])
        st = state_of(conn, r) if r is not None else None
        label, choice = piece.get("label"), piece.get("choice")
        route = piece_route(label, roster, choice, available)
        # brief 23, D: the router's own word for the piece (what `sr check` prints and `sr split --skip` reads), so the
        # page offers Skip on a blocked piece without working it out
        where, why = ("skipped", None) if piece["skipped"] else split.piece_state(r) if r is not None else (None, None)
        found.append({"piece": k, "task_id": piece["id"], "n": r["n"] if r else None, "status": r["status"] if r else None,
                      "waiting_on": st.waiting_on if st else None, "outcome": st.outcome if st else None,
                      "skipped": piece["skipped"], "text": split.text_of(piece), "result": r["result"] if r else None,
                      # brief 23 (decision 14): what the plan holds per piece, read-only
                      "jev": {"status": label.get("status"), "label": label.get("label"),
                              "confidence": label.get("confidence")} if label else None,
                      "route": route, "needs_label": bool(label) and roster is not None and route is None,
                      "choice": choice, "edited": piece.get("edited_text") is not None,
                      "piece_state": where, "why": why})
    return found


def _handoff(row, build):
    """Whether the project's handoff rode with the build call, and how much of it (rules v2.25)."""
    if not log.project_of(row):
        return None
    record = log.context_of(build) if build is not None else None
    if record is None:
        return {"attached": False, "lines": None, "total": None, "left_out": False}
    left_out = bool(record.get("left_out"))
    return {"attached": not left_out, "lines": record.get("lines"), "total": record.get("total"), "left_out": left_out}


def _memory_given(build):
    """The memories the build call's block carried, by their headings (rules v2.27): number, date, kind, doer, status."""
    from router import memory
    record = log.call_memory_of(build) if build is not None else None
    if not record or not record.get("text"):
        return []
    return [{"n": e.n, "date": e.date, "kind": e.kind, "doer": e.doer, "status": e.status, "text": e.text}  # brief 23: text
            for e in memory.entries_of_block(record["text"])]


def first_build(row, calls, preset=None):
    """The first build's call: what "show the original" reads (rules v2.30, Round outputs and Checking). A routed task:
    its first `do` row. A relay or split task: the first row of the stage that builds the deliverable (the last stage,
    or the stage a check stage checks, as on collab); on versus the picked candidate's build; a vote has none. Without
    the preset: the first row of the last stage."""
    if _mode(row) not in ("relay", "split"):
        return next((c for c in calls if c["kind"] == "do"), None)
    from router import relay  # kept local, as above
    stages = [c for c in calls if c["kind"] in log.STAGE_KINDS]
    if preset is None:
        n = max((c["stage"] for c in stages), default=None)
    elif preset.tallies:
        return None
    elif preset.has_reviews:
        found = next((c for c in relay.candidates(calls, preset) if c.letter == relay.picked(row)), None)
        n = found.stage if found is not None else None
    else:
        last = preset.stages[-1]
        n = last.input_stage if last.is_check else last.n
    return next((c for c in stages if c["stage"] == n), None)


def _result_file(row, calls):
    """The round file of the newest call whose text holds the delivered result."""
    result = row["result"]
    if not result:
        return None
    for c in reversed(calls):
        if c["status"] == "done" and c["text"] and result in c["text"]:
            return _get(c, "round_file")
    return None


def show_view(conn, row, *, live=None, loaded=None, roster=None, available=None):
    """`sr show <n> --json`: the task, every call in order, and everything the task's kind has (B3). `roster` lets a
    split's pieces say where the skill table sends them (brief 23)."""
    calls = log.calls_for(conn, row["task_id"])
    preset, _ = preset_of(row, loaded)
    view = log.fallback_view(calls)
    build = build_call(row, calls)
    candidates = pick = votes = tally = None
    if preset is not None and getattr(preset, "has_reviews", False):
        candidates, pick = _candidates(row, view, preset)
    elif preset is not None and getattr(preset, "tallies", False):
        votes, tally, pick = _votes(row, view, preset)
    first = first_build(row, calls, preset)
    return {"api_version": API_VERSION, **task_view(conn, row, live=live, loaded=loaded, calls=calls),
            "calls": [call_view(c, k) for k, c in enumerate(calls, 1)],
            "handoff": _handoff(row, build), "memory_stored": log.memory_of(row), "memory_given": _memory_given(build),
            "candidates": candidates, "pick": pick, "votes": votes, "tally": tally,
            "attacks": _attacks(view) if _mode(row) == "relay" else None,
            "pieces": _pieces(conn, row, roster, available) if _mode(row) == "split" else None,
            "join": (log.split_plan_of(row) or {}).get("join") if _mode(row) == "split" else None,
            "original_file": _get(first, "round_file") if first is not None else None,
            "result_file": _result_file(row, calls)}


def log_view(conn, rows, *, limit, live=None, loaded=None):
    """`sr log --json`: each row's task keys, newest first; `next_before` pages on (the oldest row's id) when the page
    is full."""
    return {"api_version": API_VERSION, "tasks": [task_view(conn, r, live=live, loaded=loaded) for r in rows],
            "next_before": rows[-1]["task_id"] if rows and len(rows) == limit else None}
