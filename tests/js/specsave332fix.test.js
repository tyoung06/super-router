// Brief 33.2 fix 2 (the owner's decision 2, item 3 option B): after a spec save the page re-reads the project, so the plan
// card's "SPEC.md changed since this plan was made" line, What now? and Approve's confirm show the router's new answer at
// once; and Approve on a plan re-reads that plan (`sr show <n> --json`) before its confirm opens, so a spec changed from
// Terminal is caught. A failed re-read opens the confirm from the page's copy and says so. Every value here is fake.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as app from "../../static/app.js";

// a namespace import, so the file loads on code without the fix and each test fails on its own assertion
const { confirmExtra, planCardView, SPEC_CHANGED_LINE } = app;
const has = (name) => assert.equal(typeof app[name], "function", `the page has no ${name}`);

const PLAN = { steps: [{ k: 1, text: "Make the skeleton.", team: "route", why: "smallest", done_when: "test_cli.py passes", calls: 2,
  max_calls: 4, covers: [] }], needs: [], estimate: { calls: 2, max_calls: 4, jev_labels: 1 }, edits: [], coverage: null, spec_changed: false };
const WAITING = { task_id: "sr-p", n: 12, mode: "plan", project: "garden", waiting_on: "land", land_anyway: false, plan: PLAN };
const APPROVE = { action: "land", task_id: "sr-p" };

test("a spec save that ended well re-reads the status fresh, the log, What now? and the open plan's show", () => {
  has("specSaveReads");
  assert.deepEqual(app.SPEC_SAVE_READS, ["status", "log", "what_now", "shows"]);
  assert.deepEqual(app.specSaveReads(0), app.SPEC_SAVE_READS);
  assert.deepEqual(app.specSaveReads(2), []);  // a refused save changed nothing: nothing to read again
  assert.deepEqual(app.specSaveReads(null), []);
});

test("the card reads the fresh show's plan after the re-read", () => {
  const fresh = { ...WAITING, plan: { ...PLAN, spec_changed: true } };
  assert.equal(planCardView(WAITING, { plan: PLAN }).specChanged, null);
  assert.equal(planCardView(WAITING, fresh).specChanged, SPEC_CHANGED_LINE);
});

test("only a plan's Approve re-reads before its confirm", () => {
  has("rereadsBeforeConfirm");
  assert.equal(app.rereadsBeforeConfirm(WAITING, APPROVE), true);
  assert.equal(app.rereadsBeforeConfirm(WAITING, { ...APPROVE, anyway: true }), false);
  assert.equal(app.rereadsBeforeConfirm(WAITING, { action: "discard", task_id: "sr-p" }), false);
  assert.equal(app.rereadsBeforeConfirm({ task_id: "sr-r", mode: "route" }, { action: "land", task_id: "sr-r" }), false);
});

test("Approve's confirm follows the fresh plan: a spec changed from Terminal is caught, and a revert clears it", () => {
  has("approveConfirm");
  const changed = { ...WAITING, plan: { ...PLAN, spec_changed: true } };
  const found = app.approveConfirm(WAITING, changed);
  assert.equal(found.note, null);
  assert.deepEqual(confirmExtra(found.task, APPROVE), { line: `${SPEC_CHANGED_LINE}: the plan read the earlier one.`, musts: [] });
  const reverted = app.approveConfirm(changed, WAITING);  // the page's copy says changed; the router now says it isn't
  assert.equal(confirmExtra(reverted.task, APPROVE), null);
});

test("a failed re-read opens the confirm from the page's copy and says the plan couldn't be re-read", () => {
  has("approveConfirm");
  const found = app.approveConfirm(WAITING, null);
  assert.equal(found.task, WAITING);
  assert.equal(found.note, app.STALE_PLAN_LINE);
  assert.equal(app.STALE_PLAN_LINE, "The plan couldn't be re-read: this is the page's last copy of it.");
  const show = { task_id: "sr-p", plan: { ...PLAN, spec_changed: true } };  // a show without the log row's fields
  assert.equal(app.approveConfirm(WAITING, show).task.waiting_on, "land");
  assert.equal(app.approveConfirm(WAITING, show).task.plan.spec_changed, true);
});
