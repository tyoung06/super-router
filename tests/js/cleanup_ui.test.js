// The small UI cleanup brief, row by row, on the demo's own tasks and invented ones. Fake data.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { loadPage } from "./pagedom.js";
import * as app from "../../static/app.js";

const read = (name) => JSON.parse(readFileSync(new URL(`../../demo/${name}`, import.meta.url), "utf8"));
const LOG = read("log.json");
const STATUS = read("status.json");
const CSS_TEXT = readFileSync(new URL("../../static/app.css", import.meta.url), "utf8");
const SOURCE = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const byN = (n) => LOG.tasks.find((t) => t.n === n);
const showOf = (n) => read(`tasks/${byN(n).task_id}.json`);
const words = (n) => app.stepPills(byN(n), showOf(n)).map((p) => p.text);
const tones = (n) => app.stepPills(byN(n), showOf(n)).map((p) => p.tone);

const task = (over = {}) => ({ task_id: "sr-x", n: 500, mode: "route", status: "done", outcome: "passed", agent: "claude", checker: "chatgpt",
  jev: { status: "ok", label: "writing" }, steps: { chain: null, now: null }, ...over });
const call = (over = {}) => ({ call_id: `c${Math.random()}`, kind: "do", role: null, stage: null, agent: "claude", status: "done", verdict: null, reason_code: null, round_file: null, ...over });
const one = (c, over) => app.stepPills(task({ checker: null, ...over }), { calls: [call(c)] })[0];

// ---- row 2: stepPills, every row of the brief's table ----

test("row 2: done is a green ✓ with the step and the agent", () => {
  assert.deepEqual([one({}).text, one({}).state, one({}).tone], ["✓ Build · Claude", "done", "ok"]);
});

test("row 2: running is blue, from a sent row or from steps.now", () => {
  const sent = one({ kind: "stage", role: "revise", stage: 4, status: "sent" }, { status: "sent", outcome: null, mode: "relay" });
  assert.deepEqual([sent.text, sent.state, sent.tone], ["Revise · Claude, running", "running", "info"]);
  const now = app.stepPills(task({ status: "queued", outcome: null, mode: "relay", preset: "redteam",
    steps: { chain: null, now: { kind: "stage", stage: 1, role: "build", agent: "claude" } } }), { calls: [] })[0];
  assert.deepEqual([now.text, now.state, now.tone], ["Build · Claude, running", "running", "info"]);
});

test("row 2: a check or a re-check that found problems is amber", () => {
  for (const [kind, name] of [["check", "Check"], ["recheck", "Re-check"]]) {
    const p = one({ kind, agent: "chatgpt", verdict: "FIX" });
    assert.deepEqual([p.text, p.state, p.tone], [`${name} · ChatGPT, found issues`, "found", "warn"]);
  }
});

test("row 2: a failed call is a red ✗, for any reason but the two stops", () => {
  for (const reason of [null, "late", "too_long", "limited", "credits", "internal_error"]) {
    const p = one({ status: "failed", reason_code: reason });
    assert.deepEqual([p.text, p.state, p.tone], ["✗ Build · Claude, failed", "failed", "bad"], reason);
  }
});

test("row 2: a plan limit and a process that ended are amber, stopped, with no ✗", () => {
  for (const reason of ["plan_limit", "process_ended"]) {
    const p = one({ status: "failed", reason_code: reason });
    assert.deepEqual([p.text, p.state, p.tone], ["Build · Claude, stopped", "stopped", "warn"], reason);
  }
});

test("row 2: skipped is grey", () => {
  const p = one({ kind: "stage", role: "attack2", stage: 3, agent: "cursor", reason_code: "skipped" }, { mode: "relay" });
  assert.deepEqual([p.text, p.state, p.tone], ["Attack · Cursor, skipped", "skipped", "muted"]);
});

test("row 2: a step not started is grey and names no agent", () => {
  const pills = app.stepPills(task({ mode: "relay", status: "queued", outcome: null,
    steps: { chain: [{ stage: 1, role: "build", agent: "claude" }, { stage: null, role: "check", agent: "chatgpt" }], now: null } }),
  { calls: [call({ kind: "stage", role: "build", stage: 1 })] });
  assert.deepEqual([pills[1].text, pills[1].state, pills[1].tone], ["Check · not started", "not_started", "muted"]);
});

test("row 2: blocked and unreadable checks are amber, in those words", () => {
  const blocked = one({ kind: "check", agent: "chatgpt", verdict: "BLOCKED" });
  assert.deepEqual([blocked.text, blocked.state, blocked.tone], ["Check · ChatGPT, blocked", "blocked", "warn"]);
  const bad = one({ kind: "check", verdict: "unreadable" });
  assert.deepEqual([bad.text, bad.state, bad.tone], ["Check · Claude, unreadable", "unreadable", "warn"]);
});

test("row 2: a timed-out call is amber", () => {
  const p = one({ agent: "grok", status: "timed_out" });
  assert.deepEqual([p.text, p.state, p.tone], ["Build · Grok Bot, timed out", "timed_out", "warn"]);
});

test("row 2: a card with no details read shows the record's agents in grey, ✓ only when the outcome says passed or fixed", () => {
  const passed = app.stepPills(task(), null);
  assert.deepEqual(passed.map((p) => [p.text, p.tone]), [["✓ Build · Claude", "muted"], ["✓ Check · ChatGPT", "muted"]]);
  const fixed = app.stepPills(task({ outcome: "fixed" }), null);
  assert.equal(fixed[0].text, "✓ Build · Claude");
  const waiting = app.stepPills(task({ outcome: null, status: "done", waiting_on: "land" }), null);
  assert.deepEqual(waiting.map((p) => [p.text, p.tone]), [["Build · Claude", "muted"], ["Check · ChatGPT", "muted"]]);
  const failed = app.stepPills(task({ outcome: "failed_check", status: "done" }), null);
  assert.equal(failed[0].text, "Build · Claude");
  const chain = app.stepPills(task({ mode: "relay", preset: "research-build", steps: { chain: [{ stage: 1, role: "research", agent: "grok" },
    { stage: 2, role: "build", agent: "claude" }, { stage: null, role: "check", agent: "chatgpt" }], now: null } }), null);
  assert.deepEqual(chain.map((p) => p.text), ["✓ Research · Grok Bot", "✓ Build · Claude", "✓ Check · ChatGPT"]);
  assert.ok(chain.every((p) => p.tone === "muted"));
});

