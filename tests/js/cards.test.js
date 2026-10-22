// Build brief 23, C (decision 10 and the task card): the markdown renderer escapes by construction (a tree of plain
// objects drawn with textContent; never an <img>, never raw HTML; https:// links only), and a card's stage strip,
// routing receipt, checker bar and file cards come from the log row and `sr show --json`. Fixtures: the demo's documents.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { checkView, demoClock, elapsed, fileCards, humanSize, markdown, receiptView, resultHeading, roleWords, roundName, stagesView } from "../../static/app.js";

const demo = (name) => JSON.parse(readFileSync(new URL(`../../demo/${name}`, import.meta.url), "utf8"));
const TASKS = demo("log.json").tasks;
const SHOWS = Object.fromEntries(readdirSync(new URL("../../demo/tasks/", import.meta.url)).map((f) => [f.replace(/\.json$/, ""), demo(`tasks/${f}`)]));
const find = (pred) => { const task = TASKS.find(pred); return [task, SHOWS[task.task_id]]; };
const flat = (nodes) => JSON.stringify(nodes);

// ---------- markdown ----------

test("headings, paragraphs, lists, code, tables, quotes and rules", () => {
  const blocks = markdown("# Title\n\nSome **bold** and *em* and `code`.\n\n- one\n- two\n\n1. first\n2. second\n\n```py\nprint(1)\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n> quoted\n\n---");
  assert.deepEqual(blocks.map((b) => b.type), ["h1", "p", "ul", "ol", "pre", "table", "blockquote", "hr"]);
  assert.deepEqual(blocks[1].children.map((c) => c.type), ["text", "strong", "text", "em", "text", "code", "text"]);
  assert.deepEqual([blocks[4].lang, blocks[4].text], ["py", "print(1)"]);
  assert.equal(blocks[5].rows.length, 1);
});

test("raw HTML stays text and never becomes an element", () => {
  const text = '<script>alert(1)</script><img src=x onerror=alert(1)> <b>hi</b>';
  const blocks = markdown(text);
  assert.deepEqual(blocks, [{ type: "p", children: [{ type: "text", text }] }]);
});

test("a markdown image is never an image; a link is drawn only for https://", () => {
  assert.equal(flat(markdown("![x](https://example.org/a.png)")).includes('"type":"image"'), false);
  assert.equal(flat(markdown("![x](https://example.org/a.png)")).includes('"type":"link"'), false);
  const ok = markdown("[the docs](https://example.org/docs) and https://example.org/plain.");
  assert.deepEqual(ok[0].children.filter((c) => c.type === "link").map((c) => c.href), ["https://example.org/docs", "https://example.org/plain"]);
  for (const bad of ["[x](javascript:alert(1))", "[x](http://example.org)", "[x](data:text/html,hi)", "[x](//evil.example)"]) {
    assert.equal(flat(markdown(bad)).includes('"type":"link"'), false, bad);
  }
});

test("a code block keeps its text as written, markdown and HTML included", () => {
  const blocks = markdown("```\n<b>**not bold**</b>\n```");
  assert.deepEqual(blocks, [{ type: "pre", lang: null, text: "<b>**not bold**</b>" }]);
});

test("a line that is only an HTML comment (the router's handoff markers) is left out of the preview", () => {
  assert.deepEqual(markdown("<!-- sr:start -->\nHello\n<!-- sr:end -->"), [{ type: "p", children: [{ type: "text", text: "Hello" }] }]);
  assert.deepEqual(markdown("a <!-- inline --> b")[0].children, [{ type: "text", text: "a <!-- inline --> b" }]);
});

test("a fence indented under a list step is a code block, its indent taken off", () => {
  const blocks = markdown("1. Sign in:\n\n   ```\n   codex login\n   ```\n\n2. Done.");
  assert.deepEqual(blocks.map((b) => b.type), ["ol", "pre", "ol"]);
  assert.deepEqual([blocks[1].text, blocks[1].lang], ["codex login", null]);
});

test("an unclosed fence takes the rest; a 4,000-character word is one text node", () => {
  assert.equal(markdown("```\nnever closed").at(0).type, "pre");
  const word = "x".repeat(4000);
  assert.deepEqual(markdown(word), [{ type: "p", children: [{ type: "text", text: word }] }]);
});

