"""Storage for polled feed items.

Separate from the token store on purpose: these are public headlines, so no
encryption, and the retention rules are different. Yahoo's 24-hour deletion
rule does not apply here -- none of this is Yahoo user data.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Protocol

_KEY = "fbbible:feeds"
_USER_KEY_PREFIX = "fbbible:user:"


def _current_version(index: dict) -> bool:
    from .players import INDEX_VERSION

    return index.get("v") == INDEX_VERSION


_PLAYER_KEY = "fbbible:players"
# Sleeper asks callers not to pull the 14MB dump more than once a day.
PLAYER_TTL_SECONDS = 20 * 60 * 60


_AUTH_KEY = "fbbible:auth"


class FeedStore(Protocol):
    async def load(self) -> dict: ...

    async def save(self, payload: dict) -> None: ...

    async def load_players(self) -> dict | None: ...

    async def save_players(self, index: dict) -> None: ...

    async def load_auth(self) -> dict: ...

    async def save_auth(self, payload: dict) -> None: ...

    async def load_user(self, email: str) -> dict: ...

    async def save_user(self, email: str, payload: dict) -> None: ...


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

    @property
    def _player_path(self) -> Path:
        return self._path.with_name("players.index.json")

    async def load_players(self) -> dict | None:
        path = self._player_path
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > PLAYER_TTL_SECONDS:
            return None
        try:
            index = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return index if _current_version(index) else None

    async def save_players(self, index: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._player_path.write_text(json.dumps(index), encoding="utf-8")

    # The access allowlist lives OUTSIDE the feeds blob on purpose: the
    # hourly sync rebuilds that blob with an explicit carry-forward list,
    # and auth data must never depend on being remembered there (the
    # verdict-wipe bug class).
    @property
    def _auth_path(self) -> Path:
        return self._path.with_name("auth.json")

    async def load_auth(self) -> dict:
        if not self._auth_path.exists():
            return {}
        try:
            return json.loads(self._auth_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    async def save_auth(self, payload: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._auth_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._auth_path)

    # Per-user data ("My stuff"): each signed-in email gets its own slot,
    # so the base app stays shared while personal additions stay personal.
    def _user_path(self, email: str) -> Path:
        digest = hashlib.sha256(email.encode()).hexdigest()[:24]
        return self._path.with_name(f"user.{digest}.json")

    async def load_user(self, email: str) -> dict:
        path = self._user_path(email)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    async def save_user(self, email: str, payload: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        path = self._user_path(email)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)


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

    async def load_players(self) -> dict | None:
        raw = await self._redis.get(_PLAYER_KEY)
        if not raw:
            return None
        try:
            index = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return index if _current_version(index) else None

    async def save_players(self, index: dict) -> None:
        # TTL does the expiry, so a stale index can never be served.
        await self._redis.set(_PLAYER_KEY, json.dumps(index), ex=PLAYER_TTL_SECONDS)

    async def load_auth(self) -> dict:
        raw = await self._redis.get(_AUTH_KEY)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    async def save_auth(self, payload: dict) -> None:
        # Own key, no TTL: the allowlist must survive every sync rebuild
        # of the feeds blob (see the FileFeedStore note).
        await self._redis.set(_AUTH_KEY, json.dumps(payload))

    async def load_user(self, email: str) -> dict:
        raw = await self._redis.get(_USER_KEY_PREFIX + email)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    async def save_user(self, email: str, payload: dict) -> None:
        # No TTL: personal data is the user's own, not Yahoo-sourced --
        # the 24h deletion rule does not apply (docs/LICENSING.md).
        await self._redis.set(_USER_KEY_PREFIX + email, json.dumps(payload))


def build_feed_store(settings) -> FeedStore:
    if settings.token_store == "redis":
        return RedisFeedStore(settings.redis_url)
    return FileFeedStore(settings.feed_file_path)
