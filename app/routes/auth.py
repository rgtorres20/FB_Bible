"""The OAuth endpoints -- the actual Phase 2 deliverable."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from ..config import Settings, get_settings
from ..deps import DEFAULT_USER_KEY, get_store
from ..store import TokenStore
from ..yahoo import oauth

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/yahoo", tags=["auth"])


@router.get("/login", summary="Start the Yahoo OAuth flow")
async def login(settings: Settings = Depends(get_settings)) -> RedirectResponse:
    if not settings.configured:
        raise HTTPException(
            status_code=503,
            detail="Yahoo credentials are not configured. See docs/YAHOO_SETUP.md.",
        )
    state = oauth.make_state(settings.session_secret)
    return RedirectResponse(oauth.authorization_url(settings, state), status_code=307)


@router.get("/callback", summary="Yahoo redirects back here with the code")
async def callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
    store: TokenStore = Depends(get_store),
) -> HTMLResponse:
    if error:
        raise HTTPException(
            status_code=400,
            detail=f"Yahoo denied the request: {error} {error_description or ''}".strip(),
        )
    if not code:
        raise HTTPException(status_code=400, detail="Missing ?code from Yahoo.")
    if not state or not oauth.verify_state(settings.session_secret, state):
        # Either a forged callback or one that sat around past STATE_TTL.
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state.")

    try:
        tokens = await oauth.exchange_code(settings, code)
    except oauth.OAuthError as exc:
        log.exception("Token exchange failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await store.put(DEFAULT_USER_KEY, tokens)
    log.info("Yahoo account linked (guid=%s)", tokens.xoauth_yahoo_guid or "unknown")

    # Landing page rather than a redirect: the browser app isn't necessarily
    # served from this origin yet.
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8>"
        "<title>Yahoo linked</title>"
        "<body style='font:16px/1.5 system-ui;max-width:34rem;margin:4rem auto'>"
        "<h1>Yahoo account linked</h1>"
        "<p>Tokens stored. You can close this tab and go back to Fantasy Sports Bible.</p>"
        "<p><a href='/api/leagues'>Check your leagues &rarr;</a></p>"
    )


@router.get("/status", summary="Is a Yahoo account currently linked?")
async def status(store: TokenStore = Depends(get_store)) -> dict:
    tokens = await store.get(DEFAULT_USER_KEY)
    if tokens is None:
        return {"linked": False}
    return {
        "linked": True,
        "guid": tokens.xoauth_yahoo_guid or None,
        "access_token_expired": tokens.expired,
        "expires_at": tokens.expires_at,
    }


@router.post("/logout", summary="Forget the stored tokens")
async def logout(store: TokenStore = Depends(get_store)) -> dict:
    await store.delete(DEFAULT_USER_KEY)
    return {"linked": False}
