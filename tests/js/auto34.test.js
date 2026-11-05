// Build brief 34, C (decisions 10 to 13): the page's Auto. The router works every state out (a project's `auto`, a task's
// `auto`, `what_now`'s Auto lines, the dry run's numbers, the plan's steps and marks); these tests feed its JSON to the
// page's pure parts. Every value here is invented.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  autoBoard, autoConfirmView, autoSwitchView, fileView, needsConfirm, needsYou, needsYouList, rescueOffers, stopHereRows,
  taskSummary, verdictLine, whatNowParts,
} from "../../static/app.js";

const JS = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const CSS = readFileSync(new URL("../../static/app.css", import.meta.url), "utf8");

const RUN_ID = "sr-20261030-090000-a001";
const RUN = { task_id: RUN_ID, n: 41, state: "running", words: "Auto · step 2 of 4 · 3 of 14 calls", stop: null, used: 3, budget: 14, next: 2 };
const PROJECT = (auto) => ({ name: "seed-trays", git: true, plan: { task_id: "sr-p", n: 12, done: 1, total: 4 }, auto });

// ---------- the switch (decision 10) ----------

test("the switch is off when --on would be accepted, on while a run runs, and hidden otherwise, never greyed", () => {
  const off = autoSwitchView(PROJECT({ state: "off", run: null, switch: "off", why: null }));
  assert.deepEqual([off.on, off.to, off.label, off.busy], [false, "on", "Off", false]);
  const on = autoSwitchView(PROJECT({ state: "on", run: RUN, switch: "on", why: null }));
  assert.deepEqual([on.on, on.to, on.label, on.busy], [true, "off", "On", false]);
  assert.equal(autoSwitchView(PROJECT({ state: "finished", run: { ...RUN, state: "finished" }, switch: "hidden", why: "run #41 is finished and waits to land" })), null);
  assert.equal(autoSwitchView(PROJECT({ state: "off", run: null, switch: "hidden", why: "no current plan" })), null);
  assert.equal(autoSwitchView({ name: "x" }), null);
  assert.equal(autoSwitchView(null), null);
  assert.doesNotMatch(JS.slice(JS.indexOf("function autoSwitch("), JS.indexOf("function autoSwitch(") + 900), /disabled: true|class: "[^"]*greyed/);
});

test("a stopped run shows the switch off once --on would be accepted, and hidden while the cause stays", () => {
  const stopped = { ...RUN, state: "stopped", words: "Auto stopped: stop here before step 2", stop: { code: "stop_here", why: "stop here before step 2", step: 2 } };
  const view = autoSwitchView(PROJECT({ state: "stopped", run: stopped, switch: "off", why: null }));
  assert.deepEqual([view.on, view.to], [false, "on"]);
  assert.equal(autoSwitchView(PROJECT({ state: "stopped", run: stopped, switch: "hidden", why: "Before step 2: set WEATHER_KEY" })), null);
});

test("the page's own run in flight shows the switch busy with its direction, and the title names the command", () => {
  const starting = autoSwitchView(PROJECT({ state: "off", run: null, switch: "off", why: null }), { to: "on", started: 1 });
  assert.deepEqual([starting.on, starting.busy, starting.label, starting.disabled], [true, true, "Starting…", true]);
  assert.match(starting.title, /sr auto seed-trays --on/);
  const stopping = autoSwitchView(PROJECT({ state: "on", run: RUN, switch: "on", why: null }), { to: "off", started: 1 });
  assert.deepEqual([stopping.on, stopping.busy, stopping.label], [false, true, "Stopping…"]);
  assert.match(stopping.title, /sr auto seed-trays --off/);
  // decision 10: a run in flight keeps the switch drawn even where status would hide it (the status read comes later)
  assert.ok(autoSwitchView(PROJECT({ state: "off", run: null, switch: "hidden", why: "x" }), { to: "on", started: 1 }).busy);
});

// ---------- the confirm from the dry run (decision 10) ----------

const DRY = { api_version: 1, task_id: null, n: null, status: null, waiting_on: null, outcome: null, reason_code: null, exit: 0,
  message: "Auto runs step 2 of plan #12, 14 calls at most, then stops before step 3 (stop here).",
  auto: { plan: { task_id: "sr-p", n: 12 }, from_step: 2, to_step: 4, steps: [2, 3, 4], budget: 14, used: 0,
    estimate: { calls: 9, max_calls: 9, jev_labels: 2 }, first_stop_here: 3,
    overrun: "A step already started finishes, so the run can pass its budget by up to one step's calls.",
    words: "Auto runs step 2 of plan #12, 14 calls at most, then stops before step 3 (stop here)." } };

