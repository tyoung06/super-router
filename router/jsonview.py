"""The JSON the interface reads (rules v2.30, Status and JSON and Router for the interface; build brief 21). Every
string, and every key, goes through the redactor before it is printed or served, with every value in `.env` (not only
the three secrets the prompts know). Pure reads: nothing here writes a row or calls an agent.

One serializer for a task, `task_view`, shared by `sr status` (its open tasks), `sr log --json` (each row) and
`sr show --json` (the task-level keys): the row, its state (router/state.py, computed, never stored), and the two rescue
offers, computed by the code that decides them (fallback.decide and resume.decide), never stored (the owner's B3
amendment): a double fail or a plan-limit stop is an ended task whose card offers the rescue."""
import json
import re

from router import (cardline, checking, fallback, fromblock, locks, log, nextsteps, presets, relay, resume, rounds,
                    routing, runs, safety, split,
                    splitview, state, takeover, teams)

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


def held(conn, row, calls, loaded=None):
    """A queued piece whose next call would go to Grok while another piece of its split has a Grok call out (rules v2.19):
    it waits on Grok too. The same reading `sr log` and `sr check` make (split.grok_holder). Brief 29: a piece of any
    team (its chain's next stage read with `loaded`)."""
    if not log.is_piece(row) or row["status"] != "queued":
        return False
    if split.next_agent(row, log.fallback_view(calls), loaded) != "grok":
        return False
    parent = log.get_task(conn, row["parent"])
    plan = log.split_plan_of(parent) if parent is not None else None
    if plan is None:
        return False
    return split.grok_holder(row, log.pieces_of(conn, parent["task_id"]), lambda tid: log.calls_for(conn, tid), plan) is not None


def order_holder(conn, row):
    """Brief 29 (decision 13): the earlier piece holding a queued piece of a project split, or None."""
    if not log.is_piece(row) or row["status"] != "queued":
        return None
    parent = log.get_task(conn, row["parent"])
    plan = log.split_plan_of(parent) if parent is not None else None
    return split.order_holder(row, parent, log.pieces_of(conn, parent["task_id"]) if parent else [], plan)


def state_of(conn, row, calls=None, loaded=None):
    """state.of with what it needs from around the row: its split's plan (a skipped piece), the Grok hold and (brief 29)
    the order hold."""
    calls = log.calls_for(conn, row["task_id"]) if calls is None else calls
    parent = log.get_task(conn, row["parent"]) if log.is_piece(row) else None  # brief 29: a piece of any team
    return state.of(row, calls, plan=log.split_plan_of(parent) if parent is not None else None,
                    held=held(conn, row, calls, loaded), waiting=locks.waiting_on(runs.folder_of(conn), row),
                    ordered=order_holder(conn, row) is not None)


def preset_of(row, loaded):
    """(the task's filled preset, None) for a relay or split task, (None, why) when it can't be read, (None, None) else."""
    if _mode(row) == "split":
        return split.PRESET, None
    if _mode(row) in log.CHAINED_MODES:  # brief 33.1: a plan task's chain is redteam's, in its plan shape
        return presets.for_task(row, loaded)
    return None, None


def offers(row, calls, *, live, loaded):
    """The two rescues as the commands would decide them now: `sr fallback` and `sr resume`. Never stored."""
    preset, problem = preset_of(row, loaded)
    plan = fallback.decide(row, calls, live=live, preset=preset)
    fall = {"ok": plan.ok, "agent": plan.doer if plan.ok else None, "reason": None if plan.ok else plan.reason}
    if _mode(row) in log.CHAINED_MODES and preset is None:
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
    if _mode(row) not in ("relay", "split", "plan"):
        return {"agent": row["agent"], "doing": None}
    if preset is None:
        return None
    from router import relay
    total = len(preset.stages)
    step = relay.next_stage(row, calls, preset, checks=split.stored_checks(row))
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


