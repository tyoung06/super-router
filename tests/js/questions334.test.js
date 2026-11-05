// Build brief 33.4, Q4 (decision 14 and P1): the questions card. Each question with its options as chips, the guess marked
// and not pre-picked, an Other box under each; Send answers on only once every question has a pick or Other text; Use your
// best guess the quiet skip; then the planning line. It sits on the plan task's own card; What now? and Needs you carry the
// wait. The Approve confirm's hand-edit line (6b). Every value is fake.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { answersRequest, confirmExtra, needsConfirm, needsYou, PLANNING_LINE, questionsCardView, SECTION_EDITED_LINE } from "../../static/app.js";

const JS = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const TASK = { task_id: "sr-1", n: 7, mode: "plan", waiting_on: "answers", questions: { k: 2, waiting: true, planning: false, answers: null,
  asked: [{ k: 1, text: "Which units?", guess: "B", options: [{ letter: "A", text: "Length" }, { letter: "B", text: "Weight" }] },
    { k: 2, text: "Which input?", guess: "A", options: [{ letter: "A", text: "Flags" }, { letter: "B", text: "Prompt" }] }] } };

test("a task that didn't ask has no card", () => {
  assert.equal(questionsCardView({ mode: "plan", questions: null }), null);
  assert.equal(questionsCardView({ mode: "route", questions: TASK.questions }), null);
  assert.equal(questionsCardView({ ...TASK, questions: { ...TASK.questions, waiting: false } }), null);
});

test("the guess is marked and never pre-picked; Send answers starts off", () => {
  const view = questionsCardView(TASK);
  assert.equal(view.title, "The planner asks 2 questions before it plans");
  assert.deepEqual(view.questions[0].options.map((o) => [o.letter, o.guess, o.picked]), [["A", false, false], ["B", true, false]]);
  assert.equal(view.send, null);
  assert.equal(view.sendOff, "2 questions still to answer");
  assert.ok(view.bestGuess);
});

test("one question reads in the singular", () => {
  const one = { ...TASK, questions: { ...TASK.questions, asked: [TASK.questions.asked[0]] } };
  assert.equal(questionsCardView(one).title, "The planner asks 1 question before it plans");
});

test("partly answered: still off, and it says how many are left", () => {
  const view = questionsCardView(TASK, { picks: { 1: "A" } });
  assert.equal(view.send, null);
  assert.equal(view.sendOff, "1 question still to answer");
  assert.equal(view.questions[0].options[0].picked, true);
});

test("Send answers turns on with a pick or Other text on every question", () => {
  const view = questionsCardView(TASK, { picks: { 1: "A" }, others: { 2: "my words" } });
  assert.deepEqual(view.send, { action: "plan_answer", task_id: "sr-1", picks: { 1: "A" }, others: { 2: "my words" } });
  assert.equal(view.sendOff, null);
});

test("Other text replaces the pick; blank Other doesn't count", () => {
  const typed = questionsCardView(TASK, { picks: { 1: "A", 2: "B" }, others: { 1: "mine" } });
  assert.equal(typed.questions[0].options[0].picked, false);
  assert.deepEqual(typed.send, { action: "plan_answer", task_id: "sr-1", picks: { 2: "B" }, others: { 1: "mine" } });
  assert.equal(questionsCardView(TASK, { picks: { 1: "A" }, others: { 2: "   " } }).send, null);
  assert.deepEqual(answersRequest(TASK, { 1: "A" }, { 1: "  x " }), { action: "plan_answer", task_id: "sr-1", picks: {}, others: { 1: "x" } });
});

test("Use your best guess sends only that, with no confirm", () => {
  const request = questionsCardView(TASK).bestGuess;
  assert.deepEqual(request, { action: "plan_answer", task_id: "sr-1", best_guess: true });
  assert.equal(needsConfirm(request), false);
  assert.equal(needsConfirm({ action: "plan_answer", task_id: "sr-1", picks: { 1: "A" } }), false);
});

test("after either, the card reads the planning line", () => {
  assert.deepEqual(questionsCardView(TASK, { running: true }), { planning: true, line: PLANNING_LINE });
  assert.equal(PLANNING_LINE, "Planning with your answers…");
  const going = { ...TASK, waiting_on: null, questions: { ...TASK.questions, waiting: false, planning: true } };
  assert.equal(questionsCardView(going).planning, true);
});

test("the demo sends nothing", () => {
  const view = questionsCardView(TASK, { demo: true, picks: { 1: "A", 2: "A" } });
  assert.equal(view.send, null);
  assert.equal(view.bestGuess, null);
  assert.equal(view.sendOff, "Demo: nothing runs");
});

test("Needs you lists a plan waiting on answers", () => {
  assert.equal(needsYou(TASK), "Answer questions");
});

test("the Approve confirm says so in one line when the section differs", () => {
  const plan = { mode: "plan", plan: { section_edited: true } };
  assert.equal(confirmExtra(plan, { action: "land" }).line, SECTION_EDITED_LINE);
  assert.equal(confirmExtra({ mode: "plan", plan: {} }, { action: "land" }), null);
  const both = confirmExtra({ mode: "plan", plan: { section_edited: true, spec_changed: true } }, { action: "land" });
  assert.ok(both.line.includes(SECTION_EDITED_LINE) && both.line.includes("SPEC.md changed"));
});

test("the card is the plan task's own, drawn with no raw HTML, its answers one argument each", () => {
  const body = JS.slice(JS.indexOf("function questionsCard(task, view)"), JS.indexOf("function oneStepCard(task, view)"));
  assert.ok(!body.includes("innerHTML"));
  assert.ok(JS.includes("if (asked) return questionsCard(task, asked);"));
  assert.ok(body.includes("cardMainAction(") && body.includes('"Use your best guess"'));  // UI-1m (2.6): Send answers' label comes from cardMainAction
});
