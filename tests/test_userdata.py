"""My stuff (/app/mine) and the invite email.

The contract: the personal layer needs a signed-in identity and shows
each email only its own documents; caps are enforced with honest
messages; and adding a user emails the invite when mail is configured --
with the link still shown on the page as the fallback either way.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import authn, mailer, main
from app.config import get_settings
from app.feeds.store import FileFeedStore
from app.routes import access as access_route
from app.routes import feeds as feeds_route


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    s = get_settings()
    monkeypatch.setattr(s, "app_auth", True, raising=False)
    monkeypatch.setattr(s, "owner_email", "owner@example.com", raising=False)
    monkeypatch.setattr(s, "app_owner_code", "open-sesame", raising=False)
    monkeypatch.setattr(s, "session_secret", "unit-test-secret", raising=False)
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    monkeypatch.setattr(access_route, "build_feed_store", lambda _s: store)
    yield TestClient(main.app), store
    main.app.dependency_overrides.clear()


def _sign_in_owner(c: TestClient) -> None:
    c.post("/login", data={"email": "owner@example.com", "code": "open-sesame"})


# --- /app/mine ---------------------------------------------------------------


def test_mine_requires_a_signed_in_identity(client):
    c, _ = client
    # Bypass the /app gate with a would-be sync caller: still no identity,
    # so the page asks for sign-in rather than guessing whose data to show.
    monkey_headers = {"accept": "text/html"}
    r = c.get("/app/mine", headers=monkey_headers, follow_redirects=False)
    assert r.status_code == 303  # gate: not signed in at all


def test_save_view_and_delete_a_document(client):
    c, _ = client
    _sign_in_owner(c)
    r = c.post(
        "/app/mine/save",
        files={"name": (None, "Draft notes"), "text": (None, "target Gibbs early")},
        follow_redirects=True,
    )
    assert "Draft notes" in r.text and "target Gibbs early" in r.text
    r = c.post("/app/mine/delete", data={"name": "Draft notes"}, follow_redirects=True)
    assert "target Gibbs early" not in r.text
    assert "Nothing saved yet" in r.text


def test_file_upload_lands_as_text(client):
    c, _ = client
    _sign_in_owner(c)
    r = c.post(
        "/app/mine/save",
        files={
            "name": (None, "My rankings"),
            "text": (None, ""),
            "file": ("ranks.csv", b"rank,player\n1,Gibbs", "text/csv"),
        },
        follow_redirects=True,
    )
    assert "rank,player" in r.text
    # A binary file is refused with a plain reason, never stored garbled.
    r = c.post(
        "/app/mine/save",
        files={
            "name": (None, "Binary"),
            "text": (None, ""),
            "file": ("x.bin", b"\xff\xfe\x00\x01", "application/octet-stream"),
        },
    )
    assert "isn&#x27;t text" in r.text


async def test_documents_are_isolated_per_email(client):
    c, store = client
    _sign_in_owner(c)
    c.post("/app/mine/save", files={"name": (None, "Secret"), "text": (None, "mine only")})

    # A second signed-in user (allowlisted) sees none of it.
    await store.save_auth({"allow": {"buddy@example.com": {"added": 0}}})
    other = TestClient(main.app)
    s = get_settings()
    other.cookies.set(
        authn.SESSION_COOKIE, authn.mint_session("buddy@example.com", s.session_secret)
    )
    page = other.get("/app/mine").text
    assert "mine only" not in page
    assert "Nothing saved yet" in page


def test_size_cap_is_enforced_with_an_honest_message(client, monkeypatch):
    from app.routes import userdata

    monkeypatch.setattr(userdata, "MAX_DOC_BYTES", 50)
    c, _ = client
    _sign_in_owner(c)
    r = c.post(
        "/app/mine/save",
        files={"name": (None, "Big"), "text": (None, "x" * 100)},
    )
    assert "Too big" in r.text


# --- the invite email --------------------------------------------------------


def test_invite_email_carries_link_leagues_and_app_info():
    body = mailer.invite_body("https://x/login/invite/tok123", "https://x/")
    assert "https://x/login/invite/tok123" in body
    assert "192426" in body and "red_eye" in body  # both league links
    assert "Mock draft room" in body and "My stuff" in body


def test_add_sends_the_email_when_configured_and_reports_failure(client, monkeypatch):
    c, _ = client
    _sign_in_owner(c)
    s = get_settings()
    monkeypatch.setattr(s, "smtp_host", "smtp.example.com", raising=False)
    monkeypatch.setattr(s, "smtp_user", "owner@example.com", raising=False)
    monkeypatch.setattr(s, "smtp_pass", "app-password", raising=False)

    sent = {}

    def fake_send(to_email, link, base, settings):
        sent["to"] = to_email
        sent["link"] = link

    monkeypatch.setattr(mailer, "send_invite", fake_send)
    page = c.post("/app/access/add", data={"email": "pal@example.com"}).text
    assert sent["to"] == "pal@example.com" and "/login/invite/" in sent["link"]
    assert "Invite emailed" in page
    assert sent["link"] in page  # the backup copy still renders

    def broken_send(*a, **k):
        raise ConnectionError("boom")

    monkeypatch.setattr(mailer, "send_invite", broken_send)
    page = c.post("/app/access/add", data={"email": "pal2@example.com"}).text
    assert "Emailing failed" in page and "/login/invite/" in page


def test_without_mail_config_the_page_says_send_it_yourself(client):
    c, _ = client
    _sign_in_owner(c)
    page = c.post("/app/access/add", data={"email": "pal3@example.com"}).text
    assert "send it yourself" in page and "/login/invite/" in page


def test_owner_can_send_themselves_a_test_email(client, monkeypatch):
    """'I never got one' has several causes; the button names the real one."""
    c, _ = client
    _sign_in_owner(c)
    s = get_settings()

    # Unconfigured: says so plainly instead of pretending to send.
    page = c.post("/app/access/test-mail", follow_redirects=True).text
    assert "isn&#x27;t configured" in page or "not configured" in page.lower()

    monkeypatch.setattr(s, "smtp_host", "smtp.mail.me.com", raising=False)
    monkeypatch.setattr(s, "smtp_user", "owner@example.com", raising=False)
    monkeypatch.setattr(s, "smtp_pass", "app-specific", raising=False)

    sent = {}
    monkeypatch.setattr(
        mailer, "send_test", lambda to, base, settings: sent.update(to=to, base=base)
    )
    page = c.post("/app/access/test-mail", follow_redirects=True).text
    assert sent["to"] == "owner@example.com"
    assert "Test email sent" in page

    # A failure reports the reason rather than a shrug.
    def boom(*a, **k):
        raise TimeoutError("port blocked")

    monkeypatch.setattr(mailer, "send_test", boom)
    page = c.post("/app/access/test-mail", follow_redirects=True).text
    assert "Send failed: TimeoutError" in page


def test_smtp_timeout_names_the_platform_not_the_port():
    """The failure this actually hit: a correct SMTP config that hangs
    because Vercel will not open the socket. Telling the owner to check
    the port sends them somewhere there is no fix."""
    s = get_settings()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(s, "resend_api_key", "", raising=False)
        mp.setattr(s, "smtp_host", "smtp.mail.me.com", raising=False)
        mp.setattr(s, "smtp_user", "me@icloud.com", raising=False)
        mp.setattr(s, "smtp_pass", "pw", raising=False)

        def hang(*a, **k):
            raise TimeoutError("timed out")

        mp.setattr(mailer.smtplib, "SMTP", hang)
        with pytest.raises(mailer.MailError) as caught:
            mailer.send_test("me@icloud.com", "https://x/", s)
    assert "Vercel" in str(caught.value) and "RESEND_API_KEY" in str(caught.value)


def test_http_transport_posts_to_resend(monkeypatch):
    """HTTP is the transport that works on Vercel -- stdlib, no SDK."""
    s = get_settings()
    monkeypatch.setattr(s, "resend_api_key", "re_abc", raising=False)
    monkeypatch.setattr(s, "mail_from", "invites@example.com", raising=False)
    seen = {}

    class _Resp:
        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["auth"] = req.headers.get("Authorization")
        seen["body"] = json.loads(req.data)
        return _Resp()

    monkeypatch.setattr(mailer.urllib.request, "urlopen", fake_urlopen)
    mailer.send_test("owner@example.com", "https://x/", s)

    assert seen["url"] == mailer.RESEND_ENDPOINT
    assert seen["auth"] == "Bearer re_abc"
    assert seen["body"]["from"] == "invites@example.com"
    assert seen["body"]["to"] == ["owner@example.com"]
