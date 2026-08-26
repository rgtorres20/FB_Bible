// A DOM small enough to run mobile.js's Sleepers panel headlessly.
//
// Same idea as sources_harness.js: stub only what the code touches, and
// let anything else throw. The anchor is not invented here -- the pytest
// side pulls `[data-fb-sleepers]` out of the SERVED page (the committed
// index.html plus page.PRE), so this fails if the serve-time transform
// stops firing or the design document moves the row it lands beside.
//
// Usage: node sleepers_harness.js <fixture.json>
//   fixture.json = { hasAnchor: bool, payload: {watched, posts} }

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
    type: '',
    value: '',
    placeholder: '',
    disabled: false,
    style: {},
    dataset: {},
    attrs: {},
    children: [],
    parentElement: null,
    _text: '',
    get textContent() {
      if (this._text) return this._text;
      return this.children.map((c) => c.textContent).join(' ');
    },
    set textContent(v) { this._text = v; this.children = []; },
    appendChild(child) { child.parentElement = this; this.children.push(child); return child; },
    insertBefore(child, before) {
      child.parentElement = this;
      const at = before ? this.children.indexOf(before) : -1;
      if (at < 0) this.children.push(child); else this.children.splice(at, 0, child);
      return child;
    },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    // Real enough for the one lookup the panel makes: the add box, so a
    // half-typed name survives a refresh.
    querySelector(sel) {
      if (sel !== '.fb-sl-add input' && sel !== '.fb-src-msg') {
        // innerHTML is opaque to the stub, so hand back a node rather than
        // null -- the team-picker card wires a click onto its own button.
        return el(sel);
      }
      const hit = [];
      const walk = (n) => {
        if (sel === '.fb-sl-add input' && n.tag === 'input') hit.push(n);
        if (sel === '.fb-src-msg' && n.className === 'fb-src-msg') hit.push(n);
        n.children.forEach(walk);
      };
      this.children.forEach(walk);
      return hit[0] || null;
    },
    classList: { add() {}, remove() {}, toggle() { return false; } },
    addEventListener() {},
    remove() {},
  };
}

// The anchor the transform leaves in the served page, inside a parent the
// panel is inserted before.
const screen = el('div');
const anchor = el('div');
if (fixture.hasAnchor) screen.appendChild(anchor);

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
    let idv = '';
    Object.defineProperty(n, 'id', {
      get: () => idv,
      set: (v) => { idv = v; if (v) byId.set(v, n); },
    });
    return n;
  },
  querySelector(sel) {
    if (sel === 'aside') return el('aside');
    if (sel === '[data-fb-sleepers]') return fixture.hasAnchor ? anchor : null;
    return null;
  },
  querySelectorAll() { return []; },
  addEventListener() {},
};

const frames = [];
const observers = [];
const requested = [];
const posted = [];
const handedToPage = [];
let edited = false;

// After an edit the server answers with the list MINUS the removed row,
// which is what proves the panel re-renders from the response rather than
// from what it already had.
function served() {
  if (!edited) return fixture.payload;
  return {
    watched: (fixture.payload.watched || []).slice(1),
    posts: fixture.payload.posts || [],
  };
}

const sandbox = {
  document,
  window: { addEventListener() {}, open() {} },
  location: { origin: 'https://example.test' },
  localStorage: { getItem: () => null, setItem() {} },
  matchMedia: () => ({ matches: false, addEventListener() {} }),
  requestAnimationFrame: (fn) => { frames.push(fn); },
  MutationObserver: function (fn) { observers.push(fn); this.observe = function () {}; },
  fetch: (url, opts) => {
    requested.push(url);
    if (String(url).indexOf('/app/data/sleepers.json') === 0) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(served()) });
    }
    if (String(url).indexOf('/app/mine/sleepers') === 0) {
      posted.push(String(opts && opts.body));
      edited = true;
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(served()) });
    }
    return Promise.reject(new Error('no network in the harness'));
  },
  URLSearchParams,
  Promise, setTimeout,
  console, JSON, Math, Object, Array, String, Number, Boolean, Date, parseInt, isNaN,
};
sandbox.window.document = document;
// The hook `board.inject_sleepers` defines on the real page. The panel
// must hand it the fresh list so the page's own stars agree.
sandbox.window.__fbSetSleepers = (names) => { handedToPage.push(names); };

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/mobile.js', 'utf-8'), sandbox, { filename: 'mobile.js' });

(async () => {
  // mobile.js decorates on mutation, debounced through requestAnimationFrame.
  // The panel then fetches, so the queue has to be drained across turns of
  // the microtask loop rather than once.
  for (let round = 0; round < 6; round++) {
    observers.forEach((fn) => fn([]));
    for (let i = 0; i < 20 && frames.length; i++) frames.splice(0).forEach((fn) => fn());
    await new Promise((r) => setImmediate(r));
  }

  // Click the first Remove, the way a reader would, then let the POST and
  // the re-render settle. This is the whole round trip: button -> server ->
  // fresh list -> panel redrawn -> page's own stars told.
  const host0 = byId.get('fb-sleepers');
  if (host0 && fixture.clickRemove) {
    const walk = (n, out) => { out.push(n); n.children.forEach((k) => walk(k, out)); return out; };
    const button = walk(host0, []).find((n) => n.tag === 'button' && n._text === 'Remove');
    if (button && button.onclick) button.onclick();
    for (let round = 0; round < 6; round++) {
      await new Promise((r) => setImmediate(r));
      observers.forEach((fn) => fn([]));
      for (let i = 0; i < 20 && frames.length; i++) frames.splice(0).forEach((fn) => fn());
    }
  }

  function dump(node) {
    return {
      cls: node.className,
      tag: node.tag,
      text: node._text,
      href: node.href,
      placeholder: node.placeholder,
      kids: node.children.map(dump),
    };
  }
  const host = byId.get('fb-sleepers');
  console.log(JSON.stringify({
    posted,
    handedToPage,
    rendered: !!host,
    // Inserted BEFORE the analysts' table, which is the owner's ask: the
    // tab should open on your own list.
    beforeAnchor: !!host && screen.children.indexOf(host) < screen.children.indexOf(anchor),
    requested,
    panel: host ? dump(host) : null,
  }));
})();
