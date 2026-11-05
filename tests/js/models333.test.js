// Build brief 33.3 (decisions 6, 11 and 12): the page's pure parts for models. Team → Models… and /model, the sheet (per
// agent the team uses, Defaults first with what it means now, Fable greyed with why), the pills, the send's `models`, a
// chip and Esc dropping the choice, Setup's Models row (the defaults read only, the selects, the Fable switch), Details'
// model lines, the strip's Opus and Fable counts, and the demo's command previews. The router works every model out; these
// tests feed its JSON.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { agentView, callModelLines, claudeCallsThisWeek, defaultsWords, demoCommand, fableOffWords, fableSwitchView, fillFromChip,
  firstRunItems, FABLE_OFF_WHY, modelOptions, modelPillViews, modelShort, modelsMenuItem, modelsSetupRow, modelsSetupSelects,
  modelsSheetView, PAGE_SLASHES, parseComposer, pruneModels, runAgainRequest, sendRequest, setupRows, SETUP_PIECES, teamModelsNow } from "../../static/app.js";

const INDEX = readFileSync(new URL("../../static/index.html", import.meta.url), "utf8");

const STATUS = JSON.parse(readFileSync(new URL("../../demo/status.json", import.meta.url), "utf8"));
const COPIES = JSON.parse(readFileSync(new URL("../../tests/fixtures/page_copies.json", import.meta.url), "utf8"));
const HAIKU = "claude-haiku-5-5", SONNET = "claude-sonnet-5-5", OPUS = "claude-opus-5-5", FABLE = "claude-fable-5-1";
const entry = (agent, model, name, extra = {}) => ({ agent, model, name, layer: "agent", key: null, effort: null, note: null, ...extra });
const MODELS = {
  agents: {
    claude: { default: SONNET, name: "Sonnet 5.5", file: "config/models.json", allowed: [HAIKU, SONNET, OPUS, FABLE],
      aliases: { haiku: HAIKU, sonnet: SONNET, opus: OPUS, fable: FABLE },
      names: { [HAIKU]: "Haiku 5.5", [SONNET]: "Sonnet 5.5", [OPUS]: "Opus 5.5", [FABLE]: "Fable 5.1" }, gated: [FABLE] },
    chatgpt: { default: "gpt-6.1-sol", name: "GPT-6.1 Sol", file: "config/agents.json", allowed: ["gpt-6.1-sol", "gpt-6-astra"],
      aliases: {}, names: { "gpt-6.1-sol": "GPT-6.1 Sol", "gpt-6-astra": "GPT-6 Astra" }, gated: [] },
    cursor: { default: "grok-4.7-high", name: "grok-4.7-high", file: "config/agents.json", allowed: ["grok-4.7-high", "grok-4.7-fast"],
      aliases: {}, names: {}, gated: [] },
  },
  fable: { on: false, changed_at: null, off_by: null, words: "Fable 5.1 can charge usage credits once you've used half your weekly limit on it, and the router's Claude calls pay them without asking. Turn this on only if usage credits are off on your account.", fallback: OPUS, fallback_name: "Opus 5.5" },
  layers: [{ layer: "skill", key: "code", agent: "claude", model: OPUS, name: "Opus 5.5", effort: null, file: "config/models.local.json" }],
  problems: [], files: { tracked: "config/models.json", local: "config/models.local.json", local_present: true },
  claude: { opus_calls_this_week: 3, fable_calls_this_week: 0 },
  now: {
    skills: { writing: { do: entry("claude", SONNET, "Sonnet 5.5"), check: entry("chatgpt", "gpt-6.1-sol", "GPT-6.1 Sol") },
      code: { do: entry("claude", OPUS, "Opus 5.5", { layer: "skill", key: "code" }), check: entry("chatgpt", "gpt-6.1-sol", "GPT-6.1 Sol") },
      planning: { do: entry("claude", SONNET, "Sonnet 5.5"), check: entry("chatgpt", "gpt-6.1-sol", "GPT-6.1 Sol") },
      recall: { do: entry("claude", SONNET, "Sonnet 5.5"), check: entry("chatgpt", "gpt-6.1-sol", "GPT-6.1 Sol") },
      web_research: { do: entry("claude", SONNET, "Sonnet 5.5"), check: entry("chatgpt", "gpt-6.1-sol", "GPT-6.1 Sol") },
      quick_answer: { do: entry("claude", SONNET, "Sonnet 5.5") },
      make_media: { do: entry("grok", null, null) } },
    project_skills: { writing: { do: entry("claude", OPUS, "Opus 5.5", { layer: "file", key: "file.build" }), check: entry("chatgpt", "gpt-6.1-sol", "GPT-6.1 Sol") },
      code: { do: entry("claude", OPUS, "Opus 5.5", { layer: "file", key: "file.build" }), check: entry("chatgpt", "gpt-6.1-sol", "GPT-6.1 Sol") },
      recall: { do: entry("claude", SONNET, "Sonnet 5.5"), check: entry("chatgpt", "gpt-6.1-sol", "GPT-6.1 Sol") },
      quick_answer: { do: entry("claude", SONNET, "Sonnet 5.5", { layer: "skill", key: "quick_answer" }) } },
    teams: {
      redteam: [entry("claude", SONNET, "Sonnet 5.5", { stage: 1, role: "build" }), entry("chatgpt", "gpt-6.1-sol", "GPT-6.1 Sol", { stage: 2, role: "attack" }),
        entry("cursor", "grok-4.7-high", "grok-4.7-high", { stage: 3, role: "attack" }), entry("claude", SONNET, "Sonnet 5.5", { stage: 4, role: "revise" }),
        entry("chatgpt", "gpt-6.1-sol", "GPT-6.1 Sol", { stage: null, role: "check" })],
      vote: [entry("claude", SONNET, "Sonnet 5.5", { stage: 1, role: "vote" }), entry("chatgpt", "gpt-6.1-sol", "GPT-6.1 Sol", { stage: 2, role: "vote" }),
        entry("grok", null, null, { stage: 3, role: "vote" })],
      plan: [entry("claude", OPUS, "Opus 5.5", { stage: 1, role: "plan", layer: "role", key: "plan.plan", note: "Fable is off: Opus 5.5 instead" }),
        entry("chatgpt", "gpt-6.1-sol", "GPT-6.1 Sol", { stage: 2, role: "attack" }), entry("claude", OPUS, "Opus 5.5", { stage: 4, role: "revise", note: "Fable is off: Opus 5.5 instead" }),
        entry("chatgpt", "gpt-6.1-sol", "GPT-6.1 Sol", { stage: null, role: "check" })],
      split: [entry("claude", SONNET, "Sonnet 5.5", { stage: 1, role: "plan" }), entry("claude", SONNET, "Sonnet 5.5", { stage: 2, role: "integrate" }),
        entry("chatgpt", "gpt-6.1-sol", "GPT-6.1 Sol", { stage: null, role: "check" })],
    },
    file: { build: entry("claude", OPUS, "Opus 5.5", { layer: "file", key: "file.build" }), revise: entry("claude", OPUS, "Opus 5.5", { layer: "file", key: "file.revise" }),
      execute: entry("claude", OPUS, "Opus 5.5"), fix: entry("claude", OPUS, "Opus 5.5"), integrate: entry("claude", OPUS, "Opus 5.5") },
  },
  setup: { skills: [{ key: "code", agent: "claude", model: OPUS, effort: null, name: "Opus 5.5" }, { key: "writing", agent: "claude", model: null, effort: null, name: null },
    { key: "web_research", agent: "chatgpt", model: null, effort: null, name: null }],
    roles: [{ team: "route", role: "build", agent: "claude", model: null, effort: null, name: null },
      { team: "redteam", role: "attack", agent: "chatgpt", model: null, effort: null, name: null },
      { team: "file", role: "build", agent: "claude", model: OPUS, effort: null, name: "Opus 5.5" }],
    stages: [{ team: "redteam", stage: 2, role: "attack", agent: "chatgpt", model: null, effort: null, name: null },
      { team: "redteam", stage: 3, role: "attack", agent: "cursor", model: "grok-4.7-fast", effort: null, name: "grok-4.7-fast" }] },
};
const WITH = { ...STATUS, models: MODELS, presets: [...STATUS.presets], skills: STATUS.skills };

