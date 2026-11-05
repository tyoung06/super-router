// Build brief 30 (decisions 10, 13 to 17): the page's pure parts for the router notes and a project's notes. The Setup
// row and its editor (state, counts, Grok's share, Save only with unsaved text, closing asks once), a project's Notes
// editor (the block read-only, counts, whether a save commits), the card's three actions from its JSON, Pin's text (the
// selection or the whole result) and its project choice, Save's path from `save_path`, and Details' per-call notes.
// The router works every number out; these tests feed its JSON.
import { test } from "node:test";
import assert from "node:assert/strict";
import { callNotesLines, cardActions, charCount, demoCommand, firstRunItems, forgottenLine, notesEditorView,
  pinSheetView, pinText, projectChoice, projectNotesView, routerNotesRow, saveSheetView, setupRows } from "../../static/app.js";

const DOC = { text: "## All agents\nUse metric units.\n", state: "set", why: null, line: null, total: 34, max: 6000,
  sections: { all_agents: 17, claude: 0, chatgpt: 0, grok: 0, cursor: 0, planner: 0 },
  grok: { share: 17, limit: 3662, line: "Grok gets these only on a call they fit." }, hash: "0123456789abcdef", default: false };

test("the Setup row reads the notes' state from status, and only an invalid file is a setup problem", () => {
  assert.deepEqual(routerNotesRow({ notes: { state: "blank", sections: {}, total: 72, max: 6000 } }).state, "blank");
  const set = routerNotesRow({ notes: { state: "set", sections: { all_agents: 17, grok: 9 }, total: 120, max: 6000 } });
  assert.equal(set.tone, "ok");
  assert.equal(set.detail, "All agents, Grok · 120 of 6,000 characters");
  const bad = routerNotesRow({ notes: { state: "invalid", why: "line 3 repeats a heading", sections: {}, total: 9, max: 6000 } });
  assert.equal(bad.tone, "bad");
  assert.match(bad.detail, /line 3 repeats a heading: every task is refused/);
  const rows = setupRows({ notes: { state: "blank", sections: {}, total: 72, max: 6000 }, agents: [] });
  assert.equal(rows.at(-2).key, "notes");  // brief 33.3: the Models row comes last
  assert.equal(firstRunItems({ notes: { state: "blank", sections: {}, total: 72, max: 6000 }, agents: [] })
    .some((r) => r.key === "notes"), false);  // blank is a choice
  assert.equal(firstRunItems({ notes: { state: "invalid", why: "x", sections: {}, total: 1, max: 6000 }, agents: [] })
    .some((r) => r.key === "notes"), true);
});

test("the editor shows the router's counts, Save only with unsaved text, and closing asks once", () => {
  const view = notesEditorView(DOC, DOC.text);
  assert.equal(view.dirty, false);
  assert.equal(view.canSave, false);
  assert.equal(view.total, "34 of 6,000 characters");
  assert.equal(view.grok, "Grok's share: 17 of its 3,662. Grok gets these only on a call they fit.");
  assert.deepEqual(view.sections.map((s) => s.title), ["All agents", "Claude", "ChatGPT", "Grok", "Cursor", "Planner"]);
  const typed = notesEditorView(DOC, DOC.text + "More.\n");
  assert.equal(typed.dirty, true);
  assert.equal(typed.canSave, true);
  assert.equal(typed.total, "34 of 6,000 characters (as saved)");
  assert.equal(typed.foot, "Unsaved changes");
  const closing = notesEditorView(DOC, DOC.text + "More.\n", { closing: true });
  assert.equal(closing.closeWords, "Discard changes");
  assert.match(closing.closeNote, /Close again to discard them/);
  assert.equal(notesEditorView(DOC, DOC.text, { closing: true }).closeNote, null);  // nothing unsaved: no ask
  assert.equal(notesEditorView(DOC, DOC.text + "x", { saving: true }).canSave, false);
  assert.equal(notesEditorView(DOC, DOC.text + "x", { demo: true }).canSave, false);
  assert.equal(notesEditorView(null, "").loading, true);
});

test("a refusal keeps the box as typed: the view never resets the text", () => {
  const failure = { title: "The router refused this", message: "Refused: line 2 looks like it holds a key", exit: 2 };
  const view = notesEditorView(DOC, "## Claude\nmine\n", { failure });
  assert.equal(view.dirty, true);
  assert.equal(view.failure, failure);
  assert.equal(view.canSave, true);
});

