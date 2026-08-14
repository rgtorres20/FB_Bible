"""Authenticated Yahoo Fantasy API client.

Owns the one thing callers should never have to think about: making sure the
access token is fresh before the request goes out, and re-refreshing once if
Yahoo rejects it anyway.
"""

from __future__ import annotations

import logging

import httpx

from ..config import YAHOO_API_BASE, Settings
from ..store.base import TokenSet, TokenStore
from . import oauth

log = logging.getLogger(__name__)


class NotAuthenticated(RuntimeError):
    """No stored tokens for this user -- send them through /auth/yahoo/login."""


class YahooAPIError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"Yahoo API returned {status}: {body[:400]}")
        self.status = status
        self.body = body


class YahooClient:
    def __init__(self, settings: Settings, store: TokenStore, user_key: str) -> None:
        self._settings = settings
        self._store = store
        self._user_key = user_key

    async def _tokens(self) -> TokenSet:
        tokens = await self._store.get(self._user_key)
        if tokens is None:
            raise NotAuthenticated(f"No Yahoo tokens stored for {self._user_key!r}")
        if tokens.expired:
            log.info("Access token expired for %s, refreshing", self._user_key)
            tokens = await oauth.refresh(self._settings, tokens)
            await self._store.put(self._user_key, tokens)
        return tokens

    async def get(self, path: str, **params: str) -> dict:
        """GET a Fantasy API resource. `path` is relative to /fantasy/v2."""
        tokens = await self._tokens()
        params.setdefault("format", "json")
        url = f"{YAHOO_API_BASE}/{path.lstrip('/')}"

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {tokens.access_token}"},
            )

            # A 401 here means the token died early (revoked, or Yahoo rotated
            # it). One forced refresh, then give up and make the user re-link.
            if response.status_code == 401:
                log.warning("Yahoo returned 401 for %s, forcing refresh", path)
                tokens = await oauth.refresh(self._settings, tokens)
                await self._store.put(self._user_key, tokens)
                response = await client.get(
                    url,
                    params=params,
                    headers={"Authorization": f"Bearer {tokens.access_token}"},
                )

        if response.status_code != 200:
            raise YahooAPIError(response.status_code, response.text)
        return response.json()

    # --- Resources the Fantasy Bible actually needs (blueprint phase 2) -----

    async def user_leagues(self, game: str = "nfl") -> dict:
        """Every league the signed-in user has in the current NFL season."""
        return await self.get(f"users;use_login=1/games;game_keys={game}/leagues")

    async def league(self, league_key: str) -> dict:
        return await self.get(f"league/{league_key}")

    async def league_teams(self, league_key: str) -> dict:
        return await self.get(f"league/{league_key}/teams")

    async def roster(self, team_key: str, week: int | None = None) -> dict:
        """Live roster for a team. Omit `week` for the current one."""
        suffix = f";week={week}" if week is not None else ""
        return await self.get(f"team/{team_key}/roster{suffix}")

    async def draft_results(self, league_key: str) -> dict:
        """Every pick in the league -- this is what kills manual pick entry."""
        return await self.get(f"league/{league_key}/draftresults")

    async def scoreboard(self, league_key: str, week: int | None = None) -> dict:
        suffix = f";week={week}" if week is not None else ""
        return await self.get(f"league/{league_key}/scoreboard{suffix}")

    async def transactions(self, league_key: str) -> dict:
        """Adds/drops/trades -- the Yahoo half of the wire."""
        return await self.get(f"league/{league_key}/transactions")
