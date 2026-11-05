// Build brief 33.1 (decisions 1, 6, 9 to 12, 16, 17 and 20): the plan on the page. Plan is in the team list after Split
// (⌥8, /plan), greyed off a project with the reason; Send · Plan sends `sr plan` with the project and From. The plan card
// shows each step with its team, why, done-when and calls, the needs (each key set or not, the proposed test command with
// Set), the total calls, and Approve, Reject or Approve anyway; each edit is one `sr plan --edit`. A Build step chip fills
// the step's team, the project and the Step pill; the One step card offers Build it; What now? names a need with Secrets
// or Set, a step with its chip, and the finish line with its chips; the bar reads "Plan #n · d of m". Every value fake.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  chipViews, composerGreys, contextFor, demoCommand, fileView, fillFromChip, jevBox, needsYou, oneStepView, parseComposer,
  PLAN_OFF_PROJECT, planBarWords, planCardView, planCountLine, planEditRequest, placeholderFor, sendRequest, shortcutFor,
  stepPillWords, testsConfirmWords, whatNowParts,
} from "../../static/app.js";

const JS = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const HTML = readFileSync(new URL("../../static/index.html", import.meta.url), "utf8");
const PLAN = { ready: true, why: null, description: "Claude plans the project from its files", project: true,
  chain: "Claude plan → ChatGPT attack → Cursor attack → Claude revise → ChatGPT check", calls: 5, max_calls: 7 };
const PRESETS = ["research-build", "collab", "versus", "redteam", "vote"].map((name) => ({ name, ready: true, project: true,
  slots: [], description: name, chain: name }));
const STATUS = { presets: PRESETS, split: { ready: true, description: "split", chain: "Claude plan → …" }, plan: PLAN,
  projects: [{ name: "garden" }] };
const STEP_CHIP = { kind: "build_step", words: "Build step 2: Add the conversion.", later: false,
  fill: { team: "redteam", project: "garden", chat: null, text: "Add the conversion.", from: null, idea: null,
    step: { plan: "sr-20261029-100000-aa01", n: 12, k: 2 } } };

// ---------- the team (decision 1) ----------

test("Plan is the last team, on ⌥8, greyed off a project with the reason", () => {
  const off = chipViews(STATUS, "route").at(-1);
  assert.deepEqual([off.key, off.label, off.shortcut, off.disabled, off.reason], ["plan", "Plan", "⌥8", true, PLAN_OFF_PROJECT]);
  const on = chipViews(STATUS, "plan", { project: "garden" }).at(-1);
  assert.deepEqual([on.disabled, on.checked, on.title], [false, true, `${PLAN.description} · ${PLAN.chain}`]);
  const down = chipViews({ ...STATUS, plan: { ...PLAN, ready: false, why: "Claude is signed out" } }, "route", { project: "garden" }).at(-1);
  assert.deepEqual([down.disabled, down.reason], [true, "Claude is signed out"]);
  assert.deepEqual(shortcutFor({ altKey: true, code: "Digit8" }), { action: "chip", index: 7 });
  assert.deepEqual(parseComposer("/plan the first version", []).slash, { kind: "plan", value: null });
});

test("Send · Plan sends the project, the text, From and the idea, nothing else", () => {
  const state = { team: "plan", text: "Plan the first version.", project: "garden", chat: "tray", quick: false,
    from: { task_id: "sr-a", n: 3 }, idea: { id: 4 }, step: { plan: "sr-b", n: 1, k: 1 }, files: [], slots: {}, web: true };
  assert.deepEqual(sendRequest(state, STATUS), { action: "send", team: "plan", text: "Plan the first version.", project: "garden",
    from: "sr-a", idea: 4 });  // brief 33.2 (decision 12): the Idea pill rides on a plan (Add to plan)
  assert.deepEqual(contextFor({ ...state, project: null }, STATUS).flag, null);
  assert.match(placeholderFor("plan", STATUS), /Plan the first version/);
  assert.equal(jevBox({ team: "plan" }).mode, "not_asked");
  assert.deepEqual(Object.values(composerGreys("plan")).every(Boolean), true);
});

test("Send stays off for Plan without a project, saying why", () => {
  assert.match(JS, /const planOff = state\.team === "plan" && !ctx\.value \? PLAN_OFF_PROJECT : null;/);
});

// ---------- the Step pill (decision 12) ----------

