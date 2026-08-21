"""League settings (/app/leagues) — a user's own league, their own numbers.

The contract: full custom scoring, not presets; validation refuses rather
than quietly repairs, because a clamped league would make every number
downstream a confident lie about somebody's draft; the built-in two stay
read-only and their *tuned* QB boost never travels into a copy; and a
saved league actually reaches the boards — the IDP rankings and the mock
room score with it, which is the whole reason to type it in.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import leagues as leagues_mod
from app import main
from app.config import get_settings
from app.feeds.store import FileFeedStore
from app.routes import access as access_route
from app.routes import feeds as feeds_route

# A whole league in form fields: 12-team, 4-point passing TDs (market),
# half PPR, and 4 a sack — deliberately unlike either built-in.
FORM = {
    "key": "",
    "name": "Work League",
    "teams": "12",
    "slot_QB": "1",
    "slot_RB": "2",
    "slot_WR": "3",
    "slot_TE": "1",
    "slot_FLX": "1",
    "slot_K": "1",
    "slot_DL": "0",
    "slot_LB": "2",
    "slot_DB": "2",
    "slot_D": "0",
    "slot_BN": "6",
    "ppr": "0.5",
    "pass_td": "4",
    "pass_yds_per_pt": "25",
    "pass_completion": "0",
    "rec_yds_per_pt": "10",
    "rush_yds_per_pt": "10",
    "idp_idp_tkl_solo": "1",
    "idp_idp_tkl_ast": "0.5",
    "idp_idp_sack": "4",
    "idp_idp_int": "3",
    "idp_idp_ff": "2",
    "idp_idp_fum_rec": "2",
    "idp_idp_def_td": "6",
    "idp_idp_safe": "2",
    "idp_idp_pass_def": "1",
    "idp_idp_blk_kick": "2",
    "idp_ret_yds_per_pt": "25",
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    s = get_settings()
    monkeypatch.setattr(s, "app_auth", True, raising=False)
    monkeypatch.setattr(s, "owner_email", "owner@example.com", raising=False)
    monkeypatch.setattr(s, "app_owner_code", "open-sesame", raising=False)
    monkeypatch.setattr(s, "session_secret", "unit-test-secret", raising=False)
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    monkeypatch.setattr(access_route, "build_feed_store", lambda _s: store)
    yield TestClient(main.app), store
    main.app.dependency_overrides.clear()


def _signed_in(client) -> TestClient:
    c, _ = client
    c.post("/login", data={"email": "owner@example.com", "code": "open-sesame"})
    return c


def _save(c: TestClient, **overrides):
    return c.post("/app/leagues/save", data={**FORM, **overrides}, follow_redirects=True)


# --- identity ---------------------------------------------------------------


def test_the_page_needs_to_know_whose_leagues_to_show(client):
    c, _ = client
    r = c.get("/app/leagues", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303  # the gate, before the page even runs


def test_the_built_ins_are_listed_read_only(client):
    c = _signed_in(client)
    page = c.get("/app/leagues").text
    assert "NDDPL" in page and "RED_EYE" in page
    assert "owner's, verified" in page
    assert "Read-only" in page


# --- saving -----------------------------------------------------------------


async def test_a_saved_league_keeps_every_number_it_was_given(client):
    c = _signed_in(client)
    _, store = client
    _save(c)
    stored = leagues_mod.user_leagues(await store.load_user("owner@example.com"))
    assert len(stored) == 1
    lg = stored[0]
    assert lg.name == "Work League"
    assert lg.teams == 12
    assert lg.ppr == 0.5
    assert lg.idp["idp_sack"] == 4.0
    assert lg.idp_ret_yds_per_pt == 25.0
    # 1 QB + 2 RB + 3 WR + TE + FLX + K + 2 LB + 2 DB + 6 BN
    assert lg.rounds == 19
    assert lg.idp_groups == frozenset({"LB", "DB"})


def test_the_page_says_what_the_settings_imply(client):
    """The editor's job is to show the advice changing, not to take it on
    faith: a market-scoring league gets told so out loud."""
    c = _signed_in(client)
    page = _save(c).text
    assert "QBs score at market" in page
    assert "12</b> teams" in page and "19</b> rounds" in page
    assert "12-team</b> board" in page  # FFC column follows the room size


def test_a_qb_premium_league_is_told_how_far_it_moves_quarterbacks(client):
    c = _signed_in(client)
    page = _save(c, name="Superflex-ish", pass_td="6", pass_yds_per_pt="20").text
    assert "above market for a starting QB" in page
    assert "draft slots" in page


# --- validation refuses rather than repairs ---------------------------------


def test_an_impossible_room_size_is_refused_not_clamped(client):
    c = _signed_in(client)
    page = _save(c, teams="40").text
    assert "draft air" in page
    assert "Work League" not in page.split("<div class='err'>")[1][:400]


def test_a_league_with_no_starters_is_refused(client):
    c = _signed_in(client)
    fields = {k: ("0" if k.startswith("slot_") else v) for k, v in FORM.items()}
    r = c.post("/app/leagues/save", data=fields, follow_redirects=True)
    assert "at least one starting slot" in r.text


def test_starting_defenders_you_score_nothing_is_refused(client):
    """An IDP league with no IDP values would rank every defender at zero
    and present that as a ranking. Better to say so."""
    c = _signed_in(client)
    zeros = {k: "0" for k in FORM if k.startswith("idp_")}
    r = c.post("/app/leagues/save", data={**FORM, **zeros}, follow_redirects=True)
    assert "rank everyone at zero" in r.text


def test_a_yards_per_point_divisor_cannot_be_zero(client):
    c = _signed_in(client)
    assert "divisor" in _save(c, pass_yds_per_pt="0").text


def test_a_league_needs_a_name(client):
    c = _signed_in(client)
    assert "needs a name" in _save(c, name="   ").text


# --- copying, editing, deleting ---------------------------------------------


def test_copying_a_built_in_never_carries_its_tuned_qb_boost(client):
    """10 and 18 were fitted to how the owner's own rooms draft. In
    somebody else's copy that number would be a borrowed judgement, so
    the copy derives its own from the scoring."""
    c = _signed_in(client)
    page = c.post("/app/leagues/copy", data={"from": "red_eye"}, follow_redirects=True).text
    assert "RED_EYE (mine)" in page
    assert "tuned against how this room actually drafts" not in page.split("RED_EYE (mine)")[1]


def test_editing_updates_in_place_rather_than_adding(client):
    c = _signed_in(client)
    _save(c)
    key = "u_work_league"
    page = _save(c, key=key, name="Work League", teams="10").text
    assert page.count("yours</span>") == 1
    assert "10</b> teams" in page


def test_deleting_removes_it(client):
    c = _signed_in(client)
    _save(c)
    page = c.post("/app/leagues/delete", data={"key": "u_work_league"}, follow_redirects=True).text
    assert "Work League" not in page


def test_the_league_cap_is_stated_not_silently_enforced(client):
    c = _signed_in(client)
    from app.routes.leaguecfg import MAX_LEAGUES

    for i in range(MAX_LEAGUES):
        _save(c, name=f"League {i}")
    page = _save(c, name="One too many").text
    assert f"{MAX_LEAGUES}-league cap" in page


# --- the payoff: a saved league reaches the boards ---------------------------


async def _seed_pool(store) -> None:
    """Just enough of a live pool that the room renders rather than
    showing its honest "index unavailable" page."""
    from app.feeds import players as players_mod

    await store.save_players(
        {
            "v": players_mod.INDEX_VERSION,
            "by_name": {},
            "surnames": {},
            "players": {
                "1": {"id": "1", "name": "Puka Nacua", "position": "WR", "team": "LAR", "rank": 5},
                "2": {
                    "id": "2",
                    "name": "Roquan Smith",
                    "position": "LB",
                    "team": "BAL",
                    "rank": 400,
                    "idp": "LB",
                },
            },
        }
    )
    await store.save(
        {
            "items": [],
            "stats": {
                "v": 3,
                "coverage": {
                    "players": {"idp_tkl_solo": 1},
                    "defenses": 1,
                    "defense_pa_complete": 1,
                },
                "players": {"2": {"gp": 17, "idp_tkl_solo": 100, "idp_tkl_ast": 40}},
                # Detroit's real '25 line; the ladder accounts for all 17
                # games, which is what the board gates on.
                "defenses": {
                    "DET": {
                        "gp": 17,
                        "sack": 49,
                        "int": 13,
                        "fum_rec": 6,
                        "def_st_td": 1,
                        "safe": 1,
                        "fg_blkd": 2,
                        "pts_allow": 411,
                        "pts_allow_7_13": 2,
                        "pts_allow_14_20": 2,
                        "pts_allow_21_27": 8,
                        "pts_allow_28_34": 4,
                        "pts_allow_35p": 1,
                    }
                },
            },
        }
    )


async def test_a_saved_league_appears_in_the_mock_room(client):
    c = _signed_in(client)
    _, store = client
    await _seed_pool(store)
    _save(c)
    page = c.get("/app/mock").text
    assert "Work League" in page
    assert '"teams":12' in page
    # Derived, not inherited: the room must not carry NDDPL's tuned boost
    # into a league that scores QBs at market.
    assert '"qbNote":""' in page


def test_a_stranger_still_sees_only_the_built_ins(client):
    """One user's league is not another's. The mock room is served per
    request, so this is the check that the leagues follow the sign-in."""
    c = _signed_in(client)
    _save(c)
    c.post("/logout")
    c.post("/login", data={"email": "owner@example.com", "code": "wrong"})
    assert c.get("/app/mock", follow_redirects=False).status_code in (303, 401)


async def test_a_saved_league_gets_its_own_column_on_the_idp_board(client):
    """The payoff that matters most: 4 a sack is a different board from
    3 a sack, and this is where the user sees their own ranking rather
    than the owner's."""
    c = _signed_in(client)
    _, store = client
    await _seed_pool(store)
    _save(c)
    page = c.get("/app/idp").text
    assert "Work League '25" in page
    assert "NDDPL '25" in page and "RED_EYE '25" in page
    assert "Work League</b> pays 4/sack &amp; 3/INT" in page