// ---------- a card's parts ----------

test("the stage strip comes from the calls, Jev first on a routed task, each stage naming its round file", () => {
  const [task, show] = find((t) => t.outcome === "fixed");
  const stages = stagesView(task, show);
  assert.deepEqual(stages.map((s) => s.label), ["Jev → writing", "build", "check", "fix", "re-check"]);
  assert.deepEqual(stages.map((s) => s.state), ["ok", "ok", "warn", "ok", "ok"]);
  assert.match(stages[1].file, /^tasks\/sr-.*\/01-do-claude\.md$/);
  const [rb, rbShow] = find((t) => t.preset === "research-build");
  assert.deepEqual(stagesView(rb, rbShow).map((s) => [s.label, s.agent]), [["research", "grok"], ["build", "claude"], ["check", "chatgpt"]]);
});

test("a stopped call is bad and an open call is live", () => {
  const [task, show] = find((t) => t.outcome === "process_ended");
  assert.equal(stagesView(task, show).at(-1).state, "bad");
  const [grok, grokShow] = find((t) => t.waiting_on === "grok");
  assert.equal(stagesView(grok, grokShow).at(-1).state, "live");
});

test("the receipt: Jev's label and confidence, memory entries, who did what, rounds and time", () => {
  const [task, show] = find((t) => t.skill === "recall");
  const pills = receiptView(task, show).map((p) => p.text + (p.value || ""));
  assert.equal(pills[0], `Jev → recall ${task.jev.confidence.toFixed(2)}`);
  assert.match(pills.join("|"), /memory: \d+ entries/);
  assert.match(pills.join("|"), /build: Claude\|check: ChatGPT/);
  assert.match(pills.at(-1), /^1 round · \d+s$/);
  const [versus, vShow] = find((t) => t.preset === "versus");
  assert.equal(receiptView(versus, vShow)[0].text, "Jev not asked: team chosen");
  const [project, pShow] = find((t) => t.project);
  assert.match(receiptView(project, pShow).map((p) => p.text + (p.value || "")).join("|"), /handoff: attached/);
});

test("a task waiting on the owner counts the agents' time only; a working task counts to now", () => {
  const [pick, pickShow] = find((t) => t.waiting_on === "pick");
  const expected = elapsed(pick.created_at, pick.updated_at);
  assert.equal(receiptView(pick, pickShow, "2030-01-01T00:00:00Z").at(-1).text.endsWith(expected), true);
  const [grok, grokShow] = find((t) => t.waiting_on === "grok");
  const later = new Date(Date.parse(grok.created_at) + 90_000).toISOString();
  assert.match(receiptView(grok, grokShow, later).at(-1).text, /1m 30s$/);
});

