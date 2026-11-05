"""Build brief 33.2, S1 (decisions 1 to 5): the project's SPEC.md. The reader and its labels; the intake copy, its hash and
its three refusals; the block after the STEP block and before the handoff; Grok's order (memory, notes, spec, then the
handoff's trim); the judge's line on a check, re-check, review and attack; the records on each call and in the JSON; a
piece sending from its split's copy, a run's step from its own; the put-back after a build and after a fix, the diff
without it, the card's record; the Land backstop; Save to project and files in; the editor; `--no-files`. Real git in
temp folders, fake agents; a key-shaped value is built at run time from pieces; every value here is fake."""
import json
import secrets as random_secrets

import pytest

from router import __main__ as cli
from router import context, copies, filecalls, gitops, landing, log, projects, projspec, rounds, spec
from tests.helpers import fake_label
from tests.test_auto_run import _auto, _route_plan
from tests.test_copies import git
from tests.test_filemode_flow import BUILD, CODE, CopyWorker, conn, project, route, runner  # noqa: F401 (fixtures)
from tests.test_handoff_contract import HANDOFF
from tests.test_loop import Clock, Webhook
from tests.test_plan_steps import SKELETON, _approved, _route_step
from tests.test_relay import CONFIG, ROSTER, Chat

SPEC = ("# Converter\n\nA tiny temperature converter.\n\n## Examples\n\n- c_to_f(100) == 212\n- f_to_c(212) == 100\n"
        "- c_to_f(-40) == -40\n\n## Done when\n\n1. both functions pass their tests\n2. README.md says how to run them\n")
TEXT_SPEC = "# Converter\n\nA tiny temperature converter, as text alone.\n"  # no lists: a plan needs no `covers:` (C)


def _key():
    return "to" + "ken: " + random_secrets.token_hex(8)


def _commit_spec(folder, text=SPEC, message="spec"):
    (folder / "SPEC.md").write_text(text)
    git(folder, "add", "SPEC.md")
    git(folder, "commit", "-q", "-m", message)


# ---------- decision 1: the reader ----------

def test_the_two_headings_give_labels_by_order_and_the_rest_is_text():
    found = spec.parse(SPEC)
    assert [e["label"] for e in found.examples] == ["E1", "E2", "E3"]
    assert found.examples[0]["text"] == "c_to_f(100) == 212" and found.examples[2]["text"] == "c_to_f(-40) == -40"
    assert found.done_when == [{"label": "D1", "text": "both functions pass their tests"},
                               {"label": "D2", "text": "README.md says how to run them"}]
    assert found.has_examples and found.has_done_when and found.labeled


def test_dash_star_plus_and_numbered_lists_all_count_and_the_files_numbers_never_do():
    text = "## Examples\n* a\n+ b\n7. c\n9) d\n"
    assert [e["text"] for e in spec.parse(text).examples] == ["a", "b", "c", "d"]
    assert [e["label"] for e in spec.parse(text).examples] == ["E1", "E2", "E3", "E4"]


def test_an_item_ends_at_a_blank_line_or_the_next_heading_and_a_continuation_line_joins_it():
    text = "## Examples\n- one that\n  goes on\n\nnot an item\n- two\n## Done when\n- d\nstill d\n# Other\n- not a label\n"
    found = spec.parse(text)
    assert [e["text"] for e in found.examples] == ["one that goes on", "two"]
    assert [d["text"] for d in found.done_when] == ["d still d"]


def test_one_heading_alone_an_empty_heading_or_neither_heading():
    only = spec.parse("## Examples\n- a\n")
    assert only.has_examples and not only.has_done_when and only.labeled
    empty = spec.parse("## Examples\n\nsome prose\n\n## Done when\n")
    assert empty.examples == [] and empty.done_when == [] and not empty.labeled
    plain = spec.parse("Just a paragraph.\n\n## Scope\n- not read\n")
    assert plain.examples == [] and plain.done_when == [] and not plain.labeled


def test_headings_read_without_case_a_one_hash_heading_too_and_a_fenced_one_not():
    assert [e["text"] for e in spec.parse("# EXAMPLES:\n- x\n").examples] == ["x"]
    assert [d["text"] for d in spec.parse("## Done When.\n- y\n").done_when] == ["y"]
    assert spec.parse("```\n## Examples\n- fenced\n```\n").examples == []
    assert spec.parse("### Examples\n- deeper\n").examples == []  # three hashes are text