test("a Build step chip fills the step's team, the project and the Step pill", () => {
  const { next } = fillFromChip(STEP_CHIP, { text: "", team: "route" }, 12);
  assert.deepEqual([next.team, next.project, next.text, next.step], ["redteam", "garden", "Add the conversion.",
    { plan: "sr-20261029-100000-aa01", n: 12, k: 2 }]);
  assert.equal(stepPillWords(next.step), "Step 2 of plan #12");
  const request = sendRequest({ ...next, files: [], slots: {}, chat: null, quick: false }, STATUS);
  assert.equal(request.step, "sr-20261029-100000-aa01:2");
  assert.equal(sendRequest({ ...next, project: null, files: [], slots: {}, chat: "tray", quick: false }, STATUS).step, undefined);
  assert.match(HTML, /id="step-pill"/);
  assert.match(JS, /from: null, idea: null, step: null, models: null, noFiles: false, placeholder: null \}\);  \/\/ 33\.1: the Step pill; 33\.3: the model pills; 33\.2: Text only/);
});

// ---------- the plan card (decisions 9 to 11) ----------

const WAITING = { task_id: "sr-p", n: 12, mode: "plan", project: "garden", waiting_on: "land", land_anyway: false,
  plan: { steps: [
    { k: 1, text: "Make the skeleton.", team: "route", why: "smallest", done_when: "test_cli.py passes", calls: 2, max_calls: 4, jev_label: true },
    { k: 2, text: "Add the conversion.", team: "redteam", why: "core", done_when: "test_convert.py passes", calls: 5, max_calls: 7 }],
  needs: [{ kind: "key", name: "WEATHER_KEY", what: "today's temperature", step: 2, set: false },
    { kind: "test_command", name: null, what: "python3 -m unittest", step: null, set: false },
    { kind: "decision", name: null, what: "Celsius or Fahrenheit?", step: 2, set: null }],
  estimate: { calls: 7, max_calls: 11, jev_labels: 1 }, edits: [] } };

test("the plan card shows each step with its team, why, done-when and calls, the needs and the total", () => {
  const view = planCardView(WAITING, null);
  assert.equal(view.title, "A plan is waiting");
  assert.equal(view.sub, "2 steps · nothing runs until you approve");
  assert.deepEqual(view.steps.map((s) => [s.k, s.team, s.why, s.doneWhen, s.calls]), [[1, "route", "smallest", "test_cli.py passes", "2 to 4 calls"],
    [2, "redteam", "core", "test_convert.py passes", "5 to 7 calls"]]);
  assert.deepEqual(view.needs.map((n) => [n.kind, n.state]), [["key", "not set"], ["test_command", "not set"], ["decision", null]]);
  assert.equal(view.count, "7 to 11 calls for all the steps · Jev: 1 label");
  assert.equal(planCountLine({ calls: 4, max_calls: 4, jev_labels: 0 }), "4 calls for all the steps");
  assert.deepEqual(view.approve, { action: "land", task_id: "sr-p" });
  assert.deepEqual(view.reject, { action: "discard", task_id: "sr-p" });
  assert.equal(view.approveAnyway, null);
});

test("each edit is one sr plan --edit: text, done-when, team, up, down and drop", () => {
  const view = planCardView(WAITING, null);
  assert.equal(view.steps[0].up, null);  // the first step can't move up
  assert.deepEqual(view.steps[0].down, { action: "plan_edit", task_id: "sr-p", step: 1, change: "down" });
  assert.deepEqual(planEditRequest(WAITING, 2, "team", "route"), { action: "plan_edit", task_id: "sr-p", step: 2, change: "team",
    value: "route" });
  assert.equal(demoCommand(planEditRequest(WAITING, 2, "text", "New words")), "sr plan --edit sr-p --step 2 --text -- 'New words'");
  assert.equal(demoCommand(planEditRequest(WAITING, 1, "drop")), "sr plan --edit sr-p --step 1 --drop");
  const editing = planCardView(WAITING, null, { editing: { taskId: "sr-p", k: 1, field: "done_when", text: "x".repeat(300) } });
  assert.equal(editing.steps[0].edit.tooLong, true);
  assert.equal(editing.off, "Save or cancel step 1's edit first");
});

test("after a failed check the card offers Approve anyway and Reject; the files block leaves them to it", () => {
  const anyway = { ...WAITING, waiting_on: null, land_anyway: true };
  const view = planCardView(anyway, null);
  assert.equal(view.title, "A plan whose check didn't pass");
  assert.deepEqual([view.approve, view.approveAnyway], [null, { action: "land", task_id: "sr-p", anyway: true }]);
  const files = fileView({ ...WAITING, project_files: { mode: "on", state: "waiting", changed: [{ path: "docs/PLAN.md", status: "added" }] } });
  assert.deepEqual([files.kind, files.buttons], ["plan", []]);
  assert.equal(needsYou(WAITING), "Approve a plan");
});

