"""Build brief 25 (decision 3): docs/RULES.md, the cleaned copy of SUPER-ROUTER.md that every publish makes.

One fixed transform, in this order: every "Changes from" section, and any section whose heading holds a forbidden word,
is dropped; TABLE generalises the personal lines, each row anchored on words that are not private and matching exactly
once (a row that matches nothing, or twice, means the rules moved under it: the publish stops until the table follows);
then any list item still holding a forbidden word is dropped whole; line 1 becomes the title and line 3 keeps the
version with a new tail; the owner's first name reads as "the owner" (as a stored value in lower case, `owner`), and
third-person pronouns, he and she alike, as the singular they. The forbidden words and the name are this Mac's
(`publish_forbidden` and the first name of `id -F`, passed in by scripts/publish.py) and never spelled here, because
this file goes public too. SUPER-ROUTER.md itself never changes: only its owner edits it."""
import re

TITLE = "# Super Router rules"
VERSION_LINE = re.compile(r"^(Version \d+\.\d+ · \d{4}-\d{2}-\d{2}) · .*$")
VERSION_TAIL = "A cleaned copy of the owner's rules, made at each publish."
DROP_PREFIX = "Changes from "

# (what it generalises, the pattern, the replacement): each pattern must match exactly once.
TABLE = (
    ("the brokerage line in Money",
     re.compile(r"^- No \S+ access of any kind\. This project never touches real money\.$", re.M),
     "- No brokerage access of any kind. This project never touches real money."),
    ("the never-registered folder in Project context",
     re.compile(r"`~/Projects/[a-z0-9-]+` is never registered\."),
     "A folder named in the `never_register` setting is never registered."),
    ("the drop folder on the owner's Mac in Media",
     re.compile(r"`~/Desktop/Router Drop` on [^`\s]+'s Mac"),
     "`~/Desktop/Router Drop` by default"),
)

# A list item (`- `, `* `, `+ ` or `1. `) and the lines indented under it: dropped whole when it still holds a forbidden
# word after the table has run.
ITEM = re.compile(r"^(\s*)(?:[-*+]|\d+\.)\s")

# Third-person pronouns, the he and she sets alike: a subject reads "the owner" (its verb stays as it is), the rest the
# singular they. A possessive standing alone ("his" before punctuation, "hers") reads "theirs"; "her" before punctuation
# or a word that can't follow a possessive reads "them", otherwise "their".
_OBJECT_NEXT = (r"(?=[.,;:)!?]|$|\s+(?:to|and|or|but|nor|so|if|when|while|before|after|until|unless|once|as|than|that|"
                r"this|these|those|the|a|an|first|again|now|then|too|also|back|about|at|by|for|from|in|into|of|off|on|"
                r"out|over|through|up|with|without|what|which|who|how|why|where)\b)")
PRONOUNS = (
    (re.compile(r"\b(?:He|She)\b"), "The owner"),
    (re.compile(r"\b(?:he|she)\b"), "the owner"),
    (re.compile(r"\b(?:His|Her)\b"), "Their"),
    (re.compile(r"\b(?:his|hers)\b(?=[.,;:)!?]|$)", re.M), "theirs"),
    (re.compile(r"\bhers\b"), "theirs"),
    (re.compile(r"\b(?:himself|herself)\b"), "themselves"),
    (re.compile(r"\bhim\b"), "them"),
    (re.compile(r"\bher\b" + _OBJECT_NEXT, re.M), "them"),
    (re.compile(r"\b(?:his|her)\b"), "their"),
)

# A sentence starts at a list item or a table cell (bold or not), after a sentence's end inside the line, or at a line
# whose line before ended one (the file wraps some paragraphs, so a line start alone is not a sentence start).
INSIDE = re.compile(r"""(^\s*(?:[-*]|\d+\.)\s+(?:\*\*)?|\|\s+(?:\*\*)?|[.!?](?:\*\*|["”’')\]]*)\s+)the owner""")
ENDS_SENTENCE = re.compile(r"""[.!?](?:\*\*|["”’')\]]*)\s*$""")


class RulesCopyError(ValueError):
    """The rules moved under the transform; the publish stops and says which part."""


def sections(text):
    """[(heading or None, its text)] split at `## ` headings; the part before the first heading has None."""
    parts, head, lines = [], None, []
    for line in text.splitlines(keepends=True):
        if line.startswith("## "):
            parts.append((head, "".join(lines)))
            head, lines = line[3:].strip(), [line]
        else:
            lines.append(line)
    parts.append((head, "".join(lines)))
    return parts


def dropped(heading, forbidden=()):
    """True for a "Changes from" section and for a heading that holds a forbidden word, in any case."""
    return heading.startswith(DROP_PREFIX) or any(w.lower() in heading.lower() for w in forbidden if w.strip())


def drop_items(text, forbidden=()):
    """`text` without each list item, with the lines indented under it, that holds a forbidden word, in any case."""
    words = [w.strip().lower() for w in forbidden if w.strip()]
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        item, end = ITEM.match(lines[i]), i + 1
        if item:
            while (end < len(lines) and lines[end].strip() and not ITEM.match(lines[end])
                   and len(lines[end]) - len(lines[end].lstrip()) > len(item.group(1))):
                end += 1
        if not (item and any(w in "\n".join(lines[i:end]).lower() for w in words)):
            out.extend(lines[i:end])
        i = end
    return "\n".join(out)


def _capitalise(text):
    out, before = [], None
    for line in text.split("\n"):
        line = INSIDE.sub(lambda m: m.group(1) + "The owner", line)
        stars = len(line) - len(line.lstrip("*"))
        if line[stars:].startswith("the owner") and (before is None or not before.strip() or before.startswith("#")
                                                     or ENDS_SENTENCE.search(before)):
            line = line[:stars] + "T" + line[stars + 1:]
        out.append(line)
        before = line
    return "\n".join(out)


def read_as_owner(text, name=None):
    """The owner's first name `name` (passed in, never spelled here) as "the owner", and in lower case, a stored value, as
    `owner`; third-person pronouns, he and she alike, as the singular they; capitalised where a sentence starts. Without
    a name, only the pronouns."""
    if name:
        alone = r"(?![A-Za-z])"
        text = re.sub(rf"(?<![A-Za-z]){re.escape(name)}'s{alone}", "the owner's", text)
        text = re.sub(rf"(?<![A-Za-z]){re.escape(name)}{alone}", "the owner", text)
        text = re.sub(rf"(?<![A-Za-z]){re.escape(name.lower())}{alone}", "owner", text)
    for pattern, new in PRONOUNS:
        text = pattern.sub(new, text)
    return _capitalise(text)


def transform(source, forbidden=(), name=None):
    """docs/RULES.md from SUPER-ROUTER.md's text, with this Mac's forbidden words and the owner's first name passed in.
    RulesCopyError when the rules moved under a fixed part."""
    text = "".join(body for head, body in sections(source) if head is None or not dropped(head, forbidden))
    for what, pattern, new in TABLE:
        text, n = pattern.subn(new, text)
        if n != 1:
            raise RulesCopyError(f"{what}: matched {n} times, not once; the rules moved under the transform")
    lines = drop_items(text, forbidden).split("\n")
    version = VERSION_LINE.match(lines[2]) if len(lines) > 2 else None
    if not version or not lines[0].startswith("# "):
        raise RulesCopyError("line 3 is not the version line (or line 1 is not the title)")
    lines[0], lines[2] = TITLE, f"{version.group(1)} · {VERSION_TAIL}"
    return read_as_owner("\n".join(lines), name)
