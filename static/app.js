// Super Router's page (build brief 23). Plain JavaScript, no framework, no library, no build step.
// The page renders the JSON `sr` prints and has no routing, checking or prompt of its own: every button asks the
// server to run an `sr` command that the server builds in Python (router/page_commands.py). Task and result text come
// from outside (models, people): it is set with textContent, never parsed as HTML; markdown is drawn by a small renderer
// that escapes first. The pure functions below are exported for `node --test` (tests/js/); the DOM wiring at the end
// runs only in a browser.

// ---------- words and small pure helpers ----------

export const AGENT_NAMES = { claude: "Claude", chatgpt: "ChatGPT", grok: "Grok Bot", cursor: "Cursor", muse: "Muse" };
export const PAGE_SLASHES = ["route", "quick", "project", "chat", "file", "web"];
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
  redteam: { build: "Build and revise", attack: "Attack", check: "Check" },
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

export function isOpenTask(task) {
  return !!task && task.outcome == null && ["queued", "sent", "returned"].includes(task.status);
}

export function pollInterval(tasks, pending = 0) {
  return pending > 0 || (tasks || []).some(isOpenTask) ? POLL_OPEN_MS : POLL_IDLE_MS;
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

export function agentView(agent, tasks = []) {
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
    if (agent.name === "claude") detail = [`Code ${agent.version || "?"} · ${searchWord(agent.probe)}`];
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

export function memoryView(memory) {
  if (!memory) return { tone: "muted", state: "unknown", detail: "" };
  if (memory.starting) return { tone: "info", state: "starting", detail: "about 35 s · nothing to do" };
  if (memory.setting === "off") return { tone: "muted", state: "off", detail: "memory is off in settings" };
  if (memory.online) {
    const docs = memory.documents == null ? "" : `${memory.documents} documents · `;
    return { tone: "ok", state: "online", detail: `${docs}starts itself` };
  }
  return { tone: "muted", state: "offline", detail: "starts itself when a chat task needs it" };
}

// ---------- the team chips and the slot strip ----------

export function chipViews(status, lit = "route") {
  const chips = [{ key: "route", label: "Route", disabled: false, reason: null,
    title: "Jev labels the task; the skill table picks who does it and who checks it" }];
  for (const preset of (status && status.presets) || []) {
    // brief 24 (decision 15): greyed only when status says the chain can't run now, with status's reason
    const blocked = preset.ready === false;
    chips.push({ key: preset.name, label: teamLabel(preset.name), disabled: blocked, reason: blocked ? preset.why : null,
      title: [preset.description, preset.chain].filter(Boolean).join(" · ") });
  }
  return chips.map((chip, i) => ({ ...chip, checked: chip.key === lit, shortcut: i < 6 ? `⌥${i + 1}` : null }));
}

export function slotViews(preset, chosen = {}, status = null) {
  if (!preset) return { slots: [], note: null };
  const agents = new Map(((status && status.agents) || []).map((a) => [a.name, a]));
  const words = SLOT_WORDS[preset.name] || {};
  const slots = (preset.slots || []).map((slot) => {
    // brief 24 (decisions 8 and 15): `allowed` lists only available agents; a default that isn't available shows
    // greyed with why, and the agent the router fills its slot with is the one chosen
    const fill = (preset.filled || []).find((f) => f.slot === slot.name) || null;
    const options = (slot.allowed || []).map((agent) => ({ agent, label: agentLabel(agent), disabled: false, reason: null }));
    if (!(slot.allowed || []).includes(slot.default)) {
      options.unshift({ agent: slot.default, label: agentLabel(slot.default), disabled: true,
        reason: (fill && fill.why) || usable(agents.get(slot.default)).why });
    }
    return {
      name: slot.name,
      label: words[slot.name] || teamLabel(slot.name),
      value: chosen[slot.name] || (fill ? fill.agent : slot.default),
      isDefault: !chosen[slot.name] || chosen[slot.name] === slot.default,
      filled: fill ? { agent: fill.agent, why: fill.why } : null,
      options,
    };
  });
  const cursorSlots = slots.filter((s) => s.options.some((o) => o.agent === "cursor")).map((s) => s.name.toUpperCase());
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
  const takesProject = state.team === "route" || !!(preset && preset.project);
  const project = state.project === NEW_PROJECT ? null : state.project;  // brief 26: the picker's sentinel is never sent
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

export function sendRequest(state, status) {
  const request = { action: "send", team: state.team, text: state.text };
  const ctx = contextFor(state, status);
  if (ctx.flag && ctx.value) request[ctx.flag] = ctx.value;
  if (state.team === "route") {
    if ((state.files || []).length) request.files = state.files.map((f) => f.path);
    if (state.web) request.web = true;
    const pick = skillPick(state, status);
    if (pick.needed && pick.chosen) request.skill = pick.chosen;
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
  const preset = ((status && status.presets) || []).find((p) => p.name === team);
  return `New task for ${teamLabel(team)}: ${preset ? preset.description || preset.chain : "a team"}`;
}

export function jevBox({ team, task = null, floor = 0.8, sending = false, missing = null } = {}) {
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
  if (event.altKey && !inText && !event.metaKey && !event.ctrlKey && /^Digit[1-6]$/.test(event.code || "")) {
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
      probe: "waiting for a safety check", memory: "waiting for memory to start" };
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
  const team = task.mode === "relay" ? teamLabel(task.preset) : task.mode === "split" ? "Split"
    : task.mode === "piece" ? `Piece of a split` : "Route";
  const tone = task.waiting_on ? (["grok", "piece", "probe", "memory"].includes(task.waiting_on) ? "info" : "warn")
    : ["passed", "fixed", "picked"].includes(task.outcome) ? "ok"
      : ["failed_check", "stopped", "plan_limit", "process_ended", "timed_out"].includes(task.outcome) ? "bad"
        : task.outcome ? "muted" : "info";
  const failed = task.failed_stage ? `stopped at stage ${task.failed_stage}` : null;
  return { team, state: stateWords(task), tone, check: task.check_state || null, note: task.check_note || null, failed,
    piece: task.mode === "piece", parent: task.parent || null };
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

// ---------- markdown (decision 10): a small renderer that never produces HTML ----------
// It turns text into a tree of plain objects; the DOM builder below makes elements from it with textContent only.
// Headings, lists, emphasis, code, tables and https:// links; never an image, never raw HTML (it stays text).

function inline(text) {
  const out = [];
  const re = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\*[^*\n]+\*|_[^_\n]+_)|(\[[^\]\n]+\]\([^)\s]+\))|(https:\/\/[^\s<>()]+[^\s<>().,;:!?'"])/g;
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
      while (i < lines.length && bullet.test(lines[i]) && /^\s*\d/.test(lines[i]) === ordered) {
        items.push(inline(lines[i].replace(bullet, "")));
        i += 1;
      }
      blocks.push({ type: ordered ? "ol" : "ul", items });
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
    const label = call.kind === "reask" ? `${roleWords(role)} re-ask` : roleWords(role);
    const state = call.status === "sent" ? "live" : call.status === "done" ? (call.verdict === "FIX" ? "warn" : "ok")
      : call.status === "failed" ? "bad" : "warn";
    stages.push({ key: call.call_id, label, agent: call.agent, state, file: call.round_file || null,
      verdict: call.verdict || null, reason: call.reason_code || null });
  }
  return stages;
}

// The waits that are your turn (router/state.py WAITING_ON): the agents are done until you answer.
export const YOUR_TURN = ["needs_label", "split_plan", "pick", "vote_pick"];

export function receiptView(task, show, now = new Date().toISOString()) {
  const pills = [];
  if (task.mode === "relay" || task.mode === "split") pills.push({ text: "Jev not asked: team chosen" });
  else if (task.skill_source === "owner") pills.push({ text: "your label: ", value: task.skill || "-" });
  else if (task.jev && task.jev.label) {
    pills.push({ text: `Jev → ${task.jev.label} `, value: task.jev.confidence == null ? "" : Number(task.jev.confidence).toFixed(2) });
  }
  if (task.tag && show) {
    const n = (show.memory_given || []).length;
    pills.push({ text: "memory: ", value: n ? `${n} ${n === 1 ? "entry" : "entries"}` : "none yet" });
  }
  if (show && show.handoff) pills.push({ text: "handoff: ", value: show.handoff.left_out ? "left out (Grok)" : show.handoff.attached ? "attached" : "not sent yet" });
  if (task.mode === "relay" && task.slots) {
    for (const [slot, agent] of Object.entries(task.slots)) pills.push({ text: `${slot} `, value: agentLabel(agent) });
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

export const PREVIEW_CHARS = 20000;

export function resultPreview(text, limit = PREVIEW_CHARS) {
  // a huge result (a 2 MB export) shows its first `limit` characters on the card, cut at a line; Show all opens the
  // whole of it beside, so a poll never parses and draws megabytes into the stream (break-ui, 21 Oct)
  const whole = String(text || "");
  if (whole.length <= limit) return { text: whole, cut: false };
  const at = whole.lastIndexOf("\n", limit);
  return { text: whole.slice(0, at > limit * 0.8 ? at : limit), cut: true };
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
    case "cancel": case "resume": case "fallback": return `sr ${request.action} ${id}`;
    case "check": return "sr check";
    case "split_skip": return `sr split --skip ${id}`;
    case "split_go": return [`sr split --go ${id} --answer ${request.choice}`,
      ...Object.entries(request.skills || {}).map(([k, v]) => `--skill ${k}=${v}`)].join(" ");
    case "floor": return `sr route --skill ${request.skill} --answers ${request.answers} -- ${shellQuote(request.text)}`;
    default: return "";
  }
}

export function needsConfirm(request) {
  // rules (Interface): a pick, a skip, a cancel, a split's run and a `none` each ask once; a split's Reject too (the owner,
  // 21 Oct: it closes the plan and can't be undone; a 2.33 line); nothing else does
  if (!request) return false;
  return ["pick", "split_skip", "cancel", "split_go"].includes(request.action);
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

function routeWords(route) {
  if (!route) return "";
  const check = route.checker ? `${agentLabel(route.checker)} checks` : "no check";
  return [`${route.skill} · ${agentLabel(route.agent)}, ${check}`, route.comes_back ? `comes back: ${route.comes_back}` : null]
    .filter(Boolean).join(" · ");
}

export function splitPlanView(task, show) {
  if (!task || task.waiting_on !== "split_plan" || !show || !show.pieces) return null;
  const pieces = show.pieces.map((p) => ({
    piece: p.piece, text: p.text, edited: p.edited, needsLabel: p.needs_label,
    words: p.needs_label ? `Jev left it under the floor (${p.jev && p.jev.label ? `${p.jev.label} at ${Number(p.jev.confidence).toFixed(2)}` : "no label"}): pick its skill`
      : routeWords(p.route),
  }));
  return { title: "A split plan is waiting", sub: `${pieces.length} pieces · nothing runs until you approve`, pieces,
    join: show.join || null, joiner: agentLabel(task.agent), checker: agentLabel(task.checker),
    reject: { action: "split_go", task_id: task.task_id, choice: "n" } };
}

export function splitApprove(task, show, choices = {}) {
  const under = ((show && show.pieces) || []).filter((p) => p.needs_label);
  const missing = under.filter((p) => !choices[p.piece]).map((p) => p.piece);
  const skills = Object.fromEntries(under.filter((p) => choices[p.piece]).map((p) => [String(p.piece), choices[p.piece]]));
  return { missing, request: { action: "split_go", task_id: task.task_id, choice: "y", skills } };
}

export function piecesView(task, show) {
  if (!task || task.mode !== "split" || task.waiting_on === "split_plan" || !show || !show.pieces) return null;
  return show.pieces.map((p) => ({
    piece: p.piece, n: p.n, task_id: p.task_id, text: p.text, state: p.piece_state,
    words: p.piece_state === "blocked" ? `blocked: ${p.why}` : p.piece_state === "waiting" ? `waiting (${p.why})`
      : p.piece_state || "not started",
    skip: task.waiting_on === "piece" && p.piece_state === "blocked" ? { action: "split_skip", task_id: p.task_id } : null,
  }));
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
    offers.push({ key: "check", label: "Re-check", tone: "", note: "asks Grok's inbox now", request: { action: "check" } });
  }
  if (isOpenTask(task) && task.waiting_on !== "needs_label") {
    offers.push({ key: "cancel", label: "Cancel", tone: "quiet", note: "", request: { action: "cancel", task_id: id } });
  }
  return offers;
}

export function versusBoard(task, show) {
  if (!task || task.preset !== "versus" || !show || !(show.candidates || []).length) return null;
  const picking = task.waiting_on === "pick";
  return {
    picking, picked: show.pick || null,
    cards: show.candidates.map((c) => ({ letter: c.letter, builder: agentLabel(c.builder), text: c.text || "", missing: c.missing || null,
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

export function redteamBoard(task, show) {
  if (!task || task.preset !== "redteam" || !show || !(show.attacks || []).length) return null;
  return { findings: show.attacks.map((a) => ({ n: a.n, severity: a.severity, text: a.text,
    fix: a.answered ? `answered: ${a.answered}` : "fixed" })) };
}

export function memoryCallLines(calls) {
  // Terminal's per-call memory lines (router `_call_memory_lines`), with the page's names for the role and agent
  return (calls || []).map((c) => {
    const m = c.memory || {};
    const who = `${c.kind === "stage" || c.kind === "reask" ? `stage ${c.stage}${c.kind === "reask" ? " re-ask" : ""}` : roleWords(c.kind)} · ${agentLabel(c.agent)}`;
    let what = m.state === "unavailable" ? "the store was unavailable; the call ran without it"
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

export function memoryDrawer(task, show) {
  if (!task || !task.tag || !show) return null;
  return {
    tag: task.chat ? `chat ${task.chat}` : task.project ? `project ${task.project}` : task.tag,
    given: (show.memory_given || []).map((m) => ({ head: [`#${m.n}`, m.date, m.kind, m.doer ? agentLabel(m.doer) : null, m.status]
      .filter(Boolean).join(" · "), text: m.text || "" })),
    calls: memoryCallLines(show.calls),
    handoff: handoffWords(show.handoff),
    stored: (show.memory_stored || []).map((m) => `${m.document_id} · ${m.chars} characters · ${m.state}`),
  };
}

const NEEDS_WORDS = { needs_label: "Pick a skill", split_plan: "Approve a split plan", pick: "Pick A or B",
  vote_pick: "A tie: pick one", failed_check: "Failed its check twice", plan_limit: "Plan limit",
  process_ended: "Process ended", grok: "Grok is overdue", memory: "Memory starting", probe: "A safety check is running" };

export function needsYou(task) {
  // What a task needs from you, or null: your turn on a wait, a rescue the row offers, a Grok task overdue
  if (!task) return null;
  if (YOUR_TURN.includes(task.waiting_on)) return NEEDS_WORDS[task.waiting_on];
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
  const view = slotViews(preset, request.slots, status);
  const filled = Object.fromEntries(view.slots.map((s) => [s.name, s.value]));
  const out = [];
  for (const slot of view.slots) {
    if (!usableIn(status, slot.value).bad) continue;
    for (const o of slot.options) {
      // never an agent another slot already holds: intake refuses one agent judging its own work (presets.own_work)
      const elsewhere = Object.entries(filled).some(([name, agent]) => name !== slot.name && agent === o.agent);
      if (o.agent !== slot.value && !elsewhere && !usableIn(status, o.agent).bad) {
        out.push({ label: `Run it with ${o.label} in slot ${slot.name.toUpperCase()}`, request: { ...request, slots: { ...request.slots, [slot.name]: o.agent } } });
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

export const SETUP_PIECES = [["claude", "Claude"], ["chatgpt", "ChatGPT"], ["cursor", "Cursor"], ["grok", "Grok Bot"],
  ["jev", "Jev"], ["memory", "Memory"]];

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
  if (key === "memory") return null;
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
    if (key === "jev") {
      if (status && status.jev == null) return { key, name, tone: "muted", state: "unknown", detail: "not checked yet", checkedAt: null };
      const jev = jevView(status && status.jev);
      return { key, name, tone: !jev.configured ? "muted" : jev.over ? "bad" : "ok", state: jev.configured ? jev.text : "not set up",
        detail: !jev.configured ? (status.jev.why || "no JEV_API_KEY in .env") : jev.over ? "over this month's cap: routed tasks wait for your label" : "tokens this month",
        checkedAt: null };
    }
    if (key === "memory") {
      const memory = memoryView(status && status.memory);
      return { key, name, tone: memory.tone, state: memory.state, detail: memory.detail, checkedAt: null };
    }
    const agent = agents.get(key);
    if (!agent) return { key, name, tone: "muted", state: "not in this router", detail: "", checkedAt: null };
    const view = agentView(agent, []);
    return { key, name, tone: view.tone, state: view.state, detail: view.detail.join(" · "), checkedAt: agent.checked_at || null };
  });
}

export function firstRunItems(status) {
  // the first-run card: every light that is grey or red, with its reason (rules: Setup)
  if (!status) return [];
  // an unknown light (not checked yet) is not a setup problem (break-ui, 21 Oct)
  return setupRows(status).filter((r) => (r.tone === "bad" || r.tone === "muted") && !["not checked", "unknown"].includes(r.state))
    .map((r) => ({ key: r.key, name: r.name, reason: r.detail || r.state, without: r.without }));
}

export function logFolderView(folder, tasks) {
  const task = (tasks || []).find((t) => t.task_id === folder.task_id);
  return { task_id: folder.task_id, title: task ? `#${task.n} · ${task.text}` : folder.task_id, when: task ? task.created_at : null,
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

export function verdictLine(task, show) {
  // the checker bar as one line; the raw notes and errors are behind Details
  const checker = agentLabel(task.checker);
  const agent = agentLabel(task.agent);
  if (isOpenTask(task)) {
    if (task.waiting_on === "grok") {
      const grok = grokWait(task);
      const note = grok.note.replace(/^(waiting|overdue): grok, /, (m, word) => (word === "overdue" ? "overdue, " : ""));
      return { tone: grok.tone, text: `Waiting on Grok${note ? ` · ${note}` : ""}` };
    }
    if (task.waiting_on) return { tone: YOUR_TURN.includes(task.waiting_on) ? "warn" : "info", text: capital(stateWords(task)) };
    return { tone: "info", text: task.working && task.working.doing ? `Working · ${task.working.doing}` : "Working" };
  }
  const tally = show && show.tally;
  switch (task.outcome) {
    case "passed": {
      if (tally && tally.winner) {
        const won = ((show && show.votes) || []).find((v) => v.letter === tally.winner);
        return { tone: "ok", text: `${won ? won.answer : "Agreed"} · ${tally.for} of ${tally.for + tally.against} agree` };
      }
      return { tone: "ok", text: task.preset === "vote" ? "Passed by vote" : `Passed · ${checker}` };
    }
    case "fixed": return { tone: "ok", text: `Fixed · ${checker}, round 2` };
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
    case "plan_limit": return { tone: "bad", text: `Stopped · plan limit${agent ? ` on ${agent}` : ""}` };
    case "process_ended": return { tone: "bad", text: `Stopped · process ended${agent ? ` (${agent})` : ""}` };
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

// ---------- talking to the server ----------

const META = (name) => (document.querySelector(`meta[name="${name}"]`) || {}).content || "";

const state = {
  token: "", demo: false, reveal: false,
  status: null, statusAt: 0, statusError: null,
  tasks: [], logError: null, nextBefore: null,
  chat: null, project: null, quick: false, team: "route", slots: {}, view: "chat",
  historyQuery: { chat: null, project: null, search: "" }, historyTasks: [], historyNext: null, historyPages: 1, historyError: null,
  logFolders: [], logNext: null, logError: null, setupText: null, setupError: null, setupChecking: false, setupFocus: null,
  sheetKind: null, np: null, madeProjects: new Set(), teamMenu: false, stripOpen: null, detailsOpen: new Set(), navOpen: false,
  text: "", files: [], web: false, skill: null,
  command: null, commandSeq: 0,
  pending: [], refused: [], sessionTasks: [],
  restarted: false, lastRouteTask: null, sending: false,
  theme: "auto", toastTimer: null,
  shows: new Map(), filesOf: new Map(), loading: new Set(), expanded: new Set(), menu: null, streamView: null,
  panel: null, runs: [],
  confirm: null, actions: [], actionErrors: new Map(), splitChoices: new Map(), notified: new Set(), notifyReady: false,
  focusTask: null,
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
  // one pinned line (the owner's cleanup): per agent its light, name and words; then Jev and Memory; a click shows the details
  const status = state.status;
  if (!status) {
    setChildren($("strip"), h("div", { class: "pills-row" }, h("span", { class: "agent-pill tone-muted" }, h("span", { class: "light" }),
      h("span", { class: "agent-words", text: state.statusError ? "the router's status is unreadable" : "loading…" }))));
    return;
  }
  const items = (status.agents || []).map((agent) => {
    const view = agentView(agent, state.tasks);
    return { key: agent.name, tone: view.tone, name: view.name, words: pillWords(agent, view), detail: view.detail.join(" · ") };
  });
  const jev = jevView(status.jev);
  const jevUnknown = status.jev == null;
  items.push({ key: "jev", tone: !jev.configured ? "muted" : jev.over ? "bad" : "ok", name: "Jev",
    words: jevUnknown ? "unknown" : jev.configured ? jev.text : "not set up",
    detail: jevUnknown ? "not checked yet" : !jev.configured ? "no JEV_API_KEY in .env" : jev.over ? "over this month's cap: routed tasks wait for your label" : "tokens this month against the cap" });
  const memory = memoryView(status.memory);
  items.push({ key: "memory", tone: memory.tone, name: "Memory", words: memory.state, detail: memory.detail });
  const open = items.find((i) => i.key === state.stripOpen);
  setChildren($("strip"), h("div", { class: "pills-row" }, items.map((item) => h("button", {
    class: `agent-pill tone-${item.tone}`, type: "button", title: [item.name, item.words, item.detail].filter(Boolean).join(" · "),
    "aria-expanded": state.stripOpen === item.key ? "true" : "false",
    onclick: (e) => { e.stopPropagation(); state.stripOpen = state.stripOpen === item.key ? null : item.key; renderStrip(); } },
  h("span", { class: "light", "aria-hidden": "true" }), h("span", { class: "agent-name", text: item.name }),
  h("span", { class: "agent-words", text: item.words })))),
  open ? h("div", { class: "strip-details", role: "status" }, h("strong", { text: open.name }), ` · ${open.words}`, open.detail ? ` · ${open.detail}` : "",
    open.tone === "bad" || open.tone === "muted" ? [" · ", h("button", { class: "linklike", type: "button", onclick: () => openSetup(open.key) }, "How to set it up")] : null)
    : null);
}

function renderSidebar() {
  const status = state.status || {};
  const chats = (status.chats || []).slice().sort((a, b) => String(b.newest).localeCompare(String(a.newest)));
  const list = [];
  list.push(h("div", { class: "brand" }, h("span", { class: "brand-mark" }, icon("logo")),
    h("span", { class: "brand-name", text: "Super Router" }),
    h("span", { class: "brand-version", text: status.version ? `v${status.version}` : "" })));
  list.push(h("button", { class: "side-item primary", type: "button", title: "New chat", onclick: newChat },
    icon("plus"), h("span", { class: "name", text: "New chat" })));
  const needs = needsYouList(state.tasks);
  // narrow screens (break-ui, the owner: Needs you visible at every width): the count stays in the top bar, and Menu opens
  // the sidebar's lists as a drawer
  list.push(h("div", { class: "narrow-only narrow-bar" },
    needs.you.length ? h("button", { class: "side-item needs-btn", type: "button", "aria-expanded": state.navOpen ? "true" : "false",
      onclick: () => toggleNav() }, icon("alert"), h("span", { class: "name", text: `Needs you · ${needs.you.length}` })) : null,
    h("button", { class: "side-item", type: "button", "aria-expanded": state.navOpen ? "true" : "false", "aria-label": "Menu",
      onclick: () => toggleNav() }, icon("menu"), h("span", { class: "name", text: state.navOpen ? "Close" : "Menu" }))));
  if (needs.you.length) {
    list.push(h("div", { class: "side-label", text: `Needs you · ${needs.you.length}` }));
    list.push(h("div", { class: "side-list" }, needs.you.map((item) => h("button", { class: "side-item needs", type: "button",
      title: `#${item.n}: ${item.what}`, onclick: () => goToTask(item.task_id) }, icon("alert"),
    h("span", { class: "name", text: item.what }), h("span", { class: "count", text: `#${item.n}` })))));
  }
  if (needs.router.length) {
    list.push(h("div", { class: "side-label", text: "Waiting on the router" }));
    list.push(h("div", { class: "side-list" }, needs.router.map((item) => h("button", { class: "side-item", type: "button",
      title: `#${item.n}: ${item.what}`, onclick: () => goToTask(item.task_id) }, icon("clock"),
    h("span", { class: "name", text: item.what }), h("span", { class: "count", text: `#${item.n}` })))));
  }
  list.push(h("div", { class: "side-label", text: "Chats" }));
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
  list.push(chatList);
  // brief 26 (decision 12): a + on the Projects label opens the New project sheet (a 44 px hit area round a small mark)
  list.push(h("div", { class: "side-label with-action" }, h("span", { text: "Projects" }),
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
  list.push(projectList);
  list.push(h("div", { class: "side-label", text: "History" }));
  list.push(h("div", { class: "side-list" },
    h("button", { class: "side-item", type: "button", title: "Every task: by chat or project, search, older pages",
      "aria-current": state.view === "history" ? "page" : null, onclick: openHistory }, icon("clock"), h("span", { class: "name", text: "All tasks" })),
    h("button", { class: "side-item", type: "button", title: "Every call's output: the tasks/ folder, newest first",
      "aria-current": state.view === "logfiles" ? "page" : null, onclick: openLogFiles }, icon("file"), h("span", { class: "name", text: "Log files" })),
    status.report_path ? h("button", { class: "side-item", type: "button", title: tilde(status.report_path),
      onclick: openReport }, icon("book"), h("span", { class: "name", text: "Read the report" })) : null));
  list.push(h("div", { class: "side-spacer" }));
  const bottom = h("div", { class: "side-bottom" });
  const notify = notifyState();
  if (notify) {
    bottom.append(h("button", { class: "side-item", type: "button", title: "A desktop notification when a task needs you", onclick: askNotify },
      icon("alert"), h("span", { class: "name", text: notify === "granted" ? "Notifications: on" : notify === "denied" ? "Notifications: blocked" : "Notify me when a task needs you" })));
  }
  bottom.append(h("button", { class: "side-item", type: "button", title: "Each piece's state and its steps", onclick: () => openSetup() },
    icon("gear"), h("span", { class: "name", text: "Setup" })));
  bottom.append(h("button", { class: "side-item", type: "button", title: "Light or dark", onclick: cycleTheme },
    icon("moon"), h("span", { class: "name", text: `Theme: ${state.theme}` })));
  list.push(bottom);
  setChildren($("sidebar"), list);
  $("sidebar").classList.toggle("open", state.navOpen);
  $("nav-backdrop").hidden = !state.navOpen;
}

function toggleNav(open = !state.navOpen) {
  state.navOpen = open;
  renderSidebar();
}

function streamTasks() {
  const all = state.tasks || [];
  if (state.view === "history") return state.historyTasks.slice().sort((a, b) => a.n - b.n);
  if (state.view === "logfiles") return [];
  const mine = new Set(state.sessionTasks);
  return all.filter((t) => {
    if (mine.has(t.task_id)) return true;
    if (state.project) return t.project === state.project;
    return state.chat ? t.chat === state.chat : !t.chat && !t.project;
  }).slice().sort((a, b) => a.n - b.n);
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
    if (b.type === "ul" || b.type === "ol") return h(b.type, {}, b.items.map((item) => h("li", {}, mdInline(item))));
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

function stageLine(task, show) {
  // the stages alone (each a dot coloured by its state, opening its round file), the time at the end; Jev is in Details
  const stages = stagesView(task, show).filter((s) => s.key !== "jev");
  if (!stages.length) return null;  // the time rides with the stages; alone it says nothing (break-ui)
  const time = taskTime(task, clockNow());
  const items = [];
  stages.forEach((stage, i) => {
    if (i) items.push(h("span", { class: "sep", "aria-hidden": "true", text: "→" }));
    const label = [stage.label, stage.agent ? agentLabel(stage.agent) : null].filter(Boolean).join(" · ");
    const props = { class: `st ${stage.state}`, title: stage.reason ? `${label}: ${stage.reason.replace(/_/g, " ")}` : label };
    const dot = h("span", { class: "dot", "aria-hidden": "true" });
    items.push(stage.file ? h("button", { ...props, type: "button", onclick: () => openRoundFile(task, stage.file) }, dot, label) : h("span", props, dot, label));
  });
  if (time) items.push(h("span", { class: "time", text: `· ${time}` }));
  return h("div", { class: "stageline", "aria-label": "Stages" }, items);
}

function detailsBlock(task, show) {
  // what the card no longer shows up front: Jev's label and confidence, memory, rounds, the raw notes, the two buttons
  const view = checkView(task, show);
  const notes = detailNotes(task, show);
  const actions = [];
  if (view && view.given && task.tag) actions.push(h("button", { class: "btn btn-quiet", type: "button", onclick: () => openMemory(task) }, "What the agents were given"));
  if (view && view.original) actions.push(h("button", { class: "btn btn-quiet", type: "button", onclick: () => openRoundFile(task, view.original) }, "Show original"));
  return h("div", { class: "details" },
    h("div", { class: "pills" }, receiptView(task, show, clockNow()).map((pill) => h("span", { class: "pill" }, pill.text,
      pill.value ? h("b", { text: pill.value }) : null))),
    view && view.detail ? h("div", { class: "details-line", text: `${view.title} · ${view.detail}` }) : null,
    notes.map((note) => h("div", { class: "details-line mono", text: note })),
    actions.length ? h("div", { class: "row-actions" }, actions) : null);
}

function runAgainMenu(task) {
  const open = state.menu === task.task_id;
  const own = task.mode === "relay" ? task.preset : task.mode === "split" ? null : "route";  // a split has no chip: every team
  const chips = chipViews(state.status, state.team).filter((c) => c.key !== own);
  return h("div", { class: "menu" },
    h("button", { class: "btn", type: "button", "aria-expanded": open ? "true" : "false", disabled: state.demo || state.restarted,
      onclick: () => { state.menu = open ? null : task.task_id; renderStream({ follow: false }); } }, "Run again as…"),
    open ? h("div", { class: "menu-list", role: "menu" }, chips.map((chip) => h("button", {
      class: "side-item", type: "button", role: "menuitem", disabled: chip.disabled, title: chip.reason || chip.title,
      onclick: () => { state.menu = null; runAgain(task, chip.key); } }, h("span", { class: "name", text: `${chip.label}: a new task` }))))
      : null);
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
  const preview = resultPreview(task.result);
  const long = !preview.cut && (task.result.length > 1800 || task.result.split("\n").length > 24);
  const expanded = state.expanded.has(task.task_id);
  const body = h("div", { class: `result${(long && !expanded) || preview.cut ? " clamped" : ""}` },
    renderMarkdown(preview.text, `${task.task_id}:${task.result.length}`));
  const who = resultHeading(task);
  return h("div", { class: "answer" }, h("div", { class: "answer-meta", text: who }), body,
    long ? h("button", { class: "btn btn-quiet load-earlier", type: "button",
      onclick: () => { expanded ? state.expanded.delete(task.task_id) : state.expanded.add(task.task_id); renderStream({ follow: false }); } },
    expanded ? "Show less" : "Show all") : null,
    preview.cut ? h("button", { class: "btn btn-quiet load-earlier", type: "button", onclick: () => openText(task, who) },
      `Show all ${humanSize(task.result.length)} beside`) : null,
    fileRow(task), h("div", { class: "row-actions" }, runAgainMenu(task)));
}

function taskCard(task) {
  const summary = taskSummary(task);
  const show = state.shows.get(task.task_id) || null;
  const meta = [`#${task.n}`, summary.team, task.chat ? `chat ${task.chat}` : task.project ? `project ${task.project}` : null,
    localTime(task.created_at)].filter(Boolean).join(" · ");
  const verdict = verdictLine(task, show);
  const detailed = state.detailsOpen.has(task.task_id);
  // Built through h(), which skips a missing part (Element.append(null) would write the word "null").
  const card = h("article", { class: "task", dataset: { task: task.task_id } },
    h("div", { class: "bubble-row" }, h("div", { class: "bubble-col" },
      h("div", { class: "bubble", text: task.text }), h("div", { class: "bubble-meta", text: meta }))),
    stageLine(task, show),
    task.card_line ? h("div", { class: "card-line", text: task.card_line }) : null,  // brief 24 (decision 15)
    h("div", { class: `verdict ${verdict.tone}` }, h("span", { class: "light", "aria-hidden": "true" }),
      h("span", { class: "verdict-text", text: verdict.text }),
      h("button", { class: "details-btn", type: "button", "aria-expanded": detailed ? "true" : "false",
        onclick: () => { detailed ? state.detailsOpen.delete(task.task_id) : state.detailsOpen.add(task.task_id); renderStream({ follow: false }); } },
      detailed ? "Hide details" : "Details")),
    detailed ? detailsBlock(task, show) : null,
    needsBlock(task, show),
    boardBlock(task, show),
    offersRow(task),
    confirmRow(task),
    actionLine(task),
    voteBoard(task, show) ? null : resultBlock(task, show),
    task.result && !voteBoard(task, show) ? null : fileRow(task),
    task.result && !voteBoard(task, show) ? null : h("div", { class: "row-actions" }, runAgainMenu(task)));
  observeCard(card, task);
  return card;
}

// ---------- needs you, the boards, the stop offers and the confirm (D) ----------

function needsBlock(task, show) {
  const floor = floorView(task, state.status);
  if (floor) {
    return h("div", { class: "offer warn" },
      h("div", { class: "offer-head" }, icon("alert"), h("span", { class: "offer-title", text: floor.title }),
        h("span", { class: "offer-side", text: floor.sub })),
      h("div", { class: "skills", role: "group", "aria-label": "Skills" }, floor.skills.map((s) => h("button", {
        class: `btn skill${s.guess ? " guess" : ""}`, type: "button", title: s.guess ? "Jev's guess" : s.key, disabled: busy(task),
        onclick: () => act(task, s.request) }, s.key))),
      h("div", { class: "offer-row" }, h("span", { class: "offer-cmd", text: "One click sends it again as a new task with that skill; this row keeps Jev's label." }),
        h("button", { class: "btn btn-quiet", type: "button", disabled: busy(task), onclick: () => act(task, floor.cancel) }, "Cancel")));
  }
  const plan = splitPlanView(task, show);
  if (plan) {
    const choices = state.splitChoices.get(task.task_id) || {};
    const approve = splitApprove(task, show, choices);
    const skills = ((state.status && state.status.skills) || []).map((s) => s.key);
    return h("div", { class: "offer info" },
      h("div", { class: "offer-head" }, icon("alert"), h("span", { class: "offer-title", text: plan.title }),
        h("span", { class: "offer-side", text: plan.sub })),
      h("ol", { class: "pieces" }, plan.pieces.map((piece) => h("li", { class: "piece" },
        h("span", { class: "k", text: String(piece.piece) }), h("span", { class: "t", text: piece.text }),
        piece.needsLabel
          ? h("select", { class: "select", "aria-label": `Piece ${piece.piece}'s skill`, onchange: (e) => {
            state.splitChoices.set(task.task_id, { ...(state.splitChoices.get(task.task_id) || {}), [piece.piece]: e.target.value || undefined });
            renderStream({ follow: false });
          } }, h("option", { value: "", text: "Pick its skill…" }), skills.map((k) => h("option", { value: k, selected: choices[piece.piece] === k, text: k })))
          : null,
        h("span", { class: "r", text: piece.words })))),
      plan.join ? h("div", { class: "offer-body", text: `${plan.joiner} joins them (“${plan.join}”); ${plan.checker} checks the whole.` }) : null,
      h("div", { class: "offer-row" },
        h("button", { class: "btn btn-primary", type: "button", disabled: busy(task) || approve.missing.length > 0,
          title: approve.missing.length ? `Pick a skill for piece ${approve.missing.join(" and ")} first` : null,
          onclick: () => act(task, approve.request) }, "Approve and run"),
        h("button", { class: "btn", type: "button", disabled: busy(task), onclick: () => act(task, plan.reject) }, "Reject"),
        h("span", { class: "offer-cmd", text: "Approve and Reject each ask once more · editing a piece stays in Terminal" })));
  }
  const pieces = piecesView(task, show);
  if (pieces) {
    return h("ol", { class: "pieces", "aria-label": "Pieces" }, pieces.map((piece) => h("li", { class: "piece" },
      h("span", { class: "k", text: piece.n ? `${piece.piece} · #${piece.n}` : String(piece.piece) }), h("span", { class: "t", text: piece.text }),
      h("span", { class: "r", text: piece.words }),
      piece.skip ? h("button", { class: "btn", type: "button", disabled: busy(task), onclick: () => act(task, piece.skip) }, "Skip") : null)));
  }
  if (task.waiting_on === "memory") return h("div", { class: "quiet-line", text: "Memory is starting; this task goes on by itself once it's up." });
  if (task.waiting_on === "probe") return h("div", { class: "quiet-line", text: "A safety check this task needs is running; the task goes on by itself." });
  return null;
}

function reviewEl(review) {
  if (!review) return null;
  return h("details", { class: `review ${review.verdict === "pass" ? "pass" : review.verdict === "fail" ? "fail" : ""}` },
    h("summary", { text: `${review.reviewer}'s review: ${review.verdict}` }), h("div", { class: "review-notes", text: review.notes || "No notes." }));
}

function boardBlock(task, show) {
  const versus = versusBoard(task, show);
  if (versus) {
    const grid = h("div", { class: "board" }, versus.cards.map((c) => h("div", { class: `cand${c.picked ? " won" : ""}` },
      h("div", { class: "cand-head" }, h("span", { class: `letter ${c.letter}`, text: c.letter.toUpperCase() }),
        h("span", { class: "cand-who", text: c.builder }), c.picked ? h("span", { class: "cand-sub", text: "picked" }) : null),
      h("div", { class: "cand-body result" }, renderMarkdown(c.text)),
      c.missing ? h("div", { class: "missing", text: `Missing: ${c.missing}` }) : null,
      reviewEl(c.review))));
    if (!versus.picking) return h("details", { class: "fold" }, h("summary", { text: "Both candidates and their reviews" }), grid);
    return h("div", { class: "board-wrap" }, grid, h("div", { class: "offer-row" }, versus.choices.map((c) => h("button", {
      class: c.choice === "none" ? "btn" : "btn btn-primary", type: "button", disabled: busy(task), onclick: () => act(task, c.request) }, c.label)),
    h("span", { class: "offer-cmd", text: "each asks once more, naming the command" })));
  }
  const vote = voteBoard(task, show);
  if (vote) {
    const won = vote.votes.filter((v) => v.side !== "alone").length;
    return h("div", { class: "board-wrap" },
      h("div", { class: "board three" }, vote.votes.map((v) => h("div", { class: `cand vote-card${v.side === "winner" || v.picked ? " won" : ""}${v.side === "alone" ? " dissent" : ""}` },
        h("div", { class: "cand-head" }, h("span", { class: `letter ${v.letter}`, text: v.letter.toUpperCase() }),
          h("span", { class: "cand-who", text: v.agent }), h("span", { class: "cand-sub", text: v.confidence == null ? "" : `confidence ${v.confidence}` })),
        h("div", { class: "vote-answer", text: v.answer }), v.why ? h("div", { class: "review-notes", text: v.why }) : null,
        v.picked ? h("span", { class: "cand-sub", text: "your pick" }) : null))),
      h("div", { class: "tally" }, h("div", { class: "offer-head" }, h("span", { class: "offer-title", text: vote.tie ? "No two agreed" : `Tally: ${vote.tally}` })),
        h("div", { class: "tally-bar", "aria-hidden": "true" }, vote.votes.map((v, i) => h("span", { class: i < won ? "won" : "" })))),
      vote.choices.length ? h("div", { class: "offer-row" }, vote.choices.map((c) => h("button", {
        class: c.choice === "none" ? "btn" : "btn btn-primary", type: "button", disabled: busy(task), onclick: () => act(task, c.request) }, c.label)),
      h("span", { class: "offer-cmd", text: "a tie is never broken by a model: your pick is delivered unchecked" })) : null);
  }
  const red = redteamBoard(task, show);
  if (red) {
    return h("div", { class: "redteam-wrap" }, h("table", { class: "redteam-table" },
      h("caption", { text: "Findings" }),
      h("thead", {}, h("tr", {}, h("th", { text: "Severity" }), h("th", { text: "Weak spot" }), h("th", { text: "Fix" }))),
      h("tbody", {}, red.findings.map((f) => h("tr", {}, h("td", {}, h("span", { class: `sev ${f.severity}`, text: f.severity })),
        h("td", { text: f.text }), h("td", { text: f.fix }))))));
  }
  return null;
}

function offersRow(task) {
  const offers = rescueOffers(task);
  if (!offers.length) return null;
  return h("div", { class: "offer-row offers" }, offers.map((o) => h("span", { class: "offer-item" },
    h("button", { class: `btn${o.tone === "primary" ? " btn-primary" : o.tone === "quiet" ? " btn-quiet" : ""}`, type: "button",
      disabled: busy(task), onclick: () => act(task, o.request) }, o.label),
    o.note ? h("span", { class: "offer-cmd", text: o.note }) : null)));
}

function confirmRow(task) {
  const c = state.confirm;
  if (!c || c.taskId !== task.task_id) return null;
  return h("div", { class: "confirm", role: "group", "aria-label": "Confirm" },
    h("div", { class: "confirm-text" }, `#${task.n}: run `, h("code", { text: c.display || "…" }), "?"),
    c.refused ? h("div", { class: "missing", text: c.refused }) : null,
    h("div", { class: "offer-row" },
      h("button", { class: "btn btn-primary", type: "button", disabled: !c.display || !!c.refused, onclick: () => runAction(task, c.request) }, "Confirm"),
      h("button", { class: "btn btn-quiet", type: "button", onclick: () => { state.confirm = null; renderStream({ follow: false }); } }, "Keep it")));
}

function actionLine(task) {
  const running = state.actions.filter((a) => a.taskId === task.task_id);
  const error = state.actionErrors.get(task.task_id);
  if (!running.length && !error) return null;
  return h("div", { class: "action-line" },
    running.map((a) => h("div", { class: "quiet-line", text: `Running: ${a.display}` })),
    error ? h("div", { class: "offer bad", role: "alert" },
      h("div", { class: "offer-head" }, icon("alert"), h("span", { class: "offer-title", text: error.title }),
        h("span", { class: "offer-side", text: [error.code, error.exit == null ? null : `exit ${error.exit}`].filter(Boolean).join(" · ") })),
      h("div", { class: "offer-body", text: error.message }),
      h("div", { class: "offer-row" }, h("span", { class: "offer-cmd", text: error.display || "" }),
        h("button", { class: "btn btn-quiet", type: "button", onclick: () => { state.actionErrors.delete(task.task_id); renderStream({ follow: false }); } }, "Dismiss"))) : null);
}

function busy(task) {
  return state.restarted || state.actions.some((a) => a.taskId === task.task_id);
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
    const ask = { taskId: task.task_id, request, display: null, refused: null };
    state.confirm = ask;
    renderStream({ follow: false });
    commandText(request).then((found) => {
      if (state.confirm !== ask) return;
      Object.assign(ask, found);
      renderStream({ follow: false });
    });
    return;
  }
  runAction(task, request);
}

async function runAction(task, request) {
  if (state.confirm && state.confirm.taskId === task.task_id) state.confirm = null;
  try {
    const started = await api("/api/run", { method: "POST", body: request });
    state.actions.push({ run_id: started.run_id, taskId: task.task_id, display: started.copy || started.display });
    state.actionErrors.delete(task.task_id);
  } catch (e) {
    if (state.demo) toast(e.message);
    else state.actionErrors.set(task.task_id, { title: "Not run", message: e.message, code: null, exit: null, display: "" });
  }
  renderStream({ follow: false });
  schedulePoll(800);
}

function goToTask(taskId) {
  const task = (state.tasks || []).find((t) => t.task_id === taskId);
  if (!task) return;
  state.focusTask = { id: taskId, until: Date.now() + 10000 };  // until its card is drawn (All tasks loads first)
  if (task.chat) openChat(task.chat);
  else if (task.project) openProject(task.project);
  else openHistory();
}

function focusCard() {
  const wanted = state.focusTask;
  if (!wanted) return;
  if (Date.now() > wanted.until) { state.focusTask = null; return; }
  const card = document.querySelector(`#stream > article.task[data-task="${CSS.escape(wanted.id)}"]`);
  if (!card) return;
  state.focusTask = null;
  card.scrollIntoView({ block: "start" });  // the top, not the centre: the sticky composer covers the lower part
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
  return h("article", { class: "task", dataset: { run: item.run_id } },
    h("div", { class: "bubble-row" }, h("div", { class: "bubble-col" }, h("div", { class: "bubble", text: item.text }),
      h("div", { class: "bubble-meta", text: `${teamLabel(item.team)} · sending…` }))),
    h("div", { class: "checkbar info" }, h("span", { class: "title", text: item.team === "route" ? "Jev is labeling…" : "Starting…" }),
      h("span", { class: "detail mono", text: item.display })));
}

function refusalCard(run) {
  const view = refusalView(run);
  const alts = refusalAlternatives(run, state.status);
  return h("article", { class: "offer bad", role: "alert" },
    h("div", { class: "offer-head" }, icon("alert"), h("span", { class: "offer-title", text: view.title }),
      h("span", { class: "offer-side", text: [view.code, view.exit == null ? null : `exit ${view.exit}`].filter(Boolean).join(" · ") })),
    h("div", { class: "offer-body", text: view.message }),
    alts.length ? h("div", { class: "offer-row" }, alts.map((alt) => h("button", { class: "btn btn-primary", type: "button",
      disabled: state.demo || state.restarted, onclick: () => { dismissRefusal(run.id); resend(alt.request); } }, alt.label))) : null,
    h("div", { class: "offer-row" }, h("span", { class: "offer-cmd", text: view.display }),
      h("button", { class: "btn btn-quiet", type: "button", onclick: () => dismissRefusal(run.id) }, "Dismiss")));
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
  if (changed || (follow && el.scrollHeight - el.scrollTop - el.clientHeight < 48)) return { bottom: true };
  for (const card of document.querySelectorAll("#stream > article.task")) {
    const box = card.getBoundingClientRect();
    if (box.bottom > 80) return { id: card.dataset.task, top: box.top };
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

function renderStream({ follow = true } = {}) {
  if (observer) observer.disconnect();  // the cards are drawn again: the old ones are gone
  const anchor = streamAnchor(follow);
  const stream = $("stream");
  const tasks = streamTasks();
  const head = h("div", { class: "stream-head" });
  if (state.view === "logfiles") {
    keepFocus(() => setChildren(stream, logFilesView()));
    restoreAnchor(anchor);
    return;
  }
  if (state.view === "history") {
    head.append(h("span", { class: "stream-title", text: "All tasks" }), historyFilter(), historySearch(),
      h("span", { class: "stream-sub right", text: state.historyError ? state.historyError : `${tasks.length} shown${state.historyNext ? " · older ones above" : ""}` }));
  } else if (state.project) {
    head.append(h("span", { class: "stream-title", text: state.project }), h("span", { class: "stream-sub", text: "project · its HANDOFF.md rides on every call" }),
      h("button", { class: "btn btn-quiet right", type: "button", onclick: () => openHandoff(state.project) }, icon("book"), "HANDOFF.md"));
  } else if (state.chat) {
    head.append(h("span", { class: "stream-title", text: state.chat }),
      h("span", { class: "stream-sub", text: `chat · ${tasks.length} task${tasks.length === 1 ? "" : "s"} · memory on for this chat` }),
      h("span", { class: "stream-sub right", text: `every task here is sent with --chat ${state.chat}` }));
  } else {
    head.append(h("span", { class: "stream-title", text: "Quick tasks" }), h("span", { class: "stream-sub", text: "no chat, no memory" }));
  }
  const items = [head, firstRunCard()];
  if (state.view === "history" && state.historyNext) {
    items.push(h("button", { class: "btn btn-quiet load-earlier", type: "button", onclick: () => loadHistory({ more: true }) }, "Load earlier tasks"));
  }
  if (!tasks.length && !state.pending.length && !state.refused.length) {
    // brief 26 (decision 14): a project with no tasks says its HANDOFF.md goes with every task sent there
    const project = state.project && state.view === "chat" ? ((state.status && state.status.projects) || []).find((p) => p.name === state.project) : null;
    items.push(h("div", { class: "empty", id: project ? "np-empty-card" : null, text: state.logError ? `The log could not be read: ${state.logError}`
      : project ? emptyProjectWords(project) : "No tasks here yet. Type below and press Enter." }));
  }
  items.push(...tasks.map(taskCard));
  items.push(...state.pending.map(pendingCard));
  items.push(...state.refused.map(refusalCard));
  keepFocus(() => setChildren(stream, items));
  restoreAnchor(anchor);
  focusCard();
}

function keepFocus(draw) {
  // every poll draws the stream again: a field you are typing in (History's search) keeps its focus and caret
  const active = document.activeElement;
  const id = active && active.id && $("stream").contains(active) ? active.id : null;
  const range = id && typeof active.selectionStart === "number" ? [active.selectionStart, active.selectionEnd] : null;
  draw();
  if (!id) return;
  const again = document.getElementById(id);
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
      h("span", { class: "offer-side", text: "the Setup sheet has the steps" })),
    h("ul", { class: "first-run-list" }, items.map((item) => h("li", {}, h("strong", { text: item.name }), ` · ${item.reason} · `,
      h("button", { class: "linklike", type: "button", onclick: () => openSetup(item.key) }, "How to set it up")))));
}

function logFilesView() {
  const known = [...(state.tasks || []), ...(state.historyTasks || [])];
  const head = h("div", { class: "stream-head" }, h("span", { class: "stream-title", text: "Log files" }),
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
  const tag = $("context-tag");
  tag.textContent = ctx.kind === "quick" ? "Quick task: untagged" : ctx.kind === "project" ? `Project: ${ctx.value}` : `Chat: ${ctx.value || "new"}`;
  tag.title = tag.textContent;
  $("quick").checked = state.quick;
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
  $("web-label").title = onRoute ? "Let the agents search the web on a task with files" : "Web goes on Route only";
  $("attach").disabled = !onRoute || state.demo;
  $("attach").title = onRoute ? "Attach a file (or drop one here)" : "Files go on Route only";
  setChildren($("files"), state.files.map((file) => h("span", { class: "chip-tag" }, icon("file"), h("span", { text: file.name }),
    h("button", { class: "x", type: "button", "aria-label": `Remove ${file.name}`, onclick: () => removeFile(file.path) }, "×"))));
  const pick = skillPick(state, status);  // brief 24 (decision 13): without Jev you pick the skill before Send
  const skill = $("skill");
  skill.hidden = !pick.needed;
  if (pick.needed) {
    setChildren(skill, h("option", { value: "", text: "Pick a skill" }),
      pick.options.map((o) => h("option", { value: o.key, selected: o.key === pick.chosen, text: o.label })));
    skill.title = pick.why;
  }
  const send = $("send");
  send.textContent = pick.needed && !pick.chosen ? "Send · pick a skill" : `Send · ${teamLabel(state.team)}`;
  send.disabled = state.demo || state.restarted || !state.text.trim() || (pick.needed && !pick.chosen);
  send.title = state.demo ? "Demo: nothing runs" : pick.needed && !pick.chosen ? pick.why : "";
  const prompt = $("prompt");
  prompt.placeholder = placeholderFor(state.team, status);
  $("prompt-label").textContent = placeholderFor(state.team, status);
  $("composer").classList.toggle("lit", state.team !== "route");
  renderCommand();
  renderJev();
}

function renderTeam() {
  // "Team: Route ▾" (the owner's cleanup): a menu of Route and the presets from status, each chain on hover, ⌥1-⌥6 as
  // before; a lit team's slots as small selects beside it, the slot rule as their tooltip
  const status = state.status;
  const chips = chipViews(status, state.team);
  const lit = chips.find((c) => c.checked) || { label: teamLabel(state.team), title: "" };
  const parts = [h("button", { class: `team-btn${state.team !== "route" ? " lit" : ""}`, type: "button", id: "team-btn",
    "aria-haspopup": "menu", "aria-expanded": state.teamMenu ? "true" : "false", title: lit.title || "",
    onclick: (e) => { e.stopPropagation(); state.teamMenu = !state.teamMenu; renderTeam(); } },
  h("span", { class: "k", text: "Team:" }), h("span", { text: lit.label }), h("span", { class: "caret", "aria-hidden": "true" }, icon("chevron")))];
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
    chip.shortcut ? h("span", { class: "key", text: chip.shortcut }) : null))));
  }
  const preset = ((status && status.presets) || []).find((p) => p.name === state.team);
  if (preset) {
    const view = slotViews(preset, state.slots, status);
    parts.push(h("span", { class: "team-slots", title: view.note || "" }, view.slots.map((slot, i) => [
      i ? h("span", { class: "dot", "aria-hidden": "true", text: "·" }) : null,
      h("label", { class: "slot-inline", title: view.note ? `${slot.label} · ${view.note}` : slot.label },
        h("span", { class: "slot-name", text: slot.name.length <= 2 ? slot.name.toUpperCase() : slot.label }),
        h("select", { class: "slot-select", id: `slot-${slot.name}`, "aria-label": slot.label,
          onchange: (e) => { state.slots = { ...state.slots, [slot.name]: e.target.value }; refreshCommand(); } },
        slot.options.map((o) => h("option", { value: o.agent, disabled: o.disabled, selected: o.agent === slot.value,
          title: o.disabled ? o.reason : null }, o.disabled ? `${o.label} (${o.reason})` : o.label))))])));
  }
  setChildren($("team"), parts);
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
  const box = jevBox({ team: state.team, task: state.lastRouteTask, floor, sending: state.pending.some((p) => p.team === "route"),
    missing: missing ? "Jev isn't set up: pick the skill" : null });
  const jev = $("jev");
  jev.classList.toggle("under", !!box.under);
  jev.classList.toggle("idle", box.mode !== "label");
  if (box.mode === "label") {
    const bar = h("span", { class: "bar", "aria-hidden": "true" }, h("span"), h("i"));
    bar.children[0].style.width = `${Math.round((box.confidence || 0) * 100)}%`;
    bar.children[1].style.left = `${Math.round(box.floor * 100)}%`;
    setChildren(jev, h("span", { class: "k", text: "Jev" }), h("span", { text: `${box.label} ${box.confidence == null ? "" : box.confidence.toFixed(2)}` }),
      bar, h("span", { class: "k", text: box.under ? `under the ${box.floor.toFixed(2)} floor: you pick` : `floor ${box.floor.toFixed(2)}` }));
  } else {
    setChildren(jev, h("span", { class: "k", text: "Jev" }), h("span", { text: box.text }));
  }
}

function render() {
  renderBanners();
  renderStrip();
  renderSidebar();
  renderStream();
  renderComposer();
  renderPanel();
  if (state.sheetKind === "setup") renderSetup();
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
  state.loading.add(taskId);
  try {
    const [show, files] = await Promise.all([api(`/api/task/${encodeURIComponent(taskId)}`),
      api(`/api/files/${encodeURIComponent(taskId)}`).catch(() => ({ files: [] }))]);
    state.shows.set(taskId, show);
    state.filesOf.set(taskId, files.files || []);
  } catch (e) {
    // a card without its details still shows the log row
  } finally {
    state.loading.delete(taskId);
  }
  if (!quiet) renderStream();
  if (state.panel && state.panel.taskId === taskId) renderPanel();
}

function taskById(taskId) {
  return (state.tasks || []).find((t) => t.task_id === taskId) || (state.shows.get(taskId) || null);
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
  h("div", { class: "result" }, renderMarkdown(other.text || "")),
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
  app.classList.toggle("panel-open", !!panel);
  if (!panel) { node.hidden = true; setChildren(node); return; }
  node.hidden = false;
  if (panel.kind === "memory") { renderMemoryPanel(node, panel); return; }
  if (panel.kind === "doc") { renderDocPanel(node, panel); return; }
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
  const head = h("div", { class: "panel-head" }, h("div", { class: "panel-row" },
    h("span", { class: "file-icon text" }, icon("chat")),
    h("div", { class: "panel-title" }, h("div", { class: "panel-name", text: "What the agents were given" }),
      h("div", { class: "panel-sub", text: view ? `#${task.n} · ${view.tag}` : `#${task.n}` })),
    h("div", { class: "panel-tools" }, h("button", { class: "icon-btn", type: "button", "aria-label": "Close the panel", onclick: closePanel }, icon("x")))));
  if (!view) {
    setChildren(node, head, h("div", { class: "panel-body" }, h("p", { class: "panel-note",
      text: show ? "This task has no chat or project, so it carried no memory." : "Loading…" })));
    return;
  }
  const body = [h("div", { class: "panel-sub-head", text: `The memory block (${view.given.length}): the newest task first, then matches newest first` })];
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

function runAgain(task, team) {
  const keep = { team: state.team, text: state.text, files: state.files, web: state.web, slots: state.slots };
  state.team = team;
  state.text = task.text;
  state.files = [];
  state.web = false;
  state.slots = {};
  send({ keepComposer: keep });
}

// ---------- actions ----------

function setTeam(team) {
  state.team = team;
  if (team !== "route") { state.web = false; }
  refreshCommand();
  renderComposer();
}

function newChat() {
  state.view = "chat";
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
  loadHistory();
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
  setChildren(node, head, h("div", { class: "panel-body" }, body));
}

// ---------- the New project sheet (brief 26, decisions 10–14) ----------
// Built once, then painted in place, so typing keeps its focus and caret. The router answers every question: the
// folder check is its dry run, the command line comes from the server's builder, and Create runs `sr project new`.

const NP_CHECK_MS = 160;   // like the command line: ask once typing stops
const NP_WAIT_MS = 5000;   // a dry run this slow is said so; Create stays off until it answers
const NP_POLL_MS = 400;    // a create is quick: watch its run closely
const NP_RUN_LIMIT_MS = 125 * 1000;  // the server gives a command 120 s
let npCheckTimer = null;
let npWaitTimer = null;
let npCommandTimer = null;

function openNewProject() {
  if (state.navOpen) toggleNav(false);
  state.np = { raw: "", notes: "", check: null, error: null, waited: false, seq: 0, commandSeq: 0, running: false,
    failure: null };
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
    h("p", { class: "panel-note", text: "Every task you send in a project carries its notes file, HANDOFF.md. The agents can't open the folder: these notes are all they know about it." }),
    h("div", { class: "np-field" }, h("label", { class: "np-label", for: "np-name", text: "Name" }), name,
      h("div", { class: "np-hint", id: "np-hint" })),
    h("div", { class: "np-folder tone-muted", id: "np-folder", role: "status", "aria-live": "polite" }),
    h("div", { class: "np-field" },
      h("label", { class: "np-label", for: "np-notes" }, "Starting notes", h("span", { class: "np-opt", text: "optional" })), notes,
      h("div", { class: "np-hint", id: "np-notes-hint" })),
    h("div", { class: "np-cmd", id: "np-cmd", "aria-label": "The command Create runs" }, h("span", { class: "prompt", text: "$" }),
      h("span", { class: "cmd", id: "np-cmd-text" })),
    h("div", { class: "np-other" }, "Folder somewhere else? In Terminal: ", h("code", { text: "sr project add <name> <path>" })),
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
  return { name, view: newProjectView(np.check, { name, root: status.projects_root || "~/Projects", taken, running: np.running,
    waited: np.waited, error: np.error, demo: state.demo, typed: !!np.raw.trim() }) };
}

function paintNewProject() {
  const np = state.np;
  if (state.sheetKind !== "newproject" || !np || !$("np-sheet")) return;
  const { view } = npView();
  const hint = slugHint(np.raw);
  setChildren($("np-hint"), hint.saved ? ["Saved as ", h("code", { text: hint.saved }), hint.text] : hint.text);
  const folder = $("np-folder");
  folder.className = `np-folder tone-${view.tone}`;
  setChildren(folder, icon("folder"), h("span", { class: "np-path", text: view.folder }), h("span", { class: "np-state", text: view.words }),
    view.detail ? h("span", { class: "np-detail", text: view.detail }) : null);
  const notes = $("np-notes");
  if (notes.disabled === view.notesOn) {  // turning off shows the placeholder; turning on brings the typed notes back
    notes.disabled = !view.notesOn;
    notes.value = view.notesOn ? np.notes : "";
  }
  const left = view.notesOn ? notesLeftWords(np.notes.length) : null;
  $("np-notes-hint").textContent = left ? `${view.notesHint} ${left}` : view.notesHint;
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

function npRequest() {
  const { name, view } = npView();
  return { action: "project_new", name, notes: view.notesOn ? state.np.notes : "" };
}

function npLocalParts(request) {
  // no name yet, or the demo (whose /api/command answers 409): the same shape the server's builder makes
  const parts = [{ text: "sr" }, { text: "project" }, { text: "new" }, { text: "--json", added: true }, { text: request.name || "<name>" }];
  if (request.notes) parts.push({ text: "--" }, { text: shellQuote(request.notes) });
  return parts;
}

function paintNpCommand(parts, display) {
  const node = $("np-cmd-text");
  if (!node) return;
  setChildren(node, parts.map((p, i) => [i ? " " : "", h("span", { class: p.added ? "added" : null, text: p.text })]));
  node.title = display || parts.map((p) => p.text).join(" ");
}

function refreshNpCommand() {
  clearTimeout(npCommandTimer);
  npCommandTimer = setTimeout(async () => {
    const np = state.np;
    if (!np) return;
    const request = npRequest();
    if (state.demo || !request.name) { paintNpCommand(npLocalParts(request)); return; }
    const seq = ++np.commandSeq;
    try {
      const found = await api("/api/command", { method: "POST", body: request });
      if (state.np === np && seq === np.commandSeq) paintNpCommand(found.parts, found.display);
    } catch (e) {
      if (state.np === np && seq === np.commandSeq) paintNpCommand([{ text: e.message }]);
    }
  }, NP_CHECK_MS);
}

async function npWaitRun(runId) {
  const until = Date.now() + NP_RUN_LIMIT_MS;
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
    if (state.np === np) closeSheet();
    openProject(name);
    toast(projectToast(env) || `Created ${name}`);
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
  state.sheetKind = "setup";
  state.setupFocus = focus;
  $("sheet").hidden = false;
  renderSetup();
  if (state.setupText != null) return;
  try {
    const resp = await api("/api/setup", { raw: true });
    if (!resp.ok) throw new Error(`docs/SETUP.md could not be read (HTTP ${resp.status})`);
    state.setupText = await resp.text();
    state.setupError = null;
  } catch (e) {
    state.setupError = e.message;
  }
  if (state.sheetKind === "setup") renderSetup();
}

function localClock(iso) {
  const d = new Date(iso || "");
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" });
}

function renderSetup() {
  const sections = setupSections(state.setupText || "").sections;
  const rows = setupRows(state.status);
  const checked = rows.map((r) => r.checkedAt).filter(Boolean).sort().at(-1);
  const sheet = h("div", { class: "sheet setup", role: "dialog", "aria-modal": "true", "aria-label": "Setup" },
    h("div", { class: "sheet-head" }, h("span", { class: "sheet-title", text: "Setup" }),
      h("span", { class: "sheet-sub", text: checked ? `checked ${localClock(checked)}` : "" }),
      h("button", { class: "btn", type: "button", id: "check-again", disabled: state.setupChecking || state.demo || state.restarted,
        title: state.demo ? "Demo: nothing runs." : "Ask the router for a fresh status (kept for 10 s)", onclick: checkAgain },
      state.setupChecking ? "Checking…" : "Check again"),
      h("button", { class: "icon-btn", type: "button", "aria-label": "Close", onclick: closeSheet }, icon("x"))),
    h("p", { class: "panel-note", text: "Each piece's live state beside its steps. The steps are for Terminal: the page never runs them." }),
    state.setupError ? h("p", { class: "missing", text: state.setupError }) : null,
    h("div", { class: "setup-rows" }, rows.map((row) => h("details", {
      class: `setup-row tone-${row.tone}`, id: `setup-${row.key}`,
      open: row.tone === "bad" || row.tone === "muted" || state.setupFocus === row.key ? true : null },
    h("summary", {}, h("span", { class: "light", "aria-hidden": "true" }), h("span", { class: "setup-name", text: row.name }),
      h("span", { class: "setup-state", text: row.state }), row.detail ? h("span", { class: "setup-detail", text: row.detail }) : null,
      row.checkedAt ? h("span", { class: "setup-checked", text: `checked ${localClock(row.checkedAt)}` }) : null),
    row.without ? h("p", { class: "setup-without", text: `Without it: ${row.without}` }) : null,
    h("div", { class: "setup-body result" }, sections[row.name] ? renderMarkdown(sections[row.name])
      : h("p", { class: "panel-note", text: state.setupText == null ? "Loading the steps…" : "No section for it in docs/SETUP.md." }))))));
  setChildren($("sheet"), sheet);
  if (state.setupFocus) {
    const row = document.getElementById(`setup-${state.setupFocus}`);
    if (row) row.scrollIntoView({ block: "start" });
    state.setupFocus = null;
  }
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
  state.navOpen = false;
  state.project = name;
  state.quick = false;
  state.team = "route";
  state.slots = {};
  state.sessionTasks = [];
  render();
  refreshCommand();
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
  const words = request.team === "route" ? ["sr", "route"] : ["sr", "relay", request.team];
  const parts = words.map((text) => ({ text, added: false }));
  parts.push({ text: "--json", added: true }, { text: "--source", added: true }, { text: "ui", added: true });
  if (request.chat) parts.push({ text: "--chat", added: false }, { text: request.chat, added: false });
  if (request.project) parts.push({ text: "--project", added: false }, { text: request.project, added: false });
  if (request.skill) parts.push({ text: "--skill", added: false }, { text: request.skill, added: false });
  parts.push({ text: "--", added: false }, { text: shellQuote(request.text), added: false });
  return parts;
}

async function send({ keepComposer = null } = {}) {
  if (!keepComposer) applySlash(true);
  const text = state.text;
  if (!text.trim() || state.demo || state.restarted || state.sending) return;
  const pick = skillPick(state, state.status);
  if (pick.needed && !pick.chosen) { toast(pick.why); return; }  // brief 24: without Jev, your skill first
  if (!state.quick && !state.project && !state.chat) state.chat = newChatName();
  const request = sendRequest({ ...state, text }, state.status);
  state.sending = true;
  try {
    const started = await api("/api/run", { method: "POST", body: request });
    state.pending.push({ run_id: started.run_id, pid: started.pid, text, team: state.team, display: started.copy || started.display });
    if (!keepComposer) {
      state.text = "";
      $("prompt").value = "";
      state.files = [];
      autosize();
    }
  } catch (e) {
    state.refused.push({ id: `local-${Date.now()}`, display: "", envelope: { message: e.message }, exit: null });
  } finally {
    state.sending = false;
    if (keepComposer) Object.assign(state, keepComposer);
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

async function loadStatus(fresh = false) {
  try {
    state.status = await api(fresh ? "/api/status?fresh=1" : "/api/status");
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

async function loadRuns() {
  if (!state.pending.length && !state.actions.length) return [];
  const finished = [];
  try {
    const runs = (await api("/api/runs")).runs || [];
    const byId = new Map(runs.map((r) => [r.id, r]));
    const acting = [];
    for (const item of state.actions) {
      const run = byId.get(item.run_id);
      if (!run || run.running) { acting.push(item); continue; }
      finished.push(item.taskId);
      const env = run.envelope || {};
      const code = run.exit == null ? env.exit : run.exit;
      if (code == null || [1, 2, 130].includes(code)) {
        const view = refusalView(run);
        state.actionErrors.set(item.taskId, { ...view, title: code === 2 ? "The router refused this" : "This ended with an error" });
        if (STATUS_CODES.includes(env.reason_code)) await loadStatus(true);
      } else if (env.task_id && env.task_id !== item.taskId && !state.sessionTasks.includes(env.task_id)) {
        state.sessionTasks.push(env.task_id);  // a floor answer is a new task: show it here
      }
    }
    state.actions = acting;
    const still = [];
    for (const item of state.pending) {
      const run = byId.get(item.run_id);
      if (run && run.task_id) {
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
  await loadLog();
  const acted = await loadRuns();
  if (acted.length) {
    await loadLog();  // an action ended: its rows are written, so the card shows what it did, not the old buttons
    for (const id of acted) if (state.shows.has(id)) state.shows.get(id).updated_at = null;
  }
  if (!state.demo) notifyNew();
  if (state.view === "history") await loadHistory({ quiet: true });
  const onScreen = new Set(streamTasks().map((t) => t.task_id));
  for (const task of state.tasks) {
    if (onScreen.has(task.task_id) && isOpenTask(task) && state.shows.has(task.task_id)) await loadShow(task.task_id, { quiet: true });
    else if (onScreen.has(task.task_id) && state.shows.has(task.task_id) && state.shows.get(task.task_id).updated_at !== task.updated_at) {
      await loadShow(task.task_id, { quiet: true });
    }
  }
  if (state.lastRouteTask) state.lastRouteTask = state.tasks.find((t) => t.task_id === state.lastRouteTask.task_id) || state.lastRouteTask;
  render();
  schedulePoll(pollInterval(state.tasks, state.pending.length));
}

// ---------- the composer's input, files and keys ----------

function autosize() {
  const prompt = $("prompt");
  prompt.style.height = "auto";
  prompt.style.height = `${Math.min(prompt.scrollHeight, window.innerHeight * 0.4)}px`;
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
    const chips = chipViews(state.status, state.team);
    const chip = chips[found.index];
    event.preventDefault();
    if (chip && !chip.disabled) setTeam(chip.key);
    else if (chip) toast(chip.reason);
  } else if (found.action === "send") {
    event.preventDefault();
    send();
  } else if (found.action === "escape") {
    if (!$("sheet").hidden) { closeSheet(); return; }
    if (state.navOpen) { toggleNav(false); return; }
    if (state.teamMenu) { state.teamMenu = false; renderTeam(); return; }
    if (state.stripOpen) { state.stripOpen = null; renderStrip(); return; }
    if (state.menu) { state.menu = null; renderStream(); return; }
    if (state.panel) { closePanel(); return; }
    if (state.team !== "route") setTeam("route");
  } else if (found.action === "shortcuts") {
    event.preventDefault();
    openShortcuts();
  }
}

function closeSheet() {
  $("sheet").hidden = true;
  if (state.sheetKind === "newproject") state.np = null;  // a create still running finishes and says so in a toast
  state.sheetKind = null;
  setChildren($("sheet"));
}

function openShortcuts() {
  const keys = [["Enter", "Send the task"], ["⌘ Enter", "Send the task"], ["Shift Enter", "A new line"],
    ["⌥1 … ⌥6", "Light a team chip"], ["Esc", "Back to Route, or close this"], ["?", "These shortcuts"],
    ["/versus …", "Light a team with a slash command (/route, /quick, /web, /file, /chat name, /project name)"],
    ["@claude …", "Send to one agent (an override), on Route"]];
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
  $("attach").addEventListener("click", () => $("file-input").click());
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
  document.addEventListener("click", (e) => {
    if (state.teamMenu && !e.target.closest("#team")) { state.teamMenu = false; renderTeam(); }
    if (state.stripOpen && !e.target.closest("#strip")) { state.stripOpen = null; renderStrip(); }
  });
}

async function boot() {
  state.token = META("sr-token");
  state.demo = META("sr-demo") === "1";
  state.reveal = META("sr-reveal") === "1";
  try { state.theme = localStorage.getItem("sr-theme") || "auto"; } catch (e) { state.theme = "auto"; }
  applyTheme();
  wire();
  render();
  await loadStatus();
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
