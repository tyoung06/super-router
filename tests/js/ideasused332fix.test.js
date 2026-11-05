// Brief 33.2 fix 4 (the owner's decision 4, item 6 / D2 option B): the Ideas sheet's folded "Used (n)" list under the
// open one, each used idea with its text and "used by #<n>"; no section without a used idea; folded by default, inside
// the sheet, so the project view gains no control. Every value here is fake.
import { test } from "node:test";
import assert from "node:assert/strict";
import { ideasSheetView } from "../../static/app.js";

const OPEN = { id: 2, text: "Write the tests for negative values.", source: { kind: "added", task_id: null, n: null },
  created_at: "2026-10-31T06:00:00+00:00", state: "open", sent_as: null };
const USED = { id: 1, text: "Add c_to_k(c) to conv.py with a unittest", source: { kind: "added", task_id: null, n: null },
  created_at: "2026-10-31T05:00:00+00:00", state: "used", sent_as: null, used_by: { task_id: "sr-p", n: 159 } };

test("used ideas sit in a folded Used (n) section, each with its text and the task that used it", () => {
  const view = ideasSheetView({ ideas: [OPEN], dismissed: 0, used: [USED] }, { name: "garden" });
  assert.deepEqual(view.rows.map((r) => r.text), [OPEN.text]);  // the open list is as before
  assert.ok(view.used, "the sheet has no Used section");
  assert.equal(view.used.title, "Used (1)");
  assert.equal(view.used.folded, true);
  assert.deepEqual(view.used.rows, [{ id: 1, text: USED.text, by: "used by #159", taskId: "sr-p" }]);
});

test("with no used idea there is no section, and an empty open list still reads empty", () => {
  assert.equal(ideasSheetView({ ideas: [OPEN], dismissed: 0, used: [] }, { name: "garden" }).used, null);
  assert.equal(ideasSheetView({ ideas: [OPEN], dismissed: 0 }, { name: "garden" }).used, null);
  const only = ideasSheetView({ ideas: [], dismissed: 0, used: [USED] }, { name: "garden" });
  assert.equal(only.empty, true);
  assert.equal(only.used.title, "Used (1)");
});
