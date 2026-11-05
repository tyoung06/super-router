// Build brief 29 (rules 2.41, Interface, "Split on the page"; decisions 1, 3, 7, 8, 10, 17 and 18): the page's split, as
// pure functions of the JSON. The Team menu ends with Split (⌥7); the composer's Split state (never a chat tag, a project
// at most, Quick, files and web greyed with reasons, Jev's words, the placeholder from status); the plan card's rows, team
// select, edit states and count line; the split's card after the approval; the No split card. Fixtures are inline,
// shaped as `sr status --json` and `sr show --json` print them. Every value is fake.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  chipViews, composerGreys, contextFor, countLine, fileView, jevBox, jevLabelsLine, jevPieceWords, noSplitView, parseComposer,
  PART_SHOWN, partWords, piecesView, placeholderFor, projectLine, routeItRequest, sendRequest, shortcutFor, splitApprove,
  splitEditRequest,
  splitPlanView, taskSummary,
} from "../../static/app.js";

const TEAMS = [
  { name: "route", ready: true, why: null, project: true },
  { name: "research-build", ready: true, why: null, project: true },
  { name: "collab", ready: true, why: null, project: false },
  { name: "versus", ready: true, why: null, project: false },
  { name: "redteam", ready: true, why: null, project: true },
  { name: "vote", ready: false, why: "vote can't run now: slot c (Grok Bot): Grok Bot isn't set up", project: false },
];
const STATUS = {
  presets: ["research-build", "collab", "versus", "redteam", "vote"].map((name) => ({ name, ready: true, description: `${name} words`, chain: `${name} chain`, slots: [] })),
  split: { ready: true, why: null, description: "Claude breaks the task into 2 to 4 pieces, each with its own team; you approve the plan; the pieces run one at a time; Claude joins the results and ChatGPT checks the whole.",
    chain: "Claude plan → your approval → the pieces, one at a time → Claude join → ChatGPT check", checker: "chatgpt", teams: TEAMS },
  skills: [{ key: "writing" }, { key: "code" }], jev: { floor: 0.8, available: true },
};
const base = { team: "split", text: "Two separate things", chat: "chat-20261027-1040", project: null, quick: false, files: [], web: false, slots: {} };
const SPLIT = { task_id: "sr-20261027-104210-7c1a", n: 214, mode: "split", waiting_on: "split_plan", agent: "claude", checker: "chatgpt",
  project: null, project_files: null, text: "Three separate things" };
const piece = (k, extra) => ({ piece: k, task_id: `sr-p${k}`, n: null, text: `Piece ${k} text`, edited: false, team: "route",
  planner_team: "route", team_source: "planner", team_why: "One short piece of writing: the skill table's writer is enough.",
  chain: null, needs_you: null, calls: 2, max_calls: 4, refused: null, needs_label: false, project_files: null,
  route: { skill: "writing", agent: "claude", checker: "chatgpt", comes_back: null }, jev: { status: "ok", label: "writing", confidence: 0.94 },
  piece_state: null, why: null, outcome: null, ...extra });
const SHOW = { pieces: [piece(1), piece(2, { team: "versus", planner_team: "vote", team_source: "owner", needs_you: "pick", calls: 4, max_calls: 4,
  chain: "Claude build → ChatGPT build → ChatGPT review → Claude review → your pick", route: null,
  jev: { status: "ok", label: "quick_answer", confidence: 0.86 }, team_why: "A judgment call: three answers made on their own settle it." }),
piece(3, { team: "research-build", chain: "Grok research → Claude build → ChatGPT check", calls: 3, max_calls: 5, route: null,
  jev: { status: "ok", label: "web_research", confidence: 0.91 } })],
join: "One note: the explainer, then the language pick, then the cost range.", estimate: { calls: 11, max_calls: 17, jev_labels: 3 }, menu: TEAMS };

// ---------- the Team menu and the composer (decision 1) ----------

test("the Team menu ends with Split on ⌥7, its words from status, greyed with status's reason when it can't run", () => {
  const chips = chipViews(STATUS, "split");
  assert.deepEqual(chips.map((c) => [c.key, c.shortcut]), [["route", "⌥1"], ["research-build", "⌥2"], ["collab", "⌥3"],
    ["versus", "⌥4"], ["redteam", "⌥5"], ["vote", "⌥6"], ["split", "⌥7"]]);
  const split = chips.at(-1);
  assert.equal(split.checked, true);
  assert.equal(split.title, `${STATUS.split.description} · ${STATUS.split.chain}`);
  const off = chipViews({ ...STATUS, split: { ...STATUS.split, ready: false, why: "Claude is signed out: claude auth login" } }).at(-1);
  assert.deepEqual([off.disabled, off.reason], [true, "Claude is signed out: claude auth login"]);
  assert.equal(chipViews({ ...STATUS, split: undefined }).some((c) => c.key === "split"), false, "a router with no split shows none");
});

