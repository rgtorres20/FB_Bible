"""AI-verdict storage and rendering.

The safety contract: verdicts only attach to wire items we actually hold
(an invented id dies at the door), they render prefixed "AI draft:" so they
never read as the owner's judgement, and they disappear with their items.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds import render
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route


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


def _item(item_id: str, title: str) -> dict:
    return {
        "id": item_id,
        "source_key": "espn",
        "source_name": "ESPN",
        "tier": 1,
        "title": title,
        "summary": "",
        "published": "2026-08-15T02:00:00+00:00",
        "players": [{"id": "1", "name": "Puka Nacua", "position": "WR", "team": "LAR"}],
    }


async def test_verdicts_require_the_sync_token(client):
    c, _ = client
    response = c.post("/internal/verdicts", json={"verdicts": {"a": "x"}})
    assert response.status_code == 401


async def test_verdicts_only_attach_to_held_items(client):
    c, store = client
    await store.save({"items": [_item("real", "Nacua limited")], "sources": {}})

    body = c.post(
        "/internal/verdicts",
        json={"verdicts": {"real": "Hamstring caps his early-camp workload.", "invented": "x"}},
        headers={"X-Sync-Token": "secret-token"},
    ).json()

    assert body == {"accepted": 1, "stored": 1}
    saved = await store.load()
    assert "invented" not in saved["verdicts"]


async def test_verdicts_are_pruned_with_their_items_and_capped(client):
    c, store = client
    await store.save(
        {
            "items": [_item("keep", "t")],
            "sources": {},
            "verdicts": {"gone": "about an item that scrolled off"},
        }
    )

    long_text = "x" * 500
    c.post(
        "/internal/verdicts",
        json={"verdicts": {"keep": long_text, "": "  "}},
        headers={"X-Sync-Token": "secret-token"},
    )

    saved = await store.load()
    assert set(saved["verdicts"]) == {"keep"}
    assert len(saved["verdicts"]["keep"]) == feeds_route.MAX_VERDICT_CHARS


def test_render_prefers_ai_draft_and_falls_back_to_auto():
    items = [_item("a", "Nacua carted off with ankle injury"), _item("b", "Nacua signs extension")]
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    merged = render.merge_into_feeds(
        {"news": [], "meta": []},
        items,
        now,
        ranks={"1": 10},
        verdicts={"a": "Week 1 availability now in real doubt."},
    )
    by_text = {e["text"]: e["impact"] for e in merged["news"]}
    ai = next(v for k, v in by_text.items() if "carted" in k)
    auto = next(v for k, v in by_text.items() if "extension" in k)
    assert ai == "AI draft: Week 1 availability now in real doubt."
    assert auto.startswith("Auto:")


# --- cheat sheet -----------------------------------------------------------


async def test_cheatsheet_renders_live_board(client):
    c, store = client
    await store.save(
        {
            "items": [],
            "sources": {},
            "adp": {
                "state": {
                    "date": "2026-08-15",
                    "players": [
                        {
                            "name": "Bijan Robinson",
                            "position": "RB",
                            "team": "ATL",
                            "bye": 11,
                            "adp": 1.7,
                            "sizes": {"12": 1.7, "10": 1.8},
                        }
                    ],
                },
                "history": [],
            },
        }
    )

    response = c.get("/app/cheatsheet")

    assert response.status_code == 200
    page = response.text
    assert "Bijan Robinson" in page
    assert "12tm" in page and "10tm" in page
    assert "rushing league" in page  # the Trenches QB caveat must always print


async def test_cheatsheet_without_board_says_so(client):
    c, _ = client
    response = c.get("/app/cheatsheet")
    assert response.status_code == 200
    assert "No live ADP board yet" in response.text
