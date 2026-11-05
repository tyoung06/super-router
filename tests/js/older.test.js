// Cleanup 2, rows 1 and 2: a chat's or a project's view reads its own newest tasks, with Show older, the router's count and
// jumps that find their card. Pure functions first, then the real page through pagedom.js. Invented data.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { loadPage } from "./pagedom.js";
import { viewReadKey, takeViewPage, viewTasksKnown, chatCount, patchViewRow, detailNotes } from "../../static/app.js";

const JS = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const row = (n, extra = {}) => ({ task_id: `sr-${n}`, n, text: `task ${n}`, status: "done", outcome: "passed", updated_at: `u${n}`, ...extra });
const chatRows = (name, from, to) => { const out = []; for (let n = to; n >= from; n -= 1) out.push(row(n, { chat: name })); return out; };
const projectRows = (name, from, to) => { const out = []; for (let n = to; n >= from; n -= 1) out.push(row(n, { project: name })); return out; };
const logs = (page) => page.gets.filter((p) => p.startsWith("/api/log"));
const STATUS = { agents: [], chats: [{ name: "tee", tasks: 8 }], projects: [{ name: "seed", path: "~/seed" }], presets: [] };
const cards = (page) => page.el("stream").querySelectorAll("article.task").map((c) => c.dataset.task);

async function pageWith({ answers = {}, chat = "tee", project = null, tasks = [], status = STATUS } = {}) {
  const page = await loadPage({ answers: { "/api/files/": { files: [] }, ...answers } });
  Object.assign(page.state, { status, chat, project, tasks, team: "route", statusAt: Date.now() });
  page.wire();
  return page;
}

// ---- the pure functions ----

test("viewReadKey names a chat's or a project's read, and nothing for the views with none", () => {
  assert.equal(viewReadKey({ view: "chat", chat: "tee", project: null }), "chat:tee");
  assert.equal(viewReadKey({ view: "chat", chat: "tee", project: "seed" }), "project:seed");
  assert.equal(viewReadKey({ view: "chat", chat: null, project: null }), null);  // Quick tasks
  for (const view of ["history", "logfiles", "settings"]) assert.equal(viewReadKey({ view, chat: "tee", project: "seed" }), null);
});

test("takeViewPage: the first read replaces, a poll merges and keeps older pages, more adds below", () => {
  const blank = { key: "chat:tee", tasks: [], next: null, pages: 0, loading: true, error: null };
  const first = takeViewPage(blank, { tasks: [row(9), row(8)], next_before: "sr-8" });
  assert.deepEqual(first.tasks.map((t) => t.n), [8, 9]);
  assert.equal(first.next, "sr-8");
  assert.equal(first.pages, 1);
  assert.equal(first.loading, false);
  const older = takeViewPage(first, { tasks: [row(7), row(6)], next_before: null }, { more: true });
  assert.deepEqual(older.tasks.map((t) => t.n), [6, 7, 8, 9]);
  assert.equal(older.next, null);
  assert.equal(older.pages, 2);
  const polled = takeViewPage(older, { tasks: [row(10), row(9, { text: "new words" })], next_before: "sr-9" }, { quiet: true });
  assert.deepEqual(polled.tasks.map((t) => t.n), [6, 7, 8, 9, 10]);  // the older page stays
  assert.equal(polled.tasks.find((t) => t.n === 9).text, "new words");
  assert.equal(polled.next, null);  // a poll past page 1 leaves the older pages' place alone
  const again = takeViewPage(first, { tasks: [row(10), row(9)], next_before: "sr-9" }, { quiet: true });
  assert.equal(again.next, "sr-9");  // on page 1 it moves with the first page
  assert.deepEqual(again.tasks.map((t) => t.n), [8, 9, 10]);
  const replaced = takeViewPage(older, { tasks: [row(10)], next_before: null });
  assert.deepEqual(replaced.tasks.map((t) => t.n), [10]);
  assert.equal(replaced.pages, 1);
});

