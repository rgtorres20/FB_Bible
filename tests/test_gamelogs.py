"""Game logs: every skill player's real games, this season and last
(owner, Sep 24: "yes" to the stats behind each pick).

The row shape mirrors Sleeper's per-week stats rows as probed live on
2026-09-24 (probe runs 38-40): `player_id`, `team`, `opponent`, `date`,
`player.position`, and a `stats` object in which `gp` marks a game played.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.feeds import gamelogs

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def row(pid, pos, team, opp, played="2026-09-13", **stats):
    return {
        "player_id": pid,
        "team": team,
        "opponent": opp,
        "date": played,
        "player": {"position": pos},
        "stats": {"gms_active": 1, **stats},
    }


def _week1():
    return [
        row("hill", "WR", "MIA", "BUF", gp=1, rec=6, rec_yd=90, rec_tgt=9, rec_td=1),
        row("waddle", "WR", "MIA", "BUF", gp=1, rec=4, rec_yd=40),
        row("allen", "QB", "BUF", "MIA", gp=1, pass_yd=280, pass_td=2, rush_yd=30, rush_td=1),
        row("benchwr", "WR", "MIA", "BUF"),  # active, did not play: no gp
        row("kicker", "K", "BUF", "MIA", gp=1),  # not a market position
    ]


def _week2():
    return [
        row("hill", "WR", "MIA", "NE", played="2026-09-20", gp=1, rec=8, rec_yd=110),
        row("lamb", "WR", "DAL", "BUF", played="2026-09-20", gp=1, rec=9, rec_yd=120, rec_td=2),
    ]


def _logs():
    logs = gamelogs.fold(None, 2026, 1, _week1(), NOW)
    return gamelogs.fold(logs, 2026, 2, _week2(), NOW)


def test_this_seasons_played_weeks_come_first_then_last_season():
    assert gamelogs.pending(None, slate_week=3) == [(2026, 1), (2026, 2), (2025, 1)]
    assert gamelogs.pending(_logs(), slate_week=3)[:2] == [(2025, 1), (2025, 2)]


def test_a_week_is_final_only_two_days_after_its_last_game():
    fresh = gamelogs.fold(None, 2026, 3, [row("x", "WR", "A", "B", played="2026-09-23", gp=1)], NOW)
    assert fresh["weeks"]["2026-3"] == "partial"  # a day old: corrections may come
    assert _logs()["weeks"] == {"2026-1": "final", "2026-2": "final"}
    assert gamelogs.fold(None, 2025, 1, [], NOW)["weeks"]["2025-1"] == "partial"


def test_only_games_played_by_skill_players_are_kept():
    players = _logs()["players"]
    assert set(players) == {"hill", "waddle", "allen", "lamb"}


def test_a_refetch_replaces_the_week_rather_than_counting_it_twice():
    logs = gamelogs.fold(_logs(), 2026, 1, _week1(), NOW)
    assert len(gamelogs.season_games(logs, "hill", 2026)) == 2
    corrected = [row("hill", "WR", "MIA", "BUF", gp=1, rec=7, rec_yd=95)]
    logs = gamelogs.fold(logs, 2026, 1, corrected, NOW)
    assert gamelogs.season_games(logs, "hill", 2026)[0]["rec"] == 7


def test_the_player_log_carries_each_game_and_its_touchdowns():
    log = gamelogs.player_log(_logs(), "hill")
    assert log == {
        "26": [
            {"w": 1, "o": "BUF", "rec": 6, "rec_yd": 90, "td": 1},
            {"w": 2, "o": "NE", "rec": 8, "rec_yd": 110},
        ]
    }
    allen = gamelogs.player_log(_logs(), "allen")["26"][0]
    assert allen == {"w": 1, "o": "MIA", "pass_yd": 280, "rush_yd": 30, "td": 1}


def test_what_a_defense_allowed_is_per_game_and_ranked():
    table = gamelogs.allowed(_logs())
    buf = table["BUF"]
    # BUF faced MIA (Wk 1: Hill 6/90/1 TD, Waddle 4/40) and DAL (Wk 2: Lamb 9/120/2).
    assert buf["games"] == 2
    # [per game, from the most, from the fewest, how many share it, out of]
    assert buf["WR"]["rec"] == [9.5, 1, 2, 1, 2]  # 19 catches over 2 games, the most
    assert buf["WR"]["td"] == [1.5, 1, 2, 1, 2]
    assert table["NE"]["WR"]["rec"] == [8.0, 2, 1, 1, 2]
    # Only MIA faced a quarterback, so it is ranked among one, not three.
    assert table["MIA"]["QB"]["pass_yd"] == [280.0, 1, 1, 1, 1]


def test_a_tie_is_reported_as_a_tie_not_an_order():
    rows = [
        row("a", "WR", "X", "D1", gp=1, rec=5),
        row("b", "WR", "X", "D2", gp=1, rec=5),
        row("c", "WR", "X", "D3", gp=1, rec=2),
    ]
    table = gamelogs.allowed(gamelogs.fold(None, 2026, 1, rows, NOW))
    assert table["D1"]["WR"]["rec"] == [5.0, 1, 2, 2, 3]
    assert table["D2"]["WR"]["rec"] == [5.0, 1, 2, 2, 3]
    assert table["D3"]["WR"]["rec"] == [2.0, 3, 1, 1, 3]
