# Assumptions — Aug 22 2026

A review of everything built on Aug 21–22, looking for the places where a
number was **chosen rather than measured**, or a rule was **interpreted
rather than asked**. Owner request: *"show where things may have not been
thought out right, where you made assumptions I may want to know."*

[GAP_REVIEW.md](GAP_REVIEW.md) is the list of things known to be *wrong*.
This page is different: everything below currently *works*. Each entry is
a judgement call that nobody signed off on, written down so it can be
overruled instead of inherited.

Format: what was assumed, where it lives, why that value, and **what
changes if it is wrong**. The last part is the one that matters — an
assumption whose failure changes nothing is not worth your attention.

## Read this first — the one that already bit

**Three injections shipped keyed to the wrong spelling of a name.**
`live_adp` has always re-keyed its map onto the names the *page* uses,
and its docstring says why: the injected lookup is an exact string match
at runtime. The three injections added Aug 22 — league points, the injury
badge, and the reserve drop — each skipped that step and keyed by
Sleeper's spelling instead. Sleeper writes `Ja’Marr Chase` with a curly
apostrophe; the design document writes a straight one. `match_key` folds
them; `===` does not.

So for every such player: no `'25 P/G` number, no injury badge, and — the
bad one — **no drop**, a season-ending rule that silently did not apply to
him. Seven of the 205 board rows carry an apostrophe
(`Ja'Marr Chase`, `De'Von Achane`, `D'Andre Swift`, `De'Zhaun Stribling`,
`Tre'von Moehrig`, `Wan'Dale Robinson`, `Ka'imi Fairbairn`); how many
Sleeper spells differently could not be measured from the build container,
which has no route to either API. Fixed by `board._rekey_to_page`
(`app/feeds/board.py:255`).

The general lesson, and the reason it is at the top of this page rather
than buried in the gap review: **the mechanism was already solved and
documented in the module being edited, and three consecutive changes
walked past it.** Any future map injected into the page must be re-keyed
the same way.

Worse, the watchdog check that should have caught it was a set
intersection — "is anybody on a reserve list still on the board" — and a
badge keyed by a spelling the board does not use makes that check pass by
finding nothing. It was **green because it was broken**, the exact failure
mode `CLAUDE.md` warns about. `scripts/verify_live.py` now asserts that
every key in `FB_LEAGUE_PTS` and `FB_INJURIES` matches a row that exists,
which catches the class rather than the instance.

**It failed on its first run**, and on something the re-keying had not
fixed. Both decorations were being built *before* the board's membership
was settled: `drop_reserve` then removes rows (five scored players matched
no row) and `deepen` then appends them — and the appended rows are about a
third of the served board, none of which carried a points figure or an
injury badge. Silent in both directions, live, for a day. `board.decorate`
now owns the order — membership first, decoration second — and
`tests/test_board_decorate.py` pins it.

Both instances have the same shape: **a name-keyed map is only correct for
the rows that exist at the moment it is built.** That is the rule worth
carrying forward, not the two fixes.

## Rules interpreted, not asked

### "Out for season → drop; out a few weeks → leave"

Your rule, Aug 22. The constraint: **Sleeper publishes no season-ending
field.** `injury_status` says what a player is *designated* as, never for
how long. A player on IR may be done for the year or may be designated to
return, and nothing in the feed separates them.

So the line was drawn where the data draws one — a **reserve
designation**, which carries an NFL multi-week minimum, against a
**weekly game status**, which does not
(`app/feeds/players.py:55`):

| Drops off the board | Stays on it |
| --- | --- |
| IR, PUP, NA, DNR, **Sus** | Out, Doubtful, Questionable |

**The assumption you may want to overrule:** `Sus` (suspension) is in the
drop list. A suspension is not an injury — it is a known-length absence,
often four games, and the player is fine when it ends. Treating it like
IR is defensible in August (you cannot start him) and arguably wrong in a
keeper league or a deep bench format. It is one entry in one frozenset.

**Also assumed:** `Doubtful` counts as fully "out" for `/app/nextup`'s
pickup trigger (`app/feeds/depth.py:165`) but only as a weekly status for
the draft board. Those are different questions with different right
answers, so the split is deliberate — but it does mean a doubtful player
generates a "his backup is the pickup" row while still occupying his own
draft slot.

