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
import json
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


def test_an_invite_addressed_in_mixed_case_admits_the_lowercase_sign_in():
    """The whole round trip, because this is how a real tester gets
    locked out of an app that looks correct.

    The owner types an address the way a person writes it — capital
    first letter, maybe a trailing space off a copy-paste — and the
    invitee later signs in typing their own address the way they always
    do, in lower case. If any leg of add → invite → accept → check
    skipped normalisation, the allowlist would hold one spelling and the
    gate would test another, and the refusal would be silent and
    indistinguishable from "not invited".
    """
    auth = {}
    auth, token = authn.mint_invite(auth, " Msechelski@CamIntegrated.com ", now_ts=NOW)
    auth, accepted = authn.accept_invite(auth, token, now_ts=NOW)

    assert accepted == "msechelski@camintegrated.com", "stored once, folded"
    # However they type it back at us, it is the same person.
    for typed in (
        "msechelski@camintegrated.com",
        "Msechelski@camintegrated.com",
        "MSECHELSKI@CAMINTEGRATED.COM",
        "  msechelski@camintegrated.com  ",
    ):
        assert authn.is_allowed(auth, typed, OWNER), typed
    # And the session cookie minted for any of those spellings reads back
    # as the one stored identity.
    cookie = authn.mint_session("Msechelski@CamIntegrated.com", SECRET, now_ts=NOW)
    assert authn.read_session(cookie, SECRET, now_ts=NOW) == "msechelski@camintegrated.com"


def test_a_second_invite_to_the_same_person_in_a_different_case_is_the_same_row():
    """Otherwise the access page grows two rows for one human, and
    removing the one you can see leaves the other one letting them in —
    a revocation that silently does not revoke."""
    auth = {}
    auth, first = authn.mint_invite(auth, "RGTorres09@Gmail.com", now_ts=NOW)
    auth, _ = authn.accept_invite(auth, first, now_ts=NOW)
    auth, second = authn.mint_invite(auth, "rgtorres09@gmail.com", now_ts=NOW)
    auth, _ = authn.accept_invite(auth, second, now_ts=NOW)

    assert list(auth["allow"]) == ["rgtorres09@gmail.com"]


def test_a_fresh_invite_kills_the_unused_one_it_replaces():
    """Minting was purely additive until Aug 22, so re-adding an email
    three times left THREE working links — every one a live way in, and
    only the newest one known to the owner. Nobody would guess that from
    a page whose only affordance is "add", and the docs already promised
    the opposite ("re-add the email to mint a fresh one").

    One live link per person is the whole point: it is what makes "I lost
    the link, make me another" safe to offer as a button.
    """
    auth = {}
    auth, first = authn.mint_invite(auth, "tester@example.com", now_ts=NOW)
    auth, second = authn.mint_invite(auth, "tester@example.com", now_ts=NOW)

    assert len(auth["invites"]) == 1
    after, dead = authn.accept_invite(auth, first, now_ts=NOW)
    assert dead is None, "the superseded link must not open anything"
    assert not (after.get("allow") or {}), "and must not allowlist anybody"
    _, live = authn.accept_invite(auth, second, now_ts=NOW)
    assert live == "tester@example.com"


def test_superseding_is_per_person_and_case_folded():
    """Re-inviting one tester must not revoke everybody else's pending
    link — and the same person written two ways is one person, or the
    supersede silently misses and both links stay live."""
    auth = {}
    auth, mine = authn.mint_invite(auth, "tester@example.com", now_ts=NOW)
    auth, theirs = authn.mint_invite(auth, "someone.else@example.com", now_ts=NOW)
    auth, mine_again = authn.mint_invite(auth, "  TESTER@Example.com ", now_ts=NOW)

    assert len(auth["invites"]) == 2, "one live link each, not three"
    _, dead = authn.accept_invite(auth, mine, now_ts=NOW)
    assert dead is None
    _, still_good = authn.accept_invite(auth, theirs, now_ts=NOW)
    assert still_good == "someone.else@example.com", "an unrelated invite survives"
    _, live = authn.accept_invite(auth, mine_again, now_ts=NOW)
    assert live == "tester@example.com"


