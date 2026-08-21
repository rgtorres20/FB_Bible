"""Passkeys: Face ID / Touch ID sign-in, layered on the email identity.

Owner request (Aug 21): "any way we can use Apple passkey so it would log
in with face recognition or fingerprint". Yes -- WebAuthn is a browser
standard, works with iOS/macOS Face ID and Touch ID, Android and Windows
Hello, and needs no paid service.

Shape, sized to this deployment:

  - A passkey is a *faster way in for someone who already has access*,
    never a way to grant it. You sign in once the normal way (owner code
    or invite link), then register a passkey on that device. Login still
    ends in the same allowlist check, so removing an email locks out its
    passkeys too.
  - Credentials are discoverable (resident) with user verification
    REQUIRED, which is what makes the phone ask for a face or a finger
    rather than a bare tap -- and what lets the sign-in button work with
    no email typed at all.
  - The two-step challenge lives in a short-lived signed cookie rather
    than the store: serverless has no sticky instance, and a challenge
    the server itself signed is one the server can trust back.
  - Only public keys are stored. A passkey's private half never leaves
    the device's secure enclave, so this store holds nothing that can
    impersonate anyone.

Bound to the domain: credentials are scoped to the site's hostname (the
"RP ID"). Moving to a custom domain means everyone re-registers -- stated
in docs/ACCESS.md rather than discovered later.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

CHALLENGE_COOKIE = "fb_pk_chal"
CHALLENGE_SECONDS = 300
RP_NAME = "Fantasy Bible"


def _sign(secret: str, body: str) -> str:
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def from_b64url(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def mint_challenge(challenge: bytes, secret: str, now_ts: float | None = None) -> str:
    """The challenge, its expiry and our signature, as one cookie value."""
    now_ts = time.time() if now_ts is None else now_ts
    body = f"{b64url(challenge)}|{int(now_ts + CHALLENGE_SECONDS)}"
    return b64url(f"{body}|{_sign(secret, body)}".encode())


def read_challenge(cookie: str | None, secret: str, now_ts: float | None = None) -> bytes | None:
    """The challenge we issued, or None for anything stale or forged."""
    if not cookie or not secret:
        return None
    now_ts = time.time() if now_ts is None else now_ts
    try:
        decoded = from_b64url(cookie).decode()
        chal, expires, signature = decoded.rsplit("|", 2)
    except Exception:  # noqa: BLE001 - a malformed cookie is just "no challenge"
        return None
    if not hmac.compare_digest(signature, _sign(secret, f"{chal}|{expires}")):
        return None
    try:
        if int(expires) < now_ts:
            return None
        return from_b64url(chal)
    except (ValueError, Exception):  # noqa: BLE001
        return None


def rp_from_request(request) -> tuple[str, str]:
    """(rp_id, expected_origin) for this deployment.

    Derived from the request rather than configured, so a domain change
    needs no env edit -- and read from the proxy headers, because behind
    Vercel the ASGI scope reports neither the public host nor https.
    """
    host = (
        request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    )
    host = host.split(",")[0].strip()
    hostname = host.split(":")[0]
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    proto = proto or request.url.scheme
    if hostname in ("localhost", "127.0.0.1"):
        return hostname, f"{proto}://{host}"  # dev keeps its port
    return hostname, f"https://{hostname}"


# --- credential storage (inside the auth blob, so syncs can never touch it) ---


def list_for(auth: dict, email: str) -> list[dict]:
    return list((auth.get("passkeys") or {}).get(email) or [])


def add_credential(
    auth: dict, email: str, cred_id: bytes, public_key: bytes, sign_count: int, label: str
) -> dict:
    passkeys = {k: list(v) for k, v in (auth.get("passkeys") or {}).items()}
    entries = passkeys.setdefault(email, [])
    cid = b64url(cred_id)
    entries[:] = [e for e in entries if e.get("id") != cid]  # re-register replaces
    entries.append(
        {
            "id": cid,
            "pk": b64url(public_key),
            "sign_count": sign_count,
            "label": (label or "This device")[:40],
            "added": int(time.time()),
        }
    )
    return {**auth, "passkeys": passkeys}


def find_credential(auth: dict, cred_id: str) -> tuple[str, dict] | None:
    for email, entries in (auth.get("passkeys") or {}).items():
        for entry in entries or []:
            if entry.get("id") == cred_id:
                return email, entry
    return None


def bump_sign_count(auth: dict, email: str, cred_id: str, new_count: int) -> dict:
    passkeys = {k: [dict(e) for e in v] for k, v in (auth.get("passkeys") or {}).items()}
    for entry in passkeys.get(email) or []:
        if entry.get("id") == cred_id:
            entry["sign_count"] = new_count
    return {**auth, "passkeys": passkeys}


def remove_credential(auth: dict, email: str, cred_id: str) -> dict:
    passkeys = {k: list(v) for k, v in (auth.get("passkeys") or {}).items()}
    passkeys[email] = [e for e in passkeys.get(email) or [] if e.get("id") != cred_id]
    return {**auth, "passkeys": passkeys}


def drop_all_for(auth: dict, email: str) -> dict:
    """Removing someone's access removes their passkeys with it."""
    passkeys = {k: v for k, v in (auth.get("passkeys") or {}).items() if k != email}
    return {**auth, "passkeys": passkeys}


