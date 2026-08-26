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
    assert allen["NDDPL"]["p"] == pytest.approx(round(474.0 / 17, 1))
    assert allen["RED_EYE"]["p"] == pytest.approx(round(874.0 / 17, 1))
    assert allen["RED_EYE"]["p"] > allen["NDDPL"]["p"] * 1.8
    # The season total rides along (owner ask, Aug 25) -- same scoring
    # pass, and it was being computed and discarded before.
    assert allen["NDDPL"]["t"] == 474
    assert allen["RED_EYE"]["t"] == 874


def test_halved_receiving_shows_up_where_it_is_not_halved():
    nacua = _table()["Puka Nacua"]
    assert nacua["NDDPL"] == nacua["RED_EYE"]
    assert nacua["BALLAPALOSA"]["p"] > nacua["NDDPL"]["p"]
    assert nacua["BALLAPALOSA"]["t"] > nacua["NDDPL"]["t"]


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
    wrong claim. The rename rides WITH the injection since Aug 22: as a
    standalone PRE transform it fired even when the injection no-opped,
    which put "'25 P/G" over the fabricated slope during an outage."""
    out, n = board.inject_league_points(INDEX_HTML, _index(), _stats(), leagues_mod.defaults())
    assert n == 2
    assert "<div>Blend</div><div>'25 P/G \u00b7 total</div>" in out
    assert "<div>Proj</div>" not in out.split("Latest read")[0]
    # Still not claiming a forecast. The owner asked for "total projected
    # points"; what exists is last season's real line under this league's
    # real values, and the header keeps saying which.
    assert "'25" in out.split("Latest read")[0]
    assert "Proj" not in out.split("Latest read")[0]


def test_no_injection_keeps_the_proj_header_too():
    """The other half of both-or-neither: with no stats the fabricated
    slope survives, so the header must keep calling it a projection."""
    out, n = board.inject_league_points(INDEX_HTML, _index(), None, leagues_mod.defaults())
    assert n == 0
    assert "<div>Blend</div><div>Proj</div>" in out
    assert "'25 P/G" not in out


# --- the season total beside it (owner ask, Aug 25) -------------------------


def test_the_total_is_the_season_not_a_forecast():
    """The ask was "total projected points". '26 projections do not exist
    in this app, and inventing them is the line it does not cross. What it
    has is last season's real line under this league's real values -- so
    the number is a measured total and the header says '25."""
    allen = _table()["Josh Allen"]

    assert allen["NDDPL"]["t"] == 474
    # And it is the per-game figure's own arithmetic, not a second source
    # that could disagree with it.
    assert allen["NDDPL"]["t"] == pytest.approx(allen["NDDPL"]["p"] * 17, rel=0.01)


def test_the_board_renders_both_figures():
    out, _ = board.inject_league_points(INDEX_HTML, _index(), _stats(), leagues_mod.defaults())

    assert "const totalFor" in out
    assert "projTotal: totalFor(b)" in out
    assert "{{ b.projTotal }} total" in out


def test_a_league_that_cannot_start_him_gets_no_total_either():
    """The dash rule covers both numbers. A season total of 0 for a player
    the league cannot start is the same lie as a per-game 0."""
    garrett = _table()["Myles Garrett"]

    assert set(garrett) == {"RED_EYE"}
    assert "t" in garrett["RED_EYE"] and "p" in garrett["RED_EYE"]


def test_both_readers_fall_back_to_a_dash_not_a_zero():
    """The page-side halves. `String(v.t)` on a missing entry would print
    "undefined"; both readers check the type first."""
    out, _ = board.inject_league_points(INDEX_HTML, _index(), _stats(), leagues_mod.defaults())

    start = out.index("const FBPts")
    readers = out[start : out.index("const boardOrdered", start)]
    # The JS source carries the escape sequence, not the character.
    assert readers.count(r"\u2014") == 2, "both readers need the dash"
    assert 'typeof v.p === "number"' in readers
    assert 'typeof v.t === "number"' in readers


def test_a_missing_cell_anchor_changes_nothing():
    """All-or-nothing, as before: a header renamed to promise a total
    beside a cell that never got one is worse than leaving both."""
    broken = INDEX_HTML.replace(
        '<div style="font-size:10px; color:var(--color-neutral-600);">PPG</div>', "<div>x</div>", 1
    )

    out, n = board.inject_league_points(broken, _index(), _stats(), leagues_mod.defaults())

    assert n == 0
    assert out == broken


