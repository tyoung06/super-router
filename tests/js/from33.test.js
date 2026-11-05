// Build brief 33, F (decisions 8 and 12): Build from this on the page. The card of a task built from an earlier result
// shows "Built from #<n>" outside Details, linked to that card; Details' "What the agents were given" shows the block as
// the first call sent it; Run again as… carries the card's --from (never on a split); a send clears the pills it carried.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { builtFrom, fromGiven, runAgainRequest, sendRequest } from "../../static/app.js";

const JS = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const STATUS = { presets: [{ name: "versus", slots: [{ name: "a", default: "claude" }, { name: "b", default: "chatgpt" }] }],
  skills: [{ key: "writing" }], jev: { available: true } };
const BUILT = { task_id: "sr-20261029-100000-bb01", n: 12, text: "Write a planting calendar.", project: null, chat: "tray",
  from: { task_id: "sr-20261029-090000-aa01", n: 7, chars: 84, cut: false } };

test("a card built from an earlier result says so, linked to that card; others say nothing", () => {
  assert.deepEqual(builtFrom(BUILT), { id: "sr-20261029-090000-aa01", text: "Built from #7" });
  assert.equal(builtFrom({ ...BUILT, from: null }), null);
  assert.match(JS, /builtFromLine\(task\),  \/\/ brief 33 \(decision 12\)/);
});

test("Details shows the block as the first call sent it, with its size and whether it was cut", () => {
  const given = fromGiven({ from_given: { task_id: "sr-x", n: 7, chars: 20094, cut: true, text: "===== EARLIER RESULT · #7 =====" } });
  assert.deepEqual(given, { head: "The earlier result #7 · 20,094 characters, cut", text: "===== EARLIER RESULT · #7 =====" });
  assert.equal(fromGiven({ from_given: null }), null);
  assert.equal(fromGiven(null), null);
});

test("Run again as… carries the card's --from, never on a split", () => {
  const ui = { chat: "tray", quick: false, newChat: "new-1" };
  assert.equal(runAgainRequest(BUILT, "route", ui, STATUS).request.from, "sr-20261029-090000-aa01");
  assert.equal(runAgainRequest(BUILT, "versus", ui, STATUS).request.from, "sr-20261029-090000-aa01");
  assert.equal(runAgainRequest(BUILT, "split", ui, STATUS).request.from, undefined);
  assert.equal(runAgainRequest({ ...BUILT, from: null }, "route", ui, STATUS).request.from, undefined);
});

test("a send clears the From and Idea pills it carried", () => {
  const after = JS.slice(JS.indexOf("async function send()"), JS.indexOf("async function send()") + 1600);
  assert.match(after, /Object\.assign\(state, \{ from: null, idea: null, step: null, models: null, fillPlaceholder: null \}\)/);  // 33.1
  const request = sendRequest({ team: "route", text: "x", from: { task_id: "sr-a", n: 3 }, chat: "tray", files: [], slots: {} }, STATUS);
  assert.equal(request.from, "sr-a");
});