def test_the_first_of_a_repeated_heading_wins_and_crlf_reads_as_lf():
    found = spec.parse("## Examples\r\n- a\r\n\r\n## Examples\r\n- b\r\n")
    assert [e["text"] for e in found.examples] == ["a"] and found.text == "## Examples\n- a\n\n## Examples\n- b\n"


# ---------- decision 2.3: the three checks ----------

def test_the_cap_a_env_value_and_a_key_shape_are_named_by_line_never_by_text():
    assert spec.problem("x" * 6001) == ("SPEC.md is 6,001 characters; at most 6,000", None)
    assert spec.problem("ok\nholds secret-value-here\n", secrets=("secret-value-here",)) == ("SPEC.md line 2 holds a value from .env", 2)
    found = spec.problem(f"## Examples\n- a\n{_key()}\n")
    assert found[0] == "SPEC.md line 3 looks like it holds a key" and found[1] == 3
    assert spec.problem(SPEC) is None
    assert spec.max_chars() == 6000


def test_the_folders_file_is_exactly_spec_md_never_a_case_twin_nor_a_link(tmp_path):
    assert spec.read_text(tmp_path) is None
    (tmp_path / "spec.md").write_text("lower")
    assert spec.read_text(tmp_path) is None  # a name differing only by case is not the spec
    (tmp_path / "spec.md").unlink()
    (tmp_path / "SPEC.md").write_text(SPEC)
    assert spec.read_text(tmp_path) == SPEC and spec.folder_hash(tmp_path) == spec.digest(SPEC)
    (tmp_path / "SPEC.md").unlink()
    (tmp_path / "real.md").write_text("x")
    (tmp_path / "SPEC.md").symlink_to(tmp_path / "real.md")
    assert spec.read_text(tmp_path) is None and spec.folder_hash(tmp_path) is None


# ---------- decision 2: the copy, the block, the records ----------

def _prompts(worker):
    return [c["prompt"] for c in worker.calls]


def test_a_routed_project_task_keeps_the_copy_and_every_call_carries_the_block_judges_the_line(project, conn, runner):
    _commit_spec(project)
    worker, chat = CopyWorker(BUILD, BUILD), Chat("FIX\n1. [must] Name the file.", "PASS")
    code, said, row = route(conn, worker=worker, chatgpt=chat)
    assert code == 0, said
    folder = rounds.log_folder(conn)
    kept = folder / "tasks" / row["task_id"] / "SPEC.md"
    assert kept.read_text() == SPEC and (kept.stat().st_mode & 0o777) == 0o600
    do, fix = _prompts(worker)
    check, recheck = chat.prompts
    block = spec.render("garden", SPEC)
    for prompt in (do, fix, check, recheck):
        assert block in prompt
        assert prompt.index(block) < prompt.index(context.start_marker("garden"))  # before the handoff block
        assert prompt.index(block) > prompt.index(row["task"])                       # after the task
    assert spec.JUDGE_LINE not in do and spec.JUDGE_LINE not in fix
    assert check.index(block) < check.index(spec.JUDGE_LINE) < check.index(context.start_marker("garden"))
    assert spec.JUDGE_LINE in recheck
    calls = log.calls_for(conn, row["task_id"])
    records = [json.loads(c["context"])["spec"] for c in calls]
    assert records[0] == {"hash": spec.digest(SPEC), "chars": len(SPEC), "from": row["task_id"]}
    assert all(r == records[0] for r in records)
    doc = cli.jsonview.show_view(conn, log.get_task(conn, row["task_id"]))
    assert doc["spec"] == {"hash": spec.digest(SPEC), "chars": len(SPEC), "file": f"tasks/{row['task_id']}/SPEC.md",
                           "left_out": None}  # the review: decision 19's "left out" names the call that went without it
    assert doc["calls"][0]["spec"] == records[0] and doc["calls"][1]["spec"]["hash"] == spec.digest(SPEC)


