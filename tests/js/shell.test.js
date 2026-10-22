// Build brief 23, B: the page's shell, top strip and composer, as pure functions of the JSON (static/app.js).
// Fixtures are the demo's documents (scripts/make_demo.py): what the real serializers print.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  agentView, chipViews, contextFor, isOpenTask, jevBox, jevView, memoryView, newChatName, parseComposer,
  placeholderFor, pollInterval, refusalView, sendRequest, shortcutFor, shortNumber, slotViews, teamLabel,
} from "../../static/app.js";

const demo = (name) => JSON.parse(readFileSync(new URL(`../../demo/${name}`, import.meta.url), "utf8"));
const STATUS = demo("status.json");
const TASKS = demo("log.json").tasks;
const agent = (name) => STATUS.agents.find((a) => a.name === name);
const base = { team: "route", text: "what is 6 times 7", chat: "brief23", project: null, quick: false, files: [], web: false, slots: {} };

// ---------- the top strip ----------

test("an online agent reads online, with its details; a text label always beside the light", () => {
  const claude = agentView(agent("claude"));
  assert.equal(claude.tone, "ok");
  assert.equal(claude.state, "online");
  assert.match(claude.detail[0], /^Code 2\.1\.306 · search on$/);
  const up = { available: true, why: null, why_code: null, online: true };  // brief 24: the router says it is available
  const cursor = agentView({ ...agent("cursor"), ...up, probe: { state: "passed" } });
  assert.match(cursor.detail[0], /^grok-4\.7-high · \d+ calls this week$/);
  const grok = agentView({ ...agent("grok"), ...up, configured: true, live: true });
  assert.match(grok.detail[0], /calls this week$/);
});

