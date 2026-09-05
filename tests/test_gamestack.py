"""The game stack: the slate ranked by projected fantasy points (owner, Sep 3).

Everything here is a join over feeds the app already stores, so the tests
pin the joins and the honesty rules rather than any number's "rightness":
a game nobody is projected for is uncovered, not zero; a player the
forecast skips has no number; the WSH/WAS split does not empty a game;
and the Predictions clauses put two measured figures side by side without
touching the lean.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app import leagues as leagues_mod
from app.feeds import gamestack

NOW = datetime(2026, 9, 3, 18, 0, tzinfo=UTC)
LEAGUES = leagues_mod.defaults()
NDDPL, RED_EYE = LEAGUES[0].key, LEAGUES[1].key


def _player(pid, name, pos, team, injury=None, rank=10):
    return {
        "id": pid,
        "name": name,
        "position": pos,
        "team": team,
        "injury_status": injury,
        "rank": rank,
    }


def _index():
    return {
        "players": {
            "1": _player("1", "Josh Allen", "QB", "BUF", rank=1),
            "2": _player("2", "James Cook", "RB", "BUF", injury="Out", rank=5),
            "3": _player("3", "Ray Davis", "RB", "BUF", rank=60),
            "4": _player("4", "Tua Tagovailoa", "QB", "MIA", rank=12),
            "5": _player("5", "Tyreek Hill", "WR", "MIA", injury="Questionable", rank=3),
            "6": _player("6", "Jayden Daniels", "QB", "WAS", rank=4),
            "7": _player("7", "Kicker Guy", "K", "BUF", rank=200),
            "8": _player("8", "CeeDee Lamb", "WR", "DAL", rank=2),
        },
        "by_name": {},
    }


def _week():
    return {
        "week": 1,
        "companies": ["rotowire"],
        "updated_ms": 1756000000000,
        "players": {
            "1": {"pass_cmp": 24.0, "pass_yd": 280.0, "pass_td": 2.1, "rush_yd": 30.0, "rush_td": 0.4},
            "2": {"rush_att": 15.0, "rush_yd": 70.0, "rush_td": 0.5, "rec": 2.0, "rec_yd": 15.0},
            "3": {"rush_yd": 40.0, "rush_td": 0.2, "rec": 1.0, "rec_yd": 8.0},
            "4": {"pass_cmp": 22.0, "pass_yd": 250.0, "pass_td": 1.6},
            "5": {"rec": 6.5, "rec_yd": 90.0, "rec_td": 0.6},
            "6": {"pass_cmp": 20.0, "pass_yd": 230.0, "pass_td": 1.4, "rush_yd": 45.0, "rush_td": 0.5},
            "7": {"fgm": 2.0},
            "8": {"rec": 7.0, "rec_yd": 95.0, "rec_td": 0.7},
        },
    }


def _stats():
    # '25 usage: Cook led BUF's backfield, Davis was behind him.
    return {"players": {"2": {"rush_att": 200, "rec_tgt": 40}, "3": {"rush_att": 60, "rec_tgt": 10}}}


def _slate():
    return {
        "games": [
            {
                "game": "MIA @ BUF",
                "fav": "BUF -3.5",
                "total": "48.5",
                "kickoff": "2026-09-13T17:00Z",
                "away_name": "Miami Dolphins",
                "home_name": "Buffalo Bills",
                "tv": "CBS",
            },
            {
                "game": "DAL @ WSH",
                "fav": "WSH -1.5",
                "total": "45.5",
                "kickoff": "2026-09-13T20:25Z",
                "away_name": "Dallas Cowboys",
                "home_name": "Washington Commanders",
                "tv": "FOX",
            },
            {
                "game": "CAR @ ATL",
                "fav": "ATL -6",
                "total": "41.5",
                "kickoff": "2026-09-13T17:00Z",
                "away_name": "Carolina Panthers",
                "home_name": "Atlanta Falcons",
            },
        ]
    }


def _items():
    return [
        {
            "id": "w1",
            "title": "Hill limited in practice with a hip issue",
            "published": "2026-09-02T15:00:00+00:00",
            "source_name": "ESPN NFL",
            "link": "https://espn.com/1",
            "players": [{"id": "5", "name": "Tyreek Hill"}],
        },
        {
            "id": "w2",
            "title": "Allen signs extension",
            "published": "2026-08-01T15:00:00+00:00",  # too old to be an alert
            "source_name": "ESPN NFL",
            "link": "https://espn.com/2",
            "players": [{"id": "1", "name": "Josh Allen"}],
        },
    ]


def _build(**over):
    kwargs = {
        "vegas_state": _slate(),
        "week_proj_state": _week(),
        "index": _index(),
        "stats_state": _stats(),
        "items": _items(),
        "leagues": LEAGUES,
        "now": NOW,
    }
    kwargs.update(over)
    return gamestack.build(**kwargs)


# --- the ranking -----------------------------------------------------------


def test_games_rank_by_projected_points_highest_first():
    stack = _build()
    games = stack["games"]
    assert [g["game"] for g in games] == ["MIA @ BUF", "DAL @ WSH"]
    assert [g["rank"] for g in games] == [1, 2]
    totals = [g["points"][NDDPL]["total"] for g in games]
    assert totals == sorted(totals, reverse=True)
    assert stack["default_league"] == NDDPL


def test_a_game_nobody_is_projected_for_is_uncovered_not_zero():
    stack = _build()
    assert stack["uncovered"] == ["CAR @ ATL"]
    assert all(g["game"] != "CAR @ ATL" for g in stack["games"])


def test_every_league_gets_its_own_figure_and_they_differ():
    """RED_EYE pays a point per completion, so the same quarterback's
    line totals higher there -- the column, not the sort key, changes."""
    game = _build()["games"][0]
    assert set(game["points"]) == {lg.key for lg in LEAGUES}
    assert game["points"][RED_EYE]["total"] > game["points"][NDDPL]["total"]
    assert game["points"][NDDPL]["BUF"] + game["points"][NDDPL]["MIA"] == game["points"][NDDPL]["total"]


def test_washington_joins_across_the_espn_sleeper_split():
    """ESPN's slate says WSH; Sleeper's index says WAS. Without the alias
    the Commanders are a game with nobody in it."""
    game = next(g for g in _build()["games"] if g["game"] == "DAL @ WSH")
    assert game["covered"] == {"DAL": 1, "WSH": 1}
    daniels = next(p for p in game["top"] if p["name"] == "Jayden Daniels")
    assert daniels["team"] == "WSH"  # reported in the slate's own spelling


# --- the top scorers and their alerts ----------------------------------------


def test_top_scorers_are_ordered_capped_and_skill_only():
    game = _build()["games"][0]
    names = [p["name"] for p in game["top"]]
    assert "Kicker Guy" not in names  # no weekly K line in the store, and not a "best game" input
    pts = [p["points"][NDDPL] for p in game["top"]]
    assert pts == sorted(pts, reverse=True)
    assert len(game["top"]) <= gamestack.TOP_N


def test_alerts_ride_on_the_rows_that_have_them():
    game = _build()["games"][0]
    hill = next(p for p in game["top"] if p["name"] == "Tyreek Hill")
    assert hill["injury"] == "Questionable"
    assert hill["wire"]["head"].startswith("Hill limited")
    assert hill["wire"]["link"] == "https://espn.com/1"
    allen = next(p for p in game["top"] if p["name"] == "Josh Allen")
    assert allen["injury"] == ""
    assert allen["wire"] is None  # a month-old story is not an alert


def test_touchdowns_are_not_double_counted():
    """A passing TD and the receiving TD it throws are one score."""
    tds = gamestack.team_tds(
        [
            {"line": {"pass_td": 2.0, "rush_td": 0.4}},
            {"line": {"rec_td": 1.2, "rush_td": 0.6}},
        ]
    )
    assert tds == {"rush_td": 1.0, "rec_td": 1.2, "total": 2.2}


# --- somebody being out ----------------------------------------------------


def test_an_out_starter_names_the_next_man_and_his_own_projection():
    game = _build()["games"][0]
    assert len(game["out"]) == 1
    v = game["out"][0]
    assert v["team"] == "BUF" and v["position"] == "RB"
    assert v["starter"] == "James Cook" and v["injury"] == "Out"
    assert v["vacated"] == 240  # Cook's '25 carries + targets, measured
    assert v["next"] == "Ray Davis"
    assert v["next_points"][NDDPL] == LEAGUES[0].score_offense(_week()["players"]["3"])


def test_the_next_man_without_a_line_gets_no_invented_number():
    week = _week()
    del week["players"]["3"]
    game = _build(week_proj_state=week)["games"][0]
    assert game["out"][0]["next_points"] is None


# --- provenance and the empty cases ------------------------------------------


def test_the_stack_names_its_forecaster_and_week():
    stack = _build()
    assert stack["week"] == 1
    assert stack["source"] == "Rotowire via Sleeper"
    assert "not in the forecast" in stack["note"]


def test_no_forecast_means_no_stack_rather_than_a_slate_of_zeros():
    assert _build(week_proj_state=None) is None
    assert _build(week_proj_state={"players": {}}) is None
    assert _build(vegas_state=None) is None


def test_previews_are_attached_by_matchup_names():
    stack = _build(previews={"Miami Dolphins @ Buffalo Bills": "Market expects a shootout."})
    assert stack["games"][0]["preview"] == "Market expects a shootout."
    assert stack["games"][1]["preview"] == ""


# --- the Predictions clauses -------------------------------------------------


def test_lean_clauses_put_the_line_beside_the_projection_and_name_the_out_man():
    stack = _build()
    outs = gamestack.vacancies(_index(), _stats(), _week(), LEAGUES)
    preds = [
        {"name": "Josh Allen", "meta": "QB · BUF", "prop": "Passing TDs", "lean": "OVER"},
        {"name": "CeeDee Lamb", "meta": "WR · DAL", "prop": "Receiving TDs", "lean": "OVER"},
        {"name": "Nobody Here", "meta": "TE · ATL", "prop": "Receiving TDs", "lean": "UNDER"},
    ]
    clauses = gamestack.lean_clauses(stack, preds, outs)
    allen = clauses["Josh Allen"]
    assert allen.startswith("Vegas implies BUF 26")
    assert "Rotowire via Sleeper projects BUF skill players for 1.1 TDs in Wk 1" in allen
    assert "Out on BUF: James Cook (RB, Out), 240 '25 touches/targets come loose → Ray Davis, projected" in allen
    assert "Vegas implies DAL 22" in clauses["CeeDee Lamb"]
    assert "Nobody Here" not in clauses  # ATL has no projected player: nothing measured, nothing said


def test_lean_clauses_never_touch_the_lean_or_confidence():
    """The clause map is text only; the rows are the caller's."""
    preds = [{"name": "Josh Allen", "meta": "QB · BUF", "lean": "OVER", "conf": 78}]
    gamestack.lean_clauses(_build(), preds)
    assert preds[0] == {"name": "Josh Allen", "meta": "QB · BUF", "lean": "OVER", "conf": 78}
