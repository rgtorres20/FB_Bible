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


def _accept(client_: TestClient, token: str, password: str = "draft-day-2026-buddy"):
    """Accept an invite the way a person does: set a password, get signed in."""
    return client_.post(
        "/login/invite",
        data={"token": token, "password": password, "confirm": password},
        follow_redirects=False,
    )


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
    assert "<h2>Sign in</h2>" in c.get("/login").text


def test_health_reports_which_mail_transport_is_wired(client, monkeypatch):
    """Not just on/off: SMTP is configured-but-doomed on Vercel, so the
    transport itself is the answer the owner needs in one request."""
    c, _ = client
    s = get_settings()
    assert c.get("/health").json()["invite_email"] == "off"

    monkeypatch.setattr(s, "smtp_host", "smtp.mail.me.com", raising=False)
    monkeypatch.setattr(s, "smtp_user", "me@icloud.com", raising=False)
    monkeypatch.setattr(s, "smtp_pass", "app-specific", raising=False)
    assert c.get("/health").json()["invite_email"] == "smtp"

    # An API key wins: it is the only transport that works on Vercel.
    monkeypatch.setattr(s, "resend_api_key", "re_test", raising=False)
    assert c.get("/health").json()["invite_email"] == "http"


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

    # The buddy opens the link on their own browser. Opening it only
    # SHOWS the invite -- see test_opening_an_invite_does_not_spend_it.
    buddy = TestClient(main.app)
    shown = buddy.get(f"/login/invite/{token}")
    assert shown.status_code == 200
    assert "buddy@example.com" in shown.text

    # Clicking the button is what signs them in.
    r = _accept(buddy, token)
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


def test_the_sign_in_page_introduces_the_app(client):
    """Someone who just got an invite has no idea what they were invited
    to. The page leads with the mark and says what the app does — and
    every claim on it is something the app does today."""
    c, _ = client
    page = c.get("/login").text
    assert "/app/assets/fsb-logo.svg" in page
    assert "What this is" in page
    for claim in ("Live wire", "mock draft room", "Vegas lines", "league's scoring"):
        assert claim in page, claim
    # The honesty line survives too -- it is the point of the section.
    assert "labelled" in page and "blank instead of inventing" in page


def test_the_mark_sits_on_its_own_navy_in_every_theme(client):
    """The wordmark is white and gold. On the light theme's cream ground
    "Fantasy" and "Bible" vanish and the name reads as one gold word, so
    the hero paints its own panel (docs/BRAND.md)."""
    c, _ = client
    assert "background: #0B1A36" in c.get("/login").text


def test_every_served_page_wears_the_same_icon(client):
    """A favicon that disagrees between surfaces reads as two apps."""
    c, _ = client
    _owner_login(c)  # everything but /login is behind the gate here
    for path in ("/login", "/app/leagues", "/app/mine", "/app/mock", "/app/idp"):
        assert "/app/assets/fsb-icon.svg" in c.get(path).text, path


def test_the_brand_assets_are_served_and_are_real_svg(client):
    c, _ = client
    _owner_login(c)
    for name in ("fsb-logo.svg", "fsb-icon.svg", "fsb-mark.svg"):
        r = c.get(f"/app/assets/{name}")
        assert r.status_code == 200, name
        assert r.text.lstrip().startswith(("<!--", "<svg")), name
        assert "</svg>" in r.text


def test_a_signed_out_visitor_can_load_the_sign_in_page_artwork(client):
    """The bug this test exists for: /login is public and every asset it
    references lived under /app, so the page rendered while the mark, the
    favicon and the theme stylesheet all came back 401 — broken for
    exactly the people the page is for. The watchdog missed it because it
    sends a sync token and walks through the gate."""
    c, _ = client
    for asset in (
        "/app/assets/fsb-logo.svg",
        "/app/assets/fsb-icon.svg",
        "/app/teams.css",
        "/app/icons/icon-192.png",
        "/app/manifest.webmanifest",
    ):
        assert c.get(asset, follow_redirects=False).status_code == 200, asset


