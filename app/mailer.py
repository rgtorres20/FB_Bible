"""Invite email: what a new user gets when the owner adds them.

Owner request (Aug 20): "when I create a user I want it to send an email
to them with link to league and info about my app."

Plain SMTP over stdlib on purpose -- no vendor SDK, no new dependency;
any provider works and the documented free path is a Gmail app password
(docs/ACCESS.md). Sending is best-effort: a failure is reported on the
access page and the one-time link is still shown there, so delivery
trouble never strands an invite. The link is never logged either way.
"""

from __future__ import annotations

import json
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage

from .config import Settings

RESEND_ENDPOINT = "https://api.resend.com/emails"

# Sent on every outbound call. A default "Python-urllib/3.x" is banned by
# Cloudflare's browser integrity check, which fronts Resend's API, so the
# request never arrives: 403, Cloudflare error 1010, indistinguishable
# from the API refusing us. Identifying the app honestly is also what a
# provider wants when they need to trace traffic back to a caller.
USER_AGENT = "FantasySportsBible/1.0 (+https://fantasysportsbible.com)"


class MailError(RuntimeError):
    """A send that failed, carrying a reason a person can act on."""


# The invite deliberately carries NO league links (owner, Aug 25).
#
# They used to be listed here as "public routing, not user data" -- true
# of the URLs, and beside the point. These are the owner's own teams, and
# email is the one surface that leaves the gate: a forwarded invite, a
# shared inbox or a mail archive puts them in front of people who were
# never given access. Inside the app the allowlist decides who sees them.
# An email decides nothing.

SUBJECT = "You're invited to Fantasy Sports Bible"

# One line, used by both the plain-text and HTML bodies so they cannot
# drift into describing the app differently (owner, Aug 25).
TAGLINE = "The place for all your fantasy needs"

# Written once, rendered into both bodies. Two hand-kept lists is how the
# HTML mail ends up promising something the plain-text one does not.
FEATURES = (
    "Live news wire with AI-drafted reads, updated hourly",
    "Draft cheat sheet built from live ADP, scored by league settings",
    "Mock draft room: pick your slot, the room autopicks the rest",
    "IDP draft board scored with each league's real settings",
    "In-season scoring, pickup board and a graded prediction scorecard",
    "\u201cMy stuff\u201d: your own notes and rankings, private to you",
)


def invite_body(invite_link: str, app_base: str) -> str:
    features = "\n".join(f"  - {item}" for item in FEATURES)
    return f"""You've been invited to Fantasy Sports Bible -- the place for
all your fantasy needs.

Your invite link (works once, expires in 7 days):

  {invite_link}

Open it and you'll set a password. After that you can sign in from
any device -- phone, laptop, tablet -- at

  {app_base}login

and add Face ID or Touch ID from "My stuff" to skip typing it.

Once you're in ({app_base}app/):

{features}

If the link expires, ask for a fresh one.
"""


# Navy is the app's own (`skin.py` theme-color). The mark is white and
# gold, so it MUST sit on navy or it vanishes -- the same rule that binds
# every other surface (CLAUDE.md, "The mark").
NAVY = "#0B1A36"

# A PNG, not the SVG the app itself uses: Gmail and Outlook strip SVG.
# Loaded from /app/icons/, one of the four paths the access gate
# deliberately leaves open -- everything else under /app answers 401, and
# an invite's recipient is by definition not signed in yet, so any other
# path renders a broken image.
#
# Its own file rather than the manifest icon. icon-192.png is opaque with
# white corners, which is CORRECT for a home-screen tile and wrong here:
# on the navy panel it reads as a white frame around the mark. email-mark
# is rendered from fsb-mark.svg with a transparent background, so the
# white-and-gold mark sits on the navy directly (docs/BRAND.md -- and it
# regenerates from the same SVG whenever the artwork changes).
LOGO_PATH = "app/icons/email-mark.png"
LOGO_W, LOGO_H = 132, 99  # the mark's own 4:3, not a square


