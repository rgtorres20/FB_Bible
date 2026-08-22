"""The board the owner drafts from, answering to the owner's scoring.

Owner, Aug 22: *"how does my leagues scores influence rankings"* — and
the honest answer was that on the main draft board it did not. That board
orders by ADP and the blended rank lists; the leagues reached it only
through which ADP column it read and how deep it went. Neither is scoring.

Worse, its one numeric column was `projFor`, a fabricated linear slope —
a per-position base minus a constant times the position rank, with no
data behind it and no league in it, under a header reading "Proj". The
comment directly above it claimed both leagues pay quarterbacks above
market, which the formula had no way of knowing.

It now carries last season's points per game under whichever league is
selected on that screen. Same arithmetic as `/app/scoring`, same honesty
rules: a league that cannot start a player gets no number, and a player
the stats do not cover gets a dash rather than an invention.
"""

from __future__ import annotations

import json
import re

import pytest

from app import leagues as leagues_mod
from app.feeds import board, page

NDDPL, RED_EYE, BALLAPALOSA = leagues_mod.defaults()
INDEX_HTML = open("frontend/index.html", encoding="utf-8").read()


def _index() -> dict:
    return {
        "players": {
            "1": {
                "id": "1",
                "name": "Josh Allen",
                "position": "QB",
                "team": "BUF",
                "injury_status": None,
                "rank": 20,
            },
            "2": {
                "id": "2",
                "name": "Myles Garrett",
                "position": "DE",
                "team": "CLE",
                "injury_status": None,
                "rank": 350,
                "idp": "DL",
            },
            "3": {
                "id": "3",
                "name": "Puka Nacua",
                "position": "WR",
                "team": "LAR",
                "injury_status": None,
                "rank": 5,
            },
        }
    }


def _stats() -> dict:
    return {
        "players": {
            # 4600 pass yds, 36 TD, 400 completions, 10 INT, 300 rush, 4 rush TD.
            "1": {
                "gp": 17,
                "pass_cmp": 400,
                "pass_yd": 4600,
                "pass_td": 36,
                "pass_int": 10,
                "rush_yd": 300,
                "rush_td": 4,
                "fum_lost": 3,
            },
            "2": {"gp": 17, "idp_tkl_solo": 40, "idp_sack": 14},
            "3": {"gp": 17, "rec": 110, "rec_yd": 1500, "rec_td": 10, "fum_lost": 1},
        }
    }


def _table():
    return board.league_points(_index(), _stats(), leagues_mod.defaults())


# --- the number is the league's own arithmetic --------------------------


def test_the_same_player_reads_differently_in_each_league():
    """The whole point. A quarterback totalling 474 in NDDPL and 874 in
    RED_EYE must not occupy the same square on the board."""
    allen = _table()["Josh Allen"]
    assert allen["NDDPL"] == pytest.approx(round(474.0 / 17, 1))
    assert allen["RED_EYE"] == pytest.approx(round(874.0 / 17, 1))
    assert allen["RED_EYE"] > allen["NDDPL"] * 1.8


def test_halved_receiving_shows_up_where_it_is_not_halved():
    nacua = _table()["Puka Nacua"]
    assert nacua["NDDPL"] == nacua["RED_EYE"]
    assert nacua["BALLAPALOSA"] > nacua["NDDPL"]


def test_a_league_that_cannot_start_him_gets_no_number_at_all():
    """NDDPL has no DL slot and BALLAPALOSA starts no defenders. A zero
    there would be arithmetically fine and practically a lie."""
    garrett = _table()["Myles Garrett"]
    assert set(garrett) == {"RED_EYE"}


def test_a_player_the_stats_do_not_cover_is_absent_rather_than_invented():
    """The reason this replaces a formula rather than tuning one: the
    formula always had an answer."""
    index = _index()
    index["players"]["9"] = {
        "id": "9",
        "name": "Some Rookie",
        "position": "WR",
        "team": "NYG",
        "injury_status": None,
        "rank": 400,
    }
    assert "Some Rookie" not in board.league_points(index, _stats(), leagues_mod.defaults())


def test_a_player_with_no_games_is_left_out_rather_than_divided_by_zero():
    stats = _stats()
    stats["players"]["1"]["gp"] = 0
    assert "Josh Allen" not in board.league_points(_index(), stats, leagues_mod.defaults())


# --- it reaches the page ------------------------------------------------


def test_the_fabricated_formula_is_gone():
    """`bases = { QB: 24.5, RB: 21.0, ... }` minus a slope. No data behind
    it, no league in it, rendered under a header saying "Proj"."""
    out, n = board.inject_league_points(INDEX_HTML, _index(), _stats(), leagues_mod.defaults())
    # Two of the three fixture players, not three: since Aug 22 the map is
    # re-keyed onto the board's own spelling, so it carries only players
    # the page will actually look up. Myles Garrett is in the index and
    # not on the committed board, so he contributes no key -- which is
    # right, and the old count was measuring the wrong thing.
    assert n == 2
    assert "bases = { QB: 24.5" not in out
    assert "slopes = { QB: 0.85" not in out


def test_the_column_reads_the_league_selected_on_that_screen():
    """The board already had a league picker; the number just never
    listened to it."""
    out, _ = board.inject_league_points(INDEX_HTML, _index(), _stats(), leagues_mod.defaults())
    assert "FB_LEAGUE_PTS[b.name]" in out
    assert "byLeague[s.draftLeague]" in out


def test_the_injected_table_is_keyed_by_the_names_the_page_uses():
    """`s.draftLeague` holds the name on the button, which the serve-time
    rename turns into NDDPL / RED_EYE. Key by anything else and every
    lookup silently misses and every row shows a dash."""
    out, _ = board.inject_league_points(INDEX_HTML, _index(), _stats(), leagues_mod.defaults())
    table = json.loads(re.search(r"const FB_LEAGUE_PTS = (\{.*?\});\n", out, re.S).group(1))
    renamed, misses = page.league_names(out)
    assert not misses
    for league_key in ("NDDPL", "RED_EYE"):
        assert any(league_key in v for v in table.values())
        assert f'"{league_key}"' in renamed or f"'{league_key}'" in renamed


def test_an_unknown_player_renders_a_dash_not_a_zero():
    out, _ = board.inject_league_points(INDEX_HTML, _index(), _stats(), leagues_mod.defaults())
    assert "\\u2014" in out, "the fallback is an em dash"


def test_both_edits_land_or_neither_does():
    """A map injected beside a surviving formula would keep rendering the
    invented number, which is the worst of both."""
    without_formula = INDEX_HTML.replace("const bases = { QB: 24.5", "const bases = { QB: 99.0")
    out, n = board.inject_league_points(without_formula, _index(), _stats(), leagues_mod.defaults())
    assert n == 0
    assert "FB_LEAGUE_PTS" not in out


def test_no_stats_means_no_injection_rather_than_an_empty_table():
    out, n = board.inject_league_points(INDEX_HTML, _index(), None, leagues_mod.defaults())
    assert n == 0
    assert "bases = { QB: 24.5" in out, "the page is left exactly as it was"


def test_the_header_stops_claiming_a_projection():
    """It is last season's measurement, not a forecast. Renaming the
    column is half the fix — a real number under a wrong label is still a
    wrong claim."""
    renamed, misses = page.board_points_label(INDEX_HTML)
    assert not misses
    assert "<div>Blend</div><div>'25 P/G</div>" in renamed
    assert "<div>Proj</div>" not in renamed.split("Latest read")[0]
