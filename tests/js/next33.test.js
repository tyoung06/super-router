// Build brief 33, N (decisions 1, 2, 7 and 19): the chips on the page. The router fills `next` on every delivered task;
// the page shows them under the newest card of a project's or a chat's view only, when that card was delivered and
// nothing newer is there but cancelled, discarded or undone tasks; an older card keeps them in Details, under
// "Suggested next". A chip fills the composer (Route, the tag, the text, From) and never sends; a fill over typed text
// offers Undo for 10 seconds, which puts back the box, its team, tag and pills.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { UNDO_MS, chipCardId, chipPlace, fillFromChip, sendRequest } from "../../static/app.js";

const JS = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const CSS = readFileSync(new URL("../../static/app.css", import.meta.url), "utf8");

const BUILD = (n, id, project = null, chat = "wx") => ({ kind: "build_from", words: `Build from #${n}`, later: false,
  fill: { team: "route", project, chat: project ? null : chat, text: "", from: id, idea: null } });
const AGENT = (words, id, project = null, chat = "wx") => ({ kind: "agent", words, later: !!project,
  fill: { team: "route", project, chat: project ? null : chat, text: words, from: project ? null : id, idea: null } });

function task(n, extra = {}) {
  const id = `sr-${n}`;
  return { task_id: id, n, created_at: `2026-10-29T12:${String(n).padStart(2, "0")}:00+00:00`, status: "done",
    outcome: "passed", parent: null, project_files: null, next: [BUILD(n, id), AGENT("Compare their licences.", id)], ...extra };
}

// ---------- which card shows them (decision 2) ----------

test("the newest delivered card of a project or a chat shows its chips; other views show none", () => {
  const tasks = [task(1), task(2)];
  assert.equal(chipCardId("chat", tasks), "sr-2");
  assert.equal(chipCardId("project", tasks), "sr-2");
  for (const view of ["quick", "all", "history", "logfiles"]) assert.equal(chipCardId(view, tasks), null);
});

test("a newer task, even one still running, folds them away; a cancelled, discarded or undone one doesn't", () => {
  assert.equal(chipCardId("chat", [task(1), task(2, { status: "queued", outcome: null, next: [] })]), null);
  assert.equal(chipCardId("chat", [task(1), task(2, { status: "done", outcome: "failed_check", next: [] })]), null);
  assert.equal(chipCardId("chat", [task(1), task(2, { status: "cancelled", outcome: "cancelled", next: [] })]), "sr-1");
  for (const state of ["discarded", "undone"]) {
    const newer = task(2, { project_files: { state }, next: [] });
    assert.equal(chipCardId("project", [task(1), newer]), "sr-1", state);
  }
  assert.equal(chipCardId("project", [task(1), task(2, { project_files: { state: "waiting" }, next: [] })]), null);
});

test("never a piece, and never a card with no chips", () => {
  assert.equal(chipCardId("chat", [task(1), task(2, { parent: "sr-9" })]), "sr-1");  // a piece isn't the view's task
  assert.equal(chipCardId("chat", [task(1, { next: [] })]), null);
});

test("an older card keeps its chips in Details, under Suggested next", () => {
  assert.equal(chipPlace(task(2), "sr-2"), "inline");
  assert.equal(chipPlace(task(1), "sr-2"), "details");
  assert.equal(chipPlace(task(1, { next: [] }), "sr-2"), null);
  assert.match(JS, /"Suggested next"/);
  assert.match(JS, /class: "next-row"/);
});

// ---------- the fill (decision 1) ----------

const EMPTY = { text: "", team: "redteam", project: null, chat: "wx", quick: false, from: null, idea: null };

test("Build from this fills Route, the tag, an empty box with its placeholder, and From", () => {
  const { next, undo } = fillFromChip(BUILD(7, "sr-7"), EMPTY, 7);
  assert.deepEqual(next, { text: "", team: "route", project: null, chat: "wx", quick: false,
    from: { task_id: "sr-7", n: 7 }, idea: null, step: null, placeholder: "What should be built from #7?",
    noFiles: false });  // 33.1: step; 33.2: the Text only pill (Draft it)
  assert.equal(undo, null);  // nothing typed: nothing to undo
});

test("an agent chip fills its line, and From only off a project", () => {
  assert.deepEqual(fillFromChip(AGENT("Map them.", "sr-7"), EMPTY, 7).next.from, { task_id: "sr-7", n: 7 });
  const onProject = fillFromChip(AGENT("Add a --round option.", "sr-7", "demo"), { ...EMPTY, chat: null, project: "demo" }, 7);
  assert.equal(onProject.next.text, "Add a --round option.");
  assert.equal(onProject.next.from, null);
  assert.equal(onProject.next.project, "demo");
  assert.equal(onProject.next.placeholder, null);
});

test("a fill over typed words replaces them and keeps an Undo for 10 seconds", () => {
  const typed = { ...EMPTY, text: "half a thought", team: "versus" };
  const { next, undo } = fillFromChip(AGENT("Map them.", "sr-7"), typed, 7);
  assert.equal(next.text, "Map them.");
  assert.deepEqual(undo, typed);  // the box, its team, tag and pills as they were
  assert.equal(UNDO_MS, 10000);
});

test("a chip never sends: its click only fills, and Send stays off on an empty box", () => {
  assert.match(JS, /function useChip\(/);
  assert.doesNotMatch(JS.slice(JS.indexOf("function useChip("), JS.indexOf("function useChip(") + 1500), /api\("\/api\/run"/);
  assert.match(JS, /send\.disabled = [^;]*!state\.text\.trim\(\)/);
});

// ---------- the request and the pills ----------

test("the request carries --from's task, never on a split", () => {
  const state = { ...EMPTY, team: "route", text: "Write the script.", from: { task_id: "sr-7", n: 7 }, chat: "wx",
    files: [], web: false, slots: {} };
  assert.equal(sendRequest(state, { presets: [], projects: [] }).from, "sr-7");
  assert.equal(sendRequest({ ...state, team: "split" }, { presets: [], projects: [] }).from, undefined);
});

test("the chips are real buttons with 44 px targets that wrap", () => {
  const row = CSS.slice(CSS.indexOf("\n.next-row {"), CSS.indexOf("}", CSS.indexOf("\n.next-row {")));
  assert.match(row, /flex-wrap: wrap/);
  const chip = CSS.slice(CSS.indexOf("\n.next-chip {"), CSS.indexOf("}", CSS.indexOf("\n.next-chip {")));
  assert.match(chip, /min-height: 44px/);
});
