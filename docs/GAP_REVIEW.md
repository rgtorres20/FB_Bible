# Gap review — Aug 15 2026

## Found Aug 22 (stale-data audit) — fixed

- **Data health re-stamped the wire feeds with the browser's own Sleeper
  pull.** Three client sites borrowed `s.live.ts` for any feed budgeted
  24h or less — News & posts, NBC player news, Alerts — so their real
  as-of was discarded and each row read minutes old, the nav badge read
  0, and the summary said "All feeds within budget". On the one tab
  whose whole job is reporting freshness, and true even if the server
  wire had not polled in a week. The same bug fixed server-side earlier
  the same day, surviving on the client: `merge_into_feeds` hands over
  an honest per-feed stamp in `F.meta` and the page threw it away.
  `page.data_health_stamps` now lets each feed speak for itself.
- **The Vegas caption claimed "refreshed with every news sync" with no
  age gate at all.** Which is how a dead push hid for a day: the slate
  is served from storage, so it was present, and the watchdog's own
  check read a string the code wrote unconditionally. `vegas.is_live`
  gates the caption on a 6-hour budget and `stale_caption` names the
  real age instead — the last real slate is still worth showing, it just
  is not live. `verify_live` now subtracts the stamp rather than
  trusting the label.

## Found Aug 22 (accuracy review) — real, verified, deliberately not fixed yet

Each of these was proven with a runnable script during the Aug 22 model
review; they are recorded rather than rushed because each touches the
sync path or a trade-off the owner should call.

- ~~**The sync's read-modify-write can clobber a fresher runner push.**~~
  **Fixed later the same day**: the sync re-loads immediately before
  saving and prefers the fresh copy of every key it does not itself
  change (verdicts re-apply their pruning, the slate keeps whichever
  copy is fresher). The clobber window went from minutes to
  milliseconds; splitting the keys out like the ledger remains the full
  fix if it ever bites again. `test_a_push_landing_mid_sync_survives_the_save`
  pins it.
- ~~**`first_seen` can be re-stamped for items trimmed at the 400-item
  cap.**~~ **Fixed later the same day**: the merge keeps a bounded
  memory of trimmed arrivals (`retired`, capped at 800) and restores a
  returning item's original stamp instead of badging it NEW forever.
- ~~**A preview stored against a dash total never re-queues.**~~
  **Fixed later the same day**: a real total arriving where the stored
  preview had none now counts as the line moving, so the lineless
  preview re-queues; still-no-line and line-pulled keep the old
  behaviour.
- ~~**`rss._clean` eats legitimate escaped angle-bracket prose.**~~
  **Fixed Aug 22 (owner: "do it")**: the tag pattern now requires a real
  tag open (letter, `/`, `!`, `?` — the same rule browsers apply), so
  "&lt;24 but &gt;20 points" survives as prose while every actual tag
  still dies at any escape depth. Safe because the page renders item
  text as React text nodes, never innerHTML.
- ~~**`_rekey_to_page` is last-wins on suffix-folded collisions.**~~
  **Fixed later the same day**: colliding keys decorate nobody — a dash
  is honest, a coin flip is not.

Three parallel reviews (product-vs-blueprint, code correctness, ops/robustness)
over the whole app. Everything verified against the code; line numbers were
checked at review time and may drift.

## Fixed Aug 22

- **The draft board's injury badge was a frozen name list.** Owner:
  "what happens when a player is put on IR" — and on the board they
  actually draft from, nothing. The badge came from two hand-typed arrays
  in the design document, six names in `OUT_RED` and thirteen in
  `INJ_YELLOW`, frozen at whatever the injury report said the day they
  were written. Nothing in `app/` ever touched them.

  Both directions were wrong. A player placed on IR got no badge at all,
  and the nineteen wore theirs permanently whatever their real status —
  George Kittle reading "PUP / IR" while healthy. The app has carried
  Sleeper's `injury_status` on every sync for weeks and already uses it
  on `/app/nextup`, `/app/idp`, `/app/scoring` and in the mock room's
  display; this board was the one surface still reading the frozen copy.

  It now reads the live index and shows the real word — "IR", "Out",
  "Questionable" — rather than a category. `OUT_FLAGS` and the tier
  classification moved to the kernel (`players.py`), since `depth` and
  `board` need the same answer and two copies is how one goes stale,
  which is exactly the bug being fixed.

  **Also found, not fixed:** the "Out & returning" tab has its own
  separate curated injury list (`status: "OUT · SEASON"`, `slot:
  "Bench"`). `mobile.js` already stamps live wire posts onto those rows,
  so it is not silent — but the status text itself is still curated.

