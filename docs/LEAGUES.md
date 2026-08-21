# The owner's leagues — verified settings

Source: the leagues' own Yahoo **Scoring & Settings** pages, provided by the
owner as PDFs on **Aug 19, 2026**, plus later corrections straight from the
owner (which supersede the PDFs — so far one: RED_EYE is **12-team**, said
Aug 20, where the PDF read 10). This file is the ground truth; anything
elsewhere in the repo that disagrees is wrong and should be corrected to
match. Its machine-readable twin is **`app/leagues.py`** — one `League`
dataclass per league, and the single place any surface reads scoring,
roster or size from. Change a number here, change it there, and every
surface (IDP board, mock room, cheat sheet) moves together; a user's own
league is the same dataclass with different numbers. (The chat-era league facts — "Sunday Gravy, 12-team" and "The
Trenches, a rushing league where QBs score nothing for passing" — were both
wrong: the sizes, one name's existence, and the QB rule's *direction*.)

## NDDPL — `nfl.l.192426`

| | |
|---|---|
| Teams | **10** |
| Scoring | Head-to-head, fractional, negative points allowed |
| Draft | Offline draft (results entered afterward) |
| Waivers | **None** — adds are free, first-come |
| Trades | Allowed, no review, deadline Nov 28 2026 |
| Playoffs | 6 teams, weeks 15–17 |
| Roster | QB · WR×4 · RB×3 · TE · K · **DB×4 · LB×4** · BN×8 — **no flex** |

Offense scoring vs Yahoo default:

- Passing: **20 yds/pt** (default 25) · **Pass TD 6** (default 4) · INT −2
- Rushing: 10 yds/pt · TD 6
- Receiving: **1.0 PPR** · **20 yds/pt (default 10 — receiving yardage
  halved)** · TD 6
- Returns: 20 yds/pt · return TD 6 (default 0 — returners score)
- 2-pt conversions 2 · fumbles lost −2

Kickers: FG 3/3/3/4/5 by distance, **misses −5/−4/−3/−3/−3**, PAT 1 / miss −1.

IDP (starts 4 DB + 4 LB): solo 1 · assist 0.5 · **sack 3** · INT 2 ·
FF 2 · FR 2 · TD 6 · safety 2 · PD 1 · block 2 · turnover return 20 yds/pt.

## RED_EYE — `nfl.l.811739`

| | |
|---|---|
| Teams | **12** — owner correction Aug 20 ("Redeye is a 12 man" league), superseding the settings PDF's 10 |
| Scoring | Head-to-head, fractional, negative points allowed |
| Draft | Offline draft |
| Waivers | **None** — adds are free, first-come |
| Trades | **None allowed** |
| Playoffs | 6 teams, weeks 15–17 |
| Roster | QB · WR×3 · RB×2 · TE · **W/R/T flex** · K · **D×4 · DB×4** · BN×8 |
| URL | football.fantasysports.yahoo.com/league/red_eye |

Offense scoring vs Yahoo default:

- Passing: **1 pt per completion (default 0)** · **20 yds/pt** ·
  **Pass TD 6** · INT −2
- Rushing: 10 yds/pt · TD 6
- Receiving: **1.0 PPR** · **20 yds/pt (halved)** · TD 6
- Returns: 20 yds/pt · return TD 6
- 2-pt conversions 2 · fumbles lost −2

Kickers: FG 3/3/3/4/5, misses −3 at every distance, PAT 1 / miss −1.

IDP (starts 4 D + 4 DB): solo 1 · assist 0.5 · sack 2 · **INT 3** ·
FF 2 · FR 2 · TD 6 · safety 2 · PD 1 · block 2 · turnover return 10 yds/pt.

## What this means for the product

1. **QBs are premium in both leagues, not discounted.** 6-pt passing TDs
   and 20 pass yds/pt in both; RED_EYE adds a full point per completion
   (a 25-completion game is +25 before yardage). Market ADP — built on
   4-pt-TD leagues — *underprices* QBs here. The old cheat-sheet advice
   ("draft QBs later") pointed the wrong way and is fixed.
