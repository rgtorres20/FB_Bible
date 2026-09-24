"""Game-to-game spreads, measured (owner, Sep 24: "i want to also know the
confidence percent on over under").

The percentage on an over/under needs a spread around the projection, and
Rotowire publishes none, so the app measures one from last season's game
logs. These tests pin how: a role needs volume, a thin pool claims
nothing, and nothing is claimed until the whole season is final.
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime

from app.feeds import gamelogs, spreads

NOW = datetime(2026, 9, 24, tzinfo=UTC)


def _rows(week, n_wr):
    """Receiver i catches 4 + (week % 3) passes; every receiver sits out
    Week 5 (active, no gp)."""
    out = []
    for i in range(n_wr):
        stats = {"gms_active": 1}
        if week != 5:
            stats.update(gp=1, rec=4 + week % 3, rec_yd=60 + 10 * (week % 3))
        out.append(
            {
                "player_id": str(i),
                "team": "AAA",
                "opponent": "BBB",
                "date": f"2025-10-{week:02d}",
                "player": {"position": "WR"},
                "stats": stats,
            }
        )
    return out


def _season(n_wr=12, weeks=gamelogs.LAST_WEEKS):
    logs = None
    for week in weeks:
        logs = gamelogs.fold(logs, gamelogs.LAST, week, _rows(week, n_wr), NOW)
    return logs


def test_half_a_season_claims_nothing():
    assert spreads.table(_season(weeks=range(1, 10))) is None
    assert spreads.table(_season()) is not None


def test_the_spread_is_the_median_coefficient_of_variation():
    cell = spreads.table(_season())["markets"]["rec"]["WR"]
    games = [4 + w % 3 for w in gamelogs.LAST_WEEKS if w != 5]  # Week 5 not played
    assert cell["cv"] == round(statistics.stdev(games) / statistics.mean(games), 3)
    assert cell["players"] == 12


def test_a_thin_pool_or_a_non_role_claims_no_spread():
    assert spreads.table(_season(n_wr=spreads.MIN_PLAYERS - 1)) is None
    assert "rush_yd" not in spreads.table(_season())["markets"]
