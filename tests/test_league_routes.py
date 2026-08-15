"""League endpoints, end to end with Yahoo mocked.

Until now these were only tested for the 401-when-unlinked case, so nothing
proved a successful Yahoo response actually survives parsing and reaches the
caller in the shape the browser client expects.
"""

import time

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app import main
from app.config import YAHOO_API_BASE, Settings
from app.deps import get_yahoo
from app.store.base import TokenSet
from app.yahoo import YahooClient, parse

SETTINGS = Settings(
    yahoo_client_id="id",
    yahoo_client_secret="secret",
    yahoo_redirect_uri="https://example.com/auth/yahoo/callback",
)
LEAGUE = "nfl.l.192426"


class MemoryStore:
    def __init__(self):
        self._t = TokenSet(access_token="good", refresh_token="r", expires_at=time.time() + 3600)

    async def get(self, key):
        return self._t

    async def put(self, key, tokens):
        self._t = tokens

    async def delete(self, key):
        self._t = None


@pytest.fixture
def client():
    main.app.dependency_overrides[get_yahoo] = lambda: YahooClient(SETTINGS, MemoryStore(), "owner")
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


DRAFT_JSON = {
    "fantasy_content": {
        "league": {
            "draft_results": {
                "0": {
                    "draft_result": {
                        "pick": "2",
                        "round": "1",
                        "team_key": "t2",
                        "player_key": "nfl.p.2",
                    }
                },
                "1": {
                    "draft_result": {
                        "pick": "1",
                        "round": "1",
                        "team_key": "t1",
                        "player_key": "nfl.p.1",
                    }
                },
                "count": 2,
            }
        }
    }
}

ROSTER_JSON = {
    "fantasy_content": {
        "team": {
            "roster": {
                "players": {
                    "0": {
                        "player": [
                            [
                                {"player_key": "nfl.p.100"},
                                {"name": {"full": "Puka Nacua"}},
                                {"editorial_team_abbr": "LAR"},
                                {"display_position": "WR"},
                                {"status": "Q"},
                                {"bye_weeks": {"week": "6"}},
                            ],
                            {"selected_position": {"position": "WR"}},
                        ]
                    },
                    "count": 1,
                }
            }
        }
    }
}


@respx.mock
def test_draft_returns_picks_in_order(client):
    respx.get(url__startswith=f"{YAHOO_API_BASE}/league/{LEAGUE}/draftresults").mock(
        return_value=httpx.Response(200, json=DRAFT_JSON)
    )

    body = client.get(f"/api/leagues/{LEAGUE}/draft").json()

    assert body["league_key"] == LEAGUE
    assert [p["pick"] for p in body["picks"]] == ["1", "2"]


@respx.mock
def test_roster_returns_players_with_status(client):
    respx.get(url__startswith=f"{YAHOO_API_BASE}/team/{LEAGUE}.t.4/roster").mock(
        return_value=httpx.Response(200, json=ROSTER_JSON)
    )

    body = client.get(f"/api/teams/{LEAGUE}.t.4/roster").json()

    assert body["week"] is None
    assert body["players"][0]["name"] == "Puka Nacua"
    assert body["players"][0]["status"] == "Q"
    assert body["players"][0]["bye_week"] == "6"


@respx.mock
def test_roster_passes_the_week_through_to_yahoo(client):
    route = respx.get(url__startswith=f"{YAHOO_API_BASE}/team/{LEAGUE}.t.4/roster").mock(
        return_value=httpx.Response(200, json=ROSTER_JSON)
    )

    client.get(f"/api/teams/{LEAGUE}.t.4/roster?week=3")

    assert ";week=3" in str(route.calls[0].request.url)


@respx.mock
def test_a_yahoo_outage_becomes_502_not_500(client):
    """The caller should be able to tell "Yahoo is down" from "we are broken"."""
    respx.get(url__startswith=f"{YAHOO_API_BASE}/league/{LEAGUE}/draftresults").mock(
        return_value=httpx.Response(503, text="maintenance")
    )

    response = client.get(f"/api/leagues/{LEAGUE}/draft")

    assert response.status_code == 502


@respx.mock
def test_raw_passthrough_reaches_an_unmodelled_resource(client):
    respx.get(url__startswith=f"{YAHOO_API_BASE}/game/nfl").mock(
        return_value=httpx.Response(200, json={"fantasy_content": {"game": {"season": "2026"}}})
    )

    body = client.get("/api/raw/game/nfl").json()

    assert body["fantasy_content"]["game"]["season"] == "2026"


@respx.mock
def test_week_is_rejected_outside_the_season(client):
    assert client.get(f"/api/teams/{LEAGUE}.t.4/roster?week=0").status_code == 422
    assert client.get(f"/api/teams/{LEAGUE}.t.4/roster?week=25").status_code == 422


# --- parse_leagues, previously uncovered ----------------------------------

LEAGUES_JSON = {
    "fantasy_content": {
        "users": {
            "0": {
                "user": [
                    {"guid": "abc"},
                    {
                        "games": {
                            "0": {
                                "game": [
                                    {"game_key": "461"},
                                    {
                                        "leagues": {
                                            "0": {
                                                "league": [
                                                    {
                                                        "league_key": "nfl.l.192426",
                                                        "league_id": "192426",
                                                        "name": "Sunday Gravy",
                                                        "num_teams": 12,
                                                        "scoring_type": "head",
                                                        "draft_status": "predraft",
                                                        "season": "2026",
                                                    }
                                                ]
                                            },
                                            "count": 1,
                                        }
                                    },
                                ]
                            },
                            "count": 1,
                        }
                    },
                ]
            },
            "count": 1,
        }
    }
}


def test_parse_leagues_extracts_the_fields_the_ui_needs():
    leagues = parse.parse_leagues(LEAGUES_JSON)

    assert len(leagues) == 1
    assert leagues[0]["name"] == "Sunday Gravy"
    assert leagues[0]["league_key"] == "nfl.l.192426"
    assert leagues[0]["num_teams"] == 12
    assert leagues[0]["draft_status"] == "predraft"


def test_parse_leagues_on_an_account_with_no_leagues():
    empty = {"fantasy_content": {"users": {"0": {"user": [{"guid": "abc"}]}, "count": 1}}}

    assert parse.parse_leagues(empty) == []


@respx.mock
def test_leagues_endpoint_returns_parsed_leagues(client):
    respx.get(url__startswith=f"{YAHOO_API_BASE}/users;use_login=1").mock(
        return_value=httpx.Response(200, json=LEAGUES_JSON)
    )

    body = client.get("/api/leagues").json()

    assert [x["name"] for x in body["leagues"]] == ["Sunday Gravy"]
