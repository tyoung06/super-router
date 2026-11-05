// A small stand-in for the browser, for tests that click the page's real menus (brief UI-1m, 2.3). No package: plain JS. It
// runs static/app.js itself, with `export { … }` added for the page's own functions, so a test presses what a person presses.
// Only what those paths touch is here. Not a test file: the name has no ".test".
import { readFileSync } from "node:fs";

const SOURCE = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const OWN = ["state", "renderStream", "onKey", "createProject", "flipAuto", "wire", "renderComposer", "renderTeam", "setTeam", "send", "render", "renderStrip", "renderSidebar", "cycleTheme", "openNewProject", "openSecrets", "openIdeas", "openNotesEditor", "openProjectNotes", "openPinSheet", "openSaveSheet", "renderRail", "openSetup", "openSettings", "newChat", "toggleNav", "fitHead", "readSidePrefs", "loadShow", "poll", "loadHistory", "loadViewRead", "syncViewRead", "openChat", "openProject", "openHistory", "goToTask", "goToSource", "jumpToTask", "openPieceCard", "taskById", "renderSetup"];

class FakeNode {
  constructor(tag, doc) { this.tag = String(tag).toLowerCase(); this.doc = doc; this.kids = []; this.parent = null; this.attrs = {}; this.on = {};
    this.dataset = {}; this.style = { setProperty() {} }; this.hidden = false; this.ownText = ""; this.scrollTop = 0; this.offsetHeight = 0; this.clientHeight = 0; this.scrollHeight = 0; }
  get tagName() { return this.tag.toUpperCase(); }
  get id() { return this.attrs.id || ""; }
  set id(v) { this.attrs.id = String(v); }
  get value() { return this.attrs.value == null ? "" : this.attrs.value; }
  set value(v) { this.attrs.value = String(v); }
  get disabled() { return "disabled" in this.attrs; }
  set disabled(v) { if (v) this.attrs.disabled = ""; else delete this.attrs.disabled; }
  get title() { return this.attrs.title || ""; }
  set title(v) { this.attrs.title = String(v); }
  get className() { return this.attrs.class || ""; }
  set className(v) { this.attrs.class = String(v); }
  get classList() { const n = this; const list = () => n.className.split(/\s+/).filter(Boolean);
    return { contains: (c) => list().includes(c), add: (c) => { if (!list().includes(c)) n.className = [...list(), c].join(" "); },
      remove: (c) => { n.className = list().filter((x) => x !== c).join(" "); },
      toggle: (c, on) => { const want = on === undefined ? !list().includes(c) : !!on; if (want) n.classList.add(c); else n.classList.remove(c); return want; } }; }
  get textContent() { return this.ownText + this.kids.map((k) => k.textContent).join(""); }
  set textContent(v) { this.kids.forEach((k) => { k.parent = null; }); this.kids = []; this.ownText = String(v); }
  get children() { return this.kids.filter((k) => k.tag !== "#text"); }
  get firstElementChild() { return this.children[0] || null; }
  get lastElementChild() { return this.children[this.children.length - 1] || null; }
  get parentElement() { return this.parent; }
  get parentNode() { return this.parent; }
  get isConnected() { let n = this; while (n.parent) n = n.parent; return n === this.doc.body; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  hasAttribute(k) { return k in this.attrs; }
  removeAttribute(k) { delete this.attrs[k]; }
  append(...nodes) { for (const n of nodes) { const node = n instanceof FakeNode ? n : this.doc.createTextNode(n); if (node.parent) node.remove(); node.parent = this; this.kids.push(node); } }
  appendChild(n) { this.append(n); return n; }
  replaceChildren(...nodes) { this.kids.forEach((k) => { k.parent = null; }); this.kids = []; this.ownText = ""; this.append(...nodes); }
  remove() { if (this.parent) this.parent.kids = this.parent.kids.filter((k) => k !== this); this.parent = null; }
  addEventListener(type, fn) { (this.on[type] = this.on[type] || []).push(fn); }
  removeEventListener(type, fn) { this.on[type] = (this.on[type] || []).filter((f) => f !== fn); }
  fire(type, init = {}) { // up through the parents to the document, as a real event bubbles
    const event = { type, target: this, stopped: false, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.stopped = true; }, ...init };
    for (let n = this; n && !event.stopped; n = n.parent) { event.currentTarget = n; for (const fn of n.on[type] || []) fn(event); }
    if (!event.stopped) { event.currentTarget = this.doc; for (const fn of this.doc.on[type] || []) fn(event); }
    return event; }
  click() { if (!this.disabled) this.fire("click"); }
  focus() { this.doc.activeElement = this; }
  blur() { if (this.doc.activeElement === this) this.doc.activeElement = this.doc.body; }
  setSelectionRange() {} scrollIntoView() {} scrollTo() {}
  contains(n) { for (let at = n; at; at = at.parent) if (at === this) return true; return false; }
  before(...nodes) { const up = this.parent; if (!up) return; for (const n of nodes) up.insertBefore(n instanceof FakeNode ? n : this.doc.createTextNode(n), this); }
  prepend(...nodes) { const old = this.kids; this.kids = []; this.append(...nodes); this.kids.push(...old); }
  insertBefore(n, before) { if (n.parent) n.remove(); n.parent = this; const at = this.kids.indexOf(before); this.kids.splice(at < 0 ? this.kids.length : at, 0, n); return n; }
  get nextElementSibling() { const up = this.parent ? this.parent.children : []; return up[up.indexOf(this) + 1] || null; }
  get previousElementSibling() { const up = this.parent ? this.parent.children : []; return up[up.indexOf(this) - 1] || null; }
  getBoundingClientRect() { return { top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0 }; }
  all(out = []) { for (const k of this.kids) { if (k.tag !== "#text") { out.push(k); k.all(out); } } return out; }
  matches(selector) { return selector.split(",").some((one) => matchChain(this, one.trim().split(/\s+/).filter((p) => p !== ">"))); }
  closest(selector) { for (let n = this; n; n = n.parent) if (n.tag !== "#doc" && n.matches(selector)) return n; return null; }
  querySelector(selector) { return this.all().find((n) => n.matches(selector)) || null; }
  querySelectorAll(selector) { return this.all().filter((n) => n.matches(selector)); }
}

