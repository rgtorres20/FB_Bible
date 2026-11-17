"""The Gabbs Glamour demo is served as static files at /gabbs/, outside the gate."""

import re

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PAGES = ["", "book.html", "admin.html"]


def test_bare_path_redirects_to_slash():
    r = client.get("/gabbs", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/gabbs/"


def test_pages_and_their_local_assets_are_served():
    for page in PAGES:
        r = client.get("/gabbs/" + page)
        assert r.status_code == 200, page
        assert "Gabbs Glamour" in r.text, page
        # Every local script and stylesheet a page names must be served.
        refs = re.findall(r'(?:src|href)="\./([^"#?]+\.(?:js|css))"', r.text)
        assert "styles.css" in refs and "data.js" in refs, page
        for ref in refs:
            assert client.get("/gabbs/" + ref).status_code == 200, (page, ref)


def test_pages_link_each_other():
    home = client.get("/gabbs/").text
    assert "./book.html" in home and "./admin.html" in home
