// Build brief UI A: the cards, the composer and the boards, row by row, on the demo's own tasks. Fake data.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { loadPage } from "./pagedom.js";
import * as app from "../../static/app.js";

const read = (name) => JSON.parse(readFileSync(new URL(`../../demo/${name}`, import.meta.url), "utf8"));
const STATUS = read("status.json");
const LOG = read("log.json");
const CSS_TEXT = readFileSync(new URL("../../static/app.css", import.meta.url), "utf8");
const SOURCE = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const INDEX = readFileSync(new URL("../../static/index.html", import.meta.url), "utf8");
const byN = (n) => LOG.tasks.find((t) => t.n === n);
const PROJECT = STATUS.projects[0].name;
const UP = { ...STATUS, jev: { ...STATUS.jev, configured: true, available: true, why: null },
  presets: STATUS.presets.map((p) => ({ ...p, ready: true, why: null })), split: { ...STATUS.split, ready: true, why: null }, plan: { ...STATUS.plan, ready: true, why: null } };
const showOf = (n) => read(`tasks/${byN(n).task_id}.json`);
const stream = (page) => page.el("stream");
const runs = (page) => page.posts.filter((p) => p.path === "/api/run");

async function open(task, { status = STATUS, show = null, ...options } = {}) {
  const page = await loadPage(options);
  Object.assign(page.state, { status, project: task.project || null, chat: task.chat || null, tasks: [task] });
  if (show) page.state.shows.set(task.task_id, show);
  page.renderStream();
  return page;
}

// ---- N1: the 6-line box ----

test("N1: the box grows to 6 lines, then scrolls: its CSS cap is 6 lines, no 40vh", () => {
  const rule = CSS_TEXT.match(/\.composer textarea \{[^}]*\}/)[0];
  assert.match(rule, /max-height: calc\(6 \* 1\.5em \+ 12px\)/);
  assert.doesNotMatch(rule, /40vh/);
});

// ---- N2: the state frames ----

test("N2: cardFrame on the demo's tasks, each row of A3's table and what the brief fills in", () => {
  const frames = { 3: "bad", 32: "bad", 68: "bad", 16: "bad", 74: "bad",                // failed, Grok overdue
    43: "warn", 26: "warn", 11: "warn", 12: "warn", 75: "warn", 17: "warn", 30: "warn", 67: "warn",  // blocked, unchecked, stopped, Grok waiting, Jev floor, a run stopped
    61: "info", 64: "info", 14: "info", 35: "info",                                       // running, a split on its pieces
    33: "grey", 38: "grey", 45: "grey", 5: "grey", 8: "grey", 13: "grey", 34: "grey", 41: "grey", 53: "grey", 52: "grey", 59: "grey", 71: "grey" };  // ready to land, a pick, a plan, No split, One step
  for (const [n, frame] of Object.entries(frames)) assert.equal(app.cardFrame(byN(Number(n))), frame, `#${n}`);
  for (const n of [1, 2, 4, 15, 6, 7, 18, 28, 29, 42, 58]) assert.equal(app.cardFrame(byN(n)), null, `#${n}`);
});

test("N2: No split and One step read grey, though their outcome is stopped", () => {
  assert.equal(byN(41).outcome, "stopped");
  assert.equal(byN(53).outcome, "stopped");
  assert.equal(app.cardFrame({ ...byN(41) }), "grey");
  assert.equal(app.cardFrame({ ...byN(53) }), "grey");
  assert.equal(app.cardFrame({ ...byN(41), no_split: null }), "warn", "a stopped task with no answer is amber");
});

test("N2: the cases the demo has no sample of", () => {
  const base = { task_id: "sr-1", n: 1, mode: "route", status: "returned", outcome: null };
  assert.equal(app.cardFrame({ ...base, waiting_on: "grok", check_note: null }), "info", "Grok before the router writes its note");
  assert.equal(app.cardFrame({ ...base, waiting_on: "answers" }), "grey");
  assert.equal(app.cardFrame({ ...base, waiting_on: "memory" }), "info");
  assert.equal(app.cardFrame({ ...base, waiting_on: "probe" }), "info");
  assert.equal(app.cardFrame({ ...base, outcome: "returned", reason_code: "not_routed" }), "warn", "Send as");
  assert.equal(app.cardFrame({ ...base, outcome: "returned", reason_code: "not_routed", answered_by: "sr-2" }), null);
  assert.equal(app.cardFrame({ ...base, mode: "plan", status: "done", waiting_on: "land", check_state: "failed" }), "bad", "a plan whose check failed");
  assert.equal(app.cardFrame({ ...base, mode: "plan", status: "done", outcome: "failed_check", land_anyway: true }), "bad");
  assert.equal(app.cardFrame({ ...base, mode: "auto", auto: { state: "landed" }, outcome: "passed" }), null);
  for (const state of ["landed", "discarded", "undone"]) {
    assert.equal(app.cardFrame({ ...base, status: "done", outcome: "failed_check", project_files: { state } }), null, state);
  }
  assert.equal(app.cardFrame({ ...base, status: "cancelled", outcome: "cancelled" }), null);
  assert.equal(app.cardFrame({ ...base, status: "failed", outcome: "timed_out" }), null);
});

test("N2: the card draws its frame as a class; a quick answer draws none", async () => {
  const page = await open(byN(3));
  assert.ok(stream(page).querySelector("article.task").classList.contains("frame-bad"));
  const quick = await open(byN(4));
  const card = stream(quick).querySelector("article.task");
  assert.ok(!["frame-bad", "frame-warn", "frame-info", "frame-grey"].some((c) => card.classList.contains(c)));
});

test("N2: Blocked, a plan limit and a process that ended read amber on the top line", () => {
  assert.equal(app.verdictLine(byN(43)).tone, "warn");
  assert.equal(app.verdictLine(byN(11)).tone, "warn");
  assert.equal(app.verdictLine(byN(12)).tone, "warn");
  assert.equal(app.verdictLine(byN(3)).tone, "bad", "every other top line keeps its colour");
});

test("N2: frames use the page's tokens, and a framed card's own offer drops its outline", () => {
  for (const [name, token] of [["bad", "--bad-line"], ["warn", "--warn-line"], ["info", "--info-line"], ["grey", "--line-3"]]) {
    assert.match(CSS_TEXT, new RegExp(`\\.task\\.frame-${name} \\{[^}]*var\\(${token}\\)`), name);
  }
  assert.match(CSS_TEXT, /\.task\.framed > \.offer \{[^}]*box-shadow: none/);
});

// ---- N3: one bright button (A1, A2) ----

const brightOn = (card) => {  // an open confirm's Confirm and an open editor's Save don't count, as today
  return card.querySelectorAll(".btn-primary").filter((b) => !b.closest(".confirm") && !b.closest(".edit-field"));
};

test("N3: at most one bright button on every one of the 75 demo cards; Versus's Pick A and B the one exception", async () => {
  const page = await loadPage();
  Object.assign(page.state, { status: UP, view: "history", historyTasks: LOG.tasks, tasks: LOG.tasks });
  for (const t of LOG.tasks) page.state.shows.set(t.task_id, read(`tasks/${t.task_id}.json`));
  page.renderStream();
  const cards = stream(page).querySelectorAll("article.task");
  assert.equal(cards.length, 75);
  for (const card of cards) {
    const task = LOG.tasks.find((t) => t.task_id === card.dataset.task);
    const bright = brightOn(card).map((b) => b.textContent);
    if (task.preset === "versus" && task.waiting_on === "pick") assert.deepEqual(bright, ["Pick A", "Pick B"], `#${task.n}`);
    else assert.ok(bright.length <= 1, `#${task.n}: ${bright.join(", ")}`);
  }
});

