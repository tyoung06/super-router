// Build brief UI B: navigation, sheets and phone, row by row, on the demo's own tasks and the page's real markup. Fake data.
// A failing assert.equal(node, null) makes node print the whole fake page, so these read a boolean instead.
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
const PROJECT = STATUS.projects[0].name;
const stream = (page) => page.el("stream");
const runs = (page) => page.posts.filter((p) => p.path === "/api/run");

async function pageWith({ status = STATUS, project = null, chat = "garden", tasks = LOG.tasks, width = 1280, ...options } = {}) {
  const page = await loadPage(options);
  page.resize(width);
  Object.assign(page.state, { status, project, chat, tasks, team: "route" });
  page.wire();
  page.render();
  return page;
}

// ---- N1's lights: replaced by the small UI cleanup's boxes (row 6, note 26); tests/js/cleanup_ui.test.js holds each one ----

test("the boxes come from status: two agents show two, plus Jev and Memory, not a fixed five", async () => {
  const two = { ...STATUS, agents: STATUS.agents.slice(0, 2) };
  const page = await pageWith({ status: two });
  const boxes = page.el("strip").querySelectorAll(".agent-box");
  assert.equal(boxes.length, 4);
  assert.deepEqual(boxes.map((b) => b.querySelector(".agent-name").textContent), [...two.agents.map((a) => app.agentLabel(a.name)), "Jev", "Memory"]);
  const all = await pageWith();
  assert.equal(all.el("strip").querySelectorAll(".agent-box").length, STATUS.agents.length + 2);
});

test("a click on a box opens the popover, its head chipWords' text; Esc closes it and focus returns", async () => {
  const page = await pageWith();
  page.el("agent-box-chatgpt").click();
  const pop = page.el("strip").querySelector(".status-pop");
  assert.ok(pop);
  assert.equal(pop.querySelector(".status-head").textContent, app.chipWords(STATUS, LOG.tasks).text);
  assert.equal(pop.querySelectorAll(".status-row").length, STATUS.agents.length + 2);
  page.key("Escape", page.doc.body);
  assert.ok(!page.el("strip").querySelector(".status-pop"));
  assert.equal(page.doc.activeElement.id, "agent-box-chatgpt");
});

// ---- N2: the rail, and the sidebar hiding (Q6) ----

const rail = (page) => page.el("rail").querySelectorAll("button");

test("N2: four items, in order, outside the composer", async () => {
  const page = await pageWith();
  assert.deepEqual(rail(page).map((b) => b.textContent), ["New chat", "Chats", "Projects", "Settings"]);
  assert.ok(INDEX.indexOf('id="rail"') < INDEX.indexOf('id="sidebar"'));
  assert.match(INDEX, /<nav class="rail" id="rail"/);
});

test("N2: Chats or Projects opens the sidebar at that section; the lit icon hides it", () => {
  const next = (key, hidden, section) => app.railNext(key, { hidden, section });
  assert.deepEqual(next("chats", true, "projects"), { hidden: false, section: "chats" }, "hidden: opens at that section");
  assert.deepEqual(next("projects", false, "chats"), { hidden: false, section: "projects" }, "open on the other: moves");
  assert.deepEqual(next("projects", false, "projects"), { hidden: true, section: "projects" }, "the lit icon hides it");
});

test("N2: pressing the icons hides and opens the sidebar, and it's a class on the page", async () => {
  const page = await pageWith();
  const by = (t) => rail(page).find((b) => b.textContent === t);
  assert.equal(page.state.sideHidden, false);
  by("Chats").click();  // the view is a chat, so Chats is lit
  assert.equal(page.state.sideHidden, true);
  assert.ok(page.el("app").classList.contains("side-hidden"));
  by("Projects").click();
  assert.equal(page.state.sideHidden, false);
  assert.equal(page.state.sideSection, "projects");
  assert.equal(rail(page).find((b) => b.textContent === "Projects").getAttribute("aria-expanded"), "true");
  assert.ok(!page.el("app").classList.contains("side-hidden"));
  page.render();
  assert.equal(page.state.sideHidden, false, "kept across a redraw");
});

test("N2: the hidden state is remembered, read back, and the page works without localStorage", async () => {
  const stored = {};
  const page = await pageWith();
  globalThis.localStorage = { getItem: (k) => stored[k] ?? null, setItem: (k, v) => { stored[k] = v; }, removeItem() {} };
  rail(page).find((b) => b.textContent === "Chats").click();
  assert.equal(stored["sr-side-hidden"], "1");
  const again = await pageWith();
  globalThis.localStorage = { getItem: (k) => stored[k] ?? null, setItem: (k, v) => { stored[k] = v; }, removeItem() {} };
  again.readSidePrefs();
  assert.equal(again.state.sideHidden, true);
  const broken = await pageWith();
  globalThis.localStorage = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); }, removeItem() {} };
  broken.readSidePrefs();
  assert.equal(broken.state.sideHidden, false);
  rail(broken).find((b) => b.textContent === "Chats").click();
  assert.equal(broken.state.sideHidden, true, "still works, just isn't remembered");
});

