"""Storage for polled feed items.

Separate from the token store on purpose: these are public headlines, so no
encryption, and the retention rules are different. Yahoo's 24-hour deletion
rule does not apply here -- none of this is Yahoo user data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

_KEY = "fbbible:feeds"


class FeedStore(Protocol):
    async def load(self) -> dict: ...

    async def save(self, payload: dict) -> None: ...


class FileFeedStore:
    """Local dev. Not for serverless -- no writable disk there."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)

    async def load(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    async def save(self, payload: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._path)


class RedisFeedStore:
    def __init__(self, url: str) -> None:
        import redis.asyncio as redis

        self._redis = redis.from_url(url, decode_responses=True)

    async def load(self) -> dict:
        raw = await self._redis.get(_KEY)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    async def save(self, payload: dict) -> None:
        await self._redis.set(_KEY, json.dumps(payload))


def build_feed_store(settings) -> FeedStore:
    if settings.token_store == "redis":
        return RedisFeedStore(settings.redis_url)
    return FileFeedStore(settings.feed_file_path)
