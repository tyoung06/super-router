// Build brief 33.4, I (decisions 8, 9, 9b and 15): the New project sheet's From an idea mode with its cap and counter; Save as
// SPEC.md from the JSON's offer; Run again on a text-only card fills the box with the Text only pill and never sends. Fake.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { blockedOffer, draftChipOf, fillFromChip, ideaModeView, newProjectView, runAgainFill, runAgainRequest, saveSpecView, sendRequest } from "../../static/app.js";

const JS = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const CHECK = { name: "seed", would: "create", folder: "~/Projects/seed" };
const base = (check = CHECK) => newProjectView(check, { name: "seed" });

test("Blank is today's sheet, unchanged", () => {
  assert.equal(base().button, "Create project");
  assert.equal(base().canCreate, true);
});

test("From an idea needs the idea and reads Create and draft the spec", () => {
  const empty = ideaModeView(base(), { idea: "   ", check: CHECK });
  assert.equal(empty.canCreate, false);
  assert.equal(empty.label, "Your idea");
  assert.equal(empty.required, true);
  const ok = ideaModeView(base(), { idea: "A tiny converter.", check: CHECK });
  assert.equal(ok.canCreate, true);
  assert.equal(ok.button, "Create and draft the spec");
});

test("the counter reads with its cap and Create is off past it", () => {
  const at = ideaModeView(base(), { idea: "x".repeat(2000), ideaMax: 2000, check: CHECK });
  assert.equal(at.counter, "2,000 / 2,000");
  assert.equal(at.canCreate, true);
  const past = ideaModeView(base(), { idea: "x".repeat(2001), ideaMax: 2000, check: CHECK });
  assert.equal(past.canCreate, false);
  assert.equal(past.over, true);
  assert.equal(ideaModeView(base(), { idea: "x".repeat(1240), check: CHECK }).counter, "1,240 / 2,000");
});

test("a folder that exists can't start from an idea", () => {
  const check = { name: "seed", would: "register", handoff: { exists: false } };
  const view = ideaModeView(base(check), { idea: "An idea.", check });
  assert.equal(view.canCreate, false);
  assert.ok(view.notesHint.includes("From an idea needs a new name"));
});

test("Save as SPEC.md comes from the JSON's offer, never the text", () => {
  const task = { task_id: "sr-1", n: 3, project: "seed", save_spec: { path: "SPEC.md" }, text: "anything" };
  assert.deepEqual(saveSpecView(task), { label: "Save as SPEC.md", request: { action: "project_save", name: "seed", task_id: "sr-1", path: "SPEC.md" } });
  assert.equal(saveSpecView({ ...task, save_spec: null, text: "Write SPEC.md for this project" }), null);
});

test("Plan the project fills Plan with no From", () => {
  const chip = { kind: "plan_project", words: "Plan the project", later: false,
    fill: { team: "plan", project: "seed", chat: null, text: "Plan this project from SPEC.md.", from: null, idea: null, step: null } };
  const { next } = fillFromChip(chip, { text: "" }, 3);
  assert.deepEqual([next.team, next.project, next.text, next.from], ["plan", "seed", "Plan this project from SPEC.md.", null]);
});

test("Run again on a text-only card fills the box with the pill; every other card has no fill", () => {
  const task = { task_id: "sr-1", project: "seed", text: "Write it.", text_only: true };
  const fill = runAgainFill(task);
  assert.deepEqual([fill.team, fill.project, fill.text, fill.noFiles], ["route", "seed", "Write it.", true]);
  assert.equal(runAgainFill({ ...task, text_only: false }), null);
  assert.equal(sendRequest({ ...fill, files: [], slots: {} }, { projects: [{ name: "seed" }], presets: [] }).no_files, true);
});

test("a blocked draft's Run again stays text only", () => {
  const task = { task_id: "sr-1", outcome: "blocked", project: "seed", text: "Write it.", text_only: true };
  assert.equal(blockedOffer(task).noFiles, true);
  assert.equal(blockedOffer({ ...task, text_only: false }).noFiles, false);
});

test("Run again's request keeps --no-files on Route, and only on Route", () => {
  const task = { task_id: "sr-1", project: "seed", text: "Write it.", text_only: true };
  const status = { projects: [{ name: "seed" }], presets: [] };
  assert.equal(runAgainRequest(task, "route", {}, status).request.no_files, true);
  assert.equal(runAgainRequest(task, "collab", {}, status).request.no_files, undefined);
  assert.equal(runAgainRequest({ ...task, text_only: false }, "route", {}, status).request.no_files, undefined);
});

test("Draft it's chip is read from the Spec read's own shape", () => {
  const chip = { kind: "draft_spec", words: "Draft it", fill: { team: "route", project: "seed", text: "Write SPEC.md", no_files: true } };
  assert.deepEqual(draftChipOf({ api_version: 1, spec: { exists: false, draft: chip } }), chip);  // `sr project spec --json`
  assert.equal(draftChipOf({ api_version: 1, spec: { exists: true, draft: null } }), null);
  const { next } = fillFromChip(chip, { text: "" }, null);
  assert.deepEqual([next.team, next.project, next.noFiles], ["route", "seed", true]);
});

test("the sheet fills Draft it after Create and sends nothing", () => {
  const body = JS.slice(JS.indexOf("async function fillDraftIt"), JS.indexOf("function npRequest()"));
  assert.ok(body.includes("useChip(chip") && !body.includes("/api/run"));
});
