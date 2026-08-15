# Waiver Watch / Fantasy Bible — project rules

- Team watcher + fantasy draft tool for the 2026 NFL season (real players, real news — no mocked names).
- PRE-DRAFT MODE until the user says they drafted and lists their team: treat ALL notable players as "on the team" — alerts, analysis, and feeds cover the whole player pool, not a roster.
- The user's leagues have NO waivers and NO player cost (no FAAB, no bids, no waiver-clear times). Adds are free first-come pickups. Never show FAAB/bid/waiver UI.
- Leagues (Yahoo): Sunday Gravy f1/192426 (12-team full PPR) and The Trenches f1/811739 (10-team full PPR).
- The Trenches is a rushing league: QBs get NO points from completions/passing — rushing production only. Rushing QBs rise there; pocket passers fall. Rank QBs per league.
- Roster shape (both): 1 QB, 3 RB, 4 WR, 1 TE, 1 K, 4 DB, 4 LB, 8 bench. IDP = DB + LB only (no DL slot, no team DEF).
- Trusted sources: NBC Sports player news, @AdamSchefter (X), Rotowire news, ESPN draft kit cheat sheets (PPR top-300), team beat writers, aggregate ADP, snap/route analytics, user's own tiers.
- Design system: Modernist (bound). Main file: Fantasy Bible.dc.html.
- All timestamps render in the user's Houston timezone (America/Chicago — CDT in August).

## App state (as of Aug 14, 2026)

Pages in Fantasy Bible.dc.html: Alerts, Sleepers, Team Intel, Draft Analyzer, FFBets, Predictions, Schedules, Scout Finds, Data Health.

- Draft Analyzer: 205 ranked players with bye weeks; '25 stat lines for sourced names; league picker (ranks differ per league); My-team panel per league with star/sleeper toggles; opponent-pick tracking; position filters QB/RB/WR/TE/DB/LB; offense/defense split; search by name/team.
- Alerts: paginated 100-thread list, latest first (last real update batch: Fri Aug 14 — Pearce Jr. 8-game suspension, Stribling 7-63 preseason debut, Cousins/Mendoza; Thu Aug 13 batch before that).
- Sync button is REAL now (Phase 0+1 done): doSync fetches api.sleeper.app (players dump + trending add/drop, no key), joins via NORM name resolver + PLAYER_POOL (canonical pool from BOARD/ALERTS/TARGETS), renders a "Live wire" panel on Alerts (injury flags in pool, trending adds/drops), persists to localStorage "ww_live", and bumps 24h-budget feeds in Data health ("+ Sleeper live"). On fetch failure shows "Wire unreachable". Deep news (articles, suspensions, analysis) still via chat sync.
- Sleepers: offense-only (defense only if they return kicks); online list + user's custom list with comparison view.
- FFBets: DFS-style lineup builder, $50K salary cap, offense-only; salaries/projections are model estimates with '25 stats + Vegas lines as evidence.
- Team Intel: pass rate + goal-line % by team, '25 stats + 2026 projections.
- Themes: Light, Cowboys (cream bg + rider watermark), Dark (pure black).
- Data Health: last-sync + per-feed timestamps in CDT; sync label shows real date/time.

## Open items

- Productization plan lives in Tab Blueprint.dc.html (page 2): 0 player IDs → 1 Sleeper API live sync → 2 Yahoo OAuth → 3 server jobs + push → 4 real projections → 5 split data out of the monolith. User doesn't care about licensing constraints.
- Phase 2 is BUILT in the connected repo rgtorres20/FB_Bible (see github.md): FastAPI Yahoo OAuth backend, endpoints for leagues/teams/rosters/draft/scoreboard/transactions, league keys nfl.l.192426 + nfl.l.811739, Vercel or Docker deploy. Not yet deployed/wired to the app — needs Yahoo credentials, deploy URL, CORS origin; then wire Draft Analyzer to /api/leagues/{key}/draft.
- Sync button needs backend wiring to auto-pull latest wire news (Phase 1 makes it real via api.sleeper.app).
- Phase 5 partially done: sync-updated feeds (alerts, news, scout, weekrev, meta, rotowire) live in data/feeds.json, loaded at startup and overriding in-file *_SEED consts (shadowed at top of renderVals). Chat syncs should edit data/feeds.json, not the page. Draft board/intel/targets still in-file.
- Auto-sync on load: app pulls the Sleeper wire automatically if last pull >1h old (componentDidMount, doLiveSync method).
- Phase 6 PWA done in-project: manifest.webmanifest, sw.js (shell cache-first; feeds.json + Sleeper network-first w/ offline fallback), icons/icon-192+512 (red FB mark), helmet registers sw only on https (no-op in preview). Installable once deployed to any static https host.
- Full '25 stat lines for all 205 players await ESPN/Yahoo sheet import.
- FFBets needs live DraftKings salary data when available.

## Working rules for future chats

- Edit Fantasy Bible.dc.html in place; don't fork new files unless asked.
- When adding news/alerts, use real sourced items with real timestamps (CDT), newest first.
- Keep this file updated: whenever a decision is made or app state changes materially, update the relevant section here.

