"""AI matchup previews for the Week 1 schedule tab.

The contract: the work list carries only numbers we hold (the pushed
line, the '25 offense profiles) and skips games with neither; a stored
preview survives until its line genuinely moves; the endpoint admits only
games the slate holds; and the prose renders as a labelled "AI preview:"
clause beside the owner's note, never blended into it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds import previews, vegas
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route


def _slate() -> dict:
    return {
        "fetched_at": "2026-08-18T20:00:00+00:00",
        "week_label": "Week 1",
        "games": [
            {
                "game": "DAL @ PHI",
                "fav": "PHI -7.0",
                "total": "47.5",
                "kickoff": "2026-09-10T00:20Z",
                "away_name": "Dallas Cowboys",
                "home_name": "Philadelphia Eagles",
                "tv": "NBC",
                "imp": "",
                "read": "",
            },
            {
                "game": "KC @ LAC",
                "fav": "KC -3.5",
                "total": "44.5",
                "kickoff": "2026-09-13T17:00Z",
                "away_name": "Kansas City Chiefs",
                "home_name": "Los Angeles Chargers",
                "tv": "CBS",
                "imp": "",
                "read": "",
            },
        ],
    }


def _stats() -> dict:
    team = {
        "pass_att": 600,
        "rush_att": 400,
        "pass_rz_att": 60,
        "rush_rz_att": 40,
        "rz_att": 55,
        "rz_conv": 33,
    }
    return {"teams": {code: dict(team) for code in ("DAL", "PHI", "KC", "LAC")}}


# --- the work list ---------------------------------------------------------


def test_pending_carries_the_line_and_both_profiles():
    work = previews.pending(_slate(), _stats(), {})
    assert [w["game"] for w in work] == ["DAL @ PHI", "KC @ LAC"]
    game = work[0]
    assert game["fav"] == "PHI -7.0" and game["total"] == "47.5"
    # Implied points recomputed from fav + total, both sides named.
    assert game["teams"]["PHI"]["implied_points"] == 27.2
    assert game["teams"]["DAL"]["implied_points"] == 20.3
    profile = game["teams"]["DAL"]["offense_2025"]
    assert profile == {
        "pass_rate_pct": 60,
        "rz_run_share_pct": 40,
        "rz_trips": 55,
        "rz_td_pct": 60,
    }


def test_pending_sends_nothing_for_a_team_we_did_not_measure():
    stats = _stats()
    del stats["teams"]["DAL"]["rush_att"]  # incomplete aggregates
    work = previews.pending(_slate(), stats, {})
    assert "offense_2025" not in work[0]["teams"]["DAL"]
    assert "offense_2025" in work[0]["teams"]["PHI"]


def test_a_preview_covers_until_the_line_moves():
    stored = {"DAL @ PHI": {"text": "Preview.", "total": "47.5", "fav": "PHI -7.0"}}
    assert [w["game"] for w in previews.pending(_slate(), _stats(), stored)] == ["KC @ LAC"]

    # The total drifting a full point re-queues the game...
    moved = _slate()
    moved["games"][0]["total"] = "48.5"
    assert "DAL @ PHI" in [w["game"] for w in previews.pending(moved, _stats(), stored)]

    # ...and so does the favorite flipping, even at the same total.
    flipped = _slate()
    flipped["games"][0]["fav"] = "DAL -7.0"
    assert "DAL @ PHI" in [w["game"] for w in previews.pending(flipped, _stats(), stored)]


# --- acceptance ------------------------------------------------------------


def test_accept_admits_only_slate_games_and_snapshots_the_line():
    accepted = previews.accept(
        {"DAL @ PHI": "Market likes the Eagles.", "FAKE @ GAME": "Invented."},
        _slate(),
        {"OLD @ GONE": {"text": "Left the slate.", "total": "40", "fav": ""}},
    )
    assert set(accepted) == {"DAL @ PHI"}
    assert accepted["DAL @ PHI"] == {
        "text": "Market likes the Eagles.",
        "total": "47.5",
        "fav": "PHI -7.0",
    }


def test_accept_caps_length():
    accepted = previews.accept({"DAL @ PHI": "x" * 500}, _slate(), {})
    assert len(accepted["DAL @ PHI"]["text"]) == previews.MAX_CHARS


# --- rendering -------------------------------------------------------------


def test_schedule_note_carries_the_labelled_preview():
    stored = {"KC @ LAC": {"text": "'25 profiles lean run.", "total": "44.5", "fav": "KC -3.5"}}
    rows = vegas.schedule_rows(
        _slate(),
        curated={"Kansas City Chiefs @ Los Angeles Chargers": {"note": "Owner note."}},
        previews=previews.by_matchup(_slate(), stored),
    )
    kc = next(r for r in rows if r["away"] == "Kansas City Chiefs")
    assert kc["note"] == "Owner note. AI preview: '25 profiles lean run."
    dal = next(r for r in rows if r["away"] == "Dallas Cowboys")
    assert "AI preview:" not in dal["note"]


# --- the endpoints ---------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "sync_token", "secret-token", raising=False)
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    yield TestClient(main.app), store
    main.app.dependency_overrides.clear()


async def test_save_requires_the_sync_token(client):
    c, _ = client
    assert c.post("/internal/previews", json={"previews": {"X": "y"}}).status_code == 401


async def test_save_keeps_slate_games_and_rejects_everyone_else(client):
    c, store = client
    await store.save({"items": [], "vegas": _slate()})

    response = c.post(
        "/internal/previews",
        json={"previews": {"DAL @ PHI": "Market likes the Eagles.", "FAKE @ GAME": "invented"}},
        headers={"X-Sync-Token": "secret-token"},
    )
    assert response.json() == {"stored": 1}

    rejected = c.post(
        "/internal/previews",
        json={"previews": {"FAKE @ GAME": "only invented games"}},
        headers={"X-Sync-Token": "secret-token"},
    )
    assert rejected.status_code == 422


async def test_pending_endpoint_serves_the_work_list(client):
    c, store = client
    await store.save({"items": [], "vegas": _slate(), "stats": _stats()})
    payload = c.get("/api/previews/pending").json()
    assert [g["game"] for g in payload["games"]] == ["DAL @ PHI", "KC @ LAC"]