test("a project's Notes: counts, the block read-only, and whether a save commits", () => {
  const doc = { notes: "# Garden\n\nMine.", block: "<!-- sr:start -->\n<!-- sr:end -->", lines: 3, chars: 15, max: 20000,
    tracked: true, hash: "0123456789abcdef" };
  const view = projectNotesView(doc, doc.notes);
  assert.equal(view.counts, "3 lines · 15 of 20,000 characters");
  assert.match(view.commit, /one commit holding HANDOFF.md alone/);
  assert.equal(view.block, doc.block);
  assert.equal(projectNotesView({ ...doc, tracked: false }, "x").commit.includes("commits nothing"), true);
  assert.equal(projectNotesView(doc, "changed").canSave, true);
  assert.equal(projectNotesView(doc, "changed", { closing: true }).closeWords, "Discard changes");
});

test("the card's actions come from its JSON, never worked out", () => {
  const task = { task_id: "sr-1", n: 4, card_actions: { pin: true, save: true, forget: true, remember: false } };
  assert.deepEqual(cardActions(task).map((a) => a.label), ["Pin to notes", "Save to project", "Forget"]);
  assert.deepEqual(cardActions(task).at(-1).request, { action: "forget", task_id: "sr-1" });
  const gone = { task_id: "sr-1", n: 4, forgotten: "2026-10-28", card_actions: { pin: true, save: false, forget: false, remember: true } };
  assert.deepEqual(cardActions(gone).map((a) => a.label), ["Pin to notes", "Remember again"]);
  assert.deepEqual(cardActions(gone).at(-1).request, { action: "forget", task_id: "sr-1", undo: true });
  assert.match(forgottenLine(gone), /^Forgotten 2026-10-28/);
  assert.deepEqual(cardActions({ task_id: "sr-2" }), []);
});

test("Pin: the selection, else the whole result; the project is the task's own, else none until you pick", () => {
  const task = { task_id: "sr-1", n: 4, result: "Use euros.\n\nMore lines.\n", project: "garden" };
  assert.equal(pinText(task, "  euros  "), "euros");
  assert.equal(pinText(task, ""), "Use euros.\n\nMore lines.");
  assert.deepEqual(projectChoice(task, [{ name: "a" }]), { fixed: true, chosen: "garden", options: [] });
  const untagged = { ...task, project: null };
  assert.deepEqual(projectChoice(untagged, [{ name: "a" }, { name: "b" }]), { fixed: false, chosen: null, options: ["a", "b"] });
  const before = pinSheetView(untagged, [{ name: "a" }], { text: "x" });
  assert.equal(before.canSave, false);
  assert.equal(before.size, "Pick the project whose notes get it.");
  const after = pinSheetView(untagged, [{ name: "a" }], { project: "a", text: "x", notes: { chars: 1200, max: 20000, lines: 30 } });
  assert.equal(after.canSave, true);
  assert.equal(after.size, "Its notes now: 1,200 of 20,000 characters, 30 lines.");
  assert.equal(pinSheetView(untagged, [], { project: "a", text: "   " }).canSave, false);
});

test("Save: the path is the router's save_path until you edit it", () => {
  const task = { task_id: "sr-1", n: 4, save_path: "docs/tray-sizes.md", project: null };
  const view = saveSheetView(task, [{ name: "garden" }], { project: "garden" });
  assert.equal(view.path, "docs/tray-sizes.md");
  assert.equal(view.canSave, true);
  assert.equal(saveSheetView(task, [{ name: "garden" }], { project: "garden", path: "  " }).canSave, false);
  assert.equal(saveSheetView(task, [{ name: "garden" }], {}).canSave, false);  // no project chosen yet
});