def test_the_artwork_allowlist_opens_nothing_else(client):
    """A tight allowlist, not "static files are public". Brand art and
    colour tokens carry no user data; everything else stays shut."""
    c, _ = client
    for guarded in (
        "/app/",
        "/app/mine",
        "/app/leagues",
        "/app/mock",
        "/app/nextup",
        "/app/scorecard",
        "/app/mobile.js",
        "/app/data/feeds.json",
    ):
        assert c.get(guarded, follow_redirects=False).status_code in (303, 401), guarded


def test_the_new_link_button_mints_a_replacement_and_burns_the_lost_one(client):
    """The owner's real failure mode: mint a link, navigate away before
    copying it, and it is gone — the server keeps only its hash, so it
    can never be shown again. "New link" is the recovery, and it must be
    a true replacement: the link nobody managed to copy stops working,
    so a lost link is not left live and unaccounted for."""
    c, _ = client
    _owner_login(c)

    first_page = c.post("/app/access/add", data={"email": "tester@example.com"}).text
    lost = re.search(r"/login/invite/([A-Za-z0-9_\-]+)", first_page).group(1)

    # The pending row offers the one-click replacement.
    page = c.get("/app/access").text
    assert "New link" in page
    assert "tester@example.com" in page

    second_page = c.post("/app/access/add", data={"email": "tester@example.com"}).text
    fresh = re.search(r"/login/invite/([A-Za-z0-9_\-]+)", second_page).group(1)
    assert fresh != lost

    # The lost link is dead; the fresh one works.
    stale = TestClient(main.app)
    r = stale.get(f"/login/invite/{lost}", follow_redirects=False)
    assert r.headers["location"] == "/login?e=2"
    assert _accept(stale, lost).headers["location"] == "/login?e=2", (
        "and cannot be forced past the confirm page by posting it directly"
    )
    assert stale.get("/app/data/feeds.json").status_code == 401

    invited = TestClient(main.app)
    assert invited.get(f"/login/invite/{fresh}").status_code == 200
    r = _accept(invited, fresh)
    assert r.status_code == 303 and r.headers["location"] == "/app/"
    assert invited.get("/app/data/feeds.json").status_code == 200


def test_the_access_page_says_a_link_can_never_be_shown_again(client):
    """The page must not imply a link is retrievable. It is not — only
    its hash is kept — and a reader who expects otherwise will lose one
    and not understand why."""
    c, _ = client
    _owner_login(c)
    c.post("/app/access/add", data={"email": "tester@example.com"})
    page = c.get("/app/access").text
    assert "keeps just its hash" in page
    assert "kills the unused one" in page


def test_a_bounced_invitee_sees_a_password_field_not_an_owner_code(client):
    """Owner ask, Aug 24: "web page is still asking for code even when they
    click link". The bounce was right — the link was spent — but the form
    under it said "Owner code", which reads as a code the invitee was
    supposed to have been given, and none existed.

    Now the same form is theirs: one Password field, and a line saying
    where a password comes from and what the reset is.
    """
    c, _ = client
    page = c.get("/login?e=2").text

    assert "invite link has been used already or has expired" in page
    assert "Owner code" not in page, "there is no such thing for an invitee"
    assert "<label>Password</label>" in page
    assert "It comes from your invite link" in page


def test_the_owner_code_still_signs_the_owner_in(client):
    """The owner's credential stays the env-held code, not a stored
    password — so a leaked store can never contain the owner's way in."""
    c, _ = client
    page = c.get("/login").text
    assert "<form method='post' action='/login'>" in page
    assert "name='code'" in page

    # It still signs the owner in, folded or not.
    _owner_login(c)


def test_the_sign_in_page_says_where_a_password_comes_from(client):
    """The one question the page has to answer for somebody who has never
    been here: I have no password, now what."""
    c, _ = client
    page = c.get("/login").text
    assert "password you chose when you accepted your invite" in page
    assert "Ask for a fresh invite" in page


