// Build brief 27, C (decisions 11–13; the owner's choice 7): the Memory switch's pure parts. The light's five states and
// which of them is a setup problem (only not installed), the details link, the first-run card, the switch and its note
// (the page's own run to on reads starting), the chat header, the receipt, the per-call lines and the drawer's saves.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { chatMemoryWords, firstRunItems, memoryCallLines, memoryDrawer, memoryLink, memorySwitchView, memoryView,
  receiptView, setupRows } from "../../static/app.js";

const STATUS = JSON.parse(readFileSync(new URL("../../demo/status.json", import.meta.url), "utf8"));
const ON = { setting: "auto", online: true, starting: false, documents: 16, installed: true };
const OFF = { setting: "off", online: false, starting: false, documents: null, installed: true };
const READY = { setting: "auto", online: false, starting: false, documents: null, installed: true };
const STARTING = { setting: "auto", online: false, starting: true, documents: null, installed: true };
const MISSING = { setting: "auto", online: false, starting: false, documents: null, installed: false };

test("the light's five states, and only not installed is a setup problem", () => {
  const view = (m) => { const v = memoryView(m); return [v.tone, v.state, v.detail, v.problem, v.off]; };
  assert.deepEqual(view(OFF), ["muted", "off", "you turned it off · tasks run without it and nothing is saved", false, true]);
  assert.deepEqual(view(STARTING), ["info", "starting", "about 35 s · nothing to do", false, false]);
  assert.deepEqual(view(ON), ["ok", "online", "16 documents · starts itself", false, false]);
  assert.deepEqual(view(READY), ["ok", "ready", "starts itself when a chat or project task needs it", false, false]);
  assert.deepEqual(view(MISSING), ["muted", "not installed", "chat and project tasks run without it until it's installed", true, false]);
  assert.deepEqual(view(null).slice(0, 2), ["muted", "unknown"]);
  assert.equal(memoryView(null).problem, false);
});

test("while the page's own run to on is in flight the light reads starting from that run", () => {
  for (const m of [OFF, READY, MISSING]) {
    const v = memoryView(m, { turningOn: true });
    assert.deepEqual([v.tone, v.state, v.detail, v.problem], ["info", "starting", "about 35 s · nothing to do", false]);
  }
  assert.equal(memoryView(ON, { turningOn: false }).state, "online");  // a run to off leaves the light as it is
});

test("the details link: off turns it on in Setup, not installed sets it up, the rest link nothing", () => {
  assert.equal(memoryLink(memoryView(OFF)), "Turn it on in Setup");
  assert.equal(memoryLink(memoryView(MISSING)), "How to set it up");
  for (const m of [ON, READY, STARTING, null]) assert.equal(memoryLink(memoryView(m)), null);
});

test("the first-run card and the Setup row take memory only when it isn't installed", () => {
  const green = structuredClone(STATUS);
  for (const a of green.agents) Object.assign(a, { configured: true, live: true, online: true, reason: null, probe: { state: "passed" },
    available: true, why: null, why_code: null });
  green.jev = { ...green.jev, configured: true, available: true, why: null };
  for (const [m, listed] of [[ON, false], [OFF, false], [READY, false], [STARTING, false], [MISSING, true], [null, false]]) {
    green.memory = m;
    assert.deepEqual(firstRunItems(green).map((i) => i.key), listed ? ["memory"] : [], JSON.stringify(m));
    const row = setupRows(green).find((r) => r.key === "memory");
    assert.equal(row.problem, listed);
  }
  green.memory = MISSING;
  assert.equal(firstRunItems(green)[0].reason, "chat and project tasks run without it until it's installed");
});

test("the switch: On and Off, the command it runs, and Starting… or Turning off… while its run goes", () => {
  const on = memorySwitchView(ON, null);
  assert.deepEqual([on.on, on.label, on.to, on.busy, on.disabled, on.cmdLabel], [true, "On", "off", false, false, "The switch runs"]);
  assert.match(on.words, /^On\. The router remembers what each chat and project task delivers/);
  const off = memorySwitchView(OFF, null);
  assert.deepEqual([off.on, off.label, off.to, off.disabled], [false, "Off", "on", false]);
  assert.match(off.words, /^Off\. Tasks run without memory, and nothing they deliver is saved, not even after you turn it back on\./);
  const starting = memorySwitchView(OFF, { to: "on" });
  assert.deepEqual([starting.on, starting.label, starting.to, starting.busy, starting.disabled, starting.cmdLabel],
    [true, "Starting…", "on", true, true, "Running"]);
  assert.match(starting.words, /^Starting the store: about 35 seconds\./);
  const stopping = memorySwitchView(ON, { to: "off" });
  assert.deepEqual([stopping.on, stopping.label, stopping.to, stopping.busy, stopping.disabled, stopping.cmdLabel],
    [false, "Turning off…", "off", true, true, "Running"]);
  assert.equal(memorySwitchView(null, null).disabled, true);  // no status yet: nothing to switch from
});