def test_peeking_at_an_invite_leaves_it_exactly_as_it_was():
    """`peek_invite` is what lets the link be opened safely. If it
    mutated anything — or if a peek could be mistaken for an accept —
    the whole two-step would be theatre."""
    auth = {}
    auth, token = authn.mint_invite(auth, "buddy@example.com", now_ts=NOW)
    before = json.dumps(auth, sort_keys=True)

    for _ in range(5):
        assert authn.peek_invite(auth, token, now_ts=NOW) == "buddy@example.com"

    assert json.dumps(auth, sort_keys=True) == before, "a peek changes nothing"
    assert not (auth.get("allow") or {}), "and allowlists nobody"
    # The accept still works afterwards, exactly once.
    auth, who = authn.accept_invite(auth, token, now_ts=NOW)
    assert who == "buddy@example.com"
    assert authn.peek_invite(auth, token, now_ts=NOW) is None, "spent is spent"


def test_peek_refuses_an_expired_or_unknown_token():
    auth = {}
    auth, token = authn.mint_invite(auth, "buddy@example.com", now_ts=NOW)
    assert authn.peek_invite(auth, token, now_ts=NOW + authn.INVITE_DAYS * 86400 + 1) is None
    assert authn.peek_invite(auth, "not-a-real-token", now_ts=NOW) is None
    assert authn.peek_invite(auth, "", now_ts=NOW) is None


# --- passwords -------------------------------------------------------------


def test_the_password_is_never_stored_and_never_recoverable():
    """The property that makes holding hashes acceptable at all. What
    goes in the store must not resemble what was typed, and there must be
    no way back to it."""
    auth = authn.set_password({"allow": {"b@e.com": {"added": 1}}}, "b@e.com", "correct-horse-b")
    record = auth["allow"]["b@e.com"]["pw"]

    blob = json.dumps(auth)
    assert "correct-horse-b" not in blob
    assert set(record) == {"salt", "hash", "n", "r", "p"}
    assert len(record["hash"]) == 64  # 32 bytes of scrypt, hex


def test_the_same_password_twice_stores_two_different_hashes():
    """Per-user salt. Without it, identical passwords are visibly
    identical in the store and one cracked hash breaks every match."""
    a = authn.set_password({}, "one@e.com", "same-password-here")
    b = authn.set_password({}, "two@e.com", "same-password-here")
    assert a["allow"]["one@e.com"]["pw"]["hash"] != b["allow"]["two@e.com"]["pw"]["hash"]


def test_a_password_is_checked_against_membership_too():
    """A correct password for a removed account must not open anything —
    which is why check_password looks the address up rather than trusting
    a hash handed to it."""
    auth = authn.set_password({"allow": {"b@e.com": {"added": 1}}}, "b@e.com", "long-enough-pw")
    assert authn.check_password(auth, "b@e.com", "long-enough-pw")
    gone = {**auth, "allow": {}}
    assert not authn.check_password(gone, "b@e.com", "long-enough-pw")


def test_verify_survives_a_future_cost_increase():
    """Parameters are read back from each record, so raising the cost
    later must not lock out everybody stored under the old one."""
    auth = authn.set_password({}, "b@e.com", "long-enough-pw")
    record = auth["allow"]["b@e.com"]["pw"]
    assert record["n"] == 2**14
    assert authn.verify_password(record, "long-enough-pw")
    assert not authn.verify_password(record, "long-enough-px")


def test_a_corrupt_password_record_refuses_rather_than_raising():
    """Stored blobs outlive the code that wrote them; a bad one must be a
    failed sign-in, not a 500 on the login page."""
    for bad in ({}, None, {"salt": "zz", "hash": "x"}, {"hash": "x"}, {"salt": "00", "n": "?"}):
        assert not authn.verify_password(bad, "anything-at-all")


