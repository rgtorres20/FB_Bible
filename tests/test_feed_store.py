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
from app.feeds import players
from app.feeds.store import (
    PLAYER_RETENTION_SECONDS,
    FileFeedStore,
    RedisFeedStore,
    build_feed_store,
)

INDEX = {
    "v": players.INDEX_VERSION,
    "players": {"1": {"name": "Puka Nacua"}},
    "by_name": {"puka nacua": "1"},
    "surnames": {},
}


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


async def test_a_stored_index_is_served_however_old_it_is(tmp_path):
    """Changed Aug 22 after a live incident. This used to return None past
    a 20-hour TTL, which made "stale" and "absent" the same answer — so a
    single failed refetch emptied the top-300 board, the scoring board,
    the IDP board and the mock room's pool at once.

    Age is the caller's business now (`players.needs_refresh`), and the
    store's job is to still have the thing.
    """
    store = store_at(tmp_path)
    await store.save_players(INDEX)

    path = tmp_path / "players.index.json"
    ancient = time.time() - 10 * 24 * 60 * 60
    os.utime(path, (ancient, ancient))

    assert await store.load_players() == INDEX


async def test_retention_is_long_enough_to_survive_failed_refetches(tmp_path):
    """It is a backstop against an abandoned deployment, not an expiry.
    Set anywhere near the refresh interval and the incident comes back."""
    assert PLAYER_RETENTION_SECONDS > 7 * 24 * 60 * 60


async def test_the_index_is_still_refetched_about_daily(tmp_path):
    """Sleeper asks for no more than one dump per day. Retention got
    longer; the polite fetch rate must not — that constraint moved to
    `players.FRESH_SECONDS`, it was not dropped."""
    from app.feeds import players as players_mod

    assert players_mod.FRESH_SECONDS < 24 * 60 * 60


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


async def test_an_index_from_before_rank_support_is_treated_as_absent(tmp_path):
    """Caches built before the rank field would otherwise serve rankless
    players until their TTL ran out -- up to 20 hours of unweighted scoring."""
    store = store_at(tmp_path)
    await store.save_players({"players": {}, "by_name": {}, "surnames": {}})  # no version

    assert await store.load_players() is None
