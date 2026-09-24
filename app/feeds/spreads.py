"""How much a stat swings from game to game, measured from real box scores.

Owner, Sep 24: "i want to also know the confidence percent on over under".
A projection is a mean -- "Hill, 6.5 catches" -- and a chance of clearing a
line needs the spread around it too. Rotowire publishes no spread, so this
measures one from last season's game logs (app/feeds/gamelogs.py -- the
same box scores the panel's hit rates count), per player, per stat.

The number kept is the **coefficient of variation** -- a player's
game-to-game standard deviation divided by his average -- pooled as the
median across every player at a position with a real role (enough games,
enough volume). A ratio rather than a raw spread because it travels: a
receiver projected for 90 yards and one projected for 40 swing by
different amounts, but by a similar fraction of what they average. The
panel then reads P(over) from a normal curve centred on the projection
with that spread. The model and every threshold are in
docs/ASSUMPTIONS.md.

Nothing is claimed until every week of that season is final in the logs:
a spread measured from half a season is not the one the label names.
"""

from __future__ import annotations

import statistics

from . import gamelogs

SEASON = gamelogs.LAST

# Which positions each market is measured for, and the average a player
# must clear to count as having the role -- a receiver's 4 rushing yards a
# game is not a rushing role, and its swing would say nothing about a
# back's (docs/ASSUMPTIONS.md).
MARKETS: dict[str, dict[str, float]] = {
    "pass_yd": {"QB": 150.0},
    "rush_yd": {"RB": 30.0, "QB": 20.0},
    "rec_yd": {"WR": 30.0, "TE": 25.0, "RB": 15.0},
    "rec": {"WR": 2.5, "TE": 2.0, "RB": 1.5},
}
MIN_GAMES = 8
MIN_PLAYERS = 10  # fewer qualifying players than this and no spread is claimed


def table(logs: dict | None) -> dict | None:
    """{"season": 2025, "markets": {stat: {position: {"cv", "players"}}}},
    or None until the season is final in the logs."""
    if not gamelogs.season_complete(logs, SEASON):
        return None
    out: dict[str, dict[str, dict]] = {}
    players = (logs or {}).get("players") or {}
    for stat, by_pos in MARKETS.items():
        for pos, min_mean in by_pos.items():
            cvs = []
            for pid, player in players.items():
                if player.get("pos") != pos:
                    continue
                values = [g.get(stat) or 0 for g in gamelogs.season_games(logs, pid, SEASON)]
                if len(values) < MIN_GAMES:
                    continue
                mean = statistics.mean(values)
                if mean < min_mean:
                    continue
                cvs.append(statistics.stdev(values) / mean)
            if len(cvs) >= MIN_PLAYERS:
                out.setdefault(stat, {})[pos] = {
                    "cv": round(statistics.median(cvs), 3),
                    "players": len(cvs),
                }
    return {"season": SEASON, "markets": out} if out else None