test("⌥7 outside a text box picks the seventh team; /split picks Split", () => {
  assert.deepEqual(shortcutFor({ altKey: true, code: "Digit7" }), { action: "chip", index: 6 });
  assert.equal(shortcutFor({ altKey: true, code: "Digit7" }, { inText: true }), null);
  assert.deepEqual(parseComposer("/split two things", []).slash, { kind: "split", value: null });
  assert.equal(parseComposer("/split two things", []).text, "two things");
});

test("Split never carries a chat tag, even from a chat; a project rides; the request is the text and the project", () => {
  assert.deepEqual(contextFor(base, STATUS), { kind: "split", flag: null, value: null, projectGreyed: false, takesProject: true });
  assert.deepEqual(sendRequest(base, STATUS), { action: "send", team: "split", text: "Two separate things" });
  const onProject = { ...base, project: "brief29-demo" };
  assert.deepEqual(contextFor(onProject, STATUS).value, "brief29-demo");
  assert.deepEqual(sendRequest(onProject, STATUS), { action: "send", team: "split", text: "Two separate things", project: "brief29-demo" });
  assert.deepEqual(sendRequest({ ...base, quick: true, files: [{ path: "/x" }], web: true, slots: { a: "claude" }, skill: "code" }, STATUS),
    { action: "send", team: "split", text: "Two separate things" });
});

test("the composer greys Quick, files and web with their reasons on Split; Jev's box and the placeholder say the chain", () => {
  assert.deepEqual(composerGreys("split"), { quick: "A split never carries a chat tag, so Quick has nothing to drop",
    files: "Files go on Route only", web: "Web goes on Route only" });
  assert.deepEqual(composerGreys("route"), { quick: null, files: null, web: null });
  assert.deepEqual(jevBox({ team: "split" }), { mode: "not_asked", text: "Jev labels each piece once Claude plans them" });
  assert.equal(placeholderFor("split", STATUS), `New task for Split: ${STATUS.split.chain}`);
});

// ---------- the plan card (decisions 7, 8 and 18a) ----------

test("each piece shows its team from the menu, the planner's why, where it goes, Jev's label and the pick it needs", () => {
  const view = splitPlanView(SPLIT, SHOW);
  const [one, two, three] = view.pieces;
  assert.deepEqual([one.team, one.words, one.jev, one.mark, one.changedFrom], ["route", "writing · Claude, ChatGPT checks", "Jev: writing 0.94", null, null]);
  assert.deepEqual([two.team, two.words, two.mark, two.changedFrom], ["versus", SHOW.pieces[1].chain, "needs your pick", "vote"]);
  assert.equal(two.jev, "Jev: quick_answer 0.86, not used: versus names its own agents");
  assert.equal(three.words, "Grok research → Claude build → ChatGPT check");
  assert.deepEqual(one.options.map((o) => [o.name, o.disabled]), TEAMS.map((t) => [t.name, t.ready === false]));
  assert.equal(one.options.at(-1).why, TEAMS.at(-1).why);
  assert.equal(view.count, "About 11 agent calls from here, up to 17 with fix rounds.");
  assert.equal(view.jevLine, "Jev: 3 labels so far; an edited text adds one");
  assert.deepEqual([view.approveOff, view.rejectOff, view.project], [null, null, null]);
});

test("a tie, a refusal, an under-the-floor route piece and the project line", () => {
  const show = { ...SHOW, pieces: [piece(1, { needs_label: true, route: null, jev: { status: "below_floor", label: "planning", confidence: 0.55 } }),
    piece(2, { team: "vote", needs_you: "tie", chain: "Claude vote → ChatGPT vote → Grok vote → tally", route: null,
      refused: { code: "too_long", reason: "the task is too long for grok's vote (slot c)" } })] };
  const view = splitPlanView({ ...SPLIT, project: "brief29-demo", project_files: { mode: "on" } }, show);
  assert.equal(view.pieces[0].words, "Jev left it under the floor (planning at 0.55): pick its skill");
  assert.equal(view.pieces[1].mark, "a tie needs your pick");
  assert.equal(view.pieces[1].refused, "the task is too long for grok's vote (slot c)");
  assert.equal(view.approveOff, "Piece 2 can't run: the task is too long for grok's vote (slot c)");
  assert.equal(view.project, "On brief29-demo · one copy · you land once at the end");
  assert.equal(projectLine({ project: "plain", project_files: { mode: "off", why: "no git yet: Turn on undo" } }),
    "On plain · handoff only (no git yet: Turn on undo)");
  assert.deepEqual(splitApprove(SPLIT, show, {}).missing, [1]);
  assert.deepEqual(splitApprove(SPLIT, show, { 1: "writing" }).request.skills, { 1: "writing" });
});