test("the checker bar: passed with the original and memory; fixed; failed twice; unchecked with why; the vote", () => {
  const [passed, pShow] = find((t) => t.outcome === "passed" && t.chat && t.mode === "route" && t.skill === "writing");
  assert.deepEqual([checkView(passed, pShow).tone, checkView(passed, pShow).title], ["ok", "Checker passed"]);
  assert.match(checkView(passed, pShow).detail, /^ChatGPT, round 1 · saved to this chat's memory$/);
  const [fixed, fShow] = find((t) => t.outcome === "fixed");
  assert.equal(checkView(fixed, fShow).title, "Passed after one fix");
  assert.match(checkView(fixed, fShow).original, /01-do-claude\.md$/);
  const [failed, xShow] = find((t) => t.outcome === "failed_check" && t.mode === "route");
  assert.deepEqual([checkView(failed, xShow).tone, checkView(failed, xShow).detail], ["bad", "not passed after one fix round"]);
  const [quick, qShow] = find((t) => t.skill === "quick_answer" && t.mode === "route");
  assert.equal(checkView(quick, qShow).detail, "a quick answer needs no check");
  const [vote, voShow] = find((t) => t.preset === "vote" && t.outcome === "passed");
  assert.match(checkView(vote, voShow).title, /^Monthly, 2 of 3$/);
});

test("file cards are the task's inputs and outputs, named from their files, never invented", () => {
  const files = [
    { name: "01-do-claude.md", root: "tasks", path: "tasks/x/01-do-claude.md", kind: "text", size: 10, round: { order: 1, role: "do", agent: "claude" } },
    { name: "raised-bed.png", root: "media/in", path: "media/in/x/raised-bed.png", kind: "image", size: 2048, round: null },
    { name: "tomato-badge.png", root: "media/out", path: "media/out/x/tomato-badge.png", kind: "image", size: 300, round: null },
  ];
  assert.deepEqual(fileCards(files).map((c) => [c.name, c.meta]), [["raised-bed.png", "input · 2 KB"], ["tomato-badge.png", "made by Grok · 300 B"]]);
  assert.equal(roundName(files[0]), "01 · build · Claude");
  assert.equal(roundName({ name: "03-build-a-claude.md", round: { order: 3, role: "build-a", agent: "claude" } }), "03 · build · Claude");
  assert.equal(roleWords("reask-do"), "build re-ask");
  assert.equal(humanSize(3 * 1024 * 1024), "3.0 MB");
});

test("elapsed time reads like a person would say it", () => {
  assert.equal(elapsed("2026-10-19T09:00:00Z", "2026-10-19T09:00:52Z"), "52s");
  assert.equal(elapsed("2026-10-19T09:00:00Z", "2026-10-19T09:01:06Z"), "1m 06s");
  assert.equal(elapsed("2026-10-19T09:00:00Z", "2026-10-19T11:05:00Z"), "2h 05m");
  assert.equal(elapsed("nonsense", "2026-10-19T09:00:00Z"), null);
});

test("a result says what it is: an answer, the furthest a double fail got, or what the router kept at a stop", () => {
  assert.equal(resultHeading(find((t) => t.outcome === "fixed")[0]), "Claude · writing");
  assert.equal(resultHeading(find((t) => t.outcome === "failed_check" && t.mode === "route")[0]),
    "Claude · code · the furthest result: after the fix, and its re-check failed");
  assert.equal(resultHeading(find((t) => t.outcome === "plan_limit")[0]), "What the router kept when it stopped");
  assert.equal(resultHeading(find((t) => t.preset === "versus" && t.outcome === "picked")[0]), "Claude · Versus");
});

test("the demo's Grok timers agree with their notes: the minutes since the send, at the demo's clock", () => {
  const status = JSON.parse(readFileSync(new URL("../../demo/status.json", import.meta.url), "utf8"));
  const now = demoClock(TASKS, status);
  const grok = TASKS.filter((t) => t.waiting_on === "grok");
  assert.deepEqual(grok.map((t) => t.check_note.split(",")[0]).sort(), ["overdue: grok", "waiting: grok"]);
  for (const task of grok) {
    const minutes = Math.floor((Date.parse(now) - Date.parse(task.created_at)) / 60000);
    assert.equal(task.check_note.endsWith(`, ${minutes} min`), true, `${task.check_note} vs ${minutes} min on the timer`);
    assert.match(receiptView(task, SHOWS[task.task_id], now).at(-1).text, new RegExp(`^${minutes}m \\d\\ds$`));
  }
});

import { middleTruncate, resultPreview } from "../../static/app.js";

test("a huge result shows its first 20,000 characters, cut at a line; a short one shows whole", () => {
  const line = "north,Maple Street,2026-W42,1284\n";
  const big = line.repeat(70000);
  const preview = resultPreview(big);
  assert.equal(preview.cut, true);
  assert.ok(preview.text.length <= 20000 && preview.text.endsWith("1284"));
  assert.deepEqual(resultPreview("short"), { text: "short", cut: false });
});

test("a long file name is cut in the middle, keeping its end and extension", () => {
  const name = "Q3-2026-board-review-deck-final-v12-APPROVED-by-legal-and-finance-for-the-quarterly-meeting.pdf";
  const short = middleTruncate(name, 40);
  assert.equal(short.length, 40);
  assert.ok(short.startsWith("Q3-2026-board") && short.endsWith("meeting.pdf") && short.includes("…"));
  assert.equal(middleTruncate("raised-bed.png", 40), "raised-bed.png");
});
