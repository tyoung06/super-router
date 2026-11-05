"""Cleanup 1, item 2.0: an Auto step that isn't Route, through `_main` itself (run #162 crashed there: `sr auto` loaded no
presets, so `cmd_relay` got `loaded=None`), and a crash inside a run: the run stops, its copy kept, and `--on` goes on.
Fakes only, on a throwaway git project; no model call. `cursor` is None here, so `attack2` is left out: the Cursor path
inside a run is the live check's."""
from router import __main__ as cli
from router import auto, copies, filecalls, log, plan, presets, projects, receipt, state
from tests.test_auto_run import STEP1, STEP2, _approved, _auto, _route_plan, _steps
from tests.test_filemode_flow import CODE, CopyWorker, conn, project, runner  # noqa: F401 (fixtures)


def _through_main(monkeypatch, tmp_path, db, worker, chatgpt, argv):
    """`cli._main` itself, with only the process boundaries faked: the log, the workers, the gates and the memory store.
    The roster and the presets are `_main`'s own."""
    monkeypatch.setattr(cli, "DB_PATH", db)
    monkeypatch.setattr(cli, "ENV_PATH", tmp_path / "no.env")
    monkeypatch.setattr(cli, "_workers", lambda *a, **kw: (worker, chatgpt, None))
    monkeypatch.setattr(cli, "_gate", lambda roster, config: None)
    monkeypatch.setattr(cli, "_claude_gate", lambda config, out: (lambda *a, **kw: None))
    monkeypatch.setattr(cli, "_files_gate", lambda out: (lambda: (True, None)))
    monkeypatch.setattr(cli, "_codex_gate", lambda config, out, model: (lambda *a, **kw: (True, None)))
    monkeypatch.setattr(cli.memory, "client", lambda request, **kw: None)
    monkeypatch.setattr(cli.safety, "prepare_workspace", lambda: None)
    monkeypatch.setattr(log, "ROUND_WRITER", log.ROUND_WRITER)
    monkeypatch.setattr(cli.runs, "FOLDER", cli.runs.FOLDER)
    out = receipt.Receipt()
    return cli._main(argv, "darwin", out), out


def _team_plan(conn):
    """The test plan with both steps redteam's (a route step would ask Jev), step 2's key need dropped."""
    row = _approved(conn)
    record, why = plan.edit(plan.record_of(row), 1, "team", "redteam")
    assert record is not None, why
    record["needs"] = [n for n in record.get("needs") or [] if n.get("kind") != "key"]
    log.set_plan(conn, row["task_id"], record)
    projects.set_tests("garden", ["python3", "-m", "unittest"])
    return log.get_task(conn, row["task_id"])


def test_a_team_step_through_main_reaches_its_row(project, conn, runner, monkeypatch, tmp_path):
    _team_plan(conn)
    db = tmp_path / "router.db"
    from tests.test_relay import Chat
    attack = "1. [high] 100 C isn't checked: no test covers it"
    code, out = _through_main(monkeypatch, tmp_path, db, CopyWorker(STEP1, STEP2, STEP2), Chat("PASS", attack, "PASS"),
                              ["auto", "garden", "--on"])
    assert "AttributeError" not in out.message, out.message
    run = next(r for r in log.recent_tasks(conn, 50) if r["mode"] == "auto")
    steps = _steps(conn, run)
    assert steps and steps[0]["mode"] == "relay" and steps[0]["preset"] == "redteam", out.message
    assert log.calls_for(conn, steps[0]["task_id"])[0]["role"] == "build"


def test_main_refuses_on_with_a_bad_presets_file_before_any_row(project, conn, runner, monkeypatch, tmp_path):
    _team_plan(conn)

    def bad(*a, **kw):
        raise presets.PresetsError(["the presets file is broken"])
    monkeypatch.setattr(presets, "load_presets", bad)
    code, out = _through_main(monkeypatch, tmp_path, tmp_path / "router.db", CopyWorker(), None, ["auto", "garden", "--on"])
    assert code == 2 and out.code == "bad_preset" and "Nothing was logged or sent." in out.message
    assert not [r for r in log.recent_tasks(conn, 50) if r["mode"] == "auto"]


def test_off_and_status_still_work_with_a_bad_presets_file(project, conn, runner, monkeypatch, tmp_path):
    """--off is the only Stop: a broken presets file must never take it away."""
    _team_plan(conn)

    def bad(*a, **kw):
        raise presets.PresetsError(["the presets file is broken"])
    monkeypatch.setattr(presets, "load_presets", bad)
    code, out = _through_main(monkeypatch, tmp_path, tmp_path / "router.db", CopyWorker(), None, ["auto", "garden", "--status"])
    assert code == 0 and out.code != "bad_preset", out.message
    code, out = _through_main(monkeypatch, tmp_path, tmp_path / "router.db", CopyWorker(), None, ["auto", "garden", "--off"])
    assert out.code != "bad_preset" and "no run is running" in out.message


# ---------- a crash inside a run (Fix 2) ----------

