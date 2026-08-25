"""Invite mail: what goes in the message, and how failures are reported.

Untested until Aug 21, which is the wrong state for the one module that
puts a **sign-in link** in an email. Two things worth holding down:

1. **The message never carries a secret it should not.** The invite link
   is the credential, so it goes to exactly one address and nowhere else
   — not in a log line, not in a subject, not to a second recipient.
2. **A failure says what to actually do about it.** This project lost
   real time to a correct SMTP config that timed out because Vercel's
   sandbox will not open the socket. "It didn't work" sends nobody
   anywhere; the module knows the difference between that, a bad
   password, and an unverified Resend domain, and the reasons are what
   the owner sees on screen.

No sockets are opened here — the repo's conftest fence blocks them — so
every transport is faked at the boundary the module actually calls.
"""

from __future__ import annotations

import json
import smtplib
import urllib.error
from email.message import EmailMessage

import pytest

from app import mailer

TO = "guest@example.com"
LINK = "https://fb.example/login?invite=super-secret-token-value"
BASE = "https://fb.example/"


class _Settings:
    """Only the fields mailer reads. A stand-in rather than the real
    Settings so a test cannot accidentally pick up a developer's env."""

    def __init__(self, **kw):
        self.resend_api_key = kw.get("resend_api_key", "")
        self.mail_from_address = kw.get("mail_from_address", "bible@example.com")
        self.smtp_host = kw.get("smtp_host", "smtp.example.com")
        self.smtp_port = kw.get("smtp_port", 587)
        self.smtp_user = kw.get("smtp_user", "user")
        self.smtp_pass = kw.get("smtp_pass", "pass")


# --- what the invite says -----------------------------------------------


def test_the_invite_carries_the_link_and_says_it_is_one_time():
    body = mailer.invite_body(LINK, BASE)
    assert LINK in body
    assert "works once" in body
    assert "7 days" in body


def test_the_invite_points_at_the_app():
    """Owner ask, Aug 21: the invite doubles as the intro. A link with no
    context reads like phishing."""
    body = mailer.invite_body(LINK, BASE)
    assert f"{BASE}app/" in body
    assert f"{BASE}login" in body


def test_the_invite_never_carries_the_owners_league_links():
    """Owner, Aug 25: "those are my personal teams". The URLs being public
    routing is beside the point -- email is the one surface that leaves
    the gate, so a forward, a shared inbox or an archive puts them in
    front of people who were never given access. Inside the app the
    allowlist decides who sees them; an email decides nothing."""
    body = mailer.invite_body(LINK, BASE)

    assert "fantasysports.yahoo.com" not in body
    for token in ("NDDPL", "RED_EYE", "BALLAPALOSA", "192426", "811739", "963878"):
        assert token not in body, f"{token} is in the invite email"


def test_the_invite_describes_the_sign_in_that_actually_exists():
    """It promised "no password to remember -- the link signs you in",
    which stopped being true when invites became two-step. A recipient
    told to expect no password meets a password form and reads it as a
    phishing page."""
    body = mailer.invite_body(LINK, BASE)

    assert "set a password" in body
    assert "No password to remember" not in body


def test_the_invite_goes_to_exactly_one_address(monkeypatch):
    """The link is the credential. A second recipient is a second
    account."""
    sent = {}
    monkeypatch.setattr(mailer, "_send", lambda msg, settings: sent.update(msg=msg))
    mailer.send_invite(TO, LINK, BASE, _Settings())
    msg = sent["msg"]
    assert msg["To"] == TO
    assert msg["Cc"] is None and msg["Bcc"] is None


def test_the_link_is_not_in_the_subject():
    """Subjects turn up in notification previews, lock screens and mail
    logs. The body is the only place the token belongs."""
    assert LINK not in mailer.SUBJECT
    assert "invite" not in mailer.SUBJECT.lower() or "token" not in mailer.SUBJECT.lower()


def test_the_test_email_never_contains_an_invite_link(monkeypatch):
    """It exists to prove the transport works, and is sent to whoever the
    owner types. It must not carry a credential."""
    sent = {}
    monkeypatch.setattr(mailer, "_send", lambda msg, settings: sent.update(msg=msg))
    mailer.send_test(TO, BASE, _Settings())
    body = sent["msg"].get_content()
    assert "invite=" not in body
    assert f"{BASE}app/access" in body


# --- choosing a transport ------------------------------------------------


def test_an_api_key_wins_over_smtp(monkeypatch):
    """HTTP is the only transport that works on Vercel — the sandbox
    hangs outbound SMTP — so a configured key must take precedence over a
    complete SMTP config rather than sit unused behind it."""
    calls = []
    monkeypatch.setattr(mailer, "_send_http", lambda msg, s: calls.append("http"))
    monkeypatch.setattr(mailer, "_send_smtp", lambda msg, s: calls.append("smtp"))
    mailer._send(EmailMessage(), _Settings(resend_api_key="re_live_key"))
    mailer._send(EmailMessage(), _Settings())
    assert calls == ["http", "smtp"]


