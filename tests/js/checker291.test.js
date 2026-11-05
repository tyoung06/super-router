// Brief 29.1 (decisions 14, 17 and 21): a pass's notes under its verdict (folded), a failed check's open musts, the
// Blocked card and its Run again, Land anyway beside Discard behind a confirm that lists the open musts. Every value fake.
import { test } from "node:test";
import assert from "node:assert/strict";
import { blockedOffer, checkItems, confirmExtra, demoCommand, fileView, notesWords, verdictLine } from "../../static/app.js";

const base = { task_id: "sr-1", n: 7, status: "done", agent: "claude", checker: "chatgpt", text: "Write the follow-up email." };

test("a pass carries its notes under the verdict, folded, and a failed check lists what it left open", () => {
  const passed = { ...base, outcome: "passed", notes: [{ n: 2, text: "Shorter lines." }, { n: 3, text: "A warmer close." }] };
  assert.equal(verdictLine(passed).text, "Passed · ChatGPT · 2 notes");
  assert.deepEqual(checkItems(passed), { kind: "notes", title: "Show the notes", folded: true,
    items: [{ n: 2, text: "Shorter lines." }, { n: 3, text: "A warmer close." }] });
  assert.equal(notesWords({ ...base, notes: [{ n: 1, text: "x" }] }), " · 1 note");
  assert.equal(notesWords({ ...base, notes: [] }), "");
  const failed = { ...base, outcome: "failed_check", open_musts: [{ n: 1, text: "Name the client. (not fixed: still unnamed)" }] };
  assert.deepEqual(checkItems(failed), { kind: "musts", title: "Still open", folded: false,
    items: [{ n: 1, text: "Name the client. (not fixed: still unnamed)" }] });
  assert.equal(checkItems({ ...base, outcome: "passed", notes: [] }), null);
});

test("a blocked task names what it needed and offers Run again with its text, nothing sent", () => {
  const blocked = { ...base, status: "failed", outcome: "blocked", check_state: "blocked",
    check_note: "blocked: your notes from yesterday's meeting", chat: "brief291" };
  assert.deepEqual(verdictLine(blocked), { tone: "warn", text: "Blocked · ChatGPT" });
  const offer = blockedOffer(blocked);
  assert.equal(offer.what, "your notes from yesterday's meeting");
  assert.equal(offer.text, "Write the follow-up email.");
  assert.equal(offer.chat, "brief291");
  assert.equal(blockedOffer({ ...base, outcome: "passed" }), null);
});

test("Land anyway sits beside Discard on a failed check's kept change, and its confirm says the check didn't pass", () => {
  const files = { mode: "on", copy: true, changed: [{ path: "calc.py", status: "modified", plus: 2, minus: 1 }], state: null };
  const failed = { ...base, check_state: "failed", outcome: "failed_check", land_anyway: true, project_files: files,
    open_musts: [{ n: 1, text: "Under 5 words. (not fixed: 9 words)" }] };
  const view = fileView(failed);
  assert.deepEqual(view.buttons.map((b) => b.key), ["land_anyway", "discard"]);
  const land = view.buttons[0].request;
  assert.deepEqual(land, { action: "land", task_id: "sr-1", anyway: true });
  assert.equal(demoCommand(land), "sr land sr-1 --anyway");
  assert.deepEqual(confirmExtra(failed, land), { line: "Its check didn't pass. Still open:",
    musts: [{ n: 1, text: "Under 5 words. (not fixed: 9 words)" }] });
  assert.equal(confirmExtra(failed, { action: "land", task_id: "sr-1" }), null);
  const blocked = { ...failed, check_state: "blocked", outcome: "blocked", land_anyway: false };
  assert.deepEqual(fileView(blocked).buttons.map((b) => b.key), ["discard"]);
  assert.equal(fileView(blocked).note, "the check was blocked, so it can't land");
});

// Brief 29.1 (decision 24): a follow-up, on the task's pills and on a project split's plan card
import { followUpWords, receiptView, splitPlanView } from "../../static/app.js";

