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
  fields from the transactions endpoint. (Verified against the real Yahoo
  settings, Aug 19.)
- Leagues — corrected Aug 19 from the owner's actual Yahoo settings pages,
  which override every earlier chat-era description
  ([docs/LEAGUES.md](docs/LEAGUES.md) is the ground truth):
  **NDDPL** `nfl.l.192426` (10-team) and **RED_EYE** `nfl.l.811739`
  (**12-team** — owner correction Aug 20, superseding the PDF's 10),
  **both full PPR, both IDP** (8 defensive starters each); plus
  **BALLAPALOSA** `963878` (10-team, settings page Aug 21) — full PPR,
  **team D/ST instead of IDP**, and receiving yardage *not* halved.
  A league starts individual defenders or a team defense, never both.
- **QBs score above market in both leagues** — 6-pt passing TDs and
  20 pass yds/pt in both; RED_EYE adds **1 pt per completion**. The old
  "rushing league, QBs score nothing for passing" rule had it backwards
  and is dead. Rank QBs per league, in the premium direction.
- Receiving yardage is **halved** (20 yds/pt) in both leagues while
  receptions stay 1.0 — weigh targets over air yards.
- All timestamps render in the user's Houston timezone (`America/Chicago`).
- Trusted news sources: NBC Sports, @AdamSchefter, Rotowire, ESPN, CBS,
  Yahoo's wire.

## The mark

The app's identity — open book as a football field, gold trophy, FSB —
ships as vector in `frontend/assets/` and is wired into every served page
through `skin.FAVICON`. Rules that bind code: the wordmark is white and
gold, so **it always sits on its own navy panel** (it disappears on the
light theme otherwise), and the two manifest PNGs are *rendered from* the
icon SVG, so they get regenerated whenever it changes.
[docs/BRAND.md](docs/BRAND.md) has the palette and the swap procedure for
dropping in different artwork.

Two surfaces show the **full lockup**, and both paint their own navy: the
sign-in page, and — since Aug 22, owner ask — the app page's own header,
injected by the `header_mark` transform above the screen kicker. The
design document carried the artwork only as a `logo.png` watermark at
`wmOpacity` behind the whole shell, which is texture, not identity. The
header rather than the sidebar because under 769px the sidebar is an
off-canvas drawer, so a mark placed there is invisible on a phone.

The app wears **one of 32 club themes, Dark, or Light**, and opens on the
club theme (the house navy until someone picks a club). The palettes are
*generated* from each club's two published marks in `app/feeds/teams.py`
and served as `/app/teams.css`; the generator guarantees the contrast
rather than assuming it, and the tests assert it for all 33. `ww_theme`
and `fb_team` are immutable storage keys, and the retired `cowboys` /
`titans` values are translated, never reset.

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
- **The two blobs worth stealing are encrypted at rest too** (Aug 24),
  under the same `TOKEN_ENCRYPTION_KEY`: the access list
  (`fbbible:auth` — scrypt password hashes) and each person's own layer
  (`fbbible:user:{email}` — the documents, ranking lists and league
  settings they typed). Neither used to be worth a dump; passwords made
  the first one worth it, and the second is somebody's own writing rather
  than a headline the app polled — "not Yahoo data" is a *retention* rule,
  not a reason to leave it legible.

  The rule that binds code is not the encryption but its failure mode:
  **a blob that cannot be decrypted raises `StoredDataUnreadable`, never
  `{}`.** Empty is a legitimate value — a fresh deployment, a user with
  nothing saved — and every caller does load → mutate → save, so
  collapsing the two destroys the data on the *next write* rather than at
  the failure. Adding one user would replace the whole allowlist; saving
  one league setting would replace that user's documents. That is the
  verdict-wipe bug class, pre-empted rather than repeated. One `_Vault`
  serves both blobs and both stores, because copies of a migration rule
  are how one of them stays wrong.

  A blob written before Aug 24 is plaintext and still opens, re-sealed by
  the next write. `/health` reports `stored_data_at_rest`,
  `verify-live.yml` fails on `plaintext`, `/app/*` answers a named 503
  saying which blob would not open, and rotation is in
  [docs/ACCESS.md](docs/ACCESS.md).
- **Keep both run targets working.** Any change has to survive both
  `uvicorn app.main:app` and Vercel (same entrypoint, named in
  `[tool.vercel]`). That means: no reliance
  on local disk, no in-process caches that assume a long-lived process, no
  background tasks — those wait for Phase 3.
- **League facts live in `app/leagues.py`,** nowhere else, and users can
  edit their own at `/app/leagues`
  ([docs/LEAGUE_SETTINGS.md](docs/LEAGUE_SETTINGS.md)). One `League`
  dataclass carries a league's size, roster slots and every scoring value —
  offense, individual defenders (IDP) and whole team defenses (D/ST), which
  are separate slots a league can start both of;
  the IDP board's per-event dicts and the mock room's JS config are both
  *generated* from it. Which defensive groups a league can start is derived
  from its slots, and its ADP column from its size — neither is configured
  separately, so neither can disagree with the roster. The verified numbers
  stay in [docs/LEAGUES.md](docs/LEAGUES.md).
- **Yahoo JSON gets flattened in `app/yahoo/parse.py`,** not in routes and not
  in the browser app. New resource, new extractor, new test fixture mirroring
  the real shape.
- `/api/raw/{path}` is the escape hatch for exploring unmodelled resources.
  Prefer adding an extractor over letting the browser app consume raw shapes.
- **Every served page is built with `skin.head()`.** It emits the head
  tags, the favicon, the theme boot and `home_bar()` in one place. Nine
  hand-written heads had already drifted — the alert board carried no
  favicon and three pages ignored the user's club. Installed as a PWA the
  app also has no address bar, so a page whose only exit is a text link is
  a dead end. The list is **`skin.SERVED_PAGES`, and it is read, never
  copied**: `tests/test_navigation.py` walks it signed in *and* signed
  out, `scripts/verify_live.py` walks it against the deployment, and
  `scripts/lint_docs.py` holds both to it. It was duplicated in the first
  two and drifted the first time a page was added — `/app/scoring`
  reached the unit test's copy and not the watchdog's, so the new page
  shipped with its way home unverified live. Add a page, add it to
  `skin.SERVED_PAGES`. The twelve: `/app/mine`, `/app/leagues`, `/app/mock`,
  `/app/mock/board`, `/app/nextup`, `/app/scorecard`, `/app/idp`,
  `/app/scoring`, `/app/cheatsheet`, `/app/alerts300`, `/app/idpweek`,
  `/app/access`. `scripts/lint_docs.py`
  fails if that list and this one disagree.
- **Units have fences, and the fence is a test.** `app/` is a layer
  stack — kernel, data units, surfaces, composers — and
  `tests/test_boundaries.py` fails on a new upward or sideways import, or
  on any module touching another's private names. Its `KNOWN_BREACHES`
  list is a ratchet: it fails when a breach is added *and* when a listed
  one is fixed but not deleted, so it can only shrink — **four down to
  one** on Aug 21, the survivor kept deliberately. One worked unit
  contract: [docs/units/wire.md](docs/units/wire.md).
- **Serve-time edits to the app page are named transforms** in
  `app/feeds/page.py`, never inline `html.replace()` in `main.py`. Each
  reports the anchors it could not find, and `tests/test_page.py` asserts
  every one still fires against the committed `frontend/index.html` — a
  silent miss is the same failure as a control wired to nothing.
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
- **A number chosen rather than measured gets written down.** Not every
  value can be derived — a retention window, a flex-fill model, where the
  line between "out for the season" and "out a few weeks" falls in a feed
  that publishes neither. Those are the owner's to overrule, which they
  cannot do if the choice is invisible.
  [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md) records each one with what
  changes if it is wrong. It also carries the standing rule the Aug 22
  keying bug bought: **any map injected into the page is re-keyed onto
  the board's own spelling first** (`board._rekey_to_page`) — an exact
  string match at runtime misses in silence, and a watchdog check written
  as a set intersection passes by finding nothing.
- **Two stages, one codebase.** `main` deploys prod; the `beta` branch
  deploys a stable Vercel preview that wears a BETA badge and reads (never
  writes) the shared feed store. See
  [docs/ENVIRONMENTS.md](docs/ENVIRONMENTS.md) before touching deploy or
  store wiring.

## Working rules

- **Tests must pass with no network and no Yahoo credentials** — and the
  fence enforces it rather than trusting it. `tests/conftest.py` blocks
  outbound sockets, so a test with an unpatched dependency fails naming
  the URL instead of quietly reaching the internet and passing on the
  refusal. Fake HTTP with `respx` or `httpx.MockTransport`; both patch
  the transport and never open a socket, which is why the block sits
  below them.
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

1578 tests green — 1562 Python (`pytest`) and 16 JS (`cd frontend/lib && node --test`) —
lint and format clean. CI runs all of it plus a secret guard on every push
to main and beta.
Hosting decision and its Phase 3 cost: [docs/HOSTING.md](docs/HOSTING.md).

The served page reads live data: the `/app/data/feeds.json` overlay merges the
polled wire (impact-ranked, deduped, `first_seen`-stamped) into the page's own
startup fetch, and `mobile.js` decorates NEW badges and Out & returning wire
stamps onto the rendered rows. See docs/RESUME.md for the live-state detail.
**The overlay re-pulls when the app wakes** (Sep 1 — the owner's installed
app showed mid-August wire on three tabs while the server, measured the
same minute by the watchdog run against the production domain, was
fresh). Both pullers fetched once at page load and never again, which a
browser tab survives and a PWA held in memory for weeks does not.
`page.feeds_follow_the_wake` wraps the page's own fetch and re-runs it on
`visibilitychange`/`focus`, `mobile.js` does the same for its decorator
copy, both throttled to five minutes (docs/ASSUMPTIONS.md has the number
and why nothing polls in the background). A failed re-pull keeps what is
on screen — the dated kickers are the surface that says how old that is.
And nothing gated is cacheable (same day): every `/app` response outside
the four public brand assets now carries `Cache-Control: no-store` —
they carried no cache header at all, which left the decision to whoever
sits in the path, and production sits behind Cloudflare's proxy. The
gate's own 401/redirect wear it too; a cached refusal is the same poison
pointed the other way. Stamped once in the gate middleware, tested in
`tests/test_navigation.py`.

**And the feeds fetch stopped hiding its own failure** (Sep 2, after the
report persisted through the re-pull and cache fixes). The whole pipeline
was proven healthy end to end — the server serves fresh, strict-JSON-valid
bytes (probe run 27, sync-token), `renderVals` renders them fresh under
node, and the relative fetch resolves right at `/app` and `/app/` in a
real browser — yet the page still showed the Aug-14 SEED constants,
because the one fetch every feed tab depends on caught its own failure
with a bare `.catch(() => {})` and fell back to the seeds with nothing on
screen saying so. That silent fallback is the defect: it violated the
no-false-freshness rule on the tab whose subject is freshness.
`page.feeds_follow_the_wake` now fetches the **absolute** `/app/data/feeds.json`
(a relative path can misresolve under an installed-app scope), `no-store`,
retries 3× with backoff, and on final failure raises a fixed banner naming
the HTTP status (`Live feed didn't load (HTTP 401) …`) plus a console
warning — so the next failure is diagnosable instead of a silent month on
the seed. `mobile.js`'s decorator fetch took the absolute-path/no-store
half too. The probe grew a strict browser-equivalent JSON parse and
`PROBE_SYNC=1` (X-Sync-Token) to reach the gated feed — that is what
proved the bytes are browser-parseable.

`/app/mock` is the mock draft room (owner request, Aug 20): pick a league and
a slot, the other nine teams autopick from the live pool — market ADP with
each league's verified scoring leaned on it, defenders by their /app/idp
league-scored totals — or Autopilot drafts the owner's picks too, each with a
stated reason, rendered as a round-by-round plan. All simulation is labelled;
the engine has a headless smoke test — `tests/test_mock_engine.py` runs the
page's own JavaScript under node against the DOM stub in `tests/js/`,
drafting every league from both the turn and the wheel. CI pins node and
fails the build if that test skips itself. The Draft
analyzer links to it via mobile.js. The room wears the app's own modes
(Light/Cowboys/Titans/Dark via `ww_theme`), drafts RED_EYE at its real 12
seats, and its "Draft board ⧉" button opens the snake grid with hover
details in a new tab. The page's news overlay reads newest-first — impact
selects what shows, chronology orders it (owner call, Aug 20).

`/app/scorecard` grades the app against reality (owner ask, Aug 21): an
immutable ledger records every TD lean when it is made — an existing
entry is never overwritten, which is what makes it evidence rather than
opinion — and Sleeper's per-week box scores settle it later. It reports
**calibration**, not just a hit rate, because "said 78, hit 33" is the
finding a bare percentage hides. No rate is printed until real games are
behind it; pushes and unplayed games are excluded; prose surfaces
(capsules, verdicts, previews) stay explicitly unscored rather than
graded against an invented rubric. Ledger in its own Redis key so no sync
can reset the history to "no evidence".

`/app/nextup` is the pickup board (owner request, Aug 21): every starter
flagged out, the player measured to be behind him, how much work comes
loose, and the real latest wire post about the replacement. **Defenders
included** (owner, Aug 22: *"IDPs should be — all draft should be
monitored for injuries"*) — it watched only QB/RB/WR/TE until then, which
ignored a third of an IDP roster, since both verified leagues start eight
defensive players. A defender is charted by the group a league actually
starts (DB/LB/DL, not MIKE or WILL) and measured in **tackles**, the same
volume that dominates IDP scoring; reporting his carries would report
zeros about the wrong thing. Tackles and touches are different
currencies, so the page says to read the ranking within a side of the
ball rather than across it. Depth is
computed in `app/feeds/depth.py` from Sleeper's '25 opportunity — usage
the stats reducer had been storing and nothing had joined up — so the
numbers are measured rather than the curated guesses the handcuff table
shipped with. Flags and wire posts live, workload labelled '25, nothing
projected.

Six modules that had no tests of their own now do (Aug 21). `authn` and
`mailer` were the ones that mattered: the first is every signed cookie
and one-time invite in the app, the second puts a **sign-in link** in an
email. Both are tested for how they say *no* — a tampered or
foreign-signed cookie, an expired session, a reused invite, an email
whose removal must also kill its pending invites, and a failure message
that never repeats the API key or the invite token. `config.stage` is
pinned because the beta project's own Vercel deploy reports itself as
production, so trusting Vercel alone serves an unbadged preview that
looks like prod; `deps.get_store` because a missing setting has to read
as a named 503 rather than a bare 500. `rotoworld` gained its degraded
shapes and a test that it still shares one cleaner with `rss` — two
cleaners is how one of them stays broken.

`app/feeds/replacement.py` measures **what a starter is worth over the
man you could have had for free** (owner ask, Aug 21). A season total is
not an edge: you never receive a starter's points, you receive them minus
whatever fills that slot otherwise, because somebody does either way. So
each position's spread between its best player and the first man nobody
has to start is the only figure that makes positions comparable — and it
is what decides whether a league's quarterbacks deserve to be drafted
early. Replacement depth is **derived from the roster, never chosen**:
`teams x dedicated starters`, then each flex (and RED_EYE's generic D
slot) handed one at a time to whichever eligible position has the highest
next-available player in that league's scoring. A position thinner than
the league starts reports nothing rather than a spread against the last
man in a short list. This is also the baseline `/app/scoring`
deliberately would not guess, so points above replacement now has one.
On the board this shows as **one line per league — reach, or wait** —
trimmed back on Aug 22 from a spread table with verdicts and caveats,
which the owner could not follow. An explanation nobody follows is worth
less than the fact it was wrapped around; the measurement is unchanged
underneath, and `scripts/verify_live.py` still prints the real numbers.
The tuned `qb_boost_override` stays a mock-room setting and is no longer
shown as a verdict — it says how a room drafts, not what a player is
worth.

The mock room's **QB draft boost stopped counting points that move
nobody** (Aug 21). A league's QB premium was measured against the market,
but what decides how early to draft one is its spread against a
*replacement QB in the same league* — and RED_EYE's point per completion
adds ~22 points a game to the best starter and ~22 to the twelfth, real
points that change nobody's order. `qb_spread_premium_per_game` excludes
that class of bonus; TD and yardage values stay in, since a better
quarterback throws more of them. Found by checking the derivation against
the two overrides tuned on real draft behaviour, which disagreed with it
by roughly 2x. The overrides are **kept** — they encode how those rooms
actually draft, and the fact that two leagues with identical spread
premiums draft QBs differently is a finding for the owner, not a bug to
paper over ([docs/GAP_REVIEW.md](docs/GAP_REVIEW.md)).

**The lists a reader makes follow their account, not their browser**
(owner, Aug 26: *"why make a list you cant save"*, then *"when i log into
other devices i dont see my changes"*). The design document keeps
fourteen things in `localStorage`; the nine that are somebody's own work
— the backup-RB order and cleared rows, the draft queue, who is taken,
my teams, the draft slot, dismissed scout cards, the slider weights —
were pinned to one browser. The fix is **not** a rewrite of each tab's
save code: nine bespoke transforms would be nine anchors to break on the
next design resync. Instead the *storage* is redirected once beneath all
of them — `page.prefs_shim` installs a `localStorage` shim before
`</head>`, which is before the page's own script reads those keys, and
serves the managed ones out of the account's copy while writing changes
back through `POST /app/mine/prefs` (coalesced, plus a `pagehide`
flush).
Anything unmanaged passes straight through, so themes and caches behave
exactly as before. A write **merges** rather than replaces, because two
tabs are two writers. Appearance keys stay per-device on purpose and
`ww_my_sleepers` is excluded because it already has its own store — two
writers for one list is how the copies disagree
([docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md) records both, and the caps).

The Settings panel stopped claiming to blend lists it does not have
(Aug 21). Two different things were called **sources**: four hand-written
board entries with no data behind any of them, whose sliders compute one
ratio tilting the draft board between its tier order and live ADP; and
the real ranking lists, which blend with no weights at all. The panel's
note described the second while wired to the first. The fix is naming,
not deletion — the sliders keep working because they do something, the
group is now "Board order mix", the analyzer's slider reads **Board
order** instead of "Source influence", and both point at where the real
lists live. All four are named transforms in `app/feeds/page.py`
(`source_truth`), so a design resync that renames an anchor says so.

**League scoring is a column, not a sort key** — settled by the owner
on Aug 26 (*"league status should just matter for PPR point totals no
influence, remove slider"*), after the opposite was built and shipped
that morning. The averaged top-300 lists and live ADP decide the order;
your league decides what the number beside a player says. The League fit
slider and its blend term are reverted, not deleted — see
[docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md) for the commit to recover if
this is ever revisited, and for why the heading is not an invitation.

**The board's points column reads '26 projections** (owner, Aug 25:
*"i want to add total projected poitns to draft analzer beside PPG"*,
then *"yes lets add real projections"*). It carried last season's
measured line, which is honest and backwards for a draft. It now reads
**Rotowire's '26 forecast via Sleeper**, run through the same league
scoring as everything else — the endpoint was probed live before a line
of `app/feeds/projections.py` was written, and the reduce keeps only
`stats.PLAYER_FIELDS`/`DEFENSE_FIELDS` (borrowed, not re-typed) so the
stored blob is the scorer's vocabulary rather than all 71 keys Sleeper
sends. The column falls back to '25 when no forecast is stored, and the
**header is chosen by the same call that picks the numbers**
(`board._points_source`) so a '25 figure can never render under a '26
label. The forecaster is credited on the column and read off the payload,
so it follows the data if Sleeper switches house. Projections **omit
return yardage** — recorded in [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md),
which matters for return specialists in both IDP leagues.

**The main draft board now answers to league scoring too** (owner ask,
Aug 22: *"how does my leagues scores influence rankings"* — and on that
board, it did not). It orders by ADP and the blended rank lists; the
leagues reached it only through which ADP column it read and how deep it
went, neither of which is scoring. Its one numeric column was
`projFor`, a **fabricated linear slope** — a per-position base minus a
constant times the position rank, no data behind it and no league in it,
under a header reading "Proj". It now carries **last season's points per
game under whichever league is picked on that screen**
(`board.inject_league_points`), so a quarterback reads 27.9 in NDDPL and
51.4 in RED_EYE instead of occupying the same square. Same honesty rules
as `/app/scoring`: a league that cannot start a player gets no number and
a player the stats do not cover gets a dash, never an invention. The
header is renamed to `'25 P/G` by a named transform — a real number under
a "Proj" label would swap one wrong claim for another. Both edits land
together or neither does; a map injected beside a surviving formula would
keep rendering the invented number.


**The TD leans carry Rotowire's Week 1 forecast, and the Week review's
high performers are measured** (Aug 27, the two halves of STALE_DATA #7
that could go live). Sleeper's weekly projections endpoint was re-probed
before either line was written — the three TD fields exist under the
scorer's names on every row projecting the matching volume — and each
Predictions row now carries a labelled "Wk 1 forecast: …(Rotowire via
Sleeper)" clause appended beside the owner's lean, which stays untouched
(`vegas.apply_forecasts`, same contract as the AI check). DFS salaries
stay estimates — no open source — and the Data health row names both
halves. The Week review's stars column, curated since Aug 14, is now the
shown week's top seven PPR scorers from Sleeper's real box scores once
that week has finished games — preseason included, because Sleeper
publishes those too (probed). ESPN's preseason numbering runs one above
Sleeper's (HOF week); the mapping, its verified probes, and its
fails-empty property are in docs/ASSUMPTIONS.md. Stored stars for a
different week than the scoreboard shows are refused by a label match —
last week's men under this week's heading is the lie the tab's stamp
exists to prevent.

**The week's schedule ranks its own games, and the tabs that decide a
lineup read the same forecast** (owner, Sep 3–5: *"show who would be the
potential best games for fantasy points … list them from highest to
lowest"*, *"weekly stars … this helps drive who I play"*, *"people being
out impacts other player ceiling"*, *"put weather forecast"*, and *"another
tab for idp trackers … usually I just want to know tackles"*). The weekly
Rotowire forecast via Sleeper is now reduced in full (`projections.reduce_week`
keeps the scorer's whole vocabulary, defenders included) and one surface,
`app/feeds/gamestack.py`, turns it into everything downstream:

- **The game stack** on the Schedule tab (`gamestack.build`, rendered by
  `mobile.js showGameStack` under the `data-fb-gamestack` anchor): every
  game on the pushed slate ranked by its projected fantasy points under
  the league picked by chip, each with Vegas's implied score, the line's
  movement since the runner first saw it (`save_vegas` keeps a history),
  the forecaster's TD count, its top projected scorers with their live
  flag and latest wire post, who is out and the man measured behind him,
  and the weather where ESPN publishes one. A game the forecast does not
  cover is listed as uncovered, never ranked at zero.
- **Weather is read by a written rule** (`_WEATHER_RULES`, in
  docs/ASSUMPTIONS.md): rain and snow read wet/lean run, wind reads
  against passing, a fair day reads as easier to control. No forecast
  means nothing is said — the app never types "fair" by default.
- **Predictions carry the evidence beside the lean** (`injury.lean_clauses`
  then `gamestack.lean_clauses`, applied in `main.py` before the rows are
  injected): the latest wire post and Sleeper flag for the player, what
  Vegas implies for his team against what the forecast projects, the
  weather read, and which starter on his side is out. The owner's lean
  and confidence stay untouched; the clauses are appended, labelled.
- **Weekly stars** replace the Position analysis's curated column
  (`gamestack.weekly_stars`, `showWeeklyStars`): the top projected
  players per started position under each league, defenders measured in
  projected tackles.
- **`/app/idpweek`** is the IDP tracker: this week's projected tacklers
  per group a league starts, ordered by tackles first with each IDP
  league's points beside them, a dash naming the missing slot where a
  league cannot start the group. Linked from the analyzer with the other
  draft tools.
- **Depth charts come from Sleeper now** (`depth_chart_order`, practice
  participation and injury notes captured into the player index, probe
  run 31). `depth.chart` orders by the published slot first and falls
  back to '25 opportunity, so the Backup RBs usage and Next man up read
  the club's own order instead of inferring it. The AI matchup previews
  are handed the projected top scorers (`previews.pending(projected=)`)
  so the model reads fetched numbers, never its own.

Everything above is projection or measurement with its forecaster and
pull date on it; `scripts/verify_live.py` checks the ranking order, the
provenance and the clause counts against the deployment. Beat-writer
polling for line movement and weather is *not* built — the source list
has to be measured from the runner first (docs/GAP_REVIEW.md).

**Out & returning rows carry Sleeper's current flag** (Aug 29 —
cut-down weekend made the Aug-14 curated statuses' age visible). The
index refreshes every player's live flag each sync and the draft
board's badges already read it; the same measurement now sits on the
one tab whose whole subject is availability, labelled "Sleeper now:"
beside the owner's status, which stays untouched. Three-valued like
the wire stamps (`injury.live_status`): a flag, "no injury flag" for
an indexed-but-unflagged listed man (activated or cut — the reader
decides), and silence for a name the index cannot resolve. Joined
through `by_name`, which resolves shared names by rank — a second
resolver would be a second place to get Josh Allen wrong.

**No kicker types a date it cannot keep** (owner, Aug 26: *"Week
review didnt update stayed on week 1 even though week 2"* and *"NBC
player news is stale why not live"*). Both headings read "synced Fri Aug
14" — true for about a day, a lie afterwards, printed identically
whether the feed was an hour old or a month. **The NBC tab was never
stale**: the live watchdog measured 40 live rows of 53, newest the night
before, and only the heading said otherwise — a working feed reading as a
dead one because of a typed string. Week review was the opposite: when no
scoreboard is pushed the page falls back to `WEEKREV_SEED`, which is
labelled "Preseason Week 1" and renders Aug 13–15 games as though they
were current, under a sync date agreeing with them. `weekrev.stamp()`
now reports the real pull time and says **OLDER THAN A WEEK** past
`_STALE_AFTER` (8 days — a scoreboard describes one week, so an old one
is last week wearing this week's heading), the NBC kicker reads whether
its top row is live (curated seed rows carry no `link`; every live row
does), and `page.dated_kickers_read_the_data` replaces both typed
dates.

**Back goes where you came from** (owner, Aug 26: *"When i select
areas and new pages are opened i should go back to the previous page im
at right now i go bak to main alerts page that doesnt help"*). The code
said so out loud: the control was `backToAlerts`, hardcoded to
`screen: "alerts"`, under a button reading "Back to alerts". Opening a
player from the Draft analyzer and leaving cost you your place every
time — worst exactly when you are working a board and checking players
one after another. `page.back_where_you_were` remembers the last
**sidebar** tab (not transient sub-screens: being returned to a player
detail you already left is its own kind of wrong), derives the button's
label from the same `titles` map the header reads so it cannot name a
destination the click does not go to, and persists the tab so `/app/` —
the only way home from every served page — reopens where you were. Per
device on purpose: a cursor, not a list. It is the one transform here
that is **genuinely atomic**, checking all five anchors before writing
any: `_apply` reports a miss and applies the rest, which is right for
independent edits and wrong for two halves of one promise.

**One wire, one name: Alerts** (owner, Aug 26: *"news and post and
alerts are same thing stay with alerts"*). They were right, and the app
was worse than inconsistent. The Alerts screen **already** merged the
live polled wire with the owner's curated calls
(`ALERTS.concat(newsThreads)`, newest first, paged) — the data was never
split. What was split was the door and the name: "News & posts" was a
second entry into items Alerts was already showing, and Alerts' own badge
was the hardcoded string `"6"`, describing the curated rows alone. A
badge that under-reports by two orders of magnitude is not cosmetic — it
is the number a reader uses to decide whether the tab is worth opening,
and it was telling them not to bother. `page.alerts_is_the_wire` closes
the second door, counts what is really there, renames the sidebar group,
and makes the kicker say the feed is live. **"NBC player news" stays**: a
named publisher's cut is a real distinction, not a third synonym, and its
blurbs carry editorial leans a headline cannot replace. The sleepers
panel's own "posts" wording went with it — the app had three words for
one wire and that panel had just added the third.

The **Sleepers tab is now your list, not an analyst's** (owner, Aug 26:
*"right now it doesnt make sense and this list should be editble like we
discused"*). It shipped as 19 rows transcribed by hand from PFF, Yahoo
and Bleacher Report on Aug 14 and frozen there — somebody else's picks,
from before the preseason, with no way to change them. Staleness was the
symptom; the disease was that a list you cannot edit is not your list, so
re-transcribing it would have fixed nothing. The tab opens on a per-user
watchlist (`app/feeds/watchlist.py`, stored beside your ranking lists and
league settings) and, under it, **a thread of the real polled items
mentioning those players**. That thread is a **join, not a search**: the
poller already tags every item with the players it mentions, so this is a
lookup against work already done and it renders the item's own headline
and link rather than a summary of one. A watched player nobody has
written about reports **zero posts rather than being hidden** — "nobody
is talking about him" is a real answer to what a sleeper list asks, and
often the point of one — and a name the player index does not carry stays
on the list, flagged, because dropping it would be the app overruling
what somebody typed. The tab now holds **one list, not two** (owner, Aug 26). The page
shipped its own `mySleepers` in localStorage, toggled by the stars on the
analysts' table and the "Slpr" stars on the draft board, so starring a
player did not put him in the panel and the panel's players wore no star
— and the list lived on one device. `board.inject_sleepers` rewires all
three halves together (the const the page reads, the seed that fills its
state, the toggle that writes back), the panel hands the page its new
list through `__fbSetSleepers`, and a star elsewhere dispatches
`fb-sleepers-changed` so the panel re-reads — an event rather than a
flag, because a flag is only noticed the next time something else
redraws. A signed-out reader keeps their browser's list untouched.
The 19 analyst rows are **kept below it, dated and
retitled** "Analysts' picks · hand-read, not live": nineteen researched
names are a fine place to start a list from, and the failure was that
they were the *only* list. The app deliberately does not decide who your
sleepers are.

The tab's third section is the **community consensus** (Aug 28, from a
handoff thread — the other half of the owner's Aug 25 *"we also show
sleepers alerts in seperate thread where we search for new articles on
sleepers"*): a nightly job reads full articles from five fantasy
publishers, has the AI reader classify each author's **actual stance**
per player named — a mere mention is dropped, not inflated — and blends
the positive calls with Sleeper's add/drop trends into one ranked list.
`scripts/fetch_sleepers.py` runs on the Actions runner (`sleepers.yml`)
and **pushes** to `/internal/sleepers`; nothing is committed by a bot.
The handoff's draft was adapted to the house rules before landing: the
model call goes through `draft_verdicts.chat_with_retry` (the owner's
provider, not the draft's hardcoded Anthropic), the name matching is
`app.feeds.players` (one matcher, not two), defenders stay in because
both verified leagues start eight of them, and rows are rebuilt field by
field at the door (`watchlist.clean_consensus`). Honesty carries the
design: the section renders only once a push exists, wears the data's own
fetch date, labels every one-liner "AI read:", reports dissent beside the
score rather than averaging it away, credits Sleeper, and an empty run
leaves the stored block alone (the verdict-wipe class, again). The
publisher list was **measured from the Actions runner** (Aug 28, probe
runs 22-23 — neither sandbox could reach the hosts): ten candidates
checked, five answered (PFF, PlayerProfiler, Razzball,
DynastyLeagueFootball, RotoBaller), and the dead five — ESPN's feed URL,
FantasySP, Reddit (403s runner IPs), both FantasyPros guesses — are kept
commented in `SOURCES` with their failure modes. The workflow's check
mode re-verifies the list; every tuned constant is in
docs/ASSUMPTIONS.md. The anchor is a named transform (`page.sleepers_watchlist`)
and the panel is built client-side, so `tests/test_watchlist.py` runs the
real `mobile.js` under node against the real **served** page — the anchor
does not exist on disk, and reading the file would test something no
browser ever sees.

`/app/scoring` is the scoring board (owner ask, Aug 21): every player's
stored stat line run through **each league's own scoring values**, ranked.
Every other board in the app orders by an opinion — ADP, a cheat sheet, a
blend — and this one orders by arithmetic, which is what finally makes a
league's quirks an ordering instead of prose: RED_EYE's point per
completion is worth 400 points to a 400-completion quarterback, and
BALLAPALOSA's unhalved receiving is worth 75 to a 1500-yard receiver.
Season total is the headline (it is what wins a league), per game sits
beside it (a total is also what makes a half-season look finished), and
the numbers are raw points — points-above-replacement needs a defensible
baseline per slot per league and is deliberately not guessed. A league
that cannot start a player shows a dash naming the missing slot, never a
zero, and team defenses are ranked in their own table because a D/ST is
not comparable to a player on volume. BALLAPALOSA's column is labelled a
**floor**: its per-game bonuses (`League.per_game_bonuses`, verified from
its settings page) cannot be recovered from a season aggregate, so the
page names what is missing rather than reading quietly short.

The Draft analyzer says **how its average is made** (owner ask, Aug 21).
Ranking lists are blended with **no weights at all** — every list that is
switched on counts the same, and a player's blended rank is his average
place across the lists that carry him, so a short list cannot push him
down and a player nobody ranks gets no invented rank. The analyzer now
renders that set as a panel: each list's size, its as-of date and age, its
scope, and whether it is in the blend — **including the ones switched
off**, because "why is this source not counting" is the question a panel
showing only the active ones cannot answer. The set is injected at serve
time and re-read from `/app/data/ranksources.json` when the tab regains
focus, so a list added or removed at `/app/mine` in another tab shows up
without a hard reload. Five real lists ship with the app, extracted from
the owner's own PDFs: two 300-player overall sheets, and three 40-deep
ESPN IDP sheets (DL/LB/DB) that are scoped within position and start
inactive. `tests/test_ranksources.py` runs the real `mobile.js` under node
against the real anchors in the committed `index.html` — the panel is
built client-side, so nothing else proves it renders.

The login gate (owner request, Aug 20): `/login` + an owner-managed email
allowlist at `/app/access` with one-time invite links — built, tested, and
**off by default**; the owner enables it with four Vercel env vars
([docs/ACCESS.md](docs/ACCESS.md) has the steps and the lockout escape
hatch). Sessions are signed cookies, invites are stored hashed, the
allowlist lives in its own Redis key so no sync can clobber it, and the
runner/watchdog pass with X-Sync-Token. `/api/*` deliberately stays open
(GAP_REVIEW #11). On top of it: `/app/leagues` lets each user describe
their own league — full custom scoring, not presets — and the mock room
and IDP board then score with it (docs/LEAGUE_SETTINGS.md); `/app/mine`
gives each signed-in user their own private layer (named text/CSV
documents, per-email Redis key),
and adding a user can email them the invite + app intro when mail is
configured. That email deliberately carries **no league links** (owner,
Aug 25) — email is the one surface that leaves the gate, so a forward or
a shared inbox would hand the owner's own teams to people never given
access. **Passkeys** (Face ID / Touch ID) layer on top:
register from `/app/mine` after a normal sign-in, then the login page
signs you in with a face or fingerprint — discoverable credentials, user
verification required, public keys only, and the allowlist still governs
(revoking an email deletes its passkeys). Bound to an RP ID — the hostname
unless `PASSKEY_RP_ID` pins the registrable domain, which makes a later
apex-to-subdomain move free instead of a re-registration for everybody. All of it in docs/ACCESS.md.

Not yet done: verified against a live Yahoo account — blocked on Yahoo's
fantasy-access approval (see docs/RESUME.md), not on code.

Phase 3 (cron jobs polling feeds on their budget intervals, a database, and web
push for the Settings rules) builds on this service — hence the Dockerfile and
the store interface.

Phase 4 is **Productize** — the transition from "owner + 5 testers, free" to
something sellable: [docs/PRODUCTIZE.md](docs/PRODUCTIZE.md) has the real
costs (~$21/mo floor: Vercel Pro, since Hobby is non-commercial, plus a
~$10/yr domain), the licensing blockers, and the *order*. **Planning only —
do not build from it without the owner asking.** The custom domain
exists: **`fantasysportsbible.com` serves production**, verified live
Aug 29 (probe run 24 — `/health` answers with the app's own JSON; DNS
sits behind Cloudflare's proxy, a divergence from the runbook's
grey-cloud advice that PRODUCTIZE.md now records). The time-sensitive
item narrowed accordingly: passkeys are bound to the hostname, so
`PASSKEY_RP_ID=fantasysportsbible.com` should be set (docs/ACCESS.md)
and registrations should happen at the domain — a key registered at the
vercel.app URL is not offered there.
