// Brief 29.1 (decision 3; brief 28's issue 12): Send as <skill> on a task that came back not_routed. The chips are the
// skills status marks routed; each sends the row's text again as the floor answer command; nothing once answered.
import { test } from "node:test";
import assert from "node:assert/strict";
import { sendAsView } from "../../static/app.js";

const STATUS = { skills: [{ key: "code", routed: true }, { key: "computer_use", routed: false }, { key: "writing", routed: true }] };
const BACK = { task_id: "sr-20261027-101010-aaaa", n: 7, status: "returned", reason_code: "not_routed", answered_by: null,
  text: "list the files here", jev: { status: "ok", label: "computer_use", confidence: 0.93 } };

test("a not_routed return offers the routed skills, each as the floor answer with the row's text", () => {
  const view = sendAsView(BACK, STATUS);
  assert.equal(view.title, "Jev labeled it computer_use, which version 2 doesn't route");
  assert.deepEqual(view.skills.map((s) => s.key), ["code", "writing"]);
  assert.deepEqual(view.skills[0].request, { action: "floor", skill: "code", answers: BACK.task_id, text: BACK.text });
});

test("nothing once answered, on another return, or on a task that didn't come back", () => {
  assert.equal(sendAsView({ ...BACK, answered_by: "sr-20261027-111111-bbbb" }, STATUS), null);
  assert.equal(sendAsView({ ...BACK, reason_code: "needs_label" }, STATUS), null);
  assert.equal(sendAsView({ ...BACK, status: "done", reason_code: null }, STATUS), null);
  assert.equal(sendAsView(null, STATUS), null);
});
