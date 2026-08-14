# FB Bible server — project rules

The backend half of the Fantasy Bible. The browser app (`Fantasy Bible.dc.html`)
lives in the Claude design project; this repo is **Phase 2 only** — the Yahoo
league link. Read [docs/PHASE2_SPEC.md](docs/PHASE2_SPEC.md) before changing
scope.

## Inherited domain rules

These come from the app's own CLAUDE.md and still bind here:

- Team watcher + fantasy draft tool for the **2026 NFL season**. Real players,
  real news — no mocked names, and no fixture data standing in for a live Yahoo
  response outside of `tests/`.
- The user's leagues have **no waivers and no player cost** — no FAAB, no bids,
  no waiver-clear times. Adds are free, first-come. Never surface FAAB/bid
  fields from the transactions endpoint.
- Leagues: **Sunday Gravy** `nfl.l.192426` (12-team full PPR) and
  **The Trenches** `nfl.l.811739` (10-team full PPR).
- The Trenches is a rushing league: QBs get **no** points from
  completions/passing. Rank QBs per league.
- All timestamps render in the user's Houston timezone (`America/Chicago`).
- Trusted news sources: NBC Sports, @AdamSchefter, Rotowire, ESPN, CBS,
  Yahoo's wire.

## Rules for this repo

- **Read-only against Yahoo.** Scope stays `fspt-r`. If a change needs
  `fspt-w`, that's a scope decision, not an implementation detail — ask first.
- **Never log or return a token.** Not the access token, not the refresh token,
  not in an error message. `/auth/yahoo/status` returns expiry metadata only.
- **Tokens go through `app/store`.** Don't read or write `.tokens.json` or
  Redis directly, and don't add a store that skips `TokenCipher`.
- **Keep both run targets working.** Any change has to survive both
  `uvicorn app.main:app` and Vercel's `api/index.py`. That means: no reliance
  on local disk, no in-process caches that assume a long-lived process, no
  background tasks — those wait for Phase 3.
- **Yahoo JSON gets flattened in `app/yahoo/parse.py`,** not in routes and not
  in the browser app. New resource, new extractor, new test fixture mirroring
  the real shape.
- `/api/raw/{path}` is the escape hatch for exploring unmodelled resources.
  Prefer adding an extractor over letting the browser app consume raw shapes.

## Working rules

- Run `pytest` and `ruff check .` before calling anything done.
- Tests must pass with no network and no Yahoo credentials.
- Keep this file updated: when a decision is made or the phase state changes
  materially, update the relevant section here.

## State

Phase 2 complete as scaffolded: OAuth (authorize / exchange / refresh),
encrypted swappable token store, and read endpoints for leagues, teams,
rosters, draft results, scoreboard and transactions. 17 tests, lint clean.

Not yet done: verified against a live Yahoo account (needs the developer app
registered — see docs/YAHOO_SETUP.md), and the browser app still points at its
in-file data rather than this server.

Phase 3 (cron jobs polling feeds on their budget intervals, a database, and web
push for the Settings rules) builds on this service — hence the Dockerfile and
the store interface.