def test_opening_an_invite_does_not_spend_it(client):
    """The reason this is two steps. Mail clients and chat apps fetch
    links to build previews, and corporate mail scanners open every link
    to check it for malware — all GETs. When GET accepted the invite,
    any one of those burned it before the invitee touched it, and they
    arrived at "already used" with no way to know why.

    A GET is supposed to be safe and repeatable. Ten previews must leave
    the link exactly as usable as none.
    """
    c, _ = client
    _owner_login(c)
    page = c.post("/app/access/add", data={"email": "buddy@example.com"}).text
    token = re.search(r"/login/invite/([A-Za-z0-9_\-]+)", page).group(1)

    scanner = TestClient(main.app)
    for _ in range(10):
        peek = scanner.get(f"/login/invite/{token}")
        assert peek.status_code == 200
    # No session was handed out on the way past, either.
    assert scanner.get("/app/data/feeds.json").status_code == 401

    # And the real invitee still gets in.
    invitee = TestClient(main.app)
    r = _accept(invitee, token)
    assert r.status_code == 303 and r.headers["location"] == "/app/"
    assert invitee.get("/app/data/feeds.json").status_code == 200


def test_the_confirm_page_says_who_it_signs_in_and_what_to_do_next(client):
    """An invitee should know whose account they are opening before they
    open it — and be told about the passkey, because registering one is
    what stops them needing a fresh link on that device in 30 days."""
    c, _ = client
    _owner_login(c)
    page = c.post("/app/access/add", data={"email": "buddy@example.com"}).text
    token = re.search(r"/login/invite/([A-Za-z0-9_\-]+)", page).group(1)

    shown = TestClient(main.app).get(f"/login/invite/{token}").text
    assert "buddy@example.com" in shown
    assert "Choose a password" in shown
    assert "Set up on this device" in shown


async def test_an_expired_invite_never_reaches_the_confirm_page(client):
    """Better to say so on arrival than after a click."""
    c, store = client
    _owner_login(c)
    page = c.post("/app/access/add", data={"email": "buddy@example.com"}).text
    token = re.search(r"/login/invite/([A-Za-z0-9_\-]+)", page).group(1)

    auth = await store.load_auth()
    for entry in (auth.get("invites") or {}).values():
        entry["expires"] = 0
    await store.save_auth(auth)

    r = TestClient(main.app).get(f"/login/invite/{token}", follow_redirects=False)
    assert r.headers["location"] == "/login?e=2"


# --- passwords: the credential that travels with the person ---------------


def test_a_password_signs_in_on_any_number_of_devices(client):
    """The whole point of the change. An invite link proves it once and a
    passkey proves it on one device; a password proves it anywhere, which
    is what "they should have access until I remove them" requires."""
    c, _ = client
    _owner_login(c)
    page = c.post("/app/access/add", data={"email": "buddy@example.com"}).text
    token = re.search(r"/login/invite/([A-Za-z0-9_\-]+)", page).group(1)
    _accept(TestClient(main.app), token)

    for _ in range(3):  # phone, laptop, tablet
        device = TestClient(main.app)
        r = device.post(
            "/login",
            data={"email": "Buddy@Example.com", "code": "draft-day-2026-buddy"},
            follow_redirects=False,
        )
        assert r.status_code == 303 and r.headers["location"] == "/app/"
        assert device.get("/app/data/feeds.json").status_code == 200


