"""The state parameter is the only thing standing between us and a forged
callback, so it gets real tests."""

import time

from app.yahoo import oauth

SECRET = "test-secret"


def test_state_roundtrips():
    assert oauth.verify_state(SECRET, oauth.make_state(SECRET))


def test_state_rejects_wrong_secret():
    assert not oauth.verify_state("other-secret", oauth.make_state(SECRET))


def test_state_rejects_tampered_nonce():
    nonce, issued, signature = oauth.make_state(SECRET).split(".")
    assert not oauth.verify_state(SECRET, f"{nonce}x.{issued}.{signature}")


def test_state_rejects_malformed():
    for bad in ["", "nope", "a.b", "a.b.c.d"]:
        assert not oauth.verify_state(SECRET, bad)


def test_state_expires(monkeypatch):
    state = oauth.make_state(SECRET)
    # Capture the real clock first: oauth.time IS the time module, so a lambda
    # calling time.time() would recurse into its own patch.
    later = time.time() + oauth.STATE_TTL_SECONDS + 1
    monkeypatch.setattr(oauth.time, "time", lambda: later)
    assert not oauth.verify_state(SECRET, state)


def test_authorization_url_carries_params():
    from app.config import Settings

    settings = Settings(
        yahoo_client_id="abc123",
        yahoo_redirect_uri="https://example.com/auth/yahoo/callback",
    )
    url = oauth.authorization_url(settings, "state-value")
    assert url.startswith("https://api.login.yahoo.com/oauth2/request_auth?")
    assert "client_id=abc123" in url
    assert "response_type=code" in url
    assert "state=state-value" in url
    assert "scope=fspt-r" in url
