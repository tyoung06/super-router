// Build brief 24, D (decisions 13, 15 and 17): the page reads availability from status and never works it out. Each
// Setup row says what happens without its piece, from status's skills and presets; a team whose chain can't run is
// greyed with status's reason; a slot whose default isn't available shows it greyed with why, and the agent the router
// fills it with is chosen; a card's one line comes from the router (`card_line`), and Details carry the takeover and a
// late Grok answer; without Jev the composer asks for the skill before Send. Fixtures: the demo's documents.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import {
  chipViews, detailNotes, floorView, jevBox, jevWords, lateWords, rescueOffers, sendRequest, setupRows, skillPick,
  slotViews, withoutLine,
} from "../../static/app.js";

const demo = (name) => JSON.parse(readFileSync(new URL(`../../demo/${name}`, import.meta.url), "utf8"));
const STATUS = demo("status.json");
const TASKS = demo("log.json").tasks;
const SHOWS = Object.fromEntries(readdirSync(new URL("../../demo/tasks/", import.meta.url)).map((f) => [f.replace(/\.json$/, ""), demo(`tasks/${f}`)]));
const find = (pred) => { const task = TASKS.find(pred); assert.ok(task, "no such demo task"); return task; };
const base = { team: "route", text: "plan the harvest supper", chat: "garden", project: null, quick: false, files: [], web: false, slots: {} };

// ---------- the Setup sheet: what happens without each piece ----------