test("viewTasksKnown: a row from either read counts, and the whole log's copy is the newer", () => {
  const read = { tasks: [row(1, { chat: "tee" }), row(2, { text: "older copy" })] };
  const known = viewTasksKnown(read, [row(2, { text: "newer copy" }), row(3)]);
  assert.deepEqual(known.map((t) => t.n), [1, 2, 3]);
  assert.equal(known[1].text, "newer copy");
  assert.deepEqual(viewTasksKnown(null, [row(3), row(2)]).map((t) => t.n), [2, 3]);
});

test("chatCount reads the router's count, never lower than what's on screen", () => {
  assert.equal(chatCount(STATUS, "tee", 3), 8);
  assert.equal(chatCount(STATUS, "tee", 9), 9);  // a task just sent: status is a minute old
  assert.equal(chatCount(STATUS, "new-one", 0), 0);
  assert.equal(chatCount(null, "tee", 2), 2);
});

test("patchViewRow patches a row's own keys from a show, and leaves a read without the row alone", () => {
  const read = { key: "chat:tee", tasks: [row(1, { waiting_on: "land" })] };
  const patched = patchViewRow(read, { ...row(1, { waiting_on: null, updated_at: "later" }), calls: [1, 2] });
  assert.equal(patched.tasks[0].waiting_on, null);
  assert.equal(patched.tasks[0].updated_at, "later");
  assert.equal("calls" in patched.tasks[0], false);
  assert.equal(patchViewRow(read, row(5)), read);
  assert.equal(patchViewRow(null, row(5)), null);
});

// ---- the real page ----

test("a chat with none of its tasks in the whole log's 50 still draws them", async () => {
  const whole = chatRows("other", 100, 149);
  const page = await pageWith({ tasks: whole, answers: { "/api/log?chat=tee": { tasks: chatRows("tee", 1, 8), next_before: null } } });
  page.render();
  assert.match(page.el("stream").textContent, /Loading this chat's tasks…/);
  await page.settle();
  assert.equal(cards(page).length, 8);
  assert.doesNotMatch(page.el("stream").textContent, /Loading this chat's tasks…/);
});

test("a new chat with no tasks says so straight away, and a failed read says the log could not be read", async () => {
  const fresh = await pageWith({ chat: "chat-20261104-2200" });
  fresh.render();
  assert.match(fresh.el("stream").textContent, /No tasks here yet/);
  const broken = await pageWith({ answers: { "/api/log?chat=tee": { httpStatus: 500, error: "no log today" } } });
  broken.render();
  await broken.settle();
  assert.match(broken.el("stream").textContent, /The log could not be read: no log today/);
});

test("a row only in the whole log and a row only in the view's read both draw; a stray row is still filtered out", async () => {
  const page = await pageWith({ tasks: [row(20, { chat: "tee" }), row(21, { chat: "other" })],
    answers: { "/api/log?chat=tee": { tasks: [row(5, { chat: "tee" }), row(6, { chat: "other" })], next_before: null } } });
  page.render();
  await page.settle();
  assert.deepEqual(cards(page), ["sr-5", "sr-20"]);
});

test("a poll keeps an older page; a late answer for another view is ignored", async () => {
  const page = await pageWith({ answers: { "/api/log?chat=tee": { tasks: chatRows("tee", 3, 8), next_before: null } } });
  page.render();
  await page.settle();
  page.state.viewRead.tasks = [...chatRows("tee", 1, 2), ...page.state.viewRead.tasks];
  page.state.viewRead.pages = 2;
  await page.poll();
  await page.settle();
  assert.equal(cards(page).length, 8);
  const late = page.loadViewRead();  // asked for tee; the person moves on before the answer lands
  page.state.chat = "elsewhere";
  page.render();
  await late;
  assert.equal(page.state.viewRead.key, "chat:elsewhere");
  assert.deepEqual(page.state.viewRead.tasks.map((t) => t.n).filter((n) => n <= 8), []);
});

test("a chat's poll makes one more read; a project's makes none, reusing What now?'s", async () => {
  const chat = await pageWith({ answers: { "/api/log?chat=tee": { tasks: chatRows("tee", 1, 3), next_before: null } } });
  chat.render();
  await chat.settle();
  chat.gets.length = 0;
  await chat.poll();
  assert.deepEqual(logs(chat), ["/api/log", "/api/log?chat=tee"]);

  const project = await pageWith({ chat: null, project: "seed",
    answers: { "/api/log?project=seed": { tasks: projectRows("seed", 1, 3), next_before: null, what_now: null } } });
  project.render();
  await project.settle();
  assert.equal(cards(project).length, 3);
  project.gets.length = 0;
  await project.poll();
  assert.deepEqual(logs(project), ["/api/log", "/api/log?project=seed"]);  // the same two as before this brief
  assert.match(JS, /if \(state\.project\) await loadWhatNow\(\);/);
});

test("a project's poll document lands in its read", async () => {
  const answers = { "/api/log?project=seed": { tasks: projectRows("seed", 1, 3), next_before: null, what_now: null } };
  const page = await pageWith({ chat: null, project: "seed", answers });
  page.render();
  await page.settle();
  answers["/api/log?project=seed"].tasks = projectRows("seed", 2, 4);
  await page.poll();
  assert.deepEqual(cards(page), ["sr-1", "sr-2", "sr-3", "sr-4"]);
});

test("All tasks' read and its calls don't change: a jump's more is its own button's call", async () => {
  const page = await pageWith({ answers: { "/api/log?": { tasks: [], next_before: null }, "/api/log": { tasks: [row(9)], next_before: "sr-9" } } });
  page.state.view = "history";
  page.render();
  await page.settle();
  assert.equal(page.state.viewRead, null);
  assert.deepEqual(logs(page), []);
  await page.loadHistory();
  assert.deepEqual(logs(page), ["/api/log"]);
  assert.ok(page.buttons("Load earlier tasks").length);
  assert.match(JS, /loadHistory\(\{ more: true \}\) \}, "Load earlier tasks"\)/);
});

