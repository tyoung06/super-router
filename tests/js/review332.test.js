// Build brief 33.2, the review's list: the step card quotes the SPEC.md example(s) it covers (decisions 6 and 18) from the
// router's `plan_step.covers`; the finish line's chips (decision 8) reach the page as the router gives them, Check against
// the spec first. Every value here is fake.
import { test } from "node:test";
import assert from "node:assert/strict";
import { stepCoversLine, whatNowParts } from "../../static/app.js";

test("a step card quotes the example(s) it covers; a step covering none, or off a plan, quotes nothing", () => {
  const step = { task_id: "sr-1", n: 7, plan_step: { plan: "sr-0", n: 3, step: 2, covers: [
    { label: "E1", text: "c_to_f(100) == 212" }, { label: "E2", text: "f_to_c(212) == 100" }] } };
  assert.equal(stepCoversLine(step), "covers E1: c_to_f(100) == 212 · E2: f_to_c(212) == 100");
  assert.equal(stepCoversLine({ task_id: "sr-2", plan_step: { plan: "sr-0", n: 3, step: 1, covers: [] } }), null);
  assert.equal(stepCoversLine({ task_id: "sr-3", plan_step: null }), null);
  assert.equal(stepCoversLine({ task_id: "sr-4" }), null);
  assert.equal(stepCoversLine(null), null);
});

test("the finish line's chips pass through as the router orders them: Check against the spec first", () => {
  const check = { kind: "spec_check", words: "Check against the spec", later: false,
    fill: { team: "route", project: "garden", chat: null, text: "Check the project against SPEC.md's `## Done when` list: for each "
      + "item, D1 on, say met or not met, with the evidence (the test or the file), then what is missing. Change no files; report only.",
      from: null, idea: null, step: null } };
  const readme = { kind: "readme", words: "Write the README", later: false, fill: { team: "route", project: "garden", text: "Write the README." } };
  const next = { kind: "what_next", words: "What next", later: false, fill: { team: "plan", project: "garden", text: "What next?" } };
  const parts = whatNowParts({ rung: "finish", words: "All 2 steps done", control: "chips", chips: [check, readme, next], task_id: "sr-0" });
  assert.equal(parts.lead, "All 2 steps done");
  assert.deepEqual(parts.chips.map((c) => c.words), ["Check against the spec", "Write the README", "What next"]);
  assert.equal(parts.chips[0].fill.team, "route");
  assert.match(parts.chips[0].fill.text, /Change no files; report only\.$/);
});