test("a missing piece's Setup row says what happens without it, from status's skills and presets", () => {
  const by = Object.fromEntries(setupRows(STATUS).map((r) => [r.key, r]));
  assert.equal(by.claude.without, "nothing runs: Claude is required.");   // said always: decision 2
  // The owner, 21 Oct: X research is Grok Bot's alone, as images are; only Meta research has a stand-in
  assert.match(by.grok.without, /^meta_social_trends \(done without Meta\) goes to Claude; x_social_pulse and make_media come back;/);
  assert.doesNotMatch(by.grok.without, /done without X/);
  assert.match(by.chatgpt.without, /web_research goes to Claude/);
  assert.match(by.chatgpt.without, /are delivered unchecked/);
  assert.match(by.chatgpt.without, /research-build, collab, versus, redteam and vote can't run\.$/);
  assert.equal(by.cursor.without, "nothing else changes.");
  assert.equal(by.jev.without, "you pick each routed task's skill.");
  assert.equal(by.memory.without, null);
});

test("an available piece says nothing; Claude's row always says it is required", () => {
  assert.equal(withoutLine("claude", STATUS), "nothing runs: Claude is required.");
  const up = structuredClone(STATUS);
  for (const a of up.agents) Object.assign(a, { available: true, why: null, why_code: null });
  assert.equal(withoutLine("grok", up), null);
});

test("a filled slot reads as the preset using the other agent", () => {
  const status = structuredClone(STATUS);
  status.agents.find((a) => a.name === "chatgpt").available = true;
  const rb = status.presets.find((p) => p.name === "research-build");
  rb.filled = [{ slot: "research", agent: "chatgpt", default: "grok", why: "Grok Bot isn't set up: no inbox repo in settings" }];
  assert.match(withoutLine("grok", status), /research-build uses ChatGPT for its research slot/);
});

// ---------- teams and slots ----------

test("a team greys only when status says it can't run, and a ready team stays usable with an agent out", () => {
  const status = structuredClone(STATUS);
  for (const p of status.presets) Object.assign(p, { ready: p.name !== "vote", why: p.name === "vote" ? "vote can't run now: x" : null });
  const chips = Object.fromEntries(chipViews(status).map((c) => [c.key, c]));
  assert.deepEqual([chips["research-build"].disabled, chips.vote.disabled, chips.vote.reason], [false, true, "vote can't run now: x"]);
});

test("a slot whose default isn't available shows it greyed with why, and the router's fill is the one chosen", () => {
  const rb = structuredClone(STATUS.presets.find((p) => p.name === "research-build"));
  const why = "Grok Bot isn't set up: no inbox repo in settings";
  rb.filled = [{ slot: "research", agent: "chatgpt", default: "grok", why }];
  rb.slots.find((s) => s.name === "research").allowed = ["claude", "chatgpt"];
  const research = slotViews(rb, {}, STATUS).slots.find((s) => s.name === "research");
  assert.deepEqual([research.value, research.filled], ["chatgpt", { agent: "chatgpt", why }]);
  assert.deepEqual(research.options.map((o) => [o.agent, o.disabled, o.reason]),
    [["grok", true, why], ["claude", false, null], ["chatgpt", false, null]]);
  // the page sends no flag for a slot you left alone: the router fills it, and says so on the card
  assert.equal(sendRequest({ ...base, team: "research-build", slots: {} }, { ...STATUS, presets: [rb] }).slots, undefined);
});

// ---------- the card ----------

test("the card's one line is the router's own, for a stand-in, a takeover and an overdue takeover", () => {
  const lines = TASKS.map((t) => t.card_line).filter(Boolean);
  assert.ok(lines.includes("ChatGPT did this · Grok Bot isn't set up · done without Meta"));
  assert.ok(lines.includes("ChatGPT took over the first call · Claude hit its plan limit"));
  assert.ok(lines.includes("ChatGPT took over the first call · Grok Bot was overdue · done without Meta"));
  assert.ok(!lines.some((line) => line.includes("done without X")));   // X research has no stand-in (the owner, 21 Oct)
});

test("Details carry the takeover in full and the late Grok answer, kept and never used", () => {
  const task = find((t) => t.late);
  const notes = detailNotes(task, SHOWS[task.task_id]);
  assert.ok(notes.includes("takeover: ChatGPT took over the first call (Grok Bot was overdue)"));
  assert.ok(notes.includes("late answer: Grok Bot's answer came after the takeover; kept, not used"));
  assert.equal(lateWords({ state: "out" }), "late answer: Grok Bot's answer may still come; it won't be used");
  assert.equal(lateWords({ state: "expired" }), "late answer: none came");
});

test("a task the router took over offers no resume: nothing is left for you to do", () => {
  const task = find((t) => t.takeover && t.takeover.code === "plan_limit");
  assert.deepEqual(rescueOffers(task).map((o) => o.key), []);
});

// ---------- without Jev: you pick the skill ----------

test("without Jev, Route asks for the skill before Send, and the request carries it", () => {
  assert.equal(STATUS.jev.available, false);
  const none = skillPick(base, STATUS);
  assert.deepEqual([none.needed, none.chosen, none.why], [true, null, "Jev isn't set up: no JEV_API_KEY in .env"]);
  assert.ok(none.options.some((o) => o.key === "writing") && !none.options.some((o) => o.key === "computer_use"));
  assert.equal(sendRequest(base, STATUS).skill, undefined);
  assert.equal(sendRequest({ ...base, skill: "planning" }, STATUS).skill, "planning");
  assert.equal(skillPick({ ...base, text: "@claude plan the supper" }, STATUS).needed, false);   // an override needs none
  assert.equal(skillPick({ ...base, team: "collab" }, STATUS).needed, false);                     // a team names its agents
  const withJev = { ...STATUS, jev: { ...STATUS.jev, available: true, why: null } };
  assert.equal(skillPick({ ...base, skill: "planning" }, withJev).needed, false);
  assert.equal(sendRequest({ ...base, skill: "planning" }, withJev).skill, undefined);
});

test("the skill picker says which skills need Grok Bot, in status's words, and keeps them pickable", () => {
  // The owner, 21 Oct: x_social_pulse is Grok Bot's alone, as make_media is; picking it sends it, and the router hands it back
  const labels = Object.fromEntries(skillPick(base, STATUS).options.map((o) => [o.key, o.label]));
  assert.equal(labels.x_social_pulse, "x social pulse (needs Grok Bot)");
  assert.equal(labels.make_media, "make media (needs Grok Bot)");
  assert.equal(labels.meta_social_trends, "meta social trends");   // Meta research still has its stand-in
  assert.equal(sendRequest({ ...base, skill: "x_social_pulse" }, STATUS).skill, "x_social_pulse");
});

test("Jev's box and a returned task say Jev isn't set up in the router's words", () => {
  assert.deepEqual(jevBox({ team: "route", missing: "Jev isn't set up: pick the skill" }),
    { mode: "missing", text: "Jev isn't set up: pick the skill" });
  const task = find((t) => t.jev && t.jev.status === "not_set_up");
  assert.equal(jevWords(task.jev), "Jev isn't set up: pick the skill");
  const view = floorView(task, STATUS);
  assert.equal(view.title, "Jev isn't set up");
  assert.equal(jevBox({ team: "route", task }).text, "Jev isn't set up: pick the skill");
});

test("the page's refused team shows the router's words naming the slot", () => {
  const run = demo("runs.json").runs.find((r) => r.envelope && r.envelope.reason_code === "slot_refused");
  assert.match(run.message, /^Refused: vote can't run now: slot c \(Grok Bot\): /);
});

test("Claude whose sign-in check didn't answer is tried anyway, amber with the router's words", async () => {
  const { agentView, pillWords } = await import("../../static/app.js");
  const claude = { ...STATUS.agents.find((a) => a.name === "claude"), available: true, online: false,
    why: "Claude's sign-in check didn't answer; trying anyway", why_code: "unreachable" };
  const view = agentView(claude, []);
  assert.deepEqual([view.tone, view.state, view.detail[0], pillWords(claude, view)],
    ["warn", "check didn't answer", "Claude's sign-in check didn't answer; trying anyway", "check didn't answer"]);
});

test("one call this week reads in the singular", async () => {
  const { agentView } = await import("../../static/app.js");
  const up = { available: true, why: null, why_code: null, online: true, live: true, configured: true };
  const words = (name, n) => agentView({ ...STATUS.agents.find((a) => a.name === name), ...up, calls_this_week: n }, []).detail[0];
  assert.equal(words("grok", 1), "1 call this week");
  assert.equal(words("grok", 0), "0 calls this week");
  assert.equal(words("grok", 2), "2 calls this week");
  assert.match(words("cursor", 1), / · 1 call this week$/);
});
