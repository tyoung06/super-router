// Brief 29.1 (decision 7): three page bugs from brief 29. (a) an underscore inside a word is never emphasis, as
// CommonMark says; (b) a redraw gives the focus back to a control by its id or its stable key; (c) "Run again as…" builds
// its own request from the task, as Route it does, and never borrows the composer's state.
import { test } from "node:test";
import assert from "node:assert/strict";
import { focusMark, markdown, runAgainRequest } from "../../static/app.js";

const textOf = (nodes) => nodes.map((n) => n.type === "text" ? n.text : n.type === "code" ? n.text : `<${n.type}>${textOf(n.children || [])}</${n.type}>`).join("");
const para = (source) => textOf(markdown(source)[0].children);

test("an underscore inside a word stays as typed; one around a word is emphasis", () => {
  assert.equal(para("bed_area() needs rain_needed first"), "bed_area() needs rain_needed first");
  assert.equal(para("snake_case_name and two_words"), "snake_case_name and two_words");
  assert.equal(para("an _emphasis_ here"), "an <em>emphasis</em> here");
  assert.equal(para("_a_ and *b* and in*side*word"), "<em>a</em> and <em>b</em> and in<em>side</em>word");
  assert.equal(para("a `rain_needed` call"), "a rain_needed call");
});

test("a redraw finds a control again by its id, else by its stable key", () => {
  assert.deepEqual(focusMark({ id: "act-x-cancel", dataset: {} }), { id: "act-x-cancel" });
  assert.deepEqual(focusMark({ id: "", dataset: { focusKey: "run-again-sr-1" } }), { key: "run-again-sr-1" });
  assert.equal(focusMark({ id: "", dataset: {} }), null);
  assert.equal(focusMark(null), null);
});

const STATUS = { jev: { available: true }, skills: [{ key: "code" }, { key: "writing" }],
  presets: [{ name: "versus", project: true, slots: [{ name: "a", default: "claude" }, { name: "b", default: "chatgpt" }] }],
  split: { chain: "Claude plan → …" } };
const UI = { chat: "garden", quick: false, newChat: "chat-new" };

test("Run again as… sends the task's own text, from the view it is in, with the task's project", () => {
  const task = { task_id: "sr-1", text: "compare two seed trays", project: null };
  assert.deepEqual(runAgainRequest(task, "versus", UI, STATUS).request,
    { action: "send", team: "versus", text: "compare two seed trays", chat: "garden" });
  assert.deepEqual(runAgainRequest({ ...task, project: "seeds" }, "versus", UI, STATUS).request,
    { action: "send", team: "versus", text: "compare two seed trays", project: "seeds" });
  assert.deepEqual(runAgainRequest(task, "route", { ...UI, chat: null }, STATUS).request,
    { action: "send", team: "route", text: "compare two seed trays", chat: "chat-new" });
  assert.deepEqual(runAgainRequest(task, "split", UI, STATUS).request, { action: "send", team: "split", text: "compare two seed trays" });
  assert.deepEqual(runAgainRequest(task, "route", { ...UI, quick: true }, STATUS).request,
    { action: "send", team: "route", text: "compare two seed trays" });
});

test("a routed run again asks for its skill on the card when Jev isn't set up", () => {
  const off = { ...STATUS, jev: { available: false, why: "Jev isn't set up: pick the skill" } };
  const task = { task_id: "sr-1", text: "fix the bug", project: null };
  const asked = runAgainRequest(task, "route", UI, off);
  assert.equal(asked.pick.needed, true) ;
  assert.equal(asked.pick.chosen, null);
  const chosen = runAgainRequest(task, "route", UI, off, "code");
  assert.equal(chosen.request.skill, "code");
  assert.equal(runAgainRequest(task, "versus", UI, off).pick.needed, false);  // a team names its own agents
});

// Brief 29.1 (decision 12): an agent per piece: a preset piece's slots, each a select of what status allows.
import { pieceSlots, splitEditRequest } from "../../static/app.js";

test("a preset piece's slots are selects of the agents status allows, the default marked, each change one edit", () => {
  const presets = [{ name: "versus", slots: [{ name: "a", default: "claude", allowed: ["claude", "chatgpt", "cursor"] },
    { name: "b", default: "chatgpt", allowed: ["claude", "chatgpt", "cursor"] }] }];
  const task = { task_id: "sr-9" };
  const piece = { piece: 2, slots: { b: "cursor" }, slot_map: { a: "claude", b: "cursor" } };
  const slots = pieceSlots(task, piece, "versus", presets);
  assert.deepEqual(slots.map((s) => [s.name, s.agent, s.set]), [["a", "claude", false], ["b", "cursor", true]]);
  assert.ok(slots[1].options.some((o) => o.agent === "chatgpt" && o.label.endsWith("(default)")));
  assert.deepEqual(slots[1].request("chatgpt"), { action: "split_edit", task_id: "sr-9", piece: 2, slots: { b: "default" } });
  assert.deepEqual(slots[0].request("chatgpt"), splitEditRequest(task, 2, { slots: { a: "chatgpt" } }));
  assert.deepEqual(pieceSlots(task, { piece: 1, slot_map: null }, "route", presets), []);
});

// Brief 29.1 A8 (decision 7d and 7g): Route it sends once and names the task it made; a split that ends waiting to land
// is looked at again at the open pace, so Land and Discard come without a reload.
import { fileView, justClosed, pollInterval, routeItState } from "../../static/app.js";

test("Route it, once: after a send it stays off and the card names the task it made", () => {
  assert.equal(routeItState(undefined, []), null);
  const starting = routeItState({ run_id: "r1", task_id: null }, []);
  assert.deepEqual(starting, { off: "Sent: the new task is starting", label: "Sent", line: "Routed: the new task is starting",
    taskId: null });
  const made = routeItState({ run_id: "r1", task_id: "sr-9" }, [{ task_id: "sr-9", n: 31 }]);
  assert.deepEqual(made, { off: "Sent as #31", label: "Sent", line: "Routed as #31", taskId: "sr-9" });
});

test("Land without a reload: a running action or a task that just ended keeps the open pace", () => {
  const ended = [{ task_id: "sr-1", status: "done", outcome: null, waiting_on: "land" }];
  const open = [{ task_id: "sr-1", status: "returned", outcome: null, waiting_on: "piece" }];
  assert.equal(pollInterval(ended, 0, 0, false) > pollInterval(open, 0, 0, false), true);  // idle is slower than open
  assert.equal(pollInterval(ended, 0, 1, false), pollInterval(open));  // a page action still running
  assert.equal(justClosed(open, ended), true);
  assert.equal(pollInterval(ended, 0, 0, justClosed(open, ended)), pollInterval(open));  // the look right after it ends
  assert.equal(justClosed(ended, ended), false);
  const split = { task_id: "sr-1", status: "done", mode: "split", waiting_on: "land", project: "sums",
    project_files: { mode: "on", copy: true, state: "waiting", branch: "main", changed: [{ path: "calc.py", status: "modified", plus: 1, minus: 1 }] } };
  assert.deepEqual(fileView(split).buttons.map((b) => b.key), ["land", "discard"]);
});