def test_the_build_paragraph_grows_the_clause_only_with_a_spec(project, conn, runner):
    worker = CopyWorker(BUILD)
    code, said, row = route(conn, worker=worker, chatgpt=Chat("PASS"))
    task = log.get_task(conn, row["task_id"])
    assert spec.BUILD_CLAUSE not in filecalls.with_blocks(conn, task, "do", None, "claude", "p")
    assert spec.BUILD_CLAUSE not in _prompts(worker)[0]
    cli.cmd_land([row["task_id"]], conn=conn, config=CONFIG, verb="discard", out=lambda line: None)  # the project free again
    _commit_spec(project)
    worker = CopyWorker(BUILD)
    code, said, row = route(conn, worker=worker, chatgpt=Chat("PASS"))
    assert code == 0, said
    assert _prompts(worker)[0].rstrip().endswith(spec.BUILD_CLAUSE)


def test_without_a_spec_nothing_changes_no_copy_no_block_no_record(project, conn, runner):
    worker, chat = CopyWorker(BUILD), Chat("PASS")
    code, said, row = route(conn, worker=worker, chatgpt=chat)
    assert code == 0
    assert not (rounds.log_folder(conn) / "tasks" / row["task_id"] / "SPEC.md").exists()
    assert spec.MARK + " SPEC.md" not in _prompts(worker)[0] and spec.JUDGE_LINE not in chat.prompts[0]
    assert "spec" not in (json.loads(log.calls_for(conn, row["task_id"])[0]["context"]) or {})


def test_an_edit_mid_task_never_changes_a_running_task(project, conn, runner):
    _commit_spec(project)
    seen = []

    def edit_then_build(prompt, copy=None, search=False, **kw):
        seen.append(prompt)
        (project / "SPEC.md").write_text("# Changed\n\n## Examples\n- other\n")
        git(project, "commit", "-q", "-am", "edited mid-task")
        return CopyWorker(BUILD)(prompt, copy=copy, search=search, **kw)
    chat = Chat("PASS")
    code, said, row = route(conn, worker=edit_then_build, chatgpt=chat)
    assert code == 0, said
    assert spec.render("garden", SPEC) in chat.prompts[0] and "- other" not in chat.prompts[0]


@pytest.mark.parametrize("text, words", [
    ("x" * 6001, "SPEC.md is 6,001 characters"),
    ("# Converter\n\nsecret-value-here\n", "SPEC.md line 3 holds a value from .env"),
    ("# Converter\n\n## Examples\n- a\n", "SPEC.md line 5 looks like it holds a key"),
])
def test_a_spec_that_fails_a_check_refuses_the_task_before_jev_with_nothing_written(project, conn, runner, text, words):
    if "looks like" in words:
        text += _key() + "\n"
    (project / "SPEC.md").write_text(text)
    label = fake_label(CODE)
    lines, clock, hook = [], Clock(), Webhook()
    before = len(log.recent_tasks(conn, 50))
    code = cli.cmd_route("x", conn=conn, config={**CONFIG, "SECRET_ONE": "secret-value-here"}, roster=ROSTER, environ={},
                         settings_paths=[], label=label, post=hook.post, worker=CopyWorker(), chatgpt=Chat("PASS"),
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=True, out=lines.append, project="garden", files_ready=lambda: (True, None))
    said = "\n".join(lines)
    assert code == 2 and label.calls == [] and len(log.recent_tasks(conn, 50)) == before
    assert words in said and "Nothing was logged or sent" in said and "secret-value-here" not in said
    assert not copies.exists(cli.ids.new_task_id()) and not list((rounds.log_folder(conn) / "tasks").glob("*/SPEC.md")) \
        if (rounds.log_folder(conn) / "tasks").exists() else True


def test_a_plan_and_a_relay_refuse_a_bad_spec_the_same_way(project, conn, runner):
    from tests.test_plan_chain import World
    (project / "SPEC.md").write_text("x" * 6001)
    w = World()
    code, row = w.plan(conn)
    assert code == 2 and "SPEC.md is 6,001 characters" in w.said and row is None or code == 2
    from tests.test_filemode_flow import relay
    found = relay(conn, "research-build", worker=CopyWorker(BUILD))
    assert found[0] == 2 and "SPEC.md is 6,001 characters" in found[1]


