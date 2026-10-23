"""What an action's JSON needs from inside the command (rules v2.30, Router for the interface: every action takes
`--json`; build brief 21). With `--json`, main hands the command a Receipt as its `out`: it keeps every prose line the
command prints (the JSON's `message`, so the words are the ones `sr` prints today) and what the command marks: the task
it acted on and the reason_code of a refusal or a return. Without `--json` the command's `out` is print, which has no
`mark`, so `mark()` does nothing and the prose is printed as it always was."""

# Every reason_code a refusal or a return may carry in the JSON (the brief 21 inventory). A return's code is also
# stored on the row (log.RETURN_CODES); a refusal writes no row, so its code lives in the JSON only.
REFUSAL_CODES = (
    "billing_switch", "setup", "not_live", "bad_task", "override_refused", "tag_refused", "project_unknown",
    "project_busy", "handoff_unreadable", "project_refused", "bad_name", "probe_failed", "signed_out", "not_configured",
    "bad_file", "files_to_agent", "flag_refused", "bad_preset", "slot_refused", "too_long", "usage", "unknown_task",
    "ambiguous_task", "wrong_state", "already_used", "not_resumable", "no_fallback", "memory_down", "inbox_unreadable",
    "state_changed", "stuck", "interrupted", "internal_error",
    "needs_label",  # brief 22 (decision 9): `sr split --go --answer y` with a piece Jev left under the floor and no --skill
    "unreachable",  # brief 24 (decision 1): an agent the task needs whose online check did not answer
    "project_partial",  # brief 26 (decision 7): `sr project new` stopped after the folder was made; what exists is named
    "memory_off",  # brief 27 (decision 8): `sr memory start` or `rebuild` while memory is off; `sr memory on` turns it on
)


class Receipt:
    """`out` for one `--json` command. `multi` (sr check, which moves every open task): only a mark made with
    `command=True` counts, since the deeper marks are about one of the tasks it moved, not about the command."""

    def __init__(self, multi=False):
        self.lines, self.task_id, self.code, self.multi = [], None, None, multi
        self.document = None  # a read command's own JSON document (deliver), printed in place of the envelope
        self.extra = {}  # brief 26: keys added after the envelope's own (a new project's `project`)

    def __call__(self, line=""):
        self.lines.append(str(line))

    def mark(self, *, task_id=None, code=None, command=False):
        if self.multi and not command:
            return
        if task_id is not None and self.task_id is None:
            self.task_id = task_id
        if code is not None and self.code is None:
            self.code = code

    @property
    def message(self):
        return "\n".join(self.lines)


def mark(out, *, task_id=None, code=None, command=False):
    """Tell a Receipt which task the command acted on, or why it refused or returned; nothing without one. The first
    mark of each kind wins: a command marks where it decides, and an outer site never overrides an inner one."""
    marker = getattr(out, "mark", None)
    if marker is not None:
        marker(task_id=task_id, code=code, command=command)


def attach(out, **keys):
    """Brief 26 (decision 11): keys the envelope carries after its own eight, such as `project` on a successful
    `sr project new`. Nothing without a Receipt."""
    if isinstance(out, Receipt):
        out.extra.update(keys)


def deliver(out, document):
    """A read command's JSON document (`sr project list --json`, `sr status --json`, ...): main prints it in place of the
    action envelope. Nothing without a Receipt."""
    if isinstance(out, Receipt):
        out.document = document
