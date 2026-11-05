// Build brief 33.2, C (decision 6): `covers:` on the plan card and the coverage line, from the router's JSON (each step's
// `covers` with its example's text, the plan's `coverage`); an edit of a step's covers is one `sr plan --edit --covers`.
// Without examples in the spec the card is as before. Every value here is fake.
import { test } from "node:test";
import assert from "node:assert/strict";
import { COVERS_MAX, coversWords, demoCommand, planCardView, planEditRequest } from "../../static/app.js";

const PLAN = { steps: [
  { k: 1, text: "Make the skeleton.", team: "route", why: "smallest", done_when: "test_cli.py passes", calls: 2, max_calls: 4, jev_label: true,
    covers: [{ label: "E1", text: "c_to_f(100) == 212" }] },
  { k: 2, text: "Add the conversion.", team: "redteam", why: "core", done_when: "test_convert.py passes", calls: 5, max_calls: 7, covers: [] }],
  needs: [], estimate: { calls: 7, max_calls: 11, jev_labels: 1 }, edits: [],
  coverage: { covered: ["E1"], missing: ["E2", "E3"], words: "Covers E1; not E2, E3" } };
const WAITING = { task_id: "sr-p", n: 12, mode: "plan", project: "garden", waiting_on: "land", land_anyway: false, plan: PLAN };

test("each step shows its covers and the card its coverage line, from the router's words", () => {
  const view = planCardView(WAITING, null);
  assert.deepEqual(view.steps.map((s) => s.covers), ["E1", "none"]);
  assert.equal(view.coverage, "Covers E1; not E2, E3");
  assert.equal(coversWords({ covers: [{ label: "E1", text: "x" }, { label: "E3", text: "y" }] }), "E1, E3");
  assert.equal(coversWords({ covers: [] }), "none");
  assert.equal(coversWords({ covers: [{ label: null, text: "gone", changed: true }, { label: "E3", text: "y" }] }), "example changed, E3");
});

test("without examples in the spec there is no covers line and no coverage line", () => {
  const plain = planCardView({ ...WAITING, plan: { ...PLAN, coverage: null, steps: PLAN.steps.map((s) => ({ ...s, covers: [] })) } }, null);
  assert.deepEqual(plain.steps.map((s) => s.covers), [null, null]);
  assert.equal(plain.coverage, null);
});

test("an edit of a step's covers is one sr plan --edit --covers, checked by the router", () => {
  assert.deepEqual(planEditRequest(WAITING, 2, "covers", "E2, E3"), { action: "plan_edit", task_id: "sr-p", step: 2, change: "covers", value: "E2, E3" });
  assert.equal(demoCommand(planEditRequest(WAITING, 2, "covers", "E2, E3")), "sr plan --edit sr-p --step 2 --covers -- 'E2, E3'");
  const editing = planCardView(WAITING, null, { editing: { taskId: "sr-p", k: 1, field: "covers", text: "E1, E2" } });
  assert.equal(editing.steps[0].edit.field, "covers");
  assert.equal(editing.steps[0].edit.unchanged, false);
  assert.equal(editing.steps[0].edit.count, `6 of ${COVERS_MAX} characters`);
  assert.deepEqual(editing.steps[0].edit.save, { action: "plan_edit", task_id: "sr-p", step: 1, change: "covers", value: "E1, E2" });
});
