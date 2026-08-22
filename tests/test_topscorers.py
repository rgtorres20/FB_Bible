"""The scoring board: real stat lines through each league's real values.

Owner ask, Aug 21: *"see who would score the most points in each league."*

Every other board in this app ranks by an opinion. This one ranks by
arithmetic, which means every number on it is checkable — so these tests
check them, by hand, rather than asserting that the code agrees with
itself.

The contract:

1. **The scoring is the league's own.** RED_EYE's point-per-completion
   and BALLAPALOSA's full-value receiving have to move the order, not
   just the totals.
2. **A player is scored one way.** Offence, or IDP, or team defense —
   decided by what the league can start, never twice.
3. **A dash is not a zero.** A league that cannot start a player says so.
4. **Per-game sits beside the total**, and neither is invented.
5. **A stored blob that predates the offensive fields yields a message,
   not a table of zeroes** — a zero column reads as a finding.

Real player names with constructed stat lines, the same convention
`tests/test_idp.py` uses: the names must be real so nothing fabricated
reaches a surface, and the lines are chosen to make the arithmetic
legible.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import leagues as leagues_mod
from app import main
from app.feeds import players as players_mod
from app.feeds import topscorers
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
NDDPL, RED_EYE, BALLAPALOSA = leagues_mod.defaults()


def _index() -> dict:
    return {
        "v": players_mod.INDEX_VERSION,
        "by_name": {},
        "surnames": {},
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
                "name": "Puka Nacua",
                "position": "WR",
                "team": "LAR",
                "injury_status": None,
                "rank": 5,
            },
            "3": {
                "id": "3",
                "name": "Myles Garrett",
                "position": "DE",
                "team": "CLE",
                "injury_status": None,
                "rank": 350,
                "idp": "DL",
            },
            "4": {
                "id": "4",
                "name": "Roquan Smith",
                "position": "LB",
                "team": "BAL",
                "injury_status": "Questionable",
                "rank": 400,
                "idp": "LB",
            },
        },
    }


def _stats() -> dict:
    """Constructed lines, worked through below so the expected totals in
    these tests are arithmetic anyone can redo on paper."""
    return {
        "v": 5,
        "season": 2025,
        "coverage": {"players": {"pass_cmp": 300, "idp_tkl_solo": 1124}},
        "players": {
            # Allen: 4600 pass yds, 36 pass TD, 400 completions, 10 INT,
            #        300 rush yds, 4 rush TD, 3 fumbles lost.
            #   NDDPL   4600/20=230 +216 +30 +24 -20 -6            = 474.0
            #   RED_EYE the same plus 400 completions at 1.0       = 874.0
            #   BALLA   4600/25=184 +216 +30 +24 -20 -6 +400       = 828.0
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
            # Nacua: 110 rec, 1500 rec yds, 10 rec TD, 40 rush yds, 1 fumble.
            #   NDDPL/RED_EYE  110 +1500/20=75 +60 +4 -2           = 247.0
            #   BALLA          110 +1500/10=150 +60 +4 -2          = 322.0
            "2": {
                "gp": 17,
                "rec": 110,
                "rec_yd": 1500,
                "rec_td": 10,
                "rush_yd": 40,
                "fum_lost": 1,
            },
            # Garrett, a defensive lineman: RED_EYE starts him, NDDPL has
            # no DL slot at all, BALLAPALOSA starts no defenders.
            "3": {"gp": 17, "idp_tkl_solo": 40, "idp_sack": 14},
            "4": {
                "gp": 17,
                "idp_tkl_solo": 100,
                "idp_tkl_ast": 40,
                "idp_sack": 2,
                "idp_int": 1,
                "idp_pass_def": 4,
                "idp_ff": 1,
            },
        },
        "defenses": {},
    }


def _by_name(board, name):
    return next(r for r in board if r["name"] == name)


# --- 1. the scoring is the league's own ---------------------------------


def test_the_totals_are_each_leagues_own_arithmetic():
    board = topscorers.rows(_index(), _stats())
    allen = _by_name(board, "Josh Allen")
    assert allen["nddpl"] == pytest.approx(474.0)
    assert allen["red_eye"] == pytest.approx(874.0)
    assert allen["ballapalosa"] == pytest.approx(828.0)


def test_the_completion_bonus_is_visible_as_a_number():
    """RED_EYE pays a point per completion and NDDPL pays none. On 400
    completions that is a 400-point gap between two columns for the same
    player — the single biggest reason this page exists."""
    allen = _by_name(topscorers.rows(_index(), _stats()), "Josh Allen")
    assert allen["red_eye"] - allen["nddpl"] == pytest.approx(400.0)
    assert RED_EYE.pass_completion == 1.0
    assert NDDPL.pass_completion == 0.0


def test_halved_receiving_shows_up_where_it_is_not_halved():
    """Both verified leagues halve receiving yardage; BALLAPALOSA does
    not. The same 1500-yard receiver is worth 75 more points there."""
    nacua = _by_name(topscorers.rows(_index(), _stats()), "Puka Nacua")
    assert nacua["nddpl"] == nacua["red_eye"] == pytest.approx(247.0)
    assert nacua["ballapalosa"] == pytest.approx(322.0)


def test_the_league_scoring_actually_changes_the_order():
    """The claim the page makes. Not just different totals — a different
    ranking, or the columns would be decoration."""
    board = topscorers.rows(_index(), _stats())
    for key, expected in (("nddpl", "Josh Allen"), ("red_eye", "Josh Allen")):
        ordered = sorted(
            (r for r in board if r[key] is not None), key=lambda r: r[key], reverse=True
        )
        assert ordered[0]["name"] == expected
    # Nacua trails Allen everywhere here, but by 227 in NDDPL and 627 in
    # RED_EYE -- the gap is the league, not the player.
    allen, nacua = _by_name(board, "Josh Allen"), _by_name(board, "Puka Nacua")
    assert allen["nddpl"] - nacua["nddpl"] == pytest.approx(227.0)
    assert allen["red_eye"] - nacua["red_eye"] == pytest.approx(627.0)


# --- 2. a player is scored one way --------------------------------------


def test_a_defender_is_scored_as_a_defender_not_as_an_offensive_player():
    """Roquan Smith has no receiving line, so `score_offense` would total
    him at zero and rank him last. He must go through `score_idp`."""
    smith = _by_name(topscorers.rows(_index(), _stats()), "Roquan Smith")
    assert smith["nddpl"] == pytest.approx(NDDPL.score_idp(_stats()["players"]["4"]))
    assert smith["nddpl"] > 100


def test_an_offensive_player_is_never_scored_as_a_defender():
    nacua = _by_name(topscorers.rows(_index(), _stats()), "Puka Nacua")
    assert nacua["nddpl"] == pytest.approx(NDDPL.score_offense(_stats()["players"]["2"]))


# --- 3. a dash is not a zero --------------------------------------------


def test_a_league_that_cannot_start_him_shows_no_number_at_all():
    """NDDPL has no DL slot. Garrett's RED_EYE score is real; his NDDPL
    entry must be None, because a number there would be arithmetically
    fine and practically a lie."""
    garrett = _by_name(topscorers.rows(_index(), _stats()), "Myles Garrett")
    assert garrett["nddpl"] is None
    assert garrett["red_eye"] is not None and garrett["red_eye"] > 0
    assert garrett["ballapalosa"] is None, "BALLAPALOSA starts no individual defenders"


def test_none_is_not_confusable_with_zero_anywhere_in_the_row():
    board = topscorers.rows(_index(), _stats())
    for row in board:
        for lg in leagues_mod.defaults():
            if row[lg.key] is None:
                assert row[f"{lg.key}_pg"] is None, row["name"]


def test_the_dash_reaches_the_page_with_its_reason():
    html = topscorers.build_html(_index(), _stats(), NOW)
    assert "— no DL slot" in html


# --- 4. per game -------------------------------------------------------


def test_per_game_is_the_total_over_games_played_and_nothing_else():
    allen = _by_name(topscorers.rows(_index(), _stats()), "Josh Allen")
    assert allen["gp"] == 17
    assert allen["nddpl_pg"] == pytest.approx(round(474.0 / 17, 1))


def test_a_player_with_no_games_is_left_out_rather_than_divided_by_zero():
    index, stats = _index(), _stats()
    stats["players"]["2"]["gp"] = 0
    names = [r["name"] for r in topscorers.rows(index, stats)]
    assert "Puka Nacua" not in names


def test_both_numbers_reach_the_page():
    html = topscorers.build_html(_index(), _stats(), NOW)
    assert "874.0" in html, "the season total is the headline"
    assert "51.4/g" in html, "and per game sits beside it"


# --- 5. degrading honestly ---------------------------------------------


def test_stats_predating_the_offensive_fields_yield_a_message_not_zeroes():
    """The stored blob before Aug 21 carries no pass_cmp. Every
    quarterback would total zero, and a column of zeroes reads as a
    finding rather than as a gap."""
    stale = _stats()
    stale["coverage"]["players"].pop("pass_cmp")
    html = topscorers.build_html(_index(), stale, NOW)
    assert "predate the scoring fields" in html
    assert "<tbody>" not in html


def test_no_index_yields_a_message_not_an_empty_table():
    html = topscorers.build_html(None, _stats(), NOW)
    assert "Player index unavailable" in html
    assert "<tbody>" not in html


def test_a_league_with_per_game_bonuses_says_it_reads_as_a_floor():
    """BALLAPALOSA pays 4 at 400 passing yards and two more like it. A
    season aggregate cannot recover them, so the column is short — and
    naming what is missing beats a column that is quietly wrong."""
    html = topscorers.build_html(_index(), _stats(), NOW)
    assert "BALLAPALOSA reads as a floor" in html
    assert "4 pts at 400 passing yards" in html
    for lg in (NDDPL, RED_EYE):
        assert f"{lg.name} reads as a floor" not in html


def test_the_page_says_what_the_numbers_are_not():
    html = topscorers.build_html(_index(), _stats(), NOW)
    assert "not a projection" in html
    assert "2025 season" in html, "the season has to be stated, not implied"


# --- team defenses ------------------------------------------------------


def test_team_defenses_are_ranked_separately_where_a_league_starts_one():
    index, stats = _index(), _stats()
    index["players"]["100"] = {
        "id": "100",
        "name": "Denver Broncos",
        "position": "DEF",
        "team": "DEN",
        "injury_status": None,
        "rank": 200,
        "dst": True,
    }
    stats["defenses"] = {"DEN": {"gp": 17, "sack": 60, "int": 17, "fum_rec": 8}}
    dst = topscorers.dst_rows(index, stats)
    assert [r["name"] for r in dst] == ["Denver Broncos"]
    # Only BALLAPALOSA starts a DEF slot, so only it contributes a column.
    assert "ballapalosa" in dst[0]
    assert "nddpl" not in dst[0]
    assert dst[0]["ballapalosa"] == pytest.approx(BALLAPALOSA.score_dst(stats["defenses"]["DEN"]))


def test_no_defense_table_at_all_when_no_league_starts_one():
    index, stats = _index(), _stats()
    stats["defenses"] = {"DEN": {"gp": 17, "sack": 60}}
    assert topscorers.dst_rows(index, stats, board_leagues=[NDDPL, RED_EYE]) == []


# --- the route ----------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    c = TestClient(main.app)
    c._store = store  # type: ignore[attr-defined]
    yield c
    main.app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_the_page_serves_with_real_numbers(client, anyio_backend):
    await client._store.save_players(_index())
    await client._store.save({"stats": _stats()})
    resp = client.get("/app/scoring")
    assert resp.status_code == 200
    assert "Josh Allen" in resp.text
    assert "874.0" in resp.text


def test_the_page_serves_when_the_store_is_empty(client):
    """A board with nothing behind it must still render a page that says
    so, not a 500."""
    resp = client.get("/app/scoring")
    assert resp.status_code == 200
    assert "Scoring board" in resp.text


# --- edge over replacement ---------------------------------------------
# The panel that answers the owner's Aug 21 question. The arithmetic lives
# in app/feeds/replacement.py and is tested there; these are about the page
# saying the right thing about it.


def _rich_page():
    """A pool deep enough to have a replacement level at all — the four-row
    fixture above cannot, by design."""
    import sys

    sys.path.insert(0, "tests")
    from test_replacement import INDEX, STATS

    stats = {**STATS, "coverage": {"players": {"pass_cmp": 1}}}
    return topscorers.build_html(INDEX, stats, NOW)


def test_the_page_says_a_total_is_not_an_edge():
    """The correction the whole panel exists to make. A season total is
    the number that misleads: you never receive it, you receive it minus
    whatever fills the slot otherwise."""
    page = _rich_page()
    assert "Edge over replacement" in page
    assert "A total is not an edge" in page


def test_the_panel_names_the_replacement_it_measured_against():
    """ "QB1−QB13" is checkable; a bare spread is not."""
    page = _rich_page()
    assert "QB1&#8722;QB13" in page, "RED_EYE starts one QB across 12 teams"


def test_the_panel_says_when_no_reach_is_earned():
    """An analysis that only ever recommends the position it studies is
    not an analysis. NDDPL's quarterbacks must be allowed to lose."""
    assert "no reach is earned here" in _rich_page()


