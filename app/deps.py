"""Shared FastAPI dependencies."""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, HTTPException

from .config import Settings, get_settings
from .store import TokenStore, build_token_store
from .yahoo import YahooClient

# Phase 2 is single-user: one Yahoo account (the owner's) links the leagues.
# Making it a named key now means multi-user is a routing change later, not a
# storage migration.
DEFAULT_USER_KEY = "owner"


@lru_cache
def _store_singleton() -> TokenStore:
    return build_token_store(get_settings())


def get_store() -> TokenStore:
    """Resolve the token store, or explain why it can't be built.

    A missing TOKEN_ENCRYPTION_KEY or REDIS_URL raises ValueError, which
    FastAPI would otherwise surface as a bare 500 "Internal Server Error" --
    the exact mystery-failure this project's /health endpoint exists to
    prevent. Config problems are 503 with the offending setting named.
    """
    try:
        return _store_singleton()
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Token store is not configured: {exc}",
        ) from exc


def get_yahoo(
    settings: Settings = Depends(get_settings),
    store: TokenStore = Depends(get_store),
) -> YahooClient:
    return YahooClient(settings, store, DEFAULT_USER_KEY)