def invite_html(invite_link: str, app_base: str) -> str:
    """The same invite, with the mark on it.

    Tables and inline styles because that is what mail clients render;
    a stylesheet or a flex layout is not portable here.

    This is an ALTERNATIVE to the plain text, never a replacement. Some
    clients show text only, some people prefer it, and a mail with no
    text part looks like bulk to a spam filter -- so both say the same
    thing, and the text one stays the source of truth.
    """
    logo = f"{app_base}{LOGO_PATH}"
    features = "".join(
        f"<tr><td style='padding:3px 0;color:#334155;font-size:15px;"
        f"line-height:22px'>{item}</td></tr>"
        for item in FEATURES
    )
    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#f1f5f9">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
 style="background:#f1f5f9;padding:24px 12px">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
 style="max-width:520px;background:#ffffff;border-radius:12px;overflow:hidden;
 font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif">

  <tr><td align="center" style="background:{NAVY};padding:28px 24px">
    <!-- alt is empty on purpose: the name is the line directly below, so
         with images blocked (which is most clients, by default) alt text
         here just prints "Fantasy Sports Bible" twice. Decorative image,
         adjacent text carries the meaning. -->
    <img src="{logo}" width="{LOGO_W}" height="{LOGO_H}" alt=""
     style="display:block;border:0;width:{LOGO_W}px;height:{LOGO_H}px">
    <div style="color:#ffffff;font-size:20px;font-weight:700;padding-top:12px">
      Fantasy Sports Bible</div>
    <div style="color:#cbd5e1;font-size:14px;padding-top:4px">{TAGLINE}</div>
  </td></tr>

  <tr><td style="padding:28px 24px 8px;color:#0f172a;font-size:16px;line-height:24px">
    You've been invited to Fantasy Sports Bible.
  </td></tr>

  <tr><td align="center" style="padding:12px 24px 8px">
    <a href="{invite_link}"
     style="display:inline-block;background:{NAVY};color:#ffffff;text-decoration:none;
     font-size:16px;font-weight:600;padding:13px 30px;border-radius:8px">
      Accept your invite</a>
  </td></tr>

  <tr><td align="center" style="padding:0 24px 16px;color:#64748b;font-size:13px">
    Works once, expires in 7 days.
  </td></tr>

  <tr><td style="padding:0 24px 20px;color:#334155;font-size:15px;line-height:22px">
    You'll set a password, then sign in from any device at
    <a href="{app_base}login" style="color:{NAVY}">{app_base}login</a> —
    phone, laptop or tablet. Add Face ID or Touch ID from “My stuff” to
    skip typing it.
  </td></tr>

  <tr><td style="padding:0 24px 8px;color:{NAVY};font-size:13px;font-weight:700;
   letter-spacing:.04em;text-transform:uppercase">What's inside</td></tr>
  <tr><td style="padding:0 24px 24px"><table role="presentation" cellpadding="0"
   cellspacing="0">{features}</table></td></tr>

  <tr><td style="background:#f8fafc;padding:16px 24px;color:#64748b;font-size:12px;
   line-height:18px">
    If the button doesn't work, paste this into your browser:<br>
    <span style="color:#334155;word-break:break-all">{invite_link}</span><br><br>
    If the link has expired, ask for a fresh one.
  </td></tr>

