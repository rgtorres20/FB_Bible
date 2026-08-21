"""The canonical league description.

Until this module existed the same facts lived twice -- Python dicts in
`feeds/idp.py` and a JavaScript object inside `feeds/mock.py` -- and they
agreed only because someone kept them agreeing. These tests pin the two
verified leagues to docs/LEAGUES.md (the owner's own Yahoo settings
pages, Aug 19-20) and pin the derived numbers to the values the surfaces
shipped with, so the refactor is provably a refactor.

The rest is about leagues nobody has verified: a user-defined league must
never inherit a number that was tuned against somebody else's room, and
must never be told it is QB-premium when its own settings say otherwise.
"""

from __future__ import annotations

from dataclasses import replace

from app import leagues


def test_the_two_idp_leagues_match_the_settings_pages():
    """docs/LEAGUES.md is the ground truth: NDDPL 10-team, RED_EYE
    12-team (owner correction Aug 20, superseding the PDF's 10), both
    full PPR, both 6-pt passing TDs at 20 yds/pt, RED_EYE alone paying a
    point per completion, receiving yards halved in both."""
    assert (leagues.NDDPL.teams, leagues.RED_EYE.teams) == (10, 12)
    for lg in (leagues.NDDPL, leagues.RED_EYE):
        assert lg.ppr == 1.0
        assert lg.pass_td == 6.0
        assert lg.pass_yds_per_pt == 20.0
        assert lg.rec_yds_per_pt == 20.0
        assert lg.receiving_is_halved
    assert leagues.NDDPL.pass_completion == 0.0
    assert leagues.RED_EYE.pass_completion == 1.0


def test_ballapalosa_matches_its_settings_page():
    """The third verified league (ID# 963878, settings page Aug 21), and
    the one that proves the D/ST path on real numbers: 10 teams, full
    PPR, 6-pt passing TDs and a point per completion — but market
    yardage on all three, so receiving is NOT halved here."""
    lg = leagues.BALLAPALOSA
    assert lg.teams == 10
    assert lg.ppr == 1.0
    assert (lg.pass_td, lg.pass_yds_per_pt, lg.pass_completion) == (6.0, 25.0, 1.0)
    assert lg.rec_yds_per_pt == 10.0 and not lg.receiving_is_halved
    # QB/3WR/2RB/TE/W-R-T/K/DEF then six bench. The settings page also
    # lists two IR slots; those are not draft rounds, and counting them
    # would run the mock room two rounds past the real draft.
    assert lg.rounds == 16
    assert leagues.counts_from_slots(lg.slots)["DEF"] == 1


def test_the_two_idp_leagues_start_eight_defenders():
    """The count the IDP board and the mock room both depend on."""
    for lg in (leagues.NDDPL, leagues.RED_EYE):
        assert sum(1 for s in lg.slots if s in {"DB", "LB", "DL", "D"}) == 8
        assert lg.starts_idp
        assert not lg.starts_dst


def test_no_built_in_league_starts_both_kinds_of_defense():
    """Owner's rule, Aug 21: a league picks one. The editor refuses the
    other combination; this is the assertion that the shipped leagues
    obey the same rule they are held to."""
    for lg in leagues.defaults():
        assert not (lg.starts_idp and lg.starts_dst), lg.name


def test_startable_groups_are_derived_from_the_slots():
    """NDDPL has no DL slot at all, so edge rushers are unrosterable
    there -- and that cannot be configured wrong separately from the
    roster, because it is read off the roster."""
    assert leagues.NDDPL.idp_groups == frozenset({"DB", "LB"})
    # RED_EYE's generic D slot admits every group.
    assert leagues.RED_EYE.idp_groups == frozenset({"DB", "LB", "DL"})
    assert not leagues.blank().starts_idp


def test_idp_scoring_reproduces_the_values_the_board_shipped_with():
    """100 solo + 40 assists + 2 sacks + 1 INT + 4 PD + 1 FF, the same
    line tests/test_idp.py scores: NDDPL pays 3/sack and 2/INT, RED_EYE
    2 and 3, so the two leagues land a point apart."""
    line = {
        "idp_tkl_solo": 100,
        "idp_tkl_ast": 40,
        "idp_sack": 2,
        "idp_int": 1,
        "idp_pass_def": 4,
        "idp_ff": 1,
    }
    assert leagues.NDDPL.score_idp(line) == 134.0
    assert leagues.RED_EYE.score_idp(line) == 133.0


def test_return_yardage_uses_each_league_s_own_divisor():
    """20 yds/pt in NDDPL, 10 in RED_EYE -- the one IDP field that is not
    a flat per-event value."""
    line = {"idp_int_ret_yd": 60, "idp_fum_ret_yd": 40}
    assert leagues.NDDPL.score_idp(line) == 5.0
    assert leagues.RED_EYE.score_idp(line) == 10.0
    # A league that pays nothing for return yardage must not divide by
    # zero on the way to saying so.
    assert leagues.blank().score_idp(line) == 0.0