test("N3: cardMainAction's table", () => {
  const key = (n, extra = {}, show = showOf(n)) => { const m = app.cardMainAction({ ...byN(n), ...extra }, show); return m && m.key; };
  assert.equal(key(32), null, "Land anyway is never main");
  assert.equal(key(3), "fallback", "off a project, Redo stays bright");
  assert.equal(key(33), "land");
  assert.equal(key(58), null, "Undo stays plain");
  assert.equal(key(67), null, "Land the run so far stays plain");
  assert.equal(key(71), "land", "Land run");
  assert.equal(key(45), "pick");
  assert.deepEqual(app.cardMainAction(byN(45), showOf(45)).choices, ["a", "b"]);
  assert.equal(key(8), null, "a tie's picks are plain");
  assert.equal(key(34), "approve_split");
  assert.equal(key(41), null, "Route it stays plain");
  assert.equal(key(53), "build_it");
  assert.equal(key(43), "run_again");
});

test("N3: Land anyway has the red outline and isn't bright; a tie's picks are plain", async () => {
  const page = await open(byN(32), { show: showOf(32) });
  const land = page.el(`act-${byN(32).task_id}-land_anyway`);
  assert.ok(land.classList.contains("btn-danger"));
  assert.ok(!land.classList.contains("btn-primary"));
  const tie = await open(byN(8), { show: showOf(8) });
  assert.equal(brightOn(stream(tie).querySelector("article.task")).length, 0);
});

// ---- N4: focus starts on Keep it (A10) ----

test("N4: Keep it on Neither, Cancel, Skip, a split's Reject and Discard; Confirm on a pick and on Approve and run", () => {
  const task = { task_id: "sr-1" };
  const start = (request) => app.confirmFocusId(task, request);
  assert.equal(start({ action: "pick", choice: "none" }), "keep-sr-1");
  assert.equal(start({ action: "cancel" }), "keep-sr-1");
  assert.equal(start({ action: "split_skip" }), "keep-sr-1");
  assert.equal(start({ action: "split_go", choice: "n" }), "keep-sr-1");
  assert.equal(start({ action: "discard" }), "keep-sr-1");
  for (const choice of ["a", "b", "c"]) assert.equal(start({ action: "pick", choice }), "confirm-sr-1", choice);
  assert.equal(start({ action: "split_go", choice: "y" }), "confirm-sr-1");
  assert.equal(start({ action: "land" }), "confirm-sr-1");
  assert.equal(start({ action: "undo" }), "confirm-sr-1");
});

test("N4: a floor card's Cancel and a questions card's Cancel both send cancel, so both start on Keep it", () => {
  assert.equal(app.floorView(byN(17), STATUS).cancel.action, "cancel");
  assert.equal(app.confirmFocusId(byN(17), app.floorView(byN(17), STATUS).cancel), `keep-${byN(17).task_id}`);
});

// ---- N5: Run again on text-only cards (A11) ----

const TEXT_ONLY = { task_id: "sr-text", n: 156, mode: "route", status: "done", outcome: "passed", project: PROJECT, text: "Draft the spec.",
  text_only: true, result: "A draft.", save_spec: { path: "SPEC.md" }, card_actions: [], next: [], created_at: "2026-11-03T10:00:00Z" };
const menuItems = (page) => stream(page).querySelectorAll('[role="menuitem"]');

async function againMenu(status = UP, task = TEXT_ONLY) {
  const page = await open(task, { status });
  stream(page).querySelector(".more-btn").click();
  page.find("Run again as…", stream(page)).click();
  return page;
}

test("N5: every item on a text-only card fills the box with its team and sends nothing", async () => {
  for (const [label, team] of [["Route: text only, in the box", "route"], ["Collab: in the box", "collab"], ["Redteam: in the box", "redteam"], ["Plan: in the box", "plan"], ["Split: in the box", "split"]]) {
    const page = await againMenu();
    const item = page.find(label, stream(page));
    assert.ok(item, `${label}: ${menuItems(page).map((n) => n.textContent).join(" | ")}`);
    assert.equal(item.disabled, false, label);
    item.click();
    await page.settle();
    assert.equal(page.state.text, TEXT_ONLY.text, label);
    assert.equal(page.state.team, team, label);
    assert.equal(page.state.project, PROJECT, label);
    assert.deepEqual(runs(page), [], `${label} sends nothing`);
    assert.equal(page.el("textonly-pill").hidden, team !== "route", `${label}: the Text only pill on Route alone`);
    assert.equal(page.state.noFiles, team === "route", label);
  }
});

test("N5, the small UI cleanup's row 10: Plan isn't greyed on a text-only card, or on any other card with a project", async () => {
  const page = await againMenu();
  assert.equal(page.find("Plan: in the box", stream(page)).disabled, false);
  const other = await againMenu(UP, { ...TEXT_ONLY, text_only: false, save_spec: null });
  assert.equal(other.find("Plan: a new task", stream(other)).disabled, false);
});

test("N5: runAgainFill takes a team, Route by default, with noFiles on Route alone", () => {
  assert.deepEqual([app.runAgainFill(TEXT_ONLY).team, app.runAgainFill(TEXT_ONLY).noFiles], ["route", true]);
  assert.deepEqual([app.runAgainFill(TEXT_ONLY, "collab").team, app.runAgainFill(TEXT_ONLY, "collab").noFiles], ["collab", false]);
  assert.equal(app.runAgainFill({ ...TEXT_ONLY, text_only: false }, "collab"), null);
});

// ---- N6: Esc keeps a pick (A11) ----

const ASKING = { task_id: "sr-ask", n: 7, mode: "plan", status: "returned", waiting_on: "answers", project: PROJECT, text: "Plan it.", card_actions: [], next: [],
  created_at: "2026-11-03T10:00:00Z", questions: { k: 1, waiting: true, planning: false, answers: null,
    asked: [{ k: 1, text: "Which units?", guess: "B", options: [{ letter: "A", text: "Length" }, { letter: "B", text: "Weight" }] }] } };

test("N6: a pick, Other…, then Esc with nothing typed: the pick stays and the question counts as answered", async () => {
  const page = await open(ASKING);
  page.el("question-sr-ask-1-A").click();
  page.el("question-other-chip-sr-ask-1").click();
  assert.ok(page.el("question-other-sr-ask-1"));
  page.key("Escape");
  assert.ok(!page.el("question-other-sr-ask-1"));
  assert.equal(page.el("question-sr-ask-1-A").getAttribute("aria-pressed"), "true");
  assert.equal(page.el("send-answers-sr-ask").disabled, false);
});

test("N6: typing, then clearing the box, leaves the question unanswered: typing already replaced the pick", async () => {
  const page = await open(ASKING);
  page.el("question-sr-ask-1-A").click();
  page.el("question-other-chip-sr-ask-1").click();
  const box = page.el("question-other-sr-ask-1");
  box.value = "mine"; box.fire("input");
  box.value = ""; box.fire("input");
  assert.equal(page.el("question-sr-ask-1-A").getAttribute("aria-pressed"), "false");
  assert.equal(page.el("send-answers-sr-ask").disabled, true);
});

// ---- N7: numbered lists (A11) ----

test("N7: a list after text keeps its first number; a list starting at 1 has no start", () => {
  const blocks = app.markdown("1. a\n\ntext\n\n2. b\n3. c");
  assert.deepEqual(blocks.map((b) => b.type), ["ol", "p", "ol"]);
  assert.equal("start" in blocks[0], false);
  assert.equal(blocks[2].start, 2);
  assert.equal(blocks[2].items.length, 2);
});

test("N7: the card draws the list with its start", async () => {
  const page = await open({ ...byN(1), result: "1. a\n\ntext\n\n2. b" });
  const lists = stream(page).querySelectorAll(".result ol");
  assert.equal(lists.length, 2);
  assert.equal(lists[0].getAttribute("start"), null);
  assert.equal(lists[1].getAttribute("start"), "2");
});

