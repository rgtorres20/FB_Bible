"""Every page this server renders has a way back to the app.

Owner, Aug 21: "after i pick the team no way to go back to homepage."

The team page did have a link — buried mid-sentence in a paragraph of
12px grey text — and six other pages had no way back at all. In the
installed PWA there is no address bar and no browser chrome either, so a
missed text link is a dead end with no exit.

This test is deliberately written as a property over a list of every
server-rendered page rather than one assertion per page, so a new board
cannot ship without an exit: adding the route and forgetting the bar
fails here.

It runs signed IN and signed OUT. The first version only signed in, and
the live watchdog caught what it missed: /app/mine and /app/leagues
render a separate "who are you?" page for a visitor with no session, and
that branch had no bar. A page that strands you is worse, not better,
when you have not signed in yet.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds import skin
from app.feeds.store import FileFeedStore
from app.routes import access as access_route
from app.routes import feeds as feeds_route

# Every page the server renders as a full document. /login is excluded on
# purpose: it is the way IN, and it is reached by people with no session
# to go back to.
SERVED_PAGES = skin.SERVED_PAGES


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
    c = TestClient(main.app)
    c.post("/login", data={"email": "owner@example.com", "code": "open-sesame"})
    yield c
    main.app.dependency_overrides.clear()


# The two pages that render a different document for a visitor with no
# session. The rest either need no session or are gated before they render.
SIGNED_OUT_PAGES = ("/app/mine", "/app/leagues")


@pytest.fixture
def anon(tmp_path, monkeypatch):
    """Same app, no sign-in -- the branch the signed-in fixture hides."""
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    s = get_settings()
    monkeypatch.setattr(s, "app_auth", False, raising=False)
    monkeypatch.setattr(s, "owner_email", "owner@example.com", raising=False)
    monkeypatch.setattr(s, "session_secret", "unit-test-secret", raising=False)
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    monkeypatch.setattr(access_route, "build_feed_store", lambda _s: store)
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


@pytest.mark.parametrize("path", SIGNED_OUT_PAGES)
def test_the_ask_to_sign_in_still_has_a_way_back(anon, path):
    page = anon.get(path).text
    assert "Sign in" in page, f"{path} did not render the signed-out branch"
    assert "class='fsb-home' href='/app/'" in page, path


@pytest.mark.parametrize("path", SERVED_PAGES)
def test_every_page_has_a_way_back_to_the_app(client, path):
    page = client.get(path).text
    assert "class='fsb-home' href='/app/'" in page, path


@pytest.mark.parametrize("path", SERVED_PAGES)
def test_the_way_back_names_where_you_are(client, path):
    """A bare arrow tells you there is an exit but not what you are
    leaving. Every bar carries the app name and the page's own."""
    page = client.get(path).text
    assert "Fantasy Sports Bible ·" in page, path


@pytest.mark.parametrize("path", SERVED_PAGES)
def test_every_page_carries_the_mark(client, path):
    """Owner, Aug 21: "my fab logo should be on all pages."

    It is two things on every page: the tab icon in the head, and the
    mark itself in the home bar. Both come from skin.head() now, because
    nine hand-written heads had already drifted -- the alert board had no
    favicon at all and the cheat sheet's empty-board branch had lost the
    one its full branch carried.
    """
    page = client.get(path).text
    assert "/app/assets/fsb-icon.svg" in page, f"{path} has no tab icon"
    assert "/app/assets/fsb-mark.svg" in page, f"{path} does not show the mark"


@pytest.mark.parametrize("path", SERVED_PAGES)
def test_every_page_boots_the_users_theme(client, path):
    """Found while fixing the logo: three pages never read ww_theme, so
    they rendered in the house navy whichever club the user had picked."""
    page = client.get(path).text
    assert "ww_theme" in page, f"{path} ignores the picked theme"


@pytest.mark.parametrize("path", SIGNED_OUT_PAGES)
def test_the_ask_to_sign_in_carries_the_mark_too(anon, path):
    page = anon.get(path).text
    assert "/app/assets/fsb-icon.svg" in page, path
    assert "/app/assets/fsb-mark.svg" in page, path