def test_the_adp_column_follows_the_room_size():
    """FFC publishes 10- and 12-team boards; a league drafts against
    whichever is closer to its own room."""
    assert leagues.NDDPL.adp_size_key == "a10"
    assert leagues.RED_EYE.adp_size_key == "a12"
    assert leagues.blank(teams=8).adp_size_key == "a10"
    assert leagues.blank(teams=14).adp_size_key == "a12"


def test_qb_premium_is_measured_against_the_market_not_asserted():
    """This number is what justifies telling someone to draft QBs ahead
    of ADP, so it has to fall out of their settings. A league scoring at
    market gets zero and no boost -- not a borrowed one."""
    market = leagues.blank()
    assert market.qb_premium_per_game == 0.0
    assert market.qb_draft_boost == 0.0
    assert leagues.NDDPL.qb_premium_per_game > 0
    # RED_EYE's point per completion is worth far more than NDDPL's
    # touchdown and yardage bumps alone.
    assert leagues.RED_EYE.qb_premium_per_game > leagues.NDDPL.qb_premium_per_game * 3


def test_the_verified_leagues_keep_their_tuned_boosts():
    """10 and 18 were tuned against how those rooms actually draft; the
    derivation is crude enough that it must not silently replace them."""
    assert leagues.NDDPL.qb_draft_boost == 10.0
    assert leagues.RED_EYE.qb_draft_boost == 18.0


def test_a_user_league_derives_its_own_boost_and_never_inherits_one():
    """The bug this test exists for: `blank()` was built by copying
    NDDPL, so every user league silently carried NDDPL's tuned 10.0 and
    two wildly different leagues reported the same boost."""
    tame = leagues.blank("Tame", 12)
    wild = replace(tame, pass_td=8.0, pass_yds_per_pt=15.0, pass_completion=1.0)
    assert tame.qb_boost_override is None
    assert tame.qb_draft_boost == 0.0
    assert wild.qb_draft_boost > tame.qb_draft_boost


def test_a_bonus_every_quarterback_earns_does_not_move_the_draft_board():
    """The Aug 21 finding, and the reason the derived boost disagreed with
    the tuned overrides by roughly 2x.

    A point per completion adds ~22 points a game to QB1 and ~22 to the
    twelfth-best starter. It lifts the whole position and separates
    nobody, so it belongs in the *level* premium and not in the number
    that decides how early to draft one.
    """
    plain = replace(leagues.blank("Plain", 12), qb_boost_override=None)
    rich = replace(plain, pass_completion=1.0)
    assert rich.qb_premium_per_game > plain.qb_premium_per_game, "level: it is real points"
    assert rich.qb_spread_premium_per_game == plain.qb_spread_premium_per_game
    assert rich.qb_draft_boost == plain.qb_draft_boost


def test_a_bonus_that_scales_with_quality_does_move_it():
    """Touchdown and yardage values are the other case: a better
    quarterback throws more of them, so a richer value widens the gap
    between him and a replacement. Those must still count."""
    plain = replace(leagues.blank("Plain", 12), qb_boost_override=None)
    rich = replace(plain, pass_td=plain.pass_td + 2)
    assert rich.qb_spread_premium_per_game > plain.qb_spread_premium_per_game
    assert rich.qb_draft_boost > plain.qb_draft_boost


def test_the_two_verified_leagues_differ_only_by_a_bonus_that_spreads_nobody():
    """NDDPL and RED_EYE score passing touchdowns and yardage identically;
    the only difference is RED_EYE's point per completion. So their spread
    premiums must be equal even though their level premiums are not.

    Their overrides are 10 and 18, which is the interesting part and why
    both are kept: the override records how that room *actually* drafts,
    and those rooms do not draft the same way (docs/GAP_REVIEW.md).
    """
    nddpl, red_eye, _ = leagues.defaults()
    assert nddpl.qb_spread_premium_per_game == red_eye.qb_spread_premium_per_game
    assert red_eye.qb_premium_per_game > nddpl.qb_premium_per_game


def test_a_derived_boost_is_capped_at_two_rounds():
    """The cap used to be load-bearing — it was the only thing stopping
    the completion bonus deriving a 110-slot boost. It is a backstop now,
    so this checks it still holds for genuinely extreme scoring rather
    than for the case that got fixed."""
    absurd = replace(leagues.blank("Absurd", 12), pass_td=40.0, qb_boost_override=None)
    assert absurd.qb_spread_premium_per_game > 50
    assert absurd.qb_draft_boost == leagues.MAX_DERIVED_QB_BOOST


def test_a_league_survives_a_round_trip_through_storage():
    for lg in (*leagues.defaults(), leagues.blank("Mine", 14)):
        assert leagues.League.from_dict(lg.to_dict()) == lg


