"""The consolidated hourly annotation call.

The contract: four surfaces travel as sections of one request (quota is
the scarce resource, runner time is not); a section the model was not
given is ignored even if it answers one; and the lean work list -- the
only one re-reviewed every hour by design -- is assembled server-side
like all the others.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route
from scripts import annotate


def test_clean_reply_keeps_only_sections_that_were_asked_about():
    work = {"capsules": [{"id": "1001"}], "td_leans": [{"player": "A"}]}
    reply = {
        "capsules": {"1001": "A line.", "1002": 42, "1003": "   "},
        "td_leans": {"A": "Supports the lean."},
        "game_previews": {"X @ Y": "Never asked for this section."},
        "adp_movers": "not even a dict",
    }
    cleaned = annotate.clean_reply(reply, work)
    assert cleaned == {
        "capsules": {"1001": "A line."},
        "td_leans": {"A": "Supports the lean."},
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "sync_token", "secret-token", raising=False)
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    yield TestClient(main.app), store
    main.app.dependency_overrides.clear()


async def test_every_section_names_a_real_pending_route(client):
    """The section table is the coupling point with the API -- a renamed
    route must fail here, not silently return empty work forever."""
    c, store = client
    await store.save({"items": []})
    for section in annotate.SECTIONS:
        response = c.get(section["get"])
        assert response.status_code == 200, section
        assert section["items"] in response.json(), section


async def test_leans_pending_serves_rows_with_live_totals(client):
    c, store = client
    await store.save(
        {
            "items": [],
            "vegas": {"games": [{"game": "CAR @ BUF", "fav": "BUF -3", "total": "44.5"}]},
        }
    )
    leans = c.get("/api/leans/pending").json()["leans"]
    assert leans and {r["team"] for r in leans} <= {"CAR", "BUF"}
    assert all(isinstance(r["implied_team_total_now"], float) for r in leans)


async def test_leans_pending_is_empty_without_a_slate(client):
    c, store = client
    await store.save({"items": []})
    assert c.get("/api/leans/pending").json() == {"leans": []}
