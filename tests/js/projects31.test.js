// Build brief 31: the page's pure parts for a project's Test, Run and Secrets. The router works every state out (status,
// `sr project test|run --status`, `sr project secrets`); these tests feed its JSON. Every value here is invented.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { OWN_FOLDER, hourMinute, projectOutputView, projectRunState, projectTestState, runConfirmWords, runEndWords,
  followsEnd, runSheetView, secretCommandLine, secretsSheetView, testOutcomeWords } from "../../static/app.js";

const at = (iso) => iso.slice(11, 16);  // a fixed clock for the tests: the ISO time's hour and minute
const PROJECT = { name: "seed-trays", git: true, head: "4fbe5d5", why: null, tests: ["python3", "-m", "unittest"], last_test: null };

test("Test is off, with the router's reason, whenever the router would refuse it (decision 2)", () => {
  assert.equal(projectTestState({ ...PROJECT, tests: null }, null, at).off, "Set a test command first");
  assert.equal(projectTestState({ ...PROJECT, why: OWN_FOLDER }, null, at).off,
    "The router's own folder: its suite is Claude Code's to run");
  assert.equal(projectTestState({ ...PROJECT, git: false, head: null, why: "no git yet: Turn on undo" }, null, at).off,
    "Test runs the committed files: no git yet: Turn on undo");
  assert.equal(projectTestState({ ...PROJECT, head: null, why: "no commit yet: Turn on undo" }, null, at).off,
    "Test runs the committed files: no commit yet: Turn on undo");
  assert.equal(projectTestState(PROJECT, { available: false }, at).off, "This Mac has no test sandbox (sandbox-exec)");
  assert.equal(projectTestState(PROJECT, { available: true }, at).off, null);
});

test("the project's Test line is the last result and its time", () => {
  const passed = { outcome: "passed", exit: 0, when: "2026-10-28T10:42:07+00:00" };
  assert.deepEqual(projectTestState({ ...PROJECT, last_test: passed }, null, at),
    { line: "Tests passed · 10:42", off: null, tone: "ok" });
  assert.equal(projectTestState({ ...PROJECT, last_test: { ...passed, outcome: "failed", exit: 1 } }, null, at).line,
    "Tests failed (exit 1) · 10:42");
  assert.equal(testOutcomeWords({ outcome: "timed_out", exit: null }), "Tests timed out");
  assert.equal(testOutcomeWords({ outcome: "failed", exit: null }), "Tests failed");
  assert.equal(projectTestState(PROJECT, null, at).line, null);
});

test("the side panel's Test output: running, the last one, or none yet", () => {
  const running = { project: { test_status: { running: true, started: "2026-10-28T10:42:00+00:00",
    head: "4fbe5d5a0c1e", output: "test_adds ... ok\n", last: null } } };
  assert.deepEqual(projectOutputView(running, "test", at), { title: "Test", sub: "Running since 10:42 · head 4fbe5d5",
    text: "test_adds ... ok\n", running: true, empty: "No output yet." });
  const done = { project: { test_status: { running: false, output: "Ran 1 test\n\nOK\n",
    last: { outcome: "passed", exit: 0, when: "2026-10-28T10:43:09+00:00", head: "4fbe5d5a0c1e" } } } };
  assert.equal(projectOutputView(done, "test", at).sub, "Tests passed · 10:43 · head 4fbe5d5");
  const none = projectOutputView({ project: { test_status: { running: false, output: "", last: null } } }, "test", at);
  assert.equal(none.sub, "No Test has run yet");
  assert.equal(none.text, "");
});

test("hourMinute reads an ISO time and gives nothing for a bad one", () => {
  assert.equal(hourMinute("not a time"), "");
  assert.match(hourMinute("2026-10-28T10:42:07+00:00"), /\d{1,2}:\d{2}/);
});

// ---------- R: the run command, Run and Stop (decisions 3 to 7) ----------

test("Run and Stop: each off with the reason, the run command's button, and the run's line", () => {
  const none = projectRunState({ ...PROJECT, run_command: null, run: null }, at);
  assert.deepEqual([none.button, none.runOff, none.stopOff, none.line], ["Set", "Set a run command first", "No run is going", null]);
  assert.equal(projectRunState({ ...PROJECT, why: OWN_FOLDER, run_command: ["python3", "app.py"] }, at).runOff,
    "The router never runs itself");
  const going = projectRunState({ ...PROJECT, run_command: ["python3", "app.py"],
    run: { state: "running", running: true, started: "2026-10-28T10:42:00+00:00" } }, at);
  assert.deepEqual([going.button, going.words, going.runOff, going.stopOff, going.line, going.tone],
    ["Change", "python3 app.py", "A run is going: Stop it first", null, "Running since 10:42", "info"]);
});

test("a run's end reads as the brief says: exited with its code, or stopped, with the time", () => {
  assert.equal(runEndWords({ state: "exited", running: false, exit: 0, ended: "2026-10-28T10:45:00+00:00" }, at), "Exited 0 at 10:45");
  assert.equal(runEndWords({ state: "stopped", running: false, ended: "2026-10-28T10:45:00+00:00" }, at), "Stopped at 10:45");
  assert.equal(runEndWords({ state: "exited", running: false, exit: null, ended: "2026-10-28T10:45:00+00:00" }, at),
    "Ended at 10:45 (it could not start)");
  assert.equal(runEndWords(null, at), null);
});