async def test_a_league_that_starts_no_defenders_adds_no_idp_column(client):
    """An all-offense league has nothing to say about defenders. It gets
    left off the board rather than given a column of numbers nobody in
    that league can use."""
    c = _signed_in(client)
    _, store = client
    await _seed_pool(store)
    offense_only = {
        k: ("0" if k.startswith(("slot_LB", "slot_DB", "idp_")) else v) for k, v in FORM.items()
    }
    c.post(
        "/app/leagues/save", data={**offense_only, "name": "Offense Only"}, follow_redirects=True
    )
    page = c.get("/app/idp").text
    assert "Offense Only '25" not in page
    assert "NDDPL '25" in page


# --- team defense -----------------------------------------------------------
#
# Owner, Aug 21: "some leagues do Team DEF not just IDP." A DEF slot is a
# different thing from the IDP slots above -- a whole team scored as one
# unit -- and a league can start either, both, or neither.

DST_FORM = {
    **FORM,
    "name": "D/ST League",
    "slot_DEF": "1",
    "slot_LB": "0",
    "slot_DB": "0",
    **{f"idp_{k}": "0" for k, _ in __import__("app.leagues", fromlist=["x"]).IDP_FIELDS},
    "idp_ret_yds_per_pt": "0",
    "dst_sack": "1",
    "dst_int": "2",
    "dst_fum_rec": "2",
    "dst_def_st_td": "6",
    "dst_safe": "2",
    "dst_fg_blkd": "2",
    "dst_pts_allow_0": "10",
    "dst_pts_allow_1_6": "7",
    "dst_pts_allow_7_13": "4",
    "dst_pts_allow_14_20": "1",
    "dst_pts_allow_28_34": "-1",
    "dst_pts_allow_35p": "-4",
}


