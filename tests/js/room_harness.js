// A DOM small enough to run the mock room's engine headlessly.
//
// The room is plain JS embedded in the page, so there is nothing to
// import: the test writes the page's two <script> bodies to disk and
// evaluates them here against these stubs. Only what the engine actually
// touches is implemented -- getElementById, createElement/appendChild,
// dataset, localStorage, window.open -- and anything it reaches for that
// is missing throws, which is the point.

'use strict';
const fs = require('fs');
const vm = require('vm');

function el(id) {
  const node = {
    id, value: '', textContent: '', className: '',
    hidden: false, disabled: false, title: '', style: {},
    dataset: {}, children: [],
    appendChild(child) { this.children.push(child); return child; },
    setAttribute(k, v) { this[k] = v; },
  };
  // The engine empties a container with innerHTML = '' before refilling
  // it. A plain property would keep the old children in this stub, so a
  // list rendered twice would read as one list twice as long -- and a
  // test observing what the page shows would be observing an artefact
  // of the stub rather than of the engine.
  let html = '';
  Object.defineProperty(node, 'innerHTML', {
    get() { return html; },
    set(value) { html = String(value); if (!html) node.children.length = 0; },
  });
  return node;
}

function makeDocument() {
  const nodes = new Map();
  return {
    documentElement: { dataset: {} },
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, el(id));
      return nodes.get(id);
    },
    createElement(tag) { const n = el(''); n.tag = tag; return n; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    _nodes: nodes,
  };
}

function run(payloadPath, enginePath) {
  const document = makeDocument();
  const store = {};
  const sandbox = {
    document,
    localStorage: {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); },
    },
    console,
    Math, JSON, Object, Array, String, Number, Boolean, Date, parseInt,
    parseFloat, isNaN, RegExp, Error, encodeURIComponent, setTimeout,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.window.open = () => ({
    document: { write() {}, close() {} },
  });
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(payloadPath, 'utf8'), sandbox);
  vm.runInContext(fs.readFileSync(enginePath, 'utf8'), sandbox);
  return { sandbox, document, room: sandbox.window.FB_ROOM };
}

module.exports = { run };
