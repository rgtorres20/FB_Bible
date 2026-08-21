"""Sign-in primitives: signed sessions, one-time invites, the allowlist.

The module the whole login gate rests on, and it had no tests of its own
until Aug 21 — it was exercised only through the routes, which is the
worst place to discover that a signature check is wrong.

What is worth pinning here is not that the happy path works. It is every
way the module is asked to say **no**: a tampered cookie, an expired one,
a reused invite, a revoked email, a cookie signed with somebody else's
secret. Each of those failing open is the whole gate failing open.
"""

from __future__ import annotations

import base64
import time

from app import authn

SECRET = "unit-test-secret"
OTHER_SECRET = "a-different-secret"
OWNER = "owner@example.com"
GUEST = "guest@example.com"
NOW = 1_776_000_000.0
DAY = 86400.0


# --- sessions -----------------------------------------------------------


def test_a_minted_session_reads_back_as_the_same_person():
    cookie = authn.mint_session(GUEST, SECRET, now_ts=NOW)
    assert authn.read_session(cookie, SECRET, now_ts=NOW) == GUEST


def test_the_email_is_normalised_on_the_way_in():
    """Mixed case and stray whitespace must not create a second identity —
    the allowlist is keyed by this string."""
    cookie = authn.mint_session("  GuEsT@Example.COM ", SECRET, now_ts=NOW)
    assert authn.read_session(cookie, SECRET, now_ts=NOW) == GUEST


def test_a_cookie_signed_with_another_secret_is_not_accepted():
    """Rotating SESSION_SECRET must sign everyone out, and a cookie minted
    by anything but this deployment must not open it."""
    cookie = authn.mint_session(GUEST, OTHER_SECRET, now_ts=NOW)
    assert authn.read_session(cookie, SECRET, now_ts=NOW) is None


def test_editing_the_email_inside_a_cookie_invalidates_it():
    """The attack the signature exists for: take your own valid cookie,
    swap in the owner's address."""
    cookie = authn.mint_session(GUEST, SECRET, now_ts=NOW)
    decoded = base64.urlsafe_b64decode(cookie.encode()).decode()
    forged = decoded.replace(GUEST, OWNER)
    assert forged != decoded, "the fixture must actually change the email"
    tampered = base64.urlsafe_b64encode(forged.encode()).decode()
    assert authn.read_session(tampered, SECRET, now_ts=NOW) is None


def test_extending_the_expiry_inside_a_cookie_invalidates_it():
    cookie = authn.mint_session(GUEST, SECRET, now_ts=NOW)
    decoded = base64.urlsafe_b64decode(cookie.encode()).decode()
    email, expires, signature = decoded.rsplit("|", 2)
    forged = f"{email}|{int(expires) + 10 * 365 * 86400}|{signature}"
    tampered = base64.urlsafe_b64encode(forged.encode()).decode()
    assert authn.read_session(tampered, SECRET, now_ts=NOW) is None


def test_a_session_expires():
    cookie = authn.mint_session(GUEST, SECRET, now_ts=NOW)
    assert authn.read_session(cookie, SECRET, now_ts=NOW + authn.SESSION_DAYS * DAY - 1) == GUEST
    assert authn.read_session(cookie, SECRET, now_ts=NOW + authn.SESSION_DAYS * DAY + 1) is None


def test_garbage_is_signed_out_rather_than_an_exception():
    """A malformed cookie reaches this from a browser, so it must never
    raise — a 500 on every page load is a worse outage than a lockout."""
    for junk in (None, "", "not-base64!!", "///", base64.urlsafe_b64encode(b"a|b").decode()):
        assert authn.read_session(junk, SECRET, now_ts=NOW) is None


def test_no_secret_means_nobody_is_signed_in():
    """A half-configured deployment must fail closed. With no
    SESSION_SECRET every signature would verify against the empty key."""
    cookie = authn.mint_session(GUEST, SECRET, now_ts=NOW)
    assert authn.read_session(cookie, "", now_ts=NOW) is None


def test_a_non_numeric_expiry_is_refused_rather_than_raising():
    body = f"{GUEST}|not-a-number"
    signed = f"{body}|{authn._sign(SECRET, body)}"
    cookie = base64.urlsafe_b64encode(signed.encode()).decode()
    assert authn.read_session(cookie, SECRET, now_ts=NOW) is None


def test_the_cookie_carries_no_secret():
    """Repo rule: never log or return a token. The session is signed, not
    encrypted, so what it contains is readable by its holder — and must
    therefore contain nothing but their own address and an expiry."""
    cookie = authn.mint_session(GUEST, SECRET, now_ts=NOW)
    decoded = base64.urlsafe_b64decode(cookie.encode()).decode()
    assert SECRET not in decoded


# --- invites ------------------------------------------------------------


def test_an_invite_allowlists_its_email_when_accepted():
    auth, token = authn.mint_invite({}, GUEST, now_ts=NOW)
    updated, email = authn.accept_invite(auth, token, now_ts=NOW)
    assert email == GUEST
    assert authn.is_allowed(updated, GUEST, OWNER)


