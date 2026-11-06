// The memory brief, step 2 (rules 2.56, Memory "Down"): a call whose store was down still sent its newest tasks from
// the log; Details' memory line says so. An old record (no `sent`) keeps today's words.
import { test } from "node:test";
import assert from "node:assert/strict";
import { memoryCallLines } from "../../static/app.js";

test("a store-down call that sent the newest says they went from the log", () => {
  const lines = memoryCallLines([
    { kind: "do", agent: "claude", memory: { state: "unavailable", sent: 2, found: 2, from: null } },
    { kind: "check", agent: "chatgpt", memory: { state: "unavailable", sent: 2, found: 2, from: "sr-x" } }]);
  assert.deepEqual(lines.map((l) => `${l.who}: ${l.what}`), [
    "build · Claude: the store was down; the newest 2 went from the log",
    "check · ChatGPT: the store was down; the newest 2 went from the log, the block from sr-x"]);
});

test("an old unavailable record, or one that sent none, keeps today's words", () => {
  const lines = memoryCallLines([
    { kind: "do", agent: "claude", memory: { state: "unavailable", sent: null, found: null, from: null } },
    { kind: "do", agent: "claude", memory: { state: "unavailable", sent: 0, found: 0, from: null } },
    { kind: "do", agent: "claude", memory: { state: "unavailable", from: null } }]);
  assert.deepEqual(lines.map((l) => l.what), Array(3).fill("the store was unavailable; the call ran without it"));
});

// The memory brief, step 3 (fixes 1 and 2): the Memory row says a bad setting or a memory_url off this Mac, from
// status's `memory.problem`, never the value itself.
import { memoryView } from "../../static/app.js";

test("a bad memory setting reads off and says why", () => {
  const view = memoryView({ setting: "off", online: false, installed: true,
    problem: "the memory setting isn't auto or off, so memory is off" });
  assert.equal(view.state, "off");
  assert.equal(view.detail, "the memory setting isn't auto or off, so memory is off");
  assert.equal(view.problem, true);
  assert.equal(view.off, true);
});

test("a memory_url off this Mac reads offline and says why", () => {
  const view = memoryView({ setting: "auto", online: false, installed: true, problem: "memory_url isn't on this Mac" });
  assert.deepEqual([view.state, view.detail, view.problem], ["offline", "memory_url isn't on this Mac", true]);
});

test("no problem keeps today's rows", () => {
  assert.equal(memoryView({ setting: "off", problem: null }).detail, "you turned it off · tasks run without it and nothing is saved");
  assert.equal(memoryView({ setting: "auto", online: false, installed: true }).state, "ready");
});