def test_the_step_block_comes_before_the_spec_block_and_the_spec_before_the_handoff(project, conn, runner):
    _commit_spec(project, TEXT_SPEC)
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    found = _approved(conn)
    worker = CopyWorker(SKELETON)
    code, said, step = _route_step(conn, f"{found['n']}:1", worker=worker)
    assert code == 0, said
    do = _prompts(worker)[0]
    block = spec.render("garden", TEXT_SPEC)
    assert do.index("This task is step 1 of the project's plan") < do.index(block) < do.index(context.start_marker("garden"))


def test_a_piece_sends_from_its_splits_copy_and_a_runs_step_from_its_own(project, conn, runner, tmp_path):
    folder = tmp_path / "log"
    folder.mkdir()
    assert spec.keep_copy(folder, "sr-split", SPEC) == folder / "tasks" / "sr-split" / "SPEC.md"
    piece = {"task_id": "sr-piece", "parent": "sr-split"}
    assert spec.copy_of(folder, piece) == (SPEC, "sr-split")
    spec.keep_copy(folder, "sr-piece", "# own\n")
    assert spec.copy_of(folder, piece) == ("# own\n", "sr-piece")  # its own first (a run's step keeps one at intake)
    assert spec.copy_of(folder, {"task_id": "sr-none", "parent": None}) == (None, None)
    assert spec.copy_of(None, piece) == (None, None)
    # a run's step reads the folder's spec at its own intake
    _commit_spec(project, TEXT_SPEC)
    _route_plan(conn, _approved(conn))
    code, out, run = _auto(conn)
    assert code == 0, out.message
    for step in log.pieces_of(conn, run["task_id"]):
        assert (rounds.log_folder(conn) / "tasks" / step["task_id"] / "SPEC.md").read_text() == TEXT_SPEC
    assert not (rounds.log_folder(conn) / "tasks" / run["task_id"] / "SPEC.md").exists()  # the run makes no call


def test_the_order_on_grok_is_memory_then_notes_then_the_spec_then_the_handoff():
    handoff = context.Handoff("demo", f"Notes.\n\n{projects.START}\n\n{projects.END}", 4)
    entries = [object()]

    def fit(limit, lead, block):
        import router.context as c
        real = c.memory_part
        c.memory_part = lambda tag, kept, cap: "M" * 50
        try:
            return context.fit_with_spec("p", handoff, entries, "chat:x", limit, 2000, lead=lead, spec=block)
        finally:
            c.memory_part = real
    lead, block = "L" * 30 + "\n\n", "S" * 40
    base = len("p") + 2 + len(context.render("demo", handoff.text))
    with_spec = base + 2 + len(block)
    assert fit(with_spec + len(lead) + 2 + 50, lead, block)[2:] == (entries, True, True)   # everything fits
    assert fit(with_spec + len(lead), lead, block)[2:] == ([], True, True)                 # memory gives way first
    assert fit(with_spec, lead, block)[2:] == ([], False, True)                            # then the notes, whole
    assert fit(base, lead, block)[0] == handoff.text and fit(base, lead, block)[2:] == ([], False, False)  # then the spec
    text, lines, kept, notes_in, spec_in = fit(base - 1, lead, block)                      # only then the handoff is cut
    assert text != handoff.text and notes_in is False and spec_in is False
    assert fit(base + 10, "", "")[2:] == ([], True, False)                                # no spec: today's order


def test_show_handoff_prints_the_spec_as_sent_after_the_handoff(project, conn, runner):
    _commit_spec(project)
    code, said, row = route(conn, worker=CopyWorker(BUILD), chatgpt=Chat("PASS"))
    lines = []
    cli.cmd_show(conn=conn, words=[row["task_id"]], handoff=True, out=lines.append)
    text = "\n".join(lines)
    assert "Handoff as sent to" in text and "SPEC.md as sent" in text and "c_to_f(100) == 212" in text
    assert text.index("Handoff as sent to") < text.index("SPEC.md as sent")


# ---------- decision 3: only the owner changes it ----------

