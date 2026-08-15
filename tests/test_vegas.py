"""Vegas lines: ESPN scoreboard parsing and the honest-read rule.

Contract under test: spreads and totals come through as the page's table
shape, implied points are arithmetic (not judgement), the read column only
ever carries facts (kickoff times, slate superlatives), and a broken event
or a zero-game payload degrades exactly like every other source.
"""

from __future__ import annotations

import httpx
import pytest

from app.feeds import vegas


def _event(away: str, home: str, details: str | None, over_under: float | None) -> dict:
    odds = {}
    if details is not None:
        odds["details"] = details
    if over_under is not None:
        odds["overUnder"] = over_under
    return {
        "date": "2026-08-15T17:00Z",
        "competitions": [
            {
                "competitors": [
                    {"homeAway": "home", "team": {"abbreviation": home}},
                    {"homeAway": "away", "team": {"abbreviation": away}},
                ],
                "odds": [odds] if odds else [],
            }
        ],
    }


def test_implied_points_are_arithmetic():
    fav, imp = vegas.implied("BUF -4", 44.0)
    assert fav == "BUF -4"
    assert imp == "BUF 24 · opp 20"


def test_non_spread_details_pass_through_without_fake_math():
    assert vegas.implied("EVEN", 44.0) == ("EVEN", "—")
    assert vegas.implied("", 44.0) == ("—", "—")
    assert vegas.implied("BUF -4", None) == ("BUF -4", "—")


def test_build_rows_shapes_games_and_annotates_superlatives():
    payload = {
        "events": [
            _event("CAR", "BUF", "BUF -3", 38.5),
            _event("CLE", "CHI", "CLE -7", 51.5),
            _event("MIN", "NYG", None, None),
            {"competitions": [{}]},  # malformed: skipped, not fatal
        ]
    }
    rows = vegas.build_rows(payload)

    assert [r["game"] for r in rows] == ["CAR @ BUF", "CLE @ CHI", "MIN @ NYG"]
    by_game = {r["game"]: r for r in rows}
    assert by_game["MIN @ NYG"]["fav"] == "—"
    assert by_game["MIN @ NYG"]["total"] == "—"
    assert "Lowest total" in by_game["CAR @ BUF"]["read"]
    assert "Highest total" in by_game["CLE @ CHI"]["read"]
    assert "Heaviest favorite" in by_game["CLE @ CHI"]["read"]
    # Reads are kickoff times and slate facts -- never betting advice.
    assert "CT" in by_game["MIN @ NYG"]["read"]
    assert not any("_ou" in r for r in rows)


async def test_fetch_raises_on_empty_scoreboard():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"events": []}))
    ) as client:
        with pytest.raises(ValueError, match="0 parseable"):
            await vegas.fetch(client)


async def test_fetch_labels_the_week():
    payload = {
        "week": {"number": 2},
        "season": {"type": 1},
        "events": [_event("CAR", "BUF", "BUF -3", 38.5)],
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    ) as client:
        state = await vegas.fetch(client)
    assert state["week_label"] == "Preseason Week 2"
    assert state["games"][0]["game"] == "CAR @ BUF"


# --- /internal/vegas push endpoint -----------------------------------------


from fastapi.testclient import TestClient  # noqa: E402

from app import main as _main  # noqa: E402
from app.config import get_settings as _get_settings  # noqa: E402
from app.feeds.store import FileFeedStore as _FileFeedStore  # noqa: E402
from app.routes import feeds as _feeds_route  # noqa: E402


@pytest.fixture
def push_client(tmp_path, monkeypatch):
    monkeypatch.setattr(_get_settings(), "sync_token", "secret-token", raising=False)
    store = _FileFeedStore(str(tmp_path / "feeds.json"))
    _main.app.dependency_overrides[_feeds_route.get_feed_store] = lambda: store
    yield TestClient(_main.app), store
    _main.app.dependency_overrides.clear()


async def test_vegas_push_requires_token(push_client):
    c, _ = push_client
    response = c.post("/internal/vegas", json={"state": {"games": [{"game": "A @ B"}]}})
    assert response.status_code == 401


async def test_vegas_push_sanitizes_rows_to_known_string_fields(push_client):
    """Pushed rows render into the page, so only the five known columns may
    pass -- injected extra keys and non-dict rows must be dropped."""
    c, store = push_client
    response = c.post(
        "/internal/vegas",
        json={
            "state": {
                "week_label": "Preseason Week 2",
                "games": [
                    {"game": "CAR @ BUF", "fav": "BUF -3", "total": 38.5, "evil": {"x": 1}},
                    {"fav": "no game key"},
                    "not-a-dict",
                ],
            }
        },
        headers={"X-Sync-Token": "secret-token"},
    )

    assert response.json() == {"stored": 1, "week_label": "Preseason Week 2"}
    saved = await store.load()
    row = saved["vegas"]["games"][0]
    assert set(row) == {"game", "fav", "total", "imp", "read"}
    assert row["total"] == "38.5"  # coerced to string


async def test_vegas_push_rejects_empty_slate(push_client):
    c, _ = push_client
    response = c.post(
        "/internal/vegas",
        json={"state": {"games": []}},
        headers={"X-Sync-Token": "secret-token"},
    )
    assert response.status_code == 422


async def test_pushed_slate_survives_a_sync_whose_fetch_fails(push_client, monkeypatch):
    """The whole architecture: GitHub pushes lines, Vercel's own fetch 403s,
    the sync must carry the pushed slate forward instead of blanking it."""
    import httpx as _httpx

    c, store = push_client

    async def _offline(*args, **kwargs):
        raise _httpx.ConnectError("espn 403 / offline")

    monkeypatch.setattr(_feeds_route.adp, "fetch", _offline)
    monkeypatch.setattr(_feeds_route.vegas, "fetch", _offline)

    async def fake_poll(*args, **kwargs):
        return {"items": [], "sources": {}, "polled_at": "2026-08-15T15:00:00+00:00"}

    monkeypatch.setattr(_feeds_route.poller, "poll", fake_poll)

    c.post(
        "/internal/vegas",
        json={"state": {"week_label": "W", "games": [{"game": "CAR @ BUF", "fav": "BUF -3"}]}},
        headers={"X-Sync-Token": "secret-token"},
    )
    body = c.post("/internal/sync", headers={"X-Sync-Token": "secret-token"}).json()

    assert body["vegas_games"] == 1
    saved = await store.load()
    assert saved["vegas"]["games"][0]["game"] == "CAR @ BUF"