test("an open edit or a running one turns Approve and Reject off and says why; the edit's counter and its one request", () => {
  const ui = { editing: { taskId: SPLIT.task_id, piece: 1, text: "Write a 120-word explainer, for a homeowner." } };
  const view = splitPlanView(SPLIT, SHOW, ui);
  assert.equal(view.approveOff, "Save or cancel piece 1's edit to approve");
  assert.equal(view.rejectOff, "Save or cancel piece 1's edit first");
  const edit = view.pieces[0].edit;
  assert.equal(edit.count, "44 of 399 characters · saving labels it again (one Jev label)");
  assert.deepEqual(edit.save, { action: "split_edit", task_id: SPLIT.task_id, piece: 1, text: ui.editing.text });
  assert.equal(view.pieces[1].edit, null);
  const tooLong = splitPlanView(SPLIT, SHOW, { editing: { ...ui.editing, text: "x".repeat(400) } }).pieces[0].edit;
  assert.equal(tooLong.tooLong, true);
  const running = splitPlanView(SPLIT, SHOW, { running: true });
  assert.deepEqual([running.approveOff, running.rejectOff], ["A change to the plan is running", "A change to the plan is running"]);
  assert.deepEqual(splitEditRequest(SPLIT, 2, { team: "redteam" }), { action: "split_edit", task_id: SPLIT.task_id, piece: 2, team: "redteam" });
  assert.equal(splitPlanView({ ...SPLIT, waiting_on: "piece" }, SHOW), null);
});

test("the count line has its most only when fix rounds can add calls", () => {
  assert.equal(countLine({ calls: 9, max_calls: 9, jev_labels: 2 }), "About 9 agent calls from here.");
  assert.equal(countLine({ calls: 1, max_calls: 1, jev_labels: 1 }), "About 1 agent call from here.");
  assert.equal(jevLabelsLine({ calls: 1, max_calls: 1, jev_labels: 1 }), "Jev: 1 label so far; an edited text adds one");
  assert.equal(jevPieceWords({ status: "not_set_up" }, "route"), "Jev isn't set up");
});

// ---------- the split's card after the approval (decision 18b) ----------

test("each piece with its team and state; Skip on a blocked one; a held one waits; a pick links to the piece's card", () => {
  const task = { ...SPLIT, waiting_on: "piece" };
  const show = { ...SHOW, pieces: [
    piece(1, { n: 215, piece_state: "done", outcome: "passed" }),
    piece(2, { n: 216, team: "versus", piece_state: "waiting", why: "waits for your pick" }),
    piece(3, { n: 217, piece_state: "blocked", why: "it was cancelled", project_files: { changed: [
      { path: "calc.py", status: "changed", plus: 5, minus: 0 }, { path: "test_calc.py", status: "changed", plus: 6, minus: 1 }] } }),
    piece(4, { n: 218, piece_state: "waiting", why: "waits for piece 3" })] };
  const view = piecesView(task, show);
  assert.deepEqual(view.map((p) => [p.piece, p.team, p.words, !!p.skip, !!p.open]), [
    [1, "route", "passed", false, false], [2, "versus", "waits for your pick", false, true],
    [3, "route", "blocked: it was cancelled", true, false], [4, "route", "waits for piece 3", false, false]]);
  assert.deepEqual(view[1].open, { task_id: "sr-p2", n: 216 });
  assert.deepEqual(view[2].skip, { action: "split_skip", task_id: "sr-p3" });
  assert.deepEqual(view[2].part, ["calc.py +5", "test_calc.py +6 −1"]);
  assert.deepEqual(partWords([{ path: "old.py", status: "deleted", plus: 0, minus: 0 }]), ["old.py deleted"]);
});

test("a piece's own card names its team and its place in its split", () => {
  const summary = taskSummary({ task_id: "sr-p2", mode: "relay", preset: "versus", parent: SPLIT.task_id, waiting_on: "pick",
    piece_of: { split: SPLIT.task_id, n: 214, piece: 2, team: "versus" } });
  assert.deepEqual([summary.team, summary.pieceOf, summary.piece], ["Versus", "piece 2 of split #214", true]);
});

// ---------- the No split card (decision 3) ----------

test("No split: the planner's one line from the JSON and Route it with the split's text and project", () => {
  const task = { ...SPLIT, waiting_on: null, outcome: "stopped", no_split: "Each part needs the one before it.", project: "brief29-demo" };
  assert.deepEqual(noSplitView(task), { title: "No split", sub: "an answer, not a failure · nothing was made",
    line: "Each part needs the one before it.", project: "brief29-demo", text: SPLIT.text });
  assert.equal(noSplitView({ ...task, no_split: null }), null);
  assert.equal(noSplitView({ ...task, mode: "route" }), null);
});

