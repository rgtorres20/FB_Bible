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

### Neither of these leagues starts a team defense

Both are IDP — 8 individual defenders each, no `DEF` slot. That is worth
recording because plenty of leagues are the other way round, and the app
now supports both: `/app/leagues` has a `DEF` slot and full D/ST scoring
(docs/LEAGUE_SETTINGS.md), and a league that starts one gets a Team
defenses table on `/app/idp` and drafts one in the mock room. The owner's
two see none of that, correctly.

### Interpretation edge (stated on the IDP board too)

- **Position classification is Sleeper's**, which can disagree with
  Yahoo's for edge rushers: a Sleeper DE that Yahoo lists as LB *is*
  startable in an LB slot despite the board's dash (Micah Parsons is the
  classic case). Definitive eligibility is the player's page inside the
  league; exact per-league eligibility arrives with Yahoo API access.