async def test_a_team_defense_league_saves_its_own_dst_scoring(client):
    c = _signed_in(client)
    _, store = client
    c.post("/app/leagues/save", data=DST_FORM, follow_redirects=True)
    lg = leagues_mod.user_leagues(await store.load_user("owner@example.com"))[0]
    assert lg.starts_dst
    assert not lg.starts_idp  # a DEF slot is not an IDP slot
    assert lg.dst["sack"] == 1.0 and lg.dst["def_st_td"] == 6.0
    assert lg.dst_pa["pts_allow_0"] == 10.0
    assert lg.dst_pa["pts_allow_35p"] == -4.0
    # A zero tier is stored as absent, not as a zero that reads as a
    # deliberate setting -- 21-27 was left blank on the form.
    assert "pts_allow_21_27" not in lg.dst_pa


def test_starting_a_defense_you_score_nothing_is_refused(client):
    """All 32 defenses would rank identically at zero, and a flat
    ranking presented as a ranking is the false positive this repo
    will not ship."""
    c = _signed_in(client)
    zeros = {k: "0" for k in DST_FORM if k.startswith("dst_")}
    r = c.post("/app/leagues/save", data={**DST_FORM, **zeros}, follow_redirects=True)
    assert "rank identically at zero" in r.text


def test_the_editor_offers_yahoo_s_dst_defaults_on_a_new_league(client):
    """Fifteen numbers typed from memory is how a league gets entered
    wrong. Every one of them is still editable."""
    c = _signed_in(client)
    page = c.get("/app/leagues").text
    assert "Team defense (D/ST)" in page
    assert "name='dst_pts_allow_0' value='10.0'" in page
    assert "name='dst_def_st_td' value='6.0'" in page
    # Yards allowed exists but stays folded away: the data is there and
    # some leagues score it, but nine always-zero boxes would bury the
    # ladder nearly every league does use.
    assert "Yards allowed" in page and "dst_yds_allow_550p" in page


def test_the_page_says_what_a_def_slot_implies(client):
    c = _signed_in(client)
    page = c.post("/app/leagues/save", data=DST_FORM, follow_redirects=True).text
    assert "1</b> team D/ST slot" in page
    assert "10 for a shutout" in page


async def test_a_saved_dst_league_gets_a_team_defense_table(client):
    c = _signed_in(client)
    _, store = client
    await _seed_pool(store)
    c.post("/app/leagues/save", data=DST_FORM, follow_redirects=True)
    page = c.get("/app/idp").text
    assert "Team defenses" in page
    assert "D/ST League</b> pays" in page
    # The owner's two start no team defense, so they contribute no
    # column to it -- and keep their own IDP columns.
    assert "NDDPL '25" in page and "RED_EYE '25" in page


async def test_a_saved_dst_league_drafts_defenses_in_the_mock_room(client):
    c = _signed_in(client)
    _, store = client
    await _seed_pool(store)
    c.post("/app/leagues/save", data=DST_FORM, follow_redirects=True)
    page = c.get("/app/mock").text
    assert "D/ST League" in page
    assert '"dstSlots":1' in page
    # The built-ins keep zero DEF slots, so nothing about their draft moves.
    assert page.count('"dstSlots":0') == 2
