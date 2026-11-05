// Build brief UI-1m, section 5: the wiring phase 1 and 33.4 meet in. These press the page's real menus and keys, in a small
// stand-in for the browser (pagedom.js), and watch what the page sends. Fake data.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { loadPage } from "./pagedom.js";
import { cardMainAction, cardMenuItems, questionsCardView } from "../../static/app.js";

const read = (name) => JSON.parse(readFileSync(new URL(`../../demo/${name}`, import.meta.url), "utf8"));
const STATUS = read("status.json");
const PROJECT = STATUS.projects[0].name;
// demo/status.json has Jev not set up and ChatGPT signed out, which the Route item's tests keep on purpose: a filling item
// must not ask for a skill (33.4's !fill). A team's item only sends when its team can run, so those tests use this one.
const UP = { ...STATUS, jev: { ...STATUS.jev, configured: true, available: true, why: null },
  presets: STATUS.presets.map((p) => ({ ...p, ready: true, why: null })), split: { ...STATUS.split, ready: true, why: null }, plan: { ...STATUS.plan, ready: true, why: null } };
const DISCARD = read("log.json").tasks.find((t) => t.waiting_on === "land" && t.mode === "route");

const TEXT_ONLY = { task_id: "sr-text", n: 156, mode: "route", status: "done", outcome: "passed", project: PROJECT, text: "Draft the spec.",
  text_only: true, result: "A draft.", save_spec: { path: "SPEC.md" }, card_actions: [], next: [], created_at: "2026-11-03T10:00:00Z" };
const ASKING = { task_id: "sr-ask", n: 7, mode: "plan", status: "returned", waiting_on: "answers", project: PROJECT, text: "Plan it.", card_actions: [], next: [],
  created_at: "2026-11-03T10:00:00Z", questions: { k: 2, waiting: true, planning: false, answers: null,
    asked: [{ k: 1, text: "Which units?", guess: "B", options: [{ letter: "A", text: "Length" }, { letter: "B", text: "Weight" }] },
      { k: 2, text: "Which input?", guess: "A", options: [{ letter: "A", text: "Flags" }, { letter: "B", text: "Prompt" }] }] } };

async function open(task, { status = STATUS, ...options } = {}) {
  const page = await loadPage(options);
  Object.assign(page.state, { status, project: task.project, tasks: [task] });
  page.renderStream();
  return page;
}

const stream = (page) => page.el("stream");
const items = (page) => stream(page).querySelectorAll('[role="menuitem"]').map((n) => n.textContent);
const runs = (page) => page.posts.filter((p) => p.path === "/api/run");

// ---- 2.3: Run again ----

function assertFilled(page) {
  assert.equal(page.state.text, TEXT_ONLY.text);
  assert.equal(page.state.team, "route");
  assert.equal(page.state.project, TEXT_ONLY.project);
  assert.equal(page.state.noFiles, true);
  assert.equal(page.el("prompt").value, TEXT_ONLY.text);
  assert.equal(page.el("textonly-pill").hidden, false);
  assert.match(page.el("textonly-pill").textContent, /Text only/);
  assert.deepEqual(runs(page), [], "the Route item sends nothing");
}

test("Run again by ⋯, on a text-only card: the Route item fills the box and sends nothing", async () => {
  const page = await open(TEXT_ONLY);
  stream(page).querySelector(".more-btn").click();
  page.find("Run again as…", stream(page)).click();
  assert.ok(items(page).includes("Route: text only, in the box"), items(page).join(" | "));
  page.find("Route: text only, in the box", stream(page)).click();
  assertFilled(page);
});

test("Run again by ⋯, on a blocked text-only card: the Route item fills the box and sends nothing", async () => {
  const page = await open({ ...TEXT_ONLY, outcome: "blocked", check_state: "blocked", save_spec: null });
  stream(page).querySelector(".more-btn").click();
  page.find("Run again as…", stream(page)).click();
  assert.ok(items(page).includes("Route: text only, in the box"), items(page).join(" | "));
  page.find("Route: text only, in the box", stream(page)).click();
  assertFilled(page);
});