// ---------- C4 (/break-ui) ----------

test("a project split still at its plan or on its pieces shows its copy building, never Discard", () => {
  // the page offered "can't land · the task stopped before it was checked" and Discard on a plan that hadn't run
  const record = { mode: "on", state: "none", copy: true, base: "4f2a9c1e5b7d3a8f", branch: "main", changed: [] };
  for (const waiting_on of ["split_plan", "piece"]) {
    const view = fileView({ task_id: "sr-s", mode: "split", status: "returned", waiting_on, project: "garden-site",
      project_files: record });
    assert.equal(view.kind, "building");
    assert.deepEqual(view.buttons, []);
    assert.equal(view.line, "Files: a copy of garden-site at 4f2a9c1");
  }
  const stopped = fileView({ task_id: "sr-s", mode: "split", status: "failed", waiting_on: null, outcome: "plan_limit",
    project: "garden-site", project_files: record });
  assert.equal(stopped.kind, "kept", "a split that stopped with its copy still offers Discard");
});

test("a route piece under the floor names Jev once: in where it goes, not again beside it", () => {
  const view = splitPlanView(SPLIT, { ...SHOW, pieces: [piece(1, { needs_label: true, route: null,
    jev: { status: "below_floor", label: "planning", confidence: 0.52 } }), SHOW.pieces[1]] });
  assert.equal(view.pieces[0].words, "Jev left it under the floor (planning at 0.52): pick its skill");
  assert.equal(view.pieces[0].jev, null);
});

test("Route it: the split's text as a routed task from the view it is in, the split's project when it had one", () => {
  // C4: Route it borrowed the composer's state and, when the send stopped for a skill, left the composer changed
  const view = { text: "Write the parser, then its docstring from it", project: null };
  const ui = { chat: "chat-20261027-1040", quick: false, newChat: "chat-20261027-1101" };
  assert.deepEqual(routeItRequest(view, ui, STATUS).request,
    { action: "send", team: "route", text: view.text, chat: "chat-20261027-1040" });
  assert.deepEqual(routeItRequest(view, { ...ui, chat: null }, STATUS).request,
    { action: "send", team: "route", text: view.text, chat: "chat-20261027-1101" }, "no chat open: a new one, as Send does");
  assert.deepEqual(routeItRequest(view, { ...ui, chat: null, quick: true }, STATUS).request,
    { action: "send", team: "route", text: view.text }, "Quick on: no tag");
  assert.deepEqual(routeItRequest({ ...view, project: "garden-site" }, ui, STATUS).request,
    { action: "send", team: "route", text: view.text, project: "garden-site" }, "the split's project, never with a chat");
});

test("Route it without Jev: the card asks for the skill first, and the request carries it", () => {
  const noJev = { ...STATUS, jev: { available: false, why: "Jev isn't set up: pick the skill" } };
  const view = { text: "Write the parser, then its docstring from it", project: null };
  const ui = { chat: "chat-20261027-1040", quick: false, newChat: "x" };
  const found = routeItRequest(view, ui, noJev);
  assert.equal(found.pick.needed, true);
  assert.equal(found.pick.chosen, null);
  assert.deepEqual(found.pick.options.map((o) => o.key), ["writing", "code"]);
  assert.equal(routeItRequest(view, ui, noJev, "code").request.skill, "code");
});

test("a piece's part shows its first files and how many more, never a wall of chips; no +0 or −0", () => {
  // C4: a 37-file part drew 37 chips; a piece may change up to 500 files (the change limit)
  const changed = Array.from({ length: 37 }, (_, k) => ({ path: `content/section_${k}.md`, status: "added", plus: 12, minus: 0 }));
  const task = { ...SPLIT, waiting_on: "piece", status: "returned" };
  const [view] = piecesView(task, { pieces: [piece(1, { n: 215, piece_state: "done", outcome: "passed",
    project_files: { changed } })] });
  assert.equal(view.part.length, PART_SHOWN);
  assert.deepEqual(view.part.slice(0, 2), ["content/section_0.md +12", "content/section_1.md +12"]);
  assert.equal(view.more, 37 - PART_SHOWN);
  assert.deepEqual(partWords([{ path: "a", status: "deleted", plus: 0, minus: 1 }, { path: "b.py", status: "changed", plus: 0, minus: 4 },
    { path: "logo.png", status: "added", plus: null, minus: null }]), ["a deleted −1", "b.py −4", "logo.png"]);
});
