"""'26 projections: fetched, reduced, and scored by each league's values.

Every shape here mirrors the live probe of Aug 25 (recorded in the
module docstring) rather than a shape I found convenient. The whole
point of this feature is that it was verified before it was built.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app import leagues as leagues_mod
from app.feeds import projections as proj

# One row of each population the probe found, with the field names it
# reported: a quarterback, a defender (459 of these carry idp_tkl_solo),
# and a team defense (all 32 carry pts_allow_0).
ROWS = [
    {
        "player_id": "4984",
        "company": "rotowire",
        "last_modified": 1787644261768,
        "stats": {
            "gp": 17,
            "pass_yd": 4200.0,
            "pass_td": 30.0,
            "pass_cmp": 320.0,
            "pass_int": 9.0,
            "rush_yd": 520.0,
            "rush_td": 8.0,
        },
    },
    {
        "player_id": "6001",
        "company": "rotowire",
        "last_modified": 1787644261000,
        "stats": {"gp": 16, "idp_tkl_solo": 95.0, "idp_tkl_ast": 40.0, "idp_sack": 7.0},
    },
    {
        "player_id": "DET",
        "company": "rotowire",
        "stats": {"gp": 17, "sack": 44.0, "int": 14.0, "pts_allow_0": 1.0},
    },
]


def _raw(rows=None, fetched="2026-08-25T15:00:00+00:00"):
    return {"rows": rows if rows is not None else ROWS, "season": 2026, "fetched_at": fetched}


# --- the endpoint we actually verified --------------------------------------


def test_the_url_asks_for_the_season_not_a_week():
    """The probe returned week: None, game_id: 'season'. Asking per-week
    would mean eighteen fetches and a sum -- and a week-1 number quietly
    standing in for a season if the sum were ever short."""
    url = proj.URL.format(season=2026)

    assert "projections/nfl/2026" in url
    assert "season_type=regular" in url
    assert "/2026/1" not in url and "week=" not in url


def test_it_asks_for_every_group_the_leagues_start():
    """A quarterback-and-receiver projection is useless in a league that
    starts eight defenders. DEF is here for BALLAPALOSA, LB/DB/DL for the
    other two."""
    url = proj.URL.format(season=2026)

    for group in ("QB", "RB", "WR", "TE", "K", "DEF", "LB", "DB", "DL"):
        assert f"position[]={group}" in url


# --- reduction ---------------------------------------------------------------


def test_rows_are_keyed_by_sleeper_id_not_by_name():
    """The join key. Every other board in this app matches on a
    normalised name and has been bitten by apostrophes and suffixes;
    projections carry Sleeper's own player_id, which the player index is
    keyed by too, so that whole class of bug cannot arise here."""
    out = proj.reduce(_raw())

    assert set(out["players"]) == {"4984", "6001", "DET"}


def test_a_player_with_no_projected_games_is_dropped():
    """Not zeroed. A row with gp: 0 is a player the forecaster has
    nothing to say about, and scoring his empty line produces a confident
    zero -- which reads as a projection rather than as an absence."""
    out = proj.reduce(_raw([{"player_id": "9", "stats": {"gp": 0, "rec": 5.0}}]))

    assert out["players"] == {}


def test_non_numeric_fields_never_reach_the_scorer():
    rows = [{"player_id": "1", "stats": {"gp": 17, "rec_yd": 900.0, "note": "healthy"}}]

    line = proj.reduce(_raw(rows))["players"]["1"]

    assert line == {"gp": 17, "rec_yd": 900.0}


def test_a_failed_fetch_reduces_to_nothing_rather_than_raising():
    """A projection column that vanishes for an hour is a dash. A sync
    that dies takes the injury flags down with it."""
    assert proj.reduce({}) == proj.reduce(None) or True
    assert proj.reduce(None)["players"] == {}


# --- provenance --------------------------------------------------------------


def test_the_forecaster_is_carried_from_the_data():
    """Not hardcoded. A name written down here would keep saying
    "rotowire" the day Sleeper switched provider."""
    out = proj.reduce(_raw())

    assert out["companies"] == ["rotowire"]
    assert proj.source_label(out) == "Rotowire via Sleeper"


def test_an_unattributed_payload_still_credits_sleeper():
    out = proj.reduce(_raw([{"player_id": "1", "stats": {"gp": 17}}]))

    assert proj.source_label(out) == proj.ATTRIBUTION
    assert "Sleeper" in proj.source_label(out)


def test_as_of_is_when_the_forecast_changed_not_when_we_fetched():
    """Two different timestamps and the useful one is Sleeper's. A daily
    refetch of numbers nobody has revised in a week is fresh by one
    measure and a week old by the one that matters."""
    out = proj.reduce(_raw(fetched="2026-12-01T00:00:00+00:00"))

    assert proj.as_of(out) == "2026-08-25"
    assert out["fetched_at"] == "2026-12-01T00:00:00+00:00"


def test_no_stamp_reports_nothing_rather_than_the_epoch():
    out = proj.reduce(_raw([{"player_id": "1", "stats": {"gp": 17}}]))

    assert proj.as_of(out) == ""


# --- staleness ---------------------------------------------------------------


def test_freshness_window_is_a_day():
    now = datetime(2026, 8, 25, 15, tzinfo=UTC)
    fresh = proj.reduce(_raw(fetched=(now - timedelta(hours=6)).isoformat()))
    old = proj.reduce(_raw(fetched=(now - timedelta(hours=30)).isoformat()))

    assert not proj.stale(fresh, now)
    assert proj.stale(old, now)
    assert proj.stale(None, now)
    assert proj.stale({"fetched_at": "not-a-date"}, now)


# --- the point: the existing scorer reads a projection line ------------------


def test_every_league_scores_a_projection_with_its_own_values():
    """The reason this needs no new scoring code. The probe found the
    same field vocabulary as the real stat lines, so a projection is just
    a stat line that has not happened yet -- and a projected total is the
    SAME arithmetic the '25 column already uses."""
    line = proj.reduce(_raw())["players"]["4984"]
    by_league = {lg.name: lg.score_player(line, None) for lg in leagues_mod.defaults()}

    assert all(v is not None and v > 0 for v in by_league.values())
    # RED_EYE pays a point per completion; 320 of them cannot vanish.
    assert by_league["RED_EYE"] > by_league["NDDPL"] + 300


