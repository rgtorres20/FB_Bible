"""The IDP draft board.

The contract: defenders are scored with each league's *verified* settings
(docs/LEAGUES.md) -- NDDPL pays 3/sack and 2/INT, RED_EYE 2/sack and
3/INT, return yardage at 20 and 10 yds/pt respectively; NDDPL has no DL
slot, so a DL shows an explicit dash there instead of a fake number; and
a store whose stats predate the IDP fields yields an honest message,
never an empty table pretending no defender matters.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds import idp
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
            "1": {
                "id": "1",
                "name": "Roquan Smith",
                "position": "LB",
                "team": "BAL",
                "injury_status": None,
                "rank": 400,
                "idp": "LB",
            },
            "2": {
                "id": "2",
                "name": "Terrion Arnold",
                "position": "CB",
                "team": "DET",
                "injury_status": "Questionable",
                "rank": 700,
                "idp": "DB",
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
                "name": "Puka Nacua",
                "position": "WR",
                "team": "LAR",
                "injury_status": None,
                "rank": 5,
            },
        },
    }


def _stats() -> dict:
    return {
        "v": 2,
        "coverage": {"players": {"idp_tkl_solo": 1124}},
        "players": {
            # Roquan: 100 solo + 40 ast (0.5) + 2 sacks + 1 int + 4 pd + 1 ff
            #   NDDPL: 100 + 20 + 6 + 2 + 4 + 2 = 134
            #   RED_EYE: 100 + 20 + 4 + 3 + 4 + 2 = 133
            "1": {
                "gp": 17,
                "idp_tkl_solo": 100,
                "idp_tkl_ast": 40,
                "idp_sack": 2,
                "idp_int": 1,
                "idp_pass_def": 4,
                "idp_ff": 1,
            },
            # Arnold: 60 solo + 12 pd + 2 int + 40 int return yds
            #   NDDPL: 60 + 12 + 4 + 2 = 78 ;  RED_EYE: 60 + 12 + 6 + 4 = 82
            "2": {
                "gp": 16,
                "idp_tkl_solo": 60,
                "idp_pass_def": 12,
                "idp_int": 2,
                "idp_int_ret_yd": 40,
            },
            # Garrett: 40 solo + 14 sacks -> NDDPL slot does not exist (DL)
            #   RED_EYE: 40 + 28 = 68
            "3": {"gp": 17, "idp_tkl_solo": 40, "idp_sack": 14},
            # Nacua has offense stats only: never an IDP row.
            "4": {"gp": 15, "rec_tgt": 140},
        },
    }


# --- scoring ----------------------------------------------------------------


def test_scores_follow_each_leagues_verified_settings():
    board = {r["name"]: r for r in idp.rows(_index(), _stats())}
    assert board["Roquan Smith"]["nddpl"] == 134.0
    assert board["Roquan Smith"]["red_eye"] == 133.0
    assert board["Terrion Arnold"]["nddpl"] == 78.0
    assert board["Terrion Arnold"]["red_eye"] == 82.0


def test_a_dl_gets_no_nddpl_number_because_no_slot_exists():
    board = {r["name"]: r for r in idp.rows(_index(), _stats())}
    garrett = board["Myles Garrett"]
    assert garrett["nddpl"] is None
    assert garrett["red_eye"] == 68.0
    assert "nddpl_rank" not in garrett
    assert garrett["red_eye_rank"] == "DL1"


def test_offense_never_appears_and_ranks_count_within_group():
    board = idp.rows(_index(), _stats())
    assert all(r["name"] != "Puka Nacua" for r in board)
    roquan = next(r for r in board if r["name"] == "Roquan Smith")
    assert roquan["nddpl_rank"] == "LB1"
    assert roquan["red_eye_rank"] == "LB1"


# --- the page ----------------------------------------------------------------


def test_page_renders_both_league_columns_and_the_dl_dash():
    page = idp.build_html(_index(), _stats(), NOW)
    assert "NDDPL '25" in page and "RED_EYE '25" in page
    assert "no DL slot" in page
    assert "not a projection" in page


def test_page_is_honest_when_stats_predate_the_idp_fields():
    page = idp.build_html(_index(), {"coverage": {"players": {"rec_tgt": 534}}}, NOW)
    assert "predate the IDP fields" in page
    assert "<table" not in page


# --- the route ----------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "sync_token", "secret-token", raising=False)
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    yield TestClient(main.app), store
    main.app.dependency_overrides.clear()


async def test_route_serves_the_scored_board(client):
    c, store = client
    await store.save_players(_index())
    await store.save({"items": [], "stats": _stats()})
    page = c.get("/app/idp").text
    assert "Roquan Smith" in page and "LB1" in page
