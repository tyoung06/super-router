// Build brief 33.2, T (decision 7): a spec changed after the plan, on the page. What now?'s spec_changed rung with its
// Revise plan chip; the plan card's "SPEC.md changed since this plan was made" and the Approve confirm's line; the Auto
// confirm's line when going on after a change; the run card's two ways on. Every value here is fake.
import { test } from "node:test";
import assert from "node:assert/strict";
import { autoBoard, autoConfirmView, confirmExtra, planCardView, SPEC_CHANGED_LINE, whatNowParts } from "../../static/app.js";

const CHIP = { kind: "revise_plan", words: "Revise plan", later: false,
  fill: { team: "plan", project: "garden", chat: null, text: "Revise the plan for the current SPEC.md.", from: null, idea: null, step: null } };
const LINE = { rung: "spec_changed", words: "SPEC.md changed since plan #12 · Revise plan", control: "chip", task_id: "sr-p", n: 12,
  chip: CHIP, need: null, chips: null, plan_md: null };
const PLAN = { steps: [{ k: 1, text: "Make the skeleton.", team: "route", why: "smallest", done_when: "test_cli.py passes", calls: 2,
  max_calls: 4, covers: [] }], needs: [], estimate: { calls: 2, max_calls: 4, jev_labels: 1 }, edits: [], coverage: null, spec_changed: true };
const WAITING = { task_id: "sr-p", n: 12, mode: "plan", project: "garden", waiting_on: "land", land_anyway: false, plan: PLAN };

test("the spec_changed rung reads the router's words with the Revise plan chip beside them", () => {
  const parts = whatNowParts(LINE);
  assert.equal(parts.lead, "SPEC.md changed since plan #12");
  assert.deepEqual(parts.chip, CHIP);
  assert.equal(parts.open, null);
});

test("a plan still waiting says the spec changed on its card and in the Approve confirm; nothing is refused", () => {
  const view = planCardView(WAITING, null);
  assert.equal(view.specChanged, SPEC_CHANGED_LINE);
  assert.deepEqual(view.approve, { action: "land", task_id: "sr-p" });
  assert.deepEqual(confirmExtra(WAITING, { action: "land", task_id: "sr-p" }), { line: `${SPEC_CHANGED_LINE}: the plan read the earlier one.`, musts: [] });
  const same = { ...WAITING, plan: { ...PLAN, spec_changed: false } };
  assert.equal(planCardView(same, null).specChanged, null);
  assert.equal(confirmExtra(same, { action: "land", task_id: "sr-p" }), null);
  assert.equal(confirmExtra({ task_id: "sr-r", mode: "route" }, { action: "land", task_id: "sr-r" }), null);
});

test("the Auto confirm carries the router's line when going on after a spec change, and nothing otherwise", () => {
  const dry = { exit: 0, auto: { words: "Auto runs step 2 of plan #12, 6 calls at most.", overrun: "A step already started finishes.",
    steps: [2], budget: 6, first_stop_here: null, spec_changed: true, spec_line: "The remaining steps will use the new SPEC.md." } };
  assert.equal(autoConfirmView(dry, "garden").specLine, "The remaining steps will use the new SPEC.md.");
  assert.equal(autoConfirmView({ exit: 0, auto: { ...dry.auto, spec_changed: false, spec_line: null } }, "garden").specLine, null);
  assert.equal(autoConfirmView(null, "garden").specLine, null);
});

test("a run stopped on a spec change names the two ways on, the router's words", () => {
  const ways = "Land the run so far or Discard run, then Revise plan; or turn the switch on again: the remaining steps use the new SPEC.md.";
  const task = { task_id: "sr-a", project: "garden", auto: { state: "stopped", steps: [], used: 2, budget: 6,
    stop: { code: "spec_changed", why: "SPEC.md changed since the run started", step: 2 }, ways, words: "Auto stopped: SPEC.md changed since the run started" } };
  const board = autoBoard(task, null, []);
  assert.equal(board.why, "SPEC.md changed since the run started");
  assert.equal(board.ways, ways);
  assert.deepEqual(board.buttons.map((b) => b.label), ["Land the run so far", "Discard run"]);
  assert.equal(autoBoard({ ...task, auto: { ...task.auto, ways: null, stop: { code: "stop_here", why: "x", step: 2 } } }, null, []).ways, null);
});

test("the run card carries the steps' tests sum, the router's words (decision 16)", () => {
  const sum = "Tests: `python3 -m unittest` · 3 runs across 2 steps, all passing at the end (step 1 fixed once)";
  const task = { task_id: "sr-a", project: "garden", auto: { state: "finished", steps: [], used: 4, budget: 6, stop: null, tests: sum, words: "Auto finished: land the run?" } };
  assert.equal(autoBoard(task, null, []).tests, sum);
  assert.equal(autoBoard({ ...task, auto: { ...task.auto, tests: null } }, null, []).tests, null);
});
