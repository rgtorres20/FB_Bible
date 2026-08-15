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
