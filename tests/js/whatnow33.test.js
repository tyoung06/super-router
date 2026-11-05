// Build brief 33, W (decision 13): What now? on the page. The router computes the line (`what_now` on
// `sr log --json --project <name>`, read on every poll); the page shows it under the project's title with its one control,
// outside the bar that folds into Project tools at a narrow width, so it stays in view.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { whatNowParts } from "../../static/app.js";

const JS = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const CSS = readFileSync(new URL("../../static/app.css", import.meta.url), "utf8");
const CHIP = { kind: "agent", words: "Add a --round option.", later: true,
  fill: { team: "route", project: "demo", chat: null, text: "Add a --round option.", from: null, idea: null } };

test("a Next line is the chip itself, after its lead", () => {
  const parts = whatNowParts({ rung: 4, words: "Next: Add a --round option.", control: "chip", task_id: "sr-a", n: 3, chip: CHIP });
  assert.deepEqual(parts, { lead: "Next:", chip: CHIP, open: null, ideas: false, taskId: "sr-a",  // I adds `ideas`
    secrets: null, tests: null, chips: [], said: null });  // brief 33.1: the plan's controls, none here
});

test("a line that names a card has Open; a running one has no control", () => {
  assert.equal(whatNowParts({ rung: 1, words: "Waiting on you: #3 · a change ready to land", control: "open", task_id: "sr-a", n: 3,
    chip: null }).open, "sr-a");
  const running = whatNowParts({ rung: 2, words: "#3 is running · Claude", control: null, task_id: "sr-a", n: 3, chip: null });
  assert.equal(running.open, null);
  assert.equal(running.chip, null);
  assert.equal(running.lead, "#3 is running · Claude");
});

test("no line, no row", () => {
  assert.equal(whatNowParts(null), null);
  assert.equal(whatNowParts({ words: "" }), null);
});

test("it sits in the head outside the project bar, and the poll reads it on every round", () => {
  assert.match(JS, /whatNowLine\(state\.project\),  \/\/ brief 33 \(decision 13\): under the title, never folded with the bar\n\s+projectBar\(state\.project\)\);/);
  assert.match(JS, /if \(state\.project\) await loadWhatNow\(\);/);
  const rule = CSS.slice(CSS.indexOf("\n.what-now {"), CSS.indexOf("}", CSS.indexOf("\n.what-now {")));
  assert.match(rule, /flex-basis: 100%/);
  assert.match(rule, /flex-wrap: wrap/);
});
