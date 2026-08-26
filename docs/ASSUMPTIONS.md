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

### League points are a *column*, not a sort key

The board still orders by ADP and the blended rank lists. Your scoring now
appears on every row and changes nothing about where the row sits. That
was the deliberate scope — "how do my league's scores influence rankings"
was answered by putting the arithmetic on screen — but if you expected the
board to *re-sort*, it does not.

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