test("row 2: with no details read, the step in progress still reads running, and what's after it not started", () => {
  const pills = app.stepPills(task({ status: "queued", outcome: null, mode: "relay", steps: { chain: [{ stage: 1, role: "build", agent: "claude" },
    { stage: 2, role: "attack", agent: "chatgpt" }, { stage: 3, role: "revise", agent: "claude" }], now: { kind: "stage", stage: 2, role: "attack", agent: "chatgpt" } } }), null);
  assert.deepEqual(pills.map((p) => [p.text, p.tone]), [["Build · Claude", "muted"], ["Attack · ChatGPT, running", "info"], ["Revise · not started", "muted"]]);
  const route = app.stepPills(task({ status: "queued", outcome: null, steps: { chain: null, now: { kind: "do", stage: null, role: null, agent: "claude" } } }), null);
  assert.deepEqual(route.map((p) => [p.text, p.tone]), [["Build · Claude, running", "info"], ["Check · not started", "muted"]]);
  const check = app.stepPills(task({ status: "queued", outcome: null, steps: { chain: null, now: { kind: "check", stage: null, role: null, agent: "chatgpt" } } }), null);
  assert.deepEqual(check.map((p) => [p.text, p.tone]), [["Build · Claude", "muted"], ["Check · ChatGPT, running", "info"]]);
});

// ---- row 2: the words ----

test("row 2: roleWords with a capital: attack2 reads Attack, execute reads Build, split_plan Plan, integrate Join", () => {
  const name = (role) => one({ kind: "stage", role, stage: 1 }, { mode: "relay" }).text;
  assert.equal(name("attack2"), "✓ Attack · Claude");
  assert.equal(name("execute"), "✓ Build · Claude");
  assert.equal(name("split_plan"), "✓ Plan · Claude");
  assert.equal(name("integrate"), "✓ Join · Claude");
});

test("row 2: a quick answer's do reads Answer; a re-ask keeps its words", () => {
  assert.equal(one({}, { skill: "quick_answer" }).text, "✓ Answer · Claude");
  assert.equal(one({ kind: "reask", role: "attack", stage: 2, agent: "chatgpt" }, { mode: "relay" }).text, "✓ Attack re-ask · ChatGPT");
  assert.equal(one({ kind: "reask", role: "attack2", stage: 3, agent: "cursor" }, { mode: "relay" }).text, "✓ Attack re-ask · Cursor");
});

// ---- row 2: no pills at all ----

test("row 2: no pills on Auto, on a floor row, or on a task with no calls that came back; Jev never gets one", () => {
  assert.deepEqual(app.stepPills(byN(71), showOf(71)), []);
  assert.deepEqual(app.stepPills(task({ mode: "auto", auto: { state: "running", steps: [] }, steps: null }), null), []);
  assert.deepEqual(app.stepPills(task({ agent: null, checker: null, outcome: null, status: "queued", waiting_on: "needs_label" }), { calls: [] }), []);
  assert.deepEqual(app.stepPills(task({ agent: null, checker: null, outcome: "returned", status: "returned" }), { calls: [] }), []);
  assert.deepEqual(app.stepPills(task({ outcome: "returned", status: "returned" }), null), []);
  for (const t of LOG.tasks) assert.ok(!app.stepPills(t, showOf(t.n)).some((p) => /Jev/.test(p.text)), `#${t.n}`);
});

test("row 2: not started drops on a No split and a One step, and stays on a cancelled or failed card", () => {
  const chain = [{ stage: 1, role: "build", agent: "claude" }, { stage: null, role: "check", agent: "chatgpt" }];
  const calls = [call({ kind: "stage", role: "build", stage: 1 })];
  const of = (over) => app.stepPills(task({ mode: "relay", steps: { chain, now: null }, ...over }), { calls }).map((p) => p.text);
  assert.deepEqual(of({ no_split: "one task", outcome: "stopped" }), ["✓ Build · Claude"]);
  assert.deepEqual(of({ one_step: { task: "x", team: "route" }, outcome: "stopped" }), ["✓ Build · Claude"]);
  assert.deepEqual(of({ outcome: "cancelled" }), ["✓ Build · Claude", "Check · not started"]);
  assert.deepEqual(of({ outcome: "stopped" }), ["✓ Build · Claude", "Check · not started"]);
});

test("row 2: an unchecked task names no check step", () => {
  assert.deepEqual(words(4), ["✓ Answer · Claude"]);
  assert.deepEqual(app.stepPills(task({ outcome: "unchecked", check_state: "unchecked", checker: "chatgpt" }), { calls: [call()] }).map((p) => p.text), ["✓ Build · Claude"]);
  assert.deepEqual(app.stepPills(task({ outcome: "unchecked", checker: "chatgpt" }), null).map((p) => p.text), ["Build · Claude"]);
});

test("row 2 [my call]: a sent row on a task that has ended isn't running: it reads stopped", () => {
  const p = one({ kind: "stage", role: "research", stage: 1, agent: "grok", status: "sent" }, { mode: "relay", status: "cancelled", outcome: "cancelled" });
  assert.deepEqual([p.text, p.state, p.tone], ["Research · Grok Bot, stopped", "stopped", "warn"]);
});

// ---- row 2: the demo's own cards ----

