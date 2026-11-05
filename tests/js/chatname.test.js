// Cleanup 2, row 14: an optional name before a new chat's first send. Blank keeps the timestamp; once a chat has tasks its name
// stays, since the name is its memory tag. Invented data.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { loadPage } from "./pagedom.js";
import { isAutoChatName, chatNameHint } from "../../static/app.js";

const status = JSON.parse(readFileSync(new URL("../../demo/status.json", import.meta.url), "utf8"));
const AUTO = "chat-20261104-2200";
const LISTED = { ...status, chats: [{ name: "garden", tasks: 2 }] };

async function fresh(chat = AUTO, tasks = []) {
  const page = await loadPage({ answers: { "/api/log": { tasks, next_before: null } } });
  Object.assign(page.state, { status: LISTED, chat, project: null, tasks, team: "route", skill: "writing" });
  page.wire();
  page.render();
  await page.settle();
  return page;
}

async function sendWith(page, typed) {
  const field = page.el("chat-name");
  field.value = typed;
  field.fire("input", { target: field });
  page.el("prompt").value = "a picture of a tomato";
  page.state.text = "a picture of a tomato";
  await page.send();
  return page.posts.find((p) => p.path === "/api/run").body;
}

test("only a timestamped name counts as automatic", () => {
  assert.equal(isAutoChatName(AUTO), true);
  assert.equal(isAutoChatName("garden"), false);
  assert.equal(isAutoChatName("chat-notes"), false);
  assert.equal(isAutoChatName(null), false);
});

test("the hint: messy words read as the name, and an existing name says it adds to that chat", () => {
  assert.equal(chatNameHint("Garden Notes!", LISTED).saved, "garden-notes");
  assert.match(chatNameHint("Garden Notes!", LISTED).text, /garden-notes/);
  assert.match(chatNameHint("garden", LISTED).text, /That chat exists: this adds to it/);
  assert.equal(chatNameHint("   ", LISTED).saved, "");
  assert.equal(chatNameHint("   ", LISTED).text, "");
});

test("a new chat's head has the field; blank keeps the timestamp", async () => {
  const page = await fresh();
  assert.ok(page.el("chat-name"));
  const body = await sendWith(page, "");
  assert.equal(body.chat, AUTO);
});

test("typed and messy names send as the name's shape", async () => {
  const body = await sendWith(await fresh(), "Garden Notes!");
  assert.equal(body.chat, "garden-notes");
});

test("an existing name is allowed, and says so as it's typed", async () => {
  const page = await fresh();
  const field = page.el("chat-name");
  field.value = "garden";
  field.fire("input", { target: field });
  assert.match(page.el("chat-name-hint").textContent, /That chat exists: this adds to it/);
  page.el("prompt").value = "x";
  page.state.text = "x";
  await page.send();
  assert.equal(page.posts.find((p) => p.path === "/api/run").body.chat, "garden");
});

test("the field goes after the send, and isn't on a chat with tasks or a named chat", async () => {
  const page = await fresh();
  await sendWith(page, "Garden Notes!");
  assert.equal(page.el("chat-name"), null);
  const full = await fresh(AUTO, [{ task_id: "sr-1", n: 1, chat: AUTO, status: "done", outcome: "passed", text: "x", card_actions: [], next: [] }]);
  assert.equal(full.el("chat-name"), null);
  const named = await fresh("garden");
  assert.equal(named.el("chat-name"), null);
});

test("a listed timestamped chat doesn't flash the field while its tasks load", async () => {
  const page = await loadPage({ answers: { "/api/log": { tasks: [], next_before: null } } });
  Object.assign(page.state, { status: { ...status, chats: [{ name: AUTO, tasks: 3 }] }, chat: AUTO, project: null, tasks: [], team: "route" });
  page.wire();
  page.render();
  assert.equal(page.el("chat-name"), null);
});

test("a quick send and a project send ignore the name", async () => {
  const page = await fresh();
  const field = page.el("chat-name");
  field.value = "Garden Notes";
  field.fire("input", { target: field });
  page.state.quick = true;
  page.el("prompt").value = "x";
  page.state.text = "x";
  await page.send();
  assert.equal(page.posts.find((p) => p.path === "/api/run").body.chat ?? null, null);
  assert.equal(page.state.chat, AUTO);
});

test("a chat with no field leaves nothing in its head: the live check saw the word null there", async () => {
  const named = await fresh("garden");
  const head = named.el("stream").querySelector(".stream-head");
  assert.equal(head.textContent.includes("null"), false, head.textContent);
  assert.match(head.textContent, /^garden/);
});