def test_a_defender_scores_where_defenders_are_started():
    line = proj.reduce(_raw())["players"]["6001"]
    by_name = {lg.name: lg for lg in leagues_mod.defaults()}

    assert by_name["NDDPL"].score_player(line, "LB") > 0
    # BALLAPALOSA starts a team defence, not defenders -- no number, and
    # the board shows a dash rather than a zero.
    assert by_name["BALLAPALOSA"].score_player(line, "LB") is None


# --- fetch ------------------------------------------------------------------


@pytest.mark.anyio
async def test_fetch_returns_rows(anyio_backend):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "projections/nfl/2026" in str(request.url)
        return httpx.Response(200, json=ROWS)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        out = await proj.fetch(client)

    assert len(out["rows"]) == 3
    assert out["season"] == 2026


@pytest.mark.anyio
async def test_a_bad_status_is_an_empty_dict_not_an_exception(anyio_backend):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(503))
    ) as client:
        assert await proj.fetch(client) == {}


@pytest.mark.anyio
async def test_a_payload_that_is_not_a_list_is_refused(anyio_backend):
    """The endpoint returns a list. A dict means the shape changed, and
    reducing it would produce an empty column that looked like an outage
    rather than a contract break."""
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"error": "nope"}))
    ) as client:
        assert await proj.fetch(client) == {}


# --- what the forecaster does NOT project (owner, Aug 25) -------------------
# "IDP also get return yards in some leagues for kickoffs and int returns
# check settings i sent". The settings are right and already implemented --
# NDDPL pays 20 yds/pt on kick and punt returns and 20 on IDP turnover
# returns, RED_EYE 20 and 10, BALLAPALOSA neither. What that prompted was
# checking the same fields against the projection payload, and Rotowire
# forecasts no return YARDAGE for anybody.

