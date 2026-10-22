// Build brief 23, F: History (filter by chat or project, search, paging by `next_before`), Log files (the tasks/ folder,
// newest first), the Setup sheet (a row per piece, its live state from status beside its SETUP.md section) and the
// first-run card (every light that is grey or red, with its reason). Fixtures: the demo's status and log, and the
// repo's docs/SETUP.md.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { firstRunItems, historyPath, logFolderView, mergeTasks, setupRows, setupSections, SETUP_PIECES } from "../../static/app.js";

const demo = (name) => JSON.parse(readFileSync(new URL(`../../demo/${name}`, import.meta.url), "utf8"));
const STATUS = demo("status.json");
const TASKS = demo("log.json").tasks;
const SETUP = readFileSync(new URL("../../docs/SETUP.md", import.meta.url), "utf8");

test("History asks sr log for the chat or project, the search and the page before, and nothing empty", () => {
  assert.equal(historyPath({}), "/api/log");
  assert.equal(historyPath({ chat: "garden" }), "/api/log?chat=garden");
  assert.equal(historyPath({ project: "garden-site", search: "  rye loaf " }, "sr-20261019-092100-0005"),
    "/api/log?project=garden-site&search=rye+loaf&before=sr-20261019-092100-0005");
  assert.equal(historyPath({ search: "a&b=c" }), "/api/log?search=a%26b%3Dc");
});

test("a page of older tasks joins the ones already shown, a newer copy of a row winning", () => {
  const older = [{ task_id: "a", n: 1, outcome: null }, { task_id: "b", n: 2, outcome: null }];
  const newer = [{ task_id: "b", n: 2, outcome: "passed" }, { task_id: "c", n: 3, outcome: null }];
  assert.deepEqual(mergeTasks(older, newer).map((t) => [t.n, t.outcome]), [[1, null], [2, "passed"], [3, null]]);
});

test("SETUP.md splits into one section per piece the sheet shows, and an intro", () => {
  const found = setupSections(SETUP);
  for (const [, title] of SETUP_PIECES) assert.ok(found.sections[title], `no ## ${title} in docs/SETUP.md`);
  assert.match(found.sections.ChatGPT, /codex login/);
  assert.match(found.sections.Memory, /hindsight-api-slim\[local-onnx,embedded-db\]/);
  assert.match(found.intro, /Setting up Super Router/);
  assert.equal(found.sections["Before you start"].includes("requirements.txt"), true);
});

test("the guide tells no one to run sr probe or sr memory (rules: no maintenance step), and names no person or path", () => {
  assert.equal(/sr probe|sr memory/.test(SETUP), false);
  assert.equal(/\/Users\//.test(SETUP), false);  // the name and the handle: publish.py's scan covers SETUP.md
});

test("a Setup row per piece with its live state, as the top strip words it, and when each agent was checked", () => {
  const rows = setupRows(STATUS);
  assert.deepEqual(rows.map((r) => r.name), ["Claude", "ChatGPT", "Cursor", "Grok Bot", "Jev", "Memory"]);
  const by = Object.fromEntries(rows.map((r) => [r.key, r]));
  assert.deepEqual([by.claude.tone, by.claude.state], ["ok", "online"]);
  assert.deepEqual([by.chatgpt.tone, by.chatgpt.state], ["bad", "signed out"]);
  assert.deepEqual([by.grok.tone, by.grok.state], ["muted", "not set up"]);
  assert.deepEqual([by.cursor.tone, by.cursor.state], ["bad", "off"]);
  assert.equal(by.claude.checkedAt, STATUS.agents.find((a) => a.name === "claude").checked_at);
  assert.deepEqual([by.jev.tone, by.jev.state, by.jev.detail], ["muted", "not set up", "Jev isn't set up: no JEV_API_KEY in .env"]);
  assert.equal(by.memory.state, "starting");
});

test("the first-run card lists every grey or red light with its reason, and nothing when all are green", () => {
  const items = firstRunItems(STATUS);
  assert.deepEqual(items.map((i) => i.key), ["chatgpt", "cursor", "grok", "jev"]);
  assert.match(items.find((i) => i.key === "chatgpt").reason, /codex login/);
  assert.match(items.find((i) => i.key === "cursor").reason, /safety check/);
  const green = structuredClone(STATUS);
  for (const a of green.agents) Object.assign(a, { configured: true, live: true, online: true, reason: null, probe: { state: "passed" },
    available: true, why: null, why_code: null });
  green.jev = { ...green.jev, configured: true, available: true, why: null };
  green.memory = { ...green.memory, online: true, starting: false };
  assert.deepEqual(firstRunItems(green), []);
});

test("a Log files row names its task when the log has it, else its id, and each file by its round", () => {
  const task = TASKS.find((t) => t.outcome === "fixed");
  const folder = { task_id: task.task_id, files: [{ name: "01-do-claude.md", path: `tasks/${task.task_id}/01-do-claude.md`, root: "tasks",
    kind: "text", size: 10, round: { order: 1, role: "do", agent: "claude" } }] };
  const view = logFolderView(folder, TASKS);
  assert.equal(view.title, `#${task.n} · ${task.text}`);
  assert.deepEqual(view.files.map((f) => f.name), ["01 · build · Claude"]);
  assert.equal(logFolderView({ task_id: "sr-20200101-000000-0000", files: [] }, TASKS).title, "sr-20200101-000000-0000");
});

test("an unknown light is not a setup problem: the first-run card leaves it out, and Jev's reads unknown", () => {
  const unknown = structuredClone(STATUS);
  // not checked yet: the router says available (nothing is known against it), except Grok Bot, which isn't set up
  unknown.agents = unknown.agents.map((a) => ({ ...a, online: null, reason: null, checked_at: null, probe: null,
    ...(a.name === "grok" ? {} : { available: true, why: null, why_code: null }) }));
  unknown.memory = null;
  unknown.jev = null;
  assert.deepEqual(firstRunItems(unknown).map((i) => i.key), ["grok"]);  // only the one not configured
  const jev = setupRows(unknown).find((r) => r.key === "jev");
  assert.deepEqual([jev.state, jev.detail], ["unknown", "not checked yet"]);
});