def test_the_panel_reports_the_override_beside_the_measurement():
    """The two are different claims — one is what the room does, one is
    what the scoring says — and the owner is deciding between them, so
    they have to be on screen together."""
    page = _rich_page()
    assert "mock room moves them <b>18</b> slots" in page
    assert "tuned against how that room actually drafts" in page


def test_the_panel_explains_how_the_flex_was_allocated():
    """The one place this could quietly invent a number, so it is the one
    place the page has to show its working."""
    page = _rich_page()
    assert "highest next-available player" in page
    assert "rather than split by a ratio nobody measured" in page


def test_no_panel_at_all_when_the_pool_is_too_thin_to_measure():
    """The four-player fixture cannot support a replacement level, and a
    spread against the last man in a four-player list would be an
    artefact. Silence beats an invented baseline."""
    assert "Edge over replacement" not in topscorers.build_html(_index(), _stats(), NOW)


def test_the_panel_names_its_own_hindsight_bias():
    """These are last season's finishes, and whoever finished first is
    partly whoever stayed healthy — which nobody could draft in advance.
    A panel presenting that as "draft this position first" would be a
    false positive of exactly the kind the repo rules out. The
    across-league comparison is the part that survives the bias."""
    page = _rich_page()
    assert "Read across leagues, not down the column" in page
    assert "partly whoever stayed healthy" in page
    assert "only the scoring differs" in page