test("Run again: every other item on a text-only card fills too, with its team, and sends nothing (UI A N5, A11)", async () => {
  const page = await open(TEXT_ONLY, { status: UP });
  stream(page).querySelector(".more-btn").click();
  page.find("Run again as…", stream(page)).click();
  page.find("Collab: in the box", stream(page)).click();
  await page.settle();
  assert.deepEqual(runs(page), []);
  assert.equal(page.state.team, "collab");
  assert.equal(page.state.noFiles, false);
  assert.equal(page.state.text, TEXT_ONLY.text);
  assert.equal(page.el("textonly-pill").hidden, true);
});

test("Run again: a card that isn't text only has no fill; a team's Route item sends at once", async () => {
  const page = await open({ ...TEXT_ONLY, mode: "relay", preset: "collab", text_only: false, save_spec: null }, { status: UP });
  stream(page).querySelector(".more-btn").click();
  page.find("Run again as…", stream(page)).click();
  assert.ok(!items(page).includes("Route: text only, in the box"));
  page.find("Route: a new task", stream(page)).click();
  await page.settle();
  assert.equal(runs(page).length, 1);
  assert.equal(page.state.text || "", "");
});

// ---- 2.4: Draft it's fill ----

test("Create and draft the spec fills the box with the Text only pill and sends nothing more", async () => {
  const name = "new-idea";
  const text = "Draft SPEC.md for this project.";
  const chip = { kind: "draft", fill: { team: "route", text, project: name, no_files: true } };
  const projects = [...STATUS.projects, { ...STATUS.projects[0], name }];
  const page = await loadPage({ answers: { "/api/project-spec": { api_version: 1, spec: { draft: chip } }, "/api/status": { ...STATUS, projects },
    "/api/log": { tasks: [] }, "/api/runs": { runs: [{ id: "run-1", running: false, exit: 0, envelope: { exit: 0 } }] } } });
  Object.assign(page.state, { status: STATUS, tasks: [], np: { raw: name, notes: "My idea.", mode: "idea", check: { name, would: "create", folder: `~/Projects/${name}`, handoff: null }, error: null, waited: false, seq: 0, commandSeq: 0, running: false } });
  const done = page.createProject();  // it waits on the page's own timers, which settle() runs
  await page.settle();
  await done;
  await page.settle();
  assert.equal(page.state.project, name);
  assert.equal(page.state.team, "route");
  assert.equal(page.state.noFiles, true);
  assert.equal(page.el("prompt").value, text);
  assert.equal(page.el("textonly-pill").hidden, false);
  assert.deepEqual(runs(page).map((p) => p.body.action), ["project_new"], "only the create: the fill sends nothing");
});

// ---- 2.5: the questions card ----

const ids = {
  box: (k) => `question-other-${ASKING.task_id}-${k}`,
  other: (k) => `question-other-chip-${ASKING.task_id}-${k}`,
  option: (k, letter) => `question-${ASKING.task_id}-${k}-${letter}`,
  send: `send-answers-${ASKING.task_id}`,
};
const typeIn = (page, k, value) => { const box = page.el(ids.box(k)); box.value = value; box.fire("input"); };

test("the questions card: Other… is the last chip in each row, and no box shows until it's clicked", async () => {
  const page = await open(ASKING);
  for (const row of stream(page).querySelectorAll(".question")) {
    const chips = row.querySelector(".skills").children;
    assert.equal(chips[chips.length - 1].textContent, "Other…");
  }
  assert.equal(page.el(ids.box(1)), null);
  page.el(ids.other(1)).click();
  assert.ok(page.el(ids.box(1)));
  assert.equal(page.doc.activeElement, page.el(ids.box(1)));
  assert.equal(page.el(ids.box(1)).getAttribute("type"), "text");
  assert.equal(page.el(ids.box(2)), null);
});

test("the questions card: Esc closes the box, leaves the question unanswered and puts the focus back", async () => {
  const page = await open(ASKING);
  page.state.text = "typed in the composer";
  page.el(ids.option(1, "A")).click();
  page.el(ids.other(1)).click();
  typeIn(page, 1, "my own words");
  page.key("Escape");
  assert.equal(page.el(ids.box(1)), null);
  assert.equal(page.doc.activeElement, page.el(ids.other(1)));
  assert.equal(page.el(ids.option(1, "A")).getAttribute("aria-pressed"), "false");
  assert.equal(page.state.text, "typed in the composer", "Esc went to the box, not the composer");
  page.el(ids.option(2, "A")).click();
  assert.equal(page.el(ids.send).disabled, true, "question 1 is unanswered");
});