test("Team → Models… is the menu's last item, greyed until status carries models, and /model is a slash", () => {
  assert.deepEqual(modelsMenuItem(WITH), { key: "models", label: "Models…", disabled: false, reason: null,
    title: "Pick the model each agent uses on this task; the defaults apply where you pick none" });
  assert.equal(modelsMenuItem({ agents: [] }).disabled, true);
  assert.equal(modelsMenuItem(null).reason, "the router's status has no models yet");
  assert.ok(PAGE_SLASHES.includes("model"));
  assert.deepEqual(parseComposer("/model ", []), { slash: { kind: "model", value: null }, text: "", override: null });
  assert.deepEqual(parseComposer("/model", [], { atEnd: true }).slash, { kind: "model", value: null });
  assert.equal(parseComposer("/models ", []).slash, null);  // not a slash: the box keeps it
});

test("the sheet on Route lists the agents the skill table uses, Defaults first, with what Defaults means now", () => {
  const view = modelsSheetView(WITH, "route", {});
  assert.equal(view.title, "Models · Route");
  assert.deepEqual(view.agents.map((a) => a.agent), ["claude", "chatgpt"]);  // Grok Bot's service picks: no row
  const claude = view.agents[0];
  assert.equal(claude.defaults, "Sonnet 5.5 (most skills) · Opus 5.5 (code)");  // the biggest group of several reads "most skills"
  assert.deepEqual(claude.options.map((o) => [o.value, o.label, o.disabled]), [["", "Defaults", false], [HAIKU, "Haiku 5.5", false],
    [SONNET, "Sonnet 5.5", false], [OPUS, "Opus 5.5", false], [FABLE, "Fable 5.1 (off)", true]]);
  assert.equal(claude.options[4].reason, fableOffWords(MODELS));  // decision 6's own words, then where the switch is
  assert.equal(fableOffWords(MODELS), `${MODELS.fable.words} Fable is off: turn it on in Settings → Models.`);
  assert.equal(fableOffWords(null), FABLE_OFF_WHY);
  assert.equal(view.agents[1].defaults, "GPT-6.1 Sol (most skills)");
  assert.equal(view.fableOff, true);
  assert.match(view.note, /known once Jev labels the task/);
  // Fable on: nothing greyed
  const on = modelsSheetView({ ...WITH, models: { ...MODELS, fable: { ...MODELS.fable, on: true } } }, "route", {});
  assert.deepEqual(on.agents[0].options.map((o) => o.disabled), [false, false, false, false, false]);
  assert.equal(on.fableOff, false);
});

