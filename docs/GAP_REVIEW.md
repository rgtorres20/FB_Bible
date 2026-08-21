# Gap review — Aug 15 2026

Three parallel reviews (product-vs-blueprint, code correctness, ops/robustness)
over the whole app. Everything verified against the code; line numbers were
checked at review time and may drift.

## Fixed Aug 21

- **The suite was reaching the real network** — 29 tests made 37 outbound
  HTTP calls and passed on the failure, so CLAUDE.md's "tests must pass
  with no network" was true only by accident. `/internal/sync` was the
  worst of it: tests that patch `adp.fetch` and `vegas.fetch` left
  `players.fetch_index`, `stats.fetch` and `stats.fetch_week` reaching
  Sleeper and ESPN for real. Nothing failed, but the suite's runtime
  became ambient — it swung between 11s and 65s run to run on how fast
  the proxy said no, which is enough noise to hide a genuine regression
  in a timing (it hid one for most of an afternoon). `tests/conftest.py`
  now blocks outbound sockets, and `tests/test_no_network.py` guards the
  fence itself. Blocked at the socket rather than the httpx transport
  because respx and `httpx.MockTransport` both patch the transport;
  nothing that fakes a response opens a socket. Suite is now 10.4–11.1s
  across runs.

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

## Found by chasing the review's leads, same evening

**The AI verdict layer has never worked.** *(RESOLVED Aug 18 — it works
now; the account below is the post-mortem, kept because the failure mode
is the interesting part. Provider is Google AI Studio, the key is in
`AI_API_KEY`, and the first real output was 18 items in / 13 verdicts
stored / 8 on the news tab.)* The review flagged that
`draft_verdicts.py` exits 0 on model failure, so a permanent break would
look green forever. Running the job and reading its log confirmed exactly
that: `HTTP Error 410: Gone` on every run, because **GitHub Models was
retired 2026-07-30** — two weeks before the layer was written. Fixed what
was fixable (the sync no longer deletes verdicts; a 410/404 now annotates
loudly and exits non-zero instead of hiding among rate limits; the cron is
off; STALE_DATA no longer claims the feature is live). Reviving it is an
owner decision: one provider, one secret. Worth noting the compounding —
two independent silent-failure bugs stacked on a dead upstream, and each
one alone would have hidden the others.

## Owner's calls, made

- **Duplicate board row** — the board listed Jayden Reed twice (tier 7 as
  WR32, tier 11 as WR38 with the PFF slot-yards note): 205 rows, 204
  distinct players, so he appeared twice mid-draft and marking one row
  taken left the other looking available. **Owner chose tier 7.** Dropped
  at serve time, generalised to first-wins (the earlier row is the higher
  ranking), with a watchdog check so a future duplicate fails loudly.
  Nothing was lost with the dropped row: STATS25 already renders its
  slot-yards line on the kept row, and the Sleepers tab carries the
  thesis.
- **AI provider** — **Google AI Studio**, free tier, via its
  OpenAI-compatible endpoint. Shipped; waiting only on the
  `GEMINI_API_KEY` secret. See STALE_DATA.md.

## Backlog — high value, needs design or decisions

Ordered by draft-day value.

1. ~~**Draft analyzer board is not live**~~ — DONE Aug 15 evening
   (`app/feeds/board.py`). The ADP column now carries real FFC ADP joined
   by player name at serve time, **per league size** — 12-team for Sunday
   Gravy, 10-team for The Trenches — and the delta, blend slider and sort
   all read that number instead of the row's restated rank. A player the
   live board does not cover shows "—" rather than a second scale's
   number; his row still sorts on rank and still shows the owner's own
   value. Data health now stamps the board only when it is genuinely
   live, and stopped stamping the Sleepers tab, which still renders its
   committed const. Watchdog asserts both the live map and the absence of
   any consumer still reading the derived string.
   *Still open here:* the Sleepers tab itself (`TARGETS`) is untouched, so
   its as-of date is its own; and the `/12` round arithmetic elsewhere in
   the page is still 12-team-only (see item 2).
2. **Draft-day pick math.** No draft-slot input, no snake math, no "gone
   before my next pick" flag, no 10-vs-12-team awareness outside `/12`
   arithmetic. Live ADP + pick count is all it needs — and now that the
   board carries real per-league ADP, this is mostly arithmetic on data
   already in the page.
3. **"Rank QBs per league" is one browser heuristic with 12 of 24 QBs
   classified.** Unclassified QBs (including Kyler Murray, whose own row
   says "plays in both leagues") get the worst multiplier ×0.32 in The
   Trenches. Also: the Trenches view re-sorts the whole board by a
   synthetic projection with no K entry, floating kickers above real
   RB/WR picks. Fix: classify all 24 (default 1.0 + "unclassified" tag),
   sort by ADP and adjust QBs only, emit a Trenches QB column server-side
   so board and cheat sheet agree.
4. ~~**IDP is invisible to the live pipeline**~~ — FIXED Aug 20: defenders
   joined the index (v3) with a coarse DB/LB/DL group, the '25 stats carry
   the idp_* fields (names verified via the probe's field census), and
   `/app/idp` scores every defender with each league's verified settings
   (docs/LEAGUES.md). Wire tagging, capsules and the top-300 board see
   them now. Remaining: the page's own tabs still have no IDP surface —
   the board is URL-only, same discoverability debt as the cheat sheet.
5. **Yahoo draft sync is unwired client-side** — `fb.draft()` etc. exist
   with zero callers; opponent picks stay manual taps even after Yahoo
   approval. (The import-path fix above at least makes the client load.)
6. **Cheat sheet is unreachable and its round dividers are 12-team-only** —
   no link anywhere; `/app/cheatsheet` needs a Draft analyzer link, a
   `?teams=10` param for The Trenches, and a sw.js precache entry.
   (Partial pattern landed Aug 20: mobile.js injects a Draft-analyzer link
   to `/app/mock` — the same anchor can carry the cheat-sheet and IDP
   links.)
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
11. **`/api/*` stays outside the login gate** (docs/ACCESS.md) — it
    carries the same feed data the gated page shows, left open because
    the annotate runner GETs its work lists bare. Fine for a
    friends-only app; before any wider audience, move the runner GETs
    behind X-Sync-Token and gate /api too.
11. **verify-live false-alarms on a single transient publisher error** —
    FAILED should only be fatal when the data is also stale; needs a
    `last_ok_at` carried per source through the sync.
12. **Quiet degraders**: ~~verdicts job returns green on permanent model
    failure~~ (fixed — permanent codes exit non-zero, transient ones retry
    with backoff); ADP/vegas fetch failures never annotate the workflow; ESPN
    extending its block to GitHub runners would age out silently. Add
    freshness assertions on `adp.state.date` / `vegas.fetched_at`.
13. **User leagues stop at the boards** — `/app/leagues` (docs/LEAGUE_SETTINGS.md)
    feeds the mock room and the IDP board, but the main app page's own
    league picker is design-document markup renamed at serve time and
    still shows only the owner's two. Same for the printable cheat sheet,
    which is ADP-first and carries the owner's league caveat as prose. A
    user with their own league sees it in two surfaces out of four, which
    is worth stating plainly rather than letting them discover. Also not
    modelled anywhere: kicker and team-defense scoring, so the editor
    deliberately has no fields for them.
14. **Smaller product debt**: per-request Redis client (make the feed
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