test("Details: each call's router notes, by section, or left out", () => {
  const show = { calls: [
    { kind: "do", agent: "claude", router_notes: { sections: { all_agents: 31, claude: 58 }, judge: false, planner: false } },
    { kind: "check", agent: "chatgpt", router_notes: { sections: { all_agents: 31, chatgpt: 47 }, judge: true, planner: false } },
    { kind: "stage", role: "split_plan", agent: "claude", router_notes: { sections: { claude: 58, planner: 35 }, judge: false, planner: true } },
    { kind: "do", agent: "grok", router_notes: { left_out: "grok_limit", chars: 900 } },
    { kind: "fix", agent: "claude", router_notes: null }] };
  assert.deepEqual(callNotesLines(show), [
    "do · Claude: router notes · All agents 31 · Claude 58",
    "check · ChatGPT: router notes · All agents 31 · ChatGPT 47 · the judge line",
    "split_plan · Claude: router notes · Claude 58 · Planner 35 · the planner part",
    "do · Grok Bot: router notes left out (over Grok's limit)"]);
  assert.deepEqual(callNotesLines(null), []);
});

// break-ui (brief 30): a 2 MB result pinned whole was sent on every refresh and met the server's 413, and every sheet kept
// Save on while the server's builder refused its command (a 237-character path)
test("Pin holds back a text longer than the notes can hold, counted as the router counts (code points)", () => {
  const untagged = { task_id: "sr-1", n: 44, result: "x", project: null };
  const notes = { chars: 102, max: 20000, lines: 2 };
  const big = pinSheetView(untagged, [{ name: "a" }], { project: "a", text: "x".repeat(1999987), notes });
  assert.equal(big.tooLong, true);
  assert.equal(big.canSave, false);
  assert.equal(big.size, "The text is 1,999,987 characters; a project's notes hold at most 20,000. Select the part of the result to pin.");
  assert.equal(big.sizeTone, "bad");
  const emoji = "\u{1F331}" + "x".repeat(19999);  // 20,000 code points, 20,001 UTF-16 units: Python's len says 20,000
  assert.equal(charCount(emoji), 20000);
  assert.equal(pinSheetView(untagged, [{ name: "a" }], { project: "a", text: emoji, notes }).tooLong, false);
  assert.equal(pinSheetView(untagged, [{ name: "a" }], { project: "a", text: "x".repeat(20001), notes: null }).tooLong, false);
});

test("a command the server's builder refuses keeps Save off in every sheet", () => {
  const refused = "the path is 237 characters; at most 200";
  const task = { task_id: "sr-1", n: 4, save_path: "docs/tray-sizes.md", project: null };
  assert.equal(saveSheetView(task, [{ name: "garden" }], { project: "garden" }).canSave, true);
  assert.equal(saveSheetView(task, [{ name: "garden" }], { project: "garden", refused }).canSave, false);
  assert.equal(pinSheetView({ ...task, result: "x" }, [{ name: "garden" }], { project: "garden", text: "x", refused,
    notes: { chars: 1, max: 20000, lines: 1 } }).canSave, false);
  assert.equal(notesEditorView(DOC, DOC.text + "x", { refused: "the request is too big" }).canSave, false);
  const doc = { notes: "a", block: "", lines: 1, chars: 1, max: 20000, tracked: true, hash: "0123456789abcdef" };
  assert.equal(projectNotesView(doc, "b", { refused: "the request is too big" }).canSave, false);
  assert.equal(projectNotesView(doc, "b").canSave, true);
});

test("the demo's command lines for the notes actions are the builder's Copy: the texts by their length", () => {
  assert.equal(demoCommand({ action: "notes_save", expect: "0123456789abcdef", text: "ab\u{1F331}" }),
    "sr notes save --expect 0123456789abcdef -- <the notes, 3 characters>");
  assert.equal(demoCommand({ action: "project_notes_save", name: "garden-site", expect: "0123456789abcdef", text: "Mine." }),
    "sr project notes garden-site --save --expect 0123456789abcdef -- <the notes, 5 characters>");
  assert.equal(demoCommand({ action: "project_pin", name: "garden-site", task_id: "sr-1", text: "Use euros." }),
    "sr project pin garden-site --task sr-1 -- <the text, 10 characters>");
  assert.equal(demoCommand({ action: "project_save", name: "garden-site", task_id: "sr-1", path: "docs/tray sizes.md" }),
    "sr project save garden-site --task sr-1 --path 'docs/tray sizes.md'");
  assert.equal(demoCommand({ action: "forget", task_id: "sr-1" }), "sr forget sr-1");
  assert.equal(demoCommand({ action: "forget", task_id: "sr-1", undo: true }), "sr forget sr-1 --undo");
});
