"""Passkeys: Face ID / Touch ID sign-in.

The contract that matters is not the crypto -- py_webauthn owns that --
but the shell around it: a passkey is a faster way in for someone who
already has access, never a way to grant it. So registration needs a
live session, sign-in still ends at the allowlist check, a removed email
takes its passkeys with it, and a stale or forged challenge opens
nothing. The ceremony itself is stubbed; the guards are real.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app import authn, main, passkeys
from app.config import get_settings
from app.feeds.store import FileFeedStore
from app.routes import access as access_route
from app.routes import feeds as feeds_route

NOW = 1_755_000_000.0
CRED_ID = b"\x01\x02\x03credential"
PUBKEY = b"\xaa\xbb-public-key"


# --- primitives --------------------------------------------------------------


def test_challenge_cookie_round_trips_and_rejects_everything_else():
    cookie = passkeys.mint_challenge(b"the-challenge", "sek", NOW)
    assert passkeys.read_challenge(cookie, "sek", NOW) == b"the-challenge"
    assert passkeys.read_challenge(cookie, "sek", NOW + passkeys.CHALLENGE_SECONDS + 1) is None
    assert passkeys.read_challenge(cookie, "other-secret", NOW) is None
    assert passkeys.read_challenge("garbage!!", "sek", NOW) is None
    assert passkeys.read_challenge(None, "sek", NOW) is None


def test_credentials_store_and_re_register_replaces():
    auth = passkeys.add_credential({}, "a@x.com", CRED_ID, PUBKEY, 0, "iPhone")
    assert len(passkeys.list_for(auth, "a@x.com")) == 1
    # The private half never exists here -- only the public key.
    assert passkeys.b64url(PUBKEY) in json.dumps(auth)
    # Same credential registered again replaces rather than duplicates.
    auth = passkeys.add_credential(auth, "a@x.com", CRED_ID, PUBKEY, 5, "iPhone")
    assert len(passkeys.list_for(auth, "a@x.com")) == 1

    found = passkeys.find_credential(auth, passkeys.b64url(CRED_ID))
    assert found and found[0] == "a@x.com"
    assert passkeys.find_credential(auth, "nope") is None

    auth = passkeys.bump_sign_count(auth, "a@x.com", passkeys.b64url(CRED_ID), 9)
    assert passkeys.list_for(auth, "a@x.com")[0]["sign_count"] == 9

    auth = passkeys.remove_credential(auth, "a@x.com", passkeys.b64url(CRED_ID))
    assert passkeys.list_for(auth, "a@x.com") == []


def test_rp_id_follows_the_proxy_headers():
    class Req:
        def __init__(self, headers):
            self.headers = headers
            self.url = type("U", (), {"netloc": "internal:8000", "scheme": "http"})()

    rp, origin = (
        Req({"x-forwarded-host": "fb-bible.vercel.app", "x-forwarded-proto": "https"}),
        None,
    )
    rp_id, origin = passkeys.rp_from_request(rp)
    assert (rp_id, origin) == ("fb-bible.vercel.app", "https://fb-bible.vercel.app")
    # Local dev keeps its port, and its scheme.
    rp_id, origin = passkeys.rp_from_request(Req({"host": "localhost:8000"}))
    assert (rp_id, origin) == ("localhost", "http://localhost:8000")


# --- the endpoints -----------------------------------------------------------


@dataclass
class _FakeReg:
    credential_id: bytes = CRED_ID
    credential_public_key: bytes = PUBKEY
    sign_count: int = 0


@dataclass
class _FakeAuth:
    new_sign_count: int = 7


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    s = get_settings()
    monkeypatch.setattr(s, "app_auth", True, raising=False)
    monkeypatch.setattr(s, "owner_email", "owner@example.com", raising=False)
    monkeypatch.setattr(s, "app_owner_code", "open-sesame", raising=False)
    monkeypatch.setattr(s, "session_secret", "unit-test-secret", raising=False)
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    monkeypatch.setattr(access_route, "build_feed_store", lambda _s: store)
    yield TestClient(main.app), store
    main.app.dependency_overrides.clear()


def _owner(c: TestClient) -> None:
    c.post("/login", data={"email": "owner@example.com", "code": "open-sesame"})


def _register(c: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(access_route, "verify_registration_response", lambda **k: _FakeReg())
    assert c.post("/passkey/register/options").status_code == 200  # sets the challenge
    r = c.post("/passkey/register/verify", json={"credential": {}, "label": "iPhone"})
    assert r.status_code == 200, r.text


def test_registration_requires_a_live_session(client):
    c, _ = client
    assert c.post("/passkey/register/options").status_code == 401
    assert c.post("/passkey/register/verify", json={"credential": {}}).status_code == 401


def test_registration_needs_a_challenge_this_server_issued(client, monkeypatch):
    c, _ = client
    _owner(c)
    monkeypatch.setattr(access_route, "verify_registration_response", lambda **k: _FakeReg())
    # No options call first: no challenge cookie, so nothing to verify against.
    r = c.post("/passkey/register/verify", json={"credential": {}})
    assert r.status_code == 400


def test_round_trip_registers_then_signs_in(client, monkeypatch):
    c, store = client
    _owner(c)
    _register(c, monkeypatch)

    # A fresh browser with no session signs in with the passkey alone.
    fresh = TestClient(main.app)
    monkeypatch.setattr(access_route, "verify_authentication_response", lambda **k: _FakeAuth())
    assert fresh.post("/passkey/login/options").status_code == 200
    r = fresh.post(
        "/passkey/login/verify",
        json={"credential": {"rawId": passkeys.b64url(CRED_ID)}},
    )
    assert r.status_code == 200 and r.json()["next"] == "/app/"
    assert authn.SESSION_COOKIE in fresh.cookies
    # Signed in for real: the gate lets them through now.
    assert fresh.get("/app/data/feeds.json").status_code == 200


def test_unknown_credential_is_refused(client, monkeypatch):
    c, _ = client
    fresh = TestClient(main.app)
    fresh.post("/passkey/login/options")
    monkeypatch.setattr(access_route, "verify_authentication_response", lambda **k: _FakeAuth())
    r = fresh.post("/passkey/login/verify", json={"credential": {"rawId": "not-registered"}})
    assert r.status_code == 401


async def test_a_removed_email_cannot_sign_in_with_its_passkey(client, monkeypatch):
    """The allowlist governs the passkey, not the other way round."""
    c, store = client
    # A guest with access and a registered passkey.
    await store.save_auth(
        passkeys.add_credential(
            {"allow": {"guest@example.com": {"added": 0}}},
            "guest@example.com",
            CRED_ID,
            PUBKEY,
            0,
            "iPad",
        )
    )
    monkeypatch.setattr(access_route, "verify_authentication_response", lambda **k: _FakeAuth())
    guest = TestClient(main.app)
    guest.post("/passkey/login/options")
    body = {"credential": {"rawId": passkeys.b64url(CRED_ID)}}
    assert guest.post("/passkey/login/verify", json=body).status_code == 200

    # The owner revokes them; the passkey stops opening anything.
    _owner(c)
    c.post("/app/access/remove", data={"email": "guest@example.com"})
    gone = TestClient(main.app)
    gone.post("/passkey/login/options")
    r = gone.post("/passkey/login/verify", json=body)
    assert r.status_code in (401, 403)
    # And the credential itself is gone from the store, not merely ignored.
    assert passkeys.list_for(await store.load_auth(), "guest@example.com") == []


def test_owner_can_list_and_remove_their_own_passkey(client, monkeypatch):
    c, _ = client
    _owner(c)
    _register(c, monkeypatch)
    page = c.get("/app/mine").text
    assert "iPhone" in page and "Sign in with Face ID" in page
    c.post("/app/mine/passkey/remove", data={"cred": passkeys.b64url(CRED_ID)})
    assert "iPhone" not in c.get("/app/mine").text


def test_login_page_offers_the_passkey_button(client):
    c, _ = client
    page = c.get("/login").text
    assert "Sign in with Face ID" in page and "FBPK" in page


# --- RP ID pinning (Aug 24, ahead of the custom-domain move) -----------------
# A passkey is scoped to an RP ID. `fantasysportsbible.com` and
# `app.fantasysportsbible.com` are DIFFERENT relying parties, so every
# credential registered under one is dead under the other. Pinning the
# registrable domain before anyone registers makes that move free; doing it
# afterwards does not un-break the credentials.


def test_blank_config_keeps_the_hostname_as_it_always_did():
    assert passkeys.rp_id_for("fantasysportsbible.com") == "fantasysportsbible.com"
    assert passkeys.rp_id_for("fb-bible-torro2.vercel.app") == "fb-bible-torro2.vercel.app"


def test_a_subdomain_registers_against_the_pinned_domain():
    assert (
        passkeys.rp_id_for("app.fantasysportsbible.com", "fantasysportsbible.com")
        == "fantasysportsbible.com"
    )


def test_the_apex_itself_is_allowed():
    assert (
        passkeys.rp_id_for("fantasysportsbible.com", "fantasysportsbible.com")
        == "fantasysportsbible.com"
    )


def test_a_value_the_host_does_not_sit_under_is_ignored():
    """WebAuthn refuses an RP ID that is not a suffix of the origin's host,
    and it refuses it in the BROWSER -- so a typo here would break every
    registration and every sign-in, on a setting nobody re-reads. Falling
    back to the hostname degrades to the behaviour that already worked."""
    assert passkeys.rp_id_for("fantasysportsbible.com", "example.com") == "fantasysportsbible.com"
    # The classic near-miss: a suffix by string, not by label.
    assert (
        passkeys.rp_id_for("notfantasysportsbible.com", "fantasysportsbible.com")
        == "notfantasysportsbible.com"
    )


def test_leading_dots_whitespace_and_case_are_tolerated():
    for value in (" fantasysportsbible.com ", ".fantasysportsbible.com", "FantasySportsBible.COM"):
        assert (
            passkeys.rp_id_for("app.fantasysportsbible.com", value) == "fantasysportsbible.com"
        ), value


def test_the_origin_is_never_broadened_only_the_rp_id():
    """The origin must match the browser's client data exactly. Widening it
    to the pinned domain would make a credential from any subdomain verify
    against any other, which is the check doing the opposite of its job."""

    class _Req:
        headers = {"x-forwarded-host": "app.fantasysportsbible.com", "x-forwarded-proto": "https"}
        url = type("U", (), {"netloc": "app.fantasysportsbible.com", "scheme": "https"})()

    rp_id, origin = passkeys.rp_from_request(_Req(), "fantasysportsbible.com")

    assert rp_id == "fantasysportsbible.com"
    assert origin == "https://app.fantasysportsbible.com"


def test_localhost_ignores_the_pin_and_keeps_its_port():
    class _Req:
        headers = {"host": "localhost:8000"}
        url = type("U", (), {"netloc": "localhost:8000", "scheme": "http"})()

    assert passkeys.rp_from_request(_Req(), "fantasysportsbible.com") == (
        "localhost",
        "http://localhost:8000",
    )
