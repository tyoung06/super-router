// Build brief 32 (decision 17): the redteam board with two attack lists, the line for a list that didn't run, the stage
// line's four stages and a skipped one, and the slot picker's second attack. Fixtures: the demo's documents
// (scripts/make_demo.py), and copies of them changed in the test where the demo has no such case.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { pieceSlots, redteamBoard, rescueOffers, slotViews, stagesView } from "../../static/app.js";

const demo = (name) => JSON.parse(readFileSync(new URL(`../../demo/${name}`, import.meta.url), "utf8"));
const STATUS = demo("status.json");
const TASKS = demo("log.json").tasks;
const SHOWS = Object.fromEntries(readdirSync(new URL("../../demo/tasks/", import.meta.url)).map((f) => [f.replace(/\.json$/, ""), demo(`tasks/${f}`)]));
const find = (pred) => { const task = TASKS.find(pred); assert.ok(task, "no such demo task"); return [task, SHOWS[task.task_id]]; };
const bakery = () => find((t) => t.preset === "redteam" && t.text.startsWith("Plan how the bakery"));
const shed = () => find((t) => t.preset === "redteam" && t.text.startsWith("Plan how the garden club"));
const CURSOR_OFF = "Cursor is off: its safety check failed on agent 2026.10.19-6bbf2c4";

// ---------- the board ----------

test("the board groups the findings by list, each with its label, severity, answer or fixed, and the check's verdict", () => {
  const board = redteamBoard(...bakery());
  assert.deepEqual(board.groups.map((g) => g.title), ["Attacks · ChatGPT", "Attacks · Cursor"]);
  assert.deepEqual(board.groups[0].findings.map((f) => [f.label, f.severity, f.fix, f.check]), [
    ["A1", "high", "fixed", "passed"], ["A2", "medium", "fixed", "passed"],
    ["A3", "low", "answered: The column names are fixed in step 1, so this attack does not apply.", "passed"]]);
  assert.deepEqual(board.groups[1].findings.map((f) => [f.label, f.severity, f.fix.split(":")[0], f.check]), [
    ["B1", "high", "fixed", "passed"], ["B2", "medium", "answered", "passed"], ["B3", "low", "answered", "passed"]]);
  assert.deepEqual(board.lines, []);
});

test("a check whose open must names a label shows it still open, and one before any check says so", () => {
  const [task, show] = bakery();
  const copy = structuredClone(show);
  copy.attacks.find((a) => a.label === "B1").check = "open";
  copy.attacks.find((a) => a.label === "A2").check = null;
  const board = redteamBoard(task, copy);
  assert.equal(board.groups[1].findings[0].check, "still open");
  assert.equal(board.groups[0].findings[1].check, "not checked yet");
});

test("one attacker: the second attack left out reads one line, and its list has no group", () => {
  const board = redteamBoard(...shed());
  assert.deepEqual(board.groups.map((g) => [g.title, g.findings.map((f) => f.label)]), [["Attacks · ChatGPT", ["A1", "A2", "A3"]]]);
  assert.deepEqual(board.lines, [`One attacker: Cursor isn't available (${CURSOR_OFF})`]);
});

test("a skipped second attack reads its line, as the router words it", () => {
  const [task, show] = bakery();
  const copy = structuredClone(show);
  copy.attack_lists[1] = { ...copy.attack_lists[1], items: [], strongest: null, state: "skipped",
    why: "Cursor's call failed (too_long)", line: "Second attack skipped: Cursor's call failed (too_long)" };
  copy.attacks = copy.attacks.filter((a) => a.attacker === "chatgpt");
  const board = redteamBoard(task, copy);
  assert.deepEqual(board.groups.map((g) => g.title), ["Attacks · ChatGPT"]);
  assert.deepEqual(board.lines, ["Second attack skipped: Cursor's call failed (too_long)"]);
});

test("a task from before brief 32 keeps its one list by number, as it ran", () => {
  const [task, show] = bakery();
  const old = structuredClone(show);
  delete old.attack_lists;
  old.attacks = [{ n: 1, severity: "high", text: "No backup.", answered: null },
    { n: 2, severity: "low", text: "Columns.", answered: "Fixed in step 1." }];
  assert.deepEqual(redteamBoard(task, old), { findings: [{ n: 1, severity: "high", text: "No backup.", fix: "fixed" },
    { n: 2, severity: "low", text: "Columns.", fix: "answered: Fixed in step 1." }] });
  assert.equal(redteamBoard(task, { ...old, attacks: [] }), null);
  assert.equal(redteamBoard(...find((t) => t.preset === "versus")), null);
});

// ---------- the stage line ----------

test("the stage line shows four stages and the check, and a skipped stage says skipped", () => {
  const [task, show] = bakery();
  assert.deepEqual(stagesView(task, show).map((s) => [s.label, s.agent, s.state]), [
    ["build", "claude", "ok"], ["attack", "chatgpt", "ok"], ["attack", "cursor", "ok"], ["revise", "claude", "ok"],
    ["check", "chatgpt", "ok"]]);
  const copy = structuredClone(show);
  Object.assign(copy.calls[2], { status: "failed", reason_code: "skipped" });
  assert.deepEqual(stagesView(task, copy)[2], { ...stagesView(task, show)[2], label: "attack skipped", state: "skip",
    reason: "skipped" });
  Object.assign(copy.calls[2], { status: "done", reason_code: null });
  copy.calls.splice(3, 0, { ...copy.calls[2], call_id: "x-s3r", kind: "reask", status: "done", reason_code: "skipped" });
  assert.deepEqual(stagesView(task, copy).slice(2, 4).map((s) => [s.label, s.state]), [["attack", "ok"],
    ["attack re-ask skipped", "skip"]]);  // break-ui: the re-ask is the row a skip is often on
  assert.equal(stagesView(...shed()).length, 4);  // one attacker: build, attack, revise, check
});