**And:** an injury flag Sleeper invents tomorrow that this code does not
recognise is classified **questionable**, not ignored
(`app/feeds/players.py:68`). Chosen because a flag we cannot classify is
still a flag, and silently dropping it is the more confident mistake. The
cost is that a future non-injury designation would wear a yellow badge.

### A player dropped from the draft board is *not* dropped from `/app/scoring`

Deliberate, and worth stating because the two boards now disagree on
purpose. `/app/scoring` ranks what a player **did** last season; being on
IR today does not un-score those points. It prints his flag beside the
row instead. The draft board is a forward-looking instrument and drops
him. If you would rather the scoring board hide reserve players too, that
is a one-line change — but it would mean the arithmetic board stops
reporting arithmetic.

He also still appears on `/app/nextup`, which is correct: a starter on IR
is precisely when the pickup question matters.

## Numbers picked out of the air

None of these came from a measurement. Each is followed by what it costs
if it is wrong.

| Value | Where | Why that number | If wrong |
| --- | --- | --- | --- |
| `PLAYER_RETENTION_SECONDS = 14 days` | `app/feeds/store.py:31` | Long enough that a multi-day feed outage cannot erase the index, short enough that a truly abandoned deploy expires. Replaced a TTL that was deleting the index during outages — the failure it was written to stop. | Too long: a dead deploy serves month-old names. Too short: a long outage empties every board at once. The 20-hour freshness stamp (`players.py:311`) is what actually decides "stale", so this is only the floor. |
| `SEASON_GAMES = 17` | `app/feeds/replacement.py:59` | The NFL regular season. | Fine for season totals; wrong the moment anything converts a *fantasy* season (14 weeks in most leagues) to per-game. Only `par()`'s draft-slot conversion uses it. |
| `POINTS_PER_ROUND = 3.0` | `app/leagues.py:48` | Pre-existing, and its own comment already calls it "the shakiest number here". Inherited by `replacement.par()`, so the QB verdicts are quoted in slots that rest on it. | The *direction* of every QB verdict (all three leagues say "wait") is independent of it. Only the magnitude in slots moves. |
| `TOP = 200`, `MIN_GAMES = 1` | `app/feeds/topscorers.py:65,69` | 200 covers a 12-team roster deep into the bench; one game keeps a real September performance visible instead of hiding it behind a threshold. | `MIN_GAMES = 1` means a single big game can top the per-game column. The season-total headline is the defence against that, which is why it is the headline. |
| `MAX_WATCHED = 60`, `thread(limit=40)` | `app/feeds/watchlist.py:36,86` | A sleepers list is a shortlist; 60 is past any reasonable one and stops a pasted cheat sheet turning the watchlist into a second ranking list. 40 posts is the same cut the Alerts overlay uses (`MAX_LIVE_ITEMS`), so the two threads read at the same depth. | Too low: a deep-league drafter silently cannot add a 61st name — the add is refused, not truncated, so nothing is lost invisibly. Too high: the tab becomes a ranking list nobody maintains. Neither number affects what the thread *contains*, only how much of it renders. |

## A name two players share goes to the higher-ranked one

**Chosen Aug 26, after the owner reported the sleepers list "choses wrong
person".**

Josh Allen is a Buffalo quarterback and a Jacksonville linebacker. Lamar
Jackson is a Baltimore quarterback and a corner. `by_name` was a plain
dict assignment, so **Sleeper's dump order decided** which one owned the
name — and it gave "josh allen" to the linebacker. Anyone adding him to a
sleepers list got the wrong man's team and the wrong man's wire, and the
same key feeds news tagging and the handcuff join.

**The choice:** the lower `search_rank` wins — Sleeper's own measure of
fantasy relevance, so the quarterback (12) beats the linebacker (240). An
unranked player never takes a name from a ranked one. Two unranked
players fall back to the lower id: arbitrary, but *stable*, which dump
order was not.

**What this does not do:** make the name unambiguous. It makes the answer
defensible and repeatable. The surname map refuses ambiguity outright and
this cannot — dropping "josh allen" would cost the quarterback his own
name in order to spare the linebacker, which is worse for every user.