</table>
</td></tr></table>
</body></html>
"""


def send_invite(to_email: str, invite_link: str, app_base: str, settings: Settings) -> None:
    """Raises on failure -- the caller shows the link as the fallback."""
    msg = EmailMessage()
    msg["Subject"] = SUBJECT
    msg["From"] = settings.mail_from_address
    msg["To"] = to_email
    msg.set_content(invite_body(invite_link, app_base))
    msg.add_alternative(invite_html(invite_link, app_base), subtype="html")
    _send(msg, settings)


TEST_SUBJECT = "Fantasy Sports Bible — test email"


def send_test(to_email: str, app_base: str, settings: Settings) -> None:
    """Prove the SMTP settings work, from the owner's own screen.

    Raises on failure so the caller can show the real reason -- an
    authentication error and a blocked port need different fixes, and
    "it didn't work" sends nobody anywhere.
    """
    msg = EmailMessage()
    msg["Subject"] = TEST_SUBJECT
    msg["From"] = settings.mail_from_address
    msg["To"] = to_email
    msg.set_content(
        "This is a test from Fantasy Sports Bible.\n\n"
        "If you are reading it, invite mail works: adding someone at\n"
        f"{app_base}app/access will email them their sign-in link\n"
        "along with an intro to the app and both league links.\n"
    )
    _send(msg, settings)


def _send(msg: EmailMessage, settings: Settings) -> None:
    """Dispatch by whichever transport is configured.

    HTTP wins when present because it is the only one that works on
    Vercel: the serverless sandbox hangs outbound SMTP connections, so a
    correct SMTP config still times out there. SMTP stays for local and
    self-hosted runs, where it is fine and needs no third party.
    """
    if settings.resend_api_key:
        _send_http(msg, settings)
    else:
        _send_smtp(msg, settings)


def _bodies(msg: EmailMessage) -> tuple[str, str]:
    """(plain text, html) out of a message that may be either shape.

    `msg.get_content()` raises on a multipart message, so this had to
    change the moment the invite gained an HTML alternative -- SMTP sends
    the assembled MIME object and never noticed, but the Resend path pulls
    the bodies out by hand and would have thrown on every invite while the
    text-only test mail kept passing. The one that gets exercised least is
    the one that breaks.

    html is "" when there is no HTML part, which the caller uses to decide
    whether to send the field at all.
    """
    if not msg.is_multipart():
        return msg.get_content(), ""
    text = html = ""
    for part in msg.walk():
        if part.is_multipart():
            continue
        kind = part.get_content_type()
        if kind == "text/plain" and not text:
            text = part.get_content()
        elif kind == "text/html" and not html:
            html = part.get_content()
    return text, html


def _send_http(msg: EmailMessage, settings: Settings) -> None:
    """Resend's HTTP API, over 443. stdlib only -- no SDK, no new dep."""
    text, html = _bodies(msg)
    body: dict[str, object] = {
        "from": settings.mail_from_address,
        "to": [msg["To"]],
        "subject": msg["Subject"],
        "text": text,
    }
    # Only when there is one. Resend rejects an empty `html`, and the test
    # mail is deliberately text-only.
    if html:
        body["html"] = html
    payload = json.dumps(body).encode()
    request = urllib.request.Request(
        RESEND_ENDPOINT,
        data=payload,
        headers={
            "Authorization": f"Bearer {settings.resend_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Not optional. Without it urllib sends "Python-urllib/3.x",
            # and Resend's API sits behind Cloudflare, whose browser
            # integrity check bans that signature outright -- a 403 with
            # Cloudflare error 1010, before Resend sees the request at
            # all. It looks exactly like an API refusal and is not one:
            # no key, sender or domain change can fix it. See USER_AGENT.
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        detail = _api_detail(exc)
        if exc.code == 403 and ("domain" in detail.lower() or "testing emails" in detail.lower()):
            raise MailError(
                "Resend will only mail your own address until a domain is "
                "verified — see docs/ACCESS.md. It said: " + detail
            ) from exc
        if exc.code == 403 and not detail:
            # A 403 with a body we could not read. Do not invent a cause,
            # but do not pretend the status alone is useless either: this
            # is the one Resend returns for an unverified sender.
            raise MailError(
                "Resend refused it (403) and sent no readable reason. That "
                "status is almost always an unverified sending domain — "
                "check Resend > Domains says Verified, and that MAIL_FROM "
                "uses exactly that domain."
            ) from exc
        raise MailError(f"Resend refused it ({exc.code}). {detail}".strip()) from exc
    except Exception as exc:  # noqa: BLE001 - network trouble, reported as-is
        raise MailError(f"Could not reach Resend ({type(exc).__name__}).") from exc


def _api_detail(exc: urllib.error.HTTPError) -> str:
    """Whatever reason the API actually gave, out of any shape it uses.

    This read only `message` off the top level, so a body shaped any other
    way became "" and the owner got a bare status -- the diagnosis fetched
    and then dropped, one layer below the button that had the same bug.
    Resend has used both `{"message": ...}` and `{"error": {"message":
    ...}}`, and an error body is not always JSON at all (a gateway can
    answer HTML), so an unparseable body falls back to its own first line
    rather than to nothing.

    The body is read once -- HTTPError is a stream, and a second read
    returns b"" -- and truncated, since a proxy error page is not a
    reason.
    """
    try:
        raw = exc.read() or b""
    except Exception:  # noqa: BLE001 - an unreadable body is not a crash
        return ""
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    try:
        body = json.loads(text)
    except ValueError:
        return text.splitlines()[0][:200]
    if isinstance(body, dict):
        for key in ("message", "error", "detail", "name"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value[:200]
            if isinstance(value, dict) and isinstance(value.get("message"), str):
                return value["message"][:200]
    return text[:200]


def _send_smtp(msg: EmailMessage, settings: Settings) -> None:
    try:
        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20) as server:
                server.login(settings.smtp_user, settings.smtp_pass)
                server.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_pass)
                server.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(
            "SMTP rejected the login — iCloud and Gmail both need an "
            "app-specific password, not the account password."
        ) from exc
    except (TimeoutError, OSError) as exc:
        # The failure this project actually hit: a correct config that
        # hangs because the host will not open the socket.
        raise MailError(
            "SMTP timed out. Vercel's sandbox blocks outbound SMTP, so no "
            "port or password will fix this there — set RESEND_API_KEY and "
            "mail goes over HTTPS instead (docs/ACCESS.md)."
        ) from exc
