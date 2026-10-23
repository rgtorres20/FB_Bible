# NBA props research (Oct 23)

Owner: *"spend next hour researching … what is out there to measure … look at
matchups, strong players vs weak … minutes will matter, more minutes more
points"*.

Method: `scripts/research_nba.py`, run on the Actions runner (ESPN 403s the
sandbox) through `probe.yml` with `mode=research`. The study reads every
current roster player's ESPN game log for **2025-26** (regular season):
**390 players, 23,224 player-games**. Every game is predicted only from the
games before it. Round 3 fits its adjustments on the first half of the
season and tests on the second half, so nothing grades itself.

## What is out there (probed live)

| Source | Result | Use |
|---|---|---|
| ESPN box scores, game logs, injuries | ✅ (already used) | Everything below is measured from these. |
| **ESPN core `propBets` (DraftKings)** | ✅ ~1,140 items per game | The book's own lines: Points, Rebounds, Assists, P+R+A, P+R, P+A, R+A, 3PM, double/triple-double, milestones — with line (`odds.total.value`, e.g. 20.5), opening line, and prices. The athlete is a `$ref` to resolve. |
| ESPN summary `pickcenter` / `predictor` | ✅ | Spread, total, moneyline; ESPN's game projection. The spread is the pregame blowout signal. |
| ESPN team statistics | ✅ | Season team stats (not needed — box scores give more). |
| ESPN fantasy (fba) `kona_player_info` | ✅ | Season projections only (statSource 1); per-game rows are actuals. Not a per-game forecast. |
| Sleeper NBA projections (Rotowire) | ⚠️ shell | 1,776 rows, all `stats: {}`, one `game_id: "season"`. Re-check later; nothing to use today. |
| stats.nba.com | ❌ timeout | Blocks cloud IPs. |
| cdn.nba.com | ❌ 403 | |
| PrizePicks / Underdog APIs | ❌ 403 / 426 | Not open; their terms also forbid scraping. |

## What moves the numbers

**Minutes are the biggest lever** (owner's instinct, confirmed).

- Minutes above his norm explain 31% of the game-to-game swing in points
  (r 0.56), 21% for rebounds, 15% for assists. Each extra minute is worth
  **+0.55 pts, +0.18 reb, +0.11 ast**.
- Played 6+ minutes over his norm → beat his scoring average **80%** of the
  time; 6+ under → **11%**.
- If you knew his minutes, the error on points would fall 5.12 → 4.20. Last
  5 games' minutes alone barely helps (5.08), so minutes must be *forecast*
  from what is known pregame:
  - a 30+ mpg teammate out: **+0.8 min** (two out: **+1.7**); the 15–30 mpg
    players gain **+1.6 min, +1.1 pts** on average;
  - returning from a missed game: **−1.9 min, −0.8 pts**;
  - blowouts: in 20+ point finals, 30+ mpg players lose **4.7 minutes and
    2.6 points**; 15–30 mpg players don't lose. The spread is the pregame
    stand-in (no historical spreads were available to test it directly).

**Matchup matters, about half as much as minutes.**

- Softest 20% of defenses (allowed-to-date vs league): **+1.05 pts**, beat
  average 52.9%. Toughest 20%: **−0.50 pts**, 43.3%.
- **By position is sharper than by team.** Centers vs the defenses softest
  on centers: **+1.19 pts, 53.9%**; vs the toughest: −0.67, 40.4%. Same
  shape for rebounds (C +0.52 / 53.2% vs 42.4%).
- **"Strong player vs weak defense" is not an extra edge.** Stars (20+ ppg)
  beat their average 50.1% vs the softest defenses, role players 53.3% — a
  star's usage is stable; the soft matchup lifts everyone a similar amount.

**Things that do not move it** (don't build them):

- Hot hand: the last-10 average predicts no better than the season average
  (5.13 vs 5.12).
- Home/away: ±0.1.
- Rest by team schedule: back-to-backs +0.3 pts (noise-sized; no penalty).

**The average overstates a typical game.** Players beat their own average
only **47.5%** (pts), 46.8% (reb), 46.1% (ast) of the time — scoring is
right-skewed. An "over his average" read is a slight under by default.

## The combined model (round 3, out of sample)

Forecast minutes = ½ season mpg + ½ last-5 mpg, ± teammate-out, ±
returning; expected stat = per-minute rate × forecast minutes × opponent-
vs-position factor. On the second half of 2025-26 (8,136 games):

| Model vs his average (points) | Games | Beat his average |
|---|---|---|
| +3 or more | 211 | **72.0%** |
| +1.5 to +3 | 981 | 63.9% |
| +0.5 to +1.5 | 1,986 | 55.1% |
| −0.5 to +0.5 | 2,693 | 45.9% |
| −1.5 to −0.5 | 1,539 | 39.3% |
| −3 to −1.5 | 558 | 33.2% |
| −3 or worse | 168 | **28.6%** |

Rebounds: +1.0 or more → 62.7%, −1.0 or worse → 32.8%. Assists: 69.5% / 34.2%.
Minutes forecast error 4.96 vs 5.45 for his plain average.

**Caveat that decides how to show it:** these are beat-*his-average* rates,
not beat-*the-book* rates. DraftKings already prices much of this (injury
news moves lines). No historical prop lines were available, so the honest
way to measure an edge against the book is to **log the line and the model
every day and grade them later** — the scorecard pattern.

## Recommended build (not built yet — owner's call)

1. Per player: a **minutes forecast** with its reasons (teammate out,
   returning, big spread), and the **model number** beside his averages,
   labelled as a model, with the backtested bucket rate it falls in.
2. **Defense vs his position** instead of team-level allowed.
3. **DraftKings line** from ESPN `propBets` on each row, model vs line, and a
   daily ledger graded from box scores so the edge against the book gets
   measured rather than assumed.
4. Say plainly that the average runs a little high (47.5% overs).