test("an action on an older card shows at once: loadShow patches that row in the view's read", async () => {
  const older = row(3, { chat: "tee", waiting_on: "land" });
  const answers = { "/api/log?chat=tee": { tasks: [older], next_before: null }, "/api/task/sr-3": row(3, { chat: "tee", waiting_on: null, updated_at: "later" }) };
  const page = await pageWith({ answers });
  page.render();
  await page.settle();
  await page.loadShow("sr-3", { quiet: true });
  assert.equal(page.state.viewRead.tasks[0].waiting_on, null);
  assert.equal(page.state.viewRead.tasks[0].updated_at, "later");
});

test("the poll's loop reaches an older open card, so its details keep updating", async () => {
  const older = row(3, { chat: "tee", updated_at: "old" });
  const answers = { "/api/log?chat=tee": { tasks: [older], next_before: null }, "/api/task/sr-3": row(3, { chat: "tee", updated_at: "old" }) };
  const page = await pageWith({ answers });
  page.render();
  await page.settle();
  await page.loadShow("sr-3", { quiet: true });
  page.state.shows.get("sr-3").updated_at = null;  // what an ended action does
  page.gets.length = 0;
  await page.poll();
  assert.ok(page.gets.includes("/api/task/sr-3"));
});

// ---- row 2: Show older, the head's count and jumps ----

function paged(prefix, make, pages) {
  // pages: [[from, to, nextId], …], newest first; the most specific path first, as the fake fetch takes the first match
  const answers = {};
  pages.slice(1).reverse().forEach(([from, to, next], i) => {
    const at = pages.length - 1 - i;
    answers[`${prefix}&before=${pages[at - 1][2]}`] = { tasks: make(from, to), next_before: next, what_now: null };
  });
  answers[prefix] = { tasks: make(pages[0][0], pages[0][1]), next_before: pages[0][2], what_now: null };
  return answers;
}