test("the questions card: clearing the box closes it and leaves the question unanswered", async () => {
  const page = await open(ASKING);
  page.el(ids.option(2, "A")).click();
  page.el(ids.other(1)).click();
  typeIn(page, 1, "x");
  assert.equal(page.el(ids.send).disabled, false);
  typeIn(page, 1, "");
  assert.equal(page.el(ids.box(1)), null);
  assert.equal(page.el(ids.send).disabled, true);
});

test("the questions card: an open empty box isn't an answer; typing replaces a pick", async () => {
  const page = await open(ASKING);
  page.el(ids.option(2, "A")).click();
  page.el(ids.other(1)).click();
  assert.equal(page.el(ids.send).disabled, true);
  typeIn(page, 1, "   ");
  assert.equal(page.el(ids.send).disabled, true);
  typeIn(page, 1, "mine");
  assert.equal(page.el(ids.send).disabled, false);
  page.el(ids.send).click();
  await page.settle();
  assert.deepEqual(runs(page).map((p) => p.body).filter((b) => b.action === "plan_answer"),
    [{ action: "plan_answer", task_id: ASKING.task_id, picks: { 2: "A" }, others: { 1: "mine" } }]);
});

test("the questions card: Enter in the box does nothing; Enter on a button works as usual", async () => {
  const page = await open(ASKING);
  page.el(ids.option(1, "A")).click();
  page.el(ids.option(2, "A")).click();
  page.el(ids.other(1)).click();
  typeIn(page, 1, "mine");
  const enter = page.key("Enter");
  assert.equal(enter.defaultPrevented, true);
  await page.settle();
  assert.deepEqual(runs(page), [], "Enter in the box never sends the card");
  assert.ok(page.el(ids.box(1)), "and leaves the box open");
  const send = page.el(ids.send);
  send.focus();
  assert.equal(page.key("Enter").defaultPrevented, false, "the browser's own Enter on a button is left alone");
  send.click();
  await page.settle();
  assert.equal(runs(page).length, 1);
});

test("the questions card: read-first, one primary button, the guess marked and never pre-picked, best guess the quiet second", async () => {
  const page = await open(ASKING);
  const card = stream(page).querySelector(".questions-card");
  assert.ok(card.classList.contains("plan-card"), "the plan card's frame (D16)");
  assert.equal(card.querySelectorAll(".btn-primary").length, 1);
  const foot = card.querySelector(".offer-row").children.filter((n) => n.tag === "button").map((n) => n.textContent);
  assert.deepEqual(foot.slice(0, 2), ["Send answers", "Use your best guess"]);
  assert.ok(page.el(`best-guess-${ASKING.task_id}`).classList.contains("btn-quiet"));
  assert.match(page.el(ids.option(1, "B")).textContent, /guess/);
  assert.equal(page.el(ids.option(1, "B")).getAttribute("aria-pressed"), "false");
});

// ---- 2.6: the main action ----

test("cardMainAction: Save as SPEC.md on a text-only card with save_spec, from the JSON's offer", () => {
  assert.deepEqual(cardMainAction(TEXT_ONLY), { key: "save_spec", label: "Save as SPEC.md", from: "spec",
    request: { action: "project_save", name: PROJECT, task_id: TEXT_ONLY.task_id, path: "SPEC.md" } });
  assert.equal(cardMainAction({ ...TEXT_ONLY, save_spec: null }), null);
  assert.deepEqual(cardMenuItems({ ...TEXT_ONLY, card_actions: [] }).map((i) => i.key), ["again"]);
});

