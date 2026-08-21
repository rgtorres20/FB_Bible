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
SERVED_PAGES = (
    "/app/mine",
    "/app/leagues",
    "/app/mock",
    "/app/mock/board",
    "/app/nextup",
    "/app/scorecard",
    "/app/idp",
    "/app/cheatsheet",
    "/app/alerts300",
)


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