// ---- N8: the "ask once more" line goes (A10) ----

test("N8: no such words in the page; the reason stays when Approve is off", async () => {
  assert.doesNotMatch(SOURCE, /ask once more/);
  const page = await open(byN(34), { show: { ...showOf(34), pieces: showOf(34).pieces.map((p, i) => (i ? p : { ...p, refused: { reason: "no agent" } })) } });
  assert.match(stream(page).querySelector(".plan-card").textContent, /Piece 1 can't run: no agent/);
});

// ---- N9: Redteam's false "fixed" (A17) ----

const ATTACKED = { preset: "redteam", task_id: "sr-red", n: 9, mode: "relay" };
const attackList = { attack_lists: [{ letter: "A", agent: "chatgpt", state: "ran" }], attacks: [{ label: "A1", severity: "high", text: "weak", answered: null, check: null },
  { label: "A2", severity: "low", text: "thin", answered: "not a flaw", check: null }] };

test("N9: with the attacks done and no revise call, Fix reads not answered yet; an answer still reads as the answer", () => {
  const show = { ...attackList, calls: [{ kind: "stage", role: "build", status: "done" }, { kind: "stage", role: "attack", status: "done" }] };
  assert.deepEqual(app.redteamBoard(ATTACKED, show).groups[0].findings.map((f) => f.fix), ["not answered yet", "answered: not a flaw"]);
});

test("N9: a revise call still out reads not answered yet; once it has ended, fixed", () => {
  const calls = (status) => [{ kind: "stage", role: "revise", status }];
  assert.equal(app.redteamBoard(ATTACKED, { ...attackList, calls: calls("sent") }).groups[0].findings[0].fix, "not answered yet");
  assert.equal(app.redteamBoard(ATTACKED, { ...attackList, calls: calls("done") }).groups[0].findings[0].fix, "fixed");
  assert.equal(app.redteamBoard(ATTACKED, { ...attackList, calls: calls("failed") }).groups[0].findings[0].fix, "fixed", "ended means its status isn't sent");
});

test("N9: a task from before brief 32 reads the same words, and the demo's finished #9 still reads fixed", () => {
  const old = { attacks: [{ n: 1, severity: "high", text: "weak", answered: null }] };
  assert.equal(app.redteamBoard(ATTACKED, { ...old, calls: [] }).findings[0].fix, "not answered yet");
  assert.equal(app.redteamBoard(ATTACKED, { ...old, calls: [{ role: "revise", status: "done" }] }).findings[0].fix, "fixed");
  assert.ok(app.redteamBoard(byN(9), showOf(9)).groups[0].findings.some((f) => f.fix === "fixed"));
});

// ---- N10: the ⋯ panel at 390 px (A20) ----

test("N10: at phone width the ⋯ menu is one fixed panel above the composer and the status bar; the base rule keeps its layer", () => {
  const phone = CSS_TEXT.match(/@media \(max-width: 600px\) \{\s*\.card-menu \.menu-list \{[^}]*\}/);
  assert.ok(phone, "a phone rule scoped to .card-menu");
  assert.match(phone[0], /position: fixed/);
  assert.match(phone[0], /bottom: var\(--composer-h, 0px\)/);
  assert.match(phone[0], /max-height: 60vh/);
  assert.match(phone[0], /overflow-y: auto/);
  assert.match(phone[0], /z-index: 26/, "above the status bar's 25");
  assert.match(CSS_TEXT, /\.menu-list \{ position: absolute; bottom: calc\(100% \+ 6px\); left: 0; z-index: 20;/);
  assert.match(SOURCE, /root\.setProperty\("--composer-h", `\$\{\$\("composer-area"\)\.offsetHeight\}px`\)/);
  assert.match(SOURCE, /heights\.observe\(\$\("composer-area"\)\)/);
});
// ---- N11: the ⌥ sheet, the keys and the IME check (A14) ----

const alt = (page, digit) => page.doc.body.fire("keydown", { key: "x", code: `Digit${digit}`, altKey: true, shiftKey: false, metaKey: false, ctrlKey: false, isComposing: false });

test("N11: the shortcuts sheet reads ⌥1 … ⌥8", async () => {
  const page = await open(byN(1));
  page.doc.body.fire("keydown", { key: "?", code: "Slash", shiftKey: true, altKey: false, metaKey: false, ctrlKey: false, isComposing: false });
  assert.match(page.el("sheet").textContent, /⌥1 … ⌥8/);
  assert.doesNotMatch(page.el("sheet").textContent, /⌥6/);
});

test("N11: ⌥8 on a project picks Plan; off one it says why", async () => {
  const page = await open({ ...byN(1), project: PROJECT }, { status: UP });
  page.doc.activeElement = page.doc.body;
  alt(page, 8);
  assert.equal(page.state.team, "plan");
  const off = await open(byN(1), { status: UP });
  off.doc.activeElement = off.doc.body;
  alt(off, 8);
  assert.equal(off.state.team, "route");
  assert.equal(off.el("toast").textContent, app.PLAN_OFF_PROJECT);
});

test("N11: through onKey: Enter in an IME composition never sends; Shift+Enter is a new line; ⌥ in a text field types; Esc goes back to Route", async () => {
  const page = await open(byN(1), { status: UP });
  const prompt = page.el("prompt");
  page.state.text = "x";
  const send = (init) => prompt.fire("keydown", { key: "Enter", code: "Enter", shiftKey: false, altKey: false, metaKey: false, ctrlKey: false, isComposing: false, ...init });
  assert.equal(send({ isComposing: true }).defaultPrevented, false);
  assert.equal(send({ keyCode: 229 }).defaultPrevented, false);
  assert.equal(send({ shiftKey: true }).defaultPrevented, false);
  assert.deepEqual(runs(page), []);
  const typed = prompt.fire("keydown", { key: "[", code: "Digit5", altKey: true, shiftKey: false, metaKey: false, ctrlKey: false, isComposing: false });
  assert.equal(typed.defaultPrevented, false, "⌥ in a text field types");
  page.state.team = "collab";
  page.key("Escape", page.doc.body);
  assert.equal(page.state.team, "route");
});

// ---- Row 21: failed card words (A4) ----

test("Row 21: the top line ends 'failed its check'; verdictLine and stateWords keep 'twice'", () => {
  assert.match(app.cardLine(byN(3), showOf(3)).text, /failed its check$/);
  assert.equal(app.verdictLine(byN(3)).text.startsWith("Failed twice"), true);
  assert.equal(app.stateWords(byN(3)), "failed its check twice");
});

test("Row 21: each must reads by the checker's own number", async () => {
  const page = await open({ ...byN(3), open_musts: [{ n: 4, text: "the link is dead" }] });
  const li = stream(page).querySelector(".check-items li");
  assert.equal(li.getAttribute("value"), "4");
  assert.equal(li.textContent, "the link is dead");
});

// ---- Row 20: Blocked card (A5) ----

test("Row 20: a blocked card has Run again; Run again as… moves into ⋯", async () => {
  const task = byN(43);
  const page = await open(task, { show: showOf(43) });
  const card = stream(page).querySelector("article.task");
  assert.equal(page.buttons("Run again as…", card).length, 0, "not on the card");
  assert.deepEqual(app.cardMenuItems(task).map((i) => i.key)[0], "again");
  assert.equal(app.cardKeepsRunAgain(task), false);
  assert.equal(app.cardKeepsRunAgain(byN(3)), true, "a failed card keeps it");
  const again = page.find("Run again", card);
  assert.ok(again.classList.contains("btn-primary"));
  again.click();
  assert.equal(page.state.text, task.text);
  await page.settle();
  assert.deepEqual(runs(page), []);
});

// ---- Row 19: running card (A7) ----

const after = (task, seconds) => new Date(Date.parse(task.created_at) + seconds * 1000).toISOString();

test("Row 19: a running team's line names what it's doing, with the time", () => {
  const task = byN(64);
  const line = app.cardLine(task, showOf(64), { time: true, now: after(task, 80) });  // the small UI cleanup, row 3: its running pill says it
  assert.equal(line.pills[0].text, "Build · Claude, running");
  assert.equal(line.time, "1m 20s");
});

test("Row 19: a running Route card has no doing words and no second time", () => {
  const task = { task_id: "sr-b", n: 157, mode: "route", status: "sent", outcome: null, agent: "claude", created_at: "2026-11-01T10:00:00Z", working: { agent: "claude", doing: null } };
  const show = { calls: [{ call_id: "c1", kind: "stage", role: "do", agent: "claude", status: "sent" }] };
  const line = app.cardLine(task, show, { time: true, now: after(task, 80) });  // the small UI cleanup, row 3
  assert.equal(line.text, "");
  assert.equal(line.pills[0].text, "Build · Claude, running");
  assert.equal(line.time, "1m 20s");
});

test("Row 19: the time shows on any running card, not only the newest; a waiting card keeps today's", async () => {
  const running = { task_id: "sr-b", n: 157, mode: "route", status: "sent", outcome: null, agent: "claude", created_at: "2026-11-01T10:00:00Z", working: { agent: "claude", doing: null }, text: "x", next: [] };
  const newer = { ...byN(1), n: 158, task_id: "sr-new", chat: null, project: null };
  const page = await loadPage();
  Object.assign(page.state, { status: UP, tasks: [running, newer], chat: null, project: null });
  page.renderStream();
  assert.match(page.el("card-sr-b").querySelector(".card-time").textContent, /\d/);  // the small UI cleanup, row 3: the time has its own place
});

test("Row 19: Cancel on a running card is the red outline with its confirm; on a wait it stays quiet; a run and its steps have none", async () => {
  const running = { task_id: "sr-b", n: 157, mode: "route", status: "sent", outcome: null, agent: "claude", created_at: "2026-11-01T10:00:00Z", working: { agent: "claude", doing: null }, text: "x", next: [] };
  assert.equal(app.rescueOffers(running).find((o) => o.key === "cancel").tone, "danger");
  assert.equal(app.rescueOffers(byN(75)).find((o) => o.key === "cancel").tone, "quiet");
  assert.equal(app.rescueOffers(byN(45)).find((o) => o.key === "cancel").tone, "quiet");
  assert.equal(app.rescueOffers(byN(61)).find((o) => o.key === "cancel"), undefined);
  assert.equal(app.rescueOffers(byN(64)).find((o) => o.key === "cancel"), undefined);
  const page = await open(running);
  const cancel = page.el("act-sr-b-cancel");
  assert.ok(cancel.classList.contains("btn-danger"));
  cancel.focus();
  cancel.click();
  await page.settle();
  assert.equal(page.doc.activeElement.id, "keep-sr-b");
});

// ---- Row 18: Unchecked's why (A6) ----

test("Row 18: an unchecked card shows the router's why under its top line; a quick answer doesn't", async () => {
  assert.equal(app.uncheckedWhy(byN(26)), byN(26).check_note);
  assert.equal(app.uncheckedWhy(byN(4)), null);
  assert.equal(app.uncheckedWhy(byN(1)), null);
  const page = await open(byN(26), { show: showOf(26) });
  const card = stream(page).querySelector("article.task");
  assert.equal(card.querySelector(".unchecked-why").textContent, byN(26).check_note);
  assert.ok(card.querySelector(".result"), "the answer stays open");
  const quick = await open(byN(4), { show: showOf(4) });
  assert.ok(!stream(quick).querySelector(".unchecked-why"));
  assert.match(app.verdictLine(byN(4)).text, /a quick answer needs no check/);
});

// ---- Row 17: stopped and Grok cards (A8) ----

const brightLabels = async (n) => {
  const page = await open(byN(n), { show: showOf(n) });
  return [page, brightOn(stream(page).querySelector("article.task")).map((b) => b.textContent)];
};

test("Row 17: overdue: Re-check bright, Cancel plain; waiting: Cancel plain; a stop: Resume bright", async () => {
  const [overdue, a] = await brightLabels(74);
  assert.deepEqual(a, ["Re-check"]);
  assert.ok(!overdue.el(`act-${byN(74).task_id}-cancel`).classList.contains("btn-danger"));
  assert.deepEqual((await brightLabels(75))[1], []);
  assert.match((await brightLabels(12))[1][0], /^Resume: /);
  const limit = (await brightLabels(11))[1];
  assert.ok(limit.length <= 1 && (!limit.length || /^Resume/.test(limit[0])), limit.join());
  assert.match(app.cardLine(byN(75), showOf(75)).text, /waiting on Grok · 6 min$/);
  assert.match(app.cardLine(byN(74), showOf(74)).text, /waiting on Grok · overdue, 12 min$/);
  assert.match(app.cardLine(byN(11), showOf(11)).text, /hit its plan limit$/);
  assert.match(app.cardLine(byN(12), showOf(12)).text, /its process ended$/);
});

// ---- Row 16: the split plan, read first (A18) ----

test("Row 16: each piece reads as one line, then its why and where it goes, quiet", async () => {
  const page = await open(byN(34), { show: showOf(34) });
  const card = stream(page).querySelector(".plan-card");
  const lines = card.querySelectorAll(".plan-read .plan-line").map((n) => n.textContent);
  assert.match(lines[0], /^Write a 100-word note.* · route · Jev label: writing$/);
  assert.match(lines[1], / · versus · Jev label: quick_answer · needs your pick$/);
  assert.equal(card.querySelectorAll("select").length, 0, "no select shows until Edit");
  assert.match(card.textContent, /Why: One short piece of writing/);
  assert.match(card.textContent, /writing · Claude, ChatGPT checks/);
  assert.match(card.querySelector(".count-line").textContent, /About 11 agent calls/);
});

test("Row 16: Edit opens one piece at a time, in the demo too with its controls off; Esc closes it and the focus returns", async () => {
  const page = await open(byN(34), { show: showOf(34) });
  page.state.demo = true;
  page.renderStream();
  const id = byN(34).task_id;
  const opener = (k) => stream(page).querySelectorAll("button").find((b) => b.dataset.focusKey === `piece-open-${id}:${k}`);
  opener(1).click();
  assert.ok(page.el(`team-${id}-1`));
  assert.equal(page.el(`team-${id}-1`).getAttribute("aria-disabled"), "true", "controls off in the demo");
  assert.ok(!page.el(`team-${id}-2`));
  assert.equal(page.doc.activeElement.id, `edit-${id}-1`);
  opener(2).click();
  assert.ok(!page.el(`team-${id}-1`));
  assert.ok(page.el(`team-${id}-2`));
  page.key("Escape");
  assert.ok(!page.el(`team-${id}-2`));
  assert.equal(page.doc.activeElement, opener(2));
});

test("Row 16: a needed skill select always shows, and so does Can't run", async () => {
  const show = showOf(34);
  const pieces = show.pieces.map((p, i) => (i === 0 ? { ...p, needs_label: true } : i === 1 ? { ...p, refused: { reason: "no agent" } } : p));
  const page = await open(byN(34), { show: { ...show, pieces } });
  const id = byN(34).task_id;
  assert.ok(page.el(`skill-${id}-1`));
  assert.match(stream(page).querySelector(".plan-card").textContent, /Can't run: no agent/);
});

test("Row 16: while an edit is open, another piece's Edit says so and opens nothing", async () => {
  const page = await open(byN(34), { show: showOf(34) });
  const id = byN(34).task_id;
  page.state.splitEdit = { taskId: id, piece: 1, text: "x" };
  page.renderStream();
  const other = stream(page).querySelectorAll("button").find((b) => b.dataset.focusKey === `piece-open-${id}:2`);
  assert.equal(other.getAttribute("aria-disabled"), "true");
  other.click();
  assert.ok(!page.el(`team-${id}-2`));
});

// ---- Row 15: a real + menu, with Project (A12) ----

async function composerPage({ status = STATUS, project = null, chat = "garden", team = "route" } = {}) {
  const page = await loadPage();
  Object.assign(page.state, { status, project, chat, team, tasks: [] });
  page.wire();
  page.renderComposer();
  page.renderTeam();
  return page;
}
const plusMenu = (page) => page.doc.querySelector(".plus-menu");
const plusNames = (page) => plusMenu(page).querySelectorAll(".plus-name").map((n) => n.textContent);
const openPlus = (page) => { page.doc.querySelector(".plus-btn").click(); };

test("Row 15: the menu's items, in order, with a divider before Project; + holds the attach, and the bar at rest is +, the team, Send", async () => {
  const page = await composerPage();
  assert.deepEqual(plusNames(page), ["Attach files", "Skill", "Web search", "Quick task", "Project"]);
  const kids = plusMenu(page).children;
  assert.ok(kids[kids.length - 2].classList.contains("plus-divider"));
  assert.ok(page.el("attach").closest(".plus-menu"));
  const bar = page.doc.querySelector(".composer-bar").children.filter((n) => !n.hidden).map((n) => n.id || n.className.split(" ")[0]);
  assert.deepEqual(bar, ["plus", "team", "send"]);
});

test("Row 15: each item says its state on its right; a greyed one says why in words", async () => {
  const page = await composerPage();
  const state = (id) => page.el(id).querySelector(".plus-state").textContent;
  assert.equal(state("web-label"), "Off");
  assert.equal(state("quick-label"), "Off");
  page.setTeam("collab");
  assert.equal(page.el("attach").disabled, true);
  assert.equal(state("attach"), "Files go on Route only");
  assert.equal(page.el("web").disabled, true);
  assert.equal(state("web-label"), "Off · Web goes on Route only");
  page.setTeam("split");
  assert.match(state("quick-label"), /A split never carries a chat tag/);
});

test("Row 15: the project row says why when its picker is greyed", async () => {
  const noProject = { ...UP, presets: UP.presets.map((p) => ({ ...p, project: false })) };
  const page = await composerPage({ status: noProject });
  page.setTeam(noProject.presets[0].name);
  assert.equal(page.el("project").disabled, true);
  assert.match(plusMenu(page).querySelector(".plus-project .plus-state").textContent, /takes no project/);
});

test("Row 15: arrows move through the items and skip greyed ones; Esc closes and focus returns to +", async () => {
  const page = await composerPage();
  page.setTeam("collab");  // Attach and Web greyed
  page.state.skill = null;
  openPlus(page);
  assert.equal(plusMenu(page).hidden, false);
  assert.equal(page.doc.activeElement.id, "quick", "the first item not greyed takes the focus");
  const down = page.doc.activeElement.fire("keydown", { key: "ArrowDown" });
  assert.equal(down.defaultPrevented, true);
  assert.equal(page.doc.activeElement.id, "project");
  page.doc.activeElement.fire("keydown", { key: "ArrowDown" });
  assert.equal(page.doc.activeElement.id, "quick", "it wraps, past the greyed ones");
  page.key("Escape");
  assert.equal(plusMenu(page).hidden, true);
  assert.equal(page.doc.activeElement, page.doc.querySelector(".plus-btn"));
});

test("Row 15: Attach files closes the menu and opens the file picker", async () => {
  const page = await composerPage();
  let picked = 0;
  page.el("file-input").click = () => { picked += 1; };
  openPlus(page);
  page.el("attach").click();
  assert.equal(picked, 1);
  assert.equal(plusMenu(page).hidden, true);
});

test("Row 15: the tag shows only when the send goes somewhere other than the view; Split's always shows", () => {
  const ctx = (o) => ({ kind: "chat", flag: "chat", value: "garden", ...o });
  assert.equal(app.contextTagWords(ctx(), "chat"), null);
  assert.equal(app.contextTagWords(ctx({ kind: "project", value: "seed" }), "project"), null);
  assert.equal(app.contextTagWords(ctx({ kind: "quick", value: null }), "quick"), null);
  assert.equal(app.contextTagWords(ctx(), "project"), "Chat: garden");
  assert.equal(app.contextTagWords(ctx({ value: null }), "quick"), "Chat: new");
  assert.equal(app.contextTagWords(ctx({ kind: "quick", value: null }), "chat"), "Quick task: untagged");
  assert.equal(app.contextTagWords(ctx(), "history"), "Chat: garden");
  assert.equal(app.contextTagWords(ctx({ kind: "split", value: null }), "chat"), "Split: untagged");
  assert.equal(app.contextTagWords(ctx({ kind: "split", value: "seed" }), "project"), "Split: project seed");
  assert.equal(app.contextTagWords(ctx({ kind: "plan", value: "seed" }), "project"), null);
  assert.equal(app.contextTagWords(ctx({ kind: "plan", value: null }), "chat"), "Plan: pick a project");
});

test("Row 15: the tag draws hidden at rest, and shows for a Split", async () => {
  const page = await composerPage();
  assert.equal(page.el("context-tag").hidden, true);
  page.setTeam("split");
  assert.equal(page.el("context-tag").hidden, false);
  assert.equal(page.el("context-tag").textContent, "Split: untagged");
});

// ---- Row 14: the Team menu (A14) ----

test("Row 14: the chip reads the team alone; the menu's list is the router's, with Models… last and the footer at its foot", async () => {
  const page = await composerPage();
  const chip = page.el("team-btn");
  assert.equal(chip.textContent.trim(), "Route");
  assert.doesNotMatch(chip.textContent, /Team:/);
  chip.click();
  const menu = page.el("team").querySelector(".team-menu");
  const names = menu.querySelectorAll(".name").map((n) => n.textContent);
  assert.deepEqual(names.slice(0, 1), ["Route"]);
  assert.ok(names.includes("Collab"));
  assert.equal(names[names.length - 1], "Models…");
  assert.equal(menu.lastElementChild.textContent, "Each team's chain shows on hover.");
  assert.match(CSS_TEXT, /\.team-item \{[^}]*min-height: 36px/);
  assert.match(CSS_TEXT, /@media \(pointer: coarse\) \{[^}]*\.team-item \{ min-height: 44px; \}/);
});

test("Row 14: the placeholder names the chain, so a phone reads it", () => {
  const preset = STATUS.presets.find((p) => p.name === "redteam");
  assert.ok(preset.chain && preset.description);
  assert.equal(app.placeholderFor("redteam", STATUS), `New task for Redteam: ${preset.chain}`);
});

// ---- Row 13: confirmWords for picks, Cancel, Skip and split (A10) ----

test("Row 13: each of A10's words", () => {
  const w = (n, request, show) => app.confirmWords(byN(n), request, show);
  const versus = byN(5);
  const a = versus.slots && versus.slots.a;
  assert.ok(a, "the slots hold the builders");
  assert.equal(w(5, { action: "pick", choice: "a" }, showOf(5)), `Pick A for #5? ${app.agentLabel(showOf(5).candidates[0].builder)}'s answer becomes the result.`);
  assert.equal(w(5, { action: "pick", choice: "none" }), "Close #5 with no pick? No answer is kept as the result.");
  assert.equal(w(8, { action: "pick", choice: "b" }, showOf(8)), "Pick B for #8? It's delivered unchecked.");
  assert.equal(w(8, { action: "pick", choice: "none" }), "Close #8 with no pick? No answer is kept as the result.");
  assert.equal(w(64, { action: "cancel" }), "Cancel #64? It stops, and nothing more is sent.");
  assert.equal(w(34, { action: "split_go", choice: "y" }, showOf(34)), `Run split #34? Its ${showOf(34).pieces.length} pieces start now.`);
  assert.equal(w(34, { action: "split_go", choice: "n" }, showOf(34)), "Reject split #34? Nothing runs.");
});

test("Row 13: on a project, a pick's change waits for you to land it", () => {
  assert.equal(byN(45).project != null, true);
  const words = app.confirmWords(byN(45), { action: "pick", choice: "a" }, showOf(45));
  assert.equal(words, `Pick A for #45? ${app.agentLabel(showOf(45).candidates[0].builder)}'s change waits for you to land it.`);
});

test("Row 13: Skip names the piece and its split, from the split's show", () => {
  const show = { pieces: [{ piece: 1, task_id: "sr-a" }, { piece: 2, task_id: "sr-b" }] };
  const split = { task_id: "sr-s", n: 35, mode: "split" };
  assert.equal(app.confirmWords(split, { action: "split_skip", task_id: "sr-b" }, show), "Skip piece 2 of split #35? The split goes on without it.");
  assert.equal(app.confirmWords(split, { action: "split_skip", task_id: "sr-b" }, null), "Skip this piece of split #35? The split goes on without it.");
});

test("Row 13: the words draw with the command as one muted line", async () => {
  const task = byN(8);
  const page = await open(task, { show: showOf(8), status: UP, answers: { "/api/command": { display: "sr pick sr-x b", copy: "sr pick sr-x b", parts: [] } } });
  page.find("Pick B", stream(page)).click();
  await page.settle();
  const confirm = stream(page).querySelector(".confirm");
  assert.equal(confirm.querySelector(".confirm-words").textContent, "Pick B for #8? It's delivered unchecked.");
  assert.ok(confirm.querySelector(".confirm-cmd"));
});

// ---- Row 12: Redteam summary and folding (A17) ----

test("Row 12: the summary counts the findings", () => {
  const group = (sevs) => ({ findings: sevs.map((severity) => ({ severity })) });
  assert.equal(app.redteamSummary({ groups: [group(["high", "medium", "low"]), group(["high", "medium"])], lines: [] }), "2 attacks, 5 findings: 2 high, 2 medium, 1 low");
  assert.equal(app.redteamSummary({ groups: [group(["low"])], lines: [] }), "1 attack, 1 finding: 1 low");
  assert.equal(app.redteamSummary({ findings: [{ severity: "high" }, { severity: "high" }] }), "1 attack, 2 findings: 2 high");
});

test("Row 12: folded under its summary once passed or fixed, staying as you left it; open while running or failed", async () => {
  const page = await open(byN(9), { show: showOf(9) });
  const board = () => stream(page).querySelector("details.redteam-fold");
  assert.ok(board(), "#9 passed: folded");
  assert.equal(board().getAttribute("open"), null);
  assert.match(board().querySelector("summary").textContent, /^\d+ attacks?, \d+ findings?: /);
  board().open = true;
  board().fire("toggle");
  page.renderStream();
  assert.notEqual(board().getAttribute("open"), null, "a refresh keeps it as you left it");
  const failed = await open(byN(68), { show: showOf(68) });
  assert.ok(!stream(failed).querySelector("details.redteam-fold"), "#68 failed: open");
  assert.match(stream(failed).querySelector(".redteam-summary").textContent, /^\d+ attacks?, /);
  assert.ok(stream(failed).querySelector(".redteam-table"));
});

test("Row 12: a task waiting to land reads check_state, not outcome; a plan keeps its board as it is", async () => {
  const show = showOf(9);
  const waiting = await open({ ...byN(9), status: "done", outcome: null, waiting_on: "land", check_state: "passed" }, { show });
  assert.ok(stream(waiting).querySelector("details.redteam-fold"));
  const running = await open({ ...byN(9), status: "queued", outcome: null, check_state: "pending" }, { show });
  assert.ok(!stream(running).querySelector("details.redteam-fold"));
  const plan = await open({ ...byN(9), mode: "plan", check_state: "passed" }, { show });
  assert.ok(!stream(plan).querySelector("details.redteam-fold"));
  assert.ok(!stream(plan).querySelector(".redteam-summary"));
});

// ---- Row 11: quiet states (A19) ----

test("Row 11: ready to land is the row's outcome; a plan and a run keep theirs; stateWords keeps its words", () => {
  assert.equal(app.cardLine(byN(33), showOf(33)).text, "ready to land");  // the small UI cleanup, row 3: the outcome alone
  assert.equal(app.cardLine(byN(38), showOf(38)).text, "ready to land");
  assert.doesNotMatch(app.cardLine(byN(52), showOf(52)).text, /ready to land/);
  assert.doesNotMatch(app.cardLine(byN(71), showOf(71)).text, /ready to land/);
  assert.equal(app.stateWords(byN(33)), "waiting for you to land or discard its change");
});

// ---- Row 10: sending and refused (A9) ----

test("Row 10: Sending is one line in a grey frame, no command", async () => {
  const page = await open(byN(1));
  page.state.pending.push({ run_id: "r1", pid: 1, text: "Hello there", team: "route", display: "sr route --json -- 'Hello there'" });
  page.state.pending.push({ run_id: "r2", pid: 2, text: "Team it", team: "collab", display: "sr relay collab -- 'Team it'" });
  page.renderStream();
  const cards = stream(page).querySelectorAll("article.sending");
  assert.deepEqual(cards.map((c) => c.textContent), ["Route · sending… Jev is labeling it", "Starting…"]);
  assert.ok(cards[0].classList.contains("frame-grey"));
  assert.equal(cards[0].getAttribute("title"), "Hello there", "the text stays on hover");
});

test("Row 10: Refused is a red frame, the router's words, the exit code, Dismiss and the command as one muted line; the reason code goes", async () => {
  const page = await open(byN(1));
  page.state.refused.push({ id: "x1", display: "sr route --json -- hi", exit: 2, envelope: { message: "The project's test command is not set.", reason_code: "project_busy", exit: 2 } });
  page.renderStream();
  const card = stream(page).querySelector("article.refusal");
  assert.ok(card.classList.contains("frame-bad"));
  assert.equal(card.getAttribute("role"), "alert");
  assert.match(card.textContent, /The router refused this send/);
  assert.match(card.textContent, /The project's test command is not set\./);
  assert.match(card.textContent, /Exit code 2/);
  assert.doesNotMatch(card.textContent, /project_busy/);
  assert.equal(card.querySelector(".confirm-cmd").textContent, "sr route --json -- hi");
  page.find("Dismiss", card).click();
  assert.ok(!stream(page).querySelector("article.refusal"));
});

test("Row 10: the other-agent buttons are plain, however many are offered", () => {
  assert.doesNotMatch(SOURCE.slice(SOURCE.indexOf("function refusalCard("), SOURCE.indexOf("async function resend(")), /btn-primary/);
});

// ---- Row 9: slots on their own line (A14) ----

test("Row 9: slots draw under the box, before the bar, only with a preset chosen; today's select ids", async () => {
  assert.ok(INDEX.indexOf('id="slots"') > INDEX.indexOf('id="prompt"'));
  assert.ok(INDEX.indexOf('id="slots"') < INDEX.indexOf('class="composer-bar"'));
  const page = await composerPage({ status: UP });
  assert.equal(page.el("slots").hidden, true);
  page.setTeam("redteam");
  assert.equal(page.el("slots").hidden, false);
  for (const slot of ["build", "attack", "attack2", "check"]) assert.ok(page.el("slots").querySelector(`#slot-${slot}`), slot);
  assert.ok(!page.el("team").querySelector(".team-slots"), "no longer beside the team");
  page.setTeam("route");
  assert.equal(page.el("slots").hidden, true);
});

test("Row 9: a left-out slot says why in words: a phone has no tooltip", async () => {
  const status = { ...UP, presets: UP.presets.map((p) => (p.name === "redteam" ? { ...p, filled: [{ slot: "attack2", agent: null, why: "Cursor isn't available (signed out)" }] } : p)) };
  const page = await composerPage({ status });
  page.setTeam("redteam");
  assert.match(page.el("slots").querySelector(".slot-why").textContent, /Left out: Cursor isn't available \(signed out\)/);
});

// ---- Row 8: Versus restyle (A16) ----

test("Row 8: each Pick sits inside its candidate, both bright; Neither plain, below; the head reads A · Claude", async () => {
  const page = await open(byN(45), { show: showOf(45) });
  const id = byN(45).task_id;
  const cands = stream(page).querySelectorAll(".cand");
  assert.equal(cands.length, 2);
  assert.equal(page.find("Pick A", cands[0]).id, `pick-${id}-a`);
  assert.equal(page.find("Pick B", cands[1]).id, `pick-${id}-b`);
  assert.ok(!page.find("Pick B", cands[0]));
  assert.ok(page.find("Pick A", cands[0]).classList.contains("btn-primary"));
  const neither = page.el(`pick-${id}-none`);
  assert.ok(!neither.closest(".cand"));
  assert.ok(!neither.classList.contains("btn-primary"));
  assert.equal(cands[0].querySelector(".cand-who").textContent, `A · ${app.agentLabel(showOf(45).candidates[0].builder)}`);
  assert.ok(cands[0].querySelector("details.review"), "the review stays folded under the answer");
});

test("Row 8: after a pick, today's fold, and no Pick buttons", async () => {
  const page = await open(byN(6), { show: showOf(6) });
  assert.ok(!page.find("Pick A", stream(page)));
  assert.match(stream(page).querySelector("details.fold summary").textContent, /Both candidates and their reviews/);
});

test("Row 8: Neither's confirm starts on Keep it, so Enter keeps it", async () => {
  const page = await open(byN(45), { show: showOf(45) });
  const id = byN(45).task_id;
  const neither = page.el(`pick-${id}-none`);
  neither.focus();
  neither.click();
  await page.settle();
  assert.equal(page.doc.activeElement.id, `keep-${id}`);
  page.doc.activeElement.click();
  assert.equal(page.state.confirm, null);
  assert.equal(page.doc.activeElement.id, `pick-${id}-none`, "the focus returns to Neither");
  assert.deepEqual(runs(page), []);
});

// ---- Row 7: split running marks (A18) ----

test("Row 7: each piece has its mark with its words kept, its #task linked", async () => {
  assert.deepEqual(["done", "waiting", "blocked", "skipped", null].map((s) => app.pieceMark(s)), ["✓", "●", "●", "○", "○"]);
  const page = await open(byN(35), { show: showOf(35) });
  const rows = stream(page).querySelectorAll(".split-pieces .piece");
  assert.match(rows[0].querySelector(".k").textContent, /^✓ 1 · #36$/);
  assert.match(rows[1].querySelector(".k").textContent, /^● 2 · #37$/);
  assert.match(rows[0].textContent, /passed/);
  assert.match(rows[1].textContent, /waits for your pick/);
  assert.equal(rows[0].querySelector(".k .linklike").textContent, "#36");
  assert.ok(page.find("Open #37", rows[1]), "Open #n stays");
});

test("Row 7: Cancel the split, a red outline, on a split waiting on its pieces", () => {
  const cancel = app.rescueOffers(byN(35)).find((o) => o.key === "cancel");
  assert.equal(cancel.label, "Cancel the split");
  assert.equal(cancel.tone, "danger");
  assert.equal(app.rescueOffers(byN(34)).find((o) => o.key === "cancel").label, "Cancel");
});

// ---- Row 6: Vote restyle (A16) ----

test("Row 6: a tie: tally 1 on each, the amber line, plain buttons, no bar, no confidence", async () => {
  const page = await open(byN(8), { show: showOf(8) });
  const body = stream(page).querySelector(".board-wrap");
  const cards = body.querySelectorAll(".vote-card");
  assert.equal(cards.length, 3);
  for (const card of cards) {
    assert.match(card.textContent, /tally: 1/);
    assert.doesNotMatch(card.textContent, /confidence/);
  }
  assert.equal(body.querySelector(".vote-tie").textContent, "Three answers, one each: a tie. Pick one, or Neither.");
  assert.ok(!body.querySelector(".tally-bar"));
  assert.equal(body.querySelectorAll(".btn-primary").length, 0);
  assert.match(cards[0].querySelector(".cand-who").textContent, /^A · /);
  assert.ok(page.el(`pick-${byN(8).task_id}-c`));
});

test("Row 6: with a winner: 2 of 3 agree, the why kept, no confidence", async () => {
  const page = await open(byN(7), { show: showOf(7) });
  const body = stream(page).querySelector(".board-wrap");
  assert.match(body.querySelector(".tally").textContent, /2 of 3 agree/);
  assert.doesNotMatch(body.textContent, /confidence/);
  assert.ok(!body.querySelector(".vote-tie"));
  assert.ok(body.querySelector(".tally-bar"));
  assert.equal(app.voteBoard(byN(7), showOf(7)).votes[0].confidence != null, true, "voteBoard keeps it in its data");
});

// ---- Row 5: pills above the box, Idea's words (A15) ----

test("Row 5: the pills sit in a row above the box, with no id; they've left the bar", () => {
  const row = INDEX.slice(INDEX.indexOf('<div class="composer-pills">'), INDEX.indexOf('<textarea id="prompt"'));
  assert.deepEqual([...row.matchAll(/id="([a-z-]+)"/g)].map((m) => m[1]), ["skill-pill", "from-pill", "idea-pill", "textonly-pill", "step-pill", "model-pills"]);
  assert.doesNotMatch(row.slice(0, row.indexOf('<span class="chip-tag pill-skill"')), /id="/);
  const bar = INDEX.slice(INDEX.indexOf('class="composer-bar"'), INDEX.indexOf("</footer>"));
  assert.doesNotMatch(bar, /id="from-pill"/);
});

test("Row 5: the Idea pill reads its words, cut at about 30 characters, the whole on hover; × stays", async () => {
  assert.equal(app.ideaPillWords({ id: 1, text: "footer copy" }), "Idea · footer copy");
  const long = "rewrite the whole footer copy for the investor page";
  assert.equal(app.ideaPillWords({ id: 1, text: long }), "Idea · rewrite the whole footer copy…");
  assert.equal(app.ideaPillWords({ id: 1 }), "Idea");
  const page = await composerPage();
  page.state.idea = { id: 1, text: long };
  page.renderComposer();
  const pill = page.el("idea-pill");
  assert.equal(pill.hidden, false);
  assert.equal(pill.getAttribute("title"), long);
  assert.equal(pill.children[0].textContent, "Idea · rewrite the whole footer copy…");
  assert.equal(pill.querySelector(".x").textContent, "×");
});

// ---- Row 4: Jev's line (A15) ----

test("Row 4: Jev's line in words, with the bar; under the floor it says you pick", async () => {
  const page = await composerPage({ status: UP });
  page.state.lastRouteTask = { jev: { status: "ok", label: "writing", confidence: 0.91 } };
  page.renderComposer();
  const jev = page.el("jev");
  assert.equal(jev.textContent, "Jev: writing, 0.91,above the 0.80 floor");
  assert.ok(jev.querySelector(".bar"));
  page.state.lastRouteTask = { jev: { status: "ok", label: "code", confidence: 0.5 } };
  page.renderComposer();
  assert.equal(jev.textContent, "Jev: code, 0.50,under the 0.80 floor: you pick");
  assert.ok(jev.classList.contains("under"));
});

test("Row 4: the other Jev states keep today's words", async () => {
  const page = await composerPage({ status: UP });
  page.setTeam("collab");
  assert.match(page.el("jev").textContent, /not asked: Collab names its own agents/);
});
// ---- Row 3: No split and One step cards (A18) ----

test("Row 3: No split has no sr route line; Route it is plain; a stopped-outcome answer's top line says what it is", async () => {
  const page = await open(byN(41), { show: showOf(41) });
  const card = stream(page).querySelector(".no-split");
  assert.ok(!card.querySelector(".offer-cmd"));
  assert.doesNotMatch(card.textContent, /sr route/);
  assert.ok(!page.el(`route-it-${byN(41).task_id}`).classList.contains("btn-primary"));
  assert.equal(app.cardLine(byN(41), showOf(41)).text, "no split · route it instead");  // the small UI cleanup, row 3: the outcome alone
  assert.equal(app.cardLine(byN(53), showOf(53)).text, "one step · build it instead");
  assert.doesNotMatch(app.cardLine(byN(53), showOf(53)).text, /stopped/);
});

test("Row 3: One step shows no calls figure, since the router sends none, and Build it is bright and sends nothing", async () => {
  const page = await open(byN(53), { show: showOf(53) });
  const card = stream(page).querySelector(".one-step-card");
  assert.doesNotMatch(card.textContent, /Calls/);
  const build = page.find("Build it", card);
  assert.ok(build.classList.contains("btn-primary"));
  build.click();
  await page.settle();
  assert.deepEqual(runs(page), []);
});
// ---- Row 2: attached-file chips (A15) ----

test("Row 2: attached files restyle in place, ids and handlers as they were", async () => {
  const page = await composerPage();
  page.state.files = [{ path: "/x/brand.pdf", name: "brand.pdf", size: 3 }];
  page.renderComposer();
  const chip = page.el("files").querySelector(".chip-tag");
  assert.match(chip.textContent, /brand\.pdf/);
  chip.querySelector(".x").click();
  assert.deepEqual(page.state.files, []);
  assert.match(CSS_TEXT, /\.composer-files \.chip-tag \{[^}]*var\(--fill\)/);
});

// ---- Row 1: Skill on any routed task (A13) ----

test("Row 1: with Jev on, a chosen skill goes with --skill; Auto sends none", () => {
  const ui = { team: "route", text: "x", chat: "garden", files: [], slots: {} };
  assert.equal(app.sendRequest({ ...ui, skill: null }, UP).skill, undefined);
  const key = UP.skills.find((s) => !(s.now && s.now.comes_back)).key;
  assert.equal(app.sendRequest({ ...ui, skill: key }, UP).skill, key);
  const choice = app.skillChoice({ ...ui, skill: key }, UP);
  assert.deepEqual([choice.chosen, choice.first, choice.greyed], [key, "Auto", null]);
  assert.equal(app.skillChoice({ ...ui, skill: null }, UP).chosen, null);
});

test("Row 1: off Route it's greyed, Route only, and sends no skill", () => {
  const key = UP.skills[0].key;
  const choice = app.skillChoice({ team: "collab", text: "x", skill: key }, UP);
  assert.deepEqual([choice.greyed, choice.chosen], ["Route only", null]);
  assert.equal(app.sendRequest({ team: "collab", text: "x", chat: "g", files: [], slots: {}, skill: key }, UP).skill, undefined);
});

test("Row 1: with Jev off: Pick one, and Send reads Send · pick a skill, as today", async () => {
  const choice = app.skillChoice({ team: "route", text: "x", skill: null }, STATUS);
  assert.equal(choice.first, "Pick one");
  assert.equal(app.skillPick({ team: "route", text: "x", skill: null }, STATUS).needed, true);
  const page = await composerPage();
  page.state.text = "x";
  page.renderComposer();
  assert.equal(page.el("send").textContent, "Send · pick a skill");
  assert.equal(page.el("skill").children[0].textContent, "Pick one");
});

test("Row 1: a skill that would come back says why; computer_use is left out", () => {
  const status = { ...UP, skills: [{ key: "writing", now: {} }, { key: "make_media", now: { comes_back: "needs Grok Bot", note: "needs Grok Bot" } },
    { key: "computer_use", now: { comes_back: "skill not routed in version 2" } }] };
  assert.deepEqual(app.skillChoice({ team: "route", text: "x" }, status).options.map((o) => o.label), ["writing", "make media (needs Grok Bot)"]);
});

test("Row 1: an @agent override leaves the skill out, and the pill hides while the text starts with one", async () => {
  const key = UP.skills.find((s) => !(s.now && s.now.comes_back)).key;
  const ui = { team: "route", text: "@claude do it", chat: "g", files: [], slots: {}, skill: key };
  assert.equal(app.sendRequest(ui, UP).skill, undefined);
  const page = await composerPage({ status: UP });
  Object.assign(page.state, { text: "plain words", skill: key });
  page.renderComposer();
  assert.equal(page.el("skill-pill").hidden, false);
  assert.match(page.el("skill-pill").textContent, new RegExp(`^Skill: ${key.replace(/_/g, " ")}`));
  page.state.text = "@claude do it";
  page.renderComposer();
  assert.equal(page.el("skill-pill").hidden, true);
});

test("Row 1: the pill's × goes back to Auto; so does a team or a view change; five items in + at rest", async () => {
  const key = UP.skills.find((s) => !(s.now && s.now.comes_back)).key;
  const page = await composerPage({ status: UP });
  assert.equal(page.doc.querySelector(".plus-skill").hidden, false);
  assert.equal(plusMenu(page).querySelector(".plus-skill .select").children[0].textContent, "Auto");
  Object.assign(page.state, { text: "x", skill: key });
  page.renderComposer();
  page.el("skill-pill").querySelector(".x").click();
  assert.equal(page.state.skill, null);
  page.state.skill = key;
  page.setTeam("collab");
  assert.equal(page.state.skill, null);
  assert.equal(page.el("skill").disabled, true);
  assert.equal(plusMenu(page).querySelector(".plus-skill .plus-state").textContent, "Route only");
});

test("Row 1: after Send it's back to Auto; the sending line and Jev's line don't say Jev is labeling", async () => {
  const key = UP.skills.find((s) => !(s.now && s.now.comes_back)).key;
  const page = await composerPage({ status: UP });
  Object.assign(page.state, { text: "x", skill: key });
  page.renderComposer();
  await page.send();
  assert.equal(page.state.skill, null);
  assert.equal(runs(page)[0].body.skill, key);
  assert.equal(page.state.pending[0].skill, key);
  assert.equal(stream(page).querySelector("article.sending").textContent, "Route · sending…");
  assert.doesNotMatch(page.el("jev").textContent, /asking Jev/);
});

test("Row 1: without a chosen skill the sending line still says Jev is labeling it", async () => {
  const page = await composerPage({ status: UP });
  page.state.text = "x";
  await page.send();
  assert.equal(stream(page).querySelector("article.sending").textContent, "Route · sending… Jev is labeling it");
  assert.match(page.el("jev").textContent, /asking Jev/);
});

// ---- UI A's live check: page bugs it found ----

test("the live check: Attach files sits at the row's start when it has no state to its right", () => {
  assert.match(CSS_TEXT, /\.plus-item\.attach \{ justify-content: flex-start; \}/);
});