def _crash_once(monkeypatch, name, error, owner=cli):
    real = getattr(owner, name)
    calls = {"n": 0}

    def once(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise error
        return real(*a, **kw)
    monkeypatch.setattr(owner, name, once)
    return calls


SECRET_WORDS = "words a crash must never carry"


def test_a_crash_before_the_steps_row_stops_the_run_and_on_goes_on(project, conn, runner, monkeypatch):
    _route_plan(conn, _approved(conn))
    _crash_once(monkeypatch, "cmd_route", KeyError(SECRET_WORDS))
    code, out, run = _auto(conn)
    record = log.auto_of(run)
    assert code == 1 and auto.run_state(run, record) == "stopped"
    assert record["stop"]["code"] == "stopped" and "KeyError" in record["stop"]["why"]
    assert SECRET_WORDS not in out.message and SECRET_WORDS not in (run["check_note"] or "")
    assert record["steps"][0]["state"] == "stopped" and not record["steps"][0].get("task_id")
    assert copies.exists(run["task_id"])
    assert run["status"] == "returned"
    found = state.of(run, log.calls_for(conn, run["task_id"]))
    assert found.waiting_on == "auto"
    code, out, run = _auto(conn, worker=CopyWorker(STEP1, STEP2))
    record = log.auto_of(run)
    assert code == 0, out.message
    assert auto.run_state(run, record) == "finished" and record["steps"][0]["attempt"] == 1  # the crash used no attempt


def test_a_crash_inside_a_step_is_the_steps_own_failure_and_stops_the_run_as_before(project, conn, runner, monkeypatch):
    """The step's own loop catches what its calls raise: the row fails with the type's name, and the run reads that."""
    _route_plan(conn, _approved(conn))
    _crash_once(monkeypatch, "after_build", ValueError(SECRET_WORDS), owner=filecalls)
    code, out, run = _auto(conn)
    assert code == 4 and auto.run_state(run, log.auto_of(run)) == "stopped", out.message
    assert SECRET_WORDS not in out.message and "ValueError" in out.message


def test_a_crash_after_the_steps_row_closes_it_on_going_on(project, conn, runner, monkeypatch):
    """A crash outside the step's own loop, with its row made and open: the row is named on the record, `--on` closes it
    and starts the step again from its snapshot."""
    plan_row = _route_plan(conn, _approved(conn))
    real, made = cli.cmd_route, {}

    def row_then_crash(*a, **kw):
        if made:
            return real(*a, **kw)
        made["id"] = "sr-20261104-120000-cras"
        log.add_task(conn, made["id"], "step 1", "cli", CODE, mode="route", project="garden", parent=kw["auto_run"],
                     plan_step={"plan": plan_row["task_id"], "step": 1})
        (copies.folder_of(kw["auto_run"]) / "half.py").write_text("half a build\n")
        raise ValueError(SECRET_WORDS)
    monkeypatch.setattr(cli, "cmd_route", row_then_crash)
    code, out, run = _auto(conn)
    record = log.auto_of(run)
    assert code == 1 and auto.run_state(run, record) == "stopped", out.message
    assert "ValueError" in record["stop"]["why"] and SECRET_WORDS not in out.message
    assert record["steps"][0]["state"] == "stopped" and record["steps"][0]["task_id"] == made["id"]
    assert record["steps"][0]["attempt"] == 1
    code, out, run = _auto(conn, worker=CopyWorker(STEP1, STEP2))
    assert code == 0, out.message
    assert auto.run_state(run, log.auto_of(run)) == "finished"
    assert log.get_task(conn, made["id"])["status"] == "cancelled"
    assert not (copies.folder_of(run["task_id"]) / "half.py").exists()


def test_a_crash_on_a_retry_gives_back_only_that_attempt(project, conn, runner, monkeypatch):
    _route_plan(conn, _approved(conn))
    from tests.test_relay import Chat
    fails = "FIX\n1. [must] it is wrong"
    real = cli.cmd_route
    calls = {"n": 0}

    def second_crashes(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError(SECRET_WORDS)
        return real(*a, **kw)
    monkeypatch.setattr(cli, "cmd_route", second_crashes)
    code, out, run = _auto(conn, worker=CopyWorker(STEP1, STEP1), chatgpt=Chat(fails, fails))
    record = log.auto_of(run)
    assert code == 1 and record["stop"]["code"] == "stopped" and "OSError" in record["stop"]["why"], out.message
    entry = record["steps"][0]
    assert entry["state"] == "stopped" and entry["attempt"] == 1 and not entry.get("task_id")
    code, out, run = _auto(conn, worker=CopyWorker(STEP1, STEP2), chatgpt=Chat("PASS", "PASS"))
    record = log.auto_of(run)
    assert code == 0 and auto.run_state(run, record) == "finished" and record["steps"][0]["attempt"] == 2, out.message


def test_the_crash_exit_is_marked_and_names_the_run(project, conn, runner, monkeypatch):
    _route_plan(conn, _approved(conn))
    _crash_once(monkeypatch, "cmd_route", KeyError(SECRET_WORDS))
    code, out, run = _auto(conn)
    assert code == 1 and out.code == "internal_error" and out.task_id == run["task_id"]
    assert "unexpected error: KeyError" in out.message