def current_call(row, calls, preset, waiting_on):
    """The call in progress and not yet logged, shaped like a call row, or None (the small UI cleanup, row 1): a Claude, ChatGPT or
    Cursor call has no row until it ends, so the page can't see it from the calls. Read as `working` reads it: relay.next_stage,
    then checking.next_step. None once the task has ended, while it waits on something, while a sent row shows the call, and
    while no agent is named."""
    if row["status"] not in ("queued", "sent") or waiting_on:
        return None
    if _mode(row) in ("relay", "split", "plan"):
        if preset is None:
            return None
        from router import relay
        step = relay.next_stage(row, calls, preset, checks=split.stored_checks(row))
        if step.action in ("stage", "reask"):
            return {"kind": step.action, "stage": step.n, "role": step.stage.role, "agent": step.agent or step.stage.agent}
        if step.action != "check":
            return None
    nxt = checking.next_step(row, calls)
    agent = {"do": row["agent"], "fix": row["agent"], "check": row["checker"], "recheck": row["checker"]}.get(nxt.action)
    return {"kind": nxt.action, "stage": None, "role": None, "agent": agent} if agent else None


def steps_of(row, calls, preset, waiting_on):
    """A task's steps (the small UI cleanup, row 1): `chain`, its own filled chain, with the check step only when the preset has a
    checker and the row names one, null for Route, a route piece and a preset that can't be read (`agent` and `checker` name a
    routed task's two steps); and `now`, the call in progress. Null for Auto, whose steps are its own. Derived, never stored."""
    if _mode(row) == "auto":
        return None
    chain = None
    if preset is not None:
        chain = [{"stage": s.n, "role": s.role, "agent": s.agent} for s in preset.stages]
        if preset.checker and row["checker"]:
            chain.append({"stage": None, "role": "check", "agent": row["checker"]})
    return {"chain": chain, "now": current_call(row, calls, preset, waiting_on)}


def task_view(conn, row, *, live=None, loaded=None, calls=None):
    """The task-level keys: the row as stored, its state, its tag, Jev's answer, its slots and the rescue offers."""
    calls = log.calls_for(conn, row["task_id"]) if calls is None else calls
    found = state_of(conn, row, calls, loaded)
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
        # brief 33 (decision 18, Call 3): the result the card renders, without the agent's `## Next`; the row keeps it
        "result": checking.without_next(row["result"]),
        "result_url": row["result_url"] if str(row["result_url"] or "").startswith("https://") else None,
        "jev": jev, "slots": presets.slots_of(row), "working": working(row, calls, preset),
        "steps": steps_of(row, calls, preset, found.waiting_on),  # the small UI cleanup, row 1: the page's step pills
        **offers(row, calls, live=live, loaded=loaded),
        "pid": _get(row, "pid"), "run_started_at": _get(row, "run_started_at"), "answered_by": _get(row, "answered_by"),
        # brief 24 (decision 14): who stood in, for whom and why; a relay task's filled slots; the card's one line
        "stand_in": cardline.stand_in(row, calls), "filled": cardline.filled(row, preset),
        "card_line": cardline.line(row, preset, calls),
        # brief 24 (decisions 6, 7 and 14): the takeover (which call, from, to, why) and a late Grok answer, from the rows
        "takeover": takeover.record(calls), "late": takeover.late(calls),
        "project_files": log.project_files_of(row),  # brief 28 (decision 19, Phase 0 call 6): file mode's record
        # brief 29.1 (decisions 14, 15 and 21): the deciding check's notes, the musts a failed check left open, and
        # whether `sr land <n> --anyway` would take it now
        **check_facts(row, calls),
        # brief 29 (decisions 3 and 17): the planner's `## No split` line, and a piece's split, team and place
        "no_split": split.no_split_of(row, calls), "piece_of": piece_of(conn, row),
        # brief 30 (decision 9): the router notes copy its calls send from (its own, or its split's): hash and characters.
        # Named `router_notes`: `notes` is the deciding check's notes since brief 29.1 (Phase 0 report, call 15)
        "router_notes": task_notes(conn, row),
        "spec": task_spec(conn, row),  # brief 33.2 (decision 2.7): the SPEC.md copy its calls send from, or null
        # brief 30 (decisions 15 to 17): Forget's date, Save to project's proposed path, and the card's three actions,
        # each offered by the code that would refuse it, never worked out by the page
        **notes_offers(conn, row, found),
        # brief 33 (decisions 2-7 and 18): the chips, computed now from the row, its calls and the Ideas list
        "next": nextsteps.chips(conn, row, calls, loaded, moved=_moved(conn, row)),
        # brief 33 (decisions 9 and 18): the earlier result it builds from (task_id, n, chars, cut), as first sent
        "from": fromblock.json_of(conn, row, calls),
        "idea": _idea(conn, row),  # brief 33 (decision 18): the project idea it was sent from
        # brief 33.1 (decisions 6 and 19): a plan task's plan (its steps with their state and task, its needs, its edits),
        # a step task's plan and step, and a One step end's task and team; from the rows, never stored apart
        **_plan_keys(conn, row, calls),
        "models": log.models_of(row) or None,  # brief 33.3 (decision 4): the task's own choices, or null
        "auto": _auto_keys(conn, row),  # brief 34 (decision 14): a run's plan, steps, budget, calls used, stop and copy
    }


