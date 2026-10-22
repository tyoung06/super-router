// Build brief 23, D: the Needs-you buttons and the When-a-task-stops offers as the rules' Interface section lists them,
// each shown only when the JSON offers it (the rescue offers from the row's `fallback` and `resume`); the confirms on a
// pick, a skip, a cancel, a split's run and `none` only; the versus, vote and redteam boards; the memory drawer; the
// sidebar's Needs you list. Fixtures: the demo's documents.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import {
  demoCommand, floorView, grokWait, handoffWords, jevWords, memoryCallLines, memoryDrawer, needsConfirm, needsYou, needsYouList,
  piecesView, redteamBoard, refusalAlternatives, rescueOffers, splitApprove, splitPlanView, versusBoard, voteBoard,
} from "../../static/app.js";

const demo = (name) => JSON.parse(readFileSync(new URL(`../../demo/${name}`, import.meta.url), "utf8"));
const STATUS = demo("status.json");
const TASKS = demo("log.json").tasks;
const SHOWS = Object.fromEntries(readdirSync(new URL("../../demo/tasks/", import.meta.url)).map((f) => [f.replace(/\.json$/, ""), demo(`tasks/${f}`)]));
const find = (pred) => { const task = TASKS.find(pred); assert.ok(task, "no such demo task"); return [task, SHOWS[task.task_id]]; };

// ---------- the confirms ----------

test("only a pick, a skip, a cancel, a split's run or reject, and none ask first", () => {
  for (const choice of ["a", "b", "c", "none"]) assert.equal(needsConfirm({ action: "pick", task_id: "x", choice }), true);
  assert.equal(needsConfirm({ action: "split_skip", task_id: "x" }), true);
  assert.equal(needsConfirm({ action: "cancel", task_id: "x" }), true);
  assert.equal(needsConfirm({ action: "split_go", task_id: "x", choice: "y" }), true);
  assert.equal(needsConfirm({ action: "split_go", task_id: "x", choice: "n" }), true);  // The owner, 21 Oct: Reject can't be undone
  for (const request of [{ action: "floor" }, { action: "resume" }, { action: "fallback" },
    { action: "check" }, { action: "send" }, null]) assert.equal(needsConfirm(request), false, JSON.stringify(request));
});

// ---------- needs you ----------

test("the Jev floor: the skills as chips, Jev's guess first; one click is the floor answer and nothing else", () => {
  const [task] = find((t) => t.waiting_on === "needs_label" && t.jev.status === "below_floor");
  const view = floorView(task, STATUS);
  assert.equal(view.sub, "Jev said writing at 0.50 · the floor is 0.80");
  assert.deepEqual(view.skills.map((s) => s.key).sort(), STATUS.skills.map((s) => s.key).sort());
  assert.deepEqual([view.skills[0].key, view.skills[0].guess], ["writing", true]);
  assert.deepEqual(view.skills[1].request, { action: "floor", skill: view.skills[1].key, answers: task.task_id, text: task.text });
  assert.deepEqual(view.cancel, { action: "cancel", task_id: task.task_id });
  assert.equal(floorView(find((t) => t.outcome === "passed")[0], STATUS), null);
});

test("Jev's answer in Terminal's words for every way it can miss", () => {
  assert.equal(jevWords({ status: "over_cap" }), "Jev wasn't asked: this month's tokens are used up");
  assert.equal(jevWords({ status: "error", error: "timeout" }), "Jev couldn't label it (error: timeout)");
  assert.equal(jevWords({ status: "none_of_these" }), "Jev found no skill that fits");
  assert.equal(jevWords({ status: "below_floor", label: "code", confidence: 0.61 }, null), "Jev said code at 0.61");
});

test("a split plan: each piece's skill, doer and checker, a piece under the floor asks for its skill; Approve carries it", () => {
  const [task, show] = find((t) => t.waiting_on === "split_plan");
  const view = splitPlanView(task, show);
  assert.deepEqual(view.pieces.map((p) => [p.piece, p.needsLabel, p.words]), [
    [1, false, "writing · Claude, ChatGPT checks"],
    [2, true, "Jev left it under the floor (planning at 0.52): pick its skill"]]);
  assert.deepEqual([view.join, view.joiner, view.checker], ["Put the email first, then the FAQ.", "Claude", "ChatGPT"]);
  assert.deepEqual(view.reject, { action: "split_go", task_id: task.task_id, choice: "n" });
  assert.deepEqual(splitApprove(task, show, {}).missing, [2]);
  assert.deepEqual(splitApprove(task, show, { 2: "writing" }),
    { missing: [], request: { action: "split_go", task_id: task.task_id, choice: "y", skills: { 2: "writing" } } });
});

test("a split waiting on its pieces: each piece's state in the router's words, Skip only on a blocked one", () => {
  const [task, show] = find((t) => t.mode === "split" && t.waiting_on === "piece");
  const view = piecesView(task, show);
  assert.deepEqual(view.map((p) => [p.piece, p.words, !!p.skip]), [[1, "done", false], [2, "blocked: it failed its check twice", true]]);
  assert.deepEqual(view[1].skip, { action: "split_skip", task_id: show.pieces[1].task_id });
  const [plan, planShow] = find((t) => t.waiting_on === "split_plan");
  assert.equal(piecesView(plan, planShow), null);
});