test("a follow-up names itself with Jev's label kept, and a plan's follow-up piece reads the same", () => {
  const task = { ...base, skill: "follow_up", skill_source: "router", agent: "claude", checker: "chatgpt", mode: "route",
    jev: { status: "below_floor", label: "writing", confidence: 0.31 }, created_at: "2026-10-27T10:00:00Z",
    updated_at: "2026-10-27T10:01:00Z", status: "done", outcome: "passed" };
  const pills = receiptView(task, null).map((p) => `${p.text}${p.value || ""}`);
  assert.equal(pills[0], "follow-up: Claude, with memory");
  assert.equal(pills[1], "Jev → writing 0.31");
  assert.equal(followUpWords("chatgpt"), "follow-up: ChatGPT, with memory");
  const plan = splitPlanView({ task_id: "sr-9", waiting_on: "split_plan", agent: "claude", checker: "chatgpt" }, {
    menu: [{ name: "route", ready: true }],
    pieces: [{ piece: 1, text: "Fix add.", team: "route", jev: { status: "below_floor", label: "code", confidence: 0.3 },
      route: { skill: "follow_up", agent: "claude", checker: "chatgpt" }, needs_label: false, slots: {}, slot_map: null }] });
  assert.equal(plan.pieces[0].words, "follow-up: Claude, with memory");
  assert.equal(plan.pieces[0].needsLabel, false);
});

// Brief 29.1 (decisions 9, 21 and 28): versus on a project shows each candidate's files and tests; Land anyway in Needs you
import { candidateFiles, needsYou, versusBoard } from "../../static/app.js";

test("a versus card on a project shows each candidate's files and tests, and its files block waits for the pick", () => {
  const record = { mode: "on", versus: true, copy: true, state: "none", changed: [], candidates: {
    a: { changed: [{ path: "calc.py", status: "modified", plus: 1, minus: 1 }], tests: { outcome: "passed", command: ["python3", "-m", "unittest"] } },
    b: { changed: [], tests: null } } };
  const task = { ...base, preset: "versus", status: "returned", waiting_on: "pick", project: "sums", project_files: record };
  const show = { candidates: [{ letter: "a", builder: "claude", text: "A fixes add." }, { letter: "b", builder: "chatgpt", text: "B." }] };
  const board = versusBoard(task, show);
  assert.deepEqual(board.cards[0].files.files, [{ path: "calc.py", status: "modified", words: "modified · +1 −1" }]);
  assert.equal(board.cards[1].files.none, true);
  assert.equal(candidateFiles({ ...task, project_files: null }, "a"), null);
  const files = fileView(task);
  assert.equal(files.kind, "versus");
  assert.deepEqual(files.buttons, []);
});

test("Needs you offers Land anyway when the router does", () => {
  assert.equal(needsYou({ ...base, outcome: "failed_check", land_anyway: true }), "Land anyway?");
  assert.equal(needsYou({ ...base, outcome: "failed_check", land_anyway: false, fallback: { ok: false } }), null);
});

// Brief 29.1, /break-ui's fixes (findings 1-7 and the owner's four decisions of 27 Oct)
import { splitHandoff } from "../../static/app.js";

test("a versus candidate shows its first 12 files and how many more, each chip a path and its words", () => {
  const changed = Array.from({ length: 500 }, (_, i) => ({ path: `src/rules/rule_${String(i).padStart(3, "0")}.py`,
    status: "added", plus: 12, minus: 0 }));
  const task = { ...base, preset: "versus", waiting_on: "pick", project_files: { mode: "on", versus: true, candidates: {
    a: { changed, tests: { outcome: "failed", exit: 1 } }, b: { changed: [], tests: null } } } };
  const a = candidateFiles(task, "a");
  assert.equal(a.files.length, 12);
  assert.equal(a.more, 488);
  assert.deepEqual(a.files[0], { path: "src/rules/rule_000.py", status: "added", words: "added · +12 −0" });
  assert.equal(a.none, false);
  assert.deepEqual(candidateFiles(task, "b"), { files: [], more: 0, none: true, tests: null });
});

