"""The one line a card shows outside Details when someone other than the usual agent did the work (build brief 24,
decision 15), composed here once from the rows so Terminal, the JSON and the page say the same words:

    ChatGPT did this · Grok Bot isn't set up · done without Meta
    ChatGPT did the research · Grok Bot isn't set up
    ChatGPT took over the first call · Claude hit its plan limit

The reason on the line is the short form of the availability words (up to the first colon, without a closing
parenthesis); Details keep the whole sentence. A takeover (decision 6) and a Grok check skipped past its limit (the owner's
C11) are read from the task's calls. Pure: it reads a task row and its calls and nothing else."""
import re

from router import availability, log, presets, routing, takeover

SOCIAL_NOTE = routing.SOCIAL_NOTE  # decision 9; "done without Meta": the owner
SLOT_WORDS = {"research": "the research", "build": "the build", "check": "the check", "attack": "the attack",
              "lead": "the lead's part", "partner": "the partner's part"}
_TRAILING = re.compile(r"\s*\([^()]*\)$")


def short(why):
    """`Grok Bot isn't set up: no inbox repo in settings` -> `Grok Bot isn't set up`; `ChatGPT is signed out (codex
    login)` -> `ChatGPT is signed out`."""
    head = (why or "").split(":", 1)[0].strip()
    return _TRAILING.sub("", head) or (why or "")


def note(row, doer=None):
    """`done without X` / `done without Meta` when the social skill's work was done by an agent other than Grok Bot."""
    skill = row["skill"] if "skill" in row.keys() else None
    doer = doer or (row["agent"] if "agent" in row.keys() else None)
    if skill in SOCIAL_NOTE and doer and doer != "grok":
        return SOCIAL_NOTE[skill]
    return None


def stand_in(row, calls=()):
    """{"agent", "for", "why"} for a routed task whose doer stood in for the skill's best agent, else None. The agent is
    the one that stood in at intake: the first call's, when the router later took that call over (decision 6)."""
    found = routing.stand_in_of(row["route_reason"] if "route_reason" in row.keys() else None)
    if found is None:
        return None
    agent = next((c["agent"] for c in calls if c["kind"] == "do"), row["agent"])
    return {"agent": agent, "for": found[0], "why": found[1]}


def filled(row, preset=None):
    """A relay task's slots filled at intake: [{"slot", "agent", "default", "why"}], or None."""
    found = presets.fills_of(row["route_reason"] if "route_reason" in row.keys() else None)
    if not found:
        return None
    defaults = {s.name: s.default for s in preset.slots} if preset is not None else {}
    return [{**f, "default": defaults.get(f["slot"])} for f in found]


def slot_words(slot):
    return SLOT_WORDS.get(slot, f"slot {slot.upper()}")


def skipped(row):
    """The owner's C11: the card's words when Grok Bot's check was skipped past its limit, or []."""
    note_text = row["check_note"] if "check_note" in row.keys() else None
    if not (note_text or "").startswith(takeover.GROK_SKIPPED):
        return []
    checker = row["checker"] if "checker" in row.keys() else None
    who = f"{availability.name_of(checker)} did the check" if checker else "Unchecked"
    return [who, "the check was too long for Grok Bot"]


def parts(row, preset=None, calls=()):
    """The line's parts, in order: who did what (a stand-in or each filled slot), why; a takeover and why; a Grok check
    skipped; and the social note. A stand-in whose own call was taken over is said by the takeover alone."""
    found = []
    took, before = takeover.found(calls) if calls else (None, None)
    doer_moved = took is not None and before["kind"] not in ("check", "recheck")
    reason = row["route_reason"] if "route_reason" in row.keys() else None
    if (reason or "").startswith(routing.NO_FILES_DOER):  # brief 33.2 fix 1b: the one line, as the record has it
        found.append(reason)
    stood = stand_in(row, calls)
    if stood is not None and not doer_moved:
        found += [f"{availability.name_of(stood['agent'])} did this", short(stood["why"])]
    for fill in filled(row, preset) or ():
        found += [f"{availability.name_of(fill['agent'])} did {slot_words(fill['slot'])}", short(fill["why"])]
    if took is not None:
        from router import resume  # resume reads relay, which reads checking; kept local as takeover's words are
        found += [f"{availability.name_of(took['agent'])} took over {resume.stopped_text(before)}",
                  short(takeover.why_words(before))]
    found += model_notes(calls)  # brief 33.3 (decisions 6 and 7)
    found += skipped(row)
    extra = note(row)
    if found and extra:
        found.append(extra)
    if any(_notes_left_out(c) for c in calls or ()):  # brief 30 (decision 6): Grok got no router notes on a call
        from router import notes  # kept local, as the other words here are
        found.append(notes.GROK_LEFT_OUT)
    if any(_spec_left_out(c) for c in calls or ()):  # brief 33.2 (decision 2.4): Grok got no SPEC.md on a call
        from router import spec  # kept local
        found.append(spec.GROK_LEFT_OUT)
    return found


CREDITS_LINE = "stopped: billed to usage credits · Fable is off"  # brief 33.3 (decision 6)


def model_notes(calls):
    """Brief 33.3: the one-line notes about models, each said once: a served model that differs from the one asked
    (decision 7: `Fable 5.1 re-ran this on claude-opus-4-8`), a Fable default that ran on Opus while Fable is off
    (decision 6: the card says why), and a call billed to usage credits (the task stopped, Fable off)."""
    from router import models  # models reads log; kept local as resume is above
    found = []
    for call in calls or ():
        keys = call.keys() if hasattr(call, "keys") else call
        if "served" not in keys or call["agent"] not in models.AGENTS:
            continue
        record = log.served_of(call) or {}
        differs = models.differs_note(call)
        if differs and differs not in found:
            found.append(differs)
        if record.get("note") and record["note"] not in found:
            found.append(record["note"])
        if (record.get("credits") or {}).get("billed") and CREDITS_LINE not in found:
            found.append(CREDITS_LINE)
    return found


def _spec_left_out(call):
    """Brief 33.2 (decision 2.4): a Grok call whose SPEC.md block was left out for its prompt limit."""
    return bool(((log.context_of(call) or {}).get("spec") or {}).get("left_out"))


def _notes_left_out(call):
    """Brief 30 (decision 6): a Grok call whose router notes were left out for its prompt limit."""
    import json
    keys = call.keys() if hasattr(call, "keys") else call
    raw = call["context"] if "context" in keys else None
    try:
        record = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return False
    return call["agent"] == "grok" and isinstance(record, dict) and bool((record.get("notes") or {}).get("left_out"))


def line(row, preset=None, calls=()):
    """The card's one line, or None when the usual agents did the work."""
    found = parts(row, preset, calls)
    return " · ".join(found) if found else None