test("row 2: every demo card draws, each pill with words and a tone from the table", () => {
  const names = readdirSync(new URL("../../demo/tasks/", import.meta.url));
  assert.ok(names.length >= 75);
  assert.equal(LOG.tasks.length, 75);
  const seen = new Set();
  for (const t of LOG.tasks) {
    for (const show of [showOf(t.n), null]) {
      for (const p of app.stepPills(t, show)) {
        assert.ok(p.text && ["ok", "info", "warn", "bad", "muted"].includes(p.tone), `#${t.n} ${JSON.stringify(p)}`);
        seen.add(p.state);
      }
    }
  }
  for (const s of ["done", "running", "found", "failed", "stopped", "not_started", "blocked", "unreadable", "unknown"]) assert.ok(seen.has(s), s);
});

test("row 2: demo #64 is mid-build with no calls: Build running, then four not started", () => {
  assert.deepEqual(words(64), ["Build · Claude, running", "Attack · not started", "Attack · not started", "Revise · not started", "Check · not started"]);
  assert.deepEqual(tones(64), ["info", "muted", "muted", "muted", "muted"]);
});

test("row 2: a fix round adds its own pills (#2) and a double fail its amber ones (#3)", () => {
  assert.deepEqual(words(2), ["✓ Build · Claude", "Check · ChatGPT, found issues", "✓ Fix · Claude", "✓ Re-check · ChatGPT"]);
  assert.deepEqual(tones(2), ["ok", "warn", "ok", "ok"]);
  assert.deepEqual(words(3), ["✓ Build · Claude", "Check · ChatGPT, found issues", "✓ Fix · Claude", "Re-check · ChatGPT, found issues"]);
});

test("row 2: every team's demo card, as the live check's table reads", () => {
  assert.deepEqual(words(1), ["✓ Build · Claude", "✓ Check · ChatGPT"]);
  assert.deepEqual(words(10), ["✓ Research · Grok Bot", "✓ Build · Claude", "✓ Check · ChatGPT"]);
  assert.deepEqual(words(45), ["✓ Build · Claude", "✓ Build · ChatGPT", "✓ Review · ChatGPT", "✓ Review · Claude"]);
  assert.deepEqual(words(9), ["✓ Build · Claude", "✓ Attack · ChatGPT", "✓ Attack · Cursor", "✓ Revise · Claude", "✓ Check · ChatGPT"]);
  assert.deepEqual(words(8), ["✓ Vote · Claude", "✓ Vote · ChatGPT", "✓ Vote · Grok Bot"]);
  assert.deepEqual(words(38), ["✓ Plan · Claude", "✓ Join · Claude", "✓ Check · ChatGPT"]);
  assert.deepEqual(words(70), ["✓ Plan · Claude", "✓ Attack · ChatGPT", "✓ Attack · Cursor", "✓ Revise · Claude", "✓ Check · ChatGPT"]);
});

test("row 2: the two stops in the demo, and #27's late call reads red on a passed card, by the owner's choice", () => {
  assert.deepEqual(words(26), ["Build · Claude, stopped", "✓ Build · ChatGPT"]);
  assert.deepEqual(tones(26), ["warn", "ok"]);
  assert.deepEqual(words(12), ["Build · Claude, stopped", "Check · not started"]);
  assert.deepEqual(words(27), ["✗ Build · Grok Bot, failed", "✓ Build · ChatGPT", "✓ Check · Claude"]);
});

test("row 2: stagesView itself didn't change: a process-ended call is still bad there", () => {
  const stages = app.stagesView(byN(12), showOf(12));
  assert.equal(stages.find((s) => s.key !== "jev").state, "bad");
});

// ---- row 3: the card's row ----

async function cardOf(t, show = null) {
  const page = await loadPage();
  Object.assign(page.state, { status: STATUS, project: t.project || null, chat: t.chat || null, tasks: [t] });
  if (show) page.state.shows.set(t.task_id, show);
  page.renderStream();
  return { page, card: page.el(`card-${t.task_id}`) };
}

test("row 3: cardLine is the pills, then only the outcome, the time apart; files as Details reads them", () => {
  const line = app.cardLine(byN(1), showOf(1));
  assert.deepEqual(Object.keys(line).sort(), ["files", "pills", "text", "time", "tone"]);
  assert.deepEqual(line.pills.map((p) => p.text), ["✓ Build · Claude", "✓ Check · ChatGPT"]);
  assert.equal(line.text, "passed");
  assert.equal(line.time, null);
  assert.equal(line.tone, "ok");
  assert.ok(line.files.every((f) => f.file));
  assert.equal(app.cardLine({ ...byN(1), notes: [{ n: 1, text: "x" }] }, showOf(1)).text, "passed · 1 note");
  assert.equal(app.cardLine(byN(2), showOf(2)).text, "fixed in round 2");
  assert.equal(app.cardLine(byN(75), showOf(75)).text, "waiting on Grok · 6 min");
});

test("row 3: a running card has no words of its own, just its pills and the time", () => {
  const t = byN(64);
  const line = app.cardLine(t, showOf(64), { time: true, now: new Date(Date.parse(t.created_at) + 80000).toISOString() });
  assert.equal(line.text, "");
  assert.equal(line.time, "1m 20s");
  assert.equal(line.pills[0].text, "Build · Claude, running");
});

test("row 3: Auto keeps its words whole, with no pills", () => {
  const run = { task_id: "sr-r", n: 61, mode: "auto", status: "queued", outcome: null, auto: { state: "running", words: "Auto · step 3 of 4 · 4 of 29 calls", steps: [] } };
  assert.equal(app.cardLine(run, null).text, "Auto · step 3 of 4 · 4 of 29 calls");
  assert.deepEqual(app.cardLine(run, null).pills, []);
  assert.equal(app.cardLine({ ...run, auto: { state: "stopped", words: "Auto stopped: the budget is reached", steps: [] } }, null).text, "Auto stopped: the budget is reached");
});