def _auto_keys(conn, row):
    from router import auto  # auto reads log and plan; kept local
    return auto.view(conn, row) if _mode(row) == auto.MODE else None


def _plan_keys(conn, row, calls, found_menu=None):
    from router import plan  # plan imports teams, which reads this module's neighbours; kept local
    return {"plan": plan.view(conn, row, found_menu), "plan_step": plan.step_view(conn, row),
            "one_step": plan.one_step_view(row, calls) if plan.is_plan(row) else None,
            "questions": plan.questions_view(row)}  # brief 33.4 (decision 14): the questions card's facts


def _moved(conn, row):
    from router import ideas  # kept local, as below
    return ideas.moved_from(conn, row)


def _idea(conn, row):
    from router import ideas  # it reads nextsteps, which reads this module's neighbours; kept local
    found = ideas.get(conn, _get(row, "idea")) if _get(row, "idea") is not None else None
    return {"id": found.id, "text": found.text, "state": found.state} if found is not None else None


def notes_offers(conn, row, found):
    """{"forgotten", "save_path", "card_actions": {pin, save, forget, remember}} for a task's card (brief 30)."""
    from router import memory, projnotes  # both read most of the router; kept local
    gone = memory.forgotten(row)
    savable = projnotes.savable(conn, row) is None
    tagged = bool(log.tag_of(row)) and not log.is_piece(row)
    text_only, save_spec = _text_only_offer(row, savable)  # brief 33.4 (decisions 8 and 9b)
    return {"forgotten": gone, "save_path": projnotes.save_path(row) if savable else None,
            "text_only": text_only, "save_spec": save_spec,
            "card_actions": {"pin": projnotes.pinnable(conn, row) is None, "save": savable,
                             "forget": tagged and found.ended and gone is None,
                             "remember": tagged and found.ended and gone is not None}}


def _text_only_offer(row, savable):
    """Brief 33.4 (decisions 8 and 9b): whether the task is a `--no-files` one, from its files record, and Save as SPEC.md's
    offer ({path}): a delivered one, on a project with no SPEC.md."""
    from router import projects, spec  # both read settings; kept local
    found = log.project_files_of(row) if _get(row, "project_files") else None
    if not spec.is_text_only(found):
        return False, None
    project = log.project_of(row)
    try:
        folder = projects.folder_of(project) if project else None
    except projects.ProjectError:
        folder = None
    if not savable or log.is_piece(row) or folder is None or spec.read_text(folder) is not None:
        return True, None
    return True, {"path": spec.FILE}


def task_spec(conn, row):
    """Brief 33.2 (decision 2.7): {hash, chars, file, left_out} of the SPEC.md copy the task's calls send from (its own, or
    its split's), or None; `left_out` when a call of the task went without it for Grok's limit (that call's record)."""
    from router import spec  # spec reads settings; kept local
    found = spec.task_view(rounds.log_folder(conn), row)
    if found is None:
        return None
    left = [c["call_id"] for c in log.calls_for(conn, row["task_id"])
            if ((log.context_of(c) or {}).get("spec") or {}).get("left_out")]
    return {**found, "left_out": left[0] if left else None}


