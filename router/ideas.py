"""Build brief 33, I (decisions 14 to 16): each registered project's Ideas list, one-line things the owner may want to do
later. The router keeps it in the log (the `ideas` table, log version 18), never in the project folder and never in
memory; an idea reaches an agent only as a task the owner sends from it. Kept by the project's name: `sr project remove`
leaves them. An idea's state is derived from its row and the task that carries it, never stored: dismissed
(`dismissed_at`), used (a task sent from it was delivered; a change once it lands), sent (a task sent from it is still
open, a change waiting to land included), else open. At most `ideas_max` open ideas a project."""
from dataclasses import dataclass
from datetime import datetime, timezone

from router import log, nextsteps, safety, settings, state

MAX_CHARS = 400
LATER, ADDED = "later", "added"
OPEN, SENT, USED, DISMISSED = "open", "sent", "used", "dismissed"
LISTED = (OPEN, SENT)  # decision 16: a used idea leaves the list; a dismissed one too (the log keeps it). Brief 33.2
# fix 4: a used one goes to the sheet's folded Used list (`listing`'s `used`)


class Refused(Exception):
    """An idea refused: `code` is bad_idea or ideas_full; the words never quote a text the key scan matched."""

    def __init__(self, code, why):
        super().__init__(why)
        self.code, self.why = code, why


@dataclass(frozen=True)
class Idea:
    id: int
    project: str
    text: str
    source_kind: str
    source_task: str | None
    created_at: str
    dismissed_at: str | None
    state: str
    task: object  # the task row that carries it while sent, or that used it; None otherwise