test("the confirm's numbers are the router's: the steps, the budget, the first stop-here and the overrun, never worked out here", () => {
  const view = autoConfirmView(DRY, "seed-trays");
  assert.equal(view.words, DRY.auto.words);
  assert.equal(view.overrun, DRY.auto.overrun);
  assert.deepEqual([view.steps, view.budget, view.firstStop], [[2, 3, 4], 14, 3]);
  assert.equal(view.refused, null);
  assert.deepEqual(view.request, { action: "auto_on", name: "seed-trays" });
  assert.equal(view.line, "sr auto seed-trays --on");
  // the words are shown as the router gave them: no digit in the view comes from the page
  const body = JS.slice(JS.indexOf("export function autoConfirmView"), JS.indexOf("export function autoConfirmView") + 1500);
  assert.doesNotMatch(body, /Math\.ceil|\* 1\.5|budget \* |\.length \*/);
});

test("a refused dry run is the confirm's refusal, with nothing to confirm", () => {
  const view = autoConfirmView({ exit: 2, reason_code: "auto_refused", message: "Refused: Auto can't start on seed-trays: no current plan." }, "seed-trays");
  assert.equal(view.refused, "Refused: Auto can't start on seed-trays: no current plan.");
  assert.equal(view.words, null);
  assert.equal(autoConfirmView(null, "seed-trays").refused, "The dry run didn't answer.");
});

test("the switch's off needs no confirm; Land run and Discard run do (the page's confirm), stop-here doesn't", () => {
  assert.equal(needsConfirm({ action: "auto_off", name: "seed-trays" }), false);
  assert.equal(needsConfirm({ action: "auto_on", name: "seed-trays" }), false);  // its own confirm, from the dry run
  assert.equal(needsConfirm({ action: "land", task_id: RUN_ID }), true);
  assert.equal(needsConfirm({ action: "discard", task_id: RUN_ID }), true);
  assert.equal(needsConfirm({ action: "plan_stop_here", step: "sr-p:2", to: "on" }), false);
});

// ---------- What now?'s Auto lines (decision 11) ----------

test("Auto's lines: running has no control, stopped has Open or the need's control, finished has Open", () => {
  const running = whatNowParts({ rung: "auto_running", words: "Auto · step 2 of 4 · 3 of 14 calls", control: null, task_id: RUN_ID, n: 41, chip: null, need: null, chips: null, plan_md: null });
  assert.deepEqual([running.lead, running.open, running.chip, running.secrets, running.tests], ["Auto · step 2 of 4 · 3 of 14 calls", null, null, null, null]);
  const stopped = whatNowParts({ rung: "auto_stopped", words: "Auto stopped: step 2 (#43) failed its check twice, on its retry too", control: "open", task_id: RUN_ID, n: 41, chip: null, need: null, chips: null, plan_md: null });
  assert.deepEqual([stopped.lead, stopped.open], ["Auto stopped: step 2 (#43) failed its check twice, on its retry too", RUN_ID]);
  const need = whatNowParts({ rung: "auto_stopped", words: "Auto stopped: Before step 3: set WEATHER_KEY", control: "secrets", task_id: RUN_ID, n: 41, chip: null,
    need: { kind: "key", name: "WEATHER_KEY", words: "Before step 3: set WEATHER_KEY" }, chips: null, plan_md: null });
  assert.deepEqual([need.lead, need.secrets, need.open], ["Auto stopped: Before step 3: set WEATHER_KEY", "WEATHER_KEY", null]);
  const finished = whatNowParts({ rung: "auto_finished", words: "Auto finished: land the run?", control: "open", task_id: RUN_ID, n: 41, chip: null, need: null, chips: null, plan_md: null });
  assert.deepEqual([finished.lead, finished.open], ["Auto finished: land the run?", RUN_ID]);
});

// ---------- the run's card is the recap (decision 12) ----------

