# Resume here

Last worked: **Tue Aug 18 2026, ~12:15am CDT.**
old (first commit 8:23 PM Aug 14); 63 commits across two parallel sessions
landed in that window, so treat anything dated earlier than today as
already superseded.

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
| News | 6 publishers polled automatically, player-tagged, in Redis |
| Scheduler | GitHub Actions, running green |
| Cost | $0 |
| AI | Google AI Studio, free tier — wire verdicts hourly (live); TD-lean review shipped, first run pending |
| Preprod | <https://fb-bible.vercel.app/app/> — 35/35, but see FB_STAGE below |
| Tests | 314 Python + 16 JS (330), CI green on every push |

**The stale-data problem is solved server-side.** ESPN, Yahoo, Rotowire,
ProFootballTalk and CBS are polled without anyone asking, items are tagged
with the fantasy players they mention, and `/api/feeds` serves them with an
honest LIVE / STALE / FAILED state per source.

Note the real cadence: the cron says every 15 minutes, but GitHub drops
scheduled runs under load on free public repos. Observed: roughly hourly.

## START HERE — the AI layer, three pieces left

The owner asked (Aug 18) for three Gemini-driven surfaces. **One shipped,
three remain**, and they build in this order because each needs the one
before it.

### 1. `app/feeds/stats.py` — the foundation, do this first

Everything below reasons over it. The rule that shapes it: **Gemini never
recalls a number, it only reads ones we fetched.** Asking a model to
"project usage from last year" makes it invent snap counts that read as
fact, which is the no-false-positives rule broken at the root.