test("Show older adds a page, keeps the card in place (no follow) and goes at the end", async () => {
  const page = await pageWith({ chat: "older", status: { ...STATUS, chats: [{ name: "older", tasks: 60 }] },
    answers: paged("/api/log?chat=older", (a, b) => chatRows("older", a, b), [[11, 60, "sr-11"], [1, 10, null]]) });
  page.render();
  await page.settle();
  assert.equal(cards(page).length, 50);
  assert.match(page.el("chat-memory").textContent, /chat · 60 tasks/);
  const button = page.find("Show older");
  assert.ok(button);
  assert.equal(button.classList.contains("load-earlier"), true);
  const stream = page.el("stream");
  assert.ok(stream.children.indexOf(button) < stream.children.findIndex((c) => c.tag === "article"));
  button.click();
  assert.equal(page.find("Show older") ? page.find("Show older").disabled : true, true);  // off while the read runs
  await page.settle();
  assert.equal(cards(page).length, 60);
  assert.equal(page.find("Show older"), null);
  assert.ok(page.gets.includes("/api/log?chat=older&before=sr-11"));
  assert.match(JS, /renderStream\(\{ follow: !more \}\)/);
});

test("a project shows Show older too, with no count in its head", async () => {
  const page = await pageWith({ chat: null, project: "seed",
    answers: paged("/api/log?project=seed", (a, b) => projectRows("seed", a, b), [[11, 60, "sr-11"], [1, 10, null]]) });
  page.render();
  await page.settle();
  assert.equal(cards(page).length, 50);
  page.find("Show older").click();
  await page.settle();
  assert.equal(cards(page).length, 60);
  assert.doesNotMatch(page.el("stream").textContent, /· \d+ tasks/);
});

test("the head's count is the router's and never less than what's shown", async () => {
  const page = await pageWith({ answers: { "/api/log?chat=tee": { tasks: chatRows("tee", 1, 9), next_before: null } } });  // the router says 8
  page.render();
  await page.settle();
  assert.match(page.el("chat-memory").textContent, /chat · 9 tasks/);
});

test("a jump from a source link to a card on page 3 reads pages 2 and 3 and focuses it", async () => {
  const answers = paged("/api/log?chat=older", (a, b) => chatRows("older", a, b), [[101, 150, "sr-101"], [51, 100, "sr-51"], [1, 50, null]]);
  const page = await pageWith({ chat: "other", tasks: [row(150, { chat: "older", from: { task_id: "sr-20", n: 20 } })],
    answers: { ...answers, "/api/task/sr-20": row(20, { chat: "older" }), "/api/log?chat=other": { tasks: [], next_before: null } } });
  page.render();
  await page.settle();
  await page.goToSource("sr-20");
  await page.settle();
  assert.equal(page.state.chat, "older");
  assert.ok(page.gets.includes("/api/log?chat=older&before=sr-101"));
  assert.ok(page.gets.includes("/api/log?chat=older&before=sr-51"));
  assert.equal(page.state.focusTask, null);
  assert.equal(page.doc.activeElement.dataset.task, "sr-20");
});