def task_notes(conn, row):
    """Brief 30 (decision 9): {hash, chars, file} of the router notes copy the task's calls send from (its own, or its
    split's), or None (none kept). `file` is the copy's path beside the log, which the page opens behind a toggle."""
    from router import notes  # notes reads settings and locks; kept local
    text, owner = notes.copy_of(rounds.log_folder(conn), row)
    found = notes.record_of(text)
    return {**found, "file": f"{rounds.FOLDER}/{owner}/{notes.COPY_NAME}"} if found else None


def check_facts(row, calls):
    """Brief 29.1: {"notes": [{n, text}], "open_musts": [{n, text}], "land_anyway": bool}, from the rows, never stored."""
    from router import landing  # landing imports projects and gitops; kept local
    _, reading = checking.deciding(calls)
    notes = [{"n": i.n, "text": i.text} for i in reading.notes] if reading is not None else []
    failed = row["check_state"] == "failed"
    musts = [{"n": n, "text": text} for n, text in checking.open_musts(calls)] if failed else []
    found = log.project_files_of(row)
    return {"notes": notes, "open_musts": musts,
            "land_anyway": bool(found) and landing.anyway_refusal(row, found) is None}


def piece_of(conn, row):
    """A piece's split, its place in the plan and its team (brief 29, decision 17), or None for any other task."""
    if not log.is_piece(row):
        return None
    parent = log.get_task(conn, row["parent"])
    if parent is not None and parent["mode"] == "auto":  # brief 34 (decision 2): a run's step names its run and its step
        step = log.plan_step_of(row) or {}
        return {"split": None, "run": row["parent"], "n": parent["n"], "piece": None, "step": step.get("step"),
                "team": row["preset"] or teams.ROUTE}
    plan = log.split_plan_of(parent) if parent is not None else None
    k = split.piece_index(plan, row["task_id"]) if plan is not None else None
    piece = plan["pieces"][k - 1] if k else None
    return {"split": row["parent"], "n": parent["n"] if parent is not None else None, "piece": k,
            "team": split.team_of(piece) if piece is not None else (row["preset"] or teams.ROUTE)}


# ---------- sr show --json and sr log --json (build brief 21, B3) ----------

def build_call(row, calls):
    """The call whose result is the task's (rules v2.25): the routed doer (its re-ask, a resume or a fallback row), or a
    relay task's last stage's accepted row. None while there is none."""
    from router import relay  # relay imports checking, which imports this module's neighbours; kept local
    view = log.fallback_view(calls)
    if _mode(row) in log.CHAINED_MODES:
        stages = [c for c in view if c["kind"] in log.STAGE_KINDS]
        return relay.accepted(view, max(c["stage"] for c in stages)) if stages else None
    return checking._result_call(row, view)


def _call_memory(call):
    """The call's memory line as fields (rules v2.28, `sr show --memory`): sent of found, left out (with the lengths),
    unavailable, or not kept; `from` when the block was an earlier call's."""
    record = log.call_memory_of(call)
    found = {"state": "not_kept", "sent": None, "found": None, "from": None, "with": None, "limit": None, "query": None}
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
    found["query"] = record.get("query")  # brief 30 (A3): the query a fresh recall sent, as sent; None on a reused block
    return found