test("Run's confirm names the command, the folder and the .env names, each in its own block, never a value (decision 7)", () => {
  const doc = { project: { run_status: { command: ["python3", "app.py"], folder: "~/Library/Application Support/sr/projects/garden",
    env_names: ["DEMO_KEY"], output: "" } } };
  const words = runConfirmWords(doc);
  assert.equal(words.command, "python3 app.py");
  assert.deepEqual(words.facts, [{ label: "Command", text: "python3 app.py" },
    { label: "Folder", text: "~/Library/Application Support/sr/projects/garden" },
    { label: "From its .env: 1 name (the values are never shown)", text: "DEMO_KEY", box: true }]);
  const bare = runConfirmWords({ project: { run_status: { command: ["make"], env_names: [] } } });
  assert.equal(bare.facts.length, 2);
  assert.match(bare.after[0], /^The project has no \.env, so it gets no keys of its own\./);
  const forty = runConfirmWords({ project: { run_status: { command: ["make"], env_names: Array.from({ length: 40 }, (_, k) => `KEY_${k}`) } } });
  assert.equal(forty.facts[2].label, "From its .env: 40 names (the values are never shown)");
});

test("break-ui: Test is off while one runs, and a reader who scrolled up isn't pulled back to the end", () => {
  assert.equal(projectTestState({ ...PROJECT, test_running: true }, null, at).off, "A Test is running: its output is in the side panel");
  assert.equal(followsEnd(9200, 700, 9900), true);
  assert.equal(followsEnd(9196, 700, 9900), true);  // within 8 px of the end still follows
  assert.equal(followsEnd(4000, 700, 9900), false);
});

test("the run command sheet: Save only with words, at most 300 characters; Clear only when one is kept", () => {
  assert.equal(runSheetView({ name: "garden", run_command: null }, "").canSave, false);
  assert.equal(runSheetView({ name: "garden", run_command: null }, "python3 app.py").canSave, true);
  assert.equal(runSheetView({ name: "garden", run_command: null }, "x".repeat(301)).hint, "301 characters; at most 300.");
  assert.equal(runSheetView({ name: "garden", run_command: ["make"] }, "").canClear, true);
  assert.equal(runSheetView({ name: "garden", run_command: ["make"] }, "make", { demo: true }).canSave, false);
});

test("the side panel's Run output follows the run, and says how it ended", () => {
  const view = projectOutputView({ project: { run_status: { running: true, state: "running", started: "2026-10-28T10:42:00+00:00",
    output: "key length: 40\n[REDACTED]\ntick 0\n" } } }, "run", at);
  assert.deepEqual([view.title, view.sub, view.running], ["Run", "Running since 10:42", true]);
  assert.match(view.text, /\[REDACTED\]/);
  assert.equal(projectOutputView({ project: { run_status: { running: false, state: null, output: "" } } }, "run", at).sub, "No run yet");
});

// ---------- S: Secrets (decisions 8 and 9) ----------

test("the secret's command line names it, never its value, and says the value goes on stdin", () => {
  assert.deepEqual(secretCommandLine("seed-trays", "DEMO_KEY", 40),
    { command: "sr project secrets seed-trays --set DEMO_KEY", note: "(the value goes on stdin: 40 characters, never shown)" });
  assert.equal(secretCommandLine("seed-trays", "", 0).command, "sr project secrets seed-trays --set <NAME>");
});

test("the Secrets sheet: the names set or empty, Add or Change, a bad name named, Save only with a good name", () => {
  const doc = { project: { secrets: [{ name: "DEMO_KEY", set: true }, { name: "EMPTY", set: false }] } };
  const view = secretsSheetView(doc, { name: "seed-trays", key: "DEMO_KEY", length: 12 });
  assert.deepEqual(view.rows, [{ name: "DEMO_KEY", state: "set" }, { name: "EMPTY", state: "empty" }]);
  assert.equal(view.save, "Change");
  assert.equal(view.canSave, true);
  assert.equal(secretsSheetView(doc, { name: "seed-trays", key: "NEW_ONE" }).save, "Add");
  assert.match(secretsSheetView(doc, { name: "seed-trays", key: "bad-name" }).keyHint, /capital letters/);
  assert.equal(secretsSheetView(doc, { name: "seed-trays", key: "bad-name" }).canSave, false);
  assert.equal(secretsSheetView(doc, { name: "seed-trays", key: "DEMO_KEY", demo: true }).canSave, false);
  assert.equal(secretsSheetView(null, { name: "seed-trays" }).loading, true);
});

test("no page state ever holds a secret's value: Save reads the field once and clears it", () => {
  const source = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
  assert.doesNotMatch(source, /\bsc\.value\b/);  // the sheet's state keeps a length only
  const save = source.slice(source.indexOf("async function saveSecret()"), source.indexOf("async function removeSecret("));
  assert.match(save, /value: field\.value \};\s+field\.value = "";/);  // read once, then the field cleared
  assert.match(save, /request\.value = null;/);
});
