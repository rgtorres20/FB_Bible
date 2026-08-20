"""The top-300 alert board.

The contract: 300 rows by Sleeper rank; machine lines always labelled by
author ("AI draft:" / "Auto:"); a player the wire has not mentioned says so
instead of showing nothing; and a missing player index degrades to an honest
empty page, never a fabricated one.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds import alerts300
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _index(count: int = 300) -> dict:
    players = {}
    for i in range(1, count + 1):
        pid = str(1000 + i)
        players[pid] = {
            "id": pid,
            "name": f"Player {i}",
            "position": "WR",
            "team": "DET",
            "injury_status": "Questionable" if i == 2 else None,
            "rank": i,
        }
    return {"players": players}


def _item(item_id: str, pid: str, title: str, rank: int | None = None) -> dict:
    return {
        "id": item_id,
        "source_key": "espn",
        "source_name": "ESPN",
        "tier": 1,
        "title": title,
        "summary": "",
        "link": "https://example.com/story",
        "published": "2026-08-15T02:00:00+00:00",
        "players": [{"id": pid, "name": "Player 1", "position": "WR", "team": "DET", "rank": rank}],
    }


def test_ranked_players_are_capped_and_ordered():
    ranked = alerts300._ranked_players(_index(500))
    assert len(ranked) == alerts300.TOP
    assert ranked[0]["rank"] == 1
    assert ranked[-1]["rank"] == 300


def test_build_html_labels_authorship_and_absence():
    items = [
        _item("with-verdict", "1001", "Player 1 limited in practice"),
        _item("without-verdict", "1002", "Player 2 carted off with ankle injury"),
    ]
    page = alerts300.build_html(
        _index(), items, {"with-verdict": "Hamstring caps early-camp work."}, None, NOW
    )
    assert "AI draft: Hamstring caps early-camp work." in page
    assert "Auto:" in page  # the unverdicted item falls back to the rule-based line
    assert "No wire mention in the last 21 days" in page  # everyone else
    assert page.count("<tr>") == 301  # 300 players + the header row
    assert "data: Sleeper" in page


def test_build_html_carries_injury_flag_and_adp():
    adp_state = {"players": [{"name": "Player 1", "adp": 12.3, "position": "WR", "team": "DET"}]}
    page = alerts300.build_html(_index(), [], {}, adp_state, NOW)
    assert "QUESTIONABLE" in page.upper()
    assert "12.3" in page


def test_build_html_without_index_is_honest():
    page = alerts300.build_html(None, [], {}, None, NOW)
    assert "Player index unavailable" in page
    assert "<tr>" not in page


def test_newest_mention_wins():
    old = _item("old", "1001", "old story")
    old["published"] = "2026-08-10T02:00:00+00:00"
    new = _item("new", "1001", "new story")
    page = alerts300.build_html(_index(), [old, new], {}, None, NOW)
    assert "new story" in page
    assert "old story" not in page


# --- the route -------------------------------------------------------------


@pytest.fixture(autouse=True)
def offline_feeds(monkeypatch):
    async def _offline(*args, **kwargs):
        raise httpx.ConnectError("offline under test")

    monkeypatch.setattr(feeds_route.adp, "fetch", _offline)
    monkeypatch.setattr(feeds_route.vegas, "fetch", _offline)
    monkeypatch.setattr(feeds_route.stats, "fetch", _offline)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "sync_token", "secret-token", raising=False)
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    yield TestClient(main.app), store
    main.app.dependency_overrides.clear()


async def test_route_serves_the_board(client):
    c, store = client
    await store.save({"items": [_item("a", "1001", "Player 1 limited")], "sources": {}})
    await store.save_players(
        {**_index(), "v": feeds_route.players.INDEX_VERSION, "by_name": {}, "surnames": {}}
    )

    response = c.get("/app/alerts300")

    assert response.status_code == 200
    assert "Top-300 alert board" in response.text
    assert response.text.count("<tr>") == 301


async def test_route_without_index_says_so(client):
    c, _ = client
    response = c.get("/app/alerts300")
    assert response.status_code == 200
    assert "Player index unavailable" in response.text


def test_offense_and_defense_render_as_separate_sections():
    """Owner request: offense scans clean, defense is one tap away. A
    defender never appears in the offense table and vice versa."""
    index = _index(120)
    index["players"]["9001"] = {
        "id": "9001",
        "name": "Roquan Smith",
        "position": "LB",
        "team": "BAL",
        "injury_status": None,
        "rank": 5,
        "idp": "LB",
    }
    page = alerts300.build_html(index, [], {}, None, NOW)
    assert "<h2 id='offense'>" in page and "<h2 id='defense'>" in page
    offense_part, defense_part = page.split("<h2 id='defense'>")
    assert "Roquan Smith" in defense_part
    assert "Roquan Smith" not in offense_part
    assert "Player 1" in offense_part
