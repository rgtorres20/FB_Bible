"""Feed endpoint tests, including the sync success path.

test_routes.py covers the disabled/unauthorised cases; this covers what
happens when it actually works, plus the read filters the UI depends on.
"""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route

STORED = {
    "items": [
        {
            "id": "1",
            "source_key": "espn",
            "tier": 1,
            "title": "Nacua back at practice",
            "summary": "",
            "published": "2026-08-15T02:00:00+00:00",
            "players": [{"id": "9493", "name": "Puka Nacua", "position": "WR", "team": "LAR"}],
        },
        {
            "id": "2",
            "source_key": "cbs",
            "tier": 2,
            "title": "Stadium financing approved",
            "summary": "",
            "published": "2026-08-15T01:00:00+00:00",
            "players": [],
        },
        {
            "id": "3",
            "source_key": "espn",
            "tier": 1,
            "title": "Bijan Robinson dominant",
            "summary": "",
            "published": "2026-08-15T00:00:00+00:00",
            "players": [{"id": "1001", "name": "Bijan Robinson", "position": "RB", "team": "ATL"}],
        },
    ],
    "sources": {
        "espn": {
            "name": "ESPN",
            "ok": True,
            "budget_hours": 24,
            "fetched_at": "2026-08-15T02:00:00+00:00",
            "attribution": "ESPN",
        },
        "cbs": {
            "name": "CBS",
            "ok": False,
            "error": "HTTP 500",
            "budget_hours": 24,
            "fetched_at": "2026-08-15T02:00:00+00:00",
            "attribution": "CBS",
        },
    },
    "polled_at": "2026-08-15T02:00:00+00:00",
}


@pytest.fixture
def client(tmp_path):
    """A client whose feed store is a real file store in tmp_path."""
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    yield TestClient(main.app), store
    main.app.dependency_overrides.clear()


async def seed(store):
    await store.save(STORED)


async def test_reads_items_newest_first(client):
    c, store = client
    await seed(store)

    body = c.get("/api/feeds").json()

    assert body["total"] == 3
    assert [i["id"] for i in body["items"]] == ["1", "2", "3"]


async def test_limit_caps_items_but_total_reports_everything(client):
    c, store = client
    await seed(store)

    body = c.get("/api/feeds?limit=1").json()

    assert len(body["items"]) == 1
    assert body["total"] == 3


async def test_filter_by_source(client):
    c, store = client
    await seed(store)

    body = c.get("/api/feeds?source=espn").json()

    assert {i["source_key"] for i in body["items"]} == {"espn"}


async def test_filter_by_tier(client):
    c, store = client
    await seed(store)

    body = c.get("/api/feeds?tier=2").json()

    assert [i["id"] for i in body["items"]] == ["2"]


async def test_tagged_only_hides_items_about_nobody(client):
    c, store = client
    await seed(store)

    body = c.get("/api/feeds?tagged_only=true").json()

    assert [i["id"] for i in body["items"]] == ["1", "3"]


async def test_filter_by_player_name_is_case_insensitive(client):
    c, store = client
    await seed(store)

    body = c.get("/api/feeds?player=nacua").json()

    assert [i["id"] for i in body["items"]] == ["1"]


async def test_filter_by_player_id(client):
    c, store = client
    await seed(store)

    body = c.get("/api/feeds?player=1001").json()

    assert [i["id"] for i in body["items"]] == ["3"]


async def test_sources_carry_an_honest_freshness_state(client):
    """The app currently hardcodes "live" for nine sources; this is the field
    that replaces it."""
    c, store = client
    await seed(store)

    sources = c.get("/api/feeds").json()["sources"]

    assert sources["espn"]["state"] in {"LIVE", "STALE"}
    assert sources["cbs"]["state"] == "FAILED"


async def test_unknown_player_filter_returns_empty_not_an_error(client):
    c, store = client
    await seed(store)

    body = c.get("/api/feeds?player=nobody-at-all").json()

    assert body["items"] == []


def test_limit_is_validated(client):
    c, _ = client

    assert c.get("/api/feeds?limit=0").status_code == 422
    assert c.get("/api/feeds?limit=99999").status_code == 422


# --- sync success path ----------------------------------------------------


@pytest.fixture
def sync_client(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "sync_token", "secret-token", raising=False)
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    yield TestClient(main.app), store
    main.app.dependency_overrides.clear()


def fake_poll(items):
    async def _poll(*args, **kwargs):
        return {
            "items": items,
            "sources": {
                "espn": {
                    "name": "ESPN",
                    "ok": True,
                    "budget_hours": 24,
                    "fetched_at": "2026-08-15T02:00:00+00:00",
                    "attribution": "ESPN",
                    "item_count": len(items),
                }
            },
            "polled_at": "2026-08-15T02:00:00+00:00",
        }

    return _poll


async def test_sync_rejects_a_wrong_token(sync_client, monkeypatch):
    c, _ = sync_client

    response = c.post("/internal/sync", headers={"X-Sync-Token": "wrong"})

    assert response.status_code == 401


async def test_sync_stores_items_and_reports_counts(sync_client, monkeypatch):
    c, store = sync_client
    items = [
        {
            "id": "a",
            "title": "Nacua practices",
            "summary": "",
            "published": "2026-08-15T02:00:00+00:00",
        },
        {
            "id": "b",
            "title": "Nothing much",
            "summary": "",
            "published": "2026-08-15T01:00:00+00:00",
        },
    ]
    monkeypatch.setattr(feeds_route.poller, "poll", fake_poll(items))
    # Pretend the player index is already cached, so no 14MB download.
    await store.save_players(
        {
            "players": {
                "9493": {
                    "id": "9493",
                    "name": "Puka Nacua",
                    "position": "WR",
                    "team": "LAR",
                    "injury_status": None,
                }
            },
            "by_name": {"puka nacua": "9493"},
            "surnames": {"nacua": "9493"},
        }
    )

    body = c.post("/internal/sync", headers={"X-Sync-Token": "secret-token"}).json()

    assert body["new"] == 2
    assert body["total"] == 2
    assert body["sources_failed"] == []
    assert body["tagged"] == 1  # only the Nacua item mentions a player
    assert len((await store.load())["items"]) == 2


async def test_a_second_sync_adds_nothing_new(sync_client, monkeypatch):
    c, store = sync_client
    items = [{"id": "a", "title": "x", "summary": "", "published": "2026-08-15T02:00:00+00:00"}]
    monkeypatch.setattr(feeds_route.poller, "poll", fake_poll(items))
    await store.save_players({"players": {}, "by_name": {}, "surnames": {}})

    c.post("/internal/sync", headers={"X-Sync-Token": "secret-token"})
    body = c.post("/internal/sync", headers={"X-Sync-Token": "secret-token"}).json()

    assert body["new"] == 0
    assert body["total"] == 1


async def test_sync_survives_the_player_index_being_unavailable(sync_client, monkeypatch):
    """Tagging is a bonus; losing it must not cost us the news."""
    c, store = sync_client
    items = [
        {
            "id": "a",
            "title": "Nacua practices",
            "summary": "",
            "published": "2026-08-15T02:00:00+00:00",
        }
    ]
    monkeypatch.setattr(feeds_route.poller, "poll", fake_poll(items))

    async def boom():
        raise RuntimeError("sleeper is down")

    monkeypatch.setattr(feeds_route.players, "fetch_index", boom)

    body = c.post("/internal/sync", headers={"X-Sync-Token": "secret-token"}).json()

    assert body["total"] == 1
    assert body["tagged"] == 0
