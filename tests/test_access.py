"""The login gate and the owner's email allowlist.

The contract: everything is inert until the owner fully enables the gate
(a partial enable stays open rather than locking the owner out); the
owner signs in with the env-held code; invites are one-time links whose
plaintext exists only in the owner's admin response; removal revokes on
the very next request even for a still-valid cookie; and the runner's
X-Sync-Token keeps the watchdog and sync working through a closed gate.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app import authn, main
from app.config import get_settings
from app.feeds.store import FileFeedStore
from app.routes import access as access_route
from app.routes import feeds as feeds_route

NOW = 1_755_000_000.0


# --- the primitives ----------------------------------------------------------


def test_session_round_trips_and_rejects_tampering():
    token = authn.mint_session("Robert@Example.com", "s3cret", NOW)
    assert authn.read_session(token, "s3cret", NOW) == "robert@example.com"
    # Wrong key, tampered payload, garbage, expiry: all just "signed out".
    assert authn.read_session(token, "other", NOW) is None
    assert authn.read_session(token[:-4] + "AAAA", "s3cret", NOW) is None
    assert authn.read_session("not-base64!!", "s3cret", NOW) is None
    assert authn.read_session(token, "s3cret", NOW + authn.SESSION_DAYS * 86400 + 1) is None


def test_invites_are_one_time_and_removal_revokes_everything():
    auth, token = authn.mint_invite({}, "Friend@x.com", NOW)
    # Only the hash is stored.
    assert token not in str(auth)
    auth, email = authn.accept_invite(auth, token, NOW)
    assert email == "friend@x.com"
    assert authn.is_allowed(auth, "friend@x.com", "owner@x.com")
    # Burned: a second accept fails.
    _, second = authn.accept_invite(auth, token, NOW)
    assert second is None
    # An expired invite never lands.
    auth2, token2 = authn.mint_invite({}, "late@x.com", NOW)
    _, late = authn.accept_invite(auth2, token2, NOW + authn.INVITE_DAYS * 86400 + 1)
    assert late is None
    # Removal drops the allowlist entry and any pending invites at once.
    auth3, _ = authn.mint_invite(auth, "friend@x.com", NOW)
    auth3 = authn.remove_email(auth3, "friend@x.com")
    assert not authn.is_allowed(auth3, "friend@x.com", "owner@x.com")
    assert not auth3["invites"]


def test_owner_always_allowed_without_a_store_entry():
    assert authn.is_allowed({}, "Owner@X.com", "owner@x.com")
    assert not authn.is_allowed({}, "stranger@x.com", "owner@x.com")


# --- the gate ----------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    s = get_settings()
    monkeypatch.setattr(s, "app_auth", True, raising=False)
    monkeypatch.setattr(s, "owner_email", "owner@example.com", raising=False)
    monkeypatch.setattr(s, "app_owner_code", "open-sesame", raising=False)
    monkeypatch.setattr(s, "session_secret", "unit-test-secret", raising=False)
    monkeypatch.setattr(s, "sync_token", "runner-token", raising=False)
    # Route handlers get the store via Depends; the middleware builds its
    # own, so both paths are pointed at the same temp store.
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    monkeypatch.setattr(access_route, "build_feed_store", lambda _s: store)
    yield TestClient(main.app), store
    main.app.dependency_overrides.clear()


def _owner_login(c: TestClient) -> None:
    r = c.post(
        "/login",
        data={"email": "Owner@Example.com", "code": "open-sesame"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"] == "/app/"
    assert authn.SESSION_COOKIE in c.cookies


def test_gate_blocks_anonymous_and_wrong_code_leaves_no_cookie(client):
    c, _ = client
    r = c.get("/app/data/feeds.json", follow_redirects=False)
    assert r.status_code == 401  # non-HTML ask gets a plain 401
    r = c.get("/app/", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    r = c.post(
        "/login",
        data={"email": "owner@example.com", "code": "wrong"},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/login?e=1"
    assert authn.SESSION_COOKIE not in c.cookies


def test_owner_signs_in_and_passes_the_gate(client):
    c, _ = client
    _owner_login(c)
    assert c.get("/app/data/feeds.json").status_code == 200


def test_health_and_login_stay_outside_the_gate(client):
    c, _ = client
    assert c.get("/health").json()["app_auth"] == "on"
    assert "Owner sign-in" in c.get("/login").text


def test_sync_token_passes_the_gate_for_the_watchdog(client):
    c, _ = client
    r = c.get("/app/data/feeds.json", headers={"X-Sync-Token": "runner-token"})
    assert r.status_code == 200
    r = c.get("/app/data/feeds.json", headers={"X-Sync-Token": "wrong"})
    assert r.status_code == 401


def test_invite_flow_end_to_end_then_revocation(client):
    c, store = client
    _owner_login(c)

    page = c.post("/app/access/add", data={"email": "Buddy@Example.com"}).text
    match = re.search(r"/login/invite/([A-Za-z0-9_\-]+)", page)
    assert match, "the minted link must be shown to the owner exactly once"
    token = match.group(1)

    # The buddy signs in on their own browser via the link.
    buddy = TestClient(main.app)
    r = buddy.get(f"/login/invite/{token}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/app/"
    assert buddy.get("/app/data/feeds.json").status_code == 200

    # The link is burned.
    again = TestClient(main.app)
    r = again.get(f"/login/invite/{token}", follow_redirects=False)
    assert r.headers["location"] == "/login?e=2"

    # Removal revokes on the next request, cookie or not.
    c.post("/app/access/remove", data={"email": "buddy@example.com"})
    assert buddy.get("/app/data/feeds.json").status_code == 401


def test_access_page_is_owner_only(client):
    c, _ = client
    r = c.get("/app/access", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303  # anonymous: to /login
    _owner_login(c)
    page = c.get("/app/access").text
    assert "Who gets in" in page and "Add" in page


def test_partial_enable_stays_open(client, monkeypatch):
    """Half-configured auth must not lock the owner out of their own app."""
    c, _ = client
    monkeypatch.setattr(get_settings(), "app_owner_code", "", raising=False)
    assert get_settings().auth_state == "misconfigured"
    assert c.get("/app/data/feeds.json").status_code == 200
    assert "misconfigured" in c.get("/login").text


def test_invite_links_use_https_behind_the_proxy(client):
    """Vercel's ASGI scope can report http; a real invite must not go out
    on the wrong scheme. x-forwarded-proto is the authority."""
    c, _ = client
    _owner_login(c)
    page = c.post(
        "/app/access/add",
        data={"email": "proxy@example.com"},
        headers={"x-forwarded-proto": "https"},
    ).text
    assert "https://testserver/login/invite/" in page
    assert "http://testserver/login/invite/" not in page
