# The owner's leagues — verified settings

Source: the leagues' own Yahoo **Scoring & Settings** pages, provided by the
owner as PDFs on **Aug 19, 2026**. This file is the ground truth; anything
elsewhere in the repo that disagrees is wrong and should be corrected to
match. (The chat-era league facts — "Sunday Gravy, 12-team" and "The
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
| Teams | **10** |
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
4. **Both leagues are 10-team**, so the 12+10 ADP blend and the page's
   per-league ADP toggle (`adp12` for league 192426) rest on a wrong
   size. Open decision: move to 10-team ADP alone, or keep 12-team as a
   market-depth signal with honest labeling.
5. **Returns score** in both — return-role players carry hidden value no
   standard ADP reflects.
6. Confirmed as already assumed: **no waivers, no FAAB, adds first-come**
   in both leagues.

### Interpretation edges (stated on the IDP board too)

- **RED_EYE's `D` slot** is read as Yahoo's any-defender slot (DL/LB/DB
  all eligible) — Yahoo's standard meaning, but the settings page prints
  only "D". Confirm once on the league's roster page; if narrower, the
  board's RED_EYE ranks need re-slicing.
- **Position classification is Sleeper's**, which can disagree with
  Yahoo's for edge rushers: a Sleeper DE that Yahoo lists as LB *is*
  NDDPL-startable despite the board's dash (Micah Parsons is the classic
  case). Definitive eligibility is the player's page inside the league;
  exact per-league eligibility arrives with Yahoo API access.
