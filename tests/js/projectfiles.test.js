// Build brief 28, C2 (decision 20): the page's pure parts for project files. The card's files line, tests line and
// buttons for each `files.state` (the router's record, `project_files`); the diff split for the side panel; the project
// view's tests line and Turn on undo; the three sheets' states (tests, Turn on undo, files dropped on a project); the New
// project hint and the dry run's git words; the Setup sheet's Git row; Needs you's "Ready to land"; the confirm the three
// buttons ask. Fixtures in the router's own shapes; every value invented.
import { test } from "node:test";
import assert from "node:assert/strict";
import { actionRunView, demoCommand, diffLineTone, diffPicker, diffSections, dropSheetView, fileView, fileWords,
  gitCheckView, gitSetupRow, needsConfirm, needsYou, needsYouList, newProjectGitWords, otherFolderHint, projectFilesLine,
  projectTestsLine, restoredActions, stateWords, testsLine, testsSheetView } from "../../static/app.js";

const ID = "sr-20261027-090000-ab12";
const CHANGED = [{ path: "calc.py", status: "changed", plus: 1, minus: 1 },
  { path: "test_calc.py", status: "added", plus: 8, minus: 0 }];
const record = (extra = {}) => ({ mode: "on", state: "none", copy: true, base: "a1b2c3d4e5f6", branch: "main", files: 2,
  left_out: [], changed: CHANGED, diff: `tasks/${ID}/changes.diff`, latest: "after-x",
  tests: { outcome: "passed", exit: 0, summary: "OK", output: `tasks/${ID}/tests-1.txt`, command: ["python3", "-m", "unittest"] },
  commit: null, undo_commit: null, why: null, ...extra });
const task = (files, extra = {}) => ({ task_id: ID, n: 12, status: "done", outcome: "passed", waiting_on: null,
  check_state: "passed", project: "garden", project_files: files, ...extra });

test("the tests line is the router's words", () => {
  assert.equal(testsLine(null), null);
  assert.equal(testsLine({ outcome: "passed", exit: 0 }), "tests passed");
  assert.equal(testsLine({ outcome: "failed", exit: 1 }), "tests failed (exit 1)");
  assert.equal(testsLine({ outcome: "failed", exit: null }), "tests failed");
  assert.equal(testsLine({ outcome: "timed_out", exit: null }), "tests timed out");
  assert.equal(testsLine({ outcome: "not_run", why: "the project has no test command" }), "no tests run: no test command");
  assert.equal(testsLine({ outcome: "not_run", why: "this Mac has no test sandbox (sandbox-exec)" }),
    "no tests run: this Mac has no test sandbox (sandbox-exec)");
});

test("a change waiting to land offers Land and Discard behind the confirm", () => {
  const view = fileView(task(record({ state: "waiting" }), { outcome: null, waiting_on: "land" }));
  assert.equal(view.kind, "waiting");
  assert.equal(view.line, "Files: 2 changed (+9 −1)");
  assert.deepEqual(view.files.map((f) => f.words), ["changed · +1 −1", "added · +8 −0"]);
  assert.equal(view.tests, "tests passed");
  assert.deepEqual(view.buttons.map((b) => [b.label, b.request.action, b.request.task_id]), [["Land", "land", ID], ["Discard", "discard", ID]]);
  assert.ok(view.buttons.every((b) => needsConfirm(b.request)));
  assert.equal(demoCommand(view.buttons[0].request), `sr land ${ID}`);
});

test("a landed change reads Landed with its short id and offers Undo", () => {
  const view = fileView(task(record({ state: "landed", commit: "0123456789abcdef", copy: false })));
  assert.equal(view.line, "Landed · 0123456 · Undo");
  assert.deepEqual(view.buttons.map((b) => b.request), [{ action: "undo", task_id: ID }]);
  assert.ok(needsConfirm(view.buttons[0].request));
});