test("N2: the rail shows above 900 px only; the page's grid makes room for it", () => {
  assert.match(CSS_TEXT, /@media \(min-width: 901px\) \{\s*\.app \{ grid-template-columns: 64px var\(--side-w\) minmax\(0, 1fr\); \}/);
  assert.match(CSS_TEXT, /\.app\.side-hidden \.sidebar \{ display: none; \}/);
  assert.match(CSS_TEXT, /@media \(max-width: 900px\) \{\s*\.rail \{ display: none; \}/);
});

// ---- N3: pinned Menu, phone top bar, drawer (Q6, Q11) ----

test("N3: Needs you shows in the head when narrow, or wide with the sidebar hidden, and only with something to do", () => {
  assert.equal(app.needsInHead(true, false, 2), true);
  assert.equal(app.needsInHead(false, true, 2), true);
  assert.equal(app.needsInHead(false, false, 2), false);
  assert.equal(app.needsInHead(true, true, 0), false);
});

test("N3: at 390 Menu sits in the strip and New chat is in its drawer; at 1280 New chat is on the rail", async () => {
  const narrow = await pageWith({ width: 390 });
  const strip = narrow.el("strip");
  const menu = strip.querySelector('[aria-label="Menu"]');
  assert.ok(menu, "Menu in #strip");
  assert.ok(!narrow.el("sidebar").querySelector('[aria-label="Menu"]'));
  assert.match(strip.textContent, /Needs you · \d+/);
  menu.click();
  assert.equal(narrow.state.navOpen, true);
  assert.ok(narrow.el("sidebar").classList.contains("open"));
  assert.ok(narrow.find("New chat", narrow.el("sidebar")), "the drawer's top");
  const rows = narrow.el("sidebar").querySelectorAll("button");
  assert.equal(rows[rows.length - 1].textContent, "Settings", "the drawer's foot");
  narrow.key("Escape", narrow.doc.body);
  assert.equal(narrow.state.navOpen, false);
  const wide = await pageWith();
  assert.ok(!wide.el("strip").querySelector('[aria-label="Menu"]'));
  assert.ok(wide.find("New chat", wide.el("rail")));
  assert.doesNotMatch(wide.el("strip").textContent, /Needs you/);
});

test("N3: wide with the sidebar hidden, Needs you · n joins the head, and pressing it opens the sidebar", async () => {
  const page = await pageWith();
  page.state.sideHidden = true;
  page.render();
  const needs = page.el("strip").querySelector(".needs-head");
  assert.match(needs.textContent, /Needs you · \d+/);
  needs.click();
  assert.equal(page.state.sideHidden, false);
  assert.ok(!page.el("strip").querySelector(".needs-head"));
});

test("N3: New chat is reachable at every width, and the drawer's rows show narrow only", () => {
  assert.match(CSS_TEXT, /\.side-only-narrow \{ display: none; \}/);
  assert.match(CSS_TEXT, /@media \(max-width: 900px\) \{[^@]*\.sidebar:not\(\.open\) \{ display: none; \}/);
  assert.match(CSS_TEXT, /\.sidebar\.open \.side-only-narrow \{ display: flex; \}/);
});

// ---- N4: sidebar sections (Q6) ----

const labels = (page) => page.el("sidebar").querySelectorAll(".side-label").map((n) => n.textContent.replace(/[▾▸]/g, "").trim());

test("N4: Needs you at the top; Waiting stays; Projects above Chats", async () => {
  const page = await pageWith();
  const words = labels(page);
  assert.ok(words.indexOf("Projects") < words.indexOf("Chats"), words.join());
  assert.match(words[0], /^Needs you/);
  const running = { ...LOG.tasks[0], task_id: "sr-w", n: 900, status: "sent", outcome: null, waiting_on: "memory" };
  const withWait = await pageWith({ tasks: [running, ...LOG.tasks] });
  assert.ok(labels(withWait).includes("Waiting on the router"));
});

test("N4: each of Projects and Chats folds, and a fold survives a reload", async () => {
  const stored = {};
  const stub = () => { globalThis.localStorage = { getItem: (k) => stored[k] ?? null, setItem: (k, v) => { stored[k] = v; }, removeItem() {} }; };
  const page = await pageWith();
  stub();
  const fold = (p, name) => p.el(`side-section-${name}`).querySelector(".side-fold");
  assert.equal(fold(page, "chats").getAttribute("aria-expanded"), "true");
  assert.ok(page.find(STATUS.projects[0].name, page.el("sidebar")) || page.el("sidebar").textContent.includes(STATUS.projects[0].name));
  fold(page, "projects").click();
  assert.equal(fold(page, "projects").getAttribute("aria-expanded"), "false");
  assert.ok(!page.el("sidebar").textContent.includes(STATUS.projects[0].name), "its rows are gone");
  assert.equal(JSON.parse(stored["sr-side-folds"]).projects, true);
  const again = await pageWith();
  stub();
  again.readSidePrefs();
  again.render();
  assert.equal(fold(again, "projects").getAttribute("aria-expanded"), "false");
  assert.equal(fold(again, "chats").getAttribute("aria-expanded"), "true");
});

test("N4: bad stored text is ignored", () => {
  assert.deepEqual(app.sideFolds("not json"), {});
  assert.deepEqual(app.sideFolds(null), {});
  assert.deepEqual(app.sideFolds("[1,2]"), {});
  assert.deepEqual(app.sideFolds('{"projects":"yes","chats":true,"evil":true}'), { chats: true });
});

test("N4: the rail opening a folded section unfolds it", async () => {
  const page = await pageWith();
  page.el("side-section-projects").querySelector(".side-fold").click();
  rail(page).find((b) => b.textContent === "Projects").click();
  assert.equal(page.el("side-section-projects").querySelector(".side-fold").getAttribute("aria-expanded"), "true");
});

// ---- N5: the Settings tab (Q6) ----

const tabs = (page) => stream(page).querySelectorAll('.settings-tabs [role="tab"]');
const tab = (page, name) => tabs(page).find((b) => b.textContent === name);

test("N5: Settings is a page in the main column, with five tabs; the rail opens it at Setup, and it's lit", async () => {
  const page = await pageWith();
  rail(page).find((b) => b.textContent === "Settings").click();
  assert.equal(page.state.view, "settings");
  assert.equal(page.el("sheet").hidden, true, "no sheet");
  assert.deepEqual(tabs(page).map((b) => b.textContent), ["Setup", "History", "Router notes", "Models", "Memory"]);
  assert.equal(tab(page, "Setup").getAttribute("aria-selected"), "true");
  assert.ok(rail(page).find((b) => b.textContent === "Settings").classList.contains("lit"));
  assert.equal(stream(page).querySelector(".stream-title").textContent, "Settings");
});

test("N5: openSetup(focus) lands on the tab holding that row", async () => {
  for (const [focus, name] of [["memory", "Memory"], ["models", "Models"], ["notes", "Router notes"], ["claude", "Setup"], [null, "Setup"]]) {
    const page = await pageWith();
    await page.openSetup(focus);
    assert.equal(page.state.view, "settings", String(focus));
    assert.equal(tab(page, name).getAttribute("aria-selected"), "true", String(focus));
  }
  assert.equal(app.settingsTabFor("git"), "setup");
});

test("N5: the moved rows keep their ids", async () => {
  const page = await pageWith();
  await page.openSetup("memory");
  assert.ok(page.el("setup-memory"));
  assert.ok(page.el("mem-switch"));
  await page.openSetup("models");
  assert.ok(page.el("setup-models"));
  assert.ok(page.el("fable-switch"));
  await page.openSetup("notes");
  assert.ok(page.el("setup-notes"));
  assert.ok(page.el("notes-edit"));
  await page.openSetup("claude");
  assert.ok(page.el("setup-claude"));
  assert.ok(page.el("check-again"));
  assert.ok(!page.el("setup-memory"), "Memory's row is on its own tab");
});

test("N5: Theme and Notifications work from the Setup tab, and the sidebar's foot is gone", async () => {
  globalThis.Notification = { permission: "granted" };
  const page = await pageWith();
  delete globalThis.Notification;
  globalThis.Notification = { permission: "granted" };
  await page.openSettings("setup");
  assert.ok(!page.el("sidebar").querySelector(".side-bottom"));
  const theme = stream(page).querySelector("#settings-theme");
  assert.match(theme.textContent, /Theme: auto/);
  theme.click();
  assert.match(stream(page).querySelector("#settings-theme").textContent, /Theme: dark/);
  assert.match(stream(page).querySelector("#settings-notify").textContent, /Notifications: on/);
  stream(page).querySelector("#settings-notify").click();
  assert.match(page.el("toast").textContent, /Notifications are on/);
  delete globalThis.Notification;
});

test("N5: History's three rows open their own views; Read the report only with report_path", async () => {
  const page = await pageWith({ status: { ...STATUS, report_path: "/x/report.md" } });
  await page.openSettings("history");
  const rows = stream(page).querySelectorAll(".settings-history button").map((b) => b.querySelector(".name").textContent);
  assert.deepEqual(rows, ["All tasks", "Log files", "Read the report"]);
  page.find("All tasks", stream(page)) || stream(page).querySelectorAll(".settings-history button")[0].click();
  assert.equal(page.state.view, "history");
  const none = await pageWith({ status: { ...STATUS, report_path: null }, answers: { "/api/logfiles": { folders: [], next_before: null } } });
  await none.openSettings("history");
  assert.equal(stream(none).querySelectorAll(".settings-history button").length, 2);
  await none.openSettings("history");
  stream(none).querySelectorAll(".settings-history button")[1].click();
  assert.equal(none.state.view, "logfiles");
  await none.settle();
});

test("N5: the tab has no Close; Esc doesn't leave it; New chat does; a Send from it goes to the chat", async () => {
  const page = await pageWith();
  await page.openSettings("setup");
  assert.ok(!stream(page).querySelector('[aria-label="Close"]'));
  page.key("Escape", page.doc.body);
  assert.equal(page.state.view, "settings");
  rail(page).find((b) => b.textContent === "New chat").click();
  assert.equal(page.state.view, "chat");
  const send = await pageWith({ status: { ...STATUS, jev: { ...STATUS.jev, available: true, configured: true } } });
  await send.openSettings("setup");
  send.state.text = "hello";
  await send.send();
  assert.equal(send.state.view, "chat");
});

test("N5: the words follow: Settings → Models, Settings has the steps", () => {
  assert.equal(app.FABLE_OFF_WHY, "Fable is off: turn it on in Settings → Models once usage credits are off on your account");
  assert.match(SOURCE, /"Settings has the steps"/);
  assert.doesNotMatch(SOURCE, /in Setup → Models|the Setup sheet has the steps/);
});

// ---- N6: Test, Run and Project on the What now? line; Project tools on a phone (Q4, Q11) ----

const LINE = { words: "Waiting on you: #156", control: "open", task_id: "sr-x", n: 156 };

async function projectPage(width) {
  const page = await pageWith({ project: PROJECT, chat: null, width, tasks: [] });
  page.state.whatNow = { project: PROJECT, line: LINE };
  page.renderStream();
  return page;
}

test("N6: at phone width the bar folds into Project tools, whatever the head's height; What now? still shows, outside it", async () => {
  const page = await projectPage(390);
  assert.ok(page.el("project-tools"), "the button");
  assert.equal(page.el("project-bar").hidden, true);
  assert.ok(page.el("what-now"));
  assert.ok(!page.el("project-bar").contains(page.el("what-now")));
  page.el("project-tools").click();
  assert.equal(page.el("project-bar").hidden, false);
  assert.equal(page.el("project-tools").getAttribute("aria-expanded"), "true");
});

test("N6: wide, the bar stays open on a short head, and shares What now?'s line by CSS, ids and order as they were", async () => {
  const page = await projectPage(1280);
  assert.ok(!page.el("project-tools"));
  assert.equal(page.el("project-bar").hidden, false);
  const kids = stream(page).querySelector(".stream-head").children.map((n) => n.id || n.className.split(" ")[0]);
  assert.ok(kids.indexOf("what-now") < kids.indexOf("project-bar"), kids.join());
  assert.match(CSS_TEXT, /@media \(min-width: 901px\) \{\s*\.stream-head \.what-now \{ flex: 1 1 320px;/);
  assert.equal(app.foldsTools(100, 800), false, "foldsTools itself doesn't change");
});

test("N5's fix: opening Settings, or another tab, starts at the top", async () => {
  const page = await pageWith();
  page.doc.scrollingElement.scrollTop = 500;
  await page.openSettings("setup");
  assert.equal(page.doc.scrollingElement.scrollTop, 0);
  page.doc.scrollingElement.scrollTop = 500;
  page.el("settings-tab-memory").click();
  assert.equal(page.doc.scrollingElement.scrollTop, 0);
});

// ---- N7: Log files "#n · run ID" (D20) ----

test("N7: a Log files row reads #n · its run id; a folder with no row shows its bare id", () => {
  const task = LOG.tasks[0];
  assert.equal(app.logFolderView({ task_id: task.task_id, files: [] }, LOG.tasks).title, `#${task.n} · ${task.task_id}`);
  assert.equal(app.logFolderView({ task_id: "sr-20200101-000000-0000", files: [] }, LOG.tasks).title, "sr-20200101-000000-0000");
});

// ---- N8: Memory's plain link (Q3) ----

test("N8: the Memory tab links to the control page in a new tab, with its fixed line and the start command; no fetch to it", async () => {
  const page = await pageWith();
  await page.openSettings("memory");
  const link = stream(page).querySelector(".mem-control a");
  assert.equal(link.getAttribute("href"), "http://127.0.0.1:9999/");
  assert.equal(link.getAttribute("target"), "_blank");
  assert.equal(link.getAttribute("rel"), "noopener noreferrer");
  const block = stream(page).querySelector(".mem-control");
  assert.match(block.textContent, /Works while Hindsight's control page is running/);
  assert.match(block.textContent, /npx @vectorize-io\/hindsight-control-plane@1\.1\.0 --hostname 127\.0\.0\.1 --port 9999 --api-url http:\/\/127\.0\.0\.1:8888/);
  assert.equal(block.querySelector(".icon-btn").getAttribute("aria-label"), "Copy the start command");
  assert.ok(!page.gets.some((path) => /9999/.test(path)));
  assert.doesNotMatch(SOURCE, /127\.0\.0\.1/, "the script names no address");
});

// ---- N9: Show in Finder on a project (D18, Cleanup 1) ----

test("N9: Show in Finder is in the Project menu with state.reveal, not in the demo, and posts the project's own path", async () => {
  const page = await projectPage(1280);
  page.state.reveal = true;
  page.state.menu = "project-menu";
  page.renderStream();
  const item = page.find("Show in Finder", stream(page)) || stream(page).querySelectorAll('[role="menuitem"]').find((b) => b.textContent === "Show in Finder");
  assert.ok(item);
  assert.equal(item.id, "", "no id: the bar's id list stays");
  item.click();
  await page.settle();
  const posted = page.posts.find((p) => p.path === "/api/reveal");
  assert.equal(posted.body.path, STATUS.projects[0].path);
  const off = await projectPage(1280);
  off.state.menu = "project-menu";
  off.renderStream();
  assert.ok(!stream(off).querySelectorAll('[role="menuitem"]').some((b) => b.textContent === "Show in Finder"), "no state.reveal");
  const demo = await projectPage(1280);
  Object.assign(demo.state, { reveal: true, demo: true, menu: "project-menu" });
  demo.renderStream();
  assert.ok(!stream(demo).querySelectorAll('[role="menuitem"]').some((b) => b.textContent === "Show in Finder"), "not in the demo");
});

// ---- N10: the sheets' command lines go (Q4, D26) ----

const sheetEl = (page) => page.el("sheet");
const NOTES_DOC = { notes: { text: "## All agents\n", hash: "h", state: "set", sections: [], total: 10, cap: 6000, chars: 10 } };
const PN_DOC = { notes: { notes: "Mine.", hash: "h", block: "", chars: 5, max: 20000, commit: true } };

test("N10: no command line in any sheet; each says in words what its button does", async () => {
  const task = { ...LOG.tasks.find((t) => t.project && t.status === "done"), result: "A result.", save_path: "notes.md" };
  const cases = [
    ["New project", (p) => p.openNewProject(), /Create makes the folder/],
    ["Secrets", (p) => p.openSecrets(PROJECT), /Add writes the value into the project's \.env/],
    ["Ideas", (p) => p.openIdeas(PROJECT), /Add keeps it on this list/],
    ["Router notes", (p) => p.openNotesEditor(), /Save writes them to this Mac's router notes/],
    ["Notes", (p) => p.openProjectNotes(PROJECT), /Save writes them into HANDOFF\.md/],
    ["Pin", (p) => p.openPinSheet(task), /Adds the text at the end of the project's notes/],
    ["Save", (p) => p.openSaveSheet(task), /Save writes the result as a new file in the project/],
  ];
  for (const [name, open, words] of cases) {
    const page = await pageWith({ answers: { "/api/notes": NOTES_DOC, "/api/project-notes": PN_DOC, "/api/project-spec": { spec: { text: "", hash: "h" } }, "/api/project-secrets": { project: { secrets: [] } }, "/api/ideas": { ideas: [], dismissed: 0, used: [] } } });
    await open(page);
    await page.settle();
    assert.ok(!sheetEl(page).querySelector(".np-cmd"), `${name}: no command line`);
    assert.doesNotMatch(sheetEl(page).textContent, /\$ ?sr /, name);
    assert.match(sheetEl(page).textContent, words, name);
  }
});

test("N10: the Memory switch's and Fable's command lines go; their words stay", async () => {
  const page = await pageWith();
  await page.openSettings("memory");
  assert.ok(page.el("mem-note"));
  assert.ok(!stream(page).querySelector(".mem-cmd"));
  assert.ok(!stream(page).querySelector(".np-cmd"));
  await page.openSettings("models");
  assert.ok(page.el("fable-switch"));
  assert.ok(!stream(page).querySelector(".mem-cmd"));
});

test("N10: a refused command still turns Save off and says why", async () => {
  const task = { ...LOG.tasks.find((t) => t.project && t.status === "done"), result: "A result.", save_path: "notes.md" };
  const page = await pageWith({ answers: { "/api/command": { error: "path is taken" } } });
  page.openSaveSheet(task);
  await page.settle();
  const line = page.el("sf-cmd");
  assert.equal(line.hidden, false);
  assert.equal(line.textContent, "Refused: path is taken");
  assert.equal(page.el("sf-save").getAttribute("aria-disabled"), "true");
  const fine = await pageWith();
  fine.openSaveSheet(task);
  await fine.settle();
  assert.equal(fine.el("sf-cmd").hidden, true);
});

test("N10: the pure views keep their data, so their tests hold", () => {
  assert.match(app.secretCommandLine("seed", "KEY", 3).command, /sr project secrets seed --set KEY/);
});

// ---- Row 14: the Models section, read first (board 2, board 3) ----

const SET_SKILLS = STATUS.models.setup.skills.map((s, i) => (i === 3 ? { ...s, model: STATUS.models.agents[s.agent].allowed[0] } : s));
const YOURS = { ...STATUS, models: { ...STATUS.models, setup: { ...STATUS.models.setup, skills: SET_SKILLS } } };
const RUN_OK = { "/api/status": YOURS, "/api/log": { tasks: [] }, "/api/runs": { runs: [{ id: "r", running: false, exit: 0, envelope: { exit: 0, message: "that skill now uses Haiku 5.5" } }] }, "/api/run": { run_id: "r" } };
const RUN_NO = { "/api/status": YOURS, "/api/log": { tasks: [] }, "/api/runs": { runs: [{ id: "r", running: false, exit: 2, envelope: { exit: 2, message: "that isn't on the allowed list" } }] }, "/api/run": { run_id: "r" } };
const rowsOf = (page) => stream(page).querySelectorAll(".models-row");
const changeOn = (row) => row.querySelectorAll("button").find((b) => b.textContent === "Change");

test("Row 14: yours sort first and read yours; the first five show, the rest fold with the roles and the stages", async () => {
  const view = app.modelRows(app.modelsSetupSelects(YOURS).skills);
  const mine = SET_SKILLS.filter((s) => s.model).length;
  assert.ok(mine >= 1);
  assert.deepEqual(view.shown.slice(0, mine).map((r) => r.yours), Array(mine).fill(true), "yours first");
  assert.equal(view.shown.length, 5);
  assert.equal(view.more.length, SET_SKILLS.length - 5);
  assert.equal(view.yours, mine);
  const page = await pageWith({ status: YOURS });
  await page.openSettings("models");
  assert.match(rowsOf(page)[0].textContent, /yours/);
  const folds = stream(page).querySelectorAll(".models-fold > summary").map((n) => n.textContent);
  assert.match(folds[0], new RegExp(`^${SET_SKILLS.length - 5} more skills`));
  assert.ok(folds.some((t) => /^Team roles/.test(t)));
  assert.ok(folds.some((t) => /^Team stages/.test(t)));
});

test("Row 14: a row is read first; Change opens one row at a time, and the open row names itself", async () => {
  const page = await pageWith({ status: YOURS });
  await page.openSettings("models");
  assert.equal(stream(page).querySelectorAll(".models-row select").length, 0);
  changeOn(rowsOf(page)[1]).click();
  const open = () => stream(page).querySelector(".models-row.open");
  assert.match(open().querySelector(".models-row-title").textContent, /^Change /);
  assert.equal(stream(page).querySelectorAll(".models-row select").length, 1);
  const firstId = open().querySelector("select").id;
  assert.match(firstId, /^models-skill-/);
  changeOn(rowsOf(page)[2]).click();
  assert.notEqual(open().querySelector("select").id, firstId);
  assert.equal(stream(page).querySelectorAll(".models-row select").length, 1);
  page.key("Escape", page.doc.body);
  assert.ok(!open(), "Esc closes the row");
  assert.equal(page.state.view, "settings", "and doesn't leave the tab");
});

test("Row 14: the router's answer lands on the row it changed, not at the foot", async () => {
  const page = await pageWith({ status: YOURS, answers: RUN_OK });
  await page.openSettings("models");
  changeOn(rowsOf(page)[1]).click();
  const select = stream(page).querySelector(".models-row.open select");
  select.value = select.children[1].value;
  select.fire("change");
  await page.settle(); await page.settle();
  const said = stream(page).querySelectorAll(".models-row").filter((r) => /that skill now uses Haiku 5\.5/.test(r.textContent));
  assert.equal(said.length, 1);
  assert.ok(!said[0].classList.contains("open"), "a good change closes the row");
  assert.equal(runs(page)[0].body.action, "models_set");
});

test("Row 14: a refusal keeps the value and shows on its row", async () => {
  const page = await pageWith({ status: YOURS, answers: RUN_NO });
  await page.openSettings("models");
  const before = rowsOf(page)[4].textContent;
  changeOn(rowsOf(page)[4]).click();
  const select = stream(page).querySelector(".models-row.open select");
  select.value = select.children[1].value;
  select.fire("change");
  await page.settle(); await page.settle();
  const row = stream(page).querySelectorAll(".models-row").find((r) => /that isn't on the allowed list/.test(r.textContent));
  assert.ok(row);
  assert.match(row.textContent, /The router refused this/);
  assert.match(row.textContent, /Default|yours/, "the value it had");
  assert.equal(row.querySelector(".models-row-now").textContent, before.match(/Default \([^)]*\)/)[0]);
});

test("Row 14: in the demo Change still opens the row, its select off; the Models sheet keeps its one button, Done", async () => {
  const page = await pageWith({ status: YOURS });
  page.state.demo = true;
  await page.openSettings("models");
  changeOn(rowsOf(page)[0]).click();
  assert.equal(stream(page).querySelector(".models-row.open select").disabled, true);
  assert.match(SOURCE.slice(SOURCE.indexOf("function paintModelsSheet("), SOURCE.indexOf("function chooseModel(")), /"Done"/);
});

// ---- Rows 13 to 1: the sheets and the views, restyled; ids and handlers as they were ----

test("Row 13: Setup's rows keep their state in words and their ids; the steps read as blocks to copy", async () => {
  const page = await pageWith();
  await page.openSetup("chatgpt");
  assert.match(page.el("setup-chatgpt").querySelector(".setup-state").textContent, /signed out|online|not set up/);
  assert.ok(page.el("check-again"));
  assert.match(CSS_TEXT, /\/\* -+ UI B row 13/);
  assert.match(CSS_TEXT, /\.setup-body pre \{ user-select: all;/);
});

test("Row 12: two sections, two Saves, one Close at the very end", async () => {
  const body = SOURCE.slice(SOURCE.indexOf("async function openProjectNotes("), SOURCE.indexOf("async function loadProjectSpecDoc("));
  const order = ['id: "pn-box"', 'id: "pn-save"', "specSection(name)", 'id: "pn-close"'];
  const at = order.map((w) => body.indexOf(w));
  assert.deepEqual(at, [...at].sort((a, b) => a - b), at.join());
  const spec = SOURCE.slice(SOURCE.indexOf("function specSection("), SOURCE.indexOf("async function loadProjectSpecDoc("));
  assert.ok(spec.indexOf('id: "pn-spec-box"') < spec.indexOf('id: "pn-spec-labels"') && spec.indexOf('id: "pn-spec-labels"') < spec.indexOf('id: "pn-spec-save"'));
  assert.match(CSS_TEXT, /\.notes-sheet \.spec-labels \{ max-height: 150px; overflow-y: auto;/);
  assert.match(CSS_TEXT, /\.notes-sheet > \.np-foot:last-child \{ position: sticky;/);
});

test("Row 11: Secrets keeps its ids; the field clears at Save; the view's data is untouched", () => {
  const save = SOURCE.slice(SOURCE.indexOf("async function saveSecret("), SOURCE.indexOf("async function removeSecret("));
  assert.match(save, /field\.value = "";/);
  assert.match(CSS_TEXT, /\.secrets-sheet \.sc-row \{ min-height: 40px;/);
});

test("Row 10: New project keeps its ids and says what Create does", async () => {
  const page = await pageWith();
  page.openNewProject();
  for (const id of ["np-name", "np-notes", "np-create", "np-mode-blank", "np-mode-idea", "np-folder", "np-does"]) assert.ok(page.el(id), id);
  assert.match(CSS_TEXT, /\.sheet\.np #np-does \{ color: var\(--text-3\); \}/);
});

test("Row 9: Ideas keeps Add above its list and its foot sticky", () => {
  const sheet = SOURCE.slice(SOURCE.indexOf("function openIdeas("), SOURCE.indexOf("function paintIdeas("));
  assert.ok(sheet.indexOf('id: "ideas-add"') < sheet.indexOf('id: "ideas-list"'));
  assert.match(CSS_TEXT, /\.ideas-sheet \.idea-row \{ background: var\(--side\);/);
});

test("Row 8: Run's confirm: what it does, the folder, the names it can read, and that it only starts on your click", () => {
  const words = app.runConfirmWords({ project: { run_status: { command: ["python3", "app.py"], folder: "~/Projects/x", env_names: ["KEY"] } } });
  assert.deepEqual(words.facts.map((f) => f.label.split(":")[0]), ["Command", "Folder", "From its .env"]);
  assert.match(SOURCE.slice(SOURCE.indexOf("async function askRun("), SOURCE.indexOf("async function askStop(")), /Run only starts on your click\. The router never runs it on its own\./);
});

test("Row 7: Tests and Run command: one line saying what the button does, a labelled block, one primary", () => {
  for (const [from, to, id] of [["function openTestsSheet(", "function paintFailure(", "ts-save"], ["function openRunSheet(", "function paintRunSheet(", "rc-save"]]) {
    const sheet = SOURCE.slice(SOURCE.indexOf(from), SOURCE.indexOf(to));
    assert.equal((sheet.match(/btn-primary/g) || []).length, 1, id);
    assert.ok(sheet.includes(`id: "${id}"`));
    assert.doesNotMatch(sheet, /np-cmd|commandLine/);
  }
  assert.match(CSS_TEXT, /\.tests-sheet \.ts-words \{ min-height: 84px; \}/);
});

test("Row 6: Add files and Turn on undo: one primary, no command line", () => {
  const git = SOURCE.slice(SOURCE.indexOf("function openTurnOnUndo("), SOURCE.indexOf("async function askGitCheck("));
  assert.equal((git.match(/btn-primary/g) || []).length, 1);
  assert.doesNotMatch(git, /np-cmd|commandLine/);
  assert.match(CSS_TEXT, /\.drop-sheet \.git-names, \.git-sheet \.git-names \{ background: var\(--side\); \}/);
});

test("Row 5: the Router notes editor keeps its ids", async () => {
  const page = await pageWith({ answers: { "/api/notes": { notes: { text: "## All agents\n", hash: "h", state: "set", sections: [], total: 10, cap: 6000, chars: 10 } } } });
  await page.openNotesEditor();
  for (const id of ["ne-box", "ne-save", "ne-close", "ne-counts"]) assert.ok(page.el(id), id);
  assert.match(CSS_TEXT, /\.notes-sheet \.notes-sections \.pill \{ background: var\(--side\); \}/);
});

test("Row 4: Shortcuts keeps ⌥1 … ⌥8; Pin and Save keep one primary and Cancel", () => {
  assert.match(SOURCE, /"⌥1 … ⌥8"/);
  assert.match(CSS_TEXT, /\.keys \{ row-gap: 10px; \}/);
  for (const [from, to] of [["function openPinSheet(", "async function loadPinNotes("], ["function openSaveSheet(", "function saveView("]]) {
    const sheet = SOURCE.slice(SOURCE.indexOf(from), SOURCE.indexOf(to));
    assert.equal((sheet.match(/btn-primary/g) || []).length, 1, from);
    assert.match(sheet, /"Cancel"/);
  }
});

test("Row 3: the side panel's head; no Land or Discard in its foot", () => {
  const panel = SOURCE.slice(SOURCE.indexOf("function renderPanel("), SOURCE.indexOf("function renderPanel(") + 5000);
  assert.doesNotMatch(panel, /"Land"|"Discard"/);
  assert.match(CSS_TEXT, /\.panel-head \.tabs \{ background: transparent; box-shadow: none;/);
  assert.match(CSS_TEXT, /\.panel \{ position: fixed; inset: 0; z-index: 30; height: 100vh; \}/);
});

test("Row 2: All tasks keeps its search, filter and count", async () => {
  const page = await pageWith({ answers: { "/api/log": { tasks: LOG.tasks, next_before: null } } });
  page.el("sidebar");
  page.state.view = "history";
  page.state.historyTasks = LOG.tasks.slice(0, 2);
  page.renderStream();
  const head = stream(page).querySelector(".stream-head");
  assert.ok(head.querySelector("select"));
  assert.ok(head.querySelector("input"));
  assert.match(head.textContent, /2 shown/);
  assert.match(CSS_TEXT, /\.stream-head \.search \{ flex: 1 1 220px; max-width: none; \}/);
});

test("Row 1: All tasks and Log files are tabs at the head of those two views", async () => {
  const page = await pageWith({ answers: { "/api/logfiles": { folders: [], next_before: null }, "/api/log": { tasks: [], next_before: null } } });
  page.state.view = "history";
  page.state.historyTasks = [];
  page.renderStream();
  const tabsNow = () => stream(page).querySelectorAll('.history-tabs [role="tab"]');
  assert.deepEqual(tabsNow().map((b) => b.textContent), ["All tasks", "Log files"]);
  assert.equal(tabsNow()[0].getAttribute("aria-selected"), "true");
  tabsNow()[1].click();
  await page.settle();
  assert.equal(page.state.view, "logfiles");
  assert.equal(tabsNow()[1].getAttribute("aria-selected"), "true");
  tabsNow()[0].click();
  await page.settle();
  assert.equal(page.state.view, "history");
});

// ---- UI B's live check: page bugs it found ----

test("the live check: wide, the title's line fills, so What now? and the bar start the next line together", () => {
  assert.match(CSS_TEXT, /@media \(min-width: 901px\) \{\s*\.stream-head \.what-now \{ flex: 1 1 320px;[^}]*\}\s*\.stream-head \.project-bar \{[^}]*\}\s*\.stream-head \.head-where \{ flex: 1 1 60%; \}/);
});

test("the live check: in the drawer Settings stays at the foot while its lists scroll", () => {
  assert.match(CSS_TEXT, /\.sidebar\.open \{ overflow: hidden; \}\s*\.sidebar\.open \.side-scroll \{ flex: 1 1 auto; min-height: 0; overflow-y: auto; \}/);
});

test("the live check: the phone's head fits its budget: one title line beside Project tools, no where line", () => {
  const phone = CSS_TEXT.slice(CSS_TEXT.indexOf("UI B's live check: the phone's head"));
  assert.match(phone, /\.stream-head \.head-where \{ display: none; \}/);
  assert.match(phone, /\.stream-head \.project-tools \{ order: -1;/);
  assert.match(phone, /\.stream-head \.stream-title \{ order: -2;[^}]*text-overflow: ellipsis;/);
});

test("the live check: with the side panel open the sidebar steps aside, and Needs you stays reachable in the head", async () => {
  const page = await pageWith();
  assert.ok(!page.el("strip").querySelector(".needs-head"));
  page.state.panel = { kind: "doc", title: "x", sub: "y", text: "z" };
  page.render();
  const needs = page.el("strip").querySelector(".needs-head");
  assert.ok(needs);
  needs.click();
  assert.equal(page.state.panel, null, "pressing it closes the panel, so the list shows");
  assert.match(CSS_TEXT, /\.app\.panel-open \.sidebar \{ display: none; \}/);
});