test("a failed run shows the router's words and its exit on the row", () => {
  const view = memorySwitchView(OFF, null, { exit: 2, message: "Refused: config/settings.local.json is not a JSON object. Nothing was changed." });
  assert.deepEqual(view.failure, { exit: 2, message: "Refused: config/settings.local.json is not a JSON object. Nothing was changed." });
  assert.equal(memorySwitchView(OFF, null).failure, null);
});

test("a chat's header says memory is off while it is", () => {
  assert.equal(chatMemoryWords(OFF), "memory off");
  for (const m of [ON, READY, STARTING, MISSING, null]) assert.equal(chatMemoryWords(m), "memory on for this chat");
});

test("the receipt reads memory: off when the build call's record says off", () => {
  const task = { task_id: "sr-x", tag: "chat:tray", chat: "tray", jev: { label: "writing", confidence: 0.9 } };
  const show = { memory_given: [], calls: [{ kind: "do", agent: "claude", memory: { state: "off", from: null } },
    { kind: "check", agent: "chatgpt", memory: { state: "off", from: "sr-x" } }] };
  assert.ok(receiptView(task, show).some((p) => p.text === "memory: " && p.value === "off"));
  show.calls[0].memory = { state: "sent", sent: 0, found: 0, from: null };
  assert.ok(receiptView(task, show).some((p) => p.text === "memory: " && p.value === "none yet"));
});

test("a call made while memory was off says so", () => {
  const lines = memoryCallLines([{ kind: "do", agent: "claude", memory: { state: "off", from: null } },
    { kind: "check", agent: "chatgpt", memory: { state: "off", from: "sr-x" } }]);
  assert.deepEqual(lines.map((l) => `${l.who}: ${l.what}`), ["build · Claude: memory was off; the call ran without it",
    "check · ChatGPT: memory was off; the call ran without it, the block from sr-x"]);
});

test("a skipped save says why, never undefined", () => {
  const task = { tag: "chat:tray", chat: "tray" };
  const show = { memory_given: [], calls: [], memory_stored: [
    { skipped: "off", state: "done/passed/2", at: "t" },
    { skipped: "looks like a key", state: "done/passed/3", at: "t" },
    { skipped: "unavailable (ConnectionError (POST /v1/default/banks/x/memories))", state: "done/fixed/4", at: "t" },
    { document_id: "task-sr-x", chars: 139, state: "done/passed/2", at: "t" }] };
  const stored = memoryDrawer(task, show).stored;
  assert.deepEqual(stored, ["not saved: memory was off · done/passed/2", "not saved: it looked like a key · done/passed/3",
    "not saved: the store was unavailable · done/fixed/4", "task-sr-x · 139 characters · done/passed/2"]);
  assert.ok(stored.every((s) => !s.includes("undefined")));
});

test("the page names no sr memory command but on and off (the owner's rule, 22 Oct)", () => {
  // the switch's own `sr memory on|off` is the one sr memory command the page shows; the rest stay in Terminal
  const source = ["../../static/app.js", "../../static/index.html"].map((f) => readFileSync(new URL(f, import.meta.url), "utf8")).join("\n");
  assert.equal(/sr memory (start|stop|status|rebuild)|sr probe/.test(source), false);
});

test("break-ui: a run that goes on says how long after a minute, and turning off has its own words", () => {
  const t0 = Date.parse("2026-10-22T12:00:00Z");
  const early = memorySwitchView(ON, { to: "off", started: t0 }, null, t0 + 30 * 1000);
  assert.equal(early.cmdLabel, "Running");
  assert.equal(early.still, null);
  assert.match(early.words, /^Turning memory off: the router stops the store it started\./);
  const late = memorySwitchView(OFF, { to: "on", started: t0 }, null, t0 + 3 * 60 * 1000 + 5000);
  assert.equal(late.cmdLabel, "Running for 3 min");
  assert.equal(late.still, "The command hasn't ended after 3 min. It keeps running if you close this page; the Memory light shows where memory is when it ends.");
  assert.equal(memorySwitchView(OFF, { to: "on", started: t0 }, null, t0 + 61 * 1000).cmdLabel, "Running for 1 min");
});
