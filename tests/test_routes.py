"""Route-level checks that need no Yahoo credentials and no network."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_configuration():
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["encryption_configured"] is True
    assert body["league_keys"] == ["nfl.l.192426", "nfl.l.811739"]


def test_login_is_unavailable_without_credentials():
    # No YAHOO_CLIENT_ID in the test env -- should say so, not 500.
    response = client.get("/auth/yahoo/login", follow_redirects=False)
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_callback_rejects_bad_state():
    response = client.get("/auth/yahoo/callback", params={"code": "x", "state": "forged"})
    assert response.status_code == 400
    assert "state" in response.json()["detail"].lower()


def test_callback_requires_code():
    response = client.get("/auth/yahoo/callback", params={"state": "whatever"})
    assert response.status_code == 400


def test_callback_surfaces_yahoo_denial():
    response = client.get(
        "/auth/yahoo/callback",
        params={"error": "access_denied", "error_description": "user said no"},
    )
    assert response.status_code == 400
    assert "access_denied" in response.json()["detail"]


def test_api_returns_401_when_not_linked():
    response = client.get("/api/leagues")
    assert response.status_code == 401
    assert "/auth/yahoo/login" in response.json()["detail"]


def test_unconfigured_token_store_returns_503_not_500(monkeypatch):
    """A missing TOKEN_ENCRYPTION_KEY must name itself, not surface as a bare
    500. This is what the live deploy did before the fix."""
    import pytest
    from fastapi import HTTPException

    from app import deps

    def boom():
        raise ValueError("TOKEN_ENCRYPTION_KEY is not set. Generate one with: ...")

    monkeypatch.setattr(deps, "_store_singleton", boom)

    with pytest.raises(HTTPException) as exc:
        deps.get_store()

    assert exc.value.status_code == 503
    assert "TOKEN_ENCRYPTION_KEY" in exc.value.detail


def test_sync_requires_a_token():
    """SYNC_TOKEN is unset in tests, so scheduled sync must report itself
    disabled rather than quietly polling five publishers."""
    response = client.post("/internal/sync")
    assert response.status_code == 503
    assert "SYNC_TOKEN" in response.json()["detail"]


def test_feeds_endpoint_is_readable_when_empty():
    response = client.get("/api/feeds")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