test("a jump stops reading once the oldest loaded row is older than the target", async () => {
  const answers = paged("/api/log?chat=older", (a, b) => chatRows("older", a, b).filter((t) => t.n !== 120), [[101, 150, "sr-101"], [51, 100, "sr-51"]]);
  const page = await pageWith({ tasks: [], chat: "other", answers: { ...answers, "/api/task/sr-120": row(120, { chat: "older" }), "/api/log?chat=other": { tasks: [], next_before: null } } });
  page.render();
  await page.settle();
  await page.jumpToTask("sr-120", 120);
  await page.settle();
  assert.equal(page.gets.includes("/api/log?chat=older&before=sr-101"), false);
  assert.equal(page.state.focusTask, null);
  assert.match(page.el("toast").textContent, /#120 could not be found/);
});

test("a jump to an untagged old task goes to All tasks and finds it through its own more", async () => {
  const page = await pageWith({ answers: { "/api/task/sr-3": row(3),
    "/api/log?before=sr-40": { tasks: [row(3), row(39)], next_before: null }, "/api/log?chat=tee": { tasks: [], next_before: null },
    "/api/log": { tasks: [row(40)], next_before: "sr-40" } } });
  page.state.tasks = [row(40)];
  page.render();
  await page.settle();
  await page.goToSource("sr-3");
  await page.settle();
  assert.equal(page.state.view, "history");
  assert.ok(page.gets.includes("/api/log?before=sr-40"));
  assert.equal(page.doc.activeElement.dataset.task, "sr-3");
});

test("a jump to a task that doesn't exist says so and stops", async () => {
  const page = await pageWith({ answers: { "/api/task/": { httpStatus: 404, error: "no such task" }, "/api/log?chat=tee": { tasks: [], next_before: null } } });
  page.render();
  await page.settle();
  await page.jumpToTask("sr-999", 999);
  await page.settle();
  assert.equal(page.state.chat, "tee");
  assert.equal(page.state.focusTask, null);
  assert.match(page.el("toast").textContent, /#999 could not be found/);
  await page.jumpToTask("sr-998");
  assert.match(page.el("toast").textContent, /That task could not be found/);
});

test("a piece's link that isn't loaded jumps; the old toast is gone", async () => {
  assert.doesNotMatch(JS, /isn't loaded on this page yet/);
  const page = await pageWith({ answers: { "/api/task/sr-7": row(7, { project: "seed" }), "/api/log?project=seed": { tasks: [row(7, { project: "seed" })], next_before: null, what_now: null }, "/api/log?chat=tee": { tasks: [], next_before: null } } });
  page.render();
  await page.settle();
  await page.openPieceCard({ task_id: "sr-7", n: 7 });
  await page.settle();
  assert.equal(page.state.project, "seed");
  assert.equal(page.doc.activeElement.dataset.task, "sr-7");
});

test("a Needs you row in the whole log still opens its card; taskById also looks in the view's read", async () => {
  const page = await pageWith({ tasks: [row(30, { project: "seed", waiting_on: "land" })],
    answers: { "/api/log?project=seed": { tasks: [row(30, { project: "seed", waiting_on: "land" })], next_before: null, what_now: null }, "/api/log?chat=tee": { tasks: [row(4, { chat: "tee" })], next_before: null } } });
  page.render();
  await page.settle();
  assert.equal(page.taskById("sr-4").n, 4);
  await page.goToTask("sr-30");
  await page.settle();
  assert.equal(page.state.project, "seed");
  assert.equal(page.doc.activeElement.dataset.task, "sr-30");
});

test("a suggest task's link goes to All tasks, the one view that draws it", async () => {
  const task = row(6, { project: "seed", mode: "suggest" });
  const page = await pageWith({ tasks: [task], answers: { "/api/log?chat=tee": { tasks: [], next_before: null }, "/api/log": { tasks: [task], next_before: null } } });
  page.render();
  await page.settle();
  await page.goToSource("sr-6");
  await page.settle();
  assert.equal(page.state.view, "history");
});

test("a jump into All tasks with a filter on takes the filter off, or a card it hides would read as not found", async () => {
  const page = await pageWith({ tasks: [], answers: { "/api/task/sr-3": row(3), "/api/log?chat=tee": { tasks: [], next_before: null }, "/api/log": { tasks: [row(3)], next_before: null } } });
  page.state.historyQuery = { chat: "tee", project: null, search: "words" };
  page.render();
  await page.settle();
  await page.jumpToTask("sr-3", 3);
  await page.settle();
  assert.equal(page.doc.activeElement.dataset.task, "sr-3");
  assert.equal(page.state.historyQuery.chat, null);
  assert.equal(page.state.historyQuery.search, "");
});

// ---- row 5 (note 9): a plan card's Run again as… ----

async function againItems(task) {
  const demo = JSON.parse(readFileSync(new URL("../../demo/status.json", import.meta.url), "utf8"));
  const ready = { ...demo, presets: demo.presets.map((p) => ({ ...p, ready: true, why: null })), split: { ...demo.split, ready: true, why: null }, plan: { ...demo.plan, ready: true, why: null } };
  const page = await loadPage();
  Object.assign(page.state, { status: ready, project: task.project, tasks: [task], team: "route" });
  page.renderStream();
  const stream = page.el("stream");
  stream.querySelector(".more-btn").click();
  page.find("Run again as…", stream).click();
  return stream.all().filter((n) => n.getAttribute("role") === "menuitem").map((n) => n.textContent.trim());
}

test("a plan card's Run again as… offers Route and leaves out Plan", async () => {
  const items = await againItems({ task_id: "sr-p", n: 3, mode: "plan", preset: "redteam", status: "done", outcome: "passed", project: "seed", text: "Plan it.", card_actions: [], next: [], created_at: "2026-11-03T10:00:00Z" });
  assert.ok(items.includes("Route: a new task"), items.join(" | "));
  assert.equal(items.includes("Plan: a new task"), false);
});

test("a route card stays as it was: Plan offered, Route not", async () => {
  const items = await againItems({ task_id: "sr-r", n: 4, mode: "route", status: "done", outcome: "passed", project: "seed", text: "Do it.", card_actions: [], next: [], created_at: "2026-11-03T10:00:00Z" });
  assert.ok(items.includes("Plan: a new task"), items.join(" | "));
  assert.equal(items.includes("Route: a new task"), false);
});

// ---- row 8 (item 5): a finished run's Details ----

test("a finished run, its route_reason cleared, has no route: line in Details; a stopped one keeps it", () => {
  const run = { task_id: "sr-a", n: 5, mode: "auto", status: "done", check_note: "auto finished" };
  assert.equal(detailNotes({ ...run, route_reason: null }, null).some((n) => n.startsWith("route:")), false);
  assert.equal(detailNotes({ ...run, route_reason: "returned: stop here before step 2" }, null).some((n) => n.startsWith("route:")), true);
});

// ---- row 11: the stuck "Loading the steps…" ----

test("a failed read of the steps says so, on each row, in place of Loading the steps…", async () => {
  const demo = JSON.parse(readFileSync(new URL("../../demo/status.json", import.meta.url), "utf8"));
  const bad = await loadPage({ answers: { "/api/setup": { httpStatus: 500 } } });
  Object.assign(bad.state, { status: demo, chat: "garden", tasks: [], team: "route" });
  bad.wire();
  bad.state.setupOpen.set("claude", true);
  await bad.openSettings("setup");
  await bad.settle();
  assert.doesNotMatch(bad.el("stream").textContent, /Loading the steps…/);
  assert.match(bad.el("stream").textContent, /The steps couldn't be read: docs\/SETUP\.md could not be read \(HTTP 500\)/);
});

test("while the read runs the row says Loading; a good read shows the steps", async () => {
  const demo = JSON.parse(readFileSync(new URL("../../demo/status.json", import.meta.url), "utf8"));
  const page = await loadPage({ answers: { "/api/setup": { httpStatus: 0 } } });
  Object.assign(page.state, { status: demo, chat: "garden", tasks: [], team: "route", setupText: null });
  page.wire();
  page.state.view = "settings";
  page.state.settingsTab = "setup";
  page.render();
  assert.match(page.el("stream").textContent, /Loading the steps…/);
  page.state.setupText = "## Claude\n\nSign in with the steps here.\n";
  page.render();
  assert.match(page.el("stream").textContent, /Sign in with the steps here\./);
});
