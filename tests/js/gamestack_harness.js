// A DOM small enough to run mobile.js's game-stack panel headlessly.
//
// Same idea as sleepers_harness.js: the anchor is not invented here -- the
// pytest side pulls `[data-fb-gamestack]` out of the SERVED page, so this
// fails if the serve-time transform stops firing or the design document
// moves the slate heading. The feeds overlay is stubbed at the fetch, so
// what renders is what the server would have sent.
//
// Usage: node gamestack_harness.js <fixture.json>
//   fixture.json = { hasAnchor: bool, feeds: {game_stack: ...} | {}, selector?: string }
//   selector defaults to the schedule tab's '[data-fb-gamestack]'; the
//   FFBets per-game panel passes '[data-fb-gamebets]'.
//   steps?: [{click: "<button text>"} | {type: {nth: n, value: "5.5"}}]
//   runs in order after the first render, dumping the panel after each.

'use strict';
const fs = require('fs');
const vm = require('vm');

const fixture = JSON.parse(fs.readFileSync(process.argv[2], 'utf-8'));

function el(tag) {
  const attrs = {};
  return {
    tag, id: '', className: '', href: '', target: '', rel: '', type: '', value: '', style: {}, dataset: {},
    attrs, children: [], parentElement: null, _text: '', onclick: null,
    get textContent() { return this._text || this.children.map((c) => c.textContent).join(' '); },
    set textContent(v) { this._text = v; this.children = []; },
    appendChild(c) { c.parentElement = this; this.children.push(c); return c; },
    insertBefore(c, before) {
      c.parentElement = this;
      const at = before ? this.children.indexOf(before) : -1;
      if (at < 0) this.children.push(c); else this.children.splice(at, 0, c);
      return c;
    },
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return k in attrs ? attrs[k] : null; },
    // A node rather than null: the team-picker card wires a click onto its
    // own button, and innerHTML is opaque to the stub (same as sources_harness).
    querySelector(sel) { return el(sel); },
    querySelectorAll() { return []; },
    classList: { add() {}, remove() {}, toggle() { return false; } },
    addEventListener() {},
    remove() {},
  };
}

const selector = fixture.selector || '[data-fb-gamestack]';
const anchor = fixture.hasAnchor ? el('div') : null;
if (anchor) anchor.setAttribute(selector.slice(1, -1), '');

const document = {
  documentElement: { dataset: {} },
  body: { classList: { add() {}, remove() {}, toggle() { return false; } }, appendChild(n) { return n; } },
  visibilityState: 'visible',
  getElementById() { return null; },
  createElement: el,
  querySelector(sel) {
    if (sel === selector) return anchor;
    if (sel === 'aside') return el('aside');
    return null;
  },
  querySelectorAll() { return []; },
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
  // The overlay pull: resolve with the fixture's feeds, like the server would.
  fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve(fixture.feeds) }),
  console, JSON, Math, Object, Array, String, Number, Boolean, Date, parseInt, isNaN, Promise, setTimeout,
};
sandbox.window.document = document;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/mobile.js', 'utf-8'), sandbox, { filename: 'mobile.js' });

function drain() {
  observers.forEach((fn) => fn([]));
  for (let i = 0; i < 20 && frames.length; i++) frames.splice(0).forEach((fn) => fn());
}
function dump(node) {
  return { tag: node.tag, cls: node.className, text: node._text, href: node.href, value: node.value, attrs: node.attrs, kids: node.children.map(dump) };
}

// Let the fetch resolve (microtask), then decorate, then report.
setTimeout(() => {
  drain();
  const out = { anchor: anchor ? dump(anchor) : null };
  // Also exercise the league chips: click the second chip and re-dump.
  if (anchor && !fixture.steps) {
    const chips = [];
    (function walk(n) { if (String(n.className).indexOf('fb-gs-chip') === 0) chips.push(n); n.children.forEach(walk); })(anchor);
    // Click the chip that is NOT already on (the second league).
    const off = chips.find((c) => c.className === 'fb-gs-chip');
    if (off && off.onclick) { off.onclick(); drain(); out.afterChip = dump(anchor); }
  }
  if (anchor && fixture.steps) {
    out.steps = [];
    fixture.steps.forEach((step) => {
      const found = [];
      (function walk(n) { found.push(n); n.children.forEach(walk); })(anchor);
      if (step.click) {
        const btn = found.find((n) => n.tag === 'button' && n._text === step.click);
        if (!btn) throw new Error('no button named ' + step.click);
        btn.onclick(); drain();
      } else if (step.type) {
        const box = found.filter((n) => n.tag === 'input')[step.type.nth];
        if (!box) throw new Error('no input #' + step.type.nth);
        box.value = step.type.value; box.oninput();
      }
      out.steps.push(dump(anchor));
    });
  }
  process.stdout.write(JSON.stringify(out));
}, 5);