const STEPS = [
  { k: 1, state: "done", attempt: 1, team: "route", task_id: "sr-s1", n: 42, status: "done", outcome: "passed", waiting_on: null, verdict: "passed", calls: 2, covered: true },
  { k: 2, state: "failed", attempt: 2, team: "redteam", task_id: "sr-s2b", n: 44, status: "done", outcome: "failed_check", waiting_on: null, verdict: "failed", calls: 9, covered: true },
  { k: 3, state: "open", attempt: 0, team: "route", task_id: null, n: null, status: null, outcome: null, waiting_on: null, verdict: null, calls: 0, covered: true },
  { k: 4, state: "open", attempt: 0, team: "collab", task_id: null, n: null, status: null, outcome: null, waiting_on: null, verdict: null, calls: 0, covered: true },
];
const STOPPED = { task_id: RUN_ID, n: 41, mode: "auto", project: "seed-trays", status: "returned", waiting_on: "auto", outcome: null, text: "Auto: plan #12, steps 1 to 4",
  project_files: { mode: "on", state: "none", copy: true, base: "4f2a9c1e", branch: "main", changed: [{ path: "trial.py", status: "changed", plus: 6, minus: 0 }], diff: null, tests: null, commit: null },
  auto: { plan: { task_id: "sr-p", n: 12 }, from_step: 1, state: "stopped", steps: STEPS, budget: 14, used: 11, estimate: { calls: 9, max_calls: 9 },
    stop: { code: "failed", why: "step 2 (#44) failed its check twice, on its retry too", step: 2 }, passed_marks: [], copy: true, next: 2,
    words: "Auto stopped: step 2 (#44) failed its check twice, on its retry too" } };

test("the recap lists each step with its state, task, calls and verdict, the calls against the budget, what is open, why it stopped, and the marks", () => {
  const board = autoBoard(STOPPED, null, [3]);
  assert.equal(board.words, STOPPED.auto.words);
  assert.deepEqual(board.steps.map((s) => [s.k, s.state, s.taskId, s.n, s.calls, s.verdict, s.mark]), [
    [1, "passed", "sr-s1", 42, 2, "passed", false], [2, "failed twice", "sr-s2b", 44, 9, "failed", false],
    [3, "open", null, null, 0, null, true], [4, "open", null, null, 0, null, false]]);
  assert.equal(board.steps[1].attempt, "2 attempts");
  assert.equal(board.calls, "11 of 14 calls");
  assert.deepEqual(board.open, [2, 3, 4]);
  assert.equal(board.why, "step 2 (#44) failed its check twice, on its retry too");
  assert.deepEqual(board.marks, [3]);
  assert.deepEqual(board.buttons.map((b) => [b.key, b.label, b.request]), [
    ["land", "Land the run so far", { action: "land", task_id: RUN_ID }], ["discard", "Discard run", { action: "discard", task_id: RUN_ID }]]);
  assert.equal(autoBoard({ ...STOPPED, auto: null }, null), null);
});

test("a finished run offers Land run and Discard run; a landed one Undo; a running or discarded one nothing", () => {
  const finished = { ...STOPPED, status: "done", waiting_on: "land", project_files: { ...STOPPED.project_files, state: "waiting" },
    auto: { ...STOPPED.auto, state: "finished", stop: null, used: 13, steps: STEPS.map((s) => ({ ...s, state: "done" })), words: "Auto finished: land the run?" } };
  assert.deepEqual(autoBoard(finished, null).buttons.map((b) => b.label), ["Land run", "Discard run"]);
  assert.deepEqual(autoBoard(finished, null).open, []);
  const landed = { ...finished, waiting_on: null, outcome: "passed", project_files: { ...finished.project_files, state: "landed", commit: "abc1234def" }, auto: { ...finished.auto, state: "landed", words: "Auto landed" } };
  assert.deepEqual(autoBoard(landed, null).buttons.map((b) => b.label), ["Undo"]);
  const running = { ...STOPPED, status: "queued", waiting_on: null, auto: { ...STOPPED.auto, state: "running", stop: null, words: RUN.words } };
  assert.deepEqual(autoBoard(running, null).buttons, []);
  assert.equal(autoBoard(running, null).why, null);
  const discarded = { ...STOPPED, project_files: { ...STOPPED.project_files, state: "discarded", copy: false }, auto: { ...STOPPED.auto, state: "discarded" } };
  assert.deepEqual(autoBoard(discarded, null).buttons, []);
});