test("undone, discarded, kept, empty and building each read their state", () => {
  assert.equal(fileView(task(record({ state: "undone", commit: "0123456789", undo_commit: "fedcba9876", copy: false }))).line,
    "Undone · fedcba9 put back 0123456");
  assert.deepEqual(fileView(task(record({ state: "undone", commit: "0123456789", undo_commit: "fedcba9876" }))).buttons, []);
  assert.equal(fileView(task(record({ state: "discarded", copy: false }))).kind, "discarded");
  const kept = fileView(task(record({ state: "none", copy: true }), { check_state: "failed", outcome: "failed_check" }));
  assert.equal(kept.kind, "kept");
  assert.match(kept.line, /can't land$/);
  assert.deepEqual(kept.buttons.map((b) => b.label), ["Discard"]);
  const empty = fileView(task(record({ state: "none", copy: false, changed: [] })));
  assert.equal(empty.line, "Files: no file changed · nothing to land");
  const building = fileView(task(record({ changed: [], tests: null }), { status: "sent", outcome: null }));
  assert.equal(building.kind, "building");
  assert.equal(building.line, "Files: a copy of garden at a1b2c3d");
  assert.deepEqual(building.buttons, []);
});

test("a handoff-only project task says why, and a task with no project has no block", () => {
  const off = fileView(task({ mode: "off", state: "none", copy: false, why: "no git yet: Turn on undo" }));
  assert.equal(off.line, "Files: handoff only (no git yet: Turn on undo)");  // brief 33.2: the router's words, in parentheses
  assert.equal(fileView(task({ mode: "off", state: "none", copy: false, why: "ChatGPT can't change project files: nothing to land" })).line,
    "Files: handoff only (ChatGPT can't change project files: nothing to land)");
  assert.equal(fileView(task(null)), null);
});

test("a binary file has no line counts", () => {
  const view = fileView(task(record({ state: "waiting", changed: [{ path: "logo.png", status: "added", plus: null, minus: null }] })));
  assert.equal(view.files[0].words, "added · binary");
  assert.equal(view.line, "Files: 1 changed (+0 −0)");
});

test("Needs you says Ready to land, and the state words say what it waits for", () => {
  const waiting = task(record({ state: "waiting" }), { outcome: null, waiting_on: "land" });
  assert.equal(needsYou(waiting), "Ready to land");
  assert.deepEqual(needsYouList([waiting]).you.map((x) => x.what), ["Ready to land"]);
  assert.equal(stateWords(waiting), "waiting for you to land or discard its change");
  assert.equal(needsYou(task(record({ state: "landed" }))), null);
});

test("the diff splits into one section per file, and its lines take a tone", () => {
  const text = ["diff --git a/calc.py b/calc.py", "index 1..2 100644", "--- a/calc.py", "+++ b/calc.py", "@@ -1,2 +1,2 @@",
    " def add(a, b):", "-    return a - b", "+    return a + b", "diff --git a/test_calc.py b/test_calc.py", "new file mode 100644",
    "--- /dev/null", "+++ b/test_calc.py", "@@ -0,0 +1 @@", "+import unittest", ""].join("\n");
  const found = diffSections(text);
  assert.deepEqual(found.map((s) => s.path), ["calc.py", "test_calc.py"]);
  assert.ok(found[0].text.endsWith("+    return a + b") && found[1].text.startsWith("diff --git a/test_calc.py"));
  assert.deepEqual(["+++ b/x", "--- a/x", "+y", "-z", "@@ -1 +1 @@", " same"].map(diffLineTone), ["meta", "meta", "add", "del", "hunk", ""]);
  assert.deepEqual(diffSections(""), []);
});

test("the project view's tests line and Turn on undo", () => {
  assert.deepEqual(projectTestsLine({ tests: null }), { text: "Tests: none", button: "Set", words: "" });
  assert.deepEqual(projectTestsLine({ tests: ["python3", "-m", "unittest"] }),
    { text: "Tests: python3 -m unittest", button: "Change", words: "python3 -m unittest" });
  assert.equal(projectTestsLine({ tests: ["pytest", "-k", "add and not slow"] }).words, "pytest -k 'add and not slow'");
  assert.deepEqual(projectFilesLine({ git: true, files_mode: "on", branch: "main", head: "a1b2c3d" }),
    { tone: "ok", text: "Files: on · main at a1b2c3d", turnOn: false });
  assert.equal(projectFilesLine({ git: false, files_mode: "off", why: "no git yet: Turn on undo" }).turnOn, true);
  assert.equal(projectFilesLine({ git: true, files_mode: "off", why: "no commit yet: Turn on undo" }).turnOn, true);
  assert.equal(projectFilesLine({ git: true, files_mode: "off", why: "Claude's file check hasn't passed on Claude Code 2.1.311" }).turnOn, false);
  assert.equal(projectFilesLine({ git: false, files_mode: "off", why: "this is the router's own folder" }).turnOn, false);
});

test("the tests sheet saves words, clears a command, and says the limit", () => {
  const set = testsSheetView({ name: "garden", tests: ["python3", "-m", "unittest"] }, "python3 -m unittest");
  assert.equal(set.canSave, true);
  assert.equal(set.canClear, true);
  assert.equal(testsSheetView({ name: "garden", tests: null }, "").canSave, false);
  assert.equal(testsSheetView({ name: "garden", tests: null }, "x").canClear, false);
  const long = testsSheetView({ name: "garden", tests: null }, "x".repeat(301));
  assert.equal(long.canSave, false);
  assert.match(long.hint, /301 characters; at most 300/);
  assert.equal(testsSheetView({ name: "garden", tests: null }, "x", { running: true }).canSave, false);
  assert.equal(testsSheetView({ name: "garden", tests: null }, "x", { demo: true }).foot, "Demo: nothing runs.");
});

test("the Turn on undo sheet from the dry run", () => {
  const ready = gitCheckView({ would: "turn_on", name: "plain-folder", files: 3, bytes: 2048,
    names: [".gitignore", "HANDOFF.md", "notes.txt"], more: 0, gitignore: { exists: false, adds: [".env", ".DS_Store"] } },
  { name: "plain-folder" });
  assert.equal(ready.canConfirm, true);
  assert.deepEqual(ready.names, [".gitignore", "HANDOFF.md", "notes.txt"]);
  assert.equal(ready.lines[0], "3 files (2 KB) go into the first commit.");  // humanSize's own words
  assert.equal(ready.lines[1], "Makes .gitignore: .env, .DS_Store.");
  const refused = gitCheckView({ would: "refused", name: "plain-folder",
    message: "Would refuse: config.txt line 2 looks like it holds a key. Nothing was changed." }, { name: "plain-folder" });
  assert.deepEqual([refused.canConfirm, refused.lines], [false, ["config.txt line 2 looks like it holds a key."]]);
  assert.equal(gitCheckView(null, { name: "plain-folder" }).title, "Checking…");
  assert.equal(gitCheckView({ would: "turn_on", name: "other" }, { name: "plain-folder" }).canConfirm, false);  // stale
  assert.equal(gitCheckView(null, { name: "plain-folder", waited: true }).title, "No answer");
});

test("files dropped on a project: the list, Add, the refusal and the commit", () => {
  const files = [{ name: "calc.py", size: 64 }, { name: "test_calc.py", size: 2048 }];
  const view = dropSheetView(files, { project: "garden" });
  assert.equal(view.title, "Add 2 files to garden");
  assert.equal(view.canAdd, true);
  assert.deepEqual(view.list.map((f) => f.name), ["calc.py", "test_calc.py"]);
  assert.equal(dropSheetView(files, { project: "garden", running: true }).canAdd, false);
  const refused = dropSheetView(files, { project: "garden", failure: "calc.py is already in the folder; a file is never overwritten" });
  assert.equal(refused.failure, "calc.py is already in the folder; a file is never overwritten");
  assert.equal(dropSheetView(files, { project: "garden", done: "Added: calc.py, test_calc.py" }).canAdd, false);
  assert.equal(dropSheetView([], { project: "garden" }).canAdd, false);
});

test("the New project hint and the dry run's git words", () => {
  assert.equal(otherFolderHint("~/Projects"), "To use a folder from somewhere else, move it into ~/Projects in Finder, then type its name here.");
  assert.match(newProjectGitWords({ would: "create", git: true }), /^git is set up/);
  assert.match(newProjectGitWords({ would: "create", git: false }), /file work needs git/);
  assert.equal(newProjectGitWords({ would: "register", git: false }), null);
});

test("the Setup sheet's Git row", () => {
  assert.deepEqual(gitSetupRow({ git: { installed: true, version: "2.50.1 (Apple Git-155)" } }),
    { key: "git", name: "Git", tone: "ok", state: "installed", detail: "2.50.1 (Apple Git-155)" });
  assert.equal(gitSetupRow({ git: { installed: false, version: null } }).state, "not installed");
  assert.equal(gitSetupRow({}).state, "unknown");
});

test("the demo's commands for the project actions", () => {
  assert.equal(demoCommand({ action: "project_tests", name: "garden", words: "python3 -m unittest" }),
    "sr project tests garden -- 'python3 -m unittest'");
  assert.equal(demoCommand({ action: "project_tests", name: "garden", clear: true }), "sr project tests --clear garden");
  assert.equal(demoCommand({ action: "project_git", name: "plain-folder" }), "sr project git plain-folder");
  assert.equal(demoCommand({ action: "project_files", name: "garden", files: ["/d/a b.csv"] }), "sr project files garden --file '/d/a b.csv'");
});

// ---------- C4 (`/break-ui`): what broke, as tests ----------

const many = (n) => [{ path: "src/components/approval/ApprovalFlow.integration.test.tsx", status: "changed", plus: 1284, minus: 977 },
  ...Array.from({ length: n - 1 }, (_, k) => ({ path: `src/loans/rules/rule_${String(k).padStart(3, "0")}.py`, status: "added", plus: 12, minus: 0 }))];

test("a change of 500 files shows the first 12 and how many more; the counts carry separators", () => {
  const view = fileView(task(record({ state: "waiting", changed: many(500) })));
  assert.equal(view.files.length, 12);
  assert.equal(view.more, 488);
  assert.equal(view.line, "Files: 500 changed (+7,272 −977)");
  assert.equal(view.buttons.map((b) => b.key).join(" "), "land discard");  // the buttons stay right under the list
  assert.equal(fileView(task(record({ state: "waiting", changed: many(12) }))).more, 0);
  assert.equal(fileWords({ status: "changed", plus: 1284, minus: 977 }), "changed · +1,284 −977");
  assert.equal(fileWords({ status: "added", plus: null, minus: null }), "added · binary");
});

test("the diff panel picks tabs for a few files and a list for many", () => {
  assert.equal(diffPicker(many(8)), "tabs");
  assert.equal(diffPicker(many(9)), "select");
  assert.equal(diffPicker(many(1)), null);  // one file needs no picker
});

test("a reload finds the page's runs still going on a task and shows them again", () => {
  const runs = [
    { id: "run-1", running: true, display: "sr land --json sr-20261027-090000-ab12", started: "2026-10-27T09:00:00Z",
      on: { action: "land", task_id: ID } },
    { id: "run-2", running: false, display: "sr undo --json x", on: { action: "undo", task_id: ID } },
    { id: "run-3", running: true, display: "sr route …", on: null },
    { id: "run-4", running: true, display: "sr discard --json y", started: "2026-10-27T09:01:00Z", on: { action: "discard", task_id: "sr-20261027-090100-cd34" } },
  ];
  const found = restoredActions(runs, []);
  assert.deepEqual(found.map((a) => [a.run_id, a.taskId]), [["run-1", ID], ["run-4", "sr-20261027-090100-cd34"]]);
  assert.equal(found[0].started, Date.parse("2026-10-27T09:00:00Z"));
  const kept = [{ run_id: "run-1", taskId: ID, display: "sr land", started: 5 }];
  assert.deepEqual(restoredActions(runs, kept).map((a) => a.run_id), ["run-1", "run-4"]);  // never twice
  assert.equal(restoredActions(runs, kept)[0], kept[0]);
});

test("a land that never ends says how long, and what happens if the page closes", () => {
  const started = Date.parse("2026-10-27T09:00:00Z");
  const action = { display: "sr land sr-20261027-090000-ab12", started };
  assert.deepEqual(actionRunView(action, started + 20_000), { text: "Running: sr land sr-20261027-090000-ab12", still: null });
  const later = actionRunView(action, started + 150_000);
  assert.equal(later.text, "Running for 2 min: sr land sr-20261027-090000-ab12");
  assert.equal(later.still, "It hasn't ended after 2 min. It keeps running if you close this page; the card shows what happened when it ends.");
  assert.equal(actionRunView({ display: "sr land x" }, started).still, null);  // no start time: no clock
});

test("every file a drop refused is named, not only the last", () => {
  const files = [{ name: "calc.py", size: 64 }];
  const view = dropSheetView(files, { project: "garden", refused: [{ name: ".env", why: "the file's name may not hold a folder or start with a dot" },
    { name: "loans.csv", why: "an older loans.csv is waiting in the drop folder from a drop that wasn't added" }] });
  assert.equal(view.refused.title, "2 files not added");
  assert.deepEqual(view.refused.lines, [".env: the file's name may not hold a folder or start with a dot",
    "loans.csv: an older loans.csv is waiting in the drop folder from a drop that wasn't added"]);
  assert.equal(view.canAdd, true);  // the rest can still go in
  assert.equal(dropSheetView(files, { project: "garden", refused: [{ name: "a", why: "b" }] }).refused.title, "1 file not added");
  assert.equal(dropSheetView(files, { project: "garden" }).refused, null);
});
