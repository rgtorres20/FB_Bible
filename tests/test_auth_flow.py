"""The OAuth callback success path, end to end with Yahoo mocked.

Previously only the rejection cases were covered, so nothing proved a real
authorization actually results in a stored, usable token.
"""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app import main
from app.config import YAHOO_TOKEN_URL, get_settings
from app.deps import get_store
from app.store import TokenCipher, build_token_store
from app.store.base import TokenSet
from app.yahoo import oauth


class MemoryStore:
    def __init__(self):
        self.saved: TokenSet | None = None

    async def get(self, key):
        return self.saved

    async def put(self, key, tokens):
        self.saved = tokens

    async def delete(self, key):
        self.saved = None


@pytest.fixture
def client(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "yahoo_client_id", "cid", raising=False)
    monkeypatch.setattr(settings, "yahoo_client_secret", "csecret", raising=False)
    store = MemoryStore()
    main.app.dependency_overrides[get_store] = lambda: store
    yield TestClient(main.app), store, settings
    main.app.dependency_overrides.clear()


@respx.mock
def test_callback_exchanges_the_code_and_stores_the_token(client):
    c, store, settings = client
    respx.post(YAHOO_TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "at",
                "refresh_token": "rt",
                "expires_in": 3600,
                "xoauth_yahoo_guid": "guid-1",
            },
        )
    )
    state = oauth.make_state(settings.session_secret)

    response = c.get(f"/auth/yahoo/callback?code=the-code&state={state}")

    assert response.status_code == 200
    assert "Yahoo account linked" in response.text
    assert store.saved.access_token == "at"
    assert store.saved.refresh_token == "rt"
    assert not store.saved.expired


@respx.mock
def test_status_reports_linked_after_a_successful_callback(client):
    c, store, settings = client
    respx.post(YAHOO_TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600}
        )
    )
    state = oauth.make_state(settings.session_secret)

    assert c.get("/auth/yahoo/status").json()["linked"] is False
    c.get(f"/auth/yahoo/callback?code=x&state={state}")

    assert c.get("/auth/yahoo/status").json()["linked"] is True


@respx.mock
def test_status_never_leaks_the_tokens(client):
    """Expiry metadata is useful; the secrets are not ours to hand out."""
    c, store, settings = client
    store.saved = TokenSet(access_token="super-secret", refresh_token="also-secret", expires_at=9e9)

    body = c.get("/auth/yahoo/status").text

    assert "super-secret" not in body
    assert "also-secret" not in body


@respx.mock
def test_a_yahoo_rejection_at_exchange_becomes_502(client):
    c, _, settings = client
    respx.post(YAHOO_TOKEN_URL).mock(
        return_value=httpx.Response(400, text='{"error":"invalid_grant"}')
    )
    state = oauth.make_state(settings.session_secret)

    response = c.get(f"/auth/yahoo/callback?code=stale&state={state}")

    assert response.status_code == 502


def test_login_redirects_to_yahoo_once_configured(client):
    c, _, _ = client

    response = c.get("/auth/yahoo/login", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].startswith(
        "https://api.login.yahoo.com/oauth2/request_auth"
    )


def test_logout_clears_the_stored_token(client):
    c, store, _ = client
    store.saved = TokenSet(access_token="a", refresh_token="b", expires_at=9e9)

    assert c.post("/auth/yahoo/logout").json() == {"linked": False}
    assert store.saved is None


# --- crypto and store selection, previously thin --------------------------


def test_cipher_refuses_to_start_without_a_key():
    """Silently running unencrypted would be the worst possible default."""
    with pytest.raises(ValueError, match="TOKEN_ENCRYPTION_KEY"):
        TokenCipher("")


def test_a_blob_from_a_different_key_reads_as_absent_not_a_crash():
    """Rotating the key must log you out, not 500 every request."""
    from cryptography.fernet import Fernet

    blob = TokenCipher(Fernet.generate_key().decode()).encrypt({"a": 1})

    assert TokenCipher(Fernet.generate_key().decode()).decrypt(blob) is None


def test_tampered_ciphertext_reads_as_absent():
    from cryptography.fernet import Fernet

    cipher = TokenCipher(Fernet.generate_key().decode())
    blob = cipher.encrypt({"a": 1})

    assert cipher.decrypt(blob[:-4] + "AAAA") is None


def test_build_token_store_selects_redis_when_configured():
    from app.config import Settings
    from app.store.redis_store import RedisTokenStore

    settings = Settings(
        token_store="redis",
        redis_url="redis://localhost:6379",
        token_encryption_key=__import__("cryptography.fernet", fromlist=["Fernet"])
        .Fernet.generate_key()
        .decode(),
    )

    assert isinstance(build_token_store(settings), RedisTokenStore)


def test_redis_token_store_requires_a_url():
    from cryptography.fernet import Fernet

    from app.store.redis_store import RedisTokenStore

    with pytest.raises(ValueError, match="REDIS_URL"):
        RedisTokenStore("", TokenCipher(Fernet.generate_key().decode()))
