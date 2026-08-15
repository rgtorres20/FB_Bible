# Browser client

Wires `Fantasy Bible.dc.html` to the server. Dependency-free, no build step,
one file: [fbApi.js](fbApi.js).

```bash
cd web && node --test    # 16 tests
```

## Dropping it into the app

The app is a single HTML file, so either approach works.

**As a module** — if the page can use `<script type="module">`:

```html
<script type="module">
  import { createClient, createYahooCache } from './fbApi.js';
  window.fb = createClient({ baseUrl: 'https://<project>.vercel.app' });
</script>
```

**Inlined** — paste the contents of `fbApi.js` into a `<script>` tag in the
page, drop the `export` keywords, and use the `window.FBApi` global the file
sets on load:

```js
const fb = window.FBApi.createClient({ baseUrl: 'https://<project>.vercel.app' });
```

`baseUrl` must be the deployed server origin, and that origin must be listed in
the server's `CORS_ORIGINS` or the browser will block every call.

## The shape it expects you to write

Show a link button when there's no Yahoo account, real data when there is:

```js
const fb = FBApi.createClient({ baseUrl: SERVER });

async function loadDraftBoard(leagueKey) {
  try {
    const { picks } = await fb.draft(leagueKey);
    renderDraftBoard(picks);          // pick, round, team_key, player_key
  } catch (err) {
    if (err instanceof FBApi.NotLinkedError) {
      showLinkYahooButton(fb.loginUrl());   // a redirect, not a fetch
      return;
    }
    showWireUnreachable(err.message);       // same treatment as a Sleeper failure
  }
}
```

After the user comes back from linking, call `fb.clearCache()` — otherwise the
cached 401-era responses stick around for the cache window.

## Methods

| Call | Returns |
|---|---|
| `status()` | `{linked, guid, access_token_expired, expires_at}` |
| `loginUrl()` | URL to redirect to — not a fetch |
| `logout()` | `{linked: false}` |
| `leagues()` | `{leagues: [...]}` on the linked account |
| `configuredLeagues()` | Just Sunday Gravy and The Trenches |
| `teams(leagueKey)` | Every team in a league |
| `draft(leagueKey)` | `{picks: [...]}` in pick order |
| `roster(teamKey, week?)` | `{players: [...]}` with position, status, bye |
| `scoreboard(leagueKey, week?)` | Matchups |
| `transactions(leagueKey)` | Adds, drops, trades |
| `raw(path)` | Unparsed passthrough |
| `health()` | Server config state |

Errors are `NotLinkedError` (401 — offer the login link) or `ApiError` with a
`.status`. A request that outlives `timeoutMs` (default 15s) aborts.

## Caching Yahoo data — read this before using localStorage

Yahoo requires user data be deleted within 24 hours of being obtained (see
[../docs/LICENSING.md](../docs/LICENSING.md)). `localStorage` keeps things
forever, so **do not put Yahoo responses in it directly.** Use the helper:

```js
const yahooCache = FBApi.createYahooCache();
yahooCache.purgeExpired();               // on app load

yahooCache.save('roster:t4', players);
const cached = yahooCache.load('roster:t4');   // null once >24h old, and deleted
```

`load()` deletes anything past the cap rather than returning it, so the rule
holds even if the tab is left open for days. `purgeExpired()` only touches
`fb_yahoo:` keys — the existing `ww_live` Sleeper cache is left alone, since
Sleeper's terms don't impose this.

In-memory state inside the running page is fine and needs no special handling;
it dies with the tab.
