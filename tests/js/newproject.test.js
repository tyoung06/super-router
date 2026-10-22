// Build brief 26, C (decisions 12–14): New project's pure parts. The name as the router's rule allows it (projectSlug),
// the sheet's state from the router's dry run (newProjectView), the picker's options with the "New project…" sentinel
// last (projectOptions), the empty project card's words and the toast after a create. Fixtures: the demo's status and
// sample dry-run answers in the router's own shape.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { contextFor, emptyProjectWords, NEW_PROJECT, newProjectView, notesLeftWords, projectOptions, projectSlug,
  projectToast, sendRequest, slugHint } from "../../static/app.js";

const STATUS = JSON.parse(readFileSync(new URL("../../demo/status.json", import.meta.url), "utf8"));
const ROOT = "~/Projects";
const dry = (would, extra = {}) => ({ api_version: 1, would, name: "price-tracker", folder: `${ROOT}/price-tracker`,
  handoff: { exists: false, lines: null, has_block: false }, reason_code: null, message: "m", ...extra });

test("the name is saved as the router's rule allows it", () => {
  assert.equal(projectSlug("Price Tracker"), "price-tracker");
  assert.equal(projectSlug("  --My App!! "), "my-app");
  assert.equal(projectSlug("Café Notes"), "cafe-notes");
  assert.equal(projectSlug("---"), "");
  assert.equal(projectSlug("a".repeat(60)), "a".repeat(48));
  assert.equal(projectSlug(`${"a".repeat(47)} b`), "a".repeat(47));  // no - left at the end after the cut
  assert.equal(projectSlug(`${"a".repeat(40)} ${"b".repeat(20)}`), "a".repeat(40));  // the word that doesn't fit goes
  assert.equal(projectSlug("日本語"), "");
  assert.equal(projectSlug("Seed_Trays.v2"), "seed-trays-v2");
  assert.equal(projectSlug(null), "");
  for (const raw of ["Price Tracker", "  --My App!! ", "x/../y", "a.b", "-h"]) assert.match(projectSlug(raw), /^[a-z0-9]+(-[a-z0-9]+)*$/);
});

test("the name hint says what it is saved as, or why nothing is", () => {
  assert.deepEqual(slugHint("Price Tracker"), { saved: "price-tracker", text: " · lowercase letters, digits and\u00a0-" });
  assert.equal(slugHint("").saved, null);
  assert.match(slugHint("").text, /converted as you type/);
  assert.match(slugHint("!!!").text, /letters or digits/);
  // break-ui: a long name is cut at 48 and says so, at a word boundary where one is near
  const long = slugHint("Northwind Industries Holdings Q3 2026 Board Review Follow-ups");
  assert.equal(long.saved, "northwind-industries-holdings-q3-2026-board");
  assert.match(long.text, /cut to 48 characters/);
  assert.doesNotMatch(slugHint("a".repeat(48)).text, /cut/);
});

test("a long name is cut at a word boundary when one is in the last part, else at 48", () => {
  assert.equal(projectSlug("Northwind Industries Holdings Q3 2026 Board Review Follow-ups"), "northwind-industries-holdings-q3-2026-board");
  assert.equal(projectSlug("a".repeat(60)), "a".repeat(48));
});

