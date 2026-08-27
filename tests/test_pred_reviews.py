"""AI checks on the TD leans.

The contract worth defending: the model gets a say, never the pen. It can
disagree with a lean in its own labelled clause, and it cannot alter the
lean, the confidence, or introduce a player the page does not carry.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds import vegas
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "sync_token", "secret-token", raising=False)
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    yield TestClient(main.app), store
    main.app.dependency_overrides.clear()


def _known_player() -> str:
    return vegas.curated_predictions()[0]["name"]


# --- the endpoint ----------------------------------------------------------


async def test_review_requires_the_sync_token(client):
    c, _ = client
    assert c.post("/internal/pred-reviews", json={"reviews": {"X": "y"}}).status_code == 401


async def test_only_players_the_page_carries_are_kept(client):
    """The model cannot introduce a prediction row by naming someone."""
    c, store = client
    name = _known_player()

    response = c.post(
        "/internal/pred-reviews",
        json={"reviews": {name: "Implied total up 2 since the lean.", "Fake Person": "invented"}},
        headers={"X-Sync-Token": "secret-token"},
    )

    assert response.json() == {"stored": 1}
    saved = await store.load()
    assert set(saved["pred_reviews"]) == {name}


async def test_a_review_matching_nobody_is_rejected(client):
    c, _ = client
    response = c.post(
        "/internal/pred-reviews",
        json={"reviews": {"Nobody At All": "text"}},
        headers={"X-Sync-Token": "secret-token"},
    )
    assert response.status_code == 422


async def test_reviews_are_truncated_not_trusted(client):
    c, store = client
    response = c.post(
        "/internal/pred-reviews",
        json={"reviews": {_known_player(): "x" * 500}},
        headers={"X-Sync-Token": "secret-token"},
    )
    assert response.status_code == 200
    saved = await store.load()
    assert len(next(iter(saved["pred_reviews"].values()))) == feeds_route.MAX_REVIEW_CHARS


# --- applying them ---------------------------------------------------------


def test_a_review_appends_a_labelled_clause_and_changes_nothing_else():
    pred = {
        "name": "Josh Allen",
        "meta": "QB · BUF",
        "prop": "Passing TDs",
        "line": "1.5",
        "lean": "OVER",
        "conf": 78,
        "why": "Threw 2+ in 11 of 17.",
    }
    out = vegas.apply_reviews([pred], {"Josh Allen": "Implied total down 3 since the lean."})[0]

    assert out["why"] == "Threw 2+ in 11 of 17. AI check: Implied total down 3 since the lean."
    # The owner's call and its confidence are untouched.
    assert out["lean"] == "OVER"
    assert out["conf"] == 78


def test_rows_without_a_review_are_returned_unchanged():
    pred = {"name": "A", "why": "w", "lean": "OVER", "conf": 60}
    assert vegas.apply_reviews([pred], {"B": "note"})[0] == pred
    assert vegas.apply_reviews([pred], None)[0] == pred
    assert vegas.apply_reviews([pred], {"A": "   "})[0] == pred


# --- what gets sent to the model -------------------------------------------


def test_only_leans_with_a_posted_line_are_sent_for_review():
    """Without a live number there is nothing to check the lean against,
    and asking anyway invites the model to supply one from memory."""
    # BUF carries a curated lean (Josh Allen); no other game is posted, so
    # every other lean must drop out for want of a number to check.
    games = [{"game": "CAR @ BUF", "fav": "BUF -3", "total": "44.5"}]
    rows = vegas.lean_review_rows(games)

    assert rows, "expected the BUF lean to survive"
    assert {r["team"] for r in rows} <= {"CAR", "BUF"}
    assert all(isinstance(r["implied_team_total_now"], float) for r in rows)
    # The lean travels so the model can judge it -- but it is not asked to
    # return one, and the endpoint would ignore it if it did.
    assert {"player", "prop", "line", "lean"} <= set(rows[0])


# --- the forecast clause ----------------------------------------------------
# Same append-only contract as the AI check, and tested for the same
# reasons: the lean and the confidence belong to the owner, and a clause
# arrives already labelled with whose number it carries.


def test_a_forecast_appends_its_labelled_clause_and_changes_nothing_else():
    pred = {
        "name": "Josh Allen",
        "meta": "QB · BUF",
        "prop": "Passing TDs",
        "line": "1.5",
        "lean": "OVER",
        "conf": 78,
        "why": "Threw 2+ in 11 of 17.",
    }
    out = vegas.apply_forecasts(
        [pred], {"Josh Allen": "Wk 1 forecast: 1.7 passing tds (Rotowire via Sleeper)."}
    )[0]

    assert out["why"] == (
        "Threw 2+ in 11 of 17. Wk 1 forecast: 1.7 passing tds (Rotowire via Sleeper)."
    )
    assert out["lean"] == "OVER"
    assert out["conf"] == 78


def test_rows_without_a_forecast_are_returned_unchanged():
    pred = {"name": "A", "why": "w", "lean": "OVER", "conf": 60}
    assert vegas.apply_forecasts([pred], {"B": "note"})[0] == pred
    assert vegas.apply_forecasts([pred], None)[0] == pred
    assert vegas.apply_forecasts([pred], {"A": "   "})[0] == pred