test("the sheet on a team lists its stages' agents with each role, and on a project Claude's build roles read the file defaults", () => {
  const view = modelsSheetView(WITH, "redteam", { cursor: "grok-4.7-fast" });
  assert.deepEqual(view.agents.map((a) => [a.agent, a.defaults, a.chosen]), [
    ["claude", "Sonnet 5.5 (build, revise)", ""], ["chatgpt", "GPT-6.1 Sol (attack, check)", ""], ["cursor", "grok-4.7-high (attack)", "grok-4.7-fast"]]);
  assert.equal(view.agents[2].options.find((o) => o.value === "grok-4.7-fast").selected, true);
  const project = modelsSheetView(WITH, "redteam", {}, { project: "garden" });
  assert.equal(project.agents[0].defaults, "Opus 5.5 (build, revise)");
  // decision 2 on Route with a project: status's project_skills (the doer builds in the copy: Opus; recall keeps Sonnet)
  const routeProject = modelsSheetView(WITH, "route", {}, { project: "garden" });
  assert.equal(routeProject.agents[0].defaults, "Opus 5.5 (writing, code) · Sonnet 5.5 (recall, quick answer)");
  const plan = modelsSheetView(WITH, "plan", {});
  assert.equal(plan.agents[0].defaults, "Opus 5.5 (plan, revise) · Fable is off: Opus 5.5 instead");
  assert.match(plan.note, /each step runs later/);
  assert.equal(modelsSheetView(WITH, "split", {}).note, "The plan and the join; each piece uses its team's defaults.");
  const vote = modelsSheetView(WITH, "vote", {});
  assert.deepEqual(vote.agents.map((a) => a.agent), ["claude", "chatgpt"]);  // Grok Bot votes with no model choice
  assert.equal(modelsSheetView({ agents: [] }, "route", {}).ready, false);
  assert.equal(modelsSheetView(WITH, "nothing", {}).why, "Nothing makes no call with a model choice.");
  assert.deepEqual(teamModelsNow(WITH, "split").map((a) => a.agent), ["claude", "chatgpt"]);
  assert.equal(defaultsWords([{ what: "a", model: "x", name: "X", note: null }, { what: "b", model: "y", name: "Y", note: null }]), "X (a) · Y (b)");
});