- **Season-ending injuries now come off the draft board** (owner's rule,
  Aug 22: *"if they are out for season drop off list, if they are only
  out for a few weeks leave"*). The constraint worth recording: **Sleeper
  publishes no season-ending field.** `injury_status` says what a player
  is designated as, never for how long, and a player on IR may be
  season-ending or designated to return. So the line falls where the data
  draws one — a reserve designation (IR, PUP, NA, DNR, Sus), which
  carries a multi-week minimum, against a weekly game status (Out,
  Doubtful, Questionable), which does not. That is the closest faithful
  reading of the rule rather than a season-ending judgement the app
  cannot make, and it is self-correcting: the flag is live, so a player
  coming off IR is back on the board at the next sync with no list to
  edit. Caught while wiring it: `deepen` backfills from the same index
  and handed the dropped row straight back — the log read "dropped 1" and
  "appended 1" on consecutive lines. Backfill now refuses reserve players
  too, and a test pins it.

- **Nothing re-orders on injury, anywhere.** Checked while answering the
  same question: a player on IR keeps his place on every board. The main
  board sorts by ADP and the blended lists; `/app/scoring` and `/app/idp`
  sort by last season's points, which he did score. The mock room reads
  `inj` only at its two render sites and never in the pick score, so
  **autopick will draft a player who is on IR** — his own and the
  opponents'. That is a real gap and it is deliberately left open here
  rather than fixed quietly: how far an injured player should fall is a
  judgement, not an arithmetic, and it is the owner's to make.


- **The board the owner drafts from carried an invented number.**
  `projFor` in the design document computed a per-position base minus a
  slope times the position rank — `{QB: 24.5, RB: 21.0, ...}` less
  `n * 0.85` — and rendered it under a column headed "Proj" on the main
  top-300 board. No data behind it, no league in it, and the comment
  directly above it claimed both leagues pay quarterbacks above market,
  which the formula had no way of knowing. It is now each league's real
  scoring over that player's real stored line, per game, keyed to the
  league already selected on that screen. The header says `'25 P/G`,
  because a real number under a "Proj" label is still a wrong claim.

  This also closes the gap named in the same conversation: league
  scoring reached `/app/scoring`, `/app/idp` and the mock room, but the
  board most used for drafting only saw league *size* (which ADP column)
  and league *roster* (how deep to go). Neither is scoring.

  **Still open:** the board's ORDER is unchanged — it still sorts by ADP
  and the blended lists, with league points as a column to read rather
  than a sort key. `replacement.py` has the edge-over-replacement figure
  that would let it sort by the owner's rules instead of the market's;
  wiring that up is the next step, and it is a bigger one because it
  changes what the board *is*.

## Fixed Aug 22 — live incident

- **The player index was the one feed that degraded to nothing.** Twelve
  watchdog checks failed at once: the top-300 board, the scoring board,
  the IDP board and the mock room's pool all came back empty, while news,
  Vegas, ADP and team defenses were fine. The board also fell from 300
  rows to 204, because `deepen()` draws its extra rows from the index.

  The index was stored under a 20-hour TTL and refetched in exactly one
  place, only when `load_players()` returned `None`. So "stale" and
  "absent" were the same answer, and the TTL expiring in the same hour as
  a failed Sleeper fetch left nothing stored — every player-backed surface
  serving empty until some later sync happened to succeed. A few lines
  below it in the same function, ADP and Vegas both carry forward on
  exactly the opposite reasoning ("yesterday's ADP is still a usable draft
  board"). An empty board does not read as stale; it reads as *no players
  exist*, which is a false statement rather than an old one.

  Now: the index carries a `fetched_at` stamp, `players.needs_refresh`
  decides when to fetch (still under a day, since Sleeper asks for at most
  one dump daily), Redis retention is a 14-day backstop rather than an
  expiry, and a failed refetch keeps what is stored and logs its age.
  `/health` reports the index count and age, so the next outage names
  itself in one request instead of appearing as four unrelated empty
  boards. `tests/test_player_index_survives.py` reproduces the incident —
  verified failing against the old code.

  **Resolved 01:45, on its own.** The 03:51 watchdog run reported 7,582
  players, 2.1h old, and `last_error` cleared — so the Sleeper fetch
  started succeeding again roughly when the carry-forward fix was being
  pushed. The fix did not cause the recovery and should not be credited
  with it: it preserves a copy, it does not go and get one. What it buys
  is that the *next* multi-hour Sleeper outage costs a stale board rather
  than an empty one.

  **What the outage looked like while it lasted.** The sync runs every 15 minutes, so by
  01:40 it had tried four times and the index was still empty — this is a
  persistently failing Sleeper fetch, not a transient blip landing on the
  TTL boundary. The carry-forward fix is deployed and correct, but there
  was nothing left to carry: it protects the *next* copy, not one already
  lost. Cause unknown as of writing, and unreachable from outside Vercel's
  own logs, which is why the sync now records the exception type and
  message in the feeds blob and `/health` reports it as
  `players.last_error`. The next occurrence names itself.

  **Also caught:** the first version of the watchdog's index check guarded
  on `age_hours is not None` — which is None exactly when the index is
  missing, so the check skipped itself silently during the outage it was
  written for and printed nothing at all. It reports unconditionally now.

  **Still open:** nothing labels a carried-forward index as stale on the
  boards themselves. The count and age are in `/health` and the watchdog
  warns past 48h, but a reader looking at the IDP board cannot see that
  its injury flags are two days old. That is the remaining half of the
  no-stale-data rule for this feed.

## Fixed Aug 21

- **`rss._clean` could be made to emit a live script tag.** It stripped
  tags once and then unescaped twice, so anything that *became* a tag on
  the way out survived: `&amp;lt;script&amp;gt;` is not a tag when the
  strip runs and very much is one afterwards. A feed could put markup
  into a stored headline, and headlines reach the page. Now strips and
  unescapes alternately until the text stops changing, bounded at three
  rounds with a final strip — unbounded unescaping is its own denial of
  service. Ordinary double-escaped text ("Jets&amp;#39; Geno Smith")
  still decodes as before.

- **`backups()` ranked every position by rushing attempts.** Right at
  RB, silently wrong everywhere else: every receiver's sort key was 0, so
  the WR board came back in index order and read as a ranking it was not.
  It now sorts on the same position-aware opportunity `chart` already
  measures, with Sleeper rank breaking ties — including the all-zero case
  of a room where nobody played last season. The old test pinned the bug
  by name; it now pins the fix.

- **`next_man_up` dropped a room where everyone was hurt.** The week a
  whole backfield goes down is the biggest vacancy on the board, and the
  page showed nothing — indistinguishable from "nobody on this team is
  injured". It now names the next man whatever his own flag says and
  marks the row `room_all_out`, and `/app/nextup` says "this is a
  vacancy, not a pickup" rather than presenting an injured player as the
  grab. A starter with literally nobody behind him is still skipped:
  there is no pickup to name.

- **Three of the four boundary breaches are gone.** `capsules` reached
  upward into a page module for a time formatter — that formatter is now
  kernel (`app/feeds/clock.py`), which also ends six modules each
  declaring their own `CENTRAL`. `scorecard` imported the odds unit for a
  season year, now `config.SEASON_YEAR`. `previews` reached into the
  private `vegas._GAME_TEAMS`, now the public `vegas.matchup_teams`, and
  took its implied totals from the odds unit directly, now passed in by
  the composer. The one left is `previews` importing `vegas` for that
  public parser, kept deliberately: moving a parser for the odds unit's
  own row shape into the kernel to satisfy a rule would be worse than
  the import.

- **`/app/access` had never been checked live, and could not be checked
  the way the others are.** Walking the canonical eleven surfaced it
  immediately: the page is owner-only and correctly bounces anyone else
  to `/login`, so the watchdog — which holds a sync token but is not the
  owner — was asserting a home bar on the sign-in page and failing a page
  that works. `skin.OWNER_ONLY` now marks it, and the live check makes
  the claim it can actually make: that the page turns others away. The
  rendered bar stays covered signed in and signed out by
  `tests/test_navigation.py`. Two checks that had silently never run for
  a day now run and mean something.

- **Centralising that list then killed the watchdog outright.** Reading
  it as `from app.feeds import skin` executes `app/feeds/__init__.py`,
  which imports the poller, which imports httpx — and the verify-live
  workflow does a checkout and nothing else, on purpose: being
  stdlib-only is what lets it check a deployment without building an
  environment first. The run died one second in, before a single check,
  and the previous run had been green, so only reading the log said so.
  It now reads `skin.py` with `ast`, the way `scripts/lint_docs.py`
  already did, keeping both the single source of truth and the
  standalone property. `tests/test_watchdog_is_standalone.py` is the
  fence — static, because importing the script to test it would pass on
  any machine that has the dependencies, which is exactly why CI never
  saw it.

- **The served-page list was duplicated, and it drifted the same day.**
  `tests/test_navigation.py` and `scripts/verify_live.py` each kept their
  own copy. `/app/scoring` was added to the first and not the second, so
  the new page's way home was verified in the unit tests and never
  against the deployment — and nothing caught it, because the docs lint
  compared prose to code and *both* copies were code. The list is now
  `skin.SERVED_PAGES`, read by all three, with a lint rule that fails on
  a second literal or on a consumer that walks some other list.

- **A verify-live check printed its failure text next to a PASS.**
  `check(label, ok, detail)` prints `detail` whether it passed or failed,
  and the new scoring-board check passed a static explanation string. The
  live log read `PASS scoring board is not sitting on stale stat fields:
  stored stats predate pass_cmp -- the sync has not refetched`, which is
  a contradiction in the one artefact CLAUDE.md says to read instead of
  the badge. Details now describe what was observed, never what a failure
  would have meant. The same check's column list was deduped and had `GP`
  excluded — it read "GP, NDDPL, RED_EYE, BALLAPALOSA, GP, BALLAPALOSA",
  where a repeated column is indistinguishable from a duplicated league.

- **The QB draft boost counted points that move nobody.** Checking the
  derived boost against the two overrides tuned on real draft behaviour
  found them disagreeing by roughly 2x (NDDPL: override 10, derived 19;
  RED_EYE: override 18, derived 24 — capped, and 92 uncapped). The cause
  is structural rather than a bad constant: `qb_premium_per_game`
  measures a league's QB scoring against the *market*, but what decides
  how early to draft one is its spread against a *replacement QB in the
  same league*. RED_EYE's point per completion adds ~22 points a game to
  QB1 and ~22 to the twelfth-best starter — real points that change
  nobody's draft order. `qb_spread_premium_per_game` now excludes that
  class of bonus and `qb_draft_boost` derives from it; touchdown and
  yardage values stay in, because a better quarterback throws more of
  them and a richer value really does widen the gap. BALLAPALOSA, the
  one league with no override, drops from a capped 24.0 to 10.7. The
  league editor now says the two numbers apart rather than letting a big
  premium beside a small boost read as a bug.

  **Followed up Aug 21 by measuring it** (`app/feeds/replacement.py`),
  which corrected this entry twice over. Excluding the completion bonus
  entirely was an over-swing: QB1 completes materially more passes than
  the last starter, so the bonus *does* widen the gap — it is just worth
  far less than the totals imply. And the comparison that decides draft
  order is not QB-against-market at all, it is **each position's spread
  over its own replacement**, which is the only figure that makes
  positions comparable. That is now derived per league from stored
  production, with flex slots allocated greedily to whichever eligible
  position has the highest next-available player rather than split by a
  ratio nobody measured, and reported on `/app/scoring`.

  **Still the owner's call:** whether to move the overrides toward the
  measured edge. They record how those rooms actually draft, which is
  what a mock room needs to simulate — you prepare against the room, not
  against the theory. The measurement says what the scoring justifies;
  the gap between the two is the owner's edge, not a bug. The likeliest explanation is that the override is
  measuring human behaviour rather than optimal play: RED_EYE's raw QB
  totals look enormous (874 against a WR1's 247 on the scoring board),
  and people draft what the totals look like. Worth the owner's read
  before anything is changed — the overrides are kept precisely because
  they encode something real that the model does not.

  **The remaining modelling error**, smaller and the same kind: the TD
  and yardage terms still use one starter's volume rather than the spread
  between a starter and a replacement. Closing it needs measured per-QB
  lines, which the app now has the stats for (`/app/scoring`) but the
  `League` dataclass cannot reach — it is pure data with no store access.
  A `qb_spread_from_stats()` in a surface would be the honest fix.

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
