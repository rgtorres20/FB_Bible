# Gap review — Aug 15 2026

Three parallel reviews (product-vs-blueprint, code correctness, ops/robustness)
over the whole app. Everything verified against the code; line numbers were
checked at review time and may drift.

## Fixed same day

- **Sync wiped AI verdicts hourly** — the `/internal/sync` save dict omitted
  `verdicts`; the hourly GitHub Models job's output lived only minutes.
  Verdicts now carry forward, pruned to surviving items.
- **The page's Yahoo client import 404'd** — both dynamic imports used the
  design project's `./frontend/lib/fbApi.js` path; under the `/app` mount
  that path does not exist. This silently killed the Yahoo link check AND
  the 24-hour Yahoo-cache purge (a licensing compliance path). Fixed with a
  serve-time rewrite, same class as the sw.js precache fix.
- **UNDER leans adjusted confidence in the wrong direction** — a rising
  implied total now subtracts confidence from an UNDER, adds to an OVER.
- **Dotted/initialed names never enriched** — "C.J. Stroud" normalized with
  a double space and missed the index key; every A.J./D.J./T.J./St. Brown
  lost rank enrichment (and therefore impact points). Join-split fixed.
- **Cross-source credit could name the kept outlet** — "ESPN (also: ESPN,
  CBS)" when a better-tier telling took over a cluster.
- **Rank-band labels off a tier at boundaries** — rank 100 labeled
  "top-200", rank 400 "top-500".
- **Naive timestamp crash** — one publisher drifting to naive ISO dates
  would have 500'd the whole feeds overlay via naive-vs-aware subtraction.
- **Rotoworld defensive positions** — Linebacker abbreviated "LI",
  Cornerback "CO"; the map now covers the IDP positions.
- **implied_by_team phantom teams** — a spread naming neither competitor
  (WSH vs WAS) now skips instead of mis-assigning totals.
- **mobile.js frozen visit sessions** — a corrupted `fb_visit` stamp made
  NaN comparisons freeze badge rotation forever.
- **Sync burned 30s on a doomed ESPN fetch from Vercel** — skipped on
  Vercel (ESPN 403s its IPs); this also narrows the store-write race window.
- **Vegas push skipped when sync step failed** — the workflow steps are
  independent; now gated `!cancelled()` instead of implicit success-only.

## Backlog — high value, needs design or decisions

Ordered by draft-day value.

1. **Draft analyzer board is not live, but Data health says it is.** The
   live ADP blend only feeds the Scout finds tab; the board the owner
   drafts from is the in-page `BOARD` const, and its "ADP" column is the
   row's own rank restated (`round.pick` arithmetic on the index), so the
   "mine vs ADP" delta and blend slider compute on a constant. Fix: overlay
   `merged["board"]` from the live blend + `F.board || BOARD` rebind, show
   real per-size ADP (12tm for Sunday Gravy, 10tm for The Trenches — both
   already stored per player), and only stamp the Data-health rows for
   surfaces actually replaced.
2. **Draft-day pick math.** No draft-slot input, no snake math, no "gone
   before my next pick" flag, no 10-vs-12-team awareness outside `/12`
   arithmetic. Live ADP + pick count is all it needs.
3. **"Rank QBs per league" is one browser heuristic with 12 of 24 QBs
   classified.** Unclassified QBs (including Kyler Murray, whose own row
   says "plays in both leagues") get the worst multiplier ×0.32 in The
   Trenches. Also: the Trenches view re-sorts the whole board by a
   synthetic projection with no K entry, floating kickers above real
   RB/WR picks. Fix: classify all 24 (default 1.0 + "unclassified" tag),
   sort by ADP and adjust QBs only, emit a Trenches QB column server-side
   so board and cheat sheet agree.
4. **IDP is invisible to the live pipeline** — `FANTASY_POSITIONS` excludes
   DB/LB, so 8 of 18 starting slots can never be tagged, stamped, scored,
   or alerted (Branch/Joseph/Emmanwori/Parsons rows show "no wire mention"
   forever). Fix: extend the index positions; surname ambiguity is already
   handled globally.
5. **Yahoo draft sync is unwired client-side** — `fb.draft()` etc. exist
   with zero callers; opponent picks stay manual taps even after Yahoo
   approval. (The import-path fix above at least makes the client load.)
6. **Cheat sheet is unreachable and its round dividers are 12-team-only** —
   no link anywhere; `/app/cheatsheet` needs a Draft analyzer link, a
   `?teams=10` param for The Trenches, and a sw.js precache entry.
7. **Pickup queue triggers ignore the server wire** — they only check the
   browser's own Sleeper injuries; RESUME's "trigger-on-wire-news works
   today" is not wired. Evaluate against `F.news`/`injury_wire` too.
8. **Store writes race** — three writers do whole-blob load-modify-save
   with no locking; the sync's fetch window can clobber a concurrent slate
   push. Fix: per-section Redis keys (`fbbible:items`, `:adp`, `:vegas`,
   `:verdicts`). Also: corrupt-vs-absent store reads both return `{}`,
   which silently resets first_seen/history on a bad read.
9. **The watchdog dies with the patient** — GitHub disables all crons
   (including verify-live) after 60 days of repo inactivity, silently.
   Fix: external dead-man's switch (healthchecks.io ping in sync-feeds).
10. **No Redis backup** — a flush loses the 21-day item archive,
    first_seen stamps (next merge would badge everything NEW), ADP
    history (~a week of movers), verdicts. Nightly artifact dump.
11. **verify-live false-alarms on a single transient publisher error** —
    FAILED should only be fatal when the data is also stale; needs a
    `last_ok_at` carried per source through the sync.
12. **Quiet degraders**: verdicts job returns green on permanent model
    failure; ADP/vegas fetch failures never annotate the workflow; ESPN
    extending its block to GitHub runners would age out silently. Add
    freshness assertions on `adp.state.date` / `vegas.fetched_at`.
13. **Smaller product debt**: per-request Redis client (make the feed
    store an lru_cache singleton like the token store); serve-time page
    assembly re-reads/re-substitutes 257KB per request (cache the file
    text at module level); "22 picks" hardcoded where the shape sums to
    26; the alerts league filter is unwired and league tags on non-QB
    rows are arbitrary; a Settings line still mentions waivers (banned by
    project rules); player-detail timeline matches on last-name substring
    ("Brown"/"Chase"/"Love" cross-match); verdicts cron's :41 offset
    assumes sync timing GitHub doesn't honor (`workflow_run` trigger is
    the fix); Position analysis is a static const the blueprint claims is
    derived; hardcoded Upstash hostname in `setup_redis.py`;
    `allow_credentials=True` in CORS is unnecessary with same-origin
    serving.
