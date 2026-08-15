// Fantasy Bible service worker — network-first, cache as offline fallback.
//
// Written for this repo's layout rather than copied from the design project.
// That copy precaches './Fantasy%20Bible.dc.html' and './frontend/lib/fbApi.js',
// neither of which exists here: the page is served as index.html at /app/ and
// the client sits at /app/lib/. Since cache.addAll() rejects if any single
// entry 404s, that version's install event would fail and the worker would
// never activate — silently, with the page working fine otherwise.
//
// Behaviour matches the original: always fresh when online, still usable off.

const VERSION = 'fb-v9';

// Enough to open the app offline. Everything else is cached as you browse.
const SHELL = [
  './',
  './support.js',
  './mobile.css',
  './mobile.js',
  './manifest.webmanifest',
  './data/feeds.json',
  './lib/fbApi.js',
  './_ds/modernist-72a114b0-9435-4a8a-a2b5-713f996af4a4/styles.css',
  './_ds/modernist-72a114b0-9435-4a8a-a2b5-713f996af4a4/_ds_bundle.js',
  './icons/icon-192.png',
  './icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(VERSION).then((cache) =>
      // Deliberately not addAll: one missing file must not abort the install
      // and leave the worker permanently inactive. Cache what we can.
      Promise.all(
        SHELL.map((url) => cache.add(url).catch(() => undefined))
      )
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;

  // Only GETs are cacheable, and only our own origin. Yahoo and Sleeper calls
  // fall through untouched — stale fantasy data is worse than none.
  if (request.method !== 'GET') return;
  if (new URL(request.url).origin !== self.location.origin) return;

  event.respondWith(
    fetch(request)
      .then((response) => {
        // Only store real successes; a cached 404 or redirect is a trap.
        if (response && response.status === 200 && response.type === 'basic') {
          const copy = response.clone();
          caches.open(VERSION).then((cache) => cache.put(request, copy));
        }
        return response;
      })
      .catch(() =>
        caches.match(request).then(
          (hit) => hit || caches.match('./')
        )
      )
  );
});
