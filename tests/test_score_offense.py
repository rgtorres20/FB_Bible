"""League-scored offence — the half that was missing until Aug 21.

`score_idp` and `score_dst` have scored defenders against league rules
since August. Offence had every scoring *value* in `app/leagues.py` and
none of the stats they multiply, so the app could not total a single
quarterback — the position these leagues differ from market on most.

Every constant asserted here is the owner's verified Yahoo setting from
docs/LEAGUES.md. None of it is chosen by me.
"""

from __future__ import annotations

import pytest

from app import leagues

BY_NAME = {lg.name: lg for lg in leagues.defaults()}

# Season lines shaped like the real thing, so the totals mean something.
QB = {
    "pass_cmp": 359,
    "pass_yd": 4306,
    "pass_td": 28,
    "pass_int": 6,
    "rush_yd": 531,
    "rush_td": 12,
    "fum_lost": 3,
}
WR1 = {"rec": 105, "rec_yd": 1450, "rec_td": 9, "rush_yd": 40, "fum_lost": 1}


def test_an_empty_line_scores_zero_rather_than_raising():
    """Every scorer in this app has to survive a player with no stats —
    a rookie, a holdout, someone who never took a snap."""
    for lg in leagues.defaults():
        assert lg.score_offense({}) == 0.0
        # A line carrying only fields this league does not pay for.
        assert lg.score_offense({"off_snp": 900, "rec_tgt": 140}) == 0.0


def test_ppr_counts_every_reception():
    """All three leagues are full PPR (docs/LEAGUES.md)."""
    for lg in leagues.defaults():
        assert lg.ppr == 1.0
        assert lg.score_offense({"rec": 10}) == 10.0


@pytest.mark.parametrize("name,per_pt", [("NDDPL", 20.0), ("RED_EYE", 20.0), ("BALLAPALOSA", 10.0)])
def test_receiving_yardage_is_halved_in_the_two_idp_leagues(name, per_pt):
    """The rule that makes targets worth more than air yards — and the
    exception: BALLAPALOSA does NOT halve receiving."""
    lg = BY_NAME[name]
    assert lg.rec_yds_per_pt == per_pt
    assert lg.score_offense({"rec_yd": 1000}) == round(1000 / per_pt, 1)


def test_passing_touchdowns_are_worth_six_everywhere():
    """Six, not the four-point default — this is why QBs beat market here."""
    for lg in leagues.defaults():
        assert lg.pass_td == 6.0
        assert lg.score_offense({"pass_td": 4}) == 24.0


def test_completions_score_in_the_two_leagues_that_pay_for_them():
    """RED_EYE and BALLAPALOSA pay 1 per completion (default 0). It is the
    single largest scoring difference in the app: 359 completions is 359
    points, more than most WR1 seasons total."""
    assert BY_NAME["NDDPL"].pass_completion == 0.0
    assert BY_NAME["RED_EYE"].pass_completion == 1.0
    assert BY_NAME["BALLAPALOSA"].pass_completion == 1.0
    assert BY_NAME["RED_EYE"].score_offense({"pass_cmp": 359}) == 359.0
    assert BY_NAME["NDDPL"].score_offense({"pass_cmp": 359}) == 0.0


def test_interceptions_and_lost_fumbles_subtract():
    """Both −2, verified. Negative points are allowed in all three."""
    for lg in leagues.defaults():
        assert lg.pass_int == -2.0
        assert lg.fum_lost == -2.0
        assert lg.score_offense({"pass_int": 3, "fum_lost": 2}) == -10.0


def test_two_point_conversions_count_from_any_of_the_three_routes():
    """Passing, rushing and receiving conversions are all worth 2."""
    for lg in leagues.defaults():
        assert lg.score_offense({"pass_2pt": 1, "rush_2pt": 1, "rec_2pt": 1}) == 6.0


def test_kickers_score_at_all():
    """Every league starts one and six are on the board. Flat per made
    field goal: Yahoo's distance tiers are a per-league setting this repo
    has not verified, and 3/4/5-by-yardage would be an invented number."""
    for lg in leagues.defaults():
        assert lg.score_offense({"fgm": 30, "xpm": 40}) == 130.0


