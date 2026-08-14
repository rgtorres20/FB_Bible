"""Shared FastAPI dependencies."""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends

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
    return _store_singleton()


def get_yahoo(
    settings: Settings = Depends(get_settings),
    store: TokenStore = Depends(get_store),
) -> YahooClient:
    return YahooClient(settings, store, DEFAULT_USER_KEY)
