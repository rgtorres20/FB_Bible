"""The Predictions tab's "more active" clauses (owner, Sep 3).

Each TD-lean row already carried the owner's why, the line move, the AI
check and Rotowire's TD forecast. Four more labelled facts now sit beside
them -- the newest wire item tagging the man, Sleeper's current flag, the
line beside the projected team TDs, and any starter out on that team with
the next man's projection. The lean and the confidence are never touched.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app import main
from app.feeds import injury
from app.feeds import players as players_mod
from app.feeds.store import FileFeedStore
from app.routes import feeds as feeds_route

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def _index():
    return {
        "players": {
            "1": {
                "id": "1",
                "name": "Josh Allen",
                "position": "QB",
                "team": "BUF",
                "injury_status": None,
                "rank": 1,
            },
            "5": {
                "id": "5",
                "name": "Tyreek Hill",
                "position": "WR",
                "team": "MIA",
                "injury_status": "Questionable",
                "rank": 3,
            },
        },
        "by_name": {"josh allen": "1", "tyreek hill": "5"},
        # The store refuses an index without the current stamp -- the
        # same guard that turns a stale-shape index into "no index".
        "v": players_mod.INDEX_VERSION,
    }


def _items():
    return [
        {
            "title": "Hill limited in practice with a hip issue",
            "published": "2026-09-04T15:00:00+00:00",
            "source_name": "ESPN NFL",
            "link": "https://espn.com/1",
            "players": [{"id": "5", "name": "Tyreek Hill"}],
        },
        {
            "title": "Allen signs extension",
            "published": "2026-08-01T15:00:00+00:00",
            "source_name": "ESPN NFL",
            "link": "https://espn.com/2",
            "players": [{"id": "1", "name": "Josh Allen"}],
        },
    ]


def test_the_wire_and_the_flag_ride_beside_the_lean():
    out = injury.lean_clauses(
        _items(), _index(), ("Tyreek Hill", "Josh Allen", "Nobody Known"), now=NOW
    )
    assert out["Tyreek Hill"] == (
        "Wire: Hill limited in practice with a hip issue (ESPN NFL, Fri Sep 4 · 10:00 AM). "
        "Sleeper flag: Questionable."
    )
    # A month-old story is not an alert, and a clear flag says nothing.
    assert "Josh Allen" not in out
    # A name the index cannot resolve gets nothing rather than something invented.
    assert "Nobody Known" not in out


def test_the_served_predictions_carry_the_new_clauses(tmp_path, monkeypatch):
    """End to end through the composer: the page's own TD-lean rows are
    re-injected with the wire, the flag, the line-vs-projection and the
    out-impact clauses appended -- and nothing else about the row moves."""
    import asyncio

    store = FileFeedStore(str(tmp_path / "feeds.json"))
    index = _index()
    # Josh Allen's row is a curated Passing TDs lean (the page's PREDICTIONS const).
    week = {
        "week": 1,
        "companies": ["rotowire"],
        "players": {"1": {"pass_td": 2.1, "rush_td": 0.4, "pass_yd": 280.0}},
    }
    vegas_state = {
        "fetched_at": NOW.isoformat(),
        "week_label": "Week 1",
        "games": [
            {
                "game": "MIA @ BUF",
                "fav": "BUF -3.5",
                "total": "48.5",
                "kickoff": "2026-09-13T17:00Z",
                "away_name": "Miami Dolphins",
                "home_name": "Buffalo Bills",
                "tv": "CBS",
                "imp": "",
                "read": "",
            }
        ],
    }
    asyncio.run(store.save({"items": _items(), "vegas": vegas_state, "week_projections": week}))
    asyncio.run(store.save_players(index))
    main.app.dependency_overrides[feeds_route.get_feed_store] = lambda: store
    main.app.dependency_overrides[feeds_route.get_optional_feed_store] = lambda: store
    try:
        served = TestClient(main.app).get("/app/").text
    finally:
        main.app.dependency_overrides.clear()
    assert "Vegas implies BUF 26" in served
    assert "projects BUF skill players for 0.4 TDs in Wk 1" in served
    # The lean itself is untouched: still the owner's OVER at its curated
    # confidence. The injected const is JSON, so the row reads with quoted keys.
    row = re.search(r'\{"name": "Josh Allen"[^}]*\}', served).group(0)
    assert '"prop": "Passing TDs", "line": "1.5", "lean": "OVER", "conf": 78' in row
    assert "Vegas implies BUF 26" in row