test("a Grok wait takes its colour from the router's note; Re-check only when overdue", () => {
  assert.deepEqual(grokWait(find((t) => t.check_note === "waiting: grok, 6 min")[0]), { tone: "warn", note: "waiting: grok, 6 min", recheck: false });
  assert.deepEqual(grokWait(find((t) => t.check_note === "overdue: grok, 12 min")[0]), { tone: "bad", note: "overdue: grok, 12 min", recheck: true });
  assert.equal(grokWait(find((t) => t.outcome === "passed")[0]), null);
});

// ---------- when a task stops ----------

test("the stop offers come from the row: fallback after a double fail, resume after a plan limit or a process end", () => {
  const offers = (pred) => rescueOffers(find(pred)[0]).map((o) => [o.label, o.request.action]);
  assert.deepEqual(offers((t) => t.outcome === "failed_check" && t.mode === "route"), [["Redo with ChatGPT", "fallback"]]);
  assert.deepEqual(offers((t) => t.outcome === "plan_limit"), [["Resume with ChatGPT", "resume"]]);
  assert.deepEqual(offers((t) => t.outcome === "process_ended"), [["Resume: Claude again", "resume"]]);
  assert.deepEqual(offers((t) => t.check_note === "overdue: grok, 12 min"), [["Re-check", "check"], ["Cancel", "cancel"]]);
  assert.deepEqual(offers((t) => t.check_note === "waiting: grok, 6 min"), [["Cancel", "cancel"]]);
  assert.deepEqual(offers((t) => t.waiting_on === "pick"), [["Cancel", "cancel"]]);
  assert.deepEqual(offers((t) => t.waiting_on === "needs_label"), []);  // the floor card's own Cancel
  assert.deepEqual(offers((t) => t.outcome === "passed"), []);
  assert.deepEqual(offers((t) => t.outcome === "unchecked"), []);  // offers say no: no button
});

test("a fallback names who redoes it and who checks; a resume names the substitute or the same agent", () => {
  const [failed] = find((t) => t.outcome === "failed_check" && t.mode === "route");
  assert.equal(rescueOffers(failed)[0].note, "once per task · the checker redoes it, Claude checks the redo");
  const [limit] = find((t) => t.outcome === "plan_limit");
  assert.equal(rescueOffers(limit)[0].note, "once per task · Claude checks");
  const [ended] = find((t) => t.outcome === "process_ended");
  assert.equal(rescueOffers(ended)[0].note, "the same agent, no substitute · once per task");
});

// ---------- boards ----------

test("versus: A and B with the other's review; Pick A, Pick B and Neither only while it waits", () => {
  const [task, show] = find((t) => t.waiting_on === "pick");
  const board = versusBoard(task, show);
  assert.deepEqual(board.cards.map((c) => [c.letter, c.builder, c.review && c.review.reviewer]), [["a", "Claude", "ChatGPT"], ["b", "ChatGPT", "Claude"]]);
  assert.deepEqual(board.choices.map((c) => [c.label, c.request]), [
    ["Pick A", { action: "pick", task_id: task.task_id, choice: "a" }],
    ["Pick B", { action: "pick", task_id: task.task_id, choice: "b" }],
    ["Neither", { action: "pick", task_id: task.task_id, choice: "none" }]]);
  const [picked, pickedShow] = find((t) => t.preset === "versus" && t.outcome === "picked");
  const done = versusBoard(picked, pickedShow);
  assert.deepEqual([done.picking, done.choices, done.cards.map((c) => c.picked)], [false, [], [true, false]]);
});

test("vote: three answers, the tally and the winner; a tie offers A, B, C or Neither", () => {
  const [task, show] = find((t) => t.preset === "vote" && t.outcome === "passed");
  const board = voteBoard(task, show);
  assert.equal(board.tally, "2 of 3 agree");
  assert.deepEqual(board.votes.map((v) => [v.letter, v.answer, v.side]), [["a", "Monthly", "winner"], ["b", "Monthly", "agrees"], ["c", "Weekly", "alone"]]);
  assert.deepEqual(board.choices, []);
  const [tie, tieShow] = find((t) => t.waiting_on === "vote_pick");
  const tied = voteBoard(tie, tieShow);
  assert.equal(tied.tally, "no majority");
  assert.deepEqual(tied.choices.map((c) => c.request.choice), ["a", "b", "c", "none"]);
  assert.deepEqual(tied.votes.map((v) => v.side), ["alone", "alone", "alone"]);
});

test("redteam: each finding with its severity and the reviser's answer or fixed", () => {
  const [task, show] = find((t) => t.preset === "redteam");
  assert.deepEqual(redteamBoard(task, show).findings.map((f) => [f.severity, f.fix]), [
    ["high", "fixed"], ["medium", "fixed"], ["low", "answered: The column names are fixed in step 1, so this attack does not apply."]]);
  assert.equal(redteamBoard(find((t) => t.preset === "versus")[0], find((t) => t.preset === "versus")[1]), null);
});

