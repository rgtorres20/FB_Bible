"""How much a stat swings from game to game, measured from real box scores.

Owner, Sep 24: "i want to also know the confidence percent on over under".
A projection is a mean -- "Hill, 6.5 catches" -- and a chance of clearing a
line needs the spread around it too. Rotowire publishes no spread, so this
measures one: last season's weekly box scores from Sleeper (the same
endpoint the scorecard settles against), per player, per stat.

The number kept is the **coefficient of variation** -- a player's
game-to-game standard deviation divided by his average -- pooled as the
median across every player at a position with a real role (enough games,
enough volume). A ratio rather than a raw spread because it travels: a
receiver projected for 90 yards and one projected for 40 swing by
different amounts, but by a similar fraction of what they average. The
panel then reads P(over) from a normal curve centred on the projection
with that spread. The model and every threshold are in
docs/ASSUMPTIONS.md.

Built a few weeks per sync, never all at once: eighteen weekly dumps of
1-2MB each would not fit one serverless call, and a finished season never
changes, so once every week is in the table is final.
"""

from __future__ import annotations

import statistics

SEASON = 2025
WEEKS = tuple(range(1, 19))  # the '25 regular season
WEEKS_PER_SYNC = 3
VERSION = 1

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


def blank() -> dict:
    return {"v": VERSION, "season": SEASON, "weeks_done": [], "players": {}}


def _current(state: dict | None) -> dict:
    if not state or state.get("v") != VERSION or state.get("season") != SEASON:
        return blank()
    return state


def pending_weeks(state: dict | None, limit: int = WEEKS_PER_SYNC) -> list[int]:
    """The next weeks still to fold in, at most `limit` of them."""
    done = set(_current(state).get("weeks_done") or [])
    return [w for w in WEEKS if w not in done][:limit]


def complete(state: dict | None) -> bool:
    return not pending_weeks(state)


def accumulate(state: dict | None, week: int, box: dict | None, index: dict | None) -> dict:
    """Fold one week's box scores in. A player counts for a week only if
    he played in it (`gp`), so a bye or an injury is not a zero game."""
    state = dict(_current(state))
    players = {pid: dict(row) for pid, row in (state.get("players") or {}).items()}
    positions = {
        pid: (p.get("position") or "").upper()
        for pid, p in ((index or {}).get("players") or {}).items()
    }
    for pid, line in (box or {}).items():
        if not isinstance(line, dict) or not line.get("gp"):
            continue
        pos = positions.get(str(pid), "")
        if not any(pos in by_pos for by_pos in MARKETS.values()):
            continue
        row = players.setdefault(str(pid), {"pos": pos})
        for stat, by_pos in MARKETS.items():
            if pos not in by_pos:
                continue
            value = float(line.get(stat) or 0)
            n, s, ss = row.get(stat) or (0, 0.0, 0.0)
            row[stat] = (n + 1, s + value, ss + value * value)
        players[str(pid)] = row
    state["players"] = players
    state["weeks_done"] = sorted(set(state.get("weeks_done") or []) | {week})
    return state


def table(state: dict | None) -> dict | None:
    """{stat: {position: {"cv": ..., "players": n}}} once every week is in,
    else None -- a spread measured from half a season is not the one the
    label will claim."""
    state = _current(state)
    if not complete(state):
        return None
    out: dict[str, dict[str, dict]] = {}
    for stat, by_pos in MARKETS.items():
        for pos, min_mean in by_pos.items():
            cvs = []
            for row in (state.get("players") or {}).values():
                if row.get("pos") != pos or not row.get(stat):
                    continue
                n, s, ss = row[stat]
                if n < MIN_GAMES:
                    continue
                mean = s / n
                if mean < min_mean:
                    continue
                var = max(ss / n - mean * mean, 0.0) * n / (n - 1)
                cvs.append(var**0.5 / mean)
            if len(cvs) >= MIN_PLAYERS:
                out.setdefault(stat, {})[pos] = {
                    "cv": round(statistics.median(cvs), 3),
                    "players": len(cvs),
                }
    return {"season": SEASON, "markets": out} if out else None
