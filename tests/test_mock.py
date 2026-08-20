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


def test_offense_joins_the_ten_team_adp_and_excludes_team_defense():
    pool = mock.offense_pool(_index(), _adp(), _capsules())
    by_name = {p["name"]: p for p in pool}
    # Both leagues are 10-team: the 10-team column is the market number.
    assert by_name["Puka Nacua"]["adp"] == 4.5
    # A player FFC has not seen gets null, never a fake number.
    assert by_name["Josh Allen"]["adp"] is None
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
