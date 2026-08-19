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

## Commercial posture

This may be sold. That reverses the app's original "doesn't care about
licensing constraints" note — see [docs/LICENSING.md](docs/LICENSING.md) for
the verified terms. Two consequences bind code, not just paperwork:

- **Yahoo user data must be deleted within 24h of being obtained.** When Phase
  3 adds a database, Yahoo-sourced rows need a TTL and a purge job. Non-Yahoo
  feeds are unaffected.
- **Sleeper requires attribution for trending data,** which the Alerts panel
  already displays. That applies now, not just commercially.

Selling requires prior written permission from Yahoo and a commercial licence
from Sleeper. Neither blocks personal single-user use.

## Rules for this repo

- **Read-only against Yahoo.** Scope stays `fspt-r`. If a change needs
  `fspt-w`, that's a scope decision, not an implementation detail — ask first.
- **Never log or return a token.** Not the access token, not the refresh token,
  not in an error message. `/auth/yahoo/status` returns expiry metadata only.
- **Tokens go through `app/store`.** Don't read or write `.tokens.json` or
  Redis directly, and don't add a store that skips `TokenCipher`.
- **Keep both run targets working.** Any change has to survive both
  `uvicorn app.main:app` and Vercel (same entrypoint, named in
  `[tool.vercel]`). That means: no reliance
  on local disk, no in-process caches that assume a long-lived process, no
  background tasks — those wait for Phase 3.
- **Yahoo JSON gets flattened in `app/yahoo/parse.py`,** not in routes and not
  in the browser app. New resource, new extractor, new test fixture mirroring
  the real shape.
- `/api/raw/{path}` is the escape hatch for exploring unmodelled resources.
  Prefer adding an extractor over letting the browser app consume raw shapes.
- **No stale data.** Every user-facing surface is live-polled, the owner's
  own judgement, or curated facts wearing an honest as-of stamp — nothing
  claims freshness it does not have. The audit and the plan for what is
  still curated: [docs/STALE_DATA.md](docs/STALE_DATA.md). A surface that
  goes live gets a `verify-live.yml` check in the same commit.
- **No false positives.** Never fabricate a judgement, a number, or a
  freshness label to make a surface look complete — an empty truthful
  section beats an invented one. When a call is genuinely uncertain, ask
  the owner instead of guessing. The standing list of known gaps and the
  fixes already made: [docs/GAP_REVIEW.md](docs/GAP_REVIEW.md).
- **Two stages, one codebase.** `main` deploys prod; the `beta` branch
  deploys a stable Vercel preview that wears a BETA badge and reads (never
  writes) the shared feed store. See
  [docs/ENVIRONMENTS.md](docs/ENVIRONMENTS.md) before touching deploy or
  store wiring.

## Working rules

- Tests must pass with no network and no Yahoo credentials.
- Keep this file updated: when a decision is made or the phase state changes
  materially, update the relevant section here.

## The validation gate — run this BEFORE starting new work

Not after. Every rule below was bought with a real failure on Aug 15-18;
none of them are hygiene for its own sake.

```bash
git fetch origin main && git log --oneline HEAD..origin/main   # 1
ruff check . && ruff format --check .                          # 2
pytest -q                                                      # 3
(cd frontend/lib && node --test)                               # 4
python3 -c "import glob,yaml;[yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]"  # 5
```

1. **Sync with `main` first.** Two sessions work this repo in parallel and
   have twice built the same feature simultaneously (Vegas lines, then the
   AI provider), each costing a real reconciliation. Check what landed
   before writing anything, and merge it in before starting.
2-5. Lint, format, both test suites, and workflow YAML. A workflow that
   fails to parse does not run at all, and nothing else in CI catches it.

**Then, after deploying:** run `verify-live.yml` and *read the log*, do not
just check the badge. Three separate bugs this week were green-and-broken:
a retired model endpoint returning 410, a sync silently deleting every
stored verdict, and two watchdog checks running twice. A green check means
the script exited 0, which is not the same as the thing working.

**Corollary — never trust a name you did not verify against the live API.**
The AI layer was built against a provider retired two weeks earlier, then
pointed at a model that no longer existed. Both were "known" facts. Ask the
endpoint what it actually offers; the model list is one HTTP call.

## State

Phase 2 complete as scaffolded: OAuth (authorize / exchange / refresh),
encrypted swappable token store, and read endpoints for leagues, teams,
rosters, draft results, scoreboard and transactions. Plus the browser client
in `frontend/lib/` and CI in `.github/workflows/ci.yml`.

392 tests green — 376 Python (`pytest`) and 16 JS (`cd frontend/lib && node --test`) —
lint and format clean. CI runs all of it plus a secret guard on every push
to main and beta.
Hosting decision and its Phase 3 cost: [docs/HOSTING.md](docs/HOSTING.md).

The served page reads live data: the `/app/data/feeds.json` overlay merges the
polled wire (impact-ranked, deduped, `first_seen`-stamped) into the page's own
startup fetch, and `mobile.js` decorates NEW badges and Out & returning wire
stamps onto the rendered rows. See docs/RESUME.md for the live-state detail.

Not yet done: verified against a live Yahoo account — blocked on Yahoo's
fantasy-access approval (see docs/RESUME.md), not on code.

Phase 3 (cron jobs polling feeds on their budget intervals, a database, and web
push for the Settings rules) builds on this service — hence the Dockerfile and
the store interface.