Endpoint **verified live 2026-08-18** (probe run #2, not assumed):

    https://api.sleeper.app/v1/stats/nfl/regular/2025
    HTTP 200 · 1.9 MB · dict of 8,243 keys

- **Keyed by Sleeper player_id — the same ids as our player index**, so the
  join to the board is free. No new key, no new rate budget, and the
  Sleeper attribution already on the page covers it.
- Usage fields confirmed present: `rec_tgt`, `rush_att`, **`rush_rz_att`**
  (red-zone carries), `rz_att`, `rz_conv`, `rush_td`, `rec_yd`, `rush_yd`,
  `rush_ypa`, `rec_ypt`, `rec_ypr`.
- **Caveat, do not skip:** the richest entry the probe printed is a *team*
  aggregate (455 targets, 507 carries), not a player. The field *names* are
  confirmed; per-player coverage is **not**. Build the extractor to report
  coverage per field on first run rather than trusting it — the same
  self-verifying trick that finally cracked the model problem.
- 1.9 MB, so cache it like the player index (TTL in the store), never fetch
  per request.

### 2. Top-100 AI alerts

A new alerts surface, Gemini-drafted, **filtered to players ranked ≤100**.
Ranks are already in the player index (`search_rank`). The `alerts` array
in feeds.json is what the tab renders, so it overlays like everything else
— no page fork. Label them so they never read as the owner's judgement,
the same way verdicts carry "AI draft:".

Note the tension to resolve deliberately: CLAUDE.md says the Alerts tab is
curated judgement and "should never be auto-generated". The owner asked for
an AI version anyway, so it belongs *alongside* the curated entries, plainly
labelled — not replacing them.

### 3. Team intel usage reads

Join the stats feed to the `INTEL` depth charts already in the page (starters
by position per team). Gemini writes prose about expected usage — who is
ahead of whom, what the red-zone split looked like — with every claim
traceable to a number we supplied. **Prose only, never figures.**

Roster question settled (owner, Aug 18): this means **NFL team depth
charts**, not the owner's fantasy roster. Yahoo is still blocked, and the
owner's own picks live in browser localStorage where the server cannot see
them.

## Decisions locked this session, do not relitigate

- **AI provider: Google AI Studio**, free tier, OpenAI-compatible endpoint.
- **Model: `models/gemini-flash-latest`** — the floating alias, chosen
  deliberately over a pinned version. This job died twice to a name
  vanishing (GitHub Models retired; then `gemini-2.5-flash` aged out — it is
  Aug 2026 and Gemini is on 3.x). Drift is the accepted cost; verdicts are
  advisory prose, never numbers. Pin `models/gemini-3.7-flash` if
  reproducibility ever outranks surviving the next rename.
- **Secret: `AI_API_KEY`** (or `GEMINI_API_KEY` — both are read).
- **Board duplicate:** Jayden Reed kept at **tier 7 / WR32**; the tier 11
  row is dropped at serve time, generalised to first-wins.

## What the AI layer already does

- **Wire verdicts** (`scripts/draft_verdicts.py`) — one batched call an
  hour over the 18 newest tagged items; renders "AI draft:" on the news
  tab. First real output Aug 18: 18 in, 13 stored, 8 on the tab.
- **TD-lean review** (`scripts/review_predictions.py`) — checks each
  curated lean against that team's live implied total; renders as an
  "AI check:" clause appended to the row's why. **The lean and confidence
  are never touched** — a disagreeing model gets its own labelled space,
  not the pen. Leans with no posted line are dropped rather than sent,
  because asking without a number invites invention.
  **Not yet observed running.** The step landed on `main` at 05:16 UTC on
  Aug 18; every AI-verdicts run up to that point (latest: run 39, 05:05
  UTC) shows only the "Draft and post verdicts" step. Code, tests and the
  endpoint are green, but the first live proof is the next hourly run —
  check that run 40+ has a **"Review the TD leans"** step that exits 0,
  and that a Predictions row carries an "AI check:" clause. Until then
  this bullet describes intent, not an observed surface.

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
     (scripts/push_vegas.py) and POSTed to /internal/vegas.
     VERIFIED Aug 15 20:15 CDT: the workflow's "Push Vegas slate" step
     succeeds from GitHub's IPs, and the watchdog's live-lines checks pass
     against prod — so the slate reaches the store and the page renders it.
   - *Week 1 schedule*: DONE (Aug 15 evening) — same payload, kickoff
     day/time in Central, teams and network; owner's per-game notes ride
     along by matchup.
   - *AI verdicts*: **WORKING as of Aug 18.** Chased to the bottom
     Aug 15 evening: verdicts.yml reported success while every run ended
     `HTTP Error 410: Gone` — **GitHub Models was retired 2026-07-30**,
     two weeks before this layer was built, so not one verdict was ever
     produced. Two bugs kept that invisible and are both fixed
     (`/internal/sync` was deleting stored verdicts every run; a permanent
     410 was handled like a rate limit, both exiting 0 under a green
     check).
     Now on **Google AI Studio** (owner's call), free tier, via its
     OpenAI-compatible endpoint — `models/gemini-flash-latest`, one request an hour
     against a few-hundred-a-day limit. The hourly schedule is back on and
     no-ops with a warning until the key exists.
     **YOUR STEP:** create a key at <https://aistudio.google.com> → Get
     API key, add it as the `AI_API_KEY` repo secret (`GEMINI_API_KEY`
     is accepted too, so either name works). Verdicts start
     on the next hourly run; no code change, no redeploy. The watchdog
     logs `AI-drafted verdicts on the news tab: N` every 2 hours, so you
     can confirm it took.
3. **AI layer, free ("make it better but free")**: SETTLED — see the AI
   verdicts entry above. The original GitHub Models plan is dead (retired
   upstream); the route is **Google AI Studio**, free tier, one key. The
   plumbing it describes is all built and unchanged: the job drafts
   one-liners for the newest tagged items, POSTs them to
   `/internal/verdicts` behind the same X-Sync-Token, they are stored in
   Redis keyed by wire-item id (ids we do not hold are rejected, so a
   hallucinated id dies at the door), and the page renders them prefixed
   "AI draft:" so they never read as your judgement. Paid Claude remains
   the quality upgrade path — two constants.
4. **Yahoo access application**: ready to paste from
   `docs/YAHOO_APPLICATION.md`. Submitting starts their review clock.

## Watchdog

`verify-live.yml` asserts 35 production checks every 2 hours (data fresh,
six sources not FAILED, overlays served, mobile injected, FFBets predict
mode, Vegas/TD-lean/schedule/draft-board surfaces still live, decorator assets still
serving). A failure emails the repo owner. Run it on demand from the
Actions tab. Last full green: Aug 15 22:30 CDT against `0cd30b1`, all
passing — including the live draft board and its no-duplicate-players
guard, which reported `204 rows, 204 distinct`.

Known watchdog weakness (see GAP_REVIEW): a single transient publisher
error flips a source to FAILED and fails the whole run, while the sync
workflow treats the same condition as a warning — expect occasional false
alarms until FAILED is gated on staleness too.

## The old "next work" list is DONE (Aug 15 afternoon)

All five items shipped:

1. **Page reads live data** — the `/app/data/feeds.json` overlay serves the
   page's own startup fetch with the live wire merged in. No page fork.
2. **Cross-source dedupe** — `impact.cluster()` folds the same story from
   multiple outlets into one telling with `also_from` credits.
3. **"New since last visit"** — `poller.merge()` stamps `first_seen` on
   arrival (edits don't re-stamp), the overlay passes it through, and
   `mobile.js` badges NEW on stories that arrived since the previous visit
   (visits are 30-minute sessions in `localStorage fb_visit`).
4. **Impact-ranked news** — `impact.order()`: score decayed 3 pts/day, ties
   newest-first. The news tab reads in board-impact order; the raw
   chronological wire stays on `/api/feeds`.
5. **Timestamps on Out & returning** — `app/feeds/injury.py` parses the
   OUTLIST/RETURNING names out of the served index.html (no duplicated
   list), the overlay attaches `injury_wire` (freshest wire mention per
   player), and `mobile.js` renders "Wire · <time> · <source> — headline"
   on each row, or an honest "no wire mention in 21 days".

The watchdog asserts the decorator and its styles keep serving.

## Also done Aug 15 afternoon

- **Vegas lines are live** — two parallel builds reconciled (Aug 15
  evening). Delivery is the runner-push design (ESPN 403s Vercel's IPs, so
  `scripts/push_vegas.py` fetches from the sync-feeds runner and POSTs to
  `/internal/vegas`; the page reads it via the `F.vegas` rebind), now
  pinned to the regular-season Week 1 slate instead of the current
  (preseason) week. On top of that ride: the odds caption stops claiming
  openers, TD-lean confidence tracks implied-total movement, and the
  Week 1 schedule swaps in real kickoffs — all serve-time, all falling
  back to the committed page. The read column stays facts-only (kickoffs,
  slate superlatives): curated prop angles would silently go false as
  lines move. Deployed and verified in prod Aug 15 20:15-20:17 CDT.
- **Beta/prod**: `beta` branch = stable Vercel preview with a BETA badge
  and `/health` stage reporting. Full model: docs/ENVIRONMENTS.md.
- **Stale-data audit + rule**: docs/STALE_DATA.md inventories every
  surface; CLAUDE.md now carries the no-stale-data and no-false-positives
  rules.

## Aug 15 evening — three-angle gap review

Product-vs-blueprint, code correctness, and ops robustness reviewed in
parallel over the whole app. **Twelve verified defects fixed the same
day**; the ranked remainder is [GAP_REVIEW.md](GAP_REVIEW.md). The three
that were silently costing the most:

- **Every sync deleted the AI verdicts** the hourly job had just written,
  so the page nearly always showed the rule-based `Auto:` fallback.
- **The page's Yahoo client never loaded** — both dynamic imports used the
  design project's `./frontend/lib/` path, which 404s under the `/app`
  mount. That killed the Yahoo link check *and* the 24-hour Yahoo-cache
  purge, which is a licensing obligation, not a feature.
- **Initialed names never enriched** — "C.J. Stroud", "A.J. Brown",
  "Amon-Ra St. Brown" and friends normalized to a double space, missed the
  index key, and so lost the rank points that drive impact ordering. The
  most fantasy-relevant players were the ones being under-ranked.

Also fixed: UNDER leans moved confidence the wrong way on a line move;
cross-source credit could list the kept outlet as its own corroborator;
rank-band labels were a tier off at boundaries (rank 100 read "top-200");
a naive timestamp from any publisher would have 500'd the whole overlay;
Rotoworld abbreviated Linebacker as "LI"; a spread naming neither
competitor invented a phantom team; a corrupt `fb_visit` froze NEW badges
forever; sync burned 30s on an ESPN fetch that always 403s from Vercel;
and the Vegas push was skipped whenever the unrelated sync call failed.

## Owner actions nobody else can do

1. **Set `FB_STAGE=preview` on the `fb-bible` Vercel project.** Preprod is
   a *separate project*, so Vercel calls its own deploy "production" and it
   renders **no BETA badge** — pixel-identical to the real thing, which is
   the wrong-tab hazard the badge exists to prevent. The override is built
   and tested; it needs one environment variable. Verify by re-running
   `verify-live.yml` with `base_url=https://fb-bible.vercel.app`: the run
   reports the stage and asserts the badge whenever it says "preview".
2. **Submit the Yahoo access application** — paste from
   `docs/YAHOO_APPLICATION.md`. Starts their review clock.
3. **Rotate the Upstash password** (pasted into chat on Aug 14), then
   re-run `scripts/setup_redis.py`.

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
