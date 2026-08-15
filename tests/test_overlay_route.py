"""The /app/data/feeds.json overlay -- the page's actual data source.

This is the highest-traffic contract in the app: the browser fetches this
path at startup, so a regression here is a blank or stale page for the
owner. The rule under test: live wire overlaid when the store works, the
committed file served untouched when anything at all goes wrong.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route

BUNDLED = json.loads(Path("frontend/data/feeds.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def offline_adp(monkeypatch):
    async def _offline(*args, **kwargs):
        raise httpx.ConnectError("offline under test")

    monkeypatch.setattr(feeds_route.adp, "fetch", _offline)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "sync_token", "secret-token", raising=False)
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    yield TestClient(main.app), store
    main.app.dependency_overrides.clear()


class ExplodingStore:
    """A store whose every read fails -- Redis down, bad URL, whatever."""

    async def load(self) -> dict:
        raise ConnectionError("redis is on fire")

    async def load_players(self) -> dict | None:
        raise ConnectionError("redis is on fire")

    async def save(self, payload: dict) -> None:
        raise ConnectionError("redis is on fire")

    async def save_players(self, index: dict) -> None:
        raise ConnectionError("redis is on fire")


def _wire_item() -> dict:
    return {
        "id": "wire-1",
        "source_key": "espn",
        "source_name": "ESPN",
        "tier": 1,
        "title": "Puka Nacua carted off at practice",
        "summary": "Left early with trainers.",
        "published": "2026-08-15T02:00:00+00:00",
        "players": [{"id": "1", "name": "Puka Nacua", "position": "WR", "team": "LAR"}],
    }


async def test_overlay_serves_live_wire_on_top_of_bundled(client):
    c, store = client
    await store.save(
        {
            "items": [_wire_item()],
            "sources": {},
            "polled_at": "2026-08-15T02:00:00+00:00",
            "verdicts": {"wire-1": "Availability for Week 1 is now in doubt."},
        }
    )

    body = c.get("/app/data/feeds.json").json()

    texts = [e["text"] for e in body["news"]]
    assert any("carted off" in t for t in texts)
    live = next(e for e in body["news"] if "carted off" in e["text"])
    assert live["impact"] == "AI draft: Availability for Week 1 is now in doubt."
    # The overlay stamps freshness so Data health tells the truth.
    stamped = {m["feed"]: m["asOf"] for m in body["meta"]}
    assert stamped["News & posts"].startswith("2026-")
    # Everything the wire cannot know survives from the committed file.
    assert body["alerts"] == BUNDLED["alerts"]
    # Nacua is on the page's Out & returning tab, so his wire mention becomes
    # that row's timestamp (rendered by mobile.js).
    assert body["injury_wire"]["Puka Nacua"]["head"].startswith("Puka Nacua carted off")


async def test_overlay_falls_back_to_bundled_when_store_is_down(client):
    c, _ = client
    main.app.dependency_overrides[feeds_route.get_feed_store] = ExplodingStore

    body = c.get("/app/data/feeds.json").json()

    # Byte-for-byte the committed file: stale-but-honest beats blank.
    assert body == BUNDLED


async def test_overlay_with_empty_store_serves_bundled_untouched(client):
    c, _ = client

    body = c.get("/app/data/feeds.json").json()

    assert body["news"] == BUNDLED["news"]
    assert body["meta"] == BUNDLED["meta"]


# --- the served page: live Vegas lines and stage badge ---------------------


def _vegas_game() -> dict:
    return {
        "game": "NE @ SEA",
        "fav": "SEA -7.5",  # deliberately different from the curated opener
        "total": "47.5",
        "imp": "SEA 27.5 · NE 20",
        "provider": "ESPN BET",
    }


@pytest.fixture
def page_client(tmp_path, monkeypatch):
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    main.app.dependency_overrides[feeds_route.get_optional_feed_store] = lambda: store
    yield TestClient(main.app), store
    main.app.dependency_overrides.clear()


async def test_served_page_swaps_in_live_vegas_lines(page_client):
    c, store = page_client
    await store.save(
        {
            "items": [],
            "vegas": {"fetched_at": "2026-08-15T16:00:00+00:00", "games": [_vegas_game()]},
        }
    )

    served = c.get("/app/").text

    assert "SEA -7.5" in served
    assert "Live via ESPN" in served
    assert "DraftKings openers" not in served
    # The curated prop angle for that matchup survives onto the live row.
    assert "banner-night slog" in served
    # TD leans go live-adjusted whenever the board is live.
    assert "confidence adjusted" in served


async def test_served_page_keeps_curated_vegas_when_store_is_empty(page_client):
    c, _ = page_client

    served = c.get("/app/").text

    assert "SEA -3.5" in served  # the committed opener
    assert "DraftKings openers" in served


async def test_served_page_keeps_curated_vegas_when_store_is_down(page_client):
    c, _ = page_client
    main.app.dependency_overrides[feeds_route.get_optional_feed_store] = ExplodingStore

    served = c.get("/app/")

    assert served.status_code == 200
    assert "DraftKings openers" in served.text


async def test_beta_deploys_announce_themselves(page_client, monkeypatch):
    c, _ = page_client
    monkeypatch.setattr(get_settings(), "vercel_env", "preview", raising=False)

    assert 'id="fb-stage-badge"' in c.get("/app/").text

    monkeypatch.setattr(get_settings(), "vercel_env", "production", raising=False)
    assert "fb-stage-badge" not in c.get("/app/").text