// ---------- One step, What now? and the bar (decisions 6, 16, 17 and 20) ----------

test("the One step card names the task and its team, with Build it", () => {
  const buildIt = { kind: "build_it", words: "Build it", later: false,
    fill: { team: "route", project: "garden", chat: null, text: "Add a docstring.", from: null, idea: null, step: null } };
  const task = { task_id: "sr-o", mode: "plan", result: "one step: one small change", one_step: { task: "Add a docstring.",
    team: "route", why: "one small change" }, next: [buildIt] };
  const view = oneStepView(task);
  assert.deepEqual([view.title, view.line, view.task, view.chip], ["One step", "one small change", "Add a docstring.", buildIt]);
  assert.equal(oneStepView({ ...task, one_step: null }), null);
});

test("What now? names a need with Secrets or Set, a step with its chip, and the finish line with its chips", () => {
  const key = whatNowParts({ rung: "plan_need", words: "Before step 2: set WEATHER_KEY", control: "secrets", task_id: "sr-p",
    n: 12, chip: STEP_CHIP, need: { kind: "key", name: "WEATHER_KEY" }, chips: null, plan_md: null });
  assert.deepEqual([key.lead, key.secrets, key.chip], ["Before step 2: set WEATHER_KEY", "WEATHER_KEY", STEP_CHIP]);
  const tests = whatNowParts({ rung: "plan_need", words: "Before step 1: set the test command", control: "tests", task_id: "sr-p",
    n: 12, chip: null, need: { kind: "test_command", proposed: "python3 -m unittest" }, chips: null, plan_md: null });
  assert.equal(tests.tests, "python3 -m unittest");
  assert.equal(testsConfirmWords("garden", "python3 -m unittest"),
    "Set garden's test command to `python3 -m unittest`? The router runs it after each build, in its sandbox.");
  const step = whatNowParts({ rung: "plan_step", words: STEP_CHIP.words, control: "chip", task_id: "sr-p", n: 12, chip: STEP_CHIP,
    need: null, chips: null, plan_md: { state: "left_out", why: "docs/PLAN.md has uncommitted edits in the folder" } });
  assert.deepEqual([step.chip, step.said], [STEP_CHIP, "docs/PLAN.md has uncommitted edits in the folder"]);
  const finish = whatNowParts({ rung: "finish", words: "All 2 steps done", control: "chips", task_id: "sr-p", n: 12, chip: null,
    need: null, chips: [{ kind: "readme" }, { kind: "what_next" }], plan_md: null });
  assert.deepEqual([finish.lead, finish.chips.length], ["All 2 steps done", 2]);
  assert.equal(planBarWords({ plan: { n: 12, done: 1, total: 4 } }), "Plan #12 · 1 of 4");
  assert.equal(planBarWords({ plan: null }), null);
  assert.match(JS, /`\/api\/plan\/\$\{encodeURIComponent\(name\)\}`/);
});

// ---------- break-ui (brief 33.1) ----------

test("a long key's Secrets label keeps the name's start and end; the full name is the button's title", async () => {
  const { secretsLabel, SECRET_LABEL_MAX } = await import("../../static/app.js");
  const name = "NORTHWIND_INDUSTRIES_HOLDINGS_QUARTERLY_REPORTING_SERVICE_ACCOUNT_CREDENTIALS_JSON";
  const label = secretsLabel(name);
  assert.equal(label.length, "Secrets · ".length + SECRET_LABEL_MAX);
  assert.equal(label, "Secrets · NORTHWIND_IND…TIALS_JSON");
  assert.equal(secretsLabel("FROST_FEED_KEY"), "Secrets · FROST_FEED_KEY");
  assert.match(JS, /title: `Open Secrets for \$\{task\.project\}, at \$\{need\.name\}`/);
});

test("a One step answer reads as one, never a red Stopped, and its line isn't shown twice", async () => {
  const { resultShown, verdictLine } = await import("../../static/app.js");
  const task = { task_id: "sr-o", mode: "plan", status: "failed", outcome: "stopped", result: "one step: one small change",
    one_step: { task: "Add a docstring.", team: "route", why: "one small change" }, check_state: "pending" };
  assert.equal(resultShown(task), false);
  assert.deepEqual(verdictLine(task, null), { tone: "muted", text: "One step · build it instead" });
});

