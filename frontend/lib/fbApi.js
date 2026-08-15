/**
 * FB Bible API client — the browser half of the Yahoo league link.
 *
 * Dependency-free and build-step-free, because it has to drop into
 * `Fantasy Bible.dc.html`, which is a single file.
 *
 * Two things it does that a bare fetch() wrapper would not:
 *
 *   1. Turns a 401 into NotLinkedError, so the UI can show "Link Yahoo"
 *      instead of a broken panel. The server returns 401 for "no token
 *      stored" and for "refresh finally failed" — both mean the same thing
 *      to a user.
 *   2. Enforces Yahoo's 24-hour retention rule on anything cached in the
 *      browser. Yahoo requires user data be removed within 24h of being
 *      obtained; localStorage would otherwise keep it forever. See
 *      docs/LICENSING.md.
 */

/** Yahoo's terms: user data must be removed within 24h of being obtained. */
export const YAHOO_MAX_RETENTION_MS = 24 * 60 * 60 * 1000;

/** No Yahoo account linked — send the user to loginUrl(). */
export class NotLinkedError extends Error {
  constructor(message = 'No Yahoo account linked') {
    super(message);
    this.name = 'NotLinkedError';
  }
}

/** Any other non-2xx from the server. */
export class ApiError extends Error {
  constructor(status, body) {
    super(`FB Bible API returned ${status}: ${String(body).slice(0, 200)}`);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

/**
 * @param {object}   options
 * @param {string}   options.baseUrl      Deployed server origin, no trailing slash.
 * @param {function} [options.fetchImpl]  Injectable for tests.
 * @param {number}   [options.timeoutMs]  Per-request timeout. Yahoo can be slow.
 * @param {number}   [options.cacheTtlMs] In-memory dedupe window. 0 disables.
 */
export function createClient({
  baseUrl,
  fetchImpl = globalThis.fetch,
  timeoutMs = 15000,
  cacheTtlMs = 60000,
} = {}) {
  if (!baseUrl) throw new Error('createClient requires a baseUrl');
  const root = baseUrl.replace(/\/+$/, '');
  const cache = new Map();

  async function request(path, { signal } = {}) {
    const cached = cache.get(path);
    if (cached && Date.now() - cached.at < cacheTtlMs) return cached.value;

    // Compose the caller's signal with our own timeout, so a slow Yahoo call
    // cannot hang a panel forever.
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    if (signal) signal.addEventListener('abort', () => controller.abort(), { once: true });

    let response;
    try {
      response = await fetchImpl(`${root}${path}`, {
        method: 'GET',
        credentials: 'include',
        headers: { Accept: 'application/json' },
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }

    if (response.status === 401) throw new NotLinkedError();
    if (!response.ok) throw new ApiError(response.status, await safeText(response));

    const value = await response.json();
    if (cacheTtlMs > 0) cache.set(path, { value, at: Date.now() });
    return value;
  }

  async function safeText(response) {
    try {
      return await response.text();
    } catch {
      return '';
    }
  }

  return {
    /** Drop cached responses — call after linking or unlinking. */
    clearCache: () => cache.clear(),

    /** Send the browser here to start the OAuth flow. Not a fetch: it redirects. */
    loginUrl: () => `${root}/auth/yahoo/login`,

    /** {linked: boolean, ...}. Never throws NotLinkedError — that's the question. */
    status: () => request('/auth/yahoo/status'),

    /** Server config check. Reports missing credentials rather than 500ing. */
    health: () => request('/health'),

    async logout() {
      const response = await fetchImpl(`${root}/auth/yahoo/logout`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!response.ok) throw new ApiError(response.status, await safeText(response));
      cache.clear();
      return response.json();
    },

    leagues: () => request('/api/leagues'),
    configuredLeagues: () => request('/api/leagues/configured'),
    teams: (leagueKey) => request(`/api/leagues/${encodeURIComponent(leagueKey)}/teams`),

    /** Every pick in order — this is what retires manual pick entry. */
    draft: (leagueKey) => request(`/api/leagues/${encodeURIComponent(leagueKey)}/draft`),

    roster: (teamKey, week) =>
      request(
        `/api/teams/${encodeURIComponent(teamKey)}/roster${week ? `?week=${week}` : ''}`
      ),

    scoreboard: (leagueKey, week) =>
      request(
        `/api/leagues/${encodeURIComponent(leagueKey)}/scoreboard${week ? `?week=${week}` : ''}`
      ),

    transactions: (leagueKey) =>
      request(`/api/leagues/${encodeURIComponent(leagueKey)}/transactions`),

    /** Escape hatch for resources the server hasn't modelled yet. */
    raw: (path) => request(`/api/raw/${String(path).replace(/^\/+/, '')}`),
  };
}

/**
 * localStorage for Yahoo-sourced data, with a hard 24-hour expiry.
 *
 * Use this rather than localStorage directly for anything that came from the
 * Yahoo API. Reading an entry older than the cap deletes it and returns null,
 * so the retention rule holds even if the app is left open for days.
 *
 * @param {Storage} [store] Injectable for tests.
 */
export function createYahooCache(store = globalThis.localStorage) {
  const PREFIX = 'fb_yahoo:';

  return {
    save(key, value) {
      if (!store) return;
      store.setItem(PREFIX + key, JSON.stringify({ at: Date.now(), value }));
    },

    load(key) {
      if (!store) return null;
      const raw = store.getItem(PREFIX + key);
      if (!raw) return null;

      let parsed;
      try {
        parsed = JSON.parse(raw);
      } catch {
        store.removeItem(PREFIX + key);
        return null;
      }

      if (!parsed || Date.now() - parsed.at >= YAHOO_MAX_RETENTION_MS) {
        store.removeItem(PREFIX + key);
        return null;
      }
      return parsed.value;
    },

    /** Sweep every expired entry. Call on app load. */
    purgeExpired() {
      if (!store) return 0;
      const doomed = [];
      for (let i = 0; i < store.length; i += 1) {
        const key = store.key(i);
        if (!key || !key.startsWith(PREFIX)) continue;
        try {
          const { at } = JSON.parse(store.getItem(key));
          if (Date.now() - at >= YAHOO_MAX_RETENTION_MS) doomed.push(key);
        } catch {
          doomed.push(key);
        }
      }
      doomed.forEach((key) => store.removeItem(key));
      return doomed.length;
    },
  };
}

// Classic-script fallback: the app is one HTML file and may not use modules.
if (typeof globalThis !== 'undefined') {
  globalThis.FBApi = { createClient, createYahooCache, NotLinkedError, ApiError, YAHOO_MAX_RETENTION_MS };
}
