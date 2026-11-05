"""Build brief 33.4 (decisions 6 and 6b): the notes' one section, "Current plan's decisions", in the part of a project's
HANDOFF.md above the router's block. The router writes it in a new plan's land commit: each new plan's Approve replaces it,
one with no questions clears it, a revision leaves it, and Undo puts it back from the copy stored on the plan's record. Pure
text work: the commit is the land's. Anything the owner wrote there is replaced anyway; the Approve confirm says so."""
import hashlib
import re

from router import projnotes

TITLE = "Current plan's decisions"
HEADING = f"## {TITLE}"
_ANY_HEADING = re.compile(r"^#{1,2}(?!#)\s")
_PIN = re.compile(r"^### Pinned from #")  # `sr project pin` appends these at the notes' end: never the section's to replace


def _span(lines):
    """(start, end) of the section among the notes' lines, or None: from its heading to the next one- or two-hash heading,
    or a pin."""
    start = next((i for i, line in enumerate(lines) if line.strip() == HEADING), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if _ANY_HEADING.match(lines[i]) or _PIN.match(lines[i])), len(lines))
    return start, end


def read(text):
    """The section as it stands in a HANDOFF.md's text, its heading included, trailing blank lines dropped, or None."""
    lines = projnotes.parts_of(text).notes.split("\n")
    found = _span(lines)
    return "\n".join(lines[found[0]:found[1]]).rstrip() if found else None


def replaced(text, section):
    """The HANDOFF.md's text with the section replaced in place, added at the notes' end, or gone (`section` None). The
    rest of the notes and the router's block stay byte for byte, in the file's own line endings."""
    parts = projnotes.parts_of(text)
    lines = parts.notes.split("\n") if parts.notes else []
    found = _span(lines)
    new = section.split("\n") if section else []
    if found:
        start, end = found
        before, after = lines[:start], lines[end:]
        if not new:
            while before and not before[-1].strip():
                before.pop()
            return projnotes.compose(parts, "\n".join(before + ([""] + after if before and after else after)))
        return projnotes.compose(parts, "\n".join(before + new + ([""] + after if after else [])))
    if not new:
        return text
    return projnotes.compose(parts, "\n".join(lines + ([""] if lines else []) + new))


def render(answers):
    """The section the router writes from a plan's answers, or None with none (a new plan with no questions clears it)."""
    if not answers:
        return None
    rows = [f"- {a['question']} **{a['answer']}**" + (" (the planner's guess)" if a.get("how") == "guess" else "")
            for a in answers]
    return "\n".join([HEADING, "", *rows])


def digest(section):
    """The hash of a section as the router wrote it; an absent one hashes as empty."""
    return hashlib.sha256((section or "").strip().encode("utf-8")).hexdigest()[:16]