test("a choice shows as a pill per agent, 'Claude: Haiku ×', and nothing while the defaults apply", () => {
  assert.deepEqual(modelPillViews({ claude: HAIKU, chatgpt: "gpt-6-astra" }, WITH), [
    { agent: "claude", model: HAIKU, words: "Claude: Haiku", aria: "Let Claude use its default model" },
    { agent: "chatgpt", model: "gpt-6-astra", words: "ChatGPT: GPT-6 Astra", aria: "Let ChatGPT use its default model" }]);
  assert.deepEqual(modelPillViews(null, WITH), []);
  assert.deepEqual(modelPillViews({ grok: "x", claude: "" }, WITH), []);
  assert.equal(modelShort("cursor", "grok-4.7-fast", WITH), "grok-4.7-fast");
  assert.equal(modelShort("claude", OPUS, { agents: [] }), OPUS);  // no status: the id itself
});

test("the send carries `models` on every team; a team change drops an agent the team doesn't use; a chip and Esc carry none", () => {
  const base = { team: "route", text: "x", chat: "garden", project: null, quick: false, models: { claude: HAIKU } };
  assert.deepEqual(sendRequest(base, WITH).models, { claude: HAIKU });
  assert.deepEqual(sendRequest({ ...base, team: "split", project: "p" }, WITH).models, { claude: HAIKU });
  assert.deepEqual(sendRequest({ ...base, team: "plan", project: "p" }, WITH).models, { claude: HAIKU });
  assert.deepEqual(sendRequest({ ...base, team: "redteam" }, WITH).models, { claude: HAIKU });
  assert.equal("models" in sendRequest({ ...base, models: null }, WITH), false);
  assert.equal("models" in sendRequest({ ...base, models: {} }, WITH), false);
  assert.deepEqual(pruneModels({ claude: HAIKU, cursor: "grok-4.7-fast" }, WITH, "route"), { claude: HAIKU });
  assert.deepEqual(pruneModels({ claude: HAIKU, cursor: "grok-4.7-fast" }, WITH, "redteam"), { claude: HAIKU, cursor: "grok-4.7-fast" });
  assert.equal(pruneModels({ cursor: "grok-4.7-fast" }, WITH, "vote"), null);
  assert.equal(pruneModels(null, WITH, "route"), null);
  assert.deepEqual(pruneModels({ claude: HAIKU }, { agents: [] }, "vote"), { claude: HAIKU });  // no status: kept, the router decides
  const chip = { kind: "build_from", fill: { text: "go on", team: "route", project: null, chat: "garden", from: "sr-1" } };
  const { next } = fillFromChip(chip, { text: "", team: "route", models: { claude: HAIKU } }, 7);
  assert.equal(next.models, undefined);  // the fill names no models: setBox reads none (decision 4: a chip carries none)
});