# --- failures that say what to do ----------------------------------------


def _http_error(code: int, payload: dict) -> urllib.error.HTTPError:
    import io

    return urllib.error.HTTPError(
        mailer.RESEND_ENDPOINT, code, "err", {}, io.BytesIO(json.dumps(payload).encode())
    )


def test_an_unverified_resend_domain_is_named_as_such(monkeypatch):
    """The 403 everyone hits first. Resend will only mail your own address
    until a domain is verified, and the raw status says none of that."""

    def boom(*a, **k):
        raise _http_error(403, {"message": "The domain is not verified"})

    monkeypatch.setattr(mailer.urllib.request, "urlopen", boom)
    with pytest.raises(mailer.MailError) as exc:
        mailer.send_invite(TO, LINK, BASE, _Settings(resend_api_key="re_key"))
    assert "domain is verified" in str(exc.value)
    assert "ACCESS.md" in str(exc.value)


def test_another_resend_refusal_reports_its_status_and_reason(monkeypatch):
    def boom(*a, **k):
        raise _http_error(422, {"message": "Invalid `to` field"})

    monkeypatch.setattr(mailer.urllib.request, "urlopen", boom)
    with pytest.raises(mailer.MailError) as exc:
        mailer.send_invite(TO, LINK, BASE, _Settings(resend_api_key="re_key"))
    assert "422" in str(exc.value)
    assert "Invalid `to` field" in str(exc.value)


def test_a_failure_message_never_repeats_the_api_key(monkeypatch):
    """Repo rule: never log or return a token. These strings are rendered
    on the owner's screen."""

    def boom(*a, **k):
        raise _http_error(401, {"message": "bad key"})

    monkeypatch.setattr(mailer.urllib.request, "urlopen", boom)
    with pytest.raises(mailer.MailError) as exc:
        mailer.send_invite(TO, LINK, BASE, _Settings(resend_api_key="re_super_secret"))
    assert "re_super_secret" not in str(exc.value)


def test_a_failure_message_never_repeats_the_invite_link(monkeypatch):
    """Same rule, sharper: the link IS the credential, and an error is
    the most likely thing to be copied into a bug report."""

    def boom(*a, **k):
        raise OSError("connection reset")

    monkeypatch.setattr(mailer.urllib.request, "urlopen", boom)
    with pytest.raises(mailer.MailError) as exc:
        mailer.send_invite(TO, LINK, BASE, _Settings(resend_api_key="re_key"))
    assert "super-secret-token-value" not in str(exc.value)


def test_a_bad_smtp_password_says_it_needs_an_app_specific_one(monkeypatch):
    """iCloud and Gmail both refuse the account password, and the raw
    error does not say so."""

    class Boom:
        def __init__(self, *a, **k):
            raise smtplib.SMTPAuthenticationError(535, b"nope")

    monkeypatch.setattr(mailer.smtplib, "SMTP", Boom)
    with pytest.raises(mailer.MailError) as exc:
        mailer.send_invite(TO, LINK, BASE, _Settings())
    assert "app-specific password" in str(exc.value)


def test_an_smtp_timeout_names_the_real_cause(monkeypatch):
    """The failure this project actually hit: a correct config that hangs
    because Vercel will not open the socket. No port or password fixes
    it, so the message has to say to stop trying them."""

    class Boom:
        def __init__(self, *a, **k):
            raise TimeoutError("timed out")

    monkeypatch.setattr(mailer.smtplib, "SMTP", Boom)
    with pytest.raises(mailer.MailError) as exc:
        mailer.send_invite(TO, LINK, BASE, _Settings())
    assert "Vercel" in str(exc.value)
    assert "RESEND_API_KEY" in str(exc.value)