test("signed out, not set up and a failed safety check each read in words", () => {
  // brief 24 (decision 15): the light and word from `why_code`, the detail the router's own `why`
  const chatgpt = agentView(agent("chatgpt"));
  assert.deepEqual([chatgpt.tone, chatgpt.state, chatgpt.detail[0]], ["bad", "signed out", "ChatGPT is signed out (codex login)"]);
  const grok = agentView(agent("grok"));
  assert.deepEqual([grok.tone, grok.state], ["muted", "not set up"]);
  assert.match(grok.detail[0], /^Grok Bot isn't set up: /);
  const cursor = agentView(agent("cursor"));
  assert.deepEqual([cursor.tone, cursor.state, cursor.detail[0]],
    ["bad", "off", "Cursor is off: its safety check failed on agent 2026.10.19-6bbf2c4"]);
  const off = agentView({ ...agent("claude"), available: false, why: "Claude is off: not live in config/agents.json", why_code: "not_live" });
  assert.deepEqual([off.tone, off.state], ["muted", "off"]);
});

test("a Cursor model that is not a pinned Grok model is red with the reason", () => {
  const view = agentView({ ...agent("cursor"), probe: { state: "passed" }, model: "auto" });
  assert.deepEqual([view.tone, view.state], ["bad", "not pinned"]);
  assert.match(view.detail[0], /auto is not a pinned Grok model/);
});

test("an agent working on an open task says which", () => {
  const task = { n: 9, status: "sent", outcome: null, working: { agent: "claude", doing: "stage 2 of 4 (build)" } };
  const view = agentView(agent("claude"), [task]);
  assert.deepEqual([view.tone, view.state, view.detail[0]], ["info", "on #9", "stage 2 of 4 (build)"]);
});

test("a two-agent status shows two agents and every light null reads not checked", () => {
  const two = STATUS.agents.slice(0, 2);
  assert.equal(two.map((a) => agentView(a)).length, 2);
  const view = agentView({ name: "claude", live: true, configured: true, online: null, reason: null });
  assert.equal(view.state, "not checked");
});

test("the Jev meter counts tokens against the cap, and memory says what it is doing", () => {
  assert.deepEqual(jevView(STATUS.jev).text, `${shortNumber(STATUS.jev.tokens_month)} of 1M`);
  assert.equal(shortNumber(62085), "62k");
  assert.equal(shortNumber(1_000_000), "1M");
  assert.equal(memoryView(STATUS.memory).state, "starting");
  assert.equal(memoryView({ setting: "off", online: false }).state, "off");
  assert.match(memoryView({ setting: "auto", online: true, documents: 14 }).detail, /^14 documents · starts itself$/);
});

// ---------- the chips and slots ----------

test("the chips are Route plus the presets from status, in order, nothing else; the first six get ⌥ keys", () => {
  const chips = chipViews(STATUS, "route");
  assert.deepEqual(chips.map((c) => c.key), ["route", ...STATUS.presets.map((p) => p.name)]);
  assert.equal(chips[0].checked, true);
  assert.deepEqual(chips.map((c) => c.shortcut), ["⌥1", "⌥2", "⌥3", "⌥4", "⌥5", "⌥6"]);
  assert.equal(chips[1].label, "Research-build");
});

test("a chip whose chain can't run now is greyed with status's reason", () => {
  // brief 24 (decision 15): a preset's `ready` and `why` from status, never worked out on the page
  const chips = chipViews(STATUS, "route");
  const vote = chips.find((c) => c.key === "vote");
  assert.equal(vote.disabled, true);
  assert.equal(vote.reason, STATUS.presets.find((p) => p.name === "vote").why);
  assert.match(vote.reason, /^vote can't run now: slot /);
  const allUp = { ...STATUS, presets: STATUS.presets.map((p) => ({ ...p, ready: true, why: null })) };
  assert.equal(chipViews(allUp).every((c) => !c.disabled), true);
});

test("the slot strip offers only the agents status allows, with the preset's own words", () => {
  // brief 24 (decision 14): `allowed` is the router's, available agents only; the demo's Cursor is off, so none of its
  // slots offers Cursor there. A status with Cursor up allows it in Versus A and B only.
  const demoVersus = STATUS.presets.find((p) => p.name === "versus");
  assert.equal(slotViews(demoVersus, {}, STATUS).slots.some((s) => s.options.some((o) => o.agent === "cursor")), false);
  const status = structuredClone(STATUS);
  const versus = status.presets.find((p) => p.name === "versus");
  for (const slot of versus.slots) slot.allowed = ["claude", "grok", "chatgpt", "cursor"];
  const view = slotViews(versus, { b: "cursor" }, status);
  assert.deepEqual(view.slots.map((s) => [s.name, s.label, s.value]), [["a", "A builds, reviews B", "claude"], ["b", "B builds, reviews A", "cursor"]]);
  assert.deepEqual(view.slots[1].options.map((o) => o.agent), versus.slots[1].allowed);
  assert.equal(view.note, "Cursor may fill Versus A or B only");
  const rb = status.presets.find((p) => p.name === "research-build");
  assert.equal(slotViews(rb, {}, status).slots.some((s) => s.options.some((o) => o.agent === "cursor")), false);
});

// ---------- the composer ----------

test("a slash command is stripped only when it is the page's and followed by a space or the end", () => {
  const names = STATUS.presets.map((p) => p.name);
  assert.deepEqual(parseComposer("/versus write is_leap", names).slash, { kind: "team", value: "versus" });
  assert.equal(parseComposer("/versus write is_leap", names).text, "write is_leap");
  assert.equal(parseComposer("/versus", names).slash, null);
  assert.deepEqual(parseComposer("/versus", names, { atEnd: true }).slash, { kind: "team", value: "versus" });
  assert.equal(parseComposer("/usr/bin is a folder", names).slash, null);
  assert.equal(parseComposer("/versusx hi", names).slash, null);
  assert.equal(parseComposer("/unknown word", names).text, "/unknown word");
  assert.deepEqual(parseComposer("/chat tray what next", names).slash, { kind: "chat", value: "tray" });
  assert.equal(parseComposer("/chat tray what next", names).text, "what next");
  assert.deepEqual(parseComposer("/quick hi", names).slash, { kind: "quick", value: null });
});

test("a /chat or /project name is taken only once it is typed out (a space after it, or Send)", () => {
  // typed letter by letter: nothing is taken while the name is still being typed, so the box keeps it
  for (const partial of ["/chat ", "/chat b", "/chat brief23", "/project garden-si"]) {
    assert.deepEqual([parseComposer(partial, []).slash, parseComposer(partial, []).text], [null, partial], partial);
  }
  assert.deepEqual(parseComposer("/chat brief23 ", []), { slash: { kind: "chat", value: "brief23" }, text: "", override: null });
  assert.deepEqual(parseComposer("/chat brief23", [], { atEnd: true }).slash, { kind: "chat", value: "brief23" });
  assert.deepEqual(parseComposer("/project garden-site what next", []).slash, { kind: "project", value: "garden-site" });
  assert.deepEqual(parseComposer("/chat", [], { atEnd: true }).slash, { kind: "chat", value: null });  // Send with no name: dropped
});

test("@agent at the start is noticed as the override and the text is sent as typed", () => {
  const parsed = parseComposer("@claude hi", []);
  assert.deepEqual([parsed.override, parsed.text], ["claude", "@claude hi"]);
  assert.equal(parseComposer("@muse hi", []).override, null);
  assert.equal(parseComposer("email @claude later", []).override, null);
});

test("the open chat adds --chat, a project --project, a quick task neither; files and web on Route only", () => {
  assert.deepEqual(sendRequest(base, STATUS), { action: "send", team: "route", text: "what is 6 times 7", chat: "brief23" });
  assert.deepEqual(sendRequest({ ...base, quick: true }, STATUS), { action: "send", team: "route", text: "what is 6 times 7" });
  assert.equal(sendRequest({ ...base, project: "garden-site" }, STATUS).project, "garden-site");
  assert.equal(sendRequest({ ...base, project: "garden-site" }, STATUS).chat, undefined);
  const withFile = sendRequest({ ...base, files: [{ path: "/drop/a.png", name: "a.png" }], web: true }, STATUS);
  assert.deepEqual([withFile.files, withFile.web], [["/drop/a.png"], true]);
  const team = sendRequest({ ...base, team: "versus", files: [{ path: "/x" }], web: true, slots: { b: "cursor", a: "claude" } }, STATUS);
  assert.deepEqual(team, { action: "send", team: "versus", text: "what is 6 times 7", chat: "brief23", slots: { b: "cursor" } });
});

test("a chip that takes no --project greys the project selector and the chat rides instead", () => {
  const ctx = contextFor({ ...base, team: "versus", project: "garden-site" }, STATUS);
  assert.deepEqual([ctx.kind, ctx.projectGreyed], ["chat", true]);
  assert.deepEqual(contextFor({ ...base, team: "redteam", project: "garden-site" }, STATUS).kind, "project");
});

test("the placeholder names the chain; the Jev box reads not asked on a team and fills on Route", () => {
  assert.match(placeholderFor("versus", STATUS), /^New task for Versus: /);
  assert.deepEqual(jevBox({ team: "versus" }), { mode: "not_asked", text: "not asked: Versus names its own agents" });
  const task = TASKS.find((t) => t.jev && t.jev.status === "ok");
  const box = jevBox({ team: "route", task, floor: STATUS.jev.floor });
  assert.equal(box.mode, "label");
  assert.equal(box.floor, 0.8);
  const under = TASKS.find((t) => t.waiting_on === "needs_label" && t.jev.status === "below_floor");
  assert.equal(jevBox({ team: "route", task: under, floor: 0.8 }).under, true);
  assert.equal(jevBox({ team: "route", sending: true }).mode, "waiting");
  assert.match(jevBox({ team: "route", floor: 0.8 }).text, /0\.80/);
});

test("the poll is 5 s while a task is open or a send is pending, else 60 s", () => {
  assert.equal(pollInterval(TASKS, 0), 5000);
  const ended = TASKS.filter((t) => !isOpenTask(t));
  assert.equal(pollInterval(ended, 0), 60000);
  assert.equal(pollInterval(ended, 1), 5000);
  assert.equal(pollInterval([], 0), 60000);
});

test("shortcuts: ⌥1–⌥6 the chips, Enter sends, Shift+Enter does not, an IME never sends, ? outside a field", () => {
  assert.deepEqual(shortcutFor({ altKey: true, code: "Digit4", key: "¢" }), { action: "chip", index: 3 });
  // brief 24 (decision 17): in a text field ⌥-digits type (brackets on German or French layouts), never a chip
  assert.equal(shortcutFor({ altKey: true, code: "Digit5", key: "[" }, { inText: true, inPrompt: true }), null);
  assert.equal(shortcutFor({ altKey: true, metaKey: true, code: "Digit4" }), null);
  assert.equal(shortcutFor({ altKey: true, code: "Digit7" }), null);
  assert.deepEqual(shortcutFor({ key: "Enter" }, { inPrompt: true }), { action: "send" });
  assert.deepEqual(shortcutFor({ key: "Enter", metaKey: true }, { inPrompt: true }), { action: "send" });
  assert.equal(shortcutFor({ key: "Enter", shiftKey: true }, { inPrompt: true }), null);
  assert.equal(shortcutFor({ key: "Enter", isComposing: true }, { inPrompt: true }), null);
  assert.equal(shortcutFor({ key: "Enter", keyCode: 229 }, { inPrompt: true }), null);
  assert.equal(shortcutFor({ key: "Enter" }, { inPrompt: false }), null);
  assert.deepEqual(shortcutFor({ key: "?" }, { inText: false }), { action: "shortcuts" });
  assert.equal(shortcutFor({ key: "?" }, { inText: true }), null);
  assert.deepEqual(shortcutFor({ key: "Escape" }), { action: "escape" });
});

test("a refused send shows the router's words and its exit code", () => {
  const run = demo("runs.json").runs.find((r) => r.exit === 2 && r.envelope.reason_code === "override_refused");
  const view = refusalView(run);
  assert.equal(view.title, "The router refused this send");
  assert.match(view.message, /override prefix on a relay task is refused/);
  assert.deepEqual([view.exit, view.code], [2, "override_refused"]);
  const killed = refusalView({ exit: -9, envelope: null, stderr: "", display: "sr route" });
  assert.equal(killed.title, "This send ended without a task");
});

test("a new chat is named chat-YYYYMMDD-hhmm; a team's label is capitalised", () => {
  assert.equal(newChatName(new Date(2026, 9, 21, 9, 5)), "chat-20261021-0905");
  assert.deepEqual([teamLabel("route"), teamLabel("research-build"), teamLabel(null)], ["Route", "Research-build", "Route"]);
});

// ---------- what a task card says about itself (the old table's columns, now on the card) ----------
import { stateWords, taskSummary } from "../../static/app.js";

const byState = (pred) => TASKS.find(pred);

test("a relay task names its preset, and a stopped chain its stage", () => {
  const rb = byState((t) => t.preset === "research-build");
  assert.equal(taskSummary(rb).team, "Research-build");
  assert.equal(taskSummary({ ...rb, failed_stage: 2, outcome: "stopped" }).failed, "stopped at stage 2");
});

test("a split says split and a piece names itself as one, with its parent", () => {
  const split = byState((t) => t.mode === "split");
  const piece = byState((t) => t.mode === "piece");
  assert.equal(taskSummary(split).team, "Split");
  assert.deepEqual([taskSummary(piece).team, taskSummary(piece).piece, taskSummary(piece).parent],
    ["Piece of a split", true, piece.parent]);
});

test("the state says what a task waits on, and the check how it went, with the note", () => {
  assert.equal(stateWords(byState((t) => t.waiting_on === "pick")), "waiting for your pick");
  assert.equal(stateWords(byState((t) => t.waiting_on === "vote_pick")), "a tie: waiting for your pick");
  assert.equal(stateWords(byState((t) => t.waiting_on === "needs_label")), "waiting for your label");
  assert.equal(stateWords(byState((t) => t.outcome === "failed_check")), "failed its check twice");
  assert.equal(stateWords(byState((t) => t.outcome === "process_ended")), "stopped: process ended");
  const fixed = taskSummary(byState((t) => t.outcome === "fixed"));
  assert.deepEqual([fixed.state, fixed.tone, fixed.check], ["fixed", "ok", "fixed"]);
  const failed = taskSummary(byState((t) => t.outcome === "failed_check"));
  assert.deepEqual([failed.tone, failed.note], ["bad", "not passed after one fix round"]);
  assert.equal(taskSummary(byState((t) => t.check_note === "overdue: grok, 12 min")).note, "overdue: grok, 12 min");
});

import { shellQuote } from "../../static/app.js";

test("the demo's command line quotes like Python's shlex.quote", () => {
  assert.equal(shellQuote("brief23"), "brief23");
  assert.equal(shellQuote("what costs $5"), "'what costs $5'");
  assert.equal(shellQuote("it's"), `'it'"'"'s'`);
  assert.equal(shellQuote(""), "''");
});
