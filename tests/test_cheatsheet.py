"""The printable draft cheat sheet.

Three things can go wrong on this page, and only one of them is cosmetic:

  * **The empty branch must stay honest.** With no board in the store the
    sheet has nothing to print, and an empty table would read as "these
    are the players" rather than "the sync has not run". It says which.
  * **The two branches must not drift.** They are two separate returns
    from one function, and they already drifted once: the empty branch
    lost the favicon its full branch carried, which is what moved every
    head into `skin.head()`. Both branches are asserted here for the
    icon, the mark and the way back, so the next divergence fails.
  * **The league caveat is load-bearing, not decoration.** The owner's
    verified Yahoo settings score QBs *above* the market this ADP
    reflects; the sheet's earlier note said the opposite. A reader who
    trusts a reversed note drafts worse than one with no note at all.

Timestamps are Central because the owner is, and a printed sheet carries
no timezone context to correct a wrong one.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.feeds import cheatsheet

# 02:30 UTC is the previous evening in Houston -- a stamp rendered in UTC
# would print the wrong day, not just the wrong hour.
NOW = datetime(2026, 8, 21, 2, 30, tzinfo=UTC)
CENTRAL_STAMP = "Thu Aug 20, 09:30 PM Central"


def _state() -> dict:
    """A board in the shape `adp.blend()` stores it: blended `adp`, the
    per-size columns the two leagues are read off, and the RB gap that
    makes one player a position-adjusted sleeper find."""
    return {
        "date": "2026-08-20",
        "players": [
            {
                "name": "Bijan Robinson",
                "position": "RB",
                "team": "ATL",
                "bye": 5,
                "adp": 1.5,
                "sizes": {"12": 1.2, "10": 1.8},
            },
            {
                "name": "Puka Nacua",
                "position": "WR",
                "team": "LAR",
                "bye": 6,
                "adp": 11.0,
                "sizes": {"12": 10.0, "10": 12.0},
            },
            {
                "name": "Bucky Irving",
                "position": "RB",
                "team": "TB",
                "bye": 9,
                "adp": 13.0,
                "sizes": {"12": 12.0, "10": 14.0},
            },
            {
                "name": "Tyjae Spears",
                "position": "RB",
                "team": "TEN",
                "bye": 10,
                "adp": 60.0,
                "sizes": {"12": 58.0, "10": 62.0},
            },
        ],
    }


def _index() -> dict:
    """Sleeper's search ranks. Tyjae Spears goes 60th while Sleeper ranks
    him 20th -- a 40-spot gap against an RB median of 1, which is what
    earns the star. Puka Nacua is deliberately absent."""
    return {
        "players": {
            "1": {"name": "Bijan Robinson", "rank": 1},
            "2": {"name": "Bucky Irving", "rank": 12},
            "3": {"name": "Tyjae Spears", "rank": 20},
        }
    }


def _empty_page() -> str:
    return cheatsheet.build_html({}, None, NOW)


def _full_page() -> str:
    return cheatsheet.build_html(_state(), _index(), NOW)


BRANCHES = pytest.mark.parametrize("build", [_empty_page, _full_page], ids=["empty", "full"])


# --- the empty branch -------------------------------------------------------


def test_no_board_prints_the_reason_rather_than_an_empty_table():
    page = _empty_page()
    assert "No live ADP board yet" in page
    assert "<table" not in page, "an empty table reads as a board with no players in it"
    assert "★" not in page


def test_no_board_still_stamps_when_it_looked():
    """Without the stamp the page cannot be told from a board that is
    merely slow -- "checked at" is the difference between broken and
    waiting."""
    assert f"Checked {CENTRAL_STAMP}" in _empty_page()


# --- the full branch --------------------------------------------------------


def test_every_board_player_gets_a_row_with_both_league_columns():
    page = _full_page()
    for name in ("Bijan Robinson", "Puka Nacua", "Bucky Irving", "Tyjae Spears"):
        assert name in page
    assert page.count("<tr") == 5  # header row + four players
    # The two columns the leagues are actually read off: 12tm for RED_EYE,
    # 10tm for NDDPL. A sheet showing only the blend cannot be used for either.
    assert "<td class='n'>1.2</td><td class='n'>1.8</td><td class='n'><b>1.5</b></td>" in page


def test_the_sleeper_rank_is_joined_by_name_and_left_blank_when_unknown():
    """Nacua is not in the index. An unmatched player gets an empty cell,
    never a borrowed or invented rank."""
    page = _full_page()
    row = next(line for line in page.split("<tr") if "Puka Nacua" in line)
    assert row.endswith("<td class='n'></td></tr>"), "unranked player borrowed a rank"
    spears = next(line for line in page.split("<tr") if "Tyjae Spears" in line)
    assert "<td class='n'>20</td>" in spears


def test_the_star_marks_a_measured_position_adjusted_gap():
    """Spears' 40-spot gap survives the RB median subtraction; the other
    RBs' do not. The star has to mean the same thing the Scout tab's
    "Sleeper find" means, or it is decoration."""
    page = _full_page()
    assert 'Tyjae Spears <span class="star">★</span>' in page
    assert page.count('<span class="star">') == 1, "only the measured find is starred"


def test_round_dividers_break_the_board_at_the_twelve_team_turn():
    """Rounds are the 12-team turn: Bijan 1.5 and Nacua 11.0 are both
    round one, Irving at 13.0 opens round two. A printed sheet with no
    round breaks cannot be read at a draft table."""
    page = _full_page()
    rows = {
        name: next(line for line in page.split("<tr") if name in line)
        for name in ("Bijan Robinson", "Puka Nacua", "Bucky Irving", "Tyjae Spears")
    }
    assert not rows["Puka Nacua"].startswith(' class="round"')
    for name in ("Bijan Robinson", "Bucky Irving", "Tyjae Spears"):
        assert rows[name].startswith(' class="round"'), name


def test_the_full_branch_stamps_when_it_was_generated():
    assert f"generated {CENTRAL_STAMP}" in _full_page()


def test_the_note_says_qbs_are_underpriced_by_this_market():
    """docs/LEAGUES.md, from the real settings pages: 6-pt passing TDs and
    20 pass yds/pt in both leagues, plus a point per completion in
    RED_EYE. The sheet's original note claimed QBs scored nothing for
    passing -- exactly backwards, and a reader who believed it drafted
    the position last."""
    page = _full_page()
    assert "Both leagues score QBs above this market" in page
    assert "6-pt passing TDs" in page
    assert "take them earlier than listed" in page
    assert "score nothing" not in page.lower()
    # And the sheet admits what it does not carry.
    assert "8 IDP players this sheet does not carry" in page


# --- both branches ----------------------------------------------------------


@BRANCHES
def test_both_branches_carry_the_tab_icon(build):
    """The regression this file exists for: the empty branch shipped
    without the favicon its full branch had."""
    assert "/app/assets/fsb-icon.svg" in build()


@BRANCHES
def test_both_branches_show_the_mark(build):
    assert "/app/assets/fsb-mark.svg" in build()


@BRANCHES
def test_both_branches_have_a_way_back_to_the_app(build):
    """Installed as a PWA there is no address bar, so a page with no exit
    is a dead end -- including the one the owner hits at 6am when the
    sync has not run."""
    page = build()
    assert "class='fsb-home' href='/app/'" in page
    assert "Fantasy Sports Bible · Cheat sheet" in page


@BRANCHES
def test_both_branches_render_the_clock_in_houston(build):
    """America/Chicago, not UTC and not the server's locale."""
    page = build()
    assert CENTRAL_STAMP in page
    assert "AM Central" not in page  # 02:30 UTC would be an AM stamp