def test_port_465_uses_implicit_tls_and_anything_else_starts_tls(monkeypatch):
    """Getting this backwards is a silent plaintext send on 465 or a
    hang on 587."""
    used = []

    class Rec:
        def __init__(self, host, port, timeout=None):
            used.append(("ssl" if self.ssl else "plain", port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            used.append(("starttls", None))

        def login(self, *a):
            pass

        def send_message(self, msg):
            pass

    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", type("S", (Rec,), {"ssl": True}))
    monkeypatch.setattr(mailer.smtplib, "SMTP", type("P", (Rec,), {"ssl": False}))
    mailer.send_invite(TO, LINK, BASE, _Settings(smtp_port=465))
    mailer.send_invite(TO, LINK, BASE, _Settings(smtp_port=587))
    assert used == [("ssl", 465), ("plain", 587), ("starttls", None)]


# --- reading the API's reason, whatever shape it arrives in ------------------
# The owner hit "Resend refused it (403)." with nothing after it. The reason
# was in the response body; the parser read only a top-level `message` and
# dropped everything else. A bare status sends someone hunting through four
# settings pages for a cause the API already named.


def _raw_error(code: int, body: bytes) -> urllib.error.HTTPError:
    import io

    return urllib.error.HTTPError(mailer.RESEND_ENDPOINT, code, "err", {}, io.BytesIO(body))


def test_a_nested_error_object_still_yields_its_message(monkeypatch):
    """Resend has used {"error": {"message": ...}} as well as a flat one."""
    monkeypatch.setattr(
        mailer.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(
            _http_error(422, {"error": {"message": "from must be a valid email"}})
        ),
    )

    with pytest.raises(mailer.MailError, match="from must be a valid email"):
        mailer.send_invite(TO, LINK, BASE, _Settings(resend_api_key="re_key"))


def test_a_non_json_body_falls_back_to_its_first_line(monkeypatch):
    """A gateway can answer HTML. That is still more than a bare status."""
    monkeypatch.setattr(
        mailer.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(
            _raw_error(502, b"Bad Gateway\nupstream timed out\n")
        ),
    )

    with pytest.raises(mailer.MailError, match="Bad Gateway"):
        mailer.send_invite(TO, LINK, BASE, _Settings(resend_api_key="re_key"))


def test_an_unreadable_403_still_names_the_likeliest_cause(monkeypatch):
    """What the owner actually got. An empty body must not become a bare
    status: 403 from Resend is an unverified sender nearly every time, so
    say that -- as the likeliest cause, not as a certainty."""
    monkeypatch.setattr(
        mailer.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(_raw_error(403, b"")),
    )

    with pytest.raises(mailer.MailError) as caught:
        mailer.send_invite(TO, LINK, BASE, _Settings(resend_api_key="re_key"))

    assert "Verified" in str(caught.value)
    assert "MAIL_FROM" in str(caught.value)


def test_the_testing_emails_wording_is_recognised_too(monkeypatch):
    """Resend's 403 does not always say "domain" -- it often says you can
    only send testing emails to your own address. Same cause, and matching
    on one wording alone let the other fall through to a bare status."""
    monkeypatch.setattr(
        mailer.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(
            _http_error(
                403,
                {"message": "You can only send testing emails to your own email address"},
            )
        ),
    )

    with pytest.raises(mailer.MailError, match="verified"):
        mailer.send_invite(TO, LINK, BASE, _Settings(resend_api_key="re_key"))


def test_the_reason_is_capped_so_an_error_page_is_not_a_wall(monkeypatch):
    monkeypatch.setattr(
        mailer.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(_raw_error(500, b"x" * 5000)),
    )

    with pytest.raises(mailer.MailError) as caught:
        mailer.send_invite(TO, LINK, BASE, _Settings(resend_api_key="re_key"))

    assert len(str(caught.value)) < 400


def test_the_request_identifies_itself(monkeypatch):
    """Resend's API is behind Cloudflare, whose browser integrity check
    bans urllib's default "Python-urllib/3.x" signature. The result is a
    403 carrying Cloudflare error 1010 -- which reads exactly like the API
    refusing the key or the sender domain, and sent the owner hunting
    through Resend's dashboard for a cause that was never there.

    Pinned because the header is invisible in every other test: they all
    stub urlopen, so nothing else would notice it being dropped."""
    seen = {}

    def capture(req, *a, **k):
        seen["ua"] = req.get_header("User-agent")
        seen["accept"] = req.get_header("Accept")

        class _R:
            def read(self):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _R()

    monkeypatch.setattr(mailer.urllib.request, "urlopen", capture)
    mailer.send_invite(TO, LINK, BASE, _Settings(resend_api_key="re_key"))

    assert seen["ua"] == mailer.USER_AGENT
    assert "urllib" not in (seen["ua"] or "").lower()
    assert "python" not in (seen["ua"] or "").lower()
    assert seen["accept"] == "application/json"


def test_a_cloudflare_block_is_not_reported_as_an_api_refusal(monkeypatch):
    """1010 comes from the edge, not from Resend. Telling the owner their
    domain is unverified would be a fabricated cause -- the request never
    reached the API."""
    body = b"<html><title>Access denied</title><body>error code: 1010</body></html>"
    monkeypatch.setattr(
        mailer.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(_raw_error(403, body)),
    )

    with pytest.raises(mailer.MailError) as caught:
        mailer.send_invite(TO, LINK, BASE, _Settings(resend_api_key="re_key"))

    note = str(caught.value)
    assert "1010" in note, "the edge's own code is the whole diagnosis"
    assert "not verified" not in note.lower()
