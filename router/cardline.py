"""The one line a card shows outside Details when someone other than the usual agent did the work (build brief 24,
decision 15), composed here once from the rows so Terminal, the JSON and the page say the same words:

    ChatGPT did this · Grok Bot isn't set up · done without Meta
    ChatGPT did the research · Grok Bot isn't set up
    ChatGPT took over the first call · Claude hit its plan limit

The reason on the line is the short form of the availability words (up to the first colon, without a closing
parenthesis); Details keep the whole sentence. A takeover (decision 6) and a Grok check skipped past its limit (the owner's
C11) are read from the task's calls. Pure: it reads a task row and its calls and nothing else."""
import re

from router import availability, presets, routing, takeover

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
    stood = stand_in(row, calls)
    if stood is not None and not doer_moved:
        found += [f"{availability.name_of(stood['agent'])} did this", short(stood["why"])]
    for fill in filled(row, preset) or ():
        found += [f"{availability.name_of(fill['agent'])} did {slot_words(fill['slot'])}", short(fill["why"])]
    if took is not None:
        from router import resume  # resume reads relay, which reads checking; kept local as takeover's words are
        found += [f"{availability.name_of(took['agent'])} took over {resume.stopped_text(before)}",
                  short(takeover.why_words(before))]
    found += skipped(row)
    extra = note(row)
    if found and extra:
        found.append(extra)
    return found


def line(row, preset=None, calls=()):
    """The card's one line, or None when the usual agents did the work."""
    found = parts(row, preset, calls)
    return " · ".join(found) if found else None