test("the sheet with no name, and while the router's answer is coming", () => {
  const empty = newProjectView(null, { name: "", root: ROOT });
  assert.deepEqual([empty.tone, empty.folder, empty.words, empty.canCreate, empty.notesOn], ["muted", `${ROOT}/…`, "type a name", false, true]);
  const waiting = newProjectView(null, { name: "price-tracker", root: ROOT });
  assert.deepEqual([waiting.words, waiting.canCreate, waiting.folder], ["checking…", false, `${ROOT}/price-tracker`]);
  const stale = newProjectView(dry("create", { name: "price" }), { name: "price-tracker", root: ROOT });
  assert.deepEqual([stale.words, stale.canCreate], ["checking…", false]);  // an answer for another name is not used
  const symbols = newProjectView(null, { name: "", root: ROOT, typed: true });  // break-ui: "!!!" typed, nothing kept
  assert.deepEqual([symbols.words, symbols.canCreate], ["no letters yet", false]);
  const silent = newProjectView(null, { name: "price-tracker", root: ROOT, waited: true });
  assert.deepEqual([silent.tone, silent.words, silent.canCreate], ["bad", "no answer", false]);
  assert.match(silent.detail, /hasn't answered/);
});

test("a new folder: green, notes on, Create project", () => {
  const view = newProjectView(dry("create"), { name: "price-tracker", root: ROOT });
  assert.deepEqual([view.tone, view.words, view.button, view.canCreate, view.notesOn],
    ["ok", "new folder", "Create project", true, true]);
  assert.equal(view.folder, `${ROOT}/price-tracker`);
  assert.match(view.detail, /your notes first, then the router's block/);
  assert.match(view.notesHint, /No keys/);
});

test("a folder that is there: blue, notes off, Add project, with its HANDOFF.md's state", () => {
  const handoff = { exists: true, lines: 14, has_block: false };
  const view = newProjectView(dry("register", { handoff }), { name: "price-tracker", root: ROOT });
  assert.deepEqual([view.tone, view.words, view.button, view.canCreate, view.notesOn],
    ["info", "folder exists", "Add project", true, false]);
  assert.match(view.detail, /HANDOFF.md \(14 lines\) stays yours; the router adds its block at the end/);
  assert.match(view.notesHint, /yours to edit/);
  const kept = newProjectView(dry("register", { handoff: { exists: true, lines: 9, has_block: true } }), { name: "price-tracker", root: ROOT });
  assert.match(kept.detail, /has the router's block already/);
  const none = newProjectView(dry("register", { handoff: { exists: false, lines: null, has_block: false } }), { name: "price-tracker", root: ROOT });
  assert.match(none.detail, /makes its HANDOFF.md with an empty block/);
});

test("a refusal: red, Create off, notes off, in the router's words; a taken name says so", () => {
  // the owner's tweak (22 Oct): the folder is the router's, shown with ~; status's absolute path is never printed
  const taken = newProjectView(dry("refused", { folder: "~/Code/price-tracker", reason_code: "project_refused",
    message: "Would refuse: price-tracker is already registered at ~/Code/price-tracker; remove it first. Nothing was changed." }),
  { name: "price-tracker", root: ROOT, taken: { name: "price-tracker", path: "/Users/you/Code/price-tracker" } });
  assert.deepEqual([taken.tone, taken.words, taken.canCreate, taken.notesOn, taken.button], ["bad", "already a project", false, false, "Create project"]);
  assert.equal(taken.folder, "~/Code/price-tracker");
  assert.ok(!JSON.stringify(taken).includes("/Users/"));
  assert.match(taken.detail, /registered already\. Open it from the sidebar, or pick another name/);
  assert.match(taken.notesHint, /a project already/);
  const other = newProjectView(dry("refused", { folder: null, reason_code: "project_refused",
    message: "Would refuse: price-tracker in the projects root is a link; a folder kept elsewhere is registered with sr project add price-tracker <path>. Nothing was changed." }),
  { name: "price-tracker", root: ROOT });
  assert.deepEqual([other.tone, other.words, other.canCreate, other.notesOn], ["bad", "refused", false, false]);
  assert.equal(other.detail, "price-tracker in the projects root is a link; a folder kept elsewhere is registered with sr project add price-tracker <path>.");
  assert.equal(other.folder, `${ROOT}/price-tracker`);
  const failed = newProjectView(null, { name: "price-tracker", root: ROOT, error: "the router's status could not be read" });
  assert.deepEqual([failed.tone, failed.words, failed.canCreate], ["bad", "can't check", false]);
});

test("the notes counter near the limit says how many are left, in the right number", () => {
  assert.equal(notesLeftWords(3000), null);
  assert.equal(notesLeftWords(3600), "400 characters left.");
  assert.equal(notesLeftWords(3999), "1 character left.");
  assert.equal(notesLeftWords(4000), "No characters left.");
});

test("while a create runs, and in the demo, Create is off", () => {
  const running = newProjectView(dry("create"), { name: "price-tracker", root: ROOT, running: true });
  assert.deepEqual([running.button, running.canCreate], ["Creating…", false]);
  const adding = newProjectView(dry("register", { handoff: { exists: true, lines: 2, has_block: true } }), { name: "price-tracker", root: ROOT, running: true });
  assert.equal(adding.button, "Adding…");
  const demo = newProjectView(dry("create"), { name: "price-tracker", root: ROOT, demo: true });
  assert.deepEqual([demo.canCreate, demo.foot], [false, "Demo: nothing runs."]);
});

test("the picker: the sentinel last, enabled with zero projects, greyed for a team without --project and for Quick", () => {
  const none = projectOptions([], {});
  assert.deepEqual(none.options.map((o) => [o.value, o.text]), [["", "No projects"], [NEW_PROJECT, "New project…"]]);
  assert.equal(none.disabled, false);
  const one = projectOptions([{ name: "garden-site" }], { current: "garden-site" });
  assert.deepEqual(one.options.map((o) => [o.value, o.text, o.selected]),
    [["", "No project", false], ["garden-site", "Project: garden-site", true], [NEW_PROJECT, "New project…", false]]);
  assert.equal(projectOptions([], { greyed: true }).disabled, true);
  assert.equal(projectOptions([{ name: "garden-site" }], { quick: true }).disabled, true);
  assert.ok(!/^[a-z0-9-]+$/.test(NEW_PROJECT));  // no project name can be the sentinel
});

test("the sentinel never appears in a send request", () => {
  for (const team of ["route", "research-build"]) {
    const request = sendRequest({ team, text: "x", project: NEW_PROJECT, chat: "garden", slots: {}, files: [] }, STATUS);
    assert.ok(!JSON.stringify(request).includes(NEW_PROJECT), JSON.stringify(request));
  }
  assert.equal(contextFor({ team: "route", project: NEW_PROJECT, chat: null }, STATUS).value === NEW_PROJECT, false);
});

test("a project with no tasks says its HANDOFF.md goes with every task", () => {
  assert.equal(emptyProjectWords({ name: "price-tracker", handoff_lines: 7 }),
    "No tasks in price-tracker yet. Its HANDOFF.md (7 lines) goes with every task you send here.");
  assert.equal(emptyProjectWords({ name: "price-tracker", handoff_lines: null }),
    "No tasks in price-tracker yet. Its HANDOFF.md can't be read right now.");
});

test("the toast after a create or an add", () => {
  const project = { name: "brief-26-test", folder: "~/Desktop/sr-brief26/brief-26-test", handoff_lines: 5, did: "created" };
  assert.equal(projectToast({ exit: 0, project }), "Created brief-26-test · ~/Desktop/sr-brief26/brief-26-test · HANDOFF.md 5 lines");
  assert.equal(projectToast({ exit: 0, project: { ...project, name: "existing-one", folder: "~/x/existing-one", handoff_lines: 4, did: "registered" } }),
    "Added existing-one · ~/x/existing-one · HANDOFF.md 4 lines");
  assert.equal(projectToast({ exit: 2 }), null);
  assert.equal(projectToast(null), null);
});
