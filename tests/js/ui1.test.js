// UI-1 (phase 1 of the UI rebuild, the owner's decisions of 1 Nov): the page only, restyled in place. Every pure function
// that existed stays; these test the new ones and the two Enter-safety rules (rows 16 and 17), row by row.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { confirmFocusId, autoStepLine, planStepLines, planNoteWords, fileView, cardLine, confirmWords, chipWords, cardMenuItems, cardKeepsRunAgain, cardMainAction, needsYouCut } from "../../static/app.js";

const JS = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const body = (name, size = 1800) => JS.slice(JS.indexOf(`function ${name}(`), JS.indexOf(`function ${name}(`) + size);

// ---------- row 17 (D6b): Enter on the Auto confirm keeps Auto off ----------

test("UI-1 row 17 (D6b): the Auto confirm's focus starts on Keep it off, never on the button that turns it on", () => {
  const flip = body("flipAuto", 1600);
  assert.match(flip, /querySelector\("#sheet \.auto-keep-off"\)/);  // UI-1 row 7 (D6a): on the sheet now
  assert.doesNotMatch(flip, /\.btn-primary"\)/);
  const el = body("autoConfirmEl", 2600);
  assert.match(el, /class: "btn btn-quiet auto-keep-off", type: "button", dataset: \{ focusKey: "auto-keep-off" \}/);
  assert.match(el, /onclick: \(\) => \{ if \(!off\) \{ confirmAuto\(\); closeSheet\(\); \} \} \}, "Turn Auto on"\)/);  // today's handler (row 7: on a sheet)
});

// ---------- row 16 (D14b): Enter on a Discard's confirm keeps the change ----------

test("UI-1 row 16 (D14b): Discard, Discard run, Cancel and Skip start on Keep it; a Land, an Undo and a pick start on Confirm", () => {
  const task = { task_id: "sr-1" };
  assert.equal(confirmFocusId(task, { action: "discard", task_id: "sr-1" }), "keep-sr-1");  // Discard, Discard run, Reject
  for (const action of ["land", "undo", "pick", "split_go"]) {  // UI A N4 (A10): Cancel, Skip, Neither and Reject join Discard
    assert.equal(confirmFocusId(task, { action, task_id: "sr-1" }), "confirm-sr-1", action);
  }
  for (const action of ["cancel", "split_skip"]) assert.equal(confirmFocusId(task, { action, task_id: "sr-1" }), "keep-sr-1", action);
  assert.equal(confirmFocusId(task, { action: "land", task_id: "sr-1", anyway: true }), "confirm-sr-1");
  assert.match(body("act", 900), /focusId\(confirmFocusId\(task, request\)\);/);
});

// ---------- row 14 (D3, D18): the project head on a title line and two lines ----------

