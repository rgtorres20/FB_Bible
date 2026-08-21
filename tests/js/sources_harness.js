// A DOM small enough to run mobile.js's source panel headlessly.
//
// Same idea as room_harness.js: stub only what the code actually touches,
// and let anything else throw. The anchors are not invented here -- the
// pytest side pulls the real <span> elements out of the committed
// index.html and passes them in, so this fails if a design resync renames
// the row the panel hangs off.
//
// Usage: node sources_harness.js <fixture.json>
//   fixture.json = { anchors: [{style, text}], sources: [payload rows] }

'use strict';
const fs = require('fs');
const vm = require('vm');

const fixture = JSON.parse(fs.readFileSync(process.argv[2], 'utf-8'));

function el(tag) {
  return {
    tag,
    id: '',
    className: '',
    href: '',
    target: '',
    rel: '',
    style: {},
    dataset: {},
    children: [],
    parentElement: null,
    _text: '',
    get textContent() {
      if (this._text) return this._text;
      return this.children.map((c) => c.textContent).join(' ');
    },
    set textContent(v) { this._text = v; this.children = []; },
    get nextSibling() {
      const p = this.parentElement;
      if (!p) return null;
      return p.children[p.children.indexOf(this) + 1] || null;
    },
    appendChild(child) { child.parentElement = this; this.children.push(child); return child; },
    insertBefore(child, before) {
      child.parentElement = this;
      const at = before ? this.children.indexOf(before) : -1;
      if (at < 0) this.children.push(child); else this.children.splice(at, 0, child);
      return child;
    },
    setAttribute(k, v) { this[k] = v; },
    remove() {},
    // innerHTML is opaque to the stub, so hand back a node rather than
    // null -- the team-picker card wires a click onto its own button.
    querySelector(sel) { return el(sel); },
    classList: { add() {}, remove() {}, toggle() { return false; } },
    addEventListener() {},
  };
}

// The anchor rows, rebuilt from the real page: a styled element inside a
// row inside the screen. Both decorators walk anchor -> row -> row.parent,
// so that is the shape the stub has to have.
//   showRankSources() matches span[style*="0.14em"] -> "Source influence"
//   linkDraftTools()  matches div[style*="0.14em"]  -> "My team …"
const screen = el('div');
const anchors = fixture.anchors.map((a) => {
  const row = el('div');
  const node = el(a.tag);
  node._style = a.style;
  node.textContent = a.text;
  row.appendChild(node);
  screen.appendChild(row);
  return node;
});

const byId = new Map();

const document = {
  documentElement: { dataset: {} },
  body: {
    classList: { add() {}, remove() {}, toggle() { return false; } },
    appendChild(n) { return n; },
  },
  getElementById(id) { return byId.get(id) || null; },
  createElement(tag) {
    const n = el(tag);
    // Register on id assignment the same way a real document does.
    let idv = '';
    Object.defineProperty(n, 'id', {
      get: () => idv,
      set: (v) => { idv = v; if (v) byId.set(v, n); },
    });
    return n;
  },
  // The drawer IIFE polls for <aside> until it finds one; give it one so
  // it finishes instead of spinning the frame queue.
  querySelector(sel) { return sel === 'aside' ? el('aside') : null; },
  querySelectorAll(sel) {
    const m = /^(\w+)\[style\*="([^"]+)"\]$/.exec(sel);
    if (!m) return [];
    return anchors.filter((n) => n.tag === m[1] && n._style.indexOf(m[2]) !== -1);
  },
  addEventListener() {},
};

const frames = [];
const observers = [];

const sandbox = {
  document,
  window: { addEventListener() {}, open() {} },
  location: { origin: 'https://example.test' },
  localStorage: { getItem: () => null, setItem() {} },
  matchMedia: () => ({ matches: false, addEventListener() {} }),
  requestAnimationFrame: (fn) => { frames.push(fn); },
  MutationObserver: function (fn) { observers.push(fn); this.observe = function () {}; },
  fetch: () => Promise.reject(new Error('no network in the harness')),
  FB_RANK_SOURCES: fixture.sources,
  console, JSON, Math, Object, Array, String, Number, Boolean, Date, parseInt, isNaN,
};
sandbox.window.document = document;

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/mobile.js', 'utf-8'), sandbox, { filename: 'mobile.js' });

// mobile.js decorates on mutation, debounced through requestAnimationFrame.
// The harness has no mutations, so fire the observers the way the browser
// would and then drain the frame queue.
observers.forEach((fn) => fn([]));
for (let i = 0; i < 20 && frames.length; i++) frames.splice(0).forEach((fn) => fn());

function dump(node) {
  return {
    cls: node.className,
    text: node._text,
    href: node.href,
    kids: node.children.map(dump),
  };
}
const host = byId.get('fb-rank-sources');
// The draft-tool links are inserted as siblings of the "My team" header,
// so they are reported from wherever they landed rather than assumed.
const links = [...byId.values()]
  .filter((n) => n.tag === 'a' && n.id !== '')
  .map((n) => ({ id: n.id, href: n.href, target: n.target, text: n.textContent }));
console.log(JSON.stringify({
  rendered: !!host,
  panel: host ? dump(host) : null,
  links,
}));