test("Setup's Models row: the defaults read only and how many of your own; an ignored default is a setup problem", () => {
  const row = modelsSetupRow(WITH);
  assert.deepEqual([row.key, row.name, row.tone, row.state], ["models", "Models", "ok", "1 of your own"]);
  assert.equal(row.detail, "Claude Sonnet 5.5 · ChatGPT GPT-6.1 Sol · Cursor grok-4.7-high · Fable off");
  assert.equal(modelsSetupRow({ ...WITH, models: { ...MODELS, layers: [] } }).state, "the agents' defaults");
  const bad = modelsSetupRow({ ...WITH, models: { ...MODELS, problems: ["config/models.local.json: skills.code.claude: claude-opus-9 isn't on claude's allowed list"] } });
  assert.deepEqual([bad.tone, bad.state], ["bad", "1 ignored"]);
  assert.match(bad.detail, /claude-opus-9 isn't on claude's allowed list/);
  assert.deepEqual(modelsSetupRow({ agents: [] }), { key: "models", name: "Models", checkedAt: null, tone: "quiet", state: "unknown", detail: "not read yet" });
  assert.equal(SETUP_PIECES.at(-1)[1], "Models");
  const rows = setupRows(WITH);
  assert.equal(rows.at(-1).key, "models");
  assert.equal(rows.at(-1).without, null);
  assert.equal(firstRunItems(WITH).some((r) => r.key === "models"), false);
  assert.equal(firstRunItems({ ...WITH, models: { ...MODELS, problems: ["x"] } }).some((r) => r.key === "models"), true);
});

test("Setup's selects: one per skill and per team, role and agent, Default first by name, the saved value selected", () => {
  const found = modelsSetupSelects(WITH);
  assert.deepEqual(found.skills.map((s) => [s.key, s.agent, s.chosen, s.label, s.selector]), [
    ["code", "claude", OPUS, "Code · Claude", { skill: "code" }], ["writing", "claude", "", "Writing · Claude", { skill: "writing" }],
    ["web_research", "chatgpt", "", "Web research · ChatGPT", { skill: "web_research" }]]);
  assert.deepEqual(found.skills[0].options.map((o) => [o.value, o.label, o.selected]).slice(0, 2),
    [["", "Default (Sonnet 5.5)", false], [HAIKU, "Haiku 5.5", false]]);
  assert.equal(found.skills[0].options.find((o) => o.value === OPUS).selected, true);
  assert.deepEqual(found.roles.map((r) => [r.label, r.selector, r.chosen]), [
    ["Route · build · Claude", { team: "route", role: "build" }, ""], ["Redteam · attack · ChatGPT", { team: "redteam", role: "attack" }, ""],
    ["File · build · Claude", { team: "file", role: "build" }, OPUS]]);
  assert.equal(found.roles[1].options[0].label, "Default (GPT-6.1 Sol)");
  assert.equal(found.skills[2].agent, "chatgpt");  // a ChatGPT-best skill gets ChatGPT's select
  assert.deepEqual(found.stages.map((r) => [r.label, r.selector, r.chosen]), [
    ["Redteam · stage 2 (attack) · ChatGPT", { team: "redteam", stage: 2 }, ""],
    ["Redteam · stage 3 (attack) · Cursor", { team: "redteam", stage: 3 }, "grok-4.7-fast"]]);
  assert.deepEqual(modelsSetupSelects({ agents: [] }), { skills: [], roles: [], stages: [] });
  // break-ui: a saved value the allowlist no longer holds still shows, greyed, so the select isn't blank
  const lost = modelOptions("claude", WITH, { chosen: "claude-opus-9" });
  assert.deepEqual(lost.at(-1), { value: "claude-opus-9", label: "claude-opus-9 (not on the list)", disabled: true, reason: "not on the allowed list", selected: true });
});