test("UI-1 row 14 (D3, D18): the title line names the ~ path, cut from the middle; Project ▾ holds the rest with today's ids", () => {
  const stream = body("renderStream", 3600);
  assert.match(stream, /where \? middleTruncate\(where, 40\) : null, "HANDOFF\.md rides on every call"/);
  assert.match(stream, /title: where,/);  // the whole path on hover
  const bar = JS.slice(JS.indexOf("function projectBar("), JS.indexOf("function dropZone("));
  assert.match(bar, /open \? h\("div", \{ class: menuListClass\(PROJECT_MENU, "down"\), role: "menu", "aria-label": "Project" \}, secrets, ideas, notes, handoff, testsSet, run\.set, add\)/);
  assert.match(bar, /setChildren\(bar, projectTestButton\(project\), run\.line, plan,/);  // line 2: Test, Run/Stop, Plan #n
  assert.match(bar, /files\.tone === "ok" \? null :/);  // "File mode on" is hidden; off shows with its reason
  assert.match(bar, /dataset: \{ focusKey: PROJECT_MENU \}/);  // the opener has no id: auto34's id list holds
});

// ---------- row 13 (D4, D5): the Auto run as a list ----------

test("UI-1 row 13 (D5): a step line takes its text from the run's plan, else Step k, and says the check in words", () => {
  const plan = [{ k: 1, text: "Make the skeleton." }, { k: 2, text: "Add offer()." }];
  const passed = autoStepLine({ k: 1, state: "done", attempt: 1, team: "route", task_id: "sr-a", n: 62, outcome: "passed", verdict: "passed", calls: 2, covered: true }, plan);
  assert.equal(passed.text, "Make the skeleton.");
  assert.equal(passed.words, "passed · checked: ok");
  assert.equal(passed.team, "Route");
  assert.equal(passed.calls, "2 calls");
  assert.equal(passed.n, 62);
  const fixed = autoStepLine({ k: 2, state: "done", attempt: 1, outcome: "fixed", verdict: "fixed", calls: 4 }, plan);
  assert.equal(fixed.words, "fixed · check found an issue, fixed in round 2");
  const running = autoStepLine({ k: 3, state: "running", attempt: 1, verdict: "pending", calls: 0 }, plan);
  assert.equal(running.text, "Step 3");  // no plan text for it
  assert.equal(running.words, "running · check: not yet");
  assert.equal(running.calls, "0 calls");
  assert.equal(autoStepLine({ k: 1, state: "done", outcome: "unchecked", calls: 1 }, []).words, "unchecked · not checked");
  assert.equal(autoStepLine({ k: 1, state: "done", outcome: "unchecked", calls: 1 }, []).calls, "1 call");
  assert.equal(autoStepLine({ k: 1, state: "done", covered: false, calls: 0 }, plan).words, "done before the run · not part of it");
  assert.equal(autoStepLine({ k: 4, state: "open", calls: 0 }, null).words, "open · not started");
  assert.equal(autoStepLine({ k: 2, state: "done", attempt: 2, outcome: "passed", verdict: "passed" }, plan).attempt, "2 attempts");
});

test("UI-1 row 13 (D4): the run's card is one line per step, a summary, and Land the run on today's act()", () => {
  const el = body("autoBoardEl", 3200);
  assert.match(el, /const line = autoStepLine\(raw, planSteps\);/);
  assert.match(el, /project\.plan\.task_id === runPlan/);  // the plan's text only when it is the run's plan
  assert.match(el, /onclick: \(\) => act\(task, b\.request\)/);
  assert.doesNotMatch(el, /h\("table"/);
});

// ---------- row 12 (D16): the plan card, read first ----------

test("UI-1 row 12 (D16): a step reads as two quiet lines; no covers means no covers text at all", () => {
  const step = { k: 1, text: "Write the new footer", team: "route", doneWhen: "footer test passes", why: "the page needs the links first.",
    covers: "E2", calls: "3 calls" };
  assert.deepEqual(planStepLines(step), { one: "route · done when: footer test passes", two: "Why: the page needs the links first. · covers: E2 · 3 calls" });
  assert.deepEqual(planStepLines({ ...step, covers: null, calls: null }), { one: "route · done when: footer test passes", two: "Why: the page needs the links first." });
  assert.doesNotMatch(planStepLines({ ...step, covers: "none" }).two, /covers/);
});

test("UI-1 row 12 (D16): the note and the files line come from the server's paths and branch, a missing part left out", () => {
  const task = { mode: "plan", task_id: "sr-p", project_files: { mode: "on", state: "waiting", branch: "main", changed: [{ path: "docs/PLAN.md" }] } };
  assert.equal(planNoteWords(task), "Approve lands docs/PLAN.md as one commit on main; Reject drops it");
  assert.equal(planNoteWords({ project_files: { changed: [] } }), "Approve lands it as one commit; Reject drops it");
  assert.equal(fileView({ ...task, project: "p" }).line, "Files: docs/PLAN.md · waits for your approval");
  assert.equal(fileView({ ...task, project: "p", project_files: { ...task.project_files, changed: [] } }).line, "Files: waits for your approval");
  const card = body("planBoardCard", 9000);
  assert.match(card, /"Approve plan"\)/);
  assert.match(card, /planNoteWords\(task\)/);
  assert.doesNotMatch(card, /Approve lands docs\/PLAN\.md as one commit; Reject drops it/);  // no hard-coded note
});

// ---------- row 11 (D7): the card's one top line ----------

const CALLS = [
  { call_id: "c1", kind: "do", agent: "claude", status: "done", round_file: "tasks/x/1-build.md" },
  { call_id: "c2", kind: "check", agent: "chatgpt", status: "done", verdict: "PASS", round_file: "tasks/x/2-check.md" }];

test("UI-1 row 11 (D7), the small UI cleanup's row 3: a done Route card's row is its pills and its outcome, the notes counted", () => {
  const task = { task_id: "sr-a", n: 156, mode: "route", status: "done", outcome: "passed", agent: "claude", checker: "chatgpt",
    jev: { status: "ok", label: "write" }, created_at: "2026-11-01T10:00:00Z", updated_at: "2026-11-01T10:00:40Z" };
  const line = cardLine(task, { calls: CALLS });
  assert.equal(line.text, "passed");
  assert.deepEqual(line.pills.map((p) => p.text), ["✓ Build · Claude", "✓ Check · ChatGPT"]);
  assert.equal(line.tone, "ok");
  assert.deepEqual(line.files.map((f) => f.file), ["tasks/x/1-build.md", "tasks/x/2-check.md"]);  // for Details
  assert.equal(cardLine({ ...task, notes: ["a"] }, { calls: CALLS }).text, "passed · 1 note");
  assert.equal(cardLine(task, null).text, "passed");  // before its calls are read
  assert.deepEqual(cardLine(task, null).pills.map((p) => p.tone), ["muted", "muted"]);
});

test("UI-1 row 11 (D7), the small UI cleanup's row 3: a running card's pill says who is at work and, when asked, the time; a team's stages each in words", () => {
  const task = { task_id: "sr-b", n: 157, mode: "route", status: "sent", outcome: null, agent: "claude", created_at: "2026-11-01T10:00:00Z" };
  const show = { calls: [{ call_id: "c1", kind: "stage", role: "do", agent: "claude", status: "sent" }] };
  assert.equal(cardLine(task, show).pills[0].text, "Build · Claude, running");
  assert.equal(cardLine(task, show, { time: true, now: "2026-11-01T10:01:20Z" }).time, "1m 20s");
  const relay = { task_id: "sr-c", n: 158, mode: "relay", preset: "redteam", status: "done", outcome: "passed", agent: "claude" };
  const calls = [{ call_id: "a", kind: "stage", role: "build", agent: "claude", status: "done" },
    { call_id: "b", kind: "stage", role: "attack-1", agent: "grok", status: "done" },
    { call_id: "c", kind: "stage", role: "revise", agent: "claude", status: "failed" }];
  assert.deepEqual(cardLine(relay, { calls }).pills.map((p) => p.text), ["✓ Build · Claude", "✓ Attack · Grok Bot", "✗ Revise · Claude, failed"]);
  const second = [{ call_id: "d", kind: "stage", role: "attack2", agent: "cursor", status: "done" }];
  assert.equal(cardLine(relay, { calls: second }).pills[0].text, "✓ Attack · Cursor");  // a second attack reads as an attack
  const run = { task_id: "sr-r", n: 61, mode: "auto", status: "queued", outcome: null, auto: { state: "running", words: "Auto · step 3 of 4 · 4 of 29 calls", steps: [] } };
  assert.equal(cardLine(run, null).text, "Auto · step 3 of 4 · 4 of 29 calls");
  assert.equal(cardLine({ ...run, auto: { state: "stopped", words: "Auto stopped: the budget is reached", steps: [] } }, null).text, "Auto stopped: the budget is reached");
});

// ---------- row 10 (D14a): confirm words ----------

test("UI-1 row 10 (D14a): each confirm asks in words from the server's fields; the rest keep today's form", () => {
  const pf = { mode: "on", state: "waiting", branch: "main", changed: [{ path: "docs/PLAN.md" }], commit: "abc1234def" };
  const route = { task_id: "sr-r", n: 33, mode: "route", project_files: pf };
  assert.equal(confirmWords(route, { action: "land", task_id: "sr-r" }), "Land #33? Its change lands on main as one commit.");
  assert.equal(confirmWords(route, { action: "land", task_id: "sr-r", anyway: true }), "Land #33 anyway? Its check didn't pass; it lands on main as it is.");
  assert.equal(confirmWords(route, { action: "discard", task_id: "sr-r" }), "Discard #33's change? It never lands.");
  assert.equal(confirmWords(route, { action: "undo", task_id: "sr-r" }), "Undo #33? A new commit puts back abc1234.");
  const run = { task_id: "sr-a", n: 71, mode: "auto", auto: { state: "finished" }, project_files: pf };
  assert.equal(confirmWords(run, { action: "land", task_id: "sr-a" }), "Land run #71? The whole run lands on main as one commit.");
  assert.equal(confirmWords({ ...run, auto: { state: "stopped" } }, { action: "land", task_id: "sr-a" }), "Land run #71 so far? The steps it passed land on main as one commit.");
  assert.equal(confirmWords(run, { action: "discard", task_id: "sr-a" }), "Discard run #71? Its change never lands.");
  const plan = { task_id: "sr-p", n: 52, mode: "plan", project_files: pf };
  assert.equal(confirmWords(plan, { action: "land", task_id: "sr-p" }), "Approve plan #52? docs/PLAN.md lands on main as one commit.");
  assert.equal(confirmWords(plan, { action: "land", task_id: "sr-p", anyway: true }), "Approve plan #52 anyway? Its check didn't pass; docs/PLAN.md lands on main as it is.");
  assert.equal(confirmWords(plan, { action: "discard", task_id: "sr-p" }), "Reject plan #52? docs/PLAN.md is dropped; nothing lands.");
  assert.equal(confirmWords({ task_id: "x", n: 1 }, { action: "land", task_id: "x" }), "Land #1? Its change lands as one commit.");  // no branch sent
  assert.match(confirmWords(route, { action: "pick", choice: "a" }), /^Pick A for #\d+\?/);  // UI A row 13 (A10)
  assert.match(confirmWords(route, { action: "cancel" }), /^Cancel #\d+\? It stops, and nothing more is sent\.$/);
  assert.equal(confirmWords(route, { action: "resume" }), null, "Resume, Redo and Re-check open no confirm");
  assert.doesNotMatch(JS, /each asks once more/);
  assert.match(body("confirmRow", 1600), /confirmWords\(c\.task \|\| task, c\.request, state\.shows\.get\(task\.task_id\) \|\| null\)/);
});

// ---------- row 9 (D8): the sidebar ----------

test("UI-1 row 9 (D8): Waiting rows are muted and shown only when there are any; the open project scrolls into view once", () => {
  const side = body("renderSidebar", 9000);
  assert.match(side, /if \(needs\.router\.length\) \{/);
  assert.match(side, /class: "side-item waiting"/);
  assert.match(side, /state\.sideScrolled !== state\.project/);
  assert.match(side, /scrollIntoView\(\{ block: "nearest" \}\)/);
  const history = body("settingsHistory", 900);  // UI B N4, N5: History's rows left for the Settings tab, with the same handlers
  assert.match(history, /openHistory/);
  assert.match(history, /openLogFiles/);
  assert.match(history, /status\.report_path \? row\(/);
});

// ---------- row 8 (D12): the status chip ----------

const A = (name, extra = {}) => ({ name, online: true, available: true, ...extra });
const DOWN = { signed_out: { available: false, why_code: "signed_out" }, setup: { available: false, why_code: "not_configured" },
  probe: { available: false, why_code: "probe_failed" } };

test("UI-1 row 8 (D12): the chip counts what can work now and names the most fixable problem", () => {
  const jev = { configured: true, over_cap: false };
  const up = { agents: [A("claude"), A("chatgpt"), A("grok"), A("cursor")], jev };
  assert.deepEqual([chipWords(up).text, chipWords(up).tone], ["4 of 4 up", "none"]);
  const one = { agents: [A("claude"), A("chatgpt", DOWN.signed_out), A("grok"), A("cursor")], jev };
  assert.deepEqual([chipWords(one).text, chipWords(one).tone], ["3 of 4 up · ChatGPT signed out", "warn"]);
  const many = { agents: [A("claude"), A("chatgpt", DOWN.signed_out), A("grok", DOWN.setup), A("cursor", DOWN.probe)], jev: { configured: false } };
  assert.equal(chipWords(many).text, "1 of 4 up · ChatGPT signed out and 3 more");  // the demo's line: bad first, then muted, then Jev
  const zero = { agents: [A("claude", DOWN.signed_out), A("chatgpt", DOWN.setup)], jev };
  assert.deepEqual([chipWords(zero).text, chipWords(zero).tone], ["0 of 2 up · Claude signed out and 1 more", "bad"]);
  const setupFirst = { agents: [A("claude"), A("grok", DOWN.setup), A("cursor", DOWN.probe)], jev };
  assert.equal(chipWords(setupFirst).text, "1 of 3 up · Cursor off · safety check and 1 more");  // bad before muted
});

test("UI-1 row 8 (D12): Jev counts only when it blocks routing; Memory never counts", () => {
  const agents = [A("claude"), A("chatgpt")];
  assert.equal(chipWords({ agents, jev: { configured: false }, memory: { installed: false } }).text, "2 of 2 up · Jev not set up");
  assert.equal(chipWords({ agents, jev: { configured: true, over_cap: true } }).text, "2 of 2 up · Jev over its cap");
  assert.equal(chipWords({ agents, jev: { configured: true, over_cap: false }, memory: { installed: false } }).text, "2 of 2 up");
  assert.equal(chipWords({ agents, jev: null }).tone, "none");
});

test("UI-1 row 8 (D12), the small UI cleanup's row 6: the header keeps #strip; a box opens the popover, Esc closes it and focus goes back to that box", () => {
  const strip = body("renderStrip", 4200);
  assert.match(strip, /const chip = chipWords\(status, state\.tasks\);/);
  assert.match(strip, /role: "dialog", "aria-label": "Agent status"/);
  assert.match(strip, /openSetup\(item\.key\)/);  // a row's link: today's handler
  assert.match(body("onKey", 2600), /if \(state\.stripOpen\) \{ const box = `agent-box-\$\{state\.stripOpen\}`; state\.stripOpen = null; renderStrip\(\); focusId\(box\); return; \}/);
});

// ---------- row 7 (D6a): the Auto confirm as a sheet ----------

test("UI-1 row 7 (D6a): the confirm is a sheet with the router's words, Budget and First stop here; closing it is Keep it off", () => {
  const el = body("autoConfirmEl", 2600);
  assert.match(el, /text: `Turn Auto on for \$\{name\}\?`/);
  assert.match(el, /block\("What it runs", view\.words \|\| ""\)/);
  assert.match(el, /block\("Budget"/);
  assert.match(el, /block\("First stop here"/);
  assert.doesNotMatch(el, /view\.line/);  // no command line (D26)
  assert.doesNotMatch(el, /id: "/);
  const close = body("closeSheet", 1800);
  assert.match(close, /if \(auto\) state\.autoAsk = null;/);
  assert.match(close, /focusId\("auto-switch"\)/);
});


// ---------- row 6 (D15b): the 390 px pass ----------

test("UI-1 row 6 (D15b): at a phone's width Menu is the brand row's ☰, a 44 px target on today's toggleNav", () => {
  const CSS = readFileSync(new URL("../../static/app.css", import.meta.url), "utf8");
  const block = CSS.slice(CSS.indexOf("UI-1 row 6 (D15b)"));
  assert.match(block, /\.narrow-bar \.side-item\[aria-label="Menu"\] \{ width: 44px; min-width: 44px; min-height: 44px;/);
  assert.match(body("headNav", 900), /"aria-label": "Menu",\n\s+onclick: \(\) => toggleNav\(\) \}, icon\("menu"\)/);  // UI B N3: it left the sidebar for #strip
});

// ---------- row 5 (D2): the composer's look ----------

test("UI-1 row 5 (D2), UI A row 15: + holds its five items in a container with no id; the bar's ids keep their order", () => {
  const INDEX = readFileSync(new URL("../../static/index.html", import.meta.url), "utf8");
  const plus = INDEX.slice(INDEX.indexOf('<div class="plus">'), INDEX.indexOf('<button class="btn btn-primary btn-lg send"'));
  // UI A row 15 (A12): the paperclip, the skill and Web now come first, in + itself
  assert.deepEqual([...plus.matchAll(/id="([a-z-]+)"/g)].map((m) => m[1]).slice(0, 7), ["attach", "skill", "web-label", "web", "quick-label", "quick", "project"]);
  assert.doesNotMatch(plus.slice(0, plus.indexOf('<button class="plus-item attach"')), /id="/);  // neither + nor its menu has an id
  const CSS = readFileSync(new URL("../../static/app.css", import.meta.url), "utf8");
  assert.match(CSS, /#cmdline \{ display: none; \}/);
  assert.match(CSS, /#jev\[data-mode="idle"\] \{ display: none; \}/);  // "Jev isn't set up: pick the skill" still shows
  const composer = body("renderComposer", 9000);
  assert.match(composer, /UI-1 \(D2\): the spot for 33\.4's Draft it fill and its Text only pill/);
  assert.match(composer, /renderCommand\(\);\n  renderJev\(\);/);  // both still run
  assert.match(body("setPlus", 600), /\.hidden = !open;/);
});

// ---------- row 4 (D13): the card's ⋯ menu and its main action ----------

test("UI-1 row 4 (D13): ⋯ holds Run again as… and the card's quiet actions; a failed or blocked card keeps Run again out", () => {
  const done = { task_id: "sr-d", outcome: "passed", card_actions: { pin: true, save: true, forget: true } };
  assert.deepEqual(cardMenuItems(done).map((i) => i.key), ["again", "pin", "save", "forget"]);
  assert.equal(cardMenuItems(done)[0].label, "Run again as…");
  assert.deepEqual(cardMenuItems({ ...done, card_actions: { remember: true } }).map((i) => i.label), ["Run again as…", "Remember again"]);
  assert.deepEqual(cardMenuItems({ task_id: "sr-f", outcome: "failed_check", card_actions: { pin: true } }).map((i) => i.key), ["pin"]);
  assert.deepEqual(cardMenuItems({ task_id: "sr-b", outcome: "blocked" }).map((i) => i.key), ["again"]);  // UI A row 20 (A5)
  assert.equal(cardKeepsRunAgain({ outcome: "blocked" }), false);
  assert.deepEqual(cardMenuItems(null), []);
});

test("UI-1 row 4 (D13): the main action is picked from the views' own offers by a fixed priority, never rebuilt", () => {
  const pf = { mode: "on", state: "waiting", branch: "main", changed: [{ path: "a.py", plus: 1, minus: 0, status: "changed" }], copy: true };
  const land = cardMainAction({ task_id: "sr-l", n: 3, mode: "route", status: "done", outcome: "passed", project: "p", project_files: pf });
  assert.deepEqual(land, { key: "land", label: "Land", from: "files", request: { action: "land", task_id: "sr-l" } });
  const run = { task_id: "sr-a", n: 71, mode: "auto", status: "done", project: "p", auto: { state: "finished", steps: [], used: 1, budget: 2 },
    project_files: { ...pf } };
  assert.deepEqual(cardMainAction(run), { key: "land", label: "Land run", from: "auto", request: { action: "land", task_id: "sr-a" } });
  const redo = cardMainAction({ task_id: "sr-f", n: 4, mode: "route", status: "done", outcome: "failed_check", agent: "claude",
    fallback: { ok: true, agent: "chatgpt" } });
  assert.deepEqual([redo.key, redo.label, redo.from], ["fallback", "Redo with ChatGPT", "rescue"]);
  assert.equal(cardMainAction({ task_id: "sr-n", n: 5, mode: "route", status: "done", outcome: "passed" }), null);
  assert.equal(cardMainAction(null), null);
});

test("UI-1 row 4 (D13): ⋯ calls today's handlers; arrows move, and the old quiet buttons are gone from the card", () => {
  const menu = body("cardMenu", 2800);
  assert.match(menu, /notesAction\(task, item\)/);
  assert.match(menu, /runAgainItems\(task\)/);
  assert.match(menu, /onkeydown: menuArrows/);
  assert.match(body("runAgainItems", 2200), /runAgain\(task, chip\.key\)/);
  assert.doesNotMatch(JS, /notesActions\(task\)/);
  assert.match(body("onKey", 3000), /String\(state\.menu\)\.startsWith\("more-"\) \? state\.menu/);  // Esc: focus back to ⋯
});

// ---------- row 3 (D9): Needs you capped ----------

test("UI-1 row 3 (D9): Needs you shows its 3 newest rows and an n more row; the label keeps the full count", () => {
  const rows = Array.from({ length: 20 }, (_, i) => ({ n: 80 - i }));
  const cut = needsYouCut(rows, false);
  assert.equal(cut.label, "Needs you · 20");
  assert.deepEqual(cut.shown.map((r) => r.n), [80, 79, 78]);
  assert.equal(cut.more, 17);
  assert.deepEqual([needsYouCut(rows, true).shown.length, needsYouCut(rows, true).more], [20, 0]);
  assert.deepEqual(needsYouCut(rows.slice(0, 2), false), { label: "Needs you · 2", shown: rows.slice(0, 2), more: 0 });
  assert.deepEqual(needsYouCut(null), { label: "Needs you · 0", shown: [], more: 0 });
});

test("UI-1 row 3 (D9): the sidebar's middle is one scroll region; the top and the bottom group stay pinned", () => {
  const side = body("renderSidebar", 9000);
  assert.match(side, /const cut = needsYouCut\(needs\.you, state\.needsOpen\);/);
  assert.match(side, /list\.push\(\.\.\.pinned, h\("div", \{ class: "side-scroll" \}, middle\)\);/);
  assert.doesNotMatch(side, /class: "side-bottom"/);  // UI B N5: Notifications and Theme left for the Settings tab
});

// ---------- row 2 (D10): row heights ----------

test("UI-1 row 2 (D10): sidebar and menu rows are 36 px with a fine pointer and 44 px under a coarse one", () => {
  const CSS = readFileSync(new URL("../../static/app.css", import.meta.url), "utf8");
  const block = CSS.slice(CSS.indexOf("UI-1 row 2 (D10)"));
  assert.match(block, /\.sidebar \.side-item, \.menu-list \.side-item \{ min-height: 36px; \}/);
  assert.match(block, /@media \(pointer: coarse\) \{\n  \.sidebar \.side-item, \.sidebar \.narrow-bar \.side-item, \.menu-list \.side-item \{ min-height: 44px; \}/);
});

// ---------- row 1 (D15a): the light accent ----------

test("UI-1 row 1 (D15a): light gets its own accent fill, white on #0a7d63 (5.09:1); dark keeps its own", () => {
  const CSS = readFileSync(new URL("../../static/app.css", import.meta.url), "utf8");
  const light = CSS.slice(CSS.indexOf("@media (prefers-color-scheme: light)"), CSS.indexOf("*, *::before"));
  assert.equal((light.match(/--accent: #0a7d63; --accent-ink: #ffffff;/g) || []).length, 2);  // auto light and the toggle's light
  assert.match(CSS.slice(0, CSS.indexOf("@media (prefers-color-scheme: light)")), /--accent: #6ee7c7; --accent-ink: #0b0c0f;/);
  const lum = (hex) => { const f = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
    const [r, g, b] = [0, 2, 4].map((i) => f(parseInt(hex.slice(i, i + 2), 16) / 255)); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const ratio = (lum("ffffff") + 0.05) / (lum("0a7d63") + 0.05);
  assert.ok(ratio >= 4.5, `white on #0a7d63 is ${ratio.toFixed(2)}:1`);
  assert.equal(ratio.toFixed(2), "5.09");
});
