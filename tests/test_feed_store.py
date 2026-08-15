"""Feed store tests, with the player-index TTL as the main event.

The TTL is the thing standing between a 15-minute cron and downloading 14MB
from Sleeper 96 times a day. Getting it wrong in either direction is bad: too
short hammers them, too long serves an index that no longer knows who is
injured.
"""

import json
import os
import time

from app.config import Settings
from app.feeds.store import (
    PLAYER_TTL_SECONDS,
    FileFeedStore,
    RedisFeedStore,
    build_feed_store,
)

INDEX = {"players": {"1": {"name": "Puka Nacua"}}, "by_name": {"puka nacua": "1"}, "surnames": {}}


def store_at(tmp_path) -> FileFeedStore:
    return FileFeedStore(str(tmp_path / "feeds.json"))


async def test_missing_file_loads_as_empty_not_an_error():
    assert await FileFeedStore("does/not/exist.json").load() == {}


async def test_feed_round_trip(tmp_path):
    store = store_at(tmp_path)
    payload = {"items": [{"id": "a"}], "polled_at": "2026-08-15T00:00:00+00:00"}

    await store.save(payload)

    assert await store.load() == payload


async def test_corrupt_feed_file_loads_as_empty(tmp_path):
    """A truncated write must not brick the endpoint -- the next sync repairs it."""
    path = tmp_path / "feeds.json"
    path.write_text('{"items": [', encoding="utf-8")

    assert await FileFeedStore(str(path)).load() == {}


async def test_save_is_atomic_leaving_no_temp_file(tmp_path):
    store = store_at(tmp_path)
    await store.save({"items": []})

    assert not list(tmp_path.glob("*.tmp"))


async def test_save_creates_missing_parent_directories(tmp_path):
    store = FileFeedStore(str(tmp_path / "nested" / "deeper" / "feeds.json"))

    await store.save({"items": [1]})

    assert await store.load() == {"items": [1]}


# --- player index caching -------------------------------------------------


async def test_player_index_round_trips(tmp_path):
    store = store_at(tmp_path)

    await store.save_players(INDEX)

    assert await store.load_players() == INDEX


async def test_player_index_is_absent_before_first_save(tmp_path):
    assert await store_at(tmp_path).load_players() is None


async def test_player_index_is_served_while_inside_the_ttl(tmp_path):
    store = store_at(tmp_path)
    await store.save_players(INDEX)

    # One hour short of expiry.
    path = tmp_path / "players.index.json"
    fresh = time.time() - (PLAYER_TTL_SECONDS - 3600)
    os.utime(path, (fresh, fresh))

    assert await store.load_players() == INDEX


async def test_player_index_expires_past_the_ttl(tmp_path):
    """Otherwise injury_status on every tag silently goes stale."""
    store = store_at(tmp_path)
    await store.save_players(INDEX)

    path = tmp_path / "players.index.json"
    old = time.time() - (PLAYER_TTL_SECONDS + 60)
    os.utime(path, (old, old))

    assert await store.load_players() is None


async def test_ttl_is_under_a_day(tmp_path):
    """Sleeper asks for no more than one dump per day; a TTL of 24h+ would
    drift past that as sync times shift."""
    assert PLAYER_TTL_SECONDS < 24 * 60 * 60


async def test_corrupt_player_index_is_treated_as_absent(tmp_path):
    store = store_at(tmp_path)
    await store.save_players(INDEX)
    (tmp_path / "players.index.json").write_text("{oh no", encoding="utf-8")

    assert await store.load_players() is None


async def test_player_index_lives_beside_the_feed_file(tmp_path):
    """Both belong to the same store; a stray path would silently never cache."""
    await store_at(tmp_path).save_players(INDEX)

    written = json.loads((tmp_path / "players.index.json").read_text(encoding="utf-8"))
    assert written == INDEX


# --- selection ------------------------------------------------------------


def test_build_feed_store_picks_file_for_local_dev():
    settings = Settings(token_store="file", feed_file_path="data/feeds.json")

    assert isinstance(build_feed_store(settings), FileFeedStore)


def test_build_feed_store_picks_redis_when_configured():
    """Serverless has no writable disk, so this choice follows the token store."""
    settings = Settings(token_store="redis", redis_url="redis://localhost:6379")

    assert isinstance(build_feed_store(settings), RedisFeedStore)


def test_both_stores_expose_the_same_interface():
    """FeedStore is a Protocol, so nothing enforces this at runtime."""
    for name in ("load", "save", "load_players", "save_players"):
        assert callable(getattr(FileFeedStore("x.json"), name))
        assert hasattr(RedisFeedStore, name)