**If it is wrong:** somebody who genuinely wants the Jacksonville
linebacker on a sleepers list cannot have him by name. The row shows
position and team (`QB · BUF`), so they can *see* they got the wrong man,
but they cannot currently correct it — there is no "no, the other one"
control. `shared_names` on the index records every contested name, so the
size of the problem is measurable rather than assumed.

## Which of the page's own storage keys follow an account

**Chosen Aug 26, after the owner reported "back up running backs list
does not save for users" and "when i log into other devices i dont see my
changes".**

The design document keeps fourteen things in `localStorage`. Nine of them
are the reader's own work and now travel with the account
(`prefs.MANAGED`): the backup-RB order and cleared rows, the draft queue,
who is taken, my teams, the draft slot, dismissed scout cards, and the two
slider-weight keys.

**Five deliberately do not.** `ww_theme`, `ww_skin` and `fb_team` are
appearance — a phone in the dark and a desk monitor are different rooms,
and CLAUDE.md pins two of them as immutable storage keys. `ww_live` is a
cache and `ww_api_base` a developer override; neither is anybody's work.
`ww_my_sleepers` is excluded for a different reason: that list already has
its own route and store, and a second writer is how the two copies start
disagreeing.

**If it is wrong:** somebody who wants their theme to follow them will not
get it, and somebody who expects a per-device draft queue will be
surprised that it followed them. Both are one line in `prefs.MANAGED`.

## Caps on the saved-preferences blob

**Chosen Aug 26 with the mechanism above.** `MAX_VALUE = 64KB` per key,
`MAX_TOTAL = 256KB` per account. A 300-name `ww_taken` is roughly 6KB, so
one value is generous by an order of magnitude, and the total bounds what
one account can push into a blob that is loaded on **every page render**.

An oversized value is **dropped, never truncated**: half a JSON array is
not a smaller list, it is a corrupt one, and the page would read it back
as empty and lose the lot. Over the total, the *largest* values are
evicted first — nothing here is older or less wanted than anything else,
so dropping one big list loses fewer of the reader's lists than dropping
several small ones.

**If it is wrong:** the numbers are two constants in `app/feeds/prefs.py`,
and a reader who hits the cap loses their biggest list silently, which is
the part worth improving first if it ever happens.

## Measurements that lean on a model

### IDP opportunity counts an assist like a solo tackle

`app/feeds/depth.py:55` — a defender's "opportunity" is
`idp_tkl_solo + idp_tkl_ast`, weighted equally. But NDDPL pays **1.0 for a
solo and 0.5 for an assist** (`app/leagues.py:469-470`).

The defence: `depth` is measuring *involvement* — a proxy for snaps and
role — not fantasy value, and for that purpose a tackle is a tackle. The
honest objection: the page presents the number next to fantasy decisions,
and a high-assist linebacker reads better there than he scores. Two lines
to weight it per league if you would rather it match the scoring.

### The flex is filled greedily

`replacement.depths()` (`app/feeds/replacement.py:108`) decides how deep
each position gets drafted before "replacement" begins. Dedicated slots
are arithmetic — `teams x starters`, nothing assumed. The flex is not: each
flex slot is handed, one at a time, to whichever eligible position has the
highest next-available player by that league's scoring.

That assumes managers fill a flex with the best available player. Real
rooms do not always — they fill it positionally, or they hoard. The
alternative was splitting the flex by an invented ratio, which is worse
because it is an invention with no feedback loop. Greedy is at least
answerable to real scoring data. **It is still a model of behaviour, not
an observation of it.**

Same mechanism handles RED_EYE's generic `D` slot, with the same caveat.

## Wired to less than it looks like

### The board's `'25 P/G` column reads the *built-in* leagues only

`app/main.py:267` passes `leagues.defaults()`. So a league you describe
yourself at `/app/leagues` scores `/app/idp` and the mock room — and gets
**no column on the main draft board**. Not a decision, an omission: the
injection was written against the three verified leagues and never
threaded the per-user list through. Worth knowing before you build a
custom league and wonder why that column is blank.

### The per-league ADP column distinguishes nothing today

Probed live Aug 22 (probe runs 13 and 14). FantasyFootballCalculator
echoes the `teams` parameter back in its meta — `teams: 10` and
`teams: 12` — and then serves **the same pool for both**: 7,288 drafts,
266 players, the same Aug 15–22 window, at either size. So every player
reads the identical number in the 10-team and 12-team columns, which the
watchdog now reports rather than assumes.

