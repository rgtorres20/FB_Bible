"""App sign-in primitives: signed session cookies and one-time invites.

Distinct from app/routes/auth.py, which is the *Yahoo OAuth* flow -- this
module is about who may open the app at all (owner request, Aug 20: a
login page plus "store people I want to have access via email").

Design, sized to the deployment (Vercel serverless + Redis):

  - Sessions are stateless signed cookies -- email + expiry + HMAC over
    the repo's existing SESSION_SECRET -- so page loads verify without a
    store read. Nothing secret lives in the cookie and nothing about a
    session is ever logged (repo rule: never log or return a token).
  - Access itself IS store-checked per request against the allowlist, so
    removing an email revokes on the next request, valid cookie or not.
  - Invites are one-time links: the server keeps only the SHA-256 of the
    invite token, the plaintext link is shown once to the owner at mint
    time, and accepting it consumes it and allowlists the email.
  - No passwords are ever stored. The owner signs in with an owner code
    held in Vercel env; everyone else enters through an invite link.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

SESSION_COOKIE = "fb_session"
SESSION_DAYS = 30
INVITE_DAYS = 7


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _sign(secret: str, body: str) -> str:
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def mint_session(email: str, secret: str, now_ts: float | None = None) -> str:
    now_ts = time.time() if now_ts is None else now_ts
    expires = int(now_ts + SESSION_DAYS * 86400)
    body = f"{normalize_email(email)}|{expires}"
    token = f"{body}|{_sign(secret, body)}"
    return base64.urlsafe_b64encode(token.encode()).decode()


def read_session(cookie: str | None, secret: str, now_ts: float | None = None) -> str | None:
    """The signed-in email, or None for anything invalid, expired or
    tampered with. Never raises: a garbage cookie is just 'not signed in'."""
    if not cookie or not secret:
        return None
    now_ts = time.time() if now_ts is None else now_ts
    try:
        decoded = base64.urlsafe_b64decode(cookie.encode()).decode()
        email, expires, signature = decoded.rsplit("|", 2)
    except Exception:  # noqa: BLE001 - any malformed cookie means signed out
        return None
    body = f"{email}|{expires}"
    if not hmac.compare_digest(signature, _sign(secret, body)):
        return None
    try:
        if int(expires) < now_ts:
            return None
    except ValueError:
        return None
    return email


def mint_invite(auth: dict, email: str, now_ts: float | None = None) -> tuple[dict, str]:
    """(updated auth blob, plaintext invite token). The blob keeps only the
    token's hash -- the plaintext exists in the owner's admin response and
    nowhere else, ever."""
    now_ts = time.time() if now_ts is None else now_ts
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    address = normalize_email(email)
    # A fresh link SUPERSEDES any unused one for the same person. Minting
    # was purely additive until Aug 22, so re-adding an email three times
    # left three working links -- every one of them a live way in, and
    # only the newest one known to the owner. The docs already described
    # the behaviour everyone assumed ("re-add the email to mint a fresh
    # one"), which is the one implemented here.
    #
    # Other people's invites are untouched: this drops the rows for this
    # address only.
    invites = {
        d: v
        for d, v in (auth.get("invites") or {}).items()
        if normalize_email(v.get("email", "")) != address
    }
    invites[digest] = {
        "email": address,
        "expires": int(now_ts + INVITE_DAYS * 86400),
    }
    return {**auth, "invites": invites}, token


# --- passwords -------------------------------------------------------------
# Owner ask, Aug 24: "let them create a password ... unless I remove their
# account they should have access."
#
# The right separation, and the one the invite link never made: the
# ALLOWLIST says who is allowed, and a CREDENTIAL says how they prove it is
# them. An invite link proves it once. A passkey proves it on one device (or
# one sync ecosystem). A password travels with the person, which is what
# "any device" actually needs.
#
# scrypt from the stdlib -- no new dependency, and memory-hard, so a leaked
# hash is expensive to attack rather than merely slow. n=2**14 costs ~50ms
# here: heavy enough to make guessing painful, light enough for a serverless
# request. The parameters are stored beside each hash so they can be raised
# later without invalidating anybody.
#
# What this trades away, stated plainly: until now the app stored nothing
# that could impersonate anyone even if the whole store leaked. Hashes are a
# target where there was none. scrypt is the reason that is an acceptable
# trade rather than a careless one.
PW_MIN_LENGTH = 10
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> str:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=32,
        maxmem=_SCRYPT_MAXMEM,
    ).hex()


def password_problem(password: str) -> str | None:
    """Why this password is unacceptable, or None. Length only.

    Composition rules ("one capital, one symbol") push people toward
    Passw0rd! and buy nothing; length is what actually costs an attacker.
    """
    if len(password or "") < PW_MIN_LENGTH:
        return f"Use at least {PW_MIN_LENGTH} characters."
    return None


def hash_password(password: str) -> dict:
    """The stored shape. Never the password, and never reversible."""
    salt = secrets.token_bytes(16)
    return {
        "salt": salt.hex(),
        "hash": _scrypt(password, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P),
        "n": _SCRYPT_N,
        "r": _SCRYPT_R,
        "p": _SCRYPT_P,
    }


def verify_password(stored: dict | None, password: str) -> bool:
    """Constant-time check against a stored hash.

    Re-reads the parameters from the record rather than the constants, so
    raising the cost later leaves existing users able to sign in.
    """
    if not stored or not password:
        return False
    try:
        salt = bytes.fromhex(stored["salt"])
        candidate = _scrypt(
            password,
            salt,
            int(stored.get("n", _SCRYPT_N)),
            int(stored.get("r", _SCRYPT_R)),
            int(stored.get("p", _SCRYPT_P)),
        )
    except (KeyError, ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, str(stored.get("hash", "")))


def set_password(auth: dict, email: str, password: str) -> dict:
    """Store one allowlisted person's password hash.

    It lives inside their allowlist entry on purpose: removing the email
    takes the credential with it, the same rule passkeys already follow.
    A revocation that leaves a working password behind is not one.
    """
    address = normalize_email(email)
    allow = dict(auth.get("allow") or {})
    entry = dict(allow.get(address) or {"added": int(time.time())})
    entry["pw"] = hash_password(password)
    allow[address] = entry
    return {**auth, "allow": allow}


def has_password(auth: dict, email: str) -> bool:
    entry = (auth.get("allow") or {}).get(normalize_email(email)) or {}
    return bool(entry.get("pw"))


# A record to hash against when the address is unknown. Without it an
# unknown address returns in ~0ms while a real one costs the ~50ms of a
# scrypt, and that difference is readable over the network -- so the door
# would answer "is this person a user?" to anyone willing to time it,
# which is the one thing the identical redirect was written to refuse.
# Measured before it was fixed: 40.6ms against 0.0ms.
_DUMMY_PW = hash_password(secrets.token_urlsafe(32))


def check_password(auth: dict, email: str, password: str) -> bool:
    """Whether this password signs this ALLOWLISTED person in.

    Membership is checked here too, so a removed account cannot be opened
    by a password that was correct yesterday. An unknown address still
    pays the full hashing cost, so answering takes the same time either
    way.
    """
    address = normalize_email(email)
    entry = (auth.get("allow") or {}).get(address) or {}
    stored = entry.get("pw")
    if not stored:
        verify_password(_DUMMY_PW, password)
        return False
    return verify_password(stored, password)


# --- throttling the sign-in door -------------------------------------------
# Opening /login to real passwords is what makes this necessary. Until now
# the form accepted exactly one address and one code from Vercel env, so
# guessing was pointless. A password per tester turns it into a door worth
# rattling, and an unthrottled one is a door that opens eventually.
#
# Counted per email rather than per IP: the attacker picks the IP and cannot
# pick whose account they want. It costs a stored write per failure, which
# at five testers is nothing, and the counters are pruned as they expire so
# the blob cannot grow without bound.
#
# Deliberately NOT a lockout an attacker can trigger at will: the lock is
# short and self-clearing, so hammering someone's address is a nuisance for
# fifteen minutes rather than a way to keep them out.
THROTTLE_MAX_FAILS = 5
THROTTLE_WINDOW_SECONDS = 15 * 60
THROTTLE_LOCK_SECONDS = 15 * 60


def _throttle_key(email: str) -> str:
    return normalize_email(email) or "?"


def locked_until(auth: dict, email: str, now_ts: float | None = None) -> float | None:
    """When this address may try again, or None if it may try now."""
    now_ts = time.time() if now_ts is None else now_ts
    entry = (auth.get("throttle") or {}).get(_throttle_key(email))
    if not entry:
        return None
    until = float(entry.get("until", 0))
    return until if until > now_ts else None


def record_failure(auth: dict, email: str, now_ts: float | None = None) -> dict:
    """Count a bad attempt, locking the address once they pile up."""
    now_ts = time.time() if now_ts is None else now_ts
    key = _throttle_key(email)
    throttle = {
        k: v
        for k, v in (auth.get("throttle") or {}).items()
        # Prune anything both unlocked and outside its window.
        if float(v.get("until", 0)) > now_ts
        or float(v.get("first", 0)) > now_ts - THROTTLE_WINDOW_SECONDS
    }
    entry = dict(throttle.get(key) or {})
    first = float(entry.get("first", now_ts))
    fails = int(entry.get("fails", 0)) + 1
    if now_ts - first > THROTTLE_WINDOW_SECONDS:
        # The window rolled over: this is the first failure of a new one.
        first, fails = now_ts, 1
    entry = {"first": first, "fails": fails}
    if fails >= THROTTLE_MAX_FAILS:
        entry["until"] = now_ts + THROTTLE_LOCK_SECONDS
    throttle[key] = entry
    return {**auth, "throttle": throttle}


def clear_failures(auth: dict, email: str) -> dict:
    """A correct password wipes the slate for that address."""
    key = _throttle_key(email)
    throttle = {k: v for k, v in (auth.get("throttle") or {}).items() if k != key}
    return {**auth, "throttle": throttle}


def peek_invite(auth: dict, token: str, now_ts: float | None = None) -> str | None:
    """The email a live invite is for, WITHOUT consuming it.

    Opening the link must not spend it. Mail clients, chat apps and
    security scanners fetch links to build previews or check them for
    malware, and every one of those fetches is a GET -- so a one-time
    link that accepts on GET can be burned before the invitee ever
    taps it, and they arrive at "this link has already been used" with
    no idea why.

    Which is also just what HTTP says: a GET is safe and repeatable, and
    consuming a token is neither. The link now lands on a confirmation
    page built from this, and only the POST accepts.
    """
    now_ts = time.time() if now_ts is None else now_ts
    digest = hashlib.sha256((token or "").encode()).hexdigest()
    entry = (auth.get("invites") or {}).get(digest)
    if not entry or entry.get("expires", 0) < now_ts:
        return None
    return normalize_email(entry.get("email", "")) or None


def accept_invite(auth: dict, token: str, now_ts: float | None = None) -> tuple[dict, str | None]:
    """(updated auth blob, email) when the token is live; (auth, None)
    otherwise. Accepting consumes the invite and allowlists the email."""
    now_ts = time.time() if now_ts is None else now_ts
    digest = hashlib.sha256((token or "").encode()).hexdigest()
    invites = dict(auth.get("invites") or {})
    entry = invites.pop(digest, None)
    if not entry or entry.get("expires", 0) < now_ts:
        return auth, None
    email = normalize_email(entry.get("email", ""))
    if not email:
        return auth, None
    allow = dict(auth.get("allow") or {})
    allow.setdefault(email, {"added": int(now_ts)})
    return {**auth, "invites": invites, "allow": allow}, email


def is_allowed(auth: dict, email: str | None, owner_email: str) -> bool:
    if not email:
        return False
    email = normalize_email(email)
    if email == normalize_email(owner_email):
        return True
    return email in (auth.get("allow") or {})


def remove_email(auth: dict, email: str) -> dict:
    """Drop an email from the allowlist and kill its pending invites --
    removal must revoke everything at once."""
    email = normalize_email(email)
    allow = {k: v for k, v in (auth.get("allow") or {}).items() if k != email}
    invites = {k: v for k, v in (auth.get("invites") or {}).items() if v.get("email") != email}
    return {**auth, "allow": allow, "invites": invites}