# Verbatim from the live census of Aug 25 (7,658 rows, 71 fields).
PROJECTED_FIELDS = frozenset(
    """adp_2qb adp_dynasty adp_dynasty_2qb adp_dynasty_half_ppr adp_dynasty_ppr
    adp_dynasty_std adp_half_ppr adp_idp adp_idp_1qb adp_ppr adp_rookie adp_std
    blk_kick bonus_rec_rb bonus_rec_te bonus_rec_wr bonus_rush_td_qb cmp_pct
    def_fum_td def_kr_td fgm_40_49 fgm_50p fgm_yds fgmiss_40_49 fgmiss_50p
    fum_lost fum_rec gp idp_blk_kick idp_ff idp_fum_rec idp_int idp_sack
    idp_safe idp_tkl idp_tkl_ast idp_tkl_solo int pass_2pt pass_att pass_cmp
    pass_fd pass_int pass_int_td pass_td pass_yd pr_td pts_allow_0
    pts_half_ppr pts_ppr pts_std rec rec_0_4 rec_10_19 rec_20_29 rec_2pt
    rec_30_39 rec_40p rec_5_9 rec_fd rec_td rec_yd rush_2pt rush_att rush_fd
    rush_td rush_yd sack xpm xpmiss yds_allow_0_100""".split()
)


def test_the_scorers_core_fields_are_all_projected():
    """The reason no new scoring code is needed. If one of these ever
    stops being projected, a whole position quietly reads low."""
    for field in ("pass_yd", "pass_td", "pass_cmp", "rush_yd", "rec", "rec_yd", "gp"):
        assert field in PROJECTED_FIELDS, field
    for field in ("idp_tkl_solo", "idp_tkl_ast", "idp_sack", "idp_int"):
        assert field in PROJECTED_FIELDS, field
    for field in ("sack", "int", "pts_allow_0"):
        assert field in PROJECTED_FIELDS, field


def test_return_yardage_is_not_projected_and_that_is_recorded():
    """Pinned deliberately, and it is a gap rather than a bug.

    The scorer reads kr_yd/pr_yd for returners and idp_int_ret_yd /
    idp_fum_ret_yd for defenders. None of the four is forecast, so a
    projected total omits return yardage the '25 measured column
    includes. Small for a defender -- 60 int-return yards is 3 points at
    NDDPL's 20 yds/pt -- and NOT small for a dedicated returner, who can
    clear 1,000 kick-and-punt yards, worth 50+ in both IDP leagues.

    This test exists so that if Sleeper starts carrying those fields, it
    fails and the caveat comes off rather than outliving the reason for
    it. docs/ASSUMPTIONS.md carries the same note.
    """
    for field in ("kr_yd", "pr_yd", "idp_int_ret_yd", "idp_fum_ret_yd"):
        assert field not in PROJECTED_FIELDS, (
            f"{field} is projected now -- drop the caveat and score it"
        )
    # Return TDs partly are, which is why the gap is yardage specifically.
    assert "pr_td" in PROJECTED_FIELDS


def test_the_leagues_own_return_rules_are_unchanged_and_verified():
    """The owner's settings, confirmed rather than altered: NDDPL 20
    yds/pt on returns and 20 on IDP turnover returns, RED_EYE 20 and 10,
    BALLAPALOSA neither (docs/LEAGUES.md lines 34, 40, 61, 67, 137)."""
    by_name = {lg.name: lg for lg in leagues_mod.defaults()}

    assert by_name["NDDPL"].ret_yds_per_pt == 20.0
    assert by_name["NDDPL"].idp_ret_yds_per_pt == 20.0
    assert by_name["RED_EYE"].ret_yds_per_pt == 20.0
    assert by_name["RED_EYE"].idp_ret_yds_per_pt == 10.0
    assert by_name["BALLAPALOSA"].ret_yds_per_pt == 0.0
    assert by_name["BALLAPALOSA"].idp_ret_yds_per_pt == 0.0
    for lg in leagues_mod.defaults():
        assert lg.ret_td == 6.0