The machinery is right and it stays: `League.adp_size_key` picks the
column, `blend()` keeps both, and the day FFC differentiates by size the
leagues will diverge with no code change. But **the board's per-league
ADP is currently a distinction without a difference**, and it is worth
knowing that before reading anything into two leagues showing the same
market number. It is also why the Aug 22 column swap — RED_EYE reading
the 10-team column — produced no visible wrong number: both columns
carried the same value. The bug was real and the fix is right; the
symptom was invisible.

One caveat on the measurement: `live_adp` falls back to the blend for a
size a player is missing from, so `a10`/`a12` are always populated and a
count of them proves nothing about coverage. The watchdog counts how
many players *differ* between the columns instead.

### Password and throttle numbers, all chosen

None of these were measured; they are the conventional settings for a
small private app, and each is one constant.

| Value | Where | If wrong |
| --- | --- | --- |
| `PW_MIN_LENGTH = 10` | `app/authn.py` | Length is the only rule — no composition requirements, which push people toward `Passw0rd!` and buy nothing. Ten is short for a public app and ample among five friends. |
| scrypt `n = 2**14` | `app/authn.py` | ~50ms a check here. Higher is safer and eats the serverless budget; the parameters are stored per record, so raising it later does not lock anybody out. |
| `THROTTLE_MAX_FAILS = 5` | `app/authn.py` | Low enough to stop guessing, high enough to survive genuinely fumbling a password. |
| `THROTTLE_LOCK_SECONDS = 900` | `app/authn.py` | Deliberately short: a long lock turns "hammer their address" into a denial of service against the person you are protecting. |

The trade the whole feature makes, stated once: before this the app
stored nothing that could impersonate anyone even if the entire store
leaked. Password hashes are a target where there was none. scrypt is
what makes that an acceptable trade rather than a careless one — and
the owner's own credential deliberately stays out of the store.

### League points are a *column*, not a sort key — SETTLED Aug 26, do not rebuild

The board orders by ADP and the blended rank lists. Your scoring appears
on every row and changes nothing about where the row sits.

**This is now a decision, not an open question.** It was built the other
way on Aug 26 — a League fit slider blending each player's rank under the
selected league's scoring into `blendScore` — and the owner removed it
the same day: *"league status should just matter for PPR point totals no
influence, remove slider"*.

