# Resume here

## Aug 19 — the real league settings arrived, and they change the product

The owner provided both leagues' actual Yahoo Scoring & Settings pages as
PDFs. **[docs/LEAGUES.md](LEAGUES.md) is now the ground truth** and it
overturned chat-era facts the repo was built on:

- The leagues are **NDDPL** (`192426`) and **RED_EYE** (`811739`) — both
  **10-team** (not 12), both **IDP** (8 defensive starters each).
- **"The Trenches rushing league / QBs score nothing" was backwards.**
  Both leagues pay QBs above market: 6-pt passing TDs, 20 pass yds/pt,
  and RED_EYE adds **1 pt per completion**. The cheat sheet's QB note
  said "draft QBs later" — the actively dangerous kind of wrong — and now
  says the opposite, with the watchdog check updated to match.
- Receiving yards halved (20 yds/pt) in both; returns score in both.
- Confirmed: no waivers, first-come adds, in both.

Fixed same-day: cheat-sheet note + title, CLAUDE.md domain rules, stale
comments in adp/board. **Opened, not yet decided** (see LEAGUES.md §what
this means): IDP support (the player index excludes DB/LB — now a
first-order gap, both leagues start 8), and whether ADP should drop the
12-team half of the blend.

Also added: **`yahoo_fantasy` feed** (sports.yahoo.com/fantasy/rss.xml,
verified live via probe run 4) — the fantasy vertical that carries
sleepers/rankings/draft-strategy articles the NFL news feed never did;
the owner pointed at a Boone sleepers piece that lived only there. Seventh
source; all count assertions were already dynamic.

Last worked: **Tue Aug 18 2026.** The project started Aug 14 (first commit
8:23 PM); treat anything dated earlier than the newest section as already
superseded. Two Aug 18 sessions merged here: the AI-layer/preprod work
(PRs #10–#17) and the stats/intel/top-300 build below.

## Aug 18 evening — the AI layer widens: player capsules and mover reads

Owner picked these from a ranked list ("let's start with 2 and 3", then
the Week 1 previews as a follow-up).
All follow the verdicts pattern exactly: a server-assembled work list so
the model can only cite numbers we fetched, a POST endpoint that rejects
anything the store does not hold, hourly accumulation on the free tier
(now four requests an hour against a few-hundred-a-day budget), and a
labelled render that never reads as the owner's judgement.

1. **Player capsules — "AI angle:" on the top-300 board**
   (`app/feeds/capsules.py`). Per-*player* synthesis where the drafted
   line was per-*item*: Sleeper rank, live ADP, '25 usage
   (coverage-gated, present fields only), injury flag and newest wire
   word in one sentence. `/api/capsules/pending` serves the uncovered
   best-rank-first batch (16/hour → full 300 in ~a day);
   `/internal/capsules` accepts only top-300 ids; each capsule remembers
   its `wire_id` so a player re-queues when his news changes — a stale
   synthesis cannot outlive the story it cites. Capsule outranks the
   per-item line on the board; quiet players get a grounded line where
   the column sat empty.
2. **ADP mover reads — "AI read:" on the Scout cards**
   (`adp.movers` / `adp.pending_reads` / `adp.accept_reads`). Each
   riser/faller is paired server-side with the newest wire story tagging
   that player; **movers with no story never reach the model** — an
   explanation without a source is an invented cause. The clause uses
   "follows / coincides with" framing (never asserted causation),
   appends to the card's text, and is pruned the moment its mover drops
   off the list. `/api/movers/pending`, `/internal/mover-reads`.

3. **Week 1 matchup previews — "AI preview:" on the schedule tab**
   (`app/feeds/previews.py`; owner picked it as the next one). Two short
   sentences per slate game from the pushed line (favorite, total,
   per-side implied points) and the '25 team-offense profiles (pass
   rate, red-zone run share, red-zone TD rate) — a team whose season
   aggregates are incomplete sends no profile at all. Renders appended
   to the schedule row's note beside the owner's own note.
   `/api/previews/pending`, `/internal/previews`. Freshness is
   snapshot-based like capsule wire_ids: each preview remembers the
   total and favorite it was drafted against and re-queues when the
   total moves a full point or the favorite flips — the prose never
   cites a line the table no longer shows. Usually a no-op call-wise:
   16 games drafted once.