def test_return_yardage_scores_where_the_settings_pay_for_it():
    """docs/LEAGUES.md point 5: both IDP leagues pay returners 20 yds/pt,
    and the scorer ignored kick and punt returns entirely until Aug 22.
    A full-time returner's ~1,000 kick-return yards are 50 real points --
    enough to move a WR3 past a WR2 in a board built on these totals."""
    line = {"kr_yd": 600, "pr_yd": 400}
    assert BY_NAME["NDDPL"].ret_yds_per_pt == 20.0
    assert BY_NAME["RED_EYE"].ret_yds_per_pt == 20.0
    assert BY_NAME["NDDPL"].score_offense(line) == 50.0
    assert BY_NAME["RED_EYE"].score_offense(line) == 50.0
    # BALLAPALOSA's settings page pays return TDs and no return yardage.
    # Yardage this league does not score must read zero, not the other
    # leagues' number and not a ZeroDivisionError on the way to saying so.
    assert BY_NAME["BALLAPALOSA"].ret_yds_per_pt == 0.0
    assert BY_NAME["BALLAPALOSA"].score_offense(line) == 0.0


def test_a_return_touchdown_is_worth_six_in_all_three():
    """Kick and punt return TDs are the same six points as any other, and
    both routes count -- scoring only `kr_td` would silently zero out
    every punt returner in the app."""
    for lg in leagues.defaults():
        assert lg.ret_td == 6.0
        assert lg.score_offense({"kr_td": 1}) == 6.0
        assert lg.score_offense({"pr_td": 1}) == 6.0
        assert lg.score_offense({"kr_td": 1, "pr_td": 2}) == 18.0


def test_a_blank_league_pays_nothing_for_returns():
    """Yahoo's default is 0 for both, so a league somebody defines at
    /app/leagues starts at market and every non-zero return value there
    is a deliberate statement about their settings -- not NDDPL's
    inherited by accident."""
    lg = leagues.blank()
    assert (lg.ret_yds_per_pt, lg.ret_td) == (0.0, 0.0)
    assert lg.score_offense({"kr_yd": 1200, "pr_yd": 500, "kr_td": 2, "pr_td": 1}) == 0.0


def test_the_quarterback_premium_is_now_measurable():
    """The whole point. "QBs score above market in both leagues" has been
    a rule in CLAUDE.md carried by a hand-tuned `qb_boost_override`; this
    is the first time it is a number computed from stats.

    In RED_EYE a quarterback season outscores a WR1 season by more than
    three to one — driven by the completion bonus, which no market ranking
    prices in."""
    qb_red, wr_red = (BY_NAME["RED_EYE"].score_offense(s) for s in (QB, WR1))
    qb_nd, wr_nd = (BY_NAME["NDDPL"].score_offense(s) for s in (QB, WR1))
    assert qb_red > wr_red * 3
    assert qb_nd > wr_nd
    # And the gap really is bigger in RED_EYE than NDDPL, which is the
    # league difference the app claims and never previously computed.
    assert (qb_red - wr_red) > (qb_nd - wr_nd)


def test_the_same_player_scores_differently_in_each_league():
    """Three leagues, three totals for one season. A single "points"
    column would be wrong in at least two of them."""
    totals = {name: lg.score_offense(QB) for name, lg in BY_NAME.items()}
    assert len(set(totals.values())) == 3, totals


def test_a_user_league_round_trips_the_new_values():
    """These are user-editable at /app/leagues, so they have to survive
    to_dict/from_dict like every other scoring value."""
    lg = BY_NAME["RED_EYE"]
    back = leagues.League.from_dict(lg.to_dict())
    assert back.score_offense(QB) == lg.score_offense(QB)
    for f in (
        "rush_td",
        "rec_td",
        "pass_int",
        "fum_lost",
        "two_pt",
        "fg_made",
        "xp_made",
        # The return pair is newest and so the likeliest to have been
        # added to the dataclass and forgotten in the serialiser -- a
        # user's saved league would then silently drop to market on its
        # next read, with no error anywhere to say so.
        "ret_yds_per_pt",
        "ret_td",
    ):
        assert getattr(back, f) == getattr(lg, f)
    returner = {"kr_yd": 800, "pr_yd": 300, "pr_td": 1}
    assert back.score_offense(returner) == lg.score_offense(returner) == 61.0