test("cardMainAction: Send answers on a card waiting on answers, its request only once every question is answered", () => {
  const off = cardMainAction(ASKING);
  assert.deepEqual([off.key, off.label, off.from, off.request, off.off], ["send_answers", "Send answers", "questions", null, "2 questions still to answer"]);
  const on = cardMainAction(ASKING, null, [], { questions: { picks: { 1: "A", 2: "B" } } });
  assert.deepEqual(on.request, questionsCardView(ASKING, { picks: { 1: "A", 2: "B" } }).send);
  assert.equal(on.off, null);
  assert.equal(cardMainAction({ ...ASKING, questions: { ...ASKING.questions, waiting: false, planning: true } }), null);
});

test("Save as SPEC.md draws once and calls the save", async () => {
  const page = await open(TEXT_ONLY, { answers: { "/api/runs": { runs: [{ id: "run-1", running: false, exit: 0, envelope: { exit: 0 } }] }, "/api/status": STATUS, "/api/log": { tasks: [TEXT_ONLY] } } });
  const found = page.buttons("Save as SPEC.md", stream(page));
  assert.equal(found.length, 1);
  assert.ok(found[0].classList.contains("btn-primary"));
  found[0].click();
  await page.settle();
  assert.deepEqual(runs(page).map((r) => r.body), [{ action: "project_save", name: PROJECT, task_id: TEXT_ONLY.task_id, path: "SPEC.md" }]);
});

test("saveSpecRow is gone, so Save as SPEC.md can't draw twice", () => {
  assert.doesNotMatch(readFileSync(new URL("../../static/app.js", import.meta.url), "utf8"), /saveSpecRow/);
});

test("Send answers draws once; Land draws once and no Save as SPEC.md beside it", async () => {
  const page = await open(ASKING);
  assert.equal(page.buttons("Send answers", stream(page)).length, 1);
  const land = await open(DISCARD);
  assert.equal(land.buttons("Land", stream(land)).length, 1);
  assert.equal(land.buttons("Save as SPEC.md", stream(land)).length, 0);
});

// ---- 2.7: Esc on an open inline confirm ----

async function discardAsked() {
  const page = await open(DISCARD);
  const opener = page.el(`act-${DISCARD.task_id}-discard`);
  opener.focus();
  opener.click();
  await page.settle();
  return page;
}

test("Enter on Discard focuses Keep it", async () => {
  const page = await discardAsked();
  assert.equal(page.doc.activeElement.id, `keep-${DISCARD.task_id}`);
});

test("Esc on an open inline confirm closes it as Keep it, focus back on the opener, nothing runs", async () => {
  const page = await discardAsked();
  page.state.text = "typed in the composer";
  page.key("Escape");
  assert.equal(page.state.confirm, null);
  assert.equal(stream(page).querySelector(".confirm"), null);
  assert.equal(page.doc.activeElement.id, `act-${DISCARD.task_id}-discard`);
  assert.equal(page.state.text, "typed in the composer", "Esc stopped at the confirm");
  await page.settle();
  assert.deepEqual(runs(page), []);
});

test("Esc on an open Auto sheet still closes it as Keep it off", async () => {
  const name = PROJECT;
  const status = { ...STATUS, projects: STATUS.projects.map((p) => (p.name === name ? { ...p, auto: { state: "off", switch: "off", why: null } } : p)) };
  const page = await loadPage({ answers: { "/api/auto-check": { exit: 0, words: "Auto runs step 1.", budget: 9, first_stop: null } } });
  Object.assign(page.state, { status, project: name, tasks: [] });
  page.renderStream();
  await page.flipAuto(name);
  assert.equal(page.el("sheet").hidden, false);
  page.key("Escape");
  assert.equal(page.el("sheet").hidden, true);
  assert.equal(page.state.autoAsk, null);
  assert.deepEqual(runs(page), []);
});

test("An open Other box takes Esc before an open confirm", async () => {
  const page = await open(ASKING);
  page.el(`questions-cancel-${ASKING.task_id}`).click();
  await page.settle();
  assert.ok(page.state.confirm);
  page.el(ids.other(1)).click();
  page.key("Escape");
  assert.equal(page.el(ids.box(1)), null);
  assert.ok(page.state.confirm, "the first Esc went to the box");
  page.key("Escape");
  assert.equal(page.state.confirm, null);
  await page.settle();
  assert.deepEqual(runs(page), []);
});
