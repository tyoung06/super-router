// Build brief 33.2, R2 (decision 11): Revise plan on the page. Plan again lives in the plan panel beside the Stop here
// toggles and fills Plan, the project, an empty box with its placeholder (Send off while empty); the revision's card is
// the plan board with the inherited steps first, greyed and not editable, each with its tick and task, "revises #old"
// in its head, the coverage line and `## Changed` folded; the new steps editable. Every value here is fake.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { planAgainFill, planCardView, sendRequest } from "../../static/app.js";

const JS = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const CSS = readFileSync(new URL("../../static/app.css", import.meta.url), "utf8");

const PLAN = { steps: [
  { k: 1, text: "Make the skeleton.", team: "route", why: "smallest", done_when: "test_cli.py passes", calls: 2, max_calls: 4, jev_label: true,
    covers: [{ label: "E1", text: "c_to_f(100) == 212" }], state: "done", task: { task_id: "sr-s1", n: 14, status: "done" } },
  { k: 2, text: "Add the conversion.", team: "route", why: "core", done_when: "test_convert.py passes", calls: 2, max_calls: 4, jev_label: true,
    covers: [{ label: "E2", text: "f_to_c(212) == 100" }], state: "open", task: null },
  { k: 3, text: "Add c_to_k.", team: "route", why: "the idea", done_when: "test_k passes", calls: 2, max_calls: 4, jev_label: true,
    covers: [], state: "open", task: null }],
  needs: [], estimate: { calls: 4, max_calls: 8, jev_labels: 2 }, edits: [],
  coverage: { covered: ["E1", "E2"], missing: ["E3"], words: "Covers E1, E2; not E3" },
  revises: { task_id: "sr-old", n: 12 }, inherited: 1, changed: [{ step: 2, why: "its team is now route" }], spec_changed: false };
const WAITING = { task_id: "sr-rev", n: 17, mode: "plan", project: "garden", waiting_on: "land", land_anyway: false, plan: PLAN };

test("the revision's board: inherited steps first, greyed with their tick and task, the new steps editable", () => {
  const view = planCardView(WAITING, null);
  assert.equal(view.revises, "revises #12");
  assert.match(view.sub, /revises #12/);
  assert.equal(view.inherited, 1);
  const [one, two, three] = view.steps;
  assert.equal(one.inherited, true);
  assert.equal(one.done, "done by #14");
  assert.equal(one.doneTask, "sr-s1");
  assert.equal(one.edit, null);
  assert.deepEqual([one.up, one.down, one.drop], [null, null, null]);
  assert.deepEqual(one.options, []);
  assert.equal(two.inherited, false);
  assert.equal(two.up, null);  // never over a done step
  assert.deepEqual(two.down, { action: "plan_edit", task_id: "sr-rev", step: 2, change: "down" });
  assert.deepEqual(three.up, { action: "plan_edit", task_id: "sr-rev", step: 3, change: "up" });
  assert.equal(view.coverage, "Covers E1, E2; not E3");
  assert.deepEqual(view.changed, ["step 2: its team is now route"]);
  assert.equal(view.count, "4 to 8 calls for all the steps · Jev: 2 labels");  // the router counted the new steps
});

test("a plan that revises nothing has no inherited steps, no revises line and no Changed", () => {
  const plain = planCardView({ ...WAITING, plan: { ...PLAN, revises: null, inherited: 0, changed: null,
    steps: PLAN.steps.map((s) => ({ ...s, state: "open", task: null })) } }, null);
  assert.equal(plain.revises, null);
  assert.equal(plain.changed, null);
  assert.equal(plain.steps.every((s) => !s.inherited), true);
  assert.deepEqual(plain.steps[0].down, { action: "plan_edit", task_id: "sr-rev", step: 1, change: "down" });
});

test("Plan again fills Plan, the project, an empty box with its placeholder, nothing else; Send stays off while empty", () => {
  const fill = planAgainFill("garden");
  assert.deepEqual(fill, { text: "", team: "plan", project: "garden", chat: null, quick: false, from: null, idea: null, step: null,
    noFiles: false, placeholder: "What should change in the plan?" });
  const status = { projects: [{ name: "garden" }], presets: [], skills: [], jev: { available: true }, plan: { ready: true } };
  const request = sendRequest({ ...fill, files: [], slots: {} }, status);
  assert.deepEqual(request, { action: "send", team: "plan", text: "", project: "garden" });
  assert.match(JS, /id: "plan-again"/);  // the button in the plan panel, beside the Stop here toggles
  assert.match(JS, /state\.fillPlaceholder && \(state\.from \|\| state\.team === "plan"\)/);
});

test("an inherited step is drawn greyed and the Changed section folded", () => {
  assert.match(CSS, /\.plan-step\.inherited/);
  assert.match(JS, /class: "plan-changed"/);
  assert.match(JS, /summary", \{ text: "Changed"/);
});