# --- the browser half -------------------------------------------------------
# Shared by /login (sign in) and /app/mine (register). Hand-built payloads
# rather than PublicKeyCredential.toJSON(), which older Safari lacks.

BROWSER_JS = r"""
window.FBPK = (function () {
  var supported = !!(window.PublicKeyCredential && navigator.credentials);
  function toBuf(s) {
    s = s.replace(/-/g, '+').replace(/_/g, '/');
    while (s.length % 4) s += '=';
    var raw = atob(s), out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out.buffer;
  }
  function toB64(buf) {
    var bytes = new Uint8Array(buf), s = '';
    for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  async function post(url, body) {
    var r = await fetch(url, {
      method: 'POST',
      headers: body ? { 'content-type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined
    });
    var data = null;
    try { data = await r.json(); } catch (e) {}
    if (!r.ok) throw new Error((data && data.detail) || ('HTTP ' + r.status));
    return data;
  }

  async function signIn() {
    var opts = await post('/passkey/login/options');
    opts.challenge = toBuf(opts.challenge);
    (opts.allowCredentials || []).forEach(function (c) { c.id = toBuf(c.id); });
    var cred = await navigator.credentials.get({ publicKey: opts });
    if (!cred) throw new Error('No passkey chosen');
    return post('/passkey/login/verify', {
      credential: {
        id: cred.id, rawId: toB64(cred.rawId), type: cred.type,
        authenticatorAttachment: cred.authenticatorAttachment || undefined,
        clientExtensionResults: cred.getClientExtensionResults(),
        response: {
          clientDataJSON: toB64(cred.response.clientDataJSON),
          authenticatorData: toB64(cred.response.authenticatorData),
          signature: toB64(cred.response.signature),
          userHandle: cred.response.userHandle ? toB64(cred.response.userHandle) : null
        }
      }
    });
  }

  async function register(label) {
    var opts = await post('/passkey/register/options');
    opts.challenge = toBuf(opts.challenge);
    opts.user.id = toBuf(opts.user.id);
    (opts.excludeCredentials || []).forEach(function (c) { c.id = toBuf(c.id); });
    var cred = await navigator.credentials.create({ publicKey: opts });
    if (!cred) throw new Error('Setup cancelled');
    return post('/passkey/register/verify', {
      label: label,
      credential: {
        id: cred.id, rawId: toB64(cred.rawId), type: cred.type,
        authenticatorAttachment: cred.authenticatorAttachment || undefined,
        clientExtensionResults: cred.getClientExtensionResults(),
        response: {
          clientDataJSON: toB64(cred.response.clientDataJSON),
          attestationObject: toB64(cred.response.attestationObject),
          transports: cred.response.getTransports ? cred.response.getTransports() : []
        }
      }
    });
  }

  return { supported: supported, signIn: signIn, register: register };
})();
"""