// ---------- memory ----------

test("the memory drawer: each entry as given, newest first, the per-call lines and what was stored", () => {
  const [task, show] = find((t) => t.skill === "recall" && t.chat === "garden");
  const drawer = memoryDrawer(task, show);
  assert.equal(drawer.tag, "chat garden");
  assert.deepEqual(drawer.given.map((g) => g.head), ["#7 · 2026-10-19 · vote · Claude", "#2 · 2026-10-19 · writing · Claude", "#1 · 2026-10-19 · writing · Claude"]);
  assert.match(drawer.given[0].text, /## Answer\nMonthly/);
  assert.deepEqual(drawer.calls.map((c) => `${c.who}: ${c.what}`), ["build · Claude: sent 3 of 3", `check · ChatGPT: sent 3 of 3, the block from ${show.calls[1].memory.from}`]);
  assert.deepEqual(drawer.stored, [`${show.memory_stored[0].document_id} · 139 characters · done/passed/2`]);
  assert.equal(memoryDrawer(find((t) => !t.tag)[0], find((t) => !t.tag)[1]), null);
});

test("a Grok trim, an unavailable store and an old call read as Terminal says them", () => {
  const lines = memoryCallLines([
    { kind: "stage", stage: 2, agent: "grok", memory: { state: "left_out", with: 4100, limit: 3662 } },
    { kind: "reask", stage: 3, agent: "claude", memory: { state: "unavailable" } },
    { kind: "do", agent: "claude", memory: { state: "not_kept" } }]);
  assert.deepEqual(lines.map((l) => `${l.who}: ${l.what}`), [
    "stage 2 · Grok Bot: left out: it could not fit Grok's prompt limit (4100 > 3662)",
    "stage 3 re-ask · Claude: the store was unavailable; the call ran without it",
    "build · Claude: not kept"]);
  assert.equal(lines[0].trimmed, true);
  assert.equal(handoffWords({ attached: true, lines: 2, total: 2, left_out: false }), "Handoff attached: 2 of 2 lines");
  assert.equal(handoffWords({ attached: false, lines: null, total: 40, left_out: true }), "Handoff left out: it could not fit Grok's prompt limit (40 lines)");
  assert.equal(handoffWords(null), null);
});

// ---------- the Needs you list, and an agent off after a failed safety check ----------

test("the sidebar's Needs you: your turn, a stop the row can rescue and an overdue Grok task, newest first", () => {
  const list = needsYouList(TASKS);
  const byN = Object.fromEntries(list.you.map((i) => [i.n, i.what]));
  assert.deepEqual(Object.values(byN).sort(), [
    "A tie: pick one", "Approve a split plan", "Failed its check twice", "Failed its check twice", "Grok is overdue",
    "Pick A or B", "Pick a skill", "Pick a skill", "Plan limit", "Process ended"].sort());  // brief 24: Jev not set up too
  assert.deepEqual(list.you.map((i) => i.n), list.you.map((i) => i.n).slice().sort((a, b) => b - a));
  assert.equal(needsYou(find((t) => t.check_note === "waiting: grok, 6 min")[0]), null);
  assert.deepEqual(needsYouList([{ task_id: "x", n: 1, waiting_on: "memory" }]).router, [{ task_id: "x", n: 1, what: "Memory starting" }]);
});

test("a send refused because Cursor failed its safety check offers the other usable agents for that slot", () => {
  const status = structuredClone(STATUS);
  for (const agent of status.agents) if (agent.name === "chatgpt" || agent.name === "grok") Object.assign(agent, { configured: true, online: true, reason: null, available: true, why: null });
  // brief 24 (decision 14): a slot's `allowed` is the router's, available agents only; this status has them up
  for (const slot of status.presets.find((p) => p.name === "versus").slots) slot.allowed = ["claude", "grok", "chatgpt", "cursor"];
  const run = { envelope: { reason_code: "probe_failed" },
    request: { action: "send", team: "versus", text: "is_leap", chat: "brief23", slots: { b: "cursor" } } };
  const alts = refusalAlternatives(run, status);
  assert.deepEqual(alts.map((a) => [a.label, a.request.slots]), [
    ["Run it with Grok Bot in slot B", { b: "grok" }], ["Run it with ChatGPT in slot B", { b: "chatgpt" }]]);
  assert.equal(alts[0].request.text, "is_leap");  // the same task, nothing else changed
  assert.deepEqual(refusalAlternatives({ ...run, envelope: { reason_code: "override_refused" } }, status), []);
  assert.deepEqual(refusalAlternatives({ envelope: { reason_code: "probe_failed" } }, status), []);  // no request kept
});

test("the demo's confirm preview is the builder's Copy, byte for byte (the same fixture as test_page_commands)", () => {
  const cases = JSON.parse(readFileSync(new URL("../fixtures/page_copies.json", import.meta.url), "utf8"));
  for (const c of cases) assert.equal(demoCommand(c.request), c.copy);
});
