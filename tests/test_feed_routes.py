"""Feed endpoint tests, including the sync success path.

test_routes.py covers the disabled/unauthorised cases; this covers what
happens when it actually works, plus the read filters the UI depends on.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds import players as players_mod
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route


@pytest.fixture(autouse=True)
def offline_adp(monkeypatch):
    """Sync fetches live ADP; tests must never touch the real API.

    Simulates the no-network CI environment. Tests that want a working ADP
    fetch monkeypatch their own fake over this one.
    """

    async def _offline(*args, **kwargs):
        raise httpx.ConnectError("offline under test")

    monkeypatch.setattr(feeds_route.adp, "fetch", _offline)
    monkeypatch.setattr(feeds_route.vegas, "fetch", _offline)
    monkeypatch.setattr(feeds_route.stats, "fetch", _offline)


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
            "v": players_mod.INDEX_VERSION,
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
    await store.save_players(
        {"v": players_mod.INDEX_VERSION, "players": {}, "by_name": {}, "surnames": {}}
    )

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


async def test_sync_stores_adp_board_and_snapshots_history(sync_client, monkeypatch):
    c, store = sync_client
    monkeypatch.setattr(feeds_route.poller, "poll", fake_poll([]))

    async def fake_adp(*args, **kwargs):
        return {
            "fetched_at": "2026-08-15T09:00:00+00:00",
            "date": "2026-08-15",
            "players": [{"name": "Bijan Robinson", "position": "RB", "team": "ATL", "adp": 1.4}],
        }

    monkeypatch.setattr(feeds_route.adp, "fetch", fake_adp)

    body = c.post("/internal/sync", headers={"X-Sync-Token": "secret-token"}).json()

    assert body["adp_players"] == 1
    saved = await store.load()
    assert saved["adp"]["state"]["players"][0]["name"] == "Bijan Robinson"
    assert saved["adp"]["history"][-1]["date"] == "2026-08-15"
    assert saved["adp"]["history"][-1]["adp"] == {"Bijan Robinson": 1.4}


async def test_sync_keeps_previous_adp_when_fetch_fails(sync_client, monkeypatch):
    """Yesterday's board is still a draft board; a fetch failure must not
    wipe it or the movers history, and must never fail the news sync."""
    c, store = sync_client
    previous = {
        "state": {"date": "2026-08-14", "players": [{"name": "A", "adp": 5.0}]},
        "history": [{"date": "2026-08-14", "adp": {"A": 5.0}}],
    }
    await store.save({"items": [], "sources": {}, "polled_at": "x", "adp": previous})
    monkeypatch.setattr(feeds_route.poller, "poll", fake_poll([]))
    # offline_adp autouse fixture already makes adp.fetch raise

    response = c.post("/internal/sync", headers={"X-Sync-Token": "secret-token"})

    assert response.status_code == 200
    assert response.json()["adp_players"] == 1
    saved = await store.load()
    assert saved["adp"] == previous


async def test_sync_carries_verdicts_forward_for_surviving_items(client, monkeypatch):
    """Every sync used to save a dict with no 'verdicts' key, wiping the
    hourly AI job's output minutes after it landed. Verdicts must survive a
    sync and be pruned with the items they annotate."""
    import httpx as _httpx

    from app.config import get_settings
    from app.routes import feeds as feeds_route

    c, store = client
    monkeypatch.setattr(get_settings(), "sync_token", "secret-token", raising=False)

    async def _offline(*args, **kwargs):
        raise _httpx.ConnectError("offline under test")

    monkeypatch.setattr(feeds_route.adp, "fetch", _offline)
    monkeypatch.setattr(feeds_route.vegas, "fetch", _offline)

    async def fake_poll(*args, **kwargs):
        return {
            "items": [
                {"id": "keep", "title": "kept story", "published": "2026-08-15T12:00:00+00:00"}
            ],
            "sources": {},
            "polled_at": "2026-08-15T15:00:00+00:00",
        }

    monkeypatch.setattr(feeds_route.poller, "poll", fake_poll)

    await store.save(
        {
            "items": [
                {"id": "keep", "title": "kept story", "published": "2026-08-15T12:00:00+00:00"},
                {"id": "gone", "title": "old story", "published": "2020-01-01T00:00:00+00:00"},
            ],
            "verdicts": {"keep": "still matters", "gone": "aged out"},
        }
    )

    c.post("/internal/sync", headers={"X-Sync-Token": "secret-token"})

    saved = await store.load()
    assert saved["verdicts"] == {"keep": "still matters"}
