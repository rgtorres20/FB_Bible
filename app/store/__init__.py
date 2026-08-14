"""Token store selection."""

from __future__ import annotations

from ..config import Settings
from .base import TokenSet, TokenStore
from .crypto import TokenCipher
from .file_store import FileTokenStore

__all__ = ["TokenSet", "TokenStore", "TokenCipher", "build_token_store"]


def build_token_store(settings: Settings) -> TokenStore:
    cipher = TokenCipher(settings.token_encryption_key)
    if settings.token_store == "redis":
        # Imported lazily so local dev doesn't need the redis package resolved.
        from .redis_store import RedisTokenStore

        return RedisTokenStore(settings.redis_url, cipher)
    return FileTokenStore(settings.token_file_path, cipher)
