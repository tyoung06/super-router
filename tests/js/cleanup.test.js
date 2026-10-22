// Build brief 23, G (the owner's cleanup, presentation only): the agent bar's one-line words, a card's one-line verdict
// and its time; the raw words move behind Details. Nothing here changes what a button runs.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { agentView, demoClock, detailNotes, pillWords, taskTime, verdictLine } from "../../static/app.js";

const demo = (name) => JSON.parse(readFileSync(new URL(`../../demo/${name}`, import.meta.url), "utf8"));
const STATUS = demo("status.json");
const TASKS = demo("log.json").tasks;
const SHOWS = Object.fromEntries(readdirSync(new URL("../../demo/tasks/", import.meta.url)).map((f) => [f.replace(/\.json$/, ""), demo(`tasks/${f}`)]));
const find = (pred) => { const task = TASKS.find(pred); assert.ok(task, "no such demo task"); return [task, SHOWS[task.task_id]]; };
const line = (pred) => { const [task, show] = find(pred); return verdictLine(task, show); };

test("the agent bar's words: online, signed out, not set up, and off with its safety check", () => {
  // brief 24 (decision 15): each word from status's `available` and `why_code`
  const words = Object.fromEntries(STATUS.agents.map((a) => [a.name, pillWords(a, agentView(a, []))]));
  assert.deepEqual(words, { claude: "online", chatgpt: "signed out", grok: "not set up", cursor: "off · safety check" });
});

test("a card's verdict in one line, as the owner wrote them", () => {
  assert.deepEqual(line((t) => t.outcome === "passed" && t.mode === "route" && t.skill === "writing" && t.chat),
    { tone: "ok", text: "Passed · ChatGPT" });
  assert.deepEqual(line((t) => t.outcome === "fixed"), { tone: "ok", text: "Fixed · ChatGPT, round 2" });
  assert.equal(line((t) => t.skill === "quick_answer" && t.mode === "route").text, "Unchecked · a quick answer needs no check");
  assert.equal(line((t) => t.outcome === "failed_check" && t.mode === "route").text, "Failed twice · ChatGPT");
  assert.equal(line((t) => t.preset === "vote" && t.outcome === "passed").text, "Monthly · 2 of 3 agree");
  assert.equal(line((t) => t.preset === "versus" && t.outcome === "picked").text, "Picked A · Claude");
  assert.equal(line((t) => t.outcome === "plan_limit").text, "Stopped · plan limit on Claude");
  assert.equal(line((t) => t.check_note === "overdue: grok, 12 min").text, "Waiting on Grok · overdue, 12 min");
  assert.equal(line((t) => t.check_note === "waiting: grok, 6 min").text, "Waiting on Grok · 6 min");
  assert.deepEqual(line((t) => t.waiting_on === "pick"), { tone: "warn", text: "Waiting for your pick" });
});

test("a check that failed to run reads as such; its raw words go behind Details", () => {
  const task = { task_id: "x", status: "done", outcome: "unchecked", skill: "writing", agent: "claude", checker: "chatgpt",
    check_note: "check failed: codex exited 1: Selected model is at capacity" };
  const show = { calls: [{ kind: "do", agent: "claude", status: "done" }, { kind: "check", agent: "chatgpt", status: "failed", reason_code: null }] };
  assert.equal(verdictLine(task, show).text, "Unchecked · ChatGPT's check didn't run");
  assert.deepEqual(detailNotes(task, show), ["note: check failed: codex exited 1: Selected model is at capacity", "check · ChatGPT failed"]);
});

test("a card's time: to now while it runs, to its last change once it waits on you", () => {
  const now = demoClock(TASKS, STATUS);
  const [grok] = find((t) => t.check_note === "waiting: grok, 6 min");
  assert.match(taskTime(grok, now), /^6m \d\ds$/);
  const [pick] = find((t) => t.waiting_on === "pick");
  assert.equal(taskTime(pick, "2030-01-01T00:00:00Z"), taskTime(pick, now));
});

test("before a card's details load, a picked versus or a passed vote never claims what it can't see yet", () => {
  const [picked] = find((t) => t.preset === "versus" && t.outcome === "picked");
  assert.equal(verdictLine(picked, null).text, "Picked");
  const [vote] = find((t) => t.preset === "vote" && t.outcome === "passed");
  assert.equal(verdictLine(vote, null).text, "Passed by vote");
});