test("a check's items keep the checker's own numbers, once; one note says so", () => {
  const passed = { ...base, outcome: "passed", notes: [{ n: 4, text: "One more source." }] };
  assert.deepEqual(checkItems(passed), { kind: "notes", title: "Show the note", folded: true,
    items: [{ n: 4, text: "One more source." }] });
  assert.equal(verdictLine(passed).text, "Passed · ChatGPT · 1 note");
  const failed = { ...base, outcome: "failed_check", open_musts: [{ n: 2, text: "Two." }, { n: 11, text: "Eleven." }] };
  assert.deepEqual(checkItems(failed).items.map((m) => m.n), [2, 11]);
});

test("a blocked verdict is one line; the Blocked offer holds what it needed", () => {
  const blocked = { ...base, status: "failed", outcome: "blocked", check_note: `blocked: ${"the committee's notes, ".repeat(12)}` };
  assert.equal(verdictLine(blocked).text, "Blocked · ChatGPT");
  assert.equal(verdictLine({ ...blocked, checker: null }).text, "Blocked");
  assert.match(blockedOffer(blocked).what, /^the committee's notes, the committee's notes,/);
});

test("a candidate's handoff section folds apart from its text, as the router splits it", () => {
  const text = "lend() refuses.\n\n## Handoff\n### Produced\nloans.py changed\n### Next\nPick one.";
  assert.deepEqual(splitHandoff(text), { body: "lend() refuses.", handoff: "## Handoff\n### Produced\nloans.py changed\n### Next\nPick one." });
  assert.deepEqual(splitHandoff("No section."), { body: "No section.", handoff: null });
  const fenced = "Code:\n```\n## Handoff\n```\nDone.";
  assert.deepEqual(splitHandoff(fenced), { body: fenced, handoff: null });
  assert.deepEqual(splitHandoff("A.\n## Handoff:\n### Next\nB.\n## Answered\n- 1: no"),
    { body: "A.\n## Answered\n- 1: no", handoff: "## Handoff:\n### Next\nB." });
  assert.equal(splitHandoff("A.\n### Handoff\nB.").handoff, null);
  const record = { mode: "on", versus: true, candidates: { a: { changed: [], tests: null }, b: { changed: [], tests: null } } };
  const task = { ...base, preset: "versus", status: "returned", waiting_on: "pick", project_files: record };
  const board = versusBoard(task, { candidates: [{ letter: "a", builder: "claude", text }, { letter: "b", builder: "chatgpt", text: "B." }] });
  assert.equal(board.cards[0].text, "lend() refuses.");
  assert.equal(board.cards[0].handoff, "### Produced\nloans.py changed\n### Next\nPick one.");
  assert.equal(board.cards[1].handoff, null);
});

// Brief 29.1, /break-ui's fold finding (the owner, 27 Oct): a poll draws every card again; each fold keeps its open state
import { foldOpen, foldToggled } from "../../static/app.js";

test("a card's folds stay as the owner left them across a redraw, each by its task and its own name", () => {
  let folds = new Set();
  folds = foldToggled(folds, "sr-1", "notes", true);
  folds = foldToggled(folds, "sr-1", "review-a", true);
  assert.equal(foldOpen(folds, "sr-1", "notes"), true);
  assert.equal(foldOpen(folds, "sr-2", "notes"), false);  // another task's notes stay shut
  assert.equal(foldOpen(folds, "sr-1", "review-b"), false);  // so does the other candidate's review
  const before = folds;
  folds = foldToggled(folds, "sr-1", "notes", false);
  assert.equal(foldOpen(folds, "sr-1", "notes"), false);
  assert.equal(foldOpen(folds, "sr-1", "review-a"), true);
  assert.equal(foldOpen(before, "sr-1", "notes"), true);  // a new set each time: the one a redraw read is never changed
  assert.equal(foldOpen(foldToggled(folds, "sr-1", "review-a", true), "sr-1", "review-a"), true);  // opened twice: still open
});