def test_removing_someone_kills_their_password_with_them(client):
    """A revocation that leaves a working password behind is not one. The
    hash lives inside the allowlist entry precisely so removal takes it."""
    c, _ = client
    _owner_login(c)
    page = c.post("/app/access/add", data={"email": "buddy@example.com"}).text
    token = re.search(r"/login/invite/([A-Za-z0-9_\-]+)", page).group(1)
    _accept(TestClient(main.app), token)

    c.post("/app/access/remove", data={"email": "buddy@example.com"})

    after = TestClient(main.app)
    r = after.post(
        "/login",
        data={"email": "buddy@example.com", "code": "draft-day-2026-buddy"},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/login?e=1"
    assert after.get("/app/data/feeds.json").status_code == 401


def test_the_door_locks_after_five_wrong_passwords(client):
    """Opening /login to real passwords is what makes this necessary: it
    used to take one address and one env-held code, so guessing was
    pointless. Five accounts make it a door worth rattling."""
    c, _ = client
    _owner_login(c)
    page = c.post("/app/access/add", data={"email": "buddy@example.com"}).text
    token = re.search(r"/login/invite/([A-Za-z0-9_\-]+)", page).group(1)
    _accept(TestClient(main.app), token)

    attacker = TestClient(main.app)
    for _ in range(authn.THROTTLE_MAX_FAILS):
        r = attacker.post(
            "/login",
            data={"email": "buddy@example.com", "code": "wrong-guess-here"},
            follow_redirects=False,
        )
        assert r.headers["location"] == "/login?e=1"

    # Locked — and the RIGHT password is refused too, or the lock is a
    # suggestion rather than a lock.
    r = attacker.post(
        "/login",
        data={"email": "buddy@example.com", "code": "draft-day-2026-buddy"},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/login?e=3"
    assert "Too many tries" in c.get("/login?e=3").text


def test_the_lock_follows_the_address_not_the_browser(client):
    """Counted per email because an attacker picks their IP and cannot
    pick whose account they want."""
    c, _ = client
    _owner_login(c)
    page = c.post("/app/access/add", data={"email": "buddy@example.com"}).text
    token = re.search(r"/login/invite/([A-Za-z0-9_\-]+)", page).group(1)
    _accept(TestClient(main.app), token)

    for _ in range(authn.THROTTLE_MAX_FAILS):
        TestClient(main.app).post(
            "/login",
            data={"email": "buddy@example.com", "code": "wrong"},
            follow_redirects=False,
        )

    fresh_browser = TestClient(main.app)
    r = fresh_browser.post(
        "/login",
        data={"email": "buddy@example.com", "code": "draft-day-2026-buddy"},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/login?e=3"


def test_a_wrong_password_never_says_whether_the_account_exists(client):
    """Which addresses are real is not something the door should teach."""
    c, _ = client
    _owner_login(c)
    page = c.post("/app/access/add", data={"email": "buddy@example.com"}).text
    _accept(TestClient(main.app), re.search(r"/login/invite/([\w\-]+)", page).group(1))

    real = TestClient(main.app).post(
        "/login", data={"email": "buddy@example.com", "code": "nope"}, follow_redirects=False
    )
    fake = TestClient(main.app).post(
        "/login", data={"email": "nobody@example.com", "code": "nope"}, follow_redirects=False
    )
    assert real.headers["location"] == fake.headers["location"] == "/login?e=1"


def test_a_typo_on_the_invite_form_does_not_cost_the_link(client):
    """Validation runs before the token is spent. Losing a one-time link
    to a mistyped confirmation would be a cruel way to learn to type."""
    c, _ = client
    _owner_login(c)
    page = c.post("/app/access/add", data={"email": "buddy@example.com"}).text
    token = re.search(r"/login/invite/([A-Za-z0-9_\-]+)", page).group(1)

    invitee = TestClient(main.app)
    r = invitee.post(
        "/login/invite",
        data={"token": token, "password": "long-enough-here", "confirm": "mismatched"},
        follow_redirects=False,
    )
    assert r.headers["location"] == f"/login/invite/{token}?problem=match"
    r = invitee.post(
        "/login/invite",
        data={"token": token, "password": "short", "confirm": "short"},
        follow_redirects=False,
    )
    assert r.headers["location"] == f"/login/invite/{token}?problem=short"

    # The link survived both, and still works.
    assert _accept(invitee, token).headers["location"] == "/app/"