def _now(now=None):
    return (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")


def text_refusal(text, secrets=()):
    """Decision 15: the rule a text breaks, in words, or None. One line, not empty, at most 400 characters, not starting
    with @ or /, and nothing the key scan or a .env value matches (named, never quoted)."""
    if not isinstance(text, str) or not text.strip():
        return "an idea is one line of text, and this one is empty"
    if "\n" in text or "\r" in text:
        return "an idea is one line: no line breaks"
    if len(text.strip()) > MAX_CHARS:
        return f"an idea is at most {MAX_CHARS} characters (this one is {len(text.strip()):,})"
    if text.strip()[0] in "@/":
        return "an idea can't start with @ or /, so it never fills an override or a slash command"
    if safety.key_like(text) is not None or safety.redact(text, secrets) != text:
        return "it looks like a key or holds a value from .env, so it isn't kept (the text isn't shown)"
    return None


def _task_rows(conn, idea_id):
    return conn.execute(f"SELECT {log._COLUMNS} FROM tasks WHERE idea = ? ORDER BY rowid DESC", (idea_id,)).fetchall()


def _state(conn, row):
    if row["dismissed_at"]:
        return DISMISSED, None
    tasks = [(t, log.calls_for(conn, t["task_id"])) for t in _task_rows(conn, row["id"])]
    for t, calls in tasks:
        if nextsteps.delivered(t, calls):
            return USED, t
    for t, calls in tasks:
        if t["status"] in ("queued", "sent") or state.of(t, calls).waiting_on is not None:
            return SENT, t
    return OPEN, None


def _idea(conn, row):
    found, task = _state(conn, row)
    return Idea(row["id"], row["project"], row["text"], row["source_kind"], row["source_task"], row["created_at"],
                row["dismissed_at"], found, task)


def all_of(conn, project):
    """Every idea of the project, newest first, with its state."""
    return [_idea(conn, r) for r in conn.execute("SELECT * FROM ideas WHERE project = ? ORDER BY id DESC", (project,))]


def get(conn, idea_id):
    row = conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
    return _idea(conn, row) if row is not None else None


def open_count(conn, project):
    return sum(1 for i in all_of(conn, project) if i.state == OPEN)


def moved_from(conn, row):
    """Decision 7: the words moved to the project's list from this card with Later; they are not offered again."""
    if row is None:
        return ()
    return tuple(r["text"] for r in conn.execute("SELECT text FROM ideas WHERE source_kind = ? AND source_task = ?",
                                                 (LATER, row["task_id"])))


def add(conn, project, text, *, source_task=None, secrets=(), now=None):
    """Decision 15: (the idea, whether it is new). Refused (bad_idea) by the text's rule; an add matching an open idea's
    text (ignoring case, spacing and end punctuation) adds nothing and gives that idea; past `ideas_max` open ideas,
    refused (ideas_full) with nothing written."""
    why = text_refusal(text, secrets)
    if why:
        raise Refused("bad_idea", why)
    text = " ".join(text.split())
    listed = all_of(conn, project)
    same = next((i for i in listed if i.state == OPEN and nextsteps.same_words(i.text, text)), None)
    if same is not None:
        return same, False
    most = settings.next_steps_setting("ideas_max")[0]
    if sum(1 for i in listed if i.state == OPEN) >= most:
        raise Refused("ideas_full", f"{project} has {most} open ideas, the most it keeps (ideas_max); send or dismiss one first")
    cur = conn.execute("INSERT INTO ideas (project, text, source_kind, source_task, created_at) VALUES (?, ?, ?, ?, ?)",
                       (project, text, LATER if source_task else ADDED, source_task, _now(now)))
    conn.commit()
    return get(conn, cur.lastrowid), True


def dismiss(conn, project, idea_id, *, now=None):
    """Decision 16: takes the idea off the list; the log keeps it. Refused (bad_idea) for no such idea, another
    project's, or one already dismissed."""
    found = get(conn, idea_id)
    if found is None or found.project != project:
        raise Refused("bad_idea", f"{project} has no idea {idea_id}")
    if found.state == DISMISSED:
        raise Refused("bad_idea", f"idea {idea_id} was dismissed already")
    conn.execute("UPDATE ideas SET dismissed_at = ? WHERE id = ? AND dismissed_at IS NULL", (_now(now), idea_id))
    conn.commit()
    return get(conn, idea_id)


def intake_refusal(conn, idea_id, project):
    """Decision 16: why `--idea <id>` can't go on this task (bad_idea), or None: not an idea, another project's, a task
    without that --project, or an idea that isn't open."""
    found = get(conn, idea_id) if isinstance(idea_id, int) else None
    if found is None:
        return f"there is no idea {idea_id}"
    if project is None:
        return f"idea {idea_id} is {found.project}'s: send it with --project {found.project}"
    if found.project != project:
        return f"idea {idea_id} is {found.project}'s, not {project}'s"
    if found.state != OPEN:
        return f"idea {idea_id} isn't open (it is {_state_words(found)})"
    return None


def _state_words(idea):
    if idea.state == SENT:
        return f"sent as #{idea.task['n']}"
    return idea.state


def view(conn, idea):
    """One idea in the JSON: id, text, source (its kind, and the card's task_id and n on a Later), created_at, state, and
    the task that carries it while sent."""
    source = log.get_task(conn, idea.source_task) if idea.source_task else None
    return {"id": idea.id, "text": idea.text,
            "source": {"kind": idea.source_kind, "task_id": idea.source_task, "n": source["n"] if source else None,
                       # brief 33.4 (decision 10): told apart by the source task's mode, not by a new kind
                       "suggested": bool(source is not None and source["mode"] == "suggest")},
            "created_at": idea.created_at, "state": idea.state,
            "sent_as": ({"task_id": idea.task["task_id"], "n": idea.task["n"]} if idea.state == SENT else None)}


def line(found):
    """One idea as `sr ideas` prints it: its id and text, where it came from, its date, and its task while sent."""
    source = found["source"]
    where = f"Later on #{source['n']}" if source["kind"] == LATER and source.get("n") else "Added"
    if source.get("suggested"):  # brief 33.4 (decision 13)
        where = f"Suggested by #{source['n']}"
    sent = f" · sent as #{found['sent_as']['n']}" if found.get("sent_as") else ""
    return f"{found['id']:>3}  {found['text']}  ({where}, {found['created_at'][:10]}){sent}"


def listing(conn, project):
    """`sr ideas <project> --json` (decision 18): the open ideas, newest first, each with its state, and the dismissed
    count. Brief 33.2 fix 4 (the owner's decision 4): and the used ideas, newest first, each with the task that used it
    (`used_by`), for the sheet's folded Used list; `ideas` holds open and sent ones only, as before."""
    found = all_of(conn, project)
    return {"project": project, "ideas": [view(conn, i) for i in found if i.state in LISTED],
            "dismissed": sum(1 for i in found if i.state == DISMISSED),
            "used": [{**view(conn, i), "used_by": {"task_id": i.task["task_id"], "n": i.task["n"]}}
                     for i in found if i.state == USED]}