def test_a_builds_change_to_spec_md_is_put_back_before_the_check_and_the_diff_never_shows_it(project, conn, runner):
    _commit_spec(project)
    edit = (BUILD[0], {**BUILD[1], "SPEC.md": "# Rewritten by the agent\n"})
    worker, chat = CopyWorker(edit, edit), Chat("FIX\n1. [must] Name the file.", "PASS")
    code, said, row = route(conn, worker=worker, chatgpt=chat)
    assert code == 0, said
    found = log.project_files_of(log.get_task(conn, row["task_id"]))
    assert found["spec_restored"] is True
    assert [c["path"] for c in found["changed"]] == ["calc.py", "test_calc.py"]
    assert "SPEC.md" not in chat.prompts[0] .split("CHANGE")[-1].split("=====")[0] if "CHANGE" in chat.prompts[0] else True
    assert (copies.folder_of(row["task_id"]) / "SPEC.md").read_text() == SPEC
    assert said.count(spec.PUT_BACK_LINE) == 2  # after the build and after the fix


def test_a_build_that_adds_a_spec_to_a_project_without_one_loses_it(project, conn, runner):
    edit = (BUILD[0], {**BUILD[1], "SPEC.md": "# Made up\n"})
    code, said, row = route(conn, worker=CopyWorker(edit), chatgpt=Chat("PASS"))
    found = log.project_files_of(log.get_task(conn, row["task_id"]))
    assert found["spec_restored"] is True and "SPEC.md" not in [c["path"] for c in found["changed"]]
    assert not (copies.folder_of(row["task_id"]) / "SPEC.md").exists()


def test_land_refuses_a_change_that_still_touches_spec_md(project, conn, runner):
    _commit_spec(project)
    code, said, row = route(conn, worker=CopyWorker(BUILD), chatgpt=Chat("PASS"))
    found = log.project_files_of(log.get_task(conn, row["task_id"]))
    (copies.folder_of(row["task_id"]) / "SPEC.md").write_text("# agent\n")  # forged after the put-back
    log.update_project_files(conn, row["task_id"], changed=found["changed"] + [{"path": "SPEC.md", "status": "changed",
                                                                                "plus": 1, "minus": 1}])
    lines = []
    code = cli.cmd_land([row["task_id"]], conn=conn, config=CONFIG, verb="land", out=lines.append)
    assert code == 2 and "SPEC.md is yours" in "\n".join(lines)
    assert (project / "SPEC.md").read_text() == SPEC and git(project, "status", "--porcelain").decode().strip() == ""


def test_save_to_project_writes_spec_md_once_and_files_in_takes_one(project, conn, runner, tmp_path):
    code, said, row = route(conn, worker=CopyWorker(("# Draft\n\n## Examples\n- a\n\n## Done when\n- b\n\n" + HANDOFF, {})),
                            chatgpt=Chat("PASS"))
    lines = []
    code = cli.cmd_project(["save", "garden"], conn=conn, task=row["task_id"], path="SPEC.md", out=lines.append,
                           secrets=())
    assert code == 0, lines
    assert (project / "SPEC.md").read_text().startswith("# Draft") and spec.parse(spec.read_text(project)).labeled
    lines = []
    code = cli.cmd_project(["save", "garden"], conn=conn, task=row["task_id"], path="SPEC.md", out=lines.append,
                           secrets=())
    assert code == 2 and "already" in "\n".join(lines)  # never overwrites: the editor replaces
    incoming = tmp_path / "in" / "SPEC.md"
    incoming.parent.mkdir()
    incoming.write_text(SPEC)
    (project / "SPEC.md").unlink()
    git(project, "commit", "-q", "-am", "spec removed")
    lines = []
    code = cli.cmd_project(["files", "garden"], conn=conn, files=[str(incoming)], out=lines.append, secrets=())
    assert code == 0, lines
    assert (project / "SPEC.md").read_text() == SPEC


# ---------- decision 4: the editor ----------

def _spec_cmd(conn, name, *, save=False, text=None, expect=None, as_json=False):
    lines = []
    out = cli.receipt.Receipt() if as_json else lines.append
    code = cli.cmd_project(["spec", name], conn=conn, as_json=as_json, notes=text, save=save, expect=expect, out=out,
                           secrets=())
    return code, (out if as_json else "\n".join(lines))