def test_the_plaintext_token_is_never_stored():
    """It exists in the owner's admin response and nowhere else. Only the
    SHA-256 is kept, so a leaked store cannot be replayed as invites."""
    auth, token = authn.mint_invite({}, GUEST, now_ts=NOW)
    assert token not in repr(auth)
    assert all(token != digest for digest in auth["invites"])


def test_an_invite_is_one_time():
    """The second use is the one that matters: a link forwarded on must
    not admit a second person."""
    auth, token = authn.mint_invite({}, GUEST, now_ts=NOW)
    used, email = authn.accept_invite(auth, token, now_ts=NOW)
    assert email == GUEST
    again, second = authn.accept_invite(used, token, now_ts=NOW)
    assert second is None


def test_an_invite_expires():
    auth, token = authn.mint_invite({}, GUEST, now_ts=NOW)
    late = NOW + authn.INVITE_DAYS * DAY + 1
    _, email = authn.accept_invite(auth, token, now_ts=late)
    assert email is None


def test_an_expired_invite_does_not_allowlist_anyone():
    auth, token = authn.mint_invite({}, GUEST, now_ts=NOW)
    late = NOW + authn.INVITE_DAYS * DAY + 1
    updated, _ = authn.accept_invite(auth, token, now_ts=late)
    assert not authn.is_allowed(updated, GUEST, OWNER)


def test_an_unknown_token_changes_nothing():
    auth, _ = authn.mint_invite({}, GUEST, now_ts=NOW)
    updated, email = authn.accept_invite(auth, "made-up-token", now_ts=NOW)
    assert email is None
    assert updated == auth


def test_two_invites_do_not_collide():
    auth, first = authn.mint_invite({}, GUEST, now_ts=NOW)
    auth, second = authn.mint_invite(auth, "other@example.com", now_ts=NOW)
    assert first != second
    assert len(auth["invites"]) == 2
    _, email = authn.accept_invite(auth, first, now_ts=NOW)
    assert email == GUEST


# --- the allowlist ------------------------------------------------------


def test_the_owner_is_always_allowed_even_with_an_empty_store():
    """The lockout escape hatch. A store that lost its allowlist must not
    lock out the person who can fix it."""
    assert authn.is_allowed({}, OWNER, OWNER)
    assert authn.is_allowed({}, "  OWNER@Example.com ", OWNER)


def test_a_stranger_is_not_allowed():
    assert not authn.is_allowed({}, GUEST, OWNER)
    assert not authn.is_allowed({}, None, OWNER)
    assert not authn.is_allowed({}, "", OWNER)


def test_removing_an_email_revokes_it_and_its_pending_invites():
    """Removal has to revoke everything at once. An allowlist entry
    dropped while a live invite survives means the next click lets them
    straight back in."""
    auth, token = authn.mint_invite({}, GUEST, now_ts=NOW)
    auth, _ = authn.accept_invite(auth, token, now_ts=NOW)
    auth, fresh = authn.mint_invite(auth, GUEST, now_ts=NOW)
    assert authn.is_allowed(auth, GUEST, OWNER)

    revoked = authn.remove_email(auth, GUEST)
    assert not authn.is_allowed(revoked, GUEST, OWNER)
    _, email = authn.accept_invite(revoked, fresh, now_ts=NOW)
    assert email is None, "a pending invite must not survive removal"


def test_removing_one_email_leaves_the_others_alone():
    auth, first = authn.mint_invite({}, GUEST, now_ts=NOW)
    auth, _ = authn.accept_invite(auth, first, now_ts=NOW)
    auth, second = authn.mint_invite(auth, "keep@example.com", now_ts=NOW)
    auth, _ = authn.accept_invite(auth, second, now_ts=NOW)

    revoked = authn.remove_email(auth, GUEST)
    assert authn.is_allowed(revoked, "keep@example.com", OWNER)


def test_removing_the_owner_does_not_lock_the_owner_out():
    """`is_allowed` compares against the configured owner address, so the
    escape hatch survives a mis-click on the admin page."""
    auth, token = authn.mint_invite({}, OWNER, now_ts=NOW)
    auth, _ = authn.accept_invite(auth, token, now_ts=NOW)
    assert authn.is_allowed(authn.remove_email(auth, OWNER), OWNER, OWNER)


def test_now_defaults_to_the_real_clock():
    """Every function takes an injectable clock for the tests; the default
    has to be the real one, or production sessions never expire."""
    cookie = authn.mint_session(GUEST, SECRET)
    assert authn.read_session(cookie, SECRET) == GUEST
    decoded = base64.urlsafe_b64decode(cookie.encode()).decode()
    _, expires, _ = decoded.rsplit("|", 2)
    assert abs(int(expires) - (time.time() + authn.SESSION_DAYS * DAY)) < 5
