"""Yahoo three-legged OAuth2.

Flow:
  1. /auth/yahoo/login  -> redirect the browser to Yahoo with a signed `state`
  2. Yahoo redirects back to /auth/yahoo/callback?code=...&state=...
  3. Exchange the code for an access + refresh token pair, store it
  4. Every API call refreshes the access token on demand

Yahoo wants the client_id/client_secret as HTTP Basic auth on the token
endpoint, not as form fields.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import urlencode

import httpx

from ..config import YAHOO_AUTHORIZE_URL, YAHOO_TOKEN_URL, Settings
from ..store.base import TokenSet

# How long an in-flight authorization may sit before the callback is rejected.
STATE_TTL_SECONDS = 600


class OAuthError(RuntimeError):
    """Yahoo rejected the authorization or token request.

    Carries the token endpoint's HTTP status so callers can tell a
    rejected grant (4xx -- the stored refresh token is dead, the user
    must re-link) from Yahoo being down (5xx). None for failures with
    no response at all.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _sign(secret: str, message: str) -> str:
    digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def make_state(secret: str) -> str:
    """A nonce + timestamp + HMAC, so the callback can be verified statelessly.

    Serverless has no session to park a nonce in, so the state carries its own
    proof rather than being looked up server-side.
    """
    nonce = secrets.token_urlsafe(16)
    issued = str(int(time.time()))
    payload = f"{nonce}.{issued}"
    return f"{payload}.{_sign(secret, payload)}"


def verify_state(secret: str, state: str) -> bool:
    try:
        nonce, issued, signature = state.split(".")
    except ValueError:
        return False
    if not hmac.compare_digest(_sign(secret, f"{nonce}.{issued}"), signature):
        return False
    try:
        return (time.time() - int(issued)) <= STATE_TTL_SECONDS
    except ValueError:
        return False


def authorization_url(settings: Settings, state: str) -> str:
    params = {
        "client_id": settings.yahoo_client_id,
        "redirect_uri": settings.yahoo_redirect_uri,
        "response_type": "code",
        "scope": settings.yahoo_scope,
        "state": state,
    }
    return f"{YAHOO_AUTHORIZE_URL}?{urlencode(params)}"


def _basic_auth_header(settings: Settings) -> str:
    raw = f"{settings.yahoo_client_id}:{settings.yahoo_client_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


async def _post_token(settings: Settings, form: dict[str, str]) -> TokenSet:
    headers = {
        "Authorization": _basic_auth_header(settings),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(YAHOO_TOKEN_URL, data=form, headers=headers)

    if response.status_code != 200:
        raise OAuthError(
            f"Yahoo token endpoint returned {response.status_code}: {response.text[:400]}",
            status=response.status_code,
        )
    return TokenSet.from_response(response.json())


async def exchange_code(settings: Settings, code: str) -> TokenSet:
    """Leg 3: authorization code -> token pair."""
    return await _post_token(
        settings,
        {
            "grant_type": "authorization_code",
            "code": code,
            # Yahoo requires redirect_uri again here and matches it exactly.
            "redirect_uri": settings.yahoo_redirect_uri,
        },
    )


async def refresh(settings: Settings, tokens: TokenSet) -> TokenSet:
    """Trade the refresh token for a fresh access token."""
    refreshed = await _post_token(
        settings,
        {
            "grant_type": "refresh_token",
            "refresh_token": tokens.refresh_token,
            "redirect_uri": settings.yahoo_redirect_uri,
        },
    )
    # Yahoo usually returns the same refresh token, but not always -- keep
    # whatever came back, falling back to the one we already had.
    if not refreshed.refresh_token:
        refreshed.refresh_token = tokens.refresh_token
    return refreshed
