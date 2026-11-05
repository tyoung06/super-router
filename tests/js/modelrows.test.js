// Cleanup 2, row 3: the 12 Models rows tell the truth about who does the work. Invented data.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { loadPage } from "./pagedom.js";
import { modelsSetupSelects, modelRows, skillName, skillRowWords, unusedPickWords } from "../../static/app.js";

const read = (name) => JSON.parse(readFileSync(new URL(`../../demo/${name}`, import.meta.url), "utf8"));
const OPUS = "claude-opus-5-5";
const row = (key, agent, state, extra = {}) => ({ key, agent, doer: agent, state, comes_back: false, unused: [], model: null, effort: null, name: null, ...extra });
const ROWS = [
  row("x_social_pulse", "grok", "service"), row("meta_social_trends", "grok", "service"), row("make_media", "grok", "service"),
  row("computer_use", null, "not_routed"), row("web_research", "chatgpt", "choice"), row("read_media", "claude", "choice"), row("code", "claude", "choice", { model: OPUS, name: "Opus 5.5" }),
  row("writing", "claude", "choice"), row("planning", "claude", "choice"), row("bulk_text", "claude", "choice"), row("quick_answer", "claude", "choice"), row("recall", "claude", "choice"),
];
const demo = read("status.json");
const withRows = (skills) => ({ ...demo, models: { ...demo.models, setup: { ...demo.models.setup, skills } } });

test("each row names its real doer in plain words", () => {
  const found = modelsSetupSelects(withRows(ROWS)).skills;
  assert.deepEqual(found.map((s) => s.label), ["X research · Grok Bot", "Meta research · Grok Bot", "Make media · Grok Bot", "Computer use", "Web research · ChatGPT",
    "Read media · Claude", "Code · Claude", "Writing · Claude", "Planning · Claude", "Bulk text · Claude", "Quick answer · Claude", "Recall · Claude"]);
  assert.equal(skillName("a_new_skill"), "a new skill");
});

test("a row with no choice has no options and its own words", () => {
  const found = modelsSetupSelects(withRows(ROWS)).skills;
  assert.deepEqual(found[0].options, []);
  assert.equal(found[0].words, "its service picks the model");
  assert.equal(found[3].words, "not routed");
  assert.equal(found[4].words, null);
  assert.ok(found[4].options.length);
  assert.ok(found[4].options.every((o) => !/claude-/.test(o.value)));  // ChatGPT's models on ChatGPT's row
  assert.equal(skillRowWords({ state: "service", agent: "grok", comes_back: true }), "its service picks the model · comes back without Grok Bot");
});

test("a row follows its stand-in: Meta research reads ChatGPT, with ChatGPT's models", () => {
  const skills = ROWS.map((r) => (r.key === "meta_social_trends" ? row(r.key, "chatgpt", "choice") : r));
  const meta = modelsSetupSelects(withRows(skills)).skills[1];
  assert.equal(meta.label, "Meta research · ChatGPT");
  assert.equal(meta.state, "choice");
  assert.ok(meta.options.some((o) => /gpt/.test(o.value)));
});

test("the sort: yours, then rows with a choice, then the rest", () => {
  const { shown, more } = modelRows(modelsSetupSelects(withRows(ROWS)).skills);
  const order = [...shown, ...more].map((r) => r.key);
  assert.equal(order[0], "code");
  assert.deepEqual(order.slice(-4), ["x_social_pulse", "meta_social_trends", "make_media", "computer_use"]);
  assert.deepEqual(shown.map((r) => r.key), ["code", "web_research", "read_media", "writing", "planning"]);
});

test("the old pick's words name the two doors for Claude, and the one door for another agent", () => {
  assert.equal(unusedPickWords({ agent: "claude", model: OPUS, name: "Opus 5.5", effort: null }),
    "Your earlier pick for Claude (Opus 5.5) isn't used: it reaches only a task you send as @claude, or a text-only draft.");
  assert.equal(unusedPickWords({ agent: "cursor", model: "grok-4.7-low", name: "Grok 4.7 low", effort: null }),
    "Your earlier pick for Cursor (Grok 4.7 low) isn't used: it reaches only a task you send as @cursor.");
  assert.match(unusedPickWords({ agent: "claude", model: null, name: null, effort: "high" }), /Claude \(effort high\)/);
});

async function settings(skills) {
  const page = await loadPage({ answers: { "/api/setup": { text: "" } } });
  Object.assign(page.state, { status: withRows(skills), chat: "garden", tasks: [], team: "route" });
  page.wire();
  page.state.modelsFolds.add("skills");
  page.state.setupOpen.set("models", true);
  await page.openSettings("models");
  page.render();
  await page.settle();
  return page;
}

test("the page draws no Change on the four rows without a choice, and one on the rest", async () => {
  const page = await settings(ROWS);
  const rows = page.el("stream").querySelectorAll(".models-row-line").filter((r) => /·|Computer use/.test(r.querySelector(".models-row-name").textContent));
  const of = (name) => rows.find((r) => r.querySelector(".models-row-name").textContent === name);
  for (const name of ["X research · Grok Bot", "Meta research · Grok Bot", "Make media · Grok Bot", "Computer use"]) {
    assert.ok(of(name), name);
    assert.equal(page.find("Change", of(name)), null, name);
  }
  assert.ok(page.find("Change", of("Web research · ChatGPT")));
  assert.equal(of("Computer use").querySelector(".models-row-now").textContent, "not routed");
});

test("an old pick shows its note and Clear, which runs sr models clear; Clear is never bright", async () => {
  const skills = ROWS.map((r) => (r.key === "x_social_pulse" ? { ...r, unused: [{ agent: "claude", model: OPUS, name: "Opus 5.5", effort: null }] } : r));
  const page = await settings(skills);
  const note = page.el("stream").querySelector(".models-unused");
  assert.match(note.textContent, /Your earlier pick for Claude \(Opus 5\.5\) isn't used/);
  const clear = page.find("Clear", note);
  assert.equal(clear.classList.contains("btn-quiet"), true);
  clear.click();
  await page.settle();
  assert.deepEqual(page.posts.find((p) => p.body.action === "models_clear").body, { action: "models_clear", selector: { skill: "x_social_pulse" }, agent: "claude" });
});