def test_a_stored_blob_cannot_crash_the_scoring_path():
    """Stored league settings are user data that outlives the code that
    wrote it. An unknown key from a newer version, or a missing one from
    an older, has to degrade rather than raise -- the alternative is a
    draft board that 500s the morning of the draft."""
    revived = leagues.League.from_dict(
        {"name": "Half a blob", "slots": ["QB", "RB"], "unknown_future_field": 3}
    )
    assert revived.name == "Half a blob"
    assert revived.teams == 10
    assert revived.score_idp({"idp_sack": 4}) == 0.0
    assert leagues.League.from_dict({}).slots == ()


# --- team defenses ----------------------------------------------------------


def _detroit() -> dict:
    """Detroit's real '25 team-defense line, straight off Sleeper's season
    dump (probe run 7, 2026-08-21). A real row rather than a made-up one,
    so a scoring bug shows up as a number somebody could recognise."""
    return {
        "gp": 17,
        "sack": 49,
        "int": 13,
        "ff": 15,
        "fum_rec": 6,
        "safe": 1,
        "blk_kick_any": 2,
        "def_st_td": 1,
        "def_pass_def": 93,
        "def_4_and_stop": 11,
        "int_ret_yd": 132,
        "fum_ret_yd": 5,
        "pts_allow": 411,
        "pts_allow_7_13": 2,
        "pts_allow_14_20": 2,
        "pts_allow_21_27": 8,
        "pts_allow_28_34": 4,
        "pts_allow_35p": 1,
        # The trap: a bare `td` on the same entry, which is touchdowns
        # ALLOWED. Scoring it would hand every defense a few hundred
        # phantom points, so nothing may read it.
        "td": 57,
    }


def _yahoo_dst() -> leagues.League:
    return replace(
        leagues.blank("D/ST league", 12),
        slots=("QB", "RB", "WR", "TE", "K", "DEF", "BN", "BN"),
        dst=dict(leagues.DEFAULT_DST),
        dst_pa=dict(leagues.DEFAULT_DST_PA),
    )


def test_a_def_slot_is_not_an_idp_slot():
    """Two different things that both look like defense. A league can
    start either, both, or neither, and the derivation has to keep them
    apart -- "DEF" must never be read as the generic IDP "D"."""
    dst_only = _yahoo_dst()
    assert dst_only.starts_dst
    assert not dst_only.starts_idp
    assert dst_only.idp_groups == frozenset()

    idp_only = leagues.NDDPL
    assert idp_only.starts_idp
    assert not idp_only.starts_dst

    both = replace(dst_only, slots=(*dst_only.slots, "LB", "DB"))
    assert both.starts_dst and both.idp_groups == frozenset({"LB", "DB"})


def test_detroit_scores_the_way_the_settings_say():
    """49 sacks, 13 INTs, 6 recoveries, a safety, 2 blocks, 1 defensive
    or return TD = 99, and a points-allowed ladder worth +2 on Yahoo's
    defaults. Fourth-down stops score 0 by Yahoo default, so the eleven
    Detroit had are worth nothing here -- and 55 points in BALLAPALOSA,
    which pays 5 apiece."""
    assert _yahoo_dst().score_dst(_detroit()) == 101.0
    assert leagues.BALLAPALOSA.score_dst(_detroit()) == 139.0


def test_touchdowns_allowed_are_never_scored_as_touchdowns_scored():
    """The single most expensive mistake available here: the team entry
    carries a bare `td` of 57, which is what the defense gave up."""
    assert "td" not in dict(leagues.DST_FIELDS)
    line = _detroit()
    with_td = _yahoo_dst().score_dst(line)
    line["td"] = 0
    assert _yahoo_dst().score_dst(line) == with_td


def test_the_points_allowed_ladder_is_a_dot_product_over_game_counts():
    """Each stored value is games finished inside that band, so a shutout
    tier is worth its value times the number of shutouts -- no
    game-by-game reconstruction anywhere."""
    league = replace(
        leagues.blank(),
        slots=("DEF",),
        dst_pa={"pts_allow_0": 10.0, "pts_allow_35p": -4.0},
    )
    assert league.score_dst({"pts_allow_0": 3, "pts_allow_35p": 2}) == 22.0


def test_yards_allowed_and_return_yardage_are_available_but_off_by_default():
    """Uncommon, so folded away in the editor -- but a league that scores
    them must not be told its settings are unrepresentable."""
    assert _yahoo_dst().dst_ya == {} and _yahoo_dst().dst_ret_yds_per_pt == 0.0
    scored = replace(
        _yahoo_dst(),
        dst_ya={"yds_allow_100_199": 2.0},
        dst_ret_yds_per_pt=25.0,
    )
    # +2 for the one sub-200 game Detroit had... they had none, so only
    # the return yardage moves: (132 + 5) / 25 = 5.48.
    assert scored.score_dst(_detroit()) == round(101.0 + 137 / 25, 1)


def test_a_dst_league_survives_a_round_trip_through_storage():
    league = replace(_yahoo_dst(), dst_ya={"yds_allow_550p": -3.0}, dst_ret_yds_per_pt=25.0)
    assert leagues.League.from_dict(league.to_dict()) == league


def test_a_league_that_starts_no_defense_scores_none():
    assert leagues.blank().score_dst(_detroit()) == 0.0