// ---------- the slot picker ----------

const upStatus = () => {
  const status = structuredClone(STATUS);
  for (const a of status.agents) Object.assign(a, { available: true, why: null, why_code: null, online: true });
  const red = status.presets.find((p) => p.name === "redteam");
  for (const slot of red.slots) slot.allowed = ["claude", "grok", "chatgpt", ...(slot.name.startsWith("attack") ? ["cursor"] : [])];
  red.filled = [];
  return [status, red];
};

test("the second attack offers the agents intake allows there: never the build's, never the first attack's", () => {
  const [status, red] = upStatus();
  const view = slotViews(red, {}, status);
  assert.deepEqual(view.slots.map((s) => [s.name, s.label, s.value]), [["build", "Build and revise", "claude"],
    ["attack", "Attack", "chatgpt"], ["attack2", "Second attack", "cursor"], ["check", "Check", "chatgpt"]]);
  const second = view.slots[2].options;
  assert.deepEqual(second.filter((o) => o.disabled).map((o) => [o.agent, o.reason]), [
    ["claude", "an attacker doesn't attack its own build"], ["chatgpt", "two lists from one agent are not two attackers"]]);
  assert.deepEqual(second.filter((o) => !o.disabled).map((o) => o.agent), ["grok", "cursor"]);
  assert.deepEqual(view.slots[1].options.filter((o) => o.disabled).map((o) => o.agent), ["claude"]);
  assert.equal(view.note, "Cursor may fill Redteam Attack or Second attack only");
  const moved = slotViews(red, { attack: "grok" }, status).slots[2].options;  // the first attack moved: grok is out now
  assert.deepEqual(moved.filter((o) => o.disabled).map((o) => o.agent), ["claude", "grok"]);
});

test("a second attack the router leaves out reads Left out with why, until an agent is picked for it", () => {
  const [status, red] = upStatus();
  for (const slot of red.slots) slot.allowed = slot.allowed.filter((a) => a !== "cursor");
  red.filled = [{ slot: "attack2", agent: null, default: "cursor", why: CURSOR_OFF }];
  const out = slotViews(red, {}, status).slots[2];
  assert.equal(out.value, "");
  assert.equal(out.leftOut, true);
  assert.deepEqual(out.options.slice(0, 2).map((o) => [o.agent, o.label, o.disabled, o.reason]), [
    ["", "Left out", false, CURSOR_OFF], ["cursor", "Cursor", true, CURSOR_OFF]]);
  const picked = slotViews(red, { attack2: "grok" }, status).slots[2];
  assert.equal(picked.value, "grok");
  assert.equal(picked.leftOut, false);
  // a refused send's rescue never offers an agent for the left-out slot, nor one the picker greys
  const run = { request: { action: "send", team: "redteam", text: "t", slots: { build: "claude" } },
    envelope: { reason_code: "signed_out" } };
  assert.deepEqual(rescueOffers(run, status), []);
});

test("on a project a slot greys the agents status says a project refuses there", () => {
  const status = structuredClone(STATUS);
  const versus = status.presets.find((p) => p.name === "versus");
  for (const slot of versus.slots) slot.allowed = ["claude", "grok", "chatgpt", "cursor"];
  const off = slotViews(versus, {}, status, "swap-shelf").slots.map((s) => s.options.find((o) => o.agent === "cursor"));
  assert.deepEqual(off, [0, 1].map(() => ({ agent: "cursor", label: "Cursor", disabled: true, reason: "not on a project" })));
  assert.equal(slotViews(versus, {}, status).slots[1].options.find((o) => o.agent === "cursor").disabled, false);
  const [, red] = upStatus();
  const onProject = slotViews(red, {}, status, "swap-shelf").slots;
  assert.equal(onProject[2].options.find((o) => o.agent === "cursor").disabled, false);  // the attack slots take Cursor there
});

test("a split piece's second attack the router leaves out reads Left out, and choosing it puts the default back", () => {
  const presets = [{ name: "redteam", slots: [{ name: "build", default: "claude", allowed: ["claude"] },
    { name: "attack", default: "chatgpt", allowed: ["chatgpt"] }, { name: "attack2", default: "cursor", allowed: ["grok"] },
    { name: "check", default: "chatgpt", allowed: ["chatgpt"] }] }];
  const piece = { piece: 1, slots: {}, slot_map: { build: "claude", attack: "chatgpt", attack2: null, check: "chatgpt" } };
  const slot = pieceSlots({ task_id: "sr-9" }, piece, "redteam", presets)[2];
  assert.equal(slot.agent, "");
  assert.deepEqual(slot.options.map((o) => [o.agent, o.label]), [["", "Left out"], ["grok", "Grok Bot"]]);
  assert.deepEqual(slot.request(""), { action: "split_edit", task_id: "sr-9", piece: 1, slots: { attack2: "default" } });
  assert.deepEqual(slot.request("grok").slots, { attack2: "grok" });
});
