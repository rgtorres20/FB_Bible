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


# The leagues' own pages (docs/LEAGUES.md). Yahoo's league URLs are
# public routing, not user data.
LEAGUE_LINKS = (
    ("NDDPL", "https://football.fantasysports.yahoo.com/f1/192426"),
    ("RED_EYE", "https://football.fantasysports.yahoo.com/league/red_eye"),
)

SUBJECT = "You're invited to Fantasy Sports Bible"


def invite_body(invite_link: str, app_base: str) -> str:
    leagues = "\n".join(f"  - {name}: {url}" for name, url in LEAGUE_LINKS)
    return f"""You've been invited to Fantasy Sports Bible -- our draft-prep app
for this season's leagues.

Your sign-in link (works once, expires in 7 days -- open it on the
device you'll use):

  {invite_link}

Once you're in ({app_base}app/):

  - Live news wire with AI-drafted reads, updated hourly
  - Draft cheat sheet built from live ADP, tuned to our scoring
  - Mock draft room: pick your slot, the room autopicks the rest
  - IDP draft board scored with each league's real settings
  - "My stuff" (/app/mine): your own notes and rankings, private to you

The leagues:

{leagues}

No password to remember -- the link signs you in. If it expires, ask for
a fresh one.
"""


def send_invite(to_email: str, invite_link: str, app_base: str, settings: Settings) -> None:
    """Raises on failure -- the caller shows the link as the fallback."""
    msg = EmailMessage()
    msg["Subject"] = SUBJECT
    msg["From"] = settings.mail_from_address
    msg["To"] = to_email
    msg.set_content(invite_body(invite_link, app_base))
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


def _send_http(msg: EmailMessage, settings: Settings) -> None:
    """Resend's HTTP API, over 443. stdlib only -- no SDK, no new dep."""
    payload = json.dumps(
        {
            "from": settings.mail_from_address,
            "to": [msg["To"]],
            "subject": msg["Subject"],
            "text": msg.get_content(),
        }
    ).encode()
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
