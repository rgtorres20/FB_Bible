"""The solitaire game is served as static files at /solitaire/, outside the gate."""

import re

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_bare_path_redirects_to_slash():
    r = client.get("/solitaire", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/solitaire/"


def test_page_and_its_assets_are_served():
    r = client.get("/solitaire/")
    assert r.status_code == 200
    assert "<title>Solitaire</title>" in r.text
    # Every script and stylesheet the page names must actually be served.
    refs = re.findall(r'(?:src|href)="\./(assets/[^"]+)"', r.text)
    assert refs
    for ref in refs:
        assert client.get("/solitaire/" + ref).status_code == 200, ref
    assert client.get("/solitaire/manifest.webmanifest").status_code == 200