// ---------- D2 (the live check's step 2, 30 Oct): Save on a plan step's edit ----------

test("a plan step's edit repaints its counter and Save as the text changes, and Save reads the text as it is now", () => {
  // the owner typed into step 2's edit and Save stayed off: the button's state was worked out once, when the box
  // opened ("unchanged"), and neither typing nor Save looked again
  const field = JS.slice(JS.indexOf("function planEditField("), JS.indexOf("function openPlanEdit("));
  assert.match(field, /oninput: \(e\) => \{[\s\S]*?paintPlanEdit\(task, step\.k\);\s*\},/);
  assert.match(field, /id: `plan-edit-save-\$\{task\.task_id\}-\$\{step\.k\}`/);
  assert.match(field, /id: `plan-edit-count-\$\{task\.task_id\}-\$\{step\.k\}`/);
  assert.doesNotMatch(field.slice(field.indexOf("const save"), field.indexOf("const cancel")), /step\.edit\.unchanged/);
  assert.match(field.slice(field.indexOf("const save"), field.indexOf("const cancel")), /edit\.text === before/);
  const paint = JS.slice(JS.indexOf("function paintPlanEdit("), JS.indexOf("function openPlanEdit("));
  assert.match(paint, /planCardView\(/);
  assert.match(paint, /save\.disabled = /);
});

// ---------- D6 (the live check's step 5, 30 Oct): the bar's plan count after an Undo ----------

test("a land, undo or discard that ends well reads the status again at once, so the bar's plan count is current", async () => {
  // the owner undid step 1 and the bar still read "Plan #156 · 1 of 5" until a reload: a card action's end read the log
  // again but not the status, which the bar's count comes from (the server had already dropped its kept status)
  const { STATUS_AFTER, refreshesStatus } = await import("../../static/app.js");
  assert.deepEqual(STATUS_AFTER, ["land", "undo", "discard"]);
  assert.equal(refreshesStatus({ action: "undo" }, 0), true);
  assert.equal(refreshesStatus({ action: "land" }, 0), true);
  assert.equal(refreshesStatus({ action: "undo" }, 2), false);  // refused: nothing changed
  assert.equal(refreshesStatus({ action: "plan_edit" }, 0), false);
  assert.equal(refreshesStatus({}, 0), false);
  const run = JS.slice(JS.indexOf("async function runAction("), JS.indexOf("async function runAction(") + 1200);
  assert.match(run, /state\.actions\.push\(\{ run_id: started\.run_id, taskId: task\.task_id, action: request\.action,/);
  const runs = JS.slice(JS.indexOf("async function loadRuns("), JS.indexOf("async function poll("));
  assert.match(runs, /if \(refreshesStatus\(item, code\)\) statusDue = true;/);
  assert.match(runs, /if \(statusDue\) await loadStatus\(\);/);
});

// ---------- E1 (the hand-back, 30 Oct): a refused plan edit opens again (rules 2.47, The plan on the page) ----------

test("a refused edit of a step's text or finish line opens again with what was typed and the router's refusal", () => {
  // 2.47: "a refused edit opening again with what was typed and the router's refusal", as the split's plan card does
  const field = JS.slice(JS.indexOf("function planEditField("), JS.indexOf("function paintPlanEdit("));
  const save = field.slice(field.indexOf("const save"), field.indexOf("const cancel"));
  assert.match(save, /state\.planEditSaved = \{ \.\.\.edit \};/);
  assert.match(field, /oninput: \(e\) => \{\s*state\.planEdit = \{ \.\.\.state\.planEdit, text: e\.target\.value, refused: null \};/);
  assert.match(field, /role: "alert", id: `plan-edit-refused-\$\{task\.task_id\}-\$\{step\.k\}`, text: edit\.refused/);
  assert.match(field, /if \(edit\.focus\) \{ state\.planEdit\.focus = false; box\.focus\(\); \}/);
  const runs = JS.slice(JS.indexOf("async function loadRuns("), JS.indexOf("async function poll("));
  assert.match(runs, /const planSaved = state\.planEditSaved && state\.planEditSaved\.taskId === item\.taskId/);
  assert.match(runs, /if \(planSaved && !state\.planEdit\) \{/);
  assert.match(runs, /state\.planEdit = \{ \.\.\.planSaved, refused: view\.message, focus: onPlan \};/);
});