# --- reading forward: '26 projections ------------------------------------
#
# Owner, Aug 25: "i want to add total projected poitns to draft analzer
# beside PPG", then "yes lets add real projections". The column was last
# season's measured line, which is honest but backwards for a draft. It
# now reads Rotowire's '26 forecast (via Sleeper, probed live before a
# line of app/feeds/projections.py was written) through the same league
# scoring, and falls back to '25 when there is none.


def _proj() -> dict:
    """The reduced shape the sync stores: same stat vocabulary as the
    measured lines, which is what lets one scorer read both."""
    return {
        "players": {
            # A deliberately bigger season than his '25 line, so a test
            # can tell the two sources apart by the number alone.
            "1": {
                "gp": 17,
                "pass_cmp": 430,
                "pass_yd": 5000,
                "pass_td": 40,
                "pass_int": 9,
                "rush_yd": 350,
                "rush_td": 5,
                "fum_lost": 2,
            },
        },
        "companies": ["rotowire"],
    }


def test_the_column_reads_the_projection_when_there_is_one():
    """Not last season. A draft is about the season ahead."""
    measured = board.league_points(_index(), _stats(), leagues_mod.defaults())
    projected = board.league_points(_index(), _stats(), leagues_mod.defaults(), _proj())

    assert projected["Josh Allen"]["NDDPL"]["t"] > measured["Josh Allen"]["NDDPL"]["t"]


def test_the_projection_is_still_scored_by_each_league():
    """The point of routing it through the same scorer: RED_EYE's point
    per completion is worth 430 points to a 430-completion forecast, the
    same way it is worth 400 to a 400-completion season."""
    allen = board.league_points(_index(), _stats(), leagues_mod.defaults(), _proj())["Josh Allen"]

    assert allen["RED_EYE"]["t"] - allen["NDDPL"]["t"] == 430


def test_the_header_says_which_season_it_is_reading():
    """The label is not decoration — it is the difference between what a
    player did and what somebody thinks he will do. `_points_source`
    returns the numbers and the header together so a page can never show
    one under the other's name."""
    with_proj, _ = board.inject_league_points(
        INDEX_HTML, _index(), _stats(), leagues_mod.defaults(), _proj()
    )
    without, _ = board.inject_league_points(INDEX_HTML, _index(), _stats(), leagues_mod.defaults())

    # The exact header cell, not a fragment: Team intel's win projections
    # already say "'26 proj" in unrelated prose, so a bare substring test
    # passes on the wrong text. (The same trap cost a live watchdog check
    # on Aug 25 — see docs/GAP_REVIEW.md.)
    projected = "<div>Blend</div><div>'26 proj \u00b7 Rotowire</div>"
    measured = "<div>Blend</div><div>'25 P/G \u00b7 total</div>"

    assert projected in with_proj and measured not in with_proj
    assert measured in without and projected not in without


def test_the_forecaster_is_credited_on_the_column():
    """Rotowire's numbers, said so — and read off the payload rather than
    typed, so the credit follows the data the day Sleeper switches
    provider instead of quietly crediting the wrong house."""
    served, _ = board.inject_league_points(
        INDEX_HTML, _index(), _stats(), leagues_mod.defaults(), _proj()
    )
    swapped, _ = board.inject_league_points(
        INDEX_HTML,
        _index(),
        _stats(),
        leagues_mod.defaults(),
        {**_proj(), "companies": ["someone else"]},
    )

    assert "<div>Blend</div><div>'26 proj \u00b7 Rotowire</div>" in served
    assert "<div>Blend</div><div>'26 proj \u00b7 Someone Else</div>" in swapped


def test_an_empty_projection_state_falls_back_rather_than_emptying_the_column():
    """A fetch that failed must not blank the board. Yesterday's measured
    line under a '25 header beats no column at all."""
    for empty in ({}, None, {"players": {}}):
        served, n = board.inject_league_points(
            INDEX_HTML, _index(), _stats(), leagues_mod.defaults(), empty
        )
        assert n, empty
        assert "'25 P/G" in served, empty
