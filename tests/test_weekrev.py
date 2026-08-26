"""The Week review tab going live.

The contract: games are real scores from the current-week scoreboard with
FINAL/clock/kickoff status and the broadcast as the only note; the
high-performer column stays the page's own curated reads, parsed from the
seed; and when either half is missing, no weekrev is served at all -- the
page keeps its complete seed rather than showing live games beside an
empty column.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.feeds import render, weekrev
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route


def _event(state: str, away: str, home: str, ascore: str = "", hscore: str = "") -> dict:
    return {
        "date": "2026-08-21T00:20Z",
        "status": {"type": {"state": state, "shortDetail": "Q3 5:22" if state == "in" else ""}},
        "competitions": [
            {
                "competitors": [
                    {"homeAway": "away", "score": ascore, "team": {"abbreviation": away}},
                    {"homeAway": "home", "score": hscore, "team": {"abbreviation": home}},
                ],
                "broadcasts": [{"names": ["NFLN"]}],
            }
        ],
    }


def _payload() -> dict:
    return {
        "week": {"number": 2},
        "season": {"type": 1},
        "events": [
            _event("post", "PIT", "GB", "28", "9"),
            _event("in", "CIN", "DET", "16", "14"),
            _event("pre", "DAL", "SEA"),
        ],
    }


# --- game rows ---------------------------------------------------------------


def test_finals_live_and_upcoming_render_their_own_shapes():
    games = weekrev.build_games(_payload())
    assert games[0]["score"] == "PIT 28 · GB 9" and games[0]["status"] == "FINAL"
    assert games[1]["score"] == "CIN 16 · DET 14" and games[1]["status"] == "Q3 5:22"
    assert games[2]["score"] == "DAL @ SEA" and games[2]["status"].endswith("CT")
    # The note is the broadcast -- a fact -- never invented analysis.
    assert all(g["note"] == "NFLN" for g in games)
    # Kickoffs render in Central: 00:20Z on Aug 21 is the evening of Aug 20.
    assert games[0]["day"] == "Thu Aug 20"


# --- the curated column ------------------------------------------------------


def test_stars_parse_from_the_pages_own_seed():
    stars = weekrev.curated_stars()
    assert len(stars) >= 5
    assert all({"name", "meta", "line", "read", "src"} <= set(s) for s in stars)


# --- gating ------------------------------------------------------------------


def test_no_weekrev_without_both_halves():
    scores = {"week_label": "Preseason Week 2", "range": "x", "games": [{"score": "a"}]}
    assert weekrev.build(scores, stars=[]) is None  # no stars: keep the seed
    assert weekrev.build({"games": []}, stars=[{"name": "x"}]) is None  # no games
    built = weekrev.build(scores, stars=[{"name": "x"}])
    assert built and built["week"] == "Preseason Week 2"


def test_overlay_serves_weekrev_and_renames_the_leagues():
    scores = {
        "week_label": "Preseason Week 2",
        "range": "Thu Aug 20 – Sun Aug 23",
        "games": [{"day": "d", "score": "PIT 28 · GB 9", "status": "FINAL", "note": ""}],
    }
    merged = render.merge_into_feeds(
        {"news": []},
        [{"id": "a", "title": "t", "summary": "", "published": "2026-08-20T01:00:00+00:00"}],
        datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        scores_state=scores,
    )
    assert merged["weekrev"]["games"][0]["score"] == "PIT 28 · GB 9"
    # The stars came from the page's seed, and the rename pass speaks the
    # real league names even inside those curated reads.
    renamed = render.rename_leagues(merged)
    text = str(renamed["weekrev"]["stars"])
    assert "Trenches" not in text and "Gravy" not in text


# --- the endpoint ------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "sync_token", "secret-token", raising=False)
    store = FileFeedStore(str(tmp_path / "feeds.json"))
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    yield TestClient(main.app), store
    main.app.dependency_overrides.clear()


async def test_scores_endpoint_sanitizes_and_stores(client):
    c, store = client
    assert c.post("/internal/scores", json={"state": {"games": []}}).status_code == 401

    response = c.post(
        "/internal/scores",
        json={
            "state": {
                "week_label": "Preseason Week 2",
                "range": "Thu – Sun",
                "games": [
                    {
                        "day": "Thu Aug 20",
                        "score": "PIT 28 · GB 9",
                        "status": "FINAL",
                        "note": "NFLN",
                        "extra": {"nested": "dropped"},
                    },
                    {"no_score": "skipped"},
                ],
            }
        },
        headers={"X-Sync-Token": "secret-token"},
    )
    assert response.json()["stored"] == 1
    saved = (await store.load())["scores"]
    assert saved["games"] == [
        {"day": "Thu Aug 20", "score": "PIT 28 · GB 9", "status": "FINAL", "note": "NFLN"}
    ]
    assert saved["week_label"] == "Preseason Week 2"


# --- how old is this? ------------------------------------------------------


def test_a_fresh_scoreboard_reports_when_it_was_pulled():
    """Owner, Aug 26: the tab "stayed on week 1 even though week 2". It
    had no way to say how old it was in either direction."""
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 8, 26, 2, 0, tzinfo=UTC)
    state = {"fetched_at": (now - timedelta(hours=2)).isoformat()}

    assert weekrev.stamp(state, now) == "scores pulled Tue Aug 25"


def test_a_scoreboard_older_than_its_own_week_says_so_in_words():
    """A scoreboard describes one week, so an old one is not a stale copy
    of this week — it is last week wearing this week's heading."""
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 8, 26, 2, 0, tzinfo=UTC)
    state = {"fetched_at": (now - timedelta(days=12)).isoformat()}

    assert "OLDER THAN A WEEK" in weekrev.stamp(state, now)


def test_no_pull_time_reports_nothing_rather_than_guessing():
    """An empty stamp is what makes the page print "stored review — no
    live scoreboard" instead of inventing a date."""
    assert weekrev.stamp({}) == ""
    assert weekrev.stamp({"fetched_at": "not a timestamp"}) == ""


def test_the_built_object_carries_the_stamp_for_the_page():
    from datetime import UTC, datetime

    now = datetime(2026, 8, 26, 2, 0, tzinfo=UTC)
    built = weekrev.build(
        {"fetched_at": now.isoformat(), "games": [{"day": "x"}], "week_label": "Preseason Week 3"},
        stars=[{"name": "x"}],
        now=now,
    )

    assert built["stamp"].startswith("scores pulled")