So the entry that used to sit here ("if you expected the board to
re-sort, it does not") is answered: the owner does not. Scoring belongs
in the column, where it says what a player is worth without overruling
the consensus of the ranking lists. The averaged top-300 lists and live
ADP decide the order; your league decides what the number beside him
says.

**If it is wrong:** the reverted commit is `6412712` and its revert is
the one after it, so the whole mechanism — the rank cache, the blend
term, the slider, and the tests that ran the generated JavaScript under
node — is recoverable rather than rewritten. Do not rebuild it from
scratch, and do not treat this heading as an invitation.

### The mock room drafts injured players as though healthy

`app/feeds/mock.py:523` — `price()` reads position and ADP and the QB
boost. It never reads `p.inj`, which is carried all the way to the render
and then only displayed. So autopick will spend a second-round pick on a
player wearing an "Out" badge, for you and for the nine simulated rooms.

Left open rather than fixed quietly, because **how far an injured player
should fall is a judgement, not an arithmetic** — and it is yours. A
reserve designation and a weekly status clearly should not cost the same.
This is also in [GAP_REVIEW.md](GAP_REVIEW.md); it is repeated here
because it is the largest gap between what a surface shows and what it
acts on.

### Appended depth rows carry no live ADP

The third instance of the map-keyed-too-early class, and the one **not**
fixed. `board.inject` builds the live-ADP map before `deepen` appends its
rows, so every appended player shows a dash in the ADP column. It predates
Aug 22, and unlike the other two it is arguably fine — these are round-20+
depth rows carrying an explicit "no scouting read yet" note. Left alone
rather than swept into an unrelated commit; say the word and it moves.

### During an index outage the board shows no injury badges at all

`inject_injuries` replaces the committed name lists whether or not the
index answered, so a missing index means every badge is cleared — which
reads as "everybody is healthy". Deliberate, because the alternative is
asserting hand-typed statuses from weeks ago, which is the bug this
replaced. But "no badges" is still a claim, and the honest third option —
saying status is unavailable — does not exist. The index went down for
several hours on Aug 22, so this is not hypothetical.

### Nothing anywhere labels a carried-forward index as stale on the board itself

`/health` reports `players.age_hours` and the sync records `index_error`,
so the outage is *diagnosable*. But a board served from a 30-hour-old
index looks identical to a fresh one. The freshness constant exists
(`FRESH_SECONDS`, 20h) and nothing user-facing consumes it.

### `WEEKLY_FLAGS` is defined and never used

`app/feeds/players.py:60`. It exists to name the other half of the reserve
split, and nothing reads it — the code asks `is_reserve` instead. Harmless,
but it is documentation wearing a constant's clothes, and a reader may
reasonably assume something enforces it. Kept for now because it makes the
frozenset above it legible; delete it if the fence starts complaining.

## What was *not* assumed

Stated so the list above is not read as a blanket disclaimer. These were
verified rather than guessed:

- **Every scoring value** in `app/leagues.py` comes from your Yahoo
  settings pages ([LEAGUES.md](LEAGUES.md)), including the corrections
  that overrode earlier chat-era descriptions.
- **Replacement depth** is derived from each league's roster, never
  configured — a league that changes its slots changes its depth with no
  edit.
- **The QB verdicts** (as of Aug 22: NDDPL −110, RED_EYE −16,
  BALLAPALOSA −61 points of spread against the best rival position, all
  "wait") are computed from real stored stats and move as the stats do. An earlier prediction of RED_EYE at *+36* came from a
  synthetic pool and was wrong by 52 points; the real data corrected it.
- **The `qb_boost_override` values are kept deliberately.** They encode
  how those rooms actually draft, which is evidence — just not
  valuation-model evidence. That two leagues with near-identical spread
  premiums draft quarterbacks differently is a finding for you, not a bug
  to paper over.

## How to overrule any of this

Every entry above is a constant or a small function, named with its file
and line, and each has a test pinning current behaviour. Changing one
means changing the value and the test that asserts it — which is the point:
nothing here can drift silently, it can only be revised on purpose.

## A ranking list is "old" at 21 days

**Chosen Aug 25, with the draft-page list controls.**

The panel flags a list older than three weeks with "preseason has moved
since this". Twenty-one days is a judgement, not a measurement: preseason
is when depth charts and injuries redraw a board, so a top-300 sheet
written before the games describes a different league — but no source
publishes the day a ranking stops being useful.

**What it does and does not do.** It adds a line to the row and tints it.
Nothing is switched off automatically, and the blend is unchanged. The
owner asked for controls because "they olderones may get outdated based
on preseason"; deciding *for* them which lists are past it would be the
app forming an opinion it cannot support.

**If it is wrong:** the number lives in one place, `STALE_DAYS` in
`frontend/mobile.js`. Too low and every list wears the note by
mid-September, which trains people to ignore it; too high and it never
fires when it matters, in the last fortnight before a draft.

## Projected totals omit return yardage

**Chosen Aug 25, when '26 projections were added.**

Rotowire's projections (via Sleeper, probed live) carry no return
**yardage** for any group — not `kr_yd`/`pr_yd` for returners, not
`idp_int_ret_yd`/`idp_fum_ret_yd` for defenders, not `int_ret_yd`/
`fum_ret_yd` for team defenses. Return **TDs** are partly there
(`pr_td`, `def_kr_td`); the yards are not.

Both IDP leagues pay for those yards — NDDPL 20 yds/pt on kick and punt
returns and 20 on IDP turnover returns, RED_EYE 20 and 10
(docs/LEAGUES.md). So a projected total is short by whatever a player
earns returning, while the '25 measured column beside it includes it.

**The choice:** score the projection with the fields that exist and say
so, rather than modelling the missing ones. A return estimate would be
this app's invention sitting inside a column labelled as somebody else's
forecast, which is worse than a number that is honestly a little low.

**Size of it.** Negligible for most defenders — 60 interception-return
yards is 3 points at 20 yds/pt. Not negligible for a dedicated kick
returner, who can clear 1,000 return yards in a season and so be
understated by 50+ points in either IDP league. Read a projected total
for a return specialist as a floor.

**If it is wrong:** `tests/test_projections.py` pins the absence of all
four fields, so the day Sleeper starts carrying them the test fails and
the caveat comes off rather than outliving its reason.


## ESPN's preseason weeks are Sleeper's plus one

**Verified Aug 27, not chosen — recorded because it looks arbitrary.**

ESPN's scoreboard counts the Hall of Fame game as its own preseason
week; Sleeper's stats endpoint does not. Probed live the day this was
built (probe runs 18/20/21): with ESPN reporting "Preseason Week 4",
Sleeper's `pre/2026/3` was filling from that night's games, `pre/2026/2`
held the full previous week (3,071 entries, 781KB) and `pre/2026/4` was
a literal `{}`. So `weekrev.sleeper_week` maps a preseason label to
ESPN's number minus one, refuses ESPN's week 1 (it would be a Sleeper
week 0 that does not exist), and refuses playoffs outright — that
numbering has never been probed. Regular-season weeks map straight
across; the scorecard has graded on that equivalence since Aug 21.

**If it is wrong** — say a future preseason drops the HOF week — the
mapping breaks *empty*, not wrong-week: an unpublished Sleeper week is
`{}`, `build_stars` produces nothing, and the curated column stands. The
one failure it cannot catch is both numberings shifting together, which
is why the coverage label on every measured star names the game count
("through N of M games") a reader can check against the scores column
beside it.

## The Week review shows seven measured performers

**Chosen Aug 27.** `weekrev.TOP_STARS = 7` — the curated seed's own row
count, kept so the measured column occupies the same space the curated
one did. Ranked by Sleeper's `pts_ppr`, which is their arithmetic under
standard PPR, credited as such — not any of the owner's three leagues'
scoring. Running league scoring here would need a league picker on a tab
that has none; the honest cheap answer is one well-labelled market
number. **If it is wrong:** one constant, and the read on every row says
whose scoring it is.

## The TD-lean forecast is pinned to Week 1

**Chosen Aug 27, derived from the tab rather than the calendar.**
`projections.PRED_WEEK = 1` because the Predictions rows are Week 1
props — the caption says so, and the ledger snapshots them against
regular-season weeks only. Fetching "the current week" instead would
serve preseason numbers as evidence for a Week 1 line. **If it is
wrong** — the owner starts writing leans for later weeks — the constant
moves to whatever names the predictions' week, and the clause's own "Wk
1" label is what makes the mismatch visible in the meantime.

## The community sleeper consensus is chosen numbers all the way down

**Chosen Aug 28**, in the handoff thread that designed
`scripts/fetch_sleepers.py`, and inherited here deliberately rather than
re-guessed. The nightly job reads the fantasy wire and ranks who writers
are recommending; almost every constant in it is a judgement call:

- **A stance under 0.4 confidence is dropped** (`MIN_CONFIDENCE`), and
  `"mentioned"` is dropped at any confidence — the model classifying a
  teammate reference as a recommendation is the false positive the whole
  pipeline is built to avoid. Lower it and the list fills with noise;
  raise it and quiet-but-real recommendations vanish.
- **The score is** `sources × recency × (1 + buzz) / (1 + roster% / 20)`
  with recency doubling calls made in the last 3 days and buzz reading
  Sleeper adds minus half the drops, per thousand — **clamped to
  [-0.5, +1.0]** (`BUZZ_CEILING` / `BUZZ_FLOOR`). The clamp is the one
  constant here that was *tuned against a live run* rather than
  inherited: the first night was roster-cut week, one player's 60,579
  adds multiplied a single article 61× past every two-source consensus,
  and the list read as Sleeper's trending page with citations. Owner
  call, Aug 29: consensus drives, buzz leans — the hottest spike can at
  most double a score and a drop-wave at most halve it, so a second
  writer always outweighs any amount of trending. The raw add count
  still renders on the row, so the spike stays visible. The remaining
  constants encode "breadth of agreement beats volume, recent beats
  stale, and a player everyone already holds is not a sleeper". Dissent
  (bust/fade calls) is **reported, never subtracted** — an average would
  hide both the love and the warning.
- **Windows and caps:** 10-day lookback, 40 articles a night, 15
  candidates per article, 40 rows stored
  (`watchlist.MAX_CONSENSUS_ROWS`), 12 rendered
  (`CONSENSUS_SHOWN` in mobile.js), Reddit threads under 25 net upvotes
  ignored, and **5 articles per model call** (`BATCH_SIZE`) with 6 s
  between batch calls. The batching was tuned against the first two
  live runs (Aug 29): at one call per article the free tier's throttle
  marched all 40 requests through the full backoff ladder and the runs
  took 38 and 58 minutes — the same calls-fight-for-one-quota failure
  the verdicts job measured on Aug 18. Eight requests instead of forty,
  each given a **240 s read window** (`BATCH_TIMEOUT` — the default
  120 s died mid-generation on the first batched run, Aug 29, and a
  five-article answer is long; network failures now ride
  `chat_with_retry`'s transient ladder instead of crashing the run);
  each article's stances are filtered against that article's own
  candidate list so a row the model files under the wrong article dies
  instead of crediting a source that never said it.
- **The live check calls the block broken at 3 days**
  (`verify_live.MAX_CONSENSUS_AGE`): the job is nightly, GitHub's
  scheduler delivers roughly a fifth of what is asked, so one slipped
  night is jitter and three is a dead job wearing a live heading.

**If any of it is wrong:** every constant is a one-line edit in the file
that owns it, and the panel's own as-of stamp plus the dissent column are
what keep a bad tuning visible instead of authoritative.

The sources, unlike the constants, are **measured**: neither build
sandbox could reach the publishers, so the check ran from the Actions
runner (probe runs 22-23, Aug 28). Ten candidates, five answering — PFF
25 entries, PlayerProfiler 100, Razzball 30, DynastyLeagueFootball 10,
RotoBaller 15 — and five dead, kept commented in `SOURCES` with their
failure modes (ESPN's feed URL 0 entries, FantasySP 0, Reddit 403s
datacenter IPs, both FantasyPros WordPress-shape guesses 0). Sleeper's
trending add/drop and the `research/regular/2026/1` ownership endpoint
(831 players) all answered with the shapes the script reads. The
workflow's check mode re-verifies all of it on demand; its OK/DEAD log
decides the list, not anybody's memory.


## The overlay re-pulls on wake, at most every five minutes

**Chosen Sep 1, when the frozen-instance bug was found.**

The served page and `mobile.js` each fetched `data/feeds.json` once, at
load, and never again. A browser tab gets reloaded; an installed app
does not — a phone keeps the instance alive in memory for weeks, and on
Sep 1 the owner's tabs (Alerts, NBC player news, Week review) were all
showing mid-August wire while the server, measured the same minute by
the watchdog against the production domain, was serving that
afternoon's. Both fetches now re-run when the document becomes visible
again (`visibilitychange`, plus `focus` for desktop window switches).

**The chosen number: five minutes** between re-pulls. Zero would re-fetch
on every app switch — a reader flipping between the app and a group chat
during games would hammer the endpoint for data that syncs every ~15
minutes anyway. An hour would leave a Sunday-afternoon reader a quarter
behind. Five minutes is well under the sync cadence, so a woken app is
never staler than the store plus five.

**What it deliberately does not do:** a failed re-pull keeps what is on
screen, silently — same contract as the startup fetch, and the dated
kickers (`page.dated_kickers_read_the_data`) are the surface that says
how old that state really is. And nothing polls in the background: the
re-pull fires on wake, not on a timer, because a hidden app asking every
five minutes is battery spent on rows nobody is looking at.

**If it is wrong:** the constant sits in two places on purpose —
`_FEEDS_FETCH_REPLACEMENT` in `app/feeds/page.py` (300000 ms) and
`wakeFeeds` in `frontend/mobile.js` (5 × 60 × 1000) — one per puller,
each beside the fetch it throttles. Change both or the two halves of the
overlay age apart.


## The game stack, the weekly stars and the Predictions clauses (Sep 3–5)

**The weekly blob carries a vocabulary stamp** (`projections.WEEK_REDUCE_VERSION`,
Sep 5). Found live an hour after the merge: the stored weekly forecast
had been reduced by the previous code, which kept the three TD fields
only, and its 24-hour budget had not run out — so the game stack ranked
the slate by touchdowns under a "projected fantasy points" heading
(Burrow 14.1 in every league, Ja'Marr Chase 4.4). A dict of numbers
cannot say which cut it is, so the reduce stamps its version, a blob
without the current stamp is stale whatever its age, and the ranking
surfaces (`gamestack.build`, `weekly_stars`, `projected_top_by_team`)
return nothing for an unstamped blob rather than score it. The TD-lean
forecast clause keeps reading the old cut, because touchdowns are all it
needs. Same mechanism as the player index's `INDEX_VERSION`.


**Chosen Sep 3–5, owner asks:** rank the slate by expected fantasy
points, a weekly stars list to drive who to play, an IDP tracker that
leads with tackles, and Predictions rows that read the wire, the line
and who is out. All of it is arithmetic over feeds already stored
(`app/feeds/gamestack.py`, `app/feeds/idpweek.py`); these are the
numbers that had to be picked rather than measured.

- **The ranking league is the visitor's first league** (the owner's
  NDDPL by default). Every league's figure ships in the payload and the
  chips re-sort client-side, so this decides only what leads on first
  paint — league scoring stays a column, not a hidden sort key.
- **`TOP_N = 6` projected scorers per game row.** Two skill lineups'
  worth of headline players: enough to see who carries a total, few
  enough to read on a phone.
- **A wire item is an "alert" for 7 days** (`WIRE_WINDOW`, and
  `injury.LEAN_WIRE_WINDOW`). Older is history, and history beside a
  lean reads as news.
- **A game total is QB/RB/WR/TE only.** Kickers and team defenses have
  no weekly line in the store, and are not what "best game for fantasy
  points" means. Return yards are not in the forecast either (see the
  projections entry above) — return specialists read a little low.
- **Projected team TDs = rushing + receiving.** A passing TD and the
  receiving TD it throws are one score; adding `pass_td` would count each
  twice.
- **WSH ↔ WAS.** ESPN's slate names Washington WSH, Sleeper's index (and
  every projection row, which joins by Sleeper id) says WAS — the one
  divergence between the two vocabularies, mapped in
  `gamestack.SLATE_TO_INDEX`. `vegas.implied_by_team` already refused to
  guess across it; without the map the Commanders were a game with nobody
  in it. If ESPN or Sleeper renames another club, that map is the place.
- **"Since open" is the oldest snapshot the store still holds** — 96
  pushes at ~4 an hour, about a day (`MAX_LINE_SNAPSHOTS`), not the
  book's true opener. A week-old opener is a different market, and the
  Data health row would then be describing a number nobody can bet.
- **The weather read is a rule, labelled "(rule)" wherever it renders**,
  in the owner's own words: snow → fewer points and a run-leaning script;
  rain/storms → passing volume falls, lean run and the short game; wind →
  deep passing and kicking get harder; anything else on a forecast →
  "fair: no weather penalty". Keyed on ESPN's forecast text
  (`gamestack._WEATHER_RULES`). **Absent forecast means absent line** — a
  dome game is never read as "fair" by default. Whether ESPN's scoreboard
  actually carries a forecast is measured every sync
  (`scripts/push_vegas.py` prints the census; the probe's plain urllib
  client gets a 403 from ESPN's edge that the app's httpx fetch does
  not).
- **The IDP tracker orders by projected tackles (solo + assisted), points
  beside.** Tackles are the volume that decides an IDP week and what the
  owner said they read; a sack-heavy league still shows its own points
  column, so the two orderings can disagree in the open.
- **The next man's number is Rotowire's own line for him**, never a
  redistributed share of the starter's. A multiplier would be this app's
  invention wearing the forecaster's name; the vacancy is the starter's
  measured '25 work, as `/app/nextup` reports it.
- **Sleeper's `depth_chart_order` leads the depth chart, measured '25
  opportunity breaks ties and orders anyone unslotted.** Verified live
  Sep 5 (probe run 31: on 12,194 of 12,226 players). The new index
  fields arrive with the next index refresh (≤20h); `INDEX_VERSION` was
  deliberately not bumped, because a bump empties every board until the
  next sync (the Aug 22 incident) and the ordering falls back cleanly
  without them.

**If any of it is wrong:** every constant is named above and lives beside
the code it governs; the watchdog prints the counts (games ranked, with
scorers, uncovered; movement and weather coverage; clauses per lean) so
a wrong number shows up as a wrong count in the log, not as silence.
