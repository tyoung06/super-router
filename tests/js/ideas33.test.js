// Build brief 33, I (decisions 7, 14 to 16 and 19): the Ideas list on the page. "Ideas · <k>" on the project's bar
// opens the sheet: the list (text, where it came from with its link, date), Send and Dismiss on each, and Add; a refusal
// stays in the sheet. Send fills the composer as a chip does, with the Idea pill (its × sends plain text). An agent chip
// on a project card has Later (×, "Later: move to Ideas"). What now?'s fifth rung offers Ideas when the list has some.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fillFromIdea, ideasSheetView, sendRequest, whatNowParts } from "../../static/app.js";

const JS = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const HTML = readFileSync(new URL("../../static/index.html", import.meta.url), "utf8");
const CSS = readFileSync(new URL("../../static/app.css", import.meta.url), "utf8");
const DOC = { ideas: [
  { id: 4, text: "Add a --round option.", source: { kind: "later", task_id: "sr-a", n: 12 }, created_at: "2026-10-29T10:00:00+00:00",
    state: "sent", sent_as: { task_id: "sr-b", n: 14 } },
  { id: 3, text: "Add a Kelvin column.", source: { kind: "added", task_id: null, n: null }, created_at: "2026-10-28T09:00:00+00:00",
    state: "open", sent_as: null }], dismissed: 2 };

test("the sheet lists each idea with its source, date and state, newest first", () => {
  const view = ideasSheetView(DOC, { name: "demo" });
  assert.equal(view.title, "Ideas · demo");
  assert.deepEqual(view.rows.map((r) => [r.id, r.source.words, r.date, r.sent, r.canSend]), [
    [4, "Later on #12", "2026-10-29", "sent as #14", false], [3, "Added", "2026-10-28", null, true]]);
  assert.equal(view.rows[0].source.taskId, "sr-a");
  assert.equal(view.dismissed, 2);
  assert.equal(ideasSheetView(null, { name: "demo" }).loading, true);
  assert.equal(ideasSheetView({ ideas: [], dismissed: 0 }, { name: "demo" }).empty, true);
});

test("Add is the router's command, off on an empty box, while running and in the demo", () => {
  assert.equal(ideasSheetView(DOC, { name: "demo", text: "  " }).canAdd, false);
  assert.equal(ideasSheetView(DOC, { name: "demo", text: "Plot the week" }).canAdd, true);
  assert.equal(ideasSheetView(DOC, { name: "demo", text: "Plot it", running: true }).canAdd, false);
  assert.equal(ideasSheetView(DOC, { name: "demo", text: "Plot it", demo: true }).canAdd, false);
  assert.equal(ideasSheetView(DOC, { name: "demo", text: "Plot the week" }).line, "sr ideas demo --add -- 'Plot the week'");
});

test("Dismiss asks once on its own row", () => {
  const view = ideasSheetView(DOC, { name: "demo", asking: 3 });
  assert.deepEqual(view.rows.map((r) => r.asking), [false, true]);
  assert.match(JS, /"Dismiss it\? The page can't undo this\."/);
});

test("Send fills Route, the project, the text and the Idea pill, with Undo over typed words", () => {
  const { next, undo } = fillFromIdea(DOC.ideas[1], "demo", { text: "half a thought", team: "versus", project: "demo" });
  assert.deepEqual(next, { text: "Add a Kelvin column.", team: "route", project: "demo", chat: null, quick: false, from: null,
    idea: { id: 3, text: "Add a Kelvin column." }, placeholder: null });
  assert.equal(undo.text, "half a thought");
  assert.equal(fillFromIdea(DOC.ideas[1], "demo", { text: "" }).undo, null);
});

test("the request carries the idea's id, never on a split", () => {
  const state = { team: "route", text: "Add a Kelvin column.", project: "demo", idea: { id: 3, text: "x" }, files: [], slots: {} };
  const status = { projects: [{ name: "demo" }], presets: [], skills: [{ key: "code" }], jev: { available: true } };
  assert.equal(sendRequest(state, status).idea, 3);
  assert.equal(sendRequest({ ...state, team: "split" }, status).idea, undefined);
});

test("Later sits beside an agent chip on a project card, with its label; the pill and the bar's button exist", () => {
  assert.match(JS, /chip\.later \? h\("button", \{ class: "next-later", type: "button", "aria-label": "Later: move to Ideas"/);
  assert.match(HTML, /id="idea-pill" hidden/);
  assert.match(JS, /project\.ideas \? `Ideas · \$\{project\.ideas\}` : "Ideas"/);
  const later = CSS.slice(CSS.indexOf("\n.next-later {"), CSS.indexOf("}", CSS.indexOf("\n.next-later {")));
  assert.match(later, /min-width: 44px/);
  assert.match(later, /min-height: 44px/);
});

test("What now?'s fifth rung offers the Ideas list when it has ideas", () => {
  assert.equal(whatNowParts({ rung: 5, words: "Nothing suggested", control: "ideas", task_id: null, n: null, chip: null }).ideas, true);
  assert.equal(whatNowParts({ rung: 5, words: "Nothing suggested", control: null, task_id: null, n: null, chip: null }).ideas, false);
});

// ---------- break-ui (brief 33): what the worst cases found, kept fixed ----------

test("a long chip is a rounded box clamped to three lines, and What now?'s to two", () => {
  const chip = CSS.slice(CSS.indexOf("\n.next-chip {"), CSS.indexOf("}", CSS.indexOf("\n.next-chip {")));
  assert.match(chip, /border-radius: 22px/);
  assert.match(chip, /min-height: 44px/);
  const words = CSS.slice(CSS.indexOf("\n.next-words {"), CSS.indexOf("}", CSS.indexOf("\n.next-words {")));
  assert.match(words, /-webkit-line-clamp: 3/);
  assert.match(CSS, /\.what-now \.next-words \{ -webkit-line-clamp: 2; line-clamp: 2; \}/);
  assert.match(JS, /title: chip\.words, onclick: \(\) => useChip\(chip, task\)/);  // every word in its title
});

test("the Ideas sheet puts Add above its 50 ideas and keeps Close at its foot", () => {
  const sheet = JS.slice(JS.indexOf("function openIdeas("), JS.indexOf("function paintIdeas("));
  assert.ok(sheet.indexOf('id: "ideas-add"') < sheet.indexOf('id: "ideas-list"'));
  assert.match(CSS, /\.ideas-foot \{ position: sticky; bottom: -18px;/);
  assert.match(CSS, /\.idea-meta \.linklike \{ padding: 12px 0; margin: -12px 0; \}/);
});

test("the From and Idea pills' × is a 32 px target", () => {
  const x = CSS.slice(CSS.indexOf("\n.pill-from .x, .pill-idea .x {"), CSS.indexOf("}", CSS.indexOf("\n.pill-from .x, .pill-idea .x {")));
  assert.match(x, /min-width: 32px/);
  assert.match(x, /min-height: 32px/);
});