def test_the_bar_needs_no_stylesheet_of_its_own():
    """These pages do not share one stylesheet — the cheat sheet and the
    IDP board carry their own — so a nav that depended on the app's
    tokens would work on half of them, which is the original bug again."""
    bar = skin.home_bar("Somewhere")
    assert "style=" in bar and "border" in bar
    assert "var(--" not in bar


def test_the_bar_does_not_print():
    """The cheat sheet and the boards are printed the morning of a draft;
    a navigation button on paper is noise."""
    assert "@media print" in skin.home_bar()
    assert "display:none" in skin.home_bar()


def test_a_trailing_slash_reaches_the_page_instead_of_a_404(client):
    """Owner, Aug 25: "mystuff not working -- not found".

    Every one of the eleven pages 404'd on a trailing slash. Starlette
    redirects /path/ to /path when nothing matches, but the StaticFiles
    mount matches the /app PREFIX, so /app/mine/ IS matched -- by
    StaticFiles, which has no such file and answers 404. The redirect
    never runs.

    What made it bite rather than lurk: /app/ is itself a real page, so
    the app teaches people to type the slash, and a PWA or an autocomplete
    will add one unasked.

    Walked from skin.SERVED_PAGES rather than a list of its own -- a copy
    is how the next page added ships with the bug back.
    """
    for path in skin.SERVED_PAGES:
        resp = client.get(path + "/", follow_redirects=False)
        assert resp.status_code in (307, 308), f"{path}/ -> {resp.status_code}"
        assert resp.headers["location"] == path, f"{path}/ -> {resp.headers['location']}"


def test_the_slash_redirect_lands_somewhere_real(client):
    """A redirect to another 404 is not a fix. Follows it and checks the
    page actually answers -- 200, or the gate's own redirect for a page
    that needs a sign-in, never 404."""
    for path in skin.SERVED_PAGES:
        resp = client.get(path + "/", follow_redirects=True)
        assert resp.status_code != 404, f"{path}/ still ends at a 404"


# --- nothing gated is cacheable (Sep 1) ------------------------------------
#
# Production sits behind Cloudflare's proxy (docs/PRODUCTIZE.md records the
# orange-cloud divergence), and every gated response shipped with no
# Cache-Control at all -- leaving the caching decision to whoever sits in
# the path. A cached feeds.json is one reader's old wire served to everyone
# behind that cache; the page then falls back to its Aug-14 seed constants
# and every tab looks dead while the server is fresh.


@pytest.mark.parametrize("path", SERVED_PAGES)
def test_every_served_page_refuses_to_be_cached(client, path):
    response = client.get(path)
    assert response.headers.get("cache-control") == "no-store", path


def test_the_overlay_data_refuses_to_be_cached(client):
    """The one response whose staleness broke three tabs at once."""
    response = client.get("/app/data/feeds.json")
    assert response.headers.get("cache-control") == "no-store"


def test_the_gates_refusal_refuses_to_be_cached(tmp_path, monkeypatch):
    """A cached 401 keeps turning away signed-in readers for as long as it
    lives, which is the same poison in the other direction."""
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    s = get_settings()
    monkeypatch.setattr(s, "app_auth", True, raising=False)
    monkeypatch.setattr(s, "owner_email", "owner@example.com", raising=False)
    monkeypatch.setattr(s, "app_owner_code", "open-sesame", raising=False)
    monkeypatch.setattr(s, "session_secret", "unit-test-secret", raising=False)
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    monkeypatch.setattr(access_route, "build_feed_store", lambda _s: store)
    stranger = TestClient(main.app)
    try:
        refused = stranger.get("/app/data/feeds.json")
        assert refused.status_code == 401
        assert refused.headers.get("cache-control") == "no-store"
        redirected = stranger.get("/app/", headers={"accept": "text/html"}, follow_redirects=False)
        assert redirected.status_code == 303
        assert redirected.headers.get("cache-control") == "no-store"
    finally:
        main.app.dependency_overrides.clear()


def test_the_public_brand_assets_stay_cacheable(client):
    """The four public paths carry no user data and no freshness claims;
    teams.css declares its own hour and the middleware must not take it
    away."""
    css = client.get("/app/teams.css")
    assert css.headers.get("cache-control") == "public, max-age=3600"
    manifest = client.get("/app/manifest.webmanifest")
    assert manifest.headers.get("cache-control") != "no-store"