def test_spec_prints_the_file_its_hash_and_the_labels_as_read_or_none(project, conn):
    code, said = _spec_cmd(conn, "garden")
    assert code == 0 and "Spec of garden: none" in said
    _commit_spec(project)
    code, said = _spec_cmd(conn, "garden")
    assert code == 0 and f"hash {spec.digest(SPEC)}" in said and "E1 c_to_f(100) == 212" in said and "D2 README.md" in said
    doc = projspec.view("garden")
    assert doc["exists"] and doc["hash"] == spec.digest(SPEC) and doc["chars"] == len(SPEC) and doc["max"] == 6000
    assert [e["label"] for e in doc["examples"]] == ["E1", "E2", "E3"] and doc["done_when"][1]["label"] == "D2"
    assert doc["commits"] and doc["tracked"] and doc["commit_words"].startswith("Save makes one commit")
    none = projspec.view("garden") if False else None
    assert none is None


def test_save_makes_one_commit_added_then_edited_and_expect_guards_it(project, conn):
    before = git(project, "rev-parse", "HEAD").decode().strip()
    code, said = _spec_cmd(conn, "garden", save=True, text=SPEC, expect=spec.digest(""))
    assert code == 0, said
    assert "sr: spec added" in git(project, "log", "-1", "--format=%s").decode()
    assert git(project, "show", "--stat", "--format=", "HEAD").decode().count("|") == 1  # SPEC.md alone
    assert (project / "SPEC.md").read_text() == SPEC and git(project, "status", "--porcelain").decode().strip() == ""
    code, said = _spec_cmd(conn, "garden", save=True, text=SPEC + "\nMore.\n", expect=spec.digest(SPEC))
    assert code == 0 and "sr: spec edited" in git(project, "log", "-1", "--format=%s").decode()
    code, said = _spec_cmd(conn, "garden", save=True, text="# other\n", expect=spec.digest(SPEC))
    assert code == 2 and "changed since you opened it" in said
    assert (project / "SPEC.md").read_text() == SPEC + "\nMore.\n"
    assert git(project, "rev-list", "--count", f"{before}..HEAD").decode().strip() == "2"


@pytest.mark.parametrize("text, words", [
    ("x" * 6001, "6,001 characters"),
    ("ok\nsecret-value-here\n", "line 2 holds a value from .env"),
    ("ok\n", "looks like it holds a key"),
    ("   \n", "the text is empty"),
])
def test_save_refuses_with_nothing_written_naming_the_line(project, conn, text, words):
    _commit_spec(project)
    head = git(project, "rev-parse", "HEAD").decode().strip()
    if "key" in words:
        text += _key() + "\n"
    lines = []
    code = cli.cmd_project(["spec", "garden"], conn=conn, notes=text, save=True, out=lines.append,
                           secrets=("secret-value-here",))
    said = "\n".join(lines)
    assert code == 2 and words in said and "secret-value-here" not in said
    assert (project / "SPEC.md").read_text() == SPEC and git(project, "rev-parse", "HEAD").decode().strip() == head


def test_without_git_the_file_is_written_and_nothing_committed(real_git, tmp_path, monkeypatch, conn):
    monkeypatch.setattr(projects, "REGISTRY_PATH", tmp_path / "config" / "projects.json")
    folder = tmp_path / "plain"
    folder.mkdir()
    (folder / "HANDOFF.md").write_text("# Plain\n")
    projects.add("plain", str(folder))
    code, said = _spec_cmd(conn, "plain", save=True, text=SPEC)
    assert code == 0 and "nothing committed" in said and (folder / "SPEC.md").read_text() == SPEC
    assert not (folder / ".git").exists()


def test_save_holds_the_projects_lock(project, conn, monkeypatch):
    from router import locks
    folder = cli.DB_PATH.parent / cli.runs.FOLDER_NAME
    with locks.held("project-garden", folder=folder, task_id="sr-other", wait=False):
        code, said = _spec_cmd(conn, "garden", save=True, text=SPEC)
    assert code == 2 and "another land, undo, discard or file change is running" in said
    assert not (project / "SPEC.md").exists()


def test_the_project_list_and_status_carry_the_specs_summary(project, conn):
    assert spec.summary(project) == {"present": False, "hash": None, "chars": 0, "examples": [], "done_when": []}
    _commit_spec(project)
    found = spec.summary(project)
    assert found == {"present": True, "hash": spec.digest(SPEC), "chars": len(SPEC), "examples": ["E1", "E2", "E3"],
                     "done_when": ["D1", "D2"]}
    entry = cli._projects_json(projects.read_registry(), {}, conn=conn)[0]
    assert entry["name"] == "garden" and entry["spec"] == found