test("a run has no chips: the card draws the recap's buttons and nothing else from Next", () => {
  const body = JS.slice(JS.indexOf("function autoBoardEl("), JS.indexOf("function autoBoardEl(") + 2500);
  assert.doesNotMatch(body, /nextRow\(|next-chip/);
});

test("the files block on a run names the run's whole change; its buttons are the recap's, never drawn twice", () => {
  const stopped = fileView(STOPPED);
  assert.equal(stopped.kind, "kept");
  assert.match(stopped.line, /1 changed \(\+6 −0\) · the run stopped/);
  assert.deepEqual(stopped.buttons, []);
  assert.match(stopped.note, /Land the run so far \(on the recap\)/);
  const finished = fileView({ ...STOPPED, status: "done", waiting_on: "land", project_files: { ...STOPPED.project_files, state: "waiting" }, auto: { ...STOPPED.auto, state: "finished", stop: null } });
  assert.equal(finished.kind, "waiting");
  assert.deepEqual(finished.buttons, []);
  assert.match(finished.note, /the whole run, one commit on main/);
  const running = fileView({ ...STOPPED, status: "queued", waiting_on: null, auto: { ...STOPPED.auto, state: "running", stop: null } });
  assert.equal(running.kind, "building");
  assert.match(running.line, /the run builds in it/);
  const step = fileView({ task_id: "sr-s1", n: 42, mode: "route", project: "seed-trays", status: "done", outcome: "passed",
    project_files: { mode: "on", state: "none", copy: true, owner: RUN_ID, run: RUN_ID, start: "step-1-1-start", changed: [{ path: "trial.py", status: "added", plus: 3, minus: 0 }] } });
  assert.equal(step.kind, "piece");
  assert.match(step.line, /this step's part; its run lands the whole change once/);
  assert.deepEqual(step.buttons, []);
});

test("the summary names a run Auto and a step by its run; the verdict line carries the run's words", () => {
  assert.equal(taskSummary(STOPPED).team, "Auto");
  const step = { task_id: "sr-s1", n: 42, mode: "route", parent: RUN_ID, piece_of: { split: null, run: RUN_ID, n: 41, piece: null, step: 1, team: "route" },
    plan_step: { plan: "sr-p", n: 12, step: 1 }, status: "done", outcome: "passed" };
  assert.deepEqual([taskSummary(step).team, taskSummary(step).pieceOf], ["Route", "step 1 of run #41"]);
  assert.deepEqual(verdictLine(STOPPED, null), { tone: "warn", text: "Auto stopped: step 2 (#44) failed its check twice, on its retry too" });
  const running = { ...STOPPED, status: "queued", waiting_on: null, auto: { ...STOPPED.auto, state: "running", stop: null, words: RUN.words } };
  assert.deepEqual(verdictLine(running, null), { tone: "info", text: RUN.words });
  const finished = { ...STOPPED, status: "done", waiting_on: "land", auto: { ...STOPPED.auto, state: "finished", words: "Auto finished: land the run?" } };
  assert.deepEqual(verdictLine(finished, null), { tone: "warn", text: "Auto finished: land the run?" });
  const landed = { ...finished, waiting_on: null, outcome: "passed", project_files: { ...STOPPED.project_files, state: "landed" }, auto: { ...finished.auto, state: "landed", words: "Auto landed" } };
  assert.deepEqual(verdictLine(landed, null), { tone: "ok", text: "Auto landed · 4 steps" });
});

// ---------- Stop here in the plan's panel (decision 13) ----------

test("the panel lists the current plan's steps with a Stop here toggle each, from the project's plan entry", () => {
  const plan = { task_id: "sr-p", n: 12, done: 1, total: 3, file: "docs/PLAN.md", stop_here: [3],
    steps: [{ k: 1, text: "Make the skeleton.", team: "route", done: true, stop_here: false },
      { k: 2, text: "Add the conversion.", team: "redteam", done: false, stop_here: false },
      { k: 3, text: "Write the README.", team: "route", done: false, stop_here: true }] };
  const rows = stopHereRows(plan, new Set(["sr-p:2"]));
  assert.deepEqual(rows.map((r) => [r.k, r.done, r.on, r.busy, r.to, r.step]), [
    [1, true, false, false, "on", "sr-p:1"], [2, false, false, true, "on", "sr-p:2"], [3, false, true, false, "off", "sr-p:3"]]);
  assert.equal(rows[1].text, "Add the conversion.");
  assert.equal(rows[1].team, "Redteam");
  assert.deepEqual(rows[2].request, { action: "plan_stop_here", step: "sr-p:3", to: "off" });
  assert.deepEqual(stopHereRows(null), []);
  assert.deepEqual(stopHereRows({ task_id: "sr-p", n: 1 }), []);  // an older status without the steps
});

test("a Stop here toggle is a 44 px switch, never greyed, and the panel draws them above docs/PLAN.md", () => {
  assert.match(CSS, /\.stop-here-row\s*\{[^}]*min-height:\s*44px/);
  assert.match(CSS, /\.auto-switch-wrap\s*\{[^}]*margin-left:\s*auto/);
  const body = JS.slice(JS.indexOf("function stopHereList("), JS.indexOf("function stopHereList(") + 1800);
  assert.match(body, /role: "switch"/);
  assert.doesNotMatch(body, /disabled: true/);
  const panel = JS.slice(JS.indexOf("function renderDocPanel("), JS.indexOf("function renderDocPanel(") + 2600);
  assert.ok(panel.indexOf("stopHereList(") < panel.indexOf('class: "panel-body"'));
});

// ---------- Needs you (decision 13) ----------

test("Needs you lists a stopped run as Auto stopped and a finished one as Land the run?", () => {
  assert.equal(needsYou(STOPPED), "Auto stopped");
  const finished = { ...STOPPED, status: "done", waiting_on: "land", auto: { ...STOPPED.auto, state: "finished" } };
  assert.equal(needsYou(finished), "Land the run?");
  const step = { task_id: "sr-s2b", n: 44, mode: "route", parent: RUN_ID, status: "done", outcome: "failed_check", waiting_on: null, fallback: { ok: false } };
  assert.equal(needsYou(step), null);  // the run's stop speaks for its step
  const list = needsYouList([STOPPED, finished, step]);
  assert.deepEqual(list.you.map((e) => [e.n, e.what]), [[41, "Auto stopped"], [41, "Land the run?"]]);
});

// ---------- the always-visible controls: only the switch is new (decision 13) ----------

test("no always-visible control is new but the switch: the composer's ids are 33.3's, and the head adds only #auto-switch", () => {
  const INDEX = readFileSync(new URL("../../static/index.html", import.meta.url), "utf8");
  const bar = INDEX.slice(INDEX.indexOf('class="composer-bar"'), INDEX.indexOf("</footer>"));
  const ids = [...bar.matchAll(/id="([a-z-]+)"/g)].map((m) => m[1]);
  assert.deepEqual(ids, ["attach", "skill", "web-label", "web", "quick-label", "quick", "project", "team", "context-tag", "send", "file-input", "cmdline", "cmd", "copy", "jev"]);
  const head = JS.slice(JS.indexOf("function whatNowLine("), JS.indexOf("async function loadWhatNow("));
  const headIds = [...new Set([...head.matchAll(/id: "([a-z-]+)"/g)].map((m) => m[1]))];  // the row is drawn by one of two paths
  assert.deepEqual(headIds, ["what-now", "auto-switch"]);
  const bar2 = JS.slice(JS.indexOf("function projectBar("), JS.indexOf("function dropZone("));
  const barIds = [...bar2.matchAll(/id: "([a-z-]+)"/g)].map((m) => m[1]);
  assert.deepEqual(barIds, ["project-file-input", "project-bar", "project-plan", "turn-on-undo", "tests-set", "project-secrets", "project-ideas", "project-notes"]);
});

test("the switch is the only Stop: a run's card and a step's card offer no Cancel", () => {
  const running = { ...STOPPED, status: "queued", waiting_on: null, outcome: null, auto: { ...STOPPED.auto, state: "running", stop: null } };
  assert.deepEqual(rescueOffers(running).map((o) => o.key), []);
  const step = { task_id: "sr-s3", n: 45, mode: "route", status: "sent", waiting_on: null, outcome: null, parent: RUN_ID,
    piece_of: { split: null, run: RUN_ID, n: 41, piece: null, step: 3, team: "route" }, fallback: null, resume: null };
  assert.deepEqual(rescueOffers(step).map((o) => o.key), []);
  const plain = { task_id: "sr-x", n: 46, mode: "route", status: "sent", waiting_on: null, outcome: null, fallback: null, resume: null };
  assert.ok(rescueOffers(plain).some((o) => o.key === "cancel"));
});
