"""Serverless token store, backed by Redis (Upstash works well on Vercel).

Uses redis.asyncio, which speaks plain RESP over TLS -- so any managed Redis
with a rediss:// URL works, not just Upstash.
"""

from __future__ import annotations

import redis.asyncio as redis

from .base import TokenSet
from .crypto import TokenCipher

_PREFIX = "fbbible:tokens:"


class RedisTokenStore:
    def __init__(self, url: str, cipher: TokenCipher) -> None:
        if not url:
            raise ValueError("REDIS_URL is required when TOKEN_STORE=redis")
        self._redis = redis.from_url(url, decode_responses=True)
        self._cipher = cipher

    async def get(self, key: str) -> TokenSet | None:
        blob = await self._redis.get(_PREFIX + key)
        if not blob:
            return None
        payload = self._cipher.decrypt(blob)
        return TokenSet.from_dict(payload) if payload else None

    async def put(self, key: str, tokens: TokenSet) -> None:
        # No TTL: the refresh token outlives the access token and is the whole
        # point of persisting here.
        await self._redis.set(_PREFIX + key, self._cipher.encrypt(tokens.to_dict()))

    async def delete(self, key: str) -> None:
        await self._redis.delete(_PREFIX + key)

    async def aclose(self) -> None:
        await self._redis.aclose()