test("the Fable switch reads status's words, its state, who turned it off and the fallback; busy while its run goes", () => {
  const off = fableSwitchView(MODELS);
  assert.deepEqual([off.on, off.to, off.busy, off.disabled, off.label], [false, "on", false, false, "Off"]);
  assert.match(off.words, /^Fable 5\.1 can charge usage credits once you've used half your weekly limit/);
  assert.equal(off.offBy, null);
  assert.match(off.fallback, /runs on Opus 5\.5 and the card says so; a typed Fable is refused/);
  const credits = fableSwitchView({ ...MODELS, fable: { ...MODELS.fable, off_by: "credits: sr-20261030-010203-abcd" } });
  assert.equal(credits.offBy, "The router turned it off (credits: sr-20261030-010203-abcd).");
  const on = fableSwitchView({ ...MODELS, fable: { ...MODELS.fable, on: true } });
  assert.deepEqual([on.on, on.to, on.label, on.fallback], [true, "off", "On", null]);
  const busy = fableSwitchView(MODELS, { to: "on", started: 1 });
  assert.deepEqual([busy.on, busy.busy, busy.disabled, busy.label, busy.cmdLabel], [true, true, true, "Turning on…", "Running"]);
  assert.equal(fableSwitchView(null).disabled, true);
  assert.deepEqual(fableSwitchView(MODELS, null, { exit: 2, message: "Refused: x" }).failure, { exit: 2, message: "Refused: x" });
});

test("Details lists each call's model, asked → served, with its time limit and effort; a row without a model has no line", () => {
  const show = { calls: [
    { kind: "do", agent: "claude", model: OPUS, served: { model: OPUS, asked: OPUS }, time_limit: 1200, effort: null },
    { kind: "check", agent: "chatgpt", model: "gpt-6.1-sol", served: null, time_limit: 600, effort: "high" },
    { kind: "stage", role: "revise", agent: "claude", model: FABLE, served: { model: OPUS }, time_limit: 1200, effort: null },
    { kind: "reask", role: "attack", agent: "cursor", model: "grok-4.7-high", served: { model: "grok-4.7-high", tool_events: 0 }, time_limit: 600 },
    { kind: "do", agent: "grok", model: null, served: null },
  ] };
  assert.deepEqual(callModelLines(show), [
    "do · Claude: claude-opus-5-5 → claude-opus-5-5 · limit 1,200 s",
    "check · ChatGPT: gpt-6.1-sol → served unknown · limit 600 s · effort high",
    "revise · Claude: claude-fable-5-1 → claude-opus-5-5 · limit 1,200 s",
    "attack re-ask · Cursor: grok-4.7-high → grok-4.7-high · limit 600 s"]);
  assert.deepEqual(callModelLines(null), []);
});

test("the strip shows Opus and Fable calls this week under Claude, from status's counts; nothing without them", () => {
  assert.equal(claudeCallsThisWeek(MODELS), "3 Opus, 0 Fable calls this week");
  assert.equal(claudeCallsThisWeek({ claude: { opus_calls_this_week: 12345, fable_calls_this_week: 1 } }), "12,345 Opus, 1 Fable calls this week");
  assert.equal(claudeCallsThisWeek(null), null);
  const claude = STATUS.agents.find((a) => a.name === "claude");
  assert.deepEqual(agentView(claude, [], MODELS).detail, [`Code ${claude.version} · search on`, "3 Opus, 0 Fable calls this week"]);
  assert.equal(agentView(claude, []).detail.length, 1);  // an older status: no counts, no line
});

test("Run again as… carries no model choice, and no always-visible control is new (the composer's controls, the pills hidden)", () => {
  // decision 4: a chip and Run again as… don't carry the choice; the request is built from the task row, which has none
  const task = { task_id: "sr-1", n: 1, text: "x", project: null, from: null, models: { claude: HAIKU } };
  const { request } = runAgainRequest(task, "route", { quick: false, chat: "garden", newChat: "chat-x" }, WITH);
  assert.equal("models" in request, false);
  // decision 12: the composer's always-visible controls are the same set; the model pills start hidden
  const bar = INDEX.slice(INDEX.indexOf('class="composer-bar"'), INDEX.indexOf("</footer>"));
  const ids = [...bar.matchAll(/id="([a-z-]+)"/g)].map((m) => m[1]);
  assert.deepEqual(ids, ["attach", "skill", "web-label", "web", "quick-label", "quick", "project", "team", "context-tag", "send", "file-input", "cmdline", "cmd", "copy", "jev"]);  // main's, plus the hidden pills
  assert.match(INDEX, /id="model-pills" hidden/);  // UI A row 5 (A15): the pills have left the bar's slice, for a row above the box
});

test("the demo's command previews equal the builder's Copy for the three actions (the shared fixture)", () => {
  const ours = COPIES.filter((c) => ["models_set", "models_clear", "models_fable"].includes(c.request.action));
  assert.equal(ours.length, 3);
  for (const c of ours) assert.equal(demoCommand(c.request), c.copy);
  assert.equal(demoCommand({ action: "models_set", selector: { team: "file", role: "build" }, agent: "claude", model: OPUS }),
    "sr models set --team file --role build --agent claude --model claude-opus-5-5");
});
