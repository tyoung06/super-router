// Build brief 33.4, S (decision 13): the Suggest ideas button's states, "Suggested by #n", the sheet's line and the toast; no
// card in the stream. Hidden when Claude is unavailable and in the demo; off at the limit, from 48 open. Every value is fake.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { chipCardId, ideasSheetView, suggestToast, suggestView } from "../../static/app.js";

const JS = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const DOC = { ideas: [], suggest: { running: null, open: 1, off: null, last: null } };

test("hidden in the demo and when Claude is unavailable", () => {
  assert.equal(suggestView(DOC, { demo: true }).hidden, true);
  assert.equal(suggestView(DOC, { claude: false }).hidden, true);
});

test("idle: on, and it reads Suggest ideas", () => {
  const view = suggestView(DOC);
  assert.deepEqual([view.hidden, view.off, view.label, view.line], [false, false, "Suggest ideas", null]);
});

test("off until the list is read", () => {
  assert.equal(suggestView(null).off, true);
});

test("running: off and Suggesting…, from this page or from the router", () => {
  for (const view of [suggestView(DOC, { starting: true }), suggestView({ suggest: { running: { n: 9 } } })]) {
    assert.deepEqual([view.off, view.label, view.running], [true, "Suggesting…", true]);
  }
});

test("off at the limit with its one line", () => {
  const view = suggestView({ suggest: { off: "48 open ideas: dismiss some to get suggestions" } });
  assert.equal(view.off, true);
  assert.equal(view.line, "48 open ideas: dismiss some to get suggestions");
  assert.equal(view.label, "Suggest ideas");
});

test("done: the line says what happened; a failure names its task", () => {
  assert.equal(suggestView({ suggest: { last: { n: 9, status: "done", line: "2 added, 1 dropped: too long" } } }).line, "2 added, 1 dropped: too long");
  assert.equal(suggestView({ suggest: { last: { n: 9, status: "failed", line: "no idea in the shape" } } }).line, "#9: no idea in the shape");
});

test("the toast counts what was added", () => {
  assert.equal(suggestToast({ added: 3, exit: 0 }), "3 ideas added");
  assert.equal(suggestToast({ added: 1, exit: 0 }), "1 idea added");
  assert.equal(suggestToast({ added: 0, exit: 1, summary: "no idea in the shape" }), "no idea in the shape");
  assert.equal(suggestToast({ message: "Refused: x" }), "Refused: x");
});

test("rows read Suggested by #n, linked to the task; a Later row stays as it was", () => {
  const view = ideasSheetView({ ideas: [
    { id: 1, text: "a", state: "open", source: { kind: "later", n: 9, task_id: "sr-9", suggested: true } },
    { id: 2, text: "b", state: "open", source: { kind: "later", n: 8, task_id: "sr-8", suggested: false } }] }, { name: "seed" });
  assert.deepEqual(view.rows[0].source, { words: "Suggested by #9", taskId: "sr-9" });
  assert.deepEqual(view.rows[1].source, { words: "Later on #8", taskId: "sr-8" });
});

test("the sheet's command line shows the suggest command while it runs", () => {
  assert.equal(ideasSheetView({ ideas: [] }, { name: "seed", suggesting: true }).line, "sr ideas seed --suggest");
  assert.ok(ideasSheetView({ ideas: [] }, { name: "seed" }).line.startsWith("sr ideas seed --add"));
});

test("no card in the stream, and never the chip card; History keeps it", () => {
  const body = JS.slice(JS.indexOf("function streamTasks()"), JS.indexOf("function mdInline(nodes)"));
  assert.ok(body.includes('t.mode === "suggest"'));
  assert.ok(body.indexOf('state.view === "history"') < body.indexOf('t.mode === "suggest"'));
  const tasks = [{ task_id: "a", n: 1, next: [{ kind: "agent" }] }, { task_id: "s", n: 2, mode: "suggest", next: [] }];
  assert.equal(chipCardId("project", tasks), "a");
});
