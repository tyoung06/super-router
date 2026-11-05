// Build brief 33.2, A (decision 12): Add to plan on an idea's row fills the composer with team Plan, the project, the Idea
// pill and the idea's text, editable; the request carries the idea's id on a plan. Every value here is fake.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fillFromIdeaToPlan, ideasSheetView, sendRequest } from "../../static/app.js";

const JS = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const IDEA = { id: 3, text: "Add c_to_k(c) to conv.py with a unittest.", source: { kind: "added", task_id: null, n: null },
  created_at: "2026-10-30T10:00:00+00:00", state: "open", sent_as: null };

test("Add to plan fills Plan, the project, the Idea pill and the text, with Undo over typed words", () => {
  const { next, undo } = fillFromIdeaToPlan(IDEA, "garden", { text: "half a thought", team: "route", project: "garden" });
  assert.deepEqual(next, { text: IDEA.text, team: "plan", project: "garden", chat: null, quick: false, from: null,
    idea: { id: 3, text: IDEA.text }, step: null, noFiles: false, placeholder: null });
  assert.equal(undo.text, "half a thought");
  assert.equal(fillFromIdeaToPlan(IDEA, "garden", { text: "" }).undo, null);
});

test("the request carries the idea's id on a plan", () => {
  const status = { projects: [{ name: "garden" }], presets: [], plan: { ready: true }, skills: [], jev: { available: true } };
  const request = sendRequest({ team: "plan", text: IDEA.text, project: "garden", idea: { id: 3, text: IDEA.text }, files: [], slots: {} }, status);
  assert.deepEqual(request, { action: "send", team: "plan", text: IDEA.text, project: "garden", idea: 3 });
});

test("an open idea's row offers Add to plan beside Send; a sent one neither", () => {
  const view = ideasSheetView({ ideas: [IDEA, { ...IDEA, id: 4, state: "sent", sent_as: { task_id: "sr-9", n: 9 } }], dismissed: 0 }, { name: "garden" });
  assert.deepEqual(view.rows.map((r) => [r.canSend, r.canAddToPlan]), [[true, true], [false, false]]);
  assert.match(JS, /"Add to plan"\)/);
});
