// Build brief 33.2, S2 (decisions 4 and 5): the spec on the page. The Spec section of a project's Notes sheet (none, set,
// saving, refused), its labels as the router read them, Save only with unsaved text; Draft it while the project has no
// spec, filling Route, the project, the router's text and the Text only pill (`--no-files`); the card's files line
// "handoff only (text only, as asked)"; the put-back line; Details' per-call spec lines. Every value here is fake.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  callSpecLines, demoCommand, fileView, fillFromChip, labelRanges, projectSpecView, sendRequest, specRestoredLine, SPEC_NONE,
} from "../../static/app.js";

const JS = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const HTML = readFileSync(new URL("../../static/index.html", import.meta.url), "utf8");
const CSS = readFileSync(new URL("../../static/app.css", import.meta.url), "utf8");

const DRAFT = { kind: "draft_spec", words: "Draft it", later: false,
  fill: { team: "route", project: "garden", chat: null, text: "Write SPEC.md for this project: what it is and why, what is not "
    + "in it, then `## Examples` and `## Done when`, each a numbered list, one line per item.", from: null, idea: null, step: null,
  no_files: true } };
const NONE = { name: "garden", folder: "~/Projects/garden", exists: false, text: "", hash: "e3b0c44298fc1c14", chars: 0, lines: 0,
  max: 6000, git: true, commits: true, tracked: false, examples: [], done_when: [], labeled: false,
  commit_words: "Save makes one commit holding SPEC.md alone.", draft: DRAFT };
const SET = { ...NONE, exists: true, text: "# Converter\n\n## Examples\n- c_to_f(100) == 212\n\n## Done when\n- tests pass\n",
  hash: "0123456789abcdef", chars: 70, lines: 7, tracked: true, labeled: true,
  examples: [{ label: "E1", text: "c_to_f(100) == 212" }], done_when: [{ label: "D1", text: "tests pass" }], draft: null };

test("a project without a spec reads Spec · none and offers Draft it; one with a spec shows its labels as read", () => {
  const none = projectSpecView(NONE, null);
  assert.equal(none.title, SPEC_NONE);
  assert.equal(none.exists, false);
  assert.deepEqual(none.draft, DRAFT);
  assert.equal(none.labels.length, 0);
  assert.equal(none.canSave, false);  // nothing typed yet
  const set = projectSpecView(SET, null);
  assert.equal(set.title, "Spec · E1, D1");
  assert.equal(set.draft, null);
  assert.deepEqual(set.labels.map((l) => `${l.label} ${l.text}`), ["E1 c_to_f(100) == 212", "D1 tests pass"]);
  assert.equal(set.counts, "7 lines · 70 of 6,000 characters");
  assert.match(set.commit, /one commit holding SPEC.md alone/);
  assert.equal(set.labeledNote, null);
  const sixty = [...Array(60)].map((_, k) => ({ label: `E${k + 1}`, text: "x" }));
  const long = projectSpecView({ ...SET, examples: sixty, done_when: [{ label: "D1", text: "y" }, { label: "D2", text: "z" }] }, null);
  assert.equal(long.title, "Spec · E1–E60, D1, D2");  // break-ui: runs of three or more read as a range
  assert.equal(labelRanges(["E1", "E2", "E3", "E5", "D1", "D2", "D3"]), "E1–E3, E5, D1–D3");
  const text = projectSpecView({ ...SET, examples: [], done_when: [], labeled: false }, null);
  assert.equal(text.title, "Spec · text only");
  assert.match(text.labeledNote, /No `## Examples` or `## Done when` list/);
});

test("Save only with unsaved, non-empty text; off while saving, in the demo and after a refusal kept on the sheet", () => {
  assert.equal(projectSpecView(SET, SET.text).canSave, false);
  assert.equal(projectSpecView(SET, SET.text + "\nMore.\n").canSave, true);
  assert.equal(projectSpecView(SET, SET.text + "\nMore.\n").counts, "7 lines · 70 of 6,000 characters (as saved)");
  assert.equal(projectSpecView(SET, SET.text + "x", { saving: true }).canSave, false);
  assert.equal(projectSpecView(SET, SET.text + "x", { saving: true }).saveWords, "Saving…");
  assert.equal(projectSpecView(SET, SET.text + "x", { demo: true }).canSave, false);
  assert.equal(projectSpecView(NONE, "   \n").canSave, false);  // an empty spec is never saved
  assert.equal(projectSpecView(NONE, "# Mine\n").canSave, true);
  assert.equal(projectSpecView(NONE, "# Mine\n").foot, "Unsaved changes");
  const failure = { title: "The router refused this", message: "Refused: SPEC.md line 2 looks like it holds a key", exit: 2 };
  const refused = projectSpecView(SET, "# typed\n", { failure });
  assert.equal(refused.failure, failure);
  assert.equal(refused.text, "# typed\n");  // the box keeps what was typed
  assert.equal(refused.canSave, true);
  assert.equal(projectSpecView(null, "").loading, true);
});