def call_view(call, order, calls=(), folder=None, pins=None):
    from router import models  # models reads log; kept local as plan is
    search = log.search_of(call)
    reading = checking.reading_of(call, calls)  # brief 29.1 (decisions 14 and 15): how code read a check
    return {"call_id": call["call_id"], "order": order, "kind": call["kind"], "stage": call["stage"], "role": call["role"],
            "agent": call["agent"], "status": call["status"], "verdict": call["verdict"], "sent_at": call["sent_at"],
            "finished_at": call["finished_at"], "round_file": _get(call, "round_file"), "served": log.served_of(call),
            "reason_code": call["reason_code"], "resume_of": _get(call, "resume_of"), "fallback_of": _get(call, "fallback_of"),
            "takeover_of": _get(call, "resume_of") if relay.is_takeover(call) else None,  # brief 24 (decision 14)
            "search": {"state": search.get("state"), "count": search.get("count")} if search else None,
            "memory": _call_memory(call), "tests": log.tests_of(call),  # brief 28: a file-mode build call's tests
            # brief 29.1 (issue 2): a call in the project's copy, and the tools its init event listed
            "cwd": (log.context_of(call) or {}).get("cwd"), "tools": (log.context_of(call) or {}).get("tools"),
            # brief 29.1: the first line's word beside code's verdict, the items, and the kept prompt (decision 22)
            "said": reading.said if reading is not None else None,
            # brief 30 (decision 9): the router notes this call was sent (sections and characters, judge, planner) or
            # that they were left out for Grok's limit; None when the task had none
            "router_notes": (log.context_of(call) or {}).get("notes"),
            "spec": (log.context_of(call) or {}).get("spec"),  # brief 33.2 (decision 2.7): as sent, or left out
            "items": [{"n": i.n, "tag": i.tag, "text": i.text, "state": i.state}
                      for i in reading.lines + reading.items] if reading is not None else [],
            "blocked": reading.blocked if reading is not None else None,
            "prompt_file": rounds.prompt_file(folder, call, order),
            # brief 33.3 (decision 7): the model asked (an older row as its agent ran then), its effort and time limit
            "model": models.asked_of(call, pins) if call["agent"] in models.AGENTS else None,
            "effort": _get(call, "effort"), "time_limit": _get(call, "time_limit")}


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


def _attacks(calls, row=None):
    """Redteam (the owner's B3 amendment): each attack with its severity, and the reviser's reason for an attack it
    rejected in `## Answered` (null when it took the attack). The check's verdict stays the task's. Brief 32 (decision 16):
    on a lettered task every list's attacks, each with its `label` and `attacker`, and `check`: `open` when the deciding
    check's open [must] names its label, `ok` when a check ran and didn't, null before any check."""
    from router import relay
    if row is not None and relay.lettered(row):
        lists = relay.attack_lists(row, calls)
        if not any(l.state == relay.RAN for l in lists):
            return None
        revision = relay.final_revision(calls, row)
        answered = relay.answered_labeled(relay.split_answered(revision)[1]) if revision else {}
        named = _labels_open(calls)
        return [{"label": i.label, "attacker": l.agent, "n": i.n, "severity": i.severity, "text": i.text,
                 "answered": answered.get(i.label), "check": None if named is None else "open" if i.label in named else "ok"}
                for l in lists if l.state == relay.RAN for i in l.items]
    text = relay.attack_text(calls)
    if text is None:
        return None
    revision = relay.final_revision(calls)
    answered = relay.answered_items(relay.split_answered(revision)[1]) if revision else {}
    return [{"n": n, "severity": severity, "text": said, "answered": answered.get(n)}
            for n, severity, said in relay.parse_attacks(text)[0]]


_LABEL = re.compile(r"\b([A-Z][0-9]+)\b")


def _labels_open(calls):
    """The labels the deciding check's open [must] items name (brief 32): {} when it named none, None before a check."""
    found, reading = checking.deciding(calls)
    if found is None or reading is None:
        return None
    return {m for item in reading.open_musts for m in _LABEL.findall(item.text or "")}


def _attack_lists(row, calls):
    """Brief 32 (decision 16): each list's stage, agent, letter, items, `## Strongest` line, state and why."""
    from router import relay
    return [{"stage": l.stage, "agent": l.agent, "letter": l.letter,
             "items": [{"label": i.label, "n": i.n, "severity": i.severity, "text": i.text} for i in l.items],
             "strongest": l.strongest, "state": l.state, "why": l.why,
             "line": relay.list_line(l) if l.state != relay.RAN else None,
             "round_file": _get(l.row, "round_file") if l.row is not None else None}
            for l in relay.attack_lists(row, calls)]


def _lettered(row):
    from router import relay
    return relay.lettered(row)


