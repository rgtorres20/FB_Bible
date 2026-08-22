"""The player index must degrade like every other feed.

Live incident, Aug 22. Twelve watchdog checks failed at once: the top-300
board, the scoring board, the IDP board and the mock room's pool all came
back empty, while news, Vegas, ADP and team defenses were fine.

The index was stored under a 20-hour TTL and refetched only when
`load_players()` returned None — so the TTL expiring and a fetch failing
in the same hour left nothing stored, and every board that reads players
served empty until some later sync happened to succeed. It was the one
feed in the app that degraded to *nothing* rather than to yesterday's
copy; a few lines below it in the same function, ADP and Vegas both carry
forward on exactly that reasoning.

An empty board does not read as stale. It reads as "no players exist",
which is a false statement rather than an old one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds import players as players_mod
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _index(fetched_at: datetime | None = NOW) -> dict:
    index = {
        "v": players_mod.INDEX_VERSION,
        "by_name": {},
        "surnames": {},
        "players": {
            "4034": {
                "id": "4034",
                "name": "Saquon Barkley",
                "position": "RB",
                "team": "PHI",
                "injury_status": None,
                "rank": 2,
            }
        },
    }
    if fetched_at is not None:
        index["fetched_at"] = fetched_at.isoformat()
    return index


# --- when to go and get a new one ---------------------------------------


def test_a_fresh_index_is_left_alone():
    """Sleeper asks for at most one dump a day. Refetching a two-hour-old
    index would be rude and slow."""
    assert not players_mod.needs_refresh(_index(NOW - timedelta(hours=2)), now=NOW)


def test_an_index_past_the_refresh_window_is_due():
    stale = _index(NOW - timedelta(hours=players_mod.FRESH_SECONDS / 3600 + 1))
    assert players_mod.needs_refresh(stale, now=NOW)


def test_a_missing_or_empty_index_is_due():
    assert players_mod.needs_refresh(None, now=NOW)
    assert players_mod.needs_refresh({"v": players_mod.INDEX_VERSION, "players": {}}, now=NOW)


def test_an_unstamped_index_is_due_rather_than_trusted():
    """One written before the stamp existed. Its age cannot be judged, so
    it is treated as due — trusting it would be assuming freshness."""
    assert players_mod.needs_refresh(_index(fetched_at=None), now=NOW)


def test_a_nonsense_stamp_is_due_rather_than_crashing():
    broken = {**_index(), "fetched_at": "not-a-date"}
    assert players_mod.age_seconds(broken, now=NOW) is None
    assert players_mod.needs_refresh(broken, now=NOW)


def test_a_freshly_built_index_stamps_itself():
    """Without the stamp there is no way to tell a copy kept through an
    outage from a fresh one, which is the whole point of keeping it."""
    built = players_mod.build_index({})
    assert players_mod.fetched_at(built) is not None
    assert (players_mod.age_seconds(built) or 0) < 60


def test_an_index_with_no_players_is_due_however_fresh_its_stamp():
    """A stamp is not coverage. An empty dump that parsed is still an
    empty board, and carrying it forward would be carrying the outage
    forward."""
    empty = players_mod.build_index({})
    assert empty["players"] == {}
    assert players_mod.needs_refresh(empty)


# --- the incident itself -------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    s = get_settings()
    monkeypatch.setattr(s, "sync_token", "secret-token", raising=False)
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    # /health takes the OPTIONAL store — a different dependency, and
    # overriding only the first silently gave it a real (unconfigured) one.
    main.app.dependency_overrides[feeds_route.get_optional_feed_store] = lambda: store
    c = TestClient(main.app)
    c._store = store  # type: ignore[attr-defined]
    yield c
    main.app.dependency_overrides.clear()


def _offline_sync(monkeypatch, *, index_fetch):
    """Every outbound call stubbed; only the index fetch varies."""

    async def nothing(*a, **k):
        raise RuntimeError("offline")

    async def no_items(*a, **k):
        return {"items": [], "sources": {}, "polled_at": NOW.isoformat()}

    monkeypatch.setattr(feeds_route.poller, "poll", no_items)
    monkeypatch.setattr(feeds_route.adp, "fetch", nothing)
    monkeypatch.setattr(feeds_route.vegas, "fetch", nothing)
    monkeypatch.setattr(feeds_route.stats, "fetch", nothing)
    monkeypatch.setattr(feeds_route.players, "fetch_index", index_fetch)


@pytest.mark.anyio
async def test_a_failed_refetch_keeps_yesterdays_players(client, monkeypatch, anyio_backend):
    """The incident, reproduced. A stale index plus a failed fetch used to
    leave nothing stored; it must now leave what was already there."""
    stored = _index(NOW - timedelta(days=2))
    await client._store.save_players(stored)

    async def boom(*a, **k):
        raise RuntimeError("sleeper is down")

    _offline_sync(monkeypatch, index_fetch=boom)
    resp = client.post("/internal/sync", headers={"X-Sync-Token": "secret-token"})
    assert resp.status_code == 200

    kept = await client._store.load_players()
    assert kept is not None, "a failed refetch must not empty the index"
    assert kept["players"]["4034"]["name"] == "Saquon Barkley"


@pytest.mark.anyio
async def test_a_successful_refetch_replaces_it(client, monkeypatch, anyio_backend):
    """Carrying forward must not become never updating."""
    await client._store.save_players(_index(NOW - timedelta(days=2)))

    async def fresh(*a, **k):
        return {
            "v": players_mod.INDEX_VERSION,
            "fetched_at": NOW.isoformat(),
            "by_name": {},
            "surnames": {},
            "players": {"1": {"id": "1", "name": "Bijan Robinson", "position": "RB"}},
        }

    _offline_sync(monkeypatch, index_fetch=fresh)
    client.post("/internal/sync", headers={"X-Sync-Token": "secret-token"})

    stored = await client._store.load_players()
    assert "1" in stored["players"]
    assert "4034" not in stored["players"]


@pytest.mark.anyio
async def test_a_fresh_index_is_not_refetched_at_all(client, monkeypatch, anyio_backend):
    """The politeness rule. A sync an hour after the last one must not
    pull 14MB again."""
    await client._store.save_players(_index(datetime.now(UTC) - timedelta(hours=1)))
    called = []

    async def counting(*a, **k):
        called.append(1)
        raise RuntimeError("should never be reached")

    _offline_sync(monkeypatch, index_fetch=counting)
    client.post("/internal/sync", headers={"X-Sync-Token": "secret-token"})
    assert called == []


@pytest.mark.anyio
async def test_the_sync_still_succeeds_with_no_index_at_all(client, monkeypatch, anyio_backend):
    """First run on an empty store, with Sleeper down. The news half must
    still land — a fetch failure degrades to untagged items, never to a
    failed sync."""

    async def boom(*a, **k):
        raise RuntimeError("sleeper is down")

    _offline_sync(monkeypatch, index_fetch=boom)
    resp = client.post("/internal/sync", headers={"X-Sync-Token": "secret-token"})
    assert resp.status_code == 200
    assert await client._store.load_players() is None


# --- so the next outage names itself ------------------------------------


@pytest.mark.anyio
async def test_health_reports_the_index_count_and_age(client, anyio_backend):
    """The Aug 22 outage showed up as four unrelated boards coming back
    empty and nothing saying why. It is one store key; one request should
    answer it."""
    await client._store.save_players(_index(datetime.now(UTC) - timedelta(hours=3)))
    state = client.get("/health").json()["players"]
    assert state["count"] == 1
    assert 2.5 < state["age_hours"] < 3.5


@pytest.mark.anyio
async def test_health_reports_a_zero_count_rather_than_hiding_it(client, anyio_backend):
    """Zero is the incident. It has to be visible, not absent."""
    assert client.get("/health").json()["players"]["count"] == 0


@pytest.mark.anyio
async def test_health_survives_an_unreadable_store(client, monkeypatch, anyio_backend):
    """It is the endpoint you reach for *because* something is wrong, so a
    broken store must not take it down."""

    async def boom(*a, **k):
        raise RuntimeError("redis is gone")

    monkeypatch.setattr(client._store, "load_players", boom)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["players"] == {"count": None, "age_hours": None}