2. **Both leagues start 8 IDP players** (more than half a starting lineup
   with K). The player index deliberately excludes DB/LB today
   (GAP_REVIEW #4) — that exclusion is now a first-order product gap, not
   a footnote: no board, capsule, alert or pickup surface can see half
   the roster.
3. **Receiving yardage is halved in both** (20 yds/pt) while receptions
   stay a full point — target-hog possession receivers gain relative to
   deep threats.
4. **NDDPL is 10-team; RED_EYE is 12-team** (owner correction Aug 20,
   superseding the PDF's 10 — the sizes note below). So both FFC ADP
   size columns are load-bearing: 10-team for NDDPL, 12-team for
   RED_EYE. The cheat sheet says which column belongs to which league
   and the mock room drafts each league at its own size. Leftover: the
   page's own `adp12` toggle is wired to league 192426 (NDDPL) — it
   should be 811739's; design-project logic, recorded so it isn't
   relearned.
5. **Returns score** in both — return-role players carry hidden value no
   standard ADP reflects.
6. Confirmed as already assumed: **no waivers, no FAAB, adds first-come**
   in both leagues.

### Owner's IDP read (Aug 20) — how the slots are actually played

Straight from the owner, superseding the earlier D-slot open question:

- **RED_EYE's D slots go to LBs in practice**; DBs fill the DB slots. So
  both leagues draft to the same shape: **4 LB + 4 DB**.
- **Tackles rule this scoring** — every-down **MIKE linebackers are among
  the best picks**. The '25 point totals on /app/idp agree: solo+assist
  volume dominates them.
- DL is therefore situational in both rooms (no NDDPL slot at all; a
  RED_EYE D slot an elite sack artist would have to out-point a
  tackle-machine LB to claim).

## BALLAPALOSA — ID# 963878

Source: the league's own Yahoo **Scoring & Settings** page, provided by
the owner **Aug 21, 2026**. The third verified league, and the one that
exercises the team-defense path on real numbers.

| | |
|---|---|
| Teams | **10** |
| Scoring | Head-to-head, fractional, negative points allowed |
| Draft | Offline draft |
| Waivers | **None** — no maximum acquisitions, continual rolling list |
| Trades | Allowed, commissioner review, deadline Nov 28 2026 |
| Playoffs | 6 teams, weeks 15–17 |
| Roster | QB · WR×3 · RB×2 · TE · **W/R/T flex** · K · **DEF** · BN×6 · IR×2 |

The two **IR slots are not draft rounds** and are deliberately excluded
from `app/leagues.py` — counting them would run the mock room two rounds
past the real draft.

Offense vs Yahoo default:

- Passing: **1 pt per completion (default 0)** · 25 yds/pt · **Pass TD 6**
  (default 4) · **INT −2** (default −1) · bonus 4 at 400 yards
- Rushing / Receiving: 10 yds/pt each · TD 6 · bonus 4 at 175 yards
- Receptions: **1.0 PPR** (default 0.5) — and **receiving yardage is NOT
  halved here**, unlike NDDPL and RED_EYE
- Return TDs 6 · 2-pt 2 · fumbles lost −2 · offensive fumble return TD 6
- **40+ yard passing / rushing / receiving TDs: 4 each** (default 0)

Kickers: FG 3/3/3/4/5 by distance, PAT 1.

**Defense/Special Teams** (this is the D/ST league):

- Sack 1 · **INT 1** (default 2) · **Fumble recovery 1** (default 2) ·
  TD 6 · Safety 2 · Block kick 2 · **Kickoff and punt return TDs 6**
- **4th-down stops 5** (default 0) — the biggest departure from Yahoo's
  defaults, and worth ~55 points a season to a good defense
- Points allowed: 0→**10** · 1-6→7 · 7-13→4 · 14-20→1 · 21-27→0 ·
  28-34→−1 · **35+→−2** (default −4)
- Yards allowed: 300-399→−1 · 400-499→−2 · 500+→−3 (all default 0)
- Extra point returned 2

**QBs are premium here too** — 25.2 pts/game above market, almost all of
it the point per completion. Unlike the other two, that boost is
**derived and capped**, not tuned: nobody has watched this room draft, so
it gets the same honest estimate a user's own league would.

### Neither NDDPL nor RED_EYE starts a team defense

Both are IDP — 8 individual defenders each, no `DEF` slot. BALLAPALOSA is
the other way round: one `DEF` slot and no individual defenders at all.

**A league uses one or the other, never both** (owner's rule, Aug 21).
`/app/leagues` refuses a roster with both, and all three built-ins obey
the same rule they are held to.

### Interpretation edge (stated on the IDP board too)

- **Position classification is Sleeper's**, which can disagree with
  Yahoo's for edge rushers: a Sleeper DE that Yahoo lists as LB *is*
  startable in an LB slot despite the board's dash (Micah Parsons is the
  classic case). Definitive eligibility is the player's page inside the
  league; exact per-league eligibility arrives with Yahoo API access.

## League-scored offence (Aug 21)

`League.score_offense()` totals an offensive player under a league's own
settings, the way `score_idp` and `score_dst` already did for defenders.
Until this existed the app held every offensive scoring *value* and none
of the stats they multiply — it could not total a single quarterback,
which is the position these leagues differ from market on most.

`stats.PLAYER_FIELDS` gained the eleven inputs it needed (passing yards,
TDs, completions, interceptions, lost fumbles, 2-pt conversions, and
kicker makes) and `STATS_VERSION` went to 5 so the store refetches rather
than waiting a week.

What that makes visible for the first time, on a real quarterback season
(359 cmp / 4306 yd / 28 TD / 6 INT / 531 rush / 12 rush TD) against a
WR1 season (105 / 1450 / 9):

| League | QB | WR1 | Ratio |
| --- | ---: | ---: | ---: |
| NDDPL | 490.4 | 233.5 | 2.1x |
| RED_EYE | 849.4 | 233.5 | **3.6x** |
| BALLAPALOSA | 806.3 | 306.0 | 2.6x |

RED_EYE's completion bonus alone is 359 points — more than that entire
WR1 season. "QBs score above market" has been a rule in CLAUDE.md carried
by a hand-tuned `qb_boost_override`; it is now a computed number, and
that override should be retired against measurement rather than kept as
a fudge factor.

**Two honest limits, both labelled rather than silent:**

- **Kickers score flat** — 3 per made field goal, 1 per extra point.
  Yahoo's distance tiers are a per-league setting this repo has not
  verified, and 3/4/5-by-yardage would be an invented number.
- **BALLAPALOSA reads slightly low.** Its per-game bonuses (4 at 400
  passing yards, 4 at 175 rushing or receiving, 4 for a 40-plus yard TD)
  cannot be derived from season aggregates: one 175-yard game and two
  90-yard games are identical in a total. Weekly lines would settle it.
