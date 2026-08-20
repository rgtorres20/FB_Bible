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
    invites = dict(auth.get("invites") or {})
    invites[digest] = {
        "email": normalize_email(email),
        "expires": int(now_ts + INVITE_DAYS * 86400),
    }
    return {**auth, "invites": invites}, token


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