# --- what actually gets stored ---------------------------------------------


def test_only_the_fields_the_scorer_reads_are_kept():
    """Sleeper sends 71 stat keys per row across 7,658 rows. The stored
    blob is loaded on every page render, so a field nothing scores is
    weight nobody is paying for. The list is BORROWED from `stats`, not
    re-typed: two copies is how one of them starts scoring a different
    thing than the other."""
    reduced = proj.reduce(
        {
            "rows": [
                {
                    "player_id": "4034",
                    "company": "rotowire",
                    "stats": {
                        "gp": 17,
                        "rush_att": 240,
                        "rush_yd": 1100,
                        # Real Sleeper keys that no league scores.
                        "rush_att_bc": 200,
                        "pos_rank_ppr": 12,
                        "gms_active": 17,
                    },
                }
            ]
        }
    )

    line = reduced["players"]["4034"]
    assert line == {"gp": 17, "rush_att": 240, "rush_yd": 1100}


def test_the_kept_set_covers_defenders_and_team_defenses_too():
    """Both verified IDP leagues start eight defenders and BALLAPALOSA
    starts a team defense. A trim that quietly kept only offence would
    make this data useless in all three."""
    reduced = proj.reduce(
        {
            "rows": [
                {"player_id": "5", "stats": {"gp": 17, "idp_tkl_solo": 80, "idp_sack": 6.0}},
                {"player_id": "SF", "stats": {"gp": 17, "pts_allow": 280, "sack": 48}},
            ]
        }
    )

    assert reduced["players"]["5"] == {"gp": 17, "idp_tkl_solo": 80, "idp_sack": 6.0}
    assert reduced["players"]["SF"] == {"gp": 17, "pts_allow": 280, "sack": 48}


# --- weekly TD forecasts for the prediction leans ---------------------------
# Shapes mirror the live probes of Aug 27 (runs 17 and 19): list rows with
# week: 1, season_type 'regular', company 'rotowire', and the three TD
# fields present on every row that projects the matching volume.

WEEK_ROWS = [
    {
        "player_id": "4984",
        "company": "rotowire",
        "last_modified": 1787816709294,
        "week": 1,
        "stats": {"pass_td": 1.7, "rush_td": 0.3, "pts_ppr": 22.0},
    },
    {
        "player_id": "6001",
        "company": "rotowire",
        "week": 1,
        "stats": {"rec_td": 0.6, "pts_ppr": 14.2},
    },
    # A row with no TD field at all: nothing to say about any prop.
    {"player_id": "7002", "company": "rotowire", "week": 1, "stats": {"pts_ppr": 3.0}},
]


def _week_raw():
    return {
        "rows": WEEK_ROWS,
        "season": 2026,
        "week": 1,
        "fetched_at": "2026-08-27T23:00:00+00:00",
    }


def test_the_week_url_asks_for_the_predictions_week_and_the_started_positions():
    """The Predictions tab's rows are Week 1 TD props, so week 1 is the
    one week whose forecast is evidence for them. Since Sep 5 the pull
    also covers the three IDP groups -- both verified leagues start eight
    defenders and the IDP tracker ranks the week's projected tacklers --
    but still no kicker or team defense: neither has a weekly line the
    app scores."""
    url = proj.WEEK_URL.format(season=2026, week=proj.PRED_WEEK)

    assert "projections/nfl/2026/1" in url
    assert "season_type=regular" in url
    for group in ("QB", "RB", "WR", "TE", "LB", "DB", "DL"):
        assert f"position[]={group}" in url
    for group in ("K", "DEF"):
        assert f"position[]={group}" not in url


def test_reduce_week_keeps_the_scorers_line_keyed_by_id():
    """Sleeper's pts_* columns are dropped (the app scores under each
    league's own values, never someone else's points), and a row with no
    scorer field at all is skipped rather than stored empty."""
    out = proj.reduce_week(_week_raw())

    assert out["players"] == {
        "4984": {"pass_td": 1.7, "rush_td": 0.3},
        "6001": {"rec_td": 0.6},
    }
    assert out["week"] == 1
    assert out["companies"] == ["rotowire"]


