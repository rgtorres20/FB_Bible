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
    monkeypatch.setattr(feeds_route.vegas, "fetch", _offline)


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


async def test_overlay_replaces_vegas_table_when_lines_are_live(client):
    c, store = client
    await store.save(
        {
            "items": [_wire_item()],
            "sources": {},
            "vegas": {
                "week_label": "Preseason Week 2",
                "games": [
                    {"game": "CAR @ BUF", "fav": "BUF -3", "total": "38.5", "imp": "x", "read": "y"}
                ],
            },
        }
    )

    body = c.get("/app/data/feeds.json").json()

    assert body["vegas"][0]["game"] == "CAR @ BUF"
    meta = {m["feed"]: m for m in body["meta"]}
    assert "live" in meta["Vegas lines"]["source"]
    assert "Preseason Week 2" in meta["Vegas lines"]["source"]