function matchOne(node, part) {
  for (const piece of part.match(/:not\([^)]*\)|\[[^\]]*\]|#[^.#[:]+|\.[^.#[:]+|^[a-z0-9]+/gi) || []) {
    if (piece.startsWith(":not(")) { if (piece === ":not(:disabled)") { if (node.disabled) return false; } continue; }
    if (piece[0] === "#") { if (node.id !== piece.slice(1)) return false; }
    else if (piece[0] === ".") { if (!node.classList.contains(piece.slice(1))) return false; }
    else if (piece[0] === "[") { const m = piece.match(/^\[([\w-]+)(?:="?([^"\]]*)"?)?\]$/); if (!m) return false;
      const name = m[1].startsWith("data-") ? m[1].slice(5).replace(/-(\w)/g, (_, c) => c.toUpperCase()) : null;
      const have = name ? node.dataset[name] : node.getAttribute(m[1]);
      if (have == null || (m[2] !== undefined && have !== m[2])) return false; }
    else if (node.tag !== piece.toLowerCase()) return false;
  }
  return true;
}

function matchChain(node, parts) {
  if (!parts.length || !matchOne(node, parts[parts.length - 1])) return false;
  let at = node.parent, i = parts.length - 2;
  while (i >= 0 && at) { if (matchOne(at, parts[i])) i -= 1; at = at.parent; }
  return i < 0;
}

function makeDocument() {
  const doc = { on: {}, activeElement: null, addEventListener(t, f) { (this.on[t] = this.on[t] || []).push(f); }, removeEventListener() {},
    createElement: (tag) => new FakeNode(tag, doc), createElementNS: (_, tag) => new FakeNode(tag, doc),
    createTextNode: (text) => { const n = new FakeNode("#text", doc); n.ownText = String(text); return n; },
    getElementById(id) { let found = doc.body.all().find((n) => n.id === id); // the page's fixed elements appear when first asked for
      if (!found && doc.fixed.includes(id)) { found = new FakeNode("div", doc); found.id = id; doc.body.append(found); } return found || null; },
    querySelector: (s) => doc.body.querySelector(s), querySelectorAll: (s) => doc.body.querySelectorAll(s), fixed: [] };
  doc.body = new FakeNode("body", doc); doc.documentElement = new FakeNode("html", doc); doc.scrollingElement = doc.documentElement; doc.activeElement = doc.body;
  return doc;
}

const INDEX = readFileSync(new URL("../../static/index.html", import.meta.url), "utf8");