test("row 3: the row holds the pills, the outcome, Details and ⋯, with no dot, no #n and no team; those stay under the bubble", async () => {
  const { card } = await cardOf(byN(1), showOf(1));
  const top = card.querySelector(".card-top");
  assert.deepEqual(top.querySelectorAll(".stage").map((p) => p.textContent), ["✓ Build · Claude", "✓ Check · ChatGPT"]);
  assert.ok(top.querySelectorAll(".stage").every((p) => p.classList.contains("ok")));
  assert.equal(top.querySelector(".light"), null);
  assert.equal(top.querySelector(".verdict-text").textContent, "passed");
  assert.ok(top.querySelector(".details-btn"));
  assert.doesNotMatch(top.textContent, /#1\b|Route/);
  assert.match(card.querySelector(".bubble-meta").textContent, /#1 · Route/);
  assert.equal(card.firstElementChild.nextElementSibling, top);  // its place at the card's top, right under the bubble
});

test("row 3: pills aren't buttons; the outcome sits with the time, Details and ⋯ in one part, for the phone's last line", async () => {
  const { card } = await cardOf(byN(9), showOf(9));
  const top = card.querySelector(".card-top");
  assert.ok(top.querySelectorAll(".stage").every((p) => p.tag === "span"));
  const end = top.querySelector(".card-end");
  assert.ok(end.querySelector(".verdict-text") && end.querySelector(".details-btn"));
  assert.equal(end.querySelector(".stage"), null);
});

test("row 3: the time shows on the newest and running cards only", async () => {
  const plain = { chat: null, project: null, parent: null, piece_of: null };
  const running = { ...byN(64), task_id: "sr-run", n: 800, ...plain };
  const middle = { ...byN(1), task_id: "sr-mid", n: 801, ...plain };
  const newest = { ...byN(1), task_id: "sr-new", n: 802, ...plain };
  const page = await loadPage();
  Object.assign(page.state, { status: STATUS, tasks: [newest, middle, running], chat: null, project: null });
  page.renderStream();
  const time = (id) => page.el(`card-${id}`).querySelector(".card-time");
  assert.equal(page.state.newestCard, "sr-new");
  assert.ok(time("sr-new") && time("sr-run"));
  assert.equal(time("sr-mid"), null);
});

test("row 3: the CSS draws the pills in tokens, and the outcome shows its colour", () => {
  assert.doesNotMatch(CSS_TEXT, /\.card-top \.verdict-text \{ color: var\(--text-3\)/);
  assert.match(CSS_TEXT, /\.stage \{[^}]*border-radius: 999px/);
  for (const [cls, token] of [["ok", "ok-text"], ["info", "info-text"], ["warn", "warn-text"], ["bad", "bad-text"], ["muted", "muted"]]) {
    assert.match(CSS_TEXT, new RegExp(`\\.stage\\.${cls} \\{ color: var\\(--${token}\\)`), cls);
  }
  assert.match(CSS_TEXT, /\.card-end \{ flex: 1 1 100%/);
});

// ---- row 4: notes 14 and 8 ----

test("row 4 (note 14): a card ready to land reads muted grey, not red; its pills and bright Land still say whose turn it is", async () => {
  for (const n of [33, 38]) {
    const line = app.cardLine(byN(n), showOf(n));
    assert.equal(line.tone, "muted", `#${n}`);
    assert.equal(line.text, "ready to land");
  }
  const { card } = await cardOf(byN(33), showOf(33));
  assert.ok(card.querySelector(".card-top").classList.contains("muted"));
  assert.ok(card.querySelector(`#act-${byN(33).task_id}-land`).classList.contains("btn-primary"));
});

test("row 4 (note 14): no card waiting on anything reads bad, but a Grok call overdue, which the rules say reads red", () => {
  for (const t of LOG.tasks.filter((x) => x.waiting_on)) {
    const line = app.cardLine(t, showOf(t.n));
    if (t.n === 74) assert.equal(line.tone, "bad");
    else assert.notEqual(line.tone, "bad", `#${t.n} ${t.waiting_on}`);
  }
  assert.equal(app.verdictLine({ ...byN(59) }).tone, "muted");  // a failed plan's frame and pills say what failed
});

test("row 4 (note 8): an undone or discarded card's outcome says so, in grey, and doesn't say passed", () => {
  for (const state of ["undone", "discarded"]) {
    const t = { ...byN(1), project: "x", waiting_on: null, outcome: "passed", project_files: { mode: "on", state } };
    const line = app.cardLine(t, showOf(1));
    assert.equal(line.text, state);
    assert.equal(line.tone, "muted");
    assert.doesNotMatch(line.text, /passed/);
    assert.deepEqual(line.pills.map((p) => p.text), ["✓ Build · Claude", "✓ Check · ChatGPT"]);  // the steps did pass; the change is what went
    assert.equal(app.verdictLine(t).text, state === "undone" ? "Undone" : "Discarded");
  }
  const landed = { ...byN(1), outcome: "passed", project_files: { mode: "on", state: "landed", commit: "a".repeat(40) } };
  assert.equal(app.cardLine(landed, showOf(1)).text, "passed");
  const run = { ...byN(71), auto: { ...byN(71).auto, state: "undone", words: "Auto undone" }, project_files: { mode: "on", state: "undone" } };
  assert.equal(app.cardLine(run, null).text, "Auto undone");
});

// ---- row 5: note 5 ----

test("row 5 (note 5): a plan waiting on its answers, with a kept copy, says so; no can't land, no stopped; Discard stays", () => {
  const plan = { task_id: "sr-q", n: 501, mode: "plan", status: "returned", waiting_on: "answers", outcome: null, check_state: "pending", land_anyway: false,
    project: "x", project_files: { mode: "on", state: "none", copy: true, changed: [], base: "c".repeat(40), branch: "main", tests: null } };
  const view = app.fileView(plan);
  assert.equal(view.line, "Files: waiting for your answers");
  assert.equal(view.kind, "answers");
  assert.equal(view.tone, "muted");
  assert.equal(view.note, undefined);
  assert.doesNotMatch(JSON.stringify(view), /can't land|stopped/);
  assert.deepEqual(view.buttons.map((b) => b.key), ["discard"]);
  assert.equal(app.fileView({ ...plan, project_files: { ...plan.project_files, copy: false } }).buttons.length, 0);
});

// ---- row 6: the top bar (note 26) ----

const UP = { ...STATUS, agents: STATUS.agents.map((a) => ({ ...a, available: true, why: null, why_code: null, online: true, configured: true })),
  jev: { ...STATUS.jev, configured: true, available: true, why: null, tokens_month: 32000, cap: 1000000, over_cap: false },
  memory: { ...STATUS.memory, online: true, starting: false, documents: 16 } };
const WRONG = { ...UP, agents: UP.agents.map((a) => (a.name === "chatgpt" ? { ...a, available: false, why: "ChatGPT is signed out (codex login)", why_code: "signed_out" }
  : a.name === "grok" ? { ...a, available: false, configured: false, why: "Grok Bot isn't set up", why_code: "not_configured" }
    : a.name === "claude" ? { ...a, online: false, why: "its check didn't answer" } : a)), memory: { ...UP.memory, online: false, starting: true } };

async function barOf(status = UP, { width = 1280, tasks = [] } = {}) {
  const page = await loadPage();
  page.resize(width);
  Object.assign(page.state, { status, tasks, project: null, chat: "garden", team: "route" });
  page.wire();
  page.render();
  return page;
}
const boxes = (page) => page.el("strip").querySelectorAll(".agent-box");

test("row 6: one real button per item, from status, in the list's order; two agents give 4", async () => {
  const page = await barOf();
  assert.deepEqual(boxes(page).map((b) => b.id), ["claude", "chatgpt", "grok", "cursor", "jev", "memory"].map((k) => `agent-box-${k}`));
  assert.ok(boxes(page).every((b) => b.tag === "button" && b.getAttribute("type") === "button" && b.getAttribute("aria-haspopup") === "dialog"));
  assert.ok(boxes(page).every((b) => b.parent.classList.contains("strip-row")));
  const two = await barOf({ ...UP, agents: UP.agents.slice(0, 2) });
  assert.equal(boxes(two).length, 4);
});

test("row 6: each box is a round light and its name, with no other words but Jev's count", async () => {
  const page = await barOf();
  assert.deepEqual(boxes(page).map((b) => b.textContent), ["Claude", "ChatGPT", "Grok Bot", "Cursor", "Jev32k of 1M", "Memory"]);
  assert.ok(boxes(page).every((b) => b.querySelector(".light")));
  assert.equal(page.el("agent-box-jev").querySelector(".agent-state").textContent, "32k of 1M");
  assert.ok(boxes(page).filter((b) => b.id !== "agent-box-jev").every((b) => !b.querySelector(".agent-state")));
  assert.doesNotMatch(page.el("strip").textContent, /[●▲○]|of 4 up/);
});

test("row 6: Jev not set up is a grey light with no count; over its cap reads red and keeps its count", async () => {
  const off = await barOf({ ...UP, jev: { ...UP.jev, configured: false } });
  const jev = off.el("agent-box-jev");
  assert.equal(jev.textContent, "Jev");
  assert.ok(jev.classList.contains("tone-muted"));
  assert.match(jev.getAttribute("title"), /not set up/);
  const over = await barOf({ ...UP, jev: { ...UP.jev, over_cap: true } });
  assert.ok(over.el("agent-box-jev").classList.contains("tone-bad"));
  assert.equal(over.el("agent-box-jev").querySelector(".agent-state").textContent, "32k of 1M");
  const none = await barOf({ ...UP, jev: null });
  assert.equal(none.el("agent-box-jev").textContent, "Jev");
});

test("row 6: each tone's class: ok, bad, muted, warn and info, from section 3's bar", async () => {
  const page = await barOf(WRONG);
  const tone = (key) => page.el(`agent-box-${key}`).className.match(/tone-(\w+)/)[1];
  assert.deepEqual(["claude", "chatgpt", "grok", "cursor", "jev", "memory"].map(tone), ["warn", "bad", "muted", "ok", "ok", "info"]);
  for (const [cls, line] of [["bad", "bad-line"], ["info", "info-line"], ["warn", "warn-line"]]) {
    assert.match(CSS_TEXT, new RegExp(`\\.agent-box\\.tone-${cls} \\{ box-shadow: inset 0 0 0 1px var\\(--${line}\\)`), cls);
  }
  assert.doesNotMatch(CSS_TEXT, /\.agent-box\.tone-muted \{ box-shadow/);
});

test("row 6: the title and aria-label hold that agent's words and details", async () => {
  const page = await barOf(WRONG);
  for (const b of boxes(page)) assert.equal(b.getAttribute("title"), b.getAttribute("aria-label"));
  assert.match(page.el("agent-box-chatgpt").getAttribute("title"), /^ChatGPT · signed out · ChatGPT is signed out/);
  assert.match(page.el("agent-box-jev").getAttribute("title"), /^Jev · 32k of 1M · tokens this month/);
  assert.match(page.el("agent-box-memory").getAttribute("title"), /^Memory · starting/);
  assert.match(page.el("agent-box-claude").getAttribute("aria-label"), /^Claude · check didn't answer · its check didn't answer/);
});

test("row 6: the full list opens from each box, its head chipWords' text, with every row and its link", async () => {
  for (const key of ["claude", "chatgpt", "grok", "cursor", "jev", "memory"]) {
    const page = await barOf(WRONG);
    page.el(`agent-box-${key}`).click();
    const pop = page.el("strip").querySelector(".status-pop");
    assert.ok(pop, key);
    assert.equal(page.state.stripOpen, key);
    assert.equal(page.el(`agent-box-${key}`).getAttribute("aria-expanded"), "true");
    assert.equal(pop.querySelector(".status-head").textContent, app.chipWords(WRONG, []).text);
    assert.equal(pop.querySelectorAll(".status-row").length, 6);
    assert.ok(pop.querySelector(".linklike"));
  }
});

test("row 6 [my call]: a click on any box while the list is open closes it", async () => {
  const page = await barOf();
  page.el("agent-box-claude").click();
  page.el("agent-box-jev").click();
  assert.ok(!page.el("strip").querySelector(".status-pop"));
});

test("row 6: Esc closes the list and the focus goes back to the box that was clicked", async () => {
  const page = await barOf();
  page.el("agent-box-cursor").click();
  page.key("Escape", page.doc.body);
  assert.ok(!page.el("strip").querySelector(".status-pop"));
  assert.equal(page.doc.activeElement.id, "agent-box-cursor");
});

test("row 6: a tap outside closes the list; a tap on a box's own list doesn't", async () => {
  const page = await barOf();
  page.el("agent-box-claude").click();
  page.el("strip").querySelector(".status-pop").click();
  assert.ok(page.el("strip").querySelector(".status-pop"));
  page.el("stream").click();
  assert.ok(!page.el("strip").querySelector(".status-pop"));
});

test("row 6: status not read yet, or unreadable: one grey box with today's words", async () => {
  const page = await barOf(null);
  assert.deepEqual(boxes(page).map((b) => [b.textContent, b.classList.contains("tone-muted")]), [["loading…", true]]);
  page.state.statusError = "no";
  page.renderStrip();
  assert.equal(boxes(page)[0].textContent, "the router's status is unreadable");
});

test("row 6: Menu and Needs you stay in the head; the wide bar keeps Needs you beside the boxes when the sidebar is hidden", async () => {
  const narrow = await barOf(UP, { width: 390, tasks: LOG.tasks });
  const bar = narrow.el("strip").querySelector(".narrow-bar");
  assert.ok(bar.querySelector('[aria-label="Menu"]') && bar.querySelector(".needs-head"));
  assert.equal(boxes(narrow).length, 6);
  const wide = await barOf(UP, { tasks: LOG.tasks });
  wide.state.sideHidden = true;
  wide.renderStrip();
  assert.ok(wide.el("strip").querySelector(".needs-head"));
});

test("row 6: nothing of the old button is left in the code or the CSS", () => {
  for (const word of ["status-chip", "lightEl", "lightView", "lightsCount", "light-item", "light-mark", "light-name", "light-short", "light-word", "lights-count", "chip-wrap", "chip-words", "chip-mark"]) {
    assert.ok(!SOURCE.includes(word), `app.js: ${word}`);
    assert.ok(!CSS_TEXT.includes(word), `app.css: ${word}`);
  }
});

test("row 6: nothing shrinks; at 900 px and under Menu and Needs you take their own line and the boxes are 32 px on a phone", () => {
  assert.match(CSS_TEXT, /\.agent-box \{[^}]*flex: 1 1 0;[^}]*min-width: max-content/);
  assert.match(CSS_TEXT, /@media \(max-width: 900px\) \{[^}]*\.narrow-bar \{ flex: 1 1 100%/);
  assert.match(CSS_TEXT, /@media \(max-width: 600px\) \{[^}]*\.agent-box \{[^}]*min-height: 32px/);
  assert.match(CSS_TEXT, /\.strip-row \{[^}]*position: relative/);
});

// ---- row 7 (note 1): an open menu doesn't fade in again ----

async function streamOf(tasks, { project = null, chat = null, status = UP, shows = {}, ...options } = {}) {
  const page = await loadPage(options);
  Object.assign(page.state, { status, project, chat, tasks, team: "route" });
  for (const [id, show] of Object.entries(shows)) page.state.shows.set(id, show);
  page.wire();
  page.render();
  return page;
}

test("row 7: the ⋯ menu fades in on opening and stays settled across a redraw", async () => {
  const t = { ...byN(1), chat: null, project: null };
  const page = await streamOf([t]);
  page.el(`card-${t.task_id}`).querySelector(".more-btn").click();
  const list = () => page.el(`card-${t.task_id}`).querySelector(".menu-list");
  assert.ok(list() && !list().classList.contains("settled"));
  page.renderStream({ follow: false });
  assert.ok(list().classList.contains("settled"));
  page.renderStream({ follow: false });
  assert.ok(list().classList.contains("settled"));
  page.el(`card-${t.task_id}`).querySelector(".more-btn").click();
  assert.ok(!list());
  page.el(`card-${t.task_id}`).querySelector(".more-btn").click();
  assert.ok(!list().classList.contains("settled"), "a second opening fades in again");
});

test("row 7: the same for Project and a failed card's Run again as…", async () => {
  const project = STATUS.projects[0].name;
  const page = await streamOf([], { project });
  const button = () => page.el("stream").querySelector(".project-menu button");
  const list = () => page.el("stream").querySelector(".project-menu .menu-list");
  button().click();
  assert.ok(list() && !list().classList.contains("settled"));
  page.renderStream({ follow: false });
  assert.ok(list().classList.contains("settled"));
  const failed = { ...byN(3), chat: null, project: null };
  const card = await streamOf([failed], { shows: { [failed.task_id]: showOf(3) } });
  const again = () => card.el(`card-${failed.task_id}`).querySelector(".row-actions .menu");
  again().querySelector("button").click();
  assert.ok(again().querySelector(".menu-list") && !again().querySelector(".menu-list").classList.contains("settled"));
  card.renderStream({ follow: false });
  assert.ok(again().querySelector(".menu-list").classList.contains("settled"));
});

test("row 7: a settled menu has no transition, so @starting-style has nothing to replay", () => {
  assert.match(CSS_TEXT, /\.menu-list\.settled \{ transition: none; \}/);
});

// ---- row 8 (note 9): a burst of card loads redraws once ----

function countDraws(page) {
  const stream = page.el("stream");
  const real = stream.replaceChildren.bind(stream);
  let draws = 0;
  stream.replaceChildren = (...nodes) => { draws += 1; real(...nodes); };
  return () => draws;
}

const tenCards = () => Array.from({ length: 10 }, (_, i) => ({ ...byN(1), task_id: `sr-b${i}`, n: 600 + i, chat: null, project: null }));

test("row 8: ten loads at once give one redraw, at the end", async () => {
  const tasks = tenCards();
  const page = await streamOf(tasks, { answers: { "/api/task/": { calls: [] }, "/api/files/": { files: [] } } });
  const draws = countDraws(page);
  await Promise.all(tasks.map((t) => page.loadShow(t.task_id)));
  assert.equal(draws(), 1);
  assert.equal(page.state.loading.size, 0);
  assert.ok(page.state.shows.has("sr-b9"));
});

test("row 8: a load that fails still redraws at the end", async () => {
  const tasks = tenCards().slice(0, 2);
  const page = await streamOf(tasks, { answers: { get "/api/task/"() { throw new Error("offline"); }, "/api/files/": { files: [] } } });
  const draws = countDraws(page);
  await Promise.all(tasks.map((t) => page.loadShow(t.task_id)));
  assert.equal(draws(), 1);
  assert.ok(!page.state.shows.has("sr-b0"));
  assert.equal(page.state.loading.size, 0);
});

test("row 8: a long burst still redraws, at most once a second", async () => {
  const tasks = tenCards();
  const page = await streamOf(tasks, { answers: { "/api/task/": { calls: [] }, "/api/files/": { files: [] } } });
  const draws = countDraws(page);
  const realNow = Date.now;
  let clock = realNow();
  Date.now = () => clock;
  try {
    const held = page.loadShow("sr-b9");  // one that's still out across the whole burst
    for (let i = 0; i < 6; i += 1) {
      clock += 400;
      const load = page.loadShow(`sr-b${i}`);
      page.state.loading.add("held");  // the burst hasn't ended
      await load;
    }
    assert.ok(draws() >= 1 && draws() <= 3, `${draws()} draws over 2.4 s`);
    page.state.loading.delete("held");
    await held;
    clock += 1;
    await page.loadShow("sr-b8");
    assert.ok(draws() >= 2);
  } finally { Date.now = realNow; }
});

test("row 8: a quiet load draws nothing of its own, but ends a burst it held open", async () => {
  const tasks = tenCards().slice(0, 2);
  const page = await streamOf(tasks, { answers: { "/api/task/": { calls: [] }, "/api/files/": { files: [] } } });
  const draws = countDraws(page);
  await page.loadShow("sr-b0", { quiet: true });
  assert.equal(draws(), 0);
  await Promise.all([page.loadShow("sr-b1"), page.loadShow("sr-b0", { quiet: true })]);
  assert.equal(draws(), 1);
});

// ---- row 9 (notes 16 and 21): menus close properly ----

const PROJECT_ITEMS = [["project-secrets", "secrets"], ["project-ideas", "ideas"], ["project-notes", "notes"], ["tests-set", "tests"]];

async function projectPage(name = STATUS.projects[0].name) {
  const page = await streamOf([], { project: name, answers: { "/api/": { tasks: [], ideas: [], notes: "", hash: "h", secrets: [], used: [], dismissed: 0, suggest: {} } } });
  return page;
}
const projectButton = (page) => page.el("stream").querySelector(".project-menu button");
const projectList = (page) => page.el("stream").querySelector(".project-menu .menu-list");

test("row 9 (note 16): each Project item closes the menu behind its sheet, and the next press of Project opens it", async () => {
  for (const [id] of PROJECT_ITEMS) {
    const page = await projectPage();
    projectButton(page).click();
    assert.ok(projectList(page), id);
    page.el(id).click();
    assert.ok(!projectList(page), `${id}: the menu is gone`);
    assert.equal(page.state.menu, null);
    page.el("sheet").hidden = true;  // the sheet closes
    projectButton(page).click();
    assert.ok(projectList(page), `${id}: the first press opens it`);
  }
});

test("row 9 (note 16): HANDOFF.md and the run command's item do the same", async () => {
  for (const pick of [(page) => page.find("HANDOFF.md", page.el("stream")), (page) => projectList(page).querySelectorAll(".side-item").find((b) => /run/i.test(b.textContent))]) {
    const page = await projectPage();
    projectButton(page).click();
    pick(page).click();
    assert.ok(!projectList(page));
    page.el("sheet").hidden = true;
    projectButton(page).click();
    assert.ok(projectList(page));
  }
});

test("row 9 (note 16): Add files… clicks the new input, after the redraw", async () => {
  const name = STATUS.projects.find((p) => p.git).name;
  const page = await streamOf([], { project: name });
  projectButton(page).click();
  const old = page.el("project-file-input");
  const add = page.find("Add files…", page.el("stream"));
  const realGet = page.doc.getElementById;
  let clicked = null;
  page.doc.getElementById = (id) => {
    const node = realGet(id);
    if (id === "project-file-input" && node) node.click = () => { clicked = node; };
    return node;
  };
  add.click();
  assert.ok(!projectList(page));
  assert.ok(clicked && clicked !== old && clicked.isConnected, "the input clicked is the one on the page");
});

test("row 9 (note 21): a tap outside closes a failed card's own Run again as…; a tap inside doesn't", async () => {
  const failed = { ...byN(3), chat: null, project: null };
  const page = await streamOf([failed], { shows: { [failed.task_id]: showOf(3) } });
  const again = () => page.el(`card-${failed.task_id}`).querySelector(".row-actions .menu");
  again().querySelector("button").click();
  assert.ok(again().querySelector(".menu-list"));
  again().querySelector(".menu-list").fire("click");
  assert.ok(again().querySelector(".menu-list"), "a tap inside leaves it");
  page.el("banners").click();
  assert.ok(!again().querySelector(".menu-list"), "a tap outside closes it");
  assert.equal(page.state.menu, null);
});

// ---- row 10 (note 22): Plan in Run again as… ----

const PLAN_UP = { ...UP, plan: { ...UP.plan, ready: true, why: null }, presets: UP.presets.map((p) => ({ ...p, ready: true, why: null })), split: { ...UP.split, ready: true, why: null } };

async function againMenu(t, show) {
  const page = await streamOf([t], { status: PLAN_UP, project: t.project || null, chat: t.chat || null, shows: { [t.task_id]: show } });
  page.el(`card-${t.task_id}`).querySelector(".more-btn").click();
  page.find("Run again as…", page.el(`card-${t.task_id}`)).click();
  return page;
}
const planItem = (page, t) => page.el(`card-${t.task_id}`).querySelectorAll('[role="menuitem"]').find((b) => /^Plan/.test(b.textContent));

test("row 10: on a project card Plan is on, and pressing it posts team plan with the project", async () => {
  const t = byN(33);
  const page = await againMenu(t, showOf(33));
  const item = planItem(page, t);
  assert.equal(item.disabled, false);
  item.click();
  await page.settle();
  const sent = page.posts.filter((p) => p.path === "/api/run").map((p) => p.body);
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0], app.runAgainRequest(t, "plan", { quick: false, chat: null, newChat: null }, PLAN_UP).request);
  assert.equal(sent[0].team, "plan");
  assert.equal(sent[0].project, t.project);
});

test("row 10: off a project Plan stays greyed, with its reason", async () => {
  const t = { ...byN(1), project: null, chat: "garden" };
  const page = await againMenu(t, showOf(1));
  const item = planItem(page, t);
  assert.equal(item.disabled, true);
  assert.equal(item.getAttribute("title"), app.PLAN_OFF_PROJECT);
});

// ---- row 11 (notes 2, 3 and 4): the composer on a phone ----

function mediaBlocks(head) {
  // everything inside each `@media <head> { … }`, by counting braces
  let out = "", at = CSS_TEXT.indexOf(head);
  while (at !== -1) {
    let i = CSS_TEXT.indexOf("{", at) + 1, depth = 1;
    const start = i;
    while (depth) { if (CSS_TEXT[i] === "{") depth += 1; if (CSS_TEXT[i] === "}") depth -= 1; i += 1; }
    out += CSS_TEXT.slice(start, i - 1);
    at = CSS_TEXT.indexOf(head, i);
  }
  return out;
}
const PHONE_CSS = mediaBlocks("@media (max-width: 600px)");

test("row 11 (note 2): at 600 px and under the slots are a two-column grid, and stay hidden when hidden", () => {
  assert.match(PHONE_CSS, /#slots \.team-slots \{ display: grid; grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/);
  assert.match(CSS_TEXT, /\[hidden\] \{ display: none !important; \}/);
});

async function promptPage() {
  const page = await streamOf([], { chat: "garden" });
  const prompt = page.el("prompt");
  const heights = [];
  Object.defineProperty(prompt, "scrollHeight", { get: () => Math.ceil(prompt.value.length / 40) * 20 });
  Object.defineProperty(prompt.style, "height", { get: () => heights[heights.length - 1], set: (v) => heights.push(v) });
  return { page, prompt, heights };
}

test("row 11 (note 3): an empty box is as tall as its placeholder; the box stays empty", async () => {
  const { page, prompt } = await promptPage();
  page.setTeam("redteam");
  assert.equal(prompt.value, "");
  assert.equal(prompt.style.height, `${Math.ceil(prompt.placeholder.length / 40) * 20}px`);
  assert.ok(prompt.placeholder.length > 40);
});

test("row 11 (note 3): typed words are what's measured once there are any", async () => {
  const { page, prompt } = await promptPage();
  page.setTeam("redteam");
  prompt.value = "short";
  prompt.fire("input");
  assert.equal(prompt.style.height, "20px");
  assert.equal(prompt.value, "short");
});

test("row 11 (note 3): it runs again when the team changes and when the width does", async () => {
  const { page, prompt, heights } = await promptPage();
  const before = heights.length;
  page.setTeam("redteam");
  assert.ok(heights.length > before, "the team changed");
  const after = heights.length;
  page.resize(390);
  page.windowEvent("resize");
  assert.ok(heights.length > after, "the width changed");
  assert.equal(prompt.value, "");
});

test("row 11 (note 4): at 600 px and under the tag has its own line above the bar", () => {
  assert.match(PHONE_CSS, /#context-tag \{ order: -1; flex: 1 1 100%; max-width: none/);
  assert.match(CSS_TEXT, /\.composer-bar \{[^}]*flex-wrap: wrap/);
});

// ---- row 12 (note 10): Details and ⋯ on a phone ----

test("row 12: at 600 px and under Details and ⋯ each have a 44 px tap area", () => {
  assert.match(PHONE_CSS, /\.card-top \.details-btn, \.card-top \.card-menu \.details-btn \{ min-width: 44px; min-height: 44px/);
});

test("row 12, the live check: the 44 px rule comes after the rule that gives ⋯ 32 px, so it wins at phone width", () => {
  const small = CSS_TEXT.indexOf(".card-top .card-menu .details-btn { margin-left: 0; min-width: 32px");
  const big = CSS_TEXT.indexOf(".card-top .details-btn, .card-top .card-menu .details-btn { min-width: 44px");
  assert.ok(small > 0 && big > small, `${small} ${big}`);
});

test("row 12: Land stays where it is, above the result", async () => {
  const t = byN(33);
  const page = await streamOf([t], { project: t.project, shows: { [t.task_id]: showOf(33) } });
  const card = page.el(`card-${t.task_id}`);
  const kids = card.children;
  const files = kids.findIndex((n) => n.classList.contains("files-block"));
  const result = kids.findIndex((n) => n.classList.contains("result") || n.querySelector(".result"));
  assert.ok(files > 0 && (result === -1 || files < result));
  assert.ok(card.querySelector(`#act-${t.task_id}-land`));
});