All three ride the hourly `verdicts.yml`, all survive `/internal/sync`
(carried forward beside `pred_reviews` — the wiped-verdicts bug class),
and the watchdog logs each count as an INFO line — best-effort surfaces
report, they do not fail the run.

**Consolidated to two calls an hour (late evening).** Five separate
hourly calls plus retries tripped Google's free-tier throttles all
evening (runs 50–52 below), so the four annotation jobs (capsules,
mover reads, TD-lean review, previews) now travel as sections of ONE
batched request in `scripts/annotate.py` — verdicts keeps its own call.
The four per-surface scripts are deleted; their POST endpoints and all
validation are unchanged, and the lean work list moved server-side
(`vegas.lean_review_rows`, `/api/leans/pending`) like the others, which
also removed the workflow's httpx install step. Trade accepted
knowingly: one malformed reply now costs all four sections for an hour,
where the extra calls were costing whole evenings.

**Observed live (run 50, 23:44 UTC):** the plumbing works end-to-end —
prod's pending endpoints served real work (16 uncovered players, 4
movers with stories) — but all three retry-less calls hit HTTP 429: the
free tier throttles per *minute* too, and the job now makes four calls
back-to-back. Fixed the same hour: `chat_with_retry` in
draft_verdicts.py gives the capsule, mover-read and lean-review calls
the same backoff the verdicts call already had. Runs 51–57 then mapped
the real problem: **`gemini-flash-latest` refused every chat call for
10+ hours** (503/429, spanning the daily quota reset — so neither our
pacing nor the quota), while the key stayed healthy (the authed probe
listed 51 models, HTTP 200). Run 58 (13:34 UTC Aug 19), dispatched with
the new one-run model override pointing at
`models/gemini-flash-lite-latest`, **filled every surface on the first
try**: verdicts 8 accepted, capsules 16, mover reads 5, lean checks 12,
game previews 16 — all "posted". The watchdog then read 40/40 against
prod with the new INFO counts: 16 capsules and 11 drafted lines on the
top-300 board, 5 mover reads, 16 schedule previews, 10 verdicts on the
news tab. **Durable fix:** `chat_with_retry` now walks a model chain —
primary `MODEL`, then `FALLBACK_MODEL`
(`models/gemini-flash-lite-latest`, overridable via
`VERDICT_FALLBACK_MODEL`) — falling back when the primary exhausts its
transient retries **or 404s** (the name-vanished death this job has had
twice). Codes that fail on any model (401/400) still raise immediately.

## Aug 18 session — season stats, Team intel usage, top-300 alert board

Three pieces, built in order on `claude/stats-intel-alerts300`:

