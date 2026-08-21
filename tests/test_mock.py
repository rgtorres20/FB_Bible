"""The mock draft room.

The contract: the server assembles the pool from the same live numbers as
every other surface -- offense joined to the 10-team ADP (both leagues are
10-team), defenders from the IDP board's own league-scored rows, capsules
attached where the hourly job drafted one -- and the page is honest about
what the simulation is: labelled machine picks over stated inputs, never
"the AI predicted your leaguemates".
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds import mock
from app.feeds import players as players_mod
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def _index() -> dict:
    return {
        "v": players_mod.INDEX_VERSION,
        "by_name": {},
        "surnames": {},
        "players": {
            "4": {
                "id": "4",
                "name": "Puka Nacua",
                "position": "WR",
                "team": "LAR",
                "injury_status": None,
                "rank": 5,
            },
            "5": {
                "id": "5",
                "name": "Josh Allen",
                "position": "QB",
                "team": "BUF",
                "injury_status": None,
                "rank": 20,
            },
            "6": {
                "id": "6",
                "name": "Ravens D/ST",
                "position": "DEF",
                "team": "BAL",
                "injury_status": None,
                "rank": 150,
            },
            "7": {
                "id": "7",
                "name": "Justin Tucker",
                "position": "K",
                "team": "BAL",
                "injury_status": None,
                "rank": 999,
            },
            "1": {
                "id": "1",
                "name": "Roquan Smith",
                "position": "LB",
                "team": "BAL",
                "injury_status": None,
                "rank": 400,
                "idp": "LB",
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
        },
    }


def _adp() -> dict:
    return {
        "players": [
            {
                "name": "Puka Nacua",
                "adp": 4.9,
                "position": "WR",
                "team": "LAR",
                "bye": 8,
                "sizes": {"10": 4.5, "12": 5.2},
            }
        ]
    }


def _stats() -> dict:
    return {
        "v": 2,
        "coverage": {"players": {"idp_tkl_solo": 1124}},
        "players": {
            "1": {
                "gp": 17,
                "idp_tkl_solo": 100,
                "idp_tkl_ast": 40,
                "idp_sack": 2,
                "idp_int": 1,
                "idp_pass_def": 4,
                "idp_ff": 1,
            },
            "3": {"gp": 17, "idp_tkl_solo": 40, "idp_sack": 14},
        },
    }


def _capsules() -> dict:
    return {"4": {"text": "Target hog; halved yardage still leaves</script> him WR1."}}


# --- the pool ----------------------------------------------------------------


def test_offense_joins_both_adp_sizes_and_excludes_team_defense():
    pool = mock.offense_pool(_index(), _adp(), _capsules())
    by_name = {p["name"]: p for p in pool}
    # Both FFC size columns travel: NDDPL drafts against the 10-team
    # market, RED_EYE against the 12-team one (owner correction Aug 20).
    assert by_name["Puka Nacua"]["a10"] == 4.5
    assert by_name["Puka Nacua"]["a12"] == 5.2
    # A player FFC has not seen gets null, never a fake number.
    assert by_name["Josh Allen"]["a10"] is None
    # Team defenses are not rosterable in either league.
    assert "Ravens D/ST" not in by_name
    # Defenders live in their own pool.
    assert "Roquan Smith" not in by_name


def test_kickers_are_pulled_in_when_the_top_slice_has_none(monkeypatch):
    monkeypatch.setattr(mock, "OFFENSE_TOP", 2)
    pool = mock.offense_pool(_index(), _adp(), {})
    names = [p["name"] for p in pool]
    assert "Justin Tucker" in names  # rank 999, far past the slice


def test_defense_pool_carries_each_leagues_scored_totals():
    pool = {p["name"]: p for p in mock.defense_pool(_index(), _stats(), {})}
    assert pool["Roquan Smith"]["nddpl"] == 134.0
    assert pool["Roquan Smith"]["red_eye"] == 133.0
    # A DL has no NDDPL slot: null there, scored for RED_EYE.
    assert pool["Myles Garrett"]["nddpl"] is None
    assert pool["Myles Garrett"]["red_eye"] == 68.0


# --- the page ----------------------------------------------------------------


def test_page_embeds_the_pool_and_states_what_the_simulation_is():
    page = mock.build_html(_index(), _adp(), _stats(), _capsules(), NOW)
    assert "FB_MOCK" in page
    assert "Simulated picks are labelled" in page
    assert "not a" in page and "prediction" in page
    assert "Autopilot" in page
    assert "AI angle" in page  # capsules render labelled, never as fact
    # A "</script>" inside a capsule must not close the data script tag.
    assert "leaves</script>" not in page
    assert "leaves<\\/script>" in page
    # The room wears the app's skin: token blocks for every mode, and it
    # follows (and writes back) the page's own stored theme.
    assert 'data-theme="titans"' in page and 'data-theme="cowboys"' in page
    assert "ww_theme" in page
    # RED_EYE drafts as a 12-team room (owner correction Aug 20). The
    # config is generated from app/leagues.py into the JSON payload now,
    # so it travels as data rather than as a literal in the engine.
    assert '"teams":12' in page
    # The clickable board print-out with hover details.
    assert "Draft board" in page and "openBoard" in page


def test_page_is_honest_without_an_index():
    page = mock.build_html(None, None, None, None, NOW)
    assert "Player index unavailable" in page
    assert "FB_MOCK" not in page


# --- the route ----------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "sync_token", "secret-token", raising=False)
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    yield TestClient(main.app), store
    main.app.dependency_overrides.clear()


async def test_route_serves_the_room(client):
    c, store = client
    await store.save_players(_index())
    await store.save(
        {
            "items": [],
            "adp": {"state": _adp()},
            "stats": _stats(),
            "capsules": _capsules(),
        }
    )
    page = c.get("/app/mock").text
    assert "Mock draft room" in page
    assert "Roquan Smith" in page and "Puka Nacua" in page


def test_the_engine_config_is_generated_not_restated():
    """The room's JS league object used to be a hand-kept copy of the
    Python dicts in feeds/idp.py. It is generated from app/leagues.py
    now, and this pins it to exactly what shipped hardcoded -- the
    refactor has to be invisible to the draft."""
    from app import leagues as leagues_mod

    cfg = {lg.name: mock.league_config(lg) for lg in mock.ROOM_LEAGUES}
    assert set(cfg) == {"NDDPL", "RED_EYE", "BALLAPALOSA"}
    assert cfg["NDDPL"]["slots"] == [
        *"QB RB RB RB WR WR WR WR TE K".split(),
        *("DB",) * 4,
        *("LB",) * 4,
        *("BN",) * 8,
    ]
    assert cfg["NDDPL"]["defGroups"] == {"DB": 1, "LB": 1}  # no DL slot at all
    assert cfg["NDDPL"]["qbBoost"] == 10 and cfg["NDDPL"]["adpKey"] == "a10"
    assert cfg["RED_EYE"]["slots"] == [
        *"QB RB RB WR WR WR TE FLX K".split(),
        *("D",) * 4,
        *("DB",) * 4,
        *("BN",) * 8,
    ]
    assert cfg["RED_EYE"]["defGroups"] == {"DB": 1, "DL": 1, "LB": 1}
    assert cfg["RED_EYE"]["qbBoost"] == 18 and cfg["RED_EYE"]["adpKey"] == "a12"
    # The ADP label names the column actually read, not the room size --
    # a 14-team league drafts against FFC's 12-team board and says so.
    assert cfg["RED_EYE"]["adpLabel"] == "ADP 12tm"
    fourteen = leagues_mod.blank("Big", 14)
    assert mock.league_config(fourteen)["adpLabel"] == "ADP 12tm"
    # BALLAPALOSA is the team-defense league: one DEF slot, no IDP.
    assert cfg["BALLAPALOSA"]["dstSlots"] == 1
    assert cfg["BALLAPALOSA"]["defGroups"] == {}
    assert cfg["NDDPL"]["dstSlots"] == 0 and cfg["RED_EYE"]["dstSlots"] == 0


def test_a_market_scoring_league_makes_no_qb_premium_claim():
    """The pick reason quoting "6-pt pass TDs" is true of the owner's two
    leagues and of nobody else's. Generated from the settings, so a
    league at market scoring says nothing rather than something false."""
    from app import leagues as leagues_mod

    assert mock.qb_note(leagues_mod.NDDPL) == "6-pt pass TDs, 20 pass yds/pt"
    assert mock.qb_note(leagues_mod.RED_EYE).endswith("1/completion")
    assert mock.qb_note(leagues_mod.blank()) == ""


def test_the_room_refuses_to_rank_defenses_from_a_partial_ladder():
    """Consistent with the board: an order built from an incomplete
    points-allowed ladder is still an order, and the room would present
    it as one. The DEF slot stays visibly empty and the caption says why."""
    from dataclasses import replace

    from app import leagues as leagues_mod

    league = replace(
        leagues_mod.blank("D/ST League", 10),
        slots=("QB", "RB", "WR", "TE", "K", "DEF", "BN"),
        dst=dict(leagues_mod.DEFAULT_DST),
        dst_pa=dict(leagues_mod.DEFAULT_DST_PA),
    )
    index = _index()
    index["players"]["DET"] = {
        "id": "DET",
        "name": "Detroit Lions",
        "position": "DEF",
        "team": "DET",
        "rank": None,
        "dst": True,
    }
    state = _stats()
    state["defenses"] = {"DET": {"gp": 17, "sack": 49, "pts_allow_21_27": 8}}
    state["coverage"]["defenses"] = 1
    state["coverage"]["defense_pa_complete"] = 0  # 8 of 17 games banded

    assert mock.dst_pool(index, state, None, board_leagues=[league]) == []
    page = mock.build_html(index, _adp(), state, None, NOW, board_leagues=[league])
    assert "team defenses are not on the board yet" in page

    # With the ladder complete, the same room drafts them and says so.
    state["defenses"]["DET"].update({"pts_allow_21_27": 17})
    state["coverage"]["defense_pa_complete"] = 1
    assert len(mock.dst_pool(index, state, None, board_leagues=[league])) == 1
    page = mock.build_html(index, _adp(), state, None, NOW, board_leagues=[league])
    assert "1 team defenses" in page
    assert "not on the board yet" not in page


def test_the_draft_board_is_a_real_page_so_refresh_works():
    """It used to be written into an about:blank popup, which gave that
    tab no document of its own — so a reload went white (owner, Aug 21).
    Now the room hands the board off through localStorage and opens a
    real same-origin URL."""
    from fastapi.testclient import TestClient

    from app import main as main_mod

    room = mock.build_html(_index(), _adp(), _stats(), _capsules(), NOW)
    assert "window.open('/app/mock/board', '_blank')" in room
    assert "localStorage.setItem(BOARD_KEY" in room
    # The old failure mode must not come back.
    assert "w.document.write" not in room

    page = TestClient(main_mod.app).get("/app/mock/board")
    assert page.status_code == 200
    assert "fb_mock_board" in page.text
    # Nothing about anyone's draft is stored or served: the page is a
    # reader for what the visitor's own browser saved.
    assert "No draft board saved on this device yet" in page.text


def test_the_board_keeps_its_title_and_round_column_in_view():
    """On a phone the grid is taller and wider than the screen, and
    scrolling took the league name, the seat and the "this is a
    simulation" line away together (owner, Aug 21)."""
    room = mock.build_html(_index(), _adp(), _stats(), _capsules(), NOW)
    assert ".bhead{position:sticky" in room
    assert "td.rnd,th.rnd{position:sticky" in room
    assert "<tr><th class='rnd'>" in room


def test_pick_details_are_reachable_without_a_mouse():
    """Hover-only tooltips are invisible on a phone, which is where the
    board is most often read."""
    room = mock.build_html(_index(), _adp(), _stats(), _capsules(), NOW)
    assert "td.cell.tapped .tip{display:block}" in room
    assert "tapped" in mock.BOARD_JS and "addEventListener('click'" in mock.BOARD_JS