# ---------- decision 5: the Draft chip and --no-files ----------

def test_the_draft_chip_shows_only_without_a_spec_and_fills_a_text_only_task(project, conn):
    doc = projspec.view("garden")
    assert doc["exists"] is False and doc["draft"] == {
        "kind": "draft_spec", "words": "Draft it", "later": False,
        "fill": {"team": "route", "project": "garden", "chat": None, "text": projspec.DRAFT_TEXT, "from": None, "idea": None,
                 "step": None, "no_files": True}}
    assert projspec.DRAFT_TEXT == ("Write SPEC.md for this project: what it is and why, what is not in it, then `## Examples` "
                                   "and `## Done when`, each a numbered list, one line per item.")
    _commit_spec(project)
    assert projspec.view("garden")["draft"] is None
    from router import page_commands
    status = {"projects": [{"name": "garden"}], "presets": [], "skills": [{"key": "code"}], "jev": {"available": True}}
    found = page_commands.build({"action": "send", "team": "route", "text": projspec.DRAFT_TEXT, "project": "garden",
                                 "no_files": True}, status)
    assert "--no-files" in found.args and found.args[-1] == projspec.DRAFT_TEXT
    with pytest.raises(page_commands.Refused):
        page_commands.build({"action": "send", "team": "redteam", "text": "x", "project": "garden", "no_files": True}, status)
    with pytest.raises(page_commands.Refused):
        page_commands.build({"action": "send", "team": "route", "text": "x", "chat": "c", "no_files": True}, status)
    saved = page_commands.build({"action": "project_spec_save", "name": "garden", "expect": "0123456789abcdef", "text": "# x\n"}, status)
    assert saved.args[:7] == ("project", "spec", "--json", "garden", "--save", "--expect", "0123456789abcdef") and saved.args[-1] == "# x\n"



def test_no_files_reads_a_read_only_copy_and_answers_in_text(project, conn, runner):
    """Brief 33.2 fix 1 (the owner's decision 1) changed this: `--no-files` was handoff only with no copy; it now reads a
    read-only copy, answers in text, and the copy goes at delivery (tests/test_nofiles_read332.py has the rest)."""
    worker, chat = CopyWorker(("an answer\n\n" + HANDOFF, {})), Chat("PASS")
    lines, clock, hook = [], Clock(), Webhook()
    code = cli.cmd_route("Write SPEC.md for this project", conn=conn, config=CONFIG, roster=ROSTER, environ={},
                         settings_paths=[], label=fake_label(CODE), post=hook.post, worker=worker, chatgpt=chat,
                         codex_login=lambda: True, fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock,
                         wait=True, out=lines.append, project="garden", files_ready=lambda: (True, None), no_files=True)
    said = "\n".join(lines)
    assert code == 0, said
    row = log.recent_tasks(conn)[0]
    found = log.project_files_of(row)
    assert (found["mode"], found["read_only"], found["copy"], found["why"], found["changed"]) == (
        "on", True, False, "read only, answers in text", [])
    assert not copies.exists(row["task_id"])
    assert worker.calls[0]["copy"].write is False and "Make the change by editing files there" not in worker.calls[0]["prompt"]
    assert filecalls.start_words("garden", {**found, "copy": True}).startswith("Files: a read-only copy of garden at")
    assert "### #" in (project / "HANDOFF.md").read_text()  # delivered as text: the entry is written at once


def test_no_files_is_refused_without_a_project_and_off_route(project, conn, runner):
    label = fake_label(CODE)
    lines, clock, hook = [], Clock(), Webhook()
    code = cli.cmd_route("x", conn=conn, config=CONFIG, roster=ROSTER, environ={}, settings_paths=[], label=label,
                         post=hook.post, worker=CopyWorker(), chatgpt=Chat("PASS"), codex_login=lambda: True,
                         fetch=hook.fetch, close=hook.close, sleep=clock.sleep, clock=clock, wait=True, out=lines.append,
                         files_ready=lambda: (True, None), no_files=True)
    assert code == 2 and label.calls == [] and "--no-files goes with --project" in "\n".join(lines)
    lines = []
    code = cli.main(["relay", "research-build", "--project", "garden", "--no-files", "--", "x"])
    assert code == 2