1. **`app/feeds/stats.py`** — Sleeper `/v1/stats/nfl/regular/2025`
   extractor. The earlier probe caveat ("richest entry was a team
   aggregate; per-player coverage unconfirmed") is now settled by
   measurement: the endpoint's 8,243 keys are 8,179 player ids + 32 bare
   team codes (team **defense** fantasy aggregates) + 32 `TEAM_XXX` keys
   (team **offense** aggregates: pass/rush attempts, red-zone and
   goal-to-go splits). Per-player coverage is real but sparse (pass_att:
   128 players, rush_att: 367, rec_tgt: 534, off_snp: 947), so `reduce()`
   **counts holders per field into `coverage`** and consumers gate on the
   counts — nothing assumes a field exists. Stored state is ~80KB (603
   players with offensive usage + 32 team offenses), rides the hourly sync
   with a weekly refetch policy (the season is final; the numbers never
   change).
2. **Top-300 alert board** — `/app/alerts300` (owner asked for top-300,
   up from top-100). Server-rendered zero-script page, cheat-sheet
   pattern: one row per top-300 Sleeper-ranked player with live injury
   flag, blended ADP, newest wire mention, and the machine line for that
   item — "AI draft:" when the hourly job has one, "Auto:" fallback
   otherwise, an explicit "No wire mention in the last 21 days" when the
   archive is empty. The hourly verdicts job now reads `verdict_ids` from
   `/api/feeds` and spends its one request on **uncovered** items,
   top-300-player items first, so coverage accumulates instead of
   re-drafting the newest 18 forever. Reachable by URL only (same
   discoverability debt as the cheat sheet, GAP_REVIEW #6).
3. **Team intel usage reads** — the curated `PASSRATE` / `GLRUN` /
   `TEAM_SPLIT` consts are replaced at serve time from the '25 team
   offense aggregates, all 32 teams or nothing. "GL x% run" became
   **"RZ x% run share ('25)"** because Sleeper has no run/pass split
   inside goal-to-go — the label names the stat that is actually shown.
   Win projections on the tab stay curated; the Data health row says so.

**After merging to main:** the two new watchdog check groups (top-300
board, Team intel live marker) stay red until Vercel deploys **and** the
next sync stores the stats state — trigger `sync-feeds` from the Actions
tab (or POST `/internal/sync`) right after the deploy to close that
window.

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
| Preprod | <https://fb-bible.vercel.app/app/> — 35/35, but it builds `main`: a duplicate of prod, not a stage (see owner actions) |
| Tests | 340 Python + 16 JS (356), CI green on every push |

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
- **TD-lean review** (now a section of `scripts/annotate.py`) — checks each
  curated lean against that team's live implied total; renders as an
  "AI check:" clause appended to the row's why. **The lean and confidence
  are never touched** — a disagreeing model gets its own labelled space,
  not the pen. Leans with no posted line are dropped rather than sent,
  because asking without a number invites invention.
  **First runs failed; fix pushed, first green run still unobserved.**
  Runs 42–47 (Aug 18, hourly) all died the same way: the review step
  imports `app.feeds.vegas`, the `app.feeds` package pulls in `httpx` at
  import time, and the verdicts workflow — stdlib-only by design —
  never installed it. `ModuleNotFoundError: No module named 'httpx'`,
  exit 1, before any lean was reviewed. (The verdicts step kept working
  throughout: run 47 posted 11 accepted / 41 stored.) The fix mirrors
  sync-feeds, which hit the identical wall with `push_vegas.py`: a
  `pip install --quiet httpx` step ahead of the review. Reproduced and
  verified in a bare venv before pushing. **Observed working:** run 48
  (dispatched 22:27 UTC Aug 18 on the fixed commit) ran the review step
  green — "reviewing 12 leans via models/gemini-flash-latest", posted
  `{'stored': 12}`. What has not been eyeballed yet: an actual
  Predictions row rendering its "AI check:" clause on the page — the
  clauses are stored, the render is asserted only by the generic
  TD-lean checks.

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

1. **PARKED (owner, Aug 18): point the `fb-bible` Vercel project at the
   `beta` branch.** The owner is deliberately deferring this — it only
   matters once a real staging flow is wanted, and everything below works
   without it. Do not re-raise it as a blocker; the detail stays here for
   when it happens. Settings → Git → **Production Branch** → `beta`. One
   dropdown. Verified still unflipped at 22:27 UTC Aug 18
   (`stage: production  branch: main`, 40/40 checks otherwise green).

   This replaces the old "set `FB_STAGE=preview`" item, and the reason is a
   finding, not a preference. The watchdog was run against preprod at 05:41
   UTC on Aug 18 and its log read:

       INFO  stage: production  branch: main

   **Preprod builds `main`.** It is not a pre-production stage — it is a
   second deployment of the exact commit prod serves, which is why it has
   always reported 35/35 with identical data, and why pushing to `beta`
   does nothing to it. Every earlier claim that it tracks `beta` was
   assumed and never checked.

   `Settings.stage` now falls back to the git branch
   (`VERCEL_GIT_COMMIT_REF`): `beta` means preview whatever the host calls
   the deploy. That code is live and working — the ref reached the function,
   which also proves the project exposes system environment variables — it
   simply has nothing to match while the branch is `main`. Flip the dropdown
   and the badge appears with no environment variable at all.

   Do **not** reach for `FB_STAGE=preview` as a shortcut here. It would
   raise a BETA badge over a deployment still byte-identical to prod: an
   honest-looking label on a stage that does not exist.

   **Verify after flipping:** re-run `verify-live.yml` with
   `base_url=https://fb-bible.vercel.app` and read the log for
   `INFO stage: preview  branch: beta`, plus the
   `preview wears the BETA badge` assertion, which only arms when the stage
   says preview.
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