test("Draft it fills Route, the project, the router's text and the Text only pill; the request carries --no-files", () => {
  const { next, undo } = fillFromChip(DRAFT, { text: "half", team: "plan", project: "garden" }, 7);
  assert.deepEqual([next.team, next.project, next.text, next.noFiles, next.idea, next.step], ["route", "garden", DRAFT.fill.text, true, null, null]);
  assert.equal(undo.text, "half");
  const status = { projects: [{ name: "garden" }], presets: [], skills: [{ key: "code" }], jev: { available: true } };
  const state = { team: "route", text: DRAFT.fill.text, project: "garden", noFiles: true, files: [], slots: {} };
  assert.equal(sendRequest(state, status).no_files, true);
  assert.equal(sendRequest({ ...state, noFiles: false }, status).no_files, undefined);
  assert.equal(sendRequest({ ...state, project: null, chat: "x" }, status).no_files, undefined);  // the switch is a project task's
  assert.equal(sendRequest({ ...state, team: "redteam" }, status).no_files, undefined);
  const plain = fillFromChip({ kind: "agent", words: "x", fill: { team: "route", project: "garden", text: "x" } }, { text: "" }, 7);
  assert.equal(plain.next.noFiles, false);
});

test("the Text only pill is in the composer with a 32 px ×, and Esc clears it with the others", () => {
  assert.match(HTML, /id="textonly-pill"/);
  assert.match(CSS, /\.pill-textonly \.x[^}]*min-width: 32px/);
  assert.match(JS, /state\.noFiles = false; refreshCommand\(\); renderComposer\(\);/);  // the ×
  assert.match(JS, /state\.text \|\| state\.from \|\| state\.idea \|\| state\.step \|\| state\.models \|\| state\.noFiles/);  // Esc
});

test("the card's files line reads handoff only (text only, as asked), and the put-back line is the router's", () => {
  const task = (files) => ({ task_id: "sr-1", project: "garden", status: "done", project_files: files });
  const off = fileView(task({ mode: "off", state: "none", copy: false, why: "text only, as asked" }));
  assert.equal(off.line, "Files: handoff only (text only, as asked)");
  assert.equal(fileView(task({ mode: "off", state: "none", copy: false, why: "no git yet: Turn on undo" })).line,
    "Files: handoff only (no git yet: Turn on undo)");
  assert.equal(specRestoredLine(task({ mode: "on", state: "waiting", copy: true, changed: [], spec_restored: true })),
    "SPEC.md was changed by the build; the router put it back (it is yours).");
  assert.equal(specRestoredLine(task({ mode: "on", state: "waiting", copy: true, changed: [] })), null);
  assert.equal(specRestoredLine({ task_id: "sr-2" }), null);
});

test("Details: each call's spec, as sent or left out", () => {
  const show = { calls: [
    { call_id: "sr-1", kind: "do", agent: "claude", spec: { hash: "0123456789abcdef", chars: 1234, from: "sr-1" } },
    { call_id: "sr-1-c1", kind: "check", agent: "chatgpt", spec: { hash: "0123456789abcdef", chars: 1234, from: "sr-1" } },
    { call_id: "sr-1-g", kind: "do", agent: "grok", spec: { left_out: "grok_limit", hash: "0123456789abcdef", chars: 1234, from: "sr-1" } },
    { call_id: "sr-1-x", kind: "fix", agent: "claude", spec: null },
  ] };
  const lines = callSpecLines(show);
  assert.equal(lines.length, 3);
  assert.match(lines[0], /^do · Claude: SPEC\.md · 1,234 characters$/);
  assert.match(lines[1], /^check · ChatGPT: SPEC\.md · 1,234 characters · the judge line$/);
  assert.match(lines[2], /^do · Grok Bot: SPEC\.md left out \(over Grok's limit\)$/);
  assert.deepEqual(callSpecLines({ calls: [] }), []);
});

test("the demo's command line for a spec save is the builder's copy: the text by its length", () => {
  assert.equal(demoCommand({ action: "project_spec_save", name: "garden", expect: "0123456789abcdef", text: "# Mine\n\nx" }),
    "sr project spec garden --save --expect 0123456789abcdef -- <the spec, 9 characters>");
});
