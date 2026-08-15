/**
 * Tests for the browser client. Uses node:test, so there are no dependencies
 * and no build step -- `node --test web/`.
 */

import assert from 'node:assert/strict';
import { afterEach, describe, it } from 'node:test';

import {
  ApiError,
  NotLinkedError,
  YAHOO_MAX_RETENTION_MS,
  createClient,
  createYahooCache,
} from './fbApi.js';

const BASE = 'https://fb.example.com';

/** Minimal fetch stub that records calls and replays queued responses. */
function stubFetch(responses) {
  const queue = Array.isArray(responses) ? [...responses] : [responses];
  const calls = [];
  const impl = async (url, options) => {
    calls.push({ url, options });
    const next = queue.length > 1 ? queue.shift() : queue[0];
    return {
      ok: next.status >= 200 && next.status < 300,
      status: next.status,
      json: async () => next.body,
      text: async () => JSON.stringify(next.body ?? ''),
    };
  };
  impl.calls = calls;
  return impl;
}

function memoryStorage() {
  const map = new Map();
  return {
    get length() {
      return map.size;
    },
    key: (i) => [...map.keys()][i] ?? null,
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
  };
}

describe('createClient', () => {
  it('requires a baseUrl', () => {
    assert.throws(() => createClient({}), /baseUrl/);
  });

  it('strips trailing slashes so URLs never double up', async () => {
    const fetchImpl = stubFetch({ status: 200, body: { leagues: [] } });
    const api = createClient({ baseUrl: `${BASE}///`, fetchImpl, cacheTtlMs: 0 });

    await api.leagues();

    assert.equal(fetchImpl.calls[0].url, `${BASE}/api/leagues`);
  });

  it('maps 401 to NotLinkedError so the UI can offer the login link', async () => {
    const fetchImpl = stubFetch({ status: 401, body: { detail: 'not linked' } });
    const api = createClient({ baseUrl: BASE, fetchImpl, cacheTtlMs: 0 });

    await assert.rejects(() => api.leagues(), NotLinkedError);
  });

  it('raises ApiError with the status for other failures', async () => {
    const fetchImpl = stubFetch({ status: 502, body: { detail: 'yahoo down' } });
    const api = createClient({ baseUrl: BASE, fetchImpl, cacheTtlMs: 0 });

    await assert.rejects(
      () => api.leagues(),
      (err) => err instanceof ApiError && err.status === 502
    );
  });

  it('encodes league keys, which contain dots', async () => {
    const fetchImpl = stubFetch({ status: 200, body: { picks: [] } });
    const api = createClient({ baseUrl: BASE, fetchImpl, cacheTtlMs: 0 });

    await api.draft('nfl.l.192426');

    assert.equal(fetchImpl.calls[0].url, `${BASE}/api/leagues/nfl.l.192426/draft`);
  });

  it('appends week only when given one', async () => {
    const fetchImpl = stubFetch({ status: 200, body: { players: [] } });
    const api = createClient({ baseUrl: BASE, fetchImpl, cacheTtlMs: 0 });

    await api.roster('nfl.l.192426.t.4');
    await api.roster('nfl.l.192426.t.4', 3);

    assert.ok(!fetchImpl.calls[0].url.includes('week'));
    assert.ok(fetchImpl.calls[1].url.endsWith('?week=3'));
  });

  it('dedupes repeat calls inside the cache window', async () => {
    const fetchImpl = stubFetch({ status: 200, body: { leagues: [] } });
    const api = createClient({ baseUrl: BASE, fetchImpl, cacheTtlMs: 60000 });

    await api.leagues();
    await api.leagues();

    assert.equal(fetchImpl.calls.length, 1);
  });

  it('refetches after clearCache, which linking must trigger', async () => {
    const fetchImpl = stubFetch({ status: 200, body: { leagues: [] } });
    const api = createClient({ baseUrl: BASE, fetchImpl, cacheTtlMs: 60000 });

    await api.leagues();
    api.clearCache();
    await api.leagues();

    assert.equal(fetchImpl.calls.length, 2);
  });

  it('builds the login URL without fetching it', () => {
    const fetchImpl = stubFetch({ status: 200, body: {} });
    const api = createClient({ baseUrl: BASE, fetchImpl });

    assert.equal(api.loginUrl(), `${BASE}/auth/yahoo/login`);
    assert.equal(fetchImpl.calls.length, 0);
  });

  it('aborts a request that outlives the timeout', async () => {
    const fetchImpl = async (_url, { signal }) =>
      new Promise((_resolve, reject) => {
        signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
      });
    const api = createClient({ baseUrl: BASE, fetchImpl, timeoutMs: 20, cacheTtlMs: 0 });

    await assert.rejects(() => api.leagues(), /aborted/);
  });
});

describe('createYahooCache', () => {
  let store;
  afterEach(() => {
    store = null;
  });

  it('round-trips a value', () => {
    store = memoryStorage();
    const cache = createYahooCache(store);

    cache.save('roster', { players: [1, 2] });

    assert.deepEqual(cache.load('roster'), { players: [1, 2] });
  });

  it('drops entries older than Yahoo\'s 24h retention limit', () => {
    store = memoryStorage();
    const cache = createYahooCache(store);
    store.setItem(
      'fb_yahoo:roster',
      JSON.stringify({ at: Date.now() - YAHOO_MAX_RETENTION_MS - 1, value: { players: [] } })
    );

    assert.equal(cache.load('roster'), null);
    // and it is gone, not merely hidden
    assert.equal(store.getItem('fb_yahoo:roster'), null);
  });

  it('keeps entries just inside the limit', () => {
    store = memoryStorage();
    const cache = createYahooCache(store);
    store.setItem(
      'fb_yahoo:roster',
      JSON.stringify({ at: Date.now() - (YAHOO_MAX_RETENTION_MS - 60000), value: { ok: 1 } })
    );

    assert.deepEqual(cache.load('roster'), { ok: 1 });
  });

  it('discards corrupt entries instead of throwing', () => {
    store = memoryStorage();
    const cache = createYahooCache(store);
    store.setItem('fb_yahoo:roster', 'not json');

    assert.equal(cache.load('roster'), null);
  });

  it('purgeExpired sweeps only expired fb_yahoo keys', () => {
    store = memoryStorage();
    const cache = createYahooCache(store);
    store.setItem('fb_yahoo:old', JSON.stringify({ at: 0, value: 1 }));
    store.setItem('fb_yahoo:new', JSON.stringify({ at: Date.now(), value: 2 }));
    store.setItem('ww_live', 'sleeper data, not ours to purge');

    assert.equal(cache.purgeExpired(), 1);
    assert.equal(store.getItem('fb_yahoo:old'), null);
    assert.ok(store.getItem('fb_yahoo:new'));
    assert.ok(store.getItem('ww_live'));
  });

  it('no-ops without a storage backend', () => {
    const cache = createYahooCache(undefined);

    assert.doesNotThrow(() => cache.save('x', 1));
    assert.equal(cache.load('x'), null);
    assert.equal(cache.purgeExpired(), 0);
  });
});
