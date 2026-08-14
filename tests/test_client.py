"""Token lifecycle tests.

This is the code most likely to fail in production and the hardest to notice
when it does: an access token dies after an hour, and if the refresh path is
broken the app just starts returning 401s days later. All HTTP is mocked, so
these run with no network and no Yahoo credentials.
"""

import time

import httpx
import pytest
import respx

from app.config import YAHOO_API_BASE, YAHOO_TOKEN_URL, Settings
from app.store.base import TokenSet
from app.yahoo import NotAuthenticated, YahooAPIError, YahooClient, oauth

SETTINGS = Settings(
    yahoo_client_id="test-id",
    yahoo_client_secret="test-secret",
    yahoo_redirect_uri="https://example.com/auth/yahoo/callback",
)

LEAGUE_URL = f"{YAHOO_API_BASE}/league/nfl.l.192426"
PATH = "league/nfl.l.192426"


class MemoryStore:
    """In-memory TokenStore, so these tests touch no disk and no Redis."""

    def __init__(self, tokens: TokenSet | None = None) -> None:
        self._data = {"owner": tokens} if tokens else {}

    async def get(self, key):
        return self._data.get(key)

    async def put(self, key, tokens):
        self._data[key] = tokens

    async def delete(self, key):
        self._data.pop(key, None)


def valid_token() -> TokenSet:
    return TokenSet(access_token="good", refresh_token="r1", expires_at=time.time() + 3600)


def expired_token() -> TokenSet:
    return TokenSet(access_token="old", refresh_token="r1", expires_at=time.time() - 10)


def token_response(access: str, refresh: str | None = "r2") -> httpx.Response:
    body = {"access_token": access, "expires_in": 3600}
    if refresh is not None:
        body["refresh_token"] = refresh
    return httpx.Response(200, json=body)


async def test_missing_tokens_raise_not_authenticated():
    client = YahooClient(SETTINGS, MemoryStore(), "owner")
    with pytest.raises(NotAuthenticated):
        await client.get(PATH)


@respx.mock
async def test_expired_token_refreshes_before_the_call():
    store = MemoryStore(expired_token())
    token_route = respx.post(YAHOO_TOKEN_URL).mock(return_value=token_response("new"))
    api_route = respx.get(url__startswith=LEAGUE_URL).mock(
        return_value=httpx.Response(200, json={"fantasy_content": {}})
    )

    await YahooClient(SETTINGS, store, "owner").get(PATH)

    assert token_route.called
    assert api_route.calls[0].request.headers["Authorization"] == "Bearer new"
    # Must be persisted, or every single request would refresh again.
    stored = await store.get("owner")
    assert stored.access_token == "new"
    assert not stored.expired


@respx.mock
async def test_valid_token_is_used_without_refreshing():
    store = MemoryStore(valid_token())
    token_route = respx.post(YAHOO_TOKEN_URL).mock(return_value=token_response("unwanted"))
    api_route = respx.get(url__startswith=LEAGUE_URL).mock(
        return_value=httpx.Response(200, json={"fantasy_content": {}})
    )

    await YahooClient(SETTINGS, store, "owner").get(PATH)

    assert not token_route.called
    assert api_route.calls[0].request.headers["Authorization"] == "Bearer good"


@respx.mock
async def test_401_triggers_one_refresh_and_retry():
    """Yahoo can reject a token we believe is still valid (revoked, rotated)."""
    store = MemoryStore(valid_token())
    respx.post(YAHOO_TOKEN_URL).mock(return_value=token_response("recovered"))
    api_route = respx.get(url__startswith=LEAGUE_URL).mock(
        side_effect=[
            httpx.Response(401, text="token expired"),
            httpx.Response(200, json={"fantasy_content": {"ok": 1}}),
        ]
    )

    result = await YahooClient(SETTINGS, store, "owner").get(PATH)

    assert result == {"fantasy_content": {"ok": 1}}
    assert api_route.call_count == 2
    assert api_route.calls[1].request.headers["Authorization"] == "Bearer recovered"


@respx.mock
async def test_second_401_gives_up_instead_of_looping():
    store = MemoryStore(valid_token())
    respx.post(YAHOO_TOKEN_URL).mock(return_value=token_response("still-bad"))
    api_route = respx.get(url__startswith=LEAGUE_URL).mock(
        return_value=httpx.Response(401, text="nope")
    )

    with pytest.raises(YahooAPIError) as exc:
        await YahooClient(SETTINGS, store, "owner").get(PATH)

    assert exc.value.status == 401
    assert api_route.call_count == 2  # one retry, not an infinite loop


@respx.mock
async def test_non_401_error_is_surfaced_without_refreshing():
    store = MemoryStore(valid_token())
    token_route = respx.post(YAHOO_TOKEN_URL).mock(return_value=token_response("x"))
    respx.get(url__startswith=LEAGUE_URL).mock(return_value=httpx.Response(999, text="boom"))

    with pytest.raises(YahooAPIError) as exc:
        await YahooClient(SETTINGS, store, "owner").get(PATH)

    assert exc.value.status == 999
    assert not token_route.called


@respx.mock
async def test_refresh_keeps_existing_refresh_token_when_yahoo_omits_it():
    """Yahoo does not always return refresh_token on a refresh. Dropping it
    would silently orphan the account at the next expiry."""
    respx.post(YAHOO_TOKEN_URL).mock(return_value=token_response("new", refresh=None))

    refreshed = await oauth.refresh(SETTINGS, expired_token())

    assert refreshed.access_token == "new"
    assert refreshed.refresh_token == "r1"


@respx.mock
async def test_token_request_uses_basic_auth_not_form_fields():
    """Yahoo requires the client credentials as HTTP Basic, and rejects them
    as form fields -- an easy thing to regress."""
    route = respx.post(YAHOO_TOKEN_URL).mock(return_value=token_response("new"))

    await oauth.exchange_code(SETTINGS, "the-code")

    request = route.calls[0].request
    assert request.headers["Authorization"].startswith("Basic ")
    body = request.content.decode()
    assert "test-secret" not in body
    assert "grant_type=authorization_code" in body
    assert "code=the-code" in body


@respx.mock
async def test_token_endpoint_failure_raises_oauth_error():
    respx.post(YAHOO_TOKEN_URL).mock(
        return_value=httpx.Response(400, text='{"error":"invalid_grant"}')
    )

    with pytest.raises(oauth.OAuthError, match="400"):
        await oauth.exchange_code(SETTINGS, "stale-code")


async def test_file_store_encrypts_tokens_on_disk(tmp_path):
    """The refresh token must never be readable in the file."""
    from cryptography.fernet import Fernet

    from app.store.crypto import TokenCipher
    from app.store.file_store import FileTokenStore

    path = tmp_path / "tokens.json"
    store = FileTokenStore(str(path), TokenCipher(Fernet.generate_key().decode()))

    await store.put("owner", TokenSet("secret-access", "secret-refresh", time.time() + 60))

    raw = path.read_text(encoding="utf-8")
    assert "secret-refresh" not in raw
    assert "secret-access" not in raw

    assert (await store.get("owner")).refresh_token == "secret-refresh"
    await store.delete("owner")
    assert await store.get("owner") is None