def piece_route(label, roster, choice=None, available=None, tagged=False):
    """Brief 23 (decision 14): where the skill table sends a piece now, as fields (the approval screen's `_piece_route`
    in Terminal): None while Jev left it under the floor and the owner has not chosen; `comes_back` when it would come back
    instead of running. `available` (brief 24): what runs nothing says who is available (a JSON read checks nothing)."""
    if roster is None or label is None:
        return None
    decision = routing.decide(label, roster, answer=choice, can_ask=choice is None, available=available, tagged=tagged)
    if decision.action == "ask":
        return None
    return {"skill": decision.skill, "agent": decision.agent if decision.action != "return" else None,
            "checker": decision.checker if decision.action != "return" else None,
            "check_state": decision.check_state if decision.action != "return" else None,
            "comes_back": decision.reason.removeprefix("returned: ") if decision.action == "return" else None}


def _pieces(conn, row, roster=None, available=None, loaded=None, send_paths=None):
    plan = log.split_plan_of(row)
    if plan is None:
        return None
    rows = {r["task_id"]: r for r in log.pieces_of(conn, row["task_id"])}
    project = log.project_of(row)
    menu = (teams.menu(loaded, roster, available, project=project is not None, send_paths=send_paths)
            if roster is not None and send_paths is not None else None)
    found = []
    for k, piece in enumerate(plan["pieces"], 1):
        r = rows.get(piece["id"])
        st = state_of(conn, r) if r is not None else None
        label, choice = piece.get("label"), piece.get("choice")
        is_route = split.team_of(piece) == teams.ROUTE  # brief 29 (decision 9): a team's label routes nothing
        route = piece_route(label, roster, choice, available, tagged=log.project_of(row) is not None) if is_route else None
        # brief 23, D: the router's own word for the piece (what `sr check` prints and `sr split --skip` reads), so the
        # page offers Skip on a blocked piece without working it out
        where, why = (("skipped", None) if piece["skipped"] else split.piece_state(r, log.calls_for(conn, r["task_id"]))
                      if r is not None else (None, None))
        holder = order_holder(conn, r) if r is not None else None
        if holder is not None:  # brief 29 (decision 14): held by an earlier piece of a project split
            why = split.order_words(plan, holder)
        found.append({"piece": k, "task_id": piece["id"], "n": r["n"] if r else None, "status": r["status"] if r else None,
                      "waiting_on": st.waiting_on if st else None, "outcome": st.outcome if st else None,
                      "skipped": piece["skipped"], "text": split.text_of(piece), "result": r["result"] if r else None,
                      # brief 23 (decision 14): what the plan holds per piece, read-only
                      "jev": {"status": label.get("status"), "label": label.get("label"),
                              "confidence": label.get("confidence")} if label else None,
                      "route": route, "needs_label": is_route and bool(label) and roster is not None and route is None,
                      "choice": choice, "edited": piece.get("edited_text") is not None,
                      "piece_state": where, "why": why,
                      **_piece_facts(conn, piece, r, project, roster, loaded, available, send_paths, menu)})
    return found


def _piece_facts(conn, piece, r, project, roster, loaded, available, send_paths, menu):
    """Brief 29 (decision 17): a piece's team (and the planner's, who chose it, why), its chain as filled now, the pick
    it may need, its calls by the count, the approval's refusal, and on a project split its part of the change."""
    found = {"team": split.team_of(piece), "planner_team": piece.get("planner_team") or teams.ROUTE,
             "team_source": piece.get("team_source") or "planner", "team_why": piece.get("team_why"), "chain": None,
             "needs_you": None, "calls": None, "max_calls": None, "refused": None,
             # brief 29.1 (decision 12): the owner's slots on a preset piece, and every slot as the piece would run now
             "slots": dict(piece.get("slots") or {}), "slot_map": _piece_slot_map(piece, roster, loaded, available,
                                                                                 send_paths)}
    if menu is not None:
        view = splitview.piece_view(piece, project=project, conn=conn, roster=roster, loaded=loaded,
                                    available=available, send_paths=send_paths, menu=menu)
        found.update({key: view[key] for key in ("chain", "needs_you", "calls", "max_calls", "refused")})
    record = log.project_files_of(r) if r is not None and project is not None else None
    found["project_files"] = ({"changed": record.get("changed") or [], "diff": record.get("diff"),
                               "mode": record.get("mode"), "why": record.get("why")} if record else None)
    return found


