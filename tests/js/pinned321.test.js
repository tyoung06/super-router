// Build brief 32.1: the stream head stays at the top while the stream scrolls, a card jumped to lands just below it,
// a project's bar folds into "Project tools" where the head would take more than about a third of the window, and a
// result shows whole up to PREVIEW_CHARS; past it, its first part whole, with no box (the design chat's D fix 5, 29 Oct).
// The layout itself is CSS, so its rules are read from the stylesheet.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  FOLD_SHARE, HEAD_GAP, PREVIEW_CHARS, anchorChoice, cardMargin, foldsTools, heldTop, projectToolsView, resultView, streamTop,
} from "../../static/app.js";

const CSS = readFileSync(new URL("../../static/app.css", import.meta.url), "utf8");
const JS = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const rule = (selector) => {
  const at = CSS.indexOf(`\n${selector} {`);
  assert.ok(at >= 0, `no rule for ${selector}`);
  return CSS.slice(at, CSS.indexOf("}", at));
};

// ---------- the sticky head ----------

test("the head is sticky in each view: one rule, under the strip, over the cards, below menus, the panel and sheets", () => {
  const head = rule(".stream-head");
  assert.match(head, /position: sticky;/);
  assert.match(head, /top: var\(--strip-h, 0px\);/);
  assert.match(head, /background: var\(--bg\);/);
  const z = Number(/z-index: (\d+);/.exec(head)[1]);
  for (const [selector, above] of [[".menu-list", 20], [".team-menu", 30], [".strip", 25], [".sheet-backdrop", 40]]) {
    assert.match(rule(selector), new RegExp(`z-index: ${above};`));
    assert.ok(z < above, `${selector} sits above the head`);
  }
  // every view draws its head with that class, first in the stream: a project, a chat, Quick tasks, All tasks, Log files
  assert.equal((JS.match(/h\("div", \{ class: "stream-head" \}/g) || []).length, 2);
  // brief 34: the Auto switch's confirm was the stream's first item under the head, never inside it (break-ui at 390 px).
  // UI-1 row 7 (D6a): the confirm moved to a sheet (friction 1), so the stream's first items are the head and the first-run card
  assert.match(JS, /const items = \[head, firstRunCard\(\)\]\.filter\(Boolean\);/);
  assert.match(JS, /return \[head, state\.logError/);
});

test("a card jumped to lands just below the head, the margin following the head's height", () => {
  assert.equal(HEAD_GAP, 12);
  assert.equal(cardMargin(52, 40), 104);
  assert.equal(cardMargin(52, 160), 224);  // a head that wrapped
  assert.equal(cardMargin(52.4, 40.2), 105);  // whole pixels, rounded up: never a sliver under the head
  assert.equal(cardMargin(undefined, null), HEAD_GAP);
  assert.equal(streamTop(52, 40), 92);  // the line a card must cross to be the one you are reading
  assert.match(rule(".stream > :not(.stream-head)"), /scroll-margin-top: var\(--card-margin, 16px\);/);
});

test("a card jumped to holds its place while it loads: a refresh never follows the end over it", () => {
  // break-ui: Needs you's last card, short until its details load, landed at the page's end; the next refresh followed
  // the end as it grew and put its top under the head
  assert.equal(anchorChoice({ changed: true, follow: true, nearEnd: true, held: true }), "end");  // a new view starts at its end
  assert.equal(anchorChoice({ changed: false, follow: true, nearEnd: true, held: true }), "held");
  assert.equal(anchorChoice({ changed: false, follow: true, nearEnd: true, held: false }), "end");
  assert.equal(anchorChoice({ changed: false, follow: false, nearEnd: true, held: false }), "reading");
  assert.equal(anchorChoice({ changed: false, follow: true, nearEnd: false, held: false }), "reading");
  assert.match(JS, /state\.heldCard = \{ id: wanted\.id, until: Date\.now\(\) \+ HOLD_MS \};/);
});

test("a jump the page was too short for goes just below the head once the page grows; a reader's own scroll is kept", () => {
  // D (29 Oct): after a page load, the first jump to a card in a one-card view ran while the card's details loaded, so
  // the page stopped at its end, 188 px below the card's place, and the hold kept it there
  assert.equal(heldTop({ top: 407, line: 231, atEnd: true }), 231);
  assert.equal(heldTop({ top: 407, line: 231, atEnd: false }), 407);  // not at the end: you scrolled it, it stays
  assert.equal(heldTop({ top: 231, line: 231, atEnd: true }), 231);
  assert.equal(heldTop({ top: 120, line: 231, atEnd: true }), 120);  // above its place: never pulled down
  assert.match(JS, /if \(choice === "held"\) \{[\s\S]{0,500}heldTop\(\{ top: held\.getBoundingClientRect\(\)\.top, line, atEnd \}\)/);
});

// ---------- narrow windows ----------

test("the project's bar folds into Project tools when the head would pass about a third of the window", () => {
  assert.equal(FOLD_SHARE, 1 / 3);
  assert.equal(foldsTools(330, 844), true);  // 390 x 844 with a long project bar
  assert.equal(foldsTools(281, 844), false);
  assert.equal(foldsTools(120, 900), false);  // a laptop
  assert.equal(foldsTools(330, 844, { open: true }), false);  // opened: it stays open
});

test("Project tools opens the bar in place, and a drop goes to whichever is shown", () => {
  assert.deepEqual(projectToolsView({ folds: false, open: false }), { button: null, bar: true, drop: "bar" });
  assert.deepEqual(projectToolsView({ folds: true, open: false }),
    { button: { label: "Project tools", expanded: false }, bar: false, drop: "button" });
  assert.deepEqual(projectToolsView({ folds: true, open: true }),
    { button: { label: "Project tools", expanded: true }, bar: true, drop: "bar" });
  // the bar's drop handler is one function, given to the bar and to the folded button alike: either opens the files sheet
  assert.match(JS, /function dropZone\(el, project, name\)/);
  assert.equal((JS.match(/dropZone\(/g) || []).length, 3);  // the definition and its two uses
});

// ---------- results in full ----------

test("a result of 3,000 characters and 60 lines shows whole, with no Show all or Show less", () => {
  const text = Array.from({ length: 60 }, (_, i) => `Line ${i + 1}: ${"x".repeat(40)}`).join("\n").slice(0, 3000);
  assert.equal(text.split("\n").length, 60);
  assert.deepEqual(resultView(text), { text, cut: false, beside: null });
  assert.doesNotMatch(JS, /Show less/);
  assert.doesNotMatch(JS, /state\.expanded/);
});

test("past PREVIEW_CHARS a result shows its first part whole, with no box, then Show all beside", () => {
  // the design chat's D fix 5 (29 Oct): the owner asked to see the entire message; the limit keeps megabytes out of the
  // stream, never a box: no 420 px clamp and no fade over the first 20,000 characters
  const line = "region,store,week,units\n";
  const text = line.repeat(Math.ceil(25000 / line.length)).slice(0, 25000);
  const view = resultView(text);
  assert.equal(PREVIEW_CHARS, 20000);
  assert.ok(view.text.length <= PREVIEW_CHARS && view.text.length > PREVIEW_CHARS * 0.8);
  assert.ok(text.startsWith(view.text));
  assert.equal(view.cut, true);
  assert.equal(view.beside, "Show all 24 KB beside");
  assert.equal(resultView("x".repeat(PREVIEW_CHARS)).cut, false);  // exactly 20,000 still shows whole
  assert.doesNotMatch(CSS, /\.result\.clamped/);
  assert.doesNotMatch(rule(".result"), /max-height/);
  assert.doesNotMatch(JS, /clamped/);
});