## Phase 2 — Yahoo OAuth server (moved to Claude Code, Fri Aug 14 2026)

- Repo: github.com/rgtorres20/FB_Bible (local: C:\Users\rober\Projects\FB_Bible). Python + FastAPI. Serverless-first (Vercel via api/index.py), but the same app.main:app runs under uvicorn/Docker — Phase 3's cron jobs + web push need a long-running process, so both targets are wired from day one.
- Built: 3-legged Yahoo OAuth2 (authorize / code exchange / refresh). OAuth state is a self-verifying nonce+timestamp+HMAC (10-min TTL) because serverless has nowhere to park a session. Tokens are Fernet-encrypted at rest behind a TokenStore interface — file store local, Redis on Vercel, Postgres slots in for Phase 3.
- Endpoints: /auth/yahoo/{login,callback,status,logout}; /api/leagues, /api/leagues/configured, /api/leagues/{key}/{teams,draft,scoreboard,transactions}, /api/teams/{key}/roster, /api/raw/{path}, /health. 17 tests, ruff clean, and they need no network or Yahoo credentials.
- League keys are nfl.l.192426 (Gravy) and nfl.l.811739 (Trenches). The bare "nfl" game code means current season, so the keys survive the rollover; f1/<id> is only Yahoo's UI shorthand.
- Yahoo's JSON (index-keyed collections, single objects split across list entries) is flattened in app/yahoo/parse.py, never in the page. Scope stays fspt-r: read-only, no lineup writes.
- BLOCKED: Yahoo developer app not registered yet — Yahoo rejects non-HTTPS redirect URIs, so localhost needs a tunnel or self-signed cert; see docs/YAHOO_SETUP.md in the repo.
- NOT done: Fantasy Bible.dc.html still reads data/feeds.json + in-file consts and does not point at this server. Roster, draft-pick and opponent-pick entry stay manual until it does — that is the stale-data fix this phase exists for.
- PUSHED: initial commit 042607a is live on github.com/rgtorres20/FB_Bible (main, 32 files). Repo is connected to this design project, so it can read the code directly.

## Commercial posture (supersedes the licensing note in Open items)

- This may be SOLD. The earlier "user doesn't care about licensing constraints" no longer holds. Verified terms are recorded in docs/LICENSING.md in the repo.
- Yahoo: may not "derive income from the use or provision of the Yahoo APIs" without prior written permission. Also requires Yahoo user data be deleted within 24h of being obtained — that constrains Phase 3's database (TTL + purge job on Yahoo-sourced rows), it is not just paperwork.
- Sleeper: free for non-commercial use only; commercial needs a licence from them. Attribution is required for the trending data the Alerts panel already shows — that applies NOW.
- Not yet reviewed: ESPN, NFL.com, CBS, Rotowire, NBC/Rotoworld, PFR, PFF, FantasyPros, DraftKings salaries, and NFL marks/logos.
- Decision Aug 14 2026: stay SINGLE-USER and prove the flow against a real Yahoo account first. Opening it to others ("could be anyone") needs a browser session, per-user token rows, and Yahoo's third-party-access clause handled.
- Repo intentionally has no open-source LICENSE file — all rights reserved, which is the right posture for a sellable asset.
- Hosting decision (Aug 14, docs/HOSTING.md): stay on Vercel Hobby for Phase 2 (zero-config, no vercel.json); Phase 3 hourly jobs need Vercel Pro or a container host. Repo also gained CI and frontend/lib/fbApi.js (browser client, adopted in-app Aug 14). docs/MIGRATION.md asks the app to be committed as frontend/index.html — pending user go-ahead.

## Next steps to go live (as of Fri Aug 14 2026)

1. Register the Yahoo developer app at developer.yahoo.com/apps/create — type Web Application, API Permissions = Fantasy Sports > Read (the fspt-r scope). Yahoo REJECTS non-HTTPS callback URLs, so plain localhost will not register: deploy to Vercel first and register https://<project>.vercel.app/auth/yahoo/callback, or use an ngrok tunnel / self-signed cert. See docs/YAHOO_SETUP.md.
2. Set env vars: YAHOO_CLIENT_ID, YAHOO_CLIENT_SECRET, YAHOO_REDIRECT_URI (must match EXACTLY), TOKEN_ENCRYPTION_KEY, SESSION_SECRET. On Vercel also set TOKEN_STORE=redis and REDIS_URL — the file store does not survive between invocations.
3. Link the account at /auth/yahoo/login, then verify with /auth/yahoo/status and /api/leagues.
4. Set CORS_ORIGINS to wherever Fantasy Bible.dc.html is served, then wire Draft Analyzer to /api/leagues/{key}/draft and the My-team panels to /api/teams/{key}/roster.
5. DONE Aug 14: visible Sleeper attribution (+24h retention note) added to the Live wire panel; Yahoo card notes read-only scope + 24h browser retention; Check server also reads /health and flags missing Yahoo credentials.