def _piece_slot_map(piece, roster, loaded, available, send_paths):
    """{slot: agent} a preset piece would run with now (the owner's slots, the rest as intake fills them), or None. A slot
    left out (brief 32: the second attack without Cursor) is there as None, as the task row will keep it."""
    team = split.team_of(piece)
    if team == teams.ROUTE or loaded is None or roster is None or send_paths is None or team not in loaded.presets:
        return None
    from router import intake  # intake imports this module's neighbours; kept local
    filled, _ = teams.filled(loaded.presets[team], roster, routing._table(available, roster), send_paths=send_paths,
                             flags=intake.piece_flags(piece))
    return presets.row_slots(filled) if filled is not None else None


def _estimate(conn, row, roster, loaded, available, send_paths):
    """Brief 29 (decision 7): the plan's count from here, with Jev's labels apart; None without a plan or a roster."""
    plan = log.split_plan_of(row)
    if plan is None or roster is None or send_paths is None:
        return None
    project = log.project_of(row)
    menu = teams.menu(loaded, roster, available, project=project is not None, send_paths=send_paths)
    views = [splitview.piece_view(p, project=project, conn=conn, roster=roster, loaded=loaded, available=available,
                                  send_paths=send_paths, menu=menu) for p in plan["pieces"]]
    return splitview.estimate(plan, views, roster=roster, available=available)


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
    if _mode(row) not in ("relay", "split", "plan"):
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


def show_view(conn, row, *, live=None, loaded=None, roster=None, available=None, send_paths=None):
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
    pins = {name: roster.model(name) for name in ("chatgpt", "cursor")} if roster is not None else None  # brief 33.3
    return {"api_version": API_VERSION, **task_view(conn, row, live=live, loaded=loaded, calls=calls),
            "calls": [call_view(c, k, calls, rounds.log_folder(conn), pins) for k, c in enumerate(calls, 1)],
            "handoff": _handoff(row, build), "memory_stored": log.memory_of(row), "memory_given": _memory_given(build),
            "candidates": candidates, "pick": pick, "votes": votes, "tally": tally,
            "attacks": _attacks(view, row) if _mode(row) in log.CHAINED_MODES else None,
            # brief 32 (decision 16): the lists on a lettered redteam task only, so an old task's JSON is as it was
            **({"attack_lists": _attack_lists(row, view)} if _mode(row) in log.CHAINED_MODES and _lettered(row) else {}),
            "pieces": _pieces(conn, row, roster, available, loaded, send_paths) if _mode(row) == "split" else None,
            "join": (log.split_plan_of(row) or {}).get("join") if _mode(row) == "split" else None,
            # brief 29 (decision 17): the count from here and the teams a piece of this split may take now
            "estimate": _estimate(conn, row, roster, loaded, available, send_paths) if _mode(row) == "split" else None,
            "menu": (teams.menu(loaded, roster, available, project=log.project_of(row) is not None, send_paths=send_paths)
                     if _mode(row) == "split" and roster is not None and send_paths is not None else None),
            "original_file": _get(first, "round_file") if first is not None else None,
            "result_file": _result_file(row, calls),
            # brief 33 (decision 12): the from-block as the first call that carried it sent it, for Details
            "from_given": fromblock.first_sent(calls),
            # brief 33.1 (decision 10): a plan's steps with their team's calls and the estimate, the menu as it stands now
            **(_plan_with_menu(conn, row, calls, loaded, roster, available, send_paths) if _mode(row) == "plan" else {})}


def _plan_with_menu(conn, row, calls, loaded, roster, available, send_paths):
    from router import plan  # kept local, as above
    if roster is None or send_paths is None or loaded is None:
        return {}
    found = plan.menu(loaded, roster, available, send_paths=send_paths)
    return {"plan": plan.view(conn, row, found), "plan_menu": found}


def log_view(conn, rows, *, limit, live=None, loaded=None):
    """`sr log --json`: each row's task keys, newest first; `next_before` pages on (the oldest row's id) when the page
    is full."""
    return {"api_version": API_VERSION, "tasks": [task_view(conn, r, live=live, loaded=loaded) for r in rows],
            "next_before": rows[-1]["task_id"] if rows and len(rows) == limit else None}
