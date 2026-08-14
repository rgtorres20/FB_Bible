"""Token storage.

Phase 2 runs serverless, where there is no writable disk and no process to
hold state between requests, so the token pair has to live somewhere external
from day one. Everything above this layer talks to `TokenStore`, so swapping
file -> redis -> Postgres (Phase 3) is a config change, not a rewrite.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Protocol


@dataclass(slots=True)
class TokenSet:
    access_token: str
    refresh_token: str
    # Absolute unix expiry, not the relative expires_in Yahoo returns.
    expires_at: float
    # Yahoo's opaque per-user id; useful once more than one account signs in.
    xoauth_yahoo_guid: str = ""
    token_type: str = "bearer"

    @classmethod
    def from_response(cls, payload: dict) -> TokenSet:
        """Build from Yahoo's /get_token JSON response."""
        return cls(
            access_token=payload["access_token"],
            refresh_token=payload["refresh_token"],
            # Shave 60s off so a token can't expire mid-flight.
            expires_at=time.time() + float(payload.get("expires_in", 3600)) - 60,
            xoauth_yahoo_guid=payload.get("xoauth_yahoo_guid", ""),
            token_type=payload.get("token_type", "bearer"),
        )

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> TokenSet:
        return cls(**data)


class TokenStore(Protocol):
    """Persists one TokenSet per user key."""

    async def get(self, key: str) -> TokenSet | None: ...

    async def put(self, key: str, tokens: TokenSet) -> None: ...

    async def delete(self, key: str) -> None: ...