function buildBody(doc) {
  // UI A: the page's real markup, so a test presses the composer's real menus. index.html is plain and regular, so a
  // tokenizer is enough: tags, their attributes, text. The head is skipped.
  const body = INDEX.slice(INDEX.indexOf("<body>") + 6, INDEX.indexOf("<script type=\"module\""));
  const stack = [doc.body];
  for (const m of body.matchAll(/<\/([a-z0-9]+)>|<([a-z0-9]+)((?:\s+[a-zA-Z-:]+(?:="[^"]*")?)*)\s*(\/?)>|([^<]+)/g)) {
    if (m[1]) { stack.pop(); continue; }
    if (m[5]) { if (m[5].trim()) stack[stack.length - 1].append(m[5]); continue; }
    const node = doc.createElement(m[2]);
    for (const a of m[3].matchAll(/([a-zA-Z-:]+)(?:="([^"]*)")?/g)) {
      if (a[1] === "hidden") node.hidden = true;
      else if (a[1].startsWith("data-")) node.dataset[a[1].slice(5)] = a[2];
      else node.setAttribute(a[1], a[2] == null ? "" : a[2]);
    }
    stack[stack.length - 1].append(node);
    if (!m[4] && !["input", "br", "meta", "link"].includes(m[2])) stack.push(node);
  }
}
const FIXED_IDS = [...INDEX.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]);
let loads = 0;

function makeWindow(size, on = {}) {
  return { ...size, scrollY: 0, scrollTo() {}, addEventListener(type, fn) { (on[type] = on[type] || []).push(fn); }, removeEventListener() {},
    matchMedia: () => ({ matches: false, addEventListener() {} }), getComputedStyle: () => ({}), confirm: () => false, location: { reload() {}, hash: "" }, requestAnimationFrame: (f) => { f(); return 0; } };
}

export async function loadPage({ answers = {} } = {}) {
  // A fresh page. `answers` maps a path's start to the JSON the server gives; `page.posts` lists what the page sent.
  const doc = makeDocument();
  doc.fixed = FIXED_IDS;
  buildBody(doc);
  for (const id of ["sheet", "toast"]) doc.getElementById(id).hidden = true;
  Object.assign(globalThis, { Node: FakeNode, CSS: { escape: (s) => String(s) } });
  const posts = [], gets = [];
  const fetch = async (url, options = {}) => {
    const path = String(url);
    if (options.method === "POST") posts.push({ path, body: JSON.parse(options.body || "{}") }); else gets.push(path);
    const key = Object.keys(answers).find((k) => path.startsWith(k));
    const doc2 = key ? answers[key] : { run_id: "run-1", pid: 1, display: "sr …", copy: "sr …", parts: [], argv: [], exit: 0, code: 0, tasks: [], runs: [] };
    if (doc2 && doc2.httpStatus) return { ok: false, status: doc2.httpStatus, json: async () => doc2, text: async () => JSON.stringify(doc2), headers: { get: () => "application/json" } };
    return { ok: true, status: 200, json: async () => doc2, text: async () => JSON.stringify(doc2), headers: { get: () => "application/json" } };
  };
  // Each page has its own document, fetch and timers, so one test's late work never lands in the next test's page. The
  // timers wait for page.settle(), so a poll never loops on its own. `window` is empty while it loads: a page boots only in a browser.
  const timers = [];
  globalThis.pageNext = { document: doc, fetch, timers };
  const own = "const { document, fetch, timers: pageTimers } = globalThis.pageNext; let window;\n"
    + "const setTimeout = (f) => { pageTimers.push(f); return 0; }, clearTimeout = () => {}, setInterval = () => 0, clearInterval = () => {};\n";
  const code = `${own}${SOURCE}\nexport { ${OWN.filter((name) => new RegExp(`(function|const) ${name}\\b`).test(SOURCE)).join(", ")} };\nexport function setWindow(w) { window = w; }\n// load ${loads += 1}\n`;
  const module = await import(`data:text/javascript,${encodeURIComponent(code)}`);
  const windowOn = {};  // what the page listens for on window, across a resize (the small UI cleanup, row 11)
  module.setWindow(makeWindow({ innerHeight: 800, innerWidth: 1280 }, windowOn));
  Object.assign(globalThis, { requestAnimationFrame: (f) => { f(); return 0; }, cancelAnimationFrame() {},
    ResizeObserver: class { observe() {} disconnect() {} unobserve() {} }, IntersectionObserver: class { observe() {} disconnect() {} unobserve() {} },
    getComputedStyle: () => ({}), localStorage: { getItem: () => null, setItem() {}, removeItem() {} }, sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} } });
  doc.addEventListener("keydown", module.onKey);
  const size = { innerHeight: 800, innerWidth: 1280 };
  return { ...module, doc, posts, gets, el: (id) => doc.getElementById(id),
    resize: (width, height = 800) => { Object.assign(size, { innerWidth: width, innerHeight: height }); module.setWindow(makeWindow(size, windowOn)); },
    windowEvent: (type) => (windowOn[type] || []).forEach((fn) => fn({ type })),
    find: (text, root = doc.body) => root.all().find((n) => (n.tag === "button" || n.getAttribute("role") === "menuitem") && n.textContent.trim() === text) || null,
    buttons: (text, root = doc.body) => root.all().filter((n) => n.tag === "button" && n.textContent.trim() === text),
    settle: async () => { for (let i = 0; i < 12; i += 1) { await new Promise((r) => setImmediate(r)); timers.splice(0).forEach((f) => f()); } },
    key: (key, target = doc.activeElement) => { const n = target || doc.body; return n.fire("keydown", { key, code: key, shiftKey: false, altKey: false, metaKey: false, ctrlKey: false, isComposing: false }); } };
}
