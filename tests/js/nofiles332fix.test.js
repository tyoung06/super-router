// Brief 33.2 fix 1 (the owner's decision 1, D4 option A): a `--no-files` task reads a read-only copy and answers in text.
// The card's files line reads "Files: read only (answers in text)" in place of "handoff only (text only, as asked)",
// while it runs and once delivered, with no tests line and no button; its fallback (no file mode, another doer) still
// reads "handoff only" with the router's reason. Every value here is fake.
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileView } from "../../static/app.js";

const RECORD = { mode: "on", state: "none", copy: true, read_only: true, why: "read only, answers in text", base: "abc1234def",
  branch: "main", changed: [], tests: { outcome: "not_run", why: "read only: no file can change" } };
const TASK = { task_id: "sr-d", n: 7, project: "garden", mode: "route", status: "sent", project_files: RECORD };

test("a read-only task's card reads 'read only (answers in text)' while it runs and once delivered", () => {
  const running = fileView(TASK);
  assert.equal(running.line, "Files: read only (answers in text)");
  assert.deepEqual(running.buttons, []);
  assert.equal(running.tests, null);
  const done = fileView({ ...TASK, status: "done", check_state: "passed", project_files: { ...RECORD, copy: false } });
  assert.equal(done.line, "Files: read only (answers in text)");
  assert.equal(done.kind, "read");
  assert.deepEqual(done.buttons, []);
});

test("the fallback still reads handoff only with the router's reason", () => {
  const off = { mode: "off", state: "none", copy: false, why: "text only, as asked; no read-only copy: no git yet: Turn on undo" };
  assert.equal(fileView({ ...TASK, project_files: off }).line,
    "Files: handoff only (text only, as asked; no read-only copy: no git yet: Turn on undo)");
});
