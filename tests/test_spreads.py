"""Game-to-game spreads, measured (owner, Sep 24: "i want to also know the
confidence percent on over under").

The percentage on an over/under needs a spread around the projection, and
Rotowire publishes none, so the app measures one from last season's real
box scores. These tests pin how it is measured -- games he did not play
are not zeros, a role needs volume, a thin pool claims nothing -- and that
nothing is claimed until the whole season is in.
"""

from __future__ import annotations

import statistics

from app.feeds import spreads


def _index(n_wr=12):
    players = {str(i): {"position": "WR"} for i in range(n_wr)}
    players["qb"] = {"position": "QB"}
    players["k"] = {"position": "K"}
    return {"players": players}


def _box(week, n_wr=12):
    """Receiver i catches 4 + (week % 3) passes for 60 + 10 * (week % 3)
    yards, and every receiver sits out Week 5."""
    if week == 5:
        return {str(i): {"gp": 0} for i in range(n_wr)}
    box = {
        str(i): {"gp": 1, "rec": 4 + week % 3, "rec_yd": 60 + 10 * (week % 3)} for i in range(n_wr)
    }
    box["k"] = {"gp": 1, "rec": 9}  # a kicker is not a market
    return box


def _season(n_wr=12):
    state = None
    for week in spreads.WEEKS:
        state = spreads.accumulate(state, week, _box(week, n_wr), _index(n_wr))
    return state


def test_weeks_are_folded_in_a_few_at_a_time_until_the_season_is_in():
    assert spreads.pending_weeks(None) == [1, 2, 3]
    state = spreads.accumulate(None, 1, _box(1), _index())
    assert spreads.pending_weeks(state) == [2, 3, 4]
    assert not spreads.complete(state)
    assert spreads.table(state) is None  # half a season claims nothing
    assert spreads.complete(_season())


def test_the_spread_is_the_median_coefficient_of_variation():
    table = spreads.table(_season())
    cell = table["markets"]["rec"]["WR"]
    # The measured games: every week but 5, catches 4/5/6 by week % 3.
    games = [4 + w % 3 for w in spreads.WEEKS if w != 5]
    assert cell["cv"] == round(statistics.stdev(games) / statistics.mean(games), 3)
    assert cell["players"] == 12
    assert table["season"] == spreads.SEASON


def test_a_game_he_did_not_play_is_not_a_zero():
    row = _season()["players"]["0"]
    n, total, _ = row["rec"]
    assert n == 17  # 18 weeks, Week 5 not played
    assert total == sum(4 + w % 3 for w in spreads.WEEKS if w != 5)


def test_a_thin_pool_or_a_non_role_claims_no_spread():
    table = spreads.table(_season(n_wr=spreads.MIN_PLAYERS - 1))
    assert table is None  # nine receivers is not a measurement
    table = spreads.table(_season())
    assert "rush_yd" not in table["markets"]  # nobody here has a rushing role
    assert "k" not in _season()["players"]


def test_a_stale_version_starts_over():
    old = {**_season(), "v": spreads.VERSION - 1}
    assert spreads.pending_weeks(old) == [1, 2, 3]