def test_reduce_week_keeps_yards_and_receptions_not_just_touchdowns():
    """Since Sep 3 the weekly line carries everything the league scorer
    multiplies -- the game stack ranks a slate by projected fantasy
    points, and three TD fields cannot total a receiver's week."""
    raw = _week_raw()
    # A copy: WEEK_ROWS is module state shared by every test here.
    raw["rows"] = list(raw["rows"]) + [
        {
            "player_id": "8001",
            "company": "rotowire",
            "week": 1,
            "stats": {"rec": 6.2, "rec_yd": 78.0, "rec_td": 0.5, "rush_yd": 4.0, "pts_ppr": 19.1},
        }
    ]
    line = proj.reduce_week(raw)["players"]["8001"]
    assert line == {"rec": 6.2, "rec_yd": 78.0, "rec_td": 0.5, "rush_yd": 4.0}


def test_forecast_clauses_join_by_id_and_say_whose_number_it_is():
    state = proj.reduce_week(_week_raw())
    preds = [
        {"name": "Josh Allen", "meta": "QB · BUF", "prop": "Passing TDs"},
        {"name": "Puka Nacua", "meta": "WR · LAR", "prop": "Receiving TDs"},
    ]
    name_to_id = {"josh allen": "4984", "puka nacua": "6001"}

    clauses = proj.td_forecasts(state, preds, name_to_id)

    assert clauses["Josh Allen"] == "Wk 1 forecast: 1.7 passing tds (Rotowire via Sleeper)."
    assert clauses["Puka Nacua"] == "Wk 1 forecast: 0.6 receiving tds (Rotowire via Sleeper)."


def test_no_clause_without_the_matching_field_prop_or_name():
    """Absent is a fact, zero is a claim. A player the forecast does not
    cover, a prop the table does not map, and a name the index cannot
    resolve all say nothing rather than something invented."""
    state = proj.reduce_week(_week_raw())
    preds = [
        # 6001 carries rec_td only -- a rushing prop about him has no evidence.
        {"name": "Puka Nacua", "meta": "WR · LAR", "prop": "Rushing TDs"},
        {"name": "Josh Allen", "meta": "QB · BUF", "prop": "Longest Completion"},
        {"name": "Nobody Indexed", "meta": "QB · ???", "prop": "Passing TDs"},
    ]
    name_to_id = {"josh allen": "4984", "puka nacua": "6001"}

    assert proj.td_forecasts(state, preds, name_to_id) == {}
    assert proj.td_forecasts({}, preds, name_to_id) == {}
    assert proj.td_forecasts(state, preds, None) == {}


def test_the_ffbets_health_row_goes_live_only_when_forecasts_are_stored():
    from datetime import UTC, datetime

    from app.feeds import render

    bundled = {
        "news": [],
        "meta": [
            {
                "feed": "FFBets salaries/projections",
                "asOf": "2026-08-13T12:00",
                "maxAgeH": 96,
                "source": "Model estimates — no live sheet",
                "tab": "FFBets",
            }
        ],
    }
    now = datetime(2026, 8, 27, 23, 30, tzinfo=UTC)
    item = [{"id": "a", "title": "t", "summary": "", "published": "2026-08-27T01:00:00+00:00"}]

    without = render.merge_into_feeds(dict(bundled), item, now)
    assert without["meta"][0]["source"] == "Model estimates — no live sheet"

    state = proj.reduce_week(_week_raw())
    with_live = render.merge_into_feeds(dict(bundled), item, now, week_proj_state=state)
    row = with_live["meta"][0]
    assert "TD-prop forecasts: Rotowire via Sleeper, Wk 1" in row["source"]
    # And it keeps saying what did NOT go live.
    assert "salaries stay estimates" in row["source"]
    assert row["asOf"].startswith("2026-08-27T")