# --- throttling ------------------------------------------------------------


def test_five_failures_lock_the_address_and_a_success_clears_it():
    auth, now = {}, 1000.0
    for i in range(authn.THROTTLE_MAX_FAILS - 1):
        auth = authn.record_failure(auth, "b@e.com", now_ts=now + i)
        assert authn.locked_until(auth, "b@e.com", now_ts=now + i) is None
    auth = authn.record_failure(auth, "b@e.com", now_ts=now + 10)
    assert authn.locked_until(auth, "b@e.com", now_ts=now + 10) is not None
    assert authn.locked_until(auth, "b@e.com", now_ts=now + 10) > now + 10
    auth = authn.clear_failures(auth, "b@e.com")
    assert authn.locked_until(auth, "b@e.com", now_ts=now + 10) is None


def test_the_lock_expires_on_its_own():
    """Short and self-clearing on purpose: otherwise hammering someone's
    address is a way to keep them out, and the defence becomes the
    attack."""
    auth, now = {}, 1000.0
    for i in range(authn.THROTTLE_MAX_FAILS):
        auth = authn.record_failure(auth, "b@e.com", now_ts=now + i)
    # The lock runs from the LAST failure, which was at now + 4.
    later = now + authn.THROTTLE_MAX_FAILS + authn.THROTTLE_LOCK_SECONDS + 1
    assert authn.locked_until(auth, "b@e.com", now_ts=later) is None


def test_slow_guessing_does_not_accumulate_forever():
    """Failures age out of their window, so one wrong password a day
    never adds up to a lockout."""
    auth, now = {}, 1000.0
    for day in range(10):
        auth = authn.record_failure(auth, "b@e.com", now_ts=now + day * 86400)
        assert authn.locked_until(auth, "b@e.com", now_ts=now + day * 86400) is None


def test_one_address_being_locked_does_not_lock_another():
    auth, now = {}, 1000.0
    for i in range(authn.THROTTLE_MAX_FAILS):
        auth = authn.record_failure(auth, "target@e.com", now_ts=now + i)
    assert authn.locked_until(auth, "target@e.com", now_ts=now + 5) is not None
    assert authn.locked_until(auth, "bystander@e.com", now_ts=now + 5) is None


def test_the_throttle_table_does_not_grow_without_bound():
    """A stored write per failure is fine at five testers only because
    spent counters are pruned as they expire."""
    auth, now = {}, 1000.0
    for n in range(50):
        auth = authn.record_failure(auth, f"drive-by-{n}@e.com", now_ts=now)
    # Long after every window and lock has passed, one more failure
    # sweeps the dead entries out.
    auth = authn.record_failure(auth, "someone@e.com", now_ts=now + 10 * 86400)
    assert list(auth["throttle"]) == ["someone@e.com"]


def test_an_unknown_address_costs_the_same_as_a_real_one():
    """User enumeration by stopwatch. An unknown address used to return in
    ~0ms while a real one paid scrypt's ~40ms, and that gap is readable
    over the network — so the door answered "is this person a user?" to
    anyone willing to time it, which is exactly what the identical
    redirect exists to refuse. Measured before the fix: 40.6ms vs 0.0ms.

    Timing in a test is inherently noisy, so this asserts the shape (both
    pay for a hash) rather than a tight bound.
    """
    import time

    auth = authn.set_password({"allow": {"real@e.com": {"added": 1}}}, "real@e.com", "long-pw-here")

    def cost(address: str) -> float:
        start = time.perf_counter()
        assert not authn.check_password(auth, address, "a-wrong-guess")
        return time.perf_counter() - start

    known = min(cost("real@e.com") for _ in range(3))
    unknown = min(cost("nobody@e.com") for _ in range(3))
    assert unknown > known / 4, f"unknown {unknown:.4f}s vs known {known:.4f}s — enumerable"
