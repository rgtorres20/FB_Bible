# Resume here

Last worked: **Sat Aug 15 2026, ~1am CDT.**

## Scope check, so this file is not misread

**Yahoo is one integration, not the product.** The product is the Fantasy
Bible, and its core loop is **Alerts**: news arrives, you judge it, and it
drives roster, draft-board and target changes. Yahoo removes manual roster and
pick entry from that loop; it does not define it.

## What is live right now

| | |
|---|---|
| App | <https://fb-bible-torro2.vercel.app/app> — installable to a phone home screen |
| API | <https://fb-bible-torro2.vercel.app/docs> — 15 endpoints |
| Store | Upstash Redis, encrypted token store |
| News | 5 publishers polled automatically, player-tagged, in Redis |
| Scheduler | GitHub Actions, running green |
| Cost | $0 |
| Tests | 119 Python + 16 JS, CI green on every push |

**The stale-data problem is solved server-side.** ESPN, Yahoo, Rotowire,
ProFootballTalk and CBS are polled without anyone asking, items are tagged
with the fantasy players they mention, and `/api/feeds` serves them with an
honest LIVE / STALE / FAILED state per source.

Note the real cadence: the cron says every 15 minutes, but GitHub drops
scheduled runs under load on free public repos. Observed: roughly hourly.

## Yahoo is BLOCKED on Yahoo, not on us

The app is registered (`developer.yahoo.com/apps/XSJqPLxv`), credentials are
in `.env` and live on Vercel, `/health` reports `yahoo_configured: true`, and
`/auth/yahoo/login` produces a correct authorize URL. Yahoo still refuses:

    invalid_scope invalid scope

Fantasy API access now requires an approved application at
<https://sports.yahoo.com/developer>. See `docs/LICENSING.md`. Until that is
granted there is no point touching the Yahoo code -- it is verified correct
against mocks and cannot be verified further without access.

**Do not spend time debugging this.** It is not a bug.

## Superseded: registering the app

**Register the Yahoo developer app** — <https://developer.yahoo.com/apps/create/>

- Application Type: **Web Application**
- Redirect URI: `https://fb-bible-torro2.vercel.app/auth/yahoo/callback`
  (copy it from `.env`; Yahoo matches character for character)
- API Permissions: **Fantasy Sports → Read**

Then paste the Client ID and Secret into `.env` (lines 4 and 5) and run:

```bash
python scripts/push_env_to_vercel.py
```

Then visit `/auth/yahoo/login`. Success = `/api/leagues` returning Sunday
Gravy and The Trenches by name. That endpoint had a parser bug that returned
an empty list for real Yahoo data; it is fixed and covered by a test, so it
should work first time.

## Action items from the Aug 15 session (user-requested)

1. **Pickup queue working for both leagues** (Sunday Gravy + The Trenches).
   The tab exists with 0 items; queue is per-league with triggers per
   CLAUDE.md. Needs design-project sync for the UI wiring plus, ideally,
   Yahoo access for live adds — but trigger-on-wire-news can work today
   against the live feed.
2. **More stale tabs → live**, in value order:
   - *Scout finds / ADP*: DONE (Aug 15, `app/feeds/adp.py`). FFC free ADP
     for both league sizes averaged per the owner's instruction ("combine
     the 2 based on avg"); daily snapshots in the feed store drive
     risers/fallers (movers appear once ~1+ day of history exists);
     Sleeper-rank-vs-ADP gaps + wire sleeper articles fill "Sleeper find".
   - *Vegas lines (FFBets · Predictions)*: DONE (Aug 15, `app/feeds/vegas.py`).
     ESPN scoreboard JSON (DraftKings spread+total); page's VEGAS table
     rebound to F.vegas at serve time, committed table as fallback.
     Prop-angle column carries facts only (kickoffs, slate superlatives).
     DELIVERY QUIRK, hard-won: ESPN 403s Vercel's IP range outright, and
     ALSO 403s faked browser headers from anywhere (TLS fingerprint check)
     while the honest tool UA passes from residential/runner IPs. So the
     slate is fetched by the sync-feeds workflow runner
     (scripts/push_vegas.py) and POSTed to /internal/vegas. VERIFY next
     session: the hourly workflow's "Push Vegas slate" step succeeds from
     GitHub's IPs (a manual local run seeded the first slate).
   - *Week 1 schedule*: same ESPN endpoint, trivial, low value until Sep.
   - *AI verdicts note*: verdicts.yml deployed but GitHub's scheduler had
     not fired it as of two cycles later (0 runs). New-workflow cron lag is
     normal; if it stays at 0 runs for a day, trigger once by hand (Actions
     → AI verdicts → Run workflow) which also confirms the models: read
     permission works.
