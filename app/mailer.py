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

import smtplib
from email.message import EmailMessage

from .config import Settings

# The leagues' own pages (docs/LEAGUES.md). Yahoo's league URLs are
# public routing, not user data.
LEAGUE_LINKS = (
    ("NDDPL", "https://football.fantasysports.yahoo.com/f1/192426"),
    ("RED_EYE", "https://football.fantasysports.yahoo.com/league/red_eye"),
)

SUBJECT = "You're invited to the Fantasy Bible"


def invite_body(invite_link: str, app_base: str) -> str:
    leagues = "\n".join(f"  - {name}: {url}" for name, url in LEAGUE_LINKS)
    return f"""You've been invited to the Fantasy Bible -- our draft-prep app
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
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to_email
    msg.set_content(invite_body(invite_link, app_base))
    _send(msg, settings)


TEST_SUBJECT = "Fantasy Bible — test email"


def send_test(to_email: str, app_base: str, settings: Settings) -> None:
    """Prove the SMTP settings work, from the owner's own screen.

    Raises on failure so the caller can show the real reason -- an
    authentication error and a blocked port need different fixes, and
    "it didn't work" sends nobody anywhere.
    """
    msg = EmailMessage()
    msg["Subject"] = TEST_SUBJECT
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to_email
    msg.set_content(
        "This is a test from the Fantasy Bible.\n\n"
        "If you are reading it, invite mail works: adding someone at\n"
        f"{app_base}app/access will email them their sign-in link\n"
        "along with an intro to the app and both league links.\n"
    )
    _send(msg, settings)


def _send(msg: EmailMessage, settings: Settings) -> None:
    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            server.login(settings.smtp_user, settings.smtp_pass)
            server.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_pass)
            server.send_message(msg)
