"""Redis-backed stores, exercised against an in-test fake.

These are the only two classes that talk to the production database, and
until now nothing covered them. The fake implements the four redis.asyncio
methods the stores use, so the tests pin the store's own contract -- key
prefixes, encryption at rest, TTL discipline, version gating, and corrupt-
data fallbacks -- without a server or a new dependency.
"""

from __future__ import annotations

import json

from cryptography.fernet import Fernet

from app.feeds import store as feed_store_mod
from app.feeds.players import INDEX_VERSION
from app.feeds.store import PLAYER_RETENTION_SECONDS, RedisFeedStore
from app.store.base import TokenSet
from app.store.crypto import TokenCipher
from app.store.redis_store import RedisTokenStore


class FakeRedis:
    """The slice of redis.asyncio the stores actually use."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}
        self.closed = False

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.data[key] = value
        self.ttls[key] = ex

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)

    async def aclose(self) -> None:
        self.closed = True


def _token_store() -> tuple[RedisTokenStore, FakeRedis]:
    store = RedisTokenStore.__new__(RedisTokenStore)
    fake = FakeRedis()
    store._redis = fake
    store._cipher = TokenCipher(Fernet.generate_key().decode())
    return store, fake


def _tokens() -> TokenSet:
    return TokenSet(
        access_token="access-secret-abc",
        refresh_token="refresh-secret-xyz",
        expires_at=2_000_000_000.0,
        xoauth_yahoo_guid="GUID123",
    )


# --- token store -----------------------------------------------------------


async def test_token_round_trip():
    store, _ = _token_store()
    await store.put("me", _tokens())
    got = await store.get("me")
    assert got is not None
    assert got.access_token == "access-secret-abc"
    assert got.refresh_token == "refresh-secret-xyz"
    assert got.xoauth_yahoo_guid == "GUID123"


async def test_tokens_are_encrypted_at_rest_and_prefixed():
    store, fake = _token_store()
    await store.put("me", _tokens())
    (key,) = fake.data.keys()
    assert key == "fbbible:tokens:me"
    blob = fake.data[key]
    # The whole point of the cipher: no token material readable in Redis.
    assert "access-secret-abc" not in blob
    assert "refresh-secret-xyz" not in blob


async def test_missing_and_corrupt_blobs_read_as_signed_out():
    store, fake = _token_store()
    assert await store.get("nobody") is None
    fake.data["fbbible:tokens:garbled"] = "not-a-fernet-blob"
    assert await store.get("garbled") is None


async def test_delete_and_close():
    store, fake = _token_store()
    await store.put("me", _tokens())
    await store.delete("me")
    assert fake.data == {}
    await store.aclose()
    assert fake.closed


async def test_tokens_persist_without_ttl():
    # The refresh token outlives the access token; an expiring key would
    # silently sign the user out.
    store, fake = _token_store()
    await store.put("me", _tokens())
    assert fake.ttls["fbbible:tokens:me"] is None


# --- feed store ------------------------------------------------------------


def _feed_store() -> tuple[RedisFeedStore, FakeRedis]:
    store = RedisFeedStore.__new__(RedisFeedStore)
    fake = FakeRedis()
    store._redis = fake
    return store, fake


async def test_feed_round_trip_and_empty_default():
    store, _ = _feed_store()
    assert await store.load() == {}
    payload = {"items": [{"id": "a"}], "polled_at": "2026-08-15T00:00:00+00:00"}
    await store.save(payload)
    assert await store.load() == payload


async def test_feed_corrupt_json_reads_as_empty():
    store, fake = _feed_store()
    fake.data[feed_store_mod._KEY] = "{broken"
    assert await store.load() == {}


async def test_player_index_is_kept_far_longer_than_it_is_refreshed():
    """Retention is a backstop, not an expiry. It was the expiry until
    Aug 22, which meant the index vanished every 20 hours and any sync
    whose refetch failed served empty boards — the one feed that degraded
    to nothing rather than to yesterday's copy."""
    from app.feeds import players as players_mod

    store, fake = _feed_store()
    await store.save_players({"v": INDEX_VERSION, "players": {}})
    ttl = fake.ttls[feed_store_mod._PLAYER_KEY]
    assert ttl == PLAYER_RETENTION_SECONDS
    assert ttl > players_mod.FRESH_SECONDS * 10, "a short TTL brings the incident back"


async def test_player_index_version_gate():
    store, _ = _feed_store()
    await store.save_players({"v": INDEX_VERSION - 1, "players": {}})
    # An index built by an older tagger must be rebuilt, not trusted.
    assert await store.load_players() is None
    await store.save_players({"v": INDEX_VERSION, "players": {}})
    assert (await store.load_players()) == {"v": INDEX_VERSION, "players": {}}


async def test_player_index_missing_or_corrupt_is_none():
    store, fake = _feed_store()
    assert await store.load_players() is None
    fake.data[feed_store_mod._PLAYER_KEY] = "]["
    assert await store.load_players() is None


# --- compressed values (Oct 23: the plan's bandwidth cap was hit) ------------


def _feed_store() -> tuple[RedisFeedStore, FakeRedis]:
    store = RedisFeedStore.__new__(RedisFeedStore)
    fake = FakeRedis()
    store._redis = fake
    store._vault = feed_store_mod._Vault("")
    return store, fake


def _realistic_blob() -> dict:
    """News-like rows: the repetitive keys and phrasing the real blob has."""
    return {
        "items": [
            {
                "id": f"n{i}",
                "title": f"Player {i % 40} questionable for Sunday with an ankle injury",
                "summary": "Coach said he was limited in practice Wednesday and Thursday.",
                "source": "rotowire",
                "published": f"2026-10-{1 + i % 28:02d}T12:00:00+00:00",
                "players": [f"p{i % 40}"],
            }
            for i in range(400)
        ]
    }


async def test_every_plain_key_is_stored_compressed_and_reads_back():
    store, fake = _feed_store()
    blob = _realistic_blob()
    await store.save(blob)
    await store.save_scorecard({"entries": [1, 2]})
    await store.save_gamelogs({"v": 1, "players": {"1": {"games": {}}}})
    await store.save_cfb({"v": 1})
    await store.save_nba({"v": 2})
    for key, value in fake.data.items():
        assert value.startswith("z1:"), key
    assert await store.load() == blob
    assert await store.load_scorecard() == {"entries": [1, 2]}
    assert (await store.load_nba()) == {"v": 2}
    plain = len(json.dumps(blob))
    stored = len(fake.data["fbbible:feeds"])
    assert stored * 4 < plain, f"{stored} bytes stored for {plain} of JSON"


async def test_values_written_before_compression_still_read():
    """No migration step: the old plain JSON reads, and the next save of
    that key rewrites it compressed."""
    store, fake = _feed_store()
    fake.data["fbbible:feeds"] = json.dumps({"items": [{"id": "old"}]})
    assert await store.load() == {"items": [{"id": "old"}]}
    await store.save(await store.load())
    assert fake.data["fbbible:feeds"].startswith("z1:")


async def test_a_corrupt_compressed_value_reads_like_a_corrupt_json_one():
    store, fake = _feed_store()
    fake.data["fbbible:feeds"] = "z1:not-base64-zlib!!"
    assert await store.load() == {}
    fake.data["fbbible:players"] = "z1:AAAA"
    assert await store.load_players() is None