3. **AI layer, free ("make it better but free")**: user asked for a
   zero-cost plan. Preferred route: **GitHub Models** — free LLM inference
   authenticated with the workflow's own `GITHUB_TOKEN` inside the existing
   sync-feeds Action, no card, no new secret. Rate limits are tight but an
   hourly job drafting ~10 verdict lines fits. The job would POST drafted
   verdicts to a new `/internal/verdicts` endpoint (same X-Sync-Token
   pattern), stored in Redis and overlaid on Alerts' lean/verdict columns
   prefixed "AI draft:". Fallbacks if quality disappoints: Groq or Google
   AI Studio free tiers (need one extra key each, still $0). The paid
   Claude/Haiku route stays documented as the quality upgrade path.
4. **Yahoo access application**: ready to paste from
   `docs/YAHOO_APPLICATION.md`. Submitting starts their review clock.

## Watchdog

`verify-live.yml` asserts 22 production checks every 2 hours (data fresh,
six sources not FAILED, overlays served, mobile injected, FFBets predict
mode). A failure emails the repo owner. Run it on demand from the Actions
tab.

## Next work, no dependencies — highest value first

1. **Point the page at `/api/feeds`.** The server holds 143 live tagged items
   the page does not read yet. This is the last mile of the stale-data fix.
   Drop-in snippet: `frontend/lib/README.md`.
2. **Cross-source dedupe.** The same story arrives from two outlets and shows
   twice.
3. **"New since last visit."** The poller already knows which ids are new; it
   needs a `first_seen` stamp so the UI can mark them.
4. **Rank by impact on your board**, not just time — you have 205 ranked
   players and player tags; joining them is the whole point.
5. **Timestamps on Out & returning** — the only tab without them, and the one
   where age matters most.

## Housekeeping worth doing when fresh

- **Rotate the Upstash password.** It was pasted into chat. Reset it in the
  Upstash console, then re-run `scripts/setup_redis.py`.
- **Remove `mcp__claude-in-chrome__javascript_tool`** from
  `~/.claude/settings.local.json`. It was added to extract the frontend files;
  that job is done, and it grants standing arbitrary-JS-in-browser access.
- **Delete the Vercel Protection Bypass secret** — unused, and its value was
  pasted into chat.

## Hard-won context worth not relearning

- Vercel installs from `pyproject.toml` via `uv` and **never reads
  `requirements.txt`**. An empty `dependencies` list deploys a function with no
  packages at all, visible only as `FUNCTION_INVOCATION_FAILED`.
- **Do not add a `vercel.json`.** A `builds` key silently disables `rewrites`
  (404 everywhere) and bundles only the entrypoint. Zero-config plus
  `[tool.vercel] entrypoint` is the working setup.
- Deployment Protection must stay **off**, or Yahoo's redirect hits a Vercel
  login wall.
- Upstash's console shows the redis-cli form, where TLS comes from a `--tls`
  flag. The server needs `rediss://`. `scripts/setup_redis.py` normalises this.
- On Windows, `npx` is `npx.CMD`; subprocess needs `cmd /c` to start it.
- Read deploy state from the GitHub commit status API, not by polling the
  endpoint. A ~2 second failure is config validation, not a build error.
- The frontend is a Claude Design `.dc` document: it loads `support.js` and a
  `_ds/` bundle. `manifest.webmanifest` and `sw.js` both shipped with paths
  from the design project's layout and had to be corrected for this one.

## Still true, deliberately not done

Multi-user auth (single-user first, decided Aug 14), commercial licensing
agreements with Yahoo and Sleeper (only if selling — see `docs/LICENSING.md`),
migration to a personal Claude account (`docs/MIGRATION.md`), and Phase 3 web
push.
