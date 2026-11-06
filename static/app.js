// Super Router's page (build brief 23). Plain JavaScript, no framework, no library, no build step.
// The page renders the JSON `sr` prints and has no routing, checking or prompt of its own: every button asks the
// server to run an `sr` command that the server builds in Python (router/page_commands.py). Task and result text come
// from outside (models, people): it is set with textContent, never parsed as HTML; markdown is drawn by a small renderer
// that escapes first. The pure functions below are exported for `node --test` (tests/js/); the DOM wiring at the end
// runs only in a browser.

// ---------- words and small pure helpers ----------

export const AGENT_NAMES = { claude: "Claude", chatgpt: "ChatGPT", grok: "Grok Bot", cursor: "Cursor", muse: "Muse" };
export const PAGE_SLASHES = ["route", "split", "plan", "quick", "project", "chat", "file", "web",
  "model"];  // brief 29: /split; 33.1: /plan; 33.3: /model opens the Models sheet
export const OVERRIDES = ["claude", "chatgpt", "grok", "cursor"];
export const POLL_OPEN_MS = 5000;
export const POLL_IDLE_MS = 60000;
export const STATUS_MS = 60000;
export const FRESH_MS = 10000;
const SLOT_WORDS = {
  versus: { a: "A builds, reviews B", b: "B builds, reviews A" },
  vote: { a: "Voter A", b: "Voter B", c: "Voter C" },
  "research-build": { research: "Research", build: "Build", check: "Check" },
  collab: { lead: "Lead (plans, builds)", partner: "Partner (amends, edits)" },
  redteam: { build: "Build and revise", attack: "Attack", attack2: "Second attack", check: "Check" },  // brief 32: attack2
};

export function agentLabel(name) {
  return AGENT_NAMES[name] || String(name || "");
}

export function teamLabel(name) {
  if (!name || name === "route") return "Route";
  return name.charAt(0).toUpperCase() + name.slice(1);
}

export function shortNumber(n) {
  const v = Number(n) || 0;
  if (v >= 1e6) return `${+(v / 1e6).toFixed(v % 1e6 ? 1 : 0)}M`;
  if (v >= 1e3) return `${Math.round(v / 1e3)}k`;
  return String(v);
}

export function newChatName(date = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return `chat-${date.getFullYear()}${p(date.getMonth() + 1)}${p(date.getDate())}-${p(date.getHours())}${p(date.getMinutes())}`;
}

export function isAutoChatName(name) {
  // the shape newChatName makes (Cleanup 2, row 14): only such a chat, with no tasks yet, can still be named
  return /^chat-\d{8}-\d{4}$/.test(name || "");
}

export function chatNameHint(typed, status) {
  const saved = projectSlug(typed || "");
  if (!saved) return { saved: "", text: "" };
  const taken = ((status && status.chats) || []).some((c) => c.name === saved);
  return { saved, text: taken ? "That chat exists: this adds to it" : `Reads as ${saved}` };
}

export function isOpenTask(task) {
  return !!task && task.outcome == null && ["queued", "sent", "returned"].includes(task.status);
}

export function pollInterval(tasks, pending = 0, actions = 0, justClosed = false) {
  // brief 29.1 (decision 7g): a page action still running, or a task that ended since the last look, keeps the open
  // pace. A split's end is two writes (done, then its change waiting to land): a look between them saw an ended split
  // with no Land, and the next look was a minute away, so Land showed only after a reload
  return pending > 0 || actions > 0 || justClosed || (tasks || []).some(isOpenTask) ? POLL_OPEN_MS : POLL_IDLE_MS;
}

export function justClosed(before, now) {
  // the ids that read open at the last look and read closed now
  const open = new Set((before || []).filter(isOpenTask).map((t) => t.task_id));
  return (now || []).some((t) => open.has(t.task_id) && !isOpenTask(t));
}

function usable(agent) {
  // brief 24 (decision 15): the router's own answer (`available`, `why`), never worked out here
  if (!agent) return { ok: false, why: "not in this router" };
  return agent.available ? { ok: true, why: null } : { ok: false, why: agent.why || "not available" };
}

// brief 24: the light and the word for each reason an agent isn't available (status's `why_code`)
const UNAVAILABLE = { not_live: ["muted", "off"], not_configured: ["muted", "not set up"], signed_out: ["bad", "signed out"],
  unreachable: ["bad", "offline"], probe_failed: ["bad", "off"] };

function searchWord(probe) {
  const state = probe && probe.state;
  if (state === "passed") return "search on";
  if (state === "failed") return "search off";
  if (state === "could_not_run") return "search off for now";
  if (state === "moved" || state === "missing") return "search checks itself";
  return "search ?";
}

// ---------- the top strip ----------

export function agentView(agent, tasks = [], models = null) {
  const name = agentLabel(agent.name);
  const working = (tasks || []).find((t) => t.working && t.working.agent === agent.name && isOpenTask(t)) || null;
  let tone = "muted", state = "not checked", detail = [];
  if (agent.available === false) {  // brief 24 (decision 15): status's answer and its words
    [tone, state] = UNAVAILABLE[agent.why_code] || ["bad", "not available"];
    detail = [agent.why || state];
  } else if (agent.online === true) {
    tone = "ok"; state = "online";
  } else if (agent.online === false && agent.why) {  // The owner after F: Claude's check didn't answer; it is tried anyway
    tone = "warn"; state = "check didn't answer"; detail = [agent.why];
  }
  if (tone === "ok") {
    if (agent.name === "claude") detail = [`Code ${agent.version || "?"} · ${searchWord(agent.probe)}`, claudeCallsThisWeek(models)];  // 33.3
    else if (agent.name === "chatgpt") detail = [`${agent.model || "-"} · signed in`];
    else if (agent.name === "grok") detail = [callsThisWeek(agent.calls_this_week)];
    else if (agent.name === "cursor") detail = [`${agent.model || "-"} · ${callsThisWeek(agent.calls_this_week)}`];
    else detail = [agent.model || ""];
  }
  if (agent.name === "cursor" && agent.configured && agent.model && !/^(grok|cursor-grok)/.test(agent.model)) {
    tone = "bad"; state = "not pinned"; detail = [`${agent.model} is not a pinned Grok model`];
  }
  if (working && tone === "ok") {
    tone = "info";
    state = `on #${working.n}`;
    detail = [working.working.doing || "working"];
  }
  return { key: agent.name, name, tone, state, detail: detail.filter(Boolean),
    setup: tone === "bad" || state === "not set up" };
}

function callsThisWeek(n) {
  const count = n || 0;
  return `${count} call${count === 1 ? "" : "s"} this week`;
}

export function jevView(jev) {
  if (!jev) return { text: "-", pct: 0, over: false, configured: false };
  const pct = jev.cap ? Math.min(100, (jev.tokens_month / jev.cap) * 100) : 0;
  return { text: `${shortNumber(jev.tokens_month)} of ${shortNumber(jev.cap)}`, pct, over: !!jev.over_cap,
    configured: !!jev.configured };
}

const MEMORY_STARTING = { tone: "info", state: "starting", detail: "about 35 s · nothing to do", problem: false, off: false };

export function memoryView(memory, { turningOn = false } = {}) {
  // brief 27 (decision 12): off is your choice and installed-and-down is "ready"; only "not installed" is a setup
  // problem. While the page's own run to on is in flight the light reads starting from that run (the owner's choice 7).
  if (turningOn) return MEMORY_STARTING;
  if (!memory) return { tone: "muted", state: "unknown", detail: "", problem: false, off: false };
  // the memory brief (fixes 1 and 2): a bad setting reads off, a memory_url off this Mac offline; the router's words say why
  if (memory.problem) return { tone: "warn", state: memory.setting === "off" ? "off" : "offline", detail: memory.problem, problem: true, off: memory.setting === "off" };
  if (memory.setting === "off") return { tone: "muted", state: "off", detail: "you turned it off · tasks run without it and nothing is saved", problem: false, off: true };
  if (memory.starting) return MEMORY_STARTING;
  if (memory.online) {
    const docs = memory.documents == null ? "" : `${memory.documents} documents · `;
    return { tone: "ok", state: "online", detail: `${docs}starts itself`, problem: false, off: false };
  }
  if (memory.installed === false) return { tone: "muted", state: "not installed", detail: "chat and project tasks run without it until it's installed", problem: true, off: false };
  return { tone: "ok", state: "ready", detail: "starts itself when a chat or project task needs it", problem: false, off: false };
}

export function memoryLink(view) {
  // the strip's details link for memory: off turns it on in Setup, not installed sets it up, the rest link nothing
  if (!view) return null;
  return view.off ? "Turn it on in Settings" : view.problem ? "How to set it up" : null;
}

const MEMORY_WORDS = {
  on: "On. The router remembers what each chat and project task delivers, and gives later tasks there the earlier results that match. It starts the store itself when a task needs it.",
  off: "Off. Tasks run without memory, and nothing they deliver is saved, not even after you turn it back on. The store is stopped. A project's HANDOFF.md still goes with its tasks.",
  starting: "Starting the store: about 35 seconds. Then it saves what chat and project tasks delivered while it was down.",
  stopping: "Turning memory off: the router stops the store it started. Tasks from now on run without memory.",
};

export function memorySwitchView(memory, run = null, failure = null, now = Date.now()) {
  // the Setup row's switch and its note (decision 11): `run` is the page's own memory_switch run in flight ({to, started}),
  // `failure` the last one's refusal ({exit, message}); the switch can't be clicked while a run goes or before status.
  // break-ui: a run still going after a minute says how long, and where to look
  const busy = !!run;
  const on = busy ? run.to === "on" : !!memory && memory.setting !== "off";
  const to = busy ? run.to : on ? "off" : "on";
  const label = busy ? (run.to === "on" ? "Starting…" : "Turning off…") : on ? "On" : "Off";
  const words = busy ? (run.to === "on" ? MEMORY_WORDS.starting : MEMORY_WORDS.stopping) : on ? MEMORY_WORDS.on : MEMORY_WORDS.off;
  const minutes = busy && run.started ? Math.floor((now - run.started) / 60000) : 0;
  return { on, to, label, busy, disabled: busy || !memory, words,
    cmdLabel: busy ? (minutes >= 1 ? `Running for ${minutes} min` : "Running") : "The switch runs",
    still: minutes >= 1 ? `The command hasn't ended after ${minutes} min. It keeps running if you close this page; the Memory light shows where memory is when it ends.` : null,
    failure: failure ? { exit: failure.exit, message: failure.message } : null };
}

export function chatMemoryWords(memory) {
  return memory && memory.setting === "off" ? "memory off" : "memory on for this chat";
}

// ---------- the team chips and the slot strip ----------

export function chipViews(status, lit = "route", { project = null } = {}) {
  const chips = [{ key: "route", label: "Route", disabled: false, reason: null,
    title: "Jev labels the task; the skill table picks who does it and who checks it" }];
  for (const preset of (status && status.presets) || []) {
    // brief 24 (decision 15): greyed only when status says the chain can't run now, with status's reason
    const blocked = preset.ready === false;
    chips.push({ key: preset.name, label: teamLabel(preset.name), disabled: blocked, reason: blocked ? preset.why : null,
      title: [preset.description, preset.chain].filter(Boolean).join(" · ") });
  }
  const split = status && status.split;
  if (split) {  // brief 29 (decision 1): Split after the presets, greyed with status's reason when it can't run
    chips.push({ key: "split", label: "Split", disabled: split.ready === false, reason: split.ready === false ? split.why : null,
      title: [split.description, split.chain].filter(Boolean).join(" · ") });
  }
  const plan = status && status.plan;
  if (plan) {  // brief 33.1 (decision 1): Plan after Split, on a project only, greyed off one with the reason
    const why = plan.ready === false ? plan.why : !project ? PLAN_OFF_PROJECT : null;
    chips.push({ key: "plan", label: "Plan", disabled: !!why, reason: why,
      title: [plan.description, plan.chain].filter(Boolean).join(" · ") });
  }
  return chips.map((chip, i) => ({ ...chip, checked: chip.key === lit, shortcut: i < 8 ? `⌥${i + 1}` : null }));
}

export const PLAN_OFF_PROJECT = "Plan works on a project: pick one";  // brief 33.1 (decision 1)

// ---------- brief 33.3 (decisions 6, 11 and 12): the Models sheet, its pills, Setup's Models row, Details' model lines ----------
// The router works every model out (status's `models`: each agent's default and allowlist, the Fable switch, what each role
// would use now, Setup's rows, the week's counts); the page shows them and sends `--model <agent>=<model>` for a choice.

export const MODEL_AGENTS = ["claude", "chatgpt", "cursor"];  // the agents with a model choice (Grok Bot's and Jev's services pick)
const FILE_ROLES = ["build", "revise", "execute", "fix", "integrate"];  // decision 2: Claude's file-mode roles on a project
export const FABLE_OFF_WHY = "Fable is off: turn it on in Settings → Models once usage credits are off on your account";

export function fableOffWords(models) {
  // decision 6's own words (status's `fable.words`), then where the switch is; the short line when status has none
  const words = models && models.fable && models.fable.words;
  return words ? `${words} Fable is off: turn it on in Settings → Models.` : FABLE_OFF_WHY;
}

export function modelsMenuItem(status) {
  // the Team menu's last item, opening the Models sheet (/model too); greyed while status carries no models (not read yet)
  const models = status && status.models;
  return { key: "models", label: "Models…", disabled: !models, reason: models ? null : "the router's status has no models yet",
    title: "Pick the model each agent uses on this task; the defaults apply where you pick none" };
}

export function modelShort(agent, id, status) {
  // a pill's word for a model: Claude's alias with a capital ("Haiku"), else the tracked name, else the id itself
  const doc = ((status && status.models && status.models.agents) || {})[agent];
  if (!id) return "";
  if (!doc) return id;
  const alias = Object.entries(doc.aliases || {}).find(([, full]) => full === id);
  if (alias) return alias[0].charAt(0).toUpperCase() + alias[0].slice(1);
  return (doc.names || {})[id] || id;
}

export function modelOptions(agent, status, { chosen = "", defaults = "Defaults" } = {}) {
  // a select's options: Defaults first (value ""), then the agent's allowlist by name; Fable greyed with why while it is off
  const models = (status && status.models) || {};
  const doc = (models.agents || {})[agent] || {};
  const fableOff = !!(models.fable && models.fable.on === false);
  const options = [{ value: "", label: defaults, disabled: false, reason: null, selected: !chosen }];
  for (const id of doc.allowed || []) {
    const gated = fableOff && (doc.gated || []).includes(id);
    options.push({ value: id, label: `${(doc.names || {})[id] || id}${gated ? " (off)" : ""}`, disabled: gated,
      reason: gated ? fableOffWords(models) : null, selected: chosen === id });
  }
  if (chosen && !options.some((o) => o.value === chosen)) {  // break-ui: a choice the allowlist lost still shows, greyed
    options.push({ value: chosen, label: `${chosen} (not on the list)`, disabled: true, reason: "not on the allowed list", selected: true });
  }
  return options;
}

function callWho(c) {
  return `${c.kind === "stage" || c.kind === "reask" ? `${c.role || "stage"}${c.kind === "reask" ? " re-ask" : ""}` : c.kind} · ${agentLabel(c.agent)}`;
}

export function teamModelsNow(status, team, { project = null } = {}) {
  // decision 11: per agent the chosen team uses, what each of its roles would use now, from status: Route's by skill (its
  // agents are known once Jev labels the task), a team's by stage and its check, a split's plan, join and check, a plan's
  // chain; on a project a team's Claude build, revise, execute, fix and integration calls read the file-mode defaults
  const now = (status && status.models && status.models.now) || {};
  const byAgent = new Map();
  const add = (agent, what, entry) => {
    if (!MODEL_AGENTS.includes(agent) || !entry) return;
    if (!byAgent.has(agent)) byAgent.set(agent, []);
    byAgent.get(agent).push({ what, model: entry.model, name: entry.name || entry.model, note: entry.note || null });
  };
  if (team === "route") {
    // decision 2: on a project the doer builds in the copy, so the file-mode defaults apply (status's `project_skills`)
    const skills = project && now.project_skills ? now.project_skills : now.skills;
    for (const [key, roles] of Object.entries(skills || {})) {
      if (roles.do) add(roles.do.agent, key.replace(/_/g, " "), roles.do);
      if (roles.check) add(roles.check.agent, `${key.replace(/_/g, " ")} check`, roles.check);
    }
  } else {
    for (const item of (now.teams || {})[team] || []) {
      const file = project && team !== "plan" && item.agent === "claude" && FILE_ROLES.includes(item.role) ? (now.file || {})[item.role] : null;
      add(item.agent, item.role, file || item);
    }
  }
  return [...byAgent].map(([agent, entries]) => ({ agent, entries }));
}

export function defaultsWords(entries, { skills = false } = {}) {
  // "Sonnet 5.5 (most skills) · Opus 5.5 (code)": the roles grouped by the model each would use now; on Route a group of
  // more than three skills reads "most skills" (twelve skill names would not fit a line)
  const groups = new Map();
  for (const e of entries) {
    if (!groups.has(e.name)) groups.set(e.name, { name: e.name, whats: [], note: e.note });
    groups.get(e.name).whats.push(e.what);
  }
  const list = [...groups.values()].sort((a, b) => b.whats.length - a.whats.length);
  return list.map((g, i) => {
    const most = skills && g.whats.length > 3;
    return `${g.name} (${most ? "most skills" : g.whats.join(", ")})${g.note ? ` · ${g.note}` : ""}`;
  }).join(" · ");
}

export function modelsSheetView(status, team, chosen = {}, { project = null } = {}) {
  // decision 12: the Models sheet: per agent the chosen team uses, a select of its allowlist with Defaults first, and what
  // Defaults means now ("Claude: Opus 5.5 (code)"); Fable greyed with why while it is off
  const models = status && status.models;
  const title = `Models · ${teamLabel(team)}`;
  if (!models) return { ready: false, why: "The router's status has no models yet: reload, or check the router's version.", title, agents: [], note: null, fableOff: false };
  const agents = teamModelsNow(status, team, { project }).map(({ agent, entries }) => ({
    agent, label: agentLabel(agent), chosen: (chosen || {})[agent] || "",
    defaults: defaultsWords(entries, { skills: team === "route" }),
    options: modelOptions(agent, status, { chosen: (chosen || {})[agent] || "" }),
  }));
  const note = team === "route" ? "Route's agents are known once Jev labels the task: a choice applies to whatever calls that agent makes."
    : team === "split" ? "The plan and the join; each piece uses its team's defaults."
      : team === "plan" ? "The plan's own calls; each step runs later as its team does." : null;
  return { ready: true, why: agents.length ? null : `${teamLabel(team)} makes no call with a model choice.`, title, agents, note,
    fableOff: !!(models.fable && models.fable.on === false) };
}

export function modelPillViews(chosen, status) {
  // decision 12: one pill per chosen agent, "Claude: Haiku", with its × (the aria words say what the × does)
  return Object.entries(chosen || {}).filter(([agent, id]) => MODEL_AGENTS.includes(agent) && id).map(([agent, id]) => ({
    agent, model: id, words: `${agentLabel(agent)}: ${modelShort(agent, id, status)}`,
    aria: `Let ${agentLabel(agent)} use its default model` }));
}

export function pruneModels(chosen, status, team, { project = null } = {}) {
  // a choice for an agent the team doesn't use is dropped when the team changes (the router would refuse it); null when none
  if (!chosen) return null;
  if (!(status && status.models)) return chosen;
  const used = new Set(teamModelsNow(status, team, { project }).map((a) => a.agent));
  const kept = Object.fromEntries(Object.entries(chosen).filter(([agent, id]) => id && used.has(agent)));
  return Object.keys(kept).length ? kept : null;
}

export function modelsSetupRow(status) {
  // decision 12: the Setup sheet's Models row from status's `models`: each agent's default, how many defaults of your own,
  // and Fable; a default the router ignored (decision 5: a name off the allowlist at load) is a setup problem, said why
  const models = status && status.models;
  const row = { key: "models", name: "Models", checkedAt: null };
  if (!models) return { ...row, tone: "quiet", state: "unknown", detail: "not read yet" };
  const problems = models.problems || [];
  const layers = models.layers || [];
  if (problems.length) return { ...row, tone: "bad", state: `${count(problems.length)} ignored`, detail: problems.join("; ") };
  const defaults = Object.entries(models.agents || {}).map(([agent, doc]) => `${agentLabel(agent)} ${doc.name || doc.default || "-"}`);
  return { ...row, tone: "ok", state: layers.length ? `${count(layers.length)} of your own` : "the agents' defaults",
    detail: `${defaults.join(" · ")} · Fable ${models.fable && models.fable.on ? "on" : "off"}` };
}

export function fableSwitchView(models, run = null, failure = null) {
  // decision 6: the Fable switch and its words, from status (`models.fable`); the page's own run in flight ({to, started}),
  // the last one's refusal; it can't be clicked while a run goes or before status
  const fable = models && models.fable;
  const busy = !!run;
  const on = busy ? run.to === "on" : !!(fable && fable.on);
  const to = busy ? run.to : on ? "off" : "on";
  return { on, to, busy, disabled: busy || !fable, label: busy ? (run.to === "on" ? "Turning on…" : "Turning off…") : on ? "On" : "Off",
    words: (fable && fable.words) || "",
    offBy: fable && !fable.on && fable.off_by ? `The router turned it off (${fable.off_by}).` : null,
    fallback: fable && !fable.on ? `While it is off, a Fable default runs on ${fable.fallback_name || "Opus"} and the card says so; a typed Fable is refused.` : null,
    cmdLabel: busy ? "Running" : "The switch runs", failure: failure ? { exit: failure.exit, message: failure.message } : null };
}

// Cleanup 2, row 3: the skills' plain names. A key not here (a clone's own skill) reads with spaces. The router has its own for
// its refusal's words (routing.SKILL_WORDS); a test holds the two alike.
const SKILL_NAMES = { x_social_pulse: "X research", meta_social_trends: "Meta research", make_media: "Make media", computer_use: "Computer use",
  web_research: "Web research", read_media: "Read media", code: "Code", writing: "Writing", planning: "Planning", bulk_text: "Bulk text",
  quick_answer: "Quick answer", recall: "Recall" };

export function skillName(key) {
  return SKILL_NAMES[key] || String(key || "").replace(/_/g, " ");
}

export function skillRowWords(s) {
  // what a row without a choice reads in place of a model
  if (s.state === "not_routed") return "not routed";
  if (s.state !== "service") return null;
  return s.comes_back ? `its service picks the model · comes back without ${agentLabel(s.agent)}` : "its service picks the model";
}

export function unusedPickWords(pick) {
  // a pick already in the file that the router itself can never reach: it stays until it's cleared (option A: the two doors)
  const what = pick.name || (pick.effort ? `effort ${pick.effort}` : pick.model);
  return `Your earlier pick for ${agentLabel(pick.agent)} (${what}) isn't used: it reaches only a task you send as @${pick.agent}${pick.agent === "claude" ? ", or a text-only draft" : ""}.`;
}

export function modelsSetupSelects(status) {
  // decision 12: Setup's selects from status's `models.setup`: one per skill, naming the agent that does it now (a skill with no
  // choice has no select: Cleanup 2, row 3), and one per team, role and agent, each with Default first (that agent's default by
  // name) and its allowlist; a change runs `sr models set`
  const models = status && status.models;
  if (!models) return { skills: [], roles: [], stages: [] };
  const setup = models.setup || {};
  const agentDefault = (agent) => ((models.agents || {})[agent] || {}).name || "the agent's default";
  const skills = (setup.skills || []).map((s) => {
    const state = s.state || "choice";
    return { key: s.key, agent: s.agent, chosen: s.model || "", state, words: skillRowWords({ ...s, state }), unused: s.unused || [],
      label: state === "not_routed" ? skillName(s.key) : `${skillName(s.key)} · ${agentLabel(s.agent)}`, selector: { skill: s.key },
      options: state === "choice" ? modelOptions(s.agent, status, { chosen: s.model || "", defaults: `Default (${agentDefault(s.agent)})` }) : [] };
  });
  const roles = (setup.roles || []).map((r) => ({ team: r.team, role: r.role, agent: r.agent, chosen: r.model || "",
    label: `${teamLabel(r.team)} · ${r.role} · ${agentLabel(r.agent)}`, selector: { team: r.team, role: r.role },
    options: modelOptions(r.agent, status, { chosen: r.model || "", defaults: `Default (${agentDefault(r.agent)})` }) }));
  const stages = (setup.stages || []).map((r) => ({ team: r.team, stage: r.stage, role: r.role, agent: r.agent, chosen: r.model || "",
    label: `${teamLabel(r.team)} · stage ${r.stage} (${r.role}) · ${agentLabel(r.agent)}`, selector: { team: r.team, stage: r.stage },
    options: modelOptions(r.agent, status, { chosen: r.model || "", defaults: `Default (${agentDefault(r.agent)})` }) }));
  return { skills, roles, stages };
}

export function callModelLines(show) {
  // decision 12: Details lists each call's model, asked → served, and its time limit (its effort when one was set)
  return ((show && show.calls) || []).filter((c) => c.model).map((c) => {
    const served = c.served && c.served.model ? c.served.model : "served unknown";
    const limit = c.time_limit ? ` · limit ${count(c.time_limit)} s` : "";
    const effort = c.effort ? ` · effort ${c.effort}` : "";
    return `${callWho(c)}: ${c.model} → ${served}${limit}${effort}`;
  });
}

export function claudeCallsThisWeek(models) {
  // decision 11: under Claude, Opus and Fable calls this week (calls, never tokens), from status's `models.claude`
  const counts = models && models.claude;
  if (!counts) return null;
  return `${count(counts.opus_calls_this_week || 0)} Opus, ${count(counts.fable_calls_this_week || 0)} Fable calls this week`;
}

export function modelsSelectorWords(request) {
  // the demo's command preview for Setup's selects (page_commands builds the real one)
  const s = request.selector || {};
  if (s.skill) return `--skill ${s.skill}`;
  if (s.stage != null) return `--team ${s.team} --stage ${s.stage}`;
  return `--team ${s.team} --role ${s.role}`;
}

// Brief 32 (decision 12): who may not hold an attack slot, as intake refuses: the build's agent, and for the second attack
// also the first attack's
const OWN_BUILD = ["build", "an attacker doesn't attack its own build"];
const NOT_WITH = { attack: [OWN_BUILD], attack2: [OWN_BUILD, ["attack", "two lists from one agent are not two attackers"]] };

// A slot's short name on the page: Versus's and Vote's letters as capitals, any other slot by its preset's words
const slotShort = (slot) => (slot.name.length <= 2 ? slot.name.toUpperCase() : slot.label);

export function slotViews(preset, chosen = {}, status = null, project = null) {
  if (!preset) return { slots: [], note: null };
  const agents = new Map(((status && status.agents) || []).map((a) => [a.name, a]));
  const words = SLOT_WORDS[preset.name] || {};
  const valueOf = (slot) => {
    const fill = (preset.filled || []).find((f) => f.slot === slot.name) || null;
    return chosen[slot.name] || (fill && fill.agent ? fill.agent : slot.default);
  };
  const values = Object.fromEntries((preset.slots || []).map((s) => [s.name, valueOf(s)]));
  const slots = (preset.slots || []).map((slot) => {
    // brief 24 (decisions 8 and 15): `allowed` lists only available agents; a default that isn't available shows
    // greyed with why, and the agent the router fills its slot with is the one chosen
    const fill = (preset.filled || []).find((f) => f.slot === slot.name) || null;
    const leftOut = !!fill && !fill.agent && !chosen[slot.name];  // brief 32 (decision 11): the second attack, left out
    const options = (slot.allowed || []).map((agent) => ({ agent, label: agentLabel(agent), disabled: false, reason: null }));
    if (!(slot.allowed || []).includes(slot.default)) {
      options.unshift({ agent: slot.default, label: agentLabel(slot.default), disabled: true,
        reason: (fill && fill.why) || usable(agents.get(slot.default)).why });
    }
    if (leftOut) options.unshift({ agent: "", label: "Left out", disabled: false, reason: fill.why });
    for (const [other, why] of (preset.name === "redteam" && NOT_WITH[slot.name]) || []) {  // brief 32: as intake refuses
      for (const o of options) if (!o.disabled && o.agent === values[other]) Object.assign(o, { disabled: true, reason: why });
    }
    if (project) {  // brief 32 (decision 13): a project refuses some agents in some slots (status's own words for each slot)
      for (const o of options) if (!o.disabled && (slot.project_refuses || []).includes(o.agent)) Object.assign(o, { disabled: true, reason: "not on a project" });
    }
    return {
      name: slot.name,
      label: words[slot.name] || teamLabel(slot.name),
      value: leftOut ? "" : values[slot.name] || slot.default,
      isDefault: !chosen[slot.name] || chosen[slot.name] === slot.default,
      filled: fill ? { agent: fill.agent, why: fill.why } : null,
      leftOut,
      options,
    };
  });
  // where the router allows Cursor (its `allowed`), whatever another slot holds now
  const cursorSlots = slots.filter((s, i) => (preset.slots[i].allowed || []).includes("cursor")).map(slotShort);
  const note = cursorSlots.length ? `Cursor may fill ${teamLabel(preset.name)} ${cursorSlots.join(" or ")} only` : null;
  return { slots, note };
}

// ---------- what the person types ----------

export function parseComposer(text, presetNames = [], { atEnd = false } = {}) {
  const value = String(text || "");
  const match = /^\/([a-z][a-z0-9-]*)(\s|$)/.exec(value);
  let slash = null, rest = value;
  if (match && (match[2] || atEnd)) {
    const word = match[1];
    if (PAGE_SLASHES.includes(word) || presetNames.includes(word)) {
      rest = value.slice(match[0].length);
      if (word === "project" || word === "chat") {
        // the name counts once a space follows it (or on Send): while it is being typed the box keeps it as it is
        const arg = (atEnd ? /^(\S+)(\s|$)/ : /^(\S+)\s/).exec(rest);
        if (!arg && !atEnd) return { slash: null, text: value, override: null };
        slash = { kind: word, value: arg ? arg[1] : null };
        if (arg) rest = rest.slice(arg[0].length);
      } else {
        slash = presetNames.includes(word) ? { kind: "team", value: word } : { kind: word, value: null };
      }
    }
  }
  const over = /^@([a-z]+)(\s|$)/.exec(rest);
  return { slash, text: rest, override: over && OVERRIDES.includes(over[1]) ? over[1] : null };
}

export function contextFor(state, status) {
  const presets = (status && status.presets) || [];
  const preset = presets.find((p) => p.name === state.team) || null;
  const takesProject = state.team === "route" || !!(preset && preset.project) || (state.team === "split" && !!(status && status.split));
  const project = state.project === NEW_PROJECT ? null : state.project;  // brief 26: the picker's sentinel is never sent
  if (state.team === "split" || state.team === "plan") {
    // brief 29 (decision 1): a split takes a project but never a chat tag, even sent from a chat; Quick has nothing to drop.
    // Brief 33.1 (decision 1): a plan, the same, and on a project only (the router refuses it without one)
    const kind = state.team;
    return project ? { kind, flag: "project", value: project, projectGreyed: false, takesProject: true }
      : { kind, flag: null, value: null, projectGreyed: false, takesProject: true };
  }
  if (state.quick) return { kind: "quick", flag: null, value: null, projectGreyed: true, takesProject };
  if (project && takesProject) return { kind: "project", flag: "project", value: project, projectGreyed: false, takesProject };
  return { kind: "chat", flag: "chat", value: state.chat, projectGreyed: !takesProject, takesProject };
}

export function skillPick(state, status) {
  // brief 24 (decision 13, C16): without Jev a routed task needs your skill before Send (an @agent override needs none)
  const jev = status && status.jev;
  if (state.team !== "route" || !jev || jev.available !== false) return { needed: false, options: [], chosen: null };
  if (parseComposer(state.text || "").override) return { needed: false, options: [], chosen: null };
  // a skill that would come back says why in status's note ("needs Grok Bot": make_media, and x_social_pulse since 21 Oct)
  const options = ((status && status.skills) || []).filter((s) => !(s.now && s.now.comes_back === "skill not routed in version 2"))
    .map((s) => ({ key: s.key, label: s.key.replace(/_/g, " ") + (s.now && s.now.comes_back && s.now.note ? ` (${s.now.note})` : "") }));
  const chosen = options.some((o) => o.key === state.skill) ? state.skill : null;
  return { needed: true, options, chosen, why: jev.why || "Jev isn't set up: pick the skill" };
}

export function skillChoice(ui, status) {
  // UI A row 1 (A13): a skill on any routed task: Auto (Jev labels it) or your pick, which goes with --skill, so Jev isn't
  // called. skillPick stays as it is for the Jev-off case. Off Route it's greyed; an @agent override carries none, since the
  // router refuses --skill with one. A skill that would come back says why; `computer_use` is left out, as today
  const jevOff = !!(status && status.jev && status.jev.available === false);
  const options = ((status && status.skills) || []).filter((s) => !(s.now && s.now.comes_back === "skill not routed in version 2"))
    .map((s) => ({ key: s.key, label: s.key.replace(/_/g, " ") + (s.now && s.now.comes_back && s.now.note ? ` (${s.now.note})` : "") }));
  const base = { options, first: jevOff ? "Pick one" : "Auto", greyed: null, chosen: null };
  if (ui.team !== "route") return { ...base, first: "Auto", greyed: "Route only" };
  if (parseComposer(ui.text || "").override) return base;
  return { ...base, chosen: options.some((o) => o.key === ui.skill) ? ui.skill : null };
}

// ---------- brief 33, N: next-step chips (decisions 1, 2, 7 and 19) ----------

export const UNDO_MS = 10000;  // decision 1: how long a fill over typed words offers Undo
const PASSED_OVER = new Set(["discarded", "undone"]);  // decision 2: newer tasks that leave the chips where they are

export function chipCardId(view, tasks) {
  // decision 2: the one card of a view that shows its chips: in a project's or a chat's view, its newest top-level task
  // (cancelled, discarded and undone ones passed over), when the router gave it chips (it does only once delivered)
  if (view !== "project" && view !== "chat") return null;
  const newest = [...(tasks || [])].filter((t) => !t.parent && t.mode !== "suggest")  // brief 33.4 (decision 10)
    .filter((t) => t.status !== "cancelled" && !PASSED_OVER.has(t.project_files && t.project_files.state))
    .sort((a, b) => b.n - a.n)[0];
  return newest && (newest.next || []).length ? newest.task_id : null;
}

export function chipPlace(task, chipId) {
  // under the result on the view's chip card; an older card keeps them in its Details, under "Suggested next"
  if (!(task.next || []).length) return null;
  return task.task_id === chipId ? "inline" : "details";
}

export function fillFromChip(chip, current, n) {
  // decision 1: Route, the tag, the text and, when the move carries one, From; a fill over typed words keeps an undo.
  // Brief 33.1 (decisions 6, 12 and 18): a plan's moves fill their own team (a step's, Plan) and a Step pill
  const fill = chip.fill || {};
  const step = fill.step ? { plan: fill.step.plan, n: fill.step.n, k: fill.step.k } : null;
  const next = { text: fill.text || "", team: fill.team || "route", project: fill.project || null,
    chat: fill.project ? null : fill.chat || null, quick: false, from: fill.from ? { task_id: fill.from, n } : null,
    idea: fill.idea || null, step, placeholder: chip.kind === "build_from" ? `What should be built from #${n}?` : null,
    noFiles: !!fill.no_files };  // brief 33.2 (decision 5): Draft it's text-only task, the Text only pill
  return { next, undo: (current.text || "").trim() ? { ...current } : null };
}

export function stepPillWords(step) {
  // brief 33.1 (decision 12): the Step pill, "Step 2 of plan #12"; the task is still that step if you change its words
  return step ? `Step ${step.k} of plan #${step.n}` : null;
}

export function sendRequest(state, status) {
  const request = { action: "send", team: state.team, text: state.text };
  const ctx = contextFor(state, status);
  if (ctx.flag && ctx.value) request[ctx.flag] = ctx.value;
  if (state.models && Object.keys(state.models).length) request.models = { ...state.models };  // brief 33.3 (decision 4): every team
  if (state.team === "split") return request;  // brief 29: no slots, files, web or skill; a project at most
  if (state.from) request.from = state.from.task_id;  // brief 33 (decision 8): never on a split
  if (state.idea) request.idea = state.idea.id;  // brief 33 (decision 16): sent with the Idea pill; 33.2: on a plan too
  if (state.team === "plan") return request;  // brief 33.1 (decision 1): the project, the text, From and the idea; nothing else
  if (state.step && ctx.flag === "project" && ctx.value) request.step = `${state.step.plan}:${state.step.k}`;  // 33.1
  if (state.team === "route") {
    if ((state.files || []).length) request.files = state.files.map((f) => f.path);
    if (state.web) request.web = true;
    if (state.noFiles && ctx.flag === "project" && ctx.value) request.no_files = true;  // brief 33.2 (decision 5)
    const choice = skillChoice(state, status);  // UI A row 1 (A13): any routed task
    if (choice.chosen) request.skill = choice.chosen;
  } else {
    const preset = ((status && status.presets) || []).find((p) => p.name === state.team);
    const slots = {};
    for (const slot of (preset && preset.slots) || []) {
      const chosen = (state.slots || {})[slot.name];
      if (chosen && chosen !== slot.default) slots[slot.name] = chosen;
    }
    if (Object.keys(slots).length) request.slots = slots;
  }
  return request;
}

export function placeholderFor(team, status) {
  if (team === "route") return "New task: Jev labels it, the right agent does it, another checks it";
  if (team === "plan") return "What should Plan plan? A goal, a focus, or “Plan the first version.”";  // brief 33.1
  if (team === "split") {  // brief 29 (decision 1): the chain from status
    const split = status && status.split;
    return `New task for Split: ${split ? split.chain : "Claude plans the pieces, you approve them"}`;
  }
  const preset = ((status && status.presets) || []).find((p) => p.name === team);
  return `New task for ${teamLabel(team)}: ${preset ? preset.chain || preset.description : "a team"}`;  // UI A row 14 (A14): the chain, for a phone
}

export function jevBox({ team, task = null, floor = 0.8, sending = false, missing = null } = {}) {
  if (team === "split") return { mode: "not_asked", text: "Jev labels each piece once Claude plans them" };  // brief 29
  if (team === "plan") return { mode: "not_asked", text: "not asked: a plan's steps each run as their team does" };  // 33.1
  if (team && team !== "route") return { mode: "not_asked", text: `not asked: ${teamLabel(team)} names its own agents` };
  if (missing) return { mode: "missing", text: missing };  // brief 24 (decision 13): "Jev isn't set up: pick the skill"
  if (task && task.jev) {
    if (task.jev.status === "not_asked") return { mode: "yours", text: `your label: ${task.skill || "-"}` };
    if (task.jev.status === "error") return { mode: "error", text: "Jev did not answer: you pick the skill" };
    if (task.jev.status === "not_set_up") return { mode: "error", text: "Jev isn't set up: pick the skill" };
    const confidence = task.jev.confidence == null ? null : Number(task.jev.confidence);
    return { mode: "label", label: task.jev.label || "none of these", confidence, floor,
      under: confidence == null || confidence < floor };
  }
  if (sending) return { mode: "waiting", text: "asking Jev…" };
  return { mode: "idle", text: `fills when a Route task is sent · the floor is ${Number(floor).toFixed(2)}` };
}

export function shortcutFor(event, { inText = false, inPrompt = false } = {}) {
  if (event.isComposing || event.keyCode === 229) return null;
  if (event.altKey && !inText && !event.metaKey && !event.ctrlKey && /^Digit[1-8]$/.test(event.code || "")) {  // brief 29: ⌥7 Split; 33.1: ⌥8 Plan
    return { action: "chip", index: Number(event.code.slice(5)) - 1 };
  }
  if (event.key === "Enter" && inPrompt && !event.shiftKey && !event.altKey && !event.ctrlKey) return { action: "send" };
  if (event.key === "Escape") return { action: "escape" };
  if (event.key === "?" && !inText && !event.metaKey && !event.ctrlKey) return { action: "shortcuts" };
  return null;
}

export function stateWords(task) {
  if (task.waiting_on) {
    const words = { pick: "waiting for your pick", vote_pick: "a tie: waiting for your pick", needs_label: "waiting for your label",
      split_plan: "a split plan waiting for you", grok: "waiting on Grok", piece: "waiting on its pieces",
      probe: "waiting for a safety check", memory: "waiting for memory to start",
      land: "waiting for you to land or discard its change",  // brief 28
      answers: "waiting for your answers" };  // Cleanup 2, row 12 (note 5)
    return words[task.waiting_on] || `waiting on ${task.waiting_on.replace(/_/g, " ")}`;
  }
  if (task.outcome) {
    const words = { failed_check: "failed its check twice", plan_limit: "stopped on a plan limit", process_ended: "stopped: process ended",
      timed_out: "timed out", returned: "came back to you", tie: "a tie, picked" };
    return words[task.outcome] || task.outcome.replace(/_/g, " ");
  }
  return task.working && task.working.doing ? task.working.doing : "working";
}

export function taskSummary(task) {
  const of = task.piece_of || null;  // brief 29 (decision 17): a piece names its team and its place in its split
  const team = task.mode === "auto" ? "Auto" : of ? teamLabel(of.team) : task.mode === "relay" ? teamLabel(task.preset)  // brief 34
    : task.mode === "split" ? "Split" : task.mode === "plan" ? "Plan" : task.mode === "piece" ? `Piece of a split` : "Route";
  const tone = task.waiting_on ? (["grok", "piece", "probe", "memory"].includes(task.waiting_on) ? "info" : "warn")
    : ["passed", "fixed", "picked"].includes(task.outcome) ? "ok"
      : ["failed_check", "stopped", "plan_limit", "process_ended", "timed_out"].includes(task.outcome) ? "bad"
        : task.outcome ? "muted" : "info";
  const failed = task.failed_stage ? `stopped at stage ${task.failed_stage}` : null;
  return { team, state: stateWords(task), tone, check: task.check_state || null, note: task.check_note || null, failed,
    piece: !!task.parent, parent: task.parent || null,
    pieceOf: of && of.run ? `step ${of.step} of run #${of.n}` : of && of.piece ? `piece ${of.piece} of split #${of.n}`  // brief 34
      : task.plan_step && task.plan_step.n ? `step ${task.plan_step.step} of plan #${task.plan_step.n}` : null };  // brief 33.1
}

export function shellQuote(word) {
  // Python's shlex.quote, for the demo's command line (the real one comes from the server).
  const text = String(word);
  if (text && /^[A-Za-z0-9@%+=:,./_-]+$/.test(text)) return text;
  return `'${text.replace(/'/g, `'"'"'`)}'`;
}

export function refusalView(run) {
  const env = run.envelope || {};
  const message = env.message || run.message || (run.stderr ? run.stderr : "The command ended without an answer.");
  const exit = run.exit == null ? env.exit : run.exit;
  return { title: exit === 2 ? "The router refused this send" : "This send ended without a task",
    message, exit, code: env.reason_code || null, display: run.display };
}

// ---------- New project (brief 26, decisions 12–14) ----------
// The router decides; these only shape its answers. The folder check is `sr project new --json --dry-run <name>`.

export const NEW_PROJECT = "__new__";  // the picker's last option: opens the sheet, never sent (no project name has "_")
export const NOTES_MAX = 4000;
const SLUG_MAX = 48;

function slugAll(raw) {
  return String(raw || "").toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+/, "").replace(/-+$/, "");
}

export function projectSlug(raw) {
  // lower case, accents folded, each run of other characters one -, no - at either end, at most 48 characters; a cut
  // through a word moves back to the word's start when that is in the last third (break-ui: "…-board-revi")
  const all = slugAll(raw);
  if (all.length <= SLUG_MAX) return all;
  let cut = all.slice(0, SLUG_MAX);
  const dash = cut.lastIndexOf("-");
  if (all[SLUG_MAX] !== "-" && dash >= Math.floor(SLUG_MAX * 2 / 3)) cut = cut.slice(0, dash);
  return cut.replace(/-+$/, "");
}

export function slugHint(raw) {
  const saved = projectSlug(raw);
  if (saved && slugAll(raw).length > SLUG_MAX) return { saved, text: ` · cut to ${SLUG_MAX} characters` };
  if (saved) return { saved, text: " · lowercase letters, digits and\u00a0-" };  // break-ui: never a lone - on a line
  if (String(raw || "").trim()) return { saved: null, text: "Use letters or digits: the rest is converted as you type" };
  return { saved: null, text: "Lowercase letters, digits and -: the rest is converted as you type" };
}

export function newProjectView(check, { name = "", root = "~/Projects", taken = null, running = false, waited = false,
  error = null, demo = false, typed = false } = {}) {
  // The sheet from the router's dry run (`would`: create, register or refused). An answer for another name is stale.
  // `typed`: something is in the box though nothing of it is kept ("!!!", "日本語").
  const base = { tone: "muted", folder: name ? `${root}/${name}` : `${root}/…`, words: typed ? "no letters yet" : "type a name", detail: null,
    notesOn: true, notesHint: "Written once, at the top of HANDOFF.md. No keys: notes that look like one are refused.",
    button: "Create project", canCreate: false, foot: demo ? "Demo: nothing runs." : null };
  if (!name) return base;
  if (error) return { ...base, tone: "bad", words: "can't check", detail: error };
  if (!check || check.name !== name) {
    return waited ? { ...base, tone: "bad", words: "no answer", detail: "The router hasn't answered the folder check. Type again, or close and try later." }
      : { ...base, words: "checking…" };
  }
  const offWhenTaken = "Off: that name is a project already.";
  if (check.would === "refused") {
    const words = String(check.message || "").replace(/^Would refuse: /, "").replace(/ Nothing was changed\.$/, "");
    // the router's folder, shown with ~ (a taken name: where it is registered); status's absolute path is never printed
    return { ...base, tone: "bad", folder: check.folder || base.folder,
      words: taken ? "already a project" : "refused",
      detail: taken ? `${name} is registered already. Open it from the sidebar, or pick another name.` : words,
      notesOn: false, notesHint: taken ? offWhenTaken : "Off: the router refuses this name." };
  }
  const go = !running && !demo;
  if (check.would === "register") {
    const h = check.handoff || {};
    const detail = !h.exists ? "Added as it is. The router makes its HANDOFF.md with an empty block."
      : h.has_block ? `Added as it is. Its HANDOFF.md (${h.lines} lines) has the router's block already.`
        : `Added as it is. Its HANDOFF.md (${h.lines} lines) stays yours; the router adds its block at the end.`;
    return { ...base, tone: "info", folder: check.folder || base.folder, words: "folder exists", detail, notesOn: false,
      notesHint: h.exists ? "Off: this folder already has its own HANDOFF.md, and that file is yours to edit."
        : "Off: starting notes go only in a HANDOFF.md the router makes in a new folder.",
      button: running ? "Adding…" : "Add project", canCreate: go };
  }
  return { ...base, tone: "ok", folder: check.folder || base.folder, words: "new folder",
    detail: "The router makes the folder and its HANDOFF.md: your notes first, then the router's block.",
    button: running ? "Creating…" : "Create project", canCreate: go };
}

export function draftChipOf(doc) {
  // brief 33.4 (decision 15): Draft it's chip from `/api/project-spec`, whose answer is `{api_version, spec: {…, draft}}`
  return (doc && doc.spec && doc.spec.draft) || null;
}

export function ideaModeView(view, { idea = "", ideaMax = 2000, running = false, check = null } = {}) {
  // brief 33.4 (decision 15): From an idea: "Your idea", required, capped by `idea_max` with a live counter; Create off past
  // it and on a folder that exists (notes go only into a HANDOFF.md the router makes). Blank is `view` as it is.
  const length = idea.length;
  const over = length > ideaMax;
  const creates = !!check && check.would === "create";
  return { ...view, label: "Your idea", required: true, counter: `${length.toLocaleString("en-US")} / ${ideaMax.toLocaleString("en-US")}`, over,
    notesHint: over ? `Over the cap by ${(length - ideaMax).toLocaleString("en-US")}. It becomes the project's notes, which ride on every call.`
      : view.notesOn ? "It becomes the project's notes, word for word. Then the box fills with a task that drafts the spec; nothing is sent."
        : `${view.notesHint} From an idea needs a new name.`,
    button: running ? "Creating…" : "Create and draft the spec",
    canCreate: view.canCreate && creates && view.notesOn && !!idea.trim() && !over };
}

export function notesLeftWords(length) {
  // under 500 left, the count, in the right number (break-ui: "1 characters left")
  const left = NOTES_MAX - length;
  if (left >= 500) return null;
  if (left <= 0) return "No characters left.";
  return left === 1 ? "1 character left." : `${left.toLocaleString("en-US")} characters left.`;
}

export function projectOptions(projects, { current = null, greyed = false, quick = false } = {}) {
  // brief 26 (decision 12): enabled with zero projects; still greyed for a team that takes no --project and for Quick
  const list = projects || [];
  return { disabled: !!(greyed || quick), options: [
    { value: "", text: list.length ? "No project" : "No projects", selected: !current },
    ...list.map((p) => ({ value: p.name, text: `Project: ${p.name}`, selected: p.name === current })),
    { value: NEW_PROJECT, text: "New project…", selected: false }] };
}

export function emptyProjectWords(project) {
  if (project.handoff_lines == null) return `No tasks in ${project.name} yet. Its HANDOFF.md can't be read right now.`;
  return `No tasks in ${project.name} yet. Its HANDOFF.md (${project.handoff_lines} lines) goes with every task you send here.`;
}

export function projectToast(envelope) {
  const p = envelope && envelope.exit === 0 && envelope.project;
  if (!p) return null;
  return `${p.did === "registered" ? "Added" : "Created"} ${p.name} · ${p.folder} · HANDOFF.md ${p.handoff_lines} lines`;
}

// ---------- project files (brief 28, decision 20) ----------
// A file-mode task's card reads its `project_files` record and its calls' tests from the router's JSON; every button is a
// request the server's builder turns into one `sr` command, behind the confirm pick and cancel use. The page never runs
// git and never writes in a project.

export function testsLine(tests) {
  // the router's words for a run's tests (router/testrun.py `line`), or why none ran; null before any build
  if (!tests) return null;
  if (tests.outcome === "not_run") {
    const why = String(tests.why || "no test command").replace(/^the project has /, "");
    return `no tests run: ${why}`;
  }
  if (tests.outcome === "passed") return "tests passed";
  if (tests.outcome === "timed_out") return "tests timed out";
  return tests.exit == null ? "tests failed" : `tests failed (exit ${tests.exit})`;
}

export function changeCounts(changed) {
  const items = changed || [];
  return { count: items.length, plus: items.reduce((s, c) => s + (c.plus || 0), 0),
    minus: items.reduce((s, c) => s + (c.minus || 0), 0) };
}

const count = (n) => Number(n || 0).toLocaleString("en-US");  // 1,284, never 1284 (break-ui)
export const FILES_SHOWN = 12;  // break-ui: a 500-file change put Land 9,600 px below the card's head
export const DIFF_TABS = 8;     // more files than this: the side panel lists them in a select, not 500 tabs

export function fileWords(item) {
  // one changed file as the card lists it: its status word, then its line counts (a binary file has none)
  const counts = item.plus == null && item.minus == null ? "binary" : `+${count(item.plus)} −${count(item.minus)}`;
  return `${item.status} · ${counts}`;
}

export function diffPicker(files) {
  // how the side panel moves between a change's files: none for one, tabs for a few, a select for many
  const n = (files || []).length;
  return n <= 1 ? null : n <= DIFF_TABS ? "tabs" : "select";
}

const TASK_RUNS = ["pick", "resume", "fallback", "cancel", "split_go", "split_skip", "split_edit", "land", "undo", "discard"];

export function restoredActions(runs, actions) {
  // break-ui: after a reload the page forgot a land still running, and offered Land again. The server's runs that are
  // still going on a task come back as the card's running lines; one already known is kept as it is.
  const known = new Set((actions || []).map((a) => a.run_id));
  const found = (runs || []).filter((r) => r && r.running && !known.has(r.id) && r.on
    && TASK_RUNS.includes(r.on.action) && typeof r.on.task_id === "string")
    .map((r) => ({ run_id: r.id, taskId: r.on.task_id, display: r.display || "", started: Date.parse(r.started) || null }));
  return [...(actions || []), ...found];
}

export function actionRunView(action, now = Date.now()) {
  // a run the page started on a task: its line, and after a minute how long and what happens if the page closes
  const minutes = action && action.started ? Math.floor((now - action.started) / 60000) : 0;
  return { text: minutes >= 1 ? `Running for ${minutes} min: ${action.display}` : `Running: ${action.display}`,
    still: minutes >= 1 ? `It hasn't ended after ${minutes} min. It keeps running if you close this page; the card shows what happened when it ends.` : null };
}

const shortId = (sha) => String(sha || "").slice(0, 7);

export const SPEC_PUT_BACK_LINE = "SPEC.md was changed by the build; the router put it back (it is yours).";

export function specRestoredLine(task) {
  // brief 33.2 (decision 3): the card's line when a build's change to SPEC.md was put back (the files record says so)
  const f = task && task.project_files;
  return f && f.spec_restored ? SPEC_PUT_BACK_LINE : null;
}

export function fileView(task) {
  // The card's files block from the task's record, or null for a task with no project. `kind`: off (handoff only, its
  // why), building (the copy is there, nothing delivered yet), waiting, landed, undone, discarded, kept (a stopped or
  // failed task's copy: Discard only), empty (no file changed).
  const f = task && task.project_files;
  if (!f) return null;
  if (f.mode !== "on") return { kind: "off", tone: "muted", line: `Files: handoff only (${f.why || "file mode is off"})`,
    files: [], more: 0, all: [], tests: null, buttons: [] };  // brief 33.2 (decision 5): the router's words, "(text only, as asked)"
  const id = task.task_id;
  const running = task.status === "queued" || task.status === "sent";
  if (f.read_only && (running || !f.copy)) {  // brief 33.2 fix 1: `--no-files` reads a read-only copy; nothing can land
    return { kind: "read", tone: "muted", line: "Files: read only (answers in text)", files: [], more: 0, all: [], tests: null,
      buttons: [] };
  }
  const counts = changeCounts(f.changed);
  const counted = counts.count ? `Files: ${count(counts.count)} changed (+${count(counts.plus)} −${count(counts.minus)})` : "Files: no file changed";
  const all = (f.changed || []).map((c) => ({ path: c.path, status: c.status, words: fileWords(c) }));
  const tests = testsLine(f.tests);
  const view = { files: all.slice(0, FILES_SHOWN), more: Math.max(all.length - FILES_SHOWN, 0), all, tests, diff: f.diff || null };
  if (task.mode === "auto") return autoFileView(task, f, counted, view);  // brief 34: the run's whole change
  if (f.versus && f.candidates) {  // brief 29.1 (decisions 9 and 28): before the pick, the board shows each candidate's
    return { ...view, kind: "versus", tone: "muted", tests: null, buttons: [], files: [], more: 0,
      line: "Files: each candidate in its own copy · the one you pick waits to land; the other copy goes" };
  }
  if (f.owner) {  // brief 29 (decision 13): a piece of a project split shows its own part; only its split lands
    const part = f.run ? "this step's part; its run lands the whole change once" : "this piece's part; its split lands the whole change once";
    return { ...view, kind: "piece", tone: "muted", tests: f.run ? tests : null, buttons: [],  // brief 34: a step's tests ran
      line: counts.count ? `${counted} · ${part}` : f.run ? "Files: this step changed no file" : "Files: this piece changed no file" };
  }
  if (task.mode === "plan" && (f.state === "waiting" || task.land_anyway)) {  // brief 33.1 (decision 9): the card approves
    const paths = (f.changed || []).map((c) => c.path).filter(Boolean).join(", ");  // UI-1 row 12 (D16): the paths sent
    return { ...view, kind: "plan", tone: "info", tests: null, buttons: [],
      line: `Files: ${paths ? `${paths} · ` : ""}waits for your approval${task.land_anyway ? " (its check didn't pass)" : ""}` };
  }
  if (f.state === "waiting") {
    return { ...view, kind: "waiting", tone: "info", line: counted, note: "Ready to land: one commit on " + (f.branch || "its branch"),
      buttons: [{ key: "land", label: "Land", tone: "primary", request: { action: "land", task_id: id } },
        { key: "discard", label: "Discard", tone: "quiet", request: { action: "discard", task_id: id } }] };
  }
  if (f.state === "landed") {
    return { ...view, kind: "landed", tone: "ok", line: `Landed · ${shortId(f.commit)} · Undo`, commit: shortId(f.commit),
      buttons: [{ key: "undo", label: "Undo", tone: "", request: { action: "undo", task_id: id } }] };
  }
  if (f.state === "undone") {
    return { ...view, kind: "undone", tone: "muted", line: `Undone · ${shortId(f.undo_commit)} put back ${shortId(f.commit)}`,
      buttons: [] };
  }
  if (f.state === "discarded") return { ...view, kind: "discarded", tone: "muted", line: "Discarded: the change never landed", buttons: [] };
  if (task.waiting_on === "answers") {  // the small UI cleanup, row 5 (note 5): a wait for you, never a stop; Discard stays as it was
    return { ...view, kind: "answers", tone: "muted", line: "Files: waiting for your answers",
      buttons: f.copy ? [{ key: "discard", label: "Discard", tone: "quiet", request: { action: "discard", task_id: id } }] : [] };
  }
  const open = task.status === "queued" || task.status === "sent"
    || (task.mode === "split" && ["split_plan", "piece"].includes(task.waiting_on));  // brief 29, C4: a split still going
  // builds in its one copy; only its join's change can land, and Reject or Cancel drops the copy, never Discard
  if (open) return { ...view, kind: "building", tone: "muted", line: counts.count ? counted : `Files: a copy of ${task.project} at ${shortId(f.base)}`, buttons: [] };
  if (f.copy) {
    const discard = { key: "discard", label: "Discard", tone: "quiet", request: { action: "discard", task_id: id } };
    if (task.land_anyway) {  // brief 29.1 (decision 21): its own path, behind a confirm that lists the open musts
      return { ...view, kind: "kept", tone: "warn", line: `${counted} · its check didn't pass`,
        note: "Land anyway lands it as it is; the entry says the check didn't pass",
        buttons: [{ key: "land_anyway", label: "Land anyway", tone: "danger", request: { action: "land", task_id: id, anyway: true } },
          discard] };
    }
    return { ...view, kind: "kept", tone: "warn", line: `${counted} · can't land`,
      note: task.check_state === "blocked" ? "the check was blocked, so it can't land"
        : task.check_state === "failed" ? "the check failed, so it can't land" : "the task stopped before it was checked",
      buttons: [discard] };
  }
  return { ...view, kind: "empty", tone: "muted", line: "Files: no file changed · nothing to land", buttons: [] };
}

export function diffSections(text) {
  // changes.diff split into one section per file (`diff --git a/<path> b/<path>`), for the side panel
  const sections = [];
  let current = null;
  for (const line of String(text || "").split("\n")) {
    const m = /^diff --git a\/(.+) b\/(.+)$/.exec(line);
    if (m) {
      current = { path: m[2], lines: [line] };
      sections.push(current);
    } else if (current) current.lines.push(line);
  }
  return sections.map((s) => ({ path: s.path, text: s.lines.join("\n").replace(/\n+$/, "") }));
}

export function diffLineTone(line) {
  if (line.startsWith("+++") || line.startsWith("---")) return "meta";
  if (line.startsWith("+")) return "add";
  if (line.startsWith("-")) return "del";
  if (line.startsWith("@@")) return "hunk";
  return "";
}

export function projectTestsLine(project) {
  // the project view's line and its button
  const words = project && project.tests;
  if (!words || !words.length) return { text: "Tests: none", button: "Set", words: "" };
  return { text: `Tests: ${words.map(shellQuote).join(" ")}`, button: "Change", words: words.map(shellQuote).join(" ") };
}

// ---------- a project's Test, Run and Secrets (brief 31): the pure parts ----------

export function hourMinute(iso) {
  // "10:42" in this browser's own clock (the brief's lines: "Tests passed · 10:42", "Running since 10:42")
  const d = new Date(iso || "");
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

export function testOutcomeWords(last) {
  // the router's own words for a kept Test (router/projtest.py, `line`)
  if (!last) return "";
  if (last.outcome === "passed") return "Tests passed";
  if (last.outcome === "timed_out") return "Tests timed out";
  return last.exit == null ? "Tests failed" : `Tests failed (exit ${last.exit})`;
}

export const OWN_FOLDER = "this is the router's own folder";

export function projectTestState(project, sandbox, timeOf = hourMinute) {
  // decision 2: Test is off, with the reason, when the router would refuse it; the line is the last result and its time
  if (!project) return null;
  const last = project.last_test || null;
  const line = last ? `${testOutcomeWords(last)} · ${timeOf(last.when)}` : null;
  let off = null;
  if (!project.tests || !project.tests.length) off = "Set a test command first";
  else if (project.why === OWN_FOLDER) off = "The router's own folder: its suite is Claude Code's to run";
  else if (!project.git || !project.head) off = `Test runs the committed files: ${project.why || "no commit yet"}`;
  else if (sandbox && sandbox.available === false) off = "This Mac has no test sandbox (sandbox-exec)";
  else if (project.test_running) off = "A Test is running: its output is in the side panel";  // break-ui 3
  return { line, off, tone: !last ? "muted" : last.outcome === "passed" ? "ok" : "bad" };
}

export function runEndWords(run, timeOf = hourMinute) {
  // decision 7: "Running since 10:42", "Exited 0 at 10:45" or "Stopped at 10:45"
  if (!run || !run.state) return null;
  if (run.running) return `Running since ${timeOf(run.started)}`;
  if (run.state === "stopped") return `Stopped at ${timeOf(run.ended)}`;
  if (run.state === "exited") return run.exit == null ? `Ended at ${timeOf(run.ended)} (it could not start)` : `Exited ${run.exit} at ${timeOf(run.ended)}`;
  return "Ended (no exit was recorded)";
}

export function projectRunState(project, timeOf = hourMinute) {
  // decisions 3 and 7: the run command's button (Set or Change), Run and Stop each off with the reason, the run's line
  if (!project) return null;
  const words = project.run_command && project.run_command.length ? project.run_command : null;
  const run = project.run || null;
  const running = !!(run && run.running);
  let runOff = null;
  if (!words) runOff = "Set a run command first";
  else if (project.why === OWN_FOLDER) runOff = "The router never runs itself";
  else if (running) runOff = "A run is going: Stop it first";
  return { words: words ? words.map(shellQuote).join(" ") : "", button: words ? "Change" : "Set", line: runEndWords(run, timeOf),
    running, runOff, stopOff: running ? null : "No run is going",
    tone: running ? "info" : run && run.state === "exited" && run.exit === 0 ? "ok" : run && run.state === "exited" ? "bad" : "muted" };
}

export function runConfirmWords(doc) {
  // decision 7: Run asks once, naming the command, the folder and the .env names it will pass, never a value. Break-ui 4:
  // each in its own block (a 300-character command, a deep folder and 40 names ran together in one sentence)
  const st = (doc && doc.project && doc.project.run_status) || {};
  const command = (st.command || []).map(shellQuote).join(" ");
  const names = st.env_names || [];
  const facts = [{ label: "Command", text: command || "its run command" }, { label: "Folder", text: st.folder || "the project's folder" }];
  if (names.length) facts.push({ label: `From its .env: ${names.length === 1 ? "1 name" : `${names.length} names`} (the values are never shown)`,
    text: names.join(", "), box: true });
  return { command, folder: st.folder || "", names, facts,
    lines: ["Runs this in the project's own folder, as you would in Terminal: not in a sandbox, with no time limit."],
    after: [names.length ? "It keeps running if you close this page; Stop ends it."
      : "The project has no .env, so it gets no keys of its own. It keeps running if you close this page; Stop ends it."] };
}

export function runSheetView(project, words, { running = false, failure = null, demo = false } = {}) {
  // decision 3: the run command, kept as the test command is (one line, at most 300 characters, split as a shell would)
  const typed = String(words || "");
  const tooLong = typed.length > 300;
  return { title: `Run command for ${project ? project.name : "…"}`,
    hint: tooLong ? `${typed.length} characters; at most 300.` : "Words, as you'd type them in Terminal; the router runs them without a shell, in the project's own folder, only when you click Run.",
    hintTone: tooLong ? "bad" : "muted", canSave: !!typed.trim() && !tooLong && !running && !demo,
    canClear: !!(project && project.run_command && project.run_command.length) && !running && !demo,
    failure: failure || null, saving: running, foot: demo ? "Demo: nothing runs." : null };
}

export const SECRET_NAME = /^[A-Z_][A-Z0-9_]*$/;

export function secretCommandLine(name, key, length) {
  // decision 9: the live command line names the secret, never its value: the value goes on stdin
  return { command: `sr project secrets ${name} --set ${key || "<NAME>"}`,
    note: `(the value goes on stdin: ${Number(length || 0).toLocaleString("en-US")} characters, never shown)` };
}

export function secretsSheetView(doc, { name = "", key = "", length = 0, running = false, failure = null, demo = false } = {}) {
  // decision 9: the names in the project's .env, each set or empty; Add or Change with a password field; Remove asks once
  const found = (doc && doc.project && doc.project.secrets) || null;
  const typed = String(key || "");
  const badKey = !!typed && !SECRET_NAME.test(typed);
  const exists = !!(found || []).find((f) => f.name === typed);
  return { title: `Secrets for ${name}`, rows: (found || []).map((f) => ({ name: f.name, state: f.set ? "set" : "empty" })),
    loading: found == null, empty: found != null && !found.length,
    keyHint: badKey ? "A name is capital letters, digits and _ only, not starting with a digit (like DEMO_KEY)." : null,
    save: exists ? "Change" : "Add", canSave: !!typed && !badKey && !running && !demo,
    line: secretCommandLine(name, typed, length), failure: failure || null, foot: demo ? "Demo: nothing runs." : null };
}

export function projectOutputView(doc, what, timeOf = hourMinute) {
  // the side panel's project output (decisions 2 and 7): what runs or ran, and its text, redacted by the router; the
  // page draws it as text, escape-first, so nothing in it runs
  const record = (doc && doc.project) || {};
  if (what === "test") {
    const st = record.test_status || {};
    const head = (sha) => (sha ? ` · head ${String(sha).slice(0, 7)}` : "");
    const sub = st.running ? `Running since ${timeOf(st.started)}${head(st.head)}`
      : st.last ? `${testOutcomeWords(st.last)} · ${timeOf(st.last.when)}${head(st.last.head)}` : "No Test has run yet";
    return { title: "Test", sub, text: st.output || "", running: !!st.running,
      empty: st.running ? "No output yet." : "Test runs the tests on a throwaway copy of the committed files, in the sandbox." };
  }
  if (what === "run") {
    const st = record.run_status || {};
    return { title: "Run", sub: runEndWords(st, timeOf) || "No run yet", text: st.output || "", running: !!st.running,
      empty: st.running ? "No output yet." : "Run starts the run command in the project's own folder, with its .env, when you click it." };
  }
  return { title: what, sub: "", text: "", running: false, empty: "" };
}

export function projectFilesLine(project) {
  // what a project's view says about file mode (decision 1's card words), and whether Turn on undo is offered
  if (!project) return null;
  if (project.files_mode === "on") return { tone: "ok", text: `Files: on · ${project.branch} at ${project.head}`, turnOn: false };
  const why = project.why || "file mode is off";
  const turnOn = !project.git || /no commit yet/.test(why);
  return { tone: "muted", text: `Files: handoff only · ${why}`, turnOn: turnOn && /Turn on undo/.test(why) };
}

export function testsSheetView(project, words, { running = false, failure = null, demo = false } = {}) {
  const typed = String(words || "");
  const tooLong = typed.length > 300;
  return { title: `Tests for ${project ? project.name : "…"}`,
    hint: tooLong ? `${typed.length} characters; at most 300.` : "Words, as you'd type them; the router runs them without a shell, in its sandbox, on a throwaway copy.",
    hintTone: tooLong ? "bad" : "muted", canSave: !!typed.trim() && !tooLong && !running && !demo,
    canClear: !!(project && project.tests && project.tests.length) && !running && !demo,
    failure: failure || null, saving: running, foot: demo ? "Demo: nothing runs." : null };
}

export function gitCheckView(check, { name = "", running = false, failure = null, demo = false, waited = false } = {}) {
  // the Turn on undo sheet from the router's dry run (`sr project git --dry-run`)
  if (!check || check.name !== name) {
    return { tone: waited ? "bad" : "muted", title: waited ? "No answer" : "Checking…", lines: [], names: [], more: 0,
      canConfirm: false, failure, foot: demo ? "Demo: nothing runs." : null };
  }
  if (check.would === "refused") {
    return { tone: "bad", title: "Refused", lines: [String(check.message || "").replace(/^Would refuse: /, "").replace(/ Nothing was changed\.$/, "")],
      names: [], more: 0, canConfirm: false, failure, foot: demo ? "Demo: nothing runs." : null };
  }
  const ignore = check.gitignore || { exists: false, adds: [] };
  const lines = [`${check.files} ${check.files === 1 ? "file" : "files"} (${humanSize(check.bytes)}) go into the first commit.`,
    ignore.adds.length ? `${ignore.exists ? "Adds to" : "Makes"} .gitignore: ${ignore.adds.join(", ")}.` : ".gitignore has every line already.",
    "Nothing else in the folder changes; your .env stays out of git."];
  return { tone: "ok", title: "Ready", lines, names: check.names || [], more: check.more || 0,
    canConfirm: !running && !demo, confirm: running ? "Turning on…" : "Confirm", failure, foot: demo ? "Demo: nothing runs." : null };
}

export function dropSheetView(files, { project = null, running = false, failure = null, done = null, demo = false, refused = [] } = {}) {
  // the sheet that opens when files are dropped on a project: the list, Add (the click itself, no second confirm), the
  // router's refusal or its commit; every file the drop itself refused, by name (break-ui: only the last one showed)
  const list = (files || []).map((f) => ({ name: f.name, size: humanSize(f.size), title: f.name }));
  const no = (refused || []).length;
  const notAdded = no ? { title: `${no} ${no === 1 ? "file" : "files"} not added`, lines: refused.map((r) => `${r.name}: ${r.why}`) } : null;
  if (done) return { list, title: "Added", line: done, canAdd: false, failure: null, refused: notAdded, foot: null };
  return { list, title: `Add ${list.length} ${list.length === 1 ? "file" : "files"} to ${project || "the project"}`,
    line: "One commit holds them and HANDOFF.md. A name already in the folder is refused, never overwritten.",
    canAdd: list.length > 0 && !running && !demo, adding: running, failure: failure || null, refused: notAdded,
    foot: demo ? "Demo: nothing runs." : null };
}

export function otherFolderHint(root) {
  // decision 20c: no Terminal line for a folder kept elsewhere
  return `To use a folder from somewhere else, move it into ${root || "~/Projects"} in Finder, then type its name here.`;
}

export function newProjectGitWords(check) {
  // the dry run's answer on whether git is set up (decision 16)
  if (!check || check.would !== "create") return null;
  return check.git ? "git is set up: a first commit of .gitignore and HANDOFF.md, so changes can land."
    : "git isn't installed: the project is made without it; file work needs git (Setup, Git).";
}

export function gitSetupRow(status) {
  const git = status && status.git;
  if (!git) return { key: "git", name: "Git", tone: "muted", state: "unknown", detail: "not checked yet" };
  return git.installed ? { key: "git", name: "Git", tone: "ok", state: "installed", detail: git.version || "" }
    : { key: "git", name: "Git", tone: "bad", state: "not installed", detail: "file work needs git: see Setup, Git" };
}

// ---------- markdown (decision 10): a small renderer that never produces HTML ----------
// It turns text into a tree of plain objects; the DOM builder below makes elements from it with textContent only.
// Headings, lists, emphasis, code, tables and https:// links; never an image, never raw HTML (it stays text).

function inline(text) {
  const out = [];
  // brief 29.1 (decision 7a): `_` opens emphasis only where no letter or digit is before it and closes only where none
  // is after it, as CommonMark says, so `bed_area() … rain_needed` stays as typed; `*` may sit inside a word
  const re = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\*[^*\n]+\*|(?<![A-Za-z0-9_])_(?=\S)[^_\n]*?[^\s_]_(?![A-Za-z0-9_]))|(\[[^\]\n]+\]\([^)\s]+\))|(https:\/\/[^\s<>()]+[^\s<>().,;:!?'"])/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push({ type: "text", text: text.slice(last, m.index) });
    const s = m[0];
    if (m[1]) out.push({ type: "code", text: s.slice(1, -1) });
    else if (m[2]) out.push({ type: "strong", children: inline(s.slice(2, -2)) });
    else if (m[3]) out.push({ type: "em", children: inline(s.slice(1, -1)) });
    else if (m[4]) {
      const close = s.indexOf("](");
      const label = s.slice(1, close), href = s.slice(close + 2, -1);
      if (/^https:\/\//.test(href) && !(m.index > 0 && text[m.index - 1] === "!")) out.push({ type: "link", href, children: inline(label) });
      else out.push({ type: "text", text: s });
    } else if (m[5]) out.push({ type: "link", href: s, children: [{ type: "text", text: s }] });
    last = m.index + s.length;
  }
  if (last < text.length) out.push({ type: "text", text: text.slice(last) });
  return out;
}

function tableRow(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => inline(cell.trim()));
}

export function markdown(source) {
  const lines = String(source || "").replace(/\r\n?/g, "\n").split("\n");
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim() || /^\s*<!--.*-->\s*$/.test(line)) { i += 1; continue; }  // a comment-only line is no content
    const fence = /^( {0,4})```\s*([\w+-]*)\s*$/.exec(line);
    if (fence) {
      // a fence may sit indented under a list step: its lines lose that indent
      const indent = fence[1].length, body = [];
      i += 1;
      while (i < lines.length && !/^ {0,4}```\s*$/.test(lines[i])) {
        body.push(lines[i].replace(new RegExp(`^ {0,${indent}}`), ""));
        i += 1;
      }
      blocks.push({ type: "pre", lang: fence[2] || null, text: body.join("\n") });
      i += 1;
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) { blocks.push({ type: `h${heading[1].length}`, children: inline(heading[2].trim()) }); i += 1; continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { blocks.push({ type: "hr" }); i += 1; continue; }
    if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const head = tableRow(line), rows = [];
      i += 2;
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { rows.push(tableRow(lines[i])); i += 1; }
      blocks.push({ type: "table", head, rows });
      continue;
    }
    if (/^\s*>\s?/.test(line)) {
      const body = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) { body.push(lines[i].replace(/^\s*>\s?/, "")); i += 1; }
      blocks.push({ type: "blockquote", children: inline(body.join(" ")) });
      continue;
    }
    const bullet = /^\s*([-*+]|\d+[.)])\s+/;
    if (bullet.test(line)) {
      const ordered = /^\s*\d/.test(line), items = [];
      const first = ordered ? parseInt(line, 10) : 1;  // UI A N7 (A11): text between two items must not restart the count
      while (i < lines.length && bullet.test(lines[i]) && /^\s*\d/.test(lines[i]) === ordered) {
        items.push(inline(lines[i].replace(bullet, "")));
        i += 1;
      }
      blocks.push(first === 1 ? { type: ordered ? "ol" : "ul", items } : { type: "ol", items, start: first });
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^( {0,4}```|#{1,4}\s|\s*>|\s*([-*+]|\d+[.)])\s+|\s*<!--.*-->\s*$)/.test(lines[i])) {
      para.push(lines[i]);
      i += 1;
    }
    if (!para.length) { para.push(line); i += 1; }
    blocks.push({ type: "p", children: inline(para.join("\n")) });
  }
  return blocks;
}

// ---------- a task card's parts, from the log row and `sr show --json` ----------

const ROLE_WORDS = { do: "build", check: "check", fix: "fix", recheck: "re-check", execute: "build", split_plan: "plan",
  integrate: "join", research: "research", build: "build", review: "review", attack: "attack", revise: "revise",
  vote: "vote", plan: "plan", amend: "amend", edit: "edit" };

export function roleWords(role) {
  const base = String(role || "").replace(/^reask-/, "");
  const word = ROLE_WORDS[base] || ROLE_WORDS[base.split("-")[0]] || base.replace(/_/g, " ");
  return String(role || "").startsWith("reask") ? `${word} re-ask` : word;
}

export function elapsed(fromIso, toIso) {
  const from = Date.parse(fromIso), to = Date.parse(toIso);
  if (Number.isNaN(from) || Number.isNaN(to) || to < from) return null;
  const s = Math.round((to - from) / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

export function stagesView(task, show) {
  const stages = [];
  if (task.mode !== "relay" && task.mode !== "split" && task.jev && task.jev.status !== "not_asked") {
    stages.push({ key: "jev", label: task.jev.label ? `Jev → ${task.jev.label}` : "Jev", agent: null,
      state: task.jev.status === "ok" ? "ok" : "warn", file: null });
  }
  for (const call of (show && show.calls) || []) {
    const role = call.kind === "stage" || call.kind === "reask" ? call.role : call.kind;
    const said = call.kind === "reask" ? `${roleWords(role)} re-ask` : roleWords(role);
    const label = call.reason_code === "skipped" ? `${said} skipped` : said;  // brief 32: said, not only shown
    const state = call.reason_code === "skipped" ? "skip"  // brief 32 (decision 11): the second attack, skipped; the chain went on
      : call.status === "sent" ? "live" : call.status === "done" ? (call.verdict === "FIX" ? "warn" : "ok")
      : call.status === "failed" ? "bad" : "warn";
    stages.push({ key: call.call_id, label, agent: call.agent, state, file: call.round_file || null,
      verdict: call.verdict || null, reason: call.reason_code || null });
  }
  return stages;
}

// ---------- the small UI cleanup, row 2 (note 27): one pill per step, built on stagesView, which stays as it is ----------

const PILL_TONES = { done: "ok", running: "info", found: "warn", failed: "bad", stopped: "warn", skipped: "muted", not_started: "muted",
  blocked: "warn", unreadable: "warn", timed_out: "warn", unknown: "muted" };
const PILL_ENDS = { running: ", running", found: ", found issues", failed: ", failed", stopped: ", stopped", skipped: ", skipped",
  blocked: ", blocked", unreadable: ", unreadable", timed_out: ", timed out" };
const STOPPED_REASONS = ["plan_limit", "process_ended"];

function stepName(task, words) {
  // "attack2 re-ask" reads "Attack re-ask"; a quick answer's do reads Answer
  const said = String(words || "").replace(/ skipped$/, "").replace(/\d+(?=$| )/, "");
  return capital(task.skill === "quick_answer" && said === "build" ? "answer" : said);
}

function pillOf(key, name, agent, state, marked = state === "done" || state === "failed") {
  const mark = !marked ? "" : state === "failed" ? "✗ " : "✓ ";
  const who = agent ? ` · ${agentLabel(agent)}` : "";
  return { key, state, tone: PILL_TONES[state], text: state === "not_started" ? `${name} · not started` : `${mark}${name}${who}${PILL_ENDS[state] || ""}` };
}

function pillState(stage, ended) {
  if (stage.state === "skip") return "skipped";
  if (stage.state === "live") return ended ? "stopped" : "running";  // my call: a sent row on an ended task isn't running
  if (stage.state === "bad") return STOPPED_REASONS.includes(stage.reason) ? "stopped" : "failed";
  if (stage.verdict === "FIX") return "found";
  if (stage.state === "warn") return "timed_out";  // stagesView's warn with no FIX: the one other call status
  return stage.verdict === "BLOCKED" ? "blocked" : stage.verdict === "unreadable" ? "unreadable" : "done";
}

function routedSteps(task) {
  // a routed task's two steps, from the record: `agent` and `checker` name them
  return task.agent ? [{ stage: null, role: "do", agent: task.agent }, ...(task.checker ? [{ stage: null, role: "check", agent: task.checker }] : [])] : [];
}

function nowMatches(step, now) {
  if (step.stage != null) return now.stage === step.stage;
  return step.role === "do" ? now.kind === "do" : ["check", "fix", "recheck"].includes(now.kind);
}

function unreadPills(task, steps, now) {
  // no details read yet: the record's agents in grey; ✓ only when the outcome says so. The step in progress is known from `now`
  const marked = task.outcome === "passed" || task.outcome === "fixed";
  const at = now ? steps.findIndex((step) => nowMatches(step, now)) : -1;
  return steps.flatMap((step, i) => {
    const name = stepName(task, roleWords(step.role));
    if (now && i === at) return [pillOf(`step-${i}`, stepName(task, roleWords(now.role || now.kind)), now.agent, "running")];
    if (at >= 0 && i > at) return [pillOf(`step-${i}`, name, null, "not_started")];
    return [pillOf(`step-${i}`, name, step.agent, "unknown", marked)];
  });
}

export function stepPills(task, show) {
  // One pill per step with its state: what ran (stagesView), the call in progress (`steps.now`, which has no row yet) and the steps
  // not started. Never on Auto, or for Jev. Pills aren't buttons: each step's round file stays in Details.
  if (!task || task.mode === "auto" || task.auto) return [];
  const routed = !["relay", "split", "plan"].includes(task.mode);
  const steps = ((task.steps && task.steps.chain) || (routed ? routedSteps(task) : []))
    .filter((step) => step.role !== "check" || task.outcome !== "unchecked");  // the why line says why it had no check
  const now = (task.steps && task.steps.now) || null;
  const nothing = task.waiting_on === "needs_label" || task.outcome === "returned";
  const answered = task.no_split || task.one_step;  // my call: those answers end the chain, so no steps not started
  if (!show) return nothing ? [] : unreadPills(task, answered ? steps.slice(0, 1) : steps, now);
  const calls = show.calls || [];
  if (nothing && !calls.length) return [];
  const running = now ? [...calls, { call_id: "now", kind: now.kind, stage: now.stage, role: now.role, agent: now.agent, status: "sent" }] : calls;
  const ended = !isOpenTask(task);
  const pills = stagesView(task, { calls: running }).filter((s) => s.key !== "jev")
    .map((s) => pillOf(s.key, stepName(task, s.label), s.agent, pillState(s, ended)));
  if (answered) return pills;
  const ran = (step) => (step.stage != null
    ? running.some((c) => (c.kind === "stage" || c.kind === "reask") && c.stage === step.stage)
    : step.role === "do" ? running.some((c) => c.kind === "do")
      : running.some((c) => ["check", "recheck", "fix"].includes(c.kind)));
  return [...pills, ...steps.filter((step) => !ran(step)).map((step, i) => pillOf(`todo-${i}`, stepName(task, roleWords(step.role)), null, "not_started"))];
}

// The waits that are your turn (router/state.py WAITING_ON): the agents are done until you answer.
export const YOUR_TURN = ["needs_label", "split_plan", "pick", "vote_pick", "land",  // brief 28: a change waits to land
  "answers"];  // brief 33.4 (decision 5): a plan that asked its questions

export function receiptView(task, show, now = new Date().toISOString()) {
  const pills = [];
  if (task.mode === "relay" || task.mode === "split") pills.push({ text: "Jev not asked: team chosen" });
  else if (task.skill_source === "owner") pills.push({ text: "your label: ", value: task.skill || "-" });
  else if (task.skill === FOLLOW_UP) {  // brief 29.1 (decision 24): Jev's label kept, the router's route named
    pills.push({ text: followUpWords(task.agent) });
    if (task.jev && task.jev.label) {
      pills.push({ text: `Jev → ${task.jev.label} `, value: task.jev.confidence == null ? "" : Number(task.jev.confidence).toFixed(2) });
    }
  } else if (task.jev && task.jev.label) {
    pills.push({ text: `Jev → ${task.jev.label} `, value: task.jev.confidence == null ? "" : Number(task.jev.confidence).toFixed(2) });
  }
  if (task.tag && show) {
    const n = (show.memory_given || []).length;
    const build = (show.calls || []).find((c) => c.memory) || null;  // the first call: its record is the fresh one
    const off = !!(build && build.memory && build.memory.state === "off");
    pills.push({ text: "memory: ", value: off ? "off" : n ? `${n} ${n === 1 ? "entry" : "entries"}` : "none yet" });
  }
  if (show && show.handoff) pills.push({ text: "handoff: ", value: show.handoff.left_out ? "left out (Grok)" : show.handoff.attached ? "attached" : "not sent yet" });
  if (task.mode === "relay" && task.slots) {
    for (const [slot, agent] of Object.entries(task.slots)) pills.push({ text: `${slot} `, value: agent ? agentLabel(agent) : "left out" });
  } else {
    if (task.agent) pills.push({ text: "build: ", value: agentLabel(task.agent) });
    if (task.checker) pills.push({ text: "check: ", value: agentLabel(task.checker) });
  }
  const rounds = ((show && show.calls) || []).filter((c) => c.kind === "check" || c.kind === "recheck").length;
  const running = isOpenTask(task) && !YOUR_TURN.includes(task.waiting_on);
  const time = elapsed(task.created_at, running ? now : task.updated_at);
  if (rounds || time) pills.push({ text: [rounds ? `${rounds} round${rounds === 1 ? "" : "s"}` : null, time].filter(Boolean).join(" · ") });
  if (task.web) pills.push({ text: "web search on files" });
  return pills;
}

export function checkView(task, show) {
  const checker = agentLabel(task.checker);
  const stored = show && (show.memory_stored || []).some((m) => m.document_id);
  const original = show && show.original_file && show.original_file !== show.result_file ? show.original_file : null;
  const given = !!(show && ((show.memory_given || []).length || show.handoff));
  const savedWords = stored ? (task.project ? " · saved to this project's memory" : " · saved to this chat's memory") : "";
  if (isOpenTask(task)) {
    if (task.waiting_on) return null;
    return { tone: "info", title: "Working", detail: task.working && task.working.doing ? `${agentLabel(task.working.agent)} · ${task.working.doing}` : "", original: null, given };
  }
  const tally = show && show.tally;
  switch (task.outcome) {
    case "passed":
      if (tally) return { tone: "ok", title: `${(show.votes || []).find((v) => v.letter === tally.winner)?.answer || "Agreed"}, ${tally.for} of ${tally.for + tally.against}`, detail: `the vote is the check${savedWords}`, original: null, given };
      return { tone: "ok", title: "Checker passed", detail: `${checker}, round 1${savedWords}`, original, given };
    case "fixed": return { tone: "ok", title: "Passed after one fix", detail: `${checker}${savedWords}`, original, given };
    case "picked": return { tone: "ok", title: task.result ? `You picked ${(show && show.pick || "").toUpperCase()}` : "Closed with no pick", detail: task.check_note || "", original: null, given };
    case "unchecked": return { tone: "muted", title: "Unchecked", detail: task.skill === "quick_answer" ? "a quick answer needs no check" : (task.check_note || "the check did not run"), original: null, given };
    case "failed_check": return { tone: "bad", title: "The check failed twice", detail: task.check_note || "", original, given };
    case "tie": return { tone: "warn", title: "A tie, then your pick", detail: "delivered unchecked: no two agents agreed", original: null, given };
    case "cancelled": return { tone: "muted", title: "Cancelled", detail: "", original: null, given };
    case "timed_out": return { tone: "muted", title: "Timed out", detail: task.check_note || "", original: null, given };
    case "returned": return { tone: "muted", title: "Came back to you", detail: task.check_note || task.route_reason || "", original: null, given };
    default: return { tone: "bad", title: stateWords(task), detail: task.check_note || "", original: null, given };
  }
}

export function demoClock(tasks, status) {
  // The demo is a snapshot: its clock is when its status was taken (or its newest row), so a working task's timer
  // counts to then, never to today, and agrees with the router's Grok note on it
  const stamps = [...(tasks || []).map((t) => t.updated_at), ...((status && status.agents) || []).map((a) => a.checked_at)];
  return stamps.filter(Boolean).reduce((max, s) => (s > max ? s : max), "");
}

export function resultHeading(task) {
  // what the result is: a delivered answer, the furthest a double fail got, or what the router kept at a stop
  const who = [agentLabel(task.agent), task.skill || (task.preset ? teamLabel(task.preset) : null)].filter(Boolean).join(" · ");
  if (task.outcome === "failed_check") return `${who} · the furthest result: after the fix, and its re-check failed`;
  if (["plan_limit", "process_ended", "stopped", "timed_out", "cancelled"].includes(task.outcome)) return "What the router kept when it stopped";
  return who;
}

export function resultShown(task) {
  // brief 29 (decision 3): a No split answer's line is on its own grey card; the row's stored "no split: …" isn't shown
  // again under it as what the router kept at a stop. Brief 33.1 (decision 6, break-ui): nor a One step answer's
  return !!(task && task.result && !task.no_split && !task.one_step);
}

export const PREVIEW_CHARS = 20000;

export function resultPreview(text, limit = PREVIEW_CHARS) {
  // a huge result (a 2 MB export) shows its first `limit` characters on the card, cut at a line; Show all opens the
  // whole of it beside, so a poll never parses and draws megabytes into the stream (break-ui, 21 Oct)
  const whole = String(text || "");
  if (whole.length <= limit) return { text: whole, cut: false };
  const at = whole.lastIndexOf("\n", limit);
  return { text: whole.slice(0, at > limit * 0.8 ? at : limit), cut: true };
}

// ---------- brief 32.1: the stream head stays at the top; a result shows whole ----------

export const HEAD_GAP = 12;  // the space between the stuck head and the top of a card jumped to
export const FOLD_SHARE = 1 / 3;  // the most of the window's height the head takes before a project's bar folds

export function streamTop(stripHeight, headHeight) {
  // where the stuck head ends: the strip's height and the head's own
  return (stripHeight || 0) + (headHeight || 0);
}

export function cardMargin(stripHeight, headHeight) {
  // a card scrolled to (a link, Needs you, a refusal shown) lands just below the head, in whole pixels
  return Math.ceil(streamTop(stripHeight, headHeight) + HEAD_GAP);
}

export function foldsTools(headHeight, viewportHeight, { open = false } = {}) {
  // a project's bar folds into Project tools where the head would take more than about a third of the window; opened,
  // it stays open
  return !open && headHeight > viewportHeight * FOLD_SHARE;
}

export const HOLD_MS = 5000;  // how long a card jumped to keeps its place while its details load

export function anchorChoice({ changed, follow, nearEnd, held }) {
  // what the next refresh keeps in place: a new view starts at its end; a card just jumped to keeps its top (it may still
  // be growing as its details load, and following the end would push it under the head: break-ui); else the end when
  // you were at it, else the card you were reading
  if (changed) return "end";
  if (held) return "held";
  return follow && nearEnd ? "end" : "reading";
}

export function heldTop({ top, line, atEnd }) {
  // where a held card's top goes on the next refresh: where it is, unless the jump stopped at the page's end below its
  // place (D, 29 Oct: the page was still too short while the card's details loaded); then its place, just below the head
  return atEnd && top > line ? line : top;
}

export function projectToolsView({ folds, open }) {
  // folded, the bar is one Project tools button that opens it in place; a drop goes to whichever of the two is shown
  if (!folds) return { button: null, bar: true, drop: "bar" };
  return { button: { label: "Project tools", expanded: !!open }, bar: !!open, drop: open ? "bar" : "button" };
}

export function resultView(text) {
  // decision 4: a result shows whole up to PREVIEW_CHARS; past it, its first part, whole and in no box (the design chat's
  // D fix 5, 29 Oct), then Show all … beside: the limit keeps megabytes out of the stream, nothing more
  const whole = String(text || "");
  const preview = resultPreview(whole);
  return { text: preview.text, cut: preview.cut, beside: preview.cut ? `Show all ${humanSize(whole.length)} beside` : null };
}

export function middleTruncate(name, max = 40) {
  // a file name keeps its start, its end and its extension: versions differ at the end (break-ui, 21 Oct)
  const s = String(name || "");
  if (s.length <= max) return s;
  const dot = s.lastIndexOf(".");
  const ext = dot > 0 && s.length - dot <= 8 ? s.slice(dot) : "";
  const keep = max - 1 - ext.length;
  const head = Math.ceil(keep * 0.55);
  return `${s.slice(0, head)}…${s.slice(s.length - ext.length - (keep - head))}`;
}

export function fileCards(files) {
  return (files || []).filter((f) => f.root !== "tasks").map((f) => {
    const what = f.root === "media/in" ? "input" : f.root === "media/out" ? "made by Grok"
      : f.root === "media/pages" ? "PDF page" : f.root === "media/frames" ? "video still" : f.root;
    return { path: f.path, name: f.name, kind: f.kind, meta: `${what} · ${humanSize(f.size)}` };
  });
}

export function pdfShots(pdf, files) {
  // brief 24 (decision 17): a PDF's own page images, from its folder (its stem, or its whole name when two PDFs share a
  // stem); a task from before has one flat pages folder
  const stem = pdf.name.replace(/\.[^.]*$/, "");
  const pages = (files || []).filter((f) => f.root === "media/pages" && f.kind === "image");
  const own = pages.filter((f) => f.folder === pdf.name);
  const found = own.length ? own : pages.filter((f) => f.folder === stem);
  return found.length || pages.some((f) => f.folder) ? found : pages.filter((f) => !f.folder);
}

export function roundName(file) {
  if (file && file.round) return `${String(file.round.order).padStart(2, "0")} · ${roleWords(file.round.role)} · ${agentLabel(file.round.agent)}`;
  return file ? file.name : "";
}

export function humanSize(bytes) {
  const n = Number(bytes) || 0;
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

// ---------- needs you, the stop offers, the boards and memory (D) ----------
// Every button here is a request the server's builder turns into one `sr` command; each shows only when the JSON
// offers it (the rescue offers come from the row's `fallback` and `resume`, never worked out here).

export function demoCommand(request) {
  // The demo answers every POST with "Demo: nothing runs.", /api/command included, so its confirms show this preview,
  // shaped like the builder's Copy (decision 4). The real page always shows the server's.
  const id = request.task_id;
  switch (request.action) {
    case "pick": return `sr pick ${id} ${request.choice}`;
    case "land": return `sr land ${id}${request.anyway ? " --anyway" : ""}`;  // brief 29.1 (decision 21)
    case "cancel": case "resume": case "fallback": case "undo": case "discard": return `sr ${request.action} ${id}`;
    case "project_git": return `sr project git ${request.name}`;
    case "project_tests": return request.clear ? `sr project tests --clear ${request.name}` : `sr project tests ${request.name} -- ${shellQuote(request.words || "")}`;
    case "project_files": return [`sr project files ${request.name}`, ...(request.files || []).map((f) => `--file ${shellQuote(f)}`)].join(" ");
    case "check": return "sr check";
    case "split_skip": return `sr split --skip ${id}`;
    case "plan_edit": return [`sr plan --edit ${id} --step ${request.step}`, request.change === "team" ? `--team ${request.value}`
      : request.change === "text" ? `--text -- ${shellQuote(request.value || "")}`
        : request.change === "done_when" ? `--done-when -- ${shellQuote(request.value || "")}`
          : request.change === "covers" ? `--covers -- ${shellQuote(request.value || "")}` : `--${request.change}`].join(" ");  // 33.1; 33.2
    case "split_edit": return [`sr split --edit ${id} --piece ${request.piece}`, request.team != null ? `--team ${request.team}` : null,
      request.text != null ? `-- ${shellQuote(request.text)}` : null].filter(Boolean).join(" ");  // brief 29
    case "split_go": return [`sr split --go ${id} --answer ${request.choice}`,
      ...Object.entries(request.skills || {}).map(([k, v]) => `--skill ${k}=${v}`)].join(" ");
    case "floor": return `sr route --skill ${request.skill} --answers ${request.answers} -- ${shellQuote(request.text)}`;
    // brief 30: a notes text by its length, as the builder shows it (decision 10); break-ui found these lines empty
    case "notes_save": return `sr notes save --expect ${request.expect} -- <the notes, ${count(charCount(request.text))} characters>`;
    case "project_notes_save": return `sr project notes ${request.name} --save --expect ${request.expect} -- <the notes, ${count(charCount(request.text))} characters>`;
    case "project_spec_save": return `sr project spec ${request.name} --save --expect ${request.expect} -- <the spec, ${count(charCount(request.text))} characters>`;  // 33.2
    case "project_pin": return `sr project pin ${request.name} --task ${id} -- <the text, ${count(charCount(request.text))} characters>`;
    case "project_save": return `sr project save ${request.name} --task ${id} --path ${shellQuote(request.path || "")}`;
    case "forget": return `sr forget ${id}${request.undo ? " --undo" : ""}`;
    // brief 33.3 (decisions 6 and 12): Setup's selects and the Fable switch
    case "models_set": return `sr models set ${modelsSelectorWords(request)} --agent ${request.agent} --model ${request.model}`;
    case "models_clear": return `sr models clear ${modelsSelectorWords(request)} --agent ${request.agent}`;
    case "models_fable": return `sr models fable ${request.to}`;
    default: return "";
  }
}

export function needsConfirm(request) {
  // rules (Interface): a pick, a skip, a cancel, a split's run and a `none` each ask once; a split's Reject too (the owner,
  // 21 Oct: it closes the plan and can't be undone; a 2.33 line); nothing else does
  if (!request) return false;
  return ["pick", "split_skip", "cancel", "split_go", "land", "undo", "discard"].includes(request.action);  // brief 28: the three
}

export function jevWords(jev, floor) {
  // Terminal's words for Jev's answer (router `_jev_text`), shorter
  if (!jev) return "";
  const conf = typeof jev.confidence === "number" ? jev.confidence.toFixed(2) : "-";
  const at = typeof floor === "number" ? ` · the floor is ${floor.toFixed(2)}` : "";
  switch (jev.status) {
    case "below_floor": return `Jev said ${jev.label || "-"} at ${conf}${at}`;
    case "none_of_these": return "Jev found no skill that fits";
    case "over_cap": return "Jev wasn't asked: this month's tokens are used up";
    case "error": return `Jev couldn't label it${jev.error ? ` (error: ${jev.error})` : ""}`;
    case "not_set_up": return "Jev isn't set up: pick the skill";  // brief 24 (decision 13)
    default: return jev.label ? `Jev said ${jev.label} at ${conf}` : "";
  }
}

export function floorView(task, status) {
  if (!task || task.waiting_on !== "needs_label") return null;
  const keys = ((status && status.skills) || []).map((s) => s.key);
  const guess = task.jev && task.jev.label;
  const ordered = guess && keys.includes(guess) ? [guess, ...keys.filter((k) => k !== guess)] : keys;
  return {
    title: task.jev && task.jev.status === "not_set_up" ? "Jev isn't set up" : "Jev wasn't sure which skill",
    sub: jevWords(task.jev, status && status.jev ? status.jev.floor : null),
    // decision 12: the row's text with --skill and --answers, nothing else; the router takes the tag, web and files
    skills: ordered.map((key) => ({ key, guess: key === guess,
      request: { action: "floor", skill: key, answers: task.task_id, text: task.text } })),
    cancel: { action: "cancel", task_id: task.task_id },
  };
}

export function sendAsView(task, status) {
  // Brief 29.1 (decision 3; brief 28's issue 12): a task that came back because Jev's label is a skill version 2 doesn't
  // route offers the skills it does route, as the floor card does; a chip sends the row's text again with --skill and
  // --answers (the router takes its tag, --web and files). Once answered, nothing.
  if (!task || task.status !== "returned" || task.reason_code !== "not_routed" || task.answered_by) return null;
  const skills = ((status && status.skills) || []).filter((s) => s.routed !== false).map((s) => s.key);
  const label = task.jev && task.jev.label;
  return {
    title: `Jev labeled it ${label || "a skill"}, which version 2 doesn't route`,
    sub: "Send it again as another skill: the same text, tag and files, as a new task; this row keeps Jev's label.",
    skills: skills.map((key) => ({ key, request: { action: "floor", skill: key, answers: task.task_id, text: task.text } })),
  };
}

export const FOLLOW_UP = "follow_up";  // brief 29.1 (decision 24): the router's route for a tagged task Jev isn't sure of

export function followUpWords(agent) {
  return `follow-up: ${agentLabel(agent)}, with memory`;
}

function routeWords(route) {
  if (!route) return "";
  if (route.skill === FOLLOW_UP && route.agent) return followUpWords(route.agent);  // decision 24: the plan card's words
  const check = route.checker ? `${agentLabel(route.checker)} checks` : "no check";
  return [`${route.skill} · ${agentLabel(route.agent)}, ${check}`, route.comes_back ? `comes back: ${route.comes_back}` : null]
    .filter(Boolean).join(" · ");
}

// ---------- split on the page (brief 29, decisions 1, 3, 7, 8, 10, 17 and 18) ----------
// Every team, count, state and refusal comes from the JSON (`sr show --json`'s pieces, `estimate` and `menu`); the page
// words them and builds the one request each control sends, never more.

export const PICK_MARKS = { pick: "needs your pick", tie: "a tie needs your pick" };
export const PIECE_MAX = 399;  // the router's piece rule (under 400 characters), shown as a counter; the router decides

export function countLine(estimate) {
  if (!estimate) return null;
  const word = estimate.calls === 1 ? "call" : "calls";
  const most = estimate.max_calls > estimate.calls ? `, up to ${estimate.max_calls} with fix rounds` : "";
  return `About ${estimate.calls} agent ${word} from here${most}.`;
}

export function jevLabelsLine(estimate) {
  if (!estimate) return null;
  return `Jev: ${estimate.jev_labels} label${estimate.jev_labels === 1 ? "" : "s"} so far; an edited text adds one`;
}

export function jevPieceWords(jev, team) {
  if (!jev) return null;
  const words = jev.label ? `Jev: ${jev.label} ${jev.confidence == null ? "" : Number(jev.confidence).toFixed(2)}`.trim()
    : jev.status === "not_set_up" ? "Jev isn't set up" : "Jev couldn't label it";
  return team && team !== "route" ? `${words}, not used: ${team} names its own agents` : words;
}

export function projectLine(task) {
  // decision 12: the one copy and the one land, or the handoff-only reason
  if (!task || !task.project) return null;
  const found = task.project_files || null;
  if (found && found.mode === "on") return `On ${task.project} · one copy · you land once at the end`;
  return `On ${task.project} · handoff only (${(found && found.why) || "no copy"})`;
}

export function splitEditRequest(task, piece, { team, text, slots } = {}) {
  const request = { action: "split_edit", task_id: task.task_id, piece };
  if (team != null) request.team = team;
  if (text != null) request.text = text;
  if (slots != null) request.slots = slots;  // brief 29.1 (decision 12)
  return request;
}

export function pieceSlots(task, piece, team, presets) {
  // brief 29.1 (decision 12): each slot of a preset piece as a select: the agents status says the slot allows, the
  // default marked, the one it runs with chosen; a change is `split_edit` with that slot (`default` puts it back)
  const preset = (presets || []).find((p) => p.name === team);
  const map = piece.slot_map || null;
  if (!preset || team === "route" || !map) return [];
  return (preset.slots || []).map((slot) => {
    // brief 32: a slot the router leaves out (the second attack without Cursor) is null in the map, and reads Left out
    const agent = slot.name in map ? map[slot.name] || "" : slot.default;
    const allowed = [...new Set([...(agent ? [] : [""]), ...(slot.allowed || []), ...(agent ? [agent] : [])])];
    return { name: slot.name, agent, default: slot.default, set: !!(piece.slots || {})[slot.name],
      options: allowed.map((a) => ({ agent: a, label: a ? `${agentLabel(a)}${a === slot.default ? " (default)" : ""}` : "Left out" })),
      request: (value) => splitEditRequest(task, piece.piece, { slots: { [slot.name]: value === slot.default || !value ? "default" : value } }) };
  });
}

export function splitPlanView(task, show, ui = {}) {
  if (!task || task.waiting_on !== "split_plan" || !show || !show.pieces) return null;
  const editing = ui.editing && ui.editing.taskId === task.task_id ? ui.editing : null;
  const menu = show.menu || [];
  const pieces = show.pieces.map((p) => {
    const team = p.team || "route";
    const options = menu.map((t) => ({ name: t.name, disabled: t.ready === false && t.name !== team, why: t.ready === false ? t.why : null }));
    if (!options.some((o) => o.name === team)) options.unshift({ name: team, disabled: true, why: "not on this split's menu now" });
    const words = team !== "route" ? (p.chain || "can't run now")
      : p.needs_label ? `Jev left it under the floor (${p.jev && p.jev.label ? `${p.jev.label} at ${Number(p.jev.confidence).toFixed(2)}` : "no label"}): pick its skill`
        : routeWords(p.route);
    const edit = editing && editing.piece === p.piece ? {
      text: editing.text, length: editing.text.length, tooLong: editing.text.length > PIECE_MAX,
      count: `${editing.text.length} of ${PIECE_MAX} characters · saving labels it again (one Jev label)`,
      unchanged: editing.text === p.text,
      save: splitEditRequest(task, p.piece, { text: editing.text }) } : null;
    return { piece: p.piece, text: p.text, edited: p.edited, team, options, words, edit,
      slots: pieceSlots(task, p, team, ui.presets),  // brief 29.1 (decision 12): a preset piece's agents, one select each
      changedFrom: p.team_source === "owner" ? p.planner_team : null, why: p.team_why || null,
      jev: team === "route" && p.needs_label ? null : jevPieceWords(p.jev, team),  // C4: the floor line names Jev once
      jevLabel: team === "route" && p.needs_label ? null : (p.jev && p.jev.label) || null,  // UI A row 16: the line read first
      mark: PICK_MARKS[p.needs_you] || null,
      refused: p.refused ? p.refused.reason : null, needsLabel: team === "route" && !!p.needs_label };
  });
  const choices = ui.choices || {};
  const missing = pieces.filter((p) => p.needsLabel && !choices[p.piece]).map((p) => p.piece);
  const refused = pieces.find((p) => p.refused);
  const off = editing ? `Save or cancel piece ${editing.piece}'s edit to approve`
    : ui.running ? "A change to the plan is running"
      : refused ? `Piece ${refused.piece} can't run: ${refused.refused}`
        : missing.length ? `Pick a skill for piece ${missing.join(" and ")} first` : null;
  return { title: "A split plan is waiting", sub: `${pieces.length} pieces · nothing runs until you approve`, pieces,
    join: show.join || null, joiner: agentLabel(task.agent), checker: task.checker ? agentLabel(task.checker) : null,
    project: projectLine(task), count: countLine(show.estimate), jevLine: jevLabelsLine(show.estimate),
    approveOff: off, rejectOff: editing ? `Save or cancel piece ${editing.piece}'s edit first` : ui.running ? off : null,
    reject: { action: "split_go", task_id: task.task_id, choice: "n" } };
}

export function pieceReadLine(piece) {
  // UI A row 16 (A18): a piece read first: its team, Jev's label and the mark, after its text, on one line
  return [piece.team, piece.jevLabel ? `Jev label: ${piece.jevLabel}` : piece.jev, piece.mark].filter(Boolean).join(" · ");
}

export function splitApprove(task, show, choices = {}) {
  const under = ((show && show.pieces) || []).filter((p) => p.needs_label && (p.team || "route") === "route");
  const missing = under.filter((p) => !choices[p.piece]).map((p) => p.piece);
  const skills = Object.fromEntries(under.filter((p) => choices[p.piece]).map((p) => [String(p.piece), choices[p.piece]]));
  return { missing, request: { action: "split_go", task_id: task.task_id, choice: "y", skills } };
}

export const PART_SHOWN = 6;  // C4 (/break-ui): a piece's line shows its first files; its own card shows them all

export function partWords(changed) {
  // decision 18b: a piece's part of the change, one chip per file: `calc.py +3 −1`, `mathx.py +6`; a count of 0 is left
  // out (C4: `a +0 −1`), a deleted file says so
  return (changed || []).map((c) => {
    const plus = c.plus ? ` +${c.plus}` : "";
    const minus = c.minus ? ` −${c.minus}` : "";
    return c.status === "deleted" ? `${c.path} deleted${minus}` : `${c.path}${plus}${minus}`;
  });
}

export function piecesView(task, show) {
  if (!task || task.mode !== "split" || task.waiting_on === "split_plan" || !show || !show.pieces) return null;
  return show.pieces.map((p) => {
    const waitingPick = p.piece_state === "waiting" && /pick/.test(p.why || "");
    const words = p.piece_state === "blocked" ? `blocked: ${p.why}` : p.piece_state === "waiting" ? (p.why || "waiting")
      : p.piece_state === "done" ? (p.outcome || "done") : p.piece_state || "not started";
    const part = p.project_files ? partWords(p.project_files.changed) : [];
    return { piece: p.piece, n: p.n, task_id: p.task_id, text: p.text, team: p.team || "route", state: p.piece_state, words,
      part: part.slice(0, PART_SHOWN), more: Math.max(part.length - PART_SHOWN, 0),
      skip: task.waiting_on === "piece" && p.piece_state === "blocked" ? { action: "split_skip", task_id: p.task_id } : null,
      open: waitingPick && p.n ? { task_id: p.task_id, n: p.n } : null };
  });
}

export function pieceMark(state) {
  // UI A row 7 (A18): ✓ delivered, ● out or held (the words beside it say which), ○ not started or skipped
  return state === "done" ? "✓" : state === "waiting" || state === "blocked" ? "●" : "○";
}

export function routeItState(made, tasks) {
  // brief 29.1 (decision 7d): once Route it has sent, it stays off and the card names the task it made
  if (!made) return null;
  const task = made.task_id ? (tasks || []).find((t) => t.task_id === made.task_id) : null;
  if (task) return { off: `Sent as #${task.n}`, label: "Sent", line: `Routed as #${task.n}`, taskId: task.task_id };
  return { off: "Sent: the new task is starting", label: "Sent", line: "Routed: the new task is starting", taskId: null };
}

// ---------- brief 33.1: the plan card and the One step card (decisions 6, 10 and 11) ----------

export const STEP_MAX = 399;  // a step's text is under 400 characters; the router decides
export const DONE_MAX = 299;  // a step's finish line, under 300
export const COVERS_MAX = 120;  // brief 33.2 (decision 6): a step's `covers:` labels, a short line

export function planCallWords(calls, most) {
  if (calls == null) return null;
  return most > calls ? `${calls} to ${most} calls` : `${calls} call${calls === 1 ? "" : "s"}`;
}

export function planCountLine(estimate) {
  // decision 10: the total calls for all the steps, Jev's labels apart, as a split's estimate is counted
  if (!estimate) return null;
  const labels = estimate.jev_labels ? ` · Jev: ${estimate.jev_labels} label${estimate.jev_labels === 1 ? "" : "s"}` : "";
  return `${planCallWords(estimate.calls, estimate.max_calls)} for all the steps${labels}`;
}

export function planEditRequest(task, k, change, value = null) {
  // decision 11: one change per command: sr plan --edit <task> --step <k> with --team, --up, --down, --drop, --text or
  // --done-when (the words after --)
  const request = { action: "plan_edit", task_id: task.task_id, step: k, change };
  if (value != null) request.value = value;
  return request;
}

export function needWords(need) {
  // a need as the card shows it: a key with set or not set, the test command, an account or a decision as text
  const at = need.step ? ` (step ${need.step})` : "";
  if (need.kind === "key") return { kind: "key", name: need.name, words: `${need.name}${at}: ${need.what || ""}`.trim(),
    state: need.set ? "set" : "not set" };
  if (need.kind === "test_command") return { kind: "test_command", words: `Test command: ${need.what}`, state: need.set ? "set" : "not set",
    proposed: need.what };
  return { kind: need.kind, words: `${need.kind === "account" ? "Account" : "Decision"}: ${need.what}${at}`, state: null };
}

export function planCardView(task, show, ui = {}) {
  // decisions 9 to 11: a board like redteam's, the plan first: each step (number, text, team, why, done-when and its team's
  // calls) with its edits; the needs; the total calls; then the check's verdict, and the attack lists folded (the board's)
  if (!task || task.mode !== "plan" || !task.plan) return null;
  const waiting = task.waiting_on === "land", anyway = !!task.land_anyway;
  if (!waiting && !anyway) return null;
  const plan = (show && show.plan) || task.plan;
  const editing = ui.editing && ui.editing.taskId === task.task_id ? ui.editing : null;
  const menu = (show && show.plan_menu) || [];
  const total = plan.steps.length;
  const inherited = plan.revises ? plan.inherited || 0 : 0;  // brief 33.2 (decision 11): a revision's done steps stay
  const steps = plan.steps.map((s) => {
    if (s.k <= inherited) {  // greyed, not editable: its tick and the task that did it
      return { k: s.k, text: s.text, team: s.team, why: s.why, doneWhen: s.done_when, calls: null, jev: null, options: [], edit: null,
        up: null, down: null, drop: null, inherited: true, covers: plan.coverage ? coversWords(s) : null,
        done: s.state === "done" && s.task ? `done by #${s.task.n}` : "done", doneTask: s.task ? s.task.task_id : null };
    }
    const options = menu.map((t) => ({ name: t.name, disabled: t.ready === false && t.name !== s.team, why: t.ready === false ? t.why : null }));
    if (!options.some((o) => o.name === s.team)) options.unshift({ name: s.team, disabled: true, why: "not on the plan's menu now" });
    const edit = editing && editing.k === s.k ? (() => {
      const max = editing.field === "done_when" ? DONE_MAX : editing.field === "covers" ? COVERS_MAX : STEP_MAX;
      const before = editing.field === "done_when" ? s.done_when : editing.field === "covers" ? coversWords(s) : s.text;
      return { field: editing.field, text: editing.text, tooLong: editing.text.length > max,
        count: `${editing.text.length} of ${max} characters`, unchanged: editing.text === before,
        save: planEditRequest(task, s.k, editing.field, editing.text) };
    })() : null;
    return { k: s.k, text: s.text, team: s.team, why: s.why, doneWhen: s.done_when, calls: planCallWords(s.calls, s.max_calls),
      covers: plan.coverage ? coversWords(s) : null,  // brief 33.2 (decision 6): with examples in the spec, "E1, E3" or "none"
      jev: s.jev_label ? "one Jev label" : null, options, edit, inherited: false, done: null, doneTask: null,
      up: s.k > inherited + 1 ? planEditRequest(task, s.k, "up") : null, down: s.k < total ? planEditRequest(task, s.k, "down") : null,
      drop: total > inherited + 1 ? planEditRequest(task, s.k, "drop") : null };
  });
  const needs = (plan.needs || []).map(needWords);
  const edits = (plan.edits || []).length;
  const revises = plan.revises ? `revises #${plan.revises.n}` : null;  // brief 33.2 (decision 11)
  return { title: anyway ? "A plan whose check didn't pass" : "A plan is waiting",
    sub: `${total} step${total === 1 ? "" : "s"}${revises ? ` · ${revises}` : ""} · nothing runs until you approve${edits ? ` · ${edits} edit${edits === 1 ? "" : "s"} of yours` : ""}`,
    steps, needs, project: task.project, count: planCountLine(plan.estimate), revises, inherited,
    changed: plan.revises ? (plan.changed || []).map((c) => `step ${c.step}: ${c.why}`) : null,  // `## Changed`, folded
    coverage: plan.coverage ? plan.coverage.words : null,  // brief 33.2 (decision 6): "Covers E1–E3; not E4"
    specChanged: plan.spec_changed ? SPEC_CHANGED_LINE : null,  // brief 33.2 (decision 7.1): the spec moved since
    approve: anyway ? null : { action: "land", task_id: task.task_id },
    approveAnyway: anyway ? { action: "land", task_id: task.task_id, anyway: true } : null,
    reject: { action: "discard", task_id: task.task_id },
    off: editing ? `Save or cancel step ${editing.k}'s edit first` : ui.running ? "A change to the plan is running" : null };
}

export const PLANNING_LINE = "Planning with your answers…";

export function questionsCardView(task, ui = {}) {
  // brief 33.4 (decision 14): a plan task's card while it waits on answers: each question with its options as chips, the
  // planner's guess marked and never pre-picked, an Other box under each (typing replaces the pick), Send answers on only
  // once every question has a pick or Other text, Use your best guess the quiet skip. After either: the planning line.
  // UI-1m (D25): "Other…" is the last chip; its box shows only while open. An open empty box isn't an answer.
  const found = task && task.mode === "plan" ? task.questions : null;
  if (!found) return null;
  if (found.planning || (found.waiting && ui.running)) return { planning: true, line: PLANNING_LINE };
  if (!found.waiting) return null;
  const picks = ui.picks || {}, others = ui.others || {};
  const questions = found.asked.map((q) => {
    const other = others[q.k] || "";
    const typed = !!other.trim();
    return { k: q.k, text: q.text, other, otherId: `question-other-${task.task_id}-${q.k}`, answered: typed || !!picks[q.k],
      otherChipId: `question-other-chip-${task.task_id}-${q.k}`, open: typed || !!(ui.open && ui.open[q.k]), typed,
      options: q.options.map((o) => ({ letter: o.letter, text: o.text, guess: o.letter === q.guess, picked: !typed && picks[q.k] === o.letter })) };
  });
  const k = questions.length;
  const left = questions.filter((q) => !q.answered).length;
  const off = ui.demo ? "Demo: nothing runs" : null;
  return { planning: false, title: `The planner asks ${k} question${k === 1 ? "" : "s"} before it plans`,
    sub: "nothing runs until you answer", questions,
    send: !left && !off ? answersRequest(task, picks, others) : null,
    sendOff: off || (left ? `${left} question${left === 1 ? "" : "s"} still to answer` : null),
    bestGuess: off ? null : { action: "plan_answer", task_id: task.task_id, best_guess: true },
    cancel: off ? null : { action: "cancel", task_id: task.task_id } };
}

export function closeOther(ui, k) {
  // UI-1m (D25), UI A N6 (A11): Esc, or clearing the box: it closes. A pick stays when nothing was typed; typing had already
  // replaced it, so typing then clearing leaves the question unanswered
  return { ...ui, others: { ...ui.others, [k]: "" }, open: { ...ui.open, [k]: false } };
}

export function answersRequest(task, picks, others) {
  // decision 14: a question's Other text replaces its pick; the router checks both
  const request = { action: "plan_answer", task_id: task.task_id, picks: {}, others: {} };
  for (const q of task.questions.asked) {
    const typed = (others[q.k] || "").trim();
    if (typed) request.others[q.k] = typed;
    else if (picks[q.k]) request.picks[q.k] = picks[q.k];
  }
  return request;
}

export const SPEC_CHANGED_LINE = "SPEC.md changed since this plan was made";
export const SECTION_EDITED_LINE = "Approve replaces the notes' \"Current plan's decisions\", which has words the router didn't write.";
export const PLAN_AGAIN_PLACEHOLDER = "What should change in the plan?";

export function planAgainFill(project) {
  // brief 33.2 (decision 11): Plan again, from the plan panel: Plan, the project, an empty box with its placeholder; Send
  // stays off while the box is empty, as Build from this does
  return { text: "", team: "plan", project, chat: null, quick: false, from: null, idea: null, step: null, noFiles: false,
    placeholder: PLAN_AGAIN_PLACEHOLDER };
}

export function stepCoversLine(task) {
  // brief 33.2 (decision 6): a step card quotes the SPEC.md example(s) it covers, text and label, from the router's JSON
  const covers = ((task && task.plan_step && task.plan_step.covers) || []).filter((c) => c.label);
  if (!covers.length) return null;
  return `covers ${covers.map((c) => `${c.label}: ${c.text || "-"}`).join(" · ")}`;
}

export function coversWords(step) {
  // brief 33.2 (decision 6): a step's covers as the card shows them, "E1, E3" or "none"; (decision 10) an inherited cover
  // whose example's text is gone from the current spec reads "example changed", as the router's words do
  const labels = (step && step.covers || []).map((c) => c.label || "example changed");
  return labels.length ? labels.join(", ") : "none";
}

export function oneStepView(task) {
  // decision 6: a grey card with the planner's one line and Build it, which fills the composer with the task, its team and
  // the project; an answer, not a failure
  if (!task || task.mode !== "plan" || !task.one_step) return null;
  const why = String(task.result || "").replace(/^one step: /, "");
  return { title: "One step", sub: "an answer, not a failure · nothing was planned", line: why, task: task.one_step.task,
    team: task.one_step.team, chip: (task.next || []).find((c) => c.kind === "build_it") || null };
}

export function noSplitView(task) {
  // decision 3: a grey card with the planner's one line (the JSON's `no_split`, never the result text) and Route it
  if (!task || task.mode !== "split" || !task.no_split) return null;
  return { title: "No split", sub: "an answer, not a failure · nothing was made", line: task.no_split,
    project: task.project || null, text: task.text };
}

export function routeItRequest(view, ui, status, skill = null) {
  // decision 3: Route it is the page's usual send of the split's text, from the view it is in (an open chat's tag rides;
  // none open, a new chat, as Send makes; Quick on, no tag), with the split's project when it had one. C4 (/break-ui):
  // it borrowed the composer's state and, when the send stopped for a skill, left the composer changed; now it never
  // touches the composer, and a skill Jev can't give is picked on the card
  const draft = { team: "route", text: view.text, files: [], web: false, slots: {}, skill,
    project: view.project || null, quick: view.project ? false : !!ui.quick, chat: view.project ? null : ui.chat || null };
  if (!draft.quick && !draft.project && !draft.chat) draft.chat = ui.newChat;
  return { request: sendRequest(draft, status), pick: skillPick(draft, status) };
}

export function runAgainFill(task, team = "route") {
  // brief 33.4 (decision 9b), UI A N5 (A11): every Run again item on a text-only card fills the composer (its team, the
  // project, its text, the Text only pill on Route alone, since --no-files works on Route alone: off Route it is visibly a
  // build before you send); it never sends. Null on every other card.
  if (!task || !task.text_only || !task.project) return null;
  return { text: task.text, team, project: task.project, chat: null, quick: false, from: null, idea: null, step: null,
    noFiles: team === "route", placeholder: null };
}

export function saveSpecView(task) {
  // brief 33.4 (decision 8): Save as SPEC.md, a text-only card's main action, from the JSON's offer, never from the text
  if (!task || !task.save_spec || !task.project) return null;
  return { label: `Save as ${task.save_spec.path}`, request: { action: "project_save", name: task.project, task_id: task.task_id, path: task.save_spec.path } };
}

export function runAgainRequest(task, team, ui, status, skill = null) {
  // brief 29.1 (decision 7c): Run again as… sends the task's text as a new task for `team`, from the view it is in (an
  // open chat's tag rides; none open, a new chat, as Send makes; Quick on, no tag), with the task's project when it had
  // one; never the composer's state. A routed run asks for its skill on the card when Jev isn't set up.
  const project = task.project || null;
  const draft = { team, text: task.text, files: [], web: false, slots: {}, skill: team === "route" ? skill : null,
    project, quick: project ? false : !!ui.quick, chat: project || team === "split" ? null : ui.chat || null,
    from: team !== "split" && task.from ? { task_id: task.from.task_id, n: task.from.n } : null,  // brief 33
    noFiles: team === "route" && !!task.text_only };  // brief 33.4 (decision 9b)
  if (team !== "split" && !draft.quick && !draft.project && !draft.chat) draft.chat = ui.newChat;
  return { request: sendRequest(draft, status), pick: skillPick(draft, status) };
}

export function composerGreys(team) {
  // decision 1: what a team greys in the composer, each with its reason
  if (team === "plan") {  // brief 33.1 (decision 1): on a project only, so no chat tag, no Quick, no file, no web
    return { quick: "A plan is on a project, so Quick has nothing to drop", files: "Files go on Route only",
      web: "Web goes on Route only" };
  }
  if (team === "split") {
    return { quick: "A split never carries a chat tag, so Quick has nothing to drop", files: "Files go on Route only",
      web: "Web goes on Route only" };
  }
  if (team !== "route") return { quick: null, files: "Files go on Route only", web: "Web goes on Route only" };
  return { quick: null, files: null, web: null };
}

export function grokWait(task) {
  // The router's own Grok note (rules v2.30: `waiting: grok, <m> min` from N, `overdue: grok, <m> min` from 2N, N from
  // settings), for its colour and Re-check only: what the task waits on is still `waiting_on`.
  if (!task || task.waiting_on !== "grok") return null;
  const note = task.check_note || "";
  if (note.startsWith("overdue: grok")) return { tone: "bad", note, recheck: true };
  if (note.startsWith("waiting: grok")) return { tone: "warn", note, recheck: false };
  return { tone: "info", note: "", recheck: false };
}

export function rescueOffers(task) {
  if (!task) return [];
  const offers = [];
  const id = task.task_id;
  if (task.fallback && task.fallback.ok) {
    offers.push({ key: "fallback", label: `Redo with ${agentLabel(task.fallback.agent)}`, tone: "primary",
      note: `once per task · the checker redoes it, ${agentLabel(task.agent)} checks the redo`, request: { action: "fallback", task_id: id } });
  }
  if (task.resume && task.resume.ok) {
    const same = task.outcome === "process_ended";
    offers.push({ key: "resume", tone: "primary",
      label: same ? `Resume: ${agentLabel(task.resume.agent)} again` : `Resume with ${agentLabel(task.resume.substitute)}`,
      note: same ? "the same agent, no substitute · once per task"
        : `once per task${task.resume.checker ? ` · ${agentLabel(task.resume.checker)} checks` : ""}`,
      request: { action: "resume", task_id: id } });
  }
  const grok = grokWait(task);
  if (grok && grok.recheck) {
    offers.push({ key: "check", label: "Re-check", tone: "primary", note: "asks Grok's inbox now", request: { action: "check" } });
  }
  const ofRun = task.mode === "auto" || !!(task.piece_of && task.piece_of.run);  // brief 34 (decision 10): the switch is
  if (isOpenTask(task) && task.waiting_on !== "needs_label" && !ofRun) {  // the only Stop: no Cancel on a run or its step
    const ofPieces = task.mode === "split" && task.waiting_on === "piece";  // UI A row 7 (A18): "Cancel the split", red
    offers.push({ key: "cancel", label: ofPieces ? "Cancel the split" : "Cancel", tone: task.waiting_on && !ofPieces ? "quiet" : "danger", note: "", request: { action: "cancel", task_id: id } });  // UI A row 19 (A7)
  }
  return offers;
}

export function candidateFiles(task, letter) {
  // brief 29.1 (decision 28): a versus candidate's own copy on a project, from the task's record until the pick: its
  // first files as the files block lists them and how many more (break-ui: 500 chips put the pick 19,000 px down), its
  // tests line, or "no file changed"; null on a task without the candidates' records
  const found = task && task.project_files && task.project_files.candidates && task.project_files.candidates[letter];
  if (!found) return null;
  const all = (found.changed || []).map((c) => ({ path: c.path, status: c.status, words: fileWords(c) }));
  return { files: all.slice(0, FILES_SHOWN), more: Math.max(all.length - FILES_SHOWN, 0), none: !all.length,
    tests: all.length ? testsLine(found.tests) : null };
}

const HEADING = /^\s{0,3}(#{1,3})(?!#)\s*(.+?)\s*$/;
const FENCE = /^\s{0,3}(```|~~~)/;

export function splitHandoff(text) {
  // a result's `## Handoff` section apart from the rest, as the router's context.split_handoff reads it: from the first
  // one- or two-hash Handoff heading outside a code fence to the next one- or two-hash heading, or the end
  const lines = String(text || "").split(/\r\n|\r|\n/);
  let fence = null, at = null, end = null;
  for (let i = 0; i < lines.length; i++) {
    const f = FENCE.exec(lines[i]);
    if (f) { fence = fence === f[1] ? null : (fence || f[1]); continue; }
    if (fence !== null) continue;
    const m = HEADING.exec(lines[i]);
    const level = m && m[1].length <= 2 ? m[1].length : 0;
    if (at === null) {
      if (level && m[2].trim().replace(/:+$/, "").replace(/^[*_` ]+|[*_` ]+$/g, "").toLowerCase() === "handoff") at = i;
    } else if (level) { end = i; break; }
  }
  if (at === null) return { body: text, handoff: null };
  return { body: lines.slice(0, at).concat(end === null ? [] : lines.slice(end)).join("\n").replace(/\n+$/, ""),
    handoff: lines.slice(at, end === null ? undefined : end).join("\n").replace(/^\n+|\n+$/g, "") };
}

export function candidateText(text) {
  // break-ui (the owner's decision, 27 Oct): a versus candidate's `## Handoff` section folds under it as "Its handoff",
  // without its heading; its text is the rest
  const parts = splitHandoff(text || "");
  const handoff = parts.handoff ? parts.handoff.split("\n").slice(1).join("\n").replace(/^\n+/, "") : "";
  return { text: parts.body, handoff: handoff || null };
}

export function versusBoard(task, show) {
  if (!task || task.preset !== "versus" || !show || !(show.candidates || []).length) return null;
  const picking = task.waiting_on === "pick";
  return {
    picking, picked: show.pick || null,
    cards: show.candidates.map((c) => ({ letter: c.letter, builder: agentLabel(c.builder), ...candidateText(c.text), missing: c.missing || null,
      files: candidateFiles(task, c.letter),
      review: c.review ? { reviewer: agentLabel(c.review.reviewer), verdict: c.review.verdict || "no verdict", notes: c.review.notes || "" } : null,
      picked: show.pick === c.letter })),
    choices: picking ? [["a", "Pick A"], ["b", "Pick B"], ["none", "Neither"]].map(([choice, label]) => ({ choice, label,
      request: { action: "pick", task_id: task.task_id, choice } })) : [],
  };
}

export function voteBoard(task, show) {
  if (!task || task.preset !== "vote" || !show || !(show.votes || []).length) return null;
  const tally = show.tally || null;
  const tie = task.waiting_on === "vote_pick";
  return {
    tie, picked: show.pick || null,
    tally: tally && tally.winner ? `${tally.for} of ${tally.for + tally.against} agree` : "no majority",
    votes: show.votes.map((v) => ({ letter: v.letter, agent: agentLabel(v.agent), answer: v.answer || "", why: v.why || "",
      confidence: v.confidence, side: tally && tally.winner === v.letter ? "winner"
        : !tally || !tally.winner || (tally.dissent || []).includes(v.letter) ? "alone" : "agrees",
      picked: show.pick === v.letter })),
    choices: tie ? [["a", "Pick A"], ["b", "Pick B"], ["c", "Pick C"], ["none", "Neither"]].map(([choice, label]) => ({ choice, label,
      request: { action: "pick", task_id: task.task_id, choice } })) : [],
  };
}

const CHECK_WORDS = { open: "still open", ok: "passed" };

export function redteamBoard(task, show) {
  if (!task || task.preset !== "redteam" || !show) return null;
  // UI A N9 (A17): a finding with no answer reads "fixed" only once the revise call has ended
  const revised = (show.calls || []).some((c) => c.role === "revise" && c.status !== "sent");
  const unanswered = revised ? "fixed" : "not answered yet";
  if (!show.attack_lists) {  // a task from before brief 32: its one list, by its numbers, as it ran
    if (!(show.attacks || []).length) return null;
    return { findings: show.attacks.map((a) => ({ n: a.n, severity: a.severity, text: a.text,
      fix: a.answered ? `answered: ${a.answered}` : unanswered })) };
  }
  // brief 32 (decision 17): the findings grouped by list, each with its label, severity, the reviser's answer or "fixed",
  // and the check's verdict on it; a list that didn't run is one line
  const attacks = show.attacks || [];
  const groups = show.attack_lists.filter((l) => l.state === "ran").map((l) => ({
    title: `Attacks · ${agentLabel(l.agent)}`, letter: l.letter,
    findings: attacks.filter((a) => a.label && a.label.startsWith(l.letter)).map((a) => ({ label: a.label,
      severity: a.severity, text: a.text, fix: a.answered ? `answered: ${a.answered}` : unanswered,
      check: CHECK_WORDS[a.check] || "not checked yet" })) }));
  const lines = show.attack_lists.filter((l) => l.state !== "ran").map((l) => l.line).filter(Boolean);
  return groups.length || lines.length ? { groups, lines } : null;
}

export function redteamSummary(red) {
  // UI A row 12 (A17): "2 attacks, 5 findings: 2 high, 2 medium, 1 low", counted from the findings; a task from before brief
  // 32 is its one list
  const lists = red.groups ? red.groups.map((g) => g.findings) : [red.findings || []];
  const all = lists.flat();
  const bySeverity = ["high", "medium", "low"].map((sev) => [all.filter((f) => f.severity === sev).length, sev]).filter(([k]) => k);
  const plural = (k, word) => `${k} ${word}${k === 1 ? "" : "s"}`;
  return `${plural(lists.length, "attack")}, ${plural(all.length, "finding")}: ${bySeverity.map(([k, sev]) => `${k} ${sev}`).join(", ")}`;
}

export function memoryCallLines(calls) {
  // Terminal's per-call memory lines (router `_call_memory_lines`), with the page's names for the role and agent
  return (calls || []).map((c) => {
    const m = c.memory || {};
    const who = `${c.kind === "stage" || c.kind === "reask" ? `stage ${c.stage}${c.kind === "reask" ? " re-ask" : ""}` : roleWords(c.kind)} · ${agentLabel(c.agent)}`;
    let what = m.state === "off" ? "memory was off; the call ran without it"
      : m.state === "unavailable" && m.sent ? `the store was down; the newest ${m.sent} went from the log`  // the memory brief, step 2
      : m.state === "unavailable" ? "the store was unavailable; the call ran without it"
      : m.state === "left_out" ? `left out: it could not fit Grok's prompt limit${m.with != null && m.limit != null ? ` (${m.with} > ${m.limit})` : ""}`
        : m.state === "sent" ? `sent ${m.sent} of ${m.found}` : "not kept";
    if (m.from) what += `, the block from ${m.from}`;
    return { who, what, trimmed: m.state === "left_out" };
  });
}

export function handoffWords(handoff) {
  if (!handoff) return null;
  if (handoff.left_out) return `Handoff left out: it could not fit Grok's prompt limit (${handoff.total} lines)`;
  if (handoff.attached) return `Handoff attached: ${handoff.lines} of ${handoff.total} lines`;
  return "Handoff: not sent yet (the build call has not been made)";
}

function storedWords(m) {
  // a save, or why it was skipped (brief 27, decision 13: never `undefined · undefined characters`)
  if (m.forgotten) return `forgotten · ${m.forgotten}`;  // brief 30 (decision 15): the owner's Forget
  if (m.remembered) return `remembered again · ${m.remembered}`;
  if (m.skipped) {
    const why = m.skipped === "off" ? "memory was off" : m.skipped === "looks like a key" ? "it looked like a key"
      : String(m.skipped).startsWith("unavailable") ? "the store was unavailable" : m.skipped;
    return `not saved: ${why} · ${m.state}`;
  }
  return `${m.document_id} · ${m.chars} characters · ${m.state}`;
}

export function whatNowParts(line) {
  // decision 13: the router's line and its one control: Open (a card), the chip itself (it fills the box), Ideas, or none.
  // Brief 33.1 (decisions 6, 16 and 17): Build step k and Build it are chips; a need's Secrets (naming the key) or Set (the
  // proposed test command, after a confirm naming it), with the step's chip beside it; the finish line's chips; and the
  // router's word when docs/PLAN.md was left out or written over
  if (!line || !line.words) return null;
  const said = line.plan_md && line.plan_md.why ? line.plan_md.why : null;
  const base = { chip: null, open: null, ideas: false, taskId: line.task_id, secrets: null, tests: null, chips: [], said };
  if (line.control === "chip" && line.chip) {
    const own = ["build_step", "build_it"].includes(line.chip.kind);  // the plan's lines say themselves; brief 33's say Next:
    if (line.chip.kind === "revise_plan") {  // brief 33.2 (decision 7.1): "SPEC.md changed since plan #n", the chip beside it
      return { ...base, lead: String(line.words).replace(/ · Revise plan$/, ""), chip: line.chip };
    }
    return { ...base, lead: own ? (line.chip.kind === "build_it" ? line.words : "Next:") : "Next:", chip: line.chip };
  }
  if (line.control === "secrets" && line.need) return { ...base, lead: line.words, secrets: line.need.name, chip: line.chip || null };
  if (line.control === "tests" && line.need) return { ...base, lead: line.words, tests: line.need.proposed, chip: line.chip || null };
  if (line.control === "chips") return { ...base, lead: line.words, chips: line.chips || [] };
  return { ...base, lead: line.words, open: line.control === "open" ? line.task_id : null, ideas: line.control === "ideas" };
}

export const SECRET_LABEL_MAX = 24;  // break-ui (brief 33.1): a key's name has no limit; at 320 px 24 fits whole

export function secretsLabel(name) {
  // break-ui (brief 33.1): an 80-character key name pushed its Secrets button 350 px past the card at 390 px; the label
  // keeps the name's start and end (names differ at the end: _KEY, _TOKEN, _JSON), the full name in its title
  return `Secrets · ${middleTruncate(name, SECRET_LABEL_MAX)}`;
}


// ---------- Auto on the page (build brief 34, decisions 10 to 13): the pure parts ----------
// The router works every state out (a project's `auto`, a task's `auto`, What now?'s Auto lines, the dry run's numbers,
// the plan's steps and marks); the page draws them and never works a number out itself.

export function autoSwitchView(project, run = null) {
  // decision 10: off when `--on` would be accepted, on while a run runs, hidden otherwise (never greyed); `run` is the
  // page's own auto_on/auto_off run in flight ({name, to, started}), which keeps the switch drawn and busy until status
  // says where the run stands
  const auto = project && project.auto;
  if (run) {
    const on = run.to === "on";
    return { on, to: run.to, label: on ? "Starting…" : "Stopping…", busy: true, disabled: true,
      title: `Running sr auto ${project ? project.name : ""} --${run.to}`, state: auto ? auto.state : null, words: null };
  }
  if (!auto || auto.switch === "hidden") return null;
  const on = auto.switch === "on";
  return { on, to: on ? "off" : "on", label: on ? "On" : "Off", busy: false, disabled: false,
    title: on ? `Runs sr auto ${project.name} --off: the run stops after the step in progress, never mid-call`
      : `Asks once (the steps, the budget, the first stop-here), then runs sr auto ${project.name} --on`,
    state: auto.state, words: auto.run ? auto.run.words : null };
}

export function autoConfirmView(doc, name) {
  // decision 10: the confirm's words are the router's dry run (`sr auto <name> --on --dry-run --json`): the steps the run
  // covers, the budget, the first stop-here and the one-step overrun, as it wrote them; a refusal is shown as it came
  const request = { action: "auto_on", name };
  const line = `sr auto ${name} --on`;
  const none = { words: null, overrun: null, steps: [], budget: null, firstStop: null, request, line, specLine: null };
  if (!doc) return { ...none, refused: "The dry run didn't answer." };
  const found = doc.auto;
  if (!found || (doc.exit != null && doc.exit !== 0)) return { ...none, refused: doc.message || doc.error || "The dry run was refused." };
  return { refused: null, words: found.words, overrun: found.overrun, steps: found.steps || [], budget: found.budget,
    firstStop: found.first_stop_here == null ? null : found.first_stop_here, request, line,
    specLine: found.spec_line || null };  // brief 33.2 (decision 7.2): "The remaining steps will use the new SPEC.md."
}

const STEP_STATE_WORDS = { open: "open", running: "running", retried: "failed twice, retried", failed: "failed twice", stopped: "stopped" };

export function autoBoard(task, show, marks = []) {
  // decision 12: the run's card is the recap: each step with its state, its task, its calls and its checker's verdict (and
  // its stop-here mark), the calls used against the budget, what is still open, why it stopped, and the two buttons
  const auto = task && task.auto;
  if (!auto) return null;
  const steps = (auto.steps || []).map((s) => ({
    k: s.k, label: `Step ${s.k}`, team: s.team ? teamLabel(s.team) : null,
    state: s.state === "done" ? (s.outcome === "unchecked" ? "unchecked" : s.verdict === "fixed" ? "fixed" : "passed")
      : STEP_STATE_WORDS[s.state] || s.state || "open",
    taskId: s.task_id || null, n: s.n == null ? null : s.n, calls: s.calls || 0, verdict: s.verdict || null,
    attempt: s.attempt > 1 ? `${s.attempt} attempts` : null, mark: (marks || []).includes(s.k), covered: s.covered !== false }));
  const open = steps.filter((s) => !["passed", "fixed", "unchecked"].includes(s.state)).map((s) => s.k);
  const id = task.task_id;
  const land = (label, tone) => ({ key: "land", label, tone, request: { action: "land", task_id: id } });
  const discard = { key: "discard", label: "Discard run", tone: "quiet", request: { action: "discard", task_id: id } };
  const buttons = auto.state === "finished" ? [land("Land run", "primary"), discard]
    : auto.state === "stopped" ? [land("Land the run so far", ""), discard]
      : auto.state === "landed" ? [{ key: "undo", label: "Undo", tone: "", request: { action: "undo", task_id: id } }] : [];
  return { words: auto.words || null, state: auto.state || null, steps, calls: `${count(auto.used || 0)} of ${count(auto.budget || 0)} calls`,
    open, why: auto.stop ? auto.stop.why || null : null, stopStep: auto.stop ? auto.stop.step || null : null,
    ways: auto.ways || null,  // brief 33.2 (decision 7.2): after a spec_changed stop, the two ways on, the router's words
    tests: auto.tests || null,  // brief 33.2 (decision 16): the steps' test runs summed, the router's words
    marks: (marks || []).slice(), buttons, plan: auto.plan && auto.plan.n != null ? `plan #${auto.plan.n}` : null };
}

export function stopHereRows(plan, busy = new Set()) {
  // decision 13: the current plan's steps from the project's `plan` entry (status), each with its Stop here toggle; a
  // status from before brief 34 has no steps, so the panel shows the text alone
  if (!plan || !Array.isArray(plan.steps)) return [];
  return plan.steps.map((s) => {
    const step = `${plan.task_id}:${s.k}`;
    const to = s.stop_here ? "off" : "on";
    return { k: s.k, text: s.text || "", team: s.team ? teamLabel(s.team) : null, done: !!s.done, on: !!s.stop_here,
      busy: !!busy && busy.has(step), to, step, request: { action: "plan_stop_here", step, to } };
  });
}

function autoFileView(task, f, counted, view) {
  // brief 34 (decisions 8 and 12): the files block on a run names the run's whole change; its buttons are the recap's
  const state = task.auto ? task.auto.state : null;
  if (f.state === "waiting") return { ...view, kind: "waiting", tone: "info", line: counted, buttons: [],
    note: `Ready to land: the whole run, one commit on ${f.branch || "its branch"} (Land run is on the recap)` };
  if (f.state === "landed") return { ...view, kind: "landed", tone: "ok", line: `Landed · ${shortId(f.commit)} · Undo`, commit: shortId(f.commit), buttons: [] };
  if (f.state === "undone") return { ...view, kind: "undone", tone: "muted", line: `Undone · ${shortId(f.undo_commit)} put back ${shortId(f.commit)}`, buttons: [] };
  if (f.state === "discarded") return { ...view, kind: "discarded", tone: "muted", line: "Discarded: the run never landed", buttons: [] };
  if (state === "stopped" && f.copy) return { ...view, kind: "kept", tone: "warn", line: `${counted} · the run stopped`, buttons: [],
    note: "Land the run so far (on the recap) lands the steps it passed, as the copy stood when the stopped step started" };
  return { ...view, kind: "building", tone: "muted", line: `Files: a copy of ${task.project} at ${shortId(f.base)} · the run builds in it`, buttons: [] };
}

export function planBarWords(project) {
  // brief 33.1 (decision 20): "Plan #12 · 1 of 4" on the project's bar; it opens docs/PLAN.md, read only
  const plan = project && project.plan;
  return plan ? `Plan #${plan.n} · ${plan.done} of ${plan.total}` : null;
}

export function testsConfirmWords(name, words) {
  // decision 16: Set asks once, naming the words it sets as the project's test command
  return `Set ${name}'s test command to \`${words}\`? The router runs it after each build, in its sandbox.`;
}

export function suggestView(doc, { demo = false, claude = true, starting = false } = {}) {
  // brief 33.4 (decision 13, and the owner's answer on its limit): the Suggest ideas button: hidden when Claude is unavailable and in
  // the demo; off and "Suggesting…" while one runs; off at the limit with its line (from 48 open, as intake refuses)
  if (demo || !claude) return { hidden: true };
  const found = (doc && doc.suggest) || {};
  const running = starting || !!found.running;
  const last = found.last;
  return { hidden: false, running, label: running ? "Suggesting…" : "Suggest ideas", off: running || !!found.off || !doc,
    why: found.off || null, line: found.off || (last && !running ? (last.status === "done" ? last.line : `#${last.n}: ${last.line}`) : null) };
}

export function suggestToast(env) {
  // decision 13: "3 ideas added" when it ends, or what went wrong; the sheet's line says what was dropped
  if (!env) return "The page lost track of the suggest.";
  if (env.added == null || !env.added) return env.summary || env.message || "The suggest stopped.";
  return `${env.added} idea${env.added === 1 ? "" : "s"} added`;
}

export function ideasSheetView(doc, { name, text = "", running = false, failure = null, demo = false, asking = null, suggesting = false } = {}) {
  // decisions 14 to 16 and 19: the list (text, where it came from with its link, date), Send and Dismiss on each, and Add
  const listed = (doc && doc.ideas) || [];
  const typed = (text || "").trim();
  return {
    title: `Ideas · ${name}`,
    loading: !doc,
    empty: !!doc && !listed.length,
    rows: listed.map((idea) => ({
      id: idea.id, text: idea.text, date: String(idea.created_at || "").slice(0, 10),
      source: idea.source && idea.source.kind === "later" && idea.source.n
        ? { words: `${idea.source.suggested ? "Suggested by" : "Later on"} #${idea.source.n}`, taskId: idea.source.task_id }  // 33.4
        : { words: "Added", taskId: null },
      sent: idea.sent_as ? `sent as #${idea.sent_as.n}` : null,
      canSend: idea.state === "open", canAddToPlan: idea.state === "open", asking: asking === idea.id })),  // 33.2
    dismissed: (doc && doc.dismissed) || 0,
    // brief 33.2 fix 4 (the owner's decision 4): the used ideas, folded under the list, each with the task that used it
    used: doc && (doc.used || []).length ? { title: `Used (${doc.used.length})`, folded: true,
      rows: doc.used.map((idea) => ({ id: idea.id, text: idea.text, by: idea.used_by ? `used by #${idea.used_by.n}` : "used",
        taskId: idea.used_by ? idea.used_by.task_id : null })) } : null,
    canAdd: !!typed && !running && !demo,
    line: suggesting ? `sr ideas ${name} --suggest` : `sr ideas ${name} --add -- ${shellQuote(typed || "<the idea>")}`,  // 33.4
    failure,
  };
}

export function fillFromIdea(idea, project, current) {
  // decision 16: Send fills the composer as a chip does (Route, the project, the text) with the Idea pill; never sends
  const next = { text: idea.text, team: "route", project, chat: null, quick: false, from: null,
    idea: { id: idea.id, text: idea.text }, placeholder: null };
  return { next, undo: (current.text || "").trim() ? { ...current } : null };
}

export function fillFromIdeaToPlan(idea, project, current) {
  // brief 33.2 (decision 12): Add to plan fills Plan, the project, the Idea pill and the idea's text, editable; with a
  // current plan that has open steps the router makes a revision, else a new plan; nothing is added to the text
  const next = { text: idea.text, team: "plan", project, chat: null, quick: false, from: null,
    idea: { id: idea.id, text: idea.text }, step: null, noFiles: false, placeholder: null };
  return { next, undo: (current.text || "").trim() ? { ...current } : null };
}

export function builtFrom(task) {
  // brief 33 (decision 12): "Built from #<n>" outside Details, linked to that card
  return task && task.from && task.from.task_id ? { id: task.from.task_id, text: `Built from #${task.from.n}` } : null;
}

export function fromGiven(show) {
  // brief 33 (decision 12): Details' "What the agents were given" shows the block as the first call sent it
  const found = show && show.from_given;
  if (!found || !found.text) return null;
  const size = `${Number(found.chars || 0).toLocaleString("en-US")} characters`;
  return { head: `The earlier result #${found.n} · ${size}${found.cut ? ", cut" : ""}`, text: found.text };
}

export function memoryDrawer(task, show) {
  if (!task || !task.tag || !show) return null;
  return {
    tag: task.chat ? `chat ${task.chat}` : task.project ? `project ${task.project}` : task.tag,
    given: (show.memory_given || []).map((m) => ({ head: [`#${m.n}`, m.date, m.kind, m.doer ? agentLabel(m.doer) : null, m.status]
      .filter(Boolean).join(" · "), text: m.text || "" })),
    calls: memoryCallLines(show.calls),
    handoff: handoffWords(show.handoff),
    stored: (show.memory_stored || []).map(storedWords),
  };
}

const NEEDS_WORDS = { needs_label: "Pick a skill", split_plan: "Approve a split plan", pick: "Pick A or B", land: "Ready to land",
  plan_land: "Approve a plan",  // brief 33.1 (decision 9)
  answers: "Answer questions",  // brief 33.4 (decision 5)
  vote_pick: "A tie: pick one", failed_check: "Failed its check twice", plan_limit: "Plan limit",
  process_ended: "Process ended", grok: "Grok is overdue", memory: "Memory starting", probe: "A safety check is running",
  land_anyway: "Land anyway?",  // brief 29.1 (decisions 21 and 28); break-ui: longer words were cut in the sidebar
  auto: "Auto stopped", auto_land: "Land the run?" };  // brief 34 (decision 13)

export function needsYou(task) {
  // What a task needs from you, or null: your turn on a wait, a rescue the row offers, a Grok task overdue
  if (!task) return null;
  if (task.waiting_on === "auto") return NEEDS_WORDS.auto;  // brief 34: a stopped run
  if (task.waiting_on === "land" && task.mode === "auto") return NEEDS_WORDS.auto_land;  // brief 34: a finished run
  if (task.waiting_on === "land" && task.mode === "plan") return NEEDS_WORDS.plan_land;  // brief 33.1
  if (YOUR_TURN.includes(task.waiting_on)) return NEEDS_WORDS[task.waiting_on];
  if (task.land_anyway) return NEEDS_WORDS.land_anyway;  // brief 29.1 (decision 21): the router's offer, never worked out
  if (task.outcome === "failed_check" && task.fallback && task.fallback.ok) return NEEDS_WORDS.failed_check;
  if ((task.outcome === "plan_limit" || task.outcome === "process_ended") && task.resume && task.resume.ok) return NEEDS_WORDS[task.outcome];
  const grok = grokWait(task);
  return grok && grok.recheck ? NEEDS_WORDS.grok : null;
}

export function needsYouList(tasks) {
  const you = [], router = [];
  for (const task of (tasks || []).slice().sort((a, b) => b.n - a.n)) {
    const what = needsYou(task);
    if (what) you.push({ task_id: task.task_id, n: task.n, what, key: `${task.task_id}:${what}` });
    else if (task.waiting_on === "memory" || task.waiting_on === "probe") router.push({ task_id: task.task_id, n: task.n, what: NEEDS_WORDS[task.waiting_on] });
  }
  return { you, router };
}

export function refusalAlternatives(run, status) {
  // A send refused because an agent in a slot can't run (rules: an agent off after a failed safety check offers the
  // others): the same request with each usable agent the slot allows.
  const env = (run && run.envelope) || {};
  const request = run && run.request;
  if (!request || request.action !== "send" || !request.slots || !["probe_failed", "signed_out", "not_configured", "not_live"].includes(env.reason_code)) return [];
  const preset = ((status && status.presets) || []).find((p) => p.name === request.team);
  if (!preset) return [];
  const view = slotViews(preset, request.slots, status, request.project || null);
  const filled = Object.fromEntries(view.slots.map((s) => [s.name, s.value]));
  const out = [];
  for (const slot of view.slots) {
    if (slot.leftOut || !usableIn(status, slot.value).bad) continue;  // brief 32: a left-out second attack needs no rescue
    for (const o of slot.options) {
      // never an agent another slot already holds: intake refuses one agent judging its own work (presets.own_work);
      // never one the picker greys (brief 32)
      const elsewhere = Object.entries(filled).some(([name, agent]) => name !== slot.name && agent === o.agent);
      if (o.agent && !o.disabled && o.agent !== slot.value && !elsewhere && !usableIn(status, o.agent).bad) {
        out.push({ label: `Run it with ${o.label} in slot ${slotShort(slot)}`, request: { ...request, slots: { ...request.slots, [slot.name]: o.agent } } });
      }
    }
  }
  return out;
}

function usableIn(status, name) {
  const agent = ((status && status.agents) || []).find((a) => a.name === name);
  const u = usable(agent);
  return { bad: !u.ok, why: u.why };
}

// ---------- History, Log files, the report, Setup and the first-run card (F) ----------

export function historyPath({ chat = null, project = null, search = "" } = {}, before = null) {
  // `sr log --json` with --chat, --project, --search and --before (decision 16's History), nothing empty
  const params = new URLSearchParams();
  if (chat) params.set("chat", chat);
  if (project) params.set("project", project);
  if (search && search.trim()) params.set("search", search.trim());
  if (before) params.set("before", before);
  const query = params.toString();
  return query ? `/api/log?${query}` : "/api/log";
}

export function mergeTasks(older, newer) {
  const byId = new Map((older || []).map((t) => [t.task_id, t]));
  for (const task of newer || []) byId.set(task.task_id, task);
  return [...byId.values()].sort((a, b) => a.n - b.n);
}

// Cleanup 2, row 1: a chat's or a project's view reads its own newest tasks. state.tasks stays the whole log's newest 50,
// since Needs you, the agents' counts and the notifications read that.
export function viewReadKey({ view, chat, project }) {
  if (view !== "chat") return null;  // All tasks, Log files and Settings
  if (project) return `project:${project}`;
  return chat ? `chat:${chat}` : null;  // Quick tasks keep the whole log's read: `sr log` has no "untagged" filter
}

export function viewReadQuery(key) {
  const at = key.indexOf(":");
  return { [key.slice(0, at)]: key.slice(at + 1) };
}

export function takeViewPage(read, doc, { more = false, quiet = false } = {}) {
  // as loadHistory merges: the first read replaces, a poll merges the first page and keeps older ones, more adds below
  const found = (doc && doc.tasks) || [];
  const next = (doc && doc.next_before) || null;
  if (more) return { ...read, tasks: mergeTasks(found, read.tasks), next, pages: read.pages + 1, loading: false, error: null };
  if (quiet) {
    return { ...read, tasks: mergeTasks(read.tasks, found), next: read.pages > 1 ? read.next : next, pages: Math.max(read.pages, 1), error: null };
  }
  return { ...read, tasks: mergeTasks([], found), next, pages: 1, loading: false, error: null };
}

export function viewTasksKnown(read, tasks) {
  return mergeTasks(read ? read.tasks : [], tasks);  // a row from either read counts; the whole log's is read last, so it wins
}

export function patchViewRow(read, show) {
  // a poll only re-reads the first page, so an action on an older card comes back through its show: the row's own keys
  if (!read || !show || !read.tasks.some((t) => t.task_id === show.task_id)) return read;
  const patch = (t) => {
    if (t.task_id !== show.task_id) return t;
    const row = { ...t };
    for (const key of Object.keys(t)) if (key in show) row[key] = show[key];
    return row;
  };
  return { ...read, tasks: read.tasks.map(patch) };
}

function chatHeadWords(count, memory) {
  return `chat · ${count} task${count === 1 ? "" : "s"} · ${chatMemoryWords(memory)}`;
}

export function jumpStep(rows, next, task) {
  // Cleanup 2, row 2: one step of a jump: the card is loaded, it can't be (the oldest row is already older, or nothing is left), or read more
  if ((rows || []).some((t) => t.task_id === task.task_id)) return "found";
  if (!next) return "gone";
  return (rows || []).some((t) => t.n < task.n) ? "gone" : "more";
}

export function chatCount(status, name, shown) {
  // status is read once a minute, so its count can lag a task just sent: never lower than what's on screen
  const chat = ((status && status.chats) || []).find((c) => c.name === name);
  return Math.max(chat ? Number(chat.tasks) || 0 : 0, shown);
}

export const SETUP_PIECES = [["claude", "Claude"], ["chatgpt", "ChatGPT"], ["cursor", "Cursor"], ["grok", "Grok Bot"],
  ["jev", "Jev"], ["memory", "Memory"], ["git", "Git"],  // brief 28 (decision 20d): the Git row
  ["notes", "Router notes"],  // brief 30 (decision 10): the router notes' row and its editor
  ["models", "Models"]];  // brief 33.3 (decision 12): the model defaults' row, its selects and the Fable switch

export function setupSections(markdown) {
  // docs/SETUP.md by its "## " sections, keyed by title; what comes before the first is the intro
  const found = { intro: "", sections: {} };
  let title = null, lines = [];
  const flush = () => {
    const text = lines.join("\n").trim();
    if (title === null) found.intro = text;
    else found.sections[title] = text;
  };
  for (const line of String(markdown || "").replace(/\r\n?/g, "\n").split("\n")) {
    const heading = /^##\s+(.+?)\s*$/.exec(line);
    if (heading) { flush(); title = heading[1]; lines = []; } else lines.push(line);
  }
  flush();
  return found;
}

const and = (items) => (items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`);

export function withoutLine(key, status) {
  // brief 24 (decision 15): what happens without this piece, in words drawn from status's skills and presets (what the
  // router does now), so only while the piece is missing; Claude's is said always (decision 2: Claude is required)
  if (!status) return null;
  if (key === "claude") return "nothing runs: Claude is required.";
  if (key === "memory" || key === "models") return null;
  if (key === "git") return status.git && status.git.installed === false ? "no project's files change: every project task runs handoff only." : null;
  if (key === "jev") return status.jev && status.jev.available === false ? "you pick each routed task's skill." : null;
  const agent = ((status.agents) || []).find((a) => a.name === key);
  if (!agent || agent.available !== false) return null;
  const name = agentLabel(key);
  const moved = new Map(), back = [], unchecked = [], filled = [], blocked = [];
  for (const s of status.skills || []) {
    const now = s.now || {};
    if (now.stand_in && now.stand_in.for === key) {
      const doer = agentLabel(now.doer);
      moved.set(doer, [...(moved.get(doer) || []), now.note ? `${s.key} (${now.note})` : s.key]);
    }
    if (now.comes_back && now.comes_back.includes(name)) back.push(s.key);
    if (now.unchecked && now.unchecked.includes(name)) unchecked.push(s.key);
  }
  for (const p of status.presets || []) {
    for (const f of p.filled || []) if (f.default === key) filled.push(`${p.name} uses ${agentLabel(f.agent)} for its ${f.slot} slot`);
    if (p.ready === false && (p.why || "").includes(name)) blocked.push(p.name);
  }
  const parts = [...[...moved].map(([doer, keys]) => `${and(keys)} go${keys.length === 1 ? "es" : ""} to ${doer}`),
    back.length ? `${and(back)} come${back.length === 1 ? "s" : ""} back` : null,
    unchecked.length ? `${and(unchecked)} ${unchecked.length === 1 ? "is" : "are"} delivered unchecked` : null,
    ...filled, blocked.length ? `${and(blocked)} can't run` : null].filter(Boolean);
  return parts.length ? `${parts.join("; ")}.` : "nothing else changes.";
}

export function setupRows(status) {
  // a row per piece with its live state from status, in the top strip's words, and what happens without it (brief 24)
  return setupRowsBare(status).map((row) => ({ ...row, without: withoutLine(row.key, status) }));
}

function setupRowsBare(status) {
  const agents = new Map(((status && status.agents) || []).map((a) => [a.name, a]));
  return SETUP_PIECES.map(([key, name]) => {
    if (key === "git") return { ...gitSetupRow(status), checkedAt: null };  // brief 28
    if (key === "notes") return routerNotesRow(status);  // brief 30
    if (key === "models") return modelsSetupRow(status);  // brief 33.3
    if (key === "jev") {
      if (status && status.jev == null) return { key, name, tone: "muted", state: "unknown", detail: "not checked yet", checkedAt: null };
      const jev = jevView(status && status.jev);
      return { key, name, tone: !jev.configured ? "muted" : jev.over ? "bad" : "ok", state: jev.configured ? jev.text : "not set up",
        detail: !jev.configured ? (status.jev.why || "no JEV_API_KEY in .env") : jev.over ? "over this month's cap: routed tasks wait for your label" : "tokens this month",
        checkedAt: null };
    }
    if (key === "memory") {
      const memory = memoryView(status && status.memory);
      return { key, name, tone: memory.tone, state: memory.state, detail: memory.detail, checkedAt: null,
        problem: memory.problem, off: memory.off };
    }
    const agent = agents.get(key);
    if (!agent) return { key, name, tone: "muted", state: "not in this router", detail: "", checkedAt: null };
    const view = agentView(agent, [], status && status.models);
    return { key, name, tone: view.tone, state: view.state, detail: view.detail.join(" · "), checkedAt: agent.checked_at || null };
  });
}

// ---------- router notes and project notes (brief 30, decisions 10, 13 to 17) ----------
// The router works every count out (`sr notes --json`, `sr project notes <name> --json`, status); the page shows them.

export const NOTES_SECTIONS = [["all_agents", "All agents"], ["claude", "Claude"], ["chatgpt", "ChatGPT"], ["grok", "Grok"],
  ["cursor", "Cursor"], ["planner", "Planner"]];

export function routerNotesRow(status) {
  // the Setup sheet's Router notes row from status's `notes`: blank is a choice (never in the first-run card), invalid
  // refuses every task (so it is), set says how much goes
  const notes = status && status.notes;
  const row = { key: "notes", name: "Router notes", checkedAt: null };
  if (!notes) return { ...row, tone: "quiet", state: "unknown", detail: "not read yet" };
  if (notes.state === "invalid") {
    return { ...row, tone: "bad", state: "invalid", detail: `${notes.why || "the file can't be read"}: every task is refused until you fix it` };
  }
  if (notes.state === "blank") return { ...row, tone: "quiet", state: "blank", detail: "nothing is sent with your tasks" };
  const parts = NOTES_SECTIONS.filter(([key]) => (notes.sections || {})[key]).map(([, title]) => title);
  return { ...row, tone: "ok", state: "set", detail: `${parts.join(", ")} · ${count(notes.total)} of ${count(notes.max)} characters` };
}

export function notesEditorView(doc, text, { saving = false, failure = null, closing = false, demo = false, refused = null } = {}) {
  // decision 10: the editor's words. Counts, state, cap and Grok's share are the saved file's, as the router read it
  if (!doc) return { loading: true, sections: [], canSave: false, dirty: false, failure, closeWords: "Close", closeNote: null };
  const typed = String(text == null ? doc.text : text);
  const dirty = typed !== doc.text;
  const grok = doc.grok || {};
  const sections = NOTES_SECTIONS.map(([key, title]) => ({ key, title, chars: count((doc.sections || {})[key] || 0) }));
  return {
    loading: false, sections, dirty, saving, failure,
    total: `${count(doc.total)} of ${count(doc.max)} characters${dirty ? " (as saved)" : ""}`,
    grok: `Grok's share: ${count(grok.share)} of its ${count(grok.limit)}. ${grok.line || ""}`.trim(),
    state: doc.state === "invalid" ? `Invalid: ${doc.why}` : doc.state === "blank" ? "Blank: nothing is sent" : "Set: sent with every task from the next one on",
    stateTone: doc.state === "invalid" ? "bad" : "muted",
    where: doc.default ? "The six empty headings (no notes file yet)." : null,
    canSave: dirty && !saving && !demo && !refused,
    closeWords: closing && dirty ? "Discard changes" : "Close",
    closeNote: closing && dirty ? "You have unsaved changes. Close again to discard them." : null,
    foot: demo ? "Demo: nothing runs." : dirty ? "Unsaved changes" : null,
  };
}

export function projectNotesView(doc, text, { saving = false, failure = null, closing = false, demo = false, refused = null } = {}) {
  // decision 17: the notes in a box, the router's block read-only under it, lines, characters and the cap
  if (!doc) return { loading: true, canSave: false, dirty: false, failure, closeWords: "Close", closeNote: null };
  const typed = String(text == null ? doc.notes : text);
  const dirty = typed !== doc.notes;
  return {
    loading: false, dirty, saving, failure, block: doc.block || "(no block yet: the router adds one at the end)",
    counts: `${count(doc.lines)} ${doc.lines === 1 ? "line" : "lines"} · ${count(doc.chars)} of ${count(doc.max)} characters${dirty ? " (as saved)" : ""}`,
    commit: doc.tracked ? "Save makes one commit holding HANDOFF.md alone." :
      "Save writes HANDOFF.md and commits nothing (no git here, or HANDOFF.md isn't tracked).",
    canSave: dirty && !saving && !demo && !refused,
    closeWords: closing && dirty ? "Discard changes" : "Close",
    closeNote: closing && dirty ? "You have unsaved changes. Close again to discard them." : null,
    foot: demo ? "Demo: nothing runs." : dirty ? "Unsaved changes" : null,
  };
}

export const SPEC_NONE = "Spec · none";

export function labelRanges(names) {
  // E1, E2, E3, E5, D1 → "E1–E3, E5, D1": per prefix, runs of three or more compressed, the order kept
  const out = [];
  let i = 0;
  while (i < names.length) {
    const m = /^([A-Za-z]+)(\d+)$/.exec(names[i]);
    if (!m) { out.push(names[i]); i++; continue; }
    let j = i;
    while (j + 1 < names.length) {
      const n = /^([A-Za-z]+)(\d+)$/.exec(names[j + 1]);
      if (!n || n[1] !== m[1] || Number(n[2]) !== Number(/^([A-Za-z]+)(\d+)$/.exec(names[j])[2]) + 1) break;
      j++;
    }
    if (j - i >= 2) out.push(`${names[i]}–${names[j]}`); else for (let k = i; k <= j; k++) out.push(names[k]);
    i = j + 1;
  }
  return out.join(", ");
}

export function projectSpecView(doc, text, { saving = false, failure = null, demo = false } = {}) {
  // brief 33.2 (decision 4): the Spec section of a project's Notes sheet: the file in a box, the labels as the router
  // read them, lines, characters and the cap, Save only with unsaved non-empty text, Draft it while there is no spec
  if (!doc) return { loading: true, exists: false, canSave: false, dirty: false, failure, labels: [], draft: null, title: "Spec" };
  const typed = String(text == null ? doc.text : text);
  const dirty = typed !== doc.text;
  const labels = (doc.examples || []).concat(doc.done_when || []);
  const names = labels.map((l) => l.label);
  // break-ui: 60 examples made a 300-character title; runs of three or more labels read as a range, as the router's
  // coverage line does ("E1–E60, D1–D10")
  const title = !doc.exists ? SPEC_NONE : names.length ? `Spec · ${labelRanges(names)}` : "Spec · text only";
  return {
    loading: false, exists: !!doc.exists, title, text: typed, dirty, saving, failure, labels, draft: doc.exists ? null : doc.draft || null,
    counts: `${count(doc.lines)} ${doc.lines === 1 ? "line" : "lines"} · ${count(doc.chars)} of ${count(doc.max)} characters${dirty ? " (as saved)" : ""}`,
    commit: doc.commit_words || "",
    labeledNote: doc.exists && !names.length ? "No `## Examples` or `## Done when` list: the spec rides as text, and no step is held to a label." : null,
    canSave: dirty && !!typed.trim() && !saving && !demo,
    saveWords: saving ? "Saving…" : "Save",
    foot: demo ? "Demo: nothing runs." : dirty ? "Unsaved changes" : null,
  };
}

export function cardActions(task) {
  // decision 17: Pin to notes, Save to project, Forget or Remember again, each offered by the card's JSON
  const a = (task && task.card_actions) || {};
  const found = [];
  if (a.pin) found.push({ key: "pin", label: "Pin to notes" });
  if (a.save) found.push({ key: "save", label: "Save to project" });
  if (a.forget) found.push({ key: "forget", label: "Forget", request: { action: "forget", task_id: task.task_id } });
  if (a.remember) found.push({ key: "remember", label: "Remember again", request: { action: "forget", task_id: task.task_id, undo: true } });
  return found;
}

export function forgottenLine(task) {
  // decision 15: a forgotten card reads `Forgotten · Remember again` (the button is the card's action)
  return task && task.forgotten ? `Forgotten ${task.forgotten}: no memory block carries it and no search finds it` : null;
}

export function pinText(task, selection) {
  // decision 13: what you selected inside that card's result, else the whole result as the card shows it
  const picked = String(selection || "").trim();
  if (picked) return picked;
  return task && resultShown(task) ? String(task.result || "").replace(/\s+$/, "") : "";
}

export function projectChoice(task, projects, picked = null) {
  // decisions 13 and 14: the task's own project, else a select of the registered ones with none chosen until you pick
  const own = task && task.project;
  return { fixed: !!own, chosen: own || picked || null, options: own ? [] : (projects || []).map((p) => p.name) };
}

export function charCount(text) {
  // characters as the router counts them (Python's len: code points), never the browser's UTF-16 units
  const s = String(text || "");
  let n = s.length;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff && i + 1 < s.length) {
      const d = s.charCodeAt(i + 1);
      if (d >= 0xdc00 && d <= 0xdfff) { n--; i++; }
    }
  }
  return n;
}

export function pinSheetView(task, projects, { project = null, text = "", notes = null, running = false, failure = null, demo = false,
  refused = null } = {}) {
  const choice = projectChoice(task, projects, project);
  // break-ui: a text longer than the notes can hold is never sent (a 2 MB result met the server's 413); the router's max
  const chars = notes && String(text).length > notes.max ? charCount(text) : 0;
  const tooLong = !!notes && chars > notes.max;
  const size = !choice.chosen ? "Pick the project whose notes get it." : !notes ? "Reading the project's notes…"
    : tooLong ? `The text is ${count(chars)} characters; a project's notes hold at most ${count(notes.max)}. Select the part of the result to pin.`
    : `Its notes now: ${count(notes.chars)} of ${count(notes.max)} characters, ${count(notes.lines)} ${notes.lines === 1 ? "line" : "lines"}.`;
  return { title: `Pin #${task.n} to notes`, ...choice, size, sizeTone: tooLong ? "bad" : null, tooLong, failure, saving: running,
    heading: `### Pinned from #${task.n} (<today>)`,
    canSave: !!choice.chosen && !!String(text).trim() && !tooLong && !refused && !running && !demo, foot: demo ? "Demo: nothing runs." : null };
}

export function saveSheetView(task, projects, { project = null, path = null, running = false, failure = null, demo = false,
  refused = null } = {}) {
  const choice = projectChoice(task, projects, project);
  const typed = path == null ? (task.save_path || "") : String(path);
  return { title: `Save #${task.n} to a project`, ...choice, path: typed, failure, saving: running,
    hint: "A new .md or .txt file inside the project's folder; one commit with HANDOFF.md's entry. A file already there is never overwritten.",
    canSave: !!choice.chosen && !!typed.trim() && !refused && !running && !demo, foot: demo ? "Demo: nothing runs." : null };
}

export function callNotesLines(show) {
  // decision 10: Details, "What the agents were given": each call's router notes, its sections and their characters
  const titles = Object.fromEntries(NOTES_SECTIONS);
  return ((show && show.calls) || []).filter((c) => c.router_notes).map((c) => {
    const r = c.router_notes;
    const who = callWho(c);
    if (r.left_out) return `${who}: router notes left out (over Grok's limit)`;
    const parts = Object.entries(r.sections || {}).map(([k, v]) => `${titles[k] || k} ${count(v)}`);
    return `${who}: router notes · ${parts.join(" · ")}${r.judge ? " · the judge line" : ""}${r.planner ? " · the planner part" : ""}`;
  });
}

export function callSpecLines(show) {
  // brief 33.2 (decision 2.7): Details, "What the agents were given": each call's SPEC.md as sent (its characters, the
  // judge line on a judging call) or left out for Grok's limit
  return ((show && show.calls) || []).filter((c) => c.spec).map((c) => {
    const who = callWho(c);
    if (c.spec.left_out) return `${who}: SPEC.md left out (over Grok's limit)`;
    const judge = ["check", "recheck"].includes(c.kind) || ["attack", "review"].includes(c.role);
    return `${who}: SPEC.md · ${count(c.spec.chars)} characters${judge ? " · the judge line" : ""}`;
  });
}

export function firstRunItems(status) {
  // the first-run card: every light that is grey or red, with its reason (rules: Setup)
  if (!status) return [];
  // an unknown light (not checked yet) is not a setup problem (break-ui, 21 Oct)
  // brief 27 (decision 12): memory joins only when it is a setup problem (not installed), never for off
  return setupRows(status).filter((r) => (r.key === "memory" ? r.problem
    : (r.tone === "bad" || r.tone === "muted") && !["not checked", "unknown"].includes(r.state)))
    .map((r) => ({ key: r.key, name: r.name, reason: r.detail || r.state, without: r.without }));
}

export function logFolderView(folder, tasks) {
  const task = (tasks || []).find((t) => t.task_id === folder.task_id);
  return { task_id: folder.task_id, title: task ? `#${task.n} · ${task.task_id}` : folder.task_id, when: task ? task.created_at : null,
    files: (folder.files || []).map((f) => ({ path: f.path, name: roundName(f), file: f })) };
}

// ---------- the cleanup (G, the owner's six): one-line words for the agent bar and a card ----------

export function pillWords(agent, view) {
  // the agent bar's text status beside the light: the state, and why when a safety check turned the agent off
  if (agent && agent.available === false && agent.why_code === "probe_failed") return "off · safety check";
  return view.state;
}

export function taskTime(task, now = new Date().toISOString()) {
  // how long the agents have taken: to now while it runs, to its last change once it waits on you or ends
  const running = isOpenTask(task) && !YOUR_TURN.includes(task.waiting_on);
  return elapsed(task.created_at, running ? now : task.updated_at);
}

const capital = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

export function notesWords(task) {
  // brief 29.1 (decision 14): a passed check's notes ride under its verdict, folded: " · 2 notes"
  const n = ((task && task.notes) || []).length;
  return n ? ` · ${n} ${n === 1 ? "note" : "notes"}` : "";
}

export function blockedWhat(task) {
  // brief 29.1 (decision 17): what the doer needed, from the note the router wrote (`blocked: <what>`)
  return String((task && task.check_note) || "").split("; ")[0].replace(/^blocked: /, "") || "what it wasn't given";
}

export function foldOpen(folds, taskId, name) {
  // break-ui (the owner, 27 Oct): each poll draws the cards again, so a fold is drawn as the owner left it, by its task
  // and its own name (notes, board, review-a, handoff-b, panel-handoff)
  return folds.has(`${taskId}:${name}`);
}

export function foldToggled(folds, taskId, name, open) {
  const next = new Set(folds);
  if (open) next.add(`${taskId}:${name}`);
  else next.delete(`${taskId}:${name}`);
  return next;
}

const numbered = (m) => ({ n: m.n, text: m.text });  // break-ui: the list draws the checker's number, once ("3. 4. …")

export function checkItems(task) {
  // brief 29.1: what sits under the verdict: a pass's notes (folded; the verdict has their count), or the musts a failed
  // check left open
  if (!task) return null;
  if (task.outcome === "failed_check" && (task.open_musts || []).length) {
    return { kind: "musts", title: "Still open", folded: false, items: task.open_musts.map(numbered) };
  }
  if (["passed", "fixed"].includes(task.outcome) && (task.notes || []).length) {
    return { kind: "notes", title: task.notes.length === 1 ? "Show the note" : "Show the notes", folded: true,
      items: task.notes.map(numbered) };
  }
  return null;
}

export function blockedOffer(task) {
  // brief 29.1 (decision 17): the Blocked card's one offer: Run again puts the task's text in the composer, so the owner
  // adds what was missing and sends it themselves; nothing runs from here
  if (!task || task.outcome !== "blocked") return null;
  return { what: blockedWhat(task), text: task.text, project: task.project || null, chat: task.chat || null,
    noFiles: !!task.text_only,  // brief 33.4 (decision 9b): a blocked draft stays text only
    note: "Run again puts this task's text in the box below: add what it needed, then send it." };
}

// brief 33.2 fix 2 (the owner's decision 2): what a spec save that ended well reads again, so the plan card's spec line,
// What now? and Approve's confirm show the router's new answer at once: the status (the server drops its kept copy at the
// run's end), the log (the rows the confirm reads), What now?, and the shows of the project's plans that wait (the card
// reads its show first, and the poll re-reads a waiting plan's show only when its row moves)
export const SPEC_SAVE_READS = ["status", "log", "what_now", "shows"];

export function specSaveReads(code) {
  return code === 0 ? SPEC_SAVE_READS.slice() : [];
}

export const STALE_PLAN_LINE = "The plan couldn't be re-read: this is the page's last copy of it.";

export function rereadsBeforeConfirm(task, request) {
  // brief 33.2 fix 2: a plan's Approve reads the plan again (`sr show <n> --json`) before its confirm opens, so a spec
  // changed from Terminal since the page's last read is caught
  return !!task && task.mode === "plan" && !!request && request.action === "land" && !request.anyway;
}

export function approveConfirm(cached, fresh) {
  // the task the confirm reads: the page's row with the fresh show's plan, or the row as it is with one line when the
  // re-read failed (Approve is never blocked on a read)
  if (!fresh || !fresh.plan) return { task: cached, note: STALE_PLAN_LINE };
  return { task: { ...cached, plan: fresh.plan }, note: null };
}

export function confirmExtra(task, request) {
  // brief 29.1 (decision 21): Land anyway's confirm says the check didn't pass and lists what it left open
  if (!request || request.action !== "land") return null;
  if (!request.anyway) {  // brief 33.2 (decision 7.1): a plan's Approve says the spec moved since the plan read it
    const plan = task && task.mode === "plan" ? task.plan : null;
    const lines = [plan && plan.spec_changed ? `${SPEC_CHANGED_LINE}: the plan read the earlier one.` : null,
      plan && plan.section_edited ? SECTION_EDITED_LINE : null].filter(Boolean);  // brief 33.4 (decision 6b)
    return lines.length ? { line: lines.join(" "), musts: [] } : null;
  }
  const musts = ((task && task.open_musts) || []).map(numbered);
  return { line: musts.length ? "Its check didn't pass. Still open:" : "Its check didn't pass.", musts };
}

export function verdictLine(task, show) {
  // the checker bar as one line; the raw notes and errors are behind Details
  const checker = agentLabel(task.checker);
  const agent = agentLabel(task.agent);
  if (task.mode === "auto" && task.auto) {  // brief 34 (decision 12): the run's own words
    const a = task.auto;
    const tones = { running: "info", stopped: "warn", finished: "warn", landed: "ok", discarded: "muted", undone: "muted" };
    const total = (a.steps || []).length;
    const text = a.state === "landed" ? `Auto landed · ${total} step${total === 1 ? "" : "s"}` : a.words || "Auto";
    return { tone: tones[a.state] || "muted", text };
  }
  // the small UI cleanup, row 4 (note 8): the change is gone, so "passed" in green no longer tells the story
  const gone = task.project_files && task.project_files.state;
  if (gone === "undone" || gone === "discarded") return { tone: "muted", text: capital(gone) };
  if (isOpenTask(task)) {
    if (task.waiting_on === "grok") {
      const grok = grokWait(task);
      const note = grok.note.replace(/^(waiting|overdue): grok, /, (m, word) => (word === "overdue" ? "overdue, " : ""));
      return { tone: grok.tone, text: `Waiting on Grok${note ? ` · ${note}` : ""}` };
    }
    if (task.waiting_on) {
      const of = task.piece_of && ["pick", "vote_pick"].includes(task.waiting_on)  // brief 29 (decision 10)
        ? ` · piece ${task.piece_of.piece} of split #${task.piece_of.n}: the join waits for it` : "";
      return { tone: YOUR_TURN.includes(task.waiting_on) ? "warn" : "info", text: capital(stateWords(task)) + of };
    }
    return { tone: "info", text: task.working && task.working.doing ? `Working · ${task.working.doing}` : "Working" };
  }
  if (task.waiting_on === "land") return { tone: "muted", text: capital(stateWords(task)) };  // row 4 (note 14): calm, its bright Land says it's your turn
  if (task.no_split) return { tone: "muted", text: "No split · route it instead" };  // brief 29 (decision 3): an answer
  if (task.one_step) return { tone: "muted", text: "One step · build it instead" };  // brief 33.1 (decision 6): an answer
  const tally = show && show.tally;
  switch (task.outcome) {
    case "passed": {
      if (tally && tally.winner) {
        const won = ((show && show.votes) || []).find((v) => v.letter === tally.winner);
        return { tone: "ok", text: `${won ? won.answer : "Agreed"} · ${tally.for} of ${tally.for + tally.against} agree` };
      }
      return { tone: "ok", text: (task.preset === "vote" ? "Passed by vote" : `Passed · ${checker}`) + notesWords(task) };
    }
    case "fixed": return { tone: "ok", text: `Fixed · ${checker}, round 2${notesWords(task)}` };
    case "blocked": return { tone: "warn", text: checker ? `Blocked · ${checker}` : "Blocked" };  // brief 29.1 (decision 17);
    // break-ui: what it needed is said once, in the Blocked offer under the verdict
    case "picked": {
      if (!show) return { tone: "ok", text: "Picked" };  // the pick is in the details, not loaded yet
      const pick = show.pick;
      const cand = ((show && show.candidates) || []).find((c) => c.letter === pick);
      return { tone: "ok", text: pick && pick !== "none" ? `Picked ${pick.toUpperCase()}${cand ? ` · ${agentLabel(cand.builder)}` : ""}` : "Closed with no pick" };
    }
    case "unchecked": {
      if (task.skill === "quick_answer") return { tone: "muted", text: "Unchecked · a quick answer needs no check" };
      const failed = ((show && show.calls) || []).some((c) => (c.kind === "check" || c.kind === "recheck") && c.status === "failed");
      return { tone: "warn", text: failed && checker ? `Unchecked · ${checker}'s check didn't run` : "Unchecked" };
    }
    case "failed_check": return { tone: "bad", text: `Failed twice · ${checker}` };
    case "tie": return { tone: "warn", text: "A tie · your pick, unchecked" };
    case "cancelled": return { tone: "muted", text: "Cancelled" };
    case "timed_out": return { tone: "muted", text: "Timed out" };
    case "returned": return { tone: "muted", text: "Came back to you" };
    case "plan_limit": return { tone: "warn", text: `Stopped · plan limit${agent ? ` on ${agent}` : ""}` };
    case "process_ended": return { tone: "warn", text: `Stopped · process ended${agent ? ` (${agent})` : ""}` };
    default: return { tone: "bad", text: capital(stateWords(task)) };
  }
}

export function lateWords(late) {
  // brief 24 (decision 7): an overdue Grok call's answer, kept and never used
  if (!late) return null;
  if (late.state === "arrived") return "late answer: Grok Bot's answer came after the takeover; kept, not used";
  if (late.state === "out") return "late answer: Grok Bot's answer may still come; it won't be used";
  return "late answer: none came";
}

export function detailNotes(task, show) {
  // the raw words behind Details: the router's note, its route reason, a failed call's reason, the stopped stage
  const notes = [];
  if (task.check_note) notes.push(`note: ${task.check_note}`);
  if (task.route_reason && !["best", "relay", "split"].includes(task.route_reason)) notes.push(`route: ${task.route_reason}`);
  if (task.failed_stage) notes.push(`stopped at stage ${task.failed_stage}`);
  if (task.takeover) notes.push(`takeover: ${agentLabel(task.takeover.to)} took over ${task.takeover.call} (${task.takeover.why})`);
  if (task.late) notes.push(lateWords(task.late));
  for (const c of (show && show.calls) || []) {
    if (c.status === "failed") notes.push(`${roleWords(c.kind === "stage" || c.kind === "reask" ? c.role : c.kind)} · ${agentLabel(c.agent)} failed${c.reason_code ? ` (${c.reason_code.replace(/_/g, " ")})` : ""}`);
  }
  return notes;
}

// ---------- UI-1 (phase 1 of the UI rebuild): new pure functions, added row by row; none of the above changed ----------

export function confirmFocusId(task, request) {
  // UI-1 row 16 (D14b), UI A N4 (A10): Enter must not end something by accident, so the focus starts on Keep it on Discard
  // (Plan Reject sends the same request), Cancel, Skip, Neither and a split's Reject; Confirm on a pick, an Approve and the rest.
  const id = task && task.task_id;
  const a = request && request.action;
  const keep = a === "discard" || a === "cancel" || a === "split_skip" || (a === "pick" && request.choice === "none")
    || (a === "split_go" && request.choice === "n");
  return keep ? `keep-${id}` : `confirm-${id}`;
}

// UI-1 row 13 (D4, D5): a step of an Auto run as one line
const STEP_CHECK_WORDS = {
  passed: "passed · checked: ok", fixed: "fixed · check found an issue, fixed in round 2", running: "running · check: not yet",
  unchecked: "unchecked · not checked" };

export function autoStepLine(step, planSteps) {
  // UI-1 row 13 (D4, D5): one line of an Auto run: its step's text from the project's plan when that plan is the run's,
  // else "Step k"; its state and the check's result in words (never colour alone); its task and its calls
  const s = step || {};
  const found = (planSteps || []).find((p) => p && p.k === s.k && p.text);
  const state = s.state === "done" ? (s.covered === false ? "before" : s.outcome === "unchecked" ? "unchecked"
    : s.verdict === "fixed" ? "fixed" : "passed") : s.state || "open";
  const words = STEP_CHECK_WORDS[state] || (state === "before" ? "done before the run · not part of it"
    : state === "open" ? "open · not started" : state === "retried" ? "failed twice, retried · check: failed"
      : state === "failed" ? "failed twice · check: failed" : state === "stopped" ? "stopped · check: not finished" : state);
  return { k: s.k, text: found ? found.text : `Step ${s.k}`, team: s.team ? teamLabel(s.team) : null, state, words,
    attempt: s.attempt > 1 ? `${s.attempt} attempts` : null, taskId: s.task_id || null, n: s.n == null ? null : s.n,
    calls: `${count(s.calls || 0)} call${(s.calls || 0) === 1 ? "" : "s"}`, covered: s.covered !== false };
}

export function planNoteWords(task) {
  // UI-1 row 12 (D16): the plan card's note from the server's own fields (the changed paths and the branch); a missing
  // field's part is left out
  const f = (task && task.project_files) || {};
  const paths = (f.changed || []).map((c) => c.path).filter(Boolean).join(", ");
  return `Approve lands ${paths || "it"} as one commit${f.branch ? ` on ${f.branch}` : ""}; Reject drops it`;
}

export function planStepLines(step) {
  // UI-1 row 12 (D16): a step read first, as two quiet lines: "Write the new footer · route · done when: …" and
  // "Why: … · covers: E1 · 3 calls"; a step with no covers says nothing about covers
  const one = [step.team, step.doneWhen ? `done when: ${step.doneWhen}` : null].filter(Boolean).join(" · ");
  const two = [step.why ? `Why: ${step.why}` : null, step.covers && step.covers !== "none" ? `covers: ${step.covers}` : null,
    step.calls || null].filter(Boolean).join(" · ");
  return { one, two };
}

// the card's outcome word (UI-1 row 11, D7; the small UI cleanup, row 3)
const OUTCOME_WORDS = { passed: "passed", fixed: "fixed in round 2", unchecked: "unchecked", failed_check: "failed its check",
  blocked: "blocked", picked: "picked", tie: "a tie", cancelled: "cancelled", timed_out: "timed out", stopped: "stopped",
  plan_limit: "hit its plan limit", process_ended: "its process ended", returned: "came back to you" };

export function cardLine(task, show, { time = false, now = new Date().toISOString() } = {}) {
  // The card's one row (the small UI cleanup, row 3): the step pills, then only the outcome in its colour and the time when asked
  // (the newest and running cards). `#n` and the team sit under the bubble; a running card has its running pill and no words
  if (!task) return null;
  const stages = stagesView(task, show).filter((s) => s.key !== "jev");
  const verdict = verdictLine(task, show);
  // UI A row 3 (A18): No split and One step are answers, not stops: their outcome is `stopped`, so their own words come first
  const end = isOpenTask(task) || task.auto ? (task.waiting_on || task.auto ? verdict.text : "")
    : task.no_split || task.one_step || ["undone", "discarded"].includes(task.project_files && task.project_files.state) ? verdict.text
    : OUTCOME_WORDS[task.outcome] ? OUTCOME_WORDS[task.outcome] + (task.outcome === "passed" ? notesWords(task) : "") : verdict.text;
  const said = task.auto ? end  // brief 34 (decision 12): a run's own words, whole
    : task.waiting_on === "land" && task.mode !== "plan" ? "ready to land" : end;  // UI A row 11 (A19)
  return { pills: stepPills(task, show), text: task.auto ? said : said.charAt(0).toLowerCase() + said.slice(1), tone: verdict.tone,
    time: time ? taskTime(task, now) : null,
    files: stages.filter((s) => s.file).map((s) => ({ label: [s.label, s.agent ? agentLabel(s.agent) : null].filter(Boolean).join(" · "), file: s.file })) };
}

// UI-1 row 10 (D14a): the confirm's words
export function confirmWords(task, request, show = null) {
  // UI-1 row 10 (D14a), UI A row 13 (A10): the confirm's question in words, from fields the server sent and nothing worked
  // out; `show` holds a split's pieces. Null keeps today's form for every other action
  if (!task || !request) return null;
  const f = task.project_files || {};
  const on = f.branch ? ` on ${f.branch}` : "";
  const n = `#${task.n}`;
  const paths = (f.changed || []).map((c) => c.path).filter(Boolean).join(", ");
  if (task.mode === "plan") {
    if (request.action === "land" && request.anyway) return `Approve plan ${n} anyway? Its check didn't pass; ${paths || "the plan"} lands${on} as it is.`;
    if (request.action === "land") return `Approve plan ${n}? ${paths || "The plan"} lands${on} as one commit.`;
    if (request.action === "discard") return `Reject plan ${n}? ${paths || "The plan"} is dropped; nothing lands.`;
  }
  if (task.mode === "auto" && task.auto) {
    const so = task.auto.state === "stopped";
    if (request.action === "land") return so ? `Land run ${n} so far? The steps it passed land${on} as one commit.`
      : `Land run ${n}? The whole run lands${on} as one commit.`;
    if (request.action === "discard") return `Discard run ${n}? Its change never lands.`;
    if (request.action === "undo") return `Undo run ${n}?${f.commit ? ` A new commit puts back ${shortId(f.commit)}.` : ""}`;
  }
  if (request.action === "land" && request.anyway) return `Land ${n} anyway? Its check didn't pass; it lands${on} as it is.`;
  if (request.action === "land") return `Land ${n}? Its change lands${on} as one commit.`;
  if (request.action === "discard") return `Discard ${n}'s change? It never lands.`;
  if (request.action === "undo") return `Undo ${n}?${f.commit ? ` A new commit puts back ${shortId(f.commit)}.` : ""}`;
  if (request.action === "cancel") return `Cancel ${n}? It stops, and nothing more is sent.`;
  if (request.action === "pick") {
    if (request.choice === "none") return `Close ${n} with no pick? No answer is kept as the result.`;
    const letter = String(request.choice).toUpperCase();
    if (task.preset === "vote") return `Pick ${letter} for ${n}? It's delivered unchecked.`;
    const who = agentLabel((task.slots || {})[request.choice]) || `Candidate ${letter}`;
    return `Pick ${letter} for ${n}? ${who}'s ${f.candidates ? "change waits for you to land it" : "answer becomes the result"}.`;  // rules: the pick keeps that copy waiting
  }
  if (request.action === "split_skip") {
    const piece = ((show && show.pieces) || []).find((p) => p.task_id === request.task_id);
    return `Skip ${piece ? `piece ${piece.piece}` : "this piece"} of split ${n}? The split goes on without it.`;
  }
  if (request.action === "split_go") {
    if (request.choice === "n") return `Reject split ${n}? Nothing runs.`;
    const k = ((show && show.pieces) || []).length;
    return `Run split ${n}? Its ${k ? `${k} pieces start` : "pieces start"} now.`;
  }
  return null;
}

// UI-1 row 8 (D12): the status chip's words
export function chipWords(status, tasks = []) {
  // UI-1 row 8 (D12): the header chip counts the agents that can work now and names the most fixable problem, then counts
  // the rest. Bad (signed out, safety check) before muted (not set up), then the popover's order. Jev counts only when it
  // blocks routing; Memory never counts. Tone: warn while anything is down, bad at 0 up, none when all is well.
  if (!status) return null;
  const agents = (status.agents || []).map((a) => ({ a, view: agentView(a, tasks, status.models) }));
  const up = agents.filter((x) => ["ok", "info", "warn"].includes(x.view.tone)).length;
  const problems = agents.map((x, i) => ({ x, i })).filter(({ x }) => !["ok", "info", "warn"].includes(x.view.tone))
    .map(({ x, i }) => ({ name: x.view.name, words: pillWords(x.a, x.view), bad: x.view.tone === "bad", order: i }));
  const jev = status.jev;
  if (jev && (!jev.configured || jev.over_cap)) {
    problems.push({ name: "Jev", words: jev.over_cap ? "over its cap" : "not set up", bad: !!jev.over_cap, order: agents.length });
  }
  problems.sort((p, q) => (p.bad === q.bad ? p.order - q.order : p.bad ? -1 : 1));
  const head = `${up} of ${agents.length} up`;
  const first = problems[0];
  const text = first ? `${head} · ${first.name} ${first.words}${problems.length > 1 ? ` and ${problems.length - 1} more` : ""}` : head;
  return { text, tone: !agents.length || up === 0 ? "bad" : problems.length ? "warn" : "none", up, total: agents.length,
    problems: problems.length };
}

// UI-1 row 4 (D13): the card's ⋯ menu and its main action
export function cardMenuItems(task) {
  // UI-1 row 4 (D13): the ⋯ menu's items: Run again as… (its own teams submenu) unless a failed card keeps it as
  // a button, then the card's quiet actions as the JSON offers them (cardActions)
  if (!task) return [];
  const items = [];
  if (!cardKeepsRunAgain(task)) items.push({ key: "again", label: "Run again as…", submenu: true });
  return items.concat(cardActions(task));
}

export function cardKeepsRunAgain(task) {
  // CardStatesA, UI A row 20 (A5): a failed card keeps Run again as… on the card, beside its main action; a blocked one has
  // Run again, and Run again as… sits in ⋯, since the two look alike and most of the second's items send at once
  return !!task && task.outcome === "failed_check";
}

export function cardMainAction(task, show = null, marks = [], ui = {}) {
  // UI-1 row 4 (D13), UI A N3 (A1, A2): the card's one main action, picked by a fixed priority from the offers the pure views
  // already return; never rebuilt. Every part of a card asks this before drawing a bright button. Files and an Auto run pick
  // only a button whose view says `tone: "primary"`, so Land anyway, Undo and "Land the run so far" are never bright.
  if (!task) return null;
  const asked = questionsCardView(task, ui.questions || {});
  if (asked && !asked.planning) return { key: "send_answers", label: "Send answers", from: "questions", request: asked.send, off: asked.sendOff };
  const spec = saveSpecView(task);  // the offer from the JSON, never the card's text
  if (spec) return { key: "save_spec", label: spec.label, from: "spec", request: spec.request };
  const plan = task.mode === "plan" ? planCardView(task, show, {}) : null;
  if (plan && plan.approve) return { key: "approve", label: "Approve plan", from: "plan", request: plan.approve };
  if (splitPlanView(task, show)) return { key: "approve_split", label: "Approve and run", from: "split", request: splitApprove(task, show, ui.choices || {}).request };
  const versus = versusBoard(task, show);
  if (versus && versus.picking) {  // the one card with two: Pick A and Pick B, each under its own answer
    return { key: "pick", label: "Pick A or Pick B", from: "versus", choices: versus.choices.filter((c) => c.choice !== "none").map((c) => c.choice) };
  }
  const one = oneStepView(task);
  if (one && one.chip) return { key: "build_it", label: "Build it", from: "one_step", chip: one.chip };
  if (blockedOffer(task)) return { key: "run_again", label: "Run again", from: "blocked" };
  const board = autoBoard(task, show, marks);
  const fromBoard = board && board.buttons.find((b) => b.tone === "primary");
  if (fromBoard) return { key: fromBoard.key, label: fromBoard.label, from: "auto", request: fromBoard.request };
  const files = fileView(task);
  const fromFiles = files && (files.buttons || []).find((b) => b.tone === "primary");
  if (fromFiles) return { key: fromFiles.key, label: fromFiles.label, from: "files", request: fromFiles.request };
  const rescue = rescueOffers(task).find((o) => o.tone === "primary");
  if (rescue) return { key: rescue.key, label: rescue.label, from: "rescue", request: rescue.request };
  return null;
}

// UI-1 row 3 (D9): Needs you capped
export function needsYouCut(rows, expanded = false, keep = 3) {
  // UI-1 row 3 (D9): Needs you shows its newest rows and an "n more" row that opens it in place; the label keeps the count
  const all = rows || [];
  const shown = expanded ? all.slice() : all.slice(0, keep);
  return { label: `Needs you · ${all.length}`, shown, more: all.length - shown.length };
}

// ---------- UI A: the cards, the composer and the boards ----------

const FILE_ENDED = new Set(["landed", "discarded", "undone"]);

export function cardFrame(task) {
  // UI A N2 (A3): the frame in the state's colour: bad, warn, info, grey, or null for none. The words stay in the top line.
  if (!task) return null;
  if (task.no_split || task.one_step) return "grey";  // their outcome is `stopped`, so this comes before the outcomes
  if (task.mode === "auto" && task.auto) return { running: "info", stopped: "warn", finished: "grey" }[task.auto.state] || null;
  const failedPlan = task.mode === "plan" && (task.check_state === "failed" || task.outcome === "failed_check");
  if (task.waiting_on) {
    if (failedPlan) return "bad";
    if (task.waiting_on === "grok") return grokWait(task).tone;  // blue until the router writes its note
    if (["needs_label", "auto"].includes(task.waiting_on)) return "warn";  // the Jev floor; a run that stopped
    if (["piece", "probe", "memory"].includes(task.waiting_on)) return "info";
    return "grey";  // land, a pick, a split's plan, questions
  }
  if (isOpenTask(task)) return "info";
  if (FILE_ENDED.has(task.project_files && task.project_files.state)) return null;
  if (task.outcome === "failed_check" || failedPlan) return "bad";
  if (task.outcome === "unchecked") return task.skill === "quick_answer" ? null : "warn";
  if (["blocked", "stopped", "plan_limit", "process_ended"].includes(task.outcome)) return "warn";
  if (task.reason_code === "not_routed" && !task.answered_by) return "warn";  // Send as
  return null;
}

export function contextTagWords(ctx, view) {
  // UI A row 15 (A12): the tag shows only when the send goes somewhere other than the view. A split's always shows: the
  // rules' tag line reads "Split: untagged" or "Split: project <name>"
  if (ctx.kind === "split") return ctx.value ? `Split: project ${ctx.value}` : "Split: untagged";
  if (ctx.kind === "plan") return ctx.value ? (view === "project" ? null : `Plan: project ${ctx.value}`) : "Plan: pick a project";
  if (ctx.kind === "quick") return view === "quick" ? null : "Quick task: untagged";
  if (ctx.kind === "project") return view === "project" ? null : `Project: ${ctx.value}`;
  return view === "chat" ? null : `Chat: ${ctx.value || "new"}`;
}

export function plusStates(ui, greys) {
  // UI A row 15 (A12): each + item's state, in words; a greyed item says why
  const n = (ui.files || []).length;
  const onOff = (on, why) => (why ? `Off · ${why}` : on ? "On" : "Off");
  return { attach: greys.files || (ui.demo ? "Demo: nothing runs" : n ? `${n} attached` : ""), web: onOff(ui.web, greys.web), quick: onOff(ui.quick, greys.quick) };
}

export function ideaPillWords(idea) {
  // UI A row 5 (A15): "Idea · footer copy", cut at about 30 characters; the whole text is on hover
  const text = String((idea && idea.text) || "").trim();
  if (!text) return "Idea";
  return `Idea · ${text.length > 30 ? `${text.slice(0, 30).trimEnd()}…` : text}`;
}

export function uncheckedWhy(task) {
  // UI A row 18 (A6): why a result went unchecked, the router's own words, outside Details; a quick answer needs no check
  if (!task || task.outcome !== "unchecked" || task.skill === "quick_answer") return null;
  return task.check_note || null;
}

// ---------- UI B: navigation, sheets and phone ----------

export function needsInHead(narrow, hidden, count) {
  // UI B N3 (Q6): "Needs you · n" joins the head when narrow, or wide with the sidebar hidden: it stays reachable at any width
  return count > 0 && (narrow || hidden);
}

export function sideFolds(saved) {
  // UI B N4: which sections are folded, from what's stored; anything malformed is ignored
  let found;
  try { found = JSON.parse(saved); } catch (e) { return {}; }
  if (!found || typeof found !== "object" || Array.isArray(found)) return {};
  return Object.fromEntries(["projects", "chats"].filter((key) => found[key] === true).map((key) => [key, true]));
}

export function settingsTabFor(focus) {
  // UI B N5: the Settings tab holding a Setup row
  return ["memory", "models", "notes"].includes(focus) ? focus : "setup";
}

export function modelRows(rows, { keep = 5 } = {}) {
  // UI B row 14 (board 3): rows you've set read "yours" and sort first, then rows with a choice (Cleanup 2, row 3); the first few
  // show, the rest fold
  const read = (rows || []).map((row) => ({ ...row, yours: !!row.chosen,
    current: row.words || (row.options.find((o) => o.selected) || row.options[0] || { label: "" }).label }));
  const hasChoice = (r) => !r.state || r.state === "choice";
  const sorted = [...read.filter((r) => r.yours), ...read.filter((r) => !r.yours && hasChoice(r)), ...read.filter((r) => !r.yours && !hasChoice(r))];
  return { shown: sorted.slice(0, keep), more: sorted.slice(keep), yours: read.filter((r) => r.yours).length };
}

export function railNext(key, { hidden, section }) {
  // UI B N2 (Q6): Chats or Projects opens the sidebar at that section; the lit icon hides it
  if (hidden) return { hidden: false, section: key };
  return section === key ? { hidden: true, section: key } : { hidden: false, section: key };
}

// ---------- the DOM (a browser only) ----------

const SVG = "http://www.w3.org/2000/svg";
const ICONS = {
  plus: "M12 5v14M5 12h14", chat: "M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2", book: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z",
  file: "M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M8 13h8M8 17h5",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19 12a7 7 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2L14 3h-4l-.4 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6A7 7 0 0 0 5 12c0 .4 0 .8.1 1.2l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2 1.2L10 21h4l.4-2.6a7 7 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.2-.8.2-1.2z",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z", x: "M18 6L6 18M6 6l12 12", copy: "M9 9h12v12H9zM5 15V5a2 2 0 0 1 2-2h10",
  check: "M20 6L9 17l-5-5", alert: "M12 3l9 16H3zM12 10v4M12 17h.01", code: "M16 18l6-6-6-6M8 6l-6 6 6 6",
  download: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3", reveal: "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3",
  logo: "M4 12h6M14 12h6M12 4v6M12 14v6", chevron: "M6 9l6 6 6-6", menu: "M4 6h16M4 12h16M4 18h16", key: "M15 7a4 4 0 1 0-3.9 5L4 19v2h3l1-1v-2h2v-2h2l.9-.9A4 4 0 0 0 15 7z",
};

function icon(name) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(SVG, "path");
  path.setAttribute("d", ICONS[name] || ICONS.file);
  svg.append(path);
  return svg;
}

function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = String(value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (value === true) node.setAttribute(key, "");
    else node.setAttribute(key, String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function setChildren(node, ...children) {
  node.replaceChildren(...children.flat(Infinity).filter((c) => c != null && c !== false)
    .map((c) => (c instanceof Node ? c : document.createTextNode(String(c)))));
}

const $ = (id) => document.getElementById(id);
const SHOW_DRAW_MS = 1000;
const showDraws = { at: 0, owed: false };  // the small UI cleanup, row 8

// ---------- talking to the server ----------

const META = (name) => (document.querySelector(`meta[name="${name}"]`) || {}).content || "";

const state = {
  sideHidden: false, sideSection: null, sideFolds: {},  // UI B N2, N4 (Q6): the rail and the sidebar
  modelsOpen: null, modelsFolds: new Set(), settingsTab: "setup",  // UI B N5, row 14
  suggesting: new Set(),  // brief 33.4 (decision 13): the projects with a suggest this page started and is waiting on
  questionsUi: new Map(),  // brief 33.4 (decision 14): a waiting plan's picks and Other text, by task, until it's sent
  autoRun: null, autoAsk: null, markRuns: new Set(),  // brief 34: the Auto switch's run in flight, its confirm, the toggles' runs
  token: "", demo: false, reveal: false,
  whatNow: null,  // brief 33 (decision 13): {project, line}, the router's What now? for the open project
  status: null, statusAt: 0, statusError: null,
  tasks: [], logError: null, nextBefore: null,
  chatDraft: "",  // Cleanup 2, row 14: a new chat's typed name, used at its first send
  viewRead: null,  // Cleanup 2, row 1: { key, tasks, next, pages, loading, error }, the open chat's or project's own read
  chat: null, project: null, quick: false, team: "route", slots: {}, view: "chat",
  historyQuery: { chat: null, project: null, search: "" }, historyTasks: [], historyNext: null, historyPages: 1, historyError: null,
  logFolders: [], logNext: null, logError: null, setupText: null, setupError: null, setupChecking: false, setupFocus: null,
  sheetKind: null, ideasSheet: null, np: null, madeProjects: new Set(), testing: new Set(), outputTimer: null, runBusy: new Set(), rc: null, pc: null, sc: null, setupOpen: new Map(), memRun: null, memFailure: null, memCmd: null, teamMenu: false, stripOpen: null, detailsOpen: new Set(), folds: new Set(), navOpen: false,
  text: "", files: [], web: false, skill: null,
  models: null,  // brief 33.3 (decision 12): the task's model choices {agent: id} from the Models sheet; null while the defaults apply
  modelsSheet: null, modelsRun: null, modelsSaid: null, fableRun: null, fableFailure: null,  // the sheet; Setup's row: a select's run, the answer, the switch's run and refusal
  step: null,  // brief 33.1 (decision 12): the Step pill, {plan, n, k}, set only by a Build step chip
  planEdit: null,  // brief 33.1 (decision 11): {taskId, k, field, text} while a step's text or finish line is edited
  command: null, commandSeq: 0,
  pending: [], refused: [], sessionTasks: [],
  restarted: false, lastRouteTask: null, sending: false,
  theme: "auto", toastTimer: null,
  shows: new Map(), filesOf: new Map(), loading: new Set(), menu: null, streamView: null,
  panel: null, runs: [],
  confirm: null, actions: [], starting: new Set(), actionErrors: new Map(), splitChoices: new Map(), notified: new Set(), notifyReady: false,
  splitEdit: null, splitEditCommand: "",  // brief 29 (decision 18a): the one piece being edited, and the command Save runs
  splitEditSaved: null,  // C4: the text a Save sent, until its run answers (a refusal opens it again)
  routing: new Set(), routeItSkills: new Map(),  // brief 29, C4: Route it's send in flight per card, and its picked skill
  routedFrom: new Map(),  // brief 29.1 (decision 7d): a No split card that sent: the run, then the task it made
  focusTask: null, heldCard: null,
};

async function api(path, { method = "GET", body = null, raw = false } = {}) {
  const headers = { "X-SR-Token": state.token };
  if (body != null) headers["Content-Type"] = "application/json";
  let resp;
  try {
    resp = await fetch(path, { method, headers, cache: "no-store", body: body == null ? undefined : JSON.stringify(body) });
  } catch (e) {
    throw Object.assign(new Error("The page server is not answering. Is `sr serve` still running?"), { offline: true });
  }
  if (resp.status === 403) {
    const doc = await resp.json().catch(() => ({}));
    if (doc.error === "token") {
      state.restarted = true;
      renderBanners();
    }
    throw Object.assign(new Error(doc.message || "Refused by the page server."), { status: 403 });
  }
  if (raw) return resp;
  const doc = await resp.json().catch(() => null);
  // the server's words: `message` beside a short `error` code (403, the demo's 409), else `error` holds them
  if (!resp.ok) throw Object.assign(new Error((doc && (doc.message || doc.error)) || `HTTP ${resp.status}`), { status: resp.status, doc });
  return doc;
}

// ---------- rendering ----------

function renderBanners() {
  const items = [];
  if (state.restarted) {
    items.push(h("div", { class: "banner bad", role: "alert" }, h("strong", { text: "The page server restarted: reload." }),
      h("span", { text: "This page still holds the old server's key." }),
      h("button", { class: "btn btn-primary", type: "button", onclick: () => location.reload() }, "Reload")));
  }
  if (state.demo) {
    items.push(h("div", { class: "banner" }, h("strong", { text: "Demo: sample tasks, nothing runs." }),
      h("span", { text: "Every task, agent and answer here is invented. Send is off." })));
  }
  if (state.statusError && !state.restarted) {
    items.push(h("div", { class: "banner warn" }, h("strong", { text: "The router's status could not be read." }),
      h("span", { text: state.statusError })));
  }
  setChildren($("banners"), items);
}

function renderStrip() {
  // The small UI cleanup, row 6 (note 26): one box per item, a round light and a name, with Jev's count; the words and details are on
  // hover and in the list a click on any box opens. A problem is the light's colour and an outline. `state.stripOpen` holds the box clicked
  const status = state.status;
  if (!status) {
    setChildren($("strip"), h("div", { class: "strip-row" }, h("span", { class: "agent-box tone-muted" }, h("span", { class: "light", "aria-hidden": "true" }),
      h("span", { class: "agent-name", text: state.statusError ? "the router's status is unreadable" : "loading…" }))));
    return;
  }
  const items = (status.agents || []).map((agent) => {
    const view = agentView(agent, state.tasks, status.models);  // brief 33.3: Opus and Fable calls this week under Claude
    return { key: agent.name, tone: view.tone, name: view.name, words: pillWords(agent, view), detail: view.detail.join(" · ") };
  });
  const jev = jevView(status.jev);
  const jevUnknown = status.jev == null;
  items.push({ key: "jev", tone: !jev.configured ? "muted" : jev.over ? "bad" : "ok", name: "Jev", count: jev.configured ? jev.text : null,
    words: jevUnknown ? "unknown" : jev.configured ? jev.text : "not set up",
    detail: jevUnknown ? "not checked yet" : !jev.configured ? "no JEV_API_KEY in .env" : jev.over ? "over this month's cap: routed tasks wait for your label" : "tokens this month against the cap" });
  const memory = memoryView(status.memory, { turningOn: !!(state.memRun && state.memRun.to === "on") });
  items.push({ key: "memory", tone: memory.tone, name: "Memory", words: memory.state, detail: memory.detail, link: memoryLink(memory) });
  const chip = chipWords(status, state.tasks);
  const open = !!state.stripOpen;
  const linkOf = (item) => (item.key === "memory" ? item.link : item.tone === "bad" || item.tone === "muted" ? "How to set it up" : null);
  const said = (item) => [item.name, item.words, item.detail].filter(Boolean).join(" · ");
  const active = document.activeElement;  // Cleanup 2, row 17 (note 2): a status redraw leaves the keyboard's focus on its box
  const focused = active && active.id && String(active.id).startsWith("agent-box-") ? active.id : null;
  setChildren($("strip"), h("div", { class: "strip-row" }, headNav(),
    items.map((item) => h("button", { class: `agent-box tone-${item.tone}`, type: "button", id: `agent-box-${item.key}`, "aria-haspopup": "dialog",
      "aria-expanded": state.stripOpen === item.key ? "true" : "false", title: said(item), "aria-label": said(item),
      onclick: (e) => {
        e.stopPropagation();  // or the list would close itself as it opens, so an open ⋯, Project or Run again as… closes here (Cleanup 2, row 16)
        const menuOpen = !!state.menu;
        state.menu = null;
        state.menuSub = null;
        state.stripOpen = open ? null : item.key;
        renderStrip();
        if (menuOpen) renderStream({ follow: false });
      } },
    h("span", { class: "light", "aria-hidden": "true" }), h("span", { class: "agent-name", text: item.name }),
    item.count ? h("span", { class: "agent-state", text: item.count }) : null)),
    open ? h("div", { class: "status-pop", role: "dialog", "aria-label": "Agent status" },
      h("div", { class: "status-head", text: chip.text }),
      items.map((item) => h("div", { class: `status-row tone-${item.tone}` },
        h("span", { class: "light", "aria-hidden": "true" }),
        h("span", { class: "status-name", text: item.name }),
        h("span", { class: "status-words" }, [item.words, item.detail].filter(Boolean).join(" · "),
          linkOf(item) ? [" · ", h("button", { class: "linklike", type: "button", dataset: { focusKey: `status-${item.key}` },
            onclick: () => { state.stripOpen = null; renderStrip(); openSetup(item.key); } }, linkOf(item))] : null))),
      h("div", { class: "status-foot", text: "A row's link opens its steps in Settings." })) : null));
  if (focused) {
    const box = document.getElementById(focused);
    if (box) box.focus({ preventScroll: true });
  }
}

function isNarrow() {
  return window.innerWidth <= 900;  // app.css's breakpoint
}

function headNav() {
  // UI B N3 (Q6, Q11): at 900 px and under, Menu sits at the top left of the pinned strip; "Needs you · n" joins it there, and on
  // a wide window while the sidebar is hidden
  const narrow = isNarrow();
  const count = needsYouList(state.tasks).you.length;
  const parts = [];
  if (narrow) {
    parts.push(h("button", { class: "side-item", type: "button", "aria-expanded": state.navOpen ? "true" : "false", "aria-label": "Menu",
      onclick: () => toggleNav() }, icon("menu"), h("span", { class: "name", text: state.navOpen ? "Close" : "Menu" })));
  }
  // UI B's live check: the side panel takes the sidebar's place on a wide window, so Needs you moves up then too
  if (needsInHead(narrow, state.sideHidden || !!state.panel, count)) {
    parts.push(h("button", { class: "needs-head", type: "button", onclick: () => { if (narrow) toggleNav(); else if (state.panel) closePanel(); else railPress(sideSection()); } },
      icon("alert"), h("span", { text: `Needs you · ${count}` })));
  }
  return parts.length ? h("div", { class: "narrow-bar" }, parts) : null;
}

function sideSection() {
  return state.sideSection || (state.project ? "projects" : "chats");
}

function readSidePrefs() {
  // UI B N2: what the sidebar remembers; a browser that blocks storage just starts from the defaults
  try { state.sideHidden = localStorage.getItem("sr-side-hidden") === "1"; } catch (e) { state.sideHidden = false; }
  try { state.sideFolds = sideFolds(localStorage.getItem("sr-side-folds")); } catch (e) { state.sideFolds = {}; }
}

function railPress(key) {
  const next = railNext(key, { hidden: state.sideHidden, section: sideSection() });
  state.sideHidden = next.hidden;
  state.sideSection = next.section;
  if (!next.hidden && state.sideFolds[key]) state.sideFolds = { ...state.sideFolds, [key]: false };  // N4: it opens at that section
  try { localStorage.setItem("sr-side-hidden", next.hidden ? "1" : "0"); } catch (e) { /* it just isn't remembered */ }
  renderRail();
  renderStrip();
  renderSidebar();
  if (!next.hidden) { const at = $(`side-section-${key}`); if (at) at.scrollIntoView({ block: "start" }); }
}

function renderRail() {
  // UI B N2 (Q6, board 4): the rail always shows above 900 px: New chat, Chats, Projects, Settings
  const lit = (key) => !state.sideHidden && sideSection() === key;
  const item = (label, iconName, props) => h("button", { class: "rail-item", type: "button", title: label, ...props }, icon(iconName), h("span", { text: label }));
  setChildren($("rail"),
    item("New chat", "plus", { onclick: newChat }),
    item("Chats", "chat", { class: `rail-item${lit("chats") ? " lit" : ""}`, "aria-expanded": lit("chats") ? "true" : "false", onclick: () => railPress("chats") }),
    item("Projects", "folder", { class: `rail-item${lit("projects") ? " lit" : ""}`, "aria-expanded": lit("projects") ? "true" : "false", onclick: () => railPress("projects") }),
    item("Settings", "gear", { class: `rail-item${state.view === "settings" ? " lit" : ""}`, "aria-current": state.view === "settings" ? "page" : null, onclick: () => openSettings() }));
  $("app").classList.toggle("side-hidden", !!state.sideHidden);
}

async function openSettings(tab = "setup") {
  // UI B N5 (Q6, board 3): one tab, a page in the main column as All tasks is; other sheets stay sheets. No Close: the rail and
  // the drawer leave it. The Setup rows' steps come from docs/SETUP.md, read once
  state.view = "settings";
  state.settingsTab = tab;
  state.navOpen = false;
  state.menu = null;
  render();
  if (document.scrollingElement && !state.setupFocus) document.scrollingElement.scrollTop = 0;
  if (state.setupText != null) return;
  try {
    const resp = await api("/api/setup", { raw: true });
    if (!resp.ok) throw new Error(`docs/SETUP.md could not be read (HTTP ${resp.status})`);
    state.setupText = await resp.text();
    state.setupError = null;
  } catch (e) {
    state.setupError = e.message;
  }
  if (state.view === "settings") renderSetup();
}

function foldButton(key, label) {
  // UI B N4 (Q6): a section's label folds it; remembered across a reload
  const open = !state.sideFolds[key];
  return h("button", { class: "side-fold", type: "button", "aria-expanded": open ? "true" : "false", onclick: () => {
    state.sideFolds = { ...state.sideFolds, [key]: open };
    try { localStorage.setItem("sr-side-folds", JSON.stringify(state.sideFolds)); } catch (e) { /* it just isn't remembered */ }
    renderSidebar();
  } }, h("span", { class: "side-fold-mark", "aria-hidden": "true", text: open ? "▾" : "▸" }), h("span", { text: label }));
}

function renderSidebar() {
  const status = state.status || {};
  const chats = (status.chats || []).slice().sort((a, b) => String(b.newest).localeCompare(String(a.newest)));
  const list = [];
  list.push(h("div", { class: "brand" }, h("span", { class: "brand-mark" }, icon("logo")),
    h("span", { class: "brand-name", text: "Super Router" }),
    h("span", { class: "brand-version", text: status.version ? `v${status.version}` : "" })));
  // UI B N3: above 900 px New chat is the rail's; the drawer holds it at its top, and Settings at its foot
  list.push(h("button", { class: "side-item primary side-only-narrow", type: "button", title: "New chat", onclick: newChat },
    icon("plus"), h("span", { class: "name", text: "New chat" })));
  const needs = needsYouList(state.tasks);
  // UI-1 row 3 (D9): Needs you shows its 3 newest and an "n more" row that opens it in place; the brand, New chat and
  // Needs you stay pinned at the top, Waiting to History scroll in one region, the bottom group stays pinned
  const cut = needsYouCut(needs.you, state.needsOpen);
  const needRow = (item) => h("button", { class: "side-item needs", type: "button",
    title: `#${item.n}: ${item.what}`, onclick: () => goToTask(item.task_id) }, icon("alert"),
  h("span", { class: "name", text: item.what }), h("span", { class: "count", text: `#${item.n}` }));
  if (needs.you.length) {
    list.push(h("div", { class: "side-label", text: cut.label }));
    if (!state.needsOpen) {
      list.push(h("div", { class: "side-list" }, cut.shown.map(needRow),
        cut.more ? h("button", { class: "side-item more-row", type: "button", "aria-expanded": "false",
          onclick: () => { state.needsOpen = true; renderSidebar(); } }, h("span", { class: "name", text: `${cut.more} more` })) : null));
    }
  }
  const pinned = list.splice(0);
  if (needs.you.length && state.needsOpen) list.push(h("div", { class: "side-list" }, cut.shown.map(needRow)));  // once open, it scrolls
  if (needs.router.length) {
    list.push(h("div", { class: "side-label", text: "Waiting on the router" }));
    list.push(h("div", { class: "side-list" }, needs.router.map((item) => h("button", { class: "side-item waiting", type: "button",  // UI-1 row 9: muted
      title: `#${item.n}: ${item.what}`, onclick: () => goToTask(item.task_id) }, icon("clock"),
    h("span", { class: "name", text: item.what }), h("span", { class: "count", text: `#${item.n}` })))));
  }
  // brief 26 (decision 12): a + on the Projects label opens the New project sheet (a 44 px hit area round a small mark)
  list.push(h("div", { class: "side-label with-action", id: "side-section-projects" }, foldButton("projects", "Projects"),
    h("button", { class: "label-btn", id: "np-open", type: "button", title: "New project", "aria-label": "New project",
      onclick: () => openNewProject() }, icon("plus"))));
  const projectList = h("div", { class: "side-list" });
  for (const project of status.projects || []) {
    // the "new" tag: this page session only, in memory (decision 14)
    projectList.append(h("button", { class: "side-item", type: "button", title: project.name,
      "aria-current": project.name === state.project ? "page" : null, onclick: () => openProject(project.name) },
    icon("folder"), h("span", { class: "name", text: project.name }),
    h("span", { class: "count", text: project.open_task ? `#${project.open_task.n} open` : state.madeProjects.has(project.name) ? "new" : "" })));
  }
  if (!(status.projects || []).length) {  // the empty list is the way in
    projectList.append(h("button", { class: "side-item new-project", id: "np-empty", type: "button", onclick: () => openNewProject() },
      icon("plus"), h("span", { class: "name", text: "New project" })));
  }
  if (!state.sideFolds.projects) list.push(projectList);
  list.push(h("div", { class: "side-label with-action", id: "side-section-chats" }, foldButton("chats", "Chats")));
  const chatList = h("div", { class: "side-list" });
  if (state.chat && !chats.some((c) => c.name === state.chat)) {
    chatList.append(h("button", { class: "side-item", type: "button", "aria-current": state.project ? null : "page" },
      icon("chat"), h("span", { class: "name", text: state.chat }), h("span", { class: "count", text: "new" })));
  }
  for (const chat of chats) {
    chatList.append(h("button", { class: "side-item", type: "button", title: chat.name,
      "aria-current": chat.name === state.chat && !state.project && !state.quick ? "page" : null,
      onclick: () => openChat(chat.name) }, icon("chat"), h("span", { class: "name", text: chat.name }),
    h("span", { class: "count", text: chat.tasks })));
  }
  if (!chats.length && !state.chat) chatList.append(h("div", { class: "side-item faint", text: "No chats yet" }));
  if (!state.sideFolds.chats) list.push(chatList);
  const middle = list.splice(0);
  list.push(...pinned, h("div", { class: "side-scroll" }, middle));  // UI-1 row 3 (D9): one scroll region
  list.push(h("button", { class: "side-item side-only-narrow", type: "button", title: "Settings", onclick: () => openSettings() },
    icon("gear"), h("span", { class: "name", text: "Settings" })));
  const was = $("sidebar").querySelector(".side-scroll");  // UI-1 row 3: a redraw keeps the region where it was scrolled
  const top = was ? was.scrollTop : 0;
  setChildren($("sidebar"), list);
  const region = $("sidebar").querySelector(".side-scroll");
  if (region) region.scrollTop = top;
  $("sidebar").classList.toggle("open", state.navOpen);
  if (state.sideScrolled !== state.project) {  // UI-1 row 9 (D8): the open project scrolls into view, once per opening
    state.sideScrolled = state.project;
    const open = state.project && $("sidebar").querySelector('.side-list [aria-current="page"]');
    if (open) open.scrollIntoView({ block: "nearest" });
  }
  $("nav-backdrop").hidden = !state.navOpen;
}

function toggleNav(open = !state.navOpen) {
  state.navOpen = open;
  renderSidebar();
  renderStrip();
}

function streamTasks() {
  const all = viewTasksKnown(state.viewRead, state.tasks || []);  // Cleanup 2, row 1: the view's own read beside the whole log's
  if (state.view === "history") return state.historyTasks.slice().sort((a, b) => a.n - b.n);
  if (state.view === "logfiles" || state.view === "settings") return [];
  const mine = new Set(state.sessionTasks);
  const picked = all.filter((t) => {
    if (t.mode === "suggest") return false;  // brief 33.4 (decision 10): no card in the stream; History and sr log have it
    if (mine.has(t.task_id)) return true;
    if (state.project) return t.project === state.project;
    return state.chat ? t.chat === state.chat : !t.chat && !t.project;
  });
  const shown = new Set(picked.map((t) => t.task_id));  // brief 29: a split's pieces show wherever their split shows
  const pieces = all.filter((t) => t.parent && shown.has(t.parent) && !shown.has(t.task_id));
  return [...picked, ...pieces].sort((a, b) => a.n - b.n);
}

function mdInline(nodes) {
  return (nodes || []).map((n) => {
    if (n.type === "text") return document.createTextNode(n.text);
    if (n.type === "code") return h("code", { text: n.text });
    if (n.type === "strong") return h("strong", {}, mdInline(n.children));
    if (n.type === "em") return h("em", {}, mdInline(n.children));
    if (n.type === "link" && /^https:\/\//.test(n.href)) {
      return h("a", { href: n.href, target: "_blank", rel: "noopener noreferrer" }, mdInline(n.children));
    }
    return document.createTextNode(n.text || "");
  });
}

function mdBlocks(blocks) {
  return blocks.map((b) => {
    if (/^h[1-4]$/.test(b.type)) return h(b.type, {}, mdInline(b.children));
    if (b.type === "p") return h("p", {}, mdInline(b.children));
    if (b.type === "ul" || b.type === "ol") return h(b.type, { start: b.start }, b.items.map((item) => h("li", {}, mdInline(item))));
    if (b.type === "pre") return h("pre", {}, h("code", { text: b.text }));
    if (b.type === "blockquote") return h("blockquote", {}, mdInline(b.children));
    if (b.type === "hr") return h("hr");
    if (b.type === "table") {
      return h("table", {}, h("thead", {}, h("tr", {}, b.head.map((c) => h("th", {}, mdInline(c))))),
        h("tbody", {}, b.rows.map((row) => h("tr", {}, row.map((c) => h("td", {}, mdInline(c)))))));
    }
    return null;
  });
}

const mdCache = new Map();
function renderMarkdown(text, key = null) {
  // a poll draws every card again: a result's parsed blocks are kept per task and length, so it is parsed once
  if (key == null) return mdBlocks(markdown(text));
  let blocks = mdCache.get(key);
  if (!blocks) {
    blocks = markdown(text);
    mdCache.set(key, blocks);
    if (mdCache.size > 200) mdCache.delete(mdCache.keys().next().value);
  }
  return mdBlocks(blocks);
}

function detailsBlock(task, show) {
  // what the card no longer shows up front: Jev's label and confidence, memory, rounds, the raw notes, the two buttons
  const view = checkView(task, show);
  const notes = detailNotes(task, show);
  const actions = [];
  if ((view && view.given && task.tag) || task.from) actions.push(h("button", { class: "btn btn-quiet", type: "button", onclick: () => openMemory(task) }, "What the agents were given"));
  const given = callNotesLines(show).concat(callSpecLines(show));  // brief 30 (decision 10): the router notes each call was sent; 33.2: the spec
  const modelLines = callModelLines(show);
  const rounds = cardLine(task, show).files;  // UI-1 row 11 (D7): the round files, one row per stage, as the stage line had them  // brief 33.3 (decision 12): each call's model, asked → served, its time limit
  if (task.router_notes) actions.push(h("button", { class: "btn btn-quiet", type: "button", id: `notes-copy-${task.task_id}`,
    onclick: () => openRoundFile(task, task.router_notes.file) }, "Show the router notes it was sent"));
  if (task.spec) actions.push(h("button", { class: "btn btn-quiet", type: "button", id: `spec-copy-${task.task_id}`,
    onclick: () => openRoundFile(task, task.spec.file) }, "Show the SPEC.md it was sent"));  // brief 33.2 (decision 2.7)
  if (view && view.original) actions.push(h("button", { class: "btn btn-quiet", type: "button", onclick: () => openRoundFile(task, view.original) }, "Show original"));
  return h("div", { class: "details" },
    h("div", { class: "pills" }, receiptView(task, show, clockNow()).map((pill) => h("span", { class: "pill" }, pill.text,
      pill.value ? h("b", { text: pill.value }) : null))),
    view && view.detail ? h("div", { class: "details-line", text: `${view.title} · ${view.detail}` }) : null,
    notes.map((note) => h("div", { class: "details-line mono", text: note })),
    given.length ? h("div", { class: "details-given" }, h("div", { class: "details-line", text: "What the agents were given:" }),
      given.map((line) => h("div", { class: "details-line mono", text: line }))) : null,
    modelLines.length ? h("div", { class: "details-given" }, h("div", { class: "details-line", text: "Models:" }),
      modelLines.map((line) => h("div", { class: "details-line mono", text: line }))) : null,
    chipPlace(task, state.chipCard) === "details"  // brief 33 (decision 2): an older card's chips, still filling the box
      ? h("div", { class: "details-next" }, h("div", { class: "details-line", text: "Suggested next" }), nextRow(task, false)) : null,
    rounds.length ? h("div", { class: "details-given details-rounds" }, h("div", { class: "details-line", text: "Round files:" }),  // UI-1 row 11
      h("div", { class: "row-actions" }, rounds.map((r) => h("button", { class: "btn btn-quiet btn-small", type: "button",
        onclick: () => openRoundFile(task, r.file) }, r.label)))) : null,
    actions.length ? h("div", { class: "row-actions" }, actions) : null);
}

function viewKind() {
  if (state.view === "history" || state.view === "logfiles" || state.view === "settings") return state.view;
  return state.project ? "project" : state.chat ? "chat" : "quick";
}

function nextRow(task, labeled = true) {
  // decision 19: real buttons, reachable by keyboard, 44 px targets, wrapping at narrow widths, labeled "Next"
  return h("div", { class: "next-row", role: "group", "aria-label": labeled ? "Next" : "Suggested next" },
    labeled ? h("span", { class: "next-label", "aria-hidden": "true", text: "Next" }) : null,
    task.next.map((chip, i) => h("span", { class: "next-item" },
      h("button", { class: `next-chip${chip.kind === "build_from" ? " own" : ""}`, type: "button",
        dataset: { focusKey: `next-${task.task_id}-${i}` }, title: chip.words, onclick: () => useChip(chip, task) },
        h("span", { class: "next-words", text: chip.words })),
      chip.later ? h("button", { class: "next-later", type: "button", "aria-label": "Later: move to Ideas",
        title: "Later: move to Ideas", disabled: state.demo || state.restarted, dataset: { focusKey: `later-${task.task_id}-${i}` },
        onclick: () => laterChip(chip, task) }, "×") : null)));
}

async function laterChip(chip, task) {
  // decision 7: the line moves to the project's Ideas list (sr ideas <project> --add --source <task> -- <text>)
  let result;
  try {
    result = await runProjectAction({ action: "ideas_add", name: task.project, text: chip.words, source: task.task_id });
  } catch (e) {
    result = { code: null, message: e.message };
  }
  toast(result.code === 0 ? `Moved to ${task.project}'s Ideas` : result.message);
  if (result.code === 0) { await loadLog(); await loadStatus(); render(); }
}

function useChip(chip, task) {
  // decision 1: fill the composer for you to read, edit and send; never send, never run, never ask to confirm
  const current = { text: state.text, team: state.team, project: state.project, chat: state.chat, quick: state.quick,
    from: state.from || null, idea: state.idea || null, step: state.step || null, noFiles: !!state.noFiles };
  const { next, undo } = fillFromChip(chip, current, task.n);
  setBox(next);
  if (undo) undoToast("The chip replaced what you typed.", () => setBox({ ...undo, placeholder: null }));
}

function setBox(fill) {
  Object.assign(state, { text: fill.text, team: fill.team, project: fill.project, chat: fill.chat, quick: fill.quick,
    from: fill.from || null, idea: fill.idea || null, step: fill.step || null,  // brief 33.1 (decision 12): the Step pill
    models: fill.models || null,  // brief 33.3 (decision 4): a chip and Run again carry no model choice
    noFiles: !!fill.noFiles,  // brief 33.2 (decision 5): the Text only pill (Draft it)
    fillPlaceholder: fill.placeholder || null });
  const prompt = $("prompt");
  prompt.value = fill.text;
  refreshCommand();
  renderComposer();
  prompt.focus();
  prompt.setSelectionRange(prompt.value.length, prompt.value.length);
}

function undoToast(message, undo) {
  // decision 1: Undo for 10 seconds puts back the box, its team, tag and pills as they were
  const node = $("toast");
  setChildren(node, h("span", { text: message }), h("button", { class: "toast-undo", type: "button",
    onclick: () => { node.hidden = true; clearTimeout(state.toastTimer); undo(); } }, "Undo"));
  node.hidden = false;
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => { node.hidden = true; }, UNDO_MS);
}

function runAgainOff() {
  return state.demo || state.restarted;  // Run again as… is off in the demo and after a restart (as before), on the card or in ⋯
}

function runAgainItems(task) {
  // the teams Run again as… offers, each today's runAgain (UI-1 row 4: shared by the card's button and its ⋯ menu)
  const own = task.mode === "relay" ? task.preset : task.mode === "split" ? null : task.mode === "plan" ? "plan" : "route";  // a split has no chip: every team
  const fill = runAgainFill(task);  // brief 33.4 (decision 9b): a text-only card's Route item fills the box
  // the small UI cleanup, row 10 (note 22): any card with a project offers Plan; off a project it stays greyed with its reason
  const chips = chipViews(state.status, state.team, task.project ? { project: task.project } : {}).filter((c) => c.key !== own || fill);
  const skill = state.routeItSkills.get(`again-${task.task_id}`) || null;  // brief 29.1 (decision 7c): its own skill pick
  const routed = runAgainRequest(task, "route", againUi(), state.status, skill);
  const needsSkill = !fill && chips.some((c) => c.key === "route") && routed.pick.needed;
  return [needsSkill ? h("select", { class: "select", "aria-label": "Its skill for Route (Jev isn't set up)",
    dataset: { focusKey: `run-again-skill-${task.task_id}` }, onchange: (e) => {
      state.routeItSkills.set(`again-${task.task_id}`, e.target.value || null);
      renderStream({ follow: false });
    } }, h("option", { value: "", text: "Route: pick its skill…" }),
  routed.pick.options.map((o) => h("option", { value: o.key, selected: o.key === skill, text: o.label }))) : null,
  chips.map((chip) => {
    const off = chip.disabled || (chip.key === "route" && needsSkill && !routed.pick.chosen);
    return h("button", { class: "side-item", type: "button", role: "menuitem", disabled: off,
      title: chip.key === "route" && needsSkill && !routed.pick.chosen ? routed.pick.why : chip.reason || chip.title,
      dataset: { focusKey: `run-again-${task.task_id}-${chip.key}` },
      onclick: () => { state.menu = null; state.menuSub = null; if (fill) fillAgain(runAgainFill(task, chip.key)); else runAgain(task, chip.key); } },
    h("span", { class: "name", text: !fill ? `${chip.label}: a new task` : chip.key === "route" ? `${chip.label}: text only, in the box` : `${chip.label}: in the box` }));
  })];
}

function menuListClass(key, extra = "") {
  // the small UI cleanup, row 7 (note 1): a menu drawn again while already open keeps its place with no fade; the first opening still fades
  const settled = state.menuDrawn === key;
  state.menuDrawn = key;
  return ["menu-list", extra, settled ? "settled" : ""].filter(Boolean).join(" ");
}

function runAgainMenu(task) {
  const open = state.menu === task.task_id;
  return h("div", { class: "menu" },
    h("button", { class: "btn", type: "button", "aria-expanded": open ? "true" : "false", disabled: runAgainOff(),
      dataset: { focusKey: `run-again-${task.task_id}` },
      onclick: () => { state.menu = open ? null : task.task_id; renderStream({ follow: false }); } }, "Run again as…"),
    open ? h("div", { class: menuListClass(task.task_id), role: "menu", onkeydown: menuArrows }, runAgainItems(task)) : null);
}

function menuArrows(e) {
  // UI-1 row 4 (D13): ↑ and ↓ move through a menu's items
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
  const items = [...e.currentTarget.querySelectorAll('[role="menuitem"]:not(:disabled)')];
  if (!items.length) return;
  e.preventDefault();
  const at = items.indexOf(document.activeElement);
  items[(at + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].focus();
}

function cardMenu(task) {
  // UI-1 row 4 (D13): ⋯ beside Details: Run again as… (its teams, each today's runAgain), Pin to notes, Save to project,
  // Forget or Remember again (each today's notesAction). New: ⋯ itself only opens and closes the list.
  const items = cardMenuItems(task);
  if (!items.length) return null;
  const key = `more-${task.task_id}`;
  const open = state.menu === key;
  const teams = open && state.menuSub === key ? runAgainItems(task) : [];
  return h("div", { class: "menu card-menu" },
    h("button", { class: "details-btn more-btn", type: "button", "aria-label": "More actions", "aria-haspopup": "menu",
      "aria-expanded": open ? "true" : "false", dataset: { focusKey: key },
      onclick: () => {
        state.menu = open ? null : key;
        state.menuSub = null;
        renderStream({ follow: false });
        const first = !open && document.querySelector(`#card-${CSS.escape(task.task_id)} .card-menu [role="menuitem"]:not(:disabled)`);
        if (first) first.focus();
      } }, "⋯"),
    open ? h("div", { class: menuListClass(key), role: "menu", "aria-label": "More actions", onkeydown: menuArrows },
      items.map((item) => item.key === "again"
        ? [h("button", { class: "side-item", type: "button", role: "menuitem", "aria-expanded": teams.length ? "true" : "false",
          disabled: runAgainOff(), dataset: { focusKey: `${key}-again` },
          onclick: () => { state.menuSub = state.menuSub === key ? null : key; renderStream({ follow: false }); } },
        h("span", { class: "name", text: item.label })), teams.length ? h("div", { class: "menu-sub" }, teams) : null]
        : h("button", { class: "side-item", type: "button", role: "menuitem", id: `act-${task.task_id}-${item.key}`, disabled: busy(task),
          onclick: () => { state.menu = null; renderStream({ follow: false }); notesAction(task, item); } },
        h("span", { class: "name", text: item.label })))) : null);
}

function fillAgain(fill) {
  // brief 33.4 (decision 9b): as a chip does: the box filled, nothing sent; Undo puts back anything typed
  const current = { text: state.text, team: state.team, project: state.project, chat: state.chat, quick: state.quick,
    from: state.from || null, idea: state.idea || null, step: state.step || null, noFiles: !!state.noFiles };
  renderStream({ follow: false });
  setBox(fill);
  if ((current.text || "").trim()) undoToast("Run again replaced what you typed.", () => setBox({ ...current, placeholder: null }));
}

function holdsMain(task, from, key = null) {
  // UI A N3 (A1): does this part of the card hold its one main action? The buttons stay where they are; only this one is bright
  const main = cardMainAction(task, state.shows.get(task.task_id) || null);
  return !!main && main.from === from && (key == null || main.key === key);
}

function buttonClass(tone, main) {
  // UI A N3: a view's tone for a card's button: bright only as the main action; Land anyway's red outline
  return `btn${main ? " btn-primary" : tone === "quiet" ? " btn-quiet" : tone === "danger" ? " btn-danger" : ""}`;
}

function saveSpecMain(task) {
  // UI-1m (2.6): Save as SPEC.md through cardMainAction, the text-only card's main action, gone once the spec exists
  const main = cardMainAction(task, state.shows.get(task.task_id) || null);
  if (!main || main.key !== "save_spec") return null;
  return h("div", { class: "offer-row save-spec" }, h("button", { class: "btn btn-primary", type: "button", id: `save-spec-${task.task_id}`,
    disabled: busy(task) || state.starting.has(task.task_id), title: "One commit: the spec and this draft's entry",
    onclick: () => saveSpec(task, main) }, main.label));
}

async function saveSpec(task, view) {
  if (state.demo) { toast("Demo: nothing runs."); return; }
  state.starting.add(task.task_id);
  renderStream({ follow: false });
  let result;
  try {
    result = await runProjectAction(view.request);
  } catch (e) {
    result = { code: null, message: e.message };
  }
  state.starting.delete(task.task_id);
  if (result.code === 0) { await loadStatus(); await loadLog(); }
  toast(result.code === 0 ? `Saved #${task.n} as ${view.request.path}` : result.message);
  render();
}

function againUi() {
  return { chat: state.chat, quick: state.quick, newChat: newChatName() };
}

function fileRow(task) {
  const cards = fileCards(state.filesOf.get(task.task_id));
  if (!cards.length) return null;
  const current = state.panel && state.panel.taskId === task.task_id ? state.panel.file.path : null;
  return h("div", { class: "files-row" }, cards.map((card) => h("button", {
    class: "file-card", type: "button", title: card.name, "aria-current": card.path === current ? "true" : null,
    onclick: () => openFile(task, card.path) },
  h("span", { class: `file-icon ${card.kind}` }, icon(card.kind === "image" ? "file" : card.kind === "text" ? "code" : "file")),
  h("span", { class: "file-text" }, h("span", { class: "file-name", text: middleTruncate(card.name, 30) }), h("span", { class: "file-meta", text: card.meta })))));
}

function resultBlock(task, show) {
  if (!task.result) return null;
  if (!resultShown(task)) return cardKeepsRunAgain(task) ? h("div", { class: "row-actions" }, runAgainMenu(task)) : null;  // UI-1 row 4 (D13): the rest is in ⋯
  const view = resultView(task.result);  // brief 32.1 (decision 4): whole, up to PREVIEW_CHARS
  const body = h("div", { class: "result" }, renderMarkdown(view.text, `${task.task_id}:${task.result.length}`));
  const who = resultHeading(task);
  return h("div", { class: "answer" }, h("div", { class: "answer-meta", text: who }), body,
    view.beside ? h("button", { class: "btn btn-quiet load-earlier", type: "button", onclick: () => openText(task, who) },
      view.beside) : null,
    forgottenLine(task) ? h("div", { class: "quiet-line forgotten-line", text: forgottenLine(task) }) : null,
    fileRow(task), cardKeepsRunAgain(task) ? h("div", { class: "row-actions" }, runAgainMenu(task)) : null);  // UI-1 row 4 (D13)
}

function taskCard(task) {
  const summary = taskSummary(task);
  const show = state.shows.get(task.task_id) || null;
  const meta = [`#${task.n}`, summary.team, summary.pieceOf, stepCoversLine(task),  // brief 29: "piece 2 of split #214"; 33.2: the example
    task.chat ? `chat ${task.chat}` : task.project ? `project ${task.project}` : task.mode === "split" ? "untagged" : null,
    localTime(task.created_at)].filter(Boolean).join(" · ");
  const verdict = verdictLine(task, show);
  const line = cardLine(task, show, { time: task.task_id === state.newestCard || (isOpenTask(task) && !task.waiting_on), now: clockNow() });  // UI A row 19: any running card
  const detailed = state.detailsOpen.has(task.task_id);
  // Built through h(), which skips a missing part (Element.append(null) would write the word "null").
  const frame = cardFrame(task);  // UI A N2 (A3)
  const card = h("article", { class: `task${frame ? ` framed frame-${frame}` : ""}`, id: `card-${task.task_id}`, tabindex: "-1", dataset: { task: task.task_id } },
    h("div", { class: "bubble-row" }, h("div", { class: "bubble-col" },
      h("div", { class: "bubble", text: task.text }), h("div", { class: "bubble-meta", text: meta }))),
    builtFromLine(task),  // brief 33 (decision 12)
    h("div", { class: `verdict card-top ${line.tone}` },  // the small UI cleanup, row 3: the pills, then the outcome, the time, Details and ⋯
      line.pills.length ? h("div", { class: "stages" }, line.pills.map((p) => h("span", { class: `stage ${p.tone}`, text: p.text }))) : null,
      h("div", { class: "card-end" },
        line.text ? h("span", { class: "verdict-text", text: line.text }) : null,
        line.time ? h("span", { class: "card-time", text: line.time }) : null,
        h("button", { class: "details-btn", type: "button", "aria-expanded": detailed ? "true" : "false",
          onclick: () => { detailed ? state.detailsOpen.delete(task.task_id) : state.detailsOpen.add(task.task_id); renderStream({ follow: false }); } },
        detailed ? "Hide details" : "Details"), cardMenu(task))),  // UI-1 row 4 (D13): ⋯ beside Details
    uncheckedWhy(task) ? h("div", { class: "card-line unchecked-why", text: uncheckedWhy(task) }) : null,  // UI A row 18 (A6)
    task.card_line ? h("div", { class: "card-line", text: task.card_line }) : null,  // brief 24 (decision 15)
    filesBlock(task),  // brief 28 (decision 20): the change, its tests, Land, Discard or Undo
    checkItemsBlock(task),  // brief 29.1: a pass's notes, folded; a failed check's open musts
    detailed ? detailsBlock(task, show) : null,
    blockedBlock(task),  // brief 29.1 (decision 17)
    needsBlock(task, show),
    boardBlock(task, show),
    saveSpecMain(task),  // brief 33.4 (decision 8); UI-1m (2.6)
    offersRow(task),
    confirmRow(task),
    actionLine(task),
    voteBoard(task, show) ? null : resultBlock(task, show),
    chipPlace(task, state.chipCard) === "inline" ? nextRow(task) : null,  // brief 33 (decision 2)
    task.result && !voteBoard(task, show) ? null : fileRow(task),
    task.result && !voteBoard(task, show) ? null : cardKeepsRunAgain(task) ? h("div", { class: "row-actions" }, runAgainMenu(task)) : null);  // UI-1 row 4 (D13)
  observeCard(card, task);
  return card;
}

function whatNowLine(name) {
  const line = state.whatNow && state.whatNow.project === name ? state.whatNow.line : null;
  const parts = whatNowParts(line);
  // brief 34 (decision 10): the Auto switch at the right end of the line, from the project's `auto` (status); its confirm
  // under the line while it asks
  const switchView = autoSwitchView(projectOf(name), state.autoRun && state.autoRun.name === name ? state.autoRun : null);
  if (!parts) {
    if (!switchView) return null;
    return h("div", { class: "what-now", id: "what-now", role: "status" }, h("span", { class: "what-now-label", text: "What now?" }),
      autoSwitch(switchView, name));
  }
  const task = (state.tasks || []).find((t) => t.task_id === parts.taskId) || { n: line.n, task_id: parts.taskId };
  const chipButton = (chip) => chip.opens === "run_command"  // brief 33.1 (decision 17): Set the run command opens it
    ? h("button", { class: "next-chip", type: "button", title: "Open the run command's setting", disabled: state.restarted,
      onclick: () => { const found = projectOf(name); if (found) openRunSheet(found); } }, h("span", { class: "next-words", text: chip.words }))
    : h("button", { class: "next-chip", type: "button", title: chip.words, onclick: () => useChip(chip, task) },
      h("span", { class: "next-words", text: chip.words }));
  const row = h("div", { class: "what-now", id: "what-now", role: "status" },
    h("span", { class: "what-now-label", text: "What now?" }),
    h("span", { class: "what-now-words", text: parts.lead }),
    parts.secrets ? h("button", { class: "btn btn-quiet secrets-btn", type: "button", disabled: state.restarted,  // 33.1
      title: `Set ${parts.secrets} in ${name}'s .env; the step may be sent anyway`, onclick: () => openSecrets(name, parts.secrets) },
    secretsLabel(parts.secrets)) : null,
    parts.tests ? h("button", { class: "btn btn-quiet", type: "button", disabled: state.restarted || state.demo,
      title: `Set the test command to \`${parts.tests}\`; the step may be sent anyway`,
      onclick: () => setTestCommand(name, parts.tests) }, "Set") : null,
    parts.chip ? chipButton(parts.chip) : null,
    ...(parts.chips || []).map(chipButton),
    parts.open ? h("button", { class: "btn btn-quiet", type: "button", onclick: () => goToSource(parts.open) }, "Open") : null,
    parts.ideas ? h("button", { class: "btn btn-quiet", type: "button", onclick: () => openIdeas(name) }, "Ideas") : null,
    switchView ? autoSwitch(switchView, name) : null,  // brief 34 (decision 10): the only new always-visible control
    parts.said ? h("span", { class: "what-now-said", text: parts.said }) : null);
  return row;
}

function autoSwitch(view, name) {
  // brief 34 (decision 10): drawn as the Memory switch is; aria-disabled (never disabled) while the page's own run goes
  return h("div", { class: "auto-switch-wrap" },
    h("button", { class: `mem-switch auto-switch${view.on ? " on" : ""}${view.busy ? " busy" : ""}`, type: "button", role: "switch", id: "auto-switch",
      "aria-checked": view.on ? "true" : "false", "aria-label": "Auto", "aria-busy": view.busy ? "true" : null,
      "aria-disabled": view.disabled ? "true" : null, title: view.title, onclick: () => flipAuto(name) },
    h("span", { class: "mem-switch-label", text: `Auto · ${view.label}` }),
    h("span", { class: "mem-switch-track", "aria-hidden": "true" }, h("span", { class: "mem-switch-knob" }))));
}

function autoConfirmEl(name, ask) {
  // decision 10: the switch asks once, with the router's numbers (the dry run); Turn Auto on runs `sr auto <name> --on`.
  // UI-1 row 7 (D6a): drawn as the canvas's Run confirm, a sheet: What it runs (the router's words as given), Budget,
  // First stop here and the overrun line, from today's autoConfirmView only; no command line (D26). Focus starts on Keep
  // it off (row 17) and Esc closes it as Keep it off. No ids here, so brief 34's head ids stay as pinned.
  const view = ask.view;
  const off = !view || !!view.refused;
  const block = (label, text) => h("div", { class: "pc-fact" }, h("div", { class: "pc-label", text: label }), h("div", { class: "pc-code", text }));
  return h("div", { class: "sheet np auto-sheet", role: "dialog", "aria-modal": "true", "aria-label": `Turn Auto on for ${name}?` },
    h("div", { class: "sheet-head" }, h("span", { class: "sheet-title", text: `Turn Auto on for ${name}?` })),
    !view ? h("p", { class: "panel-note pc-line", text: "Asking the router what the run would cover…" })
      : view.refused ? h("div", { class: "missing", text: view.refused })
        : [block("What it runs", view.words || ""), view.budget == null ? null : block("Budget", `${count(view.budget)} calls`),
          block("First stop here", view.firstStop == null ? "none set" : `step ${view.firstStop}`),
          view.overrun ? h("p", { class: "panel-note pc-line auto-overrun", text: view.overrun }) : null,
          view.specLine ? h("p", { class: "panel-note pc-line spec-changed-line", text: view.specLine }) : null],  // brief 33.2 (decision 7.2)
    h("div", { class: "np-foot" },
      // UI-1 row 17 (D6b): Keep it off is where the focus starts, so Enter keeps Auto off
      h("button", { class: "btn btn-quiet auto-keep-off", type: "button", dataset: { focusKey: "auto-keep-off" },
        onclick: () => closeSheet() }, "Keep it off"),
      h("button", { class: `btn btn-primary${off ? " is-off" : ""}`, type: "button", "aria-disabled": off ? "true" : "false",
        onclick: () => { if (!off) { confirmAuto(); closeSheet(); } } }, "Turn Auto on")));
}

function paintAutoSheet() {
  // UI-1 row 7 (D6a): the Auto confirm's sheet, drawn again as the dry run answers
  const ask = state.autoAsk;
  if (!ask) return;
  if (state.navOpen) toggleNav(false);
  state.sheetKind = "auto";
  setChildren($("sheet"), autoConfirmEl(ask.name, ask));
  $("sheet").hidden = false;
}

async function flipAuto(name) {
  const view = autoSwitchView(projectOf(name), state.autoRun && state.autoRun.name === name ? state.autoRun : null);
  if (!view || view.disabled) return;
  if (view.to === "off") {  // decision 10: off runs at once, with no confirm; it is the only Stop
    if (state.demo) { toast("Demo: nothing runs."); return; }
    state.autoRun = { name, to: "off", started: Date.now() };
    renderStream({ follow: false });
    const found = await runProjectAction({ action: "auto_off", name });
    if (found.code !== 0) toast(found.message);
    await loadStatus();
    state.autoRun = null;
    renderStream({ follow: false });
    return;
  }
  const ask = { name, view: null };
  state.autoAsk = ask;
  paintAutoSheet();
  try {
    const doc = await api(`/api/auto-check?name=${encodeURIComponent(name)}`);
    if (state.autoAsk !== ask) return;
    ask.view = autoConfirmView(doc, name);
  } catch (e) {
    if (state.autoAsk !== ask) return;
    ask.view = autoConfirmView({ exit: 2, message: e.message }, name);
  }
  paintAutoSheet();
  const button = document.querySelector("#sheet .auto-keep-off");  // UI-1 row 17 (D6b): never Turn Auto on
  if (button) button.focus({ preventScroll: true });
}

const AUTO_START_WAIT_MS = 6000;  // the run row is written at once; a refusal ends at once; a run that goes on is left running

async function autoWaitRun(runId) {
  const until = Date.now() + AUTO_START_WAIT_MS;
  while (Date.now() < until) {
    await new Promise((resolve) => setTimeout(resolve, NP_POLL_MS));
    try {
      const run = ((await api("/api/runs")).runs || []).find((r) => r.id === runId);
      if (!run || !run.running) return run || null;
    } catch (e) {
      // the next look tries again
    }
  }
  return null;
}

async function confirmAuto() {
  const ask = state.autoAsk;
  if (!ask || !ask.view || ask.view.refused) return;
  state.autoAsk = null;
  if (state.demo) { toast("Demo: nothing runs."); renderStream({ follow: false }); return; }
  state.autoRun = { name: ask.name, to: "on", started: Date.now() };
  renderStream({ follow: false });
  try {
    const started = await api("/api/run", { method: "POST", body: ask.view.request });
    const run = await autoWaitRun(started.run_id);
    const env = (run && run.envelope) || {};
    const code = run ? (run.exit == null ? env.exit : run.exit) : null;
    if (run && !run.running && code !== 0 && code != null) toast(env.message || run.stderr || "Auto didn't start.");
  } catch (e) {
    toast(e.message);
  }
  await loadStatus();
  state.autoRun = null;
  renderStream({ follow: false });
}

async function flipStopHere(name, row) {
  // decision 13: a toggle runs `sr plan --stop-here <plan>:<k> on|off`; the log keeps the mark, nothing is committed
  if (row.busy) return;
  if (state.demo) { toast("Demo: nothing runs."); return; }
  state.markRuns.add(row.step);
  renderPanel();
  const found = await runProjectAction(row.request);
  if (found.code !== 0) toast(found.message);
  state.markRuns.delete(row.step);
  await loadStatus();
  renderPanel();
  renderStream({ follow: false });
}

async function loadWhatNow() {
  // decision 13: recomputed by the router on every poll, from `sr log --json --project <name>`
  const name = state.project;
  if (!name) { state.whatNow = null; return; }
  try {
    const doc = await api(historyPath({ project: name }));
    if (state.project === name) state.whatNow = { project: name, line: doc.what_now || null };
    // Cleanup 2, row 1: this read is the project's first page too, so a project's view costs no extra process per poll
    if (state.viewRead && state.viewRead.key === `project:${name}`) state.viewRead = takeViewPage(state.viewRead, doc, { quiet: true });
  } catch (e) {
    if (state.whatNow && state.whatNow.project !== name) state.whatNow = null;
    if (e.status !== 403 && state.viewRead && state.viewRead.key === `project:${name}` && !state.viewRead.pages) {
      state.viewRead = { ...state.viewRead, error: e.message };
    }
  }
}

function builtFromLine(task) {
  const found = builtFrom(task);
  if (!found) return null;
  return h("div", { class: "built-from" }, h("button", { class: "linklike", type: "button",
    onclick: () => goToSource(found.id, task.from.n) }, found.text));
}

function goToSource(taskId, n = null) {
  return jumpToTask(taskId, n);  // Cleanup 2, row 2: the card is found wherever it is, its pages read if they must be
}

// ---------- project files on the card and in the side panel (brief 28, decision 20a) ----------

function filesBlock(task) {
  const view = fileView(task);
  if (!view) return null;
  const bad = view.tests && /failed|timed out/.test(view.tests);
  return h("div", { class: `files-block tone-${view.tone}`, dataset: { files: view.kind } },
    h("div", { class: "files-head" }, icon("file"), h("span", { class: "files-line", text: view.line }),
      view.tests ? h("span", { class: `tests-line${bad ? " bad" : ""}`, text: view.tests }) : null),
    view.files.length ? h("div", { class: "files-list" }, view.files.map((f) => h("button", {
      class: "file-chip", type: "button", title: view.diff ? `${f.path}: its diff` : f.path, disabled: !view.diff,
      "aria-current": state.panel && state.panel.kind === "diff" && state.panel.taskId === task.task_id && state.panel.path === f.path ? "true" : null,
      onclick: () => openDiff(task, f.path) },
    h("span", { class: "file-path", text: middleTruncate(f.path, 56) }), h("span", { class: `file-words ${f.status}`, text: f.words }))),
    view.more ? h("button", { class: "file-chip more", type: "button", disabled: !view.diff,
      title: view.diff ? "Every file is in the diff panel" : "", onclick: () => openDiff(task, view.all[FILES_SHOWN].path) },
    h("span", { class: "file-path", text: `and ${view.more.toLocaleString("en-US")} more` }))
      : null) : null,
    view.note ? h("div", { class: "files-note", text: view.note }) : null,
    specRestoredLine(task) ? h("div", { class: "files-note", text: specRestoredLine(task) }) : null,  // brief 33.2 (decision 3)
    view.buttons.length ? h("div", { class: "offer-row" }, view.buttons.map((b) => h("button", {
      class: buttonClass(b.tone, holdsMain(task, "files", b.key)), type: "button",
      id: `act-${task.task_id}-${b.key}`, disabled: busy(task), onclick: () => act(task, b.request) }, b.label))) : null);
}

function openDiff(task, path) {
  if (state.panel && state.panel.blob) URL.revokeObjectURL(state.panel.blob);
  for (const url of (state.panel && state.panel.blobs) || []) URL.revokeObjectURL(url);
  state.panel = { kind: "diff", taskId: task.task_id, path, text: null, error: null };
  renderPanel();
  loadDiff();
  renderStream({ follow: false });
}

async function loadDiff() {
  const panel = state.panel;
  if (!panel || panel.kind !== "diff") return;
  const task = taskById(panel.taskId);
  const where = task && task.project_files && task.project_files.diff;
  if (!where) { panel.error = "This change's diff isn't kept."; renderPanel(); return; }
  try {
    const resp = await fetchFile(where);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const text = await resp.text();
    if (state.panel !== panel) return;
    panel.text = text;
  } catch (e) {
    if (state.panel !== panel) return;
    panel.error = `The diff could not be read (${e.message}).`;
  }
  renderPanel();
}

function diffNav(view, panel) {
  const picker = view ? diffPicker(view.all) : null;
  const go = (path) => { panel.path = path; renderPanel(); renderStream({ follow: false }); };
  if (picker === "select") {  // break-ui: 500 tabs pushed the diff 5,800 px down
    return h("label", { class: "diff-pick" }, h("span", { class: "muted", text: `File (${view.all.length.toLocaleString("en-US")})` }),
      h("select", { class: "np-input", onchange: (e) => go(e.target.value) },
        view.all.map((f) => h("option", { value: f.path, selected: f.path === panel.path ? true : null, text: `${f.path} · ${f.words}` }))));
  }
  if (picker !== "tabs") return null;
  return h("div", { class: "tabs", role: "tablist", "aria-label": "Changed files" }, view.all.map((f) => h("button", {
    class: "tab", type: "button", role: "tab", "aria-selected": f.path === panel.path ? "true" : "false", title: f.path,
    onclick: () => go(f.path) }, middleTruncate(f.path, 28))));
}

function renderDiffPanel(node, panel) {
  const task = taskById(panel.taskId) || { n: "?", task_id: panel.taskId };
  const view = fileView(task);
  const sections = diffSections(panel.text || "");
  const shown = sections.find((s) => s.path === panel.path) || null;
  const head = h("div", { class: "panel-head" },
    h("div", { class: "panel-row" }, h("span", { class: "file-icon text" }, icon("code")),
      h("div", { class: "panel-title" }, h("div", { class: "panel-name", text: panel.path }),
        h("div", { class: "panel-sub", text: [`#${task.n}`, view ? view.line : null].filter(Boolean).join(" · ") })),
      h("div", { class: "panel-tools" }, h("button", { class: "icon-btn", type: "button", "aria-label": "Close the panel", onclick: closePanel }, icon("x")))),
    diffNav(view, panel));
  let body;
  if (panel.error) body = [h("p", { class: "panel-note", text: panel.error })];
  else if (panel.text == null) body = [h("p", { class: "panel-note", text: "Loading…" })];
  else if (!shown) body = [h("p", { class: "panel-note", text: "No diff for this file (a binary file, or one the diff leaves out)." })];
  else body = [h("pre", { class: "diff-view", tabindex: "0", "aria-label": `The diff of ${panel.path}` },
    shown.text.split("\n").map((line) => h("span", { class: `diff-line ${diffLineTone(line)}`, text: line || " " })))];
  setChildren(node, head, h("div", { class: "panel-body" }, body));
}

// ---------- a project's bar: file mode, its tests, Turn on undo, files in (brief 28, decision 20b) ----------

function projectOf(name) {
  return ((state.status && state.status.projects) || []).find((p) => p.name === name) || null;
}

const PROJECT_MENU = "project-menu";  // UI-1 row 14 (D3): state.menu while Project ▾ is open

function closeProjectMenu() {
  // the small UI cleanup, row 9 (note 16): an item closes the menu and draws that, so it isn't left behind its sheet, where the first
  // press of Project would close the stale menu rather than open it
  state.menu = null;
  renderStream({ follow: false });
}

function projectBar(name) {
  // UI-1 row 14 (D3): the head's line 2. Test, Run/Stop, Plan #n and anything that needs you stay on the line; the rest
  // sits in Project ▾ (new: it only opens and closes). Each control keeps today's id and handler, built in today's order.
  const project = projectOf(name);
  if (!project) return null;
  const files = projectFilesLine(project);
  const tests = projectTestsLine(project);
  const input = h("input", { type: "file", multiple: true, hidden: true, id: "project-file-input",
    onchange: (e) => { dropOnProject(name, e.target.files); e.target.value = ""; } });
  const bar = h("div", { class: "project-bar", id: "project-bar" });
  const plan = planBarWords(project) ? h("button", { class: "btn btn-quiet plan-bar", type: "button", id: "project-plan",  // brief 33.1
    title: "docs/PLAN.md, read only: the router writes it and ticks each step there", onclick: () => openPlanFile(name) },
  planBarWords(project)) : null;
  const turnOn = files.turnOn ? h("button", { class: "btn", type: "button", id: "turn-on-undo", disabled: state.restarted,
    onclick: () => openTurnOnUndo(project) }, "Turn on undo") : null;
  const testsSet = h("button", { class: "side-item", type: "button", role: "menuitem", id: "tests-set", disabled: state.restarted,
    title: tests.text, onclick: () => { closeProjectMenu(); openTestsSheet(project); } },
  h("span", { class: "name", text: tests.text }), h("span", { class: "count", text: tests.button }));
  const run = projectRunGroup(project);  // brief 31 (decisions 3 to 7)
  const secrets = h("button", { class: "side-item", type: "button", role: "menuitem", id: "project-secrets", disabled: state.restarted,  // brief 31 (decision 9)
    title: "The names in the project's .env; set or remove a value without it ever being shown",
    onclick: () => { closeProjectMenu(); openSecrets(name); } }, h("span", { class: "name", text: project.secrets ? `Secrets · ${project.secrets}` : "Secrets" }));
  const ideas = h("button", { class: "side-item", type: "button", role: "menuitem", id: "project-ideas", disabled: state.restarted,  // brief 33 (decision 19)
    title: "One-line things to do later on this project: Send fills the box, Dismiss takes one off",
    onclick: () => { closeProjectMenu(); openIdeas(name); } }, h("span", { class: "name", text: project.ideas ? `Ideas · ${project.ideas}` : "Ideas" }));
  const notes = h("button", { class: "side-item", type: "button", role: "menuitem", id: "project-notes", disabled: state.restarted,  // brief 30 (decision 17)
    title: "The part of HANDOFF.md above the router's block: it rides on every call of this project",
    onclick: () => { closeProjectMenu(); openProjectNotes(name); } }, h("span", { class: "name", text: "Notes" }));
  const handoff = h("button", { class: "side-item", type: "button", role: "menuitem", onclick: () => { closeProjectMenu(); openHandoff(name); } },
    h("span", { class: "name", text: "HANDOFF.md" }));
  const addFiles = project.git ? h("button", { class: "side-item drop-btn", type: "button", role: "menuitem", disabled: state.restarted || state.demo,
    title: state.demo ? "Demo: nothing runs." : "Add files to the project's top level as one commit (or drop them here)",
    onclick: () => { state.menu = null; renderStream({ follow: false }); const fresh = $("project-file-input"); if (fresh) fresh.click(); } }, h("span", { class: "name", text: "Add files…" })) : null;
  const finder = state.reveal && !state.demo ? h("button", { class: "side-item", type: "button", role: "menuitem",  // UI B N9 (D18): no id, as HANDOFF.md has none
    onclick: () => { closeProjectMenu(); reveal(project.path); } }, h("span", { class: "name", text: "Show in Finder" })) : null;
  const add = [addFiles, finder];
  const open = state.menu === PROJECT_MENU;
  const menu = h("div", { class: "menu project-menu" },
    h("button", { class: "btn btn-quiet", type: "button", "aria-haspopup": "menu", "aria-expanded": open ? "true" : "false",
      dataset: { focusKey: PROJECT_MENU }, onclick: () => { state.menu = open ? null : PROJECT_MENU; renderStream({ follow: false }); } },
    "Project", h("span", { class: "caret", "aria-hidden": "true" }, icon("chevron"))),
    open ? h("div", { class: menuListClass(PROJECT_MENU, "down"), role: "menu", "aria-label": "Project" }, secrets, ideas, notes, handoff, testsSet, run.set, add) : null);
  setChildren(bar, projectTestButton(project), run.line, plan,  // brief 31 (decisions 1 and 2); 33.1
    files.tone === "ok" ? null : h("span", { class: `pill tone-${files.tone}`, title: files.text, text: files.text }),  // D3: "on" is hidden
    turnOn, menu, input);
  return dropZone(bar, project, name);
}

function dropZone(el, project, name) {
  // files dropped on a project's bar go to the files sheet (brief 28); brief 32.1: on its folded button too
  el.addEventListener("dragover", (e) => { if (project.git && !state.demo) { e.preventDefault(); el.classList.add("dragging"); } });
  el.addEventListener("dragleave", () => el.classList.remove("dragging"));
  el.addEventListener("drop", (e) => {
    el.classList.remove("dragging");
    if (!project.git || state.demo) return;
    e.preventDefault();
    dropOnProject(name, e.dataTransfer.files);
  });
  return el;
}

function fitHead() {
  // brief 32.1 (decision 3): the head is drawn whole, then measured; one taller than about a third of the window folds
  // its project's bar into Project tools, before the browser paints, so nothing flickers
  const head = document.querySelector("#stream > .stream-head");
  const bar = head && head.querySelector("#project-bar");
  const project = state.project ? projectOf(state.project) : null;
  if (!bar || !project) return;
  // UI B N6 (Q11): at phone width it always folds, with What now? still showing
  const view = projectToolsView({ folds: foldsTools(head.offsetHeight, window.innerHeight) || isNarrow(), open: state.toolsOpen });
  if (!view.button) return;
  const button = h("button", { class: "btn btn-quiet project-tools", type: "button", id: "project-tools",
    "aria-expanded": view.button.expanded ? "true" : "false", "aria-controls": "project-bar",
    title: "Files, Tests, Run, Secrets, Notes and Add files…",
    onclick: () => { state.toolsOpen = !state.toolsOpen; renderStream({ follow: false }); } }, icon("file"), view.button.label);
  if (view.drop === "button") dropZone(button, project, state.project);
  bar.before(button);
  bar.hidden = !view.bar;
}

let heights = null;
function watchHeights() {
  // brief 32.1 (decisions 1 and 2): the strip's height places the stuck head; the head's places a card jumped to
  const head = document.querySelector("#stream > .stream-head");
  if (typeof ResizeObserver !== "undefined") {
    if (!heights) { heights = new ResizeObserver(setHeights); heights.observe($("strip")); heights.observe($("composer-area")); }
    if (heights.head !== head) {
      if (heights.head) heights.unobserve(heights.head);
      if (head) heights.observe(head);
      heights.head = head;
    }
  }
  setHeights();
}

function setHeights() {
  const strip = $("strip").offsetHeight;
  const head = document.querySelector("#stream > .stream-head");
  const root = document.documentElement.style;
  root.setProperty("--strip-h", `${strip}px`);
  root.setProperty("--composer-h", `${$("composer-area").offsetHeight}px`);  // UI A N10: the ⋯ panel sits just above it
  root.setProperty("--card-margin", `${cardMargin(strip, head ? head.offsetHeight : 0)}px`);
}

async function runProjectAction(request) {
  // one project action: the server builds its command and runs it; the run's end is read back as its envelope
  const started = await api("/api/run", { method: "POST", body: request });
  const run = await npWaitRun(started.run_id);
  const env = (run && run.envelope) || {};
  const code = run ? (run.exit == null ? env.exit : run.exit) : null;
  return { run, env, code, message: env.message || (run && (run.message || run.stderr)) || "The command ended without an answer." };
}

// ---------- a project's Ideas list (brief 33, decisions 14 to 16 and 19) ----------

async function loadIdeas() {
  const sheet = state.ideasSheet;
  if (!sheet) return;
  try {
    const doc = await api(`/api/ideas?name=${encodeURIComponent(sheet.name)}`);
    if (state.ideasSheet !== sheet) return;
    sheet.doc = { ideas: doc.ideas || [], dismissed: doc.dismissed || 0, used: doc.used || [], suggest: doc.suggest || null };  // 33.2 fix 4: used; 33.4: the suggest
  } catch (e) {
    if (state.ideasSheet === sheet) sheet.failure = { title: "Not read", message: e.message, exit: null, code: null };
  }
  paintIdeas();
}

function openIdeas(name) {
  if (state.navOpen) toggleNav(false);
  state.ideasSheet = { name, doc: null, text: "", running: false, failure: null, asking: null };
  state.sheetKind = "ideas";
  const field = h("input", { class: "np-input", id: "ideas-text", autocomplete: "off", maxlength: "400",
    placeholder: "One line: something to do later", "aria-label": "A new idea",
    oninput: (e) => { state.ideasSheet.text = e.target.value; state.ideasSheet.failure = null; paintIdeas(); },
    onkeydown: (e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); addIdea(); } } });
  const sheet = h("div", { class: "sheet np ideas-sheet", id: "ideas-sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "ideas-title" },
    h("div", { class: "sheet-head" }, h("span", { class: "sheet-title", id: "ideas-title" }),
      h("button", { class: "icon-btn", type: "button", "aria-label": "Close", onclick: closeSheet }, icon("x"))),
    h("p", { class: "panel-note", text: "The router keeps this list in its log, never in the project. An idea reaches an agent only when you send it. Add keeps it on this list; nothing runs." }),
    // break-ui: Add sits above the list and Close stays in reach, so 50 ideas never push them out of sight
    h("div", { class: "np-field" }, h("label", { class: "np-label", for: "ideas-text", text: "Add" }),
      h("div", { class: "ideas-add-row" }, field,
        h("button", { class: "btn btn-primary", type: "button", id: "ideas-add", onclick: () => addIdea() }, "Add"),
        h("button", { class: "btn", type: "button", id: "ideas-suggest", hidden: true, onclick: () => suggestIdeas(name) }, "Suggest ideas")),
      h("div", { class: "np-hint", id: "ideas-suggest-line", hidden: true, role: "status" })),
    h("div", { class: "np-failure", id: "ideas-failure", role: "alert", hidden: true }),
    h("div", { class: "ideas-list", id: "ideas-list" }),
    h("div", { class: "np-foot ideas-foot" }, h("span", { class: "np-foot-note", id: "ideas-foot" }),
      h("button", { class: "btn", type: "button", onclick: closeSheet }, "Close")));
  setChildren($("sheet"), sheet);
  $("sheet").hidden = false;
  paintIdeas();
  loadIdeas();
  field.focus();
}

function paintIdeas() {
  const sheet = state.ideasSheet;
  if (state.sheetKind !== "ideas" || !sheet || !$("ideas-sheet")) return;
  const suggesting = suggestViewNow(sheet);
  const view = ideasSheetView(sheet.doc, { name: sheet.name, text: sheet.text, running: sheet.running, failure: sheet.failure,
    demo: state.demo, asking: sheet.asking, suggesting: !suggesting.hidden && suggesting.running });
  $("ideas-title").textContent = view.title;
  const button = $("ideas-suggest");  // brief 33.4 (decision 13)
  button.hidden = !!suggesting.hidden;
  button.disabled = !!suggesting.off;
  button.textContent = suggesting.label || "Suggest ideas";
  button.title = suggesting.why || "One Claude call adds up to 3 ideas from what the project holds; never checked: you judge each";
  const said = $("ideas-suggest-line");
  said.hidden = suggesting.hidden || !suggesting.line;
  said.textContent = suggesting.line || "";
  const rows = view.loading ? [h("p", { class: "panel-note", text: "Reading the list…" })]
    : view.empty ? [h("p", { class: "panel-note", text: "No ideas yet. Later on a project card's chip moves one here, or add one below." })]
    : view.rows.map((row) => h("div", { class: "idea-row" },
      h("div", { class: "idea-text", text: row.text }),
      h("div", { class: "idea-meta" },
        row.source.taskId ? h("button", { class: "linklike", type: "button", onclick: () => { closeSheet(); goToSource(row.source.taskId); } }, row.source.words)
          : h("span", { text: row.source.words }),
        h("span", { text: ` · ${row.date}` }), row.sent ? h("span", { class: "idea-sent", text: ` · ${row.sent}` }) : null),
      row.asking
        ? h("div", { class: "idea-ask" }, h("span", { class: "idea-ask-text", text: "Dismiss it? The page can't undo this." }),
          h("button", { class: "btn", type: "button", onclick: () => { sheet.asking = null; paintIdeas(); } }, "Cancel"),
          h("button", { class: "btn btn-primary", type: "button", disabled: sheet.running || state.demo, onclick: () => dismissIdea(row.id) }, "Dismiss"))
        : h("div", { class: "idea-actions" },
          h("button", { class: "btn", type: "button", disabled: !row.canSend, title: row.canSend ? "Fill the box with it: Route, this project, the Idea pill" : row.sent,
            onclick: () => sendIdea(row, sheet.name) }, "Send"),
          h("button", { class: "btn", type: "button", disabled: !row.canAddToPlan,  // brief 33.2 (decision 12)
            title: row.canAddToPlan ? "Fill the box with it: Plan, this project, the Idea pill (a revision while the plan has open steps)" : row.sent,
            onclick: () => addIdeaToPlan(row, sheet.name) }, "Add to plan"),
          h("button", { class: "btn btn-quiet", type: "button", disabled: sheet.running || state.demo,
            onclick: () => { sheet.asking = row.id; paintIdeas(); } }, "Dismiss"))));
  if (view.used) {  // brief 33.2 fix 4: folded by default, inside the sheet
    rows.push(h("details", { class: "ideas-used" }, h("summary", { text: view.used.title }),
      view.used.rows.map((row) => h("div", { class: "idea-row" },
        h("div", { class: "idea-text", text: row.text }),
        h("div", { class: "idea-meta" }, row.taskId
          ? h("button", { class: "linklike", type: "button", onclick: () => { closeSheet(); goToSource(row.taskId); } }, row.by)
          : h("span", { text: row.by }))))));
  }
  setChildren($("ideas-list"), ...rows);
  const add = $("ideas-add");
  add.setAttribute("aria-disabled", view.canAdd ? "false" : "true");
  add.classList.toggle("is-off", !view.canAdd);
  add.textContent = sheet.running ? "Adding…" : "Add";
  $("ideas-foot").textContent = view.dismissed ? `${view.dismissed} dismissed (the log keeps them)` : "";
  paintFailure($("ideas-failure"), view.failure);
}

function suggestViewNow(sheet) {
  const claude = ((state.status || {}).agents || []).find((a) => a.name === "claude");
  return suggestView(sheet.doc, { demo: state.demo, claude: !!(claude && claude.available), starting: state.suggesting.has(sheet.name) });
}

async function suggestIdeas(name) {
  // decision 13: closing the sheet doesn't stop it; a toast when it ends; the sheet re-reads the list if it's still open
  if (state.suggesting.has(name) || state.demo) return;
  state.suggesting.add(name);
  paintIdeas();
  let env = null;
  try {
    const started = await api("/api/run", { method: "POST", body: { action: "ideas_suggest", name } });
    const run = await npWaitRun(started.run_id, SUGGEST_RUN_LIMIT_MS);
    env = run ? { ...(run.envelope || {}), exit: run.exit } : null;
  } catch (e) {
    env = { message: e.message };
  }
  state.suggesting.delete(name);
  toast(suggestToast(env));
  await loadStatus();
  if (state.ideasSheet && state.ideasSheet.name === name) await loadIdeas();
}

function sendIdea(row, name) {
  const current = { text: state.text, team: state.team, project: state.project, chat: state.chat, quick: state.quick,
    from: state.from || null, idea: state.idea || null };
  const { next, undo } = fillFromIdea(row, name, current);
  closeSheet();
  if (state.project !== name) openProject(name);
  setBox(next);
  if (undo) undoToast("The idea replaced what you typed.", () => setBox({ ...undo, placeholder: null }));
}

function addIdeaToPlan(row, name) {
  // brief 33.2 (decision 12): as Send does, with team Plan
  const current = { text: state.text, team: state.team, project: state.project, chat: state.chat, quick: state.quick,
    from: state.from || null, idea: state.idea || null };
  const { next, undo } = fillFromIdeaToPlan(row, name, current);
  closeSheet();
  if (state.project !== name) openProject(name);
  setBox(next);
  if (undo) undoToast("The idea replaced what you typed.", () => setBox({ ...undo, placeholder: null }));
}

async function ideaAction(request) {
  const sheet = state.ideasSheet;
  if (!sheet || sheet.running) return;
  sheet.running = true;
  sheet.failure = null;
  paintIdeas();
  let result;
  try {
    result = await runProjectAction(request);
  } catch (e) {
    result = { code: null, env: {}, message: e.message };
  }
  if (state.ideasSheet !== sheet) { if (result.code !== 0) toast(result.message); return; }
  sheet.running = false;
  sheet.asking = null;
  if (result.code === 0) {
    if (request.action === "ideas_add") { sheet.text = ""; const field = $("ideas-text"); if (field) field.value = ""; }
    toast(result.message);
    await loadIdeas();
    await loadStatus();
    renderStream({ follow: false });
    return;
  }
  sheet.failure = failureOf(result);  // decision 19: a refusal stays in the sheet, in the router's words
  paintIdeas();
}

function addIdea() {
  const sheet = state.ideasSheet;
  if (!sheet || !ideasSheetView(sheet.doc, { name: sheet.name, text: sheet.text, demo: state.demo }).canAdd) return;
  ideaAction({ action: "ideas_add", name: sheet.name, text: sheet.text.trim() });
}

function dismissIdea(id) {
  const sheet = state.ideasSheet;
  if (!sheet) return;
  ideaAction({ action: "ideas_dismiss", name: sheet.name, id });
}

// ---------- a project's Test and its output in the side panel (brief 31, decisions 1, 2 and 7) ----------

const OUTPUT_POLL_MS = 2000;  // decision 7: every 2 seconds while the panel is open
const TEST_RUN_LIMIT_MS = 330 * 1000;  // a Test has 300 s in the sandbox, and the copy to make first

function projectTestButton(project) {
  const view = projectTestState(project, state.status && state.status.test_sandbox);
  const busy = state.testing.has(project.name);
  const off = state.demo ? "Demo: nothing runs." : busy ? "A Test is running" : view.off;
  return h("span", { class: "project-test" },
    h("button", { class: "btn btn-quiet", type: "button", id: "project-test", disabled: state.restarted || !!off,
      title: off || "Run the tests now on a throwaway copy of the committed files, in the sandbox (no network, no keys)",
      onclick: () => startTest(project.name) }, "Test"),
    view.line ? h("button", { class: `link project-test-line tone-${view.tone}`, type: "button", title: "Show the last Test's output",
      onclick: () => openProjectOutput(project.name, "test") }, view.line) : null,
    off && !state.demo && !busy ? h("span", { class: "project-off", text: off }) : null);
}

function openProjectOutput(name, what) {
  if (state.panel && state.panel.blob) URL.revokeObjectURL(state.panel.blob);
  for (const url of (state.panel && state.panel.blobs) || []) URL.revokeObjectURL(url);
  state.panel = { kind: "project", name, what, doc: null, error: null };
  renderPanel();
  pollProjectOutput();
}

async function pollProjectOutput() {
  clearTimeout(state.outputTimer);
  const panel = state.panel;
  if (!panel || panel.kind !== "project") return;
  try {
    const doc = await api(`/api/project-output?name=${encodeURIComponent(panel.name)}&kind=${panel.what}`);
    if (state.panel !== panel) return;
    panel.doc = doc;
    panel.error = null;
  } catch (e) {
    if (state.panel === panel) panel.error = e.message;
  }
  if (state.panel !== panel) return;
  renderPanel();
  state.outputTimer = setTimeout(pollProjectOutput, OUTPUT_POLL_MS);
}

export function followsEnd(scrollTop, clientHeight, scrollHeight) {
  // break-ui 2: a reader who scrolled up to read is left there; one at the end follows the newest line
  return scrollTop + clientHeight >= scrollHeight - 8;
}

function renderProjectPanel(node, panel) {
  const view = projectOutputView(panel.doc, panel.what);
  const key = `${panel.name}:${panel.what}`;
  const shown = node.querySelector(".project-output");
  if (shown && node.dataset.output === key && !panel.error && panel.doc != null && view.text) {
    // break-ui 2: the same output again updates in place, so a scroll position and a selection survive the 2-second poll
    const sub = node.querySelector(".panel-sub");
    if (sub) { sub.textContent = view.sub; sub.classList.toggle("running", view.running); }
    if (shown.textContent !== view.text) {
      const atEnd = followsEnd(shown.scrollTop, shown.clientHeight, shown.scrollHeight);
      shown.textContent = view.text;
      if (atEnd) shown.scrollTop = shown.scrollHeight;
    }
    return;
  }
  node.dataset.output = key;
  const head = h("div", { class: "panel-head" },
    h("div", { class: "panel-row" }, h("span", { class: "file-icon text" }, icon("code")),
      h("div", { class: "panel-title" }, h("div", { class: "panel-name", text: `${panel.name} · ${view.title}` }),
        h("div", { class: `panel-sub${view.running ? " running" : ""}`, text: view.sub })),
      h("div", { class: "panel-tools" }, h("button", { class: "icon-btn", type: "button", "aria-label": "Close the panel", onclick: closePanel }, icon("x")))));
  let body;
  if (panel.error) body = [h("p", { class: "panel-note", text: panel.error })];
  else if (panel.doc == null) body = [h("p", { class: "panel-note", text: "Loading…" })];
  else if (!view.text) body = [h("p", { class: "panel-note", text: view.empty })];
  else body = [h("pre", { class: "project-output", tabindex: "0", "aria-label": `${panel.name}'s ${view.title} output`, text: view.text })];
  setChildren(node, head, h("div", { class: "panel-body" }, body));
  const pre = node.querySelector(".project-output");
  if (pre && view.running) pre.scrollTop = pre.scrollHeight;  // a running output follows its newest line
}

async function startTest(name) {
  if (state.demo || state.testing.has(name)) return;
  state.testing.add(name);
  openProjectOutput(name, "test");
  renderStream({ follow: false });
  try {
    const started = await api("/api/run", { method: "POST", body: { action: "project_test", name } });
    const until = Date.now() + TEST_RUN_LIMIT_MS;
    let run = null;
    while (Date.now() < until) {
      await new Promise((resolve) => setTimeout(resolve, OUTPUT_POLL_MS));
      try { run = ((await api("/api/runs")).runs || []).find((r) => r.id === started.run_id) || null; } catch (e) { run = null; }
      if (!run || !run.running) break;
    }
    const env = (run && run.envelope) || {};
    if (run && run.exit === 2) toast(env.message || "The router refused the Test.");
  } catch (e) {
    toast(e.message);
  } finally {
    state.testing.delete(name);
    await loadStatus();
    renderStream({ follow: false });
    if (state.panel && state.panel.kind === "project" && state.panel.name === name) pollProjectOutput();
  }
}

// ---------- a project's Run and Stop (brief 31, decisions 3 to 7) ----------

function projectRunGroup(project) {
  // UI-1 row 14 (D3): Run, Stop and the run's line stay on the head's line 2; the run command's Set or Change moves into
  // Project ▾. Ids and handlers as before.
  const view = projectRunState(project);
  const demo = state.demo ? "Demo: nothing runs." : null;
  const busy = state.runBusy.has(project.name);
  const words = view.words ? `Run: ${view.words}` : "Run: none";
  const set = h("button", { class: "side-item", type: "button", role: "menuitem", id: "run-set", disabled: state.restarted, title: words,
    onclick: () => { closeProjectMenu(); openRunSheet(project); } }, h("span", { class: "name", text: words }), h("span", { class: "count", text: view.button }));
  const line = h("span", { class: "project-run" },
    h("button", { class: "btn btn-quiet", type: "button", id: "project-run", disabled: state.restarted || !!(demo || view.runOff) || busy,
      title: demo || view.runOff || "Start the run command in the project's own folder, with its .env (asks first)",
      onclick: () => askRun(project.name) }, "Run"),
    view.running ? h("button", { class: "btn btn-quiet", type: "button", id: "project-stop", disabled: state.restarted || !!demo || busy,
      title: demo || "End the run (asks first)", onclick: () => askStop(project.name) }, "Stop") : null,
    view.line ? h("button", { class: `link project-test-line tone-${view.tone}`, type: "button", title: "Show the run's output",
      onclick: () => openProjectOutput(project.name, "run") }, view.line) : null);
  return { line, set };
}

// One question before Run, Stop and a secret's Remove (decisions 7 and 9): the facts, Cancel, and the one button.
function openProjectConfirm({ title, lines, facts = [], after = [], button, onConfirm }) {
  if (state.navOpen) toggleNav(false);
  state.pc = { running: false, failure: null, onConfirm };
  state.sheetKind = "pconfirm";
  const sheet = h("div", { class: "sheet np pconfirm-sheet", id: "pc-sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "pc-title" },
    h("div", { class: "sheet-head" }, h("span", { class: "sheet-title", id: "pc-title", text: title }),
      h("button", { class: "icon-btn", type: "button", "aria-label": "Close", onclick: closeSheet }, icon("x"))),
    lines.map((line) => h("p", { class: "panel-note pc-line", text: line })),
    facts.map((fact) => h("div", { class: "pc-fact" }, h("div", { class: "pc-label", text: fact.label }),
      h("div", { class: `pc-code${fact.box ? " pc-box" : ""}`, tabindex: fact.box ? "0" : null, text: fact.text }))),
    after.map((line) => h("p", { class: "panel-note pc-line", text: line })),
    h("div", { class: "np-failure", id: "pc-failure", role: "alert", hidden: true }),
    h("div", { class: "np-foot" }, h("span", { class: "np-foot-note", id: "pc-foot" }),
      h("button", { class: "btn", type: "button", onclick: closeSheet }, "Cancel"),
      h("button", { class: "btn btn-primary", type: "button", id: "pc-go", onclick: () => confirmProject() }, button)));
  setChildren($("sheet"), sheet);
  $("sheet").hidden = false;
  $("pc-go").focus();
}

async function confirmProject() {
  const pc = state.pc;
  if (!pc || pc.running) return;
  pc.running = true;
  $("pc-go").setAttribute("aria-disabled", "true");
  $("pc-foot").textContent = "Running…";
  let failure = null;
  try {
    failure = await pc.onConfirm();
  } catch (e) {
    failure = { title: "Not run", message: e.message, exit: null, code: null };
  }
  if (state.pc !== pc) return;
  pc.running = false;
  if (!failure) { closeSheet(); return; }
  $("pc-go").setAttribute("aria-disabled", "false");
  $("pc-foot").textContent = "";
  paintFailure($("pc-failure"), failure);
}

async function askRun(name) {
  if (state.demo) return;
  let doc = null;
  try { doc = await api(`/api/project-output?name=${encodeURIComponent(name)}&kind=run`); } catch (e) { toast(e.message); return; }
  const words = runConfirmWords(doc);
  openProjectConfirm({ title: `Run ${name}?`, lines: words.lines, facts: words.facts, after: [...words.after, "Run only starts on your click. The router never runs it on its own."], button: "Run", onConfirm: async () => {
    state.runBusy.add(name);
    try {
      const result = await runProjectAction({ action: "project_run", name });
      if (result.code !== 0) return failureOf(result);
      await loadStatus();
      openProjectOutput(name, "run");
      return null;
    } finally {
      state.runBusy.delete(name);
      renderStream({ follow: false });
    }
  } });
}

async function askStop(name) {
  if (state.demo) return;
  openProjectConfirm({ title: `Stop the run on ${name}?`, button: "Stop",
    lines: ["Its process group gets SIGTERM, then SIGKILL after 10 seconds if it is still there.", "A run that ended is never started again by itself."],
    onConfirm: async () => {
      state.runBusy.add(name);
      try {
        const result = await runProjectAction({ action: "project_stop", name });
        if (result.code !== 0) return failureOf(result);
        await loadStatus();
        if (state.panel && state.panel.kind === "project" && state.panel.name === name) pollProjectOutput();
        return null;
      } finally {
        state.runBusy.delete(name);
        renderStream({ follow: false });
      }
    } });
}

// ---------- a project's Secrets (brief 31, decisions 8 and 9) ----------
// The page never keeps a value: the password field holds it until Save reads it once and clears it, whatever the result;
// state keeps only its length, for the command line's note.

async function loadSecrets() {
  const sc = state.sc;
  if (!sc) return;
  try {
    const doc = await api(`/api/project-secrets?name=${encodeURIComponent(sc.name)}`);
    if (state.sc !== sc) return;
    sc.doc = doc;
  } catch (e) {
    if (state.sc === sc) sc.failure = { title: "Not read", message: e.message, exit: null, code: null };
  }
  paintSecrets();
}

function openSecrets(name, key = "") {
  // brief 33.1 (decision 16): a plan's Secrets button names its key, filled in the Name field
  if (state.navOpen) toggleNav(false);
  state.sc = { name, doc: null, key, length: 0, running: false, failure: null, removing: null };
  state.sheetKind = "secrets";
  const keyField = h("input", { class: "np-input", id: "sc-key", autocomplete: "off", spellcheck: "false", placeholder: "DEMO_KEY",
    "aria-describedby": "sc-key-hint", value: key || null,
    oninput: (e) => { state.sc.key = e.target.value.trim(); state.sc.failure = null; paintSecrets(); } });
  const valueField = h("input", { class: "np-input", id: "sc-value", type: "password", autocomplete: "new-password", spellcheck: "false",
    placeholder: "the value (never shown)", oninput: (e) => { state.sc.length = e.target.value.length; paintSecrets(); },
    onkeydown: (e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); saveSecret(); } } });
  const sheet = h("div", { class: "sheet np secrets-sheet", id: "sc-sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "sc-title" },
    h("div", { class: "sheet-head" }, h("span", { class: "sheet-title", id: "sc-title" }),
      h("button", { class: "icon-btn", type: "button", "aria-label": "Close", onclick: closeSheet }, icon("x"))),
    h("p", { class: "panel-note", text: "A value lives only in the project's .env. The page never shows, keeps or logs one, and Run passes them to the program. Add writes the value into the project's .env, and the field clears." }),
    h("div", { class: "sc-list", id: "sc-list" }),
    h("div", { class: "np-field" }, h("label", { class: "np-label", for: "sc-key", text: "Name" }), keyField,
      h("div", { class: "np-hint", id: "sc-key-hint" })),
    h("div", { class: "np-field" }, h("label", { class: "np-label", for: "sc-value", text: "Value" }), valueField),
    h("div", { class: "np-hint", id: "sc-note" }),
    h("div", { class: "np-failure", id: "sc-failure", role: "alert", hidden: true }),
    h("div", { class: "np-foot" }, h("span", { class: "np-foot-note", id: "sc-foot" }),
      h("button", { class: "btn", type: "button", onclick: closeSheet }, "Close"),
      h("button", { class: "btn btn-primary", type: "button", id: "sc-save", onclick: () => saveSecret() }, "Add")));
  setChildren($("sheet"), sheet);
  $("sheet").hidden = false;
  paintSecrets();
  loadSecrets();
  (key ? valueField : keyField).focus();  // brief 33.1: a named key goes straight to its value
}

function paintSecrets() {
  const sc = state.sc;
  if (state.sheetKind !== "secrets" || !sc || !$("sc-sheet")) return;
  const view = secretsSheetView(sc.doc, { name: sc.name, key: sc.key, length: sc.length, running: sc.running, failure: sc.failure, demo: state.demo });
  $("sc-title").textContent = view.title;
  const rows = view.loading ? [h("p", { class: "panel-note", text: "Reading the names…" })]
    : view.empty ? [h("p", { class: "panel-note", text: "No names in its .env yet." })]
    : view.rows.map((row) => h("div", { class: "sc-row" },
      h("span", { class: "sc-name", text: row.name }), h("span", { class: `sc-state tone-${row.state === "set" ? "ok" : "muted"}`, text: row.state }),
      sc.removing === row.name
        ? h("span", { class: "sc-ask" }, h("span", { class: "sc-ask-text", text: `Remove ${row.name}?` }),
          h("button", { class: "btn", type: "button", onclick: () => { sc.removing = null; paintSecrets(); } }, "Cancel"),
          h("button", { class: "btn btn-primary", type: "button", disabled: sc.running || state.demo, onclick: () => removeSecret(row.name) }, "Remove"))
        : h("span", { class: "sc-actions" },
          h("button", { class: "btn btn-quiet", type: "button", disabled: sc.running, onclick: () => {
            sc.key = row.name; $("sc-key").value = row.name; $("sc-value").focus(); paintSecrets(); } }, "Change"),
          h("button", { class: "btn btn-quiet", type: "button", disabled: sc.running || state.demo, onclick: () => { sc.removing = row.name; paintSecrets(); } }, "Remove"))));
  setChildren($("sc-list"), ...rows);
  const hint = $("sc-key-hint");
  hint.className = `np-hint tone-${view.keyHint ? "bad" : "muted"}`;
  hint.textContent = view.keyHint || "";
  $("sc-note").textContent = view.line.note;
  const save = $("sc-save");
  save.setAttribute("aria-disabled", view.canSave ? "false" : "true");
  save.classList.toggle("is-off", !view.canSave);
  save.textContent = sc.running ? "Saving…" : view.save;
  $("sc-foot").textContent = view.foot || "";
  paintFailure($("sc-failure"), view.failure);
}

async function saveSecret() {
  const sc = state.sc;
  if (!sc || sc.running) return;
  const field = $("sc-value");
  const view = secretsSheetView(sc.doc, { name: sc.name, key: sc.key, length: sc.length, demo: state.demo });
  if (!view.canSave || !field) return;
  const request = { action: "project_secret_set", name: sc.name, key: sc.key, value: field.value };
  field.value = "";  // decision 9: the field clears at Save, whatever the result; nothing keeps the value
  sc.length = 0;
  sc.running = true;
  sc.failure = null;
  paintSecrets();
  let result;
  try {
    result = await runProjectAction(request);
  } catch (e) {
    result = { code: null, env: {}, message: e.message };
  }
  request.value = null;
  if (state.sc !== sc) { if (result.code !== 0) toast(result.message); return; }
  sc.running = false;
  if (result.code === 0) {
    toast(result.message || `${sc.key} saved`);
    sc.key = "";
    $("sc-key").value = "";
    await loadSecrets();  // D (brief 31): the list first; a fresh status can take seconds
    await loadStatus();
    renderStream({ follow: false });
    return;
  }
  sc.failure = failureOf(result);
  paintSecrets();
}

async function removeSecret(key) {
  const sc = state.sc;
  if (!sc || sc.running) return;
  sc.running = true;
  sc.failure = null;
  paintSecrets();
  let result;
  try {
    result = await runProjectAction({ action: "project_secret_remove", name: sc.name, key });
  } catch (e) {
    result = { code: null, env: {}, message: e.message };
  }
  if (state.sc !== sc) return;
  sc.running = false;
  sc.removing = null;
  if (result.code === 0) {
    toast(`Removed ${key}`);
    await loadSecrets();  // D (brief 31): the list first; a fresh status can take seconds
    await loadStatus();
    renderStream({ follow: false });
    return;
  }
  sc.failure = failureOf(result);
  paintSecrets();
}

// The run command sheet: one field, Save and Clear, as the tests sheet (decision 3).
function openRunSheet(project) {
  if (state.navOpen) toggleNav(false);
  state.rc = { name: project.name, words: projectRunState(project).words, running: false, failure: null };
  state.sheetKind = "runcmd";
  const field = h("textarea", { class: "np-input ts-words", id: "rc-words", rows: "3", autocomplete: "off", spellcheck: "false",
    placeholder: "python3 app.py", "aria-describedby": "rc-hint",
    oninput: (e) => { state.rc.words = e.target.value; state.rc.failure = null; paintRunSheet(); },
    onkeydown: (e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); saveRunCommand(false); } } });
  const sheet = h("div", { class: "sheet np tests-sheet", id: "rc-sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "rc-title" },
    h("div", { class: "sheet-head" }, h("span", { class: "sheet-title", id: "rc-title" }),
      h("button", { class: "icon-btn", type: "button", "aria-label": "Close", onclick: closeSheet }, icon("x"))),
    h("p", { class: "panel-note", text: "Run starts these words in the project's own folder with its .env, only when you click it; it isn't sandboxed. The router never starts it on its own." }),
    h("div", { class: "np-field" }, h("label", { class: "np-label", for: "rc-words", text: "Run command" }), field,
      h("div", { class: "np-hint", id: "rc-hint" })),
    h("div", { class: "np-failure", id: "rc-failure", role: "alert", hidden: true }),
    h("div", { class: "np-foot" }, h("span", { class: "np-foot-note", id: "rc-foot" }),
      h("button", { class: "btn", type: "button", onclick: closeSheet }, "Cancel"),
      h("button", { class: "btn btn-quiet", type: "button", id: "rc-clear", onclick: () => saveRunCommand(true) }, "Clear"),
      h("button", { class: "btn btn-primary", type: "button", id: "rc-save", onclick: () => saveRunCommand(false) }, "Save")));
  setChildren($("sheet"), sheet);
  $("sheet").hidden = false;
  field.value = state.rc.words;
  paintRunSheet();
  field.focus();
}

function paintRunSheet() {
  const rc = state.rc;
  if (state.sheetKind !== "runcmd" || !rc || !$("rc-sheet")) return;
  const project = projectOf(rc.name) || { name: rc.name, run_command: null };
  const view = runSheetView(project, rc.words, { running: rc.running, failure: rc.failure, demo: state.demo });
  $("rc-title").textContent = view.title;
  const hint = $("rc-hint");
  hint.className = `np-hint tone-${view.hintTone}`;
  hint.textContent = view.hint;
  for (const [id, on, words] of [["rc-clear", view.canClear, "Clear"], ["rc-save", view.canSave, view.saving ? "Saving…" : "Save"]]) {
    const button = $(id);
    button.setAttribute("aria-disabled", on ? "false" : "true");
    button.classList.toggle("is-off", !on);
    button.textContent = words;
  }
  $("rc-foot").textContent = view.foot || "";
  paintFailure($("rc-failure"), view.failure);
}

async function saveRunCommand(clear) {
  const rc = state.rc;
  if (!rc || rc.running) return;
  const project = projectOf(rc.name) || { name: rc.name, run_command: null };
  const view = runSheetView(project, rc.words, { demo: state.demo });
  if (clear ? !view.canClear : !view.canSave) return;
  rc.running = true;
  rc.failure = null;
  paintRunSheet();
  let result;
  try {
    result = await runProjectAction(clear ? { action: "project_run_command", name: rc.name, clear: true }
      : { action: "project_run_command", name: rc.name, words: rc.words });
  } catch (e) {
    rc.running = false;
    rc.failure = { title: "Not run", message: e.message, exit: null, code: null };
    paintRunSheet();
    return;
  }
  rc.running = false;
  if (result.code === 0) {
    await loadStatus();
    if (state.rc === rc) closeSheet();
    toast(clear ? `Cleared ${rc.name}'s run command` : `Run command for ${rc.name} saved`);
    renderStream({ follow: false });
    return;
  }
  rc.failure = failureOf(result);
  if (state.rc === rc) paintRunSheet(); else toast(result.message);
}

function sheetFailure(failure) {
  if (!failure) return null;
  return h("div", { class: "np-failure", role: "alert" }, h("div", { class: "np-failure-title", text: failure.title }),
    h("div", { class: "np-failure-text", text: failure.message }),
    failure.exit != null ? h("div", { class: "np-failure-exit", text: `exit ${failure.exit}${failure.code ? ` · ${failure.code}` : ""}` }) : null);
}

function failureOf(result) {
  return { title: result.code === 2 ? "The router refused this" : result.code == null ? "No answer" : "This stopped part way",
    message: result.message, exit: result.code, code: result.env.reason_code || null };
}

// The tests sheet: one field, Save and Clear. Built once, then painted in place, so typing keeps its focus and caret.
function openTestsSheet(project) {
  if (state.navOpen) toggleNav(false);
  state.ts = { name: project.name, words: projectTestsLine(project).words, running: false, failure: null };
  state.sheetKind = "tests";
  const field = h("textarea", { class: "np-input ts-words", id: "ts-words", rows: "3", autocomplete: "off",  // break-ui: a
    // 300-character command showed 75 characters at a time in one line
    spellcheck: "false", placeholder: "python3 -m unittest", "aria-describedby": "ts-hint",
    oninput: (e) => { state.ts.words = e.target.value; state.ts.failure = null; paintTests(); },
    onkeydown: (e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); saveTests(false); } } });
  const sheet = h("div", { class: "sheet np tests-sheet", id: "ts-sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "ts-title" },
    h("div", { class: "sheet-head" }, h("span", { class: "sheet-title", id: "ts-title" }),
      h("button", { class: "icon-btn", type: "button", "aria-label": "Close", onclick: closeSheet }, icon("x"))),
    h("p", { class: "panel-note", text: "After each change Claude makes, the router runs these words on a throwaway copy, in a sandbox with no network and no keys; the checker sees the results." }),
    h("div", { class: "np-field" }, h("label", { class: "np-label", for: "ts-words", text: "Test command" }), field,
      h("div", { class: "np-hint", id: "ts-hint" })),
    h("div", { class: "np-failure", id: "ts-failure", role: "alert", hidden: true }),
    h("div", { class: "np-foot" }, h("span", { class: "np-foot-note", id: "ts-foot" }),
      h("button", { class: "btn", type: "button", onclick: closeSheet }, "Cancel"),
      h("button", { class: "btn btn-quiet", type: "button", id: "ts-clear", onclick: () => saveTests(true) }, "Clear"),
      h("button", { class: "btn btn-primary", type: "button", id: "ts-save", onclick: () => saveTests(false) }, "Save")));
  setChildren($("sheet"), sheet);
  $("sheet").hidden = false;
  field.value = state.ts.words;
  paintTests();
  field.focus();
}

function paintFailure(node, failure) {
  const fresh = !!failure && node.hidden;
  node.hidden = !failure;
  if (!failure) { setChildren(node); return; }
  setChildren(node, h("div", { class: "np-failure-title", text: failure.title }), h("div", { class: "np-failure-text", text: failure.message }),
    failure.exit != null ? h("div", { class: "np-failure-exit", text: `exit ${failure.exit}${failure.code ? ` · ${failure.code}` : ""}` }) : null);
  if (fresh) node.scrollIntoView({ block: "nearest" });  // a refusal never lands out of sight
}

function paintTests() {
  const ts = state.ts;
  if (state.sheetKind !== "tests" || !ts || !$("ts-sheet")) return;
  const project = projectOf(ts.name) || { name: ts.name, tests: null };
  const view = testsSheetView(project, ts.words, { running: ts.running, failure: ts.failure, demo: state.demo });
  $("ts-title").textContent = view.title;
  const hint = $("ts-hint");
  hint.className = `np-hint tone-${view.hintTone}`;
  hint.textContent = view.hint;
  // aria-disabled, not disabled, so a keyboard user's focus stays on the button through a run (saveTests checks the view)
  for (const [id, on, words] of [["ts-clear", view.canClear, "Clear"], ["ts-save", view.canSave, view.saving ? "Saving…" : "Save"]]) {
    const button = $(id);
    button.setAttribute("aria-disabled", on ? "false" : "true");
    button.classList.toggle("is-off", !on);
    button.textContent = words;
  }
  $("ts-foot").textContent = view.foot || "";
  paintFailure($("ts-failure"), view.failure);
}

async function saveTests(clear) {
  const ts = state.ts;
  if (!ts || ts.running) return;
  const project = projectOf(ts.name) || { name: ts.name, tests: null };
  const view = testsSheetView(project, ts.words, { demo: state.demo });
  if (clear ? !view.canClear : !view.canSave) return;
  ts.running = true;
  ts.failure = null;
  paintTests();
  let result;
  try {
    result = await runProjectAction(clear ? { action: "project_tests", name: ts.name, clear: true }
      : { action: "project_tests", name: ts.name, words: ts.words });
  } catch (e) {
    ts.running = false;
    ts.failure = { title: "Not run", message: e.message, exit: null, code: null };
    paintTests();
    return;
  }
  ts.running = false;
  if (result.code === 0) {
    await loadStatus();
    if (state.ts === ts) closeSheet();
    toast(clear ? `Cleared ${ts.name}'s test command` : `Tests for ${ts.name} saved`);
    renderStream({ follow: false });
    return;
  }
  ts.failure = failureOf(result);
  if (state.ts === ts) paintTests(); else toast(result.message);
}

// ---------- brief 30: the Router notes editor, a project's Notes, Pin to notes, Save to project ----------

function sheetHead(id, title, onClose) {
  return h("div", { class: "sheet-head" }, h("span", { class: "sheet-title", id, text: title }),
    h("button", { class: "icon-btn", type: "button", "aria-label": "Close", onclick: onClose || requestCloseSheet }, icon("x")));
}

function commandLine(id) {
  // UI B N10 (Q4, D26): the sheets' command lines go; this place holds only the words of a refused command
  return h("div", { class: "np-hint tone-bad sheet-refused", id, role: "alert", hidden: true });
}

function paintCommand(id, found) {
  const node = $(id);
  if (!node) return;
  node.hidden = !(found && found.error);
  node.textContent = found && found.error ? `Refused: ${found.error}` : "";
}

async function askCommand(id, request, seqHolder, repaint = null) {
  // the server's builder, asked so a refused command shows: a refusal is kept on the sheet (`refused`), which keeps Save
  // off, as Confirm does for a refused action (break-ui; rules: Save stays off on a refused command)
  if (state.demo) { paintCommand(id, null); return; }
  const seq = (seqHolder.seq = (seqHolder.seq || 0) + 1);
  let found;
  try {
    found = await api("/api/command", { method: "POST", body: request });
  } catch (e) {
    found = { error: e.message };
  }
  if (seqHolder.seq !== seq) return;
  seqHolder.refused = found.error || null;
  paintCommand(id, found);
  if (repaint) repaint();
}

function clearCommand(id, seqHolder) {
  // nothing to build yet (no project, no path, a text too long to send): no line, and no old refusal kept
  seqHolder.seq = (seqHolder.seq || 0) + 1;
  seqHolder.refused = null;
  paintCommand(id, { parts: [] });
}

// The Router notes editor (decision 10): one box holding the file, the saved file's counts, Grok's share, Save.
async function openNotesEditor() {
  if (state.navOpen) toggleNav(false);
  state.ne = { doc: null, text: null, running: false, failure: null, closing: false, seq: 0 };
  state.sheetKind = "notes";
  const field = h("textarea", { class: "np-input notes-box", id: "ne-box", rows: "16", spellcheck: "false", autocomplete: "off",
    "aria-describedby": "ne-state", "aria-label": "Router notes",
    oninput: (e) => { state.ne.text = e.target.value; state.ne.failure = null; state.ne.closing = false; paintNotesEditor(); refreshNotesCommand(); } });
  const sheet = h("div", { class: "sheet np notes-sheet", id: "ne-sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "ne-title" },
    sheetHead("ne-title", "Router notes"),
    h("p", { class: "panel-note", text: "Sent first with every agent call, as your standing instructions: All agents to each, and each agent's own section to it; Planner to a split's plan. The task, the role's instructions and the reply format win any conflict, and a checker never fails a result for them. They reach every agent's service (Grok Bot's inbox too), so keep them free of anything private; keys are refused. Save writes them to this Mac's router notes; every task from the next one on gets them." }),
    h("div", { class: "np-hint", id: "ne-state" }),
    h("div", { class: "np-field" }, field),
    h("div", { class: "notes-counts", id: "ne-counts" }),
    h("div", { class: "np-hint", id: "ne-grok" }),
    commandLine("ne-cmd"),
    h("div", { class: "np-failure", id: "ne-failure", role: "alert", hidden: true }),
    h("div", { class: "np-hint tone-warn", id: "ne-close-note", hidden: true }),
    h("div", { class: "np-foot" }, h("span", { class: "np-foot-note", id: "ne-foot" }),
      h("button", { class: "btn", type: "button", id: "ne-close", onclick: requestCloseSheet }, "Close"),
      h("button", { class: "btn btn-primary", type: "button", id: "ne-save", onclick: saveNotes }, "Save")));
  setChildren($("sheet"), sheet);
  $("sheet").hidden = false;
  paintNotesEditor();
  await loadNotesDoc();
  if (state.ne && state.sheetKind === "notes") { field.value = state.ne.text; paintNotesEditor(); refreshNotesCommand(); field.focus(); }
}

async function loadNotesDoc() {
  const ne = state.ne;
  try {
    const found = await api("/api/notes");
    if (state.ne !== ne) return;
    ne.doc = found.notes;
    if (ne.text == null) ne.text = ne.doc.text;
  } catch (e) {
    if (state.ne === ne) ne.failure = { title: "The notes could not be read", message: e.message, exit: null, code: null };
  }
}

function refreshNotesCommand() {
  const ne = state.ne;
  if (!ne || !ne.doc) return;
  askCommand("ne-cmd", { action: "notes_save", expect: ne.doc.hash, text: ne.text == null ? ne.doc.text : ne.text }, ne, paintNotesEditor);
}

function paintNotesEditor() {
  const ne = state.ne;
  if (state.sheetKind !== "notes" || !ne || !$("ne-sheet")) return;
  const view = notesEditorView(ne.doc, ne.text, { saving: ne.running, failure: ne.failure, closing: ne.closing, demo: state.demo,
    refused: ne.refused });
  const stateLine = $("ne-state");
  stateLine.className = `np-hint tone-${view.stateTone || "muted"}`;
  stateLine.textContent = view.loading ? "Reading the notes…" : [view.state, view.where].filter(Boolean).join(" · ");
  setChildren($("ne-counts"), view.loading ? [] : [
    h("div", { class: "notes-sections" }, view.sections.map((sec) => h("span", { class: "pill" }, sec.title, h("b", { text: sec.chars })))),
    h("div", { class: "np-hint", text: view.total })]);
  $("ne-grok").textContent = view.grok || "";
  const save = $("ne-save");
  save.setAttribute("aria-disabled", view.canSave ? "false" : "true");
  save.classList.toggle("is-off", !view.canSave);
  save.textContent = view.saving ? "Saving…" : "Save";
  $("ne-close").textContent = view.closeWords;
  const note = $("ne-close-note");
  note.hidden = !view.closeNote;
  note.textContent = view.closeNote || "";
  $("ne-foot").textContent = view.foot || "";
  paintFailure($("ne-failure"), view.failure);
}

async function saveNotes() {
  const ne = state.ne;
  if (!ne || !ne.doc) return;
  const view = notesEditorView(ne.doc, ne.text, { saving: ne.running, demo: state.demo });
  if (!view.canSave) { if (state.demo) toast("Demo: nothing runs."); return; }
  ne.running = true;
  ne.failure = null;
  paintNotesEditor();
  let result;
  try {
    result = await runProjectAction({ action: "notes_save", expect: ne.doc.hash, text: ne.text });
  } catch (e) {
    ne.running = false;
    ne.failure = { title: "Not run", message: e.message, exit: null, code: null };
    paintNotesEditor();
    return;
  }
  ne.running = false;
  if (result.code === 0) {
    ne.doc = null;
    await loadNotesDoc();  // the router's counts and hash for what was saved
    await loadStatus();
    if (state.ne === ne) { ne.text = ne.doc ? ne.doc.text : ne.text; ne.closing = false; paintNotesEditor(); refreshNotesCommand(); }
    toast("Router notes saved: they go with every task from the next one on");
    return;
  }
  ne.failure = failureOf(result);  // the box keeps what you typed
  if (state.ne === ne) paintNotesEditor(); else toast(result.message);
}

// A project's Notes (decision 17): the notes in a box, the router's block read-only under it, Save.
async function openProjectNotes(name) {
  if (state.navOpen) toggleNav(false);
  state.pn = { name, doc: null, text: null, running: false, failure: null, closing: false, seq: 0 };
  state.sheetKind = "pnotes";
  const field = h("textarea", { class: "np-input notes-box", id: "pn-box", rows: "12", spellcheck: "true", autocomplete: "off",
    "aria-label": `Notes of ${name}`, "aria-describedby": "pn-counts",
    oninput: (e) => { state.pn.text = e.target.value; state.pn.failure = null; state.pn.closing = false; paintProjectNotes(); refreshProjectNotesCommand(); } });
  const sheet = h("div", { class: "sheet np notes-sheet", id: "pn-sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "pn-title" },
    sheetHead("pn-title", `Notes of ${name}`),
    h("p", { class: "panel-note", text: "The part of the project's HANDOFF.md above the router's block. It rides on every call of the project; editing it is how you correct what the project's tasks believe. Save writes them into HANDOFF.md, around the router's block." }),
    h("div", { class: "np-field" }, field),
    h("div", { class: "np-hint", id: "pn-counts" }),
    h("div", { class: "np-hint", id: "pn-commit" }),
    h("details", { class: "pn-block" }, h("summary", { text: "The router's block (read-only)" }),
      h("pre", { class: "mono pn-block-text", id: "pn-block" })),
    commandLine("pn-cmd"),
    h("div", { class: "np-failure", id: "pn-failure", role: "alert", hidden: true }),
    h("div", { class: "np-hint tone-warn", id: "pn-close-note", hidden: true }),
    h("div", { class: "np-foot notes-foot" }, h("span", { class: "np-foot-note", id: "pn-foot" }),
      h("button", { class: "btn btn-primary", type: "button", id: "pn-save", onclick: saveProjectNotes }, "Save")),
    specSection(name),  // brief 33.2 (decision 4): the Spec section, below the notes, its own Save
    h("div", { class: "np-foot" },  // break-ui: Close stays at the sheet's end, under both sections
      h("button", { class: "btn", type: "button", id: "pn-close", onclick: requestCloseSheet }, "Close")));
  setChildren($("sheet"), sheet);
  $("sheet").hidden = false;
  paintProjectNotes();
  paintProjectSpec();
  await Promise.all([loadProjectNotesDoc(), loadProjectSpecDoc()]);
  if (state.pn && state.sheetKind === "pnotes") {
    field.value = state.pn.text; paintProjectNotes(); refreshProjectNotesCommand(); field.focus();
    const box = $("pn-spec-box"); if (box) box.value = state.pn.spec.text || ""; paintProjectSpec(); refreshProjectSpecCommand();
  }
}

function specSection(name) {
  // brief 33.2 (decision 4): SPEC.md's box, the labels as the router read them, Save (off while the box holds the saved
  // file), the router's answer on a refusal with the box kept as typed; "Spec · none" with Draft it while there is none
  state.pn.spec = { doc: null, text: null, running: false, failure: null, seq: 0 };
  const box = h("textarea", { class: "np-input notes-box", id: "pn-spec-box", rows: "8", spellcheck: "true", autocomplete: "off",
    "aria-label": `SPEC.md of ${name}`, "aria-describedby": "pn-spec-counts",
    oninput: (e) => { state.pn.spec.text = e.target.value; state.pn.spec.failure = null; paintProjectSpec(); refreshProjectSpecCommand(); } });
  return h("div", { class: "spec-section", id: "pn-spec" },
    h("div", { class: "spec-head" }, h("span", { class: "spec-title", id: "pn-spec-title", text: "Spec" }),
      h("button", { class: "next-chip", type: "button", id: "pn-spec-draft", hidden: true }, h("span", { class: "next-words", text: "Draft it" }))),
    h("p", { class: "panel-note", text: "SPEC.md at the project's top level: what the project is for. It rides on every agent call of the project, "
      + "as data; the lists under ## Examples and ## Done when are read by code and labeled E1…, D1…. Only you change it: a build's change to it is put back." }),
    h("div", { class: "np-field" }, box),
    h("div", { class: "np-hint", id: "pn-spec-counts" }),
    h("div", { class: "np-hint", id: "pn-spec-commit" }),
    h("div", { class: "spec-labels", id: "pn-spec-labels" }),
    commandLine("pn-spec-cmd"),
    h("div", { class: "np-failure", id: "pn-spec-failure", role: "alert", hidden: true }),
    h("div", { class: "np-foot" }, h("span", { class: "np-foot-note", id: "pn-spec-foot" }),
      h("button", { class: "btn btn-primary", type: "button", id: "pn-spec-save", onclick: saveProjectSpec }, "Save")));
}

async function loadProjectSpecDoc() {
  const pn = state.pn;
  if (!pn || !pn.spec) return;
  try {
    const found = await api(`/api/project-spec?name=${encodeURIComponent(pn.name)}`);
    if (state.pn !== pn) return;
    pn.spec.doc = found.spec;
    if (pn.spec.text == null) pn.spec.text = pn.spec.doc.text;
  } catch (e) {
    if (state.pn === pn) pn.spec.failure = { title: "The spec could not be read", message: e.message, exit: null, code: null };
  }
}

function refreshProjectSpecCommand() {
  const pn = state.pn;
  if (!pn || !pn.spec || !pn.spec.doc) return;
  askCommand("pn-spec-cmd", { action: "project_spec_save", name: pn.name, expect: pn.spec.doc.hash, text: pn.spec.text == null ? pn.spec.doc.text : pn.spec.text },
    pn.spec, paintProjectSpec);
}

function paintProjectSpec() {
  const pn = state.pn;
  if (state.sheetKind !== "pnotes" || !pn || !pn.spec || !$("pn-spec")) return;
  const view = projectSpecView(pn.spec.doc, pn.spec.text, { saving: pn.spec.running, failure: pn.spec.failure, demo: state.demo });
  $("pn-spec-title").textContent = view.loading ? "Spec · reading…" : view.title;
  $("pn-spec-counts").textContent = view.loading ? "" : view.counts;
  $("pn-spec-commit").textContent = view.commit || "";
  setChildren($("pn-spec-labels"), view.labeledNote ? [h("div", { class: "np-hint", text: view.labeledNote })]
    : view.labels.map((l) => h("div", { class: "spec-label" }, h("code", { text: l.label }), h("span", { text: ` ${l.text}` }))));
  const draft = $("pn-spec-draft");
  draft.hidden = !view.draft;
  draft.onclick = view.draft ? () => { closeSheet(); if (state.project !== pn.name) openProject(pn.name); useChip(view.draft, { n: null }); } : null;
  draft.title = view.draft ? "Fills the box with a text-only task that writes the spec; you read it, then Save to project at SPEC.md" : "";
  const save = $("pn-spec-save");
  save.setAttribute("aria-disabled", view.canSave ? "false" : "true");
  save.classList.toggle("is-off", !view.canSave);
  save.textContent = view.saveWords || "Save";
  $("pn-spec-foot").textContent = view.foot || "";
  paintFailure($("pn-spec-failure"), view.failure);
}

async function saveProjectSpec() {
  const pn = state.pn;
  if (!pn || !pn.spec || !pn.spec.doc) return;
  const view = projectSpecView(pn.spec.doc, pn.spec.text, { saving: pn.spec.running, demo: state.demo });
  if (!view.canSave) { if (state.demo) toast("Demo: nothing runs."); return; }
  pn.spec.running = true;
  pn.spec.failure = null;
  paintProjectSpec();
  let result;
  try {
    result = await runProjectAction({ action: "project_spec_save", name: pn.name, expect: pn.spec.doc.hash, text: pn.spec.text });
  } catch (e) {
    pn.spec.running = false;
    pn.spec.failure = { title: "Not run", message: e.message, exit: null, code: null };
    paintProjectSpec();
    return;
  }
  pn.spec.running = false;
  if (result.code === 0) {
    pn.spec.doc = null;
    await loadProjectSpecDoc();
    if (state.pn === pn) { pn.spec.text = pn.spec.doc ? pn.spec.doc.text : pn.spec.text; paintProjectSpec(); refreshProjectSpecCommand(); }
    toast(`SPEC.md of ${pn.name} saved`);
    const reads = specSaveReads(result.code);  // brief 33.2 fix 2: the project read again, so the plan card is current
    if (reads.includes("status")) await loadStatus();
    if (reads.includes("log")) await loadLog();
    if (reads.includes("what_now")) await loadWhatNow();
    if (reads.includes("shows")) {
      for (const task of state.tasks || []) {
        if (task.mode === "plan" && task.project === pn.name && task.waiting_on === "land") await loadShow(task.task_id, { quiet: true });
      }
    }
    render();
    return;
  }
  pn.spec.failure = failureOf(result);  // the box keeps what was typed
  if (state.pn === pn) paintProjectSpec(); else toast(result.message);
}

async function loadProjectNotesDoc() {
  const pn = state.pn;
  try {
    const found = await api(`/api/project-notes?name=${encodeURIComponent(pn.name)}`);
    if (state.pn !== pn) return;
    pn.doc = found.notes;
    if (pn.text == null) pn.text = pn.doc.notes;
  } catch (e) {
    if (state.pn === pn) pn.failure = { title: "The notes could not be read", message: e.message, exit: null, code: null };
  }
}

function refreshProjectNotesCommand() {
  const pn = state.pn;
  if (!pn || !pn.doc) return;
  askCommand("pn-cmd", { action: "project_notes_save", name: pn.name, expect: pn.doc.hash, text: pn.text == null ? pn.doc.notes : pn.text },
    pn, paintProjectNotes);
}

function paintProjectNotes() {
  const pn = state.pn;
  if (state.sheetKind !== "pnotes" || !pn || !$("pn-sheet")) return;
  const view = projectNotesView(pn.doc, pn.text, { saving: pn.running, failure: pn.failure, closing: pn.closing, demo: state.demo });
  $("pn-counts").textContent = view.loading ? "Reading the notes…" : view.counts;
  $("pn-commit").textContent = view.commit || "";
  $("pn-block").textContent = view.block || "";
  const save = $("pn-save");
  save.setAttribute("aria-disabled", view.canSave ? "false" : "true");
  save.classList.toggle("is-off", !view.canSave);
  save.textContent = view.saving ? "Saving…" : "Save";
  $("pn-close").textContent = view.closeWords;
  const note = $("pn-close-note");
  note.hidden = !view.closeNote;
  note.textContent = view.closeNote || "";
  $("pn-foot").textContent = view.foot || "";
  paintFailure($("pn-failure"), view.failure);
}

async function saveProjectNotes() {
  const pn = state.pn;
  if (!pn || !pn.doc) return;
  const view = projectNotesView(pn.doc, pn.text, { saving: pn.running, demo: state.demo });
  if (!view.canSave) { if (state.demo) toast("Demo: nothing runs."); return; }
  pn.running = true;
  pn.failure = null;
  paintProjectNotes();
  let result;
  try {
    result = await runProjectAction({ action: "project_notes_save", name: pn.name, expect: pn.doc.hash, text: pn.text });
  } catch (e) {
    pn.running = false;
    pn.failure = { title: "Not run", message: e.message, exit: null, code: null };
    paintProjectNotes();
    return;
  }
  pn.running = false;
  if (result.code === 0) {
    pn.doc = null;
    await loadProjectNotesDoc();
    if (state.pn === pn) { pn.text = pn.doc ? pn.doc.notes : pn.text; pn.closing = false; paintProjectNotes(); refreshProjectNotesCommand(); }
    toast(`Notes of ${pn.name} saved`);
    return;
  }
  pn.failure = failureOf(result);
  if (state.pn === pn) paintProjectNotes(); else toast(result.message);
}

// The card's actions (decisions 13 to 15): Pin to notes and Save to project open a sheet; Forget runs at once.
function notesAction(task, a) {
  // brief 30 (decision 17): Pin to notes, Save to project, Forget or Remember again, as the card's quiet buttons did; UI-1
  // row 4 (D13): now the ⋯ menu's items, with these same handlers
  return a.key === "pin" ? openPinSheet(task) : a.key === "save" ? openSaveSheet(task)
    : state.demo ? toast("Demo: nothing runs.") : runAction(task, a.request);
}

function selectionIn(task) {
  // what you selected inside this card's result, or "" (decision 13)
  const sel = window.getSelection && window.getSelection();
  const card = document.getElementById(`card-${task.task_id}`);
  const result = card && card.querySelector(".answer .result");
  if (!sel || sel.isCollapsed || !result || !result.contains(sel.anchorNode) || !result.contains(sel.focusNode)) return "";
  return sel.toString();
}

function projectSelect(id, choice, onChange) {
  if (choice.fixed) return h("div", { class: "np-hint", text: `Project: ${choice.chosen}` });
  return h("select", { class: "np-input", id, onchange: (e) => onChange(e.target.value || null) },
    h("option", { value: "", text: "Pick a project…", selected: !choice.chosen ? true : null }),
    choice.options.map((name) => h("option", { value: name, text: name, selected: name === choice.chosen ? true : null })));
}

function openPinSheet(task) {
  if (state.navOpen) toggleNav(false);
  state.ps = { task, project: null, text: pinText(task, selectionIn(task)), notes: null, running: false, failure: null, seq: 0 };
  state.sheetKind = "pin";
  const projects = (state.status && state.status.projects) || [];
  const choice = projectChoice(task, projects);
  const field = h("textarea", { class: "np-input notes-box", id: "ps-box", rows: "8", "aria-label": "What to pin",
    oninput: (e) => { state.ps.text = e.target.value; state.ps.failure = null; paintPin(); refreshPinCommand(); } });
  const sheet = h("div", { class: "sheet np", id: "ps-sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "ps-title" },
    sheetHead("ps-title", `Pin #${task.n} to notes`),
    h("p", { class: "panel-note", text: "Adds the text at the end of the project's notes under its own heading, as one commit. Edit it first if you like." }),
    h("div", { class: "np-field" }, h("label", { class: "np-label", for: "ps-project", text: "Project" }),
      projectSelect("ps-project", choice, (name) => { state.ps.project = name; state.ps.notes = null; paintPin(); loadPinNotes(); refreshPinCommand(); })),
    h("div", { class: "np-field" }, h("label", { class: "np-label", for: "ps-box", text: "Text" }), field),
    h("div", { class: "np-hint", id: "ps-size" }),
    commandLine("ps-cmd"),
    h("div", { class: "np-failure", id: "ps-failure", role: "alert", hidden: true }),
    h("div", { class: "np-foot" }, h("span", { class: "np-foot-note", id: "ps-foot" }),
      h("button", { class: "btn", type: "button", onclick: closeSheet }, "Cancel"),
      h("button", { class: "btn btn-primary", type: "button", id: "ps-save", onclick: savePin }, "Save")));
  setChildren($("sheet"), sheet);
  $("sheet").hidden = false;
  field.value = state.ps.text;
  paintPin();
  loadPinNotes();
  refreshPinCommand();
  field.focus();
}

async function loadPinNotes() {
  const ps = state.ps;
  const name = ps && projectChoice(ps.task, (state.status && state.status.projects) || [], ps.project).chosen;
  if (!name) return;
  try {
    const found = await api(`/api/project-notes?name=${encodeURIComponent(name)}`);
    if (state.ps === ps) { ps.notes = found.notes; paintPin(); refreshPinCommand(); }
  } catch (e) {
    if (state.ps === ps) { ps.failure = { title: "The project's notes could not be read", message: e.message, exit: null, code: null }; paintPin(); }
  }
}

function pinView() {
  const ps = state.ps;
  return pinSheetView(ps.task, (state.status && state.status.projects) || [], { project: ps.project, text: ps.text, notes: ps.notes,
    running: ps.running, failure: ps.failure, demo: state.demo, refused: ps.refused });
}

function refreshPinCommand() {
  const ps = state.ps;
  const view = ps && pinView();
  // the command waits for the project's notes: only then is a text too long to send known (break-ui)
  if (!view || !view.chosen || !ps.notes || view.tooLong) { if (ps) clearCommand("ps-cmd", ps); return; }
  askCommand("ps-cmd", { action: "project_pin", name: view.chosen, task_id: ps.task.task_id, text: ps.text }, ps, paintPin);
}

function paintPin() {
  if (state.sheetKind !== "pin" || !state.ps || !$("ps-sheet")) return;
  const view = pinView();
  $("ps-size").textContent = view.size;
  $("ps-size").classList.toggle("tone-bad", view.sizeTone === "bad");
  const save = $("ps-save");
  save.setAttribute("aria-disabled", view.canSave ? "false" : "true");
  save.classList.toggle("is-off", !view.canSave);
  save.textContent = view.saving ? "Saving…" : "Save";
  $("ps-foot").textContent = view.foot || "";
  paintFailure($("ps-failure"), view.failure);
}

async function savePin() {
  const ps = state.ps;
  if (!ps) return;
  const view = pinView();
  if (!view.canSave) { if (state.demo) toast("Demo: nothing runs."); return; }
  ps.running = true;
  ps.failure = null;
  paintPin();
  let result;
  try {
    result = await runProjectAction({ action: "project_pin", name: view.chosen, task_id: ps.task.task_id, text: ps.text });
  } catch (e) {
    ps.running = false;
    ps.failure = { title: "Not run", message: e.message, exit: null, code: null };
    paintPin();
    return;
  }
  ps.running = false;
  if (result.code === 0) {
    if (state.ps === ps) closeSheet();
    toast(`Pinned #${ps.task.n} to the notes of ${view.chosen}`);
    return;
  }
  ps.failure = failureOf(result);
  if (state.ps === ps) paintPin(); else toast(result.message);
}

function openSaveSheet(task) {
  if (state.navOpen) toggleNav(false);
  state.sf = { task, project: null, path: task.save_path || "", running: false, failure: null, seq: 0 };
  state.sheetKind = "savefile";
  const projects = (state.status && state.status.projects) || [];
  const choice = projectChoice(task, projects);
  const field = h("input", { class: "np-input", id: "sf-path", type: "text", spellcheck: "false", autocomplete: "off",
    "aria-describedby": "sf-hint", oninput: (e) => { state.sf.path = e.target.value; state.sf.failure = null; paintSave(); refreshSaveCommand(); },
    onkeydown: (e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); saveFile(); } } });
  const sheet = h("div", { class: "sheet np", id: "sf-sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "sf-title" },
    sheetHead("sf-title", `Save #${task.n} to a project`),
    h("p", { class: "panel-note", text: "Save writes the result as a new file in the project, as one commit. It never overwrites a file." }),
    h("div", { class: "np-field" }, h("label", { class: "np-label", for: "sf-project", text: "Project" }),
      projectSelect("sf-project", choice, (name) => { state.sf.project = name; paintSave(); refreshSaveCommand(); })),
    h("div", { class: "np-field" }, h("label", { class: "np-label", for: "sf-path", text: "Path" }), field,
      h("div", { class: "np-hint", id: "sf-hint" })),
    commandLine("sf-cmd"),
    h("div", { class: "np-failure", id: "sf-failure", role: "alert", hidden: true }),
    h("div", { class: "np-foot" }, h("span", { class: "np-foot-note", id: "sf-foot" }),
      h("button", { class: "btn", type: "button", onclick: closeSheet }, "Cancel"),
      h("button", { class: "btn btn-primary", type: "button", id: "sf-save", onclick: saveFile }, "Save")));
  setChildren($("sheet"), sheet);
  $("sheet").hidden = false;
  field.value = state.sf.path;
  paintSave();
  refreshSaveCommand();
  field.focus();
}

function saveView() {
  const sf = state.sf;
  return saveSheetView(sf.task, (state.status && state.status.projects) || [], { project: sf.project, path: sf.path,
    running: sf.running, failure: sf.failure, demo: state.demo, refused: sf.refused });
}

function refreshSaveCommand() {
  const sf = state.sf;
  const view = sf && saveView();
  if (!view || !view.chosen || !view.path.trim()) { if (sf) clearCommand("sf-cmd", sf); return; }
  askCommand("sf-cmd", { action: "project_save", name: view.chosen, task_id: sf.task.task_id, path: view.path }, sf, paintSave);
}

function paintSave() {
  if (state.sheetKind !== "savefile" || !state.sf || !$("sf-sheet")) return;
  const view = saveView();
  $("sf-hint").textContent = view.hint;
  const save = $("sf-save");
  save.setAttribute("aria-disabled", view.canSave ? "false" : "true");
  save.classList.toggle("is-off", !view.canSave);
  save.textContent = view.saving ? "Saving…" : "Save";
  $("sf-foot").textContent = view.foot || "";
  paintFailure($("sf-failure"), view.failure);
}

async function saveFile() {
  const sf = state.sf;
  if (!sf) return;
  const view = saveView();
  if (!view.canSave) { if (state.demo) toast("Demo: nothing runs."); return; }
  sf.running = true;
  sf.failure = null;
  paintSave();
  let result;
  try {
    result = await runProjectAction({ action: "project_save", name: view.chosen, task_id: sf.task.task_id, path: view.path });
  } catch (e) {
    sf.running = false;
    sf.failure = { title: "Not run", message: e.message, exit: null, code: null };
    paintSave();
    return;
  }
  sf.running = false;
  if (result.code === 0) {
    if (state.sf === sf) closeSheet();
    await loadStatus();
    toast(`Saved #${sf.task.n} to ${view.chosen} as ${view.path}`);
    return;
  }
  sf.failure = failureOf(result);
  if (state.sf === sf) paintSave(); else toast(result.message);
}

// Turn on undo: the dry run's counts, then Confirm
let gitWaitTimer = null;

function openTurnOnUndo(project) {
  if (state.navOpen) toggleNav(false);
  state.gu = { name: project.name, check: null, running: false, failure: null, waited: false, seq: 0 };
  state.sheetKind = "git";
  const sheet = h("div", { class: "sheet np git-sheet", id: "git-sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "git-title" },
    h("div", { class: "sheet-head" }, h("span", { class: "sheet-title", id: "git-title", text: `Turn on undo for ${project.name}` }),
      h("button", { class: "icon-btn", type: "button", "aria-label": "Close", onclick: closeSheet }, icon("x"))),
    h("p", { class: "panel-note", text: "The router sets up git for this folder and makes one first commit, so each change an agent makes can land as a commit, and Undo can take it back." }),
    h("div", { class: "np-folder tone-muted", id: "git-state", role: "status", "aria-live": "polite" }),
    h("ul", { class: "git-names", id: "git-names", "aria-label": "What the first commit holds", hidden: true }),
    h("div", { class: "np-failure", id: "git-failure", role: "alert", hidden: true }),
    h("div", { class: "np-foot" }, h("span", { class: "np-foot-note", id: "git-foot" }),
      h("button", { class: "btn", type: "button", onclick: closeSheet }, "Cancel"),
      h("button", { class: "btn btn-primary", type: "button", id: "git-confirm", onclick: confirmGit }, "Confirm")));
  setChildren($("sheet"), sheet);
  $("sheet").hidden = false;
  paintGit();
  askGitCheck(state.gu);
  $("git-confirm").focus();
}

async function askGitCheck(gu) {
  const seq = ++gu.seq;
  clearTimeout(gitWaitTimer);
  gitWaitTimer = setTimeout(() => { if (state.gu === gu && !gu.check) { gu.waited = true; paintGit(); } }, NP_WAIT_MS);
  try {
    const found = await api(`/api/project-git-check?name=${encodeURIComponent(gu.name)}`);
    if (state.gu !== gu || seq !== gu.seq) return;
    gu.check = found;
  } catch (e) {
    if (state.gu !== gu || seq !== gu.seq) return;
    gu.failure = { title: "Can't check", message: e.message, exit: null, code: null };
  }
  paintGit();
}

function paintGit() {
  const gu = state.gu;
  if (state.sheetKind !== "git" || !gu || !$("git-sheet")) return;
  const view = gitCheckView(gu.check, { name: gu.name, running: gu.running, failure: gu.failure, demo: state.demo, waited: gu.waited });
  const box = $("git-state");
  box.className = `np-folder tone-${view.tone}`;
  setChildren(box, icon("folder"), h("span", { class: "np-state", text: view.title }), view.lines.map((line) => h("span", { class: "np-detail", text: line })));
  const names = $("git-names");
  names.hidden = !view.names.length;
  setChildren(names, view.names.map((n) => h("li", { title: n, text: middleTruncate(n, 64) })),
    view.more ? h("li", { class: "muted", text: `and ${view.more} more` }) : null);
  const confirm = $("git-confirm");
  confirm.setAttribute("aria-disabled", view.canConfirm ? "false" : "true");
  confirm.classList.toggle("is-off", !view.canConfirm);
  confirm.textContent = view.confirm || "Confirm";
  $("git-foot").textContent = view.foot || "";
  paintFailure($("git-failure"), view.failure);
}

async function confirmGit() {
  const gu = state.gu;
  if (!gu || gu.running) return;
  const view = gitCheckView(gu.check, { name: gu.name, demo: state.demo });
  if (!view.canConfirm) return;
  gu.running = true;
  gu.failure = null;
  paintGit();
  let result;
  try {
    result = await runProjectAction({ action: "project_git", name: gu.name });
  } catch (e) {
    gu.running = false;
    gu.failure = { title: "Not run", message: e.message, exit: null, code: null };
    paintGit();
    return;
  }
  gu.running = false;
  if (result.code === 0) {
    await loadStatus();
    if (state.gu === gu) closeSheet();
    toast(`Undo is on for ${gu.name}`);
    renderStream({ follow: false });
    return;
  }
  gu.failure = failureOf(result);
  if (state.gu === gu) { paintGit(); askGitCheck(gu); } else toast(result.message);
}

// Files dropped on a project: the list, Add (the click itself), the router's refusal or the commit
async function dropOnProject(name, fileList) {
  const files = Array.from(fileList || []);
  if (!files.length) return;
  state.fd = { name, files: [], refused: [], running: false, failure: null, done: null, writing: true };
  state.sheetKind = "drop";
  setChildren($("sheet"));
  $("sheet").hidden = false;
  paintDrop();
  for (const file of files) {
    try {
      const data = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
      });
      const written = await api("/api/drop", { method: "POST", body: { name: file.name, data, for: "project" } });
      if (state.fd && state.fd.name === name) state.fd.files.push({ path: written.path, name: written.name, size: written.size });
    } catch (e) {
      if (state.fd && state.fd.name === name) state.fd.refused.push({ name: file.name, why: e.message });
    }
    paintDrop();
  }
  if (state.fd && state.fd.name === name) { state.fd.writing = false; paintDrop(); }
}

function paintDrop() {
  const fd = state.fd;
  if (state.sheetKind !== "drop" || !fd) return;
  const view = dropSheetView(fd.files, { project: fd.name, running: fd.running || fd.writing, failure: fd.failure, done: fd.done,
    demo: state.demo, refused: fd.refused });
  if (!$("drop-sheet")) {  // built once, then painted in place, so a keyboard user's focus stays where it was
    setChildren($("sheet"), h("div", { class: "sheet np drop-sheet", id: "drop-sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "drop-title" },
      h("div", { class: "sheet-head" }, h("span", { class: "sheet-title", id: "drop-title" }),
        h("button", { class: "icon-btn", type: "button", "aria-label": "Close", onclick: closeSheet }, icon("x"))),
      h("p", { class: "panel-note", id: "drop-line" }),
      h("ul", { class: "git-names drop-list", id: "drop-list", "aria-label": "The files", hidden: true }),
      h("div", { class: "np-failure", id: "drop-refused", role: "alert", hidden: true }),
      h("div", { class: "np-failure", id: "drop-failure", role: "alert", hidden: true }),
      h("div", { class: "np-foot" }, h("span", { class: "np-foot-note", id: "drop-foot" }),
        h("button", { class: "btn", type: "button", id: "drop-cancel", onclick: closeSheet }, "Cancel"),
        h("button", { class: "btn btn-primary", type: "button", id: "drop-add", onclick: addToProject }, "Add"))));
    $("drop-add").focus();
  }
  $("drop-title").textContent = view.title;
  $("drop-line").textContent = view.line;
  const list = $("drop-list");
  list.hidden = !view.list.length;
  setChildren(list, view.list.map((f) => h("li", { title: f.title }, h("span", { class: "drop-name", text: middleTruncate(f.name, 64) }),
    h("span", { class: "muted", text: f.size }))));
  const add = $("drop-add");
  add.hidden = !!fd.done;
  add.setAttribute("aria-disabled", view.canAdd ? "false" : "true");
  add.classList.toggle("is-off", !view.canAdd);
  add.textContent = view.adding && !fd.writing ? "Adding…" : "Add";
  $("drop-cancel").textContent = fd.done ? "Close" : "Cancel";
  if (fd.done && document.activeElement === add) $("drop-cancel").focus();
  $("drop-foot").textContent = view.foot || (fd.writing ? "Reading the files…" : "");
  const refused = $("drop-refused");
  refused.hidden = !view.refused;
  setChildren(refused, view.refused ? [h("div", { class: "np-failure-title", text: view.refused.title }),
    h("ul", { class: "drop-refused" }, view.refused.lines.map((line) => h("li", { class: "np-failure-text", text: line })))] : []);
  paintFailure($("drop-failure"), view.failure);
}

async function addToProject() {
  const fd = state.fd;
  if (!fd || fd.running || fd.writing || fd.done || !fd.files.length || state.demo) return;
  fd.running = true;
  fd.failure = null;
  paintDrop();
  let result;
  try {
    result = await runProjectAction({ action: "project_files", name: fd.name, files: fd.files.map((f) => f.path) });
  } catch (e) {
    fd.running = false;
    fd.failure = { title: "Not run", message: e.message, exit: null, code: null };
    paintDrop();
    return;
  }
  fd.running = false;
  if (result.code === 0) {
    fd.done = `Added: ${fd.files.map((f) => f.name).join(", ")}, one commit.`;
    await loadStatus();
    paintDrop();
    renderStream({ follow: false });
    return;
  }
  fd.failure = failureOf(result);
  if (state.fd === fd) paintDrop(); else toast(result.message);
}

// ---------- needs you, the boards, the stop offers and the confirm (D) ----------

function needsBlock(task, show) {
  const sendAs = sendAsView(task, state.status);  // brief 29.1 (decision 3): Send as <skill> on a not_routed card
  if (sendAs) {
    return h("div", { class: "offer" },
      h("div", { class: "offer-head" }, icon("alert"), h("span", { class: "offer-title", text: sendAs.title })),
      h("div", { class: "skills", role: "group", "aria-label": "Send as" }, sendAs.skills.map((s) => h("button", {
        class: "btn skill", type: "button", title: `Send it again as ${s.key}`, disabled: busy(task),
        dataset: { focusKey: `send-as-${task.task_id}-${s.key}` }, onclick: () => act(task, s.request) }, s.key))),
      h("div", { class: "offer-row" }, h("span", { class: "offer-cmd", text: sendAs.sub })));
  }
  const floor = floorView(task, state.status);
  if (floor) {
    return h("div", { class: "offer warn" },
      h("div", { class: "offer-head" }, icon("alert"), h("span", { class: "offer-title", text: floor.title }),
        h("span", { class: "offer-side", text: floor.sub })),
      h("div", { class: "skills", role: "group", "aria-label": "Skills" }, floor.skills.map((s) => h("button", {
        class: `btn skill${s.guess ? " guess" : ""}`, type: "button", title: s.guess ? "Jev's guess" : s.key, disabled: busy(task),
        onclick: () => act(task, s.request) }, s.key))),
      h("div", { class: "offer-row" }, h("span", { class: "offer-cmd", text: "One click sends it again as a new task with that skill; this row keeps Jev's label." }),
        h("button", { class: "btn btn-quiet", type: "button", disabled: busy(task), dataset: { focusKey: `floor-cancel-${task.task_id}` },
          onclick: () => act(task, floor.cancel) }, "Cancel")));
  }
  const plan = splitPlanView(task, show, { editing: state.splitEdit, running: busy(task), presets: (state.status || {}).presets,
    choices: state.splitChoices.get(task.task_id) || {} });
  if (plan) return planCard(task, show, plan);  // brief 29 (decision 18a)
  const asked = questionsCardView(task, { ...(state.questionsUi.get(task.task_id) || {}), running: busy(task), demo: state.demo });
  if (asked) return questionsCard(task, asked);  // brief 33.4 (decision 14)
  const planned = planCardView(task, show, { editing: state.planEdit, running: busy(task) });
  if (planned) return planBoardCard(task, show, planned);  // brief 33.1 (decisions 10 and 11)
  const one = oneStepView(task);
  if (one) return oneStepCard(task, one);  // brief 33.1 (decision 6)
  const noSplit = noSplitView(task);
  if (noSplit) return noSplitCard(task, noSplit);  // brief 29 (decision 3)
  const pieces = piecesView(task, show);
  if (pieces) return piecesList(task, pieces);  // brief 29 (decision 18b)
  if (task.waiting_on === "memory") return h("div", { class: "quiet-line", text: "Memory is starting; this task goes on by itself once it's up." });
  if (task.waiting_on === "probe") return h("div", { class: "quiet-line", text: "A safety check this task needs is running; the task goes on by itself." });
  return null;
}

// ---------- the plan on the page (brief 33.1, decisions 6, 9 to 11 and 20) ----------

function planEditOffNow(task) {
  if (state.demo) return "Demo: nothing runs";
  if (busy(task)) return "A change to the plan is running";
  if (state.planEdit) return `Save or cancel step ${state.planEdit.k}'s edit first`;
  return null;
}

function planBoardCard(task, show, view) {
  const off = planEditOffNow(task);
  const quiet = (label, request, title, id) => h("button", { class: `btn btn-quiet btn-small${off || !request ? " is-off" : ""}`,
    type: "button", id, title: off || title, "aria-disabled": off || !request ? "true" : null,
    onclick: () => { if (!planEditOffNow(task) && request) runAction(task, request); } }, label);
  const steps = h("ol", { class: "pieces plan-pieces plan-steps" }, view.steps.map((step) => step.inherited
    ? h("li", { class: "piece plan-piece plan-step inherited" },  // brief 33.2 (decision 11): done, greyed, not editable
      h("span", { class: "k", text: String(step.k) }),
      h("div", { class: "piece-main" },
        h("div", { class: "piece-text-row" }, h("span", { class: "t", text: step.text }),
          step.doneTask ? h("button", { class: "linklike plan-done-by", type: "button", onclick: () => goToSource(step.doneTask) }, step.done)
            : h("span", { class: "plan-done-by", text: step.done })),
        h("div", { class: "piece-team" }, h("span", { class: "k", text: "team" }), h("span", { text: step.team || "-" })),
        step.covers == null || step.covers === "none" ? null : h("div", { class: "piece-why plan-covers" }, h("span", { class: "k", text: "covers" }), h("span", { class: "t", text: step.covers }))))
    : !planStepOpen(task, step) ? planReadStep(task, step, off)  // UI-1 row 12 (D16): read first; Edit opens today's controls
    : h("li", { class: "piece plan-piece plan-step plan-open" },
    h("span", { class: "k", text: String(step.k) }),
    h("div", { class: "piece-main" },
      step.edit && step.edit.field === "text" ? planEditField(task, step) : h("div", { class: "piece-text-row" },
        h("span", { class: "t", text: step.text }),
        h("button", { class: `btn btn-quiet btn-small${off ? " is-off" : ""}`, type: "button", id: `plan-edit-${task.task_id}-${step.k}`,
          "aria-disabled": off ? "true" : null, title: off || `Change step ${step.k}'s text`,
          onclick: () => { if (!planEditOffNow(task)) openPlanEdit(task, step, "text"); } }, "Edit")),
      h("div", { class: "piece-team" },
        h("label", { class: "team-pick" }, h("span", { class: "k", text: "team" }),
          h("select", { class: `select${off ? " is-off" : ""}`, id: `plan-team-${task.task_id}-${step.k}`,
            "aria-label": `Step ${step.k}'s team`, "aria-disabled": off ? "true" : null, title: off,
            onchange: (e) => {
              const now = planEditOffNow(task);
              if (now) { e.target.value = step.team; toast(now); return; }
              runAction(task, planEditRequest(task, step.k, "team", e.target.value));
            } },
          step.options.map((o) => h("option", { value: o.name, selected: o.name === step.team, disabled: o.disabled,
            title: o.why || null, text: o.disabled && o.why ? `${o.name} (can't run now)` : o.name })))),
        step.calls ? h("span", { class: "mark plan-calls", text: step.calls }) : null,
        h("span", { class: "plan-moves" }, quiet("↑", step.up, `Move step ${step.k} up`, `plan-up-${task.task_id}-${step.k}`),
          quiet("↓", step.down, `Move step ${step.k} down`, `plan-down-${task.task_id}-${step.k}`),
          quiet("Drop", step.drop, step.drop ? `Drop step ${step.k}` : "A plan keeps at least one step", `plan-drop-${task.task_id}-${step.k}`))),
      step.why ? h("div", { class: "piece-why" }, h("span", { class: "k", text: "why" }), h("span", { text: step.why })) : null,
      step.edit && step.edit.field === "done_when" ? planEditField(task, step) : h("div", { class: "piece-why plan-done" },
        h("span", { class: "k", text: "done when" }), h("span", { class: "t", text: step.doneWhen }),
        h("button", { class: `btn btn-quiet btn-small${off ? " is-off" : ""}`, type: "button", id: `plan-done-${task.task_id}-${step.k}`,
          "aria-disabled": off ? "true" : null, title: off || `Change step ${step.k}'s finish line`,
          onclick: () => { if (!planEditOffNow(task)) openPlanEdit(task, step, "done_when"); } }, "Edit")),
      step.covers == null ? null : step.edit && step.edit.field === "covers" ? planEditField(task, step)  // brief 33.2 (decision 6)
        : h("div", { class: "piece-why plan-covers" },
          h("span", { class: "k", text: "covers" }), h("span", { class: "t", text: step.covers }),
          h("button", { class: `btn btn-quiet btn-small${off ? " is-off" : ""}`, type: "button", id: `plan-covers-${task.task_id}-${step.k}`,
            "aria-disabled": off ? "true" : null, title: off || `Change the SPEC.md examples step ${step.k} covers`,
            onclick: () => { if (!planEditOffNow(task)) openPlanEdit(task, step, "covers"); } }, "Edit"))))));
  const needs = view.needs.length ? h("div", { class: "plan-needs" }, h("div", { class: "k", text: "Needs from you" }),
    h("ul", {}, view.needs.map((need) => h("li", { class: `plan-need ${need.kind}` },
      h("span", { class: "t", text: need.words }),
      need.state ? h("span", { class: `need-state ${need.state === "set" ? "ok" : "bad"}`, text: need.state }) : null,
      need.kind === "key" ? h("button", { class: "btn btn-quiet btn-small secrets-btn", type: "button", disabled: state.restarted,
        title: `Open Secrets for ${task.project}, at ${need.name}`, onclick: () => openSecrets(task.project, need.name) },
      secretsLabel(need.name)) : null,
      need.kind === "test_command" && need.state !== "set" ? h("button", { class: "btn btn-quiet btn-small", type: "button",
        disabled: state.restarted || state.demo, onclick: () => setTestCommand(task.project, need.proposed) }, "Set") : null))))
    : h("div", { class: "plan-needs" }, h("span", { class: "k", text: "Needs from you" }), h("span", { class: "t", text: "none" }));
  return h("div", { class: "offer info plan-card plan-board", id: `plan-${task.task_id}` },
    h("div", { class: "offer-head" }, icon("alert"), h("span", { class: "offer-title", text: view.title }),
      h("span", { class: "offer-side", text: view.sub })),
    steps, needs,
    view.coverage ? h("div", { class: "offer-body coverage-line", text: view.coverage }) : null,  // brief 33.2 (decision 6)
    view.specChanged ? h("div", { class: "offer-body spec-changed-line", text: view.specChanged }) : null,  // decision 7.1
    view.changed ? h("details", { class: "plan-changed" }, h("summary", { text: "Changed" }),  // decision 11: `## Changed`, folded
      view.changed.length ? h("ul", {}, view.changed.map((line) => h("li", { text: line }))) : h("div", { class: "muted", text: "none" })) : null,
    view.count ? h("div", { class: "offer-body count-line" }, h("span", { text: view.count })) : null,
    h("div", { class: "offer-row" },
      view.approve ? h("button", { class: buttonClass("", holdsMain(task, "plan")), type: "button", id: `approve-${task.task_id}`, disabled: busy(task) || !!view.off,
        title: view.off, onclick: () => act(task, view.approve) }, "Approve plan") : null,
      view.approveAnyway ? h("button", { class: "btn", type: "button", id: `approve-anyway-${task.task_id}`, disabled: busy(task) || !!view.off,
        title: view.off, onclick: () => act(task, view.approveAnyway) }, "Approve anyway") : null,
      h("button", { class: "btn", type: "button", id: `reject-${task.task_id}`, disabled: busy(task) || !!view.off,
        title: view.off, onclick: () => act(task, view.reject) }, "Reject"),
      h("span", { class: "offer-cmd", text: view.off || planNoteWords(task) })));  // UI-1 row 12 (D16): from the server's fields
}

function planStepOpen(task, step) {
  // UI-1 row 12 (D16): one step open at a time (Edit), and the step a field edit is on
  const edit = state.planEdit;
  return state.planOpen === `${task.task_id}:${step.k}` || !!(edit && edit.taskId === task.task_id && edit.k === step.k);
}

function planReadStep(task, step, off) {
  const lines = planStepLines(step);
  const key = `${task.task_id}:${step.k}`;
  return h("li", { class: "piece plan-piece plan-step plan-read" },
    h("span", { class: "k", text: `${step.k}.` }),
    h("div", { class: "piece-main" },
      h("div", { class: "plan-line" }, h("span", { class: "t", text: step.text }),
        lines.one ? h("span", { class: "plan-quiet", text: ` · ${lines.one}` }) : null),
      lines.two ? h("div", { class: "plan-quiet", text: lines.two }) : null),
    h("button", { class: "btn btn-quiet btn-small", type: "button", dataset: { focusKey: `plan-open-${key}` },
      title: off || `Edit step ${step.k}: its text, team, finish line and place`,
      onclick: () => { state.planOpen = key; renderStream({ follow: false }); focusId(`plan-edit-${task.task_id}-${step.k}`); } }, "Edit"));
}

function planEditField(task, step) {
  const id = `plan-edit-text-${task.task_id}-${step.k}`;
  const field = step.edit.field;
  const max = field === "done_when" ? DONE_MAX : field === "covers" ? COVERS_MAX : STEP_MAX;
  const before = field === "done_when" ? step.doneWhen : field === "covers" ? step.covers : step.text;
  const back = () => focusId(field === "done_when" ? `plan-done-${task.task_id}-${step.k}` : field === "covers"
    ? `plan-covers-${task.task_id}-${step.k}` : `plan-edit-${task.task_id}-${step.k}`);
  const save = () => {
    const edit = state.planEdit;  // D2 (the live check, 30 Oct): the text as it is now, never the box's first state
    if (!edit || edit.text === before || edit.text.length > max || !edit.text.trim()) return;
    state.planEdit = null;
    state.planEditSaved = { ...edit };  // E1 (2.47): a refused edit opens again with what was typed
    runAction(task, planEditRequest(task, step.k, field, edit.text));
    back();
  };
  const cancel = () => { state.planEdit = null; renderStream({ follow: false }); back(); };
  const box = h("textarea", { class: "edit-text", id, rows: 2, "aria-label": field === "done_when" ? `Step ${step.k}'s new finish line`
    : field === "covers" ? `The SPEC.md examples step ${step.k} covers` : `Step ${step.k}'s new text`, text: step.edit.text,
    oninput: (e) => {
      state.planEdit = { ...state.planEdit, text: e.target.value, refused: null };
      const refused = $(`plan-edit-refused-${task.task_id}-${step.k}`);
      if (refused) refused.remove();  // the refusal was about the text before this change
      growEdit(e.target);
      paintPlanEdit(task, step.k);
    },
    onkeydown: (e) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cancel(); }
      else if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !e.isComposing) { e.preventDefault(); save(); }
    } });
  const edit = state.planEdit || {};
  requestAnimationFrame(() => {
    if (!box.isConnected) return;
    growEdit(box);
    if (edit.focus) { state.planEdit.focus = false; box.focus(); }  // a refused edit, reopened where the keyboard was
  });
  return h("div", { class: "edit-field" }, box,
    edit.refused ? h("div", { class: "piece-refused", role: "alert", id: `plan-edit-refused-${task.task_id}-${step.k}`, text: edit.refused })
      : null,
    h("div", { class: "edit-foot" },
      h("span", { class: `edit-count${step.edit.tooLong ? " bad" : ""}`, id: `plan-edit-count-${task.task_id}-${step.k}`,
        text: step.edit.count }),
      h("button", { class: "btn btn-quiet", type: "button", onclick: cancel }, "Cancel"),
      h("button", { class: "btn btn-primary", type: "button", id: `plan-edit-save-${task.task_id}-${step.k}`,
        disabled: step.edit.tooLong || step.edit.unchanged || !step.edit.text.trim(), onclick: save }, "Save")));
}

function paintPlanEdit(task, k) {
  // D2: the counter and Save as the text changes, without drawing the stream again under the caret (the split's paintEdit)
  const view = planCardView(task, state.shows.get(task.task_id), { editing: state.planEdit, running: busy(task) });
  const step = view && view.steps.find((s) => s.k === k);
  if (!step || !step.edit) return;
  const count = $(`plan-edit-count-${task.task_id}-${k}`);
  if (count) { count.textContent = step.edit.count; count.classList.toggle("bad", step.edit.tooLong); }
  const save = $(`plan-edit-save-${task.task_id}-${k}`);
  if (save) save.disabled = step.edit.tooLong || step.edit.unchanged || !step.edit.text.trim();
}

function openPlanEdit(task, step, field) {
  state.planEdit = { taskId: task.task_id, k: step.k, field, text: field === "done_when" ? step.doneWhen : field === "covers" ? step.covers : step.text };  // 33.2
  renderStream({ follow: false });
  const box = document.getElementById(`plan-edit-text-${task.task_id}-${step.k}`);
  if (box) { growEdit(box); box.focus(); box.setSelectionRange(box.value.length, box.value.length); }
}

function questionsCard(task, view) {
  // brief 33.4 (decision 14): the plan task's one card while it waits on answers; nothing here changes a file, so no confirm
  if (view.planning) return h("div", { class: "quiet-line questions-planning", text: view.line });
  const ui = () => {
    if (!state.questionsUi.has(task.task_id)) state.questionsUi.set(task.task_id, { picks: {}, others: {} });
    return state.questionsUi.get(task.task_id);
  };
  const pick = (q, letter) => {
    const now = ui();
    now.picks = { ...now.picks, [q.k]: now.picks[q.k] === letter ? null : letter };
    now.others = { ...now.others, [q.k]: "" };
    now.open = { ...now.open, [q.k]: false };
    renderStream({ follow: false });
  };
  const openOther = (q) => {  // UI-1m (D25): the box opens in place; typing in it is what replaces a pick
    const now = ui();
    now.open = { ...now.open, [q.k]: true };
    renderStream({ follow: false });
    focusId(q.otherId);
  };
  const type = (q, value) => {  // typing replaces the pick; the box keeps its focus, so only the chips and Send repaint
    if (!value) { closeOtherBox(task.task_id, q.k); return; }  // UI-1m (D25): clearing the box closes it
    const now = ui();
    now.others = { ...now.others, [q.k]: value };
    if (value.trim()) now.picks = { ...now.picks, [q.k]: null };
    const fresh = questionsCardView(task, { ...now, demo: state.demo });
    const freshMain = mainNow();
    for (const row of fresh.questions) {
      for (const o of row.options) {
        const chip = $(`question-${task.task_id}-${row.k}-${o.letter}`);
        if (chip) { chip.classList.toggle("picked", o.picked); chip.setAttribute("aria-pressed", o.picked ? "true" : "false"); }
      }
    }
    const send = $(`send-answers-${task.task_id}`);
    if (send) { send.disabled = !freshMain.request; send.title = freshMain.off || ""; }
  };
  const mainNow = () => cardMainAction(task, null, [], { questions: { ...ui(), demo: state.demo } });  // UI-1m (2.6)
  const send = () => {
    const now = mainNow();
    if (!now || !now.request) return;
    state.questionsUi.delete(task.task_id);
    runAction(task, now.request);
  };
  const main = mainNow();
  // UI-1m (D25): the frame and title line of the read-first plan card (D16), one primary button in its foot
  return h("div", { class: "offer info plan-card plan-board questions-card", id: `questions-${task.task_id}` },
    h("div", { class: "offer-head" }, icon("alert"), h("span", { class: "offer-title", text: view.title }), h("span", { class: "offer-side", text: view.sub })),
    view.questions.map((q) => h("div", { class: "question" },
      h("div", { class: "question-text", text: `${q.k}. ${q.text}` }),
      h("div", { class: "skills", role: "group", "aria-label": `Question ${q.k}'s options` }, q.options.map((o) => h("button", {
        class: `btn skill question-option${o.picked ? " picked" : ""}`, type: "button", id: `question-${task.task_id}-${q.k}-${o.letter}`,
        "aria-pressed": o.picked ? "true" : "false", disabled: state.demo, onclick: () => pick(q, o.letter) },
        `${o.letter}. ${o.text}`, o.guess ? h("span", { class: "question-guess", text: " · guess" }) : null)),
      h("button", { class: `btn skill question-option question-other-chip${q.typed ? " picked" : ""}`, type: "button", id: q.otherChipId,
        "aria-expanded": q.open ? "true" : "false", disabled: state.demo, onclick: () => openOther(q) }, "Other…")),
      q.open ? h("input", { class: "question-other", id: q.otherId, type: "text", placeholder: "Your own answer", value: q.other,
        "aria-label": `Question ${q.k}: your own answer`, autocomplete: "off", disabled: state.demo, oninput: (e) => type(q, e.target.value),
        onkeydown: (e) => { if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); } } }) : null)),  // D25: Enter here never sends
    h("div", { class: "offer-row" },
      h("button", { class: "btn btn-primary", type: "button", id: `send-answers-${task.task_id}`, disabled: !main.request, title: main.off, onclick: send }, main.label),
      h("button", { class: "btn btn-quiet", type: "button", id: `best-guess-${task.task_id}`, disabled: !view.bestGuess,
        title: "Answer every question with the planner's guess", onclick: () => { state.questionsUi.delete(task.task_id); runAction(task, view.bestGuess); } }, "Use your best guess"),
      h("button", { class: "btn btn-quiet", type: "button", id: `questions-cancel-${task.task_id}`, disabled: !view.cancel,
        title: "End this plan and remove its copy", onclick: () => act(task, view.cancel) }, "Cancel")));
}

function closeOtherBox(taskId, k) {
  // UI-1m (D25): Esc or a cleared box: closed, the question unanswered, the focus back on its Other… chip
  state.questionsUi.set(taskId, closeOther(state.questionsUi.get(taskId) || { picks: {}, others: {} }, k));
  renderStream({ follow: false });
  focusId(`question-other-chip-${taskId}-${k}`);
}

function openOtherBox() {
  // UI-1m (D25): the open box Esc goes to: the one with the focus, else the first still on the page
  const active = document.activeElement;
  let first = null;
  for (const [taskId, ui] of state.questionsUi) {
    for (const [k, open] of Object.entries(ui.open || {})) {
      if (!open) continue;
      const box = $(`question-other-${taskId}-${k}`);
      if (box && box === active) return { taskId, k };
      if (box && !first) first = { taskId, k };
    }
  }
  return first;
}

function oneStepCard(task, view) {
  return h("div", { class: "offer muted one-step-card", id: `one-step-${task.task_id}` },
    h("div", { class: "offer-head" }, h("span", { class: "offer-title", text: view.title }),
      h("span", { class: "offer-side", text: view.sub })),
    h("div", { class: "offer-body", text: view.line }),
    h("div", { class: "offer-body one-step-task" }, h("span", { class: "k", text: `${teamLabel(view.team)} · ` }), h("span", { text: view.task })),
    view.chip ? h("div", { class: "offer-row" }, h("button", { class: buttonClass("", holdsMain(task, "one_step")), type: "button", id: `build-it-${task.task_id}`,
      title: "Fill the box with this task, its team and the project; nothing is sent", onclick: () => useChip(view.chip, task) }, "Build it"))
      : null);
}

function setTestCommand(name, words) {
  // decision 16: Set fills the proposed words and asks once, naming them; Cancel sends nothing
  if (!name || !words) return;
  if (!window.confirm(testsConfirmWords(name, words))) return;
  runProjectAction({ action: "project_tests", name, words });
}

function openPlanFile(name) {
  // decision 20: docs/PLAN.md, read only, in the side panel (it joins the files the server may open, as HANDOFF.md is)
  const opened = openDoc("docs/PLAN.md", `${name} · the router writes it · read only`, `/api/plan/${encodeURIComponent(name)}`);
  if (state.panel && state.panel.kind === "doc") {  // brief 34 (decision 13): the steps' Stop here toggles above the text
    state.panel.project = name;
    renderPanel();
  }
  return opened;
}

function stopHereList(panel) {
  // brief 34 (decision 13): the current plan's steps, each with a 44 px Stop here switch (never greyed: aria-busy while
  // its run goes), from the project's plan entry as status gives it now
  const project = projectOf(panel.project);
  const rows = stopHereRows(project && project.plan, state.markRuns);
  if (!rows.length) return null;
  return h("div", { class: "stop-here-list", role: "group", "aria-label": "Stop here, per step" },
    h("div", { class: "stop-here-head" }, h("span", { text: "Auto stops before a marked step. The mark is kept in the log; nothing is committed." }),
      h("button", { class: "btn btn-quiet", type: "button", id: "plan-again", title: "Fills the box with Plan on this project: the done steps stay, the open ones may change",
        onclick: () => { closePanel(); if (state.project !== panel.project) openProject(panel.project); setBox(planAgainFill(panel.project)); } },
      "Plan again")),  // brief 33.2 (decision 11): the plan's one home
    rows.map((r) => h("div", { class: `stop-here-row${r.done ? " done" : ""}` },
      h("span", { class: "stop-here-step", text: `Step ${r.k}` }),
      h("span", { class: "stop-here-text", text: r.text, title: r.text }),
      r.team ? h("span", { class: "stop-here-team", text: r.team }) : null,
      h("button", { class: `mem-switch stop-here-switch${r.on ? " on" : ""}${r.busy ? " busy" : ""}`, type: "button", role: "switch",
        "aria-checked": r.on ? "true" : "false", "aria-label": `Stop here before step ${r.k}`, "aria-busy": r.busy ? "true" : null,
        "aria-disabled": r.busy ? "true" : null, title: `Runs sr plan --stop-here ${r.step} ${r.to}`,
        onclick: () => flipStopHere(panel.project, r) },
      h("span", { class: "mem-switch-label", text: "Stop here" }),
      h("span", { class: "mem-switch-track", "aria-hidden": "true" }, h("span", { class: "mem-switch-knob" }))))));
}

// ---------- split on the page (brief 29, decisions 3, 8 and 18) ----------

function planEditOff(task) {
  // why Edit and the team selects are off now, or null. C4 (/break-ui), keyboard only: they turn aria-disabled, never
  // disabled, so a run they start keeps the focus where it was (a disabled control drops it to the page)
  if (state.demo) return "Demo: nothing runs";
  if (busy(task)) return "A change to the plan is running";
  if (state.splitEdit) return `Save or cancel piece ${state.splitEdit.piece}'s edit first`;
  return null;
}

function pieceOpen(task, piece) {
  // UI A row 16 (A18): one piece open at a time (Edit), and the piece a text edit is on
  return state.pieceOpen === `${task.task_id}:${piece.piece}` || !!piece.edit;
}

function planCard(task, show, plan) {
  const editOff = planEditOff(task);
  const choices = state.splitChoices.get(task.task_id) || {};
  const approve = splitApprove(task, show, choices);
  const skills = ((state.status && state.status.skills) || []).map((s) => s.key);
  const skillSelect = (piece) => (piece.needsLabel ? h("select", { class: "select", id: `skill-${task.task_id}-${piece.piece}`,  // C4: an id keeps focus on a redraw
    "aria-label": `Piece ${piece.piece}'s skill`, onchange: (e) => {
      state.splitChoices.set(task.task_id, { ...(state.splitChoices.get(task.task_id) || {}), [piece.piece]: e.target.value || undefined });
      renderStream({ follow: false });
    } }, h("option", { value: "", text: "Pick its skill…" }), skills.map((k) => h("option", { value: k, selected: choices[piece.piece] === k, text: k }))) : null);
  const refusal = (piece) => (piece.refused ? h("div", { class: "piece-refused", role: "note", text: `Can't run: ${piece.refused}` }) : null);
  const readPiece = (piece) => {  // read first: one line, then the why and where it goes, quiet; what Approve needs always shows
    const key = `${task.task_id}:${piece.piece}`;
    const held = state.splitEdit ? `Save or cancel piece ${state.splitEdit.piece}'s edit first` : null;
    return h("li", { class: `piece plan-piece plan-read${piece.refused ? " refused" : ""}` },
      h("span", { class: "k", text: `${piece.piece}.` }),
      h("div", { class: "piece-main" },
        h("div", { class: "plan-line" }, h("span", { class: "t", text: piece.text }),
          h("span", { class: "plan-quiet", text: ` · ${pieceReadLine(piece)}` })),
        piece.changedFrom ? h("div", { class: "plan-quiet", text: `you changed it from ${piece.changedFrom}` }) : null,
        piece.why ? h("div", { class: "plan-quiet", text: `Why: ${piece.why}` }) : null,
        h("div", { class: "plan-quiet", text: piece.words }),
        skillSelect(piece), refusal(piece)),
      h("button", { class: `btn btn-quiet btn-small${held ? " is-off" : ""}`, type: "button", dataset: { focusKey: `piece-open-${key}` },
        "aria-disabled": held ? "true" : null, title: held || `Edit piece ${piece.piece}: its text, team and slots`,
        onclick: () => { if (state.splitEdit) return; state.pieceOpen = key; renderStream({ follow: false }); focusId(`edit-${task.task_id}-${piece.piece}`); } }, "Edit"));
  };
  return h("div", { class: "offer info plan-card", id: `plan-${task.task_id}` },
    h("div", { class: "offer-head" }, icon("alert"), h("span", { class: "offer-title", text: plan.title }),
      h("span", { class: "offer-side", text: plan.sub })),
    h("ol", { class: "pieces plan-pieces" }, plan.pieces.map((piece) => (!pieceOpen(task, piece) ? readPiece(piece) : h("li", { class: `piece plan-piece plan-open${piece.refused ? " refused" : ""}` },
      h("span", { class: "k", text: String(piece.piece) }),
      h("div", { class: "piece-main" },
        piece.edit ? editField(task, piece) : h("div", { class: "piece-text-row" },
          h("span", { class: "t", text: piece.text }),
          h("button", { class: `btn btn-quiet btn-small${editOff ? " is-off" : ""}`, type: "button", id: `edit-${task.task_id}-${piece.piece}`,
            "aria-disabled": editOff ? "true" : null, title: editOff || `Change piece ${piece.piece}'s text`,
            onclick: () => { if (!planEditOff(task)) openEdit(task, piece); } }, "Edit")),
        h("div", { class: "piece-team" },
          h("label", { class: "team-pick" }, h("span", { class: "k", text: "team" }),
            h("select", { class: `select${editOff ? " is-off" : ""}`, id: `team-${task.task_id}-${piece.piece}`,
              "aria-label": `Piece ${piece.piece}'s team`, "aria-disabled": editOff ? "true" : null, title: editOff,
              onchange: (e) => {
                const off = planEditOff(task);
                if (off) { e.target.value = piece.team; toast(off); return; }  // C4: off, but it keeps the keyboard's focus
                runAction(task, splitEditRequest(task, piece.piece, { team: e.target.value }));
              } },
            piece.options.map((o) => h("option", { value: o.name, selected: o.name === piece.team, disabled: o.disabled,
              title: o.why || null, text: o.disabled && o.why ? `${o.name} (can't run now)` : o.name })))),
          piece.mark ? h("span", { class: "mark", text: piece.mark }) : null,
          piece.changedFrom ? h("span", { class: "changed", text: `you changed it from ${piece.changedFrom}` }) : null),
        piece.slots.length ? h("div", { class: "piece-slots" }, piece.slots.map((slot) => h("label", { class: "team-pick" },
          h("span", { class: "k", text: `slot ${slot.name}` }),  // brief 29.1 (decision 12): one select per slot, run at once
          h("select", { class: `select${editOff ? " is-off" : ""}`, id: `slot-${task.task_id}-${piece.piece}-${slot.name}`,
            "aria-label": `Piece ${piece.piece}'s slot ${slot.name}`, "aria-disabled": editOff ? "true" : null, title: editOff,
            onchange: (e) => {
              const off = planEditOff(task);
              if (off) { e.target.value = slot.agent; toast(off); return; }
              runAction(task, slot.request(e.target.value));
            } },
          slot.options.map((o) => h("option", { value: o.agent, selected: o.agent === slot.agent, text: o.label })))))) : null,
        piece.why ? h("div", { class: "piece-why" }, h("span", { class: "k", text: "why" }), h("span", { text: piece.why })) : null,
        h("div", { class: "piece-where" }, h("span", { class: "where", text: piece.words }),
          piece.jev ? h("span", { class: "piece-jev", text: piece.jev }) : null),
        skillSelect(piece), refusal(piece)))))),
    plan.join ? h("div", { class: "offer-body", text: `${plan.joiner} joins them (“${plan.join}”); ${plan.checker ? `${plan.checker} checks the whole` : "unchecked"}.` }) : null,
    plan.project ? h("div", { class: "offer-body project-line", text: plan.project }) : null,
    plan.count ? h("div", { class: "offer-body count-line" }, h("span", { text: plan.count }), h("span", { class: "jev-line", text: plan.jevLine })) : null,
    h("div", { class: "offer-row" },
      h("button", { class: buttonClass("", holdsMain(task, "split")), type: "button", id: `approve-${task.task_id}`, disabled: busy(task) || !!plan.approveOff,
        title: plan.approveOff, onclick: () => act(task, approve.request) }, "Approve and run"),
      h("button", { class: "btn", type: "button", id: `reject-${task.task_id}`, disabled: busy(task) || !!plan.rejectOff,
        title: plan.rejectOff, onclick: () => act(task, plan.reject) }, "Reject"),
      plan.approveOff ? h("span", { class: "offer-cmd", text: plan.approveOff }) : null));
}

function editField(task, piece) {
  const id = `edit-text-${task.task_id}-${piece.piece}`;
  const save = () => {
    const edit = state.splitEdit;
    if (!edit || edit.text === piece.text || edit.text.length > PIECE_MAX || !edit.text.trim()) return;
    state.splitEdit = null;  // break-ui: a double click on Save starts one run; the field closes at once
    state.splitEditSaved = { ...edit };  // C4: a refused edit opens again with what was typed
    runAction(task, splitEditRequest(task, piece.piece, { text: edit.text }));
    focusId(`edit-${task.task_id}-${piece.piece}`);  // C4, keyboard only: back to the piece's Edit, not the page
  };
  const cancel = () => { state.splitEdit = null; renderStream({ follow: false }); focusId(`edit-${task.task_id}-${piece.piece}`); };
  // C4: the text goes in as the textarea's content; it ignores a value attribute, so the field opened empty
  const field = h("textarea", { class: "edit-text", id, rows: 3, "aria-label": `Piece ${piece.piece}'s new text`, text: piece.edit.text,
      oninput: (e) => {
        state.splitEdit = { ...state.splitEdit, text: e.target.value, refused: null };
        const refused = $(`edit-refused-${task.task_id}`);
        if (refused) refused.remove();  // the refusal was about the text before this change
        growEdit(e.target);
        paintEdit(task, piece.piece);
        refreshEditCommand(task, piece.piece);
      },
      onkeydown: (e) => {
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cancel(); }
        else if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !e.isComposing) { e.preventDefault(); save(); }
      } });
  const edit = state.splitEdit || {};
  requestAnimationFrame(() => {
    if (!field.isConnected) return;
    growEdit(field);  // drawn again by a poll: its height again
    if (edit.focus) { state.splitEdit.focus = false; field.focus(); }  // a refused edit, reopened where the keyboard was
  });
  return h("div", { class: "edit-field" }, field,
    edit.refused ? h("div", { class: "piece-refused", role: "alert", id: `edit-refused-${task.task_id}`, text: edit.refused }) : null,
    h("div", { class: "edit-foot" },
      h("span", { class: `edit-count${piece.edit.tooLong ? " bad" : ""}`, id: `edit-count-${task.task_id}`, text: piece.edit.count }),
      h("button", { class: "btn btn-quiet", type: "button", onclick: cancel }, "Cancel"),
      h("button", { class: "btn btn-primary", type: "button", id: `edit-save-${task.task_id}`,
        disabled: piece.edit.tooLong || piece.edit.unchanged || !piece.edit.text.trim(), onclick: save }, "Save")),
    // C4: the command on its own row (a 399-character text squeezed it into a column 14 lines tall), three lines at most,
    // the whole of it in its title
    h("span", { class: "edit-cmd mono", id: `edit-cmd-${task.task_id}`, text: state.splitEditCommand || "",
      title: state.splitEditCommand || null }));
}

function openEdit(task, piece) {
  state.splitEdit = { taskId: task.task_id, piece: piece.piece, text: piece.text };
  state.splitEditCommand = "";
  renderStream({ follow: false });
  const field = document.getElementById(`edit-text-${task.task_id}-${piece.piece}`);
  if (field) { growEdit(field); field.focus(); field.setSelectionRange(field.value.length, field.value.length); }
  refreshEditCommand(task, piece.piece);
}

function growEdit(field) {
  // C4: the field grows with its text, as the composer does (a 399-character text hid its last line); the CSSOM, which
  // the page's CSP allows, never a style attribute
  field.style.height = "auto";
  field.style.height = `${Math.min(field.scrollHeight + 2, window.innerHeight * 0.4)}px`;
}

function paintEdit(task, k) {
  // the counter and Save as the text changes, without drawing the stream again under the caret
  const show = state.shows.get(task.task_id);
  const view = splitPlanView(task, show, { editing: state.splitEdit, running: busy(task), presets: (state.status || {}).presets });
  const piece = view && view.pieces.find((p) => p.piece === k);
  if (!piece || !piece.edit) return;
  const count = $(`edit-count-${task.task_id}`);
  if (count) { count.textContent = piece.edit.count; count.classList.toggle("bad", piece.edit.tooLong); }
  const save = $(`edit-save-${task.task_id}`);
  if (save) save.disabled = piece.edit.tooLong || piece.edit.unchanged || !piece.edit.text.trim();
}

let editCommandTimer = null;
function refreshEditCommand(task, k) {
  // the command Save runs, shown as the composer shows its own: the server's builder, never the page's
  clearTimeout(editCommandTimer);
  editCommandTimer = setTimeout(async () => {
    const edit = state.splitEdit;
    if (!edit || edit.taskId !== task.task_id || edit.piece !== k) return;
    const request = splitEditRequest(task, k, { text: edit.text });
    const found = await commandText(request);
    if (state.splitEdit !== edit && !(state.splitEdit && state.splitEdit.text === edit.text)) return;
    state.splitEditCommand = found.refused ? `Refused: ${found.refused}` : `$ ${found.display}`;
    const node = $(`edit-cmd-${task.task_id}`);
    if (node) { node.textContent = state.splitEditCommand; node.title = state.splitEditCommand; }
  }, 200);
}

function piecesList(task, pieces) {
  return h("ol", { class: "pieces split-pieces", "aria-label": "Pieces" }, pieces.map((piece) => h("li", { class: `piece state-${piece.state || "none"}` },
    // UI A row 7 (A18): the mark with the words kept, the #task linked
    h("span", { class: "k" }, h("span", { class: `piece-mark ${piece.state || "none"}`, "aria-hidden": "true", text: pieceMark(piece.state) }), ` ${piece.piece}`,
      piece.n ? [" · ", h("button", { class: "linklike", type: "button", onclick: () => openPieceCard({ task_id: piece.task_id, n: piece.n }) }, `#${piece.n}`)] : null),
    h("div", { class: "piece-main" },
      h("span", { class: "t", text: piece.text }),
      h("div", { class: "piece-where" }, h("span", { class: "team-tag", text: piece.team }), h("span", { class: "r", text: piece.words })),
      piece.part.length ? h("div", { class: "piece-part" }, piece.part.map((words) => h("span", { class: "part-chip mono", text: words })),
        piece.more ? h("span", { class: "part-chip more", text: `+${count(piece.more)} more${piece.n ? ` on #${piece.n}` : ""}` }) : null) : null),
    h("div", { class: "piece-actions" },
      // C4, keyboard only: each with an id, so a poll's redraw keeps the focus on it (keepFocus finds controls by id)
      piece.open ? h("button", { class: "btn btn-quiet", type: "button", id: `open-${piece.task_id}`,
        onclick: () => openPieceCard(piece.open) }, `Open #${piece.open.n}`) : null,
      piece.skip ? h("button", { class: "btn", type: "button", id: `skip-${piece.task_id}`, disabled: busy(task),
        onclick: () => act(task, piece.skip) }, "Skip") : null))));
}

function openPieceCard(found) {
  // C4: the page's own way to a task's card (its view, then the card, focused); a piece shown in this view is scrolled to
  // at once, and one not loaded yet is found by the jump (Cleanup 2, row 2)
  const card = document.getElementById(`card-${found.task_id}`);
  if (card) {
    card.scrollIntoView({ block: "start" });
    card.focus({ preventScroll: true });
    state.heldCard = { id: found.task_id, until: Date.now() + HOLD_MS };  // brief 32.1: as a jump from Needs you
    return;
  }
  return jumpToTask(found.task_id, found.n);
}

function noSplitCard(task, view) {
  const skill = state.routeItSkills.get(task.task_id) || null;
  const found = routeItRequest(view, { chat: state.chat, quick: state.quick, newChat: newChatName() }, state.status, skill);
  const sending = state.routing.has(task.task_id);
  const made = routeItState(state.routedFrom.get(task.task_id), state.tasks);  // brief 29.1 (decision 7d)
  const off = state.demo ? "Demo: nothing runs" : state.restarted ? "The page restarted: reload it"
    : sending ? "Sending…" : made ? made.off : found.pick.needed && !found.pick.chosen ? found.pick.why : null;
  return h("div", { class: "offer muted no-split" },
    h("div", { class: "offer-head" }, h("span", { class: "offer-title", text: view.title }),
      h("span", { class: "offer-side", text: view.sub })),
    h("div", { class: "offer-body", text: view.line }),
    h("div", { class: "offer-row" },
      found.pick.needed ? h("select", { class: "select", id: `route-it-skill-${task.task_id}`, "aria-label": "Its skill (Jev isn't set up)",
        disabled: sending, onchange: (e) => {
          state.routeItSkills.set(task.task_id, e.target.value || null);
          renderStream({ follow: false });
        } }, h("option", { value: "", text: "Pick its skill…" }),
      found.pick.options.map((o) => h("option", { value: o.key, selected: o.key === skill, text: o.label }))) : null,
      h("button", { class: `btn${off ? " is-off" : ""}`, type: "button", id: `route-it-${task.task_id}`, "aria-disabled": off ? "true" : null,
        title: off || "Send the same text as a routed task, from this view, with its project", onclick: () => { if (!off) routeIt(task, view); } },
      sending ? "Sending…" : made ? made.label : "Route it")),
    made ? h("div", { class: "offer-row" }, h("span", { class: "quiet-line", text: made.line }),
      made.taskId ? h("button", { class: "btn btn-quiet btn-small", type: "button", id: `routed-${task.task_id}`,
        onclick: () => goToTask(made.taskId) }, "Open it") : null) : null);
}

async function routeIt(task, view) {
  // decision 3: no confirm; one send per card at a time (a double click sends once); the composer is never touched
  if (state.routing.has(task.task_id) || state.routedFrom.has(task.task_id)) return;  // brief 29.1 (7d): once
  const skill = state.routeItSkills.get(task.task_id) || null;
  const found = routeItRequest(view, { chat: state.chat, quick: state.quick, newChat: newChatName() }, state.status, skill);
  if (found.pick.needed && !found.pick.chosen) { toast(found.pick.why); return; }
  state.routing.add(task.task_id);
  renderStream({ follow: false });
  try {
    const started = await api("/api/run", { method: "POST", body: found.request });
    state.routedFrom.set(task.task_id, { run_id: started.run_id, task_id: null });
    state.pending.push({ run_id: started.run_id, pid: started.pid, text: view.text, team: "route", display: started.copy || started.display,
      from: task.task_id });
  } catch (e) {
    state.refused.push({ id: `local-${Date.now()}`, display: "", envelope: { message: e.message }, exit: null });
  } finally {
    state.routing.delete(task.task_id);
  }
  renderStream({ follow: false });
  focusId(`route-it-${task.task_id}`);  // the keyboard stays on the card it acted from
  schedulePoll(800);
}

function fold(task, name, props, ...children) {
  // a card's fold, drawn open or shut as the owner left it (break-ui: it shut itself at the next poll)
  return h("details", { ...props, open: foldOpen(state.folds, task.task_id, name) || null,
    ontoggle: (e) => { state.folds = foldToggled(state.folds, task.task_id, name, e.target.open); } }, ...children);
}

function reviewEl(task, review, letter) {
  if (!review) return null;
  return fold(task, `review-${letter}`, { class: `review ${review.verdict === "pass" ? "pass" : review.verdict === "fail" ? "fail" : ""}` },
    h("summary", { text: `${review.reviewer}'s review: ${review.verdict}` }), h("div", { class: "review-notes", text: review.notes || "No notes." }));
}

function autoBoardEl(task, show) {
  // brief 34 (decision 12): the run's card is the recap, with the plan's marks from the project's entry. UI-1 row 13 (D4,
  // D5): one line per step (mark · number · task · team · state · check · #task · calls, all in words), one summary line,
  // then Land the run as the main action with Discard beside it, on today's handlers
  const project = task.project ? projectOf(task.project) : null;
  const board = autoBoard(task, show, project && project.plan ? project.plan.stop_here || [] : []);
  if (!board) return null;
  const runPlan = task.auto && task.auto.plan ? task.auto.plan.task_id : null;
  const planSteps = project && project.plan && runPlan && project.plan.task_id === runPlan ? project.plan.steps || [] : [];
  const lines = ((task.auto && task.auto.steps) || []).map((raw, i) => {
    const s = board.steps[i];
    const line = autoStepLine(raw, planSteps);
    return h("li", { class: `auto-line ${line.state}${line.covered ? "" : " muted"}` },
      h("span", { class: "auto-k", text: `${line.k}.` }),
      h("span", { class: "auto-text", text: line.text }),
      h("span", { class: "auto-meta" },
        s.mark ? h("span", { class: "auto-mark", text: "stop here" }) : null,
        line.team ? h("span", { class: "auto-team", text: line.team }) : null,
        h("span", { class: `auto-state ${line.state}`, text: line.words }),
        line.attempt ? h("span", { class: "muted", text: line.attempt }) : null,
        line.taskId ? h("button", { class: "linklike", type: "button", onclick: () => goToSource(line.taskId, line.n) }, `#${line.n}`) : null,
        h("span", { class: "auto-calls", text: line.calls })));
  });
  return h("div", { class: "auto-wrap" },
    h("div", { class: "auto-title", text: `The run · ${board.plan || "its plan"}` }),
    h("ol", { class: "auto-list" }, lines),
    h("div", { class: "auto-sum" }, h("span", { text: board.calls }),
      board.open.length ? h("span", { text: `open: ${board.open.map((k) => `step ${k}`).join(", ")}` }) : h("span", { text: "every step passed" }),
      board.why ? h("span", { class: "auto-why", text: `stopped: ${board.why}` }) : null,
      board.ways ? h("span", { class: "auto-ways", text: board.ways }) : null,  // brief 33.2 (decision 7.2)
      board.tests ? h("span", { class: "auto-tests", text: board.tests }) : null),  // brief 33.2 (decision 16)
    board.buttons.length ? h("div", { class: "offer-row" }, board.buttons.map((b) => h("button", {
      class: buttonClass(b.tone, holdsMain(task, "auto", b.key)), type: "button",
      id: `act-${task.task_id}-${b.key}`, disabled: busy(task), onclick: () => act(task, b.request) }, b.label))) : null);
}

function boardBlock(task, show) {
  const autoEl = autoBoardEl(task, show);
  if (autoEl) return autoEl;
  const versus = versusBoard(task, show);
  if (versus) {
    const grid = h("div", { class: "board" }, versus.cards.map((c) => h("div", { class: `cand${c.picked ? " won" : ""}` },
      h("div", { class: "cand-head" }, h("span", { class: "cand-who", text: `${c.letter.toUpperCase()} · ${c.builder}` }),  // UI A row 8 (A16)
        c.picked ? h("span", { class: "cand-sub", text: "picked" }) : null),
      h("div", { class: "cand-body result" }, renderMarkdown(c.text)),
      c.handoff ? handoffFold(task, `handoff-${c.letter}`, c.handoff) : null,
      c.missing ? h("div", { class: "missing", text: `Missing: ${c.missing}` }) : null,
      c.files ? candidateFilesEl(c.files) : null,  // brief 29.1 (decision 28)
      reviewEl(task, c.review, c.letter),
      versus.choices.filter((choice) => choice.choice === c.letter).map((choice) => pickButton(task, choice, holdsMain(task, "versus"))))));  // each Pick under its answer
    if (!versus.picking) return fold(task, "board", { class: "fold" }, h("summary", { text: "Both candidates and their reviews" }), grid);
    return h("div", { class: "board-wrap" }, grid, h("div", { class: "offer-row" }, versus.choices.filter((c) => c.choice === "none").map((c) => pickButton(task, c, false))));
  }
  const vote = voteBoard(task, show);
  if (vote) {
    const won = vote.votes.filter((v) => v.side !== "alone").length;
    // UI A row 6 (A16): the head as Versus's; why stays, confidence goes; a tie's tally on each answer, its amber line, no bar
    return h("div", { class: "board-wrap" },
      h("div", { class: "board three" }, vote.votes.map((v) => h("div", { class: `cand vote-card${v.side === "winner" || v.picked ? " won" : ""}${v.side === "alone" ? " dissent" : ""}` },
        h("div", { class: "cand-head" }, h("span", { class: "cand-who", text: `${v.letter.toUpperCase()} · ${v.agent}` }),
          vote.tie ? h("span", { class: "cand-sub", text: "tally: 1" }) : null),
        h("div", { class: "vote-answer", text: v.answer }), v.why ? h("div", { class: "review-notes", text: v.why }) : null,
        v.picked ? h("span", { class: "cand-sub", text: "your pick" }) : null))),
      vote.tie ? h("div", { class: "quiet-line warn vote-tie", text: "Three answers, one each: a tie. Pick one, or Neither." })
        : h("div", { class: "tally" }, h("div", { class: "offer-head" }, h("span", { class: "offer-title", text: `Tally: ${vote.tally}` })),
          h("div", { class: "tally-bar", "aria-hidden": "true" }, vote.votes.map((v, i) => h("span", { class: i < won ? "won" : "" })))),
      vote.choices.length ? h("div", { class: "offer-row" }, vote.choices.map((c) => pickButton(task, c, false)),
      h("span", { class: "offer-cmd", text: "a tie is never broken by a model: your pick is delivered unchecked" })) : null);
  }
  const red = redteamBoard(task, show);
  if (!red) return null;
  const tables = red.groups ? [red.groups.map((g) => h("table", { class: "redteam-table" },  // brief 32: one table per list
    h("caption", { text: g.title }),
    h("thead", {}, h("tr", {}, h("th", { text: "Attack" }), h("th", { text: "Severity" }), h("th", { text: "Weak spot" }),
      h("th", { text: "Fix" }), h("th", { text: "Check" }))),
    h("tbody", {}, g.findings.map((f) => h("tr", {}, h("td", { class: "attack-label", text: f.label }),
      h("td", { class: "attack-sev" }, h("span", { class: `sev ${f.severity}`, text: f.severity })),
      h("td", { class: "attack-text", text: f.text }), h("td", { class: "attack-fix", text: f.fix }),
      h("td", { class: `attack-check ${f.check === "still open" ? "open" : ""}`, text: f.check })))))),
    red.lines.map((line) => h("div", { class: "redteam-line", text: line }))]  // then the line for a list that didn't run
    : [h("table", { class: "redteam-table" },
      h("caption", { text: "Findings" }),
      h("thead", {}, h("tr", {}, h("th", { text: "Severity" }), h("th", { text: "Weak spot" }), h("th", { text: "Fix" }))),
      h("tbody", {}, red.findings.map((f) => h("tr", {}, h("td", { class: "attack-sev" }, h("span", { class: `sev ${f.severity}`, text: f.severity })),
        h("td", { class: "attack-text", text: f.text }), h("td", { class: "attack-fix", text: f.fix })))))];
  if (task.mode === "plan") return h("div", { class: "redteam-wrap" }, tables);  // UI A row 12 (A19): a plan keeps its board
  // UI A row 12 (A17): folded under its summary once passed or fixed (check_state: a task waiting to land has no outcome yet),
  // staying as you left it; open while running or failed
  const summary = redteamSummary(red);
  if (["passed", "fixed"].includes(task.check_state)) {
    return fold(task, "board", { class: "fold redteam-fold" }, h("summary", { text: summary }), h("div", { class: "redteam-wrap" }, tables));
  }
  return h("div", { class: "board-wrap" }, h("div", { class: "redteam-summary", text: summary }), h("div", { class: "redteam-wrap" }, tables));
}

function pickButton(task, choice, main) {
  // UI A row 8 (A16): its own id, so its confirm's focus can return
  return h("button", { class: buttonClass("", main), type: "button", id: `pick-${task.task_id}-${choice.choice}`, disabled: busy(task),
    onclick: () => act(task, choice.request) }, choice.label);
}

function handoffFold(task, name, text) {
  return fold(task, name, { class: "fold cand-handoff" }, h("summary", { text: "Its handoff" }), h("div", { class: "result" }, renderMarkdown(text)));
}

function candidateFilesEl(files) {
  // a candidate's files drawn as the files block draws its own (break-ui: a long path ran past the card at 390 px)
  if (files.none) return h("div", { class: "cand-files" }, h("span", { class: "files-note", text: "no file changed" }));
  const bad = files.tests && /failed|timed out/.test(files.tests);
  return h("div", { class: "cand-files" },
    files.files.map((f) => h("span", { class: "file-chip static", title: f.path },
      h("span", { class: "file-path", text: middleTruncate(f.path, 56) }), h("span", { class: `file-words ${f.status}`, text: f.words }))),
    files.more ? h("span", { class: "file-chip static more" },
      h("span", { class: "file-path", text: `and ${files.more.toLocaleString("en-US")} more` })) : null,
    files.tests ? h("span", { class: `tests-line${bad ? " bad" : ""}`, text: files.tests }) : null);
}

function offersRow(task) {
  const offers = rescueOffers(task);
  if (!offers.length) return null;
  return h("div", { class: "offer-row offers" }, offers.map((o) => h("span", { class: "offer-item" },
    h("button", { class: buttonClass(o.tone, holdsMain(task, "rescue", o.key)), type: "button",
      id: `act-${task.task_id}-${o.key}`, disabled: busy(task), onclick: () => act(task, o.request) }, o.label),
    o.note ? h("span", { class: "offer-cmd", text: o.note }) : null)));
}

function checkItemsBlock(task) {
  const view = checkItems(task);
  if (!view) return null;
  const list = h("ol", { class: "check-items" }, view.items.map((m) => h("li", { value: m.n, text: m.text })));
  if (!view.folded) return h("div", { class: `check-items-block ${view.kind}` }, h("div", { class: "k", text: view.title }), list);
  return fold(task, "notes", { class: `check-items-block ${view.kind}` }, h("summary", { text: view.title }), list);
}

function blockedBlock(task) {
  const offer = blockedOffer(task);
  if (!offer) return null;
  return h("div", { class: "offer warn", role: "note" },
    h("div", { class: "offer-head" }, icon("alert"), h("span", { class: "offer-title", text: `Blocked: ${offer.what}` })),
    h("div", { class: "offer-body", text: offer.note }),
    h("div", { class: "offer-row" }, h("button", { class: buttonClass("", holdsMain(task, "blocked")), type: "button", id: `again-${task.task_id}`,
      dataset: { focusKey: `again-${task.task_id}` }, onclick: () => runAgainWithText(offer) }, "Run again")));
}

function runAgainWithText(offer) {
  // the task's text into the composer, its tag as it was; nothing is sent until the owner sends it
  const prompt = $("prompt");
  state.text = offer.text;
  if (offer.project) { state.project = offer.project; state.chat = null; }
  else if (offer.chat) { state.chat = offer.chat; state.project = null; }
  if (offer.noFiles) { state.noFiles = true; state.team = "route"; }  // brief 33.4 (decision 9b): a text-only card stays text only
  prompt.value = offer.text;
  renderComposer();
  refreshCommand();
  autosize();
  prompt.focus();
  prompt.setSelectionRange(prompt.value.length, prompt.value.length);
}

function confirmRow(task) {
  const c = state.confirm;
  if (!c || c.taskId !== task.task_id) return null;
  const words = confirmWords(c.task || task, c.request, state.shows.get(task.task_id) || null);
  const extra = c.rereading ? null : confirmExtra(c.task || task, c.request);  // brief 29.1 (decision 21): Land anyway says the check didn't
  // pass; brief 33.2 fix 2: a plan's Approve reads the plan it just read again (`c.task`), with a line when that failed
  return h("div", { class: "confirm", role: "group", "aria-label": "Confirm" },
    // UI-1 row 10 (D14a): the question in words, then the server's command as one muted line; the rest keep today's form
    words ? [h("div", { class: "confirm-text confirm-words", text: words }), h("div", { class: "confirm-cmd", text: c.display || "…" })]
      : h("div", { class: "confirm-text" }, `#${task.n}: run `, h("code", { text: c.display || "…" }), "?"),
    extra ? h("div", { class: "confirm-extra" }, h("div", { text: extra.line }),
      extra.musts.length ? h("ol", { class: "check-items" }, extra.musts.map((m) => h("li", { value: m.n, text: m.text }))) : null) : null,
    c.note ? h("div", { class: "confirm-extra" }, h("div", { text: c.note })) : null,
    c.refused ? h("div", { class: "missing", text: c.refused }) : null,
    h("div", { class: "offer-row" },
      h("button", { class: `btn btn-primary${!c.display || c.refused || c.rereading ? " is-off" : ""}`, type: "button",
        id: `confirm-${task.task_id}`, "aria-disabled": !c.display || c.refused || c.rereading ? "true" : "false",
        onclick: () => { if (c.display && !c.refused && !c.rereading) runAction(task, c.request); } }, "Confirm"),
      h("button", { class: "btn btn-quiet", type: "button", id: `keep-${task.task_id}`, onclick: keepConfirm }, "Keep it")));
}

function keepConfirm() {
  // Keep it, and Esc on an open confirm (UI-1m, 2.7): closed, nothing sent, the focus back on the button that asked
  const c = state.confirm;
  state.confirm = null;
  renderStream({ follow: false });
  if (!c) return;
  if (c.from) focusId(c.from);  // break-ui, keyboard only: back to the button that asked
  else if (c.fromKey) {
    const opener = [...$("stream").querySelectorAll("[data-focus-key]")].find((el) => el.dataset.focusKey === c.fromKey);
    if (opener) opener.focus();
  }
}

function actionLine(task) {
  const running = state.actions.filter((a) => a.taskId === task.task_id);
  const error = state.actionErrors.get(task.task_id);
  if (!running.length && !error) return null;
  return h("div", { class: "action-line" },
    running.map((a) => {
      const view = actionRunView(a);
      return [h("div", { class: "quiet-line", text: view.text }), view.still ? h("div", { class: "quiet-line", text: view.still }) : null];
    }),
    error ? h("div", { class: "offer bad", role: "alert" },
      h("div", { class: "offer-head" }, icon("alert"), h("span", { class: "offer-title", text: error.title }),
        h("span", { class: "offer-side", text: [error.code, error.exit == null ? null : `exit ${error.exit}`].filter(Boolean).join(" · ") })),
      h("div", { class: "offer-body", text: error.message }),
      h("div", { class: "offer-row" }, h("span", { class: "offer-cmd", text: error.display || "" }),
        h("button", { class: "btn btn-quiet", type: "button", onclick: () => { state.actionErrors.delete(task.task_id); renderStream({ follow: false }); } }, "Dismiss"))) : null);
}

function focusId(id) {
  const node = document.getElementById(id);
  if (node) node.focus({ preventScroll: true });
}

function busy(task) {
  return state.restarted || state.starting.has(task.task_id) || state.actions.some((a) => a.taskId === task.task_id);
}

async function commandText(request) {
  if (state.demo) return { display: demoCommand(request) };
  try {
    const doc = await api("/api/command", { method: "POST", body: request });
    return { display: doc.copy || doc.display };
  } catch (e) {
    return { display: "", refused: e.message };
  }
}

function act(task, request) {
  if (needsConfirm(request)) {
    // the first click runs nothing: it names the task and the command, and Confirm runs it
    const active = document.activeElement;
    const ask = { taskId: task.task_id, request, display: null, refused: null, from: active && active.id ? active.id : null,
      fromKey: active && active.dataset ? active.dataset.focusKey || null : null,  // UI-1m (2.7): an opener with no id
      task: null, note: null, rereading: rereadsBeforeConfirm(task, request) };
    state.confirm = ask;
    renderStream({ follow: false });
    focusId(confirmFocusId(task, request));  // break-ui: Enter on Land left focus on the body; UI-1 row 16: Keep it on a discard
    commandText(request).then((found) => {
      if (state.confirm !== ask) return;
      Object.assign(ask, found);
      renderStream({ follow: false });
    });
    if (ask.rereading) {  // brief 33.2 fix 2: a plan's Approve reads the plan again first; Confirm waits for it
      api(`/api/task/${encodeURIComponent(task.task_id)}`).then((show) => show, () => null).then((show) => {
        if (state.confirm !== ask) return;
        if (show) state.shows.set(task.task_id, show);
        Object.assign(ask, approveConfirm(task, show), { rereading: false });
        renderStream({ follow: false });
      });
    }
    return;
  }
  runAction(task, request);
}

async function runAction(task, request) {
  // break-ui: a double click on Confirm started two `sr land` runs. One run per task at a time: the second click finds
  // this one starting, and the Confirm goes at once, before the server answers.
  if (busy(task)) return;
  state.starting.add(task.task_id);
  const fromConfirm = document.activeElement && document.activeElement.id === `confirm-${task.task_id}`;
  if (state.confirm && state.confirm.taskId === task.task_id) state.confirm = null;
  renderStream({ follow: false });
  if (fromConfirm) focusId(`card-${task.task_id}`);
  try {
    const started = await api("/api/run", { method: "POST", body: request });
    state.actions.push({ run_id: started.run_id, taskId: task.task_id, action: request.action,  // D6: its action
      display: started.copy || started.display, started: Date.now() });
    state.actionErrors.delete(task.task_id);
  } catch (e) {
    if (state.demo) toast(e.message);
    else state.actionErrors.set(task.task_id, { title: "Not run", message: e.message, code: null, exit: null, display: "" });
  } finally {
    state.starting.delete(task.task_id);
  }
  renderStream({ follow: false });
  schedulePoll(800);
}

function goToTask(taskId) {
  return jumpToTask(taskId);
}

let jumps = 0;
async function jumpToTask(taskId, n = null) {
  // Cleanup 2, row 2: find the row, open its view, read older pages until the card is loaded, focus it; or say it can't be found
  const ticket = ++jumps;
  let task = taskById(taskId);
  if (!task) {
    try { task = await api(`/api/task/${encodeURIComponent(taskId)}`); } catch (e) { task = null; }
    if (ticket !== jumps) return;
  }
  const missing = () => {
    state.focusTask = null;
    const shown = n == null && task ? task.n : n;
    toast(shown == null ? "That task could not be found" : `#${shown} could not be found`);
  };
  if (!task) { missing(); return; }
  if (state.heldCard && state.heldCard.id === taskId) state.heldCard = null;
  state.focusTask = { id: taskId, until: Date.now() + 10000 };  // until its card is drawn (All tasks loads first)
  const history = task.mode === "suggest" || (!task.chat && !task.project);  // a suggest has no card in its project's stream
  if (history) {
    const q = state.historyQuery;  // a filter that hides the card would read as "could not be found"
    if (q.chat || q.project || q.search) state.historyQuery = { chat: null, project: null, search: "" };
    await openHistory();
  } else {
    if (task.chat) openChat(task.chat);
    else openProject(task.project);
    await viewReading;
  }
  const where = viewReadKey(state);
  const moved = () => ticket !== jumps || viewReadKey(state) !== where || (history && state.view !== "history");
  const nextPage = () => (history ? state.historyNext : (state.viewRead || {}).next);
  for (;;) {
    if (moved()) return;  // the person went elsewhere, or jumped again
    const next = nextPage();
    const step = jumpStep(streamTasks(), next, task);
    if (step === "found") break;
    if (step === "gone") { missing(); return; }
    await (history ? loadHistory({ more: true }) : (viewReading = loadViewRead({ more: true })));
    if (moved()) return;
    if (nextPage() === next) { missing(); return; }  // a read that failed moves nothing on
  }
  if (state.heldCard && state.heldCard.id === taskId) return;  // a read's own redraw already reached it
  state.focusTask = { id: taskId, until: Date.now() + 10000 };  // the timer restarts after the last read
  renderStream({ follow: false });
}

function focusCard() {
  const wanted = state.focusTask;
  if (!wanted) return;
  if (Date.now() > wanted.until) { state.focusTask = null; return; }
  const card = document.querySelector(`#stream > article.task[data-task="${CSS.escape(wanted.id)}"]`);
  if (!card) return;
  state.focusTask = null;
  card.scrollIntoView({ block: "start" });  // the top, not the centre: the sticky composer covers the lower part
  state.heldCard = { id: wanted.id, until: Date.now() + HOLD_MS };  // brief 32.1: it keeps its place while it loads
  card.focus({ preventScroll: true });  // break-ui, keyboard only: the next Tab goes into this card, not the page's top
  card.classList.add("flash");
  setTimeout(() => card.classList.remove("flash"), 1500);
}

// ---------- the desktop notification (permission asked once, from a click) ----------

function notifyState() {
  if (typeof Notification === "undefined" || state.demo) return null;
  return Notification.permission;
}

async function askNotify() {
  const now = notifyState();
  if (now === "default") {
    try { await Notification.requestPermission(); } catch (e) { /* the browser said no */ }
  } else if (now === "denied") {
    toast("Notifications are blocked for this page in the browser's settings.");
  } else if (now === "granted") {
    toast("Notifications are on: the browser's settings turn them off.");
  }
  renderSidebar();
}

function notifyNew() {
  const items = needsYouList(state.tasks).you;
  if (!state.notifyReady) {  // what already needed you when the page opened is on the page, not news
    items.forEach((i) => state.notified.add(i.key));
    state.notifyReady = true;
    return;
  }
  for (const item of items) {
    if (state.notified.has(item.key)) continue;
    state.notified.add(item.key);
    if (notifyState() !== "granted" || (!document.hidden && document.hasFocus())) continue;
    const task = state.tasks.find((t) => t.task_id === item.task_id);
    try {
      const note = new Notification(`#${item.n} needs you: ${item.what}`, { body: task ? String(task.text).slice(0, 140) : "", tag: item.task_id });
      note.onclick = () => { window.focus(); goToTask(item.task_id); note.close(); };
    } catch (e) {
      // a browser that shows no notification from a page still shows the card
    }
  }
}

function clockNow() {
  return state.demo ? demoClock(state.tasks, state.status) : new Date().toISOString();
}

function localTime(iso) {
  const d = new Date(iso || "");
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function pendingCard(item) {
  // UI A row 10 (A9): one line in a grey frame, no command; the task's text on hover, since the box has cleared
  const words = item.team !== "route" ? "Starting…" : item.skill ? "Route · sending…" : "Route · sending… Jev is labeling it";
  return h("article", { class: "task framed frame-grey sending", dataset: { run: item.run_id }, title: item.text, text: words });
}

function refusalCard(run) {
  // UI A row 10 (A9): a red frame, the router's words, the exit code, the other agents when offered, Dismiss, and the
  // command as one muted line; the reason code goes, since the words already say it
  const view = refusalView(run);
  const alts = refusalAlternatives(run, state.status);
  return h("article", { class: "task framed frame-bad refusal", role: "alert" },
    h("div", { class: "offer-head" }, icon("alert"), h("span", { class: "offer-title refusal-title", text: view.title })),
    h("div", { class: "offer-body", text: view.message }),
    view.exit == null ? null : h("div", { class: "quiet-line", text: `Exit code ${view.exit}` }),
    alts.length ? h("div", { class: "offer-row" }, alts.map((alt) => h("button", { class: "btn", type: "button",
      disabled: state.demo || state.restarted, onclick: () => { dismissRefusal(run.id); resend(alt.request); } }, alt.label))) : null,
    h("div", { class: "offer-row" }, h("button", { class: "btn btn-quiet", type: "button", onclick: () => dismissRefusal(run.id) }, "Dismiss")),
    view.display ? h("div", { class: "confirm-cmd", text: view.display }) : null);
}

async function resend(request) {
  if (state.demo || state.restarted) return;
  try {
    const started = await api("/api/run", { method: "POST", body: request });
    state.pending.push({ run_id: started.run_id, pid: started.pid, text: request.text, team: request.team, display: started.copy || started.display });
  } catch (e) {
    toast(e.message);
  }
  render();
  schedulePoll(800);
}

// Every poll draws the cards again. The view stays put: at the bottom if you were there (new work shows up), else
// the first card you can see keeps its place; a new chat, project or view opens at the bottom (the newest task).
function streamAnchor(follow) {
  const el = document.scrollingElement;
  const view = `${state.view}|${state.project}|${state.chat}|${state.quick}|${JSON.stringify(state.historyQuery)}`;
  const changed = view !== state.streamView;
  state.streamView = view;
  const hold = state.heldCard && Date.now() < state.heldCard.until ? state.heldCard : null;
  const held = hold && document.querySelector(`#stream > article.task[data-task="${CSS.escape(hold.id)}"]`);
  const choice = anchorChoice({ changed, follow, nearEnd: el.scrollHeight - el.scrollTop - el.clientHeight < 48, held: !!held });
  if (choice === "end") return { bottom: true };
  if (choice === "held") {  // brief 32.1's D: a jump the page was too short for goes to its place once the page grows
    // its place is where the jump aims it, its scroll margin: the head's height once stuck, not where it is mid-scroll
    const line = parseFloat(getComputedStyle(held).scrollMarginTop) || HEAD_GAP;
    const atEnd = el.scrollHeight - el.scrollTop - el.clientHeight < 2;
    return { id: hold.id, top: heldTop({ top: held.getBoundingClientRect().top, line, atEnd }) };
  }
  const head = document.querySelector("#stream > .stream-head");  // brief 32.1: the card you read is the first below it
  const line = head ? head.getBoundingClientRect().bottom : 80;
  for (const card of document.querySelectorAll("#stream > article.task")) {
    const box = card.getBoundingClientRect();
    if (box.bottom > line) return { id: card.dataset.task, top: box.top };
  }
  return null;
}

function restoreAnchor(anchor) {
  if (!anchor) return;
  const el = document.scrollingElement;
  if (anchor.bottom) { el.scrollTop = el.scrollHeight; return; }
  const card = document.querySelector(`#stream > article.task[data-task="${CSS.escape(anchor.id)}"]`);
  if (card) el.scrollTop += card.getBoundingClientRect().top - anchor.top;
}

function chatNameField(tasks) {
  // Cleanup 2, row 14: optional, before a new chat's first send. Once a chat has tasks its name stays: the name is its memory tag
  const listed = ((state.status && state.status.chats) || []).some((c) => c.name === state.chat);
  if (!isAutoChatName(state.chat) || tasks.length || listed || state.pending.length) return null;
  const hint = h("span", { class: "stream-sub", id: "chat-name-hint", role: "status", text: chatNameHint(state.chatDraft, state.status).text });
  return h("div", { class: "chat-name-row" },
    h("input", { class: "search chat-name", id: "chat-name", type: "text", placeholder: "Name this chat", "aria-label": "Name this chat (optional)", maxlength: "80",
      value: state.chatDraft || "", oninput: (e) => {
        state.chatDraft = e.target.value;
        hint.textContent = chatNameHint(state.chatDraft, state.status).text;
      } }), hint);
}

function renderStream({ follow = true } = {}) {
  if (observer) observer.disconnect();  // the cards are drawn again: the old ones are gone
  if (state.menu !== state.menuDrawn) state.menuDrawn = null;  // the small UI cleanup, row 7: it closed, or another opened
  const anchor = streamAnchor(follow);
  const stream = $("stream");
  const tasks = streamTasks();
  state.newestCard = tasks.length ? tasks[tasks.length - 1].task_id : null;  // UI-1 row 11 (D7): only it shows the time
  state.chipCard = chipCardId(viewKind(), tasks);  // brief 33 (decision 2): the one card of this view with its chips
  const head = h("div", { class: "stream-head" });
  if (state.view === "settings") {  // UI B N5: a redraw keeps the page where you are; a link lands on its row
    const place = document.scrollingElement ? document.scrollingElement.scrollTop : 0;
    keepFocus(() => setChildren(stream, settingsView(head)));
    watchHeights();
    if (document.scrollingElement) document.scrollingElement.scrollTop = place;
    if (state.setupFocus) {
      const row = document.getElementById(`setup-${state.setupFocus}`);
      if (row) row.scrollIntoView({ block: "start" });
      state.setupFocus = null;
    }
    return;
  }
  if (state.view === "logfiles") {
    keepFocus(() => setChildren(stream, logFilesView()));
    watchHeights();  // brief 32.1: its head sticks too
    restoreAnchor(anchor);
    return;
  }
  if (state.view === "history") {
    head.append(historyTabs(), h("span", { class: "stream-title", text: "All tasks" }), historyFilter(), historySearch(),
      h("span", { class: "stream-sub right", text: state.historyError ? state.historyError : `${tasks.length} shown${state.historyNext ? " · older ones above" : ""}` }));
  } else if (state.project) {
    const where = (projectOf(state.project) || {}).path || null;  // UI-1 row 14 (D18): the ~ path the router sent
    head.append(h("span", { class: "stream-title", text: state.project }), h("span", { class: "stream-sub head-where", title: where,
      text: ["project", where ? middleTruncate(where, 40) : null, "HANDOFF.md rides on every call"].filter(Boolean).join(" · ") }),
      whatNowLine(state.project),  // brief 33 (decision 13): under the title, never folded with the bar
      projectBar(state.project));  // brief 28 (decision 20b)
  } else if (state.chat) {
    const nameField = chatNameField(tasks);  // append(null) would write the word "null"
    head.append(h("span", { class: "stream-title", text: state.chat }), ...(nameField ? [nameField] : []),
      h("span", { class: "stream-sub", id: "chat-memory", text: chatHeadWords(chatCount(state.status, state.chat, tasks.length), (state.status || {}).memory) }),
      h("span", { class: "stream-sub right", text: `every task here is sent with --chat ${state.chat}` }));
  } else {
    head.append(h("span", { class: "stream-title", text: "Quick tasks" }), h("span", { class: "stream-sub", text: "no chat, no memory" }));
  }
  const items = [head, firstRunCard()].filter(Boolean);  // brief 34; UI-1 row 7 (D6a): the Auto confirm is a sheet now
  if (state.view === "history" && state.historyNext) {
    items.push(h("button", { class: "btn btn-quiet load-earlier", type: "button", onclick: () => loadHistory({ more: true }) }, "Load earlier tasks"));
  }
  if (state.view === "chat" && state.viewRead && state.viewRead.next) {  // Cleanup 2, row 2: a chat's or a project's older tasks
    items.push(h("button", { class: "btn btn-quiet load-earlier", type: "button", id: "show-older", disabled: state.viewRead.loading, onclick: () => {
      viewReading = loadViewRead({ more: true });
      renderStream({ follow: false });
    } }, "Show older"));
  }
  if (!tasks.length && !state.pending.length && !state.refused.length) {
    // brief 26 (decision 14): a project with no tasks says its HANDOFF.md goes with every task sent there
    const project = state.project && state.view === "chat" ? ((state.status && state.status.projects) || []).find((p) => p.name === state.project) : null;
    const read = state.viewRead;
    const logError = state.logError || (read && read.error);
    const reading = !logError && read && !read.pages && read.key.startsWith("chat:") && ((state.status && state.status.chats) || []).some((c) => c.name === state.chat);
    items.push(h("div", { class: "empty", id: project ? "np-empty-card" : null, text: logError ? `The log could not be read: ${logError}`
      : reading ? "Loading this chat's tasks…" : project ? emptyProjectWords(project) : "No tasks here yet. Type below and press Enter." }));
  }
  items.push(...tasks.map(taskCard));
  items.push(...state.pending.map(pendingCard));
  items.push(...state.refused.map(refusalCard));
  keepFocus(() => { setChildren(stream, items); fitHead(); });  // brief 32.1: folded before anything paints
  watchHeights();
  restoreAnchor(anchor);
  focusCard();
}

export function focusMark(el) {
  // brief 29.1 (decision 7b): what finds a focused control again after a redraw: its id, else its stable key
  // (`data-focus-key`: Run again as…, a card's Cancel, the first-run card's How to set it up), else nothing
  if (!el) return null;
  if (el.id) return { id: el.id };
  const key = el.dataset && el.dataset.focusKey;
  return key ? { key } : null;
}

function keepFocus(draw) {
  // every poll draws the stream again: a field you are typing in (History's search) keeps its focus and caret, and any
  // control that had the focus gets it back, by its id or its stable key
  const active = document.activeElement;
  const mark = active && $("stream").contains(active) ? focusMark(active) : null;
  const range = mark && typeof active.selectionStart === "number" ? [active.selectionStart, active.selectionEnd] : null;
  draw();
  if (!mark) return;
  const again = mark.id ? document.getElementById(mark.id)
    : [...$("stream").querySelectorAll("[data-focus-key]")].find((el) => el.dataset.focusKey === mark.key);
  if (again && again !== active) {
    again.focus();
    if (range && again.setSelectionRange) again.setSelectionRange(range[0], range[1]);
  }
}

function historyFilter() {
  const status = state.status || {};
  const value = state.historyQuery.chat ? `chat:${state.historyQuery.chat}` : state.historyQuery.project ? `project:${state.historyQuery.project}` : "";
  return h("select", { class: "select", id: "history-filter", "aria-label": "Which chat or project",
    onchange: (e) => {
      const [kind, ...rest] = e.target.value.split(":");
      const name = rest.join(":") || null;
      state.historyQuery = { ...state.historyQuery, chat: kind === "chat" ? name : null, project: kind === "project" ? name : null };
      loadHistory();
    } },
  h("option", { value: "", text: "Every chat and project", selected: !value }),
  (status.chats || []).map((c) => h("option", { value: `chat:${c.name}`, text: `chat ${c.name}`, selected: value === `chat:${c.name}` })),
  (status.projects || []).map((p) => h("option", { value: `project:${p.name}`, text: `project ${p.name}`, selected: value === `project:${p.name}` })));
}

let searchTimer = null;
function historySearch() {
  return h("input", { class: "search", id: "history-search", type: "search", placeholder: "Search the tasks", "aria-label": "Search the tasks",
    value: state.historyQuery.search, oninput: (e) => {
      state.historyQuery = { ...state.historyQuery, search: e.target.value };
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => loadHistory(), 300);
    } });
}

function firstRunCard() {
  const items = firstRunItems(state.status);
  if (!items.length) return null;
  return h("div", { class: "offer warn first-run", role: "status" },
    h("div", { class: "offer-head" }, icon("alert"),
      h("span", { class: "offer-title", text: items.length === 1 ? "One piece isn't ready" : `${items.length} pieces aren't ready` }),
      h("span", { class: "offer-side", text: "Settings has the steps" })),
    h("ul", { class: "first-run-list" }, items.map((item) => h("li", {}, h("strong", { text: item.name }), ` · ${item.reason} · `,
      h("button", { class: "linklike", type: "button", dataset: { focusKey: `first-run-${item.key}` },
        onclick: () => openSetup(item.key) }, "How to set it up")))));
}

function historyTabs() {
  // UI B row 1 (Q6): All tasks and Log files as two tabs at the head of those views, each with today's handler
  return h("div", { class: "tabs history-tabs", role: "tablist", "aria-label": "History" },
    [["history", "All tasks", openHistory], ["logfiles", "Log files", openLogFiles]].map(([view, label, go]) => h("button", { class: "tab", type: "button", role: "tab",
      "aria-selected": state.view === view ? "true" : "false", onclick: go }, label)));
}

function logFilesView() {
  const known = [...(state.tasks || []), ...(state.historyTasks || [])];
  const head = h("div", { class: "stream-head" }, historyTabs(), h("span", { class: "stream-title", text: "Log files" }),
    h("span", { class: "stream-sub", text: "every call's output, newest first · a file opens beside" }),
    h("button", { class: "btn btn-quiet right", type: "button", onclick: () => loadLogFiles() }, "Refresh"));
  const rows = state.logFolders.map((folder) => {
    const view = logFolderView(folder, known);
    return h("div", { class: "log-row" }, h("div", { class: "log-title" }, h("span", { class: "log-name", text: view.title }),
      view.when ? h("span", { class: "stream-sub", text: localTime(view.when) }) : null),
    h("div", { class: "files-row" }, view.files.length ? view.files.map((f) => h("button", { class: "file-card", type: "button",
      "aria-current": state.panel && state.panel.file && state.panel.file.path === f.path ? "true" : null,
      onclick: () => openPanel(taskById(folder.task_id) || { task_id: folder.task_id, n: "?" }, f.file) },
    h("span", { class: "file-icon text" }, icon("code")), h("span", { class: "file-text" }, h("span", { class: "file-name", text: f.name }),
      h("span", { class: "file-meta", text: humanSize(f.file.size) })))) : h("span", { class: "stream-sub", text: "no round files" })));
  });
  return [head, state.logError ? h("div", { class: "empty", text: `The log files could not be listed: ${state.logError}` }) : null,
    !rows.length && !state.logError ? h("div", { class: "empty", text: "No round files yet." }) : null, ...rows,
    state.logNext ? h("button", { class: "btn btn-quiet load-earlier", type: "button", onclick: () => loadLogFiles({ more: true }) }, "Load older") : null];
}

function renderComposer() {
  const status = state.status;
  renderTeam();
  const ctx = contextFor(state, status);
  const tag = $("context-tag");  // UI A row 15 (A12): only when the send goes somewhere other than the view
  const tagWords = contextTagWords(ctx, viewKind());
  tag.hidden = !tagWords;
  tag.textContent = tagWords || "";
  tag.title = tagWords || "";
  const greys = composerGreys(state.team);  // brief 29 (decision 1): what this team greys, each with its reason
  $("quick").checked = state.quick && !greys.quick;
  $("quick").disabled = !!greys.quick;
  $("quick").title = greys.quick || "";
  if ($("quick-label")) {
    $("quick-label").classList.toggle("off", !!greys.quick);
    $("quick-label").title = greys.quick || "No chat, no memory";
  }
  const projectSelect = $("project");
  const projects = (status && status.projects) || [];
  // brief 26 (decision 12): the last option opens the New project sheet, so the picker works with no projects
  const picker = projectOptions(projects, { current: state.project, greyed: ctx.projectGreyed, quick: state.quick });
  setChildren(projectSelect, picker.options.map((o) => h("option", { value: o.value, selected: o.selected, text: o.text })));
  projectSelect.disabled = picker.disabled;
  projectSelect.title = ctx.projectGreyed && !state.quick ? `${teamLabel(state.team)} takes no --project` : "";
  const onRoute = state.team === "route";
  $("web").disabled = !onRoute;
  $("web").checked = onRoute && state.web;
  $("web-label").classList.toggle("off", !onRoute);
  $("web-label").title = onRoute ? "Let the agents search the web on a task with files" : greys.web;
  $("attach").disabled = !onRoute || state.demo;
  $("attach").title = onRoute ? "Attach a file (or drop one here)" : greys.files;
  // UI A row 15 (A12): each + item's state on its right; a greyed one says why in words
  const stateOf = (id) => $(id).querySelector(".plus-state");
  const words = plusStates(state, greys);
  stateOf("attach").textContent = words.attach;
  stateOf("web-label").textContent = words.web;
  stateOf("quick-label").textContent = words.quick;
  document.querySelector(".plus-project .plus-state").textContent = picker.disabled
    ? (state.quick ? "Quick task: no project" : `${teamLabel(state.team)} takes no project`) : "";
  setChildren($("files"), state.files.map((file) => h("span", { class: "chip-tag" }, icon("file"), h("span", { text: file.name }),
    h("button", { class: "x", type: "button", "aria-label": `Remove ${file.name}`, onclick: () => removeFile(file.path) }, "×"))));
  const pick = skillPick(state, status);  // brief 24 (decision 13): without Jev you pick the skill before Send
  const skill = $("skill");  // UI A row 1 (A13): "Skill · Auto" with Jev on, "Pick one" with Jev off, greyed off Route
  const choice = skillChoice(state, status);
  setChildren(skill, h("option", { value: "", text: choice.first }),
    choice.options.map((o) => h("option", { value: o.key, selected: o.key === choice.chosen, text: o.label })));
  skill.disabled = !!choice.greyed;
  skill.title = pick.needed ? pick.why : choice.greyed || "Auto: Jev labels the task. A skill you pick goes as it is, and Jev isn't asked";
  document.querySelector(".plus-skill .plus-state").textContent = choice.greyed || "";
  const skillPill = $("skill-pill");
  skillPill.hidden = !choice.chosen;
  setChildren(skillPill, choice.chosen ? [h("span", { text: `Skill: ${choice.chosen.replace(/_/g, " ")}` }),
    h("button", { class: "x", type: "button", "aria-label": "Let Jev label it", onclick: () => { state.skill = null; refreshCommand(); renderComposer(); } }, "×")] : []);
  const send = $("send");
  const planOff = state.team === "plan" && !ctx.value ? PLAN_OFF_PROJECT : null;  // brief 33.1 (decision 1)
  send.textContent = pick.needed && !pick.chosen ? "Send · pick a skill" : `Send · ${teamLabel(state.team)}`;
  send.disabled = state.demo || state.restarted || !state.text.trim() || (pick.needed && !pick.chosen) || !!planOff;
  send.title = state.demo ? "Demo: nothing runs" : pick.needed && !pick.chosen ? pick.why : planOff || "";
  const prompt = $("prompt");
  const placeholder = state.fillPlaceholder && (state.from || state.team === "plan") ? state.fillPlaceholder : placeholderFor(state.team, status);  // 33.2
  const placeholderMoved = prompt.placeholder !== placeholder;
  prompt.placeholder = placeholder;  // brief 33 (decision 4): "What should be built from #<n>?" after Build from this
  if (placeholderMoved) autosize();  // the small UI cleanup, row 11 (note 3): a new team's chain may need another line
  $("prompt-label").textContent = placeholder;
  const fromPill = $("from-pill");  // brief 33 (decision 12): "From #<n>" with its ×, beside the tag
  fromPill.hidden = !state.from;
  setChildren(fromPill, state.from ? [h("span", { text: `From #${state.from.n}` }),
    h("button", { class: "x", type: "button", "aria-label": `Don't carry #${state.from.n}'s result`,
      onclick: () => { state.from = null; state.fillPlaceholder = null; refreshCommand(); renderComposer(); } }, "×")] : []);
  const stepPill = $("step-pill");  // brief 33.1 (decision 12): "Step 2 of plan #12" with its ×, on Route or a team
  const stepShown = state.step && state.team !== "split" && state.team !== "plan" ? state.step : null;
  stepPill.hidden = !stepShown;
  setChildren(stepPill, stepShown ? [h("span", { text: stepPillWords(stepShown) }),
    h("button", { class: "x", type: "button", "aria-label": "Send it as a task of its own, not the plan's step",
      onclick: () => { state.step = null; refreshCommand(); renderComposer(); } }, "×")] : []);
  const ideaPill = $("idea-pill");  // brief 33 (decision 16): "Idea" with its ×; without it the text goes as plain text
  ideaPill.hidden = !state.idea;
  ideaPill.title = (state.idea && state.idea.text) || "";  // UI A row 5 (A15): the whole idea on hover
  setChildren(ideaPill, state.idea ? [h("span", { text: ideaPillWords(state.idea) }),
    h("button", { class: "x", type: "button", "aria-label": "Send it as plain text, leaving the idea alone",
      onclick: () => { state.idea = null; refreshCommand(); renderComposer(); } }, "×")] : []);
  const modelPills = $("model-pills");  // brief 33.3 (decision 12): "Claude: Haiku ×" per chosen agent; nothing while the defaults apply
  const pills = modelPillViews(state.models, status);
  modelPills.hidden = !pills.length;
  setChildren(modelPills, pills.map((p) => h("span", { class: "chip-tag pill-model" }, h("span", { text: p.words }),
    h("button", { class: "x", type: "button", "aria-label": p.aria, onclick: () => clearModel(p.agent) }, "×"))));
  // ---- UI-1 (D2): the spot for 33.4's Draft it fill and its Text only pill; nothing else goes in it. The fill itself is
  // fillDraftIt, which runs on Create and fills through useChip and setBox, so the pill is what this function draws. ----
  const textOnlyPill = $("textonly-pill");  // brief 33.2 (decision 5): "Text only" with its ×, on Route with a project (Draft it)
  const textOnly = state.noFiles && state.team === "route" && state.project && state.project !== NEW_PROJECT;
  textOnlyPill.hidden = !textOnly;
  setChildren(textOnlyPill, textOnly ? [h("span", { text: "Text only" }),
    h("button", { class: "x", type: "button", "aria-label": "Let the task change the project's files",
      onclick: () => { state.noFiles = false; refreshCommand(); renderComposer(); } }, "×")] : []);
  // ---- end of 33.4's spot ----
  $("composer").classList.toggle("lit", state.team !== "route");
  renderCommand();
  renderJev();
}

function plusOpen() {
  const menu = document.querySelector(".plus-menu");
  return !!menu && !menu.hidden;
}

function plusItems() {
  // UI A row 15 (A12): the controls ↑ and ↓ move through, the greyed ones left out
  return [...document.querySelector(".plus-menu").querySelectorAll("button:not(:disabled), select:not(:disabled), input:not(:disabled)")].filter((el) => !el.hidden);
}

function setPlus(open) {
  // UI-1 row 5 (D2), UI A row 15: + shows or hides its items, with today's ids and handlers; it calls nothing. Open, the
  // first item not greyed takes the focus
  document.querySelector(".plus-menu").hidden = !open;
  document.querySelector(".plus-btn").setAttribute("aria-expanded", open ? "true" : "false");
  if (open) { const first = plusItems()[0]; if (first) first.focus(); }
}

function plusKeys(e) {
  // UI A row 15 (A12): ↑ and ↓ move between the rows, and never change a select's value; Enter or Space opens a select;
  // Enter ticks a toggle, as Space already does. Esc is onKey's: it closes the menu and the focus goes back to +
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    const items = plusItems();
    if (!items.length) return;
    e.preventDefault();
    const at = items.indexOf(e.target);
    items[(at + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].focus();
    return;
  }
  if (e.target.tagName === "SELECT" && (e.key === "Enter" || e.key === " ")) {
    try { if (e.target.showPicker) { e.preventDefault(); e.target.showPicker(); } } catch (err) { /* the browser's own key handling stays */ }
    return;
  }
  if (e.target.tagName === "INPUT" && e.key === "Enter") { e.preventDefault(); e.target.click(); }
}

function renderTeam() {
  // "Route ▾" (UI A row 14, A14): a menu of Route and the presets from status, each chain on hover, ⌥1-⌥8; a lit team's
  // slots as small selects, the slot rule as their tooltip
  const status = state.status;
  const chips = chipViews(status, state.team, { project: state.project === NEW_PROJECT ? null : state.project });  // 33.1
  const lit = chips.find((c) => c.checked) || { label: teamLabel(state.team), title: "" };
  const parts = [h("button", { class: `team-btn${state.team !== "route" ? " lit" : ""}`, type: "button", id: "team-btn",
    "aria-haspopup": "menu", "aria-expanded": state.teamMenu ? "true" : "false", title: lit.title || "",
    onclick: (e) => { e.stopPropagation(); state.teamMenu = !state.teamMenu; renderTeam(); } },
  h("span", { text: lit.label }), h("span", { class: "caret", "aria-hidden": "true" }, icon("chevron")))];
  if (state.teamMenu) {
    parts.push(h("div", { class: "team-menu", role: "menu", "aria-label": "Team" }, chips.map((chip) => h("button", {
      class: "team-item", type: "button", role: "menuitemradio", "aria-checked": chip.checked ? "true" : "false",
      "aria-disabled": chip.disabled ? "true" : null, title: chip.reason || chip.title,
      onclick: (e) => {
        e.stopPropagation();
        if (chip.disabled) { toast(chip.reason); return; }
        state.teamMenu = false;
        setTeam(chip.key);
      } },
    h("span", { class: "name", text: chip.label }), chip.disabled ? h("span", { class: "why", text: chip.reason }) : null,
    chip.shortcut ? h("span", { class: "key", text: chip.shortcut }) : null)),
    modelsMenuButton(status),  // brief 33.3 (decision 12): Models… last
    h("div", { class: "team-foot", text: "Each team's chain shows on hover." })));  // UI A row 14 (A14)
  }
  setChildren($("team"), parts);
  // UI A row 9 (A14): a preset's slots on their own line under the box, real selects, today's ids; only with a preset chosen
  const preset = ((status && status.presets) || []).find((p) => p.name === state.team);
  const slotsLine = $("slots");
  slotsLine.hidden = !preset;
  if (!preset) { setChildren(slotsLine); return; }
  const view = slotViews(preset, state.slots, status, state.project === NEW_PROJECT ? null : state.project);  // brief 32
  // break-ui: four slots (redteam) wrap below ~830 px, so they go without the "·" that would end a line
  setChildren(slotsLine, h("span", { class: view.slots.length > 3 ? "team-slots many" : "team-slots", title: view.note || "" }, view.slots.map((slot, i) => [
    i ? h("span", { class: "dot", "aria-hidden": "true", text: "·" }) : null,
    h("label", { class: "slot-inline", title: view.note ? `${slot.label} · ${view.note}` : slot.label },
      h("span", { class: "slot-name", text: slotShort(slot) }),
      h("select", { class: "slot-select", id: `slot-${slot.name}`, "aria-label": slot.label,
        title: slot.leftOut ? `Left out: ${slot.options[0].reason}` : null,  // brief 32: why, without opening it
        onchange: (e) => { state.slots = { ...state.slots, [slot.name]: e.target.value }; refreshCommand(); } },
      slot.options.map((o) => h("option", { value: o.agent, disabled: o.disabled, selected: o.agent === slot.value,
        title: o.disabled ? o.reason : null }, o.disabled ? `${o.label} (${o.reason})` : o.label)))),
    slot.leftOut ? h("span", { class: "slot-why", text: `Left out: ${slot.options[0].reason}` }) : null])));  // a phone has no tooltip
}

function renderCommand() {
  const line = $("cmdline");
  const cmd = $("cmd");
  const command = state.command;
  line.classList.toggle("err", !!(command && command.error));
  if (!command) { setChildren(cmd, h("span", { class: "added", text: "sr route --json --source ui -- …" })); return; }
  if (command.error) { cmd.textContent = command.error; return; }
  setChildren(cmd, command.parts.map((part, i) => [i ? " " : "", h("span", { class: part.added ? "added" : null, text: part.text })]));
  cmd.title = command.display;
}

function renderJev() {
  const status = state.status;
  const floor = status && status.jev && status.jev.floor != null ? status.jev.floor : 0.8;
  const missing = status && status.jev && status.jev.available === false ? (status.jev.why || "Jev isn't set up") : null;
  const box = jevBox({ team: state.team, task: state.lastRouteTask, floor, sending: state.pending.some((p) => p.team === "route" && !p.skill),
    missing: missing ? "Jev isn't set up: pick the skill" : null });
  const jev = $("jev");
  jev.classList.toggle("under", !!box.under);
  jev.classList.toggle("idle", box.mode !== "label");
  jev.dataset.mode = box.mode;  // UI-1 row 5 (D2): the CSS hides the truly idle line only
  if (box.mode === "label") {
    const bar = h("span", { class: "bar", "aria-hidden": "true" }, h("span"), h("i"));
    bar.children[0].style.width = `${Math.round((box.confidence || 0) * 100)}%`;
    bar.children[1].style.left = `${Math.round(box.floor * 100)}%`;
    // UI A row 4 (A15): "Jev: writing, 0.91, [bar], above the 0.80 floor"; the bar stays (the owner's call, 29 Oct)
    setChildren(jev, h("span", { text: `Jev: ${box.label}${box.confidence == null ? "" : `, ${box.confidence.toFixed(2)}`},` }),
      bar, h("span", { text: box.under ? `under the ${box.floor.toFixed(2)} floor: you pick` : `above the ${box.floor.toFixed(2)} floor` }));
  } else {
    setChildren(jev, h("span", { class: "k", text: "Jev" }), h("span", { text: box.text }));
  }
}

let viewReading = Promise.resolve();  // the view's newest read, so a jump can wait for it

function syncViewRead() {
  // Cleanup 2, row 1: every way into a view passes through render(), so a changed key is noticed here
  const key = viewReadKey(state);
  if ((state.viewRead ? state.viewRead.key : null) === key) return;
  state.viewRead = key ? { key, tasks: [], next: null, pages: 0, loading: false, error: null } : null;
  if (key) viewReading = loadViewRead();
}

async function loadViewRead({ more = false, quiet = false } = {}) {
  const read = state.viewRead;
  if (!read) return;
  const { key } = read;
  if (!quiet) state.viewRead = { ...read, loading: true };
  try {
    const doc = await api(historyPath(viewReadQuery(key), more ? read.next : null));
    if (!state.viewRead || state.viewRead.key !== key) return;  // the person moved on, as loadHistory's check
    state.viewRead = takeViewPage(state.viewRead, doc, { more, quiet });
  } catch (e) {
    if (!state.viewRead || state.viewRead.key !== key) return;
    state.viewRead = { ...state.viewRead, loading: false, error: e.status === 403 ? state.viewRead.error : e.message };
  }
  if (!quiet && state.view === "chat") renderStream({ follow: !more });
}

function render() {
  syncViewRead();
  renderBanners();
  renderRail();
  renderStrip();
  renderSidebar();
  renderStream();
  renderComposer();
  renderPanel();
  if (state.sheetKind === "newproject") paintNewProject();  // status may name a project taken meanwhile
}

function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.hidden = false;
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => { node.hidden = true; }, 3200);
}

// ---------- a card's details and the side panel ----------

let observer = null;
function observeCard(card, task) {
  if (typeof IntersectionObserver === "undefined") { loadShow(task.task_id); return; }
  if (!observer) {
    observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        observer.unobserve(entry.target);
        const id = entry.target.dataset.task;
        if (id && !state.shows.has(id)) loadShow(id);
      }
    }, { rootMargin: "200px" });
  }
  if (!state.shows.has(task.task_id)) observer.observe(card);
}

async function loadShow(taskId, { quiet = false } = {}) {
  if (state.loading.has(taskId)) return;
  if (!state.loading.size) showDraws.at = Date.now();  // a burst starts
  state.loading.add(taskId);
  try {
    const [show, files] = await Promise.all([api(`/api/task/${encodeURIComponent(taskId)}`),
      api(`/api/files/${encodeURIComponent(taskId)}`).catch(() => ({ files: [] }))]);
    state.shows.set(taskId, show);
    state.filesOf.set(taskId, files.files || []);
    state.viewRead = patchViewRow(state.viewRead, show);  // Cleanup 2, row 1: Land, Undo or Forget on an older card shows at once
  } catch (e) {
    // a card without its details still shows the log row
  } finally {
    state.loading.delete(taskId);
  }
  // the small UI cleanup, row 8 (note 9): a burst of card loads redraws once, when its last load ends, and at most once a second
  // [GUESS: 1 second] while a long one runs, so a button doesn't vanish under the pointer as each card's details arrive
  if (!quiet) showDraws.owed = true;
  if (showDraws.owed && (!state.loading.size || Date.now() - showDraws.at >= SHOW_DRAW_MS)) {
    showDraws.owed = false;
    showDraws.at = Date.now();
    renderStream();
  }
  if (state.panel && state.panel.taskId === taskId) renderPanel();
}

function taskById(taskId) {
  return (state.tasks || []).find((t) => t.task_id === taskId)
    || (state.viewRead ? state.viewRead.tasks.find((t) => t.task_id === taskId) : null)
    || (state.shows.get(taskId) || null);
}

function fileByPath(taskId, path) {
  return (state.filesOf.get(taskId) || []).find((f) => f.path === path) || null;
}

function openRoundFile(task, path) {
  const file = fileByPath(task.task_id, path) || { path, name: path.split("/").pop(), kind: "text", round: null, missing: true };
  openPanel(task, file);
}

function openFile(task, path) {
  const file = fileByPath(task.task_id, path);
  if (file) openPanel(task, file);
}

function openPanel(task, file, tab = "preview") {
  if (state.panel && state.panel.blob) URL.revokeObjectURL(state.panel.blob);
  for (const url of (state.panel && state.panel.blobs) || []) URL.revokeObjectURL(url);
  state.panel = { taskId: task.task_id, file, tab, text: null, blob: null, blobs: [], truncated: null, error: null, kind: "file" };
  renderPanel();
  loadPanelFile();
  renderStream({ follow: false });
}

function closePanel() {
  clearTimeout(state.outputTimer);  // brief 31: a project output's poll ends with its panel
  if (state.panel && state.panel.blob) URL.revokeObjectURL(state.panel.blob);
  for (const url of (state.panel && state.panel.blobs) || []) URL.revokeObjectURL(url);
  state.panel = null;
  renderPanel();
  renderStream({ follow: false });
}

async function fetchFile(path) {
  return api(`/api/file?path=${encodeURIComponent(path)}`, { raw: true });
}

async function loadPanelFile() {
  const panel = state.panel;
  if (!panel || panel.kind !== "file") return;
  const file = panel.file;
  if (file.missing) { panel.error = "not kept (this task ran before round files were kept, or the file is gone)"; renderPanel(); return; }
  try {
    const resp = await fetchFile(file.path);
    if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).error || `HTTP ${resp.status}`);
    panel.truncated = resp.headers.get("X-SR-Truncated");
    if (file.kind === "text") panel.text = await resp.text();
    else if (file.kind === "image") panel.blob = URL.createObjectURL(await resp.blob());
    if (file.kind === "pdf" || file.kind === "video") {
      const all = state.filesOf.get(panel.taskId) || [];
      const shots = (file.kind === "pdf" ? pdfShots(file, all) : all.filter((f) => f.root === "media/frames" && f.kind === "image")).slice(0, 12);
      for (const shot of shots) {
        const r = await fetchFile(shot.path);
        if (r.ok) panel.blobs.push(URL.createObjectURL(await r.blob()));
      }
    }
  } catch (e) {
    panel.error = e.message;
  }
  if (state.panel === panel) renderPanel();
}

async function download(path, name) {
  try {
    const resp = await api(`/api/file?path=${encodeURIComponent(path)}&download=1`, { raw: true });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const url = URL.createObjectURL(await resp.blob());
    const a = h("a", { href: url, download: name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  } catch (e) {
    toast(`Download failed: ${e.message}`);
  }
}

async function reveal(path) {
  try {
    await api("/api/reveal", { method: "POST", body: { path } });
  } catch (e) {
    toast(e.message);
  }
}

function codeView(text) {
  const lines = String(text).split("\n");
  return h("div", { class: "code" }, h("div", { class: "nums", "aria-hidden": "true", text: lines.map((_, i) => i + 1).join("\n") }),
    h("div", { class: "src", text }));
}

function otherCandidate(task, show) {
  const candidates = (show && show.candidates) || [];
  const picked = show && show.pick;
  const other = candidates.find((c) => c.letter !== picked) || candidates[1] || null;
  if (!other) return [h("p", { class: "panel-note", text: "There is no other candidate on this task." })];
  return [h("div", { class: "cand-head" }, h("span", { class: `letter ${other.letter}`, text: other.letter.toUpperCase() }),
    h("span", { class: "cand-who", text: agentLabel(other.builder) })),
  h("div", { class: "result" }, renderMarkdown(candidateText(other.text).text)),
  candidateText(other.text).handoff ? handoffFold(task, "panel-handoff", candidateText(other.text).handoff) : null,
  other.review ? h("p", { class: "panel-note", text: `${agentLabel(other.review.reviewer)}'s review: ${other.review.verdict || "no verdict"}` }) : null,
  other.review && other.review.notes ? h("div", { class: "review-notes", text: other.review.notes }) : null];
}

function runLog(taskId) {
  const runs = (state.runs || []).filter((r) => r.task_id === taskId);
  if (!runs.length) return [h("p", { class: "panel-note", text: "Not kept here (run from Terminal or an earlier page)." })];
  return [h("div", { class: "runlog" }, runs.map((run) => h("div", { class: "runlog-item" },
    h("div", { class: "panel-sub", text: `${run.display} · ${run.running ? "running" : `exit ${run.exit}`} · ${localTime(run.started)}` }),
    run.message ? h("pre", { text: run.message }) : null, run.stderr ? h("pre", { text: run.stderr }) : null)))];
}

function renderPanel() {
  const node = $("panel");
  const app = $("app");
  const panel = state.panel;
  const wasOpen = app.classList.contains("panel-open");
  app.classList.toggle("panel-open", !!panel);
  if (wasOpen !== !!panel && state.status) renderStrip();  // UI B's live check: Needs you in the head
  if (!panel) { node.hidden = true; setChildren(node); return; }
  node.hidden = false;
  if (panel.kind === "memory") { renderMemoryPanel(node, panel); return; }
  if (panel.kind === "doc") { renderDocPanel(node, panel); return; }
  if (panel.kind === "diff") { renderDiffPanel(node, panel); return; }  // brief 28
  if (panel.kind === "project") { renderProjectPanel(node, panel); return; }  // brief 31: a Test's or a Run's output
  const task = taskById(panel.taskId) || { n: "?", task_id: panel.taskId };
  const show = state.shows.get(panel.taskId);
  const file = panel.file;
  const name = file.round ? roundName(file) : file.name;
  const sub = [`#${task.n}`, task.agent ? `built by ${agentLabel(task.agent)}` : null, task.checker ? `checked by ${agentLabel(task.checker)}` : null,
    show && show.pick ? `picked ${show.pick.toUpperCase()}` : null].filter(Boolean).join(" · ");
  const tabs = [["preview", "Preview"], ["source", "Source"]];
  if (show && show.candidates) tabs.push(["other", "Other candidate"]);
  tabs.push(["runlog", "Run log"]);
  const tools = [];
  if (panel.text != null) tools.push(h("button", { class: "icon-btn", type: "button", "aria-label": "Copy the text",
    onclick: async () => { try { await navigator.clipboard.writeText(panel.text); toast("Copied."); } catch (e) { toast("Copy is blocked in this browser."); } } }, icon("copy")));
  if (state.reveal && !file.missing) tools.push(h("button", { class: "icon-btn", type: "button", "aria-label": "Open in Finder", title: "Open in Finder", onclick: () => reveal(file.path) }, icon("reveal")));
  if (!file.missing) tools.push(h("button", { class: "icon-btn", type: "button", "aria-label": "Download", title: "Download", onclick: () => download(file.path, file.name) }, icon("download")));
  tools.push(h("button", { class: "icon-btn", type: "button", "aria-label": "Close the panel", onclick: closePanel }, icon("x")));
  const head = h("div", { class: "panel-head" },
    h("div", { class: "panel-row" }, h("span", { class: `file-icon ${file.kind}` }, icon(file.kind === "text" ? "code" : "file")),
      h("div", { class: "panel-title" }, h("div", { class: "panel-name", text: name }), h("div", { class: "panel-sub", text: sub })),
      h("div", { class: "panel-tools" }, tools)),
    h("div", { class: "tabs", role: "tablist", "aria-label": "View" }, tabs.map(([key, label]) => h("button", {
      class: "tab", type: "button", role: "tab", "aria-selected": panel.tab === key ? "true" : "false",
      onclick: () => { panel.tab = key; renderPanel(); if (key === "runlog") loadRunsNow(); } }, label))));
  let body = [];
  if (panel.error) body = [h("p", { class: "panel-note", text: panel.error })];
  else if (panel.tab === "other") body = otherCandidate(task, show);
  else if (panel.tab === "runlog") body = runLog(panel.taskId);
  else if (panel.tab === "source") {
    body = panel.text != null ? [codeView(panel.text)] : [h("p", { class: "panel-note", text: file.kind === "text" ? "Loading…" : "No source view for this file: see Preview." })];
  } else if (file.kind === "text") {
    body = panel.text == null ? [h("p", { class: "panel-note", text: "Loading…" })] : [h("div", { class: "result" }, renderMarkdown(panel.text))];
  } else if (file.kind === "image") {
    body = panel.blob ? [h("img", { class: "preview-img", src: panel.blob, alt: file.name })] : [h("p", { class: "panel-note", text: "Loading…" })];
  } else if (file.kind === "pdf" || file.kind === "video") {
    body = panel.blobs.length ? [h("div", { class: "page-images" }, panel.blobs.map((url, i) => h("img", { class: "preview-img", src: url,
      alt: `${file.kind === "pdf" ? "page" : "still"} ${i + 1}` })))] : [h("p", { class: "panel-note", text: "No preview: the router made no page images or stills for this file." })];
  } else {
    body = [h("p", { class: "panel-note", text: "No preview." })];
  }
  if (panel.truncated) body.unshift(h("p", { class: "panel-note", text: `Showing the first 2 MB of ${humanSize(Number(panel.truncated))}.` }));
  if ((panel.tab === "preview" || panel.tab === "source") && file.path && file.path.startsWith("tasks/")) {
    body.push(h("p", { class: "panel-note", text: `Round file ${file.path}` }));
  }
  setChildren(node, head, h("div", { class: "panel-body" }, body));
}

function renderMemoryPanel(node, panel) {
  const task = taskById(panel.taskId) || { n: "?" };
  const show = state.shows.get(panel.taskId);
  const view = memoryDrawer(task, show);
  const given = fromGiven(show);  // brief 33 (decision 12): the block as sent
  const earlier = given ? [h("div", { class: "panel-sub-head", text: given.head }),
    h("div", { class: "mem-entry" }, h("div", { class: "mem-text", text: given.text }))] : [];
  const head = h("div", { class: "panel-head" }, h("div", { class: "panel-row" },
    h("span", { class: "file-icon text" }, icon("chat")),
    h("div", { class: "panel-title" }, h("div", { class: "panel-name", text: "What the agents were given" }),
      h("div", { class: "panel-sub", text: view ? `#${task.n} · ${view.tag}` : `#${task.n}` })),
    h("div", { class: "panel-tools" }, h("button", { class: "icon-btn", type: "button", "aria-label": "Close the panel", onclick: closePanel }, icon("x")))));
  if (!view) {
    setChildren(node, head, h("div", { class: "panel-body" }, earlier, h("p", { class: "panel-note",
      text: show ? "This task has no chat or project, so it carried no memory." : "Loading…" })));
    return;
  }
  const body = [...earlier, h("div", { class: "panel-sub-head", text: `The memory block (${view.given.length}): newest tasks first, then matches newest first` })];
  if (!view.given.length) body.push(h("p", { class: "panel-note", text: "Nothing remembered under this tag went with the build call." }));
  for (const g of view.given) body.push(h("div", { class: "mem-entry" }, h("div", { class: "mem-head", text: g.head }), h("div", { class: "mem-text", text: g.text })));
  body.push(h("div", { class: "panel-sub-head", text: "Each call" }),
    h("div", { class: "timeline wide" }, view.calls.map((c) => h("div", { class: `timeline-row ${c.trimmed ? "warn" : "ok"}` },
      h("span", { class: "light" }), h("span", { class: "what", text: c.who }), h("span", { class: "said", text: c.what })))));
  if (view.handoff) body.push(h("p", { class: "panel-note", text: view.handoff }));
  body.push(h("div", { class: "panel-sub-head", text: "Saved to memory" }),
    view.stored.length ? h("ul", { class: "mem-stored" }, view.stored.map((s) => h("li", { text: s })))
      : h("p", { class: "panel-note", text: "Not saved: a result is saved once it is delivered." }));
  setChildren(node, head, h("div", { class: "panel-body" }, body));
}

function openMemory(task) {
  state.panel = { kind: "memory", taskId: task.task_id };
  renderPanel();
}

async function loadRunsNow() {
  try {
    state.runs = (await api("/api/runs")).runs || [];
  } catch (e) {
    state.runs = [];
  }
  if (state.panel && state.panel.tab === "runlog") renderPanel();
}

async function runAgain(task, team) {
  // brief 29.1 (decision 7c): its own request, as Route it builds one; the composer is never touched; one send per card
  const key = `again-${task.task_id}`;
  if (state.routing.has(key)) return;
  const found = runAgainRequest(task, team, againUi(), state.status, state.routeItSkills.get(key) || null);
  if (found.pick.needed && !found.pick.chosen) { toast(found.pick.why); return; }
  state.routing.add(key);
  renderStream({ follow: false });
  try {
    const started = await api("/api/run", { method: "POST", body: found.request });
    state.pending.push({ run_id: started.run_id, pid: started.pid, text: task.text, team, display: started.copy || started.display });
  } catch (e) {
    state.refused.push({ id: `local-${Date.now()}`, display: "", envelope: { message: e.message }, exit: null });
  } finally {
    state.routing.delete(key);
  }
  renderStream({ follow: false });
  schedulePoll(800);
}

// ---------- actions ----------

function setTeam(team) {
  state.team = team;
  state.skill = null;  // UI A row 1 (A13): back to Auto
  if (team !== "route") { state.web = false; }
  if (team !== "plan" && !state.from) state.fillPlaceholder = null;  // brief 33.2: Plan again's placeholder goes with Plan
  // brief 33.3: a choice for an agent the team doesn't use is dropped (the router would refuse it)
  state.models = pruneModels(state.models, state.status, team, { project: state.project === NEW_PROJECT ? null : state.project });
  if (team === "split") { state.quick = false; state.files = []; }  // brief 29: a split carries neither
  refreshCommand();
  renderComposer();
}

function newChat() {
  state.view = "chat";
  state.chatDraft = "";
  state.skill = null;  // UI A row 1 (A13)
  state.navOpen = false;
  state.chat = newChatName();
  state.project = null;
  state.quick = false;
  state.team = "route";
  state.slots = {};
  state.sessionTasks = [];
  render();
  refreshCommand();
  $("prompt").focus();
}

function openHistory() {
  state.view = "history";
  state.navOpen = false;
  state.menu = null;
  render();
  return loadHistory();
}

function openLogFiles() {
  state.view = "logfiles";
  state.navOpen = false;
  state.menu = null;
  render();
  loadLogFiles();
}

async function loadHistory({ more = false, quiet = false } = {}) {
  const query = state.historyQuery;
  try {
    const doc = await api(historyPath(query, more ? state.historyNext : null));
    if (query !== state.historyQuery) return;  // a newer filter or search is on its way
    if (more) {
      state.historyTasks = mergeTasks(doc.tasks, state.historyTasks);
      state.historyNext = doc.next_before;
      state.historyPages += 1;
    } else if (quiet) {
      state.historyTasks = mergeTasks(state.historyTasks, doc.tasks);  // a poll: the first page again, older pages kept
      if (state.historyPages === 1) state.historyNext = doc.next_before;
    } else {
      state.historyTasks = mergeTasks([], doc.tasks);
      state.historyNext = doc.next_before;
      state.historyPages = 1;
    }
    state.historyError = null;
  } catch (e) {
    state.historyError = e.message;
  }
  if (state.view === "history") renderStream({ follow: !more });
}

async function loadLogFiles({ more = false } = {}) {
  try {
    const doc = await api(`/api/logfiles${more && state.logNext ? `?before=${encodeURIComponent(state.logNext)}` : ""}`);
    state.logFolders = more ? state.logFolders.concat(doc.folders) : doc.folders;
    state.logNext = doc.next_before;
    state.logError = null;
  } catch (e) {
    state.logError = e.message;
  }
  if (state.view === "logfiles") renderStream({ follow: false });
}

function tilde(path) {
  return String(path || "").replace(/^\/Users\/[^/]+/, "~");
}

async function openDoc(title, sub, url) {
  const panel = { kind: "doc", title, sub, url, text: null, error: null, tab: "preview", truncated: null };
  state.panel = panel;
  renderPanel();
  renderStream({ follow: false });
  try {
    const resp = await api(url, { raw: true });
    if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).error || `HTTP ${resp.status}`);
    panel.truncated = resp.headers.get("X-SR-Truncated");
    panel.text = await resp.text();
  } catch (e) {
    panel.error = e.message;
  }
  if (state.panel === panel) renderPanel();
}

function openText(task, who) {
  // a huge result opens whole in the side panel (Preview and Source), never inline in the stream
  const panel = { kind: "doc", title: `#${task.n} · the whole result`, sub: who, url: null, text: task.result, error: null,
    tab: "source", truncated: null };
  state.panel = panel;
  renderPanel();
  renderStream({ follow: false });
}

function openReport() {
  openDoc("The report", tilde((state.status || {}).report_path), "/api/report");
}

function openHandoff(name) {
  openDoc(`HANDOFF.md · ${name}`, "read-only: the router writes it", `/api/handoff/${encodeURIComponent(name)}`);
}

function renderDocPanel(node, panel) {
  const tools = [];
  if (panel.text != null) tools.push(h("button", { class: "icon-btn", type: "button", "aria-label": "Copy the text",
    onclick: async () => { try { await navigator.clipboard.writeText(panel.text); toast("Copied."); } catch (e) { toast("Copy is blocked in this browser."); } } }, icon("copy")));
  tools.push(h("button", { class: "icon-btn", type: "button", "aria-label": "Close the panel", onclick: closePanel }, icon("x")));
  const head = h("div", { class: "panel-head" },
    h("div", { class: "panel-row" }, h("span", { class: "file-icon text" }, icon("book")),
      h("div", { class: "panel-title" }, h("div", { class: "panel-name", text: panel.title }), h("div", { class: "panel-sub", text: panel.sub || "" })),
      h("div", { class: "panel-tools" }, tools)),
    h("div", { class: "tabs", role: "tablist", "aria-label": "View" }, [["preview", "Preview"], ["source", "Source"]].map(([key, label]) => h("button", {
      class: "tab", type: "button", role: "tab", "aria-selected": panel.tab === key ? "true" : "false",
      onclick: () => { panel.tab = key; renderPanel(); } }, label))));
  let body;
  if (panel.error) body = [h("p", { class: "panel-note", text: panel.error })];
  else if (panel.text == null) body = [h("p", { class: "panel-note", text: "Loading…" })];
  else body = [panel.tab === "source" ? codeView(panel.text) : h("div", { class: "result" }, renderMarkdown(panel.text))];
  if (panel.truncated) body.unshift(h("p", { class: "panel-note", text: `Showing the first 2 MB of ${humanSize(Number(panel.truncated))}.` }));
  const marks = panel.project ? stopHereList(panel) : null;  // brief 34 (decision 13): above docs/PLAN.md's text
  setChildren(node, head, marks, h("div", { class: "panel-body" }, body));
}

// ---------- the New project sheet (brief 26, decisions 10–14) ----------
// Built once, then painted in place, so typing keeps its focus and caret. The router answers every question: the
// folder check is its dry run, the command line comes from the server's builder, and Create runs `sr project new`.

const NP_CHECK_MS = 160;   // like the command line: ask once typing stops
const NP_WAIT_MS = 5000;   // a dry run this slow is said so; Create stays off until it answers
const NP_POLL_MS = 400;    // a create is quick: watch its run closely
const NP_RUN_LIMIT_MS = 125 * 1000;  // the server gives a command 120 s
const SUGGEST_RUN_LIMIT_MS = 30 * 60 * 1000;  // brief 33.4: a suggest is one model call, long past any time limit
let npCheckTimer = null;
let npWaitTimer = null;
let npCommandTimer = null;

function openNewProject() {
  if (state.navOpen) toggleNav(false);
  state.np = { raw: "", notes: "", check: null, error: null, waited: false, seq: 0, commandSeq: 0, running: false,
    failure: null, mode: "blank" };  // brief 33.4 (decision 15): Blank or From an idea
  state.sheetKind = "newproject";
  const name = h("input", { class: "np-input", id: "np-name", type: "text", placeholder: "e.g. Price Tracker", autocomplete: "off",
    spellcheck: "false", "aria-describedby": "np-hint", oninput: (e) => onNpName(e.target.value),
    onkeydown: (e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); createProject(); } } });
  const notes = h("textarea", { class: "np-notes", id: "np-notes", rows: "5", maxlength: String(NOTES_MAX), spellcheck: "true",
    "aria-describedby": "np-notes-hint", placeholder: "What it is:\nStack:\nWhere things are:\nDecided so far:",
    oninput: (e) => { state.np.notes = e.target.value; state.np.failure = null; paintNewProject(); refreshNpCommand(); } });
  const sheet = h("div", { class: "sheet np", id: "np-sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "np-title" },
    h("div", { class: "sheet-head" }, h("span", { class: "sheet-title", id: "np-title", text: "New project" }),
      h("button", { class: "icon-btn", type: "button", "aria-label": "Close", onclick: closeSheet }, icon("x"))),
    h("p", { class: "panel-note", text: "Every task you send in a project carries its notes file, HANDOFF.md. With git, Claude works on a copy of the project's committed files, and you land each change as one commit." }),
    h("div", { class: "np-mode", role: "group", "aria-label": "How the project starts" },
      [["blank", "Blank"], ["idea", "From an idea"]].map(([mode, words]) => h("button", { class: "btn np-mode-btn", type: "button", id: `np-mode-${mode}`,
        onclick: () => { state.np.mode = mode; state.np.failure = null; paintNewProject(); refreshNpCommand(); } }, words))),
    h("div", { class: "np-field" }, h("label", { class: "np-label", for: "np-name", text: "Name" }), name,
      h("div", { class: "np-hint", id: "np-hint" })),
    h("div", { class: "np-folder tone-muted", id: "np-folder", role: "status", "aria-live": "polite" }),
    h("div", { class: "np-field" },
      h("label", { class: "np-label", for: "np-notes" }, h("span", { id: "np-notes-label", text: "Starting notes" }),
        h("span", { class: "np-opt", id: "np-notes-opt", text: "optional" }), h("span", { class: "np-count", id: "np-notes-count", hidden: true })), notes,
      h("div", { class: "np-hint", id: "np-notes-hint" })),
    h("div", { class: "np-hint", id: "np-does", text: "Create makes the folder, its HANDOFF.md with your notes, and git's first commit." }),
    commandLine("np-cmd"),
    h("div", { class: "np-other", text: otherFolderHint((state.status || {}).projects_root) }),  // brief 28 (decision 20c)
    h("div", { class: "np-failure", id: "np-failure", role: "alert", hidden: true }),
    h("div", { class: "np-foot" }, h("span", { class: "np-foot-note", id: "np-foot-note" }),
      h("button", { class: "btn", type: "button", onclick: closeSheet }, "Cancel"),
      h("button", { class: "btn btn-primary", type: "button", id: "np-create", disabled: true, onclick: createProject }, "Create project")));
  setChildren($("sheet"), sheet);
  $("sheet").hidden = false;
  paintNewProject();
  refreshNpCommand();
  name.focus();
}

function npView() {
  const np = state.np;
  const status = state.status || {};
  const name = projectSlug(np.raw);
  const taken = (status.projects || []).find((p) => p.name === name) || null;
  const view = newProjectView(np.check, { name, root: status.projects_root || "~/Projects", taken, running: np.running,
    waited: np.waited, error: np.error, demo: state.demo, typed: !!np.raw.trim() });
  return { name, view: np.mode !== "idea" ? view : ideaModeView(view, { idea: np.notes, running: np.running,
    ideaMax: (status.limits || {}).idea_max || 2000, check: np.check && np.check.name === name ? np.check : null }) };
}

function paintNewProject() {
  const np = state.np;
  if (state.sheetKind !== "newproject" || !np || !$("np-sheet")) return;
  const { view } = npView();
  const hint = slugHint(np.raw);
  setChildren($("np-hint"), hint.saved ? ["Saved as ", h("code", { text: hint.saved }), hint.text] : hint.text);
  const folder = $("np-folder");
  folder.className = `np-folder tone-${view.tone}`;
  const git = np.check && np.check.name === projectSlug(np.raw) ? newProjectGitWords(np.check) : null;  // brief 28
  setChildren(folder, icon("folder"), h("span", { class: "np-path", text: view.folder }), h("span", { class: "np-state", text: view.words }),
    view.detail ? h("span", { class: "np-detail", text: view.detail }) : null, git ? h("span", { class: "np-detail", text: git }) : null);
  const notes = $("np-notes");
  if (notes.disabled === view.notesOn) {  // turning off shows the placeholder; turning on brings the typed notes back
    notes.disabled = !view.notesOn;
    notes.value = view.notesOn ? np.notes : "";
  }
  const left = view.notesOn && np.mode !== "idea" ? notesLeftWords(np.notes.length) : null;
  $("np-notes-hint").textContent = left ? `${view.notesHint} ${left}` : view.notesHint;
  // brief 33.4 (decision 15): the switch, the relabelled box and its live counter
  for (const mode of ["blank", "idea"]) {
    const on = np.mode === mode;
    $(`np-mode-${mode}`).classList.toggle("is-on", on);
    $(`np-mode-${mode}`).setAttribute("aria-pressed", on ? "true" : "false");
  }
  $("np-notes-label").textContent = view.label || "Starting notes";
  $("np-notes-opt").hidden = !!view.required;
  const counter = $("np-notes-count");
  counter.hidden = !view.counter;
  counter.textContent = view.counter || "";
  counter.classList.toggle("is-over", !!view.over);
  const create = $("np-create");
  create.textContent = view.button;
  create.disabled = !view.canCreate;
  $("np-foot-note").textContent = view.foot || "";
  const failure = $("np-failure");
  const fresh = !!np.failure && failure.hidden;
  failure.hidden = !np.failure;
  if (np.failure) {
    setChildren(failure, h("div", { class: "np-failure-title", text: np.failure.title }),
      h("div", { class: "np-failure-text", text: np.failure.message }),
      np.failure.exit != null ? h("div", { class: "np-failure-exit", text: `exit ${np.failure.exit}${np.failure.code ? ` · ${np.failure.code}` : ""}` }) : null);
    // break-ui: the sheet scrolls, so a refusal could land out of sight and Create would seem to do nothing
    if (fresh) failure.scrollIntoView({ block: "nearest" });
  }
}

function onNpName(raw) {
  const np = state.np;
  np.raw = raw;
  np.failure = null;
  np.error = null;
  np.waited = false;
  paintNewProject();
  refreshNpCommand();
  clearTimeout(npCheckTimer);
  clearTimeout(npWaitTimer);
  const name = projectSlug(raw);
  if (!name) return;
  npCheckTimer = setTimeout(() => askProjectCheck(np, name), NP_CHECK_MS);
}

async function askProjectCheck(np, name) {
  const seq = ++np.seq;
  const current = () => state.np === np && np.seq === seq;
  clearTimeout(npWaitTimer);
  npWaitTimer = setTimeout(() => { if (current()) { np.waited = true; paintNewProject(); } }, NP_WAIT_MS);
  try {
    const doc = await api(`/api/project-check?name=${encodeURIComponent(name)}`);
    if (!current()) return;  // a stale answer is dropped
    Object.assign(np, { check: doc, error: null, waited: false });
  } catch (e) {
    if (!current()) return;
    np.error = (e.doc && e.doc.message) || e.message;
  }
  clearTimeout(npWaitTimer);
  paintNewProject();
  refreshNpCommand();
}

async function fillDraftIt(name) {
  // brief 33.4 (decisions 7 and 15): Draft it, from the router's own chip (the Spec section's): Route, the project, the Text
  // only pill and its text in the composer. The owner presses Send.
  try {
    const chip = draftChipOf(await api(`/api/project-spec?name=${encodeURIComponent(name)}`));
    if (chip && state.project === name) useChip(chip, { n: null });
  } catch (e) {
    toast(`Couldn't fill Draft it: ${e.message}`);
  }
}

function npRequest() {
  const { name, view } = npView();
  return { action: "project_new", name, notes: view.notesOn ? state.np.notes : "" };
}

function refreshNpCommand() {
  // UI B N10: no command shown; the server's builder is asked so a refused one still says why
  clearTimeout(npCommandTimer);
  npCommandTimer = setTimeout(() => {
    const np = state.np;
    if (!np) return;
    const request = npRequest();
    if (state.demo || !request.name) { paintCommand("np-cmd", null); return; }
    np.builder = np.builder || {};
    askCommand("np-cmd", request, np.builder);
  }, NP_CHECK_MS);
}

async function npWaitRun(runId, limit = NP_RUN_LIMIT_MS) {
  const until = Date.now() + limit;
  while (Date.now() < until) {
    await new Promise((resolve) => setTimeout(resolve, NP_POLL_MS));
    try {
      const run = ((await api("/api/runs")).runs || []).find((r) => r.id === runId);
      if (!run) return null;
      if (!run.running) return run;
    } catch (e) {
      // the next look tries again
    }
  }
  return null;
}

async function createProject() {
  const np = state.np;
  if (!np) return;
  const { name, view } = npView();
  if (!view.canCreate) return;
  const request = npRequest();
  np.running = true;
  np.failure = null;
  paintNewProject();
  let run = null;
  try {
    const started = await api("/api/run", { method: "POST", body: request });
    run = await npWaitRun(started.run_id);
  } catch (e) {
    np.running = false;
    np.failure = { title: "Not run", message: e.message, exit: null, code: null };
    paintNewProject();
    return;
  }
  np.running = false;
  const env = (run && run.envelope) || {};
  const code = run ? (run.exit == null ? env.exit : run.exit) : null;
  if (code === 0) {
    state.madeProjects.add(name);
    await loadStatus();  // the server dropped its kept status, so this read is fresh
    const fromIdea = np.mode === "idea";
    if (state.np === np) closeSheet();
    openProject(name);
    toast(projectToast(env) || `Created ${name}`);
    if (fromIdea) await fillDraftIt(name);  // brief 33.4 (decision 15): fills Draft it; nothing is sent
    return;
  }
  np.failure = run ? { title: code === 2 ? "The router refused this" : "This stopped part way",
    message: env.message || run.message || run.stderr || "The command ended without an answer.", exit: code, code: env.reason_code || null }
    : { title: "No answer", message: "The page lost track of the command. Reload to see whether the project was made.", exit: null, code: null };
  if (state.np === np) {
    paintNewProject();
    askProjectCheck(np, name);  // the folder may have changed: ask again
  } else {
    toast(np.failure.message);
  }
}

// ---------- the Setup sheet ----------

async function openSetup(focus = null) {
  // UI B N5: the first-run card's and the popover's links: the tab, at the section holding that row
  state.setupFocus = focus;
  state.setupOpen = new Map();  // brief 27: each opening starts from the defaults
  return openSettings(settingsTabFor(focus));
}

const SETTINGS_TABS = [["setup", "Setup"], ["history", "History"], ["notes", "Router notes"], ["models", "Models"], ["memory", "Memory"]];
const SINGLE_ROW_TABS = ["notes", "models", "memory"];

function localClock(iso) {
  const d = new Date(iso || "");
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" });
}

function setupRowOpen(row) {
  // brief 27 (the owner's choice 8): a row keeps the open state it was given while the sheet is up; the defaults (a
  // setup problem, or the row asked for) apply when the sheet opens. Memory's default: open only when not installed.
  if (state.setupOpen.has(row.key)) return state.setupOpen.get(row.key);
  if (state.setupFocus === row.key) return true;
  if (SINGLE_ROW_TABS.includes(row.key)) return true;  // UI B N5: the row is its tab's whole page
  return row.tone === "bad" || row.tone === "muted";
}

function renderSetup() {
  if (state.view === "settings") renderStream({ follow: false });
}

function settingsRow(row, sections) {
  // each row by its key, keeping its id and its body (decision 11: the switch sits outside <summary>)
  if (row.key === "memory" && state.memRun && state.memRun.to === "on") Object.assign(row, memoryView(null, { turningOn: true }));
  const view = row.key === "memory" ? memorySwitchView(state.status && state.status.memory, state.memRun, state.memFailure) : null;
  const details = h("details", {
    class: `setup-row tone-${row.tone}`, id: `setup-${row.key}`, open: setupRowOpen(row) ? true : null,
    ontoggle: (e) => state.setupOpen.set(row.key, e.target.open) },
  h("summary", {}, h("span", { class: "light", "aria-hidden": "true" }), h("span", { class: "setup-name", text: row.name }),
    h("span", { class: "setup-state", text: row.state }), row.detail ? h("span", { class: "setup-detail", text: row.detail }) : null,
    row.checkedAt ? h("span", { class: "setup-checked", text: `checked ${localClock(row.checkedAt)}` }) : null),
  row.without ? h("p", { class: "setup-without", text: `Without it: ${row.without}` }) : null,
  view ? memoryNote(view) : null,
  h("div", { class: "setup-body result" }, sections[row.name] ? renderMarkdown(sections[row.name])
    : h("p", { class: "panel-note", text: state.setupText != null ? "No section for it in docs/SETUP.md."
      : state.setupError ? `The steps couldn't be read: ${state.setupError}` : "Loading the steps…" })));
  if (row.key === "models") {  // brief 33.3 (decision 12): the defaults read only, the selects and the Fable switch, in the body
    details.insertBefore(modelsRowBody(state.status), details.lastElementChild);
    return details;
  }
  if (row.key === "notes") {  // brief 30 (decision 10): the router notes' Edit, outside the summary as the switch is
    return h("div", { class: "setup-row-wrap" }, details, h("div", { class: "mem-switch-wrap" },
      h("button", { class: "btn", type: "button", id: "notes-edit", disabled: state.restarted,
        title: "Edit the router notes: sent first with every agent call", onclick: openNotesEditor }, "Edit")));
  }
  return view ? h("div", { class: "setup-row-wrap" }, details, memorySwitch(view)) : details;
}

function settingsSetup(rows, sections) {
  // the rows but the three with a tab of their own, Check again, then Notifications and Theme (from the sidebar's old foot)
  const notify = notifyState();
  const checked = rows.map((r) => r.checkedAt).filter(Boolean).sort().at(-1);
  return [h("div", { class: "settings-line" }, h("p", { class: "panel-note", text: "Each piece's live state beside its steps. The steps are for Terminal; the page runs two things here: the Memory switch and the Router notes editor." }),
    h("span", { class: "sheet-sub", text: checked ? `checked ${localClock(checked)}` : "" }),
    h("button", { class: "btn", type: "button", id: "check-again", disabled: state.setupChecking || state.demo || state.restarted,
      title: state.demo ? "Demo: nothing runs." : "Ask the router for a fresh status (kept for 10 s)", onclick: checkAgain },
    state.setupChecking ? "Checking…" : "Check again")),
  state.setupError ? h("p", { class: "missing", text: state.setupError }) : null,
  h("div", { class: "setup-rows" }, rows.filter((r) => !SINGLE_ROW_TABS.includes(r.key)).map((row) => settingsRow(row, sections))),
  h("div", { class: "settings-prefs" },
    notify ? h("button", { class: "side-item", type: "button", id: "settings-notify", title: "A desktop notification when a task needs you", onclick: askNotify },
      icon("alert"), h("span", { class: "name", text: notify === "granted" ? "Notifications: on" : notify === "denied" ? "Notifications: blocked" : "Notify me when a task needs me" })) : null,
    h("button", { class: "side-item", type: "button", id: "settings-theme", title: "Light or dark", onclick: cycleTheme },
      icon("moon"), h("span", { class: "name", text: `Theme: ${state.theme}` })))];
}

function settingsHistory() {
  // All tasks, Log files and Read the report, with today's handlers; each opens its own view
  const status = state.status || {};
  const row = (name, sub, iconName, onclick, title = null) => h("button", { class: "side-item settings-link", type: "button", title, onclick },
    icon(iconName), h("span", { class: "settings-link-words" }, h("span", { class: "name", text: name }), h("span", { class: "setup-detail", text: sub })));
  return h("div", { class: "settings-history" },
    row("All tasks", "every task, by chat or project, search", "clock", openHistory, "Every task: by chat or project, search, older pages"),
    row("Log files", "every call's output, as #n · its run id", "file", openLogFiles, "Every call's output: the tasks/ folder, newest first"),
    status.report_path ? row("Read the report", tilde(status.report_path), "book", openReport, tilde(status.report_path)) : null);
}

function memoryControl() {
  // UI B N8 (Q3): a plain link, a fixed line and the start command to copy. No detection (the page's connect-src is itself),
  // and the page never starts it. The address and the command sit in index.html as markup: this script names no address
  // (tests/test_page.py), and a link loads nothing
  const start = $("control-start").textContent;
  return h("div", { class: "mem-control" },
    h("a", { href: $("control-page").getAttribute("href"), target: "_blank", rel: "noopener noreferrer", text: "Open Hindsight's control page ↗" }),
    h("p", { class: "panel-note", text: "Works while Hindsight's control page is running" }),
    h("div", { class: "pc-code mem-control-start" }, h("span", { text: start }),
      h("button", { class: "icon-btn", type: "button", "aria-label": "Copy the start command", onclick: async () => {
        try { await navigator.clipboard.writeText(start); toast("Copied."); } catch (e) { toast("Copy is blocked in this browser."); }
      } }, icon("copy"))));
}

function settingsView(head) {
  const tab = state.settingsTab || "setup";
  const sections = setupSections(state.setupText || "").sections;
  const rows = setupRows(state.status);
  head.append(h("span", { class: "stream-title", text: "Settings" }),
    h("div", { class: "tabs settings-tabs", role: "tablist", "aria-label": "Settings" }, SETTINGS_TABS.map(([key, label]) => h("button", {
      class: "tab", type: "button", role: "tab", id: `settings-tab-${key}`, "aria-selected": key === tab ? "true" : "false",
      onclick: () => { state.settingsTab = key; renderStream({ follow: false }); document.scrollingElement.scrollTop = 0; } }, label))));
  const one = (key) => rows.filter((r) => r.key === key).map((row) => settingsRow(row, sections));
  const body = tab === "setup" ? settingsSetup(rows, sections) : tab === "history" ? settingsHistory()
    : tab === "memory" ? [one(tab), memoryControl()] : one(tab);
  return [head, h("div", { class: "settings-page", role: "tabpanel", "aria-labelledby": `settings-tab-${tab}` }, body)];
}

// ---------- the Models sheet and Setup's Models row (brief 33.3, decisions 6, 11 and 12) ----------

function modelsMenuButton(status) {
  const item = modelsMenuItem(status);
  return h("button", { class: "team-item models-item", type: "button", role: "menuitem", "aria-disabled": item.disabled ? "true" : null,
    title: item.reason || item.title,
    onclick: (e) => { e.stopPropagation(); if (item.disabled) { toast(item.reason); return; } state.teamMenu = false; renderTeam(); openModelsSheet(); } },
  h("span", { class: "name", text: item.label }), h("span", { class: "key", text: "/model" }));
}

function openModelsSheet() {
  if (state.navOpen) toggleNav(false);
  state.modelsSheet = { team: state.team };
  state.sheetKind = "models";
  paintModelsSheet();
  $("sheet").hidden = false;
  const first = document.querySelector("#models-sheet select");
  if (first) first.focus();
}

function paintModelsSheet() {
  if (state.sheetKind !== "models") return;
  const project = state.project === NEW_PROJECT ? null : state.project;
  const view = modelsSheetView(state.status, state.team, state.models || {}, { project });
  const sheet = h("div", { class: "sheet np models-sheet", id: "models-sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "models-title" },
    sheetHead("models-title", view.title, closeSheet),
    // break-ui: "--model" broke at its hyphen ("-" / "-model"); the flag sits in its own unbreakable span
    h("p", { class: "panel-note" }, "Each agent's model on this task. Defaults keeps what the router would use now; a choice goes as ",
      h("code", { class: "nowrap", text: "--model" }), " and shows as a pill in the composer."),
    view.note ? h("p", { class: "panel-note", text: view.note }) : null,
    view.why ? h("p", { class: "missing", text: view.why }) : null,
    view.agents.map((a) => h("div", { class: "models-agent" },
      h("label", { class: "models-agent-row", for: `model-${a.agent}` },
        h("span", { class: "models-agent-name", text: a.label }),
        h("select", { class: "select", id: `model-${a.agent}`, "aria-label": `${a.label}'s model on this task`,
          onchange: (e) => chooseModel(a.agent, e.target.value) },
        a.options.map((o) => h("option", { value: o.value, disabled: o.disabled, selected: o.selected, title: o.reason }, o.label)))),
      h("div", { class: "models-defaults", text: `Defaults now: ${a.defaults}` }))),
    view.fableOff ? h("p", { class: "np-hint", text: fableOffWords(state.status && state.status.models) }) : null,
    h("div", { class: "np-foot" }, h("span", { class: "np-foot-note", text: state.demo ? "Demo: a choice is shown, never sent." : "" }),
      h("button", { class: "btn", type: "button", onclick: closeSheet }, "Done")));
  setChildren($("sheet"), sheet);
}

function chooseModel(agent, value) {
  const next = { ...(state.models || {}) };
  if (value) next[agent] = value; else delete next[agent];
  state.models = Object.keys(next).length ? next : null;
  const keep = document.activeElement && document.activeElement.id;
  refreshCommand();
  renderComposer();
  paintModelsSheet();
  const again = keep && $(keep);
  if (again && again !== document.activeElement) again.focus({ preventScroll: true });
}

function clearModel(agent) {
  chooseModel(agent, "");
}

function modelsRowBody(status) {
  // decision 12: the Models row's body: each agent's default read only with its file, Claude's counts, the selects (one per
  // skill, one per team, role and agent), the router's last answer, then the Fable switch with its words
  const models = status && status.models;
  const selects = modelsSetupSelects(status);
  const view = fableSwitchView(models, state.fableRun, state.fableFailure);
  const busy = !!state.modelsRun;
  const agentLines = Object.entries((models && models.agents) || {}).map(([agent, doc]) =>
    `${agentLabel(agent)}: ${doc.name ? `${doc.name} (${doc.default})` : doc.default || "no default"} · ${doc.file}`);
  // UI B row 14 (board 3): the slip of 30 Oct, a change landing on the row below: a row is read first, its select stays behind
  // Change, one opens at a time and names itself, and the router's answer sits on the row it changed
  const said = state.modelsSaid;
  const saidOn = (id) => (said && said.key === id ? h("div", { class: said.code === 0 ? "np-hint models-said ok" : "np-failure models-said", role: "status" },
    said.code === 0 ? null : h("div", { class: "np-failure-title", text: "The router refused this" }),
    h("div", { class: said.code === 0 ? null : "np-failure-text", text: said.message }),
    said.code != null && said.code !== 0 ? h("div", { class: "np-failure-exit", text: `exit ${said.code}` }) : null) : null);
  const line = (row, id) => (state.modelsOpen === id
    ? h("div", { class: "models-row open" }, h("div", { class: "models-row-title", text: `Change ${row.label}` }),
      h("div", { class: "models-row-pick" },
        h("select", { class: "select setup-model-select", id, "aria-label": `${row.label}: model`, disabled: busy || state.demo || state.restarted,
          title: state.demo ? "Demo: nothing runs." : "Sets it at once",
          onchange: (e) => setModelDefault(row, e.target.value, id) },
        row.options.map((o) => h("option", { value: o.value, disabled: o.disabled, selected: o.selected, title: o.reason }, o.label))),
        h("button", { class: "btn btn-quiet", type: "button", onclick: () => { state.modelsOpen = null; renderSetup(); } }, "Cancel")),
      h("div", { class: "np-hint", text: `Picking a model sets ${row.label} at once. A refusal keeps it as it was.` }), saidOn(id))
    : h("div", { class: "models-row" }, h("div", { class: "models-row-line" }, h("span", { class: "models-row-name", text: row.label }),
      h("span", { class: "models-row-now", text: row.current }), row.yours ? h("span", { class: "models-yours", text: "yours" }) : null,
      !row.state || row.state === "choice" ? h("button", { class: "btn btn-quiet btn-small", type: "button", dataset: { focusKey: `models-change-${id}` }, title: `Change ${row.label}`,
        onclick: () => { state.modelsOpen = id; state.modelsSaid = null; renderSetup(); } }, "Change") : null),
    (row.unused || []).map((pick) => h("div", { class: "models-unused" }, h("span", { class: "np-hint", text: unusedPickWords(pick) }),
      h("button", { class: "btn btn-quiet btn-small", type: "button", disabled: busy || state.restarted, dataset: { focusKey: `models-clear-${id}-${pick.agent}` },
        title: `Clear your earlier pick for ${agentLabel(pick.agent)}`, onclick: () => setModelDefault({ ...row, agent: pick.agent }, "", id) }, "Clear"))),
    saidOn(id)));
  const skillId = (row) => `models-skill-${row.key}`;
  const roleId = (row) => `models-role-${row.team}-${row.role}-${row.agent}`;
  const stageId = (row) => `models-stage-${row.team}-${row.stage}-${row.agent}`;
  const skills = modelRows(selects.skills);
  const roles = modelRows(selects.roles, { keep: 0 });
  const stages = modelRows(selects.stages, { keep: 0 });
  const ofYours = (k) => (k ? ` · ${k} of your own` : "");
  const folded = (key, title, rows, idOf) => (rows.length ? h("details", { class: "models-fold", open: state.modelsFolds.has(key) || rows.some((r) => idOf(r) === state.modelsOpen || (said && idOf(r) === said.key)) ? true : null,
    ontoggle: (e) => { if (e.target.open) state.modelsFolds.add(key); else state.modelsFolds.delete(key); } },
  h("summary", { text: title }), rows.map((row) => line(row, idOf(row)))) : null);
  return h("div", { class: "setup-models", id: "setup-models" },
    h("div", { class: "setup-models-title", text: "Each agent's default, read only, with its file:" }),
    h("ul", { class: "setup-models-agents" }, agentLines.map((text) => h("li", { text }))),
    claudeCallsThisWeek(models) ? h("div", { class: "setup-models-counts", text: `Claude this week: ${claudeCallsThisWeek(models)}` }) : null,
    h("div", { class: "setup-models-title", text: "Your own defaults. Each change runs at once; a refusal keeps it as it was." }),
    h("div", { class: "models-section-title", text: `Skills${ofYours(skills.yours)}` }),
    skills.shown.map((row) => line(row, skillId(row))),
    folded("skills", `${skills.more.length} more skills`, skills.more, skillId),
    folded("roles", `Team roles${ofYours(roles.yours)}`, roles.more, roleId),
    folded("stages", `Team stages${ofYours(stages.yours)}`, stages.more, stageId),
    h("div", { class: "fable-row" }, fableSwitch(view),
      h("div", { class: "fable-words" }, h("p", { text: view.words }),
        view.offBy ? h("p", { class: "mem-still", text: view.offBy }) : null,
        view.fallback ? h("p", { text: view.fallback }) : null,
        view.failure ? h("div", { class: "np-failure", role: "alert" }, h("div", { class: "np-failure-title", text: "The router refused this" }),
          h("div", { class: "np-failure-text", text: view.failure.message }),
          view.failure.exit != null ? h("div", { class: "np-failure-exit", text: `exit ${view.failure.exit}` }) : null) : null)));
}

function fableSwitch(view) {
  return h("button", { class: `mem-switch fable-switch${view.on ? " on" : ""}${view.busy ? " busy" : ""}`, type: "button", role: "switch", id: "fable-switch",
    "aria-checked": view.on ? "true" : "false", "aria-label": "Fable 5.1", "aria-busy": view.busy ? "true" : null,
    "aria-disabled": view.disabled ? "true" : null, title: `Runs sr models fable ${view.to}`, onclick: flipFable },
  h("span", { class: "mem-switch-label", text: `Fable ${view.label}` }),
  h("span", { class: "mem-switch-track", "aria-hidden": "true" }, h("span", { class: "mem-switch-knob" })));
}

async function runSafely(request) {
  try {
    return await runProjectAction(request);
  } catch (e) {
    return { run: null, env: {}, code: null, message: e.message };
  }
}

async function flipFable() {
  const view = fableSwitchView(state.status && state.status.models, state.fableRun, state.fableFailure);
  if (view.disabled) return;  // a double click, or a click while a run goes: one run at a time
  if (state.demo) { toast("Demo: nothing runs."); return; }
  state.fableRun = { to: view.to, started: Date.now() };
  state.fableFailure = null;
  renderSetup();
  const result = await runSafely({ action: "models_fable", to: view.to });
  if (result.code === 0) await loadStatus();  // the server dropped its kept status when the run ended
  else { state.fableFailure = { exit: result.code, message: result.message }; state.setupOpen.set("models", true); }
  state.fableRun = null;
  render();
}

async function setModelDefault(row, value, key = null) {
  // decision 12: a select change runs `sr models set …` (Default: `clear`) and shows the router's answer; a refusal keeps the
  // select as it was (status didn't change, so the row draws the saved value again)
  if (state.demo) { toast("Demo: nothing runs."); renderSetup(); return; }
  const request = value ? { action: "models_set", selector: row.selector, agent: row.agent, model: value }
    : { action: "models_clear", selector: row.selector, agent: row.agent };
  state.modelsRun = request;
  state.modelsSaid = null;
  renderSetup();
  const result = await runSafely(request);
  state.modelsSaid = { code: result.code, message: result.message, key };  // UI B row 14: it sits on the row it changed
  state.modelsOpen = null;
  if (result.code === 0) await loadStatus();
  state.modelsRun = null;
  state.setupOpen.set("models", true);
  render();
}

// ---------- the Memory switch (brief 27, decisions 10–12; the owner's choice 7) ----------

function memorySwitch(view) {
  return h("div", { class: "mem-switch-wrap" },
    h("button", { class: `mem-switch${view.on ? " on" : ""}${view.busy ? " busy" : ""}`, type: "button", role: "switch", id: "mem-switch",
      "aria-checked": view.on ? "true" : "false", "aria-label": "Memory", "aria-busy": view.busy ? "true" : null,
      // break-ui: aria-disabled, not disabled, so a keyboard user keeps focus on it through the run (flipMemory ignores it)
      "aria-disabled": view.disabled ? "true" : null, title: `Runs sr memory ${view.to}`, onclick: flipMemory },
    h("span", { class: "mem-switch-label", text: view.label }),
    h("span", { class: "mem-switch-track", "aria-hidden": "true" }, h("span", { class: "mem-switch-knob" }))));
}

function memoryNote(view) {
  // UI B N10: the note says what On and Off mean; the switch's command line went (rules proposal)
  return h("div", { class: "mem-note", id: "mem-note" }, h("p", { text: view.words }),
    view.still ? h("p", { class: "mem-still", text: view.still }) : null,
    view.failure ? h("div", { class: "np-failure", role: "alert" }, h("div", { class: "np-failure-title", text: "The router refused this" }),
      h("div", { class: "np-failure-text", text: view.failure.message }),
      view.failure.exit != null ? h("div", { class: "np-failure-exit", text: `exit ${view.failure.exit}` }) : null) : null);
}

async function memWaitRun(runId) {
  // a switch to on waits for the start (up to 180 s) and the backfill: no limit while the server says the run goes
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, 600));
    try {
      const run = ((await api("/api/runs")).runs || []).find((r) => r.id === runId);
      if (!run) return null;
      if (!run.running) return run;
    } catch (e) {
      if (state.restarted) return null;
    }
  }
}

async function flipMemory() {
  const view = memorySwitchView(state.status && state.status.memory, state.memRun, state.memFailure);
  if (view.disabled) return;  // a double click, or a click while a run goes: one run at a time
  if (state.demo) { toast("Demo: nothing runs."); return; }
  state.memRun = { to: view.to, started: Date.now() };
  state.memFailure = null;
  render();
  let run = null, error = null;
  try {
    const started = await api("/api/run", { method: "POST", body: { action: "memory_switch", to: view.to } });
    run = await memWaitRun(started.run_id);
  } catch (e) {
    error = e.message;
  }
  const env = (run && run.envelope) || {};
  const code = run ? (run.exit == null ? env.exit : run.exit) : null;
  if (code === 0) {
    await loadStatus();  // the server dropped its kept status when the run ended: one fresh read (decision 10)
  } else {
    state.memFailure = { exit: code, message: error || env.message || (run && run.stderr) || "The page lost track of the command. Reload to see whether memory switched." };
    state.setupOpen.set("memory", true);  // break-ui: the refusal is in the row's body; a closed row would hide it
  }
  state.memRun = null;
  render();
  const failed = state.memFailure && document.querySelector("#mem-note .np-failure");
  if (failed) failed.scrollIntoView({ block: "nearest" });
}

async function checkAgain() {
  // the server keeps a fresh status for 10 s, so a second press within 10 s reads the kept one (decision 16)
  state.setupChecking = true;
  renderSetup();
  await loadStatus(true);
  state.setupChecking = false;
  renderSetup();
  renderStrip();
  renderSidebar();
  renderStream({ follow: false });
}

function openChat(name) {
  state.view = "chat";
  state.chatDraft = "";
  state.skill = null;  // UI A row 1 (A13)
  state.navOpen = false;
  state.chat = name;
  state.project = null;
  state.quick = false;
  state.team = "route";
  state.slots = {};
  state.sessionTasks = [];
  render();
  refreshCommand();
}

function openProject(name) {
  state.view = "chat";
  state.skill = null;  // UI A row 1 (A13)
  state.navOpen = false;
  state.project = name;
  state.quick = false;
  state.team = "route";
  state.slots = {};
  state.sessionTasks = [];
  render();
  refreshCommand();
  loadWhatNow().then(() => { if (state.project === name) render(); });  // brief 33 (decision 13)
}

function removeFile(path) {
  state.files = state.files.filter((f) => f.path !== path);
  renderComposer();
  refreshCommand();
}

function dismissRefusal(id) {
  state.refused = state.refused.filter((r) => r.id !== id);
  renderStream();
}

function applySlash(atEnd = false) {
  const presetNames = ((state.status && state.status.presets) || []).map((p) => p.name);
  const parsed = parseComposer(state.text, presetNames, { atEnd });
  if (!parsed.slash) return false;
  const { kind, value } = parsed.slash;
  if (kind === "team") setTeam(value);
  else if (kind === "route") setTeam("route");
  else if (kind === "split" || kind === "plan") {  // brief 29: /split picks it, unless status says it can't run; 33.1: /plan
    const chip = chipViews(state.status, state.team, { project: state.project === NEW_PROJECT ? null : state.project })
      .find((c) => c.key === kind);
    if (!chip) toast(`This router has no ${kind}`);
    else if (chip.disabled) toast(chip.reason);
    else setTeam(kind);
  }
  else if (kind === "model") openModelsSheet();  // brief 33.3 (decision 12)
  else if (kind === "quick") state.quick = !state.quick;
  else if (kind === "web" && state.team === "route") state.web = !state.web;
  else if (kind === "file") $("file-input").click();
  else if (kind === "chat" && value) { state.chat = value; state.project = null; state.quick = false; }
  else if (kind === "project" && value) state.project = value;
  state.text = parsed.text;
  $("prompt").value = parsed.text;
  render();
  refreshCommand();
  return true;
}

let commandTimer = null;
function refreshCommand() {
  clearTimeout(commandTimer);
  commandTimer = setTimeout(fetchCommand, 160);
}

async function fetchCommand() {
  if (!state.status || state.restarted) return;
  const seq = ++state.commandSeq;
  const request = sendRequest({ ...state, text: state.text || "…" }, state.status);
  if (state.demo) {
    state.command = { error: null, parts: demoParts(request), display: "" };
    renderCommand();
    return;
  }
  try {
    const found = await api("/api/command", { method: "POST", body: request });
    if (seq !== state.commandSeq) return;
    state.command = found;
  } catch (e) {
    if (seq !== state.commandSeq) return;
    state.command = { error: e.message };
  }
  renderCommand();
}

function demoParts(request) {
  const words = request.team === "route" ? ["sr", "route"] : request.team === "split" ? ["sr", "split"]
    : ["sr", "relay", request.team];  // brief 29
  const parts = words.map((text) => ({ text, added: false }));
  parts.push({ text: "--json", added: true }, { text: "--source", added: true }, { text: "ui", added: true });
  if (request.chat) parts.push({ text: "--chat", added: false }, { text: request.chat, added: false });
  if (request.project) parts.push({ text: "--project", added: false }, { text: request.project, added: false });
  if (request.skill) parts.push({ text: "--skill", added: false }, { text: request.skill, added: false });
  if (request.from) parts.push({ text: "--from", added: false }, { text: request.from, added: false });  // brief 33
  if (request.no_files) parts.push({ text: "--no-files", added: false });  // brief 33.2 (decision 5)
  for (const [agent, model] of Object.entries(request.models || {}).sort()) {  // brief 33.3: as page_commands orders them
    parts.push({ text: "--model", added: false }, { text: `${agent}=${model}`, added: false });
  }
  parts.push({ text: "--", added: false }, { text: shellQuote(request.text), added: false });
  return parts;
}

async function send() {
  applySlash(true);
  const text = state.text;
  if (!text.trim() || state.demo || state.restarted || state.sending) return;
  const pick = skillPick(state, state.status);
  if (pick.needed && !pick.chosen) { toast(pick.why); return; }  // brief 24: without Jev, your skill first
  if (!state.quick && !state.project && !state.chat) state.chat = newChatName();
  const named = projectSlug(state.chatDraft || "");  // Cleanup 2, row 14: a split carries no chat, and a project or Quick send isn't one
  if (named && !state.quick && !state.project && state.team !== "split" && isAutoChatName(state.chat)) {
    state.chat = named;
    state.chatDraft = "";
  }
  const request = sendRequest({ ...state, text }, state.status);
  state.sending = true;
  try {
    const started = await api("/api/run", { method: "POST", body: request });
    state.pending.push({ run_id: started.run_id, pid: started.pid, text, team: state.team, display: started.copy || started.display, skill: request.skill || null });
    state.text = "";
    $("prompt").value = "";
    state.files = [];
    Object.assign(state, { from: null, idea: null, step: null, models: null, fillPlaceholder: null });  // brief 33: the pills went with it
    state.skill = null;  // UI A row 1 (A13): back to Auto
    if (state.view === "settings") state.view = "chat";  // UI B N5: a page with no stream: go where the task is
    autosize();
  } catch (e) {
    state.refused.push({ id: `local-${Date.now()}`, display: "", envelope: { message: e.message }, exit: null });
  } finally {
    state.sending = false;
  }
  render();
  refreshCommand();
  schedulePoll(800);
}

// ---------- polling (decision 16) ----------

let pollTimer = null;
function schedulePoll(ms) {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(poll, ms);
}

let statusAsked = 0;
let statusTaken = 0;
async function loadStatus(fresh = false) {
  const asked = ++statusAsked;
  try {
    const found = await api(fresh ? "/api/status?fresh=1" : "/api/status");
    if (asked < statusTaken) return;  // break-ui: an older read that lands late never undoes a newer one (the switch's)
    statusTaken = asked;
    state.status = found;
    state.statusAt = Date.now();
    state.statusError = null;
  } catch (e) {
    if (e.status !== 403) state.statusError = e.message;
  }
}

async function loadLog() {
  try {
    const doc = await api("/api/log");
    state.tasks = doc.tasks || [];
    state.nextBefore = doc.next_before;
    state.logError = null;
  } catch (e) {
    if (e.status !== 403) state.logError = e.message;
  }
}

const STATUS_CODES = ["probe_failed", "signed_out", "not_configured", "not_live"];
// D6 (the live check, 30 Oct): a card action that moves a project's head or its plan's ticks; the server drops its kept
// status when one ends well (page.DROPS_STATUS), and the page reads it again at once, so the bar's "Plan #n · d of m" is
// current without waiting for the minute's read
export const STATUS_AFTER = ["land", "undo", "discard"];

export function refreshesStatus(item, code) {
  return code === 0 && STATUS_AFTER.includes((item || {}).action);
}

async function loadRuns() {
  if (!state.pending.length && !state.actions.length) return [];
  const finished = [];
  try {
    const runs = (await api("/api/runs")).runs || [];
    const byId = new Map(runs.map((r) => [r.id, r]));
    const acting = [];
    let statusDue = false;
    for (const item of state.actions) {
      const run = byId.get(item.run_id);
      if (!run || run.running) { acting.push(item); continue; }
      finished.push(item.taskId);
      const env = run.envelope || {};
      const code = run.exit == null ? env.exit : run.exit;
      if (refreshesStatus(item, code)) statusDue = true;
      const saved = state.splitEditSaved && state.splitEditSaved.taskId === item.taskId ? state.splitEditSaved : null;
      if (saved) state.splitEditSaved = null;  // brief 29, C4: one run per task, so this one is the edit's
      const planSaved = state.planEditSaved && state.planEditSaved.taskId === item.taskId ? state.planEditSaved : null;
      if (planSaved) state.planEditSaved = null;  // E1: a plan's step edit, the same way
      if (code == null || [1, 2, 130].includes(code)) {
        const view = refusalView(run);
        state.actionErrors.set(item.taskId, { ...view, title: code === 2 ? "The router refused this" : "This ended with an error" });
        if (saved && !state.splitEdit) {  // the refused text opens again, to fix rather than retype, the refusal in it
          const active = document.activeElement;
          const onIt = !active || active === document.body || active.id === `edit-${saved.taskId}-${saved.piece}`;
          state.splitEdit = { ...saved, refused: view.message, focus: onIt };
          state.actionErrors.delete(item.taskId);
        }
        if (planSaved && !state.planEdit) {  // E1 (rules 2.47, the plan on the page): the refused text opens again
          const active = document.activeElement;
          const button = planSaved.field === "done_when" ? `plan-done-${planSaved.taskId}-${planSaved.k}`
            : `plan-edit-${planSaved.taskId}-${planSaved.k}`;
          const onPlan = !active || active === document.body || active.id === button;
          state.planEdit = { ...planSaved, refused: view.message, focus: onPlan };
          state.actionErrors.delete(item.taskId);
        }
        if (STATUS_CODES.includes(env.reason_code)) await loadStatus(true);
      } else if (env.task_id && env.task_id !== item.taskId && !state.sessionTasks.includes(env.task_id)) {
        state.sessionTasks.push(env.task_id);  // a floor answer is a new task: show it here
      }
    }
    state.actions = acting;
    if (statusDue) await loadStatus();  // D6: the server dropped its kept status, so this read is fresh
    const still = [];
    for (const item of state.pending) {
      const run = byId.get(item.run_id);
      if (run && run.task_id) {
        if (item.from) state.routedFrom.set(item.from, { run_id: item.run_id, task_id: run.task_id });  // brief 29.1 (7d)
        if (!state.sessionTasks.includes(run.task_id)) state.sessionTasks.push(run.task_id);
        const task = state.tasks.find((t) => t.task_id === run.task_id);
        if (item.team === "route" && task) state.lastRouteTask = task;
        if (!task) still.push(item);
      } else if (run && !run.running) {
        state.refused.push(run);
        if (STATUS_CODES.includes((run.envelope || {}).reason_code)) await loadStatus(true);
      } else {
        still.push(item);
      }
    }
    state.pending = still;
  } catch (e) {
    // the next poll tries again
  }
  return finished;
}

async function poll() {
  if (state.restarted) return;
  if (Date.now() - state.statusAt >= STATUS_MS) await loadStatus();
  const before = state.tasks;
  await loadLog();
  const acted = await loadRuns();
  if (acted.length) {
    await loadLog();  // an action ended: its rows are written, so the card shows what it did, not the old buttons
    for (const id of acted) if (state.shows.has(id)) state.shows.get(id).updated_at = null;
  }
  if (!state.demo) notifyNew();
  if (state.view === "history") await loadHistory({ quiet: true });
  if (state.project) await loadWhatNow();  // brief 33 (decision 13)
  else if (state.viewRead) await loadViewRead({ quiet: true });  // Cleanup 2, row 1: a chat's own read; a project's is What now?'s
  const onScreen = new Set(streamTasks().map((t) => t.task_id));
  for (const task of viewTasksKnown(state.viewRead, state.tasks)) {  // an older open card keeps updating
    if (onScreen.has(task.task_id) && isOpenTask(task) && state.shows.has(task.task_id)) await loadShow(task.task_id, { quiet: true });
    else if (onScreen.has(task.task_id) && state.shows.has(task.task_id) && state.shows.get(task.task_id).updated_at !== task.updated_at) {
      await loadShow(task.task_id, { quiet: true });
    }
  }
  if (state.lastRouteTask) state.lastRouteTask = state.tasks.find((t) => t.task_id === state.lastRouteTask.task_id) || state.lastRouteTask;
  render();
  schedulePoll(pollInterval(state.tasks, state.pending.length, state.actions.length, justClosed(before, state.tasks)));
}

// ---------- the composer's input, files and keys ----------

function autosize() {
  // the small UI cleanup, row 11 (note 3): an empty box is as tall as its placeholder, which a browser doesn't count; it holds the words
  // only while they're measured, inside this one synchronous step, so nothing paints and nothing is lost
  const prompt = $("prompt");
  const measured = !prompt.value && prompt.placeholder;
  if (measured) prompt.value = prompt.placeholder;
  prompt.style.height = "auto";
  const height = `${Math.min(prompt.scrollHeight, window.innerHeight * 0.4)}px`;
  if (measured) prompt.value = "";
  prompt.style.height = height;
}

async function addFiles(fileList) {
  if (state.team !== "route") { toast("Files go on Route only: a team task carries no files."); return; }
  for (const file of Array.from(fileList || [])) {
    try {
      const data = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
      });
      const written = await api("/api/drop", { method: "POST", body: { name: file.name, data } });
      state.files.push({ path: written.path, name: written.name, size: written.size });
    } catch (e) {
      toast(`${file.name}: ${e.message}`);
    }
  }
  renderComposer();
  refreshCommand();
}

function inTextField(target) {
  return !!target && (target.tagName === "TEXTAREA" || target.tagName === "INPUT" || target.tagName === "SELECT" || target.isContentEditable);
}

function onKey(event) {
  const found = shortcutFor(event, { inText: inTextField(event.target), inPrompt: event.target && event.target.id === "prompt" });
  if (!found) return;
  if (state.sheetKind === "newproject" && found.action !== "escape") return;  // brief 26: nothing acts behind the sheet
  if (found.action === "chip") {
    const chips = chipViews(state.status, state.team, { project: state.project === NEW_PROJECT ? null : state.project });  // UI A N11: ⌥8 on a project
    const chip = chips[found.index];
    event.preventDefault();
    if (chip && !chip.disabled) setTeam(chip.key);
    else if (chip) toast(chip.reason);
  } else if (found.action === "send") {
    event.preventDefault();
    send();
  } else if (found.action === "escape") {
    if (!$("sheet").hidden) { requestCloseSheet(); return; }
    if (state.navOpen) { toggleNav(false); return; }
    if (plusOpen()) { setPlus(false); document.querySelector(".plus-btn").focus(); return; }  // UI-1 row 5 (D2)
    if (state.teamMenu) { state.teamMenu = false; renderTeam(); return; }
    if (state.stripOpen) { const box = `agent-box-${state.stripOpen}`; state.stripOpen = null; renderStrip(); focusId(box); return; }
    const other = openOtherBox();  // UI-1m (D25): an open Other box takes Esc first
    if (other) { closeOtherBox(other.taskId, other.k); return; }
    if (state.confirm && !state.menu && $(`keep-${state.confirm.taskId}`)) { keepConfirm(); return; }  // UI-1m (2.7): as Keep it
    if (state.planOpen) {  // UI-1 row 12 (D16): Esc closes the open step, back to its Edit
      const key = state.planOpen;
      state.planOpen = null;
      renderStream();
      const opener = [...$("stream").querySelectorAll("[data-focus-key]")].find((el) => el.dataset.focusKey === `plan-open-${key}`);
      if (opener) opener.focus();
      return;
    }
    if (state.view === "settings" && state.modelsOpen) {  // UI B row 14: Esc closes the open row, back to its Change
      const key = state.modelsOpen;
      state.modelsOpen = null;
      renderSetup();
      const opener = [...$("stream").querySelectorAll("[data-focus-key]")].find((el) => el.dataset.focusKey === `models-change-${key}`);
      if (opener) opener.focus();
      return;
    }
    if (state.pieceOpen) {  // UI A row 16 (A18): Esc closes the open piece, back to its Edit
      const key = state.pieceOpen;
      state.pieceOpen = null;
      renderStream();
      const opener = [...$("stream").querySelectorAll("[data-focus-key]")].find((el) => el.dataset.focusKey === `piece-open-${key}`);
      if (opener) opener.focus();
      return;
    }
    if (state.menu) {  // UI-1 row 14: back to the button that opened it
      const from = state.menu === PROJECT_MENU || String(state.menu).startsWith("more-") ? state.menu : `run-again-${state.menu}`;
      state.menu = null;
      state.menuSub = null;
      renderStream();
      const opener = [...$("stream").querySelectorAll("[data-focus-key]")].find((el) => el.dataset.focusKey === from);
      if (opener) opener.focus();
      return;
    }
    if (state.panel) { closePanel(); return; }
    if (state.team !== "route") setTeam("route");
    // brief 33 (D's step 3; the rules' "Esc clears"): the box, its From and Idea pills and a fill's placeholder
    state.skill = null;  // UI A row 1: back to Auto, with the rest of the box
    if (state.text || state.from || state.idea || state.step || state.models || state.noFiles) setBox({ text: "", team: "route", project: state.project,
      chat: state.chat, quick: state.quick, from: null, idea: null, step: null, models: null, noFiles: false, placeholder: null });  // 33.1: the Step pill; 33.3: the model pills; 33.2: Text only
  } else if (found.action === "shortcuts") {
    event.preventDefault();
    openShortcuts();
  }
}

function requestCloseSheet() {
  // brief 30 (decisions 10 and 17): an editor with unsaved text asks once (the second close discards it)
  const editor = state.sheetKind === "notes" ? state.ne : state.sheetKind === "pnotes" ? state.pn : null;
  const specDirty = state.sheetKind === "pnotes" && editor && editor.spec && editor.spec.doc && editor.spec.text != null
    && editor.spec.text !== editor.spec.doc.text;  // brief 33.2: the Spec section's box counts too
  if (editor && ((editor.doc && editor.text !== (state.sheetKind === "notes" ? editor.doc.text : editor.doc.notes)) || specDirty) && !editor.closing) {
    editor.closing = true;
    if (state.sheetKind === "notes") paintNotesEditor(); else paintProjectNotes();
    return;
  }
  closeSheet();
}

function closeSheet() {
  $("sheet").hidden = true;
  if (["notes", "pnotes", "pin", "savefile"].includes(state.sheetKind)) {  // brief 30: a save still running ends in a toast
    state.ne = null; state.pn = null; state.ps = null; state.sf = null;
  }
  if (state.sheetKind === "newproject") state.np = null;  // a create still running finishes and says so in a toast
  if (state.sheetKind === "tests") state.ts = null;  // brief 28: a save still running finishes and says so in a toast
  if (state.sheetKind === "git") state.gu = null;
  if (state.sheetKind === "runcmd") state.rc = null;  // brief 31: a save still running finishes and says so in a toast
  if (state.sheetKind === "pconfirm") state.pc = null;
  if (state.sheetKind === "secrets") state.sc = null;  // brief 31: no value is held anywhere once the sheet closes
  if (state.sheetKind === "drop") state.fd = null;
  if (state.sheetKind === "ideas") state.ideasSheet = null;  // brief 33: an add still running finishes in a toast
  if (state.sheetKind === "models") state.modelsSheet = null;  // brief 33.3: the choices stay in the composer's pills
  const auto = state.sheetKind === "auto";  // UI-1 row 7 (D6a): closed any way, it is Keep it off: back to the switch
  if (auto) state.autoAsk = null;
  state.sheetKind = null;
  setChildren($("sheet"));
  if (auto) { renderStream({ follow: false }); focusId("auto-switch"); }
}

function openShortcuts() {
  const keys = [["Enter", "Send the task"], ["⌘ Enter", "Send the task"], ["Shift Enter", "A new line"],
    ["⌥1 … ⌥8", "Light a team chip"], ["Esc", "Back to Route, or close this"], ["?", "These shortcuts"],
    ["/versus …", "Light a team with a slash command (/route, /quick, /web, /file, /chat name, /project name)"],
    ["@claude …", "Send to one agent (an override), on Route"],
    ["/model", "Pick the model each agent uses on this task (Team → Models…)"]];  // brief 33.3
  const sheet = h("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-label": "Shortcuts" },
    h("div", { class: "sheet-head" }, h("span", { class: "sheet-title", text: "Shortcuts" }),
      h("button", { class: "icon-btn", type: "button", "aria-label": "Close", onclick: closeSheet }, icon("x"))),
    h("div", { class: "keys" }, keys.map(([k, what]) => [h("kbd", { text: k }), h("span", { text: what })])));
  setChildren($("sheet"), sheet);
  state.sheetKind = "shortcuts";
  $("sheet").hidden = false;
}

function cycleTheme() {
  state.theme = state.theme === "auto" ? "dark" : state.theme === "dark" ? "light" : "auto";
  applyTheme();
  try { localStorage.setItem("sr-theme", state.theme); } catch (e) { /* the theme just isn't remembered */ }
  renderSidebar();
  renderSetup();  // UI B N5: Theme sits in the Settings tab now
}

function applyTheme() {
  if (state.theme === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", state.theme);
}

function wire() {
  const prompt = $("prompt");
  prompt.addEventListener("input", () => {
    state.text = prompt.value;
    if (!applySlash(false)) { renderComposer(); refreshCommand(); }
    autosize();
  });
  document.addEventListener("keydown", onKey);
  $("send").addEventListener("click", send);
  $("quick").addEventListener("change", (e) => { state.quick = e.target.checked; renderComposer(); refreshCommand(); renderStream(); });
  $("project").addEventListener("change", (e) => {
    if (e.target.value === NEW_PROJECT) { e.target.value = state.project || ""; openNewProject(); return; }  // brief 26: never sent
    state.project = e.target.value || null; render(); refreshCommand();
  });
  $("web").addEventListener("change", (e) => { state.web = e.target.checked; refreshCommand(); });
  $("skill").addEventListener("change", (e) => { state.skill = e.target.value || null; renderComposer(); refreshCommand(); });
  $("attach").addEventListener("click", () => { setPlus(false); $("file-input").click(); });
  document.querySelector(".plus-btn").addEventListener("click", (e) => { e.stopPropagation(); setPlus(!plusOpen()); });  // UI-1 row 5
  document.querySelector(".plus-menu").addEventListener("keydown", plusKeys);  // UI A row 15
  $("file-input").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
  $("copy").addEventListener("click", async () => {
    const text = state.command && state.command.copy;
    if (!text) return;
    try { await navigator.clipboard.writeText(text); toast("Copied the command."); } catch (e) { toast("Copy is blocked in this browser."); }
  });
  const composer = $("composer");
  composer.addEventListener("dragover", (e) => { if (state.team === "route" && !state.demo) { e.preventDefault(); composer.classList.add("dragging"); } });
  composer.addEventListener("dragleave", () => composer.classList.remove("dragging"));
  composer.addEventListener("drop", (e) => {
    composer.classList.remove("dragging");
    if (state.team !== "route" || state.demo) return;
    e.preventDefault();
    addFiles(e.dataTransfer.files);
  });
  $("sheet").addEventListener("click", (e) => { if (e.target === $("sheet")) closeSheet(); });
  $("nav-backdrop").addEventListener("click", () => toggleNav(false));
  let resized = 0;  // brief 32.1: a window that changes size measures the head again, once a frame
  window.addEventListener("resize", () => {
    if (resized) return;
    resized = requestAnimationFrame(() => { resized = 0; renderStrip(); renderStream({ follow: false }); autosize(); });  // UI B N3: Menu by the width; row 11: the box's lines
  });
  document.addEventListener("click", (e) => {
    if (state.teamMenu && !e.target.closest("#team")) { state.teamMenu = false; renderTeam(); }
    if (plusOpen() && !e.target.closest(".plus")) setPlus(false);  // UI-1 row 5 (D2)
    if (state.stripOpen && !e.target.closest("#strip")) { state.stripOpen = null; renderStrip(); }
    if (state.menu === PROJECT_MENU && !e.target.closest(".project-menu")) { state.menu = null; renderStream({ follow: false }); }  // UI-1 row 14
    if (String(state.menu).startsWith("more-") && !e.target.closest(".card-menu")) { state.menu = null; renderStream({ follow: false }); }  // row 4
    // the small UI cleanup, row 9 (note 21): a failed card's own Run again as…, whose key is its task
    if (state.menu && state.menu !== PROJECT_MENU && !String(state.menu).startsWith("more-") && !e.target.closest(".row-actions .menu")) { state.menu = null; renderStream({ follow: false }); }
  });
}

async function boot() {
  state.token = META("sr-token");
  state.demo = META("sr-demo") === "1";
  state.reveal = META("sr-reveal") === "1";
  try { state.theme = localStorage.getItem("sr-theme") || "auto"; } catch (e) { state.theme = "auto"; }
  applyTheme();
  readSidePrefs();  // UI B N2
  wire();
  render();
  await loadStatus();
  if (!state.demo) {
    try { state.actions = restoredActions((await api("/api/runs")).runs || [], state.actions); } catch (e) { /* the poll tries */ }
  }
  await loadLog();
  const chats = ((state.status && state.status.chats) || []).slice().sort((a, b) => String(b.newest).localeCompare(String(a.newest)));
  state.chat = chats.length ? chats[0].name : newChatName();
  render();
  refreshCommand();
  schedulePoll(pollInterval(state.tasks, 0));
}

if (typeof document !== "undefined" && typeof window !== "undefined") {
  boot();
}
