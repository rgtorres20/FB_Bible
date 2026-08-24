"""Storage for polled feed items.

Separate from the token store on purpose: these are public headlines, so no
encryption, and the retention rules are different. Yahoo's 24-hour deletion
rule does not apply here -- none of this is Yahoo user data.

The one exception is the access blob under `fbbible:auth`. It is not a
headline: since Aug 24 it carries password hashes, so it is encrypted at
rest with the same `TokenCipher` the Yahoo tokens use. See `_AuthVault`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

_KEY = "fbbible:feeds"
_USER_KEY_PREFIX = "fbbible:user:"


def _current_version(index: dict) -> bool:
    from .players import INDEX_VERSION

    return index.get("v") == INDEX_VERSION


_PLAYER_KEY = "fbbible:players"
# Sleeper asks callers not to pull the 14MB dump more than once a day.
# How long a stored index is kept at all. Deliberately far longer than the
# refresh interval (`players.FRESH_SECONDS`): this is a backstop, not an
# expiry, so that a run of failed refetches degrades to a stale board that
# says so rather than to no board at all.
PLAYER_RETENTION_SECONDS = 14 * 24 * 60 * 60


_AUTH_KEY = "fbbible:auth"
# The prediction ledger. Its own key for the same reason as the
# allowlist: the sync rebuilds the feeds blob from an explicit
# carry-forward list, and a record of what the app predicted must not
# depend on being remembered there. Losing it would not just drop data
# -- it would silently reset the accuracy history to "no evidence".
_SCORECARD_KEY = "fbbible:scorecard"


class AuthUnreadable(RuntimeError):
    """The stored access blob exists but could not be decrypted.

    Raised rather than returning {} on purpose, and it is the whole point
    of this class. An empty dict is a *legitimate* value -- it is what a
    fresh deployment holds -- so handing one back for a blob written under
    a different TOKEN_ENCRYPTION_KEY would make "nobody is enrolled yet"
    and "the allowlist is unreadable" the same answer. Every caller that
    adds or removes a user does load -> mutate -> save, so that mistake
    would not merely deny access, it would overwrite the allowlist with
    the empty dict on the next write and delete every user for good. This
    is the verdict-wipe bug class (docs/GAP_REVIEW.md), pre-empted.

    `request_allowed` already fails closed on any exception, so raising
    also keeps the gate shut instead of open.
    """


class _AuthVault:
    """Encrypt the access blob at rest, and read what is already there.

    One class, shared by both stores, because two copies of a migration
    rule is how one of them stays wrong (the rotoworld-cleaner lesson).

    Reading handles three shapes, and the order matters:

      * nothing stored          -> {}, a fresh deployment
      * plaintext JSON          -> returned as-is, then re-encrypted by the
                                   next save. Blobs written before Aug 24
                                   are this, and locking those users out
                                   to gain encryption would be a poor trade
      * a Fernet token          -> decrypted, or AuthUnreadable

    A Fernet token is urlsafe base64 and a JSON object starts with `{`, so
    the two can never be mistaken for each other.

    With no TOKEN_ENCRYPTION_KEY configured this writes plaintext, exactly
    as before. That is a real downgrade, so it is *reported* rather than
    assumed: `/health` says `auth_at_rest`, and it is the deployment's job
    to set the key. Production already must -- the token store refuses to
    build without one.
    """

    def __init__(self, key: str) -> None:
        self._cipher = None
        if key:
            from ..store.crypto import TokenCipher

            self._cipher = TokenCipher(key)

    @property
    def encrypting(self) -> bool:
        return self._cipher is not None

    def read(self, raw: str | None) -> dict:
        if not raw:
            return {}
        text = raw.strip()
        if text.startswith("{"):
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise AuthUnreadable("stored access blob is not valid JSON") from exc
        if self._cipher is None:
            raise AuthUnreadable(
                "stored access blob is encrypted but TOKEN_ENCRYPTION_KEY is not set"
            )
        payload = self._cipher.decrypt(text)
        if payload is None:
            raise AuthUnreadable(
                "stored access blob could not be decrypted -- wrong TOKEN_ENCRYPTION_KEY?"
            )
        return payload

    def write(self, payload: dict) -> str:
        if self._cipher is None:
            return json.dumps(payload)
        return self._cipher.encrypt(payload)


class FeedStore(Protocol):
    async def load(self) -> dict: ...

    async def save(self, payload: dict) -> None: ...

    async def load_players(self) -> dict | None: ...

    async def save_players(self, index: dict) -> None: ...

    async def load_auth(self) -> dict: ...

    async def save_auth(self, payload: dict) -> None: ...

    async def load_scorecard(self) -> dict: ...

    async def save_scorecard(self, payload: dict) -> None: ...

    async def load_user(self, email: str) -> dict: ...

    async def save_user(self, email: str, payload: dict) -> None: ...


class FileFeedStore:
    """Local dev. Not for serverless -- no writable disk there."""

    def __init__(self, path: str, encryption_key: str = "") -> None:
        self._path = Path(path)
        self._vault = _AuthVault(encryption_key)

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
        """The stored index, however old. Age is the caller's business.

        This used to return None past the TTL, which made "stale" and
        "absent" the same answer -- so a failed refetch served empty
        boards rather than yesterday's players (Aug 22 incident,
        docs/GAP_REVIEW.md). Freshness is now `players.needs_refresh`.
        """
        path = self._player_path
        if not path.exists():
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

    @property
    def _scorecard_path(self) -> Path:
        return self._path.with_name("scorecard.json")

    async def load_scorecard(self) -> dict:
        if not self._scorecard_path.exists():
            return {}
        try:
            return json.loads(self._scorecard_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    async def save_scorecard(self, payload: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._scorecard_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._scorecard_path)

    async def load_auth(self) -> dict:
        # An OSError still reads as {} -- a file that is not there is a
        # deployment with nobody enrolled. A file that IS there and cannot
        # be read is AuthUnreadable, raised by the vault: see its docstring
        # for why the two must not collapse into one answer.
        if not self._auth_path.exists():
            return {}
        try:
            raw = self._auth_path.read_text(encoding="utf-8")
        except OSError:
            return {}
        return self._vault.read(raw)

    async def save_auth(self, payload: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._auth_path.with_suffix(".tmp")
        tmp.write_text(self._vault.write(payload), encoding="utf-8")
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
    def __init__(self, url: str, encryption_key: str = "") -> None:
        import redis.asyncio as redis

        self._redis = redis.from_url(url, decode_responses=True)
        self._vault = _AuthVault(encryption_key)

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
        # Retention, not expiry. The TTL used to be the freshness rule,
        # which meant the index simply vanished every 20 hours and any
        # sync whose refetch failed left every board empty -- the one feed
        # in the app that degraded to nothing instead of to yesterday's
        # copy. It is now a long backstop against an abandoned deployment;
        # `players.needs_refresh` decides when to fetch, and a failed
        # fetch keeps what is already here.
        await self._redis.set(_PLAYER_KEY, json.dumps(index), ex=PLAYER_RETENTION_SECONDS)

    async def load_auth(self) -> dict:
        return self._vault.read(await self._redis.get(_AUTH_KEY))

    async def save_auth(self, payload: dict) -> None:
        # Own key, no TTL: the allowlist must survive every sync rebuild
        # of the feeds blob (see the FileFeedStore note). Encrypted, since
        # Aug 24, because this blob carries password hashes.
        await self._redis.set(_AUTH_KEY, self._vault.write(payload))

    async def load_scorecard(self) -> dict:
        raw = await self._redis.get(_SCORECARD_KEY)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    async def save_scorecard(self, payload: dict) -> None:
        # Own key, no TTL. The ledger only grows and is the evidence the
        # accuracy page reads; a TTL would quietly delete the record.
        await self._redis.set(_SCORECARD_KEY, json.dumps(payload))

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
    key = getattr(settings, "token_encryption_key", "") or ""
    if settings.token_store == "redis":
        return RedisFeedStore(settings.redis_url, key)
    return FileFeedStore(settings.feed_file_path, key)
